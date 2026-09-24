# Tasks: 單純來回機票搜尋

**Input**: Design documents from `/specs/008-roundtrip-search/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、
contracts/roundtrip-api.md、quickstart.md（皆已完成）

**Tests**: 本 feature 新增獨立資料表與端點，不涉及既有生產資料的
破壞性異動（與 007 不同），測試任務納入但風險等級較低——比照
005、006、007 的既有慣例，仍全部納入不視為選配。

**Organization**: 依 spec.md 的 4 個 User Story（P1 多目的地比價核心
能力、P2 偏好轉機城市、P2 通知標示候選目的地、P3 組合數上限守衛）
分階段，各自可獨立測試與交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行進行（不同檔案、不互相依賴）
- **[Story]**：所屬 User Story（US1／US2／US3／US4）
- 每個任務都附確切檔案路徑

---

## Phase 1: Setup

**Purpose**：確認起點乾淨、驗證最關鍵的技術假設

- [ ] T001 執行 `.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"`，確認目前 264 個機票測試全綠（基準線）
- [ ] T002 **驗證 scraper 對「2 段來回」頁面的相容性**（research.md §1「尚待驗證」）：用 `flight_search.google_flights_url()` 手動組一個 2 段的來回網址（例如 TPE→AOJ 去程＋AOJ→TPE 回程），透過 `scrape_itineraries()` 或直接執行 `scraper/flight_scraper.js` 對該網址查價，確認能正確抓到價格、且 `isMultiCity` 判斷邏輯正確落入「非多城市」分支。**這是本 feature 風險最高的假設，必須在其他任務開始前驗證**——若不相容，需要回頭修改 scraper 而非在 US1 階段才發現

**Checkpoint**：核心技術假設（scraper 相容性）已驗證，可以安心動工

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**：新資料表與基礎 CRUD，四個 User Story 都建立在這之上

**⚠️ CRITICAL**：本階段完成前，User Story 不可動工

- [ ] T003 在 `poc/kb-mcp/flight_store.py` 的 `SCHEMA` 新增
      `roundtrip_track`／`roundtrip_scan_result` 兩張表（`CREATE TABLE
      IF NOT EXISTS`，全新表不需要 `_migrate()` 的 `ALTER TABLE` 路徑），
      含唯一索引 `idx_roundtrip_result_combo`（data-model.md）
- [ ] T004 在 `poc/kb-mcp/flight_store.py` 新增
      `create_roundtrip_track(destinations, window_start, window_end,
      trip_days_min, trip_days_max, hub="TPE", preferred_transit=None,
      name=None, samples_per_month=2, target_price=None,
      scan_frequency_days=7)`：驗證規則比照既有 `create_track()`（每個
      候選目的地機場代碼驗證、天數區間驗證、window 驗證），
      `preferred_transit` 為選填的機場代碼（`None` 或合法 3 碼代碼）
- [ ] T005 在 `poc/kb-mcp/flight_store.py` 新增 `_row_to_roundtrip_track()`
      列轉換函式，回傳形狀含 `track_type: "roundtrip"` 欄位（contracts/roundtrip-api.md §2）
- [ ] T006 [P] 在 `poc/kb-mcp/flight_store.py` 新增
      `list_roundtrip_tracks()`／`get_roundtrip_track(id)`／
      `delete_roundtrip_track(id)`，行為比照既有四段票對應方法
- [ ] T007 [P] 在 `poc/kb-mcp/flight_store.py` 新增
      `upsert_roundtrip_result()`／`list_roundtrip_results(track_id)`／
      `roundtrip_lowest_result(track_id)`／`count_roundtrip_results(track_id)`，
      `roundtrip_lowest_result()` 回傳需含 `destination` 欄位（data-model.md
      「與既有機制的相容性」表）
- [ ] T008 [P] 在 `poc/kb-mcp/flight_store.py` 新增
      `record_roundtrip_notification(track_id, price, ok, when=None)`，
      邏輯比照既有 `record_notification()`，寫入 `roundtrip_track` 的
      通知欄位
- [ ] T009 [P] 在 `poc/kb-mcp/tests/test_flight_store.py` 補上
      T003-T008 的測試：schema 建表、`create_roundtrip_track()` 驗證
      規則（候選目的地為空拒絕、單一機場代碼錯誤拒絕、天數區間規則同
      007、`preferred_transit` 選填）、CRUD round-trip、
      `roundtrip_lowest_result()` 跨候選目的地正確取最低價

**Checkpoint**：新資料表與 CRUD 就緒，四個 User Story 可以動工

---

## Phase 3: User Story 1 - 建立單純來回條件並取得多目的地比價結果 (Priority: P1) 🎯 MVP

**Goal**：PO 在同一個機票分頁建立單純來回條件，可填多個候選目的地，
系統展開天數區間內的組合各自查價，結果標示對應的候選目的地

**Independent Test**：建立一個候選目的地 2 個以上、天數區間 3～7 天的
單純來回條件，觸發掃描後，結果中至少出現 2 個不同候選目的地的比價
結果，且能分辨每筆對應哪個目的地

- [ ] T010 [US1] 在 `poc/kb-mcp/flight_scan_service.py` 新增
      `expand_roundtrip_track(track)`：對每個候選目的地 × 天數區間內
      每個天數值，呼叫 `fs.sample_dates()` 展開組合（重用 007 的天數
      迴圈模式，見 `expand_track()`）；本任務**只處理未指定
      `preferred_transit` 的情境**（2 段來回，US2 再擴充轉機情境）；
      回傳的每個 itinerary 含 `destination` 欄位
- [ ] T011 [US1] 在 `poc/kb-mcp/tests/test_flight_scan_service.py`
      補上 `expand_roundtrip_track()` 測試：多候選目的地正確展開、
      單一候選目的地也能正常運作（spec.md Edge Cases）、天數區間
      退化為單一值時行為正確、每筆 itinerary 的 `destination` 對得上
- [ ] T012 [US1] 在 `app/routers/flights.py` 新增
      `POST /api/flights/tracks/roundtrip`（contracts/roundtrip-api.md
      §1）：Pydantic 請求模型、呼叫 `store.create_roundtrip_track()`，
      驗證失敗回 400（本任務**不含**組合數上限檢查，US4 再加）
- [ ] T013 [US1] 在 `app/routers/flights.py` 新增
      `GET /api/flights/tracks/roundtrip/{id}/results`
      （contracts/roundtrip-api.md §4）：回應含 `state`／`progress`／
      `quota`／`results`（含 `destination`）／`skipped`／`notify`／
      `next_scan_date`；`links.round_trip` 用既有 `google_flights_url()`
      組 2 段網址
- [ ] T014 [US1] 在 `app/routers/flights.py` 修改
      `GET /api/flights/tracks`：合併 `store.list_tracks()` 與
      `store.list_roundtrip_tracks()` 的摘要，每筆加上 `track_type`
      欄位（contracts/roundtrip-api.md §2）；單純來回的 `lowest` 摘要
      額外含 `destination` 欄位
- [ ] T015 [US1] 在 `app/routers/flights.py` 新增
      `DELETE /api/flights/tracks/roundtrip/{id}`（contracts/roundtrip-api.md
      §5），行為比照既有四段票刪除端點
- [ ] T016 [US1] 在 `app/routers/flights.py` 新增
      `POST /api/flights/tracks/roundtrip/{id}/scan`（contracts/roundtrip-api.md
      §3）：背景任務比照既有 `_run_scan_background()` 模式，**不使用
      request-scoped store 依賴**（沿用既有坑 1 的教訓，見
      `specs/005-flight-scan-page/quickstart.md`）
- [ ] T017 [P] [US1] 在 `web/src/pages/FlightTrackForm.jsx` 新增
      單純來回建立表單：行程類型切換（四段票／單純來回）、候選目的地
      多選輸入、天數區間（沿用 007 的兩輸入框模式）、出發區間
- [ ] T018 [P] [US1] 在 `web/src/pages/Flights.jsx` 新增類型切換 UI；
      單純來回卡片顯示候選目的地清單、最低價與對應目的地（沿用既有
      `gap_to_target` 顯示模式）；依 `track_type` 決定要打
      `/api/flights/tracks/{id}/...` 還是
      `/api/flights/tracks/roundtrip/{id}/...`（quickstart.md 坑 1）
- [ ] T019 [US1] 在 `app/tests/test_smoke.py` 新增單純來回的深度比對
      測試：建立條件→與底層 `expand_roundtrip_track()` 比對組合數→
      觸發掃描→查詢結果，沿用既有「與底層比對」深度檢查風格

**Checkpoint**：User Story 1 完整可用——PO 可建立單純來回條件並取得
跨候選目的地比價結果

---

## Phase 4: User Story 2 - 指定偏好轉機城市 (Priority: P2)

**Goal**：PO 可為單純來回條件選擇性指定偏好轉機城市，查詢結果反映
該偏好；未指定時交由 Google Flights 自動決定

**Independent Test**：建立一個指定偏好轉機城市的單純來回條件，查詢
結果的行程確實經過指定城市轉機

- [ ] T020 [US2] 擴充 `poc/kb-mcp/flight_scan_service.py` 的
      `expand_roundtrip_track()`：當 `track["preferred_transit"]` 有值
      時，組成 4 段行程（TPE→轉機、轉機→目的地、目的地→轉機、
      轉機→TPE）而非 2 段（research.md §1，`google_flights_url()`
      依段數自動判斷 trip type，本任務不需要修改該函式本身）
- [ ] T021 [US2] 在 `poc/kb-mcp/tests/test_flight_scan_service.py`
      補上測試：指定 `preferred_transit` 時產生 4 段 legs 且轉機城市
      正確；未指定時產生 2 段；4 段的 trip type 應落入
      `google_flights_url()` 既有的多城市編碼分支（可用既有的
      `_pb_bytes`／protobuf 解碼輔助或直接檢查 legs 數量作為代理驗證）
- [ ] T022 [US2] 在 `app/tests/test_smoke.py` 新增指定 `preferred_transit`
      建立單純來回條件的測試：確認欄位正確持久化與回傳（真實查價驗證
      轉機城市是否生效，留給實作階段用真實瀏覽器人工核對一次，不強制
      進自動化測試——沿用 quickstart.md 對「尚待驗證」項目的處理方式）

**Checkpoint**：User Story 2 完整可用——PO 可指定偏好轉機城市

---

## Phase 5: User Story 3 - 達標與現況通知標示觸發的候選目的地 (Priority: P2)

**Goal**：單純來回條件沿用既有目標價達標通知與現況通知機制，通知
內容明確標示觸發的候選目的地

**Independent Test**：讓一個多目的地單純來回條件的某次重掃後最低價
跌破目標價，確認收到的通知內容包含觸發的候選目的地名稱

- [ ] T023 [US3] 在 `poc/kb-mcp/flight_scan_service.py` 新增
      `build_roundtrip_notification(track, lowest_row)`／
      `build_roundtrip_status_notification(track, lowest_row)`：訊息
      含目的地名稱、來回票價、出發回程日期、`google_flights_url()`
      連結（2 段或 4 段依 `preferred_transit` 而定）；不含四段票專屬
      的「第1段不可 no-show」提醒（data-model.md「不重用」表）
- [ ] T024 [US3] 在 `poc/kb-mcp/flight_tracking_job.py` 的排程迴圈
      擴充：`due_tracks()` 同時對 `store.list_tracks()` 與
      `store.list_roundtrip_tracks()` 兩組資料各自套用
      `is_due()`（research.md §3，函式本身不修改，呼叫端擴充）；單純
      來回條件的處理分支呼叫 `expand_roundtrip_track()`／
      `roundtrip_lowest_result()`／`should_notify()`／
      `should_notify_status()`／`build_roundtrip_notification()`／
      `record_roundtrip_notification()`
- [ ] T025 [US3] 在 `poc/kb-mcp/tests/test_flight_tracking.py` 補上
      測試：`build_roundtrip_notification()` 內容含候選目的地名稱；
      排程迴圈正確涵蓋兩種類型的到期條件；多候選目的地情境下通知
      判定基準是全部候選目的地中的最低價（spec.md User Story 3
      情境 3／Edge Cases）
- [ ] T026 [US3] 在 `poc/kb-mcp/tests/test_flight_scan_service.py`
      補上 `roundtrip_lowest_result()` 的跨候選目的地測試（若 T009
      尚未涵蓋，此處補齊邊界情況：多個候選目的地平手時的行為，
      spec.md Edge Cases）

**Checkpoint**：User Story 3 完整可用——通知內容明確標示候選目的地

---

## Phase 6: User Story 4 - 組合數超標時拒絕建立條件 (Priority: P3)

**Goal**：建立單純來回條件時，若組合數超過上限，系統拒絕建立並說明
組合數與上限，避免吃光整小時查詢配額

**Independent Test**：建立一個候選目的地數與天數區間都偏寬、組合數
超過上限的單純來回條件，系統拒絕建立；資料庫未寫入這筆條件

- [ ] T027 [US4] 在 `app/routers/flights.py` 的
      `POST /api/flights/tracks/roundtrip`（T012）建立前，用既有
      `svc.combination_count()`（`num_targets` 傳候選目的地數量）
      與 `svc.MAX_COMBINATIONS_PER_TRACK` 檢查，超過則回 400 並說明
      組合數與上限（沿用 007 四段票端點的既有模式，程式碼結構可
      參考但不強制抽成共用函式——兩個 HTTP handler 各自獨立呼叫）
- [ ] T028 [P] [US4] 在 `app/tests/test_smoke.py` 新增單純來回組合數
      超標的測試：POST 一個組合數超過 60 的單純來回條件，確認回 400
      且訊息含組合數與上限；確認未寫入資料庫（沿用 007 T024 的測試
      模式）

**Checkpoint**：四個 User Story 全數完成，MVP（P1）＋轉機偏好（P2）
＋通知標示（P2）＋安全守衛（P3）皆已實作並測試覆蓋

---

## Phase 7: Polish & Cross-Cutting

**Purpose**：完整回歸、文件同步、正式環境部署

- [ ] T029 完整回歸：`poc/kb-mcp/tests` 全套綠、`npx vite build`
      （`web/`）通過、smoke test 乾淨測試庫整體 PASS
- [ ] T030 [P] 更新 `CLAUDE.md`／`docs/architecture.md` 的機票分頁列，
      補上單純來回搜尋已上線的現況
- [ ] T031 更新
      `docs/spec-intake/flight-roundtrip-search/handoff-checklist.md`，
      標記 `roundtrip-search` 包已完成——這是整個
      `flight-roundtrip-search` pre-spec 工作區的最後一包，可視情況
      將 pre-spec 全域索引（`docs/spec-intake/index.md`）狀態更新為
      `Handoff Complete`
- [ ] T032 **⏸ 待 PO 確認的正式環境部署**：合併程式碼到
      `function/alphavibe` → 重啟 `com.alphavibe.reportserver`（新表
      由 `_migrate()`／`CREATE TABLE IF NOT EXISTS` 自動建立，不需要
      額外遷移腳本，quickstart.md「正式環境部署順序」）→ 用 `curl`
      建立一個真實單純來回條件、觸發掃描、確認端到端運作 → 確認既有
      四段票條件（id=9）在合併後仍正常運作（清單合併邏輯是共用程式碼，
      需要實際驗證不影響既有行為）

---

## Dependencies & Execution Order

```text
Phase 1 (Setup：scraper 相容性驗證，風險最高，最先做)
   ↓
Phase 2 (Foundational：新資料表與 CRUD)
   ↓
Phase 3 (US1，P1，MVP：核心查詢與展示能力)
   ↓
   ├── Phase 4 (US2，P2：轉機偏好，擴充 US1 的展開邏輯)
   ├── Phase 5 (US3，P2：通知，依賴 US1 的 lowest_result 與展開邏輯)
   └── Phase 6 (US4，P3：組合數守衛，依賴 US1 的建立端點)
   ↓
Phase 7 (Polish：正式環境部署依賴 Phase 3-6 全數完成)
```

**User Story 間的實際耦合**：US2（T020）直接修改 US1（T010）建立的
`expand_roundtrip_track()`，不是平行檔案關係，必須先完成 US1 才能
動工；US3（T024）的排程整合與 US4（T027）的建立端點檢查都依賴 US1
已完成的基礎（`roundtrip_lowest_result()`／建立端點本身），但 US3
與 US4 彼此互不依賴，可平行進行。

## Parallel Execution Examples

Phase 2 完成後，以下任務可同時進行（不同檔案、無相互依賴）：

```text
T006 [P] list/get/delete_roundtrip_track()
T007 [P] upsert/list/lowest_result 系列
T008 [P] record_roundtrip_notification()
T009 [P] test_flight_store.py 的新測試
```

Phase 3（US1）完成後，US3 與 US4 可平行推進：

```text
T023-T026 [US3] 通知相關（flight_scan_service.py／flight_tracking_job.py）
T027-T028 [US4] 組合數守衛（app/routers/flights.py，不同函式範圍）
```

## Implementation Strategy

**MVP 優先**：Phase 1（scraper 驗證）→ Phase 2 → Phase 3（US1）即可
讓 PO 開始用單純來回搜尋多目的地、取得比價結果，是本 feature 最小
可用交付。

**完整交付**：加上 Phase 4（轉機偏好）、Phase 5（通知標示）、
Phase 6（組合數守衛）才算完整實現 speckit-input.md 的全部範圍——
三者皆為 PO 明確要求的範圍內項目，建議同一輪做完，不分批交付
（與 007 的策略一致）。

**正式環境部署（T032）需要 PO 明確確認後才執行**，理由同 007／006
的既有先例——即使本包不涉及破壞性資料異動，仍是對正式服務的變更，
且清單合併端點（T014）是與既有四段票共用的程式碼路徑，需要人工
確認不影響既有功能後才部署。
