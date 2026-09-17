"""report.py 輔助函式測試（2026-09-17 架構體檢 B2）。

背景：清死碼時發現 report.py 剩下的 504 行**全部是 app/ 正在用的**
（4 個 router 透過 11 個進入點呼叫），但單元測試覆蓋是 0——原本的
test_report.py 95 個測試全在測已刪除的伺服器端 HTML 渲染，沒有一個
測到這些還在跑的計算邏輯。

這支補上其中風險最高的一組：**會算出金額給人看的函式**。純顯示類
（esc／_render_sparkline_svg 等）刻意不測——不為覆蓋率而測。

執行：.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import report  # noqa: E402
from kb_store import KBStore  # noqa: E402


class InvestedAmountTest(unittest.TestCase):
    """_invested_amount()：加碼進度卡的「已投入」金額。

    這個函式的語意很容易寫錯：它要的是**目前部位的成本**，不是歷史
    買進總額。買了又賣掉的錢已經收回來了，若還算在「這檔投入多少
    預算」裡，出清過的標的會顯示投入滿額、明明手上一股都沒有。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-invested-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _trade(self, action, shares, price, date="2026-01-02"):
        self.store.save_trade_ledger_entry("2330", "台積電", action, shares, price, date)

    def _snapshot(self, shares, avg_cost):
        self.store.save_holdings([{"code": "2330", "name": "台積電",
                                   "shares": shares, "avg_cost": avg_cost}],
                                 snapshot_date="2026-09-17")

    def test_snapshot_with_avg_cost_wins(self):
        """快照有完整資料時最權威，不用流水表估算。"""
        self._snapshot(1000, 800.0)
        self._trade("買", 1000, 500.0)      # 流水表故意給不同的數字
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertAlmostEqual(amount, 800_000.0)
        self.assertEqual(shares, 1000)
        self.assertEqual(source, "庫存快照")

    def test_snapshot_without_avg_cost_uses_ledger_price(self):
        """實測快照的 avg_cost 常缺值（22 筆中僅 1 筆有值），這時股數
        仍以快照為準（權威），單價用流水表估。"""
        self._snapshot(1000, None)
        self._trade("買", 500, 600.0)
        self._trade("買", 500, 800.0)       # 買進加權平均 = 700
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertAlmostEqual(amount, 700_000.0)
        self.assertEqual(shares, 1000, "股數要用快照的，不是流水表的")
        self.assertEqual(source, "交易流水表估算")

    def test_sold_out_position_returns_none_not_full_amount(self):
        """核心語意：已出清的標的不該顯示「投入滿額」。"""
        self._trade("買", 1000, 800.0)
        self._trade("賣", 1000, 900.0, date="2026-02-02")
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertIsNone(amount, "出清過的標的不該還算投入金額")
        self.assertEqual(shares, 0)
        self.assertIsNone(source)

    def test_partial_sale_counts_only_remaining_position(self):
        """賣掉一部分時，投入金額只算手上剩下的。"""
        self._trade("買", 1000, 800.0)
        self._trade("賣", 400, 900.0, date="2026-02-02")
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertEqual(shares, 600, "淨股數 = 買 1000 - 賣 400")
        self.assertAlmostEqual(amount, 600 * 800.0)

    def test_research_only_stock_returns_none(self):
        """純研究標的（沒買過）回 None，呼叫端才能顯示「尚未投入」
        而不是「投入了 0 元」。"""
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertIsNone(amount)
        self.assertIsNone(source)

    def test_sell_only_history_does_not_divide_by_zero(self):
        """只有賣出紀錄（資料不完整）不能讓除法炸掉。"""
        self._trade("賣", 500, 900.0)
        amount, shares, source = report._invested_amount(self.store, "2330")
        self.assertIsNone(amount)


class AvgCostForChartTest(unittest.TestCase):
    """_avg_cost_for_chart()：走勢圖的均價虛線。"""

    def test_snapshot_avg_cost_preferred(self):
        got = report._avg_cost_for_chart({"avg_cost": 800.0}, [])
        self.assertAlmostEqual(got, 800.0)

    def test_falls_back_to_weighted_buy_price(self):
        entries = [{"action": "買", "shares": 1000, "price": 600.0},
                   {"action": "買", "shares": 1000, "price": 800.0}]
        self.assertAlmostEqual(report._avg_cost_for_chart({"avg_cost": None}, entries), 700.0)

    def test_sells_are_not_deducted(self):
        """刻意的簡化：估算值不扣賣出（跟 mockup 設計取捨一致，不做
        FIFO）。這裡釘住這個行為，避免日後有人「順手修正」成 FIFO 而
        跟 app/ 那條真正的 FIFO 路徑混淆。"""
        entries = [{"action": "買", "shares": 1000, "price": 600.0},
                   {"action": "賣", "shares": 900, "price": 900.0}]
        self.assertAlmostEqual(report._avg_cost_for_chart(None, entries), 600.0)

    def test_no_data_returns_none_not_zero(self):
        self.assertIsNone(report._avg_cost_for_chart(None, []))
        self.assertIsNone(report._avg_cost_for_chart({"avg_cost": None}, []))

    def test_only_sell_entries_returns_none(self):
        entries = [{"action": "賣", "shares": 500, "price": 900.0}]
        self.assertIsNone(report._avg_cost_for_chart(None, entries))


class CarryOverAvgCostTest(unittest.TestCase):
    """_carry_over_avg_cost()：貼帳單時把舊快照的成本帶過去。

    帳單本身沒有成本資料，若不沿用，每次匯入都會把已知的成本洗掉。
    """

    def test_carries_previous_avg_cost(self):
        rows = [{"code": "2330", "name": "台積電", "shares": 1000}]
        prev = {"holdings": [{"code": "2330", "avg_cost": 800.0}]}
        out = report._carry_over_avg_cost(rows, prev)
        self.assertAlmostEqual(out[0]["avg_cost"], 800.0)

    def test_new_code_has_no_avg_cost(self):
        rows = [{"code": "2317", "name": "鴻海", "shares": 2000}]
        out = report._carry_over_avg_cost(rows, {"holdings": [{"code": "2330", "avg_cost": 800.0}]})
        self.assertIsNone(out[0]["avg_cost"])

    def test_does_not_mutate_input(self):
        """docstring 明講回傳新清單、不修改傳入的 rows。"""
        rows = [{"code": "2330", "shares": 1000}]
        report._carry_over_avg_cost(rows, {"holdings": [{"code": "2330", "avg_cost": 800.0}]})
        self.assertNotIn("avg_cost", rows[0], "不該就地修改呼叫端的資料")

    def test_handles_empty_previous_snapshot(self):
        out = report._carry_over_avg_cost([{"code": "2330", "shares": 1}], {})
        self.assertIsNone(out[0]["avg_cost"])


class DiffHoldingsTest(unittest.TestCase):
    """_diff_holdings()：帳單預覽的三類差異。"""

    @staticmethod
    def _prev(*pairs):
        return {"holdings": [{"code": c, "shares": s} for c, s in pairs]}

    def test_added_removed_changed(self):
        rows = [{"code": "2330", "shares": 1000}, {"code": "2317", "shares": 2000}]
        out = report._diff_holdings(rows, self._prev(("2330", 500), ("2454", 300)))
        self.assertEqual([r["code"] for r in out["added"]], ["2317"])
        self.assertEqual([h["code"] for h in out["removed"]], ["2454"])
        self.assertEqual(out["changed"][0]["code"], "2330")
        self.assertEqual(out["changed"][0]["prev_shares"], 500)
        self.assertEqual(out["changed"][0]["new_shares"], 1000)

    def test_same_shares_not_reported_as_changed(self):
        rows = [{"code": "2330", "shares": 1000}]
        out = report._diff_holdings(rows, self._prev(("2330", 1000)))
        self.assertEqual(out["changed"], [])

    def test_removed_means_absent_from_statement_not_sold(self):
        """「消失」只代表這次帳單沒印到，不代表出清——函式不替使用者
        下判斷，所以它只會出現在 removed，不會被算成 changed 到 0 股。"""
        out = report._diff_holdings([], self._prev(("2330", 1000)))
        self.assertEqual([h["code"] for h in out["removed"]], ["2330"])
        self.assertEqual(out["changed"], [])

    def test_empty_previous_makes_everything_added(self):
        rows = [{"code": "2330", "shares": 1000}]
        out = report._diff_holdings(rows, {})
        self.assertEqual(len(out["added"]), 1)
        self.assertEqual(out["removed"], [])


if __name__ == "__main__":
    unittest.main()
