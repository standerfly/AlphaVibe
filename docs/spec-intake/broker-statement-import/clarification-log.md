# Clarification Log: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Last Updated:** 2026-10-30

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 寫入要不要先經 PO 確認？（與既有規則「未經確認不寫入」衝突） | SRC-001 | Scope／workflow | Answered | 直接寫入、事後通知 PO。本功能是既有規則的明確例外，理由：資料來源是券商官方對帳單 | Stander | 2026-10-30 |
| Q-002 | 庫存以誰為準？對帳單「庫存明細」的集保股數，與買賣紀錄推算的庫存不一致時怎麼辦？平均成本從哪來？ | SRC-002 | Data | Blocking | **建議**：股數以對帳單庫存明細為準（它是券商帳上的完整持股，含配股、減資）；平均成本沿用 STND 既有成本，新出現的股票用買賣紀錄推算，算不出來就留空並在通知中標示；兩者不一致時照樣寫入，但在通知中列出差異 | Stander | — |
| Q-003 | 匯入完成後用什麼方式通知、通知哪些內容？ | SRC-001 | Observability | Blocking | **建議**：用既有的 Telegram 通知（機票追蹤已在用），每次匯入傳一則摘要：對帳單日期、寫入幾筆成交、庫存幾檔、有沒有差異或錯誤；沒有成交的日子不通知 | Stander | — |
| Q-004 | Mac 要能自動讀 Gmail、自動開 PDF，就得在 Mac 上保存兩樣敏感資料：Gmail 的「應用程式密碼」與身分證字號。這樣的保管方式可以接受嗎？ | SRC-002 | Security／privacy | Blocking | **建議**：兩者只存在 Mac 的「鑰匙圈」，不進 repo、不寫進設定檔、不出現在對話；Gmail 用唯讀方式存取，只讀國泰寄來的對帳單 | Stander | — |
| Q-005 | 驗證期要多久、怎樣算通過？ | SRC-001 | Success criteria | Blocking | **建議**：上線後 2 週或累積 5 份有成交的對帳單（先到者為準），PO 手動申請對應期間的對帳單交給 Claude 逐筆比對，全部一致即結束驗證期；任何不一致都要找出原因修正後重新計算 | Stander | — |
| Q-006 | 沒有成交的交易日，國泰還會寄日對帳單嗎？ | SRC-002 | Workflow | Non-blocking | 待觀察。若不寄，庫存只在有成交的日子更新（配股等變動要等下次成交或月對帳單才反映） | Stander | — |
| Q-007 | 庫存明細的集保股數，是否已含當天成交但尚未交割的股數？ | SRC-002 | Data | Non-blocking | 樣本顯示已含（10/29 買進、11/02 交割的 4 股已列入）；需更多天的資料確認，開發與驗證期驗證 | Claude | 2026-10-30 |
| Q-008 | 訂閱生效前的歷史對帳單要不要回補？ | SRC-001 | Scope | Non-blocking | 不回補。電子對帳單 2026-10-29 起才有，更早的紀錄維持既有手動匯入的資料 | Claude 建議 | 2026-10-30 |
| Q-009 | 美股（國泰複委託日對帳單）格式 | SRC-001 | Scope | Deferred | 等 PO 下次美股交易、收到信後提供樣本，再另開規格補入 | Stander | 2026-10-30 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
