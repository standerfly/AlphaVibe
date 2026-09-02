"""歷史收盤價百分位測試（FR-007~FR-009）。

三段式降級門檻沿用 review_engine 既有常數語意：
  樣本 >= PERCENTILE_MIN_POINTS(30) → ok（給百分位）
  6 <= 樣本 < 30                    → limited（給百分位，但 basis 明講樣本不足）
  樣本 < MIN_PER_HISTORY_POINTS(6)  → insufficient（percentile 必須是 None）
  完全無資料                        → no_data

最關鍵的是 InsufficientDataTest：資料不足時絕不能回 0，
那會被讀成「現價在歷史最低點」——完全相反的意思。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import price_position  # noqa: E402


def _history(closes, start_day=1):
    """把收盤價 list 組成 get_cached_price_history() 的形狀。"""
    return [{"date": "2026-04-%02d" % (start_day + i), "close": c}
            for i, c in enumerate(closes)]


class PercentileRankTest(unittest.TestCase):
    """percentile_rank 是「給數值求排名」，與 review_engine._percentile
    （給排名求數值）互為反函數，repo 內原本沒有這個方向的實作。"""

    def test_middle_value(self):
        self.assertAlmostEqual(price_position.percentile_rank([1, 2, 3, 4, 5], 3), 50.0)

    def test_lowest_and_highest(self):
        self.assertAlmostEqual(price_position.percentile_rank([10, 20, 30], 10), 16.666666, places=4)
        self.assertAlmostEqual(price_position.percentile_rank([10, 20, 30], 30), 83.333333, places=4)

    def test_above_all_samples(self):
        self.assertAlmostEqual(price_position.percentile_rank([1, 2, 3], 99), 100.0)

    def test_empty_returns_none(self):
        self.assertIsNone(price_position.percentile_rank([], 5))


class SufficientSampleTest(unittest.TestCase):
    """FR-007／FR-008：樣本充足時給百分位，並揭露樣本數與涵蓋期間。"""

    def test_ok_status_with_range_disclosure(self):
        closes = list(range(1, 41))  # 40 筆，1~40
        history = _history(closes)
        prices = {"1111": {"price": 30.0, "price_date": "2026-08-31"}}
        result = price_position.compute("1111", history, prices)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sample_size"], 40)
        self.assertEqual(result["range_start"], history[0]["date"])
        self.assertEqual(result["range_end"], history[-1]["date"])
        self.assertAlmostEqual(result["low"], 1)
        self.assertAlmostEqual(result["high"], 40)
        self.assertIsNotNone(result["percentile"])
        self.assertGreater(result["percentile"], 50)


class DegradationTest(unittest.TestCase):
    """FR-009：三段式降級。"""

    def test_limited_sample_still_gives_value_but_says_so(self):
        history = _history([10, 11, 12, 13, 14, 15, 16, 17])  # 8 筆（6~29）
        prices = {"2222": {"price": 14.0, "price_date": "2026-08-31"}}
        result = price_position.compute("2222", history, prices)

        self.assertEqual(result["status"], "limited")
        self.assertIsNotNone(result["percentile"])
        self.assertEqual(result["sample_size"], 8)
        self.assertIn("樣本", result["basis"])
        self.assertIn("不足", result["basis"])

    def test_no_data_status(self):
        result = price_position.compute("3333", [], {})
        self.assertEqual(result["status"], "no_data")
        self.assertIsNone(result["percentile"])
        self.assertEqual(result["sample_size"], 0)


class InsufficientDataTest(unittest.TestCase):
    """FR-009 的核心風險：資料不足時不得輸出會被誤讀為極端值的預設值。"""

    def test_below_minimum_returns_none_not_zero(self):
        history = _history([10, 11, 12])  # 3 筆，低於 6
        prices = {"4444": {"price": 11.0, "price_date": "2026-08-31"}}
        result = price_position.compute("4444", history, prices)

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["sample_size"], 3)
        # 關鍵：必須是 None，不能是 0／0.0／""
        self.assertIsNone(result["percentile"])
        self.assertNotEqual(result["percentile"], 0)
        self.assertNotEqual(result["percentile"], 0.0)
        self.assertNotEqual(result["percentile"], "")

    def test_no_data_percentile_is_none_not_zero(self):
        result = price_position.compute("5555", [], {})
        self.assertIsNone(result["percentile"])
        self.assertNotEqual(result["percentile"], 0)


class CurrentPriceFallbackTest(unittest.TestCase):
    """現價缺席時退回歷史最後一筆收盤價，並在 basis 說明。"""

    def test_falls_back_to_latest_close(self):
        history = _history(list(range(1, 41)))
        result = price_position.compute("6666", history, {})

        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["current_price"], 40)
        self.assertIn("收盤價", result["basis"])


class DirtyDataTest(unittest.TestCase):
    """髒值過濾：None 與非正數收盤價不納入樣本（比照 _downside_risk
    過濾 FinMind 的 0.0 sentinel 的既有做法）。"""

    def test_filters_none_and_non_positive(self):
        history = _history([10, 11, 12, 13, 14, 15, 16])
        history.append({"date": "2026-05-01", "close": None})
        history.append({"date": "2026-05-02", "close": 0})
        history.append({"date": "2026-05-03", "close": -5})
        prices = {"7777": {"price": 13.0, "price_date": "2026-08-31"}}
        result = price_position.compute("7777", history, prices)

        self.assertEqual(result["sample_size"], 7)
        self.assertAlmostEqual(result["low"], 10)


class BatchTest(unittest.TestCase):
    """FR-011：批次模式，單檔問題不影響其他檔。"""

    def test_batch_mixes_statuses(self):
        history_by_code = {
            "1111": _history(list(range(1, 41))),
            "2222": _history([5, 6]),      # insufficient
            "3333": [],                     # no_data
        }
        prices = {"1111": {"price": 20.0, "price_date": "2026-08-31"},
                  "2222": {"price": 5.5, "price_date": "2026-08-31"}}
        result = price_position.compute_all(history_by_code, prices)

        by_code = {p["code"]: p for p in result["positions"]}
        self.assertEqual(result["count"], 3)
        self.assertEqual(by_code["1111"]["status"], "ok")
        self.assertEqual(by_code["2222"]["status"], "insufficient")
        self.assertEqual(by_code["3333"]["status"], "no_data")


if __name__ == "__main__":
    unittest.main()
