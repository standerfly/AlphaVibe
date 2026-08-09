"""TWSE／TPEx 官方「月批次」歷史股價／大盤指數查詢，FinMind 的免額度備援
資料源（2026-07-28，Phase 3B）。

背景：FinMind 匿名查詢額度在密集測試時容易打光（HTTP 402），而
`screener.compute_drawdown()`／`benchmark.load_benchmark()` 需要頻繁查詢
個股與大盤的歷史股價才能算出回檔幅度／超額跌幅。TWSE／TPEx 另有一組
「官方月批次」端點，完全獨立於 FinMind 帳號額度，資料經 curl 實測與
FinMind 完全吻合（2026-07-28 實測：TAIEX 7/27收43,634.19、7/17收42,671.27；
TPEx 3260 威剛 7/27收402.00，皆與 FinMind 資料一致）：

- TWSE FMTQIK（www.twse.com.tw/rwd/zh/afterTrading/FMTQIK）：大盤(TAIEX)
  月歷史，只有收盤指數，沒有日內最高/最低
- TWSE STOCK_DAY（.../afterTrading/STOCK_DAY）：上市個股月歷史 OHLC
- TPEx tradingStock（www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock）：
  上櫃個股月歷史 OHLC

三個端點都是「查一個月給整月」，沒有單日或任意區間查詢參數；
`fetch_price_history()`／`fetch_index_history()` 這兩個高階函式負責依
window_days 逐月合併、去重、排序，並用日期下限裁到跟 FinMind
`start_date` 語意相同的窗口。

⚠️ TPEx tradingStock 的過去月份日期參數是「西元年」格式 `date=YYYY/MM/DD`
（day 值不影響回傳結果，一律回傳整月資料）——2026-07-28 實測：
`date=115/04/01`（民國年，直覺猜測格式）回傳 `{"stat":"參數輸入錯誤"}`；
`date=2026/04/01`（西元年）才成功，`date=2026/04`（不含day）也失敗。
不要沿用 tpex_client.py 其他 TPEx 端點慣用的民國年格式。

⚠️ TPEx tradingStock 查無資料時（例如誤傳 TWSE 上市代碼查詢）`stat`
欄位仍是 `"ok"`，但 `tables[0]["data"]` 是空陣列——不能只檢查 stat，
要一併檢查 data 是否為空（2026-07-28 對 2330 用 TPEx 端點查證過）。

⚠️ TWSE STOCK_DAY 對 TPEx 代碼（誤查）回傳 `{"stat":"很抱歉，沒有符合
條件的資料!"}`，乾淨失敗，`stat != "OK"` 即可判斷。

⚠️ TAIEX 大盤只有「收盤指數」、沒有日內最高/最低——這裡用收盤指數同時
當 prices 結構裡的 close 與 max（近似值，不是真正的日內高點）。
`benchmark._fetch_benchmark()` 找「窗口內最高點」時，本質上會變成
「窗口內收盤新高」而非「窗口內盤中新高」，跟改動前用 FinMind
TaiwanStockPrice（有真正日內 max）語意略有差異——這是改用官方端點
必須接受的取捨，不是 bug，呼叫端不需要特別處理，只是精確度略降。

回溯深度：2026-07-28 實測三個端點查 2020-07（5年前）皆正常回傳，
沒有「只能查最近幾個月」的隱藏限制。

Header：2026-07-28 用 urllib（無自訂 User-Agent）裸呼叫三個端點皆成功，
不是必需，但比照 finmind_client.py／tpex_client.py 既有慣例仍加上
User-Agent，降低未來被視為異常流量擋掉的風險。

僅標準庫（urllib），錯誤處理風格比照 finmind_client.py／tpex_client.py：
不丟例外、回傳 {"error": ...}。Python 3.9 相容。

2026-08-01（來源選用邏輯稽核修正）：新增 TWSE BWIBBU（個股歷史殖利率／
本益比／股價淨值比，`www.twse.com.tw/exchangeReport/BWIBBU`）——
`fetch_per_history()` 供 `fundamentals_client.get_per_history()` 取代
FinMind `get_per_history` 當第一優先來源（FR-051 下檔風險模型用）。
⚠️ BWIBBU 的日期欄位格式是中文全形「115年07月01日」，跟 STOCK_DAY／
FMTQIK 用的「115/07/01」斜線格式不同（2026-08-01 實測確認），故另立
`_roc_cjk_to_ad_date()` 解析，不擴充 `_roc_to_ad_date()` 的職責。
⚠️ 對 TPEx 代碼查 BWIBBU（2026-08-01 對 3260 實測）回傳
`{"stat":"很抱歉，沒有符合條件的資料!"}`，跟 STOCK_DAY 對 TPEx 代碼的
清爽失敗行為一致，`stat != "OK"` 即可判斷——BWIBBU 沒有對應的 TPEx
官方歷史端點，TPEx 股或 TWSE 查詢失敗一律由呼叫端 fallback FinMind。
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.request

TIMEOUT = 15
USER_AGENT = "alphavibe-kb-poc"

# 對外部服務的節流禮貌：目前沒有證據顯示 TWSE/TPEx 這兩個網域有明訂速率
# 限制，但密集批次查詢（一次全量篩選可能上千次請求）時加上輕量間隔，
# 降低被暫時封鎖的風險。只在真的打網路時 sleep，cache 命中不用等。
SLEEP_SECONDS = 0.15

TWSE_FMTQIK_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TPEX_TRADING_STOCK_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
TWSE_BWIBBU_URL = "https://www.twse.com.tw/exchangeReport/BWIBBU"

# window_days（曆日）換算回溯月數的除數＋buffer——沿用 Phase 3B 規格建議值。
# 20 是粗估「每月交易日數」，+2 個月是保守buffer，確保逐月合併後窗口起點
# 前有足夠資料可裁切，不會因為月初/月底邊界或缺交易日而窗口內資料不足。
_MONTHS_DIVISOR = 20
_MONTHS_BUFFER = 2


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _roc_to_ad_date(roc_str):
    """民國年日期字串（如 "115/07/01"）轉西元 ISO 格式（"2026-07-01"）。

    格式不符或轉換後不是合法日期則回傳 None，不丟例外。
    """
    if not isinstance(roc_str, str):
        return None
    parts = roc_str.split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0]) + 1911
        month = int(parts[1])
        day = int(parts[2])
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


_BWIBBU_DATE_RE = re.compile(r"^(\d+)年(\d+)月(\d+)日$")


def _roc_cjk_to_ad_date(date_str):
    """BWIBBU 專用：民國年中文日期字串（如 "115年07月01日"）轉西元 ISO
    格式（"2026-07-01"）。格式不符或轉換後不是合法日期回傳 None，不丟例外。
    見模組 docstring：BWIBBU 的日期格式跟 STOCK_DAY／FMTQIK 的斜線格式不同，
    不能沿用 `_roc_to_ad_date()`。
    """
    if not isinstance(date_str, str):
        return None
    match = _BWIBBU_DATE_RE.match(date_str)
    if not match:
        return None
    try:
        year = int(match.group(1)) + 1911
        month = int(match.group(2))
        day = int(match.group(3))
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _to_float(value):
    """數字字串轉 float，去除千分位逗號；空值/佔位符（"--"、"－"等）回傳
    None，不丟例外。"""
    if value in (None, "", "--", "---", "－", "X", "-"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _year_month_key(year, month):
    return "%04d%02d" % (year, month)


def _months_needed(window_days):
    return window_days // _MONTHS_DIVISOR + _MONTHS_BUFFER


def _recent_year_months(count):
    """回傳最近 count 個 (year, month)，由舊到新排序，最後一個是當月。"""
    today = datetime.date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(count):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    return months


def _throttled_get(url, cache_key=None, cache=None):
    """打單一端點 URL，回傳 {"payload": <解析後JSON>} 或 {"error": ...}。

    cache：可選 dict，key 命中直接回傳、不打網路也不 sleep；未命中才真的
    發送請求並節流。cache=None（預設）時完全不快取，每次都真的打網路。
    """
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        result = {"payload": payload}
    except urllib.error.HTTPError as exc:
        result = {"error": "HTTP %s（%s）" % (exc.code, url)}
    except Exception as exc:  # 網路不通、逾時、JSON 壞掉
        result = {"error": "呼叫失敗（%s）：%s" % (url, exc)}
    time.sleep(SLEEP_SECONDS)
    if cache is not None:
        cache[cache_key] = result
    return result


def fetch_twse_index_month(year_month, cache=None):
    """單月 TAIEX 大盤歷史（FMTQIK）。year_month："YYYYMM" 字串。

    回傳 {"prices": [{"date","close","max","min","open"}, ...]} 或
    {"error": ...}。max 用 close 頂替（見模組 docstring 的取捨說明）。
    """
    cache_key = ("TWSE_INDEX", "TAIEX", year_month)
    url = TWSE_FMTQIK_URL + "?date=%s01&response=json" % year_month
    fetched = _throttled_get(url, cache_key=cache_key, cache=cache)
    if "error" in fetched:
        return {"error": fetched["error"]}
    payload = fetched["payload"]
    if payload.get("stat") != "OK":
        return {"error": "TWSE FMTQIK 回應異常（%s）：%s" % (year_month, payload.get("stat"))}
    prices = []
    for row in payload.get("data", []):
        if len(row) < 5:
            continue
        date = _roc_to_ad_date(row[0])
        close = _to_float(row[4])
        if date is None or close is None:
            continue
        prices.append({"date": date, "close": close, "max": close,
                       "min": None, "open": None})
    if not prices:
        return {"error": "TWSE FMTQIK 該月無有效資料（%s）" % year_month}
    return {"prices": prices}


def fetch_twse_stock_month(stock_id, year_month, cache=None):
    """單月上市個股歷史 OHLC（STOCK_DAY）。

    stat != "OK" 一律視為失敗，含「查無符合條件的資料」（常見於誤傳
    TPEx 代碼）。回傳格式同 fetch_twse_index_month。
    """
    cache_key = ("TWSE", stock_id, year_month)
    url = TWSE_STOCK_DAY_URL + "?date=%s01&stockNo=%s&response=json" % (year_month, stock_id)
    fetched = _throttled_get(url, cache_key=cache_key, cache=cache)
    if "error" in fetched:
        return {"error": fetched["error"]}
    payload = fetched["payload"]
    if payload.get("stat") != "OK":
        return {"error": "TWSE STOCK_DAY 查無資料（%s，%s）：%s"
                         % (stock_id, year_month, payload.get("stat"))}
    prices = []
    for row in payload.get("data", []):
        if len(row) < 7:
            continue
        date = _roc_to_ad_date(row[0])
        close = _to_float(row[6])
        if date is None or close is None:
            continue
        prices.append({"date": date, "open": _to_float(row[3]), "max": _to_float(row[4]),
                       "min": _to_float(row[5]), "close": close})
    if not prices:
        return {"error": "TWSE STOCK_DAY 該月無有效資料（%s，%s）" % (stock_id, year_month)}
    return {"prices": prices}


def fetch_tpex_stock_month(stock_id, year_month, cache=None):
    """單月上櫃個股歷史 OHLC（tradingStock）。

    日期參數用西元年格式 date=YYYY/MM/DD（見模組docstring），day固定用
    01（回傳整月資料，day值不影響結果）。stat=="ok"但data為空陣列視為
    查無資料（誤查TWSE代碼時會出現這種情況，不能只看stat）。
    """
    cache_key = ("TPEx", stock_id, year_month)
    ad_year, month = year_month[:4], year_month[4:6]
    date_param = "%s/%s/01" % (ad_year, month)
    url = (TPEX_TRADING_STOCK_URL
           + "?code=%s&date=%s&response=json" % (stock_id, date_param))
    fetched = _throttled_get(url, cache_key=cache_key, cache=cache)
    if "error" in fetched:
        return {"error": fetched["error"]}
    payload = fetched["payload"]
    tables = payload.get("tables") or []
    if payload.get("stat") != "ok" or not tables:
        return {"error": "TPEx tradingStock 回應異常（%s，%s）：%s"
                         % (stock_id, year_month, payload.get("stat"))}
    rows = tables[0].get("data") or []
    if not rows:
        return {"error": "TPEx tradingStock 查無資料（%s，%s，可能非上櫃代碼或無交易）"
                         % (stock_id, year_month)}
    prices = []
    for row in rows:
        if len(row) < 7:
            continue
        date = _roc_to_ad_date(row[0])
        close = _to_float(row[6])
        if date is None or close is None:
            continue
        prices.append({"date": date, "open": _to_float(row[3]), "max": _to_float(row[4]),
                       "min": _to_float(row[5]), "close": close})
    if not prices:
        return {"error": "TPEx tradingStock 該月無有效資料（%s，%s）" % (stock_id, year_month)}
    return {"prices": prices}


def fetch_twse_per_month(stock_id, year_month, cache=None):
    """單月上市個股歷史PER/PBR/殖利率（BWIBBU，僅TWSE，見模組 docstring）。

    fields＝["日期","殖利率(%)","股利年度","本益比","股價淨值比","財報年/季"]
    （2026-08-01 curl 實測確認），data 每列對應索引：
    [0]日期(中文民國格式) [1]殖利率 [2]股利年度 [3]本益比 [4]股價淨值比
    [5]財報年/季。stat != "OK" 一律視為失敗，含「查無符合條件的資料」
    （TPEx代碼誤查時的清爽失敗，見模組 docstring）。
    """
    cache_key = ("TWSE_PER", stock_id, year_month)
    url = TWSE_BWIBBU_URL + "?date=%s01&stockNo=%s&response=json" % (year_month, stock_id)
    fetched = _throttled_get(url, cache_key=cache_key, cache=cache)
    if "error" in fetched:
        return {"error": fetched["error"]}
    payload = fetched["payload"]
    if payload.get("stat") != "OK":
        return {"error": "TWSE BWIBBU 查無資料（%s，%s）：%s"
                         % (stock_id, year_month, payload.get("stat"))}
    per_history = []
    for row in payload.get("data", []):
        if len(row) < 6:
            continue
        date = _roc_cjk_to_ad_date(row[0])
        per = _to_float(row[3])
        if date is None or per is None:
            continue
        per_history.append({"date": date, "PER": per, "PBR": _to_float(row[4]),
                            "dividend_yield": _to_float(row[1])})
    if not per_history:
        return {"error": "TWSE BWIBBU 該月無有效資料（%s，%s）" % (stock_id, year_month)}
    return {"per_history": per_history}


def fetch_per_history(stock_id, window_days=730, cache=None):
    """高階函式：TWSE個股歷史PER序列，依 window_days 回推月數、逐月合併
    去重排序（重用 `_merge_months`／`_recent_year_months`／`_months_needed`，
    邏輯跟 fetch_price_history 一致，只是資料集與 result_key 不同）。

    僅支援TWSE（BWIBBU沒有對應TPEx官方端點，見模組docstring）——TPEx股票
    查詢會查無資料回傳error，呼叫端（fundamentals_client.get_per_history）
    據此fallback FinMind get_per_history，這裡不用先判斷市場別，直接嘗試
    即可（跟STOCK_DAY對TPEx代碼的清爽失敗行為一致）。

    回傳 {"per_history": [...], "stock_id": stock_id} 或 {"error": ...}；
    格式對齊 finmind_client.get_per_history 的 per_history 結構（date/PER/
    PBR/dividend_yield），讓下游 review_engine._downside_risk 可以直接
    替換資料源，不需要改讀取邏輯。
    """
    months = _recent_year_months(_months_needed(window_days))
    by_date, month_errors = _merge_months(fetch_twse_per_month, months, cache,
                                          stock_id=stock_id, result_key="per_history")
    if not by_date:
        return {"error": "TWSE %s BWIBBU官方端點全數月份查無資料：%s"
                         % (stock_id, "；".join(month_errors) or "無詳細原因")}
    cutoff = _days_ago(window_days)
    per_history = sorted((row for row in by_date.values() if row["date"] >= cutoff),
                         key=lambda r: r["date"])
    if not per_history:
        return {"error": "TWSE %s BWIBBU資料都早於窗口起點（%s）" % (stock_id, cutoff)}
    return {"per_history": per_history, "stock_id": stock_id}


def _merge_months(fetch_month_fn, months, cache, stock_id=None, result_key="prices"):
    """共用邏輯：逐月呼叫 fetch_month_fn、依日期去重合併。回傳
    (by_date dict, 月份層級的錯誤訊息 list)。stock_id 為 None 時
    fetch_month_fn 只吃 year_month 一個參數（給 TAIEX 用）。

    result_key（2026-08-01 新增，預設 "prices" 維持既有呼叫不變）：
    fetch_month_fn 成功時回傳 dict 裡實際的清單欄位名——`fetch_per_history()`
    重用這個迴圈邏輯合併 BWIBBU 歷史PER月資料時，該欄位叫 "per_history"
    不是 "prices"（避免用「prices」這個名字裝PER資料造成誤導），故加這個
    參數讓同一份合併邏輯可以服務兩種資料，不必另外複製一份迴圈。
    """
    by_date = {}
    month_errors = []
    for year, month in months:
        ym = _year_month_key(year, month)
        result = (fetch_month_fn(ym, cache=cache) if stock_id is None
                  else fetch_month_fn(stock_id, ym, cache=cache))
        if "error" in result:
            month_errors.append(result["error"])
            continue
        for row in result[result_key]:
            by_date[row["date"]] = row
    return by_date, month_errors


def fetch_price_history(stock_id, market, window_days=120, cache=None):
    """高階函式：依 window_days 回推月數，逐月合併去重排序，回傳格式
    對齊 finmind_client.get_stock_price_history 的 prices 結構（含
    date/close/max/min/open 等鍵名），讓下游可以直接替換資料源。

    market 必須是 "TWSE" 或 "TPEx"（呼叫端負責市場判斷，這裡只負責照
    給定市場打對應端點）。回傳 {"prices": [...], "stock_id": stock_id}
    或 {"error": ...}——單月失敗不影響其他月份，只有全部月份都拿不到
    有效資料、或裁完窗口後空無一筆時才回傳 error。
    """
    if market not in ("TWSE", "TPEx"):
        return {"error": "未知市場別：%s（僅支援 TWSE/TPEx）" % market}
    fetch_month_fn = fetch_twse_stock_month if market == "TWSE" else fetch_tpex_stock_month
    months = _recent_year_months(_months_needed(window_days))
    by_date, month_errors = _merge_months(fetch_month_fn, months, cache, stock_id=stock_id)
    if not by_date:
        return {"error": "%s %s 官方端點全數月份查無資料：%s"
                         % (market, stock_id, "；".join(month_errors) or "無詳細原因")}
    cutoff = _days_ago(window_days)
    prices = sorted((row for row in by_date.values() if row["date"] >= cutoff),
                    key=lambda r: r["date"])
    if not prices:
        return {"error": "%s %s 官方端點資料都早於窗口起點（%s）" % (market, stock_id, cutoff)}
    return {"prices": prices, "stock_id": stock_id}


def fetch_index_history(window_days=120, cache=None):
    """TAIEX 大盤歷史，固定呼叫 FMTQIK，邏輯同 fetch_price_history。"""
    months = _recent_year_months(_months_needed(window_days))
    by_date, month_errors = _merge_months(fetch_twse_index_month, months, cache)
    if not by_date:
        return {"error": "TAIEX 官方端點全數月份查無資料：%s"
                         % ("；".join(month_errors) or "無詳細原因")}
    cutoff = _days_ago(window_days)
    prices = sorted((row for row in by_date.values() if row["date"] >= cutoff),
                    key=lambda r: r["date"])
    if not prices:
        return {"error": "TAIEX 官方端點資料都早於窗口起點（%s）" % cutoff}
    return {"prices": prices, "stock_id": "TAIEX"}
