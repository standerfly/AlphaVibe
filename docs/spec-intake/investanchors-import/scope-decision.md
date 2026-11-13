# Scope Decision: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Last Updated:** 2026-11-13

## MVP In Scope

- 自動登入 investanchors.com 並取得「台股」「美股」「週報」文章全文（含圖片）；表格圖內容可供 LLM 讀取（Q-007）。
- 獨立文章庫＋搜尋／讀取單篇查詢工具，台美連接器分流（Q-005 選項B）。
- 每次跑完登出；新文章 Telegram 通知（Q-011、Q-012）。
- Gmail 新信觸發＋每週清單核對（Q-014）；失敗隔次重試（Q-015）；表格圖匯入時轉寫（Q-016）。
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

- 文章留言（Q-010）；表格數字結構化入庫（逐格成為可計算欄位）。
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
| 獨立文章庫＋查詢工具（選項B） | SRC-001 | Stander | 2026-11-13 | 維持台美獨立；防重複有唯一鍵 |
| 表格圖內容進 MVP | SRC-003 | Stander | 2026-11-13 | PO：表格數字是重點 |
| 跑完即登出、務必低頻 | SRC-004 | Stander | 2026-11-13 | 兩台裝置上限；避免被阻擋或停用 |
| 接受已讀副作用 | SRC-002 | Stander | 2026-11-13 | PO 同意 |
| Gmail 新信觸發，不每日掃網站 | SRC-005 | Stander | 2026-11-13 | 無新文章的日子零登入，最低頻 |
| 表格匯入時轉寫、用最低成本有效模型 | SRC-005 | Stander | 2026-11-13 | 表格數字可檢索；成本由 PO 決定取最低 |
