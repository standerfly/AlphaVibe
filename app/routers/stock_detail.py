"""個股詳情頁路由：GET /api/stocks/{code}。

規劃文件第5節「逐一遷移既有功能」的第五項（見
docs/spec-intake/alphavibe/roadmap.md Q-046，第一項 MCP 連接器、第二項
選股篩選、第三項全市場批次篩選、第四項持股/自選清單皆已完成，分別見
app/routers/mcp.py、app/routers/screen.py、app/routers/market_scan.py、
app/routers/holdings.py）。從 poc/kb-mcp/report_server.py 的 `do_GET()`
`path.startswith("/dashboard/stock/")` 分支遷移過來（GET 讀取端；
`/dashboard/stock/<code>/refresh`、`/note`、`/plan` 等 POST 表單端點刻意
不遷移，理由同下）。**輸出格式改變**：原本是
`report.render_stock_detail_page()` 產出的伺服器端渲染 HTML，這裡改成
JSON（理由同前四個 router：規劃文件明確要求重寫成 FastAPI + React 前後端
分離架構，HTML 渲染不該留在新架構）。

**這是目前所有既有路由裡資料整合度最高的一頁**——舊版單一 HTML 函式背後
呼叫了十幾個獨立的資料/計算函式（估值快照、模組D檢視結果、集中度／部位
控制建議、加碼計畫、持股與交易流水、心得留言…）。這裡的作法比照
holdings.py 對 `report._tracked_stock_rows()` 的既有慣例：**直接呼叫這些
既有的「資料函式」（`store.get_*()`／`review_engine.position_control_
suggestion()`／`report._latest_module_d_batch()` 等 report.py 內部但非
HTML 渲染的私有函式），在這支路由裡把多次呼叫的結果合併成一個 JSON dict，
完全不重寫任何一段整合/判斷邏輯**（見下方各欄位來源對照）。

**唯一例外——`verdict_html`**：Verdict banner（今天該不該動的結論，
`report._verdict_banner_html()`）的「tone/title 判斷」（Gate concern >
集中度超標 > 集中度算不出來 > 全過 > 尚無資料，五級優先序）是直接寫在
該 HTML 渲染函式內部的分支邏輯，**没有**一個獨立的「只回傳資料不回傳
HTML」版本可以重用；`_concentration_card_html()`／`_module_d_card_html()`
等其餘卡片則都是「先呼叫資料函式、再排版成 HTML」兩段式寫法，資料段可以
單獨重用。硬要在這支路由裡重新刻一份「tone 怎麼判斷」的 if/elif，等於
重寫這頁最關鍵的一段整合判斷邏輯（且未來 `_verdict_banner_html()` 改了
判準，這裡會悄悄跟著漂移出不同答案）——所以這裡直接呼叫該函式、把渲染好
的 HTML 片段原樣放進 `verdict_html` 欄位（跟 holdings.py 拿掉
`spark_html`「沒有 JSON 等價欄位就整個省略」的取捨相反：這裡是「沒有
JSON 等價欄位，但寧可帶原始 HTML 保證跟舊頁一字不差，也不要重新發明一份
可能跟舊邏輯不同步的結構化欄位」）。`concentration` 欄位已經把這個 banner
背後真正的資料來源（`position_control_suggestion()` 全部欄位）以結構化
形式提供，之後 React 前端如果要做原生渲染，應該從那裡重新設計 UI，而不是
解析這個 HTML 字串。

**刻意不遷移的部分**（跟 holdings.py 同樣的取捨原則）：
- `/dashboard/stock/<code>/refresh`／`/note`／`/plan`（3 個表單 POST
  端點）、`/dashboard/stocks/add`：留給之後的 Step（任務範圍明講剩 5 個
  表單端點留給之後）
- `refreshing` 狀態：舊版 `is_refreshing(code)` 是 `report_server.py`
  進程內的執行緒安全記憶體 set（`_refreshing_codes`），只有背景更新
  執行緒會寫入。這支路由是完全獨立的 uvicorn 進程，物理上讀不到那個
  set——這不是「忘記遷移」，是兩個進程本來就不共享記憶體，故意不假裝
  能提供這個欄位。
- 走勢圖 SVG（`_render_combo_chart_svg()`）／迷你走勢 SVG：跟 holdings.py
  省略 `spark_html` 同一個理由，已渲染好的圖形字串不是 JSON 資料。改成
  提供畫圖所需的原始資料（`holdings.price_history`／`holdings.
  ledger_entries`／`holdings.avg_cost`），供以後 React 前端自行畫圖。
- `flash` 一次性提示訊息：跟 holdings.py 同理，這是 POST 表單處理完後的
  UX 文案，這一步沒有遷移任何 POST 端點，沒有訊息來源。

**代碼不存在時的行為**：舊版 `do_GET()` 只在 `code` 為空或含 `/` 時回
404（`report_server.py:423-425`）；只要 code 是一般字串，即使查無此股票
的任何資料，也是回 200＋一個「大部分欄位是 None／空清單」的頁面（不是
404）。這裡完全比照：FastAPI 的 `{code}` path 參數本來就不吃含 `/` 的
字串（不吻合的路徑由 FastAPI 自己回它標準的 404，效果等同舊版），空字串
在路由層面對應 `/api/stocks/`（不吻合 `/api/stocks/{code}`，同樣由
FastAPI 自己回 404）；查無資料的正常代碼一律回 200，各欄位為 None／空
清單/`holdings` 整段為 `null`，不額外拋 404——刻意不比照直覺「查無資料
就該 404」，因為那不是舊版的實際行為，遷移的目標是行為一致而非「看起來
更 RESTful」。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends

# app/routers/stock_detail.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 report.py／review_engine.py 所在目錄。
# 獨立做一次 sys.path.insert（跟其餘 app/routers/*.py 同一套 idempotent
# 寫法），讓這個檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import report  # noqa: E402  (需先插入 sys.path 才能 import)
import review_engine  # noqa: E402

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()


@router.get("/api/stocks/{code}")
def get_stock_detail(code: str, store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """對外語意等同舊版 `GET /dashboard/stock/<code>`（不含 `refreshing`
    狀態與已渲染 SVG，理由見檔案 docstring）。

    回傳結構（各區塊資料來源 = 舊版 `report.render_stock_detail_page()`
    對應段落實際呼叫的既有函式，逐一沿用、不重寫）：

    - `code`／`name`：`name` 取自庫存快照，查不到再退回最新立場
      （`store.get_holdings()`／`store.get_latest_stance()`），跟舊版
      開頭邏輯一致。
    - `price`／`prev_close`／`delta_pct`：`store.get_stock_prices()`；
      `delta_pct` 是舊版同一行 `(price-prev_close)/prev_close*100` 的
      單行算式，非整合判斷邏輯，比照沿用。
    - `valuation`：`store.get_stock_valuation()` 原始 dict（本益比／
      股價淨值比／殖利率／營收年增率／資料來源／錯誤訊息等，查不到為
      `None`）。
    - `module_d`：Checks・加碼審查卡的資料層。`latest_batch` 來自
      `report._latest_module_d_batch()`；`gate`／`reference`／`status`
      三個子分類來自 `report._split_module_d_batch()`（舊版 mockup
      的分區依據，見該函式 docstring：策略層不是 Gate）；`score` 來自
      `store.get_auto_score()`；`manual_gate_items`／`manual_score_items`
      是 `review_engine.MANUAL_GATE_ITEMS`／`MANUAL_SCORE_ITEMS`
      （系統無資料源、待人工查證的靜態清單，所有股票共用同一份）。
    - `verdict_html`：見檔案 docstring「唯一例外」一節。
    - `concentration`：`review_engine.position_control_suggestion()`
      原始 dict（單股/主題集中度、下次加碼建議比例等）＋兩個上限常數
      `single_stock_cap_pct`／`theme_cap_pct`。
    - `position_plan`：`store.get_position_plan()`（`None`＝尚未設定）＋
      `report._invested_amount()`（已投入金額/股數/來源，優先讀庫存快照
      成本，缺值退回交易流水表估算）；`completion_pct`／
      `remaining_amount` 只在兩者都有值時才算（同舊版
      `_position_plan_card_html()` 的算式，單行除法，非整合邏輯）。
    - `holdings`：持股與交易卡。舊版「純研究標的（無庫存快照也從無交易
      紀錄）整張卡不顯示」的取捨，這裡對應整段回傳 `None`——不是漏欄位，
      是刻意保留舊版「沒有就不要假裝有資料」的語意。有資料時內含
      `holding_row`（庫存快照列）、`market_value`／`portfolio_pct`
      （來自 `report._portfolio_context()`）、`ledger_entries`（完整
      交易流水）、`price_history`（`store.get_cached_price_history()`，
      供以後畫圖用的原始序列）、`avg_cost`／`avg_cost_label`（來自
      `report._avg_cost_for_chart()`）、`current_price`／`pnl_pct`
      （浮動損益，單行算式同舊版 `_chart_stats_html()`）。
    - `buy_reason`／`buy_reasons_count`／`other_notes`：來自
      `store.get_comments_by_code()`，依 `source_tag == "買進理由"`
      拆成置頂理由（取最新一筆）與其餘留言，拆分邏輯照搬舊版
      `render_stock_detail_page()` 本體（單行 list comprehension 過濾，
      非整合判斷）。
    """
    stance = store.get_latest_stance(code)
    valuation = store.get_stock_valuation(code)
    price_info = store.get_stock_prices().get(code)
    latest_batch = report._latest_module_d_batch(store, code)  # noqa: SLF001  (刻意重用既有資料函式，見檔案 docstring)

    holdings_latest = store.get_holdings()["holdings"]
    holding_row = next((h for h in holdings_latest if h["code"] == code), None)
    name = holding_row.get("name") if holding_row else None
    if not name and stance:
        name = stance.get("name")

    price = price_info["price"] if price_info else None
    prev_close = price_info.get("prev_close") if price_info else None
    delta_pct = None
    if price is not None and prev_close:
        delta_pct = (price - prev_close) / prev_close * 100

    gate, reference, status = report._split_module_d_batch(latest_batch)  # noqa: SLF001
    score = store.get_auto_score(code)
    verdict_html = report._verdict_banner_html(store, code, latest_batch)  # noqa: SLF001

    pc = review_engine.position_control_suggestion(code, store)
    concentration = dict(pc)
    concentration["single_stock_cap_pct"] = review_engine.SINGLE_STOCK_CONCENTRATION_WARN_PCT
    concentration["theme_cap_pct"] = review_engine.THEME_CONCENTRATION_WARN_PCT

    plan = store.get_position_plan(code)
    invested, invested_shares, invested_source = report._invested_amount(store, code)  # noqa: SLF001
    position_plan_block: Dict[str, Any] = {
        "plan": plan,
        "invested_amount": invested,
        "invested_shares": invested_shares,
        "invested_source": invested_source,
        "completion_pct": None,
        "remaining_amount": None,
    }
    if plan and invested is not None:
        position_plan_block["completion_pct"] = invested / plan["plan_amount"] * 100
        position_plan_block["remaining_amount"] = max(plan["plan_amount"] - invested, 0)

    ledger = store.get_trade_ledger(code)["entries"]
    holdings_block = None
    if holding_row is not None or ledger:
        _, market_values, total_value = report._portfolio_context(store)  # noqa: SLF001
        market_value = market_values.get(code)
        portfolio_pct = (market_value / total_value * 100
                        if market_value is not None and total_value else None)
        history = store.get_cached_price_history(code)
        avg_cost = report._avg_cost_for_chart(holding_row, ledger)  # noqa: SLF001
        if holding_row and holding_row.get("avg_cost") is not None:
            avg_cost_label = "均價"
        else:
            avg_cost_label = "均價（%d筆）" % sum(1 for e in ledger if e["action"] == "買")
        current_price = price  # 同一份 store.get_stock_prices() 快取
        pnl_pct = None
        if avg_cost is not None and current_price is not None:
            pnl_pct = (current_price - avg_cost) / avg_cost * 100
        holdings_block = {
            "holding_row": holding_row,
            "market_value": market_value,
            "portfolio_pct": portfolio_pct,
            "ledger_entries": ledger,
            "price_history": history,
            "avg_cost": avg_cost,
            "avg_cost_label": avg_cost_label,
            "current_price": current_price,
            "pnl_pct": pnl_pct,
        }

    comments = store.get_comments_by_code(code, limit=50)["results"]
    buy_reasons = [c for c in comments if c["source_tag"] == "買進理由"]
    other_notes = [c for c in comments if c["source_tag"] != "買進理由"]

    return {
        "code": code,
        "name": name,
        "price": price,
        "prev_close": prev_close,
        "delta_pct": delta_pct,
        "valuation": valuation,
        "module_d": {
            "latest_batch": latest_batch,
            "gate": gate,
            "reference": reference,
            "status": status,
            "score": score,
            "manual_gate_items": [
                {"label": label, "why": why} for label, why in review_engine.MANUAL_GATE_ITEMS
            ],
            "manual_score_items": [
                {"label": label, "weight": weight, "why": why}
                for label, weight, why in review_engine.MANUAL_SCORE_ITEMS
            ],
        },
        "verdict_html": verdict_html,
        "concentration": concentration,
        "position_plan": position_plan_block,
        "holdings": holdings_block,
        "buy_reason": buy_reasons[0] if buy_reasons else None,
        "buy_reasons_count": len(buy_reasons),
        "other_notes": other_notes,
    }
