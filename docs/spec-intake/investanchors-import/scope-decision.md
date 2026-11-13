# Scope Decision: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-13

## MVP In Scope

- 自動登入 investanchors.com 並取得「台股」「美股」「週報」文章全文（含圖片）。
- 歷史全量回補（分批）＋之後定期取新文章，排程不定時。
- 以文章 ID/網址防重複；略過置頂公告。
- 全文可被檢索與讀取（供 claude.ai／Claude Code 查詢後與 PO 討論；介面見 Q-005）。
- 不超過網站兩台裝置上限（Q-011）。
- 失敗通知（Telegram）與可續跑。

## Out Of Scope

- 自動 LLM 抽取個股立場（PO：先存全文）。
- 「產業」「總經」「最愛」分類。
- 註冊、付費、取得非 PO 帳號權限的內容。
- 對外分享或再發布文章內容。

## Deferred Or Later

- 文章留言（Q-010）；圖片 OCR／表格數值化（Q-007）。
- STND 前端閱讀頁、LLM 自動摘要與立場抽取（Layer 2 寫入需人工確認，FR-003）。
- 「產業」「總經」分類擴充。

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| investanchors-import | 登入＋抓取＋儲存全文＋排程＋通知（單一 feature） | Playwright（沿用機票 scraper 架構）、Telegram 通知、鑰匙圈 | 1 | Draft |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 範圍＝台/美/週報 | SRC-001 | Stander | 2026-11-12 | PO 明確指定 |
| 歷史全量＋分批慢抓 | SRC-001 | Stander | 2026-11-12 | 避免被網站阻擋 |
| 先存全文不做自動抽取 | SRC-001 | Stander | 2026-11-12 | 之後由 PO 與 LLM 討論，降低初期成本 |
