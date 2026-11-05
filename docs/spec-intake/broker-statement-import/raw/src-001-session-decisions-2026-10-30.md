# SRC-001：PO 與 Claude Code 對話紀錄摘要（2026-10-28 ～ 2026-10-30）

> 來源：Claude Code 雲端 session（claude.ai/code，session_017cx5dkCE3v3LKrufmYXAwn）。
> 由 Claude 依對話整理，PO 原話以「」標示。本檔為原始素材，不得改寫。

## 背景與動機

- PO 想把 STND 投資相關操作改成以 claude.ai 對話為主（2026-10-28 已完成：
  台股／美股兩個 claude.ai 連接器、`get_today_highlights` 工具，PR #36～#39）。
- PO 說明改用對話的原因：「因為STND無法自動匯入我的資料，導致我懶得使用。」
- claude.ai 對話只解決一半：匯入從「整理成固定格式貼表單」變成「截圖丟給
  Claude」，但仍需 PO 主動截圖上傳，不是自動。

## 需求範圍

- 自動匯入要省掉的資料：PO 回答「兩種」——買賣紀錄與庫存。
- PO 問：「買賣紀錄的結果就是庫存，對嗎?」Claude 回覆原則上是，但有三種情況會
  對不上：紀錄起點之前的持股、配股／分割／減資、成本算法差異；建議平常靠買賣
  紀錄、定期以券商庫存核對。
- 券商：台股與美股都在國泰證券（美股為國泰證券複委託）。PO 信箱為 Gmail。

## 研究結論（Claude 查證，2026-10-30）

- 國泰證券**沒有**開放給個人的程式交易／查詢 API（官網只有樹精靈 AP／WEB、
  隨身證券、國泰證券 App 等下單工具）。
- 國泰「雲端訂閱中心」提供 Email 寄送：成交回報（成交後即時＋盤後約 15:00 彙整）、
  證券日對帳單（每日 18:30 起）、證券月對帳單（每月 5 日前）、複委託日對帳單
  （交易完次一交易日 13:00 起）、複委託月對帳單（每月 10 日）。對帳單為加密 PDF，
  開啟密碼為身分證字號。
  來源：https://webap.cathaysec.com.tw/cloud_subscription/content/C_QA.aspx
- 集保 e手掌握可跨券商查庫存，但只能手動匯出 PDF，無 API。
- 自動登入樹精靈網頁抓資料：技術可行但不建議（憑證／密碼處理、改版即壞、可能違反
  使用條款）。

## PO 決策

1. 已向國泰申請電子對帳單（2026-10-30 已收到台股日對帳單）。
2. Claude 建議只用日對帳單、不必訂成交回報（日對帳單已同時涵蓋買賣與庫存），
   PO 未反對。
3. 附檔格式：PO 確認「附檔是 PDF」。
4. 寫入方式：PO 決定「直接寫入、事後通知我」（Claude 提出的另一選項為「先排進
   待確認清單，按一下才寫入」）。
5. 驗證期：PO 表示「初期我可以手動申請對帳單，讓你比對資料庫的內容是否正確。」
6. 範圍順序：台股先做；美股（複委託日對帳單）待 PO 下次美股交易收到信後提供
   樣本再補入。

## 已知相關既有能力（Claude 查證 repo）

- `poc/kb-mcp/trade_ledger_parser.py`：已能解析國泰「交易明細表」文字格式
  （含「集買」等類別寫法、委託書號防重複、股票名稱→代號解析）與國泰 App
  「已成交」CSV，寫入後呼叫 `holdings_sync.sync_holdings_from_trades()` 同步庫存。
- 網頁庫存匯入（`/api/holdings/preview`→`confirm`）有 avg_cost 沿用與增減差異比對；
  `get_holdings` 只讀最新一次快照（部分匯入會讓其他持股消失）。
- 正式環境 2026-10-29 起改跑獨立 worktree `AlphaVibe-prod`，排程以 macOS launchd 執行
  （見 CLAUDE.md、docs/architecture.md）。
- Telegram 通知模組 `poc/kb-mcp/notify.py` 已存在（機票追蹤等排程使用）。
