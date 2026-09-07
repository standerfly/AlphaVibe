"""美股獨立投資系統儲存層：`USStockStore`。

**完全獨立於 `poc/kb-mcp/kb_store.py`／`KBStore`**——不 import、不繼承、
不共用任何程式碼或資料表，獨立資料庫檔案 `poc/data/us_stocks.db`。決策
依據見 `specs/003-us-stocks/research.md` §1、`data-model.md`（FR-015/016
「完全獨立」要求）。

4 張表：`us_trades`（交易紀錄）／`us_stances`（投資立場／研究筆記）／
`us_watch_conditions`（關注條件）／`us_price_snapshots`（報價紀錄）。
四張表都以 `ticker` 作為邏輯關聯鍵，不建立外鍵約束（見 data-model.md
「實體關係總覽」）。

**不得在 `__init__` 掛任何有副作用的種子寫入邏輯**——2026-08-22 資產表
事故教訓（見 AlphaVibe/CLAUDE.md 教訓紀錄）：`KBStore.__init__` 曾經
無條件呼叫種子寫入方法，導致任何建構 `KBStore` 的呼叫端（包含每天
02:00 排程腳本）都會觸發寫入，正式資料庫因此被污染兩次。這個類別從
設計上就不建立這種耦合——`__init__` 只做 schema 建立，不寫入任何列。

限制：這台開發機只有 Python 3.9.6，不使用 3.10+ 語法（match-case、
`X | Y` 型別聯集寫法）；僅用標準庫（`sqlite3`），比照 `kb_store.py`
既有慣例。
"""
import datetime
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS us_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    action TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_us_trades_ticker ON us_trades(ticker, trade_date);

CREATE TABLE IF NOT EXISTS us_stances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    direction TEXT NOT NULL,
    bear_price REAL,
    bear_price_high REAL,
    base_price_low REAL,
    base_price_high REAL,
    bull_price REAL,
    summary TEXT NOT NULL,
    full_note TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_us_stances_ticker ON us_stances(ticker, id);

CREATE TABLE IF NOT EXISTS us_watch_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    comparator TEXT NOT NULL,
    threshold REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'insufficient_data',
    last_evaluated_at TEXT,
    last_notified_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_us_watch_conditions_ticker ON us_watch_conditions(ticker);

CREATE TABLE IF NOT EXISTS us_price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    close_price REAL,
    gaap_gross_margin REAL,
    revenue_yoy REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(ticker, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_us_price_snapshots_ticker ON us_price_snapshots(ticker, snapshot_date);
"""

VALID_TRADE_ACTIONS = ("buy", "sell")
VALID_STANCE_DIRECTIONS = ("bullish", "bearish", "neutral")
VALID_STANCE_STATUSES = ("active", "closed")
VALID_WATCH_COMPARATORS = ("lt", "gt")
VALID_WATCH_STATUSES = ("ok", "alert", "insufficient_data")

_TRACKED_TABLES = (
    "us_trades", "us_stances", "us_watch_conditions", "us_price_snapshots",
)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _business_days_between(date_str_a, date_str_b):
    """`date_str_a`／`date_str_b` 皆為 'YYYY-MM-DD'，回傳兩者之間（不含
    頭尾本身）的平日（週一~週五）日期字串清單，用於
    `price_history_with_gaps()` 偵測相鄰快照之間的資料缺口。"""
    start = datetime.date.fromisoformat(date_str_a)
    end = datetime.date.fromisoformat(date_str_b)
    days = []
    cur = start + datetime.timedelta(days=1)
    while cur < end:
        if cur.weekday() < 5:  # 0=週一 ... 4=週五
            days.append(cur.isoformat())
        cur += datetime.timedelta(days=1)
    return days


class USStockStore:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "us_stocks.db")
        # check_same_thread=False：比照 kb_store.py 2026-08-22 教訓——
        # FastAPI 的 sync generator dependency（app/us_stock_deps.py）由
        # anyio thread pool 執行，同一個 request 的「建立」與「關閉」不
        # 保證在同一條 worker thread，這裡預先關掉這個誤判，實際上並沒有
        # 真正跨執行緒併發存取同一個連線（見 kb_store.py 同一段註解）。
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # 刻意不呼叫任何種子資料寫入方法——這裡從設計上就不允許 __init__
        # 有這類副作用（見本檔案開頭 docstring 的 2026-08-22 教訓）。

    def close(self):
        self.conn.close()

    # ---------- us_trades ----------

    def save_trade(self, ticker, trade_date, action, shares, price, amount=None):
        """新增一筆交易紀錄。`amount` 未提供時＝shares×price；提供時採用
        使用者核對後的值（data-model.md 允許手動調整，見該表欄位說明）。
        不做同筆交易的自動去重（spec.md Edge Cases 已定案）。"""
        if action not in VALID_TRADE_ACTIONS:
            raise ValueError(
                "action 必須是 %s，收到：%s" % (VALID_TRADE_ACTIONS, action))
        if shares is None or shares <= 0:
            raise ValueError("shares 必須 > 0")
        if price is None or price <= 0:
            raise ValueError("price 必須 > 0")
        if amount is None:
            amount = shares * price
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO us_trades"
            " (ticker, trade_date, action, shares, price, amount, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, trade_date, action, shares, price, amount, created_at),
        )
        self.conn.commit()
        return self.get_trade(cur.lastrowid)

    def get_trade(self, trade_id):
        row = self.conn.execute(
            "SELECT * FROM us_trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None

    def list_trades(self, ticker=None):
        if ticker:
            rows = self.conn.execute(
                "SELECT * FROM us_trades WHERE ticker=? ORDER BY trade_date, id",
                (ticker,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM us_trades ORDER BY trade_date, id").fetchall()
        return [dict(r) for r in rows]

    def update_trade(self, trade_id, ticker, trade_date, action, shares,
                      price, amount=None):
        """更新一筆既有交易紀錄（Phase 3 US1 T016/T017：匯入核對確認畫面
        用——Claude 已在對話中呼叫 `save_trade`／`parse_and_save_us_trade`
        寫入初版紀錄，使用者在網頁核對畫面修正欄位後呼叫這裡）。驗證規則
        與 `save_trade` 相同。`trade_id` 不存在回傳 `None`，呼叫端據此
        判斷要回 404（比照 data-model.md 對 `us_trades` 的驗證規則，
        不另立一套）。"""
        if self.get_trade(trade_id) is None:
            return None
        if action not in VALID_TRADE_ACTIONS:
            raise ValueError(
                "action 必須是 %s，收到：%s" % (VALID_TRADE_ACTIONS, action))
        if shares is None or shares <= 0:
            raise ValueError("shares 必須 > 0")
        if price is None or price <= 0:
            raise ValueError("price 必須 > 0")
        if amount is None:
            amount = shares * price
        self.conn.execute(
            "UPDATE us_trades SET ticker=?, trade_date=?, action=?,"
            " shares=?, price=?, amount=? WHERE id=?",
            (ticker, trade_date, action, shares, price, amount, trade_id),
        )
        self.conn.commit()
        return self.get_trade(trade_id)

    def list_recent_trades(self, limit=20):
        """依 id（＝寫入順序）由新到舊回傳最近 N 筆交易——供匯入核對
        確認畫面（T017）顯示「Claude 剛在對話中解析寫入的紀錄」，跟
        `list_trades()`（依 `trade_date` 排序，給圖表/流水帳用）用途不
        同，刻意分開兩個方法，不共用同一份排序邏輯。"""
        rows = self.conn.execute(
            "SELECT * FROM us_trades ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 持股彙總（contracts 工具二 get_us_holdings，FR-013） ----------

    def compute_holdings(self, ticker=None):
        """依 `us_trades` 彙總計算目前持股。MVP 只算簡單加權平均成本，
        不做 FIFO 精算（見 contracts/mcp-tools.md 工具二說明，精確 FIFO
        損益列為未來擴充）。

        `ticker` 省略時回傳全部「曾有交易」的股票各自一筆彙總——注意這
        不是 `get_tracked_tickers()` 的四表聯集（純觀察中、尚無交易的
        股票沒有持股可言，不該出現在持股彙總裡）。"""
        if ticker:
            return self._holdings_from_trades(ticker, self.list_trades(ticker))
        tickers = sorted({row["ticker"] for row in self.list_trades()})
        return {"holdings": [
            self._holdings_from_trades(tk, self.list_trades(tk)) for tk in tickers
        ]}

    @staticmethod
    def _holdings_from_trades(ticker, trades):
        """單一股票的簡單加權平均成本彙總。`trades` 需已依時間排序
        （`list_trades()` 回傳本來就依 trade_date, id 排序）。賣出後
        `shares_held` 歸零時 `avg_cost` 重設為 `None`（沒有部位就沒有
        「均價」這個概念，不留舊值造成誤解）。"""
        shares_held = 0.0
        avg_cost = None
        realized = 0.0
        for t in trades:
            if t["action"] == "buy":
                prior_cost = (avg_cost or 0.0) * shares_held
                shares_held += t["shares"]
                avg_cost = (prior_cost + t["shares"] * t["price"]) / shares_held \
                    if shares_held else None
            else:  # sell
                if avg_cost is not None:
                    realized += (t["price"] - avg_cost) * t["shares"]
                shares_held -= t["shares"]
                if shares_held <= 0:
                    shares_held = 0.0
                    avg_cost = None
        return {"ticker": ticker, "shares_held": shares_held,
                "avg_cost": avg_cost, "realized": realized}

    # ---------- us_stances ----------

    def save_stance(self, ticker, direction, summary, full_note,
                     bear_price=None, bear_price_high=None,
                     base_price_low=None, base_price_high=None,
                     bull_price=None, status="active"):
        """新增一筆立場／研究筆記。一檔股票可有多筆（每次重新討論後勢都
        新增一筆，不覆蓋舊的，見 data-model.md「生命週期」）。`full_note`
        不得為空——FR-009 要求保留完整研究筆記內容，不可只存摘要。"""
        if direction not in VALID_STANCE_DIRECTIONS:
            raise ValueError(
                "direction 必須是 %s，收到：%s" % (VALID_STANCE_DIRECTIONS, direction))
        if status not in VALID_STANCE_STATUSES:
            raise ValueError(
                "status 必須是 %s，收到：%s" % (VALID_STANCE_STATUSES, status))
        if not full_note or not full_note.strip():
            raise ValueError("full_note 不得為空（FR-009 要求完整研究筆記內容）")
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO us_stances"
            " (ticker, created_at, direction, bear_price, bear_price_high,"
            "  base_price_low, base_price_high, bull_price, summary, full_note, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, created_at, direction, bear_price, bear_price_high,
             base_price_low, base_price_high, bull_price, summary, full_note,
             status),
        )
        self.conn.commit()
        return self.get_stance(cur.lastrowid)

    def get_stance(self, stance_id):
        row = self.conn.execute(
            "SELECT * FROM us_stances WHERE id=?", (stance_id,)).fetchone()
        return dict(row) if row else None

    def get_latest_stance(self, ticker, include_closed=False):
        """預設只回傳最新一筆 `status='active'` 的立場（contracts 工具五
        `get_us_stance` 的預設行為）；`include_closed=True` 時不篩選
        status，回傳最新一筆（不論 active/closed）。"""
        if include_closed:
            row = self.conn.execute(
                "SELECT * FROM us_stances WHERE ticker=? ORDER BY id DESC LIMIT 1",
                (ticker,)).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM us_stances WHERE ticker=? AND status='active'"
                " ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
        return dict(row) if row else None

    def list_stances(self, ticker=None, include_closed=True):
        query = "SELECT * FROM us_stances"
        conditions = []
        params = []
        if ticker:
            conditions.append("ticker=?")
            params.append(ticker)
        if not include_closed:
            conditions.append("status='active'")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ---------- us_watch_conditions ----------

    def save_watch_condition(self, ticker, metric_type, comparator, threshold):
        """新增一筆監控條件。新建立時固定 `status='insufficient_data'`、
        `last_evaluated_at=NULL`（data-model.md §3 狀態轉換規則）——狀態
        評估／推播邏輯是 Phase 5（US3，T027）的擴充範圍，這裡只負責
        schema 與新增/查詢。"""
        if comparator not in VALID_WATCH_COMPARATORS:
            raise ValueError(
                "comparator 必須是 %s，收到：%s"
                % (VALID_WATCH_COMPARATORS, comparator))
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO us_watch_conditions"
            " (ticker, metric_type, comparator, threshold, status, created_at)"
            " VALUES (?, ?, ?, ?, 'insufficient_data', ?)",
            (ticker, metric_type, comparator, threshold, created_at),
        )
        self.conn.commit()
        return self.get_watch_condition(cur.lastrowid)

    def get_watch_condition(self, condition_id):
        row = self.conn.execute(
            "SELECT * FROM us_watch_conditions WHERE id=?",
            (condition_id,)).fetchone()
        return dict(row) if row else None

    def list_watch_conditions(self, ticker=None):
        if ticker:
            rows = self.conn.execute(
                "SELECT * FROM us_watch_conditions WHERE ticker=? ORDER BY id",
                (ticker,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM us_watch_conditions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---------- us_price_snapshots ----------

    def save_price_snapshot(self, ticker, snapshot_date, close_price=None,
                             gaap_gross_margin=None, revenue_yoy=None,
                             source="fmp"):
        """寫入一筆報價快照。`(ticker, snapshot_date)` 唯一——同一天排程
        對同一檔股票重複呼叫會覆蓋既有值（UPSERT），不是疊加新列，對應
        data-model.md §4「同一天排程對同一檔股票只會成功寫入一筆」。若
        當天排程對某股跳過（額度用盡/查詢失敗），呼叫端就不該呼叫這個
        方法——該股當天完全沒有紀錄，形成預期中的「歷史缺口」。"""
        fetched_at = _now()
        self.conn.execute(
            "INSERT INTO us_price_snapshots"
            " (ticker, snapshot_date, close_price, gaap_gross_margin,"
            "  revenue_yoy, source, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker, snapshot_date) DO UPDATE SET"
            "   close_price=excluded.close_price,"
            "   gaap_gross_margin=excluded.gaap_gross_margin,"
            "   revenue_yoy=excluded.revenue_yoy,"
            "   source=excluded.source,"
            "   fetched_at=excluded.fetched_at",
            (ticker, snapshot_date, close_price, gaap_gross_margin,
             revenue_yoy, source, fetched_at),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM us_price_snapshots WHERE ticker=? AND snapshot_date=?",
            (ticker, snapshot_date)).fetchone()
        return dict(row) if row else None

    def list_price_snapshots(self, ticker, days=90):
        """依 `snapshot_date` 由舊到新回傳最近 `days` 筆快照（供股價走勢圖
        使用，見 contracts `get_us_price_history`）。"""
        rows = self.conn.execute(
            "SELECT * FROM us_price_snapshots WHERE ticker=?"
            " ORDER BY snapshot_date DESC LIMIT ?",
            (ticker, days)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def price_history_with_gaps(self, ticker, days=90):
        """股價走勢圖資料（contracts 工具八 `get_us_price_history`，
        FR-003）：`us_price_snapshots` 依日期排序的時間序列，並標示相鄰
        兩筆快照之間「本該有平日快照卻缺漏」的日期，供前端圖表決定要不要
        顯示斷點。

        缺口偵測用「平日（週一~週五）」當基準，不精確排除美股假日
        （需要完整的 NYSE 假日表，超出本階段範圍）——寧可把假日也列成
        「缺口」（前端頂多多顯示幾個無害的斷點提示），也不要漏掉真正的
        資料缺口（額度用盡/排程失敗，見 data-model.md §4「歷史缺口」）。
        """
        snapshots = self.list_price_snapshots(ticker, days=days)
        history = [{"date": s["snapshot_date"], "close_price": s["close_price"]}
                   for s in snapshots]
        gap_dates = []
        for prev, cur in zip(snapshots, snapshots[1:]):
            gap_dates.extend(_business_days_between(
                prev["snapshot_date"], cur["snapshot_date"]))
        return {"ticker": ticker, "days": days, "history": history,
                "gap_dates": gap_dates}

    # ---------- 追蹤清單（FR-013：四表 ticker 聯集） ----------

    def get_tracked_tickers(self):
        """追蹤中股票清單＝四張表任一張出現過的 ticker 聯集（data-model.md
        「實體關係總覽」定義），不是獨立的第五張表。供
        `us_stock_scan.py` 決定要抓哪些股票的報價。"""
        tickers = set()
        for table in _TRACKED_TABLES:
            rows = self.conn.execute(
                "SELECT DISTINCT ticker FROM %s" % table).fetchall()
            tickers.update(r["ticker"] for r in rows)
        return sorted(tickers)
