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
        self.assertEqual((L.MAX_ARTICLES_PER_RUN, L.MAX_LOGINS_PER_DAY), (5, 2))
        self.assertEqual(L.MIN_LOGIN_GAP_HOURS, 6)
        self.assertEqual((L.DELAY_RANGE, L.IMAGE_DELAY_RANGE), ((30, 90), (5, 15)))
        self.assertEqual((L.MAX_ATTEMPTS_PER_ARTICLE, L.BLOCK_BACKOFF_DAYS, L.MAX_LIST_PAGES), (3, 1, 3))

    def _login(self, at, failed=False):
        """在 at 時間啟動一次登入（只寫執行紀錄，不碰網站）。"""
        self.clock[0] = at
        run = self.store.start_run("mail")
        self.store.mark_login_started(run)
        self.store.finish_run(run, not failed, 0, 0, "login_failed" if failed else "ok", None if failed else True)

    def test_two_logins_per_day_third_refused_and_next_day_resets(self):
        self.clock[0] = T(15, 12, 30)
        self.assertEqual(self.guard.may_login(), (True, "ok"))
        self._login(T(15, 12, 30))
        self.clock[0] = T(15, 23, 0)                                 # 相隔 10.5 小時 → 放行
        self.assertEqual(self.guard.may_login(), (True, "ok"))
        self._login(T(15, 23, 0))
        self.clock[0] = T(15, 23, 59)
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertEqual(reason, "daily_login_limit")                # 第 3 次：額度優先於間隔原因
        self.clock[0] = T(16, 12, 30)                                # 隔天（台北日期）重置，距上次 13.5 小時
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_min_gap_boundary_5h59_refused_exactly_6h_allowed(self):
        self._login(T(15, 6, 0))
        self.clock[0] = T(15, 11, 59)
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("min_gap:"), reason)
        self.assertNotEqual(reason, "daily_login_limit")
        self.assertIn(T(15, 12, 0).isoformat(), reason)              # 原因帶出最早可登入時間
        self.clock[0] = T(15, 12, 0)                                 # 剛好滿 6 小時 → 放行
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_min_gap_applies_across_midnight(self):
        self._login(T(15, 23, 30))
        self.clock[0] = T(16, 5, 29)                                 # 新的一天、額度重置但間隔不足
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("min_gap:"), reason)
        self.clock[0] = T(16, 5, 30)
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_failed_login_attempt_counts_for_quota_and_gap(self):
        # 密碼錯誤／帳號停用／被擋在登入頁：有嘗試但失敗，同樣計入當日次數與間隔
        self._login(T(15, 12, 30), failed=True)
        self.clock[0] = T(15, 13, 0)
        ok, reason = self.guard.may_login()
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("min_gap:"), reason)
        self._login(T(15, 19, 0), failed=True)                       # 第 2 次也失敗
        self.clock[0] = T(15, 23, 59)
        self.assertEqual(self.guard.may_login(), (False, "daily_login_limit"))
        self.clock[0] = T(16, 12, 30)
        self.assertEqual(self.guard.may_login(), (True, "ok"))

    def test_refused_runs_do_not_count_as_logins_nor_reset_the_gap(self):
        self._login(T(15, 12, 30))
        self.clock[0] = T(15, 13, 0)
        run = self.store.start_run("none")                           # 被拒絕的執行（logged_in=0）
        self.store.finish_run(run, None, 0, 0, "aborted_limit", None)
        self.assertEqual(self.store.logins_today(T(15, 13, 0)), 1)
        self.clock[0] = T(15, 18, 30)                                # 以最後一次「真登入」起算，不是被拒的那次
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
                return reason.split(":")[0]
            run = self.store.start_run("mail")
            self.store.mark_login_started(run)
            calls.append(1)                                          # 假的 scraper 呼叫
            return "ran"

        self.clock[0] = T(15, 12, 30)
        self.assertEqual(run_once(), "ran")
        self.clock[0] = T(15, 13, 0)
        self.assertEqual(run_once(), "min_gap")                      # 間隔不足
        self.clock[0] = T(15, 23, 0)
        self.assertEqual(run_once(), "ran")
        self.clock[0] = T(15, 23, 30)
        self.assertEqual(run_once(), "daily_login_limit")            # 第 3 次
        self.assertEqual(run_once(), "daily_login_limit")
        self.assertEqual(len(calls), 2)

    def test_naive_now_is_treated_as_taipei(self):
        g = L.LimitGuard(self.store, now=lambda: datetime.datetime(2026, 11, 15, 23, 0))
        self.assertEqual(g.now(), T(15))


if __name__ == "__main__":
    unittest.main()
