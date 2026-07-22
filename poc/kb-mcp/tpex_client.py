"""櫃買中心（TPEx）興櫃股估值查詢——PER/PBR 粗估。

背景：FinMind 的 TaiwanStockPER 資料集不涵蓋興櫃股（已實測 6826 和淞回傳
0 筆）。TPEx OpenAPI（免 token、純 JSON）有興櫃股當日行情/EPS排名/資本額
排名三個端點，可組出粗估 PER/PBR；PBR 用的每股淨值另外呼叫 FinMind
TaiwanStockBalanceSheet（見 finmind_client.get_equity_attributable_to_owners）。

僅標準庫（urllib），錯誤處理風格比照 finmind_client.py：不丟例外、回傳
{"error": ...}。TPEx OpenAPI 不需 token，但仍加 User-Agent header
（部分政府/準官方 API 沒有 UA 會拒絕請求）。

⚠️ 興櫃股估值資料特性遠不如正式上市櫃股嚴謹：
- EPS 僅半年報/年報揭露，非 TTM（近四季）基礎，PER 精確度較低
- 這三個端點都不含「流通股數」，PBR 用「資本額(百萬元)÷10元面額」估算
  股數，非實際流通股數，特殊股本結構（如面額非 10 元）會有誤差
get_emerging_stock_valuation() 的回傳一定帶 caveats 欄位說明這些限制，
呼叫端（AI/使用者）不可把回傳的 PER/PBR 當成嚴謹估值使用。
"""
import datetime
import json
import urllib.error
import urllib.request

import finmind_client

BASE_URL = "https://www.tpex.org.tw/openapi/v1"
TIMEOUT = 15
PAR_VALUE = 10  # 股票面額假設（新臺幣元）；多數上櫃/興櫃股面額為 10 元

ENDPOINTS = {
    "latest_statistics": BASE_URL + "/tpex_esb_latest_statistics",
    "eps_rank": BASE_URL + "/tpex_esb_eps_rank",
    "capitals_rank": BASE_URL + "/tpex_esb_capitals_rank",
}

CAVEATS = (
    "興櫃公司僅揭露半年報/年報，EPS非TTM（近四季）基礎，PER精確度低於正式上市櫃股",
    "PBR的流通股數以資本額÷10元面額估算，非實際流通股數，特殊股本結構可能有誤差",
)


def roc_date_to_iso(roc_date):
    """民國年日期字串（如 "1150717"）轉西元 ISO 格式（"2026-07-17"）。

    格式不符（非 7 碼純數字）或轉換後不是合法日期則回傳 None，不丟例外。

    注意：TPEx 各端點的 Date 欄位語意不一致，不能一概當「資料所屬期間」。
    latest_statistics 的 Date 是實際成交日；eps_rank／capitals_rank 的
    Date 經實測（2026-07-19 對 6826 查證：EPS 回傳 Date="1150719"，等於
    查詢當下日期）等於「資料更新/查詢日」，*不是*財報所屬期間終止日——
    呼叫端不應把這個欄位當成 EPS 半年報/年報的期間依據，只能當作
    「這筆排名資料何時被回報」的參考日期。
    """
    if not isinstance(roc_date, str) or len(roc_date) != 7 or not roc_date.isdigit():
        return None
    try:
        year = int(roc_date[:3]) + 1911
        month = int(roc_date[3:5])
        day = int(roc_date[5:7])
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _fetch(endpoint_key):
    url = ENDPOINTS[endpoint_key]
    req = urllib.request.Request(url, headers={"User-Agent": "alphavibe-kb-poc"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": "TPEx HTTP %s（%s）" % (exc.code, endpoint_key)}
    except Exception as exc:  # 網路不通、逾時、JSON 壞掉
        return {"error": "TPEx 呼叫失敗（%s）：%s" % (endpoint_key, exc)}
    if not isinstance(payload, list):
        return {"error": "TPEx 回應格式異常（%s，非陣列）" % endpoint_key}
    return {"data": payload}


def _find_by_code(rows, stock_id):
    for row in rows:
        if row.get("SecuritiesCompanyCode") == stock_id:
            return row
    return None


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_emerging_stock_valuation(stock_id, data_dir=None):
    """興櫃股估值粗估（PER/PBR）。資料源：TPEx 興櫃三端點＋FinMind 淨值。

    - price/eps 分別來自 latest_statistics／eps_rank，任一查無資料則對應
      欄位為 None 並記錄到 errors，PER 不強算
    - EPS<=0 時不計算 PER（避免除以零或負數誤導），記錄到 errors
    - estimated_shares 用 capitals_rank 的資本額(百萬元)÷10元面額估算
    - book_value（每股淨值粗估）＝ FinMind 淨值 ÷ estimated_shares；
      PBR ＝ price ÷ book_value；任一環節缺資料則 book_value/pbr 為 None
    - 回傳一定含 caveats（精確度限制說明），呼叫端須轉達給使用者
    """
    result = {
        "stock_id": stock_id, "name": None,
        "price": None, "price_date": None,
        "eps": None, "eps_period": None,
        "per": None,
        "estimated_shares": None,
        "book_value": None, "book_value_date": None,
        "pbr": None,
        "caveats": list(CAVEATS),
        "errors": [],
    }

    price_resp = _fetch("latest_statistics")
    eps_resp = _fetch("eps_rank")
    cap_resp = _fetch("capitals_rank")

    price_row = eps_row = cap_row = None

    if "error" in price_resp:
        result["errors"].append(price_resp["error"])
    else:
        price_row = _find_by_code(price_resp["data"], stock_id)
        if price_row is None:
            result["errors"].append("興櫃當日行情查無代碼 %s（是否為興櫃股？代碼是否正確？）" % stock_id)

    if "error" in eps_resp:
        result["errors"].append(eps_resp["error"])
    else:
        eps_row = _find_by_code(eps_resp["data"], stock_id)
        if eps_row is None:
            result["errors"].append("興櫃EPS排名查無代碼 %s" % stock_id)

    if "error" in cap_resp:
        result["errors"].append(cap_resp["error"])
    else:
        cap_row = _find_by_code(cap_resp["data"], stock_id)
        if cap_row is None:
            result["errors"].append("興櫃資本額排名查無代碼 %s" % stock_id)

    if price_row is None and eps_row is None and cap_row is None:
        result["errors"].append("三個 TPEx 興櫃端點皆查無此代碼，可能不是興櫃股")
        return result

    if price_row:
        result["name"] = price_row.get("CompanyName")
        result["price"] = _to_float(price_row.get("LatestPrice"))
        result["price_date"] = roc_date_to_iso(price_row.get("Date"))
        if result["price"] is None:
            result["errors"].append("興櫃當日行情price欄位無法解析（可能當日無成交）")

    if eps_row:
        result["name"] = result["name"] or eps_row.get("CompanyName")
        result["eps"] = _to_float(eps_row.get("EPS"))
        result["eps_period"] = roc_date_to_iso(eps_row.get("Date"))
        if result["eps"] is None:
            result["errors"].append("興櫃EPS排名EPS欄位無法解析")

    price, eps = result["price"], result["eps"]
    if price is not None and eps is not None:
        if eps <= 0:
            result["errors"].append("EPS<=0（%.2f），不計算PER避免誤導" % eps)
        else:
            result["per"] = round(price / eps, 2)
    else:
        result["errors"].append("價格或EPS缺資料，PER無法計算")

    estimated_shares = None
    if cap_row:
        capital = _to_float(cap_row.get("Capital"))  # 單位：百萬元
        if capital is not None and capital > 0:
            estimated_shares = (capital * 1_000_000) / PAR_VALUE
            result["estimated_shares"] = estimated_shares
        else:
            result["errors"].append("興櫃資本額排名Capital欄位無法解析，無法估算股數")

    equity_info = finmind_client.get_equity_attributable_to_owners(stock_id, data_dir=data_dir)
    if equity_info.get("errors"):
        result["errors"].extend("FinMind淨值查詢：%s" % e for e in equity_info["errors"])
    equity = equity_info.get("equity")

    if equity is not None and estimated_shares:
        book_value = equity / estimated_shares
        result["book_value"] = round(book_value, 2)
        result["book_value_date"] = equity_info.get("equity_date")
        if price is not None and book_value > 0:
            result["pbr"] = round(price / book_value, 2)
        elif price is not None:
            result["errors"].append("估算每股淨值<=0，不計算PBR")
    elif equity is None:
        result["errors"].append("PBR無法計算：FinMind查無淨值資料")
    elif not estimated_shares:
        result["errors"].append("PBR無法計算：估算股數缺資料")

    return result
