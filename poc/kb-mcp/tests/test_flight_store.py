"""`flight_store.py` 測試：schema、CRUD、唯一鍵覆寫、驗證規則。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight_store*"

測試範圍刻意聚焦「已知會出錯的地方」而非覆蓋率：建構子副作用與唯一鍵
覆寫都是專案內實際發生過事故的類型（見 flight_store.py docstring）。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from flight_store import FlightStore  # noqa: E402


def _base_track(store, **kw):
    args = dict(destination="PRG", outstations=["NRT", "OKA"],
                window_start="2027-04", window_end="2027-06",
                trip_days_min=12, trip_days_max=12)
    args.update(kw)
    return store.create_track(**args)


class SchemaTest(unittest.TestCase):
    """建表：兩張表存在，且 __init__ 沒有任何寫入副作用。

    2026-08-22 事故：kb_store.py 在建構子內自動寫入種子資料，任何建立
    store 的呼叫端都會觸發，正式資料庫被污染兩次。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-store-test-")
        self.store = FlightStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tables_created(self):
        rows = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = set(r["name"] for r in rows)
        self.assertIn("flight_track", names)
        self.assertIn("flight_scan_result", names)

    def test_init_writes_no_rows(self):
        self.assertEqual(self.store.list_tracks(), [])
        n = self.store.conn.execute(
            "SELECT COUNT(*) AS n FROM flight_scan_result").fetchone()["n"]
        self.assertEqual(n, 0)

    def test_uses_own_database_file(self):
        """獨立 db，不與投資／相簿資料共用。"""
        self.assertTrue(self.store.db_path.endswith("flights.db"))
        self.assertTrue(os.path.exists(self.store.db_path))

    def test_reopen_is_idempotent(self):
        _base_track(self.store)
        again = FlightStore(self.tmp)
        try:
            self.assertEqual(len(again.list_tracks()), 1)
        finally:
            again.close()


class TrackCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-track-test-")
        self.store = FlightStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_get_roundtrip(self):
        t = _base_track(self.store, lead_strategy="m5", trail_strategy="m3",
                        exclude_months_trip=[6, 7, 8],
                        exclude_months_lead=[6, 7, 8],
                        exclude_months_trail=[12, 1, 2],
                        target_price=38000)
        got = self.store.get_track(t["id"])
        self.assertEqual(got["destination"], "PRG")
        self.assertEqual(got["outstations"], ["NRT", "OKA"])
        self.assertEqual(got["lead_strategy"], "m5")
        self.assertEqual(got["exclude_months"]["trip"], [6, 7, 8])
        self.assertEqual(got["exclude_months"]["trail"], [12, 1, 2])
        self.assertEqual(got["target_price"], 38000)

    def test_three_exclusion_groups_are_independent(self):
        """主行程／第1段／第4段各自一組排除月份（FR-009）。"""
        t = _base_track(self.store, exclude_months_trip=[6],
                        exclude_months_lead=[7], exclude_months_trail=[8])
        got = self.store.get_track(t["id"])
        self.assertEqual(got["exclude_months"],
                         {"trip": [6], "lead": [7], "trail": [8]})

    def test_airport_codes_upcased(self):
        t = _base_track(self.store, destination="prg", outstations=["nrt"])
        got = self.store.get_track(t["id"])
        self.assertEqual(got["destination"], "PRG")
        self.assertEqual(got["outstations"], ["NRT"])

    def test_auto_generated_name_when_blank(self):
        t = _base_track(self.store, name="   ")
        self.assertIn("PRG", t["name"])
        self.assertIn("2027-04", t["name"])

    def test_delete_removes_track_and_its_results(self):
        t = _base_track(self.store)
        self.store.upsert_result(t["id"], "NRT", "2026-11-02", "2027-04-01",
                                 "2027-04-13", "2027-04-14", 150, 1,
                                 price=37265)
        self.assertEqual(self.store.count_results(t["id"]), 1)
        self.assertTrue(self.store.delete_track(t["id"]))
        self.assertIsNone(self.store.get_track(t["id"]))
        self.assertEqual(self.store.count_results(t["id"]), 0)

    def test_delete_missing_returns_false(self):
        self.assertFalse(self.store.delete_track(9999))

    def test_mark_success_records_timestamp(self):
        t = _base_track(self.store)
        self.assertIsNone(t["last_success_at"])
        self.store.mark_success(t["id"], "2026-09-23T10:00:00")
        self.assertEqual(self.store.get_track(t["id"])["last_success_at"],
                         "2026-09-23T10:00:00")


class TrackingFieldsTest(unittest.TestCase):
    """006 新增的排程與通知欄位。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-tracking-test-")
        self.store = FlightStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_frequency_defaults_to_weekly(self):
        """預設每週一次（PO 於 Q-017 決定）。"""
        t = _base_track(self.store)
        self.assertEqual(t["scan_frequency_days"], 7)

    def test_frequency_can_be_set(self):
        t = _base_track(self.store, scan_frequency_days=30)
        self.assertEqual(self.store.get_track(t["id"])["scan_frequency_days"], 30)

    def test_rejects_non_positive_frequency(self):
        for bad in (0, -7):
            with self.assertRaises(ValueError):
                _base_track(self.store, scan_frequency_days=bad)

    def test_notify_fields_start_empty(self):
        t = _base_track(self.store)
        self.assertEqual(t["notify"], {"last_notified_at": None,
                                       "last_notified_price": None,
                                       "last_notify_failed": False})

    def test_update_frequency(self):
        t = _base_track(self.store)
        updated = self.store.update_track_frequency(t["id"], 14)
        self.assertEqual(updated["scan_frequency_days"], 14)

    def test_update_frequency_rejects_invalid(self):
        t = _base_track(self.store)
        with self.assertRaises(ValueError):
            self.store.update_track_frequency(t["id"], 0)

    def test_update_frequency_missing_track_returns_none(self):
        self.assertIsNone(self.store.update_track_frequency(9999, 14))

    def test_update_target_price(self):
        t = _base_track(self.store, target_price=38000)
        updated = self.store.update_target_price(t["id"], 40000)
        self.assertEqual(updated["target_price"], 40000)

    def test_update_target_price_to_none_clears_it(self):
        """2026-09-24 新增：清空目標價（等同取消通知），不是拒絕，是合法操作。"""
        t = _base_track(self.store, target_price=38000)
        updated = self.store.update_target_price(t["id"], None)
        self.assertIsNone(updated["target_price"])

    def test_update_target_price_rejects_negative(self):
        t = _base_track(self.store)
        with self.assertRaises(ValueError):
            self.store.update_target_price(t["id"], -100)

    def test_update_target_price_missing_track_returns_none(self):
        self.assertIsNone(self.store.update_target_price(9999, 40000))

    def test_update_target_price_does_not_affect_frequency(self):
        """改目標價不該動到其他欄位（跟 update_track_frequency 對稱）。"""
        t = _base_track(self.store, scan_frequency_days=14)
        updated = self.store.update_target_price(t["id"], 40000)
        self.assertEqual(updated["scan_frequency_days"], 14)

    def test_update_trip_days_range(self):
        """007：id=9 遷移機制的底層方法。"""
        t = _base_track(self.store, trip_days_min=12, trip_days_max=12)
        updated = self.store.update_trip_days_range(t["id"], 10, 14)
        self.assertEqual(updated["trip_days_min"], 10)
        self.assertEqual(updated["trip_days_max"], 14)

    def test_update_trip_days_range_rejects_max_below_min(self):
        t = _base_track(self.store)
        with self.assertRaises(ValueError):
            self.store.update_trip_days_range(t["id"], 14, 10)

    def test_update_trip_days_range_rejects_non_positive(self):
        t = _base_track(self.store)
        with self.assertRaises(ValueError):
            self.store.update_trip_days_range(t["id"], 0, 10)

    def test_update_trip_days_range_missing_track_returns_none(self):
        self.assertIsNone(self.store.update_trip_days_range(9999, 10, 14))

    def test_update_trip_days_range_preserves_other_fields(self):
        """遷移不得變動目標價、重掃頻率等非天數欄位（spec.md US2 驗收情境 1）。"""
        t = _base_track(self.store, target_price=40000,
                        scan_frequency_days=7)
        self.store.record_notification(t["id"], 37265, ok=True,
                                       when="2026-09-23T10:00:00")
        updated = self.store.update_trip_days_range(t["id"], 10, 14)
        self.assertEqual(updated["target_price"], 40000)
        self.assertEqual(updated["scan_frequency_days"], 7)
        self.assertEqual(updated["notify"]["last_notified_price"], 37265)

    def test_record_notification_success(self):
        t = _base_track(self.store)
        self.store.record_notification(t["id"], 37265, ok=True,
                                       when="2026-09-23T10:00:00")
        n = self.store.get_track(t["id"])["notify"]
        self.assertEqual(n["last_notified_price"], 37265)
        self.assertEqual(n["last_notified_at"], "2026-09-23T10:00:00")
        self.assertFalse(n["last_notify_failed"])

    def test_record_notification_failure_still_stores_price(self):
        """通知失敗也要記下價格。

        否則下一輪因 last_notified_price 仍為空而重複嘗試，使用者在通知
        管道恢復後會收到一串補發。
        """
        t = _base_track(self.store)
        self.store.record_notification(t["id"], 37265, ok=False)
        n = self.store.get_track(t["id"])["notify"]
        self.assertEqual(n["last_notified_price"], 37265)
        self.assertTrue(n["last_notify_failed"])

    def test_existing_database_gets_new_columns(self):
        """既有資料庫（005 建立、無新欄位）重新開啟後應完成升級。"""
        import sqlite3 as _sq
        db = os.path.join(self.tmp, "legacy")
        os.makedirs(db, exist_ok=True)
        conn = _sq.connect(os.path.join(db, "flights.db"))
        conn.execute("""CREATE TABLE flight_track (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            destination TEXT NOT NULL, hub TEXT NOT NULL,
            outstations TEXT NOT NULL, window_start TEXT NOT NULL,
            window_end TEXT NOT NULL, trip_days INTEGER NOT NULL,
            lead_strategy TEXT NOT NULL, trail_strategy TEXT NOT NULL,
            exclude_months_trip TEXT NOT NULL DEFAULT '',
            exclude_months_lead TEXT NOT NULL DEFAULT '',
            exclude_months_trail TEXT NOT NULL DEFAULT '',
            target_price INTEGER, samples_per_month INTEGER NOT NULL DEFAULT 2,
            created_at TEXT NOT NULL, last_success_at TEXT)""")
        conn.execute(
            "INSERT INTO flight_track (name, destination, hub, outstations,"
            " window_start, window_end, trip_days, lead_strategy,"
            " trail_strategy, created_at) VALUES"
            " ('舊資料','PRG','TPE','NRT','2027-04','2027-05',12,'none','none','x')")
        conn.commit(); conn.close()

        store = FlightStore(db)
        try:
            t = store.list_tracks()[0]
            self.assertEqual(t["name"], "舊資料")
            self.assertEqual(t["scan_frequency_days"], 7)   # 預設值已套用
            self.assertIsNone(t["notify"]["last_notified_at"])
        finally:
            store.close()


class TrackValidationTest(unittest.TestCase):
    """FR-025：無效輸入必須被拒絕並說明原因。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-valid-test-")
        self.store = FlightStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rejects_empty_outstations(self):
        with self.assertRaises(ValueError) as ctx:
            _base_track(self.store, outstations=[])
        self.assertIn("outstations", str(ctx.exception))

    def test_rejects_non_positive_trip_days(self):
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                _base_track(self.store, trip_days_min=bad, trip_days_max=bad)

    def test_rejects_trip_days_max_below_min(self):
        """007：上限不得小於下限。"""
        with self.assertRaises(ValueError) as ctx:
            _base_track(self.store, trip_days_min=14, trip_days_max=10)
        self.assertIn("trip_days_max", str(ctx.exception))

    def test_accepts_trip_days_min_equal_max(self):
        """007：下限等於上限是合法輸入，等同舊版單一天數（spec.md Edge Cases）。"""
        t = _base_track(self.store, trip_days_min=12, trip_days_max=12)
        self.assertEqual(t["trip_days_min"], 12)
        self.assertEqual(t["trip_days_max"], 12)

    def test_accepts_trip_days_range(self):
        t = _base_track(self.store, trip_days_min=10, trip_days_max=14)
        self.assertEqual(t["trip_days_min"], 10)
        self.assertEqual(t["trip_days_max"], 14)

    def test_rejects_non_integer_trip_days(self):
        with self.assertRaises(ValueError):
            _base_track(self.store, trip_days_min="十天", trip_days_max=14)

    def test_rejects_months_out_of_range(self):
        for bad in ([0], [13], [6, 13]):
            with self.assertRaises(ValueError) as ctx:
                _base_track(self.store, exclude_months_trip=bad)
            self.assertIn("1-12", str(ctx.exception))

    def test_accepts_non_contiguous_months(self):
        """1-12 任意複選，可不連續（FR-009）。"""
        t = _base_track(self.store, exclude_months_trip=[2, 7, 12])
        self.assertEqual(self.store.get_track(t["id"])["exclude_months"]["trip"],
                         [2, 7, 12])

    def test_accepts_southern_hemisphere_months(self):
        """南半球旺季 12,1,2 與北半球相反，不得被視為無效（CON-12）。"""
        t = _base_track(self.store, exclude_months_trip=[12, 1, 2])
        self.assertEqual(self.store.get_track(t["id"])["exclude_months"]["trip"],
                         [12, 1, 2])

    def test_rejects_window_end_before_start(self):
        with self.assertRaises(ValueError) as ctx:
            _base_track(self.store, window_start="2027-06", window_end="2027-04")
        self.assertIn("window_end", str(ctx.exception))

    def test_rejects_bad_airport_code(self):
        for bad in ("PR", "PRAG", "12X", ""):
            with self.assertRaises(ValueError):
                _base_track(self.store, destination=bad)

    def test_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError) as ctx:
            _base_track(self.store, lead_strategy="約三個月")
        self.assertIn("lead_strategy", str(ctx.exception))

    def test_rejects_bad_year_month(self):
        with self.assertRaises(ValueError):
            _base_track(self.store, window_start="2027/04")


class ResultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-result-test-")
        self.store = FlightStore(self.tmp)
        self.track = _base_track(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _r(self, **kw):
        args = dict(track_id=self.track["id"], outstation="NRT",
                    leg1_date="2026-11-02", outbound_date="2027-04-01",
                    return_date="2027-04-13", leg4_date="2027-04-14",
                    lead_days=150, trail_days=1, price=37265)
        args.update(kw)
        return self.store.upsert_result(**args)

    def test_upsert_overwrites_same_combination(self):
        """重掃時同一組合覆寫而非累積（data-model.md 唯一性）。"""
        self._r(price=37265)
        self._r(price=35000, airline="星宇航空")
        results = self.store.list_results(self.track["id"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["price"], 35000)
        self.assertEqual(results[0]["airline"], "星宇航空")

    def test_different_combination_creates_new_row(self):
        self._r()
        self._r(outstation="OKA", price=36917)
        self.assertEqual(self.store.count_results(self.track["id"]), 2)

    def test_sorted_by_price_with_failures_last(self):
        self._r(price=37265)
        self._r(outstation="OKA", price=36917)
        self._r(outstation="KIX", status="no_fare", price=None)
        self._r(outstation="FUK", status="failed", price=None)
        results = self.store.list_results(self.track["id"])
        self.assertEqual([r["price"] for r in results[:2]], [36917, 37265])
        self.assertEqual(set(r["status"] for r in results[2:]),
                         {"no_fare", "failed"})

    def test_no_fare_and_failed_are_distinct(self):
        """FR-023：查無票價與查詢失敗必須可區分。"""
        self._r(status="no_fare", price=None)
        self.assertEqual(
            self.store.list_results(self.track["id"])[0]["status"], "no_fare")

    def test_ok_requires_price(self):
        with self.assertRaises(ValueError):
            self._r(status="ok", price=None)

    def test_non_ok_must_not_carry_price(self):
        with self.assertRaises(ValueError):
            self._r(status="failed", price=1000)

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self._r(status="pending")

    def test_lowest_result_ignores_non_ok(self):
        self._r(outstation="KIX", status="failed", price=None)
        self._r(outstation="OKA", price=36917)
        self._r(price=37265)
        low = self.store.lowest_result(self.track["id"])
        self.assertEqual(low["price"], 36917)
        self.assertEqual(low["outstation"], "OKA")

    def test_lowest_result_none_when_no_successful_row(self):
        self._r(status="failed", price=None)
        self.assertIsNone(self.store.lowest_result(self.track["id"]))

    def test_connector_price_is_stored_separately(self):
        """接駁估價與四段票價分開存——達標判定只看四段票價（Q-016）。"""
        self._r(price=37265, connector_price=6800)
        r = self.store.list_results(self.track["id"])[0]
        self.assertEqual(r["price"], 37265)
        self.assertEqual(r["connector_price"], 6800)


def _base_roundtrip(store, **kw):
    args = dict(destinations=["AOJ", "CTS"], window_start="2027-01",
                window_end="2027-02", trip_days_min=3, trip_days_max=7)
    args.update(kw)
    return store.create_roundtrip_track(**args)


class RoundtripTrackTest(unittest.TestCase):
    """008：單純來回追蹤條件——schema、CRUD、驗證規則。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-roundtrip-test-")
        self.store = FlightStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_table_created(self):
        rows = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = set(r["name"] for r in rows)
        self.assertIn("roundtrip_track", names)
        self.assertIn("roundtrip_scan_result", names)

    def test_create_and_get_roundtrip(self):
        t = _base_roundtrip(self.store, target_price=30000)
        got = self.store.get_roundtrip_track(t["id"])
        self.assertEqual(got["destinations"], ["AOJ", "CTS"])
        self.assertEqual(got["trip_days_min"], 3)
        self.assertEqual(got["trip_days_max"], 7)
        self.assertEqual(got["target_price"], 30000)
        self.assertEqual(got["track_type"], "roundtrip")
        self.assertIsNone(got["preferred_transit"])

    def test_single_destination_is_valid(self):
        """spec.md Edge Cases：只填 1 個候選目的地仍合法。"""
        t = _base_roundtrip(self.store, destinations=["AOJ"])
        self.assertEqual(t["destinations"], ["AOJ"])

    def test_rejects_empty_destinations(self):
        with self.assertRaises(ValueError) as ctx:
            _base_roundtrip(self.store, destinations=[])
        self.assertIn("destinations", str(ctx.exception))

    def test_rejects_bad_destination_code(self):
        """候選清單中每一個都要驗證，不能只驗第一個（spec.md Edge Cases）。"""
        with self.assertRaises(ValueError):
            _base_roundtrip(self.store, destinations=["AOJ", "XX"])

    def test_preferred_transit_optional(self):
        t = _base_roundtrip(self.store, preferred_transit="NRT")
        self.assertEqual(t["preferred_transit"], "NRT")

    def test_preferred_transit_validated_when_provided(self):
        with self.assertRaises(ValueError):
            _base_roundtrip(self.store, preferred_transit="XX")

    def test_rejects_trip_days_max_below_min(self):
        with self.assertRaises(ValueError):
            _base_roundtrip(self.store, trip_days_min=7, trip_days_max=3)

    def test_delete_removes_track_and_results(self):
        t = _base_roundtrip(self.store)
        self.store.upsert_roundtrip_result(
            t["id"], "AOJ", "2027-01-15", "2027-01-20", price=23773)
        self.assertEqual(self.store.count_roundtrip_results(t["id"]), 1)
        self.assertTrue(self.store.delete_roundtrip_track(t["id"]))
        self.assertIsNone(self.store.get_roundtrip_track(t["id"]))
        self.assertEqual(self.store.count_roundtrip_results(t["id"]), 0)

    def test_mark_roundtrip_success_records_timestamp(self):
        t = _base_roundtrip(self.store)
        self.assertIsNone(t["last_success_at"])
        self.store.mark_roundtrip_success(t["id"], "2026-09-24T10:00:00")
        self.assertEqual(
            self.store.get_roundtrip_track(t["id"])["last_success_at"],
            "2026-09-24T10:00:00")

    def test_record_roundtrip_notification(self):
        t = _base_roundtrip(self.store)
        self.store.record_roundtrip_notification(
            t["id"], 23773, ok=True, when="2026-09-24T10:00:00")
        n = self.store.get_roundtrip_track(t["id"])["notify"]
        self.assertEqual(n["last_notified_price"], 23773)
        self.assertFalse(n["last_notify_failed"])

    def test_list_roundtrip_tracks_does_not_include_four_segment(self):
        """兩張表各自獨立列表，不互相污染。"""
        _base_roundtrip(self.store)
        self.store.create_track(
            destination="PRG", outstations=["NRT"], window_start="2027-04",
            window_end="2027-04", trip_days_min=12, trip_days_max=12)
        self.assertEqual(len(self.store.list_roundtrip_tracks()), 1)
        self.assertEqual(len(self.store.list_tracks()), 1)


class RoundtripResultTest(unittest.TestCase):
    """008：單純來回掃描結果——跨目的地最低價、狀態區分。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-roundtrip-result-test-")
        self.store = FlightStore(self.tmp)
        self.track = _base_roundtrip(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _r(self, destination="AOJ", outbound_date="2027-01-15",
          return_date="2027-01-20", **kw):
        args = dict(track_id=self.track["id"], destination=destination,
                    outbound_date=outbound_date, return_date=return_date,
                    price=23773)
        args.update(kw)
        return self.store.upsert_roundtrip_result(**args)

    def test_upsert_and_list(self):
        self._r()
        rows = self.store.list_roundtrip_results(self.track["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["destination"], "AOJ")
        self.assertEqual(rows[0]["price"], 23773)

    def test_same_combo_overwrites_not_accumulates(self):
        self._r(price=23773)
        self._r(price=21000)
        rows = self.store.list_roundtrip_results(self.track["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 21000)

    def test_lowest_result_across_all_destinations(self):
        """跨候選目的地判定最低價，不是固定某一個（spec.md FR-09）。"""
        self._r(destination="AOJ", price=46872)
        self._r(destination="CTS", price=23773,
               outbound_date="2027-01-10", return_date="2027-01-15")
        low = self.store.roundtrip_lowest_result(self.track["id"])
        self.assertEqual(low["price"], 23773)
        self.assertEqual(low["destination"], "CTS")

    def test_lowest_result_ignores_non_ok(self):
        self._r(destination="AOJ", status="failed", price=None)
        self._r(destination="CTS", price=23773,
               outbound_date="2027-01-10", return_date="2027-01-15")
        low = self.store.roundtrip_lowest_result(self.track["id"])
        self.assertEqual(low["price"], 23773)

    def test_lowest_result_none_when_no_successful_row(self):
        self._r(status="failed", price=None)
        self.assertIsNone(self.store.roundtrip_lowest_result(self.track["id"]))

    def test_no_fare_and_failed_must_not_carry_price(self):
        with self.assertRaises(ValueError):
            self._r(status="failed", price=1000)


if __name__ == "__main__":
    unittest.main()
