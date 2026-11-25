"""Substack 文章庫（011，獨立資料庫 `substack.db`；data-model.md §1、research R6／R8）。

與 010 文章庫完全分離：本模組只開啟 `<data_dir>/substack.db`，不 import 也不開啟 010 的任何
資料庫或儲存模組（FR-006、FR-021；隔離由 tests/test_substack_isolation.py 的 T-A 靜態掃描守門）。

必須遵守的既有教訓：
1. `sqlite3.connect()` 帶 `check_same_thread=False`（2026-08-22 FastAPI 併發事故）；
2. `__init__()` **不得有任何資料寫入副作用**（2026-08-22 資產表污染事故）——建構子只建表；
3. 連線一律 `isolation_level=None`（autocommit），所有寫入經 `with store.transaction():`
   （顯式 `BEGIN IMMEDIATE`／`COMMIT`／`ROLLBACK`），交易外不得有任何 DML（research R8：
   Python 3.9 的隱性 BEGIN 會讓「單篇一交易」的原子性無聲失效）。

設計約束：
* 已存文章**不覆寫**：`UPDATE article SET` 只允許改通知欄位（`notify_status`／`notify_attempts`／
  `notified_at`），沒有任何路徑會改標題、內容或判斷（FR-007；靜態守門測試會檢查）。
* 重判紀錄 `reclassification` **只增不改**：沒有 UPDATE／DELETE 路徑（FR-033）。
* 非文字（N）類文章 `body_text` 恆為 NULL（FR-011、spec Q14），以 Python 驗證＋資料庫 CHECK 雙重把關。
* 日後加欄位：比照 010 文章庫的做法用 `PRAGMA table_info` 檢查後 `ALTER TABLE ADD COLUMN`，
  唯讀查詢先確認欄位存在（本包是新庫，沒有遷移）。

僅標準庫、Python 3.9 相容。
"""
import contextlib
import datetime
import os
import shutil
import sqlite3

DB_FILENAME = "substack.db"
IMAGES_DIRNAME = "substack_images"
TZ8 = datetime.timezone(datetime.timedelta(hours=8))

COMPLETENESS = ("P", "F", "N")
NOTIFY_STATUSES = ("pending", "sent", "failed", "abandoned")
MAX_NOTIFY_ATTEMPTS = 3
IMAGE_STATUSES = ("pending", "downloaded", "missing", "abandoned")
MAX_IMAGE_FAILS = 3
UNCERTAIN_PREFIX = "uncertain:"
# 排程日判斷只看「真的執行過」的列（data-model §1.5 註）
NON_RUN_RESULTS = ("deferred", "already_done")

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS author (
        author_key TEXT PRIMARY KEY,
        display_name TEXT,
        feed_url TEXT,
        last_seen_enabled INTEGER NOT NULL DEFAULT 0,
        activated_at TEXT,
        window_from TEXT,
        etag TEXT,
        last_request_at TEXT,
        last_outcome TEXT,
        last_success_at TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS article (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_key TEXT NOT NULL,
        guid TEXT,
        link TEXT NOT NULL,
        link_norm TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        source TEXT,
        completeness TEXT NOT NULL CHECK (completeness IN ('P','F','N')),
        classify_reason TEXT NOT NULL,
        content_html TEXT,
        body_text TEXT,
        description TEXT,
        enclosure_type TEXT,
        notify_status TEXT NOT NULL DEFAULT 'pending',
        notify_attempts INTEGER NOT NULL DEFAULT 0,
        notified_at TEXT,
        CHECK ((completeness = 'N') = (body_text IS NULL))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS article_image (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        src_url TEXT NOT NULL,
        alt TEXT,
        caption TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        fail_count INTEGER NOT NULL DEFAULT 0,
        last_error_code TEXT,
        file_path TEXT,
        sha256 TEXT,
        bytes INTEGER,
        downloaded_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS poll_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        author_key TEXT,
        at TEXT,
        requested INTEGER NOT NULL DEFAULT 0,
        http_status INTEGER,
        outcome TEXT,
        items_in_feed INTEGER,
        new_items INTEGER,
        skipped_window INTEGER,
        skipped_no_pubdate INTEGER,
        all_new INTEGER NOT NULL DEFAULT 0,
        duration_ms INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT,
        finished_at TEXT,
        trigger TEXT,
        schedule_day TEXT,
        result TEXT,
        authors_polled INTEGER NOT NULL DEFAULT 0,
        authors_skipped_interval INTEGER NOT NULL DEFAULT 0,
        authors_failed INTEGER NOT NULL DEFAULT 0,
        new_articles INTEGER NOT NULL DEFAULT 0,
        images_downloaded INTEGER NOT NULL DEFAULT 0,
        images_missing INTEGER NOT NULL DEFAULT 0,
        images_abandoned_now INTEGER NOT NULL DEFAULT 0,
        notify_sent INTEGER NOT NULL DEFAULT 0,
        notify_failed INTEGER NOT NULL DEFAULT 0,
        budget_exhausted INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS robots_cache (
        host TEXT PRIMARY KEY,
        fetched_at TEXT,
        http_status INTEGER,
        body TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcription_trial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT,
        finished_at TEXT,
        confirm_code TEXT,
        articles INTEGER,
        images_attempted INTEGER,
        images_ok INTEGER,
        images_not_table INTEGER,
        images_failed INTEGER,
        claude_calls INTEGER,
        models TEXT,
        result TEXT,
        reset_hint TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_transcription (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_id INTEGER NOT NULL,
        trial_id INTEGER NOT NULL,
        is_table INTEGER,
        text TEXT,
        reader_model TEXT,
        verifier_model TEXT,
        verdict TEXT,
        issues_json TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reclassification (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        at TEXT NOT NULL,
        trigger TEXT NOT NULL,
        old_completeness TEXT NOT NULL,
        new_completeness TEXT NOT NULL CHECK (new_completeness IN ('P','F','N')),
        new_reason TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        derived_body_text TEXT,
        changed INTEGER NOT NULL DEFAULT 0,
        run_id INTEGER
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_guid ON article(guid) "
    "WHERE guid IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_link_norm ON article(link_norm)",
    "CREATE INDEX IF NOT EXISTS idx_article_author_published ON article(author_key, published_at)",
    "CREATE INDEX IF NOT EXISTS idx_article_fetched ON article(fetched_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_image_seq ON article_image(article_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_article_image_status ON article_image(status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_image_transcription_unique "
    "ON image_transcription(image_id, trial_id)",
    "CREATE INDEX IF NOT EXISTS idx_reclassification_article ON reclassification(article_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_poll_log_run ON poll_log(run_id)",
    # 有效完整度／有效內文的唯一出處（FR-033、FR-011、spec Q14）
    """
    CREATE VIEW IF NOT EXISTS article_effective AS
    SELECT a.*,
           a.completeness AS original_completeness,
           a.classify_reason AS original_reason,
           COALESCE(r.new_completeness, a.completeness) AS effective_completeness,
           COALESCE(r.new_reason, a.classify_reason) AS effective_reason,
           (SELECT COUNT(*) FROM reclassification c WHERE c.article_id = a.id)
               AS reclassified_count,
           CASE
             WHEN COALESCE(r.new_completeness, a.completeness) = 'N' THEN NULL
             WHEN a.body_text IS NOT NULL THEN a.body_text
             ELSE (SELECT d.derived_body_text FROM reclassification d
                    WHERE d.article_id = a.id AND d.derived_body_text IS NOT NULL
                    ORDER BY d.id DESC LIMIT 1)
           END AS effective_body_text
      FROM article a
      LEFT JOIN reclassification r
        ON r.id = (SELECT MAX(x.id) FROM reclassification x WHERE x.article_id = a.id)
    """,
)


class DiskFullError(RuntimeError):
    """磁碟（或資料庫）空間不足：當次立即中止，已提交的文章各自完整（research R8）。"""


def _is_disk_full(exc):
    text = str(exc).lower()
    return "disk is full" in text or "disk full" in text or "database or disk" in text


def _rows(cursor):
    return [dict(r) for r in cursor]


class SubstackStore(object):
    def __init__(self, data_dir, now=None):
        self.data_dir = os.path.realpath(os.path.abspath(data_dir))
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, DB_FILENAME)
        self._now = now or (lambda: datetime.datetime.now(TZ8))
        self._depth = 0
        self.conn = sqlite3.connect(self.db_path, isolation_level=None,
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self.transaction():                       # DDL 也在自己的顯式交易內（research R8）
            for stmt in SCHEMA:
                self.conn.execute(stmt)

    # ------------------------------------------------------------------ 基礎
    def close(self):
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def now_text(self):
        return self._now().isoformat(timespec="seconds")

    @contextlib.contextmanager
    def transaction(self):
        """唯一的寫入入口：顯式 BEGIN IMMEDIATE；例外回滾後重拋（磁碟滿轉 DiskFullError）。"""
        if self._depth:
            self._depth += 1
            try:
                yield self.conn
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self.conn
        except BaseException as exc:
            self._depth = 0
            self._rollback()
            if isinstance(exc, sqlite3.OperationalError) and _is_disk_full(exc):
                raise DiskFullError(str(exc))
            raise
        self._depth = 0
        try:
            self.conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            self._rollback()
            if _is_disk_full(exc):
                raise DiskFullError(str(exc))
            raise

    def _rollback(self):
        try:
            self.conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------------ 作者狀態（§1.1）
    def upsert_author(self, author_key, display_name=None, feed_url=None):
        with self.transaction():
            self.conn.execute(
                "INSERT OR IGNORE INTO author(author_key, display_name, feed_url) VALUES (?,?,?)",
                (author_key, display_name, feed_url))
            self.conn.execute(
                "UPDATE author SET display_name=?, feed_url=? WHERE author_key=?",
                (display_name, feed_url, author_key))
        return self.get_author(author_key)

    def get_author(self, author_key):
        row = self.conn.execute("SELECT * FROM author WHERE author_key=?",
                                (author_key,)).fetchone()
        return dict(row) if row else None

    def list_authors(self):
        return _rows(self.conn.execute("SELECT * FROM author ORDER BY author_key"))

    def activate_author(self, author_key, activated_at, window_from):
        """首次／重新啟用：寫入 14 天窗的基準（FR-008）。"""
        with self.transaction():
            self.conn.execute(
                "UPDATE author SET activated_at=?, window_from=?, last_seen_enabled=1 "
                "WHERE author_key=?", (activated_at, window_from, author_key))
        return self.get_author(author_key)

    def note_author_enabled(self, author_key, enabled):
        with self.transaction():
            self.conn.execute("UPDATE author SET last_seen_enabled=? WHERE author_key=?",
                              (1 if enabled else 0, author_key))

    def record_feed_request(self, author_key, at, outcome, http_status=None, etag=None,
                            success=False, requested=True):
        """更新作者的請求狀態；200／304 把連續失敗歸零，間隔跳過（requested=False）不增不減。"""
        with self.transaction():
            if requested:
                self.conn.execute(
                    "UPDATE author SET last_request_at=?, last_outcome=? WHERE author_key=?",
                    (at, outcome, author_key))
            else:
                self.conn.execute("UPDATE author SET last_outcome=? WHERE author_key=?",
                                  (outcome, author_key))
            if etag is not None:
                self.conn.execute("UPDATE author SET etag=? WHERE author_key=?",
                                  (etag, author_key))
            if success:
                self.conn.execute(
                    "UPDATE author SET last_success_at=?, consecutive_failures=0 "
                    "WHERE author_key=?", (at, author_key))
            elif requested:
                self.conn.execute(
                    "UPDATE author SET consecutive_failures=consecutive_failures+1 "
                    "WHERE author_key=?", (author_key,))
        return self.get_author(author_key)

    # ------------------------------------------------------------------ 文章（§1.2）
    def _validate_article(self, article):
        comp = article.get("completeness")
        reason = article.get("classify_reason") or ""
        body = article.get("body_text")
        if comp not in COMPLETENESS:
            raise ValueError("completeness 必須是 P／F／N，收到 %r" % (comp,))
        if not reason:
            raise ValueError("classify_reason 不得為空")
        if reason.startswith(UNCERTAIN_PREFIX) and comp != "P":
            raise ValueError("不確定（%s）的文章一律存 P，收到 %s" % (reason, comp))
        if comp == "N":
            if body not in (None, ""):
                raise ValueError("非文字（N）文章不得保存內文（FR-011、spec Q14）")
        else:
            # F／P 的 body_text 必須非 NULL（data-model §3）。允許空字串：內容缺漏或無法解析的
            # uncertain:* 文章沒有可抽取的文字，存空字串是誠實的表示，不補假內容。
            if body is None:
                raise ValueError("完整度 %s 的文章 body_text 不得為 NULL" % comp)
        for field in ("author_key", "link", "link_norm", "title", "published_at", "fetched_at"):
            if not article.get(field):
                raise ValueError("缺少必填欄位 %s" % field)

    ARTICLE_FIELDS = ("author_key", "guid", "link", "link_norm", "title", "published_at",
                      "fetched_at", "source", "completeness", "classify_reason", "content_html",
                      "body_text", "description", "enclosure_type", "notify_status",
                      "notify_attempts", "notified_at")

    def insert_article_row(self, article):
        """只插入文章列（必須在 transaction() 內呼叫）；回傳新 id。"""
        data = dict(article)
        if data.get("completeness") == "N":
            data["body_text"] = None
        data.setdefault("notify_status", "pending")
        data.setdefault("notify_attempts", 0)
        cols = [c for c in self.ARTICLE_FIELDS if c in data]
        sql = "INSERT INTO article(%s) VALUES (%s)" % (
            ", ".join(cols), ", ".join("?" for _ in cols))
        cur = self.conn.execute(sql, tuple(data.get(c) for c in cols))
        return cur.lastrowid

    def _insert_image_rows(self, article_id, images):
        """同一交易內建立圖片列（status=pending）。"""
        for img in images or ():
            self.conn.execute(
                "INSERT INTO article_image(article_id, seq, src_url, alt, caption, status, "
                "fail_count) VALUES (?,?,?,?,?,?,0)",
                (article_id, int(img["seq"]), img["src_url"], img.get("alt"),
                 img.get("caption"), img.get("status", "pending")))

    def insert_article_with_images(self, article, images=()):
        """單一交易寫入文章與其全部圖片列（FR-009）。重複（含 dedupe_conflict）回 None。"""
        self._validate_article(article)
        if self.find_duplicate(article.get("guid"), article.get("link_norm")):
            return None
        try:
            with self.transaction():
                article_id = self.insert_article_row(article)
                self._insert_image_rows(article_id, images)
        except sqlite3.IntegrityError as exc:
            if "check" in str(exc).lower():
                raise ValueError("文章列違反資料庫層的驗證規則：%s" % exc)
            return None             # 競態：同一篇已被另一個行程寫入，不覆寫（FR-007）
        return article_id

    def find_duplicate(self, guid, link_norm):
        """回傳 None／{'kind':'duplicate'…}／{'kind':'dedupe_conflict'…}（只回傳，不入庫）。"""
        by_guid = None
        if guid not in (None, ""):
            row = self.conn.execute("SELECT id FROM article WHERE guid=?", (guid,)).fetchone()
            by_guid = row[0] if row else None
        by_link = None
        if link_norm not in (None, ""):
            row = self.conn.execute("SELECT id FROM article WHERE link_norm=?",
                                    (link_norm,)).fetchone()
            by_link = row[0] if row else None
        if by_guid and by_link and by_guid != by_link:
            return {"kind": "dedupe_conflict", "guid_article_id": by_guid,
                    "link_article_id": by_link, "article_id": by_guid}
        if by_guid or by_link:
            return {"kind": "duplicate", "article_id": by_guid or by_link,
                    "guid_article_id": by_guid, "link_article_id": by_link}
        return None

    def get_article(self, article_id):
        row = self.conn.execute("SELECT * FROM article WHERE id=?", (article_id,)).fetchone()
        return dict(row) if row else None

    def list_articles(self, author_key=None):
        if author_key:
            return _rows(self.conn.execute(
                "SELECT * FROM article WHERE author_key=? ORDER BY id", (author_key,)))
        return _rows(self.conn.execute("SELECT * FROM article ORDER BY id"))

    # ------------------------------------------------------------------ 有效完整度（視圖）
    def effective_article(self, article_id):
        row = self.conn.execute("SELECT * FROM article_effective WHERE id=?",
                                (article_id,)).fetchone()
        return dict(row) if row else None

    def list_effective_articles(self, author_key=None, completeness=None, limit=None):
        sql = "SELECT * FROM article_effective"
        where, params = [], []
        if author_key:
            where.append("author_key=?")
            params.append(author_key)
        if completeness:
            where.append("effective_completeness=?")
            params.append(completeness)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        if limit:
            sql += " LIMIT %d" % int(limit)
        return _rows(self.conn.execute(sql, tuple(params)))

    def effective_completeness(self, article_id):
        row = self.conn.execute(
            "SELECT effective_completeness FROM article_effective WHERE id=?",
            (article_id,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ 重判紀錄（§1.9，只增不改）
    def add_reclassification(self, article_id, trigger, old_completeness, new_completeness,
                             new_reason, rule_version, derived_body_text=None, run_id=None,
                             at=None):
        changed = 1 if new_completeness != old_completeness else 0
        at = at or self.now_text()
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO reclassification(article_id, at, trigger, old_completeness, "
                "new_completeness, new_reason, rule_version, derived_body_text, changed, run_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (article_id, at, trigger, old_completeness, new_completeness, new_reason,
                 rule_version, derived_body_text, changed, run_id))
            return cur.lastrowid

    def reclassification_rows(self, article_ids=None):
        if article_ids:
            ids = [int(i) for i in article_ids]
            sql = ("SELECT * FROM reclassification WHERE article_id IN (%s) "
                   "ORDER BY article_id, id" % ", ".join("?" for _ in ids))
            return _rows(self.conn.execute(sql, tuple(ids)))
        return _rows(self.conn.execute(
            "SELECT * FROM reclassification ORDER BY article_id, id"))

    def latest_reclassification(self, article_id):
        row = self.conn.execute(
            "SELECT * FROM reclassification WHERE article_id=? ORDER BY id DESC LIMIT 1",
            (article_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ 圖片（§1.3）
    def list_images(self, article_id):
        return _rows(self.conn.execute(
            "SELECT * FROM article_image WHERE article_id=? ORDER BY seq", (article_id,)))

    def images_awaiting_download(self, limit=None):
        sql = ("SELECT * FROM article_image WHERE status IN ('pending','missing') "
               "AND fail_count < ? ORDER BY article_id, seq")
        if limit:
            sql += " LIMIT %d" % int(limit)
        return _rows(self.conn.execute(sql, (MAX_IMAGE_FAILS,)))

    def get_image(self, image_id):
        row = self.conn.execute("SELECT * FROM article_image WHERE id=?", (image_id,)).fetchone()
        return dict(row) if row else None

    def set_image_downloaded(self, image_id, file_path, sha256=None, size_bytes=None, at=None):
        """檔案已經 os.replace 到正式路徑之後才呼叫（research R8）。"""
        at = at or self.now_text()
        with self.transaction():
            self.conn.execute(
                "UPDATE article_image SET status='downloaded', file_path=?, sha256=?, bytes=?, "
                "downloaded_at=?, last_error_code=NULL, fail_count=0 WHERE id=?",
                (file_path, sha256, size_bytes, at, image_id))
        return self.get_image(image_id)

    def set_image_failed(self, image_id, error_code):
        """連續失敗 +1；達上限改 abandoned（排程不再嘗試，PO 可 --retry-images）。"""
        with self.transaction():
            row = self.conn.execute("SELECT fail_count FROM article_image WHERE id=?",
                                    (image_id,)).fetchone()
            if row is None:
                return None
            fail_count = int(row[0]) + 1
            status = "abandoned" if fail_count >= MAX_IMAGE_FAILS else "missing"
            self.conn.execute(
                "UPDATE article_image SET status=?, fail_count=?, last_error_code=? WHERE id=?",
                (status, fail_count, error_code, image_id))
        return self.get_image(image_id)

    def reset_images_for_retry(self, image_ids):
        """PO 要求重試：只接受 missing／abandoned，歸零 fail_count。回傳實際重設的 id。"""
        done = []
        with self.transaction():
            for image_id in image_ids or ():
                row = self.conn.execute("SELECT status FROM article_image WHERE id=?",
                                        (image_id,)).fetchone()
                if row is None or row[0] not in ("missing", "abandoned"):
                    continue
                self.conn.execute(
                    "UPDATE article_image SET status='missing', fail_count=0 WHERE id=?",
                    (image_id,))
                done.append(int(image_id))
        return done

    def image_status_counts(self):
        counts = {s: 0 for s in IMAGE_STATUSES}
        for row in self.conn.execute(
                "SELECT status, COUNT(*) FROM article_image GROUP BY status"):
            counts[row[0]] = row[1]
        return counts

    # ------------------------------------------------------------------ 通知佇列（§1.2、§2.2）
    def articles_awaiting_notify(self):
        """先補發 pending／failed（依發布時間由舊到新）。"""
        return _rows(self.conn.execute(
            "SELECT * FROM article WHERE notify_status IN ('pending','failed') "
            "AND notify_attempts < ? ORDER BY published_at, id", (MAX_NOTIFY_ATTEMPTS,)))

    def record_notify_result(self, article_id, ok, at=None):
        """唯一會 UPDATE article 的路徑，且只動通知欄位（FR-007）。"""
        with self.transaction():
            row = self.conn.execute("SELECT notify_attempts FROM article WHERE id=?",
                                    (article_id,)).fetchone()
            if row is None:
                return None
            attempts = int(row[0]) + 1
            if ok:
                self.conn.execute(
                    "UPDATE article SET notify_status='sent', notify_attempts=?, notified_at=? "
                    "WHERE id=?", (attempts, at or self.now_text(), article_id))
            else:
                status = "abandoned" if attempts >= MAX_NOTIFY_ATTEMPTS else "failed"
                self.conn.execute(
                    "UPDATE article SET notify_status=?, notify_attempts=? WHERE id=?",
                    (status, attempts, article_id))
        return self.get_article(article_id)

    def unnotified_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM article WHERE notify_status IN ('pending','failed')"
        ).fetchone()[0]

    # ------------------------------------------------------------------ 執行與輪詢紀錄（§1.4、§1.5）
    def start_run(self, trigger, schedule_day=None, started_at=None):
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO run(started_at, trigger, schedule_day) VALUES (?,?,?)",
                (started_at or self.now_text(), trigger, schedule_day))
            return cur.lastrowid

    RUN_COUNTERS = ("authors_polled", "authors_skipped_interval", "authors_failed",
                    "new_articles", "images_downloaded", "images_missing",
                    "images_abandoned_now", "notify_sent", "notify_failed", "budget_exhausted")

    def finish_run(self, run_id, result, finished_at=None, **counters):
        cols = ["finished_at=?", "result=?"]
        params = [finished_at or self.now_text(), result]
        for name in self.RUN_COUNTERS:
            if name in counters and counters[name] is not None:
                cols.append("%s=?" % name)
                params.append(int(counters[name]))
        params.append(run_id)
        with self.transaction():
            self.conn.execute("UPDATE run SET %s WHERE id=?" % ", ".join(cols), tuple(params))
        return self.get_run(run_id)

    def get_run(self, run_id):
        row = self.conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def recent_runs(self, limit=5):
        return _rows(self.conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT %d"
                                       % int(limit)))

    def has_actual_scheduled_run(self, schedule_day):
        """FR-017：只看真的執行過的排程列（排除 deferred／already_done）。"""
        placeholders = ", ".join("?" for _ in NON_RUN_RESULTS)
        sql = ("SELECT COUNT(*) FROM run WHERE schedule_day=? "
               "AND trigger IN ('schedule','catchup') "
               "AND (result IS NULL OR result NOT IN (%s))" % placeholders)
        params = (schedule_day,) + NON_RUN_RESULTS
        return self.conn.execute(sql, params).fetchone()[0] > 0

    def add_poll_log(self, run_id=None, author_key=None, at=None, requested=0, http_status=None,
                     outcome=None, items_in_feed=None, new_items=None, skipped_window=None,
                     skipped_no_pubdate=None, all_new=0, duration_ms=None):
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO poll_log(run_id, author_key, at, requested, http_status, outcome, "
                "items_in_feed, new_items, skipped_window, skipped_no_pubdate, all_new, "
                "duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, author_key, at or self.now_text(), 1 if requested else 0, http_status,
                 outcome, items_in_feed, new_items, skipped_window, skipped_no_pubdate,
                 1 if all_new else 0, duration_ms))
            return cur.lastrowid

    def poll_logs(self, run_id=None):
        if run_id is None:
            return _rows(self.conn.execute("SELECT * FROM poll_log ORDER BY id"))
        return _rows(self.conn.execute("SELECT * FROM poll_log WHERE run_id=? ORDER BY id",
                                       (run_id,)))

    # ------------------------------------------------------------------ robots 快取（§1.6）
    def get_robots_cache(self, host):
        row = self.conn.execute("SELECT * FROM robots_cache WHERE host=?", (host,)).fetchone()
        return dict(row) if row else None

    def put_robots_cache(self, host, fetched_at, http_status, body):
        with self.transaction():
            self.conn.execute(
                "INSERT INTO robots_cache(host, fetched_at, http_status, body) VALUES (?,?,?,?) "
                "ON CONFLICT(host) DO UPDATE SET fetched_at=excluded.fetched_at, "
                "http_status=excluded.http_status, body=excluded.body",
                (host, fetched_at, http_status, body))
        return self.get_robots_cache(host)

    # ------------------------------------------------------------------ 統計（--status／健檢）
    def completeness_counts(self, effective=True):
        col = "effective_completeness" if effective else "completeness"
        table = "article_effective" if effective else "article"
        counts = {c: 0 for c in COMPLETENESS}
        for row in self.conn.execute("SELECT %s, COUNT(*) FROM %s GROUP BY %s"
                                     % (col, table, col)):
            counts[row[0]] = row[1]
        counts["reclassified"] = self.conn.execute(
            "SELECT COUNT(DISTINCT article_id) FROM reclassification").fetchone()[0]
        return counts

    def author_status_rows(self):
        return _rows(self.conn.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM article t WHERE t.author_key=a.author_key) "
            "AS articles FROM author a ORDER BY a.author_key"))

    # ------------------------------------------------------------------ 唯讀開庫（健檢、--status）
    @classmethod
    def open_readonly(cls, data_dir):
        """以 SQLite 唯讀模式（mode=ro）開啟既有的庫：不建目錄、不建表、不寫任何東西。"""
        resolved = os.path.realpath(os.path.abspath(data_dir))
        path = os.path.join(resolved, DB_FILENAME)
        if not os.path.isfile(path):
            raise FileNotFoundError("本功能的資料庫尚未建立（找不到 %s）" % DB_FILENAME)
        self = cls.__new__(cls)
        self.data_dir = resolved
        self.db_path = path
        self._now = lambda: datetime.datetime.now(TZ8)
        self._depth = 0
        uri = "file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23")
        self.conn = sqlite3.connect(uri, uri=True, isolation_level=None,
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        return self


# ---------------------------------------------------------------- 空間現況（FR-028、research R4）
def _dir_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def space_status(data_dir):
    """回傳 {'free_gb','db_mb','images_mb'}；取不到就丟例外（呼叫端轉成「無法取得」）。"""
    resolved = os.path.realpath(os.path.abspath(data_dir))
    usage = shutil.disk_usage(resolved)
    db_path = os.path.join(resolved, DB_FILENAME)
    db_bytes = os.path.getsize(db_path) if os.path.isfile(db_path) else 0
    images_dir = os.path.join(resolved, IMAGES_DIRNAME)
    images_bytes = _dir_bytes(images_dir) if os.path.isdir(images_dir) else 0
    return {"free_gb": round(usage.free / (1024.0 ** 3), 1),
            "db_mb": round(db_bytes / (1024.0 ** 2), 1),
            "images_mb": round(images_bytes / (1024.0 ** 2), 1)}


def format_space_line(data_dir):
    """只報現況、不下判定（SC-010）；算不出來就明說「無法取得」，不猜、不省略。"""
    try:
        st = space_status(data_dir)
    except Exception:                                   # noqa: BLE001
        return "空間：無法取得"
    return "空間：剩餘 %.1f GB；%s %.1f MB；圖片 %.1f MB" % (
        st["free_gb"], DB_FILENAME, st["db_mb"], st["images_mb"])
