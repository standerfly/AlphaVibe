"""選股篩選：本益成長比(PEG)＋股價回檔幅度（第一層：候選清單篩選）。

篩選邏輯來源：framework_peg_deep_dip_concentration 哲學框架（觀察老芋頭
「清理門戶」策略沉澱，2026-07-20）——PEG<1 且股價從近期高點回檔>=40%，
視為同時符合這套框架的兩項可量化條件。

只負責算數字、不寫資料庫、不丟例外中斷整批。PER／最新一期營收年增率查詢
重用 fundamentals_client（官方優先＋FinMind備援，見下方2026-08-01說明）；
股價歷史／股票基本資料仍重用既有 finmind_client 的單股查詢函式
（get_stock_price_history／get_stock_info），純標準庫、Python 3.9 相容，
跟本專案既有模組風格一致。

2026-07-28（Phase 3B）：compute_drawdown() 的股價來源改為優先呼叫
twse_price_client（TWSE STOCK_DAY／TPEx tradingStock 官方端點，免額度），
失敗才 fallback 回 FinMind（見 _fetch_prices_with_fallback()）。
market_scan.py 呼叫端已知候選的 market（"TWSE"/"TPEx"），直接傳入指定
單一端點；screen_stocks()（使用者手動貼代碼，沒有market資訊）則採「先
試 TWSE 再試 TPEx」的雙重嘗試（choice (b)：比 (a) 多一次API呼叫但省去
額外查 get_stock_info 判斷市場的往返，且兩個市場官方端點都不消耗
FinMind額度，多打一次的成本很低）。

2026-08-01（來源選用邏輯稽核修正）：screen_stocks() 查PER／最新一期營收
年增率改呼叫 fundamentals_client（官方TWSE/TPEx批次端點優先，FinMind
降級為備援），不再直接寫死呼叫 finmind_client.get_fundamentals／
get_revenue_yoy——跟股價回檔幅度早就有的「官方優先」原則一致，見
fundamentals_client 模組docstring。fundamentals_client 對 market_scan 的
依賴是函式內延遲匯入（避免三模組互相匯入形成環，見該模組docstring說明），
這裡在模組頂層 import 沒有問題。
"""
import datetime

import benchmark
import finmind_client
import fundamentals_client
import twse_price_client

MAX_CODES = 50
PRICE_WINDOW_DAYS = 120
PEG_THRESHOLD = 1.0
DRAWDOWN_THRESHOLD = 0.40


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def parse_codes(text):
    """把使用者貼的一段文字(逗號、全形逗號、或換行分隔)解析成去重、去空白
    的代碼清單，保留原始輸入順序。"""
    if not text:
        return []
    raw = text.replace(",", "\n").replace("，", "\n").splitlines()
    seen = set()
    codes = []
    for item in raw:
        code = item.strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _latest_yoy_growth(revenue_yoy_rows):
    """從 get_revenue_yoy 的結果裡找「最新一筆非 null」的年增率。

    回傳 (yoy_growth 小數如0.2代表20%, 對應月份字串如"2026-06")；
    找不到就回傳 (None, None)，不臆測。
    """
    candidates = [r for r in revenue_yoy_rows
                  if r.get("yoy_growth") is not None
                  and r.get("revenue_year") is not None
                  and r.get("revenue_month") is not None]
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda r: (r["revenue_year"], r["revenue_month"]))
    return latest["yoy_growth"], "%d-%02d" % (latest["revenue_year"], latest["revenue_month"])


def _drawdown(prices):
    """回傳 (回檔幅度0~1小數, 波段高點, 高點日期, 目前收盤價, 目前日期)。

    回檔幅度 = (區間內最高的 max 價 - 最新一筆 close) / 最高的 max 價。
    查無有效資料時全部回傳 None，不可以除以零。
    """
    valid = [p for p in prices if p.get("max") is not None and p.get("close") is not None]
    if not valid:
        return None, None, None, None, None
    high_row = max(valid, key=lambda p: p["max"])
    latest_row = max(valid, key=lambda p: p.get("date") or "")
    high = high_row["max"]
    current = latest_row["close"]
    if not high:
        return None, high, high_row.get("date"), current, latest_row.get("date")
    drawdown = (high - current) / high
    return drawdown, high, high_row.get("date"), current, latest_row.get("date")


def _fetch_prices_with_fallback(code, market, data_dir, token, price_cache):
    """股價來源優先序：twse_price_client 官方端點 → FinMind fallback。

    回傳 (prices_list, data_source)。market 給定時（market_scan.py 呼叫端
    已知候選市場）只打對應那一個官方端點；market 為 None 時（screen_stocks()
    手動貼代碼，不知道市場別）依序試 TWSE 再試 TPEx。官方端點兩者都失敗
    （或 market 未知時兩個都失敗）才 fallback 回 FinMind
    get_stock_price_history，資料源標記為 "finmind_fallback"，就算最終
    仍查無資料也是這個標記（表示「這是我們最後嘗試過的來源」，不代表
    一定有資料——跟改動前 hist 查無資料時 error 仍為 None 的行為一致，
    由 drawdown_pct 等欄位是否為 None 表示資料是否足夠）。
    """
    markets_to_try = [market] if market in ("TWSE", "TPEx") else ["TWSE", "TPEx"]
    for mkt in markets_to_try:
        official = twse_price_client.fetch_price_history(
            code, mkt, window_days=PRICE_WINDOW_DAYS, cache=price_cache)
        if "error" not in official and official.get("prices"):
            return official["prices"], ("twse_official" if mkt == "TWSE" else "tpex_official")

    hist = finmind_client.get_stock_price_history(
        code, start_date=_days_ago(PRICE_WINDOW_DAYS),
        data_dir=data_dir, token=token)
    return hist.get("prices") or [], "finmind_fallback"


def compute_drawdown(code, data_dir=None, token=None, benchmark_series=None,
                      market=None, price_cache=None):
    """對單一代碼查近 PRICE_WINDOW_DAYS 天股價、算回檔幅度。

    從 screen_stocks() 抽出，供 market_scan.py 的第二層 Stage B 重用
    （第二層Stage A已經用TWSE/TPEx批次資料算出PER/PEG，只缺回檔幅度——
    批次API沒有歷史區間，仍要逐檔查補這一項）。內部包try/except，
    絕不丟例外，跟 finmind_client 系列函式的既有慣例一致。

    2026-07-28（Phase 3B）：股價來源改為優先呼叫 twse_price_client（見
    _fetch_prices_with_fallback()），FinMind 降級為備援。回傳新增
    data_source 欄位（"twse_official"/"tpex_official"/"finmind_fallback"）。

    market：可選，"TWSE"/"TPEx"。market_scan.py 已知候選市場時應傳入，
    只打對應官方端點；screen_stocks() 不知道市場別時傳 None，函式內部
    會依序試 TWSE 再試 TPEx。

    price_cache：可選 dict，透傳給 twse_price_client（月資料 HTTP 回應
    快取，key 為 (market, stock_id, year_month)），供呼叫端跨多檔股票、
    跨多個框架共用。

    benchmark_series：可選，已經抓好的 benchmark.load_benchmark() 回傳值。
    這個函式本身「不」呼叫 load_benchmark（避免每檔各打一次查大盤，
    大盤只該由呼叫端抓一次再逐檔傳進來）；不給就不算超額跌幅，
    market_drawdown_pct／excess_drawdown_pct 兩個 key 仍一定存在，值為 None。
    """
    try:
        prices, data_source = _fetch_prices_with_fallback(
            code, market, data_dir, token, price_cache)
        drawdown, high, high_date, current, current_date = _drawdown(prices)
        market_dd, excess_dd = None, None
        if benchmark_series is not None and drawdown is not None:
            market_dd, excess_dd = benchmark.excess_drawdown(
                drawdown, benchmark_series, high_date, current_date)
        return {"drawdown_pct": drawdown, "high_price": high, "high_date": high_date,
                "current_price": current, "current_date": current_date,
                "market_drawdown_pct": market_dd, "excess_drawdown_pct": excess_dd,
                "data_source": data_source, "error": None}
    except Exception as exc:
        return {"drawdown_pct": None, "high_price": None, "high_date": None,
                "current_price": None, "current_date": None,
                "market_drawdown_pct": None, "excess_drawdown_pct": None,
                "data_source": None, "error": "非預期錯誤：%s" % exc}


def meets_framework_thresholds(peg, drawdown, peg_threshold=PEG_THRESHOLD,
                                drawdown_min=DRAWDOWN_THRESHOLD, drawdown_max=None,
                                excess_drawdown=None, excess_drawdown_min=None):
    """純函式、無副作用：判斷是否符合框架門檻。

    peg_threshold/drawdown_min/drawdown_max/excess_drawdown_min 任一給 None
    代表「這個框架不看這項條件」。drawdown_max 是為了支援像
    framework_revenue_high_price_dip 這種「15~40%甜蜜區間」雙邊門檻的框架，
    跟 framework_peg_deep_dip_concentration 的「回檔>=40%」單邊門檻
    （drawdown_max=None）用同一個函式表達。excess_drawdown_min 只有給值時
    才檢查超額跌幅（個股回檔－同期大盤跌幅）下限。
    """
    if peg_threshold is not None and (peg is None or peg >= peg_threshold):
        return False
    if drawdown_min is not None and (drawdown is None or drawdown < drawdown_min):
        return False
    if drawdown_max is not None and (drawdown is None or drawdown > drawdown_max):
        return False
    if excess_drawdown_min is not None and (
            excess_drawdown is None or excess_drawdown < excess_drawdown_min):
        return False
    return True


def screen_stocks(codes, data_dir=None, token=None,
                   peg_threshold=PEG_THRESHOLD, drawdown_min=DRAWDOWN_THRESHOLD,
                   drawdown_max=None, framework_id=None, excess_drawdown_min=None):
    """對每檔代碼計算PEG與股價回檔幅度，回傳依PEG排序(null排最後)的結果。

    單檔查詢失敗(包含結構化errors與非預期例外)只記錄在該筆的"error"欄位，
    不可以讓整批中斷——這是這個專案今天已經在 refresh_holdings_prices 上
    踩過的坑，這裡從一開始就用同樣的try/except-per-item防護寫法。

    peg_threshold/drawdown_min/drawdown_max 預設值等於原本寫死的門檻常數，
    不傳這三個新參數時行為跟改動前完全一致（第二層 market_scan.py 呼叫
    這幾個新函式時才會傳入框架自訂門檻）。framework_id 只是回傳的
    thresholds 區塊裡的標籤，不影響篩選邏輯本身。

    codes 為空或超過 MAX_CODES 時直接短路回傳，不會呼叫 benchmark.load_benchmark
    ——沒有代碼要篩就不需要查大盤基準，也避免 MAX_CODES 防呆測試意外打到
    真實 API。
    """
    codes = list(dict.fromkeys(c.strip() for c in codes if c and c.strip()))
    if not codes:
        return {"results": [], "total": 0}
    if len(codes) > MAX_CODES:
        return {"results": [], "total": 0,
                "error": "一次最多篩選 %d 檔，目前輸入 %d 檔，請減少數量後再試"
                         % (MAX_CODES, len(codes))}

    price_cache = {}
    # fundamentals_client 內部呼叫的官方批次PER／營收端點回傳「全市場」資料，
    # 同一次 screen_stocks() 呼叫裡多檔代碼共用同一份批次回應，不用每檔各打
    # 一次（比照 market_scan.py 的 shared["batch"] 快取設計）。
    batch_cache = {}
    bench = benchmark.load_benchmark(
        data_dir=data_dir, token=token, window_days=PRICE_WINDOW_DAYS,
        price_cache=price_cache)

    names = {}
    if codes:
        try:
            info = finmind_client.get_stock_info(data_dir=data_dir, token=token)
            code_set = set(codes)
            for stock in info.get("stocks") or []:
                stock_id = stock.get("stock_id")
                if stock_id in code_set:
                    names[stock_id] = stock.get("stock_name")
        except Exception:
            pass  # 名稱查詢失敗不影響主要篩選結果，代碼本身還是能顯示

    results = []
    for code in codes:
        row = {"code": code, "name": names.get(code), "per": None,
               "per_data_source": None,
               "revenue_yoy": None, "revenue_period": None,
               "revenue_data_source": None,
               "drawdown_pct": None, "high_price": None, "high_date": None,
               "current_price": None, "current_date": None,
               "market_drawdown_pct": None, "excess_drawdown_pct": None,
               "data_source": None,
               "peg": None, "meets_framework": False, "error": None}
        try:
            # PER／最新一期營收年增率：官方優先＋FinMind備援，見
            # fundamentals_client 模組docstring（2026-08-01 來源選用邏輯
            # 稽核修正）。兩個函式內部各自 try/except，不會丟例外；
            # error 欄位只在「官方與FinMind都真的查詢失敗」時才有值
            # （純粹「查得到但這期算不出年增率」不算error，維持None，
            # 跟改動前 screen_stocks() 從不檢查 fund/rev errors 的既有
            # 靜默降級行為一致）。
            valuation = fundamentals_client.get_valuation(
                code, data_dir=data_dir, token=token, cache=batch_cache)
            per = valuation["per"]
            row["per"] = per
            row["per_data_source"] = valuation["data_source"]
            if valuation["error"]:
                row["error"] = valuation["error"]

            revenue = fundamentals_client.get_revenue_yoy_latest(
                code, data_dir=data_dir, token=token, cache=batch_cache)
            yoy = revenue["revenue_yoy"]
            row["revenue_yoy"] = yoy
            row["revenue_period"] = revenue["revenue_period"]
            row["revenue_data_source"] = revenue["data_source"]
            if revenue["error"] and not row["error"]:
                row["error"] = revenue["error"]

            drawdown_info = compute_drawdown(
                code, data_dir=data_dir, token=token, benchmark_series=bench,
                price_cache=price_cache)
            drawdown = drawdown_info["drawdown_pct"]
            row["drawdown_pct"] = drawdown
            row["high_price"] = drawdown_info["high_price"]
            row["high_date"] = drawdown_info["high_date"]
            row["current_price"] = drawdown_info["current_price"]
            row["current_date"] = drawdown_info["current_date"]
            row["market_drawdown_pct"] = drawdown_info["market_drawdown_pct"]
            row["excess_drawdown_pct"] = drawdown_info["excess_drawdown_pct"]
            row["data_source"] = drawdown_info["data_source"]
            if drawdown_info["error"] and not row["error"]:
                row["error"] = drawdown_info["error"]

            # PEG = 本益比 / 營收年增率(%數字，非小數)。yoy<=0 或缺資料時
            # 算不出來，維持 None，不可以除以零或用負成長率算出負PEG。
            if per is not None and yoy is not None and yoy > 0:
                row["peg"] = per / (yoy * 100)

            row["meets_framework"] = meets_framework_thresholds(
                row["peg"], drawdown, peg_threshold=peg_threshold,
                drawdown_min=drawdown_min, drawdown_max=drawdown_max,
                excess_drawdown=row["excess_drawdown_pct"],
                excess_drawdown_min=excess_drawdown_min)
        except Exception as exc:  # 單檔非預期錯誤不可讓整批中斷
            row["error"] = "非預期錯誤：%s" % exc
        results.append(row)

    results.sort(key=lambda r: (r["peg"] is None, r["peg"] if r["peg"] is not None else 0))
    return {"results": results, "total": len(results),
            "thresholds": {"framework_id": framework_id,
                           "peg_threshold": peg_threshold,
                           "drawdown_min": drawdown_min,
                           "drawdown_max": drawdown_max,
                           "excess_drawdown_min": excess_drawdown_min},
            "benchmark": {"window_drawdown_pct": bench.get("window_drawdown_pct"),
                         "high_date": bench.get("high_date"),
                         "high_price": bench.get("high_price"),
                         "current_date": bench.get("current_date"),
                         "current_close": bench.get("current_close"),
                         "error": bench.get("error")}}
