"""AlphaVibe FastAPI 服務骨架 — 進入點。

「個人主控台擴建」重寫的第一步（規劃文件第5節 Step 1）：把
poc/kb-mcp/report_server.py（純 Python 標準庫）重寫成 FastAPI + React
輕量前後端分離架構，先求「能跑、能驗證身分」。第5節 Step 2 起開始逐一
遷移既有功能：MCP 連接器（/mcp、/mcp/{token}，見 app/routers/mcp.py）是
第一項，選股篩選（GET /api/screen，見 app/routers/screen.py）是第二項，
全市場批次篩選（GET /api/market-scan，見 app/routers/market_scan.py）是
第三項，持股與自選清單（GET /api/holdings，見 app/routers/holdings.py）是
第四項，個股詳情頁（GET /api/stocks/{code}，見 app/routers/stock_detail.py）
是第五項——原本是伺服器端渲染 HTML 的 GET /dashboard/stock/<code> 頁面。
第六項是規劃文件「5 個表單端點」裡的其中 4 個：加自選股、記交易、老芋頭
進出、交易明細表（POST /api/watchlist、/api/trades、/api/laoyutou-trades、
/api/trade-ledger，見 app/routers/actions.py）。第七項、也是「5 個表單
端點」的最後一項：貼零股庫存表快速輸入，兩步驟預覽/確認
（POST /api/holdings/preview、POST /api/holdings/confirm，見
app/routers/holdings_import.py）。

**修正（2026-08-21）**：上一段原本寫「至此規劃文件第5節列出的既有功能全部
遷移完成」——這句話是錯的。規劃文件的既有功能遷移清單把 `/`（儀表板
首頁）跟 `/dashboard/stocks`（持股清單）列為兩個分開項目，第四項只搬了
後者，`/` 本身（`report.render_dashboard()`，FR-058「今日重點」所在頁面）
當時完全沒有對應路由，直到要接前端才發現這個缺口。第八項補上它：
儀表板首頁（GET /api/dashboard，見 app/routers/dashboard.py）——只新做
「今日重點」「今日新候選」「策略設定」三個目前沒有其他端點涵蓋的區塊，
其餘區塊（觀察名單庫存總覽、純觀察標的、快速輸入）已被前面幾項既有
端點涵蓋，回應裡用 `see_also` 註記，不重複建置（判斷依據見
app/routers/dashboard.py 檔頭 docstring）。至此規劃文件第5節列出的既有
功能，加上這次發現的補漏項目，才是真正全部遷移完成。決策脈絡見
docs/spec-intake/alphavibe/roadmap.md Q-046，以及
docs/spec-intake/alphavibe/supporting-artifacts/2026-08-21-personal-console-expansion.md。

**這一步刻意不做的事**：
- 不遷移不在「5 個表單端點」清單內的其餘既有路由
  （/dashboard/stock/<code>/refresh、/note、/plan、/dashboard/stocks/add、
  /dashboard/tradecsv、/market-scan/track，理由見 actions.py docstring）
- 不動 poc/ 底下任何檔案；資料庫連線直接 import 既有 KBStore（見 deps.py）；
  選股篩選／批次篩選／個股詳情／表單寫入同樣直接 import 既有
  screener.py／frameworks.py／report.py／review_engine.py／
  trade_text_parser.py／trade_ledger_parser.py／holdings_parser.py，
  不重寫演算法或驗證/寫入邏輯（見 screen.py、market_scan.py、
  stock_detail.py、actions.py、holdings_import.py）
- 不影響正在跑的 poc/kb-mcp/report_server.py（launchd 常駐、ngrok 對外），
  也不觸發 com.alphavibe.marketscan 排程本來負責的「跑一次新掃描」動作

**第5節 Step 4（2026-08-21，本次新增）**：資產分頁（口袋／帳戶／餘額／
建倉進度）的資料層與 API，見 `app/routers/assets.py`——這是全新功能、
不是既有路由遷移，`poc/kb-mcp/kb_store.py` 新增 5 張表（`asset_pockets`／
`asset_accounts`／`asset_holdings`／`asset_buildup_plans`／
`asset_buildup_entries`）與對應方法承載資料層，`assets.py` 只負責 HTTP
介面轉接。前端這一步不做，`/assets` 仍是 placeholder 頁面。

**第5節 Step 3（2026-08-21）**：上面「不開始寫 React 前端」的
決定已被推翻——`web/` 目錄是新建的 Vite + React + React Router 前端骨架
（首頁／儀表板／個股詳情／資產 placeholder／相簿 MVP 空狀態四分頁），
`npm run build` 產出 `web/dist/`。這裡新增的靜態檔案服務（檔案最後段）
比照 `AI-stock-km-v1/main.py` 既有模式：`web/dist/` 存在時才掛載，
`/assets` 交給 `StaticFiles`，其餘未被上面任何 API 路由吃掉的路徑一律
回傳 `index.html`（讓 React Router 的 client-side routing 生效）。
**掛載順序是正確性的關鍵**：靜態服務區塊必須放在所有 `app.include_router`
與 `/api/*` 路由**之後**——FastAPI 依註冊順序比對路由，catch-all 的
`/{full_path:path}` 若先註冊會攔截所有請求；順序正確時，`/api/*`／`/mcp*`
這些明確路徑一定先被上面的路由比對命中，catch-all 只接住剩下的路徑。

啟動方式（在 AlphaVibe/.venv 內）：
    uvicorn app.main:app --port 8090
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.deps import DashboardAuthMiddleware, KBStore, get_kb_store
from app.routers import actions as actions_router
from app.routers import assets as assets_router
from app.routers import dashboard as dashboard_router
from app.routers import holdings as holdings_router
from app.routers import holdings_import as holdings_import_router
from app.routers import market_scan as market_scan_router
from app.routers import mcp as mcp_router
from app.routers import screen as screen_router
from app.routers import stock_detail as stock_detail_router

app = FastAPI(title="AlphaVibe App (skeleton)")
app.add_middleware(DashboardAuthMiddleware)
app.include_router(mcp_router.router)
app.include_router(screen_router.router)
app.include_router(market_scan_router.router)
app.include_router(holdings_router.router)
app.include_router(stock_detail_router.router)
app.include_router(actions_router.router)
app.include_router(holdings_import_router.router)
app.include_router(dashboard_router.router)
app.include_router(assets_router.router)


@app.get("/api/healthz")
def healthz() -> dict:
    """健康檢查，比照 poc/kb-mcp/report_server.py 的 /healthz 定位：
    不需要認證，給 uptime/monitoring 探測用（見 deps._AUTH_EXEMPT_PATHS）。
    """
    return {"status": "ok"}


@app.get("/api/whoami")
def whoami(store: KBStore = Depends(get_kb_store)) -> dict:
    """最小受保護端點，這一步唯一目的是驗證：

    1. DashboardAuthMiddleware 真的生效（未設定 token 時 fail-open放行；
       設定 token 後未帶認證會被擋、帶正確 Basic Auth 會放行）
    2. get_kb_store dependency 真的能開到跟 report_server.py 同一個
       alphavibe.db（回傳的 data_dir/db_path 可用來對照）

    不查詢任何業務資料表——遷移真正的業務路由是下一步的工作。
    """
    return {
        "authenticated": True,
        "data_dir": store.data_dir,
        "db_path": store.db_path,
    }


# ---------------------------------------------------------------------------
# React 前端靜態檔案（第5節 Step 3，2026-08-21）：必須放在檔案最後——
# 所有 app.include_router(...) 與上面兩個 /api/* 端點都已經註冊完畢，
# FastAPI 依註冊順序比對路由，catch-all 若先註冊會搶走全部請求。
# `web/dist/` 是 `npm run build` 的產出，不進版控（見 .gitignore），開發
# 環境沒 build 過時這個區塊整段跳過，不影響既有 API 端點的可用性。
# ---------------------------------------------------------------------------
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

if _WEB_DIST.exists():
    _WEB_ASSETS = _WEB_DIST / "assets"
    if _WEB_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(_WEB_ASSETS)), name="web_assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Client-side routing 的 fallback：任何不吻合上面 API 路由／
        /assets 靜態檔的路徑一律回傳 index.html，交給 React Router 在
        瀏覽器端決定要顯示哪個分頁（/、/dashboard、/dashboard/:code、
        /assets、/photos）。因為這個路由最後才註冊，/api/*、/mcp、/mcp/*
        這些已有明確 handler 的路徑不會落到這裡（FastAPI 先比對到就直接
        用那個 handler，不會再往下比對 catch-all）。
        """
        return FileResponse(str(_WEB_DIST / "index.html"))
