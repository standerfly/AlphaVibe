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


class SubstackBackupTest(unittest.TestCase):
    """011 US7（T052；US7-AS3、V9）：substack.db 以可選資料庫納入每日備份；
    substack_images/ 以增量鏡像備份（只複製新檔或大小不同者、不刪目的端、完成寫 .last_sync）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="alphavibe-bk011-")
        self.data = os.path.join(self.root, "data")
        self.dest = os.path.join(self.root, "dest")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.root, True)
        for n in bk.DATABASES:
            _mkdb(os.path.join(self.data, n), n)

    def _daily(self):
        return sorted(os.listdir(os.path.join(self.dest, "daily")))

    def _write(self, rel, data):
        path = os.path.join(self.data, "substack_images", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_substack_registered_as_optional(self):
        self.assertIn("substack.db", bk.OPTIONAL_DATABASES)
        self.assertIn("articles.db", bk.OPTIONAL_DATABASES)
        self.assertNotIn("substack.db", bk.DATABASES)
        self.assertIn(("substack_images", "substack_images"), bk.OPTIONAL_DIR_MIRRORS)

    def test_substack_missing_is_skipped_without_failure(self):
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        self.assertIn("substack.db 略過（尚未建立）", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "substack.db")))
        self.assertFalse([f for f in self._daily() if f.startswith("substack-")])

    def test_substack_present_backup_integrity_ok(self):
        _mkdb(os.path.join(self.data, "substack.db"), "sub-marker")
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        f = [x for x in self._daily() if x.startswith("substack-") and x.endswith(".db.gz")]
        self.assertEqual(len(f), 1)
        line = [ln for ln in out.splitlines() if f[0] in ln][0]
        self.assertIn("完整性 ok", line)
        out_db = os.path.join(self.root, "restored.db")
        with gzip.open(os.path.join(self.dest, "daily", f[0])) as fi, open(out_db, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        c = sqlite3.connect(out_db)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(c.execute("SELECT v FROM t").fetchall(), [("sub-marker",)])
        c.close()

    def test_mirror_copies_new_and_resized_only_and_never_deletes(self):
        src = os.path.join(self.data, "substack_images")
        dst = os.path.join(self.root, "mirror", "substack_images")
        self._write("1/1.png", b"a" * 10)
        self._write("2/1.jpg", b"b" * 20)
        copied, total = bk.mirror_dir(src, dst)
        self.assertEqual((copied, total), (2, 2))
        with open(os.path.join(dst, "2", "1.jpg"), "rb") as f:
            self.assertEqual(f.read(), b"b" * 20)
        self.assertTrue(os.path.isfile(os.path.join(dst, ".last_sync")))
        # 目的端多出的檔案不刪；同大小不重抄；大小不同才重抄
        extra = os.path.join(dst, "9", "old.png")
        os.makedirs(os.path.dirname(extra))
        with open(extra, "wb") as f:
            f.write(b"keep")
        self._write("1/1.png", b"c" * 11)                      # 大小改變
        copied, total = bk.mirror_dir(src, dst)
        self.assertEqual((copied, total), (1, 2))
        with open(os.path.join(dst, "1", "1.png"), "rb") as f:
            self.assertEqual(f.read(), b"c" * 11)
        self.assertTrue(os.path.isfile(extra), "鏡像不得刪除目的端多出的檔案")
        # 第二次（沒有變化）複製 0 個
        self.assertEqual(bk.mirror_dir(src, dst), (0, 2))

    def test_mirror_source_missing_skips_and_creates_nothing(self):
        src = os.path.join(self.data, "substack_images")
        dst = os.path.join(self.root, "mirror", "substack_images")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            result = bk.mirror_dir(src, dst)
        self.assertIsNone(result)
        self.assertEqual(len([ln for ln in buf.getvalue().splitlines() if ln.strip()]), 1)
        self.assertIn("略過", buf.getvalue())
        self.assertFalse(os.path.exists(src))
        self.assertFalse(os.path.exists(os.path.join(self.root, "mirror")))

    def test_main_mirrors_after_database_loop(self):
        _mkdb(os.path.join(self.data, "substack.db"), "s")
        self._write("3/2.png", b"z" * 5)
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        mirror = os.path.join(self.dest, "mirror", "substack_images")
        self.assertTrue(os.path.isfile(os.path.join(mirror, "3", "2.png")))
        self.assertTrue(os.path.isfile(os.path.join(mirror, ".last_sync")))
        lines = out.splitlines()
        db_idx = max(i for i, ln in enumerate(lines) if ".db.gz" in ln)
        mirror_idx = min(i for i, ln in enumerate(lines) if "鏡像" in ln)
        self.assertGreater(mirror_idx, db_idx, "鏡像要在資料庫迴圈之後")
        # 第二次執行：鏡像複製 0 個
        rc2, out2 = _run(self.data, self.dest)
        self.assertEqual(rc2, 0)
        self.assertIn("複製 0 個", out2)

    def test_main_without_images_dir_does_not_create_mirror(self):
        rc, out = _run(self.data, self.dest)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "mirror")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "substack_images")))


if __name__ == "__main__":
    unittest.main()
