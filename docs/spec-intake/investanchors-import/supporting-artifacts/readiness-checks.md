# Dynamic Readiness Checks: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-12

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram or sequence diagram | Draft | workflow-and-states.md | 登入→清單→逐篇抓取→寫入 |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Draft | workflow-and-states.md | 排程批次＋文章狀態 |
| New or changed external/internal API behavior | No | N/A | N/A | N/A | 無新增對外 API 為 MVP 必要；檢索走既有連接器模式，介面於 plan 定 |
| Third-party or cross-system integration | Yes | Integration note, data mapping, timeout/retry semantics, and failure behavior | Draft | integration-data-security-note.md | 登入第三方網站 |
| New or changed data lifecycle | Yes | Data model note, retention rule, migration note, or compatibility note | Draft | integration-data-security-note.md | 新增獨立文章庫 |
| Permission, role, or approval behavior | No | N/A | N/A | N/A | 單一使用者；無新權限模型 |
| Security, privacy, compliance, or audit concern | Yes | Security/privacy requirements and audit expectations | Draft | integration-data-security-note.md | 帳密、付費內容 |
| Import, export, or batch processing | Yes | Validation rules, partial failure policy, and recovery behavior | Draft | integration-data-security-note.md | 歷史回補批次 |
| High-risk, irreversible, payment, order, or control flow | No | N/A | N/A | N/A | 唯讀抓取、不下單、不改網站資料 |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Draft | integration-data-security-note.md | 被擋/改版需通知與續跑 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | 已讀副作用實測 | Yes | Q-004，需在 Mac 驗證 | Stander | Open |
