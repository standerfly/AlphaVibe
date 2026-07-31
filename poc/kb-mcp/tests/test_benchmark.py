"""benchmark.py 測試：TAIEX 大盤資料源優先序（2026-07-28 Phase 3B）——
twse_price_client 官方端點（FMTQIK）優先，失敗才 fallback 回 FinMind；
module 級 memo 快取行為。全部用 mock，不打真實 API。
"""
import os
import sys
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import benchmark  # noqa: E402
import finmind_client  # noqa: E402
import twse_price_client  # noqa: E402


def _finmind_prices(rows):
    """rows: list of (date, max, close) → finmind_client.get_stock_price_history() 形狀。"""
    return {"stock_id": "TAIEX", "errors": [],
            "prices": [{"date": d, "max": mx, "close": c} for d, mx, c in rows]}


def _official_prices(rows):
    """rows: list of (date, close) → twse_price_client.fetch_index_history() 形狀
    （max 用 close 頂替，見 twse_price_client 模組docstring）。"""
    return {"prices": [{"date": d, "close": c, "max": c, "min": None, "open": None}
                       for d, c in rows]}


class FetchBenchmarkTest(unittest.TestCase):
    def setUp(self):
        # 每個測試獨立，不共用 module 級 memo（否則測試順序會互相汙染）。
        benchmark._memo["result"] = None
        benchmark._memo["fetched_at"] = 0.0
        benchmark._memo["window_days"] = None

    def test_official_endpoint_success_skips_finmind(self):
        official = _official_prices([("2026-06-01", 80.0), ("2026-07-01", 100.0)])
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value=official) as mock_official, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history") as mock_finmind:
            out = benchmark._fetch_benchmark()
        self.assertIsNone(out["error"])
        self.assertEqual(out["data_source"], "twse_official")
        self.assertEqual(out["high_price"], 100.0)
        self.assertEqual(out["current_close"], 100.0)
        mock_official.assert_called_once()
        mock_finmind.assert_not_called()

    def test_official_endpoint_failure_falls_back_to_finmind(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value={"error": "模擬官方端點失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_finmind_prices(
                    [("2026-06-01", 90.0, 80.0), ("2026-07-01", 100.0, 100.0)])) as mock_finmind:
            out = benchmark._fetch_benchmark()
        self.assertIsNone(out["error"])
        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertEqual(out["high_price"], 100.0)
        mock_finmind.assert_called_once()

    def test_both_sources_fail_returns_error_and_no_data_source(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value={"error": "官方端點失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value={"stock_id": "TAIEX", "errors": ["FinMind HTTP 402"]}):
            out = benchmark._fetch_benchmark()
        self.assertIsNotNone(out["error"])
        self.assertIsNone(out["data_source"])
        self.assertIn("402", out["error"])

    def test_official_empty_prices_treated_as_failure_triggers_fallback(self):
        """twse_price_client 回傳沒有 error key 但 prices 是空list（理論上
        該模組自己不會這樣回，但這裡驗證 benchmark 端的防禦邏輯）。"""
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value={"prices": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_finmind_prices(
                    [("2026-07-01", 100.0, 90.0)])) as mock_finmind:
            out = benchmark._fetch_benchmark()
        self.assertEqual(out["data_source"], "finmind_fallback")
        mock_finmind.assert_called_once()

    def test_window_drawdown_pct_computed_from_high_to_latest(self):
        official = _official_prices(
            [("2026-06-01", 100.0), ("2026-06-15", 120.0), ("2026-07-01", 90.0)])
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history", return_value=official):
            out = benchmark._fetch_benchmark()
        self.assertAlmostEqual(out["window_drawdown_pct"], (120.0 - 90.0) / 120.0)
        self.assertEqual(out["high_date"], "2026-06-15")
        self.assertEqual(out["current_date"], "2026-07-01")

    def test_unexpected_exception_not_raised(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                side_effect=RuntimeError("模擬非預期例外")):
            out = benchmark._fetch_benchmark()
        self.assertIn("非預期錯誤", out["error"])
        self.assertIsNone(out["data_source"])

    def test_price_cache_passed_through(self):
        cache = {}
        official = _official_prices([("2026-07-01", 100.0)])
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value=official) as mock_official:
            benchmark._fetch_benchmark(price_cache=cache)
        self.assertIs(mock_official.call_args.kwargs["cache"], cache)


class LoadBenchmarkMemoTest(unittest.TestCase):
    def setUp(self):
        benchmark._memo["result"] = None
        benchmark._memo["fetched_at"] = 0.0
        benchmark._memo["window_days"] = None

    def test_successful_result_is_memoized(self):
        official = _official_prices([("2026-07-01", 100.0)])
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value=official) as mock_official:
            first = benchmark.load_benchmark()
            second = benchmark.load_benchmark()
        self.assertEqual(first, second)
        mock_official.assert_called_once()  # 第二次應該吃 memo，不重打

    def test_failed_result_not_memoized_retries_next_call(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value={"error": "官方端點失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value={"stock_id": "TAIEX", "errors": ["斷網"]}) as mock_finmind:
            benchmark.load_benchmark()
            benchmark.load_benchmark()
        self.assertEqual(mock_finmind.call_count, 2)  # 失敗不快取，兩次都真的查

    def test_different_window_days_not_treated_as_cache_hit(self):
        official = _official_prices([("2026-07-01", 100.0)])
        with unittest.mock.patch.object(
                twse_price_client, "fetch_index_history",
                return_value=official) as mock_official:
            benchmark.load_benchmark(window_days=120)
            benchmark.load_benchmark(window_days=60)
        self.assertEqual(mock_official.call_count, 2)


if __name__ == "__main__":
    unittest.main()
