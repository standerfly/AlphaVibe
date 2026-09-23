"""機票查詢條件與掃描結果的持久化（獨立資料庫 `flights.db`）。

**完全不 import 任何投資或相簿模組**，比照 `us_stock_store.py`／
`photo_store.py` 的既有先例——只沿用慣例，程式碼不共用一行。

## 與 `flight_search.py` 的分工

`flight_search.py` 負責「查價這件事」：行程枚舉、間隔挑選、瀏覽器查價、
速率守衛、查價快取。本模組只負責「使用者建立的條件與查到的結果」的
持久化，**不含任何查價邏輯**。

刻意**不把查價快取與配額紀錄遷進本資料庫**：兩者已由 `flight_search.py`
以檔案形式管理（`flight_cache/`、`flight_browser_usage.json`）並經測試
覆蓋，遷移只增加風險而無實益（見 `specs/005-flight-scan-page/research.md`
§1、§6）。

## 兩個必須遵守的既有教訓

1. `sqlite3.connect()` 帶 `check_same_thread=False`——FastAPI 的 sync
   generator dependency 由 anyio thread pool 執行，同一 request 的建立與
   關閉不保證在同一條 worker thread。2026-08-22 正式環境 30 個併發請求
   有 23 個 500（見 `kb_store.py:372` 與 CLAUDE.md 教訓紀錄）。
2. `__init__()` **不得有任何資料寫入副作用**——`kb_store.py` 曾因建構子
   內自動寫入種子資料而污染正式資料庫兩次（同一天的教訓）。
"""
import datetime
import os
import sqlite3

DB_FILENAME = "flights.db"

# 第1段／第4段的間隔策略。`auto` 代表「自動避開排除月份」，實際挑選由
# flight_scan_service 呼叫 flight_search.pick_lead()／pick_trail() 完成。
VALID_STRATEGIES = ("none", "m1", "m3", "m5", "auto")

# 掃描結果狀態。`no_fare`（查到了但無可用票價）與 `failed`（查詢本身失敗）
# 必須分開，spec FR-023 要求介面能區分這兩者。
VALID_RESULT_STATUS = ("ok", "no_fare", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS flight_track (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    destination TEXT NOT NULL,
    hub TEXT NOT NULL,
    outstations TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    trip_days INTEGER NOT NULL,
    lead_strategy TEXT NOT NULL,
    trail_strategy TEXT NOT NULL,
    exclude_months_trip TEXT NOT NULL DEFAULT '',
    exclude_months_lead TEXT NOT NULL DEFAULT '',
    exclude_months_trail TEXT NOT NULL DEFAULT '',
    target_price INTEGER,
    samples_per_month INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    last_success_at TEXT
);

CREATE TABLE IF NOT EXISTS flight_scan_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    outstation TEXT NOT NULL,
    leg1_date TEXT NOT NULL,
    outbound_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    leg4_date TEXT NOT NULL,
    lead_days INTEGER NOT NULL,
    trail_days INTEGER NOT NULL,
    price INTEGER,
    connector_price INTEGER,
    airline TEXT,
    status TEXT NOT NULL,
    queried_at TEXT NOT NULL,
    FOREIGN KEY (track_id) REFERENCES flight_track(id)
);

-- 同一條件下，同一組四段行程只保留一筆（重掃時覆寫而非累積）
CREATE UNIQUE INDEX IF NOT EXISTS idx_flight_result_combo
    ON flight_scan_result (track_id, outstation, leg1_date,
                           outbound_date, return_date, leg4_date);

CREATE INDEX IF NOT EXISTS idx_flight_result_track
    ON flight_scan_result (track_id);
"""


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _parse_months(text):
    """把資料庫裡的逗號字串轉回月份整數清單。"""
    if not text:
        return []
    return [int(x) for x in str(text).split(",") if str(x).strip()]


def _months_to_text(months):
    return ",".join(str(int(m)) for m in (months or []))


def _parse_codes(text):
    if not text:
        return []
    return [c.strip().upper() for c in str(text).split(",") if c.strip()]


def _validate_airport(code, field):
    if not code or not str(code).strip():
        raise ValueError("%s 不得為空" % field)
    code = str(code).strip()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("%s 必須是 3 個英文字母的機場代碼，收到：%r"
                         % (field, code))
    return code.upper()


def _validate_year_month(value, field):
    try:
        datetime.datetime.strptime(str(value), "%Y-%m")
    except (ValueError, TypeError):
        raise ValueError("%s 必須是 YYYY-MM 格式，收到：%r" % (field, value))
    return str(value)


def _validate_months(months, field):
    """排除月份：1-12 任意複選，可不連續，可為空。

    **不得內建任何季節定義**——南半球目的地的旺季與北半球相反
    （spec CON-12，PO 2026-09-23 審閱需求時指正）。
    """
    out = []
    for m in months or []:
        try:
            m = int(m)
        except (ValueError, TypeError):
            raise ValueError("%s 的項目必須是整數，收到：%r" % (field, m))
        if not 1 <= m <= 12:
            raise ValueError("%s 的月份必須介於 1-12，收到：%d" % (field, m))
        if m not in out:
            out.append(m)
    return out


class FlightStore:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, DB_FILENAME)
        # check_same_thread=False：見本檔案 docstring 的教訓 1
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # 刻意不寫入任何資料列——見 docstring 的教訓 2

    def close(self):
        self.conn.close()

    # ---------- flight_track ----------

    def create_track(self, destination, outstations, window_start, window_end,
                     trip_days, hub="TPE", name=None, lead_strategy="none",
                     trail_strategy="none", exclude_months_trip=None,
                     exclude_months_lead=None, exclude_months_trail=None,
                     target_price=None, samples_per_month=2):
        """建立查詢條件。驗證失敗一律拋 ValueError（spec FR-025）。

        `target_price` 在本 feature 僅儲存與顯示，**不觸發任何通知**——
        通知屬 flight-price-tracking（pre-spec handoff order 2）。
        """
        destination = _validate_airport(destination, "destination")
        hub = _validate_airport(hub, "hub")

        codes = _parse_codes(",".join(outstations)
                             if isinstance(outstations, (list, tuple))
                             else outstations)
        if not codes:
            raise ValueError("outstations 不得為空")
        for c in codes:
            _validate_airport(c, "outstations 的項目")

        window_start = _validate_year_month(window_start, "window_start")
        window_end = _validate_year_month(window_end, "window_end")
        if window_end < window_start:
            raise ValueError("window_end（%s）不得早於 window_start（%s）"
                             % (window_end, window_start))

        try:
            trip_days = int(trip_days)
        except (ValueError, TypeError):
            raise ValueError("trip_days 必須是整數，收到：%r" % (trip_days,))
        if trip_days <= 0:
            raise ValueError("trip_days 必須是正整數，收到：%d" % trip_days)

        for field, val in (("lead_strategy", lead_strategy),
                           ("trail_strategy", trail_strategy)):
            if val not in VALID_STRATEGIES:
                raise ValueError("%s 必須是 %s 之一，收到：%r"
                                 % (field, list(VALID_STRATEGIES), val))

        ex_trip = _validate_months(exclude_months_trip, "exclude_months_trip")
        ex_lead = _validate_months(exclude_months_lead, "exclude_months_lead")
        ex_trail = _validate_months(exclude_months_trail, "exclude_months_trail")

        if samples_per_month is None:
            samples_per_month = 2
        samples_per_month = int(samples_per_month)
        if samples_per_month <= 0:
            raise ValueError("samples_per_month 必須是正整數")

        if target_price is not None:
            target_price = int(target_price)
            if target_price < 0:
                raise ValueError("target_price 不得為負")

        if not name or not str(name).strip():
            name = "%s（%s）%s~%s" % (destination, "／".join(codes),
                                      window_start, window_end)

        cur = self.conn.execute(
            "INSERT INTO flight_track"
            " (name, destination, hub, outstations, window_start, window_end,"
            "  trip_days, lead_strategy, trail_strategy, exclude_months_trip,"
            "  exclude_months_lead, exclude_months_trail, target_price,"
            "  samples_per_month, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(name).strip(), destination, hub, ",".join(codes),
             window_start, window_end, trip_days, lead_strategy,
             trail_strategy, _months_to_text(ex_trip),
             _months_to_text(ex_lead), _months_to_text(ex_trail),
             target_price, samples_per_month, _now()),
        )
        self.conn.commit()
        return self.get_track(cur.lastrowid)

    def _row_to_track(self, row):
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "destination": row["destination"],
            "hub": row["hub"],
            "outstations": _parse_codes(row["outstations"]),
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "trip_days": row["trip_days"],
            "lead_strategy": row["lead_strategy"],
            "trail_strategy": row["trail_strategy"],
            "exclude_months": {
                "trip": _parse_months(row["exclude_months_trip"]),
                "lead": _parse_months(row["exclude_months_lead"]),
                "trail": _parse_months(row["exclude_months_trail"]),
            },
            "target_price": row["target_price"],
            "samples_per_month": row["samples_per_month"],
            "created_at": row["created_at"],
            "last_success_at": row["last_success_at"],
        }

    def get_track(self, track_id):
        row = self.conn.execute(
            "SELECT * FROM flight_track WHERE id=?", (track_id,)).fetchone()
        return self._row_to_track(row)

    def list_tracks(self):
        rows = self.conn.execute(
            "SELECT * FROM flight_track ORDER BY id").fetchall()
        return [self._row_to_track(r) for r in rows]

    def delete_track(self, track_id):
        """刪除條件與其掃描結果。

        **不刪除查價快取**——快取以行程組合為鍵、跨條件共用，刪掉會讓其他
        條件（甚至 CLI 使用者）白白重查，且那是 flight_search.py 管理的
        資產，不屬本模組。
        """
        if self.get_track(track_id) is None:
            return False
        self.conn.execute(
            "DELETE FROM flight_scan_result WHERE track_id=?", (track_id,))
        self.conn.execute("DELETE FROM flight_track WHERE id=?", (track_id,))
        self.conn.commit()
        return True

    def mark_success(self, track_id, when=None):
        """記錄本輪掃描成功完成的時間。

        這是**唯一需要儲存的狀態類欄位**——其餘狀態（掃描中／排隊中／
        部分完成／已完成）都能即時推導，只有「資料過期」需要知道上次成功
        是什麼時候，那無法從查價快取反推（快取有價格但不知是第幾輪寫的）。
        見 research.md §7。
        """
        self.conn.execute(
            "UPDATE flight_track SET last_success_at=? WHERE id=?",
            (when or _now(), track_id))
        self.conn.commit()

    # ---------- flight_scan_result ----------

    def upsert_result(self, track_id, outstation, leg1_date, outbound_date,
                      return_date, leg4_date, lead_days, trail_days,
                      status="ok", price=None, connector_price=None,
                      airline=None, queried_at=None):
        """寫入或覆寫一筆組合的報價。

        以 (track_id, 外站, 四段日期) 為唯一鍵覆寫，避免重掃時同一組合
        累積多筆（data-model.md「唯一性」）。
        """
        if status not in VALID_RESULT_STATUS:
            raise ValueError("status 必須是 %s 之一，收到：%r"
                             % (list(VALID_RESULT_STATUS), status))
        if status == "ok" and (price is None or price <= 0):
            raise ValueError("status=ok 時 price 必須是正整數")
        if status != "ok" and price is not None:
            raise ValueError("status=%s 時不應帶 price" % status)

        self.conn.execute(
            "INSERT INTO flight_scan_result"
            " (track_id, outstation, leg1_date, outbound_date, return_date,"
            "  leg4_date, lead_days, trail_days, price, connector_price,"
            "  airline, status, queried_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(track_id, outstation, leg1_date, outbound_date,"
            "             return_date, leg4_date)"
            " DO UPDATE SET price=excluded.price,"
            "               connector_price=excluded.connector_price,"
            "               airline=excluded.airline,"
            "               status=excluded.status,"
            "               lead_days=excluded.lead_days,"
            "               trail_days=excluded.trail_days,"
            "               queried_at=excluded.queried_at",
            (track_id, outstation.upper(), leg1_date, outbound_date,
             return_date, leg4_date, int(lead_days), int(trail_days),
             price, connector_price, airline, status, queried_at or _now()),
        )
        self.conn.commit()

    def list_results(self, track_id):
        """回傳該條件的結果，依價格升冪；查無票價與查詢失敗排在最後。

        排序用 SQL 完成而非 Python，讓「有價格的在前」這個規則只有一處
        定義，避免 API 層與資料層各排一次而分岔。
        """
        rows = self.conn.execute(
            "SELECT * FROM flight_scan_result WHERE track_id=?"
            " ORDER BY CASE WHEN status='ok' THEN 0 ELSE 1 END,"
            "          price ASC, outstation ASC",
            (track_id,)).fetchall()
        out = []
        for r in rows:
            out.append({
                "outstation": r["outstation"],
                "leg1_date": r["leg1_date"],
                "outbound_date": r["outbound_date"],
                "return_date": r["return_date"],
                "leg4_date": r["leg4_date"],
                "lead_days": r["lead_days"],
                "trail_days": r["trail_days"],
                "price": r["price"],
                "connector_price": r["connector_price"],
                "airline": r["airline"],
                "status": r["status"],
                "queried_at": r["queried_at"],
            })
        return out

    def update_connector_prices(self, track_id, prices_by_outstation):
        """批次寫入各外站的接駁票估價。

        接駁價以**外站**為單位估算（單一代表日期），不隨每個組合的日期
        逐一查詢——那會讓查詢量倍增，而接駁票價的日期敏感度遠低於四段票
        （data-model.md「與既有資料的關係」）。
        """
        n = 0
        for outstation, price in (prices_by_outstation or {}).items():
            if price is None:
                continue
            cur = self.conn.execute(
                "UPDATE flight_scan_result SET connector_price=?"
                " WHERE track_id=? AND outstation=?",
                (int(price), track_id, outstation.upper()))
            n += cur.rowcount
        self.conn.commit()
        return n

    def count_results(self, track_id):
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM flight_scan_result WHERE track_id=?",
            (track_id,)).fetchone()
        return row["n"] if row else 0

    def lowest_result(self, track_id):
        """最低價那筆（只看 status='ok'）；沒有則回 None。"""
        row = self.conn.execute(
            "SELECT * FROM flight_scan_result"
            " WHERE track_id=? AND status='ok' AND price IS NOT NULL"
            " ORDER BY price ASC LIMIT 1", (track_id,)).fetchone()
        if row is None:
            return None
        return {
            "price": row["price"],
            "outstation": row["outstation"],
            "outbound_date": row["outbound_date"],
            "return_date": row["return_date"],
        }
