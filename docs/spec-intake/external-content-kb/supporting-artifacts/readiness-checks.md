# Dynamic Readiness Checks: 外部內容知識庫（YouTube／Podcast／文章）

**Feature Slug:** external-content-kb
**Last Updated:** 2026-11-25

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram or sequence diagram | Complete | ../product-spec.md「Workflow」節 | 收件匣進件、去重、確認摘要多步驟 |
| Async job, callback, event handling, or state transition | Yes（僅狀態轉移） | Sequence diagram and state transition model | Draft | ../product-spec.md「狀態模型」節 | 無非同步任務；有摘要確認與內容生命週期的狀態轉移 |
| New or changed external/internal API behavior | Yes（技術設計留待 plan） | API contract or API design note | Deferred to plan（PO 2026-11-25 接受） | — | 新增 MCP 查詢與匯入工具、收件匣進件；工具名稱／參數屬技術設計，於 Spec Kit plan 產出；需求層行為已在 FR-004～FR-014 |
| Third-party or cross-system integration | N/A | — | N/A | — | 第一階段不抓取外部平台（自動抓字幕列為後續）；內容由 PO 提供 |
| New or changed data lifecycle | Yes | Data model note, retention rule, migration note, or compatibility note | Complete | ../product-spec.md「Data Lifecycle And Security Notes」節 | 新資料庫；無遷移；保存期限＝不自動過期 |
| Permission, role, or approval behavior | Yes（PO 確認摘要） | Permission matrix or approval flow | Draft | ../product-spec.md「Workflow」「狀態模型」 | 唯一的審核關卡是 PO 確認摘要；寫入／刪除只在非唯讀端 |
| Security, privacy, compliance, or audit concern | Yes（輕度） | Security/privacy requirements and audit expectations | Draft | ../product-spec.md「Data Lifecycle And Security Notes」節 | 第三方內容個人使用假設（Q-011）、收件匣讀檔範圍、操作稽核 |
| Import, export, or batch processing | Yes（單筆匯入） | Validation rules, partial failure policy, and recovery behavior | Draft | ../product-spec.md FR-002、FR-007 與 Error Handling 表 | 必填驗證、全有或全無、重送不重複 |
| High-risk, irreversible, payment, order, or control flow | Yes（刪除） | Idempotency expectations, compensation behavior, and audit trail requirements | Draft | ../product-spec.md FR-010、FR-013 | 刪除須 PO 明確確認；重送不得造成重複（冪等） |
| Operationally sensitive behavior | N/A | — | N/A | — | 無排程、無常駐背景作業；失敗皆為即時回報給 PO |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | 去重行為定案 | No | Q-003 | Stander | Closed（2026-11-25） |
| GAP-002 | 摘要確認與儲存定案 | No | Q-005 | Stander | Closed（2026-11-25） |
| GAP-003 | 連接器暴露範圍 | No | Q-009 | Stander | Closed（2026-11-25） |
| GAP-004 | 更新／刪除流程定案 | No | Q-013 | Stander | Closed（2026-11-25） |
| GAP-005 | 上傳端點是否入 MVP | No | Q-014：不入 MVP | Stander | Closed（2026-11-25） |
| GAP-006 | claude.ai 短文備援單次呼叫上限實測 | No（plan 階段） | Q-018 | Claude | Open |
