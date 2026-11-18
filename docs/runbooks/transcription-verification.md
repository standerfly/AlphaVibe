# 轉寫驗證操作手冊（定錨表格圖；010 Q-027／Q-028）

> 給 PO 與任何新對話（Claude Code、Cline）共用的操作入口。規則與細節以 `specs/010-investanchors-article-import/quickstart.md` §12～§14 為準；本檔只講「誰、在哪、貼什麼」。

## 一、角色與原則
- **資料錯誤是最嚴重的錯**：轉寫預設 `unverified`（不進搜尋、單篇附警告）；兩個檢核家族（數字＋文字）都通過才是 `cross_checked`（進搜尋）；任何疑慮 → `flagged`（只有 PO 能清除）；`reviewed` 只能由 PO 的 `--mark-reviewed` 設定。
- **誰能做什麼**：讀圖／抽查的 agent 只**寫檔**（`verification.json`），**不得匯入**；匯入由操作者（Mac 上的 Claude Code 對話）預覽後經 PO 同意才 `--apply`。
- **獨立第二讀者的結論只是「疑慮」**：必須附位置與依據，由人／工具重新查證（案例：Cline 曾誤報 6196 備註被截斷，實為它引用長行時自己縮短）。
- **資料外送**：圖片是付費文章。agent 讀圖會把圖送到它設定的模型供應商；**免費模型不得使用**（條款可能用來改進模型）。
- 本機資料夾裡的轉寫與報告**不得貼到公開處**；回報只給數字與位置。

## 二、流程（現行手動版）
1. 操作者（Mac 的 Claude Code 對話）匯出抽查任務：`python3 poc/kb-mcp/investanchors_import.py --data-dir <資料目錄> --export-verification-task`（唯讀；正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`）→ `articles_probe/verify-task-<時間>/`（`manifest.json`、`transcriptions/`、`VERIFY_GUIDE.md`）。
2. **文字家族**：獨立 agent（Claude 讀圖 agent，或 PO 用 VS Code 的 Cline agent）依 `VERIFY_GUIDE.md` 逐張抽查，寫出 `verification.json`（`method=agent-spot-check`）。
3. **數字家族**：`python3 poc/kb-mcp/compare_transcriptions.py --d-results … --c-report … --out … --emit-verification <路徑>`（`method=compare-d-c`，輸出 ok／issues／inconclusive）。
4. 操作者對每個 `verification.json` 先**預覽**：`--import-verification <檔>`（不加 `--apply`），把各狀態張數回報 PO；PO 同意後才 `--apply`。
5. 有疑慮（`flagged`）的圖：PO 對照原圖逐格核對；確認無誤才 `--mark-reviewed <image_id,…> --apply`。

## 三、Prompt 範本（直接複製）

### A. 給 Cline agent（PO 在 VS Code 的 Cline 面板貼）
```
任務：抽查表格圖轉寫。資料夾：<verify-task-資料夾絕對路徑>
1. 先讀該資料夾的 VERIFY_GUIDE.md 與 manifest.json，嚴格照指示做。
2. 逐張圖（manifest 內每一項）：開啟原圖，與 transcriptions/ 內對應轉寫逐列、逐格、逐字比對；特別檢查文字欄位是否被截斷或漏字、每個數字是否正確。
3. 看不清楚就標 uncertain，不要猜；不得修改轉寫；原圖本身的明顯筆誤照抄即可，另標 kind=source-typo。
4. 把結果寫成同資料夾的 verification-cline.json（格式見 VERIFY_GUIDE.md；verifier 填 cline-agent；每筆要帶 manifest 的 sha256 與 transcription_sha256）。
5. issues 只寫「位置＋簡短描述」，不要貼整行或大段原文（我們曾因引用長行被縮短而誤報）。
6. 不要匯入資料庫、不要執行 investanchors_import.py、不要改其他檔案。完成後只回報：每張圖 ok 或 issues 數、檔案路徑。
```

### B. 給 Mac 上的 Claude Code 操作者（新對話貼）
```
請先讀 CLAUDE.md（010 段落）與 docs/runbooks/transcription-verification.md、specs/010-investanchors-article-import/quickstart.md §12～§14。
目標：把正式庫中 unverified 的表格轉寫做驗證。依 runbook「二、流程」：匯出抽查任務 → 派全新的讀圖 agent（Write 工具寫 verification.json，非做轉寫者、非自己）→ 產出數字家族檔（compare_transcriptions.py --emit-verification）→ 全部先預覽（不加 --apply）。
規則：全程唯讀正式資料直到我同意；不 --mark-reviewed；不貼轉寫全文，只回數字與位置；任何異常停下回報。預覽結果回報後，等我說「同意匯入」才 --apply。
```

### C. 給獨立 Claude 讀圖 agent（由操作者派工時使用）
```
你是獨立抽查員（不是做轉寫的人）。讀 <verify-task 資料夾>/VERIFY_GUIDE.md 與 manifest.json，逐張對照原圖與轉寫；文字欄位逐字比對是否截斷或漏字，每個數字都核對；看不清楚標 uncertain 不猜；不得修改轉寫、不得更正原圖筆誤（另標 source-typo）。用 Write 工具把 verification.json 寫到該資料夾（verifier 取 claude-reader-N、method=agent-spot-check、帶 sha256 與 transcription_sha256）。不要匯入資料庫。只回報每張圖 ok 或 issues 數。
```

## 四、未來（尚未開發）：用 Cline 自動抽查的工具
規劃見 `specs/010-investanchors-article-import/cline-integration-prompt.md`（Phase 13；新對話開發中／待開發）。**開發完成並合併後**，本節會補上指令與 prompt。在此之前一律用上面的手動流程。

## 四之二、自動化之後 PO 的角色（Phase 14，Q-029；尚未上線）
流水線（`transcription_pipeline.py`，預設關閉）上線後，新圖由排程呼叫 `claude -p`（訂閱、零花費）自動轉寫並由另一次 `claude -p` 驗證，上面的手動流程變成**備援**。PO 只需：
1. 收到 Telegram「📋 定錨轉寫：N 張圖需核對」或健檢顯示「有疑慮待 PO 核對」時，對 flagged 的圖逐格核對（`--mark-reviewed`）；**其他不抽查**。
2. 健檢出現「連續撞使用量上限」「登入失效」時處理（重新登入或 `claude setup-token`；見 quickstart §15）。
3. 啟用前的 Mac 實測與第一週看實際結果。flagged 仍然只有 PO 能清除。

## 五、注意
- claude.ai 的 AlphaVibe 連接器（搜尋、讀文章）是**唯讀**，沒有 shell，**不能**執行匯出／匯入／驗證工具；這些只能在 Mac 的終端機或 Mac 上的 Claude Code 對話進行。
- 給 PO 在 Mac 貼的指令一律 zsh 相容；鑰匙圈檢查只用存在性，禁止 `dump-keychain`、`-w`、`-g`。
