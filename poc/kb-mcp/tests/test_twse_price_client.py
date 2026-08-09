"""twse_price_client.py 測試：TWSE/TPEx 官方月批次端點的 ROC 日期轉換、
市場路由、stat!=OK 錯誤處理、cache 命中不重打、月份合併與窗口裁切。

全部用 mock，不打真實 TWSE/TPEx API（跟 finmind_client/tpex_client 既有
測試風格一致：低階測試 mock urllib，高階測試 mock 內部函式）。
"""
import datetime
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import twse_price_client as tpc  # noqa: E402


class RocToAdDateTest(unittest.TestCase):
    def test_normal_conversion(self):
        self.assertEqual(tpc._roc_to_ad_date("115/07/01"), "2026-07-01")
        self.assertEqual(tpc._roc_to_ad_date("109/07/01"), "2020-07-01")

    def test_invalid_format_returns_none(self):
        self.assertIsNone(tpc._roc_to_ad_date("2026-07-01"))  # 已經是西元格式
        self.assertIsNone(tpc._roc_to_ad_date("115/07"))  # 缺日
        self.assertIsNone(tpc._roc_to_ad_date(""))
        self.assertIsNone(tpc._roc_to_ad_date(None))
        self.assertIsNone(tpc._roc_to_ad_date("abc/07/01"))
        self.assertIsNone(tpc._roc_to_ad_date("115/13/01"))  # 月份不合法


class RocCjkToAdDateTest(unittest.TestCase):
    """BWIBBU 專用日期格式（"115年07月01日"），跟 STOCK_DAY／FMTQIK 的
    "115/07/01" 斜線格式不同（2026-08-01 curl 實測確認，見模組docstring）。"""

    def test_normal_conversion(self):
        self.assertEqual(tpc._roc_cjk_to_ad_date("115年07月01日"), "2026-07-01")
        self.assertEqual(tpc._roc_cjk_to_ad_date("109年01月02日"), "2020-01-02")

    def test_invalid_format_returns_none(self):
        self.assertIsNone(tpc._roc_cjk_to_ad_date("2026-07-01"))  # 西元格式
        self.assertIsNone(tpc._roc_cjk_to_ad_date("115/07/01"))  # 斜線格式
        self.assertIsNone(tpc._roc_cjk_to_ad_date(""))
        self.assertIsNone(tpc._roc_cjk_to_ad_date(None))
        self.assertIsNone(tpc._roc_cjk_to_ad_date("115年13月01日"))  # 月份不合法


class ToFloatTest(unittest.TestCase):
    def test_strips_thousand_separators(self):
        self.assertEqual(tpc._to_float("39,836,425"), 39836425.0)
        self.assertEqual(tpc._to_float("2,505.00"), 2505.0)

    def test_placeholder_values_return_none(self):
        for v in (None, "", "--", "－", "X", "-"):
            self.assertIsNone(tpc._to_float(v))

    def test_non_numeric_returns_none(self):
        self.assertIsNone(tpc._to_float("abc"))


class MonthHelpersTest(unittest.TestCase):
    def test_months_needed_formula(self):
        self.assertEqual(tpc._months_needed(120), 120 // 20 + 2)
        self.assertEqual(tpc._months_needed(0), 2)

    def test_recent_year_months_length_and_ends_at_current_month(self):
        today = datetime.date.today()
        months = tpc._recent_year_months(8)
        self.assertEqual(len(months), 8)
        self.assertEqual(months[-1], (today.year, today.month))

    def test_recent_year_months_strictly_increasing_with_year_rollover(self):
        months = tpc._recent_year_months(15)  # 必定跨過至少一次跨年
        self.assertEqual(len(months), 15)
        self.assertEqual(len(set(months)), 15)  # 沒有重複
        for (y1, m1), (y2, m2) in zip(months, months[1:]):
            # 月份序號（year*12+month）必須嚴格遞增1
            self.assertEqual(y2 * 12 + m2, y1 * 12 + m1 + 1)

    def test_year_month_key_zero_pads(self):
        self.assertEqual(tpc._year_month_key(2026, 7), "202607")
        self.assertEqual(tpc._year_month_key(2026, 11), "202611")


class ThrottledGetCacheTest(unittest.TestCase):
    """_throttled_get()：cache 命中不重打網路、不 sleep；未命中才真的
    發送請求並節流。"""

    def test_cache_hit_skips_network_and_sleep(self):
        cache = {}
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = b'{"stat":"OK","data":[]}'
        fake_cm = unittest.mock.MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with unittest.mock.patch.object(
                tpc.urllib.request, "urlopen", return_value=fake_cm) as mock_open, \
             unittest.mock.patch.object(tpc.time, "sleep") as mock_sleep:
            first = tpc._throttled_get("http://example.test", cache_key="k1", cache=cache)
            second = tpc._throttled_get("http://example.test", cache_key="k1", cache=cache)
        self.assertEqual(first, second)
        mock_open.assert_called_once()  # 第二次是 cache 命中，不該再打網路
        mock_sleep.assert_called_once()  # 只有第一次真的打網路才 sleep

    def test_no_cache_dict_always_hits_network(self):
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = b'{"stat":"OK","data":[]}'
        fake_cm = unittest.mock.MagicMock()
        fake_cm.__enter__.return_value = fake_resp
        with unittest.mock.patch.object(
                tpc.urllib.request, "urlopen", return_value=fake_cm) as mock_open:
            tpc._throttled_get("http://example.test", cache_key="k1", cache=None)
            tpc._throttled_get("http://example.test", cache_key="k1", cache=None)
        self.assertEqual(mock_open.call_count, 2)

    def test_http_error_returns_error_dict(self):
        with unittest.mock.patch.object(
                tpc.urllib.request, "urlopen",
                side_effect=tpc.urllib.error.HTTPError(
                    "http://x", 500, "boom", None, None)):
            out = tpc._throttled_get("http://example.test")
        self.assertIn("error", out)

    def test_generic_exception_returns_error_dict_not_raised(self):
        with unittest.mock.patch.object(
                tpc.urllib.request, "urlopen", side_effect=RuntimeError("斷網")):
            out = tpc._throttled_get("http://example.test")
        self.assertIn("error", out)


class FetchTwseIndexMonthTest(unittest.TestCase):
    """FMTQIK：只有收盤指數，用 close 頂替 max（見模組docstring取捨說明）。"""

    def test_parses_roc_date_and_uses_close_as_max(self):
        payload = {"stat": "OK", "data": [
            ["115/07/27", "8,980,078,815", "747,647,200,740", "3,900,804",
             "43,634.19", "-20.65"],
        ]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_twse_index_month("202607")
        self.assertNotIn("error", out)
        row = out["prices"][0]
        self.assertEqual(row["date"], "2026-07-27")
        self.assertEqual(row["close"], 43634.19)
        self.assertEqual(row["max"], 43634.19)
        self.assertIsNone(row["min"])
        self.assertIsNone(row["open"])

    def test_stat_not_ok_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "查無資料"}}):
            out = tpc.fetch_twse_index_month("202607")
        self.assertIn("error", out)

    def test_network_error_propagates(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"error": "斷網"}):
            out = tpc.fetch_twse_index_month("202607")
        self.assertEqual(out, {"error": "斷網"})

    def test_empty_data_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "OK", "data": []}}):
            out = tpc.fetch_twse_index_month("202607")
        self.assertIn("error", out)


class FetchTwseStockMonthTest(unittest.TestCase):
    def test_parses_full_ohlc(self):
        payload = {"stat": "OK", "data": [
            ["115/07/01", "37,544,470", "93,600,076,825", "2,495.00", "2,505.00",
             "2,475.00", "2,505.00", "+95.00", "111,091", ""],
        ]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_twse_stock_month("2330", "202607")
        row = out["prices"][0]
        self.assertEqual(row["date"], "2026-07-01")
        self.assertEqual(row["open"], 2495.0)
        self.assertEqual(row["max"], 2505.0)
        self.assertEqual(row["min"], 2475.0)
        self.assertEqual(row["close"], 2505.0)

    def test_wrong_market_code_stat_message_is_error(self):
        """對 TPEx 代碼誤查 STOCK_DAY：stat 是「很抱歉，沒有符合條件的資料!」，
        不是 "OK"，2026-07-28 實測驗證過的乾淨失敗案例。"""
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "很抱歉，沒有符合條件的資料!",
                                          "total": 0}}):
            out = tpc.fetch_twse_stock_month("3260", "202607")
        self.assertIn("error", out)


class FetchTpexStockMonthTest(unittest.TestCase):
    def test_date_param_uses_ad_year_not_roc_year(self):
        """2026-07-28 實測：TPEx tradingStock 過去月份必須用西元年
        date=YYYY/MM/DD，民國年格式回傳「參數輸入錯誤」——這裡驗證
        fetch_tpex_stock_month 組出的 URL 真的是西元年格式。"""
        captured_urls = []

        def fake_throttled(url, cache_key=None, cache=None):
            captured_urls.append(url)
            return {"payload": {"stat": "ok", "tables": [
                {"data": [["115/04/01", "5,691", "2,071,527", "362.50",
                          "368.50", "360.00", "368.50", "33.50", "8,320"]]}]}}

        with unittest.mock.patch.object(tpc, "_throttled_get", fake_throttled):
            tpc.fetch_tpex_stock_month("3260", "202604")
        self.assertIn("date=2026/04/01", captured_urls[0])
        self.assertNotIn("date=115/04", captured_urls[0])

    def test_parses_full_ohlc(self):
        payload = {"stat": "ok", "tables": [{"data": [
            ["115/07/27", "6,929", "2,704,757", "386.00", "403.00",
             "378.50", "402.00", "19.00", "8,666"],
        ]}]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_tpex_stock_month("3260", "202607")
        row = out["prices"][0]
        self.assertEqual(row["date"], "2026-07-27")
        self.assertEqual(row["close"], 402.0)
        self.assertEqual(row["max"], 403.0)
        self.assertEqual(row["min"], 378.5)

    def test_stat_ok_but_empty_data_is_error(self):
        """2026-07-28 實測：誤查 TWSE 代碼時 stat 仍是 "ok" 但 data 是
        空陣列——不能只檢查 stat，要一併檢查 data 是否為空。"""
        payload = {"stat": "ok", "tables": [{"data": []}]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_tpex_stock_month("2330", "202607")
        self.assertIn("error", out)

    def test_missing_tables_is_error(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "ok"}}):
            out = tpc.fetch_tpex_stock_month("3260", "202607")
        self.assertIn("error", out)


class FetchTwsePerMonthTest(unittest.TestCase):
    """BWIBBU：單月個股歷史PER/PBR/殖利率，2026-08-01 新增（來源選用邏輯
    稽核修正，供 fundamentals_client.get_per_history 官方優先來源用）。
    欄位對照 2026-08-01 curl 實測：fields=[日期,殖利率(%),股利年度,本益比,
    股價淨值比,財報年/季]。"""

    def test_parses_per_pbr_dividend_yield(self):
        payload = {"stat": "OK", "data": [
            ["115年07月01日", "0.88", 114, "33.68", "11.03", "115/1"],
        ]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_twse_per_month("2330", "202607")
        row = out["per_history"][0]
        self.assertEqual(row["date"], "2026-07-01")
        self.assertEqual(row["PER"], 33.68)
        self.assertEqual(row["PBR"], 11.03)
        self.assertEqual(row["dividend_yield"], 0.88)

    def test_wrong_market_code_stat_message_is_error(self):
        """對 TPEx 代碼誤查 BWIBBU：stat 是「很抱歉，沒有符合條件的資料!」，
        2026-08-01 實測驗證過（跟 STOCK_DAY 對 TPEx 代碼的行為一致）。"""
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "很抱歉，沒有符合條件的資料!",
                                          "total": 0}}):
            out = tpc.fetch_twse_per_month("3260", "202607")
        self.assertIn("error", out)

    def test_network_error_propagates(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"error": "斷網"}):
            out = tpc.fetch_twse_per_month("2330", "202607")
        self.assertEqual(out, {"error": "斷網"})

    def test_row_with_null_per_is_skipped(self):
        """PER欄位是佔位符（停牌等情況）時該列被濾掉，不可以塞None進PER
        造成下游誤判（_to_float已把"--"等轉None，這裡確認會跳過該列）。"""
        payload = {"stat": "OK", "data": [
            ["115年07月01日", "0.88", 114, "--", "11.03", "115/1"],
            ["115年07月02日", "0.89", 114, "33.14", "10.85", "115/1"],
        ]}
        with unittest.mock.patch.object(
                tpc, "_throttled_get", return_value={"payload": payload}):
            out = tpc.fetch_twse_per_month("2330", "202607")
        self.assertEqual(len(out["per_history"]), 1)
        self.assertEqual(out["per_history"][0]["date"], "2026-07-02")

    def test_empty_data_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "_throttled_get",
                return_value={"payload": {"stat": "OK", "data": []}}):
            out = tpc.fetch_twse_per_month("2330", "202607")
        self.assertIn("error", out)


class FetchPerHistoryTest(unittest.TestCase):
    """高階函式：TWSE個股歷史PER序列，逐月合併去重排序（重用
    _merge_months／_recent_year_months／_months_needed，邏輯同
    fetch_price_history，只是 result_key 不同）。"""

    def test_merges_months_dedups_and_sorts(self):
        def fake_month(stock_id, year_month, cache=None):
            rows_by_month = {
                "202606": [{"date": "2026-06-15", "PER": 10.0, "PBR": None,
                           "dividend_yield": None}],
                "202607": [{"date": "2026-07-01", "PER": 11.0, "PBR": None,
                           "dividend_yield": None},
                          {"date": "2026-07-02", "PER": 12.0, "PBR": None,
                           "dividend_yield": None}],
            }
            return {"per_history": rows_by_month.get(year_month, [])}

        with unittest.mock.patch.object(tpc, "fetch_twse_per_month", fake_month), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 6), (2026, 7)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-01-01"):
            out = tpc.fetch_per_history("2330", window_days=730)
        dates = [p["date"] for p in out["per_history"]]
        self.assertEqual(dates, ["2026-06-15", "2026-07-01", "2026-07-02"])
        self.assertEqual(out["stock_id"], "2330")

    def test_window_cutoff_filters_out_old_rows(self):
        def fake_month(stock_id, year_month, cache=None):
            return {"per_history": [
                {"date": "2024-01-01", "PER": 10.0, "PBR": None, "dividend_yield": None},
                {"date": "2026-07-01", "PER": 11.0, "PBR": None, "dividend_yield": None},
            ]}

        with unittest.mock.patch.object(tpc, "fetch_twse_per_month", fake_month), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 7)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-06-01"):
            out = tpc.fetch_per_history("2330", window_days=730)
        dates = [p["date"] for p in out["per_history"]]
        self.assertEqual(dates, ["2026-07-01"])

    def test_all_months_fail_returns_error(self):
        """典型情境：TPEx股票查BWIBBU全月查無資料——呼叫端
        fundamentals_client.get_per_history 據此fallback FinMind。"""
        with unittest.mock.patch.object(
                tpc, "fetch_twse_per_month",
                return_value={"error": "TWSE BWIBBU 查無資料"}), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 6), (2026, 7)]):
            out = tpc.fetch_per_history("3260", window_days=730)
        self.assertIn("error", out)

    def test_all_rows_older_than_cutoff_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "fetch_twse_per_month",
                return_value={"per_history": [{"date": "2020-01-01", "PER": 10.0,
                                              "PBR": None, "dividend_yield": None}]}), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2020, 1)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-06-01"):
            out = tpc.fetch_per_history("2330", window_days=730)
        self.assertIn("error", out)


class FetchPriceHistoryTest(unittest.TestCase):
    """高階函式：市場路由、月份合併去重排序、視窗裁切。"""

    def test_unknown_market_returns_error_without_any_call(self):
        with unittest.mock.patch.object(tpc, "fetch_twse_stock_month") as mock_twse, \
             unittest.mock.patch.object(tpc, "fetch_tpex_stock_month") as mock_tpex:
            out = tpc.fetch_price_history("2330", "NYSE", window_days=120)
        self.assertIn("error", out)
        mock_twse.assert_not_called()
        mock_tpex.assert_not_called()

    def test_twse_market_only_calls_twse_stock_month(self):
        with unittest.mock.patch.object(
                tpc, "fetch_twse_stock_month",
                return_value={"prices": [{"date": "2026-07-01", "open": 100.0,
                                          "max": 110.0, "min": 95.0, "close": 105.0}]}) as mock_twse, \
             unittest.mock.patch.object(tpc, "fetch_tpex_stock_month") as mock_tpex, \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2020-01-01"):
            out = tpc.fetch_price_history("2330", "TWSE", window_days=20)
        self.assertNotIn("error", out)
        mock_twse.assert_called()
        mock_tpex.assert_not_called()

    def test_tpex_market_only_calls_tpex_stock_month(self):
        with unittest.mock.patch.object(tpc, "fetch_twse_stock_month") as mock_twse, \
             unittest.mock.patch.object(
                tpc, "fetch_tpex_stock_month",
                return_value={"prices": [{"date": "2026-07-01", "open": 100.0,
                                          "max": 110.0, "min": 95.0, "close": 105.0}]}) as mock_tpex, \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2020-01-01"):
            out = tpc.fetch_price_history("3260", "TPEx", window_days=20)
        self.assertNotIn("error", out)
        mock_tpex.assert_called()
        mock_twse.assert_not_called()

    def test_merges_months_dedups_and_sorts(self):
        def fake_month(stock_id, year_month, cache=None):
            rows_by_month = {
                "202606": [{"date": "2026-06-15", "open": 1.0, "max": 2.0,
                           "min": 0.5, "close": 1.5}],
                "202607": [{"date": "2026-07-01", "open": 1.0, "max": 2.0,
                           "min": 0.5, "close": 1.5},
                          {"date": "2026-07-02", "open": 1.0, "max": 2.0,
                           "min": 0.5, "close": 1.5}],
            }
            return {"prices": rows_by_month.get(year_month, [])}

        with unittest.mock.patch.object(tpc, "fetch_twse_stock_month", fake_month), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 6), (2026, 7)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-01-01"):
            out = tpc.fetch_price_history("2330", "TWSE", window_days=120)
        dates = [p["date"] for p in out["prices"]]
        self.assertEqual(dates, ["2026-06-15", "2026-07-01", "2026-07-02"])

    def test_window_cutoff_filters_out_old_rows(self):
        def fake_month(stock_id, year_month, cache=None):
            return {"prices": [
                {"date": "2026-01-01", "open": 1.0, "max": 2.0, "min": 0.5, "close": 1.5},
                {"date": "2026-07-01", "open": 1.0, "max": 2.0, "min": 0.5, "close": 1.5},
            ]}

        with unittest.mock.patch.object(tpc, "fetch_twse_stock_month", fake_month), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 7)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-06-01"):
            out = tpc.fetch_price_history("2330", "TWSE", window_days=120)
        dates = [p["date"] for p in out["prices"]]
        self.assertEqual(dates, ["2026-07-01"])  # 2026-01-01 早於窗口起點，被裁掉

    def test_all_months_fail_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "fetch_twse_stock_month",
                return_value={"error": "查無資料"}), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 6), (2026, 7)]):
            out = tpc.fetch_price_history("9999", "TWSE", window_days=120)
        self.assertIn("error", out)

    def test_all_rows_older_than_cutoff_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "fetch_twse_stock_month",
                return_value={"prices": [{"date": "2020-01-01", "open": 1.0,
                                          "max": 2.0, "min": 0.5, "close": 1.5}]}), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2020, 1)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-06-01"):
            out = tpc.fetch_price_history("2330", "TWSE", window_days=120)
        self.assertIn("error", out)


class FetchIndexHistoryTest(unittest.TestCase):
    def test_merges_and_sorts_index_months(self):
        def fake_index_month(year_month, cache=None):
            rows_by_month = {
                "202606": [{"date": "2026-06-30", "close": 100.0, "max": 100.0,
                           "min": None, "open": None}],
                "202607": [{"date": "2026-07-01", "close": 101.0, "max": 101.0,
                           "min": None, "open": None}],
            }
            return {"prices": rows_by_month.get(year_month, [])}

        with unittest.mock.patch.object(tpc, "fetch_twse_index_month", fake_index_month), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 6), (2026, 7)]), \
             unittest.mock.patch.object(tpc, "_days_ago", return_value="2026-01-01"):
            out = tpc.fetch_index_history(window_days=120)
        dates = [p["date"] for p in out["prices"]]
        self.assertEqual(dates, ["2026-06-30", "2026-07-01"])
        self.assertEqual(out["stock_id"], "TAIEX")

    def test_all_months_fail_returns_error(self):
        with unittest.mock.patch.object(
                tpc, "fetch_twse_index_month", return_value={"error": "斷網"}), \
             unittest.mock.patch.object(
                tpc, "_recent_year_months", return_value=[(2026, 7)]):
            out = tpc.fetch_index_history(window_days=120)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
