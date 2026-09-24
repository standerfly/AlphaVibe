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
`specs/003-us-stocks/contracts/mcp-tools.md` 工具一/二/三/八）。

**Phase 4（US2，T021）新增 2 個工具**——`save_us_stance`／`get_us_stance`
（contracts 工具四/五）：agent 與使用者討論後的投資立場／研究筆記寫入與
查詢。`get_us_stance` 預設只回傳最新一筆 `status='active'` 立場（含完整
`full_note`，不截斷，FR-009），`include_closed=true` 時改回傳全部歷史
立場列表——兩種模式回傳形狀不同（單一物件 vs 陣列），呼叫端需依
`include_closed` 參數判斷，不是同一個 key 底下切換型別。

**Phase 5（US3，T026）新增 2 個工具**——`save_us_watch_condition`／
`get_us_watch_conditions`（contracts 工具六/七）。監控條件的「新增」走
網頁表單直接呼叫 REST 端點（`app/routers/us_stocks.py`，T028）而非 agent
對話，跟 trades/stances 的寫入模式不同——這裡仍提供 MCP 工具版本供 agent
在對話中也能直接幫使用者設定監控門檻（例如「幫我在 NET 跌破 250 時提醒
我」這類自然語言請求）。`get_us_watch_conditions` 回傳的每筆條件都帶
`is_stale` 衍生欄位（`USStockStore.list_watch_conditions_with_stale()`）。

排程評估／推播邏輯（`update_watch_condition_evaluation`／
`mark_watch_condition_notified`／Telegram 推播 stub）在 `us_stock_scan.py`，
不是 MCP 工具的職責——MCP 工具只負責「使用者/agent 主動設定與查詢監控
條件」，不負責背景排程的自動評估。

`get_us_watchlist`（工具九，四表聯集彙整含立場/監控狀態）仍不在 MCP
server 範圍：landing 頁改由 `app/routers/us_stocks.py` 直接組合
`USStockStore` 既有方法完成（`GET /api/us-stocks/watchlist`），避免同一份
彙整邏輯要在 MCP 工具與 REST 端點各寫一次、日後改一邊忘了改另一邊。

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

# Phase 3（US1）4 個工具＋Phase 4（US2）新增 2 個工具，對應
# contracts/mcp-tools.md 工具一/二/三/四/五/八。其餘 3 個工具留待
# Phase 5，見本檔案開頭 docstring。
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
    {
        "name": "save_us_stance",
        "description": (
            "把 agent 與使用者討論後的投資立場與完整研究筆記存入 "
            "us_stances 表。一檔股票可有多筆，每次重新討論後勢都新增一筆"
            "（不覆蓋舊的）。full_note 是完整研究筆記內容，不得省略章節"
            "（FR-009）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["bullish", "bearish", "neutral"],
                    "description": "買/賣/觀望方向",
                },
                "bear_price": {"type": "number", "description": "Bear 情境價格帶下緣"},
                "bear_price_high": {"type": "number", "description": "Bear 情境價格帶上緣"},
                "base_price_low": {"type": "number", "description": "Base 情境價格帶下緣"},
                "base_price_high": {"type": "number", "description": "Base 情境價格帶上緣"},
                "bull_price": {"type": "number", "description": "Bull 情境價格帶下緣"},
                "summary": {"type": "string", "description": "論點摘要（短文字，供列表/卡片顯示）"},
                "full_note": {
                    "type": "string",
                    "description": "完整研究筆記內容，Markdown格式，FR-009渲染來源，不得省略章節",
                },
            },
            "required": ["ticker", "direction", "summary", "full_note"],
        },
    },
    {
        "name": "get_us_stance",
        "description": (
            "取得個股詳情頁「投資立場」卡片與完整研究筆記內容。預設只回傳"
            "最新一筆 status='active' 的立場（含 full_note 完整內容，不"
            "截斷）；include_closed=true 時回傳全部歷史立場列表。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "include_closed": {
                    "type": "boolean",
                    "description": "true＝回傳全部歷史立場列表；省略/false＝只回傳最新一筆active立場",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "save_us_watch_condition",
        "description": "新增一筆監控門檻（例如股價、毛利率）。新建立時狀態固定為 insufficient_data，要等下一次排程評估才會轉為 ok/alert。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "metric_type": {
                    "type": "string",
                    "enum": ["price", "gaap_gross_margin", "revenue_yoy"],
                    "description": "指標類型：price=股價, gaap_gross_margin=毛利率, revenue_yoy=營收年增率",
                },
                "comparator": {
                    "type": "string",
                    "enum": ["lt", "gt"],
                    "description": "lt=小於門檻時觸發, gt=大於門檻時觸發",
                },
                "threshold": {"type": "number", "description": "門檻數值"},
            },
            "required": ["ticker", "metric_type", "comparator", "threshold"],
        },
    },
    {
        "name": "get_us_watch_conditions",
        "description": (
            "取得監控條件與目前狀態（status: ok=未觸發/alert=已觸發/"
            "insufficient_data=資料不足）。每筆額外帶 is_stale 衍生欄位："
            "true 時代表 last_evaluated_at 不是今天，前端應顯示「未更新"
            "（無額度）」而非直接採信 status（status 在這種情況下維持上一次"
            "成功評估的值）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "省略＝回傳全部股票的監控條件"},
            },
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
        if name == "save_us_stance":
            ticker = args.get("ticker")
            direction = args.get("direction")
            summary = args.get("summary")
            full_note = args.get("full_note")
            if not ticker or not direction or not summary or not full_note:
                raise ValueError(
                    "save_us_stance 需要 ticker/direction/summary/full_note 參數")
            return self.store.save_stance(
                ticker, direction, summary, full_note,
                bear_price=args.get("bear_price"),
                bear_price_high=args.get("bear_price_high"),
                base_price_low=args.get("base_price_low"),
                base_price_high=args.get("base_price_high"),
                bull_price=args.get("bull_price"),
            )
        if name == "get_us_stance":
            ticker = args.get("ticker")
            if not ticker:
                raise ValueError("get_us_stance 需要 ticker 參數")
            if args.get("include_closed"):
                return {"ticker": ticker,
                        "stances": self.store.list_stances(ticker, include_closed=True)}
            return {"ticker": ticker,
                    "stance": self.store.get_latest_stance(ticker, include_closed=False)}
        if name == "save_us_watch_condition":
            ticker = args.get("ticker")
            metric_type = args.get("metric_type")
            comparator = args.get("comparator")
            threshold = args.get("threshold")
            if not ticker or not metric_type or not comparator or threshold is None:
                raise ValueError(
                    "save_us_watch_condition 需要 ticker/metric_type/"
                    "comparator/threshold 參數")
            return self.store.save_watch_condition(
                ticker, metric_type, comparator, threshold)
        if name == "get_us_watch_conditions":
            ticker = args.get("ticker")
            return {"conditions": self.store.list_watch_conditions_with_stale(ticker)}
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
                # 失敗時撤回未 commit 的寫入（2026-09-17 架構體檢 A2）。
                # 這個 stdio 服務整個 session 共用同一條 SQLite 連線，
                # 工具中途失敗留下的未決交易不會自己消失，會被下一次任何
                # 無關的成功寫入順帶 commit 進正式庫。個別寫入方法自己也
                # 該保證原子性（見 kb_store.save_holdings），這裡是涵蓋
                # 所有工具、包含日後新增的那些的防禦網。
                # rollback 自己失敗（連線已關閉等）不能蓋掉原本的錯誤訊息，
                # 所以吞掉它——使用者要看到的是工具為什麼失敗。
                try:
                    self.store.conn.rollback()
                except Exception:
                    pass
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
    sys.stderr.write("alphavibe-us-stock 啟動（%d 個工具），資料目錄：%s\n"
                      % (len(TOOLS), server.data_dir))
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
