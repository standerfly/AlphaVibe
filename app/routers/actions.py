"""既有表單端點遷移（4/5）：POST /api/watchlist、/api/trades、
/api/laoyutou-trades、/api/trade-ledger。

規劃文件第5節「逐一遷移既有功能」最後一批的其中 4 項（見
docs/spec-intake/alphavibe/roadmap.md Q-046「5 個表單端點：
watchlist／trade／laoyutou／tradeledger／holdings-preview」——前四項見本
檔，holdings-preview 是兩步驟預覽/確認表單，明顯更複雜，留給之後的
Step，不在這裡）。MCP、/screen、/market-scan、持股清單、個股詳情五項既有
唯讀端點已完成（見 app/routers/mcp.py、screen.py、market_scan.py、
holdings.py、stock_detail.py）；`/dashboard/tradecsv`、`/dashboard/stocks/add`、
`/dashboard/stock/<code>/refresh`／`/note`／`/plan`、`/market-scan/track`
等其餘既有表單路由**不在**規劃文件列出的「5 個表單端點」清單內，這裡
比照前面各 router docstring 的既有慣例，不擅自擴大範圍去遷移。

對應舊路由（見 poc/kb-mcp/report_server.py `do_POST()`）：
- POST /dashboard/watchlist   → POST /api/watchlist       （加自選股，單筆表單）
- POST /dashboard/trade       → POST /api/trades          （記錄交易，單筆表單）
- POST /dashboard/laoyutou    → POST /api/laoyutou-trades （老芋頭進出，批次貼文字解析）
- POST /dashboard/tradeledger → POST /api/trade-ledger    （PO自己的交易明細表，批次貼文字解析）

**這是這批遷移唯一涉及寫入的一組路由**（前面五項既有 router 都只查詢）。
安全限制與前面幾項相同：不動 poc/ 底下任何檔案、不影響常駐的
poc/kb-mcp/report_server.py／launchd／ngrok；驗證這批路由時一律對著
複製出來的測試資料庫操作，絕不對正式 poc/data/alphavibe.db 做任何寫入
測試（執行細節與證據是任務執行過程的產物，不落在程式碼裡，這裡只記錄
設計本身）。

**介面轉換**：舊路由是 `application/x-www-form-urlencoded` 表單 + 伺服器
端 redirect（`_dashboard_flash_redirect()` 把成功/失敗訊息塞進
`?flash=` query string，用 303 redirect 回首頁顯示）；這裡改成 JSON
request body + JSON response（理由同前面各 router：以後 React 前端要直接
打這些 API，不該讓後端負責組 redirect URL 或 flash 文案）。**寫入邏輯
本身完全不重寫**：4 條路由分別直接呼叫既有的
`store.save_stance()`／`store.save_trade_ledger_entry()`／
`trade_text_parser.resolve_and_save_laoyutou_trades()`／
`trade_ledger_parser.resolve_and_save_trade_ledger()`——跟
report_server.py 對應分支呼叫的函式完全相同，只換了「輸入從哪裡解析」
「成功/失敗怎麼回應」這兩層介面，中間的必填檢查／格式驗證／去重／
add_sequence 計算一行都沒有重寫。

**錯誤回應設計**（三層，各自對應舊版的一種既有檢查）：
1. 請求體本身缺必填欄位、型別不對（例如 `shares` 不是數字）→
   FastAPI/Pydantic 自動回 422，帶欄位層級的錯誤說明。這一層對應舊版
   `float(shares_raw)` 等 `try/except ValueError` 轉型檢查。
2. 型別正確但語意不合法、且檢查邏輯本來就寫在 `report_server.py`
   do_POST() 分支本身（不在 kb_store.py 裡）的情況——例如 `code` 去空白
   後是空字串、貼上的 `text` 是空字串——這裡照原樣搬過來，回 400 + 沿用
   原本的中文錯誤文案。
3. 型別正確但語意不合法、且檢查邏輯本來就寫在 `kb_store.py` 寫入方法
   內部的情況——例如 `action` 不是「買」或「賣」——直接呼叫既有方法讓它
   丟 `ValueError`，這裡只負責 catch 並轉成 400，錯誤文字直接沿用
   exception message，不重新編一份。

**source_ref 文案調整**（唯一偏離「一字不動搬過去」的地方，純文字標籤，
不影響任何驗證/寫入邏輯或資料結構）：舊路由固定寫「dashboard快速輸入」，
這裡改成「app快速輸入」，如實反映這筆資料實際上是透過新 FastAPI JSON
API 寫入、不是透過舊版伺服器端表單。laoyutou／trade-ledger 兩條路由呼叫
的 `resolve_and_save_*` 函式內部自己已經硬寫了各自的 source_ref
（「老芋頭進出批次解析」／「交易明細表批次解析」），這裡沒有介面可以
覆寫、也不需要覆寫，原樣沿用。

**回應內容選擇**（比照 screen.py／market_scan.py「plain dict、不包裝
`success`/`data` 外層」的既有慣例）：4 條路由都直接回傳底層函式的原始
回傳 dict，讓呼叫端拿到的欄位跟 kb_store.py／trade_text_parser.py／
trade_ledger_parser.py 的既有回傳形狀完全一致。**唯一行為差異**：舊版
`/dashboard/watchlist` 分支完全不檢查 `save_stance()` 的回傳值（衝突與否
一律都導回「已加入自選股：<code>」），這裡把回傳值原樣透出，讓呼叫端能
看到 `conflict`／`saved` 狀態——這是「介面從『只看得到一句訊息』變成
『看得到完整結構化欄位』的必然結果，不是新增了 save_stance() 原本沒有
的驗證邏輯」（`conflict` 判斷本來就存在於 save_stance() 內部，舊路由只是
沒有把它用出來）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# app/routers/actions.py 在 AlphaVibe/app/routers/ 底下，往上兩層是
# AlphaVibe/，再進 poc/kb-mcp/ 才是 trade_text_parser.py／
# trade_ledger_parser.py 所在目錄。獨立做一次 sys.path.insert（跟
# app/deps.py、其餘 app/routers/*.py 同一套 idempotent 寫法），讓這個
# 檔案不依賴其他模組是否已先被 import 過。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import trade_ledger_parser  # noqa: E402  (需先插入 sys.path 才能 import)
import trade_text_parser  # noqa: E402

from app.deps import KBStore, get_kb_store  # noqa: E402

router = APIRouter()

# 新路由統一用這個標籤取代舊版寫死的「dashboard快速輸入」，理由見本檔
# 開頭 docstring「source_ref 文案調整」一段。只有 watchlist／trades 兩條
# 單筆路由用得到（laoyutou／trade-ledger 的 source_ref 是底層函式內部
# 硬寫的，這裡管不到也不需要管）。
_SOURCE_REF = "app快速輸入"


class WatchlistCreate(BaseModel):
    """POST /api/watchlist 的 request body，欄位語意等同舊版
    `/dashboard/watchlist` 表單的 `code`／`name` 欄位。"""

    code: str = Field(..., description="股票代碼，必填（去除前後空白後不可為空字串）")
    name: Optional[str] = Field(None, description="股票名稱，選填")


class TradeCreate(BaseModel):
    """POST /api/trades 的 request body，欄位語意等同舊版 `/dashboard/trade`
    表單的 `code`／`name`／`action`／`shares`／`price`／`date`／
    `add_sequence` 欄位（單筆手動填寫，非批次貼文字）。"""

    code: str = Field(..., description="股票代碼，必填")
    name: Optional[str] = Field(None, description="股票名稱，選填")
    action: str = Field(..., description="買 或 賣，必填")
    shares: float = Field(..., description="股數，必填")
    price: float = Field(..., description="成交價格，必填")
    date: str = Field(..., description="交易日期（YYYY-MM-DD），必填")
    add_sequence: Optional[int] = Field(
        None, description="加碼序號，選填；賣出時 kb_store.py 會強制存 NULL"
    )


class TradeTextInput(BaseModel):
    """POST /api/laoyutou-trades、POST /api/trade-ledger 共用的 request
    body 形狀，欄位語意等同舊版兩個表單各自唯一的 `text` 欄位（批次貼上
    的原始文字）。"""

    text: str = Field(..., description="批次貼上的原始文字，必填")


@router.post("/api/watchlist")
def create_watchlist_entry(
    payload: WatchlistCreate, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/watchlist`：以「觀察」立場把一檔
    股票加入自選（呼叫 `store.save_stance()`，不重寫該方法的立場衝突判斷
    /寫入邏輯）。

    `code` 去除前後空白後為空字串 → 400（照搬舊版 `do_POST()` 本來就在
    handler 層做的檢查，`save_stance()` 本身不驗證 code 是否為空）。

    成功回應直接是 `save_stance()` 的原始回傳 dict：
    `{"saved": bool, "conflict": bool, "record": {...}}`（衝突且未覆寫時
    是 `{"saved": False, "conflict": True, "existing": {...}, "hint": "..."}`
    ——舊版表單流程無法傳入 `overwrite`，這裡同樣不暴露，行為與舊版一致，
    只是把衝突結果如實回傳而非靜默忽略，見本檔開頭 docstring 說明）。
    """
    code = (payload.code or "").strip()
    name = (payload.name or "").strip() or None
    if not code:
        raise HTTPException(status_code=400, detail="⚠️ 加自選股失敗：代碼為必填")
    return store.save_stance(code, "觀察", name=name, source_ref=_SOURCE_REF)


@router.post("/api/trades")
def create_trade(
    payload: TradeCreate, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/trade`：把單筆手動填寫的交易寫入
    `trade_ledger`（呼叫 `store.save_trade_ledger_entry()`，不重寫該方法的
    必填檢查／add_sequence 賣出歸零邏輯）。

    `code`／`action`／`date` 去除前後空白後為空字串，或 `action` 不是
    「買」「賣」→ `save_trade_ledger_entry()` 內部會丟 `ValueError`，這裡
    catch 起來轉成 400，錯誤文字直接沿用 exception message。`shares`／
    `price`／`add_sequence` 型別錯誤（例如帶非數字字串）在進到這支函式
    之前就會被 Pydantic 攔下回 422（對應舊版 `float()`/`int()` 轉型失敗的
    `try/except`）。

    成功回應直接是 `save_trade_ledger_entry()` 的原始回傳 dict：
    `{"saved": True, "id": int, "code": str, "action": str,
    "add_sequence": int|None, "date": str, "order_ref": None}`
    （這條路由不支援 `order_ref`，語意同舊表單——`order_ref` 只有批次貼
    交易明細表時才有意義，見 trade_ledger_parser.py 防重複機制）。
    """
    code = (payload.code or "").strip()
    name = (payload.name or "").strip() or None
    action = (payload.action or "").strip()
    date = (payload.date or "").strip()
    try:
        return store.save_trade_ledger_entry(
            code,
            name,
            action,
            payload.shares,
            payload.price,
            date,
            add_sequence=payload.add_sequence,
            source_ref=_SOURCE_REF,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="⚠️ 記交易失敗：%s" % exc) from exc


@router.post("/api/laoyutou-trades")
def create_laoyutou_trades(
    payload: TradeTextInput, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/laoyutou`：把批次貼上的老芋頭進出
    文字解析＋寫入 `laoyutou_trades`（`trade_text_parser.
    parse_laoyutou_trade_text()` + `resolve_and_save_laoyutou_trades()`，
    兩段都是既有純函式，這裡不重寫日期/交易行解析規則、也不重寫名稱→代碼
    解析或寫入邏輯）。

    `text` 去除前後空白後為空字串 → 400（照搬舊版 `do_POST()` 本來就在
    handler 層做的檢查）。

    成功回應直接是 `resolve_and_save_laoyutou_trades()` 的原始回傳 dict：
    `{"total_parsed": int, "saved": [...], "unresolved_names": [...],
    "unparsed_lines": [...]}`——名稱查無對應代碼、或格式無法解析的行都不
    會擋下整批請求（跟舊版行為一致：這兩種情況只計入對應清單，其餘可解析
    的交易照常寫入，200 回應），呼叫端應檢查這兩個清單是否為空來判斷是否
    「完全成功」。
    """
    text = payload.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="⚠️ 貼老芋頭進出失敗：內容是空的")
    parsed = trade_text_parser.parse_laoyutou_trade_text(text)
    return trade_text_parser.resolve_and_save_laoyutou_trades(
        parsed, store, data_dir=store.data_dir
    )


@router.post("/api/trade-ledger")
def create_trade_ledger_entries(
    payload: TradeTextInput, store: KBStore = Depends(get_kb_store)
) -> Dict[str, Any]:
    """對外語意等同舊版 `POST /dashboard/tradeledger`：把批次貼上的交易
    明細表文字解析＋寫入 `trade_ledger`（`trade_ledger_parser.
    parse_trade_ledger_text()` + `resolve_and_save_trade_ledger()`，兩段
    都是既有純函式，這裡不重寫資料列解析規則、名稱→代碼解析、
    add_sequence 計算、或委託書號防重複邏輯）。

    `text` 去除前後空白後為空字串 → 400（照搬舊版 `do_POST()` 本來就在
    handler 層做的檢查）。

    成功回應直接是 `resolve_and_save_trade_ledger()` 的原始回傳 dict：
    `{"total_parsed": int, "saved": [...], "unresolved_names": [...],
    "unparsed_lines": [...], "duplicates_skipped": [...]}`——名稱查無代碼、
    格式無法解析、或委託書號重複的資料列都不會擋下整批請求（跟舊版行為
    一致：這三種情況只計入對應清單，其餘資料列照常寫入，200 回應）。
    """
    text = payload.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="⚠️ 貼交易明細表失敗：內容是空的")
    parsed = trade_ledger_parser.parse_trade_ledger_text(text)
    return trade_ledger_parser.resolve_and_save_trade_ledger(
        parsed, store, data_dir=store.data_dir
    )
