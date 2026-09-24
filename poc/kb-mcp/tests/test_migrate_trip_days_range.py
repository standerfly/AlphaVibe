"""`migrate_trip_days_range.py` 的整合測試（007-trip-day-range）。

腳本鎖定 `TRACK_ID = 9`（正式庫唯一需要遷移的既有條件，非通用遷移
工具），測試對獨立測試資料庫建立 8 筆佔位條件把 AUTOINCREMENT 推到
id=9，再建立「模擬 id=9」的真實條件驗證遷移行為——不直接碰正式庫。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_migrate*"
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import migrate_trip_days_range as migrate  # noqa: E402
from flight_store import FlightStore  # noqa: E402


class MigrateTripDaysRangeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flight-migrate-test-")
        self.store = FlightStore(self.tmp)
        # 推進 AUTOINCREMENT，讓下一筆真正建立的條件落在 id=9
        for _ in range(8):
            t = self.store.create_track(
                destination="PRG", outstations=["NRT"],
                window_start="2027-04", window_end="2027-04",
                trip_days_min=12, trip_days_max=12)
            self.store.delete_track(t["id"])

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, dry_run=False):
        argv = ["migrate_trip_days_range.py", "--data-dir", self.tmp]
        if dry_run:
            argv.append("--dry-run")
        old_argv = sys.argv
        sys.argv = argv
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = migrate.main()
        finally:
            sys.argv = old_argv
        return code, buf.getvalue()

    def test_id_placeholder_setup_lands_on_nine(self):
        """setUp 的佔位機制本身要先驗證正確，否則後面的測試都建立在
        錯誤假設上。"""
        t = self.store.create_track(
            destination="PRG", outstations=["NRT"],
            window_start="2027-04", window_end="2027-05",
            trip_days_min=12, trip_days_max=12,
            target_price=40000, scan_frequency_days=7)
        self.assertEqual(t["id"], migrate.TRACK_ID)

    def test_migrates_trip_days_and_preserves_other_fields(self):
        self.store.create_track(
            destination="PRG", outstations=["NRT"],
            window_start="2027-04", window_end="2027-05",
            trip_days_min=12, trip_days_max=12,
            target_price=40000, scan_frequency_days=7)
        self.store.record_notification(migrate.TRACK_ID, 51618, ok=True,
                                       when="2026-09-24T12:00:00")

        code, output = self._run()

        self.assertEqual(code, 0)
        after = self.store.get_track(migrate.TRACK_ID)
        self.assertEqual(after["trip_days_min"], 10)
        self.assertEqual(after["trip_days_max"], 14)
        self.assertEqual(after["target_price"], 40000)
        self.assertEqual(after["scan_frequency_days"], 7)
        self.assertEqual(after["notify"]["last_notified_price"], 51618)
        self.assertIn("遷移完成", output)

    def test_dry_run_does_not_write(self):
        self.store.create_track(
            destination="PRG", outstations=["NRT"],
            window_start="2027-04", window_end="2027-05",
            trip_days_min=12, trip_days_max=12)

        code, output = self._run(dry_run=True)

        self.assertEqual(code, 0)
        after = self.store.get_track(migrate.TRACK_ID)
        self.assertEqual(after["trip_days_min"], 12)
        self.assertEqual(after["trip_days_max"], 12)
        self.assertIn("dry-run", output)

    def test_missing_track_aborts_without_writing(self):
        """id=9 不存在時中止，回傳非 0——避免在錯的環境誤跑。"""
        code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("找不到", output)

    def test_already_migrated_is_a_safe_no_op(self):
        """重跑已遷移過的條件不該報錯，也不該視為失敗（冪等）。"""
        self.store.create_track(
            destination="PRG", outstations=["NRT"],
            window_start="2027-04", window_end="2027-05",
            trip_days_min=10, trip_days_max=14)
        code, output = self._run()
        self.assertEqual(code, 0)
        self.assertIn("不需要遷移", output)


if __name__ == "__main__":
    unittest.main()
