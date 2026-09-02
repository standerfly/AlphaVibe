# Spec Kit Inputs Index: 進出場時機分析工具

**Feature Slug:** entry-exit-timing-analysis
**Last Updated:** 2026-09-01

| Spec Feature Slug | Status | Scope Summary | Dependencies | Source Decisions | Handoff Order |
|-------------------|--------|---------------|--------------|------------------|---------------|
| entry-exit-foundation | Accepted | 階段A（基礎）：FIFO 損益追蹤（已實現＋未實現）、股價歷史高低位百分位判斷、MCP 工具化 | 既有 `get_trade_ledger`／`get_stock_price_history`／`get_holdings`／`_downside_risk` 邏輯框架 | Q-001、Q-002、Q-004（clarification-log.md）；scope-decision.md Split Feature Decisions | 1 |
| entry-exit-signals | Draft | 階段B（進階）：討論式停損停利門檻設定與觸發、基本面與價格背離偵測、營收趨勢判斷範圍擴大、觸發時策略建議、報告頁面整合、每日排程整合 | 階段A（entry-exit-foundation）；既有模組D排程與 Layer 2 立場記錄寫入路徑 | Q-001、Q-003、Q-004、Q-005、Q-006（clarification-log.md）；scope-decision.md Split Feature Decisions | 2 |

兩包皆為 Draft，需待 `product-spec.md` 取得 PO/TPM 正式驗收後才能標記
Accepted 並交付 `speckit-specify`（ADR-0027 Step 2 Gate）。
