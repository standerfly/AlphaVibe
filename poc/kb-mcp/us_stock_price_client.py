"""FMP（Financial Modeling Prep）美股報價／基本面查詢用戶端。

美股獨立投資系統（`specs/003-us-stocks`）唯一使用的價格資料來源模組。
**完全不 import 任何既有台股模組**（`finmind_client.py`／
`twse_price_client.py`／`tpex_client.py` 等）——只是參考它們的既有慣例
（HTTP client 選用 `urllib` 標準庫、失敗回傳 `{"error": ...}` 不拋例外、
token 讀取優先序，見 `research.md` §5），程式碼本身不共用一行。

**2026-09-08 已用真實 API key 驗證過（PO申請key後第一次實測）**：原本
寫的 `/api/v3/quote/{ticker}` 路徑式端點在真實呼叫時回傳 HTTP 403
「Legacy Endpoint」——FMP 已於 2025-08-31 停用舊版 `/api/v3/` 端點，
改用 `/stable/` 前綴＋query string 帶 `symbol` 參數。已修正為實測
成功的正確格式：`https://financialmodelingprep.com/stable/quote?
symbol={ticker}&apikey=...`；`change_pct` 欄位名稱也修正
（`changePercentage`，原本寫的 `changesPercentage` 多了一個 s，實際
回應沒有這個欄位）。`income-statement` 端點的 `revenue`／`grossProfit`
欄位名稱原本的假設是對的，只有路徑格式要一併改成 query string。

備援來源：`yfinance` 套件（2026-09-08 真實 key 整測後定案，見
`get_quote_fallback()` docstring——原本手刻直接打 Yahoo 端點以維持零
依賴，但被 HTTP 429 擋下，改裝真正的套件）；`us_stock_scan.py` 的
`_scan_one_ticker()` 已接上：FMP 失敗時自動嘗試這個備援，備援也失敗
才真的視為這輪跳過。**另外發現**：FMP 免費層除了額度限制，還有股票
代碼白名單限制（大型股如 AAPL/MSFT/TSLA 可查，NET/GOOG/CRWD 這類回傳
HTTP 402「訂閱方案不含此股票」）——這代表 yfinance 備援在本系統的
實際使用情境下，觸發頻率會比原本設計時預期的「純額度備援」高得多，
不是次要角色。

token 來源優先序：參數 > 環境變數 `FMP_API_KEY` > `data_dir/fmp_token.txt`
（比照 `finmind_client.py::_read_token` 的既有慣例，見 quickstart.md
「已知的技術待辦」）。
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_BASE_URL = "https://financialmodelingprep.com/stable"
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
    """取得單一股票即時報價（收盤價／漲跌幅），FMP `/stable/quote`
    端點（`symbol` 帶在 query string，2026-09-08 用真實 key 實測確認
    格式，見本檔案開頭）。

    回傳 `{"ticker":.., "close_price":.., "change_pct":.., "source": "fmp"}`
    或 `{"error": ...}`——失敗時不拋例外，比照既有 `finmind_client.py`
    慣例（`research.md` §4 降級模式）。
    """
    token = token or _read_token(data_dir)
    if not token:
        return {"error": "FMP_API_KEY 未設定（環境變數或 data_dir/fmp_token.txt）"}
    result = _fetch("/quote", {"symbol": ticker}, token)
    if "error" in result:
        return result
    data = result["data"]
    if not isinstance(data, list) or not data:
        return {"error": "FMP 無此股票資料：%s" % ticker}
    row = data[0]
    return {
        "ticker": ticker,
        "close_price": row.get("price"),
        "change_pct": row.get("changePercentage"),
        "source": "fmp",
    }


def get_fundamentals(ticker, data_dir=None, token=None):
    """取得基本面快照（毛利率／營收年增率），供 `us_stock_scan.py` 寫入
    `us_price_snapshots` 的 `gaap_gross_margin`／`revenue_yoy` 欄位。

    用 FMP `/stable/income-statement?symbol={ticker}&period=quarter&
    limit=5` 取最近 5 季損益表，`revenue`／`grossProfit` 算毛利率，
    最新季 vs 剛好一年前
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
        "/income-statement",
        {"symbol": ticker, "period": "quarter",
         "limit": _FUNDAMENTALS_QUARTERS_NEEDED}, token)
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
    """備援報價來源：`yfinance` 套件（2026-09-08 真實 key 整測時定案）。

    **2026-09-08 改版**：這裡原本手刻直接呼叫 Yahoo Finance 公開圖表
    端點（不裝套件、避免拉進 `pandas`／`numpy` 依賴）。真實整測時發現
    手刻版本被 Yahoo 以 HTTP 429 擋下——即使延遲重試也一樣，因為 Yahoo
    現在要求正確的 session／crumb／TLS 指紋處理才放行程式化存取，
    `yfinance` 套件底層用 `curl_cffi` 處理這些細節。手刻重現這段的
    技術風險與維護成本比多裝一個依賴更高（見
    `poc/kb-mcp/requirements.txt` 的完整理由），PO 確認後改裝真正的
    `yfinance` 套件。`data_dir` 參數保留但用不到（yfinance 不需要
    API key），維持與 `get_quote()` 一致的呼叫介面。

    用 `Ticker.fast_info`（比完整 `.info` 輕量，只抓報價相關欄位，
    請求數少、速度快）。同樣是**非官方資料源**——`research.md` §1
    已經記錄過的已知風險（Yahoo 未提供正式 API 保證、ToS 灰色地帶），
    不是這裡新引入的風險。

    回傳格式與 `get_quote()` 一致：成功
    `{"ticker":.., "close_price":.., "change_pct":.., "source": "yfinance"}`，
    失敗 `{"error": ...}`（無效代號、網路失敗、`yfinance` 內部拋出的
    任何例外都在這裡被攔下轉成 error，不往外拋）。不提供基本面資料
    （毛利率/營收年增率）——`us_stock_scan.py` 呼叫端已經把基本面查詢
    獨立處理，這裡失敗不影響那邊。
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        close_price = info.get("lastPrice")
        prev_close = info.get("previousClose")
    except Exception as exc:  # yfinance 對無效代號/網路問題的例外型別
        # 不固定（曾見過 KeyError／requests例外等），一律攔下不往外拋，
        # 比照本檔案一貫的降級精神。
        return {"error": "yfinance 呼叫失敗（%s）：%s" % (ticker, exc)}

    if close_price is None:
        return {"error": "yfinance 無此股票資料：%s" % ticker}

    change_pct = None
    if prev_close:
        change_pct = round((close_price - prev_close) / prev_close * 100, 2)

    return {
        "ticker": ticker,
        "close_price": close_price,
        "change_pct": change_pct,
        "source": "yfinance",
    }
