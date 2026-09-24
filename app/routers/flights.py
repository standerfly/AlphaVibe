"""機票掃描分頁的 HTTP 層。

對應規格：`specs/005-flight-scan-page/`（spec.md FR-001~FR-026、
contracts/flights-api.md）。

**不含任何查價或枚舉邏輯**——那些在 `poc/kb-mcp/flight_search.py`
（已完成、112 測試）與 `poc/kb-mcp/flight_scan_service.py`。本檔案只做
HTTP 的事：驗證輸入、呼叫服務層、組裝回應。

## 兩個與一般 CRUD router 不同的地方

1. **配額不足與被外部服務阻擋不是 HTTP 錯誤**，而是 200 回應中的狀態值
   （contracts「錯誤語意」）。它們是預期的營運狀態，不是系統故障——
   前端要顯示「約 N 分鐘後接續」，而不是紅色錯誤。
2. **背景任務不使用 `Depends(get_flight_store)`**——background task 在
   response 送出後才執行，該連線可能已被 `finally` 關閉。改用
   `resolve_flight_data_dir_for_background()` 自行開關連線，這是
   `app/routers/photos.py` 已踩過並記錄的坑。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.flight_deps import (FlightStore, get_flight_store,
                             resolve_flight_data_dir_for_background)

# 服務層與查價層：sys.path 已由 app/flight_deps.py 插入 poc/kb-mcp
import flight_scan_service as svc  # noqa: E402
import flight_search as fs  # noqa: E402

router = APIRouter()


class ExcludeMonths(BaseModel):
    """主行程／第1段／第4段各自一組排除月份（FR-009）。

    1–12 任意複選、可不連續。**不提供任何季節快捷**——南半球目的地的
    旺季與北半球相反，寫死季節定義會讓南半球航線判斷錯誤（CON-12）。
    """
    trip: List[int] = Field(default_factory=list)
    lead: List[int] = Field(default_factory=list)
    trail: List[int] = Field(default_factory=list)


class TrackCreate(BaseModel):
    destination: str
    outstations: List[str]
    window_start: str
    window_end: str
    trip_days: int
    hub: str = "TPE"
    name: Optional[str] = None
    lead_strategy: str = "none"
    trail_strategy: str = "none"
    exclude_months: ExcludeMonths = Field(default_factory=ExcludeMonths)
    target_price: Optional[int] = None
    samples_per_month: int = 2
    scan_frequency_days: int = 7


# 目前有背景掃描在執行的 track id。
#
# 這是**暫態**而非進度：服務重啟後清空是正確的——重啟後確實沒有任何背景
# 任務在跑。真正需要跨重啟存活的「哪些組合已完成」由查價快取持久化，
# 不在這裡（research.md §2）。
_SCANNING: set = set()

# 上一輪掃描的結果摘要（是否被擋、哪一種）。
#
# 與 `_SCANNING` 同性質的**暫態**——服務重啟後清空是可接受的：重啟後
# 「上一輪掃描」已無上下文，而真正重要的兩件事都還在（已完成的組合在
# 查價快取、配額在 usage 檔）。這不是進度，不需要持久化。
_LAST_OUTCOME: Dict[int, Dict[str, Any]] = {}


def _quota_block(data_dir: str) -> Dict[str, Any]:
    """配額資訊。`limit_basis` 讓前端不必硬編文案即可正確標示該限制值的
    性質——FR-018／CON-09 要求顯示的限制數字必須標明是實測或推估。"""
    used = fs.read_browser_usage(data_dir)["count"]
    return {
        "used": used,
        "limit": fs.HOURLY_BROWSER_LIMIT,
        "window": "rolling_hour",
        "limit_basis": "estimated",
        "seconds_until_free": fs.seconds_until_quota_frees(data_dir),
    }


def _track_summary(store: FlightStore, track: Dict[str, Any],
                   data_dir: str) -> Dict[str, Any]:
    itineraries, skipped = svc.expand_track(track)
    pending = [i for i in itineraries
               if not svc._is_cached(i, data_dir)]
    state = svc.derive_state(track, data_dir, store=store,
                             scanning=track["id"] in _SCANNING)
    lowest = store.lowest_result(track["id"])
    if lowest and track.get("target_price") is not None:
        target_met = lowest["price"] <= track["target_price"]
        lowest = dict(lowest, target_met=target_met)
        if not target_met:
            # 未達標時附上差距，前端不用自己算（PO 2026-09-24 新增：
            # 「若沒有達成，找最接近的組合」——現有的「最低價」本身就是
            # 最接近的組合，只是原本沒標示差多少）
            lowest["gap_to_target"] = lowest["price"] - track["target_price"]
    out = dict(track)
    out["state"] = state
    out["progress"] = {"done": len(itineraries) - len(pending),
                       "total": len(itineraries)}
    out["lowest"] = lowest
    out["skipped_count"] = len(skipped)
    # 排程資訊（006 FR-004）：下次掃描日由服務層**單一來源**推算，
    # 前端不自行計算——規則（id%7 決定星期幾＋週期）只定義在
    # `svc.next_scan_date()` 一處
    out["next_scan_date"] = svc.next_scan_date(track)
    return out


@router.get("/api/flights/tracks")
def list_tracks(store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """條件清單，含推導狀態、進度、最低價摘要與配額（contracts §1）。"""
    data_dir = store.data_dir
    return {
        "tracks": [_track_summary(store, t, data_dir)
                   for t in store.list_tracks()],
        "quota": _quota_block(data_dir),
    }


@router.post("/api/flights/tracks", status_code=201)
def create_track(body: TrackCreate,
                 store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """建立條件。**不自動開始掃描**——讓使用者先確認條件正確（contracts §2）。

    驗證失敗回 400 並說明原因（FR-025）。驗證規則定義在 FlightStore，
    不在這裡重寫一份，避免兩處分岔。
    """
    try:
        track = store.create_track(
            destination=body.destination, outstations=body.outstations,
            window_start=body.window_start, window_end=body.window_end,
            trip_days=body.trip_days, hub=body.hub, name=body.name,
            lead_strategy=body.lead_strategy,
            trail_strategy=body.trail_strategy,
            exclude_months_trip=body.exclude_months.trip,
            exclude_months_lead=body.exclude_months.lead,
            exclude_months_trail=body.exclude_months.trail,
            target_price=body.target_price,
            samples_per_month=body.samples_per_month,
            scan_frequency_days=body.scan_frequency_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": track["id"]}


class TrackUpdate(BaseModel):
    """只開放頻率與目標價——兩者都只是「怎麼判斷/怎麼排程」的參數，
    不影響已枚舉的查詢組合。

    `trip_days`、`window_start/end`、排除月份、外站清單這些欄位不開放
    PATCH：改了枚舉出的組合就整組不同，既有結果會變成孤兒列。要改那些，
    語意上是「建新條件」而非「編輯」。

    兩個欄位都選填，但至少要有一個——空的 PATCH request 沒有意義，
    寧可在這裡明確拒絕，不要讓它悄悄變成 no-op。
    """
    scan_frequency_days: Optional[int] = None
    target_price: Optional[int] = None
    clear_target_price: bool = False
    """PATCH 語意下無法區分「沒填 target_price」跟「故意清空」——兩者
    在 JSON 裡都可能是欄位缺席或 null。用這個旗標明確表達「清空」意圖，
    避免使用者想取消目標價時被誤判成「沒有要改」而忽略。"""


@router.patch("/api/flights/tracks/{track_id}")
def update_track(track_id: int, body: TrackUpdate,
                 store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """調整重掃頻率（FR-005）與／或目標價。回傳更新後的摘要，前端不必
    再打一次清單。"""
    if (body.scan_frequency_days is None and body.target_price is None
            and not body.clear_target_price):
        raise HTTPException(status_code=400,
                            detail="至少要提供 scan_frequency_days 或 target_price")
    try:
        track = None
        if body.scan_frequency_days is not None:
            track = store.update_track_frequency(track_id,
                                                  body.scan_frequency_days)
            if track is None:
                raise HTTPException(status_code=404, detail="查詢條件不存在")
        if body.target_price is not None or body.clear_target_price:
            new_price = None if body.clear_target_price else body.target_price
            track = store.update_target_price(track_id, new_price)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if track is None:
        raise HTTPException(status_code=404, detail="查詢條件不存在")
    return _track_summary(store, track, store.data_dir)


@router.delete("/api/flights/tracks/{track_id}", status_code=204)
def delete_track(track_id: int,
                 store: FlightStore = Depends(get_flight_store)) -> None:
    """刪除條件與其結果。查價快取跨條件共用，不隨之刪除（contracts §3）。"""
    if not store.delete_track(track_id):
        raise HTTPException(status_code=404, detail="查詢條件不存在")
    _SCANNING.discard(track_id)
    _LAST_OUTCOME.pop(track_id, None)


def _connector_background(track_id: int, data_dir: str) -> None:
    """只補接駁估價的背景任務（四段票已全部命中快取時走這條）。

    與 `_run_scan_background` 一樣自行建立與關閉連線，不用 request-scoped
    的依賴。
    """
    from flight_store import FlightStore as _FS
    store = _FS(data_dir)
    try:
        track = store.get_track(track_id)
        if track:
            svc.ensure_connector_prices(track_id, track, data_dir, store)
    finally:
        store.close()
        _SCANNING.discard(track_id)


def _run_scan_background(track_id: int, data_dir: str) -> None:
    """背景任務入口。

    **自行建立與關閉連線**——不使用 request-scoped 的
    `Depends(get_flight_store)`，那個連線在 response 送出後可能已被
    `finally` 關閉（app/routers/photos.py 記錄的坑）。
    """
    try:
        outcome = svc.run_scan(track_id, data_dir) or {}
        _LAST_OUTCOME[track_id] = {
            "blocked": bool(outcome.get("blocked")),
            "blocked_kind": ("soft_timeout" if outcome.get("soft_blocked")
                             else ("explicit" if outcome.get("blocked")
                                   else None)),
            "queried": outcome.get("queried", 0),
            "written": outcome.get("written", 0),
        }
    finally:
        _SCANNING.discard(track_id)


@router.post("/api/flights/tracks/{track_id}/scan")
def trigger_scan(track_id: int, background_tasks: BackgroundTasks,
                 store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """觸發掃描（非同步）。

    **配額不足不是錯誤**：回 200 並附排隊資訊，因為那是預期的營運狀態
    而非系統故障（contracts「錯誤語意」）。重複觸發不建立第二個作業。
    """
    track = store.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="查詢條件不存在")

    data_dir = store.data_dir

    # 先同步補上「已在查價快取、但結果表還沒有」的組合。
    #
    # 必須在這裡做而不是只放在 run_scan 裡：當所有組合都已在快取時
    # （例如別的條件或 CLI 先查過），下面的 pending==0 分支會直接回
    # complete 而不啟動背景任務，run_scan 根本不會執行。2026-09-23 真實
    # 驗證踩到：觸發回 complete 但結果空白。這一步只讀快取寫資料庫，
    # 不連外部服務，同步執行即可。
    synced = svc.sync_cached_results(track_id, track, data_dir, store)

    plan = svc.scan_plan(track, data_dir)

    if track_id in _SCANNING:
        return {"state": "scanning", "planned": plan["planned"],
                "done": plan["already_cached"],
                "message": "此條件已有掃描進行中"}

    if plan["pending"] == 0:
        store.mark_success(track_id)
        # 四段票都已有結果，但接駁價可能還缺——那需要實際查詢，放背景做
        needs_connector = any(r.get("connector_price") is None
                              for r in store.list_results(track_id))
        if needs_connector:
            _SCANNING.add(track_id)
            background_tasks.add_task(_connector_background, track_id, data_dir)
        return {"state": "scanning" if needs_connector else "complete",
                "planned": plan["planned"],
                "already_cached": plan["already_cached"], "will_query": 0,
                "from_cache": synced}

    if plan["will_query"] == 0:
        wait = plan["seconds_until_free"]
        return {
            "state": "queued", "planned": plan["planned"],
            "already_cached": plan["already_cached"], "will_query": 0,
            "seconds_until_free": wait,
            "message": "最近一小時已達查詢上限，約 %d 分鐘後釋出名額"
                       % ((wait + 59) // 60),
        }

    _SCANNING.add(track_id)
    background_tasks.add_task(_run_scan_background, track_id, data_dir)
    return {"state": "scanning", "planned": plan["planned"],
            "already_cached": plan["already_cached"],
            "will_query": plan["will_query"]}


@router.get("/api/flights/tracks/{track_id}/results")
def get_results(track_id: int,
                store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """結果與進度（contracts §5）。結果排序由資料層完成，不在此重排。"""
    track = store.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="查詢條件不存在")

    data_dir = store.data_dir
    itineraries, skipped = svc.expand_track(track)
    pending = [i for i in itineraries if not svc._is_cached(i, data_dir)]
    results = store.list_results(track_id)
    for r in results:
        r["connector_is_estimate"] = True
        # 連結由後端用既有的 google_flights_url() 構造——前端若自行拼接
        # 就會有第二份網址編碼邏輯，兩處必然分岔（tfs 是 base64 protobuf，
        # 不是可目視檢查的格式）
        legs = [
            {"departure_id": r["outstation"], "arrival_id": track["hub"],
             "date": r["leg1_date"]},
            {"departure_id": track["hub"], "arrival_id": track["destination"],
             "date": r["outbound_date"]},
            {"departure_id": track["destination"], "arrival_id": track["hub"],
             "date": r["return_date"]},
            {"departure_id": track["hub"], "arrival_id": r["outstation"],
             "date": r["leg4_date"]},
        ]
        r["links"] = {
            "four_segment": fs.google_flights_url(legs),
            # 接駁票：台北→外站的單程，排在第1段出發日之前
            "connector": fs.google_flights_url([{
                "departure_id": track["hub"], "arrival_id": r["outstation"],
                "date": r["leg1_date"]}]),
        }

    last = _LAST_OUTCOME.get(track_id) or {}
    return {
        "state": svc.derive_state(track, data_dir, store=store,
                                  scanning=track_id in _SCANNING),
        "progress": {"done": len(itineraries) - len(pending),
                     "total": len(itineraries)},
        "quota": _quota_block(data_dir),
        # 區分「連續逾時的軟阻擋」與「明確阻擋頁」——兩者對使用者的建議
        # 不同：前者等一段時間即可，後者要放慢節流（FR-016）
        "blocked": bool(last.get("blocked")),
        "blocked_kind": last.get("blocked_kind"),
        "results": results,
        "skipped": skipped,
        # 通知狀態（FR-019）：上次通知的時間與價格，以及是否送達失敗。
        # 送達失敗要讓使用者看得到——否則他會以為「沒通知＝沒達標」，
        # 實際上是通知管道壞了
        "notify": track.get("notify"),
        "next_scan_date": svc.next_scan_date(track),
    }


@router.get("/api/flights/native-tracking")
def native_tracking(store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """外部服務原生價格追蹤的可用性與操作說明（FR-022）。

    `supported_for_four_segment` 是結構化欄位而非純文案——讓前端能以
    一致方式呈現這項限制，不必解析說明文字。

    2026-09-23 實測：四段票頁面找不到任何追蹤開關，而對照組（來回票）
    有；兩者皆在未登入狀態下測試，故非登入問題。網路文章聲稱該功能已
    延伸至多城市，實測不成立。
    """
    tracks = store.list_tracks()
    links = []
    seen = set()
    for t in tracks:
        low = store.lowest_result(t["id"])
        if not low:
            continue
        key = (t["hub"], t["destination"], low["outbound_date"],
               low["return_date"])
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "label": "%s↔%s %s～%s" % (t["hub"], t["destination"],
                                       low["outbound_date"], low["return_date"]),
            "url": fs.google_flights_url([
                {"departure_id": t["hub"], "arrival_id": t["destination"],
                 "date": low["outbound_date"]},
                {"departure_id": t["destination"], "arrival_id": t["hub"],
                 "date": low["return_date"]},
            ]),
        })
    return {
        "supported_for_four_segment": False,
        "reason": "外部服務的價格追蹤不支援多城市行程——四段票頁面沒有追蹤"
                  "按鈕，而同樣未登入的來回票頁面有（2026-09-23 對照實測）。",
        "usable_for": "主行程來回票（可作為四段票價格的代理指標：主行程"
                      "落在旺季時整張四段票都會被拉高）",
        "steps": [
            "登入外部服務帳號（追蹤結果會寄到該帳號的信箱）",
            "開啟下方的主行程來回票連結（不是四段票連結）",
            "在頁面上開啟「追蹤價格」開關，或執行提供的 console 腳本",
        ],
        "main_trip_links": links,
        "script_path": "poc/kb-mcp/scraper/track-prices-console.js",
        "bookmarklet_path": "poc/kb-mcp/scraper/track-prices-bookmarklet.txt",
    }


@router.get("/api/flights/healthz")
def healthz(store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """確認資料層可用與資料庫位置正確（測試與部署驗證用）。"""
    return {
        "ok": True,
        "db": store.db_path.split("/")[-1],
        "tracks": len(store.list_tracks()),
    }
