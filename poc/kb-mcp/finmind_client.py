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


def _fetch(dataset, stock_id, start_date, token):
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
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
        result["valuation"] = {
            "date": latest.get("date"),
            "PER": latest.get("PER"),
            "PBR": latest.get("PBR"),
            "dividend_yield": latest.get("dividend_yield"),
        }
    else:
        result["errors"].append("TaiwanStockPER 無資料（代碼是否正確？）")

    revenue = _fetch("TaiwanStockMonthRevenue", stock_id, _days_ago(220), token)
    if "error" in revenue:
        result["errors"].append(revenue["error"])
    elif revenue["data"]:
        result["monthly_revenue"] = [
            {"date": row.get("date"), "revenue": row.get("revenue")}
            for row in revenue["data"][-6:]
        ]

    if result["errors"] and "valuation" not in result and "monthly_revenue" not in result:
        result["hint"] = ("完全取不到數據。若為網路/額度問題：註冊 FinMind 免費帳號後，"
                          "把 token 存到環境變數 FINMIND_TOKEN 或 "
                          "poc/data/finmind_token.txt。知識庫功能不受影響。")
    return result
