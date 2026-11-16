"""010 T049：launchd plist 靜態檢查（只讀 plist，不安裝、不碰 launchctl）。"""
import os
import plistlib
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
PLIST = os.path.join(HERE, "..", "..", "..", "ops", "launchd", "com.alphavibe.investanchorsimport.plist")
PROD_DATA = "/Users/stander/My_project/AlphaVibe-prod/poc/data"

import article_data_guard as guard  # noqa: E402


def _load():
    with open(PLIST, "rb") as f:
        return plistlib.load(f)


class PlistTest(unittest.TestCase):
    def setUp(self):
        self.p = _load()

    def test_label(self):
        self.assertEqual(self.p["Label"], "com.alphavibe.investanchorsimport")

    def test_schedule_2300_single(self):
        sci = self.p["StartCalendarInterval"]
        self.assertIsInstance(sci, dict)
        self.assertEqual((sci["Hour"], sci["Minute"]), (23, 0))

    def test_no_runatload_or_keepalive(self):
        self.assertNotIn("RunAtLoad", self.p)
        self.assertNotIn("KeepAlive", self.p)

    def test_env(self):
        env = self.p["EnvironmentVariables"]
        self.assertEqual(env["ALPHAVIBE_ALLOW_PRODUCTION_WRITE"], "1")
        self.assertIn("/opt/homebrew/bin", env["PATH"].split(":"))

    def test_program_arguments(self):
        a = self.p["ProgramArguments"]
        self.assertEqual(a[0], "/usr/bin/python3")
        self.assertEqual(a[1], "/Users/stander/My_project/AlphaVibe-prod/poc/kb-mcp/investanchors_import.py")
        self.assertEqual(a[a.index("--data-dir") + 1], PROD_DATA)
        self.assertEqual(self.p["WorkingDirectory"], "/Users/stander/My_project/AlphaVibe-prod")

    def test_logs(self):
        for k in ("StandardOutPath", "StandardErrorPath"):
            self.assertTrue(self.p[k].startswith("/Users/stander/Library/Logs/alphavibe-investanchors"))

    def test_guard_logic_with_plist_data_dir(self):
        """prod 的 poc/data 是 symlink，realpath 後即正式資料目錄：沒旗標拒絕、帶旗標（plist 的值）放行。
        以注入的 env 與假的正式目錄模擬，不碰真實正式庫。"""
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="ia-plist-")
        try:
            real = os.path.realpath(os.path.join(tmp, "real-data"))
            os.makedirs(real)
            link = os.path.join(tmp, "prod", "poc-data")
            os.makedirs(os.path.dirname(link))
            os.symlink(real, link)
            old = guard.PRODUCTION_DATA_DIR
            guard.PRODUCTION_DATA_DIR = real
            try:
                with self.assertRaises(guard.DataDirRefused):
                    guard.resolve_data_dir(link, env={})
                env = dict(self.p["EnvironmentVariables"])
                self.assertEqual(guard.resolve_data_dir(link, env=env), real)
            finally:
                guard.PRODUCTION_DATA_DIR = old
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
