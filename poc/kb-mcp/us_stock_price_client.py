"""FMP（Financial Modeling Prep）美股報價／基本面查詢用戶端。

美股獨立投資系統（`specs/003-us-stocks`）唯一使用的價格資料來源模組。
**完全不 import 任何既有台股模組**（`finmind_client.py`／
`twse_price_client.py`／`tpex_client.py` 等）——只是參考它們的既有慣例
（HTTP client 選用 `urllib` 標準庫、失敗回傳 `{"error": ...}` 不拋例外、
token 讀取優先序，見 `research.md` §5），程式碼本身不共用一行。

**⚠️ 未經真實 API 呼叫驗證**：以下端點路徑與回應欄位名稱
（`price`／`changesPercentage`／`revenue`／`grossProfit`）是依 FMP 公開
API 文件的一般 schema 寫的，這次任務範圍沒有可用的 FMP API key 做實際
呼叫驗證——下一輪真正整測時，**務必**先用真實 key 打一次確認欄位名稱
與本檔案假設一致，不一致要照實際回應調整，不要假設這裡寫的就是對的。

備援來源（Alpha Vantage 或 yfinance，二擇一定案，見 `research.md` §1
待辦）：這一輪只留好可掛載的函式簽名（`get_quote_fallback`），**尚未
實作備援邏輯本身**——呼叫會如實回傳「尚未實作」的錯誤，不假裝有資料。

token 來源優先序：參數 > 環境變數 `FMP_API_KEY` > `data_dir/fmp_token.txt`
（比照 `finmind_client.py::_read_token` 的既有慣例，見 quickstart.md
「已知的技術待辦」）。
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_BASE_URL = "https://financialmodelingprep.com/api/v3"
TIMEOUT = 15
USER_AGENT = "alphavibe-us-stock-poc"

# 基本面年增率計算需要至少這麼多期季資料（本季 + 去年同季 = 間隔4季，
# 故至少要有5筆：index 0 是最新季、index 4 是剛好一年前的同一季）。
_FUNDAMENTALS_QUARTERS_NEEDED = 5


def _read_token(data_dir=None):
    token = os.environ.get("FMP_API_KEY", "").strip()
    if token:
        return token
    if data_dir:
        path = os.path.join(data_dir, "fmp_token.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
    return ""


def _fetch(path, params, token):
    query = dict(params or {})
    if token:
        query["apikey"] = token
    url = API_BASE_URL + path + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": "FMP HTTP %s（%s）" % (exc.code, path)}
    except Exception as exc:  # 網路不通、逾時、JSON 壞掉——不拋例外
        return {"error": "FMP 呼叫失敗（%s）：%s" % (path, exc)}
    return {"data": payload}


def get_quote(ticker, data_dir=None, token=None):
    """取得單一股票即時報價（收盤價／漲跌幅），FMP `/quote/{ticker}` 端點。

    回傳 `{"ticker":.., "close_price":.., "change_pct":.., "source": "fmp"}`
    或 `{"error": ...}`——失敗時不拋例外，比照既有 `finmind_client.py`
    慣例（`research.md` §4 降級模式）。
    """
    token = token or _read_token(data_dir)
    if not token:
        return {"error": "FMP_API_KEY 未設定（環境變數或 data_dir/fmp_token.txt）"}
    result = _fetch("/quote/%s" % urllib.parse.quote(ticker), {}, token)
    if "error" in result:
        return result
    data = result["data"]
    if not isinstance(data, list) or not data:
        return {"error": "FMP 無此股票資料：%s" % ticker}
    row = data[0]
    return {
        "ticker": ticker,
        "close_price": row.get("price"),
        "change_pct": row.get("changesPercentage"),
        "source": "fmp",
    }


def get_fundamentals(ticker, data_dir=None, token=None):
    """取得基本面快照（毛利率／營收年增率），供 `us_stock_scan.py` 寫入
    `us_price_snapshots` 的 `gaap_gross_margin`／`revenue_yoy` 欄位。

    用 FMP `/income-statement/{ticker}?period=quarter&limit=5` 取最近
    5 季損益表，`revenue`／`grossProfit` 算毛利率，最新季 vs 剛好一年前
    的同一季算年增率。資料不足 5 季時只算得出毛利率、年增率留 None——
    這不算錯誤，只是這次算不出來（沿用既有「查不到就是 None」的降級
    精神，不拋例外）。金鑰未設定或 HTTP 失敗一律回傳 `{"error": ...}`。

    `metric_type` 的完整可監控欄位清單留待後續任務依 FMP 實際可取得的
    欄位定案（見 quickstart.md「已知的技術待辦」），這裡先只算這兩項。
    """
    token = token or _read_token(data_dir)
    if not token:
        return {"error": "FMP_API_KEY 未設定（環境變數或 data_dir/fmp_token.txt）"}

    result = _fetch(
        "/income-statement/%s" % urllib.parse.quote(ticker),
        {"period": "quarter", "limit": _FUNDAMENTALS_QUARTERS_NEEDED}, token)
    if "error" in result:
        return result
    rows = result["data"]
    if not isinstance(rows, list) or not rows:
        return {"error": "FMP 無此股票損益表資料：%s" % ticker}

    latest = rows[0]
    revenue = latest.get("revenue")
    gross_profit = latest.get("grossProfit")
    gaap_gross_margin = (
        gross_profit / revenue if revenue and gross_profit is not None else None)

    revenue_yoy = None
    if len(rows) >= _FUNDAMENTALS_QUARTERS_NEEDED:
        year_ago = rows[_FUNDAMENTALS_QUARTERS_NEEDED - 1]
        prev_revenue = year_ago.get("revenue")
        if revenue and prev_revenue:
            revenue_yoy = (revenue - prev_revenue) / prev_revenue

    return {
        "ticker": ticker,
        "gaap_gross_margin": gaap_gross_margin,
        "revenue_yoy": revenue_yoy,
        "source": "fmp",
    }


def get_quote_fallback(ticker, data_dir=None):
    """備援報價來源留好的介面（Alpha Vantage 或 yfinance，二擇一定案，
    見 `research.md` §1 待辦）。**這一輪只留函式簽名，尚未實作備援邏輯
    本身**——呼叫時如實回傳「尚未實作」，不假裝有資料、不猜測回應格式。

    未來實作時預期回傳格式應與 `get_quote()` 一致：成功時
    `{"ticker":.., "close_price":.., "change_pct":.., "source": "alpha_vantage"}`
    （或 `"yfinance"`），失敗時 `{"error": ...}`。
    """
    return {
        "error": (
            "備援報價來源尚未實作（Alpha Vantage/yfinance 二擇一待定案，"
            "見 research.md §1）：%s" % ticker
        )
    }
