# Clarification Log: 知識庫查詢與易用性工具擴充

**Feature Slug:** kb-tooling-extensions
**Last Updated:** 2026-07-18

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | `get_stock_info` 對單一股票代碼回傳多筆（FinMind 原始資料本身重複），是否需要去重？ | SRC-001 | Data | Non-blocking | 目前實作原樣回傳不去重，避免猜測該保留哪一筆；PO 知悉此行為，未要求變更 | Stander | 2026-07-18 |
| Q-002 | pre-spec 初始化預設以 `develop` 分支為基底，但本 repo 只有 `function/alphavibe`，無 `develop` | SRC-001 | Workflow | Answered | 使用 `--no-branch`，直接在現有分支建立 spec-intake 文件，不建新分支 | Stander | 2026-07-18 |
| Q-003 | 這批「回溯補 pre-spec」的範圍，應只涵蓋最後一批 4 個 FinMind API，還是涵蓋今天全部 `poc/kb-mcp` 擴充？ | SRC-001 | Scope | Answered | 回溯涵蓋全部：股票代碼快取、批次存入工具、手機版面優化、4 個 FinMind 查詢 API | Stander | 2026-07-18 |
| Q-004 | 這批開發工作是否應該用 Cline（而非 Claude）執行？ | SRC-001 | Workflow | Answered | 不使用 Cline。理由：任務需要理解既有架構慣例與做設計判斷，非機械式簡單工作；且本環境的 Claude 與 Cline 之間無串接介面，無法由 AI 端調度 | Stander | 2026-07-18 |
| Q-005 | 法人 EPS 預估、重大訊息摘要是否納入本輪查詢 API 範圍？ | SRC-001 | Scope | Deferred | 不納入本輪。資料源可行性不確定（EPS 共識預估通常是付費資料，FinMind 免費層可能沒有；重大訊息摘要需另外串接 MOPS，工程量較大），待未來有需要時再評估 | Stander | 2026-07-18 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
