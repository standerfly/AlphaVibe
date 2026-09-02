"""股價歷史深度回補——一次性、需要人手動執行的腳本。

## 為什麼需要這支腳本（spec 001-entry-exit-foundation FR-014）

`get_price_position` 的百分位判斷用 `stock_price_history` 快取當樣本，
但那張表只從 2026-04-13 開始累積、每檔最多約 100 個交易日，樣本區間
不到 5 個月，判斷的是「近期位置」而非有意義的「區間定位」。

原本的想法是把每日排程的 `screener.PRICE_WINDOW_DAYS` 從 120 加長到
400 讓資料自然累積——**這個想法是錯的**，2026-09-02 實測證實
`twse_price_client.fetch_price_history()` 是**逐月**抓的
（`_months_needed = window_days // 20 + 2`），窗口加長會等比例增加
HTTP 呼叫次數：每檔 8 次 → 22 次（上櫃股 16 → 44 次），25 檔持股的
每日排程會從約 200 次變成 550+ 次，每次還有節流，執行時間與被 TWSE
暫時封鎖的風險同步上升。

改用這支腳本：**長歷史只抓一次**，之後每日排程維持 120 天窗口接續
更新即可。`stock_price_history` 是 `INSERT OR REPLACE`（`kb_store.py`
的 `save_price_history_points`）永不刪除舊列，所以補過一次就永久有了。

## 冪等性

跟 `backfill_holdings_sync_once.py` 不同，**這支腳本是冪等的**：
重複執行只會用相同資料覆寫相同的 (code, date) 主鍵，不會產生重複列、
不會讓任何數字翻倍。唯一的代價是重複執行會重複打外部 API，所以還是
不要沒事就跑。

## 用法

先看要打幾次 API（不碰網路）：

    python3 poc/kb-mcp/backfill_price_history_once.py --data-dir poc/data --dry-run

實際回補（正式庫）：

    python3 poc/kb-mcp/backfill_price_history_once.py --data-dir poc/data

只補特定幾檔：

    python3 poc/kb-mcp/backfill_price_history_once.py --data-dir poc/data \\
        --codes 2330,2337,3008

官方端點對某些標的的舊月份會回 HTTP 308（實測 6257／3661 的 2025-12
就是如此，但同一支的 2026-08、以及 2308 的 2025-12 都正常），而
`fetch_price_history` 只要有任何一個月成功就算成功、不會退回 FinMind，
結果那些標的只補到最近幾個月。這種情況改用 FinMind 直取：

    python3 poc/kb-mcp/backfill_price_history_once.py --data-dir poc/data \\
        --codes 6257,3661 --source finmind

測試環境：把 `--data-dir` 指向獨立測試庫（例如 `poc/data-test`）。
`--data-dir` 是必填且沒有預設值——沿用 2026-08-22 教訓（正式庫曾被
測試污染兩次）的防呆做法，不讓人不小心打到正式庫。
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finmind_client  # noqa: E402
import screener  # noqa: E402
import twse_price_client  # noqa: E402
from kb_store import KBStore  # noqa: E402

DEFAULT_WINDOW_DAYS = 400  # 約 13 個月，讓百分位能涵蓋近一年


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _target_codes(store, explicit):
    """要回補哪些標的：明確指定優先，否則取「持股 ∪ 交易流水」去重。

    刻意不只取 get_holdings()——它會濾掉 shares<=0，查不到已出清標的，
    而已出清標的一樣可能需要價位定位（見 spec FR-003 的同類考量）。
    """
    if explicit:
        return [c.strip() for c in explicit.split(",") if c.strip()]
    codes = []
    for row in store.get_all_trade_entries():
        code = row.get("code")
        if code and code not in codes:
            codes.append(code)
    for row in store.get_holdings().get("holdings", []):
        code = row.get("code")
        if code and code not in codes:
            codes.append(code)
    return sorted(codes)


def _estimate_calls(codes, window_days):
    """估算會打幾次外部 API，讓執行者事前知道成本。

    每檔至少 _months_needed(window_days) 次；市場別未知時（本腳本走
    screener._fetch_prices_with_fallback，market=None）上櫃股會先試
    TWSE 失敗再試 TPEx，最差是兩倍。
    """
    per_code = twse_price_client._months_needed(window_days)
    return {"months_per_code": per_code,
            "best_case": per_code * len(codes),
            "worst_case": per_code * len(codes) * 2}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="一次性回補股價歷史深度（spec 001-entry-exit-foundation FR-014）")
    parser.add_argument("--data-dir", required=True,
                        help="資料目錄（必填，沒有預設值以免誤打正式庫）")
    parser.add_argument("--codes", default=None,
                        help="逗號分隔的股票代碼；省略＝持股與交易流水的全部標的")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help="回補窗口天數（預設 %d）" % DEFAULT_WINDOW_DAYS)
    parser.add_argument("--source", choices=("auto", "finmind"), default="auto",
                        help=("auto＝官方端點優先、失敗才退回 FinMind（預設）；"
                              "finmind＝直接用 FinMind。官方端點對某些「個股×月份」"
                              "組合會回 HTTP 308，而 fetch_price_history 只要有任何"
                              "一個月成功就算成功、不會退回 FinMind，導致那些標的"
                              "只補到最近幾個月——這種情況用 --source finmind 補。"))
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出將回補的標的與預估 API 呼叫次數，不碰網路也不寫入")
    args = parser.parse_args(argv)

    store = KBStore(args.data_dir)
    try:
        codes = _target_codes(store, args.codes)
        estimate = _estimate_calls(codes, args.window_days)
        print("資料目錄：%s" % args.data_dir)
        print("回補標的：%d 檔｜窗口：%d 天（每檔 %d 個月）"
              % (len(codes), args.window_days, estimate["months_per_code"]))
        print("預估外部 API 呼叫：%d~%d 次（上櫃股需先試 TWSE 再試 TPEx）"
              % (estimate["best_case"], estimate["worst_case"]))

        if args.dry_run:
            print("\n--dry-run：不執行實際抓取。標的清單：")
            print("  " + ", ".join(codes))
            return 0

        saved_total = 0
        failures = []
        for index, code in enumerate(codes, 1):
            try:
                if args.source == "finmind":
                    start = _days_ago(args.window_days)
                    result = finmind_client.get_stock_price_history(
                        code, start_date=start, data_dir=args.data_dir)
                    prices, source = (result.get("prices") or []), "finmind"
                else:
                    prices, source = screener._fetch_prices_with_fallback(
                        code, None, args.data_dir, None, {})
                if not prices:
                    failures.append((code, "查無資料（來源：%s）" % source))
                    continue
                store.save_price_history_points(code, prices)
                saved_total += len(prices)
                print("[%d/%d] %s：%d 筆（%s~%s，來源 %s）"
                      % (index, len(codes), code, len(prices),
                         prices[0].get("date"), prices[-1].get("date"), source))
            except Exception as exc:  # 單檔失敗不中斷整批
                failures.append((code, str(exc)))
                print("[%d/%d] %s：失敗——%s" % (index, len(codes), code, exc))

        print("\n完成：%d 檔成功、%d 檔失敗，共寫入 %d 筆價格點"
              % (len(codes) - len(failures), len(failures), saved_total))
        if failures:
            print("失敗清單（可單獨用 --codes 重跑，本腳本冪等）：")
            for code, reason in failures:
                print("  %s：%s" % (code, reason))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
