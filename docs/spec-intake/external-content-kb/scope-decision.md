# Scope Decision: 外部內容知識庫（YouTube／Podcast／文章）

**Feature Slug:** external-content-kb
**Last Updated:** 2026-11-25

## MVP In Scope

- 獨立的外部內容庫，收 YouTube、Podcast、文章三種來源的全文與中繼資料。
- 收件匣資料夾進件（`poc/data/inbox/`）：PO 說「匯入」即逐檔入庫，不經模型輸出；claude.ai 直接收全文僅作短文備援。
- 全文檢索（含 2 字中文詞，回傳命中片段）與依 ID 取全文。
- 每筆固定標註來源資訊與「作者個人觀點，未經查證」。
- 去重（行為見 Q-003）。
- 摘要分開存放、PO 確認後才入庫（細節見 Q-005）。
- 更新全文與刪除單筆（見 Q-013）。
- 查詢工具在台股、美股兩連接器都提供（含唯讀端）；寫入類只在 claude.ai 非唯讀連接器（Q-009）。
- 專案指示更新：討論投資先搜尋、三句話使用說明、AI Studio prompt 範本（Q-020、Q-021）。
- 驗收案例：EP466。

## Out Of Scope

- 評論庫（Layer 3）既有 3 筆 EP466 摘要的刪除或遷移（PO 另行決定，Q-015）。
- 修改 010 articles.db、011 substack.db 的任何表或程式。
- 自動寫入未經 PO 確認的摘要或觀點。

## Deferred Or Later

- 自動抓 YouTube 字幕、Whisper 轉錄（SRC-001 明列後續選項）。
- 網頁上傳端點（Q-014：PO 決定第一版不做）。
- 手機經 iCloud 存檔（待實測 macOS 權限）。
- 跨庫統一搜尋（Q-012）。
- Podcast RSS 自動追蹤、YouTube 頻道訂閱。

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| external-content-kb | 獨立內容庫＋匯入核心＋收件匣進件＋檢索＋摘要確認＋更新／刪除 | 無（不依賴 011 元件） | 1 | Draft |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 獨立新庫，不併 010／011／評論庫 | SRC-001, SRC-003 | Stander | 2026-11-19 | 語意不合、測試與連接器耦合風險高；評論庫 trigram 搜不到 2 字中文 |
| 共用核心；進件改為收件匣資料夾 | SRC-002 | Stander | 2026-11-25 | PO 兩種環境都會用；收件匣讓兩環境同一流程且不耗輸出 token；不做網頁上傳（開發量與登入成本） |
| 不依賴 011 元件 | SRC-003 | Claude（建議，待 PO 認可） | 2026-11-20 | 011 尚未全部結清、未產生 tasks |
