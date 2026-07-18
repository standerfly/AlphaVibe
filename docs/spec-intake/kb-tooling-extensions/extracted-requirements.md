# Extracted Requirements: 知識庫查詢與易用性工具擴充

**Feature Slug:** kb-tooling-extensions
**Last Updated:** 2026-07-18

## Candidate Functional Requirements

- FR-1（SRC-001）：系統應提供常駐的知識庫檢視服務，在裝置重啟或程序異常終止後自動恢復，不依賴任何特定對話 session 存在
- FR-2（SRC-001）：系統應提供股票代碼快取機制，記錄已查證過的股票名稱與代碼對應，避免重複查證
- FR-3（SRC-001）：系統應提供批次寫入評論的能力，允許一次提交多筆評論，並在部分筆數不合法時仍寫入其餘合法筆數
- FR-4（SRC-001）：知識庫檢視頁在行動裝置（寬度 ≤640px）應以可讀的版面呈現表格內容，不需要橫向捲動
- FR-5（SRC-001）：知識庫檢視頁應能展開顯示投資哲學模組的完整內容，而非僅顯示檔名與大小
- FR-6（SRC-001）：系統應提供股票基本資料/產業分類查詢
- FR-7（SRC-001）：系統應提供股價歷史（開高低收）查詢，取代依賴新聞報導的不精確資料
- FR-8（SRC-001）：系統應提供月營收年增率查詢，無法計算時應明確回傳「無資料」而非臆測數字
- FR-9（SRC-001）：系統應提供三大法人（含外資）買賣超查詢

## Candidate Actors And User Goals

- Stander（PO/TPM/唯一使用者，SRC-001）：想要在跟 AI 討論股票時，減少因外部資料不足而反覆上網查證的次數與等待時間，並能在手機上方便查閱已累積的知識庫內容

## Candidate Success Criteria

- 常駐服務在 Mac 重啟/崩潰後不需人工介入即恢復運作（SRC-001）
- 同一檔股票代碼只需查證一次，之後直接命中快取（SRC-001）
- 批次貼上多筆交易/評論時，一次工具呼叫即可完成，不需逐筆呼叫（SRC-001）
- 檢視頁在手機瀏覽器開啟時，表格內容不需橫向捲動即可完整閱讀（SRC-001）
- 哲學模組可在頁面上直接展開閱讀全文（SRC-001）
- 4 個新查詢 API 均可對真實股票代碼查得結果，且外部資料失敗時不中斷整體流程（SRC-001）

## Candidate Constraints And Assumptions

- 沿用 `poc/kb-mcp` 既有的純 Python 標準庫、Python 3.9 相容架構，不引入外部依賴（SRC-001）
- FinMind 免費 API 額度限制（匿名 300 次/小時、有 token 600 次/小時），單檔查詢可行，全市場批次查詢多數需付費層，本次不做（SRC-001）
- 此為 Phase 1 PoC 範圍內的擴充，非 Phase 2 正式 production code（SRC-001，對應 AlphaVibe 專案 CLAUDE.md）
- 假設使用者是唯一使用者，無多人權限/角色需求（SRC-001）

## Candidate Error Or Failure Behavior

- 外部 API（FinMind）呼叫失敗時，回傳含錯誤訊息的結果，不中斷程式、不拋出未處理例外（SRC-001）
- 批次寫入時，個別筆數缺必填欄位應標記失敗原因，其餘合法筆數仍需成功寫入（SRC-001）
- 月營收年增率若找不到可比較的去年同月資料，應明確回傳 null，不得臆測或編造數字（SRC-001）

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001 | Unclear | `get_stock_info` 對單一股票代碼可能回傳多筆（FinMind 原始資料本身有重複的歷史產業分類記錄）；實作選擇原樣回傳不去重，但 product-spec 未明確定義這是否為期望行為 | Non-blocking | 見 clarification-log Q-001，屬既成實作的揭露事項，不阻塞規格審查，PO 可事後決定是否要求調整 |
