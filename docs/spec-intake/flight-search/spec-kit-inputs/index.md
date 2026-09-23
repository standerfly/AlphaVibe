# Spec Kit Inputs: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
**Last Updated:** 2026-09-23

| Package Slug | Status | Scope Summary | Dependencies | Handoff Order |
|--------------|--------|---------------|--------------|---------------|
| flight-scan-page | Draft | 分頁骨架、查詢條件 CRUD、四段票掃描與結果顯示、手動觸發、速率守衛與跨時段分批、外部連結、票規提示、原生追蹤說明 | 既有 `poc/kb-mcp/flight_search.py` 與 `scraper/`（已完成，97 測試） | 1 |
| flight-price-tracking | Draft | 定期自動重掃排程、達標判定（以四段票價）、Telegram 通知、資料過期標示與狀態呈現 | flight-scan-page；既有 Telegram 推播基礎設施 | 2 |

## Source Decisions

- 拆分理由：掃描與顯示是可獨立交付且立即有用的最小單位；定期重掃與通知
  需要排程與推播整合，風險與相依都不同，分開交付可讓第一部分先上線驗證。
- 兩個包皆**不重寫演算法**，直接 import 既有模組（比照 `app/` 其他 router 慣例）。
- 兩個包的資料層共用同一組獨立 store ＋ 獨立 db 檔（比照 `us_stock_store.py`／
  `photo_store.py` 先例）。

## Notes

兩個包目前皆為 `Draft`。依 ADR-0027，只有在 `product-spec.md` 取得 PO/TPM
接受證據、且 PO/TPM 明確核准交接後，才可標記為 `Accepted` 並交給
`speckit-specify`。
