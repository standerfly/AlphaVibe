# Extracted Requirements: 進出場時機分析工具

**Feature Slug:** entry-exit-timing-analysis
**Last Updated:** 2026-09-01

## Candidate Functional Requirements

全部 6 項已於 Q-001~Q-006（clarification-log.md）確認納入 MVP：

- FR-cand-01（SRC-001，Q-002 已答）：提供「進場後損益追蹤」，用 FIFO
  成本法計算，同時涵蓋**已實現損益**（已出清標的）與**未實現損益**
  （目前持有部位），可被 Claude 對話直接查詢（MCP 工具化）。
- FR-cand-02（SRC-001）：提供「現價相對歷史價格區間的高低位判斷」，
  套用在股價序列本身（非既有 `_downside_risk` 衡量的 PER），複用其歷史
  百分位邏輯框架。
- FR-cand-03（SRC-001，Q-003 已答）：提供「停損/停利觸發判斷」，門檻
  **不是固定公式、不是系統自動決定**，而是由 PO 與 Claude **逐檔討論後
  設定**（協作式設定流程），系統負責記住設定值並持續監控現價是否觸發。
- FR-cand-04（SRC-001，Q-001 已答，**由 Deferred 改列 MVP**）：提供
  「基本面訊號與價格走勢的背離偵測」——例如營收轉強但股價不漲、或股價
  漲但基本面未跟上。對應 product-spec.md FR-051 規劃過但未實作的
  `good_news_priced_in`（見 GAP-001）。
- FR-cand-05（SRC-001，Q-001 已答，**由 Deferred 改列 MVP**）：擴大既有
  `_growth_deceleration`／`revenue_yoy_accel` 的營收年增率轉強/轉弱判斷
  範圍（現況只看最近 2-3 期）。
- FR-cand-06（SRC-001，Q-006 新增）：當 FR-cand-03（停損/停利）或
  FR-cand-04（背離偵測）的訊號觸發時，系統除了標示訊號本身，也要**建議
  該檔持股接下來可以怎麼調整**（例如：換股、部分減碼、對沖、續抱理由）。
  範圍鎖定在「觸發當下、該檔持股怎麼辦」，**不做**更廣的主動選股/策略
  發現（Q-006 已排除，見 scope-decision.md Out of Scope）。

## Candidate Actors And User Goals

- **Stander（PO，唯一使用者）**：目標是在檢視持股時，能直接得到「這個
  價位算不算好的進場點」「現在該不該停損/停利」「觸發訊號後該怎麼調整」
  的系統化判斷，取代目前對話中人工交叉比對多個唯讀工具的方式；且停損
  停利門檻要能跟 Claude 討論後客製化設定，而非套用一體適用的公式。
- **Claude（透過 MCP 工具或對話代 PO 執行分析）**：需要能查詢到結構化的
  損益、歷史區間定位、停損停利觸發結果，也需要能記住/寫入 PO 討論後
  設定的個股門檻，並在訊號觸發時提出調整建議。

## Candidate Success Criteria

- PO 能在對話中直接查詢任一持股（或全部持股）的進場損益（已實現＋
  未實現），FIFO 正確計算，不需要 Claude 手動交叉比對多個工具。
- PO 能查到某檔股票目前價位在歷史價格區間的相對高低位。
- PO 能透過對話跟 Claude 討論、設定某檔持股的停損/停利門檻，系統之後
  能持續監控並在觸發時主動標示。
- 基本面與價格背離、營收轉強/轉弱的訊號能被系統偵測並呈現。
- 訊號觸發時，系統能一併提出「這檔接下來可以怎麼調整」的選項，不只是
  單純標示訊號。
- 訊號與提醒能透過每日排程主動產生（不需 PO 主動查詢才看得到）、且能
  在 MCP 工具與報告頁面兩處都查得到/看得到。
- （具體可測量的數值門檻，例如「查詢回應時間」，SRC-001 未提供，
  留待 spec-kit 技術規劃階段細化，非 product-spec 層級的必要項）

## Candidate Constraints And Assumptions

- 沿用既有資料源（`get_trade_ledger`、`get_stock_price_history`、
  `get_revenue_yoy`等），不新增外部資料源。
- 停損/停利門檻是「PO 與 Claude 討論後逐檔設定」，不是自動計算——這代表
  系統需要一個**儲存機制**記住每檔的設定值，且未設定門檻的持股不會被
  誤判為「觸發」或「安全」，需要有清楚的「尚未設定」狀態。
- FR-cand-06（觸發時策略建議）的建議內容不涉及自動下單，維持唯讀
  建議性質。
- 假設：這是唯讀分析/建議性質的功能延伸，不涉及自動下單。

## Candidate Error Or Failure Behavior

- 尚待補齊，非本輪 Q-001~Q-006 涵蓋範圍。已知需要定義的情境：
  - 某檔缺歷史價格資料，無法計算百分位時如何降級（建議參考既有
    `_downside_risk`／`benchmark.py` 的降級模式）
  - FIFO 計算遇到交易紀錄不完整時如何處理
  - 尚未設定停損/停利門檻的持股，在每日排程掃描時如何呈現（不能
    誤標為「安全」或「已觸發」）

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001 | Conflict/Overlap | FR-cand-03（停損/停利觸發）與 product-spec.md 既有 FR-051「利多出盡／停利邏輯」（`good_news_priced_in`，目前為 `manual_notes: None`）概念重疊。 | Resolved（product-spec 撰寫階段處理） | Q-003 答案確定門檻是「PO與Claude討論設定」而非公式化判斷，這與 FR-051 原規劃的「財報兌現但股價無感」質化判斷是互補而非重複——FR-cand-03/04 負責「觸發」，FR-051 的質化描述可作為 Claude 與 PO 討論時的參考依據之一，於 product-spec Source Decisions 節說明整合關係 |
| GAP-002 | SRC-001 | Unclear | FR-cand-01（損益追蹤）與現有 `report.py:1922-1941`／`app/routers/stock_detail.py:194-206` 的浮動損益快照顯示是否要整合成同一套邏輯 | Resolved | Q-004 已答「兩者都要」（MCP工具+報告頁面），代表報告頁面既有的快照顯示需要改用新的 FIFO 損益邏輯以求數字一致，於 product-spec Dependencies 節記錄 |
