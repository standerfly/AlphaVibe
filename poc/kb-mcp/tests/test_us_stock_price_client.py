"""`us_stock_price_client.py` 測試——`get_quote`／`get_fundamentals`（FMP，
mock `urllib.request.urlopen`）與 `get_quote_fallback`（`yfinance` 套件，
mock `yfinance.Ticker`）。全程不會真的打網路、不需要真實 API key。

**執行要用 AlphaVibe 自己的 `.venv`**（`yfinance` 只裝在這裡；本機預設
`python3` 指向另一個專案 `AI-stock-km-v1` 的虛擬環境，2026-09-08 才發現
這個既有環境落差——poc/kb-mcp/ 過去純標準庫不受影響，現在有了第一個
第三方依賴才浮現）：

    .venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_stock_price_client  # noqa: E402


class GetQuoteFallbackTest(unittest.TestCase):
    """`get_quote_fallback()`——2026-09-08 改用真正的 `yfinance` 套件
    （原本手刻直接打 Yahoo 端點被 HTTP 429 擋下，見該函式 docstring）。
    全程 mock `yfinance.Ticker`，不會真的呼叫 yfinance／連網路。
    **這個測試檔案需要 `yfinance` 是可 import 的**（`unittest.mock.
    patch("yfinance.Ticker", ...)` 用字串路徑指定 patch 目標時，本身
    就要先能 import 該模組——這跟 `get_quote_fallback()` 函式內部才
    `import yfinance`〔延後載入〕是兩回事，別搞混），所以要用裝了
    `yfinance` 的 `.venv`（見本檔案開頭）跑，不能用裸 `python3`。"""

    def _mock_ticker(self, fast_info):
        instance = unittest.mock.Mock()
        instance.fast_info = fast_info
        return unittest.mock.patch("yfinance.Ticker", return_value=instance)

    def test_success_parses_price_and_change_pct(self):
        with self._mock_ticker({"lastPrice": 286.96, "previousClose": 305.11}):
            result = us_stock_price_client.get_quote_fallback("NET")
        self.assertEqual(result["ticker"], "NET")
        self.assertEqual(result["close_price"], 286.96)
        self.assertEqual(result["source"], "yfinance")
        # (286.96 - 305.11) / 305.11 * 100 約 -5.95
        self.assertAlmostEqual(result["change_pct"], -5.95, places=1)

    def test_missing_previous_close_returns_none_change_pct_not_error(self):
        """`previousClose` 欄位缺失：仍然回傳 close_price（有價格總比
        完全沒有好），change_pct 給 None，不視為整體失敗。"""
        with self._mock_ticker({"lastPrice": 50.0}):
            result = us_stock_price_client.get_quote_fallback("XYZ")
        self.assertNotIn("error", result)
        self.assertEqual(result["close_price"], 50.0)
        self.assertIsNone(result["change_pct"])

    def test_missing_price_returns_error(self):
        """`fast_info` 裡連 `lastPrice` 都沒有（例如代號有效但當下沒有
        報價資料）：回傳 error，不假裝有資料。"""
        with self._mock_ticker({}):
            result = us_stock_price_client.get_quote_fallback("XYZ")
        self.assertIn("error", result)

    def test_yfinance_exception_returns_error_not_exception(self):
        """`yfinance` 對無效代號／網路問題丟出的例外型別不固定
        （2026-09-08 實測遇過 `KeyError`），一律要攔下轉成 error，
        不往外拋炸掉呼叫端（比照本專案一貫的降級精神）。"""
        with unittest.mock.patch(
                "yfinance.Ticker", side_effect=KeyError("currentTradingPeriod")):
            try:
                result = us_stock_price_client.get_quote_fallback("BADTICKER")
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
