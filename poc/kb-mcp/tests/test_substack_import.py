"""`substack_import.py` 的測試。

T011：骨架——資料目錄防呆、執行鎖、互斥選項、退出碼（contracts/cli.md）。
T019：主流程（同步作者、14 天窗、去重、條件請求、寫入）。
T020：通知（逐篇格式、N 類提醒、節流、補發、摘要）。
T021：排程日判斷與牆鐘預算（假時鐘六個邊界）。

本檔案所有測試都用獨立 tempfile 資料目錄，零真實網路（一律注入 FakeHttp／FakeClock／FakeNotifier）。
"""
import datetime
import fcntl
import io
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import article_data_guard  # noqa: E402
import substack_html as H  # noqa: E402
import substack_import as IMP  # noqa: E402
import substack_store as S  # noqa: E402


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.notifier = F.FakeNotifier()
        self.out = io.StringIO()
        self.err = io.StringIO()

    def go(self, *args, **kwargs):
        argv = ["--data-dir", kwargs.pop("data_dir", self.dir)] + list(args)
        deps = {"http": self.http, "notifier": self.notifier, "clock": self.clock,
                "sleep": self.clock.sleep, "env": kwargs.pop("env", {}),
                "out": self.out, "err": self.err}
        deps.update(kwargs)
        return IMP.run(argv, **deps)

    @property
    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    def db_path(self):
        return os.path.join(self.dir, "substack.db")


class DataDirGuardTest(ImportTestBase):
    def test_missing_data_dir_refused(self):
        code = IMP.run([], http=self.http, out=self.out, err=self.err, env={})
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0)

    def test_production_data_dir_refused_before_anything(self):
        prod = article_data_guard.PRODUCTION_DATA_DIR
        before = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        code = self.go(data_dir=prod)
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0, "防呆要先於任何請求")
        self.assertEqual(self.notifier.calls, 0)
        after = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        self.assertEqual(before, after, "拒絕後正式資料目錄不得被建立任何檔案")
        self.assertFalse(os.path.exists(os.path.join(prod, "substack.db")))
        self.assertFalse(os.path.exists(os.path.join(prod, IMP.LOCK_NAME)))

    def test_production_data_dir_allowed_with_flag(self):
        """只驗 guard 判斷（帶旗標時不拒絕）；不真的對正式目錄執行。"""
        prod = article_data_guard.PRODUCTION_DATA_DIR
        self.assertEqual(
            article_data_guard.resolve_data_dir(prod, env={"ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "1"}),
            prod)


class LockTest(ImportTestBase):
    def hold_lock(self):
        path = os.path.join(self.dir, IMP.LOCK_NAME)
        handle = open(path, "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(handle.close)
        return handle

    def test_busy_exits_3_without_touching_db_or_network(self):
        F.write_config(self.dir)
        self.hold_lock()
        code = self.go()
        self.assertEqual(code, IMP.EXIT_BUSY)
        self.assertIn("忙碌", self.text)
        self.assertFalse(os.path.exists(self.db_path()), "忙碌時不得建立資料庫（FR-017）")
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0)

    def test_busy_leaves_existing_db_bytes_unchanged(self):
        import substack_store as S
        F.write_config(self.dir)
        store = S.SubstackStore(self.dir)
        store.close()
        before = os.path.getsize(self.db_path())
        self.hold_lock()
        self.assertEqual(self.go(), IMP.EXIT_BUSY)
        self.assertEqual(os.path.getsize(self.db_path()), before)

    def test_lock_is_released_on_every_path(self):
        """任何例外／提早返回之後，鎖都必須可以再被取得。"""
        F.write_config(self.dir)
        self.go()                       # 骨架階段：動作未實作也要釋放鎖
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)      # 取不到會丟 BlockingIOError
        fcntl.flock(handle, fcntl.LOCK_UN)

    def test_lock_released_after_internal_exception(self):
        F.write_config(self.dir)
        boom = io.StringIO()

        def explode(*a, **k):
            raise RuntimeError("注入的例外")
        original = IMP.dispatch
        IMP.dispatch = explode
        try:
            with self.assertRaises(RuntimeError):
                IMP.run(["--data-dir", self.dir], http=self.http, out=boom, err=boom, env={},
                        clock=self.clock)
        finally:
            IMP.dispatch = original
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


class CliShapeTest(ImportTestBase):
    def test_exit_codes_match_contract(self):
        self.assertEqual(IMP.EXIT_OK, 0)
        self.assertEqual(IMP.EXIT_AUTHOR_FAILED, 1)
        self.assertEqual(IMP.EXIT_REFUSED, 2)
        self.assertEqual(IMP.EXIT_BUSY, 3)
        self.assertEqual(IMP.EXIT_DISK, 4)
        self.assertEqual(IMP.EXIT_USAGE_LIMIT, 5)

    def test_parser_declares_every_documented_option(self):
        parser = IMP.build_parser()
        samples = [
            ["--data-dir", "d"],
            ["--data-dir", "d", "--scheduled"],
            ["--data-dir", "d", "--dry-run"],
            ["--data-dir", "d", "--backfill", "zzauthora"],
            ["--data-dir", "d", "--retry-images", "1,2"],
            ["--data-dir", "d", "--reclassify", "--article-ids", "1,2"],
            ["--data-dir", "d", "--reclassify", "--author", "zzauthora"],
            ["--data-dir", "d", "--reclassify", "--article-ids", "1", "--dry-run"],
            ["--data-dir", "d", "--reclassify-history", "1,2"],
            ["--data-dir", "d", "--status"],
        ]
        for argv in samples:
            parser.parse_args(argv)         # 不該丟例外

    def test_mutually_exclusive_actions_refused(self):
        F.write_config(self.dir)
        combos = [
            ["--backfill", "zzauthora", "--reclassify", "--author", "zzauthora"],
            ["--backfill", "zzauthora", "--retry-images", "1"],
            ["--status", "--backfill", "zzauthora"],
            ["--reclassify", "--article-ids", "1", "--author", "zzauthora"],
            ["--reclassify"],                               # 少了 --article-ids／--author
            ["--article-ids", "1"],                         # 沒有 --reclassify
            ["--reclassify-history", "1", "--reclassify", "--article-ids", "1"],
        ]
        for argv in combos:
            self.out, self.err = io.StringIO(), io.StringIO()
            code = self.go(*argv)
            self.assertEqual(code, IMP.EXIT_REFUSED, "%s 應該被拒絕（exit 2）" % argv)
            self.assertEqual(self.http.count(), 0)

    def test_unimplemented_action_reports_code(self):
        """US5 起所有文件化的動作都已實作；dispatch 遇到未知動作仍回 exit 2＋not_implemented。"""
        ctx = IMP.Context(None, "zzbogus", self.dir, None, None, None, None, self.clock,
                          self.clock.sleep, {}, self.out, self.err, 0)
        self.assertEqual(IMP.dispatch(ctx), IMP.EXIT_REFUSED)
        self.assertIn("not_implemented", self.text)

    def test_readonly_action_without_db_refuses_without_creating_it(self):
        code = self.go("--status")
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertFalse(os.path.exists(self.db_path()), "唯讀動作不得建庫")


# ================================================================ T019～T021 共用組裝
KEY_A, KEY_B = F.AUTHOR_A["key"], F.AUTHOR_B["key"]
NAME_A, NAME_B = F.AUTHOR_A["name"], F.AUTHOR_B["name"]
FEED_A, FEED_B = F.AUTHOR_A["feed_url"], F.AUTHOR_B["feed_url"]
ROBOTS_A = "https://%s/robots.txt" % F.DEFAULT_HOST
ROBOTS_B = "https://%s/robots.txt" % F.SECOND_HOST
SITE_URLS = {FEED_A, FEED_B, ROBOTS_A, ROBOTS_B}
SPACE_RE = re.compile(r"^空間：剩餘 [0-9.]+ GB；substack\.db [0-9.]+ MB；圖片 [0-9.]+ MB$")


def synth_items(host, tag, count=20, step_days=5, step_hours=0, base=None, sample=None):
    """合成 count 篇條目（由新到舊）。sample 指定 `article_samples` 的樣本名稱。"""
    base = base or datetime.datetime(2026, 11, 20, 9, 0, tzinfo=F.TZ8)
    out = []
    for i in range(count):
        published = base - datetime.timedelta(days=step_days * i, hours=step_hours * i)
        slug = "%s-%s-%d" % (F.SLUG_MARK, tag, i)
        link = "https://%s/p/%s" % (host, slug)
        kwargs = {"host": host, "slug": slug, "published": published,
                  "title": "%s 標題-%s-%d" % (F.TITLE_MARK, tag, i)}
        if sample is not None:
            kwargs["content_html"] = F.article_samples(link)[sample]
        out.append(F.feed_item(**kwargs))
    return out


class FlowBase(ImportTestBase):
    """主流程測試的共用組裝：合法設定檔、robots 允許、可腳本化的 feed。"""

    AUTHORS = None              # None＝兩位作者；可覆寫成只有一位

    def setUp(self):
        super().setUp()
        overrides = {} if self.AUTHORS is None else {"authors": self.AUTHORS}
        self.cfg = F.write_config(self.dir, **overrides)
        self.http.route(ROBOTS_A, F.ok("", content_type="text/plain"))
        self.http.route(ROBOTS_B, F.ok("", content_type="text/plain"))
        # 夾具樣本的圖片網址（`img_tag()` 的 1～3 號）預設可下載；要讓某張失敗的測試
        # 自己覆寫 self.http.routes[F.image_url(n)]（US3／T031 起圖片階段會真的下載）
        for idx in (1, 2, 3):
            self.http.route(F.image_url(idx), F.image_ok())

    def reset_output(self):
        self.out, self.err = io.StringIO(), io.StringIO()

    def serve_feed(self, url, items, host, *extra):
        self.http.route(url, F.ok(F.make_feed(items, host=host)), *extra)

    def serve_both(self, items_a, items_b):
        self.serve_feed(FEED_A, items_a, F.DEFAULT_HOST)
        self.serve_feed(FEED_B, items_b, F.SECOND_HOST)

    # ---- 讀庫小工具（每次都重新開庫，避免測試持有連線影響位元組比對）
    def _read(self, fn):
        store = S.SubstackStore(self.dir)
        try:
            return fn(store)
        finally:
            store.close()

    def articles(self):
        return self._read(lambda s: s.list_articles())

    def author_row(self, key):
        return self._read(lambda s: s.get_author(key))

    def runs(self):
        return self._read(lambda s: list(reversed(s.recent_runs(50))))

    def polls(self, author_key=None):
        rows = self._read(lambda s: s.poll_logs())
        return [r for r in rows if author_key is None or r["author_key"] == author_key]

    def images_of(self, article_id):
        return self._read(lambda s: s.list_images(article_id))

    def urls(self):
        return [r["url"] for r in self.http.requests]


# ================================================================ T019 主流程
class MainFlowTest(FlowBase):
    def test_first_run_stores_only_items_inside_14_day_window(self):
        """(1) 各 20 篇跨 3 個月 → 只存 published_at ≥ window_from（activated_at 往前 14 天）。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a"), synth_items(F.SECOND_HOST, "b"))
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        rows = self.articles()
        self.assertEqual(len(rows), 6, "每位作者 3 篇（0／5／10 天前）")
        window_from = self.author_row(KEY_A)["window_from"]
        self.assertEqual(window_from, "2026-11-06")
        for row in rows:
            self.assertGreaterEqual(row["published_at"][:10], window_from)
        self.assertEqual(sorted(r["published_at"][:10] for r in rows),
                         ["2026-11-10", "2026-11-10", "2026-11-15", "2026-11-15",
                          "2026-11-20", "2026-11-20"])
        poll = self.polls(KEY_A)[-1]
        self.assertEqual((poll["items_in_feed"], poll["new_items"], poll["skipped_window"]),
                         (20, 3, 17))

    def test_second_run_adds_nothing(self):
        """(2) 立即再執行一次 → 文章總數不變、無重複。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a"), synth_items(F.SECOND_HOST, "b"))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        before = [dict(r) for r in self.articles()]
        calls = self.notifier.calls
        self.clock.advance(31 * 60)          # 越過最小輪詢間隔，確保真的再請求一次
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        after = [dict(r) for r in self.articles()]
        self.assertEqual(len(after), len(before))
        self.assertEqual([r["id"] for r in after], [r["id"] for r in before])
        self.assertEqual(self.polls(KEY_A)[-1]["new_items"], 0)
        self.assertEqual(self.http.count(FEED_A), 2, "第二次真的再請求了一次")
        self.assertEqual(self.notifier.calls, calls, "第二次沒有新文章 → 零通知")

    def test_one_feed_request_per_author_robots_first_and_gap(self):
        """(3) 每作者 feed 請求 ≤1、robots 先於 feed、作者之間 sleep(5)。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=2),
                        synth_items(F.SECOND_HOST, "b", count=2))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.count(FEED_A), 1)
        self.assertEqual(self.http.count(FEED_B), 1)
        urls = self.urls()
        self.assertEqual(urls[0], ROBOTS_A, "robots 必須先於 feed")
        self.assertLess(urls.index(ROBOTS_A), urls.index(FEED_A))
        self.assertLess(urls.index(ROBOTS_B), urls.index(FEED_B))
        self.assertEqual(self.clock.slept.count(5.0), 1, "兩位作者之間恰好一次 sleep(5)")
        self.assertEqual(len([p for p in self.polls(KEY_A) if p["requested"]]), 1)

    def test_conditional_request_and_304(self):
        """(4) 第二次帶 If-None-Match；304 → 不解析、不寫文章、更新 last_request_at、失敗歸零。"""
        etag = 'W/"abc-123"'
        self.http.route(FEED_A,
                        F.ok(F.make_feed(synth_items(F.DEFAULT_HOST, "a", count=2),
                                         host=F.DEFAULT_HOST), etag=etag),
                        F.not_modified(etag))
        self.serve_feed(FEED_B, synth_items(F.SECOND_HOST, "b", count=1), F.SECOND_HOST)
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertNotIn("If-None-Match", self.http.headers_for(FEED_A)[0])
        self.assertEqual(self.author_row(KEY_A)["etag"], etag)
        store = S.SubstackStore(self.dir)                   # 人工造一次失敗，驗證 304 會歸零
        store.record_feed_request(KEY_A, "2026-11-20T22:05:00+08:00", "timeout")
        store.close()
        self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 1)
        before = len(self.articles())
        self.clock.advance(61 * 60)          # 越過最小間隔（基準是上面人工寫入的 22:05）
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.headers_for(FEED_A)[1].get("If-None-Match"), etag)
        self.assertEqual(len(self.articles()), before)
        poll = self.polls(KEY_A)[-1]
        self.assertEqual((poll["outcome"], poll["http_status"], poll["requested"]),
                         ("not_modified", 304, 1))
        self.assertIsNone(poll["items_in_feed"], "304 不解析，沒有條目數")
        row = self.author_row(KEY_A)
        self.assertEqual(row["consecutive_failures"], 0)
        self.assertGreater(row["last_request_at"], "2026-11-20T22:05:00+08:00",
                           "304 仍算一次請求，last_request_at 要更新")
        self.assertTrue(row["last_request_at"].startswith("2026-11-20T23:0"),
                        row["last_request_at"])
        self.assertIn("304", self.text)

    def test_unparseable_pubdate_is_skipped_and_counted(self):
        """(5) pubDate 解析不了 → 不存、skipped_no_pubdate 計數。"""
        items = synth_items(F.DEFAULT_HOST, "a", count=2)
        items[0]["pub_date_raw"] = "完全不是日期"
        self.serve_both(items, [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 1)
        self.assertEqual(self.polls(KEY_A)[-1]["skipped_no_pubdate"], 1)

    def test_duplicate_guid_or_link_is_skipped(self):
        """(5) guid 或 link_norm 重複 → 略過。"""
        items = synth_items(F.DEFAULT_HOST, "a", count=2)
        store = S.SubstackStore(self.dir)
        store.insert_article_with_images(
            F.article_row(author_key=KEY_A, guid=items[0]["guid"],
                          link=items[0]["link"], link_norm=items[0]["link"]), [])
        store.close()
        self.serve_both(items, [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 2, "只多存第二篇")
        self.assertEqual(self.polls(KEY_A)[-1]["new_items"], 1)

    def test_dedupe_conflict_is_skipped_counted_and_not_persisted(self):
        """(5) guid 與 link_norm 各命中不同兩篇 → 略過、計 dedupe_conflict，且不入庫。"""
        store = S.SubstackStore(self.dir)
        row_a = F.article_row(author_key=KEY_A)
        row_b = F.article_row(author_key=KEY_A)
        store.insert_article_with_images(row_a, [])
        store.insert_article_with_images(row_b, [])
        columns = {}
        for table in ("run", "poll_log", "article"):
            columns[table] = [r[1] for r in store.conn.execute("PRAGMA table_info(%s)" % table)]
        store.close()
        item = F.feed_item(guid=row_a["guid"], link=row_b["link"], slug="zz-conflict")
        self.serve_both([item], [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 2, "衝突條目不得寫入")
        self.assertIn("dedupe_conflict=1", self.text)
        for table, cols in columns.items():
            for col in cols:
                self.assertNotIn("dedupe", col.lower(), "%s 不得有 dedupe 計數欄位" % table)
                self.assertNotIn("conflict", col.lower(), "%s 不得有衝突計數欄位" % table)

    def test_article_fields_and_image_rows(self):
        """(6) source／completeness／classify_reason／content_html 原樣／圖片列與文章同交易。

        T031 起圖片階段會接著把 pending 的圖下載完（本測試的圖在 FlowBase 已可下載），
        所以狀態斷言是 `downloaded`；「圖片列與文章在同一個交易」由 T005 的回滾測試證明。
        """
        items = synth_items(F.DEFAULT_HOST, "a", count=1)
        self.serve_both(items, [])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        row = self.articles()[0]
        self.assertEqual(row["source"], "schedule")
        self.assertEqual(row["content_html"], items[0]["content_html"], "content_html 原樣保存")
        self.assertEqual(row["title"], items[0]["title"])
        self.assertEqual(row["description"], items[0]["description"])
        expect = H.classify(items[0]["content_html"], items[0]["link"])
        self.assertEqual((row["completeness"], row["classify_reason"]), expect)
        self.assertEqual(row["author_key"], KEY_A)
        images = self.images_of(row["id"])
        self.assertEqual([i["status"] for i in images], ["downloaded"])
        self.assertEqual([i["seq"] for i in images], [1])
        self.assertEqual(images[0]["caption"], "圖說CAP1")
        self.assertEqual(images[0]["fail_count"], 0)
        self.assertEqual(images[0]["file_path"],
                         os.path.join("substack_images", str(row["id"]), "1.jpg"))

    def test_manual_run_marks_source_manual(self):
        """(6) 不帶 --scheduled → source='manual'、run.trigger='manual'。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=1), [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.articles()[0]["source"], "manual")
        self.assertEqual(self.runs()[-1]["trigger"], "manual")
        self.assertIsNone(self.runs()[-1]["schedule_day"])

    def test_all_new_full_page_sets_all_new_flag(self):
        """(7) 20 篇全為新文 → poll_log.all_new=1。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=20, step_days=0, step_hours=6), [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        poll = self.polls(KEY_A)[-1]
        self.assertEqual((poll["items_in_feed"], poll["new_items"], poll["all_new"]), (20, 20, 1))
        self.assertEqual(self.polls(KEY_B)[-1]["all_new"], 0)

    def test_requests_carry_no_cookie_or_authorization(self):
        """(8) 請求不含 Cookie／Authorization（FR-001）。"""
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=1),
                        synth_items(F.SECOND_HOST, "b", count=1))
        self.go()
        self.assertTrue(self.http.requests)
        for req in self.http.requests:
            keys = [k.lower() for k in req["headers"]]
            self.assertNotIn("cookie", keys)
            self.assertNotIn("authorization", keys)
            self.assertEqual(req["headers"].get("User-Agent"),
                             "Mozilla/5.0 (compatible; personal-feed-reader/1.0)")

    def test_no_subprocess_and_no_model_module(self):
        """(9) FR-019 執行期：零 subprocess；執行不得新載入模型模組。"""
        import subprocess
        calls = []

        def boom(*args, **kwargs):
            calls.append(args)
            raise AssertionError("排程不得開子行程（FR-019）")

        watched = ("claude_cli_runner", "article_transcribe", "transcription_pipeline",
                   "keychain_secrets")
        before = {name: name in sys.modules for name in watched}
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=2),
                        synth_items(F.SECOND_HOST, "b", count=2))
        with mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "check_output", boom):
            self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(calls, [])
        # 全套 discover 把整個測試程序的 sys.modules 混在一起（010 的測試會先載入這些模組），
        # 所以只能比對「本次執行前後的差異」——011 執行不得**新**載入任何模型／鑰匙圈模組。
        after = {name: name in sys.modules for name in watched}
        self.assertEqual(after, before, "本次執行不得載入模型／鑰匙圈模組")
        self.assertFalse(any(name in sys.modules for name in watched
                             if not before[name]))

    def test_first_sight_of_enabled_author_records_activation(self):
        """(10) 首次看到啟用作者 → 寫 activated_at／window_from／last_seen_enabled=1。"""
        self.serve_both([], [])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        for key in (KEY_A, KEY_B):
            row = self.author_row(key)
            self.assertEqual(row["last_seen_enabled"], 1)
            self.assertEqual(row["activated_at"], "2026-11-20T22:00:00+08:00")
            self.assertEqual(row["window_from"], "2026-11-06")
            self.assertEqual(row["display_name"],
                             NAME_A if key == KEY_A else NAME_B)
            self.assertEqual(row["feed_url"], FEED_A if key == KEY_A else FEED_B)
        # 第二次執行不得改寫啟用基準（14 天窗要穩定）
        self.clock.advance(31 * 60)
        self.reset_output()
        self.go("--scheduled")
        self.assertEqual(self.author_row(KEY_A)["activated_at"], "2026-11-20T22:00:00+08:00")

    def test_no_new_articles_says_so_and_sends_nothing(self):
        """(11) 無新文章 → stdout 有「無新文章」、不發通知（US1-AS4）。"""
        old = synth_items(F.DEFAULT_HOST, "a", count=3, step_days=40,
                          base=datetime.datetime(2026, 10, 20, 9, 0, tzinfo=F.TZ8))
        self.serve_both(old, [])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.articles(), [])
        self.assertIn("無新文章", self.text)
        self.assertEqual(self.notifier.calls, 0)
        self.assertEqual(self.runs()[-1]["result"], "ok")


# ================================================================ T020 通知
class NotifyTest(FlowBase):
    AUTHORS = [dict(F.AUTHOR_A)]

    SPECS = (("f", "full_no_tail", datetime.datetime(2026, 11, 18, 9, 0, tzinfo=F.TZ8)),
             ("p", "preview_short", datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8)),
             ("n", "player_only", datetime.datetime(2026, 11, 20, 9, 0, tzinfo=F.TZ8)))

    def build(self, specs=None):
        out = []
        for tag, sample, published in (specs or self.SPECS):
            slug = "%s-%s" % (F.SLUG_MARK, tag)
            link = "https://%s/p/%s" % (F.DEFAULT_HOST, slug)
            out.append(F.feed_item(host=F.DEFAULT_HOST, slug=slug, published=published,
                                   title="%s 標題-%s" % (F.TITLE_MARK, tag),
                                   content_html=F.article_samples(link)[sample]))
        return out

    def serve(self, items=None):
        items = self.build() if items is None else items
        self.serve_feed(FEED_A, items, F.DEFAULT_HOST)
        return items

    def notices(self):
        return [t for t in self.notifier.texts if t.startswith("📰")]

    def summaries(self):
        return [t for t in self.notifier.texts if t.startswith("📚")]

    def test_one_notice_per_article_with_exact_format_oldest_first(self):
        """(1) 每篇一則、格式逐字相同、依發布時間由舊到新。"""
        items = self.serve()
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        titles = {it["title"][-1]: it["title"] for it in items}
        self.assertEqual(self.notices(), [
            "📰 Substack 新文章｜%s\n%s\n完整度：全文" % (NAME_A, titles["f"]),
            "📰 Substack 新文章｜%s\n%s\n完整度：僅預覽" % (NAME_A, titles["p"]),
            "📰 Substack 新文章｜%s\n%s\n完整度：非文字\n%s" % (NAME_A, titles["n"],
                                                               IMP.NON_TEXT_REMINDER),
        ])
        rows = {r["completeness"]: r for r in self.articles()}
        self.assertEqual(sorted(rows), ["F", "N", "P"])
        self.assertTrue(all(r["notify_status"] == "sent" for r in self.articles()))

    def test_uncertain_is_labelled_preview(self):
        """(1) uncertain:* 一律標「僅預覽」。"""
        self.serve(self.build([("u", "empty_content",
                                datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8))]))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertIn("完整度：僅預覽", self.notices()[0])
        self.assertTrue(self.articles()[0]["classify_reason"].startswith("uncertain:"))

    def test_notices_contain_no_url(self):
        """(2) 通知不含 http(s) 與該文章實際的 link／link_norm。"""
        self.serve()
        self.go()
        rows = self.articles()
        for text in self.notifier.texts:
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)
            for row in rows:
                self.assertNotIn(row["link"], text)
                self.assertNotIn(row["link_norm"], text)
                self.assertNotIn(F.SLUG_MARK, text)

    def test_throttle_between_messages(self):
        """(3) 相鄰兩則之間 sleep(1.5)。"""
        self.serve()
        self.go()
        self.assertEqual(len(self.notifier.texts), 4, "3 篇＋1 則摘要")
        self.assertEqual(self.clock.slept.count(1.5), 3)

    def test_failure_marks_failed_and_is_retried_next_run_before_new(self):
        """(4) 失敗記 failed、同次不重試；下次先補發再發新文章；3 次後 abandoned。"""
        first = self.build([("x", "full_no_tail",
                             datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8))])
        self.notifier.fail_all = True
        self.serve(first)
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        row = self.articles()[0]
        self.assertEqual((row["notify_status"], row["notify_attempts"]), ("failed", 1))
        self.assertEqual(self.notifier.calls, 2, "1 篇＋1 則摘要，同次不重試")

        # 第二次：先補發舊的（發布日較晚），再發新的（發布日較早）→ 順序證明「補發優先」
        second = self.build([("y", "full_no_tail",
                              datetime.datetime(2026, 11, 18, 9, 0, tzinfo=F.TZ8))])
        self.http.routes[FEED_A] = [F.ok(F.make_feed(first + second, host=F.DEFAULT_HOST))]
        self.notifier.fail_all = False
        self.notifier.texts = []
        self.clock.advance(31 * 60)
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual([t.split("\n")[1] for t in self.notices()],
                         [first[0]["title"], second[0]["title"]])
        rows = {r["title"]: r for r in self.articles()}
        self.assertEqual(rows[first[0]["title"]]["notify_status"], "sent")
        self.assertEqual(rows[first[0]["title"]]["notify_attempts"], 2)

    def test_three_failures_abandon(self):
        """(4) 累計 3 次 → abandoned；文章存檔不受影響。"""
        self.notifier.fail_all = True
        self.serve(self.build([("x", "full_no_tail",
                                datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8))]))
        for i in range(3):
            self.reset_output()
            self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
            self.clock.advance(31 * 60)
        row = self.articles()[0]
        self.assertEqual((row["notify_status"], row["notify_attempts"]), ("abandoned", 3))
        self.assertTrue(row["content_html"], "文章存檔不受通知失敗影響")
        self.reset_output()
        self.notifier.texts = []
        self.go()
        self.assertEqual(self.notices(), [], "abandoned 之後不再補發")

    def test_summary_format(self):
        """(5) 摘要格式、空間行、圖片行（本階段固定 0）、漏文提示、尚未通知成功行。"""
        self.serve()
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        lines = self.summaries()[0].split("\n")
        self.assertEqual(lines[0],
                         "📚 Substack 匯入（排程）：新增 3 篇（全文 1／僅預覽 1／非文字 1）")
        # 三篇裡只有 full_no_tail 那篇有一張圖，且 FlowBase 已讓它可下載（T031 起驗實值）
        self.assertEqual(lines[1], "圖片：本次下載 1 張、缺圖待補 0 張、放棄累計 0 張")
        self.assertRegex(lines[2], SPACE_RE)
        self.assertEqual(len(lines), 3, "沒有漏文提示、沒有未通知成功時只有三行")

    def test_summary_optional_lines(self):
        """(5) 漏文提示行與尚未通知成功行在條件成立時出現。"""
        self.notifier.fail_all = True
        self.serve(synth_items(F.DEFAULT_HOST, "a", count=20, step_days=0, step_hours=6))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        summary = self.summaries()[0]
        self.assertIn("提示：%s 本次 feed 的 20 篇皆為新文，兩次輪詢之間可能有漏文（只提示，不補救）"
                      % NAME_A, summary)
        self.assertIn("通知：20 篇尚未通知成功，下次執行補發", summary)

    def test_article_notice_has_no_space_line(self):
        """(5) 逐篇通知不附空間現況（FR-028）。"""
        self.serve()
        self.go()
        for text in self.notices():
            self.assertNotIn("空間：", text)

    def test_notify_error_text_is_not_logged(self):
        """(6) 通知失敗只印「失敗 N 則」，不含 token 或錯誤原文。"""
        self.notifier.fail_all = True
        self.serve()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertIn("failed=4", self.text)
        self.assertNotIn(F.FakeNotifier.FAKE_BOT_TOKEN, self.text)
        self.assertNotIn("api.telegram.org", self.text)
        self.assertNotIn("401", self.text)

    def test_non_text_reminder_only_once_and_only_per_article(self):
        """(7) N 類提醒：逐篇恰一次、F／P 不含、摘要不含、重跑與重判不重複。"""
        self.serve()
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        notices = self.notices()
        for text in notices:
            if "完整度：非文字" in text:
                self.assertEqual(text.split("\n")[-1], IMP.NON_TEXT_REMINDER)
                self.assertNotIn(F.BODY_MARK, text)
                self.assertNotIn("https://", text)
            else:
                self.assertNotIn(IMP.NON_TEXT_REMINDER, text)
        self.assertNotIn(IMP.NON_TEXT_REMINDER, self.summaries()[0])
        self.assertIn("非文字 1", self.summaries()[0])

        n_row = [r for r in self.articles() if r["completeness"] == "N"][0]
        self.assertIsNone(n_row["body_text"])
        self.clock.advance(31 * 60)
        self.reset_output()
        self.go("--scheduled")                                       # 再跑一次
        self.reset_output()
        self.go("--reclassify", "--article-ids", str(n_row["id"]))    # 重判不發通知
        joined = "\n".join(self.notifier.texts)
        self.assertEqual(joined.count(IMP.NON_TEXT_REMINDER), 1, "提醒累計只有一次")
        allowed = SITE_URLS | {F.image_url(i) for i in (1, 2, 3)}
        self.assertTrue(set(self.urls()) <= allowed,
                        "N 類匯入全程只打 robots／feed／白名單圖片：%s"
                        % sorted(set(self.urls()) - allowed))

    def test_non_text_reminder_resent_once_after_failure(self):
        """(7) 通知失敗補發重送同一則（含提醒），成功後累計 1 次。"""
        self.notifier.fail_all = True
        self.serve(self.build([("n", "player_only",
                                datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8))]))
        self.go()
        self.assertEqual("\n".join(self.notifier.texts).count(IMP.NON_TEXT_REMINDER), 1)
        self.notifier.fail_all = False
        self.notifier.texts = []
        self.clock.advance(31 * 60)
        self.reset_output()
        self.go()
        self.assertEqual("\n".join(self.notifier.texts).count(IMP.NON_TEXT_REMINDER), 1)
        self.assertEqual(self.articles()[0]["notify_status"], "sent")

    def test_non_text_never_triggers_model_or_extra_request(self):
        """(7) 系統不自行處理 N 類：零模型、零子行程、零額外請求。"""
        import subprocess
        runner = F.FakeClaudeRunner()
        calls = []
        self.serve(self.build([("n", "player_only",
                                datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8))]))
        with mock.patch.object(subprocess, "Popen", lambda *a, **k: calls.append(a)), \
                mock.patch.object(subprocess, "run", lambda *a, **k: calls.append(a)):
            self.go()
        self.assertEqual(runner.calls, [])
        self.assertEqual(calls, [])
        self.assertTrue(set(self.urls()) <= SITE_URLS)


# ================================================================ T021 排程日與牆鐘預算
class ScheduleDayTest(FlowBase):
    AUTHORS = [dict(F.AUTHOR_A)]

    def at(self, when):
        self.clock.set_now(when)
        self.reset_output()

    def feed(self, count=1):
        self.serve_feed(FEED_A, synth_items(F.DEFAULT_HOST, "a", count=count), F.DEFAULT_HOST)

    def seed_actual_run(self, day, trigger="schedule"):
        store = S.SubstackStore(self.dir)
        run_id = store.start_run(trigger, schedule_day=day)
        store.finish_run(run_id, result="ok")
        store.close()

    def last_run(self):
        return self.runs()[-1]

    def test_schedule_day_is_start_minus_22_hours(self):
        """(9) schedule_day＝啟動時刻減 22 小時的日期。"""
        cases = {"2026-11-20 22:00:00": "2026-11-20", "2026-11-21 01:00:00": "2026-11-20",
                 "2026-11-21 21:59:00": "2026-11-20", "2026-11-21 22:00:00": "2026-11-21",
                 "2026-11-20 23:00:00": "2026-11-20", "2026-11-21 00:59:00": "2026-11-20",
                 "2026-11-21 07:00:00": "2026-11-20"}
        for when, day in cases.items():
            now = self.clock.set_now(when)
            self.assertEqual(IMP.schedule_day(now), day, when)

    def test_2159_runs_as_catchup_when_previous_day_not_done(self):
        """(1) 21:59 屬前一排程日：未執行過 → catchup 執行。"""
        self.feed()
        self.at("2026-11-21 21:59:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        run = self.last_run()
        self.assertEqual((run["trigger"], run["schedule_day"], run["result"]),
                         ("catchup", "2026-11-20", "ok"))
        self.assertEqual(self.http.count(FEED_A), 1)

    def test_2159_already_done(self):
        """(1) 21:59 且該排程日已執行 → already_done、零網路。"""
        self.seed_actual_run("2026-11-20")
        self.feed()
        self.at("2026-11-21 21:59:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.last_run()["result"], "already_done")
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0)

    def test_2200_starts_new_schedule_day(self):
        """(2) 22:00 → trigger='schedule' 並執行。"""
        self.seed_actual_run("2026-11-19")
        self.feed()
        self.at("2026-11-20 22:00:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        run = self.last_run()
        self.assertEqual((run["trigger"], run["schedule_day"], run["result"]),
                         ("schedule", "2026-11-20", "ok"))

    def test_defer_window_hours(self):
        """(3) 23:00／23:59／00:59 → deferred、零網路、只寫一列 run。"""
        for when in ("2026-11-20 23:00:00", "2026-11-20 23:59:00", "2026-11-21 00:59:00"):
            self.setUp()
            self.feed()
            self.at(when)
            before = len(self.runs()) if os.path.exists(self.db_path()) else 0
            self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
            runs = self.runs()
            self.assertEqual(len(runs) - before, 1, when)
            self.assertEqual(runs[-1]["result"], "deferred", when)
            self.assertEqual(runs[-1]["schedule_day"], "2026-11-20", when)
            self.assertEqual(self.http.count(), 0, when)
            self.assertEqual(self.notifier.calls, 0, when)
            self.assertEqual(self.articles(), [], when)

    def test_0100_catchup_or_already_done(self):
        """(4) 01:00：當日未執行 → catchup；已執行 → already_done。"""
        self.feed()
        self.at("2026-11-21 01:00:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.last_run()["trigger"], "catchup")
        self.assertEqual(self.last_run()["result"], "ok")
        requests = self.http.count()
        self.at("2026-11-21 01:00:30")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.last_run()["result"], "already_done")
        self.assertEqual(self.http.count(), requests, "already_done 零網路")

    def test_sequence_run_then_deferred_then_already_done(self):
        """(5) 22:00 執行 → 23:30 deferred → 01:00 already_done。"""
        self.feed()
        self.at("2026-11-20 22:00:00")
        self.go("--scheduled")
        self.assertEqual(self.last_run()["result"], "ok")
        self.at("2026-11-20 23:30:00")
        self.go("--scheduled")
        self.assertEqual(self.last_run()["result"], "deferred")
        self.at("2026-11-21 01:00:00")
        self.go("--scheduled")
        self.assertEqual(self.last_run()["result"], "already_done")
        self.assertEqual(self.http.count(FEED_A), 1, "整個排程日只實際抓一次")

    def test_sequence_missed_then_deferred_then_runs_at_0100(self):
        """(6) 22:00 錯過 → 23:30 deferred → 01:00 執行（deferred 不得讓補跑誤判）。"""
        self.feed()
        self.at("2026-11-20 23:30:00")
        self.go("--scheduled")
        self.assertEqual(self.last_run()["result"], "deferred")
        self.at("2026-11-21 01:00:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        run = self.last_run()
        self.assertEqual((run["trigger"], run["result"]), ("catchup", "ok"))
        self.assertEqual(self.http.count(FEED_A), 1)
        self.assertEqual(len(self.articles()), 1)

    def test_0700_wakeup_runs_immediately(self):
        """(7) 07:00 醒來且當日未執行 → 立即執行（不受 05:00～18:00 時窗限制）。"""
        self.feed()
        self.at("2026-11-21 07:00:00")
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        run = self.last_run()
        self.assertEqual((run["trigger"], run["schedule_day"], run["result"]),
                         ("catchup", "2026-11-20", "ok"))
        self.assertEqual(len(self.articles()), 1)

    def test_manual_run_ignores_schedule_day(self):
        """(8) 不帶 --scheduled 不做排程日判斷（即使同日已執行過、即使在延後時窗）。"""
        self.seed_actual_run("2026-11-20")
        self.feed()
        self.at("2026-11-20 23:30:00")
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        run = self.last_run()
        self.assertEqual((run["trigger"], run["result"]), ("manual", "ok"))
        self.assertEqual(self.http.count(FEED_A), 1)
        self.assertEqual(len(self.articles()), 1)

    def test_no_time_window_code(self):
        """(7) FR-018：程式不得有 05:00～18:00 時窗邏輯。"""
        with open(IMP.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            source = f.read()
        for needle in ("05:00", "18:00"):
            self.assertNotIn(needle, source)


class BudgetTest(FlowBase):
    def test_wall_clock_budget_aborts_and_releases_lock(self):
        """(10) 20 分鐘牆鐘預算到 → aborted_budget、exit 1、鎖已釋放、通知仍 pending。"""
        self.serve_feed(FEED_A, synth_items(F.DEFAULT_HOST, "a", count=1), F.DEFAULT_HOST)
        self.http.route(FEED_B, F.hang(seconds=IMP.RUN_BUDGET_SEC + 50))
        code = self.go()
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED, self.text)
        run = self.runs()[-1]
        self.assertEqual(run["result"], "aborted_budget")
        self.assertEqual(run["budget_exhausted"], 1)
        rows = self.articles()
        self.assertEqual(len(rows), 1, "已提交的文章各自完整")
        self.assertEqual(rows[0]["notify_status"], "pending")
        self.assertEqual(len(self.images_of(rows[0]["id"])), 1, "無半寫入")
        self.assertEqual(self.notifier.calls, 0, "預算中止不發通知（下次補發）")
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)      # 取不到會丟 BlockingIOError
        fcntl.flock(handle, fcntl.LOCK_UN)

    def test_timeout_is_clamped_to_remaining_budget(self):
        """(10) 每次網路逾時取 min(原逾時, 剩餘時間)。"""
        self.http.route(FEED_A, F.hang(seconds=1180))
        self.serve_feed(FEED_B, synth_items(F.SECOND_HOST, "b", count=1), F.SECOND_HOST)
        self.go()
        by_url = {}
        for req in self.http.requests:
            by_url.setdefault(req["url"], []).append(req["timeout"])
        self.assertEqual(by_url[ROBOTS_A][0], 30, "預算充足時用預設 30 秒")
        self.assertEqual(by_url[FEED_A][0], 30)
        self.assertEqual(by_url[ROBOTS_B][0], 15, "1180 秒耗掉＋作者間隔 5 秒 → 只剩 15 秒")
        self.assertEqual(by_url[FEED_B][0], 15)


# ================================================================ T031 US3 圖片階段
class SlowHttp(object):
    """包住 FakeHttp：feed 回應之後把注入的時鐘往前推，用來逼出「圖片階段期限已過」。

    不自己記錄請求（仍由內層 FakeHttp 記錄），所以 FlowBase 的 urls()／count() 照常可用。
    """

    def __init__(self, inner, clock, extra_seconds, match="/feed"):
        self.inner = inner
        self.clock = clock
        self.extra_seconds = float(extra_seconds)
        self.match = match

    def __call__(self, url, headers=None, timeout=None):
        resp = self.inner(url, headers=headers, timeout=timeout)
        if self.match in url:
            self.clock.advance(self.extra_seconds)
        return resp


IMAGE_DELETE_RE = re.compile(r"os\.remove\(|os\.unlink\(|\.unlink\(|shutil\.rmtree|os\.rmdir")


class ImageFlowTest(FlowBase):
    """US3-AS1～AS3、FR-015／FR-016：圖片下載接進主流程後的整合行為。"""

    AUTHORS = [dict(F.AUTHOR_A)]

    def multi(self, tag="m", published=None, sample="multi_image"):
        published = published or datetime.datetime(2026, 11, 20, 9, 0, tzinfo=F.TZ8)
        slug = "%s-%s" % (F.SLUG_MARK, tag)
        link = "https://%s/p/%s" % (F.DEFAULT_HOST, slug)
        return F.feed_item(host=F.DEFAULT_HOST, slug=slug, published=published,
                           title="%s 標題-%s" % (F.TITLE_MARK, tag),
                           content_html=F.article_samples(link)[sample])

    def serve_items(self, items):
        self.http.routes[FEED_A] = [F.ok(F.make_feed(items, host=F.DEFAULT_HOST))]

    def fail_image(self, idx, *actions):
        self.http.routes[F.image_url(idx)] = list(actions)

    def next_scheduled_run(self):
        """下一個排程日再跑一次（同一排程日重跑會是 already_done、零網路）。"""
        self.clock.advance(24 * 3600)
        self.reset_output()
        return self.go("--scheduled")

    def all_images(self):
        rows = []
        for article in self.articles():
            rows.extend(self.images_of(article["id"]))
        return rows

    def image_files(self):
        base = os.path.join(self.dir, "substack_images")
        out = []
        for root, _dirs, names in os.walk(base):
            out.extend(os.path.join(root, n) for n in names)
        return sorted(out)

    def image_bytes_total(self):
        return sum(os.path.getsize(p) for p in self.image_files())

    def summaries(self):
        return [t for t in self.notifier.texts if t.startswith("📚")]

    # ---- (a) 一張失敗不影響文章與其他圖，且執行不算失敗
    def test_one_failed_image_keeps_article_and_run_ok(self):
        self.fail_image(2, F.status(500))
        self.serve_items([self.multi()])
        code = self.go("--scheduled")
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 1, "圖片失敗不影響文章存檔（FR-015）")
        rows = self.all_images()
        self.assertEqual([r["status"] for r in rows],
                         ["downloaded", "missing", "downloaded"])
        self.assertEqual(rows[1]["fail_count"], 1)
        self.assertEqual(rows[1]["last_error_code"], "http_500")
        self.assertIn("images: downloaded=2 missing=1 abandoned_now=0", self.text)
        run = self.runs()[-1]
        self.assertEqual(run["result"], "ok", "圖片失敗不改變 run.result（spec US3-AS2）")
        self.assertEqual((run["images_downloaded"], run["images_missing"],
                          run["images_abandoned_now"]), (2, 1, 0))
        summary = self.summaries()[0]
        self.assertIn("圖片：本次下載 2 張、缺圖待補 1 張、放棄累計 0 張", summary)
        self.assertNotIn(F.IMG_URL_MARK, self.text, "stdout 不得出現圖片網址（FR-026）")

    # ---- (b) 下一次執行補下載缺圖
    def test_next_run_backfills_missing_image(self):
        self.fail_image(2, F.status(500), F.image_ok())
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual([r["status"] for r in self.all_images()],
                         ["downloaded", "missing", "downloaded"])
        self.assertEqual(self.next_scheduled_run(), IMP.EXIT_OK, self.text)
        rows = self.all_images()
        self.assertEqual([r["status"] for r in rows],
                         ["downloaded", "downloaded", "downloaded"])
        self.assertEqual(rows[1]["fail_count"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, rows[1]["file_path"])))
        run = self.runs()[-1]
        self.assertEqual((run["images_downloaded"], run["images_missing"]), (1, 0))

    # ---- (c)(d) 連續失敗 3 次 → abandoned、之後零請求、摘要回報放棄張數
    def test_three_failures_abandon_then_no_more_requests(self):
        self.fail_image(2, F.status(500))
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.next_scheduled_run(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.all_images()[1]["fail_count"], 2)
        self.assertEqual(self.all_images()[1]["status"], "missing")

        # 第三次：同時帶一篇新文章，確認摘要會報「放棄累計」
        self.serve_items([self.multi(), self.multi(
            tag="p2", published=datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8),
            sample="preview_short")])
        self.notifier.texts = []
        self.assertEqual(self.next_scheduled_run(), IMP.EXIT_OK, self.text)
        row = self.all_images()[1]
        self.assertEqual((row["status"], row["fail_count"]), ("abandoned", 3))
        run = self.runs()[-1]
        self.assertEqual((run["images_downloaded"], run["images_missing"],
                          run["images_abandoned_now"]), (0, 0, 1))
        self.assertIn("圖片：本次下載 0 張、缺圖待補 0 張、放棄累計 1 張", self.summaries()[0])
        self.assertIn("abandoned_now=1", self.text)

        # 第四次：放棄的圖不再自動重試（零請求）
        before = self.http.count(F.image_url(2))
        self.assertEqual(self.next_scheduled_run(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.count(F.image_url(2)), before,
                         "abandoned 之後排程零請求（SC-008）")
        self.assertEqual(self.all_images()[1]["fail_count"], 3)

    # ---- (e) PO 可用 --retry-images 要求重新嘗試
    def test_retry_images_downloads_and_only_touches_image_hosts(self):
        self.fail_image(2, F.status(500))
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        target = self.all_images()[1]
        self.fail_image(2, F.image_ok())
        self.reset_output()
        feed_before = self.http.count(FEED_A)
        self.notifier.texts = []
        code = self.go("--retry-images", str(target["id"]))
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        self.assertEqual(self.all_images()[1]["status"], "downloaded")
        self.assertEqual(self.http.count(FEED_A), feed_before,
                         "--retry-images 不打 feed（contracts/cli.md）")
        self.assertEqual(self.http.count(ROBOTS_A), 1)
        self.assertEqual(self.runs()[-1]["trigger"], "retry_images")
        self.assertEqual(self.runs()[-1]["images_downloaded"], 1)
        self.assertEqual(self.notifier.texts, [], "--retry-images 不發通知")

    def test_retry_images_refuses_downloaded_and_unknown_ids(self):
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        done = self.all_images()[0]
        self.reset_output()
        code = self.go("--retry-images", "%d,9999" % done["id"])
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED, self.text)
        self.assertIn("status_downloaded", self.text)
        self.assertIn("not_found", self.text)
        self.assertEqual(self.all_images()[0]["status"], "downloaded")

    def test_retry_images_rejects_non_integer_ids(self):
        self.serve_items([self.multi()])
        self.go("--scheduled")
        self.reset_output()
        self.assertEqual(self.go("--retry-images", "abc"), IMP.EXIT_REFUSED, self.text)

    def test_retry_images_takes_the_lock(self):
        self.serve_items([self.multi()])
        self.go("--scheduled")
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.reset_output()
        self.assertEqual(self.go("--retry-images", "1"), IMP.EXIT_BUSY, self.text)
        self.assertIn("忙碌", self.text)

    # ---- 圖片階段期限＝預算減 120 秒
    def test_image_stage_deadline_is_budget_minus_120(self):
        self.assertEqual(IMP.IMAGE_DEADLINE_MARGIN_SEC, 120)
        self.serve_items([self.multi()])
        slow = SlowHttp(self.http, self.clock, IMP.RUN_BUDGET_SEC - 100)
        code = self.go("--scheduled", http=slow)
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.count(F.image_url(1)), 0,
                         "剩餘 <120 秒 → 圖片階段直接中止（research R2）")
        rows = self.all_images()
        self.assertEqual([r["status"] for r in rows], ["pending", "pending", "pending"])
        self.assertEqual([r["fail_count"] for r in rows], [0, 0, 0], "期限中止不計失敗")
        self.assertTrue([t for t in self.notifier.texts if t.startswith("📰")],
                        "期限中止後仍要發逐篇通知")
        self.assertIn("圖片：本次下載 0 張、缺圖待補 3 張、放棄累計 0 張", self.summaries()[0])
        run = self.runs()[-1]
        self.assertEqual(run["result"], "ok")
        self.assertEqual((run["images_downloaded"], run["images_missing"]), (0, 3))
        self.assertEqual(run["budget_exhausted"], 1, "圖片階段期限到也算預算用完")

    def test_image_stage_runs_when_budget_is_enough(self):
        self.serve_items([self.multi()])
        slow = SlowHttp(self.http, self.clock, 60)
        self.assertEqual(self.go("--scheduled", http=slow), IMP.EXIT_OK, self.text)
        self.assertEqual([r["status"] for r in self.all_images()],
                         ["downloaded"] * 3)
        self.assertEqual(self.runs()[-1]["budget_exhausted"], 0)

    # ---- 計數與摘要一致
    def test_counters_match_summary_line(self):
        self.fail_image(2, F.status(500))
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        run = self.runs()[-1]
        line = [l for l in self.summaries()[0].split("\n") if l.startswith("圖片：")][0]
        store = S.SubstackStore(self.dir)
        try:
            counts = store.image_status_counts()
        finally:
            store.close()
        self.assertEqual(line, "圖片：本次下載 %d 張、缺圖待補 %d 張、放棄累計 %d 張"
                         % (run["images_downloaded"], run["images_missing"],
                            counts["abandoned"]))
        self.assertEqual(run["images_missing"], counts["pending"] + counts["missing"])

    # ---- FR-016：只增不減、不刪圖、沒有保留期限／占用上限
    def test_image_files_only_grow_across_runs(self):
        self.serve_items([self.multi()])
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        first_files, first_bytes = self.image_files(), self.image_bytes_total()
        self.assertTrue(first_files)
        self.serve_items([self.multi(),
                          self.multi(tag="second",
                                     published=datetime.datetime(2026, 11, 19, 9, 0,
                                                                 tzinfo=F.TZ8))])
        self.assertEqual(self.next_scheduled_run(), IMP.EXIT_OK, self.text)
        self.assertTrue(set(first_files) <= set(self.image_files()),
                        "既有圖檔不得被刪除或改名（FR-016）")
        self.assertGreaterEqual(self.image_bytes_total(), first_bytes)

    def test_no_image_deletion_or_retention_code(self):
        """FR-016 靜態：處理圖片的模組不得有刪除／清理已下載圖檔的程式路徑。

        掃描範圍＝`substack_images.py` 與 `substack_import.py`（操作 substack_images/ 的部分）。
        **白名單例外**：`substack_config.py` 的設定檔備份只保留最新 10 份，刪的是
        `substack_config.json.bak-*`，與圖片無關，依 T031 明定不列入掃描。
        """
        for name in ("substack_images.py", "substack_import.py"):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                name)
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            for idx, line in enumerate(lines):
                if not IMAGE_DELETE_RE.search(line):
                    continue
                window = "\n".join(lines[max(0, idx - 5):idx + 1]).lower()
                self.assertIn("part", window,
                              "%s:%d 只允許刪除 .part 暫存檔" % (name, idx + 1))
            text = "\n".join(lines)
            for word in ("retention", "max_total", "older_than", "prune_images"):
                self.assertNotIn(word, text, "%s 不得有保留期限／占用上限處理" % name)


# ================================================================ T035（US4）失敗隔離與告警
# 告警文字逐字照 contracts/notifications.md §3（測試端獨立寫一份，不引用實作常數）
BLOCKED_TPL = "⚠️ Substack 匯入：%s 被站方擋下（%s），本次已停止該作者、不重試，下次排程再試。"
FAILED_TPL = "⚠️ Substack 匯入：%s 抓取失敗（%s，連續 %d 次），下次排程再試。"
CONFIG_TPL = ("⚠️ Substack 匯入：設定檔無法使用（%s），本次未發出任何請求。"
              "請在對話中請 Claude 檢查設定。")
DISK_RE = re.compile(r"^⚠️ Substack 匯入：寫入失敗（可能是硬碟空間不足），本次已中止，"
                     r"已存文章不受影響。剩餘空間 [0-9.]+ GB。$")
BROKEN_XML = "<rss><channel><item><title>壞掉"

# 其他失敗的觸發方式與原因詞（契約只列五個固定詞；未列者的對應見 substack_import 的 FAILURE_REASON）
OTHER_FAILURES = (
    # (outcome, 觸發的 URL 種類, 假回應, 原因詞)
    ("timeout", "feed", F.timeout(), "逾時"),
    ("network", "feed", F.network(), "網路錯誤"),
    ("parse_error", "feed", F.ok(BROKEN_XML), "無法解析"),
    ("http_500", "feed", F.status(500), "HTTP 500"),
    ("robots_disallow", "robots", F.ok("User-agent: *\nDisallow: /", content_type="text/plain"),
     "robots 不允許"),
    ("robots_unavailable", "robots", F.status(503), "robots 不允許"),
    ("too_large", "feed", F.too_large(), "無法解析"),
    ("redirect_refused", "feed", F.redirect("https://zzelsewhere.example.net/feed"), "網路錯誤"),
)


def alerts_of(notifier):
    return [t for t in notifier.texts if t.startswith("⚠️")]


class AlertTestBase(FlowBase):
    def set_policy(self, policy):
        cfg = dict(self.cfg)
        cfg["alert_policy"] = policy
        self.cfg = F.write_config(self.dir, **cfg)

    def alerts(self):
        return alerts_of(self.notifier)

    def assertAlert(self, text, first_line):
        lines = text.split("\n")
        self.assertEqual(len(lines), 2, text)
        self.assertEqual(lines[0], first_line)
        self.assertRegex(lines[1], SPACE_RE, "告警末尾必須是空間現況行")
        self.assertNotIn(F.TITLE_MARK, text)
        self.assertNotIn(F.SLUG_MARK, text)
        self.assertNotIn("http", text)

    def next_run(self, *args):
        """越過 30 分鐘最小間隔後再跑一次手動執行。"""
        self.clock.advance(3600)
        self.reset_output()
        return self.go(*args)

    def feed_requests(self, url):
        return self.http.count(url)


class BlockedAlertTest(AlertTestBase):
    """(1)(2)(5)(6)：403／429／挑戰頁不論策略一律立即告警；B 照常；同次不重試。"""

    CASES = (("blocked_403", F.status(403), "403"),
             ("rate_limited_429", F.status(429), "429"),
             ("challenge_html", F.challenge(), "非 feed 回應"))

    def test_blocked_alerts_immediately_under_both_policies(self):
        for policy in ("every_failure", "consecutive_3"):
            for outcome, action, word in self.CASES:
                with self.subTest(policy=policy, outcome=outcome):
                    self.setUp()
                    self.set_policy(policy)
                    self.http.route(FEED_A, action)
                    self.serve_feed(FEED_B, synth_items(F.SECOND_HOST, "b", count=2),
                                    F.SECOND_HOST)
                    code = self.go("--scheduled")
                    self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED, self.text)
                    self.assertEqual(self.feed_requests(FEED_A), 1, "同次不重試")
                    self.assertEqual(self.feed_requests(FEED_B), 1)
                    rows = self.articles()
                    self.assertFalse([r for r in rows if r["author_key"] == KEY_A],
                                     "被擋的作者不得寫入")
                    self.assertEqual(len([r for r in rows if r["author_key"] == KEY_B]), 2,
                                     "B 照常存入")
                    alerts = self.alerts()
                    self.assertEqual(len(alerts), 1, alerts)
                    self.assertAlert(alerts[0], BLOCKED_TPL % (NAME_A, word))
                    self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 1)
                    self.assertEqual(self.polls(KEY_A)[-1]["outcome"], outcome)
                    self.assertEqual(self.runs()[-1]["result"], "partial")

    def test_blocked_alerts_again_on_every_occurrence_under_consecutive_3(self):
        self.set_policy("consecutive_3")
        self.http.route(FEED_A, F.status(403))
        self.serve_feed(FEED_B, [], F.SECOND_HOST)
        for i in range(3):
            code = self.go() if i == 0 else self.next_run()
            self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED)
        self.assertEqual(len(self.alerts()), 3, "403 每次都立即告警，不受連續 3 次策略影響")

    def test_alert_only_run_still_sends_summary_with_space_line(self):
        """(6) 只有告警、沒有新文章 → 仍發 1 則摘要（含空間行）。"""
        self.http.route(FEED_A, F.status(429))
        self.http.route(FEED_B, F.not_modified())
        code = self.go()
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED)
        self.assertEqual(self.runs()[-1]["result"], "partial")
        summaries = [t for t in self.notifier.texts if t.startswith("📚")]
        self.assertEqual(len(summaries), 1, self.notifier.texts)
        self.assertIn("新增 0 篇", summaries[0])
        self.assertTrue(any(SPACE_RE.match(line) for line in summaries[0].split("\n")))
        self.assertLess(self.notifier.texts.index(self.alerts()[0]),
                        self.notifier.texts.index(summaries[0]), "告警先於摘要")


class OtherFailureAlertTest(AlertTestBase):
    """(3)(4)：其他失敗依策略；不寫入、不覆蓋既有資料與 etag、連續次數 +1、成功即歸零。"""

    AUTHORS = [dict(F.AUTHOR_A)]
    ETAG = 'W/"zz-etag-1"'

    def prime(self):
        """第一次成功：存 2 篇、記 etag、robots 快取；之後跳過 8 天讓 robots 快取全部過期。"""
        self.http.routes[FEED_A] = [F.ok(F.make_feed(synth_items(F.DEFAULT_HOST, "a", count=2),
                                                     host=F.DEFAULT_HOST), etag=self.ETAG)]
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 2)
        self.notifier.texts[:] = []
        self.clock.advance(8 * 24 * 3600)

    def fail_with(self, kind, action):
        if kind == "feed":
            self.http.routes[FEED_A] = [action]
        else:
            self.http.routes[ROBOTS_A] = [action]

    def test_each_other_failure_every_failure_policy(self):
        for outcome, kind, action, word in OTHER_FAILURES:
            with self.subTest(outcome=outcome):
                self.setUp()
                self.prime()
                before = [dict(r) for r in self.articles()]
                feed_before = self.feed_requests(FEED_A)
                self.fail_with(kind, action)
                code = self.next_run()
                self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED, self.text)
                self.assertLessEqual(self.feed_requests(FEED_A) - feed_before, 1, "同次不重試")
                self.assertEqual([dict(r) for r in self.articles()], before,
                                 "既有資料不得被改動")
                row = self.author_row(KEY_A)
                self.assertEqual(row["etag"], self.ETAG, "etag 不得被覆蓋")
                self.assertEqual(row["consecutive_failures"], 1)
                self.assertEqual(self.polls(KEY_A)[-1]["outcome"], outcome)
                alerts = self.alerts()
                self.assertEqual(len(alerts), 1, alerts)
                self.assertAlert(alerts[0], FAILED_TPL % (NAME_A, word, 1))
                self.assertEqual(self.runs()[-1]["result"], "partial")

    def test_every_failure_alerts_each_time_with_count(self):
        self.prime()
        self.fail_with("feed", F.timeout())
        for _ in (1, 2, 3):
            self.assertEqual(self.next_run(), IMP.EXIT_AUTHOR_FAILED)
        self.assertEqual([a.split("\n")[0] for a in self.alerts()],
                         [FAILED_TPL % (NAME_A, "逾時", c) for c in (1, 2, 3)])

    def test_consecutive_3_alerts_only_on_third(self):
        self.set_policy("consecutive_3")
        self.prime()
        self.fail_with("feed", F.status(500))
        counts = []
        for _ in range(4):
            self.assertEqual(self.next_run(), IMP.EXIT_AUTHOR_FAILED)
            counts.append(len(self.alerts()))
        self.assertEqual(counts, [0, 0, 1, 1], "只在連續第 3 次發，第 4 次不再發")
        self.assertAlert(self.alerts()[0], FAILED_TPL % (NAME_A, "HTTP 500", 3))
        self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 4)

    def test_success_in_between_resets_count(self):
        self.set_policy("consecutive_3")
        self.prime()
        script = [F.timeout(), F.timeout(), F.not_modified(self.ETAG), F.timeout(), F.timeout()]
        for action in script:
            self.http.routes[FEED_A] = [action]
            self.next_run()
        self.assertEqual(self.alerts(), [], "304 歸零後重新計數，只到 2 不告警")
        self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 2)
        self.http.routes[FEED_A] = [F.timeout()]
        self.next_run()
        self.assertEqual(len(self.alerts()), 1)
        self.assertAlert(self.alerts()[0], FAILED_TPL % (NAME_A, "逾時", 3))
        self.http.routes[FEED_A] = [F.ok(F.make_feed([], host=F.DEFAULT_HOST))]
        self.assertEqual(self.next_run(), IMP.EXIT_OK)
        self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 0, "200 也歸零")

    def test_skipped_interval_does_not_change_count(self):
        self.prime()
        self.fail_with("feed", F.timeout())
        self.next_run()
        self.reset_output()
        self.clock.advance(60)                       # 仍在 30 分鐘間隔內
        self.assertEqual(self.go(), IMP.EXIT_OK)
        self.assertEqual(self.author_row(KEY_A)["consecutive_failures"], 1)
        self.assertEqual(len(self.alerts()), 1, "間隔跳過不告警")

    def test_policy_switch_applies_to_next_failure(self):
        """(4) consecutive_3 下第 1 次不告警 → 切到 every_failure → 第 2 次立即告警（c=2）。"""
        self.set_policy("consecutive_3")
        self.prime()
        self.fail_with("feed", F.network())
        self.next_run()
        self.assertEqual(self.alerts(), [])
        self.set_policy("every_failure")
        self.next_run()
        self.assertEqual([a.split("\n")[0] for a in self.alerts()],
                         [FAILED_TPL % (NAME_A, "網路錯誤", 2)])
        self.set_policy("consecutive_3")
        self.next_run()                              # c=3：新策略下也該告警
        self.next_run()                              # c=4：consecutive_3 不再告警
        self.assertEqual([a.split("\n")[0] for a in self.alerts()],
                         [FAILED_TPL % (NAME_A, "網路錯誤", 2),
                          FAILED_TPL % (NAME_A, "網路錯誤", 3)])

    def test_suppressed_failure_is_still_partial_without_summary(self):
        """consecutive_3 壓下的失敗：仍是 partial／exit 1，但沒有告警也沒有新文章 → 不發任何通知。"""
        self.set_policy("consecutive_3")
        self.prime()
        self.fail_with("feed", F.timeout())
        self.assertEqual(self.next_run(), IMP.EXIT_AUTHOR_FAILED)
        self.assertEqual(self.runs()[-1]["result"], "partial")
        self.assertEqual(self.notifier.texts, [])


class ConfigAlertTest(ImportTestBase):
    """(7) 設定檔不存在／格式錯誤 → 零請求、config_invalid 告警、exit 2。"""

    def assertConfigAlert(self, word):
        alerts = alerts_of(self.notifier)
        self.assertEqual(len(alerts), 1, self.notifier.texts)
        lines = alerts[0].split("\n")
        self.assertEqual(lines[0], CONFIG_TPL % word)
        self.assertRegex(lines[1], SPACE_RE)
        self.assertEqual(len(lines), 2)

    def test_missing_config(self):
        code = self.go("--scheduled")
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0)
        self.assertConfigAlert("不存在")

    def test_invalid_config(self):
        F.write_config(self.dir, alert_policy="sometimes")
        code = self.go("--scheduled")
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0)
        self.assertConfigAlert("格式錯誤")

    def test_broken_json_config(self):
        with open(os.path.join(self.dir, "substack_config.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        code = self.go()
        self.assertEqual(code, IMP.EXIT_REFUSED)
        self.assertEqual(self.http.count(), 0)
        self.assertConfigAlert("格式錯誤")


class DiskAlertTest(FlowBase):
    """(8) 文章交易中磁碟滿 → 立即中止、aborted_disk、exit 4、disk 告警、無半寫入。"""

    AUTHORS = [dict(F.AUTHOR_A)]

    def test_disk_full_mid_article_aborts_cleanly(self):
        import sqlite3
        self.serve_feed(FEED_A, synth_items(F.DEFAULT_HOST, "a", count=3, step_days=1),
                        F.DEFAULT_HOST)
        original = S.SubstackStore._insert_image_rows
        calls = {"n": 0}

        def flaky(store, article_id, images):
            calls["n"] += 1
            if calls["n"] == 2:                      # 第 2 篇：文章列已 INSERT、圖片列時磁碟滿
                raise sqlite3.OperationalError("database or disk is full")
            return original(store, article_id, images)

        with mock.patch.object(S.SubstackStore, "_insert_image_rows", flaky):
            code = self.go("--scheduled")
        self.assertEqual(code, IMP.EXIT_DISK, self.text)
        rows = self.articles()
        self.assertEqual(len(rows), 1, "先前已提交的 1 篇保留、第 2 篇不得半寫入、第 3 篇不再處理")
        self.assertEqual(self._read(lambda s: s.conn.execute(
            "SELECT COUNT(*) FROM article_image WHERE article_id NOT IN "
            "(SELECT id FROM article)").fetchone()[0]), 0)
        self.assertEqual(self.runs()[-1]["result"], "aborted_disk")
        alerts = alerts_of(self.notifier)
        self.assertEqual(len(alerts), 1, self.notifier.texts)
        lines = alerts[0].split("\n")
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], DISK_RE)
        self.assertRegex(lines[1], SPACE_RE)
        self.assertNotIn(F.TITLE_MARK, alerts[0])
        self.assertFalse([t for t in self.notifier.texts if t.startswith("📰")],
                         "中止後不發逐篇通知（維持 pending，下次補發）")
        self.assertEqual(self.http.count(FEED_A), 1)


class AlertHelpersTest(unittest.TestCase):
    """should_alert 與固定文字的單元行為。"""

    def test_should_alert_matrix(self):
        for outcome in ("blocked_403", "rate_limited_429", "challenge_html"):
            for policy in ("every_failure", "consecutive_3"):
                for c in (1, 2, 3, 7):
                    self.assertTrue(IMP.should_alert(outcome, policy, c))
        for outcome, _kind, _action, _word in OTHER_FAILURES:
            for c in (1, 2, 3, 4):
                self.assertTrue(IMP.should_alert(outcome, "every_failure", c))
                self.assertEqual(IMP.should_alert(outcome, "consecutive_3", c), c == 3)

    def test_alert_texts_are_fixed_and_titleless(self):
        self.assertEqual(sorted(IMP.ALERT_TEXTS), ["blocked", "config_invalid", "disk",
                                                   "fetch_failed"])
        for text in IMP.ALERT_TEXTS.values():
            self.assertTrue(text.startswith("⚠️ Substack 匯入："))
            self.assertNotIn("title", text.lower())



# ================================================================ T042 追蹤清單、最小間隔、追補（US5）
import substack_config as CFG  # noqa: E402

WAIT_RE = re.compile(r"還需等待 (\d+) 分鐘")


class Us5Base(FlowBase):
    def set_authors(self, *authors, **overrides):
        """直接改寫設定檔的作者清單（模擬 Claude 代 PO 執行 add／enable／disable 後的結果）。"""
        cfg = dict(self.cfg)
        cfg["authors"] = [dict(a) for a in authors]
        cfg.update(overrides)
        self.cfg = F.write_config(self.dir, **cfg)

    def cli(self, *args):
        out = io.StringIO()
        code = CFG.main(["--data-dir", self.dir] + list(args), env={}, out=out)
        self.assertEqual(code, 0, out.getvalue())

    def disabled(self, author):
        entry = dict(author)
        entry["enabled"] = False
        return entry

    def alerts(self):
        return alerts_of(self.notifier)

    def db_bytes(self):
        with open(self.db_path(), "rb") as f:
            return f.read()


class TrackingListTest(Us5Base):
    """(1)(2)(3)：停用／新增／重新啟用（FR-002、FR-008，US5-AS1／AS2／AS5）。"""

    def test_disabled_author_not_requested_and_articles_kept(self):
        self.serve_both(synth_items(F.DEFAULT_HOST, "a", count=2),
                        synth_items(F.SECOND_HOST, "b", count=2))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        b_rows = [r for r in self.articles() if r["author_key"] == KEY_B]
        self.assertEqual(len(b_rows), 2)
        self.cli("disable", KEY_B)
        self.clock.advance(3600)
        self.reset_output()
        before_b = (self.http.count(FEED_B), self.http.count(ROBOTS_B))
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual((self.http.count(FEED_B), self.http.count(ROBOTS_B)), before_b,
                         "停用作者不得被請求（含 robots）")
        self.assertEqual(self.http.count(FEED_A), 2, "其他作者照常")
        self.assertEqual([dict(r) for r in self.articles() if r["author_key"] == KEY_B],
                         [dict(r) for r in b_rows], "停用作者的已存文章保留、不變")
        self.assertEqual(self.author_row(KEY_B)["last_seen_enabled"], 0)
        self.assertFalse([p for p in self.polls(KEY_B) if p["run_id"] == self.runs()[-1]["id"]],
                         "停用作者本次不寫輪詢紀錄")

    def test_new_author_included_next_run_with_own_window(self):
        self.set_authors(F.AUTHOR_A)
        self.serve_feed(FEED_A, [], F.DEFAULT_HOST)
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertIsNone(self.author_row(KEY_B))
        self.assertEqual(self.http.count(FEED_B), 0)
        # 3 天後 PO 要求新增 B
        self.clock.set_now("2026-11-23 22:00:00")
        self.cli("add", "--key", KEY_B, "--name", NAME_B, "--feed-url", FEED_B)
        items = synth_items(F.SECOND_HOST, "b", count=6, step_days=4,
                            base=datetime.datetime(2026, 11, 23, 9, 0, tzinfo=F.TZ8))
        self.serve_feed(FEED_B, items, F.SECOND_HOST)
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        row = self.author_row(KEY_B)
        self.assertEqual(row["activated_at"], "2026-11-23T22:00:00+08:00")
        self.assertEqual(row["window_from"], "2026-11-09")
        stored = sorted(r["published_at"][:10] for r in self.articles()
                        if r["author_key"] == KEY_B)
        self.assertEqual(stored, ["2026-11-11", "2026-11-15", "2026-11-19", "2026-11-23"])
        self.assertEqual(self.author_row(KEY_A)["activated_at"], "2026-11-20T22:00:00+08:00",
                         "既有作者的啟用基準不受影響")

    def test_reenable_rewrites_activation_and_window(self):
        self.serve_both([], [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.author_row(KEY_B)["activated_at"], "2026-11-20T22:00:00+08:00")
        self.cli("disable", KEY_B)
        self.clock.set_now("2026-11-25 22:00:00")
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(self.author_row(KEY_B)["last_seen_enabled"], 0)
        self.assertEqual(self.author_row(KEY_B)["activated_at"], "2026-11-20T22:00:00+08:00",
                         "停用期間不改啟用基準")
        self.cli("enable", KEY_B)
        self.clock.set_now("2026-11-30 22:00:00")
        items = [F.feed_item(host=F.SECOND_HOST, slug="%s-re-1" % F.SLUG_MARK,
                             published=datetime.datetime(2026, 11, 18, 9, 0, tzinfo=F.TZ8)),
                 F.feed_item(host=F.SECOND_HOST, slug="%s-re-2" % F.SLUG_MARK,
                             published=datetime.datetime(2026, 11, 12, 9, 0, tzinfo=F.TZ8))]
        self.http.routes[FEED_B] = [F.ok(F.make_feed(items, host=F.SECOND_HOST))]
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        row = self.author_row(KEY_B)
        self.assertEqual(row["activated_at"], "2026-11-30T22:00:00+08:00", "重新啟用＝重寫基準")
        self.assertEqual(row["window_from"], "2026-11-16")
        self.assertEqual(row["last_seen_enabled"], 1)
        self.assertEqual([r["published_at"][:10] for r in self.articles()
                          if r["author_key"] == KEY_B], ["2026-11-18"])

    def test_first_activation_written_even_if_fetch_fails_and_kept_on_rerun(self):
        self.set_authors(F.AUTHOR_A)
        self.http.route(FEED_A, F.timeout())
        self.assertEqual(self.go(), IMP.EXIT_AUTHOR_FAILED, self.text)
        self.assertEqual(self.author_row(KEY_A)["activated_at"], "2026-11-20T22:00:00+08:00")
        self.clock.set_now("2026-11-21 22:00:00")
        self.http.routes[FEED_A] = [F.ok(F.make_feed([], host=F.DEFAULT_HOST))]
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        row = self.author_row(KEY_A)
        self.assertEqual(row["activated_at"], "2026-11-20T22:00:00+08:00", "重跑沿用同一基準日")
        self.assertEqual(row["window_from"], "2026-11-06")

    def test_dry_run_does_not_touch_last_seen_enabled(self):
        self.serve_both([], [])
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.cli("disable", KEY_B)
        self.clock.advance(3600)
        self.reset_output()
        self.go("--dry-run")
        self.assertEqual(self.author_row(KEY_B)["last_seen_enabled"], 1,
                         "--dry-run 不得寫 last_seen_enabled")
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)        # 真的執行一次：記為停用
        self.cli("enable", KEY_B)
        self.clock.advance(3600)
        self.reset_output()
        self.go("--dry-run")
        row = self.author_row(KEY_B)
        self.assertEqual(row["last_seen_enabled"], 0)
        self.assertEqual(row["activated_at"], "2026-11-20T22:00:00+08:00",
                         "--dry-run 不得重寫啟用基準")


class MinIntervalTest(Us5Base):
    """(4)：最小間隔守衛（FR-004，US5-AS3／AS4）。"""

    def test_scheduled_run_inside_interval_skips_quietly(self):
        self.clock.set_now("2026-11-20 21:50:00")
        self.serve_feed(FEED_A, [], F.DEFAULT_HOST)
        self.http.route(FEED_B, F.timeout())
        self.go()                                           # 手動：A 成功、B 失敗一次
        self.assertEqual(self.author_row(KEY_B)["consecutive_failures"], 1)
        alerts_before = len(self.alerts())
        requests_before = self.http.count()
        self.clock.set_now("2026-11-20 22:00:00")           # 10 分鐘後排程啟動
        self.reset_output()
        self.assertEqual(self.go("--scheduled"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.count(), requests_before, "間隔內零請求")
        run_id = self.runs()[-1]["id"]
        for key in (KEY_A, KEY_B):
            logs = [p for p in self.polls(key) if p["run_id"] == run_id]
            self.assertEqual(len(logs), 1)
            self.assertEqual((logs[0]["outcome"], logs[0]["requested"]), ("skipped_interval", 0))
        self.assertEqual(self.author_row(KEY_B)["consecutive_failures"], 1, "不增不減")
        self.assertEqual(len(self.alerts()), alerts_before, "不告警")
        self.assertEqual(self.runs()[-1]["authors_skipped_interval"], 2)
        self.assertEqual(self.runs()[-1]["result"], "ok", "間隔跳過不算失敗")

    def test_manual_run_inside_interval_says_how_long_to_wait(self):
        self.serve_both([], [])
        self.go()
        self.clock.set_now("2026-11-20 22:10:00")
        self.reset_output()
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        waits = [int(m) for m in WAIT_RE.findall(self.out.getvalue())]
        # A 在 22:00:00 請求、B 在作者間隔 5 秒後請求 → 剩 20 與 20 分 5 秒（無條件進位成 21）
        self.assertEqual(waits, [20, 21], self.text)
        self.assertEqual(self.http.count(FEED_A), 1)

    def test_changed_interval_applies_to_next_run(self):
        self.serve_both([], [])
        self.go()
        self.cli("set-interval", "10")
        self.clock.set_now("2026-11-20 22:15:00")
        self.reset_output()
        self.go()
        self.assertEqual(self.http.count(FEED_A), 2, "改成 10 分鐘後，15 分鐘就可以再請求")
        self.cli("set-interval", "60")
        self.clock.set_now("2026-11-20 22:55:00")
        self.reset_output()
        self.go()
        self.assertEqual(self.http.count(FEED_A), 2, "改成 60 分鐘後，40 分鐘仍在間隔內")
        self.assertEqual([int(m) for m in WAIT_RE.findall(self.out.getvalue())], [20, 21])


BACKFILL_HINT = "  提示：早於 %s 的文章 feed 已不提供，無法取得（不會改抓其他來源）。"


class BackfillTest(Us5Base):
    """(5)：`--backfill KEY`（FR-008、US5-AS5、research R5、PO 決定 B3）。"""

    ETAG = 'W/"bf-1"'

    def prime(self):
        """一般執行：A 的 feed 20 篇（每 5 天一篇）只存 14 天窗內 3 篇；B 空。"""
        self.http.route(FEED_A, F.ok(F.make_feed(synth_items(F.DEFAULT_HOST, "a"),
                                                 host=F.DEFAULT_HOST), etag=self.ETAG))
        self.serve_feed(FEED_B, [], F.SECOND_HOST)
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 3)
        self.assertEqual(self.author_row(KEY_A)["etag"], self.ETAG)

    def notices(self):
        return [t for t in self.notifier.texts if t.startswith("📰")]

    def summaries(self):
        return [t for t in self.notifier.texts if t.startswith("📚")]

    def test_backfill_stores_older_items_ignoring_window(self):
        self.prime()
        old_rows = [dict(r) for r in self.articles()]
        notices_before = len(self.notices())
        self.clock.advance(31 * 60)
        self.reset_output()
        start = len(self.http.requests)
        code = self.go("--backfill", KEY_A)
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        lines = self.out.getvalue().splitlines()
        self.assertIn("backfill %s: feed_items=20 already=3 stored=17 oldest_in_feed=2026-08-17"
                      % KEY_A, lines)
        self.assertIn(BACKFILL_HINT % "2026-08-17", lines)
        rows = self.articles()
        self.assertEqual(len(rows), 20)
        self.assertEqual([dict(r) for r in rows[:3]], old_rows, "已存文章不重複、不覆寫")
        self.assertEqual({r["source"] for r in rows[3:]}, {"backfill"})
        run = self.runs()[-1]
        self.assertEqual((run["trigger"], run["result"], run["new_articles"]),
                         ("backfill", "ok", 17))
        # 請求：只出現該作者的 robots 與 feed（不抓單篇網頁、不碰其他作者、不下載圖片）
        urls = [r["url"] for r in self.http.requests[start:]]
        self.assertTrue(set(urls) <= {ROBOTS_A, FEED_A}, urls)
        self.assertEqual(urls.count(FEED_A), 1)
        self.assertNotIn("If-None-Match", self.http.headers_for(FEED_A)[-1],
                         "追補不帶 ETag（要拿完整 20 篇）")
        # 通知：逐篇 17 則（不合併）＋摘要標「追補」
        self.assertEqual(len(self.notices()) - notices_before, 17)
        self.assertTrue(self.summaries()[-1].startswith(
            "📚 Substack 匯入（追補）：新增 17 篇"), self.summaries()[-1])
        self.assertNotIn(F.TITLE_MARK, self.text)
        self.assertNotIn(F.SLUG_MARK, self.text)

    def test_backfill_again_finds_nothing_new(self):
        self.prime()
        self.clock.advance(31 * 60)
        self.go("--backfill", KEY_A)
        self.clock.advance(31 * 60)
        self.reset_output()
        calls = self.notifier.calls
        self.assertEqual(self.go("--backfill", KEY_A), IMP.EXIT_OK, self.text)
        self.assertIn("backfill %s: feed_items=20 already=20 stored=0 oldest_in_feed=2026-08-17"
                      % KEY_A, self.out.getvalue().splitlines())
        self.assertEqual(len(self.articles()), 20)
        self.assertEqual(self.notifier.calls, calls, "沒有新存文章就不發通知")

    def test_backfill_inside_interval_refused_with_remaining_minutes(self):
        self.prime()
        self.clock.advance(10 * 60)
        self.reset_output()
        before = (self.http.count(), self.notifier.calls, len(self.runs()))
        code = self.go("--backfill", KEY_A)
        self.assertEqual(code, IMP.EXIT_REFUSED, self.text)
        waits = [int(m) for m in WAIT_RE.findall(self.text)]
        self.assertEqual(len(waits), 1, self.text)
        self.assertTrue(19 <= waits[0] <= 20, waits)
        self.assertEqual((self.http.count(), self.notifier.calls, len(self.runs())), before,
                         "間隔內拒絕：零網路、不通知、不寫執行紀錄")
        self.assertEqual(len(self.articles()), 3)

    def test_backfill_counts_toward_interval_of_next_run(self):
        self.prime()
        self.clock.advance(31 * 60)
        self.go("--backfill", KEY_A)
        self.clock.advance(5 * 60)
        self.reset_output()
        feed_count = self.http.count(FEED_A)
        self.go()
        self.assertEqual(self.http.count(FEED_A), feed_count, "追補後 30 分鐘內一般執行也要跳過")

    def test_backfill_for_never_polled_author(self):
        self.set_authors(F.AUTHOR_A)
        self.serve_feed(FEED_A, synth_items(F.DEFAULT_HOST, "a", count=4, step_days=30),
                        F.DEFAULT_HOST)
        self.assertEqual(self.go("--backfill", KEY_A), IMP.EXIT_OK, self.text)
        self.assertEqual(len(self.articles()), 4, "追補忽略 14 天窗")
        self.assertIn("backfill %s: feed_items=4 already=0 stored=4 oldest_in_feed=2026-08-22"
                      % KEY_A, self.out.getvalue().splitlines())

    def test_backfill_takes_the_lock(self):
        self.prime()
        self.clock.advance(31 * 60)
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = self.http.count()
        self.reset_output()
        self.assertEqual(self.go("--backfill", KEY_A), IMP.EXIT_BUSY, self.text)
        self.assertEqual(self.http.count(), before)
        self.assertEqual(len(self.articles()), 3)

    def test_backfill_unknown_or_disabled_author_refused_without_side_effects(self):
        # 庫不存在：不建庫
        for key in ("zznosuch", KEY_B):
            if key == KEY_B:
                self.set_authors(F.AUTHOR_A, self.disabled(F.AUTHOR_B))
            self.reset_output()
            self.assertEqual(self.go("--backfill", key), IMP.EXIT_REFUSED, self.text)
            self.assertFalse(os.path.exists(self.db_path()), "拒絕時不得建庫")
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0)
        # 庫已存在：位元組不變
        self.set_authors(F.AUTHOR_A, F.AUTHOR_B)
        self.prime()
        self.set_authors(F.AUTHOR_A, self.disabled(F.AUTHOR_B))
        self.clock.advance(3600)
        before = (self.db_bytes(), self.http.count(), self.notifier.calls)
        for key in ("zznosuch", KEY_B):
            self.reset_output()
            self.assertEqual(self.go("--backfill", key), IMP.EXIT_REFUSED, self.text)
        self.assertEqual((self.db_bytes(), self.http.count(), self.notifier.calls), before)

    def test_backfill_fetch_failure_exits_1_and_alerts(self):
        self.prime()
        self.clock.advance(31 * 60)
        self.http.routes[FEED_A] = [F.status(403)]
        self.reset_output()
        self.assertEqual(self.go("--backfill", KEY_A), IMP.EXIT_AUTHOR_FAILED, self.text)
        self.assertEqual(len(self.articles()), 3)
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(self.runs()[-1]["trigger"], "backfill")
        self.assertEqual(self.runs()[-1]["result"], "partial")



# ================================================================ T044 --dry-run 與 --status（cli.md §1）
DRY_REQUEST_RE = re.compile(r"^  (\S+): 會請求", re.M)
DRY_SKIP_RE = re.compile(r"^  (\S+): 會因間隔跳過（還需等待 (\d+) 分鐘）", re.M)
DRY_OFF_RE = re.compile(r"^  (\S+): 停用", re.M)
DRY_MISSING_RE = re.compile(r"缺圖待補 (\d+) 張")
ST_ARTICLES_RE = re.compile(r"文章（有效完整度）：共 (\d+) 篇｜全文 F=(\d+)／僅預覽 P=(\d+)／"
                            r"非文字 N=(\d+)；被重判過 (\d+) 篇")
ST_IMAGES_RE = re.compile(r"圖片：已下載 (\d+)／待下載 (\d+)／缺圖 (\d+)／放棄 (\d+)")
ST_UNNOTIFIED_RE = re.compile(r"通知：未通知 (\d+) 篇")
ST_RUN_RE = re.compile(r"^  run#(\d+) ", re.M)
AUTHOR_C = {"key": "zzauthorc", "name": "測試出版C",
            "feed_url": "https://zzfeedhost-c.example.com/feed", "enabled": True}


class ReadonlyActionBase(Us5Base):
    def populated(self):
        """存一些文章：A 3 篇（圖 1 失敗→缺圖）、B 2 篇；通知全部失敗（未通知）。"""
        self.http.routes[F.image_url(1)] = [F.status(404)]
        self.serve_both(synth_items(F.DEFAULT_HOST, "a"),
                        synth_items(F.SECOND_HOST, "b", count=2))
        self.notifier.fail_all = True
        self.assertEqual(self.go(), IMP.EXIT_OK, self.text)
        self.notifier.fail_all = False
        self.reset_output()

    def snapshot(self):
        return (self.db_bytes(), os.path.getmtime(self.db_path()), self.http.count(),
                self.notifier.calls)


class DryRunTest(ReadonlyActionBase):
    def test_without_db_lists_authors_and_creates_nothing(self):
        self.assertEqual(self.go("--dry-run"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.http.count(), 0, "零網路")
        self.assertEqual(self.notifier.calls, 0)
        self.assertFalse(os.path.exists(self.db_path()), "庫不存在時不建立")
        self.assertEqual(sorted(DRY_REQUEST_RE.findall(self.out.getvalue())), [KEY_A, KEY_B])
        self.assertEqual(DRY_MISSING_RE.findall(self.out.getvalue()), ["0"])

    def test_lists_request_skip_disabled_and_missing_images(self):
        self.populated()
        self.set_authors(F.AUTHOR_A, self.disabled(F.AUTHOR_B), AUTHOR_C)
        self.clock.set_now("2026-11-20 22:10:00")
        before = self.snapshot()
        expected_missing = self._read(lambda s: len(s.images_awaiting_download()))
        self.assertGreater(expected_missing, 0)
        self.assertEqual(self.go("--dry-run"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.snapshot(), before, "零網路、零通知、庫位元組與 mtime 不變")
        text = self.out.getvalue()
        self.assertEqual(DRY_REQUEST_RE.findall(text), [AUTHOR_C["key"]])
        skips = DRY_SKIP_RE.findall(text)
        self.assertEqual([k for k, _ in skips], [KEY_A])
        self.assertIn(int(skips[0][1]), (19, 20))
        self.assertEqual(DRY_OFF_RE.findall(text), [KEY_B])
        self.assertEqual(DRY_MISSING_RE.findall(text), [str(expected_missing)])
        self.assertEqual(F.marks_in(self.text), [], "輸出不含標題、內文、網址")
        self.assertEqual(len(self.runs()), 1, "dry-run 不寫執行紀錄")

    def test_invalid_config_refused_without_network_or_alert(self):
        with open(os.path.join(self.dir, "substack_config.json"), "w", encoding="utf-8") as f:
            f.write("{壞掉")
        self.assertEqual(self.go("--dry-run"), IMP.EXIT_REFUSED, self.text)
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0, "dry-run 不發告警")
        self.assertFalse(os.path.exists(self.db_path()))

    def test_scheduled_dry_run_reports_schedule_judgement(self):
        self.clock.set_now("2026-11-20 23:30:00")
        self.assertEqual(self.go("--scheduled", "--dry-run"), IMP.EXIT_OK, self.text)
        self.assertIn("deferred", self.out.getvalue())
        self.assertEqual(DRY_REQUEST_RE.findall(self.out.getvalue()), [])
        self.clock.set_now("2026-11-20 22:00:00")
        self.reset_output()
        self.assertEqual(self.go("--scheduled", "--dry-run"), IMP.EXIT_OK, self.text)
        self.assertEqual(sorted(DRY_REQUEST_RE.findall(self.out.getvalue())), [KEY_A, KEY_B])
        self.assertEqual(self.http.count(), 0)
        self.assertFalse(os.path.exists(self.db_path()))

    def test_dry_run_does_not_take_lock(self):
        self.populated()
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.go("--dry-run"), IMP.EXIT_OK, self.text)

    def test_dry_run_only_with_run_or_scheduled(self):
        for argv in (["--dry-run", "--backfill", KEY_A], ["--dry-run", "--status"],
                     ["--dry-run", "--retry-images", "1"]):
            self.reset_output()
            self.assertEqual(self.go(*argv), IMP.EXIT_REFUSED, argv)
        self.assertEqual(self.http.count(), 0)


class StatusTest(ReadonlyActionBase):
    def expected(self):
        def collect(s):
            return {"comp": s.completeness_counts(effective=True),
                    "images": s.image_status_counts(),
                    "unnotified": s.unnotified_count(),
                    "articles": len(s.list_articles())}
        return self._read(collect)

    def test_status_reports_counts_readonly_and_titleless(self):
        self.populated()
        self.clock.advance(3600)
        a_id = self.articles()[0]["id"]
        self.assertEqual(self.go("--reclassify", "--article-ids", str(a_id)), IMP.EXIT_OK)
        self.set_authors(F.AUTHOR_A, self.disabled(F.AUTHOR_B))
        for _ in range(5):                       # 累積到 7 次執行，只列最近 5 次
            self.clock.advance(3600)
            self.reset_output()
            self.go()
        exp = self.expected()
        self.reset_output()
        before = self.snapshot()
        self.assertEqual(self.go("--status"), IMP.EXIT_OK, self.text)
        self.assertEqual(self.snapshot(), before, "唯讀：零網路、零通知、庫位元組與 mtime 不變")
        text = self.out.getvalue()
        m = ST_ARTICLES_RE.search(text)
        self.assertIsNotNone(m, text)
        c = exp["comp"]
        self.assertEqual(tuple(int(x) for x in m.groups()),
                         (exp["articles"], c["F"], c["P"], c["N"], 1))
        m = ST_IMAGES_RE.search(text)
        i = exp["images"]
        self.assertEqual(tuple(int(x) for x in m.groups()),
                         (i["downloaded"], i["pending"], i["missing"], i["abandoned"]))
        self.assertGreater(i["missing"] + i["abandoned"], 0, "夾具應產生缺圖／放棄的圖片")
        self.assertEqual(ST_UNNOTIFIED_RE.findall(text), [str(exp["unnotified"])])
        runs = [int(x) for x in ST_RUN_RE.findall(text)]
        self.assertEqual(runs, [r["id"] for r in reversed(self.runs())][:5], "最近 5 次、新到舊")
        # 作者狀態：停用作者與其已存文章仍可見（US5-AS2）
        lines = text.splitlines()
        b_line = [l for l in lines if l.startswith("  %s " % KEY_B)]
        self.assertEqual(len(b_line), 1, text)
        self.assertIn("設定=停用", b_line[0])
        self.assertIn("文章=2", b_line[0])
        a_line = [l for l in lines if l.startswith("  %s " % KEY_A)][0]
        self.assertIn("設定=啟用", a_line)
        self.assertIn("文章=3", a_line)
        self.assertEqual(F.marks_in(self.text), [], "輸出不含標題、內文、網址")

    def test_status_without_db_refuses_and_creates_nothing(self):
        self.assertEqual(self.go("--status"), IMP.EXIT_REFUSED, self.text)
        self.assertFalse(os.path.exists(self.db_path()))
        self.assertEqual(self.http.count(), 0)

    def test_status_does_not_take_lock_or_need_config(self):
        self.populated()
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.remove(os.path.join(self.dir, "substack_config.json"))
        calls, requests = self.notifier.calls, self.http.count()
        self.assertEqual(self.go("--status"), IMP.EXIT_OK, self.text)
        self.assertIn("設定檔無法讀取", self.out.getvalue())
        self.assertEqual((self.notifier.calls, self.http.count()), (calls, requests))


if __name__ == "__main__":
    unittest.main()
