"""T020：匯入端到端——本機假網站＋真 scraper＋假信箱＋假 Telegram（無瀏覽器環境 skip）。"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import article_images  # noqa: E402
import article_probe  # noqa: E402
from fake_investanchors_site import EMAIL, PASSWORD, FakeSite  # noqa: E402
from test_investanchors_import import WED, Harness, clue  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402


class E2E(Harness):
    """沿用 Harness 的假信箱／假 Telegram／假鑰匙圈，但改用真 scraper 與真圖片下載。"""

    def __init__(self, test, site, **kw):
        Harness.__init__(self, test, **kw)
        self.site = site
        self.base = site.start()
        test.addCleanup(site.stop)

    def _secret(self, account, runner=None, service=None):
        if service == keychain_service():
            return {"email": EMAIL, "password": PASSWORD}[account]
        return Harness._secret(self, account, runner, service)

    def go(self, argv=None, **over):
        deps = dict(run_scraper=article_probe.default_scraper_runner, download_images=article_images.download_images,
                    base_url=self.base, timeout_ms=15000, delay_ms=[30, 60])
        deps.update(over)
        return self.run(argv, **deps)


def keychain_service():
    import keychain_secrets
    return keychain_secrets.INVESTANCHORS_SERVICE


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class ImportEndToEndTest(unittest.TestCase):
    def test_new_mail_imports_articles_logs_out_server_side_and_notifies_title_and_link(self):
        site = FakeSite()
        h = E2E(self, site, clues=[clue()])
        self.assertEqual(h.go(), 0, h.out.getvalue())
        s = h.store()
        self.assertEqual(s.count_by_status().get("fetched"), 5)                  # 單次上限 5 篇
        self.assertEqual(site.sessions, set(), "網站端不得留有登入狀態")
        run = s.recent_runs(1)[0]
        self.assertEqual((run["logged_in"], run["login_ok"], run["logged_out"], run["result"]), (1, 1, 1, "ok"))
        self.assertEqual(len(site.login_posts()), 1)
        self.assertEqual(len(h.notes), 5)
        self.assertTrue(all("定錨新文章" in n and "https://investanchors.com/user/vip_contents/" in n for n in h.notes))
        self.assertTrue(all("SECRETBODY" not in n for n in h.notes))
        r = s.get_article_row(1010)
        self.assertEqual((r["title"], r["published_at"]), ("SECRETTITLE 1010", "2026-11-14T12:00"))
        self.assertGreaterEqual(len(r["body"]), 200)
        imgs = s.list_images(1010)
        self.assertEqual(len(imgs), 2)
        self.assertIsNotNone(imgs[0]["file_path"])                                 # 公開圖已下載
        self.assertIsNone(imgs[1]["file_path"])                                    # 需登入才能下載的圖：失敗只標該圖

    def test_rerun_adds_zero_and_never_reopens_imported_articles(self):
        site = FakeSite()
        h = E2E(self, site, clues=[clue("<a@x>")])
        h.go()
        h.clock[0] = WED + datetime.timedelta(days=1)
        h.clues.append(clue("<b@x>"))
        self.assertEqual(h.go(), 0)                                                # 第二天：抓剩下的 5 篇
        self.assertEqual(h.store().count_by_status().get("fetched"), 10)
        first_batch = [777, 1010, 1009, 1008, 1007]
        opens = site.article_requests()
        self.assertEqual([i for i in opens if i in first_batch].count(1010), 1)    # 已入庫的不重複開啟
        h.clock[0] = WED + datetime.timedelta(days=2)
        h.clues.append(clue("<c@x>"))
        before = len(site.article_requests())
        self.assertEqual(h.go(), 0)                                                # 第三天：新增 0 篇
        self.assertEqual(len(site.article_requests()), before)
        self.assertEqual(h.store().count_by_status().get("fetched"), 10)
        self.assertEqual(site.sessions, set())

    def test_no_new_mail_and_not_weekly_means_zero_logins_on_the_site(self):
        site = FakeSite()
        h = E2E(self, site)                                                        # 週三、無信
        self.assertEqual(h.go(), 0)
        self.assertEqual(site.log, [])                                             # 連一個請求都沒有
        self.assertEqual(h.store().recent_runs(1)[0]["trigger"], "none")

    def test_pinned_and_announcement_handling(self):
        site = FakeSite()
        h = E2E(self, site, clues=[clue()])
        h.go()
        self.assertNotIn(9999, site.article_requests())                            # 公告不開啟
        s = h.store()
        self.assertEqual(s.get_article_row(9999)["status"], "skipped")
        self.assertEqual(s.get_article_row(777)["pinned"], 1)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM article WHERE article_id=777").fetchone()[0], 1)

    def test_more_pending_than_the_cap_only_takes_five_and_leaves_the_rest(self):
        site = FakeSite()
        h = E2E(self, site, clues=[clue()])
        h.go()
        s = h.store()
        self.assertEqual(len(site.article_requests()), 5)
        self.assertEqual(s.count_by_status().get("discovered"), 5)                  # 其餘留待之後

    def test_blocked_run_stops_records_delay_and_still_logs_out(self):
        site = FakeSite(article_modes={1010: "forbidden"})
        h = E2E(self, site, clues=[clue()])
        self.assertEqual(h.go(), 1)
        s = h.store()
        run = s.recent_runs(1)[0]
        self.assertEqual((run["result"], run["logged_out"]), ("blocked", 1))
        self.assertEqual(s.blocked_until(), WED + datetime.timedelta(days=1))
        self.assertEqual(site.sessions, set())
        h.clock[0] = WED + datetime.timedelta(hours=10)
        h.clues.append(clue("<n@x>"))
        self.assertEqual(h.go(), 2)                                                # 延後期內被拒、不登入
        self.assertEqual(len(site.login_posts()), 1)


if __name__ == "__main__":
    unittest.main()
