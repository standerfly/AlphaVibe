"""ledger_cleanup：以交易明細表清理 trade_ledger（虛構數值、暫存資料目錄、假解密）。"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import ledger_cleanup  # noqa: E402
from kb_store import KBStore  # noqa: E402

DETAIL = """交易日期: 115/10/01 - 115/10/06 頁次: 1
交易日期 CD 股票名稱 股數 單價 手續費 交易稅 委託書號
115/10/01 集買 台積電 10 1,000.00 14 0 10,000 10,014(付) k-AAAA-00
115/10/02 集買 台積電 30 990.00 42 0 29,700 29,742(付) k-BBBB-00
115/10/03 集買 台積電 5 1,010.00 7 0 5,050 5,057(付) k-CCCC-00
115/10/04 集賣 台積電 20 1,100.00 31 66 22,000 21,903(收) k-DDDD-00
115/10/05 集買 新股票 3 50.00 1 0 150 151(付) k-EEEE-00
115/10/06 集買 台積電 2 1,000.00 1 0 2,000 2,001(付) k-FFFF-00
合 計: 96 66 68,900
"""


def _extract(pdf, password):
    with open(pdf, "rb") as f:
        return f.read().decode("utf-8")


class LedgerCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stnd-cleanup-")
        self.data = os.path.join(self.tmp, "data")
        self.backup = os.path.join(self.tmp, "backup")
        self.store = KBStore(self.data)
        self.store.save_stock_alias("台積電", "2330")
        self.pdf = os.path.join(self.tmp, "detail.pdf")
        with open(self.pdf, "w", encoding="utf-8") as f:
            f.write(DETAIL)
        add = self.store.save_trade_ledger_entry
        add("2330", "台積電", "買", 100, 500.0, "2025-12-01", add_sequence=1)       # 期間外
        add("2330", "台積電", "買", 10, 1000.0, "2026-10-01", add_sequence=2, order_ref="kAAAA")
        add("2330", "台積電", "買", 10, 1000.0, "2026-10-01", add_sequence=3,
            order_ref="k-AAAA-00")                                                  # 留這筆
        add("2330", "台積電", "買", 20, 990.0, "2026-10-02", add_sequence=4, order_ref="kBBBB")
        add("2330", "台積電", "買", 10, 990.0, "2026-10-02", add_sequence=5, order_ref="kBBBB")
        add("2330", "台積電", "買", 30, 990.0, "2026-10-02", add_sequence=6,
            order_ref="k-BBBB-00")                                                  # 拆單三筆
        add("2330", "台積電", "買", 5, 1010.0, "2026-10-03", add_sequence=7,
            order_ref="k-CCCC-00")
        add("2330", "台積電", "買", 5, 1010.0, "2026-10-03", add_sequence=8)        # 無號重複
        add("2330", "台積電", "賣", 20, 1100.0, "2026-10-04", order_ref="k-DDDD-00")
        add("2330", "台積電", "買", 7, 777.0, "2026-10-05", add_sequence=9)         # 多出、非重複
        # k-EEEE-00（新股票，名稱未知）、k-FFFF-00 缺漏
        self.store.conn.close()
        self.db = os.path.join(self.data, "alphavibe.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ledger_cleanup.main([self.pdf, "--data-dir", self.data,
                                      "--backup-dir", self.backup] + list(args),
                                     get_secret=lambda a: "pw", extract=_extract)
        return rc, out.getvalue(), err.getvalue()

    def rows(self):
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM trade_ledger ORDER BY date, id")]

    def digest(self):
        with open(self.db, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def plan(self, *args):
        rc, out, _ = self.run_cli("--json", *args)
        self.assertEqual(rc, 0)
        return json.loads(out)

    def test_plan_rules(self):
        p = self.plan("--alias", "新股票=9999")
        deleted = {d["row"]["order_ref"] or "(無)": d for d in p["deletes"]}
        self.assertEqual(len(p["deletes"]), 4)
        self.assertEqual(sorted(deleted), ["(無)", "kAAAA", "kBBBB"])   # kBBBB 兩筆
        self.assertEqual(sum(1 for d in p["deletes"] if d["row"]["order_ref"] == "kBBBB"), 2)
        self.assertEqual([r["price"] for r in p["extra_kept"]], [777.0])
        self.assertEqual([(t["code"], t["order_ref"]) for t in p["inserts"]],
                         [("9999", "k-EEEE-00"), ("2330", "k-FFFF-00")])
        self.assertEqual(p["unresolved_names"], [])

    def test_plan_is_read_only(self):
        before = self.digest()
        self.run_cli()
        self.run_cli("--json")
        self.assertEqual(self.digest(), before)

    def test_unresolved_name_blocks_apply(self):
        p = self.plan()
        self.assertEqual(p["unresolved_names"], ["新股票"])
        before = self.digest()
        rc, _, err = self.run_cli("--apply", "--confirm", p["plan_code"])
        self.assertEqual(rc, 2)
        self.assertIn("--alias", err)
        self.assertEqual(self.digest(), before)

    def test_wrong_plan_code_refused(self):
        before = self.digest()
        rc, _, err = self.run_cli("--alias", "新股票=9999", "--apply", "--confirm", "000000000000")
        self.assertEqual(rc, 2)
        self.assertIn("計畫代碼不符", err)
        self.assertEqual(self.digest(), before)
        self.assertFalse(os.path.exists(self.backup))

    def test_apply_backup_and_result(self):
        before = self.rows()
        p = self.plan("--alias", "新股票=9999")
        rc, out, _ = self.run_cli("--alias", "新股票=9999", "--apply", "--confirm", p["plan_code"])
        self.assertEqual(rc, 0, out)
        after = self.rows()
        self.assertEqual(len(after), len(before) - 4 + 2)
        tsmc_buys = [(r["date"], r["shares"], r["add_sequence"]) for r in after
                     if r["code"] == "2330" and r["action"] == "買"]
        self.assertEqual(tsmc_buys, [("2025-12-01", 100, 1), ("2026-10-01", 10, 2),
                                     ("2026-10-02", 30, 3), ("2026-10-03", 5, 4),
                                     ("2026-10-05", 7, 5), ("2026-10-06", 2, 6)])
        self.assertIsNone([r for r in after if r["action"] == "賣"][0]["add_sequence"])
        self.assertEqual([r["add_sequence"] for r in after if r["code"] == "9999"], [1])
        backups = os.listdir(self.backup)
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(os.path.join(self.backup, backups[0])) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM trade_ledger").fetchone()[0],
                             len(before))
        # 套用後再試跑：沒有任何要改的
        p2 = self.plan("--alias", "新股票=9999")
        self.assertEqual((p2["deletes"], p2["inserts"], p2["seq_updates"]), ([], [], []))

    def test_failure_midway_rolls_back(self):
        p = self.plan("--alias", "新股票=9999")
        before = self.digest()
        bad = dict(p, inserts=p["inserts"] + [{"code": None, "name": "x", "action": "買",
                                               "add_sequence": 1, "shares": 1, "price": 1,
                                               "date": "2026-10-07", "source_ref": "",
                                               "order_ref": "k-ZZZZ-00"}])
        with self.assertRaises(sqlite3.IntegrityError):
            ledger_cleanup.apply_plan(self.db, bad, self.backup)
        self.assertEqual(self.digest(), before)

    def test_text_report(self):
        rc, out, _ = self.run_cli()
        self.assertIn("計畫代碼：", out)
        self.assertIn("名稱對不到代號", out)
        self.assertIn("無法判定為重複", out)


if __name__ == "__main__":
    unittest.main()
