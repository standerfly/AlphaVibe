"""009 T009：日對帳單匯入的資料層（單一交易寫入、處理紀錄、通知去重、委託書號正規化）。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from kb_store import KBStore  # noqa: E402


def _trade(**kw):
    t = {"code": "2330", "name": "台積電", "action": "買", "shares": 10, "price": 1000.0,
         "date": "2026-10-30", "add_sequence": 1, "fee": 14.0, "tax": 0.0,
         "order_ref": "kAbCd00", "source_ref": "statement:msg-1"}
    t.update(kw)
    return t


def _import_row(**kw):
    r = {"message_id": "msg-1", "statement_date": "2026-10-30", "status": "processed",
         "trades_written": 1, "trades_skipped_duplicate": 0, "holdings_count": 1,
         "holdings_written": 1, "detail_json": None, "error": None,
         "holdings_source_ref": "statement:msg-1"}
    r.update(kw)
    return r


class StatementStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stnd-stmt-store-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _count(self, table):
        return self.store.conn.execute("SELECT count(*) AS n FROM %s" % table).fetchone()["n"]

    def test_writes_trades_holdings_and_record(self):
        self.store.apply_statement_import(
            [_trade()], [{"code": "2330", "name": "台積電", "shares": 10, "avg_cost": 1001.4}],
            "2026-10-30", True, _import_row())
        entry = self.store.get_trade_ledger("2330")["entries"][0]
        self.assertEqual((entry["fee"], entry["tax"], entry["order_ref"]), (14.0, 0.0, "kAbCd00"))
        h = self.store.get_holdings()
        self.assertEqual(h["snapshot_date"], "2026-10-30")
        self.assertEqual(h["holdings"][0]["avg_cost"], 1001.4)
        self.assertEqual(self.store.statement_import_status("msg-1")["status"], "processed")

    def test_sell_never_gets_add_sequence(self):
        self.store.apply_statement_import(
            [_trade(action="賣", add_sequence=3)], [], "2026-10-30", False, _import_row())
        self.assertIsNone(self.store.get_trade_ledger("2330")["entries"][0]["add_sequence"])

    def test_failure_midway_leaves_db_unchanged(self):
        self.store.save_holdings([{"code": "2317", "name": "鴻海", "shares": 1000}],
                                 snapshot_date="2026-09-02")
        before = (self._count("trade_ledger"), self._count("holdings"),
                  self._count("statement_imports"))
        bad_holdings = [{"code": "2330", "shares": 10}, {"name": "缺代號", "shares": 1}]
        with self.assertRaises(KeyError):
            self.store.apply_statement_import(
                [_trade(), _trade(order_ref="kAbCd01")], bad_holdings,
                "2026-10-30", True, _import_row())
        after = (self._count("trade_ledger"), self._count("holdings"),
                 self._count("statement_imports"))
        self.assertEqual(before, after)
        # 後續無關寫入不會把未決列順帶 commit 進去
        self.store.alert_once("x", "y")
        self.assertEqual(self._count("trade_ledger"), 0)

    def test_rerun_same_date_replaces_snapshot_and_upserts_record(self):
        self.store.apply_statement_import(
            [], [{"code": "2330", "shares": 10, "avg_cost": 1000}], "2026-10-30", True,
            _import_row(status="partial"))
        self.store.apply_statement_import(
            [], [{"code": "2330", "shares": 20, "avg_cost": 1000}], "2026-10-30", True,
            _import_row(status="processed"))
        rows = self.store.get_holdings("2330")["history"]
        self.assertEqual([r["shares"] for r in rows], [20])
        self.assertEqual(self._count("statement_imports"), 1)
        self.assertEqual(self.store.statement_import_status("msg-1")["status"], "processed")
        self.assertEqual(len(self.store.find_statement_imports_by_date("2026-10-30")), 1)

    def test_unlisted_previous_codes_get_zero_rows(self):
        self.store.save_holdings([{"code": "2317", "shares": 1000},
                                  {"code": "2330", "shares": 5}], snapshot_date="2026-09-02")
        self.store.apply_statement_import(
            [], [{"code": "2330", "shares": 10, "avg_cost": 1000}], "2026-10-30", True,
            _import_row())
        h = self.store.get_holdings()
        self.assertEqual(h["snapshot_date"], "2026-10-30")
        self.assertEqual([r["code"] for r in h["holdings"]], ["2330"])
        self.assertEqual(self.store.get_holdings("2317")["history"][0]["shares"], 0)

    def test_empty_statement_holdings_clears_everything(self):
        self.store.save_holdings([{"code": "2317", "shares": 1000}], snapshot_date="2026-09-02")
        self.store.apply_statement_import([], [], "2026-10-30", True, _import_row())
        h = self.store.get_holdings()
        self.assertEqual((h["snapshot_date"], h["count"]), ("2026-10-30", 0))
        self.assertEqual(self.store.latest_holdings_date(), "2026-10-30")

    def test_write_holdings_false_keeps_snapshot(self):
        self.store.save_holdings([{"code": "2317", "shares": 1000}], snapshot_date="2026-10-31")
        self.store.apply_statement_import([_trade()], [{"code": "2330", "shares": 10}],
                                          "2026-10-30", False, _import_row())
        self.assertEqual(self.store.latest_holdings_date(), "2026-10-31")
        self.assertEqual(self._count("holdings"), 1)

    def test_record_failure_only_writes_record(self):
        self.store.record_statement_failure(_import_row(status="failed", error="PDF 密碼錯誤"))
        self.assertEqual(self._count("trade_ledger"), 0)
        self.assertEqual(self.store.statement_import_status("msg-1")["error"], "PDF 密碼錯誤")

    def test_alert_once(self):
        self.assertTrue(self.store.alert_once("avg_cost_unknown", "2330"))
        self.assertFalse(self.store.alert_once("avg_cost_unknown", "2330"))
        self.assertTrue(self.store.alert_once("avg_cost_unknown", "2317"))

    def test_import_runs(self):
        run_id = self.store.start_import_run()
        self.store.finish_import_run(run_id, "ok", statements_found=2, notify_failed=True)
        row = self.store.conn.execute(
            "SELECT * FROM statement_import_runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual((row["outcome"], row["statements_found"], row["notify_failed"]),
                         ("ok", 2, 1))
        self.assertIsNotNone(row["finished_at"])

    def test_order_ref_exists_across_spellings(self):
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 1000, "2026-10-01",
                                           order_ref="k-AbCd-00")
        self.assertTrue(self.store.trade_ledger_order_ref_exists("kAbCd00"))
        self.assertTrue(self.store.trade_ledger_order_ref_exists("kAbCd"))
        self.assertFalse(self.store.trade_ledger_order_ref_exists("kAbCd01"))
        self.assertFalse(self.store.trade_ledger_order_ref_exists("kABCD00"))
        self.assertFalse(self.store.trade_ledger_order_ref_exists(None))


if __name__ == "__main__":
    unittest.main()
