---
description: "Task list for feature implementation"
---

# Tasks: Pending Verification List

**Input**: Design documents from `specs/001-pending-verification-list/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、
`contracts/mcp-tools.md`、`contracts/http-api.md`、quickstart.md（全部
已產出，見同目錄）

**Tests**: 本功能包含測試任務——不是套用範本的預設選項，而是依
`research.md` 決策4與 `CLAUDE.md` 2026-08-22 兩則教訓紀錄（新表上線
必須測併發，否則正式環境會炸）明確要求；測試任務標記方式與其他任務
相同，不另外用 OPTIONAL 標記。

**Organization**：依 `spec.md` 4 個 User Story（US1~US4）分組。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行執行（不同檔案、無相依）
- **[Story]**：對應 spec.md 的 US1~US4
- 每個任務都含明確檔案路徑

## Path Conventions

延伸既有三層架構，不是新專案：
- `poc/kb-mcp/`：資料層與 MCP server（純標準庫，Python 3.9 相容）
- `app/`：FastAPI 後端（`app/routers/`、`app/tests/`）
- `web/src/`：React 前端

---

## Phase 1: Setup

**Purpose**：新增資料表定義，其餘既有專案結構/依賴不需變動（見
`plan.md` Technical Context——無新增套件）

- [X] T001 在 `poc/kb-mcp/kb_store.py` 的 `SCHEMA` 常數新增
  `pending_verifications` 表定義（欄位與型別見 `data-model.md`），沿用
  既有 `CREATE TABLE IF NOT EXISTS` 風格；因為是全新表，不需要
  `_MIGRATIONS`／`_migrate()` 遷移項目

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**：US3／US4（標記解決）需要先能查到單筆項目目前的狀態才能
判斷「是否已是終態」，這是所有標記解決情境的共同前提

**⚠️ CRITICAL**：本階段完成前，US3／US4 無法開始；US1／US2 不依賴本階段

- [X] T002 [P] 在 `poc/kb-mcp/kb_store.py` 實作
  `KBStore.get_pending_verification(id)`，回傳單筆完整內容或 `None`
  （查無資料）——依賴 T001

**Checkpoint**：Foundational 完成後，US3／US4 可以開始；US1／US2 本來就
可以跟 Setup 完成後立刻平行開始

---

## Phase 3: User Story 1 - 登記待驗證判斷 (Priority: P1) 🎯 MVP

**Goal**：使用者能透過 Claude／MCP tool 登記一筆帶觸發條件與預期時間點
的待觀察判斷

**Independent Test**：呼叫 `save_pending_verification` MCP tool 登記一
筆項目，直接用 `get_pending_verification`／`list_pending_verifications`
查詢確認內容正確，不依賴首頁或標記解決功能

### Tests for User Story 1

- [X] T003 [P] [US1] 在 `poc/kb-mcp/tests/test_pending_verifications.py`
  新增 `save_pending_verification` 單元測試：成功登記案例；缺
  `judgment_text`／`trigger_type`／`trigger_condition_text` 各自被拒絕；
  `trigger_type=date` 卻缺 `trigger_date` 被拒絕；`trigger_type=event`
  可以不填 `trigger_date`（依 `data-model.md` 驗證規則、FR-001/FR-002）

### Implementation for User Story 1

- [X] T004 [US1] 在 `poc/kb-mcp/kb_store.py` 實作
  `KBStore.save_pending_verification(...)`：驗證必填欄位、
  `trigger_type=date` 時要求 `trigger_date`、寫入時
  `status='pending'`、`created_at`/`updated_at` 自動填入，回傳新建記錄
  完整內容——依賴 T001，須讓 T003 全數通過
- [X] T005 [US1] 在 `poc/kb-mcp/server.py` 的 `TOOLS` 清單新增
  `save_pending_verification` 工具 schema（見
  `contracts/mcp-tools.md`），並在既有 dispatch if/elif 鏈新增對應
  分支呼叫 `self.store.save_pending_verification(...)`——依賴 T004

**Checkpoint**：US1 完成後可獨立驗證——透過 MCP tool 登記，能查到剛登記
的內容（可先用 T002 的 `get_pending_verification` 驗證，不需等 US2）

---

## Phase 4: User Story 2 - 在 STND 首頁看到已到期的待驗證項目 (Priority: P1)

**Goal**：STND 首頁新增一個唯讀區塊，顯示已到期／即將到期且仍
`pending` 的待觀察項目——這是本功能要解決的核心痛點

**Independent Test**：預先在資料庫寫入一筆 `trigger_date` 已過、
`status=pending` 的項目，開啟首頁確認該項目出現在對應區塊；也可獨立於
US1 測試（直接寫測試資料，不透過 MCP tool 登記）

### Tests for User Story 2

- [X] T006 [P] [US2] 在 `poc/kb-mcp/tests/test_pending_verifications.py`
  新增 `list_pending_verifications` 單元測試：依 `status` 篩選；
  `due_only=True` 時只回傳 `trigger_date` 已過或在7天內、且
  `status=pending` 的項目；剛好在7天視窗邊界的案例；`trigger_date`
  為 `NULL`（event 類型未填日期）的項目不出現在 `due_only` 結果中
  （FR-003/FR-004，data-model.md Query Patterns，research.md 決策5）
- [X] T007 [P] [US2] 在 `app/tests/test_smoke.py` 新增
  `GET /api/pending-verifications` 測試：空清單回傳
  `{"items": []}`；有已到期項目時正確回傳；**併發測試**——至少30個
  併發 request，全數成功（比照 CLAUDE.md 2026-08-22 教訓紀錄，
  `finally:` 區塊位置需正確，避免對已關閉的 server 送請求）——依賴
  T009（endpoint 需先存在才能測）

### Implementation for User Story 2

- [X] T008 [US2] 在 `poc/kb-mcp/kb_store.py` 實作
  `KBStore.list_pending_verifications(status=None, due_only=False)`——
  依賴 T001，須讓 T006 全數通過
- [X] T009 [US2] 在 `poc/kb-mcp/server.py` 的 `TOOLS` 清單新增
  `list_pending_verifications` 工具 schema（見
  `contracts/mcp-tools.md`），並新增對應 dispatch 分支——依賴 T008
- [X] T010 [US2] 新增 `app/routers/pending_verifications.py`：
  `GET /api/pending-verifications`（query params `due_only`、
  `status`，見 `contracts/http-api.md`），比照
  `app/routers/assets.py` 風格（直接呼叫 `store.
  list_pending_verifications(...)`，不重寫商業邏輯）——依賴 T008
- [X] T011 [US2] 在 `app/main.py` 新增
  `app.include_router(pending_verifications_router.router)`——依賴
  T010
- [X] T012 [US2] 在 `web/src/pages/Home.jsx` 新增一個唯讀區塊：獨立
  `fetch` 呼叫 `GET /api/pending-verifications?due_only=true`，獨立
  `loading`/`error` state（比照既有 dashboard／holdings 兩區塊「互不
  阻塞」模式），顯示判斷內容＋觸發條件摘要；查詢失敗時顯示簡短錯誤
  提示、不擋首頁其他區塊（FR-008，spec.md Acceptance Scenario）——
  依賴 T010

**Checkpoint**：US1 + US2 完成後，MVP 可用——使用者能登記、且能在首頁
看到已到期項目，呼應 NVIDIA 案例的核心價值

---

## Phase 5: User Story 3 - 標記待觀察項目為已驗證，記錄結論 (Priority: P2)

**Goal**：使用者確認觸發事件已發生後，能將項目標記為已驗證並記錄結論

**Independent Test**：對一筆既有 `pending` 項目呼叫標記解決（
`status=resolved`），確認狀態轉換、結論與時間戳被記錄，且該項目不再
出現在 US2 的「已到期」查詢結果中

### Tests for User Story 3

- [X] T013 [P] [US3] 在 `poc/kb-mcp/tests/test_pending_verifications.py`
  新增 `resolve_pending_verification` 「resolved」路徑單元測試：
  成功案例（附 `resolution`，`resolved_at` 被寫入）；缺 `resolution`
  被拒絕；對已是 `resolved`／`dropped` 的項目再次呼叫被拒絕（終態不可
  逆，FR-007）；`id` 不存在時回傳明確錯誤（FR-005）

### Implementation for User Story 3

- [X] T014 [US3] 在 `poc/kb-mcp/kb_store.py` 實作
  `KBStore.resolve_pending_verification(id, status, resolution=None)`：
  `status='resolved'` 時要求 `resolution` 非空；檢查目前狀態是否已是
  終態（`resolved`／`dropped`）並拒絕；寫入 `resolved_at`；`id` 不存在
  時回傳明確錯誤——依賴 T001、T002，須讓 T013 全數通過（此方法同時
  服務 US4 的 `dropped` 路徑，見 Phase 6）
- [X] T015 [US3] 在 `poc/kb-mcp/server.py` 的 `TOOLS` 清單新增
  `get_pending_verification`（曝露 T002）與
  `resolve_pending_verification` 兩個工具 schema（見
  `contracts/mcp-tools.md`），並新增對應 dispatch 分支——依賴 T002、
  T014

**Checkpoint**：US1+US2+US3 完成後，「判斷→觸發→結果」完整軌跡可用——
標記已驗證後，項目從首頁消失但仍可透過 `get_pending_verification`
追溯

---

## Phase 6: User Story 4 - 標記待觀察項目為不再追蹤 (Priority: P3)

**Goal**：使用者能將不再重要的待觀察項目標記為不再追蹤

**Independent Test**：對一筆 `pending` 項目呼叫標記解決
（`status=dropped`），確認狀態轉換（`resolution` 為可選），且不再出現
在首頁「已到期」區塊

**實作說明**：`resolve_pending_verification`（T014）與其 MCP tool
（T015）已同時支援 `resolved`／`dropped` 兩種目標狀態——本階段只需要
補上 `dropped` 路徑專屬的測試案例，沒有新的實作任務

### Tests for User Story 4

- [X] T016 [P] [US4] 在 `poc/kb-mcp/tests/test_pending_verifications.py`
  新增 `resolve_pending_verification` 「dropped」路徑單元測試：成功案例
  （不附 `resolution`）；成功案例（附 `resolution` 說明原因）；對已是
  終態的項目再次呼叫被拒絕——依賴 T014

**Checkpoint**：全部 4 個 User Story 完成，功能範圍（product-spec.md
MVP In Scope）全數實作完畢

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**：跨故事的收尾工作

- [X] T017 依 `quickstart.md` 完整跑一次端到端案例（呼應 NVIDIA 案例：
  登記已到期項目→首頁看到→標記已驗證→首頁不再顯示→
  `get_pending_verification` 仍可查得完整歷史），使用獨立測試資料庫
  （`ALPHAVIBE_DATA_DIR` 指向 `poc/data-test/`，絕不可指向
  `poc/data/`）
- [X] T018 執行 `python3 -m unittest discover -s poc/kb-mcp/tests`
  確認全數綠燈（含 T003/T006/T013/T016 新增的測試，以及既有測試未被
  破壞）
- [X] T019 執行 `ALPHAVIBE_DATA_DIR=<獨立測試庫路徑> .venv/bin/python3
  -m app.tests.test_smoke` 確認全數綠燈（含 T007 新增的測試，含
  併發測試）
- [X] T020 在 `CLAUDE.md` 記錄協作慣例（呼應 pre-spec Q-004 選項C的
  PO 決定）：Claude 完成研究筆記時若識別出「待驗證」句型，主動建議
  使用者登記為待觀察項目——這是非程式邏輯的使用慣例，不是程式碼變更
  （FR-005 in spec.md／product-spec.md，本 repo 目前沒有獨立的「研究
  撰寫」skill，CLAUDE.md 是既有慣例記載的正確位置）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：無前置依賴
- **Foundational (Phase 2)**：依賴 Setup（T001）完成；只**阻擋 US3/US4**
  （US1/US2 不依賴 Foundational）
- **US1 (Phase 3)**：依賴 Setup（T001）完成，可與 US2 平行開始
- **US2 (Phase 4)**：依賴 Setup（T001）完成，可與 US1 平行開始（US1／
  US2 互不依賴——US2 的測試資料可直接寫入資料庫，不需透過 US1 的
  save API）
- **US3 (Phase 5)**：依賴 Foundational（T002）完成；不依賴 US1／US2
  （可直接對預先寫入的測試資料做標記解決）
- **US4 (Phase 6)**：依賴 US3（T014／T015，共用同一個
  `resolve_pending_verification` 實作）
- **Polish (Phase 7)**：依賴所有想要涵蓋的 User Story 完成（T017 端到
  端驗證需要 US1+US2+US3 全部完成才有意義；T020 不依賴任何程式任務，
  可隨時獨立進行）

### Parallel Opportunities

- Setup 完成後，US1（T003-T005）與 US2（T006-T012）可完全平行開發
  （不同檔案、不同商業邏輯）
- Foundational（T002）完成後，US3（T013-T015）可與 US1／US2 平行開發
- 同一 Phase 內標記 `[P]` 的任務可平行執行（例如 T003 與後續 US2 的
  T006/T007 分屬不同檔案）

---

## Parallel Example: User Story 1 + User Story 2（Setup後同時開始）

```bash
# Setup（T001）完成後，可同時派工：
Task: "T003 撰寫 save_pending_verification 單元測試（US1）"
Task: "T006 撰寫 list_pending_verifications 單元測試（US2）"

# 兩邊實作各自獨立進行：
Task: "T004 實作 KBStore.save_pending_verification()（US1）"
Task: "T008 實作 KBStore.list_pending_verifications()（US2）"
```

---

## Implementation Strategy

### MVP First（User Story 1 + User Story 2）

1. 完成 Phase 1：Setup（T001）
2. 完成 Phase 3：User Story 1（T003-T005）
3. 完成 Phase 4：User Story 2（T006-T012）
4. **停下驗證**：US1+US2 已經是可獨立交付的 MVP——使用者能登記、
   能在首頁看到已到期項目，呼應 product-spec.md 的核心價值主張
5. 如果只做到這裡就上線，「判斷→觸發→結果」的「結果」記錄部分（US3/
   US4）留待下一輪

### Incremental Delivery

1. Setup → Foundational → US1 → US2 →（可上線的 MVP，呼應 NVIDIA
   案例前半段：登記＋首頁提醒）
2. + US3 → 「已驗證」標記與結論記錄可用（呼應 NVIDIA 案例後半段：
   財報公布後回頭確認）
3. + US4 → 清單維護（不再追蹤）可用
4. + Polish → 端到端驗證、回歸測試、協作慣例文件化

---

## Notes

- 全部 4 個 User Story 都可以在 Setup 完成後立刻平行開始（US3/US4
  需先等 Foundational），符合 spec.md「每個 User Story 都可獨立測試、
  獨立交付」的設計
- 每個任務完成後建議各自 commit（比照本 repo既有 `speckit-git-commit`
  慣例／既有的頻繁小步提交風格）
- 測試任務（T003/T006/T007/T013/T016）為必要項目，非範本預設的
  可選項——理由見文件開頭「Tests」說明
- 避免：把多個 User Story 的邏輯混進同一個 commit、跳過併發測試
  （T007，這是本 repo 明確踩過的坑）
