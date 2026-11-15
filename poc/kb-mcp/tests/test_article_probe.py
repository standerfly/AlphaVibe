"""010 Phase 0 探查工具測試：全部使用假資料／本機假網站，不連真實網站、不讀真鑰匙圈。"""
import datetime
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_probe  # noqa: E402
import keychain_secrets  # noqa: E402
from fake_investanchors_site import CSRF, EMAIL, PASSWORD, FakeSite  # noqa: E402

NOW = datetime.datetime(2026, 11, 15, 23, 0, 0)
IA = keychain_secrets.INVESTANCHORS_SERVICE
CONFIRM = ["--confirm-po-present", "--confirm-one-device-only"]


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

    def test_refuses_without_one_device_confirmation(self):
        def boom(*a, **k):
            raise AssertionError("must not be called")
        out = io.StringIO()
        rc = article_probe.run(["--confirm-po-present"], get_secret=boom,
                               scraper_runner=boom, mail_prober=boom, out=out)
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-one-device-only", out.getvalue())
        self.assertIn("最多兩台", out.getvalue())

    def test_short_delay_refused_unless_test_override(self):
        def boom(*a, **k):
            raise AssertionError("must not be called")
        out = io.StringIO()
        rc = article_probe.run(CONFIRM, get_secret=boom, scraper_runner=boom,
                               out=out, delay_ms=(100, 200))
        self.assertEqual(rc, 2)

    def test_missing_secret_stops_before_scraper(self):
        def get(account, runner=None, service=None):
            raise keychain_secrets.SecretNotFound(account)
        def boom(*a, **k):
            raise AssertionError("scraper must not run")
        out = io.StringIO()
        rc = article_probe.run(CONFIRM + ["--skip-mail"], get_secret=get,
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
        rc = article_probe.run(["--data-dir", self.tmp] + CONFIRM + ["--skip-mail"]
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
            def terminate(self):
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
        self.assertIn("請勿再次執行探查", out)
        self.assertIn("無法清除", out)
        self.assertNotIn("請 PO 立刻手動登出", out)

    def test_no_logout_mechanism_stops_and_reports(self):
        rc, out, _ = self._run([self._summary(
            logout_found=False, logged_out=False, logout_verified=False,
            stage_error="no_logout_mechanism")])
        self.assertEqual(rc, 1)
        self.assertIn("找不到伺服器端登出機制", out)

    def test_missing_summary_is_failure(self):
        rc, out, _ = self._run([{"type": "fact", "step": "login", "data": {}}])
        self.assertEqual(rc, 1)
        self.assertIn("請勿再次執行探查", out)

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


class AnalyzeListTest(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 15)

    def test_duplicates_across_pages_excluded_from_ranges_and_counts(self):
        pinned = {"article_id": 7, "date": "2021-02-06", "is_announcement": False}
        p1 = [pinned, {"article_id": 10, "date": "2026-11-10", "is_announcement": False},
              {"article_id": 9, "date": "2026-11-01", "is_announcement": False}]
        p2 = [pinned, {"article_id": 8, "date": "2026-05-01", "is_announcement": False},
              {"article_id": 6, "date": "2026-01-01", "is_announcement": False}]
        r = article_probe.analyze_list(p1, p2, self.TODAY)
        self.assertEqual(r["duplicated_across_pages"], 1)
        self.assertEqual(r["duplicated_item_dates_sorted"], ["2021-02-06"])
        self.assertEqual(r["page1_excluding_duplicates"]["from"], "2026-11-01")
        self.assertEqual(r["items_within_half_year_excluding_duplicates"], 2)  # 5/1 早於 5/16 截止日
        self.assertTrue(r["half_year_boundary_reached_on_page2"])
        self.assertEqual(r["unique_items"], 5)


class CliValidationTest(unittest.TestCase):
    def _run(self, extra):
        def boom(*a, **k):
            raise AssertionError("must not be called")
        out = io.StringIO()
        rc = article_probe.run(CONFIRM + extra, get_secret=boom, scraper_runner=boom, out=out)
        return rc, out.getvalue()

    def test_non_numeric_article_id_rejected(self):
        self.assertEqual(self._run(["--article-id", "abc"])[0], 2)

    def test_more_than_two_article_ids_rejected(self):
        self.assertEqual(self._run(["--article-id", "1", "--article-id", "2",
                                    "--article-id", "3"])[0], 2)


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


class RunnerTimeoutTest(unittest.TestCase):
    def test_silent_node_is_terminated_by_watchdog(self):
        tmp = tempfile.mkdtemp(prefix="probe-sleeper-")
        self.addCleanup(shutil.rmtree, tmp, True)
        script = os.path.join(tmp, "sleeper.py")
        with open(script, "w") as f:
            f.write("import time\ntime.sleep(60)\n")
        with mock.patch.object(article_probe, "_node_binary", return_value=sys.executable), \
                mock.patch.object(article_probe, "SCRAPER_JS", script):
            t0 = time.time()
            objs = article_probe.default_scraper_runner({"mode": "probe"}, timeout_sec=1,
                                                        grace_sec=3)
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(objs, [])


@unittest.skipUnless(shutil.which("node") or os.path.exists("/opt/homebrew/bin/node"), "需要 node")
class SameSiteTest(unittest.TestCase):
    def test_www_variant_is_same_site_but_lookalikes_are_not(self):
        node = shutil.which("node") or "/opt/homebrew/bin/node"
        code = ("const {sameSite}=require('./scraper/site_util');"
                "console.log(JSON.stringify([sameSite('investanchors.com','www.investanchors.com'),"
                "sameSite('www.investanchors.com','investanchors.com'),"
                "sameSite('evil.com','investanchors.com'),"
                "sameSite('investanchors.com.evil.com','investanchors.com')]))")
        out = subprocess.run([node, "-e", code], cwd=article_probe.HERE,
                             capture_output=True, text=True, timeout=30).stdout
        self.assertEqual(json.loads(out), [True, True, False, False])


class MailAnalysisTest(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 15)
    ID_A = "17942117264764"
    ID_B = "17941457714762"

    def test_path_shapes_query_keys_and_long_numbers_without_values(self):
        html = ('<a href="https://investanchors.com/user/vip_contents/%s?utm_source=x&id=%s">a</a>'
                '<a href="https://investanchors.com/articles/abc123def456/view">b</a>'
                '<a href="https://click.example.net/t?u=SECRETTOKEN">c</a>' % (self.ID_A, self.ID_B))
        got = article_probe.classify_mail_links(html)
        self.assertEqual(got["path_shapes"], {"/user/vip_contents/#": 1, "/articles/#/view": 1})
        self.assertEqual(sorted(got["query_keys"]), ["id", "u", "utm_source"])
        self.assertEqual(got["links_with_long_number_in_path"], 1)
        self.assertEqual(got["links_with_long_number_in_query"], 1)
        self.assertEqual(sorted(got["long_numbers"]), sorted([self.ID_A, self.ID_B]))
        self.assertNotIn("SECRETTOKEN", json.dumps({k: v for k, v in got.items()
                                                    if k != "long_numbers"}))

    def test_long_path_segments_are_masked_as_token(self):
        tok = "eJwUzEGOhCAQAMDXwHFCNabcdefGHIJKLMNOPQRSTUVWXYZ"
        html = '<a href="https://investanchors.com/c/%s">x</a>' % tok
        got = article_probe.classify_mail_links(html)
        self.assertEqual(got["path_shapes"], {"/c/<token>": 1})
        self.assertNotIn("eJw", json.dumps({k: v for k, v in got.items() if k != "long_numbers"}))

    def _mail(self, date_hdr, body):
        m = MIMEMultipart("alternative")
        m["From"] = "定錨 <%s>" % article_probe.MAIL_SENDER
        m["Subject"] = "SECRETSUBJECT"
        m["Date"] = date_hdr
        m.attach(MIMEText(body, "html", "utf-8"))
        return m.as_bytes()

    def _imap(self, mails):
        class Fake:
            def login(self, u, p):
                return "OK", [b""]
            def list(self):
                return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']
            def select(self, name, readonly=False):
                return "OK", [b"1"]
            def uid(self, cmd, *args):
                if cmd == "SEARCH":
                    return "OK", [b" ".join(sorted(mails))]
                return "OK", [(b"1 (UID 1)", mails[args[0]]), b")"]
            def logout(self):
                pass
        return Fake()

    def test_probe_mail_reports_dates_and_id_matches_without_leaking_numbers(self):
        mails = {
            b"1": self._mail("Sat, 14 Nov 2026 22:30:00 +0800",
                             '<a href="https://investanchors.com/p/%s">x</a>' % self.ID_A),
            b"2": self._mail("Sun, 15 Nov 2026 01:00:00 +0000",
                             '<a href="https://investanchors.com/p/%s">x</a>'
                             '<a href="https://investanchors.com/p/99999999999999">y</a>' % self.ID_B),
        }
        facts = article_probe.probe_mail("me@x", "pw", imap_factory=lambda: self._imap(mails),
                                         max_messages=60, known_ids=[self.ID_A, self.ID_B])
        self.assertEqual(facts["messages_examined"], 2)
        dates = [m["date"] for m in facts["messages"]]
        self.assertEqual(dates, ["2026-11-14", "2026-11-15"], "UTC 01:00 要換成台北日期")
        self.assertEqual([m["ids_in_list"] for m in facts["messages"]], [1, 1])
        self.assertEqual([m["ids_not_in_list"] for m in facts["messages"]], [0, 1])
        self.assertEqual(facts["path_shapes"], {"/p/#": 3})
        dumped = json.dumps(facts, ensure_ascii=False)
        self.assertNotRegex(dumped, r"\d{13,}")
        self.assertNotIn("SECRETSUBJECT", dumped)

    def test_compare_mail_vs_list_by_date_only(self):
        mk = lambda i, d, dup=False, ann=False: {"id": i, "date": d, "announcement": ann,
                                                 "dup_across_pages": dup}
        items = [
            mk(1612580077558, "2021-02-06", dup=True, ann=True),
            mk(int(self.ID_A), "2021-02-06", dup=True),          # 置頂：改用 ID 時間（2026-11-09）
            mk(100000000000001, "2026-11-12"),
            mk(100000000000002, "2026-11-12"),                    # 同日兩篇
            mk(100000000000003, "2026-10-20"),                    # 前後 1 天內都沒有信
        ]
        msgs = [{"date": "2026-11-12", "sender_ok": True, "distinct_long_numbers": 2,
                 "ids_in_list": 0, "ids_not_in_list": 2},
                {"date": "2026-11-09", "sender_ok": True, "distinct_long_numbers": 1},
                {"date": "2026-11-01", "sender_ok": True, "distinct_long_numbers": 0},
                {"date": "2026-11-13", "sender_ok": False, "distinct_long_numbers": 0}]
        r = article_probe.compare_mail_vs_list(msgs, items, self.TODAY, 30)
        self.assertEqual(r["mails_in_window"], 3)
        self.assertEqual(r["articles_in_window"], 4)
        self.assertEqual(r["articles_on_days_with_no_mail_same_day"], 1)
        self.assertEqual(r["articles_with_no_mail_within_1_day"], 1)
        self.assertEqual(r["mail_days_with_no_article_same_day"], 1)
        self.assertEqual(r["mails_with_multiple_long_numbers"], 1)
        self.assertEqual({d["date"]: (d["mails"], d["articles"]) for d in r["per_day"]},
                         {"2026-11-12": (1, 2), "2026-11-09": (1, 1),
                          "2026-11-01": (1, 0), "2026-10-20": (0, 1)})


class MailOnlyModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="probe-mailonly-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _boom(self, *a, **k):
        raise AssertionError("must not be called")

    def test_refuses_without_mail_consent_and_touches_nothing(self):
        out = io.StringIO()
        rc = article_probe.run(["--mail-only", "--data-dir", self.tmp], get_secret=self._boom,
                               scraper_runner=self._boom, mail_prober=self._boom, out=out)
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-mail-read", out.getvalue())

    def test_never_logs_in_or_reads_site_credentials(self):
        listing = {"P1_list_pagination": {"list_items": [
            {"id": 100000000000001, "date": "2026-11-12", "announcement": False,
             "dup_across_pages": False}]}}
        os.makedirs(os.path.join(self.tmp, "articles_probe"))
        with open(os.path.join(self.tmp, "articles_probe", "probe-20261115-000000.json"), "w") as f:
            json.dump(listing, f)
        asked = []
        def get(account, runner=None, service=None):
            asked.append((account, service))
            return {"gmail-address": "me@gmail.example", "gmail-app-password": "app-pw-xyz"}[account]
        seen = {}
        def prober(addr, pw, days=30, max_messages=2, known_ids=None):
            seen["known_ids"] = list(known_ids)
            seen["max_messages"] = max_messages
            return {"messages": [{"date": "2026-11-12", "sender_ok": True,
                                  "distinct_long_numbers": 1, "ids_in_list": 1,
                                  "ids_not_in_list": 0}]}
        out = io.StringIO()
        rc = article_probe.run(["--mail-only", "--confirm-mail-read", "--data-dir", self.tmp],
                               get_secret=get, scraper_runner=self._boom, mail_prober=prober,
                               now=lambda: NOW, out=out)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertEqual([a for a, _ in asked], ["gmail-address", "gmail-app-password"])
        self.assertTrue(all(svc is None for _, svc in asked), "不得讀 stnd-investanchors")
        self.assertEqual(seen["known_ids"], [100000000000001])
        path = out.getvalue().split("信箱檢視報告：")[1].splitlines()[0]
        self.assertTrue(os.path.basename(path).startswith("mail-"))
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("app-pw-xyz", raw)
        self.assertIn("comparison", json.loads(raw))


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

    def _probe(self, site, wrong_password=False, extra=None):
        base = site.start()
        self.addCleanup(site.stop)
        out = io.StringIO()
        rc = article_probe.run(
            ["--data-dir", self.tmp] + CONFIRM + ["--skip-mail", "--base-url", base] + (extra or []),
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
            for needle in ("SECRETTITLE", "SECRETBODY", PASSWORD, EMAIL, CSRF):
                self.assertNotIn(needle, raw, "報告不得含 %s" % needle)
        return rc, out.getvalue(), report

    def test_happy_path_logs_in_once_respects_caps_and_logs_out_server_side(self):
        site = FakeSite()
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 0, out)
        self.assertEqual(site.sessions, set(), "探查結束後伺服器端不得留有登入狀態")
        posts = [e for e in site.log if e[0] == "POST"]
        self.assertEqual(posts, [("POST", "/login")], "只送出登入表單，不得碰註冊表單")
        opened = [e for e in site.log if e[0] == "GET" and e[1].rsplit("/", 1)[-1].isdigit()
                  and e[1].startswith("/user/vip_contents/")]
        self.assertEqual(len(opened), 2)
        self.assertNotIn(("GET", "/user/vip_contents/9999"), site.log, "公告不得被開啟")
        self.assertEqual(report["counters"]["logins"], 1)
        self.assertLessEqual(report["counters"]["list_pages"], 3)
        self.assertEqual(report["limit_violations"], [])
        self.assertTrue(report["P2_logout"]["server_side_verified"])
        self.assertEqual(report["P2_logout"]["attempts"][0]["method"], "menu_click")
        self.assertEqual(report["P1_list_pagination"]["paging_type"], "link_pagination")
        self.assertEqual(report["P1_list_pagination"]["items_per_page_page1"], 8)
        self.assertEqual(report["P1_list_pagination"]["items_per_page_page2"], 4)
        self.assertEqual(report["P1_list_pagination"]["overlap_page1_page2"], 1)
        self.assertEqual(report["P5_list_structure"]["announcements_on_page1"], 1)
        self.assertEqual([t["lv"] for t in report["P5_list_structure"]["tabs"]], ["0", "1"])
        self.assertTrue(report["P3_read_state"]["changed_after_open"])
        self.assertTrue(report["P7_block_and_login"]["remember_checkbox"])
        self.assertTrue(report["P7_block_and_login"]["remember_default_checked"])
        arts = report["P6_article_dom"]
        self.assertEqual(len(arts), 2)
        a0 = arts[0]
        self.assertEqual(a0["container_chain"][0]["id"], "inves_content")
        self.assertEqual(a0["content_image_count"], 2)
        self.assertEqual(a0["outside_image_count"], 1, "站台 logo 不算內文圖")
        self.assertTrue(all(i["in_table"] for i in a0["content_images"]))
        self.assertTrue(a0["content_images"][1]["lazy_attr"])
        self.assertEqual(a0["content_images"][1]["loading_attr"], "lazy")
        self.assertEqual(len(a0["content_tables"]), 1)
        self.assertTrue(a0["content_tables"][0]["has_img"])
        self.assertGreater(a0["body_text_len"], 0)
        checks = a0["image_download_check_without_cookies"]
        self.assertEqual([c["status"] for c in checks], [200, 403],
                         "公開圖不需登入；需登入的圖不帶 cookie 會被拒")
        self.assertEqual(report["P8_id_monotonic_with_date_excluding_duplicates"], True)
        li = report["P1_list_pagination"]["list_items"]
        self.assertEqual(len(li), 12)
        self.assertEqual([i["id"] for i in li if i["dup_across_pages"]], [777, 777])
        h = report["P8_half_year"]
        self.assertEqual(h["duplicated_across_pages"], 1)
        self.assertEqual(h["duplicated_item_dates_sorted"], ["2021-02-06"])
        self.assertFalse(h["half_year_boundary_reached_on_page2"], "假網站第 2 頁尚未早於半年前")
        self.assertEqual(h["page2_excluding_duplicates"]["from"], "2026-10-24")

    def test_explicit_article_ids_are_opened_first_and_control_is_unread_item(self):
        site = FakeSite()
        rc, out, report = self._probe(site, extra=["--article-id", "424242"])
        self.assertEqual(rc, 0, out)
        opened = [int(e[1].rsplit("/", 1)[-1]) for e in site.log
                  if e[0] == "GET" and e[1].startswith("/user/vip_contents/")
                  and e[1].rsplit("/", 1)[-1].isdigit()]
        self.assertEqual(opened, [424242, 1010],
                         "先開指定的，再補一篇未讀對照（排除置頂／跨頁重複項 777）；不得超過 2 篇")
        arts = report["P6_article_dom"]
        self.assertTrue(arts[0]["explicitly_requested"])
        self.assertFalse(arts[0]["was_in_list_pages_1_2"])
        self.assertFalse(arts[1]["explicitly_requested"])
        self.assertTrue(arts[1]["was_in_list_pages_1_2"])
        rs = report["P3_read_state"]
        self.assertTrue(rs["had_unread_target"])
        self.assertTrue(rs["changed_after_open"])
        self.assertEqual(report["limit_violations"], [])

    def test_no_logout_mechanism_stops_before_opening_articles(self):
        site = FakeSite(logout_mode="none")
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 1)
        self.assertIn("找不到伺服器端登出機制", out)
        self.assertIn("請勿再次執行探查", out)
        self.assertEqual(report["counters"]["articles_opened"], 0)
        self.assertFalse(report["P2_logout"]["mechanism_found"])
        self.assertFalse(report["P2_logout"]["server_side_verified"])

    def test_bad_credentials_classified_and_nothing_else_visited(self):
        site = FakeSite()
        rc, out, report = self._probe(site, wrong_password=True)
        self.assertEqual(rc, 1)
        self.assertEqual(report["P7_block_and_login"]["login_failure_reason"], "bad_credentials")
        self.assertEqual(report["counters"]["articles_opened"], 0)
        self.assertEqual(site.sessions, set())

    def test_logout_in_hidden_dropdown_that_only_accepts_delete(self):
        site = FakeSite(logout_mode="menu_js_delete")
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 0, out)
        self.assertEqual(site.sessions, set())
        self.assertIn(("DELETE", "/logout"), site.log)
        self.assertTrue(report["P2_logout"]["mechanism_found"])
        cand = report["P2_logout"]["candidates"][0]
        self.assertEqual(cand["data_method"], "delete")
        self.assertFalse(cand["visible"])

    def test_hidden_logout_link_without_js_falls_back_to_csrf_post_override(self):
        site = FakeSite(logout_mode="hidden_delete_no_js")
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 0, out)
        self.assertEqual(site.sessions, set())
        methods = [a["method"] for a in report["P2_logout"]["attempts"]]
        self.assertEqual(methods[-1], "fetch")
        self.assertIn("menu_click", methods)
        self.assertTrue(report["P2_logout"]["attempts"][-1]["verified"])
        self.assertFalse(any(a["verified"] for a in report["P2_logout"]["attempts"][:-1]))
        self.assertIn(("POST", "/logout"), site.log)

    def test_logout_verification_ignores_hidden_password_field_before_login_form(self):
        site = FakeSite(hidden_register_first=True)
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 0, out)
        self.assertEqual(site.sessions, set())
        attempts = report["P2_logout"]["attempts"]
        self.assertEqual(len(attempts), 1, "第一次登出後就應驗證成功，不該多跑幾輪")
        self.assertTrue(attempts[0]["verified"])
        self.assertEqual([e for e in site.log if e[0] == "POST"], [("POST", "/login")])

    def test_register_form_before_login_form_aborts_without_submitting(self):
        site = FakeSite(register_first=True)
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 1)
        self.assertEqual(report["P7_block_and_login"]["stage_error"], "ambiguous_login_form")
        self.assertEqual([e for e in site.log if e[0] == "POST"], [], "不得送出任何表單")
        self.assertEqual(site.sessions, set())

    def test_session_is_logged_out_even_when_login_is_judged_failed(self):
        site = FakeSite(post_login_pw_field=True)
        rc, out, report = self._probe(site)
        self.assertEqual(rc, 1)
        self.assertEqual(site.sessions, set(), "已登入但被判定失敗時仍須登出")
        self.assertEqual(report["counters"]["articles_opened"], 0)

    def test_sigterm_during_run_logs_out_before_exit(self):
        site = FakeSite()
        base = site.start()
        self.addCleanup(site.stop)
        payload = {"mode": "probe", "email": EMAIL, "password": PASSWORD, "base_url": base,
                   "max_list_pages": 3, "max_articles": 2, "delay_ms": [6000, 6000],
                   "timeout_ms": 30000}
        proc = subprocess.Popen(["node", article_probe.SCRAPER_JS] if shutil.which("node")
                                else ["/opt/homebrew/bin/node", article_probe.SCRAPER_JS],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        proc.stdin.write(json.dumps(payload).encode())
        proc.stdin.close()
        deadline = time.time() + 40
        while not site.sessions and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(site.sessions, "假網站應已建立登入狀態")
        proc.send_signal(signal.SIGTERM)
        out = proc.stdout.read().decode("utf-8")
        proc.stdout.close()
        proc.wait(timeout=60)
        self.assertEqual(site.sessions, set(), "收到 SIGTERM 後須先登出再結束")
        summaries = [json.loads(l) for l in out.splitlines() if '"type":"summary"' in l]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["stage_error"], "signal_SIGTERM")
        self.assertTrue(summaries[0]["logout_verified"])


if __name__ == "__main__":
    unittest.main()
