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
import json
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
CREATE TABLE IF NOT EXISTS stock_valuation_snapshots (
    code TEXT PRIMARY KEY,
    per REAL,
    pbr REAL,
    dividend_yield REAL,
    revenue_yoy REAL,
    revenue_period TEXT,
    valuation_data_source TEXT,
    revenue_data_source TEXT,
    valuation_error TEXT,
    revenue_error TEXT,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exit_thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    reason TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exit_thresholds_code ON exit_thresholds(code, id DESC);
CREATE TABLE IF NOT EXISTS stock_price_history (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_price_history_code ON stock_price_history(code, date);
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
CREATE TABLE IF NOT EXISTS revenue_yoy_cache (
    code TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_score_cache (
    code TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS financial_metrics_cache (
    code TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS position_plans (
    code TEXT PRIMARY KEY,
    plan_amount REAL NOT NULL,
    note TEXT,
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
CREATE TABLE IF NOT EXISTS asset_pockets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount REAL,
    note TEXT,
    sort_order INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS asset_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    note TEXT,
    archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS asset_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pocket_id INTEGER NOT NULL REFERENCES asset_pockets(id),
    account_id INTEGER NOT NULL REFERENCES asset_accounts(id),
    amount REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    UNIQUE(pocket_id, account_id)
);
CREATE TABLE IF NOT EXISTS asset_buildup_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pocket_id INTEGER NOT NULL REFERENCES asset_pockets(id),
    account_id INTEGER NOT NULL REFERENCES asset_accounts(id),
    label TEXT NOT NULL,
    total_months INTEGER NOT NULL,
    monthly_target_amount REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS asset_buildup_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES asset_buildup_plans(id),
    month_number INTEGER NOT NULL,
    planned_amount REAL,
    actual_amount REAL,
    completed_at TEXT,
    note TEXT,
    UNIQUE(plan_id, month_number)
);
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
    "trade_ledger": [
        ("order_ref", "TEXT"),
    ],
    "stock_prices": [
        ("prev_close", "REAL"),
    ],
    "module_d_results": [
        # concern_flag（2026-08-01 新增，個股頁背景刷新機制用）：
        # run_module_d_review() 內部 items 清單本來就有這個布林值，但先前
        # save_module_d_result() 沒有把它存下來——只存了語意不同的
        # conflict_flag（自動回寫立場時是否跟既有記錄衝突，屬批次層級
        # 旗標，不是逐項的「這項發現要不要留意」）。清單頁／個股詳情頁要
        # 讀「最新一批檢視結果裡有沒有需留意的項目」，需要這個逐項欄位；
        # 既有「今日重點」（_render_today_highlights_section）改用
        # suggested_action 判斷、不受影響，這裡新增欄位不動它。
        ("concern_flag", "INTEGER DEFAULT 0"),
        # trigger_label（2026-08-19 新增，個股詳情頁 Checks 分組用）：
        # run_module_d_review() 內部 items 早就算出細分標籤（「通用層／
        # 成長趨緩」「通用層／下檔風險」「策略層／<id>」），但先前只存了
        # 粗分的 trigger_type（僅三個值）——導致頁面拿到兩筆都是「通用層」
        # 的資料，分不出哪筆是成長趨緩、哪筆是下檔風險，只能靠解析 finding
        # 文字硬猜（脆弱）。存下來才能把 Checks 依實際檢查項目分組呈現。
        # 舊資料為 NULL，讀取端退回顯示 trigger_type，不用回填。
        ("trigger_label", "TEXT"),
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
        # 2026-08-22 教訓：check_same_thread=False 是必要的，不是隨手加的
        # 選項。report_server.py（ThreadingHTTPServer）每個請求從頭到尾
        # 都在同一條執行緒處理，原本不需要這個參數；但 app/deps.py 的
        # get_kb_store() 是 FastAPI 的 sync generator dependency，
        # Starlette 用 anyio thread pool 執行——同一個 request 的
        # 「建立」（yield 前）跟「關閉」（finally，yield 後）**不保證
        # 在同一條 pool worker thread 上執行**，正式環境併發測試 30 個
        # request 有 23 個因為這個原因 500（sqlite3.ProgrammingError:
        # SQLite objects created in a thread can only be used in that
        # same thread）。這裡的用法本身沒有真正跨執行緒併發存取同一個
        # connection（每個 request 各自建立、各自關閉，生命週期不重疊），
        # 只是「同一段邏輯的不同階段」剛好被排到不同 thread，
        # check_same_thread=False 關掉的正是這個誤判，不是關掉真正的
        # 併發保護——sqlite3 連線本身仍然只會被單一 request 依序使用。
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()
        # 2026-08-22 教訓：這裡原本無條件呼叫 self._seed_asset_defaults()，
        # 導致「任何」建立 KBStore 的呼叫端都會觸發種子資料寫入——不只是
        # 新 app/ 的測試埠，連 market_scan.py 這種每天 02:00 排程、每次
        # 都重新讀取磁碟上最新 kb_store.py 的既有腳本也會中招（排程本身
        # 沒有錯，錯在這裡把「使用者資料初始化」跟「物件建構」綁在一起）。
        # 修正：種子資料改成完全獨立、需要明確呼叫的動作，見
        # seed_asset_defaults()（已移除前導底線，開放給外部明確呼叫）與
        # poc/kb-mcp/seed_assets_once.py。KBStore.__init__() 之後不會再
        # 因為「表是空的」就自動寫入任何資料。

    def seed_asset_defaults(self):
        """資產分頁初始種子資料（Q-046 第5節 Step 4）：只在 asset_pockets
        表完全空的時候寫入一次，重複呼叫不會重複塞資料——這是使用者現在
        的真實現況（口袋/帳戶/初始餘額/建倉計畫進度），不是 demo 假資料，
        改動前請先跟需求方（roadmap.md Q-046）核對數字。

        **這個方法不會被 KBStore.__init__() 自動呼叫**（2026-08-22 教訓，
        見 __init__ 內的說明）——只能由呼叫端明確呼叫，目前唯一的呼叫點
        是 poc/kb-mcp/seed_assets_once.py，一次性、由人手動執行。

        寫入順序：口袋 → 帳戶 → 餘額 → 建倉計畫 → 10 筆進度 entries，
        全部在同一個 transaction 內完成（任何一步失敗就整批不寫入，避免
        半套資料）。"""
        existing = self.conn.execute(
            "SELECT COUNT(*) AS c FROM asset_pockets").fetchone()["c"]
        if existing:
            return

        pockets = [
            ("緊急預備金", 600000),
            ("危機加碼緩衝", 500000),
            ("核心0050累積", 1200000),
            ("衛星倉位", 500000),
        ]
        pocket_ids = {}
        for name, target in pockets:
            cur = self.conn.execute(
                "INSERT INTO asset_pockets (name, target_amount) VALUES (?, ?)",
                (name, target),
            )
            pocket_ids[name] = cur.lastrowid

        accounts = [
            ("銀行TS", "銀行"),
            ("銀行KT", "銀行"),
            ("銀行HN", "銀行"),
            ("證券HN·原有部位", "證券"),
            ("證券HN·分批投入", "證券"),
            ("證券KT", "證券"),
        ]
        account_ids = {}
        for name, category in accounts:
            cur = self.conn.execute(
                "INSERT INTO asset_accounts (name, category) VALUES (?, ?)",
                (name, category),
            )
            account_ids[name] = cur.lastrowid

        holdings = [
            ("緊急預備金", "銀行TS", 600000),
            ("危機加碼緩衝", "銀行KT", 300000),
            ("危機加碼緩衝", "銀行HN", 200000),
            ("核心0050累積", "證券HN·原有部位", 800000),
            # 建倉計畫尚未開始，這裡刻意是 0，不塞假的已完成進度。
            ("核心0050累積", "證券HN·分批投入", 0),
            ("衛星倉位", "證券KT", 500000),
        ]
        for pocket_name, account_name, amount in holdings:
            self.conn.execute(
                "INSERT INTO asset_holdings (pocket_id, account_id, amount)"
                " VALUES (?, ?, ?)",
                (pocket_ids[pocket_name], account_ids[account_name], amount),
            )

        plan_cur = self.conn.execute(
            "INSERT INTO asset_buildup_plans"
            " (pocket_id, account_id, label, total_months, monthly_target_amount)"
            " VALUES (?, ?, ?, ?, ?)",
            (pocket_ids["核心0050累積"], account_ids["證券HN·分批投入"],
             "核心0050累積建倉計畫", 10, 40000),
        )
        plan_id = plan_cur.lastrowid
        for month_number in range(1, 11):
            self.conn.execute(
                "INSERT INTO asset_buildup_entries"
                " (plan_id, month_number, planned_amount, actual_amount, completed_at)"
                " VALUES (?, ?, ?, NULL, NULL)",
                (plan_id, month_number, 40000),
            )

        self.conn.commit()

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

    def get_comments_by_code(self, code, limit=50):
        """依股票代碼精確查留言（2026-08-01新增，個股詳情頁「心得與留言」
        卡片用）：`search_comments()` 是FTS5 MATCH全文搜尋，查詢字串出現
        在body/symbols任何欄位都算命中，也不保證能拿代碼本身當查詢字串
        （FTS5 trigram至少需要3字元，多數台股代碼剛好4碼還好，但無法精確
        限定「只比對symbols欄位」，也無法排除code剛好是另一檔股票代碼子
        字串的誤判，例如code="330"會誤中symbols="2330"）。這裡改用一般
        SELECT掃描symbols欄位、以逗號/全形逗號/空白切開後精確比對code，
        避免子字串誤判。FTS5虛擬表允許一般SELECT（非MATCH），個人使用
        量級（數百筆留言）全表掃描效能無虞，不需要另建索引表。
        依date DESC、created_at DESC排序，上限limit。"""
        if not code:
            raise ValueError("code 為必填")
        rows = self.conn.execute(
            "SELECT body, symbols, source_tag, date, source_ref"
            " FROM comments ORDER BY date DESC, created_at DESC"
        ).fetchall()
        matched = []
        for r in rows:
            parts = [p for p in re.split(r"[,，\s]+", r["symbols"] or "") if p]
            if code in parts:
                matched.append(dict(r))
                if len(matched) >= limit:
                    break
        return {"code": code, "count": len(matched), "results": matched}

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
        """新增一批持股快照（純INSERT，不覆蓋/刪除舊快照，見docstring歷史
        設計）。2026-08-31新增同日「完全相同」重複匯入防呆（PO明確要求）：
        同一個(code, snapshot_date)若已存在**且shares／avg_cost都跟現有列
        完全相同**，判定為同一份資料被不小心重複確認匯入，該筆跳過不寫入，
        歸入回傳的duplicates_skipped——避免get_holdings()把兩批一模一樣的
        資料都當作「最新那天」回傳，造成股數看起來被重複計算（例如同一檔
        出現兩列各自的股數）。

        刻意只比對「完全相同」而非單純「code+snapshot_date存在」：同一天
        合理地可能會有股數/成本真的不同的第二次確認（例如當天盤中先存一次、
        尾盤又更新一次真的變動的持股數），這種情況不是使用者的錯誤重複，
        不該被擋下——見test_report_server.py
        test_dashboard_holdings_preview_then_confirm_full_flow 的既有情境。
        跨「不同天」的快照完全不受本防呆影響，仍然完整保留歷史
        （get_holdings()只看最新一天，不做跨天加總，不是這裡要防的問題）。

        同一批次(rows)內部若本身就貼了兩筆一模一樣的資料，也會被擋下
        第二筆——SQLite同一連線內尚未commit的INSERT對後續SELECT可見
        （read-your-own-writes），不需要額外處理批次內比對。"""
        if not rows or not isinstance(rows, list):
            raise ValueError("rows 必須是非空的持股清單")
        snapshot_date = snapshot_date or _today()
        duplicates_skipped = []
        saved_count = 0
        for r in rows:
            if not r.get("code"):
                raise ValueError("每筆持股都必須有 code：%r" % r)
            existing = self.conn.execute(
                "SELECT shares, avg_cost FROM holdings"
                " WHERE code=? AND snapshot_date=? LIMIT 1",
                (r["code"], snapshot_date),
            ).fetchone()
            if existing is not None and existing["shares"] == r.get("shares") \
                    and existing["avg_cost"] == r.get("avg_cost"):
                duplicates_skipped.append({"code": r["code"], "name": r.get("name")})
                continue
            self.conn.execute(
                "INSERT INTO holdings (code, name, shares, avg_cost,"
                " snapshot_date, source_ref, created_at) VALUES (?,?,?,?,?,?,?)",
                (r["code"], r.get("name"), r.get("shares"), r.get("avg_cost"),
                 snapshot_date, source_ref, _now()),
            )
            saved_count += 1
        self.conn.commit()
        return {"saved": True, "count": saved_count,
                "snapshot_date": snapshot_date,
                "duplicates_skipped": duplicates_skipped}

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
        # 2026-09-02（交易紀錄自動同步持股快照）：同一天同代碼可能出現兩列
        # ——holdings_sync.py 每次交易匯入後會重寫「今天完整快照」，若當天
        # 稍後又手動上傳一次券商持股報告，兩者都落在同一個
        # snapshot_date，靠 id AUTOINCREMENT 嚴格遞增取後寫入者勝出（券商
        # 報告永遠優先於自動推算，見product-spec決策），不需要額外的
        # 「來源優先權」欄位。同時篩掉 shares<=0（賣出歸零/已出清的代碼）
        # ——這代表「是否持有」，不該再出現在最新持股清單。get_holdings
        # (code=X) 這條「查歷史」的分支不受影響，仍完整保留每一列
        # （含shares=0那筆），供需要「出清那一刻」的呼叫端使用。
        rows = self.conn.execute(
            "SELECT h.* FROM holdings h"
            " INNER JOIN (SELECT code, max(id) AS max_id FROM holdings"
            "             WHERE snapshot_date=? GROUP BY code) t"
            " ON h.id = t.max_id"
            " WHERE h.shares > 0"
            " ORDER BY h.code",
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

    def upsert_stock_price(self, code, price, price_date, prev_close=None):
        """prev_close（2026-08-01新增，個股清單/詳情頁「今天漲跌幅」用）：
        前一交易日收盤價，選填——呼叫端查不到（例如資料源只回傳單一交易日）
        時傳 None，沿用「查不到就是 None，不擅自臆測」的既有慣例，頁面端
        看到 None 就顯示「—」不算漲跌幅。INSERT OR REPLACE 只存最新一筆，
        沒有歷史（跟改動前的既有設計一致，見上方 stock_prices 表註解）。"""
        if not code:
            raise ValueError("code 為必填")
        updated_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_prices"
            " (code, price, price_date, prev_close, updated_at) VALUES (?,?,?,?,?)",
            (code, price, price_date, prev_close, updated_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code, "price": price,
                "price_date": price_date, "prev_close": prev_close,
                "updated_at": updated_at}

    def get_stock_prices(self):
        rows = self.conn.execute(
            "SELECT code, price, price_date, prev_close, updated_at FROM stock_prices"
        ).fetchall()
        return {r["code"]: {"price": r["price"], "price_date": r["price_date"],
                            "prev_close": r["prev_close"],
                            "updated_at": r["updated_at"]} for r in rows}

    # ---------- 估值快照快取（2026-08-01新增，個股詳情頁「上次更新於」
    # 用）：背景刷新（trigger_stock_refresh／module_d_scheduler排程）查到的
    # PER/PBR/殖利率/營收年增率，連同資料來源標記與錯誤訊息一起存最新一筆，
    # 供頁面讀快取顯示，不即時查外部API。跟 module_d_results（存「發現」）
    # 是不同性質的資料，不合併進同一張表：這裡是「估值數字快照」，
    # PRIMARY KEY code 只留最新一筆（跟 stock_prices 同款設計，不需要歷史
    # ——「這檔股票現在的估值是多少」不像 module_d 的「發現」需要累積比對，
    # 只需要最新值）。 ----------

    def upsert_stock_valuation(self, code, per=None, pbr=None, dividend_yield=None,
                               revenue_yoy=None, revenue_period=None,
                               valuation_data_source=None, revenue_data_source=None,
                               valuation_error=None, revenue_error=None, checked_at=None):
        if not code:
            raise ValueError("code 為必填")
        checked_at = checked_at or _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO stock_valuation_snapshots"
            " (code, per, pbr, dividend_yield, revenue_yoy, revenue_period,"
            " valuation_data_source, revenue_data_source, valuation_error,"
            " revenue_error, checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (code, per, pbr, dividend_yield, revenue_yoy, revenue_period,
             valuation_data_source, revenue_data_source, valuation_error,
             revenue_error, checked_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code, "checked_at": checked_at}

    def get_stock_valuation(self, code):
        row = self.conn.execute(
            "SELECT * FROM stock_valuation_snapshots WHERE code=?", (code,)
        ).fetchone()
        return dict(row) if row else None

    # ---------- 個股股價歷史快取（2026-08-09新增，庫存買賣圖表用）：
    # review_engine.refresh_price_and_valuation() 背景刷新時本來就已經
    # 打過官方/FinMind查到一整段區間的股價（只是改動前只挑最後兩筆存進
    # stock_prices 算漲跌幅、其餘丟棄）——這裡讓它「順便」把整段也存下來，
    # 不是另外多打一次API。INSERT OR REPLACE以(code,date)為key，同一天
    # 重複刷新會覆蓋成最新值；不同天的舊資料不會被清掉，隨著PO時間推移
    # 反覆按「更新」，快取會自然累積成比單次查詢窗口更長的歷史（每次
    # fetch的180天窗口會隨時間推移往前滑動，重疊的部分覆蓋更新、新的
    # 部分補進來、舊窗口以外先前存過的部分繼續保留），不用另外設計
    # 「合併歷史」的邏輯。頁面讀取時仍只顯示最近N天（get_cached_price_
    # history的limit_days），避免圖表因為累積太多年資料而畫不出有意義
    # 的走勢。 ----------

    def save_price_history_points(self, code, prices):
        """prices：[{"date": "YYYY-MM-DD", "close": float}, ...]，通常是
        screener._fetch_prices_with_fallback() 已經查到、正要被呼叫端
        丟棄的完整序列。缺 date 或 close 的點跳過不存（比照其餘cache
        寫入函式「查不到就是None，不擅自臆測」的既有慣例，但這裡是
        「這筆資料本身不完整就不存」，不是存None）。"""
        if not code or not prices:
            return {"saved": True, "code": code, "count": 0}
        rows = [(code, p["date"], p.get("close")) for p in prices
                if p.get("date") and p.get("close") is not None]
        if rows:
            self.conn.executemany(
                "INSERT OR REPLACE INTO stock_price_history (code, date, close)"
                " VALUES (?,?,?)", rows)
            self.conn.commit()
        return {"saved": True, "code": code, "count": len(rows)}

    def get_cached_price_history(self, code, limit_days=180):
        """回傳依日期升冪排序的 [{"date","close"}, ...]，只取最近
        limit_days 天（見上方表註解——快取本身可能累積比這更長的歷史，
        這裡負責裁到畫圖用得到的範圍，不是資料庫實際保留的範圍）。
        還沒刷新過的代碼回傳空list，呼叫端自行決定顯示什麼提示文字，
        不在這裡臆測。"""
        cutoff = (datetime.date.today() - datetime.timedelta(days=limit_days)).isoformat()
        rows = self.conn.execute(
            "SELECT date, close FROM stock_price_history"
            " WHERE code=? AND date>=? ORDER BY date", (code, cutoff),
        ).fetchall()
        return [{"date": r["date"], "close": r["close"]} for r in rows]

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

    # ---------- 季度財報指標快取（2026-08-19新增）：財報是**季頻**資料，
    # 但模組D排程每天對全部觀察標的跑一次——若每次都重打 FinMind，等於
    # 每天多消耗「標的數×2」次額度去換一批一季才變一次的數字。CLAUDE.md
    # 2026-07-28 教訓明確記載匿名額度是全域共用池、被打光會連累當晚排程，
    # 所以這裡用 TTL 快取（預設30天）：一季內最多重抓一次，仍能在一個月
    # 內接到新一季財報。存整包 JSON 而非拆欄位，因為呼叫端要的是整段季度
    # 序列（算同季去年比較與TTM），拆表反而要 join 回來。 ----------

    def save_revenue_yoy_cache(self, code, payload):
        """月營收年增率序列快取（2026-08-19新增）。

        動機是**去重**不是加速：每日排程對同一檔會走兩條路徑——
        `run_module_d_review`→`general_review`（成長趨緩要多月序列）與
        `refresh_price_and_valuation`→`auto_score_review`（月營收加速也要
        同一份序列）。沒有快取的話同一份資料一天抓兩次，31 檔就是 62 次
        FinMind 呼叫（CLAUDE.md 2026-07-28 教訓：匿名額度是全域共用池，
        打光會連累當晚排程）。TTL 預設 20 小時：足以涵蓋同一次排程的兩條
        路徑，又保證隔天一定重抓（月營收約每月10日更新，日更綽綽有餘）。"""
        if not code:
            raise ValueError("code 為必填")
        fetched_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO revenue_yoy_cache (code, payload, fetched_at)"
            " VALUES (?,?,?)",
            (code, json.dumps(payload, ensure_ascii=False), fetched_at))
        self.conn.commit()
        return {"saved": True, "code": code, "fetched_at": fetched_at}

    def get_revenue_yoy_cache(self, code, max_age_hours=20):
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM revenue_yoy_cache WHERE code = ?",
            (code,)).fetchone()
        if not row:
            return None
        try:
            fetched = datetime.datetime.fromisoformat(row["fetched_at"])
        except (ValueError, TypeError):
            return None
        if (datetime.datetime.now() - fetched).total_seconds() > max_age_hours * 3600:
            return None
        try:
            return json.loads(row["payload"])
        except ValueError:
            return None

    def save_auto_score(self, code, payload, checked_at=None):
        """存 Score 自動化四項的**計算結果**（不是原始財報）。

        為什麼存結果而不是讓頁面現算：個股詳情頁的既有原則是「只讀快取、
        不即時查外部API」，但 Score 的月營收加速項需要多月年增率序列（財報
        快取涵蓋不到）。由背景刷新路徑算好存起來，頁面純讀取，渲染路徑就
        完全不碰網路——這也是 2026-08-19 實測發現的問題：先前讓頁面現算，
        單元測試從 6.5 秒變成 18.9 秒，就是渲染時打了 FinMind。"""
        if not code:
            raise ValueError("code 為必填")
        checked_at = checked_at or _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO auto_score_cache (code, payload, checked_at)"
            " VALUES (?,?,?)",
            (code, json.dumps(payload, ensure_ascii=False), checked_at))
        self.conn.commit()
        return {"saved": True, "code": code, "checked_at": checked_at}

    def get_auto_score(self, code):
        """沒算過回 None——頁面據此顯示「按更新後顯示」，不要自己編分數。"""
        row = self.conn.execute(
            "SELECT payload, checked_at FROM auto_score_cache WHERE code = ?",
            (code,)).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except ValueError:
            return None
        payload["checked_at"] = row["checked_at"]
        return payload

    def save_financial_metrics_cache(self, code, payload):
        if not code:
            raise ValueError("code 為必填")
        fetched_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO financial_metrics_cache (code, payload, fetched_at)"
            " VALUES (?,?,?)",
            (code, json.dumps(payload, ensure_ascii=False), fetched_at))
        self.conn.commit()
        return {"saved": True, "code": code, "fetched_at": fetched_at}

    def get_financial_metrics_cache(self, code, max_age_days=30):
        """回傳 (payload, fetched_at)；沒有或已過期回傳 (None, fetched_at
        或 None)——過期仍回傳 fetched_at，讓呼叫端可以在 API 失敗時決定
        要不要退回用舊資料（有總比沒有好，但要標明是舊的）。"""
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM financial_metrics_cache WHERE code = ?",
            (code,)).fetchone()
        if not row:
            return None, None
        try:
            fetched = datetime.datetime.fromisoformat(row["fetched_at"])
        except (ValueError, TypeError):
            return None, row["fetched_at"]
        age = (datetime.datetime.now() - fetched).days
        if age > max_age_days:
            return None, row["fetched_at"]
        try:
            return json.loads(row["payload"]), row["fetched_at"]
        except ValueError:
            return None, row["fetched_at"]

    # ---------- 加碼計畫總額度（2026-08-19新增）：補上 review_engine
    # `position_control_suggestion()` 的 `suggested_add_pct` 一直缺的分母
    # ——那個比例的定義是「這次加碼佔**此股加碼計畫總額度**的比例」，但
    # 「加碼計畫總額度」先前在整個系統裡沒有任何地方存得下來（見
    # roadmap.md「已知限制／待辦」2026-08-16 條目），導致「加碼進度
    # （已投入/計畫總額/完成幾成）」算不出來，只能人工心算。
    #
    # 單位是**金額**（PO 2026-08-19 決定）：跟「預計買多少、已經買多少」
    # 的語感一致，且已投入金額本來就能從 trade_ledger 加總算出，同單位
    # 才能直接算進度百分比（換成股數或投組佔比都得再換算一次，量綱不同）。
    # PRIMARY KEY code 只留最新一筆、可隨時覆寫——PO 明確要求「投資預算
    # 會變動，預計買多少也可以調整」，不需要保留歷次計畫的歷史。 ----------

    def save_position_plan(self, code, plan_amount, note=None):
        if not code:
            raise ValueError("code 為必填")
        try:
            plan_amount = float(plan_amount)
        except (TypeError, ValueError):
            raise ValueError("plan_amount 必須是數字：%r" % (plan_amount,))
        if plan_amount <= 0:
            raise ValueError("plan_amount 必須大於 0：%r" % (plan_amount,))
        updated_at = _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO position_plans"
            " (code, plan_amount, note, updated_at) VALUES (?,?,?,?)",
            (code, plan_amount, note, updated_at),
        )
        self.conn.commit()
        return {"saved": True, "code": code, "plan_amount": plan_amount,
                "note": note, "updated_at": updated_at}

    def get_position_plan(self, code):
        """回傳單一標的的加碼計畫；沒設定過回傳 None（呼叫端據此顯示
        「尚未設定」，不要自己編一個預設額度）。"""
        row = self.conn.execute(
            "SELECT code, plan_amount, note, updated_at FROM position_plans"
            " WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None

    def delete_position_plan(self, code):
        cur = self.conn.execute(
            "DELETE FROM position_plans WHERE code = ?", (code,))
        self.conn.commit()
        return {"deleted": cur.rowcount > 0, "code": code}

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
    # 不必額外用 action 欄位過濾。order_ref（委託書號，2026-07-31 新增，
    # 經 _MIGRATIONS 補欄位）：券商發的理論唯一編號，供
    # resolve_and_save_trade_ledger() 防止同一份對帳單／交易明細表被貼入
    # 兩次而重複寫入；沒有 order_ref 可判斷的來源（None）不受影響。 ----------

    def save_trade_ledger_entry(self, code, name, action, shares, price, date,
                                add_sequence=None, source_ref=None, order_ref=None):
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
            " price, date, source_ref, order_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (code, name, action, add_sequence, shares, price, date, source_ref,
             order_ref, created_at),
        )
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "code": code, "action": action,
                "add_sequence": add_sequence, "date": date, "order_ref": order_ref}

    def get_trade_ledger(self, code):
        """回傳該標的完整加碼流水（依 date、id 排序，舊到新），讓呼叫方能
        數出目前買入筆數（add_sequence 非 NULL 的列）來推算下一次加碼序號。"""
        if not code:
            raise ValueError("code 為必填")
        rows = self.conn.execute(
            "SELECT * FROM trade_ledger WHERE code=? ORDER BY date, id", (code,),
        ).fetchall()
        return {"code": code, "count": len(rows), "entries": [dict(r) for r in rows]}

    # ---------- 停損停利門檻（002-entry-exit-signals FR-001~FR-003）----------
    # 刻意採 append-only + max(id) 取最新，跟 stances 同模式，而不是
    # position_plans 的 INSERT OR REPLACE——門檻背後有討論脈絡，
    # 要能回答「當初為什麼設在這裡」，覆寫掉就查不到了。

    def save_exit_threshold(self, code, stop_loss=None, take_profit=None,
                            reason=None, source_ref=None):
        """新增一筆門檻設定（append-only，不覆寫舊值）。

        stop_loss 與 take_profit 至少要給一個；給定的值必須 > 0；
        兩者都給時 stop_loss 必須小於 take_profit（否則是明顯的設定錯誤，
        直接擋下而不是存進去讓它每天誤觸發）。
        """
        if not code:
            raise ValueError("code 為必填")
        if stop_loss is None and take_profit is None:
            raise ValueError("stop_loss 與 take_profit 至少要給一個")
        parsed = {}
        for name, value in (("stop_loss", stop_loss), ("take_profit", take_profit)):
            if value is None:
                parsed[name] = None
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError("%s 必須是數字" % name)
            if number <= 0:
                raise ValueError("%s 必須大於 0" % name)
            parsed[name] = number
        if (parsed["stop_loss"] is not None and parsed["take_profit"] is not None
                and parsed["stop_loss"] >= parsed["take_profit"]):
            raise ValueError("stop_loss 必須小於 take_profit")

        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO exit_thresholds"
            " (code, stop_loss, take_profit, reason, source_ref, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (code, parsed["stop_loss"], parsed["take_profit"], reason,
             source_ref or "對話設定", created_at))
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "code": code,
                "stop_loss": parsed["stop_loss"], "take_profit": parsed["take_profit"],
                "reason": reason, "created_at": created_at}

    def get_exit_threshold(self, code):
        """該標的最新一筆門檻；**從未設定回 None**。

        呼叫端據此顯示「尚未設定」，不要自己編一個預設門檻——沒討論過的
        標的看起來像已經有策略，比沒有更危險（FR-003）。
        """
        if not code:
            raise ValueError("code 為必填")
        row = self.conn.execute(
            "SELECT * FROM exit_thresholds WHERE code=? ORDER BY id DESC LIMIT 1",
            (code,)).fetchone()
        return dict(row) if row else None

    def get_all_exit_thresholds(self):
        """每檔最新一筆，供批次判斷。"""
        rows = self.conn.execute(
            "SELECT t.* FROM exit_thresholds t"
            " INNER JOIN (SELECT code, max(id) AS mid FROM exit_thresholds"
            "             GROUP BY code) latest ON t.id = latest.mid"
        ).fetchall()
        return {r["code"]: dict(r) for r in rows}

    def get_exit_threshold_history(self, code):
        """該標的完整設定歷史，舊到新——這是 append-only 的意義所在。"""
        if not code:
            raise ValueError("code 為必填")
        rows = self.conn.execute(
            "SELECT * FROM exit_thresholds WHERE code=? ORDER BY id", (code,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_trade_entries(self):
        """回傳全部標的的交易流水（依 code、date、id 排序）。

        給 FIFO 損益的全量計算用（FR-011）：既有 get_trade_ledger(code)
        必須逐檔查，60 檔就是 60 次查詢；這裡一次查回由呼叫端在記憶體
        分組，資料量小（實測 537 筆）成本可忽略。
        刻意另開新方法而非改 get_trade_ledger 的簽名，避免影響既有呼叫端。
        """
        rows = self.conn.execute(
            "SELECT * FROM trade_ledger ORDER BY code, date, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def trade_ledger_order_ref_exists(self, order_ref):
        """委託書號防重複查詢：trade_ledger 裡是否已存在相同 order_ref 的
        既有列（非 NULL 比對，SQLite `=` 對 NULL 一律不成立，不需要額外
        排除 NULL 條件）。order_ref 為空值（None／空字串）時，呼叫端本來就
        不該呼叫（見 resolve_and_save_trade_ledger()：沒有 order_ref 的
        交易不做防重複檢查），這裡仍防禦性回傳 False，避免誤擋合法交易。"""
        if not order_ref:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM trade_ledger WHERE order_ref=? LIMIT 1", (order_ref,)
        ).fetchone()
        return row is not None

    # ---------- 模組D檢視結果表（FR-051~055/057）：模組E排程整合跑完
    # 模組D後，結果持久化在這裡，供模組F（報告呈現，下一輪）直接讀取，
    # 不即時運算。一檔標的每次檢視會有多筆（通用層2筆＋策略層N筆＋
    # 老芋頭層0或1筆），皆屬正常設計，不是重複資料。 ----------

    def save_module_d_result(self, code, trigger_type, finding, strategy_id=None,
                             suggested_action=None, conflict_flag=False,
                             concern_flag=False, checked_at=None,
                             trigger_label=None):
        """concern_flag（2026-08-01新增，見 _MIGRATIONS 註解）：這一項發現
        是否需要PO留意（對應 review_engine.run_module_d_review() 內部
        items/findings 清單的同名欄位）——跟 conflict_flag（自動回寫立場
        跟既有記錄是否衝突，批次層級旗標）是兩個獨立概念，不要混淆。

        trigger_label（2026-08-19新增）：細分標籤（「通用層／成長趨緩」等），
        選填——`trigger_type` 只有三個值，同屬「通用層」的兩項檢查靠它才
        分得開。不給就是 None，讀取端退回顯示 trigger_type。"""
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
            " suggested_action, conflict_flag, concern_flag, checked_at, trigger_label)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (code, strategy_id, trigger_type, finding, suggested_action,
             1 if conflict_flag else 0, 1 if concern_flag else 0, checked_at,
             trigger_label),
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

    # ---------- 資產分頁：口袋／帳戶／餘額／建倉計畫（Q-046 第5節 Step 4）----------
    # 「刪除」一律採封存（archived=1），不做硬刪——之前規劃已定案，見
    # docs/spec-intake/alphavibe/roadmap.md Q-046。

    def list_asset_pockets(self, include_archived=False):
        """列出口袋，附 `current_amount`（JOIN asset_holdings 加總該口袋
        底下所有帳戶的餘額，方便前端直接拿來算進度條，不用自己再查一次
        /api/assets/holdings 湊資料）。"""
        query = (
            "SELECT p.id, p.name, p.target_amount, p.note, p.sort_order,"
            " p.archived, p.created_at, p.updated_at,"
            " COALESCE(SUM(h.amount), 0) AS current_amount"
            " FROM asset_pockets p"
            " LEFT JOIN asset_holdings h ON h.pocket_id = p.id"
        )
        if not include_archived:
            query += " WHERE p.archived = 0"
        query += " GROUP BY p.id ORDER BY p.sort_order, p.id"
        rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def save_asset_pocket(self, id=None, name=None, target_amount=None,
                          note=None, sort_order=0):
        """新增或更新口袋：`id` 為 None 時新增，帶 `id` 時更新該筆（比照
        `save_position_plan()` INSERT OR REPLACE 的精神，但這裡表的主鍵是
        AUTOINCREMENT，不是自然鍵，所以用「查得到就 UPDATE、查不到就
        INSERT」而非 INSERT OR REPLACE，避免帶 id 更新時意外重新指派
        rowid）。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("name 為必填")
        now = _now()
        if id is None:
            cur = self.conn.execute(
                "INSERT INTO asset_pockets"
                " (name, target_amount, note, sort_order, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, target_amount, note, sort_order or 0, now),
            )
            pocket_id = cur.lastrowid
        else:
            existing = self.conn.execute(
                "SELECT id FROM asset_pockets WHERE id=?", (id,)).fetchone()
            if not existing:
                raise ValueError("找不到口袋 id=%s" % id)
            self.conn.execute(
                "UPDATE asset_pockets SET name=?, target_amount=?, note=?,"
                " sort_order=?, updated_at=? WHERE id=?",
                (name, target_amount, note, sort_order or 0, now, id),
            )
            pocket_id = id
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM asset_pockets WHERE id=?", (pocket_id,)).fetchone()
        return dict(row)

    def archive_asset_pocket(self, id):
        now = _now()
        cur = self.conn.execute(
            "UPDATE asset_pockets SET archived=1, updated_at=? WHERE id=?",
            (now, id),
        )
        if cur.rowcount == 0:
            raise ValueError("找不到口袋 id=%s" % id)
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM asset_pockets WHERE id=?", (id,)).fetchone()
        return dict(row)

    def list_asset_accounts(self, include_archived=False):
        query = "SELECT * FROM asset_accounts"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY id"
        rows = self.conn.execute(query).fetchall()
        return [dict(r) for r in rows]

    def save_asset_account(self, id=None, name=None, category=None, note=None):
        """新增或更新帳戶，邏輯對稱 `save_asset_pocket()`（帳戶沒有
        `sort_order`——目前規格沒要求帳戶可排序，見 API 規格）。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("name 為必填")
        now = _now()
        if id is None:
            cur = self.conn.execute(
                "INSERT INTO asset_accounts (name, category, note, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (name, category, note, now),
            )
            account_id = cur.lastrowid
        else:
            existing = self.conn.execute(
                "SELECT id FROM asset_accounts WHERE id=?", (id,)).fetchone()
            if not existing:
                raise ValueError("找不到帳戶 id=%s" % id)
            self.conn.execute(
                "UPDATE asset_accounts SET name=?, category=?, note=?,"
                " updated_at=? WHERE id=?",
                (name, category, note, now, id),
            )
            account_id = id
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM asset_accounts WHERE id=?", (account_id,)).fetchone()
        return dict(row)

    def archive_asset_account(self, id):
        now = _now()
        cur = self.conn.execute(
            "UPDATE asset_accounts SET archived=1, updated_at=? WHERE id=?",
            (now, id),
        )
        if cur.rowcount == 0:
            raise ValueError("找不到帳戶 id=%s" % id)
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM asset_accounts WHERE id=?", (id,)).fetchone()
        return dict(row)

    def list_asset_holdings(self):
        """列出所有餘額記錄，JOIN 出口袋／帳戶名稱方便前端直接顯示，不用
        另外查 pockets/accounts 兩張表湊名字。"""
        rows = self.conn.execute(
            "SELECT h.id, h.pocket_id, p.name AS pocket_name, h.account_id,"
            " a.name AS account_name, h.amount, h.updated_at, h.note"
            " FROM asset_holdings h"
            " JOIN asset_pockets p ON p.id = h.pocket_id"
            " JOIN asset_accounts a ON a.id = h.account_id"
            " ORDER BY p.sort_order, p.id, a.id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_asset_holding(self, pocket_id, account_id, amount, note=None):
        """新增/更新某口袋×帳戶的餘額——這是**覆蓋**（設成 `amount` 這個
        絕對值），不是累加。累加是 `complete_asset_buildup_month()` 內部
        `_apply_asset_holding_delta()` 的專屬語意，兩者刻意分開避免呼叫端
        搞混（呼叫這支方法永遠是「我現在要把餘額設成 X」）。"""
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("amount 必須是數字：%r" % (amount,))
        if not self.conn.execute(
            "SELECT id FROM asset_pockets WHERE id=?", (pocket_id,)
        ).fetchone():
            raise ValueError("找不到口袋 id=%s" % pocket_id)
        if not self.conn.execute(
            "SELECT id FROM asset_accounts WHERE id=?", (account_id,)
        ).fetchone():
            raise ValueError("找不到帳戶 id=%s" % account_id)
        now = _now()
        self.conn.execute(
            "INSERT INTO asset_holdings (pocket_id, account_id, amount, note, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(pocket_id, account_id) DO UPDATE SET"
            " amount=excluded.amount, note=excluded.note, updated_at=excluded.updated_at",
            (pocket_id, account_id, amount, note, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT h.id, h.pocket_id, p.name AS pocket_name, h.account_id,"
            " a.name AS account_name, h.amount, h.updated_at, h.note"
            " FROM asset_holdings h"
            " JOIN asset_pockets p ON p.id = h.pocket_id"
            " JOIN asset_accounts a ON a.id = h.account_id"
            " WHERE h.pocket_id=? AND h.account_id=?",
            (pocket_id, account_id),
        ).fetchone()
        return dict(row)

    def _apply_asset_holding_delta(self, pocket_id, account_id, delta):
        """內部用：把 `delta`（可正可負）累加進某口袋×帳戶的餘額，記錄
        不存在時視同從 0 開始（用 ON CONFLICT DO UPDATE 的 UPSERT，一次
        處理「還沒有這筆記錄」與「已有記錄要累加」兩種情況）。呼叫端
        （`complete_asset_buildup_month()`／`undo_asset_buildup_month()`）
        負責 commit，這裡不自行 commit，讓「更新 entry」與「更新
        holdings」落在同一個 transaction。"""
        now = _now()
        self.conn.execute(
            "INSERT INTO asset_holdings (pocket_id, account_id, amount, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(pocket_id, account_id) DO UPDATE SET"
            " amount = amount + excluded.amount, updated_at = excluded.updated_at",
            (pocket_id, account_id, delta, now),
        )

    def get_asset_buildup_plan_with_entries(self, plan_id):
        """回傳建倉計畫本身＋10筆（或 total_months 筆）進度 entries，
        附口袋／帳戶名稱方便前端顯示標題不用另外查表。查無此計畫回傳
        None（呼叫端據此回 404，不要自己編一個空殼）。"""
        plan_row = self.conn.execute(
            "SELECT pl.*, p.name AS pocket_name, a.name AS account_name"
            " FROM asset_buildup_plans pl"
            " JOIN asset_pockets p ON p.id = pl.pocket_id"
            " JOIN asset_accounts a ON a.id = pl.account_id"
            " WHERE pl.id=?",
            (plan_id,),
        ).fetchone()
        if not plan_row:
            return None
        entries = self.conn.execute(
            "SELECT * FROM asset_buildup_entries WHERE plan_id=? ORDER BY month_number",
            (plan_id,),
        ).fetchall()
        plan = dict(plan_row)
        plan["entries"] = [dict(r) for r in entries]
        return plan

    def complete_asset_buildup_month(self, plan_id, month_number, actual_amount):
        """把某個月的建倉進度標記完成，並把金額累加進對應的
        asset_holdings 餘額——「更新 entry」與「累加 holdings」在同一個
        transaction 內完成（呼叫端看到的結果永遠是兩者一致，不會出現
        entry 顯示完成但 holdings 沒加到、或反過來的半套狀態）。

        取消打勾的復原設計（見 undo_asset_buildup_month）：**不新增額外
        欄位**記錄「上次套用金額」——`entries.actual_amount` 在完成狀態下
        本身就等於「已套用進 asset_holdings 的金額」，取消時直接讀回這個
        值扣回去即可，不需要重算整個口袋餘額（那種做法一來粗暴、二來會
        把使用者透過 `upsert_asset_holding()` 手動調整過的部分一併蓋掉）。

        額外處理「對已完成的月份重新打勾、金額跟上次不同」（更正輸入
        錯誤）的情況：不是整批重算，是只把「新舊金額的差額」套用進
        asset_holdings，語意等同「先扣回舊值、再加上新值」但只需一次
        UPDATE。"""
        try:
            actual_amount = float(actual_amount)
        except (TypeError, ValueError):
            raise ValueError("actual_amount 必須是數字：%r" % (actual_amount,))
        plan = self.conn.execute(
            "SELECT * FROM asset_buildup_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not plan:
            raise ValueError("找不到建倉計畫 id=%s" % plan_id)
        entry = self.conn.execute(
            "SELECT * FROM asset_buildup_entries WHERE plan_id=? AND month_number=?",
            (plan_id, month_number),
        ).fetchone()
        if not entry:
            raise ValueError(
                "找不到第 %s 個月的進度記錄（plan_id=%s）" % (month_number, plan_id))

        previous_applied = entry["actual_amount"] or 0.0
        delta = actual_amount - previous_applied
        now = _now()
        self.conn.execute(
            "UPDATE asset_buildup_entries SET actual_amount=?, completed_at=?"
            " WHERE id=?",
            (actual_amount, now, entry["id"]),
        )
        self._apply_asset_holding_delta(plan["pocket_id"], plan["account_id"], delta)
        self.conn.commit()
        updated_entry = self.conn.execute(
            "SELECT * FROM asset_buildup_entries WHERE id=?", (entry["id"],)
        ).fetchone()
        holding = self.conn.execute(
            "SELECT * FROM asset_holdings WHERE pocket_id=? AND account_id=?",
            (plan["pocket_id"], plan["account_id"]),
        ).fetchone()
        return {"entry": dict(updated_entry),
                "holding": dict(holding) if holding else None}

    def undo_asset_buildup_month(self, plan_id, month_number):
        """取消打勾：把 entry 設回未完成（`actual_amount`／`completed_at`
        清成 NULL），並把當初完成時套用進 asset_holdings 的金額精確扣回去
        （讀 entry 被清空前的 `actual_amount`，見
        `complete_asset_buildup_month()` docstring 說明的復原設計）。

        該月本來就未完成（`actual_amount` 已是 NULL）時視為 no-op，不當
        錯誤：回傳 `undone: False` 讓呼叫端知道沒有東西可取消，而不是
        丟一個「你在取消一個沒完成的東西」的 400——這種情況比較像是
        呼叫端狀態過期（例如使用者連點兩次取消鍵），沒有必要當成錯誤。
        """
        plan = self.conn.execute(
            "SELECT * FROM asset_buildup_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not plan:
            raise ValueError("找不到建倉計畫 id=%s" % plan_id)
        entry = self.conn.execute(
            "SELECT * FROM asset_buildup_entries WHERE plan_id=? AND month_number=?",
            (plan_id, month_number),
        ).fetchone()
        if not entry:
            raise ValueError(
                "找不到第 %s 個月的進度記錄（plan_id=%s）" % (month_number, plan_id))

        if entry["actual_amount"] is None:
            return {"entry": dict(entry), "holding": None, "undone": False}

        previous_applied = entry["actual_amount"]
        self.conn.execute(
            "UPDATE asset_buildup_entries SET actual_amount=NULL, completed_at=NULL"
            " WHERE id=?",
            (entry["id"],),
        )
        self._apply_asset_holding_delta(
            plan["pocket_id"], plan["account_id"], -previous_applied)
        self.conn.commit()
        updated_entry = self.conn.execute(
            "SELECT * FROM asset_buildup_entries WHERE id=?", (entry["id"],)
        ).fetchone()
        holding = self.conn.execute(
            "SELECT * FROM asset_holdings WHERE pocket_id=? AND account_id=?",
            (plan["pocket_id"], plan["account_id"]),
        ).fetchone()
        return {"entry": dict(updated_entry),
                "holding": dict(holding) if holding else None, "undone": True}
