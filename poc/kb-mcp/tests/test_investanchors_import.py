"""T016～T019：匯入協調器（觸發判斷、套用結果、失敗處理、登出強制與通知）。全用假依賴，不需瀏覽器。"""
import datetime
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_store  # noqa: E402
import investanchors_import as I  # noqa: E402
import investanchors_limits  # noqa: E402
import investanchors_redact  # noqa: E402
import keychain_secrets  # noqa: E402

TZ8 = I.TZ8
PW = "pw-secret-123"
EMAIL = "po@example.com"
BODY = "SECRETBODY 內文。" * 30
WED = datetime.datetime(2026, 11, 11, 23, 0, tzinfo=TZ8)      # 週三
SUN = datetime.datetime(2026, 11, 15, 23, 0, tzinfo=TZ8)      # 週日


def li(aid, title=None, date="2026-11-10", ann=False, pinned=False, page=1):
    return {"type": "list_item", "page": page, "article_id": aid, "title": title or "標題%d" % aid,
            "date": date, "is_announcement": ann, "read_state": "bold", "pinned": pinned}


def art(aid, body=BODY, images=(), published="2026-11-10T12:00"):
    return {"type": "article", "article_id": aid, "published_at": published, "body": body,
            "images": [{"seq": i, "src_url": u} for i, u in enumerate(images, 1)]}


def err(aid, reason="structure"):
    return {"type": "article_error", "article_id": aid, "reason": reason}


def summ(**kw):
    s = {"type": "summary", "counters": {"logins": 1, "navigations": 3, "list_pages": 1, "articles_opened": 1},
         "blocked": False, "logged_in": True, "logout_found": True, "logged_out": True,
         "logout_verified": True, "stage_error": None}
    s.update(kw)
    return s


class Harness(object):
    def __init__(self, test, now=WED, clues=None, script=None):
        self.test = test
        self.tmp = tempfile.mkdtemp(prefix="import-test-")
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = [now]
        self.clues = list(clues or [])
        self.mail_error = None
        self.notes = []
        self.payloads = []
        self.downloads = []
        self.script = script or (lambda payload: [li(1001), art(1001), summ()])
        self.fail_images = False
        self.out = io.StringIO()
        self.creds_ok = True

    def _mail(self):
        if self.mail_error:
            raise self.mail_error
        return list(self.clues)

    def _scraper(self, payload):
        self.payloads.append(payload)
        return self.script(payload)

    def _dl(self, store, aid, data_dir, **kw):
        if self.fail_images:
            raise RuntimeError("image boom")
        self.downloads.append((aid, kw.get("allowed_hosts")))
        return {"downloaded": [], "failed": []}

    def _secret(self, account, runner=None, service=None):
        if not self.creds_ok:
            raise keychain_secrets.SecretNotFound(account)
        return {"email": EMAIL, "password": PW, "gmail-address": "me@g.x", "gmail-app-password": "app-pw"}[account]

    def run(self, argv=None, **over):
        deps = dict(fetch_mail=self._mail, run_scraper=self._scraper, download_images=self._dl,
                    notifier=self.notes.append, get_secret=self._secret, now=lambda: self.clock[0],
                    sleeper=lambda s: None, delay_ms=[10, 20], image_hosts=("127.0.0.1",), out=self.out,
                    auto_backfill=False)
        deps.update(over)
        return I.run(["--data-dir", self.tmp] + (argv or []), **deps)

    def store(self):
        s = article_store.ArticleStore(self.tmp, now=lambda: self.clock[0])
        self.test.addCleanup(s.close)
        return s


def clue(mid="<m1@x>", date="2026-11-11T20:00:00+08:00"):
    return {"message_id": mid, "mail_date": date}


# ====================================================================== T016

class TriggerDecisionTest(unittest.TestCase):
    def test_no_trigger_means_scraper_never_called_and_run_recorded_as_none(self):
        h = Harness(self)
        self.assertEqual(h.run(), 0)
        self.assertEqual(h.payloads, [])
        run = h.store().recent_runs(1)[0]
        self.assertEqual((run["trigger"], run["logged_in"], run["result"]), ("none", 0, "ok"))

    def test_new_mail_triggers_one_login_with_import_payload(self):
        h = Harness(self, clues=[clue()])
        self.assertEqual(h.run(), 0)
        self.assertEqual(len(h.payloads), 1)
        p = h.payloads[0]
        self.assertEqual((p["mode"], p["email"], p["password"]), ("import", EMAIL, PW))
        self.assertEqual((p["max_articles"], p["max_list_pages"]), (5, 3))
        self.assertEqual(p["delay_ms"], [10, 20])
        s = h.store()
        self.assertEqual(s.logins_today(h.clock[0]), 1)
        self.assertEqual(s.recent_runs(1)[0]["trigger"], "mail")

    def test_processed_mail_does_not_trigger_again(self):
        h = Harness(self, clues=[clue()])
        h.run()
        h.clock[0] = WED + datetime.timedelta(days=1)
        self.assertEqual(h.run(), 0)
        self.assertEqual(len(h.payloads), 1)

    def test_second_login_same_day_refused_without_launching_scraper(self):
        h = Harness(self, clues=[clue("<a@x>")])
        h.run()
        h.clues.append(clue("<b@x>"))
        self.assertEqual(h.run(), 2)
        self.assertEqual(len(h.payloads), 1)
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "aborted_limit")

    def test_blocked_until_refuses_until_it_passes(self):
        h = Harness(self, clues=[clue()], script=lambda p: [summ(blocked=True, stage_error="blocked_timeouts")])
        self.assertEqual(h.run(), 1)
        h.clues.append(clue("<n@x>"))
        h.clock[0] = WED + datetime.timedelta(hours=20)           # 隔天 19:00：仍在延後期內
        self.assertEqual(h.run(), 2)
        h.clock[0] = WED + datetime.timedelta(days=1, hours=1)    # 週五 00:00 之後 → 到期，且是新的一天
        h.script = lambda p: [li(1001), art(1001), summ()]
        self.assertEqual(h.run(), 0)
        self.assertEqual(len(h.payloads), 2)

    def test_dry_run_has_zero_side_effects_on_a_fresh_directory(self):
        h = Harness(self, clues=[clue()])
        before = os.listdir(h.tmp)
        self.assertEqual(h.run(["--dry-run"]), 0)
        self.assertEqual(os.listdir(h.tmp), before)                # 沒有建立資料庫檔
        self.assertEqual((h.payloads, h.notes), ([], []))
        self.assertIn("新信 1 封", h.out.getvalue())

    def test_dry_run_does_not_write_into_existing_database(self):
        h = Harness(self, clues=[clue()])
        s = h.store()
        h.run(["--dry-run"])
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM mail_clue").fetchone()[0], 0)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)
        self.assertEqual(h.payloads, [])

    def test_weekly_trigger_rules(self):
        self.assertTrue(I.weekly_due(SUN, None))
        self.assertFalse(I.weekly_due(WED, None))
        self.assertFalse(I.weekly_due(SUN, SUN - datetime.timedelta(days=3)))
        self.assertTrue(I.weekly_due(SUN, SUN - datetime.timedelta(days=6)))
        mon = SUN + datetime.timedelta(days=1)
        self.assertTrue(I.weekly_due(mon, mon - datetime.timedelta(days=9)))      # 週日睡過頭：超過 8 天補上
        self.assertFalse(I.weekly_due(mon, mon - datetime.timedelta(days=5)))

    def test_sunday_triggers_weekly_without_mail_and_force_weekly_works_any_day(self):
        h = Harness(self, now=SUN)
        self.assertEqual(h.run(), 0)
        self.assertEqual(h.store().recent_runs(1)[0]["trigger"], "weekly")
        h2 = Harness(self)
        h2.run(["--force-weekly"])
        self.assertEqual(len(h2.payloads), 1)

    def test_mailbox_failure_never_triggers_scraping_but_weekly_still_runs(self):
        h = Harness(self)
        h.mail_error = RuntimeError("imap down")
        self.assertEqual(h.run(), 0)
        self.assertEqual(h.payloads, [])
        h2 = Harness(self, now=SUN)
        h2.mail_error = RuntimeError("imap down")
        h2.run()
        self.assertEqual(len(h2.payloads), 1)

    def test_mailbox_failure_alerts_only_after_three_in_a_row_and_resets_on_success(self):
        h = Harness(self)
        h.mail_error = RuntimeError("x")
        for d in range(2):
            h.clock[0] = WED + datetime.timedelta(days=d)
            h.run()
        self.assertEqual(h.notes, [])
        h.clock[0] = WED + datetime.timedelta(days=2)
        h.run()
        self.assertEqual(h.notes, [I.ALERT_TEXTS["mailbox_failure"]])
        h.mail_error = None
        h.clock[0] = WED + datetime.timedelta(days=3)
        h.run()
        self.assertEqual(h.store().get_setting("mail_fail_count"), "0")

    def test_missing_credentials_stop_before_scraper_and_do_not_consume_quota(self):
        h = Harness(self, clues=[clue()])
        h.creds_ok = False
        self.assertEqual(h.run(), 1)
        self.assertEqual(h.payloads, [])
        self.assertEqual(h.store().logins_today(h.clock[0]), 0)

    def test_max_articles_can_only_lower_the_cap(self):
        for arg, expect in (("2", 2), ("99", 5), ("0", 0)):
            h = Harness(self, clues=[clue()])
            h.run(["--max-articles", arg])
            self.assertEqual(h.payloads[0]["max_articles"], expect)

    def test_reset_abandoned_and_resume_commands_do_not_login(self):
        h = Harness(self)
        s = h.store()
        s.upsert_discovered(1, "https://investanchors.com/user/vip_contents/1", "t")
        for _ in range(3):
            s.mark_failed(1, "e")
        self.assertEqual(h.run(["--reset-abandoned", "1"]), 0)
        self.assertEqual(s.get_article_row(1)["status"], "failed")
        self.assertEqual(h.run(["--reset-abandoned", "1"]), 1)         # 已不是 abandoned
        s.set_setting(I.HALT_SETTING, "account_disabled")
        self.assertEqual(h.run(["--resume"]), 0)
        self.assertEqual(h.payloads, [])


# ====================================================================== T017

class ApplyResultsTest(unittest.TestCase):
    def test_list_items_articles_and_images_are_stored_and_notified_with_title_and_link_only(self):
        script = lambda p: [li(1001, "標題甲", pinned=True), li(1002, "標題乙"), li(9999, "【公告】x", ann=True),
                            art(1001, images=["http://127.0.0.1/a.png", "http://127.0.0.1/b.png"]),
                            art(1002), summ(counters={"logins": 1, "list_pages": 1, "articles_opened": 2})]
        h = Harness(self, clues=[clue()], script=script)
        self.assertEqual(h.run(), 0)
        s = h.store()
        r = s.get_article_row(1001)
        self.assertEqual((r["status"], r["title"], r["pinned"], r["list_date"], r["published_at"], r["body"]),
                         ("fetched", "標題甲", 1, "2026-11-10", "2026-11-10T12:00", BODY))
        self.assertEqual(r["url"], "https://investanchors.com/user/vip_contents/1001")
        self.assertEqual(r["discovered_via"], "mail")
        self.assertEqual(s.get_article_row(9999)["status"], "skipped")         # 公告不匯入（FR-004）
        self.assertEqual(len(s.list_images(1001)), 2)
        self.assertEqual(sorted(a for a, _ in h.downloads), [1001, 1002])
        self.assertEqual(h.downloads[0][1], ("127.0.0.1",))
        self.assertEqual(sorted(h.notes), sorted(["📰 定錨新文章：標題甲\nhttps://investanchors.com/user/vip_contents/1001",
                                                  "📰 定錨新文章：標題乙\nhttps://investanchors.com/user/vip_contents/1002"]))
        for n in h.notes:
            self.assertNotIn("SECRETBODY", n)                                   # FR-019：不含內文

    def test_rerun_next_day_creates_no_duplicates_and_known_ids_are_passed(self):
        h = Harness(self, clues=[clue()])
        h.run()
        h.clock[0] = WED + datetime.timedelta(days=1)
        h.clues.append(clue("<m2@x>"))
        h.script = lambda p: [li(1001), summ()]                                 # 清單再次看到同一篇
        self.assertEqual(h.run(), 0)
        self.assertIn(1001, h.payloads[1]["known_ids"])
        s = h.store()
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0], 1)
        self.assertEqual(len(h.notes), 1)                                       # 不重複通知

    def test_fetched_article_is_never_overwritten_even_if_scraper_returns_it_again(self):
        h = Harness(self, clues=[clue()])
        h.run()
        h.clock[0] = WED + datetime.timedelta(days=1)
        h.clues.append(clue("<m2@x>"))
        h.script = lambda p: [art(1001, body="另一份完全不同的內文。" * 50), summ()]
        h.run()
        self.assertEqual(h.store().get_article_row(1001)["body"], BODY)

    def test_unknown_article_events_are_ignored(self):
        h = Harness(self, clues=[clue()], script=lambda p: [art(5555), summ()])
        self.assertEqual(h.run(), 0)
        self.assertIsNone(h.store().get_article_row(5555))

    def test_pending_failed_articles_are_sent_to_scraper_for_retry(self):
        h = Harness(self, clues=[clue()])
        s = h.store()
        s.upsert_discovered(7, "https://investanchors.com/user/vip_contents/7", "舊", via="backfill")
        s.upsert_discovered(8, "https://investanchors.com/user/vip_contents/8", "新", via="mail")
        s.mark_failed(8, "e")
        h.run()
        self.assertEqual(h.payloads[0]["pending_ids"], [8, 7])                  # 新文章優先於回補

    def test_mail_clues_marked_processed_only_when_list_was_read(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1001), summ()])
        h.run()
        self.assertEqual(h.store().unprocessed_mail_clues(), [])
        h2 = Harness(self, clues=[clue()],
                     script=lambda p: [summ(counters={"logins": 1, "list_pages": 0}, stage_error="exception:Error")])
        h2.run()
        self.assertEqual(len(h2.store().unprocessed_mail_clues()), 1)

    def test_image_download_failure_does_not_affect_the_article(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1001), art(1001, images=["http://x/a.png"]), summ()])
        h.fail_images = True
        self.assertEqual(h.run(), 0)
        self.assertEqual(h.store().get_article_row(1001)["status"], "fetched")


# ====================================================================== T018

class FailureHandlingTest(unittest.TestCase):
    def test_login_failure_aborts_keeps_existing_data_alerts_and_burns_the_daily_quota(self):
        h = Harness(self, clues=[clue()], script=lambda p: [summ(logged_in=False, stage_error="login_failed:bad_credentials",
                                                                  counters={"logins": 1})])
        s = h.store()
        s.upsert_discovered(1, "https://investanchors.com/user/vip_contents/1", "舊")
        s.mark_fetched(1, BODY)
        self.assertEqual(h.run(), 1)
        self.assertEqual(h.notes, [I.ALERT_TEXTS["login_failed"]])
        self.assertEqual(s.get_article_row(1)["status"], "fetched")
        self.assertEqual(len(s.unprocessed_mail_clues()), 1)
        run = s.recent_runs(1)[0]
        self.assertEqual((run["result"], run["logged_in"], run["login_ok"]), ("login_failed", 1, 0))
        h.clues.append(clue("<n@x>"))
        self.assertEqual(h.run(), 2)                                            # 同一天不得再試
        self.assertEqual(len(h.payloads), 1)

    def test_account_disabled_halts_schedule_until_resume(self):
        h = Harness(self, clues=[clue()], script=lambda p: [summ(logged_in=False, stage_error="login_failed:account_disabled")])
        h.run()
        self.assertEqual(h.notes, [I.ALERT_TEXTS["account_disabled"]])
        h.clock[0] = WED + datetime.timedelta(days=3)
        h.clues.append(clue("<n@x>"))
        self.assertEqual(h.run(), 2)
        self.assertEqual(len(h.payloads), 1)
        self.assertEqual(h.run(["--resume"]), 0)
        h.script = lambda p: [li(1), art(1), summ()]
        self.assertEqual(h.run(), 0)
        self.assertEqual(len(h.payloads), 2)

    def test_blocked_stops_run_keeps_what_was_fetched_and_delays_next_run_one_day(self):
        script = lambda p: [li(1), li(2), art(1), summ(blocked=True, stage_error="blocked_unexpected_page")]
        h = Harness(self, clues=[clue()], script=script)
        self.assertEqual(h.run(), 1)
        s = h.store()
        self.assertEqual(s.get_article_row(1)["status"], "fetched")
        self.assertEqual(s.get_article_row(2)["status"], "discovered")           # 沒抓到的不算失敗
        self.assertEqual(s.get_article_row(2)["attempts"], 0)
        self.assertEqual(s.blocked_until(), WED + datetime.timedelta(days=1))
        self.assertIn(I.ALERT_TEXTS["blocked"], h.notes)
        self.assertEqual(s.recent_runs(1)[0]["result"], "blocked")

    def test_structure_change_marks_failed_without_partial_body_and_alerts(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), li(2), err(1, "structure"), art(2), summ()])
        self.assertEqual(h.run(), 1)
        s = h.store()
        r1 = s.get_article_row(1)
        self.assertEqual((r1["status"], r1["attempts"], r1["body"], r1["last_error"]),
                         ("failed", 1, None, "article_error:structure"))
        self.assertEqual(s.get_article_row(2)["status"], "fetched")              # 一篇失敗不影響他篇
        self.assertIn(I.ALERT_TEXTS["structure_changed"], h.notes)

    def test_short_body_from_scraper_is_failed_not_stored(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), art(1, body="太短"), summ()])
        h.run()
        r = h.store().get_article_row(1)
        self.assertEqual((r["status"], r["body"]), ("failed", None))

    def test_failed_article_is_not_retried_in_the_same_run_but_next_run(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), err(1, "timeout"), summ()])
        h.run()
        self.assertEqual(len(h.payloads), 1)                                     # 同次不重試
        h.clock[0] = WED + datetime.timedelta(days=1)
        h.clues.append(clue("<n@x>"))
        h.script = lambda p: [summ()]
        h.run()
        self.assertEqual(h.payloads[1]["pending_ids"], [1])                      # 下次排程才試

    def test_third_failure_abandons_and_alerts_once_then_stops_retrying(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), err(1, "timeout"), summ()])
        for d in range(3):
            h.clock[0] = WED + datetime.timedelta(days=d)
            h.clues.append(clue("<n%d@x>" % d))
            h.run()
            h.script = lambda p: [err(1, "timeout"), summ()]
        r = h.store().get_article_row(1)
        self.assertEqual((r["status"], r["attempts"]), ("abandoned", 3))
        self.assertEqual(h.notes.count(I.ALERT_TEXTS["article_abandoned"]), 1)
        h.clock[0] = WED + datetime.timedelta(days=3)
        h.clues.append(clue("<n9@x>"))
        h.run()
        self.assertEqual(h.payloads[-1]["pending_ids"], [])

    def test_last_error_is_redacted_even_if_scraper_reason_contains_a_secret(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), err(1, "boom " + PW), summ()])
        h.run()
        le = h.store().get_article_row(1)["last_error"]
        self.assertNotIn(PW, le)

    def test_scraper_exception_is_a_failed_run_without_leaking_credentials(self):
        h = Harness(self, clues=[clue()])
        h.script = lambda p: (_ for _ in ()).throw(RuntimeError("crash with %s" % PW))
        self.assertEqual(h.run(), 1)
        self.assertNotIn(PW, h.out.getvalue())
        run = h.store().recent_runs(1)[0]
        self.assertEqual((run["result"], run["logged_in"]), ("scraper_error", 1))  # 額度已扣
        self.assertEqual(run["logged_out"], 0)


# ====================================================================== T019

class LogoutAndNotificationTest(unittest.TestCase):
    def test_unverified_logout_is_recorded_and_alerted_immediately(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1), art(1), summ(logout_verified=False, logged_out=False)])
        self.assertEqual(h.run(), 1)
        self.assertIn(I.ALERT_TEXTS["logout_unverified"], h.notes)
        s = h.store()
        self.assertEqual([r["logged_out"] for r in s.unverified_logout_runs()], [0])

    def test_missing_summary_counts_as_unverified_logout(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1)])
        self.assertEqual(h.run(), 1)
        self.assertIn(I.ALERT_TEXTS["logout_unverified"], h.notes)
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "scraper_error")

    def test_verified_logout_is_recorded_as_one_and_no_alert(self):
        h = Harness(self, clues=[clue()])
        h.run()
        self.assertEqual(h.store().recent_runs(1)[0]["logged_out"], 1)
        self.assertNotIn(I.ALERT_TEXTS["logout_unverified"], h.notes)

    def test_no_browser_is_not_reported_as_unverified_logout(self):
        h = Harness(self, clues=[clue()], script=lambda p: [summ(logged_in=False, logout_verified=False, stage_error="no_browser")])
        h.run()
        self.assertNotIn(I.ALERT_TEXTS["logout_unverified"], h.notes)

    def test_alert_texts_are_fixed_and_dedupe_per_day(self):
        h = Harness(self)
        s = h.store()
        imp = I.Importer(None, notifier=h.notes.append, now=lambda: h.clock[0])
        self.assertTrue(imp.alert(s, "blocked"))
        self.assertFalse(imp.alert(s, "blocked"))
        self.assertTrue(imp.alert(s, "login_failed"))
        self.assertEqual(len(h.notes), 2)
        h.clock[0] = WED + datetime.timedelta(days=1)
        self.assertTrue(imp.alert(s, "blocked"))                                 # 隔天可再通知
        for text in I.ALERT_TEXTS.values():
            investanchors_redact.assert_clean(text, [PW, EMAIL])

    def test_notifier_failure_never_breaks_the_import(self):
        def boom(text):
            raise RuntimeError("telegram down")
        h = Harness(self, clues=[clue()])
        self.assertEqual(h.run(notifier=boom), 0)
        self.assertEqual(h.store().get_article_row(1001)["status"], "fetched")


def _id_at(dt, k=1):
    """造一個「前 13 位是 epoch 毫秒」的 14 位數文章 ID。"""
    return int(dt.timestamp() * 1000) * 10 + k


class DataDirGuardTest(unittest.TestCase):
    """審查 #1：--data-dir 必填；指向正式庫（含 symlink）沒有旗標就在取信、登入、寫入之前拒絕。"""

    def setUp(self):
        import article_data_guard
        self.guard = article_data_guard
        self.prod = article_data_guard.PRODUCTION_DATA_DIR
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.touched = []

    def _boom(self, *a, **k):
        self.touched.append(1)
        raise AssertionError("must not be called")

    def _run(self, argv):
        out = io.StringIO()
        env = dict(os.environ)
        env.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
        old = os.environ
        os.environ = env
        try:
            rc = I.run(argv, fetch_mail=self._boom, run_scraper=self._boom, get_secret=self._boom,
                       notifier=self._boom, out=out)
        finally:
            os.environ = old
        return rc, out.getvalue()

    def test_data_dir_is_required_and_has_no_default(self):
        with self.assertRaises(SystemExit):
            I.build_parser().parse_args([])
        with self.assertRaises(SystemExit):
            I.build_parser().parse_args(["--dry-run"])
        self.assertFalse(hasattr(I, "DEFAULT_DATA_DIR"))

    def test_production_dir_refused_without_flag_for_normal_and_dry_run(self):
        for extra in ([], ["--dry-run"], ["--resume"]):
            rc, out = self._run(["--data-dir", self.prod] + extra)
            self.assertEqual(rc, 2)
            self.assertIn("拒絕執行", out)
        self.assertEqual(self.touched, [])

    def test_symlink_to_production_dir_is_also_refused(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.prod, link)
        rc, out = self._run(["--data-dir", link, "--dry-run"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.touched, [])
        with self.assertRaises(self.guard.DataDirRefused):
            self.guard.resolve_data_dir(link, env={})

    def test_flag_allows_production_and_other_dirs_need_no_flag(self):
        self.assertEqual(self.guard.resolve_data_dir(self.prod, env={"ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "1"}),
                         self.prod)
        self.assertEqual(self.guard.resolve_data_dir(self.tmp, env={}), os.path.realpath(self.tmp))
        with self.assertRaises(self.guard.DataDirRefused):
            self.guard.resolve_data_dir(self.prod, env={"ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "0"})
        with self.assertRaises(self.guard.DataDirRefused):
            self.guard.resolve_data_dir("", env={})

    def test_probe_uses_same_guard(self):
        import article_probe
        out = io.StringIO()
        rc = article_probe.run(["--data-dir", self.prod, "--confirm-po-present", "--confirm-one-device-only"],
                               get_secret=self._boom, scraper_runner=self._boom, out=out)
        self.assertEqual(rc, 2)
        rc = article_probe.run(["--confirm-po-present", "--confirm-one-device-only"],
                               get_secret=self._boom, scraper_runner=self._boom, out=out)
        self.assertEqual(rc, 2)
        self.assertEqual(self.touched, [])


class NotificationRecencyTest(unittest.TestCase):
    """審查 #3：7 天內逐篇通知；更早的合併成一則摘要（不列標題）；id_time_ok=0 視為近期。"""

    def test_recent_notified_individually_and_older_merged_into_one_summary(self):
        recent = _id_at(WED - datetime.timedelta(days=2))
        edge = _id_at(WED - datetime.timedelta(days=6, hours=23), 2)
        old1 = _id_at(WED - datetime.timedelta(days=8), 3)
        old2 = _id_at(WED - datetime.timedelta(days=60), 4)
        h = Harness(self, clues=[clue()], script=lambda p: [
            li(recent, "近期文"), li(edge, "邊界文"), li(old1, "舊文一"), li(old2, "舊文二"),
            art(recent), art(edge), art(old1), art(old2), summ()])
        self.assertEqual(h.run(), 0)
        singles = [n for n in h.notes if n.startswith("📰 定錨新文章")]
        self.assertEqual(len(singles), 2)
        self.assertTrue(any("近期文" in n for n in singles) and any("邊界文" in n for n in singles))
        merged = [n for n in h.notes if "補抓" in n]
        self.assertEqual(merged, ["📰 定錨補抓：已補抓 2 篇較早的文章"])
        self.assertFalse(any("舊文" in n for n in h.notes))

    def test_id_time_ok_zero_counts_as_recent(self):
        h = Harness(self, clues=[clue()], script=lambda p: [li(1001, "短ID文"), art(1001), summ()])
        h.run()
        self.assertEqual(h.store().get_article_row(1001)["id_time_ok"], 0)
        self.assertEqual(len(h.notes), 1)
        self.assertIn("短ID文", h.notes[0])

    def test_recency_constant_is_seven_days(self):
        self.assertEqual(I.RECENT_ARTICLE_DAYS, 7)

    def test_no_summary_when_nothing_old(self):
        recent = _id_at(WED - datetime.timedelta(hours=5))
        h = Harness(self, clues=[clue()], script=lambda p: [li(recent), art(recent), summ()])
        h.run()
        self.assertFalse(any("補抓" in n for n in h.notes))


class WeeklyCheckCompletionTest(unittest.TestCase):
    """審查 #2：核對日登入失敗或沒讀到清單，不算完成核對。"""

    def test_failed_weekly_run_is_not_counted_as_checked(self):
        h = Harness(self, now=SUN, script=lambda p: [summ(logged_in=False, stage_error="login_failed:bad_credentials")])
        h.run()
        self.assertIsNone(h.store().last_weekly_check())

    def test_blocked_without_list_is_not_counted(self):
        h = Harness(self, now=SUN, script=lambda p: [
            summ(blocked=True, counters={"logins": 1, "navigations": 1, "list_pages": 0, "articles_opened": 0})])
        h.run()
        self.assertIsNone(h.store().last_weekly_check())

    def test_successful_weekly_run_that_read_list_is_counted(self):
        h = Harness(self, now=SUN, script=lambda p: [li(1001), summ()])
        h.run()
        self.assertEqual(h.store().last_weekly_check(), SUN)
        self.assertEqual(h.store().recent_runs(1)[0]["list_pages"], 1)


if __name__ == "__main__":
    unittest.main()
