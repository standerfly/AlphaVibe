# Quickstart: 美股獨立投資系統

**Feature**: `specs/003-us-stocks/spec.md`

給接手實作或驗收這個功能的人（含未來 session）的快速上手指南。

## 這個功能是什麼

STND 新增獨立「美股」分頁：截圖匯入交易、股價走勢圖疊加買賣點位、研究
筆記/投資立場記錄、關注條件監控（每日排程刷新+Telegram推播）。**與既有
台股系統在分頁、資料表、查詢管道三層完全獨立**，不共用任何程式碼或資料。

## 開發前必讀

1. `specs/003-us-stocks/spec.md` — 完整需求（3個User Story、17條FR）
2. `specs/003-us-stocks/research.md` — 5項關鍵技術決策與依據（尤其
   §3「交易截圖辨識不需要OCR」跟§1「資料庫要開全新獨立db檔案」，這兩點
   直接決定實作路線，不要憑直覺假設）
3. `specs/003-us-stocks/data-model.md` — 4張新表的完整schema
4. `specs/003-us-stocks/contracts/mcp-tools.md` — 9個新MCP工具規格
5. `docs/spec-intake/us-stocks/` — pre-spec 階段的完整決策脈絡（含
   Q-001~Q-004及第三輪修訂），想知道「為什麼是這樣設計」查這裡

## 本地驗證方式（實作完成後）

比照既有 `poc/kb-mcp/tests/` 與 `app/tests/test_smoke.py` 的模式：

```bash
# 儲存層測試（新增 test_us_stock_store.py 後）
python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"

# FastAPI router 深度比對測試（若有新增 app/tests 對應測試）
ALPHAVIBE_DATA_DIR=<獨立測試庫路徑> .venv/bin/python3 -m app.tests.test_smoke
```

**務必**指定獨立的 `ALPHAVIBE_DATA_DIR`（例如 `poc/data-test/`，已
gitignore），**絕對不要**指向 `poc/data/`（正式庫）——這是本 repo
2026-08-22 資產表污染事故的教訓，見 CLAUDE.md 教訓紀錄。

## 排程腳本本地測試

`us_stock_scan.py` 部署後由 launchd 每日觸發，本地開發時可以直接手動
跑一次確認邏輯（比照 `market_scan.py --trigger scheduled` 的 CLI 模式）：

```bash
python3 poc/kb-mcp/us_stock_scan.py --trigger manual
```

## 已知的技術待辦（非阻塞，留待實作階段解決）

- 備援報價來源最終選定（Alpha Vantage 或 yfinance）——research.md §1
  已列出兩者利弊，需要在寫 `us_stock_price_client.py` 時定案
- HTTP client 函式庫沿用 `finmind_client.py` 的既有慣例，實作前先看
  該檔案確認用的是哪個函式庫
- API 金鑰儲存方式——比照 `finmind_token.txt` 的既有先例，或改用環境變數，
  待實作時決定
- `metric_type` 的完整列舉值清單——依 FMP 實際可取得的基本面欄位定案

## launchd 部署步驟（`us_stock_scan.py` 每日排程）

比照既有 `com.alphavibe.marketscan.plist` 的先例（見
`poc/kb-mcp/README.md`「排程服務」一節）——**這個 repo 從來沒有 plist
範本檔進版控**，plist 是直接手動建在使用者機器上的獨立檔案，這裡只寫
操作步驟，不在 repo 內建立範本。

1. 建立 `~/Library/LaunchAgents/com.alphavibe.usstockscan.plist`，內容
   比照下列骨架（`StartCalendarInterval` 用 `research.md` §4 建議的
   台北時間 06:00，跟既有 `marketscan` 的 02:00、`moduled` 的 17:00
   錯開，避免排程互相搶佔系統資源）：

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.alphavibe.usstockscan</string>
     <key>ProgramArguments</key>
     <array>
       <string>/usr/bin/python3</string>
       <string>/Users/stander/My_project/AlphaVibe/poc/kb-mcp/us_stock_scan.py</string>
       <string>--trigger</string>
       <string>scheduled</string>
     </array>
     <key>EnvironmentVariables</key>
     <dict>
       <key>ALPHAVIBE_DATA_DIR</key>
       <string>/Users/stander/My_project/AlphaVibe/poc/data</string>
     </dict>
     <key>StartCalendarInterval</key>
     <dict>
       <key>Hour</key><integer>6</integer>
       <key>Minute</key><integer>0</integer>
     </dict>
     <key>StandardOutPath</key>
     <string>/Users/stander/Library/Logs/alphavibe-us-stock-scan.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/stander/Library/Logs/alphavibe-us-stock-scan.log</string>
   </dict>
   </plist>
   ```

   `FMP_API_KEY` 若要用環境變數而非 `poc/data/fmp_token.txt`（見
   `us_stock_price_client.py` 的 token 讀取優先序），一併加進
   `EnvironmentVariables`——但金鑰本身不要寫進任何進版控的檔案，這份
   quickstart 只示範結構，實際 plist 由使用者在自己機器上手動填值。

2. 載入排程（不是 `RunAtLoad`+`KeepAlive` 常駐服務，是跑一次就結束的
   批次工作，比照 `marketscan` 的既有定位）：

   ```bash
   launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.alphavibe.usstockscan.plist
   ```

3. 改排程時間要重新載入才會生效（`launchctl kickstart -k` 只重啟已載入
   的定義，**不會**重讀 plist 內容——比照 `marketscan` 同樣的坑）：

   ```bash
   launchctl bootout gui/501/com.alphavibe.usstockscan
   launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.alphavibe.usstockscan.plist
   ```

4. 想立刻測試一次、不等明天 06:00（這種情境不是要重讀時間，用
   `kickstart` 沒問題）：

   ```bash
   launchctl kickstart -k gui/501/com.alphavibe.usstockscan
   ```

   log 在 `~/Library/Logs/alphavibe-us-stock-scan.log`。

**這一步（Foundational，Phase 2）不會真的建立或部署這份 plist**——上面
是給之後真正要上線排程時使用的步驟文件，`us_stock_scan.py` 本身可以先
用「本地驗證方式」一節的手動 CLI 呼叫測試邏輯，不需要等 plist 部署好。

## 部署後的驗收重點（不要只測「有沒有報錯」）

**以下三項已在 2026-09-07~08 實作階段由主 session 獨立複驗過（不是實作者
自報），細節見對應 commit message：**

- 確認美股功能的任何查詢/寫入路徑，實際上完全碰不到 `alphavibe.db`／
  `KBStore`／既有 `mcp__alphavibe-kb__*` 工具（FR-015/016 的核心要求，
  抽查程式碼 import 語句即可驗證）——✅ 已驗證，Phase 1-5 每一輪都重新
  grep 過一次
- 手動觸發一次排程腳本，確認額度用盡情境下「未更新（無額度）」與
  「資料不足」兩種狀態不會混淆（FR-017 是這次規劃修訂最容易做錯的地方）
  ——✅ 已驗證（Phase 5），需要真的構造「上次評估是過去某天、今天跳過」
  的情境才測得出來，直接呼叫評估方法測不到這個 bug（第一版自寫驗證腳本
  就犯過這個錯，見 commit 2c9416b 說明）
- 交易截圖匯入流程結束後，確認暫存檔真的被刪除、沒有殘留在任何持久化
  位置（FR-004）——✅ 已確認**這一項在目前實作中無需額外處理**：
  `research.md` §3 的架構決定是「截圖辨識發生在 Claude 對話中，圖片本身
  從未送到後端」，所以後端程式碼裡完全沒有暫存截圖檔案的邏輯（已 grep
  `poc/kb-mcp/us_stock_*.py`／`app/routers/us_stocks.py`／
  `UsStockImport.jsx` 確認無 `tempfile`／`UploadFile`／圖片副檔名相關
  程式碼），不是「有暫存邏輯但沒測到」，是從架構上就不存在這個風險點
