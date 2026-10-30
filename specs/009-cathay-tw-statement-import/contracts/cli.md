# CLI Contracts: 國泰台股日對帳單 Email 自動匯入

本功能不新增 HTTP API 或 MCP 工具；對外介面是兩支命令列程式（排程與 PO 手動使用）。

## 1. `poc/kb-mcp/statement_import.py`（每日自動匯入）

```text
python3 statement_import.py [--data-dir DIR] [--days N] [--dry-run]
python3 statement_import.py --rerun MESSAGE_ID_OR_DATE [--data-dir DIR]
python3 statement_import.py --from-file PDF [--data-dir DIR] [--dry-run]
```

| 參數 | 說明 |
|---|---|
| `--data-dir` | 資料目錄；省略＝`<本檔>/../data`（正式環境經 symlink 指向正式庫） |
| `--days` | 往回找幾天內的信（預設 14） |
| `--dry-run` | 只解析與計算，不寫入、不通知，印出將寫入的內容摘要 |
| `--rerun` | 重新處理一份 `partial`／`failed` 的對帳單（以 message_id 或對帳單日期指定；FR-014） |
| `--from-file` | 處理本機 PDF（開發／Mac 實測用，不連 Gmail；仍用鑰匙圈的 PDF 密碼） |

- 結束碼：0＝完成（含部分完成與個別對帳單失敗，失敗已記錄並通知）；1＝信箱連線或設定錯誤。
- 標準輸出：每份對帳單一行摘要；不印任何密碼、身分證字號、帳號。
- 每次執行寫一筆 `statement_import_runs`。

## 2. `poc/kb-mcp/statement_reconcile.py`（唯讀比對工具，FR-015）

```text
python3 statement_reconcile.py [PDF] [--folder DIR] [--data-dir DIR] [--json]
```

| 參數 | 說明 |
|---|---|
| `PDF` | 指定交易明細表 PDF；省略＝`--folder` 中修改時間最新的 `.pdf` |
| `--folder` | 預設 `/Users/stander/STND-對帳單` |
| `--data-dir` | 同上 |
| `--json` | 輸出 JSON（給 Claude 讀）；預設為人看的文字報告 |

- **不寫入資料庫、不修改／刪除資料夾內任何檔案**（以唯讀模式開啟 SQLite）。
- 比對範圍：只比對交易明細表期間（第一筆～最後一筆成交日）內的資料庫成交。
- 輸出三類：資料庫重複、資料庫缺漏、數值不一致（日期、代號、買賣別、股數、價格）；全部一致時輸出「全部一致」。
- 結束碼：0＝比對完成（不論有無差異）；2＝PDF 打不開或格式無法辨識。

## 3. Telegram 通知訊息（FR-008）

成功（範例，數字為示意）：

```text
📒 國泰日對帳單 2026-11-03 已匯入
成交 2 筆寫入（跳過重複 0）・庫存 15 檔
⚠️ 庫存與買賣紀錄推算不同：2308 推算 65／對帳單 70
⚠️ 平均成本算不出來：6826
```

部分完成／失敗：

```text
⚠️ 國泰日對帳單 2026-11-03 部分完成：1 筆成交名稱對不到代號（XXX），其餘已寫入
❌ 國泰日對帳單 2026-11-03 匯入失敗：PDF 格式無法辨識（可能改版），未寫入任何資料
```
