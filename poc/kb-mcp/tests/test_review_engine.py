"""review_engine.py 測試：FR-051 模組D通用檢視層（成長趨緩／下檔風險）、
FR-052 策略專屬層、FR-053 老芋頭動向比對、FR-054 部位控制建議。

FR-051/052 全部用 mock 頂替 finmind_client／screener 的查詢函式，不打真實
外部 API；FR-053/054 需要 KBStore（老芋頭交易表、庫存、交易流水、股價/
主題快取都是本機 SQLite 查詢，不涉及外部 API），用 tempfile 建立真實但
臨時的資料庫，比照 test_traceability.py 既有慣例。
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import review_engine  # noqa: E402
import screener  # noqa: E402
from kb_store import KBStore  # noqa: E402


def _revenue_yoy(values):
    """values: list of yoy_growth（None 或 float），依時間升冪排列。"""
    return {"stock_id": "2330", "errors": [],
            "revenue_yoy": [{"revenue_year": 2026, "revenue_month": i + 1,
                             "revenue": 100, "yoy_growth": v}
                            for i, v in enumerate(values)]}


def _per_history(values):
    """values: list of PER（None 或 float），依時間升冪排列。"""
    return {"stock_id": "2330", "errors": [],
            "per_history": [{"date": "2026-%02d-01" % (i % 12 + 1), "PER": v,
                             "PBR": None, "dividend_yield": None}
                            for i, v in enumerate(values)]}


class GrowthDecelerationTest(unittest.TestCase):
    def test_flags_three_consecutive_declining_months(self):
        out = review_engine._growth_deceleration(_revenue_yoy([0.9, 0.7, 0.55, 0.40]))
        self.assertTrue(out["flagged"])
        self.assertIn("70%", out["detail"])
        self.assertIn("55%", out["detail"])
        self.assertIn("40%", out["detail"])

    def test_does_not_flag_when_not_strictly_declining(self):
        # 最近3個非null：0.30, 0.35, 0.40 —— 上升不是下滑
        out = review_engine._growth_deceleration(_revenue_yoy([0.9, 0.30, 0.35, 0.40]))
        self.assertFalse(out["flagged"])

    def test_does_not_flag_when_turns_negative(self):
        # 連續下滑但最後轉負，不算「成長趨緩」（轉負是另一個問題）
        out = review_engine._growth_deceleration(_revenue_yoy([0.20, 0.10, -0.05]))
        self.assertFalse(out["flagged"])

    def test_insufficient_data_fewer_than_three_non_null(self):
        out = review_engine._growth_deceleration(_revenue_yoy([None, None, 0.5]))
        self.assertFalse(out["flagged"])
        self.assertIn("資料不足", out["detail"])

    def test_insufficient_data_when_revenue_yoy_key_missing(self):
        out = review_engine._growth_deceleration(
            {"stock_id": "2330", "errors": ["FinMind 呼叫失敗（TaiwanStockMonthRevenue）：模擬斷網"]})
        self.assertFalse(out["flagged"])
        self.assertIn("資料不足", out["detail"])


class DownsideRiskTest(unittest.TestCase):
    def test_flags_when_current_per_above_percentile_threshold(self):
        # 30 筆歷史 PER，值 10~39（線性遞增），目前(最新一筆)PER=39 明顯偏高
        values = [10.0 + i for i in range(30)]
        out = review_engine._downside_risk(_per_history(values))
        self.assertTrue(out["flagged"])
        self.assertIsNotNone(out["estimated_downside_pct"])
        self.assertGreater(out["estimated_downside_pct"], 0)

    def test_does_not_flag_when_current_per_in_normal_range(self):
        # 29 筆歷史 10~38 分布 + 目前(最新)PER=20，仍達 PERCENTILE_MIN_POINTS(30)
        # 走百分位數門檻分支；20 落在區間中段，非偏高
        values = [10.0 + i for i in range(29)] + [20.0]
        self.assertEqual(len(values), 30)
        out = review_engine._downside_risk(_per_history(values))
        self.assertFalse(out["flagged"])
        self.assertIsNone(out["estimated_downside_pct"])
        self.assertIn("90百分位", out["detail"])

    def test_fallback_to_max_times_point_nine_when_few_data_points(self):
        # 只有 6 筆（未達 PERCENTILE_MIN_POINTS=30），退回 max*0.9 門檻
        # 值：10,10,10,10,10,20 → max=20 → 門檻=18；目前PER=20 > 18 → flagged
        out = review_engine._downside_risk(_per_history([10.0, 10.0, 10.0, 10.0, 10.0, 20.0]))
        self.assertTrue(out["flagged"])
        self.assertIn("簡化門檻", out["detail"])

    def test_insufficient_data_fewer_than_minimum(self):
        out = review_engine._downside_risk(_per_history([10.0, 12.0, None]))
        self.assertFalse(out["flagged"])
        self.assertIsNone(out["estimated_downside_pct"])
        self.assertIn("資料不足", out["detail"])

    def test_insufficient_data_when_per_history_key_missing(self):
        out = review_engine._downside_risk(
            {"stock_id": "2330", "errors": ["FinMind 呼叫失敗（TaiwanStockPER）：模擬斷網"]})
        self.assertFalse(out["flagged"])
        self.assertIsNone(out["estimated_downside_pct"])
        self.assertIn("資料不足", out["detail"])


class GeneralReviewTest(unittest.TestCase):
    def test_general_review_shape_and_manual_notes_default_none(self):
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value=_revenue_yoy([0.9, 0.7, 0.55, 0.40])) as mock_yoy, \
             unittest.mock.patch.object(
                finmind_client, "get_per_history",
                return_value=_per_history([10.0 + i for i in range(20)] + [20.0])) as mock_per:
            out = review_engine.general_review("2330", data_dir="/tmp/fake")

        mock_yoy.assert_called_once_with("2330", data_dir="/tmp/fake", token=None)
        mock_per.assert_called_once_with("2330", data_dir="/tmp/fake", token=None)

        self.assertEqual(out["code"], "2330")
        self.assertTrue(out["growth_deceleration"]["flagged"])
        self.assertFalse(out["downside_risk"]["flagged"])
        self.assertEqual(out["manual_notes"], {
            "earnings_delivery": None,
            "good_news_priced_in": None,
            "estimate_revision": None,
        })
        self.assertIn("checked_at", out)
        self.assertTrue(out["checked_at"])  # 非空字串


def _screen_result(code, peg=None, drawdown_pct=None, revenue_yoy=None, error=None):
    """組出 screener.screen_stocks() 回傳形狀的假資料，只填 strategy_specific_review
    用得到的欄位（peg/drawdown_pct/revenue_yoy/error），其餘略過。"""
    row = {"code": code, "name": None, "peg": peg, "drawdown_pct": drawdown_pct,
           "revenue_yoy": revenue_yoy, "error": error}
    return {"results": [row], "total": 1}


class StrategySpecificReviewTest(unittest.TestCase):
    """FR-052 策略專屬層：兩套策略的假說失效判斷。"""

    def test_strategy1_peg_rebound_triggers_invalidation(self):
        # peg_deep_dip_concentration：peg_min=1.0，drawdown_max=0.15
        # PEG回升到1.15（>=1.0）觸發；回檔仍深(0.45)未收斂，不觸發第二條
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=1.15, drawdown_pct=0.45,
                                            revenue_yoy=0.10)) as mock_screen:
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        mock_screen.assert_called_once_with(["2330"], data_dir="/tmp/fake", token=None)
        self.assertTrue(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIn("PEG已回升至1.15", out["reasons"][0])
        self.assertIn("門檻1.0", out["reasons"][0])
        self.assertEqual(out["current_values"],
                         {"peg": 1.15, "drawdown_pct": 0.45, "revenue_yoy": 0.10})

    def test_strategy1_drawdown_convergence_triggers_invalidation(self):
        # PEG仍便宜(0.8)未觸發；回檔收斂到0.10（<=0.15）觸發
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=0.8, drawdown_pct=0.10,
                                            revenue_yoy=0.10)):
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        self.assertTrue(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIn("回檔已收斂至10.0%", out["reasons"][0])
        self.assertIn("門檻15.0%", out["reasons"][0])

    def test_strategy1_neither_condition_triggered(self):
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=0.8, drawdown_pct=0.45,
                                            revenue_yoy=0.10)):
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        self.assertFalse(out["invalidated"])
        self.assertEqual(out["reasons"], [])

    def test_strategy1_both_conditions_triggered_has_two_reasons(self):
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=1.20, drawdown_pct=0.05,
                                            revenue_yoy=0.10)):
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        self.assertTrue(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 2)
        self.assertTrue(any("PEG" in r for r in out["reasons"]))
        self.assertTrue(any("回檔" in r for r in out["reasons"]))

    def test_strategy2_drawdown_convergence_triggers_invalidation(self):
        # revenue_high_price_dip：drawdown_max=0.15，revenue_yoy_max=0.0
        # 回檔收斂到0.12（<=0.15）觸發；營收年增率仍正(0.35)不觸發
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=None, drawdown_pct=0.12,
                                            revenue_yoy=0.35)):
            out = review_engine.strategy_specific_review(
                "2330", "revenue_high_price_dip", data_dir="/tmp/fake")

        self.assertTrue(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIn("回檔已收斂至12.0%", out["reasons"][0])

    def test_strategy2_revenue_turns_negative_triggers_invalidation(self):
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=None, drawdown_pct=0.25,
                                            revenue_yoy=-0.05)):
            out = review_engine.strategy_specific_review(
                "2330", "revenue_high_price_dip", data_dir="/tmp/fake")

        self.assertTrue(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIn("營收年增率已降至-5.0%", out["reasons"][0])
        self.assertIn("門檻0.0%", out["reasons"][0])

    def test_strategy2_neither_condition_triggered(self):
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", peg=None, drawdown_pct=0.25,
                                            revenue_yoy=0.35)):
            out = review_engine.strategy_specific_review(
                "2330", "revenue_high_price_dip", data_dir="/tmp/fake")

        self.assertFalse(out["invalidated"])
        self.assertEqual(out["reasons"], [])

    def test_unknown_strategy_id_returns_error_shape(self):
        out = review_engine.strategy_specific_review("2330", "not_a_real_strategy")
        self.assertFalse(out["invalidated"])
        self.assertEqual(out["reasons"], ["查無此策略代號：not_a_real_strategy"])
        self.assertEqual(out["current_values"],
                         {"peg": None, "drawdown_pct": None, "revenue_yoy": None})
        self.assertEqual(out["strategy_id"], "not_a_real_strategy")
        self.assertIn("checked_at", out)

    def test_query_failure_does_not_misreport_invalidation(self):
        # screen_stocks 該筆 error 不是 None：資料不足或查詢失敗，
        # invalidated 必須是 False（保守原則，不確定就不誤報失效）。
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value=_screen_result("2330", error="非預期錯誤：模擬斷網")):
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        self.assertFalse(out["invalidated"])
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIn("資料不足或查詢失敗，無法判斷", out["reasons"][0])
        self.assertIn("模擬斷網", out["reasons"][0])
        self.assertEqual(out["current_values"],
                         {"peg": None, "drawdown_pct": None, "revenue_yoy": None})

    def test_missing_result_row_does_not_misreport_invalidation(self):
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value={"results": [], "total": 0}):
            out = review_engine.strategy_specific_review(
                "2330", "peg_deep_dip_concentration", data_dir="/tmp/fake")

        self.assertFalse(out["invalidated"])
        self.assertIn("資料不足或查詢失敗，無法判斷", out["reasons"][0])


class LaoyutouSignalReviewTest(unittest.TestCase):
    """FR-053 老芋頭動向比對：需要真實 KBStore（老芋頭交易表/庫存都是本機
    SQLite 查詢，不涉外部 API），用 tempfile 建臨時資料庫，比照
    test_traceability.py 既有慣例。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-laoyutou-review-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    @staticmethod
    def _date(days_ago):
        return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()

    def test_sell_signal_when_po_holds_mentions_holding(self):
        self.store.save_holdings([{"code": "2330", "shares": 1000}])
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="賣", shares=500, price=900.0,
            date=self._date(3))
        out = review_engine.laoyutou_signal_review("2330", self.store)

        self.assertTrue(out["has_signal"])
        self.assertTrue(out["po_holds"])
        self.assertIn("賣出500.0股（900.0元）", out["finding"])
        self.assertIn("你目前持有此檔", out["finding"])
        self.assertEqual(len(out["recent_trades"]), 1)
        self.assertIn("checked_at", out)

    def test_buy_signal_when_po_not_holding_no_holding_phrase(self):
        # 不存 holdings，代表 PO 沒有持有這檔
        self.store.save_laoyutou_trade(
            code="6805", name="鴻勁", action="買", shares=2000, price=1200.0,
            date=self._date(1))
        out = review_engine.laoyutou_signal_review("6805", self.store)

        self.assertTrue(out["has_signal"])
        self.assertFalse(out["po_holds"])
        self.assertIn("買進2000.0股（1200.0元）", out["finding"])
        self.assertNotIn("你目前持有此檔", out["finding"])

    def test_no_signal_outside_lookback_window(self):
        # 15 天前的交易，超出預設 14 天視窗，不該被視為「近期訊號」
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="買", shares=1000, price=900.0,
            date=self._date(15))
        out = review_engine.laoyutou_signal_review("2330", self.store, lookback_days=14)

        self.assertFalse(out["has_signal"])
        self.assertEqual(out["recent_trades"], [])
        self.assertEqual(out["finding"], "近14天無老芋頭相關動向")

    def test_finding_appends_reason_when_present(self):
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="賣", shares=300, price=950.0,
            date=self._date(2), reason="轉倉到更看好的標的")
        out = review_engine.laoyutou_signal_review("2330", self.store)

        self.assertIn("原因：轉倉到更看好的標的", out["finding"])

    def test_multiple_trades_recent_trades_lists_all_finding_uses_latest(self):
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="買", shares=1000, price=850.0,
            date=self._date(10))
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="賣", shares=400, price=920.0,
            date=self._date(2))
        out = review_engine.laoyutou_signal_review("2330", self.store)

        # 兩筆都在14天視窗內，recent_trades 要完整列出，不能只保留一筆
        self.assertEqual(len(out["recent_trades"]), 2)
        # finding 以最新一筆（賣出）為主
        self.assertIn("賣出400.0股（920.0元）", out["finding"])

    def test_does_not_fabricate_fundamental_judgment(self):
        """FR-053 刻意的範圍限制：finding 不該出現任何基本面轉強/轉弱推論
        字眼，只陳述事實。"""
        self.store.save_laoyutou_trade(
            code="2330", name="台積電", action="賣", shares=500, price=900.0,
            date=self._date(1))
        out = review_engine.laoyutou_signal_review("2330", self.store)
        for forbidden in ("基本面轉弱", "基本面轉強", "建議", "應該"):
            self.assertNotIn(forbidden, out["finding"])


class PositionControlSuggestionTest(unittest.TestCase):
    """FR-054 部位控制建議：同樣需要真實 KBStore。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-position-control-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_new_build_with_confidence_level_gives_initial_position(self):
        # 沒有 holdings、沒有 trade_ledger 紀錄 = 這檔第一次建倉
        out = review_engine.position_control_suggestion(
            "2330", self.store, confidence_level="很好")

        self.assertEqual(out["next_add_sequence"], 1)
        self.assertEqual(out["suggested_add_pct"], 0.40)
        self.assertEqual(out["suggested_initial_position_pct"], 0.08)
        self.assertIsNone(out["current_position_pct"])
        self.assertIsNone(out["theme"])
        self.assertIsNone(out["theme_concentration_pct"])
        self.assertIsNone(out["concentration_warning"])
        self.assertIn("首次建倉", out["detail"])
        self.assertIn("很好", out["detail"])
        self.assertIn("8.0%", out["detail"])
        self.assertIn("第1次加碼", out["detail"])
        self.assertIn("40.0%", out["detail"])
        self.assertIn("非投資組合佔比", out["detail"])

    def test_new_build_without_confidence_level_gives_no_initial_position(self):
        out = review_engine.position_control_suggestion("2330", self.store)
        self.assertEqual(out["next_add_sequence"], 1)
        self.assertIsNone(out["suggested_initial_position_pct"])

    def test_existing_position_computes_correct_next_add_sequence(self):
        self.store.save_trade_ledger_entry(
            code="2330", name="台積電", action="買", shares=1000, price=800.0,
            date="2026-01-01", add_sequence=1)
        self.store.save_trade_ledger_entry(
            code="2330", name="台積電", action="買", shares=500, price=850.0,
            date="2026-02-01", add_sequence=2)
        # 賣出動作跟加碼次序無關（save_trade_ledger_entry 強制寫入 NULL），
        # 不該被算進「已加碼次數」。
        self.store.save_trade_ledger_entry(
            code="2330", name="台積電", action="賣", shares=200, price=900.0,
            date="2026-03-01")

        out = review_engine.position_control_suggestion(
            "2330", self.store, confidence_level="非常高")

        self.assertEqual(out["next_add_sequence"], 3)
        self.assertEqual(out["suggested_add_pct"], 0.15)
        # 不是第一次建倉，即使有給 confidence_level 也不該給初始部位建議
        self.assertIsNone(out["suggested_initial_position_pct"])
        self.assertIn("第3次加碼", out["detail"])

    def test_exceeds_five_adds_notes_out_of_schedule_range(self):
        for seq in range(1, 6):
            self.store.save_trade_ledger_entry(
                code="2330", name="台積電", action="買", shares=100, price=800.0,
                date="2026-0%d-01" % seq, add_sequence=seq)

        out = review_engine.position_control_suggestion("2330", self.store)

        self.assertEqual(out["next_add_sequence"], 6)
        self.assertIsNone(out["suggested_add_pct"])
        self.assertIn("已超出預設遞減加碼表範圍（僅定義到第5次）", out["detail"])
        self.assertIn("建議依實際情況自行判斷", out["detail"])

    def test_concentration_warning_when_single_stock_and_theme_over_threshold(self):
        self.store.save_holdings([
            {"code": "AAA", "shares": 1000},
            {"code": "BBB", "shares": 100},
        ])
        self.store.upsert_stock_price("AAA", 100.0, "2026-07-01")
        self.store.upsert_stock_price("BBB", 100.0, "2026-07-01")
        self.store.save_stock_theme("AAA", "半導體")
        self.store.save_stock_theme("BBB", "半導體")

        out = review_engine.position_control_suggestion("AAA", self.store)

        # AAA: 100000 / 110000 * 100 ≈ 90.9% ≥ 15% 單股門檻
        self.assertGreaterEqual(out["current_position_pct"], 15.0)
        # 半導體主題：110000 / 110000 * 100 = 100% ≥ 50% 主題門檻
        self.assertGreaterEqual(out["theme_concentration_pct"], 50.0)
        self.assertIsNotNone(out["concentration_warning"])
        self.assertIn("單股佔比已達", out["concentration_warning"])
        self.assertIn("半導體", out["concentration_warning"])
        self.assertIn("主題佔比已達", out["concentration_warning"])

    def test_no_warning_when_under_thresholds(self):
        self.store.save_holdings([
            {"code": "AAA", "shares": 10},
            {"code": "BBB", "shares": 1000},
        ])
        self.store.upsert_stock_price("AAA", 100.0, "2026-07-01")
        self.store.upsert_stock_price("BBB", 100.0, "2026-07-01")

        out = review_engine.position_control_suggestion("AAA", self.store)
        # AAA: 1000 / 101000 * 100 ≈ 1%，遠低於15%門檻
        self.assertLess(out["current_position_pct"], 15.0)
        self.assertIsNone(out["concentration_warning"])

    def test_current_position_pct_none_when_no_price_cache_no_crash(self):
        self.store.save_holdings([{"code": "CCC", "shares": 500}])
        out = review_engine.position_control_suggestion("CCC", self.store)

        self.assertIsNone(out["current_position_pct"])
        self.assertIn("尚無市值資料", out["detail"])

    def test_theme_concentration_matches_report_py_calculation_method(self):
        """驗證 FR-054 的市值/主題集中度計算方式跟 report.py「我的庫存與
        分析」既有頁面完全一致：市值=股數×股價快取，查不到股價的持股
        （FFF）不計入市值也不計入分母，主題集中度只算有標記主題且有
        市值的持股。這裡獨立重算一次（不呼叫 review_engine 內部函式）當
        oracle，交叉比對兩邊算出同一個數字。"""
        self.store.save_holdings([
            {"code": "DDD", "shares": 100},
            {"code": "EEE", "shares": 200},
            {"code": "FFF", "shares": 300},  # 故意不給股價快取
        ])
        self.store.upsert_stock_price("DDD", 50.0, "2026-07-01")
        self.store.upsert_stock_price("EEE", 25.0, "2026-07-01")
        self.store.save_stock_theme("DDD", "電動車")
        self.store.save_stock_theme("EEE", "電動車")
        self.store.save_stock_theme("FFF", "AI")

        out = review_engine.position_control_suggestion("DDD", self.store)

        # ---- oracle：獨立複製 report.py 的演算法，不呼叫 review_engine ----
        price_map = {"DDD": 50.0, "EEE": 25.0}  # FFF 沒有股價快取
        shares_map = {"DDD": 100, "EEE": 200, "FFF": 300}
        theme_map = {"DDD": "電動車", "EEE": "電動車", "FFF": "AI"}
        market_values = {c: shares_map[c] * p for c, p in price_map.items()}
        total_value = sum(market_values.values())
        theme_totals = {}
        for c, v in market_values.items():
            theme = theme_map.get(c)
            if theme:
                theme_totals[theme] = theme_totals.get(theme, 0) + v
        expected_current_pct = market_values["DDD"] / total_value * 100
        expected_theme_pct = theme_totals["電動車"] / total_value * 100

        self.assertAlmostEqual(out["current_position_pct"], expected_current_pct)
        self.assertEqual(out["theme"], "電動車")
        self.assertAlmostEqual(out["theme_concentration_pct"], expected_theme_pct)
        # FFF 沒有股價快取，不該污染分母：DDD+EEE 的市值合計是 10000
        # （100*50 + 200*25），FFF 的 300 股完全不計入。
        self.assertEqual(total_value, 10000)


class AutoRecordFindingsTest(unittest.TestCase):
    """FR-055 立場自動回寫機制：同樣需要真實 KBStore（save_stance/
    get_latest_stance/get_stance_history 都是本機 SQLite 查詢）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-auto-record-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_skips_when_no_existing_stance(self):
        out = review_engine.auto_record_findings(
            "2330", self.store,
            [{"trigger_label": "通用層／成長趨緩", "concern_flag": False,
              "detail": "營收年增率穩定，未見趨緩"}])

        self.assertTrue(out["skipped"])
        self.assertEqual(out["skip_reason"],
                         "查無既有立場，系統不建立新立場，略過自動記錄")
        self.assertEqual(out["written"], [])
        self.assertFalse(out["has_conflict"])
        self.assertEqual(out["code"], "2330")
        # 沒有既有立場，不該建立任何 stance 記錄
        self.assertEqual(self.store.get_stance_history("2330"), [])

    def test_each_finding_writes_its_own_record_consistent_all_no_conflict(self):
        self.store.save_stance("2330", "觀察", reason="人工初始建倉觀察")

        findings = [
            {"trigger_label": "策略層／peg_deep_dip_concentration",
             "concern_flag": False, "detail": "PEG仍低於門檻，假說未失效"},
            {"trigger_label": "通用層／成長趨緩",
             "concern_flag": False, "detail": "營收年增率穩定，未見趨緩"},
        ]
        out = review_engine.auto_record_findings(
            "2330", self.store, findings, date="2026-07-29")

        self.assertFalse(out["skipped"])
        self.assertIsNone(out["skip_reason"])
        self.assertFalse(out["has_conflict"])
        self.assertEqual(len(out["written"]), 2)

        history = self.store.get_stance_history("2330")
        # 原本人工那筆 + 2 筆新的系統記錄 = 3 筆
        self.assertEqual(len(history), 3)

        for w in out["written"]:
            self.assertNotIn("⚠️與同批其他檢視結果不一致", w["reason"])
            self.assertIn("[模組D自動檢視 2026-07-29／%s]" % w["trigger_label"],
                         w["reason"])

        written_labels = {w["trigger_label"] for w in out["written"]}
        self.assertEqual(written_labels,
                         {"策略層／peg_deep_dip_concentration", "通用層／成長趨緩"})

    def test_all_records_reuse_existing_stance_value_no_fr013_conflict(self):
        self.store.save_stance("2330", "加碼", reason="人工初始加碼決策")

        findings = [
            {"trigger_label": "策略層／peg_deep_dip_concentration",
             "concern_flag": False, "detail": "假說未失效"},
        ]
        out = review_engine.auto_record_findings("2330", self.store, findings)

        history = self.store.get_stance_history("2330")
        for record in history:
            self.assertEqual(record["stance"], "加碼")

        # 額外驗證：用相同 stance 值重複呼叫 save_stance 不會觸發 FR-013
        # 衝突偵測（conflict 應為 False）。
        result = self.store.save_stance("2330", "加碼", reason="驗證用")
        self.assertFalse(result["conflict"])
        self.assertTrue(result["saved"])
        self.assertFalse(out["has_conflict"])

    def test_written_stance_record_id_matches_history(self):
        self.store.save_stance("2330", "觀察", reason="人工初始建倉觀察")
        findings = [
            {"trigger_label": "通用層／下檔風險",
             "concern_flag": True, "detail": "PE偏高，潛在跌幅估計約15%"},
        ]
        out = review_engine.auto_record_findings(
            "2330", self.store, findings, date="2026-07-29")

        written = out["written"][0]
        history = self.store.get_stance_history("2330")
        matched = [h for h in history if h["id"] == written["stance_record_id"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["reason"], written["reason"])
        self.assertEqual(matched[0]["source_ref"],
                         "模組D自動檢視／通用層／下檔風險")
        self.assertEqual(matched[0]["date"], "2026-07-29")

    def test_conflicting_concern_flags_sets_has_conflict_and_annotates_all(self):
        self.store.save_stance("2330", "觀察", reason="人工初始建倉觀察")
        findings = [
            {"trigger_label": "策略層／peg_deep_dip_concentration",
             "concern_flag": True,
             "detail": "PEG已回升至1.15（門檻1.0），假說可能失效"},
            {"trigger_label": "通用層／成長趨緩",
             "concern_flag": False, "detail": "營收年增率穩定，未見趨緩"},
        ]
        out = review_engine.auto_record_findings(
            "2330", self.store, findings, date="2026-07-29")

        self.assertTrue(out["has_conflict"])
        self.assertEqual(len(out["written"]), 2)

        for w in out["written"]:
            self.assertIn("⚠️與同批其他檢視結果不一致", w["reason"])
            self.assertIn(
                "[策略層／peg_deep_dip_concentration] 標記需留意", w["reason"])
            self.assertIn("[通用層／成長趨緩] 標記無異常", w["reason"])
            # 衝突提示之後仍要看得到原始發現內容
            self.assertIn("PEG已回升至1.15" if "peg" in w["trigger_label"]
                         else "營收年增率穩定", w["reason"])

    def test_default_date_is_today_when_omitted(self):
        self.store.save_stance("2330", "觀察", reason="人工初始建倉觀察")
        findings = [
            {"trigger_label": "通用層／成長趨緩",
             "concern_flag": False, "detail": "未見趨緩"},
        ]
        out = review_engine.auto_record_findings("2330", self.store, findings)

        today = datetime.date.today().isoformat()
        self.assertIn("[模組D自動檢視 %s／" % today, out["written"][0]["reason"])


class GetAssociatedStrategiesTest(unittest.TestCase):
    """FR-052 策略關聯判斷：review_engine.get_associated_strategies 只是薄
    包裝，實際SQL在 KBStore.get_associated_frameworks（已在 test_kb.py
    涵蓋完整查詢邏輯），這裡只驗證委派正確。"""

    def test_delegates_to_store_method(self):
        store = unittest.mock.Mock()
        store.get_associated_frameworks.return_value = ["peg_deep_dip_concentration"]
        out = review_engine.get_associated_strategies("2330", store)
        store.get_associated_frameworks.assert_called_once_with("2330")
        self.assertEqual(out, ["peg_deep_dip_concentration"])

    def test_never_scanned_returns_empty_list(self):
        store = unittest.mock.Mock()
        store.get_associated_frameworks.return_value = []
        self.assertEqual(review_engine.get_associated_strategies("9999", store), [])


class RunModuleDReviewTest(unittest.TestCase):
    """FR-057 單檔檢視整合：用真實KBStore（module_d_results/stances 都是
    本機SQLite查詢），mock掉FR-051/052/053三個下層函式與FR-054部位控制
    建議，避免打真實FinMind/TWSE/TPEx API或screener查詢。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-module-d-review-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    @staticmethod
    def _general(growth_flagged=False, downside_flagged=False):
        return {
            "code": "2330",
            "growth_deceleration": {"flagged": growth_flagged,
                                    "detail": "成長趨緩detail"},
            "downside_risk": {"flagged": downside_flagged,
                              "detail": "下檔風險detail",
                              "estimated_downside_pct": None},
            "manual_notes": {"earnings_delivery": None,
                             "good_news_priced_in": None, "estimate_revision": None},
            "checked_at": "2026-07-29T02:00:00",
        }

    @staticmethod
    def _strategy(strategy_id, invalidated, reasons=None):
        return {
            "code": "2330", "strategy_id": strategy_id, "invalidated": invalidated,
            "reasons": reasons or [],
            "current_values": {"peg": 1.15, "drawdown_pct": 0.1, "revenue_yoy": 0.05},
            "checked_at": "2026-07-29T02:00:00",
        }

    @staticmethod
    def _laoyutou(has_signal=False, finding=None):
        return {"code": "2330", "has_signal": has_signal, "recent_trades": [],
                "po_holds": False,
                "finding": finding or "近14天無老芋頭相關動向",
                "checked_at": "2026-07-29T02:00:00"}

    def test_all_normal_no_concern_does_not_write_stance_but_saves_module_d_results(self):
        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value=self._general(False, False)), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies", return_value=[]), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(False)), \
             unittest.mock.patch.object(
                review_engine, "auto_record_findings") as mock_auto, \
             unittest.mock.patch.object(
                review_engine, "position_control_suggestion") as mock_pos:
            out = review_engine.run_module_d_review("2330", self.store)

        self.assertEqual(out["findings"], [])
        mock_auto.assert_not_called()
        mock_pos.assert_not_called()
        self.assertIsNone(out["auto_record"])
        self.assertIsNone(out["position_control"])
        self.assertEqual(out["errors"], {})

        saved = self.store.get_module_d_results(code="2330")
        self.assertEqual(saved["count"], 2)  # 通用層固定2筆，即使都沒觸發
        for row in saved["results"]:
            self.assertEqual(row["trigger_type"], "通用層")
            self.assertIsNone(row["strategy_id"])
            self.assertIsNone(row["suggested_action"])
            self.assertEqual(row["conflict_flag"], 0)

        # 沒有任何concern，stances不該被寫入
        self.assertEqual(self.store.get_stance_history("2330"), [])

    def test_concern_triggers_findings_auto_record_and_position_control(self):
        self.store.save_stance("2330", "觀察", reason="人工初始建倉觀察")
        position_detail = "單股佔比已達18.0%，達參考上限，加碼前應審慎評估。"

        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value=self._general(True, False)), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies",
                return_value=["peg_deep_dip_concentration"]), \
             unittest.mock.patch.object(
                review_engine, "strategy_specific_review",
                return_value=self._strategy(
                    "peg_deep_dip_concentration", True,
                    ["PEG已回升至1.15（門檻1.0）"])), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(False)), \
             unittest.mock.patch.object(
                review_engine, "position_control_suggestion",
                return_value={"code": "2330", "detail": position_detail}) as mock_pos:
            out = review_engine.run_module_d_review("2330", self.store)

        # findings 只含concern_flag=True的2筆（成長趨緩＋策略層），下檔風險
        # concern_flag=False不該混進來
        self.assertEqual(len(out["findings"]), 2)
        self.assertTrue(all(f["concern_flag"] for f in out["findings"]))
        labels = {f["trigger_label"] for f in out["findings"]}
        self.assertEqual(labels,
                         {"通用層／成長趨緩", "策略層／peg_deep_dip_concentration"})

        mock_pos.assert_called_once_with("2330", self.store)
        self.assertIsNotNone(out["auto_record"])
        self.assertFalse(out["auto_record"]["skipped"])
        self.assertEqual(len(out["auto_record"]["written"]), 2)

        # stances：人工1筆 + 系統2筆 = 3筆
        self.assertEqual(len(self.store.get_stance_history("2330")), 3)

        # module_d_results：通用層2筆＋策略層1筆＝3筆；concern筆才附
        # suggested_action，非concern筆（下檔風險）維持None
        saved = self.store.get_module_d_results(code="2330")
        self.assertEqual(saved["count"], 3)
        by_label_prefix = {}
        for row in saved["results"]:
            by_label_prefix.setdefault(row["trigger_type"], []).append(row)
        general_rows = by_label_prefix["通用層"]
        self.assertEqual(len(general_rows), 2)
        concern_general = [r for r in general_rows if r["finding"] == "成長趨緩detail"]
        normal_general = [r for r in general_rows if r["finding"] == "下檔風險detail"]
        self.assertEqual(concern_general[0]["suggested_action"], position_detail)
        self.assertIsNone(normal_general[0]["suggested_action"])
        strategy_rows = by_label_prefix["策略層"]
        self.assertEqual(len(strategy_rows), 1)
        self.assertEqual(strategy_rows[0]["strategy_id"], "peg_deep_dip_concentration")
        self.assertEqual(strategy_rows[0]["suggested_action"], position_detail)

    def test_laoyutou_signal_produces_finding_and_module_d_result_row(self):
        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value=self._general(False, False)), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies", return_value=[]), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(True, "老芋頭於2026-07-28賣出500股（900元）")):
            out = review_engine.run_module_d_review("2330", self.store)

        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(out["findings"][0]["trigger_label"], "老芋頭動向")
        self.assertTrue(out["findings"][0]["concern_flag"])
        saved = self.store.get_module_d_results(code="2330")
        self.assertEqual(saved["count"], 3)  # 通用層2筆 + 老芋頭1筆
        laoyutou_rows = [r for r in saved["results"] if r["trigger_type"] == "老芋頭動向"]
        self.assertEqual(len(laoyutou_rows), 1)

    def test_laoyutou_no_signal_produces_no_finding_and_no_module_d_result_row(self):
        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value=self._general(False, False)), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies", return_value=[]), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(False)):
            out = review_engine.run_module_d_review("2330", self.store)

        self.assertEqual(out["findings"], [])
        saved = self.store.get_module_d_results(code="2330")
        self.assertEqual(saved["count"], 2)  # 只有通用層2筆，老芋頭沒有訊號不產生列

    def test_general_layer_failure_does_not_abort_other_layers(self):
        with unittest.mock.patch.object(
                review_engine, "general_review", side_effect=Exception("finmind boom")), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies",
                return_value=["peg_deep_dip_concentration"]), \
             unittest.mock.patch.object(
                review_engine, "strategy_specific_review",
                return_value=self._strategy(
                    "peg_deep_dip_concentration", False)), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(False)):
            out = review_engine.run_module_d_review("2330", self.store)

        self.assertIsNone(out["general"])
        self.assertIn("general", out["errors"])
        self.assertIn("finmind boom", out["errors"]["general"])
        self.assertEqual(len(out["strategies"]), 1)  # 策略層仍正常跑完

        saved = self.store.get_module_d_results(code="2330")
        self.assertEqual(saved["count"], 1)  # 只有策略層1筆，通用層失敗沒有記錄

    def test_one_strategy_failure_does_not_block_other_strategies(self):
        def _side_effect(code, strategy_id, data_dir=None, token=None):
            if strategy_id == "broken_strategy":
                raise Exception("查詢失敗")
            return self._strategy(strategy_id, False)

        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value=self._general(False, False)), \
             unittest.mock.patch.object(
                review_engine, "get_associated_strategies",
                return_value=["broken_strategy", "peg_deep_dip_concentration"]), \
             unittest.mock.patch.object(
                review_engine, "strategy_specific_review", side_effect=_side_effect), \
             unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value=self._laoyutou(False)):
            out = review_engine.run_module_d_review("2330", self.store)

        self.assertEqual(len(out["strategies"]), 1)
        self.assertEqual(out["strategies"][0]["strategy_id"], "peg_deep_dip_concentration")
        self.assertIn("strategies", out["errors"])
        self.assertIn("broken_strategy", out["errors"]["strategies"])

        saved = self.store.get_module_d_results(code="2330")
        # 通用層2筆 + 正常那個策略1筆 = 3筆，壞掉的策略沒有記錄
        self.assertEqual(saved["count"], 3)


class RunModuleDBatchTest(unittest.TestCase):
    """FR-057 批次執行：觀察名單∪庫存去重，單檔失敗不中斷整批。用真實
    KBStore建立list_stances/get_holdings的資料，mock掉run_module_d_review
    本身（下層邏輯已在RunModuleDReviewTest涵蓋，這裡只驗證批次串接）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-module-d-batch-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _fake_review(self, code, has_concern=False):
        findings = ([{"trigger_label": "通用層／成長趨緩", "concern_flag": True,
                     "detail": "detail"}] if has_concern else [])
        return {"code": code, "checked_at": "2026-07-29T02:00:00", "general": {},
                "strategies": [], "laoyutou": {}, "position_control": None,
                "findings": findings, "auto_record": None,
                "module_d_results_saved_count": 0, "errors": {}}

    def test_codes_are_union_of_stances_and_holdings_deduped(self):
        self.store.save_stance("2330", "觀察")
        self.store.save_stance("6805", "加碼")
        self.store.save_holdings([{"code": "6805", "shares": 1000},
                                  {"code": "2454", "shares": 500}])

        with unittest.mock.patch.object(
                review_engine, "run_module_d_review",
                side_effect=lambda code, store, data_dir=None, token=None:
                    self._fake_review(code)) as mock_review:
            out = review_engine.run_module_d_batch(self.store)

        called_codes = sorted(c.args[0] for c in mock_review.call_args_list)
        self.assertEqual(called_codes, ["2330", "2454", "6805"])  # 去重，6805只查一次
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["checked_count"], 3)
        self.assertEqual(out["failed_count"], 0)

    def test_single_code_failure_does_not_abort_batch(self):
        self.store.save_stance("2330", "觀察")
        self.store.save_stance("6805", "觀察")

        def _side_effect(code, store, data_dir=None, token=None):
            if code == "6805":
                raise Exception("非預期錯誤")
            return self._fake_review(code)

        with unittest.mock.patch.object(
                review_engine, "run_module_d_review", side_effect=_side_effect):
            out = review_engine.run_module_d_batch(self.store)

        self.assertEqual(out["total"], 2)
        self.assertEqual(out["checked_count"], 1)
        self.assertEqual(out["failed_count"], 1)
        self.assertEqual(out["failed"][0]["code"], "6805")
        self.assertIn("非預期錯誤", out["failed"][0]["error"])

    def test_concern_codes_collected_from_findings(self):
        self.store.save_stance("2330", "觀察")
        self.store.save_stance("6805", "觀察")

        def _side_effect(code, store, data_dir=None, token=None):
            return self._fake_review(code, has_concern=(code == "6805"))

        with unittest.mock.patch.object(
                review_engine, "run_module_d_review", side_effect=_side_effect):
            out = review_engine.run_module_d_batch(self.store)

        self.assertEqual(out["concern_codes"], ["6805"])

    def test_empty_watchlist_and_holdings_returns_empty_summary(self):
        out = review_engine.run_module_d_batch(self.store)
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["checked_count"], 0)
        self.assertEqual(out["results"], [])


if __name__ == "__main__":
    unittest.main()
