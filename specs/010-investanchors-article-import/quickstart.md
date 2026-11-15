# Quickstart: 定錨產業筆記文章自動匯入

> 規劃階段文件；實作完成後以實測回填「實測」字樣。順序不可跳：**探查 → 抽查轉寫 → 回補 → 日常**。

## 1. 一次性設定（PO）
1. 鑰匙圈（**`-a` 後是固定名稱，`-w` 後不接任何東西**，互動輸入；009 曾誤填）：
   ```bash
   security add-generic-password -U -s stnd-investanchors -a email -w
   security add-generic-password -U -s stnd-investanchors -a password -w
   security add-generic-password -U -s stnd-investanchors -a vision-api-key -w   # 轉寫模型金鑰
   ```
   驗證只能用：`security find-generic-password -s stnd-investanchors -a email >/dev/null && echo ok`。
   **禁止** `dump-keychain`、`-w`、`-g`。Gmail 沿用 `stnd-statement-import`（009 已存）。
2. `cd poc/kb-mcp/scraper && npm install`（若尚未裝）。
3. 確認 Telegram 設定存在：`~/.config/stnd-gateway/.env`。

## 2. Phase 0 探查（**已於 2026-11-15 完成兩次**，結果見 research.md R0 實測回填；以下為執行規約，重跑需 PO 再次同意）
**執行前**：PO 把電腦上的定錨網站**先登出**，只保留手機一台登入（網站規定同帳號最多兩台，探查瀏覽器算一台；
同時登入第三台可能導致帳號被停用）。探查期間不要在電腦開定錨、不要額外做登入測試。結束後確認手機是否仍在線。
`python3 poc/kb-mcp/article_probe.py --data-dir poc/data --confirm-po-present`；把輸出的結構事實回填
`research.md` R0 的 P1～P7。PO 已決定（2026-11-14／15）：(a) 排程**每晚 23:00 一天一次**、(b) 表格圖送第三方
模型 API **已同意**（Q-016）、(c) 轉寫抽查**抽 10 張、由 PO 本人逐格確認、無百分比門檻**。探查後還需回報 PO：
半年內篇數、每頁篇數與以每天 5 篇回補所需天數（P1／P8；PO 預估約 50～130 篇、11～26 天）、登出機制與名額釋放行為（P2／P2a／P2b）。

## 3. 轉寫抽查與啟用（**部署後**，FR-018；轉寫開關預設關閉）
真實圖片要等部署後回補累積（每天最多 5 篇）。累積 ≥10 張且含長圖後：PO 存金鑰（存了不會啟動轉寫）→ `investanchors_import.py --transcribe-sample 10`（只轉寫抽樣的圖、不寫 DB）→ **PO 本人逐格確認**；PO 認可才採用目前模型，不認可則升級模型再抽 10 張，不設百分比門檻 → 通過後 `--enable-transcription` → `--retranscribe` 補轉積壓。結果寫入本檔「實測」節。

## 4. 回補
排程啟用後，每次至多 5 篇、分多天自動進行，**只補最近半年**（預估約 11～26 天），更早的標記為 `deferred`；
完成後跑 `article_reconcile.py` 與「總覽」清單中半年內的文章逐篇核對（SC-001）。日後要補更早的文章：
`investanchors_import.py --backfill-since <YYYY-MM-DD>`（須 PO 同意放寬）。

## 5. 日常
無新信的日子不登入；新文章 Telegram 通知。從 claude.ai／Claude Code 以 `search_articles`／`get_article` 查詢。
改過 `poc/kb-mcp/*.py` 後，依既有慣例重新部署（`ops/deploy.sh`）並確認 MCP 服務重啟。

## 6. 已知坑（規劃階段已查證）
- **清單每頁頂端有 5 筆置頂項（1 公告＋4 一般文章）在各頁重複**；4 筆置頂文章的清單日期顯示 2021-02-06，但其實是近期
  文章。不得用清單日期判斷新舊或半年截止；以文章 ID 前 13 位（epoch 毫秒＝建立時間）判斷，並有防呆（research R11）。
- **開啟文章會把未讀改成已讀**（FR-009 例外，PO 已接受）；探查時挑未讀文章當對照也會改變 PO 帳號上的已讀狀態。
- **Playwright 預設收到 SIGTERM／SIGINT 會先關瀏覽器**，導致無法登出；scraper 已關閉其內建訊號處理並自行登出再結束。
- 登出在下拉選單內（`a[href=/user/session][data-method=delete]`，不可見）；登入頁有登入／註冊兩個表單，限定在
  第一個可見密碼欄位所屬的 form。
- **通知信中的連結是每位收件人的點擊追蹤轉址（`/c/<token>`），不可跟隨、不可解碼、不取文章 ID**；信只當觸發。PO 表示每篇
  文章都寄信，但實測近 30 天只搜到 12 封（同期文章約 24 篇），原因未驗證——新設計每次登入都抓清單上所有未入庫文章，漏信只延後觸發。
- **探查工具的報告不得含 token**：首次純信箱實跑發現路徑形態只遮數字、字母 token 片段仍進報告，已修（長路徑段一律標 `<token>`）。
- 一篇文章可能只有 1 張很高的長圖（2190×5195），圖片網址不帶 cookie 可下載。
- **FTS5 trigram 搜不到 2 字中文詞**（實測：「環宇」「財測」=0），本功能用 `LIKE`，不要「優化」成 FTS5。
- `setup-plan.sh` 在非 `NNN-` 分支會拒絕：用 `SPECIFY_FEATURE=010-investanchors-article-import`。
- repo 沒有任何登入／storageState／LLM 呼叫先例；這兩塊是全新程式碼，驗收要加倍嚴。
- **PO 待辦（T056，部署後）**：Mac 上 `~/.claude` 的 stock-researcher 白名單**不在 repo**，須由 PO 手動加入 `search_articles`／`get_article` 兩個工具（agent 不修改 `~/.claude`）。
- 工具數守門已於 T029 同步：`test_pnl.py::test_tool_counts`（50／31）、`test_traceability.py::test_tools_list_has_fifty`；台美輸出一致性見 `test_article_connectors_parity.py`。
- 工具數守門有兩處要同步：`test_pnl.py::test_tool_counts` 與 `test_traceability.py::test_tools_list_has_forty_eight`（都 48→50；後者函式名、docstring 也要改）。
- `.gitignore` 沒有祕密檔規則：本設計不產生任何祕密落地檔；探查輸出在已忽略的 `poc/data/` 下。
- 站方「兩台裝置」上限：排程的瀏覽器算一台，PO 手機＋電腦已兩台時，**絕不可與 PO 同時上線**——時段須先問 PO。
- 通知信連結若是追蹤轉址，不要跟隨（見 research P4）。
