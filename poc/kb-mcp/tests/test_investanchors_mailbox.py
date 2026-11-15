"""T012：定錨通知信線索（假 IMAP，不連網）。只取 Message-ID 與寄達時間，不讀本文、不記連結與標題。"""
import imaplib
import json
import os
import sys
import unittest
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import investanchors_mailbox as M  # noqa: E402

SENDER = M.SENDER


def _mail(msgid, sender=SENDER, date_hdr="Sat, 14 Nov 2026 22:30:00 +0800", subject="SECRETSUBJECT 文章標題"):
    m = MIMEMultipart("alternative")
    m["From"] = formataddr((str(Header("定錨產業筆記", "utf-8")), sender))
    m["Subject"] = Header(subject, "utf-8").encode()
    if msgid:
        m["Message-ID"] = msgid
    m["Date"] = date_hdr
    m.attach(MIMEText('<a href="https://investanchors.com/c/eJwSECRETTRACKINGTOKEN1234567890">SECRETLINKTEXT</a>',
                      "html", "utf-8"))
    return m.as_bytes()


class FakeImap:
    def __init__(self, mails, fail_login=False):
        self.mails = mails
        self.fail_login = fail_login
        self.selected = None
        self.fetch_specs = []
        self.search_args = None
        self.logged_out = False

    def login(self, user, pw):
        if self.fail_login:
            raise imaplib.IMAP4.error("auth failed")
        return "OK", [b""]

    def list(self):
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']

    def select(self, name, readonly=False):
        self.selected = (name, readonly)
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            self.search_args = args
            return "OK", [b" ".join(sorted(self.mails))]
        uid, spec = args
        self.fetch_specs.append(spec)
        raw = self.mails[uid]
        # 假伺服器：只回標頭（標頭與本文以空行分隔）。若有人要求整封，會連本文一起給，測試會抓到。
        if "HEADER.FIELDS" in spec:
            raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
        return "OK", [(b"1 (UID %s)" % uid, raw), b")"]

    def logout(self):
        self.logged_out = True


class FetchMailCluesTest(unittest.TestCase):
    def _run(self, fake, days=14):
        return M.fetch_mail_clues("me@example.com", "app-pw", days=days, imap_factory=lambda: fake)

    def test_returns_only_message_id_and_taipei_mail_date_sorted(self):
        fake = FakeImap({b"1": _mail("<b@x>", date_hdr="Sun, 15 Nov 2026 01:00:00 +0000"),
                         b"2": _mail("<a@x>", date_hdr="Sat, 14 Nov 2026 22:30:00 +0800")})
        got = self._run(fake)
        self.assertEqual([c["message_id"] for c in got], ["<a@x>", "<b@x>"])
        self.assertEqual(got[0]["mail_date"], "2026-11-14T22:30:00+08:00")
        self.assertEqual(got[1]["mail_date"], "2026-11-15T09:00:00+08:00")     # UTC 01:00 → 台北 09:00
        for c in got:
            self.assertEqual(sorted(c.keys()), ["mail_date", "message_id"])

    def test_readonly_header_peek_only_never_full_body(self):
        fake = FakeImap({b"1": _mail("<a@x>")})
        self._run(fake, days=7)
        self.assertEqual(fake.selected, ('"[Gmail]/All Mail"', True))
        self.assertIn("X-GM-RAW", fake.search_args)
        self.assertIn("newer_than:7d", fake.search_args[1])
        self.assertIn(SENDER, fake.search_args[1])
        self.assertTrue(fake.fetch_specs)
        self.assertTrue(all("PEEK" in s and "HEADER.FIELDS" in s for s in fake.fetch_specs))
        self.assertFalse(any(s == "BODY.PEEK[]" for s in fake.fetch_specs))
        self.assertTrue(fake.logged_out)

    def test_result_contains_no_subject_link_text_or_tracking_token(self):
        fake = FakeImap({b"1": _mail("<a@x>")})
        dumped = json.dumps(self._run(fake), ensure_ascii=False)
        for secret in ("SECRETSUBJECT", "SECRETLINKTEXT", "SECRETTRACKINGTOKEN", "文章標題", "investanchors.com/c/"):
            self.assertNotIn(secret, dumped)

    def test_spoofed_sender_is_skipped(self):
        fake = FakeImap({b"1": _mail("<x@x>", sender="phish@evil.example"),
                         b"2": _mail("<ok@x>")})
        self.assertEqual([c["message_id"] for c in self._run(fake)], ["<ok@x>"])

    def test_missing_message_id_falls_back_to_uid(self):
        fake = FakeImap({b"7": _mail(None)})
        self.assertEqual(self._run(fake)[0]["message_id"], "uid:7")

    def test_unparseable_date_gives_none_and_sorts_first(self):
        fake = FakeImap({b"1": _mail("<a@x>", date_hdr="not a date"), b"2": _mail("<b@x>")})
        got = self._run(fake)
        self.assertEqual(got[0]["message_id"], "<a@x>")
        self.assertIsNone(got[0]["mail_date"])

    def test_login_failure_raises_mailbox_error_without_password(self):
        fake = FakeImap({}, fail_login=True)
        with self.assertRaises(M.MailboxError) as cm:
            self._run(fake)
        self.assertNotIn("app-pw", str(cm.exception))

    def test_no_mail_returns_empty_list(self):
        self.assertEqual(self._run(FakeImap({})), [])


if __name__ == "__main__":
    unittest.main()
