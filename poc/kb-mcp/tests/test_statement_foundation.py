"""009 Foundational：委託書號正規化、鑰匙圈讀取、PDF 解密擷取。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import keychain_secrets  # noqa: E402
import statement_pdf  # noqa: E402
from order_ref import normalize_order_ref  # noqa: E402


class NormalizeOrderRefTest(unittest.TestCase):
    def test_three_spellings_are_equal(self):
        self.assertEqual(normalize_order_ref("k-AbCd-00"), "kAbCd00")
        self.assertEqual(normalize_order_ref("kAbCd00"), "kAbCd00")
        self.assertEqual(normalize_order_ref("kAbCd"), "kAbCd00")

    def test_sequence_distinguishes_fills(self):
        self.assertNotEqual(normalize_order_ref("k-AbCd-00"), normalize_order_ref("k-AbCd-01"))
        self.assertEqual(normalize_order_ref("k-AbCd-01"), "kAbCd01")

    def test_case_is_preserved(self):
        self.assertNotEqual(normalize_order_ref("k00on"), normalize_order_ref("k00ON"))

    def test_other_prefix_and_whitespace(self):
        self.assertEqual(normalize_order_ref(" V-00on-00 "), "V00on00")

    def test_unrecognized_kept_as_is(self):
        self.assertEqual(normalize_order_ref("ABC-123456"), "ABC123456")

    def test_empty(self):
        self.assertIsNone(normalize_order_ref(None))
        self.assertIsNone(normalize_order_ref("  "))


class _Proc:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


class KeychainTest(unittest.TestCase):
    def test_returns_value_and_calls_security(self):
        calls = []

        def runner(args):
            calls.append(args)
            return _Proc(0, "secret-value\n")
        self.assertEqual(keychain_secrets.get_secret("pdf-password", runner), "secret-value")
        self.assertEqual(calls[0][:2], ["security", "find-generic-password"])
        self.assertIn("stnd-statement-import", calls[0])

    def test_missing_raises_without_value(self):
        with self.assertRaises(keychain_secrets.SecretNotFound) as cm:
            keychain_secrets.get_secret("gmail-app-password", lambda a: _Proc(44, ""))
        self.assertIn("gmail-app-password", str(cm.exception))

    def test_unknown_account_rejected(self):
        with self.assertRaises(ValueError):
            keychain_secrets.get_secret("something-else", lambda a: _Proc(0, "x"))


def _make_encrypted_pdf(workdir, text, password):
    """以 LibreOffice 產生含中文的 PDF，再用 qpdf AES-256 加密。工具不全時回傳 None。"""
    soffice = shutil.which("soffice")
    qpdf = shutil.which("qpdf")
    if not (soffice and qpdf and shutil.which("pdftotext")):
        return None
    src = os.path.join(workdir, "doc.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", workdir, src],
                   capture_output=True, timeout=180)
    plain = os.path.join(workdir, "doc.pdf")
    if not os.path.exists(plain):
        return None
    enc = os.path.join(workdir, "enc.pdf")
    subprocess.run([qpdf, "--encrypt", password, "owner-pw", "256", "--", plain, enc],
                   check=True, capture_output=True)
    return enc


class ExtractTextIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="stnd-pdf-test-")
        cls.enc = _make_encrypted_pdf(cls.tmp, "交易明細\n範例股 集買 3 5000 15,000 7 0 kAbCd00\n",
                                      "TestPw123")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        if not self.enc:
            self.skipTest("需要 soffice、qpdf、pdftotext")

    def test_correct_password_from_path_and_bytes(self):
        self.assertIn("範例股", statement_pdf.extract_text(self.enc, "TestPw123"))
        with open(self.enc, "rb") as f:
            data = f.read()
        before = set(os.listdir(tempfile.gettempdir()))
        self.assertIn("kAbCd00", statement_pdf.extract_text(data, "TestPw123"))
        leftovers = [n for n in set(os.listdir(tempfile.gettempdir())) - before
                     if n.startswith("stnd-stmt-")]
        self.assertEqual(leftovers, [], "暫存檔要刪除")

    def test_wrong_password(self):
        with self.assertRaises(statement_pdf.WrongPassword):
            statement_pdf.extract_text(self.enc, "nope")

    def test_garbage_bytes_unreadable(self):
        with self.assertRaises(statement_pdf.PdfUnreadable):
            statement_pdf.extract_text(b"not a pdf", "TestPw123")


class FindToolTest(unittest.TestCase):
    def test_missing_tool(self):
        with self.assertRaises(statement_pdf.PdfToolMissing):
            statement_pdf.find_tool("definitely-not-a-real-tool-xyz")


if __name__ == "__main__":
    unittest.main()
