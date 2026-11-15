"""010 T043／A'(1)：「太舊不開啟」判定的跨語言一致性——Python（article_id_time）與 scraper/id_filter.js 對同一份語料逐筆相同。

語料在 fixtures/id_time_corpus.json（含非 14 位、含字母、過小、未來值、邊界 -1／0／+1、正常近期、前導零、超長字串）。
JS 端不含任何時間常數（本檔也守門）。需要 node；沒有 node 時 skip。"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import article_id_time  # noqa: E402

CORPUS = os.path.join(HERE, "fixtures", "id_time_corpus.json")
SCRAPER_DIR = os.path.join(HERE, "..", "scraper")
NODE = shutil.which("node") or "/opt/homebrew/bin/node"


def _load():
    with open(CORPUS, encoding="utf-8") as f:
        return json.load(f)


def _js_decisions(doc):
    code = ("const {shouldDefer}=require('./id_filter');const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
            "process.stdout.write(JSON.stringify(d.cases.map(c=>shouldDefer(c.id,d.thresholds))));")
    r = subprocess.run([NODE, "-e", code], cwd=SCRAPER_DIR, input=json.dumps(doc), capture_output=True,
                       text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


class CorpusShapeTest(unittest.TestCase):
    def test_corpus_covers_the_required_kinds(self):
        doc = _load()
        ids = [c["id"] for c in doc["cases"]]
        b = doc["thresholds"]["defer_below_id"]
        for needed in (str(b - 1), str(b), str(b + 1)):
            self.assertIn(needed, ids)                                     # 邊界 -1／0／+1
        self.assertTrue(any(not i.isdigit() for i in ids))                  # 含字母／符號
        self.assertTrue(any(i.isdigit() and len(i) != 14 for i in ids))     # 非 14 位
        self.assertTrue(any(i.startswith("0") for i in ids))                # 前導零
        self.assertTrue(any(len(i) > 20 for i in ids))                      # 超長
        self.assertIn(str(doc["thresholds"]["valid_id_max"] + 1), ids)      # 未來值
        self.assertIn(str(doc["thresholds"]["valid_id_min"] - 1), ids)      # 過小
        self.assertTrue(any(c["expect_defer"] for c in doc["cases"]) and
                        any(not c["expect_defer"] for c in doc["cases"]))

    def test_thresholds_in_corpus_are_what_python_computes_now(self):
        doc = _load()
        self.assertEqual(article_id_time.defer_thresholds(doc["cutoff_ms"], doc["now_ms"]), doc["thresholds"])


class PythonSideTest(unittest.TestCase):
    def test_python_matches_expected_column(self):
        doc = _load()
        for c in doc["cases"]:
            self.assertEqual(
                article_id_time.is_before_cutoff(c["id"], doc["cutoff_ms"], now_ms=doc["now_ms"]),
                c["expect_defer"], c)


@unittest.skipUnless(os.path.exists(NODE), "需要 node")
class CrossLanguageTest(unittest.TestCase):
    def test_js_decisions_equal_python_decisions_case_by_case(self):
        doc = _load()
        js = _js_decisions(doc)
        py = [article_id_time.is_before_cutoff(c["id"], doc["cutoff_ms"], now_ms=doc["now_ms"]) for c in doc["cases"]]
        self.assertEqual(len(js), len(py))
        for c, a, b in zip(doc["cases"], js, py):
            self.assertEqual(a, b, "Python 與 JS 判定不一致：%r" % (c,))
        self.assertEqual(js, [c["expect_defer"] for c in doc["cases"]])

    def test_without_thresholds_js_never_defers(self):
        code = "const {shouldDefer}=require('./id_filter');process.stdout.write(String(shouldDefer('17772191999999', null)));"
        r = subprocess.run([NODE, "-e", code], cwd=SCRAPER_DIR, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout, "false")

    def test_id_filter_module_contains_no_time_constants(self):
        with open(os.path.join(SCRAPER_DIR, "id_filter.js"), encoding="utf-8") as f:
            code = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
        for bad in ("2020", "86400", "3600", "EARLIEST", "MARGIN", "slice(0, 13)", "substring", "Date"):
            self.assertNotIn(bad, code)
        self.assertNotRegex(code, r"\b(13|14)\b\s*(\)|\*|,)\s*(?!\})")  # 不做「前 13 位」或天數換算

    def test_scraper_main_file_also_has_no_time_conversion(self):
        with open(os.path.join(SCRAPER_DIR, "investanchors_scraper.js"), encoding="utf-8") as f:
            code = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
        for bad in ("2020", "86400", "EARLIEST", "MARGIN", "slice(0, 13)", "cutoff_ms"):
            self.assertNotIn(bad, code)


if __name__ == "__main__":
    unittest.main()
