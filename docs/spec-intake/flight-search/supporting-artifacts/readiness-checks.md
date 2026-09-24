# Dynamic Readiness Checks: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
**Last Updated:** 2026-09-23

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram | Complete | supporting-artifacts/workflow-and-states.md | 掃描是多步驟流程：枚舉組合→依速率分批→逐筆查價→落地快取→排序→達標判定。屬 multi-step 而非 multi-role——單人系統故無角色維度 |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Complete | supporting-artifacts/workflow-and-states.md | 掃描為背景非同步作業，跨時段分批；追蹤條件有明確狀態（待掃／掃描中／排隊中／已完成／已達標／失敗／資料過期）。**內容依賴 Q-017（重掃頻率）** |
| New or changed external/internal API behavior | Yes | API contract or API design note | Complete | product-spec.md §API 行為 | 新增 `app/routers/flights.py` 端點（追蹤條件 CRUD、觸發掃描、查詢進度與結果）。屬本專案內部 API，以 product-spec 章節描述即可，不需獨立契約檔 |
| Third-party or cross-system integration | Yes | Integration note, data mapping, timeout/retry semantics, and failure behavior | Complete | supporting-artifacts/integration-and-failure.md | 整合 Google Flights（瀏覽器抓取）、Telegram（推播）、SerpApi（備援）。三者的逾時、重試、失敗語意各不相同，且有速率限制與軟封鎖等非典型失敗形態 |
| New or changed data lifecycle | Yes | Data model note | Complete | product-spec.md §資料模型 | 新增追蹤條件、掃描結果、價格快取三類資料。比照 `us_stock_store.py`／`photo_store.py` 先例使用獨立 db 檔。保留策略見 Q-018（非阻斷） |
| Permission, role, or approval behavior | No | Permission matrix or approval flow | N/A | — | 單人個人系統，無其他使用者、無角色分層、無審批流程（見 scope-decision「Out Of Scope」） |
| Security, privacy, compliance, or audit concern | Yes | Security/privacy requirements | Complete | supporting-artifacts/integration-and-failure.md §合規 | 僅合規面（不涉個資或金流），但**涉及第三方網站的自動化存取合規**：須遵循 robots.txt（Skyscanner 明確禁止抓取）、節流、不規避封鎖。此為產品層約束而非實作細節 |
| Import, export, or batch processing | Yes | Validation rules, partial failure policy, and recovery behavior | Complete | supporting-artifacts/integration-and-failure.md §部分失敗 | 屬 batch processing：掃描本質是批次作業且**經常部分完成**（速率上限、軟封鎖）。部分失敗策略是核心需求而非邊角：已完成結果必須保留且可接續 |
| High-risk, irreversible, payment, order, or control flow | No | Idempotency, compensation, audit trail | N/A | — | 系統只查價與比價，不訂票、不付款、不改變任何外部狀態（見 scope-decision「Out Of Scope：訂票與付款」）。重複掃描僅是重複讀取，無副作用 |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Complete | supporting-artifacts/integration-and-failure.md §可觀測性 | 速率上限與軟封鎖會讓功能靜默失效（表現為連續逾時而非明確錯誤）。需要用量可視性、封鎖偵測與人工恢復路徑 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-A01 | supporting-artifacts/workflow-and-states.md | Yes | 追蹤條件的狀態轉換模型；**內容依賴 Q-017（自動重掃頻率）**，頻率決定「排隊中」與「資料過期」的判定門檻 | Stander（決策）／Claude（撰寫） | Open |
| GAP-A02 | supporting-artifacts/integration-and-failure.md | Yes | 三個外部整合的逾時／重試／失敗語意、部分失敗策略、合規約束、可觀測性需求。大部分內容已有實測依據（SRC-005），可在 Q-017 決定後一併完成 | Claude | Open |
| GAP-A03 | product-spec.md §API 行為、§資料模型 | Yes | 隨 product-spec 主文一併完成；**§資料模型依賴 Q-016**（目標價基準決定要不要存接駁票估價與總成本欄位） | Claude | Open |

## Notes

- 三個 Pending 的支援文件都**部分依賴未決的 Blocking 問題**
  （Q-015／Q-016／Q-017），故本輪不先行撰寫，避免寫了再推翻。
- 已明確判定 N/A 的兩項（權限、高風險不可逆流程）皆有理由記錄，
  不是因為尚未評估而留白。
