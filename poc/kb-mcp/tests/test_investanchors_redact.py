"""T010：脫敏與外洩斷言工具（spec 驗收（c）的工具層）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import investanchors_redact as r  # noqa: E402

PW = "pw-secret-123"
EMAIL = "po@example.com"


class SafeErrorTest(unittest.TestCase):
    def test_password_in_exception_message_is_masked(self):
        out = r.safe_error(RuntimeError("login failed for %s with %s" % (EMAIL, PW)), [EMAIL, PW])
        self.assertNotIn(PW, out)
        self.assertNotIn(EMAIL, out)
        self.assertIn("login failed", out)

    def test_cookie_headers_and_session_ids_masked(self):
        out = r.safe_error("Set-Cookie: sid=abcDEF123; Path=/\nCookie: sid=abcDEF123", [])
        self.assertNotIn("abcDEF123", out)
        out2 = r.safe_error("request failed sid=abcDEF123 and session=XYZ789", [])
        self.assertNotIn("abcDEF123", out2)
        self.assertNotIn("XYZ789", out2)

    def test_csrf_and_authenticity_tokens_masked(self):
        out = r.safe_error("authenticity_token=ZZZtokenZZZ x-csrf-token: tok123abc", [])
        self.assertNotIn("ZZZtokenZZZ", out)
        self.assertNotIn("tok123abc", out)

    def test_tracking_path_and_long_tokens_masked(self):
        tok = "eJwUzEGOhCAQAMDXwHFCNabcdefGHIJKLMNOPQRSTUVWXYZ"
        out = r.safe_error("GET https://investanchors.com/c/%s failed" % tok, [])
        self.assertIn("/c/<token>", out)
        self.assertNotIn("eJw", out)
        out2 = r.safe_error("blob " + "A1b2C3d4" * 8, [])
        self.assertIn("<token>", out2)

    def test_long_text_suspected_body_is_omitted(self):
        body = "這是一段很長的文章內文。" * 40
        out = r.safe_error(body, [])
        self.assertNotIn("文章內文", out)
        self.assertIn("長文字已省略", out)

    def test_short_secrets_below_minimum_are_not_replaced(self):
        self.assertEqual(r.safe_error("ab", ["ab"]), "ab")

    def test_none_and_plain_text(self):
        self.assertEqual(r.safe_error(None, []), "")
        self.assertEqual(r.safe_error("逾時", []), "逾時")


class AssertCleanTest(unittest.TestCase):
    def test_clean_text_passes(self):
        r.assert_clean("新文章：標題 https://investanchors.com/user/vip_contents/123", [PW], ["SECRETBODY"])

    def test_each_kind_of_leak_is_detected(self):
        cases = [
            ("pw " + PW, [PW], ()),
            ("Cookie: sid=abc", [], ()),
            ("set-cookie: x=1", [], ()),
            ("authenticity_token=abc", [], ()),
            ("https://x/c/eJwUzEGOhCAQAMDXwH", [], ()),
            ("內文 SECRETBODY 出現", [], ("SECRETBODY",)),
        ]
        for text, secrets, forbidden in cases:
            with self.assertRaises(AssertionError, msg=text):
                r.assert_clean(text, secrets, forbidden)

    def test_find_leaks_lists_kinds(self):
        self.assertEqual(sorted(set(r.find_leaks("Cookie: a=1 " + PW, [PW]))), ["cookie", "secret"])


if __name__ == "__main__":
    unittest.main()
