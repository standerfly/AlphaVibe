# 010 上線前最後審查材料（T054）

> 撰寫日期 2026-11-16；基準 HEAD=`d2308b5`，分支 `claude/admiring-ptolemy-1jaw79`。
> 讀者：主對話（審查者）與 PO。本文件**只是草案與核對清單，沒有執行任何一條指令**。
> 差異範圍以 git 已提交內容為準；**scraper 的「篇間隔下限防呆」由另一個 agent 修改中、另行提交，不在本文件 diff 內**
> （`poc/kb-mcp/scraper/investanchors_scraper.js` 與相關測試的最終內容以該提交為準）。
> 出處標記：`檔案:行號` 或 `指令`；查不到的一律寫「未驗證」。本文件刻意不含帳密、token、文章標題或內文。

---

## 1. 整個 010 的 diff 範圍

### 1.1 範圍定義與總量

- 010 起點：最早的 010 相關提交是 `ab5de1c`（2026-11-12，`docs(prespec): 新增 investanchors-import …`）；其父提交 `c9b99f4`
  （Merge PR #47，亦即目前 `origin/function/alphavibe` 的頂端）。
  出處：`git log --oneline`；`git rev-parse origin/function/alphavibe` = `c9b99f4`。
- 範圍：`git diff ab5de1c~1 HEAD`。
- `git rev-list --count origin/function/alphavibe..HEAD` = 43（本分支領先 43 個提交）、`HEAD..origin/function/alphavibe` = 0（沒落後，可 fast-forward 或直接 PR）。
- `git diff --shortstat`：**90 個檔案、+13773／−18**；其中新增（A）76、修改（M）14、無刪除、無改名（`git diff --name-status`）。
- 工作樹撰寫時 `git status --short` 為空（乾淨）。

### 1.2 修改了「既有（非 010 專屬）檔案」的位置（14 個，重點審查）

| 檔案 | 改了什麼（行數） | 為何安全／行為不變的證據 | 風險 |
|---|---|---|---|
| `poc/kb-mcp/server.py` | +`import article_tools`；`TOOLS` 結尾加 `+ article_tools.ARTICLE_TOOL_SCHEMAS`；`call_tool()` 開頭加「名稱屬於 `ARTICLE_TOOL_NAMES` 就轉給 `article_tools.call_article_tool(self.data_dir, …)`」（+5／−1） | 既有 48 個工具的程式路徑沒動，只在 `call_tool` 最前面多一個名稱判斷；新工具名（`search_articles`／`get_article`）與既有名稱不重複。守門：`tests/test_pnl.py::test_tool_counts`（50／31）、`tests/test_traceability.py::test_tools_list_has_fifty`（含 48 個既有名稱仍在清單內的 `assertIn` 迴圈） | **中**：這是正式 MCP 連接器載入的檔案；import 失敗會讓整個 reportserver 的 `/mcp` 掛掉。緩解：`article_tools` 在模組載入時只 import `article_store`，不連庫、不建檔（`article_tools.py:10-16`） |
| `poc/kb-mcp/server_readonly.py` | `READONLY_TOOLS` 加兩個名稱；docstring 數字 48→50、29→31（+5／−3） | 只加唯讀白名單；`test_tool_counts` 守 31 | 低：仍是唯讀；Cline 唯讀 wrapper 多兩個讀工具 |
| `poc/kb-mcp/us_stock_mcp_server.py` | 與 server.py 對稱：import、`TOOLS` 結尾串接、`call_tool` 開頭分流（+5／−1） | `tests/test_us_stock_mcp_server.py::test_ten_tools_registered` 精確比對 10 個名稱集合；`test_claude_ai_connector.py` 加兩個 `assertIn`、並保留 `assertNotIn("get_holdings")`（不混入台股工具）。**文章分流在 `call_tool` 內不碰 `us_stocks.db`**（`us_stock_mcp_server.py` 改動處註解） | **中**：美股連接器同樣是正式載入檔；台美共用同一份 `articles.db` 屬刻意設計（spec FR；`CLAUDE.md` 新增段落） |
| `app/article_deps.py`（**新檔，非修改**，列於此因位於 `app/`） | FastAPI dependency 取得 `ArticleStore` | `grep -rn 'article_deps\|get_article_store' app` 排除 tests 後只有自己定義，**沒有任何 router 引用**，等於未接線；不 import `app/deps.py`／`us_stock_deps.py`（檔頭 docstring）。測試：`app/tests/test_article_deps.py` | 低：目前不影響正式服務。注意：它屬 `app/`，deploy.sh 會判定為「變動」但不因此多做任何事（見 §2） |
| `poc/kb-mcp/check_scheduled_jobs.py` | 新增 `INVESTANCHORS_STALE_DAYS=3`、`_aware_age_hours()`、`check_investanchors_import()`（唯讀檢視 `articles.db`），並登記進檢查清單 `("investanchors_import", check_investanchors_import, True)`（+75） | 庫不存在回 `ok`「尚未建立」、無執行紀錄回 `ok`、缺表（`sqlite3.OperationalError`）回 `ok`（改動處 :37、:44、:83），所以**部署後、排程安裝前不會誤報**；用 `open_readonly`，不建庫。測試：`tests/test_check_scheduled_jobs.py` 新增 `InvestanchorsImportCheckTest` | 低～中：每日 healthcheck 會多一項；若庫存在但排程停擺會報 critical（符合預期）。注意 `test_check_scheduled_jobs` 單檔有既有 error，見 §5 |
| `poc/kb-mcp/keychain_secrets.py` | 新增 `INVESTANCHORS_SERVICE="stnd-investanchors"`、`INVESTANCHORS_ACCOUNTS=("email","password","vision-api-key")`、`_ACCOUNTS_BY_SERVICE`；`get_secret(account, runner=None, service=None)` 加選用參數（+19／−… ） | **預設 `service=None` → 用原本 `SERVICE`（`stnd-statement-import`）**，009 對帳單匯入既有呼叫簽名相容；仍只用 `security find-generic-password … -w`，錯誤訊息只含 account 名稱、不含值 | **中**：009 已上線的 `statement_import.py` 共用此模組；請審查者確認 009 的測試仍綠（`git diff` 只動這一檔的鑰匙圈邏輯；本文件**未**單獨重跑，未驗證） |
| `CLAUDE.md`（根目錄） | SPECKIT 區塊加 010 現況段（+9）；「常用查證點」加定錨文章查詢說明（+6）；教訓紀錄加 2026-11-16 一則（+11）。共 +26 | 純文件；不改規則語意 | 低。**注意**：其中「T048 真實回補試跑待 PO；尚未部署」之敘述，在 T048 勾選（`tasks.md:143` 為 `[x]`）後已與現況落差，上線前需更新（見 §6） |
| `.gitignore` | +3：忽略 `poc/data-test-articles/` | 純忽略規則；`git status` 乾淨 | 低 |
| `.specify/feature.json` | `feature_directory` 009→010 | Spec Kit 工具指標，不影響執行時程式 | 低（合併後之後的新 feature 工作要記得再切換） |
| `docs/spec-intake/index.md` | +1 列 investanchors-import | 純文件 | 低 |
| `poc/kb-mcp/tests/test_pnl.py`／`test_traceability.py`／`test_us_stock_mcp_server.py`／`test_claude_ai_connector.py`／`test_check_scheduled_jobs.py` | 工具數 48→50、29→31；美股工具集合 8→10；連接器加 2 個 `assertIn`；新增巡檢測試類 | 這些修改是**因新增工具而必要的守門數字更新**，且方向一致（加不減），既有斷言（含「不混入台股工具」）未被刪弱 | 低；審查者可核對 `git diff` 確認沒有任何 `assertEqual` 被放寬為 `assertGreaterEqual` |

另：`poc/kb-mcp/backup_databases.py` 已於 2026-11-16 依 PO 決定修改：新增 `OPTIONAL_DATABASES = ("articles.db",)`，`articles.db` 納入每日備份（來源不存在時略過、不算失敗）；`DATABASES` 三個既有庫行為不變。測試：`poc/kb-mcp/tests/test_backup_databases.py`。**`articles_images/` 不備份**（見 §6 風險 1、`quickstart.md` 第 11 節）。

### 1.3 新增檔案（76 個，依類別；每檔一行用途）

**ops（1）**
- `ops/launchd/com.alphavibe.investanchorsimport.plist` — 每晚 23:00 排程；無 RunAtLoad／KeepAlive；帶 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`；**尚未安裝**（檔內註解）。

**app（2）**
- `app/article_deps.py` — 文章庫 FastAPI dependency（未接線）。
- `app/tests/test_article_deps.py` — 其單元測試。

**生產程式 poc/kb-mcp（14）**
- `article_store.py` — `articles.db` 資料層（含 `open_readonly`、`setting`、回補狀態、轉寫計數）。
- `article_tools.py` — `search_articles`／`get_article` 的格式化、唯讀開庫、schema（台美共用）。
- `article_data_guard.py` — 資料目錄防呆（必須明確指定；指向正式庫要旗標；realpath 判斷）。
- `article_id_time.py` — 文章 ID→建立時間推算與 `id_time_ok` 防呆。
- `article_images.py` — 圖片下載（主機白名單、落於 `articles_images/`）。
- `article_image_tiles.py` — 長圖切片（Playwright canvas）。
- `article_transcribe.py` — 視覺模型轉寫模組。
- `article_reconcile.py` — 與網站清單逐篇核對的唯讀工具（T062 用）。
- `article_probe.py` — Phase 0 網站探查工具。
- `investanchors_import.py` — 匯入主流程與 CLI（含回補、轉寫開關、抽查、補轉）。
- `investanchors_limits.py` — 低頻守衛（每日登入上限、冷卻）。
- `investanchors_mailbox.py` — Gmail 通知信只當觸發。
- `investanchors_redact.py` — 輸出脫敏（token 等）。
- （修改檔見 §1.2）

**scraper（5，`poc/kb-mcp/scraper/`）**
- `investanchors_scraper.js` — 登入、清單、文章擷取、登出（**間隔下限防呆另行提交**）。
- `investanchors_session.js` — 共用 Playwright session／登出保證。
- `id_filter.js` — 文章 ID 門檻（整數比較）。
- `image_tiler.js` — 圖片切片腳本。
- `site_util.js` — 共用小工具。
- 無 `package.json`／`package-lock.json` 變動（`git diff --name-status` 無此路徑）→ `ops/deploy.sh:56` 的 `npm ci` 不會被觸發。

**測試（約 28，`poc/kb-mcp/tests/`）**
- 共用夾具：`_article_fixture.py`、`fake_investanchors_site.py`、`fixtures/id_time_corpus.json`。
- 單元／整合：`test_article_store.py`、`test_article_tools.py`、`test_article_search.py`、`test_article_connectors_parity.py`（台美輸出逐字相同）、`test_article_id_time.py`、`test_article_id_filter_corpus.py`、`test_article_images.py`、`test_article_image_tiles.py`、`test_article_transcribe.py`、`test_article_transcription_search.py`、`test_article_reconcile.py`、`test_article_probe.py`、`test_fake_investanchors_site.py`。
- 匯入流程：`test_investanchors_import.py`、`…_import_e2e.py`、`…_backfill.py`、`…_backfill_e2e.py`、`…_limits.py`、`…_mailbox.py`、`…_redact.py`、`…_no_leak.py`、`…_plist.py`、`…_scraper_import.py`、`…_transcription.py`。

**文件（約 26）**
- `specs/010-investanchors-article-import/`：`spec.md`、`plan.md`、`research.md`、`data-model.md`、`quickstart.md`、`tasks.md`、`checklists/requirements.md`、`contracts/cli.md`、`contracts/mcp-tools.md`。
- `docs/spec-intake/investanchors-import/`：product-spec、clarification-log、extracted-requirements、scope-decision、handoff-checklist、intake-index、supporting-artifacts 三份、spec-kit-inputs、`raw/` 下 6 份素材（含 2 張 png）。
- `docs/spec-intake/.../investanchors-article-import/speckit-input.md`。

> 提醒審查者：`docs/spec-intake/investanchors-import/raw/` 下兩張 png 與 `src-004-site-terms-excerpts.md` 是 PO 原始素材，進入 git 前請確認不含帳號畫面資訊（本文件**未**打開查看，未驗證）。

### 1.4 `git diff --stat` 摘要（重現指令）

```
git diff --stat ab5de1c~1 HEAD | tail -1
#  90 files changed, 13773 insertions(+), 18 deletions(-)
git diff --name-status ab5de1c~1 HEAD | grep -v '^A'   # 列出 14 個修改檔
```

---

## 2. 部署步驟草案（全部未執行）

### 2.1 合併前置（選項，由 PO／主對話決定）

現況：目前分支 `claude/admiring-ptolemy-1jaw79` 領先 `function/alphavibe` 43 個提交、未落後（§1.1），所以合併不會有衝突。可選方式：
- **選項 A**：對 `function/alphavibe` 開 PR，審查後 merge（CLAUDE.md 既有慣例，009 即 PR #44／#46／#47）。
- **選項 B**：本機 fast-forward 合併後推送（不經 PR；較快，但少一道審查紀錄）。
- 無論哪個：`ops/deploy.sh:9-12` 要求部署指令從 `origin/function/alphavibe` 取腳本，所以**一定要先讓 `origin/function/alphavibe` 含 010 提交**。
- 「間隔下限防呆」那個提交也要在合併之前進分支，否則正式版缺少該防呆（目前未提交，未驗證其內容）。
- 全套回歸與 smoke test 對照基準（§5）應在合併前由審查者再跑一次（本文件未跑）。

### 2.2 備份（部署前）

- `ops/deploy.sh` **不含任何資料備份**（逐行讀過，行 19–73 無 backup／cp／sqlite3；它只備份「回滾用的 commit 位置」並印出回滾指令，行 69／72）。
- 沿用 `ops/` 外的既有慣例：`poc/kb-mcp/backup_databases.py`（sqlite 線上備份 API＋`integrity_check`，`backup_databases.py:1-22`），預設目的地 `~/AlphaVibe-backups`（:34）。草案：
  ```bash
  cd /Users/stander/My_project/AlphaVibe
  python3 poc/kb-mcp/backup_databases.py --dry-run                      # 先看會備份什麼
  python3 poc/kb-mcp/backup_databases.py --dest ~/AlphaVibe-backups/pre-010-$(date +%Y%m%d-%H%M%S)
  ```
- 說明：010 **不會寫** `alphavibe.db`／`us_stocks.db`／`flights.db`（文章分流只以 `mode=ro` 開 `articles.db`，`article_tools.py:5`；匯入只寫 `articles.db` 與 `articles_images/`、`articles_probe/`）。這份備份是「保險」，不是 010 必需；正式的回滾對象是程式版本（§3.3）。
- 同時備份現行 plist 目錄（慣例見 CLAUDE.md：`~/Library/LaunchAgents/backup-20261029/`）：
  ```bash
  mkdir -p ~/Library/LaunchAgents/backup-pre-010
  cp ~/Library/LaunchAgents/com.alphavibe.*.plist ~/Library/LaunchAgents/backup-pre-010/
  ```
- `articles.db` 此時**尚不存在**，沒有東西要備份；備份腳本遇不存在的 `articles.db` 會記「略過（尚未建立）」且 exit 0（`backup_databases.py` 的 `OPTIONAL_DATABASES` 分支）。**已決定（PO，2026-11-16）：`articles.db` 納入每日備份、`articles_images/` 不備份。**上線後 `articles.db` 建立的隔天備份起即涵蓋。

### 2.3 `deploy.sh` 會做什麼（逐步，行號為 `ops/deploy.sh`）

1. 行 19：`set -euo pipefail`，用 bash 執行（行 18 註明 zsh 規則不同）。
2. 行 21–24：`PROD=/Users/stander/My_project/AlphaVibe-prod`，`cd` 進去。
3. 行 28–32：worktree 有未提交修改（追蹤檔）就中止。
4. 行 34–36：`git fetch origin function/alphavibe`；`OLD=HEAD`、`NEW=origin/function/alphavibe`（或指定 commit）。
5. 行 38–41：新舊相同就印訊息結束。
6. 行 43–45：印出新舊版本，`git checkout --detach "$NEW"`。
7. 行 47–59：只在對應檔案有變動時才做：`app/requirements.txt`→`pip install`、`web/`→`npm ci && npm run build`、`poc/kb-mcp/scraper/package*`→`npm ci`。**010 沒有動這三類檔案**（§1.3），所以這三步預期全部略過。
8. 行 63：`launchctl kickstart -k gui/$(id -u)/com.alphavibe.reportserver` **自動重啟 reportserver**；行 64 `sleep 5`。
9. 行 66–74：以 `POST /mcp/wrong` 期望 HTTP 404 作健康檢查；404 印「完成」與回滾指令（行 69），否則印警告、exit 1（行 71–73）。

**重啟需求**：需要重啟 `reportserver`（`server.py`／`us_stock_mcp_server.py` 改動，由 `app/routers/mcp.py` 載入——`mcp.py:113` 用 `mcp_http_gateway.kb_server`、`:136` 用 `us_stock_mcp_server`）。**deploy.sh 已自動 kickstart（行 63），不需手動重啟**。其他排程每次執行時才讀程式（`deploy.sh:14-16`），不需重啟；`com.alphavibe.moduled` 等若是常駐請審查者確認（未驗證）。

### 2.4 部署後驗證（草案，唯讀）

```bash
# 1. 健康檢查（deploy.sh 已做一次；這裡獨立再確認）
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/mcp/wrong       # 預期 404
# 2. 服務日誌無 import 錯誤
tail -n 30 ~/Library/Logs/alphavibe-report-server.err.log
# 3. 正式環境直接載入兩個 server 模組並印工具數（不連網、不建庫；以唯讀工作樹執行）
cd /Users/stander/My_project/AlphaVibe-prod/poc/kb-mcp && python3 -c "import server, us_stock_mcp_server, server_readonly; print(len(server.TOOLS), len(server_readonly.READONLY_TOOLS), len(us_stock_mcp_server.TOOLS))"
#    預期 50 31 10（出處：test_pnl.py::test_tool_counts、test_us_stock_mcp_server.py::test_ten_tools_registered）
```
- 透過 claude.ai 連接器的 `tools/list`：需要連接器密鑰路徑（`/mcp/<密鑰>`），**密鑰不得寫進文件或貼進對話**；請 PO 在 claude.ai 連接器介面重新整理，確認台股看到 50 個、美股 10 個（人工，未驗證）。
- **articles.db 預期狀態**：此時不存在（`ls /Users/stander/My_project/AlphaVibe/poc/data/articles.db` 應回「No such file」）。對 `search_articles`／`get_article` 呼叫應回清楚錯誤「文章庫尚未建立（找不到 articles.db），尚無已匯入的文章」且**不建庫**（`article_store.py:322-328` `open_readonly` 對不存在檔案 `raise FileNotFoundError`、不建目錄不建表）。可用 claude.ai 實際呼叫一次確認；`ls` 再確認仍不存在。
- healthcheck：`python3 poc/kb-mcp/check_scheduled_jobs.py`（用法以該檔為準，未驗證參數）預期 `investanchors_import` 項為 ok「尚未建立（找不到 articles.db）」（`check_scheduled_jobs.py` 改動處）。
- **轉寫開關維持預設關閉**：不要執行 `--enable-transcription`；無 `setting.transcribe_enabled` 列＝關（`quickstart.md:97-98`；`check_scheduled_jobs.py` 以 `get_setting("transcribe_enabled","0")` 判定）。

---

## 3. plist 安裝步驟與回滾（全部未執行）

### 3.1 安裝（T055，PO 在場同意後）

前置核對（唯讀）：
- plist 指向 `AlphaVibe-prod/poc/kb-mcp/investanchors_import.py`、`--data-dir /Users/stander/My_project/AlphaVibe-prod/poc/data`（symlink；以 realpath 判斷，因此需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，plist 已內建）（plist 註解）。
- 鑰匙圈 `stnd-investanchors` 的 `email`／`password` 必須已存在（`keychain_secrets.py` 新增的 service／account 名單）；**用存在性指令驗證，不得印值**：
  ```bash
  security find-generic-password -s stnd-investanchors -a email >/dev/null 2>&1 && echo "email 存在" || echo "email 不存在"
  security find-generic-password -s stnd-investanchors -a password >/dev/null 2>&1 && echo "password 存在" || echo "password 不存在"
  ```
  （不加 `-w`／`-g`、不用 `dump-keychain`，依 CLAUDE.md 2026-11-12 教訓。T023／T048 已用同名項目執行過，推定已存在，**本文件未驗證**。）
- 確認電腦瀏覽器已登出定錨、只留手機一台（兩台裝置上限，`tasks.md:143`、T023 慣例）。

安裝草案（bash／zsh 皆可，不使用迴圈）：
```bash
PLIST=com.alphavibe.investanchorsimport.plist
cp /Users/stander/My_project/AlphaVibe-prod/ops/launchd/$PLIST ~/Library/LaunchAgents/$PLIST
plutil -lint ~/Library/LaunchAgents/$PLIST
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$PLIST
echo "bootstrap 結束碼：$?"          # 非 0 → 立刻停下，不要重複 bootstrap；先 launchctl print gui/$(id -u)/com.alphavibe.investanchorsimport 看狀態
launchctl print gui/$(id -u)/com.alphavibe.investanchorsimport | head -20   # 確認已載入、state 為 not running（沒有 RunAtLoad）
```
- 新 job 第一次 `bootstrap` 不涉及舊行程，沒有 2026-10-29 的「Bootstrap failed: 5」問題（該問題發生在對常駐服務 bootout 後立刻 bootstrap）；仍須檢查結束碼。
- plist 刻意無 `RunAtLoad`／`KeepAlive`（plist 註解），所以 bootstrap 當下**不會**登入網站。

### 3.2 首次用 launchd 實跑驗證一次

- 觸發：`launchctl kickstart gui/$(id -u)/com.alphavibe.investanchorsimport`（不加 `-k`，避免殺掉執行中行程）。
- **通用規則 8（`tasks.md:25`）**：正式庫的「每日登入 ≤1 次」記在正式庫內。**若在 23:00 前手動 kickstart 實跑，當晚 23:00 排程會被低頻守衛拒絕（同日第二次登入）**——這正是預期的保護，而非錯誤；但要在驗證後告知 PO「今晚排程不會再登入」。反過來：若選擇讓 23:00 的排程當作首次實跑，則不要再手動 kickstart。
- 需要的人為條件：PO 在場同意；電腦瀏覽器已登出；通知信（Gmail IMAP 唯讀）觸發或回補未完成才會登入（plist 註解）。**正式庫首次執行時回補啟動，會用掉當日登入額度、讀清單、抓 ≤5 篇**（`--max-articles` 預設值未在 plist 指定；每次 ≤5 篇出自 `tasks.md:22`）。
- 預期（唯讀檢視，出處 quickstart §10 `quickstart.md:84-99`）：
  ```bash
  tail -n 40 ~/Library/Logs/alphavibe-investanchors.log ~/Library/Logs/alphavibe-investanchors.err.log
  sqlite3 -readonly /Users/stander/My_project/AlphaVibe/poc/data/articles.db "select id, started_at, trigger, logged_in, login_ok, list_pages, articles_fetched, result, logged_out from import_runs order by id desc limit 3;"
  ```
  預期：`logged_in=1`、`login_ok=1`、`logged_out=1`、`result` 非錯誤；`articles.db` 新建；`articles_images/` 有圖；PO 手機仍在線；`check_scheduled_jobs.py` 的 `investanchors_import` 項為 ok（有摘要，轉寫開關「關」）。log 內不得有 token／全文（`test_investanchors_no_leak.py` 守，真實輸出請 PO／主對話再掃一次）。
- 異常處置：`logged_out=0`（已登入但未確認登出）→ 巡檢會報 critical（`check_scheduled_jobs.py` 改動處）；立刻回滾 §3.3 並請 PO 檢查手機／電腦登入狀態與帳號是否被限制。

### 3.3 回滾

1. **停排程（最先做）**：
   ```bash
   launchctl bootout gui/$(id -u)/com.alphavibe.investanchorsimport
   echo "bootout 結束碼：$?"
   rm -f ~/Library/LaunchAgents/com.alphavibe.investanchorsimport.plist
   launchctl print gui/$(id -u)/com.alphavibe.investanchorsimport 2>&1 | head -3     # 預期「Could not find service」
   ```
2. **程式回滾**：用 `deploy.sh` 在結尾印的 `$OLD`（`deploy.sh:69`）：
   ```bash
   cd /Users/stander/My_project/AlphaVibe-prod && git fetch origin function/alphavibe && bash <(git show origin/function/alphavibe:ops/deploy.sh) c9b99f4
   ```
   （`c9b99f4` 為 010 合併前的 `function/alphavibe` 頂端，出處 §1.1；若部署時 `OLD` 與此不同，以實際印出者為準。此指令會自動 kickstart reportserver，使連接器回到 48／29／8。）
3. **資料回滾**：`alphavibe.db`／`us_stocks.db`／`flights.db` 不受 010 影響（§2.2），一般不需還原；若要還原以 §2.2 的備份為準，且先停服務。010 自己的資料只有 `<data>/articles.db`、`articles_images/`、`articles_probe/`——**要完全撤銷就刪這三者**（刪除前請 PO 同意；`articles.db` 已納入每日備份，`articles_images/` 與 `articles_probe/` 不在備份內，§6 風險 1）。不要動 `poc/data-test-articles/`（測試庫，`quickstart.md:67` 要求保留）。
4. 回滾後驗證：§2.4 的 `curl` 預期 404、工具數預期 48／29／8（回到舊版）。

---

## 4. PO 手動事項清單（依 `tasks.md` 原文順序與依賴）

來源：`tasks.md:159-174`、依賴圖 `tasks.md:186-191`、PO 待辦表 `tasks.md:230-238`。

| 順序 | 任務 | PO 要做的事 | 依賴 | 做完怎麼驗證（不讀秘密） |
|---|---|---|---|---|
| 0 | T054（本文件對象） | 審查本材料，決定通過與否 | T053 | 主對話回覆通過；T053 在 `tasks.md:157` 仍為未勾選，**進入 T055 前須確認已完成並勾選** |
| 1 | T055 | 同意並在場：提交推送→備份→部署→安裝 plist→launchd 實跑一次。**轉寫開關維持關閉** | T049／T050／T054 | §2.4、§3.2 的唯讀查詢全部符合預期；`logged_out=1`；手機仍在線 |
| 2 | T056 | 在 Mac 的 `~/.claude` stock-researcher 白名單手動加入 `search_articles`、`get_article`（不在 repo，agent 不改 `~/.claude`；`tasks.md:160`、`quickstart` 補述） | T055 | 開新 session 讓 stock-researcher 查一次（會得到「文章庫尚未建立」或實際結果，而非「無此工具」）；或比對 `~/.claude/agents/stock-researcher.md` 的 tools 清單含兩個名稱 |
| 3 | T057 | 每隔幾天唯讀檢視回補進度與圖片累積（`quickstart.md:84-99` 的 `sqlite3 -readonly` 查詢）；回補約 20 天完成。目標：≥10 張且含 ≥1 張長圖 | T055 | 圖片計數查詢≥10；`--transcribe-sample` 回報含長圖（`tasks.md:168`）；`import_runs` 無 `logged_out=0` |
| 4 | T058 | 累積達標後把視覺模型 API 金鑰存進鑰匙圈：`security add-generic-password -U -s stnd-investanchors -a vision-api-key -w`（`-a` 後是固定名稱、`-w` 後**不接任何東西**、互動輸入；`tasks.md:169`）。存了不會啟動轉寫 | T057 | `security find-generic-password -s stnd-investanchors -a vision-api-key >/dev/null 2>&1 && echo 存在`（不加 `-w`／`-g`）；再確認開關仍關：`sqlite3 -readonly …/articles.db "select value from setting where key='transcribe_enabled';"` 無列或為 0 |
| 5 | T059 | 同意並逐格確認抽查：`python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data --transcribe-sample 10`（須含長圖；少量 API 費用；只讀本機圖、不登入網站、不寫 DB；輸出在 `poc/data/articles_probe/transcribe-sample-<時間>.md`）。PO 本人比對轉寫與原圖；不認可→升級模型（改 `TRANSCRIBE_MODEL`、提交推送、主對話審查）再抽 | T058、T040 | PO 逐格比對結論記入 `quickstart.md`「實測」節；**這也是真實 API 請求格式（§5）的首次驗證** |
| 6 | T060 | 同意打開開關：`… --data-dir poc/data --enable-transcription` | T059 通過 | 開關查詢回 `1`；`check_scheduled_jobs.py` 摘要「轉寫開關 開」 |
| 7 | T061 | 補轉積壓圖片：`… --data-dir poc/data --retranscribe`（只讀本機圖） | T060 | 在對話搜表格內才有的數字／代號能找到該文章（SC-008）；失敗者有「未轉寫」標示（SC-007） |
| 8 | T062 | 回補完成（`completed=1`）後，對真實網站跑 `article_reconcile.py` 逐篇核對（SC-001：缺漏 0、重複 0）。**排程已安裝，須遵守通用規則 8**：當天先停用 `com.alphavibe.investanchorsimport`（`launchctl bootout …`），核對完再重新 bootstrap；PO 在場、只留手機一台；只跑一次 | T057（回補完成） | 核對輸出缺漏／重複為 0；排程重新啟用後 `launchctl print` 確認已載入；`import_runs` 當日只有一次登入 |
| 9 | T063 | 上線驗證期至少兩週，每週檢視：進庫時間 vs 發布時間（SC-002）、睡眠補跑是否與 PO 使用時段重疊（必要時另開「時間窗守衛」任務）、`import_runs` 登入次數與 `logged_out`、帳號未被鎖（SC-005）、`abandoned` 與 `id_time_ok=0` 數量、轉寫成本與失敗率、通知是否過量；結論更新 `research.md` R8／R12 | T055 | 每週一次的唯讀查詢結果與結論回報主對話 |

（T062 與 T057 之間、T063 與其他並行的細部依賴以 `tasks.md:186-191` 為準。）

---

## 5. 已知限制與上線後待驗證清單

| 項目 | 現況 | 出處／驗證方式 |
|---|---|---|
| SC-001 逐篇核對 | 程式層有 `article_reconcile.py` 與 e2e 測試；**真實核對尚未做**，T062 才驗 | `spec.md:215`；`tasks.md:173` |
| SC-002 兩週無遺漏、下一次登入即匯入 | 只能上線後觀察；**未驗證** | `spec.md:217`；`tasks.md:174` |
| SC-005 帳號未被鎖／限制 | 只能上線後觀察；T023 一次真實單篇執行後手機仍在線，但不足以證明長期 | `spec.md:223`；`tasks.md:83` |
| SC-007 轉寫一致率 | 程式層僅用假模型驗證；真實準確度靠 T059 PO 逐格抽查；**未驗證** | `spec.md:225`；`tasks.md:125,170` |
| 真實視覺模型品質 | 模型名 `claude-haiku-5-5` 僅做過官方文件查證（T033），**從未真實呼叫** | 提交 `51ebee8` 訊息；`research.md` R5 |
| 真實 API 請求格式 | `x-api-key` 加 `anthropic-version: 2026-10-21` **從未對真實 API 驗證**；首次真實請求會是 `--transcribe-sample`；401／400 先看 research R5 的 T033 小節，不要先改模型 | `quickstart.md:60` |
| 切片器空白帶門檻 | 99%、容差 10、連續 ≥4 列只用合成圖調過；Importer 預設長圖路徑沒做端到端整合（測試用假 runner） | `quickstart.md:61` |
| 轉寫沒有圖片間延遲 | 模型 API 呼叫節奏未限制，量大留意 429 | `quickstart.md:64` |
| 篇間隔只有推論一致（T048） | 呼叫者告知「篇間隔只有推論一致」；repo 內對應敘述我未能定位（`grep 篇間隔` 於 tasks／research／quickstart 僅命中 T014 規格處），**未驗證**；篇間隔下限防呆另行提交（不在本 diff） | `tasks.md:74`（T014 規格：篇間隔 30～90 秒）；未驗證 |
| 回歸基準 5 個既有失敗 | `unittest discover` 1407 個測試中，既有 5 個失敗／錯誤與本功能無關：`test_us_stock_price_client.GetQuoteFallbackTest` 4 個、`test_flight_search.SampleDatesTest.test_covers_requested_number_of_months` 1 個（後者為日期敏感測試，CLAUDE.md 亦記載） | `tasks.md:20`；`CLAUDE.md`（008 段落）。本文件**未重跑**，數字為 2026-11-15 基準，未驗證其現況 |
| `test_check_scheduled_jobs` 單檔 3 個既有 error | 由呼叫者告知；我在 repo 文件中**找不到**這項記載（`tasks.md:20` 的基準只列上面 5 個），單檔跑與整體 discover 結果可能不同，**未驗證**，請審查者實跑單檔確認這 3 個與 010 無關（`git diff` 對該檔只新增 `InvestanchorsImportCheckTest`，未改既有測試） | 呼叫者訊息；`git diff ab5de1c~1 HEAD -- poc/kb-mcp/tests/test_check_scheduled_jobs.py` |
| `app/` smoke test | `app.tests.test_smoke` 依 CLAUDE.md 的重建步驟需獨立測試庫；T052 已勾選；本文件未重跑 | `tasks.md:156`；`CLAUDE.md`「STND（app/）驗證」 |
| 通知信只當觸發、約一半信搜得到 | PO 表示每篇都寄信，實測只搜到約一半；設計上信漏搜只延後觸發 | `research.md:36`（P4）；`tasks.md:174` |
| T048 狀態 | `tasks.md:143` 已勾選 `[x]`，但**未附實測結果**（T023 有）；`quickstart.md:73`、`CLAUDE.md` 仍寫「T048 待 PO」。文件需同步 | 上述三處 |

---

## 6. 審查中發現的風險與疑慮

1. **已決定（PO，2026-11-16）：articles.db 納入每日備份；articles_images/ 不備份（原風險已處理）**：以 `OPTIONAL_DATABASES` 納入，沿用 `Connection.backup()`＋`integrity_check`＋gzip 與同一套輪替（每日留 30、每月 1 號收進 monthly 留 24）。圖片只是備份用途、需要時回定錨網站重抓——但**現有工具沒有「對指定文章重抓圖片」的能力**（`quickstart.md` 第 11 節），這是接受的殘餘風險：圖檔遺失後，圖片本身無現成還原路徑（轉寫文字在 `articles.db`，已備份）。`check_scheduled_jobs.check_backups` 只看 `alphavibe-*`，未新增 articles 備份缺漏／過舊檢查（待主對話決定）。
2. **`deploy.sh` 無資料備份、無工具數驗證（低～中）**：健康檢查只看 `/mcp/wrong`=404（行 66），不證明新工具已載入；請務必加做 §2.4 的工具數檢查。
3. **`keychain_secrets.py` 被 009 共用（中）**：已上線的 009 對帳單匯入也呼叫 `get_secret`；改動向後相容（預設 service 不變），但請審查者實跑 009 相關測試確認（本文件未驗證）。
4. **`app/article_deps.py` 未接線（低）**：含完整防呆但沒有 router 使用，屬待用程式碼；不影響上線，但審查者可決定是否保留。
5. **文件與現況落差（低）**：根目錄 `CLAUDE.md` 與 `quickstart.md` 的 T048「待 PO」敘述已過時；`tasks.md` 的 T053、T054 仍未勾選（`tasks.md:157-158`），而最近提交 `d2308b5` 訊息顯示 T053 驗收已發現並修正問題——是否重驗通過、是否已勾選，請主對話確認。
6. **diff 內本不該出現／需人工過目的檔案**：`.specify/feature.json`（工具指標，合併後會讓之後新 feature 預設指向 010）、`docs/spec-intake/investanchors-import/raw/src-002-article-list.png`／`src-003-article-body.png`（網站畫面截圖，77KB／251KB；可能含帳號相關畫面，未打開查看）。除此之外，diff 內**沒有**發現 `poc/data*`、`.db`、`.env`、金鑰或 token 檔案（`git diff --name-status` 清單中無此類路徑）。
7. **scraper 另有未提交修改（需注意順序）**：另一個 agent 正在改 `investanchors_scraper.js` 與其測試，合併／部署前必須先提交並重新通過 §5 的回歸，否則審查對象與正式版不一致。
8. **首次正式實跑會用掉當日登入額度**：見 §3.2（通用規則 8）；手動 kickstart 與 23:00 排程只能擇一。
9. **未驗證的環境假設**：`AlphaVibe-prod` 的 scraper `node_modules` 與 Playwright 瀏覽器是否已安裝可跑 010 的 scraper（deploy 因 package 檔未變不會 `npm ci`；機票 scraper 已共用同目錄，推定可用，但**未驗證**）；`/usr/bin/python3`（plist 指定）需為 3.9 相容，010 程式碼是否全程 3.9 相容**未驗證**（CLAUDE.md 2026-07-07 教訓）。
