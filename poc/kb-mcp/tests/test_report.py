"""report.py 測試：有資料／空資料／HTML 跳脫。"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import report  # noqa: E402
from kb_store import KBStore  # noqa: E402


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-report-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _generate(self):
        out = os.path.join(self.tmp, "report.html")
        code = report.main(["--data-dir", self.tmp, "--out", out])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            return fh.read()

    def test_report_with_data(self):
        store = KBStore(self.tmp)
        store.save_stance("2330", "偏多", name="台積電",
                          entry_condition="900 以下分批",
                          valuation_metric="PER 20 以下", source_ref="conv#1")
        store.save_comment("大盤量縮整理，觀望 FOMC", source_tag="conversation",
                           symbols="TAIEX")
        store.save_philosophy("yuzhiyu", "# 低 PER 高殖利率")
        store.close()

        page = self._generate()
        self.assertIn("台積電", page)
        self.assertIn("900 以下分批", page)
        self.assertIn("#c92a2a", page)  # 偏多＝紅（台股慣例）
        self.assertIn("大盤量縮整理", page)
        self.assertIn("yuzhiyu", page)
        self.assertIn("立場 1 檔", page)

    def test_report_empty_db(self):
        page = self._generate()
        self.assertIn("尚無立場資料", page)
        self.assertIn("尚無評論資料", page)
        self.assertIn("立場 0 檔", page)

    def test_html_escaping(self):
        store = KBStore(self.tmp)
        store.save_comment("<script>alert(1)</script> 惡意內容測試",
                           source_tag="web")
        store.save_stance("2454", "偏多", reason="估值 <合理> & 便宜")
        store.close()

        page = self._generate()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;合理&gt; &amp; 便宜", page)


if __name__ == "__main__":
    unittest.main()
