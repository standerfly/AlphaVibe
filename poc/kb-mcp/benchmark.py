"""大盤（加權指數 TAIEX）基準資料＋相對大盤超額跌幅（2026-07-28）。

背景：2026-07 這波下跌是「殺個股不殺指數」——加權指數只回檔約9.5%，個股卻
回檔20~60%。單看個股自身回檔幅度無法回答「這檔跌得比大盤兇多少」，這裡補上
「超額跌幅」＝個股回檔－同期大盤跌幅，作為「錯殺」的量化代理。

「同期大盤」採「個股高點日→個股最新日」逐檔區間，不採固定窗：固定窗的大盤
回檔在這波行情下恆為正值（約9.5%），若個股高點落在大盤自身還在上漲的期間，
固定窗完全無法反映「大盤同期其實在漲」這件事，超額跌幅會被低估。逐檔區間
用 interval_drawdown() 對任意兩個日期算大盤同期漲跌，可為負（大盤該區間
上漲）——這是刻意設計，不是bug。

只 import 標準庫與 finmind_client，刻意不 import screener（screener.py 會
import 這個模組，import screener 會造成循環匯入）。整段查詢包 try/except，
絕不丟例外，失敗回傳同樣的 key 結構、值全為 None，比照 finmind_client／
screener 系列函式的既有慣例。

限制：Python 3.9 相容、僅標準庫。

2026-07-28（Phase 3B）：改為優先呼叫 twse_price_client.fetch_index_history()
（TWSE FMTQIK 官方端點，免額度），失敗才 fallback 回 FinMind——見
_fetch_benchmark() 內的 data_source 判斷。FinMind 呼叫路徑保留，不刪除。
"""
import bisect
import datetime
import time

import finmind_client
import twse_price_client

BENCHMARK_STOCK_ID = "TAIEX"

# 與 screener.PRICE_WINDOW_DAYS 應保持同一個值，但這裡不 import screener
# （見模組 docstring，避免循環匯入）。呼叫端（screener.py／market_scan.py）
# 一律明確傳入 window_days=screener.PRICE_WINDOW_DAYS，確保大盤跟個股用
# 同一個回看窗口；這個常數只是「沒傳 window_days 時」的獨立預設值。
WINDOW_DAYS = 120

# report_server.py 是長駐行程，短時間內重複請求同一頁不用每次都打 FinMind。
MEMO_TTL_SECONDS = 900

_memo = {"result": None, "fetched_at": 0.0, "window_days": None}


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _fetch_benchmark(data_dir=None, token=None, window_days=WINDOW_DAYS, price_cache=None):
    """查 TAIEX 股價、算窗口內回檔幅度（窗口內高點 vs 最新收盤）。

    2026-07-28（Phase 3B）：優先呼叫 twse_price_client.fetch_index_history()
    （TWSE FMTQIK 官方端點，免額度）；只有回傳 error（端點改版/網路問題/
    該窗口查無資料等任何原因）才 fallback 用 FinMind TaiwanStockPrice
    （既有路徑，保留不刪）。data_source 標記實際採用哪個來源
    （"twse_official" / "finmind_fallback"），查詢完全失敗時維持 None。

    邏輯跟 screener._drawdown() 對個股做的事一樣，這裡獨立實作一份（不 import
    screener，見模組 docstring）。絕不丟例外。
    """
    result = {"closes": None, "dates": None, "high_date": None, "high_price": None,
              "current_date": None, "current_close": None,
              "window_drawdown_pct": None, "data_source": None, "error": None}
    try:
        official = twse_price_client.fetch_index_history(
            window_days=window_days, cache=price_cache)
        if "error" not in official and official.get("prices"):
            prices = official["prices"]
            data_source = "twse_official"
            fallback_errors = []
        else:
            hist = finmind_client.get_stock_price_history(
                BENCHMARK_STOCK_ID, start_date=_days_ago(window_days),
                data_dir=data_dir, token=token)
            prices = hist.get("prices") or []
            data_source = "finmind_fallback"
            fallback_errors = hist.get("errors") or []

        valid = [p for p in prices if p.get("max") is not None
                 and p.get("close") is not None and p.get("date")]
        if not valid:
            result["error"] = ("TAIEX 無有效股價資料" +
                                ("：%s" % "；".join(fallback_errors) if fallback_errors else ""))
            return result
        valid.sort(key=lambda p: p["date"])
        result["dates"] = [p["date"] for p in valid]
        result["closes"] = [p["close"] for p in valid]
        high_row = max(valid, key=lambda p: p["max"])
        latest_row = valid[-1]
        result["high_price"] = high_row["max"]
        result["high_date"] = high_row["date"]
        result["current_close"] = latest_row["close"]
        result["current_date"] = latest_row["date"]
        if high_row["max"]:
            result["window_drawdown_pct"] = (
                (high_row["max"] - latest_row["close"]) / high_row["max"])
        result["data_source"] = data_source
        return result
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        result["error"] = "非預期錯誤：%s" % exc
        return result


def load_benchmark(data_dir=None, token=None, window_days=None, price_cache=None):
    """回傳 TAIEX 大盤基準資料（module 級 memo，TTL 900 秒）。

    只快取「成功」的結果——查詢失敗時不快取，讓下一次呼叫可以立刻重試，
    不用在 report_server.py 這種長駐行程裡卡住整整 900 秒才能恢復。
    window_days 改變時視為不同快取鍵，不會拿錯窗口的舊資料。

    price_cache：可選 dict，透傳給 twse_price_client（見該模組
    fetch_index_history docstring），供呼叫端（market_scan.run_scan）
    跨多檔個股共用同一份月資料 HTTP 回應快取。
    """
    window_days = window_days or WINDOW_DAYS
    now = time.time()
    cached = _memo["result"]
    if (cached is not None and _memo["window_days"] == window_days
            and now - _memo["fetched_at"] < MEMO_TTL_SECONDS):
        return cached
    result = _fetch_benchmark(data_dir=data_dir, token=token, window_days=window_days,
                              price_cache=price_cache)
    if result["error"] is None:
        _memo["result"] = result
        _memo["fetched_at"] = now
        _memo["window_days"] = window_days
    return result


def close_on_or_before(bench, date):
    """純函式：從 bench["dates"]/["closes"]（升冪排序）找「小於等於 date 的
    最後一筆收盤價」（bisect_right - 1）。bench 有 error、缺日期序列、或
    date 之前完全沒有資料，回傳 None，不丟例外、不臆測。"""
    if not bench or bench.get("error") or not bench.get("dates") or not date:
        return None
    dates = bench["dates"]
    idx = bisect.bisect_right(dates, date) - 1
    if idx < 0:
        return None
    return bench["closes"][idx]


def interval_drawdown(bench, start, end):
    """個股「高點日→最新日」同一區間，大盤的漲跌幅＝(c_start-c_end)/c_start。

    可為負（大盤該區間反而上漲）——這是刻意設計：個股在大盤上漲期間下跌時，
    超額跌幅＝個股回檔－(負的大盤跌幅) 會被正確放大，這正是要抓的「錯殺」訊號。
    任一端點查無資料則回傳 None。
    """
    c_start = close_on_or_before(bench, start)
    c_end = close_on_or_before(bench, end)
    if c_start is None or c_end is None or not c_start:
        return None
    return (c_start - c_end) / c_start


def excess_drawdown(stock_dd, bench, high_date, current_date):
    """回傳 (market_drawdown_pct, excess_drawdown_pct)。

    excess_drawdown_pct＝個股回檔－同期大盤跌幅，數值越大代表跌得比大盤兇
    越多。任一輸入缺值就回傳 (None, None)，不臆測、不丟例外。
    """
    if stock_dd is None:
        return None, None
    market_dd = interval_drawdown(bench, high_date, current_date)
    if market_dd is None:
        return None, None
    return market_dd, stock_dd - market_dd
