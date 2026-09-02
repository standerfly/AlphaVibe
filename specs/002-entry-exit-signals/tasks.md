---
description: 002-entry-exit-signals 的可執行任務清單
---

# Tasks: 進出場訊號層（門檻、背離偵測與主動提醒）

**Branch**: `002-entry-exit-signals` | **Date**: 2026-09-03
**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/mcp-tools.md](contracts/mcp-tools.md)、[quickstart.md](quickstart.md)

## Format: `[ID] [P?] [Story] Description`

- `[P]`＝可與同區塊其他 `[P]` 任務平行（不同檔案、無未完成依賴）
- `[US1]`~`[US5]`＝對應 spec.md 的使用者故事；Setup／Foundational／Polish 不掛標籤

## Path Conventions

商業邏輯在 `poc/kb-mcp/`，測試在 `poc/kb-mcp/tests/`，HTTP 轉接在
`app/routers/`，前端在 `web/src/pages/`。

## ⚠️ 全域紅線（每個任務都適用）

- **零新增外部呼叫**（research.md R-002）：三種新訊號的資料全部來自既有
  已載入或已快取的來源。T028 是專門驗證這件事的獨立任務——階段A 就是
  在「從參數語意推論呼叫次數」上出錯，害正式排程慢了 29 分鐘。
- **絕不對正式庫 `poc/data/` 寫入**。測試一律 `tempfile.mkdtemp()` ＋
  `KBStore(tmp)`、tearDown `shutil.rmtree`。需要讀正式資料驗證時用
  `sqlite3 "file:...?mode=ro"` 唯讀連線。
- **不動這些檔案**：`pnl.py`、`price_position.py`（階段A 產物，只讀不改）、
  `holdings_sync.py`、`screener.py`、`twse_price_client.py`、`finmind_client.py`。
- Python 3.9 相容；`poc/kb-mcp/` 零外部依賴；註解與文件繁體中文。
- 遇到「改了程式碼但行為沒變」先查 `模組.__cached__`——本機 pyc 快取在
  `~/Library/Caches/com.apple.python/`（CLAUDE.md 2026-09-03 教訓）。

---

## Phase 1: Setup

- [ ] T001 執行 `python3 -m unittest discover -s poc/kb-mcp/tests` 記錄改動前
      基準（階段A 完成後應為 688 tests 全綠），作為 T037 回歸比對的基準

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T002 在 `poc/kb-mcp/kb_store.py` 新增 `exit_thresholds` 表
      （`CREATE TABLE IF NOT EXISTS`，schema 見 data-model.md）與 4 個方法：
      `save_exit_threshold`／`get_exit_threshold`／`get_all_exit_thresholds`／
      `get_exit_threshold_history`。**append-only、`max(id) GROUP BY code`
      取最新**（比照 `stances`，非 `position_plans` 的覆寫式）；驗證規則：
      兩門檻至少給一個、值需可轉 float 且 > 0、兩者都給時
      `stop_loss < take_profit`，違反則 raise（FR-001）
- [ ] T003 [P] 在 `poc/kb-mcp/tests/test_kb.py` 寫 `exit_thresholds` 存取測試：
      append-only 保留歷史、`get_exit_threshold` 從未設定回 `None`、
      驗證規則各自 raise（FR-001）
- [ ] T004 [P] 在 `poc/kb-mcp/module_d_scheduler.py` 的輸出加上起訖時間戳與
      逐階段耗時（research.md R-009）。**必須先於 US4 完成**——目前 log
      完全沒有時間戳，沒有它 FR-012 的耗時比對沒有量測基礎

---

## Phase 3: User Story 1 - 門檻設定與監控 (Priority: P1) 🎯 MVP

**Goal**：PO 與 Claude 討論後為持股設定停損停利門檻，系統記住並持續比對現價。

**Independent Test**：設定門檻後用高於/低於門檻的現價驗證觸發與未觸發；
對未設定門檻的持股驗證回傳 `not_set` 而非任何安全語意。

### Tests for User Story 1

- [ ] T005 [P] [US1] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫觸發判斷測試：
      現價跌破停損回 `triggered_stop_loss`、漲過停利回 `triggered_take_profit`、
      區間內回 `within_range`，並驗證 `distance_pct` 正負號正確（FR-002）
- [ ] T006 [P] [US1] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫 `not_set`
      防呆測試：未設定門檻時 `status == "not_set"`、`stop_loss`／`take_profit`
      **必須是 None**、且 `status != "within_range"`——不得被當成安全（FR-003）
- [ ] T007 [P] [US1] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫無現價測試：
      有門檻但查無現價回 `no_price`，不得誤判為未觸發（FR-002）
- [ ] T008 [P] [US1] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫批次測試：
      混合 `not_set`／`within_range`／已觸發的多檔，驗證各自狀態與 summary
      計數正確，單檔問題不影響整批（FR-002、FR-011）

### Implementation for User Story 1

- [ ] T009 [US1] 建立 `poc/kb-mcp/exit_signals.py`，實作
      `evaluate_threshold(code, threshold, prices)`：純函式不碰 I/O，
      status 判定順序依 data-model.md（`not_set` → `no_price` →
      `triggered_stop_loss` → `triggered_take_profit` → `within_range`）
      （FR-002、FR-003）
- [ ] T010 [US1] 在 `poc/kb-mcp/exit_signals.py` 新增
      `evaluate_all_thresholds(thresholds, prices)`：逐檔獨立 try 保護，
      產出 summary 各狀態計數（FR-002、FR-011）
- [ ] T011 [US1] 在 `poc/kb-mcp/server.py` 的 `TOOLS` 新增
      `save_exit_threshold`（寫入）與 `get_exit_threshold`（唯讀）定義，
      inputSchema 見 contracts/mcp-tools.md（FR-004）
- [ ] T012 [US1] 在 `poc/kb-mcp/server.py` 的 dispatch 區塊新增兩個分支；
      `get_exit_threshold` 省略 code 時走全量路徑（FR-004）
- [ ] T013 [US1] 在 `poc/kb-mcp/server_readonly.py` 的 `READONLY_TOOLS`
      **只加 `get_exit_threshold`**；`save_exit_threshold` 是寫入工具，
      **不得加入**（FR-004）
- [ ] T014 [US1] 擴充 `poc/kb-mcp/tests/test_pnl.py::ToolRegistrationTest`：
      涵蓋兩個新工具的三處註冊，並新增**反向斷言**——
      `assertNotIn("save_exit_threshold", server_readonly.READONLY_TOOLS)`；
      工具總數斷言 45→47、唯讀白名單 27→28（FR-004）

**Checkpoint**：US1 完成即可用——PO 能在對話中設門檻並查觸發狀態。

---

## Phase 4: User Story 2 - 背離偵測 (Priority: P2)

**Goal**：偵測營收趨勢與股價位置的背離，資料不足時明確說不知道。

**Independent Test**：用構造的資料驗證兩個方向的背離與 `aligned`；
用單邊資料不足驗證回 `insufficient` 而非單憑一邊下結論。

### Tests for User Story 2

- [ ] T015 [P] [US2] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫
      `revenue_trend` 測試：上升/下降/持平/樣本不足四種情況，並驗證
      `periods_used` 不超過既有資料窗口可得的期數（FR-007）
- [ ] T016 [P] [US2] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫背離測試：
      營收上升＋股價低百分位回 `fundamentals_ahead`、營收下降＋股價高
      百分位回 `price_ahead`、其餘回 `aligned`，且 `basis` 同時含兩邊數字
      （FR-005）
- [ ] T017 [P] [US2] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫資料不足測試：
      營收或股價任一邊不足即回 `insufficient`，**不得**單憑一邊下結論
      （FR-006）

### Implementation for User Story 2

- [ ] T018 [US2] 在 `poc/kb-mcp/exit_signals.py` 實作
      `revenue_trend(values, periods=6)`：斜率方向＋最新值相對窗口中位數
      的位置；**不新增任何外部呼叫**，只吃既有 `fetch_revenue_yoy()` 的
      結果（FR-007）
- [ ] T019 [US2] 在 `poc/kb-mcp/exit_signals.py` 實作
      `detect_divergence(code, revenue_values, price_position_result)`：
      高低檔門檻 30／70 百分位定義為模組常數，不散落在判斷式（FR-005、FR-006）
- [ ] T020 [US2] 修改 `poc/kb-mcp/review_engine.py` 的 `_growth_deceleration`
      委派給 `exit_signals.revenue_trend`，**輸出結構與呼叫端介面完全不變**
      （仍回 `{"flagged", "detail", ...}`）（FR-007）
- [ ] T021 [US2] **改動前後的正式資料逐檔比對（獨立任務，不可併入 T020）**：
      用 `git archive` 匯出改動前版本到暫存目錄，兩版對同一批正式資料
      （**唯讀連線**）跑 `_growth_deceleration`，列出哪些標的的 flagged
      結果改變、變化是否合理，結果寫回 `specs/002-entry-exit-signals/research.md`
      R-004。**不可只跑單元測試就宣稱完成**（FR-007）

---

## Phase 5: User Story 3 - 觸發時的調整建議 (Priority: P2)

**Goal**：訊號觸發時一併給出這檔可以怎麼調整，且建議產不出來時訊號本身
不被吞掉。

**Independent Test**：對已觸發標的驗證回傳含具體選項；對資料不足情況
驗證訊號仍在、建議欄位標示資料不足。

### Tests for User Story 3

- [ ] T022 [P] [US3] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫建議測試：
      觸發停損/停利/背離時各自產出可選調整方向與依據；資料不足時
      **訊號仍照常回傳**、建議欄位標示資料不足（FR-008、FR-009）

### Implementation for User Story 3

- [ ] T023 [US3] 在 `poc/kb-mcp/exit_signals.py` 實作
      `build_suggestion(signal)`：依訊號類型產出調整選項與依據，
      範圍限於該檔持股，**不得**呼叫任何選股或市場掃描邏輯（FR-008）
- [ ] T024 [US3] 在 `poc/kb-mcp/exit_signals.py` 實作洗版控制：
      **只有實際觸發的訊號才填 `suggested_action`**，未設定門檻／未觸發／
      資料不足一律不填（research.md R-006——首頁「今日重點」的篩選條件
      就是 `suggested_action is not None`，全填會灌爆）（FR-008）

---

## Phase 6: User Story 4 - 訊號自動出現 (Priority: P3)

**Goal**：新訊號併入既有每日流程，PO 打開頁面就看得到，且不拖慢流程、
不影響既有檢查。

**Independent Test**：在測試環境跑一次完整流程，驗證新訊號與既有結果
一起產生、`stances` 筆數不變、既有檢查項目數量不變。

### Tests for User Story 4

- [ ] T025 [P] [US4] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫
      **不寫入 stances** 的測試：跑完含新訊號的檢視流程後，
      `stances` 表筆數與跑之前完全相同（FR-013）
- [ ] T026 [P] [US4] 在 `poc/kb-mcp/tests/test_exit_signals.py` 寫失敗隔離
      測試：注入例外讓新訊號計算失敗，驗證既有通用層/策略層/老芋頭層
      檢查照常完成、結果照常寫入（FR-011）

### Implementation for User Story 4

- [ ] T027 [US4] 修改 `poc/kb-mcp/review_engine.py` 的 `run_module_d_review`：
      新增門檻與背離兩類 items，`trigger_label` 用 `通用層／停損停利`、
      `通用層／背離`；每類各自 try 包住不影響既有項目；**不呼叫
      `auto_record_findings`**（FR-010、FR-011、FR-013）
- [ ] T028 [US4] **外部呼叫次數實測（獨立任務，本階段最高風險項）**：
      攔截 `twse_price_client._throttled_get` 與 finmind 的請求函式，
      對同一批標的分別在「關閉新訊號」與「開啟新訊號」下執行，
      **兩者呼叫次數必須完全相同**。方法見 quickstart.md「FR-012 的必做
      實測」。實測數字寫回 research.md R-002。不接受從參數語意推論
      ——階段A 就是這樣錯的（FR-012）
- [ ] T029 [US4] 用 T004 補上的時間戳，在測試環境跑一次完整流程並與
      基準線（39 檔 1097 秒）比對，記錄增幅；若增幅超出「本機計算應有的
      毫秒級」，回頭查 T028 的假設哪裡不成立（FR-012）

---

## Phase 7: User Story 5 - 頁面損益口徑一致 (Priority: P3)

**Goal**：頁面同時顯示 FIFO 與加權平均估算，各自標明口徑、視覺可區分。

**Independent Test**：對 FIFO 可算與不可算的兩種標的，分別驗證頁面呈現；
數字與 `get_position_pnl` 一致。

### Tests for User Story 5

- [ ] T030 [P] [US5] 在 `poc/kb-mcp/tests/test_report.py` 寫渲染測試：
      FIFO 可算時顯示 FIFO 數字＋口徑標籤；`history_incomplete` 時顯示
      「FIFO 無法計算」＋加權平均估算值＋其口徑標籤。**斷言要用渲染形式**
      （帶 `class="` 前綴或帶標籤），不可用裸字串——CSS 常數內嵌在每個
      頁面，裸字串會命中樣式定義（CLAUDE.md 2026-08-19 教訓）（FR-014、FR-015）

### Implementation for User Story 5

- [ ] T031 [US5] 修改 `poc/kb-mcp/report.py` 的 `_chart_stats_html`
      （約 1922-1942 行）支援兩種口徑並存與標籤；呼叫處
      （`_holdings_card_html`，約 1985/1992 行）傳入 FIFO 結果。
      走勢圖均價虛線維持沿用估算值不動（FR-014、FR-015）
- [ ] T032 [US5] 修改 `app/routers/stock_detail.py` 的 holdings 區塊
      （約 188-206 行）：新增 `fifo` 與 `cost_method_label` 欄位，
      **保留既有 `avg_cost`／`pnl_pct` 不變**以維持向後相容（FR-014）
- [ ] T033 [US5] 修改 `web/src/pages/StockDetail.jsx`（約 299 行附近）
      呈現兩種口徑，視覺上可區分（FR-015）
- [ ] T034 [US5] `cd web && npm run build`，並重啟正式服務
      `launchctl kickstart -k gui/$(id -u)/com.alphavibe.reportserver`，
      用 `curl -s http://127.0.0.1:8080/api/healthz` 確認存活後，
      實際檢視一檔 FIFO 可算（例 2308）與一檔不可算（例 6257）的頁面
      ——**改 `report.py` 不重啟不會生效**（FR-014、FR-015）

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T035 [P] 在 `poc/kb-mcp/tests/test_traceability.py` 登記 FR-001~FR-015
      的需求↔實作↔測試對照，並更新工具數斷言 45→47
- [ ] T036 [P] 修正三處排程時間註解不一致：實際是 17:00（plist），但
      `poc/kb-mcp/review_engine.py:834` 寫 18:00、`poc/kb-mcp/server.py:600`
      寫 02:00（research.md R-009）
- [ ] T037 執行完整回歸 `python3 -m unittest discover -s poc/kb-mcp/tests`，
      與 T001 基準（688）比對，應為 688 ＋ 本次新增數且 0 失敗
- [ ] T038 依 `~/.claude/rules/10-model-dispatch.md` 第 6 節「驗證不自驗」，
      派 fresh-context agent 對照 spec.md 的 15 條 FR 逐條驗收。驗收 prompt
      **必須包含**：(a) 外部呼叫次數的獨立實測 (b) `save_exit_threshold`
      不得出現在唯讀白名單的反向檢查 (c) 正式庫未被寫入的確認
      (d) `stances` 筆數未增加的確認。**不由實作者自行宣告完成**

---

## Dependencies & Execution Order

```
Phase 1 (T001 基準)
  └─> Phase 2 (T002/T003 門檻表、T004 排程時間戳)
        ├─> Phase 3 US1 (T005–T014)  ← MVP，可獨立交付
        ├─> Phase 4 US2 (T015–T021)  ← 不依賴 US1，可平行
        │     └─> Phase 5 US3 (T022–T024)  ← 需要 US1/US2 的訊號輸出
        │           └─> Phase 6 US4 (T025–T029)  ← 需要全部訊號才能整合進流程
        └─> Phase 7 US5 (T030–T034)  ← 與訊號無關，隨時可做
              └─> Phase 8 Polish (T035–T038)
```

### User Story Dependencies

- **US1**：只依賴 T002（門檻表）。完成即可獨立交付。
- **US2**：只依賴 T002 以外的東西都沒有——與 US1 完全獨立，可平行。
- **US3**：依賴 US1 與 US2 的訊號輸出（要有訊號才能給建議）。
- **US4**：依賴 US1~US3 全部（整合進流程需要全部訊號就位），且
  **T004 必須先完成**（否則 T029 無從量測）。
- **US5**：與訊號完全無關（動的是頁面損益顯示），可與任何階段平行。

### Parallel Opportunities

- **US1 與 US2 整個階段可平行**（不同函式、同一新檔案 `exit_signals.py`
  的不同區塊——建議先後寫避免衝突，或分兩人各自完成後合併）
- **US5 可與所有訊號工作平行**（動的是 `report.py`／`app/`／`web/`）
- Polish 的 T035／T036 互為不同檔案，可平行

## Implementation Strategy

**MVP ＝ Phase 1 + 2 + 3（US1）**：完成 T001–T014 即可在對話中設門檻並
查觸發狀態，這是階段B 最核心的價值。

US2~US5 為增量。**T028（外部呼叫次數實測）與 T038（獨立驗收）不可省略**
——前者是階段A 教訓的直接防護，後者是 repo 的既有制度要求。

## 任務統計

- 總任務數：**38**
- Setup 1／Foundational 3／US1 10／US2 7／US3 3／US4 5／US5 5／Polish 4
- 標註 `[P]` 可平行：13
