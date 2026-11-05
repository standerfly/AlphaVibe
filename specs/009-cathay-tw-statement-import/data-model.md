# Data Model: 國泰台股日對帳單 Email 自動匯入

**Feature**: 009-cathay-tw-statement-import
**Database**: 既有 `poc/data/alphavibe.db`（`KBStore`），沿用 `_MIGRATIONS` 機制擴欄；新增 3 張表。

## 既有表擴充

### trade_ledger（新增欄位）

| 欄位 | 型別 | 說明 |
|---|---|---|
| fee | REAL | 手續費（FR-003）；舊資料為 NULL |
| tax | REAL | 交易稅（FR-003）；舊資料為 NULL |

- `source_ref` 自動匯入時寫 `國泰日對帳單 YYYY-MM-DD`（FR-010 可區分來源）。
- `order_ref` 保留原始寫法；防重複一律比對 `normalize_order_ref()` 後的值（research R4）。

### holdings（不改結構）

- 自動匯入以對帳單日期為 `snapshot_date`、`source_ref`＝`國泰日對帳單 YYYY-MM-DD` 寫入完整持股。
- 若資料庫已有比對帳單日期更新的快照（FR-013），本次不寫庫存。

## 新增表

### statement_imports（每份對帳單一筆，FR-010）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK | |
| message_id | TEXT UNIQUE NOT NULL | 信件 Message-ID（本機檔案測試時為 `file:<路徑>`） |
| statement_date | TEXT NOT NULL | 對帳單日期 YYYY-MM-DD |
| status | TEXT NOT NULL | `processed`／`partial`／`failed` |
| trades_written | INTEGER | 本次新寫入成交筆數 |
| trades_skipped_duplicate | INTEGER | 因已存在而跳過的筆數 |
| holdings_count | INTEGER | 庫存檔數（未寫庫存時為 NULL） |
| holdings_written | INTEGER | 0/1，是否寫入庫存快照（FR-013） |
| detail_json | TEXT | 差異股票、對不到代號的成交、成本未知代號等 |
| error | TEXT | 失敗原因（不含任何密碼或個資） |
| processed_at | TEXT NOT NULL | |

狀態轉換：

```text
（新信）──► processed     全部成交與庫存寫入
       ├─► partial       有成交名稱對不到代號：其餘照常寫入（FR-004）
       └─► failed        PDF 打不開／格式無法辨識／寫入失敗：什麼都不留下（FR-009）
partial、failed ──(PO 手動重跑 --rerun)──► processed／partial／failed（FR-014）
processed ─（排程不再處理）
```

`failed` 的對帳單不寫 `statement_imports` 以外的任何資料。排程只跳過狀態為 `processed` 者；
`partial`／`failed` 會在之後的排程**自動重試**（暫時性錯誤可自行恢復、補上名稱對應後自動補寫，
重試具冪等性），同一份對帳單的同一類錯誤一天最多通知一次（`statement_alerts`）。`--rerun` 供 PO
在排程時間之外立即重跑。

### statement_import_runs（每次排程執行一筆，健康檢查用）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK | |
| started_at | TEXT NOT NULL | |
| finished_at | TEXT | |
| outcome | TEXT | `ok`／`mailbox_error`／`error` |
| statements_found | INTEGER | 本次發現的新對帳單數 |
| notify_failed | INTEGER | 0/1，Telegram 是否送失敗 |
| error | TEXT | |

### statement_alerts（通知去重）

| 欄位 | 型別 | 說明 |
|---|---|---|
| kind | TEXT NOT NULL | `cost_unknown`（每檔只通知一次）／`error`（同一錯誤一天一次） |
| key | TEXT NOT NULL | `cost_unknown`：股票代號；`error`：`日期|錯誤類別` |
| created_at | TEXT NOT NULL | |
| | | PRIMARY KEY (kind, key) |

## 解析結果（程式內部結構，不落地）

```text
DailyStatement
  statement_date: "YYYY-MM-DD"
  trades: [ {name, market(集/OT/興), action(買/賣), shares, price, amount, fee, tax, order_ref} ]
  holdings: [ {code, name, shares} ]     # 完整持股；可為空清單（全部出清）

ReconcileReport（比對工具輸出）
  period, statement_trades_count, db_trades_count
  duplicates_in_db: [ {normalized_ref, rows:[...]} ]
  missing_in_db:   [ {date, code/name, action, shares, price, order_ref} ]
  mismatched:      [ {order_ref, field, statement_value, db_value} ]
```

## 驗證規則

- 成交：股數 > 0、單價 > 0、類別必須含「買」或「賣」、委託書號非空。
- 庫存：代號 4～6 碼英數、股數 ≥ 0。
- 對帳單日期必須能從交割金額區塊取得，否則視為格式無法辨識。
