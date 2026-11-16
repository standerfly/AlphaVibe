"""T030：台股／美股連接器對同一個 articles.db 輸出逐字相同，且兩邊都只讀。"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _article_fixture as F  # noqa: E402
import server  # noqa: E402
import server_readonly  # noqa: E402
import us_stock_mcp_server  # noqa: E402

WRITE_PREFIXES = ("save_", "parse_and_save", "record_", "refresh_", "run_")


class ParityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="article-parity-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        F.build(self.tmp)
        self.tw = server.Server(data_dir=self.tmp)
        self.us = us_stock_mcp_server.Server(data_dir=self.tmp)
        self.addCleanup(self.tw.store.close)
        self.addCleanup(self.us.store.conn.close)

    def test_identical_output(self):
        cases = [("search_articles", {"query": "環宇"}),
                 ("search_articles", {"query": "EPS"}),
                 ("search_articles", {"query": "環宇 財測"}),
                 ("search_articles", {"query": "98765"}),
                 ("search_articles", {"query": "查無此詞"}),
                 ("get_article", {"article_id": 104}),
                 ("get_article", {"article_id": 101})]
        for name, args in cases:
            a = self.tw.call_tool(name, dict(args))
            b = self.us.call_tool(name, dict(args))
            self.assertEqual(a, b, (name, args))
            self.assertTrue(a)

    def test_identical_errors(self):
        for name, args in (("get_article", {"article_id": 999}), ("get_article", {"article_id": 105})):
            with self.assertRaises(ValueError) as e1:
                self.tw.call_tool(name, args)
            with self.assertRaises(ValueError) as e2:
                self.us.call_tool(name, args)
            self.assertEqual(str(e1.exception), str(e2.exception))

    def test_jsonrpc_text_identical(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "search_articles", "arguments": {"query": "環宇"}}}
        self.assertEqual(self.tw.handle(msg)["result"], self.us.handle(msg)["result"])

    def test_no_article_write_tools_and_db_untouched(self):
        for mod in (server.TOOLS, us_stock_mcp_server.TOOLS):
            names = [t["name"] for t in mod if "article" in t["name"]]
            self.assertEqual(sorted(names), ["get_article", "search_articles"])
            for n in names:
                self.assertFalse(n.startswith(WRITE_PREFIXES))
        self.assertTrue({"search_articles", "get_article"} <= server_readonly.READONLY_TOOLS)
        path = os.path.join(self.tmp, "articles.db")

        def digest():
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        before = digest()
        self.tw.call_tool("search_articles", {"query": "環宇"})
        self.us.call_tool("get_article", {"article_id": 104})
        after = digest()
        self.assertEqual(before, after)

    def test_missing_articles_db_errors_without_creating(self):
        empty = tempfile.mkdtemp(prefix="article-parity-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        us = us_stock_mcp_server.Server(data_dir=empty)
        self.addCleanup(us.store.conn.close)
        with self.assertRaises(FileNotFoundError):
            us.call_tool("search_articles", {"query": "x"})
        self.assertFalse(os.path.exists(os.path.join(empty, "articles.db")))
        self.assertFalse(os.path.exists(os.path.join(empty, "alphavibe.db")))


if __name__ == "__main__":
    unittest.main()
