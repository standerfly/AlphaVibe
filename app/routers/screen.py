"""選股篩選路由：GET /api/screen。

規劃文件第5節「逐一遷移既有功能」的第二項（見
docs/spec-intake/alphavibe/roadmap.md Q-046，第一項 MCP 連接器已完成，見
app/routers/mcp.py）。從 poc/kb-mcp/report_server.py 的 `do_POST()`
`path == "/screen"` 分支遷移過來，但**輸出格式改變**：原本是
`report.render_screen_results()` 產出的伺服器端渲染 HTML，這裡改成給
以後 React 前端用的 JSON（規劃文件明確要求「重寫成 FastAPI + React 輕量
前後端分離架構」，HTML 渲染本來就不該留在新架構裡）。

**輸入介面也跟著方法一起變**：poc/kb-mcp/report_server.py 原本用
`POST /screen`＋form-urlencoded body（欄位名 `codes`）；這裡照任務指示改
用 `GET /api/screen`，把同一個欄位語意搬成 query string 參數（同樣叫
`codes`——沿用既有欄位名稱，不發明新名字）。GET 對「篩選查詢、無副作用」
這種操作語意更貼切，也方便以後 React 前端直接組 URL 呼叫、瀏覽器分享/
書籤查詢結果。除了這個「表單欄位→query string」的介面轉換，**不新增任何
poc/kb-mcp/report_server.py 原本沒有的參數**（例如 peg_threshold／
drawdown_min 等 screener.screen_stocks() 雖然支援、但 report_server.py
這條路由從來沒有把它們暴露給使用者調整，維持同樣的範圍）。

**這裡刻意不做的事**：
- 不改 poc/kb-mcp/screener.py 的任何一行，只 import 呼叫
  screener.parse_codes()／screener.screen_stocks()（比照 app/routers/mcp.py
  對 mcp_http_gateway.py 的既有作法：sys.path.insert 後直接 import，
  篩選演算法本身完全不重寫）
- 不遷移 GET /screen（原本只是回傳空白表單 HTML，之後 React 前端會自己
  刻表單，不需要 API 對應這個 no-op 頁面）
- 不遷移 /screen 以外的其他既有路由（/market-scan、/dashboard/* 等留給
  之後的 Step）

**回傳格式選擇**：直接回傳 `screener.screen_stocks()` 的原始 dict（不包
Pydantic model）——比照 app/main.py 的 `/api/healthz`、`/api/whoami` 目前
就是回傳 plain dict 讓 FastAPI 自動序列化，這是這個 app/ 目錄目前唯一
建立起來的慣例；plain dict 也讓這裡誠實地「只轉手、不重新定義資料形狀」，
避免 Pydantic model 欄位定義跟 screener.py 實際回傳的 key 兜不齊而悄悄
漏欄位或加欄位（screen_stocks() 依輸入不同，回傳 dict 的 key 組合不完全
固定：見下方函式 docstring）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query

# app/routers/screen.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 screener.py 所在目錄。獨立做一次
# sys.path.insert（跟 app/deps.py、app/routers/mcp.py 同一套 idempotent
# 寫法），讓這個檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import screener  # noqa: E402  (需先插入 sys.path 才能 import)

from app.deps import _resolve_data_dir  # noqa: E402

router = APIRouter()


@router.get("/api/screen")
def get_screen(
    codes: str = Query(
        "",
        description=(
            "股票代碼，逗號（半形或全形）或換行分隔，語意等同 "
            "poc/kb-mcp/report_server.py 舊版 POST /screen 的 `codes` "
            "表單欄位；解析邏輯直接呼叫 screener.parse_codes()，行為不變。"
        ),
    ),
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /screen`：把 `codes` 解析成代碼清單後，直接
    呼叫 screener.screen_stocks() 取得篩選結果，原封不動回傳給呼叫端。

    回傳 dict 的 key 組合依 screen_stocks() 內部分支而不同（這裡不強加
    固定 schema，忠實反映既有函式的行為）：
    - `codes` 解析後為空清單（含缺參數／全空白）：
      `{"results": [], "total": 0}`
    - 超過 screener.MAX_CODES（50）檔：
      `{"results": [], "total": 0, "error": "一次最多篩選 ..."}`
    - 正常情況：`{"results": [...], "total": N, "thresholds": {...},
      "benchmark": {...}}`，其中 `results` 每筆包含 code／name／per／
      revenue_yoy／drawdown_pct／peg／meets_framework／error 等欄位，
      完整欄位定義見 screener.screen_stocks() docstring 與其內部組
      `row = {...}` 那段。

    刻意不比照 report_server.py 在「完全沒輸入代碼」時另外擋下來顯示
    「請至少輸入一個股票代碼」——那是 POST 表單頁面特有的 UX 提示文字，
    不是 screener.py 篩選邏輯本身的一部分（screen_stocks() 對空清單本來
    就有明確定義的回傳值，見上）。JSON API 對空輸入直接回傳
    screen_stocks() 的原始空結果，讓呼叫端（以後的 React 前端）自行決定
    要不要在 UI 層顯示等效提示。
    """
    code_list = screener.parse_codes(codes)
    return screener.screen_stocks(code_list, data_dir=_resolve_data_dir())
