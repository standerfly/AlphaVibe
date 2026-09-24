# Research: 美股獨立投資系統

**Feature**: `specs/003-us-stocks/spec.md`
**Date**: 2026-09-06

本文件解決 Technical Context 中的未知項與關鍵技術決策，依據對本 repo 既有
架構的實地查證（Explore agent，2026-09-06），而非通用最佳實務臆測。

---

## 1. 資料庫獨立方案（解決 pre-spec Q-005：美股KB要怎麼獨立）

**問題**：spec.md FR-015/FR-016 要求美股資料表與查詢管道完全獨立於台股。

**查證結果**：
- `KBStore.__init__(self, data_dir)`（`poc/kb-mcp/kb_store.py:329`）只接受
  `data_dir`，DB 檔名 `"alphavibe.db"` 是類別內部寫死（`kb_store.py:333`），
  不支援傳入不同 db 檔名
- 2026-08-22 新增的「資產」5張表**沒有**開新 db 檔，是加進同一個
  `alphavibe.db` 的同一個 `SCHEMA` 字串（`kb_store.py:217-263`）

**決策**：新增一個獨立的 `USStockStore` 類別（新檔案
`poc/kb-mcp/us_stock_store.py`），有自己的 schema 與獨立的 db 檔案
`poc/data/us_stocks.db`，**不修改、不繼承、不共用 `KBStore`**。

**理由**：
- 修改 `KBStore.__init__` 加 `db_path` 參數技術上可行，但會讓兩個市場的
  程式碼路徑糾纏在同一個類別裡，任何未來對 `KBStore` 的改動都有意外波及
  美股資料的風險——這正是 FR-015/016「完全獨立」想避免的情況
- 全新獨立類別＋獨立 db 檔案，是唯一能讓「美股功能的查詢/寫入路徑都不觸及
  台股既有的資料或工具」（FR-016）在物理層級成立的做法，不只是邏輯層級

**Alternatives considered**：
- 修改 `KBStore` 加 `db_path` 參數 → 拒絕，理由如上（程式碼路徑糾纏風險）
- 同一個 db 檔案加美股專用表（比照資產表的先例）→ 拒絕，這正是 2026-08-22
  資產表污染事故的同一種風險模式（一個db檔案，任何連進來的呼叫端都摸得到
  所有表），且 FR-016 明確要求連查詢管道都要獨立，同檔案無法滿足

---

## 2. MCP 查詢管道獨立方案

**決策**：新增一組獨立的 MCP 工具（新檔案，暫名
`poc/kb-mcp/us_stock_mcp_server.py`，比照既有 `server.py`／
`server_readonly.py` 的 server 模式），工具命名加上明確前綴區分（例如
`save_us_trade`／`get_us_holdings`／`save_us_stance`／
`get_us_watch_conditions`，具體命名見 `contracts/mcp-tools.md`），內部只
呼叫 `USStockStore`，不 import 任何 `kb_store.py` 或既有 `server.py` 的
函式。

**理由**：與第1點一致——查詢管道獨立要在程式碼層級體現，不能只是「工具
名字不同但底層共用同一份程式碼」。

---

## 3. 交易截圖「辨識」的技術做法（解決 spec.md 的關鍵假設）

**查證結果（重要發現）**：本 repo 既有的 4 個交易/持股匯入工具
（`parse_holdings_report`、`parse_and_save_laoyutou_trades`、
`parse_and_save_trade_ledger`、`parse_and_save_trade_csv`，皆定義於
`poc/kb-mcp/server.py`）的 `inputSchema` **全部只接受 `text: string`**，
**沒有任何一個接受圖片參數**。實作面（`holdings_parser.py`／
`trade_ledger_parser.py`／`trade_text_parser.py`）也證實只用正則表達式
解析固定格式的文字，完全沒有 import 任何影像處理或 OCR 套件。

**結論**：這幾個既有工具的「辨識」步驟，發生在**呼叫工具之前**——是
Claude（或使用者）先讀圖／轉文字，工具本身只管解析文字格式。

**決策**：美股交易截圖匯入（FR-002/003/004）**沿用完全相同的模式**：
1. 使用者在對話中上傳截圖
2. Claude 用自己的多模態視覺能力讀圖，轉成結構化文字（日期/代號/買賣/
   股數/價格）
3. Claude 呼叫新的 MCP 工具（例如 `parse_and_save_us_trade`，接受
   `text: string`，比照既有工具的 inputSchema 慣例）
4. 工具內部用正則表達式解析文字、寫入核對用的暫存結構，前端呈現核對畫面
   （STEP 2）供使用者確認/修正
5. 使用者確認後才真正寫入 `USStockStore`

**理由**：**不需要新增 OCR/影像處理程式碼或依賴**——STND 系統的「辨識」
向來是 agent 與使用者互動的一部分，不是後端服務自己做電腦視覺。這與整個
系統「agent-mediated」的既有設計哲學一致（比照今天 Cloudflare 研究、
`stock-researcher` subagent 這類先例），也大幅降低技術複雜度與依賴風險。

**Alternatives considered**：
- 整合真正的 OCR 函式庫（Tesseract／雲端視覺API）→ 拒絕，既有系統從未
  這樣做過，且 Claude 本身的多模態能力已經能勝任這個工作，多一層 OCR
  依賴只會增加失敗點與維護成本，沒有對應的效益

---

## 4. 每日排程機制（解決 spec.md FR-006/017：排程怎麼做，額度用盡怎麼降級）

**查證結果**：
- `market_scan.py` 由 macOS launchd plist 觸發（部署在
  `~/Library/LaunchAgents/com.alphavibe.marketscan.plist`，**不在 repo
  版控範圍內**，是直接建在使用者機器上的獨立檔案），`StartCalendarInterval`
  設定為每天 02:00
- 降級處理的實際程式碼模式（非文件轉述）：每一次外部 API 呼叫都包在
  try/except 裡，失敗回傳 `{"error": ...}` 而不拋例外
  （`finmind_client.py:43-53`、`market_scan.py:47-74`）；多個獨立單位
  （市場、框架、股票）各自獨立失敗，互不影響（`market_scan.py:102-182,
  307-319`）；CLI 層即使有單位失敗也確保 `store.close()`、其餘單位照常
  寫入（`market_scan.py:352-371`）

**決策**：新增獨立腳本 `poc/kb-mcp/us_stock_scan.py`（CLI 入口，比照
`market_scan.py:327-377` 的 `main()` 模式），由新的獨立 launchd plist
（`com.alphavibe.usstockscan.plist`，同樣部署在使用者機器上、不進版控）
每日觸發一次。排程時間建議 **台北時間早上 6:00**（美股收盤約為台北時間
清晨 4-5 點，視夏令時間，6:00 可確保當天收盤資料已可查詢，且與
`market_scan.py` 的 02:00 錯開，避免兩個排程同時搶佔系統資源）。

降級邏輯完全比照既有模式：對每一檔追蹤股票獨立包 try/except，主要來源
（FMP）失敗時嘗試備援來源，兩者皆失敗且該股**從未成功取得過資料**→
標示「資料不足」；若該股**過去曾有資料、只是這次額度用盡而跳過**→ 標示
「未更新（無額度）」（FR-017，需要在 `USStockStore` 的 schema 設計時
支援保留「上一次成功資料」而非覆寫清空，見 `data-model.md`）。整個排程
執行過程中，任一股票失敗都不中斷其餘股票的處理，比照
`market_scan.py:307-319` 的模式。

**Alternatives considered**：
- 用 Python 內建排程套件（`schedule`/`APScheduler`）常駐執行 → 拒絕，
  這個 repo 從未使用這類套件，既有排程一律靠 launchd，維持架構一致性
- 排程時間對齊 `market_scan.py` 的 02:00 → 拒絕，兩個排程同時觸發可能
  搶佔系統資源，且美股收盤時間跟台股不同，沒有理由對齊

---

## 5. 外部報價 API 串接（延續 pre-spec Integration Note 的決定）

已在 pre-spec 階段定案：主要來源 FMP（250次/日免費額度），備援來源候選
Alpha Vantage 或 yfinance。**本次 research 階段的待確認項**：repo 既有
`finmind_client.py`／`twse_price_client.py` 用什麼 HTTP client 函式庫
（例如 `requests`）——若有明確既有慣例，新的 FMP client 應該沿用同一個
函式庫維持一致性；此細節留待實作階段開始寫程式碼時直接查看這兩個既有
client 檔案確認，不影響本規劃文件的其餘決策。

---

## Technical Context 未知項解決總覽

| 未知項 | 解決方式 |
|---|---|
| Storage 方案 | 獨立 `USStockStore` + 獨立 db 檔 `us_stocks.db`（§1） |
| 查詢管道獨立 | 獨立 MCP server 檔案，新工具前綴命名（§2） |
| 截圖辨識技術 | 不需要 OCR，沿用 agent 讀圖轉文字＋既有文字解析模式（§3） |
| 排程機制 | 獨立 launchd plist，比照 `market_scan.py` 模式，台北時間06:00（§4） |
| 降級/額度用盡處理 | 沿用既有 try/except 單位獨立失敗模式（§4） |
| HTTP client 函式庫 | 待實作階段直接查看 `finmind_client.py` 確認（§5，non-blocking） |
