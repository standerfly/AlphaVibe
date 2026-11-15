"""T003：文章 ID 推建立時間與防呆（spec 驗收（f））。"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_id_time as t  # noqa: E402

NOW = int(datetime.datetime(2026, 11, 15, 23, 0, tzinfo=t.TZ8).timestamp() * 1000)
DAY = 24 * 3600 * 1000
# 探查樣本（2026-11-15）：建立時間 2026-11-08 20:23 +8
SAMPLE = 17941406364761


class IdTimeTest(unittest.TestCase):
    def test_sample_id_gives_creation_time(self):
        ms = t.id_time_ms(SAMPLE, NOW)
        d = datetime.datetime.fromtimestamp(ms / 1000.0, t.TZ8)
        self.assertEqual(d.strftime("%Y-%m-%d %H:%M"), "2026-11-08 20:23")
        self.assertTrue(t.id_time_ok(SAMPLE, NOW))

    def test_string_and_int_inputs_equal(self):
        self.assertEqual(t.id_time_ms("17941406364761", NOW), t.id_time_ms(17941406364761, NOW))

    def test_announcement_13_digit_id_is_not_ok(self):
        self.assertIsNone(t.id_time_ms(1612580077558, NOW))     # 公告：13 位，不推時間
        self.assertFalse(t.id_time_ok(1612580077558, NOW))

    def test_non_numeric_or_malformed_ids(self):
        for bad in ("abc", "", None, "-17941406364761", "1794140636476x", 0, "0", "17941406364.5"):
            self.assertIsNone(t.id_time_ms(bad, NOW), bad)
            self.assertFalse(t.id_time_ok(bad, NOW), bad)

    def test_unreasonable_derived_times_are_not_ok(self):
        too_old = 14 * 10 ** 12 + 5            # 前 13 位 → 約 2001 年，早於 2020-01-01
        self.assertEqual(len(str(too_old)), 14)
        self.assertIsNone(t.id_time_ms(too_old, NOW))
        future = int(str(NOW + 30 * DAY) + "3")
        self.assertIsNone(t.id_time_ms(future, NOW))
        tomorrow_edge = int(str(NOW + DAY - 1000) + "3")        # 現在＋1 天內仍算合理
        self.assertIsNotNone(t.id_time_ms(tomorrow_edge, NOW))
        self.assertIsNone(t.id_time_ms(int(str(NOW + DAY + 1000) + "3"), NOW))

    def test_too_long_or_too_short_ids(self):
        self.assertIsNone(t.id_time_ms(179414063647611, NOW))   # 15 位
        self.assertIsNone(t.id_time_ms(1794140636476, NOW))     # 13 位


class CutoffTest(unittest.TestCase):
    def test_six_months_before_handles_year_wrap_and_month_end(self):
        self.assertEqual(t.six_months_before(datetime.date(2026, 11, 15)), datetime.date(2026, 5, 15))
        self.assertEqual(t.six_months_before(datetime.date(2026, 3, 31)), datetime.date(2025, 9, 30))
        self.assertEqual(t.six_months_before(datetime.date(2026, 8, 31)), datetime.date(2026, 2, 28))
        self.assertEqual(t.six_months_before(datetime.date(2026, 1, 10)), datetime.date(2025, 7, 10))
        self.assertEqual(t.six_months_before(datetime.date(2026, 6, 30)), datetime.date(2025, 12, 30))

    def test_cutoff_for_returns_iso_and_taipei_midnight_ms(self):
        iso, ms = t.cutoff_for(datetime.date(2026, 11, 15))
        self.assertEqual(iso, "2026-05-15")
        self.assertEqual(datetime.datetime.fromtimestamp(ms / 1000.0, t.TZ8).isoformat(),
                         "2026-05-15T00:00:00+08:00")

    def _id_at(self, ms):
        return int(str(ms) + "0")

    def test_is_before_cutoff_uses_14_day_margin(self):
        _, cutoff = t.cutoff_for(datetime.date(2026, 11, 15))
        edge = cutoff - 14 * DAY
        self.assertFalse(t.is_before_cutoff(self._id_at(edge), cutoff, now_ms=NOW))       # 恰好 14 天：不早於
        self.assertTrue(t.is_before_cutoff(self._id_at(edge - 1), cutoff, now_ms=NOW))    # 再早 1 毫秒：早於
        self.assertFalse(t.is_before_cutoff(self._id_at(cutoff), cutoff, now_ms=NOW))
        self.assertFalse(t.is_before_cutoff(self._id_at(NOW - DAY), cutoff, now_ms=NOW))

    def test_id_time_not_ok_is_never_before_cutoff(self):
        _, cutoff = t.cutoff_for(datetime.date(2026, 11, 15))
        for bad in (1612580077558, "abc", None, 14 * 10 ** 12 + 5, 179414063647611):
            self.assertFalse(t.is_before_cutoff(bad, cutoff, now_ms=NOW), bad)

    def test_pinned_recent_article_is_not_before_cutoff_even_with_2021_list_date(self):
        # 置頂文章清單日期顯示 2021，但 ID 時間是近期 → 不得被判為舊文
        _, cutoff = t.cutoff_for(datetime.date(2026, 11, 15))
        self.assertFalse(t.is_before_cutoff(SAMPLE, cutoff, now_ms=NOW))


if __name__ == "__main__":
    unittest.main()
