"""PO自己的券商「交易明細表」批次文字解析（FR-056 週邊工具）。

跟 trade_text_parser.py（老芋頭進出批次）解析的是不同來源、寫入不同表：
這裡是PO自己券商App/網站匯出的「交易明細表」，寫入 trade_ledger（不是
laoyutou_trades）。名稱→代碼解析共用 stock_alias_resolver.py（同一套
快取查詢／FinMind整批比對規則，見該模組docstring），不重複實作。

輸入格式（PO 實際貼法）：
    交易日期: 115/07/22 - 115/07/29 頁次: 1
    ------------------------------------------------------------------
    交易日期 CD 股票名稱 股數 單價 手續費 交易稅 ... 委託書號
    ------------------------------------------------------------------
    115/07/22 OT賣 中美晶 50 242.50 4 36 12,125 12,085(付) k-0116-00
    115/07/22 集買 台達電 10 1,905.00 7 19,050 19,057(收) k-01NM-00
    ------------------------------------------------------------------
    合 計: 64 92 180,782 118,788(收)

跟老芋頭格式的關鍵差異：這份格式**每一列自己就有完整日期**（民國年，
115/07/22 這種格式），不像老芋頭格式需要從文字最前面猜一個共用日期套用
到整批——這份格式沒有「原因行」的概念，也不需要猜日期。

每一列組成：{日期} {CD} {股票名稱} {股數} {單價} ...(手續費/交易稅/證所稅/
融券手續費/利息/預收留置款/價金/淨收付金額(收/付)/委託書號，數量不固定，
不需要精確解析)... 。CD 組合「市場別＋買賣別」（OT=櫃買/興櫃、集=集中
市場；這次用不到市場別），只看字串裡含「買」還是「賣」判斷 action。

`parse_trade_ledger_text()` 是純函式（不碰資料庫、不呼叫外部API）；
`resolve_and_save_trade_ledger()` 負責名稱→代碼解析＋add_sequence計算＋
寫入，兩者分開方便獨立測試（同 holdings_parser.py／trade_text_parser.py
的兩階段設計）。

僅標準庫（re/datetime），不丟例外、回傳 dict。Python 3.9 相容。
"""
import re

import stock_alias_resolver

# 資料列：{日期 115/07/22}{空白}{CD 如 OT賣/集買}{空白}{股票名稱}{空白}
# {股數}{空白}{單價 含小數點}{其餘欄位，寬鬆吃掉，數量不固定，不精確解析}。
#   日期：民國年 3碼/月2碼/日2碼，斜線分隔
#   CD：市場別(OT/集/其他可能字樣，非空白字元) + 買賣別(買/賣)，這裡只
#       抓整個CD字串，判斷action時用「含買」或「含賣」判斷，不特別驗證
#       市場別字面（規則未知窮盡，容錯優先）
#   股票名稱：中文/英文，不含空白（可能含「-KY」字尾，如「世芯-KY」）
#   股數：整數，可能有千分位逗號
#   單價：一定含小數點（PO格式規則明講），可能有千分位逗號
#   其餘：手續費/交易稅/證所稅/融券手續費/利息/預收留置款/價金/
#       淨收付金額(收/付)/委託書號，欄位數量不固定，不精確解析，用
#       `.*` 寬鬆吃掉一整列剩餘部分即可（跟 holdings_parser.py 同精神）
_DATA_LINE_RE = re.compile(
    r"^(?P<date>\d{3}/\d{2}/\d{2})\s+"
    r"(?P<cd>\S*[買賣]\S*)\s+"
    r"(?P<name>[^\s\d][^\s]*?)\s+"
    r"(?P<shares>\d[\d,]*)\s+"
    r"(?P<price>\d[\d,]*\.\d+)\s+"
    r".*$"
)

# 表頭列／分隔線／頁首列／合計列的固定判斷樣式。
_SEPARATOR_RE = re.compile(r"^-+$")
_HEADER_LINE_RE = re.compile(r"^交易日期[:：]")  # 「交易日期: 115/07/22 - ... 頁次: 1」
_HEADER_MARKERS = ("交易日期", "CD", "股票名稱", "委託書號")
_TOTAL_LINE_PREFIXES = ("合 計", "合計", "合  計")

# 開頭是「民國年日期」但不符合完整資料列格式的行——視為疑似資料列但格式
# 跑掉，歸入 unparsed_lines 讓PO人工檢查，跟 holdings_parser.py／
# trade_text_parser.py 同一套「寧可歸入待查也不要靜默丟棄」精神。
_LOOKS_LIKE_DATA_RE = re.compile(r"^\d{3}/\d{2}/\d{2}\s")


def _roc_to_western(date_str):
    """民國年日期 115/07/22 → 西元 2026-07-22（年份+1911，月日補零）。"""
    roc_year, month, day = date_str.split("/")
    western_year = int(roc_year) + 1911
    return "%04d-%02d-%02d" % (western_year, int(month), int(day))


def parse_trade_ledger_text(text):
    """解析交易明細表原始文字，回傳
    {"trades": [...], "unparsed_lines": [...], "total_parsed": int}。

    每筆 trade：{"date"(西元YYYY-MM-DD), "action"("買"/"賣"), "name",
    "shares"(int), "price"(float), "raw_line"}。

    跳過：表頭列（含「交易日期」「CD」「股票名稱」「委託書號」等字樣）、
    分隔線（一整排"-"）、「交易日期:...頁次:...」開頭列、「合 計:」開頭列。
    """
    trades = []
    unparsed_lines = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SEPARATOR_RE.match(line):
            continue
        if _HEADER_LINE_RE.match(line):
            continue
        if line.startswith(_TOTAL_LINE_PREFIXES):
            continue
        if any(marker in line for marker in _HEADER_MARKERS):
            continue

        match = _DATA_LINE_RE.match(line)
        if match:
            cd = match.group("cd")
            action = "賣" if "賣" in cd else ("買" if "買" in cd else None)
            if action is None:
                # CD 欄位不含買也不含賣，格式不符預期，歸入待查而不是亂猜。
                unparsed_lines.append(raw_line)
                continue
            trades.append({
                "date": _roc_to_western(match.group("date")),
                "action": action,
                "name": match.group("name"),
                "shares": int(match.group("shares").replace(",", "")),
                "price": float(match.group("price").replace(",", "")),
                "raw_line": line,
            })
            continue

        if _LOOKS_LIKE_DATA_RE.match(line):
            unparsed_lines.append(raw_line)
        # 其餘不像資料列、也不符合已知跳過樣式的行：不計入 trades 也不計入
        # unparsed_lines，避免雜訊（同 holdings_parser.py 慣例）。

    return {
        "trades": trades,
        "unparsed_lines": unparsed_lines,
        "total_parsed": len(trades),
    }


def resolve_and_save_trade_ledger(parsed, store, data_dir=None, token=None):
    """把 parse_trade_ledger_text() 的解析結果做名稱→代碼解析＋add_sequence
    計算並批次寫入 trade_ledger。

    parsed：接受 parse_trade_ledger_text() 的完整回傳 dict（優先讀裡面的
    unparsed_lines 直接透傳），也容錯接受單純的 trades list。

    名稱→代碼解析：委派給 stock_alias_resolver.resolve_stock_codes()
    （整批只呼叫一次 finmind_client.get_stock_info，規則見該模組
    docstring）。查無代碼的名稱歸入 unresolved_names，不寫入（不可塞假
    代碼），比照 trade_text_parser.py 既有慣例。

    add_sequence 計算（本函式最重要的部分）：
    1. 依「代碼」分組，每組內的交易依 (date, 原始出現順序) 由舊到新排序
       ——同一天出現多筆時，tie-break 用原始出現順序（穩定排序），不判斷
       真實下單時間（PO明講不需要複雜判斷）。
    2. 對每個代碼，先呼叫 store.get_trade_ledger(code) 查「這批新資料
       之前」已經存在的歷史買進筆數（action="買" 且 add_sequence 不是
       None 的筆數），當作起始序號基準——例如已有2筆歷史買進，這批新
       資料的第一筆買進就該拿到序號3。
    3. 這批新資料裡，同一代碼的每一筆「買」依上述排序後順序，序號依序
       遞增（起始基準+1, +2, ...）。「賣」的 add_sequence 固定是 None
       （save_trade_ledger_entry() 既有邏輯會自動處理，這裡不特別設）。

    回傳 {"total_parsed", "saved"(每筆含code/name/action/shares/price/
    date/add_sequence), "unresolved_names", "unparsed_lines"}。
    """
    if isinstance(parsed, dict):
        trades = list(parsed.get("trades") or [])
        unparsed_lines = list(parsed.get("unparsed_lines") or [])
    else:
        trades = list(parsed or [])
        unparsed_lines = []

    # 名稱→代碼解析（整批只查一次快取/FinMind，共用邏輯見
    # stock_alias_resolver.py，不重寫 trade_text_parser.py 已有的一套）。
    resolved_codes, _unresolved = stock_alias_resolver.resolve_stock_codes(
        (trade.get("name") for trade in trades), store,
        data_dir=data_dir, token=token, alias_source="交易明細表批次解析自動比對")

    unresolved_names = []
    resolvable_trades = []  # (original_index, trade, code) — 保留原始出現順序供同日tie-break
    for idx, trade in enumerate(trades):
        name = trade.get("name")
        code = resolved_codes.get(name)
        if not code:
            unresolved_names.append({"name": name, "raw_line": trade.get("raw_line")})
            continue
        resolvable_trades.append((idx, trade, code))

    # 依代碼分組，組內依 (date, 原始出現順序) 排序——Python sort 穩定，
    # 用 (date, idx) 當排序鍵即可達成「同日按原始出現順序」的 tie-break。
    by_code = {}
    for idx, trade, code in resolvable_trades:
        by_code.setdefault(code, []).append((idx, trade))

    # 每個代碼的起始序號基準：查該代碼在「這批新資料之前」已存在的買進筆數。
    next_seq_by_code = {}
    for code in by_code:
        existing = store.get_trade_ledger(code)
        existing_buy_count = sum(
            1 for entry in existing["entries"]
            if entry.get("action") == "買" and entry.get("add_sequence") is not None)
        next_seq_by_code[code] = existing_buy_count + 1

    # 為了輸出時仍照原始文字順序回報（方便PO肉眼核對整批），先算好每筆
    # 的 add_sequence，再依原始 idx 排序輸出。
    add_sequence_by_idx = {}
    for code, group in by_code.items():
        group.sort(key=lambda item: (item[1]["date"], item[0]))
        seq = next_seq_by_code[code]
        for idx, trade in group:
            if trade["action"] == "買":
                add_sequence_by_idx[idx] = seq
                seq += 1
            else:
                add_sequence_by_idx[idx] = None  # 賣出不算加碼序號

    saved = []
    for idx, trade, code in resolvable_trades:
        add_sequence = add_sequence_by_idx.get(idx)
        store.save_trade_ledger_entry(
            code=code, name=trade.get("name"), action=trade["action"],
            shares=trade["shares"], price=trade["price"], date=trade["date"],
            add_sequence=add_sequence, source_ref="交易明細表批次解析")
        saved.append({
            "code": code, "name": trade.get("name"), "action": trade["action"],
            "shares": trade["shares"], "price": trade["price"],
            "date": trade["date"], "add_sequence": add_sequence,
        })

    return {
        "total_parsed": len(trades),
        "saved": saved,
        "unresolved_names": unresolved_names,
        "unparsed_lines": unparsed_lines,
    }
