# Dynamic Readiness Checks: 進出場時機分析工具

**Feature Slug:** entry-exit-timing-analysis
**Last Updated:** 2026-09-01

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | No | Workflow diagram or sequence diagram | N/A | — | 單一使用者（PO）、單一系統（AlphaVibe），查詢式互動，非多角色/多系統流程 |
| Async job, callback, event handling, or state transition | **Yes**（Q-005 確認） | Sequence diagram and state transition model | Open（GAP-R03） | — | 整合進既有模組D每日排程（17:00 launchd 自動觸發），需要說明「計算完成→判斷觸發→寫入Layer2立場記錄→（報告頁面/MCP查詢時）呈現」的狀態流程；也需要說明「尚未設定停損停利門檻」這個中介狀態如何在排程掃描時處理，避免誤判 |
| New or changed external/internal API behavior | **Yes**（Q-004 確認） | API contract or API design note | Open（GAP-R01） | — | 新增 MCP 工具（供 Claude 對話查詢）+ 報告頁面整合，屬於新增/變更 internal API 行為；需定義新工具的名稱、輸入輸出、以及報告頁面既有浮動損益顯示邏輯的變更範圍 |
| Third-party or cross-system integration | No | Integration note, data mapping, timeout/retry semantics, and failure behavior | N/A | — | 沿用既有資料源（TWSE/TPEx 官方營收、FinMind 備援、既有持股/交易紀錄表），不引入新的外部系統或第三方 API |
| New or changed data lifecycle | **Yes**（Q-002/Q-003 確認） | Data model note, retention rule, migration note, or compatibility note | Open（GAP-R02） | — | 需要新增資料儲存：(1) FIFO 損益計算的中介狀態或快取 (2) PO 與 Claude 討論後設定的逐檔停損/停利門檻（新欄位或新表，含「尚未設定」狀態）；需定義這些資料的生命週期、要不要保留歷史設定變更紀錄 |
| Permission, role, or approval behavior | No | Permission matrix or approval flow | N/A | — | 單一使用者系統，沿用既有唯讀 MCP 工具權限模式，無新增角色/權限層級 |
| Security, privacy, compliance, or audit concern | No | Security/privacy requirements and audit expectations | N/A | — | 個人本機系統，資料不外流，沿用既有 MCP 唯讀邊界，本功能不改變這個邊界（新增的寫入僅限門檻設定值，屬於低風險本機資料） |
| Import, export, or batch processing | No | Validation rules, partial failure policy, and recovery behavior | N/A | — | 計算基於既有資料即時查詢/排程計算，非批次匯入/匯出功能 |
| High-risk, irreversible, payment, order, or control flow | No | Idempotency expectations, compensation behavior, and audit trail requirements | N/A | — | 輸出是分析/建議（唯讀），不觸發下單或任何不可逆的系統動作；scope-decision.md 已明確排除自動下單 |
| Operationally sensitive behavior | **Yes**（Q-005 確認） | Observability, alerting, and manual recovery note | Open（GAP-R04） | — | 整合進每日排程主動提醒，若排程失敗或資料異常需要有降級/告警機制（呼應既有 `benchmark.py` 的優雅降級模式，CLAUDE.md 2026-07-28 教訓紀錄），避免誤判觸發或漏掉真正該提醒的訊號 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-R01 | API contract / API design note | Yes（handoff 前必須補上） | 定義新 MCP 工具的名稱、輸入輸出、涵蓋幾檔/單檔查詢；定義報告頁面既有浮動損益顯示要如何改用新 FIFO 邏輯 | Stander | Open |
| GAP-R02 | Data model note | Yes（handoff 前必須補上） | 定義 FIFO 損益計算所需資料結構；定義逐檔停損/停利門檻的儲存欄位/表格設計，含「尚未設定」狀態的表示方式 | Stander | Open |
| GAP-R03 | Sequence diagram / state transition model | Yes（handoff 前必須補上） | 定義每日排程→訊號判斷→寫入立場記錄→呈現（MCP查詢/報告頁面）的完整狀態流程 | Stander | Open |
| GAP-R04 | Observability / alerting note | Yes（handoff 前必須補上） | 定義排程失敗、資料不足時的降級與告警行為，避免誤判或漏報 | Stander | Open |

這 4 項預期在 `product-spec.md` 定稿、或後續 spec-kit-input 拆分階段展開為
獨立文件/章節；目前 product-spec.md 已在對應章節標註待補位置。
