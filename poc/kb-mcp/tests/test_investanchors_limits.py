"""T009：低頻上限守衛（spec 驗收（a））。"""
import datetime
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_store  # noqa: E402
import investanchors_limits as L  # noqa: E402

TZ8 = L.TZ8


def T(day, hour=23, minute=0):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=TZ8)


class LimitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="limits-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = [T(15)]
        self.store = article_store.ArticleStore(self.tmp, now=lambda: self.clock[0])
        self.addCleanup(self.store.close)
        self.guard = L.LimitGuard(self.store, now=lambda: self.clock[0])

    def test_constants_are_the_conservative_starting_values(self):
        self.assertEqual((L.MAX_ARTICLES_PER_RUN, L.MAX_LOGINS_PER_DAY), (5, 1))
        self.assertEqual((L.DELAY_RANGE, L.IMAGE_DELAY_RANGE), ((30, 90), (5, 15)))
        self.assertEqual((L.MAX_ATTEMPTS_PER_ARTICLE, L.BLOCK_BACKOFF_DAYS, L.MAX_LIST_PAGES), (3, 1, 3))

    def test_first_login_allowed_second_same_day_refused(self):
        self.assertEqual(self.guard.may_login(), (True, "ok"))
        run = self.store.start_run("mail")
        self.store.mark_login_started(run)
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertEqual(reason, "daily_login_limit")
        self.clock[0] = T(16, 0, 30)                                 # 隔天放行
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_blocked_until_refuses_until_it_passes(self):
        run = self.store.start_run("mail")
        self.store.finish_run(run, True, 0, 0, "blocked", True, blocked_until=self.guard.block_until())
        self.clock[0] = T(16, 22, 59)
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("blocked_until:"))
        self.clock[0] = T(16, 23, 1)
        # 被擋那次本身算昨天的登入，今天沒有 → 放行
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_block_until_is_one_day_after_now(self):
        self.assertEqual(self.guard.block_until(), T(16))
        self.assertEqual(self.guard.block_until(T(20, 1)), T(21, 1))

    def test_cap_for_run_only_lowers(self):
        self.assertEqual(self.guard.cap_for_run(), 5)
        self.assertEqual(self.guard.cap_for_run(99), 5)
        self.assertEqual(self.guard.cap_for_run(1), 1)
        self.assertEqual(self.guard.cap_for_run(0), 0)
        self.assertEqual(self.guard.cap_for_run(-3), 0)

    def test_delay_sampling_stays_in_range_and_never_below_30s(self):
        rng = random.Random(7)
        samples = [self.guard.delay_seconds(rng) for _ in range(500)]
        self.assertGreaterEqual(min(samples), 30)
        self.assertLessEqual(max(samples), 90)
        img = [self.guard.image_delay_seconds(rng) for _ in range(500)]
        self.assertGreaterEqual(min(img), 5)
        self.assertLessEqual(max(img), 15)

    def test_refusal_triggers_no_login_via_fake_scraper_counter(self):
        calls = []

        def run_once():
            ok, reason = self.guard.may_login()
            if not ok:
                return reason
            run = self.store.start_run("mail")
            self.store.mark_login_started(run)
            calls.append(1)                                          # 假的 scraper 呼叫
            return "ran"

        self.assertEqual(run_once(), "ran")
        self.assertEqual(run_once(), "daily_login_limit")
        self.assertEqual(run_once(), "daily_login_limit")
        self.assertEqual(len(calls), 1)

    def test_naive_now_is_treated_as_taipei(self):
        g = L.LimitGuard(self.store, now=lambda: datetime.datetime(2026, 11, 15, 23, 0))
        self.assertEqual(g.now(), T(15))


if __name__ == "__main__":
    unittest.main()
