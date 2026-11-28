"""T016：PO 要求重新判斷完整度（FR-033、FR-011／spec Q14；research R11；V12、SC-012）。

重點：原判斷與原始內容**位元組不變**、重判紀錄只增不改、有效值取最近一筆、
零網路零模型零通知、N 類重判為 F／P 時內文存在重判紀錄的 `derived_body_text`。
"""
import fcntl
import io
import os
import socket
import subprocess
import sys
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_html as H  # noqa: E402
import substack_import as IMP  # noqa: E402
import substack_reclassify as RC  # noqa: E402
import substack_store as S  # noqa: E402


class NoNetworkGuard(object):
    """執行期攔截：重判期間不得有任何網路或子行程呼叫。"""

    def __init__(self, test):
        self.calls = []
        self._saved = []
        for module, name in ((urllib.request, "urlopen"), (socket, "create_connection"),
                             (subprocess, "Popen"), (subprocess, "run")):
            self._saved.append((module, name, getattr(module, name)))
            setattr(module, name, self._make(name))
        test.addCleanup(self.restore)

    def _make(self, label):
        def blocked(*args, **kwargs):
            self.calls.append(label)
            raise AssertionError("重判不得呼叫 %s" % label)
        return blocked

    def restore(self):
        for module, name, original in self._saved:
            setattr(module, name, original)


class ReclassifyTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.notifier = F.FakeNotifier()
        self.http = F.FakeHttp(self.clock)
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)
        self.counter = 0

    @property
    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    def db_path(self):
        return os.path.join(self.dir, "substack.db")

    def db_bytes(self):
        with open(self.db_path(), "rb") as f:
            return f.read()

    def article_rows(self):
        return [tuple(r) for r in self.store.conn.execute("SELECT * FROM article ORDER BY id")]

    def add(self, sample, author_key=None, completeness=None, reason=None, body=None,
            host=None):
        """以指定的「原判斷」直接插入一篇文章（模擬舊規則留下的判斷）。"""
        self.counter += 1
        host = host or F.DEFAULT_HOST
        link = "https://%s/p/%s-%d" % (host, F.SLUG_MARK, self.counter)
        html = F.article_samples(link)[sample]
        natural = H.analyze(html, link)
        completeness = natural["completeness"] if completeness is None else completeness
        reason = natural["reason"] if reason is None else reason
        if body is None:
            body = None if completeness == "N" else (natural["body_text"] or "")
        row = F.article_row(author_key=author_key or F.AUTHOR_A["key"], link=link, link_norm=link,
                            completeness=completeness, classify_reason=reason,
                            content_html=html, body_text=body)
        images = [{"seq": i["seq"], "src_url": i["src"], "alt": i["alt"], "caption": i["caption"]}
                  for i in natural["images"]]
        return self.store.insert_article_with_images(row, images)

    def go(self, *args):
        self.out, self.err = io.StringIO(), io.StringIO()
        return IMP.run(["--data-dir", self.dir] + list(args), http=self.http,
                       notifier=self.notifier, clock=self.clock, sleep=self.clock.sleep,
                       env={}, out=self.out, err=self.err)

    def rows(self, article_id=None):
        return self.store.reclassification_rows([article_id] if article_id else None)


class ReclassifyByIdsTest(ReclassifyTestBase):
    def test_article_ids_adds_one_row_each(self):
        guard = NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        a2 = self.add("preview_short")
        code = self.go("--reclassify", "--article-ids", "%d,%d" % (a1, a2))
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        by_article = {r["article_id"]: r for r in rows}
        self.assertEqual(by_article[a1]["old_completeness"], "P")
        self.assertEqual(by_article[a1]["new_completeness"], "F")
        self.assertEqual(by_article[a1]["changed"], 1)
        self.assertEqual(by_article[a2]["new_completeness"], "P")
        self.assertEqual(by_article[a2]["changed"], 0, "結果相同也要記一列")
        for row in rows:
            self.assertEqual(row["rule_version"], H.RULE_VERSION)
            self.assertEqual(row["trigger"], "po_article")
        self.assertEqual(guard.calls, [])
        self.assertEqual(self.notifier.calls, 0, "重判不得發通知")
        self.assertEqual(self.http.count(), 0)

    def test_effective_takes_latest_and_keeps_original(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        self.assertEqual(self.go("--reclassify", "--article-ids", str(a1)), IMP.EXIT_OK)
        self.assertEqual(self.go("--reclassify", "--article-ids", str(a1)), IMP.EXIT_OK)
        rows = self.rows(a1)
        self.assertEqual(len(rows), 2)
        self.assertLess(rows[0]["id"], rows[1]["id"])
        self.assertEqual(rows[1]["old_completeness"], "F",
                         "第二次的 old 應等於第一次的 new（當下有效值）")
        effective = self.store.effective_article(a1)
        self.assertEqual(effective["effective_completeness"], "F")
        self.assertEqual(effective["original_completeness"], "P")
        self.assertEqual(effective["reclassified_count"], 2)
        self.assertEqual(RC.effective_completeness(self.store, a1), "F")

    def test_article_row_bytes_unchanged(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        a2 = self.add("player_only")
        before = self.article_rows()
        self.assertEqual(self.go("--reclassify", "--article-ids", "%d,%d" % (a1, a2)),
                         IMP.EXIT_OK)
        self.assertEqual(self.article_rows(), before,
                         "重判前後 article 每個欄位都必須位元組相同")

    def test_missing_ids_reported_and_exit_1(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        code = self.go("--reclassify", "--article-ids", "%d,9999" % a1)
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED)
        self.assertIn("9999", self.text)
        self.assertEqual(len(self.rows()), 1, "存在的 id 仍照常重判")

    def test_all_missing_ids_exit_1_without_any_row(self):
        NoNetworkGuard(self)
        self.add("full_long")
        code = self.go("--reclassify", "--article-ids", "8888,9999")
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED)
        self.assertEqual(self.rows(), [])

    def test_stdout_has_no_title(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        self.go("--reclassify", "--article-ids", str(a1))
        self.assertNotIn(F.TITLE_MARK, self.text)
        self.assertNotIn(F.BODY_MARK, self.text)
        self.assertNotIn(F.SLUG_MARK, self.text)

    def test_writes_one_run_row(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long")
        self.go("--reclassify", "--article-ids", str(a1))
        runs = self.store.recent_runs(10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["trigger"], "reclassify")
        self.assertIsNotNone(runs[0]["finished_at"])
        self.assertEqual(self.rows()[0]["run_id"], runs[0]["id"])


class ReclassifyByAuthorTest(ReclassifyTestBase):
    def test_author_scope_only(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        a2 = self.add("preview_short")
        b1 = self.add("full_no_tail", author_key=F.AUTHOR_B["key"], host=F.SECOND_HOST)
        code = self.go("--reclassify", "--author", F.AUTHOR_A["key"])
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        touched = {r["article_id"] for r in self.rows()}
        self.assertEqual(touched, {a1, a2})
        self.assertNotIn(b1, touched)
        for row in self.rows():
            self.assertEqual(row["trigger"], "po_author")

    def test_unknown_author_touches_nothing(self):
        NoNetworkGuard(self)
        self.add("full_long")
        code = self.go("--reclassify", "--author", "zznosuchauthor")
        self.assertEqual(code, IMP.EXIT_OK)
        self.assertEqual(self.rows(), [])


class ReclassifyDryRunTest(ReclassifyTestBase):
    def test_dry_run_writes_nothing_and_lists_changes(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        a2 = self.add("preview_short")
        self.store.close()
        before = self.db_bytes()
        code = self.go("--reclassify", "--article-ids", "%d,%d" % (a1, a2), "--dry-run")
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        self.assertEqual(self.db_bytes(), before, "--dry-run 不得寫庫")
        self.assertIn(str(a1), self.out.getvalue())
        self.assertIn("P→F", self.out.getvalue())
        self.store = S.SubstackStore(self.dir)
        self.assertEqual(self.rows(), [])


class ReclassifyLockTest(ReclassifyTestBase):
    def test_busy_exits_3_without_writing(self):
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        handle = open(os.path.join(self.dir, IMP.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = self.go("--reclassify", "--article-ids", str(a1))
        self.assertEqual(code, IMP.EXIT_BUSY)
        self.assertIn("忙碌", self.text)
        self.assertEqual(self.rows(), [])


class ReclassifyHistoryTest(ReclassifyTestBase):
    def test_history_is_readonly_and_lists_everything(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long", completeness="P", reason="uncertain:parse_error")
        self.go("--reclassify", "--article-ids", str(a1))
        self.go("--reclassify", "--article-ids", str(a1))
        self.store.close()
        before = self.db_bytes()
        code = self.go("--reclassify-history", str(a1))
        self.assertEqual(code, IMP.EXIT_OK, self.text)
        text = self.out.getvalue()
        self.assertIn("P", text)
        self.assertIn("F", text)
        self.assertIn(H.RULE_VERSION, text)
        self.assertEqual(text.count("→"), 2, "兩次重判都要列出")
        self.assertNotIn(F.TITLE_MARK, text)
        self.assertEqual(self.db_bytes(), before, "唯讀列出不得改變資料庫位元組")

    def test_history_reports_missing_ids(self):
        NoNetworkGuard(self)
        a1 = self.add("full_long")
        code = self.go("--reclassify-history", "%d,7777" % a1)
        self.assertEqual(code, IMP.EXIT_AUTHOR_FAILED)
        self.assertIn("7777", self.text)


class NonTextReclassifyTest(ReclassifyTestBase):
    """spec Q14／FR-011／SC-015(f)：N 類重判的內文產生。"""

    def setUp(self):
        ReclassifyTestBase.setUp(self)
        self.guard = NoNetworkGuard(self)
        # 原判斷 N（body_text 為 NULL），但原始內容其實是全文
        self.aid = self.add("full_long", completeness="N", reason="text_lt_200", body=None)
        self.html = self.store.get_article(self.aid)["content_html"]
        self.link = self.store.get_article(self.aid)["link"]

    def test_n_to_f_produces_derived_body_text(self):
        before = self.article_rows()
        self.assertEqual(self.go("--reclassify", "--article-ids", str(self.aid)), IMP.EXIT_OK)
        row = self.rows(self.aid)[-1]
        self.assertEqual(row["new_completeness"], "F")
        expected, _ = H.html_to_text(self.html, link=self.link)
        self.assertEqual(row["derived_body_text"], expected)
        effective = self.store.effective_article(self.aid)
        self.assertIsNotNone(effective["effective_body_text"])
        self.assertEqual(effective["effective_body_text"], expected)
        self.assertEqual(self.article_rows(), before, "article 欄位位元組不變（body_text 仍 NULL）")
        self.assertIsNone(self.store.get_article(self.aid)["body_text"])
        self.assertEqual(self.guard.calls, [])
        self.assertEqual(self.http.count(), 0)
        self.assertEqual(self.notifier.calls, 0, "重判不得產生新的 N 類提醒")

    def test_back_to_n_hides_body_but_keeps_history(self):
        self.go("--reclassify", "--article-ids", str(self.aid))
        first = self.rows(self.aid)[-1]
        self.assertIsNotNone(first["derived_body_text"])
        # 以重判把它變回 N：直接寫一列（模擬規則調整後的結果）
        self.store.add_reclassification(article_id=self.aid, trigger="po_article",
                                        old_completeness="F", new_completeness="N",
                                        new_reason="text_lt_200",
                                        rule_version=H.RULE_VERSION, run_id=None)
        effective = self.store.effective_article(self.aid)
        self.assertEqual(effective["effective_completeness"], "N")
        self.assertIsNone(effective["effective_body_text"], "有效完整度 N 不提供內文")
        kept = self.store.reclassification_rows([self.aid])[0]
        self.assertIsNotNone(kept["derived_body_text"], "舊列的 derived_body_text 要保留")

    def test_still_n_leaves_derived_null(self):
        aid = self.add("player_only")        # 自然就是 N
        self.assertEqual(self.go("--reclassify", "--article-ids", str(aid)), IMP.EXIT_OK)
        row = self.rows(aid)[-1]
        self.assertEqual(row["new_completeness"], "N")
        self.assertIsNone(row["derived_body_text"])
        self.assertIsNone(self.store.effective_article(aid)["effective_body_text"])

    def test_f_reclassified_to_n_hides_body(self):
        aid = self.add("full_no_tail")       # 原判斷 F、body_text 有值
        self.store.add_reclassification(article_id=aid, trigger="po_article",
                                        old_completeness="F", new_completeness="N",
                                        new_reason="text_lt_200",
                                        rule_version=H.RULE_VERSION, run_id=None)
        effective = self.store.effective_article(aid)
        self.assertEqual(effective["effective_completeness"], "N")
        self.assertIsNone(effective["effective_body_text"])
        self.assertIsNotNone(self.store.get_article(aid)["body_text"],
                             "article.body_text 本身不被改動")

    def test_existing_body_is_not_recomputed(self):
        aid = self.add("full_no_tail")
        self.assertEqual(self.go("--reclassify", "--article-ids", str(aid)), IMP.EXIT_OK)
        row = self.rows(aid)[-1]
        self.assertIsNone(row["derived_body_text"],
                          "body_text 已有值者不重算、不覆寫（research R11）")


if __name__ == "__main__":
    unittest.main()
