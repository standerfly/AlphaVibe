"""T010：YouTube 中繼資料擷取——解析函式固定樣本、SSRF 防護、不猜測。測試不連網。"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import external_content_metadata as M  # noqa: E402

VID = "dQw4w9WgXcQ"
CANON = "https://www.youtube.com/watch?v=" + VID
OEMBED_OK = json.dumps({"title": "範例影片", "author_name": "範例頻道", "type": "video"})
PAGE_OK = 'xx<script>{"uploadDate":"2009-10-24T23:57:33-07:00","name":"x"}</script>'


class FakeFetcher(object):
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for prefix, val in self.pages.items():
            if url.startswith(prefix):
                if isinstance(val, Exception):
                    raise val
                return val
        raise RuntimeError("unexpected url " + url)


class ParseTest(unittest.TestCase):
    def test_parse_oembed(self):
        self.assertEqual(M.parse_oembed(OEMBED_OK), ("範例影片", "範例頻道"))
        self.assertEqual(M.parse_oembed('{"title":"  ","author_name":"a"}'), (None, "a"))
        for bad in ("不是 json", "[1,2]"):
            with self.assertRaises(M.MetadataError):
                M.parse_oembed(bad)

    def test_parse_upload_date(self):
        # 2009-10-24T23:57:33-07:00 = UTC 2009-10-25 06:57 = 台灣 2009-10-25（PO 決定換算成台灣日期）
        self.assertEqual(M.parse_upload_date(PAGE_OK), "2009-10-25")
        self.assertEqual(M.parse_upload_date('"uploadDate" : "2026-11-19"'), "2026-11-19")
        self.assertIsNone(M.parse_upload_date("沒有日期"))
        self.assertIsNone(M.parse_upload_date('"uploadDate":"2026-02-30T00:00:00"'))
        self.assertIsNone(M.parse_upload_date(None))

    def test_upload_date_converted_to_taiwan_time(self):
        """PO 2026-11-25 決定：YouTube 的 uploadDate（美國太平洋時間）換算成台灣時間的日期。
        三個案例取自 PO 提供的真實影片（原始字串逐字）。"""
        def page(v):
            return 'x{"uploadDate":"%s"}y' % v
        # 02:04 PST → 台灣當天 18:04，日期不變
        self.assertEqual(M.parse_upload_date(page("2026-11-24T02:04:49-08:00")), "2026-11-24")
        # 21:00 PDT → 台灣隔天 12:00，日期 +1（PO 在 YouTube 看到 4/14）
        self.assertEqual(M.parse_upload_date(page("2026-04-13T21:00:19-07:00")), "2026-04-14")
        self.assertEqual(M.parse_upload_date(page("2026-01-07T02:24:05-08:00")), "2026-01-07")

    def test_upload_date_offset_variants(self):
        def page(v):
            return '"uploadDate":"%s"' % v
        # UTC：16:30Z = 台灣隔天 00:30
        self.assertEqual(M.parse_upload_date(page("2026-05-01T16:30:00Z")), "2026-05-02")
        self.assertEqual(M.parse_upload_date(page("2026-05-01T15:59:59Z")), "2026-05-01")
        # 本來就是台灣時間
        self.assertEqual(M.parse_upload_date(page("2026-05-01T23:59:59+08:00")), "2026-05-01")
        self.assertEqual(M.parse_upload_date(page("2026-05-01T00:00:00+0800")), "2026-05-01")
        # 跨月、跨年
        self.assertEqual(M.parse_upload_date(page("2026-12-31T20:00:00-08:00")), "2027-01-01")
        self.assertEqual(M.parse_upload_date(page("2026-02-28T22:00:00-08:00")), "2026-03-01")
        # 含小數秒
        self.assertEqual(M.parse_upload_date(page("2026-05-01T16:30:00.123Z")), "2026-05-02")
        # 只有日期：原樣；有時間沒時區：原樣取日期部分
        self.assertEqual(M.parse_upload_date(page("2026-05-01")), "2026-05-01")
        self.assertEqual(M.parse_upload_date(page("2026-05-01T23:00:00")), "2026-05-01")

    def test_upload_date_malformed_returns_none(self):
        def page(v):
            return '"uploadDate":"%s"' % v
        for bad in ("2026-02-30T10:00:00-08:00", "2026-13-01T10:00:00Z",
                    "2026-05-01T25:00:00Z", "2026-05-01T10:61:00Z",
                    "2026-05-01T10:00:00+99:00", "2026-05-01T10:00:00+08:99"):
            self.assertIsNone(M.parse_upload_date(page(bad)), bad)


class UrlGuardTest(unittest.TestCase):
    def test_allowed_hosts_exact(self):
        for u in ("https://www.youtube.com/watch?v=" + VID, "https://youtu.be/" + VID,
                  "https://m.youtube.com/watch?v=" + VID, "https://music.youtube.com/watch?v=" + VID,
                  "https://youtube.com/shorts/" + VID):
            M.check_allowed_url(u)
            self.assertEqual(M.canonical_urls(u)[1], CANON)

    def test_rejected_urls(self):
        for u in ("http://www.youtube.com/watch?v=" + VID,            # 非 https
                  "https://youtube.com.evil.com/watch?v=" + VID,      # 後綴比對
                  "https://evil.com/youtube.com/watch?v=" + VID,
                  "https://www.youtube.com.evil.com/watch?v=" + VID,
                  "https://user@evil.com/watch?v=" + VID,
                  "https://127.0.0.1/watch?v=" + VID,
                  "file:///etc/passwd", "不是網址"):
            with self.assertRaises(M.MetadataError, msg=u):
                M.canonical_urls(u)

    def test_no_video_id(self):
        with self.assertRaises(M.MetadataError):
            M.canonical_urls("https://www.youtube.com/watch?v=short")

    def test_canonical_rebuild_drops_original_junk(self):
        _, canon, oembed = M.canonical_urls("https://youtu.be/%s?si=abc&t=30&evil=http://x" % VID)
        self.assertEqual(canon, CANON)
        self.assertTrue(oembed.startswith("https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D" + VID))
        self.assertNotIn("evil", oembed)


class FetchTest(unittest.TestCase):
    def test_success_only_canonical_urls_fetched(self):
        f = FakeFetcher({"https://www.youtube.com/oembed": OEMBED_OK, CANON: PAGE_OK})
        r = M.fetch_youtube_metadata("https://youtu.be/%s?si=zzz" % VID, fetcher=f)
        self.assertEqual((r["title"], r["author"], r["date"]), ("範例影片", "範例頻道", "2009-10-25"))  # PAGE_OK 為太平洋時間 10-24 23:57 → 台灣 10-25
        self.assertEqual(r["missing"], [])
        self.assertEqual(len(f.calls), 2)
        for c in f.calls:
            self.assertTrue(c.startswith("https://www.youtube.com/"))
            self.assertNotIn("si=zzz", c)

    def test_missing_fields_reported_not_guessed(self):
        f = FakeFetcher({"https://www.youtube.com/oembed": OEMBED_OK, CANON: "<html>沒有日期</html>"})
        r = M.fetch_youtube_metadata("https://www.youtube.com/watch?v=" + VID, fetcher=f)
        self.assertIsNone(r["date"])
        self.assertEqual(r["missing"], ["date"])
        self.assertEqual((r["title"], r["author"]), ("範例影片", "範例頻道"))

    def test_all_fail_all_missing(self):
        f = FakeFetcher({"https://www.youtube.com/": IOError("斷線")})
        r = M.fetch_youtube_metadata("https://www.youtube.com/watch?v=" + VID, fetcher=f)
        self.assertEqual(r["missing"], ["title", "author", "date"])
        self.assertTrue(r["notes"])

    def test_oversized_fake_response_rejected(self):
        big = "x" * (M.MAX_RESPONSE_BYTES + 1)
        f = FakeFetcher({"https://www.youtube.com/oembed": big, CANON: PAGE_OK})
        r = M.fetch_youtube_metadata("https://www.youtube.com/watch?v=" + VID, fetcher=f)
        self.assertIn("title", r["missing"])
        self.assertEqual(r["date"], "2009-10-25")  # 台灣時間（PO 2026-11-25 決定）

    def test_bad_url_raises_and_fetcher_untouched(self):
        f = FakeFetcher({})
        for u in ("http://www.youtube.com/watch?v=" + VID, "https://evil.com/watch?v=" + VID):
            with self.assertRaises(M.MetadataError):
                M.fetch_youtube_metadata(u, fetcher=f)
        self.assertEqual(f.calls, [])


class NetworkLayerTest(unittest.TestCase):
    def test_read_limited(self):
        self.assertEqual(M.read_limited(io.BytesIO(b"abc"), 3), b"abc")
        with self.assertRaises(M.MetadataError):
            M.read_limited(io.BytesIO(b"abcd"), 3)

    def test_redirect_cross_host_rejected(self):
        h = M._SameHostRedirect()
        import urllib.request
        req = urllib.request.Request(CANON)
        for new in ("https://evil.com/x", "http://www.youtube.com/x", "https://youtube.com.evil.com/x"):
            with self.assertRaises(M.MetadataError, msg=new):
                h.redirect_request(req, None, 302, "Found", {}, new)
        out = h.redirect_request(req, None, 302, "Found", {}, "https://m.youtube.com/watch?v=" + VID)
        self.assertEqual(out.full_url, "https://m.youtube.com/watch?v=" + VID)

    def test_default_fetch_uses_limit_and_timeout_without_network(self):
        opened = {}

        class Resp(io.BytesIO):
            pass

        class Opener(object):
            def open(self, req, timeout=None):
                opened["url"] = req.full_url
                opened["timeout"] = timeout
                return Resp(b"x" * (M.MAX_RESPONSE_BYTES + 1))
        with mock.patch.object(M, "_build_opener", return_value=Opener()):
            with self.assertRaises(M.MetadataError) as cm:
                M.default_fetch(CANON)
        self.assertIn("大小上限", str(cm.exception))
        self.assertEqual(opened["timeout"], 10)
        with mock.patch.object(M, "_build_opener") as bo:
            with self.assertRaises(M.MetadataError):
                M.default_fetch("https://evil.com/")
            bo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
