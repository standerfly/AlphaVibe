# Tasks: 美股獨立投資系統

**Input**: Design documents from `/specs/003-us-stocks/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md（全部已存在）

**Tests**：本清單包含測試任務——spec.md 本身沒有明講要 TDD，但比照本 repo
既有慣例（`poc/kb-mcp/tests/`、`app/tests/test_smoke.py` 皆為深度比對測試、
非僅測 200 OK），沿用同等測試密度，非新規定。

**Organization**：任務依 spec.md 的 3 個 User Story（P1/P2/P3）分組，每個
Story 完工後都應該能獨立展示/驗證。

## ✅ 已確認：截圖上傳發生在對話中，不是網頁表單

`research.md` §3 查證發現：既有交易匯入工具全部**只接受文字，不接受圖片**，
辨識步驟發生在「Claude 讀圖轉文字」這一層，不是後端服務的工作。

**PO 已於 2026-09-07 確認**：真正的「上傳截圖」動作發生在**與 Claude 的
對話中**（使用者把截圖貼進對話），Claude 讀圖轉文字後呼叫
`parse_and_save_us_trade` 存成待核對紀錄；網頁的「交易匯入畫面」只負責
**呈現核對結果、讓使用者確認/修正**（對應 mockup `Import.dc.html` 的
STEP 2），**不實作 STEP 1 的網頁拖曳上傳 UI**。T013/T017 依此執行，
不需要再確認。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行執行（不同檔案、無相依）
- **[Story]**：對應 spec.md 的 US1/US2/US3

## Path Conventions

延伸既有 `app/`（FastAPI）＋`web/`（React）＋`poc/kb-mcp/`（演算法/儲存層）
三層架構，不新建 `backend/`／`frontend/` 目錄（見 plan.md Structure Decision）。

---

## Phase 1: Setup

- [X] T001 建立 `poc/kb-mcp/us_stock_store.py` 骨架（空類別＋import），並在
      `poc/data/.gitignore`（若無則新增）確認 `us_stocks.db` 會被忽略
- [X] T002 [P] 建立 `poc/kb-mcp/us_stock_mcp_server.py` 骨架（server 註冊
      樣板，尚無實際工具）
- [X] T003 [P] 建立 `app/routers/us_stocks.py` 骨架，並在 `app/main.py`
      註冊此 router（比照既有 router 的 include_router 慣例）
- [X] T004 [P] `web/src/components/AppShell.jsx` 的 `TABS` 常數新增「美股」
      項目＋圖示；`web/src/App.jsx` 新增對應路由（先指向佔位頁面）

---

## Phase 2: Foundational（阻擋所有 User Story，必須先完成）

**⚠️ 這個 Phase 完成前，任何 User Story 都不能開始**

- [X] T005 在 `poc/kb-mcp/us_stock_store.py` 實作 `USStockStore` 類別與
      4 張表 schema（`us_trades`／`us_stances`／`us_watch_conditions`／
      `us_price_snapshots`，欄位定義見 `data-model.md`）——**不得**在
      `__init__` 掛任何有副作用的種子寫入邏輯（2026-08-22 資產表事故教訓，
      見 CLAUDE.md 教訓紀錄）
- [X] T006 [P] 為 `USStockStore` 的資料目錄解析加上安全防呆（比照
      `app/deps.py::_resolve_data_dir()` 的既有模式：未明確設定環境變數
      拒絕啟動，指向正式路徑需額外旗標）
- [X] T007 [P] 實作 `poc/kb-mcp/us_stock_price_client.py`：FMP 主要來源＋
      備援來源（Alpha Vantage 或 yfinance，二擇一定案，見 research.md §1
      待辦）的 HTTP client，失敗回傳 `{"error": ...}` 而非拋例外（比照
      `finmind_client.py:43-53` 的既有模式）
- [X] T008 實作 `poc/kb-mcp/us_stock_scan.py` CLI 入口：迴圈處理所有追蹤中
      股票，呼叫 T007 的 client 取得價格/基本面資料寫入 `us_price_snapshots`；
      單一股票失敗不中斷其餘股票（比照 `market_scan.py:307-319`）
      （depends on: T005, T007）
- [X] T009 [P] `poc/kb-mcp/tests/test_us_stock_store.py`：schema 建立、
      CRUD、獨立 db 檔案隔離的基本測試
- [X] T010 [P] `poc/kb-mcp/tests/test_us_stock_scan.py`：mock price client，
      驗證單一股票失敗時其餘股票仍正常寫入（graceful degradation）
- [X] T011 在 `quickstart.md` 補上實際部署 `com.alphavibe.usstockscan.plist`
      的操作步驟（比照 `com.alphavibe.marketscan.plist` 的既有先例，
      **不**建立 repo 內的 plist 範本檔——這個 repo 從來沒有這類範本，
      plist 是直接手動建在使用者機器上）

**Checkpoint**：Foundation 完成，US1/US2/US3 可以開始（可平行）

---

## Phase 3: User Story 1 - 交易紀錄匯入與股價走勢對照 (P1) 🎯 MVP

**Goal**：使用者能把截圖交易變成看得懂進出場時機的股價圖表

**Independent Test**：把交易明細文字貼給 Claude → 確認存入 → 打開個股
詳情頁能看到股價線＋買賣點位標記

### Tests for User Story 1

- [X] T012 [P] [US1] `poc/kb-mcp/tests/test_us_trade_text_parser.py`——
      先寫測試（固定格式範例），此時應該 FAIL

### Implementation for User Story 1

- [X] T013 [P] [US1] 實作 `poc/kb-mcp/us_trade_text_parser.py`（正則表達式
      解析交易文字，比照 `trade_ledger_parser.py` 既有模式），讓 T012 通過
- [X] T014 [US1] 在 `us_stock_mcp_server.py` 實作 `parse_and_save_us_trade`
      工具（見 contracts/mcp-tools.md 工具一）（depends on: T013, T005）
- [X] T015 [P] [US1] 在 `us_stock_mcp_server.py` 實作 `get_us_trade_ledger`／
      `get_us_holdings`／`get_us_price_history` 三個工具（contracts 工具
      二/三/八）（depends on: T005）
- [X] T016 [US1] `app/routers/us_stocks.py` 新增 GET 端點：持股清單、交易
      列表、股價歷史（直接呼叫 `USStockStore`，不透過 MCP 協議，比照既有
      `app/` 直接 import `poc/kb-mcp/*.py` 的慣例）（depends on: T005）
- [X] T017 [US1] `web/src/pages/UsStockImport.jsx`——**只實作 STEP 2 核對
      確認畫面**（顯示 Claude 已解析出的待確認交易，供使用者修正/確認，
      confirm 後呼叫對應 API），STEP 1 上傳 UI 見本檔案開頭的範圍判斷
- [X] T018 [P] [US1] `web/src/pages/UsStockDetail.jsx` 的股價圖區塊——
      比照 `StockComboChart.jsx` 視覺風格（紅漲綠跌/紅買綠賣），資料源
      改接 T016 的端點
- [X] T019 [US1] `web/src/pages/UsStocks.jsx` landing 頁基本版（持股清單
      ＋現價＋漲跌；立場/監控狀態欄位留給 US2/US3 補上）
- [X] T020 [US1] `app/tests/test_smoke.py` 新增美股 router 的深度比對測試
      （比照既有模式，不只測 200，比對底層函式輸出）

**Checkpoint**：US1 應可獨立完整運作與驗證

---

## Phase 4: User Story 2 - 研究筆記與投資立場記錄 (P2)

**Goal**：使用者能保留跟 agent 討論出的投資立場，之後回顧不用重新翻對話

**Independent Test**：存一筆立場＋研究筆記 → 個股詳情頁看得到完整內容
（章節/引用來源/情境區間都不砍減）

### Implementation for User Story 2

- [X] T021 [P] [US2] 在 `us_stock_mcp_server.py` 實作 `save_us_stance`／
      `get_us_stance` 工具（contracts 工具四/五）（depends on: T005）
- [X] T022 [P] [US2] `app/routers/us_stocks.py` 新增 GET 端點：個股立場
      （depends on: T005）
- [X] T023 [US2] `web/src/components/UsStockResearchNote.jsx`——完整研究
      筆記渲染元件，比照 STND 既有卡片/字體/配色系統，**內容不得因版面
      密度砍減**（FR-009，這是 2026-09-04 對話中使用者明確否決過壓縮版
      的地方，見 `docs/spec-intake/us-stocks/` 的決策紀錄）
- [X] T024 [US2] `web/src/pages/UsStockDetail.jsx` 加入「投資立場」卡片，
      連結到 T023 的完整研究筆記元件（depends on: T023, T022）
- [X] T025 [P] [US2] `poc/kb-mcp/tests/test_us_stock_store.py` 補立場相關
      的 CRUD 測試

**Checkpoint**：US1 + US2 應可各自獨立運作

---

## Phase 5: User Story 3 - 關注條件監控與觸發推播 (P3)

**Goal**：追蹤股票觸及設定門檻時，使用者能主動被通知，不用自己盯盤

**Independent Test**：設定一個容易觸發的門檻 → 手動跑一次排程腳本 →
確認 landing 頁與詳情頁顯示「已觸發」、且收到 Telegram 推播

### Implementation for User Story 3

- [X] T026 [P] [US3] 在 `us_stock_mcp_server.py` 實作
      `save_us_watch_condition`／`get_us_watch_conditions` 工具（contracts
      工具六/七）（depends on: T005）
- [X] T027 [US3] 擴充 `us_stock_scan.py`：排程執行時比對每個監控條件，
      更新 `status`／`last_evaluated_at`（額度用盡時**不更新**這兩個欄位，
      見 data-model.md §3 狀態轉換規則），狀態轉為 `alert` 時呼叫既有
      Telegram 閘道（`function/stnd-gateway-web`）推播（depends on: T008, T026）
      ——**實作說明（2026-09-08）**：`function/stnd-gateway-web` 分支不在
      本分支工作目錄內，先實作為明確標記的 stub `notify_telegram()`，
      狀態轉換判斷邏輯（何時觸發/不觸發推播）完整實作並測試。**同日
      追加**：查證後發現真正的 Telegram bot 是完全獨立的專案
      `AI/telegram_gateway/`（不在任何 AlphaVibe 分支內），STND 既有整合
      模式（`function/stnd-gateway-web` 的 `gateway_monitor.py`）本來就是
      「獨立實作、不 import telegram_gateway，只共用設定值」——已比照
      同一慣例把 stub 換成真正呼叫 Telegram Bot API（`urllib` 直接打
      `sendMessage`，token 從共用的 `~/.config/stnd-gateway/.env` 讀取，
      不寫死進原始碼），不需要等那條分支合併
- [X] T028 [P] [US3] `app/routers/us_stocks.py` 新增監控條件的 CRUD 端點
      （depends on: T005）——GET/POST/DELETE 三個端點，並同步擴充
      `GET /api/us-stocks/watchlist` 為四表聯集完整版（T030 範圍）
- [X] T029 [US3] `web/src/pages/UsStockDetail.jsx` 加入「關注條件」卡片，
      三態 pill（未觸發/已觸發/資料不足）＋「未更新（無額度）」標記
      （depends on: T028）
- [X] T030 [US3] `web/src/pages/UsStocks.jsx` landing 頁補上監控觸發狀態
      欄位，完成完整版 landing 頁（depends on: T019, T028）
- [X] T031 [P] [US3] `poc/kb-mcp/tests/test_us_stock_scan.py` 補監控條件
      評估＋推播觸發的測試（mock Telegram 閘道呼叫，驗證額度用盡時「未
      更新（無額度）」與「資料不足」不會混淆——FR-017 是本次規劃最容易
      做錯的地方）

**Checkpoint**：US1/US2/US3 應可全部獨立運作，也能組合成完整體驗

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T032 [P] `docs/architecture.md` 分頁地圖補上「美股」分頁列
- [X] T033 [P] `CLAUDE.md`「STND 分頁與程式碼位置」表補上美股列
- [X] T034 逐項執行 `quickstart.md` 的「部署後驗收重點」（尤其美股資料
      完全碰不到台股既有表/工具這條，是 FR-015/016 的核心要求）
- [X] T035 [P] 確認 `web/src/components/AppShell.jsx` 的美股圖示（mockup
      用 globe 線稿佔位，實作時可維持或替換）

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup（Phase 1）：無相依，可立即開始
- Foundational（Phase 2）：依賴 Setup 完成，**阻擋所有 User Story**
- User Stories（Phase 3-5）：都依賴 Foundational 完成；US1 是 MVP 範圍，
  US2/US3 可平行於 US1 之後進行，彼此間沒有強制的完成順序，但 US3 的
  排程評估邏輯（T027）建在 US1 的排程基礎（T008）之上
- Polish（Phase 6）：依賴所有想要的 User Story 完成

### 跨 Story 的資料相依（非阻擋，但影響測試順序）

`us_stock_scan.py`（T008）先只做「抓資料寫入 us_price_snapshots」
（Foundational 範圍），US3 的 T027 才擴充「比對監控條件＋推播」——這樣
US1 不需要等 US3 的監控/推播邏輯做完就能先測（股價圖只需要
`us_price_snapshots` 有資料，不需要監控條件存在）。

---

## Parallel Example: User Story 1

```bash
# T012（測試）與 T013（實作對應）依序；以下可與其他 story 平行：
Task: "在 poc/kb-mcp/us_stock_mcp_server.py 實作 get_us_trade_ledger/get_us_holdings/get_us_price_history"
Task: "web/src/pages/UsStockDetail.jsx 的股價圖區塊"
```

---

## Implementation Strategy

### MVP First（只做 User Story 1）

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（**關鍵**——阻擋所有後續）
3. 完成 Phase 3 User Story 1
4. **停下來驗證**：獨立測試 User Story 1（截圖→匯入→股價圖）
5. 這時已經是可展示的 MVP：能記錄交易並看到進出場對照圖

### Incremental Delivery

1. Setup + Foundational → 地基完成
2. + User Story 1 → 獨立測試 → MVP 可展示
3. + User Story 2 → 獨立測試 → 展示（研究筆記功能）
4. + User Story 3 → 獨立測試 → 展示（監控推播功能，完整體驗）

---

## Notes

- `[P]` 任務＝不同檔案、無相依，可平行
- `[Story]` 標籤只出現在 User Story 專屬 phase（Setup/Foundational/Polish
  沒有）
- 每個 User Story 完工後都要能獨立驗證，不要等全部做完才第一次測試
- Commit 時機：每完成一個邏輯任務群組就 commit（比照本次 pre-spec/specify/
  clarify/plan 階段的做法，不要累積到最後一次性 commit）
- 避免：模糊任務、同檔案衝突、破壞 story 獨立性的跨 story 硬相依
