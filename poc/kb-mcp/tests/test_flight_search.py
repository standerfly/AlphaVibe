"""`flight_search.py` 測試：四段票枚舉、日期推導、回應萃取、節流與快取。

全部離線——`search_itinerary`／`scan` 的網路層以 monkeypatch 替換，
不消耗任何 SerpApi 額度（免費層只有 250 次/月，測試不該吃它）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight_search*"
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import flight_search  # noqa: E402


class BuildItinerariesTest(unittest.TestCase):
    """枚舉邏輯：組合數、四段結構、日期推導。"""

    def test_leg_structure_is_outstation_hub_destination_hub_outstation(self):
        """四段必須是 外站→樞紐→目的地→樞紐→外站，頭尾同一個外站。"""
        itins = flight_search.build_itineraries(
            "CDG", "2026-11", outstations=["BKK"], trip_days=[10])
        legs = itins[0]["legs"]
        self.assertEqual(len(legs), 4)
        self.assertEqual(
            [(l["departure_id"], l["arrival_id"]) for l in legs],
            [("BKK", "TPE"), ("TPE", "CDG"), ("CDG", "TPE"), ("TPE", "BKK")])

    def test_dates_follow_stay_and_trip_day_offsets(self):
        """日期推導：base → +out_stay → +trip_day → +ret_stay，逐段累加。"""
        itins = flight_search.build_itineraries(
            "CDG", "2026-11", outstations=["KUL"], trip_days=[10],
            out_stays=[2], ret_stays=[3])
        legs = itins[0]["legs"]
        self.assertEqual(legs[0]["date"], "2026-11-01")   # base
        self.assertEqual(legs[1]["date"], "2026-11-03")   # +2 外站停留
        self.assertEqual(legs[2]["date"], "2026-11-13")   # +10 主行程
        self.assertEqual(legs[3]["date"], "2026-11-16")   # +3 回程停留

    def test_dates_may_cross_into_next_month(self):
        """月底出發＋長行程會跨月，不該被截斷或報錯。"""
        itins = flight_search.build_itineraries(
            "CDG", "2026-11", outstations=["HKG"], trip_days=[10],
            out_stays=[0])
        last = itins[-1]["legs"]
        self.assertEqual(last[0]["date"], "2026-11-30")
        self.assertEqual(last[2]["date"], "2026-12-10")

    def test_combination_count_is_product_of_all_dimensions(self):
        """組合數＝外站 × 當月天數 × out_stay × trip_day × ret_stay。
        這個數字直接決定 API 額度夠不夠，算錯會燒光免費額度。"""
        itins = flight_search.build_itineraries(
            "CDG", "2026-11", outstations=["KUL", "BKK", "HKG"],
            trip_days=[8, 10], out_stays=[0, 2], ret_stays=[0])
        self.assertEqual(len(itins), 3 * 30 * 2 * 2 * 1)

    def test_february_leap_and_non_leap_day_counts(self):
        """月份天數要照實際曆法，不能寫死 30。"""
        self.assertEqual(
            len(flight_search.build_itineraries(
                "CDG", "2026-02", outstations=["BKK"], trip_days=[7],
                out_stays=[0])), 28)
        self.assertEqual(
            len(flight_search.build_itineraries(
                "CDG", "2028-02", outstations=["BKK"], trip_days=[7],
                out_stays=[0])), 29)

    def test_invalid_month_raises(self):
        with self.assertRaises(ValueError):
            flight_search.build_itineraries("CDG", "2026/11")


class DefaultsTest(unittest.TestCase):
    """預設值本身就是產品決策，值得釘住——改動要是刻意的，不是手滑。"""

    def test_out_stays_default_covers_same_day_and_next_day_transfer(self):
        """長途線常見「傍晚抵台北、隔日凌晨飛歐洲」，預設必須涵蓋隔日轉機。
        （PO 實例：BKK 18:00 抵台北 → TPE 隔日 00:10 飛 PRG）"""
        self.assertEqual(flight_search.DEFAULT_OUT_STAYS, [0, 1])
        itins = flight_search.build_itineraries(
            "PRG", "2026-07", outstations=["BKK"], trip_days=[10])
        self.assertEqual(len(itins), 31 * 2)

    def test_far_future_fourth_leg_is_expressible(self):
        """第四段可丟到很遠的未來（PO 實例相隔 57 天），枚舉要表達得出來。"""
        itins = flight_search.build_itineraries(
            "PRG", "2026-07", outstations=["BKK"], trip_days=[10],
            out_stays=[1], ret_stays=[57])
        legs = itins[1]["legs"]           # 7/2 出發那組，對齊 PO 實例
        self.assertEqual(legs[0]["date"], "2026-07-02")   # BKK→TPE
        self.assertEqual(legs[1]["date"], "2026-07-03")   # TPE→PRG
        self.assertEqual(legs[2]["date"], "2026-07-13")   # PRG→TPE
        self.assertEqual(legs[3]["date"], "2026-09-08")   # TPE→BKK，+57 天


class ConnectorCostTest(unittest.TestCase):
    """接駁成本：外站四段票的第一段要自費飛去搭，不算進去排序就是錯的。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-conn-test-")
        self._orig_fetch = flight_search._fetch

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_interleave_covers_all_outstations_before_second_date(self):
        """額度有限時要先橫向比外站，不能掃完一個外站的整月才換下一個。"""
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": 30000, "flights": []}]}
        report = flight_search.scan(
            "PRG", "2026-07", token="fake-key",
            outstations=["KUL", "BKK", "HKG"], trip_days=[10], out_stays=[0],
            data_dir=self.tmp, limit=3, rate_per_hour=0)
        self.assertEqual(sorted(r["outstation"] for r in report["results"]),
                         ["BKK", "HKG", "KUL"])
        self.assertEqual({r["base_date"] for r in report["results"]},
                         {"2026-07-01"})

    def test_total_cost_reorders_against_face_price(self):
        """票面價最低的外站，加上接駁票後可能不再是最便宜的。"""
        prices = iter([30000, 33000])
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": next(prices), "flights": []}]}
        report = flight_search.scan(
            "PRG", "2026-07", token="fake-key", outstations=["KUL", "BKK"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp, limit=2,
            rate_per_hour=0,
            # 輪替後同一天內按字母序：BKK 先、KUL 後 → 價格 33000/30000
            # KUL 票面便宜 3000，但接駁貴 9000 → 總成本應該輸給 BKK
            connector_prices={"KUL": 14000, "BKK": 5000})
        by_station = dict((r["outstation"], r) for r in report["results"])
        self.assertEqual(by_station["BKK"]["price"], 30000)   # 先掃到
        self.assertEqual(by_station["KUL"]["price"], 33000)
        self.assertEqual(by_station["BKK"]["total_cost"], 35000)
        self.assertEqual(by_station["KUL"]["total_cost"], 47000)
        self.assertEqual([r["outstation"] for r in report["results"]],
                         ["BKK", "KUL"])

    def test_missing_connector_price_falls_back_to_face_price(self):
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": 30000, "flights": []}]}
        report = flight_search.scan(
            "PRG", "2026-07", token="fake-key", outstations=["KUL"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp, limit=1,
            rate_per_hour=0, connector_prices={})
        self.assertEqual(report["results"][0]["total_cost"], 30000)
        self.assertIsNone(report["results"][0]["connector_price"])


class ConnectorUsageTest(unittest.TestCase):
    """接駁估價必須計入額度——漏記會讓守衛低估用量而超支。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-connusage-test-")
        self._orig_fetch = flight_search._fetch
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": 5200, "flights": []}]}

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_each_connector_lookup_is_recorded(self):
        flight_search.estimate_connectors(
            ["NRT", "KIX", "FUK"], "2027-02-10", "fake-key",
            data_dir=self.tmp)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 3)

    def test_cached_connector_does_not_double_count(self):
        kw = dict(data_dir=self.tmp)
        flight_search.estimate_connectors(["NRT"], "2027-02-10", "fake-key", **kw)
        flight_search.estimate_connectors(["NRT"], "2027-02-10", "fake-key", **kw)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 1)

    def test_stops_when_quota_exhausted(self):
        flight_search.record_usage(self.tmp, 249)      # 剩 1
        prices = flight_search.estimate_connectors(
            ["NRT", "KIX", "FUK"], "2027-02-10", "fake-key",
            data_dir=self.tmp, quota=250)
        self.assertEqual(prices["NRT"], 5200)
        self.assertIsNone(prices["KIX"])               # 額度用完，不再查
        self.assertIsNone(prices["FUK"])
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 250)


class PosTest(unittest.TestCase):
    """訂票地(POS)：不同國家版本可能不同價，快取必須分開存。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-pos-test-")
        self._orig_fetch = flight_search._fetch
        self.legs = flight_search.build_itineraries(
            "PRG", "2026-07", outstations=["BKK"], trip_days=[10])[0]["legs"]

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gl_hl_are_passed_through_to_api(self):
        captured = []
        flight_search._fetch = lambda params: (
            captured.append(params),
            {"best_flights": [{"price": 31036, "flights": []}]})[1]
        flight_search.search_itinerary(self.legs, "fake-key",
                                       data_dir=self.tmp, gl="nl", hl="nl")
        self.assertEqual(captured[0]["gl"], "nl")
        self.assertEqual(captured[0]["hl"], "nl")

    def test_different_pos_do_not_share_cache(self):
        """快取鍵不含 gl/hl 的話，荷蘭價會被當成台灣價回傳——嚴重誤導。"""
        seq = iter([{"best_flights": [{"price": 44794, "flights": []}]},
                    {"best_flights": [{"price": 31036, "flights": []}]}])
        flight_search._fetch = lambda params: next(seq)
        tw = flight_search.search_itinerary(self.legs, "k", data_dir=self.tmp,
                                            gl="tw", hl="zh-TW")
        nl = flight_search.search_itinerary(self.legs, "k", data_dir=self.tmp,
                                            gl="nl", hl="nl")
        self.assertEqual(tw["price"], 44794)
        self.assertEqual(nl["price"], 31036)

    def test_compare_pos_reports_spread(self):
        seq = iter([40000, 31000, 35000])
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": next(seq), "flights": []}]}
        report = flight_search.compare_pos(
            self.legs, "fake-key", pos_list=[("tw", "zh-TW"), ("nl", "nl"),
                                             ("hk", "zh-TW")],
            data_dir=self.tmp)
        self.assertEqual(report["spread"]["low"], 31000)
        self.assertEqual(report["spread"]["high"], 40000)
        self.assertEqual(report["spread"]["diff"], 9000)

    def test_oneway_connector_uses_type_2(self):
        captured = []
        flight_search._fetch = lambda params: (
            captured.append(params),
            {"best_flights": [{"price": 5200, "flights": []}]})[1]
        out = flight_search.search_oneway("TPE", "BKK", "2026-07-02",
                                          "fake-key", data_dir=self.tmp)
        self.assertEqual(captured[0]["type"], 2)
        self.assertEqual(captured[0]["departure_id"], "TPE")
        self.assertEqual(captured[0]["arrival_id"], "BKK")
        self.assertEqual(out["price"], 5200)


class FixedTripTest(unittest.TestCase):
    """固定主行程模式——對應 2026-09-22 PO 提供的曼谷/米蘭實例。

    實例參數：BKK 外站、主行程 2026-12-10 出發 / 2027-03-11 回，
    第 1 段早 15 天（11/25）、第 4 段晚 1 天（3/12，$15,225）或
    晚 13 天（3/24，$18,564）。
    """

    OUTBOUND = "2026-12-10"
    RETURN = "2027-03-11"

    def test_reproduces_po_screenshot_one(self):
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", self.OUTBOUND, self.RETURN, outstations=["BKK"],
            lead_days=[15], trail_days=[1])
        legs = itins[0]["legs"]
        self.assertEqual(
            [(l["departure_id"], l["arrival_id"], l["date"]) for l in legs],
            [("BKK", "TPE", "2026-11-25"), ("TPE", "MXP", "2026-12-10"),
             ("MXP", "TPE", "2027-03-11"), ("TPE", "BKK", "2027-03-12")])

    def test_reproduces_po_screenshot_two(self):
        """只有第 4 段不同——這一天之差在實例中造成 21.9% 價差。"""
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", self.OUTBOUND, self.RETURN, outstations=["BKK"],
            lead_days=[15], trail_days=[13])
        self.assertEqual(itins[0]["legs"][3]["date"], "2027-03-24")
        self.assertEqual(itins[0]["legs"][1]["date"], self.OUTBOUND)  # 主行程不動
        self.assertEqual(itins[0]["legs"][2]["date"], self.RETURN)

    def test_records_long_trip_duration(self):
        """主行程可以長達數月（實例是 91 天的米蘭旅居），不該被當成異常。"""
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", self.OUTBOUND, self.RETURN, outstations=["BKK"],
            lead_days=[15], trail_days=[1])
        self.assertEqual(itins[0]["trip_day"], 91)

    def test_defaults_cover_the_po_example_values(self):
        """預設掃描範圍必須涵蓋已知真實案例（lead=15、trail=1~13）。
        原本憑空定的 0-14 差一天就漏掉那組票。"""
        self.assertIn(15, flight_search.DEFAULT_LEAD_DAYS)
        self.assertIn(13, flight_search.DEFAULT_TRAIL_DAYS)
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", self.OUTBOUND, self.RETURN, outstations=["BKK"])
        dates = set(i["legs"][0]["date"] for i in itins)
        self.assertIn("2026-11-25", dates)   # lead=15 那組確實被枚舉

    def test_combination_count(self):
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", self.OUTBOUND, self.RETURN,
            outstations=["BKK", "KUL"], lead_days=[0, 7, 15],
            trail_days=[0, 13])
        self.assertEqual(len(itins), 2 * 3 * 2)

    def test_return_before_outbound_raises(self):
        with self.assertRaises(ValueError):
            flight_search.build_itineraries_fixed_trip(
                "MXP", "2027-03-11", "2026-12-10", outstations=["BKK"])

    def test_bad_date_format_raises(self):
        with self.assertRaises(ValueError):
            flight_search.build_itineraries_fixed_trip(
                "MXP", "2026/12/10", self.RETURN, outstations=["BKK"])


class LayeredScanTest(unittest.TestCase):
    """分層貪婪掃描：額度必須遠低於全組合，且要找得到便宜的第 4 段。"""

    OUTBOUND = "2026-12-10"
    RETURN = "2027-03-11"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-layer-test-")
        self._orig_fetch = flight_search._fetch

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _price_by_trail(self, params):
        """依第 4 段日期給價，重現 PO 兩張圖：3/12＝15225、3/24＝18564。"""
        legs = json.loads(params["multi_city_json"])
        last_date = legs[3]["date"]
        table = {"2027-03-12": 15225, "2027-03-24": 18564}
        return {"best_flights": [{"price": table.get(last_date, 21000),
                                  "flights": [{"airline": "EVA Air"}]}]}

    def test_finds_cheaper_fourth_leg_date(self):
        """第 3 層必須掃到 trail=1 那組，否則就錯過 3,339 元的價差。"""
        flight_search._fetch = self._price_by_trail
        report = flight_search.scan_layered(
            "MXP", self.OUTBOUND, self.RETURN, token="fake-key",
            outstations=["BKK"], lead_days=[15], trail_days=[1, 13],
            base_lead=15, base_trail=13, top_k=1, data_dir=self.tmp,
            rate_per_hour=0)
        self.assertIsNotNone(report["best"])
        self.assertEqual(report["best"]["price"], 15225)
        self.assertEqual(report["best"]["legs"][3]["date"], "2027-03-12")

    def test_spends_far_less_than_full_scan(self):
        flight_search._fetch = self._price_by_trail
        report = flight_search.scan_layered(
            "MXP", self.OUTBOUND, self.RETURN, token="fake-key",
            outstations=["BKK", "KUL", "HKG", "NRT"],
            lead_days=list(range(0, 15)), trail_days=list(range(0, 15)),
            top_k=2, data_dir=self.tmp, rate_per_hour=0)
        full = report["planned_full_scan"]
        self.assertEqual(full, 4 * 15 * 15)          # 900 次全掃
        self.assertLess(report["api_calls_spent"], 80)
        # 三層都要真的跑過
        self.assertEqual([l["name"] for l in report["layers"]],
                         ["外站比價", "第1段日期", "第4段日期"])

    def test_first_layer_all_failed_returns_error_not_crash(self):
        flight_search._fetch = lambda params: {"error": "SerpApi HTTP 500"}
        report = flight_search.scan_layered(
            "MXP", self.OUTBOUND, self.RETURN, token="fake-key",
            outstations=["BKK"], lead_days=[15], trail_days=[1],
            data_dir=self.tmp, rate_per_hour=0)
        self.assertIsNone(report["best"])
        self.assertIn("error", report)


class SummarizeTest(unittest.TestCase):
    """回應萃取：必須同時看 best_flights 與 other_flights。"""

    def test_picks_cheapest_across_both_buckets(self):
        """四段票的最低價常落在 other_flights，只看 best_flights 會漏掉。"""
        payload = {
            "best_flights": [{"price": 42000,
                              "flights": [{"airline": "EVA Air"}]}],
            "other_flights": [{"price": 31500,
                               "flights": [{"airline": "Thai Airways"},
                                           {"airline": "Thai Airways"}]}],
        }
        out = flight_search._summarize(payload)
        self.assertEqual(out["price"], 31500)
        self.assertEqual(out["airlines"], ["Thai Airways"])  # 去重
        self.assertEqual(out["source"], "flights")
        self.assertEqual(out["option_count"], 2)

    def test_falls_back_to_price_insights_when_no_flights(self):
        out = flight_search._summarize(
            {"price_insights": {"lowest_price": 28000}})
        self.assertEqual(out["price"], 28000)
        self.assertEqual(out["source"], "price_insights")

    def test_no_price_returns_none_not_exception(self):
        out = flight_search._summarize({"best_flights": []})
        self.assertIsNone(out["price"])
        self.assertEqual(out["source"], "none")

    def test_ignores_zero_and_missing_prices(self):
        out = flight_search._summarize(
            {"best_flights": [{"price": 0}, {"flights": []},
                              {"price": 19999}]})
        self.assertEqual(out["price"], 19999)


class SearchItineraryTest(unittest.TestCase):
    """單筆查詢：參數組裝、錯誤處理、快取。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-search-test-")
        self.captured = []
        self._orig_fetch = flight_search._fetch

        def fake_fetch(params):
            self.captured.append(params)
            return {"best_flights": [{"price": 33000,
                                      "flights": [{"airline": "EVA Air"}]}]}

        flight_search._fetch = fake_fetch
        self.legs = flight_search.build_itineraries(
            "CDG", "2026-11", outstations=["BKK"], trip_days=[10])[0]["legs"]

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sends_multi_city_type_3_with_all_four_legs(self):
        """type 必須是 3，四段要完整序列化進 multi_city_json。"""
        flight_search.search_itinerary(self.legs, "fake-key",
                                       data_dir=self.tmp)
        params = self.captured[0]
        self.assertEqual(params["type"], 3)
        self.assertEqual(params["engine"], "google_flights")
        self.assertEqual(json.loads(params["multi_city_json"]), self.legs)

    def test_defaults_to_economy_class(self):
        """商務艙在 multi-city 會跳艙翻倍，預設必須是經濟艙（1）。"""
        flight_search.search_itinerary(self.legs, "fake-key",
                                       data_dir=self.tmp)
        self.assertEqual(self.captured[0]["travel_class"], 1)

    def test_missing_token_returns_error_without_calling_api(self):
        out = flight_search.search_itinerary(self.legs, "", data_dir=self.tmp)
        self.assertIn("error", out)
        self.assertEqual(self.captured, [])

    def test_second_call_hits_cache_and_spends_no_api_call(self):
        first = flight_search.search_itinerary(self.legs, "fake-key",
                                               data_dir=self.tmp)
        second = flight_search.search_itinerary(self.legs, "fake-key",
                                                data_dir=self.tmp)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["price"], 33000)
        self.assertEqual(len(self.captured), 1)  # 只打了一次

    def test_error_response_is_not_cached(self):
        """失敗不能寫快取，否則暫時性錯誤會被永久記住。"""
        flight_search._fetch = lambda params: {"error": "SerpApi HTTP 429：quota"}
        out = flight_search.search_itinerary(self.legs, "fake-key",
                                             data_dir=self.tmp)
        self.assertIn("error", out)
        cache_dir = os.path.join(self.tmp, "flight_cache")
        self.assertFalse(os.path.isdir(cache_dir) and os.listdir(cache_dir))


class ScanTest(unittest.TestCase):
    """批次掃描：limit 計額、排序、429 提早停止。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-scan-test-")
        self._orig_fetch = flight_search._fetch

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_limit_caps_api_calls_and_results_are_price_sorted(self):
        prices = iter([50000, 30000, 40000])

        def fake_fetch(params):
            return {"best_flights": [{"price": next(prices), "flights": []}]}

        flight_search._fetch = fake_fetch
        report = flight_search.scan(
            "CDG", "2026-11", token="fake-key", outstations=["BKK"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp, limit=3,
            rate_per_hour=0)
        self.assertEqual(report["api_calls_spent"], 3)
        self.assertEqual(report["planned"], 30)      # 整月仍列 30 組
        self.assertEqual([r["price"] for r in report["results"]],
                         [30000, 40000, 50000])

    def test_stops_early_after_three_consecutive_quota_errors(self):
        """額度用盡就別再白跑 —— 連續 3 次 429 必須中止。"""
        flight_search._fetch = lambda params: {"error": "SerpApi HTTP 429：quota"}
        report = flight_search.scan(
            "CDG", "2026-11", token="fake-key", outstations=["BKK"],
            trip_days=[10], data_dir=self.tmp, rate_per_hour=0)
        self.assertEqual(report["api_calls_spent"], 3)
        self.assertEqual(report["priced_count"], 0)
        self.assertEqual(len(report["failures"]), 3)

    def test_one_failure_does_not_abort_whole_batch(self):
        seq = iter([
            {"error": "SerpApi HTTP 500：boom"},
            {"best_flights": [{"price": 27000, "flights": []}]},
        ])
        flight_search._fetch = lambda params: next(seq)
        report = flight_search.scan(
            "CDG", "2026-11", token="fake-key", outstations=["BKK"],
            trip_days=[10], data_dir=self.tmp, limit=2, rate_per_hour=0)
        self.assertEqual(report["priced_count"], 1)
        self.assertEqual(len(report["failures"]), 1)


class QuotaTest(unittest.TestCase):
    """免費額度守衛——PO 明確要求不花錢，這是唯一能保證的機制。

    額度是「本月用完就沒了」的硬限制，必須持久化追蹤：只靠單次執行的
    limit 參數擋不住「今天跑一次、明天再跑一次」累計超額。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-quota-test-")
        self._orig_fetch = flight_search._fetch
        flight_search._fetch = lambda params: {
            "best_flights": [{"price": 30000, "flights": []}]}

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_usage_starts_at_zero_and_accumulates(self):
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 0)
        flight_search.record_usage(self.tmp, 10)
        flight_search.record_usage(self.tmp, 5)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 15)
        self.assertEqual(flight_search.remaining_quota(self.tmp, 250), 235)

    def test_usage_resets_on_month_change(self):
        """額度按自然月重置——上個月的用量不該擋住這個月。"""
        path = os.path.join(self.tmp, "flight_usage.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"month": "2020-01", "count": 250}, fh)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 0)
        self.assertEqual(flight_search.remaining_quota(self.tmp, 250), 250)

    def test_corrupt_usage_file_does_not_crash(self):
        with open(os.path.join(self.tmp, "flight_usage.json"), "w") as fh:
            fh.write("{ not json")
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 0)

    def test_remaining_never_negative(self):
        flight_search.record_usage(self.tmp, 999)
        self.assertEqual(flight_search.remaining_quota(self.tmp, 250), 0)

    def test_scan_stops_when_quota_exhausted(self):
        """額度剩 2 次時，就算要掃 30 組也只能打 2 次。"""
        flight_search.record_usage(self.tmp, 248)   # 250 - 248 = 剩 2
        report = flight_search.scan(
            "PRG", "2026-07", token="fake-key", outstations=["BKK"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp,
            rate_per_hour=0, quota=250)
        self.assertEqual(report["api_calls_spent"], 2)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 250)

    def test_scan_records_usage_so_next_run_sees_it(self):
        """跨次執行累計：這次用掉的，下次執行要看得到。"""
        flight_search.scan(
            "PRG", "2026-07", token="fake-key", outstations=["BKK"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp, limit=5,
            rate_per_hour=0)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 5)
        self.assertEqual(flight_search.remaining_quota(self.tmp, 250), 245)

    def test_cache_hits_do_not_consume_quota(self):
        """重跑完全相同的一批查詢不該再扣額度，否則反覆測試會白燒。"""
        itins = flight_search.build_itineraries_fixed_trip(
            "MXP", "2026-12-10", "2027-03-11", outstations=["BKK"],
            lead_days=[0, 1, 2], trail_days=[0])
        self.assertEqual(len(itins), 3)
        _, spent = flight_search._query_batch(
            itins, "fake-key", data_dir=self.tmp, rate_per_hour=0)
        self.assertEqual(spent, 3)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 3)

        _, spent2 = flight_search._query_batch(   # 同一批再跑一次
            itins, "fake-key", data_dir=self.tmp, rate_per_hour=0)
        self.assertEqual(spent2, 0)               # 全部命中快取
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 3)

    def test_limit_resumes_forward_across_runs(self):
        """limit 是「本次最多打幾次 API」，快取不計入——所以重跑會往後推進，
        可以把一次大掃描拆成好幾天分批跑完，不會卡在同樣的前 N 組。"""
        kw = dict(token="fake-key", outstations=["BKK"], trip_days=[10],
                  out_stays=[0], data_dir=self.tmp, limit=3, rate_per_hour=0)
        first = flight_search.scan("PRG", "2026-07", **kw)
        second = flight_search.scan("PRG", "2026-07", **kw)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 6)
        first_dates = [r["base_date"] for r in first["results"]]
        new_dates = [r["base_date"] for r in second["results"]
                     if r["base_date"] not in first_dates]
        self.assertEqual(len(new_dates), 3)   # 第二次確實掃到 3 組新的

    def test_layered_scan_respects_quota_across_layers(self):
        """分層掃描三層加起來也不能超過額度。"""
        flight_search.record_usage(self.tmp, 245)   # 剩 5
        report = flight_search.scan_layered(
            "MXP", "2026-12-10", "2027-03-11", token="fake-key",
            outstations=["BKK", "KUL", "HKG"], lead_days=[0, 5, 15],
            trail_days=[0, 13], data_dir=self.tmp, rate_per_hour=0, quota=250)
        self.assertLessEqual(report["api_calls_spent"], 5)
        self.assertLessEqual(flight_search.read_usage(self.tmp)["count"], 250)

    def test_quota_none_disables_guard(self):
        """改用額度大得多的供應商時要能關掉守衛。"""
        flight_search.record_usage(self.tmp, 9999)
        report = flight_search.scan(
            "PRG", "2026-07", token="fake-key", outstations=["BKK"],
            trip_days=[10], out_stays=[0], data_dir=self.tmp, limit=2,
            rate_per_hour=0, quota=None)
        self.assertEqual(report["api_calls_spent"], 2)


class UrlBuilderTest(unittest.TestCase):
    """零成本查價路徑：直接產生可點開的查詢網址，不消耗任何 API 額度。"""

    LEGS = [{"departure_id": "NRT", "arrival_id": "TPE", "date": "2026-12-07"},
            {"departure_id": "TPE", "arrival_id": "PRG", "date": "2026-12-10"},
            {"departure_id": "PRG", "arrival_id": "TPE", "date": "2026-12-22"},
            {"departure_id": "TPE", "arrival_id": "NRT", "date": "2026-12-23"}]

    def test_tfs_matches_the_url_verified_against_google(self):
        """釘住 2026-09-22 實測通過的 tfs 值。

        該網址實測回 HTTP 200，頁面同時含四個航段日期與 NRT/TPE/PRG，
        且含 multi_city 標記。編碼若被改動，這個斷言會先失敗。
        """
        expected = ("GhoSCjIwMjYtMTItMDdqBRIDTlJUcgUSA1RQRRoaEgoyMDI2LTEyLTEw"
                    "agUSA1RQRXIFEgNQUkcaGhIKMjAyNi0xMi0yMmoFEgNQUkdyBRIDVFBF"
                    "GhoSCjIwMjYtMTItMjNqBRIDVFBFcgUSA05SVEgBQAGYAQM")
        self.assertIn("tfs=" + expected,
                      flight_search.google_flights_url(self.LEGS))

    @staticmethod
    def _trip_field(url):
        """解出 tfs 尾端的 trip 欄位值（f19 varint，key 編碼為 0x98 0x01）。"""
        import base64 as b64
        raw = url.split("tfs=")[1].split("&")[0]
        raw += "=" * (-len(raw) % 4)
        blob = b64.urlsafe_b64decode(raw)
        idx = blob.rfind(b"\x98\x01")
        return blob[idx + 2] if idx >= 0 else None

    def test_trip_type_depends_on_leg_count(self):
        """1 段＝單程(2)、2 段＝來回(1)、3 段以上＝多城市(3)。"""
        self.assertEqual(
            self._trip_field(flight_search.google_flights_url(self.LEGS[:1])), 2)
        self.assertEqual(
            self._trip_field(flight_search.google_flights_url(self.LEGS[:2])), 1)
        self.assertEqual(
            self._trip_field(flight_search.google_flights_url(self.LEGS)), 3)

    def test_market_params_are_passed(self):
        url = flight_search.google_flights_url(self.LEGS, hl="nl", gl="nl",
                                               currency="EUR")
        self.assertIn("hl=nl", url)
        self.assertIn("gl=nl", url)
        self.assertIn("curr=EUR", url)

    def test_airport_codes_are_upcased(self):
        legs = [{"departure_id": "nrt", "arrival_id": "tpe",
                 "date": "2026-12-07"}]
        self.assertEqual(flight_search.google_flights_url(legs),
                         flight_search.google_flights_url(
                             [{"departure_id": "NRT", "arrival_id": "TPE",
                               "date": "2026-12-07"}]))

    def test_skyscanner_url_is_oneway_only(self):
        """Skyscanner 多城市路徑 2026-09-22 實測 404，只保留單程用途。"""
        url = flight_search.skyscanner_url(self.LEGS[:1])
        self.assertIn("/nrt/tpe/261207/", url)
        self.assertIn("skyscanner.com.tw", url)

    def test_japan_outstations_listed(self):
        """PO 指定日本首選——東京兩場要分開列，票價常有落差。"""
        self.assertIn("NRT", flight_search.JAPAN_OUTSTATIONS)
        self.assertIn("HND", flight_search.JAPAN_OUTSTATIONS)
        self.assertIn("KIX", flight_search.JAPAN_OUTSTATIONS)


class CheapDateSearchTest(unittest.TestCase):
    """PO 的核心需求：日期是輸出不是輸入——先找便宜時段，再看時間合不合適。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-dates-test-")
        self._orig_fetch = flight_search._fetch
        self.captured = []

    def tearDown(self):
        flight_search._fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deals_fetch(self, params):
        self.captured.append(params)
        return {"deals": [
            {"price": 28000, "start_date": "2027-02-11",
             "end_date": "2027-02-22", "arrival_airport": "PRG"},
            {"price": 35000, "start_date": "2027-02-03",
             "end_date": "2027-02-14", "arrival_airport": "PRG"},
        ]}

    def test_sends_date_range_not_single_date(self):
        """關鍵：一次查詢涵蓋整個月窗口，不是逐日查。"""
        flight_search._fetch = self._deals_fetch
        flight_search.search_deals("TPE", "PRG", "2027-02-01", "2027-02-28",
                                   "fake-key", trip_length="10,14",
                                   data_dir=self.tmp)
        p = self.captured[0]
        self.assertEqual(p["engine"], "google_flights_deals")
        self.assertEqual(p["outbound_date"], "2027-02-01,2027-02-28")
        self.assertEqual(p["trip_length"], "10,14")
        self.assertEqual(p["type"], 1)      # Deals 不支援 multi-city

    def test_results_sorted_by_price(self):
        flight_search._fetch = self._deals_fetch
        out = flight_search.search_deals("TPE", "PRG", "2027-02-01",
                                         "2027-02-28", "fake-key",
                                         data_dir=self.tmp)
        self.assertEqual([d["price"] for d in out["deals"]], [28000, 35000])
        self.assertEqual(out["deals"][0]["outbound_date"], "2027-02-11")

    def test_filters_out_other_destinations(self):
        """arrival_id 未必被 engine 採用，必須再依回應內容過濾。"""
        flight_search._fetch = lambda params: {"deals": [
            {"price": 9000, "start_date": "2027-02-11",
             "end_date": "2027-02-22", "arrival_airport": "BKK"},
            {"price": 28000, "start_date": "2027-02-11",
             "end_date": "2027-02-22", "arrival_airport": "PRG"},
        ]}
        out = flight_search.search_deals("TPE", "PRG", "2027-02-01",
                                         "2027-02-28", "fake-key",
                                         data_dir=self.tmp)
        self.assertEqual(len(out["deals"]), 1)     # 便宜的曼谷不該混進來
        self.assertEqual(out["deals"][0]["price"], 28000)

    def test_one_api_call_per_month(self):
        """半年只花 6 次額度，而不是逐日查的 180 次。"""
        flight_search._fetch = self._deals_fetch
        report = flight_search.find_cheap_dates(
            "TPE", "PRG", "fake-key", months_ahead=6, data_dir=self.tmp,
            rate_per_hour=0, start_date="2026-10-01")
        self.assertEqual(report["api_calls_spent"], 6)
        self.assertEqual(len(self.captured), 6)

    def test_month_windows_are_contiguous_and_correct(self):
        """窗口要接續不重疊，且月底日期要照曆法（2 月不是 30 天）。"""
        flight_search._fetch = self._deals_fetch
        flight_search.find_cheap_dates(
            "TPE", "PRG", "fake-key", months_ahead=3, data_dir=self.tmp,
            rate_per_hour=0, start_date="2027-01-01")
        windows = [p["outbound_date"] for p in self.captured]
        self.assertEqual(windows, ["2027-01-01,2027-01-31",
                                   "2027-02-01,2027-02-28",
                                   "2027-03-01,2027-03-31"])

    def test_skips_stub_first_window(self):
        """起始月剩不到 14 天就跳到下個月——殘缺窗口浪費額度又找不到便宜票。"""
        flight_search._fetch = self._deals_fetch
        flight_search.find_cheap_dates(
            "TPE", "PRG", "fake-key", months_ahead=2, data_dir=self.tmp,
            rate_per_hour=0, start_date="2026-09-22")   # 9 月只剩 9 天
        windows = [p["outbound_date"] for p in self.captured]
        self.assertEqual(windows, ["2026-10-01,2026-10-31",
                                   "2026-11-01,2026-11-30"])

    def test_keeps_first_window_when_enough_days_left(self):
        """月初執行時不該跳過當月。"""
        flight_search._fetch = self._deals_fetch
        flight_search.find_cheap_dates(
            "TPE", "PRG", "fake-key", months_ahead=1, data_dir=self.tmp,
            rate_per_hour=0, start_date="2026-09-05")
        self.assertEqual(self.captured[0]["outbound_date"],
                         "2026-09-05,2026-09-30")

    def test_two_stage_budget_is_small(self):
        """半年 × 7 外站 × 前 5 個日期 = 6 + 35 = 41 次，遠低於全掃。"""
        def fetch(params):
            if params.get("engine") == "google_flights_deals":
                return self._deals_fetch(params)
            return {"best_flights": [{"price": 31000, "flights": []}]}
        flight_search._fetch = fetch
        report = flight_search.plan_cheap_trip(
            "TPE", "PRG", "fake-key",
            outstations=flight_search.JAPAN_OUTSTATIONS,
            months_ahead=6, top_dates=5, data_dir=self.tmp, rate_per_hour=0,
            start_date="2026-10-01")
        self.assertEqual(report["stage1"]["api_calls_spent"], 6)
        # 只有 2 組不重複日期可選，所以第 2 階段是 2 × 7
        self.assertEqual(report["stage2"]["spent"],
                         len(report["stage2"]["candidates"])
                         * len(flight_search.JAPAN_OUTSTATIONS))
        self.assertLess(report["api_calls_spent"], 50)

    def test_duplicate_dates_collapse_to_cheapest(self):
        """同一組出發/回程日只留最便宜那筆，避免 top_dates 被同一天塞滿。"""
        flight_search._fetch = lambda params: (
            {"deals": [
                {"price": 40000, "start_date": "2027-02-11",
                 "end_date": "2027-02-22", "arrival_airport": "PRG"},
                {"price": 28000, "start_date": "2027-02-11",
                 "end_date": "2027-02-22", "arrival_airport": "PRG"},
            ]} if params.get("engine") == "google_flights_deals"
            else {"best_flights": [{"price": 31000, "flights": []}]})
        report = flight_search.plan_cheap_trip(
            "TPE", "PRG", "fake-key", outstations=["NRT"], months_ahead=1,
            top_dates=5, data_dir=self.tmp, rate_per_hour=0,
            start_date="2027-02-01")
        self.assertEqual(len(report["stage2"]["candidates"]), 1)
        self.assertEqual(report["stage2"]["candidates"][0]["price"], 28000)

    def test_stage1_empty_reports_error_not_crash(self):
        flight_search._fetch = lambda params: {"deals": []}
        report = flight_search.plan_cheap_trip(
            "TPE", "PRG", "fake-key", outstations=["NRT"], months_ahead=2,
            data_dir=self.tmp, rate_per_hour=0, start_date="2027-02-01")
        self.assertIsNone(report["stage2"])
        self.assertIn("error", report)


class BrowserScrapeTest(unittest.TestCase):
    """瀏覽器路徑（PO 選定的主力）：不消耗 API 額度，改由 node scraper 取價。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-scrape-test-")
        self._orig_popen = flight_search.subprocess.Popen
        self._orig_avail = flight_search.scraper_available
        flight_search.scraper_available = lambda: True
        self.sent = []
        self.itins = flight_search.build_itineraries_fixed_trip(
            "PRG", "2027-05-08", "2027-05-20", outstations=["NRT", "OKA"],
            lead_days=[3], trail_days=[1])

    def tearDown(self):
        flight_search.subprocess.Popen = self._orig_popen
        flight_search.scraper_available = self._orig_avail
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_run(self, payload_out):
        """模擬 scraper 的 JSON Lines 輸出（每筆一行，最後一行 summary）。"""
        lines = []
        for r in payload_out.get("results", []):
            row = dict(r)
            row["type"] = "result"
            lines.append(json.dumps(row) + "\n")
        summary = {"type": "summary",
                   "blocked": payload_out.get("blocked", False),
                   "soft_blocked": payload_out.get("soft_blocked", False),
                   "stats": payload_out.get("stats", {})}
        if payload_out.get("error"):
            summary["error"] = payload_out["error"]
        lines.append(json.dumps(summary) + "\n")
        return self._popen_returning(lines)

    def _popen_returning(self, lines):
        outer = self

        class FakeStdin(object):
            def write(self, data):
                outer.sent.append(json.loads(data.decode("utf-8")))

            def close(self):
                pass

        class FakeProc(object):
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = iter([l.encode("utf-8") for l in lines])

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        def popen(cmd, stdin=None, stdout=None, stderr=None):
            return FakeProc()
        return popen

    def test_sends_urls_and_throttle_config_to_scraper(self):
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "ok", "price": 47529,
                         "airline": "星宇航空"},
                        {"id": "1", "status": "ok", "price": 45812,
                         "airline": "星宇航空"}],
            "blocked": False, "stats": {"ok": 2}})
        out = flight_search.scrape_itineraries(
            self.itins, data_dir=self.tmp, min_delay_ms=5000,
            max_delay_ms=11000)
        sent = self.sent[0]
        self.assertEqual(len(sent["urls"]), 2)
        self.assertEqual(sent["min_delay_ms"], 5000)
        self.assertEqual(sent["max_delay_ms"], 11000)
        self.assertTrue(sent["urls"][0]["url"].startswith(
            "https://www.google.com/travel/flights?tfs="))
        prices = sorted(r["price"] for r in out["results"])
        self.assertEqual(prices, [45812, 47529])

    def test_result_shape_matches_api_path(self):
        """瀏覽器與 API 兩條路的結果形狀要一致，才能互換與共用排序。"""
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "ok", "price": 47529,
                         "airline": "星宇航空", "option_count": 6}],
            "blocked": False, "stats": {}})
        out = flight_search.scrape_itineraries(
            self.itins[:1], data_dir=self.tmp)
        row = out["results"][0]
        for field in ("price", "airlines", "outstation", "legs", "cached"):
            self.assertIn(field, row)
        self.assertEqual(row["airlines"], ["星宇航空"])
        self.assertEqual(row["source"], "browser")

    def test_second_run_hits_cache_without_launching_browser(self):
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "ok", "price": 47529,
                         "airline": "星宇航空"}],
            "blocked": False, "stats": {}})
        flight_search.scrape_itineraries(self.itins[:1], data_dir=self.tmp)
        self.assertEqual(len(self.sent), 1)

        def boom(*a, **k):
            raise AssertionError("命中快取時不該再啟動瀏覽器")
        flight_search.subprocess.Popen = boom
        out = flight_search.scrape_itineraries(self.itins[:1],
                                               data_dir=self.tmp)
        self.assertTrue(out["results"][0]["cached"])
        self.assertEqual(out["results"][0]["price"], 47529)

    def test_blocked_flag_is_surfaced(self):
        """被擋必須明確回報——繼續打只會加深封鎖。"""
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "blocked"}],
            "blocked": True, "stats": {}})
        out = flight_search.scrape_itineraries(self.itins[:1],
                                               data_dir=self.tmp)
        self.assertTrue(out["blocked"])
        self.assertIsNone(out["results"][0]["price"])

    def test_soft_block_is_surfaced_separately(self):
        """連續逾時形式的軟封鎖要能跟明確封鎖頁區分——2026-09-22 實測遇到
        的是前者，當時認不出來而白打了 16 次。"""
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "timeout"}],
            "blocked": True, "soft_blocked": True, "stats": {}})
        out = flight_search.scrape_itineraries(self.itins[:1],
                                               data_dir=self.tmp)
        self.assertTrue(out["blocked"])
        self.assertTrue(out["soft_blocked"])

    def test_failed_scrape_is_not_cached(self):
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "timeout"}],
            "blocked": False, "stats": {}})
        flight_search.scrape_itineraries(self.itins[:1], data_dir=self.tmp)
        cache_dir = os.path.join(self.tmp, "flight_cache")
        self.assertFalse(os.path.isdir(cache_dir) and os.listdir(cache_dir))

    def test_results_are_cached_as_they_stream_in(self):
        """逐筆落地：即使 summary 行從未送達（模擬中途當機），
        已完成的結果仍必須留在快取裡，重跑才不會全部重查。"""
        rows = [json.dumps({"type": "result", "id": "0", "status": "ok",
                            "price": 47529, "airline": "星宇航空"}) + "\n"]
        flight_search.subprocess.Popen = self._popen_returning(rows)
        flight_search.scrape_itineraries(self.itins, data_dir=self.tmp)
        cache_dir = os.path.join(self.tmp, "flight_cache")
        self.assertEqual(len(os.listdir(cache_dir)), 1)

        # 重跑：第一筆命中快取，只有第二筆需要再查
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "ok", "price": 45812,
                         "airline": "星宇航空"}],
            "blocked": False, "stats": {}})
        out = flight_search.scrape_itineraries(self.itins, data_dir=self.tmp)
        self.assertEqual(len(self.sent[-1]["urls"]), 1)   # 只送了 1 個 URL
        cached = [r for r in out["results"] if r.get("cached")]
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0]["price"], 47529)

    def test_missing_scraper_reports_error(self):
        flight_search.scraper_available = lambda: False
        out = flight_search.scrape_itineraries(self.itins, data_dir=self.tmp)
        self.assertIn("error", out)
        self.assertEqual(out["results"], [])

    def test_scraping_does_not_consume_api_quota(self):
        """瀏覽器路徑完全不該動到 API 額度計數。"""
        flight_search.subprocess.Popen = self._fake_run({
            "results": [{"id": "0", "status": "ok", "price": 47529,
                         "airline": "星宇航空"}],
            "blocked": False, "stats": {}})
        flight_search.scrape_itineraries(self.itins[:1], data_dir=self.tmp)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 0)


class PickLeadTest(unittest.TestCase):
    """為每個主行程日期各自挑 lead，讓第1段避開指定月份。

    緣由（2026-09-23 PO）：主行程要避開北半球暑假，第1段也不想在夏季。
    單一 lead 值做不到——主行程 2027-12 配 lead 120 會把第1段推到 8 月、
    lead 150 推到 7 月，都在夏季；得用 lead 60（第1段落 10 月）。
    """

    CANDS = [60, 90, 120, 150, 180, 210]
    SUMMER = [6, 7, 8]

    def test_picks_first_candidate_that_avoids_summer(self):
        # 2027-09-01 − 60 天 = 7 月（夏季，跳過）→ 90 天 = 6 月（夏季，跳過）
        # → 120 天 = 5 月（合格）
        self.assertEqual(
            flight_search.pick_lead("2027-09-01", self.CANDS, self.SUMMER), 120)

    def test_december_needs_short_lead_not_long(self):
        """反直覺但正確：12 月主行程要用**短** lead 才避得開夏季。"""
        self.assertEqual(
            flight_search.pick_lead("2027-12-01", self.CANDS, self.SUMMER), 60)

    def test_skips_leads_landing_in_the_past(self):
        """第1段不能排在今天之前。"""
        soon = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        lead = flight_search.pick_lead(soon, [365, 60, 10], [])
        self.assertEqual(lead, 10)      # 365 與 60 都會落在過去

    def test_returns_none_when_nothing_qualifies(self):
        soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        self.assertIsNone(
            flight_search.pick_lead(soon, [120, 150], self.SUMMER))

    def test_no_exclusion_returns_first_future_candidate(self):
        self.assertEqual(
            flight_search.pick_lead("2027-09-01", self.CANDS, []), 60)

    def test_all_sampled_dates_avoid_summer_first_leg(self):
        """整批驗收：8 個抽樣日期的第1段都不可落在 6–8 月。"""
        pairs = flight_search.sample_dates(4, 2, 12, start_date="2027-09-01")
        for ob, _rt in pairs:
            lead = flight_search.pick_lead(ob, self.CANDS, self.SUMMER)
            self.assertIsNotNone(lead, "%s 找不到合格 lead" % ob)
            d1 = (datetime.date.fromisoformat(ob)
                  - datetime.timedelta(days=lead))
            self.assertNotIn(d1.month, self.SUMMER,
                             "%s 的第1段落在 %d 月" % (ob, d1.month))


class PickTrailTest(unittest.TestCase):
    """第4段（台北→外站）的延後天數挑選，與 pick_lead 對稱。

    PO 2026-09-23 追加需求：第3段與第4段的間隔也要能設定，理由同樣是
    避免密集請假——第4段緊接回程就是連續行程，拉遠後可當下一趟旅行的去程。
    這一端的價格槓桿比第1段更大（SRC-003／SRC-004：僅第4段差 12 天，
    票價差 21.9%）。
    """

    CANDS = [1, 14, 30, 60, 90, 120]
    SUMMER = [6, 7, 8]

    def test_picks_first_candidate_avoiding_excluded_months(self):
        # 回程 2027-05-20：+1 天＝5 月（可）
        self.assertEqual(
            flight_search.pick_trail("2027-05-20", self.CANDS, self.SUMMER), 1)

    def test_skips_candidates_landing_in_excluded_months(self):
        # 回程 2027-05-25：+14＝6 月（排除）、+30＝6 月（排除）、
        # +60＝7 月（排除）、+90＝8 月（排除）、+120＝9 月（可）
        self.assertEqual(
            flight_search.pick_trail("2027-05-25", [14, 30, 60, 90, 120],
                                     self.SUMMER), 120)

    def test_is_symmetric_with_pick_lead_direction(self):
        """lead 往前推、trail 往後推——同一組候選值結果應不同。"""
        lead = flight_search.pick_lead("2027-09-01", [60, 90], self.SUMMER)
        trail = flight_search.pick_trail("2027-09-01", [60, 90], self.SUMMER)
        self.assertIsNone(lead)          # 往前推 60/90 天都落在 6-7 月
        self.assertEqual(trail, 60)      # 往後推 60 天落在 10 月

    def test_candidate_order_is_preference_order(self):
        """候選順序即偏好順序，本函式不做最佳化。

        2026-09-23 實測踩到：候選寫成 [1, 14, 30] 時每組都挑到「延後 1 天」，
        即第4段緊接回程——正是 PO 想避免的密集行程。要拉遠就把大值放前面。
        """
        rt = "2027-05-20"
        self.assertEqual(flight_search.pick_trail(rt, [1, 30, 90], []), 1)
        self.assertEqual(flight_search.pick_trail(rt, [90, 30, 1], []), 90)

    def test_returns_none_when_nothing_qualifies(self):
        self.assertIsNone(
            flight_search.pick_trail("2027-05-25", [14, 30], self.SUMMER))

    def test_no_exclusion_returns_first_candidate(self):
        self.assertEqual(
            flight_search.pick_trail("2027-05-20", self.CANDS, []), 1)

    def test_southern_hemisphere_exclusion_works_too(self):
        """南半球旺季（12,1,2）同樣適用，不寫死北半球。"""
        # 回程 2027-11-20：+14＝12 月（排除）、+30＝12 月（排除）、
        # +60＝1 月（排除）、+90＝2 月（排除）、+120＝3 月（可）
        self.assertEqual(
            flight_search.pick_trail("2027-11-20", [14, 30, 60, 90, 120],
                                     flight_search.SOUTHERN_SUMMER_MONTHS), 120)


class HourlyBrowserRateTest(unittest.TestCase):
    """瀏覽器路徑的滾動小時速率守衛。

    快取時間戳證據：52 筆/小時與 205 筆/小時都被擋，故限制更可能是速率
    而非每日總量（前一版誤寫成「每日 25 筆、跨日歸零」，那個「跨日」
    毫無證據支持）。與 API 路徑的月額度是不同的限制來源，分開記帳。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-daily-test-")
        self._orig_popen = flight_search.subprocess.Popen
        self._orig_avail = flight_search.scraper_available
        flight_search.scraper_available = lambda: True
        self.itins = flight_search.build_itineraries_fixed_trip(
            "PRG", "2027-05-01", "2027-05-13", outstations=["OKA", "NRT"],
            lead_days=[90], trail_days=[1])

    def tearDown(self):
        flight_search.subprocess.Popen = self._orig_popen
        flight_search.scraper_available = self._orig_avail
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _popen(self, rows):
        outer = self

        class FakeStdin(object):
            def write(self, data):
                outer.last = json.loads(data.decode("utf-8"))

            def close(self):
                pass

        class FakeProc(object):
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = iter([l.encode("utf-8") for l in rows])

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass
        return lambda *a, **k: FakeProc()

    def test_old_queries_fall_out_of_window(self):
        """滾動視窗：一小時前的查詢不該再計入。"""
        import time as _t
        old = _t.time() - 7200      # 2 小時前
        recent = _t.time() - 60     # 1 分鐘前
        with open(os.path.join(self.tmp, "flight_browser_usage.json"),
                  "w") as fh:
            json.dump({"queries": [old, old, recent]}, fh)
        self.assertEqual(flight_search.read_browser_usage(self.tmp)["count"], 1)

    def test_reports_wait_time_when_saturated(self):
        """配額滿時要能算出還要等多久，而不是只說「明天再來」。"""
        import time as _t
        stamps = [_t.time() - 1800] * 20      # 半小時前跑滿 20 筆
        with open(os.path.join(self.tmp, "flight_browser_usage.json"),
                  "w") as fh:
            json.dump({"queries": stamps}, fh)
        wait = flight_search.seconds_until_quota_frees(self.tmp, 20)
        self.assertGreater(wait, 1500)        # 約再等半小時
        self.assertLess(wait, 1900)

    def test_blocks_when_hourly_rate_reached(self):
        flight_search.record_browser_usage(self.tmp, 20)

        def boom(*a, **k):
            raise AssertionError("已達每日上限時不該啟動瀏覽器")
        flight_search.subprocess.Popen = boom
        out = flight_search.scrape_itineraries(
            self.itins, data_dir=self.tmp, hourly_limit=20)
        self.assertIn("error", out)
        self.assertIn("20", out["error"])

    def test_trims_batch_to_remaining_quota(self):
        """今日只剩 1 筆時，2 筆的批次要被裁成 1 筆，而不是整批拒絕。"""
        flight_search.record_browser_usage(self.tmp, 19)
        flight_search.subprocess.Popen = self._popen([
            json.dumps({"type": "result", "id": "0", "status": "ok",
                        "price": 36917, "airline": "星宇航空"}) + "\n",
            json.dumps({"type": "summary", "blocked": False,
                        "stats": {}}) + "\n"])
        flight_search.scrape_itineraries(self.itins, data_dir=self.tmp,
                                         hourly_limit=20)
        self.assertEqual(len(self.last["urls"]), 1)
        self.assertEqual(flight_search.read_browser_usage(self.tmp)["count"],
                         20)

    def test_timeout_also_consumes_daily_quota(self):
        """逾時一樣消耗配額——請求已經發出去了，不記帳會低估用量。"""
        flight_search.subprocess.Popen = self._popen([
            json.dumps({"type": "result", "id": "0",
                        "status": "timeout"}) + "\n",
            json.dumps({"type": "summary", "blocked": False,
                        "stats": {}}) + "\n"])
        flight_search.scrape_itineraries(self.itins[:1], data_dir=self.tmp)
        self.assertEqual(flight_search.read_browser_usage(self.tmp)["count"], 1)

    def test_separate_from_api_monthly_quota(self):
        """瀏覽器用量不該動到 API 月額度，反之亦然。"""
        flight_search.record_browser_usage(self.tmp, 10)
        self.assertEqual(flight_search.read_usage(self.tmp)["count"], 0)
        flight_search.record_usage(self.tmp, 7)
        self.assertEqual(flight_search.read_browser_usage(self.tmp)["count"],
                         10)

    def test_hourly_limit_none_disables_guard(self):
        flight_search.record_browser_usage(self.tmp, 999)
        flight_search.subprocess.Popen = self._popen([
            json.dumps({"type": "summary", "blocked": False,
                        "stats": {}}) + "\n"])
        out = flight_search.scrape_itineraries(
            self.itins[:1], data_dir=self.tmp, hourly_limit=None)
        self.assertNotIn("error", out)


class SampleDatesTest(unittest.TestCase):
    """日期抽樣：瀏覽器沒有額度限制，直接抽樣掃描即可。"""

    def test_skips_near_term_dates(self):
        """近期票價本來就高，21 天內不該掃。"""
        pairs = flight_search.sample_dates(months_ahead=2, per_month=4,
                                           start_date="2026-09-22")
        earliest = min(p[0] for p in pairs)
        self.assertGreaterEqual(earliest, "2026-10-13")

    def test_covers_requested_number_of_months(self):
        """months_ahead 是「抽到樣本的月份數」。起始月可能因 21 天緩衝
        少掉前幾個抽樣日（本例 10/01、10/08 都在緩衝內），筆數因此少於
        months_ahead × per_month，但月份數必須剛好。"""
        pairs = flight_search.sample_dates(months_ahead=6, per_month=4,
                                           start_date="2026-09-22")
        months = sorted(set(p[0][:7] for p in pairs))
        self.assertEqual(len(months), 6)
        self.assertEqual(months[0], "2026-10")
        self.assertEqual(months[-1], "2027-03")
        self.assertEqual(len(pairs), 22)   # 10 月被緩衝削掉 2 個

    def test_excludes_requested_months(self):
        """排除的月份不計入 months_ahead——要的是 N 個可用月份。"""
        pairs = flight_search.sample_dates(
            months_ahead=9, per_month=2, start_date="2026-12-01",
            exclude_months=flight_search.NORTHERN_SUMMER_MONTHS)
        months = sorted(set(p[0][:7] for p in pairs))
        self.assertEqual(len(months), 9)
        for m in months:
            self.assertNotIn(int(m[5:7]), [6, 7, 8])
        # 明確指定的 start_date 不再被 21 天緩衝往後推
        self.assertEqual(months[0], "2026-12")
        self.assertEqual(months[-1], "2027-11")   # 跳過 6-8 月後往後延伸

    def test_explicit_future_start_date_is_not_pushed_by_lead_buffer(self):
        """指定未來起始日時不該再加緩衝，否則整個起始月會被跳掉。"""
        pairs = flight_search.sample_dates(
            months_ahead=1, per_month=2, start_date="2027-01-01")
        self.assertEqual(pairs[0][0], "2027-01-01")

    def test_near_term_start_date_still_respects_buffer(self):
        """但起始日若在緩衝內，仍要被推到緩衝之後——近期票價高不值得掃。"""
        pairs = flight_search.sample_dates(
            months_ahead=1, per_month=4,
            start_date=datetime.date.today().isoformat())
        floor = datetime.date.today() + datetime.timedelta(days=21)
        self.assertGreaterEqual(pairs[0][0], floor.isoformat())

    def test_hemisphere_constants(self):
        """兩個半球的旺季相反——把「夏季」寫死成 6-8 月會讓南半球航線判斷錯誤
        （2026-09-23 PO 審閱需求時指正）。"""
        self.assertEqual(flight_search.NORTHERN_SUMMER_MONTHS, [6, 7, 8])
        self.assertEqual(flight_search.SOUTHERN_SUMMER_MONTHS, [12, 1, 2])


class ParseMonthsTest(unittest.TestCase):
    """排除月份必須是 1-12 自由複選，季節快捷須標明半球。"""

    def test_hemisphere_shortcuts(self):
        self.assertEqual(flight_search._parse_months("north-summer"), [6, 7, 8])
        self.assertEqual(flight_search._parse_months("south-summer"), [12, 1, 2])

    def test_bare_summer_is_northern_alias(self):
        """保留無字首的 summer 僅為相容既有用法，等同 north-summer。"""
        self.assertEqual(flight_search._parse_months("summer"),
                         flight_search._parse_months("north-summer"))

    def test_arbitrary_multiselect_including_non_contiguous(self):
        """任意複選，不限連續月份。"""
        self.assertEqual(flight_search._parse_months("2,7,12"), [2, 7, 12])

    def test_deduplicates_and_preserves_order(self):
        self.assertEqual(flight_search._parse_months("6,7,6,8"), [6, 7, 8])

    def test_rejects_out_of_range(self):
        for bad in ("0", "13", "6,13"):
            with self.assertRaises(ValueError):
                flight_search._parse_months(bad)

    def test_empty_means_no_exclusion(self):
        self.assertEqual(flight_search._parse_months(""), [])
        self.assertEqual(flight_search._parse_months(None), [])

    def test_southern_hemisphere_scan_excludes_correct_months(self):
        """南半球情境：排除 12,1,2 後，抽樣日期不得落在那三個月。"""
        pairs = flight_search.sample_dates(
            months_ahead=9, per_month=2, start_date="2027-01-01",
            exclude_months=flight_search.SOUTHERN_SUMMER_MONTHS)
        for ob, _rt in pairs:
            self.assertNotIn(int(ob[5:7]), [12, 1, 2],
                             "%s 落在南半球旺季" % ob)
        self.assertEqual(len(set(p[0][:7] for p in pairs)), 9)

    def test_currency_constants(self):
        """對外 API 用 ISO 代碼 TWD，顯示用 NTD——同一貨幣的不同寫法。"""
        self.assertEqual(flight_search.DEFAULT_CURRENCY, "TWD")
        self.assertEqual(flight_search.DISPLAY_CURRENCY, "NTD")

    def test_return_date_follows_trip_days(self):
        pairs = flight_search.sample_dates(months_ahead=1, per_month=1,
                                           trip_days=12,
                                           start_date="2026-09-22")
        out, ret = pairs[0]
        d1 = datetime.date.fromisoformat(out)
        d2 = datetime.date.fromisoformat(ret)
        self.assertEqual((d2 - d1).days, 12)


class TokenTest(unittest.TestCase):
    """token 優先序：參數 > 環境變數 > data_dir 檔案。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-token-test-")
        self._orig_env = os.environ.get("SERPAPI_KEY")
        os.environ.pop("SERPAPI_KEY", None)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("SERPAPI_KEY", None)
        else:
            os.environ["SERPAPI_KEY"] = self._orig_env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_priority_order(self):
        with open(os.path.join(self.tmp, "serpapi_token.txt"), "w") as fh:
            fh.write("from-file\n")
        self.assertEqual(flight_search._read_token(self.tmp), "from-file")
        os.environ["SERPAPI_KEY"] = "from-env"
        self.assertEqual(flight_search._read_token(self.tmp), "from-env")
        self.assertEqual(flight_search._read_token(self.tmp, "from-arg"),
                         "from-arg")

    def test_no_token_anywhere_returns_empty_string(self):
        self.assertEqual(flight_search._read_token(self.tmp), "")


if __name__ == "__main__":
    unittest.main()
