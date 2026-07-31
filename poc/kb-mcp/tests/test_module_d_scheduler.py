"""module_d_scheduler.py 測試：CLI 入口，mock review_engine.run_module_d_batch，
不打真實API／不跑真實下層檢視邏輯（下層邏輯已在test_review_engine.py涵蓋）。

比照 tests/test_market_scan.py 的 MainCliTest 既有慣例。
"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import module_d_scheduler  # noqa: E402
import review_engine  # noqa: E402


class MainCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-moduled-cli-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _fake_summary(self, failed=None, concern_codes=None):
        return {"total": 2, "checked_count": 2 - len(failed or []),
                "failed_count": len(failed or []), "failed": failed or [],
                "concern_codes": concern_codes or [], "results": []}

    def test_main_scheduled_trigger_runs_batch_and_returns_zero(self):
        with unittest.mock.patch.object(
                review_engine, "run_module_d_batch",
                return_value=self._fake_summary()) as mock_batch:
            code = module_d_scheduler.main(
                ["--data-dir", self.tmp, "--trigger", "scheduled"])
            self.assertEqual(mock_batch.call_count, 1)
            called_args, called_kwargs = mock_batch.call_args
            self.assertEqual(called_kwargs.get("data_dir"), self.tmp)
        self.assertEqual(code, 0)

    def test_main_manual_trigger_passed_through(self):
        with unittest.mock.patch.object(
                review_engine, "run_module_d_batch",
                return_value=self._fake_summary()):
            code = module_d_scheduler.main(
                ["--data-dir", self.tmp, "--trigger", "manual"])
        self.assertEqual(code, 0)

    def test_main_default_trigger_is_scheduled(self):
        with unittest.mock.patch.object(
                review_engine, "run_module_d_batch",
                return_value=self._fake_summary()):
            code = module_d_scheduler.main(["--data-dir", self.tmp])
        self.assertEqual(code, 0)

    def test_main_prints_summary_line(self):
        summary = self._fake_summary(
            failed=[{"code": "9999", "error": "非預期錯誤：boom"}],
            concern_codes=["2330"])
        with unittest.mock.patch.object(
                review_engine, "run_module_d_batch", return_value=summary), \
             unittest.mock.patch("builtins.print") as mock_print:
            module_d_scheduler.main(["--data-dir", self.tmp, "--trigger", "scheduled"])

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("module_d_scheduler完成", printed)
        self.assertIn("trigger=scheduled", printed)
        self.assertIn("total=2", printed)
        self.assertIn("checked=1", printed)
        self.assertIn("failed=1", printed)
        self.assertIn("concern=1", printed)
        self.assertIn("9999", printed)  # 失敗代碼要印出來，方便launchd log排查

    def test_main_unexpected_exception_returns_one_not_silent(self):
        """排程失敗不該讓 launchd 誤判為靜默成功——run_module_d_batch本身
        理論上內部都有try/except不會往外丟例外，但CLI層仍要有最後防線。"""
        with unittest.mock.patch.object(
                review_engine, "run_module_d_batch", side_effect=Exception("db炸了")):
            code = module_d_scheduler.main(["--data-dir", self.tmp])
        self.assertEqual(code, 1)

    def test_invalid_trigger_choice_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            module_d_scheduler.main(
                ["--data-dir", self.tmp, "--trigger", "not-a-real-choice"])


if __name__ == "__main__":
    unittest.main()
