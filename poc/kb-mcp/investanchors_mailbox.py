"""定錨通知信：只取「有沒有新信」的線索（010 T012、research R1／R2）。

通知信**只當觸發**：只取 Message-ID 與寄達時間，**不讀信件本文、不解析、不記錄信中的連結與標題**
（連結是每位收件人的點擊追蹤轉址，不可跟隨、不可解碼）。因此只抓標頭（`BODY.PEEK[HEADER.FIELDS …]`），
信件內容根本不會被讀進來；唯讀、不標已讀。

沿用 `statement_mailbox.py` 的骨架（IMAP4_SSL、`select(readonly=True)`、`X-GM-RAW`、`_find_all_mail`、
`_fetch_parts`），不改 009 的常數。Gmail 憑證沿用 `stnd-statement-import` 的 `gmail-address`／`gmail-app-password`。
僅標準庫，Python 3.9 相容。
"""
import datetime
import email
import email.policy
import email.utils
import imaplib

import statement_mailbox
from statement_mailbox import MailboxError

SENDER = "postmaster@mailer.investanchors.com"
TZ8 = datetime.timezone(datetime.timedelta(hours=8))
HEADER_SPEC = "BODY.PEEK[HEADER.FIELDS (FROM DATE MESSAGE-ID)]"

__all__ = ["fetch_mail_clues", "MailboxError", "SENDER"]


def _mail_date(msg):
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(TZ8).isoformat()
    except (TypeError, ValueError):
        return None


def fetch_mail_clues(address, app_password, days=14, imap_factory=None):
    """回傳 `[{message_id, mail_date}]`（依寄達時間舊到新；寄件者不符的一律略過）。"""
    factory = imap_factory or statement_mailbox._default_factory
    try:
        conn = factory()
        conn.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as e:
        raise MailboxError("Gmail 登入失敗（請確認 IMAP 已啟用、應用程式密碼正確）：%s" % type(e).__name__)
    try:
        typ, _ = conn.select(statement_mailbox._find_all_mail(conn), readonly=True)
        if typ != "OK":
            raise MailboxError("無法開啟「所有郵件」")
        typ, data = conn.uid("SEARCH", "X-GM-RAW", '"from:%s newer_than:%dd"' % (SENDER, int(days)))
        if typ != "OK":
            raise MailboxError("Gmail 搜尋失敗")
        uids = (data[0] or b"").split() if data else []
        clues = []
        for uid in uids:
            raw = statement_mailbox._fetch_parts(conn, uid, HEADER_SPEC)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            if SENDER not in str(msg.get("From") or "").lower():
                continue
            message_id = str(msg.get("Message-ID") or "").strip()
            if not message_id:
                message_id = "uid:%s" % (uid.decode() if isinstance(uid, bytes) else uid)
            clues.append({"message_id": message_id, "mail_date": _mail_date(msg)})
        clues.sort(key=lambda c: c["mail_date"] or "")
        return clues
    except (imaplib.IMAP4.error, OSError) as e:
        raise MailboxError("Gmail 讀取失敗：%s" % type(e).__name__)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
