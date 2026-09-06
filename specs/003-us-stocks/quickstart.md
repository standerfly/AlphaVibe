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

## 部署後的驗收重點（不要只測「有沒有報錯」）

- 確認美股功能的任何查詢/寫入路徑，實際上完全碰不到 `alphavibe.db`／
  `KBStore`／既有 `mcp__alphavibe-kb__*` 工具（FR-015/016 的核心要求，
  抽查程式碼 import 語句即可驗證）
- 手動觸發一次排程腳本，確認額度用盡情境下「未更新（無額度）」與
  「資料不足」兩種狀態不會混淆（FR-017 是這次規劃修訂最容易做錯的地方）
- 交易截圖匯入流程結束後，確認暫存檔真的被刪除、沒有殘留在任何持久化
  位置（FR-004）
