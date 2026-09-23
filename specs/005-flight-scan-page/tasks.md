# Tasks: 機票掃描分頁

**Input**: Design documents from `/specs/005-flight-scan-page/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/flights-api.md, quickstart.md

**Tests**: 本清單**包含測試任務**。理由不是 TDD，而是兩項明確要求：
(1) `quickstart.md` §3 坑 2 記載 2026-08-22 的正式環境事故——當次深度測試
全是依序單一請求，完全沒測到只有併發才會踩到的 race，因此**併發測試為
必要項而非加分項**；(2) 專案規範 `CLAUDE.md` 硬規則「完成＝驗證過」。
測試範圍聚焦在「已知會出錯的地方」，不為覆蓋率而寫。

**Organization**: 依 user story 分組，每組可獨立實作、測試與交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可平行執行（不同檔案、無未完成相依）
- **[Story]**: 對應 spec.md 的 user story

## Path Conventions

本專案為 web application，沿用既有三層分工（見 plan.md「Structure Decision」）：
演算法與資料層 `poc/kb-mcp/`、HTTP 層 `app/routers/`、介面 `web/src/pages/`。

---

## Phase 1: Setup

**Purpose**: 確認既有能力可用，不重複建置

- [X] T001 確認 scraper 依賴已安裝：在 `poc/kb-mcp/scraper/` 執行 `npm install`，並以 `node --check flight_scraper.js` 驗證
- [X] T002 [P] 以 `--dry-run` 驗證既有查價模組可用：執行 `poc/kb-mcp/flight_search.py --scan-dates --destination PRG --outstations NRT --start-date 2027-04-01 --months-ahead 1 --per-month 1 --trip-days 12 --data-dir poc/data --dry-run`，確認輸出組合數與月份正確（不發任何請求、不耗配額）
- [X] T003 [P] 建立隔離測試資料庫：`rm -rf poc/data-test && cp -R poc/data poc/data-test`，確認 `poc/data-test/` 已在 `.gitignore` 內

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有 user story 都依賴的資料層與接線

**⚠️ CRITICAL**: 本階段完成前，任何 user story 都無法開始

- [X] T004 建立 `poc/kb-mcp/flight_store.py`：`FlightStore` 類別，`__init__(data_dir)` 連線至 `<data_dir>/flights.db`，建立 `flight_track` 與 `flight_scan_result` 兩張表（欄位見 data-model.md）。**`sqlite3.connect()` 必須帶 `check_same_thread=False`**（quickstart §3 坑 2），**`__init__()` 不得有任何資料寫入**（坑 3）
- [X] T005 在 `poc/kb-mcp/flight_store.py` 實作查詢條件 CRUD：`create_track()`／`list_tracks()`／`get_track()`／`delete_track()`。刪除時連帶移除該條件的 `flight_scan_result`，但**不刪除跨條件共用的查價快取**
- [X] T006 在 `poc/kb-mcp/flight_store.py` 實作結果讀寫：`upsert_result()`（以 `track_id` ＋ 四段日期 ＋ 外站為唯一鍵覆寫）、`list_results(track_id)`（依 `price` 升冪，`status != ok` 排最後）
- [X] T007 在 `poc/kb-mcp/flight_store.py` 實作條件欄位驗證：外站清單非空、`trip_days` 為正整數、排除月份每項介於 1–12、`window_end` 不早於 `window_start`（FR-025），驗證失敗拋出明確例外
- [X] T008 [P] 建立 `poc/kb-mcp/tests/test_flight_store.py`：涵蓋建表無副作用、CRUD、唯一鍵覆寫、刪除連帶行為、四項驗證規則各自的失敗案例
- [X] T009 建立 `app/flight_deps.py`：`get_flight_store()` 依賴注入（比照 `app/us_stock_deps.py`），以及 **`resolve_flight_data_dir_for_background()`**——背景任務不得使用 request-scoped 連線（quickstart §3 坑 1）
- [X] T010 建立 `app/routers/flights.py` 骨架並在 `app/main.py` 註冊路由，前綴 `/api/flights`
- [X] T011 [P] 建立 `web/src/pages/Flights.jsx` 骨架，並在 `web/src/components/AppShell.jsx` 新增「機票」導覽項

**Checkpoint**: 分頁可開啟（空白）、API 可回應、資料表已建立

---

## Phase 3: User Story 1 - 不指定日期就看到便宜組合 (Priority: P1) 🎯 MVP

**Goal**: 使用者建立條件後，不輸入任何具體日期即可取得依價格排序的組合清單

**Independent Test**: 建立一個條件、觸發掃描、確認得到排序結果，且全程未輸入具體出發日

### 服務層

- [X] T012 [US1] 建立 `poc/kb-mcp/flight_scan_service.py`：`expand_track(track)` 將條件展開為完整組合清單，內部呼叫既有 `sample_dates()` 與 `build_itineraries_fixed_trip()`，**不重新實作枚舉邏輯**
- [X] T013 [US1] 在 `flight_scan_service.py` 實作 `pending_combinations(track)`：枚舉組合減去已在查價快取中的組合（research.md §2 的核心決策，**不儲存進度**）
- [X] T014 [US1] 在 `flight_scan_service.py` 實作 `run_scan(track_id, data_dir)`：取得未完成組合、呼叫既有 `scrape_itineraries()`、逐筆寫入 `flight_scan_result`、更新 `last_success_at`。供背景任務呼叫，自行建立與關閉 store 連線
- [X] T015 [US1] 在 `flight_scan_service.py` 實作 `derive_state(track)`：依 data-model.md 的推導表回傳 `idle`／`queued`／`scanning`／`partial`／`complete`／`stale`

### API 層

- [X] T016 [P] [US1] 在 `app/routers/flights.py` 實作 `GET /api/flights/tracks`：回傳條件清單、推導狀態、進度、最低價摘要與配額資訊（contracts §1）
- [X] T017 [P] [US1] 在 `app/routers/flights.py` 實作 `POST /api/flights/tracks`：驗證後建立，回傳 201 與 id；**建立後不自動掃描**（contracts §2）
- [X] T018 [P] [US1] 在 `app/routers/flights.py` 實作 `DELETE /api/flights/tracks/{id}`：回傳 204，404 於條件不存在（contracts §3）
- [X] T019 [US1] 在 `app/routers/flights.py` 實作 `POST /api/flights/tracks/{id}/scan`：以 `BackgroundTasks` 觸發 `run_scan`，立即回傳狀態。重複觸發不建立第二個作業（contracts §4）
- [X] T020 [US1] 在 `app/routers/flights.py` 實作 `GET /api/flights/tracks/{id}/results`：回傳狀態、進度、排序後結果（contracts §5）

### 前端

- [X] T021 [P] [US1] 建立 `web/src/pages/FlightTrackForm.jsx`：條件表單（目的地、外站多選、出發區間、行程天數、目標價），送出後呼叫建立端點
- [X] T022 [US1] 在 `web/src/pages/Flights.jsx` 實作條件卡片清單：顯示名稱、狀態、最低價、上次更新時間，提供「重新掃描」與「刪除」動作
- [X] T023 [US1] 在 `web/src/pages/Flights.jsx` 實作結果表：主行程起訖、外站、四段票價（NTD）、航空公司、第1段日期。分頁開啟時直接顯示既有結果，不觸發掃描
- [X] T024 [US1] 在 `web/src/pages/Flights.jsx` 區分「查無票價」與「查詢失敗」兩種狀態的呈現（FR-023）

### 測試

- [X] T025 [P] [US1] 建立 `poc/kb-mcp/tests/test_flight_scan_service.py`：涵蓋 `expand_track` 的組合數正確、`pending_combinations` 在快取命中時正確排除、`derive_state` 六種狀態的判定
- [X] T026 [US1] 在 `app/tests/test_smoke.py` 新增機票路由檢查：建立→列出→觸發→查詢→刪除的完整流程，並**比對 API 回傳的組合數與底層 `expand_track()` 的輸出一致**（非僅檢查回 200）

**Checkpoint**: US1 完成即為可用的 MVP——使用者能取得「哪時候便宜」的答案

---

## Phase 4: User Story 2 - 設定兩端間隔以分散行程 (Priority: P2)

**Goal**: 第1段與第4段的間隔可各自設定，並能自動避開指定月份

**Independent Test**: 同一組主行程，分別選「不拉遠」與「約 3 個月」，確認兩端日期隨之改變且互不影響

- [X] T027 [US2] 在 `poc/kb-mcp/flight_scan_service.py` 實作策略對應：`none`／`m1`／`m3`／`m5`／`auto` 映射到候選天數清單。**清單順序即偏好順序，拉遠的策略必須把大值排前面**（FR-008、CON-14；研究筆記記載此處曾因由小到大排列而全部挑到最小間隔）
- [X] T028 [US2] 在 `flight_scan_service.py` 的 `expand_track()` 接上 `auto` 模式：對每個主行程日期各自呼叫既有 `pick_lead()` 與 `pick_trail()`，兩端使用各自的排除月份
- [X] T029 [US2] 在 `flight_scan_service.py` 實作跳過與回報：所有候選間隔都無法避開排除月份的日期整組跳過，並記錄原因供 API 回傳 `skipped`（FR-010）
- [X] T030 [P] [US2] 在 `poc/kb-mcp/flight_store.py` 補上三組排除月份欄位的讀寫與驗證（`exclude_months_trip`／`_lead`／`_trail`）
- [X] T031 [P] [US2] 在 `web/src/pages/FlightTrackForm.jsx` 新增兩端間隔策略下拉選單與三組排除月份複選（1–12 月），**不得提供寫死的「夏季」快捷而無半球標示**（FR-009、CON-12）
- [X] T032 [US2] 在 `web/src/pages/Flights.jsx` 結果表新增「第1段日期／提前天數」與「第4段日期／延後天數」欄位
- [X] T033 [US2] 在 `app/routers/flights.py` 的結果端點回傳 `skipped` 清單，前端顯示被跳過的日期與原因
- [X] T034 [P] [US2] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 新增策略測試：`m3` 策略在回程後 1 天未被排除時**仍須回傳接近 90 天的值**（FR-008 的反向驗證，這是最容易寫錯的一項）
- [X] T035 [P] [US2] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 新增排除月份測試：北半球（6,7,8）、南半球（12,1,2）、不連續（2,7,12）三種情境下，主行程／第1段／第4段皆不落在排除月份

**Checkpoint**: US1 ＋ US2 皆可獨立運作

---

## Phase 5: User Story 3 - 大範圍掃描不因外部限制而失敗 (Priority: P3)

**Goal**: 超量掃描自動裁切與排隊，被阻擋時停止而非持續重試，已完成結果不遺失

**Independent Test**: 建立超過單時段配額的條件，確認完成可執行量、顯示剩餘與預估時間、下個時段接續未完成者

- [X] T036 [US3] 在 `flight_scan_service.py` 實作配額裁切：掃描前讀取既有 `remaining_browser_quota()`，將本批裁切為可執行量，其餘留待下次（FR-012）
- [X] T037 [US3] 在 `flight_scan_service.py` 處理軟阻擋：`scrape_itineraries()` 回報 `blocked`／`soft_blocked` 時立即停止本批、保留已完成結果、記錄阻擋種類（FR-016）
- [X] T038 [US3] 在 `app/routers/flights.py` 的觸發端點回傳排隊資訊：配額不足時回 **200 而非錯誤**，附 `seconds_until_free` 與說明（contracts §4；配額不足是營運狀態不是故障）
- [X] T039 [US3] 在 `app/routers/flights.py` 的結果端點回傳 `blocked`／`blocked_kind`／`seconds_until_free`，並在列表端點回傳 `quota` 物件含 `limit_basis`（FR-018）
- [X] T040 [US3] 在 `web/src/pages/Flights.jsx` 顯示進度（已完成／總數）、排隊狀態與預估接續時間；掃描進行中以 `setInterval` 輪詢結果端點（比照 `web/src/pages/Gateway.jsx:115` 既有慣例），完成後停止輪詢
- [X] T041 [US3] 在 `web/src/pages/Flights.jsx` 顯示配額用量與剩餘，並依 `limit_basis` 標明該限制值是實測值或推估值（FR-018、CON-09）
- [X] T042 [P] [US3] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 新增續掃測試：第一批完成 N 筆後，第二批的待查清單**只含未完成者**，且不重查已完成者
- [X] T043 [P] [US3] 在 `poc/kb-mcp/tests/test_flight_scan_service.py` 新增軟阻擋測試：模擬連續失敗達門檻時停止本批、已完成結果仍保留、回報 `blocked_kind` 為軟阻擋
- [X] T044 [US3] **在 `app/tests/test_smoke.py` 新增機票路由的併發請求測試**（至少 30 個併發），驗證 `check_same_thread=False` 生效。quickstart §3 坑 2：2026-08-22 的事故正是因為當時只做依序單一請求測試而未測到

**Checkpoint**: 大範圍掃描可靠，中斷與阻擋皆不遺失資料

---

## Phase 6: User Story 4 - 核對價格並避開票規風險 (Priority: P4)

**Goal**: 使用者能一鍵核對實際航班，並知道關鍵票規風險與接駁成本

**Independent Test**: 從任一筆結果點開外部連結，確認行程一致；確認風險提示與接駁估價可見

- [X] T045 [US4] 在 `app/routers/flights.py` 的結果端點為每筆結果附上 `links.four_segment` 與 `links.connector`，**由後端呼叫既有 `google_flights_url()` 構造**，前端不自行拼接（避免兩處邏輯分岔）
- [X] T046 [P] [US4] 在 `flight_scan_service.py` 接上接駁票估價：呼叫既有 `estimate_connectors()`，結果寫入 `connector_price`，API 回傳時附 `connector_is_estimate: true`（FR-020）
- [X] T047 [P] [US4] 在 `web/src/pages/Flights.jsx` 每筆結果顯示接駁估價（標明「估算」）與兩個外部連結按鈕
- [X] T048 [P] [US4] 在 `web/src/pages/Flights.jsx` 結果頁顯示票規提示：「第1段不可缺搭，否則後三段全部失效」與「僅經濟艙適用」（FR-021）
- [X] T049 [US4] 在 `app/routers/flights.py` 實作 `GET /api/flights/native-tracking`：回傳結構化的原生追蹤說明（`supported_for_four_segment: false` ＋ 理由 ＋ 主行程連結 ＋ 腳本路徑），資料見 contracts §6 與 `poc/kb-mcp/scraper/README-track-prices.md`
- [X] T050 [P] [US4] 在 `web/src/pages/Flights.jsx` 新增原生追蹤說明區塊，呈現「不支援四段票」的限制與主行程來回票的操作步驟
- [ ] T051 [US4] **手動驗證（無程式改動）**：以手機瀏覽器開啟 ngrok 網址的 `/flights` 分頁，確認 `web/src/pages/Flights.jsx` 的結果表可完整閱讀（頁面本體不橫向捲動）且外部連結正確開啟（FR-026、US4 情境 6）。有版面問題則回頭修改該檔案

**Checkpoint**: 四個 user story 全部完成

---

## Phase 7: Polish & Cross-Cutting

- [ ] T052 [P] 更新 `CLAUDE.md` 的「STND 分頁與程式碼位置」表，新增機票分頁一列（前端頁面、後端 router、資料來源），註明資料層為獨立 `flights.db`
- [ ] T053 [P] 更新 `docs/architecture.md` 的分頁地圖與相關敘述
- [ ] T054 [P] 在 `poc/kb-mcp/flight_store.py` 與 `flight_scan_service.py` 補齊模組層 docstring，說明與既有 `flight_search.py` 的分工邊界
- [ ] T055 完整測試回歸：`.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"` 全綠，且 `ALPHAVIBE_DATA_DIR=poc/data-test .venv/bin/python3 -m app.tests.test_smoke` 通過
- [ ] T056 **手動驗證（無程式改動）**：於 `web/src/pages/Flights.jsx` 建立一個小規模條件（1 外站 × 2 日期），實際掃描後比對結果價格與手動開啟外部連結所見一致（SC-004）。掃描前先以 `poc/kb-mcp/flight_search.py --dry-run` 確認規模，**注意會消耗配額**

---

## Dependencies

```text
Phase 1 (Setup)
    ↓
Phase 2 (Foundational) ←── 阻塞所有 user story
    ↓
Phase 3 (US1, P1) ←── MVP，可獨立交付
    ↓
Phase 4 (US2, P2) ←── 依賴 US1 的服務層與表單
    ↓
Phase 5 (US3, P3) ←── 依賴 US1 的掃描流程
    ↓
Phase 6 (US4, P4) ←── 依賴 US1 的結果呈現
    ↓
Phase 7 (Polish)
```

**Story 間的相依性**：四個 story 並非完全獨立——US2／US3／US4 都在 US1
建立的掃描流程與結果表上擴充。這是刻意的：本 feature 是單一畫面的漸進
增強，強行拆成完全獨立的切片會產生重複的鷹架。但**每個 story 完成後
都是可交付、可驗證的增量**：US1 完成即能回答「哪時候便宜」，
US2 加上請假彈性，US3 加上大範圍可靠性，US4 加上決策所需的核對能力。

---

## Parallel Opportunities

**Phase 2**：T008（store 測試）可與 T009～T011 平行；T011（前端骨架）
與後端任務完全獨立

**Phase 3**：T016／T017／T018 為三個獨立端點可平行；T021（表單）與
T025（服務層測試）可與 API 任務平行

**Phase 4**：T030（store 欄位）、T031（前端表單）、T034／T035（測試）
四者可平行

**Phase 5**：T042／T043 測試可與 T040／T041 前端平行

**Phase 6**：T046／T047／T048／T050 分屬不同檔案，可平行

**Phase 7**：T052／T053／T054 為三份不同文件，可平行

---

## Implementation Strategy

**MVP = Phase 1 ＋ 2 ＋ 3（T001–T026）**
完成後使用者即可建立條件、取得依價格排序的日期建議——這是整個功能存在
的理由。其餘三個 story 皆為增強。

**增量交付順序**：
1. US1 上線後實際用一次，確認掃描結果與手動查價一致（SC-004）
2. 再做 US2——它會改變 `expand_track()` 的行為，在 US1 驗證過的基礎上
   擴充較安全
3. US3 在掃描規模變大後才有意義，不必提前做
4. US4 為決策輔助，可最後補

**風險最高的兩個任務**：
- **T027**（策略對應候選清單）：順序寫反會讓「拉遠」策略全部挑到最小
  間隔，且測試若只檢查「有避開排除月份」會通過而不會發現。T034 是專門
  針對此的反向驗證
- **T044**（併發測試）：2026-08-22 的事故證明少了它會在正式環境才爆
