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


@router.get("/api/flights/healthz")
def healthz(store: FlightStore = Depends(get_flight_store)) -> Dict[str, Any]:
    """確認資料層可用與資料庫位置正確（測試與部署驗證用）。"""
    return {
        "ok": True,
        "db": store.db_path.split("/")[-1],
        "tracks": len(store.list_tracks()),
    }
