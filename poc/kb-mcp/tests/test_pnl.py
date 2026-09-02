"""FIFO 損益計算測試（FR-001~FR-006、FR-011）。

比照 tests/test_holdings_sync.py 的慣例：純函式測試不需要資料庫，
需要資料庫的部分一律用 tempfile 建獨立庫，絕不碰正式庫 poc/data/。

本檔案最重要的一個測試是 test_share_unit_is_shares_not_lots——
股數單位是「股」不是「張」，金額即 股數 × 價格，不可 ×1000。
規格 research.md R-001 有完整證據，這個測試負責釘死它。
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pnl  # noqa: E402
from kb_store import KBStore  # noqa: E402


def _entry(code, action, shares, price, date, entry_id, name="測試股"):
    """組一列 trade_ledger 形狀的 dict（欄位名與 kb_store 一致）。"""
    return {"id": entry_id, "code": code, "name": name, "action": action,
            "shares": shares, "price": price, "date": date}


class ResolveCurrentPriceTest(unittest.TestCase):
    def test_returns_price_and_date(self):
        prices = {"2330": {"price": 1000.0, "price_date": "2026-08-31"}}
        self.assertEqual(pnl.resolve_current_price("2330", prices),
                         (1000.0, "2026-08-31"))

    def test_missing_code_returns_none_pair(self):
        self.assertEqual(pnl.resolve_current_price("9999", {}), (None, None))
        self.assertEqual(pnl.resolve_current_price("9999", None), (None, None))


class FifoBasicTest(unittest.TestCase):
    """FR-001／FR-002：多筆買進後部分賣出的已實現與未實現損益。"""

    def test_partial_sell_matches_oldest_lots_first(self):
        entries = [
            _entry("1111", "買", 100, 10.0, "2026-01-01", 1),
            _entry("1111", "買", 100, 20.0, "2026-01-02", 2),
            _entry("1111", "賣", 150, 30.0, "2026-01-03", 3),
        ]
        prices = {"1111": {"price": 25.0, "price_date": "2026-01-04"}}
        result = pnl.compute_position_pnl("1111", entries, prices)

        # 賣 150 股：先吃掉 100 股 @10（賺 20/股），再吃 50 股 @20（賺 10/股）
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["realized_pnl"], 100 * 20 + 50 * 10)
        # 剩 50 股 @20，現價 25 → 未實現 250
        self.assertAlmostEqual(result["shares_held"], 50)
        self.assertAlmostEqual(result["cost_basis"], 50 * 20.0)
        self.assertAlmostEqual(result["unrealized_pnl"], 50 * (25.0 - 20.0))
        self.assertAlmostEqual(result["unrealized_pct"], 25.0)
        self.assertEqual(result["cost_method"], "FIFO")
        self.assertFalse(result["fees_included"])

    def test_no_trades_status(self):
        result = pnl.compute_position_pnl("9999", [], {})
        self.assertEqual(result["status"], "no_trades")
        self.assertIsNone(result["realized_pnl"])


class ShareUnitTest(unittest.TestCase):
    """research.md R-001：股數單位是「股」，金額不可 ×1000。

    用大立光真實交易固定住：買 3 股 @2605 的成本必須是 7815 元，
    不是 7815000（若誤把單位當「張」就會變成後者）。
    """

    def test_share_unit_is_shares_not_lots(self):
        entries = [_entry("3008", "買", 3, 2605.0, "2026-07-15", 1, "大立光")]
        prices = {"3008": {"price": 7650.0, "price_date": "2026-08-31"}}
        result = pnl.compute_position_pnl("3008", entries, prices)

        self.assertAlmostEqual(result["cost_basis"], 7815.0)
        self.assertNotAlmostEqual(result["cost_basis"], 7815000.0)
        # 未實現＝3 ×（7650 - 2605）＝15135 元，同樣不帶 ×1000
        self.assertAlmostEqual(result["unrealized_pnl"], 15135.0)


class HistoryIncompleteTest(unittest.TestCase):
    """FR-004：賣出超過買進（流水表起始日之前的既有部位無進場紀錄）。"""

    def test_oversold_reports_shortfall_and_blocks_unrealized(self):
        entries = [
            _entry("2222", "買", 100, 10.0, "2026-01-01", 1),
            _entry("2222", "賣", 250, 15.0, "2026-01-02", 2),
        ]
        prices = {"2222": {"price": 20.0, "price_date": "2026-01-03"}}
        result = pnl.compute_position_pnl("2222", entries, prices)

        self.assertEqual(result["status"], "history_incomplete")
        self.assertAlmostEqual(result["shortfall_shares"], 150)
        # 只算配得上批次的部分：100 股 ×（15-10）
        self.assertAlmostEqual(result["realized_pnl"], 500.0)
        # 不輸出未實現損益，也不捏造缺失批次的成本
        self.assertIsNone(result["unrealized_pnl"])
        self.assertIsNone(result["unrealized_pct"])


class NoPriceAndClosedPositionTest(unittest.TestCase):
    """FR-003：已出清標的仍要回傳已實現損益；FR-002：查無現價的處理。"""

    def test_missing_current_price_still_reports_realized(self):
        entries = [
            _entry("3333", "買", 100, 10.0, "2026-01-01", 1),
            _entry("3333", "賣", 50, 12.0, "2026-01-02", 2),
        ]
        result = pnl.compute_position_pnl("3333", entries, {})

        self.assertEqual(result["status"], "no_price")
        self.assertAlmostEqual(result["realized_pnl"], 50 * 2.0)
        self.assertIsNone(result["unrealized_pnl"])

    def test_fully_closed_position_still_reports_realized(self):
        entries = [
            _entry("4444", "買", 100, 10.0, "2026-01-01", 1),
            _entry("4444", "賣", 100, 18.0, "2026-01-05", 2),
        ]
        result = pnl.compute_position_pnl("4444", entries, {})

        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["realized_pnl"], 800.0)
        self.assertAlmostEqual(result["shares_held"], 0)
        self.assertAlmostEqual(result["unrealized_pnl"], 0.0)


class SuspectedDuplicateTest(unittest.TestCase):
    """FR-006（PO 裁決 Q2-A）：疑似重複列照原樣計入，只附警示。"""

    def test_duplicates_counted_but_not_excluded(self):
        entries = [
            _entry("5555", "買", 50, 100.0, "2026-05-11", 1),
            _entry("5555", "買", 50, 100.0, "2026-05-11", 2),  # 疑似重複
            _entry("5555", "買", 50, 100.0, "2026-05-11", 3),  # 疑似重複
        ]
        prices = {"5555": {"price": 110.0, "price_date": "2026-08-31"}}
        result = pnl.compute_position_pnl("5555", entries, prices)

        self.assertEqual(result["suspected_duplicates"], 2)
        # 照原樣計入：三筆都算，共 150 股
        self.assertAlmostEqual(result["shares_held"], 150)
        self.assertAlmostEqual(result["cost_basis"], 15000.0)

    def test_no_duplicates_reports_zero(self):
        entries = [
            _entry("6666", "買", 50, 100.0, "2026-05-11", 1),
            _entry("6666", "買", 50, 101.0, "2026-05-11", 2),  # 價格不同，非重複
        ]
        result = pnl.compute_position_pnl("6666", entries, {})
        self.assertEqual(result["suspected_duplicates"], 0)


class BatchIsolationTest(unittest.TestCase):
    """FR-011：批次查詢時單一標的的問題不得影響其他標的。"""

    def test_mixed_statuses_do_not_break_batch(self):
        entries = [
            _entry("1111", "買", 100, 10.0, "2026-01-01", 1),   # ok
            _entry("2222", "賣", 100, 15.0, "2026-01-02", 2),   # history_incomplete
            _entry("3333", "買", 10, 50.0, "2026-01-03", 3),    # no_price
        ]
        prices = {"1111": {"price": 12.0, "price_date": "2026-08-31"}}
        result = pnl.compute_all_positions(entries, prices)

        by_code = {p["code"]: p for p in result["positions"]}
        self.assertEqual(result["count"], 3)
        self.assertEqual(by_code["1111"]["status"], "ok")
        self.assertEqual(by_code["2222"]["status"], "history_incomplete")
        self.assertEqual(by_code["3333"]["status"], "no_price")
        self.assertEqual(result["summary"]["ok"], 1)
        self.assertEqual(result["summary"]["history_incomplete"], 1)
        self.assertEqual(result["summary"]["no_price"], 1)


class StoreAccessTest(unittest.TestCase):
    """get_all_trade_entries()：獨立暫存庫，不碰正式庫。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_all_codes_sorted(self):
        self.store.save_trade_ledger_entry(
            code="2222", name="乙", action="買", shares=10, price=20.0,
            date="2026-01-02", source_ref="測試")
        self.store.save_trade_ledger_entry(
            code="1111", name="甲", action="買", shares=5, price=10.0,
            date="2026-01-01", source_ref="測試")
        self.store.save_trade_ledger_entry(
            code="1111", name="甲", action="賣", shares=5, price=12.0,
            date="2026-01-03", source_ref="測試")

        rows = self.store.get_all_trade_entries()
        self.assertEqual(len(rows), 3)
        # 排序為 code, date, id
        self.assertEqual([r["code"] for r in rows], ["1111", "1111", "2222"])
        self.assertEqual([r["date"] for r in rows[:2]], ["2026-01-01", "2026-01-03"])

    def test_existing_get_trade_ledger_unchanged(self):
        """不得影響既有 get_trade_ledger(code) 的行為。"""
        self.store.save_trade_ledger_entry(
            code="1111", name="甲", action="買", shares=5, price=10.0,
            date="2026-01-01", source_ref="測試")
        single = self.store.get_trade_ledger("1111")
        self.assertEqual(single["code"], "1111")
        self.assertEqual(single["count"], 1)
        with self.assertRaises(ValueError):
            self.store.get_trade_ledger("")


class ToolRegistrationTest(unittest.TestCase):
    """MCP 工具註冊守門：TOOLS 定義、dispatch、唯讀白名單三處都要有。

    這個 repo 先前完全沒有這類守門測試，漏加白名單會讓工具在 Cline
    唯讀路徑上靜默消失且不會被任何測試抓到。
    """

    def test_new_tools_registered_in_all_three_places(self):
        import server
        import server_readonly

        for tool_name in ("get_position_pnl", "get_price_position"):
            names = [t["name"] for t in server.TOOLS]
            self.assertIn(tool_name, names, "%s 不在 server.TOOLS" % tool_name)
            self.assertIn(tool_name, server_readonly.READONLY_TOOLS,
                          "%s 不在 READONLY_TOOLS 白名單" % tool_name)

    def test_tools_have_input_schema(self):
        import server
        for tool in server.TOOLS:
            if tool["name"] in ("get_position_pnl", "get_price_position"):
                self.assertIn("inputSchema", tool)
                self.assertIn("code", tool["inputSchema"].get("properties", {}))
                # code 為選填（省略＝全部）
                self.assertNotIn("code", tool["inputSchema"].get("required", []))


if __name__ == "__main__":
    unittest.main()
