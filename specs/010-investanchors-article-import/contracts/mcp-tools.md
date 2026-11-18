# Contract: MCP 唯讀工具（台股與美股連接器各一份、同一個 articles.db）

註冊位置：`poc/kb-mcp/server.py`（TOOLS＋call_tool）、`poc/kb-mcp/us_stock_mcp_server.py`（TOOLS＋call_tool）、
`poc/kb-mcp/server_readonly.py`（READONLY_TOOLS＋READONLY_TOOL_SCHEMAS）。兩個 Server 的行為與輸出必須逐字相同
（US3 驗收情境 3）。工具名與台股既有工具不得衝突。

## `search_articles`
- 輸入：`query`（string，必填；空白分隔多關鍵字，**全部需出現**）、`limit`（int，預設 10，最大 30）。
- 搜尋範圍：標題＋全文＋**已驗證**的圖片轉寫文字（驗證等級 `cross_checked`〔數字與文字兩個檢核家族都通過〕或 `reviewed`〔PO 核對〕；`unverified`／`flagged` 的轉寫不納入，Q-028）；僅 `status='fetched'` 的文章。
- 輸出（文字）：每筆 `標題｜發布日期｜原文網址（必帶）｜片段（命中處前後約 60 字，標明命中來源：內文／表格轉寫）｜article_id`；
  依發布日期新到舊。無命中 → 明確回「查無符合的文章」，不回無關內容。
- 唯讀；不觸發任何網站存取。

## `get_article`
- 輸入：`article_id`（int，必填）。
- 輸出：標題、發布日期、原文網址（必帶）、全文；之後列出圖片：`#seq｜是否表格｜轉寫狀態｜原圖 src_url｜本機檔路徑`。
  **原圖回查以 `src_url`（PO 登入網站後可開）為主**——PO 多半從 claude.ai 連接器查，本機路徑在那裡打不開；
  本機路徑保留供 Claude Code 使用。表格轉寫文字附在該圖下，**由輸出層加上**「【機器轉寫，可能有誤，請以原圖為準】」
  標示（資料庫欄位不存此標示，見 data-model.md）；每張已轉寫圖另標驗證等級：`unverified`／`flagged` 附「【未驗證／有疑慮的圖片轉寫：數字可能有誤，不得用於投資判斷，請對照原圖】」（flagged 附疑慮摘要；只通過單一檢核家族者註明「已通過數字檢核，尚缺文字抽查」或反之），轉寫文字每行加固定前綴「│ 」，避免文字內偽造的警告樣式行與真正標頭混淆；`untranscribed` 明寫「未轉寫」。找不到或非 `fetched` →
  明確錯誤訊息（不回殘缺內容）。
- 不存在於庫＝不去網站抓（唯讀、不登入）。

## 守門測試同步
- `test_pnl.py::test_tool_counts`：`len(server.TOOLS)` 48→50、`len(READONLY_TOOLS)` 29→31；
- `test_traceability.py::test_tools_list_has_forty_eight`（:252-261）：48→50，函式名與 docstring 同步，預期工具名清單加 `search_articles`／`get_article`；
- `test_claude_ai_connector.py`：美股 names==TOOLS 的預期清單加兩項；
- 新增：兩個 Server 對同一個測試庫、同一關鍵字回傳完全相同結果的測試；
- Mac 上 `~/.claude` stock-researcher 白名單（不在 repo）由 PO 手動加入，列入上線 checklist。
