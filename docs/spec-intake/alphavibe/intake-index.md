# Intake Index: AlphaVibe

This file tracks all raw source materials collected for the AlphaVibe feature.

| Source ID | File / Reference | Type | Source Date | Owner | Status | Notes |
|-----------|------------------|------|-------------|-------|--------|-------|
| SRC-001 | raw/src-001-product-brief.md | 產品需求草稿 | 2026-05-16 | Stander | Extracted | FR-001~014 已抽取；§11 Q1/Q2 未決（非阻塞，見 extracted-requirements） |
| SRC-002 | raw/src-002-ai-conversation-input.md | 需求來源（PO 口述＋決策紀錄） | 2026-07-06 | Stander | Extracted | 候選 FR-015~018；決策對應 Q-019~Q-021 |
| SRC-003 | raw/[LINE] 與于志宇的聊天.txt | 資料樣本（LINE 一對一匯出，約 1.3MB） | 未知 | Stander | Indexed | 知識庫內容樣本＋清洗規則設計依據（FR-012）；非需求敘述來源；大檔勿直讀 |
| SRC-004 | raw/[LINE] 🍀U Life的聊天.txt | 資料樣本（LINE 群組匯出，約 24MB） | 未知 | Stander | Indexed | 同 SRC-003；隱私規則見 Q-005/Q-008（群主匿名、僅收群主發言）；大檔勿直讀 |
| SRC-005 | raw/定錨個股.txt | 資料樣本（定錨 email 個股） | 未知 | Stander | Indexed | regex 結構化解析設計依據（FR-002） |
| SRC-006 | raw/定錨週報.txt | 資料樣本（定錨 email 週報） | 未知 | Stander | Indexed | 同 SRC-005 |
| SRC-007 | raw/股癌筆記.txt | 資料樣本（股癌 FB 筆記） | 未知 | Stander | Indexed | Layer 1 Module B 素材來源樣本（FR-001） |
| SRC-008 | raw/全方位分析儀表板範例.jpg | UI 參考圖 | 未知 | Stander | Indexed | 儀表板版面參考；現行 mockup 為 repo 根目錄 frontend_mockup.html |
| SRC-009 | raw/src-009-fundamental-selection-pivot.md | 需求來源（PO 口述＋主軸重塑決策） | 2026-07-07 | Stander | Extracted | 候選 FR-019~025；決策對應 Q-028~Q-032；含引擎架構轉向（Claude+Cline、local-first） |
| SRC-010 | raw/src-010-claude-app-supplement-brief.md | 補充需求建議書（Claude App 實測流程萃取） | 2026-07-09 | Stander | Extracted | 候選 FR-026~031；裁決見 Q-034~Q-036（引擎維持、持股部分納入、追溯包納入＋擴充 PoC）；服務化架構不採納、Phase 2 前再評估 |
| SRC-011 | raw/部位管理*.md | 需求來源（PO與AI教練對話，v1+v2.0兩版本） | 2026-07-23 | Stander | Extracted | v1=anchoring bias與六項加碼checklist；v2.0=十層部位管理框架（信心分級建倉/Gate+Score加碼/遞減部位/組合集中度/風險評分/投資日誌）；候選 FR-038~043；決策見 Q-038~Q-040；MVP子集見 product-spec §5-K，量化評分/風險評分/流水表列 Deferred |
