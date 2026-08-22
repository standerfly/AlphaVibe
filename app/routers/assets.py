"""資產分頁資料層與 API：口袋／帳戶／餘額／建倉進度。

規劃文件第5節 Step 4 的後端部分（前端這一步不做，`/assets` 目前是
placeholder 頁面，見 app/main.py 的 SPA fallback；下一步才接前端）。
決策脈絡見 docs/spec-intake/alphavibe/roadmap.md Q-046，以及
docs/spec-intake/alphavibe/supporting-artifacts/2026-08-21-personal-console-expansion.md。

跟前面幾個 router 不同：這裡**不是遷移既有 report_server.py 路由**——
資產分頁是全新功能，`poc/kb-mcp/` 沒有對應的既有邏輯可以照搬，資料模型
與寫入邏輯本身就是這次任務的產出（定義在 `poc/kb-mcp/kb_store.py` 新增
的 5 張表與對應方法，這裡的 router 只負責 HTTP 介面轉接，不重複實作
驗證/寫入邏輯）。

**「刪除」一律是封存（`archived=1`），不是硬刪**——之前規劃已定案不做
硬刪，`GET .../pockets`／`GET .../accounts` 預設不列出已封存項目
（`include_archived` 目前不對外暴露成 query 參數：規格沒有要求「看已封存
清單」這個功能，之後真的需要再加）。

**錯誤回應設計**：
1. Request body 型別不對（例如 `amount` 不是數字）→ FastAPI/Pydantic
   自動回 422，比照 actions.py 既有慣例。
2. `kb_store.py` 對應方法丟出的 `ValueError`，這裡 catch 起來轉成
   HTTP 錯誤：訊息含「找不到」的（口袋/帳戶/計畫/月份查無資料，通常是
   URL path 參數指到不存在的資源）轉成 404；其餘（例如 `name` 為空字串）
   轉成 400。這個分類規則寫在 `_raise_from_value_error()`，不要在每支
   handler 各自判斷一次。

**建倉打勾/取消打勾**：直接呼叫 `store.complete_asset_buildup_month()`／
`store.undo_asset_buildup_month()`，這兩支方法內部已經把「更新 entry」與
「累加/扣回 asset_holdings 餘額」放在同一個 transaction，這裡不重複、也
不需要额外包一層 transaction。復原邏輯的設計取捨見這兩支方法的 docstring
（`poc/kb-mcp/kb_store.py`）。

**情境試算（`POST /api/assets/simulate`，第5節 Step 4 最後一塊後端工作，
2026-08-21 新增）**：跟上面幾組端點不同，這支**完全不碰資料庫**——純數學
運算，不需要 `store`、不需要 transaction，也不寫入任何表。公式來源見
`docs/spec-intake/alphavibe/roadmap.md` Q-046 與
`docs/spec-intake/alphavibe/supporting-artifacts/2026-08-21-personal-console-expansion.md`
「情境試算」一節，**明確標註「待驗證」**——年金公式尚未跟使用者原始素材
核對過精確版本（已知用範例反推有約 1~2% 誤差）。因此：

1. 公式本身照規劃文件指定的版本實作（一般年金/期末給付假設、月複利），
   不自行更動假設去湊任何特定數字。
2. 回應一律夾帶 `disclaimer` 欄位，誠實告知這個不確定性——不能省略，
   也不能等到「以後驗證過」才加，現在就要讓使用者知道這是暫定公式。
3. 邊界防呆（`SimulateRequest`）：本金／定期定額不可為負；年數必須 >0；
   報酬率允許 0 但不可小於 -1（-100%，避免 `(1+rate)` 變負數後對小數次方
   運算時出現數學定義域錯誤）。累積期月利率 `r_m`／提領期月利率 `r_w`
   為 0 時走線性特殊處理分支，避免除以零；`withdrawal_years` 換算月數後
   四捨五入為 0（例如填了小於半個月的極端值）也視為輸入錯誤擋下，理由
   相同——避免下一步公式除以零。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import KBStore, get_kb_store

router = APIRouter()


def _raise_from_value_error(exc: ValueError) -> None:
    """把 kb_store.py 方法丟出的 ValueError 轉成 HTTP 錯誤，見本檔開頭
    docstring「錯誤回應設計」第 2 點的分類規則。"""
    message = str(exc)
    status_code = 404 if "找不到" in message else 400
    raise HTTPException(status_code=status_code, detail=message) from exc


class PocketUpsert(BaseModel):
    """POST /api/assets/pockets 的 request body。`id` 帶值時更新該筆，
    不帶（或 None）時新增——語意對稱 `kb_store.save_asset_pocket()`。"""

    id: Optional[int] = Field(None, description="口袋 id，帶值＝更新，不帶＝新增")
    name: str = Field(..., description="口袋名稱，必填")
    target_amount: Optional[float] = Field(None, description="目標金額，選填")
    note: Optional[str] = Field(None, description="備註，選填")
    sort_order: Optional[int] = Field(0, description="排序序號，預設 0")


class AccountUpsert(BaseModel):
    """POST /api/assets/accounts 的 request body，語意對稱 `PocketUpsert`
    （帳戶沒有 `sort_order`，目前規格沒有要求帳戶可排序）。"""

    id: Optional[int] = Field(None, description="帳戶 id，帶值＝更新，不帶＝新增")
    name: str = Field(..., description="帳戶名稱，必填")
    category: Optional[str] = Field(None, description="分類，例如「銀行」「證券」，選填")
    note: Optional[str] = Field(None, description="備註，選填")


class HoldingUpsert(BaseModel):
    """POST /api/assets/holdings 的 request body：設定某口袋×帳戶的餘額
    為 `amount`（覆蓋，不是累加——累加只發生在建倉打勾的內部邏輯）。"""

    pocket_id: int = Field(..., description="口袋 id，必填")
    account_id: int = Field(..., description="帳戶 id，必填")
    amount: float = Field(..., description="餘額，必填（覆蓋既有值）")
    note: Optional[str] = Field(None, description="備註，選填")


class BuildupComplete(BaseModel):
    """POST /api/assets/buildup/{plan_id}/months/{month_number}/complete
    的 request body。"""

    actual_amount: float = Field(..., description="該月實際投入金額，必填")


class SimulateRequest(BaseModel):
    """POST /api/assets/simulate 的 request body：資產情境試算的 6 個輸入
    參數。邊界值理由見本檔開頭 docstring「情境試算」一節第 3 點。"""

    principal: float = Field(..., ge=0, description="起始本金，不可為負")
    monthly_contribution: float = Field(
        ..., ge=0, description="每月定期定額，不可為負"
    )
    years_to_retirement: float = Field(
        ..., gt=0, description="累積期年數，可為小數，必須 >0"
    )
    accumulation_rate: float = Field(
        ...,
        ge=-1,
        description="累積期年化報酬率，例如 0.08 代表 8%，不可小於 -1（-100%）",
    )
    withdrawal_rate: float = Field(
        ..., ge=-1, description="提領期年化報酬率，不可小於 -1（-100%）"
    )
    withdrawal_years: float = Field(
        ..., gt=0, description="提領期年數（累加到目標年齡歸零），必須 >0"
    )


# ---------- 口袋 ----------


@router.get("/api/assets/pockets")
def list_pockets(store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """列出未封存的口袋，每筆附 `current_amount`（該口袋底下所有帳戶餘額
    加總，見 `store.list_asset_pockets()`），前端可直接拿來算進度條，不用
    另外查一次 `/api/assets/holdings` 湊資料。"""
    return {"pockets": store.list_asset_pockets()}


@router.post("/api/assets/pockets")
def upsert_pocket(
    payload: PocketUpsert, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """新增或更新口袋（`payload.id` 決定新增/更新，見 `PocketUpsert`
    docstring）。`name` 去除前後空白後為空字串會被 `save_asset_pocket()`
    擋下轉成 400；帶不存在的 `id` 會被擋下轉成 404。"""
    try:
        return store.save_asset_pocket(
            id=payload.id,
            name=payload.name,
            target_amount=payload.target_amount,
            note=payload.note,
            sort_order=payload.sort_order or 0,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


@router.post("/api/assets/pockets/{id}/archive")
def archive_pocket(id: int, store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """封存口袋（不是刪除，見本檔開頭 docstring）。封存後資料仍在資料庫
    裡，只是 `GET /api/assets/pockets` 預設不列出。"""
    try:
        return store.archive_asset_pocket(id)
    except ValueError as exc:
        _raise_from_value_error(exc)


# ---------- 帳戶 ----------


@router.get("/api/assets/accounts")
def list_accounts(store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    return {"accounts": store.list_asset_accounts()}


@router.post("/api/assets/accounts")
def upsert_account(
    payload: AccountUpsert, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    try:
        return store.save_asset_account(
            id=payload.id,
            name=payload.name,
            category=payload.category,
            note=payload.note,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


@router.post("/api/assets/accounts/{id}/archive")
def archive_account(id: int, store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    try:
        return store.archive_asset_account(id)
    except ValueError as exc:
        _raise_from_value_error(exc)


# ---------- 餘額 ----------


@router.get("/api/assets/holdings")
def list_holdings(store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """列出所有餘額記錄，附口袋／帳戶名稱（見
    `store.list_asset_holdings()` 的 JOIN），前端不用另外查表湊名字。"""
    return {"holdings": store.list_asset_holdings()}


@router.post("/api/assets/holdings")
def upsert_holding(
    payload: HoldingUpsert, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """設定某口袋×帳戶的餘額（覆蓋既有值，見 `HoldingUpsert` docstring）。
    `pocket_id`／`account_id` 指到不存在的資源會被
    `store.upsert_asset_holding()` 擋下轉成 404。"""
    try:
        return store.upsert_asset_holding(
            pocket_id=payload.pocket_id,
            account_id=payload.account_id,
            amount=payload.amount,
            note=payload.note,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


# ---------- 建倉進度 ----------


@router.get("/api/assets/buildup/{plan_id}")
def get_buildup_plan(plan_id: int, store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """該建倉計畫詳情＋每月進度 entries。查無此計畫回 404（`store.
    get_asset_buildup_plan_with_entries()` 查無資料時回傳 None，這裡負責
    轉成 HTTP 語意，見 `_raise_from_value_error()` 同樣的 404 判斷邏輯，
    只是這裡不是 ValueError 而是直接檢查 None，故不透過該函式）。"""
    plan = store.get_asset_buildup_plan_with_entries(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="找不到建倉計畫 id=%s" % plan_id)
    return plan


@router.post("/api/assets/buildup/{plan_id}/months/{month_number}/complete")
def complete_buildup_month(
    plan_id: int,
    month_number: int,
    payload: BuildupComplete,
    store: KBStore = Depends(get_kb_store),
) -> Dict[str, Any]:
    """把該月標記完成，並把 `actual_amount` 累加進對應的
    asset_holdings 餘額（`store.complete_asset_buildup_month()` 內部同一
    個 transaction 完成兩件事，見該方法 docstring）。"""
    try:
        return store.complete_asset_buildup_month(
            plan_id=plan_id, month_number=month_number,
            actual_amount=payload.actual_amount,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


@router.post("/api/assets/buildup/{plan_id}/months/{month_number}/undo")
def undo_buildup_month(
    plan_id: int, month_number: int, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """取消打勾：把該月設回未完成，並把當初累加的金額精確扣回
    asset_holdings（`store.undo_asset_buildup_month()`，復原設計見該方法
    docstring）。該月本來就未完成時不算錯誤，回應裡 `undone: False`。"""
    try:
        return store.undo_asset_buildup_month(plan_id=plan_id, month_number=month_number)
    except ValueError as exc:
        _raise_from_value_error(exc)


# ---------- 情境試算 ----------

_SIMULATE_DISCLAIMER = (
    "此試算公式尚未跟你原始素材核對過精確版本，用範例反推目前有約1~2%誤差，"
    "僅供參考，正式依賴前請再次確認公式假設（本試算採一般年金/期末給付假設）"
)


def _simulate_asset_scenario(payload: SimulateRequest) -> Dict[str, Any]:
    """情境試算核心公式，純運算不碰資料庫。公式假設、來源與「待驗證」
    標註見本檔開頭 docstring「情境試算」一節——不要在這裡自行調整假設。

    累積期：一般年金/期末給付、月複利；`r_m == 0` 時走線性特殊處理，
    避免除以零。提領期：反推「m 個月後恰好歸零」的每月提領金額；
    `r_w == 0` 時同樣走線性特殊處理。`m <= 0`（`withdrawal_years` 換算
    月數後四捨五入為 0）在呼叫前就應該被擋下，這裡用 assert 當最後一道
    防線，不應該被觸發到。
    """
    accumulation_rate = payload.accumulation_rate
    withdrawal_rate = payload.withdrawal_rate

    r_m = (1 + accumulation_rate) ** (1 / 12) - 1
    n = round(payload.years_to_retirement * 12)
    fv_lump_sum = payload.principal * (1 + accumulation_rate) ** payload.years_to_retirement
    if r_m == 0:
        fv_annuity = payload.monthly_contribution * n
    else:
        fv_annuity = payload.monthly_contribution * (((1 + r_m) ** n - 1) / r_m)
    fv_total = fv_lump_sum + fv_annuity

    r_w = (1 + withdrawal_rate) ** (1 / 12) - 1
    m = round(payload.withdrawal_years * 12)
    assert m > 0, "呼叫前應已擋下 m<=0，見 simulate_scenario() 的檢查"
    if r_w == 0:
        monthly_withdrawal = fv_total / m
    else:
        monthly_withdrawal = fv_total * r_w / (1 - (1 + r_w) ** (-m))

    return {
        "fv_total": round(fv_total, 2),
        "monthly_withdrawal": round(monthly_withdrawal, 2),
        "inputs": payload.model_dump(),
        "disclaimer": _SIMULATE_DISCLAIMER,
    }


@router.post("/api/assets/simulate")
def simulate_scenario(payload: SimulateRequest) -> Dict[str, Any]:
    """資產情境試算：起始本金／定期定額／累積期年數與報酬率 → 退休時
    資產（`fv_total`）＋提領期每月可提領金額（`monthly_withdrawal`），
    伺服器端即時運算，**不進資料庫**（跟本檔其餘端點不同，沒有
    `Depends(get_kb_store)`）。公式與「待驗證」標註見本檔開頭 docstring
    「情境試算」一節與回應內的 `disclaimer` 欄位。

    `withdrawal_years` 換算月數後四捨五入為 0（極端小的值，例如小於
    半個月）在這裡擋下轉成 400，避免核心公式除以零；其餘邊界值已由
    `SimulateRequest` 的 Field 驗證擋在 422（型別/範圍不符）。
    """
    m = round(payload.withdrawal_years * 12)
    if m <= 0:
        raise HTTPException(
            status_code=400,
            detail="withdrawal_years 換算月數後四捨五入為 0，請提高數值（至少約 0.04 年／半個月以上）",
        )
    return _simulate_asset_scenario(payload)
