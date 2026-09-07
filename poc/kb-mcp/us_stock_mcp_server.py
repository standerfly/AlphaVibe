"""美股獨立投資系統 MCP server（stdio）。

比照既有 `poc/kb-mcp/server.py` 的 server 註冊樣板（純標準庫實作 MCP
stdio transport，每行一個 JSON-RPC 訊息；本機只有 Python 3.9，官方 MCP
SDK 需 3.10+，故不引依賴），但**完全獨立**：不 import `server.py`／
`server_readonly.py`，也不共用其 `TOOLS`／`Server` 定義。內部只呼叫
`USStockStore`（`us_stock_store.py`）與 `us_trade_text_parser.py`，不
import `kb_store.py` 或任何既有台股工具的程式碼（`research.md` §2 查詢
管道獨立決策，`contracts/mcp-tools.md` 檔頭聲明）。

**Phase 3（US1）已實作 4 個工具**——`parse_and_save_us_trade`／
`get_us_holdings`／`get_us_trade_ledger`／`get_us_price_history`（對應
`specs/003-us-stocks/contracts/mcp-tools.md` 工具一/二/三/八）。其餘 5 個
（`save_us_stance`／`get_us_stance`／`save_us_watch_condition`／
`get_us_watch_conditions`／`get_us_watchlist`）留待 Phase 4/5（US2/US3）
逐一補上——`get_us_watchlist`（工具九，四表聯集彙整含立場/監控狀態）也
不在 Phase 3 範圍內：Phase 3 landing 頁的「現價/漲跌」需求改由
`app/routers/us_stocks.py` 直接組合 `USStockStore` 既有方法完成，避免
提前實作出還用不到立場/監控欄位的半成品工具。

**這次也不整合進正式 MCP 啟動流程**——不會被 `server.py`／
`server_readonly.py`／任何 launchd/ngrok 常駐設定引用，純粹是可以獨立
執行的檔案，供之後接上其餘工具、要正式對外開放時再串接。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import us_trade_text_parser  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# Phase 3（US1）4 個工具，對應 contracts/mcp-tools.md 工具一/二/三/八。
# 其餘 5 個工具留待 Phase 4/5，見本檔案開頭 docstring。
TOOLS = [
    {
        "name": "parse_and_save_us_trade",
        "description": (
            "解析使用者截圖轉譯出的交易文字（已由 Claude 於對話中確認"
            "無誤），寫入 us_trades 表。不接受圖片參數——辨識步驟在呼叫"
            "這個工具之前，由 Claude 讀圖轉文字完成。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "已由使用者確認過的交易明細文字，格式：每行一筆，"
                        "'{日期 YYYY-MM-DD} {代號} {買進|賣出} {股數}股"
                        " ${價格}'，例：2026-08-05 NET 買進 10股 $298.40"
                        "（完整格式規則見 us_trade_text_parser.py 檔頭）。"
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_us_holdings",
        "description": "依 us_trades 彙總計算目前持股（簡單加權平均成本，MVP不含FIFO精算）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "省略＝回傳全部曾有交易的股票"},
            },
        },
    },
    {
        "name": "get_us_trade_ledger",
        "description": "取得原始交易列表（供股價圖疊加買賣點位）。",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_us_price_history",
        "description": "取得股價走勢圖資料，並標示資料缺口日期。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "description": "預設90"},
            },
            "required": ["ticker"],
        },
    },
]


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

    # ---- 工具實作（Phase 3/US1 已完成4個，其餘見本檔案開頭 docstring） ----

    def call_tool(self, name, args):
        if name == "parse_and_save_us_trade":
            text = args.get("text")
            if not text:
                raise ValueError("parse_and_save_us_trade 需要 text 參數")
            return us_trade_text_parser.parse_and_save_us_trade_text(
                text, self.store)
        if name == "get_us_holdings":
            return self.store.compute_holdings(args.get("ticker"))
        if name == "get_us_trade_ledger":
            ticker = args.get("ticker")
            if not ticker:
                raise ValueError("get_us_trade_ledger 需要 ticker 參數")
            return {"ticker": ticker, "entries": self.store.list_trades(ticker)}
        if name == "get_us_price_history":
            ticker = args.get("ticker")
            if not ticker:
                raise ValueError("get_us_price_history 需要 ticker 參數")
            days = args.get("days") or 90
            return self.store.price_history_with_gaps(ticker, days)
        raise ValueError("未知或尚未實作的工具：%s" % name)

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
