# AlphaVibe — 專案對話上下文

> 此文件用於在 claude.ai Projects（含手機 Claude App 透過 Custom Connector
> 存取）上維持跨 session 的對話連續性。內容會過時，請對照
> `docs/spec-intake/alphavibe/roadmap.md` 確認現況；兩者衝突時以 roadmap.md
> 為準。
> 最後更新：2026-07-31

---

## 專案身份

- **專案名稱：** AlphaVibe
- **PO / TPM：** Stander（台股投資者，非工程師）
- **目前階段：** Phase 1b 試用累積（PoC 已上線實際使用中，正式 production
  code 尚未開始，屬 Phase 2）
- **需求基線：** `docs/spec-intake/alphavibe/product-spec.md`（Accepted）

---

## 核心目標

AlphaVibe 是 Stander 的**個人投資知識庫與選股估值工作流**，圍繞「策略引擎＋
每日PDCA」重新設計，核心是七個功能模組（A-G）：

- **A** 資料輸入與知識庫（自選股、留言、券商資料貼入解析）
- **B** 策略定義（`frameworks.py` 裡的選股策略，含進場條件與失效條件）
- **C** 全市場批次篩選（TWSE/TPEx官方API，找符合策略的候選標的）
- **D** 策略檢視引擎（通用檢視層／策略專屬層／老芋頭訊號比對／部位控制
  建議——這是核心功能，PO特別重視）
- **E** 自選股與觀察名單
- **F** 儀表板呈現（手機/電腦皆可用的網頁報表）
- **G** 策略績效回顧（Deferred，待累積更多樣本資料）

老芋頭是一個訊號來源（真實存在的投資達人/社群訊號），不是系統使用者，
Module D 會比對他的進出動向，但只做事實陳述、不做主觀評論。

---

## 目前的技術現況（實際可跑，不是規劃）

- 唯一可跑的程式碼在 `poc/kb-mcp/`（Python 3.9.6、零外部依賴的 MCP
  server），透過 macOS launchd 常駐服務對外提供：
  - 網頁 dashboard（貼交易明細/庫存表、記交易、看今日重點與策略檢視）
  - MCP 工具（本 Project 連接的 Custom Connector 用的就是這組工具，
    詳見下方「可用工具」）
- 資料庫是本機 SQLite，內容包含：自選股、老芋頭交易紀錄、PO 自己的交易
  流水表、庫存快照、Module D 每次檢視結果等。
- 對外連線走 ngrok 固定網址常駐服務（devtunnel 曾用過但實測30%失敗率，
  已於2026-07-31換掉，細節見 repo 內 `CLAUDE.md` 教訓紀錄）。

---

## 對話時請遵守的原則

1. **先查再答**：涉及 PO 的實際持股、交易紀錄、策略設定時，用連接器的
   工具實際查詢（`get_holdings`、`get_trade_ledger`、`list_stances` 等），
   不要憑對話記憶或猜測回答。
2. **加碼/減碼建議前，先查哲學庫**：呼叫 `get_philosophy` 讀部位管理框架
   （`framework_evidence_based_position_sizing`），不要直接給主觀建議。
3. **手機使用情境，回覆要精簡**：PO 常在手機上快速查看，不要長篇大論，
   結論先講，細節視需要展開。
4. **PER/PBR等估值數字如果看起來異常（例如剛好是0），要有警覺**：FinMind
   對EPS為負的時期，PER欄位會回傳0.0當sentinel，不是真的估值是0——
   2026-07-31已修正`get_fundamentals`會自動標記這種情況並附註解釋，但
   遇到其他可疑數字時仍要保持懷疑、不要直接照單全出。
5. **不確定就明講**：查不到資料、工具回傳錯誤、或PO問的東西超出目前系統
   範圍，直接說清楚，不要編造數字或过度自信。

---

## 可用工具（MCP Connector，39個，重點分類）

- **查詢類**：`get_holdings`／`get_trade_ledger`／`get_laoyutou_trades`／
  `get_stance`／`list_stances`／`get_fundamentals`／`get_revenue_yoy`／
  `get_market_scan`／`get_philosophy` 等
- **檢視類（Module D 核心）**：`check_general_review`／
  `check_strategy_review`／`check_laoyutou_signal`／`check_position_control`／
  `run_module_d_check`
- **寫入類**：`save_stance`／`save_comment`／`save_holdings`／
  `parse_and_save_laoyutou_trades`／`parse_and_save_trade_ledger`／
  `parse_holdings_report` 等

工具清單會隨開發持續增加，不確定某個功能有沒有對應工具時，直接嘗試
`tool_search` 搜尋「AlphaVibe」關鍵字確認，不要假設沒有。

---

## 關鍵決策紀錄（重大轉折，供快速回顧）

| 日期 | 主題 | 決策內容 |
|---|---|---|
| 2026-07-07 | 主軸重塑 | 從「投資資訊儀表板」重新聚焦成「策略引擎＋每日PDCA」，Q-028~032 |
| 2026-07-08 | 需求基線 Accepted | product-spec.md 首版通過 |
| 2026-07-25~27 | 全面需求重構 | 健檢發現文件與實際使用嚴重脫節，重寫成 A-G 七模組架構 |
| 2026-07-30 | UI/UX優化＋快速輸入 | dark mode、手機UI重做、三個文字貼上解析工具 |
| 2026-07-31 | 手機對話能力上線 | 建立本 Project 使用的 MCP Custom Connector，脫離純表單操作 |
