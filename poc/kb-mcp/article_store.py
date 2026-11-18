"""定錨文章庫（獨立資料庫 `articles.db`；010 data-model.md）。

**完全不 import 任何投資、美股或相簿模組**，比照 `flight_store.py`／`us_stock_store.py` 的先例——
只沿用慣例。文章庫不屬於台股或美股任一方，兩個 MCP 連接器唯讀查詢同一份（FR-015）。

兩個必須遵守的既有教訓（同 flight_store.py）：
1. `sqlite3.connect()` 帶 `check_same_thread=False`；
2. `__init__()` **不得有任何資料寫入副作用**。

額外的設計約束：
* **只增不刪**：本類別不提供任何 delete 方法；放棄的文章只改 status。
* **不寫殘缺全文**（FR-013）：`mark_fetched` 在內文過短時拒絕。
* **已 fetched 的文章不覆寫、不重複**（FR-003）。
* `last_error` 一律經 `investanchors_redact.safe_error`（FR-020）。
"""
import datetime
import hashlib
import json
import os
import re
import sqlite3

import article_id_time
import investanchors_limits
import investanchors_redact

DB_FILENAME = "articles.db"
TZ8 = datetime.timezone(datetime.timedelta(hours=8))
MIN_BODY_LEN = 200
SNIPPET_RADIUS = 60
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 30
URL_RE = re.compile(r"^https://(www\.)?investanchors\.com/user/vip_contents/\d+$")

STATUSES = ("discovered", "fetched", "failed", "abandoned", "skipped", "deferred")
PENDING_STATUSES = ("discovered", "failed")
MAX_TRANSCRIBE_ATTEMPTS = 3     # 2026-11-15 審查決定：自動補轉的失敗次數上限；超過只有 --retranscribe 才會再試
TRANSCRIPTION_STATUSES = ("done", "untranscribed", "not_table")

# ---- 轉寫驗證等級（2026-11-18，PO 決定，clarification-log Q-028）
# 預設（沒有驗證列）＝unverified。只有 cross_checked／reviewed 的轉寫文字才納入搜尋；
# unverified／flagged 只在單篇 get_article 顯示並附醒目警告。
VERIFICATION_STATUSES = ("unverified", "flagged", "cross_checked", "reviewed")
SEARCHABLE_VERIFICATION = ("cross_checked", "reviewed")
VERIFICATION_METHODS = ("compare-d-c", "agent-spot-check", "arithmetic", "body-crosscheck")   # 驗證匯入可用的來源白名單
# 檢核家族（2026-11-18 獨立驗收後，PO「資料錯誤最嚴重」原則）：cross_checked 需要「數字家族」與「文字家族」都通過。
# compare 只比數字，抓不到文字截斷（例：「營收」被改成「營」仍判 ok），所以文字家族只認逐字抽查。
NUMERIC_METHODS = ("compare-d-c", "arithmetic", "body-crosscheck")
TEXT_METHODS = ("agent-spot-check",)
FAMILIES = ("numeric", "text")
PO_REVIEW_METHOD = "po-review"        # 只有 --mark-reviewed 會寫入
VERIFICATION_TABLE = "transcription_verification"

SCHEMA = """
CREATE TABLE IF NOT EXISTS article (
    article_id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    list_date TEXT,
    published_at TEXT,
    body TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    discovered_via TEXT,
    discovered_at TEXT,
    fetched_at TEXT,
    id_time_ms INTEGER,
    id_time_ok INTEGER NOT NULL DEFAULT 1,
    pinned INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_article_status ON article(status);

CREATE TABLE IF NOT EXISTS article_image (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES article(article_id),
    seq INTEGER NOT NULL,
    src_url TEXT,
    file_path TEXT,
    is_table INTEGER,
    transcription_status TEXT NOT NULL DEFAULT 'untranscribed',
    transcription TEXT,
    transcribed_model TEXT,
    transcribe_attempts INTEGER NOT NULL DEFAULT 0,
    UNIQUE(article_id, seq)
);

CREATE TABLE IF NOT EXISTS mail_clue (
    message_id TEXT PRIMARY KEY,
    mail_date TEXT,
    seen_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS backfill_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    completed INTEGER NOT NULL DEFAULT 0,
    next_cursor TEXT,
    cutoff_date TEXT,
    cutoff_ms INTEGER,
    started_at TEXT,
    updated_at TEXT,
    list_done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    logged_in INTEGER NOT NULL DEFAULT 0,
    login_ok INTEGER,
    list_pages INTEGER NOT NULL DEFAULT 0,
    articles_attempted INTEGER NOT NULL DEFAULT 0,
    articles_fetched INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    logged_out INTEGER,
    blocked_until TEXT
);

CREATE TABLE IF NOT EXISTS alert_log (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (kind, key, day)
);

CREATE TABLE IF NOT EXISTS setting (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS transcription_verification (
    image_id INTEGER PRIMARY KEY REFERENCES article_image(id),
    status TEXT NOT NULL CHECK (status IN ('unverified','flagged','cross_checked','reviewed')),
    method TEXT,
    verifier TEXT,
    note TEXT,
    flagged_cells TEXT,
    flag_history TEXT,
    checks_passed TEXT,
    checked_at TEXT,
    updates INTEGER NOT NULL DEFAULT 1
);
"""


class BodyTooShort(ValueError):
    """內文過短（疑似殘缺）：不得寫入全文（FR-013）。"""


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ8)


def _iso(dt):
    return _aware(dt).astimezone(TZ8).isoformat()


def _parse(value):
    if not value:
        return None
    return datetime.datetime.fromisoformat(value)


def _json_list(value):
    if not value:
        return []
    try:
        out = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [x for x in out if isinstance(x, str)] if isinstance(out, list) else []


def _merge_names(*parts):
    """把逗號分隔的名稱清單合併、去重、保留順序。"""
    seen, out = set(), []
    for part in parts:
        for name in (part or "").split(","):
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return ",".join(out)


def transcription_sha256(text):
    """轉寫文字的 SHA-256（UTF-8）。驗證結論綁定這個值：轉寫被改寫後，舊的驗證結論不得再套用。
    沒有轉寫文字（not_table）以空字串計。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class TranscriptionChanged(ValueError):
    """驗證匯入時，資料庫目前的轉寫文字與抽查時不同（已被改寫）。"""


def method_family(method):
    if method in NUMERIC_METHODS:
        return "numeric"
    if method in TEXT_METHODS:
        return "text"
    return None


def plan_verification_transition(cur, verdict, method):
    """驗證匯入的狀態轉換規則（純函式；預覽與實際寫入共用，保證兩邊判斷一致）。

    cur＝現有驗證列（dict）或 None；verdict＝'ok'｜'issues'；method＝本次驗證來源（白名單）。
    回傳 {"action": "write", "status": ..., "checks": [已通過的家族]} 或 {"action": "skip", "reason": ...}。
    * issues → 一律 flagged，已通過的家族清空（壞消息永遠優先；含把 cross_checked／reviewed 降為 flagged）；
    * ok → 該 method 所屬家族記為通過；**數字家族與文字家族都通過才是 cross_checked**，只過一個家族維持
      原狀態（unverified 或 flagged）並記錄 checks；
      reviewed：略過（PO 核對過的不被自動流程動）；
      flagged：method 曾標過疑慮者略過（防洗白）；要轉 cross_checked 仍須兩個家族都有「疑慮之後」的新 ok。
    reviewed 絕不會由這個函式產生。"""
    fam = method_family(method)
    if fam is None:
        raise ValueError("未知的驗證 method：%r" % (method,))
    cur_status = cur["status"] if cur else "unverified"
    if verdict == "issues":
        return {"action": "write", "status": "flagged", "checks": []}
    if verdict != "ok":
        raise ValueError("未知的 verdict：%r" % (verdict,))
    if cur_status == "reviewed":
        return {"action": "skip", "reason": "reviewed"}
    if cur_status == "flagged" and method in set(_json_list(cur.get("flag_history"))):
        return {"action": "skip", "reason": "same-method"}
    checks = set(n for n in ((cur or {}).get("checks_passed") or "").split(",") if n in FAMILIES)
    if cur_status == "cross_checked":
        checks = set(FAMILIES)
    checks.add(fam)
    if checks >= set(FAMILIES):
        status = "cross_checked"
    else:
        status = "flagged" if cur_status == "flagged" else "unverified"
    return {"action": "write", "status": status, "checks": [f for f in FAMILIES if f in checks]}


class ArticleStore(object):
    def __init__(self, data_dir, now=None):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, DB_FILENAME)
        self._now = now or (lambda: datetime.datetime.now(TZ8))
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._ensure_columns()
        self.conn.commit()
        # 刻意不寫入任何資料列

    def _ensure_columns(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(import_runs)")]
        if "login_ok" not in cols:          # 早期測試目錄建立的舊表
            self.conn.execute("ALTER TABLE import_runs ADD COLUMN login_ok INTEGER")
        if "list_pages" not in cols:        # 每週核對判定用：本次讀到幾頁清單
            self.conn.execute("ALTER TABLE import_runs ADD COLUMN list_pages INTEGER NOT NULL DEFAULT 0")

        bcols = [r[1] for r in self.conn.execute("PRAGMA table_info(backfill_state)")]
        if "list_done" not in bcols:        # T042：清單已掃完（停止規則成立），之後只清待辦、不再往舊翻
            self.conn.execute("ALTER TABLE backfill_state ADD COLUMN list_done INTEGER NOT NULL DEFAULT 0")

        vcols = [r[1] for r in self.conn.execute("PRAGMA table_info(transcription_verification)")]
        if vcols and "checks_passed" not in vcols:   # 開發期建立的早期驗證表
            self.conn.execute("ALTER TABLE transcription_verification ADD COLUMN checks_passed TEXT")

        icols = [r[1] for r in self.conn.execute("PRAGMA table_info(article_image)")]
        if "transcribe_attempts" not in icols:   # 2026-11-15 審查：夜間補轉的失敗累計次數
            self.conn.execute("ALTER TABLE article_image ADD COLUMN transcribe_attempts INTEGER NOT NULL DEFAULT 0")

    def close(self):
        self.conn.close()

    def _begin_immediate(self):
        """批次寫入先取得寫入鎖（BEGIN IMMEDIATE），之後的讀取與寫入在同一個一致的視窗內（避免多寫入者交錯）。"""
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")

    def now(self):
        return _aware(self._now())

    # ------------------------------------------------------------------ 文章

    def get_article_row(self, article_id):
        row = self.conn.execute("SELECT * FROM article WHERE article_id=?", (article_id,)).fetchone()
        return dict(row) if row else None

    def upsert_discovered(self, article_id, url, title, list_date=None, via="mail",
                          pinned=False, now=None):
        """登記清單上看到的文章。回傳 "inserted"／"exists"。已存在者不改狀態；`fetched` 完全不動。"""
        aid = article_id_time.parse_article_id(article_id)
        if aid is None:
            raise ValueError("文章 ID 必須是正整數：%r" % (article_id,))
        if not URL_RE.match(url or ""):
            raise ValueError("不是定錨文章網址：%r" % (url,))
        row = self.get_article_row(aid)
        if row is not None:
            if row["status"] != "fetched":
                self.conn.execute(
                    "UPDATE article SET title=?, list_date=COALESCE(?, list_date), "
                    "pinned=MAX(pinned, ?) WHERE article_id=?",
                    (title or row["title"], list_date, 1 if pinned else 0, aid))
                self.conn.commit()
            return "exists"
        ms = article_id_time.id_time_ms(aid)
        self.conn.execute(
            "INSERT INTO article (article_id, url, title, list_date, status, discovered_via, "
            "discovered_at, id_time_ms, id_time_ok, pinned) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, url, title, list_date, "discovered", via, _iso(now or self.now()), ms,
             1 if ms is not None else 0, 1 if pinned else 0))
        self.conn.commit()
        return "inserted"

    def mark_fetched(self, article_id, body, published_at=None, now=None):
        """寫入全文。只允許 discovered／failed；已 fetched 回 False（不覆寫）；內文過短拋 BodyTooShort。"""
        row = self.get_article_row(article_id)
        if row is None:
            raise KeyError(article_id)
        if row["status"] == "fetched":
            return False
        if row["status"] not in PENDING_STATUSES:
            raise ValueError("狀態 %s 不能直接轉為 fetched" % row["status"])
        if body is None or len(body.strip()) < MIN_BODY_LEN:
            raise BodyTooShort("內文過短（%d 字 < %d），不寫入" % (len((body or "").strip()), MIN_BODY_LEN))
        self.conn.execute(
            "UPDATE article SET status='fetched', body=?, published_at=?, fetched_at=?, "
            "last_error=NULL WHERE article_id=?",
            (body, published_at, _iso(now or self.now()), article_id))
        self.conn.commit()
        return True

    def mark_failed(self, article_id, error, secrets=(), max_attempts=None):
        """單篇失敗：attempts+1、last_error 脫敏；達上限 → abandoned。回傳新狀態（fetched 等終態不動）。"""
        row = self.get_article_row(article_id)
        if row is None:
            raise KeyError(article_id)
        if row["status"] not in PENDING_STATUSES:
            return row["status"]
        limit = max_attempts or investanchors_limits.MAX_ATTEMPTS_PER_ARTICLE
        attempts = row["attempts"] + 1
        status = "abandoned" if attempts >= limit else "failed"
        self.conn.execute(
            "UPDATE article SET status=?, attempts=?, last_error=? WHERE article_id=?",
            (status, attempts, investanchors_redact.safe_error(error, secrets), article_id))
        self.conn.commit()
        return status

    def mark_deferred(self, article_id):
        """回補：早於截止日、不開啟。只允許 discovered。"""
        return self._transition(article_id, ("discovered",), "deferred")

    def mark_skipped(self, article_id):
        """公告（FR-004）。只允許 discovered。"""
        return self._transition(article_id, ("discovered",), "skipped")

    def reset_abandoned(self, article_id):
        """PO 介入後手動重置：abandoned → failed（attempts 歸零，可再試 3 次）。"""
        ok = self._transition(article_id, ("abandoned",), "failed")
        if ok:
            self.conn.execute("UPDATE article SET attempts=0 WHERE article_id=?", (article_id,))
            self.conn.commit()
        return ok

    def reactivate_deferred(self, article_id):
        """PO 要求補抓更早文章（放寬截止日）：deferred → discovered。"""
        return self._transition(article_id, ("deferred",), "discovered")

    def _transition(self, article_id, allowed_from, to_status):
        row = self.get_article_row(article_id)
        if row is None:
            raise KeyError(article_id)
        if row["status"] not in allowed_from:
            return False
        self.conn.execute("UPDATE article SET status=? WHERE article_id=?", (to_status, article_id))
        self.conn.commit()
        return True

    def set_pinned(self, article_id, pinned=True):
        self.conn.execute("UPDATE article SET pinned=? WHERE article_id=?",
                          (1 if pinned else 0, article_id))
        self.conn.commit()

    def list_pending(self, limit=None, max_attempts=None):
        """待抓：discovered＋failed（attempts<上限）。新文章優先於回補，其次依 ID 新到舊。"""
        cap = max_attempts or investanchors_limits.MAX_ATTEMPTS_PER_ARTICLE
        sql = ("SELECT * FROM article WHERE status IN ('discovered','failed') AND attempts < ? "
               "ORDER BY CASE WHEN discovered_via='backfill' THEN 1 ELSE 0 END, article_id DESC")
        params = [cap]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in self.conn.execute(sql, params)]

    def count_id_time_anomalies(self):
        """推不出建立時間（id_time_ok=0）的文章數；公告（skipped，真實公告 ID 只有 13 位）不算。"""
        return self.conn.execute(
            "SELECT COUNT(*) FROM article WHERE id_time_ok=0 AND status != 'skipped'").fetchone()[0]

    def deferred_rows(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM article WHERE status='deferred' ORDER BY article_id")]

    def known_ids(self):
        return set(r[0] for r in self.conn.execute("SELECT article_id FROM article"))

    def count_by_status(self):
        return dict((r[0], r[1]) for r in self.conn.execute(
            "SELECT status, COUNT(*) FROM article GROUP BY status"))

    # ------------------------------------------------------------------ 圖片

    def add_image(self, article_id, seq, src_url):
        """登記文章內一張圖；同 (article_id, seq) 不重複。回傳 True＝新登記。"""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO article_image (article_id, seq, src_url) VALUES (?,?,?)",
            (article_id, seq, src_url))
        self.conn.commit()
        return cur.rowcount == 1

    def set_image_file(self, article_id, seq, file_path):
        """相對 data_dir 的本機路徑；下載失敗就不要呼叫（保留 NULL，下次補抓）。"""
        self.conn.execute("UPDATE article_image SET file_path=? WHERE article_id=? AND seq=?",
                          (file_path, article_id, seq))
        self.conn.commit()

    def list_images(self, article_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM article_image WHERE article_id=? ORDER BY seq", (article_id,))]

    # ------------------------------------------------------------------ 查詢（US2，唯讀）

    @classmethod
    def open_readonly(cls, data_dir):
        """以 SQLite 唯讀模式（mode=ro）開啟既有 articles.db，給 MCP 查詢用。

        不建目錄、不建表、不寫任何東西；庫不存在就明確報錯而不是建立空庫。"""
        path = os.path.join(os.path.abspath(data_dir), DB_FILENAME)
        if not os.path.isfile(path):
            raise FileNotFoundError("文章庫尚未建立（找不到 %s），尚無已匯入的文章" % DB_FILENAME)
        self = cls.__new__(cls)
        self.data_dir = os.path.abspath(data_dir)
        self.db_path = path
        self._now = lambda: datetime.datetime.now(TZ8)
        self.conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23"),
                                    uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        return self

    @staticmethod
    def _like_pattern(keyword):
        esc = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "%" + esc + "%"

    @staticmethod
    def _snippet(text, keyword, radius=SNIPPET_RADIUS):
        idx = text.lower().find(keyword.lower())
        if idx < 0:
            return None
        start = max(0, idx - radius)
        end = min(len(text), idx + len(keyword) + radius)
        out = text[start:end].replace("\n", " ")
        return ("…" if start > 0 else "") + out + ("…" if end < len(text) else "")

    def search_articles(self, query, limit=DEFAULT_SEARCH_LIMIT):
        """關鍵字搜尋（LIKE，非 FTS5，見 research R6）。

        query 以空白切多關鍵字、全部需出現（AND）；範圍＝標題＋全文＋圖片轉寫文字；
        僅 status='fetched'；發布日期新到舊。回傳 list[dict]：
        article_id／title／published_at／url／snippet／source（內文／表格轉寫／標題）。"""
        keywords = (query or "").split()
        if not keywords:
            raise ValueError("query 不可為空，請給至少一個關鍵字")
        try:
            limit = int(limit) if limit is not None else DEFAULT_SEARCH_LIMIT
        except (TypeError, ValueError):
            raise ValueError("limit 必須是整數")
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        conds, params = ["a.status = 'fetched'"], []
        # 轉寫文字只有 cross_checked／reviewed 才納入搜尋（Q-028）。唯讀開庫時舊庫可能還沒有驗證表：
        # 表不存在＝所有轉寫皆 unverified＝轉寫文字完全不納入（不是出錯）。
        has_ver = self._has_verification_table()
        ver_marks = ",".join("?" for _ in SEARCHABLE_VERIFICATION)
        for kw in keywords:
            pat = self._like_pattern(kw)
            if has_ver:
                conds.append(
                    "(a.title LIKE ? ESCAPE '\\' OR a.body LIKE ? ESCAPE '\\' OR EXISTS ("
                    "SELECT 1 FROM article_image i JOIN %s v ON v.image_id = i.id "
                    "WHERE i.article_id = a.article_id AND i.transcription_status = 'done' "
                    "AND v.status IN (%s) AND i.transcription LIKE ? ESCAPE '\\'))"
                    % (VERIFICATION_TABLE, ver_marks))
                params += [pat, pat] + list(SEARCHABLE_VERIFICATION) + [pat]
            else:
                conds.append("(a.title LIKE ? ESCAPE '\\' OR a.body LIKE ? ESCAPE '\\')")
                params += [pat, pat]
        sql = ("SELECT a.* FROM article a WHERE " + " AND ".join(conds) +
               " ORDER BY COALESCE(a.published_at, a.list_date, '') DESC, a.article_id DESC LIMIT ?")
        params.append(limit)
        results = []
        for row in self.conn.execute(sql, params).fetchall():
            row = dict(row)
            snippet, source = None, None
            images = None
            for kw in keywords:
                snippet = self._snippet(row.get("body") or "", kw)
                if snippet:
                    source = "內文"
                    break
                if images is None:
                    images = self._searchable_images(row["article_id"])
                for img in images:
                    snippet = self._snippet(img.get("transcription") or "", kw)
                    if snippet:
                        source = "表格轉寫"
                        break
                if snippet:
                    break
                snippet = self._snippet(row.get("title") or "", kw)
                if snippet:
                    source = "標題"
                    break
            results.append({
                "article_id": row["article_id"], "title": row["title"],
                "published_at": row.get("published_at") or row.get("list_date"),
                "url": row["url"], "snippet": snippet or "", "source": source or "",
            })
        return results

    def _searchable_images(self, article_id):
        """該文章可被搜尋／產生片段的圖：已轉寫且驗證等級為 cross_checked／reviewed。"""
        if not self._has_verification_table():
            return []
        marks = ",".join("?" for _ in SEARCHABLE_VERIFICATION)
        return [dict(r) for r in self.conn.execute(
            "SELECT i.* FROM article_image i JOIN %s v ON v.image_id = i.id "
            "WHERE i.article_id = ? AND i.transcription_status = 'done' AND v.status IN (%s) ORDER BY i.seq"
            % (VERIFICATION_TABLE, marks), [article_id] + list(SEARCHABLE_VERIFICATION))]

    # ------------------------------------------------------------------ 轉寫驗證（Q-028）

    def _has_verification_table(self):
        """舊庫（升級前建立、唯讀開啟）可能沒有驗證表；沒有＝全部 unverified。"""
        row = self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                (VERIFICATION_TABLE,)).fetchone()
        return row is not None

    def get_verification(self, image_id):
        """單張圖的驗證列（dict）；沒有列或沒有表＝None（呼叫端視為 unverified）。"""
        return self.get_verifications([image_id]).get(image_id)

    def get_verifications(self, image_ids):
        """批次取驗證列：{image_id: dict}；沒有列的圖不在結果內（＝unverified）。"""
        ids = [int(i) for i in image_ids]
        if not ids or not self._has_verification_table():
            return {}
        out = {}
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            marks = ",".join("?" for _ in chunk)
            for r in self.conn.execute("SELECT * FROM %s WHERE image_id IN (%s)" % (VERIFICATION_TABLE, marks), chunk):
                out[r["image_id"]] = dict(r)
        return out

    def verification_counts(self):
        """健康檢查／統計用：僅計 status=fetched 文章中已轉寫（done）的圖。
        回 {"unverified", "flagged", "cross_checked", "reviewed", "single_family"}；舊庫沒有驗證表＝全部 unverified。"""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM article_image i JOIN article a ON a.article_id=i.article_id "
            "WHERE a.status='fetched' AND i.transcription_status='done'").fetchone()[0]
        out = {"flagged": 0, "cross_checked": 0, "reviewed": 0}
        if self._has_verification_table():
            for r in self.conn.execute(
                    "SELECT v.status AS st, COUNT(*) AS n FROM %s v JOIN article_image i ON i.id=v.image_id "
                    "JOIN article a ON a.article_id=i.article_id "
                    "WHERE a.status='fetched' AND i.transcription_status='done' GROUP BY v.status" % VERIFICATION_TABLE):
                if r["st"] in out:
                    out[r["st"]] = r["n"]
        out["unverified"] = total - sum(out.values())
        out["single_family"] = 0       # 未驗證中「只通過單一檢核家族」的張數（unverified 的子集）
        if self._has_verification_table():
            out["single_family"] = self.conn.execute(
                "SELECT COUNT(*) FROM %s v JOIN article_image i ON i.id=v.image_id "
                "JOIN article a ON a.article_id=i.article_id WHERE a.status='fetched' AND "
                "i.transcription_status='done' AND v.status='unverified' AND v.checks_passed IS NOT NULL"
                % VERIFICATION_TABLE).fetchone()[0]
        return out

    def apply_verification_batch(self, entries, audit_kind=None, audit_key=None, audit_day=None):
        """驗證匯入：單一交易（BEGIN IMMEDIATE）、全有或全無。entries＝[{image_id, verdict('ok'|'issues'), method,
        verifier, note, cells(JSON 字串或 None), transcription_sha256}]。每筆在**交易內**以最新狀態判斷
        （預覽之後狀態可能變了），並確認資料庫目前的轉寫文字 SHA-256 與抽查時一致，不符即丟 TranscriptionChanged
        （整批 rollback）。回傳 {"cross_checked":[ids], "flagged":[ids], "partial":[ids], "skipped":{reason:[ids]}}；
        partial＝ok 但兩個檢核家族尚未都通過。audit_key 可為字串或 callable(result)->字串（只存數量與 method）。"""
        result = {"cross_checked": [], "flagged": [], "partial": [], "skipped": {}}
        try:
            self._begin_immediate()
            for e in entries:
                img = self.conn.execute("SELECT transcription_status, transcription FROM article_image WHERE id=?",
                                        (e["image_id"],)).fetchone()
                if img is None or transcription_sha256(img["transcription"]) != e["transcription_sha256"]:
                    raise TranscriptionChanged("轉寫在抽查後已被改寫，須重新抽查")
                cur = self.conn.execute("SELECT * FROM %s WHERE image_id=?" % VERIFICATION_TABLE,
                                        (e["image_id"],)).fetchone()
                cur = dict(cur) if cur else None
                plan = plan_verification_transition(cur, e["verdict"], e["method"])
                if plan["action"] == "skip":
                    result["skipped"].setdefault(plan["reason"], []).append(e["image_id"])
                    continue
                status = plan["status"]
                history = _json_list(cur.get("flag_history")) if cur else []
                checks = ",".join(plan["checks"]) or None
                if e["verdict"] == "issues":
                    if e["method"] not in history:
                        history.append(e["method"])
                    method, verifier = e["method"], e["verifier"]
                    note, cells = e.get("note"), e.get("cells")
                    kind = "flagged"
                else:
                    kind = "cross_checked" if status == "cross_checked" else "partial"
                    fresh = cur is None or (cur["status"] == "flagged" and not cur.get("checks_passed"))
                    if fresh:
                        method, verifier = e["method"], e["verifier"]
                    else:
                        method = _merge_names(cur.get("method"), e["method"])
                        verifier = _merge_names(cur.get("verifier"), e["verifier"])
                    note = cells = None
                    if cur is not None and cur["status"] == "flagged":
                        if status == "cross_checked":
                            note = "原 flagged（來源：%s）之後由不同來源重新檢核，數字與文字兩家族皆通過，轉為 cross_checked" % (
                                ",".join(history) or "?")
                        else:
                            note, cells = cur.get("note"), cur.get("flagged_cells")      # 仍是 flagged：疑慮摘要保留
                self.conn.execute(
                    "INSERT OR REPLACE INTO %s (image_id, status, method, verifier, note, flagged_cells, "
                    "flag_history, checks_passed, checked_at, updates) VALUES (?,?,?,?,?,?,?,?,?,?)" % VERIFICATION_TABLE,
                    (e["image_id"], status, method, verifier, note, cells,
                     json.dumps(history) if history else None, checks, _iso(self.now()),
                     (cur["updates"] + 1) if cur else 1))
                result[kind].append(e["image_id"])
            if audit_kind:
                key = audit_key(result) if callable(audit_key) else (audit_key or "-")
                day = audit_day or self.now().astimezone(TZ8).date().isoformat()
                self.conn.execute("INSERT OR IGNORE INTO alert_log (kind, key, day) VALUES (?,?,?)",
                                  (audit_kind, key, day))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return result

    def apply_mark_reviewed(self, image_ids, audit_kind=None, audit_key=None, audit_day=None):
        """PO 本人核對後設為 reviewed（**唯一**會寫入 reviewed 的路徑）。單一交易。
        圖必須存在且為 done；否則整批 rollback 並丟 ValueError。回傳 {"reviewed":[ids], "was":{status:[ids]}}。"""
        result = {"reviewed": [], "was": {}}
        try:
            self._begin_immediate()
            for iid in image_ids:
                img = self.conn.execute("SELECT transcription_status FROM article_image WHERE id=?", (iid,)).fetchone()
                if img is None or img["transcription_status"] != "done":
                    raise ValueError("image_id=%d 不存在或尚未轉寫（done），無法標記為已核對" % iid)
                cur = self.conn.execute("SELECT * FROM %s WHERE image_id=?" % VERIFICATION_TABLE, (iid,)).fetchone()
                cur = dict(cur) if cur else None
                was = cur["status"] if cur else "unverified"
                result["was"].setdefault(was, []).append(iid)
                note = "PO 逐格核對後確認" + ("（原為 flagged，疑慮已由 PO 處理）" if was == "flagged" else "")
                self.conn.execute(
                    "INSERT OR REPLACE INTO %s (image_id, status, method, verifier, note, flagged_cells, "
                    "flag_history, checks_passed, checked_at, updates) VALUES (?,?,?,?,?,?,?,?,?,?)" % VERIFICATION_TABLE,
                    (iid, "reviewed", PO_REVIEW_METHOD, "po", note, None,
                     cur.get("flag_history") if cur else None, None, _iso(self.now()), (cur["updates"] + 1) if cur else 1))
                result["reviewed"].append(iid)
            if audit_kind:
                key = audit_key(result) if callable(audit_key) else (audit_key or "-")
                day = audit_day or self.now().astimezone(TZ8).date().isoformat()
                self.conn.execute("INSERT OR IGNORE INTO alert_log (kind, key, day) VALUES (?,?,?)",
                                  (audit_kind, key, day))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return result

    def get_article(self, article_id):
        """讀單篇（僅 status='fetched'）。找不到或非 fetched → ValueError，不回殘缺內容。"""
        try:
            article_id = int(article_id)
        except (TypeError, ValueError):
            raise ValueError("article_id 必須是整數")
        row = self.get_article_row(article_id)
        if row is None:
            raise ValueError("文章庫裡沒有 article_id=%d（唯讀查詢，不會去網站抓取）" % article_id)
        if row["status"] != "fetched":
            raise ValueError("article_id=%d 尚未成功匯入（狀態：%s），沒有可讀的全文" % (article_id, row["status"]))
        images = self.list_images(article_id)
        vers = self.get_verifications([i["id"] for i in images])
        for img in images:       # 沒有驗證列（或舊庫沒有驗證表）＝unverified
            v = vers.get(img["id"])
            img["verification"] = v
            img["verification_status"] = v["status"] if v else "unverified"
        return {
            "article_id": row["article_id"], "title": row["title"],
            "published_at": row.get("published_at") or row.get("list_date"),
            "url": row["url"], "body": row.get("body") or "",
            "images": images,
        }

    def images_missing_file(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM article_image WHERE file_path IS NULL ORDER BY article_id, seq")]

    @staticmethod
    def _check_transcription(status, text):
        if status not in TRANSCRIPTION_STATUSES:
            raise ValueError("未知的轉寫狀態：%r" % (status,))
        if status == "done":
            if not text or not text.strip():
                raise ValueError("done 必須有轉寫文字")
        elif text:
            raise ValueError("%s 不得帶轉寫文字（不以空白或猜測值充數）" % status)

    def _write_transcription(self, article_id, seq, status, text, model, is_table):
        """只執行 UPDATE、不 commit（供單筆與整批共用）。

        轉寫內容一變（含 --overwrite、換模型重轉、重新匯入），舊的驗證記錄即失效：
        在同一交易內刪除該圖的驗證列（回到 unverified，疑慮記錄一併清除）。"""
        self.conn.execute(
            "DELETE FROM transcription_verification WHERE image_id IN "
            "(SELECT id FROM article_image WHERE article_id=? AND seq=?)", (article_id, seq))
        self.conn.execute(
            "UPDATE article_image SET transcription_status=?, transcription=?, transcribed_model=?, "
            "is_table=COALESCE(?, is_table) WHERE article_id=? AND seq=?",
            (status, text if status == "done" else None, model if status == "done" else None,
             None if is_table is None else (1 if is_table else 0), article_id, seq))

    def set_transcription(self, article_id, seq, status, text=None, model=None, is_table=None):
        """`transcription` 只存轉寫內容、不含標示；`untranscribed` 時必為 NULL（FR-017）。"""
        self._check_transcription(status, text)
        self._write_transcription(article_id, seq, status, text, model, is_table)
        self.conn.commit()

    def apply_transcription_batch(self, rows, audit_kind=None, audit_key=None, audit_day=None):
        """整批寫入轉寫（方案 D 手動匯入用）：單一交易、全有或全無。

        rows＝[(article_id, seq, status, text, model, is_table), ...]；先全部驗證再寫入，任何一筆出錯即 rollback。
        audit_kind／audit_key 若有，在**同一交易內**寫一筆 alert_log 稽核（只放數量，不放內容）；
        刻意不寫 import_runs——避免讓健康檢查把手動匯入誤當成排程執行。"""
        for r in rows:
            self._check_transcription(r[2], r[3])
        try:
            self._begin_immediate()
            for aid, seq, status, text, model, is_table in rows:
                self._write_transcription(aid, seq, status, text, model, is_table)
            if audit_kind:
                day = audit_day or self.now().astimezone(TZ8).date().isoformat()
                self.conn.execute("INSERT OR IGNORE INTO alert_log (kind, key, day) VALUES (?,?,?)",
                                  (audit_kind, audit_key or "-", day))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_image_by_id(self, image_id):
        """依 article_image.id 取一張圖（含所屬文章狀態）；沒有回 None。"""
        row = self.conn.execute(
            "SELECT i.*, a.status AS article_status FROM article_image i "
            "JOIN article a ON a.article_id=i.article_id WHERE i.id=?", (image_id,)).fetchone()
        return dict(row) if row else None

    def images_for_manual_export(self):
        """方案 D 匯出候選：未轉寫、有本機檔、所屬文章非 abandoned；依 article_id／seq 穩定排序。"""
        return [dict(r) for r in self.conn.execute(
            "SELECT i.* FROM article_image i JOIN article a ON a.article_id=i.article_id "
            "WHERE i.file_path IS NOT NULL AND i.transcription_status='untranscribed' "
            "AND a.status != 'abandoned' ORDER BY i.article_id, i.seq")]

    def images_to_transcribe(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM article_image WHERE file_path IS NOT NULL "
            "AND transcription_status='untranscribed' ORDER BY article_id, seq")]

    def bump_transcribe_attempts(self, article_id, seq):
        """實際送出轉寫嘗試但仍未轉寫時 +1。"""
        self.conn.execute("UPDATE article_image SET transcribe_attempts = transcribe_attempts + 1 "
                          "WHERE article_id=? AND seq=?", (article_id, seq))
        self.conn.commit()

    def reset_transcribe_attempts(self):
        """把所有未轉寫圖的失敗次數歸零，回傳受影響張數。"""
        cur = self.conn.execute("UPDATE article_image SET transcribe_attempts=0 "
                                "WHERE transcription_status='untranscribed' AND transcribe_attempts>0")
        self.conn.commit()
        return cur.rowcount

    def images_to_backfill(self, limit, exclude=()):
        """夜間補轉候選：status=fetched 文章、有本機檔、未轉寫、失敗次數未達上限；
        失敗次數少的先，再依 article_id／seq。`exclude` 為 (article_id, seq) 集合（本次已試過者）。"""
        rows = self.conn.execute(
            "SELECT i.* FROM article_image i JOIN article a ON a.article_id=i.article_id "
            "WHERE a.status='fetched' AND i.file_path IS NOT NULL AND i.transcription_status='untranscribed' "
            "AND i.transcribe_attempts < ? ORDER BY i.transcribe_attempts, i.article_id, i.seq",
            (MAX_TRANSCRIBE_ATTEMPTS,))
        out = []
        for r in rows:
            if (r["article_id"], r["seq"]) in exclude:
                continue
            out.append(dict(r))
            if len(out) >= limit:
                break
        return out

    def transcription_counts(self):
        """健康檢查用：僅計 status=fetched 文章的圖。exhausted＝未轉寫且已達自動補轉上限。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(i.transcribe_attempts >= ?), 0) AS ex "
            "FROM article_image i JOIN article a ON a.article_id=i.article_id "
            "WHERE a.status='fetched' AND i.transcription_status='untranscribed'",
            (MAX_TRANSCRIBE_ATTEMPTS,)).fetchone()
        return {"untranscribed": row["n"], "exhausted": int(row["ex"])}

    # ------------------------------------------------------------------ 通知信線索

    def add_mail_clue(self, message_id, mail_date, now=None):
        """只記 Message-ID 與寄達時間；同一封不重複。回傳 True＝新信。"""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO mail_clue (message_id, mail_date, seen_at) VALUES (?,?,?)",
            (message_id, mail_date, _iso(now or self.now())))
        self.conn.commit()
        return cur.rowcount == 1

    def unprocessed_mail_clues(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM mail_clue WHERE processed=0 ORDER BY mail_date, message_id")]

    def mark_mail_processed(self, message_ids):
        for mid in message_ids:
            self.conn.execute("UPDATE mail_clue SET processed=1 WHERE message_id=?", (mid,))
        self.conn.commit()

    # ------------------------------------------------------------------ 回補進度

    def get_backfill_state(self):
        row = self.conn.execute("SELECT * FROM backfill_state WHERE id=1").fetchone()
        return dict(row) if row else None

    def start_backfill(self, cutoff_date, cutoff_ms, now=None):
        """首次啟動：寫入截止日並固定。已存在則拒絕（截止日只能經 widen_cutoff 往前放寬）。"""
        if self.get_backfill_state() is not None:
            raise ValueError("回補已啟動，截止日已固定")
        ts = _iso(now or self.now())
        self.conn.execute(
            "INSERT INTO backfill_state (id, completed, next_cursor, cutoff_date, cutoff_ms, "
            "started_at, updated_at) VALUES (1, 0, NULL, ?, ?, ?, ?)",
            (cutoff_date, int(cutoff_ms), ts, ts))
        self.conn.commit()

    def update_backfill(self, next_cursor=None, completed=None, list_done=None, now=None):
        if self.get_backfill_state() is None:
            raise ValueError("回補尚未啟動")
        sets, params = ["updated_at=?"], [_iso(now or self.now())]
        if next_cursor is not None:
            sets.append("next_cursor=?")
            params.append(next_cursor)
        if completed is not None:
            sets.append("completed=?")
            params.append(1 if completed else 0)
        if list_done is not None:
            sets.append("list_done=?")
            params.append(1 if list_done else 0)
        self.conn.execute("UPDATE backfill_state SET %s WHERE id=1" % ", ".join(sets), params)
        self.conn.commit()

    def widen_cutoff(self, cutoff_date, cutoff_ms, now=None):
        """PO 要求補抓更早文章：只能往前放寬；completed 重設為 0、游標清空。"""
        state = self.get_backfill_state()
        if state is None:
            raise ValueError("回補尚未啟動")
        if int(cutoff_ms) >= int(state["cutoff_ms"]):
            raise ValueError("新截止日必須早於現有截止日（只能往前放寬）")
        self.conn.execute(
            "UPDATE backfill_state SET cutoff_date=?, cutoff_ms=?, completed=0, next_cursor=NULL, "
            "list_done=0, updated_at=? WHERE id=1", (cutoff_date, int(cutoff_ms), _iso(now or self.now())))
        self.conn.commit()

    # ------------------------------------------------------------------ 設定

    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    # ------------------------------------------------------------------ 執行紀錄

    def start_run(self, trigger, now=None):
        cur = self.conn.execute(
            "INSERT INTO import_runs (started_at, trigger) VALUES (?, ?)",
            (_iso(now or self.now()), trigger))
        self.conn.commit()
        return cur.lastrowid

    def mark_login_started(self, run_id):
        """**啟動登入前**呼叫：就算之後當機，這次也已計入當日登入次數。

        `logged_in` 的意思是「**已嘗試登入**」（用來計當日額度），只會由 0 變 1，`finish_run` 不得調回 0——
        密碼錯誤、帳號停用、被擋在登入頁這類「有嘗試但失敗」的情況，重複嘗試正是要避免的。
        「登入是否成功」另存 `login_ok`。"""
        self.conn.execute("UPDATE import_runs SET logged_in=1 WHERE id=?", (run_id,))
        self.conn.commit()

    def finish_run(self, run_id, login_ok, attempted, fetched, result, logged_out,
                   blocked_until=None, now=None, list_pages=0):
        """`login_ok`：登入是否成功（None＝沒嘗試登入）。`logged_in`（已嘗試）只升不降：成功必然代表嘗試過。"""
        self.conn.execute(
            "UPDATE import_runs SET finished_at=?, logged_in=MAX(logged_in, ?), login_ok=?, "
            "articles_attempted=?, articles_fetched=?, result=?, logged_out=?, blocked_until=?, list_pages=? "
            "WHERE id=?",
            (_iso(now or self.now()), 1 if login_ok else 0, None if login_ok is None else (1 if login_ok else 0),
             attempted, fetched, result,
             None if logged_out is None else (1 if logged_out else 0),
             _iso(blocked_until) if blocked_until else None, int(list_pages or 0), run_id))
        self.conn.commit()

    def logins_today(self, now=None):
        """以台北日期計：今天已啟動登入的執行次數。"""
        day = _aware(now or self.now()).astimezone(TZ8).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) FROM import_runs WHERE logged_in=1 AND substr(started_at,1,10)=?",
            (day,)).fetchone()
        return row[0]

    def last_login_started_at(self):
        """最近一次「已啟動登入」（logged_in=1）的執行開始時間（跨日皆計；沒有則 None）。

        run 在 `start_run` 後極短時間內就 `mark_login_started`（中間只有讀鑰匙圈），以 started_at 代表登入時間。run id 單調遞增（循序執行），最新一筆就是最近一次登入。
        被守衛拒絕的執行（logged_in=0）不算。"""
        row = self.conn.execute(
            "SELECT started_at FROM import_runs WHERE logged_in=1 ORDER BY id DESC LIMIT 1").fetchone()
        return _aware(_parse(row[0])) if row and row[0] else None

    def blocked_until(self):
        row = self.conn.execute(
            "SELECT blocked_until FROM import_runs WHERE blocked_until IS NOT NULL").fetchall()
        values = [_parse(r[0]) for r in row]
        return max(values) if values else None

    def last_weekly_check(self):
        """只有「登入成功且至少讀到一頁清單」的每週核對才算完成；登入失敗、被擋、沒讀到清單都不算。"""
        row = self.conn.execute(
            "SELECT started_at FROM import_runs WHERE trigger LIKE '%weekly%' AND login_ok=1 AND list_pages>=1 "
            "ORDER BY started_at DESC LIMIT 1").fetchone()
        return _parse(row[0]) if row else None

    def unverified_logout_runs(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM import_runs WHERE logged_in=1 AND logged_out=0 ORDER BY id")]

    def recent_runs(self, limit=20):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM import_runs ORDER BY id DESC LIMIT ?", (int(limit),))]

    # ------------------------------------------------------------------ 通知去重

    def alert_once(self, kind, key, day=None):
        """同 (kind, key, 日期) 第一次回 True（該通知），之後 False。"""
        d = day or self.now().astimezone(TZ8).date().isoformat()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO alert_log (kind, key, day) VALUES (?,?,?)", (kind, key, d))
        self.conn.commit()
        return cur.rowcount == 1
