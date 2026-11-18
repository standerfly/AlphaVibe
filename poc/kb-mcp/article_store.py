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

        icols = [r[1] for r in self.conn.execute("PRAGMA table_info(article_image)")]
        if "transcribe_attempts" not in icols:   # 2026-11-15 審查：夜間補轉的失敗累計次數
            self.conn.execute("ALTER TABLE article_image ADD COLUMN transcribe_attempts INTEGER NOT NULL DEFAULT 0")

    def close(self):
        self.conn.close()

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
        for kw in keywords:
            pat = self._like_pattern(kw)
            conds.append(
                "(a.title LIKE ? ESCAPE '\\' OR a.body LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM article_image i WHERE i.article_id = a.article_id "
                "AND i.transcription LIKE ? ESCAPE '\\'))")
            params += [pat, pat, pat]
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
                    images = self.list_images(row["article_id"])
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
        return {
            "article_id": row["article_id"], "title": row["title"],
            "published_at": row.get("published_at") or row.get("list_date"),
            "url": row["url"], "body": row.get("body") or "",
            "images": self.list_images(article_id),
        }

    def images_missing_file(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM article_image WHERE file_path IS NULL ORDER BY article_id, seq")]

    def set_transcription(self, article_id, seq, status, text=None, model=None, is_table=None):
        """`transcription` 只存轉寫內容、不含標示；`untranscribed` 時必為 NULL（FR-017）。"""
        if status not in TRANSCRIPTION_STATUSES:
            raise ValueError("未知的轉寫狀態：%r" % (status,))
        if status == "done":
            if not text or not text.strip():
                raise ValueError("done 必須有轉寫文字")
        elif text:
            raise ValueError("%s 不得帶轉寫文字（不以空白或猜測值充數）" % status)
        self.conn.execute(
            "UPDATE article_image SET transcription_status=?, transcription=?, transcribed_model=?, "
            "is_table=COALESCE(?, is_table) WHERE article_id=? AND seq=?",
            (status, text if status == "done" else None, model if status == "done" else None,
             None if is_table is None else (1 if is_table else 0), article_id, seq))
        self.conn.commit()

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

        run 在 `start_run` 後極短時間內就 `mark_login_started`（中間只有讀鑰匙圈），以 started_at 代表登入時間。
        被守衛拒絕的執行（logged_in=0）不算。"""
        rows = self.conn.execute("SELECT started_at FROM import_runs WHERE logged_in=1").fetchall()
        values = [_aware(_parse(r[0])) for r in rows if r[0]]
        return max(values) if values else None

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
