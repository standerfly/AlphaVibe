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
        lowest = dict(lowest, target_met=lowest["price"] <= track["target_price"])
    out = dict(track)
    out["state"] = state
    out["progress"] = {"done": len(itineraries) - len(pending),
                       "total": len(itineraries)}
    out["lowest"] = lowest
    out["skipped_count"] = len(skipped)
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": track["id"]}


@router.delete("/api/flights/tracks/{track_id}", status_code=204)
def delete_track(track_id: int,
                 store: FlightStore = Depends(get_flight_store)) -> None:
    """刪除條件與其結果。查價快取跨條件共用，不隨之刪除（contracts §3）。"""
    if not store.delete_track(track_id):
        raise HTTPException(status_code=404, detail="查詢條件不存在")
    _SCANNING.discard(track_id)
    _LAST_OUTCOME.pop(track_id, None)


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
    plan = svc.scan_plan(track, data_dir)

    if track_id in _SCANNING:
        return {"state": "scanning", "planned": plan["planned"],
                "done": plan["already_cached"],
                "message": "此條件已有掃描進行中"}

    if plan["pending"] == 0:
        return {"state": "complete", "planned": plan["planned"],
                "already_cached": plan["already_cached"], "will_query": 0}

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
    }


@router.get("/api/flights/healthz")
def healthz(store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """確認資料層可用與資料庫位置正確（測試與部署驗證用）。"""
    return {
        "ok": True,
        "db": store.db_path.split("/")[-1],
        "tracks": len(store.list_tracks()),
    }
