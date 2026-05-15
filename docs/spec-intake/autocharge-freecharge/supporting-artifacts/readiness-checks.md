# Dynamic Readiness Checks: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram or sequence diagram | Complete | workflow-sequence.md | CPO/LXM, AutoCharge, Retail, DB, payment, invoice, and operations all participate in the checkout decision path. Existing 202/203 HTTP contracts remain unchanged. |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Complete | workflow-sequence.md; order-state-model.md | The new `EligibilityPending` status requires delayed retry and state transition from pending to final order status. |
| New or changed external/internal API behavior | Yes | API contract or API design note | Complete | retail-api-contract.md | AutoCharge adds a Retail eligibility side-call during 203 Checkout; CPO/LXM 202/203 request and response contracts remain compatible. |
| Third-party or cross-system integration | Yes | Integration note, data mapping, timeout/retry semantics, and failure behavior | Complete | integration-and-data-mapping.md | Retail is the eligibility source. SRC-005 defines vehicle/time mapping, timeout, retry, Retail 4xx, and failure behavior. |
| New or changed data lifecycle | Yes | Data model note, retention rule, or compatibility note | Complete | data-model-note.md | The feature maps FreeCharge to existing `NoChargePromotion`, adds `EligibilityPending`, and intentionally excludes trace persistence in v1. |
| Permission, role, or approval behavior | No | Permission matrix or approval flow | N/A | N/A | No new runtime user permission, approval, or role behavior is described. PO/TPM approval is handled by pre-spec governance, not product runtime. |
| Security, privacy, compliance, or audit concern | Yes | Security/privacy requirements and audit expectations | Complete | error-handling-matrix.md; observability-recovery.md | The feature affects vehicle identifiers, payment bypass, invoice bypass, and reconciliation evidence. |
| Import, export, or batch processing | No | Validation rules, partial failure policy, and recovery behavior | N/A | N/A | The source does not describe import/export or batch data processing. Pending retry is operational recovery, not a batch import/export workflow. |
| High-risk, irreversible, payment, order, or control flow | Yes | Idempotency expectations, compensation behavior, and audit trail requirements | Complete | error-handling-matrix.md; observability-recovery.md | Incorrect behavior can charge an eligible vehicle, skip required invoice behavior, duplicate CPO orders, or let redo/helper paths bypass FreeCharge guards. |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Complete | observability-recovery.md | SRC-005 defines stuck-pending warning, retry limit, manual recovery threshold, and retry evidence source. |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | Product baseline | Yes | Business priority and acceptance evidence path. Target stage timing is answered as 2026-06-10. | PO/TPM | Answered by SRC-005; final `product-spec.md` acceptance evidence still required before status can become `Accepted` |
| GAP-002 | Data model note | No | FreeCharge maps to `NoChargePromotion`; `EligibilityPending` shall be added. Exact numeric value can be assigned during implementation unless TPM requires it earlier. | TPM | Answered by SRC-003 |
| GAP-003 | Integration and observability notes | Yes | Retail timeout, retry interval, retry threshold, and retry tracking source. | TPM | Answered by SRC-005 |
| GAP-004 | Invoice and compliance behavior | No | FreeCharge v1 skips invoice issuance and payment deduction; zero-amount invoice mode is out of scope. | PO/TPM with Finance/Tax if needed | Answered by SRC-003 |
| GAP-005 | API and workflow contract | Yes | Final Retail `charging_time` wire format, Retail 4xx behavior for invalid vehicle UUID, and CPO/LXM response mapping. | TPM | Answered by SRC-005; existing 202/203 HTTP contracts must remain unchanged |
