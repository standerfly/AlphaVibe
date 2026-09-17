"""個股詳情的損益口徑測試（2026-09-17 架構體檢 B1/B2）。

**這是一次測試遷移，不是新功能的測試。**

這條規則原本由 `poc/kb-mcp/tests/test_exit_signals.py::ChartStatsRenderTest`
守著，但它測的是 `report._chart_stats_html()`——舊版伺服器端 HTML 渲染，
2026-08-22 起正式服務已改用 `app/` + React，那支函式沒有任何活體呼叫端。
清死碼時發現：**這條規則只在死碼上有測試保護，真正在跑的 app/ 實作是
0 覆蓋**。所以不是刪掉測試了事，是把它搬到正在跑的程式碼上。

規則本身（002-entry-exit-signals FR-014／FR-015／SC-004）：
FIFO 算得出來時，「浮動損益」顯示的就必須是 FIFO 的數字。

為什麼這條規則值得專門守：2026-09-03 的獨立驗收抓到原本實作把浮動損益
維持加權平均、只在旁邊多加一格 FIFO，導致頁面與 `get_position_pnl`
對不起來——實測 14 檔可算的標的有 5 檔不同，3131 連正負號都相反。
使用者看到的損益跟工具算的損益不一致，是會影響買賣決策的錯誤。

執行：.venv/bin/python3 -m unittest discover -s app/tests
"""
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_KB = os.path.join(_ROOT, "poc", "kb-mcp")
if _KB not in sys.path:
    sys.path.insert(0, _KB)

from kb_store import KBStore  # noqa: E402
from app.routers.stock_detail import get_stock_detail  # noqa: E402

CODE = "3131"   # 借用當年出事的那一檔當測試標的


class PnlMethodTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-detail-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _setup_position(self, trades, current_price, snapshot_avg_cost):
        """建一個有持股快照、交易紀錄與現價的部位。

        snapshot_avg_cost 是持股快照裡的加權平均成本——刻意讓它跟交易
        紀錄推得出的 FIFO 成本不同，才能分辨顯示的到底是哪一種。
        """
        for action, shares, price, date in trades:
            self.store.save_trade_ledger_entry(
                CODE, "測試標的", action, shares, price, date)
        self.store.upsert_stock_price(CODE, current_price, "2026-09-17")
        self.store.save_holdings([{
            "code": CODE, "name": "測試標的",
            "shares": sum(s for a, s, _, _ in trades if a == "買")
                      - sum(s for a, s, _, _ in trades if a == "賣"),
            "avg_cost": snapshot_avg_cost,
        }], snapshot_date="2026-09-17")

    def _detail(self):
        return get_stock_detail(CODE, store=self.store)["holdings"]

    def test_fifo_available_means_pnl_is_fifo_not_weighted_average(self):
        """核心規則：兩種口徑數字不同時，顯示的必須是 FIFO 那個。"""
        # 買 1000@100、買 1000@200，賣掉 1000 股 → FIFO 剩下的是 200 那批
        self._setup_position(
            trades=[("買", 1000, 100.0, "2026-01-02"),
                    ("買", 1000, 200.0, "2026-02-02"),
                    ("賣", 1000, 180.0, "2026-03-02")],
            current_price=150.0,
            snapshot_avg_cost=100.0,   # 快照說成本 100（加權平均口徑）
        )
        h = self._detail()
        self.assertIsNotNone(h, "應該要有持股區塊")
        self.assertEqual(h["fifo"]["status"], "ok", "這組資料 FIFO 應該算得出來")

        fifo_pct = h["fifo"]["unrealized_pct"]
        self.assertAlmostEqual(h["pnl_pct"], fifo_pct, places=6,
                               msg="浮動損益必須等於 FIFO 的數字")
        self.assertIn("FIFO", h["pnl_source"])
        # 加權平均口徑（現價 150 vs 快照成本 100 = +50%）不該是顯示值
        self.assertNotAlmostEqual(h["pnl_pct"], 50.0, places=6,
                                  msg="顯示的是加權平均，這正是 2026-09-03 抓到的 bug")

    def test_weighted_average_estimate_is_still_kept_for_comparison(self):
        """FR-015：估算口徑不能消失，要留著供對照。"""
        self._setup_position(
            trades=[("買", 1000, 100.0, "2026-01-02"),
                    ("買", 1000, 200.0, "2026-02-02"),
                    ("賣", 1000, 180.0, "2026-03-02")],
            current_price=150.0, snapshot_avg_cost=100.0)
        h = self._detail()
        self.assertAlmostEqual(h["pnl_pct_estimate"], 50.0, places=6)
        self.assertIn("加權平均", h["cost_method_label"])

    def test_incomplete_history_falls_back_to_estimate_and_says_so(self):
        """FIFO 算不出來時（賣超過買，歷史不完整）回到估算值，並標明口徑。"""
        self._setup_position(
            trades=[("買", 100, 100.0, "2026-01-02"),
                    ("賣", 1000, 180.0, "2026-03-02")],
            current_price=150.0, snapshot_avg_cost=100.0)
        h = self._detail()
        self.assertNotEqual(h["fifo"]["status"], "ok",
                            "賣超過買，FIFO 不該回報 ok")
        self.assertAlmostEqual(h["pnl_pct"], 50.0, places=6,
                               msg="FIFO 不可用時要回到加權平均估算")
        self.assertIn("加權平均", h["pnl_source"])
        self.assertNotIn("FIFO・", h["pnl_source"])

    def test_no_trade_ledger_still_shows_estimate(self):
        """完全沒有交易紀錄（只有快照）時不能整格空白。"""
        self.store.upsert_stock_price(CODE, 150.0, "2026-09-17")
        self.store.save_holdings([{
            "code": CODE, "name": "測試標的", "shares": 1000, "avg_cost": 100.0,
        }], snapshot_date="2026-09-17")
        h = self._detail()
        self.assertIsNotNone(h["pnl_pct"], "沒有交易紀錄也要顯示估算損益")
        self.assertAlmostEqual(h["pnl_pct"], 50.0, places=6)

    def test_fifo_failure_does_not_break_the_whole_endpoint(self):
        """FIFO 算爆不該讓整支 API 掛掉——這是既有的防護，一併釘住。"""
        self._setup_position(
            trades=[("買", 1000, 100.0, "2026-01-02")],
            current_price=150.0, snapshot_avg_cost=100.0)
        import app.routers.stock_detail as mod
        original = mod.pnl.compute_position_pnl
        mod.pnl.compute_position_pnl = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("模擬 FIFO 計算失敗"))
        try:
            h = self._detail()
        finally:
            mod.pnl.compute_position_pnl = original
        self.assertIsNone(h["fifo"])
        self.assertIsNotNone(h["pnl_pct"], "FIFO 失敗仍要有估算值可看")


if __name__ == "__main__":
    unittest.main()
