"""從 Gmail 唯讀取得國泰日對帳單信件（specs/009 research R1、FR-001、FR-012）。

- `imap.gmail.com:993` SSL，應用程式密碼登入；`EXAMINE`（唯讀選取，信件不會被標成已讀）
  開「所有郵件」。
- Gmail 擴充搜尋 `X-GM-RAW` 先在伺服器端以寄件人過濾，再**只抓 header**
  （`BODY.PEEK[HEADER.FIELDS ...]`）在本機嚴格驗證寄件人地址與主旨（RFC 2047 解碼後
  完全相等），通過的才用 `BODY.PEEK[]` 取整封信——其他信件的內容完全不會被讀取。
- 回傳依日期舊到新排序（FR-013）。

`imap_factory` 可注入（測試用假物件）；預設建立 `imaplib.IMAP4_SSL`。僅標準庫，Python 3.9 相容。
"""
import email
import email.policy
import email.utils
import imaplib
import re

SENDER = "e-notification@ebill1.cathaysec.com.tw"
SUBJECT = "國泰綜合證券日對帳單"
IMAP_HOST = "imap.gmail.com"
# 「所有郵件」在不同語系介面下名稱不同；以 \All 特殊用途旗標找，找不到才用英文預設名。
_DEFAULT_ALL_MAIL = '"[Gmail]/All Mail"'
_BODY_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


class MailboxError(Exception):
    """信箱連線、登入或搜尋失敗；訊息不含密碼。"""


def _default_factory():
    return imaplib.IMAP4_SSL(IMAP_HOST, 993)


def _find_all_mail(conn):
    try:
        typ, data = conn.list()
    except imaplib.IMAP4.error:
        return _DEFAULT_ALL_MAIL
    for raw in data or []:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if "\\All" in line:
            m = re.search(r'"[^"]*"\s+("?[^"]*"?)$', line) or re.search(r"\s(\S+)$", line)
            if m:
                name = m.group(1)
                return name if name.startswith('"') else '"%s"' % name
    return _DEFAULT_ALL_MAIL


def _fetch_parts(conn, uid, spec):
    typ, data = conn.uid("FETCH", uid, "(%s)" % spec)
    if typ != "OK":
        return None
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            return item[1]
    return None


def _header_ok(msg):
    from_hdr = msg.get("From")
    addresses = getattr(from_hdr, "addresses", None) or ()
    if len(addresses) == 1:
        addr = addresses[0].addr_spec
    else:
        _, addr = email.utils.parseaddr(str(from_hdr or ""))
    subject = str(msg.get("Subject", "")).strip()
    return addr.lower() == SENDER and subject == SUBJECT


def _pdf_attachment(msg):
    for part in msg.walk():
        filename = part.get_filename() or ""
        if part.get_content_type() == "application/pdf" or filename.lower().endswith(".pdf"):
            payload = part.get_payload(decode=True)
            if payload:
                return payload
    return None


def _statement_date_hint(msg):
    """內文「這是您YYYY/MM/DD的證券電子對帳單」的日期，取不到時用 Date 標頭。"""
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            try:
                body = part.get_content()
            except (LookupError, ValueError):
                continue
            m = _BODY_DATE_RE.search(body or "")
            if m:
                return "%04d-%02d-%02d" % tuple(int(x) for x in m.groups())
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
        return dt.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def fetch_statements(address, app_password, days=14, imap_factory=None):
    """回傳 `[{message_id, date_hint, pdf_bytes}]`（依日期舊到新）。

    沒有 PDF 附件的對帳單信件 pdf_bytes 為 None（呼叫端記為失敗）。
    """
    factory = imap_factory or _default_factory
    try:
        conn = factory()
        conn.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as e:
        raise MailboxError("Gmail 登入失敗（請確認 IMAP 已啟用、應用程式密碼正確）：%s"
                           % type(e).__name__)
    try:
        typ, _ = conn.select(_find_all_mail(conn), readonly=True)
        if typ != "OK":
            raise MailboxError("無法開啟「所有郵件」")
        query = '"from:%s newer_than:%dd"' % (SENDER, int(days))
        typ, data = conn.uid("SEARCH", "X-GM-RAW", query)
        if typ != "OK":
            raise MailboxError("Gmail 搜尋失敗")
        uids = (data[0] or b"").split() if data else []
        results = []
        for uid in uids:
            raw_header = _fetch_parts(
                conn, uid, "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)]")
            if not raw_header:
                continue
            header = email.message_from_bytes(raw_header, policy=email.policy.default)
            if not _header_ok(header):
                continue
            raw = _fetch_parts(conn, uid, "BODY.PEEK[]")
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            message_id = str(msg.get("Message-ID") or header.get("Message-ID") or "").strip()
            if not message_id:
                message_id = "uid:%s" % (uid.decode() if isinstance(uid, bytes) else uid)
            results.append({"message_id": message_id,
                            "date_hint": _statement_date_hint(msg),
                            "pdf_bytes": _pdf_attachment(msg)})
        results.sort(key=lambda r: r["date_hint"] or "")
        return results
    except (imaplib.IMAP4.error, OSError) as e:
        raise MailboxError("讀取信件失敗：%s" % type(e).__name__)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
