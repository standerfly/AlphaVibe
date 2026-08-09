"""screener.py 測試：PEG／回檔幅度計算、單檔失敗不中斷整批、代碼數量防呆。

篩選邏輯來源：framework_peg_deep_dip_concentration 哲學框架
（PEG<1 且股價回檔>=40%）。全部用 mock，不打真實 FinMind／TWSE／TPEx API。

2026-07-28（Phase 3B）：compute_drawdown() 改為優先呼叫 twse_price_client
官方端點，失敗才 fallback 回 FinMind。既有測試（在 Phase 3B 之前寫的）
全部只關心「拿到FinMind股價資料之後」的計算邏輯，不關心資料源本身——
ScreenStocksTest／ScreenStocksBenchmarkTest 兩個 TestCase 因此在 setUp
統一把 screener.twse_price_client.fetch_price_history 強制 mock 成回傳
error（模擬官方端點不可用），逼所有既有測試走 finmind_client fallback
路徑，維持原本的 mock 資料與斷言不變。真正測試「官方端點成功」／
「官方端點失敗才fallback」這兩條路徑本身的案例見
TwsePriceClientFallbackTest。
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import benchmark  # noqa: E402
import finmind_client  # noqa: E402
import fundamentals_client  # noqa: E402
import screener  # noqa: E402
import twse_price_client  # noqa: E402


def _force_finmind_fallback(test_case):
    """在給定 TestCase 上 patch screener.twse_price_client.fetch_price_history
    永遠回傳 error，逼 compute_drawdown() 走 finmind_client fallback 路徑。
    給 Phase 3B 之前寫的既有測試沿用，不用逐一修改每個測試案例。"""
    patcher = unittest.mock.patch.object(
        screener.twse_price_client, "fetch_price_history",
        return_value={"error": "test stub：強制模擬官方端點不可用，測試 fallback 路徑"})
    patcher.start()
    test_case.addCleanup(patcher.stop)


def _force_fundamentals_official_fallback(test_case):
    """在給定 TestCase 上 patch fundamentals_client._official_valuation／
    _official_revenue 永遠回傳 None，逼 screen_stocks() 呼叫
    fundamentals_client.get_valuation／get_revenue_yoy_latest 時走
    finmind_client fallback 路徑（2026-08-01 來源選用邏輯稽核修正）。

    給改動前寫的既有測試沿用，不用逐一修改每個測試案例——這些測試直接
    mock finmind_client.get_fundamentals／get_revenue_yoy，只關心「拿到
    FinMind估值/營收資料之後」的PEG計算邏輯，不關心資料源本身。沒有這個
    patch的話，"2330" 這種真實代碼會讓 fundamentals_client 真的打官方
    TWSE/TPEx 端點拿到真實資料，蓋掉mock的假資料，測試斷言會失真、而且
    真的打了外部API（不該發生在單元測試裡）。真正測試「官方優先／
    fallback」這兩條路徑本身的案例見 test_fundamentals_client.py。"""
    for attr in ("_official_valuation", "_official_revenue"):
        patcher = unittest.mock.patch.object(fundamentals_client, attr, return_value=None)
        patcher.start()
        test_case.addCleanup(patcher.stop)


def _bench(dates, closes, error=None):
    """建一份 benchmark.load_benchmark() 形狀的假資料，供測試 excess_drawdown
    相關邏輯，不用真的打 FinMind。"""
    if error:
        return {"closes": None, "dates": None, "high_date": None, "high_price": None,
                "current_date": None, "current_close": None,
                "window_drawdown_pct": None, "error": error}
    return {"closes": closes, "dates": dates,
            "high_date": dates[0], "high_price": closes[0],
            "current_date": dates[-1], "current_close": closes[-1],
            "window_drawdown_pct": (closes[0] - closes[-1]) / closes[0], "error": None}


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
    def setUp(self):
        _force_finmind_fallback(self)
        _force_fundamentals_official_fallback(self)

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


class ComputeDrawdownTest(unittest.TestCase):
    """compute_drawdown()：從 screen_stocks() 抽出，第二層 market_scan.py
    的 Stage B 會重用這個函式，單獨測試確保抽出後行為不變。"""

    def setUp(self):
        _force_finmind_fallback(self)

    def test_normal_case_matches_price_history(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.compute_drawdown("2330")
        self.assertAlmostEqual(out["drawdown_pct"], 0.40)
        self.assertEqual(out["high_price"], 100.0)
        self.assertEqual(out["current_price"], 60.0)
        self.assertIsNone(out["error"])

    def test_unexpected_exception_recorded_not_raised(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                side_effect=RuntimeError("模擬非預期例外")):
            out = screener.compute_drawdown("2330")
        self.assertIsNone(out["drawdown_pct"])
        self.assertIn("非預期錯誤", out["error"])

    def test_market_and_excess_drawdown_keys_always_present(self):
        """回傳 dict 一律含 market_drawdown_pct／excess_drawdown_pct 兩個
        key（含 except 分支）——沒傳 benchmark_series 時兩者皆為 None，
        不能整個 key 消失。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.compute_drawdown("2330")
        self.assertIn("market_drawdown_pct", out)
        self.assertIn("excess_drawdown_pct", out)
        self.assertIsNone(out["market_drawdown_pct"])
        self.assertIsNone(out["excess_drawdown_pct"])

        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                side_effect=RuntimeError("boom")):
            out = screener.compute_drawdown("2330")
        self.assertIn("market_drawdown_pct", out)
        self.assertIn("excess_drawdown_pct", out)

    def test_benchmark_series_produces_excess_drawdown(self):
        """個股高點日早於大盤高點日：同期大盤其實在漲，超額跌幅應該比
        個股自身回檔還大（跟計畫檔的關鍵設計決策一致）。"""
        bench = _bench(["2026-05-01", "2026-06-01", "2026-07-01"],
                       [80.0, 90.0, 100.0])  # 大盤這段期間持續上漲
        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0,
                                     high_date="2026-05-01", current_date="2026-07-01")):
            out = screener.compute_drawdown("2330", benchmark_series=bench)
        # 個股回檔40%；大盤同期是 (80-100)/80 = -25%（上漲，負值）
        self.assertAlmostEqual(out["drawdown_pct"], 0.40)
        self.assertAlmostEqual(out["market_drawdown_pct"], -0.25)
        # 超額跌幅 = 0.40 - (-0.25) = 0.65，遠大於個股自身回檔
        self.assertAlmostEqual(out["excess_drawdown_pct"], 0.65)
        self.assertGreater(out["excess_drawdown_pct"], out["drawdown_pct"])


def _official(high, current, high_date="2026-06-01", current_date="2026-07-01"):
    """建一份 twse_price_client.fetch_price_history() 成功時的形狀。"""
    return {"prices": [{"date": high_date, "max": high, "close": high},
                       {"date": current_date, "max": current, "close": current}]}


class TwsePriceClientFallbackTest(unittest.TestCase):
    """compute_drawdown() 的資料源優先序（2026-07-28 Phase 3B）：
    twse_price_client 官方端點優先，失敗才 fallback 回 FinMind；
    market 已知時只打對應端點，market=None 時先試 TWSE 再試 TPEx。"""

    def test_market_twse_uses_official_and_skips_finmind(self):
        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history",
                return_value=_official(high=100.0, current=60.0)) as mock_official, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history") as mock_finmind:
            out = screener.compute_drawdown("2330", market="TWSE")
        self.assertAlmostEqual(out["drawdown_pct"], 0.40)
        self.assertEqual(out["data_source"], "twse_official")
        mock_official.assert_called_once()
        self.assertEqual(mock_official.call_args.args[1], "TWSE")
        mock_finmind.assert_not_called()

    def test_market_tpex_uses_official_and_skips_finmind(self):
        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history",
                return_value=_official(high=100.0, current=60.0)) as mock_official, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history") as mock_finmind:
            out = screener.compute_drawdown("3260", market="TPEx")
        self.assertEqual(out["data_source"], "tpex_official")
        self.assertEqual(mock_official.call_args.args[1], "TPEx")
        mock_finmind.assert_not_called()

    def test_market_known_but_official_fails_falls_back_to_finmind(self):
        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history",
                return_value={"error": "模擬官方端點失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)) as mock_finmind:
            out = screener.compute_drawdown("2330", market="TWSE")
        self.assertAlmostEqual(out["drawdown_pct"], 0.40)
        self.assertEqual(out["data_source"], "finmind_fallback")
        mock_finmind.assert_called_once()

    def test_market_none_tries_twse_then_tpex(self):
        """market 未知時（screen_stocks() 的情境）：TWSE 先失敗，TPEx 成功
        → 採用 TPEx 官方資料，不用打 FinMind。"""
        calls = []

        def fake_official(code, market, window_days=120, cache=None):
            calls.append(market)
            if market == "TWSE":
                return {"error": "TWSE查無資料"}
            return _official(high=100.0, current=60.0)

        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history", fake_official), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history") as mock_finmind:
            out = screener.compute_drawdown("3260")  # market 未傳
        self.assertEqual(calls, ["TWSE", "TPEx"])
        self.assertEqual(out["data_source"], "tpex_official")
        mock_finmind.assert_not_called()

    def test_market_none_both_official_fail_falls_back_to_finmind(self):
        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history",
                return_value={"error": "官方端點都失敗"}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)) as mock_finmind:
            out = screener.compute_drawdown("9999")
        self.assertEqual(out["data_source"], "finmind_fallback")
        self.assertAlmostEqual(out["drawdown_pct"], 0.40)
        mock_finmind.assert_called_once()

    def test_price_cache_passed_through_to_twse_price_client(self):
        cache = {}
        with unittest.mock.patch.object(
                screener.twse_price_client, "fetch_price_history",
                return_value=_official(high=100.0, current=60.0)) as mock_official:
            screener.compute_drawdown("2330", market="TWSE", price_cache=cache)
        self.assertIs(mock_official.call_args.kwargs["cache"], cache)


class ScreenStocksFundamentalsSourceTest(unittest.TestCase):
    """2026-08-01 來源選用邏輯稽核修正：screen_stocks() 接上
    fundamentals_client 後，PER／最新一期營收年增率的資料源正確反映在
    per_data_source／revenue_data_source 欄位；官方成功時不打
    finmind_client.get_fundamentals／get_revenue_yoy。真正測試「官方優先／
    fallback」這兩條路徑本身的案例見 test_fundamentals_client.py，這裡
    只測「screener.py 有沒有正確接上」這件事本身。"""

    def setUp(self):
        _force_finmind_fallback(self)  # 股價維持既有fallback強制，這裡只關心PER/revenue

    def test_official_valuation_and_revenue_used_skips_finmind_for_those_two(self):
        with unittest.mock.patch.object(
                fundamentals_client, "get_valuation",
                return_value={"per": 20.0, "pbr": 5.0, "dividend_yield": 1.0,
                             "market": "TWSE", "data_source": "twse_official",
                             "error": None}) as mock_val, \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": 0.20, "revenue_period": "2026-06",
                             "market": "TWSE", "data_source": "twse_official",
                             "error": None}) as mock_rev, \
             unittest.mock.patch.object(finmind_client, "get_fundamentals") as mock_fm_fund, \
             unittest.mock.patch.object(finmind_client, "get_revenue_yoy") as mock_fm_rev, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=100.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertEqual(row["per"], 20.0)
        self.assertAlmostEqual(row["peg"], 1.0)
        self.assertEqual(row["per_data_source"], "twse_official")
        self.assertEqual(row["revenue_data_source"], "twse_official")
        mock_val.assert_called_once()
        mock_rev.assert_called_once()
        mock_fm_fund.assert_not_called()
        mock_fm_rev.assert_not_called()

    def test_fundamentals_error_propagates_to_row_when_both_sources_fail(self):
        with unittest.mock.patch.object(
                fundamentals_client, "get_valuation",
                return_value={"per": None, "pbr": None, "dividend_yield": None,
                             "market": None, "data_source": "finmind_fallback",
                             "error": "模擬官方與FinMind皆失敗"}), \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": None, "revenue_period": None,
                             "market": None, "data_source": "finmind_fallback",
                             "error": None}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            out = screener.screen_stocks(["2330"])
        row = out["results"][0]
        self.assertIsNone(row["per"])
        self.assertIsNone(row["peg"])
        self.assertEqual(row["error"], "模擬官方與FinMind皆失敗")

    def test_batch_cache_shared_across_codes_in_one_call(self):
        """同一次 screen_stocks() 呼叫裡，多檔代碼應共用同一個 cache dict
        傳給 fundamentals_client（避免官方批次端點被重打多次）。"""
        seen_caches = []

        def fake_valuation(code, data_dir=None, token=None, cache=None):
            seen_caches.append(cache)
            return {"per": None, "pbr": None, "dividend_yield": None, "market": None,
                    "data_source": "finmind_fallback", "error": None}

        with unittest.mock.patch.object(
                fundamentals_client, "get_valuation", fake_valuation), \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": None, "revenue_period": None,
                             "market": None, "data_source": "finmind_fallback",
                             "error": None}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)):
            screener.screen_stocks(["2330", "2454"])
        self.assertEqual(len(seen_caches), 2)
        self.assertIs(seen_caches[0], seen_caches[1])


class MeetsFrameworkThresholdsTest(unittest.TestCase):
    def test_single_sided_threshold_peg_deep_dip(self):
        # framework_peg_deep_dip_concentration：PEG<1 且回檔>=40%（單邊，無上限）
        self.assertTrue(screener.meets_framework_thresholds(0.5, 0.40))
        self.assertFalse(screener.meets_framework_thresholds(1.0, 0.40))  # peg剛好=門檻，不符合
        self.assertFalse(screener.meets_framework_thresholds(0.5, 0.39))  # 回檔差一點點

    def test_double_sided_drawdown_window(self):
        # 模擬 framework_revenue_high_price_dip：回檔15~30%甜蜜區間（雙邊門檻）
        self.assertTrue(screener.meets_framework_thresholds(
            None, 0.20, peg_threshold=None, drawdown_min=0.15, drawdown_max=0.30))
        self.assertFalse(screener.meets_framework_thresholds(
            None, 0.35, peg_threshold=None, drawdown_min=0.15, drawdown_max=0.30))  # 超過上限
        self.assertFalse(screener.meets_framework_thresholds(
            None, 0.10, peg_threshold=None, drawdown_min=0.15, drawdown_max=0.30))  # 不到下限

    def test_none_threshold_skips_that_condition(self):
        # peg_threshold=None：完全不檢查PEG，只看回檔
        self.assertTrue(screener.meets_framework_thresholds(
            None, 0.50, peg_threshold=None, drawdown_min=0.40))

    def test_missing_values_never_satisfy_active_thresholds(self):
        self.assertFalse(screener.meets_framework_thresholds(None, 0.50))  # peg缺值
        self.assertFalse(screener.meets_framework_thresholds(0.5, None))   # drawdown缺值

    def test_excess_drawdown_threshold_only_checked_when_min_given(self):
        # excess_drawdown_min=None（預設）：不檢查超額跌幅，跟改動前行為一致
        self.assertTrue(screener.meets_framework_thresholds(0.5, 0.40))

        # 給了 excess_drawdown_min，超額跌幅不足則不符合
        self.assertFalse(screener.meets_framework_thresholds(
            0.5, 0.40, excess_drawdown=0.10, excess_drawdown_min=0.20))
        # 超額跌幅缺值（None）也不符合，不可以當作「通過」
        self.assertFalse(screener.meets_framework_thresholds(
            0.5, 0.40, excess_drawdown=None, excess_drawdown_min=0.20))
        # 超額跌幅足夠則符合
        self.assertTrue(screener.meets_framework_thresholds(
            0.5, 0.40, excess_drawdown=0.25, excess_drawdown_min=0.20))


class ScreenStocksCustomThresholdsTest(unittest.TestCase):
    def setUp(self):
        _force_finmind_fallback(self)
        _force_fundamentals_official_fallback(self)

    def test_custom_thresholds_change_meets_framework(self):
        # PER=10,yoy=20% → peg=0.5；drawdown=20%。預設門檻(drawdown>=0.40)不符合，
        # 但自訂門檻(drawdown_min=0.15,drawdown_max=0.30)應該符合。
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(10.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=80.0)):
            default_out = screener.screen_stocks(["2330"])
            custom_out = screener.screen_stocks(
                ["2330"], peg_threshold=None, drawdown_min=0.15, drawdown_max=0.30)
        self.assertFalse(default_out["results"][0]["meets_framework"])
        self.assertTrue(custom_out["results"][0]["meets_framework"])

    def test_default_call_unchanged_when_new_params_omitted(self):
        """不傳新參數時，行為必須跟改動前完全一致——這是向後相容的關鍵驗證。"""
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
        self.assertAlmostEqual(row["drawdown_pct"], 0.40)
        self.assertTrue(row["meets_framework"])


class ScreenStocksBenchmarkTest(unittest.TestCase):
    """screen_stocks() 串接 benchmark 的行為：只抓一次大盤基準、回傳新增
    thresholds／benchmark 兩區塊、excess_drawdown_pct 有值。"""

    def setUp(self):
        _force_finmind_fallback(self)
        _force_fundamentals_official_fallback(self)

    def test_load_benchmark_called_once_not_per_code(self):
        bench = _bench(["2026-06-01", "2026-07-01"], [100.0, 100.0])
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(10.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0)), \
             unittest.mock.patch.object(
                screener.benchmark, "load_benchmark",
                return_value=bench) as mock_load_bench:
            screener.screen_stocks(["2330", "2454", "3260"])
        mock_load_bench.assert_called_once()

    def test_empty_and_max_codes_do_not_call_load_benchmark(self):
        """沒有代碼可篩、或超過MAX_CODES短路時，不該打大盤查詢——沒有東西
        要篩就不需要大盤基準，也避免防呆測試意外打到真實API。"""
        with unittest.mock.patch.object(
                screener.benchmark, "load_benchmark") as mock_load_bench:
            screener.screen_stocks([])
            mock_load_bench.assert_not_called()

            codes = ["%04d" % i for i in range(screener.MAX_CODES + 1)]
            screener.screen_stocks(codes)
            mock_load_bench.assert_not_called()

    def test_result_includes_thresholds_and_benchmark_blocks(self):
        bench = _bench(["2026-06-01", "2026-07-01"], [100.0, 90.0])
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(10.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0,
                                     high_date="2026-06-01", current_date="2026-07-01")), \
             unittest.mock.patch.object(
                screener.benchmark, "load_benchmark", return_value=bench):
            out = screener.screen_stocks(["2330"], framework_id="revenue_high_price_dip")

        self.assertEqual(out["thresholds"]["framework_id"], "revenue_high_price_dip")
        self.assertEqual(out["thresholds"]["peg_threshold"], screener.PEG_THRESHOLD)
        self.assertAlmostEqual(out["benchmark"]["window_drawdown_pct"], 0.10)
        row = out["results"][0]
        self.assertIsNotNone(row["excess_drawdown_pct"])
        # 個股回檔40%，大盤同期回檔10% → 超額跌幅30%
        self.assertAlmostEqual(row["excess_drawdown_pct"], 0.30)

    def test_excess_drawdown_min_filters_meets_framework(self):
        bench = _bench(["2026-06-01", "2026-07-01"], [100.0, 90.0])
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}), \
             unittest.mock.patch.object(
                finmind_client, "get_fundamentals", return_value=_fund(10.0)), \
             unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_revenue_yoy(0.20)), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_prices(high=100.0, current=60.0,
                                     high_date="2026-06-01", current_date="2026-07-01")), \
             unittest.mock.patch.object(
                screener.benchmark, "load_benchmark", return_value=bench):
            # 超額跌幅30%，門檻要求>=50% → 不符合
            strict_out = screener.screen_stocks(
                ["2330"], peg_threshold=None, drawdown_min=None,
                excess_drawdown_min=0.50)
            # 門檻要求>=20% → 符合
            loose_out = screener.screen_stocks(
                ["2330"], peg_threshold=None, drawdown_min=None,
                excess_drawdown_min=0.20)
        self.assertFalse(strict_out["results"][0]["meets_framework"])
        self.assertTrue(loose_out["results"][0]["meets_framework"])


if __name__ == "__main__":
    unittest.main()
