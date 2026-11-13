# Clarification Log: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-13

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 要抓哪些分類？ | SRC-001 | Scope | Answered | 台股、美股、週報（不含產業、總經） | Stander | 2026-11-12 |
| Q-002 | 歷史資料要回補嗎？如何避免被擋？ | SRC-001 | Scope／Import | Answered | 全部回補；排程不定時、分批 | Stander | 2026-11-12 |
| Q-003 | 抓回後做什麼分析？ | SRC-001 | Scope | Answered | 先存全文；之後由 PO 與 LLM 討論，MVP 不做自動抽取 | Stander | 2026-11-12 |
| Q-004 | 爬蟲開啟文章會讓網站把文章標成「已讀」，是否接受？ | SRC-002 | Data／Integration | Answered | 接受：排程開啟文章導致網站標成已讀可以接受 | Stander | 2026-11-13 |
| Q-005 | 抓回的文章放哪、PO 怎麼跟 LLM 討論？（2026-11-13 複審補充選項） | SRC-001 | Data／API／Scope | Answered | 選項B：獨立文章庫＋新增「搜尋文章／讀取單篇」查詢工具；台股連接器看台股＋週報、美股連接器看美股；STND 閱讀頁 Deferred | Stander | 2026-11-13 |
| Q-006 | 週報與台股分類重疊時怎麼處理？ | SRC-002 | Data | Non-blocking | 採建議值（PO 未異議）：以文章 ID 為唯一、容許多標籤；Mac 實測確認是否真有重疊 | Stander | 2026-11-13 |
| Q-007 | 文章內的圖片（表格圖）要存嗎？要讓 LLM 讀得到嗎？ | SRC-003 | Data／Scope | Answered | 表格數字是重點→**進 MVP**：圖片存檔，且表格圖的內容須讓 LLM 在討論時讀得到（轉文字或回傳圖片，做法於 plan 定）；轉出的文字須標示為機器轉寫、原圖可回查 | Stander | 2026-11-13 |
| Q-008 | 版權／服務條款：僅個人使用、不對外分享？ | SRC-001、SRC-004 | Security | Answered | 確認：僅 PO 個人使用、不對外分享；**務必低頻抓取，避免阻擋** | Stander | 2026-11-13 |
| Q-009 | 如何辨識並略過置頂公告？ | SRC-002 | Scope | Non-blocking | 採建議值（PO 未異議）：標題以「【公告】」開頭者略過 | Stander | 2026-11-13 |
| Q-010 | 文章留言（留言數顯示）要抓嗎？ | SRC-002 | Scope | Deferred | MVP 不抓留言 | Claude 提案 | 2026-11-12 |
| Q-011 | 條款規定同一帳號最多兩台裝置或瀏覽器上線，超過可停用帳號；排程的瀏覽器算一台。PO 平常用幾台看定錨？ | SRC-004 | Integration／Security | Answered | PO 只在手機或電腦間切換、不會同時上線；採建議：排程每次跑完即登出、不常駐登入狀態、避開 PO 常用時段 | Stander | 2026-11-13 |
| Q-012 | 抓到新文章時要不要 Telegram 通知（標題＋連結）？ | SRC-001 | Scope | Non-blocking | 採建議值（PO 未異議）：新文章 Telegram 通知，僅標題與連結 | Stander | 2026-11-13 |
| Q-013 | 清單是否分頁、文章網址形態、`lv=` 參數意義、登入狀態有效期、紅色數字是總數或未讀數 | SRC-002 | Integration | Non-blocking | 無法由截圖判斷；列為技術規劃第一步的 Mac 探查項目，不需 PO 決策 | Claude | 2026-11-13 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
