# PO 原始需求（2026-11-19，原文整理，勿改寫）

【任務】為 AlphaVibe 規劃「外部內容知識庫」功能（走 /prespec，現階段只做需求基線，不寫程式碼、不建 specs/）。

【需求（PO 原話整理）】
- 目的：YouTube 影片、Podcast、文章有參考價值，要納入 AlphaVibe，討論投資時當知識查詢與引用。
- 輸入方式：PO 在 Claude 對話中貼連結（＋逐字稿）。PO 目前用 Google AI Studio 把影片轉逐字稿，所以第一階段做法：PO 提供連結＋逐字稿，系統負責儲存與檢索；自動抓字幕、Whisper 轉錄先不做，列為後續選項。
- 必須全文可檢索（不是只存摘要）。
- 摘要／觀點歸納只能在 PO 確認後才入庫，不可自動寫入。
- 每筆要標註來源類型、連結、標題、頻道/作者、日期，並標明「作者個人觀點，未經查證」。
- 範圍：YouTube、Podcast、文章。

【已做的決定】
- 資料庫：獨立 db，不混進 alphavibe.db 的評論庫（Layer 3 是短評，中文 FTS 查詢需 ≥3 字）。比照 articles.db／substack.db／us_stocks.db 的慣例。
- 查詢介面比照定錨文章的 search_articles／get_article 模式（poc/kb-mcp/article_tools.py、server.py、us_stock_mcp_server.py；新增 MCP 工具要同步 server_readonly.py 白名單與工具數守門測試）。

【請先查證再提案】
1. 與 specs/011-substack-fetch-store、010 articles.db 的關係：是否合併為同一個內容庫，或維持分開但共用查詢介面？給選項與代價與推薦，讓 PO 決定。
2. 寫入工具的設計：PO 在對話貼逐字稿時，Claude 如何一次寫入長文（避免我方輸出整份逐字稿耗 token；例如寫入本機檔案後由腳本匯入）。
3. 去重：同一連結再貼一次的行為。

【待 PO 另行確認的事（不要自行處理）】
- 之前在評論庫（Layer 3）存了 3 筆「股市隱者 EP466」摘要（source_tag=podcast），PO 傾向刪除；刪除須先問 PO。
- 逐字稿原檔預定在 docs/research/2026-11-19-stockhermit-ep466-transcript.md，由 PO 自行存放，可作為第一個測試案例。
