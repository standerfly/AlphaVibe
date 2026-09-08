# Clarification Log: Us Stocks

**Feature Slug:** us-stocks
**Last Updated:** 2026-09-04

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 美股報價資料源要用哪一種？免費不穩定（如 yfinance，可能中斷/限流）vs 付費穩定（如 Alpha Vantage／Polygon，需申請 key、可能有費用）。這決定股價圖（FR-03）與關注條件比對（FR-06）能不能穩定運作。 | SRC-001「尚未在對話中決定」段 | Integration / Scope | Answered（三輪：手動→免費API多來源(按需)→免費API多來源(每日排程)） | **改用免費API多來源，每日一次背景排程自動刷新**。第一輪原答「如果有需要，我可以手動提供給agent處理」；第二輪查證FMP／Polygon.io／Alpha Vantage後決定「選用免費API，且多來源使用」（FMP為主要來源＋備援候選Alpha Vantage/yfinance），但當時仍維持「按需查詢，非背景排程」。**第三輪（2026-09-06，`/speckit.clarify`階段）**：PO主動推翻「按需查詢非排程」，改為「排程，碰觸到免費額度後，沒更新的顯示未更新（無額度）」；追問排程頻率，PO選擇「每天一次，比照台股market_scan.py先例」。最終定案：FMP為主要來源＋備援，**每日一次背景排程自動刷新**（收盤後執行），額度用盡時未刷新股票顯示「未更新（無額度）」，保留上次成功資料，不清空、不誤判為「資料不足」。備援來源最終選定與排程額度分配邏輯留待 speckit-plan 階段決定。 | Stander | 2026-09-04（第三輪：2026-09-06） |
| Q-002 | 關注條件碰觸門檻後，要怎麼讓使用者知道？repo 目前已有 Telegram 閘道（「管家」分頁，`function/stnd-gateway-web` 已上線）可以推播訊息——美股觸發警示要不要重用這個既有管道？還是 MVP 先只做「打開STND美股分頁才看得到」，主動通知留到之後？ | SRC-001 §4, §5 | Workflow / Integration | Answered | **推播**——重用既有 Telegram 閘道（`function/stnd-gateway-web`）主動通知，納入 MVP，從 Deferred 移除。 | Stander | 2026-09-04 |
| Q-003 | 交易截圖辨識結果有誤或欄位缺漏時，產品行為是什麼？是整批擋下要求重新上傳，還是允許使用者在核對畫面（mockup STEP 2）逐欄手動修正後才放行匯入？辨識完全失敗（例如截圖模糊、非交易紀錄畫面）時要怎麼提示？ | SRC-001 §4, §6；SRC-002 Import.dc.html | Error Handling | Answered | **手動核對**——不論辨識完整、部分失敗或完全失敗，一律進入核對畫面（mockup STEP 2）由使用者手動修正/補齊欄位，確認後才寫入；辨識結果永遠不自動落庫，人工核對是唯一防線。完全無法辨識時呈現空白核對表，由使用者手動輸入全部欄位。 | Stander | 2026-09-04 |
| Q-004 | 交易截圖可能包含帳戶末幾碼等個資，這些截圖原始檔要不要保留（供之後追溯核對用）？如果保留，存放位置/存取範圍有沒有特別要求（例如比照本機 repo 慣例不上雲端、或匯入完成後即刪除只留結構化資料）？ | 未在 SRC-001 直接提及，Claude 於 pre-spec 萃取階段主動提出的安全/隱私考量 | Security / Privacy | Answered | **不保留**，存放位置由 Claude 提議：截圖僅在「上傳→辨識→核對」流程中暫存（例如伺服器端 temp 目錄），使用者確認匯入或取消核對後立即刪除暫存檔，不寫入任何永久儲存位置（不進資料庫、不進 repo、不進雲端）；只有核對後的結構化交易資料（日期/代號/買賣/股數/價格）會被永久保存。 | Stander | 2026-09-04 |
| Q-005 | 美股獨立 KB（SRC-001 §9 已確認「要獨立」）具體怎麼實作——另開一套類似 `mcp__alphavibe-kb__*` 的 MCP 工具，還是同一個資料庫但用欄位/schema 隔離、在查詢層擋住跨市場查詢？ | SRC-001 §9 | Data / Integration | Deferred | 屬技術實作方案選擇，待 speckit-plan 階段依技術可行性決定；product-spec 只需記錄「必須獨立」這條產品約束 | — | — |
| Q-006 | 「結構化內容→STND頁面元件」的研究筆記渲染功能技術做法未定 | SRC-001「尚未在對話中決定」段 | Workflow | Deferred | 屬技術實作細節，待 speckit-plan 階段處理 | — | — |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
- Q-001 ~ Q-004 已於 2026-09-04 由 Stander 回答完畢，詳見上表 Answer Or Decision 欄。
- Q-005、Q-006 屬實作細節而非產品層決策，已標記 Deferred，不阻塞 product-spec 驗收，留待 speckit-plan 階段處理。
- **Q-001 第三輪（2026-09-06，發生在 `/speckit.clarify` 階段，`specs/003-us-stocks/`）**：
  PO 在技術規格澄清階段主動要求推翻第二輪「使用者/agent互動時按需查詢，
  非背景排程」的決定，改為「每日一次背景排程自動刷新（比照`market_scan.py`
  先例，收盤後執行）；當日碰觸免費API額度上限時，未刷新的股票顯示
  「未更新（無額度）」，保留上一次成功取得的資料與監控條件評估結果，
  不清空、不誤判為『資料不足』」。已回頭同步更新本 pre-spec 全部相關文件
  （product-spec.md／scope-decision.md／readiness-checks.md）與
  `specs/003-us-stocks/spec.md`（FR-006/007/011/013，新增FR-017）。
  這是 Accepted 文件的**追加修訂**，不是推翻整體驗收——product-spec.md
  Status 維持 Accepted，修訂記錄見該檔案頭部。
