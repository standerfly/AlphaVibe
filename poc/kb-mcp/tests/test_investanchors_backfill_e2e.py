"""010 T046：多日回補模擬（真 scraper＋假網站 127.0.0.1＋假時鐘，每「天」跑一次）。

情境：約 12 篇半年內＋6 篇更早＋置頂 4 篇（清單日期 2021 但 ID 近期）＋1 篇公告，每頁 4 篇。
- 每次最多 5 篇；此模擬每天只跑一次（每日 2 次的行為由 test_investanchors_backfill.TwiceDailyTest 覆蓋）；
- 第二天因登入失敗中斷（假網站暫時改密碼），第三天接續、不重抓、不遺漏；
- 更早的 6 篇只有 deferred 標記、從未被開啟；
- 完成後 completed=1，再跑不登入（日期避開週日核對：完成日的隔天是週一）；
- 最後用 article_reconcile（同一個假網站）核對：缺漏 0、重複 0，且 article 表前後完全相同、核對不開任何文章頁。
不連真實網路、不讀鑰匙圈、不動正式庫。無瀏覽器環境 skip。"""
import datetime
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import article_probe  # noqa: E402
import article_reconcile as R  # noqa: E402
import article_store  # noqa: E402
from fake_investanchors_site import PASSWORD, FakeSite  # noqa: E402
from test_article_reconcile import snapshot  # noqa: E402
from test_investanchors_backfill import BFE2E, aid_at  # noqa: E402
from test_investanchors_import import WED, clue  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402


def world():
    within = [{"id": aid_at(d, i), "title": "近%d" % d, "date": "2026-11-01"}
              for i, d in enumerate([2, 9, 16, 25, 40, 55, 75, 100, 125, 150, 170, 185])]
    older = [{"id": aid_at(d, i), "title": "舊%d" % d, "date": "2026-11-01"}
             for i, d in enumerate([215, 235, 260, 285, 310, 340])]
    pinned = [{"id": aid_at(1 + k, 5 + k), "title": "置頂%d" % k, "date": "2021-02-06"} for k in range(4)]
    return within, older, pinned


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class MultiDayBackfillWithReconcileTest(unittest.TestCase):
    def test_five_per_day_interrupt_resume_older_only_deferred_no_login_after_done_then_reconcile_clean(self):
        within, older, pinned = world()
        site = FakeSite(items=within + older, per_page=4, pinned=pinned, announcement=True)
        h = BFE2E(self, site, clues=[clue()])
        fetched_ids = lambda: set(r[0] for r in h.store().conn.execute(      # noqa: E731
            "SELECT article_id FROM article WHERE status='fetched'"))
        daily_logins, fetched_after, done = [], [], None
        for d in range(0, 8):
            h.clock[0] = WED + datetime.timedelta(days=d)
            site.password = "wrong-password" if d == 1 else PASSWORD         # 第二天登入失敗＝中斷
            before = len(site.login_posts())
            rc = h.go()
            daily_logins.append(len(site.login_posts()) - before)
            self.assertIn(rc, (0, 1), h.out.getvalue())
            self.assertEqual(site.sessions, set())
            fetched_after.append(len(fetched_ids()))
            if h.store().get_backfill_state()["completed"]:
                done = d
                break
        self.assertIsNotNone(done, h.out.getvalue())
        # 此 e2e 每個「模擬日」只執行一次：登入 1 次、至多 5 篇（每日上限 2 次見 test_investanchors_limits）
        self.assertTrue(all(n <= 1 for n in daily_logins), daily_logins)
        steps = [fetched_after[0]] + [b - a for a, b in zip(fetched_after, fetched_after[1:])]
        self.assertTrue(all(0 <= s <= 5 for s in steps), steps)
        # 第二天（d=1）中斷：登入失敗、沒抓到任何一篇；第三天接續
        self.assertEqual(steps[1], 0)
        self.assertGreater(steps[2], 0)
        # 全部半年內（含置頂）入庫；更早的只有 deferred、從未被開啟
        self.assertEqual(fetched_ids(), set(x["id"] for x in within) | set(p["id"] for p in pinned))
        s = h.store()
        self.assertEqual(set(r["article_id"] for r in s.deferred_rows()), set(o["id"] for o in older))
        opens = site.article_requests()
        self.assertEqual(len(opens), len(set(opens)))                          # 一篇都沒重開
        self.assertFalse(set(opens) & set(o["id"] for o in older))
        self.assertEqual(s.get_backfill_state()["completed"], 1)
        # 完成後再跑不登入；那天不是週日（避開週日核對）
        nxt = WED + datetime.timedelta(days=done + 1)
        self.assertNotEqual(nxt.weekday(), 6, "測試日期落在週日會觸發每週核對登入，請調整情境")
        h.clock[0] = nxt
        n_logins, n_opens = len(site.login_posts()), len(site.article_requests())
        self.assertEqual(h.go(), 0, h.out.getvalue())
        self.assertEqual((len(site.login_posts()), len(site.article_requests())), (n_logins, n_opens))

        # ---- 逐篇核對（同一個假網站、同一個資料目錄；當天匯入沒登入，額度還在）----
        before = snapshot(h.tmp)
        opens_before = len(site.article_requests())
        last = None
        for k in range(0, 4):
            h.clock[0] = nxt + datetime.timedelta(days=k)
            out = io.StringIO()
            args = R.build_parser().parse_args(["--data-dir", h.tmp])
            rec = R.Reconciler(args, run_scraper=article_probe.default_scraper_runner, get_secret=h._secret,
                               now=lambda: h.clock[0], base_url=h.base, delay_ms=[30, 60], timeout_ms=15000,
                               out=out)
            self.assertEqual(rec.main(), 0, out.getvalue())
            self.assertEqual(site.sessions, set())
            last = rec.report
            if last["scan_complete"]:
                break
        self.assertTrue(last["scan_complete"], out.getvalue())
        self.assertEqual((last["missing"], last["duplicates"], last["not_fetched"]), ([], [], []))
        self.assertEqual(last["older_deferred"], len(older))
        self.assertEqual(last["recent_ok"], len(within) + len(pinned))
        self.assertEqual(len(site.article_requests()), opens_before)           # 核對沒有開任何文章頁
        self.assertEqual(snapshot(h.tmp), before)                              # article 表前後完全相同


if __name__ == "__main__":
    unittest.main()
