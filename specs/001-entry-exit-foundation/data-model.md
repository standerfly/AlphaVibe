# Data Model: 進出場分析基礎層

**Feature**: 001-entry-exit-foundation | **Date**: 2026-09-02
**對應 pre-spec 缺口**：GAP-R02（Data model note）

## 結論：本階段不新增任何資料表或欄位

FIFO 損益與價位百分位皆為**查詢時即算**（read-only computation），
輸入全部來自既有三張表，輸出不落盤。唯一的持久化變更是一個常數值
（見「設定值變更」節），不涉及 schema migration。

**不做快取表的理由**：資料規模小（537 筆交易 / 60 檔），單次全量計算
成本可忽略；引入快取表會多出「何時失效」的複雜度與不一致風險，
違反本 repo「先簡單」的既有做法。若日後效能成為問題再另議。

## 輸入：既有資料表（唯讀，不修改）

### `trade_ledger`（`poc/kb-mcp/kb_store.py:192-204`）

FIFO 的唯一事實來源。

| 欄位 | 型別 | 本功能用途 | 注意事項 |
|---|---|---|---|
| `code` | TEXT | 分組鍵 | |
| `name` | TEXT | 顯示用 | |
| `action` | TEXT | 買/賣別 | **只有中文「買」/「賣」**，`kb_store.py:1141-1142` 強制驗證 |
| `shares` | REAL | 批次股數 | **單位是「股」**（見 research.md R-001），金額不需 ×1000 |
| `price` | REAL | 批次單價 | |
| `date` | TEXT | FIFO 排序主鍵 | 實測 537 筆全為 `YYYY-MM-DD` |
| `id` | INTEGER | FIFO 排序次鍵 | 同日多筆時決定先後 |
| `order_ref` | TEXT | 重複偵測輔助 | 實測有 3 組重複值 |
| `add_sequence` | INTEGER | **本功能不用** | 賣出時強制 NULL；語意是「加碼序號」非流水序 |

**沒有的東西**：手續費、證交稅欄位 → 損益一律為毛額（FR-005）。

### `stock_prices`（`kb_store.py:84-89`）

未實現損益的現價來源。`code` 為 PK，含 `price`、`price_date`、
`updated_at`。讀取用既有 `get_stock_prices()`（`kb_store.py:800`）。
`price_date` 必須一併回傳，讓使用者判斷報價新鮮度。

### `stock_price_history`（`kb_store.py:103-109`）

百分位的樣本來源。只有 `code`／`date`／`close`（PK `(code,date)`），
**無 OHLC、無成交量** → 百分位只能用收盤價。讀取用既有
`get_cached_price_history(code, limit_days)`（`kb_store.py:872-885`）。

實測涵蓋：3726 筆 / 39 檔 / 2026-04-13~2026-09-02，每檔最多約 100 個
交易日。

## 新增的資料存取方法（不改既有方法）

### `KBStore.get_all_trade_entries()`

```
輸入：無
輸出：list[dict]，每筆為 trade_ledger 完整列
排序：ORDER BY code, date, id
```

單一查詢取回全部交易列，由計算層在 Python 分組，避免 60 檔逐檔查詢的
N+1。**不修改**既有 `get_trade_ledger(code)`（`kb_store.py:1158-1166`），
避免影響現有呼叫端。

## 計算層的記憶體資料結構（不落盤）

### TradeLot（交易批次）

FIFO 佇列的元素，由一筆「買」產生：

| 欄位 | 說明 |
|---|---|
| `shares_remaining` | 尚未被賣出配對消耗的股數 |
| `price` | 該批次單價 |
| `date` | 買進日期 |

賣出時從佇列前端依序消耗；每次配對產生一筆已實現損益
`(賣價 - 批次單價) × 配對股數`。

### PositionPnL（標的損益結果）

| 欄位 | 說明 |
|---|---|
| `code` / `name` | 標的識別 |
| `realized_pnl` | 已實現損益金額（配對完成的部分加總） |
| `unrealized_pnl` | 未實現損益金額（剩餘批次以現價計） |
| `unrealized_pct` | 未實現報酬率（剩餘批次成本為分母） |
| `shares_held` | 剩餘持有股數（＝剩餘批次股數加總） |
| `cost_basis` | 剩餘批次的成本合計 |
| `current_price` / `price_date` | 現價與其日期（缺則為 None） |
| `cost_method` | 固定 `"FIFO"` |
| `fees_included` | 固定 `false`（毛額，FR-005） |
| `status` | `ok` / `history_incomplete` / `no_price` / `no_trades` |
| `shortfall_shares` | 僅 `history_incomplete` 時：賣出超出買進的股數 |
| `suspected_duplicates` | 偵測到的疑似重複列筆數（FR-006，僅警示） |

### PricePosition（價位定位結果）

| 欄位 | 說明 |
|---|---|
| `code` | 標的識別 |
| `percentile` | 現價在歷史收盤價中的百分位（0–100）；資料不足時為 None |
| `sample_size` | 實際樣本數（FR-008） |
| `range_start` / `range_end` | 樣本涵蓋起訖日（FR-008） |
| `low` / `high` | 樣本區間的最低/最高收盤價 |
| `status` | `ok`（≥30 筆）/ `limited`（6–29 筆）/ `insufficient`（<6 筆）/ `no_data` |
| `basis` | 人類可讀的判斷依據說明，`limited` 時必須明講樣本不足 |

## 狀態轉換（GAP-R03）

本階段**沒有持久化狀態機**——所有輸出都是查詢當下計算出來的即時結果，
沒有需要在多次呼叫之間維持的狀態。唯一的「狀態」是每次結果的
`status` 欄位，由資料充足度決定：

```
PositionPnL.status 判定順序（先命中先決定）：
  該 code 無任何交易列                        → no_trades
  賣出股數 > 買進股數（FIFO 佇列不足以配對）  → history_incomplete（附 shortfall_shares）
  有剩餘持股但 stock_prices 查不到現價        → no_price（realized 仍照常回傳）
  其餘                                        → ok

PricePosition.status 判定順序：
  該 code 在 stock_price_history 無資料       → no_data
  樣本數 < 6                                  → insufficient
  6 ≤ 樣本數 < 30                             → limited
  樣本數 ≥ 30                                 → ok
```

**排程整合的狀態流程屬階段B**（entry-exit-signals），本階段只有
「MCP 查詢 → 讀三張表 → 計算 → 回傳」的單向流程，無非同步、無回呼、
無事件。
