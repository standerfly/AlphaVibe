"""report_server 測試：即時渲染、PWA meta、icon、健康檢查、404。"""
import os
import shutil
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import report  # noqa: E402
import report_server  # noqa: E402
import screener  # noqa: E402
from kb_store import KBStore  # noqa: E402


class ReportServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="alphavibe-rsrv-test-")
        report_server.ReportHandler.data_dir = cls.tmp
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), report_server.ReportHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def _get(self, path):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def _post(self, path, form):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def test_page_ok_and_pwa_meta(self):
        status, headers, body = self._get("/")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("AlphaVibe 知識庫檢視", page)
        self.assertIn("apple-mobile-web-app-capable", page)
        self.assertIn("apple-touch-icon", page)

    def test_live_rendering_reflects_new_data(self):
        _, _, before = self._get("/report.html")
        self.assertNotIn("台積電".encode("utf-8"), before)
        store = KBStore(self.tmp)
        store.save_stance("2330", "偏多", name="台積電")
        store.close()
        _, _, after = self._get("/report.html")
        self.assertIn("台積電".encode("utf-8"), after)

    def test_legacy_bookmark_path(self):
        status, _, body = self._get("/poc/data/report.html")
        self.assertEqual(status, 200)
        self.assertIn("AlphaVibe 知識庫檢視".encode("utf-8"), body)

    def test_icon_is_valid_png(self):
        status, headers, body = self._get("/apple-touch-icon.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        # 舊書籤路徑下的相對 icon 連結也要通
        status2, _, _ = self._get("/poc/data/apple-touch-icon.png")
        self.assertEqual(status2, 200)

    def test_healthz_and_404(self):
        status, _, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/no/such/page")
        self.assertEqual(ctx.exception.code, 404)

    def test_screen_get_returns_form(self):
        status, headers, body = self._get("/screen")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("<form method=\"post\" action=\"/screen\">", page)

    def test_screen_post_empty_codes_reshows_form_with_error(self):
        status, _, body = self._post("/screen", {"codes": "   "})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("請至少輸入一個股票代碼", page)

    def test_screen_post_renders_results_table(self):
        fake_result = {
            "results": [{"code": "2330", "name": "台積電", "per": 10.0,
                        "revenue_yoy": 0.20, "drawdown_pct": 0.40,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 60.0, "current_date": "2026-07-01",
                        "peg": 0.5, "meets_framework": True, "error": None}],
            "total": 1,
        }
        with unittest.mock.patch.object(
                screener, "screen_stocks", return_value=fake_result) as mock_screen:
            status, _, body = self._post("/screen", {"codes": "2330"})
        mock_screen.assert_called_once_with(["2330"], data_dir=self.tmp)
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("data-label=\"代碼\">2330", page)
        self.assertIn("background:#fff3bf", page)

    def test_screen_post_wrong_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/no/such/post", {"codes": "2330"})
        self.assertEqual(ctx.exception.code, 404)


class StaticIconTest(unittest.TestCase):
    def test_static_mode_writes_icon(self):
        tmp = tempfile.mkdtemp(prefix="alphavibe-static-icon-")
        try:
            out = os.path.join(tmp, "report.html")
            self.assertEqual(report.main(["--data-dir", tmp, "--out", out]), 0)
            icon = os.path.join(tmp, "apple-touch-icon.png")
            self.assertTrue(os.path.exists(icon))
            with open(icon, "rb") as fh:
                self.assertTrue(fh.read(8) == b"\x89PNG\r\n\x1a\n")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
