"""T011：`substack_import.py` 的骨架——資料目錄防呆、執行鎖、互斥選項、退出碼（contracts/cli.md）。

主流程（抓取、通知、排程日、預算）的測試在 T019～T021 另加。
本檔案所有測試都用獨立 tempfile 資料目錄，零真實網路。
"""
import fcntl
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import article_data_guard  # noqa: E402
import substack_import as IMP  # noqa: E402


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.notifier = F.FakeNotifier()
        self.out = io.StringIO()
        self.err = io.StringIO()

    def go(self, *args, **kwargs):
        argv = ["--data-dir", kwargs.pop("data_dir", self.dir)] + list(args)
        deps = {"http": self.http, "notifier": self.notifier, "clock": self.clock,
                "sleep": self.clock.sleep, "env": kwargs.pop("env", {}),
                "out": self.out, "err": self.err}
        deps.update(kwargs)
        return IMP.run(argv, **deps)

    @property
    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    def db_path(self):
        return os.path.join(self.dir, "substack.db")


class DataDirGuardTest(ImportTestBase):
    def test_missing_data_dir_refused(self):
        code = IMP.run([], http=self.http, out=self.out, err=self.err, env={})
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0)

    def test_production_data_dir_refused_before_anything(self):
        prod = article_data_guard.PRODUCTION_DATA_DIR
        before = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        code = self.go(data_dir=prod)
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0, "防呆要先於任何請求")
        self.assertEqual(self.notifier.calls, 0)
        after = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        self.assertEqual(before, after, "拒絕後正式資料目錄不得被建立任何檔案")
        self.assertFalse(os.path.exists(os.path.join(prod, "substack.db")))
        self.assertFalse(os.path.exists(os.path.join(prod, IMP.LOCK_NAME)))

    def test_production_data_dir_allowed_with_flag(self):
        """只驗 guard 判斷（帶旗標時不拒絕）；不真的對正式目錄執行。"""
        prod = article_data_guard.PRODUCTION_DATA_DIR
        self.assertEqual(
            article_data_guard.resolve_data_dir(prod, env={"ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "1"}),
            prod)


class LockTest(ImportTestBase):
    def hold_lock(self):
        path = os.path.join(self.dir, IMP.LOCK_NAME)
        handle = open(path, "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(handle.close)
        return handle

    def test_busy_exits_3_without_touching_db_or_network(self):
        F.write_config(self.dir)
        self.hold_lock()
        code = self.go()
        self.assertEqual(code, IMP.EXIT_BUSY)
        self.assertIn("忙碌", self.text)
        self.assertFalse(os.path.exists(self.db_path()), "忙碌時不得建立資料庫（FR-017）")
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0)

    def test_busy_leaves_existing_db_bytes_unchanged(self):
        import substack_store as S
        F.write_config(self.dir)
        store = S.SubstackStore(self.dir)
        store.close()
        before = os.path.getsize(self.db_path())
        self.hold_lock()
        self.assertEqual(self.go(), IMP.EXIT_BUSY)
        self.assertEqual(os.path.getsize(self.db_path()), before)

    def test_lock_is_released_on_every_path(self):
        """任何例外／提早返回之後，鎖都必須可以再被取得。"""
        F.write_config(self.dir)
        self.go()                       # 骨架階段：動作未實作也要釋放鎖
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)      # 取不到會丟 BlockingIOError
        fcntl.flock(handle, fcntl.LOCK_UN)

    def test_lock_released_after_internal_exception(self):
        F.write_config(self.dir)
        boom = io.StringIO()

        def explode(*a, **k):
            raise RuntimeError("注入的例外")
        original = IMP.dispatch
        IMP.dispatch = explode
        try:
            with self.assertRaises(RuntimeError):
                IMP.run(["--data-dir", self.dir], http=self.http, out=boom, err=boom, env={},
                        clock=self.clock)
        finally:
            IMP.dispatch = original
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


class CliShapeTest(ImportTestBase):
    def test_exit_codes_match_contract(self):
        self.assertEqual(IMP.EXIT_OK, 0)
        self.assertEqual(IMP.EXIT_AUTHOR_FAILED, 1)
        self.assertEqual(IMP.EXIT_REFUSED, 2)
        self.assertEqual(IMP.EXIT_BUSY, 3)
        self.assertEqual(IMP.EXIT_DISK, 4)
        self.assertEqual(IMP.EXIT_USAGE_LIMIT, 5)

    def test_parser_declares_every_documented_option(self):
        parser = IMP.build_parser()
        samples = [
            ["--data-dir", "d"],
            ["--data-dir", "d", "--scheduled"],
            ["--data-dir", "d", "--dry-run"],
            ["--data-dir", "d", "--backfill", "zzauthora"],
            ["--data-dir", "d", "--retry-images", "1,2"],
            ["--data-dir", "d", "--reclassify", "--article-ids", "1,2"],
            ["--data-dir", "d", "--reclassify", "--author", "zzauthora"],
            ["--data-dir", "d", "--reclassify", "--article-ids", "1", "--dry-run"],
            ["--data-dir", "d", "--reclassify-history", "1,2"],
            ["--data-dir", "d", "--status"],
        ]
        for argv in samples:
            parser.parse_args(argv)         # 不該丟例外

    def test_mutually_exclusive_actions_refused(self):
        F.write_config(self.dir)
        combos = [
            ["--backfill", "zzauthora", "--reclassify", "--author", "zzauthora"],
            ["--backfill", "zzauthora", "--retry-images", "1"],
            ["--status", "--backfill", "zzauthora"],
            ["--reclassify", "--article-ids", "1", "--author", "zzauthora"],
            ["--reclassify"],                               # 少了 --article-ids／--author
            ["--article-ids", "1"],                         # 沒有 --reclassify
            ["--reclassify-history", "1", "--reclassify", "--article-ids", "1"],
        ]
        for argv in combos:
            self.out, self.err = io.StringIO(), io.StringIO()
            code = self.go(*argv)
            self.assertEqual(code, IMP.EXIT_REFUSED, "%s 應該被拒絕（exit 2）" % argv)
            self.assertEqual(self.http.count(), 0)

    def test_unimplemented_action_reports_code(self):
        import substack_store as S
        F.write_config(self.dir)
        store = S.SubstackStore(self.dir)
        store.close()
        code = self.go("--status")
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertIn("not_implemented", self.text)

    def test_readonly_action_without_db_refuses_without_creating_it(self):
        code = self.go("--status")
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertFalse(os.path.exists(self.db_path()), "唯讀動作不得建庫")


if __name__ == "__main__":
    unittest.main()
