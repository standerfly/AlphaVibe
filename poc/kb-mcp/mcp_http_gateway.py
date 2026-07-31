"""alphavibe-kb MCP Streamable HTTP 閘道（手機用 Claude App 自訂連接器）。

既有 `server.py` 只有 stdio transport（Claude Code CLI 專用，一行一個
JSON-RPC 訊息）。Claude App 的自訂連接器要用 MCP Streamable HTTP
transport 連——單一端點 `/mcp` 收 POST，body 是一個 JSON-RPC 訊息，
這個場景是無狀態的工具呼叫，直接回 `application/json`（不做 SSE、不做
session 管理）。規格依據：
https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

本檔只負責「HTTP 進、HTTP 出」這層轉接，實際工具邏輯完全重用
`server.Server`（不重寫、不修改既有 stdio transport 的任何行為）。

認證機制（PO 拍板，2026-07-30）：這次不在 MCP 層強制驗證 token，安全性
依賴 devtunnel 本身既有的帳號登入層。但保留彈性：
- 環境變數 `ALPHAVIBE_MCP_TOKEN` 有設定時 → 檢查 `Authorization: Bearer
  <token>`，不符回 401（給 Claude Code CLI `claude mcp add --header`
  這類場景、或 PO 未來想加驗證時用）。
- 沒設定時 → 不做任何驗證檢查，但啟動時印出明顯警告，不是靜默不安全。

純標準庫、Python 3.9 相容、zero 外部依賴（比照 report_server.py 風格，
繁體中文註解）。sqlite 連線不可跨執行緒共用，因此每個請求各自建立一個
`server.Server`（進而各自開一個 KBStore 連線），成本可忽略。

架構（2026-07-30 重構，合併進 report_server.py 共用 8080 埠時的動機：
devtunnel 在 PO 的 VS Code 環境轉發新埠會卡住，直接掛在已成功轉發的
8080 埠上完全繞開這個問題）：核心請求處理邏輯是 `handle_mcp_post()`，
一個不依賴 `BaseHTTPRequestHandler` 的獨立函式（輸入 headers＋原始
body bytes，輸出 `(status, content_type, body_bytes)`），`MCPHandler`
只是薄薄一層外殼，把 HTTP 進出轉接到這個函式。這樣其他 HTTP handler
（如 `report_server.ReportHandler`）也能直接呼叫同一段邏輯，不需要
另外起一個 process／埠。獨立執行的能力（`main()`／CLI／
`ThreadingHTTPServer`）完整保留，未來仍可用 `--port` 另外跑一個獨立埠。

用法：python3 poc/kb-mcp/mcp_http_gateway.py [--port 8081] [--host 127.0.0.1] [--data-dir DIR]
"""
import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as kb_server  # noqa: E402 — 重用既有 Server class（不改動它）

# Origin 白名單掛鉤：留空（falsy）＝這次不限制任何來源（PoC 階段依賴
# devtunnel 帳號驗證），但程式結構上保留檢查點——未來要收緊白名單只需
# 填這個清單，不需要改呼叫端的邏輯。
ALLOWED_ORIGINS = ()


def _configured_token():
    """讀目前生效的 ALPHAVIBE_MCP_TOKEN。每次呼叫都重讀 os.environ（不快取
    成模組常數），測試才能用 os.environ 動態切換兩種模式後照樣生效。"""
    return os.environ.get("ALPHAVIBE_MCP_TOKEN") or None


def warn_if_token_unset():
    """啟動時的安全性警告：未設定 token 時，不是靜默不安全，而是明確印出
    這次是哪種模式在跑。獨立成函式方便測試直接呼叫＋capture stderr 驗證，
    不用整個啟動常駐 server 才能測。"""
    if not _configured_token():
        sys.stderr.write(
            "⚠️  ALPHAVIBE_MCP_TOKEN 未設定，"
            "此端點不做應用層驗證，"
            "安全性完全依賴外層網路"
            "存取控制（如devtunnel帳號驗"
            "證），請確認你知道這個"
            "風險再繼續\n")
        sys.stderr.flush()


def _origin_allowed(origin):
    if not ALLOWED_ORIGINS:
        return True
    return origin in ALLOWED_ORIGINS


def _protocol_version_error(version):
    """有帶 MCP-Protocol-Version header 時檢查是否在支援清單內；沒帶就
    略過不擋（規格是 SHOULD 不是 MUST）。"""
    if version and version not in kb_server.SUPPORTED_PROTOCOL_VERSIONS:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": ("不支援的 MCP-Protocol-Version：%s；支援版本：%s"
                            % (version, ", ".join(kb_server.SUPPORTED_PROTOCOL_VERSIONS))),
            },
        }
    return None


def _auth_ok(headers):
    """認證檢查。`headers` 只要求支援 `.get(key)`（dict 或
    `http.client.HTTPMessage` 皆可，故意不綁定 BaseHTTPRequestHandler）。"""
    token = _configured_token()
    if not token:
        return True  # 未設定 token＝這次選擇不驗證（見模組docstring）
    auth_header = headers.get("Authorization") or ""
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    supplied = auth_header[len(prefix):]
    # 用 compare_digest 做定時比對，避免時序攻擊；不管成敗都不在回應裡
    # 洩漏任何系統資訊（401 body 是固定的通用訊息）。
    return hmac.compare_digest(supplied, token)


def path_token_matches(candidate):
    """URL 路徑密鑰驗證（2026-07-30 新增）。動機：手機 Claude App 的
    「Custom Connectors via Remote MCP」設定 UI 只有 OAuth Client
    ID/Secret 一個驗證選項，沒有自訂 header 欄位可以填 `Authorization:
    Bearer <token>`（該功能仍在 Anthropic 封閉測試中），因此另外開一條
    把密鑰放進 URL 路徑本身的路由（`report_server.py` 的 `/mcp/<token>`）
    給 Claude App 用。

    密鑰來源刻意跟 `_auth_ok()` 共用同一個 `ALPHAVIBE_MCP_TOKEN`（單一
    真相來源，不新增第二個環境變數）。跟 `_auth_ok()` 刻意不同的一點是
    fail-closed：`_auth_ok()` 在未設定 token 時選擇「不驗證」（見模組
    docstring開頭的認證機制說明），但這條新路由是給公開網路呼叫的，未
    設定密鑰時一律回傳 False，沒有「沒設密鑰=不驗證」這種寬鬆預設。
    """
    token = _configured_token()
    if not token:
        return False  # fail closed：未設定密鑰時，路徑型驗證一律不通過
    if not candidate:
        return False  # 空字串一律不算符合，即使密鑰意外設成空字串
    # 用 compare_digest 做定時比對，避免時序攻擊（比照 _auth_ok()）。
    return hmac.compare_digest(candidate, token)


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def mcp_method_not_allowed():
    """/mcp 路徑收到 GET／DELETE 時的共用回應：`(status, content_type,
    body_bytes)`。獨立成函式方便被其他 handler（如 report_server.py）
    直接沿用，不用各自重寫一次 405 文案。"""
    return 405, "text/plain; charset=utf-8", "405：/mcp 僅支援 POST".encode("utf-8")


def handle_mcp_post(headers, body_bytes, data_dir=None):
    """處理一次 `POST /mcp` 請求的完整邏輯（Origin 檢查、
    MCP-Protocol-Version 檢查、token 驗證、JSON-RPC 解析與 dispatch），
    不依賴任何 `http.server` 的 class，方便被其他 HTTP handler
    （如 report_server.py 的 `ReportHandler`）直接呼叫，達成同 process、
    同埠共用。

    參數：
    - headers：dict-like，只用到 `.get(key)`（`self.headers`／一般 dict
      皆可）。
    - body_bytes：原始 request body（bytes，未解析）。
    - data_dir：knowledge base 資料目錄，轉傳給 `kb_server.Server`。

    回傳：`(status_code, content_type, response_body_bytes)`，呼叫端只
    需要用自己既有的送出邏輯（如 `self._send(status, content_type,
    body)`）原樣送出即可。
    """
    # 1) Origin 檢查掛鉤（防 DNS rebinding；清單留空目前不擋任何來源）。
    if not _origin_allowed(headers.get("Origin")):
        return 403, "application/json", _json_bytes({"error": "Origin not allowed"})

    # 2) MCP-Protocol-Version 檢查（有帶才擋）。
    version_error = _protocol_version_error(headers.get("MCP-Protocol-Version"))
    if version_error is not None:
        return 400, "application/json", _json_bytes(version_error)

    # 3) Token 驗證（依環境變數是否設定決定要不要驗）。
    if not _auth_ok(headers):
        return 401, "application/json", _json_bytes(
            {"error": "未授權：缺少或錯誤的 Authorization"})

    # 4) 解析 JSON-RPC 訊息。壞掉的 JSON 不可讓常駐服務掛掉。
    try:
        msg = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except ValueError:
        return 400, "application/json", _json_bytes({
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32700, "message": "Parse error：body 不是合法的 JSON"},
        })

    # 5) 呼叫既有 Server.handle()——單一請求處理失敗（包含非預期例外）
    # 不可讓常駐服務掛掉，比照專案既有的 try/except-per-request 防護風格。
    msg_id = msg.get("id") if isinstance(msg, dict) else None
    server_instance = kb_server.Server(data_dir=data_dir)
    try:
        response = server_instance.handle(msg)
    except Exception as exc:
        return 500, "application/json", _json_bytes({
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32603, "message": "Internal error：%s" % exc},
        })
    finally:
        server_instance.store.close()

    if response is None:
        # notification（無 id 的訊息）：回 202 空 body，不是錯誤。
        return 202, "application/json", b""
    return 200, "application/json", _json_bytes(response)


class MCPHandler(BaseHTTPRequestHandler):
    """獨立可執行外殼：把 HTTP 進出轉接到上面的純函式。保留獨立執行能力
    （見模組docstring），供未來真的需要獨立埠時使用；PO 目前實際跑的是
    合併進 `report_server.py` 的版本，那邊直接呼叫 `handle_mcp_post()`／
    `mcp_method_not_allowed()`，不經過這個 class。"""

    data_dir = None  # 由 main() 設定

    def _send_tuple(self, status, content_type, body):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    # ---- 路由 ----

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/mcp":
            self._send_tuple(*mcp_method_not_allowed())
        else:
            self._send_tuple(404, "text/plain; charset=utf-8",
                             "404：僅支援 POST /mcp".encode("utf-8"))

    def do_DELETE(self):
        if self.path.split("?", 1)[0] == "/mcp":
            self._send_tuple(*mcp_method_not_allowed())
        else:
            self._send_tuple(404, "text/plain; charset=utf-8",
                             "404：僅支援 POST /mcp".encode("utf-8"))

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/mcp":
            self._send_tuple(404, "text/plain; charset=utf-8",
                             "404：僅支援 POST /mcp".encode("utf-8"))
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        status, content_type, body = handle_mcp_post(
            self.headers, raw, data_dir=self.data_dir)
        self._send_tuple(status, content_type, body)

    def log_message(self, fmt, *args):  # 安靜一點，只留到 stderr
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="alphavibe-kb MCP Streamable HTTP 閘道（手機自訂連接器用）")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    MCPHandler.data_dir = os.path.abspath(
        args.data_dir or os.environ.get("ALPHAVIBE_DATA_DIR")
        or os.path.join(here, "..", "data"))

    warn_if_token_unset()

    httpd = ThreadingHTTPServer((args.host, args.port), MCPHandler)
    print("alphavibe-kb MCP HTTP 閘道啟動：http://%s:%d/mcp（資料目錄 %s）"
          % (args.host, httpd.server_address[1], MCPHandler.data_dir))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
