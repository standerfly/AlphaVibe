"""claude.ai 連接器擴充（2026-10-28）：美股連接器＋「今日重點」MCP 工具。

- 閘道 `handle_mcp_post(server_module=...)` 可以轉接美股 server，且台美
  工具清單互不混用（台美完全獨立是產品硬性要求）。
- `get_today_highlights` 與網頁今日重點共用 `KBStore.get_today_highlights()`：
  只留有建議動作的項目、持有中優先、立場衝突次之、附 type 欄位。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import mcp_http_gateway  # noqa: E402
import server as kb_server  # noqa: E402
import us_stock_mcp_server  # noqa: E402
from kb_store import KBStore  # noqa: E402


def _rpc(method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg).encode("utf-8")


class USConnectorGatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-us-connector-test-")
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _tool_names(self, server_module):
        status, _, body = mcp_http_gateway.handle_mcp_post(
            {}, _rpc("tools/list"), data_dir=self.tmp, server_module=server_module)
        self.assertEqual(status, 200)
        return {t["name"] for t in json.loads(body)["result"]["tools"]}

    def test_us_module_serves_only_us_tools(self):
        names = self._tool_names(us_stock_mcp_server)
        self.assertEqual(names, {t["name"] for t in us_stock_mcp_server.TOOLS})
        self.assertIn("get_us_holdings", names)
        self.assertNotIn("get_holdings", names)  # 不混入台股工具

    def test_default_module_is_still_tw(self):
        names = self._tool_names(None)
        self.assertIn("get_holdings", names)
        self.assertNotIn("get_us_holdings", names)

    def test_us_initialize_reports_us_server(self):
        status, _, body = mcp_http_gateway.handle_mcp_post(
            {}, _rpc("initialize", {"protocolVersion": "2025-06-18"}),
            data_dir=self.tmp, server_module=us_stock_mcp_server)
        self.assertEqual(status, 200)
        info = json.loads(body)["result"]["serverInfo"]
        self.assertEqual(info["name"], "alphavibe-us-stock")

    def test_us_tool_call_writes_us_db_only(self):
        status, _, body = mcp_http_gateway.handle_mcp_post(
            {}, _rpc("tools/call", {"name": "get_us_holdings", "arguments": {}}),
            data_dir=self.tmp, server_module=us_stock_mcp_server)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["result"]["isError"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "us_stocks.db")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "alphavibe.db")))

    def test_protocol_version_checked_against_us_module(self):
        status, _, _ = mcp_http_gateway.handle_mcp_post(
            {"MCP-Protocol-Version": "1999-01-01"}, _rpc("tools/list"),
            data_dir=self.tmp, server_module=us_stock_mcp_server)
        self.assertEqual(status, 400)


class TodayHighlightsTest(unittest.TestCase):
    DATE = "2026-10-28"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-highlights-test-")
        self.store = KBStore(self.tmp)
        self.store.save_holdings([{"code": "2330", "name": "台積電",
                                   "shares": 100, "avg_cost": 500}],
                                 snapshot_date=self.DATE)
        ts = self.DATE + "T17:00:00"
        save = self.store.save_module_d_result
        save("1111", "通用層", "觀察無衝突", suggested_action="減碼", checked_at=ts)
        save("2222", "通用層", "觀察有衝突", suggested_action="減碼",
             conflict_flag=True, checked_at=ts)
        save("2330", "通用層", "持有中", suggested_action="續抱", checked_at=ts)
        save("3333", "通用層", "正常無動作", checked_at=ts)
        save("4444", "通用層", "別天的", suggested_action="減碼",
             checked_at="2026-10-27T17:00:00")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_filter_sort_and_type(self):
        rows = self.store.get_today_highlights(date=self.DATE)
        self.assertEqual([r["code"] for r in rows], ["2330", "2222", "1111"])
        self.assertEqual([r["type"] for r in rows], ["存股", "觀察中", "觀察中"])

    def test_mcp_tool_matches_store(self):
        srv = kb_server.Server(data_dir=self.tmp)
        try:
            out = srv.call_tool("get_today_highlights", {"date": self.DATE})
        finally:
            srv.store.close()
        self.assertEqual(out["date"], self.DATE)
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["highlights"],
                         self.store.get_today_highlights(date=self.DATE))

    def test_tool_is_readonly_whitelisted(self):
        import server_readonly
        self.assertIn("get_today_highlights", server_readonly.READONLY_TOOLS)


if __name__ == "__main__":
    unittest.main()
