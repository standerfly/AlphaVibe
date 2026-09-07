"""美股獨立投資系統 MCP server（stdio）骨架。

比照既有 `poc/kb-mcp/server.py` 的 server 註冊樣板（純標準庫實作 MCP
stdio transport，每行一個 JSON-RPC 訊息；本機只有 Python 3.9，官方 MCP
SDK 需 3.10+，故不引依賴），但**完全獨立**：不 import `server.py`／
`server_readonly.py`，也不共用其 `TOOLS`／`Server` 定義。內部只呼叫
`USStockStore`（`us_stock_store.py`），不 import `kb_store.py` 或任何
既有台股工具的程式碼（`research.md` §2 查詢管道獨立決策，
`contracts/mcp-tools.md` 檔頭聲明）。

**這一步只建立 server 註冊樣板，尚無任何工具實作**——9 個工具
（`parse_and_save_us_trade`／`get_us_holdings`／`get_us_trade_ledger`／
`save_us_stance`／`get_us_stance`／`save_us_watch_condition`／
`get_us_watch_conditions`／`get_us_price_history`／`get_us_watchlist`，
完整規格見 `specs/003-us-stocks/contracts/mcp-tools.md`）留待 Phase 3-5
（US1/US2/US3）逐一實作，`TOOLS` 目前故意是空清單。

**這次也不整合進正式 MCP 啟動流程**——不會被 `server.py`／
`server_readonly.py`／任何 launchd/ngrok 常駐設定引用，純粹是可以獨立
執行、驗證 JSON-RPC 骨架能動的檔案，供之後接上真正工具時使用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us_stock_store import USStockStore  # noqa: E402

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# 9 個工具的完整 inputSchema／實作留待 Phase 3-5（見本檔案開頭
# docstring），這裡刻意維持空清單——tools/list 目前會回傳「尚無工具」。
TOOLS = []


def _default_data_dir():
    """比照 `server.py::_default_data_dir()` 的既有慣例：環境變數
    `ALPHAVIBE_DATA_DIR`（跟既有台股 MCP server 共用同一個「資料目錄在
    哪」的環境變數，兩者 db 檔案同住 `poc/data/` 但檔名不同，不影響
    FR-015/016 的程式碼/資料表獨立要求），未設定則預設
    `<本檔案>/../data`。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


class Server:
    def __init__(self, data_dir=None):
        self.data_dir = os.path.abspath(data_dir or _default_data_dir())
        self.store = USStockStore(self.data_dir)

    # ---- 工具實作（Phase 3-5 逐一補上，目前無任何工具可呼叫） ----

    def call_tool(self, name, args):
        raise ValueError("未知或尚未實作的工具：%s（TOOLS 目前是空清單，"
                          "見本檔案開頭 docstring）" % name)

    # ---- JSON-RPC 處理（比照 server.py::Server.handle 的既有樣板） ----

    def handle(self, msg):
        """處理一則訊息；回傳 response dict 或 None（notification）。"""
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
            version = (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                       else DEFAULT_PROTOCOL_VERSION)
            return self._result(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "alphavibe-us-stock", "version": "0.1.0"},
            })
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = self.call_tool(name, args)
                text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                })
            except Exception as exc:
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": "工具執行失敗：%s" % exc}],
                    "isError": True,
                })
        if method and method.startswith("notifications/"):
            return None
        if msg_id is not None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": "Method not found: %s" % method}}
        return None

    @staticmethod
    def _result(msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main():
    server = Server()
    sys.stderr.write("alphavibe-us-stock 啟動（骨架，尚無工具），資料目錄：%s\n"
                      % server.data_dir)
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        response = server.handle(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
