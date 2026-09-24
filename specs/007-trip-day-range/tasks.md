# Tasks: 四段票天數區間化

**Input**: Design documents from `/specs/007-trip-day-range/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、
contracts/tracks-api.md、quickstart.md（皆已完成）

**Tests**: 本 feature 對已上線生產功能與資料做破壞性異動，測試任務
**全部納入**，不視為選配——比照 005、006 的既有慣例。

**Organization**: 依 spec.md 的 3 個 User Story（P1 區間查詢核心能力、
P2 id=9 遷移、P3 組合數上限守衛）分階段，各自可獨立測試與交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行進行（不同檔案、不互相依賴）
- **[Story]**：所屬 User Story（US1／US2／US3）
- 每個任務都附確切檔案路徑

---

## Phase 1: Setup

**Purpose**：確認起點乾淨，動工前先有基準線

- [X] T001 執行 `.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"`，確認合併 `function/alphavibe` 後的既有 247 個機票測試全綠（基準線，任何後續失敗都能歸因到本次改動）
- [X] T002 [P] 確認 `poc/kb-mcp/backup_databases.py` 的 `DATABASES` 常數現況（quickstart.md 記錄的既有缺口：不含 `flights.db`），為 Phase 6 的修正任務預先確認範圍

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**：天數區間的 schema 與驗證規則，三個 User Story 都建立在這之上

**⚠️ CRITICAL**：本階段完成前，User Story 不可動工

- [X] T003 在 `poc/kb-mcp/flight_store.py` 的 `SCHEMA` 新增 2 個欄位：`trip_days_min INTEGER`、`trip_days_max INTEGER`，於 `_migrate()` 用既有的逐欄 `ALTER TABLE ADD COLUMN`＋容忍 `OperationalError` 寫法新增（data-model.md「新增欄位」）
- [X] T004 在 `poc/kb-mcp/flight_store.py` 的 `create_track()` 把 `trip_days` 參數改為 `trip_days_min`／`trip_days_max`：驗證皆為正整數、上限不得小於下限；`INSERT` 語句同步寫入這兩個新欄位，並鏡射寫入舊的 `trip_days` 欄位（= `trip_days_max`）以滿足既有 `NOT NULL` 約束（research.md §2）
- [X] T005 在 `poc/kb-mcp/flight_store.py` 的 `_row_to_track()` 回傳 `trip_days_min`／`trip_days_max`，移除回傳中的 `trip_days`
- [X] T006 [P] 在 `poc/kb-mcp/flight_scan_service.py` 新增純函式 `combination_count(months, samples_per_month, num_targets, num_day_options)`，回傳算出的組合數（不依賴 `Track` 物件形狀，供 `roundtrip-search` 包未來重用，research.md §4）
- [X] T007 [P] 在 `poc/kb-mcp/tests/test_flight_store.py` 補上 T003-T005 的測試：schema 新欄位存在、`create_track()` 驗證規則（下限>上限拒絕、非正整數拒絕、下限=上限合法）、既有資料庫升級後欄位可讀、舊 `trip_days` 欄位鏡射寫入但不影響 `_row_to_track()` 回傳形狀
- [X] T008 [P] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 補上 `combination_count()` 的測試：基本乘法正確、邊界值（單一天數選項＝1、單一目標數＝1）

**Checkpoint**：schema 與驗證規則就緒，三個 User Story 可以動工

---

## Phase 3: User Story 1 - 建立條件時用天數區間比較不同天數的價格 (Priority: P1) 🎯 MVP

**Goal**：PO 建立四段票條件時可設定天數區間，系統展開多個天數選項各自
查價，一次看到不同天數的比價結果

**Independent Test**：建立一個天數區間 10～14 天、出發區間跨 2 個月的
新條件，觸發掃描後，結果集合中至少出現 3 種不同天數的組合

- [X] T009 [US1] 在 `poc/kb-mcp/flight_scan_service.py` 的 `expand_track()` 改為對天數區間內每個值各呼叫一次 `fs.sample_dates(trip_days=<值>, ...)`，累加所有 `(天數, outbound_date, return_date)` 組合再逐一解析 lead／trail 與建立行程（research.md §1；`_resolve_offsets()`／`build_itineraries_fixed_trip()` 不變動）
- [X] T010 [US1] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 補上 `expand_track()` 天數區間測試：區間 10～14 天時結果涵蓋 5 種天數；區間退化為單一值（min=max）時行為等同舊版單一天數；驗證每筆行程的天數與 `outbound_date`／`return_date` 差值一致
- [X] T011 [US1] 在 `app/routers/flights.py` 的 `TrackCreate` 請求模型把 `trip_days` 改為 `trip_days_min`／`trip_days_max`，`create_track()` 呼叫改傳這兩個欄位（contracts/tracks-api.md §1）
- [X] T012 [US1] 在 `app/routers/flights.py` 的 `_track_summary()`／清單與結果端點，回應欄位反映新的天數區間形狀（contracts/tracks-api.md §2）
- [X] T013 [P] [US1] 在 `web/src/pages/FlightTrackForm.jsx` 把單一「行程天數」輸入框改為兩個輸入框（天數下限／上限），送出時對應 `trip_days_min`／`trip_days_max`
- [X] T014 [P] [US1] 在 `web/src/pages/Flights.jsx` 的卡片與結果顯示，把天數欄位從單一數字改為區間格式（例如「10～14 天」）
- [X] T015 [US1] 在 `app/tests/test_smoke.py` 更新既有依賴 `trip_days` 單一整數與 `progress.total` 組合數的深度比對斷言，改用新的區間欄位與 `combination_count()` 公式比對（沿用既有「與底層比對」深度檢查風格，非僅檢查 200；contracts/tracks-api.md「相容性影響」）

**Checkpoint**：User Story 1 完整可用——PO 可建立區間天數條件並取得跨天數比價結果

---

## Phase 4: User Story 2 - 既有追蹤條件遷移到區間並重新查價 (Priority: P2)

**Goal**：把正式庫既有唯一一筆追蹤條件（id=9）遷移到區間語意（10～14
天）並重新查價，保留其目標價、通知歷史、重掃頻率不變

**Independent Test**：遷移前記錄 id=9 的目標價／通知歷史／重掃頻率；
執行遷移後直接讀資料庫確認天數已變成 10～14 區間，其餘欄位數值不變

- [X] T016 [US2] 建立 `poc/kb-mcp/migrate_trip_days_range.py`：一次性腳本，`--data-dir` 參數，`--dry-run` 支援（只印出遷移前後對照、不寫入），對 id=9 執行 `store.update` 系列方法把天數改為 10～14（不得用裸 SQL，走 `FlightStore` 既有驗證路徑；research.md §3；比照 `seed_assets_once.py` 的既有先例）
- [X] T017 [US2] 在 `poc/kb-mcp/flight_store.py` 視需要新增 `update_trip_days_range(track_id, trip_days_min, trip_days_max)` 方法（若既有沒有可重用的 update 方法），驗證規則與 `create_track()` 一致
- [X] T018 [P] [US2] 在 `poc/kb-mcp/tests/test_flight_store.py` 補上 T017 新方法的測試：更新成功、驗證規則套用、找不到條件回傳 None
- [X] T019 [US2] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 或新測試檔補上遷移腳本的整合測試：對獨立測試資料庫建立一個模擬 id=9 的條件（含目標價／通知歷史），執行遷移後驗證天數區間正確、其餘欄位不變、`--dry-run` 不寫入任何變更
- [X] T020 [US2] **⏸ 待手動執行**：比照 quickstart.md 步驟，先對 `poc/data-test/`（獨立測試庫，非正式庫）執行 `migrate_trip_days_range.py --dry-run` 再執行正式遷移，確認行為符合預期——這是本任務在**本機測試環境**的驗證，不是正式環境部署（正式環境部署見 Phase 6 T028）

**Checkpoint**：遷移機制經測試庫驗證，正式環境部署留給 Phase 6（需要先合併程式碼與備份）

---

## Phase 5: User Story 3 - 組合數超標時拒絕建立條件 (Priority: P3)

**Goal**：建立條件時若算出的查詢組合數超過上限（預設 60），系統拒絕
建立並說明組合數與上限，避免吃光整小時的查詢配額

**Independent Test**：建立一個候選外站數 × 抽樣日期數 × 天數選項數
明顯超過 60 的條件，系統拒絕建立並在錯誤訊息中說明組合數與上限；
資料庫未寫入這筆條件

- [X] T021 [US3] 在 `poc/kb-mcp/flight_scan_service.py` 新增常數 `MAX_COMBINATIONS_PER_TRACK = 60`（assumption，見 spec.md「Assumptions」，可隨時調整）
- [X] T022 [US3] 在 `app/routers/flights.py` 的 `create_track()` 端點，建立前用 `combination_count()`（T006）算出組合數，超過 `MAX_COMBINATIONS_PER_TRACK` 時回 400，錯誤訊息包含算出的組合數與上限（contracts/tracks-api.md §1；沿用既有「驗證失敗必須回 400 並說明原因」慣例）
- [X] T023 [P] [US3] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 補上 `MAX_COMBINATIONS_PER_TRACK` 常數存在性測試（避免未來被誤刪或改錯型別）
- [X] T024 [US3] 在 `app/tests/test_smoke.py` 新增組合數超標的正式流程測試：POST 一個組合數超過 60 的條件，確認回 400 且訊息含組合數與上限；資料庫確認未寫入這筆條件（可用 `store.list_tracks()` 數量比對，或確認回應無 `id` 欄位）
- [X] T025 [US3] 確認 `PATCH /api/flights/tracks/{id}` 端點（`TrackUpdate`）收到 `trip_days_min`／`trip_days_max` 欄位時直接忽略、不報錯（contracts/tracks-api.md §3；FR-007 天數區間不開放 PATCH），並補上對應測試

**Checkpoint**：三個 User Story 全數完成，MVP 範圍（P1）＋資料遷移（P2）
＋安全守衛（P3）皆已實作並測試覆蓋

---

## Phase 6: Polish & Cross-Cutting

**Purpose**：文件同步、既有缺口修正、正式環境部署

- [X] T026 [P] 在 `poc/kb-mcp/backup_databases.py` 的 `DATABASES` 常數加入 `"flights.db"`（quickstart.md 記錄的既有缺口——四段票功能上線以來不在既有每日自動備份範圍，本次要對其做 schema 遷移，低成本一併修正）
- [X] T027 完整回歸：`poc/kb-mcp/tests` 全套綠、`npx vite build`（`web/`）通過、smoke test 乾淨測試庫（`poc/data-test/`，比照 CLAUDE.md 既有重建步驟）整體 PASS
- [X] T028 **正式環境部署已完成（2026-09-24）**：備份正式庫 `poc/data/flights.db`（用 T026 更新後的 `backup_databases.py` 或手動執行一次）→ 合併程式碼到 `function/alphavibe` → 重啟 `com.alphavibe.reportserver` → 對正式庫執行 `migrate_trip_days_range.py`（先 `--dry-run`）→ 觸發 id=9 手動掃描確認新組合可查價 → `curl` 直接驗證正式 API 回傳的 `trip_days_min`／`trip_days_max` 欄位正確（quickstart.md「正式環境部署順序」，比照本 session 過去對 005／006／通知功能的正式環境驗證慣例）
- [X] T029 [P] 更新 `CLAUDE.md`／`docs/architecture.md` 的機票分頁列，補上天數區間化與 id=9 遷移後的現況
- [X] T030 更新 `docs/spec-intake/flight-roundtrip-search/handoff-checklist.md`「非阻斷的已知待辦」段落，標記 `trip-day-range` 包已實作完成，`roundtrip-search` 包可以開始（供下一個 Spec Kit feature 接手時查證現況）

---

## Dependencies & Execution Order

```text
Phase 1 (Setup)
   ↓
Phase 2 (Foundational: schema + combination_count())
   ↓
   ├── Phase 3 (US1，P1，MVP) ──┐
   ├── Phase 4 (US2，P2)         │ 三者皆依賴 Phase 2，
   └── Phase 5 (US3，P3) ────────┘ 彼此間可平行推進
   ↓
Phase 6 (Polish：正式環境部署依賴 Phase 3/4/5 全數完成)
```

**User Story 間的實際耦合**：US2（id=9 遷移）依賴 US1 已完成的 schema
與展開邏輯（遷移後要能重新查價）；US3（組合數上限）依賴 Phase 2 的
`combination_count()`，與 US1／US2 互不阻塞，可平行進行。嚴格的
User-Story-獨立性在本 feature 因為三者共用同一張表的同一組新欄位而
天然較緊密，與 spec.md 標注的優先順序一致（P1→P2→P3 循序交付仍是
建議路徑，但 US3 的兩個任務 T021-T025 技術上可以在 US1 完成 T009
後立即開始，不需等待 US2）。

## Parallel Execution Examples

Phase 2 完成後，以下任務可同時進行（不同檔案、無相互依賴）：

```text
T013 [P] [US1] FlightTrackForm.jsx 天數輸入框
T014 [P] [US1] Flights.jsx 天數顯示
T018 [P] [US2] test_flight_store.py 的 update 方法測試
T023 [P] [US3] MAX_COMBINATIONS_PER_TRACK 常數測試
```

## Implementation Strategy

**MVP 優先**：Phase 1 → Phase 2 → Phase 3（US1）即可讓 PO 開始用區間
天數建立新條件並取得比價結果，是本 feature 最小可用交付。

**完整交付**：加上 Phase 4（US2，id=9 遷移）與 Phase 5（US3，組合數
守衛）才算完整實現 product-spec.md 與 speckit-input.md 的全部範圍——
兩者皆為 PO 明確要求的範圍內項目，不是延伸功能，建議同一輪做完，不
分批交付。

**正式環境部署（T028）需要 PO 明確確認後才執行**，理由同 006 的
launchd 部署先例：涉及對正式生產資料的異動，即使測試庫驗證通過，
仍需要人手動確認備份已完成、且願意承擔遷移風險後才對正式庫動手。
