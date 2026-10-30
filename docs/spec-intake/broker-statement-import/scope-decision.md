# Scope Decision: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Last Updated:** 2026-10-30

## MVP In Scope

- 自動讀取 PO Gmail 中的國泰台股日對帳單 Email 與加密 PDF 附件。
- 擷取交易明細，寫入台股交易流水表（含手續費、委託書號防重複、名稱→代號）。
- 擷取庫存明細，更新台股庫存。
- 直接寫入、事後通知 PO。
- 驗證期：PO 手動申請的對帳單，與資料庫逐筆比對。
- 失敗時的通知與手動補救方式。

## Out Of Scope

- 程式化下單或任何會改變券商帳戶的動作。
- 自動登入國泰網頁（樹精靈）擷取資料。
- 成交回報 Email（日對帳單已涵蓋，PO 未訂閱）。
- 月對帳單（MVP 不用；日對帳單已有完整庫存）。
- 其他券商。

## Deferred Or Later

- 美股：國泰複委託日對帳單（Q-009，等樣本）。
- 歷史對帳單回補（Q-008）。
- 用月對帳單做每月庫存核對（日對帳單已有庫存明細，視驗證期結果再決定）。

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| cathay-tw-statement-import | 國泰台股日對帳單 Email 自動匯入（交易＋庫存＋通知＋驗證期） | 無 | 1 | Draft |
| cathay-us-statement-import | 國泰複委託（美股）日對帳單自動匯入 | cathay-tw-statement-import；PO 提供樣本 | 2 | Deferred |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 用日對帳單 Email，不用 API | SRC-001 | Stander | 2026-10-30 | 國泰無個人 API；Email 是唯一可自動化的官方管道 |
| 只用日對帳單、不訂成交回報 | SRC-001 | Stander | 2026-10-30 | 日對帳單同時有交易與完整庫存，少一種格式就少一個出錯點 |
| 直接寫入、事後通知 | SRC-001（Q-001） | Stander | 2026-10-30 | 來源是券商官方對帳單；PO 的目標是「不用動手」 |
| 台股先做、美股延後 | SRC-001 | Stander | 2026-10-30 | 只有台股樣本；美股格式不同 |
| 驗證期由 PO 手動提供對帳單比對 | SRC-001 | Stander | 2026-10-30 | 直接寫入少了事前把關，以上線初期逐筆比對補足 |
