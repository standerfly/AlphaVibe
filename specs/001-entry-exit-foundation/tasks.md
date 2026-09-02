---
description: 001-entry-exit-foundation 的可執行任務清單
---

# Tasks: 進出場分析基礎層（損益追蹤與價位定位）

**Branch**: `001-entry-exit-foundation` | **Date**: 2026-09-02
**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/mcp-tools.md](contracts/mcp-tools.md)

## Format: `[ID] [P?] [Story] Description`

- `[P]`＝可與同區塊其他 `[P]` 任務平行（不同檔案、無未完成依賴）
- `[US1]`/`[US2]`/`[US3]`＝對應 spec.md 的使用者故事；Setup／Foundational／
  Polish 階段不掛故事標籤

## Path Conventions

商業邏輯一律在 `poc/kb-mcp/`，測試在 `poc/kb-mcp/tests/`。
本階段**不動** `report.py`、`app/routers/stock_detail.py`、`holdings_sync.py`，
以及 `review_engine.py` 的既有函式（只 `import` 其 `_percentile`）。

## ⚠️ 全域紅線（每個任務都適用）

- **股數單位是「股」不是「張」**（research.md R-001）：金額＝`股數 × 價格`，
  **不可 ×1000**。這是本功能最高風險項，寫測試時用真實案例固定住
  （大立光買 3 @2605 ＝ 7,815 元）。
- **絕不對正式庫 `poc/data/` 寫入**。測試一律 `tempfile.mkdtemp()` ＋
  `KBStore(tmp)`、tearDown `shutil.rmtree`（範本 `tests/test_holdings_sync.py:24-30`）。
  2026-08-22 曾發生正式庫被測試污染兩次的事故。
- Python 3.9 相容；`poc/kb-mcp/` 零外部依賴；註解與文件繁體中文。

---

## Phase 1: Setup

- [X] T001 執行 `python3 -m unittest discover -s poc/kb-mcp/tests` 記錄改動前的
      基準測試數（目前應為 15 檔 / 657 個 test 全綠），作為後續回歸比對基準

---

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T002 在 `poc/kb-mcp/pnl.py` 建立模組骨架與共用的現價取得 helper
      `resolve_current_price(code, prices)`：輸入 `get_stock_prices()` 回傳的
      dict，輸出 `(price, price_date)`，查無資料回 `(None, None)`。純函式不碰 I/O
      （FR-002、FR-007 共用）

---

## Phase 3: User Story 1 - 查詢持股的真實損益 (Priority: P1) 🎯 MVP

**Goal**：單一標的的 FIFO 已實現／未實現損益可透過 MCP 工具查得。

**Independent Test**：對任一有完整買賣紀錄的標的呼叫 `get_position_pnl`，
與手動依 FIFO 從 `get_trade_ledger` 原始列推算的結果比對，數字一致。

### Tests for User Story 1

- [X] T003 [P] [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 寫 FIFO 基本情境測試：
      多筆買進後部分賣出，驗證已實現損益＝配對批次的 `(賣價-買價)×股數` 加總、
      未實現損益＝剩餘批次以現價計（FR-001、FR-002）
- [X] T004 [P] [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 寫**單位固定測試**：
      用大立光真實案例（買 3 @2605）斷言成本為 7,815 元而非 7,815,000，
      防止未來有人誤加 ×1000（research.md R-001）
- [X] T005 [P] [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 寫賣超情境測試：
      賣出股數 > 買進股數時回 `status="history_incomplete"` ＋
      `shortfall_shares`，且不輸出未實現損益、不捏造成本（FR-004）
- [X] T006 [P] [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 寫無現價與已出清情境：
      查無現價回 `status="no_price"` 但已實現損益照常；已全數出清的標的
      仍回傳已實現損益（FR-003）
- [X] T007 [P] [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 寫重複列警示測試：
      同 code/action/shares/price/date 的多餘列**照原樣計入**，且
      `suspected_duplicates` 回報正確筆數（FR-006）

### Implementation for User Story 1

- [X] T008 [US1] 在 `poc/kb-mcp/pnl.py` 實作 FIFO 佇列引擎
      `compute_position_pnl(code, entries, prices)`：依 `(date, id)` 排序，
      「買」推入佇列、「賣」從前端消耗並累計已實現損益；`action` 只認中文
      「買」/「賣」（`kb_store.py:1141-1142` 的既有值域）（FR-001、FR-002）
- [X] T009 [US1] 在 `poc/kb-mcp/pnl.py` 實作 status 判定與結果組裝，順序依
      `data-model.md`「狀態轉換」節：`no_trades` → `history_incomplete` →
      `no_price` → `ok`；固定附上 `cost_method="FIFO"`、`fees_included=False`
      （FR-003、FR-004、FR-005、FR-006）
- [X] T010 [US1] 在 `poc/kb-mcp/server.py` 的 `TOOLS` list 新增
      `get_position_pnl` 定義（name／description／inputSchema，`code` 為選填），
      格式比照 `get_trade_ledger`（`server.py:439-448`）（FR-012）
- [X] T011 [US1] 在 `poc/kb-mcp/server.py` 的 dispatch 區塊（`:820` 起）新增
      `get_position_pnl` 分支，比照 `get_trade_ledger`（`:968-969`）（FR-012）
- [X] T012 [US1] 在 `poc/kb-mcp/server_readonly.py` 的 `READONLY_TOOLS`
      白名單（`:22-32`）加入 `get_position_pnl`——**漏加會讓工具在 Cline
      唯讀路徑上靜默消失**（FR-012）
- [X] T013 [US1] 在 `poc/kb-mcp/tests/test_pnl.py` 新增**註冊守門測試**：
      斷言 `get_position_pnl` 同時存在於 `server.TOOLS`、dispatch 可呼叫、
      以及 `server_readonly.READONLY_TOOLS`——目前 repo 完全沒有這類守門測試
      （grep 在 `tests/` 下 0 命中），三處漏一處不會被抓到

**Checkpoint**：US1 完成後即可用（單檔損益查詢），可獨立交付。

---

## Phase 4: User Story 2 - 判斷價位在歷史區間的高低 (Priority: P2)

**Goal**：單一標的的現價歷史百分位可透過 MCP 工具查得，且資料不足時
明確說「不知道」而非給誤導數字。

**Independent Test**：對有足夠樣本的標的查詢並人工用同一段收盤價驗算；
對樣本不足的標的查詢，確認回傳 `percentile: null` 而非 0。

### Tests for User Story 2

- [X] T014 [P] [US2] 在 `poc/kb-mcp/tests/test_price_position.py` 寫百分位
      計算測試：樣本 ≥30 時回 `status="ok"` ＋正確百分位，並驗證
      `sample_size`／`range_start`／`range_end` 與輸入序列一致（FR-007、FR-008）
- [X] T015 [P] [US2] 在 `poc/kb-mcp/tests/test_price_position.py` 寫三段式
      降級測試：6–29 筆回 `status="limited"` 且 `basis` 字串明講樣本不足；
      <6 筆回 `status="insufficient"` 且 **`percentile` 必須是 None**；
      無資料回 `status="no_data"`（FR-009）
- [X] T016 [P] [US2] 在 `poc/kb-mcp/tests/test_price_position.py` 寫防呆測試：
      斷言資料不足時**不會**回傳 0、0.0 或空字串等會被誤讀為「在最低點」
      的值（FR-009 的核心風險）

### Implementation for User Story 2

- [X] T017 [US2] 建立 `poc/kb-mcp/price_position.py`，實作
      `compute(code, history_rows, prices)`：純函式，輸入
      `get_cached_price_history()` 的列與現價 dict，輸出 `PricePosition`
      結構（欄位見 `data-model.md`）；百分位計算 `import` 既有
      `review_engine._percentile`，**不重寫**（FR-007、FR-008）
- [X] T018 [US2] 在 `poc/kb-mcp/price_position.py` 實作三段式門檻，沿用
      `review_engine` 既有常數語意（`PERCENTILE_MIN_POINTS=30`、
      `MIN_PER_HISTORY_POINTS=6`），並在 `basis` 產出人類可讀的依據說明
      （FR-009）
- [X] T019 [US2] 在 `poc/kb-mcp/server.py` 的 `TOOLS` list 與 dispatch 區塊
      新增 `get_price_position`（兩處），格式同 T010／T011（FR-012）
- [X] T020 [US2] 在 `poc/kb-mcp/server_readonly.py` 的 `READONLY_TOOLS`
      加入 `get_price_position`，並擴充 T013 的守門測試涵蓋這個工具（FR-012）

**Checkpoint**：US1＋US2 完成後，兩項核心查詢皆可單檔使用。

---

## Phase 5: User Story 3 - 一次看完整個投資組合 (Priority: P3)

**Goal**：省略 `code` 即可一次取得全部標的結果，單一標的的資料問題不會
讓整批查詢失敗。

**Independent Test**：全量查詢的每檔結果與逐檔查詢一致，且至少一檔
`history_incomplete` 的標的不會中斷整批。

### Tests for User Story 3

- [X] T021 [P] [US3] 在 `poc/kb-mcp/tests/test_kb.py` 寫
      `get_all_trade_entries()` 的存取測試：回傳全部交易列且排序為
      `code, date, id`，不影響既有 `get_trade_ledger(code)` 的行為
- [X] T022 [P] [US3] 在 `poc/kb-mcp/tests/test_pnl.py` 寫批次隔離測試：
      同一批資料中混入賣超標的與無現價標的，驗證每檔各自回傳正確 status、
      **任何單檔問題都不讓整批拋例外**（FR-011）

### Implementation for User Story 3

- [X] T023 [US3] 在 `poc/kb-mcp/kb_store.py` 新增
      `get_all_trade_entries()`（單一查詢 `ORDER BY code, date, id`），
      **不修改**既有 `get_trade_ledger`（`:1158-1166`）以免影響現有呼叫端
- [X] T024 [US3] 在 `poc/kb-mcp/pnl.py` 新增 `compute_all_positions(entries, prices)`：
      以 `code` 分組後逐檔呼叫 T008 的引擎，每檔獨立 try 保護，並產出
      `summary` 各 status 計數（FR-011）
- [X] T025 [US3] 在 `poc/kb-mcp/price_position.py` 新增全量模式，並在
      `poc/kb-mcp/server.py` 讓兩個工具的 `code` 省略時走全量路徑
      （回傳結構見 `contracts/mcp-tools.md`）（FR-011、FR-012）

**Checkpoint**：三個故事全部完成，階段A 功能齊備。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] 在 `poc/kb-mcp/screener.py` 將 `PRICE_WINDOW_DAYS` 由 120
      改為 400（FR-014），**並以單一標的實測**外部來源回應正常：
      `python3 -c "import screener; print(len(screener._fetch_prices_with_fallback('2330')))"`。
      **只測一檔**——2026-07-28 曾因密集測試把 FinMind 匿名額度打光、
      連累當晚 02:00 正式排程。實測結果（筆數、是否有截斷）寫回
      `research.md` R-006；若回應異常則降為 250 天並記錄原因
- [X] T027 [P] 在 `poc/kb-mcp/tests/test_traceability.py` 登記 FR-001~FR-014
      的需求↔實作↔測試對照（本 repo 的守門測試慣例）
- [X] T028 [P] 校正 `poc/kb-mcp/server_readonly.py:7-9` docstring 中過時的
      工具數字（現寫「40 個工具／23 個唯讀」，實際改動前為 43／26，
      本階段完成後應為 45／28）
- [X] T029 [P] 統一 `poc/kb-mcp/server.py:270` 的參數描述用字——目前寫
      「股數/張數」語意含混，`:397`／`:431` 寫「股數」；依 research.md R-001
      的結論統一為「股數（單位：股）」
- [X] T030 執行完整回歸 `python3 -m unittest discover -s poc/kb-mcp/tests`，
      與 T001 的基準數字比對（應為 657 ＋ 本次新增數，且 0 失敗）
- [ ] T031 依 `~/.claude/rules/10-model-dispatch.md` 第 6 節「驗證不自驗」，
      派 fresh-context agent 對照 spec.md 的 14 條 FR 逐條驗收，
      **不由實作者自行宣告完成**；驗收 prompt 必須含否決條件

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (T001 基準)
  └─> Phase 2 (T002 共用 helper)
        ├─> Phase 3 US1 (T003–T013)  ← MVP，可獨立交付
        ├─> Phase 4 US2 (T014–T020)  ← 不依賴 US1，可平行
        └─> Phase 5 US3 (T021–T025)  ← 依賴 US1 的引擎（T008）與 US2 的模組（T017）
              └─> Phase 6 Polish (T026–T031)
```

### User Story Dependencies

- **US1**：只依賴 T002。完成即可獨立交付（單檔損益查詢）。
- **US2**：只依賴 T002，**與 US1 無依賴關係**，兩者可平行開發。
- **US3**：依賴 T008（FIFO 引擎）與 T017（百分位模組）——批次是在兩者
  之上加一層分組與隔離。

### Parallel Opportunities

- **US1 的測試 T003–T007**：全部同一檔但互不相干的測試方法，可一次寫完
  再一起跑
- **US1 與 US2 整個階段可平行**（不同模組檔案：`pnl.py` vs
  `price_position.py`），唯一交會點是 `server.py` 的註冊——建議先後進行
  避免同檔衝突
- **Polish 的 T026–T029** 互為不同檔案，可平行

## Implementation Strategy

**MVP ＝ Phase 1 + 2 + 3（US1）**：完成 T001–T013 即可解決 2026-09-01
事故的核心痛點（人工拼湊損益），此時已可交付使用。

US2 與 US3 為增量：US2 補上價位定位，US3 補上批次便利性。
Phase 6 的 T031（獨立驗收）**不可省略**——這是 repo 的既有制度要求。

## 任務統計

- 總任務數：**31**
- Setup：1／Foundational：1／US1：11／US2：7／US3：5／Polish：6
- 標註 `[P]` 可平行：14
