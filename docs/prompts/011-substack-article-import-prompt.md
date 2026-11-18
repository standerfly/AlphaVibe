# 開發任務 prompt：Substack 文章自動匯入（011，新功能；先 pre-spec）

> 用法：PO 在 Mac 的 VS Code **開新對話**，把「## Prompt 本文」整段貼進去。開發者先 `git fetch origin function/alphavibe` 取得最新版。
> 本檔在 `docs/prompts/`，不屬任何 `specs/` 產物（pre-spec 階段不得建立 `specs/` 下的東西，見 CLAUDE.md ADR-0027）。

## Prompt 本文

你是 AlphaVibe 專案的資深架構師兼開發者。PO（Stander）是 PO/TPM，不寫程式，終端機是 zsh。**先讀**：`CLAUDE.md`（含 010、009 段落與全部教訓紀錄）、`docs/runbooks/pre-spec-workflow.md`、`docs/adr/0027-prespec-workflow.md`，以及 010 的實作與規格作為**可重用的範本**：`specs/010-investanchors-article-import/{spec,plan,research,data-model,quickstart,contracts/cli}.md`、`poc/kb-mcp/{article_store,article_tools,article_data_guard,investanchors_limits,investanchors_redact,investanchors_mailbox,keychain_secrets}.py`、`app/article_deps.py`。

### Purpose（目的）
PO 在 substack.com 追蹤了喜歡的作者；有新文章時 PO 的 Gmail 會收到通知信。PO 要 Mac 自動把這些文章存下來（PO **目前沒有付費訂閱**，所以付費文章只會有摘要／預覽），讓 AlphaVibe 在 claude.ai 對話（台股／美股連接器）中能搜尋並引用。目標：**有效使用資源、方便未來維護**——不要為 Substack 另造一整套平行系統。

### Target（環境與已知事實）
- 環境：macOS Apple Silicon Mac mini；`/usr/bin/python3` 3.9.6（只用標準庫、3.9 相容）；Node 26；Playwright 已有（scraper 目錄）；排程用 launchd；正式環境在 `AlphaVibe-prod`（git worktree，`ops/deploy.sh` 部署）；Gmail 以 IMAP 唯讀＋鑰匙圈取信（`investanchors_mailbox.py` 的模式）。
- 010 的已驗證經驗（**必讀並沿用，不要重新發明**）：低頻守衛（每日登入與間隔上限）、新資料目錄防呆（`article_data_guard`：realpath、正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`）、外洩掃描與 `no_leak` 測試、固定文字通知、台美連接器共讀同一個唯讀 `articles.db`、MCP 工具數守門（台股 50／唯讀 31／美股 10；新增工具要同步 `server.py`／`server_readonly.py`／`us_stock_mcp_server.py`／兩個守門測試與 Mac 上 `~/.claude` stock-researcher 白名單）、轉寫驗證等級（未驗證不進搜尋）、「驗證不能由產出者自己做」的獨立驗收流程。
- **要先查證、不可假設**（請在 pre-spec 的 research 階段用官方文件與實測確認，並寫進 research.md）：Substack 是否提供公開 RSS／Atom（常見為 `https://<出版名>.substack.com/feed`，自訂網域通常為 `/feed`）、feed 內含全文還是摘要、付費文章在 feed 的呈現、更新頻率、有無速率限制、通知信的格式與連結結構（追蹤轉址不可跟隨，見 010 教訓）、站方服務條款對自動存取的規定、robots.txt。**不得繞過付費牆、不得登入他人帳號或使用 PO 的 Substack 登入 cookie 抓取付費內容**；PO 目前無訂閱，只存公開可見的內容。
- 資料與版權：文章只供 PO 個人本機參考，不轉發、不公開；專案是 local-first。

### Components（請在 pre-spec 就這些與 PO 逐題釐清，每題附你的建議與取捨）
1. **取得方式**：以 RSS 輪詢為主（無登入、風險最低）、Gmail 通知信只當「新文章線索／發現新出版」的觸發？或兩者並用？請比較成本與可靠度。
2. **追蹤清單**：作者／出版清單從哪來（PO 手填設定檔、從 Gmail 通知信自動發現、或兩者）；新增／停用一個出版的操作方式（PO 不寫程式，要簡單）。
3. **資料模型與重用**（核心決策，請給 2～3 個方案與推薦）：與 010 共用 `articles.db`（加 `source` 欄位，如 `investanchors`／`substack:<出版名>`，以加欄位、不破壞既有資料的方式遷移）並讓既有 `search_articles`／`get_article` 加 `source` 篩選與來源標示，**不新增 MCP 工具**；或獨立 `substack.db`＋新工具。請評估：既有守衛／唯讀開庫／備份（`backup_databases.py` 的可選庫機制）／健檢（`check_scheduled_jobs`）／連接器台美一致性的影響與遷移風險；以及不同來源的可信度標示（引用 Substack 作者的意見時，agent 必須標明來源與「僅摘要」）。
4. **內容處理**：付費文章只有摘要時的標記（`僅摘要`）、全文與摘要的區分、圖片（是否下載；表格圖是否沿用 010 的轉寫與驗證流程，或先不處理）、重複與更新文章的處理、去重鍵（文章 URL／GUID，勿用傳輸層鍵）。
5. **排程與通知**：頻率（建議低頻，例如每日數次；對站方禮貌）、Mac 睡眠補跑、Telegram 通知內容（固定文字，不含標題全文？與 010 一致）、失敗與封鎖的處理。
6. **維運**：備份、健檢警示、日誌與外洩掃描、回滾、部署（沿用 `ops/deploy.sh`）、文件（quickstart 接手備忘）。

### Function（流程與限制）
- **流程**：嚴格走 ADR-0027——先 `/prespec`（`docs/spec-intake/substack-import/`：product-spec、clarification-log、scope-decision…；**未 Accepted 前不寫程式、不建 `specs/`**）→ PO 審閱 Accepted → Spec Kit（`speckit-*`，分支編號先查 `function/alphavibe` 的 `specs/` 已用號碼，010 之後是 011 起）→ 實作 → 每階段全新 agent 獨立驗收 → PO 同意才合併／部署。功能分支 `function/substack-import`（基底 `function/alphavibe`）。
- **回應風格**：繁體中文、簡短直接；需求不明就問 PO，不猜；給建議而非羅列選項。
- **安全與隱私（硬性）**：日誌、通知、回報不得含帳密、cookie、token、文章標題與全文；對外請求（RSS 抓取）用**通用** User-Agent，**不得放 PO 的 email 或任何個資**；不登入、不用 cookie；鑰匙圈檢查只用存在性（`find-generic-password … >/dev/null && echo ok`），**禁止** `dump-keychain`、`-w`、`-g`；給 PO 的貼上指令一律 zsh 相容；任何要讀 Gmail／鑰匙圈的真實執行須 PO 在對話中親自同意。
- **低頻與禮貌**：對站方的請求量維持最低（遵守 robots.txt、設定逾時與間隔、用 ETag／If-Modified-Since 之類條件請求若 feed 支援），被擋或異常即停並通知，不重試轟炸。
- **不要做**：不繞過付費牆、不抓付費全文、不自動轉發內容、不在 pre-spec 階段寫程式、不改 010 既有行為（共用資料庫的遷移必須向後相容且可回滾）、不部署前未備份。
- **環境注意**（CLAUDE.md 教訓）：先 `pwd` 與 `git status`；Python bytecode 快取問題（`模組.__cached__`）；macOS 路徑 `/var`→`/private/var` 比對用 `os.path.realpath`；測試用獨立資料目錄，不碰正式庫。

### 第一步（本次對話先做到這裡就回報）
1. 讀完上述文件與程式，用 3～5 句話向 PO 複述你理解的需求與你認為最大的風險。
2. 做 research（RSS／通知信格式／站方條款，唯讀、不登入、請求量極低），把結論與不確定處列給 PO。
3. 提出「資料模型與重用」的 2～3 個方案與推薦，以及需要 PO 回答的釐清問題清單（不超過 10 題，每題附建議）。
4. 經 PO 回答後，用 `/prespec` 產出需求基線草稿（仍不寫程式）。
