# Scope Decision: 知識庫查詢與易用性工具擴充

**Feature Slug:** kb-tooling-extensions
**Last Updated:** 2026-07-18

## MVP In Scope

以下 7 項已於 2026-07-18 完成開發並通過獨立驗收 agent 確認（不是待開發項目，
本文件回溯記錄範圍決定）：

1. 常駐檢視服務（`report_server.py` + macOS launchd 服務）
2. 股票代碼快取（`save_stock_alias`/`get_stock_alias`）
3. 批次存入評論（`save_comments_batch`）
4. 檢視頁行動裝置版面優化（表格轉卡片、哲學模組全文展開）
5. 股票基本資料/產業分類查詢（`get_stock_info`）
6. 股價歷史查詢（`get_stock_price_history`）
7. 月營收年增率查詢（`get_revenue_yoy`）＋三大法人買賣超查詢
   （`get_institutional_trading`）

## Out Of Scope

- 法人 EPS 預估／上修下修查詢——資料源可行性不確定（Q-005）
- 重大訊息／法說會摘要查詢——需另外串接 MOPS，工程量較大，本輪不做（Q-005）
- 全市場批次查詢（不帶單一股票代碼的查詢）——FinMind 免費層多數需付費
  Backer/Sponsor，本輪只做單檔查詢
- 手機端「跟 AI 對話＋存資料」——需要把知識庫服務化上雲，屬 Phase 2
  範圍（對應 product-spec.md 既有 Q-034 決策），本輪僅解決手機端「檢視」

## Deferred Or Later

- 法人 EPS 預估、重大訊息摘要：待未來評估資料源可行性後再排入
- `get_stock_info` 多筆不去重的行為：目前非阻塞，PO 未要求變更（Q-001），
  未來若造成困擾可重新評估

## Split Feature Decisions

本次為回溯記錄既有實作，不切分獨立 Spec Kit input package 交付給 RD
實作（實作已完成）。若未來要以此為基礎再擴充（例如法人 EPS 預估），
屆時再另開新的 spec-kit-inputs 包。

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| kb-tooling-extensions | 涵蓋上述 7 項既有實作的回溯記錄 | 依賴既有 `poc/kb-mcp` Phase 1 PoC 架構 | 1 | Draft（回溯記錄性質，非待交付） |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 先開發、後補 pre-spec | SRC-001 | Stander | 2026-07-18 | 需求已在對話中談清楚、無模糊地帶，不需要為了走流程而卡住開發；但範圍持續累積需要正式記錄避免治理缺口 |
| pre-spec 範圍回溯涵蓋今天全部 4 項工作 | SRC-001 | Stander | 2026-07-18 | 避免只記錄最後一批、漏了前面三項同樣持續擴充 `poc/kb-mcp` 範圍的工作 |
| 不做全市場批次查詢 | SRC-001 | Stander（技術判斷，PO 未反對） | 2026-07-18 | FinMind 免費層限制，且目前使用情境都是針對特定個股 |
