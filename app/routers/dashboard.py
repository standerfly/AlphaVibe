"""儀表板首頁遷移：GET /api/dashboard。

**這是補漏，不是規劃文件第5節「逐一遷移既有功能」清單的下一個順位項目**
（見 docs/spec-intake/alphavibe/roadmap.md Q-046）：規劃文件的既有功能
遷移清單裡，`/`（儀表板首頁）跟 `/dashboard/stocks`（持股清單）本來就是
兩個分開的項目，之前只搬了後者（app/routers/holdings.py 的
GET /api/holdings）；`/` 本身（report.render_dashboard()，FR-058「今日
重點」所在頁面）完全沒有對應的 app/ 路由，直到要接前端才發現這個缺口。

`render_dashboard()`（poc/kb-mcp/report.py:921-979）docstring 明講「由上
到下——今日重點／今日新候選／觀察名單庫存總覽／策略設定／快速輸入」，
實際上是六個 `_render_*_section()` 呼叫（第三項另外拆出「純觀察標的」
補在後面，見該函式自己的 docstring）。逐一盤點是否已被既有 API 涵蓋：

1. **今日重點**（`_render_today_highlights_section`，report.py:708-749）
   —— **全新，這裡新做**：目前沒有任何既有端點涵蓋。FR-058 核心：
   `module_d_results` 裡 `suggested_action` 不為 `None` 的記錄，依「是否
   持有」為第一排序鍵、「立場衝突」為次要排序鍵。這裡照抄同一段
   `store.get_module_d_results()` 呼叫＋篩選謂詞＋排序 key（逐行對照
   report.py:720-723），只是把「組 HTML 表格」換成「組 dict list」，不是
   重新設計判斷邏輯。
2. **今日新候選**（`_render_new_candidates_section`，report.py:752-801）
   —— **這裡補做**：底層資料 `store.get_latest_market_scan()` 已透過
   `app/routers/market_scan.py` 的 `GET /api/market-scan` 公開，但那支
   路由一次只查一個 framework；report.py 這個區塊是「跨
   `frameworks.FRAMEWORKS` 全部框架合併去重」，這段合併迴圈只存在於
   HTML 渲染函式內，沒有其他 JSON 端點能取得，也沒有任何端點對外列出
   framework id 清單讓呼叫端自己迭代——呼叫端無法只靠現有 API 兜出同一份
   資料。這裡照抄同一段合併邏輯（`frameworks.FRAMEWORKS` 迭代順序、
   `store.get_latest_market_scan(meets_only=True)` 呼叫方式、依代碼合併／
   去重規則，逐行對照 report.py:759-770），不是新發明的判斷。
3. **觀察名單／庫存總覽**（`_render_holdings_section`，report.py:405-518）
   —— **已由 `GET /api/holdings?filter=holdings` 涵蓋**：兩者共用同一段
   核心資料（`store.get_holdings()`／`list_stances()`／
   `get_stock_prices()`／`get_module_d_results()`，經由
   `report._tracked_stock_rows()`——holdings.py 這支既有 router 已經在用
   的函式）。`/api/holdings` 沒有複製市值／持股比例／主題集中度這類延伸
   計算欄位，但那是「持股清單」路由本身既有的取捨（見 holdings.py
   docstring「刻意省略」段，理由是 React 前端另外設計走勢圖等資料時再
   一併規劃），不是這次「首頁補漏」該重做的範圍——這裡只在 `see_also`
   註記，不重複建置。
4. **純觀察標的（無庫存）**（`_render_watchlist_only_section`，
   report.py:521-559）—— **已由 `GET /api/holdings?filter=research` 涵蓋**：
   同一份 `_tracked_stock_rows()` 資料，`is_holding=False` 的子集合就是
   這個區塊（立場存在但代碼不在庫存清單）。
5. **策略設定**（`_render_strategy_settings_section`，report.py:804-829）
   —— **這裡補做**：純靜態設定（`frameworks.FRAMEWORKS` 每套策略的篩選
   門檻與 invalidation 定義），目前沒有任何端點回傳這份設定本身
   （`/api/market-scan` 只回傳某一個 `framework_id` 的「掃描結果」，不是
   「所有框架的門檻設定」）。這裡直接回傳 `frameworks.FRAMEWORKS` 原始
   dict（不經過 `report._format_condition_text()`／`_invalidation_text()`
   的 HTML 轉譯——那兩個函式產出的是給網頁排版用的 HTML 片段字串，含
   `&gt;=` 這類 HTML entity，JSON API 直接給原始數值更符合 screen.py／
   market_scan.py「plain dict、不因為手動定義 schema 而漏欄位」的既有
   慣例，呼叫端要格式化文字可以自己做）。
6. **快速輸入**（`_render_quick_input_section`，report.py:836-918）
   —— **已由 5 個既有寫入端點涵蓋**（`app/routers/actions.py` 的
   `POST /api/watchlist`／`/api/trades`／`/api/laoyutou-trades`／
   `/api/trade-ledger`，與 `app/routers/holdings_import.py` 的
   `POST /api/holdings/preview`／`/api/holdings/confirm`）。這個區塊本身
   只是表單 HTML 標記，沒有資料內容，這裡只在 `see_also` 列出對應端點，
   不用任何方式「翻譯」表單 HTML。「貼CSV對帳單」表單刻意不列在
   `see_also` 裡：`app/main.py` docstring 已說明 `/dashboard/tradecsv`
   不在「5 個表單端點」遷移範圍內，這裡沿用同一個範圍決定，不擅自多列
   一個不存在的端點。

**跟其他 router 一致的取捨**：不改 `poc/kb-mcp/` 任何一行；直接 import
`report`／`frameworks` 呼叫既有函式與資料結構（`sys.path.insert` 方式，
比照 `holdings.py`／`market_scan.py`／`screen.py`）；plain dict 回傳，不包
Pydantic model。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

# app/routers/dashboard.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 report.py／frameworks.py 所在目錄。
# 獨立做一次 sys.path.insert（跟 app/deps.py、其餘 app/routers/*.py 同一套
# idempotent 寫法），讓這個檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import frameworks  # noqa: E402  (需先插入 sys.path 才能 import)
import report  # noqa: E402  (需先插入 sys.path 才能 import)

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()


def _today_highlights(store: KBStore, today: str) -> List[Dict[str, Any]]:
    """逐行對照 `report._render_today_highlights_section()`
    （poc/kb-mcp/report.py:708-749）：同一個 `store.get_module_d_results()`
    呼叫、同一個篩選謂詞（`suggested_action is not None`）、同一個排序 key
    （是否持有為第一鍵、立場衝突為次要鍵），只是回傳 dict list 而非 HTML
    表格。回傳每筆為 `module_d_results` 資料表的原始欄位（`SELECT *`，
    含 `concern_flag`／`strategy_id` 等既有欄位，不手動篩掉任何一個，
    比照 screen.py／market_scan.py「plain dict、不漏欄位」的既有慣例）
    外加一個 `type` 計算欄位（`存股`／`觀察中`，對應 report.py 同一段的
    `type_text`，本來就是呈現用的衍生欄位，不是資料表欄位）。
    """
    results = store.get_module_d_results(date=today)["results"]
    highlights = [r for r in results if r.get("suggested_action") is not None]
    held_codes = {h["code"] for h in store.get_holdings()["holdings"]}
    highlights.sort(key=lambda r: (r["code"] not in held_codes, not r.get("conflict_flag")))
    return [
        {**r, "type": "存股" if r["code"] in held_codes else "觀察中"}
        for r in highlights
    ]


def _today_new_candidates(store: KBStore) -> List[Dict[str, Any]]:
    """逐行對照 `report._render_new_candidates_section()`
    （poc/kb-mcp/report.py:752-801）：同一個 `frameworks.FRAMEWORKS` 迭代
    順序、同一個 `store.get_latest_market_scan(meets_only=True)` 呼叫、
    同一套「依代碼合併、符合的框架各自併入 `matched_frameworks`」規則，
    只是回傳 dict list 而非 HTML 表格。每筆是 `market_scan_results` 的原始
    欄位（同 `/api/market-scan` 的 `results` 欄位定義）外加
    `matched_frameworks`（該代碼符合的所有框架 label，對應 report.py 同
    一段的 `tags`，這裡改成原始清單而非已渲染的 HTML `<span>` 標籤）。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for fw in frameworks.FRAMEWORKS:
        latest = store.get_latest_market_scan(framework_id=fw["id"], meets_only=True)
        if not latest.get("found"):
            continue
        for r in latest["results"]:
            code = r["code"]
            if code not in merged:
                merged[code] = {"row": r, "labels": []}
                order.append(code)
            merged[code]["labels"].append(fw["label"])
    return [
        {**merged[code]["row"], "matched_frameworks": merged[code]["labels"]}
        for code in order
    ]


def _strategy_settings() -> List[Dict[str, Any]]:
    """對照 `report._render_strategy_settings_section()`
    （poc/kb-mcp/report.py:804-829）：回傳 `frameworks.FRAMEWORKS` 原始
    dict（淺拷貝，避免呼叫端意外改到模組層級的共用設定），不經過
    `report._format_condition_text()`／`_invalidation_text()` 的 HTML
    轉譯——那兩個函式是給網頁排版用，回傳的是 HTML 片段字串，JSON API
    直接給原始數值更符合既有慣例。"""
    return [dict(fw) for fw in frameworks.FRAMEWORKS]


@router.get("/api/dashboard")
def get_dashboard(store: KBStore = Depends(get_kb_store)) -> Dict[str, Any]:
    """對外語意等同舊版 `GET /`（`report.render_dashboard()`）：回傳儀表板
    首頁六個區塊裡、目前沒有其他既有端點涵蓋的資料（今日重點／今日新
    候選／策略設定），其餘已被涵蓋的區塊（觀察名單庫存總覽／純觀察標的／
    快速輸入）在 `see_also` 註記對應的既有端點，不重複建置。

    刻意不搬的部分：`flash`（表單送出後的一次性成功/失敗訊息，純 UX
    文案，跟 holdings.py 對同一參數的取捨理由一致）；「本頁為研究輔助
    資訊，非投資建議」這類頁面文案（HTML 呈現層的固定文字，JSON API
    沒有等價欄位，且不影響資料本身）。
    """
    today = datetime.date.today().isoformat()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "generated_at": now,
        "date": today,
        "today_highlights": _today_highlights(store, today),
        "today_new_candidates": _today_new_candidates(store),
        "strategy_settings": _strategy_settings(),
        "see_also": {
            "holdings_overview": "GET /api/holdings?filter=holdings",
            "watchlist_only": "GET /api/holdings?filter=research",
            "market_scan_by_framework": "GET /api/market-scan?framework=<id>",
            "quick_input": {
                "add_watchlist": "POST /api/watchlist",
                "add_trade": "POST /api/trades",
                "add_laoyutou_trade": "POST /api/laoyutou-trades",
                "add_trade_ledger": "POST /api/trade-ledger",
                "holdings_preview": "POST /api/holdings/preview",
                "holdings_confirm": "POST /api/holdings/confirm",
            },
        },
    }
