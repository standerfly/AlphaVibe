"""MCP 路徑密鑰路由的路由層測試（2026-10-28，code review 後新增）。

直接打 FastAPI 路由（TestClient），不只測底層 handle_mcp_post()——先前
的單元測試直接呼叫 gateway，沒抓到路由把 header 轉成小寫 dict、導致
MCP-Protocol-Version／Origin 檢查在路徑密鑰路由上從未生效的問題。

用法：.venv/bin/python3 -m unittest app.tests.test_mcp_routes
（資料目錄一律是暫存目錄，不碰 poc/data）
"""
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

TOKEN = "route-test-secret"


def _rpc(method, params=None):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}})


class MCPPathTokenRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="alphavibe-mcp-routes-test-")
        cls.env = unittest.mock.patch.dict(os.environ, {
            "ALPHAVIBE_DATA_DIR": cls.tmp,
            "ALPHAVIBE_MCP_TOKEN": TOKEN,
            "ALPHAVIBE_DASHBOARD_TOKEN": "dash-secret",
        })
        cls.env.start()
        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp)

    def _tools(self, path):
        r = self.client.post(path, content=_rpc("tools/list"))
        self.assertEqual(r.status_code, 200, r.text)
        return {t["name"] for t in r.json()["result"]["tools"]}

    def test_us_route_serves_only_us_tools(self):
        names = self._tools("/mcp/us/" + TOKEN)
        self.assertIn("get_us_holdings", names)
        self.assertNotIn("get_holdings", names)

    def test_tw_route_serves_tw_tools(self):
        names = self._tools("/mcp/" + TOKEN)
        self.assertIn("get_today_highlights", names)
        self.assertNotIn("get_us_holdings", names)

    def test_wrong_token_is_generic_404(self):
        for path in ("/mcp/us/wrong", "/mcp/wrong"):
            r = self.client.post(path, content=_rpc("tools/list"))
            self.assertEqual(r.status_code, 404, path)

    def test_non_ascii_token_is_404_not_500(self):
        for path in ("/mcp/us/%E5%AF%86", "/mcp/%E5%AF%86"):
            r = self.client.post(path, content=_rpc("tools/list"))
            self.assertEqual(r.status_code, 404, path)

    def test_protocol_version_checked_on_path_token_routes(self):
        for path in ("/mcp/us/" + TOKEN, "/mcp/" + TOKEN):
            r = self.client.post(path, content=_rpc("tools/list"),
                                 headers={"MCP-Protocol-Version": "1999-01-01"})
            self.assertEqual(r.status_code, 400, path)

    def test_us_route_writes_us_db_only(self):
        r = self.client.post("/mcp/us/" + TOKEN, content=_rpc(
            "tools/call", {"name": "get_us_holdings", "arguments": {}}))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "us_stocks.db")))

    def test_get_returns_405_with_token_404_without(self):
        for path in ("/mcp/us/" + TOKEN, "/mcp/" + TOKEN):
            self.assertEqual(self.client.get(path).status_code, 405, path)
        for path in ("/mcp/us/wrong", "/mcp/wrong"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


if __name__ == "__main__":
    unittest.main()
