# Data Model: 進出場訊號層

**Feature**: 002-entry-exit-signals | **Date**: 2026-09-03

## 新增資料表：`exit_thresholds`

**唯一的 schema 變更**。其餘訊號（背離、營收趨勢）都是查詢時即算，
不落盤；訊號結果沿用既有 `module_d_results`（見下）。

```sql
CREATE TABLE IF NOT EXISTS exit_thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    reason TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exit_thresholds_code ON exit_thresholds(code, id DESC);
```

**append-only，最新一筆勝出**（`max(id) GROUP BY code`），與 `stances`
同模式（`kb_store.py:478-483`）。理由見 research.md R-001：門檻背後有
討論脈絡，要能回答「當初為什麼設在這裡」。

| 欄位 | 說明 |
|---|---|
| `stop_loss` | 停損價（絕對價格，非百分比）；可為 NULL 表示只設停利 |
| `take_profit` | 停利價；可為 NULL 表示只設停損 |
| `reason` | 設定當下的討論結論——這是保留歷史的意義所在 |
| `source_ref` | 來源標記，預設 `對話設定`（沿用 repo 既有的 source_ref 慣例） |

**驗證規則**：
- `stop_loss` 與 `take_profit` **至少要有一個**，兩者皆空則 raise
- 給定的值必須可轉 float 且 > 0（沿用 `save_position_plan` 的驗證風格，
  `kb_store.py:1053-1070`）
- 兩者都給時 `stop_loss < take_profit`，否則 raise（明顯的設定錯誤）
- **不做任何預設值填補**——沒設定就是沒設定（FR-003）

## 新增的資料存取方法

| 方法 | 行為 |
|---|---|
| `save_exit_threshold(code, stop_loss=None, take_profit=None, reason=None, source_ref=None)` | INSERT 一筆，回 `{"saved": True, "id", "code", ...}` |
| `get_exit_threshold(code)` | 該檔最新一筆；**從未設定回 `None`**（呼叫端據此顯示「尚未設定」，不得自行編預設值——沿用 `get_position_plan` 的 docstring 約定） |
| `get_all_exit_thresholds()` | 每檔最新一筆的 dict，供批次判斷 |
| `get_exit_threshold_history(code)` | 該檔全部歷史，舊到新 |

## 沿用既有資料表（不改 schema）

| 表 | 本階段用途 |
|---|---|
| `stock_prices` | 門檻觸發判斷的現價來源（每日流程本來就刷新） |
| `stock_price_history` | 背離偵測的股價位置（透過階段A `price_position`） |
| `revenue_yoy_cache` | 背離偵測與營收趨勢的資料來源（20 小時快取，`general_review` 已呼叫過） |
| `module_d_results` | **新訊號的輸出通道**，不新增欄位，`trigger_label` 新增兩個值 |
| `trade_ledger` | FIFO 損益（透過階段A `pnl`） |
| `stances` | **本階段完全不寫入**（FR-013） |

## 計算層的記憶體結構（不落盤）

### ThresholdStatus（門檻判斷結果）

| 欄位 | 說明 |
|---|---|
| `code` | 標的 |
| `status` | `not_set`／`no_price`／`triggered_stop_loss`／`triggered_take_profit`／`within_range` |
| `stop_loss`／`take_profit` | 設定值（未設定為 None） |
| `current_price`／`price_date` | 現價與其日期 |
| `distance_pct` | 距離最近門檻的百分比（觸發時為負/正的超出幅度） |
| `reason` | 設定當下的理由，供 PO 回想脈絡 |

### DivergenceSignal（背離判斷結果）

| 欄位 | 說明 |
|---|---|
| `code` | 標的 |
| `status` | `fundamentals_ahead`（基本面轉強但股價未跟上）／`price_ahead`（股價漲但基本面未跟上）／`aligned`／`insufficient` |
| `revenue_trend` | 營收趨勢方向與強度（見下） |
| `price_percentile` | 階段A 算出的股價百分位 |
| `basis` | 人類可讀的依據說明，兩邊的數字都要在裡面 |

### RevenueTrend（營收趨勢，FR-007）

| 欄位 | 說明 |
|---|---|
| `direction` | `rising`／`falling`／`flat`／`insufficient` |
| `periods_used` | 實際採用的期數（上限受既有資料窗口限制，實測最多 14） |
| `values` | 採用的年增率序列，供 detail 呈現 |
| `latest_vs_median` | 最新值相對窗口中位數的位置，用於判斷是否轉弱 |

## 狀態轉換

本階段**仍然沒有持久化狀態機**——門檻是設定值不是狀態，訊號是每次
計算出來的結果。唯一的「歷史」是 `exit_thresholds` 的 append-only 紀錄，
以及 `module_d_results` 每日累積的檢視結果。

```
ThresholdStatus 判定順序（先命中先決定）：
  該 code 在 exit_thresholds 查無紀錄          → not_set
  查無現價                                     → no_price
  有 stop_loss 且 現價 <= stop_loss            → triggered_stop_loss
  有 take_profit 且 現價 >= take_profit        → triggered_take_profit
  其餘                                         → within_range

DivergenceSignal 判定順序：
  營收年增率樣本不足 或 股價百分位為 insufficient/no_data → insufficient
  營收 rising 且 股價百分位 < 低檔門檻                    → fundamentals_ahead
  營收 falling 且 股價百分位 > 高檔門檻                   → price_ahead
  其餘                                                    → aligned
```

低/高檔門檻取 **30／70 百分位**——與階段A 的 `PERCENTILE_MIN_POINTS`
等既有常數放在一起管理，不散落在判斷式裡。
