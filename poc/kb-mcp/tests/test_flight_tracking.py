"""排程選取、達標通知、過期防護的測試（006）。

全部離線——查價與通知都以替身替換，不連外部服務、不發真實訊息、
不消耗配額。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight_tracking*"
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import flight_search as fs  # noqa: E402
import flight_scan_service as svc  # noqa: E402
import flight_tracking_job as job  # noqa: E402
from flight_store import FlightStore  # noqa: E402


def _window():
    base = datetime.date.today().replace(day=1)
    for _ in range(6):
        base = (base + datetime.timedelta(days=32)).replace(day=1)
    return base.strftime("%Y-%m")


class ScheduleSelectionTest(unittest.TestCase):
    """今天該掃哪些條件（FR-002、FR-003）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-sched-test-")
        self.store = FlightStore(self.tmp)
        w = _window()
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=w,
            window_end=w, trip_days=12)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _day_for(self, track, weeks_ago=None):
        """回傳一個「輪到這個條件」的日期。"""
        d = datetime.date.today()
        while d.weekday() != svc.scheduled_weekday(track):
            d += datetime.timedelta(days=1)
        return d

    def test_due_when_never_succeeded_and_today_is_its_day(self):
        day = self._day_for(self.track)
        self.assertTrue(svc.is_due(self.track, day))

    def test_not_due_on_other_weekdays(self):
        day = self._day_for(self.track) + datetime.timedelta(days=1)
        self.assertFalse(svc.is_due(self.track, day))

    def test_not_due_when_period_not_elapsed(self):
        """今天輪到，但距上次成功還沒滿一個週期。"""
        day = self._day_for(self.track)
        recent = (day - datetime.timedelta(days=3)).isoformat() + "T00:00:00"
        self.store.mark_success(self.track["id"], recent)
        t = self.store.get_track(self.track["id"])
        self.assertFalse(svc.is_due(t, day))

    def test_due_when_period_elapsed(self):
        day = self._day_for(self.track)
        old = (day - datetime.timedelta(days=8)).isoformat() + "T00:00:00"
        self.store.mark_success(self.track["id"], old)
        t = self.store.get_track(self.track["id"])
        self.assertTrue(svc.is_due(t, day))

    def test_monthly_frequency_not_due_after_one_week(self):
        """頻率是判定的一部分——每月一次的條件不該每週跑。"""
        w = _window()
        monthly = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=w,
            window_end=w, trip_days=12, scan_frequency_days=30)
        day = self._day_for(monthly)
        self.store.mark_success(monthly["id"],
                                (day - datetime.timedelta(days=10)).isoformat()
                                + "T00:00:00")
        t = self.store.get_track(monthly["id"])
        self.assertFalse(svc.is_due(t, day))

    def test_multiple_tracks_spread_across_days(self):
        """多個條件應分散到不同天，避免同日累積查詢量（FR-003）。"""
        w = _window()
        ids = [self.track["id"]]
        for _ in range(6):
            ids.append(self.store.create_track(
                destination="PRG", outstations=["NRT"], window_start=w,
                window_end=w, trip_days=12)["id"])
        days = [svc.scheduled_weekday({"id": i}) for i in ids]
        self.assertEqual(len(set(days)), 7, "7 個連號條件應落在 7 個不同天")

    def test_next_scan_date_lands_on_its_weekday(self):
        nxt = svc.next_scan_date(self.track)
        self.assertEqual(
            datetime.date.fromisoformat(nxt).weekday(),
            svc.scheduled_weekday(self.track))

    def test_next_scan_date_after_success_respects_frequency(self):
        today = datetime.date.today()
        self.store.mark_success(self.track["id"], today.isoformat() + "T00:00:00")
        t = self.store.get_track(self.track["id"])
        nxt = datetime.date.fromisoformat(svc.next_scan_date(t, today))
        self.assertGreaterEqual((nxt - today).days, 7)


class NotifyDecisionTest(unittest.TestCase):
    """達標判定與去重（FR-006、FR-007、FR-009、FR-010、FR-014）。"""

    def _track(self, target=38000, last=None, freq=7):
        return {"id": 1, "name": "測試", "destination": "PRG", "hub": "TPE",
                "target_price": target, "scan_frequency_days": freq,
                "notify": {"last_notified_price": last}}

    def test_notifies_when_below_target_first_time(self):
        self.assertTrue(svc.should_notify(self._track(), 37265))

    def test_no_notify_when_above_target(self):
        self.assertFalse(svc.should_notify(self._track(), 39000))

    def test_no_notify_without_target_price(self):
        self.assertFalse(svc.should_notify(self._track(target=None), 1000))

    def test_no_duplicate_at_same_price(self):
        self.assertFalse(svc.should_notify(self._track(last=37265), 37265))

    def test_notifies_again_when_cheaper(self):
        """比上次通知時更低就值得再看一眼（FR-009）。"""
        self.assertTrue(svc.should_notify(self._track(last=37265), 35000))

    def test_no_notify_when_price_rises_back(self):
        self.assertFalse(svc.should_notify(self._track(last=35000), 37265))

    def test_connector_price_does_not_affect_decision(self):
        """反向驗證 FR-007：四段票價達標即通知，即使加上接駁後超過目標。

        達標判定只看四段票價——接駁是估算值且會變動，納入會讓通知
        時定時不定（PO 於 Q-016 決定）。
        """
        # 四段票 37,500 ≤ 目標 38,000；接駁 6,000 使總成本 43,500 > 目標
        self.assertTrue(svc.should_notify(self._track(target=38000), 37500))

    def test_stale_state_blocks_notification(self):
        """過期資料不得觸發通知（FR-014）。"""
        self.assertFalse(
            svc.should_notify(self._track(), 37265, state="stale"))


class StatusNotifyDecisionTest(unittest.TestCase):
    """未達標的現況通知判定（PO 2026-09-24 新增：「若沒有達成，找最
    接近的組合」）。跟 NotifyDecisionTest 用同一套 _track() 慣例。
    """

    def _track(self, target=38000, freq=7):
        return {"id": 1, "name": "測試", "destination": "PRG", "hub": "TPE",
                "target_price": target, "scan_frequency_days": freq,
                "notify": {"last_notified_price": None}}

    def test_notifies_status_when_above_target(self):
        self.assertTrue(svc.should_notify_status(self._track(), 44320))

    def test_no_status_notify_when_target_met(self):
        """達標時走 should_notify() 的訊息，不該同時又發現況通知。"""
        self.assertFalse(svc.should_notify_status(self._track(), 37265))

    def test_no_status_notify_without_target_price(self):
        self.assertFalse(
            svc.should_notify_status(self._track(target=None), 44320))

    def test_no_status_notify_when_no_priced_result(self):
        self.assertFalse(svc.should_notify_status(self._track(), None))

    def test_stale_state_blocks_status_notification(self):
        """跟達標通知一樣，過期資料不得觸發現況通知（FR-014 同理）。"""
        self.assertFalse(
            svc.should_notify_status(self._track(), 44320, state="stale"))

    def test_no_dedup_unlike_should_notify(self):
        """刻意反向驗證：即使上一輪已經發過現況通知、價格完全沒變，
        這一輪仍要再發——PO 明知會員增加通知頻率仍選擇要（跟
        should_notify() 的「比上次更低才發」刻意不同）。
        """
        track = self._track()
        track["notify"] = {"last_notified_price": 44320}   # 假裝發過
        self.assertTrue(svc.should_notify_status(track, 44320))


class BuildStatusNotificationTest(unittest.TestCase):
    """現況通知的訊息內容。"""

    def _row(self):
        return {"outstation": "NRT", "leg1_date": "2027-01-16",
                "outbound_date": "2027-04-16", "return_date": "2027-04-28",
                "leg4_date": "2027-05-28", "price": 44320,
                "airline": "捷星日本航空"}

    def test_message_shows_gap_and_marks_unmet(self):
        track = {"name": "布拉格（成田出發）2027春", "destination": "PRG",
                 "hub": "TPE", "target_price": 40000}
        msg = svc.build_status_notification(track, self._row())
        self.assertIn("尚未達標", msg)
        self.assertIn("44,320", msg)
        self.assertIn("40,000", msg)
        self.assertIn("還差 NT$4,320", msg)
        self.assertIn("google.com/travel/flights", msg)
        # 現況通知不是「達標」，不該出現降價通知專屬的達標措辭
        self.assertNotIn("降到目標價以下", msg)


class TrackingJobTest(unittest.TestCase):
    """排程腳本的端到端行為（以替身取代查價與通知）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-job-test-")
        self.store = FlightStore(self.tmp)
        w = _window()
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=w,
            window_end=w, trip_days=12, samples_per_month=1,
            target_price=50000)
        self._orig_scrape = fs.scrape_itineraries
        self._orig_conn = fs.estimate_connectors_browser
        fs.estimate_connectors_browser = lambda outs, date, **kw: {}
        self.sent = []

    def tearDown(self):
        fs.scrape_itineraries = self._orig_scrape
        fs.estimate_connectors_browser = self._orig_conn
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scrape(self, price):
        def scrape(itineraries, **kw):
            rows = []
            for i in itineraries:
                row = dict(i)
                row["price"] = price
                row["airlines"] = ["星宇航空"]
                k = fs._cache_key(i["legs"], 1, 1, fs.DEFAULT_CURRENCY,
                                  "tw", "zh-TW")
                fs._write_cache(self.tmp, k, {"price": price,
                                              "airlines": ["星宇航空"]})
                rows.append(row)
            return {"results": rows, "blocked": False, "soft_blocked": False,
                    "stats": {}}
        return scrape

    def _notifier(self, ok=True):
        def send(text):
            self.sent.append(text)
            return (1, []) if ok else (0, ["Telegram 未設定"])
        return send

    def _its_day(self):
        d = datetime.date.today()
        while d.weekday() != svc.scheduled_weekday(self.track):
            d += datetime.timedelta(days=1)
        return d

    def test_dry_run_does_not_scan_or_notify(self):
        fs.scrape_itineraries = lambda *a, **k: self.fail("dry-run 不該查價")
        res = job.run(self.tmp, dry_run=True, today=self._its_day(),
                      notifier=self._notifier())
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0]["scanned"])
        self.assertEqual(self.sent, [])

    def test_scans_and_notifies_when_below_target(self):
        fs.scrape_itineraries = self._scrape(37265)
        res = job.run(self.tmp, today=self._its_day(),
                      notifier=self._notifier())
        self.assertTrue(res[0]["scanned"])
        self.assertTrue(res[0]["notified"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("37,265", self.sent[0])
        self.assertIn("google.com/travel/flights", self.sent[0])
        n = self.store.get_track(self.track["id"])["notify"]
        self.assertEqual(n["last_notified_price"], 37265)
        self.assertFalse(n["last_notify_failed"])

    def test_does_not_notify_twice_at_same_price(self):
        fs.scrape_itineraries = self._scrape(37265)
        day = self._its_day()
        job.run(self.tmp, today=day, notifier=self._notifier())
        # 第二輪：清掉快取讓它重查，但價格相同
        shutil.rmtree(os.path.join(self.tmp, "flight_cache"), ignore_errors=True)
        self.store.mark_success(self.track["id"],
                                (day - datetime.timedelta(days=8)).isoformat()
                                + "T00:00:00")
        job.run(self.tmp, today=day, notifier=self._notifier())
        self.assertEqual(len(self.sent), 1, "同價不該重複通知")

    def test_notify_failure_keeps_results_and_flags(self):
        """通知失敗不影響掃描結果（FR-011），並標記未送達（FR-019）。"""
        fs.scrape_itineraries = self._scrape(37265)
        res = job.run(self.tmp, today=self._its_day(),
                      notifier=self._notifier(ok=False))
        self.assertTrue(res[0]["scanned"])
        self.assertFalse(res[0]["notified"])
        self.assertTrue(self.store.count_results(self.track["id"]) > 0)
        n = self.store.get_track(self.track["id"])["notify"]
        self.assertTrue(n["last_notify_failed"])
        self.assertEqual(n["last_notified_price"], 37265)

    def test_no_notify_without_target_price(self):
        w = _window()
        t = self.store.create_track(
            destination="PRG", outstations=["OKA"], window_start=w,
            window_end=w, trip_days=12, samples_per_month=1)
        fs.scrape_itineraries = self._scrape(30000)
        d = datetime.date.today()
        while d.weekday() != svc.scheduled_weekday(t):
            d += datetime.timedelta(days=1)
        res = job.run(self.tmp, today=d, notifier=self._notifier())
        target_res = [r for r in res if r["id"] == t["id"]]
        self.assertTrue(target_res)
        self.assertFalse(target_res[0]["notified"])

    def test_skips_tracks_not_due_today(self):
        day = self._its_day() + datetime.timedelta(days=1)
        fs.scrape_itineraries = lambda *a, **k: self.fail("不該掃描")
        res = job.run(self.tmp, today=day, notifier=self._notifier())
        self.assertEqual(res, [])

    def test_sends_status_notification_when_above_target(self):
        """PO 2026-09-24 新增：未達標時發「現況」通知，告知最接近的組合。

        setUp 的 self.track 目標價 50,000；查到 55,000（高於目標），
        應該送出現況通知而非達標通知。
        """
        fs.scrape_itineraries = self._scrape(55000)
        res = job.run(self.tmp, today=self._its_day(),
                      notifier=self._notifier())
        self.assertTrue(res[0]["scanned"])
        self.assertFalse(res[0]["notified"], "未達標不該走達標通知分支")
        self.assertTrue(res[0].get("status_notified"),
                        "未達標應發送現況通知")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("尚未達標", self.sent[0])
        self.assertIn("55,000", self.sent[0])
        # 現況通知不寫進 last_notified_price／last_notified_at——那組
        # 欄位是「上次達標通知」的語意（FR-019），現況通知不應污染它
        n = self.store.get_track(self.track["id"])["notify"]
        self.assertIsNone(n["last_notified_price"])
        self.assertIsNone(n["last_notified_at"])

    def test_status_and_target_notifications_are_mutually_exclusive(self):
        """同一輪掃描只會發一種通知：達標時不該再多發一則現況通知。"""
        fs.scrape_itineraries = self._scrape(37265)   # 低於目標 50,000
        res = job.run(self.tmp, today=self._its_day(),
                      notifier=self._notifier())
        self.assertTrue(res[0]["notified"])
        self.assertFalse(res[0].get("status_notified"))
        self.assertEqual(len(self.sent), 1, "同一輪不該發兩則通知")

    def test_status_notification_sent_every_round_even_if_unchanged(self):
        """反向驗證：現況通知刻意不去重——即使兩輪價格完全相同，各發
        一次（跟達標通知的「比上次更低才發」刻意不同，見
        should_notify_status() 的 docstring）。
        """
        fs.scrape_itineraries = self._scrape(55000)
        day = self._its_day()
        job.run(self.tmp, today=day, notifier=self._notifier())
        shutil.rmtree(os.path.join(self.tmp, "flight_cache"), ignore_errors=True)
        self.store.mark_success(self.track["id"],
                                (day - datetime.timedelta(days=8)).isoformat()
                                + "T00:00:00")
        job.run(self.tmp, today=day, notifier=self._notifier())
        self.assertEqual(len(self.sent), 2, "未達標的現況通知每輪都該發")


class StaleProtectionTest(unittest.TestCase):
    """過期防護（FR-013、FR-014、FR-015）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-stale-test-")
        self.store = FlightStore(self.tmp)
        w = _window()
        self.track = self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start=w,
            window_end=w, trip_days=12, samples_per_month=1,
            target_price=50000)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cache_all(self, price=37265):
        itins, _ = svc.expand_track(self.store.get_track(self.track["id"]))
        for i in itins:
            k = fs._cache_key(i["legs"], 1, 1, fs.DEFAULT_CURRENCY, "tw", "zh-TW")
            fs._write_cache(self.tmp, k, {"price": price, "airlines": []})

    def test_stale_after_two_periods(self):
        self._cache_all()
        old = (datetime.datetime.now() - datetime.timedelta(days=15)).isoformat()
        self.store.mark_success(self.track["id"], old)
        t = self.store.get_track(self.track["id"])
        self.assertEqual(svc.derive_state(t, self.tmp), "stale")

    def test_monthly_track_not_stale_at_day_15(self):
        """反向驗證：005 原本把過期週期寫死 7 天，會讓每月頻率的條件
        在第 15 天被誤判為過期而停止通知（quickstart 坑 1）。"""
        self.store.update_track_frequency(self.track["id"], 30)
        self._cache_all()
        day15 = (datetime.datetime.now() - datetime.timedelta(days=15)).isoformat()
        self.store.mark_success(self.track["id"], day15)
        t = self.store.get_track(self.track["id"])
        self.assertNotEqual(svc.derive_state(t, self.tmp), "stale")

    def test_stale_clears_after_success(self):
        self._cache_all()
        self.store.mark_success(
            self.track["id"],
            (datetime.datetime.now() - datetime.timedelta(days=20)).isoformat())
        self.assertEqual(
            svc.derive_state(self.store.get_track(self.track["id"]), self.tmp),
            "stale")
        self.store.mark_success(self.track["id"])
        self.assertNotEqual(
            svc.derive_state(self.store.get_track(self.track["id"]), self.tmp),
            "stale")

    def test_partial_scan_does_not_refresh_success_time(self):
        """部分完成不得更新上次成功時間（FR-015）——否則過期判定會被
        一直往後推，讓過期價格看起來永遠是新的。"""
        orig = fs.scrape_itineraries
        try:
            def partial(itineraries, **kw):
                rows = []
                for i in itineraries:      # 全部失敗、不寫快取
                    row = dict(i); row["price"] = None; row["error"] = "timeout"
                    rows.append(row)
                return {"results": rows, "blocked": True, "soft_blocked": True,
                        "stats": {}}
            fs.scrape_itineraries = partial
            svc.run_scan(self.track["id"], self.tmp)
        finally:
            fs.scrape_itineraries = orig
        self.assertIsNone(
            self.store.get_track(self.track["id"])["last_success_at"])


if __name__ == "__main__":
    unittest.main()
