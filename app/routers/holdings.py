"""持股與自選清單路由：GET /api/holdings。

規劃文件第5節「逐一遷移既有功能」的第四項（見
docs/spec-intake/alphavibe/roadmap.md Q-046，第一項 MCP 連接器、第二項
選股篩選、第三項全市場批次篩選已完成，分別見 app/routers/mcp.py、
app/routers/screen.py、app/routers/market_scan.py）。從
poc/kb-mcp/report_server.py 的 `do_GET()` `path == "/dashboard/stocks"`
分支遷移過來，但**輸出格式改變**：原本是 `report.render_stock_list_page()`
產出的伺服器端渲染 HTML（篩選/搜尋/分頁皆用 GET query string 帶狀態、
無 JS），這裡改成 JSON（理由同前三個 router：規劃文件明確要求重寫成
FastAPI + React 前後端分離架構，HTML 渲染不該留在新架構）。

**參數**：沿用 `report_server.py` `do_GET()` 該分支既有支援的三個 query
string 參數，名稱與語意都不變（比照 market_scan.py 對 `framework` 的
取捨：只轉手介面，不新增/不改名）：
- `filter`（篩選 tab）：`all`／`holdings`／`research`，預設 `all`；帶到
  其他值時 fallback 到 `all`（照搬 `render_stock_list_page()` 開頭的
  正規化邏輯）。
- `q`（搜尋關鍵字）：比對股票代碼/名稱，或（長度 ≥3 時）透過
  `store.search_comments()` FTS5 全文檢索比對 PO 寫過的心得內容，命中
  心得的 `symbols` 欄位解析出代碼後併入。
- `page`（分頁頁碼）：從 1 開始，超出範圍會被夾在 `[1, total_pages]`
  之間（照搬既有夾值邏輯，不回傳 400）。

**刻意不搬的參數**：`flash`——那是 `/dashboard/stocks/add` 等 POST 表單
處理完後導回本頁時，用 query string 夾帶的一次性成功/失敗訊息（純 UX
文案，例如「⚠️ 股票代碼格式錯誤」），不屬於本任務範圍列出的「搜尋關鍵字、
篩選 tab、分頁參數」三者；且表單端點本身這一步不遷移（見任務範圍），
沒有 flash 訊息的產生來源，JSON API 也不需要對應這個純呈現用的一次性
提示欄位。

**這裡刻意不做的事**：
- 不改 `poc/kb-mcp/report.py`／`kb_store.py` 的任何一行，只 import 呼叫
  既有函式（比照 screen.py／market_scan.py 對 screener.py／frameworks.py
  的既有作法：sys.path.insert 後直接 import，篩選/排序/分頁演算法本身
  完全不重寫——見下方函式實作對 `report._tracked_stock_rows()` 與
  `report.STOCKLIST_PAGE_SIZE` 的重用）
- 不遷移 `/dashboard/stock/<code>`（個股詳情頁）、`/dashboard/stocks/add`
  （加入研究表單）、`/dashboard/watchlist` 等其他既有路由，留給之後的
  Step
- 不新增舊路由沒有的篩選能力（例如更多 filter 值、依價格/漲跌排序等）

**回傳格式選擇**：`results` 內每筆股票資料直接來自
`report._tracked_stock_rows()` 回傳的 dict（比照 screen.py／
market_scan.py「plain dict、不包 Pydantic model」的既有慣例），只拿掉
`spark_html` 一個欄位——那是給 HTML `<svg>` 用的已渲染字串（迷你走勢圖），
不是資料，JSON API 沒有等價欄位可轉手，故意省略並非漏欄位（詳見下方
函式 docstring「刻意省略」段）。其餘欄位（`code`／`name`／`is_holding`／
`price`／`delta_pct`／`has_concern`／`status_text`）原樣透傳。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

# app/routers/holdings.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 report.py 所在目錄。獨立做一次
# sys.path.insert（跟 app/deps.py、app/routers/screen.py、
# app/routers/market_scan.py 同一套 idempotent 寫法），讓這個檔案不依賴
# 其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import report  # noqa: E402  (需先插入 sys.path 才能 import)

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()

_VALID_FILTERS = ("all", "holdings", "research")


@router.get("/api/holdings")
def get_holdings_list(
    filter: str = Query(  # noqa: A002  (欄位名沿用舊路由的 `filter`)
        "all",
        description=(
            "篩選 tab，語意與驗證邏輯同 poc/kb-mcp/report_server.py 舊版 "
            "GET /dashboard/stocks 的 `filter` query string 參數：`all`／"
            "`holdings`／`research`，其他值 fallback 到 `all`。"
        ),
    ),
    q: str = Query(
        "",
        description=(
            "搜尋關鍵字，語意同舊版 `q` 參數：比對股票代碼/名稱，長度 ≥3 "
            "時另外比對 PO 寫過的心得內容（FTS5 全文檢索）。"
        ),
    ),
    page: int = Query(
        1,
        description="分頁頁碼，語意同舊版 `page` 參數，超出範圍會被夾在合法區間內。",
    ),
    store: KBStore = Depends(get_kb_store),
) -> Dict[str, Any]:
    """對外語意等同舊版 `GET /dashboard/stocks`：把庫存＋自選標的清單依
    `filter`／`q` 篩選、依 `page` 分頁後，回傳 JSON（原本是
    `report.render_stock_list_page()` 產出的 HTML 頁面）。

    篩選／搜尋／分頁三段邏輯直接照搬 `report.render_stock_list_page()`
    對應區塊（同樣的正規化規則、同樣的 `STOCKLIST_PAGE_SIZE`、同樣的
    FTS5 搜尋門檻與 symbols 解析正則），只是拿掉中間的 HTML 組字串，改成
    組 dict——這是「輸出格式轉換」，不是「重寫篩選/分頁邏輯」：實際判斷
    標的是否為庫存、股價/漲跌/需留意訊號怎麼算，全部由
    `report._tracked_stock_rows()` 內部呼叫既有的
    `store.get_holdings()`／`store.list_stances()`／`store.get_stock_prices()`／
    `store.get_module_d_results()` 得出，這裡完全不碰。

    刻意省略的欄位：`spark_html`（`_tracked_stock_rows()` 原始 dict裡的
    已渲染 SVG 走勢圖字串）——JSON API 沒有「渲染好的 HTML 片段」這種
    資料類型可對應，React 前端之後若要畫走勢圖，應該另外設計回傳原始
    價格序列的端點，不是這一步的範圍（比照 market_scan.py 明確排除
    POST /market-scan 觸發新掃描的取捨方式：安全/範圍限制下，寧可少做
    也不擅自擴大這一步的範圍）。

    回傳結構：
    - `filter`：正規化後實際套用的篩選 tab（可能跟輸入不同，例如帶了
      無效值會回 `"all"`）。
    - `query`：正規化（trim）後實際套用的搜尋關鍵字。
    - `page`：夾值後實際套用的頁碼。
    - `total_pages`：套用篩選＋搜尋後的總頁數（至少為 1）。
    - `total`：套用篩選＋搜尋後、分頁前的總筆數（對應舊版「顯示 X–Y /
      N 檔」裡的 N）。
    - `all_total`：完全不篩選時的總標的數（庫存∪自選去重後）。
    - `holdings_count`／`research_count`：對應清單頁三個 tab 各自的計數
      徽章（`全部 <all_total>`／`庫存中 <holdings_count>`／
      `研究中 <research_count>`）。
    - `results`：本頁（`STOCKLIST_PAGE_SIZE`＝10 筆一頁）股票清單，每筆
      含 `code`／`name`／`is_holding`／`price`／`delta_pct`／
      `has_concern`／`status_text`（欄位定義見
      `report._tracked_stock_rows()` docstring）。
    """
    filter_key = filter if filter in _VALID_FILTERS else "all"
    search_query = (q or "").strip()

    all_rows = report._tracked_stock_rows(store)  # noqa: SLF001  (刻意重用既有邏輯，見檔案 docstring)
    holdings_count = sum(1 for r in all_rows if r["is_holding"])
    research_count = len(all_rows) - holdings_count

    if filter_key == "holdings":
        rows = [r for r in all_rows if r["is_holding"]]
    elif filter_key == "research":
        rows = [r for r in all_rows if not r["is_holding"]]
    else:
        rows = all_rows

    if search_query:
        comment_hit_codes = set()
        if len(search_query) >= 3:
            hits = store.search_comments(search_query, limit=100).get("results") or []
            for h in hits:
                for part in re.split(r"[,，\s]+", h.get("symbols") or ""):
                    if part:
                        comment_hit_codes.add(part)
        rows = [r for r in rows
                if search_query in (r["code"] or "") or search_query in (r["name"] or "")
                or r["code"] in comment_hit_codes]

    total = len(rows)
    total_pages = max(1, (total + report.STOCKLIST_PAGE_SIZE - 1) // report.STOCKLIST_PAGE_SIZE)
    resolved_page = max(1, min(page or 1, total_pages))
    start = (resolved_page - 1) * report.STOCKLIST_PAGE_SIZE
    page_rows = rows[start:start + report.STOCKLIST_PAGE_SIZE]

    results: List[Dict[str, Any]] = [
        {k: v for k, v in r.items() if k != "spark_html"} for r in page_rows
    ]

    return {
        "filter": filter_key,
        "query": search_query,
        "page": resolved_page,
        "total_pages": total_pages,
        "total": total,
        "all_total": len(all_rows),
        "holdings_count": holdings_count,
        "research_count": research_count,
        "results": results,
    }
