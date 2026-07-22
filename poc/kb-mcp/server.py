"""alphavibe-kb — 三層知識庫 MCP server（stdio）。

純標準庫實作 MCP stdio transport（每行一個 JSON-RPC 訊息）：本機只有
Python 3.9，官方 MCP SDK 需 3.10+，故不引依賴。僅實作 tools 能力，
對應 product-spec FR-015~021 與 Q-021 即時確認制（工具核准＝使用者確認）。

資料目錄：環境變數 ALPHAVIBE_DATA_DIR，預設 <本檔案>/../data。
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finmind_client  # noqa: E402
import holdings_parser  # noqa: E402
import screener  # noqa: E402
import tpex_client  # noqa: E402
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
        "name": "save_comments_batch",
        "description": ("一次存入多筆 Layer 3 評論，欄位同 save_comment。適合貼一整批"
                        "交易/評論紀錄時減少逐筆呼叫。個別筆缺必填欄位（body/source_tag）"
                        "只會該筆失敗，不影響其餘筆數存入——回傳含每筆結果。"
                        "經使用者確認後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "comments": {
                    "type": "array",
                    "description": "評論清單，每筆欄位同 save_comment",
                    "items": {
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
            },
            "required": ["comments"],
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
    {
        "name": "get_stock_info",
        "description": "查股票基本資料：股票名稱/產業分類/市場別（TWSE/TPEX/興櫃）。不帶 stock_id 查全部。",
        "inputSchema": {
            "type": "object",
            "properties": {"stock_id": {"type": "string", "description": "台股代碼；省略＝查全部"}},
        },
    },
    {
        "name": "get_stock_price_history",
        "description": "查個股股價歷史（OHLC/成交量）。start_date 預設近 90 天，end_date 預設今天。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string", "description": "台股代碼，如 2330"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD，預設近 90 天"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "get_revenue_yoy",
        "description": "查個股月營收年增率（FinMind 無此欄位，以去年同月營收自行計算；找不到去年同月資料則標 null）。",
        "inputSchema": {
            "type": "object",
            "properties": {"stock_id": {"type": "string", "description": "台股代碼，如 2330"}},
            "required": ["stock_id"],
        },
    },
    {
        "name": "get_institutional_trading",
        "description": ("查三大法人買賣超（外資/投信/自營商，長表格式）。start_date 預設近 30 天、"
                        "end_date 預設今天。額外回傳 foreign_net：外資（含外資自營商）淨買賣超加總。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_id": {"type": "string", "description": "台股代碼，如 2330"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD，預設近 30 天"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
            },
            "required": ["stock_id"],
        },
    },
    {
        "name": "save_snapshot",
        "description": ("將本次分析結論凍結為快照：當時價格/估值＋三段式結論"
                        "（驅動因素/下檔風險/後續關注點）＋框架版本，可附引用來源。"
                        "股市資料會過期，凍結才能日後 diff（FR-026/027）。"
                        "經使用者確認後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "thesis": {"type": "string", "description": "驅動因素（為什麼看好/看壞）"},
                "risks": {"type": "string", "description": "下檔風險"},
                "watch_next": {"type": "string", "description": "後續關注點"},
                "name": {"type": "string", "description": "股票名稱"},
                "snapshot_date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
                "price_at_time": {"type": "number", "description": "當時股價"},
                "valuation_at_time": {"type": "string", "description": "當時估值，如「PER 18.5、殖利率 2.1%」"},
                "framework_version": {"type": "string", "description": "使用的篩選框架版本，如 framework_v1"},
                "model_id": {"type": "string", "description": "產出此結論的模型"},
                "source_ref": {"type": "string", "description": "對話來源引用"},
                "sources": {
                    "type": "array",
                    "description": "查證來源清單",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "retrieved_at": {"type": "string", "description": "擷取日期，預設今天"},
                            "quote_summary": {"type": "string", "description": "引用重點摘要"},
                        },
                    },
                },
            },
            "required": ["code", "thesis"],
        },
    },
    {
        "name": "get_snapshots",
        "description": "列出標的歷次分析快照（由新到舊，含引用來源），供「當時判斷 vs 現在事實」diff 對照（FR-028）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "limit": {"type": "integer", "description": "筆數上限，預設 10"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "save_holdings",
        "description": ("將截圖解析出的持股寫入持股快照（FR-029；只記 {code, name, "
                        "shares, avg_cost}，不做損益計算——Q-035 邊界）。"
                        "經使用者確認解析結果後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "description": "持股清單",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "股票代碼"},
                            "name": {"type": "string", "description": "股票名稱"},
                            "shares": {"type": "number", "description": "股數/張數"},
                            "avg_cost": {"type": "number", "description": "平均成本"},
                        },
                        "required": ["code"],
                    },
                },
                "snapshot_date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
                "source_ref": {"type": "string", "description": "來源（如：截圖檔名/對話）"},
            },
            "required": ["rows"],
        },
    },
    {
        "name": "get_holdings",
        "description": "查最新一次持股快照（不給 code），或單一標的的持股快照歷史（給 code）。",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼；省略＝最新整體持股"}},
        },
    },
    {
        "name": "refresh_holdings_prices",
        "description": ("批次更新目前庫存（get_holdings）每檔代碼的股價快取（近 7 天最新"
                        "收盤價）與產業別快取，供手機檢視頁顯示市值/持股比例/產業別——"
                        "檢視頁本身不即時呼叫外部 API，靠這個工具定期寫入快取。"
                        "個別代碼查詢失敗或查無資料（如興櫃股無 TaiwanStockPrice）只會"
                        "該檔記入 failed，不中斷整批。不需參數。"),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_stock_alias",
        "description": ("將查證過的股票名稱→代碼對應存入快取，避免下次遇到同一檔"
                        "又要重新查證（同名再存＝更新既有記錄）。經確認查證結果後呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "股票常用簡稱，如「環宇KY」"},
                "code": {"type": "string", "description": "股票代碼，如 4991"},
                "name_full": {"type": "string", "description": "正式全名"},
                "market": {"type": "string", "description": "上市/上櫃/興櫃"},
                "source": {"type": "string", "description": "查證來源摘要"},
                "verified_date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
            },
            "required": ["name", "code"],
        },
    },
    {
        "name": "get_stock_alias",
        "description": "查詢股票名稱→代碼查證快取；不給 name 則列出全部（依查證日期新到舊）。",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "股票簡稱；省略＝列全部"}},
        },
    },
    {
        "name": "get_emerging_stock_valuation",
        "description": ("查興櫃股估值粗估：PER（TPEx興櫃當日行情÷EPS排名）／PBR"
                        "（資本額估算股數，搭配FinMind淨值）。FinMind的PER資料集"
                        "不含興櫃股，故另用此工具。⚠️ 精確度低於正式上市櫃股"
                        "（EPS非TTM基礎、股數為估算值）——回傳一定含 caveats 欄位，"
                        "呈現給使用者時務必一併轉達，不可當成嚴謹估值。"),
        "inputSchema": {
            "type": "object",
            "properties": {"stock_id": {"type": "string", "description": "興櫃股代碼，如 6826"}},
            "required": ["stock_id"],
        },
    },
    {
        "name": "parse_holdings_report",
        "description": ("解析券商零股庫存表原始文字，擷取每列的代碼/名稱/股數"
                        "（名稱含 * 前綴代表興櫃，另標 is_emerging）。純解析、"
                        "不寫入資料庫——請先把解析結果念給使用者確認無誤，"
                        "確認後再呼叫 save_holdings 正式入庫。看起來像資料列但"
                        "解析不出來的行會列在 unparsed_lines，需人工檢查。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "券商 App/網站匯出的零股庫存表原始文字"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "screen_stocks",
        "description": ("第一層選股篩選：對候選代碼清單逐一計算PEG（本益成長比）"
                        "與股價回檔幅度（近120天區間高點到最新收盤），依"
                        "framework_peg_deep_dip_concentration 框架標註是否同時符合"
                        "「PEG<1 且回檔>=40%」。結果依PEG由小到大排序（算不出來的"
                        "排最後）。單檔查詢失敗只記錄在該筆的error欄位，不影響其他"
                        "代碼。一次最多 50 檔，超過會回傳 error 欄位並拒絕執行——"
                        "請提醒使用者分批。這是候選清單篩選，不是全市場掃描。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "string",
                          "description": "候選股票代碼，逗號或換行分隔，如 3485,6953,6719"},
            },
            "required": ["codes"],
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
        if name == "save_comments_batch":
            return self.store.save_comments_batch(args["comments"])
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
        if name == "get_stock_info":
            return finmind_client.get_stock_info(
                stock_id=args.get("stock_id"), data_dir=self.data_dir)
        if name == "get_stock_price_history":
            return finmind_client.get_stock_price_history(
                args["stock_id"], start_date=args.get("start_date"),
                end_date=args.get("end_date"), data_dir=self.data_dir)
        if name == "get_revenue_yoy":
            return finmind_client.get_revenue_yoy(
                args["stock_id"], data_dir=self.data_dir)
        if name == "get_institutional_trading":
            return finmind_client.get_institutional_trading(
                args["stock_id"], start_date=args.get("start_date"),
                end_date=args.get("end_date"), data_dir=self.data_dir)
        if name == "save_snapshot":
            return self.store.save_snapshot(
                code=args["code"], thesis=args["thesis"],
                name=args.get("name"), snapshot_date=args.get("snapshot_date"),
                price_at_time=args.get("price_at_time"),
                valuation_at_time=args.get("valuation_at_time"),
                risks=args.get("risks"), watch_next=args.get("watch_next"),
                framework_version=args.get("framework_version"),
                model_id=args.get("model_id"),
                source_ref=args.get("source_ref"),
                sources=args.get("sources"),
            )
        if name == "get_snapshots":
            return self.store.get_snapshots(
                args["code"], limit=int(args.get("limit") or 10))
        if name == "save_holdings":
            return self.store.save_holdings(
                rows=args["rows"], snapshot_date=args.get("snapshot_date"),
                source_ref=args.get("source_ref"))
        if name == "get_holdings":
            return self.store.get_holdings(code=args.get("code"))
        if name == "refresh_holdings_prices":
            return self.refresh_holdings_prices()
        if name == "save_stock_alias":
            return self.store.save_stock_alias(
                name=args["name"], code=args["code"],
                name_full=args.get("name_full"), market=args.get("market"),
                source=args.get("source"), verified_date=args.get("verified_date"),
            )
        if name == "get_stock_alias":
            return self.store.get_stock_alias(name=args.get("name"))
        if name == "parse_holdings_report":
            return holdings_parser.parse_holdings_report(args["text"])
        if name == "get_emerging_stock_valuation":
            return tpex_client.get_emerging_stock_valuation(
                args["stock_id"], data_dir=self.data_dir)
        if name == "screen_stocks":
            codes = screener.parse_codes(args["codes"])
            return screener.screen_stocks(codes, data_dir=self.data_dir)
        raise ValueError("未知工具：%s" % name)

    def refresh_holdings_prices(self):
        """批次更新目前庫存代碼的股價／產業別快取。

        價格：對每檔代碼查近 7 天 TaiwanStockPrice（只是要拿最新收盤價，
        不需要抓 90 天預設窗口），取日期最新一筆 close 存入 stock_prices。
        查詢失敗或查無資料（如興櫃股）只讓該檔記入 failed，不中斷整批
        （外部 API 失敗不阻塞，同 finmind_client 的設計原則）。

        產業別：同一批代碼「順便」用同一次 get_stock_info() 全市場查詢帶出
        （不為了產業別另外呼叫一次全市場 API），篩出庫存代碼對應的
        industry_category 存入 stock_industries。
        """
        holdings = self.store.get_holdings()["holdings"]
        codes = []
        seen = set()
        for h in holdings:
            code = h["code"]
            if code not in seen:
                seen.add(code)
                codes.append(code)

        start_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        updated = 0
        failed = []
        prices = {}
        for code in codes:
            try:
                result = finmind_client.get_stock_price_history(
                    code, start_date=start_date, data_dir=self.data_dir)
                price_rows = result.get("prices") or []
                if not price_rows:
                    reason = "; ".join(result.get("errors") or ["查無股價資料"])
                    failed.append({"code": code, "reason": reason})
                    continue
                latest = max(price_rows, key=lambda r: r.get("date") or "")
                close = latest.get("close")
                if close is None:
                    failed.append({"code": code, "reason": "最新資料缺收盤價"})
                    continue
                saved = self.store.upsert_stock_price(code, close, latest.get("date"))
                prices[code] = {"price": saved["price"], "price_date": saved["price_date"],
                                "updated_at": saved["updated_at"]}
                updated += 1
            except Exception as exc:  # 單檔非預期錯誤不可讓整批中斷
                failed.append({"code": code, "reason": "非預期錯誤：%s" % exc})

        if codes:
            try:
                info = finmind_client.get_stock_info(data_dir=self.data_dir)
                code_set = set(codes)
                for stock in info.get("stocks") or []:
                    stock_id = stock.get("stock_id")
                    if stock_id in code_set:
                        self.store.upsert_stock_industry(
                            stock_id, stock.get("industry_category"))
            except Exception:
                pass  # 產業別是附加資訊，查詢失敗不可讓已完成的股價更新結果遺失

        return {"updated": updated, "failed": failed, "prices": prices}

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
