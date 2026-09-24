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


def months_between(window_start, window_end):
    """把 YYYY-MM 區間換算成 sample_dates 需要的起始日與月份數。

    007：升格為公開函式——`app/routers/flights.py` 的組合數上限守衛
    （建立條件前，不經過完整 `expand_track()`）需要用同一個月份數算法，
    不能各自算一份而分岔。
    """
    start = datetime.datetime.strptime(window_start, "%Y-%m").date()
    end = datetime.datetime.strptime(window_end, "%Y-%m").date()
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return start.isoformat(), max(1, months)


# 007：建立條件時的組合數上限守衛（避免天數區間帶來的組合數暴增吃光
# 共用查詢配額）。60 是 pre-spec 階段的 Claude 提案並經 PO 採納的
# assumption，非精確驗證過的數字——依現行速率上限約 20 筆／小時推算，
# 60 組合約需 3 小時分批查完，是背景排程可接受的上限，可隨時調整
# （見 docs/spec-intake/flight-roundtrip-search/clarification-log.md
# Q-010、specs/007-trip-day-range/spec.md「Assumptions」）。
MAX_COMBINATIONS_PER_TRACK = 60


def combination_count(months, samples_per_month, num_targets, num_day_options):
    """算出一個追蹤條件展開後的查詢組合數。

    刻意寫成**不依賴 `Track` 物件形狀**的純函式，只吃抽象計數參數
    （月份數、每月抽樣數、目標數量、天數選項數）——四段票的「目標數量」
    是外站數，未來 roundtrip-search 包的「目標數量」是候選目的地數，
    兩者可以呼叫同一支函式而不需要共用資料模型，避免各自實作一份
    幾乎相同的算法而分岔（research.md §4）。
    """
    return int(months) * int(samples_per_month) * int(num_targets) * int(num_day_options)


def _resolve_offsets(track, outbound_date, return_date):
    """決定這一組主行程日期要用的第1段提前與第4段延後天數。

    非 `auto` 策略直接取固定值；`auto` 則為**這個日期**各自挑選，
    因為單一固定值無法同時滿足所有月份（spec FR-007）。
    回傳 (lead, trail)，任一端無可行值時該端為 None，呼叫端應整組跳過。

    2026-09-24 修正：固定策略（`m1`／`m3`／`m5`）原本沒有檢查算出來的
    航段日期是否已經過去——`auto` 策略透過 `pick_lead()`/`pick_trail()`
    內的 `_pick_offset()` 早就擋了這件事（`target <= today` 就跳過），
    但固定策略直接套用 `STRATEGY_DAYS` 的天數，完全不檢查。近期建立的
    主行程配上較大的固定提前量（例如主行程 2027-04、lead=90 天）會把
    第1段推到今天之前——那是已經飛走的航班，買不到，只會白佔查詢配額。
    修法：兩端都補上「結果日期不得早於或等於今天」的檢查，不合格時視同
    `auto` 策略的「找不到可行值」，回傳 None 讓呼叫端整組跳過並記錄原因
    （與既有的 `no_feasible_offset` skip 邏輯一致，不必新增分支）。
    """
    ex = track.get("exclude_months") or {}
    today = datetime.date.today()
    lead_reason = trail_reason = None

    if track.get("lead_strategy") == "auto":
        lead = fs.pick_lead(outbound_date, AUTO_LEAD_CANDIDATES,
                            ex.get("lead") or [])
        if lead is None:
            lead_reason = "excluded_month"
    else:
        lead = STRATEGY_DAYS.get(track.get("lead_strategy", "none"), 1)
        leg1 = (datetime.date.fromisoformat(outbound_date)
               - datetime.timedelta(days=lead))
        if leg1 <= today:
            lead, lead_reason = None, "past_date"

    if track.get("trail_strategy") == "auto":
        trail = fs.pick_trail(return_date, AUTO_TRAIL_CANDIDATES,
                              ex.get("trail") or [])
        if trail is None:
            trail_reason = "excluded_month"
    else:
        trail = STRATEGY_DAYS.get(track.get("trail_strategy", "none"), 1)
        leg4 = (datetime.date.fromisoformat(return_date)
               + datetime.timedelta(days=trail))
        if leg4 <= today:
            trail, trail_reason = None, "past_date"

    return lead, trail, lead_reason, trail_reason


def expand_track(track):
    """把查詢條件展開成完整的組合清單。

    回傳 (itineraries, skipped)。`skipped` 是所有候選間隔都無法避開排除
    月份而被整組跳過的日期（spec FR-010），含原因供介面說明。

    枚舉本身全部委派給 `flight_search`：日期抽樣用 `sample_dates()`、
    四段行程用 `build_itineraries_fixed_trip()`，本函式只負責「條件怎麼
    對應到那些函式的參數」。

    007 天數區間化：對 `trip_days_min`～`trip_days_max` 內每個天數值
    各呼叫一次 `sample_dates()`，再累加所有 `(天數, outbound_date,
    return_date)` 組合逐一處理。`sample_dates()`／
    `build_itineraries_fixed_trip()` 本身不需要改動——出發日的抽樣
    不依賴天數，只有回程日會變（specs/007-trip-day-range/research.md
    §1）。同一個出發日在不同天數選項下，lead／trail 是否可行可能不同
    （trail 依賴 return_date，隨天數而變），所以 skip 判斷仍以每個
    `(天數, outbound_date)` 組合各自為單位。
    """
    start_date, months = months_between(track["window_start"],
                                        track["window_end"])
    ex = track.get("exclude_months") or {}
    day_options = range(track["trip_days_min"], track["trip_days_max"] + 1)
    pairs = []
    for days in day_options:
        for outbound_date, return_date in fs.sample_dates(
                months_ahead=months,
                per_month=track.get("samples_per_month", 2),
                trip_days=days,
                start_date=start_date,
                exclude_months=ex.get("trip") or []):
            pairs.append((days, outbound_date, return_date))

    itineraries, skipped = [], []
    for days, outbound_date, return_date in pairs:
        lead, trail, lead_reason, trail_reason = _resolve_offsets(
            track, outbound_date, return_date)
        if lead is None or trail is None:
            which = "第1段" if lead is None else "第4段"
            reason = lead_reason if lead is None else trail_reason
            detail = ("%s 已經是過去日期，買不到票" % which
                      if reason == "past_date"
                      else "%s 找不到能避開排除月份的間隔" % which)
            skipped.append({"outbound_date": outbound_date,
                            "trip_days": days,
                            "reason": reason or "no_feasible_offset",
                            "detail": detail})
            continue
        itineraries.extend(fs.build_itineraries_fixed_trip(
            track["destination"], outbound_date, return_date,
            track["outstations"], track["hub"], [lead], [trail]))
    return itineraries, skipped


def expand_roundtrip_track(track):
    """把單純來回追蹤條件展開成完整的組合清單（008）。

    回傳 (itineraries, skipped)——形狀與 `expand_track()` 對稱，但
    `skipped` 目前恆為空清單：單純來回沒有第1/4段、沒有 lead/trail
    排除月份判斷（那是四段票特有的概念），沒有東西會因為「找不到
    可行間隔」而被跳過。保留這個回傳形狀是為了讓呼叫端（建立時的
    組合數驗證等）不必依 track_type 另外分兩套介面。

    對每個候選目的地 × 天數區間內每個天數值，呼叫既有 `sample_dates()`
    展開 `(outbound_date, return_date)`，再依是否指定
    `preferred_transit` 決定組 2 段（純來回）或 4 段（含轉機）的
    `legs`——`google_flights_url()` 依段數自動判斷 trip type，本函式
    不需要關心那個細節（research.md §1）。指定轉機時，第1、2 段共用
    `outbound_date`、第3、4 段共用 `return_date`：這是**同一趟行程被
    強制走指定轉機點**，不是四段票那種刻意拉開日期、包裝成兩趟獨立
    行程的結構（四段票的 lead/trail 概念本次不適用，research.md §2）。
    """
    start_date, months = months_between(track["window_start"],
                                        track["window_end"])
    hub = track.get("hub", "TPE")
    transit = track.get("preferred_transit")
    pairs = []
    for days in range(track["trip_days_min"], track["trip_days_max"] + 1):
        for outbound_date, return_date in fs.sample_dates(
                months_ahead=months,
                per_month=track.get("samples_per_month", 2),
                trip_days=days,
                start_date=start_date):
            pairs.append((days, outbound_date, return_date))

    itineraries = []
    for destination in track["destinations"]:
        for days, outbound_date, return_date in pairs:
            if transit:
                legs = [
                    {"departure_id": hub, "arrival_id": transit,
                     "date": outbound_date},
                    {"departure_id": transit, "arrival_id": destination,
                     "date": outbound_date},
                    {"departure_id": destination, "arrival_id": transit,
                     "date": return_date},
                    {"departure_id": transit, "arrival_id": hub,
                     "date": return_date},
                ]
            else:
                legs = [
                    {"departure_id": hub, "arrival_id": destination,
                     "date": outbound_date},
                    {"departure_id": destination, "arrival_id": hub,
                     "date": return_date},
                ]
            itineraries.append({
                "destination": destination,
                "outbound_date": outbound_date,
                "return_date": return_date,
                "trip_days": days,
                "legs": legs,
            })
    return itineraries, []


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


def _connector_probe_date(track, store, track_id):
    """接駁票估價要用哪一天。

    取已有結果中**最早的第1段日期**——接駁票要在第1段之前飛到外站，
    用最早那天估價最接近實際需求。沒有結果時退回區間起始月的月初。
    """
    results = store.list_results(track_id)
    dates = [r["leg1_date"] for r in results if r.get("leg1_date")]
    if dates:
        return min(dates)
    return track["window_start"] + "-01"


def _row_from_itinerary(itin, summary):
    """把一組行程＋價格摘要轉成 upsert_result 需要的欄位。"""
    legs = itin["legs"]
    price = summary.get("price") if summary else None
    return {
        "outstation": itin["outstation"],
        "leg1_date": legs[0]["date"], "outbound_date": legs[1]["date"],
        "return_date": legs[2]["date"], "leg4_date": legs[3]["date"],
        "lead_days": itin.get("lead", 0), "trail_days": itin.get("trail", 0),
        "status": "ok" if price else "no_fare",
        "price": int(price) if price else None,
        # 2026-09-24 修正：原本只取 airlines[0]，四段航程分屬不同公司時
        # 會悄悄丟掉其他航段的資料。改存全部去重後的名單（用「／」join，
        # 跟本檔案其他多值欄位的顯示慣例一致），顯示時交給
        # fs.describe_airlines() 判斷是否同一聯盟
        "airline": "／".join(dict.fromkeys((summary or {}).get("airlines") or [])) or None,
    }


def sync_cached_results(track_id, track, data_dir, store):
    """把**已在查價快取、但資料庫還沒有**的組合補寫進結果表。

    為什麼需要這一步：`pending_combinations()` 只回報「還沒查過的組合」，
    而查價快取是跨條件共用的。新建一個條件時，如果它的組合先前已被別的
    條件（或 CLI）查過，pending 會是 0——掃描直接判定完成，但結果表裡
    一筆都沒有，使用者看到「已完成」卻沒有任何結果。

    2026-09-23 真實驗證時踩到：建立條件→觸發→回 complete→結果空白。
    單元測試抓不到，因為測試都從空快取開始。
    """
    itineraries, _skipped = expand_track(track)
    existing = set()
    for r in store.list_results(track_id):
        existing.add((r["outstation"], r["leg1_date"], r["outbound_date"],
                      r["return_date"], r["leg4_date"]))
    written = 0
    for itin in itineraries:
        legs = itin["legs"]
        key = (itin["outstation"], legs[0]["date"], legs[1]["date"],
               legs[2]["date"], legs[3]["date"])
        if key in existing:
            continue
        ck = fs._cache_key(legs, 1, 1, fs.DEFAULT_CURRENCY, "tw", "zh-TW")
        cached = fs._read_cache(data_dir, ck)
        if cached is None:
            continue
        store.upsert_result(track_id=track_id, **_row_from_itinerary(itin, cached))
        written += 1
    return written


def ensure_connector_prices(track_id, track, data_dir, store,
                            hourly_limit=fs.HOURLY_BROWSER_LIMIT):
    """補齊尚未估價的外站接駁票（FR-020）。

    **只在配額還有剩時執行**——接駁價是輔助資訊（不參與達標判定，
    Q-016），不該排擠真正要查的四段票。配額不足就跳過，下一輪再估。

    抽成獨立函式是因為有兩條路徑會需要它：一般掃描（`run_scan`），
    以及「組合全部命中快取、不需查價」的情況——後者不會進 `run_scan`，
    但結果同樣需要接駁價。

    回傳實際更新的列數。任何失敗都吞掉並回 0：接駁價缺了只是少一欄
    參考資訊，不該讓主結果連帶失敗。
    """
    try:
        if hourly_limit is not None and fs.remaining_browser_quota(
                data_dir, hourly_limit) <= 0:
            return 0
        missing = [r["outstation"] for r in store.list_results(track_id)
                   if r.get("connector_price") is None]
        if not missing:
            return 0
        probe_date = _connector_probe_date(track, store, track_id)
        prices = fs.estimate_connectors_browser(
            sorted(set(missing)), probe_date, hub=track["hub"],
            data_dir=data_dir, hourly_limit=hourly_limit)
        return store.update_connector_prices(track_id, prices)
    except Exception:
        return 0


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

        # 先把已在快取、但結果表還沒有的組合補進來——否則新條件若命中
        # 既有快取，會出現「已完成但沒有任何結果」（見 sync_cached_results）
        from_cache = sync_cached_results(track_id, track, data_dir, store)

        pending = pending_combinations(track, data_dir)
        if not pending:
            store.mark_success(track_id)
            return {"queried": 0, "written": from_cache, "blocked": False,
                    "from_cache": from_cache, "note": "no_pending"}

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
                # 同上（_row_from_itinerary 的註解）：保留全部航空公司，
                # 不只取第一家
                airline="／".join(dict.fromkeys(row.get("airlines") or [])) or None,
            )
            written += 1

        ensure_connector_prices(track_id, track, data_dir, store, hourly_limit)

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


# ---------- 單純來回（008）：與上面四段票的對應函式平行存在 ----------
#
# 不共用實作：四段票版本綁死 outstation／leg1_date～leg4_date／
# lead_days／trail_days／connector_price 這組欄位形狀（`_row_from_
# itinerary()`／`run_scan()` 內都直接假設這個形狀），單純來回沒有這些
# 概念（data-model.md）。`_is_cached()` 是唯一雙方共用不變的函式——
# 它只依賴 `itinerary["legs"]`，兩種類型的 itinerary 都有這個欄位。

def pending_roundtrip_combinations(track, data_dir):
    """尚未查過的組合（比照 `pending_combinations()`）。"""
    itineraries, _skipped = expand_roundtrip_track(track)
    return [i for i in itineraries if not _is_cached(i, data_dir)]


def roundtrip_scan_plan(track, data_dir, hourly_limit=fs.HOURLY_BROWSER_LIMIT):
    """回報「這次觸發會做什麼」（比照 `scan_plan()`）。"""
    itineraries, skipped = expand_roundtrip_track(track)
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


def _row_from_roundtrip_itinerary(itin, summary):
    """把一組行程＋價格摘要轉成 `upsert_roundtrip_result()` 需要的欄位
    （比照 `_row_from_itinerary()`）。"""
    price = summary.get("price") if summary else None
    return {
        "destination": itin["destination"],
        "outbound_date": itin["outbound_date"],
        "return_date": itin["return_date"],
        "status": "ok" if price else "no_fare",
        "price": int(price) if price else None,
        "airline": "／".join(dict.fromkeys(
            (summary or {}).get("airlines") or [])) or None,
    }


def sync_cached_roundtrip_results(track_id, track, data_dir, store):
    """把已在查價快取、但結果表還沒有的組合補寫進去（比照
    `sync_cached_results()`，理由與 007 事故背景相同）。"""
    itineraries, _skipped = expand_roundtrip_track(track)
    existing = set()
    for r in store.list_roundtrip_results(track_id):
        existing.add((r["destination"], r["outbound_date"], r["return_date"]))
    written = 0
    for itin in itineraries:
        key = (itin["destination"], itin["outbound_date"], itin["return_date"])
        if key in existing:
            continue
        ck = fs._cache_key(itin["legs"], 1, 1, fs.DEFAULT_CURRENCY, "tw", "zh-TW")
        cached = fs._read_cache(data_dir, ck)
        if cached is None:
            continue
        store.upsert_roundtrip_result(
            track_id=track_id, **_row_from_roundtrip_itinerary(itin, cached))
        written += 1
    return written


def run_roundtrip_scan(track_id, data_dir, hourly_limit=fs.HOURLY_BROWSER_LIMIT,
                       min_delay_ms=fs.SCRAPE_MIN_DELAY_MS,
                       max_delay_ms=fs.SCRAPE_MAX_DELAY_MS,
                       session_limit=fs.SCRAPE_SESSION_LIMIT, progress=None):
    """執行一輪單純來回掃描並把結果寫回資料庫（比照 `run_scan()`）。

    不含接駁價估算——單純來回沒有接駁票概念（data-model.md）。
    """
    store = FlightStore(data_dir)
    try:
        track = store.get_roundtrip_track(track_id)
        if track is None:
            return {"error": "track_not_found", "track_id": track_id}

        from_cache = sync_cached_roundtrip_results(track_id, track, data_dir,
                                                    store)

        pending = pending_roundtrip_combinations(track, data_dir)
        if not pending:
            store.mark_roundtrip_success(track_id)
            return {"queried": 0, "written": from_cache, "blocked": False,
                    "from_cache": from_cache, "note": "no_pending"}

        outcome = fs.scrape_itineraries(
            pending, data_dir=data_dir, min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms, session_limit=session_limit,
            progress=progress, hourly_limit=hourly_limit)
        if outcome.get("error"):
            return {"error": outcome["error"], "queried": 0, "written": 0}

        written = 0
        for row in outcome.get("results", []):
            price = row.get("price")
            if price is not None:
                status, price_val = "ok", int(price)
            elif row.get("error") in ("no_fare", "empty"):
                status, price_val = "no_fare", None
            else:
                status, price_val = "failed", None
            store.upsert_roundtrip_result(
                track_id=track_id,
                destination=row["destination"],
                outbound_date=row["outbound_date"],
                return_date=row["return_date"],
                status=status, price=price_val,
                airline="／".join(dict.fromkeys(row.get("airlines") or [])) or None,
            )
            written += 1

        # 同 run_scan()：只有本輪沒有剩餘未完成組合才算成功完成一輪
        if not pending_roundtrip_combinations(track, data_dir):
            store.mark_roundtrip_success(track_id)

        return {
            "queried": len(outcome.get("results", [])),
            "written": written,
            "blocked": outcome.get("blocked", False),
            "soft_blocked": outcome.get("soft_blocked", False),
        }
    finally:
        store.close()


# 排程把條件分散到一週七天，避免同一天累積過多查詢而撞上速率上限。
_SCHEDULE_SLOTS = 7


def scheduled_weekday(track):
    """這個條件排定在星期幾執行（0=週一 … 6=週日）。

    用 `id % 7` 而非隨機或動態計算：需要的性質只有決定性（同一條件每次
    都落在同一天）、分散（不同條件盡量不同天）、免維護（新增條件不必
    重算全體）。取餘數同時滿足三者且不需額外欄位（research.md §2）。
    """
    return int(track["id"]) % _SCHEDULE_SLOTS


def is_due(track, today=None):
    """今天是否該重掃這個條件。

    兩個條件都要成立：**今天輪到它**（排定的星期幾），且**週期已滿**
    （距上次成功已達 `scan_frequency_days` 天，或從未成功過）。

    只看「週期已滿」會讓所有條件在同一天一起跑；只看「今天輪到」則會
    讓每週頻率以外的設定失效。
    """
    today = today or datetime.date.today()
    if scheduled_weekday(track) != today.weekday():
        return False
    last = track.get("last_success_at")
    if not last:
        return True
    try:
        last_date = datetime.datetime.fromisoformat(last).date()
    except (ValueError, TypeError):
        return True
    return (today - last_date).days >= int(track.get("scan_frequency_days", 7))


def next_scan_date(track, today=None):
    """下次預定重掃日。

    從「上次成功 ＋ 一個週期」起算，往後找到第一個符合排定星期幾的日子；
    從未成功過則從今天起算。**這個規則只在這裡定義**——API 與前端都不
    自行推算，否則兩處必然分岔（contracts §2）。
    """
    today = today or datetime.date.today()
    weekday = scheduled_weekday(track)
    last = track.get("last_success_at")
    if last:
        try:
            base = (datetime.datetime.fromisoformat(last).date()
                    + datetime.timedelta(
                        days=int(track.get("scan_frequency_days", 7))))
        except (ValueError, TypeError):
            base = today
    else:
        base = today
    if base < today:
        base = today
    for offset in range(_SCHEDULE_SLOTS + 1):
        candidate = base + datetime.timedelta(days=offset)
        if candidate.weekday() == weekday:
            return candidate.isoformat()
    return base.isoformat()


def due_tracks(store, today=None):
    """今天該重掃的所有四段票條件，依 id 排序（執行順序可預期）。"""
    return [t for t in store.list_tracks() if is_due(t, today)]


def due_roundtrip_tracks(store, today=None):
    """今天該重掃的所有單純來回條件（比照 `due_tracks()`）。

    `is_due()` 只依賴 `id`／`scan_frequency_days`／`last_success_at`
    三個欄位，`roundtrip_track` 都有，函式本身不需要修改
    （specs/008-roundtrip-search/research.md §3）。
    """
    return [t for t in store.list_roundtrip_tracks() if is_due(t, today)]


def should_notify(track, lowest_price, state=None):
    """是否該為這次結果發出通知。

    三個條件都要成立：
    1. 有設定目標價（未設定就不通知，FR-010）
    2. 最低**四段票價** ≤ 目標價——**不含接駁估價**（FR-007，PO 於 Q-016
       決定）。接駁價是估算值且會變動，納入會讓通知時定時不定
    3. 從未通知過，或這次的價格**比上次通知時更低**（FR-009）

    第 3 點是刻意的取捨：單純「達標後不再通知」會讓使用者錯過更好的價格
    （37,000 掉到 32,000 卻沒收到）；每輪都通知則是噪音。以「比上次更低」
    為門檻，兩邊都避開。

    `state` 為 `stale` 時一律不通知（FR-014）——拿過期價格通知，使用者
    跑去看卻發現是舊資料，比沒收到更糟。
    """
    if state == "stale":
        return False
    target = track.get("target_price")
    if target is None or lowest_price is None:
        return False
    if lowest_price > target:
        return False
    last = (track.get("notify") or {}).get("last_notified_price")
    if last is None:
        return True
    return lowest_price < last


def should_notify_status(track, lowest_price, state=None):
    """是否該發送「本輪未達標，目前最低價是多少」的現況通知
    （PO 2026-09-24 新增：「若沒有達成，找最接近的組合」）。

    跟 `should_notify()` 是兩種互斥的通知——`should_notify()` 只在達標
    且比上次通知更低時觸發（刻意避免噪音）；這個函式反過來，服務「不想
    每次都手動開分頁查」的訴求：只要有設目標價、這輪掃描有查到價格、
    且**沒有**達標，就一定通知現況。

    刻意不做去重或降頻——PO 在得知「這會讓每輪排程都收到訊息」的取捨後
    仍選擇兩者都要，所以這裡不額外加「跟上次一樣就不發」的邏輯，那是
    `should_notify()` 的設計、不是這個函式的。呼叫端只會在 `state` 不是
    `stale` 時排程觸發到這裡，但仍在此再擋一次，避免未來新增呼叫點時
    忘記檢查（跟 `should_notify()` 的防護原則一致）。
    """
    if state == "stale":
        return False
    target = track.get("target_price")
    if target is None or lowest_price is None:
        return False
    return lowest_price > target


def _notification_legs(track, lowest_row, hub=None):
    """通知訊息共用的四段航程（達標通知／現況通知都需要同一組資料）。

    連結用既有的 `google_flights_url()` 構造，與 API 層同一支函式——
    那是 base64 protobuf，兩處各寫一份必然分岔（research.md §7）。
    """
    hub = hub or track.get("hub", "TPE")
    return [
        {"departure_id": lowest_row["outstation"], "arrival_id": hub,
         "date": lowest_row["leg1_date"]},
        {"departure_id": hub, "arrival_id": track["destination"],
         "date": lowest_row["outbound_date"]},
        {"departure_id": track["destination"], "arrival_id": hub,
         "date": lowest_row["return_date"]},
        {"departure_id": hub, "arrival_id": lowest_row["outstation"],
         "date": lowest_row["leg4_date"]},
    ]


def _notification_trip_lines(lowest_row):
    """通知訊息共用的行程細節（主行程、外站、航空／聯盟、接駁估價）。"""
    lines = [
        "主行程 %s ~ %s" % (lowest_row["outbound_date"],
                            lowest_row["return_date"]),
        "外站 %s（第1段 %s）" % (lowest_row["outstation"],
                                 lowest_row["leg1_date"]),
    ]
    # 2026-09-24：四段航程不一定是同一家航空公司，標示聯盟資訊（PO
    # 要求）。儲存格式是「／」join 的字串，這裡還原成清單交給
    # describe_airlines() 判斷。
    airline_desc = fs.describe_airlines(
        (lowest_row.get("airline") or "").split("／"))
    if airline_desc:
        lines.append("航空 %s" % airline_desc)
    if lowest_row.get("connector_price"):
        lines.append("接駁估價 NT$%s（不計入達標判定）"
                     % format(int(lowest_row["connector_price"]), ","))
    return lines


def build_notification(track, lowest_row, hub=None):
    """組出達標通知訊息（FR-008）。"""
    legs = _notification_legs(track, lowest_row, hub)
    lines = [
        "✈️ 機票降到目標價以下",
        "",
        "%s" % track["name"],
        "四段票 NT$%s（目標 NT$%s）" % (
            format(int(lowest_row["price"]), ","),
            format(int(track["target_price"]), ",")),
    ]
    lines += _notification_trip_lines(lowest_row)
    lines += ["", fs.google_flights_url(legs), "",
              "提醒：第1段不可 no-show，否則後三段全部失效。"]
    return "\n".join(lines)


def build_status_notification(track, lowest_row, hub=None):
    """組出未達標時的現況通知（PO 2026-09-24 新增）。

    跟 `build_notification()` 的差異只在標題與「還差多少」這行——行程
    細節（主行程／外站／航空／接駁）共用 `_notification_trip_lines()`，
    避免兩份訊息各寫一次而分岔。呼叫端只在 `lowest_row["price"]` 高於
    `target_price` 時才會叫到這裡，這裡不重複驗證。
    """
    legs = _notification_legs(track, lowest_row, hub)
    gap = int(lowest_row["price"]) - int(track["target_price"])
    lines = [
        "📊 本輪掃描完成（尚未達標）",
        "",
        "%s" % track["name"],
        "目前最低 NT$%s（目標 NT$%s，還差 NT$%s）" % (
            format(int(lowest_row["price"]), ","),
            format(int(track["target_price"]), ","),
            format(gap, ",")),
    ]
    lines += _notification_trip_lines(lowest_row)
    lines += ["", fs.google_flights_url(legs)]
    return "\n".join(lines)


def derive_state(track, data_dir, store=None, scanning=False,
                 hourly_limit=fs.HOURLY_BROWSER_LIMIT, stale_periods=2,
                 period_days=None):
    """推導使用者看得到的狀態。

    七個狀態中只有「資料過期」需要儲存的資訊（`last_success_at`），
    其餘全部即時推導——推導的結果永遠與事實一致，而狀態欄位漏寫就會
    與事實不符（`research.md` §7）。
    """
    # 過期判定的週期必須跟著**這個條件的**重掃頻率走。005 原本寫死 7 天，
    # 那會讓「每月一次」的條件在第 15 天被誤判為過期而停止通知——而使用者
    # 只會覺得「怎麼都沒通知」，不會意識到是誤判（quickstart 坑 1）。
    if period_days is None:
        period_days = int(track.get("scan_frequency_days") or 7)

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


def derive_roundtrip_state(track, data_dir, store=None, scanning=False,
                           hourly_limit=fs.HOURLY_BROWSER_LIMIT,
                           stale_periods=2, period_days=None):
    """推導單純來回條件使用者看得到的狀態（比照 `derive_state()`）。"""
    if period_days is None:
        period_days = int(track.get("scan_frequency_days") or 7)

    pending = pending_roundtrip_combinations(track, data_dir)
    owns_store = store is None
    if owns_store:
        store = FlightStore(data_dir)
    try:
        has_results = store.count_roundtrip_results(track["id"]) > 0
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


def _roundtrip_notification_legs(track, lowest_row):
    """單純來回通知訊息用的航段（比照 `_notification_legs()`）。

    段數判斷邏輯跟 `expand_roundtrip_track()` 一致：未指定偏好轉機城市
    傳 2 段（`google_flights_url()` 自動編碼來回），指定時傳 4 段
    （自動編碼多城市）——兩處不能各寫一份，否則行為分岔。
    """
    hub = track.get("hub", "TPE")
    transit = track.get("preferred_transit")
    destination = lowest_row["destination"]
    outbound_date = lowest_row["outbound_date"]
    return_date = lowest_row["return_date"]
    if transit:
        return [
            {"departure_id": hub, "arrival_id": transit, "date": outbound_date},
            {"departure_id": transit, "arrival_id": destination,
             "date": outbound_date},
            {"departure_id": destination, "arrival_id": transit,
             "date": return_date},
            {"departure_id": transit, "arrival_id": hub, "date": return_date},
        ]
    return [
        {"departure_id": hub, "arrival_id": destination, "date": outbound_date},
        {"departure_id": destination, "arrival_id": hub, "date": return_date},
    ]


def _roundtrip_notification_trip_lines(lowest_row):
    """單純來回通知訊息共用的行程細節（比照
    `_notification_trip_lines()`）。**明確標示目的地**——這是跟四段票
    通知的關鍵差異：多目的地候選情境下不標示會讓 PO 不知道要看哪個
    行程（spec.md FR-10）。沒有接駁票概念，不需要那一行。
    """
    lines = [
        "目的地：%s" % lowest_row["destination"],
        "去程 %s ～ 回程 %s" % (lowest_row["outbound_date"],
                              lowest_row["return_date"]),
    ]
    airline_desc = fs.describe_airlines(
        (lowest_row.get("airline") or "").split("／"))
    if airline_desc:
        lines.append("航空 %s" % airline_desc)
    return lines


def build_roundtrip_notification(track, lowest_row):
    """組出單純來回的達標通知訊息（比照 `build_notification()`）。

    不含四段票專屬的「第1段不可 no-show」提醒——單純來回沒有這個風險
    （data-model.md「與既有機制的相容性」）。
    """
    legs = _roundtrip_notification_legs(track, lowest_row)
    lines = [
        "✈️ 機票降到目標價以下",
        "",
        "%s" % track["name"],
        "來回票 NT$%s（目標 NT$%s）" % (
            format(int(lowest_row["price"]), ","),
            format(int(track["target_price"]), ",")),
    ]
    lines += _roundtrip_notification_trip_lines(lowest_row)
    lines += ["", fs.google_flights_url(legs)]
    return "\n".join(lines)


def build_roundtrip_status_notification(track, lowest_row):
    """組出單純來回未達標時的現況通知（比照 `build_status_notification()`）。"""
    legs = _roundtrip_notification_legs(track, lowest_row)
    gap = int(lowest_row["price"]) - int(track["target_price"])
    lines = [
        "📊 本輪掃描完成（尚未達標）",
        "",
        "%s" % track["name"],
        "目前最低 NT$%s（目標 NT$%s，還差 NT$%s）" % (
            format(int(lowest_row["price"]), ","),
            format(int(track["target_price"]), ","),
            format(gap, ",")),
    ]
    lines += _roundtrip_notification_trip_lines(lowest_row)
    lines += ["", fs.google_flights_url(legs)]
    return "\n".join(lines)
