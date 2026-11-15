"""010 Phase 0 探查工具測試：全部使用假資料／本機假網站，不連真實網站、不讀真鑰匙圈。"""
import datetime
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_probe  # noqa: E402
import keychain_secrets  # noqa: E402

EMAIL = "po@example.com"
PASSWORD = "pw-secret-123"
NOW = datetime.datetime(2026, 11, 15, 23, 0, 0)
IA = keychain_secrets.INVESTANCHORS_SERVICE


def _secrets(wrong_password=False):
    def get(account, runner=None, service=None):
        if service == IA:
            return {"email": EMAIL, "password": "bad" if wrong_password else PASSWORD}[account]
        return {"gmail-address": "me@gmail.example", "gmail-app-password": "app-pw-xyz"}[account]
    return get


# ------------------------------------------------------------------ 單元測試

class GateTest(unittest.TestCase):
    def test_refuses_without_confirm_flag_and_touches_nothing(self):
        def boom(*a, **k):
            raise AssertionError("must not be called")
        out = io.StringIO()
        rc = article_probe.run(["--data-dir", tempfile.gettempdir()], get_secret=boom,
                               scraper_runner=boom, mail_prober=boom, out=out)
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-po-present", out.getvalue())

    def test_short_delay_refused_unless_test_override(self):
        def boom(*a, **k):
            raise AssertionError("must not be called")
        out = io.StringIO()
        rc = article_probe.run(["--confirm-po-present"], get_secret=boom, scraper_runner=boom,
                               out=out, delay_ms=(100, 200))
        self.assertEqual(rc, 2)

    def test_missing_secret_stops_before_scraper(self):
        def get(account, runner=None, service=None):
            raise keychain_secrets.SecretNotFound(account)
        def boom(*a, **k):
            raise AssertionError("scraper must not run")
        out = io.StringIO()
        rc = article_probe.run(["--confirm-po-present", "--skip-mail"], get_secret=get,
                               scraper_runner=boom, out=out)
        self.assertEqual(rc, 1)
        self.assertNotIn(PASSWORD, out.getvalue())


class RunnerHygieneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="probe-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _summary(self, **over):
        s = {"type": "summary", "counters": {"logins": 1, "list_pages": 3, "articles_opened": 2},
             "logged_in": True, "logout_found": True, "logged_out": True,
             "logout_verified": True, "blocked": False, "stage_error": None}
        s.update(over)
        return s

    def _run(self, objs, extra=None):
        seen = {}
        def runner(payload):
            seen["payload"] = payload
            return objs
        out = io.StringIO()
        rc = article_probe.run(["--data-dir", self.tmp, "--confirm-po-present", "--skip-mail"]
                               + (extra or []), get_secret=_secrets(), scraper_runner=runner,
                               now=lambda: NOW, out=out, allow_short_delay=True,
                               delay_ms=(10, 20))
        return rc, out.getvalue(), seen

    def test_payload_carries_hard_limits_and_credentials_only_in_payload(self):
        rc, out, seen = self._run([self._summary()])
        self.assertEqual(rc, 0)
        p = seen["payload"]
        self.assertEqual((p["max_list_pages"], p["max_articles"]), (3, 2))
        self.assertEqual((p["email"], p["password"]), (EMAIL, PASSWORD))
        self.assertNotIn(PASSWORD, out)
        self.assertNotIn(EMAIL, out)

    def test_default_runner_sends_secrets_via_stdin_not_argv_or_env(self):
        class FakeProc:
            def __init__(self):
                self.written = b""
                self.stdin = self
                self.stdout = iter([json.dumps({"type": "summary"}).encode() + b"\n"])
            def write(self, b):
                self.written += b
            def close(self):
                pass
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass
        proc = FakeProc()
        with mock.patch.object(article_probe.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(article_probe.os.path, "exists", return_value=True):
            objs = article_probe.default_scraper_runner(
                {"mode": "probe", "email": EMAIL, "password": PASSWORD})
        args, kwargs = popen.call_args
        self.assertNotIn(PASSWORD, " ".join(args[0]))
        self.assertNotIn(EMAIL, " ".join(args[0]))
        self.assertNotIn("env", kwargs)
        self.assertEqual(kwargs["stdin"], article_probe.subprocess.PIPE)
        self.assertIn(PASSWORD.encode(), proc.written)
        self.assertEqual(objs[0]["type"], "summary")

    def test_limit_violation_is_flagged_and_fails(self):
        rc, out, _ = self._run([self._summary(
            counters={"logins": 2, "list_pages": 4, "articles_opened": 3})])
        self.assertEqual(rc, 1)
        self.assertIn("超過硬上限", out)
        path = out.split("探查報告：")[1].splitlines()[0]
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(sorted(report["limit_violations"]),
                         ["articles", "list_pages", "logins"])

    def test_unverified_logout_fails_with_manual_logout_warning(self):
        rc, out, _ = self._run([self._summary(logout_verified=False)])
        self.assertEqual(rc, 1)
        self.assertIn("請 PO 立刻手動登出", out)

    def test_no_logout_mechanism_stops_and_reports(self):
        rc, out, _ = self._run([self._summary(
            logout_found=False, logged_out=False, logout_verified=False,
            stage_error="no_logout_mechanism")])
        self.assertEqual(rc, 1)
        self.assertIn("找不到伺服器端登出機制", out)

    def test_missing_summary_is_failure(self):
        rc, out, _ = self._run([{"type": "fact", "step": "login", "data": {}}])
        self.assertEqual(rc, 1)
        self.assertIn("手動登出", out)

    def test_report_file_is_private_and_under_probe_dir(self):
        rc, out, _ = self._run([self._summary()])
        path = out.split("探查報告：")[1].splitlines()[0]
        self.assertEqual(os.path.dirname(path),
                         os.path.join(os.path.abspath(self.tmp), "articles_probe"))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class SanitizeTest(unittest.TestCase):
    def test_long_string_rejected(self):
        with self.assertRaises(article_probe.ProbeError):
            article_probe.sanitize({"x": "字" * 300}, [])

    def test_credential_in_report_rejected(self):
        with self.assertRaises(article_probe.ProbeError):
            article_probe.sanitize({"x": ["ok", "has " + PASSWORD + " inside"]}, [PASSWORD])
        with self.assertRaises(article_probe.ProbeError):
            article_probe.sanitize({"x": "abc"}, ["abc"])

    def test_clean_report_passes(self):
        article_probe.sanitize({"a": [1, 2, {"b": "短字串"}]}, [PASSWORD, EMAIL])


class EstimateTest(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 15)

    def test_half_year_estimate_from_rate_and_announcements_excluded(self):
        items = [{"article_id": 100 + i, "date": (self.TODAY - datetime.timedelta(days=i * 2))
                  .isoformat(), "is_announcement": False} for i in range(10)]
        items.append({"article_id": 999, "date": "2027-01-01", "is_announcement": True})
        est = article_probe.estimate_half_year(items, self.TODAY)
        self.assertEqual(est["dated_items"], 10)
        self.assertEqual(est["items_within_half_year"], 10)
        # 10 篇 / 19 天 * 183 ≈ 96
        self.assertAlmostEqual(est["estimated_half_year_count"], 96, delta=2)

    def test_month_day_only_infers_year(self):
        items = [{"article_id": 1, "md": "11-10", "date": None},
                 {"article_id": 2, "md": "11-01", "date": None},
                 {"article_id": 3, "md": "12-30", "date": None}]  # 去年底，不是未來
        est = article_probe.estimate_half_year(items, self.TODAY)
        self.assertEqual(est["observed_from"], "2025-12-30")

    def test_insufficient_data_gives_none(self):
        est = article_probe.estimate_half_year([{"article_id": 1, "date": "2026-11-14"}],
                                               self.TODAY)
        self.assertIsNone(est["estimated_half_year_count"])

    def test_id_monotonic(self):
        mk = lambda i, d: {"article_id": i, "date": d}
        up = [mk(1, "2026-11-01"), mk(2, "2026-11-05"), mk(3, "2026-11-09")]
        self.assertTrue(article_probe.check_id_monotonic(up, self.TODAY))
        self.assertFalse(article_probe.check_id_monotonic(
            [mk(5, "2026-11-01"), mk(2, "2026-11-05"), mk(3, "2026-11-09")], self.TODAY))
        self.assertEqual(article_probe.check_id_monotonic(up[:2], self.TODAY),
                         "insufficient_data")


class MailProbeTest(unittest.TestCase):
    def test_classify_links_never_returns_full_urls(self):
        html = ('<a href="https://investanchors.com/user/vip_contents/123">a</a>'
                '<a href="https://click.mailer.investanchors.com/t?uid=SECRETTOKEN">b</a>'
                '<a href="https://track.example.net/x?u=SECRETTOKEN">c</a>'
                '<a href="mailto:x@y.z">d</a>')
        got = article_probe.classify_mail_links(html)
        self.assertEqual((got["direct_article"], got["same_site_other"],
                          got["external_redirect"]), (1, 1, 1))
        self.assertNotIn("SECRETTOKEN", json.dumps(got))

    def _mail(self, sender, body):
        m = MIMEMultipart("alternative")
        m["From"] = "定錨 <%s>" % sender
        m["Subject"] = "新文章"
        m.attach(MIMEText(body, "html", "utf-8"))
        return m.as_bytes()

    def _imap(self, raw):
        class Fake:
            def login(self, u, p):
                return "OK", [b""]
            def list(self):
                return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']
            def select(self, name, readonly=False):
                self.readonly = readonly
                return "OK", [b"1"]
            def uid(self, cmd, *args):
                if cmd == "SEARCH":
                    return "OK", [b"1"]
                self.spec = args[1]
                return "OK", [(b"1 (UID 1)", raw), b")"]
            def logout(self):
                pass
        return Fake()

    def test_probe_mail_readonly_peek_and_classifies(self):
        raw = self._mail(article_probe.MAIL_SENDER,
                         '<a href="https://investanchors.com/user/vip_contents/55">x</a>')
        fake = self._imap(raw)
        facts = article_probe.probe_mail("me@x", "pw", imap_factory=lambda: fake)
        self.assertTrue(fake.readonly)
        self.assertIn("PEEK", fake.spec)
        self.assertTrue(facts["sender_matches"])
        self.assertEqual(facts["direct_article"], 1)

    def test_spoofed_sender_links_are_not_classified(self):
        raw = self._mail("evil@phish.example",
                         '<a href="https://investanchors.com/user/vip_contents/55">x</a>')
        facts = article_probe.probe_mail("me@x", "pw", imap_factory=lambda: self._imap(raw))
        self.assertFalse(facts["sender_matches"])
        self.assertEqual(facts["direct_article"], 0)


class KeychainServiceTest(unittest.TestCase):
    class _P:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    def test_investanchors_service_used_in_command(self):
        calls = []
        def runner(args):
            calls.append(args)
            return self._P(0, "v\n")
        self.assertEqual(keychain_secrets.get_secret("email", runner, service=IA), "v")
        self.assertIn("stnd-investanchors", calls[0])
        self.assertIn("email", calls[0])

    def test_account_whitelist_is_per_service(self):
        with self.assertRaises(ValueError):
            keychain_secrets.get_secret("email", lambda a: self._P(0, "x"))  # 預設 service
        with self.assertRaises(ValueError):
            keychain_secrets.get_secret("pdf-password", lambda a: self._P(0, "x"), service=IA)

    def test_default_service_unchanged(self):
        calls = []
        keychain_secrets.get_secret("pdf-password", lambda a: (calls.append(a), self._P(0, "x"))[1])
        self.assertIn("stnd-statement-import", calls[0])


# ------------------------------------------------------------------ 端到端（本機假網站）

class FakeSite(object):
    def __init__(self, has_logout=True):
        self.has_logout = has_logout
        self.sessions = set()
        self.read = set()
        self.log = []
        self.lock = threading.Lock()
        self.server = None

    def start(self):
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _sid(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sid":
                        return v
                return None

            def _send(self, body, code=200, headers=None):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _login_page(self, err=False):
                return ('<html><body><form method="POST" action="/login">%s'
                        '<input type="email" name="email"><input type="password" name="password">'
                        '<label><input type="checkbox" name="remember" checked>記住我</label>'
                        '<button type="submit">登入</button></form></body></html>'
                        % ("<p>帳號或密碼錯誤</p>" if err else ""))

            def _list_page(self, page):
                rows = []
                if page == 1:
                    rows.append((9999, "【公告】SECRETTITLE公告", "2027-01-01"))
                    ids = [(1010 - i, "2026-11-%02d" % (14 - 2 * i)) for i in range(6)]
                else:
                    ids = [(1004 - i, "2026-10-%02d" % (28 - 2 * i)) for i in range(3)]
                rows += [(i, "SECRETTITLE %d" % i, d) for i, d in ids]
                trs = "".join(
                    '<tr><td><a href="/user/vip_contents/%d" style="font-weight:%s">%s</a>'
                    '</td><td>%s</td></tr>' % (i, "400" if i in site.read else "700", t, d)
                    for i, t, d in rows)
                nxt = ('<a rel="next" href="/user/vip_contents/investanchors_index?page=2">'
                       '下一頁</a>' if page == 1 else "")
                nav = ('<nav><a href="/user/vip_contents/investanchors_index?lv=0">總覽</a>'
                       '<a href="/user/vip_contents/investanchors_index?lv=1">週報</a>%s</nav>'
                       % ('<a href="/logout">登出</a>' if site.has_logout else ""))
                return "<html><body>%s<table>%s</table>%s</body></html>" % (nav, trs, nxt)

            def _article_page(self, aid):
                return ('<html><body><nav>%s</nav><h1>SECRETTITLE %d</h1><div class="post">'
                        '<p>SECRETBODY 第一段內容</p><p>SECRETBODY 第二段內容</p>'
                        '<img src="/img/%d/a1b2c3d4e5.png" alt="">'
                        '<img src="/img/%d/f6e5d4c3b2.png" alt="表"></div></body></html>'
                        % ('<a href="/logout">登出</a>' if site.has_logout else "", aid, aid, aid))

            def do_GET(self):
                u = urlparse(self.path)
                with site.lock:
                    site.log.append(("GET", u.path))
                    logged = self._sid() in site.sessions
                    if u.path == "/logout":
                        site.sessions.discard(self._sid())
                        return self._send("", 302, {"Location": "/user/vip_contents/investanchors_index",
                                                    "Set-Cookie": "sid=; Max-Age=0; Path=/"})
                    if u.path.startswith("/img/"):
                        return self._send("x")
                    if not logged:
                        return self._send(self._login_page())
                    if u.path == "/user/vip_contents/investanchors_index":
                        page = int((parse_qs(u.query).get("page") or ["1"])[0])
                        return self._send(self._list_page(page))
                    parts = u.path.rsplit("/", 1)
                    if parts[-1].isdigit():
                        site.read.add(int(parts[-1]))
                        return self._send(self._article_page(int(parts[-1])))
                    return self._send("not found", 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                with site.lock:
                    site.log.append(("POST", urlparse(self.path).path))
                    ok = (form.get("email") == [EMAIL] and form.get("password") == [PASSWORD])
                    if ok:
                        site.sessions.add("s1")
                        return self._send("", 302, {"Location": "/user/vip_contents/investanchors_index",
                                                    "Set-Cookie": "sid=s1; Path=/"})
                    return self._send(self._login_page(err=True))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def _browser_available():
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    return (os.path.exists(node)
            and os.path.isdir(os.path.join(article_probe.HERE, "scraper", "node_modules", "playwright"))
            and (os.path.exists("/Applications/Google Chrome.app")
                 or os.path.isdir(os.path.expanduser("~/Library/Caches/ms-playwright"))))


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class EndToEndFakeSiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="probe-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _probe(self, site, wrong_password=False):
        base = site.start()
        self.addCleanup(site.stop)
        out = io.StringIO()
        rc = article_probe.run(
            ["--data-dir", self.tmp, "--confirm-po-present", "--skip-mail", "--base-url", base],
            get_secret=_secrets(wrong_password), now=lambda: NOW, out=out,
            allow_short_delay=True, delay_ms=(30, 60))
        path = None
        if "探查報告：" in out.getvalue():
            path = out.getvalue().split("探查報告：")[1].splitlines()[0]
        report = None
        if path:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            report = json.loads(raw)
            for needle in ("SECRETTITLE", "SECRETBODY", PASSWORD, EMAIL):
                self.assertNotIn(needle, raw, "報告不得含 %s" % needle)
        return rc, out.getvalue(), report

    def test_happy_path_logs_in_once_respects_caps_and_logs_out_server_side(self):
        site = FakeSite()
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 0, out)
        self.assertEqual(site.sessions, set(), "探查結束後伺服器端不得留有登入狀態")
        posts = [e for e in site.log if e[0] == "POST"]
        self.assertEqual(len(posts), 1)
        opened = [e for e in site.log if e[0] == "GET" and e[1].rsplit("/", 1)[-1].isdigit()
                  and e[1].startswith("/user/vip_contents/")]
        self.assertEqual(len(opened), 2)
        self.assertNotIn(("GET", "/user/vip_contents/9999"), site.log, "公告不得被開啟")
        self.assertEqual(report["counters"]["logins"], 1)
        self.assertLessEqual(report["counters"]["list_pages"], 3)
        self.assertEqual(report["limit_violations"], [])
        self.assertTrue(report["P2_logout"]["server_side_verified"])
        self.assertEqual(report["P1_list_pagination"]["paging_type"], "link_pagination")
        self.assertEqual(report["P1_list_pagination"]["items_per_page_page1"], 7)
        self.assertEqual(report["P1_list_pagination"]["items_per_page_page2"], 3)
        self.assertEqual(report["P5_list_structure"]["announcements_on_page1"], 1)
        self.assertEqual([t["lv"] for t in report["P5_list_structure"]["tabs"]], ["0", "1"])
        self.assertTrue(report["P3_read_state"]["changed_after_open"])
        self.assertTrue(report["P7_block_and_login"]["remember_checkbox"])
        self.assertTrue(report["P7_block_and_login"]["remember_default_checked"])
        arts = report["P6_article_dom"]
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0]["container_chain"][0]["classes"], ["post"])
        self.assertEqual(len(arts[0]["images"]), 2)
        self.assertGreater(arts[0]["body_text_len"], 0)
        self.assertEqual(report["P8_id_monotonic_with_date"], True)

    def test_no_logout_mechanism_stops_before_opening_articles(self):
        site = FakeSite(has_logout=False)
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 1)
        self.assertIn("找不到伺服器端登出機制", out)
        self.assertEqual(report["counters"]["articles_opened"], 0)
        self.assertFalse(report["P2_logout"]["mechanism_found"])

    def test_bad_credentials_classified_and_nothing_else_visited(self):
        site = FakeSite()
        rc, out, report = self._probe(site, wrong_password=True)
        self.assertEqual(rc, 1)
        self.assertEqual(report["P7_block_and_login"]["login_failure_reason"], "bad_credentials")
        self.assertEqual(report["counters"]["articles_opened"], 0)
        self.assertEqual(site.sessions, set())


if __name__ == "__main__":
    unittest.main()
