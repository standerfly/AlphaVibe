# Extracted Requirements: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Last Updated:** 2026-10-30

## Candidate Functional Requirements

- CFR-01 系統自動取得 PO Gmail 信箱中國泰綜合證券寄出的台股日對帳單（寄件人
  `e-notification@ebill1.cathaysec.com.tw`、主旨「國泰綜合證券日對帳單」），PO 不需
  手動操作。（SRC-001 決策 1～3、SRC-002）
- CFR-02 系統開啟加密的 PDF 附件（密碼為身分證字號，英文字母大寫）。（SRC-002）
- CFR-03 從「交易明細」區塊擷取每筆成交：成交日、商品名稱、類別（買／賣、市場）、
  股數、單價、成交金額、手續費、交易稅、委託書號，寫入 PO 的交易流水表。
  （SRC-002）
- CFR-04 交易明細只有股票名稱，系統須把名稱對應到代號（可參照同份對帳單的庫存
  明細，及既有名稱→代號解析）。（SRC-002、SRC-001 既有能力）
- CFR-05 同一筆成交（委託書號相同）不得重複寫入，包含與既有手動匯入（交易明細表、
  CSV）重疊的情況。（SRC-002、SRC-001 既有能力）
- CFR-06 從「庫存明細」區塊擷取完整持股（代號、名稱、集保股數）更新庫存。
  （SRC-001「兩種」、SRC-002）
- CFR-07 庫存明細沒有平均成本，系統須以既有資料決定成本。（SRC-002）
- CFR-08 寫入不需 PO 事前確認；完成後通知 PO 匯入結果。（SRC-001 決策 4）
- CFR-09 上線初期支援驗證：PO 提供手動申請的對帳單，與資料庫內容比對是否一致。
  （SRC-001 決策 5）
- CFR-10 美股（國泰複委託日對帳單）後續補入。（SRC-001 決策 6）

## Candidate Actors And User Goals

- PO（Stander）：不必再手動截圖／匯出，STND 與 claude.ai 查到的買賣與庫存每天自動是
  最新的。（SRC-001 背景）
- 國泰綜合證券（外部系統）：每交易日以 Email 寄送加密 PDF 日對帳單。（SRC-001、SRC-002）
- 排程系統（Mac launchd，正式環境 `AlphaVibe-prod`）：執行自動匯入。（SRC-001 既有能力）

## Candidate Success Criteria

- PO 在有成交的交易日，當晚不做任何操作，STND 已出現當天成交與更新後的庫存。
- 驗證期內，系統寫入的資料與國泰對帳單逐筆一致。
- 不產生重複的成交紀錄。

## Candidate Constraints And Assumptions

- 國泰無個人 API，Email 對帳單是唯一可自動化管道。（SRC-001 研究結論）
- 對帳單於交易日約 18:30 起寄送（樣本 19:12 寄達）。（SRC-001、SRC-002）
- 假設：未成交的交易日不寄日對帳單（待觀察確認）。
- 假設：庫存明細的集保股數已含當日未交割的成交（樣本觀察，待更多資料確認）。（SRC-002）
- 敏感資料：PDF 開啟密碼（身分證字號）與信箱存取憑證須妥善保管。（SRC-002）
- 正式環境在 PO 的 Mac 上執行；Mac 睡眠時排程可能延遲。（SRC-001 既有能力）

## Candidate Error Or Failure Behavior

- 當天沒收到對帳單、PDF 打不開、格式變動無法解析、名稱對不到代號、庫存與買賣紀錄
  推算不一致——皆需定義行為（見 product-spec Error Handling）。

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001 | Conflict | 「直接寫入、事後通知」與既有產品規則「未經確認不寫入」（alphavibe product-spec 場景 3）衝突 | Resolved | PO 明確決定本功能為例外：來源為券商官方對帳單（SRC-001 決策 4），記為 Q-001 |
| GAP-002 | SRC-002 | Unclear | 庫存明細與買賣紀錄推算的庫存不一致時，以哪個為準；平均成本從何而來 | Open | Q-002 |
| GAP-003 | SRC-001 | Unclear | 通知管道與內容 | Open | Q-003 |
| GAP-004 | SRC-002 | Unclear | 信箱存取與 PDF 密碼的保管方式是否可接受 | Open | Q-004 |
| GAP-005 | SRC-001 | Unclear | 驗證期多久、何時算通過 | Open | Q-005 |
