"""`us_stock_scan.py` 測試：mock price client，驗證單一股票失敗時其餘
股票仍正常寫入（graceful degradation，比照 market_scan.py 的既有降級
模式測試精神）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_stock_scan  # noqa: E402
import us_stock_price_client  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402


def _fake_get_quote(ticker, data_dir=None, token=None):
    if ticker == "BAD":
        return {"error": "FMP HTTP 402（配額用盡）"}
    return {"ticker": ticker, "close_price": 100.0 + len(ticker),
            "change_pct": 1.5, "source": "fmp"}


def _fake_get_fundamentals(ticker, data_dir=None, token=None):
    return {"ticker": ticker, "gaap_gross_margin": 0.75,
            "revenue_yoy": 0.12, "source": "fmp"}


class RunScanGracefulDegradationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-scan-test-")
        store = USStockStore(self.tmp)
        # 三檔追蹤中股票：兩檔會成功、一檔（BAD）模擬額度用盡失敗。
        store.save_trade(ticker="NET", trade_date="2026-08-05",
                          action="buy", shares=10, price=298.40)
        store.save_watch_condition(ticker="CRWD", metric_type="price",
                                    comparator="gt", threshold=400)
        store.save_watch_condition(ticker="BAD", metric_type="price",
                                    comparator="lt", threshold=100)
        store.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_one_ticker_failure_does_not_block_others(self):
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        by_ticker = {row["ticker"]: row for row in result["results"]}
        self.assertEqual(set(by_ticker.keys()), {"NET", "CRWD", "BAD"})

        self.assertTrue(by_ticker["NET"]["saved"])
        self.assertIsNone(by_ticker["NET"]["error"])
        self.assertTrue(by_ticker["CRWD"]["saved"])
        self.assertIsNone(by_ticker["CRWD"]["error"])

        self.assertFalse(by_ticker["BAD"]["saved"])
        self.assertIsNotNone(by_ticker["BAD"]["error"])

    def test_failed_ticker_leaves_no_snapshot_row_others_written(self):
        """額度用盡的股票當天完全沒有 us_price_snapshots 紀錄（歷史缺口，
        data-model.md §4 的預期行為），成功的股票正常寫入。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        store = USStockStore(self.tmp)
        try:
            net_snapshots = store.list_price_snapshots("NET")
            crwd_snapshots = store.list_price_snapshots("CRWD")
            bad_snapshots = store.list_price_snapshots("BAD")
        finally:
            store.close()

        self.assertEqual(len(net_snapshots), 1)
        self.assertEqual(net_snapshots[0]["snapshot_date"], result["snapshot_date"])
        self.assertEqual(len(crwd_snapshots), 1)
        self.assertEqual(len(bad_snapshots), 0)

    def test_fundamentals_failure_does_not_block_price_write(self):
        """基本面查詢失敗不影響報價本身寫入——兩者是獨立欄位。"""
        def failing_fundamentals(ticker, data_dir=None, token=None):
            return {"error": "FMP 無此股票損益表資料：%s" % ticker}

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=failing_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        by_ticker = {row["ticker"]: row for row in result["results"]}
        self.assertTrue(by_ticker["NET"]["saved"])
        self.assertIsNone(by_ticker["NET"]["gaap_gross_margin"])
        self.assertIsNone(by_ticker["NET"]["revenue_yoy"])


class MainCliExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-scan-test-")
        store = USStockStore(self.tmp)
        store.save_trade(ticker="NET", trade_date="2026-08-05",
                          action="buy", shares=10, price=298.40)
        store.save_watch_condition(ticker="BAD", metric_type="price",
                                    comparator="lt", threshold=100)
        store.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_partial_failure_returns_nonzero_but_still_writes_success(self):
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            exit_code = us_stock_scan.main(
                ["--data-dir", self.tmp, "--trigger", "manual"])

        self.assertEqual(exit_code, 1)
        store = USStockStore(self.tmp)
        try:
            self.assertEqual(len(store.list_price_snapshots("NET")), 1)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
