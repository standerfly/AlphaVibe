# Clarification Log: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-12

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 要抓哪些分類？ | SRC-001 | Scope | Answered | 台股、美股、週報（不含產業、總經） | Stander | 2026-11-12 |
| Q-002 | 歷史資料要回補嗎？如何避免被擋？ | SRC-001 | Scope／Import | Answered | 全部回補；排程不定時、分批 | Stander | 2026-11-12 |
| Q-003 | 抓回後做什麼分析？ | SRC-001 | Scope | Answered | 先存全文；之後由 PO 與 LLM 討論，MVP 不做自動抽取 | Stander | 2026-11-12 |
| Q-004 | 爬蟲開啟文章會讓網站把文章標成「已讀」，是否接受？ | SRC-002 | Data／Integration | Blocking | 建議：接受，但實測確認；若可避免（只讀清單／API）則優先避免 | Stander | 待回覆 |
| Q-005 | 抓回的文章放哪、怎麼看？ | SRC-001 | Data／Scope | Blocking | 建議：獨立資料庫（比照美股／相簿先例），台股/美股分類以標籤區分並分別可被台/美連接器查詢；STND 頁面列為 Deferred | Stander | 待回覆 |
| Q-006 | 週報與台股分類重疊時怎麼處理？ | SRC-002 | Data | Non-blocking | 建議：以文章 ID 為唯一，一篇文章可帶多個分類標籤 | Stander | 待回覆 |
| Q-007 | 文章內的圖片（表格圖）要存嗎？要 OCR 嗎？ | SRC-003 | Data／Scope | Non-blocking | 建議：存圖檔於本機與文章關聯；OCR／表格數值化列為 Deferred | Stander | 待回覆 |
| Q-008 | 版權／服務條款：僅個人使用、不對外分享？ | SRC-001 | Security | Blocking | 建議：僅 PO 個人使用；資料不得經公開網址無驗證存取；抓取低頻 | Stander | 待回覆 |
| Q-009 | 如何辨識並略過置頂公告？ | SRC-002 | Scope | Non-blocking | 建議：標題以「【公告】」開頭者略過；其他一律視為內容 | Stander | 待回覆 |
| Q-010 | 文章留言（留言數顯示）要抓嗎？ | SRC-002 | Scope | Deferred | MVP 不抓留言 | Claude 提案 | 2026-11-12 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
