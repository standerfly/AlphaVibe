# EP461 量價狀態與相對強弱回測（poc/backtest-ep461）

規格：專案文件 `claude/回測規格-EP461與相對強弱.md` v0.3。範圍＝庫存 15 檔＋基準 0050。
**完全獨立**：不 import `poc/kb-mcp`、不讀寫正式庫 `poc/data`；下載資料在 `data/`、結果在 `out/`（皆 gitignore）。
只用標準庫，Python 3.9 相容。回測不連網、不經 LLM，同一份資料重跑結果必相同。

## 檔案

| 檔案 | 用途 |
|---|---|
| `b0_download.py` | B0：`probe`（確認資料集名稱／欄位／權限）、`download`（可續傳）、`status` |
| `b1_adjust.py` | B1：讀本地檔、依除權息／分割／減資參考價後復權、資料品質報告 |
| `b2_signals.py` | B2：C3 量價訊號、C2 相對強弱 |
| `b3_forward.py` | B3：前瞻報酬（確認日 T+5 起算）、超額報酬、MFE／MAE、獨立事件 |
| `b4_b5_stats.py` | B4 分組統計、B5 前後半切分與敏感度 |
| `b6_report.py` | B6：CSV 與 `summary.md` |
| `run_backtest.py` | 串起 B1～B6 |
| `regression_0050.py` | 用 0050 的 14 筆已知訊號（規格第 7 節）驗證 B2 |
| `pack_results.py` | 把要貼回對話的彙總打包成一段文字 |
| `tests/` | 合成資料測試（`python3 -m unittest discover -s tests`） |

## 在你的 Mac 上執行（zsh）

這個環境連不上 FinMind，下載要在你的電腦或 AlphaVibe 主機跑。用獨立 worktree，不動開發資料夾與正式環境：

```bash
cd /Users/stander/My_project/AlphaVibe
git fetch origin function/backtest-ep461
git worktree add ../AlphaVibe-backtest origin/function/backtest-ep461
cd ../AlphaVibe-backtest/poc/backtest-ep461

# token（只需一次；輸入時不顯示，不會進指令歷史）
read -s "T?貼上 FinMind token: "; echo "$T" > finmind_token.txt; unset T; chmod 600 finmind_token.txt
```

第 1 步：確認資料集與欄位（約 7 次呼叫），輸出貼回給 Claude：

```bash
python3 b0_download.py probe
```

第 2 步：下載（約 64 次呼叫、每次間隔 2.5 秒；額度用完會自動停並存進度，一小時後重跑同一指令即可續傳）：

```bash
python3 b0_download.py download
python3 b0_download.py status
```

第 3 步：回歸驗證與回測，然後一次回貼：

```bash
python3 regression_0050.py
python3 run_backtest.py
python3 pack_results.py | pbcopy
```

在對話裡貼上即可（內容只有彙總與欄位確認，沒有原始價格、沒有 token）。明細在 `out/`。

節制機制：預設避開 01:30–03:30（02:00 全市場掃描時段）；沒有 token 預設不執行；遇額度用完（402）立即停止；
暫時性錯誤最多退避重試 3 次；`--max-calls`（預設 100）限制單次呼叫數。

## 暫定假設（請核對）

1. 還原＝後復權，因子＝參考價／事件前收盤。除權息用 `after_price`（找不到再用 `reference_price`）；欄位若與 probe 結果不同，`b1_adjust.load_events` 會明確報錯，不猜。
2. 成交量只在分割與減資事件乘 1/因子；現金／股票股利不調整成交量。
3. 0050 的 2025-06 一拆四有手動備援（`common.MANUAL_EVENTS`），只在下載資料裡找不到同檔 ±5 天內的分割事件時使用。
4. 冷卻的兩處細節規格沒說清楚（只有被計入的訊號重設冷卻，或任何價格突破日都重設；相隔 ≥5 日或 >5 日才可再計）：`regression_0050.py` 自動試 4 種組合，吻合者寫回規格；正式回測預設用「只計入者重設、相隔 ≥5 日」。**regression 若吻合的是別種組合，要改 `b2_signals.c3_signals` 的預設值再跑回測。**
5. 超額報酬＝個股報酬 − 同期 0050 報酬（0050 也用還原價）。獨立事件＝同檔同方向、與上一個獨立事件相隔 ≥20 交易日。
6. 前後半切點＝所有個股交易日合併後的中位日期。
7. C2 分組（規格沒定義）：60 日窗口，累計相對報酬是否 >0 × 下跌捕捉率是否 <1，共 4 組；每 20 個交易日取樣一次降低重疊。基準上漲或下跌日少於 8 天，該指標標「樣本不足」。
8. 6826 和淞（興櫃）預期查無價格，會列在「樣本不足／無資料」；歷史少於 250 列的檔也會列入並排除。

## 限制

存活者偏誤、半導體／AI 供應鏈高度相關、重疊窗口、未計交易成本；結論只能說「在這些檔上」。
後半期看過結果後再改門檻，該段即視為已用掉。
