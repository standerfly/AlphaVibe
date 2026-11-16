"""T039：表格轉寫文字的搜尋與輸出整合（FR-016、US3 情境 1～3）。合成資料，不連網路。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _article_fixture as F  # noqa: E402
import article_store as A  # noqa: E402
import article_tools as T  # noqa: E402

TABLE_TEXT = "代號|營收\n9958|7654321 百萬\n6669|毛利率 47.3%"


class TranscriptionSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="article-trans-search-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        s = A.ArticleStore(self.tmp)
        for aid, title in ((201, "有表格圖的文章"), (202, "只有文字的文章"), (203, "圖尚未轉寫的文章")):
            s.upsert_discovered(aid, F.URL % aid, title, list_date="2026-11-10")
            s.mark_fetched(aid, F.body("這篇內文不含任何圖表代號"), published_at="2026-11-10T08:00:00+08:00")
        s.add_image(201, 1, "https://img.example/201-1.png")
        s.set_transcription(201, 1, "done", text=TABLE_TEXT, model="m", is_table=True)
        s.add_image(203, 1, "https://img.example/203-1.png")
        s.set_transcription(203, 1, "untranscribed")
        s.close()
        self.s = A.ArticleStore.open_readonly(self.tmp)
        self.addCleanup(self.s.close)

    def test_code_only_in_table_transcription_finds_article_and_labels_source(self):
        for kw in ("9958", "7654321", "47.3%"):
            hits = self.s.search_articles(kw)
            self.assertEqual([h["article_id"] for h in hits], [201], kw)
            self.assertEqual(hits[0]["source"], "表格轉寫")
            self.assertIn(kw, hits[0]["snippet"])
        out = T.search_articles_text(self.s, "9958")
        self.assertIn("表格轉寫", out)
        self.assertIn(F.URL % 201, out)

    def test_untranscribed_image_text_is_not_searchable(self):
        self.assertEqual(self.s.search_articles("9958 203"), [])

    def test_get_article_marks_machine_transcription_and_gives_original_image_url(self):
        out = T.get_article_text(self.s, 201)
        self.assertIn(T.TRANSCRIPTION_WARNING, out)
        self.assertIn("機器轉寫", out)
        self.assertIn("https://img.example/201-1.png", out)
        self.assertIn("9958|7654321 百萬", out)

    def test_untranscribed_image_says_not_transcribed(self):
        out = T.get_article_text(self.s, 203)
        self.assertIn("未轉寫", out)
        self.assertNotIn(T.TRANSCRIPTION_WARNING, out)
        self.assertIn("https://img.example/203-1.png", out)

    def test_db_transcription_column_has_no_label_so_like_search_is_not_polluted(self):
        n = self.s.conn.execute(
            "SELECT COUNT(*) FROM article_image WHERE transcription LIKE '%機器轉寫%' OR transcription LIKE '%可能有誤%'"
        ).fetchone()[0]
        self.assertEqual(n, 0)
        self.assertEqual(self.s.search_articles("機器轉寫"), [])         # 標示字樣不會命中任何文章


if __name__ == "__main__":
    unittest.main()
