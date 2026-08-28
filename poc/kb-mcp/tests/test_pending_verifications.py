"""待觀察／待查詢清單（pending_verifications）單元測試。

對應 specs/001-pending-verification-list/tasks.md T003/T006/T013/T016，
驗證規則見 specs/001-pending-verification-list/data-model.md。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from kb_store import KBStore  # noqa: E402


class PendingVerificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-pv-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    # ---------- T003: save_pending_verification ----------

    def test_save_success_date_trigger(self):
        rec = self.store.save_pending_verification(
            judgment_text="NVIDIA漲價是否守住75%毛利率",
            trigger_type="date",
            trigger_condition_text="NVIDIA公布Q2 FY2027財報",
            trigger_date="2026-08-26",
            code="NVDA",
            target_value="毛利率75%",
        )
        self.assertEqual(rec["status"], "pending")
        self.assertEqual(rec["trigger_date"], "2026-08-26")
        self.assertEqual(rec["code"], "NVDA")
        self.assertIsNone(rec["resolution"])
        self.assertIsNotNone(rec["id"])

    def test_save_success_event_trigger_without_date(self):
        rec = self.store.save_pending_verification(
            judgment_text="超大規模業者是否持續消化漲價",
            trigger_type="event",
            trigger_condition_text="下一輪資本支出guidance公布",
        )
        self.assertEqual(rec["status"], "pending")
        self.assertIsNone(rec["trigger_date"])

    def test_save_missing_judgment_text_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_pending_verification(
                judgment_text="",
                trigger_type="event",
                trigger_condition_text="某事件",
            )

    def test_save_invalid_trigger_type_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_pending_verification(
                judgment_text="判斷",
                trigger_type="sometime",
                trigger_condition_text="條件",
            )

    def test_save_missing_trigger_condition_text_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_pending_verification(
                judgment_text="判斷", trigger_type="event",
                trigger_condition_text="",
            )

    def test_save_date_type_missing_trigger_date_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_pending_verification(
                judgment_text="判斷", trigger_type="date",
                trigger_condition_text="財報公布",
            )

    # ---------- T006: list_pending_verifications ----------

    def test_list_filter_by_status(self):
        a = self.store.save_pending_verification(
            "判斷A", "event", "條件A")
        self.store.save_pending_verification("判斷B", "event", "條件B")
        self.store.resolve_pending_verification(a["id"], "resolved",
                                                  resolution="已驗證")
        pending = self.store.list_pending_verifications(status="pending")
        resolved = self.store.list_pending_verifications(status="resolved")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["judgment_text"], "判斷B")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["judgment_text"], "判斷A")

    def test_list_due_only_includes_overdue_and_near_term(self):
        overdue = self.store.save_pending_verification(
            "已過期", "date", "條件", trigger_date="2020-01-01")
        near = self.store.save_pending_verification(
            "即將到期", "date", "條件",
            trigger_date=_days_from_now(3))
        far = self.store.save_pending_verification(
            "還很遠", "date", "條件", trigger_date=_days_from_now(30))
        due = self.store.list_pending_verifications(due_only=True)
        due_ids = {row["id"] for row in due}
        self.assertIn(overdue["id"], due_ids)
        self.assertIn(near["id"], due_ids)
        self.assertNotIn(far["id"], due_ids)

    def test_list_due_only_boundary_at_window_edge(self):
        edge = self.store.save_pending_verification(
            "剛好7天", "date", "條件", trigger_date=_days_from_now(7))
        due = self.store.list_pending_verifications(due_only=True)
        self.assertIn(edge["id"], {row["id"] for row in due})

    def test_list_due_only_excludes_event_without_date(self):
        no_date = self.store.save_pending_verification(
            "事件無日期", "event", "條件")
        due = self.store.list_pending_verifications(due_only=True)
        self.assertNotIn(no_date["id"], {row["id"] for row in due})

    def test_list_due_only_excludes_non_pending(self):
        item = self.store.save_pending_verification(
            "已過期但已解決", "date", "條件", trigger_date="2020-01-01")
        self.store.resolve_pending_verification(item["id"], "resolved",
                                                  resolution="結論")
        due = self.store.list_pending_verifications(due_only=True)
        self.assertNotIn(item["id"], {row["id"] for row in due})

    def test_list_empty(self):
        self.assertEqual(self.store.list_pending_verifications(), [])
        self.assertEqual(
            self.store.list_pending_verifications(due_only=True), [])

    # ---------- T013: resolve_pending_verification（resolved 路徑）----------

    def test_resolve_success_with_resolution(self):
        item = self.store.save_pending_verification(
            "判斷", "date", "條件", trigger_date="2020-01-01")
        resolved = self.store.resolve_pending_verification(
            item["id"], "resolved", resolution="財報顯示毛利率守住75%")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolution"], "財報顯示毛利率守住75%")
        self.assertIsNotNone(resolved["resolved_at"])

    def test_resolve_missing_resolution_rejected(self):
        item = self.store.save_pending_verification(
            "判斷", "event", "條件")
        with self.assertRaises(ValueError):
            self.store.resolve_pending_verification(item["id"], "resolved")

    def test_resolve_already_terminal_rejected(self):
        item = self.store.save_pending_verification(
            "判斷", "event", "條件")
        self.store.resolve_pending_verification(item["id"], "resolved",
                                                  resolution="結論")
        with self.assertRaises(ValueError):
            self.store.resolve_pending_verification(item["id"], "dropped")

    def test_resolve_not_found_rejected(self):
        with self.assertRaises(ValueError):
            self.store.resolve_pending_verification(99999, "resolved",
                                                       resolution="x")

    # ---------- T016: resolve_pending_verification（dropped 路徑）----------

    def test_drop_success_without_resolution(self):
        item = self.store.save_pending_verification(
            "判斷", "event", "條件")
        dropped = self.store.resolve_pending_verification(
            item["id"], "dropped")
        self.assertEqual(dropped["status"], "dropped")
        self.assertIsNone(dropped["resolution"])
        self.assertIsNotNone(dropped["resolved_at"])

    def test_drop_success_with_optional_resolution(self):
        item = self.store.save_pending_verification(
            "判斷", "event", "條件")
        dropped = self.store.resolve_pending_verification(
            item["id"], "dropped", resolution="前提假設已不成立")
        self.assertEqual(dropped["resolution"], "前提假設已不成立")

    def test_drop_already_terminal_rejected(self):
        item = self.store.save_pending_verification(
            "判斷", "event", "條件")
        self.store.resolve_pending_verification(item["id"], "dropped")
        with self.assertRaises(ValueError):
            self.store.resolve_pending_verification(
                item["id"], "resolved", resolution="結論")

    # ---------- get_pending_verification ----------

    def test_get_not_found_returns_none(self):
        self.assertIsNone(self.store.get_pending_verification(99999))


def _days_from_now(n):
    import datetime
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


if __name__ == "__main__":
    unittest.main()
