"""既有表單端點遷移（5/5，最後一項）：POST /api/holdings/preview、
POST /api/holdings/confirm——貼零股庫存表快速輸入，兩步驟預覽/確認。

規劃文件第5節「逐一遷移既有功能」清單裡「5 個表單端點」的最後一項（見
docs/spec-intake/alphavibe/roadmap.md Q-046：「watchlist／trade／
laoyutou／tradeledger／holdings-preview」——前四項見 app/routers/
actions.py，已完成）。這一項完成後，規劃文件第5節列出的既有功能遷移
清單全部完成。

**先確認過的事實：這是真正的兩步驟，不是靠參數切換的單一端點**（見
poc/kb-mcp/report_server.py `do_POST()`）：
- `POST /dashboard/holdings/preview`（第737行起）：只呼叫
  `holdings_parser.parse_holdings_report(text)` 解析＋`store.get_holdings()`
  讀上次快照＋`report.render_holdings_preview()` 組頁面，**完全沒有呼叫任何
  store 寫入方法**，是唯讀端點。
- `POST /dashboard/holdings/confirm`（第755行起）：從預覽頁隱藏欄位
  （`rows_json`，即 `report._carry_over_avg_cost()` 的輸出原樣序列化）
  還原解析結果，呼叫 `store.save_holdings(rows, source_ref=...)` 真的寫入
  `holdings` 表，是這兩步驟裡唯一的寫入點。

這裡照這個既有邊界掛兩個端點：`POST /api/holdings/preview`（唯讀）與
`POST /api/holdings/confirm`（寫入）。**沒有走「單一端點靠 confirm 參數
切換」的設計**，因為既有實作本來就是兩個獨立 handler、且 preview 回傳的
`rows`（已用 `_carry_over_avg_cost()` 補上沿用的 `avg_cost`）需要讓呼叫端
先看過、可能人工調整後再原樣送回 confirm——這正是 holdings_parser.py
docstring 講的「人工確認關卡，刻意保留，不可省略」，兩個端點的介面邊界
剛好對應這個關卡，比硬併成一個端點更貼近既有語意。

**save_holdings() 的寫入行為（很重要，決定前端以後怎麼呈現警告）**：
是**純新增（INSERT），不是覆蓋/刪除**——每次確認存入都是以「今天」為
`snapshot_date` 新插入一批 `holdings` 列，不會刪除或更新任何既有列（見
kb_store.py `save_holdings()` 沒有任何 `DELETE`/`UPDATE`，以及
report.py `render_holdings_preview()` 原文案「存入不會覆蓋歷史紀錄，
而是新增一筆最新快照」）。`store.get_holdings()`（不帶 code）只回傳
`snapshot_date` 最新的一批，所以「看起來像覆蓋」是查詢邏輯（只看最新
快照）造成的錯覺，不是寫入邏輯真的覆蓋——前端之後若要顯示「即將覆蓋」
警告，文案上應該澄清成「將新增一筆最新快照，舊快照仍保留在歷史紀錄」，
不是真的資料庫覆蓋，這點刻意在此記錄，避免以後被文案誤導去改寫入邏輯。

**直接重用、完全不重寫的既有函式**：
- `holdings_parser.parse_holdings_report(text)`：純解析，不碰 DB。
- `report._carry_over_avg_cost(rows, previous_holdings)`／
  `report._diff_holdings(enriched_rows, previous_holdings)`：私有函式但
  比照 `app/routers/holdings.py` 對 `report._tracked_stock_rows()` 的既有
  前例（`# noqa: SLF001`），直接重用，不複製邏輯進來自己重寫一份。
- `store.get_holdings()`／`store.save_holdings()`：既有 KBStore 方法。

**回應格式選擇**：比照 actions.py／holdings.py「plain dict、不包 Pydantic
model」的既有慣例。preview 回傳的 `rows` 就是 confirm 端點預期收到的
`rows` 格式（同一份 `_carry_over_avg_cost()` 輸出），呼叫端理論上可以
「preview 拿到什麼就原樣塞進 confirm」，也可以在送出前人工調整
（例如修正某筆 `avg_cost`）——這正是 HTML 版隱藏欄位表單在做的事，只是
介面換成 JSON。

**source_ref 文案調整**（比照 actions.py 同一段落的既有前例，唯一偏離
「一字不動搬過去」的地方）：舊路由 confirm 分支固定寫
「dashboard貼庫存帳單快速輸入」，這裡改用 actions.py 已定義的
`_SOURCE_REF = "app快速輸入"`，如實反映這筆資料改由新 FastAPI JSON API
寫入，不影響任何驗證/寫入邏輯或資料結構。

**錯誤回應設計**（比照 actions.py 三層框架）：
1. Pydantic 型別檢查（例如 `rows` 不是 list）→ 422，自動處理。
2. Handler 層本來就有、照原樣搬過來的必填檢查：`text` 去空白後為空字串
   （preview）、`rows` 為空清單（confirm）→ 400，沿用原本中文錯誤文案。
3. `save_holdings()` 內部丟出的 `ValueError`（例如某筆缺 `code`）→ catch
   後轉 400，錯誤文字直接沿用 exception message，不重新編一份。

**這裡刻意不做的事**：
- 不改 `poc/kb-mcp/holdings_parser.py`／`report.py`／`kb_store.py` 任何
  一行，只 import 呼叫既有函式。
- 不新增舊路由沒有的能力（例如自訂 `snapshot_date`、批次刪除舊快照）。
- 不開始寫 React 前端——這是最後一項後端遷移，不代表要開始做前端。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# app/routers/holdings_import.py 在 AlphaVibe/app/routers/ 底下，往上兩層
# 是 AlphaVibe/，再進 poc/kb-mcp/ 才是 holdings_parser.py／report.py 所在
# 目錄。獨立做一次 sys.path.insert（跟 app/deps.py、其餘 app/routers/*.py
# 同一套 idempotent 寫法），讓這個檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import holdings_parser  # noqa: E402  (需先插入 sys.path 才能 import)
import report  # noqa: E402

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()

# 比照 actions.py 既有前例：新路由統一用這個標籤取代舊版寫死的
# 「dashboard貼庫存帳單快速輸入」，理由見本檔開頭 docstring「source_ref
# 文案調整」一段。
_SOURCE_REF = "app快速輸入"


class HoldingsPreviewInput(BaseModel):
    """POST /api/holdings/preview 的 request body，欄位語意等同舊版
    `/dashboard/holdings/preview` 表單的 `text` 欄位（貼上的零股庫存表
    原始文字）。"""

    text: str = Field(..., description="貼上的零股庫存表原始文字，必填")


class HoldingsConfirmInput(BaseModel):
    """POST /api/holdings/confirm 的 request body，欄位語意等同舊版
    `/dashboard/holdings/confirm` 表單隱藏欄位 `rows_json` 解碼後的內容：
    `POST /api/holdings/preview` 回傳的 `rows`（可能經人工調整）原樣送回。

    刻意用 `List[Dict[str, Any]]`（不逐欄位定義 Pydantic model）：
    `save_holdings()` 本身才是驗證每筆資料是否合法（是否有 `code`）的
    地方，這裡不重複定義一份 schema 去卡在 `save_holdings()` 之前，
    避免兩邊驗證邏輯不同步（比照本檔開頭 docstring「不重寫既有驗證/寫入
    邏輯」的原則）。
    """

    rows: List[Dict[str, Any]] = Field(
        ..., description="要存入的持股清單，每筆至少要有 code；語意同舊版隱藏欄位 rows_json"
    )


@router.post("/api/holdings/preview")
def preview_holdings(
    payload: HoldingsPreviewInput, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/holdings/preview`：解析貼上的
    零股庫存表文字＋跟上次快照比對，**只回傳預覽結果，不寫入資料庫**
    （`holdings_parser.parse_holdings_report()`／`report._carry_over_avg_cost()`／
    `report._diff_holdings()` 皆為既有純函式或唯讀查詢，這裡完全不重寫）。

    `text` 去除前後空白後為空字串 → 400（照搬舊版 `do_POST()` 本來就在
    handler 層做的檢查）。文字本身格式無法解析（例如整段貼錯內容）不會
    回 400——比照舊版行為，解析失敗的行收進 `unparsed_lines`、`rows`
    可能為空清單，仍是 200，讓呼叫端自行判斷「沒有可存入的資料」。

    回傳結構：
    - `total_parsed`：成功解析出的資料列數（等於 `len(rows)`）。
    - `unparsed_lines`：看起來像資料列但解析失敗的原始行，未計入
      `rows`，需要人工核對原始帳單。
    - `rows`：解析結果，每筆已用 `_carry_over_avg_cost()` 補上「若上次
      快照同代碼有 avg_cost 則沿用」的欄位（`code`／`name`／`shares`／
      `avg_cost`／`is_emerging`）——**這就是之後要送進
      `POST /api/holdings/confirm` 的資料格式**，呼叫端可以直接原樣送回，
      也可以先讓使用者調整後再送。
    - `previous_snapshot_date`／`previous_count`：上次快照的日期與筆數
      （`previous_count == 0` 代表目前完全沒有庫存快照）。
    - `diff`：與上次快照比對結果，`{"added": [...], "removed": [...],
      "changed": [...]}`，語意同 `report._diff_holdings()` 回傳值
      （`removed` 只代表這次帳單沒印到該代碼，不代表已出清，見該函式
      docstring）。
    """
    text = payload.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="⚠️ 貼庫存帳單失敗：內容是空的")

    parsed = holdings_parser.parse_holdings_report(text)
    previous_holdings = store.get_holdings()
    enriched_rows = report._carry_over_avg_cost(  # noqa: SLF001  (刻意重用既有邏輯，見檔案 docstring)
        parsed.get("rows") or [], previous_holdings
    )
    diff = report._diff_holdings(enriched_rows, previous_holdings)  # noqa: SLF001

    return {
        "total_parsed": parsed.get("total_parsed", 0),
        "unparsed_lines": parsed.get("unparsed_lines") or [],
        "rows": enriched_rows,
        "previous_snapshot_date": previous_holdings.get("snapshot_date"),
        "previous_count": previous_holdings.get("count", 0),
        "diff": diff,
    }


@router.post("/api/holdings/confirm")
def confirm_holdings(
    payload: HoldingsConfirmInput, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/holdings/confirm`：把
    `POST /api/holdings/preview` 回傳（或人工調整過）的 `rows` 真的存入
    `holdings` 表（呼叫 `store.save_holdings()`，不重寫該方法的必填檢查
    ／寫入邏輯）。

    這是這一組路由**唯一涉及寫入的端點**。`save_holdings()` 是純新增
    （INSERT 新一批 `snapshot_date` 為今天的列），不會刪除或更新任何既有
    快照，細節見本檔開頭 docstring「save_holdings() 的寫入行為」一段。

    `rows` 為空清單 → 400（照搬舊版 `do_POST()` 本來就在 handler 層做的
    「沒有可存入的資料」檢查）。`rows` 非空但某筆缺 `code` →
    `save_holdings()` 內部會丟 `ValueError`，這裡 catch 起來轉成 400，
    錯誤文字直接沿用 exception message。

    成功回應直接是 `save_holdings()` 的原始回傳 dict：
    `{"saved": True, "count": int, "snapshot_date": str}`。
    """
    rows = payload.rows or []
    if not rows:
        raise HTTPException(
            status_code=400, detail="⚠️ 貼庫存帳單失敗：沒有可存入的資料，請回上一步重新貼上"
        )
    try:
        return store.save_holdings(rows, source_ref=_SOURCE_REF)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="⚠️ 貼庫存帳單失敗：%s" % exc) from exc
