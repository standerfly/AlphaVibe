# Clarification Log: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-14

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 要抓哪些分類？ | SRC-001 | Scope | Answered | （已被 Q-017 取代）原答覆：台股、美股、週報 | Stander | 2026-11-12 |
| Q-002 | 歷史資料要回補嗎？如何避免被擋？ | SRC-001 | Scope／Import | Answered | 全部回補；排程不定時、分批 | Stander | 2026-11-12 |
| Q-003 | 抓回後做什麼分析？ | SRC-001 | Scope | Answered | 先存全文；之後由 PO 與 LLM 討論，MVP 不做自動抽取 | Stander | 2026-11-12 |
| Q-004 | 爬蟲開啟文章會讓網站把文章標成「已讀」，是否接受？ | SRC-002 | Data／Integration | Answered | 接受：排程開啟文章導致網站標成已讀可以接受 | Stander | 2026-11-13 |
| Q-005 | 抓回的文章放哪、PO 怎麼跟 LLM 討論？（2026-11-13 複審補充選項） | SRC-001 | Data／API／Scope | Answered | 選項B：獨立文章庫＋新增「搜尋文章／讀取單篇」查詢工具；台股連接器看台股＋週報、美股連接器看美股；STND 閱讀頁 Deferred | Stander | 2026-11-13 |
| Q-006 | 週報與台股分類重疊時怎麼處理？ | SRC-002 | Data | Out of Scope | 不適用：Q-017 決定不分類，分類重疊問題消失 | Stander | 2026-11-14 |
| Q-007 | 文章內的圖片（表格圖）要存嗎？要讓 LLM 讀得到嗎？ | SRC-003 | Data／Scope | Answered | 表格數字是重點→**進 MVP**：圖片存檔，且表格圖的內容須讓 LLM 在討論時讀得到（轉文字或回傳圖片，做法於 plan 定）；轉出的文字須標示為機器轉寫、原圖可回查 | Stander | 2026-11-13 |
| Q-008 | 版權／服務條款：僅個人使用、不對外分享？ | SRC-001、SRC-004 | Security | Answered | 確認：僅 PO 個人使用、不對外分享；**務必低頻抓取，避免阻擋** | Stander | 2026-11-13 |
| Q-009 | 如何辨識並略過置頂公告？ | SRC-002 | Scope | Non-blocking | 採建議值（PO 未異議）：標題以「【公告】」開頭者略過 | Stander | 2026-11-13 |
| Q-010 | 文章留言（留言數顯示）要抓嗎？ | SRC-002 | Scope | Deferred | MVP 不抓留言 | Claude 提案 | 2026-11-12 |
| Q-011 | 條款規定同一帳號最多兩台裝置或瀏覽器上線，超過可停用帳號；排程的瀏覽器算一台。PO 平常用幾台看定錨？ | SRC-004 | Integration／Security | Answered | PO 只在手機或電腦間切換、不會同時上線；採建議：排程每次跑完即登出、不常駐登入狀態、避開 PO 常用時段 | Stander | 2026-11-13 |
| Q-012 | 抓到新文章時要不要 Telegram 通知（標題＋連結）？ | SRC-001 | Scope | Non-blocking | 採建議值（PO 未異議）：新文章 Telegram 通知，僅標題與連結 | Stander | 2026-11-13 |
| Q-013 | 清單是否分頁、文章網址形態、`lv=` 參數意義、登入狀態有效期、紅色數字是總數或未讀數 | SRC-002 | Integration | Non-blocking | 無法由截圖判斷；列為技術規劃第一步的 Mac 探查項目，不需 PO 決策 | Claude | 2026-11-13 |
| Q-014 | 每天掃描網站，還是 Gmail 有定錨新信才掃描？ | SRC-005 | Integration／Workflow | Answered | Gmail 新信觸發：平常只檢查 Gmail（寄件者 `postmaster@mailer.investanchors.com`，信內只有標題＋連結），有新信才登入網站抓文；另每週一次只讀清單做核對，補信件漏寄 | Stander | 2026-11-13 |
| Q-015 | 如何避免重複與過度掃描？重試有間隔嗎？ | SRC-005 | Import／Error handling | Answered | 不以「當日」判斷，以文章 ID 記帳：抓過不再開啟、清單碰到已抓過即停；失敗文章不在同一次執行內重試，留待下次排程（間隔以小時計），單篇累計失敗達上限即停止並通知；出現被擋跡象則整次中止並拉長下次間隔 | Stander | 2026-11-13 |
| Q-016 | 表格圖何時、用什麼轉成文字？ | SRC-005 | Data／Integration | Answered | 排程匯入時即轉成文字並存檔（之後可全文檢索表格數字）；採成本最低且抽查準確度合格的模型，起始用最低價位模型，抽查不合格才升級；原圖保留可回查 | Stander | 2026-11-13 |
| Q-017 | 要不要依分類取文章？ | SRC-006 | Scope／Data | Answered | 不分類：文章標題不好分類，FR-002 改為全部文章都取得、不存分類。連帶：連接器無法依分類分流，改為台股與美股連接器查同一個獨立文章庫 | Stander | 2026-11-14 |
| Q-018 | 【公告】類置頂文（會員權益、意見回饋）在「全部都要取得」之下要不要抓？ | SRC-002、SRC-006 | Scope | Non-blocking | 建議：維持略過（非研究內容）；PO 若要連公告也抓，移除 FR-004 即可 | Stander | 待回覆 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
