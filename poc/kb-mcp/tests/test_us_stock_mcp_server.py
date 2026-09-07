"""`us_stock_mcp_server.py` 測試（Phase 3 US1，T014/T015）：TOOLS 註冊、
`Server.call_tool` dispatch、JSON-RPC `handle()` 串接。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_stock_mcp_server  # noqa: E402


class ToolsListTest(unittest.TestCase):
    def test_four_phase3_tools_registered(self):
        names = {t["name"] for t in us_stock_mcp_server.TOOLS}
        self.assertEqual(names, {
            "parse_and_save_us_trade", "get_us_holdings",
            "get_us_trade_ledger", "get_us_price_history",
        })

    def test_each_tool_has_input_schema(self):
        for tool in us_stock_mcp_server.TOOLS:
            self.assertIn("inputSchema", tool)
            self.assertIn("description", tool)


class ServerCallToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-mcp-test-")
        self.srv = us_stock_mcp_server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        shutil.rmtree(self.tmp)

    def test_parse_and_save_us_trade_writes_to_store(self):
        out = self.srv.call_tool(
            "parse_and_save_us_trade",
            {"text": "2026-08-05 NET 買進 10股 $298.40\n"})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["saved_count"], 1)
        self.assertEqual(len(self.srv.store.list_trades("NET")), 1)

    def test_parse_and_save_us_trade_missing_text_raises(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("parse_and_save_us_trade", {})

    def test_get_us_holdings_single_ticker(self):
        self.srv.store.save_trade(ticker="NET", trade_date="2026-08-05",
                                   action="buy", shares=10, price=300.0)
        out = self.srv.call_tool("get_us_holdings", {"ticker": "NET"})
        self.assertEqual(out["shares_held"], 10)
        self.assertEqual(out["avg_cost"], 300.0)

    def test_get_us_holdings_all_tickers(self):
        self.srv.store.save_trade(ticker="NET", trade_date="2026-08-05",
                                   action="buy", shares=10, price=300.0)
        out = self.srv.call_tool("get_us_holdings", {})
        self.assertIn("holdings", out)

    def test_get_us_trade_ledger_requires_ticker(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("get_us_trade_ledger", {})

    def test_get_us_trade_ledger_returns_entries(self):
        self.srv.store.save_trade(ticker="NET", trade_date="2026-08-05",
                                   action="buy", shares=10, price=300.0)
        out = self.srv.call_tool("get_us_trade_ledger", {"ticker": "NET"})
        self.assertEqual(out["ticker"], "NET")
        self.assertEqual(len(out["entries"]), 1)

    def test_get_us_price_history_requires_ticker(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("get_us_price_history", {})

    def test_get_us_price_history_default_days(self):
        self.srv.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-06", close_price=286.96)
        out = self.srv.call_tool("get_us_price_history", {"ticker": "NET"})
        self.assertEqual(out["days"], 90)
        self.assertEqual(len(out["history"]), 1)

    def test_get_us_price_history_custom_days(self):
        out = self.srv.call_tool(
            "get_us_price_history", {"ticker": "NET", "days": 30})
        self.assertEqual(out["days"], 30)

    def test_unknown_tool_raises(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("no_such_tool", {})


class JsonRpcHandleTest(unittest.TestCase):
    """`handle()` 串接：tools/call 走完整 JSON-RPC 路徑（見 server.py
    既有樣板），確認 dispatch 沒有繞過這一層。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-mcp-test-")
        self.srv = us_stock_mcp_server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        shutil.rmtree(self.tmp)

    def test_tools_list_via_jsonrpc(self):
        resp = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("parse_and_save_us_trade", names)

    def test_tools_call_via_jsonrpc(self):
        resp = self.srv.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "parse_and_save_us_trade",
                "arguments": {"text": "2026-08-05 NET 買進 10股 $298.40\n"},
            },
        })
        self.assertFalse(resp["result"]["isError"])
        self.assertEqual(len(self.srv.store.list_trades("NET")), 1)

    def test_tools_call_error_surfaces_as_is_error(self):
        resp = self.srv.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_us_trade_ledger", "arguments": {}},
        })
        self.assertTrue(resp["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
