# Product Spec: 知識庫查詢與易用性工具擴充

**Status:** In Review
**Feature Slug:** kb-tooling-extensions
**Function Branch:** function/alphavibe（本次依 PO 決定使用 `--no-branch`，未另建
`function/kb-tooling-extensions` 分支）
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** N/A
**Acceptance Evidence:** N/A（待 PO/TPM 正式核准後補上核准紀錄）

> 本規格為**回溯性文件**：所描述的全部功能已於 2026-07-18 在
> `poc/kb-mcp`（Phase 1 PoC）上完成開發，並各自通過獨立驗收 agent
> 確認（測試全綠、關鍵資料經真實 API 實測，非猜測）。撰寫本規格的目的
> 是補齊治理記錄，避免 PoC 範圍持續擴大卻沒有正式文件可追溯，不是要求
> 重新開發。

## Problem And Goal

Stander 於 2026-07-18 開始實際使用 `poc/kb-mcp` 知識庫，過程中連續遇到
四類具體困擾，導致操作效率低、資料可靠度不足：

1. 手機看不到已存入的資料（常駐服務未運作）
2. 記錄他人（朋友）交易紀錄時，逐筆呼叫工具、且陌生股票代碼要重複上網
   查證，耗費大量時間與 token
3. 檢視頁在手機上難以閱讀（寬表格需橫向捲動、哲學模組看不到內容）
4. 分析股票時，多次需要股價回檔幅度、月營收年增率、外資動向等資料，
   但既有工具不含這些，只能派 AI 上網搜尋，資料來源是「新聞報導的盤中
   價」而非官方數據，可靠度不足

目標：讓知識庫從「能存但難用、資料要現查」，變成「查詢有穩固後端資料源、
操作有效率、手機可隨時查閱」，作為使用者持續累積投資判斷紀錄的基礎工具。

## Business Context And Priority

- Priority：高——使用者明確表示這是「一直做不好這個投資系統」的根因，
  必須先解決才能繼續累積使用
- Timing：即時處理，於發現當天（2026-07-18）完成開發並驗收
- Business value：降低每次記錄/分析股票的操作成本與資料不確定性，是
  Phase 1b「試用累積」階段能否持續下去的前提

## Actors

- Stander（PO/TPM/唯一使用者）：透過與 Claude 對話使用知識庫，記錄自己
  與他人的股票判斷、查詢外部數據、回顧歷史紀錄

## MVP Scope

### In Scope

1. **常駐檢視服務**：`report_server.py` 常駐運行（macOS launchd 服務
   `com.alphavibe.reportserver`，`RunAtLoad`+`KeepAlive`），不依賴對話
   session 存在
2. **股票代碼快取**：`stock_aliases` 表 + `save_stock_alias`/
   `get_stock_alias` 工具，記錄查證過的股票名稱→代碼對應
3. **批次存入評論**：`save_comments_batch` 工具，一次提交多筆評論，
   部分筆數不合法時其餘合法筆數仍寫入
4. **檢視頁行動裝置優化**：表格於窄螢幕（≤640px）改為卡片式版面；
   哲學模組改為可展開顯示全文
5. **股票基本資料/產業分類查詢**：`get_stock_info`
6. **股價歷史查詢**：`get_stock_price_history`（開高低收）
7. **月營收年增率查詢**：`get_revenue_yoy`
8. **三大法人買賣超查詢**：`get_institutional_trading`（含外資淨買賣
   加總 `foreign_net`）

### Out Of Scope

- 法人 EPS 預估／上修下修查詢
- 重大訊息／法說會摘要查詢
- 不帶單一股票代碼的全市場批次查詢
- 手機端「跟 AI 對話並直接存資料」（需服務化上雲，屬 Phase 2）

### Deferred

- 法人 EPS 預估、重大訊息摘要：待未來評估資料源可行性後再排入
- `get_stock_info` 多筆不去重的行為調整（如 PO 未來要求）

## Functional Requirements

- FR-1：常駐檢視服務應在裝置重啟或程序異常終止後自動恢復運作
- FR-2：系統應能記錄「股票名稱→代碼」的查證結果，供後續同名查詢直接
  命中快取，同名再次寫入視為更新既有記錄
- FR-3：系統應能一次接受多筆評論寫入請求；其中缺少必填欄位（`body`、
  `source_tag`）的筆數應標記失敗原因，不影響其餘合法筆數的寫入結果
- FR-4：檢視頁的立場/快照/持股表格，在寬度 ≤640px 的裝置上應以卡片式
  版面呈現（不需橫向捲動），寬度 >640px 維持原本表格版面
- FR-5：檢視頁應能以可展開/收合的方式呈現投資哲學模組的完整文字內容
- FR-6：系統應能查詢指定股票代碼（或全部）的官方基本資料，含產業分類
- FR-7：系統應能查詢指定股票代碼在指定日期區間的日成交價（開高低收）
- FR-8：系統應能查詢指定股票代碼近期每月營收，並計算年增率（今年當月
  vs 去年同月）；找不到可比較的去年同月資料時，該月年增率應回傳
  null，不得臆測
- FR-9：系統應能查詢指定股票代碼在指定日期區間的三大法人買賣超，並
  提供外資（含外資自營商）淨買賣超的加總欄位

## Acceptance Scenarios

1. Mac 重新開機後，使用者未執行任何指令，手機開啟檢視頁網址即可看到
   最新資料（驗證 FR-1）
2. 使用者提供一個先前查過的股票名稱，系統直接回傳快取的代碼，不觸發
   新的查證流程（驗證 FR-2）
3. 使用者一次貼上 15 筆交易紀錄（其中 1 筆缺必填欄位），系統回報
   14 筆成功、1 筆失敗及原因，資料庫中確實只新增 14 筆（驗證 FR-3）
4. 使用者以手機瀏覽器（寬度 <640px）開啟檢視頁，立場表格以卡片呈現，
   每張卡片可讀完整欄位內容，不需左右滑動（驗證 FR-4）
5. 使用者在檢視頁點擊哲學模組標題，該模組完整文字內容展開顯示
   （驗證 FR-5）
6. 使用者查詢一檔股票的基本資料，取得產業分類與市場別（驗證 FR-6）
7. 使用者查詢一檔股票近 90 天的股價歷史，取得每日開高低收數據
   （驗證 FR-7）
8. 使用者查詢一檔股票的月營收年增率，對有去年同期資料的月份取得正確
   計算值，對沒有的月份取得 null（驗證 FR-8）
9. 使用者查詢一檔股票近 30 天的三大法人買賣超，取得逐日各類別數據與
   外資淨買賣超加總（驗證 FR-9）

## Success Criteria

- 常駐服務可用性：Mac 開機後不需人工介入即可存取檢視頁（可觀察）
- 股票代碼重複查證次數：同一檔股票查過一次後，後續不再觸發網路查證
  agent（可觀察，比對 `stock_aliases` 表命中率）
- 批次寫入效率：多筆評論寫入所需工具呼叫次數從「筆數次」降為「1 次」
  （可觀察）
- 手機可讀性：檢視頁表格內容在 ≤640px 裝置上不需橫向捲動即可完整閱讀
  （可觀察，人工驗證）
- 資料可靠度：股價回檔幅度、月營收年增率、外資動向改為直接查詢官方
  API，不再需要引用「新聞報導盤中價」作為分析依據（可觀察，比對後續
  分析是否還出現「未查得」「精確度有限」等資料品質警語）

## Constraints And Assumptions

- 沿用 `poc/kb-mcp` 既有純 Python 標準庫、Python 3.9 相容架構，不引入
  外部依賴（本機環境限制，已記錄於 AlphaVibe 專案 CLAUDE.md 教訓紀錄）
- FinMind API：免費層額度為匿名 300 次/小時、有 token 600 次/小時；
  單檔（帶 `data_id`）查詢皆可用免費層，全市場批次查詢多數需付費
  Backer/Sponsor（本次不做）
- 假設使用者是唯一使用者，無多人權限/角色需求
- 此為 Phase 1 PoC 範圍內的擴充，非 Phase 2 正式 production code；
  若未來 `poc/kb-mcp` 的範圍持續成長，建議另外評估是否該啟動 Phase 2
  正式規格流程

## Dependencies

- FinMind 台股開放資料 API（`https://api.finmindtrade.com`）：股票基本
  資料、股價歷史、月營收、三大法人買賣超四個 dataset
- macOS `launchd`：常駐服務的作業系統層級依賴
- 既有 `poc/kb-mcp` 三層知識庫架構（`kb_store.py`/`server.py`/
  `finmind_client.py`）

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| FinMind API 逾時或回傳錯誤 | 不拋出未處理例外，回傳含錯誤訊息的結果 | 呼叫端（AI/使用者）看到 `errors` 欄位說明失敗原因 | 使用者可重新查詢或改查其他資料源 | 否 |
| 批次評論中個別筆數缺必填欄位 | 該筆標記失敗與原因，其餘合法筆數正常寫入 | 回傳成功/失敗筆數與各自結果 | 使用者補齊欄位後單獨重新提交該筆 | 否 |
| 月營收年增率找不到去年同月資料 | 該月 `yoy_growth` 回傳 null | 呼叫端看到明確的 null 值而非錯誤數字 | 使用者可自行查證更早期資料或接受無此月份數據 | 否 |
| 常駐服務程序異常終止 | launchd `KeepAlive` 自動重啟 | 使用者下次開啟檢視頁應可正常存取（若重啟中會短暫無法連線） | 若重啟後仍異常，需人工檢查 log（`~/Library/Logs/alphavibe-report-server.err.log`） | 否 |
| `get_stock_info` 查到重複歷史分類記錄 | 原樣回傳全部筆數，不猜測去重 | 呼叫端看到多筆記錄，需自行判斷取用哪一筆（多為近期 `date`） | 無需復原，屬已知行為（見 Q-001） | 否 |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Complete | supporting-artifacts/readiness-checks.md | ADR-0027 要求 |
| API Contract（工具清單） | Yes | Complete | `poc/kb-mcp/README.md` | 涉及新增 MCP 工具行為 |
| Integration Note（FinMind） | Yes | Complete | `poc/kb-mcp/finmind_client.py`（程式碼即文件，逾時/失敗語意見上表 Error Handling） | 第三方 API 整合 |
| Data Model Note（股票代碼快取） | Yes | Complete | `poc/kb-mcp/kb_store.py`（`stock_aliases` schema） | 新增資料表 |
| Validation/Partial-Failure Policy（批次寫入） | Yes | Complete | `poc/kb-mcp/kb_store.py`（`save_comments_batch`） | 批次處理需求 |

## Source Decisions

- 全部功能範圍與優先序：SRC-001（2026-07-18 對話紀錄摘要）
- 分支策略（`--no-branch`）：Q-002
- pre-spec 回溯範圍：Q-003
- 不使用 Cline 執行開發：Q-004
- 法人 EPS 預估/重大訊息摘要排除範圍：Q-005
- `get_stock_info` 多筆不去重：Q-001（非阻塞）
