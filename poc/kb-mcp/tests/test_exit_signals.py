"""進出場訊號層測試（002-entry-exit-signals，FR-001~FR-013）。

慣例同 tests/test_pnl.py：純函式測試不需資料庫；需要資料庫的部分一律
tempfile 獨立庫，**絕不碰正式庫 poc/data/**。

本檔案最重要的三個測試：
- NotSetTest：未設定門檻不得被當成安全（FR-003）
- ZeroExternalCallTest：新訊號不得新增外部 API 呼叫（FR-012）——
  階段A 就是在這裡從參數語意推論而出錯，害正式排程慢了 29 分鐘
- NoStanceWriteTest：新訊號不得寫入立場記錄（FR-013）
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import exit_signals  # noqa: E402
from kb_store import KBStore  # noqa: E402

PRICES = {"1111": {"price": 100.0, "price_date": "2026-09-02"}}


class ThresholdTriggerTest(unittest.TestCase):
    """FR-002：觸發判斷與 distance_pct。"""

    def test_stop_loss_triggered(self):
        out = exit_signals.evaluate_threshold(
            "1111", {"stop_loss": 110.0, "take_profit": 200.0}, PRICES)
        self.assertEqual(out["status"], "triggered_stop_loss")
        self.assertLess(out["distance_pct"], 0)  # 跌破＝負值
        self.assertIn("已觸發停損", out["detail"])

    def test_take_profit_triggered(self):
        out = exit_signals.evaluate_threshold(
            "1111", {"stop_loss": 50.0, "take_profit": 90.0}, PRICES)
        self.assertEqual(out["status"], "triggered_take_profit")
        self.assertGreater(out["distance_pct"], 0)  # 超過＝正值
        self.assertIn("已觸發停利", out["detail"])

    def test_within_range(self):
        out = exit_signals.evaluate_threshold(
            "1111", {"stop_loss": 80.0, "take_profit": 150.0}, PRICES)
        self.assertEqual(out["status"], "within_range")
        self.assertIn("未觸發", out["detail"])
        # 距離停損 20%、距離停利 50% → 取較近的停損
        self.assertAlmostEqual(out["distance_pct"], 20.0)

    def test_only_stop_loss_set(self):
        out = exit_signals.evaluate_threshold("1111", {"stop_loss": 80.0}, PRICES)
        self.assertEqual(out["status"], "within_range")
        self.assertIsNone(out["take_profit"])


class NotSetTest(unittest.TestCase):
    """FR-003：未設定門檻不得被當成安全——這是本階段最重要的防呆。"""

    def test_not_set_is_not_within_range(self):
        out = exit_signals.evaluate_threshold("1111", None, PRICES)
        self.assertEqual(out["status"], "not_set")
        self.assertNotEqual(out["status"], "within_range")
        # 不得填任何預設門檻值
        self.assertIsNone(out["stop_loss"])
        self.assertIsNone(out["take_profit"])
        self.assertIn("尚未設定", out["detail"])

    def test_not_set_has_no_distance(self):
        out = exit_signals.evaluate_threshold("1111", None, PRICES)
        self.assertIsNone(out["distance_pct"])


class NoPriceTest(unittest.TestCase):
    """FR-002：有門檻但查無現價，不得誤判為未觸發。"""

    def test_no_price_status(self):
        out = exit_signals.evaluate_threshold("9999", {"stop_loss": 50.0}, {})
        self.assertEqual(out["status"], "no_price")
        self.assertNotEqual(out["status"], "within_range")
        self.assertEqual(out["stop_loss"], 50.0)


class ThresholdBatchTest(unittest.TestCase):
    """FR-002／FR-011：批次判斷，單檔問題不影響整批。"""

    def test_mixed_statuses(self):
        thresholds = {
            "1111": {"stop_loss": 110.0},          # triggered
            "2222": {"stop_loss": 10.0},           # no_price
            "3333": None,                          # not_set
        }
        prices = {"1111": {"price": 100.0, "price_date": "2026-09-02"}}
        out = exit_signals.evaluate_all_thresholds(thresholds, prices)
        by_code = {p["code"]: p for p in out["positions"]}
        self.assertEqual(out["count"], 3)
        self.assertEqual(by_code["1111"]["status"], "triggered_stop_loss")
        self.assertEqual(by_code["2222"]["status"], "no_price")
        self.assertEqual(by_code["3333"]["status"], "not_set")
        self.assertEqual(out["summary"]["triggered_stop_loss"], 1)
        self.assertEqual(out["summary"]["not_set"], 1)


class RevenueTrendTest(unittest.TestCase):
    """FR-007：營收趨勢，擴大觀察期數。"""

    def test_falling(self):
        out = exit_signals.revenue_trend([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
        self.assertEqual(out["direction"], "falling")
        self.assertEqual(out["periods_used"], 6)
        self.assertLess(out["slope"], 0)

    def test_rising(self):
        out = exit_signals.revenue_trend([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertEqual(out["direction"], "rising")
        self.assertGreater(out["slope"], 0)

    def test_flat_when_recovering(self):
        """先崩後穩不算持續下滑——斜率為負但最新值高於中位數。"""
        out = exit_signals.revenue_trend([0.9, 0.30, 0.35, 0.40])
        self.assertEqual(out["direction"], "flat")

    def test_insufficient(self):
        out = exit_signals.revenue_trend([0.5, 0.4])
        self.assertEqual(out["direction"], "insufficient")
        self.assertIn("資料不足", out["detail"])

    def test_window_capped_at_periods(self):
        """超過觀察期數只取最近的，不會無限往前吃。"""
        out = exit_signals.revenue_trend(list(range(20)), periods=6)
        self.assertEqual(out["periods_used"], 6)
        self.assertEqual(out["values"], [14, 15, 16, 17, 18, 19])

    def test_none_values_filtered(self):
        out = exit_signals.revenue_trend([None, 0.9, None, 0.7, 0.5, 0.3])
        self.assertEqual(out["periods_used"], 4)


class DivergenceTest(unittest.TestCase):
    """FR-005／FR-006：背離偵測。"""

    def _pp(self, percentile, status="ok"):
        return {"percentile": percentile, "status": status,
                "basis": "測試", "sample_size": 100}

    def test_fundamentals_ahead(self):
        out = exit_signals.detect_divergence(
            "1111", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], self._pp(15.0))
        self.assertEqual(out["status"], "fundamentals_ahead")
        self.assertIn("基本面轉強但股價未跟上", out["basis"])
        # basis 必須同時含兩邊數字
        self.assertIn("15.0", out["basis"])
        self.assertIn("60%", out["basis"])

    def test_price_ahead(self):
        out = exit_signals.detect_divergence(
            "1111", [0.9, 0.8, 0.7, 0.6, 0.5, 0.4], self._pp(92.0))
        self.assertEqual(out["status"], "price_ahead")
        self.assertIn("高檔", out["basis"])

    def test_aligned(self):
        out = exit_signals.detect_divergence(
            "1111", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], self._pp(85.0))
        self.assertEqual(out["status"], "aligned")

    def test_insufficient_revenue_side(self):
        out = exit_signals.detect_divergence("1111", [0.5], self._pp(50.0))
        self.assertEqual(out["status"], "insufficient")
        self.assertIn("無法判斷背離", out["basis"])

    def test_insufficient_price_side(self):
        """單邊資料不足不得下結論（FR-006）。"""
        out = exit_signals.detect_divergence(
            "1111", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            {"percentile": None, "status": "insufficient", "basis": "樣本太少"})
        self.assertEqual(out["status"], "insufficient")
        self.assertNotEqual(out["status"], "fundamentals_ahead")


class SuggestionTest(unittest.TestCase):
    """FR-008／FR-009：觸發時的建議與洗版控制。"""

    def test_suggestion_for_each_triggered_status(self):
        for status in ("triggered_stop_loss", "triggered_take_profit",
                       "fundamentals_ahead", "price_ahead"):
            suggestion = exit_signals.build_suggestion({"status": status})
            self.assertTrue(suggestion, "%s 應該要有建議" % status)
            self.assertIn("可考慮", suggestion)

    def test_no_suggestion_when_not_triggered(self):
        """洗版控制：未觸發不填 suggested_action（research.md R-006）。"""
        for status in ("not_set", "within_range", "no_price", "aligned",
                       "insufficient"):
            self.assertIsNone(exit_signals.build_suggestion({"status": status}),
                              "%s 不該有建議" % status)

    def test_signal_not_swallowed_when_suggestion_missing(self):
        """FR-009：建議產不出來時訊號本身仍要在。"""
        suggestion, note = exit_signals.suggestion_or_note(
            {"status": "triggered_stop_loss"})
        self.assertIsNotNone(suggestion)
        # 未觸發時兩者皆 None，但呼叫端仍會拿到訊號本身
        suggestion2, note2 = exit_signals.suggestion_or_note({"status": "aligned"})
        self.assertIsNone(suggestion2)
        self.assertIsNone(note2)

    def test_suggestions_do_not_recommend_specific_stocks(self):
        """Q-006 邊界：建議不得延伸為主動選股。"""
        for status in exit_signals.TRIGGERED_STATUSES:
            suggestion = exit_signals.build_suggestion({"status": status})
            self.assertNotIn("建議買進", suggestion)
            self.assertNotIn("推薦標的", suggestion)


class StoreThresholdTest(unittest.TestCase):
    """FR-001：門檻儲存（append-only、驗證規則）。獨立暫存庫。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-exit-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_only_keeps_history(self):
        self.store.save_exit_threshold("2337", stop_loss=110.0, reason="第一次")
        self.store.save_exit_threshold("2337", stop_loss=120.0, reason="調整")
        self.assertEqual(self.store.get_exit_threshold("2337")["stop_loss"], 120.0)
        history = self.store.get_exit_threshold_history("2337")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["stop_loss"], 110.0)
        self.assertEqual(history[0]["reason"], "第一次")

    def test_never_set_returns_none(self):
        self.assertIsNone(self.store.get_exit_threshold("9999"))

    def test_validation_rules(self):
        with self.assertRaises(ValueError):
            self.store.save_exit_threshold("1111")           # 兩個都沒給
        with self.assertRaises(ValueError):
            self.store.save_exit_threshold("1111", stop_loss=0)
        with self.assertRaises(ValueError):
            self.store.save_exit_threshold("1111", stop_loss=200, take_profit=100)

    def test_get_all_returns_latest_per_code(self):
        self.store.save_exit_threshold("1111", stop_loss=10.0)
        self.store.save_exit_threshold("1111", stop_loss=20.0)
        self.store.save_exit_threshold("2222", take_profit=99.0)
        latest = self.store.get_all_exit_thresholds()
        self.assertEqual(latest["1111"]["stop_loss"], 20.0)
        self.assertEqual(latest["2222"]["take_profit"], 99.0)


class PureFunctionTest(unittest.TestCase):
    """FR-012 的結構性保證：訊號模組不得 import 任何外部 API client。"""

    def test_no_external_client_imports(self):
        import exit_signals as mod
        with open(mod.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("finmind_client", "twse_price_client", "tpex_client",
                          "urllib", "requests", "http.client"):
            self.assertNotIn("import %s" % forbidden, source,
                             "exit_signals 不得 import %s——訊號層必須是純函式，"
                             "資料由呼叫端提供（FR-012）" % forbidden)


class DailyFlowIntegrationTest(unittest.TestCase):
    """FR-011／FR-013：整合進每日流程後的兩條紅線。獨立暫存庫。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-flow-test-")
        self.store = KBStore(self.tmp)
        self.store.save_stance(code="1111", name="測試股", stance="存股",
                               reason="人工判斷", date="2026-09-01")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stance_count(self):
        return len(self.store.get_stance_history("1111", limit=999))

    def test_new_signals_do_not_write_stances(self):
        """FR-013：跑完含新訊號的檢視後，stances 筆數必須完全不變。

        實測正式庫 stances 474 筆中 437 筆已是機器自動寫入、PO 手寫僅 37 筆
        ——新訊號再寫進去會讓 PO 自己的判斷更難被看見。
        """
        import unittest.mock
        import review_engine

        before = self._stance_count()
        # 讓門檻觸發（concern_flag=True），確認即使觸發也不寫 stances
        self.store.save_exit_threshold("1111", stop_loss=999.0, reason="必觸發")
        self.store.upsert_stock_price("1111", 100.0, "2026-09-02")

        with unittest.mock.patch.object(
                review_engine, "general_review",
                side_effect=RuntimeError("跳過通用層，只驗新訊號")):
            review_engine.run_module_d_review("1111", self.store,
                                              data_dir=self.tmp)
        self.assertEqual(self._stance_count(), before,
                         "新訊號不得寫入 stances（FR-013）")

    def test_new_signal_failure_does_not_break_existing_checks(self):
        """FR-011：新訊號計算失敗時，既有檢查照常完成並寫入結果。"""
        import unittest.mock
        import review_engine

        with unittest.mock.patch.object(
                review_engine.exit_signals, "evaluate_threshold",
                side_effect=RuntimeError("模擬門檻計算爆炸")):
            with unittest.mock.patch.object(
                    review_engine, "general_review",
                    return_value={"growth_deceleration": {"flagged": False,
                                                          "detail": "正常"},
                                  "downside_risk": {"flagged": False,
                                                    "detail": "正常"},
                                  "manual_notes": {}}):
                out = review_engine.run_module_d_review("1111", self.store,
                                                        data_dir=self.tmp)
        # 既有通用層 2 筆照常寫入
        saved = self.store.get_module_d_results("1111")
        labels = [r["trigger_label"] for r in saved["results"]]
        self.assertIn("通用層／成長趨緩", labels)
        self.assertIn("通用層／下檔風險", labels)
        # 失敗的新訊號記在 errors，不中斷流程
        self.assertIn("exit_threshold", out["errors"])


class ChartStatsRenderTest(unittest.TestCase):
    """FR-014／FR-015：兩種損益口徑並存的渲染。

    斷言一律用**渲染形式**（帶 class="），不可用裸字串——report.py 把整份
    CSS 常數內嵌進每個頁面，裸字串會先命中樣式定義而不是實際渲染的元素
    （CLAUDE.md 2026-08-19 教訓）。
    """

    def test_fifo_ok_shows_both_with_labels(self):
        import report
        html = report._chart_stats_html(
            126.0, 140.0, "均價（加權平均估算・未扣賣出・非 FIFO，3筆買進）",
            fifo={"status": "ok", "unrealized_pnl": -1400.0, "unrealized_pct": -10.0})
        self.assertIn('class="stat stat--fifo"', html)
        self.assertIn("FIFO 未實現・未扣交易成本", html)
        # 既有估算值仍在，且標明口徑
        self.assertIn("非 FIFO", html)

    def test_history_incomplete_shows_cannot_compute_not_blank(self):
        import report
        html = report._chart_stats_html(
            126.0, 140.0, "均價（加權平均估算・未扣賣出・非 FIFO，3筆買進）",
            fifo={"status": "history_incomplete", "shortfall_shares": 280.0,
                  "unrealized_pnl": None})
        self.assertIn('class="stat stat--fifo-na"', html)
        self.assertIn("歷史不完整", html)
        # FR-015：估算值必須仍然顯示，不得因為 FIFO 算不出來就整格消失
        self.assertIn("非 FIFO", html)

    def test_no_fifo_result_falls_back_to_existing_display(self):
        import report
        html = report._chart_stats_html(126.0, 140.0, "均價（快照）", fifo=None)
        self.assertIn('class="chart-stats"', html)
        self.assertNotIn('class="stat stat--fifo"', html)


if __name__ == "__main__":
    unittest.main()
