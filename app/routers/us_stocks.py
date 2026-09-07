"""美股獨立投資系統：FastAPI router 骨架。

**這一步（Phase 1 Setup）只建立骨架**——實際的業務端點（持股清單、交易
列表、股價歷史、立場、監控條件 CRUD）留待 Phase 3-5（見
`specs/003-us-stocks/tasks.md` T016/T022/T028）逐一補上。這裡只放一個
`healthz` 端點，驗證 router 掛載與 `USStockStore` dependency wiring
本身沒問題。

**完全獨立於既有台股 router**：不 import `app/routers/dashboard.py`／
`screen.py`／`market_scan.py`／`holdings.py`／`stock_detail.py`／
`actions.py`／`holdings_import.py`／`assets.py` 等任何既有台股相關
router，也不 import `app/deps.py`（改用獨立的 `app/us_stock_deps.py`，
見該檔案 docstring）——對應 spec.md FR-015/016「完全獨立」要求。
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.us_stock_deps import USStockStore, get_us_stock_store

router = APIRouter()


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
