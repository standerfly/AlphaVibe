# Specification Quality Checklist: 進出場訊號層（門檻、背離偵測與主動提醒）

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

**驗證第 2 輪（2026-09-03）：16 項全數通過。**

PO 已裁決三個待決項（Q1 選項 A：訊號不寫立場記錄；Q2 選項 C：FIFO 與
加權平均估算並存但標明口徑；Q3 選項 A：僅對話設定門檻，不新增網頁表單），
三個標記皆已轉為正式需求（FR-013／FR-015／FR-004）。

以下為第 1 輪原始紀錄，保留供追溯：

**驗證第 1 輪（2026-09-03）：1 項未通過。**

未通過項目：`No [NEEDS CLARIFICATION] markers remain` —— 3 個標記，
全部來自實查現況後浮現的真實取捨，非規格撰寫疏漏：

1. **FR-004（門檻設定管道）**：React 前端目前只能讀不能寫，既有的加碼
   計畫表單留在舊版頁面、新版 API 刻意未遷移。要不要網頁設定＝要不要
   新開端點，屬範圍決策。
2. **FR-013（訊號要不要寫進立場記錄）**：實測立場記錄 474 筆中 437 筆
   已是機器自動寫入、PO 手寫僅 37 筆，且每檔的「最新立場」永遠是機器
   那筆。新訊號寫或不寫，影響 PO 自己的投資紀錄品質，無明顯預設答案。
3. **FR-015（FIFO 切換的顯示退步）**：實測約 1/3 持股會從「有數字」
   變成「無法計算」，是可見的 UX 退步，需 PO 判斷可否接受。

其餘 15 項通過。判斷依據補充：

- **No implementation details**：spec 提及「營收年增率」「百分位」
  「每日自動檢視流程」屬領域概念與既有機制，未出現檔名、函式名、
  資料表名、框架名。
- **Success criteria measurable**：SC-003 以實測基準線（39 檔 18.3 分鐘）
  為比較基準，可量測；其餘為 100% 覆蓋率或一致性判斷，皆可驗證。
- **Edge cases**：六項全部來自實際查證的數字（437/474 洗版、21/60 賣超、
  18.3 分鐘基準線、14 筆年增率上限、1 檔有加碼計畫、註解時間不一致），
  非臆測。
