"""T021 接線與守門：唯讀端／美股端只有 2 個查詢工具、寫入 5 個不外露；
channel 傳遞；正式庫保護經 tools/call 路徑生效；工具數守門。"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import external_content_tools as T  # noqa: E402
import external_content_store as store_mod  # noqa: E402
import server  # noqa: E402
import server_readonly  # noqa: E402
import us_stock_mcp_server  # noqa: E402
import mcp_http_gateway  # noqa: E402

YT = "https://www.youtube.com/watch?v=abcdefghijk"
IMPORT_ARGS = {"source_type": "youtube", "url": YT, "title": "接線測試影片", "author": "測試者",
               "date": "2026-01-02", "body": "這是接線測試獨特關鍵字蘋果香蕉的內文"}


def _call(srv, name, args=None, msg_id=1):
    return srv.handle({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                       "params": {"name": name, "arguments": args or {}}})["result"]


class _TmpMixin(object):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ReadonlyWhitelistTest(_TmpMixin, unittest.TestCase):
    def setUp(self):
        _TmpMixin.setUp(self)
        self.srv = server_readonly.ReadonlyServer(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        _TmpMixin.tearDown(self)

    def test_tools_list_has_only_query_tools(self):
        resp = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        ext = names & set(T.TOOL_NAMES)
        self.assertEqual(ext, {"search_external_content", "get_external_content"})

    def test_write_tools_rejected(self):
        for n in T.WRITE_TOOL_NAMES:
            r = _call(self.srv, n, {})
            self.assertTrue(r["isError"], n)
            self.assertIn("沒有授權呼叫寫入工具", r["content"][0]["text"])

    def test_tool_names_avoid_reserved_words(self):
        for n in T.TOOL_NAMES:
            for bad in ("article", "verif", "reviewed"):
                self.assertNotIn(bad, n.lower())

    def test_gate_numbers(self):
        self.assertEqual(len(server.TOOLS), 57)
        self.assertEqual(len(server_readonly.READONLY_TOOLS), 33)
        self.assertEqual(len(us_stock_mcp_server.TOOLS), 12)
        self.assertFalse(set(T.WRITE_TOOL_NAMES) & server_readonly.READONLY_TOOLS)


class UsStockWiringTest(_TmpMixin, unittest.TestCase):
    def test_us_tools_list_only_query_tools(self):
        names = {t["name"] for t in us_stock_mcp_server.TOOLS}
        self.assertEqual(names & set(T.TOOL_NAMES), set(T.QUERY_TOOL_NAMES))
        for n in T.WRITE_TOOL_NAMES:
            self.assertNotIn(n, names)

    def test_us_write_tools_are_unknown(self):
        srv = us_stock_mcp_server.Server(data_dir=self.tmp)
        try:
            for n in T.WRITE_TOOL_NAMES:
                r = _call(srv, n, {})
                self.assertTrue(r["isError"], n)
        finally:
            srv.store.close()

    def test_same_content_found_via_both_servers(self):
        st = store_mod.ExternalContentStore(self.tmp)
        try:
            res = st.add_content("youtube", YT, "接線測試影片", "測試者", "2026-01-02",
                                 IMPORT_ARGS["body"])
            self.assertEqual(res["status"], "imported")
        finally:
            st.conn.close()
        kb = server.Server(data_dir=self.tmp)
        us = us_stock_mcp_server.Server(data_dir=self.tmp)
        try:
            a = kb.call_tool("search_external_content", {"query": "蘋果香蕉"})
            b = us.call_tool("search_external_content", {"query": "蘋果香蕉"})
        finally:
            kb.store.close()
            us.store.close()
        self.assertIn("接線測試影片", a)
        self.assertIn("接線測試影片", b)
        self.assertEqual(a, b)


class KbServerRoutingTest(_TmpMixin, unittest.TestCase):
    def test_default_channel_and_error_flag(self):
        srv = server.Server(data_dir=self.tmp)
        try:
            self.assertEqual(srv.channel, "stdio")
            ok = _call(srv, "search_external_content", {"query": "不存在的字"})
            self.assertFalse(ok["isError"])
            bad = _call(srv, "get_external_content", {})
            self.assertTrue(bad["isError"])
        finally:
            srv.store.close()

    def test_write_to_production_dir_blocked_via_tools_call(self):
        srv = server.Server(data_dir=self.tmp)
        try:
            with unittest.mock.patch.object(T, "_production_data_dir",
                                            return_value=os.path.realpath(self.tmp)), \
                    unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
                r = _call(srv, "import_text", dict(IMPORT_ARGS))
            self.assertTrue(r["isError"])
            self.assertIn("寫入被拒絕", r["content"][0]["text"])
        finally:
            srv.store.close()

    def test_import_text_success_path_not_error(self):
        srv = server.Server(data_dir=self.tmp)
        try:
            r = _call(srv, "import_text", dict(IMPORT_ARGS))
            self.assertFalse(r["isError"], r["content"][0]["text"])
        finally:
            srv.store.close()


class GatewayChannelTest(_TmpMixin, unittest.TestCase):
    def test_gateway_creates_http_channel_server(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "import_text",
                                      "arguments": dict(IMPORT_ARGS)}}).encode("utf-8")
        env = {"ALPHAVIBE_MCP_TOKEN": ""}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)
            os.environ.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
            status, _, out = mcp_http_gateway.handle_mcp_post(
                {"MCP-Protocol-Version": "2025-06-18"}, body, data_dir=self.tmp)
        self.assertEqual(status, 200)
        result = json.loads(out.decode("utf-8"))["result"]
        self.assertFalse(result["isError"], result["content"][0]["text"])
        conn = sqlite3.connect(os.path.join(self.tmp, store_mod.DB_FILENAME))
        try:
            chans = [r[0] for r in conn.execute("SELECT channel FROM audit_log")]
        finally:
            conn.close()
        self.assertEqual(chans, ["http"])

    def test_gateway_us_module_still_works(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)
            status, _, out = mcp_http_gateway.handle_mcp_post(
                {"MCP-Protocol-Version": "2025-06-18"}, body, data_dir=self.tmp,
                server_module=us_stock_mcp_server)
        self.assertEqual(status, 200)
        names = {t["name"] for t in json.loads(out.decode("utf-8"))["result"]["tools"]}
        self.assertEqual(len(names), 12)


if __name__ == "__main__":
    unittest.main()
