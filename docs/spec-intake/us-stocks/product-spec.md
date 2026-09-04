# Product Spec: 美股獨立投資系統

**Status:** Accepted
**Feature Slug:** us-stocks
**Function Branch:** function/us-stocks
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** 2026-09-04
**Acceptance Evidence:** PO Stander 於 2026-09-04 Claude Code session 中，在
回覆 Q-001 第二輪決定（免費API多來源）並確認 §Integration Note 等連動更新後，
針對「還有其他要補充或修正的地方嗎？還是可以驗收了？」的直接提問回覆
「可以驗收了」，完成驗收。全部4項blocking clarification（Q-001~Q-004，見
clarification-log.md）已回答並反映進本文件。
**Last Updated:** 2026-09-04

## Problem And Goal

使用者（Stander）除了既有的台股投資外，也投資美股，但目前沒有任何系統支援——
研究討論散落在對話（如 ChatGPT 分享連結、與 Claude 的即時討論）裡，交易紀錄
只存在券商 App 截圖，沒有集中的地方可以回顧持股現況、追蹤投資立場是否仍然
成立、或察覺關注中的個股是否已經觸及該重新檢視的門檻。

目標是在 STND 建立一個獨立的美股投資系統，複製既有台股「投資」分頁證明有效
的核心體驗（股價走勢＋進出場點位、立場記錄、條件監控），但資料與判斷邏輯
完全獨立於台股，因為兩者的投資方法可能不同，混用容易造成誤判與資料污染。

## Business Context And Priority

- Priority: 使用者主動提出、經過多輪討論定案，視為 STND 下一個要做的分頁功能
- Timing: 尚未指定明確時程；本 pre-spec 完成、blocking clarification（Q-001~Q-004）
  獲得回答後即可進入 speckit 階段
- Business value: 讓使用者的美股投資决策（研究→立場→交易→監控）有系統性紀錄，
  取代目前分散在對話與截圖裡、難以回顧與追蹤的現況；呼應使用者一貫想建立的
  「檢視→討論→對策→交易→再檢視」投資循環（見 memory: holdings-review-cycle-goal）

## Actors

- Stander：STND 的唯一使用者，同時是本功能的 PO/TPM/操作者。沒有其他角色。

## MVP Scope

### In Scope

- STND 導覽新增獨立「美股」分頁
- 美股 landing 頁：追蹤清單，顯示現價/漲跌/立場/觸發狀態
- 個股詳情頁：股價走勢圖＋買賣點位標記（視覺比照台股 `StockComboChart` 風格，
  資料源獨立）
- 投資立場／研究筆記功能：討論結果結構化存入，完整內容可在詳情頁原生查看
- 關注條件清單：設定門檻、比對最新資料、標示觸發狀態
- 交易紀錄匯入：截圖→辨識→人工核對→寫入（不論辨識完整度，一律經人工核對才落庫）
- 視覺規範：紅漲綠跌／紅買綠賣沿用台股既有慣例
- 報價/基本面資料改採免費API多來源取得（主要：FMP；備援：候選Alpha Vantage或
  yfinance，待speckit-plan定案），使用者與agent互動時按需查詢，非背景排程
  輪詢（Q-001第二輪決定，見§Integration Note）
- 關注條件觸發時透過既有 Telegram 閘道（`function/stnd-gateway-web`）推播通知（Q-002）

完整依據見 `scope-decision.md`。

### Out Of Scope

- 交易紀錄 CSV／報表匯入（僅截圖）
- 付費報價API方案（MVP僅用FMP/備援來源的免費層）
- 排程自動輪詢報價/關注條件（免費API額度不足以支撐，仍是按需查詢）
- 美股與台股資料的任何跨市場彙總計算
- 多使用者/多角色權限設計
- 截圖原始檔的永久保存（Q-004 已定案不保留）

### Deferred

- 美股獨立 KB 的具體技術實作方案（待 speckit-plan，Q-005）
- 研究筆記渲染的技術做法（待 speckit-plan，Q-006）
- 若未來手動/agent互動模式不敷使用，是否導入自動化報價 API（需使用者重新提出才評估，非待辦）

## Functional Requirements

- FR-01 STND 導覽新增獨立的「美股」分頁，不併入既有「投資」（台股）或「資產」分頁
- FR-02 交易紀錄匯入：使用者上傳券商 App/網頁截圖 → 系統辨識 → 呈現核對畫面 →
  使用者確認（可修正欄位）→ 寫入美股獨立交易紀錄表
- FR-03 個股詳情頁提供股價走勢圖，疊加買賣點位標記；視覺呈現比照台股既有
  `StockComboChart` 元件風格（配色/圖例/線稿），資料來源與資料表完全獨立於台股。
  股價資料在使用者與 agent 互動時，由 agent 呼叫免費報價API（主要來源FMP）
  按需取得，可拿到 FMP 免費層涵蓋範圍內的連續日K歷史股價（僅EOD收盤資料，
  非即時報價），非使用者手動輸入的離散快照（見 §Integration Note，Q-001）
- FR-04 研究筆記／投資立場：使用者與 Claude 討論個股後，可將討論結果存入系統，
  包含結構化立場（買/賣/觀望＋情境區間：Bear/Base/Bull 價格帶＋論點摘要）與
  完整研究筆記內容
- FR-05 個股詳情頁可查看完整研究筆記內容，在 STND 內以既有卡片/字體/配色系統
  原生渲染；渲染時不得因版面密度考量而砍減章節、引用來源或論述完整度
- FR-06 關注條件清單：可為每檔股票設定監控門檻（例：股價、毛利率、NRR等指標），
  在使用者與 agent 互動時由 agent 呼叫報價/基本面 API 取得最新資料並比對是否
  碰觸條件（按需觸發，非背景排程——免費API額度不足以支撐排程輪詢，見
  §Integration Note），碰觸時在美股分頁與個股詳情頁標示警示狀態（未觸發/
  已觸發/資料不足 三態）；NRR等SaaS特有指標多半查不到，仍需使用者/agent
  互動時手動補充，非API可自動取得
- FR-09 關注條件碰觸門檻時，透過既有 Telegram 閘道（`function/stnd-gateway-web`
  「管家」分頁）主動推播通知使用者
- FR-07 美股分頁 landing 呈現追蹤中清單，每檔顯示現價/漲跌/立場/觸發狀態一覽，
  無需逐檔點開即可判斷是否需要關注
- FR-08 漲跌與買賣點位視覺色彩沿用台股既有慣例（紅=漲/買進，綠=跌/賣出），
  全站一致

## Workflow

本功能的核心是三個循環，對應「檢視→討論→對策→交易→再檢視」的投資管理目標：

**循環 A（研究到立場）**：使用者貼分析或與 Claude 討論想法 → Claude 消化並
獨立查證 → 落成研究筆記 → 萃取成結構化立場（FR-04）→ 存入美股獨立資料庫

**循環 B（交易紀錄）**：使用者截圖交易 → 系統辨識 → 人工核對 → 結構化寫入
（FR-02）→ 股價圖疊加買賣點位（FR-03）

**循環 C（持續監控）**：使用者與 agent 互動時，agent 呼叫免費報價API（主要
FMP，必要時切換備援來源）按需取得最新資料（非背景排程，見 §Integration Note）
→ 比對關注清單的觸發條件（FR-06）→ 碰觸條件時標記警示（狀態：未觸發 ok →
已觸發 alert，或資料不足 pending）→ 透過既有 Telegram 閘道推播通知使用者
（FR-09，Q-002）→ 使用者看到警示 → 回到循環 A 重新討論是否調整立場/交易

## Data Model Note

美股功能新增以下概念實體，**均與既有台股資料表完全獨立**（不共用
`trade_ledger`／`stance`等既有表，理由見 `scope-decision.md` Decision Rationale）：

- **美股交易紀錄**：日期、代號、買賣方向、股數、價格、金額（USD）、截圖來源
  參照（原始檔保留策略待 Q-004）
- **美股立場**：代號、建立日期、論點摘要、情境價格帶（Bear/Base/Bull）、
  來源研究筆記連結、狀態（進行中/已結束）
- **關注條件**：代號、指標類型（價格/估值/基本面等）、比較條件、門檻值、
  狀態（未觸發/已觸發/資料不足）
- **美股報價歷史**：代號、日期、收盤價；資料來源為 agent 於使用者互動時呼叫
  免費報價API（主要FMP）按需取得並存入（Q-001第二輪決定），非背景排程持續
  寫入；只存「查過的」日期範圍，不代表連續無缺口的完整歷史

**截圖保留規則（Q-004）**：交易截圖僅在「上傳→辨識→核對」流程中暫存，使用者
確認匯入或取消核對後立即刪除暫存檔，不寫入任何永久儲存位置（不進資料庫、
不進 repo、不進雲端）；永久保存的只有核對後的結構化交易資料。

具體 schema、欄位型別、索引設計、暫存目錄的技術實作留待 speckit-plan 階段
處理，此處僅記錄產品層的「實體要有哪些、彼此獨立、截圖不保留」的約束。

## Integration Note（美股報價資料源）

**決策依據**：Q-001 第二輪查證（general-purpose agent 研究，2026-09-04）比較
FMP、Polygon.io（現名Massive）、Alpha Vantage 三個服務的免費方案：

| 服務 | 免費額度 | 股價歷史 | 基本面數據 | 結論 |
|---|---|---|---|---|
| **FMP**（主要來源） | 250次/日，免信用卡 | 有EOD日K | 有（損益/資產負債/現金流量表） | 三者中最適合，唯一股價+基本面都在免費層 |
| Alpha Vantage（備援候選） | 25次/日 | 免費層僅約近5個月（compact模式） | 端點有列但免費/付費界線不明確 | 額度太緊，不適合當主力，可當備援 |
| Polygon.io/Massive | 5次/分鐘 | 有，僅2年 | **無**（需付費$29/月起） | 免費層無基本面，出局 |
| yfinance（備援候選） | 無官方限制（社群慣例自律） | 涵蓋較廣 | 有 | 非官方、ToS灰色地帶，穩定性無保證 |

**產品層決定**：MVP 採用 **FMP 為主要資料源**，另加至少一個備援來源（
Alpha Vantage 或 yfinance，最終選定與切換邏輯留待 speckit-plan）。

**失敗/降級行為**：主要來源額度用盡或請求失敗時，嘗試備援來源；若備援也
失敗，關注條件顯示「資料不足」（pending，見 FR-06 三態設計），不阻塞其他
功能、不誤判為「未觸發」。可參照本 repo 既有 `benchmark.py` 對 FinMind
額度用盡時的優雅降級先例（顯示異常提示、不影響其他欄位）。

**明確排除**：背景排程批次輪詢多檔股票——FMP 250次/日與 Alpha Vantage
25次/日的額度都不足以支撐；資料取得維持「使用者/agent互動時按需查詢」。

**API金鑰管理**：FMP／備援來源皆需要申請個人免費API key，儲存與管理方式
（環境變數/設定檔）留待 speckit-plan 階段依本 repo 既有慣例（例如
`finmind_token.txt` 的先例）決定。

## Acceptance Scenarios

1. **正常路徑－交易匯入**：使用者上傳一張券商 App 截圖 → 系統顯示辨識出的
   日期/代號/買賣/股數/價格核對表 → 使用者確認無誤 → 點擊確認匯入 → 該筆
   交易出現在對應個股的股價圖買賣點位上
2. **正常路徑－研究到立場**：使用者與 Claude 討論一檔股票的後勢 → Claude
   產出研究筆記與結構化立場 → 使用者確認存入 → 個股詳情頁的「投資立場」卡片
   顯示該立場摘要，並可點入查看完整研究筆記
3. **正常路徑－關注條件觸發**：使用者與 agent 互動時取得某檔股票最新資料 →
   系統發現股價跌破使用者設定的門檻 → 透過 Telegram 閘道推播通知使用者 →
   美股 landing 頁該檔列顯示「已觸發」狀態 → 使用者點入個股詳情頁看到具體是
   哪個條件觸發、目前數值與門檻的對比
4. **例外路徑－截圖辨識失敗或不完整**：使用者上傳截圖 → 系統嘗試辨識 →
   不論辨識完整、部分失敗或完全失敗，一律呈現核對畫面（已辨識欄位帶入、
   未辨識欄位留空）→ 使用者手動修正/補齊所有欄位 → 確認後才寫入；使用者
   取消核對時，暫存截圖與未確認資料一律捨棄，不留痕跡
5. **例外路徑－agent 查詢不到某檔股票的最新資料**：關注條件比對時若查無
   資料（含FMP查無該股、或FMP額度用盡且備援來源也失敗），狀態顯示為
   「資料不足」（pending，非「未觸發」），避免誤判為條件正常；不觸發推播

## Success Criteria

- 使用者能在美股分頁一眼看出「哪些持股/關注股觸發了警示」，不用逐檔比對
- 使用者能把跟 Claude 討論出的投資立場保留在系統裡，之後回顧時不需要重新
  翻找對話記錄
- 使用者提供交易截圖後，系統能正確辨識並在人工核對後寫入紀錄，不需要逐筆
  手動輸入
- 美股資料與台股資料在分頁、資料表、KB 三層都不互相汙染或混淆（可用「隨機
  抽查美股功能的查詢/寫入路徑，確認沒有任何一條會碰到台股既有的表或KB工具」
  驗證）

## Constraints And Assumptions

- 美股相關資料表（交易紀錄、立場、關注條件、報價歷史）不得與既有台股資料表
  共用
- 美股查詢用 KB 必須與既有台股 KB（`mcp__alphavibe-kb__*`）完全獨立
- 幣別一律 USD，不與台股 TWD 混合計算加總
- 單一使用者個人系統，不需要多使用者/多角色權限設計
- 假設交易截圖來源是使用者自己的券商 App/網頁，非公開網路截圖
- 報價/基本面資料透過免費API多來源取得（主要FMP＋備援），使用者與agent
  互動時按需查詢；不做背景排程輪詢，僅用免費層，不升級付費方案（Q-001）
- 交易截圖不永久保留，僅在辨識/核對流程中暫存（Q-004）

## Dependencies

- 視覺元件風格依賴既有 `web/src/styles/tokens.css`／`app.css`／
  `StockComboChart.jsx` 建立的 STND 設計系統（沿用，非重寫）
- 依賴既有 Telegram 閘道（`function/stnd-gateway-web` 已上線的「管家」分頁
  功能）提供關注條件觸發推播（FR-09，Q-002 已定案採用）
- 依賴外部免費報價API：FMP（主要）＋備援來源（Alpha Vantage或yfinance，
  待speckit-plan選定）——需要使用者申請個人免費API key（見§Integration Note）

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 截圖辨識結果有誤或欄位缺漏（部分或全部） | 一律進入核對畫面，已辨識欄位帶入、未辨識欄位留空，不自動落庫 | 核對畫面顯示待確認的完整/部分欄位表 | 使用者手動修正/補齊後確認匯入；取消則暫存檔與未確認資料一併捨棄 | No（Q-003 已定案：手動核對是唯一防線） |
| agent 互動時查無該股最新資料（例如冷門股票查不到） | 關注條件狀態顯示「資料不足」，不誤判為未觸發，不觸發推播 | 個股列表/詳情頁 pill 顯示 pending 灰色狀態 | 下次互動取得資料後自動轉為 ok/alert | No（已有明確產品行為，沿用 SRC-002 mockup 的三態設計） |
| 主要報價來源（FMP）額度用盡或請求失敗 | 自動嘗試備援來源；若備援也失敗，顯示「資料不足」，不阻塞其他功能 | 個股列表/詳情頁 pill 顯示 pending；無需使用者手動介入即可自動降級 | 額度重置或備援恢復後，下次互動自動取得資料 | No（Q-001第二輪已定案降級行為，見§Integration Note） |
| Telegram 閘道推播失敗（例如閘道服務未啟動） | 觸發狀態仍正常寫入並在 STND 頁面顯示，不因推播失敗而遺漏警示 | STND 頁面的警示狀態是最終防線，不依賴推播成功與否 | 使用者下次開啟 STND 美股分頁仍能看到已觸發狀態 | No（沿用「STND頁面顯示」為主、推播為輔的設計） |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Complete | supporting-artifacts/readiness-checks.md | Required by ADR-0027；Q-001~Q-004 已解決，全部項目補完 |
| Workflow 說明 | Yes | Complete | 本檔案 §Workflow | 多步驟循環工作流，已用文字描述取代獨立圖表 |
| Data Model Note | Yes | Complete | 本檔案 §Data Model Note | 概念層＋截圖保留規則（Q-004）均已補完 |
| Integration Note（報價資料源） | Yes | Complete | 本檔案 §Integration Note | Q-001第二輪定案：FMP主要＋備援來源，含降級行為；備援來源最終選定留待speckit-plan，不影響product-spec層級的完整度 |
| Integration Note（通知管道） | Yes | Complete | 本檔案 §Dependencies, §Workflow | 重用既有已上線的 Telegram 閘道（`function/stnd-gateway-web`），介面已存在，不需另開技術性文件 |
| Security/Privacy Note（截圖保留） | Yes | Complete | 本檔案 §Data Model Note | Q-004 已定案：不永久保留，僅流程中暫存 |

## Source Decisions

- 全部來自 `docs/spec-intake/us-stocks/raw/2026-09-04-session-summary.md`（SRC-001）
  的 12 段對話時間軸，逐條決策依據見 `scope-decision.md` 的 Decision Rationale
- 功能內容範例來自 SRC-003（Cloudflare/NET 研究筆記）與 SRC-004（其排版版）
- 畫面結構來自 SRC-002（4畫面 wireframe mockup）
