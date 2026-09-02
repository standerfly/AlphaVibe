# Product Spec: 進出場時機分析工具

**Status:** Draft
**Feature Slug:** entry-exit-timing-analysis
**Function Branch:** function/entry-exit-timing-analysis
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** N/A
**Acceptance Evidence:** N/A

## Problem And Goal

目前 AlphaVibe 沒有任何工具能回答「這個價位算不算好的進場點」或「現在該
不該停損/停利」——既有的複核工具（`check_position_control`、
`check_strategy_review`、`check_laoyutou_signal`、`_downside_risk` 等）
各自做的是部位大小建議、策略候選資格檢查、真人導師動向比對、PER 估值
定位，沒有一個是針對 PO 自己的持股成本與股價走勢做進場/出場時機判斷。

2026-09-01 的一輪對話中，PO 要求「分析投資進場時機」，只能靠人工/agent
手動交叉比對 `get_holdings`、`get_trade_ledger`、`get_stock_price_history`、
`get_revenue_yoy` 多個唯讀工具現拼現湊，過程中發生一次真實的資料誤讀
事故（`yoy_growth` 欄位單位換算錯誤，導致多檔持股的成長判斷方向整個
顛倒），靠 PO 事後追問、主線對話直接查原始 API 交叉核對才抓到。

目標：把這套「進出場時機分析」系統化、工具化，讓 Claude 能直接查詢結構化
結果，而不是每次都重新手動拼湊、且容易在拼湊過程中出錯；並且在訊號觸發
時主動提醒 PO、一併給出調整建議，取代目前完全被動、靠 PO 想到才問的
狀態。

## Business Context And Priority

- Priority: **高——roadmap 第一順位**（PO 2026-09-01 決定）。與其他懸置
  待辦的相對順序：本功能 ＞ 興櫃候選篩選缺口 ＞ 1g 模組G策略績效回顧
  ＞ Layer 1 哲學庫自動拼接（FR-014）；Phase 2 正式產品啟動維持按住不動
  （PO 2026-08-18 決定，本次未翻案）。
  排序理由：本功能來自 2026-09-01 對話中**真實發生的分析事故**，不是
  預先規劃可無限期等待的路線圖項目；直接餵給 PO 日常的加減碼決策流程，
  價值兌現速度快於事後回顧性質的 1g；且 FIFO 損益邏輯完成後 1g 可直接
  複用，順序上先做本功能反而省工。
- Timing: **分兩階段交付**（PO 2026-09-01 同意，拆分內容見
  `scope-decision.md` Split Feature Decisions）——階段A（基礎：損益追蹤
  ＋股價歷史高低位＋MCP工具化）先交付並可獨立使用，階段B（進階：討論式
  停損停利＋背離偵測＋觸發建議＋報告頁面整合＋排程整合）接續。
  PO 目標是完成 roadmap 前三順位項目（本功能、興櫃篩選缺口、1g），
  興櫃篩選缺口範圍小且與本功能不衝突，可並行推進。
- Business value: 降低 PO 每次檢視持股時的人工分析成本與出錯風險
  （本次事故已證明手動拼湊會出錯）；把 product-spec.md 既有但延宕未兌現
  的規劃（FR-051 停利邏輯、FR-022 損益追蹤）往前推進；訊號主動化取代
  被動查詢，降低「沒想到要查」而錯過調整時機的風險

## Actors

- **Stander（PO，唯一使用者）**：查詢持股的進場時機評估、損益、停損停利
  訊號與調整建議，作為部位調整決策的輸入；與 Claude 討論並設定每檔持股
  的停損/停利門檻
- **Claude（透過 MCP 工具或既有報告頁面代 PO 執行查詢/分析）**：本功能的
  直接呼叫者與門檻討論的對話對象，取代目前的手動交叉比對流程

## MVP Scope

> 完整範圍決策與理由見 `scope-decision.md`。

### In Scope

- 進場後損益追蹤（FIFO 成本法，已實現＋未實現損益皆含）
- 現價相對歷史價格區間的高低位判斷（股價本身，非既有 `_downside_risk`
  衡量的 PER）
- 停損/停利觸發判斷——門檻由 PO 與 Claude **逐檔討論後設定**（非固定
  公式、非全自動）
- 基本面訊號與價格走勢的背離偵測
- 既有營收年增率轉強/轉弱判斷範圍擴大
- 訊號觸發時（停損/停利/背離）一併建議該檔持股接下來可以怎麼調整
  （換股/減碼/對沖/續抱理由）
- 呈現形式：MCP 工具＋報告頁面整合，兩者都要
- 整合進既有模組D每日排程（17:00 自動跑），主動觸發提醒並寫入 Layer 2
  立場記錄

### Out Of Scope

- 自動下單／自動執行交易
- 老芋頭訊號的自動化解讀（維持純陳述、不做基本面判斷的既有邊界）
- 新增外部資料源或第三方 API
- 更廣的主動策略/選股發現（例如整合 `screen_stocks`／`market_scan`
  主動比對「有沒有更好的候選標的」）——本功能的策略建議僅限「觸發訊號
  當下、該檔持股怎麼辦」

### Deferred

- （本輪確認後，原 Deferred 項目已全數改列 In Scope，目前無延後項目）

## Functional Requirements

- **FR-E01**：系統應能計算並回傳指定持股（或全部持股）的進場後損益，
  使用 FIFO 成本法，同時涵蓋已實現損益（已出清標的）與未實現損益
  （目前持有部位）。
- **FR-E02**：系統應能計算並回傳指定股票現價在其歷史價格區間中的相對
  百分位，判斷方式參考既有 `_downside_risk`
  （`poc/kb-mcp/review_engine.py:146-200`）的歷史百分位邏輯框架，但衡量
  對象改為股價本身而非 PER。區間長度（例如近 52 週或近 N 年）待
  spec-kit 階段與現有 `stock_price_history` 資料涵蓋範圍一併確認。
- **FR-E03**：系統應提供機制讓 PO 與 Claude 討論後，為指定持股設定停損/
  停利門檻（非系統自動計算、非固定公式）；系統需記住設定值，並持續
  監控現價是否觸發；尚未設定門檻的持股需有明確的「尚未設定」狀態，
  不可誤判為「安全」或「已觸發」。
- **FR-E04**：系統應能偵測基本面訊號（營收年增率變化）與股價走勢之間的
  背離——例如營收轉強但股價不漲、或股價上漲但基本面未跟上。對應
  product-spec.md 既有 FR-051 規劃過但未實作的 `good_news_priced_in`
  （見 Source Decisions）。
- **FR-E05**：系統應擴大既有 `_growth_deceleration`
  （`poc/kb-mcp/review_engine.py:117-143`）／`revenue_yoy_accel`
  （`review_engine.py:984-1001`）的營收年增率轉強/轉弱判斷範圍（現況
  只看最近 2-3 期）。
- **FR-E06**：當 FR-E03（停損/停利）或 FR-E04（背離偵測）的訊號觸發時，
  系統除了標示訊號本身，也要建議該檔持股接下來可以怎麼調整（例如：
  換股、部分減碼、對沖、續抱理由）。範圍鎖定在觸發當下的該檔持股，
  不做主動選股/策略發現。
- **FR-E07**：以上功能須同時具備 MCP 工具（供 Claude 對話直接查詢）與
  報告頁面（`report.py`／`app/`）整合兩種呈現形式；報告頁面既有的浮動
  損益快照顯示需改用 FR-E01 的 FIFO 邏輯以確保數字一致（見 Dependencies）。
- **FR-E08**：以上判斷需整合進既有模組D每日排程（`roadmap.md:200-208`，
  17:00 launchd 自動跑），主動觸發提醒並寫入 Layer 2 立場記錄，而非僅
  在 PO 主動查詢時才計算。

## Acceptance Scenarios

1. PO 於對話中詢問「我的持股進場損益」，系統回傳每檔持股的 FIFO 損益
   金額與百分比（含已實現與未實現），數字與 `get_trade_ledger` 的原始
   交易紀錄可交叉驗證一致。
2. PO 詢問某檔股票「現在的價位算高還是低」，系統回傳該股現價在歷史區間
   的百分位。
3. PO 與 Claude 討論後為某檔持股設定停損門檻，之後系統的每日排程掃描
   到現價觸及該門檻時，主動寫入立場記錄並提示 PO；PO 於報告頁面與
   對話中都能看到這則提醒。
4. 系統偵測到某檔持股「營收年增率轉強但股價未跟漲」的背離訊號，主動
   提醒 PO，並附帶「可以考慮加碼/繼續觀察」等調整建議選項。
5. 某檔持股觸發停利門檻，系統除了標示「已達停利」，也一併列出「部分
   減碼」「换股」「續抱（理由：...）」等選項供 PO 參考決策，不自動執行
   任何交易。
6. 尚未設定停損/停利門檻的持股，在每日排程掃描與報告頁面顯示中，明確
   標示「尚未設定門檻」，不會被誤呈現為「安全」或「已觸發」。
7. 某檔股票缺完整歷史價格資料，FR-E02 的百分位計算回傳「資料不足，
   無法計算」，不用不足樣本硬算也不顯示 0%，且不影響該檔的損益計算與
   其他持股的結果（完整降級行為見 Error Handling Requirements）。

## Success Criteria

- PO 能直接查詢到 FIFO 正確計算的損益數字（已實現＋未實現），不需要
  Claude 手動交叉比對多個工具（對照本次事故：避免重蹈單位誤讀覆轍）。
- 股價歷史高低位判斷、停損停利觸發判斷、背離偵測，能被單一工具呼叫
  取得結果，取代目前需要多輪 agent 對話＋人工交叉驗證的方式。
- 訊號觸發時能主動出現在報告頁面與立場記錄，不需 PO 主動查詢才看得到。
- 訊號觸發時附帶具體可選的調整建議，不是只有「觸發了」三個字。
- （具體可測量的數值門檻，例如查詢延遲、涵蓋檔數、排程執行時間，
  留待 spec-kit 技術規劃階段細化）

## Constraints And Assumptions

- 沿用既有資料源，不引入新的外部資料源或第三方 API。
- 這是延伸 product-spec.md 既有但未兌現的規劃（見 Source Decisions），
  FR-E03/E04 與既有 FR-051 是互補關係：FR-051 的質化描述（財報兌現但
  股價無感）可作為 PO 與 Claude 討論停損/停利門檻或背離判斷時的參考
  依據，不是重複實作。
- FR-E03 的門檻設定是協作式（PO 與 Claude 討論），需要新的資料儲存
  機制記住設定值，具體 schema 設計留給 spec-kit 階段。
- 假設本功能是唯讀分析/建議性質，FR-E06 的調整建議不涉及自動下單或
  自動執行任何交易。

## Dependencies

- 依賴既有 MCP 工具與底層函式：`get_trade_ledger`、`get_stock_price_history`、
  `get_holdings`、`get_revenue_yoy`、`review_engine.py` 的 `_downside_risk`／
  `_growth_deceleration`／`revenue_yoy_accel` 邏輯框架
- 依賴 `report.py`／`app/routers/stock_detail.py` 既有的浮動損益顯示
  邏輯——需改用 FR-E01 的 FIFO 邏輯以確保數字一致（見 GAP-002，
  extracted-requirements.md）
- 依賴既有模組D每日排程機制（`roadmap.md:200-208`，17:00 launchd）與
  Layer 2 立場記錄寫入路徑

## Error Handling Requirements

> 以下行為沿用本 repo 既有慣例，非新發明：`benchmark.py` 的優雅降級模式
> （失敗時記錄錯誤、不影響其他欄位、頁面顯示異常橫幅，CLAUDE.md
> 2026-07-28 教訓紀錄）與部位控制卡的「算不出來就明講、不要畫 0% 空條」
> 三分狀態原則（roadmap.md:87-89、264-266）。

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 個股缺完整歷史價格資料，無法計算 FR-E02 百分位 | 該檔百分位回傳「無法判斷」狀態，不猜測、不用不足的樣本硬算；其餘欄位（損益、門檻狀態）不受影響照常回傳 | 報告頁面與 MCP 回傳皆明確標示「資料不足，無法計算」，不顯示 0% 或空白讓人誤讀 | 待該檔累積足夠歷史價格資料（既有背景刷新機制會逐步補齊）後自動恢復 | 否 |
| FIFO 計算遇到交易紀錄不完整（例如缺進場價或數量） | 該檔損益回傳「無法計算」狀態並註明原因（缺哪個欄位），不用不完整資料算出誤導性數字；其他持股的計算不受影響 | 明確指出是哪一筆交易紀錄有問題，讓 PO 能去補正原始資料 | PO 補正交易紀錄後重新計算 | 否 |
| 持股尚未設定停損/停利門檻 | 明確標示「尚未設定」狀態，不得誤判為安全或已觸發（見 Acceptance Scenario 6） | 報告頁面與 MCP 查詢皆需顯示此狀態 | PO 可隨時與 Claude 討論補設 | 否 |
| 每日排程執行失敗或資料來源異常（例如 FinMind/TWSE 額度用盡，參照 CLAUDE.md 2026-07-28 教訓） | 比照 `benchmark.py` 既有模式：記錄錯誤、該次掃描的受影響欄位標為異常，不中斷整批排程、不影響其他檢查項目的結果寫入 | 報告頁面顯示異常橫幅說明哪部分資料當次未取得；立場記錄中標註該次結果不完整 | 隔日排程自動重試；PO 也可手動觸發重跑 | 否 |
| 訊號觸發但 FR-E06 無法產生調整建議（例如缺基本面資料無從比較） | 仍然照常標示訊號觸發本身（不因為建議產不出來就吞掉訊號），建議欄位標示「資料不足，需人工判斷」 | 明確區分「訊號有觸發」與「建議產不出來」兩件事 | PO 可在對話中要求 Claude 補查後再議 | 否 |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Draft | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| API contract / API design note | Yes | Open（GAP-R01） | supporting-artifacts/readiness-checks.md | 新增 MCP 工具＋報告頁面變更的 internal API 行為 |
| Data model note | Yes | Open（GAP-R02） | supporting-artifacts/readiness-checks.md | FIFO 損益計算與逐檔門檻儲存的資料生命週期變更 |
| Sequence diagram / state transition model | Yes | Open（GAP-R03） | supporting-artifacts/readiness-checks.md | 每日排程整合的狀態流程 |
| Observability / alerting note | Yes | Open（GAP-R04） | supporting-artifacts/readiness-checks.md | 排程失敗/資料異常的降級與告警行為 |

## Source Decisions

- 本 spec 全部內容源自 SRC-001（2026-09-01 對話紀錄與 Explore agent 系統
  盤點）與後續 Q-001~Q-006 clarification 回答，見
  `raw/2026-09-01-conversation-gap-analysis.md`、`clarification-log.md`
- 與既有 product-spec 決策的關聯：
  - FR-051（`product-spec.md:358-360`，通用檢視層）：規劃過「利多出盡／
    停利邏輯」但目前 `manual_notes` 寫死 `None`，與 FR-E03/E04 是互補
    關係（見 Constraints And Assumptions），非重複實作
  - FR-022（`product-spec.md:398-401`）：進出場紀錄 FR 明文排除損益
    追蹤，留給「交易覆盤頁」階段，該階段未排時程——FR-E01 承接這個
    被延後的範圍
  - FR-011（`product-spec.md:447-449`）：曾規劃的「進場價觸及提醒」已
    明文放棄（0% 使用率），本功能不重啟該機制，改用 FR-E02／FR-E03
    的新邏輯
  - FR-059（`product-spec.md:451-460`，模組G策略績效回顧）：策略/候選
    層級的事後回顧，與本功能的個股即時進出場時機分析屬不同層次，
    無直接依賴
