"""T008：文章庫資料目錄守衛（比照 us_stock_deps 的三種情形）。

執行：python3 -m unittest discover -s app/tests -p "test_article_deps*"
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "poc", "kb-mcp")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import article_deps  # noqa: E402


class ResolveDataDirTest(unittest.TestCase):
    def test_unset_env_refuses_without_implicit_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                article_deps._resolve_article_data_dir()
        self.assertIn("ALPHAVIBE_DATA_DIR 未設定", str(cm.exception))

    def test_production_path_requires_explicit_flag(self):
        prod = article_deps._ARTICLE_PRODUCTION_DATA_DIR
        with mock.patch.dict(os.environ, {"ALPHAVIBE_DATA_DIR": prod}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                article_deps._resolve_article_data_dir()
        self.assertIn("ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1", str(cm.exception))
        with mock.patch.dict(os.environ, {"ALPHAVIBE_DATA_DIR": prod,
                                          "ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "1"}, clear=True):
            self.assertEqual(article_deps._resolve_article_data_dir(), prod)
        with mock.patch.dict(os.environ, {"ALPHAVIBE_DATA_DIR": prod,
                                          "ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "yes"}, clear=True):
            with self.assertRaises(RuntimeError):
                article_deps._resolve_article_data_dir()

    def test_separate_test_directory_is_accepted(self):
        tmp = tempfile.mkdtemp(prefix="article-deps-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"ALPHAVIBE_DATA_DIR": tmp}, clear=True):
            self.assertEqual(article_deps._resolve_article_data_dir(), os.path.realpath(tmp))

    def test_dependency_yields_store_and_closes_it(self):
        tmp = tempfile.mkdtemp(prefix="article-deps-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"ALPHAVIBE_DATA_DIR": tmp}, clear=True):
            gen = article_deps.get_article_store()
            store = next(gen)
            self.assertTrue(os.path.exists(os.path.join(tmp, "articles.db")))
            self.assertEqual(store.known_ids(), set())
            with self.assertRaises(StopIteration):
                next(gen)
        import sqlite3
        with self.assertRaises(sqlite3.ProgrammingError):
            store.known_ids()                       # 已關閉

    def test_module_does_not_import_other_markets(self):
        with open(article_deps.__file__, encoding="utf-8") as f:
            src = f.read()
        for forbidden in ("from app.deps", "import app.deps", "us_stock_deps import", "kb_store"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
