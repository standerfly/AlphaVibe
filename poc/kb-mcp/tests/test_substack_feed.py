"""T009：feed 請求、回應判別、解析、網址正規化、robots 與錯誤代碼（data-model §2.4、research R6）。

全部用假 HTTP（夾具 FakeHttp），**不發出任何真實網路請求**。
"""
import datetime
import os
import socket
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_feed as FEED  # noqa: E402
import substack_store as S  # noqa: E402

FEED_URL = "https://%s/feed" % F.DEFAULT_HOST
ROBOTS_URL = "https://%s/robots.txt" % F.DEFAULT_HOST


def sample_feed(n=2, **item_kwargs):
    items = []
    for i in range(1, n + 1):
        items.append(F.feed_item(slug="%s-%d" % (F.SLUG_MARK, i), **item_kwargs))
    return F.make_feed(items)


class RequestTest(unittest.TestCase):
    def setUp(self):
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)

    def test_user_agent_is_exact_and_no_cookie_or_auth(self):
        self.assertEqual(FEED.UA, "Mozilla/5.0 (compatible; personal-feed-reader/1.0)")
        headers = FEED.build_headers()
        self.assertEqual(headers.get("User-Agent"), FEED.UA)
        lowered = {k.lower() for k in headers}
        self.assertNotIn("cookie", lowered)
        self.assertNotIn("authorization", lowered)

    def test_if_none_match_uses_raw_etag_including_weak_marker(self):
        headers = FEED.build_headers('W/"abc123"')
        self.assertEqual(headers.get("If-None-Match"), 'W/"abc123"')
        self.assertNotIn("If-None-Match", FEED.build_headers(None))

    def test_request_timeout_takes_min_of_default_and_remaining(self):
        self.assertEqual(FEED.request_timeout(None), FEED.FEED_TIMEOUT)
        self.assertEqual(FEED.request_timeout(100), FEED.FEED_TIMEOUT)
        self.assertEqual(FEED.request_timeout(5), 5)
        self.assertEqual(FEED.request_timeout(0), 0)

    def test_fetch_feed_passes_headers_and_timeout(self):
        self.http.route(FEED_URL, F.ok(sample_feed(1), etag='W/"e1"'))
        result = FEED.fetch_feed(self.http, FEED_URL, etag='W/"old"', remaining=7)
        self.assertEqual(result["outcome"], "ok_200")
        self.assertEqual(result["etag"], 'W/"e1"')
        self.assertEqual(len(result["items"]), 1)
        req = self.http.requests[-1]
        self.assertEqual(req["timeout"], 7)
        self.assertEqual(req["headers"]["If-None-Match"], 'W/"old"')
        self.assertEqual(req["headers"]["User-Agent"], FEED.UA)
        self.assertNotIn("Cookie", req["headers"])
        self.assertNotIn("Authorization", req["headers"])


class ClassifyResponseTest(unittest.TestCase):
    def test_outcome_codes(self):
        xml = sample_feed(1)
        cases = [
            (200, {"Content-Type": "application/rss+xml"}, xml, "ok_200"),
            (304, {}, "", "not_modified"),
            (403, {}, "nope", "blocked_403"),
            (429, {}, "slow down", "rate_limited_429"),
            (200, {"Content-Type": "text/html; charset=utf-8"}, "<p>x</p>", "challenge_html"),
            (200, {"Content-Type": "application/rss+xml"}, F.CHALLENGE_HTML, "challenge_html"),
            (200, {"Content-Type": "application/rss+xml"}, "<html><body>x</body></html>",
             "challenge_html"),
            (500, {}, "", "http_500"),
            (301, {}, "", "http_301"),
        ]
        for status, headers, body, want in cases:
            self.assertEqual(FEED.classify_response(status, headers, body), want,
                             "status=%s headers=%s" % (status, headers))

    def test_too_large(self):
        body = b"x" * (FEED.MAX_FEED_BYTES + 1)
        self.assertEqual(FEED.classify_response(200, {"Content-Type": "application/rss+xml"},
                                                body), "too_large")
        self.assertEqual(FEED.MAX_FEED_BYTES, 5 * 1024 * 1024)

    def test_fetch_feed_outcomes_from_fake_http(self):
        clock = F.FakeClock()
        for action, want in [(F.not_modified(etag='W/"x"'), "not_modified"),
                             (F.status(403), "blocked_403"),
                             (F.status(429), "rate_limited_429"),
                             (F.challenge(), "challenge_html"),
                             (F.status(500), "http_500"),
                             (F.timeout(), "timeout"),
                             (F.network(), "network"),
                             (F.too_large(), "too_large"),
                             (F.redirect("https://evil.example.com/feed"), "redirect_refused")]:
            http = F.FakeHttp(clock)
            http.route(FEED_URL, action)
            result = FEED.fetch_feed(http, FEED_URL)
            self.assertEqual(result["outcome"], want)
            self.assertIsNone(result.get("items"))

    def test_hang_until_timeout_consumes_budget(self):
        clock = F.FakeClock()
        http = F.FakeHttp(clock)
        http.route(FEED_URL, F.hang())
        before = clock.monotonic()
        result = FEED.fetch_feed(http, FEED_URL, remaining=12)
        self.assertEqual(result["outcome"], "timeout")
        self.assertEqual(clock.monotonic() - before, 12)

    def test_redirect_allowed_rules(self):
        self.assertTrue(FEED.redirect_allowed(FEED_URL, FEED_URL))
        self.assertTrue(FEED.redirect_allowed(FEED_URL, "https://%s/feed/" % F.DEFAULT_HOST))
        self.assertTrue(FEED.redirect_allowed(FEED_URL, "https://anything.substack.com/feed"))
        self.assertFalse(FEED.redirect_allowed(FEED_URL, "https://evil.example.com/feed"))
        self.assertFalse(FEED.redirect_allowed(FEED_URL, "http://%s/feed" % F.DEFAULT_HOST))


class ParseTest(unittest.TestCase):
    def test_rejects_dtd_before_parsing(self):
        with self.assertRaises(FEED.FeedParseError):
            FEED.parse_feed(F.MALICIOUS_FEED_XML)
        with self.assertRaises(FEED.FeedParseError):
            FEED.parse_feed('<!ENTITY x "y"><rss><channel></channel></rss>')
        result = FEED.fetch_feed(F.FakeHttp(), FEED_URL)
        self.assertIsNotNone(result)

    def test_broken_xml_is_parse_error(self):
        with self.assertRaises(FEED.FeedParseError):
            FEED.parse_feed("<rss><channel><item></rss>")
        http = F.FakeHttp()
        http.route(FEED_URL, F.ok("<rss><channel><item></rss>"))
        self.assertEqual(FEED.fetch_feed(http, FEED_URL)["outcome"], "parse_error")

    def test_parses_all_item_fields(self):
        item = F.feed_item(slug="%s-9" % F.SLUG_MARK,
                           enclosure=("image/jpeg", "https://%s/%s-cover.jpg"
                                      % (F.IMAGE_HOST, F.IMG_URL_MARK)))
        items = FEED.parse_feed(F.make_feed([item]))
        self.assertEqual(len(items), 1)
        got = items[0]
        self.assertEqual(got["guid"], item["guid"])
        self.assertEqual(got["link"], item["link"])
        self.assertEqual(got["title"], item["title"])
        self.assertIsInstance(got["published_at"], datetime.datetime)
        self.assertEqual(got["published_at"].utcoffset(), datetime.timedelta(hours=8))
        self.assertIn(F.BODY_MARK, got["content_html"])
        self.assertEqual(got["description"], item["description"])
        self.assertEqual(got["enclosure_type"], "image/jpeg")
        self.assertEqual(got["enclosure_url"], item["enclosure"][1])

    def test_unparsable_pubdate_returns_none(self):
        item = F.feed_item(pub_date_raw="昨天下午")
        got = FEED.parse_feed(F.make_feed([item]))[0]
        self.assertIsNone(got["published_at"])
        item = F.feed_item(published=None)
        got = FEED.parse_feed(F.make_feed([item]))[0]
        self.assertIsNone(got["published_at"])

    def test_missing_content_encoded_is_none(self):
        item = F.feed_item(content_html=None)
        got = FEED.parse_feed(F.make_feed([item]))[0]
        self.assertIsNone(got["content_html"])


class NormalizeLinkTest(unittest.TestCase):
    def test_normalizes(self):
        base = "https://host.example.com/p/slug"
        cases = {
            "https://host.example.com/p/slug": base,
            "http://host.example.com/p/slug": base,
            "https://HOST.Example.COM/p/slug": base,
            "https://host.example.com/p/slug/": base,
            "https://host.example.com/p/slug?utm_source=x": base,
            "https://host.example.com/p/slug#intro": base,
            "https://host.example.com/p/slug/?a=1#b": base,
        }
        for raw, want in cases.items():
            self.assertEqual(FEED.normalize_link(raw), want, raw)

    def test_two_url_forms_collapse_to_one(self):
        a = FEED.normalize_link("https://x.substack.com/p/aaa?utm_campaign=1")
        b = FEED.normalize_link("http://X.substack.com/p/aaa/")
        self.assertEqual(a, b)


class RobotsTest(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)
        self.clock = F.FakeClock("2026-11-20 22:00:00")
        self.http = F.FakeHttp(self.clock)
        self.gate = FEED.RobotsGate(self.store, self.http, self.clock)

    def test_allows_and_caches_for_24h(self):
        self.http.route(ROBOTS_URL, F.ok("User-agent: *\nAllow: /\n", content_type="text/plain"))
        ok, outcome = self.gate.allowed(FEED_URL)
        self.assertTrue(ok)
        self.assertIsNone(outcome)
        self.assertEqual(self.http.count(ROBOTS_URL), 1)
        cached = self.store.get_robots_cache(F.DEFAULT_HOST)
        self.assertIsNotNone(cached)

        self.clock.advance(23 * 3600)
        self.assertTrue(self.gate.allowed(FEED_URL)[0])
        self.assertEqual(self.http.count(ROBOTS_URL), 1, "24 小時內用快取，不重打")

        self.clock.advance(2 * 3600)
        self.assertTrue(self.gate.allowed(FEED_URL)[0])
        self.assertEqual(self.http.count(ROBOTS_URL), 2, "超過 24 小時要重新取")

    def test_disallow(self):
        self.http.route(ROBOTS_URL, F.ok("User-agent: *\nDisallow: /feed\n",
                                         content_type="text/plain"))
        ok, outcome = self.gate.allowed(FEED_URL)
        self.assertFalse(ok)
        self.assertEqual(outcome, "robots_disallow")

    def test_unavailable_falls_back_to_cache_within_7_days(self):
        self.http.route(ROBOTS_URL, F.ok("User-agent: *\nAllow: /\n", content_type="text/plain"))
        self.assertTrue(self.gate.allowed(FEED_URL)[0])

        self.clock.advance(3 * 86400)
        self.http.routes[ROBOTS_URL] = [F.network()]
        ok, outcome = self.gate.allowed(FEED_URL)
        self.assertTrue(ok, "7 天內的舊快取可用")
        self.assertIsNone(outcome)

        self.clock.advance(5 * 86400)
        self.http.routes[ROBOTS_URL] = [F.timeout()]
        ok, outcome = self.gate.allowed(FEED_URL)
        self.assertFalse(ok)
        self.assertEqual(outcome, "robots_unavailable")

    def test_unavailable_without_cache(self):
        self.http.route(ROBOTS_URL, F.timeout())
        ok, outcome = self.gate.allowed(FEED_URL)
        self.assertFalse(ok)
        self.assertEqual(outcome, "robots_unavailable")

    def test_robots_request_is_not_a_feed_request(self):
        self.http.route(ROBOTS_URL, F.ok("User-agent: *\nAllow: /\n", content_type="text/plain"))
        self.gate.allowed(FEED_URL)
        self.assertEqual(self.http.count(FEED_URL), 0)
        self.assertEqual(self.http.count(ROBOTS_URL), 1)

    def test_robots_uses_same_user_agent(self):
        self.http.route(ROBOTS_URL, F.ok("User-agent: *\nAllow: /\n", content_type="text/plain"))
        self.gate.allowed(FEED_URL)
        self.assertEqual(self.http.headers_for(ROBOTS_URL)[0]["User-Agent"], FEED.UA)


class ErrorCodeTest(unittest.TestCase):
    SECRET = "123456789:AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqR"
    URL = "https://host.example.com/p/%s-secret" % F.SLUG_MARK

    def _exc_text(self):
        return "boom token=%s url=%s" % (self.SECRET, self.URL)

    def test_error_code_returns_code_only(self):
        samples = [
            (socket.timeout(self._exc_text()), "timeout"),
            (urllib.error.URLError(self._exc_text()), "network"),
            (OSError(self._exc_text()), "network"),
            (FEED.RedirectRefused(self._exc_text()), "redirect_refused"),
            (FEED.FeedTooLarge(self._exc_text()), "too_large"),
            (FEED.FeedParseError(self._exc_text()), "parse_error"),
            (ValueError(self._exc_text()), "error"),
        ]
        for exc, want in samples:
            code = FEED.error_code(exc)
            self.assertEqual(code, want, repr(exc))
            self.assertNotIn(self.SECRET, code)
            self.assertNotIn(F.SLUG_MARK, code)
            self.assertNotIn("token", code)

    def test_http_error_maps_to_status_code(self):
        exc = urllib.error.HTTPError(self.URL, 503, self._exc_text(), {}, None)
        code = FEED.error_code(exc)
        self.assertEqual(code, "http_503")
        self.assertNotIn(self.SECRET, code)

    def test_all_codes_are_in_the_declared_set(self):
        for code in ("ok_200", "not_modified", "blocked_403", "rate_limited_429",
                     "challenge_html", "timeout", "network", "parse_error", "too_large",
                     "redirect_refused", "robots_disallow", "robots_unavailable",
                     "skipped_interval"):
            self.assertIn(code, FEED.OUTCOMES, code)


if __name__ == "__main__":
    unittest.main()
