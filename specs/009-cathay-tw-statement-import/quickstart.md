# Quickstart: 國泰台股日對帳單 Email 自動匯入

> 給接手的人與 PO。所有指令在 PO 的 Mac 上執行；以 zsh 為準（迴圈用陣列）。

## 一次性設定（PO）

1. 安裝系統工具：`brew install qpdf poppler`
2. Gmail：開啟兩步驟驗證 → 建立「應用程式密碼」；Gmail 設定 → 轉寄和 POP/IMAP → 啟用 IMAP。
3. 存入鑰匙圈（`-w` 後不接值＝互動輸入，不留在 shell 歷史）：

   ```bash
   security add-generic-password -U -s stnd-statement-import -a gmail-address -w
   security add-generic-password -U -s stnd-statement-import -a gmail-app-password -w
   security add-generic-password -U -s stnd-statement-import -a pdf-password -w
   ```

   `pdf-password`＝身分證字號，英文字母大寫。第一次被程式讀取時若跳出鑰匙圈存取對話框，選「永遠允許」。

## 實測（上線前，不寫正式庫）

```bash
cd /Users/stander/My_project/AlphaVibe-prod
# 1) 日對帳單：從 Gmail 抓、只解析不寫入
/usr/bin/python3 poc/kb-mcp/statement_import.py --dry-run
# 1b) 或指定一份本機日對帳單 PDF（不連 Gmail）
/usr/bin/python3 poc/kb-mcp/statement_import.py --from-file ~/STND-對帳單/<日對帳單>.pdf --dry-run
# 2) 交易明細表比對（讀 /Users/stander/STND-對帳單/ 最新一份）
/usr/bin/python3 poc/kb-mcp/statement_reconcile.py
```

## 上線

1. 部署（`ops/deploy.sh`）。
2. 上線前整年度比對：PO 申請今年度交易明細表放進 `/Users/stander/STND-對帳單/`，執行比對工具，
   把結果交給 Claude；PO 確認修正清單後，**先備份正式庫**再修正。
3. 安裝排程：

   ```bash
   cp /Users/stander/My_project/AlphaVibe-prod/ops/launchd/com.alphavibe.statementimport.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphavibe.statementimport.plist
   ```

4. 驗證期：連續 3 次以比對工具比對一致即結束（FR-011）。

## 日常

- 立即重跑某份對帳單：`/usr/bin/python3 poc/kb-mcp/statement_import.py --rerun 2026-11-03`
- 查處理紀錄：`sqlite3 poc/data/alphavibe.db "select statement_date,status,error from statement_imports order by id desc limit 10"`
- 健康檢查（04:00）會在 30 小時沒執行、最近一份失敗、Telegram 送不出去時回報。

## 已知坑

- launchd 的 PATH 不含 Homebrew：程式會自己找 `/opt/homebrew/bin/qpdf` 等路徑。
- 真實日對帳單（2026-11-04 實測）轉出的文字**沒有**「交割金額／交易明細／庫存明細」標題字，
  解析器以各表表頭列（成交日期 交割日期／商品名稱 類別／代碼 股票名稱）切區塊。
- **同一天的對帳單只處理一次**（2026-11-11 首次匯入實測）：用 `--from-file` 匯入過、之後 Gmail
  又抓到同一天的信（message_id 不同）時，後者只登記為「同一天已處理過」、不重寫成交與庫存，
  否則會把當天手動補正的平均成本蓋回推算值。要強制重處理請用 `--rerun <日期>`；重跑同一天時，
  同日快照裡既有的成本（股數相同）會沿用，不會被推算值蓋掉。
- 國泰 PDF 改版會導致「格式無法辨識」：整份不寫入並通知，需更新 `cathay_statement_parser.py`。
- 測試一律用暫存資料目錄，絕不指向 `poc/data`。
