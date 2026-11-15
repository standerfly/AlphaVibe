"""010 T045：article_reconcile.py（SC-001 逐篇核對，唯讀）。

只用假網站（127.0.0.1）與假時鐘；快測用「會模擬瀏覽器端規則的假 scraper」（沿用回補測試的 ListScraper），
另有一條跑真 scraper＋假網站（無瀏覽器環境 skip）。不連真實網路、不讀鑰匙圈（注入假 get_secret）、不動正式庫。"""
import datetime
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import article_data_guard  # noqa: E402
import article_id_time  # noqa: E402
import article_reconcile as R  # noqa: E402
import article_store  # noqa: E402
import investanchors_limits  # noqa: E402
from fake_investanchors_site import EMAIL, PASSWORD, FakeSite  # noqa: E402
from test_investanchors_backfill import PINNED, ListScraper, aid_at, mk  # noqa: E402
from test_investanchors_import import BODY, WED, summ  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402

TZ8 = R.TZ8
CUT_DATE, CUT_MS = article_id_time.cutoff_for(WED.date())
TITLE_MARK = "SECRETTITLE"


def titled(days_ago, n):
    a = aid_at(days_ago, n)
    return {"id": a, "title": "%s%d" % (TITLE_MARK, a), "date": "2026-11-01", "ann": False}


def snapshot(data_dir):
    """article／article_image／backfill_state 三張表的完整內容（比對前後是否完全相同）。"""
    conn = sqlite3.connect(os.path.join(data_dir, article_store.DB_FILENAME))
    try:
        return dict((t, conn.execute("SELECT * FROM %s ORDER BY 1, 2" % t).fetchall())
                    for t in ("article", "article_image", "backfill_state"))
    finally:
        conn.close()


class RH(object):
    """核對工具的測試台：獨立資料目錄、假時鐘、假憑證；回補狀態預先建立（截止日固定）。"""

    def __init__(self, test, scraper=None):
        self.test = test
        self.tmp = tempfile.mkdtemp(prefix="reconcile-test-")
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = [WED]
        self.scraper = scraper
        self.payloads = []
        self.out = io.StringIO()
        self.secret_reads = 0
        s = self.store()
        s.start_backfill(CUT_DATE, CUT_MS, now=WED)
        s.close()

    def store(self):
        return article_store.ArticleStore(self.tmp, now=lambda: self.clock[0])

    def seed(self, rows, status="fetched"):
        """rows：mk()／titled() 產生的清單項目；status：fetched／deferred／discovered。"""
        s = self.store()
        try:
            for r in rows:
                s.upsert_discovered(r["id"], article_store_url(r["id"]), r["title"], list_date=r["date"],
                                    via="backfill", now=WED)
                if status == "fetched":
                    s.mark_fetched(r["id"], BODY, "2026-11-01T12:00", now=WED)
                elif status == "deferred":
                    s.mark_deferred(r["id"])
        finally:
            s.close()

    def day(self, n):
        self.clock[0] = WED + datetime.timedelta(days=n)

    def _secret(self, account, runner=None, service=None):
        self.secret_reads += 1
        return {"email": EMAIL, "password": PASSWORD}[account]

    def _scraper(self, payload):
        self.payloads.append(payload)
        return self.scraper(payload)

    def run(self, argv=None, **over):
        deps = dict(run_scraper=self._scraper, get_secret=self._secret, now=lambda: self.clock[0],
                    delay_ms=[10, 20], out=self.out)
        deps.update(over)
        args = R.build_parser().parse_args(["--data-dir", self.tmp] + (argv or []))
        rec = R.Reconciler(args, **deps)
        rc = rec.main()
        self.report = rec.report
        return rc

    def logins(self):
        s = self.store()
        try:
            return s.conn.execute("SELECT COUNT(*) FROM import_runs WHERE trigger='reconcile'").fetchone()[0]
        finally:
            s.close()

    def probe_files(self):
        d = os.path.join(self.tmp, R.PROBE_DIRNAME)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


def article_store_url(aid):
    return "https://investanchors.com/user/vip_contents/%d" % aid


def two_page_world():
    """第 1 頁：置頂一＋公告＋4 篇近期；第 2 頁：近期 2 篇；第 3、4 頁：全部早於門檻（連續 2 頁全舊）。
    每次登入讀 3 頁（第 1 頁＋游標起 2 頁）→ 第一次讀 1、2、3；第二次讀 1、4、5 → 掃完。"""
    recent1 = [titled(6 + k, 1 + k) for k in range(4)]
    recent2 = [titled(20 + k, 1 + k) for k in range(2)]
    old3 = [titled(215 + k, 1 + k) for k in range(2)]
    old4 = [titled(240 + k, 1 + k) for k in range(2)]
    scraper = ListScraper(pages={1: recent1, 2: recent2, 3: old3, 4: old4, 5: []}, pinned=PINNED[:1])
    return scraper, recent1 + recent2, old3 + old4


class ReconcileCasesTest(unittest.TestCase):
    def test_missing_duplicate_pinned_and_deferred_each_reported_after_two_runs(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        pinned_row = {"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}
        missing = recent[1]                                       # 清單有、庫裡沒有
        h.seed([r for r in recent if r is not missing])
        h.seed([pinned_row])                                      # 置頂（清單日期 2021 但 ID 近期）：已入庫 → 不是缺漏
        h.seed(old, status="deferred")                            # 更早的：只有 deferred
        dup_of = recent[0]                                        # 另一筆不同 ID、同標題同清單日期 → 實質重複
        dup_id = aid_at(7, 9)
        h.seed([{"id": dup_id, "title": dup_of["title"], "date": dup_of["date"]}])
        self.assertEqual(h.run(), 1, h.out.getvalue())            # 第一次：1、2、3 頁，尚未掃完
        self.assertFalse(h.report["scan_complete"])
        h.day(1)
        self.assertEqual(h.run(), 1, h.out.getvalue())            # 第二次（隔天）：1、4、5 頁 → 掃完
        rep = h.report
        self.assertTrue(rep["scan_complete"])
        self.assertEqual(rep["missing"], [missing["id"]])
        self.assertEqual(rep["duplicates"], [sorted([dup_of["id"], dup_id])])
        self.assertEqual(rep["older_deferred"], len(old))        # 早於截止日：只確認為 deferred
        self.assertEqual(rep["older_not_deferred"], [])
        self.assertNotIn(PINNED[0]["id"], rep["missing"])        # 置頂近期文章已入庫，不算缺漏
        self.assertEqual(rep["recent_ok"], len(recent) - 1 + 1)  # 近期已入庫（含置頂一篇，不含缺漏）
        self.assertEqual(rep["not_fetched"], [])
        self.assertEqual([p for p in scraper.read_pages], [[1, 2, 3], [1, 4, 5]])

    def test_clean_state_reports_zero_missing_zero_duplicates_and_exit_zero(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        h.seed([{"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}])
        h.seed(old, status="deferred")
        self.assertEqual(h.run(), 0, h.out.getvalue())
        h.day(1)
        self.assertEqual(h.run(), 0, h.out.getvalue())
        self.assertEqual((h.report["missing"], h.report["duplicates"], h.report["scan_complete"]),
                         ([], [], True))

    def test_deferred_case_older_item_not_in_db_is_hint_not_missing(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        h.seed([{"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}])
        h.seed(old[:-1], status="deferred")                       # 最後一篇更早的沒被標延後
        h.run()
        h.day(1)
        self.assertEqual(h.run(), 0, h.out.getvalue())            # 提示用，不算缺漏
        self.assertEqual(h.report["missing"], [])
        self.assertEqual(h.report["older_not_deferred"], [{"id": old[-1]["id"], "status": "absent"}])

    def test_recent_item_in_db_but_not_fetched_is_reported_separately(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent[1:])
        h.seed([recent[0]], status="discovered")
        h.seed([{"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}])
        h.seed(old, status="deferred")
        h.run()
        h.day(1)
        self.assertEqual(h.run(), 0)
        self.assertEqual(h.report["not_fetched"], [{"id": recent[0]["id"], "status": "discovered"}])
        self.assertEqual(h.report["missing"], [])

    def test_db_rows_absent_from_list_only_reported_when_scan_complete(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        extra = titled(30, 4)
        h.seed([extra])
        h.seed([{"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}])
        h.seed(old, status="deferred")
        h.run()
        self.assertEqual(h.report["db_not_in_list"], [])         # 掃到一半：不下判斷
        h.day(1)
        h.run()
        self.assertEqual(h.report["db_not_in_list"], [{"id": extra["id"], "status": "fetched"}])


class ReadOnlyAndLimitsTest(unittest.TestCase):
    def test_article_table_is_identical_before_and_after_every_run(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent[:3])
        h.seed(old, status="deferred")
        before = snapshot(h.tmp)
        h.run()
        h.day(1)
        h.run()
        h.run(["--report-only"])
        self.assertEqual(snapshot(h.tmp), before)

    def test_payload_never_asks_for_article_pages(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        h.run()
        p = h.payloads[0]
        self.assertEqual((p["mode"], p["max_articles"], p["pending_ids"]), ("import", 0, []))
        self.assertEqual(scraper.opened, [])                      # 假 scraper 依 payload 算出的目標＝空
        self.assertLessEqual(p["max_list_pages"], investanchors_limits.MAX_LIST_PAGES)
        self.assertLessEqual(scraper.max_pages_seen, 3)
        self.assertEqual(p["resume_cursor"], 2)

    def test_one_login_per_day_second_run_same_day_is_refused_without_scraper(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        self.assertIn(h.run(), (0, 1))
        self.assertEqual(h.run(), 2)
        self.assertIn("daily_login_limit", h.out.getvalue())
        self.assertEqual(len(h.payloads), 1)
        self.assertEqual(h.logins(), 1)                           # 登入計入當日額度（走同一個 LimitGuard）

    def test_login_shares_the_daily_quota_with_the_importer(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        s = h.store()
        rid = s.start_run("mail")
        s.mark_login_started(rid)                                 # 今天匯入已登入過
        s.finish_run(rid, True, 0, 0, "ok", True)
        s.close()
        self.assertEqual(h.run(), 2)
        self.assertEqual(h.payloads, [])

    def test_blocked_postpones_next_day_and_does_not_advance_progress(self):
        blocked = lambda p: [summ(blocked=True, stage_error="blocked_timeouts")]  # noqa: E731
        h = RH(self, blocked)
        self.assertEqual(h.run(), 1)
        self.assertFalse(os.path.exists(os.path.join(h.tmp, R.PROBE_DIRNAME, R.STATE_FILENAME)))
        h.clock[0] = WED + datetime.timedelta(hours=12)           # 隔天中午仍在延後期內
        self.assertEqual(h.run(), 2)
        self.assertEqual(len(h.payloads), 1)

    def test_login_failure_does_not_advance_progress_and_is_not_retried_same_day(self):
        h = RH(self, lambda p: [summ(logged_in=False, stage_error="login_failed:bad_credentials")])
        self.assertEqual(h.run(), 1)
        self.assertEqual(h.run(), 2)
        self.assertEqual(len(h.payloads), 1)

    def test_complete_scan_and_report_only_never_login(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent)
        h.seed([{"id": PINNED[0]["id"], "title": PINNED[0]["title"], "date": "2021-02-06"}])
        h.seed(old, status="deferred")
        h.run()
        h.day(1)
        h.run()
        n = len(h.payloads)
        h.day(2)
        self.assertEqual(h.run(), 0)                              # 已掃完：不登入
        self.assertEqual(h.run(["--report-only"]), 0)
        self.assertEqual(len(h.payloads), n)
        h.day(3)
        h.run(["--restart"])                                      # 明確要求才重掃
        self.assertEqual(len(h.payloads), n + 1)
        self.assertEqual(h.payloads[-1]["resume_cursor"], 2)

    def test_widening_the_cutoff_invalidates_old_progress(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.run()
        h.day(1)
        h.run()
        d, ms = article_id_time.cutoff_from_date(datetime.date(2026, 3, 1))
        s = h.store()
        s.widen_cutoff(d, ms, now=h.clock[0])
        s.close()
        h.day(2)
        h.run()
        self.assertEqual(h.payloads[-1]["resume_cursor"], 2)      # 進度作廢，從頭掃

    def test_cutoff_mismatch_does_not_advance_progress(self):
        scraper, recent, old = two_page_world()
        scraper.lie[recent[0]["id"]] = True                       # 瀏覽器端說要延後、Python 說不用
        h = RH(self, scraper)
        self.assertEqual(h.run(), 1)
        self.assertIn("不一致", h.out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(h.tmp, R.PROBE_DIRNAME, R.STATE_FILENAME)))

    def test_report_and_state_files_have_ids_only_no_titles_no_body_no_credentials(self):
        scraper, recent, old = two_page_world()
        h = RH(self, scraper)
        h.seed(recent[1:])
        h.run()
        h.day(1)
        h.run()
        files = h.probe_files()
        self.assertTrue(any(f.startswith("reconcile-2") for f in files), files)
        self.assertIn(R.STATE_FILENAME, files)
        blob = h.out.getvalue()
        for f in files:
            with open(os.path.join(h.tmp, R.PROBE_DIRNAME, f), encoding="utf-8") as fh:
                blob += fh.read()
        for bad in (TITLE_MARK, "SECRETBODY", PASSWORD, EMAIL, "置頂", "公告"):
            self.assertNotIn(bad, blob)


class DataDirGuardTest(unittest.TestCase):
    def test_production_dir_refused_without_flag_and_nothing_runs(self):
        called = []
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(article_data_guard.ALLOW_FLAG, None)
            out = io.StringIO()
            args = R.build_parser().parse_args(["--data-dir", article_data_guard.PRODUCTION_DATA_DIR])
            rc = R.Reconciler(args, run_scraper=lambda p: called.append(p), get_secret=lambda *a, **k: called.append(1),
                              out=out).main()
        self.assertEqual(rc, 2)
        self.assertEqual(called, [])
        self.assertIn("拒絕執行", out.getvalue())

    def test_data_dir_is_required(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                R.build_parser().parse_args([])

    def test_empty_data_dir_refused(self):
        out = io.StringIO()
        args = R.build_parser().parse_args(["--data-dir", ""])
        self.assertEqual(R.Reconciler(args, out=out).main(), 2)

    def test_missing_database_or_backfill_state_is_refused_without_creating_anything(self):
        tmp = tempfile.mkdtemp(prefix="reconcile-empty-")
        self.addCleanup(shutil.rmtree, tmp, True)
        out = io.StringIO()
        args = R.build_parser().parse_args(["--data-dir", tmp])
        self.assertEqual(R.Reconciler(args, out=out, run_scraper=self.fail).main(), 2)
        self.assertEqual(os.listdir(tmp), [])
        s = article_store.ArticleStore(tmp)                       # 庫存在但回補沒啟動
        s.close()
        self.assertEqual(R.Reconciler(args, out=out, run_scraper=self.fail).main(), 2)


class DuplicateDefinitionTest(unittest.TestCase):
    def test_same_title_and_date_or_same_url_with_different_ids(self):
        rows = [{"article_id": 1, "url": "https://investanchors.com/user/vip_contents/1", "title": "甲", "list_date": "d"},
                {"article_id": 2, "url": "https://www.investanchors.com/user/vip_contents/1/", "title": "乙", "list_date": "d"},
                {"article_id": 3, "url": "https://investanchors.com/user/vip_contents/3", "title": "丙", "list_date": "d"},
                {"article_id": 4, "url": "https://investanchors.com/user/vip_contents/4", "title": "丙", "list_date": "d"},
                {"article_id": 5, "url": "https://investanchors.com/user/vip_contents/5", "title": "丙", "list_date": "e"}]
        self.assertEqual(R.find_duplicates(rows), [[1, 2], [3, 4]])


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class RealScraperReconcileTest(unittest.TestCase):
    def test_real_flow_reads_lists_only_never_opens_an_article_and_logs_out(self):
        import article_probe
        recent = [{"id": aid_at(2 + 5 * k, k), "title": "近%d" % k, "date": "2026-11-01"} for k in range(4)]
        older = [{"id": aid_at(215 + 10 * k, k), "title": "舊%d" % k, "date": "2026-11-01"} for k in range(8)]
        pinned = [{"id": aid_at(1 + k, 5 + k), "title": "置頂%d" % k, "date": "2021-02-06"} for k in range(2)]
        site = FakeSite(items=recent + older, per_page=2, pinned=pinned, announcement=True)
        base = site.start()
        self.addCleanup(site.stop)
        h = RH(self, article_probe.default_scraper_runner)
        h.seed(recent + pinned)
        h.seed(older, status="deferred")
        before = snapshot(h.tmp)
        done = None
        for d in range(0, 6):
            h.day(d)
            rc = h.run(base_url=base, timeout_ms=15000, delay_ms=[30, 60])
            self.assertEqual(rc, 0, h.out.getvalue())
            self.assertEqual(site.sessions, set())                # 每次都已在伺服器端登出
            if h.report["scan_complete"]:
                done = d
                break
        self.assertIsNotNone(done, h.out.getvalue())
        self.assertEqual(site.article_requests(), [])             # 一篇文章頁都沒開
        self.assertEqual(len(site.login_posts()), done + 1)       # 每「天」1 次
        self.assertLessEqual(max(len(set(site.page_log[i:i + 3])) for i in range(0, len(site.page_log), 3)), 3)
        self.assertEqual(h.report["missing"], [])
        self.assertEqual(h.report["duplicates"], [])
        self.assertEqual(snapshot(h.tmp), before)


if __name__ == "__main__":
    unittest.main()
