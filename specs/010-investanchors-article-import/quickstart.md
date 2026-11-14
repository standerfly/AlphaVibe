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

## 2. Phase 0 探查（PO 在場，一次）
`python3 poc/kb-mcp/article_probe.py --data-dir poc/data --confirm-po-present`；把輸出的結構事實回填
`research.md` R0 的 P1～P7，並由 PO 決定：(a) 排程時段（避開常用時段）、(b) 表格圖可送第三方模型 API、
(c) 轉寫準確度門檻。**這三項定案前不進入實作的排程與轉寫部分。**

## 3. 轉寫抽查（上線前，FR-018）
抽 ≥20 張真實表格圖 → 轉寫 → PO 逐格比對 → 達門檻才採用；未達升級模型再測。結果寫入本檔「實測」節。

## 4. 回補
排程啟用後，每次至多 5 篇、分多天自動進行；完成後跑 `article_reconcile.py` 與「總覽」逐篇核對（SC-001）。

## 5. 日常
無新信的日子不登入；新文章 Telegram 通知。從 claude.ai／Claude Code 以 `search_articles`／`get_article` 查詢。
改過 `poc/kb-mcp/*.py` 後，依既有慣例重新部署（`ops/deploy.sh`）並確認 MCP 服務重啟。

## 6. 已知坑（規劃階段已查證）
- **FTS5 trigram 搜不到 2 字中文詞**（實測：「環宇」「財測」=0），本功能用 `LIKE`，不要「優化」成 FTS5。
- `setup-plan.sh` 在非 `NNN-` 分支會拒絕：用 `SPECIFY_FEATURE=010-investanchors-article-import`。
- repo 沒有任何登入／storageState／LLM 呼叫先例；這兩塊是全新程式碼，驗收要加倍嚴。
- CLAUDE.md 說工具數守門在 `test_pnl.py`／`test_traceability.py`；實際只有 `test_pnl.py`。
- `.gitignore` 沒有祕密檔規則：本設計不產生任何祕密落地檔；探查輸出在已忽略的 `poc/data/` 下。
- 站方「兩台裝置」上限：排程的瀏覽器算一台，PO 手機＋電腦已兩台時，**絕不可與 PO 同時上線**——時段須先問 PO。
- 通知信連結若是追蹤轉址，不要跟隨（見 research P4）。
