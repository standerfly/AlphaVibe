# Repo 查證報告（2026-11-20，subagent 回報整理；供需求基線引用，非 PO 原話）

## 與既有庫的關係
- comments（alphavibe.db）：FTS5 trigram，查詢至少 3 字（poc/kb-mcp/kb_store.py:37-42、:633-636）。
- articles.db（010）：article 表 PK＝站方 article_id；搜尋用 LIKE 不用 FTS5，因 trigram 對 2 字中文詞搜不到
  （「環宇」「財測」→0）（poc/kb-mcp/article_store.py:56-71、:504-534；specs/010-investanchors-article-import/research.md:246-254）。
- substack.db（011）：guid UNIQUE＋link_norm UNIQUE＋完整度 P/F/N（specs/011-substack-fetch-store/data-model.md:30-51）；
  011 目前無查詢入口，plan.md:113 要求第 1 包測試斷言 app／server*.py 不含 substack 字樣。
- 三庫皆無講者、時間軸、媒體長度、摘要確認狀態欄位（屬新需求）。
- 工具數現況：台股 server.TOOLS=50（server.py:65）、唯讀 READONLY_TOOLS=31（server_readonly.py:9,:40）、美股 10；
  守門測試 test_pnl.py:244-252、test_traceability.py:252-262、test_article_connectors_parity.py:56-61、test_us_stock_mcp_server.py:21,:32。
  Mac 上 ~/.claude stock-researcher 白名單不在 repo。claude.ai 連接器路由 app/routers/mcp.py。

## 長文寫入
- save_comment 直接收 body 字串、無長度檢查（server.py:74-87、kb_store.py:589-598）；HTTP 路徑直接讀整個 request body
  無上限（mcp_http_gateway.py:263-264、app/routers/mcp.py:86,:159）。ngrok／claude.ai 對單次工具呼叫的大小上限：未查到，須實測。
- 先例：statement_import.py --from-file（:10-11、:378-379）。
- claude.ai 連接器只能呼叫 MCP 工具、不能寫 PO 本機檔案（推論）；本 repo MCP 工具無寫檔工具。
- 既有決定 OQ-1（roadmap.md:321-322）：PO 自行預處理 YouTube 成文字後貼入；Q-026（roadmap.md:318-320）：對話歷史只存已確認內容。

## 去重
- 010 以站方 article_id 為 PK 去重；011 以 guid／link_norm UNIQUE；comments 無去重（重複 save 會重複插入）。
- 011 的 link_norm「去 query」規則套到 YouTube 會出錯（影片 ID 在 watch?v= 的 query 裡）。
- YouTube 需收斂 youtu.be／watch?v=／shorts／live／m.／music. 為同一影片 ID，剝除 si=、feature=、utm_*，t=／start= 不影響身分，list= 待決。
  Podcast 以 RSS guid 最穩，平台頁連結難互相對應（推論，repo 無對應程式碼）。
- 未查到：us_stock_store.py 的去重細節。

## 其他
- 無相近既有 slug（最近的是 kb-tooling-extensions，屬工具擴充）。各 slug clarification-log 各自編號。
- 011 的 15 項 PO 決定尚未全部結清、tasks 未產生；本功能不可假設能重用 011 元件。

## 更正（2026-11-20，獨立驗收後）
- 011 `plan.md` 的「第 1 包無對外入口」限制實際在第 115 行（`011-substack-fetch-store` 分支），上文寫的 113 有誤。
- `article_store.py`、`article_tools.py` 等 010 程式不在目前 `develop` 分支；位於 `origin/function/alphavibe` 與 `AlphaVibe-prod`。上文對 010 的行號引用以該分支為準。
  已核對：`article_store.py:504-506` 為 `search_articles`，註解「LIKE，非 FTS5」。
