# Dynamic Readiness Checks: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-step workflow | No | — | N/A | — | 單一使用者（Stander）、單一系統（STND），沒有跨角色交接的多步驟流程；假設仍待 Q-005 確認範圍，但不改變此判斷 |
| Async job, callback, event handling, or state transition | Yes | 狀態轉換模型（至少一份簡短的 state note，不一定要獨立檔案） | Required, pending Q-001 | TBD | 不論 Q-001/Q-003 選哪個選項，「待觀察項目」本身都需要 pending/resolved/dropped 之類的狀態欄位與轉換規則（FR-C04）——這是最小共識，細節（是否需要獨立 sequence diagram）取決於 Q-003 是否選到主動排程掃描（選項C） |
| New or changed external/internal API behavior | Deferred | API contract note | Deferred to Spec Kit | — | Pre-spec 階段依 Hard Boundaries 只定義產品行為，不寫 API 合約；若進入 Spec Kit（Q-005 選A），屆時 `app/` 新增 router 才需要 API 設計note |
| Third-party or cross-system integration | Conditional | Integration note（通知管道的 timeout/retry/失敗行為） | Conditional on Q-003 | — | 只有 Q-003 選 C（主動排程掃描＋通知）才成立——STND 目前沒有任何 push/通知基礎設施，需要新建；若選 A/B 則不需要 |
| New or changed data lifecycle | Yes | Data model note（欄位定義＋與既有 stock_themes/comments/position_plans 的關係） | Required, pending Q-001/Q-002 | TBD | 這正是 Q-001、Q-002 本身要決定的內容——clarification-log 目前是選項討論，PO 決定後需另外沉澱成一份簡短 data model note（可以就是 product-spec 裡的一個章節，不一定要獨立檔案） |
| Permission, role, or approval behavior | No | — | N/A | — | STND 現有假設是個人單一使用者、local-first，沿用既有 stances/comments/position_plans 無角色權限機制的前例 |
| Security, privacy, compliance, or audit concern | No | — | N/A | — | 待觀察項目儲存的內容性質與既有 `comments`/`stances` 表相同（使用者自己的分析判斷文字），未引入新的個資/機密資料類別；沿用既有信任邊界 |
| Import, export, or batch processing | Conditional | Validation rules, partial failure policy | Conditional on Q-004 | — | 只有 Q-004 選到「從研究筆記自動抽取」方向（選項C的延伸或更積極的做法）才成立；目前 Q-004 三個選項都以手動登記為 MVP 主體，暫不需要 |
| High-risk, irreversible, payment, order, or control flow | No | — | N/A | — | 沒有金流、下單或不可逆動作；待觀察項目寫錯/漏登記頂多是漏掉一次提醒，可事後補登 |
| Operationally sensitive behavior | Conditional | Observability/alerting/manual recovery note | Conditional on Q-003 | — | 只有 Q-003 選 C（比照 `market_scan.py` 排程模式）才需要——若選，應比照 `market_scan.py`/`benchmark.py` 既有的優雅降級模式（掃描失敗記錄 error 欄位、不擋其他功能），不是新發明一套 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | Data model note（欄位定義＋與既有實體關係） | Yes | Q-001、Q-002 的 PO 決定 | Stander | Open |
| GAP-002 | 狀態轉換模型（pending/resolved/dropped 等狀態與轉換規則） | Yes | Q-001 的 PO 決定（欄位複雜度決定狀態集合大小） | Stander | Open |
| GAP-003 | Integration/observability note（僅當 Q-003 選 C 時才需要） | Conditional | Q-003 的 PO 決定 | Stander | Open |
