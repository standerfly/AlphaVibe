"""fundamentals_client.py 測試：單股估值／營收查詢，官方TWSE/TPEx優先、
FinMind 降級為備援（2026-08-01 來源選用邏輯稽核修正）。

全部 mock market_scan._fetch_json／finmind_client／twse_price_client，
不打真實外部API。批次端點回應形狀比照 test_market_scan.py 既有慣例
（成功＝{"data": [...]}，失敗＝{"error": ...}）。
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import fundamentals_client  # noqa: E402
import market_scan  # noqa: E402
import twse_price_client  # noqa: E402


def _batch(rows):
    return {"data": rows}


def _batch_err(msg):
    return {"error": msg}


class GetValuationTest(unittest.TestCase):
    """get_valuation()：官方PER批次端點優先，兩市場都查無/失敗才 fallback
    finmind_client.get_fundamentals 的估值部分。"""

    def test_twse_official_found_skips_finmind(self):
        # 欄位對照 2026-08-01 curl 實測（見任務驗證）：2330 台積電
        # PER=32.60／PBR=10.67／殖利率=0.91。
        twse_rows = [{"Code": "2330", "PEratio": "32.60", "PBratio": "10.67",
                     "DividendYield": "0.91"}]

        def fake_fetch_json(url, market_label, cache=None):
            if url == market_scan.TWSE_PER_URL:
                return _batch(twse_rows)
            return _batch([])

        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=fake_fetch_json), \
             unittest.mock.patch.object(finmind_client, "get_fundamentals") as mock_fm:
            out = fundamentals_client.get_valuation("2330")

        self.assertAlmostEqual(out["per"], 32.60)
        self.assertAlmostEqual(out["pbr"], 10.67)
        self.assertAlmostEqual(out["dividend_yield"], 0.91)
        self.assertEqual(out["market"], "TWSE")
        self.assertEqual(out["data_source"], "twse_official")
        self.assertIsNone(out["error"])
        mock_fm.assert_not_called()

    def test_tpex_official_found_when_absent_from_twse_batch(self):
        def fake_fetch_json(url, market_label, cache=None):
            if url == market_scan.TWSE_PER_URL:
                return _batch([])  # 3260 不在TWSE批次裡（上櫃股）
            if url == market_scan.TPEX_PER_URL:
                return _batch([{"SecuritiesCompanyCode": "3260",
                               "PriceEarningRatio": "11.82",
                               "PriceBookRatio": "1.57", "YieldRatio": "6.34"}])
            return _batch([])

        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=fake_fetch_json), \
             unittest.mock.patch.object(finmind_client, "get_fundamentals") as mock_fm:
            out = fundamentals_client.get_valuation("3260")

        self.assertAlmostEqual(out["per"], 11.82)
        self.assertAlmostEqual(out["pbr"], 1.57)
        self.assertAlmostEqual(out["dividend_yield"], 6.34)
        self.assertEqual(out["market"], "TPEx")
        self.assertEqual(out["data_source"], "tpex_official")
        mock_fm.assert_not_called()

    def test_both_official_endpoints_fail_falls_back_to_finmind(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch_err("模擬批次端點失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "9999", "errors": [],
                             "valuation": {"date": "2026-07-31", "PER": 15.0,
                                          "PBR": 2.0, "dividend_yield": 3.0}}
                ) as mock_fm:
            out = fundamentals_client.get_valuation("9999", data_dir="/tmp/fake")

        self.assertEqual(out["per"], 15.0)
        self.assertEqual(out["pbr"], 2.0)
        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertIsNone(out["market"])
        self.assertIsNone(out["error"])
        mock_fm.assert_called_once_with("9999", data_dir="/tmp/fake", token=None)

    def test_code_absent_from_both_markets_falls_back_to_finmind(self):
        """官方批次端點本身查詢成功，但這個代碼不在任何一個市場的批次資料
        裡（例如興櫃股，見模組docstring不在範圍內）——一樣要fallback。"""
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch([])), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "6666", "errors": [],
                             "valuation": {"PER": 8.0, "PBR": 1.0, "dividend_yield": 5.0}}
                ) as mock_fm:
            out = fundamentals_client.get_valuation("6666")

        self.assertEqual(out["per"], 8.0)
        self.assertEqual(out["data_source"], "finmind_fallback")
        mock_fm.assert_called_once()

    def test_both_official_and_finmind_fail_returns_error(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch_err("批次失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "0000",
                             "errors": ["TaiwanStockPER 無資料（代碼是否正確？）"]}):
            out = fundamentals_client.get_valuation("0000")

        self.assertIsNone(out["per"])
        self.assertIsNone(out["pbr"])
        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertIn("無資料", out["error"])

    def test_unexpected_exception_does_not_raise(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=RuntimeError("模擬非預期例外")):
            out = fundamentals_client.get_valuation("2330")

        self.assertIsNone(out["per"])
        self.assertIsNone(out["data_source"])
        self.assertIn("非預期錯誤", out["error"])

    def test_cache_forwarded_to_fetch_json(self):
        cache = {}
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch([])) as mock_fetch, \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "2330", "errors": [], "valuation": {}}):
            fundamentals_client.get_valuation("2330", cache=cache)

        self.assertTrue(mock_fetch.call_args_list)
        for call in mock_fetch.call_args_list:
            self.assertIs(call.kwargs["cache"], cache)


class GetRevenueYoyLatestTest(unittest.TestCase):
    """get_revenue_yoy_latest()：官方月營收批次端點優先，兩市場都查無/失敗
    才 fallback finmind_client.get_revenue_yoy 的最新一筆非null年增率。"""

    def test_twse_official_found_skips_finmind(self):
        rows = [{"公司代號": "2330", "營業收入-去年同月增減(%)": "67.86685548491262",
                "資料年月": "11506"}]

        def fake_fetch_json(url, market_label, cache=None):
            if url == market_scan.TWSE_REVENUE_URL:
                return _batch(rows)
            return _batch([])

        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=fake_fetch_json), \
             unittest.mock.patch.object(finmind_client, "get_revenue_yoy") as mock_fm:
            out = fundamentals_client.get_revenue_yoy_latest("2330")

        self.assertAlmostEqual(out["revenue_yoy"], 0.6786685548491262)
        self.assertEqual(out["revenue_period"], "2026-06")
        self.assertEqual(out["market"], "TWSE")
        self.assertEqual(out["data_source"], "twse_official")
        self.assertIsNone(out["error"])
        mock_fm.assert_not_called()

    def test_tpex_official_found_when_absent_from_twse_batch(self):
        rows = [{"公司代號": "1240", "營業收入-去年同月增減(%)": "24.166329644472224",
                "資料年月": "11506"}]

        def fake_fetch_json(url, market_label, cache=None):
            if url == market_scan.TWSE_REVENUE_URL:
                return _batch([])
            if url == market_scan.TPEX_REVENUE_URL:
                return _batch(rows)
            return _batch([])

        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=fake_fetch_json), \
             unittest.mock.patch.object(finmind_client, "get_revenue_yoy") as mock_fm:
            out = fundamentals_client.get_revenue_yoy_latest("1240")

        self.assertAlmostEqual(out["revenue_yoy"], 0.24166329644472224)
        self.assertEqual(out["market"], "TPEx")
        self.assertEqual(out["data_source"], "tpex_official")
        mock_fm.assert_not_called()

    def test_official_fails_falls_back_to_finmind_latest_non_null(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch_err("模擬批次端點失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "2330", "errors": [],
                             "revenue_yoy": [
                                 {"revenue_year": 2026, "revenue_month": 5,
                                  "revenue": 100, "yoy_growth": 0.30},
                                 {"revenue_year": 2026, "revenue_month": 6,
                                  "revenue": 110, "yoy_growth": 0.20}]}
                ) as mock_fm:
            out = fundamentals_client.get_revenue_yoy_latest("2330", data_dir="/tmp/fake")

        self.assertAlmostEqual(out["revenue_yoy"], 0.20)
        self.assertEqual(out["revenue_period"], "2026-06")
        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertIsNone(out["error"])
        mock_fm.assert_called_once_with("2330", data_dir="/tmp/fake", token=None)

    def test_official_fails_and_finmind_query_itself_fails_surfaces_error(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch_err("模擬批次端點失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "0000",
                             "errors": ["FinMind 呼叫失敗（TaiwanStockMonthRevenue）：模擬斷網"]}):
            out = fundamentals_client.get_revenue_yoy_latest("0000")

        self.assertIsNone(out["revenue_yoy"])
        self.assertIn("模擬斷網", out["error"])

    def test_official_fails_finmind_succeeds_but_no_non_null_point_not_an_error(self):
        """FinMind查詢本身成功（errors為空），只是挑不出非null年增率
        （例如新掛牌不滿一年）——不算error，維持None，跟改動前
        screen_stocks() 從不檢查這種情況的既有靜默降級行為一致。"""
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", return_value=_batch_err("模擬批次端點失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "1234", "errors": [], "revenue_yoy": []}):
            out = fundamentals_client.get_revenue_yoy_latest("1234")

        self.assertIsNone(out["revenue_yoy"])
        self.assertIsNone(out["error"])

    def test_unexpected_exception_does_not_raise(self):
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", side_effect=RuntimeError("模擬非預期例外")):
            out = fundamentals_client.get_revenue_yoy_latest("2330")

        self.assertIsNone(out["revenue_yoy"])
        self.assertIn("非預期錯誤", out["error"])


def _twse_official_per_history(values, dates=None):
    dates = dates or ["2026-%02d-01" % (i % 12 + 1) for i in range(len(values))]
    return {"per_history": [{"date": d, "PER": v, "PBR": None, "dividend_yield": None}
                            for d, v in zip(dates, values)],
            "stock_id": "2330"}


class GetPerHistoryTest(unittest.TestCase):
    """get_per_history()：TWSE官方BWIBBU逐月合併優先，查無資料/失敗才
    fallback finmind_client.get_per_history。"""

    def test_twse_official_success_skips_finmind(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_per_history",
                return_value=_twse_official_per_history([10.0, 20.0, 30.0])
                ) as mock_official, \
             unittest.mock.patch.object(finmind_client, "get_per_history") as mock_fm:
            out = fundamentals_client.get_per_history("2330")

        self.assertEqual(out["data_source"], "twse_official")
        self.assertEqual(len(out["per_history"]), 3)
        self.assertEqual(out["errors"], [])
        mock_official.assert_called_once()
        mock_fm.assert_not_called()

    def test_twse_official_fails_falls_back_to_finmind(self):
        """TPEx股票或官方端點失敗都會走這條路：twse_price_client.fetch_per_history
        對TPEx代碼會查無資料回傳error（見該模組docstring），一律fallback。"""
        with unittest.mock.patch.object(
                twse_price_client, "fetch_per_history",
                return_value={"error": "TWSE %s BWIBBU官方端點全數月份查無資料"
                                       % "3260"}), \
             unittest.mock.patch.object(
                finmind_client, "get_per_history",
                return_value={"stock_id": "3260", "errors": [],
                             "per_history": [{"date": "2026-07-01", "PER": 12.0,
                                             "PBR": None, "dividend_yield": None}]}
                ) as mock_fm:
            out = fundamentals_client.get_per_history("3260", data_dir="/tmp/fake",
                                                       window_days=730)

        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertEqual(len(out["per_history"]), 1)
        mock_fm.assert_called_once_with("3260", days=730, data_dir="/tmp/fake", token=None)

    def test_official_empty_per_history_list_also_falls_back(self):
        """official 回傳沒有error但per_history是空list也要fallback（防呆，
        跟 screener._fetch_prices_with_fallback 對official.get("prices")的
        truthy 檢查邏輯一致）。"""
        with unittest.mock.patch.object(
                twse_price_client, "fetch_per_history",
                return_value={"per_history": [], "stock_id": "2330"}), \
             unittest.mock.patch.object(
                finmind_client, "get_per_history",
                return_value={"stock_id": "2330", "errors": [],
                             "per_history": [{"date": "2026-07-01", "PER": 30.0,
                                             "PBR": None, "dividend_yield": None}]}
                ) as mock_fm:
            out = fundamentals_client.get_per_history("2330")

        self.assertEqual(out["data_source"], "finmind_fallback")
        mock_fm.assert_called_once()

    def test_both_official_and_finmind_fail_no_per_history_key(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_per_history",
                return_value={"error": "模擬官方端點失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_per_history",
                return_value={"stock_id": "0000",
                             "errors": ["TaiwanStockPER 無資料（代碼是否正確？）"]}):
            out = fundamentals_client.get_per_history("0000")

        self.assertNotIn("per_history", out)
        self.assertEqual(out["data_source"], "finmind_fallback")

    def test_unexpected_exception_does_not_raise(self):
        with unittest.mock.patch.object(
                twse_price_client, "fetch_per_history", side_effect=RuntimeError("boom")):
            out = fundamentals_client.get_per_history("2330")

        self.assertNotIn("per_history", out)
        self.assertIn("非預期錯誤", out["errors"][0])


if __name__ == "__main__":
    unittest.main()
