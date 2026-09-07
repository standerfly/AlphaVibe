"""美股交易文字解析（contracts/mcp-tools.md 工具一
`parse_and_save_us_trade`，FR-002/003/004）。

**完全獨立於既有台股解析器**（`trade_text_parser.py`／
`trade_ledger_parser.py`）——不 import 它們，也不呼叫
`stock_alias_resolver.py`。美股不需要「名稱→代碼」解析：截圖辨識（Claude
在對話中讀圖轉文字，見 `research.md` §3）出來的就是股票代號本身
（例如「NET」），不是像台股那樣先出現中文股票名稱再查代碼。

輸入格式（本模組自訂，一行一筆交易）：
    {日期 YYYY-MM-DD} {代號} {買進|賣出} {股數}股 ${價格}

例：
    2026-08-05 NET 買進 10股 $298.40
    2026-08-06 CRWD 賣出 5股 $350.00
    2026-08-11 SNOW 買進 2.5股 $150.75      ← 支援小數股數（美股常見零股）
    2026-08-05 BRK.B 買進 10股 $410.00      ← 代號支援「.」分類股尾碼

    代號：1~6碼英文字母，大小寫皆可（自動正規化為大寫），可選「.字母」
        分類股尾碼（如 BRK.B）
    動詞：買進→action="buy"；賣出→action="sell"（USStockStore.
        VALID_TRADE_ACTIONS 只接受這兩個英文值，不是台股解析器慣用的
        中文'買'/'賣'——這裡直接映射成美股 store 期待的值，呼叫端不需要
        再轉換）
    股數：整數或小數，固定接「股」字（美股沒有台股的「張」單位，不需要
        單位換算）
    價格：固定接「$」字首（美元），整數或小數

跟其餘既有解析器一樣：僅標準庫（re），純函式不碰資料庫、不丟例外、
回傳 dict，`parse_us_trade_text()` 與 `parse_and_save_us_trade_text()`
兩階段設計方便獨立測試（同 trade_text_parser.py／trade_ledger_parser.py
既有慣例）。Python 3.9 相容。
"""
import re

# 代號：1~6碼英文字母，可選「.字母」分類股尾碼（如 BRK.B）。
# 動詞：買進／賣出，跟台股解析器一樣只認這兩個字面（no OCR/模糊比對，
#   截圖辨識已在呼叫這個函式之前由 Claude 完成，見模組 docstring）。
# 股數：整數或小數，固定接「股」；價格：固定接「$」，整數或小數。
_TRADE_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<ticker>[A-Za-z]{1,6}(?:\.[A-Za-z])?)\s+"
    r"(?P<verb>買進|賣出)\s+"
    r"(?P<shares>\d+(?:\.\d+)?)股\s+"
    r"\$(?P<price>\d+(?:\.\d+)?)\s*$"
)

_ACTION_MAP = {"買進": "buy", "賣出": "sell"}

# 開頭是日期格式（YYYY-MM-DD + 空白）但不符合完整交易行規則的行——視為
# 「疑似交易行但格式跑掉」，歸入 unparsed_lines 讓使用者人工檢查，不要
# 靜默丟棄（同 trade_ledger_parser.py::_LOOKS_LIKE_DATA_RE 的既有精神）。
_LOOKS_LIKE_TRADE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s")


def parse_us_trade_text(text):
    """解析美股交易文字，回傳
    {"trades": [...], "unparsed_lines": [...], "total_parsed": int}。

    每筆 trade：{"trade_date"(YYYY-MM-DD), "ticker"(大寫), "action"
    ("buy"/"sell"), "shares"(float), "price"(float), "raw_line"}。

    不像交易行、也不符合日期開頭樣式的行（例如使用者順手加的說明文字）
    一律安靜略過，不計入 trades 也不計入 unparsed_lines（同既有解析器
    對「非資料列、非已知跳過樣式」行的處理慣例）。
    """
    trades = []
    unparsed_lines = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _TRADE_LINE_RE.match(line)
        if match:
            trades.append({
                "trade_date": match.group("date"),
                "ticker": match.group("ticker").upper(),
                "action": _ACTION_MAP[match.group("verb")],
                "shares": float(match.group("shares")),
                "price": float(match.group("price")),
                "raw_line": line,
            })
            continue

        if _LOOKS_LIKE_TRADE_RE.match(line):
            unparsed_lines.append(raw_line)
        # 其餘不像交易行、也不是日期開頭的雜訊行：安靜略過。

    return {
        "trades": trades,
        "unparsed_lines": unparsed_lines,
        "total_parsed": len(trades),
    }


def parse_and_save_us_trade_text(text, store):
    """解析美股交易文字並直接寫入 `USStockStore`（contracts 工具一
    `parse_and_save_us_trade` 的核心邏輯，MCP server 只是薄薄包一層
    JSON-RPC dispatch，見 `us_stock_mcp_server.py`）。

    美股不需要台股解析器那套「名稱→代碼」resolve 步驟（見模組
    docstring），解析出的 ticker 可以直接餵給 `store.save_trade()`。

    FR-003「不論辨識完整度，一律經人工核對才落庫」：已成功解析的行照樣
    寫入，不因批次裡有格式錯誤的行就整批放棄；`parse_issues` 彙整
    `unparsed_lines`（正則不匹配）與寫入時的 `ValueError`（例如 shares/
    price 非正數，理論上不太會發生——正則已限制成正數格式——但仍防禦性
    處理，不讓單筆寫入例外中斷整批），供 agent 提示使用者修正後重新
    呼叫。

    回傳格式對應 contracts/mcp-tools.md 工具一：
    {"status": "ok", "saved_count": int, "trades": [...], "parse_issues": [...]}
    """
    parsed = parse_us_trade_text(text)
    parse_issues = list(parsed["unparsed_lines"])
    saved = []

    for trade in parsed["trades"]:
        try:
            saved_trade = store.save_trade(
                ticker=trade["ticker"],
                trade_date=trade["trade_date"],
                action=trade["action"],
                shares=trade["shares"],
                price=trade["price"],
            )
            saved.append(saved_trade)
        except ValueError as exc:
            parse_issues.append("%s（寫入失敗：%s）" % (trade["raw_line"], exc))

    return {
        "status": "ok",
        "saved_count": len(saved),
        "trades": saved,
        "parse_issues": parse_issues,
    }
