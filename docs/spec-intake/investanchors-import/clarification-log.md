# Clarification Log: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-14

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 要抓哪些分類？ | SRC-001 | Scope | Answered | （已被 Q-017 取代）原答覆：台股、美股、週報 | Stander | 2026-11-12 |
| Q-002 | 歷史資料要回補嗎？如何避免被擋？ | SRC-001 | Scope／Import | Answered | （回補範圍已被 Q-022 改為半年內）原答覆：全部回補；排程不定時、分批 | Stander | 2026-11-12 |
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
| Q-019 | 排程時段？（規劃階段提出） | spec 010 research R8 | Workflow | Answered | 一天一次，每晚 23:00；每日登入上限由 2 次改為 1 次。影響：歷史回補每天最多 5 篇，總天數待探查總篇數後估算 | Stander | 2026-11-14 |
| Q-020 | 表格轉寫上線前抽查的標準？ | spec 010 research R5 | Data | Answered | 抽 10 張真實表格圖，轉寫數字由 PO 本人確認，PO 認可才採用；不設百分比門檻 | Stander | 2026-11-14 |
| Q-021 | 是否同意把表格圖送模型 API 轉寫？ | spec 010 research R5 | Security | Answered | 同意（agree） | Stander | 2026-11-14 |
| Q-022 | 歷史回補要補多久以前的文章？ | SRC-007 | Scope／Import | Answered | 只補最近半年內；更早的先標記不抓，有需要再補。取代 Q-002 的「全部回補」。PO 另提供：網站發文頻率約每週 2～5 篇（半年約 50～130 篇，以每天 5 篇計約 11～26 天） | Stander | 2026-11-15 |
| Q-023 | 兩次網站探查（2026-11-15，PO 在場）的結果如何影響需求？ | spec 010 research R0 | Integration／Data | Answered | 成立：email＋密碼登入、伺服器端登出可驗證、`?page=` 分頁、表格是圖片、開文章會改已讀（Q-004 已接受）、手機一台＋排程一台時排程登入登出不影響手機（PO 回報）。修正：半年截止改用文章 ID 推得的建立時間，不用清單日期（置頂的近期文章清單日期顯示 2021 年）；清單置頂項跨頁重複須去重；標題取自清單連結文字；一篇可能只有 1 張長圖，轉寫前需切片；半年內約 100 篇、約 20 天補完。未決：通知信連結形態與篇數落差（免登入補查中） | Stander／Claude | 2026-11-15 |
| Q-024 | 沒有通知信的文章靠定期核對補抓，核對頻率？ | spec 010 research R12 | Workflow | Non-blocking | 選項：每週一次（最慢約 7 天）／每週兩次（約 4 天）／每天（約 1 天，幾乎每天登入）。待通知信落差分析後由 PO 決定；目前維持每週一次 | Stander | 待回覆 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
