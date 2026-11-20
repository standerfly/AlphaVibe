# Quickstart: Substack 文章抓取與儲存（011，第 1 包）

給接手者（Claude／開發者）與 PO。指令皆可直接貼進 macOS zsh；含迴圈的部分寫成 `bash -c` 或直接展開清單。
正式環境在 `/Users/stander/My_project/AlphaVibe-prod`（見專案 CLAUDE.md），**開發與測試一律用獨立資料目錄**。

**工作位置**：011 在獨立 git worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`）開發與測試。主資料夾 `/Users/stander/My_project/AlphaVibe` 被其他 session 佔用、可能被切到別的分支，**不要假設其分支**，不得碰、不得在那裡切換分支、commit 或推送。正式環境仍是 `/Users/stander/My_project/AlphaVibe-prod`（路徑不變）。換環境或隔一段時間接手：先 `pwd`、`git branch --show-current`（須為 `011-substack-fetch-store`）、`git status`。

## 1. 接手前必讀

1. `spec.md`（唯一需求依據）、`plan.md`（含「已決定」表與仍待確認的 FR-013 暫解讀）、`research.md` R0（重用邊界）與 R10（已知坑）。
2. 本包**沒有** MCP 工具、STND 頁面、即時取得——那些屬第 2 包，不要先做。**本包有**重新判斷完整度的指令（`--reclassify`，FR-033，PO 2026-11-20 決定提供）。
3. 不改 010 的任何行為：`article_store.py`、`transcription_pipeline.py`、`investanchors_*.py`、`claude_cli_runner.py`、`notify.py`、
   `article_data_guard.py`、`investanchors_redact.py` **只 import 不修改**；只有 `backup_databases.py`、`check_scheduled_jobs.py` 做 research R7 列出的新增。
4. 換環境或隔一段時間接手：先 `pwd`、`git status`、`git diff --stat`（CLAUDE.md 2026-08-09 教訓）。

## 2. 建立測試資料目錄（不碰正式庫）

```bash
cd /Users/stander/My_project/AlphaVibe-011
mkdir -p poc/data-test-substack
python3 poc/kb-mcp/substack_config.py --data-dir poc/data-test-substack init
python3 poc/kb-mcp/substack_config.py --data-dir poc/data-test-substack validate
python3 poc/kb-mcp/substack_import.py --data-dir poc/data-test-substack --dry-run
```
`poc/data-test-substack/` 要在 `.gitignore`（tasks 階段補一行；`poc/data-test/` 已在 `.gitignore:14`，但名稱不同不會自動涵蓋）。

## 3. 自動化測試

```bash
cd /Users/stander/My_project/AlphaVibe-011
python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack*.py'      # 011 新測試
python3 -m unittest discover -s poc/kb-mcp/tests                              # 全套（含 010，必須全綠，SC-004）
```
- 所有 011 測試以注入的假 HTTP（feed／圖片／robots）、假 notifier、假時鐘、假 claude runner 執行；**不連真網站、不呼叫模型**。
- 「改了程式但行為沒變」→ 先查 `python3 -c "import sys; sys.path.insert(0,'poc/kb-mcp'); import substack_import as m; print(m.__cached__)"`，
  必要時刪 `~/Library/Caches/com.apple.python/` 下對應 `.pyc`（CLAUDE.md 2026-09-03）。獨立驗收用乾淨副本：
  `git archive HEAD | tar -x -C "$(mktemp -d)"`。

## 4. 驗證步驟對照（驗收時逐項跑，證據貼進驗收報告）

| # | 驗證 | 怎麼做 | 預期 |
|---|---|---|---|
| V1 | 首次只收 14 天、重跑不重複（US1-AS1/2、SC-002） | 測試 `test_substack_import`：假 feed 20 篇跨 3 個月，跑兩次 | 第一次只存窗內篇數；第二次總數不變 |
| V2 | 三類分類（US2、SC-006） | `test_substack_classify`：以兩位作者真實 feed 的**結構樣本**（Read more 尾端、純播放器、嵌入卡片、長文帶 Read more、免責聲明結尾）組成 fixture | 規則表逐篇吻合；不確定者全為 P |
| V3 | 缺圖、補下載、放棄（US3、SC-008） | `test_substack_images`：一張圖連續失敗 | 第 1、2 次 `missing`，第 3 次 `abandoned`，之後不再請求；`--retry-images` 後再試 |
| V4 | 單一作者被擋不拖累（US4、SC-007、SC-011） | 假 feed：A 回 403、B 正常；兩種告警策略各跑 | A 停手＋立即告警、B 照常；`consecutive_3` 下逾時第 3 次才告警 |
| V5 | 忙碌不寫庫（FR-017） | 測試先持有 `.substack_import.lock` 再執行 | exit 3、`substack.db` 位元組不變 |
| V6 | 不呼叫模型、不碰 010（SC-003、SC-004） | `test_substack_isolation`（research R1 T-A／T-B／T-C／T-D）＋全套測試 | 流水線選取 0 筆 011；`articles.db` 前後位元組相同 |
| V7 | 外洩掃描（SC-005） | `test_substack_no_leak` | 日誌／錯誤／DB 非資料欄位／檔名不含標題、內文、文章網址 |
| V8 | 健檢（US7、SC-010） | `test_check_scheduled_jobs` 新增案例＋手動：`python3 poc/kb-mcp/check_scheduled_jobs.py --data-dir poc/data-test-substack --state-file "" --json` | 每日含剩餘空間、占用量、放棄張數、上次成功、失敗統計；空間項無判定字眼與閾值（提醒句用「提醒：」現況措辭） |
| V9 | 備份（US7-AS3） | `python3 poc/kb-mcp/backup_databases.py --data-dir poc/data-test-substack --dest "$(mktemp -d)"` | 有 `substack-*.db.gz`（完整性 ok）與 `mirror/substack_images/` |
| V10 | 補跑判斷（research R2、FR-017） | 假時鐘測試：22:00 已跑 → 01:00 `already_done`；23:30 醒來 → `deferred`；07:00 醒來且當日未跑 → 執行；**邊界 21:59／22:00／23:00／23:59／00:59／01:00**；`deferred`／`already_done` 紀錄不影響後續 01:00 判斷 | 如左 |
| V11 | FR-027 | `test_substack_isolation`：`.gitignore` 涵蓋 `poc/data/`；`app/`、`server*.py`、`us_stock_mcp_server.py` 不含 `substack`；備份目的地在家目錄；通知文字不含 `http` 與任何文章網址片段 | 全過 |
| V12 | 重判（US2-AS6/7、FR-033、SC-012） | `test_substack_reclassify`：重判前後 `article` 位元組不變、`reclassification` 逐次新增、`article_effective` 取最近一筆、攔截網路與 subprocess 為 0 次 | 原判斷與歷史皆保留 |
| V13 | 圖片白名單（US3-AS4、FR-034、SC-013） | `test_substack_images`：非白名單主機的圖零請求、記 `host_not_allowed`；`add-image-host` 後可 `--retry-images` | 如左 |
| V14 | 通知內容與摘要（FR-025、SC-014） | `test_substack_import`：逐篇通知含作者／標題／完整度、無連結；追補逐篇；有告警無新文章也發含空間現況的摘要 | 如左 |
| V15 | 預算強制中止與交易回滾（research R2／R8） | 假時鐘＋卡住的假 HTTP；回滾注入測試 | 預算內中止、鎖釋放、無 `.part`、無半寫入 |
| V16 | 手動轉寫不動 010（T-C 執行期） | `test_substack_isolation`：攔截 `sqlite3.connect`／`open`，全程未開啟 `articles.db`；`XPC_SERVICE_NAME` 三種值案例 | 全過 |

## 5. 上線（PO 在場；安裝排程與首次真實抓取都要 PO 當下確認，FR-020）

1. PR 合併進 `function/alphavibe` 後部署（CLAUDE.md「部署」指令；`ops/deploy.sh` 不需修改）。
2. 正式設定檔（只做一次）：
   ```bash
   cd /Users/stander/My_project/AlphaVibe-prod
   ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 python3 poc/kb-mcp/substack_config.py --data-dir poc/data init
   ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 python3 poc/kb-mcp/substack_import.py --data-dir poc/data --dry-run
   ```
3. **首跑檢核（PO 在場，手動跑一次）**：
   ```bash
   cd /Users/stander/My_project/AlphaVibe-prod
   ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_import.py --data-dir poc/data
   ```
   **先確認資料磁碟實際剩餘空間**：`df -h /System/Volumes/Data`（或 `df -h poc/data`）——`df -h /` 看到的是系統卷、不代表資料磁碟（2026-11-20 實測資料卷 91% 已用、約 20Gi 可用）；圖片鏡像會使圖片占用翻倍，本包不設閾值，由 PO 判斷。
   確認：兩個 feed 都 200（FOMO 若失敗，依 `contracts/config-format.md` 改網址）；新增篇數約 25；P/F/N 分布與 2026-11-19 實測相近
   （約 35／40 為 P）；Telegram 收到逐篇通知＋1 則摘要；`--status` 中缺圖張數；圖片主機是否都在白名單（若出現 `host_not_allowed`，
   評估後以 `add-image-host` 補）。
4. 安裝排程（PO 說「安裝」後才執行）：
   ```bash
   cp /Users/stander/My_project/AlphaVibe-prod/ops/launchd/com.alphavibe.substackimport.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphavibe.substackimport.plist
   launchctl print gui/$(id -u)/com.alphavibe.substackimport | grep -i state
   ```
5. 隔天：`tail -n 30 ~/Library/Logs/alphavibe-substack.log`，確認 22:00 執行、01:00 為 `already_done`、耗時（Q-105 實證）。

## 6. 日常操作（PO 在對話中提出，Claude 執行）

| PO 說 | Claude 執行（正式目錄前加 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`） |
|---|---|
| 追蹤／停用／重新啟用作者、改間隔、改告警策略 | `substack_config.py ... add|disable|enable|set-interval|set-alert-policy`（見 `contracts/config-format.md`） |
| 追補某作者更早的文章 | `substack_import.py --data-dir poc/data --backfill <代號>` |
| 某張圖再試一次 | `substack_import.py --data-dir poc/data --retry-images <image_id,...>` |
| 某幾篇／某作者的完整度判斷怪怪的，重新判斷 | 先 `substack_import.py --data-dir poc/data --reclassify --author <代號> --dry-run`（或 `--article-ids`）回報會改幾篇，PO 同意後去掉 `--dry-run`；歷史用 `--reclassify-history <id,...>` |
| 圖片主機增修白名單 | `substack_config.py --data-dir poc/data add-image-host|remove-image-host <主機>` |
| 看現況 | `substack_import.py --data-dir poc/data --status` |

## 7. 手動轉寫試跑（US6；會消耗 claude.ai 訂閱用量）

```bash
cd /Users/stander/My_project/AlphaVibe-prod
ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_transcribe.py --data-dir poc/data --plan --per-author 1
```
1. Claude 把 `--plan` 的篇數、圖數、預估呼叫次數與確認碼貼給 PO，**等 PO 在當下對話說確認**（別的對話的同意不算）。
2. PO 確認後：`... substack_transcribe.py --data-dir poc/data --run --confirm <確認碼> --per-author 1`。
3. 驗證：`--report` 看篇數／成敗／呼叫次數；直接查庫確認結果可查找引用：
   `sqlite3 "file:poc/data/substack.db?mode=ro" "SELECT image_id, is_table, length(text) FROM image_transcription ORDER BY image_id DESC LIMIT 10;"`；
   跑 010 全套測試＋比對 `articles.db` 試跑前後 `shasum -a 256`（US6-AS2）。
4. 已知限制：010 提示詞只轉寫表格圖，非表格圖記「非表格」；「消耗」只記呼叫次數與圖數（取不到額度百分比）。

## 8. 回滾

```bash
launchctl bootout gui/$(id -u)/com.alphavibe.substackimport          # 停排程（立即停止所有自動請求）
cd /Users/stander/My_project/AlphaVibe-prod && git fetch origin function/alphavibe \
  && bash <(git show origin/function/alphavibe:ops/deploy.sh) <舊commit>   # 程式回到 011 之前
```
資料：`poc/data/substack.db`、`poc/data/substack_images/`、`poc/data/substack_config.json` 皆為 011 專屬，可保留或刪除；要還原用
`~/AlphaVibe-backups/daily/substack-*.db.gz`（`gunzip` 後放回）與 `~/AlphaVibe-backups/mirror/substack_images/`。不需動 `articles.db`。

## 9. 接手備忘（坑）

- 日誌絕不印標題、文章網址（slug 常是標題）、圖片網址、notify 錯誤原文（Bot token 遮不到，research R4）。
- `poc/kb-mcp/substack_*.py` 全文（含註解與字串）不得出現 `articles.db`／`article_store`／`ArticleStore`（T-A 靜態測試掃全文）；要提 010 時寫「010 文章庫」。
- 路徑比較一律 `os.path.realpath`（`/var`→`/private/var`）。
- `SubstackStore()` 建構子只建表；唯讀開庫不得建檔。
- 排程日判斷只看實際執行過的排程列，要排除 `deferred`／`already_done`（research R2）；sqlite3 一律 `isolation_level=None`＋`transaction()`（research R8）；`XPC_SERVICE_NAME` 判斷用 `com.alphavibe.` 前綴、不是「是否存在」（research R1 T-D）。
- 通知不含文章連結（PO 決定 A1）；要看原文時用作者與標題向 Claude 查本機文章庫。
- 新增「會消耗 token 的排程」時，要把它加進 `check_scheduled_jobs.py` 的 `TOKEN_JOBS`，否則 FR-030 間隔提醒看不到它。
- 改 plist 後重新載入：先 `launchctl bootout`，確認 `launchctl print` 查不到後再 `bootstrap`（CLAUDE.md 2026-10-29）。
