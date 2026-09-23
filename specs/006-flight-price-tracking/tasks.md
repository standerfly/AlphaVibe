# Tasks: 機票價格追蹤與通知

**Input**: Design documents from `/specs/006-flight-price-tracking/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: 包含測試任務。理由與 005 相同：專案規範要求「完成＝驗證過」，
且本功能的三個核心邏輯（排程選取、通知去重、過期防護）都是**不跑排程就
看不出對錯**的純判定，正是單元測試最能發揮的地方。範圍聚焦這三項，
不為覆蓋率而寫。

**Organization**: 依 user story 分組。本功能建在 005 之上，Setup 與
Foundational 因此很短。

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [ ] T001 確認 005 的基礎可用：執行 `.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"`，178 測試須全綠
- [ ] T002 [P] 確認通知模組可載入且在未設定時正確降級：執行 `.venv/bin/python3 -c "import sys; sys.path.insert(0,'poc/kb-mcp'); import notify; print(notify.send_telegram.__doc__)"`

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T003 在 `poc/kb-mcp/flight_store.py` 的 SCHEMA 新增 4 個欄位：`scan_frequency_days`（預設 7）、`last_notified_at`、`last_notified_price`、`last_notify_failed`。以 `ALTER TABLE ... ADD COLUMN` 逐欄新增並容忍「欄位已存在」，讓建表對新舊資料庫都成立（data-model.md「遷移」）
- [ ] T004 在 `poc/kb-mcp/flight_store.py` 的 `create_track()` 接受並驗證 `scan_frequency_days`（正整數），`_row_to_track()` 回傳新欄位
- [ ] T005 在 `poc/kb-mcp/flight_store.py` 新增 `update_track_frequency(track_id, days)` 與 `record_notification(track_id, price, ok)`，後者同時寫入 `last_notified_at`／`last_notified_price`／`last_notify_failed`
- [ ] T006 [P] 在 `poc/kb-mcp/tests/test_flight_store.py` 補上新欄位的測試：預設值、驗證規則、通知紀錄寫入、既有資料庫升級後欄位存在

**Checkpoint**: 資料層可儲存頻率與通知狀態

---

## Phase 3: User Story 1 - 不必手動重查就能追到降價 (Priority: P1) 🎯 MVP

**Goal**: 系統依設定頻率自動重掃，使用者打開分頁就是最新價格

**Independent Test**: 設定頻率後，排程到期時自動執行掃描並更新結果與時間戳，全程無需操作

- [ ] T007 [US1] 在 `poc/kb-mcp/flight_scan_service.py` 新增 `is_due(track, today)`：判斷「今天輪到」（`id % 7 == 今天星期幾`）且「週期已滿」（`last_success_at` 為空或距今已滿 `scan_frequency_days` 天）
- [ ] T008 [US1] 在 `poc/kb-mcp/flight_scan_service.py` 新增 `next_scan_date(track, today)`：從上次成功加一個週期，再往後找到第一個符合 `id % 7` 的日子。**這個規則只在此處定義**，API 與前端都不自行推算（contracts §2）
- [ ] T009 [US1] 建立 `poc/kb-mcp/flight_tracking_job.py`：`--data-dir` 參數（**不走環境變數防呆**，理由見 quickstart 坑 2）、`--dry-run`（只列出今天輪到誰、不查價不通知）、逐一對到期條件呼叫既有 `run_scan()`
- [ ] T010 [US1] 在 `flight_tracking_job.py` 處理配額不足與軟阻擋：沿用 `run_scan()` 的既有行為，不另建邏輯；每個條件的執行結果寫入 stdout 供 launchd log 記錄
- [ ] T011 [P] [US1] 在 `app/routers/flights.py` 的條件回應加入 `scan_frequency_days`／`next_scan_date`／`last_success_at`
- [ ] T012 [P] [US1] 在 `app/routers/flights.py` 新增 `PATCH /api/flights/tracks/{id}`：更新頻率、回傳重算後的 `next_scan_date`（contracts §3）
- [ ] T013 [P] [US1] 在 `web/src/pages/FlightTrackForm.jsx` 新增重掃頻率選項（每週／每兩週／每月），並說明為何不提供更高頻（速率上限）
- [ ] T014 [US1] 在 `web/src/pages/Flights.jsx` 的條件卡片顯示下次預定重掃與上次成功時間（FR-017），並提供調整頻率的入口
- [ ] T015 [P] [US1] 建立 `poc/kb-mcp/tests/test_flight_tracking.py`：`is_due` 的四種情境（今天輪到＋週期滿／輪到但未滿／沒輪到／從未成功過）、`next_scan_date` 的計算、多條件分散到不同日
- [ ] T016 [US1] 建立 `~/Library/LaunchAgents/com.alphavibe.flighttracking.plist`：每日觸發一次，比照 `com.alphavibe.usstockscan.plist` 的既有寫法，log 導向 `~/Library/Logs/alphavibe-flight-tracking.log`。**載入前先以 `--dry-run` 在 launchd 的乾淨環境驗證**（005 踩過：到點才發現路徑錯就白等一天）

**Checkpoint**: 自動重掃可運作，使用者不必手動觸發

---

## Phase 4: User Story 2 - 跌破目標價時主動通知 (Priority: P2)

**Goal**: 最低四段票價跌破目標價時主動通知，且不重複打擾

**Independent Test**: 設定高於當前價的目標價觸發重掃，確認收到含價格與連結的通知；再觸發一次確認不重複

- [ ] T017 [US2] 在 `poc/kb-mcp/flight_scan_service.py` 新增 `should_notify(track, lowest_price)`：目標價存在、`lowest_price <= target_price`、且（從未通知過 或 `lowest_price < last_notified_price`）。**不看接駁估價**（FR-007）
- [ ] T018 [US2] 在 `poc/kb-mcp/flight_scan_service.py` 新增 `build_notification(track, result)`：組出含條件名稱、四段票價、主行程起訖、外站與查價連結的訊息。連結用既有 `google_flights_url()` 構造（research.md §7）
- [ ] T019 [US2] 在 `flight_tracking_job.py` 接上通知：掃描完成後判定並呼叫 `notify.send_telegram()`，依回傳的 `(成功數, 錯誤)` 決定 `record_notification()` 的 `ok` 值。**通知失敗不重試掃描、不拋例外**（FR-011）
- [ ] T020 [P] [US2] 在 `app/routers/flights.py` 的條件回應加入 `notify` 區塊（`last_notified_at`／`last_notified_price`／`last_notify_failed`）
- [ ] T021 [P] [US2] 在 `web/src/pages/Flights.jsx` 顯示上次通知時間與價格；`last_notify_failed` 為真時標示「通知未送達」（FR-019）
- [ ] T022 [P] [US2] 在 `poc/kb-mcp/tests/test_flight_tracking.py` 補 `should_notify` 測試：達標首次通知、達標但未更低不重複、達標且更低再次通知、未設目標價不通知、**接駁價使總成本超過目標價時仍通知**（FR-007 的反向驗證）
- [ ] T023 [P] [US2] 在 `poc/kb-mcp/tests/test_flight_tracking.py` 補通知失敗的測試：`send_telegram` 回傳失敗時，掃描結果仍保存、`last_notify_failed` 為真、不拋例外

**Checkpoint**: 達標會通知且不重複打擾

---

## Phase 5: User Story 3 - 不因過期資料收到誤導的通知 (Priority: P3)

**Goal**: 連續失敗時標示過期，且不以過期價格觸發通知

**Independent Test**: 讓條件連續兩個週期失敗，確認標為過期且即使舊價達標也不通知

- [ ] T024 [US3] 修正 `poc/kb-mcp/flight_scan_service.py::derive_state()`：過期判定的週期長度改為跟著該條件的 `scan_frequency_days`，不再寫死 7 天（quickstart 坑 1；005 遺留）
- [ ] T025 [US3] 在 `flight_tracking_job.py` 的通知判定前檢查狀態：`stale` 時**不通知**（FR-014），並在 log 記錄跳過原因
- [ ] T026 [P] [US3] 在 `web/src/pages/Flights.jsx` 的過期標示補上「上次成功時間」，讓使用者知道資料多舊（FR-013）
- [ ] T027 [P] [US3] 在 `poc/kb-mcp/tests/test_flight_tracking.py` 補過期測試：連續兩週期未成功即為 stale、stale 時不通知（即使舊價達標）、下次成功後解除、**每月頻率的條件在第 15 天不得被誤判為過期**（T024 的反向驗證）
- [ ] T028 [P] [US3] 在 `poc/kb-mcp/tests/test_flight_tracking.py` 補「部分完成不更新 last_success_at」的測試（FR-015）——005 已實作此行為，這裡確保它在自動重掃路徑上同樣成立

**Checkpoint**: 三個 user story 全部完成

---

## Phase 6: Polish & Cross-Cutting

- [ ] T029 [P] 在 `app/tests/test_smoke.py` 補 PATCH 端點與新欄位的檢查（沿用既有的「與底層比對」深度檢查風格，非僅檢查 200）
- [ ] T030 [P] 更新 `CLAUDE.md` 與 `docs/architecture.md` 的機票分頁列，補上自動重掃與通知
- [ ] T031 完整回歸：`poc/kb-mcp/tests` 全套綠、smoke test 整體 PASS、前端 `npx vite build` 通過
- [ ] T032 以 `--dry-run` 實跑 `poc/kb-mcp/flight_tracking_job.py`，確認「今天輪到誰」的判定正確且不發出任何查詢或通知
- [ ] T033 ⏸ **待 PO 確認**：實際載入 `~/Library/LaunchAgents/com.alphavibe.flighttracking.plist` 並等待第一次自動執行——需跨日觀察，無法在單次工作階段內驗證

---

## Dependencies

```text
Phase 1 (Setup)
    ↓
Phase 2 (Foundational：資料表欄位)
    ↓
Phase 3 (US1, P1：自動重掃) ←── MVP
    ↓
Phase 4 (US2, P2：達標通知) ←── 依賴 US1 的排程執行
    ↓
Phase 5 (US3, P3：過期防護) ←── 依賴 US2 的通知路徑
    ↓
Phase 6 (Polish)
```

US2 與 US3 都在 US1 建立的排程流程上擴充。US1 單獨完成即有價值
（打開分頁就是最新的），US2 讓使用者連分頁都不必開，US3 是正確性保護。

---

## Parallel Opportunities

- **Phase 2**：T006（測試）可與 T003–T005 之後的任何任務平行
- **Phase 3**：T011／T012（API）、T013（表單）、T015（測試）三組互不相干
- **Phase 4**：T020／T021／T022／T023 分屬不同檔案，可全部平行
- **Phase 5**：T026／T027／T028 可平行
- **Phase 6**：T029／T030 可平行

---

## Implementation Strategy

**MVP = Phase 1 ＋ 2 ＋ 3（T001–T016）**——自動重掃可運作即已解決
「不可能天天手動重查」這個核心問題。

**風險最高的兩個任務**：
- **T024**（過期週期跟著頻率）：這是 005 遺留的寫死值。若漏改，
  「每月一次」的條件會在第 15 天被誤判為過期而停止通知，而使用者只會
  覺得「怎麼都沒通知」，不會意識到是誤判。T027 是專門的反向驗證。
- **T016**（launchd plist）：005 的經驗是「到點才發現路徑錯就白等一天」，
  因此要求載入前先在 launchd 的乾淨環境以 `--dry-run` 驗證。
