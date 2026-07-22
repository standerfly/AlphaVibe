"""screener.py 測試：PEG／回檔幅度計算、單檔失敗不中斷整批、代碼數量防呆。

篩選邏輯來源：framework_peg_deep_dip_concentration 哲學框架
（PEG<1 且股價回檔>=40%）。全部用 mock，不打真實 FinMind API。
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import screener  # noqa: E402


def _fund(per):
    return {"stock_id": None, "errors": [], "valuation": {"PER": per}} if per is not None \
        else {"stock_id": None, "errors": ["TaiwanStockPER 無資料（代碼是否正確？）"]}


def _revenue_yoy(yoy, year=2026, month=6):
    if yoy is None:
        return {"stock_id": None, "errors": [], "revenue_yoy": []}
    return {"stock_id": None, "errors": [],
            "revenue_yoy": [{"revenue_year": year, "revenue_month": month,
                             "revenue": 1000, "yoy_growth": yoy}]}


def _prices(high, current, high_date="2026-06-01", current_date="2026-07-01"):
    return {"stock_id": None, "errors": [],
            "prices": [{"date": high_date, "max": high, "close": high},
                       {"date": current_date, "max": current, "close": current}]}


class ParseCodesTest(unittest.TestCase):
    def test_comma_and_newline_and_fullwidth_comma_separated(self):
        self.assertEqual(
            screener.parse_codes("3485,6953\n6719，2330"),
            ["3485", "6953", "6719", "2330"])

    def test_dedup_preserves_first_occurrence_order(self):
        self.assertEqual(screener.parse_codes("2330,6953,2330"), ["2330", "6953"])

    def test_strips_whitespace_and_drops_empty(self):
        self.assertEqual(screener.parse_codes("  2330 \n\n 6953  \n"), ["2330", "6953"])

    def test_empty_input(self):
        self.assertEqual(screener.parse_codes(""), [])
        self.assertEqual(screener.parse_codes(None), [])


class ScreenStocksTest(unittest.TestCase):
    def test_empty_code_list_returns_empty_results(self):
        out = screener.screen_stocks([])
        self.assertEqual(out, {"results": [], "total": 0})

    def test_max_codes_exceeded_short_circuits_before_any_lookup(self):
        codes = ["%04d" % i for i in range(screener.MAX_CODES + 1)]
        with unittest.mock.patch.object(finmind_client, "get_stock_info") as mock_info, \
             unittest.mock.patch.object(finmind_client, "get_fundamentals") as mock_fund:
            out = screener.screen_stocks(codes)
        mock_info.assert_not_called()
        mock_fund.assert_not_called()
        self.assertEqual(out["results"], [])
        self.assertEqual(out["total"], 0)
        self.assertIn("error", out)
        self.assertIn(str(screener.MAX_CODES), out["error"])

    def test_peg_calculated_when_per_and_positive_yoy_present(self):
        # PER 20、年增率 20% → PEG = 20 / (0.20*100) = 1.0
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(20.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=100.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertAlmostEqual(row["peg"], 1.0)
        self.assertEqual(row["per"], 20.0)
        self.assertAlmostEqual(row["revenue_yoy"], 0.20)

    def test_peg_is_none_when_yoy_missing(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(20.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(None)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=100.0)):
            out = screener.screen_stocks(["3485"])
        row = out["results"][0]
        self.assertIsNone(row["peg"])
        self.assertIsNone(row["revenue_yoy"])

    def test_peg_is_none_when_yoy_negative_not_negative_peg(self):
        """負成長率不可以硬算出負PEG——這是規格明文要求，不是臆測行為。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(20.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(-0.036)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=100.0)):
            out = screener.screen_stocks(["6719"])
        row = out["results"][0]
        self.assertIsNone(row["peg"])
        self.assertAlmostEqual(row["revenue_yoy"], -0.036)

    def test_drawdown_uses_window_high_vs_latest_close(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(None)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(None)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertAlmostEqual(row["drawdown_pct"], 0.40)
        self.assertEqual(row["high_price"], 100.0)
        self.assertEqual(row["current_price"], 60.0)

    def test_meets_framework_true_only_when_both_conditions_hold(self):
        # PEG=1.0 剛好卡在門檻（<1 才算符合），回檔剛好40%（>=40% 符合）
        # → 因為 PEG 不是嚴格 <1，整體不應判定符合框架
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(20.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertAlmostEqual(row["peg"], 1.0)
        self.assertAlmostEqual(row["drawdown_pct"], 0.40)
        self.assertFalse(row["meets_framework"])

        # PEG=0.5（<1）、回檔40%（>=40%）→ 應該符合
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(10.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertAlmostEqual(row["peg"], 0.5)
        self.assertTrue(row["meets_framework"])

    def test_per_item_exception_recorded_not_fatal(self):
        """回歸測試：比照 refresh_holdings_prices 修過的坑——單檔非預期例外
        （非finmind_client結構化errors）只記錄在該筆error，不可以中斷整批。"""
        call_log = []

        def fake_fundamentals(stock_id, data_dir=None, token=None):
            call_log.append(stock_id)
            if stock_id == "1111":
                raise RuntimeError("模擬非預期例外")
            return _fund(20.0)

        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", fake_fundamentals), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["1111", "2330"])

        self.assertIn("1111", call_log)
        self.assertIn("2330", call_log)  # 2330 排在1111後面，仍必須被嘗試到
        by_code = {r["code"]: r for r in out["results"]}
        self.assertIsNotNone(by_code["1111"]["error"])
        self.assertIsNone(by_code["1111"]["peg"])
        self.assertIsNone(by_code["2330"]["error"])
        self.assertAlmostEqual(by_code["2330"]["peg"], 1.0)

    def test_name_lookup_failure_does_not_block_screening(self):
        """get_stock_info 是「順便」查名稱，失敗不該讓整個篩選掛掉——只是
        名稱顯示為 None。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", side_effect=RuntimeError("查詢失敗")), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(20.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertIsNone(row["name"])
        self.assertAlmostEqual(row["peg"], 1.0)

    def test_results_sorted_by_peg_ascending_with_nulls_last(self):
        def fake_fundamentals(stock_id, data_dir=None, token=None):
            return _fund({"A": 10.0, "B": 30.0, "C": None}[stock_id])

        def fake_yoy(stock_id, data_dir=None, token=None):
            return _revenue_yoy({"A": 0.20, "B": 0.20, "C": None}[stock_id])

        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", fake_fundamentals), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", fake_yoy), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["B", "C", "A"])

        # A: PEG=0.5, B: PEG=1.5, C: PEG=None（排最後）
        self.assertEqual([r["code"] for r in out["results"]], ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
