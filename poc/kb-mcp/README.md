# alphavibe-kb — 三層知識庫 MCP server（Phase 1 PoC）

對應 spec：`docs/spec-intake/alphavibe/product-spec.md`（FR-015~021、Q-021
即時確認制）與 `implementation-options.md` Phase 1。純 Python 標準庫
（本機 Python 3.9，官方 MCP SDK 需 3.10+ 故不引依賴）。

## 用法（Claude Code）

repo 根目錄的 `.mcp.json` 已註冊本 server。在 AlphaVibe 目錄**開新的
Claude Code session**，首次會詢問是否啟用 `alphavibe-kb`——允許後即可：

- 「幫我把剛剛討論的台積電看法存進知識庫」→ AI 呼叫 `save_stance`，
  **工具核准提示＝你的確認**（Q-021）；與既有立場衝突時會先被擋下、
  列出新舊立場請你決定（FR-013/018）
- 「查一下 2330 的基本面」→ `get_fundamentals`（FinMind 即時數據）
- 「6826 和淞的本益比大概多少？」→ `get_emerging_stock_valuation`（興櫃股估值
  粗估，FinMind 的 PER 資料集不含興櫃股；回傳一定附精確度限制說明）
- 「我對哪些股票有立場？」→ `list_stances`
- 「搜尋知識庫裡關於法說會的評論」→ `search_comments`
- 「更新一下我持股的股價」→ `refresh_holdings_prices`（寫入快取，檢視頁
  下次重新整理就會顯示最新市值/持股比例）
- 「幫我篩選這幾檔：3485,6953,6719」→ `screen_stocks`（第一層候選清單篩選，
  依 PEG＜1 且回檔≥40% 框架；手機也可直接開 `/screen` 網頁表單篩選，見下）

## 工具清單

| 工具 | 層 | 說明 |
|------|-----|------|
| save_stance / get_stance / list_stances | L2 | 個股立場（含衝突擋下機制，保留歷史） |
| save_comment / search_comments | L3 | 盤勢評論，FTS5 trigram 全文檢索（**查詢至少 3 個字**） |
| save_comments_batch | L3 | 一次存入多筆評論（欄位同 save_comment）；個別筆缺必填欄位只該筆失敗，不影響其餘筆數存入 |
| save_philosophy / get_philosophy | L1 | 投資哲學模組 md 檔（append/replace）；篩選框架（如 framework_v1）也存這裡 |
| save_snapshot / get_snapshots | 追溯 | 分析結論凍結（當時價/估值/三段式結論/框架版本）＋引用來源；歷次快照供 diff（FR-026~028） |
| save_holdings / get_holdings | 追溯 | 持股快照 {code, shares, avg_cost, date}——不含損益計算（FR-029、Q-035 邊界） |
| refresh_holdings_prices | 快取 | 批次更新目前庫存每檔的股價（近 7 天最新收盤價）與產業別快取，供檢視頁算市值/持股比例、顯示產業別；不帶參數，個別代碼失敗只記入 failed 不中斷整批。檢視頁本身不即時呼叫外部 API，靠這個工具定期寫入快取——建議每個交易日跑一次 |
| save_stock_alias / get_stock_alias | 輔助 | 股票名稱→代碼查證快取，避免同一檔股票重複查證（同名再存＝更新） |
| parse_holdings_report | 輔助 | 解析券商零股庫存表原始文字，擷取每列 code/name/shares（`*`前綴標 is_emerging）；純解析不寫入資料庫，需人工確認後再呼叫 save_holdings 入庫 |
| get_fundamentals | 數據 | FinMind：近期 PER/PBR/殖利率＋近 6 月營收 |
| get_stock_info | 數據 | FinMind：股票基本資料（名稱/產業分類/市場別）；不帶代碼查全部 |
| get_stock_price_history | 數據 | FinMind：個股股價歷史 OHLC＋成交量，預設近 90 天 |
| get_revenue_yoy | 數據 | FinMind：月營收年增率（FinMind 無此欄位，自行以去年同月計算；缺去年同月資料標 null） |
| get_institutional_trading | 數據 | FinMind：三大法人買賣超，預設近 30 天，額外回傳 foreign_net（外資淨買賣超加總） |
| get_emerging_stock_valuation | 數據 | 興櫃股估值粗估（PER/PBR，資料源 TPEx OpenAPI 興櫃三端點＋FinMind 淨值）；FinMind 的 PER 資料集不含興櫃股才需要這個工具。**精確度低於正式上市櫃股**（EPS 僅半年報/年報、非 TTM 基礎；PBR 股數為資本額估算值），詳見回傳的 caveats 欄位 |
| screen_stocks | 篩選 | 第一層選股篩選：對候選代碼清單逐檔計算 PEG（本益成長比）與近 120 天股價回檔幅度，依 `framework_peg_deep_dip_concentration` 框架標註是否符合「PEG<1 且回檔≥40%」；單檔失敗只記入該筆 error，不中斷整批；一次最多 50 檔。純候選清單篩選，不是全市場掃描 |

追溯性用法示例：「分析完了，幫我把這次結論存成快照，附上剛剛查證的來源」；
「這是我的持股截圖，解析後存快照」；「列出 6805 的歷次快照，比對我當時的判斷」。

## 檢視頁

**即時模式（推薦，手機適用）**：
```bash
python3 poc/kb-mcp/report_server.py        # 佔用 8080，取代 http.server
```
每次瀏覽器重新整理都即時讀資料庫重新渲染——不必再手動重跑產出。
沿用既有 devtunnels 轉發網址（開 `/` 或舊路徑 `/poc/data/report.html` 都通）。

**iPhone 加入主畫面（假 App）**：Safari 開 devtunnels 網址（首次登入帳號）
→ 分享 → 「加入主畫面」→ 主畫面出現 AlphaVibe 圖示，點開全螢幕。
電腦入庫新資料後，手機下拉重新整理即見。

**靜態模式（備用）**：`python3 poc/kb-mcp/report.py` 產出
`poc/data/report.html`＋圖示檔，適合離線留存單一時點快照。

內容：立場總覽（紅多綠空）＋分析快照＋持股快照（含市值/持股比例/產業別，
讀 `refresh_holdings_prices` 寫入的快取，未執行過則顯示「未更新價格」）＋
最近 20 則評論＋哲學模組清單＋免責聲明。「理由」欄位超過 40 字自動摺疊，
點擊展開看全文。兩種模式同為 OQ-3（儀表板技術形態）的實驗——1c 前的過渡
工具，刻意不含即時股價（市值用的是定期更新的快取，非即時報價）與距離
目標買價（FR-024 儀表板的事）。

**第一層選股篩選（手機可用）**：即時模式下另有 `/screen` 網頁表單——貼入
股票代碼（逗號或換行分隔）、送出即看到 PEG/回檔幅度篩選結果，符合框架
的列以黃底標出。全程網頁操作，不經過 Claude 對話，解決手機上 Claude Code
chat 面板不穩定的問題。靜態模式不支援（表單需要伺服器處理送出的請求）。

## 資料位置

`poc/data/`：`alphavibe.db`（SQLite，已 gitignore）＋ `philosophy/*.md`。
可用環境變數 `ALPHAVIBE_DATA_DIR` 覆寫。

## FinMind token（可選）

匿名呼叫已實測可用（2026-07-08），額度較低。頻繁使用時到
https://finmindtrade.com 免費註冊，token 放環境變數 `FINMIND_TOKEN`
或 `poc/data/finmind_token.txt`（已 gitignore）。

## 測試

```bash
python3 -m unittest discover -s poc/kb-mcp/tests -v
```

涵蓋：儲存層（立場衝突流程、中文全文檢索、哲學檔案）、FinMind 解析
（mock）、MCP 協定端到端（真實子行程握手＋工具呼叫）、screen_stocks 篩選
邏輯（PEG/回檔計算、單檔失敗不中斷整批、代碼數量上限）、/screen 網頁表單
（GET/POST，mock）。
