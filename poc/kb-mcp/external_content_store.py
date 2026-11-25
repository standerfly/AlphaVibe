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
import sqlite3

DB_FILENAME = "external_content.db"

SOURCE_TYPES = ("youtube", "podcast", "article")
SUMMARY_STATUSES = ("confirmed", "revoked")
AUDIT_ACTIONS = ("import", "replace", "delete", "summary_confirm", "summary_revise", "summary_revoke")
CHANNELS = ("http", "stdio")

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
