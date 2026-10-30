"""009 T015／T017：日對帳單匯入流程（US1 驗收情境 1～6、US2 驗收情境）。

全部使用暫存資料目錄與虛構數值；不連 Gmail、不呼叫 FinMind、不送 Telegram。
"""
import contextlib
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

import statement_import  # noqa: E402
import statement_pdf  # noqa: E402
from kb_store import KBStore  # noqa: E402


def _stmt(date, trades=(), holdings=()):
    return {"statement_date": date,
            "trades": [dict({"date": date, "market": "集", "amount": 0, "fee": 1.0,
                             "tax": 0.0}, **t) for t in trades],
            "holdings": list(holdings)}


def _buy(name, shares, price, ref, action="買"):
    return {"name": name, "action": action, "shares": shares, "price": price, "order_ref": ref}


def _no_resolver(names):
    return {}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stnd-stmt-import-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def process(self, stmt, msg="m1", resolver=_no_resolver):
        return statement_import.process_statement(self.store, stmt, msg, resolver)

    def holding(self, code):
        rows = {h["code"]: h for h in self.store.get_holdings()["holdings"]}
        return rows.get(code)

    def ledger_count(self):
        return len(self.store.get_all_trade_entries())


class US1ScenarioTest(_Base):
    def test_1_new_stock_written_with_cost(self):
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00")],
                               [{"code": "2330", "name": "台積電", "shares": 10}]))
        self.assertEqual((s["status"], s["written"], s["duplicates"]), ("processed", 1, 0))
        e = self.store.get_trade_ledger("2330")["entries"][0]
        self.assertEqual((e["add_sequence"], e["fee"], e["source_ref"]),
                         (1, 1.0, "國泰日對帳單 2026-10-29"))
        self.assertEqual(self.holding("2330")["avg_cost"], 100.0)
        self.assertEqual(self.store.statement_import_status("m1")["status"], "processed")

    def test_2_add_on_weighted_average(self):
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 10,
                                   "avg_cost": 100.0}], snapshot_date="2026-10-01")
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 100.0, "2026-09-01",
                                           add_sequence=1, order_ref="k-ZZZZ-00")
        self.process(_stmt("2026-10-29", [_buy("台積電", 10, 200.0, "kAAAA00")],
                           [{"code": "2330", "name": "台積電", "shares": 20}]))
        self.assertEqual(self.holding("2330")["avg_cost"], 150.0)
        self.assertEqual(self.store.get_trade_ledger("2330")["entries"][-1]["add_sequence"], 2)

    def test_3_sell_keeps_cost(self):
        self.store.save_holdings([{"code": "2330", "shares": 10, "avg_cost": 100.0}],
                                 snapshot_date="2026-10-01")
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 4, 300.0, "kAAAA00", "賣")],
                               [{"code": "2330", "name": "台積電", "shares": 6}]))
        self.assertEqual(self.holding("2330")["avg_cost"], 100.0)
        self.assertIsNone(self.store.get_trade_ledger("2330")["entries"][0]["add_sequence"])
        self.assertEqual(s["diffs"], [])

    def test_4_unlisted_stock_removed(self):
        self.store.save_holdings([{"code": "2330", "shares": 10, "avg_cost": 100.0},
                                  {"code": "2317", "shares": 1000, "avg_cost": 50.0}],
                                 snapshot_date="2026-10-01")
        s = self.process(_stmt("2026-10-29", [],
                               [{"code": "2330", "name": "台積電", "shares": 10}]))
        self.assertIsNone(self.holding("2317"))
        self.assertEqual(s["diffs"], [{"code": "2317", "expected": 1000, "actual": 0}])

    def test_5_holdings_difference_reported(self):
        self.store.save_holdings([{"code": "2330", "shares": 10, "avg_cost": 100.0}],
                                 snapshot_date="2026-10-01")
        s = self.process(_stmt("2026-10-29", [],
                               [{"code": "2330", "name": "台積電", "shares": 12}]))
        self.assertEqual(self.holding("2330")["shares"], 12)  # 對帳單是標準
        self.assertEqual(self.holding("2330")["avg_cost"], 100.0)
        self.assertIn("2330 推算 10／對帳單 12", statement_import.format_summary(s))

    def test_6_cost_unknown_alerted_once(self):
        self.store.save_holdings([{"code": "2330", "shares": 10}], snapshot_date="2026-10-01")
        hold = [{"code": "2330", "name": "台積電", "shares": 10}]
        s1 = self.process(_stmt("2026-10-29", [], hold), msg="m1")
        s2 = self.process(_stmt("2026-10-30", [], hold), msg="m2")
        self.assertIsNone(self.holding("2330")["avg_cost"])
        self.assertEqual((s1["cost_alerts"], s2["cost_alerts"]), (["2330"], []))
        self.assertIn("平均成本算不出來：2330", statement_import.format_summary(s1))
        self.assertNotIn("平均成本", statement_import.format_summary(s2))

    def test_cost_from_full_ledger_replay(self):
        # 基準庫存沒有成本，但交易紀錄完整、重播股數等於對帳單 → 採用重播結果
        self.store.save_holdings([{"code": "2330", "shares": 10}], snapshot_date="2026-10-01")
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 100.0, "2026-09-01",
                                           add_sequence=1)
        self.process(_stmt("2026-10-29", [_buy("台積電", 10, 200.0, "kAAAA00")],
                           [{"code": "2330", "name": "台積電", "shares": 20}]))
        self.assertEqual(self.holding("2330")["avg_cost"], 150.0)


class US2ScenarioTest(_Base):
    HOLD = [{"code": "2330", "name": "台積電", "shares": 10}]

    def test_reprocess_is_noop(self):
        stmt = _stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00")], self.HOLD)
        self.process(stmt)
        s = self.process(stmt)
        self.assertEqual((s["written"], s["duplicates"], self.ledger_count()), (0, 1, 1))
        self.assertEqual(len(self.store.get_holdings("2330")["history"]), 1)

    def test_hyphenated_existing_ref_not_duplicated(self):
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 100.0, "2026-10-29",
                                           order_ref="k-AAAA-00")
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00")],
                               self.HOLD))
        self.assertEqual((s["written"], s["duplicates"], self.ledger_count()), (0, 1, 1))

    def test_same_order_different_sequence_both_written(self):
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 4, 100.0, "kAAAA00"),
                                              _buy("台積電", 6, 101.0, "kAAAA01")], self.HOLD))
        self.assertEqual(s["written"], 2)
        self.assertEqual([e["add_sequence"] for e in
                          self.store.get_trade_ledger("2330")["entries"]], [1, 2])

    def test_same_ref_twice_in_one_statement_both_written(self):
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 4, 100.0, "kAAAA00"),
                                              _buy("台積電", 6, 101.0, "kAAAA00")], self.HOLD))
        self.assertEqual((s["written"], s["duplicates"]), (2, 0))

    def test_newer_manual_sync_snapshot_does_not_block_statement_holdings(self):
        # 手動匯入交易同步出的 10-30 快照不擋 10-29 對帳單寫入庫存（FR-013 只比對帳單）
        self.store.save_holdings([{"code": "2330", "shares": 99}], snapshot_date="2026-10-30")
        s = self.process(_stmt("2026-10-29", [], self.HOLD))
        self.assertTrue(s["holdings_written"])
        self.assertEqual(self.store.get_holdings("2330")["history"][-1]["snapshot_date"],
                         "2026-10-29")

    def test_unresolved_name_partial_then_auto_retry(self):
        stmt = _stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00"),
                                    _buy("神秘股", 5, 20.0, "kBBBB00")], self.HOLD)
        s = self.process(stmt)
        self.assertEqual((s["status"], s["written"], s["unresolved"]),
                         ("partial", 1, ["神秘股"]))
        self.assertIn("部分完成", statement_import.format_summary(s))
        self.store.save_stock_alias("神秘股", "9999")
        s2 = self.process(stmt, resolver=statement_import.make_resolver(
            self.store, self.tmp, dry_run=True))
        self.assertEqual((s2["status"], s2["written"], s2["duplicates"]), ("processed", 1, 1))
        self.assertEqual(self.store.statement_import_status("m1")["status"], "processed")

    def test_older_statement_does_not_overwrite_newer_holdings(self):
        self.process(_stmt("2026-10-30", [], [{"code": "2330", "name": "台積電",
                                               "shares": 20}]), msg="new")
        s = self.process(_stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00")],
                               self.HOLD), msg="old")
        self.assertFalse(s["holdings_written"])
        self.assertEqual(self.store.latest_holdings_date(), "2026-10-30")
        self.assertEqual(self.holding("2330")["shares"], 20)
        self.assertEqual(self.ledger_count(), 1)
        self.assertIn("本份不更新庫存", statement_import.format_summary(s))

    def test_dry_run_writes_nothing(self):
        statement_import.process_statement(
            self.store, _stmt("2026-10-29", [_buy("台積電", 10, 100.0, "kAAAA00")], self.HOLD),
            "m1", _no_resolver, dry_run=True)
        self.assertEqual(self.ledger_count(), 0)
        self.assertIsNone(self.store.statement_import_status("m1"))


# ---------- run()：信箱、PDF、通知、心跳 ----------

STATEMENT_TEXT = """交割金額
 2026/10/29  2026/11/02
交易明細
 台積電  集買  10  100  1,000  1  0  -1,001  0 0 0 0  kAAAA00
庫存明細
 2330  台積電  100  10  1,000
"""


def _fake_extract(pdf, password):
    if password != "pw":
        raise statement_pdf.WrongPassword("PDF 密碼錯誤")
    if pdf == b"BAD":
        raise statement_pdf.PdfUnreadable("PDF 無法開啟")
    return pdf.decode("utf-8")


class RunTest(_Base):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.secrets = {"pdf-password": "pw", "gmail-address": "me@example.com",
                        "gmail-app-password": "app"}
        p = mock.patch.object(statement_pdf, "extract_text", _fake_extract)
        p.start()
        self.addCleanup(p.stop)

    def _secret(self, account):
        if account not in self.secrets:
            raise statement_import.keychain_secrets.SecretNotFound(account)
        return self.secrets[account]

    def _notifier(self, text):
        self.sent.append(text)
        return 1, []

    def run_job(self, items, notifier=None, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            return statement_import.run(
                self.tmp, get_secret=self._secret, fetch=lambda a, p, d: list(items),
                notifier=notifier or self._notifier, resolver=_no_resolver,
                today="2026-10-30", **kw)

    def runs(self):
        with sqlite3.connect(os.path.join(self.tmp, "alphavibe.db")) as c:
            return c.execute("SELECT outcome, statements_found, notify_failed"
                             " FROM statement_import_runs ORDER BY id").fetchall()

    def test_happy_path_and_skip_processed(self):
        item = {"message_id": "<a@x>", "date_hint": "2026-10-29",
                "pdf_bytes": STATEMENT_TEXT.encode()}
        self.assertEqual(self.run_job([item]), 0)
        self.assertEqual(self.ledger_count(), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("📒 國泰日對帳單 2026-10-29 已匯入", self.sent[0])
        self.assertEqual(self.run_job([item]), 0)  # 已 processed：不再處理、不再通知
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.runs(), [("ok", 1, 0), ("ok", 0, 0)])

    def test_unreadable_pdf_writes_nothing_and_notifies_once_per_day(self):
        item = {"message_id": "<bad@x>", "date_hint": "2026-10-29", "pdf_bytes": b"BAD"}
        self.run_job([item])
        self.run_job([item])
        self.assertEqual(self.ledger_count(), 0)
        self.assertIsNone(self.store.latest_holdings_date())
        st = self.store.statement_import_status("<bad@x>")
        self.assertEqual((st["status"], st["error"]), ("failed", "PDF 無法開啟"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("❌", self.sent[0])

    def test_format_error_writes_nothing(self):
        item = {"message_id": "<f@x>", "date_hint": "2026-10-29",
                "pdf_bytes": "改版後的內容".encode()}
        self.run_job([item])
        self.assertEqual(self.ledger_count(), 0)
        self.assertIn("格式無法辨識", self.store.statement_import_status("<f@x>")["error"])

    def test_missing_attachment(self):
        self.run_job([{"message_id": "<n@x>", "date_hint": "2026-10-29", "pdf_bytes": None}])
        self.assertEqual(self.store.statement_import_status("<n@x>")["status"], "failed")

    def test_write_failure_rolls_back(self):
        item = {"message_id": "<w@x>", "date_hint": "2026-10-29",
                "pdf_bytes": STATEMENT_TEXT.encode()}
        real = KBStore.apply_statement_import

        def boom(store, trades, holdings_rows, *a, **k):
            # 呼叫真實寫入但讓最後一筆庫存列缺代號 → 交易中途失敗
            return real(store, trades, holdings_rows + [{"name": "x", "shares": 1}], *a, **k)
        with mock.patch.object(KBStore, "apply_statement_import", boom):
            self.assertEqual(self.run_job([item]), 0)
        self.assertEqual(self.ledger_count(), 0)
        self.assertIsNone(self.store.latest_holdings_date())
        self.assertEqual(self.store.statement_import_status("<w@x>")["status"], "failed")

    def test_mailbox_error_exit_1_and_heartbeat(self):
        del self.secrets["gmail-app-password"]
        self.assertEqual(self.run_job([]), 1)
        self.assertEqual(self.run_job([]), 1)
        self.assertEqual([r[0] for r in self.runs()], ["mailbox_error", "mailbox_error"])
        self.assertEqual(len(self.sent), 1)  # 同一錯誤一天一次
        self.assertNotIn("app", self.sent[0].split("：")[0])

    def test_multiple_statements_processed_oldest_first(self):
        newer = STATEMENT_TEXT.replace("2026/10/29", "2026/10/30").replace(
            "kAAAA00", "kBBBB00").replace("2330  台積電  100  10", "2330  台積電  100  20")
        items = [{"message_id": "<1@x>", "date_hint": "2026-10-29",
                  "pdf_bytes": STATEMENT_TEXT.encode()},
                 {"message_id": "<2@x>", "date_hint": "2026-10-30", "pdf_bytes": newer.encode()}]
        self.run_job(items)
        self.assertEqual(self.store.latest_holdings_date(), "2026-10-30")
        self.assertEqual(self.holding("2330")["shares"], 20)
        self.assertEqual(self.ledger_count(), 2)

    def test_partial_retry_same_day_does_not_call_finmind_again(self):
        text = STATEMENT_TEXT.replace(
            "庫存明細", " 神秘股  集買  5  20  100  1  0  -101  0 0 0 0  kBBBB00\n庫存明細")
        item = {"message_id": "<p@x>", "date_hint": "2026-10-29", "pdf_bytes": text.encode()}
        calls = []

        def counting(names):
            calls.append(list(names))
            return {}
        out = io.StringIO()
        for _ in range(2):
            with contextlib.redirect_stdout(out):
                statement_import.run(self.tmp, get_secret=self._secret,
                                     fetch=lambda a, p, d: [item], notifier=self._notifier,
                                     resolver=counting, today="2026-10-30")
        self.assertEqual(calls, [["神秘股"]])
        self.assertEqual(self.store.statement_import_status("<p@x>")["status"], "partial")
        self.store.save_stock_alias("神秘股", "9999")  # PO 補上對應 → 下一次只查快取即可補寫
        self.run_job([item])
        self.assertEqual(self.store.statement_import_status("<p@x>")["status"], "processed")
        self.assertEqual(self.ledger_count(), 2)

    def test_notify_failure_recorded(self):
        item = {"message_id": "<a@x>", "date_hint": "2026-10-29",
                "pdf_bytes": STATEMENT_TEXT.encode()}
        self.run_job([item], notifier=lambda text: (0, ["timeout"]))
        self.assertEqual(self.runs()[-1][2], 1)

    def test_rerun_by_date_reprocesses_processed(self):
        item = {"message_id": "<a@x>", "date_hint": "2026-10-29",
                "pdf_bytes": STATEMENT_TEXT.encode()}
        self.run_job([item])
        self.run_job([item], rerun="2026-10-29")
        self.assertEqual(len(self.sent), 2)
        self.assertIn("跳過重複 1", self.sent[1])
        self.assertEqual(self.ledger_count(), 1)

    def test_dry_run_from_file(self):
        path = os.path.join(self.tmp, "s.pdf")
        with open(path, "wb") as f:
            f.write(STATEMENT_TEXT.encode())

        def extract_path(pdf, pw):
            with open(pdf, "rb") as fh:
                return fh.read().decode("utf-8")
        with mock.patch.object(statement_pdf, "extract_text", extract_path):
            self.assertEqual(self.run_job([], dry_run=True, from_file=path), 0)
        self.assertEqual(self.ledger_count(), 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.runs(), [])

    def test_detail_json_has_no_secrets(self):
        item = {"message_id": "<a@x>", "date_hint": "2026-10-29",
                "pdf_bytes": STATEMENT_TEXT.encode()}
        self.run_job([item])
        detail = json.loads(self.store.statement_import_status("<a@x>")["detail_json"])
        self.assertEqual(set(detail), {"unresolved_names", "diffs", "cost_unknown"})


if __name__ == "__main__":
    unittest.main()
