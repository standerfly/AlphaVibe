# Quickstart: 進出場訊號層

**Feature**: 002-entry-exit-signals | **Date**: 2026-09-03

## 跑測試

```bash
cd /Users/stander/My_project/AlphaVibe
python3 -m unittest discover -s poc/kb-mcp/tests
python3 -m unittest poc.kb-mcp.tests.test_exit_signals -v   # 本階段新增
```

> 測試一律 `tempfile.mkdtemp()` 建獨立庫，**不碰正式庫**。
> 若遇到「改了程式碼但行為沒變」，先查快取位置：
> `python3 -c "import screener; print(screener.__cached__)"`
> ——本機的 pyc 快取在 `~/Library/Caches/com.apple.python/`，不是 repo 的
> `__pycache__`（CLAUDE.md 2026-09-03 教訓）。

## 手動驗證三種訊號

```bash
cd /Users/stander/My_project/AlphaVibe/poc/kb-mcp
python3 - <<'EOF'
import sqlite3, exit_signals, price_position

conn = sqlite3.connect("file:../data/alphavibe.db?mode=ro", uri=True)  # 唯讀
conn.row_factory = sqlite3.Row
prices = {r["code"]: {"price": r["price"], "price_date": r["price_date"]}
          for r in conn.execute("SELECT code, price, price_date FROM stock_prices")}

# 門檻判斷（用假的門檻試，不寫入）
print(exit_signals.evaluate_threshold(
    "2337", {"stop_loss": 110.0, "take_profit": 160.0, "reason": "測試"}, prices))
print(exit_signals.evaluate_threshold("2337", None, prices))  # 應為 not_set

# 營收趨勢（FR-007，擴大後的期數）
yoy = [r["yoy_growth"] for r in conn.execute(
    "SELECT yoy_growth FROM revenue_yoy_cache WHERE code='2337' ORDER BY id") ]
print(exit_signals.revenue_trend([v for v in yoy if v is not None]))
conn.close()
EOF
```

**預期**：`not_set` 狀態的 `stop_loss`／`take_profit` 必須是 `None`
（不得填任何預設值）。

## FR-012 的必做實測：外部呼叫次數不得增加

**這是本階段最重要的驗證**，階段A 就是在這裡摔過（從參數語意推論而
沒實測，導致排程慢 29 分鐘）：

```bash
cd /Users/stander/My_project/AlphaVibe/poc/kb-mcp
python3 - <<'EOF'
import twse_price_client as t, finmind_client as f
calls = {"twse": 0, "finmind": 0}
_orig_t, _orig_f = t._throttled_get, f._request   # 依實際函式名調整
def spy_t(*a, **k):
    calls["twse"] += 1; return _orig_t(*a, **k)
def spy_f(*a, **k):
    calls["finmind"] += 1; return _orig_f(*a, **k)
t._throttled_get, f._request = spy_t, spy_f
# 在此跑「關閉新訊號」與「開啟新訊號」兩種情況的同一批標的，比對 calls
EOF
```

**驗收標準**：兩種情況的 `calls` 完全相同。若有任何增加，設計就是錯的
——三種新訊號的資料都應該來自既有已載入或已快取的來源。

## FR-007 的必做驗證：改動前後的逐檔比對

`_growth_deceleration` 的判斷準則會改變，**不可只跑單元測試就宣稱完成**。
用正式庫的既有資料跑改動前後比對，列出哪些標的結果改變：

```bash
# 用 git archive 匯出改動前的版本到暫存目錄，兩版各跑一次同一批資料
git archive HEAD~1 poc/kb-mcp | tar -x -C /tmp/before
# 比對兩邊對同一批 code 的 flagged 結果
```

結果寫回 `research.md` R-004。

## 排程耗時的基準線與比對

改動前基準線（實測，來自 `module_d_results.checked_at`）：

| 日期 | 檔數 | 秒數 |
|---|---|---|
| 2026-09-02 | 39 | **1097（18.3 分）** |
| 2026-09-01 | 39 | 765 |

改動後要能從 log 直接看到耗時（本階段會補上時間戳），與上表比對。

```bash
tail -20 ~/Library/Logs/alphavibe-module-d.log
sqlite3 "file:poc/data/alphavibe.db?mode=ro" \
  "SELECT date(checked_at) d, count(*), min(checked_at), max(checked_at)
   FROM module_d_results GROUP BY d ORDER BY d DESC LIMIT 5;"
```

## 頁面驗證（FR-014／FR-015）

正式服務跑在 `:8080`（`com.alphavibe.reportserver.plist`）。改動
`report.py` 後**必須重啟**才會生效：

```bash
launchctl kickstart -k gui/$(id -u)/com.alphavibe.reportserver
curl -s http://127.0.0.1:8080/api/healthz
```

檢查兩種標的的呈現：
- **FIFO 可算**（例：2308）→ 應看到 FIFO 數字＋`FIFO・未扣交易成本` 標籤
- **FIFO 無法算**（例：6257，賣超）→ 應看到「FIFO 無法計算：歷史不完整」
  ＋加權平均估算值＋`加權平均估算・未扣賣出・非 FIFO` 標籤，
  且走勢圖的均價虛線仍在

## 完成後的驗收

依 `~/.claude/rules/10-model-dispatch.md` 第 6 節「驗證不自驗」，派
fresh-context agent 對照 spec 的 15 條 FR 逐條驗收。**驗收 prompt 必須
包含**：外部呼叫次數的獨立實測、`save_exit_threshold` 不得出現在唯讀
白名單的反向檢查、以及正式庫未被寫入的確認。
