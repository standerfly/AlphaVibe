"""T013／T014：scraper `import` 模式（清單讀取＋文章擷取）——本機假網站＋真瀏覽器，無瀏覽器時 skip。"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import article_probe  # noqa: E402
from fake_investanchors_site import EMAIL, PASSWORD, FakeSite  # noqa: E402


def _browser_available():
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    return (os.path.exists(node)
            and os.path.isdir(os.path.join(article_probe.HERE, "scraper", "node_modules", "playwright"))
            and (os.path.exists("/Applications/Google Chrome.app")
                 or os.path.isdir(os.path.expanduser("~/Library/Caches/ms-playwright"))))


def run_import(test, site, **overrides):
    base = site.start()
    test.addCleanup(site.stop)
    payload = {"mode": "import", "email": EMAIL, "password": PASSWORD, "base_url": base,
               "known_ids": [], "pending_ids": [], "max_list_pages": 3, "max_articles": 5,
               "delay_ms": [30, 60], "timeout_ms": 15000}
    payload.update(overrides)
    objs = article_probe.default_scraper_runner(payload, timeout_sec=240, grace_sec=30)
    out = {"list_item": [], "article": [], "article_error": [], "fact": [], "summary": None, "raw": objs}
    for o in objs:
        if o.get("type") == "summary":
            out["summary"] = o
        else:
            out.setdefault(o.get("type"), []).append(o)
    return out


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class ImportModeListTest(unittest.TestCase):
    def test_reads_pages_marks_pinned_skips_announcement_and_caps_at_five(self):
        site = FakeSite()
        out = run_import(self, site)
        s = out["summary"]
        self.assertEqual((s["counters"]["logins"], s["counters"]["list_pages"]), (1, 2))
        self.assertTrue(s["logout_verified"])
        self.assertEqual(site.sessions, set())
        items = out["list_item"]
        self.assertEqual(len(items), 12)                                    # 第 1 頁 8＋第 2 頁 4
        pinned = [i for i in items if i["pinned"]]
        self.assertEqual(sorted(set(i["article_id"] for i in pinned)), [777])
        self.assertEqual(len(pinned), 2)                                    # 兩頁各出現一次
        self.assertTrue([i for i in items if i["article_id"] == 9999][0]["is_announcement"])
        self.assertEqual([i["title"] for i in items if i["article_id"] == 1010], ["SECRETTITLE 1010"])
        targets = [f for f in out["fact"] if f["step"] == "targets"][0]["data"]["article_ids"]
        self.assertEqual(targets, [777, 1010, 1009, 1008, 1007])           # 清單順序、上限 5、不含公告
        self.assertEqual(site.article_requests(), targets)
        self.assertNotIn(9999, site.article_requests())

    def test_stops_after_first_page_when_everything_on_it_is_known(self):
        site = FakeSite()
        out = run_import(self, site, known_ids=[777, 1010, 1009, 1008, 1007, 1006, 1005, 9999])
        self.assertEqual(out["summary"]["counters"]["list_pages"], 1)
        self.assertEqual(set(i["page"] for i in out["list_item"]), {1})
        self.assertEqual(site.article_requests(), [])
        self.assertEqual([f for f in out["fact"] if f["step"] == "targets"][0]["data"]["article_ids"], [])

    def test_pending_ids_follow_fresh_ones_and_are_fetched_by_id(self):
        site = FakeSite()
        out = run_import(self, site, known_ids=[777, 1010, 1009, 1008, 1007, 1006, 1005, 9999],
                         pending_ids=[1002, 1001])
        self.assertEqual(site.article_requests(), [1002, 1001])
        self.assertEqual([a["article_id"] for a in out["article"]], [1002, 1001])

    def test_hard_caps_override_larger_requests(self):
        items = [{"id": 2000 + i, "title": "T%d" % i, "date": "2026-11-%02d" % (28 - i)} for i in range(30)]
        site = FakeSite(items=items, per_page=2, pinned=[], announcement=False)
        out = run_import(self, site, max_list_pages=99, max_articles=99)
        self.assertEqual(out["summary"]["counters"]["list_pages"], 3)       # ≤3 頁
        self.assertEqual(len(site.article_requests()), 5)                   # ≤5 篇

    def test_list_date_is_not_used_to_skip_anything(self):
        items = [{"id": 3001, "title": "老日期", "date": "2019-01-01"},
                 {"id": 3002, "title": "新日期", "date": "2026-11-14"}]
        site = FakeSite(items=items, per_page=6, pinned=[], announcement=False)
        out = run_import(self, site)
        self.assertEqual(site.article_requests(), [3001, 3002])


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class ImportModeArticleTest(unittest.TestCase):
    def test_article_extracts_body_published_at_and_content_images_only(self):
        items = [{"id": 4001, "title": "A", "date": "2026-11-14"}]
        site = FakeSite(items=items, pinned=[], announcement=False)
        out = run_import(self, site)
        art = out["article"][0]
        self.assertEqual(art["article_id"], 4001)
        self.assertGreaterEqual(len(art["body"]), 200)
        self.assertIn("SECRETBODY", art["body"])
        self.assertEqual(art["published_at"], "2026-11-14T12:00")
        self.assertEqual([i["seq"] for i in art["images"]], [1, 2])         # 站台 logo 不算內文圖
        self.assertTrue(all(i["src_url"].startswith("http://127.0.0.1:") for i in art["images"]))
        self.assertNotIn("logo.png", " ".join(i["src_url"] for i in art["images"]))

    def test_article_without_images_has_empty_image_list(self):
        items = [{"id": 4002, "title": "A", "date": "2026-11-14"}]
        site = FakeSite(items=items, pinned=[], announcement=False, default_article_mode="no_image")
        out = run_import(self, site)
        self.assertEqual(out["article"][0]["images"], [])

    def test_missing_container_and_short_body_never_emit_partial_text(self):
        items = [{"id": 5001, "title": "A", "date": "2026-11-14"}, {"id": 5002, "title": "B", "date": "2026-11-13"},
                 {"id": 5003, "title": "C", "date": "2026-11-12"}]
        site = FakeSite(items=items, pinned=[], announcement=False,
                        article_modes={5001: "no_container", 5002: "short"})
        out = run_import(self, site)
        errs = dict((e["article_id"], e["reason"]) for e in out["article_error"])
        self.assertEqual(errs, {5001: "structure", 5002: "short"})
        self.assertEqual([a["article_id"] for a in out["article"]], [5003])
        self.assertNotIn("太短", str(out["raw"]))                            # 殘缺內文不得輸出
        self.assertEqual(site.sessions, set())

    def test_two_consecutive_timeouts_mean_blocked_and_stop_opening_more(self):
        items = [{"id": 6000 + i, "title": "T%d" % i, "date": "2026-11-%02d" % (20 - i)} for i in range(4)]
        site = FakeSite(items=items, pinned=[], announcement=False, timeout_sleep=4.0,
                        article_modes={6000: "timeout", 6001: "timeout"})
        out = run_import(self, site, timeout_ms=1500)
        s = out["summary"]
        self.assertTrue(s["blocked"])
        self.assertEqual(s["stage_error"], "blocked_timeouts")
        self.assertEqual(site.article_requests(), [6000, 6001])             # 第 3、4 篇不再開
        self.assertEqual([e["reason"] for e in out["article_error"]], ["timeout"])
        self.assertTrue(s["logout_verified"])
        self.assertEqual(site.sessions, set())

    def test_forbidden_article_means_blocked_and_logout_still_verified(self):
        items = [{"id": 7001, "title": "A", "date": "2026-11-14"}, {"id": 7002, "title": "B", "date": "2026-11-13"}]
        site = FakeSite(items=items, pinned=[], announcement=False, article_modes={7001: "forbidden"})
        out = run_import(self, site)
        s = out["summary"]
        self.assertTrue(s["blocked"])
        self.assertEqual(site.article_requests(), [7001])
        self.assertTrue(s["logout_verified"])
        self.assertEqual(site.sessions, set())

    def test_single_timeout_is_a_failure_for_that_article_only(self):
        items = [{"id": 8001, "title": "A", "date": "2026-11-14"}, {"id": 8002, "title": "B", "date": "2026-11-13"}]
        site = FakeSite(items=items, pinned=[], announcement=False, timeout_sleep=4.0,
                        article_modes={8001: "timeout"})
        out = run_import(self, site, timeout_ms=1500)
        self.assertFalse(out["summary"]["blocked"])
        self.assertEqual([e["article_id"] for e in out["article_error"]], [8001])
        self.assertEqual([a["article_id"] for a in out["article"]], [8002])


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class ImportModeLoginTest(unittest.TestCase):
    def test_wrong_password_stops_before_any_list_or_article(self):
        site = FakeSite()
        out = run_import(self, site, password="wrong")
        s = out["summary"]
        self.assertEqual(s["stage_error"], "login_failed:bad_credentials")
        self.assertEqual(out["list_item"], [])
        self.assertEqual(site.article_requests(), [])
        self.assertEqual(s["counters"]["logins"], 1)
        self.assertEqual(site.sessions, set())

    def test_normal_run_logs_in_exactly_once_and_logs_out_server_side(self):
        site = FakeSite()
        out = run_import(self, site)
        self.assertEqual(len(site.login_posts()), 1)
        self.assertTrue(out["summary"]["logged_out"] and out["summary"]["logout_verified"])
        self.assertEqual(site.sessions, set())
        self.assertNotIn(PASSWORD, str(out["raw"]))


if __name__ == "__main__":
    unittest.main()
