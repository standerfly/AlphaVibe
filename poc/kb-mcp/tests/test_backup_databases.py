"""backup_databases.py 測試（010：articles.db 以可選資料庫納入每日備份）。

全部用 tempfile 臨時目錄，不碰 poc/data。
"""
import contextlib
import gzip
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import backup_databases as bk  # noqa: E402
import check_scheduled_jobs as checker  # noqa: E402


def _mkdb(path, marker):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t(v TEXT)")
    c.execute("INSERT INTO t VALUES (?)", (marker,))
    c.commit()
    c.close()


def _run(data_dir, dest):
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = bk.main(["--data-dir", data_dir, "--dest", dest])
    return rc, buf.getvalue()


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="alphavibe-bktest-")
        self.data = os.path.join(self.root, "data")
        self.dest = os.path.join(self.root, "dest")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.root, True)

    def _make_core(self):
        for n in bk.DATABASES:
            _mkdb(os.path.join(self.data, n), n)

    def _daily(self):
        return sorted(os.listdir(os.path.join(self.dest, "daily")))

    def test_articles_missing_no_failure_no_file(self):
        self._make_core()
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        self.assertIn("略過（尚未建立）", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))
        files = self._daily()
        self.assertEqual(len(files), 3)
        self.assertFalse([f for f in files if f.startswith("articles-")])

    def test_articles_present_backup_readable_and_identical(self):
        self._make_core()
        _mkdb(os.path.join(self.data, "articles.db"), "art-marker")
        rc, _ = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        f = [x for x in self._daily() if x.startswith("articles-")]
        self.assertEqual(len(f), 1)
        out = os.path.join(self.root, "restored.db")
        with gzip.open(os.path.join(self.dest, "daily", f[0])) as fi, open(out, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        c = sqlite3.connect(out)
        self.assertEqual(c.execute("SELECT v FROM t").fetchall(), [("art-marker",)])
        c.close()

    def test_core_missing_still_fails(self):
        # 既有三庫缺檔仍維持失敗語意（證明未被改變）
        _mkdb(os.path.join(self.data, "alphavibe.db"), "x")
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 1)
        self.assertIn("來源不存在", out)
        b = bk.backup_one(os.path.join(self.data, "flights.db"),
                          self.root, "s")
        self.assertFalse(b[0])

    def test_core_missing_fails_even_if_articles_missing(self):
        rc, _ = _run(self.data, self.dest)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_prefixes_do_not_collide(self):
        bases = [n[:-3] for n in bk.DATABASES + bk.OPTIONAL_DATABASES]
        for a in bases:
            for b in bases:
                if a != b:
                    self.assertFalse((b + "-").startswith(a + "-"))
        self.assertIn("articles.db", bk.OPTIONAL_DATABASES)
        self.assertNotIn("articles.db", bk.DATABASES)

    def test_prune_only_touches_own_prefix(self):
        d = os.path.join(self.root, "d")
        os.makedirs(d)
        for base in ("articles", "alphavibe", "us_stocks", "flights"):
            for i in range(35):
                open(os.path.join(d, "%s-202601%02d-000000.db.gz" % (base, i + 1)), "w").close()
        gone = bk.prune(d, "articles", bk.DAILY_KEEP)
        self.assertEqual(len(gone), 5)
        left = os.listdir(d)
        self.assertEqual(len([f for f in left if f.startswith("articles-")]), 30)
        for base in ("alphavibe", "us_stocks", "flights"):
            self.assertEqual(len([f for f in left if f.startswith(base + "-")]), 35)

    def test_main_rotation_includes_articles_and_spares_others(self):
        self._make_core()
        _mkdb(os.path.join(self.data, "articles.db"), "a")
        daily = os.path.join(self.dest, "daily")
        os.makedirs(daily)
        for base in ("articles", "alphavibe", "us_stocks", "flights"):
            for i in range(30):
                open(os.path.join(daily, "%s-200001%02d-000000.db.gz" % (base, i + 1)), "w").close()
        rc, _ = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        left = os.listdir(daily)
        for base in ("articles", "alphavibe", "us_stocks", "flights"):
            self.assertEqual(len([f for f in left if f.startswith(base + "-")]), 30)

    def test_monthly_prune_keeps_24(self):
        m = os.path.join(self.root, "m")
        os.makedirs(m)
        for base in ("articles", "alphavibe"):
            for i in range(26):
                open(os.path.join(m, "%s-%04d%02d01-000000.db.gz" % (base, 2020 + i // 12, i % 12 + 1)), "w").close()
        self.assertEqual(len(bk.prune(m, "articles", bk.MONTHLY_KEEP)), 2)
        self.assertEqual(len([f for f in os.listdir(m) if f.startswith("alphavibe-")]), 26)


class HealthCheckUnaffectedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-bkhealth-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, age_hours, size=200000):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(os.urandom(size))
        t = os.path.getmtime(p) - age_hours * 3600
        os.utime(p, (t, t))

    def test_no_articles_backup_no_false_alarm(self):
        self._write("alphavibe-20261116-000000.db.gz", 1)
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "ok")

    def test_stale_articles_backup_does_not_affect_result(self):
        # 健檢只看 alphavibe-*；articles 備份過舊不影響、也不新增檢查
        self._write("alphavibe-20261116-000000.db.gz", 1)
        self._write("articles-20200101-000000.db.gz", 9999)
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "ok")

    def test_alphavibe_stale_still_critical_with_fresh_articles(self):
        self._write("alphavibe-20200101-000000.db.gz", 9999)
        self._write("articles-20261116-000000.db.gz", 1)
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "critical")


if __name__ == "__main__":
    unittest.main()
