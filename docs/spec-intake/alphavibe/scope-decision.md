# Scope Decision: AlphaVibe

This document defines the boundaries of the feature implementation.

## 🎯 Goal

建立可持續維護的個人投資知識庫與工作流（2026-07-07 依 SRC-009 重塑主軸）：
分散的投資資訊（LINE、定錨 email、股癌 FB、網頁、YouTube、市場數據 API）
與 AI 討論後歸檔累積成資料庫；**核心迴圈**為「資訊討論 → 從基本面浮現目標股
→ 估值討論 → 進出決策」，並記錄預計/實際進出場。每日收盤後彙整報告降為
支援能力（覆盤時間 1 小時 → 10 分鐘內的效率目標維持）。引擎為 Claude（思考）
＋ Cline（粗活）、local-first。（SRC-001 §1/§2、SRC-009、Q-028/Q-029/Q-032）

## ✅ In-Scope（v1 MVP）

- 手動貼入三來源資料：LINE 群組／LINE 一對一、定錨 email、股癌 FB（FR-001；Q-004）
- 三層知識庫：Layer 1 哲學庫（md 檔→system prompt）、Layer 2 個股立場（SQLite）、Layer 3 每日評論（FTS5）（Q-013、Q-015）
- 外部數據：FinMind（台股）＋ Alpha Vantage（美股）基礎整合（FR-008；Q-016）
- 內容抓取與解析：user-triggered 單頁爬取（FR-009）、Vision LLM 圖片解析（FR-010；Q-018）
- 每日收盤後結構化報告：市場方向＋明日策略＋個股更新，兩區呈現（FR-004、FR-006；Q-012）
- 自選股 watchlist：新增／刪除／檢視，可收合面板（FR-005；Q-010、Q-011）
- 觸價買入條件提醒（報告內標記）（FR-011）
- 立場衝突標記（FR-013）與前置清洗層（FR-012）
- **AI 對話式輸入（FR-015~018）**：第四種輸入方式＋三層歸檔＋即時確認制
  （Q-019~Q-021）。**Q-024 已於 2026-07-08 由 PO 確認納入 v1**
- **名單驅動＋哲學驅動選股（FR-019、FR-020；Q-030）**：v1 的兩種選股方式，
  只需個股級數據（沿用 FR-008）
- **估值討論（FR-021；Q-029）**：基本面認可後與 AI 討論買賣價格區間，
  結論寫入 Layer 2 既有欄位（entry_condition、valuation_metric）
- **YouTube 來源（FR-023；SRC-009）**：納入資料來源清單，處理方式見 SRC-009 OQ-1
- **儀表板圖像化（FR-024、FR-025；Q-031）**：優先序＝總覽名單頁 >
  資訊流時間軸 > 個股頁 > 交易覆盤頁；含快照 diff 檢視（FR-028；Q-036）
- **追溯性快照包（FR-026~028、FR-030；Q-036，源自 SRC-010）**：分析結論
  凍結（當時價格/估值/來源/框架版本/產出模型）＋來源引用（單檔單次 ≤3
  查詢）＋可版本化篩選框架；已擴充進 MCP PoC
- **持股快照（FR-029；Q-035 部分納入）**：截圖 Vision 解析入庫
  {code, shares, avg_cost, snapshot_date}；**不含損益追蹤介面**
- **交易紀錄（FR-022；Q-029）——後行階段**：預計/實際進出場（價位、時間、理由），
  in scope 但非 v1 首發；與 Q-010 持倉排除的邊界見 SRC-009 OQ-2
- **watchpoints 事件提醒（FR-031；Q-036）——後行階段**：除權息/法說/
  月營收到期提醒，排程形態 Phase 2 定

## ❌ Out-of-Scope

- 持倉追蹤之**損益計算與部位管理**（SRC-001 §4b；Q-010；Q-035 於
  2026-07-09 邊界修正：持股快照 FR-029 納入 in-scope，損益/部位管理仍排除）。
  注意：FR-022「預計/實際進出場紀錄」亦**不屬**此排除範圍（只記價位/時間/理由，
  不算損益；邊界細節見 SRC-009 OQ-2）
- 自動爬取／n8n 自動化（SRC-001 §4b；Q-006）
- LINE `[照片]` 自動解析（v1 記錄佔位符）（Q-007）
- 自動通知推播（SRC-001 §4b）
- 多用戶管理與權限系統（SRC-001 §4b）
- （2026-07-08 更新：原列於此的「全域投資助理」經 Q-027 定案移至 Deferred 節）
- 盤後固定架構引導訪談（Q-019 明確排除）
- web 版 AI 工具歷史對話的自動匯入（Q-023：不撈回，個案手動貼入）

## ⏳ Deferred（未來再考慮）

- n8n 自動化資料收集、持倉管理、自動通知（LINE／email）（SRC-001 §4c）
- Feedback Loop：使用者修正回寫 Layer 1（SRC-001 §4c、§11 Q4）
- 更大規模多用戶支援與自選股權限（SRC-001 §11 Q1）
- **全市場條件篩選選股**（需全市場系統性財務數據管線）（Q-030：v1 先做
  名單驅動＋哲學驅動，此模式等資料庫基礎穩定後再建）
- **全域投資助理**（對話中查詢知識庫既有內容）：v1 不做（Q-019）；
  Q-027 於 2026-07-08 定案列入 Deferred（Phase 2 後的自然延伸）
- **服務化與多供應商架構**（FastAPI＋Agent Router＋自建聊天 UI，
  SRC-010 §2/§3.2）：不採納於現階段（Q-034）；列為 Phase 2 前待評估項，
  屆時以 1b 實測經驗決定。現階段可換性由 MCP 開放標準與開放 SQLite 提供
- Docker 雲端部署與自建前後端產品形態（Q-032 改 local-first；多用戶
  階段再議）（SRC-001 §8 原假設）
- 來源立場衝突的 AI 權重判定邏輯（SRC-001 §11 Q2；v1 以 FR-013 人工判斷）
- 對話歷史保存策略（SRC-002 OQ-1；待 Phase 1 PoC 實測後定）
- LLM 用量邊界（clarification-log Q-025；Phase 2 動工前定案）

## 🔀 實作順序決策（Split / Sequencing）

- **Phase 1 PoC 先行**（2026-07-07 決策，Q-022 與 PO 指示）：product-spec 補完
  後，先在本 repo `poc/` 做 PoC——MCP 三層知識庫＋對話入庫＋FinMind 個股
  數據查詢＋估值討論工作流，驗證 schema、抽取品質與選股估值迴圈（Q-029/Q-030）；
  **Phase 2** 走 speckit 流程做正式產品。詳見 implementation-options.md。
- Spec Kit input 的單一功能切分（拆幾個 speckit-input 包）：待 product-spec
  被接受後於 spec-kit-inputs/ 定案。

## 🔗 跨功能依賴

- AI-stock-km-v1 已封存（Q-022）：其架構模式可參考、資料（raw_documents、
  watchlist）保留為未來遷移來源；v1 範圍不含資料遷移。
