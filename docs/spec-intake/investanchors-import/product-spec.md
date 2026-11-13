# Product Spec: 定錨產業筆記文章自動匯入

**Status:** Draft
**Feature Slug:** investanchors-import
**Function Branch:** function/investanchors-import
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** N/A
**Acceptance Evidence:** N/A

## Problem And Goal

PO 訂閱「定錨產業筆記」（需登入的付費網站，每週報告與個股/產業筆記）。目前 STND 沒有任何自動取得機制，只能手動貼入（FR-001），FR-002 的 email 解析也未實作，且定錨內容不是 email，是登入後網頁。目標：讓系統**代 PO 登入並自動取得台股、美股、週報三類文章全文**存進知識庫，PO 之後可在 claude.ai／Claude Code 中檢索並與 LLM 討論，不必每天手動複製貼上。

## Business Context And Priority

- Priority: 中（補上 FR-002 缺口，餵養 Layer 3 資訊來源）
- Timing: 無硬性期限；歷史回補為一次性、之後定期
- Business value: 省去手動貼文；歷史筆記可全文檢索

## Actors

- PO（Stander）：訂閱者，檢索與討論文章。
- 排程（系統）：以 PO 帳號登入並取文。

## MVP Scope

### In Scope

- 自動登入、取得「台股」「美股」「週報」文章全文與圖片。
- 歷史全量回補（分批）＋定期取新文章，排程不定時。
- 文章 ID 防重複、略過置頂公告。
- 全文檢索；失敗通知；可續跑。

### Out Of Scope

- 自動 LLM 抽取／寫入 Layer 2 立場、產業與總經分類、非 PO 帳號、對外分享。

### Deferred

- 留言、圖片 OCR、STND 閱讀頁、自動摘要（見 scope-decision.md）。

## Functional Requirements

- FR-001 系統以 PO 的會員帳號自動登入；帳密不出現在 repo、對話或日誌。
- FR-002 系統能列出「台股」「美股」「週報」三類文章，並取得每篇的標題、發布日期、分類標籤、網址、全文、內文圖片。
- FR-003 一篇文章以其網址/文章 ID 為唯一身分；重複執行或跨分類出現不會產生重複紀錄，且分類標籤可累加。
- FR-004 置頂公告（如標題以「【公告】」開頭）不匯入。
- FR-005 首次執行回補全部歷史文章；回補以小批次、不固定間隔進行，每批有上限，中斷後從未完成處續跑。
- FR-006 回補完成後定期取得新文章；抓取維持低頻、分散時段，不對網站造成明顯負載。
- FR-007 已匯入文章的全文可被關鍵字檢索，結果可回溯到原文網址與日期。
- FR-008 登入失敗、被網站阻擋、頁面結構改變時，系統中止當次、不刪除既有資料，並通知 PO（Telegram）。
- FR-009 系統不得改變 PO 在網站上的資料（不留言、不按最愛、不變更帳號設定）；是否影響「已讀」狀態見 Q-004。
- FR-010 文章內容僅供 PO 個人使用，不得經無驗證的公開網址提供，不對外分享（Q-008；條款依據 SRC-004）。
- FR-011 排程登入不得使 PO 帳號超過網站「同一帳號最多兩台裝置或瀏覽器上線」的限制（Q-011）。
- FR-012 PO 能在 claude.ai／Claude Code 對話中搜尋並讀取已匯入文章全文，作為與 LLM 討論的依據（Q-005）。

## Acceptance Scenarios

1. 首次回補：給定帳密已存入鑰匙圈，執行後分多批取得三類文章，完成時與網站三類清單逐篇核對無缺漏（去重後）。
2. 重跑：立即再執行一次，新增 0 篇、無重複。
3. 新文章：網站新增一篇台股週報後，下次定期執行取得該篇，且不重抓舊篇。
4. 置頂公告：「【公告】會員權益及常見問題」不出現在匯入結果。
5. 重疊分類：同時屬週報與台股的文章只存一筆、帶兩個標籤。
6. 登入失敗：密碼錯誤時當次中止、既有文章不變、PO 收到通知。
7. 被擋：連續逾時／回傳非預期頁面時中止並退避，PO 收到通知，不反覆重試。
8. 檢索：以個股名稱（如「環宇-KY」）查詢，可得含該字樣的文章與原文連結。

## Success Criteria

- 回補後與網站三類清單逐篇核對無缺漏（去重後；截圖上的紅色數字可能是未讀數，不作為篇數依據）。
- 連續一週的定期執行無重複、無遺漏新文章。
- 失敗情境 100% 有通知且既有資料不損。
- 全程未造成 PO 帳號被鎖、被停用或遭網站限制存取（含兩台裝置上限）。

## Constraints And Assumptions

- 登入僅 email＋密碼，無 captcha／雙因素（SRC-001，截圖觀察）。
- 雲端沙箱無登入狀態，實測只能在 PO 的 Mac。
- 內文表格以圖片呈現，圖內數字不可全文檢索（OCR 為 Deferred）。
- 無附件／PDF（PO 確認，SRC-003）。
- 台股與美股在 STND 為獨立系統，匯入後兩者須可分別被查詢（Q-005）。
- 付費內容、僅個人使用（Q-008，待確認）；條款允許個人使用目的之瀏覽及下載、禁止散布（SRC-004）。
- 同一帳號最多兩台裝置或瀏覽器上線，超過網站可停用帳號（SRC-004）。
- 清單上的日期不可靠（置頂公告為 2026-12-30、週報日期可晚於實際發布日），新舊判斷只靠文章 ID。
- 清單分頁方式、文章網址形態、登入狀態有效期尚未知，須在 Mac 探查（Q-013）。

## Dependencies

- Playwright（沿用 `poc/kb-mcp/scraper/` 架構）、macOS 鑰匙圈、Telegram 通知、launchd 排程。
- investanchors.com 頁面結構穩定（外部依賴，改版會中斷）。

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 帳號因裝置數超限被停用 | 當次中止，停止後續排程直到 PO 處理 | Telegram 通知 | PO 聯絡網站或調整使用裝置後手動恢復 | Yes |
| 登入失敗（密碼錯/帳號鎖） | 當次中止，不重試 | Telegram 通知 | PO 更新鑰匙圈密碼後重跑 | Yes |
| 被擋／連續逾時 | 中止並拉長下次間隔 | Telegram 通知 | 稍後自動或手動續跑 | Yes |
| 頁面結構改變（取不到內文） | 該篇標記失敗、不寫入殘缺全文 | Telegram 通知＋失敗清單 | 修爬蟲後重跑失敗清單 | Yes |
| 單篇圖片下載失敗 | 文章仍存，圖片標記缺 | 日誌 | 重跑時補圖 | No |
| 回補中斷（Mac 關機等） | 已存文章保留 | 無 | 從未完成處續跑 | No |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Draft | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| Workflow Diagram | Yes | Draft | supporting-artifacts/workflow-and-states.md | 多步驟流程＋批次狀態 |
| Integration/Data/Security Note | Yes | Draft | supporting-artifacts/integration-data-security-note.md | 第三方登入整合、資料生命週期、憑證與版權、批次部分失敗、查詢介面 |

## Source Decisions

- 範圍、回補、先存全文：Q-001～Q-003（PO 2026-11-12）。
- 未決：Q-004、Q-005、Q-008、Q-011（Blocking）；Q-006、Q-007、Q-009、Q-012 為建議值待確認；Q-010 Deferred；Q-013 為技術探查項。
- 2026-11-13 複審：補查網站條款（SRC-004）、更正篇數假設、補上查詢介面與裝置上限。
