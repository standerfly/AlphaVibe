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

---

`parse_trade_csv_text()`（2026-07-31 新增，第四個貼文字快速輸入工具）：
國泰證券App還能匯出**另一種**「已成交」CSV格式對帳單，比上面的交易明細表
更乾淨（標準CSV、西元日期、明確買賣別文字），概念上仍是PO自己的交易紀錄
（同一張 trade_ledger 表），只是輸入格式不同，因此是這個模組的姊妹函式，
不另開檔案。

輸入格式（PO 實際貼法，逐行）：
    根據您篩選的結果，總計有4筆資料，當前資料為1-4筆，看更多請至國泰證券app查詢
    股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號
    弘塑,2026/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI
    矽格,2026/07/30,50,"8,622",現賣,173,"8,650",3,25,0,0,0,0,0,k09j3

第一行是變動的提示文字（筆數/內容會變），不寫死比對其內容，只要在還沒
看到表頭列之前一律當雜訊跳過。第二行起是**真正的CSV**（含千分位逗號的
數字欄位有雙引號包住，如`"-6,542"`）——用標準庫`csv`模組逐行解析（不用
正規表示式/split手刻），才能正確處理引號內的逗號。日期已是西元
`YYYY/MM/DD`，只需把`/`換成`-`，不需要民國年轉換。買賣別目前只認得
「現買」「現賣」（對應「買」「賣」）；其他字串（如融資買/融券賣，PO未
提供範例）歸入unparsed_lines讓PO人工檢查，不猜測。

輸出格式跟`parse_trade_ledger_text()`完全一致（trades/unparsed_lines/
total_parsed），可直接餵給`resolve_and_save_trade_ledger()`，不需要另
一套resolve/save邏輯。
"""
import csv
import re

import holdings_sync
import stock_alias_resolver

# 資料列：{日期 115/07/22}{空白}{CD 如 OT賣/集買}{CD跟股票名稱之間可能有
# 空白也可能沒有}{股票名稱}{股票名稱跟股數之間可能有空白也可能沒有}
# {股數}{空白}{單價 含小數點}{其餘欄位，寬鬆吃掉，數量不固定，不精確解析}。
#   日期：民國年 3碼/月2碼/日2碼，斜線分隔
#   CD：市場別(OT/集/興/其他可能字樣，非空白非數字字元) + 買賣別(買/賣)。
#       用 lazy `[^\s\d]*?[買賣]` 比對到第一個「買」或「賣」字元為止就停，
#       不再像舊版 `\S*[買賣]\S*` 貪婪吃到整個欄位（那樣在CD跟股票名稱
#       之間沒空白時會把股票名稱、股數都吃進cd，導致整列比對失敗）。
#       判斷action時用「含買」或「含賣」判斷，不特別驗證市場別字面
#       （規則未知窮盡，容錯優先）
#   股票名稱：中文/英文，不含數字（可能含「-KY」字尾，如「世芯-KY」）
#   股數：整數，可能有千分位逗號
#
#   股票名稱跟股數之間「有沒有空白」實測會因來源不同而不一致：既有測試
#   範例（PO App/網站匯出）都有空白（如「集買 台達電 10」），但2026-08-31
#   PO從有密碼保護的PDF複製出來的文字大多沒有空白（如「集買台達電10」，
#   CD跟名稱之間也沒空白）——原本的規則要求名稱跟股數間一定要有空白，
#   遇到沒空白的格式會整列判定失敗（安全但沒用）。改用「名稱用 lazy
#   `[^\d]*?` 比對到第一個數字字元出現為止」界定股數起點，中間可有可無
#   的空白用 `\s*` 容錯，兩種來源格式都能正確切開。已知限制：股票名稱
#   本身若含阿拉伯數字，會被誤判為股數邊界，目前實際看過的個股清單沒有
#   這種情況。
#   單價：一定含小數點（PO格式規則明講），可能有千分位逗號，股數跟單價
#       之間維持要求至少一個空白（兩者一律以空白分隔，沒看過反例）
#   其餘：手續費/交易稅/證所稅/融券手續費/利息/預收留置款/價金/
#       淨收付金額(收/付)/委託書號，欄位數量不固定，不精確解析，用
#       `.*` 寬鬆吃掉一整列剩餘部分即可（跟 holdings_parser.py 同精神）
_DATA_LINE_RE = re.compile(
    r"^(?P<date>\d{3}/\d{2}/\d{2})\s+"
    r"(?P<cd>[^\s\d]*?[買賣])\s*"
    r"(?P<name>[^\s\d][^\d]*?)\s*"
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
    "shares"(int), "price"(float), "raw_line", "order_ref"(str或None)}。

    order_ref（委託書號，2026-07-31新增，供防重複判斷用）：這一列最後一個
    非空白token（如「k-0116-00」）——不用正則結構化抽取每個中間欄位（手續
    費/交易稅/...數量不固定），直接取價格欄位之後剩餘文字的最後一個token
    即可。抽取失敗（例如price之後沒有剩餘文字）給None，不拋例外、不影響
    這一列其餘欄位的解析結果。

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
            try:
                trailing = line[match.end("price"):].strip()
                order_ref = trailing.split()[-1] if trailing else None
            except Exception:
                order_ref = None
            trades.append({
                "date": _roc_to_western(match.group("date")),
                "action": action,
                "name": match.group("name"),
                "shares": int(match.group("shares").replace(",", "")),
                "price": float(match.group("price").replace(",", "")),
                "raw_line": line,
                "order_ref": order_ref,
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


# ---------------------------------------------------------------------------
# parse_trade_csv_text()：國泰證券App「已成交」CSV格式對帳單（見模組docstring）
# ---------------------------------------------------------------------------

# 表頭列第一欄固定是「股名」，只認第一欄就足以判斷是不是表頭列（容錯優先，
# 不要求其餘14欄逐字比對——欄位順序/名稱萬一App改版微調也還能繼續動作）。
_CSV_HEADER_FIRST_FIELD = "股名"

# 買賣別目前只看過這兩種值。其他字串（融資買/融券賣等，PO未提供範例）一律
# 歸入unparsed_lines讓PO人工檢查，不可靜默猜測（同模組docstring規則）。
_CSV_ACTION_MAP = {"現買": "買", "現賣": "賣"}

# 日期欄位必須是西元 YYYY/MM/DD（4碼年/2碼月/2碼日），格式跑掉的行歸入
# unparsed_lines，不硬解析出可能錯誤的日期。
_CSV_DATE_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def parse_trade_csv_text(text):
    """解析國泰證券App「已成交」CSV格式對帳單原始文字，回傳格式跟
    parse_trade_ledger_text() 完全一致：
    {"trades": [...], "unparsed_lines": [...], "total_parsed": int}。

    每筆 trade：{"date"(西元YYYY-MM-DD), "action"("買"/"賣"), "name",
    "shares"(int), "price"(float), "raw_line", "order_ref"(str或None)}。

    order_ref（委託書號，2026-07-31新增，供防重複判斷用）：CSV最後一欄
    （索引14，見模組docstring欄位順序），取值失敗（欄位數不足14／該欄
    為空字串）給None，不拋例外。

    逐行處理（不是把整段文字一次丟給csv.reader）：先用strip()去頭尾空白，
    空行跳過；還沒看到表頭列（第一欄=="股名"）之前的行一律當雜訊跳過
    （含PO App產生的變動提示文字，見模組docstring，不寫死比對其內容）；
    看到表頭列本身也跳過，之後每一行才用`csv.reader([line])`解析成欄位
    （正確處理引號內的千分位逗號，如`"-6,542"`）。

    資料列欄位不足、買賣別不是「現買」/「現賣」、或日期格式不是
    西元YYYY/MM/DD，都歸入unparsed_lines（保留原始行文字），不猜測。
    """
    trades = []
    unparsed_lines = []
    header_seen = False

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        row = next(csv.reader([line]), [])
        if not row:
            continue

        if not header_seen:
            if row[0].strip() == _CSV_HEADER_FIRST_FIELD:
                header_seen = True
            # 表頭列本身、以及表頭列出現前的任何雜訊（含變動提示文字）都
            # 在這裡被跳過，不進 unparsed_lines（同 parse_trade_ledger_text()
            # 對表頭/分隔線/頁首列的既有處理精神）。
            continue

        # 欄位順序：股名(0) 日期(1) 成交股數(2) 淨收付金額(3) 買賣別(4)
        # 成交價(5)，之後欄位（成本/手續費/交易稅/...）不需要精確解析。
        if len(row) < 6:
            unparsed_lines.append(raw_line)
            continue

        action = _CSV_ACTION_MAP.get(row[4].strip())
        date_str = row[1].strip()
        if action is None or not _CSV_DATE_RE.match(date_str):
            unparsed_lines.append(raw_line)
            continue

        try:
            shares = int(row[2].strip().replace(",", ""))
            price = float(row[5].strip().replace(",", ""))
        except ValueError:
            unparsed_lines.append(raw_line)
            continue

        try:
            order_ref = row[14].strip() or None if len(row) > 14 else None
        except Exception:
            order_ref = None

        trades.append({
            "date": date_str.replace("/", "-"),
            "action": action,
            "name": row[0].strip(),
            "shares": shares,
            "price": price,
            "raw_line": line,
            "order_ref": order_ref,
        })

    return {
        "trades": trades,
        "unparsed_lines": unparsed_lines,
        "total_parsed": len(trades),
    }


def resolve_and_save_trade_ledger(parsed, store, data_dir=None, token=None):
    """把 parse_trade_ledger_text() 或 parse_trade_csv_text() 的解析結果
    做名稱→代碼解析＋add_sequence計算並批次寫入 trade_ledger（兩個解析
    函式輸出格式完全一致，共用同一套resolve/save邏輯，不重寫）。

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

    委託書號防重複（2026-07-31新增，PO明確要求）：名稱解析成功後、算
    add_sequence／寫入之前，逐筆檢查 trade.get("order_ref")——有值且
    store.trade_ledger_order_ref_exists(order_ref) 為True，代表資料庫裡
    已經有這筆交易（同一份對帳單／交易明細表被貼了兩次，或同一筆交易
    出現在不同批次貼上的文字裡），整筆跳過：不寫入、也不佔用add_sequence
    序號（因為它根本沒被寫入這批，序號基準只該反映「真的寫入」的筆
    數）。沒有order_ref（None，例如來源格式抽取失敗）的交易不做任何
    防重複檢查、照常寫入——刻意保守，寧可放行也不要誤判合法交易為重複。
    這個檢查只比對「這批新資料之前」已存在的DB列，同一批次內部若出現
    重複order_ref不會被互相攔下（已知邊界情況，見呼叫端docstring）。

    回傳 {"total_parsed", "saved"(每筆含code/name/action/shares/price/
    date/add_sequence/order_ref), "unresolved_names", "unparsed_lines",
    "duplicates_skipped"(每筆含code/name/action/shares/price/date/
    order_ref，被防重複機制擋下、未寫入的交易), "holdings_sync"}。

    holdings_sync（2026-09-02新增，FR-056週邊）：`saved` 這批真的寫入
    trade_ledger 的交易，會自動同步反映到 holdings 持股快照（見
    holdings_sync.py::sync_holdings_from_trades()）。`saved` 為空（整批
    都查無代碼或被防重複擋下）時不觸發，這個鍵是
    `{"synced": False, ...}`。同步失敗**不影響** trade_ledger 本身是否
    寫入成功——交易紀錄已經在上面的迴圈逐筆 commit 過了，這裡只是把
    例外訊息放進 `holdings_sync.error`，不重新拋出，避免「交易明明存
    成功了，卻因為持股同步這個附加動作出錯，讓呼叫端誤以為整個匯入失
    敗」。
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

    # 委託書號防重複：有order_ref且DB裡已存在同一order_ref的交易整筆
    # 跳過，且不進入下面的add_sequence計算基礎（見本函式docstring）。
    duplicates_skipped = []
    deduped_trades = []
    for idx, trade, code in resolvable_trades:
        order_ref = trade.get("order_ref")
        if order_ref and store.trade_ledger_order_ref_exists(order_ref):
            duplicates_skipped.append({
                "code": code, "name": trade.get("name"), "action": trade.get("action"),
                "shares": trade.get("shares"), "price": trade.get("price"),
                "date": trade.get("date"), "order_ref": order_ref,
            })
            continue
        deduped_trades.append((idx, trade, code))
    resolvable_trades = deduped_trades

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
        order_ref = trade.get("order_ref")
        store.save_trade_ledger_entry(
            code=code, name=trade.get("name"), action=trade["action"],
            shares=trade["shares"], price=trade["price"], date=trade["date"],
            add_sequence=add_sequence, source_ref="交易明細表批次解析",
            order_ref=order_ref)
        saved.append({
            "code": code, "name": trade.get("name"), "action": trade["action"],
            "shares": trade["shares"], "price": trade["price"],
            "date": trade["date"], "add_sequence": add_sequence,
            "order_ref": order_ref,
        })

    # 持股快照自動同步（2026-09-02新增）：sync_holdings_from_trades()
    # 自己在 saved 為空時就回傳 synced=False、不觸發，這裡不重複判斷；
    # 只包一層 try/except——同步本身失敗不影響 trade_ledger 已經寫入
    # 成功這件事，錯誤放進 holdings_sync.error，不重新拋出。
    try:
        sync_result = holdings_sync.sync_holdings_from_trades(store, saved)
    except Exception as exc:  # noqa: BLE001 — 見上方 docstring 取捨說明
        sync_result = {"synced": False, "error": str(exc)}

    return {
        "total_parsed": len(trades),
        "saved": saved,
        "unresolved_names": unresolved_names,
        "unparsed_lines": unparsed_lines,
        "duplicates_skipped": duplicates_skipped,
        "holdings_sync": sync_result,
    }
