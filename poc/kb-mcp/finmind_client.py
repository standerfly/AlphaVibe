"""FinMind 個股基本面查詢（FR-008／FR-019，Q-016）。

僅標準庫（urllib）。token 來源優先序：參數 > 環境變數 FINMIND_TOKEN >
data_dir/finmind_token.txt。無 token 時仍嘗試呼叫（FinMind 匿名有低速額度），
失敗則回傳可讀的錯誤訊息，不丟例外——對應 product-spec §9「外部 API 失敗
不阻塞」的精神。
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://api.finmindtrade.com/api/v4/data"
TIMEOUT = 15


def _read_token(data_dir):
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        return token
    if data_dir:
        path = os.path.join(data_dir, "finmind_token.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
    return ""


def _fetch(dataset, stock_id, start_date, token, end_date=None):
    params = {"dataset": dataset}
    if stock_id:
        params["data_id"] = stock_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if token:
        params["token"] = token
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "alphavibe-kb-poc"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": "FinMind HTTP %s（%s）" % (exc.code, dataset)}
    except Exception as exc:  # 網路不通、逾時、JSON 壞掉
        return {"error": "FinMind 呼叫失敗（%s）：%s" % (dataset, exc)}
    if payload.get("status") not in (200, "200", None):
        return {"error": "FinMind 回應異常（%s）：%s"
                         % (dataset, payload.get("msg", payload.get("status")))}
    return {"data": payload.get("data", [])}


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def get_fundamentals(stock_id, data_dir=None, token=None):
    """回傳個股近期估值指標（PER/PBR/殖利率）與近 6 個月營收。"""
    token = token or _read_token(data_dir)
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    per = _fetch("TaiwanStockPER", stock_id, _days_ago(45), token)
    if "error" in per:
        result["errors"].append(per["error"])
    elif per["data"]:
        latest = per["data"][-1]
        raw_per = latest.get("PER")
        # 2026-07-31 查證：FinMind EPS 為負／無意義時，PER 回傳 0.0（不是
        # None）當作 sentinel，不是真實的本益比是0。這裡直接透傳會誤導
        # （見 review_engine._downside_risk 同一次查證的教訓），改標記為
        # None 並附 per_note 說明；PBR 不受影響（同一批資料裡 PBR 在虧損期
        # 仍是正常正值，book value 不會因單季虧損就歸零，不需要同樣處理）。
        result["valuation"] = {
            "date": latest.get("date"),
            "PER": raw_per if raw_per else None,
            "PBR": latest.get("PBR"),
            "dividend_yield": latest.get("dividend_yield"),
        }
        if raw_per == 0:
            result["valuation"]["per_note"] = (
                "FinMind當期PER原始值為0，通常代表EPS為負或無意義（例如"
                "虧損期），已改標記為None，不代表股價為0或本益比真的是0")
    else:
        result["errors"].append("TaiwanStockPER 無資料（代碼是否正確？）")

    revenue = _fetch("TaiwanStockMonthRevenue", stock_id, _days_ago(220), token)
    if "error" in revenue:
        result["errors"].append(revenue["error"])
    elif revenue["data"]:
        # 2026-07-31 查證：FinMind TaiwanStockMonthRevenue 的 `date` 欄位是
        # 「營收所屬月份+1、當月1號」（例如6月營收的 date 是 "2026-07-01"），
        # 不是公佈日期也不是營收所屬月份本身——單看 date 容易誤以為是7月
        # 營收。get_revenue_yoy() 用的是 FinMind 的 revenue_year/revenue_month
        # 欄位（=營收實際所屬月份），兩個工具口徑不同。這裡把 revenue_year/
        # revenue_month 也一併帶出，讓兩個工具的輸出可以互相對照，不用只靠
        # date 猜。保留 date 欄位不動，避免影響既有呼叫端。
        result["monthly_revenue"] = [
            {
                "date": row.get("date"),
                "revenue_year": row.get("revenue_year"),
                "revenue_month": row.get("revenue_month"),
                "revenue": row.get("revenue"),
            }
            for row in revenue["data"][-6:]
        ]

    if result["errors"] and "valuation" not in result and "monthly_revenue" not in result:
        result["hint"] = ("完全取不到數據。若為網路/額度問題：註冊 FinMind 免費帳號後，"
                          "把 token 存到環境變數 FINMIND_TOKEN 或 "
                          "poc/data/finmind_token.txt。知識庫功能不受影響。")
    return result


def get_stock_info(stock_id=None, data_dir=None, token=None):
    """查股票基本資料（產業分類/市場別）。不帶 stock_id 查全部，帶則查單檔。

    TaiwanStockInfo 是靜態參考表，非時間序列，不需要 start_date。
    """
    token = token or _read_token(data_dir)
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    info = _fetch("TaiwanStockInfo", stock_id, None, token)
    if "error" in info:
        result["errors"].append(info["error"])
    elif info["data"]:
        result["stocks"] = [
            {
                "stock_id": row.get("stock_id"),
                "stock_name": row.get("stock_name"),
                "industry_category": row.get("industry_category"),
                "type": row.get("type"),
                "date": row.get("date"),
            }
            for row in info["data"]
        ]
    else:
        result["errors"].append("TaiwanStockInfo 無資料（代碼是否正確？）")
    return result


def get_stock_price_history(stock_id, start_date=None, end_date=None, data_dir=None, token=None):
    """查個股股價歷史（OHLC）。start_date 預設近 90 天，end_date 預設今天。"""
    token = token or _read_token(data_dir)
    start_date = start_date or _days_ago(90)
    end_date = end_date or datetime.date.today().isoformat()
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    price = _fetch("TaiwanStockPrice", stock_id, start_date, token, end_date=end_date)
    if "error" in price:
        result["errors"].append(price["error"])
    elif price["data"]:
        result["prices"] = [
            {
                "date": row.get("date"),
                "stock_id": row.get("stock_id"),
                "Trading_Volume": row.get("Trading_Volume"),
                "Trading_money": row.get("Trading_money"),
                "open": row.get("open"),
                "max": row.get("max"),
                "min": row.get("min"),
                "close": row.get("close"),
                "spread": row.get("spread"),
                "Trading_turnover": row.get("Trading_turnover"),
            }
            for row in price["data"]
        ]
    else:
        result["errors"].append("TaiwanStockPrice 無資料（代碼/日期區間是否正確？）")
    return result


# 月營收年增率的抓取窗口（2026-08-19 修正，原為 400 天）：年增率要拿「去年
# 同月」比，窗口 N 個月只能算出 (N-12) 筆 YoY。400 天≈13 個月 → 只有 1 筆，
# 不足 review_engine.MIN_YOY_POINTS(3)，導致成長趨緩檢查從未真正運作過。
# 800 天≈26 個月 → 實測可算出 14 筆。改窄前請先確認 MIN_YOY_POINTS。
REVENUE_YOY_LOOKBACK_DAYS = 800


def get_revenue_yoy(stock_id, data_dir=None, token=None):
    """查個股月營收年增率（FinMind 不提供年增率欄位，自行以去年同月比對計算）。

    抓近 800 天（約 26 個月）；找不到去年同月資料的月份，yoy_growth 標 null，
    不臆測。

    ⚠️ 2026-08-19 修正（原本抓 400 天）：400 天≈13 個月，但年增率要拿「去年
    同月」比，13 個月的窗口裡**只有最新那 1 個月**找得到對應的去年同月——
    實測 2308 只算得出 1 筆 YoY。原註解寫「至少 13 個月才能算出每個月的年增率」
    是推理錯誤，13 個月只夠算 1 個月。後果是 `review_engine._growth_deceleration`
    要求至少 MIN_YOY_POINTS(3) 筆才判斷趨勢，永遠拿不到 → 這個檢查上線以來
    **從未真正運作過**，一律回「資料不足，無法判斷趨勢」。改抓 800 天後實測
    同一檔可算出 14 筆 YoY，趨勢判斷與「年增率是否加速」才有資料基礎。
    每次仍只打一次 API，不增加 FinMind 額度消耗（見 CLAUDE.md 2026-07-28 教訓）。
    """
    token = token or _read_token(data_dir)
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    revenue = _fetch("TaiwanStockMonthRevenue", stock_id,
                     _days_ago(REVENUE_YOY_LOOKBACK_DAYS), token)
    if "error" in revenue:
        result["errors"].append(revenue["error"])
        return result
    if not revenue["data"]:
        result["errors"].append("TaiwanStockMonthRevenue 無資料（代碼是否正確？）")
        return result

    rows = revenue["data"]
    by_year_month = {}
    for row in rows:
        y, m = row.get("revenue_year"), row.get("revenue_month")
        if y is not None and m is not None:
            by_year_month[(y, m)] = row.get("revenue")

    yoy_list = []
    for row in rows:
        y, m, rev = row.get("revenue_year"), row.get("revenue_month"), row.get("revenue")
        prev = by_year_month.get((y - 1, m)) if y is not None and m is not None else None
        yoy = None
        if prev not in (None, 0) and rev is not None:
            yoy = (rev - prev) / prev
        yoy_list.append({
            "revenue_month": m,
            "revenue_year": y,
            "revenue": rev,
            "yoy_growth": yoy,
        })
    result["revenue_yoy"] = yoy_list
    return result


# TaiwanStockInstitutionalInvestorsBuySell 的 name 欄位真實分類值（2026-07-18
# 對 2330 實測確認，非猜測）：Foreign_Investor（外資及陸資）、
# Foreign_Dealer_Self（外資自營商）、Investment_Trust（投信）、
# Dealer_self（自營商自行買賣）、Dealer_Hedging（自營商避險）。
# 「外資」廣義包含前兩者，foreign_net 加總這兩個分類。
FOREIGN_INVESTOR_NAMES = ("Foreign_Investor", "Foreign_Dealer_Self")


def get_institutional_trading(stock_id, start_date=None, end_date=None, data_dir=None, token=None):
    """查三大法人買賣超（長表格式：一列一個投資人類別），外加外資淨買賣超加總。"""
    token = token or _read_token(data_dir)
    start_date = start_date or _days_ago(30)
    end_date = end_date or datetime.date.today().isoformat()
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    trading = _fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id,
                      start_date, token, end_date=end_date)
    if "error" in trading:
        result["errors"].append(trading["error"])
        return result
    if not trading["data"]:
        result["errors"].append(
            "TaiwanStockInstitutionalInvestorsBuySell 無資料（代碼/日期區間是否正確？）")
        return result

    rows = trading["data"]
    result["trading"] = [
        {
            "date": row.get("date"),
            "stock_id": row.get("stock_id"),
            "name": row.get("name"),
            "buy": row.get("buy"),
            "sell": row.get("sell"),
        }
        for row in rows
    ]
    result["foreign_net"] = sum(
        (row.get("buy") or 0) - (row.get("sell") or 0)
        for row in rows if row.get("name") in FOREIGN_INVESTOR_NAMES
    )
    return result


def get_per_history(stock_id, days=730, data_dir=None, token=None):
    """查個股較長期歷史 PER（近 `days` 天，預設約 2 年），供 FR-051 下檔風險
    （PE壓縮模型）建立歷史區間分布用。`get_fundamentals` 的 45 天窗口只夠取
    最新一筆估值，不足以看出歷史分布，故另立此函式。

    TaiwanStockPER 是逐交易日資料，730 天窗口對長年上市股通常能取回數百筆；
    近期才掛牌的新股資料點會偏少，由呼叫端（review_engine）自行判斷資料
    是否足夠評估，本函式不臆測、不補值。
    """
    token = token or _read_token(data_dir)
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": []}

    per = _fetch("TaiwanStockPER", stock_id, _days_ago(days), token)
    if "error" in per:
        result["errors"].append(per["error"])
    elif per["data"]:
        result["per_history"] = [
            {
                "date": row.get("date"),
                "PER": row.get("PER"),
                "PBR": row.get("PBR"),
                "dividend_yield": row.get("dividend_yield"),
            }
            for row in per["data"]
        ]
    else:
        result["errors"].append("TaiwanStockPER 無資料（代碼是否正確？）")
    return result


def get_equity_attributable_to_owners(stock_id, data_dir=None, token=None):
    """查最近一期「歸屬於母公司業主之權益」（淨值），供興櫃股 PBR 粗估用
    （tpex_client.get_emerging_stock_valuation 呼叫）。

    抓近 730 天（財報為季/半年頻率，確保至少涵蓋到最新一期）。取 date 最大
    的一筆當最新值；查無資料回傳 equity=None 並在 errors 說明，不臆測。
    """
    token = token or _read_token(data_dir)
    result = {"stock_id": stock_id, "token_used": bool(token), "errors": [],
              "equity": None, "equity_date": None}

    balance = _fetch("TaiwanStockBalanceSheet", stock_id, _days_ago(730), token)
    if "error" in balance:
        result["errors"].append(balance["error"])
        return result
    rows = [row for row in balance["data"]
            if row.get("type") == "EquityAttributableToOwnersOfParent"]
    if not rows:
        result["errors"].append(
            "TaiwanStockBalanceSheet 無 EquityAttributableToOwnersOfParent 資料（代碼是否正確？）")
        return result

    latest = max(rows, key=lambda row: row.get("date") or "")
    result["equity"] = latest.get("value")
    result["equity_date"] = latest.get("date")
    return result
