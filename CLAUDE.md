# AlphaVibe 專案指南（v3，2026-08-22；v3：STND 個人主控台正式上線）

## 這個 repo 是什麼

**個人投資知識庫與選股估值工作流**（2026-07-07 主軸重塑：基本面選股→
估值→交易紀錄；引擎＝Claude 聊天思考＋Cline 粗活、local-first，Q-028~032）。
需求基線 product-spec 已 **Accepted**（2026-07-08）。

**code 現況（2026-08-22 更新）**：正式對外服務是 **STND**（個人遠端主控台，
UI 品牌名；技術/repo 層級仍叫 AlphaVibe），FastAPI（`app/`）+ React
（`web/`），已於 2026-08-22 正式取代 `poc/kb-mcp/report_server.py` 常駐
在 `:8080`／ngrok 固定網址 `chancefully-erosive-lilian.ngrok-free.dev`。
`poc/kb-mcp/` 不再是唯一可跑的東西，但**底層演算法/資料層仍是它**——
`app/` 的所有 router 都是直接 import `poc/kb-mcp/*.py` 既有函式，沒有
重寫任何商業邏輯，`poc/kb-mcp/` 因此仍是查證計算邏輯的地方。
`docs/swagger.yaml`、`docs/docs.go`、`frontend_mockup.html` 仍是模板/
mockup 殘留，不代表這些。分頁對照見下方「STND 分頁與程式碼位置」。

**目前階段：STND 骨架已上線，功能持續擴充中**——完整進度與各階段接手
指南見 `docs/spec-intake/alphavibe/roadmap.md`（接手任何開發工作前先讀
它，尤其 Q-046）。

## STND 分頁與程式碼位置（2026-08-22 新增，避免接手時找錯地方）

STND 是「個人一站入口」的定位（不只投資），會隨時間長出更多分頁。每個
分頁的程式碼**全部住在這個 repo**（`app/` + `web/`），不會因為分頁主題
不同就分散到別的 repo；但分頁背後的**內容/資料**可能來自其他獨立專案，
兩者是分開的兩件事：

| 分頁 | 前端頁面 | 後端 router | 內容/資料來源 |
|---|---|---|---|
| 首頁 | `web/src/pages/Home.jsx` | 彙總其他分頁 API | 本 repo |
| 儀表板 | `Dashboard.jsx`／`StockDetail.jsx` | `dashboard.py`／`screen.py`／`market_scan.py`／`holdings.py`／`stock_detail.py`／`actions.py` | `poc/kb-mcp/`（report.py／screener.py／frameworks.py，未重寫） |
| 資產 | `Assets.jsx` | `assets.py` | `kb_store.py` 新增 5 張表，手動輸入，無外部依賴 |
| 相簿 | `Photos.jsx`（MVP 僅入口） | 尚無 | 未來：AutoGallery 資料模型參考（僅有 README 內容，本機實際 repo 路徑未定位到，見 clarification-log） |
| 旅遊（未來，尚未建立） | — | — | 內容/研究在**另一個獨立專案** `/Users/stander/My_project/mytravel/`——若要做這個分頁，程式碼仍會建在這個 repo，但要不要整合 mytravel 的資料、整合到多深，屬於獨立待討論的範圍決策，不要預設 |

新增分頁前的判斷順序：(1) 先跟 PO 討論這個領域要不要進 STND、做到多深
（純導覽連結 vs 完整資料整合）——不要預設「以後什麼都變一個分頁」；
(2) 決定後才動工，程式碼一律加進本 repo 的 `app/`／`web/`，不另開新 repo。

使用者 Stander 在此專案的角色是 PO/TPM：需求釐清、規格文件、決策；
不以寫碼為日常。

## 工作流（ADR-0027 兩段式）

1. **Pre-spec（現階段）**：原始素材 → 審閱過的需求基線。用 `/prespec` skill。
   產物在 `docs/spec-intake/<feature-slug>/`：`product-spec.md`、
   `clarification-log.md`、`scope-decision.md` 等。
2. **Spec Kit（下游）**：需求基線 → `specs/` 技術規格與實作。用 `speckit-*` skills。
   pre-spec 階段**不得**建立 `specs/` 下的任何產物。

完整流程說明：`docs/runbooks/pre-spec-workflow.md`；
決策依據：`docs/adr/0027-prespec-workflow.md`。

## 分支規則

- 功能分支：`function/<feature-slug>`（kebab-case），基底鎖定 `develop`（ADR-0027）。
- **已知現況（2026-07-06）**：repo 目前**只有** `function/alphavibe` 分支，
  `develop` 尚未建立。初始化腳本寫死以 develop 為基底，直接跑會失敗——
  遇到新功能要初始化時，先問使用者要補建 `develop` 還是改用 `--no-branch`。
- 初始化腳本完整路徑：`.claude/skills/prespec/scripts/prespec_init.py`
  （不在 repo 根目錄）。不要手動開分支。

## 本 repo 的具體注意事項

- **協作模式（2026-08-09 確認）：雲端 session 與本機操作可能共用同一個
  對話，執行環境會在雲端沙箱與本機之間切換**——同一個對話裡，工具呼叫
  有時落在雲端沙箱的 repo 副本、有時落在本機真實的
  `/Users/stander/My_project/AlphaVibe`，且切換點不會被明講。**不能假設
  「現在在哪裡執行」跟上一輪相同，也不能假設本機一定是乾淨的**（本機
  可能有其他 session／Cline 留下的獨立進度）。實務作法：
  - 懷疑環境可能換過時，先確認執行位置（`pwd`；本機路徑含
    `/Users/stander/`，雲端沙箱通常是 `/home/user/` 或類似容器路徑）。
  - 任何要動手修改/commit 前，先 `git status`／`git diff --stat`，
    不管前一輪查過與否——查到未預期的未提交異動，先查清楚是什麼
    （`git log --all`、相關文件裡有無記載）再決定去留，不要預設是垃圾
    就地清掉，也不要預設乾淨就直接 merge／覆蓋。
- `docs/spec-intake/*/raw/` 下是原始素材（LINE 對話全文、播客筆記、週報），
  單檔可達數十 KB。**不要在主對話直讀**——派 subagent 摘要，
  只回需要的段落與行號（見全域規則 10-model-dispatch.md）。
- `frontend_mockup.html` 約 31KB。要改它時先用 Grep 定位目標區塊再點讀，
  不要整檔讀入。
- skills 有三份拷貝：`.claude/skills/`（Claude Code 用，**source of truth**）、
  `.cline/skills/`（Cline 用）、`.agents/skills/`（Codex 用）。
  **已知現況（2026-07-06）**：前兩份各 15 個 skill，`.agents/skills/` 只有
  10 個（缺全部 5 個 `speckit-git-*`）——三份本來就不齊，不要假設一致。
  修改 skill 時：改 `.claude/skills/`，再同步到另兩份既有的同名 skill；
  要不要把缺的 skill 補進 `.agents/`，問使用者，不要自行決定。
- `ALPHAVIBE_CONTEXT.md` 是手動貼到 claude.ai Projects 用的摘要，
  會過時；與 repo 內文件衝突時，以 `docs/` 下的文件為準。
- 文件一律繁體中文，表格與 kebab-case slug 沿用既有格式。

## 常用查證點

- **開發路線與進度（接手必讀）**：`docs/spec-intake/alphavibe/roadmap.md`
- 需求基線：`docs/spec-intake/alphavibe/product-spec.md`（Accepted）
- 開放問題：`docs/spec-intake/alphavibe/clarification-log.md`
- 範圍決策：`docs/spec-intake/alphavibe/scope-decision.md`
- PoC 驗證：`python3 -m unittest discover -s poc/kb-mcp/tests`
  （2026-07-08 實測 10/10 綠）；用法見 `poc/kb-mcp/README.md`
- **STND（app/）驗證**：`ALPHAVIBE_DATA_DIR=<獨立測試庫路徑>
  .venv/bin/python3 -m app.tests.test_smoke`——**一定要**明確指定
  `ALPHAVIBE_DATA_DIR` 指向獨立複製出來的測試庫（例如 `poc/data-test/`，
  已 gitignore），絕對不要指向 `poc/data/`（正式庫），見下方 2026-08-22
  教訓紀錄。真正要對正式庫寫入資產種子資料，用
  `poc/kb-mcp/seed_assets_once.py --data-dir poc/data`，一次性、需要
  人手動執行。
- 正式服務常駐設定：`~/Library/LaunchAgents/com.alphavibe.reportserver.plist`
  （現在跑 `uvicorn app.main:app`，不是 `report_server.py`）；舊版 plist
  備份在 `~/Library/LaunchAgents/backup-20260822/`，回滾步驟見同一天
  教訓紀錄。
- 加碼/減碼決策原則：`poc/data/philosophy/framework_evidence_based_position_sizing.md`
  （或呼叫 `get_philosophy`）——**不會自動載入**，討論加碼/減碼前主動查
  （Layer 1「啟動時拼接進 system prompt」的 FR-014 尚未實作，見下方教訓紀錄）

## 教訓紀錄

（依 ~/.claude/rules/40-maintenance.md 的格式在此追加）

- 2026-07-07｜情境：prespec_init.py 用 `Path.write_text(newline=)` 在本機 Python 3.9.6 崩潰（該參數需 ≥3.10）
  ｜教訓：這台機器（含 AI-stock-km-v1 的 .venv）只有 Python 3.9.6，skill 腳本必須保持 3.9 相容
  ｜動作：已用 `open(newline="\n")` 寫法修復 init／sync_index 兩腳本並同步三份拷貝

- 2026-07-10｜情境：tunnel 遠端看 report.html，Ports 面板空白、手動 Forward 回報「already forwarded」
  ｜教訓：devtunnels 轉發登記活在 tunnel 層、跨 session 保留——遇到 already forwarded 直接沿用舊轉發網址（PO 的是 `tqgq0cpn-8080.jpe1.devtunnels.ms`），只需確保 8080 有 server 跑著（2026-07-10 起用 `python3 poc/kb-mcp/report_server.py`，即時渲染；取代舊的 `python3 -m http.server 8080`）；Live Preview 的內部 3000 埠在遠端易壞，不要依賴
  ｜動作：無條文修改，僅記錄工作法

- 2026-07-24｜情境：想把部位管理框架存進 Layer 1 哲學庫、期待之後對話自動套用，查證後發現 `save_philosophy`/`get_philosophy` 只是純檔案讀寫工具，`server.py` 沒有實作 MCP resources/prompts capability，也沒有 initialize 階段自動載入 philosophy/*.md 的程式碼
  ｜教訓：product-spec.md FR-014「啟動時拼接進 system prompt」是設計意圖，不是已實作功能——凡是規格文件講「應該如何」但程式碼沒對應邏輯的，都要當作待開發項目，不能假設已生效
  ｜動作：CLAUDE.md 常用查證點加註「不會自動載入」；roadmap.md 已知限制新增一條；FR-014 本身留待 Phase 2 前評估是否要做（需新增 resources capability 或啟動腳本）

- 2026-07-28｜情境：實作「相對大盤超額跌幅」功能時，開發＋測試＋獨立驗收三階段密集重跑 `market_scan`／`benchmark.load_benchmark()`，當天稍晚就把 FinMind 匿名額度打光（HTTP 402），導致正式 DB 最新一次 run 的 `excess_drawdown_pct` 全部是 None，網頁顯示大盤基準異常橫幅
  ｜教訓：FinMind 匿名額度是全域共用池，不分「開發測試」與「正式排程」——密集開發當天很可能連累當晚 02:00 的正式排程也拿不到資料；日後改動涉及批次 FinMind 呼叫的功能時，測試要有節制（能用獨立 data-dir 不代表不耗額度），或提早申請 token 放 `poc/data/finmind_token.txt`
  ｜動作：無條文修改，僅記錄；`benchmark.py` 已設計成失敗時優雅降級（`benchmark_error` 存檔、頁面顯示異常橫幅、不影響其他欄位），不是程式錯誤

- 2026-07-31｜情境：為了讓手機 Claude App 連接器連上 `/mcp`，把 devtunnel 8080 埠切成 Public 後，反覆遇到「連不上」（dashboard 停止回應、Claude App 呼叫工具失敗）；一度發現 8080 的可見度不知為何變回 Private，手動改回 Public 才恢復
  ｜教訓：(1) 用 `devtunnel show <tunnelId>`／`devtunnel access list <tunnelId> -p 8080` 查證後，可見度（access control）其實是存在 Microsoft 伺服器端的 tunnel/port 屬性，不是 VS Code 本機 session 的暫時狀態，理論上不會因為 VS Code 視窗重啟就自動消失——先前「切VS Code管理=不持久」的猜測沒有證據支持，不要照抄這個結論。(2) 真正的風險點是「維持轉發連線的 host process 依附在 VS Code 存不存活」——VS Code 這台機器上從未裝過官方 `devtunnel` CLI，一直只靠 VS Code 內建 Ports 面板轉發。(3) VS Code 顯示的網址前綴（例：`tqgq0cpn`）是**埠專屬**的網址片段，不是 tunnel ID 本身；真正的 tunnel ID 要用 `devtunnel list` 查（這次查到是 `puzzled-dog-fxqxsq2`），`devtunnel host <tunnelId>` 可以直接接管既有 tunnel、網址完全不變。
  ｜動作：已 `brew install --cask devtunnel`，用 `devtunnel user login -g -d`（device code模式，GitHub帳號standerfly）登入，建立 `~/Library/LaunchAgents/com.alphavibe.devtunnel.plist`（`devtunnel host puzzled-dog-fxqxsq2`，KeepAlive常駐），已脫離 VS Code 獨立運作並驗證外部連線正常；VS Code Ports 面板之後可能顯示8080已斷線，屬預期行為，不用處理。**後續：當天稍晚量測發現此方案仍不足，已改用 ngrok，見下一則**

- 2026-07-31｜情境：改用 devtunnel CLI 常駐後，手機 Claude App 仍反覆回報「工具找不到／整份工具清單抓不到」；量化實測（外部連續10次 `tools/list`，間隔3秒）得到**成功7次、失敗3次（30%失敗率）**，失敗形式是連線完全無回應（HTTP 000）
  ｜教訓：(1) 遇到「時好時壞」的連線問題，**一定要先做量化量測再下判斷**——先前只憑「重試通常會成功」的主觀感受，一直誤判成偶發抖動，實際30%失敗率早已不堪用。(2) 本機服務log乾淨、devtunnel常駐服務log也沒有斷線重連紀錄，卻仍有30%請求打不通 → 證明根因在 Microsoft devtunnels.ms 雲端中繼層，不是本機、也不是 VS Code，換獨立CLI解決不了。(3) 對照組實測：同一個本機服務、同樣測法，ngrok 得到 **10/10 全成功**。(4) 查證發現 CH-EN 專案的 Cloudflare 設定其實**從未真的用過**（`CLOUDFLARE_TUNNEL.md`／`cloudflare/tunnel-config.yml` 全是佔位字串），該專案最新分支早已改用 ngrok——PO 原本以為有 Cloudflare 網域是記憶誤差，Cloudflare Named Tunnel 需要自有網域這道門檻過不了。
  ｜動作：已 `brew install ngrok`（PO 自行 `ngrok config add-authtoken`，憑證不經對話），建立 `~/Library/LaunchAgents/com.alphavibe.ngrok.plist`（`ngrok http 8080 --url=chancefully-erosive-lilian.ngrok-free.dev`，KeepAlive常駐）。**正式對外網址改為 `https://chancefully-erosive-lilian.ngrok-free.dev`**（dashboard 走 `/`、MCP 連接器走 `/mcp/<ALPHAVIBE_MCP_TOKEN>`）。舊的 devtunnel 服務暫時保留當備援（`tqgq0cpn-8080.jpe1.devtunnels.ms` 仍可用，只是有30%失敗率），確認 ngrok 穩定後可 `launchctl bootout gui/$(id -u)/com.alphavibe.devtunnel` 停用。ngrok 免費層每帳號只有一個固定網域額度，這個網域原屬 CH-EN 專案但實測當下閒置（`ERR_NGROK_3200`），未與任何執行中服務衝突

- 2026-08-09｜情境：同一場對話先在雲端 remote session 開發「庫存買賣圖表」（`claude/taiwan-ai-infrastructure-analysis-wehi3w` 分支），完成後才發現執行環境切回本機（VSCode extension），準備把分支merge進`function/alphavibe`時，`git status`發現本機早有一批完整、已測試（590/590）但從未commit的工作（`report.py`+628行等），是2026-08-02本機Cline session產出、跟雲端這批工作在同一批檔案上各自平行發展
  ｜教訓：(1) **同一段對話換執行環境（雲端↔本機）時，不能假設本機是乾淨的**——雲端session看到的`gitStatus`只反映clone當下的雲端副本，本機可能早有未commit的獨立進度，兩者會分岔。切換環境後第一件事永遠是`git status`／`git diff --stat`，不是直接動手merge。(2) 發現本機有未commit異動且內容看起來完整（本例：有意義的commit message風格注釋、通過完整測試）時，**先假設它是有價值的完成品，不要假設是垃圾**——查`git log --all`（Cline checkpoint commit會留下`session=`時間戳線索）、查`~/.cline/data/tasks/`、grep相關文件裡有沒有提過對應的mockup/需求，先弄清楚是什麼再決定去留。(3) 兩份平行開發如果解決的是同一個大目標的不同子問題（本例：雲端做「圖表視覺化」、本機Cline做「清單/詳情頁架構+背景刷新」），比起硬merge衝突，更好的做法是保留架構較完整的一份當地基、把另一份的功能「嫁接」進去，不要兩份都保留造成兩套並行機制。
  ｜動作：已將本機Cline工作單獨commit保存（`552c625`），庫存買賣圖表改嫁接進其個股清單/詳情頁架構（複用其背景刷新機制取得多日股價，而非另開一條即時查詢路由），雲端那個分支的獨立實作已判定不再需要merge。roadmap.md 1e/1f 接手指南已補上這個教訓的具體指引（換環境/隔一段時間接手前先查`git status`）

- 2026-08-12｜情境：某個 Claude Code 對話面板固定顯示「Something went wrong / React error #185」，Reload Window、完全 Cmd+Q 重開 VS Code 都排除不了；一度誤判是當天自動更新到的 extension 2.1.228 版 regression
  ｜教訓：(1) 遇到「重開也沒用」的面板崩潰，先測「開一個全新對話是否也壞」就能秒判是 extension 版本問題還是單一 session 壞掉（本例是後者，新對話正常）——比先查版本號更快定位，別急著降版。(2) 可查 `~/.claude/projects/<workspace-slug>/<sessionId>.jsonl`（sessionId 從 scratchpad 目錄路徑取得，或用錯誤畫面文字 grep 全部 session 檔案反查）看該 session 的原始事件；這次發現壞掉的 session 一開場就是「崩潰畫面文字」被存成第一則 user 訊息，前面只有兩筆 `deferred_tools_delta`／`agent_listing_delta` UI 初始化事件——判斷是還原/重放這批初始化事件時觸發畫面無限重繪，與版本、對話內容量都無關。(3) extension 是編譯過的 bundle，這類渲染 bug 沒有原始碼可以從外部修，該 session 的資料仍完整留在 jsonl（不會遺失），但面板本身救不回來，只能放棄、開新對話繼續。
  ｜動作：無條文修改，僅記錄；曾降版 `anthropic.claude-code` 2.1.228→2.1.227＋關閉 `extensions.autoUpdate` 排除版本假設，確認與版本無關後已把 `extensions.autoUpdate` 還原回預設值（未設定＝開啟），版本維持在降版後的 2.1.227，之後會隨自動更新回到最新版，不用手動處理

- 2026-08-22｜情境：STND（`app/`+`web/`）從規劃到正式上線同一天發生
  三件事：(1) 同一個 Claude Code session ID 因 VSCode `--resume` 機制
  被開成兩個獨立行程（同一份工作目錄 `AI/harness`），各自不知道對方
  存在地平行發展，一個做完整實作＋自我測試，一個完全不知情，直到人工
  要求排查（`ListAgents`＋`SendMessage` 逐一問過 6 個 peer session）才
  查清楚；(2) `kb_store.py` 的 `_seed_asset_defaults()` 原本綁在
  `KBStore.__init__()`，導致任何建立 `KBStore` 的呼叫端都會觸發種子
  寫入——不只新 app 的測試埠會中招，連 `market_scan.py` 這種每天
  02:00 排程、每次都重新讀取磁碟最新 `kb_store.py` 的既有腳本也會，
  正式資料庫的資產表因此**被污染兩次**（各自清空後又被觸發一次）；
  (3) 這兩件事都發生在 `AI/harness` 這個資料夾底下的 session 裡，但
  `harness` 實際上是完全不相關的另一個框架（Cline_DevFlow），不是給
  Claude Code 開對話管理其他專案用的
  ｜教訓：(1) 開發某個 repo 的工作，session 的工作目錄就該是那個
  repo，不要因為「反正跨資料夾讀寫也做得到」就圖方便留在別的專案資料夾
  底下——同名/同工作目錄的多個 session 會導致身份難以分辨，這正是
  (a) 項花大力氣才查清楚的根本原因。(2) 「初始化時自動做有副作用的
  動作（寫資料）」這種設計，只要有任何呼叫端會在非預期情境下建構這個
  物件，副作用就會失控觸發——凡是「這個函式只在特定情境該執行一次」的
  邏輯，都不該掛在建構子，要改成需要明確呼叫的獨立方法/腳本。(3) 正式
  服務切換前的獨立驗收（fresh subagent，不信任開發者自己的測試宣稱）
  抓到了 (2)——這再次證實「驗證不能由產出者自己做」在高風險場景
  （會動到正式資料）不是形式主義，是真的會抓到問題。
  ｜動作：`_seed_asset_defaults()` 移出 `__init__()`、更名為公開方法
  `seed_asset_defaults()`，新增 `poc/kb-mcp/seed_assets_once.py`
  一次性種子腳本；`app/deps.py::_resolve_data_dir()` 改成沒明確設定
  `ALPHAVIBE_DATA_DIR` 就拒絕啟動，且指向正式路徑還要求額外的
  `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 旗標；正式庫兩次污染皆已清空
  （僅限資產 5 張新表，其餘 18 張既有表確認未受影響）；正式服務已於
  當天完成切換（`com.alphavibe.reportserver.plist` 改跑
  `uvicorn app.main:app`），`com.alphavibe.mcphttpgateway`（獨立 8082
  埠）確認退役並改檔名停用；已新增 `app/tests/test_smoke.py`
  （16 項，含 4 個既有路由跟底層函式的輸出比對，非僅「回 200」的淺層
  檢查）。CLAUDE.md 本節與上方「STND 分頁與程式碼位置」同天新增。

- 2026-08-19｜情境：為個股詳情頁新增卡片時，連續四次寫出會誤判的測試斷言——`assertNotIn("conc-fill", page)`、`assertNotIn("完成比例", page)`、`assertIn("verdict--alert", page)`、`page.index("stock-row__delta")` 全都命中了頁面裡的 CSS 定義或說明文字，而不是實際渲染出來的元素
  ｜教訓：`report.py` 把整份 `CSS` 常數**內嵌進每一個頁面**（`<style>%s</style>` % CSS），所以任何拿 class 名稱或 CSS 片語去 grep 頁面字串的斷言，都會先命中樣式定義，位置與存在性判斷全錯。同理，說明文字裡也常包含 UI 標籤字（例：「因此算不出**完成比例**」會讓 `assertNotIn("完成比例")` 失敗）
  ｜動作：測 `report.py` 產出的頁面時，一律斷言**渲染形式**而非裸字串——用 `class="conc-fill`、`<div class="verdict `、`<span class="stock-row__delta` 這種帶 `class="` 前綴或帶標籤的比對；順序比較（assertLess）更要如此，否則比到的是 CSS 區塊的位置
