"""`us_stock_price_client.py` 測試——`get_quote`／`get_fundamentals`（FMP）
與 `get_quote_fallback`（yfinance，直接打 Yahoo Finance 公開端點，不裝
`yfinance` 套件本身，見該函式 docstring）。全程 mock `urllib.request.
urlopen`，不會真的打網路、不需要真實 API key。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import json
import os
import sys
import unittest
import unittest.mock
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_stock_price_client  # noqa: E402


def _mock_response(body_dict):
    resp = unittest.mock.MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(body_dict).encode("utf-8")
    return resp


class GetQuoteFallbackTest(unittest.TestCase):
    """`get_quote_fallback()`（yfinance／Yahoo Finance chart 端點）。"""

    def test_success_parses_price_and_change_pct(self):
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 286.96,
                        "previousClose": 305.11,
                    }
                }]
            }
        }
        with unittest.mock.patch(
                "urllib.request.urlopen",
                return_value=_mock_response(payload)) as mock_urlopen:
            result = us_stock_price_client.get_quote_fallback("NET")
        self.assertEqual(result["ticker"], "NET")
        self.assertEqual(result["close_price"], 286.96)
        self.assertEqual(result["source"], "yfinance")
        # (286.96 - 305.11) / 305.11 * 100 約 -5.95
        self.assertAlmostEqual(result["change_pct"], -5.95, places=1)
        # 確認真的呼叫了 Yahoo 的 chart 端點，不是巧合回傳
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("query1.finance.yahoo.com/v8/finance/chart/NET", called_url)

    def test_uses_chart_previous_close_when_previous_close_missing(self):
        """有些 ticker 的 meta 沒有 `previousClose`，只有
        `chartPreviousClose`——兩者擇一都要能算出 change_pct。"""
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 100.0,
                        "chartPreviousClose": 90.0,
                    }
                }]
            }
        }
        with unittest.mock.patch(
                "urllib.request.urlopen", return_value=_mock_response(payload)):
            result = us_stock_price_client.get_quote_fallback("AAPL")
        self.assertAlmostEqual(result["change_pct"], 11.11, places=1)

    def test_missing_previous_close_returns_none_change_pct_not_error(self):
        """兩個 previousClose 欄位都沒有：仍然回傳 close_price（有價格
        總比完全沒有好），change_pct 給 None，不視為整體失敗。"""
        payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 50.0}}]}}
        with unittest.mock.patch(
                "urllib.request.urlopen", return_value=_mock_response(payload)):
            result = us_stock_price_client.get_quote_fallback("XYZ")
        self.assertNotIn("error", result)
        self.assertEqual(result["close_price"], 50.0)
        self.assertIsNone(result["change_pct"])

    def test_malformed_response_returns_error_not_exception(self):
        """回應格式跟預期不符（例如 Yahoo 改版）：回傳 error，不拋例外
        炸掉呼叫端（比照本專案一貫的降級精神）。"""
        with unittest.mock.patch(
                "urllib.request.urlopen",
                return_value=_mock_response({"unexpected": "shape"})):
            result = us_stock_price_client.get_quote_fallback("NET")
        self.assertIn("error", result)

    def test_http_error_returns_error_not_exception(self):
        with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    "url", 404, "Not Found", {}, None)):
            result = us_stock_price_client.get_quote_fallback("BADTICKER")
        self.assertIn("error", result)
        self.assertIn("404", result["error"])

    def test_network_error_returns_error_not_exception(self):
        with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("timeout")):
            try:
                result = us_stock_price_client.get_quote_fallback("NET")
            except Exception as exc:  # noqa: BLE001
                self.fail("get_quote_fallback 不應拋出例外，實際拋出：%r" % exc)
        self.assertIn("error", result)


class GetQuoteMissingTokenTest(unittest.TestCase):
    """`get_quote()`（FMP 主要來源）在完全沒有 token 時的行為——不需要
    mock 網路，因為函式應該在打網路之前就先檢查 token。"""

    def test_no_token_anywhere_returns_error(self):
        with unittest.mock.patch.dict(os.environ, {"FMP_API_KEY": ""}, clear=False):
            os.environ.pop("FMP_API_KEY", None)
            with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
                result = us_stock_price_client.get_quote("NET", data_dir="/tmp/does-not-exist")
            mock_urlopen.assert_not_called()
        self.assertIn("error", result)
        self.assertIn("FMP_API_KEY", result["error"])


if __name__ == "__main__":
    unittest.main()
