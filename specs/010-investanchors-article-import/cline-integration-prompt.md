# 開發任務 prompt：Mac 上用 Cline 當「獨立第二讀者」自動抽查轉寫（010 後續，Phase 13）

> 用法：PO 在 Mac 的 VS Code 開新對話，把「## Prompt 本文」整段貼進去。本檔放在 `specs/010-investanchors-article-import/`，
> 開發者先 `git fetch origin function/alphavibe` 取得最新版再讀本檔所引用的文件。

## Prompt 本文

你是 AlphaVibe 專案的資深開發者。**先讀**：`CLAUDE.md`（含 010 段落與教訓紀錄）、`specs/010-investanchors-article-import/quickstart.md`（§12 方案 D、§13 比對、§14 驗證等級與抽查流程）、`contracts/cli.md`、`data-model.md`、`clarification-log` 的 Q-027／Q-028、`poc/kb-mcp/article_verification.py`、`compare_transcriptions.py`、`investanchors_import.py`。PO 是 PO/TPM，不寫程式；PO 的終端機是 zsh。

### Purpose（目的）
讓 Mac 上的 **Cline**（VS Code 擴充 `saoudrizwan.claude-dev` 與/或 Cline CLI）能當「獨立第二讀者」，**半自動地**對表格圖的轉寫做文字抽查（逐字比對是否截斷／漏字、核對每個數字），產出符合規格的 `verification.json`，再交給既有的 `--import-verification` 預覽與匯入。原則：**資料錯誤是最嚴重的錯**，寧可保守、寧可人工，不要為了自動化犧牲正確性。

### Target（環境與事實；以下已查證，請不要重做研究，但開工前用唯讀指令再確認一次）
- 機器：macOS、Apple Silicon（arm64）Mac mini，24GB RAM；`/usr/bin/python3` 3.9.6（專案固定，**只用標準庫、3.9 相容**）；Node v26.0.0、npm 11.12.1。
- Cline 擴充 `saoudrizwan.claude-dev@4.1.26` 已安裝可用（PO 已手動用它的 agent 抽查過 image_id=8，結果有一次誤報，見下）。
- **Cline CLI 3.0.60（`/opt/homebrew/bin/cline`）目前壞掉**：`--help`／`--version` 正常，但啟動本體失敗（`spawnSync …/cline/bin/.cline Unknown system error -88`），因為 `/opt/homebrew/lib/node_modules/cline/bin/.cline` 原生執行檔**不存在**（npm 全域安裝時下載原生檔失敗或被清掉；不是 CPU 架構問題，Rosetta 在跑）。修復＝重裝 cline（會連網下載）→ **需要 PO 同意才能做**。
- 官方文件（2026-11-18 查證）：CLI 為 `npm i -g cline`；有非互動模式（`--json`、管線輸入；輸出 NDJSON，最終文字在 `run_result` 行）、`--auto-approve`（**預設 true**）、`-t/--timeout`、`-c/--cwd`、`-m` 模型、`-P` 供應商、`--config`／`--data-dir`（隔離設定與狀態）、`--retries`。官方文件說提示裡可用 `@路徑` 附圖，**本機 `--help` 沒列、是否可用未驗證**；**未查到**：結束碼定義、max-turns、「限制只能讀寫指定資料夾」的機制、是否共用 VS Code 擴充的設定與登入、從命令列觸發擴充內 agent 的方式、程式化 SDK/API。
- 資料外送：Cline 讀圖會把**付費文章的圖片**送到它所設定的模型供應商。官方原文：「Free model usage may be used to help improve model performance and quality.」→ **免費模型不得用於這批圖**；要用就用付費／自備金鑰且確認供應商條款不拿資料訓練。telemetry 預設開啟，關閉方式為 `~/.cline/data/settings/global-settings.json` 的 `telemetryOptOut: true`（改設定檔前須 PO 同意）。**絕不讀取、列印或提交** `~/.cline/data/secrets.json`、金鑰、token、cookie；金鑰存在性檢查只用 `[ -n "$VAR" ]` 或 `security find-generic-password … >/dev/null && echo ok`，**禁止** `dump-keychain`、`-w`、`-g`。
- 既有工具（已合併、已驗收，**不要重寫**）：`investanchors_import.py --export-verification-task`（輸出 `verify-task-<時間>/`：`manifest.json`〔含 `sha256`、`transcription_sha256`、原圖路徑〕、待查轉寫逐列加行號、`VERIFY_GUIDE.md`）、`--import-verification <verification.json> [--apply]`、`--mark-reviewed`、`compare_transcriptions.py --emit-verification`。驗證等級規則：`cross_checked` 須「數字家族（compare-d-c／arithmetic／body-crosscheck）＋文字家族（agent-spot-check）」都 ok；任一 issues → `flagged`，**flagged 只有 PO 能清除**；unverified／flagged 不進搜尋。
- 已知的獨立讀者誤報案例（請納入設計）：PO 的 Cline agent 曾回報「6196 備註被截成『廠務』」，經 Mac 端以程式與原圖查證，D 轉寫其實完整（第 81 行 97 字元、備註 29 字）；Cline 的誤報原因不明。**教訓：第二讀者的結論只是「疑慮」，必須附位置與依據，由人／工具重新查證，不可直接當事實。**

### Components（要做的模組）
1. **環境檢查與修復計畫**（`poc/kb-mcp/cline_env_check.py` 或併入 runner 的 `--check`）：唯讀偵測 node／cline 版本、原生執行檔是否存在、`cline --help` 旗標、擴充是否安裝；輸出「可用／不可用＋原因＋建議修復步驟」。**不自動重裝**；需要重裝時只印指令並停下，等 PO 同意。
2. **抽查執行器 `cline_verify_runner.py`**：輸入一個 `verify-task-*` 資料夾；
   - 在暫存工作夾（例如 `<資料夾>/run-<時間>/`）**複製**「只需要的檔案」（待查轉寫檔、對應原圖、VERIFY_GUIDE.md 與 manifest 的唯讀副本），用 `--cwd` 指到該暫存夾，讓 Cline 看不到其他專案檔案（因為官方沒有細緻路徑限制）；
   - 以 `--json`、明確的 `-t/--timeout`、`--retries`、`--data-dir`（獨立設定夾，避免動到 PO 的擴充設定）、`-P`／`-m`（由 PO 提供，**預設不指定、沒指定就拒絕執行**，避免誤用免費模型）呼叫 Cline；一次一張圖（失敗只影響一張）；
   - 解析 NDJSON `run_result`，取出 agent 寫的 `verification.json`；**用既有 `article_verification.validate_verification` 做預覽驗證**（schema、sha256、transcription_sha256、控制／bidi／疑似金鑰字元）；不合格整批丟棄並保留原始輸出供人看；
   - **絕不自動 `--apply`**：只產出可匯入的 `verification.json` 與「預覽結果」，由 PO（或主流程）決定匯入。
3. **保守的結果處理**：agent 回報 `issues` → 工具再做一次「重新查證輔助」（例如把該列該欄的轉寫文字與資料庫現況比對、檢查是否為行寬截斷／切欄誤判），在報告中標注「疑似誤報」或「需人工看原圖」，**但仍保留該 issues**（寧可 flagged 由 PO 仲裁）。
4. **VS Code 擴充備援流程文件**：CLI 修不好或 PO 不想修時，寫清楚 PO 在 VS Code 的 Cline 擴充裡手動抽查的步驟（把 `verify-task-*` 資料夾與 `VERIFY_GUIDE.md` 給 agent、輸出 `verification.json` 的位置與命名、如何預覽匯入），與 CLI 流程共用同一份 VERIFY_GUIDE。
5. **文件與規格**：`quickstart.md` 新增 §15、`contracts/cli.md`、`tasks.md`（Phase 13）、`clarification-log`（新決策條目，含 PO 的模型／外送決定）；若涉及新旗標或新檔案格式請遵守專案「規格先行」流程（ADR-0027 pre-spec → Spec Kit；本件屬 010 的延伸，先與 PO 確認範圍再動手）。

### Function（行為細節與限制）
- **資料外送是 PO 的決定**：每次真實呼叫前必須印出警示（會把哪些圖送到哪個供應商／模型），並要求 PO 明確確認（旗標 `--i-understand-data-egress` 或互動輸入 yes）；沒有確認不得呼叫。預設 dry-run（只列出將處理的圖與指令，不啟動 Cline）。
- **成本與頻率上限**：單次最多 N 張（預設 3）、單張逾時、總逾時；每日上限；超過就拒絕。記錄張數與耗時（不記錄圖內容、不記錄金鑰、**不含文章標題**）。
- **安全**：不連網（除了 Cline 自己對供應商的請求；你的程式碼本身不得開 socket）；不讀鑰匙圈（除非 PO 明確同意某個金鑰項目）；日誌與報告不含帳密、token、文章標題與全文；資料目錄防呆（沿用 `article_data_guard`，正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，旗標檢查最先）。
- **相容與正確性**：Python 3.9 相容、僅標準庫；測試用**假的 cline 可執行檔**（寫一個會輸出預設 NDJSON 的 stub）覆蓋：正常、逾時、輸出壞格式、agent 試圖寫到暫存夾外、輸出含疑似金鑰、issues 的處理、旗標互斥、無模型旗標拒絕、無確認拒絕、dry-run 零副作用。
- **不要做**：不修改 `~/.cline`、不安裝／重裝任何東西、不連網、不呼叫真實 Cline 處理真實資料（**第一次真實試跑只用 1 張合成圖，且須 PO 在對話中親自同意**）、不部署、不改 AlphaVibe-prod、不改既有守衛與測試。
- **分支與流程**：分支 `function/cline-verify`（kebab-case，基底 `function/alphavibe`）；先 `git status`／`git log` 確認環境乾淨再動手；完成後：完整回歸（基準比對）→ 推送 → 全新 agent 獨立驗收（只給驗收條件，實跑測試附證據）→ PO 同意再合併。Mac 上跑測試前先查 `模組.__cached__`（CLAUDE.md 2026-09-03 教訓）。

### 驗收條件（至少）
1. `--check` 在目前這台機器（CLI 壞掉）能正確回報「不可用＋原因（原生檔缺失）」且不修改任何東西。
2. 假 cline 的整條流程（匯出資料夾 → runner → verification.json → 預覽匯入）通過，且所有失敗路徑乾淨結束、不留部分輸出、不外洩。
3. 沒有模型旗標、沒有外送確認、超過張數上限時一律拒絕；dry-run 零副作用。
4. 預覽驗證使用既有 `validate_verification`（不得另寫一套較鬆的規則）；`transcription_sha256` 不符時拒絕。
5. 文件寫明：免費模型的資料使用條款風險、CLI 目前壞掉與修復需 PO 同意、擴充備援流程、第二讀者誤報的處理原則。
6. 完整套件失敗清單與基準逐項相同；新測試全綠。
