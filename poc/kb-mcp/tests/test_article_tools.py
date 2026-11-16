"""T026：article_tools 輸出格式（原文網址必帶、轉寫標示只在輸出層、未轉寫、唯讀）。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _article_fixture as F  # noqa: E402
import article_store as A  # noqa: E402
import article_tools as T  # noqa: E402


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="article-tools-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.build(self.tmp)
        self.s = A.ArticleStore.open_readonly(self.tmp)
        self.addCleanup(self.s.close)

    def test_search_output_has_all_fields(self):
        out = T.search_articles_text(self.s, "環宇")
        for part in ("環宇產業筆記", "2026-11-10", F.URL % 101, "內文", "article_id=101"):
            self.assertIn(part, out)

    def test_search_no_result_message(self):
        self.assertEqual(T.search_articles_text(self.s, "查無此詞"), "查無符合的文章")

    def test_get_article_images_and_warning_only_for_done(self):
        out = T.get_article_text(self.s, 104)
        self.assertIn(F.URL % 104, out)
        self.assertIn("https://img.example/104-1.png", out)
        self.assertIn("98765", out)
        self.assertEqual(out.count(T.TRANSCRIPTION_WARNING), 1)   # 只有已轉寫那張
        self.assertIn("未轉寫", out)

    def test_warning_not_stored_in_db(self):
        n = self.s.conn.execute(
            "SELECT COUNT(*) FROM article_image WHERE transcription LIKE '%機器轉寫%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_get_article_errors(self):
        with self.assertRaises(ValueError):
            T.get_article_text(self.s, 105)

    def test_entry_missing_db_errors_and_creates_nothing(self):
        empty = tempfile.mkdtemp(prefix="article-tools-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(FileNotFoundError):
            T.call_article_tool(empty, "search_articles", {"query": "x"})
        self.assertEqual(os.listdir(empty), [])

    def test_entry_requires_args(self):
        with self.assertRaises(ValueError):
            T.call_article_tool(self.tmp, "search_articles", {})
        with self.assertRaises(ValueError):
            T.call_article_tool(self.tmp, "get_article", {})


if __name__ == "__main__":
    unittest.main()
