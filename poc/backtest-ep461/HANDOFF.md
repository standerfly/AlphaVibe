# 交接：EP461 回測（從 claude.ai 對話轉到 Claude Code，2026-11-17）

給接手的 Claude Code：這份是完整脈絡。先讀這份，再讀 `README.md`。使用者是 Stander（PO，非工程師），用繁體中文溝通。

## 工作方式（使用者偏好）

- 繁體中文回覆（台灣用語）；程式碼、識別字、commit 訊息用英文。結論先講，不要重述問題或寫開場白。
- 做到底：下一步若是唯讀或容易復原，直接做，不要問「要不要我…」。合理假設就做，並在最後列出假設。
- 只有「寫入、儲存、送出、刪除、難以復原」的動作才先問。
- 不確定就明講，不要猜。數字一律來自實際資料或工具結果。
- 這個 repo 的 `CLAUDE.md` 規則照常適用（例如：給 Mac 的指令假設是 zsh；FinMind 額度要節制；不碰正式庫 `poc/data`）。

## 目標

回答：EP461 量價狀態（C3）與相對強弱（C2），在 Stander 持有的 15 檔（加基準 0050）上，有沒有比「隨便哪天買」更好的後續報酬。結果決定個股檢視卡 P0 要不要做、門檻怎麼訂。**結論只能說「在這 15 檔上」。** 第一階段只輸出數值、不下判定。

庫存 15 檔（2026-11-13 快照）：2308 台達電、2337 旺宏、2441 超豐、2449 京元電子、3131 弘塑、3526 凡甲、3661 世芯-KY、4931 新盛力、6223 旺矽、6515 穎崴、6757 台灣虎航、6826 和淞、7734 印能科技、7769 鴻勁、8299 群聯。

## 已完成（分支 `function/backtest-ep461`）

`poc/backtest-ep461/` 獨立資料夾（不 import `poc/kb-mcp`、不碰 `poc/data`），標準庫、Python 3.9 相容：
B0 `b0_download.py`（probe／download／status）、B1 `b1_adjust.py`、B2 `b2_signals.py`、B3 `b3_forward.py`、B4／B5 `b4_b5_stats.py`、B6 `b6_report.py`、`run_backtest.py`、`regression_0050.py`、`pack_results.py`、`tests/`（22 項合成資料測試全過）。

## 尚未驗證（要在有網路的 Mac 上跑才知道）

1. FinMind 事件資料集的名稱與欄位：程式用 `TaiwanStockDividendResult`（`before_price`／`after_price` 或 `reference_price`）、`TaiwanStockSplitPrice`、`TaiwanStockCapitalReductionReferencePrice`（`ClosingPriceonTheLastTradingDay`／`PostReductionReferencePrice`），這是憑文件記憶寫的。`probe` 是第一步；欄位不符時 `b1_adjust.load_events` 會明確報錯，修它即可。
2. token 權限（`TaiwanStockPriceAdj` 現成還原價在 probe 裡只是選配）。
3. 0050 回歸：`regression_0050.py` 要重現規格的 14 筆訊號與基準（後 5／10／20 日均值 +1.20%／+2.36%／+5.07%，上漲比例 65%／68%／80%，n＝339／334／324）。規格那組數字是對話裡手抄的，**不吻合時先查資料再查程式**。
4. 冷卻的兩處細節規格沒說清楚（只有被計入的訊號重設冷卻 vs 任何價格突破日都重設；相隔 ≥5 日 vs >5 日），程式自動試 4 種組合；吻合的那組要寫回 `b2_signals.c3_signals` 預設值與規格。
5. 6826 和淞（興櫃）預期查無價格；7734、7769 歷史可能很短；6515 穎崴價格疑似被調整過（看資料品質報告的 off-tick 比例）；還原後是否仍有假跳空。

## 已查事實（2026-11-16）

- AlphaVibe 的價格是即時轉查 FinMind 的**原始價，未還原**（0050 在 2025-06 一拆四：2025-06-10 收盤 188.65、2025-06-18 收盤 47.57）；沒有自己的歷史價格庫（`stock_price_history` 只存收盤價、從 2026-04 起）。
- 歷史：0050、2308 至少到 2005；多數持股至少到 2019-12。
- FinMind 匿名額度是全域共用池，曾被打光、連累 02:00 排程；所以：要用 token、逐檔呼叫、避開 01:30–03:30、遇 402 立即停。

## 暫定假設（改動都在 `b2_signals.py`／`b1_adjust.py`／`common.py`）

後復權，因子＝參考價／事件前收盤；成交量只在分割與減資乘 1/因子；0050 的一拆四有手動備援（`common.MANUAL_EVENTS`）。超額報酬＝個股減同期 0050。獨立事件＝同檔同方向相隔 ≥20 日。前後半切點＝全部個股交易日的中位日期。C2 分組（規格未定義）＝60 日窗口「累計相對報酬>0」×「下跌捕捉率<1」四組，每 20 日取樣。歷史少於 250 列的檔標「樣本不足」排除。

## 執行步驟

1. 確認這個資料夾乾淨；不要切換開發資料夾的分支。用獨立 worktree：`git fetch origin function/backtest-ep461`，`git worktree add ../AlphaVibe-backtest origin/function/backtest-ep461`，之後在 `../AlphaVibe-backtest/poc/backtest-ep461` 執行。
2. token：使用者自己輸入到該資料夾的 `finmind_token.txt`（`read -s` 那段在 README）。你只能用 `test -s` 確認存在，**不得讀取、印出或寫進任何輸出**。沒有檔案就停下來，請使用者輸入後說「好了」。
3. `python3 b0_download.py probe` → 依結果修 B1（若需要）→ `python3 b0_download.py download`（約 64 次呼叫，可續傳；額度用完就停，等一小時再跑同一指令）→ `python3 regression_0050.py` → `python3 run_backtest.py`。
4. 回歸沒有任何組合吻合：列出差異並停下來，先查資料再查程式。
5. 完成後結論先講：regression 結果、`out/summary.md` 重點（每組先看「獨立事件」數，個位數不下結論）、需要使用者決定的事。

## 完成後要更新的文件（使用者的 claude.ai「AlphaVibe」專案，不在這個 repo）

- `claude/回測規格-EP461與相對強弱.md`：第 14 節的「尚未驗證」改成實際結果、冷卻定義寫回、版本升 v0.5。
- `claude/對話看板.md`：EP464／EP461 那筆更新「已完成／下一步／最後更新日」。
- 如果讀不到這些專案文件（Claude Code 看不到 claude.ai 專案），就把要更新的內容整理成一段文字交給使用者貼回 claude.ai。

## 未決（等回測結果後由使用者決定）

回測有結果後，是否把 EP461 的量比條件加進「低點比較選股」掃描；個股檢視卡 P0 要不要做；C2 的分組方式要不要換。
