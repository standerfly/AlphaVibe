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
import frameworks  # noqa: E402
import fundamentals_client  # noqa: E402
import holdings_parser  # noqa: E402
import market_scan  # noqa: E402
import review_engine  # noqa: E402
import screener  # noqa: E402
import tpex_client  # noqa: E402
import trade_ledger_parser  # noqa: E402
import trade_text_parser  # noqa: E402
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
        "description": ("查個股基本面：近期 PER/PBR/殖利率（官方TWSE/TPEx優先，FinMind降級為備援，"
                        "見 valuation_data_source）＋近 6 個月營收（FinMind，FR-019 名單驅動選股用）。"),
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
        "description": ("查個股月營收年增率完整序列（FinMind無此欄位，以去年同月營收自行計算；"
                        "找不到去年同月資料則標null）。額外附上 latest：最新一期年增率，"
                        "官方TWSE/TPEx優先、FinMind降級為備援。"),
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
        "name": "save_stock_theme",
        "description": ("記錄一檔股票的投資主題標籤（如「AI CAPEX」），跟官方產業分類是"
                        "兩回事，供部位管理組合集中度檢查用（單一主題最多50%）。一檔股票"
                        "只有一個主題，同代碼再存＝覆蓋既有標籤。經使用者確認後呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "theme": {"type": "string", "description": "投資主題，如「AI CAPEX」"},
            },
            "required": ["code", "theme"],
        },
    },
    {
        "name": "check_auto_score",
        "description": ("Score 自動化四項評分（EPS實際成長+3／月營收YoY加速+2／毛利率提升+2／"
                        "ROE改善+1，皆為最新一季對去年同季比較）。earned=true 計分、false 已"
                        "查證但條件不成立、null 資料不足——三者意義不同，不要把 null 當 false。"
                        "另有三項（法人上修EPS／新增大客戶訂單／產業需求提升）無免費資料源，"
                        "不在本工具範圍，需人工判斷。財報走30天TTL快取，不會每次都打外部API。"),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼"}},
            "required": ["code"],
        },
    },
    {
        "name": "save_position_plan",
        "description": ("設定或調整一檔股票的「加碼計畫總額度」（單位：金額 NT$）。這是"
                        "`check_position_control` 的 suggested_add_pct（遞減式加碼比例）"
                        "一直缺的分母——有了它才算得出「加碼進度：已投入/計畫總額/完成"
                        "幾成」。同代碼再存＝覆蓋（投資預算會變動，額度本來就該可調整）。"
                        "經使用者確認金額後才呼叫，不要自己臆測額度。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "plan_amount": {"type": "number",
                                "description": "計畫總額度（新台幣，須大於0）"},
                "note": {"type": "string", "description": "選填備註，如額度的訂定理由"},
            },
            "required": ["code", "plan_amount"],
        },
    },
    {
        "name": "get_position_plan",
        "description": ("查詢一檔股票的加碼計畫總額度。沒設定過回傳 null——這代表「還沒"
                        "設定」，不是「額度為0」，不要拿 null 當0計算完成比例。"),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼"}},
            "required": ["code"],
        },
    },
    {
        "name": "save_pending_verification",
        "description": ("登記一筆「待觀察／待驗證」判斷：一個判斷/假設，帶著「等到某個"
                        "未來時間點或事件發生就能驗證」的但書（例：NVIDIA公布財報後驗證"
                        "毛利率是否守住）。研究/分析對話中識別出這種句型時可主動建議登記。"
                        "trigger_type=date 時 trigger_date 為必填。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "judgment_text": {"type": "string", "description": "判斷/假設內容"},
                "trigger_type": {"type": "string", "enum": ["date", "event"],
                                  "description": "觸發類型"},
                "trigger_date": {"type": "string",
                                  "description": "YYYY-MM-DD，trigger_type=date 時必填"},
                "trigger_condition_text": {"type": "string",
                                            "description": "觸發條件文字描述"},
                "code": {"type": "string", "description": "可選，關聯股票代碼"},
                "theme": {"type": "string", "description": "可選，關聯主題"},
                "target_value": {"type": "string",
                                  "description": "可選，具體驗證目標，如「毛利率75%」"},
                "source_ref": {"type": "string", "description": "來源引用"},
            },
            "required": ["judgment_text", "trigger_type", "trigger_condition_text"],
        },
    },
    {
        "name": "list_pending_verifications",
        "description": ("查詢待觀察項目清單。due_only=true 時只回傳已到期／即將到期"
                        "（7天內）且狀態仍是 pending 的項目——適合用來回答「有哪些待驗證"
                        "的事現在該回頭看了」。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "resolved", "dropped"],
                            "description": "可選，依狀態篩選；不填則回傳全部狀態"},
                "due_only": {"type": "boolean",
                              "description": "可選，true 時只回傳已到期/即將到期且status=pending的項目"},
            },
            "required": [],
        },
    },
    {
        "name": "get_pending_verification",
        "description": "取得單筆待觀察項目的完整內容（含歷史resolution/resolved_at，若已標記過）。",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "待觀察項目ID"}},
            "required": ["id"],
        },
    },
    {
        "name": "resolve_pending_verification",
        "description": ("標記待觀察項目為resolved（需附resolution驗證結論）或dropped"
                        "（resolution可選，代表不追蹤原因）。已是終態的項目不可再次"
                        "轉換——要重新追蹤同一判斷，請登記一筆新項目。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "待觀察項目ID"},
                "status": {"type": "string", "enum": ["resolved", "dropped"],
                            "description": "目標狀態"},
                "resolution": {"type": "string",
                                "description": "status=resolved時必填；status=dropped時可選"},
            },
            "required": ["id", "status"],
        },
    },
    {
        "name": "get_stock_theme",
        "description": "查詢所有股票的投資主題標籤（code→theme 對照）。不需參數。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_laoyutou_trade",
        "description": ("記錄老芋頭（PO信任的資深投資朋友／導師，非系統使用者）的一筆"
                        "進出。他不一定每次都寫原因，但寫的時候是重要訊號（策略框架本身"
                        "即從他的原因沉澱而來），reason 可省略。供模組D「老芋頭動向比對」"
                        "（FR-053）比對他的進出、以及跟PO持股交叉比對用。經使用者確認後"
                        "呼叫，不要自行猜測他的交易內容。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "name": {"type": "string", "description": "股票名稱"},
                "action": {"type": "string", "description": "買 或 賣"},
                "shares": {"type": "number", "description": "股數"},
                "price": {"type": "number", "description": "價格"},
                "date": {"type": "string", "description": "交易日期 YYYY-MM-DD"},
                "reason": {"type": "string", "description": "原因，可省略（他不一定每次都寫）"},
                "source_ref": {"type": "string", "description": "來源引用"},
            },
            "required": ["code", "action", "shares", "price", "date"],
        },
    },
    {
        "name": "get_laoyutou_trades",
        "description": "查老芋頭交易紀錄；不給 code 列出最近N筆（跨標的，依日期新到舊），給 code 列出該標的的老芋頭交易歷史。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，省略＝跨標的列最近N筆"},
                "limit": {"type": "integer", "description": "回傳筆數上限，預設 20"},
            },
        },
    },
    {
        "name": "save_trade_ledger_entry",
        "description": ("記錄PO自己的一筆進出到交易流水表（FR-056，跟老芋頭的交易表是"
                        "兩張不同的表，這張是PO自己的），取代 holdings 快照覆蓋式的限制。"
                        "add_sequence＝這是第幾次加碼（供FR-054遞減式加碼比例"
                        "40/25/15/10/10%計算用），只在買入時有意義；賣出時會被忽略、強制"
                        "存為 NULL。經使用者確認後呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼"},
                "name": {"type": "string", "description": "股票名稱"},
                "action": {"type": "string", "description": "買 或 賣"},
                "add_sequence": {"type": "integer", "description": "第幾次加碼（1起算），僅買入適用，賣出會被忽略"},
                "shares": {"type": "number", "description": "股數"},
                "price": {"type": "number", "description": "價格"},
                "date": {"type": "string", "description": "交易日期 YYYY-MM-DD"},
                "source_ref": {"type": "string", "description": "來源引用"},
            },
            "required": ["code", "action", "shares", "price", "date"],
        },
    },
    {
        "name": "get_trade_ledger",
        "description": ("查某標的完整加碼流水（依日期由舊到新），供呼叫端推算「下一次"
                        "加碼是第幾次」（數 add_sequence 非空的買入筆數＋1）。"),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼"}},
            "required": ["code"],
        },
    },
    {
        "name": "check_general_review",
        "description": ("FR-051 模組D通用檢視層：不管哪個策略篩進來的標的，每檔都要過的"
                        "一致性提醒（所有檢查結果都是提醒，不自動裁決，決策權在PO）。"
                        "這次只自動算2項——成長趨緩（近3個月月營收年增率是否連續下滑，"
                        "且仍是正成長）、下檔風險（目前PER相對近2年歷史分布是否偏高，"
                        "偏高時附「PE回歸歷史中位數」的潛在跌幅粗估）。財報兌現度／"
                        "利多出盡／預期獲利能否持續上修這3項尚未自動化，回傳裡的"
                        "manual_notes 是留給PO手動填寫的欄位（一律是None，需另外呼叫"
                        "其他方式記錄，本工具不寫入）。"),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼，如 2330"}},
            "required": ["code"],
        },
    },
    {
        "name": "check_strategy_review",
        "description": ("FR-052 模組D策略專屬層：這檔標的目前還符不符合當初篩進來那套"
                        "策略的假說（用該策略自訂的「假說失效」規則，跟FR-050進場篩選"
                        "門檻是不同方向的判斷——進場門檻要全部符合，失效判斷是任一子"
                        "條件成立即算失效）。重用screen_stocks()已算好的PEG／回檔幅度／"
                        "營收年增率數值，不重新查詢。查無此strategy_id或資料不足/查詢"
                        "失敗時，invalidated一律回False（保守原則，不確定就不誤報失效），"
                        "reasons附說明。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，如 2330"},
                "strategy_id": {"type": "string", "description": "策略代號，如 peg_deep_dip_concentration"},
            },
            "required": ["code", "strategy_id"],
        },
    },
    {
        "name": "check_laoyutou_signal",
        "description": ("FR-053 模組D老芋頭動向比對：獨立訊號來源，不限定策略——查該標的"
                        "近N天（預設14天，可用lookback_days調整）內是否有老芋頭交易紀錄"
                        "（store.get_laoyutou_trades），並比對PO目前是否持有此檔"
                        "（store.get_holdings）。多筆交易時finding以最新一筆為主，"
                        "recent_trades完整列出視窗內全部交易。⚠️ 純陳述事實（他做了"
                        "什麼、你現在持有狀態），刻意不做任何基本面判斷或自動建議——"
                        "解讀交給使用者或後續對話脈絡。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，如 2330"},
                "lookback_days": {"type": "integer",
                                  "description": "回顧視窗天數，預設14"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "check_position_control",
        "description": ("FR-054 模組D部位控制建議（核心功能）：整合信心分級初始部位"
                        "（普通/很好/非常高→5%/8%/10%，僅「這是這檔第一次建倉」且有給"
                        "confidence_level時才提供）、遞減式加碼比例（第1~5次"
                        "40/25/15/10/10%，依store.get_trade_ledger算出下一次加碼序號；"
                        "超過5次時該欄位查不到值但仍照實回傳實際序號）、集中度上限提醒"
                        "（單股佔比≥15%或所屬主題佔比≥50%）。⚠️ 遞減式加碼比例"
                        "（suggested_add_pct）是「這次加碼佔此股加碼計畫總額度的比例」，"
                        "不是投資組合佔比，兩者量綱不同，本工具不做換算（哲學文件未"
                        "定義「加碼計畫總額度」怎麼訂）。目前市值佔比（current_"
                        "position_pct）與主題集中度（theme_concentration_pct）計算"
                        "邏輯與report.py既有「我的庫存與分析」頁面一致（市值=股數×"
                        "股價快取，查不到股價的持股不計入分母）。所有結果都是提醒，"
                        "不自動裁決。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，如 2330"},
                "confidence_level": {"type": "string",
                                     "description": "信心等級：普通／很好／非常高；"
                                                    "省略則不提供初始部位建議"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "record_module_d_findings",
        "description": ("FR-055 立場自動回寫機制：把FR-051~054（通用檢視層／策略專屬層／"
                        "老芋頭動向比對／部位控制建議）當天對同一標的批次跑出來的發現，"
                        "各自新增一筆Layer 2立場記錄（不合併、不覆蓋，沿用該標的目前最新"
                        "立場的stance值，系統不主動改變決策本身）。查無既有立場（沒有"
                        "「決策」可以承接）時整批略過不寫入，回傳skipped=true。⚠️ 只偵測"
                        "「findings裡concern_flag是否一致」這種系統記錄間的分歧，不做"
                        "「系統發現跟PO既有立場文字語意衝突」的自動判斷（語意判斷留給PO"
                        "自己讀了決定，已與PO確認此範圍簡化）；有分歧時每筆reason都會"
                        "附上衝突提示，列出這批裡各trigger_label標記需留意/無異常。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代碼，如 2330"},
                "findings": {
                    "type": "array",
                    "description": "同一天、同一標的的一批發現",
                    "items": {
                        "type": "object",
                        "properties": {
                            "trigger_label": {"type": "string",
                                              "description": "觸發來源標籤，如「策略層／peg_deep_dip_concentration」"},
                            "concern_flag": {"type": "boolean",
                                             "description": "true=需留意，false=無異常"},
                            "detail": {"type": "string", "description": "發現內容說明"},
                        },
                        "required": ["trigger_label", "concern_flag", "detail"],
                    },
                },
                "date": {"type": "string", "description": "YYYY-MM-DD，預設今天"},
            },
            "required": ["code", "findings"],
        },
    },
    {
        "name": "run_module_d_check",
        "description": ("FR-057 模組D單檔即時檢視：串接FR-051~055整個流程"
                        "（通用檢視層／策略專屬層／老芋頭動向比對／部位控制"
                        "建議／立場自動回寫），供PO貼入老芋頭新動向後即時"
                        "觸發單一標的重新檢視（不用等隔天02:00排程）。策略"
                        "專屬層會自動判斷這檔標的最近符合過哪些框架門檻"
                        "（依market_scan歷史紀錄），沒被market_scan篩中過的"
                        "標的（PO手動加入觀察名單、或老芋頭訊號帶進來的）"
                        "只跑通用層與老芋頭層，這是正常情況不是錯誤。只有"
                        "findings裡concern_flag=True的項目才會寫入stances"
                        "（Layer 2）；不管有沒有concern，每一項檢視結果"
                        "（含正常無異常的）都會寫入模組D檢視結果表供未來"
                        "模組F儀表板讀取。⚠️ 這是單檔查詢，若要批次跑整個"
                        "觀察名單＋庫存，請用CLI `module_d_scheduler.py`"
                        "（排程用，不開放成MCP工具，成本較高不適合對話中"
                        "隨手觸發）。"),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "股票代碼，如 2330"}},
            "required": ["code"],
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
                        "與股價回檔幅度（近120天區間高點到最新收盤），依門檻標註"
                        "是否符合框架（預設「PEG<1 且回檔>=40%」，即"
                        "framework_peg_deep_dip_concentration；可用 framework_id 或"
                        "peg_threshold/drawdown_min/drawdown_max 自訂）。回傳同時附"
                        "excess_drawdown_pct（超額跌幅＝個股回檔－同期大盤跌幅，"
                        "大盤區間取「個股高點日→個股最新日」）與 benchmark 區塊"
                        "（本次查到的大盤基準資料）。結果依PEG由小到大排序（算不出來的"
                        "排最後）。單檔查詢失敗只記錄在該筆的error欄位，不影響其他"
                        "代碼。一次最多 50 檔，超過會回傳 error 欄位並拒絕執行——"
                        "請提醒使用者分批。這是候選清單篩選，不是全市場掃描。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "codes": {"type": "string",
                          "description": "候選股票代碼，逗號或換行分隔，如 3485,6953,6719"},
                "framework_id": {"type": "string",
                                 "description": ("框架代號，見 frameworks.FRAMEWORKS；給了就用該框架的"
                                                 "peg_max/drawdown_min/drawdown_max/excess_drawdown_min"
                                                 "門檻（framework_id 本身不存在時直接回 error，不會呼叫"
                                                 "任何 API）。省略則用下面的 peg_threshold/drawdown_min/"
                                                 "drawdown_max 或其預設值。同時給 framework_id 又給"
                                                 "peg_threshold 等參數時，以後者為準（framework_id 只是"
                                                 "帶入預設值的捷徑）。")},
                "peg_threshold": {"type": ["number", "null"],
                                  "description": "PEG 門檻上限，預設 1.0；傳 null＝不看這項條件"},
                "drawdown_min": {"type": ["number", "null"],
                                 "description": "回檔幅度下限，小數（0.4＝40%），預設 0.4；傳 null＝不看"},
                "drawdown_max": {"type": ["number", "null"],
                                 "description": "回檔幅度上限，小數；預設不限（null）"},
            },
            "required": ["codes"],
        },
    },
    {
        "name": "run_market_scan",
        "description": ("第二層全市場批次篩選：Stage A 用 TWSE/TPEx 官方批次 "
                        "PER＋月營收年增率 API，在框架鎖定的產業別內快速初篩候選"
                        "（不逐檔查FinMind，比第一層screen_stocks快很多）；Stage B "
                        "對候選逐檔查FinMind股價區間算回檔幅度，套用框架門檻。"
                        "TWSE或TPEx任一資料源失敗不影響另一邊（該市場記入"
                        "market_errors，候選數變少但不中斷）。結果連同執行時間"
                        "存入資料庫（完整候選清單都會存檔）。範圍只有上市＋上櫃，"
                        "興櫃沒有官方批次PER端點不在這次掃描範圍內。候選數常有"
                        "數十~一百多檔，逐檔查回檔實測約30秒量級，屬正常。框架裡"
                        "「供應鏈敘事是否具體」這類條件無法自動判斷，篩出的候選"
                        "仍需人工/AI事後確認。⚠️ 這個工具回傳的是精簡摘要"
                        "（run資訊＋符合框架的候選精簡欄位），不是完整候選清單——"
                        "要看全部候選（含未達門檻）請改用 get_market_scan 並帶"
                        "meets_only=false。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "framework_id": {"type": "string",
                                 "description": "框架代號，見 frameworks.FRAMEWORKS；省略則用預設框架"},
            },
        },
    },
    {
        "name": "get_market_scan",
        "description": ("查詢最近一次全市場批次篩選結果（不重新掃描，速度快）。"
                        "不給framework_id則查全部框架中最新一次。預設只回傳"
                        "「符合框架」的候選、且欄位精簡過（meets_only=true、"
                        "limit=50、verbose=false）——回傳一定附 total_results"
                        "（篩選後總筆數）／returned（實際回傳筆數）／omitted"
                        "（被截掉幾筆）／filters（本次套用的篩選條件），不要把"
                        "returned 誤當成全部候選母體。要拿完整資料（含未達門檻、"
                        "全部欄位）請帶 meets_only=false、limit=0、verbose=true。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "framework_id": {"type": "string",
                                 "description": "框架代號；省略＝查最新一次（不限框架）"},
                "meets_only": {"type": "boolean",
                               "description": "只回傳符合框架的候選，預設 true"},
                "limit": {"type": "integer",
                          "description": "最多回傳幾筆，預設 50；0＝不限"},
                "verbose": {"type": "boolean",
                           "description": "true 才回傳每檔完整欄位，預設 false（只回精簡欄位）"},
            },
        },
    },
    {
        "name": "parse_and_save_laoyutou_trades",
        "description": ("貼入固定格式的老芋頭（PO信任的資深投資朋友／導師）進出"
                        "批次文字，自動解析並批次寫入laoyutou_trades，不需要逐行"
                        "手動理解再一筆筆呼叫save_laoyutou_trade（FR-044，PO明確"
                        "要求格式固定就該用程式解析，不要透過AI逐行理解）。文字第"
                        "一行應為8位數日期（YYYYMMDD，如20260729），代表整批交易"
                        "的日期；之後每行是「原因行」（一段敘述文字，套用到後續"
                        "交易直到空行或下一個原因行為止）或「交易行」"
                        "（{價格}{賣出/買進/買回/回補}{股數}{股/張}{名稱}"
                        "{可選括號註記}，如「365賣出500股聯鈞（出清）」）。股票"
                        "名稱→代碼解析會先查stock_aliases快取，未命中再用FinMind"
                        "全市場清單比對（自動存回快取）；兩者都查無代碼的名稱歸入"
                        "unresolved_names，不會寫入（不可塞假代碼），需人工處理。"
                        "格式解析失敗的行歸入unparsed_lines，同樣需人工檢查。"
                        "經使用者確認貼入的文字無誤後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": ("老芋頭進出批次原始文字，整段貼入。第一行應為"
                                         "8位數日期（YYYYMMDD，如20260729）；文字裡若"
                                         "沒有這行日期，改用 date 參數或今天日期。")},
                "date": {"type": "string",
                         "description": ("YYYY-MM-DD，僅在文字裡沒有偵測到8位數日期行時"
                                         "才會用到；省略則用今天。")},
            },
            "required": ["text"],
        },
    },
    {
        "name": "parse_and_save_trade_ledger",
        "description": ("貼入固定格式的券商「交易明細表」文字，自動解析每筆日期/"
                        "買賣/股數/價格，並正確計算遞減式加碼序號後批次寫入"
                        "trade_ledger（FR-056，PO自己的買賣紀錄——注意跟"
                        "laoyutou_trades〔老芋頭的交易〕是不同表）。每一列格式："
                        "{日期 民國年115/07/22}{CD 如OT賣/集買，含「買」或「賣」"
                        "判斷買賣別}{股票名稱}{股數}{單價}{其餘欄位不需要精確解析}"
                        "，跟老芋頭格式的差異是這裡每一列自己就有完整日期，不需要"
                        "猜整批共用日期。表頭列／分隔線／「交易日期:...頁次:...」"
                        "列／「合 計:」列會自動跳過。add_sequence（第幾次加碼）"
                        "計算：依代碼分組後依日期（同日按原始出現順序）排序，"
                        "接續該代碼在資料庫裡既有的買進筆數往後遞增；賣出一律為"
                        "None。股票名稱→代碼解析先查stock_aliases快取，未命中"
                        "再用FinMind全市場清單比對（自動存回快取）；兩者都查無"
                        "代碼的名稱歸入unresolved_names，不會寫入（不可塞假"
                        "代碼），需人工處理。格式解析失敗的行歸入unparsed_lines，"
                        "同樣需人工檢查。防重複：每列委託書號若跟資料庫裡既有"
                        "紀錄相同，該筆視為重複（同一份對帳單被貼了兩次），"
                        "整筆跳過不寫入，歸入回傳的duplicates_skipped（不佔用"
                        "add_sequence序號）。經使用者確認貼入的文字無誤後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "交易明細表原始文字，整段貼入。"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "parse_and_save_trade_csv",
        "description": ("貼入國泰證券App匯出的「已成交」CSV格式對帳單文字，自動"
                        "解析每筆日期/買賣/股數/價格，並正確計算遞減式加碼序號後"
                        "批次寫入trade_ledger（跟parse_and_save_trade_ledger寫入"
                        "同一張表，只是輸入格式不同——這份格式是標準CSV、西元"
                        "日期，比交易明細表〔民國年+CD欄位〕更乾淨）。文字第一行"
                        "是變動的提示文字（筆數會變，自動跳過，不用管內容），第"
                        "二行是CSV表頭（第一欄「股名」），之後每行是一筆標準CSV"
                        "格式的交易資料（含千分位逗號的欄位有雙引號包住，如"
                        "\"-6,542\"）。買賣別目前只認得「現買」「現賣」（對應"
                        "「買」「賣」），其他字串歸入unparsed_lines。"
                        "add_sequence（第幾次加碼）計算：依代碼分組後依日期"
                        "（同日按原始出現順序）排序，接續該代碼在資料庫裡既有"
                        "的買進筆數往後遞增；賣出一律為None。股票名稱→代碼解析"
                        "先查stock_aliases快取，未命中再用FinMind全市場清單比對"
                        "（自動存回快取）；兩者都查無代碼的名稱歸入"
                        "unresolved_names，不會寫入（不可塞假代碼），需人工"
                        "處理。格式解析失敗的行歸入unparsed_lines，同樣需人工"
                        "檢查。防重複：每列委託書號若跟資料庫裡既有紀錄相同，"
                        "該筆視為重複（同一份對帳單被貼了兩次），整筆跳過不"
                        "寫入，歸入回傳的duplicates_skipped（不佔用add_sequence"
                        "序號）。經使用者確認貼入的文字無誤後才呼叫。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "國泰證券App「已成交」CSV對帳單原始文字，整段貼入。"},
            },
            "required": ["text"],
        },
    },
]


def _default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


# get_market_scan／run_market_scan 輸出瘦身共用的精簡欄位集合——只留 AI
# 使用者判斷「這檔值不值得再深入查」所需的最小欄位，完整欄位（high_price／
# high_date／revenue_period／pbr／dividend_yield／error 等）要看仍可用
# get_market_scan(verbose=true) 拿到，資料庫本身永遠存完整版。
_SIMPLE_MARKET_SCAN_FIELDS = ("code", "name", "market", "industry", "per",
                              "revenue_yoy", "peg", "drawdown_pct",
                              "excess_drawdown_pct", "current_price",
                              "meets_framework")


def _simplify_scan_row(row):
    return {field: row.get(field) for field in _SIMPLE_MARKET_SCAN_FIELDS}


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
            # PER/PBR/殖利率：官方優先＋FinMind備援（2026-08-01 來源選用
            # 邏輯稽核修正，見 fundamentals_client 模組docstring）。
            # monthly_revenue（近6個月原始營收）沒有對應官方多月來源，
            # 仍呼叫 finmind_client.get_fundamentals 取得——這裡把它的
            # valuation 覆寫成官方優先結果，其餘欄位（monthly_revenue／
            # errors／token_used）維持不動。⚠️已知取捨：finmind_client.
            # get_fundamentals 內部PER與營收是綁在一起的單一函式，即使
            # 官方估值查詢成功、不需要FinMind的PER資料，這裡仍會為了
            # monthly_revenue而連帶打一次FinMind TaiwanStockPER（其回傳
            # 值不會被使用）——沒有完全省下這次FinMind額度消耗，只是
            # 回傳給呼叫端的PER/PBR/殖利率數值本身是官方優先且正確的。
            stock_id = args["stock_id"]
            result = finmind_client.get_fundamentals(stock_id, data_dir=self.data_dir)
            valuation = fundamentals_client.get_valuation(stock_id, data_dir=self.data_dir)
            result["valuation"] = {"PER": valuation["per"], "PBR": valuation["pbr"],
                                   "dividend_yield": valuation["dividend_yield"]}
            result["valuation_data_source"] = valuation["data_source"]
            if valuation["error"]:
                result.setdefault("errors", [])
                result["errors"].append(valuation["error"])
            return result
        if name == "get_stock_info":
            return finmind_client.get_stock_info(
                stock_id=args.get("stock_id"), data_dir=self.data_dir)
        if name == "get_stock_price_history":
            return finmind_client.get_stock_price_history(
                args["stock_id"], start_date=args.get("start_date"),
                end_date=args.get("end_date"), data_dir=self.data_dir)
        if name == "get_revenue_yoy":
            # 完整多月序列（供趨勢判斷）維持直接呼叫 finmind_client，
            # 官方批次端點只有最新一期沒有多月歷史（見 fundamentals_client
            # 模組docstring，PO已確認範圍）。額外附上 latest：最新一期
            # 年增率改用官方優先＋FinMind備援（2026-08-01 來源選用邏輯
            # 稽核修正）。
            stock_id = args["stock_id"]
            result = finmind_client.get_revenue_yoy(stock_id, data_dir=self.data_dir)
            result["latest"] = fundamentals_client.get_revenue_yoy_latest(
                stock_id, data_dir=self.data_dir)
            return result
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
        if name == "save_stock_theme":
            return self.store.save_stock_theme(code=args["code"], theme=args["theme"])
        if name == "get_stock_theme":
            return self.store.get_stock_theme()
        if name == "check_auto_score":
            return review_engine.auto_score_review(
                args["code"], store=self.store, data_dir=self.data_dir)
        if name == "save_position_plan":
            return self.store.save_position_plan(
                code=args["code"], plan_amount=args["plan_amount"],
                note=args.get("note"))
        if name == "get_position_plan":
            return self.store.get_position_plan(code=args["code"])
        if name == "save_pending_verification":
            return self.store.save_pending_verification(
                judgment_text=args["judgment_text"],
                trigger_type=args["trigger_type"],
                trigger_condition_text=args["trigger_condition_text"],
                code=args.get("code"), theme=args.get("theme"),
                trigger_date=args.get("trigger_date"),
                target_value=args.get("target_value"),
                source_ref=args.get("source_ref"),
            )
        if name == "list_pending_verifications":
            return self.store.list_pending_verifications(
                status=args.get("status"), due_only=bool(args.get("due_only")))
        if name == "get_pending_verification":
            return self.store.get_pending_verification(id=args["id"])
        if name == "resolve_pending_verification":
            return self.store.resolve_pending_verification(
                id=args["id"], status=args["status"],
                resolution=args.get("resolution"))
        if name == "save_laoyutou_trade":
            return self.store.save_laoyutou_trade(
                code=args["code"], name=args.get("name"), action=args["action"],
                shares=args["shares"], price=args["price"], date=args["date"],
                reason=args.get("reason"), source_ref=args.get("source_ref"),
            )
        if name == "get_laoyutou_trades":
            return self.store.get_laoyutou_trades(
                code=args.get("code"), limit=int(args.get("limit") or 20))
        if name == "save_trade_ledger_entry":
            return self.store.save_trade_ledger_entry(
                code=args["code"], name=args.get("name"), action=args["action"],
                shares=args["shares"], price=args["price"], date=args["date"],
                add_sequence=args.get("add_sequence"), source_ref=args.get("source_ref"),
            )
        if name == "get_trade_ledger":
            return self.store.get_trade_ledger(args["code"])
        if name == "check_general_review":
            return review_engine.general_review(args["code"], data_dir=self.data_dir)
        if name == "check_strategy_review":
            return review_engine.strategy_specific_review(
                args["code"], args["strategy_id"], data_dir=self.data_dir)
        if name == "check_laoyutou_signal":
            return review_engine.laoyutou_signal_review(
                args["code"], store=self.store,
                lookback_days=int(args.get("lookback_days") or 14))
        if name == "check_position_control":
            return review_engine.position_control_suggestion(
                args["code"], store=self.store,
                confidence_level=args.get("confidence_level"))
        if name == "record_module_d_findings":
            return review_engine.auto_record_findings(
                args["code"], store=self.store, findings=args["findings"],
                date=args.get("date"))
        if name == "run_module_d_check":
            return review_engine.run_module_d_review(
                args["code"], store=self.store, data_dir=self.data_dir)
        if name == "parse_holdings_report":
            return holdings_parser.parse_holdings_report(args["text"])
        if name == "get_emerging_stock_valuation":
            return tpex_client.get_emerging_stock_valuation(
                args["stock_id"], data_dir=self.data_dir)
        if name == "screen_stocks":
            codes = screener.parse_codes(args["codes"])
            framework_id = args.get("framework_id")
            kwargs = {"data_dir": self.data_dir}
            if framework_id:
                framework = frameworks.get_framework(framework_id)
                if framework is None:
                    # 無效框架代號：直接回錯誤，不打任何 FinMind/TWSE/TPEx API。
                    return {"error": "未知框架：%s" % framework_id}
                kwargs["framework_id"] = framework_id
                kwargs["peg_threshold"] = framework.get("peg_max")
                kwargs["drawdown_min"] = framework.get("drawdown_min")
                kwargs["drawdown_max"] = framework.get("drawdown_max")
                kwargs["excess_drawdown_min"] = framework.get("excess_drawdown_min")
            # 顯式傳入的門檻覆寫框架預設值／screener 內建預設值。用 "in args"
            # 而不是 args.get()，才能區分「使用者沒給這個參數」（沿用預設）
            # 跟「使用者顯式傳了 null」（明確關掉這項條件，值要變成 None）——
            # args.get("peg_threshold") 兩種情況都回傳 None，分不出來。
            if "peg_threshold" in args:
                kwargs["peg_threshold"] = args["peg_threshold"]
            if "drawdown_min" in args:
                kwargs["drawdown_min"] = args["drawdown_min"]
            if "drawdown_max" in args:
                kwargs["drawdown_max"] = args["drawdown_max"]
            return screener.screen_stocks(codes, **kwargs)
        if name == "run_market_scan":
            framework_id = args.get("framework_id") or frameworks.default_framework_id()
            result = market_scan.run_scan(
                framework_id, data_dir=self.data_dir, trigger_source="manual")
            if "error" in result:
                return result
            saved = self.store.save_market_scan_run(
                framework_id, "manual", result["results"],
                result["candidate_count"], market_errors=result["market_errors"],
                total_scanned=result["total_scanned"],
                benchmark={"window_drawdown_pct": result.get("benchmark_drawdown_pct"),
                          "error": result.get("benchmark_error")})
            # 輸出瘦身：DB 已存完整候選（見上面 save_market_scan_run），這裡
            # 回給 MCP 呼叫端的只留 run 摘要＋符合框架的候選精簡欄位——現行
            # 直接吐全部候選全欄位會超過 MCP 回傳上限被截斷（get_market_scan
            # 同樣問題已實測 63,949 字元／2,486 行）。要完整清單改呼叫
            # get_market_scan(meets_only=false, limit=0, verbose=true)。
            meets_rows = [_simplify_scan_row(r) for r in result["results"]
                         if r.get("meets_framework")]
            return {
                "framework_id": framework_id,
                "trigger_source": result.get("trigger_source"),
                "run_id": saved["run_id"],
                "run_at": saved["run_at"],
                "candidate_count": result["candidate_count"],
                "meets_count": result["meets_count"],
                "total_scanned": result["total_scanned"],
                "market_errors": result["market_errors"],
                "benchmark_drawdown_pct": result.get("benchmark_drawdown_pct"),
                "benchmark_error": result.get("benchmark_error"),
                "meets": meets_rows,
                "note": ("已存入資料庫（run_id=%d），本回傳只含符合框架的候選"
                        "（精簡欄位）；要看全部候選（含未達門檻、完整欄位）"
                        "請呼叫 get_market_scan(framework_id=\"%s\", "
                        "meets_only=false, limit=0, verbose=true)。"
                        % (saved["run_id"], framework_id)),
            }
        if name == "get_market_scan":
            meets_only = bool(args.get("meets_only", True))
            limit = args.get("limit", 50)
            verbose = bool(args.get("verbose", False))
            result = self.store.get_latest_market_scan(
                framework_id=args.get("framework_id"), meets_only=meets_only, limit=limit)
            if not result.get("found"):
                return result
            total_results = result.get("total_results", len(result["results"]))
            returned = result.get("returned", len(result["results"]))
            rows = (result["results"] if verbose
                    else [_simplify_scan_row(r) for r in result["results"]])
            return {
                "found": True,
                "run": result["run"],
                "results": rows,
                # 帶回篩選條件與計數，避免 AI 使用者把截斷/精簡後的少數幾筆
                # 誤當成全部候選母體（omitted＝篩選後總筆數 - 這次實際回傳筆數）。
                "filters": {"framework_id": args.get("framework_id"),
                           "meets_only": meets_only, "limit": limit, "verbose": verbose},
                "total_results": total_results,
                "returned": returned,
                "omitted": max(total_results - returned, 0),
                "available_frameworks": [fw["id"] for fw in frameworks.FRAMEWORKS],
            }
        if name == "parse_and_save_laoyutou_trades":
            parsed = trade_text_parser.parse_laoyutou_trade_text(args["text"])
            return trade_text_parser.resolve_and_save_laoyutou_trades(
                parsed, store=self.store, date=args.get("date"),
                data_dir=self.data_dir)
        if name == "parse_and_save_trade_ledger":
            parsed = trade_ledger_parser.parse_trade_ledger_text(args["text"])
            return trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, store=self.store, data_dir=self.data_dir)
        if name == "parse_and_save_trade_csv":
            parsed = trade_ledger_parser.parse_trade_csv_text(args["text"])
            return trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, store=self.store, data_dir=self.data_dir)
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
