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
CREATE TABLE IF NOT EXISTS stock_themes (
    code TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
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
    run_at TEXT NOT NULL,
    total_scanned INTEGER,
    benchmark_drawdown_pct REAL,
    benchmark_error TEXT
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
    error TEXT,
    market_drawdown_pct REAL,
    excess_drawdown_pct REAL,
    pbr REAL,
    dividend_yield REAL
);
CREATE INDEX IF NOT EXISTS idx_market_scan_results_run ON market_scan_results(run_id);
CREATE TABLE IF NOT EXISTS laoyutou_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    action TEXT NOT NULL,
    shares REAL,
    price REAL,
    date TEXT NOT NULL,
    reason TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_laoyutou_trades_code ON laoyutou_trades(code, date DESC);
CREATE TABLE IF NOT EXISTS trade_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    action TEXT NOT NULL,
    add_sequence INTEGER,
    shares REAL,
    price REAL,
    date TEXT NOT NULL,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_ledger_code ON trade_ledger(code, date);
CREATE TABLE IF NOT EXISTS module_d_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    strategy_id TEXT,
    trigger_type TEXT NOT NULL,
    finding TEXT NOT NULL,
    suggested_action TEXT,
    conflict_flag INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_module_d_results_code ON module_d_results(code, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_module_d_results_checked_at ON module_d_results(checked_at DESC);
"""

# FR-057 模組D檢視結果表：trigger_type 只允許這三個值（對應通用檢視層／
# 策略專屬層／老芋頭動向比對，見 review_engine.py run_module_d_review()）。
MODULE_D_TRIGGER_TYPES = ("通用層", "策略層", "老芋頭動向")

# _migrate() 用：表名 -> [(欄名, SQLite型別), ...]。回檔／超額跌幅單位一律小數
# （0.095=9.5%，與既有 drawdown_pct／revenue_yoy 一致）；dividend_yield 存百分比
# 數字（3.28=3.28%，與 finmind_client.get_fundamentals 同名欄位一致）。
_MIGRATIONS = {
    "market_scan_runs": [
        ("total_scanned", "INTEGER"),
        ("benchmark_drawdown_pct", "REAL"),
        ("benchmark_error", "TEXT"),
    ],
    "market_scan_results": [
        ("market_drawdown_pct", "REAL"),
        ("excess_drawdown_pct", "REAL"),
        ("pbr", "REAL"),
        ("dividend_yield", "REAL"),
    ],
}

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
        self._migrate()

    def _migrate(self):
        """輕量欄位遷移：CREATE TABLE IF NOT EXISTS 只對全新資料庫有效，
        既有資料庫的表不會自動補新欄位，這裡逐一檢查、缺的才 ALTER TABLE
        補上。不重建表、不清空既有資料列，舊資料列的新欄位值維持 NULL。
        資料驅動、冪等（改動見 _MIGRATIONS）：已經補過的欄位再跑一次不會出錯。"""
        for table, columns in _MIGRATIONS.items():
            existing = {row["name"] for row in
                        self.conn.execute("PRAGMA table_info(%s)" % table)}
            for col_name, col_type in columns:
                if col_name not in existing:
                    self.conn.execute(
                        "ALTER TABLE %s ADD COLUMN %s %s" % (table, col_name, col_type))
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

    # ---------- 投資主題標籤（部位管理組合集中度檢查用；一檔股票僅一個
    # 主題，跟官方 industry_category 是兩回事，見 framework_evidence_based_
    # position_sizing 哲學模組） ----------

    def save_stock_theme(self, code, theme):
        if not code:
            raise ValueError("code 為必填")
        if not theme:
            raise ValueError("theme 為必填")
        updated_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_themes"
            " (code, theme, updated_at) VALUES (?,?,?)",
            (code, theme, updated_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code, "theme": theme,
                "updated_at": updated_at}

    def get_stock_theme(self):
        rows = self.conn.execute(
            "SELECT code, theme, updated_at FROM stock_themes"
        ).fetchall()
        return {r["code"]: {"theme": r["theme"],
                            "updated_at": r["updated_at"]} for r in rows}

    # ---------- 老芋頭交易表（FR-044）：老芋頭是PO信任的資深投資朋友／
    # 導師（非系統使用者，屬訊號來源），這裡結構化記錄他的進出，供模組D
    # FR-053「老芋頭動向比對」與模組G策略對照使用。他不一定每次都寫
    # 原因，故 reason 允許為空。 ----------

    def save_laoyutou_trade(self, code, name, action, shares, price, date,
                            reason=None, source_ref=None):
        if not code:
            raise ValueError("code 為必填")
        if action not in ("買", "賣"):
            raise ValueError("action 必須是「買」或「賣」：%r" % action)
        if not date:
            raise ValueError("date 為必填")
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO laoyutou_trades (code, name, action, shares, price,"
            " date, reason, source_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (code, name, action, shares, price, date, reason, source_ref, created_at),
        )
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "code": code,
                "action": action, "date": date}

    def get_laoyutou_trades(self, code=None, limit=20):
        """不給 code：列出最近 N 筆（跨所有標的，依 date DESC）；
        給 code：列出該標的的老芋頭交易歷史（同樣依 date DESC、上限 limit）。"""
        limit = int(limit or 20)
        if code:
            rows = self.conn.execute(
                "SELECT * FROM laoyutou_trades WHERE code=?"
                " ORDER BY date DESC, id DESC LIMIT ?", (code, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM laoyutou_trades ORDER BY date DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {"code": code, "count": len(rows), "trades": [dict(r) for r in rows]}

    # ---------- 交易流水表（FR-056）：PO 自己的加碼流水（跟上面老芋頭的
    # 交易表是兩張不同的表），取代 holdings 快照覆蓋式的限制，供 FR-054
    # 部位控制建議計算「這檔股票已經加碼過幾次」。取捨：add_sequence
    # 是「買」side 才有意義的加碼序號概念，賣出動作跟加碼次序無關——
    # 這裡選擇賣出時一律強制寫入 NULL（而非 0），一來語意上「不適用」
    # 比「第 0 次加碼」更精確，二來讓呼叫端可以用
    # "WHERE add_sequence IS NOT NULL" 篩出買入紀錄來推算下一次加碼序號，
    # 不必額外用 action 欄位過濾。 ----------

    def save_trade_ledger_entry(self, code, name, action, shares, price, date,
                                add_sequence=None, source_ref=None):
        if not code:
            raise ValueError("code 為必填")
        if action not in ("買", "賣"):
            raise ValueError("action 必須是「買」或「賣」：%r" % action)
        if not date:
            raise ValueError("date 為必填")
        if action == "賣":
            add_sequence = None
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO trade_ledger (code, name, action, add_sequence, shares,"
            " price, date, source_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (code, name, action, add_sequence, shares, price, date, source_ref,
             created_at),
        )
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "code": code, "action": action,
                "add_sequence": add_sequence, "date": date}

    def get_trade_ledger(self, code):
        """回傳該標的完整加碼流水（依 date、id 排序，舊到新），讓呼叫方能
        數出目前買入筆數（add_sequence 非 NULL 的列）來推算下一次加碼序號。"""
        if not code:
            raise ValueError("code 為必填")
        rows = self.conn.execute(
            "SELECT * FROM trade_ledger WHERE code=? ORDER BY date, id", (code,),
        ).fetchall()
        return {"code": code, "count": len(rows), "entries": [dict(r) for r in rows]}

    # ---------- 模組D檢視結果表（FR-051~055/057）：模組E排程整合跑完
    # 模組D後，結果持久化在這裡，供模組F（報告呈現，下一輪）直接讀取，
    # 不即時運算。一檔標的每次檢視會有多筆（通用層2筆＋策略層N筆＋
    # 老芋頭層0或1筆），皆屬正常設計，不是重複資料。 ----------

    def save_module_d_result(self, code, trigger_type, finding, strategy_id=None,
                             suggested_action=None, conflict_flag=False, checked_at=None):
        if not code:
            raise ValueError("code 為必填")
        if trigger_type not in MODULE_D_TRIGGER_TYPES:
            raise ValueError("trigger_type 必須是「通用層」「策略層」或「老芋頭動向」之一：%r"
                             % trigger_type)
        if not finding:
            raise ValueError("finding 為必填")
        checked_at = checked_at or _now()
        cur = self.conn.execute(
            "INSERT INTO module_d_results (code, strategy_id, trigger_type, finding,"
            " suggested_action, conflict_flag, checked_at) VALUES (?,?,?,?,?,?,?)",
            (code, strategy_id, trigger_type, finding, suggested_action,
             1 if conflict_flag else 0, checked_at),
        )
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "code": code,
                "trigger_type": trigger_type, "checked_at": checked_at}

    def get_module_d_results(self, code=None, date=None, limit=50):
        """給code：列出該標的全部檢視記錄（不限日期，依checked_at DESC，
        上限limit）。不給code：列出當天（或指定date，格式YYYY-MM-DD）
        全部標的的記錄——用於儀表板「今天有哪些標的被檢查過」。"""
        limit = int(limit or 50)
        if code:
            rows = self.conn.execute(
                "SELECT * FROM module_d_results WHERE code=?"
                " ORDER BY checked_at DESC, id DESC LIMIT ?", (code, limit),
            ).fetchall()
            return {"code": code, "date": None, "count": len(rows),
                    "results": [dict(r) for r in rows]}
        date = date or _today()
        rows = self.conn.execute(
            "SELECT * FROM module_d_results WHERE checked_at LIKE ?"
            " ORDER BY checked_at DESC, id DESC LIMIT ?", (date + "%", limit),
        ).fetchall()
        return {"code": None, "date": date, "count": len(rows),
                "results": [dict(r) for r in rows]}

    def get_associated_frameworks(self, code):
        """FR-052 策略關聯判斷用：這支代碼在全市場批次篩選歷史中，曾經
        符合門檻（meets_framework=1）過的框架代號清單（不重複、跨所有
        run，非只看最新一次）。

        刻意查「曾經符合過」而非「目前最新一次run裡是否仍符合」：
        策略專屬層（strategy_specific_review／FR-052）要檢查的正是「當初
        篩進來後，這套策略的假說現在是否已經失效」——如果改成只看最新一次
        run 是否仍符合entry門檻，一旦假說真的開始失效（entry條件不再滿足，
        例如PEG回升），這支代碼會從最新run的meets清單消失，導致策略關聯
        判斷也跟著清空、invalidation檢查從此停止，恰好是最需要提醒的時候
        卻不再提醒——這是不可接受的行為，因此改為查全部歷史run。

        market_scan_results 表本身沒有 framework_id 欄位（存在
        market_scan_runs），故需 JOIN。從沒被 market_scan 篩中過的標的
        （PO手動加入觀察名單、或老芋頭訊號帶進來的）回傳空list，這是
        正常情況，不是錯誤。
        """
        rows = self.conn.execute(
            "SELECT DISTINCT r.framework_id FROM market_scan_results res"
            " JOIN market_scan_runs r ON r.id = res.run_id"
            " WHERE res.code=? AND res.meets_framework=1"
            " ORDER BY r.framework_id", (code,),
        ).fetchall()
        return [row["framework_id"] for row in rows]

    # ---------- 第二層全市場批次篩選快取（market_scan.py 用） ----------

    def save_market_scan_run(self, framework_id, trigger_source, rows,
                             candidate_count, market_errors=None, total_scanned=None,
                             benchmark=None):
        """存一次market_scan.run_scan()的完整結果（一筆run + 該批所有result列）。

        total_scanned＝本次實際掃描的公司總數（TWSE+TPEx月營收批次列數，
        比candidate_count更大的母體數字）；省略則存NULL（例如舊呼叫端還
        沒更新，不強制要求，如實反映「這筆資料沒有這項資訊」）。

        benchmark＝可選 dict（例如 benchmark.load_benchmark() 的回傳值），取其
        window_drawdown_pct／error 存進 run 層的 benchmark_drawdown_pct／
        benchmark_error 兩欄，作為這次掃描當下的大盤基準脈絡；省略則兩欄皆
        存 NULL，不強制要求。
        """
        market_errors = market_errors or {}
        benchmark = benchmark or {}
        run_at = _now()
        meets_count = sum(1 for r in rows if r.get("meets_framework"))
        cur = self.conn.execute(
            "INSERT INTO market_scan_runs (framework_id, trigger_source,"
            " candidate_count, meets_count, twse_error, tpex_error, run_at,"
            " total_scanned, benchmark_drawdown_pct, benchmark_error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (framework_id, trigger_source, candidate_count, meets_count,
             market_errors.get("TWSE"), market_errors.get("TPEx"), run_at,
             total_scanned, benchmark.get("window_drawdown_pct"), benchmark.get("error")),
        )
        run_id = cur.lastrowid
        for row in rows:
            self.conn.execute(
                "INSERT INTO market_scan_results (run_id, code, name, market,"
                " industry, per, revenue_yoy, revenue_period, drawdown_pct,"
                " high_price, high_date, current_price, current_date, peg,"
                " meets_framework, error, market_drawdown_pct, excess_drawdown_pct,"
                " pbr, dividend_yield)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, row.get("code"), row.get("name"), row.get("market"),
                 row.get("industry"), row.get("per"), row.get("revenue_yoy"),
                 row.get("revenue_period"), row.get("drawdown_pct"),
                 row.get("high_price"), row.get("high_date"), row.get("current_price"),
                 row.get("current_date"), row.get("peg"),
                 1 if row.get("meets_framework") else 0, row.get("error"),
                 row.get("market_drawdown_pct"), row.get("excess_drawdown_pct"),
                 row.get("pbr"), row.get("dividend_yield")),
            )
        self.conn.commit()
        return {"run_id": run_id, "run_at": run_at, "meets_count": meets_count}

    def get_latest_market_scan(self, framework_id=None, meets_only=False,
                               limit=None, order_by="peg"):
        """查最近一次全市場批次篩選結果。不給framework_id則查全部框架中最新一筆。

        meets_only／limit／order_by 皆為可選；預設值（False／None／"peg"）下
        行為與改動前完全一致（不篩、不截、依PEG升冪）。meets_only=True 只回傳
        meets_framework=1 的列；limit 給正整數才截斷，None／0 皆不截；
        order_by="excess_drawdown" 改依超額跌幅降冪（None 排最後），其餘值一律
        視為預設的PEG升冪。回傳新增 total_results（篩選後、截斷前的總列數）與
        returned（實際回傳列數），讓呼叫端能誠實說明是否截掉了資料。
        """
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

        where_clause = "WHERE run_id=?"
        params = [run["id"]]
        if meets_only:
            where_clause += " AND meets_framework=1"

        total_results = self.conn.execute(
            "SELECT COUNT(*) c FROM market_scan_results %s" % where_clause, params
        ).fetchone()["c"]

        if order_by == "excess_drawdown":
            order_clause = "ORDER BY (excess_drawdown_pct IS NULL), excess_drawdown_pct DESC"
        else:
            order_clause = "ORDER BY (peg IS NULL), peg ASC"

        sql = "SELECT * FROM market_scan_results %s %s" % (where_clause, order_clause)
        if limit:
            sql += " LIMIT ?"
            params = params + [limit]

        results = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        return {"found": True, "run": dict(run), "results": results,
                "total_results": total_results, "returned": len(results)}

    def get_market_scan_run(self, run_id):
        """依主鍵查單一筆批次篩選run，查無則回傳None。"""
        row = self.conn.execute(
            "SELECT * FROM market_scan_runs WHERE id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_market_scan_result(self, run_id, code):
        """依run_id+code查單一筆候選的完整結果列，查無則回傳None。

        `/market-scan/track`（加入追蹤功能）用這個從資料庫重新取值組
        追蹤理由，不信任表單裡的隱藏欄位內容。
        """
        row = self.conn.execute(
            "SELECT * FROM market_scan_results WHERE run_id=? AND code=?",
            (run_id, code),
        ).fetchone()
        return dict(row) if row else None

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
