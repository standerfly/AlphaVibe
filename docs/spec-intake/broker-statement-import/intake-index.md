# Intake Index: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Last Updated:** 2026-10-30

| Source ID | Source | Type | Owner | Source Date | Status | Notes |
|-----------|--------|------|-------|-------------|--------|-------|
| SRC-001 | raw/src-001-session-decisions-2026-10-30.md | PO 決策＋研究結論（Claude Code 對話摘要） | Stander | 2026-10-28～2026-10-30 | Extracted | 含國泰無個人 API 的查證來源、寫入方式與驗證期決策 |
| SRC-002 | raw/src-002-cathay-daily-statement-format-2026-10-29.md | 樣本格式（PO 截圖轉錄的欄位結構） | Stander | 2026-10-29 | Extracted | 只有台股、單筆買進的樣本；無賣出、多筆、跨頁交易、複委託樣本 |
| SRC-003 | raw/src-003-cathay-trade-detail-report-format-2026-10-31.md | 樣本格式（PO 手動申請的交易明細表截圖） | Stander | 2026-10-31 | Extracted | 驗證期比對來源；發現委託書號寫法與日對帳單不同（Q-010） |
