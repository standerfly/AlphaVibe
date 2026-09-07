"""美股獨立投資系統：FastAPI router。

Phase 3（US1，`specs/003-us-stocks/tasks.md` T016）新增交易紀錄匯入與
股價走勢對照所需的業務端點：持股清單、交易列表/最近匯入、股價歷史、
匯入核對確認寫入，以及 landing 頁彙整用的 watchlist。

Phase 4（US2，T022）新增個股「投資立場」查詢端點（`GET
/api/us-stocks/stance`）——寫入仍是 Claude 在對話中呼叫
`save_us_stance` MCP 工具完成（比照 T016 對 `us_trades` 的既有設計：
`parse_and_save_us_trade` 也是對話中直接寫入，網頁端不重複一套寫入
表單），這裡只負責讀取供個股詳情頁「投資立場」卡片（T024）顯示。

監控條件（`us_watch_conditions`）的 CRUD 端點留待 Phase 5（T028）。

**完全獨立於既有台股 router**：不 import `app/routers/dashboard.py`／
`screen.py`／`market_scan.py`／`holdings.py`／`stock_detail.py`／
`actions.py`／`holdings_import.py`／`assets.py` 等任何既有台股相關
router，也不 import `app/deps.py`（改用獨立的 `app/us_stock_deps.py`，
見該檔案 docstring）——對應 spec.md FR-015/016「完全獨立」要求。

**業務邏輯全部委派給 `USStockStore`**（`poc/kb-mcp/us_stock_store.py`）—
—跟既有台股 router（`stock_detail.py`／`holdings.py` 等）直接呼叫
`report.py`／`kb_store.py` 既有函式、不重寫演算法的慣例一致，這裡也不
重新實作任何持股彙總／股價缺口偵測邏輯，只做 HTTP 介面轉接。

**「STEP 2 匯入核對確認畫面」的資料流程設計取捨**（T017 對應）：
contracts/mcp-tools.md 工具一 `parse_and_save_us_trade` 是 Claude 在
對話中直接呼叫、直接寫入 `us_trades` 的工具（`text` 已由使用者於對話
中確認過）——`us_trades` schema（data-model.md，Phase 1/2 已凍結）沒有
「暫存待確認」的欄位或狀態機，所以這裡把「STEP 2 核對確認」實作為
「檢視＋修正剛剛已經寫入的紀錄」：`GET .../trades/recent` 列出最近
匯入的紀錄供網頁呈現，`POST .../trades/confirm` 對每一筆呼叫
`store.update_trade()` 套用使用者修正（欄位打錯、金額要人工調整等，
data-model.md 允許 `amount` 手動調整正是為此），不是重新從零寫入。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.us_stock_deps import USStockStore, get_us_stock_store

router = APIRouter()


def _latest_price_and_change(store: USStockStore, ticker: str):
    """取最近兩筆報價快照算現價與漲跌%（landing 頁 T019 用）。快照不足
    兩筆時 `price_change_pct` 為 `None`（無法算漲跌，不是 0%）。"""
    snapshots = store.list_price_snapshots(ticker, days=2)
    if not snapshots:
        return None, None
    latest = snapshots[-1]["close_price"]
    if len(snapshots) >= 2 and snapshots[-2]["close_price"]:
        prev = snapshots[-2]["close_price"]
        change_pct = ((latest - prev) / prev * 100
                      if latest is not None and prev else None)
    else:
        change_pct = None
    return latest, change_pct


@router.get("/api/us-stocks/healthz")
def healthz(store: USStockStore = Depends(get_us_stock_store)) -> Dict[str, Any]:
    """最小健康檢查端點，唯一目的是驗證：

    1. router 有正確掛載到 `app/main.py`
    2. `get_us_stock_store` dependency 真的能開到獨立的
       `poc/data/us_stocks.db`（回傳的 `db_path` 可用來對照，確認不是
       `alphavibe.db`）
    3. `USStockStore` 的 `get_tracked_tickers()` 在全新資料庫上不報錯、
       回傳空清單（間接確認 schema 建立成功、且沒有任何種子資料被意外
       寫入——見 `USStockStore.__init__` 的 2026-08-22 教訓）

    不是既有台股 `/api/healthz` 的重複——那支端點查的是 `KBStore`，這支
    查的是完全獨立的 `USStockStore`。
    """
    return {
        "status": "ok",
        "data_dir": store.data_dir,
        "db_path": store.db_path,
        "tracked_ticker_count": len(store.get_tracked_tickers()),
    }


@router.get("/api/us-stocks/watchlist")
def get_watchlist(store: USStockStore = Depends(get_us_stock_store)) -> Dict[str, Any]:
    """美股 landing 頁清單（T019）：目前「有交易」的股票各一筆，含持股
    彙總＋現價／漲跌。立場摘要／監控觸發狀態欄位留給 Phase 4/5（T030）
    補上，這裡刻意不假裝有這些資料（見 tasks.md T019 範圍註記）。

    刻意用「有交易的股票」而非 `get_tracked_tickers()` 四表聯集——Phase 3
    還沒有立場/監控條件功能，聯集在這個階段等於「有交易的股票」，直接用
    `compute_holdings()` 的清單語意更清楚，且不會在 Phase 4/5 加入
    純觀察標的後意外把「無持股」的列也混進這支持股導向的端點。
    """
    holdings = store.compute_holdings()["holdings"]
    rows = []
    for h in holdings:
        current_price, price_change_pct = _latest_price_and_change(store, h["ticker"])
        rows.append({
            "ticker": h["ticker"],
            "shares_held": h["shares_held"],
            "avg_cost": h["avg_cost"],
            "current_price": current_price,
            "price_change_pct": price_change_pct,
        })
    return {"watchlist": rows}


@router.get("/api/us-stocks/holdings")
def get_holdings(
    ticker: Optional[str] = Query(None, description="省略＝回傳全部曾有交易的股票"),
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """持股彙總（contracts 工具二 `get_us_holdings` 的 REST 版本，不透過
    MCP 協議，直接呼叫同一個 `USStockStore.compute_holdings()`）。"""
    return store.compute_holdings(ticker)


@router.get("/api/us-stocks/trades")
def get_trades(
    ticker: str = Query(..., description="交易流水查詢一次只查一檔（比照 contracts 工具三）"),
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """單一股票的原始交易列表，依日期排序——供個股詳情頁股價圖疊加
    買賣點位（T018）與交易流水清單使用。"""
    return {"ticker": ticker, "entries": store.list_trades(ticker)}


@router.get("/api/us-stocks/trades/recent")
def get_recent_trades(
    limit: int = Query(20, ge=1, le=200),
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """最近匯入的交易（依寫入順序，不分股票）——供匯入核對確認畫面
    （T017 STEP 2）顯示「Claude 剛剛在對話中解析寫入的紀錄」供使用者
    檢視/修正，見本檔案開頭 docstring「STEP 2」設計取捨說明。"""
    return {"trades": store.list_recent_trades(limit=limit)}


@router.get("/api/us-stocks/price-history")
def get_price_history(
    ticker: str = Query(...),
    days: int = Query(90, ge=1, le=3650),
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """股價走勢圖資料（contracts 工具八 `get_us_price_history` 的 REST
    版本），含資料缺口日期，供前端圖表判斷是否顯示斷點（T018）。"""
    return store.price_history_with_gaps(ticker, days)


@router.get("/api/us-stocks/stance")
def get_stance(
    ticker: str = Query(..., description="查詢單一股票的投資立場"),
    include_closed: bool = Query(
        False,
        description="true＝回傳全部歷史立場列表；省略/false＝只回傳最新一筆active立場",
    ),
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """個股「投資立場」查詢（contracts 工具五 `get_us_stance` 的 REST
    版本，T022）。預設回傳最新一筆 `status='active'` 立場（含完整
    `full_note`，不截斷——FR-009 要求呈現時不得因版面密度砍減內容；
    `include_closed=true` 回傳全部歷史立場列表，供未來需要回顧舊立場時
    使用，T024 目前的個股詳情頁只用預設模式）。

    兩種模式回傳形狀不同：預設模式回傳單一 `stance` 物件（或 `None`＝
    尚無立場紀錄）；`include_closed=true` 回傳 `stances` 陣列——呼叫端
    需依 `include_closed` 參數判斷要讀哪個 key，不是同一個 key 底下
    切換型別。
    """
    if include_closed:
        return {"ticker": ticker,
                "stances": store.list_stances(ticker, include_closed=True)}
    return {"ticker": ticker,
            "stance": store.get_latest_stance(ticker, include_closed=False)}


class ConfirmedTrade(BaseModel):
    """匯入核對確認畫面（T017）送出的單筆交易——`id` 對應
    `store.list_recent_trades()` 給出的既有紀錄，欄位為使用者確認/修正
    後的值。"""
    id: int
    ticker: str
    trade_date: str
    action: str
    shares: float = Field(gt=0)
    price: float = Field(gt=0)
    amount: Optional[float] = None


class ConfirmTradesRequest(BaseModel):
    trades: List[ConfirmedTrade]


@router.post("/api/us-stocks/trades/confirm")
def confirm_trades(
    body: ConfirmTradesRequest,
    store: USStockStore = Depends(get_us_stock_store),
) -> Dict[str, Any]:
    """匯入核對確認畫面（T017）「確認」按鈕呼叫的端點：對每一筆送來的
    交易呼叫 `store.update_trade()` 套用使用者的修正。單筆失敗（例如
    action 不合法）不中斷其餘筆——比照 `market_scan.py`／
    `us_stock_scan.py` 既有的「單一單位失敗不影響其餘」降級模式，逐筆
    回報結果，不是整批要嘛全過要嘛全部 400。

    找不到對應 `id` 的紀錄歸入 `errors`（`updated=None` 標記為
    "trade not found"），不拋 404——這是批次端點，單筆查無資料不該讓
    整批請求失敗。
    """
    updated: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for trade in body.trades:
        try:
            result = store.update_trade(
                trade.id, ticker=trade.ticker, trade_date=trade.trade_date,
                action=trade.action, shares=trade.shares, price=trade.price,
                amount=trade.amount,
            )
        except ValueError as exc:
            errors.append({"id": trade.id, "error": str(exc)})
            continue
        if result is None:
            errors.append({"id": trade.id, "error": "trade not found"})
            continue
        updated.append(result)
    return {"updated": updated, "errors": errors}
