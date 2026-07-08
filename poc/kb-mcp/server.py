"""alphavibe-kb — 三層知識庫 MCP server（stdio）。

純標準庫實作 MCP stdio transport（每行一個 JSON-RPC 訊息）：本機只有
Python 3.9，官方 MCP SDK 需 3.10+，故不引依賴。僅實作 tools 能力，
對應 product-spec FR-015~021 與 Q-021 即時確認制（工具核准＝使用者確認）。

資料目錄：環境變數 ALPHAVIBE_DATA_DIR，預設 <本檔案>/../data。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finmind_client  # noqa: E402
from kb_store import KBStore  # noqa: E402

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "save_stance",
        "description": ("將對話中確認的個股立場寫入 Layer 2。若與既有立場不同，"
                        "會拒絕寫入並回傳衝突資訊——請向使用者展示新舊立場，"
                        "經確認要更新才帶 overwrite=true 重呼叫（FR-013/017/018）。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，如 2330"},
                "stance": {"type": "string", "description": "立場：偏多/偏空/中性/觀望…"},
                "name": {"type": "string", "description": "股票名稱"},
                "reason": {"type": "string", "description": "立場理由"},
                "date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
                "entry_condition": {"type": "string", "description": "進場條件，如「跌破 900 分批買」"},
                "valuation_metric": {"type": "string", "description": "估值依據，如「PER 15 以下便宜」"},
                "time_horizon": {"type": "string", "description": "持有期間觀點"},
                "risk_factor": {"type": "string", "description": "風險因子"},
                "source_ref": {"type": "string", "description": "來源引用（對話片段/連結）"},
                "overwrite": {"type": "boolean", "description": "立場衝突時，經使用者確認後設 true"},
            },
            "required": ["code", "stance"],
        },
    },
    {
        "name": "get_stance",
        "description": "查詢個股的最新立場與近期歷史（Layer 2）。",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼"}},
            "required": ["code"],
        },
    },
    {
        "name": "list_stances",
        "description": "列出所有個股的最新立場（Layer 2 總覽，供觀察名單檢視）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_comment",
        "description": "將盤勢/市場評論或資訊摘要存入 Layer 3（FTS5 全文檢索）。經使用者確認後才呼叫。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "body": {"type": "string", "description": "評論內容"},
                "source_tag": {"type": "string", "description": "來源：conversation/line/youtube/web/anchor/gooaye…"},
                "date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
                "symbols": {"type": "string", "description": "相關代碼，空白分隔，如「2330 2454」"},
                "source_ref": {"type": "string", "description": "來源引用"},
            },
            "required": ["body", "source_tag"],
        },
    },
    {
        "name": "search_comments",
        "description": "全文檢索 Layer 3 評論（中文查詢至少 3 個字）。query 留空改用 recent 模式列最近幾筆。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "關鍵字（≥3 字）；留空＝列最近"},
                "limit": {"type": "integer", "description": "筆數上限，預設 10"},
            },
        },
    },
    {
        "name": "save_philosophy",
        "description": "將投資哲學/原則寫入 Layer 1 模組 md 檔（如 module=yuzhiyu）。經使用者確認後才呼叫。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {"type": "string", "description": "模組名，如 yuzhiyu/gooaye/anchor"},
                "content": {"type": "string", "description": "哲學內容（markdown）"},
                "mode": {"type": "string", "enum": ["append", "replace"], "description": "預設 append"},
            },
            "required": ["module", "content"],
        },
    },
    {
        "name": "get_philosophy",
        "description": "讀取 Layer 1 哲學模組；不給 module 則列出全部模組。",
        "inputSchema": {
            "type": "object",
            "properties": {"module": {"type": "string", "description": "模組名；省略＝列清單"}},
        },
    },
    {
        "name": "get_fundamentals",
        "description": "查 FinMind 個股基本面：近期 PER/PBR/殖利率＋近 6 個月營收（FR-019 名單驅動選股用）。",
        "inputSchema": {
            "type": "object",
            "properties": {"stock_id": {"type": "string", "description": "台股代碼，如 2330"}},
            "required": ["stock_id"],
        },
    },
]


def _default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


class Server:
    def __init__(self, data_dir=None):
        self.data_dir = os.path.abspath(data_dir or _default_data_dir())
        self.store = KBStore(self.data_dir)

    # ---- 工具實作 ----

    def call_tool(self, name, args):
        if name == "save_stance":
            return self.store.save_stance(
                code=args["code"], stance=args["stance"],
                name=args.get("name"), reason=args.get("reason"),
                date=args.get("date"),
                entry_condition=args.get("entry_condition"),
                valuation_metric=args.get("valuation_metric"),
                time_horizon=args.get("time_horizon"),
                risk_factor=args.get("risk_factor"),
                source_ref=args.get("source_ref"),
                overwrite=bool(args.get("overwrite")),
            )
        if name == "get_stance":
            latest = self.store.get_latest_stance(args["code"])
            if not latest:
                return {"found": False, "code": args["code"]}
            return {"found": True, "latest": latest,
                    "history": self.store.get_stance_history(args["code"])}
        if name == "list_stances":
            stances = self.store.list_stances()
            return {"count": len(stances), "stances": stances}
        if name == "save_comment":
            return self.store.save_comment(
                body=args["body"], source_tag=args["source_tag"],
                date=args.get("date"), symbols=args.get("symbols"),
                source_ref=args.get("source_ref"),
            )
        if name == "search_comments":
            query = (args.get("query") or "").strip()
            limit = int(args.get("limit") or 10)
            if query:
                return self.store.search_comments(query, limit)
            return self.store.recent_comments(limit)
        if name == "save_philosophy":
            return self.store.save_philosophy(
                module=args["module"], content=args["content"],
                mode=args.get("mode") or "append",
            )
        if name == "get_philosophy":
            module = args.get("module")
            if module:
                return self.store.get_philosophy(module)
            return self.store.list_philosophy()
        if name == "get_fundamentals":
            return finmind_client.get_fundamentals(
                args["stock_id"], data_dir=self.data_dir)
        raise ValueError("未知工具：%s" % name)

    # ---- JSON-RPC 處理 ----

    def handle(self, msg):
        """處理一則訊息；回傳 response dict 或 None（notification）。"""
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
            version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS \
                else DEFAULT_PROTOCOL_VERSION
            return self._result(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "alphavibe-kb", "version": "0.1.0"},
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
    sys.stderr.write("alphavibe-kb 啟動，資料目錄：%s\n" % server.data_dir)
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
