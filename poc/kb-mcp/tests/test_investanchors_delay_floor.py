"""間隔下限防呆：頁／篇 ≥30 秒、圖片 ≥5 秒；正式 CLI 與 plist 不得有調降途徑。

只用 127.0.0.1 假網站與純函式，不連任何真實網路。
"""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import article_images  # noqa: E402
import article_probe  # noqa: E402
import article_reconcile  # noqa: E402
import fake_investanchors_site  # noqa: F401,E402  會設定測試用環境變數；以下各測試自行移除
import investanchors_import as I  # noqa: E402
import investanchors_limits as L  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402

ENV = L.TEST_SHORT_DELAY_ENV
SESSION_JS = os.path.join(HERE, "..", "scraper", "investanchors_session.js")
PLIST = os.path.join(HERE, "..", "..", "..", "ops", "launchd", "com.alphavibe.investanchorsimport.plist")
NODE = shutil.which("node") or "/opt/homebrew/bin/node"


def _env(allow):
    e = {k: v for k, v in os.environ.items() if k != ENV}
    if allow:
        e[ENV] = "1"
    return e


def _node_clamp(range_, allow, image=False):
    code = ("const s=require(%s);const r=s.clampDelay(%s,process.env%s);console.log(JSON.stringify(r));"
            % (json.dumps(os.path.abspath(SESSION_JS)), json.dumps(range_),
               ",s.MIN_IMAGE_DELAY_MS" if image else ""))
    out = subprocess.run([NODE, "-e", code], env=_env(allow), capture_output=True, timeout=60,
                         cwd=os.path.dirname(SESSION_JS))
    assert out.returncode == 0, out.stderr.decode()[-300:]
    return json.loads(out.stdout.decode().strip().splitlines()[-1])


class JsClampTest(unittest.TestCase):
    def test_js_below_floor_is_clamped_without_env(self):                      # (1)
        self.assertEqual(_node_clamp([30, 60], False), [30000, 30000])
        self.assertEqual(_node_clamp([100, 200], False), [30000, 30000])
        self.assertEqual(_node_clamp([10000, 90000], False), [30000, 90000])

    def test_js_valid_values_pass_through(self):                               # (2)
        self.assertEqual(_node_clamp([30000, 90000], False), [30000, 90000])
        self.assertEqual(_node_clamp([45000, 60000], False), [45000, 60000])

    def test_js_small_values_allowed_with_test_env(self):                      # (3)
        self.assertEqual(_node_clamp([30, 60], True), [30, 60])

    def test_js_image_floor_5s(self):                                          # (5) JS 側常數
        self.assertEqual(_node_clamp([100, 200], False, image=True), [5000, 5000])
        self.assertEqual(_node_clamp([6000, 9000], False, image=True), [6000, 9000])
        self.assertEqual(_node_clamp([100, 200], True, image=True), [100, 200])

    @unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
    def test_scraper_reports_effective_delay_without_env(self):                # (1) 實際子行程事實事件
        payload = {"mode": "import", "email": "a@example.com", "password": "x",
                   "base_url": "http://127.0.0.1:9", "known_ids": [], "pending_ids": [],
                   "max_list_pages": 1, "max_articles": 0, "delay_ms": [30, 60], "timeout_ms": 3000}
        scraper = os.path.join(HERE, "..", "scraper", "investanchors_scraper.js")
        out = subprocess.run([NODE, scraper], input=json.dumps(payload).encode(), env=_env(False),
                             capture_output=True, timeout=120, cwd=os.path.dirname(scraper))
        objs = [json.loads(x) for x in out.stdout.decode().splitlines() if x.strip().startswith("{")]
        summ = [o for o in objs if o.get("type") == "summary"][-1]
        self.assertEqual(summ["effective_delay_ms"], [30000, 30000])


class PythonClampTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop(ENV, None)
        self.addCleanup(lambda: os.environ.__setitem__(ENV, self._saved) if self._saved else None)

    def test_importer_and_reconciler_clamp_payload_delay(self):                # (1)(2)(3)
        for cls in (I.Importer, article_reconcile.Reconciler):
            a = argparse.Namespace()
            self.assertEqual(cls(a, delay_ms=[10, 20]).delay_ms, [30000, 30000])
            self.assertEqual(cls(a, delay_ms=[30000, 90000]).delay_ms, [30000, 90000])
            self.assertEqual(cls(a).delay_ms, [30000, 90000])
            os.environ[ENV] = "1"
            try:
                self.assertEqual(cls(a, delay_ms=[10, 20]).delay_ms, [10, 20])
            finally:
                del os.environ[ENV]

    def test_image_delay_floor_python(self):                                   # (5)
        self.assertEqual(L.IMAGE_DELAY_RANGE[0], L.MIN_IMAGE_DELAY_SECONDS)
        self.assertEqual(L.clamp_image_delay_seconds(0.1), 5)
        self.assertEqual(L.clamp_image_delay_seconds(7), 7)
        self.assertEqual(L.clamp_image_delay_seconds(0.1, {ENV: "1"}), 0.1)
        # 即使常數範圍被改小，download_images 實際睡眠也不低於 5 秒
        import tempfile

        class StubStore(object):
            def list_images(self, article_id):
                return [{"seq": 1, "src_url": "http://127.0.0.1:9/a.png"},
                        {"seq": 2, "src_url": "http://127.0.0.1:9/b.png"}]

            def set_image_file(self, *a, **k):
                pass

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = StubStore()
        sleeps = []
        old = L.IMAGE_DELAY_RANGE
        L.IMAGE_DELAY_RANGE = (0.001, 0.002)
        try:
            article_images.download_images(store, 1, tmp, sleeper=sleeps.append, timeout=1,
                                           allowed_hosts=("127.0.0.1",))
        finally:
            L.IMAGE_DELAY_RANGE = old
        self.assertEqual(sleeps, [5])


class NoCliBypassTest(unittest.TestCase):
    def test_no_cli_option_can_lower_delay(self):                              # (4)
        import re
        parsers = [I.build_parser(), article_reconcile.build_parser()]
        for ap in parsers:
            opts = [o for a in ap._actions for o in a.option_strings]
            for o in opts:
                self.assertFalse(re.search("delay|interval|sleep|wait|fast", o.lower()), o)
        # article_probe 的 parser 寫在 main() 內：以原始碼檢查所有 add_argument 旗標
        with open(os.path.join(HERE, "..", "article_probe.py"), encoding="utf-8") as f:
            src = f.read()
        flags = re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', src)
        self.assertTrue(flags)
        for o in flags:
            self.assertFalse(re.search("delay|interval|sleep|wait|fast", o), o)


class PlistNoBypassTest(unittest.TestCase):
    def test_plist_has_no_short_delay_env(self):                               # (6)
        with open(PLIST, "rb") as f:
            p = plistlib.load(f)
        self.assertNotIn(ENV, p.get("EnvironmentVariables", {}))
        self.assertNotIn(ENV, json.dumps(p))


if __name__ == "__main__":
    unittest.main()
