"""T013／T014：scraper `import` 模式（清單讀取＋文章擷取）——本機假網站＋真瀏覽器，無瀏覽器時 skip。"""
import datetime
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import article_id_time  # noqa: E402
import article_probe  # noqa: E402
from fake_investanchors_site import EMAIL, PASSWORD, FakeSite, fake_id  # noqa: E402


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


# ====================================================================== T043：回補清單翻頁

TZ8 = article_id_time.TZ8
NOW = datetime.datetime(2026, 11, 11, 23, 0, tzinfo=TZ8)
CUT_DATE, CUT_MS = article_id_time.cutoff_for(NOW.date())
NOW_MS = int(NOW.timestamp() * 1000)
THRESH = article_id_time.defer_thresholds(CUT_MS, NOW_MS)


def _aid(days_ago, n=1):
    return fake_id(NOW - datetime.timedelta(days=days_ago), n)


def _items(days):
    return [{"id": _aid(d, i % 10), "title": "T%d" % d, "date": "2026-11-01"} for i, d in enumerate(days)]


def run_backfill(test, site, cursor=2, **overrides):
    payload = dict(THRESH)
    payload["resume_cursor"] = cursor
    payload.update(overrides)
    return run_import(test, site, **payload)


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class BackfillListPagingTest(unittest.TestCase):
    def test_jumps_to_cursor_pages_by_url_and_stops_after_page_cap(self):
        site = FakeSite(items=_items(range(1, 25)), per_page=4, pinned=[], announcement=False)
        out = run_backfill(self, site, cursor=3)
        self.assertEqual(site.page_log, [1, 3, 4])                          # 第 1 頁＋游標起 2 頁；不逐頁走、不碰第 2、5 頁
        self.assertEqual(out["summary"]["counters"]["list_pages"], 3)
        self.assertEqual(sorted(set(i["page"] for i in out["list_item"])), [1, 3, 4])
        self.assertTrue(out["summary"]["logout_verified"])
        self.assertEqual(site.sessions, set())

    def test_total_pages_never_exceed_max_list_pages(self):
        site = FakeSite(items=_items(range(1, 25)), per_page=4, pinned=[], announcement=False)
        run_backfill(self, site, cursor=3, max_list_pages=2)
        self.assertEqual(site.page_log, [1, 3])
        site2 = FakeSite(items=_items(range(1, 25)), per_page=4, pinned=[], announcement=False)
        run_backfill(self, site2, cursor=3, max_list_pages=99)
        self.assertEqual(site2.page_log, [1, 3, 4])                         # 硬上限 3 頁

    def test_all_old_pages_do_not_make_it_walk_further_or_open_deferred(self):
        site = FakeSite(items=_items(range(230, 260)), per_page=4, pinned=[], announcement=False)
        out = run_backfill(self, site, cursor=2)
        self.assertEqual(site.page_log, [1, 2, 3])                          # 停在頁數上限，不往更舊翻
        self.assertTrue(all(i["defer"] for i in out["list_item"]))
        self.assertEqual(site.article_requests(), [])                       # 延後的一篇都不開啟
        targets = [f for f in out["fact"] if f["step"] == "targets"][0]["data"]["article_ids"]
        self.assertEqual(targets, [])

    def test_defer_flag_follows_integer_thresholds_and_deferred_are_not_targets(self):
        recent, old = _aid(10, 1), _aid(300, 2)
        site = FakeSite(items=[{"id": recent, "title": "近", "date": "2026-11-01"},
                               {"id": old, "title": "舊", "date": "2026-11-01"}],
                        per_page=6, pinned=[], announcement=False)
        out = run_backfill(self, site, cursor=2)
        flags = dict((i["article_id"], i["defer"]) for i in out["list_item"])
        self.assertEqual(flags, {recent: False, old: True})
        self.assertEqual(site.article_requests(), [recent])

    def test_pinned_with_old_list_date_but_recent_id_is_deduped_across_non_adjacent_pages_and_opened_once(self):
        pinned = [{"id": _aid(2, 3), "title": "置頂", "date": "2021-02-06"}]
        site = FakeSite(items=_items(range(1, 25)), per_page=4, pinned=pinned, announcement=False)
        out = run_backfill(self, site, cursor=4)
        rows = [i for i in out["list_item"] if i["article_id"] == pinned[0]["id"]]
        self.assertEqual(sorted(r["page"] for r in rows), [1, 4, 5])
        self.assertTrue(all(r["pinned"] and not r["defer"] for r in rows))
        self.assertEqual(site.article_requests().count(pinned[0]["id"]), 1)
        self.assertIn(pinned[0]["id"], site.article_requests())

    def test_malformed_future_and_tiny_ids_are_never_deferred(self):
        future = fake_id(NOW + datetime.timedelta(days=30))
        tiny = 16000000000000 // 10                                          # 13 位，過小
        items = [{"id": 1001, "title": "短", "date": "2019-01-01"},
                 {"id": future, "title": "未來", "date": "2019-01-01"},
                 {"id": tiny, "title": "小", "date": "2019-01-01"}]
        site = FakeSite(items=items, per_page=6, pinned=[], announcement=False)
        out = run_backfill(self, site, cursor=2)
        self.assertFalse(any(i["defer"] for i in out["list_item"]))
        self.assertEqual(sorted(site.article_requests()), sorted([1001, future, tiny]))

    def test_targets_order_new_first_then_pending_then_cursor_pages(self):
        site = FakeSite(items=_items(range(1, 9)), per_page=2, pinned=[], announcement=False)
        ids = [i["id"] for i in site.items]
        out = run_backfill(self, site, cursor=3, pending_ids=[424242], max_articles=4)
        self.assertEqual([f for f in out["fact"] if f["step"] == "targets"][0]["data"]["article_ids"],
                         [ids[0], ids[1], 424242, ids[4]])

    def test_known_ids_are_not_reopened_on_cursor_pages(self):
        site = FakeSite(items=_items(range(1, 9)), per_page=2, pinned=[], announcement=False)
        ids = [i["id"] for i in site.items]
        run_backfill(self, site, cursor=3, known_ids=ids[4:6])
        self.assertNotIn(ids[4], site.article_requests())
        self.assertNotIn(ids[5], site.article_requests())

    def test_cursor_page_past_the_end_still_reads_and_reports_only_pinned_items(self):
        pinned = [{"id": _aid(2, 3), "title": "置頂", "date": "2021-02-06"}]
        site = FakeSite(items=_items(range(1, 5)), per_page=4, pinned=pinned, announcement=False)
        out = run_backfill(self, site, cursor=9)
        self.assertEqual(site.page_log, [1, 9, 10])
        self.assertEqual(set(i["article_id"] for i in out["list_item"] if i["page"] >= 9), {pinned[0]["id"]})


if __name__ == "__main__":
    unittest.main()
