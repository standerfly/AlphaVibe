"""mcp_http_gateway 測試：/mcp 端點的 Streamable HTTP transport 行為
（沒設token時不驗證但要有警告、設token時的驗證/401、GET／DELETE 405、
notification 202、不支援協定版本 400、壞掉的JSON body不讓服務掛掉）。

兩層測試：
1. `MCPHTTPGatewayTest`——比照 test_report_server.py 的 ThreadingHTTPServer
   + 背景執行緒模式，透過真實 HTTP 打 `MCPHandler`，驗證獨立執行的外殼
   （do_GET/do_POST/路由/送出）行為正確。
2. `HandleMcpPostDirectCallTest`（2026-07-30 新增，重構抽出
   `handle_mcp_post()`／`mcp_method_not_allowed()` 後補上）——不起 HTTP
   server，直接呼叫這兩個純函式，證明它們真的不依賴
   `BaseHTTPRequestHandler`，可以被 report_server.py 這類其他 HTTP
   handler 直接沿用（合併進同一個 process／埠時的前提）。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import mcp_http_gateway  # noqa: E402
from kb_store import KBStore  # noqa: E402


class MCPHTTPGatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="alphavibe-mcphttp-test-")
        mcp_http_gateway.MCPHandler.data_dir = cls.tmp
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), mcp_http_gateway.MCPHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def setUp(self):
        # 每個測試前確保沒有殘留的 token 設定（除非測試自己 patch）。
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)

    def _request(self, method, path, body=None, headers=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def _rpc(self, payload, headers=None):
        body = json.dumps(payload)
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(headers or {})
        return self._request("POST", "/mcp", body=body, headers=hdrs)

    # ---- 未設定 token：不驗證，但要有明顯警告 ----

    def test_no_token_mode_warns_on_startup(self):
        self.assertNotIn("ALPHAVIBE_MCP_TOKEN", os.environ)
        captured = io.StringIO()
        with unittest.mock.patch("sys.stderr", captured):
            mcp_http_gateway.warn_if_token_unset()
        warning = captured.getvalue()
        self.assertIn("ALPHAVIBE_MCP_TOKEN", warning)
        self.assertIn("未設定", warning)

    def test_no_token_mode_processes_request_without_auth_header(self):
        self.assertNotIn("ALPHAVIBE_MCP_TOKEN", os.environ)
        status, headers, body = self._rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "list_stances", "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        resp = json.loads(body.decode("utf-8"))
        self.assertEqual(resp["id"], 1)
        self.assertFalse(resp["result"]["isError"])

    # ---- 設定 token：驗證生效 ----

    def test_token_mode_matches_stdio_style_response_and_rejects_bad_auth(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"ALPHAVIBE_MCP_TOKEN": "s3cr3t-token"}):
            # 正確 token：拿到跟 stdio 版一致的 JSON-RPC 回應。
            store = KBStore(self.tmp)
            store.save_stance("2330", "偏多", name="台積電", source_ref="gw-test")
            store.close()
            status, _, body = self._rpc(
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                 "params": {"name": "get_stance", "arguments": {"code": "2330"}}},
                headers={"Authorization": "Bearer s3cr3t-token"})
            self.assertEqual(status, 200)
            resp = json.loads(body.decode("utf-8"))
            inner = json.loads(resp["result"]["content"][0]["text"])
            self.assertTrue(inner["found"])
            self.assertEqual(inner["latest"]["stance"], "偏多")

            # 缺 Authorization header：401，且不洩漏系統資訊。
            status, _, body = self._rpc(
                {"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
            self.assertEqual(status, 401)
            text = body.decode("utf-8")
            self.assertNotIn("Traceback", text)
            self.assertNotIn(self.tmp, text)

            # 錯誤 token：401。
            status, _, body = self._rpc(
                {"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
                headers={"Authorization": "Bearer wrong-token"})
            self.assertEqual(status, 401)

    # ---- GET／DELETE：405 ----

    def test_get_and_delete_return_405(self):
        status, _, _ = self._request("GET", "/mcp")
        self.assertEqual(status, 405)
        status, _, _ = self._request("DELETE", "/mcp")
        self.assertEqual(status, 405)

    def test_unknown_path_returns_404(self):
        status, _, _ = self._request("GET", "/no/such/path")
        self.assertEqual(status, 404)

    # ---- notification（無 id）：202 空 body ----

    def test_notification_returns_202_empty_body(self):
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, 202)
        self.assertEqual(body, b"")

    # ---- 不支援的 MCP-Protocol-Version：400 ----

    def test_unsupported_protocol_version_returns_400(self):
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"MCP-Protocol-Version": "1999-01-01"})
        self.assertEqual(status, 400)
        resp = json.loads(body.decode("utf-8"))
        self.assertIn("1999-01-01", resp["error"]["message"])

    def test_supported_protocol_version_passes(self):
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            headers={"MCP-Protocol-Version": "2025-06-18"})
        self.assertEqual(status, 200)

    # ---- 壞掉的 JSON body：400，且服務不掛掉 ----

    def test_malformed_json_body_returns_400_and_service_survives(self):
        status, _, body = self._request(
            "POST", "/mcp", body=b"{this is not valid json",
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        resp = json.loads(body.decode("utf-8"))
        self.assertEqual(resp["error"]["code"], -32700)

        # 服務仍正常回應下一個請求。
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
        self.assertEqual(status, 200)

    # ---- 完整 initialize → tools/list → tools/call 流程（無 token 模式）----

    def test_full_handshake_via_http(self):
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 100, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}})
        self.assertEqual(status, 200)
        resp = json.loads(body.decode("utf-8"))
        self.assertEqual(resp["result"]["serverInfo"]["name"], "alphavibe-kb")

        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 101, "method": "tools/list"})
        resp = json.loads(body.decode("utf-8"))
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("list_stances", names)


class HandleMcpPostDirectCallTest(unittest.TestCase):
    """直接呼叫抽出後的 `handle_mcp_post()`／`mcp_method_not_allowed()`
    （不透過 HTTP server、不經過 MCPHandler），headers 用一般 dict 即可
    ——這正是 report_server.py 合併呼叫時的用法。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-mcphttp-direct-test-")
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)

    def tearDown(self):
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)
        shutil.rmtree(self.tmp)

    def test_success_call_without_token(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
        status, content_type, resp_body = mcp_http_gateway.handle_mcp_post(
            {}, body, data_dir=self.tmp)
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        resp = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(resp["id"], 1)
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("list_stances", names)

    def test_token_mode_rejects_missing_auth_and_accepts_correct_bearer(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "direct-secret"}):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")

            status, _, _ = mcp_http_gateway.handle_mcp_post({}, body, data_dir=self.tmp)
            self.assertEqual(status, 401)

            status, _, _ = mcp_http_gateway.handle_mcp_post(
                {"Authorization": "Bearer wrong"}, body, data_dir=self.tmp)
            self.assertEqual(status, 401)

            status, _, resp_body = mcp_http_gateway.handle_mcp_post(
                {"Authorization": "Bearer direct-secret"}, body, data_dir=self.tmp)
            self.assertEqual(status, 200)
            resp = json.loads(resp_body.decode("utf-8"))
            self.assertEqual(resp["id"], 1)

    def test_notification_returns_202_empty_body(self):
        body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        status, _, resp_body = mcp_http_gateway.handle_mcp_post({}, body, data_dir=self.tmp)
        self.assertEqual(status, 202)
        self.assertEqual(resp_body, b"")

    def test_unsupported_protocol_version_returns_400(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode("utf-8")
        status, _, resp_body = mcp_http_gateway.handle_mcp_post(
            {"MCP-Protocol-Version": "1999-01-01"}, body, data_dir=self.tmp)
        self.assertEqual(status, 400)
        resp = json.loads(resp_body.decode("utf-8"))
        self.assertIn("1999-01-01", resp["error"]["message"])

    def test_malformed_json_body_returns_400_and_does_not_raise(self):
        status, _, resp_body = mcp_http_gateway.handle_mcp_post(
            {}, b"{this is not valid json", data_dir=self.tmp)
        self.assertEqual(status, 400)
        resp = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(resp["error"]["code"], -32700)

    def test_mcp_method_not_allowed_returns_405(self):
        status, content_type, body = mcp_http_gateway.mcp_method_not_allowed()
        self.assertEqual(status, 405)
        self.assertIn("text/plain", content_type)
        self.assertIn("POST", body.decode("utf-8"))


class PathTokenMatchesTest(unittest.TestCase):
    """path_token_matches()（2026-07-30新增）：URL路徑密鑰驗證，供
    report_server.py 的 `/mcp/<token>` 路由使用（手機 Claude App
    自訂連接器用，該功能標準設定UI沒有自訂header欄位，見函式docstring）。
    跟 `_auth_ok()` 刻意不同的一點是 fail-closed：未設定密鑰時一律False。
    """

    def setUp(self):
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)

    def tearDown(self):
        os.environ.pop("ALPHAVIBE_MCP_TOKEN", None)

    def test_matches_when_token_configured_and_candidate_correct(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "s3cr3t-path"}):
            self.assertTrue(mcp_http_gateway.path_token_matches("s3cr3t-path"))

    def test_rejects_wrong_candidate(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "s3cr3t-path"}):
            self.assertFalse(mcp_http_gateway.path_token_matches("wrong-value"))

    def test_fails_closed_when_token_not_configured(self):
        # 沒設定ALPHAVIBE_MCP_TOKEN時，即使candidate碰巧猜對某個字串，
        # 路徑型驗證仍一律False——跟_auth_ok()「沒設token=不驗證」的
        # 寬鬆預設刻意不同，這條路由是給公開網路呼叫的。
        self.assertNotIn("ALPHAVIBE_MCP_TOKEN", os.environ)
        self.assertFalse(mcp_http_gateway.path_token_matches("anything"))
        self.assertFalse(mcp_http_gateway.path_token_matches(""))

    def test_empty_candidate_never_matches_with_real_token_configured(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "s3cr3t-path"}):
            self.assertFalse(mcp_http_gateway.path_token_matches(""))

    def test_empty_candidate_never_matches_even_if_token_is_empty_string(self):
        # ALPHAVIBE_MCP_TOKEN="" 時 _configured_token() 的 `or None` 會把它
        # 當成未設定，但這裡直接測 candidate="" 本身的行為，不依賴那個轉換。
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": ""}):
            self.assertFalse(mcp_http_gateway.path_token_matches(""))


if __name__ == "__main__":
    unittest.main()
