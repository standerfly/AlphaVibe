# Intake Index: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
**Last Updated:** 2026-09-23

| Source ID | Source | Type | Owner | Source Date | Status | Notes |
|-----------|--------|------|-------|-------------|--------|-------|
| SRC-001 | raw/S01-po-conversation-2026-09-22-23.md | 對話紀錄 | Stander | 2026-09-22~23 | Extracted | PO 原話逐字保留。含初始需求、四項範圍選擇、成本約束、核心痛點澄清、行程分散需求、時間範圍與外站偏好、分頁範圍決策 |
| SRC-002 | raw/S02-po-screenshot-jumpzone-4segment-prague.png | 截圖 | Stander | 2026-09-22 | Extracted | 「跳區外站四段票」對照圖：台北↔布拉格一般買法 44,794 vs BKK 四段票 31,036，第2、3段為完全相同班機。含警語「第一段一定要搭乘！需再買TPE-BKK單程機票」。介面為荷蘭文 |
| SRC-003 | raw/S03-po-screenshot-bkk-mxp-leg4-0312.png | 截圖 | Stander | 2026-09-22 | Extracted | BKK-TPE-MXP-TPE-BKK，第4段 3/12，TWD 15,225 |
| SRC-004 | raw/S04-po-screenshot-bkk-mxp-leg4-0324.png | 截圖 | Stander | 2026-09-22 | Extracted | 同上四個班機，僅第4段改為 3/24，TWD 18,564。與 SRC-003 構成「第4段日期單獨造成 21.9% 價差」的對照證據 |
| SRC-005 | raw/S05-research-notes-pointer.md | 既有文件（指標） | Claude | 2026-09-22~23 | Extracted | 指向 docs/research/2026-09-22-ex-station-4segment-ticket-search.md（943 行）。含票規查證、資料源盤點、封鎖速率實測、實際票價結果。刻意不複製內容以免分岔 |

## 素材品質備註

- SRC-001 為對話紀錄，PO 陳述多為口語，部分需求須經 clarification 轉譯為可測條件
- SRC-002~004 為 PO 自行找到的真實票價，是本功能唯一的**外部價格錨點**，
  用於驗證系統查到的價格是否可信
- SRC-005 指向的研究筆記含已實測結論（含三次被記錄下來的推論失誤），
  其「未驗證假設」小節應視為待辦而非事實
