# AlphaVibe 專案指南（v2，2026-07-08；v2：主軸重塑＋Phase 1 PoC 上線）

## 這個 repo 是什麼

**個人投資知識庫與選股估值工作流**（2026-07-07 主軸重塑：基本面選股→
估值→交易紀錄；引擎＝Claude 聊天思考＋Cline 粗活、local-first，Q-028~032）。
需求基線 product-spec 已 **Accepted**（2026-07-08）。

**code 現況**：唯一可跑的是 `poc/kb-mcp/`（三層知識庫 MCP server，
Phase 1 PoC，零外部依賴）；**正式 production code 尚未開始**（屬 Phase 2，
走 speckit）。`docs/swagger.yaml`、`docs/docs.go` 是模板殘留，不代表有後端；
`frontend_mockup.html` 是純靜態 mockup。

**目前階段：Phase 1b 試用累積**——完整進度與各階段接手指南見
`docs/spec-intake/alphavibe/roadmap.md`（接手任何開發工作前先讀它）。

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
