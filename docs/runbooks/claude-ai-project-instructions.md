# claude.ai 專案設定（投資：台股＋美股）

> 建立於 2026-10-28，2026-10-29 改版：專案指示本文改放在 repo 根目錄的
> `ALPHAVIBE_CONTEXT.md`（單一來源），本文件只說明設定步驟與規則的來由，
> 不再另存一份指示內容，避免兩份各自過時。

## 分工

- **claude.ai（AlphaVibe 專案）**：即時的匯入、詢問庫存與 STND 內容、一次性分析。
- **STND 網頁**：常用畫面與排程結果（每日市場掃描、模組D今日重點）。
- 兩邊讀寫同一份資料庫：在 claude.ai 匯入的資料，網頁打開就看得到。

## 設定步驟

1. **連接器**（claude.ai 設定 → 連接器 → 新增自訂連接器，驗證選「無需登入」）：
   - `AlphaVibe`（台股）：`https://chancefully-erosive-lilian.ngrok-free.dev/mcp/<ALPHAVIBE_MCP_TOKEN>`
   - `AlphaVibe US`（美股）：`https://chancefully-erosive-lilian.ngrok-free.dev/mcp/us/<ALPHAVIBE_MCP_TOKEN>`
   - 密鑰在網址裡，網址等同密碼：截圖、分享前要遮掉。密鑰值見 Mac 上
     `~/Library/LaunchAgents/com.alphavibe.reportserver.plist` 的 `ALPHAVIBE_MCP_TOKEN`。
2. **專案指示**：把 `ALPHAVIBE_CONTEXT.md` 整份（取代舊內容）貼進 AlphaVibe 專案的「專案指示」。
3. **驗證**：在專案裡開**新對話**（指示只在新對話開始時套用），問「STND 今天有什麼重點？」，
   回答上方應出現 `get_today_highlights` 的工具呼叫紀錄；問「我的美股庫存？」應呼叫 `get_us_holdings`。

## 規則的來由（改指示前先讀）

| 規則 | 為什麼 |
|---|---|
| 明寫「STND＝AlphaVibe，一律用連接器查」 | 2026-10-29 實測：沒寫時 claude.ai 不知道 STND 是什麼，只讀記憶、不呼叫工具 |
| 寫入前只准呼叫 get_ 工具 | 產品規則「未經確認不寫入」；claude.ai 連接器沒有逐工具的寫入保護，只能靠指示 |
| 庫存截圖要完整、先比對消失股票 | `get_holdings` 只讀最新一次快照，部分截圖會讓其他持股從庫存消失；網頁匯入有 avg_cost 沿用與差異比對，對話路徑沒有 |
| 單筆交易要提醒庫存未同步 | `save_trade_ledger_entry` 不呼叫 `holdings_sync`；CSV／交易明細兩個 parse 工具才會同步 |
| 美股寫入前先查帳 | `parse_and_save_us_trade` 依 `specs/003-us-stocks` 定案不去重；經 ngrok 的公開連線重試時可能重複記帳 |
| 今日重點用 `get_today_highlights`，不用 `run_module_d_check` | 後者會重算並寫入、耗 FinMind 額度 |
| 台美不混用、不加總 | 台美完全獨立是產品硬性要求，且幣別不同 |
