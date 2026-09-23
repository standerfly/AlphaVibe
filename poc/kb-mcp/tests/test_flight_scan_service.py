"""`flight_scan_service.py` 測試：組合展開、未完成推導、掃描、狀態判定。

全部離線——查價層以 monkeypatch 替換，不連外部服務、不消耗配額。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight_scan*"
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

import flight_search as fs  # noqa: E402
import flight_scan_service as svc  # noqa: E402
from flight_store import FlightStore  # noqa: E402


def _future_window(months_from_now=6, span=2):
    """產生一個確定在未來的 YYYY-MM 區間，避免測試隨時間失效。"""
    base = datetime.date.today().replace(day=1)
    for _ in range(months_from_now):
        base = (base + datetime.timedelta(days=32)).replace(day=1)
    end = base
    for _ in range(span - 1):
        end = (end + datetime.timedelta(days=32)).replace(day=1)
    return base.strftime("%Y-%m"), end.strftime("%Y-%m")


class ExpandTrackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-svc-test-")
        self.store = FlightStore(self.tmp)
        self.ws, self.we = _future_window()

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _track(self, **kw):
        args = dict(destination="PRG", outstations=["NRT", "OKA"],
                    window_start=self.ws, window_end=self.we, trip_days=12)
        args.update(kw)
        return self.store.create_track(**args)

    def test_combination_count_is_months_times_samples_times_outstations(self):
        t = self._track(samples_per_month=2)
        itins, skipped = svc.expand_track(t)
        self.assertEqual(len(itins), 2 * 2 * 2)   # 2 月 × 2 抽樣 × 2 外站
        self.assertEqual(skipped, [])

    def test_four_legs_with_correct_shape(self):
        t = self._track(outstations=["NRT"], samples_per_month=1)
        itins, _ = svc.expand_track(t)
        legs = itins[0]["legs"]
        self.assertEqual(len(legs), 4)
        self.assertEqual(
            [(l["departure_id"], l["arrival_id"]) for l in legs],
            [("NRT", "TPE"), ("TPE", "PRG"), ("PRG", "TPE"), ("TPE", "NRT")])

    def test_strategy_maps_to_expected_offsets(self):
        t = self._track(outstations=["NRT"], samples_per_month=1,
                        lead_strategy="m5", trail_strategy="m3")
        itins, _ = svc.expand_track(t)
        self.assertEqual(itins[0]["lead"], 150)
        self.assertEqual(itins[0]["trail"], 90)

    def test_auto_strategy_avoids_excluded_months_on_both_ends(self):
        """auto 模式下，第1段與第4段都不得落在各自的排除月份。"""
        t = self._track(lead_strategy="auto", trail_strategy="auto",
                        exclude_months_lead=[6, 7, 8],
                        exclude_months_trail=[6, 7, 8])
        itins, _ = svc.expand_track(t)
        self.assertTrue(itins)
        for i in itins:
            m1 = int(i["legs"][0]["date"][5:7])
            m4 = int(i["legs"][3]["date"][5:7])
            self.assertNotIn(m1, [6, 7, 8])
            self.assertNotIn(m4, [6, 7, 8])

    def test_auto_prefers_longer_offset_not_nearest(self):
        """拉遠是目標而非僅約束（FR-008）。

        即使「緊接主行程」那個候選未被排除月份擋下，auto 也必須挑較遠的
        值——2026-09-23 實測踩過此坑：候選由小到大排列時每組都挑到最小
        間隔，正是 PO 要避免的密集行程。
        """
        t = self._track(outstations=["NRT"], samples_per_month=1,
                        lead_strategy="auto", trail_strategy="auto")
        itins, _ = svc.expand_track(t)
        self.assertGreaterEqual(itins[0]["lead"], 60)
        self.assertGreaterEqual(itins[0]["trail"], 14)

    def test_auto_does_not_pick_nearest_when_it_would_qualify(self):
        """反向驗證（FR-008）：最小候選「未被排除」時也不該被選中。

        這是最容易寫錯而測試又抓不到的一項——若測試只檢查「結果有避開
        排除月份」，把候選由小到大排列的實作會照樣通過，但每組都會挑到
        緊接主行程的間隔，正是 PO 要避免的密集行程。所以這裡不檢查排除
        月份，而是直接檢查「沒有挑到候選清單中的最小值」。
        """
        t = self._track(outstations=["NRT"], samples_per_month=1,
                        lead_strategy="auto", trail_strategy="auto")
        itins, _ = svc.expand_track(t)
        self.assertTrue(itins)
        for i in itins:
            self.assertNotEqual(i["lead"], min(svc.AUTO_LEAD_CANDIDATES))
            self.assertNotEqual(i["trail"], min(svc.AUTO_TRAIL_CANDIDATES))

    def test_candidate_lists_are_descending(self):
        """候選順序即偏好順序，必須由大到小（CON-14）。"""
        for cands in (svc.AUTO_LEAD_CANDIDATES, svc.AUTO_TRAIL_CANDIDATES):
            self.assertEqual(cands, sorted(cands, reverse=True))

    def test_fixed_strategies_map_to_exact_days(self):
        """非 auto 策略是固定值，不經挑選——m3 必定是 90 天。"""
        for strategy, days in (("none", 1), ("m1", 30), ("m3", 90), ("m5", 150)):
            t = self._track(outstations=["NRT"], samples_per_month=1,
                            lead_strategy=strategy, trail_strategy=strategy)
            itins, _ = svc.expand_track(t)
            self.assertEqual(itins[0]["lead"], days, "lead 策略 %s" % strategy)
            self.assertEqual(itins[0]["trail"], days, "trail 策略 %s" % strategy)

    def test_northern_summer_exclusion_on_all_three_segments(self):
        t = self._track(lead_strategy="auto", trail_strategy="auto",
                        exclude_months_trip=[6, 7, 8],
                        exclude_months_lead=[6, 7, 8],
                        exclude_months_trail=[6, 7, 8])
        self._assert_no_segment_in(t, [6, 7, 8])

    def test_southern_summer_exclusion_on_all_three_segments(self):
        """南半球旺季是 12–2 月，與北半球相反（CON-12）。"""
        t = self._track(lead_strategy="auto", trail_strategy="auto",
                        exclude_months_trip=[12, 1, 2],
                        exclude_months_lead=[12, 1, 2],
                        exclude_months_trail=[12, 1, 2])
        self._assert_no_segment_in(t, [12, 1, 2])

    def test_non_contiguous_exclusion_on_all_three_segments(self):
        """任意複選、可不連續（FR-009）。"""
        t = self._track(lead_strategy="auto", trail_strategy="auto",
                        exclude_months_trip=[2, 7, 12],
                        exclude_months_lead=[2, 7, 12],
                        exclude_months_trail=[2, 7, 12])
        self._assert_no_segment_in(t, [2, 7, 12])

    def _assert_no_segment_in(self, track, months):
        """主行程、第1段、第4段三者皆不得落在被排除的月份。"""
        itins, _ = svc.expand_track(track)
        self.assertTrue(itins, "應至少有一組可行組合")
        for i in itins:
            legs = i["legs"]
            for label, iso in (("第1段", legs[0]["date"]),
                               ("主行程去", legs[1]["date"]),
                               ("主行程回", legs[2]["date"]),
                               ("第4段", legs[3]["date"])):
                self.assertNotIn(int(iso[5:7]), months,
                                 "%s（%s）落在排除月份" % (label, iso))

    def test_skips_dates_with_no_feasible_offset(self):
        """所有候選間隔都無解時整組跳過並說明原因（FR-010）。"""
        t = self._track(lead_strategy="auto",
                        exclude_months_lead=list(range(1, 13)))
        itins, skipped = svc.expand_track(t)
        self.assertEqual(itins, [])
        self.assertTrue(skipped)
        self.assertEqual(skipped[0]["reason"], "no_feasible_offset")
        self.assertIn("第1段", skipped[0]["detail"])

    def test_trip_exclusion_removes_those_months(self):
        ws, we = _future_window(months_from_now=4, span=4)
        t = self._track(window_start=ws, window_end=we,
                        exclude_months_trip=[int(ws[5:7])])
        itins, _ = svc.expand_track(t)
        for i in itins:
            self.assertNotEqual(i["legs"][1]["date"][5:7], ws[5:7])


class PendingAndPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-pending-test-")
        self.store = FlightStore(self.tmp)
        self.ws, self.we = _future_window(span=1)
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=self.ws,
            window_end=self.we, trip_days=12, samples_per_month=2)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_pending_when_cache_empty(self):
        self.assertEqual(len(svc.pending_combinations(self.track, self.tmp)), 2)

    def test_cached_combination_is_excluded(self):
        """已查過的組合不再列入待查——這是「不儲存進度」的核心。"""
        itins, _ = svc.expand_track(self.track)
        key = fs._cache_key(itins[0]["legs"], 1, 1, fs.DEFAULT_CURRENCY,
                            "tw", "zh-TW")
        fs._write_cache(self.tmp, key, {"price": 37265, "airlines": ["星宇"]})
        pending = svc.pending_combinations(self.track, self.tmp)
        self.assertEqual(len(pending), 1)
        self.assertNotEqual(pending[0]["legs"][1]["date"],
                            itins[0]["legs"][1]["date"])

    def test_plan_reports_quota_and_counts(self):
        plan = svc.scan_plan(self.track, self.tmp, hourly_limit=20)
        self.assertEqual(plan["planned"], 2)
        self.assertEqual(plan["already_cached"], 0)
        self.assertEqual(plan["will_query"], 2)

    def test_plan_will_query_capped_by_quota(self):
        """配額不足時只計畫查得完的量，其餘留待下次（FR-012）。"""
        fs.record_browser_usage(self.tmp, 19)   # 上限 20，只剩 1
        plan = svc.scan_plan(self.track, self.tmp, hourly_limit=20)
        self.assertEqual(plan["pending"], 2)
        self.assertEqual(plan["will_query"], 1)
        self.assertEqual(plan["quota_left"], 1)


class RunScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-run-test-")
        self.store = FlightStore(self.tmp)
        self.ws, self.we = _future_window(span=1)
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=self.ws,
            window_end=self.we, trip_days=12, samples_per_month=2)
        self._orig = fs.scrape_itineraries

    def tearDown(self):
        fs.scrape_itineraries = self._orig
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_scrape(self, price=37265, status_key=None):
        """模擬查價層，**包含寫入查價快取的副作用**。

        真實的 `scrape_itineraries()` 成功時會逐筆寫快取，而 `run_scan()`
        以「重新推導 pending 是否為空」判斷本輪是否完成——假層若不模擬
        這個副作用，會讓 `mark_success` 永遠不觸發。這個依賴已在
        `run_scan()` 內註明。
        """
        outer = self

        def scrape(itineraries, **kw):
            rows = []
            for i in itineraries:
                row = dict(i)
                if status_key:
                    row["price"] = None
                    row["error"] = status_key
                else:
                    row["price"] = price
                    row["airlines"] = ["星宇航空"]
                    key = fs._cache_key(i["legs"], 1, 1, fs.DEFAULT_CURRENCY,
                                        "tw", "zh-TW")
                    fs._write_cache(outer.tmp, key,
                                    {"price": price, "airlines": ["星宇航空"]})
                rows.append(row)
            return {"results": rows, "blocked": False, "soft_blocked": False,
                    "stats": {}}
        return scrape

    def test_writes_results_and_marks_success(self):
        fs.scrape_itineraries = self._fake_scrape()
        out = svc.run_scan(self.track["id"], self.tmp)
        self.assertEqual(out["written"], 2)
        self.assertEqual(self.store.count_results(self.track["id"]), 2)
        self.assertIsNotNone(
            self.store.get_track(self.track["id"])["last_success_at"])

    def test_empty_result_recorded_as_no_fare_not_failure(self):
        """FR-023：查無票價與查詢失敗必須分開。"""
        fs.scrape_itineraries = self._fake_scrape(status_key="empty")
        svc.run_scan(self.track["id"], self.tmp)
        statuses = set(r["status"]
                       for r in self.store.list_results(self.track["id"]))
        self.assertEqual(statuses, {"no_fare"})

    def test_timeout_recorded_as_failed(self):
        fs.scrape_itineraries = self._fake_scrape(status_key="timeout")
        svc.run_scan(self.track["id"], self.tmp)
        statuses = set(r["status"]
                       for r in self.store.list_results(self.track["id"]))
        self.assertEqual(statuses, {"failed"})

    def test_rescan_is_idempotent_on_same_combination(self):
        fs.scrape_itineraries = self._fake_scrape(price=37265)
        svc.run_scan(self.track["id"], self.tmp)
        fs.scrape_itineraries = self._fake_scrape(price=35000)
        svc.run_scan(self.track["id"], self.tmp)
        results = self.store.list_results(self.track["id"])
        self.assertEqual(len(results), 2)   # 仍是 2 組，不是 4 筆

    def test_soft_block_keeps_completed_results_and_reports(self):
        """軟阻擋（連續逾時）時：已完成的結果必須保留，並如實回報。

        外部服務的阻擋常以連續逾時呈現而非明確錯誤頁。若把這種情況當成
        整批失敗而丟棄已完成的部分，使用者每次被擋都得從頭重來。
        """
        def scrape(itineraries, **kw):
            rows = []
            for idx, i in enumerate(itineraries):
                row = dict(i)
                if idx == 0:                      # 第一筆成功並寫快取
                    row["price"] = 37265
                    row["airlines"] = ["星宇航空"]
                    key = fs._cache_key(i["legs"], 1, 1, fs.DEFAULT_CURRENCY,
                                        "tw", "zh-TW")
                    fs._write_cache(self.tmp, key, {"price": 37265,
                                                    "airlines": ["星宇航空"]})
                else:                             # 其餘逾時，判定為軟阻擋
                    row["price"] = None
                    row["error"] = "timeout"
                rows.append(row)
            return {"results": rows, "blocked": True, "soft_blocked": True,
                    "stats": {}}

        fs.scrape_itineraries = scrape
        out = svc.run_scan(self.track["id"], self.tmp)
        self.assertTrue(out["blocked"])
        self.assertTrue(out["soft_blocked"])
        results = self.store.list_results(self.track["id"])
        self.assertEqual(len([r for r in results if r["status"] == "ok"]), 1)

    def test_partial_scan_does_not_mark_success(self):
        """部分完成不算成功一輪——否則資料過期判定會被一直往後推，
        讓過期的價格看起來永遠是新的。"""
        def scrape(itineraries, **kw):
            rows = []
            for i in itineraries:                 # 全部逾時，不寫任何快取
                row = dict(i)
                row["price"] = None
                row["error"] = "timeout"
                rows.append(row)
            return {"results": rows, "blocked": True, "soft_blocked": True,
                    "stats": {}}

        fs.scrape_itineraries = scrape
        svc.run_scan(self.track["id"], self.tmp)
        self.assertIsNone(
            self.store.get_track(self.track["id"])["last_success_at"])

    def test_connector_estimate_written_when_quota_allows(self):
        """接駁估價以外站為單位寫入，不逐組合查詢（FR-020）。"""
        fs.scrape_itineraries = self._fake_scrape()
        orig = fs.estimate_connectors_browser
        fs.estimate_connectors_browser = lambda outs, date, **kw: {
            o: 6800 for o in outs}
        try:
            svc.run_scan(self.track["id"], self.tmp)
        finally:
            fs.estimate_connectors_browser = orig
        results = self.store.list_results(self.track["id"])
        self.assertTrue(results)
        self.assertTrue(all(r["connector_price"] == 6800 for r in results))

    def test_connector_estimate_skipped_when_quota_exhausted(self):
        """配額用盡時跳過接駁估價——它是輔助資訊，不該排擠四段票查詢。"""
        fs.scrape_itineraries = self._fake_scrape()
        called = []
        orig = fs.estimate_connectors_browser
        fs.estimate_connectors_browser = lambda outs, date, **kw: (
            called.append(1) or {o: 6800 for o in outs})
        try:
            fs.record_browser_usage(self.tmp, fs.HOURLY_BROWSER_LIMIT)
            svc.run_scan(self.track["id"], self.tmp)
        finally:
            fs.estimate_connectors_browser = orig
        self.assertEqual(called, [])

    def test_connector_failure_does_not_break_main_results(self):
        """接駁估價失敗不影響主結果——它只是輔助資訊。"""
        fs.scrape_itineraries = self._fake_scrape()
        orig = fs.estimate_connectors_browser

        def boom(*a, **kw):
            raise RuntimeError("單程頁面解析失敗")
        fs.estimate_connectors_browser = boom
        try:
            out = svc.run_scan(self.track["id"], self.tmp)
        finally:
            fs.estimate_connectors_browser = orig
        self.assertEqual(out["written"], 2)
        self.assertEqual(self.store.count_results(self.track["id"]), 2)

    def test_missing_track_reports_error(self):
        out = svc.run_scan(9999, self.tmp)
        self.assertEqual(out["error"], "track_not_found")


class DeriveStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-state-test-")
        self.store = FlightStore(self.tmp)
        self.ws, self.we = _future_window(span=1)
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=self.ws,
            window_end=self.we, trip_days=12, samples_per_month=1)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cache_all(self):
        itins, _ = svc.expand_track(self.track)
        for i in itins:
            k = fs._cache_key(i["legs"], 1, 1, fs.DEFAULT_CURRENCY, "tw", "zh-TW")
            fs._write_cache(self.tmp, k, {"price": 37265, "airlines": []})

    def test_idle_when_nothing_done(self):
        self.assertEqual(svc.derive_state(self.track, self.tmp), "idle")

    def test_scanning_flag_wins(self):
        self.assertEqual(
            svc.derive_state(self.track, self.tmp, scanning=True), "scanning")

    def test_queued_when_quota_exhausted(self):
        fs.record_browser_usage(self.tmp, 20)
        self.assertEqual(svc.derive_state(self.track, self.tmp,
                                          hourly_limit=20), "queued")

    def test_complete_when_all_cached_and_results_exist(self):
        self._cache_all()
        self.store.upsert_result(self.track["id"], "NRT", "2027-01-01",
                                 "2027-01-10", "2027-01-22", "2027-01-23",
                                 1, 1, price=37265)
        t = self.store.get_track(self.track["id"])
        self.assertEqual(svc.derive_state(t, self.tmp), "complete")

    def test_stale_when_last_success_too_old(self):
        """資料過期需要儲存的資訊——無法從快取反推（research.md §7）。"""
        old = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
        self.store.mark_success(self.track["id"], old)
        self._cache_all()
        t = self.store.get_track(self.track["id"])
        self.assertEqual(svc.derive_state(t, self.tmp), "stale")


if __name__ == "__main__":
    unittest.main()
