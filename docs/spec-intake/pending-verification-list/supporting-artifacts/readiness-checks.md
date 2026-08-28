# Dynamic Readiness Checks: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-step workflow | No | — | N/A | — | 單一使用者（Stander）、單一系統（STND），沒有跨角色交接的多步驟流程 |
| Async job, callback, event handling, or state transition | Yes | 狀態轉換模型 | Complete | product-spec.md「資料模型與狀態轉換」章節 | Q-001 選(B)——`pending_verifications` 有 pending/resolved/dropped 狀態欄位與轉換規則（FR-C04），已沉澱進 product-spec.md |
| New or changed external/internal API behavior | Deferred | API contract note | Deferred to Spec Kit | — | Pre-spec 階段依 Hard Boundaries 只定義產品行為，不寫 API 合約；Q-005 已選現在排入開發，`app/` 新增 router 時由 Spec Kit 階段補 API 設計note |
| Third-party or cross-system integration | No | — | N/A | — | Q-003 已選(B) 首頁被動提醒，不建排程/通知基礎設施，STND 現有頁面瀏覽模式即可承載 |
| New or changed data lifecycle | Yes | Data model note | Complete | product-spec.md「資料模型與狀態轉換」章節 | Q-001 選(B)、Q-002 選(A) 全新獨立表已定案，欄位定義已沉澱進 product-spec.md |
| Permission, role, or approval behavior | No | — | N/A | — | STND 現有假設是個人單一使用者、local-first，沿用既有 stances/comments/position_plans 無角色權限機制的前例 |
| Security, privacy, compliance, or audit concern | No | — | N/A | — | 待觀察項目儲存的內容性質與既有 `comments`/`stances` 表相同（使用者自己的分析判斷文字），未引入新的個資/機密資料類別；沿用既有信任邊界 |
| Import, export, or batch processing | No | — | N/A | — | Q-004 已定案(B)+(C)，MVP 僅手動登記，不做研究筆記自動抽取本身 |
| High-risk, irreversible, payment, order, or control flow | No | — | N/A | — | 沒有金流、下單或不可逆動作；待觀察項目寫錯/漏登記頂多是漏掉一次提醒，可事後補登 |
| Operationally sensitive behavior | No | — | N/A | — | Q-003 已選(B)，不涉及排程掃描，沿用既有頁面渲染即可，無需額外 alerting/manual recovery 機制 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | Data model note（`pending_verifications` 欄位定義＋與既有實體關係） | Yes | 已依 Q-001(B)/Q-002(A) 沉澱進 product-spec.md「資料模型與狀態轉換」章節 | Stander/Codex | Closed |
| GAP-002 | 狀態轉換模型（pending/resolved/dropped 等狀態與轉換規則） | Yes | 已依 Q-001(B) 沉澱進 product-spec.md「資料模型與狀態轉換」章節 | Stander/Codex | Closed |
| GAP-003 | Integration/observability note | N/A | Q-003 已選(B)，不需要此類 note | — | Closed — not needed |
