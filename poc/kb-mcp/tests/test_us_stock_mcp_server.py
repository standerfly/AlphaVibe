"""`us_stock_mcp_server.py` 測試（Phase 3 US1 T014/T015 ＋ Phase 4 US2
T021 ＋ Phase 5 US3 T026）：TOOLS 註冊、`Server.call_tool` dispatch、
JSON-RPC `handle()` 串接。

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
    def test_eight_phase3_phase4_phase5_tools_registered(self):
        names = {t["name"] for t in us_stock_mcp_server.TOOLS}
        self.assertEqual(names, {
            "parse_and_save_us_trade", "get_us_holdings",
            "get_us_trade_ledger", "get_us_price_history",
            "save_us_stance", "get_us_stance",
            "save_us_watch_condition", "get_us_watch_conditions",
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

    # ---- Phase 4 US2（T021）：save_us_stance／get_us_stance ----

    def test_save_us_stance_writes_to_store(self):
        out = self.srv.call_tool("save_us_stance", {
            "ticker": "NET", "direction": "bullish",
            "summary": "偏多．等回檔", "full_note": "# 標題\n\n完整內容",
            "bear_price": 200, "bull_price": 330,
        })
        self.assertEqual(out["ticker"], "NET")
        self.assertEqual(out["direction"], "bullish")
        self.assertEqual(out["full_note"], "# 標題\n\n完整內容")
        self.assertEqual(len(self.srv.store.list_stances("NET")), 1)

    def test_save_us_stance_missing_required_field_raises(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("save_us_stance", {
                "ticker": "NET", "direction": "bullish", "summary": "偏多",
                # 缺 full_note
            })

    def test_get_us_stance_requires_ticker(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("get_us_stance", {})

    def test_get_us_stance_default_returns_latest_active_only(self):
        self.srv.store.save_stance(ticker="NET", direction="bullish",
                                    summary="偏多", full_note="筆記一")
        out = self.srv.call_tool("get_us_stance", {"ticker": "NET"})
        self.assertEqual(out["ticker"], "NET")
        self.assertIn("stance", out)
        self.assertNotIn("stances", out)
        self.assertEqual(out["stance"]["summary"], "偏多")

    def test_get_us_stance_no_stance_returns_none(self):
        out = self.srv.call_tool("get_us_stance", {"ticker": "NOPE"})
        self.assertIsNone(out["stance"])

    def test_get_us_stance_include_closed_returns_full_history_list(self):
        self.srv.store.save_stance(ticker="NET", direction="bullish",
                                    summary="舊立場", full_note="筆記一",
                                    status="closed")
        self.srv.store.save_stance(ticker="NET", direction="bearish",
                                    summary="新立場", full_note="筆記二")
        out = self.srv.call_tool(
            "get_us_stance", {"ticker": "NET", "include_closed": True})
        self.assertIn("stances", out)
        self.assertNotIn("stance", out)
        self.assertEqual(len(out["stances"]), 2)

    def test_get_us_stance_full_note_not_truncated(self):
        """FR-009：完整研究筆記（多段落）經 MCP 工具存取來回，長度與
        逐字內容都必須完整無截斷。"""
        long_note = "第一段內容。\n\n第二段內容，測試多段落。\n\n" * 20
        self.srv.call_tool("save_us_stance", {
            "ticker": "NET", "direction": "neutral", "summary": "觀望",
            "full_note": long_note,
        })
        out = self.srv.call_tool("get_us_stance", {"ticker": "NET"})
        self.assertEqual(out["stance"]["full_note"], long_note)
        self.assertEqual(len(out["stance"]["full_note"]), len(long_note))

    # ---- Phase 5 US3（T026）：save_us_watch_condition／get_us_watch_conditions ----

    def test_save_us_watch_condition_writes_to_store(self):
        out = self.srv.call_tool("save_us_watch_condition", {
            "ticker": "NET", "metric_type": "price", "comparator": "lt",
            "threshold": 250,
        })
        self.assertEqual(out["ticker"], "NET")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIsNone(out["last_evaluated_at"])
        self.assertEqual(len(self.srv.store.list_watch_conditions("NET")), 1)

    def test_save_us_watch_condition_missing_required_field_raises(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("save_us_watch_condition", {
                "ticker": "NET", "metric_type": "price", "comparator": "lt",
                # 缺 threshold
            })

    def test_save_us_watch_condition_invalid_comparator_raises(self):
        with self.assertRaises(ValueError):
            self.srv.call_tool("save_us_watch_condition", {
                "ticker": "NET", "metric_type": "price", "comparator": "eq",
                "threshold": 250,
            })

    def test_get_us_watch_conditions_single_ticker_includes_is_stale(self):
        self.srv.store.save_watch_condition(
            ticker="NET", metric_type="price", comparator="lt", threshold=250)
        out = self.srv.call_tool("get_us_watch_conditions", {"ticker": "NET"})
        self.assertEqual(len(out["conditions"]), 1)
        self.assertIn("is_stale", out["conditions"][0])
        # 從未評估過：is_stale 必須是 False（見 us_stock_store.py 對應規則）。
        self.assertFalse(out["conditions"][0]["is_stale"])

    def test_get_us_watch_conditions_omitted_ticker_returns_all(self):
        self.srv.store.save_watch_condition(
            ticker="NET", metric_type="price", comparator="lt", threshold=250)
        self.srv.store.save_watch_condition(
            ticker="CRWD", metric_type="price", comparator="gt", threshold=400)
        out = self.srv.call_tool("get_us_watch_conditions", {})
        self.assertEqual(len(out["conditions"]), 2)


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

    def test_save_and_get_us_stance_via_jsonrpc(self):
        save_resp = self.srv.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {
                "name": "save_us_stance",
                "arguments": {
                    "ticker": "NET", "direction": "bullish",
                    "summary": "偏多．等回檔", "full_note": "完整研究筆記內容",
                },
            },
        })
        self.assertFalse(save_resp["result"]["isError"])
        get_resp = self.srv.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "get_us_stance", "arguments": {"ticker": "NET"}},
        })
        self.assertFalse(get_resp["result"]["isError"])
        self.assertIn("完整研究筆記內容", get_resp["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
