# alphavibe-kb — 三層知識庫 MCP server（Phase 1 PoC）

對應 spec：`docs/spec-intake/alphavibe/product-spec.md`（FR-015~021、Q-021
即時確認制）與 `implementation-options.md` Phase 1。純 Python 標準庫
（本機 Python 3.9，官方 MCP SDK 需 3.10+ 故不引依賴）。

## 用法（Claude Code）

repo 根目錄的 `.mcp.json` 已註冊本 server。在 AlphaVibe 目錄**開新的
Claude Code session**，首次會詢問是否啟用 `alphavibe-kb`——允許後即可：

- 「幫我把剛剛討論的台積電看法存進知識庫」→ AI 呼叫 `save_stance`，
  **工具核准提示＝你的確認**（Q-021）；與既有立場衝突時會先被擋下、
  列出新舊立場請你決定（FR-013/018）
- 「查一下 2330 的基本面」→ `get_fundamentals`（FinMind 即時數據）
- 「我對哪些股票有立場？」→ `list_stances`
- 「搜尋知識庫裡關於法說會的評論」→ `search_comments`

## 工具清單

| 工具 | 層 | 說明 |
|------|-----|------|
| save_stance / get_stance / list_stances | L2 | 個股立場（含衝突擋下機制，保留歷史） |
| save_comment / search_comments | L3 | 盤勢評論，FTS5 trigram 全文檢索（**查詢至少 3 個字**） |
| save_philosophy / get_philosophy | L1 | 投資哲學模組 md 檔（append/replace） |
| get_fundamentals | 數據 | FinMind：近期 PER/PBR/殖利率＋近 6 月營收 |

## 資料位置

`poc/data/`：`alphavibe.db`（SQLite，已 gitignore）＋ `philosophy/*.md`。
可用環境變數 `ALPHAVIBE_DATA_DIR` 覆寫。

## FinMind token（可選）

匿名呼叫已實測可用（2026-07-08），額度較低。頻繁使用時到
https://finmindtrade.com 免費註冊，token 放環境變數 `FINMIND_TOKEN`
或 `poc/data/finmind_token.txt`（已 gitignore）。

## 測試

```bash
python3 -m unittest discover -s poc/kb-mcp/tests -v
```

涵蓋：儲存層（立場衝突流程、中文全文檢索、哲學檔案）、FinMind 解析
（mock）、MCP 協定端到端（真實子行程握手＋工具呼叫）。
