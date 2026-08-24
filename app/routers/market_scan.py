"""全市場批次篩選路由：GET /api/market-scan。

規劃文件第5節「逐一遷移既有功能」的第三項（見
docs/spec-intake/alphavibe/roadmap.md Q-046，第一項 MCP 連接器、第二項
選股篩選已完成，分別見 app/routers/mcp.py、app/routers/screen.py）。從
poc/kb-mcp/report_server.py 的 `do_GET()` `path == "/market-scan"` 分支
遷移過來，但**輸出格式改變**：原本是 `report.render_market_scan_page()`
產出的伺服器端渲染 HTML，這裡改成 JSON（理由同 app/routers/screen.py：
規劃文件明確要求重寫成 FastAPI + React 前後端分離，HTML 渲染不該留在
新架構）。

**只遷移 GET，刻意不遷移 POST /market-scan**：`report_server.py` 的
`do_GET()` 只是讀 `KBStore.get_latest_market_scan()` 存好的最近一次掃描
結果（純讀取，無副作用、不打外部 API）；`do_POST()` 則會呼叫
`market_scan.run_scan()` 現場對 TWSE/TPEx 打批次 API 重新計算，再用
`store.save_market_scan_run()` 寫入一筆新紀錄——這正是產生掃描結果的
**排程 `com.alphavibe.marketscan` 本來就在做的事**（每天 02:00 跑一次，
見 `report.render_market_scan_page()` 裡的固定說明文字）。這次任務的
安全限制明確要求不得碰、不得以任何方式影響這個排程 job，「觸發一次新
掃描」與排程做的是同一種計算，貿然遷移 POST 語意有跟排程重疊/衝突的
風險，所以這裡只做等同 GET 的「顯示最近一次已存結果」，不做等同 POST
的「觸發新掃描」。之後真的需要「手動觸發掃描」的 API，應該另開一個
獨立任務評估風險後再做，不是這一步的範圍。

**參數**：沿用 `report_server.py` `do_GET()` 唯一支援的 `framework` query
string 參數，語意與驗證邏輯照搬：未帶、或帶到 `frameworks.get_framework()`
查不到的代號，都 fallback 到 `frameworks.default_framework_id()`（對應
`report_server.py:385-387`）。`KBStore.get_latest_market_scan()` 本身
另外支援 `meets_only`／`limit`／`order_by` 三個可選參數，但舊版 HTML
路由的 `do_GET()` 從未把它們暴露給呼叫端（只有 `framework`）——這裡維持
同樣的範圍，不新增舊路由沒有的能力（跟 screen.py 對 `peg_threshold`／
`drawdown_min` 的取捨一致：那兩個參數 `screener.screen_stocks()` 也支援，
但舊路由沒暴露，所以新 API 也不暴露）。

**回傳格式**：直接回傳 `store.get_latest_market_scan()` 的原始 dict，
外加 `framework_id`（實際查詢用的框架代號——因為未帶/帶到無效值時會
fallback 到預設框架，呼叫端需要知道最後查的到底是哪一個框架的結果）。
比照 screen.py「plain dict、不包 Pydantic model」的既有慣例，同樣理由：
忠實反映 `get_latest_market_scan()` 的實際回傳形狀，不因為手動定義
schema 而悄悄漏欄位或加欄位。

回傳欄位對應 `report.render_market_scan_page()`／`_market_scan_row_html()`
渲染 HTML 表格時用到的資料（沒有遺漏任何欄位，只是格式從 HTML 表格換成
JSON）：

- `framework_id`：實際查詢的框架代號（可能是使用者帶的值，也可能是
  fallback 後的預設值）。
- `found`：是否已有掃描紀錄。`False` 時 `run` 為 `None`、`results` 為空
  陣列（對應 HTML「尚無掃描紀錄，可按上方『立即掃描』…」的提示文字，
  這裡不重複那段 UX 文案，由呼叫端自行決定怎麼顯示）。
- `run`：本次批次的中繼資料，只有 `found=True` 時存在，包含
  `id`／`framework_id`／`trigger_source`／`candidate_count`／
  `meets_count`／`twse_error`／`tpex_error`／`run_at`／`total_scanned`／
  `benchmark_drawdown_pct`／`benchmark_error`（欄位定義見
  `kb_store.py` 的 `market_scan_runs` 表 schema）。
- `results`：候選股票清單（`market_scan_results` 表每一列），每筆含
  `code`／`name`／`market`／`industry`／`per`／`revenue_yoy`／
  `revenue_period`／`drawdown_pct`／`high_price`／`high_date`／
  `current_price`／`current_date`／`peg`／`meets_framework`／`error`／
  `market_drawdown_pct`／`excess_drawdown_pct`／`pbr`／`dividend_yield`。
  對應 HTML「符合框架的候選」與「全部候選」兩個區塊的完整欄位聯集——
  這裡不重複拆成兩份清單（那只是 HTML 版面上「預設展開／預設收合」的
  呈現選擇），呼叫端可用 `meets_framework` 欄位自行分組，避免同一筆
  資料在 JSON 裡出現兩次。
- `total_results`／`returned`：只有 `found=True` 時存在，分別是篩選後
  （這裡不篩，即 `meets_only=False` 的預設值）總筆數與實際回傳筆數；
  此路由不帶 `limit`，兩者理論上必定相等，但照 `get_latest_market_scan()`
  原始 dict 型態原樣透傳，不擅自砍欄位。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

# app/routers/market_scan.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 frameworks.py 所在目錄。獨立做一次
# sys.path.insert（跟 app/deps.py、app/routers/screen.py 同一套 idempotent
# 寫法），讓這個檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import frameworks  # noqa: E402  (需先插入 sys.path 才能 import)

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()


@router.get("/api/market-scan")
def get_market_scan(
    framework: Optional[str] = Query(
        None,
        description=(
            "框架代號，語意與驗證邏輯同 poc/kb-mcp/report_server.py 舊版 "
            "GET /market-scan 的 `framework` query string 參數：未帶、或"
            "帶到不存在的代號，都會 fallback 到 "
            "frameworks.default_framework_id()（目前是 "
            "peg_deep_dip_concentration）。"
        ),
    ),
    store: KBStore = Depends(get_kb_store),
) -> Dict[str, Any]:
    """對外語意等同舊版 `GET /market-scan`：解析＋驗證 `framework` 參數後，
    呼叫 `store.get_latest_market_scan()` 取得最近一次批次掃描結果，原封
    不動回傳給呼叫端（外加 `framework_id` 標明實際查詢的框架，見本檔案
    開頭 docstring 的欄位說明）。

    注意：這裡**不會**觸發新的掃描計算，純粹讀取 `market_scan_runs`／
    `market_scan_results` 兩張表既有的資料——與 `com.alphavibe.marketscan`
    排程各自獨立、互不影響。
    """
    framework_id = framework
    if not framework_id or frameworks.get_framework(framework_id) is None:
        framework_id = frameworks.default_framework_id()
    result = store.get_latest_market_scan(framework_id=framework_id)
    return {"framework_id": framework_id, **result}
