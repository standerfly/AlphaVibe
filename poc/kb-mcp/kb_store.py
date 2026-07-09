"""AlphaVibe 三層知識庫儲存層。

Layer 1 投資哲學：data_dir/philosophy/ 下的 .md 檔（Q-013、FR-014）
Layer 2 個股立場：SQLite stances 表，保留歷史（FR-003、FR-017）
Layer 3 每日評論：SQLite FTS5 全文檢索，trigram tokenizer 支援中文子字串查詢（Q-015、FR-012/016）

立場衝突（FR-013/FR-018）：save_stance 遇到與既有立場不同時不寫入，
回傳 conflict 資訊，由呼叫端（AI＋使用者）確認後帶 overwrite=True 重試——
這是 Q-021「即時確認制」的落地。

限制：Python 3.9 相容、僅標準庫；FTS5 trigram 查詢至少 3 個字元。
"""
import datetime
import os
import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS stances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    stance TEXT NOT NULL,
    reason TEXT,
    date TEXT NOT NULL,
    entry_condition TEXT,
    valuation_metric TEXT,
    time_horizon TEXT,
    risk_factor TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stances_code ON stances(code, id);
CREATE VIRTUAL TABLE IF NOT EXISTS comments USING fts5(
    body, symbols, source_tag,
    date UNINDEXED, source_ref UNINDEXED, created_at UNINDEXED,
    tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    snapshot_date TEXT NOT NULL,
    price_at_time REAL,
    valuation_at_time TEXT,
    thesis TEXT NOT NULL,
    risks TEXT,
    watch_next TEXT,
    framework_version TEXT,
    model_id TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_code ON snapshots(code, id);
CREATE TABLE IF NOT EXISTS snapshot_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    url TEXT,
    title TEXT,
    retrieved_at TEXT,
    quote_summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshot_sources ON snapshot_sources(snapshot_id);
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    shares REAL,
    avg_cost REAL,
    snapshot_date TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdings_code ON holdings(code, snapshot_date);
"""

STANCE_FIELDS = (
    "code", "name", "stance", "reason", "date", "entry_condition",
    "valuation_metric", "time_horizon", "risk_factor", "source_ref",
)

_MODULE_NAME_RE = re.compile(r"^[\w\-一-鿿]+$")


def _today():
    return datetime.date.today().isoformat()


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class KBStore:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(data_dir)
        self.philosophy_dir = os.path.join(self.data_dir, "philosophy")
        os.makedirs(self.philosophy_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "alphavibe.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- Layer 2：個股立場 ----------

    def get_latest_stance(self, code):
        row = self.conn.execute(
            "SELECT * FROM stances WHERE code=? ORDER BY date DESC, id DESC LIMIT 1",
            (code,),
        ).fetchone()
        return dict(row) if row else None

    def get_stance_history(self, code, limit=10):
        rows = self.conn.execute(
            "SELECT * FROM stances WHERE code=? ORDER BY date DESC, id DESC LIMIT ?",
            (code, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_stances(self):
        rows = self.conn.execute(
            "SELECT * FROM stances WHERE id IN "
            "(SELECT max(id) FROM stances GROUP BY code) ORDER BY code"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_stance(self, code, stance, name=None, reason=None, date=None,
                    entry_condition=None, valuation_metric=None,
                    time_horizon=None, risk_factor=None, source_ref=None,
                    overwrite=False):
        date = date or _today()
        existing = self.get_latest_stance(code)
        conflict = bool(existing and existing["stance"] != stance)
        if conflict and not overwrite:
            return {
                "saved": False,
                "conflict": True,
                "existing": existing,
                "hint": ("⚠️ 立場衝突（FR-013/FR-018）：新立場「%s」與既有立場「%s」"
                         "（%s）不同。請向使用者列出兩者並確認，確認更新後以 "
                         "overwrite=true 重新呼叫；使用者不同意則略過。"
                         % (stance, existing["stance"], existing["date"])),
            }
        values = (code, name, stance, reason, date, entry_condition,
                  valuation_metric, time_horizon, risk_factor, source_ref, _now())
        cur = self.conn.execute(
            "INSERT INTO stances (code, name, stance, reason, date,"
            " entry_condition, valuation_metric, time_horizon, risk_factor,"
            " source_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        self.conn.commit()
        record = self.conn.execute(
            "SELECT * FROM stances WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return {"saved": True, "conflict": conflict, "record": dict(record)}

    # ---------- Layer 3：每日評論 ----------

    def save_comment(self, body, source_tag, date=None, symbols=None,
                     source_ref=None):
        self.conn.execute(
            "INSERT INTO comments (body, symbols, source_tag, date,"
            " source_ref, created_at) VALUES (?,?,?,?,?,?)",
            (body, symbols or "", source_tag, date or _today(),
             source_ref or "", _now()),
        )
        self.conn.commit()
        return {"saved": True, "date": date or _today(), "source_tag": source_tag}

    def search_comments(self, query, limit=10):
        if len(query.strip()) < 3:
            return {"error": "FTS5 trigram 查詢至少需要 3 個字元", "results": []}
        fts_query = '"%s"' % query.replace('"', '""')
        rows = self.conn.execute(
            "SELECT body, symbols, source_tag, date, source_ref"
            " FROM comments WHERE comments MATCH ? ORDER BY date DESC LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return {"count": len(rows), "results": [dict(r) for r in rows]}

    def recent_comments(self, limit=10):
        rows = self.conn.execute(
            "SELECT body, symbols, source_tag, date, source_ref"
            " FROM comments ORDER BY date DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"count": len(rows), "results": [dict(r) for r in rows]}

    # ---------- 追溯層：分析快照與來源（FR-026/027/028，Q-036） ----------

    def save_snapshot(self, code, thesis, name=None, snapshot_date=None,
                      price_at_time=None, valuation_at_time=None, risks=None,
                      watch_next=None, framework_version=None, model_id=None,
                      source_ref=None, sources=None):
        snapshot_date = snapshot_date or _today()
        cur = self.conn.execute(
            "INSERT INTO snapshots (code, name, snapshot_date, price_at_time,"
            " valuation_at_time, thesis, risks, watch_next, framework_version,"
            " model_id, source_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, name, snapshot_date, price_at_time, valuation_at_time,
             thesis, risks, watch_next, framework_version, model_id,
             source_ref, _now()),
        )
        sid = cur.lastrowid
        saved_sources = 0
        for src in (sources or []):
            self.conn.execute(
                "INSERT INTO snapshot_sources (snapshot_id, url, title,"
                " retrieved_at, quote_summary) VALUES (?,?,?,?,?)",
                (sid, src.get("url"), src.get("title"),
                 src.get("retrieved_at") or _today(),
                 src.get("quote_summary")),
            )
            saved_sources += 1
        self.conn.commit()
        return {"saved": True, "snapshot_id": sid, "code": code,
                "snapshot_date": snapshot_date, "sources_saved": saved_sources}

    def get_snapshots(self, code, limit=10):
        rows = self.conn.execute(
            "SELECT * FROM snapshots WHERE code=?"
            " ORDER BY snapshot_date DESC, id DESC LIMIT ?",
            (code, limit),
        ).fetchall()
        snapshots = []
        for row in rows:
            snap = dict(row)
            snap["sources"] = [dict(s) for s in self.conn.execute(
                "SELECT url, title, retrieved_at, quote_summary"
                " FROM snapshot_sources WHERE snapshot_id=?", (row["id"],)
            ).fetchall()]
            snapshots.append(snap)
        return {"code": code, "count": len(snapshots), "snapshots": snapshots}

    def list_latest_snapshots(self):
        rows = self.conn.execute(
            "SELECT s.*, (SELECT count(*) FROM snapshot_sources ss"
            "  WHERE ss.snapshot_id = s.id) AS source_count"
            " FROM snapshots s WHERE s.id IN"
            " (SELECT max(id) FROM snapshots GROUP BY code) ORDER BY s.code"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 持股快照（FR-029，Q-035：不含損益計算） ----------

    def save_holdings(self, rows, snapshot_date=None, source_ref=None):
        if not rows or not isinstance(rows, list):
            raise ValueError("rows 必須是非空的持股清單")
        snapshot_date = snapshot_date or _today()
        for r in rows:
            if not r.get("code"):
                raise ValueError("每筆持股都必須有 code：%r" % r)
            self.conn.execute(
                "INSERT INTO holdings (code, name, shares, avg_cost,"
                " snapshot_date, source_ref, created_at) VALUES (?,?,?,?,?,?,?)",
                (r["code"], r.get("name"), r.get("shares"), r.get("avg_cost"),
                 snapshot_date, source_ref, _now()),
            )
        self.conn.commit()
        return {"saved": True, "count": len(rows),
                "snapshot_date": snapshot_date}

    def get_holdings(self, code=None):
        if code:
            rows = self.conn.execute(
                "SELECT * FROM holdings WHERE code=?"
                " ORDER BY snapshot_date DESC, id DESC", (code,)
            ).fetchall()
            return {"code": code, "count": len(rows),
                    "history": [dict(r) for r in rows]}
        latest = self.conn.execute(
            "SELECT max(snapshot_date) AS d FROM holdings").fetchone()["d"]
        if latest is None:
            return {"snapshot_date": None, "count": 0, "holdings": []}
        rows = self.conn.execute(
            "SELECT * FROM holdings WHERE snapshot_date=? ORDER BY code",
            (latest,),
        ).fetchall()
        return {"snapshot_date": latest, "count": len(rows),
                "holdings": [dict(r) for r in rows]}

    # ---------- Layer 1：投資哲學 ----------

    def _module_path(self, module):
        if not _MODULE_NAME_RE.match(module):
            raise ValueError("模組名稱只能含中英數、底線、連字號：%r" % module)
        return os.path.join(self.philosophy_dir, module + ".md")

    def save_philosophy(self, module, content, mode="append"):
        path = self._module_path(module)
        if mode not in ("append", "replace"):
            raise ValueError("mode 必須是 append 或 replace")
        if mode == "append" and os.path.exists(path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n\n" + content.strip() + "\n")
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content.strip() + "\n")
        return {"saved": True, "module": module, "mode": mode,
                "size": os.path.getsize(path)}

    def list_philosophy(self):
        modules = []
        for fn in sorted(os.listdir(self.philosophy_dir)):
            if fn.endswith(".md"):
                path = os.path.join(self.philosophy_dir, fn)
                modules.append({"module": fn[:-3], "size": os.path.getsize(path)})
        return {"count": len(modules), "modules": modules}

    def get_philosophy(self, module):
        path = self._module_path(module)
        if not os.path.exists(path):
            return {"error": "模組不存在：%s" % module,
                    "available": [m["module"] for m in self.list_philosophy()["modules"]]}
        with open(path, encoding="utf-8") as fh:
            return {"module": module, "content": fh.read()}
