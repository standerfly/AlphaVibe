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
CREATE TABLE IF NOT EXISTS stock_aliases (
    name TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    name_full TEXT,
    market TEXT,
    source TEXT,
    verified_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_prices (
    code TEXT PRIMARY KEY,
    price REAL NOT NULL,
    price_date TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_industries (
    code TEXT PRIMARY KEY,
    industry_category TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    meets_count INTEGER NOT NULL,
    twse_error TEXT,
    tpex_error TEXT,
    run_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_scan_runs ON market_scan_runs(framework_id, run_at DESC);
CREATE TABLE IF NOT EXISTS market_scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    market TEXT,
    industry TEXT,
    per REAL,
    revenue_yoy REAL,
    revenue_period TEXT,
    drawdown_pct REAL,
    high_price REAL,
    high_date TEXT,
    current_price REAL,
    current_date TEXT,
    peg REAL,
    meets_framework INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_scan_results_run ON market_scan_results(run_id);
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

    def save_comments_batch(self, comments):
        """一次存入多筆評論；個別筆缺必填欄位只該筆失敗，不影響其餘筆數。

        內部重用 save_comment 的實際寫入邏輯（同一份程式碼），避免兩份邏輯
        日後不同步。
        """
        if not isinstance(comments, list):
            raise ValueError("comments 必須是陣列")
        results = []
        saved_count = 0
        for idx, item in enumerate(comments):
            if not isinstance(item, dict):
                results.append({"index": idx, "saved": False,
                                "error": "每筆評論必須是物件"})
                continue
            body = item.get("body")
            source_tag = item.get("source_tag")
            missing = [f for f, v in (("body", body), ("source_tag", source_tag)) if not v]
            if missing:
                results.append({"index": idx, "saved": False,
                                "error": "缺少必填欄位：%s" % "、".join(missing)})
                continue
            out = self.save_comment(
                body=body, source_tag=source_tag,
                date=item.get("date"), symbols=item.get("symbols"),
                source_ref=item.get("source_ref"),
            )
            results.append({"index": idx, "saved": True,
                            "date": out["date"], "source_tag": out["source_tag"]})
            saved_count += 1
        return {"total": len(comments), "saved_count": saved_count,
                "failed_count": len(comments) - saved_count, "results": results}

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

    # ---------- 輔助：股票名稱→代碼查證快取 ----------

    def save_stock_alias(self, name, code, name_full=None, market=None,
                         source=None, verified_date=None):
        if not name or not code:
            raise ValueError("name 與 code 為必填")
        verified_date = verified_date or _today()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_aliases"
            " (name, code, name_full, market, source, verified_date)"
            " VALUES (?,?,?,?,?,?)",
            (name, code, name_full, market, source, verified_date),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM stock_aliases WHERE name=?", (name,)
        ).fetchone()
        return {"saved": True, "record": dict(row)}

    def get_stock_alias(self, name=None):
        if name:
            row = self.conn.execute(
                "SELECT * FROM stock_aliases WHERE name=?", (name,)
            ).fetchone()
            if not row:
                return {"found": False, "name": name}
            return {"found": True, "record": dict(row)}
        rows = self.conn.execute(
            "SELECT * FROM stock_aliases ORDER BY verified_date DESC, name"
        ).fetchall()
        return {"count": len(rows), "aliases": [dict(r) for r in rows]}

    # ---------- 股價／產業別快取（refresh_holdings_prices 用；手機檢視頁市值/
    # 持股比例/產業別皆讀這裡，不即時呼叫外部 API） ----------

    def upsert_stock_price(self, code, price, price_date):
        if not code:
            raise ValueError("code 為必填")
        updated_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_prices"
            " (code, price, price_date, updated_at) VALUES (?,?,?,?)",
            (code, price, price_date, updated_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code, "price": price,
                "price_date": price_date, "updated_at": updated_at}

    def get_stock_prices(self):
        rows = self.conn.execute(
            "SELECT code, price, price_date, updated_at FROM stock_prices"
        ).fetchall()
        return {r["code"]: {"price": r["price"], "price_date": r["price_date"],
                            "updated_at": r["updated_at"]} for r in rows}

    def upsert_stock_industry(self, code, industry_category):
        if not code:
            raise ValueError("code 為必填")
        updated_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_industries"
            " (code, industry_category, updated_at) VALUES (?,?,?)",
            (code, industry_category, updated_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code,
                "industry_category": industry_category, "updated_at": updated_at}

    def get_stock_industries(self):
        rows = self.conn.execute(
            "SELECT code, industry_category, updated_at FROM stock_industries"
        ).fetchall()
        return {r["code"]: {"industry_category": r["industry_category"],
                            "updated_at": r["updated_at"]} for r in rows}

    # ---------- 第二層全市場批次篩選快取（market_scan.py 用） ----------

    def save_market_scan_run(self, framework_id, trigger_source, rows,
                             candidate_count, market_errors=None):
        """存一次market_scan.run_scan()的完整結果（一筆run + 該批所有result列）。"""
        market_errors = market_errors or {}
        run_at = _now()
        meets_count = sum(1 for r in rows if r.get("meets_framework"))
        cur = self.conn.execute(
            "INSERT INTO market_scan_runs (framework_id, trigger_source,"
            " candidate_count, meets_count, twse_error, tpex_error, run_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (framework_id, trigger_source, candidate_count, meets_count,
             market_errors.get("TWSE"), market_errors.get("TPEx"), run_at),
        )
        run_id = cur.lastrowid
        for row in rows:
            self.conn.execute(
                "INSERT INTO market_scan_results (run_id, code, name, market,"
                " industry, per, revenue_yoy, revenue_period, drawdown_pct,"
                " high_price, high_date, current_price, current_date, peg,"
                " meets_framework, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, row.get("code"), row.get("name"), row.get("market"),
                 row.get("industry"), row.get("per"), row.get("revenue_yoy"),
                 row.get("revenue_period"), row.get("drawdown_pct"),
                 row.get("high_price"), row.get("high_date"), row.get("current_price"),
                 row.get("current_date"), row.get("peg"),
                 1 if row.get("meets_framework") else 0, row.get("error")),
            )
        self.conn.commit()
        return {"run_id": run_id, "run_at": run_at, "meets_count": meets_count}

    def get_latest_market_scan(self, framework_id=None):
        """查最近一次全市場批次篩選結果。不給framework_id則查全部框架中最新一筆。"""
        if framework_id:
            run = self.conn.execute(
                "SELECT * FROM market_scan_runs WHERE framework_id=?"
                " ORDER BY run_at DESC, id DESC LIMIT 1",
                (framework_id,),
            ).fetchone()
        else:
            run = self.conn.execute(
                "SELECT * FROM market_scan_runs ORDER BY run_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if run is None:
            return {"found": False, "run": None, "results": []}
        results = self.conn.execute(
            "SELECT * FROM market_scan_results WHERE run_id=?"
            " ORDER BY (peg IS NULL), peg ASC",
            (run["id"],),
        ).fetchall()
        return {"found": True, "run": dict(run),
                "results": [dict(r) for r in results]}

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
