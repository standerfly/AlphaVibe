# Dynamic Readiness Checks: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
**Last Updated:** 2026-09-24

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | No | Workflow diagram or sequence diagram | N/A | — | 整體工作流程（建立條件→排程掃描→通知）已由既有 `flight-search`／`flight-price-tracking` 的 quickstart.md 完整記錄，本次異動不新增流程步驟，只改變天數與目的地維度的資料形狀，不需要新的流程圖 |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Complete | product-spec.md「Constraints And Assumptions」章節 | 排程／狀態機（idle/scanning/complete/stale/queued）本身不新增狀態，沿用既有 `derive_state()`；已在 product-spec 中以 Assumption 形式說明為何預期相容且需於 Spec Kit 階段逐一驗證，不需獨立圖表 |
| New or changed external/internal API behavior | Yes | API contract or API design note | Complete | supporting-artifacts/api-contract-changes.md | 修改既有已上線端點的欄位形狀（trip_days 區間化）、新增行程類型與候選目的地欄位，屬破壞性 API 變更，已獨立成文件記錄 |
| Third-party or cross-system integration | No | Integration note, data mapping, timeout/retry semantics, and failure behavior | N/A | — | 沿用既有 Google Flights 瀏覽器查價整合（`flight_search.py`／scraper），整合機制本身不變，只是用既有的 `google_flights_url()` multi-city 能力組出不同的查詢組合；速率限制與封鎖處理已由既有 flight-search 的 research.md／quickstart.md 記錄 |
| New or changed data lifecycle | Yes | Data model note, retention rule, migration note, or compatibility note | Complete | supporting-artifacts/data-model-migration.md | 對已上線生產資料表（`flight_track`）做破壞性 schema 變更，且正式庫已有真實追蹤條件（id=9）需要遷移，風險高於一般新增欄位，已獨立成文件記錄 |
| Permission, role, or approval behavior | No | Permission matrix or approval flow | N/A | — | 系統只有 PO 單一使用者，全域 Basic Auth／token 保護，無角色權限模型，沿用既有 flight-search 的既定現況 |
| Security, privacy, compliance, or audit concern | No | Security/privacy requirements and audit expectations | N/A | — | 無新增個資、無金流、無新的安全性表面；與既有 flight-search 相同的安全考量（既有 token 保護），本次異動不引入新風險 |
| Import, export, or batch processing | No | Validation rules, partial failure policy, and recovery behavior | N/A | — | 無批次匯入匯出使用者資料的行為；id=9 的遷移是單筆記錄的資料形狀轉換，不是批次處理，已在 data-model-migration.md 說明 |
| High-risk, irreversible, payment, order, or control flow | No | Idempotency expectations, compensation behavior, and audit trail requirements | N/A | — | 無金流、無不可逆的業務交易；最壞情況是 id=9 遷移後重新查價部分失敗，可沿用既有「部分完成不更新 last_success_at」原則安全重試，不會造成資料損毀或不可逆後果 |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Complete | supporting-artifacts/data-model-migration.md「組合數上限守衛」段落 | 組合數大增可能影響既有排程的配額分配，已透過建立時的組合數上限守衛（Q-009/Q-010）處理，沿用既有排程 log（`flight_tracking_job.py` 的 stdout 記錄）即足夠觀測，不需要新增獨立的 alerting 機制 |

## Missing Artifact Gaps

（本輪釐清問題已於 clarification-log.md Q-001～Q-010 全數回答，無阻斷性缺口。）

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| — | — | — | 無未解決的必要支援文件缺口 | — | Resolved |
