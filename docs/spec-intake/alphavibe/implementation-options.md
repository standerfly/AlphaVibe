# AlphaVibe 實作路線選項（決策支持文件）

> 2026-07-07 由 Claude Code session 產出，供 PO 決策。
> 觸發問題：「如何實現本專案，尤其是 AI 對話？我目前都是跟 AI agent 對話，
> 但訊息都在 web 版，我想本地端系統化。」
> 本文件不是 spec，是選項與代價的整理；定案後應回填 scope-decision.md。

## 背景：AI-stock-km-v1 盤點結論（2026-07-07 派 agent 實查）

`/Users/stander/My_project/AI-stock-km-v1` 是開發中的台股投資 AI 分析儀表板
（FastAPI + React，`main.py` v2.0.0，最後 commit 2026-05-14，工作區有未提交修改）。

**可借鏡的工程模式**（參考架構，非直接複製）：
- async SQLAlchemy + aiosqlite 的 SQLite 存取層（`core/database.py`）
- 多來源 ingest pipeline：text/url/pdf/youtube/image（`api/ingest_router.py` + `skills/*`）
- APScheduler 排程（`main.py:42-152`）、router 分層

**AlphaVibe 需要但它沒有的**（等於都要新做）：
- Claude/Anthropic API 整合（它用 litellm + Gemini）
- SQLite FTS5 全文檢索（它用外部 Qdrant 向量庫，與 Q-015 決策不符）
- 三層知識庫 schema（哲學／個股立場／每日評論——完全沒有此概念）
- 「AI 抽取 → 提議 → 使用者確認 → 入庫」流程（它的 ingest 是直接寫入）

已知環境問題：該 repo `.mcp.json` 的 sqlite server 寫死 Windows 路徑
`d:/AI-stock-km-v1/...`，在 macOS 上不能用，要用時需先改路徑。

## 推薦路線：兩階段

### Phase 1 — MCP 知識庫 + 既有 AI 對話工具（先解「本地端系統化」的痛）

> 2026-07-07 更新（SRC-009 主軸重塑，Q-029/Q-030/Q-032）：PoC 範圍由
> 「知識庫＋對話入庫」擴為「知識庫＋對話入庫＋**FinMind 個股數據查詢＋
> 估值討論工作流**」，以驗證新主軸的選股估值迴圈；引擎定案為
> Claude（思考）＋Cline（粗活），與本節原構想一致。

做一個小的 **MCP server（`alphavibe-kb`，Python，須相容本機 Python 3.9）**：
1. 三層知識庫的 SQLite 儲存層：Layer 1 哲學（md 檔或表）、
   Layer 2 個股立場（結構化表 {code, name, stance, reason, date,
   entry_condition, valuation_metric, source}）、
   Layer 3 每日評論（FTS5 虛擬表）
2. 暴露工具：`save_philosophy` / `save_stance` / `save_comment` /
   `query_stance` / `search_comments`
3. FinMind 個股級數據查詢工具（`get_fundamentals`：PER、殖利率、EPS 等），
   支撐「名單驅動＋哲學驅動」選股與估值討論（FR-019~021）

然後**對話照舊發生在你已經在用的 AI agent 裡**（Claude Code / Claude Desktop），
掛上這個 MCP：聊到有價值的內容時，AI 發起 save 工具呼叫，
**harness 的工具核准提示就是 Q-021 決策的「即時確認制」**——你按允許才寫入，
資料落在本地 SQLite。

- 解決的痛：對話在本地、入庫內容在本地 DB，不再散在 web 版
- 額外價值：直接驗證三層 schema 與抽取 prompt 的品質，是 Phase 2 的 PoC 證據
- 成本：小（單一 Python 套件，無前端），數天等級
- 位置（2026-07-07 已決策）：放 AlphaVibe repo 內（建議 `poc/` 目錄），
  正式實作時由 speckit 流程接手；不另開 repo

### Phase 2 — 正式產品（mockup 前端化 + FastAPI + Claude API）

走 ADR-0027 正規流程：補完 product-spec（目前仍 TBD）→ speckit-specify/plan/tasks
→ 實作。技術形態：
- 後端 FastAPI，`/chat` endpoint 用 Claude API（tool use 產生歸檔提議卡）
- 前端由 `frontend_mockup.html` 演進（AI 對話頁籤已有確認卡的互動設計）
- 儲存層直接沿用 Phase 1 的 SQLite 模組（同一顆 DB、同一套 schema）
- 工程模式參考 AI-stock-km-v1（ingest 分層、排程），LLM 層與 schema 新做

## 行動端（iPhone）路線紀錄（2026-07-10，Q-037）

**檢視層（已實作）**：report_server.py 即時渲染＋PWA meta，經 VS Code
devtunnels 8080 轉發（網址固定＋帳號驗證）；iPhone Safari 加入主畫面。

**對話層（暫不做，路線已查證）**：Claude App「自訂連接器」掛自架遠端
MCP server——官方支援手機 App 繼承、僅支援 tool calls、由 Anthropic 雲端
連入（端點須公網可達）。要做時的工程：現有 MCP server 加 streamable HTTP
閘道（純標準庫可行，重用既有工具邏輯）＋tunnel 公開外露＋存取控制
（URL secret 或 OAuth）。參考：support.claude.com 文章
11503834（build custom connectors via remote MCP）與 11175166（get
started with custom connectors）。

**CH-EN 專案研究結論（2026-07-10 實查 /Users/stander/My_project/CH-EN）**：
其手機可用機制＝Cloudflare **Quick** Tunnel（`cloudflared tunnel --url
http://localhost:PORT`，出站連線免開防火牆）；限制＝網址每次重啟改變、
無存取驗證；repo 內無 Oracle Cloud 設定（PO 原印象不符）、無 PWA 元素。
評估：檢視層不沿用（devtunnels 較優：網址固定＋驗證）；cloudflared 模式
記為備援（未來 devtunnels 失效或需分享時，改用 Named Tunnel＋驗證的正規版）。

## 開放問題與決策狀態

- **OQ-A（產品層）——已決策（2026-07-07，Q-022）**：只維護 AlphaVibe 一個專案。
  AI-stock-km-v1 封存不刪：留作架構參考，其既有資料（`data/stock_kb.db` 的
  raw_documents、watchlist 等表）日後可遷移進 AlphaVibe。
- **OQ-B（範圍層）——已決策（2026-07-07）**：Phase 1 MCP spike 放 AlphaVibe
  repo 內（`poc/` 目錄），不另開 repo。時程：**先補完 product-spec 再動工**
  （PO 2026-07-07 指示）。
- **OQ-C（銜接層）——已決策（2026-07-07，Q-023）**：不撈回 web 版歷史對話。
  日後個別重要內容以手動貼入處理（FR-001 通道），不做自動化匯入。
