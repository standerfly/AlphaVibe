# Clarification Log: 外部內容知識庫（YouTube／Podcast／文章）

**Feature Slug:** external-content-kb
**Last Updated:** 2026-11-25

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 內容庫與 010 articles.db／011 substack.db 的關係 | SRC-001, SRC-003 | data | Answered | 獨立新庫（PO 於 SRC-001 已決定獨立 db）；查詢介面沿用既有 search／get 格式。選項 B（併 articles.db）、C（併 substack.db）已查證風險並排除：010 的 status 是抓取狀態機，語意不合（Claude 的判斷，未讀 010 程式碼逐行驗證）、且須重驗台美逐字比對；011 plan.md:115（位於 `011-substack-fetch-store` 分支）禁止第 1 包碰 app／server | Stander | 2026-11-19 |
| Q-002 | 長文進件路徑 | SRC-001, SRC-002, SRC-003 | workflow | Answered | 兩條路徑合一：「收件匣資料夾」——PO 把逐字稿存成檔案（開頭有中繼資料區塊）丟進資料匣，在 claude.ai 或本機 Claude Code 說「匯入」，由服務自行讀檔入庫，逐字稿不經過模型輸出。此決定取代原先「本機給路徑」入口。【Claude 補充，PO 2026-11-25 接受】claude.ai 直接收全文保留為短文備援（須標明耗 token） | Stander | 2026-11-25 |
| Q-003 | 同一來源再貼一次的行為 | SRC-001, SRC-003 | data | Answered | PO 同意推薦：以「平台＋影片 ID（Podcast 用 RSS guid）」為身分，不論連結寫法視為同一筆；重複時不新增，回報既有那筆並詢問是否用新內容取代全文（取代時保留既有已確認摘要）；全文雜湊相同但連結不同只警告不擋 | Stander | 2026-11-25 |
| Q-004 | 沒有連結的純文字來源（例：貼上文章全文、無 URL）如何識別 | SRC-001, SRC-003 | data | Answered | PO 同意：MVP 每筆必須有連結；無連結的檔案匯入時被擋下並指出缺連結；不支援以「標題＋日期」當身分的無連結流程（備選不採用） | Stander | 2026-11-25 |
| Q-005 | 摘要／觀點歸納的產生、確認、儲存方式 | SRC-001 | workflow | Answered | PO 同意推薦：全文與摘要分開存；摘要先在對話給草稿（此時不入庫），PO 明確同意才以「已確認」入庫；PO 拒絕、要求修改或沉默則不入庫；查詢時可區分原文與已確認摘要；不採「預設存成待確認」備選 | Stander | 2026-11-25 |
| Q-006 | 每筆必填中繼資料 | SRC-001 | data | Answered | 來源類型、連結、標題、頻道／作者、日期；固定標註「作者個人觀點，未經查證」（SRC-001） | Stander | 2026-11-19 |
| Q-007 | 首批驗收案例 | SRC-001, SRC-002 | success criteria | Answered | EP466 逐字稿（路徑 docs/research/2026-11-19-stockhermit-ep466-transcript.md，PO 自行存放；截至 2026-11-20 檔案尚未存在） | Stander | 2026-11-20 |
| Q-008 | 全文檢索的詞彙能力 | SRC-003 | success criteria | Answered（需求層） | 需求：2 字中文詞必須查得到、結果回傳命中片段而非整份全文。實作方式（LIKE 或其他）留給 plan 階段；LIKE 在文章數大時的重新評估點沿用 010（>5000 或變慢） | Stander | 2026-11-20 |
| Q-009 | 查詢工具暴露在哪些連接器（台股、美股、兩者；唯讀白名單） | SRC-001, SRC-003 | integration | Answered | PO 確認專案啟用台股、美股兩個連接器，並同意：搜尋與取全文在兩個連接器都提供（含唯讀端）；匯入、更新、刪除、確認摘要只放非唯讀端（claude.ai 連接器；本機 Claude Code 的完整 MCP 同屬非唯讀，依本 session 工具清單，須於 plan 階段確認）；專案指示加「討論投資先搜尋」 | Stander | 2026-11-25 |
| Q-010 | Podcast 的身分鍵 | SRC-003 | data | Deferred | 不詢問 PO；採建議做法（Podcast 優先 RSS guid／enclosure，只有平台頁連結時以連結本身當身分），細節留 Spec Kit plan | Stander | 2026-11-25 |
| Q-011 | 第三方內容的使用範圍 | SRC-003 | security | Answered | 不詢問 PO；列為需求假設：內容僅供 PO 個人使用，系統不提供對外公開、分享或匯出功能（PO 2026-11-25 表示不需要問與需求無關的確認） | Stander | 2026-11-25 |
| Q-012 | 是否做跨庫統一搜尋（含 010 定錨、011 Substack） | SRC-003 | scope | Deferred | 建議延後：日後新增一個工具依序唯讀各庫、合併輸出，不改任何既有表 | Stander | — |
| Q-013 | 入庫後的更正、更新全文、刪除流程 | SRC-001 | workflow | Answered | PO OK：第一版提供更新全文與刪除單筆；【「更新＝重新匯入同一來源並確認取代」為 Claude 補充的具體做法，PO 2026-11-25 接受】，刪除須 PO 明確確認、僅在非唯讀端 | Stander | 2026-11-25 |
| Q-014 | MVP 是否含網頁上傳端點（讓 claude.ai／手機也能不耗輸出 token 進件） | SRC-001, SRC-002, SRC-003 | scope | Answered | PO 同意：第一版不含網頁上傳端點；以收件匣資料夾取代。【Claude 補充，PO 2026-11-25 接受】手機存檔（如 iCloud）列為後續實測 | Stander | 2026-11-25 |
| Q-015 | 評論庫（Layer 3）內 3 筆 EP466 摘要是否刪除、是否遷入新庫 | SRC-001 | scope | Out of Scope | 不屬本功能；PO 傾向刪除但尚未明確指示，須先問 PO 才可動 | Stander | — |
| Q-016 | 內容相同但來源不同（同篇文章換網址；同一集 Podcast 同時有 YouTube 版與 RSS 版）如何處理 | 驗收發現 | data | Deferred | 不詢問 PO；採建議做法（不自動合併，以全文雜湊警告可能重複，由 PO 自行決定保留或刪除），細節留 plan | Stander | 2026-11-25 |
| Q-017 | 已確認摘要入庫後，能否撤回、修改、刪除 | 驗收發現 | workflow | Deferred | 不詢問 PO；採建議做法（已確認摘要可撤回與修改，修改視同重新確認須 PO 同意；僅非唯讀端），細節留 plan | Stander | 2026-11-25 |
| Q-018 | EP466 實際字數與 claude.ai 單次工具呼叫上限未知 | SRC-003, 驗收發現 | success criteria | Non-blocking | EP466 檔案存入後量測；claude.ai 上限於 plan 階段實測。實測前不承諾 claude.ai 路徑能處理任意長度 | Claude／Stander | — |
| Q-019 | 收件匣資料夾路徑 | SRC-002 | data | Answered | PO 同意：`poc/data/inbox/`（已以 git check-ignore 確認被 .gitignore 排除，第三方逐字稿不進 git）；不用 docs/research/。【Claude 補充】資料夾實作時才建立 | Stander | 2026-11-25 |
| Q-020 | 使用流程與 prompt 取得方式：PO 只需記三句話（存檔→說「匯入」→說「同意」）；查詢由專案指示讓 agent 自動先搜尋；更正／刪除用自然語言；每次匯入後附「下一步」提示 | SRC-002 | workflow | Answered | PO 同意三句話流程：(1)問 agent 取 prompt→存檔 (2)說「匯入」(3)說「同意」；查詢由專案指示讓 agent 自動先搜尋；更正／刪除用自然語言【匯入後附下一步提示為 Claude 補充，PO 2026-11-25 接受】 | Stander | 2026-11-25 |
| Q-021 | 每次使用時 PO 如何取得貼進 Google AI Studio 的 prompt | SRC-002 | workflow | Answered | PO OK：(1)專案指示內含 prompt 範本，對 claude.ai 說「給我逐字稿 prompt」取得；（AI Studio 儲存 prompt、repo runbook 留底：PO 2026-11-25 同意不列入需求，自行視需要使用） | Stander | 2026-11-25 |
| Q-022 | PO 實際使用流程：先貼連結給 agent，請 agent 建立資料匣與檔案，PO 再貼內容 | SRC-002 | workflow | Answered | PO 同意（2026-11-25，Accept 後修訂）：以「agent 建待匯入檔」為主要進件流程（建檔前先查重、中繼資料已填、內文空白、回報路徑）；「AI Studio 產出完整檔案」保留為另一種進件方式；claude.ai 不能建檔，故由服務端工具在資料匣建檔；標題／頻道／日期取不到時詢問 PO | Stander | 2026-11-25 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
- 目前 Blocking：無（0 項；原 5 項 Q-003／005／009／013／014 皆已於 2026-11-25 由 PO 回覆而結案）。
