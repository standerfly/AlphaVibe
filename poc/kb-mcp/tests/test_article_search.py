"""T025：ArticleStore.search_articles／get_article（LIKE，非 FTS5）。"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _article_fixture as F  # noqa: E402
import article_store as A  # noqa: E402


class SearchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="article-search-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.build(self.tmp)
        self.s = A.ArticleStore.open_readonly(self.tmp)
        self.addCleanup(self.s.close)

    def ids(self, q, **kw):
        return [r["article_id"] for r in self.s.search_articles(q, **kw)]


class SearchTest(SearchBase):
    def test_two_char_chinese(self):
        self.assertEqual(self.ids("環宇"), [101])      # 105 非 fetched 不出現
        self.assertEqual(self.ids("財測"), [101])

    def test_english_three_letters_case_insensitive(self):
        self.assertEqual(self.ids("EPS"), [101])
        self.assertEqual(self.ids("eps"), [101])

    def test_multi_keyword_and(self):
        self.assertEqual(self.ids("環宇 財測"), [101])
        self.assertEqual(self.ids("環宇 緯穎"), [])

    def test_number_only_in_transcription(self):
        r = self.s.search_articles("98765")
        self.assertEqual([x["article_id"] for x in r], [104])
        self.assertEqual(r[0]["source"], "表格轉寫")
        self.assertIn("98765", r[0]["snippet"])

    def test_snippet_from_body_with_source_and_length(self):
        r = self.s.search_articles("財測")[0]
        self.assertEqual(r["source"], "內文")
        self.assertIn("財測", r["snippet"])
        self.assertLessEqual(len(r["snippet"]), 2 + 120 + 2)
        self.assertEqual(r["url"], F.URL % 101)

    def test_title_only_hit(self):
        r = self.s.search_articles("圖表文章")[0]
        self.assertEqual(r["source"], "標題")

    def test_no_result(self):
        self.assertEqual(self.ids("不存在的詞彙"), [])

    def test_like_special_chars_escaped(self):
        self.assertEqual(self.ids("%"), [104, 103])     # 只比到含字面 % 者（103 內文、104 轉寫），不是全部
        self.assertEqual(self.ids("100%"), [103])
        self.assertEqual(self.ids("_"), [103])
        self.assertEqual(self.ids("a_b"), [103])
        self.assertEqual(self.ids("\\"), [])

    def test_order_newest_first_and_limit(self):
        self.assertEqual(self.ids("。"), [104, 102, 101, 103])
        self.assertEqual(self.ids("。", limit=2), [104, 102])
        self.assertEqual(len(self.ids("。", limit=999)), 4)    # 上限 30 內
        self.assertEqual(len(self.ids("。", limit=0)), 1)      # 下限 1

    def test_empty_query_rejected(self):
        with self.assertRaises(ValueError):
            self.s.search_articles("   ")


class GetArticleTest(SearchBase):
    def test_get_with_images(self):
        a = self.s.get_article(104)
        self.assertEqual(a["url"], F.URL % 104)
        self.assertEqual([i["seq"] for i in a["images"]], [1, 2])
        self.assertIn("本文主要內容", a["body"])

    def test_missing_and_non_fetched_are_errors(self):
        with self.assertRaises(ValueError):
            self.s.get_article(999)
        with self.assertRaises(ValueError) as cm:
            self.s.get_article(105)
        self.assertIn("discovered", str(cm.exception))
        with self.assertRaises(ValueError):
            self.s.get_article("abc")


class ReadOnlyTest(unittest.TestCase):
    def test_missing_db_errors_without_creating(self):
        tmp = tempfile.mkdtemp(prefix="article-ro-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with self.assertRaises(FileNotFoundError):
            A.ArticleStore.open_readonly(tmp)
        self.assertEqual(os.listdir(tmp), [])

    def test_connection_cannot_write(self):
        tmp = tempfile.mkdtemp(prefix="article-ro-")
        self.addCleanup(shutil.rmtree, tmp, True)
        F.build(tmp)
        s = A.ArticleStore.open_readonly(tmp)
        self.addCleanup(s.close)
        with self.assertRaises(sqlite3.OperationalError):
            s.conn.execute("UPDATE article SET title='x'")


if __name__ == "__main__":
    unittest.main()
