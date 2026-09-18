# Tasks: 相簿分頁（Photo Albums & Search）

**Input**: Design documents from `/specs/004-photos-albums-search/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/photos-api.md、quickstart.md（全部已備）

**Tests**: 本 repo 既有測試慣例（`poc/kb-mcp/tests/`、`app/tests/test_smoke.py`
的深度比對模式）視同「規格已要求測試」，故本清單包含測試任務，不省略。

**Organization**: 依 spec.md 的 3 個 User Story（P1/P2/P3）分組，每個
Story 可獨立完成、獨立驗證。

## Path Conventions

沿用本 repo 既有結構（`plan.md`「Project Structure」節）：
`poc/kb-mcp/`（資料層/背景任務邏輯）、`app/`（FastAPI 路由，薄層轉呼叫）、
`web/src/`（React 前端）。

---

## Phase 1: Setup

**Purpose**: 建立本功能的檔案骨架，不含實際邏輯

- [X] T001 建立 `poc/kb-mcp/photo_store.py`、`poc/kb-mcp/photo_importer.py`、
  `poc/kb-mcp/photo_metadata_sync.py` 三個空模組檔案，各自加上模組
  docstring 說明用途與獨立性（比照 `us_stock_store.py` 檔頭慣例）
- [X] T002 [P] 核對 `specs/004-photos-albums-search/quickstart.md` 的
  `exiftool` 安裝步驟（`brew install exiftool`）已完整記錄，若本機尚未
  安裝先手動安裝並確認 `exiftool -ver` 可執行
- [X] T003 [P] 建立 `poc/kb-mcp/tests/test_photo_store.py`、
  `poc/kb-mcp/tests/test_photo_importer.py`、
  `poc/kb-mcp/tests/test_photo_metadata_sync.py` 三個測試檔骨架

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 三個 User Story 都依賴的核心基礎——資料表、Store 基礎方法、
router 掛載點、前端頁面殼

**⚠️ CRITICAL**: 本階段完成前不得開始任何 User Story 的實作任務

- [X] T004 在 `poc/kb-mcp/photo_store.py` 實作 `SCHEMA` 常數（5 張表：
  `albums`／`photos`／`photo_albums`／`tags`／`photo_tags`，完整欄位
  比照 `data-model.md`，含 `photos.metadata_sync_status` 等欄位）與
  `PhotoStore.__init__`（只執行 `CREATE TABLE IF NOT EXISTS`，**不**
  寫入任何列，比照 `us_stock_store.py`「完全獨立、無副作用種子寫入」
  慣例——2026-08-22 資產表事故的教訓）
- [X] T005 [P] 在 `poc/kb-mcp/photo_store.py` 實作相簿 CRUD：
  `create_album`／`list_albums`／`update_album`／`delete_album`
- [X] T006 [P] 在 `poc/kb-mcp/photo_store.py` 實作照片基礎方法：
  `get_photo`／`delete_photo`（僅刪除 `photos`／`photo_albums`／
  `photo_tags` 對應紀錄，不動磁碟上的實際檔案）
- [X] T007 [P] 在 `poc/kb-mcp/photo_store.py` 實作標籤方法：
  `get_or_create_tag`／`list_tags`／`suggest_tags`（依名稱前綴/包含
  比對，供標籤輸入自動完成用）
- [X] T008 在 `app/routers/photos.py` 建立 router 骨架並在 `app/main.py`
  註冊掛載點（先不含實際邏輯，僅確認掛載成功、路由前綴 `/api/photos`
  可達）
- [X] T009 [P] 在 `poc/kb-mcp/photo_store.py` 決定 `photos.db` 檔案位置
  解析方式，比照 `us_stock_store.py` 從既有資料目錄設定取得路徑的慣例
  （不寫死絕對路徑，供測試時可指向獨立測試庫）
- [X] T010 在 `web/src/pages/Photos.jsx` 移除 MVP 佔位內容，建立分頁
  基本殼（相簿列表／搜尋兩個子畫面的切換架構），接上 API client
- [X] T011 [P] 在 `web/src/api/client.js` 新增對應
  `contracts/photos-api.md` 全部端點的呼叫函式骨架
- [X] T012 [P] 在 `poc/kb-mcp/tests/test_photo_store.py` 撰寫測試驗證
  `PhotoStore.__init__` 只建 schema、不寫入任何列（比照 2026-08-22
  資產表事故後建立的既有回歸測試模式）

**Checkpoint**: 基礎就位——三個 User Story 可以開始平行或依序實作

---

## Phase 3: User Story 1 - 匯入照片並整理成相簿 (Priority: P1) 🎯 MVP

**Goal**: 使用者可以把本機資料夾裡的照片匯入、自動去重、分配相簿、
加標籤與評分、瀏覽縮圖牆——單獨這個 Story 就是一個完整可用的個人
相簿整理工具

**Independent Test**: 依 `quickstart.md`「手動驗收流程」步驟 1-3——
匯入一批照片確認去重預覽正確、重複匯入同批照片確認全部跳過、批次
分配相簿與標籤後重新整理頁面仍存在

### Tests for User Story 1

- [X] T013 [P] [US1] 在 `poc/kb-mcp/tests/test_photo_importer.py` 撰寫
  整合測試：同一批來源照片匯入兩次，第二次應全部被判定為重複並跳過，
  不產生重複的 `photos` 列
- [X] T014 [P] [US1] 在 `app/tests/test_photos_smoke.py` 撰寫契約測試：
  驗證 `POST /api/photos/import/scan`、`POST /api/photos/import/commit`
  回應格式符合 `contracts/photos-api.md`

### Implementation for User Story 1

- [X] T015 [US1] 在 `poc/kb-mcp/photo_importer.py` 實作 `scan_folder()`：
  掃描來源資料夾、對每個檔案計算 MD5、比對 `PhotoStore` 既有
  `file_hash`、回傳新增/重複清單與無法讀取的檔案清單（**`research.md`
  §4：這是 `file_hash` 凍結計算的唯一時機點，之後任何背景任務都不得
  重新計算**）
- [X] T016 [US1] 在 `poc/kb-mcp/photo_importer.py` 實作
  `commit_import()`：複製檔案到指定 `storage_location`（內接/外接）、
  呼叫 `sips` 產生縮圖並讀取基礎 EXIF（camera_model／lens／iso／
  shutter_speed／aperture／photo_date），寫入 `PhotoStore`
- [X] T017 [US1] 在 `poc/kb-mcp/photo_store.py` 實作 `add_photo()`／
  `find_by_hash()`（依賴 T015／T016 的呼叫規格）
- [X] T018 [US1] 在 `app/routers/photos.py` 實作匯入相關端點：透過
  FastAPI `BackgroundTasks` 執行 `commit_import()`，進度寫回可輪詢的
  狀態記錄（`GET /api/photos/import/jobs/{job_id}`）
- [X] T019 [P] [US1] 在 `app/routers/photos.py` 實作
  `GET /api/photos/browse-folders`、`POST /api/photos/import/scan`
- [X] T020 [P] [US1] 在 `app/routers/photos.py` 實作相簿端點：
  `GET/POST/PATCH/DELETE /api/photos/albums`、
  `GET /api/photos/albums/{id}/photos`
- [X] T021 [P] [US1] 在 `app/routers/photos.py` 實作照片整理端點：
  `PATCH /api/photos/photos/{id}`（評分/標籤，本階段暫不觸發中繼資料
  同步，留給 US3）、`POST /api/photos/photos/batch`、
  `DELETE /api/photos/photos/{id}`
- [X] T022 [US1] 在 `web/src/components/photos/ImportWizard.jsx` 實作
  匯入流程 UI（選資料夾路徑→去重預覽→背景匯入進度），互動細節比照
  已驗證的[流程圖與畫面 Demo](https://claude.ai/code/artifact/57660844-0f08-419e-84e7-cec1aba4d1ef)
- [X] T023 [US1] 在 `web/src/components/photos/AlbumGrid.jsx`、
  `web/src/components/photos/AlbumDetail.jsx` 實作相簿列表與縮圖牆
  （含批次選取指派相簿/標籤/評分）
- [X] T024 [US1] 在 `web/src/pages/Photos.jsx` 整合上述元件，套用
  `web/src/styles/tokens.css` 既有色彩/元件樣式，不另開新視覺系統
- [X] T025 [US1] 在 `poc/kb-mcp/photo_importer.py` 處理無法讀取/毀損
  檔案：跳過並列入結果，不中斷其餘照片匯入（spec.md Edge Cases）
- [X] T026 [US1] 在 `app/tests/test_photos_smoke.py` 補充端到端驗證：
  匯入去重、相簿/標籤/評分批次指派、刪除僅動 db 不動磁碟（比照既有
  `test_smoke.py` 深度比對慣例，不只驗證 HTTP 200）

**Checkpoint**: User Story 1 完整可用且可獨立驗證——即使 US2/US3 都
還沒做，相簿分頁已經是一個完整的照片整理工具

---

## Phase 4: User Story 2 - 跨相簿全域搜尋照片 (Priority: P2)

**Goal**: 使用者可以用相機型號、鏡頭、標籤組合條件搜尋，一次找出所有
相簿裡符合的照片，不需要逐一開啟每個相簿

**Independent Test**: 依 `quickstart.md` 步驟 4——對已標記好的照片用
單一條件與組合條件搜尋，驗證結果只包含符合條件的照片且跨相簿呈現

### Tests for User Story 2

- [ ] T027 [P] [US2] 在 `poc/kb-mcp/tests/test_photo_store.py` 撰寫整合
  測試：多個相簿各放帶有相同標籤的照片，搜尋該標籤應回傳跨相簿的
  合併結果
- [ ] T028 [P] [US2] 在 `app/tests/test_photos_smoke.py` 撰寫契約測試：
  `GET /api/photos/search` 各種條件組合（單一條件／組合條件的交集
  邏輯）

### Implementation for User Story 2

- [ ] T029 [US2] 在 `poc/kb-mcp/photo_store.py` 實作
  `search_photos(camera_model, lens, tags)`：多個標籤取交集，**不**
  join `photo_albums`（搜尋本身跨相簿、不限定範圍）
- [ ] T030 [P] [US2] 在 `app/routers/photos.py` 實作
  `GET /api/photos/search`、`GET /api/photos/tags`
- [ ] T031 [P] [US2] 在 `web/src/components/photos/SearchPanel.jsx`
  實作全域搜尋 UI（相機/鏡頭下拉＋標籤多選 chip＋結果縮圖牆）
- [ ] T032 [US2] 在 `web/src/pages/Photos.jsx` 整合搜尋入口按鈕與畫面
  切換
- [ ] T033 [US2] 在 `poc/kb-mcp/photo_store.py` 確認
  `search_photos()` 只讀資料庫欄位，不檢查 `storage_path` 指向的
  實際檔案是否存在（確保外接硬碟離線不影響搜尋結果，spec.md FR-010）

**Checkpoint**: User Story 1 與 2 皆可獨立運作且互不影響

---

## Phase 5: User Story 3 - 標籤與評分跟著照片走出這個工具 (Priority: P3)

**Goal**: 使用者在相簿分頁加的標籤與評分，會被寫進照片檔案本身的
XMP/IPTC 中繼資料，並可追蹤同步狀態、手動重試

**Independent Test**: 依 `quickstart.md` 步驟 5——編輯照片標籤後確認
狀態變為「已同步」，用 `exiftool` 直接檢查檔案確認真的寫入；模擬離線
情境確認標記為「待同步」且不影響資料庫端的編輯與搜尋

### Tests for User Story 3

- [ ] T034 [P] [US3] 在 `poc/kb-mcp/tests/test_photo_metadata_sync.py`
  撰寫單元測試：mock `subprocess` 驗證 exiftool 呼叫成功/失敗兩種
  情境的回傳格式
- [ ] T035 [P] [US3] 在 `poc/kb-mcp/tests/test_photo_store.py` 撰寫
  回歸測試：驗證中繼資料寫回前後 `file_hash` 不變（`research.md` §4
  核心保證，防止未來被誤「修正」成即時重算而破壞去重機制）

### Implementation for User Story 3

- [ ] T036 [US3] 在 `poc/kb-mcp/photo_metadata_sync.py` 實作
  `write_metadata(photo)`：呼叫
  `exiftool -overwrite_original -XMP:Rating=... -IPTC:Keywords=... -XMP:Subject=...`，
  回傳成功或失敗原因（見 `research.md` §2 命令格式）
- [ ] T037 [US3] 在 `app/routers/photos.py` 的
  `PATCH /api/photos/photos/{id}` 加上：評分/標籤變更後立即把
  `metadata_sync_status` 設回 `pending`，並透過 `BackgroundTasks`
  觸發 `write_metadata()`
- [ ] T038 [P] [US3] 在 `app/routers/photos.py` 實作
  `POST /api/photos/photos/{id}/resync`（手動重試）
- [ ] T039 [US3] 在 `poc/kb-mcp/photo_metadata_sync.py` 區分「硬碟離線
  （暫時性，標記 `pending`）」與「exiftool 真的寫入失敗（標記
  `failed` 並記錄 `metadata_sync_error`）」兩種情況
- [ ] T040 [P] [US3] 在 `web/src/components/photos/SyncStatusCard.jsx`
  實作已同步/待同步/失敗徽章＋重新同步按鈕，互動細節比照已驗證的
  流程圖與畫面 Demo
- [ ] T041 [US3] 在 `web/src/components/photos/PhotoDetail.jsx` 整合
  `SyncStatusCard.jsx` 與 EXIF 資訊顯示
- [ ] T042 [US3] 在 `app/tests/test_photos_smoke.py` 補充：標籤/評分
  編輯觸發同步狀態變化、`file_hash` 不因中繼資料寫回而改變的端到端
  回歸測試

**Checkpoint**: 三個 User Story 皆完整可用——相簿分頁功能全部到位

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T043 [P] 更新 `docs/architecture.md`「分頁地圖」節，把相簿分頁
  從「MVP 僅入口」更新為實際完成範圍（比照資產分頁 FR-061 上線後的
  更新模式）
- [ ] T044 [P] 更新 `CLAUDE.md`「STND 分頁與程式碼位置」表的相簿分頁
  描述
- [ ] T045 完整跑一次 `quickstart.md`「手動驗收流程」全部步驟
- [ ] T046 效能檢查：實測匯入 100+ 張照片時，其他 API 請求是否仍正常
  回應（驗證 `plan.md` Constitution Check Gate G4）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：無依賴，可立即開始
- **Foundational (Phase 2)**：依賴 Setup 完成——**阻擋**所有 User Story
- **User Stories (Phase 3-5)**：全部依賴 Foundational 完成；三個 Story
  可平行進行，或依優先序 P1→P2→P3 依序進行
- **Polish (Phase 6)**：依賴所有想交付的 User Story 完成

### User Story Dependencies

- **User Story 1 (P1)**：Foundational 完成後可開始，不依賴其他 Story——
  是 US2／US3 的資料基礎（沒有匯入進來的照片，搜尋跟同步都沒東西可
  操作），但程式碼層面三者互相獨立、不共用同一批檔案的邏輯
- **User Story 2 (P2)**：Foundational 完成後可開始；獨立測試時可用
  T012 已建好的 schema 直接寫測試資料到 `photos`／`tags` 表，不必等
  US1 的匯入 UI 做完才能測
- **User Story 3 (P3)**：同上，獨立測試時可直接對已存在的照片記錄
  呼叫 `write_metadata()`

### Within Each User Story

- 先寫測試（會失敗）→ 再實作 Store 方法 → 再接 router 端點 → 最後接
  前端 UI
- Story 完成（含 Checkpoint 驗證）才進到下一個優先序

### Parallel Opportunities

- Setup 階段 T002／T003 可平行
- Foundational 階段 T005／T006／T007／T009／T011／T012 可平行（各自
  獨立方法/檔案）
- Foundational 完成後，US1／US2／US3 三條線可由不同人平行推進
- 每個 Story 內標了 `[P]` 的任務可平行（不同檔案、不互相依賴）

---

## Parallel Example: User Story 1

```bash
# Foundational 完成後，以下四個任務可同時進行（不同檔案）：
Task: "T013 整合測試：重複匯入應被跳過 in poc/kb-mcp/tests/test_photo_importer.py"
Task: "T014 契約測試：import/scan 與 import/commit 回應格式 in app/tests/test_photos_smoke.py"
Task: "T019 GET /api/photos/browse-folders、POST /api/photos/import/scan in app/routers/photos.py"
Task: "T020 相簿端點 CRUD in app/routers/photos.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（**關鍵**——阻擋所有 Story）
3. 完成 Phase 3 User Story 1
4. **停下來驗證**：依 quickstart.md 步驟 1-3 獨立測試 US1
5. 此時相簿分頁已經是一個完整可用的個人照片整理工具，可以先讓 PO
   實際使用一段時間再決定要不要接著做 US2/US3

### Incremental Delivery

1. Setup + Foundational → 基礎就位
2. + User Story 1 → 獨立測試 → 可先上線使用（MVP！核心的匯入/整理
   價值已經到位）
3. + User Story 2 → 獨立測試 → 上線（PO 說的「核心需求」搜尋到位）
4. + User Story 3 → 獨立測試 → 上線（可攜性加值，標籤跟著照片走）

每個 Story 上線都不會破壞前面已經上線的 Story。

---

## Notes

- `[P]` 任務＝不同檔案、彼此無依賴，可平行進行
- `[US1]`／`[US2]`／`[US3]` 標籤對應 spec.md 的三個 User Story，方便
  追溯
- 每個 User Story 完成後都要能獨立測試、獨立驗證，不必等其他 Story
- 實作前務必先讀 `research.md` §4（`file_hash` 凍結時機）與
  `plan.md` Constitution Check（獨立 Store／無副作用種子寫入／背景
  任務不阻塞這幾個既有硬性慣例）
- 建議每完成一個任務或一組邏輯相關的任務就 commit 一次
- 避免：模糊的任務描述、同一檔案被多個 `[P]` 任務同時修改、跨 Story
  的隱性依賴（會破壞「每個 Story 可獨立測試」的設計）

---

## Implementation Notes（2026-09-18，US1 實作完成後補充）

實作過程中發現幾處跟原文件描述不完全一致的地方，記錄於此，供之後接續
US2/US3 或回頭查證時參考：

1. **T014／T026 的測試檔案位置**：實際寫進既有共用黑箱測試檔
   `app/tests/test_smoke.py`，**不是**另開一個 `test_photos_smoke.py`
   ——這個檔案本來就承載 dashboard／assets／us-stocks 各功能的深度
   測試（一支腳本、一次啟動真正的 uvicorn，比照既有慣例），相簿分頁
   延續同一個檔案更符合這裡「單一黑箱測試涵蓋全部業務端點」的既有
   設計，原文件寫的檔名是筆誤。
2. **`scan_folder()` 補上同批次內部去重**：原設計只用
   `photo_store.find_by_hash()` 查資料庫既有紀錄，沒擋「這次掃描的
   資料夾裡本來就有兩份內容相同的檔案」這種情況——那樣的話第二份會
   在 `commit_import()` 因 `UNIQUE` 約束衝突被誤記成「失敗」而不是
   「重複跳過」。已修正（`seen_hashes_this_batch` 集合）並補上回歸
   測試（`test_two_identical_files_in_same_batch_dedupe_against_each_other`）。
3. **新增 `GET /api/photos/thumbnail/{photo_id}`**：`contracts/
   photos-api.md` 原本只讓 `photos` 表存 `thumbnail_path`（檔案系統
   路徑），沒有對應的 HTTP 端點把縮圖位元組回給瀏覽器——前端縮圖牆
   實際上完全顯示不出照片。已補上端點與契約文件，`app/tests/
   test_smoke.py` 也補了對應驗證（真的收到非空的圖片位元組）。
4. **`GET /api/photos/tags` 的 Story 歸屬修正**：`tasks.md` 原本把它
   標在 T030（User Story 2，搜尋），但這個端點其實是 spec.md FR-006
   「加標籤時提示既有標籤」的自動完成需求，屬於 User Story 1 範圍，
   已提前在這輪實作（`app/routers/photos.py::suggest_tags`）。等做到
   User Story 2 時這個端點已經存在，直接沿用即可。
5. **`commit_import()` 回傳值新增 `imported_photo_ids`**：原設計只回
   `imported_count`／`failed`，前端/測試都需要知道「剛剛匯入的是哪幾
   張」才能接著做批次整理，已加上這個欄位（`app/routers/photos.py`
   的匯入 job 狀態一併回傳）。
6. **sips EXIF 欄位對應仍未拿真實相機 JPG 驗證**（承接 `quickstart.md`
   已知風險）：目前只驗證過「沒有 EXIF 時正確回傳 `None`」這條路徑；
   `Model`／`LensModel`／`ISOSpeedRatings` 等鍵名是否精確對應真實相機
   輸出的 `sips -g allxml` 結構，留待有真實照片時再驗證，讀取失敗不會
   中斷匯入（已有的防呆設計）。

**驗證證據**：`poc/kb-mcp/tests/test_photo_store.py`（22 tests）、
`poc/kb-mcp/tests/test_photo_importer.py`（10 tests）全數通過；
`ALPHAVIBE_DATA_DIR=poc/data-test .venv/bin/python3 -m app.tests.test_smoke`
全數通過（含 8 項相簿分頁深度驗證：匯入去重、背景任務完成、縮圖端點、
原始檔落地、批次整理、相簿內容、標籤自動完成、刪除保留原檔）；
`npm run build`（`web/`）成功產出 `dist/`，無編譯錯誤。
