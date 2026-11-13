# Clarification Log: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-13

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 要抓哪些分類？ | SRC-001 | Scope | Answered | 台股、美股、週報（不含產業、總經） | Stander | 2026-11-12 |
| Q-002 | 歷史資料要回補嗎？如何避免被擋？ | SRC-001 | Scope／Import | Answered | 全部回補；排程不定時、分批 | Stander | 2026-11-12 |
| Q-003 | 抓回後做什麼分析？ | SRC-001 | Scope | Answered | 先存全文；之後由 PO 與 LLM 討論，MVP 不做自動抽取 | Stander | 2026-11-12 |
| Q-004 | 爬蟲開啟文章會讓網站把文章標成「已讀」，是否接受？ | SRC-002 | Data／Integration | Blocking | 建議：接受，但實測確認；若可避免（只讀清單／API）則優先避免 | Stander | 待回覆 |
| Q-005 | 抓回的文章放哪、PO 怎麼跟 LLM 討論？（2026-11-13 複審補充選項） | SRC-001 | Data／API／Scope | Blocking | 選項A：寫進既有 Layer 3 `comments`（`search_comments` 立即可用、零新工具、成本最低；但美股文章會進台股庫，違反台美獨立，且該表無唯一鍵、防重複要另做）。選項B（建議）：獨立文章庫＋新增「搜尋文章／讀取單篇」查詢工具，台/美連接器各自只看得到自己分類，週報歸台股側。STND 閱讀頁 Deferred | Stander | 待回覆 |
| Q-006 | 週報與台股分類重疊時怎麼處理？ | SRC-002 | Data | Non-blocking | 複審：五類數字相加＝總覽（31+13+17+32+21=114），推測各文章只屬一類、重疊不存在；仍以文章 ID 為唯一並容許多標籤作保險，Mac 實測確認 | Stander | 待回覆 |
| Q-007 | 文章內的圖片（表格圖）要存嗎？要讓 LLM 讀得到嗎？ | SRC-003 | Data／Scope | Non-blocking | 複審提醒：財測 EPS／本益比表格是**圖片**，只存全文時 LLM 討論看不到這些數字。建議：MVP 先存圖檔並與文章關聯；「讓 LLM 讀表格圖」（回傳圖片或轉文字）列第二階段，但 PO 若認為表格數字是討論重點，應提前進 MVP | Stander | 待回覆 |
| Q-008 | 版權／服務條款：僅個人使用、不對外分享？ | SRC-001、SRC-004 | Security | Blocking | 複審已查條款（SRC-004）：允許「個人使用目的」瀏覽及下載，禁止散布／公開發表，無爬蟲明文條款但有「不得進行不利於本網站的行為」。建議：僅 PO 個人使用、不對外分享、低頻抓取；待 PO 確認並自行核對原頁 | Stander | 待回覆 |
| Q-009 | 如何辨識並略過置頂公告？ | SRC-002 | Scope | Non-blocking | 建議：標題以「【公告】」開頭者略過；其他一律視為內容 | Stander | 待回覆 |
| Q-010 | 文章留言（留言數顯示）要抓嗎？ | SRC-002 | Scope | Deferred | MVP 不抓留言 | Claude 提案 | 2026-11-12 |
| Q-011 | 條款規定同一帳號最多兩台裝置或瀏覽器上線，超過可停用帳號；排程的瀏覽器算一台。PO 平常用幾台看定錨？ | SRC-004 | Integration／Security | Blocking | 建議：排程每次跑完即登出（不常駐佔用名額）、並避開 PO 常用時段；若 PO 已固定用兩台（如手機＋電腦），需先決定讓出哪一台或接受風險 | Stander | 待回覆 |
| Q-012 | 抓到新文章時要不要 Telegram 通知（標題＋連結）？ | SRC-001 | Scope | Non-blocking | 建議：要，僅標題與連結，不含內文 | Stander | 待回覆 |
| Q-013 | 清單是否分頁、文章網址形態、`lv=` 參數意義、登入狀態有效期、紅色數字是總數或未讀數 | SRC-002 | Integration | Non-blocking | 無法由截圖判斷；列為技術規劃第一步的 Mac 探查項目，不需 PO 決策 | Claude | 2026-11-13 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
