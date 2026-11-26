# Extracted Requirements: 外部內容知識庫（YouTube／Podcast／文章）

**Feature Slug:** external-content-kb
**Last Updated:** 2026-11-25

## Candidate Functional Requirements

- CR-01 納入三種外部內容：YouTube 影片、Podcast、文章（SRC-001）。
- CR-02 第一階段由 PO 提供「連結＋逐字稿／全文」，系統負責儲存與檢索；自動抓字幕、Whisper 轉錄列為後續選項（SRC-001）。
- CR-03 儲存全文並可全文檢索，不是只存摘要（SRC-001）。
- CR-04 摘要／觀點歸納只能在 PO 確認後才入庫，不可自動寫入（SRC-001）。
- CR-05 每筆標註來源類型、連結、標題、頻道／作者、日期，並標明「作者個人觀點，未經查證」（SRC-001）。
- CR-06 使用獨立資料庫，不混進 alphavibe.db 評論庫（SRC-001「已做的決定」）。
- CR-07 查詢介面比照定錨文章的 search／get 模式；新增 MCP 工具需同步唯讀白名單與工具數守門測試（SRC-001、SRC-003）。
- CR-08 進件改為收件匣資料夾（PO 存檔、說「匯入」），本機 Claude Code 與 claude.ai 共用同一流程；claude.ai 直接收全文為短文備援（SRC-002、Q-002）。
- CR-12 PO 實際流程：先貼連結給 agent 建立資料匣與檔案，PO 再貼內容（SRC-002，2026-11-25 修訂，Q-022）。
- CR-09 長文寫入要避免由模型輸出整份逐字稿耗 token（SRC-001）。
- CR-10 同一連結再貼一次要有明確行為（去重）（SRC-001）。
- CR-11 EP466 逐字稿作為第一個驗收案例（SRC-001、SRC-002）。

## Candidate Actors And User Goals

- PO（Stander）：貼連結與逐字稿、確認摘要、在投資討論時查詢並引用外部內容。
- Claude（本機 Claude Code／claude.ai）：代 PO 呼叫匯入與查詢；產出摘要草稿供 PO 確認。
- 排程／其他系統：本階段無（自動抓取列為後續）。

## Candidate Success Criteria

- 外部內容全文可被查到，含 2 字中文詞（SRC-003：既有庫因 trigram 限制已踩過）。
- 查詢結果每筆都帶來源資訊與「作者個人觀點，未經查證」標註。
- 未經 PO 確認的摘要不會出現在庫裡。
- EP466 能完成「存檔→匯入→檢索→引用」全流程。

## Candidate Constraints And Assumptions

- 台股與美股連接器各自獨立（CLAUDE.md），查詢工具暴露範圍待決（Q-009）。
- claude.ai 只能呼叫 MCP 工具、不能寫 PO 本機檔案（SRC-003，推論）；ngrok／claude.ai 單次工具呼叫大小上限未查到，須實測。
- 011 規格尚未全部結清、未產生 tasks，不可假設能重用其元件（SRC-003）。
- 內容為第三方著作，僅供 PO 個人知識庫使用（假設，Q-011）。

## Candidate Error Or Failure Behavior

- 檔案路徑不存在／無法讀取／編碼錯誤；必要欄位缺漏；重複來源；超過進件大小上限；摘要未確認就嘗試入庫。

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001, SRC-002 | Conflict | CR-09「不耗輸出 token」與 claude.ai 路徑：連接器收全文必經模型輸出 | Closed（2026-11-25） | 以收件匣資料夾解決（Q-002）；網頁上傳不入 MVP（Q-014） |
| GAP-002 | SRC-001 | Unclear | 去重行為未指定 | Closed（2026-11-25） | Q-003 |
| GAP-003 | SRC-001 | Unclear | 「PO 確認」的流程與摘要儲存位置未指定 | Closed（2026-11-25） | Q-005 |
| GAP-004 | SRC-001 | Unclear | 無連結的來源（貼上純文字）如何識別 | Open | Q-004 |
| GAP-005 | SRC-001 | Unclear | 日後更正／更新／刪除已入庫內容的流程 | Closed（2026-11-25） | Q-013 |
| GAP-006 | SRC-001 | Unclear | 是否納入與 010／011 的跨庫統一搜尋 | Open | Q-012，建議延後 |
