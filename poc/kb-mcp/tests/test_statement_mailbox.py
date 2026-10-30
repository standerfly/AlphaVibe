"""009 T011：Gmail 唯讀取信（假 IMAP 物件，不連網）。"""
import os
import sys
import unittest
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import statement_mailbox  # noqa: E402

SENDER = "國泰綜合證券日對帳單 <e-notification@ebill1.cathaysec.com.tw>"


def _mail(msgid, sender=SENDER, subject="國泰綜合證券日對帳單", body_date="2026/10/29",
          pdf=b"%PDF-fake", date_hdr="Thu, 29 Oct 2026 19:12:00 +0800"):
    m = MIMEMultipart()
    name, addr = sender.rsplit(" <", 1)
    m["From"] = formataddr((str(Header(name, "utf-8")), addr.rstrip(">")))
    m["Subject"] = Header(subject, "utf-8").encode()
    m["Message-ID"] = msgid
    m["Date"] = date_hdr
    m.attach(MIMEText("這是您%s的證券電子對帳單" % body_date, "plain", "utf-8"))
    if pdf is not None:
        m.attach(MIMEApplication(pdf, "pdf", Name="statement.pdf"))
    return m.as_bytes()


class FakeImap:
    def __init__(self, mails, fail_login=False):
        self.mails = mails  # {uid(bytes): raw bytes}
        self.fail_login = fail_login
        self.selected = None
        self.fetched = []
        self.logged_out = False

    def login(self, user, pw):
        if self.fail_login:
            raise statement_mailbox.imaplib.IMAP4.error("auth failed")
        return "OK", [b""]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']

    def select(self, name, readonly=False):
        self.selected = (name, readonly)
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            self.search_args = args
            return "OK", [b" ".join(sorted(self.mails))]
        uid, spec = args
        self.fetched.append((uid, spec))
        raw = self.mails[uid]
        if "HEADER.FIELDS" in spec:
            raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
        return "OK", [(b"1 (UID %s)" % uid, raw), b")"]

    def logout(self):
        self.logged_out = True


class FetchStatementsTest(unittest.TestCase):
    def _run(self, fake):
        return statement_mailbox.fetch_statements("me@example.com", "app-pw", days=7,
                                                  imap_factory=lambda: fake)

    def test_valid_mail_readonly_and_sorted(self):
        fake = FakeImap({b"1": _mail("<b@x>", body_date="2026/10/30"),
                         b"2": _mail("<a@x>", body_date="2026/10/29")})
        got = self._run(fake)
        self.assertEqual([g["message_id"] for g in got], ["<a@x>", "<b@x>"])
        self.assertEqual(got[0]["date_hint"], "2026-10-29")
        self.assertEqual(got[0]["pdf_bytes"], b"%PDF-fake")
        self.assertEqual(fake.selected, ('"[Gmail]/All Mail"', True))
        self.assertIn("X-GM-RAW", fake.search_args)
        self.assertIn("newer_than:7d", fake.search_args[1])
        self.assertTrue(all("PEEK" in spec for _, spec in fake.fetched))
        self.assertTrue(fake.logged_out)

    def test_wrong_sender_body_never_fetched(self):
        fake = FakeImap({b"1": _mail("<x@x>", sender="Phish <e-notification@evil.example>")})
        self.assertEqual(self._run(fake), [])
        self.assertEqual([spec for _, spec in fake.fetched if spec == "BODY.PEEK[]"], [])

    def test_wrong_subject_skipped(self):
        fake = FakeImap({b"1": _mail("<x@x>", subject="國泰綜合證券日對帳單（廣告）")})
        self.assertEqual(self._run(fake), [])

    def test_no_attachment_returns_none_pdf(self):
        fake = FakeImap({b"1": _mail("<x@x>", pdf=None)})
        got = self._run(fake)
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["pdf_bytes"])

    def test_date_header_fallback(self):
        fake = FakeImap({b"1": _mail("<x@x>", body_date="無日期")})
        self.assertEqual(self._run(fake)[0]["date_hint"], "2026-10-29")

    def test_login_failure(self):
        with self.assertRaises(statement_mailbox.MailboxError) as cm:
            self._run(FakeImap({}, fail_login=True))
        self.assertNotIn("app-pw", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
