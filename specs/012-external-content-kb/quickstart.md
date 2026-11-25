# Quickstart：外部內容知識庫（012）

**Feature**: 012-external-content-kb | **Date**: 2026-11-25 | **狀態**: 計畫階段，尚無程式碼

## 接手前必讀

1. [spec.md](spec.md)（要什麼）→ [plan.md](plan.md)（怎麼做）→ [research.md](research.md)（為什麼）→ [data-model.md](data-model.md) → [contracts/](contracts/)。
2. 需求基線與決策紀錄：`docs/spec-intake/external-content-kb/`（`clarification-log.md` 含 Q-001～Q-022）。
3. 既有做法的樣板（`function/alphavibe` 才有）：`poc/kb-mcp/article_store.py`、`article_tools.py`、`server_readonly.py`、`us_stock_mcp_server.py`。

## 開工第一件事（會改寫本分支歷史，須先取得 PO 同意）

本分支落後 `origin/function/alphavibe` 322 個 commit。先把本分支的 5 個文件 commit rebase 到 `origin/function/alphavibe` 之上，再開始寫程式。
動手前跑 `git status`／`git log --oneline origin/function/alphavibe..HEAD`，確認只有文件 commit；`poc/data-test-articles/`、`poc/kb-mcp/scraper/` 是不屬於本功能的未追蹤項目，不要碰。

## 驗證（實作完成後）

```bash
# 單元測試（用獨立 data dir，絕不指向 poc/data/）
ALPHAVIBE_DATA_DIR=$(mktemp -d) python3 -m unittest discover -s poc/kb-mcp/tests -p "test_external_content*.py"
# 守門測試（工具數 57／33、美股名稱集合）
python3 -m unittest poc/kb-mcp/tests/test_pnl.py poc/kb-mcp/tests/test_traceability.py poc/kb-mcp/tests/test_us_stock_mcp_server.py poc/kb-mcp/tests/test_article_connectors_parity.py
# 全套（比對基準：改動前先在乾淨 checkout 跑一次，數字要能對上）
python3 -m unittest discover -s poc/kb-mcp/tests
```

端到端驗收（需 PO 提供 EP466 逐字稿檔案）：
1. 用本機 Claude Code 對 `create_inbox_file` 貼 EP466 連結 → 取得檔案路徑 → 把逐字稿貼進內文 → `import_inbox`。
2. 以 5 個取自內文的 2 字中文詞呼叫 `search_external_content`，確認全部命中且輸出含「作者個人觀點，未經查證」。
3. 以三種連結寫法重複 `create_inbox_file`／`import_text`，確認庫內只有一筆。
4. 用唯讀端（`server_readonly.py`）跑 `tools/list`，確認只看到 2 個查詢工具。
5. 在 claude.ai 的 AlphaVibe 專案（台美兩連接器皆啟用）實測：討論相關主題時 agent 是否主動搜尋（遵循度驗證，spec Scenario 11）。

## 實測任務（不阻擋開工）

- 用**真實磁碟庫**（非記憶體庫）量測 2 字中文詞搜尋的冷讀時間，確認遠低於 500 ms。
- claude.ai／ngrok 單次工具呼叫的字數上限（影響 `import_text` 上限與提示文字）。
- 多支 YouTube 影片驗證 `uploadDate` 擷取是否穩定；失效時降級為問 PO。

## 部署（合併 PR 後）

沿用 `AlphaVibe-prod` 流程：`cd /Users/stander/My_project/AlphaVibe-prod && git fetch origin function/alphavibe && bash <(git show origin/function/alphavibe:ops/deploy.sh)`。
部署後須：把 `search_external_content`、`get_external_content` 補進 Mac 上 `~/.claude` 的 stock-researcher 白名單（不在 repo）；重啟服務（`ops/deploy.sh` 內建 `kickstart -k`）、確認 claude.ai 兩個連接器的 `tools/list` 各多 2 個（台股端多 7 個）、PO 把更新後的專案指示貼進 claude.ai 專案（`docs/runbooks/external-content-project-instructions.md`）。
**不要**在正式環境以外跑會寫 `poc/data/` 的測試。

## 已知陷阱

- **陷阱 A（高）符號連結**：正式環境 `AlphaVibe-prod/poc/data` 是指向 `AlphaVibe/poc/data` 的符號連結，`server.py` 只做 `abspath` 不解開。資料匣檢查必須對 inbox 根目錄與檔案**兩邊**都 `os.path.realpath`，測試要有「資料目錄本身是符號連結」的案例（一般暫存目錄抓不到這問題）。
- **陷阱 B（中）本機 stdio 路徑**：本機 Claude Code 的 MCP 執行開發資料夾當下 checkout 的分支程式，卻連實際資料目錄（含正式資料），且該路徑沒有 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE` 檢查。開發與測試一律設 `ALPHAVIBE_DATA_DIR=<獨立測試庫>`；寫入工具另有「正式資料目錄且未設旗標則拒絕」的保護。
- **還原軟刪除**（第一版無還原工具）：手動以 SQL 把該列 `deleted_at` 設回 NULL、`source_key` 去掉 `#deleted-<id>` 後綴；操作前先備份 `external_content.db`。
  **衝突處理**：若刪除後同一來源已被重新匯入（新列佔用了原 `source_key`），直接還原會撞 `UNIQUE(source_key)`（US5 驗收實測）。還原前須先決定保留哪一筆：要還原舊列，就先對新列做軟刪除（同樣設 `deleted_at` 並把 `source_key` 改為 `<原 key>#deleted-<id>`），再還原舊列；若新列已足夠，就不必還原舊列。
- 新資料庫檔 `external_content.db` 是否被每日備份涵蓋**未查到**，部署時須確認 `ops/` 備份腳本（dbbackup）是否涵蓋，必要時補上。
- 資料匣檔案與資料庫都在 `poc/data/`（`.gitignore`），逐字稿是第三方內容，不得 commit。
- macOS `/var`→`/private/var`：任何路徑比對一律 `os.path.realpath`。
- 本機 Python 為 3.9.6：不要用 3.10+ 語法。
- 工具名稱不得含 `article`、`verif`、`reviewed`。
- 寫入工具只掛 `server.py`，不掛 `server_readonly.py` 與美股端。
