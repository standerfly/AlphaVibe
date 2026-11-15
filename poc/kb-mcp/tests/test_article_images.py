"""T015：文章內文圖片下載（本機 http server；不帶 cookie、間隔、路徑安全、失敗只標該圖）。"""
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_images as AI  # noqa: E402
import article_store  # noqa: E402

AID = 17941406364761
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 50


class _Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Handler.requests.append((self.path, self.headers.get("Cookie"), self.headers.get("Authorization")))
        p = self.path.split("?")[0]
        if p == "/ok.png":
            return self._send(PNG, "image/png")
        if p == "/noext":
            return self._send(PNG, "image/png")                     # 無副檔名、靠 Content-Type
        if p == "/page.html":
            return self._send(b"<html>", "text/html")
        if p == "/evil.exe":
            return self._send(b"MZ", "application/octet-stream")
        if p == "/404.png":
            self.send_response(404)
            self.end_headers()
            return
        if p == "/slow.png":
            time.sleep(2)
            return self._send(PNG, "image/png")
        if p == "/big.png":
            return self._send(b"x" * 5000, "image/png")
        if p == "/jump.png":
            self.send_response(302)
            self.send_header("Location", "http://localhost:%d/ok.png" % self.server.server_address[1])
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def _send(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ImageDownloadTest(unittest.TestCase):
    def setUp(self):
        _Handler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.tmp = tempfile.mkdtemp(prefix="images-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = article_store.ArticleStore(self.tmp)
        self.addCleanup(self.store.close)
        self.store.upsert_discovered(AID, "https://investanchors.com/user/vip_contents/%d" % AID, "T")
        self.sleeps = []

    def _add(self, *paths):
        for i, p in enumerate(paths, 1):
            self.store.add_image(AID, i, p if "://" in p else self.base + p)

    def _dl(self, **kw):
        kw.setdefault("allowed_hosts", ("127.0.0.1",))
        return AI.download_images(self.store, AID, self.tmp, sleeper=self.sleeps.append,
                                  rng=random.Random(3), **kw)

    def test_downloads_to_fixed_safe_path_and_records_relative_path(self):
        self._add("/ok.png")
        r = self._dl()
        self.assertEqual((r["downloaded"], r["failed"]), ([1], []))
        im = self.store.list_images(AID)[0]
        self.assertEqual(im["file_path"], os.path.join("articles_images", str(AID), "1.png"))
        with open(os.path.join(self.tmp, im["file_path"]), "rb") as f:
            self.assertEqual(f.read(), PNG)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "articles_images", str(AID))), ["1.png"])  # 無 .part

    def test_no_cookie_or_auth_header_is_sent(self):
        self._add("/ok.png")
        self._dl()
        self.assertEqual(_Handler.requests, [("/ok.png", None, None)])

    def test_gap_between_images_in_range_and_none_before_first(self):
        self._add("/ok.png", "/ok.png", "/ok.png")
        self._dl()
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(5 <= s <= 15 for s in self.sleeps))

    def test_single_failures_only_mark_that_image_and_leave_file_path_null(self):
        self._add("/404.png", "/ok.png", "/evil.exe", "/page.html", "/slow.png")
        r = self._dl(timeout=1)
        self.assertEqual(r["downloaded"], [2])
        self.assertEqual(dict(r["failed"]), {1: "http_404", 3: "bad_extension", 4: "bad_extension", 5: "network"})
        paths = dict((i["seq"], i["file_path"]) for i in self.store.list_images(AID))
        self.assertIsNone(paths[1])
        self.assertIsNotNone(paths[2])
        self.assertEqual([i["seq"] for i in self.store.images_missing_file()], [1, 3, 4, 5])

    def test_retry_next_run_only_fetches_missing_ones(self):
        self._add("/ok.png", "/404.png")
        self._dl()
        _Handler.requests = []
        self._dl()
        self.assertEqual([p for p, _, _ in _Handler.requests], ["/404.png"])

    def test_extension_from_content_type_when_url_has_none(self):
        self._add("/noext")
        self._dl()
        self.assertTrue(self.store.list_images(AID)[0]["file_path"].endswith("1.png"))

    def test_too_large_is_rejected(self):
        self._add("/big.png")
        r = self._dl(max_bytes=100)
        self.assertEqual(r["failed"], [(1, "too_large")])
        self.assertIsNone(self.store.list_images(AID)[0]["file_path"])

    def test_foreign_host_and_non_http_schemes_refused_without_request(self):
        self._add("https://evil.example/x.png", "file:///etc/passwd", "ftp://x/y.png")
        r = self._dl()
        self.assertEqual(sorted(reason for _, reason in r["failed"]), ["host_not_allowed"] * 3)
        self.assertEqual(_Handler.requests, [])

    def test_cross_host_redirect_refused(self):
        self._add("/jump.png")
        r = self._dl()
        self.assertEqual(r["failed"][0][1], "http_302")
        self.assertEqual([p for p, _, _ in _Handler.requests], ["/jump.png"])

    def test_path_never_contains_url_derived_segments(self):
        self._add("/ok.png?../../etc/passwd")
        self._dl()
        rel = self.store.list_images(AID)[0]["file_path"]
        self.assertEqual(rel, os.path.join("articles_images", str(AID), "1.png"))
        self.assertNotIn("..", rel)

    def test_default_allowed_host_is_investanchors_only(self):
        self.assertEqual(AI.DEFAULT_ALLOWED_HOSTS, ("investanchors.com",))
        self.assertTrue(AI._host_allowed("https://www.investanchors.com/a.png", AI.DEFAULT_ALLOWED_HOSTS))
        self.assertFalse(AI._host_allowed("https://investanchors.com.evil.com/a.png", AI.DEFAULT_ALLOWED_HOSTS))


if __name__ == "__main__":
    unittest.main()
