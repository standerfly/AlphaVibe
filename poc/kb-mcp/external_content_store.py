"""外部內容知識庫（獨立資料庫 `external_content.db`；012 data-model.md）。

比照 `article_store.py` 的慣例，**不 import 任何投資、美股、文章或相簿模組**。

必須遵守的既有教訓：
1. `sqlite3.connect()` 帶 `check_same_thread=False`；
2. `__init__()` **不得有任何資料寫入副作用**（建表以外一律不寫）。

本檔目前只含地基：schema、`open_readonly`、`_tx()`（BEGIN IMMEDIATE＋失敗 rollback）、`_audit()`。
業務寫入方法（入庫、取代、摘要、軟刪除）留給後續階段，一律用 `_tx()` 讓資料與稽核同一交易。
"""
import contextlib
import datetime
import json
import os
import re
import sqlite3

import external_content_identity as identity

DB_FILENAME = "external_content.db"

SOURCE_TYPES = ("youtube", "podcast", "article")
SUMMARY_STATUSES = ("confirmed", "revoked")
AUDIT_ACTIONS = ("import", "replace", "delete", "summary_confirm", "summary_revise", "summary_revoke")
CHANNELS = ("http", "stdio")

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 30
SNIPPET_RADIUS = 60
MAX_SNIPPETS = 2

# 空白判斷：SQLite 的 trim() 預設只去空格，故明確加上 tab／LF／CR。
# published_on 格式：資料庫層只擋形狀（YYYY-MM-DD），真實日曆日期（例如 2026-02-30）由業務層驗證。
SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('youtube','podcast','article')),
    url TEXT NOT NULL CHECK (length(trim(url, ' ' || char(9, 10, 13))) > 0),
    title TEXT NOT NULL CHECK (length(trim(title, ' ' || char(9, 10, 13))) > 0),
    author TEXT NOT NULL CHECK (length(trim(author, ' ' || char(9, 10, 13))) > 0),
    published_on TEXT NOT NULL
        CHECK (published_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    body TEXT NOT NULL CHECK (length(trim(body, ' ' || char(9, 10, 13))) > 0),
    body_sha256 TEXT NOT NULL,
    guid TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_content_body_sha256 ON content(body_sha256);
CREATE INDEX IF NOT EXISTS idx_content_published_on ON content(published_on);

CREATE TABLE IF NOT EXISTS summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content(id),
    text TEXT NOT NULL CHECK (length(trim(text, ' ' || char(9, 10, 13))) > 0),
    status TEXT NOT NULL CHECK (status IN ('confirmed','revoked')),
    confirmed_at TEXT NOT NULL,
    po_quote TEXT NOT NULL CHECK (length(trim(po_quote, ' ' || char(9, 10, 13))) > 0)
);
CREATE INDEX IF NOT EXISTS idx_summary_content_id ON summary(content_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('http','stdio')),
    action TEXT NOT NULL CHECK (action IN
        ('import','replace','delete','summary_confirm','summary_revise','summary_revoke')),
    content_id INTEGER,
    detail TEXT NOT NULL
);
"""


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


class ContentValidationError(ValueError):
    """入庫欄位驗證失敗（訊息為繁體中文具體原因）。"""


_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ExternalContentStore(object):
    def __init__(self, data_dir, now=None):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, DB_FILENAME)
        self._now = now or _utc_now
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # 刻意不寫入任何資料列

    @classmethod
    def open_readonly(cls, data_dir):
        """以 SQLite 唯讀模式（mode=ro）開啟既有 external_content.db，給 MCP 查詢用。

        不建目錄、不建表、不寫任何東西；庫不存在就明確報錯而不是建立空庫。"""
        path = os.path.join(os.path.abspath(data_dir), DB_FILENAME)
        if not os.path.isfile(path):
            raise FileNotFoundError("外部內容庫尚未建立（找不到 %s），尚無已匯入的內容" % DB_FILENAME)
        self = cls.__new__(cls)
        self.data_dir = os.path.abspath(data_dir)
        self.db_path = path
        self._now = _utc_now
        self.conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23"),
                                    uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        return self

    def close(self):
        self.conn.close()

    def now(self):
        return _aware(self._now())

    def now_iso(self):
        return self.now().astimezone(datetime.timezone.utc).isoformat()

    @contextlib.contextmanager
    def _tx(self):
        """寫入交易：BEGIN IMMEDIATE 先取得寫入鎖；區塊正常結束 commit，例外則 rollback 並重新拋出。"""
        if self.conn.in_transaction:
            raise RuntimeError("_tx() 不可巢狀使用")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _audit(self, action, content_id, channel, detail):
        """寫一列稽核。只能在 `_tx()` 內呼叫（與資料同一交易）；detail 以 JSON 字串存，不得含全文。"""
        if not self.conn.in_transaction:
            raise RuntimeError("_audit() 只能在 _tx() 內呼叫")
        self.conn.execute(
            "INSERT INTO audit_log (ts, channel, action, content_id, detail) VALUES (?,?,?,?,?)",
            (self.now_iso(), channel, action, content_id,
             json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)))

    # ------------------------------------------------------------ 入庫（US1）

    def find_by_source_key(self, source_key):
        """以 source_key 找既有內容（已軟刪除者 key 已被改名，不會命中）；回 dict（不含全文）或 None。"""
        r = self.conn.execute(
            "SELECT id, source_key, source_type, title, author, published_on, url, body_sha256 "
            "FROM content WHERE source_key = ?", (source_key,)).fetchone()
        return dict(r) if r else None

    def _same_body_elsewhere(self, sha, exclude_key):
        rows = self.conn.execute(
            "SELECT id, title FROM content WHERE body_sha256 = ? AND source_key != ? AND deleted_at IS NULL "
            "ORDER BY id", (sha, exclude_key)).fetchall()
        return [{"id": r["id"], "title": r["title"]} for r in rows]

    def add_content(self, source_type, url, title, author, published_on, body, guid=None,
                    channel="stdio", filename=None):
        """入庫核心（資料匣與 import_text 共用）。

        順序：驗必填與格式 → 以 source_key 判重複 → 驗內文非空 → 算雜湊 → 單一交易寫 content＋audit(import)。
        回 {"status": "imported", "id", "title", "source_key", "same_body_elsewhere": [...]}；
        重複回 {"status": "duplicate", "existing": {...}, "source_key"} 且不寫入。
        驗證失敗丟 ContentValidationError（含 identity.IdentityError 的原因）。
        稽核 detail 只放 source_key、標題、檔名，不含全文。"""
        if source_type not in SOURCE_TYPES:
            raise ContentValidationError("source_type 必須是 %s 其中之一" % "、".join(SOURCE_TYPES))
        if channel not in CHANNELS:
            raise ContentValidationError("channel 必須是 http 或 stdio")
        vals = {}
        for name, v in (("url", url), ("title", title), ("author", author)):
            if not isinstance(v, str) or not v.strip():
                raise ContentValidationError("缺少必填欄位：%s" % name)
            vals[name] = v.strip()
        if not isinstance(published_on, str) or not _DATE_SHAPE_RE.match(published_on.strip()):
            raise ContentValidationError("date 格式必須是 YYYY-MM-DD")
        published_on = published_on.strip()
        try:
            datetime.date.fromisoformat(published_on)
        except ValueError:
            raise ContentValidationError("date 不是真實的日曆日期：%s" % published_on)
        guid = guid.strip() if isinstance(guid, str) and guid.strip() else None
        try:
            key = identity.source_key(vals["url"], source_type, guid)
        except identity.IdentityError as e:
            raise ContentValidationError(str(e))

        existing = self.find_by_source_key(key)
        if existing:
            return {"status": "duplicate", "source_key": key, "existing": existing}

        if not isinstance(body, str) or not body.strip():
            raise ContentValidationError("內文為空")
        sha = identity.body_sha256(body)
        now = self.now_iso()
        try:
            with self._tx() as c:
                cur = c.execute(
                    "INSERT INTO content (source_key, source_type, url, title, author, published_on, body, "
                    "body_sha256, guid, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (key, source_type, vals["url"], vals["title"], vals["author"], published_on, body,
                     sha, guid, now, now))
                cid = cur.lastrowid
                detail = {"source_key": key, "title": vals["title"]}
                if filename:
                    detail["filename"] = filename
                self._audit("import", cid, channel, detail)
        except sqlite3.IntegrityError:
            existing = self.find_by_source_key(key)     # 兩端同時匯入：UNIQUE 先到先贏
            if existing:
                return {"status": "duplicate", "source_key": key, "existing": existing}
            raise
        return {"status": "imported", "id": cid, "title": vals["title"], "source_key": key,
                "same_body_elsewhere": self._same_body_elsewhere(sha, key)}

    # ------------------------------------------------------------ 查詢（US2；唯讀連線也可用）

    @staticmethod
    def _like_pattern(keyword):
        esc = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "%" + esc + "%"

    @staticmethod
    def _snippets(text, keywords, radius=SNIPPET_RADIUS, max_segments=MAX_SNIPPETS):
        """每個關鍵字取第一次出現處的前後 radius 字；重疊的片段不重複；最多 max_segments 段。"""
        low = text.lower()
        spans = []
        for kw in keywords:
            idx = low.find(kw.lower())
            if idx < 0:
                continue
            start, end = max(0, idx - radius), min(len(text), idx + len(kw) + radius)
            if any(start < e and end > s for s, e in spans):
                continue
            spans.append((start, end))
            if len(spans) >= max_segments:
                break
        spans.sort()
        return [("…" if s > 0 else "") + text[s:e].replace("\n", " ") + ("…" if e < len(text) else "")
                for s, e in spans]

    def _confirmed_summaries(self, content_id):
        rows = self.conn.execute(
            "SELECT id, text, confirmed_at FROM summary WHERE content_id = ? AND status = 'confirmed' "
            "ORDER BY id", (content_id,)).fetchall()
        return [{"summary_id": r["id"], "text": r["text"], "confirmed_at": r["confirmed_at"]} for r in rows]

    def search(self, query, source_type=None, limit=DEFAULT_SEARCH_LIMIT):
        """全文搜尋（標題＋內文，LIKE ESCAPE，空白切詞 AND）。排除軟刪除；日期新到舊。

        limit：None 或 <=0 用預設 10；超過 30 夾到 30。query 全空白、source_type 不合法、limit 非整數 → ValueError。
        每筆回 id／source_type／title／author／published_on／url／snippets／summary_count／summary_ids。"""
        keywords = (query or "").split() if isinstance(query, str) else []
        if not keywords:
            raise ValueError("query 不可為空，請給至少一個關鍵字")
        if source_type is not None and source_type not in SOURCE_TYPES:
            raise ValueError("source_type 必須是 %s 其中之一" % "、".join(SOURCE_TYPES))
        if limit is None:
            limit = DEFAULT_SEARCH_LIMIT
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit 必須是整數")
        if limit <= 0:
            limit = DEFAULT_SEARCH_LIMIT
        limit = min(limit, MAX_SEARCH_LIMIT)
        conds, params = ["deleted_at IS NULL"], []
        if source_type:
            conds.append("source_type = ?")
            params.append(source_type)
        for kw in keywords:
            pat = self._like_pattern(kw)
            conds.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
            params += [pat, pat]
        sql = ("SELECT id, source_type, title, author, published_on, url, body FROM content WHERE "
               + " AND ".join(conds) + " ORDER BY published_on DESC, id DESC LIMIT ?")
        params.append(limit)
        out = []
        for r in self.conn.execute(sql, params).fetchall():
            sums = self._confirmed_summaries(r["id"])
            out.append({
                "id": r["id"], "source_type": r["source_type"], "title": r["title"], "author": r["author"],
                "published_on": r["published_on"], "url": r["url"],
                "snippets": self._snippets(r["body"], keywords),
                "summary_count": len(sums), "summary_ids": [x["summary_id"] for x in sums]})
        return out

    def get(self, content_id, offset=0, length=None):
        """取單筆：中繼資料、body 的 [offset, offset+length) 字元範圍、總字數、已確認摘要。
        找不到或已軟刪除回 None（工具層轉 ToolError）；offset／length 為負或非整數 → ValueError；
        offset 超出總長回空字串並 offset_beyond_end=True。"""
        offset = 0 if offset is None else offset
        for name, v in (("offset", offset), ("length", length)):
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError("%s 必須是整數" % name)
            if v < 0:
                raise ValueError("%s 不可為負數" % name)
        r = self.conn.execute(
            "SELECT id, source_key, source_type, title, author, published_on, url, body, guid, "
            "created_at, updated_at FROM content WHERE id = ? AND deleted_at IS NULL", (content_id,)).fetchone()
        if not r:
            return None
        body = r["body"]
        total = len(body)
        end = total if length is None else min(total, offset + length)
        text = body[offset:end] if offset < total else ""
        return {
            "id": r["id"], "source_key": r["source_key"], "source_type": r["source_type"], "title": r["title"],
            "author": r["author"], "published_on": r["published_on"], "url": r["url"], "guid": r["guid"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "total_chars": total, "offset": offset, "returned_chars": len(text),
            "end": offset + len(text), "offset_beyond_end": offset >= total,
            "text": text, "summaries": self._confirmed_summaries(r["id"])}

    # ------------------------------------------------------------ 摘要（US3；FR-011/012）
    # 草稿永遠不入庫；本區只在 PO 同意後由 confirm_summary 工具呼叫。系統無法驗證 po_quote 真偽（遵循度保證）。

    @staticmethod
    def _need_text(name, v):
        if not isinstance(v, str) or not v.strip():
            raise ContentValidationError("%s 不可為空白" % name)
        return v

    def _live_content_title(self, content_id):
        r = self.conn.execute("SELECT title FROM content WHERE id = ? AND deleted_at IS NULL",
                              (content_id,)).fetchone()
        if not r:
            raise ContentValidationError("找不到 ID %s 的外部內容（不存在或已刪除）" % content_id)
        return r["title"]

    def _confirmed_summary_row(self, content_id, summary_id):
        if isinstance(summary_id, bool) or not isinstance(summary_id, int):
            raise ContentValidationError("summary_id 必須是整數")
        r = self.conn.execute("SELECT id FROM summary WHERE id = ? AND content_id = ? AND status = 'confirmed'",
                              (summary_id, content_id)).fetchone()
        if not r:
            raise ContentValidationError(
                "summary_id %d 不是內容 %d 的有效（已確認）摘要，可能屬於其他內容或已撤回" % (summary_id, content_id))

    def _insert_summary(self, c, content_id, text, po_quote):
        cur = c.execute(
            "INSERT INTO summary (content_id, text, status, confirmed_at, po_quote) VALUES (?,?,?,?,?)",
            (content_id, text, "confirmed", self.now_iso(), po_quote))
        return cur.lastrowid

    def add_summary(self, content_id, text, po_quote, channel="stdio"):
        """新增一則已確認摘要；單一交易（摘要＋audit summary_confirm）。
        audit detail 只含 summary_id、標題、po_quote，不含摘要全文或內容全文。"""
        self._need_text("摘要文字", text)
        self._need_text("PO 同意原話", po_quote)
        if channel not in CHANNELS:
            raise ContentValidationError("channel 必須是 http 或 stdio")
        with self._tx() as c:
            title = self._live_content_title(content_id)
            sid = self._insert_summary(c, content_id, text, po_quote)
            self._audit("summary_confirm", content_id, channel,
                        {"summary_id": sid, "title": title, "po_quote": po_quote})
        return {"summary_id": sid, "content_id": content_id, "title": title}

    def revise_summary(self, content_id, summary_id, text, po_quote, channel="stdio"):
        """同一交易內撤回舊則並新增新則（需新的原話）；任一步失敗整筆回滾。"""
        self._need_text("摘要文字", text)
        self._need_text("PO 同意原話", po_quote)
        if channel not in CHANNELS:
            raise ContentValidationError("channel 必須是 http 或 stdio")
        with self._tx() as c:
            title = self._live_content_title(content_id)
            self._confirmed_summary_row(content_id, summary_id)
            c.execute("UPDATE summary SET status = 'revoked' WHERE id = ?", (summary_id,))
            new_id = self._insert_summary(c, content_id, text, po_quote)
            self._audit("summary_revise", content_id, channel,
                        {"old_summary_id": summary_id, "new_summary_id": new_id, "summary_id": new_id,
                         "title": title, "po_quote": po_quote})
        return {"summary_id": new_id, "old_summary_id": summary_id, "content_id": content_id, "title": title}

    def revoke_summary(self, content_id, summary_id, po_quote, channel="stdio"):
        """撤回摘要：status 改 revoked，列保留供稽核；需 PO 原話（遵循度保證）。"""
        self._need_text("PO 同意原話", po_quote)
        if channel not in CHANNELS:
            raise ContentValidationError("channel 必須是 http 或 stdio")
        with self._tx() as c:
            title = self._live_content_title(content_id)
            self._confirmed_summary_row(content_id, summary_id)
            c.execute("UPDATE summary SET status = 'revoked' WHERE id = ?", (summary_id,))
            self._audit("summary_revoke", content_id, channel, {"summary_id": summary_id, "title": title, "po_quote": po_quote})
        return {"summary_id": summary_id, "content_id": content_id, "title": title}
