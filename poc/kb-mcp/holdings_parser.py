"""券商零股庫存表文字解析（FR-029 週邊工具）。

使用者常把券商 App/網站匯出的「零股庫存表」原始文字整段貼上；過去由 AI
逐列肉眼讀取代碼/名稱/股數再手動組 JSON 呼叫 save_holdings，容易看錯欄位
也浪費對話 token。本模組只做「解析」，純函式、不接觸資料庫、不呼叫
save_holdings——解析結果要先讓使用者確認過，才由呼叫端另行寫入
（人工確認關卡，刻意保留，不可省略）。

僅標準庫（re），與 finmind_client.py 同樣不丟例外、回傳 dict。
"""
import re

# 一整排 "-" 的分隔線（可能夾雜全形/半形皆為 "-"）。
_SEPARATOR_RE = re.compile(r"^-+$")

# 頁尾/合計/圖例列的固定開頭，直接跳過。
_SKIP_PREFIXES = ("總計:", "註:", "印表日期:")

# 表頭／次表頭列常見字樣，出現任一個即視為表頭列跳過（不是資料列）。
_HEADER_MARKERS = ("股票代號", "集 保", "融 資", "融 券", "庫 存", "本日評估")

# 資料列：代碼(4~6位數字) 空白 名稱(可能*前綴，無內部空白) 空白
# 股數(整數，可能有千分位逗號) 空白 其餘欄位(市值/收盤價，只含數字/逗號/
# 小數點/空白，不需要精確解析，只用來確認這確實是一列完整資料)。
_DATA_LINE_RE = re.compile(
    r"^(?P<code>\d{4,6})\s+(?P<name>\*?\S+)\s+(?P<shares>\d[\d,]*)(?P<rest>[\d,.\s]*)$"
)

_LOOKS_LIKE_DATA_RE = re.compile(r"^\d")


def parse_holdings_report(text):
    """解析零股庫存表原始文字，回傳 {rows, unparsed_lines, total_parsed}。

    rows 每筆只含 code/name/shares/is_emerging——市值與收盤價欄位不擷取
    （不同列有無融資融券時欄位對不齊，精確解析容易做錯，且 save_holdings
    用不到）。看起來像資料列（開頭是數字）但解析失敗的行會收進
    unparsed_lines，不靜默丟棄。
    """
    rows = []
    unparsed_lines = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SEPARATOR_RE.match(line):
            continue
        if line.startswith(_SKIP_PREFIXES):
            continue
        if any(marker in line for marker in _HEADER_MARKERS):
            continue

        match = _DATA_LINE_RE.match(line)
        if match:
            name = match.group("name")
            is_emerging = name.startswith("*")
            if is_emerging:
                name = name[1:]
            rows.append({
                "code": match.group("code"),
                "name": name,
                "shares": int(match.group("shares").replace(",", "")),
                "is_emerging": is_emerging,
            })
            continue

        if _LOOKS_LIKE_DATA_RE.match(line):
            unparsed_lines.append(raw_line)
        # 其餘不像資料列、也不符合已知跳過樣式的行（理論上不該出現在券商
        # 匯出格式裡）：不計入 rows 也不計入 unparsed_lines，避免雜訊。

    return {
        "rows": rows,
        "unparsed_lines": unparsed_lines,
        "total_parsed": len(rows),
    }
