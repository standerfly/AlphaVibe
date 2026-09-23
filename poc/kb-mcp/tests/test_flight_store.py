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
                window_start="2027-04", window_end="2027-06", trip_days=12)
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
                _base_track(self.store, trip_days=bad)

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


if __name__ == "__main__":
    unittest.main()
