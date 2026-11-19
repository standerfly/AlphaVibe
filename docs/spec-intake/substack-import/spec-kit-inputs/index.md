# Spec Kit Inputs Index: Substack 文章自動匯入（011）

**Feature Slug:** substack-import
**Last Updated:** 2026-11-19（阻擋項決定後修訂）

product-spec.md 已於 2026-11-19 Accepted；PO 於同日批准 handoff，兩包皆 Accepted，可依 Handoff Order 交給 `speckit-specify`（先第 1 包，再第 2 包）。拆法為草稿建議，PO 可改為合併一包。

| Spec Feature Slug | Status | Scope Summary | Dependencies | Source Decisions | Handoff Order |
|-------------------|--------|---------------|--------------|------------------|---------------|
| substack-fetch-and-store | Accepted | 追蹤清單、RSS 輪詢、去重、首次 14 天、免費全文／付費預覽、圖片下載（含排程補下載）與圖位標記、手動少量轉寫、`substack.db`、每日 22:00 排程與獨立鎖、通知、日誌外洩掃描、空間回報、備份／健檢 | 010 既有基礎設施；Q-111、Q-117、Q-122（Q-107、Q-115 已答） | clarification-log Q-001～Q-011、Q-101、Q-106、Q-107、Q-115、Q-119～Q-121；scope-decision | 1 |
| substack-search-and-live-fetch | Accepted | 雙庫並查搜尋與來源可信度／僅預覽標示、通用即時取得寫入工具（台美連接器＋Mac Claude Code，含同步圖片下載與逾時回報）、最小間隔守衛（與排程互計）、守門數字與 parity 例外、另證 010 唯讀守門未破壞 | 第 1 包；Q-108、Q-113、Q-118（Q-102 已答；Q-104 待審閱，不阻擋） | clarification-log Q-012～Q-015、Q-102、Q-121；scope-decision | 2 |
