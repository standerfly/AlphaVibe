"""國泰綜合證券（台股）日對帳單文字解析（specs/009 research R8、FR-003、FR-009）。

輸入是 `statement_pdf.extract_text()`（`pdftotext -layout`）的輸出；格式紀錄見
`docs/spec-intake/broker-statement-import/raw/src-002-*`。PDF 有三個區塊：

- 交割金額：第一個西元日期 `YYYY/MM/DD` 是成交日＝對帳單日期。
- 交易明細：每筆成交一列「名稱 類別 股數 單價 成交金額 手續費 交易稅 …… 委託書號」，
  類別＝市場別（集／OT／興）＋買賣別；交易稅可能帶 `*`（千分之一）；委託書號在行尾。
- 庫存明細：每檔一列「代號 名稱 收盤價(可帶▲▼、可為0) 集保股數 集保市值 ……」，
  **沒有平均成本**。

以「欄位順序＋數字樣式」辨識，不依賴固定欄寬（真實版面需在 PO 的 Mac 上以
`statement_import.py --from-file <PDF> --dry-run` 確認）。寧可整份判定格式錯誤也不猜：
在交易明細區塊裡看起來像成交（有類別＋數字）卻無法完整解析的列、庫存明細區塊裡
以代號開頭卻無法解析的列、缺少庫存明細區塊或對帳單日期，一律拋 `StatementFormatError`，
由呼叫端整份不寫入。沒有成交的對帳單（無交易明細區塊或區塊內無成交）是合法的。

純函式、僅標準庫，Python 3.9 相容。
"""
import re

SECTION_SETTLEMENT = "交割金額"
SECTION_TRADES = "交易明細"
SECTION_HOLDINGS = "庫存明細"

_DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
_NUM = r"\d[\d,]*(?:\.\d+)?"
# 名稱可含 -KY 等字尾但不含數字；類別＝集/OT/興＋（零股等最多兩字）＋買/賣。
_TRADE_RE = re.compile(
    r"^(?P<name>[^\s\d][^\d]*?)\s*"
    r"(?P<cd>(?:集|OT|興)[^\s\d]{0,2}?[買賣])\s+"
    r"(?P<shares>\d[\d,]*)\s+"
    r"(?P<price>%s)\s+"
    r"(?P<amount>%s)\s+"
    r"(?P<fee>%s)\s+"
    r"\*?(?P<tax>%s)\*?\s+"
    r".*?(?P<ref>[A-Za-z][0-9A-Za-z\-]{4,10})$" % (_NUM, _NUM, _NUM, _NUM))
_LOOKS_LIKE_TRADE_RE = re.compile(r"(?:集|OT|興)[^\s\d]{0,2}?[買賣]\s*\d")
_HOLDING_RE = re.compile(
    r"^(?P<code>\d{4}[0-9A-Z]{0,2})\s+"
    r"(?P<name>\S+?)\s+"
    r"[▲▼△▽+\-]?\s*(?P<close>%s)\s+"
    r"(?P<shares>\d[\d,]*)\s+"
    r"(?P<value>%s)(?:\s.*)?$" % (_NUM, _NUM))
_LOOKS_LIKE_HOLDING_RE = re.compile(r"^\d{4}[0-9A-Z]{0,2}\s")
_SUMMARY_MARKERS = ("合計", "總計", "合 計")


class StatementFormatError(ValueError):
    """對帳單格式無法辨識（可能改版）；訊息不含個資。"""


def _num(s):
    return float(s.replace(",", ""))


def _int(s):
    return int(s.replace(",", ""))


def _split_sections(lines):
    sections = {}
    current = None
    for line in lines:
        stripped = line.strip()
        for title in (SECTION_SETTLEMENT, SECTION_TRADES, SECTION_HOLDINGS):
            if stripped.startswith(title):
                current = title
                sections.setdefault(current, [])
                stripped = stripped[len(title):].strip()
                break
        if current is not None and stripped:
            sections[current].append(stripped)
    return sections


def _statement_date(sections, fallback_date):
    for line in sections.get(SECTION_SETTLEMENT, []):
        m = _DATE_RE.search(line)
        if m:
            return "%s-%s-%s" % m.groups()
    if fallback_date:
        return fallback_date
    raise StatementFormatError("找不到對帳單日期（交割金額區塊）")


def _parse_trades(lines, statement_date):
    trades = []
    for line in lines:
        if any(k in line for k in _SUMMARY_MARKERS):
            continue
        m = _TRADE_RE.match(line)
        if not m:
            if _LOOKS_LIKE_TRADE_RE.search(line):
                raise StatementFormatError("交易明細有無法辨識的成交列")
            continue
        cd = m.group("cd")
        trade = {
            "date": statement_date,
            "name": m.group("name").strip(),
            "market": cd[:2] if cd.startswith("OT") else cd[0],
            "action": "買" if cd.endswith("買") else "賣",
            "shares": _int(m.group("shares")),
            "price": _num(m.group("price")),
            "amount": _num(m.group("amount")),
            "fee": _num(m.group("fee")),
            "tax": _num(m.group("tax")),
            "order_ref": m.group("ref"),
        }
        if trade["shares"] <= 0 or trade["price"] <= 0:
            raise StatementFormatError("交易明細的股數或單價不合理")
        trades.append(trade)
    return trades


def _parse_holdings(lines):
    holdings = []
    for line in lines:
        if any(k in line for k in _SUMMARY_MARKERS):
            continue
        m = _HOLDING_RE.match(line)
        if not m:
            if _LOOKS_LIKE_HOLDING_RE.match(line):
                raise StatementFormatError("庫存明細有無法辨識的持股列")
            continue
        holdings.append({"code": m.group("code"), "name": m.group("name"),
                         "shares": _int(m.group("shares"))})
    return holdings


def parse_daily_statement(text, fallback_date=None):
    """回傳 {"statement_date": "YYYY-MM-DD", "trades": [...], "holdings": [...]}。

    fallback_date：交割金額區塊沒有日期時（例如無成交的對帳單）改用的日期，
    通常是信件內文／Date 標頭的日期；兩者都沒有＝格式錯誤。
    """
    lines = (text or "").replace("\f", "\n").splitlines()
    sections = _split_sections(lines)
    if SECTION_HOLDINGS not in sections:
        raise StatementFormatError("找不到庫存明細區塊")
    statement_date = _statement_date(sections, fallback_date)
    trades = _parse_trades(sections.get(SECTION_TRADES, []), statement_date)
    if SECTION_TRADES not in sections and any(
            _LOOKS_LIKE_TRADE_RE.search(l) for l in sections.get(SECTION_SETTLEMENT, [])):
        raise StatementFormatError("有成交資料但找不到交易明細區塊")
    holdings = _parse_holdings(sections[SECTION_HOLDINGS])
    return {"statement_date": statement_date, "trades": trades, "holdings": holdings}
