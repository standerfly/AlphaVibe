"""選股篩選：本益成長比(PEG)＋股價回檔幅度（第一層：候選清單篩選）。

篩選邏輯來源：framework_peg_deep_dip_concentration 哲學框架（觀察老芋頭
「清理門戶」策略沉澱，2026-07-20）——PEG<1 且股價從近期高點回檔>=40%，
視為同時符合這套框架的兩項可量化條件。

只負責算數字、不寫資料庫、不丟例外中斷整批。重用既有 finmind_client 的
單股查詢函式（get_fundamentals／get_revenue_yoy／get_stock_price_history／
get_stock_info），純標準庫、Python 3.9 相容，跟本專案既有模組風格一致。
"""
import datetime

import finmind_client

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


def compute_drawdown(code, data_dir=None, token=None):
    """對單一代碼查近 PRICE_WINDOW_DAYS 天股價、算回檔幅度。

    從 screen_stocks() 抽出，供 market_scan.py 的第二層 Stage B 重用
    （第二層Stage A已經用TWSE/TPEx批次資料算出PER/PEG，只缺回檔幅度——
    批次API沒有歷史區間，仍要逐檔查FinMind補這一項）。內部包try/except，
    絕不丟例外，跟 finmind_client 系列函式的既有慣例一致。
    """
    try:
        hist = finmind_client.get_stock_price_history(
            code, start_date=_days_ago(PRICE_WINDOW_DAYS),
            data_dir=data_dir, token=token)
        drawdown, high, high_date, current, current_date = _drawdown(
            hist.get("prices") or [])
        return {"drawdown_pct": drawdown, "high_price": high, "high_date": high_date,
                "current_price": current, "current_date": current_date, "error": None}
    except Exception as exc:
        return {"drawdown_pct": None, "high_price": None, "high_date": None,
                "current_price": None, "current_date": None,
                "error": "非預期錯誤：%s" % exc}


def meets_framework_thresholds(peg, drawdown, peg_threshold=PEG_THRESHOLD,
                                drawdown_min=DRAWDOWN_THRESHOLD, drawdown_max=None):
    """純函式、無副作用：判斷是否符合框架門檻。

    peg_threshold/drawdown_min/drawdown_max 任一給 None 代表「這個框架不看
    這項條件」。drawdown_max 是為了支援像 framework_revenue_high_price_dip
    這種「15~30%甜蜜區間」雙邊門檻的框架，跟 framework_peg_deep_dip_concentration
    的「回檔>=40%」單邊門檻（drawdown_max=None）用同一個函式表達。
    """
    if peg_threshold is not None and (peg is None or peg >= peg_threshold):
        return False
    if drawdown_min is not None and (drawdown is None or drawdown < drawdown_min):
        return False
    if drawdown_max is not None and (drawdown is None or drawdown > drawdown_max):
        return False
    return True


def screen_stocks(codes, data_dir=None, token=None,
                   peg_threshold=PEG_THRESHOLD, drawdown_min=DRAWDOWN_THRESHOLD,
                   drawdown_max=None):
    """對每檔代碼計算PEG與股價回檔幅度，回傳依PEG排序(null排最後)的結果。

    單檔查詢失敗(包含結構化errors與非預期例外)只記錄在該筆的"error"欄位，
    不可以讓整批中斷——這是這個專案今天已經在 refresh_holdings_prices 上
    踩過的坑，這裡從一開始就用同樣的try/except-per-item防護寫法。

    peg_threshold/drawdown_min/drawdown_max 預設值等於原本寫死的門檻常數，
    不傳這三個新參數時行為跟改動前完全一致（第二層 market_scan.py 呼叫
    這幾個新函式時才會傳入框架自訂門檻）。
    """
    codes = list(dict.fromkeys(c.strip() for c in codes if c and c.strip()))
    if len(codes) > MAX_CODES:
        return {"results": [], "total": 0,
                "error": "一次最多篩選 %d 檔，目前輸入 %d 檔，請減少數量後再試"
                         % (MAX_CODES, len(codes))}

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
               "revenue_yoy": None, "revenue_period": None,
               "drawdown_pct": None, "high_price": None, "high_date": None,
               "current_price": None, "current_date": None,
               "peg": None, "meets_framework": False, "error": None}
        try:
            fund = finmind_client.get_fundamentals(code, data_dir=data_dir, token=token)
            per = fund.get("valuation", {}).get("PER") if fund.get("valuation") else None
            row["per"] = per

            rev = finmind_client.get_revenue_yoy(code, data_dir=data_dir, token=token)
            yoy, period = _latest_yoy_growth(rev.get("revenue_yoy") or [])
            row["revenue_yoy"] = yoy
            row["revenue_period"] = period

            drawdown_info = compute_drawdown(code, data_dir=data_dir, token=token)
            drawdown = drawdown_info["drawdown_pct"]
            row["drawdown_pct"] = drawdown
            row["high_price"] = drawdown_info["high_price"]
            row["high_date"] = drawdown_info["high_date"]
            row["current_price"] = drawdown_info["current_price"]
            row["current_date"] = drawdown_info["current_date"]
            if drawdown_info["error"]:
                row["error"] = drawdown_info["error"]

            # PEG = 本益比 / 營收年增率(%數字，非小數)。yoy<=0 或缺資料時
            # 算不出來，維持 None，不可以除以零或用負成長率算出負PEG。
            if per is not None and yoy is not None and yoy > 0:
                row["peg"] = per / (yoy * 100)

            row["meets_framework"] = meets_framework_thresholds(
                row["peg"], drawdown, peg_threshold=peg_threshold,
                drawdown_min=drawdown_min, drawdown_max=drawdown_max)
        except Exception as exc:  # 單檔非預期錯誤不可讓整批中斷
            row["error"] = "非預期錯誤：%s" % exc
        results.append(row)

    results.sort(key=lambda r: (r["peg"] is None, r["peg"] if r["peg"] is not None else 0))
    return {"results": results, "total": len(results)}
