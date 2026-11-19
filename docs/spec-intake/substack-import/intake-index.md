# Intake Index: Substack 文章自動匯入（011）

**Feature Slug:** substack-import
**Last Updated:** 2026-11-19（追加決定二）

| Source ID | Source | Type | Owner | Source Date | Status | Notes |
|-----------|--------|------|-------|-------------|--------|-------|
| SRC-001 | raw/2026-11-18-po-prompt.md | PO 原始需求 prompt（原文摘錄）＋010 狀態補充 | Stander | 2026-11-18／19 | Extracted | 含硬性安全隱私限制；其中「通知不得含標題」已被 SRC-002 決定 9 覆寫；其中「Gmail 通知信為輔」「共用 articles.db」等選項已被 SRC-002 取代 |
| SRC-002 | raw/2026-11-19-po-decisions-dialogue.md | PO 決定紀錄（對話整理稿，非逐字；標「PO 原話」者除外） | Stander | 2026-11-19 | Extracted | **優先級最高**，與 SRC-001 衝突時以此為準；決定編號沿用檔內 1～11 及「即時取得」節，本基線引用為「SRC-002 決定N」；檔末兩個「追加決定」節（驗收後五題；Q-103／Q-104 調查後）優先於其前面任何內容 |
| SRC-003 | raw/2026-11-19-rss-tos-research.md | RSS／ToS 可行性研究（含實測 4 次 GET） | 研究 agent（非 PO） | 2026-11-19 | Extracted | 以 [事實]／[推論]／[未知] 標註；未知項全數進 clarification-log；ToS 二手轉述部分未逐字驗證 |
| SRC-004 | raw/2026-11-19-010-code-survey.md | 010 程式盤點（subagent 回報，未經主對話逐行驗證） | subagent | 2026-11-19 | Needs Review | 行號與路徑為盤點摘要，僅作為「相容性限制」的依據；進 Spec Kit 前需實作階段重新查證 |
| SRC-005 | raw/2026-11-19-paid-preview-analysis.md | 僅預覽判斷分析（本機兩份 feed 共 40 篇，只讀 XML；含 [事實]／[推論]） | agent 產出（非 PO；PO 只對結果做總括確認「結果正確，011要繼續。」，未逐篇回報） | 2026-11-19 | Extracted | Q-103 判斷規則的依據；內含字數數字有未解釋的落差（未解決），本基線不引用具體字數；「Read more 尾端＝僅預覽」是推論、非站方保證 |
## Notes

- 本功能所有 raw 來源皆已列於此表。raw/ 內檔案未被改寫。
- SRC-002 為整理稿而非逐字稿；決定若與 PO 記憶不符，以 PO 當面更正為準（Draft 審閱時請 PO 核對）。
