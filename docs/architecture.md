# STND 架構與使用方式（v1，2026-08-24）

> 讀者：任何要接手 STND（= 本 repo，AlphaVibe）開發或討論工作的人／session。
> 目的：不用重新爬程式碼就能搞懂「STND 現在長什麼樣、我該去哪裡改東西」。
> 視覺化版本（同一份資訊的 block diagram）：
> https://claude.ai/code/artifact/1e97dcdb-4e74-4b87-9bea-fb83455d4d54

## 一句話說明

**STND 不是獨立專案，是這個 repo（AlphaVibe）對外的產品名字。** 所有分頁——首頁、
儀表板、資產、相簿、未來可能的旅遊——全部住在同一個 repo 的 `app/`（FastAPI 後端）
與 `web/`（React 前端）裡，共用同一個資料庫、同一個部署單元。這是 2026-08-22
明文定案的決策（見 `CLAUDE.md` 「STND 分頁與程式碼位置」節），刻意不拆成多個 repo，
理由是同源部署可以省掉 CORS／auth 重新設計的成本。

## 分頁地圖

| 分頁 | 前端頁面 | 後端 router | 內容/資料來源 | 狀態 |
|---|---|---|---|---|
| 首頁 | `web/src/pages/Home.jsx` | `dashboard.py`（彙總其他分頁 API） | 本 repo | 已上線 |
| 儀表板 | `Dashboard.jsx`／`StockDetail.jsx` | `holdings.py`／`screen.py`／`market_scan.py`／`stock_detail.py`／`actions.py`／`holdings_import.py` | `poc/kb-mcp/`（未重寫既有邏輯） | 已上線 |
| 資產 | `Assets.jsx` | `assets.py` | `kb_store.py` 新增的 5 張表 | 已上線 |
| 相簿 | `Photos.jsx` | 尚無 | 未定 | 僅 MVP 空殼入口 |
| 旅遊 | 尚未建立 | 尚未建立 | 內容來自**另一個獨立專案** `/Users/stander/My_project/mytravel/`，但程式碼仍會建在本 repo | 未開始，整合深度待 PO 決定，不要預設 |

> `holdings_import.py` 是獨立 router（`app/main.py:81,95` 另外 import／include_router），
> 不是 `actions.py` 的一部分——`CLAUDE.md` 的分頁表目前沒列到這個檔案，屬已知文件落差。

## 前端架構

- **框架**：React 18.3（`web/package.json`），Vite 5 建置，`react-router-dom ^6.23.1`。
- **路由模式**：巢狀布局路由（layout route）。`App.jsx` 用
  `<Route element={<AppShell/>}>` 包住所有分頁路由；`AppShell.jsx` 用 `<Outlet/>`
  渲染當前分頁內容。
- **分頁清單的權威來源**：`web/src/components/AppShell.jsx` 的 `TABS` 常數
  （第 5-10 行）——導覽列上顯示哪些分頁、順序、圖示，都由這個陣列決定。目前只有
  4 個（首頁／儀表板／資產／相簿），「旅遊」還沒被加進來。
- **共用元件**：`AppShell.jsx`（導覽外殼＋Outlet）、`ThemeToggle.jsx`（深色/淺色）、
  `icons.jsx`、`api/client.js`（API 呼叫封裝）、`styles/tokens.css`+`styles/app.css`
  （配色/樣式）、`theme.js`（主題邏輯）、`main.jsx`（Vite 標準入口）。
- **建置產物**：`npm run build` → `web/dist/`，由後端同一個 process 掛載服務
  （見下方部署方式），不是獨立部署的靜態站台。

## 後端架構

- **框架**：FastAPI，`app/main.py` 為入口，`app/routers/*.py` 各自對應一個分頁的
  API（見上方分頁地圖）。
- **不重寫商業邏輯**：每個 router 直接 `import` 既有的 `poc/kb-mcp/*.py`
  （`kb_store.py`／`screener.py`／`report.py`／`frameworks.py`），這一層才是真正
  算資料、存資料的地方。`app/` 只是 HTTP 介面轉接層。
- **資料存取**：多數 router（`assets.py`／`actions.py`／`dashboard.py`／`holdings.py`／
  `holdings_import.py`／`market_scan.py`／`stock_detail.py`）透過
  `Depends(get_kb_store)`（`app/deps.py`）取得同一個 `KBStore` 連線，最終落到
  `poc/data/alphavibe.db`。
  `screen.py` **已查證（2026-08-24）：完全不碰這顆 DB**——它跟其他 router 共用同一支
  `_resolve_data_dir()`（沒有另開路徑解析邏輯、不存在繞過防呆的空隙），但這個
  `data_dir` 在 `screener.py` 整條呼叫鏈（`benchmark.py`／`finmind_client.py`／
  `fundamentals_client.py`／`twse_price_client.py`）裡唯一的用途是讀
  `finmind_token.txt`（FinMind API token 檔）；資料來源全部是即時打
  FinMind／TWSE 官方 API，四個下游模組 grep `kb_store|sqlite3|KBStore` 皆 0 命中。

## 資料層

- **單一 sqlite 檔**：`poc/data/alphavibe.db`（正式庫），路徑定義在
  `poc/kb-mcp/kb_store.py:333`。所有分頁共用同一顆資料庫，**沒有物理隔離**。
- **防呆機制（2026-08-22 新增，回應同日的資料庫污染事件）**：`app/deps.py` 的
  `_resolve_data_dir()`——沒有明確設定環境變數 `ALPHAVIBE_DATA_DIR` 就拒絕啟動；
  即使設定了，若指向正式路徑（`poc/data/`），還需要額外加
  `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 才允許寫入。
- **這道防呆擋的是「忘記設定環境變數」這類錯誤，不是把資料庫拆開**——只要還是
  同一顆 sqlite、同一個 repo，任何分頁的程式碼理論上都碰得到其他分頁的資料表。
  這是已知的結構性風險，不是要重新拆 repo（2026-08-24 已與 PO 確認保留現有決策），
  只是把殘留風險講清楚。

## 部署與存取

- **正式服務**：`uvicorn app.main:app`，port 8080，由
  `~/Library/LaunchAgents/com.alphavibe.reportserver.plist` 常駐。
- **對外網址**：`https://chancefully-erosive-lilian.ngrok-free.dev`
  （固定網址，`ngrok` 常駐服務轉發 8080；MCP 連接器走 `/mcp/<ALPHAVIBE_MCP_TOKEN>`）。
- **同源部署**：`web/` build 出的 `web/dist/` 由 `app/main.py` 用 `StaticFiles`
  掛載＋SPA fallback，前後端跑在同一個 uvicorn process、同一個 port，不需要
  CORS 設定。

## 開發與驗證指令

| 目的 | 指令 |
|---|---|
| 前端開發模式 | `cd web && npm run dev`（Vite dev server） |
| 前端建置 | `cd web && npm run build`（產出 `web/dist/`） |
| 後端煙霧測試（**務必**指定獨立測試庫） | `ALPHAVIBE_DATA_DIR=<獨立測試庫路徑，例如 poc/data-test/> .venv/bin/python3 -m app.tests.test_smoke` |
| 底層演算法 PoC 測試 | `python3 -m unittest discover -s poc/kb-mcp/tests` |
| 對正式庫寫入資產種子資料（一次性、人手動執行） | `poc/kb-mcp/seed_assets_once.py --data-dir poc/data` |

**絕對不要**讓煙霧測試的 `ALPHAVIBE_DATA_DIR` 指向 `poc/data/`（正式庫）——這正是
2026-08-22 污染事件的類型。

## 要開發／討論某個分頁，該去哪個資料夾開 session

| 想做的事 | 資料夾 |
|---|---|
| 投資（股票研究）、資產 | `/Users/stander/My_project/AlphaVibe`（本 repo） |
| 旅遊的「內容」——規劃行程、寫遊記 | `/Users/stander/My_project/mytravel`（獨立專案，純筆記） |
| 旅遊分頁的「程式碼」（尚未開始） | 也是 `AlphaVibe`，但要先決定整合 mytravel 資料的深度，不要預設 |

動手前先 `ListAgents` 檢查 `AlphaVibe` 資料夾底下有沒有其他 session 已經在跑，
避免重演 2026-08-22 那次「兩個 session 互不知情平行工作」的事故。

## 已知開放問題

- 相簿、旅遊分頁都還沒建，整合深度是留給 PO 的開放決策，不是技術問題。

**已解決（2026-08-24）**：
- ~~`screen.py` 的資料存取路徑沒有完全查證~~ → 已查證完全不碰 `alphavibe.db`，
  見「後端架構」節。
- ~~`CLAUDE.md` 分頁表沒列到 `holdings_import.py`~~ → 已補上該表格。

## 相關文件索引

- 專案總覽與教訓紀錄：`CLAUDE.md`
- 開發路線與進度（接手必讀）：`docs/spec-intake/alphavibe/roadmap.md`
- 需求基線：`docs/spec-intake/alphavibe/product-spec.md`
- 本文件的視覺化版本：見檔案開頭的 Artifact 連結

## 教訓紀錄

（依 `~/.claude/rules/40-maintenance.md` 的格式在此追加）

- 2026-08-24｜情境：使用者原本以為 STND 是要新建的獨立入口專案，要把 AlphaVibe
  裡的首頁、資產拆出去；查證 `CLAUDE.md` 才發現 2026-08-22 已經明文決定相反方向
  （全部留在同一個 repo）
  ｜教訓：涉及架構方向的請求，動手畫圖/寫方案前，先查 repo 內既有文件有沒有
  已經做過的決策，不要只憑對話裡轉述的摘要
  ｜動作：本文件建立，統一記錄查證後的架構事實，作為未來 session 的查證起點
