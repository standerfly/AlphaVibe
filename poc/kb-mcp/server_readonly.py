"""alphavibe-kb 唯讀 MCP wrapper——給 Cline 用（AI/harness 分流機制的執行端）。

background：server.py 本身沒有 per-tool 開關，Cline 的 cline_mcp_settings.json
也沒有 per-tool allow/deny 欄位（只能整個 server 開/關，見
~/.claude/rules/10-model-dispatch.md 分流章節的教訓）。Cline 一次性呼叫走
`-y`（全自動核准），若直接接 server.py 全部 47 個工具（2026-09-03 更新），模型誤判或被
prompt injection 誘導時可能真的呼叫到 save_holdings/run_market_scan 這類
寫入工具。這支檔案在 transport 層過濾，只轉發跟 stock-researcher 全域
subagent 同一份 28 個唯讀工具白名單（2026-09-03 更新），其餘一律拒絕、也不出現在 tools/list。

資料目錄跟 server.py 解析邏輯相同（同一個 __file__ 推算路徑），
接的是同一個正式資料庫，只是拿掉寫入能力——不是另一份測試資料。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as kb_server  # noqa: E402

READONLY_TOOLS = {
    "get_stance", "list_stances", "search_comments", "get_philosophy",
    "get_fundamentals", "get_stock_info", "get_stock_price_history",
    "get_revenue_yoy", "get_institutional_trading", "get_snapshots",
    "get_holdings", "get_stock_alias", "get_stock_theme", "get_position_plan",
    "get_laoyutou_trades", "get_trade_ledger", "check_general_review",
    "check_strategy_review", "check_laoyutou_signal",
    "check_position_control", "get_emerging_stock_valuation",
    "check_auto_score",
    "parse_holdings_report", "screen_stocks", "get_market_scan",
    "get_position_pnl", "get_price_position",
    # get_exit_threshold 是唯讀查詢，可以進白名單；
    # save_exit_threshold 是**寫入**工具，刻意不加——FR-004 明文規定
    # 門檻設定只能在具備完整工具存取的主對話進行。
    "get_exit_threshold",
}

READONLY_TOOL_SCHEMAS = [t for t in kb_server.TOOLS if t["name"] in READONLY_TOOLS]


class ReadonlyServer(kb_server.Server):
    def handle(self, msg):
        method = msg.get("method")
        if method == "tools/list":
            return self._result(msg.get("id"), {"tools": READONLY_TOOL_SCHEMAS})
        if method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name not in READONLY_TOOLS:
                return self._result(msg.get("id"), {
                    "content": [{"type": "text",
                                 "text": "這個唯讀 wrapper 沒有授權呼叫寫入工具：%s" % name}],
                    "isError": True,
                })
        return super().handle(msg)


def main():
    server = ReadonlyServer()
    sys.stderr.write("alphavibe-kb-readonly 啟動（僅 %d 個唯讀工具），資料目錄：%s\n"
                      % (len(READONLY_TOOLS), server.data_dir))
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
