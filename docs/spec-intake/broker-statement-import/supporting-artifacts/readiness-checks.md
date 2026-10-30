# Dynamic Readiness Checks: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Last Updated:** 2026-10-31

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram or sequence diagram | Complete | workflow-and-states.md | 國泰 Email → Gmail → 解密 → 解析 → 寫入 → 通知，跨三個系統 |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Complete | workflow-and-states.md | 每日排程；每份對帳單有待處理／已處理／部分完成／失敗狀態 |
| New or changed external/internal API behavior | No | API contract or API design note | N/A | — | MVP 不新增對外 API 或 MCP 工具；查詢沿用既有 get_holdings／get_trade_ledger |
| Third-party or cross-system integration | Yes | Integration note, data mapping, timeout/retry semantics, and failure behavior | Complete | integration-data-security-note.md §1～2 | Gmail 與國泰 PDF；資料對應依 Q-002 定案 |
| New or changed data lifecycle | Yes | Data model note, retention rule, migration note, or compatibility note | Complete | integration-data-security-note.md §2～3 | 新增自動來源的交易與庫存、處理紀錄；成本規則依 Q-002 |
| Permission, role, or approval behavior | Partial | Permission matrix or approval flow | N/A | — | 單一使用者系統，無角色；「是否需事前確認」已由 Q-001 決定為不需要 |
| Security, privacy, compliance, or audit concern | Yes | Security/privacy requirements and audit expectations | Complete | integration-data-security-note.md §3～4 | 身分證字號、信箱憑證只存 Mac 鑰匙圈（Q-004） |
| Import, export, or batch processing | Yes | Validation rules, partial failure policy, and recovery behavior | Complete | workflow-and-states.md；integration-data-security-note.md §5 | 整份全有或全無；個別名稱對不到為部分完成 |
| High-risk, irreversible, payment, order, or control flow | Partial | Idempotency expectations, compensation behavior, and audit trail requirements | Complete | integration-data-security-note.md §3 | 不動帳戶、不下單；但直接寫入財務紀錄，需冪等與稽核 |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Complete | integration-data-security-note.md §5 | Telegram 摘要通知（Q-003） |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | 資料對應（成本規則） | Yes | Q-002 | Stander | Resolved |
| GAP-002 | 監控與通知 | Yes | Q-003 | Stander | Resolved |
| GAP-003 | 安全與隱私 | Yes | Q-004 | Stander | Resolved |
| GAP-004 | 驗證期成功標準 | Yes | Q-005 | Stander | Resolved |
