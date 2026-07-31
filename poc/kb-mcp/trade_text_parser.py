"""老芋頭（PO信任的資深投資朋友／導師）進出批次文字解析（FR-044 週邊工具）。

PO 貼上老芋頭進出紀錄時格式固定、量大（常一次十幾二十筆），過去要靠 AI
逐行理解再一筆筆呼叫 save_laoyutou_trade，慢又容易看錯欄位。這裡用程式
解析取代逐行人工理解，PO 明確要求要快——格式固定就該用程式解析。

輸入格式（PO 實際貼法，2026-07-30 澄清）：
    20260729                          ← 第一行固定是8位數日期 YYYYMMDD，
    殺估值，獲利跟不上股價，清倉換股      代表整批交易的日期
    365賣出500股聯鈞（出清）            ← 交易行：價格+動詞+股數+單位+名稱+可選註記
    280賣出2張政美（出清）
                                       ← 空行清空目前的原因，之後的交易不再套用
    176買進2張揚博

`parse_laoyutou_trade_text()` 是純函式（不碰資料庫、不呼叫外部API），
`resolve_and_save_laoyutou_trades()` 負責名稱→代碼解析＋寫入，兩者分開
方便獨立測試（同 holdings_parser.py／save_holdings 的兩階段設計）。

僅標準庫（re/datetime），與 holdings_parser.py 同樣不丟例外、回傳 dict。
Python 3.9 相容。

名稱→代碼解析（2026-07-30 抽出，見 stock_alias_resolver.py）：
trade_ledger_parser.py（FR-056 PO自己的交易明細表解析）需要一模一樣的
解析邏輯，故抽成共用模組，這裡改為呼叫 stock_alias_resolver.resolve_
stock_codes()，不再自己實作。
"""
import datetime
import re

# 保留 import：測試（tests/test_trade_text_parser.py、
# tests/test_report_server.py）會 patch
# `trade_text_parser.finmind_client.get_stock_info` 來避免打真的 FinMind
# API——這是同一個 finmind_client 模組物件，stock_alias_resolver.py 內部
# 呼叫的也是它，patch 在這裡一樣有效，不需要另外改測試。
import finmind_client  # noqa: F401
import stock_alias_resolver

# 交易行：{價格}{動詞}{股數}{單位}{名稱}{可選括號註記}
#   價格：整數或小數
#   動詞：賣出→賣；買進／買回／回補→買（三個買進動詞字面不同，語意都是買）
#   股數：整數；單位「張」要乘1000，「股」維持原數字
#   名稱：不含空白/括號的字元（可能是中文＋英文字母，如「環宇KY」）
#   括號註記：可選，全形/半形括號皆接受（範例只出現全形，半形一併支援
#   是因為判斷成本為零，不算「處理範例外的格式變體」）
_TRADE_LINE_RE = re.compile(
    r"^(?P<price>\d+(?:\.\d+)?)"
    r"(?P<verb>賣出|買進|買回|回補)"
    r"(?P<shares>\d+)"
    r"(?P<unit>股|張)"
    r"(?P<name>[^\s()（）]+?)"
    r"(?:[（(](?P<note>[^）)]*)[）)])?$"
)

# 開頭是數字、但不符合完整交易行規則的行——視為「疑似交易行但格式跑掉」，
# 歸入 unparsed_lines 讓PO人工檢查，不要誤判成原因行（原因行是敘述文字，
# 通常不會以數字開頭）。跟 holdings_parser._LOOKS_LIKE_DATA_RE 是同一套
# 判斷邏輯。
_LOOKS_LIKE_TRADE_RE = re.compile(r"^\d")

# 批次文字第一個非空行若符合8位數字，視為這整批交易的日期（YYYYMMDD）。
_DATE_LINE_RE = re.compile(r"^\d{8}$")


def parse_laoyutou_trade_text(text):
    """解析老芋頭進出批次文字，回傳
    {"date": str|None, "trades": [...], "unparsed_lines": [...], "total_parsed": int}。

    date：文字第一個非空行若符合8位數 YYYYMMDD 格式，解析成 YYYY-MM-DD；
    否則為 None（不會把這行誤判成原因行或交易行，日期行一律從後續解析中
    排除）。

    每筆 trade：{"price", "action"("買"/"賣"), "shares", "name",
    "note"(括號註記或None), "reason"(當時生效的原因行文字或None),
    "raw_line"}。reason 與 note 分開存，組合方式留給呼叫端
    （resolve_and_save_laoyutou_trades 會把兩者組合成 laoyutou_trades.reason）。
    """
    lines = (text or "").splitlines()

    # 找文字裡第一個非空行，只檢查這一行是否為日期行——不是逐行檢查，
    # 避免中間某行剛好是8位數字（理論上不太可能是股數，但保守起見只信任
    # 「文字最前面」這個PO明確講過的位置）。
    date_line_idx = None
    parsed_date = None
    for i, raw in enumerate(lines):
        if raw.strip():
            candidate = raw.strip()
            if _DATE_LINE_RE.match(candidate):
                parsed_date = "%s-%s-%s" % (candidate[0:4], candidate[4:6], candidate[6:8])
                date_line_idx = i
            break  # 只看第一個非空行，不管符不符合日期格式都到此為止

    trades = []
    unparsed_lines = []
    current_reason = None

    for idx, raw_line in enumerate(lines):
        if idx == date_line_idx:
            continue  # 已判定為日期行，跳過，不進入原因/交易判斷

        line = raw_line.strip()
        if not line:
            current_reason = None  # 空行清空目前套用中的原因
            continue

        match = _TRADE_LINE_RE.match(line)
        if match:
            verb = match.group("verb")
            action = "賣" if verb == "賣出" else "買"
            shares = int(match.group("shares"))
            if match.group("unit") == "張":
                shares *= 1000
            trades.append({
                "price": float(match.group("price")),
                "action": action,
                "shares": shares,
                "name": match.group("name"),
                "note": match.group("note"),
                "reason": current_reason,
                "raw_line": line,
            })
            continue

        if _LOOKS_LIKE_TRADE_RE.match(line):
            unparsed_lines.append(raw_line)
            continue

        # 非空行、不像交易行、也不是日期行 → 原因行，套用到後續交易，
        # 直到空行或下一個原因行為止。
        current_reason = line

    return {
        "date": parsed_date,
        "trades": trades,
        "unparsed_lines": unparsed_lines,
        "total_parsed": len(trades),
    }


def resolve_and_save_laoyutou_trades(parsed_trades, store, date=None,
                                     data_dir=None, token=None):
    """把 parse_laoyutou_trade_text() 的解析結果做名稱→代碼解析並批次寫入
    laoyutou_trades。

    parsed_trades：接受 parse_laoyutou_trade_text() 的完整回傳 dict
    （優先讀裡面的 date／unparsed_lines 直接透傳），也容錯接受單純的
    trades list（此時沒有 date／unparsed_lines 可透傳，等同呼叫端自行
    組出的清單）。

    date 參數語意（2026-07-30 澄清後調整）：優先序＝
    文字裡解析出的日期(parsed_trades["date"]) > 這裡傳入的 date 參數 >
    今天。PO澄清批次文字第一行固定會帶日期，正常情況都會走第一種；
    保留後兩種是給沒有日期行的輸入或測試手動指定日期用。

    名稱→代碼解析：委派給 stock_alias_resolver.resolve_stock_codes()（整批
    只呼叫一次 finmind_client.get_stock_info，不逐筆查；規則見該模組
    docstring）。這裡逐筆比對 resolve_stock_codes() 回傳的 {name: code}——
    查無代碼的名稱歸入 unresolved_names，不呼叫 save_laoyutou_trade
    （code 是必填，不可塞假值）。
    """
    if isinstance(parsed_trades, dict):
        trades = parsed_trades.get("trades") or []
        unparsed_lines = list(parsed_trades.get("unparsed_lines") or [])
        parsed_date = parsed_trades.get("date")
    else:
        trades = list(parsed_trades or [])
        unparsed_lines = []
        parsed_date = None

    date = parsed_date or date or datetime.date.today().isoformat()

    # 名稱→代碼解析：共用邏輯見 stock_alias_resolver.py（原本在這裡自己
    # 實作，2026-07-30 抽出讓 trade_ledger_parser.py 也能重用，不重複
    # 寫一次同樣的快取查詢／FinMind整批比對／寫回快取流程）。
    resolved_codes, _unresolved = stock_alias_resolver.resolve_stock_codes(
        (trade.get("name") for trade in trades), store,
        data_dir=data_dir, token=token, alias_source="老芋頭進出批次解析自動比對")

    saved = []
    unresolved_names = []
    for trade in trades:
        name = trade.get("name")
        code = resolved_codes.get(name)
        if not code:
            unresolved_names.append({"name": name, "raw_line": trade.get("raw_line")})
            continue
        reason_parts = [p for p in (trade.get("reason"), trade.get("note")) if p]
        reason = "；".join(reason_parts) if reason_parts else None
        store.save_laoyutou_trade(
            code=code, name=name, action=trade["action"],
            shares=trade["shares"], price=trade["price"], date=date,
            reason=reason, source_ref="老芋頭進出批次解析")
        saved.append({"code": code, "name": name, "action": trade["action"],
                      "shares": trade["shares"], "price": trade["price"]})

    return {
        "total_parsed": len(trades),
        "saved": saved,
        "unresolved_names": unresolved_names,
        "unparsed_lines": unparsed_lines,
    }
