"""009 T020：交易明細表唯讀比對工具（虛構數值、暫存資料目錄、假解密）。"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import statement_pdf  # noqa: E402
import statement_reconcile  # noqa: E402
from kb_store import KBStore  # noqa: E402

DETAIL = """交易日期: 115/10/01 - 115/10/03 頁次: 1
交易日期 CD 股票名稱 股數 單價 手續費 交易稅 委託書號
115/10/01 集買 台積電 10 1,000.00 14 0 10,000 10,014(付) k-AAAA-00
115/10/02 集賣 台積電 5 1,100.00 7 16 5,500 5,477(收) k-BBBB-00
115/10/03 OT買 中美晶 50 200.00 14 0 10,000 10,014(付) k-CCCC-00
合 計: 35 16 25,500
"""


def _secret(account):
    return "pw"


def _extract(pdf, password):
    with open(pdf, "rb") as f:
        data = f.read()
    if not data.startswith(b"TEXT:"):
        raise statement_pdf.PdfUnreadable("PDF 無法開啟")
    return data[5:].decode("utf-8")


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stnd-reconcile-")
        self.data = os.path.join(self.tmp, "data")
        self.folder = os.path.join(self.tmp, "pdfs")
        os.makedirs(self.folder)
        self.store = KBStore(self.data)
        self.store.save_stock_alias("台積電", "2330")
        self.store.save_stock_alias("中美晶", "5483")
        self.pdf = self._pdf("detail.pdf", DETAIL)

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pdf(self, name, text):
        path = os.path.join(self.folder, name)
        with open(path, "wb") as f:
            f.write(b"TEXT:" + text.encode("utf-8"))
        return path

    def _add(self, code, action, shares, price, date, ref):
        self.store.save_trade_ledger_entry(code, None, action, shares, price, date, order_ref=ref)

    def _run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = statement_reconcile.main(list(args) + ["--data-dir", self.data, "--folder",
                                                        self.folder],
                                          get_secret=_secret, extract=_extract)
        return rc, out.getvalue()

    def _snapshot(self):
        h = {}
        for root, _, files in os.walk(self.tmp):
            for n in files:
                p = os.path.join(root, n)
                with open(p, "rb") as f:
                    h[p] = (hashlib.sha256(f.read()).hexdigest(), os.path.getmtime(p))
        return h

    def test_exactly_three_findings(self):
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "k-AAAA-00")
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "kAAAA")      # 重複（舊寫法）
        self._add("2330", "賣", 5, 1105.0, "2026-10-02", "kBBBB00")     # 價格不同
        # k-CCCC-00 缺漏
        rc, out = self._run(self.pdf, "--json")
        self.assertEqual(rc, 0)
        rep = json.loads(out)
        self.assertEqual(len(rep["duplicates_in_db"]), 1)
        self.assertEqual(rep["duplicates_in_db"][0]["normalized_ref"], "kAAAA00")
        self.assertEqual([m["order_ref"] for m in rep["missing_in_db"]], ["k-CCCC-00"])
        self.assertEqual([(m["field"], m["statement_value"], m["db_value"])
                          for m in rep["mismatched"]], [("price", 1100.0, 1105.0)])
        self.assertEqual(rep["period"], ["2026-10-01", "2026-10-03"])

    def test_all_consistent(self):
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "k-AAAA-00")
        self._add("2330", "賣", 5, 1100.0, "2026-10-02", "kBBBB00")
        self._add("5483", "買", 50, 200.0, "2026-10-03", "kCCCC")
        self._add("2330", "買", 1, 900.0, "2026-09-01", "kZZZZ00")      # 期間外不比
        rc, out = self._run(self.pdf)
        self.assertEqual(rc, 0)
        self.assertIn("全部一致", out)

    def test_extra_db_row_in_period_reported(self):
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "k-AAAA-00")
        self._add("2330", "賣", 5, 1100.0, "2026-10-02", "kBBBB00")
        self._add("5483", "買", 50, 200.0, "2026-10-03", "kCCCC00")
        self._add("2330", "買", 3, 990.0, "2026-10-02", None)           # 明細表沒有
        rc, out = self._run(self.pdf, "--json")
        rep = json.loads(out)
        self.assertEqual([d["reason"] for d in rep["duplicates_in_db"]], ["交易明細表沒有這筆"])

    def test_refless_db_row_matches_by_fields(self):
        self._add("2330", "買", 10, 1000.0, "2026-10-01", None)
        self._add("2330", "賣", 5, 1100.0, "2026-10-02", "kBBBB00")
        self._add("5483", "買", 50, 200.0, "2026-10-03", "kCCCC00")
        rc, out = self._run(self.pdf)
        self.assertIn("全部一致", out)

    def test_read_only(self):
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "kAAAA")
        self._add("2330", "買", 10, 1000.0, "2026-10-01", "k-AAAA-00")
        self.store.conn.close()
        before = self._snapshot()
        time.sleep(0.01)
        self._run(self.pdf)
        self._run(self.pdf, "--json")
        self.assertEqual(before, self._snapshot())
        self.store = KBStore(self.data)

    def test_unreadable_pdf_exit_2(self):
        bad = os.path.join(self.folder, "bad.pdf")
        with open(bad, "wb") as f:
            f.write(b"%PDF-encrypted")
        rc, out = self._run(bad)
        self.assertEqual(rc, 2)
        self.assertIn("無法比對", out)

    def test_unrecognized_format_exit_2(self):
        rc, _ = self._run(self._pdf("other.pdf", "這不是交易明細表"))
        self.assertEqual(rc, 2)

    def test_default_picks_newest(self):
        newer = self._pdf("newer.pdf", "這不是交易明細表")
        os.utime(self.pdf, (time.time() - 100, time.time() - 100))
        self.assertEqual(statement_reconcile.latest_pdf(self.folder), newer)
        rc, _ = self._run()
        self.assertEqual(rc, 2)  # 最新那份格式不符 → 證明預設挑的是它

    def test_empty_folder_exit_2(self):
        shutil.rmtree(self.folder)
        os.makedirs(self.folder)
        rc, _ = self._run()
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
