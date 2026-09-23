"""把查詢條件轉成掃描作業：組合枚舉、未完成推導、執行、狀態判定。

## 與相鄰模組的分工

- `flight_search.py`：查價這件事本身（行程枚舉、間隔挑選、瀏覽器查價、
  速率守衛、查價快取）。**本模組不重新實作其中任何一項**，只呼叫。
- `flight_store.py`：條件與結果的持久化。
- 本模組：兩者之間的編排——條件展開成組合、扣掉已查過的、執行、
  把結果寫回、推導出使用者看得到的狀態。

## 為什麼不儲存掃描進度

「哪些組合已完成」這個事實**已經被查價快取持久化了**。再存一份進度就是
同一事實的第二份來源，兩者不同步時無從判斷誰對。枚舉是純函式（相同條件
必得相同組合），所以「未完成 ＝ 枚舉組合 − 已在快取的組合」是確定的，
且跨服務重啟自然成立。

被否決的替代方案是比照 `app/routers/photos.py` 用模組內記憶體字典——
該檔案 docstring 自述「只有伺服器 process 真的重啟才會遺失，這是 MVP
階段的合理簡化」。相簿匯入是單次數分鐘的作業，該簡化可接受；本功能的
掃描會跨數小時與服務重啟（速率上限所致），同樣的簡化會直接違反
spec US3 情境 4。完整推導見 `specs/005-flight-scan-page/research.md` §2。
"""
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import flight_search as fs  # noqa: E402
from flight_store import FlightStore  # noqa: E402

# 策略對應的間隔天數。`auto` 不在此表——它要為每個日期各自挑選，
# 由 `_resolve_offsets()` 呼叫 flight_search.pick_lead()／pick_trail()。
STRATEGY_DAYS = {
    "none": 1,     # 不拉遠：緊接主行程（第1段前一天、第4段後一天）
    "m1": 30,
    "m3": 90,
    "m5": 150,
}

# `auto` 模式的候選天數，**由大到小排列**。
#
# 順序即偏好順序：`pick_lead()`／`pick_trail()` 回傳第一個合格值，不做
# 最佳化。2026-09-23 實測踩過此坑——候選寫成由小到大時，每組都挑到最小
# 間隔（第4段緊接回程），那正是 PO 要避免的密集行程。避開月份是約束，
# 拉遠是目標，兩者不同（spec FR-008、CON-14）。
AUTO_LEAD_CANDIDATES = [210, 180, 150, 120, 90, 60, 30]
AUTO_TRAIL_CANDIDATES = [150, 120, 90, 60, 30, 14, 1]


def _months_between(window_start, window_end):
    """把 YYYY-MM 區間換算成 sample_dates 需要的起始日與月份數。"""
    start = datetime.datetime.strptime(window_start, "%Y-%m").date()
    end = datetime.datetime.strptime(window_end, "%Y-%m").date()
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return start.isoformat(), max(1, months)


def _resolve_offsets(track, outbound_date, return_date):
    """決定這一組主行程日期要用的第1段提前與第4段延後天數。

    非 `auto` 策略直接取固定值；`auto` 則為**這個日期**各自挑選，
    因為單一固定值無法同時滿足所有月份（spec FR-007）。
    回傳 (lead, trail)，任一端無可行值時該端為 None，呼叫端應整組跳過。
    """
    ex = track.get("exclude_months") or {}

    if track.get("lead_strategy") == "auto":
        lead = fs.pick_lead(outbound_date, AUTO_LEAD_CANDIDATES,
                            ex.get("lead") or [])
    else:
        lead = STRATEGY_DAYS.get(track.get("lead_strategy", "none"), 1)

    if track.get("trail_strategy") == "auto":
        trail = fs.pick_trail(return_date, AUTO_TRAIL_CANDIDATES,
                              ex.get("trail") or [])
    else:
        trail = STRATEGY_DAYS.get(track.get("trail_strategy", "none"), 1)

    return lead, trail


def expand_track(track):
    """把查詢條件展開成完整的組合清單。

    回傳 (itineraries, skipped)。`skipped` 是所有候選間隔都無法避開排除
    月份而被整組跳過的日期（spec FR-010），含原因供介面說明。

    枚舉本身全部委派給 `flight_search`：日期抽樣用 `sample_dates()`、
    四段行程用 `build_itineraries_fixed_trip()`，本函式只負責「條件怎麼
    對應到那些函式的參數」。
    """
    start_date, months = _months_between(track["window_start"],
                                         track["window_end"])
    ex = track.get("exclude_months") or {}
    pairs = fs.sample_dates(
        months_ahead=months,
        per_month=track.get("samples_per_month", 2),
        trip_days=track["trip_days"],
        start_date=start_date,
        exclude_months=ex.get("trip") or [],
    )

    itineraries, skipped = [], []
    for outbound_date, return_date in pairs:
        lead, trail = _resolve_offsets(track, outbound_date, return_date)
        if lead is None or trail is None:
            which = "第1段" if lead is None else "第4段"
            skipped.append({"outbound_date": outbound_date,
                            "reason": "no_feasible_offset",
                            "detail": "%s 找不到能避開排除月份的間隔" % which})
            continue
        itineraries.extend(fs.build_itineraries_fixed_trip(
            track["destination"], outbound_date, return_date,
            track["outstations"], track["hub"], [lead], [trail]))
    return itineraries, skipped


def _is_cached(itinerary, data_dir, currency=fs.DEFAULT_CURRENCY,
               gl="tw", hl="zh-TW"):
    key = fs._cache_key(itinerary["legs"], 1, 1, currency, gl, hl)
    return fs._read_cache(data_dir, key) is not None


def pending_combinations(track, data_dir):
    """尚未查過的組合 ＝ 枚舉組合 − 已在查價快取中的組合。

    這是「不儲存進度」的核心（見模組 docstring）。跨時段續掃與服務重啟後
    接續，都靠這個推導自然成立。
    """
    itineraries, _skipped = expand_track(track)
    return [i for i in itineraries if not _is_cached(i, data_dir)]


def scan_plan(track, data_dir, hourly_limit=fs.HOURLY_BROWSER_LIMIT):
    """回報「這次觸發會做什麼」，不實際查價。

    供觸發端點在背景任務啟動前回應使用者：總共幾組、幾組已有結果、
    本時段能查幾組、配額不足時還要等多久。
    """
    itineraries, skipped = expand_track(track)
    pending = [i for i in itineraries if not _is_cached(i, data_dir)]
    left = (fs.remaining_browser_quota(data_dir, hourly_limit)
            if hourly_limit else len(pending))
    return {
        "planned": len(itineraries),
        "already_cached": len(itineraries) - len(pending),
        "pending": len(pending),
        "will_query": min(len(pending), left),
        "quota_left": left,
        "seconds_until_free": (fs.seconds_until_quota_frees(data_dir,
                                                            hourly_limit)
                               if hourly_limit else 0),
        "skipped": skipped,
    }


def run_scan(track_id, data_dir, hourly_limit=fs.HOURLY_BROWSER_LIMIT,
             min_delay_ms=fs.SCRAPE_MIN_DELAY_MS,
             max_delay_ms=fs.SCRAPE_MAX_DELAY_MS,
             session_limit=fs.SCRAPE_SESSION_LIMIT, progress=None):
    """執行一輪掃描並把結果寫回資料庫。

    **供背景任務呼叫**：自行建立與關閉 `FlightStore` 連線，不接受外部傳入
    的 store 物件——request-scoped 的連線在 response 送出後可能已被關閉
    （`app/routers/photos.py` 記錄的坑）。

    回傳本輪摘要。被阻擋或配額用盡都不是錯誤，會如實回報狀態。
    """
    store = FlightStore(data_dir)
    try:
        track = store.get_track(track_id)
        if track is None:
            return {"error": "track_not_found", "track_id": track_id}

        pending = pending_combinations(track, data_dir)
        if not pending:
            store.mark_success(track_id)
            return {"queried": 0, "written": 0, "blocked": False,
                    "note": "no_pending"}

        outcome = fs.scrape_itineraries(
            pending, data_dir=data_dir, min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms, session_limit=session_limit,
            progress=progress, hourly_limit=hourly_limit)
        if outcome.get("error"):
            return {"error": outcome["error"], "queried": 0, "written": 0}

        written = 0
        for row in outcome.get("results", []):
            legs = row["legs"]
            price = row.get("price")
            if price is not None:
                status, price_val = "ok", int(price)
            elif row.get("error") in ("no_fare", "empty"):
                status, price_val = "no_fare", None
            else:
                status, price_val = "failed", None
            store.upsert_result(
                track_id=track_id,
                outstation=row["outstation"],
                leg1_date=legs[0]["date"], outbound_date=legs[1]["date"],
                return_date=legs[2]["date"], leg4_date=legs[3]["date"],
                lead_days=row.get("lead", row.get("out_stay", 0)),
                trail_days=row.get("trail", row.get("ret_stay", 0)),
                status=status, price=price_val,
                airline=(row.get("airlines") or [None])[0],
            )
            written += 1

        # 只有「本輪沒有剩餘未完成組合」才算成功完成一輪——部分完成不更新
        # last_success_at，否則資料過期判定會被部分完成的掃描一直往後推。
        #
        # 這裡**重新推導**而非用本輪回傳筆數判斷，因為查價層可能因配額或
        # 軟阻擋而只做了一部分。推導依賴查價層成功時會寫入查價快取這個
        # 副作用（`scrape_itineraries()` 的既有行為）——替換查價層時
        # 必須一併模擬，否則本判斷永遠為 False。
        if not pending_combinations(track, data_dir):
            store.mark_success(track_id)

        return {
            "queried": len(outcome.get("results", [])),
            "written": written,
            "blocked": outcome.get("blocked", False),
            "soft_blocked": outcome.get("soft_blocked", False),
        }
    finally:
        store.close()


def derive_state(track, data_dir, store=None, scanning=False,
                 hourly_limit=fs.HOURLY_BROWSER_LIMIT, stale_periods=2,
                 period_days=7):
    """推導使用者看得到的狀態。

    七個狀態中只有「資料過期」需要儲存的資訊（`last_success_at`），
    其餘全部即時推導——推導的結果永遠與事實一致，而狀態欄位漏寫就會
    與事實不符（`research.md` §7）。
    """
    pending = pending_combinations(track, data_dir)
    owns_store = store is None
    if owns_store:
        store = FlightStore(data_dir)
    try:
        has_results = store.count_results(track["id"]) > 0
    finally:
        if owns_store:
            store.close()

    last = track.get("last_success_at")
    if last:
        try:
            age = (datetime.datetime.now()
                   - datetime.datetime.fromisoformat(last)).days
            if age > stale_periods * period_days:
                return "stale"
        except ValueError:
            pass

    if scanning:
        return "scanning"
    if not pending:
        return "complete" if has_results else "idle"
    if hourly_limit and fs.remaining_browser_quota(data_dir, hourly_limit) <= 0:
        return "queued"
    return "partial" if has_results else "idle"
