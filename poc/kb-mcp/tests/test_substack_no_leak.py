"""T027：不外洩負向測試（V7、SC-005、FR-026；比照 tests/test_investanchors_no_leak.py 的四個面）。

跑一次完整成功路徑（兩位作者、含 F／P／N 三類、含圖位標記），收集四個面並逐一斷言：

1. stdout／stderr：不得含標題、內文、文章網址 slug、圖片網址（四個 *_MARK 全不得出現）；
2. Telegram 通知：**可以**含標題（FR-027 例外），但不得含內文、slug、圖片網址；
3. 資料庫中**非資料通道**的 TEXT 欄位：不得含任何標記
   （資料通道＝`article.title`／`link`／`link_norm`／`content_html`／`body_text`／`description`、
   `article_image.src_url`／`alt`／`caption`、`image_transcription.text`、`robots_cache.body`）；
4. 資料目錄下所有檔名：不得含任何標記。

另外一律經 `investanchors_redact.assert_clean` 檢查 cookie／CSRF／追蹤 token。
零真實網路；本檔案只注入假物件。
"""
import datetime
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import investanchors_redact as R  # noqa: E402
import substack_import as IMP  # noqa: E402
import substack_store as S  # noqa: E402

MARKS = (F.TITLE_MARK, F.BODY_MARK, F.SLUG_MARK, F.IMG_URL_MARK)
NOTICE_FORBIDDEN = (F.BODY_MARK, F.SLUG_MARK, F.IMG_URL_MARK)       # 通知可含標題，其餘不行

# 資料通道：這些欄位本來就要存文章內容，不算外洩（data-model §1.2／§1.3）
#
# 補充（T027 條列中未提到，但依 data-model §1.2 必然是資料通道）：`article.guid`
# 是站方自己的去重識別字、必須**原字串**保存，而 Substack 的 guid 實務上就含文章 slug，
# 所以它和 `link` 同性質。guid 不會進日誌／通知（面 1、2、4 的 SLUG_MARK 斷言守住這點）。
DATA_CHANNELS = {
    ("article", "title"), ("article", "link"), ("article", "link_norm"),
    ("article", "guid"),
    ("article", "content_html"), ("article", "body_text"), ("article", "description"),
    ("article_image", "src_url"), ("article_image", "alt"), ("article_image", "caption"),
    ("image_transcription", "text"), ("robots_cache", "body"),
}

SAMPLES = (("full", "full_no_tail", datetime.datetime(2026, 11, 18, 9, 0, tzinfo=F.TZ8)),
           ("prev", "preview_short", datetime.datetime(2026, 11, 19, 9, 0, tzinfo=F.TZ8)),
           ("nont", "player_only", datetime.datetime(2026, 11, 20, 8, 0, tzinfo=F.TZ8)),
           ("imgs", "multi_image", datetime.datetime(2026, 11, 20, 9, 0, tzinfo=F.TZ8)))


def build_items(host, prefix, tags=None):
    out = []
    for tag, sample, published in (tags or SAMPLES):
        slug = "%s-%s-%s" % (F.SLUG_MARK, prefix, tag)      # 兩位作者的 guid 不得撞號
        link = "https://%s/p/%s" % (host, slug)
        out.append(F.feed_item(host=host, slug=slug, published=published,
                               title="%s 標題-%s" % (F.TITLE_MARK, tag),
                               content_html=F.article_samples(link)[sample],
                               enclosure=("image/jpeg",
                                          "https://%s/%s-cover.jpg" % (F.IMAGE_HOST,
                                                                       F.IMG_URL_MARK))))
    return out


class NoLeakTest(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.notifier = F.FakeNotifier()
        self.out, self.err = io.StringIO(), io.StringIO()
        F.write_config(self.dir)
        for host in (F.DEFAULT_HOST, F.SECOND_HOST):
            self.http.route("https://%s/robots.txt" % host, F.ok("", content_type="text/plain"))
        self.http.route(F.AUTHOR_A["feed_url"],
                        F.ok(F.make_feed(build_items(F.DEFAULT_HOST, "a"), host=F.DEFAULT_HOST)))
        self.http.route(F.AUTHOR_B["feed_url"],
                        F.ok(F.make_feed(build_items(F.SECOND_HOST, "b"), host=F.SECOND_HOST)))
        code = IMP.run(["--data-dir", self.dir, "--scheduled"], http=self.http,
                       notifier=self.notifier, clock=self.clock, sleep=self.clock.sleep,
                       env={}, out=self.out, err=self.err)
        self.assertEqual(code, IMP.EXIT_OK, self.text())
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.list_articles()), 8, "成功路徑必須真的存進文章")
        self.assertTrue(self.notifier.texts, "成功路徑必須真的發出通知")

    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    # ---- 面 1：stdout／stderr
    def test_stdout_and_stderr_have_no_marks(self):
        text = self.text()
        for mark in MARKS:
            self.assertNotIn(mark, text, "stdout／stderr 出現 %s" % mark)
        R.assert_clean(text, (), MARKS)

    # ---- 面 2：通知
    def test_notifications_may_carry_title_only(self):
        self.assertTrue(any(F.TITLE_MARK in t for t in self.notifier.texts),
                        "通知本來就該含標題，否則這個面是空轉")
        for text in self.notifier.texts:
            for mark in NOTICE_FORBIDDEN:
                self.assertNotIn(mark, text, "通知出現 %s" % mark)
            self.assertNotIn("http://", text)
            self.assertNotIn("https://", text)
            R.assert_clean(text, (), NOTICE_FORBIDDEN)

    # ---- 面 3：資料庫非資料通道欄位
    def test_non_data_channel_columns_have_no_marks(self):
        checked = 0
        tables = [r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertIn("article", tables)
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            columns = [(r[1], (r[2] or "").upper())
                       for r in self.store.conn.execute("PRAGMA table_info(%s)" % table)]
            for name, ctype in columns:
                if (table, name) in DATA_CHANNELS or ctype not in ("TEXT", ""):
                    continue
                for (value,) in self.store.conn.execute("SELECT %s FROM %s" % (name, table)):
                    if value is None:
                        continue
                    checked += 1
                    label = "%s.%s=%s" % (table, name, value)
                    for mark in MARKS:
                        self.assertNotIn(mark, str(value), label)
                    R.assert_clean(label, (), MARKS)
        self.assertGreater(checked, 0, "一個非資料通道欄位都沒檢查到，守門失效")

    def test_data_channel_really_holds_the_content(self):
        """反向確認：標記確實存在於資料通道，否則上面三個面都是空轉。"""
        row = [r for r in self.store.list_articles() if r["completeness"] == "F"][0]
        self.assertIn(F.TITLE_MARK, row["title"])
        self.assertIn(F.BODY_MARK, row["content_html"])
        self.assertIn(F.BODY_MARK, row["body_text"])
        self.assertIn(F.SLUG_MARK, row["link"])
        images = self.store.list_images(row["id"])
        self.assertTrue(images)
        self.assertTrue(any(F.IMG_URL_MARK in i["src_url"] for i in images))

    # ---- 面 4：檔名
    def test_filenames_have_no_marks(self):
        seen = 0
        for root, _dirs, files in os.walk(self.dir):
            for name in files:
                seen += 1
                path = os.path.join(root, name)
                for mark in MARKS:
                    self.assertNotIn(mark, path, path)
                R.assert_clean(path, (), MARKS)
        self.assertGreater(seen, 0)


# ================================================================ T039（US4）失敗路徑不外洩
TOKEN = F.FakeNotifier.FAKE_BOT_TOKEN
# 故意塞進例外訊息與回應內容的毒字串：標題、slug、假 Bot token
POISON = "%s https://%s/p/%s-x bot%s" % (F.TITLE_MARK, F.DEFAULT_HOST, F.SLUG_MARK, TOKEN)
FAIL_FORBIDDEN = MARKS + (TOKEN,)


class _PoisonHttp(object):
    """包住 FakeHttp：feed 網址改丟「訊息含毒字串」的例外；其餘照 FakeHttp 腳本。"""

    def __init__(self, inner, url, exc):
        self.inner = inner
        self.url = url
        self.exc = exc

    def __call__(self, url, headers=None, timeout=None):
        if url == self.url:
            self.inner.requests.append({"url": url, "headers": dict(headers or {}),
                                        "timeout": timeout})
            raise self.exc
        return self.inner(url, headers=headers, timeout=timeout)


class _RaisingNotifier(object):
    """通知通道直接丟出含毒字串的例外（比 FakeNotifier 的錯誤清單更兇）。"""

    def __init__(self):
        self.texts = []
        self.calls = 0

    def __call__(self, text, *args, **kwargs):
        self.calls += 1
        self.texts.append(text)
        raise RuntimeError("telegram 失敗：%s" % POISON)


class FailurePathNoLeakTest(unittest.TestCase):
    """403、挑戰頁、逾時、解析失敗、磁碟滿、設定檔錯誤、通知失敗各跑一次，四個面皆只出現代碼。"""

    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.notifier = F.FakeNotifier()
        self.out, self.err = io.StringIO(), io.StringIO()
        self.http.route("https://%s/robots.txt" % F.DEFAULT_HOST,
                        F.ok("", content_type="text/plain"))
        self.http.route(F.image_url(1), F.image_ok())

    def config(self):
        F.write_config(self.dir, authors=[dict(F.AUTHOR_A)])

    def serve_good_feed(self):
        self.http.route(F.AUTHOR_A["feed_url"],
                        F.ok(F.make_feed(build_items(F.DEFAULT_HOST, "a", SAMPLES[:1]),
                                         host=F.DEFAULT_HOST)))

    def go(self, http=None, notifier=None):
        return IMP.run(["--data-dir", self.dir, "--scheduled"],
                       http=http if http is not None else self.http,
                       notifier=notifier if notifier is not None else self.notifier,
                       clock=self.clock, sleep=self.clock.sleep, env={},
                       out=self.out, err=self.err)

    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    # ---- 四個面
    def assert_four_surfaces(self, texts):
        # 面 1：stdout／stderr
        console = self.text()
        for needle in FAIL_FORBIDDEN:
            self.assertNotIn(needle, console, "stdout／stderr 出現 %s" % needle[:16])
        R.assert_clean(console, (TOKEN,), MARKS)
        # 面 2：通知（告警／摘要什麼標記都不得有；逐篇通知只可含標題）
        for text in texts:
            allowed_title = text.startswith("📰")
            for needle in FAIL_FORBIDDEN:
                if allowed_title and needle == F.TITLE_MARK:
                    continue
                self.assertNotIn(needle, text, "通知出現 %s" % needle[:16])
            self.assertNotIn("http", text)
            R.assert_clean(text, (TOKEN,), tuple(n for n in MARKS
                                                 if not (allowed_title and n == F.TITLE_MARK)))
        # 面 3：資料庫非資料通道欄位
        db = os.path.join(self.dir, S.DB_FILENAME)
        if os.path.exists(db):
            store = S.SubstackStore(self.dir)
            try:
                tables = [r[0] for r in store.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]
                for table in tables:
                    if table.startswith("sqlite_"):
                        continue
                    for row in store.conn.execute("PRAGMA table_info(%s)" % table).fetchall():
                        name, ctype = row[1], (row[2] or "").upper()
                        if (table, name) in DATA_CHANNELS or ctype not in ("TEXT", ""):
                            continue
                        for (value,) in store.conn.execute(
                                "SELECT %s FROM %s" % (name, table)):
                            if value is None:
                                continue
                            for needle in FAIL_FORBIDDEN:
                                self.assertNotIn(needle, str(value),
                                                 "%s.%s 出現 %s" % (table, name, needle[:16]))
                # 資料通道也不得出現 token（token 從不是文章內容）
                for (dump,) in store.conn.execute(
                        "SELECT group_concat(coalesce(title,'')||coalesce(content_html,''), '') "
                        "FROM article"):
                    self.assertNotIn(TOKEN, str(dump or ""))
            finally:
                store.close()
        # 面 4：檔名
        for root, _dirs, files in os.walk(self.dir):
            for name in files:
                path = os.path.join(root, name)
                for needle in FAIL_FORBIDDEN:
                    self.assertNotIn(needle, path)

    def alerts(self, notifier=None):
        return [t for t in (notifier or self.notifier).texts if t.startswith("⚠️")]

    # ---- 七種失敗
    def test_403_with_poisoned_body(self):
        self.config()
        self.http.route(F.AUTHOR_A["feed_url"], F.status(403, body=POISON))
        self.assertEqual(self.go(), IMP.EXIT_AUTHOR_FAILED, self.text())
        self.assertIn("blocked_403", self.out.getvalue())
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_challenge_page_with_poisoned_body(self):
        self.config()
        self.http.route(F.AUTHOR_A["feed_url"],
                        F.ok(F.CHALLENGE_HTML + POISON, content_type="text/html"))
        self.assertEqual(self.go(), IMP.EXIT_AUTHOR_FAILED, self.text())
        self.assertIn("challenge_html", self.out.getvalue())
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_timeout_with_poisoned_exception(self):
        import socket
        self.config()
        http = _PoisonHttp(self.http, F.AUTHOR_A["feed_url"], socket.timeout(POISON))
        self.assertEqual(self.go(http=http), IMP.EXIT_AUTHOR_FAILED, self.text())
        self.assertIn("timeout", self.out.getvalue())
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_parse_failure_with_poisoned_body(self):
        self.config()
        self.http.route(F.AUTHOR_A["feed_url"],
                        F.ok("<rss><channel><title>%s</title><item>" % POISON))
        self.assertEqual(self.go(), IMP.EXIT_AUTHOR_FAILED, self.text())
        self.assertIn("parse_error", self.out.getvalue())
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_disk_full_with_poisoned_exception(self):
        import sqlite3
        from unittest import mock
        self.config()
        self.serve_good_feed()

        def boom(store, article_id, images):
            raise sqlite3.OperationalError("database or disk is full: %s" % POISON)

        with mock.patch.object(S.SubstackStore, "_insert_image_rows", boom):
            self.assertEqual(self.go(), IMP.EXIT_DISK, self.text())
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_config_error_with_poisoned_file(self):
        with open(os.path.join(self.dir, "substack_config.json"), "w", encoding="utf-8") as f:
            f.write("{ %s" % POISON)
        self.assertEqual(self.go(), IMP.EXIT_REFUSED, self.text())
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(len(self.alerts()), 1)
        self.assert_four_surfaces(self.notifier.texts)

    def test_notify_failure_error_list_and_exception(self):
        for notifier in (F.FakeNotifier(fail_all=True), _RaisingNotifier()):
            with self.subTest(notifier=type(notifier).__name__):
                self.setUp()
                self.config()
                self.serve_good_feed()
                self.assertEqual(self.go(notifier=notifier), IMP.EXIT_OK, self.text())
                self.assertIn("failed=", self.out.getvalue())
                self.assertNotIn("failed=0", self.out.getvalue(), "必須真的走到通知失敗")
                self.assertTrue(any(t.startswith("📰") for t in notifier.texts))
                self.assert_four_surfaces(notifier.texts)

    def test_notify_failure_on_alert_path(self):
        """告警本身發送失敗（錯誤含假 token）也不得落地。"""
        self.config()
        self.http.route(F.AUTHOR_A["feed_url"], F.status(429, body=POISON))
        notifier = F.FakeNotifier(fail_all=True)
        self.assertEqual(self.go(notifier=notifier), IMP.EXIT_AUTHOR_FAILED, self.text())
        self.assertIn("alert: failed", self.out.getvalue())
        self.assert_four_surfaces(notifier.texts)


if __name__ == "__main__":
    unittest.main()
