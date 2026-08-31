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

# 資料列：代碼(4~6位數字) 空白 [*興櫃前綴] 名稱 [空白] 股數(整數，可能有
# 千分位逗號) 其餘欄位(市值/收盤價，只含數字/逗號/小數點/空白，不需要精確
# 解析，只用來確認這確實是一列完整資料)。
#
# 名稱跟股數之間「有沒有空白」實測會因來源不同而不一致：App/網站匯出通常
# 有空白（如「光洋科 150」），但從有密碼保護的PDF複製出來的文字常常沒有
# （如「台達電65」）——2026-08-31 PO提供的真實PDF擷取文字證實這點，且
# 原本 `(?P<name>\*?\S+)` 貪婪比對在沒空白時會把股數也吃進 name、同時把
# 後面的市值欄位誤判成 shares（矽下不叫、看起來像解析成功但數字全錯，
# 比對不出來比直接解析失敗更危險）。改用「name 用 lazy `[^\d]*?` 比對到
# 第一個數字字元出現為止」的方式界定股數起點，中間可有可無的空白都用
# `\s*` 容錯，兩種來源格式都能正確切開——已知限制：股票名稱本身若含
# 阿拉伯數字（例如某些ETF簡稱），會被誤判為股數邊界，目前實際看過的
# 個股清單沒有這種情況。
_DATA_LINE_RE = re.compile(
    r"^(?P<code>\d{4,6})\s+"
    r"(?P<star>\*?)"
    r"(?P<name>[^\s\d][^\d]*?)\s*"
    r"(?P<shares>\d[\d,]*)"
    r"(?P<rest>[\d,.\s]*)$"
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
            rows.append({
                "code": match.group("code"),
                "name": match.group("name"),
                "shares": int(match.group("shares").replace(",", "")),
                "is_emerging": bool(match.group("star")),
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
