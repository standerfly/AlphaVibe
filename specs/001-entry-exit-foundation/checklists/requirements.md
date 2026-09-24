# Specification Quality Checklist: 進出場分析基礎層（損益追蹤與價位定位）

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-02
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

**驗證第 2 輪（2026-09-02）：16 項全數通過。**

PO 已於 2026-09-02 裁決兩個待決項（Q1 選項 C、Q2 選項 A），spec.md 的
2 個 [NEEDS CLARIFICATION] 標記皆已轉為正式需求：FR-006（重複列
照原樣計入＋警示，不自行排除）、FR-010＋FR-014（百分位只用既有快取、
不即時查外部 API，另加長每日排程抓取窗口讓資料自然累積）。

以下為第 1 輪的原始紀錄，保留供追溯：

**驗證第 1 輪（2026-09-02）：1 項未通過。**

未通過項目：`No [NEEDS CLARIFICATION] markers remain` —— spec.md 中有 2 個標記：

1. **FR-006**（疑似重複交易列的處理）：實測流水表有 141 筆同標的/買賣別/
   股數/價格/日期的多餘列、3 組重複 `order_ref`。FIFO 會把重複列當成真實
   批次，直接影響損益數字正確性。屬於「多個合理解讀、代價不同」的取捨，
   需 PO 裁決。
2. **FR-010**（百分位區間長度）：實測歷史股價快取最長僅約 100 個交易日
   （自 2026-04-13 起），無法支撐近 52 週或更長區間。選項之間的代價差異
   顯著（短區間削弱判斷價值 vs 線上查詢衝突既有原則與 API 額度風險），
   需 PO 裁決。

第 1 輪其餘 15 項通過。特別說明幾項判斷依據：

- **No implementation details**：spec 提及 FIFO、收盤價、交易成本欄位缺漏
  等，屬於**需求本身**（PO 已在 pre-spec 階段裁定成本法為 FIFO）與**資料
  現況限制**，非技術選型；未出現語言、框架、資料表名稱、函式名稱。
- **Requirements are testable**：每條 FR 都可用「查詢後比對回傳內容」驗證；
  FR-004/009 這類「不得輸出誤導值」的否定式需求，以 Acceptance Scenario
  2 的具體情境對應。
- **Edge cases**：全部來自實際查證的資料現況（21/60 檔賣超、141 筆疑似
  重複、21/23 均價缺值、39/60 檔有股價、無手續費欄位、股數單位為張），
  非臆測。
