# Extracted Requirements: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-12

## Candidate Functional Requirements

- R-01 以 PO 自己的會員帳號（email＋密碼）自動登入 investanchors.com（SRC-001）。
- R-02 自動取得「台股」「美股」「週報」三類文章清單與全文（SRC-001、SRC-002）。
- R-03 一次性回補全部歷史文章；之後持續取得新文章（SRC-001）。
- R-04 排程不定時、分批抓取，避免被網站阻擋（SRC-001）。
- R-05 先儲存全文供搜尋；不自動做 LLM 抽取，之後由 PO 與 LLM 討論（SRC-001）。
- R-06 文章內含圖片（表格以圖片呈現）；需保留（SRC-003）。
- R-07 以文章網址/ID 防重複，置頂公告不當投資內容（SRC-002，Claude 推論）。

## Candidate Actors And User Goals

- PO（Stander）：不必每天手動登入複製貼上，就能在 STND／claude.ai 中檢索與討論定錨內容。
- 排程（系統）：代 PO 登入並取文。

## Candidate Success Criteria

- 歷史文章回補後，三類文章篇數與網站清單相符（SRC-002 顯示：週報31、台股17、美股32，含重疊待確認）。
- 重跑不產生重複文章。

## Candidate Constraints And Assumptions

- 登入僅 email＋密碼，截圖未見 captcha／雙因素（SRC-001）。
- 雲端沙箱無登入狀態，實測須在 PO 的 Mac（SRC-001）。
- 帳密只放鑰匙圈（專案既有慣例，009 教訓）。
- 付費會員內容，僅供 PO 個人使用（Claude 推論，待 PO 確認 Q-008）。
- 台股與美股在 STND 為獨立系統（CLAUDE.md 美股列）。

## Candidate Error Or Failure Behavior

- 登入失敗／被擋／網站改版 → 通知 PO、不刪既有資料、可續跑。

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-002 | Unclear | 「週報」與「台股」分類可能重疊（「台股產業週報」） | Open | 見 Q-006 |
| GAP-002 | SRC-002 | Unclear | 置頂公告日期（2026-12-30）晚於其他文章，日期不可當新舊判斷 | Open | 見 Q-009 |
| GAP-003 | SRC-002 | Unclear | 已讀粗細體是否會因爬蟲開啟文章而改變 | Open | 見 Q-004，需在 Mac 實測 |
