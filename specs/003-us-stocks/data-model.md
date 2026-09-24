# Data Model: 美股獨立投資系統

**Feature**: `specs/003-us-stocks/spec.md`
**Storage**: 獨立 SQLite 檔案 `poc/data/us_stocks.db`，透過新的
`USStockStore` 類別（`poc/kb-mcp/us_stock_store.py`）存取，
**不與 `poc/data/alphavibe.db`／`KBStore` 共用任何程式碼或資料表**
（見 `research.md` §1）。

## 1. us_trades（美股交易紀錄）

對應 spec.md「美股交易紀錄」實體、FR-002/003。

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| ticker | TEXT NOT NULL | 股票代號（例：NET） |
| trade_date | TEXT NOT NULL | 交易日期（ISO 8601） |
| action | TEXT NOT NULL | `buy` 或 `sell` |
| shares | REAL NOT NULL | 股數 |
| price | REAL NOT NULL | 成交價格（USD） |
| amount | REAL NOT NULL | 金額（USD，= shares × price，容許使用者核對時手動調整） |
| created_at | TEXT NOT NULL | 寫入時間戳 |

**不含欄位**：截圖原始檔或其任何參照——FR-004 規定不永久保存，暫存檔只存在
於匯入流程的記憶體/暫存目錄，不進這張表也不進任何持久化儲存。

**驗證規則**：`action` 只能是 `buy`/`sell`；`shares` > 0；`price` > 0。
不做同筆交易的自動去重（見 spec.md Edge Cases）。

---

## 2. us_stances（美股投資立場／研究筆記）

對應 spec.md「美股投資立場」實體、FR-008/009。

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| ticker | TEXT NOT NULL | 股票代號 |
| created_at | TEXT NOT NULL | 建立時間 |
| direction | TEXT NOT NULL | `bullish`／`bearish`／`neutral`（對應買/賣/觀望） |
| bear_price | REAL NULL | Bear 情境價格帶下緣 |
| bear_price_high | REAL NULL | Bear 情境價格帶上緣 |
| base_price_low | REAL NULL | Base 情境價格帶下緣 |
| base_price_high | REAL NULL | Base 情境價格帶上緣 |
| bull_price | REAL NULL | Bull 情境價格帶下緣 |
| summary | TEXT NOT NULL | 論點摘要（短文字，供列表/卡片摘要顯示） |
| full_note | TEXT NOT NULL | 完整研究筆記內容（Markdown，FR-005渲染來源） |
| status | TEXT NOT NULL DEFAULT 'active' | `active`／`closed`（對應「進行中/已結束」；`closed`由使用者手動標記，見 spec.md Assumptions） |

**驗證規則**：`direction`、`status` 為固定列舉值；`full_note` 不得為空
（FR-009 要求完整內容，不可只存摘要）。

**生命週期**：一檔股票可以有多筆立場紀錄（每次重新討論後勢都可以新增一筆，
不覆蓋舊的），列表/詳情頁預設顯示最新一筆 `active` 立場；`closed` 的立場
仍保留供歷史回顧。

---

## 3. us_watch_conditions（關注條件）

對應 spec.md「監控條件」實體、FR-010/011/012/017。

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| ticker | TEXT NOT NULL | 股票代號 |
| metric_type | TEXT NOT NULL | 指標類型，例：`price`／`gaap_gross_margin`／`nrr` |
| comparator | TEXT NOT NULL | `lt`（小於）／`gt`（大於） |
| threshold | REAL NOT NULL | 門檻數值 |
| status | TEXT NOT NULL DEFAULT 'insufficient_data' | `ok`（未觸發）／`alert`（已觸發）／`insufficient_data`（資料不足） |
| last_evaluated_at | TEXT NULL | 最近一次**成功**評估的時間；額度用盡跳過時**不更新**此欄位，藉此區分「未更新（無額度）」與正常狀態（見下方） |
| last_notified_at | TEXT NULL | 最近一次推播通知的時間（用於 FR-012 的「狀態轉為已觸發才推播、不重複推播」判斷） |
| created_at | TEXT NOT NULL | |

**狀態轉換規則（對應 FR-011/012/017）**：
- 新建立時 `status='insufficient_data'`，`last_evaluated_at=NULL`
- 排程成功評估後：更新 `status` 為 `ok`/`alert`，更新 `last_evaluated_at`
  為當次排程時間
- 排程當次因額度用盡而**跳過**該股票：**完全不更新這一列**（`status`、
  `last_evaluated_at` 都維持上一次的值）——前端判斷「未更新（無額度）」
  的邏輯是比對 `last_evaluated_at` 是否為「今天」，而不是靠 `status` 欄位
  本身的值（因為 `status` 在跳過時就是維持原樣，不會有第四個列舉值）
- 推播觸發條件：本次評估 `status` 從非 `alert` 轉為 `alert`，且
  `last_notified_at` 早於本次評估時間，才推播並更新 `last_notified_at`

**驗證規則**：`comparator`／`metric_type` 為固定列舉值（`metric_type` 具體
可擴充清單留待實作時依 FMP 實際可取得的欄位定案）。

---

## 4. us_price_snapshots（美股報價紀錄）

對應 spec.md「美股報價紀錄」實體、FR-006/007/017。

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| ticker | TEXT NOT NULL | 股票代號 |
| snapshot_date | TEXT NOT NULL | 排程執行日期（非交易日期——即使抓到的是延遲資料，記錄的是「哪天排程抓的」） |
| close_price | REAL NULL | 收盤價（USD） |
| gaap_gross_margin | REAL NULL | 毛利率（若該次查詢有取得） |
| revenue_yoy | REAL NULL | 營收年增率（若有取得） |
| source | TEXT NOT NULL | `fmp`／`alpha_vantage`／`yfinance`（記錄這筆資料實際來自主要或備援來源，供除錯與資料品質追蹤） |
| fetched_at | TEXT NOT NULL | |

**唯一性**：`(ticker, snapshot_date)` 應唯一——同一天排程對同一檔股票只
會成功寫入一筆（若當天排程對某股跳過，則該股當天完全沒有這張表的紀錄，
形成 research.md §4 所述的「歷史缺口」，這是預期行為，不是資料遺失）。

**與 `StockComboChart` 元件的關係**：前端股價走勢圖（FR-003/005）從這張
表依 `ticker` 撈出時間序列，`close_price` 對應折線圖的資料點；買賣點位
標記則來自 `us_trades` 表依 `trade_date` 疊加，兩個資料來源在前端合併
渲染，資料庫層不需要外鍵關聯兩張表。

---

## 實體關係總覽

```text
us_trades ──┐
            │ (ticker，前端合併查詢，無外鍵)
us_price_snapshots ──┤── 同一檔 ticker 在美股 landing/詳情頁彙整顯示
            │
us_stances ──┤
            │
us_watch_conditions ──┘
```

四張表都以 `ticker`（股票代號字串）作為邏輯關聯鍵，**不建立外鍵約束**
（SQLite 外鍵預設不強制啟用，且各表的生命週期本來就不同步——例如一檔
股票可以先有 `us_watch_conditions` 卻還沒有任何 `us_trades`，見
spec.md Edge Cases「純觀察中的股票」）。「追蹤清單」（FR-013）的定義是
「四張表任一張出現過這個 ticker」的聯集查詢，不是獨立的第五張表。
