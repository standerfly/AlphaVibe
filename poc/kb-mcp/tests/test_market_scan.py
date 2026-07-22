"""market_scan.py 測試：批次初篩、產業別過濾、代碼合併、單一市場失敗不中斷另一邊。

全部用 mock，不打真實 TWSE/TPEx API。
"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import market_scan  # noqa: E402
from kb_store import KBStore  # noqa: E402

FRAMEWORK = {
    "id": "test_framework",
    "industries": ("半導體業", "電子零組件業"),
    "peg_max": 1.0,
    "revenue_yoy_min": 0.0,
}


def _twse_per(rows):
    return {"data": rows}


def _twse_revenue(rows):
    return {"data": rows}


class RevenuePeriodTest(unittest.TestCase):
    def test_six_digit_roc_yyyymm(self):
        self.assertEqual(market_scan._revenue_period("11506"), "2026-06")

    def test_invalid_format_returns_none(self):
        self.assertIsNone(market_scan._revenue_period("abc"))
        self.assertIsNone(market_scan._revenue_period(""))
        self.assertIsNone(market_scan._revenue_period(None))
        self.assertIsNone(market_scan._revenue_period("115013"))  # 月份=13，不合法


class ToFloatTest(unittest.TestCase):
    def test_empty_string_and_none_return_none(self):
        self.assertIsNone(market_scan._to_float(""))
        self.assertIsNone(market_scan._to_float(None))

    def test_valid_numeric_string(self):
        self.assertEqual(market_scan._to_float("7.6"), 7.6)


class ScanMarketTest(unittest.TestCase):
    def _fake_fetch(self, per_data, revenue_data):
        def fake(url, market_label):
            if url == market_scan.TWSE_PER_URL or url == market_scan.TPEX_PER_URL:
                return {"data": per_data}
            return {"data": revenue_data}
        return fake

    def test_industry_filter_excludes_non_target_rows(self):
        per_rows = [{"Code": "1101", "PEratio": "10"}, {"Code": "2330", "PEratio": "15"}]
        rev_rows = [
            {"公司代號": "1101", "公司名稱": "台泥", "產業別": "水泥工業",
             "營業收入-去年同月增減(%)": "20", "資料年月": "11506"},
            {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
             "營業收入-去年同月增減(%)": "20", "資料年月": "11506"},
        ]
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", self._fake_fetch(per_rows, rev_rows)):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertIsNone(out["error"])
        codes = [c["code"] for c in out["candidates"]]
        self.assertEqual(codes, ["2330"])  # 水泥工業(1101)被排除
        # total_scanned是「營收批次總列數」，不是候選數——2列都要算進去，
        # 即使1101被產業別篩掉沒有變成候選
        self.assertEqual(out["total_scanned"], 2)

    def test_code_merge_between_per_and_revenue_rows(self):
        per_rows = [{"Code": "2330", "PEratio": "8.0"}]
        rev_rows = [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                     "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", self._fake_fetch(per_rows, rev_rows)):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        cand = out["candidates"][0]
        self.assertEqual(cand["per"], 8.0)
        # PEG = 8.0 / (0.20*100) = 0.4
        self.assertAlmostEqual(cand["peg"], 0.4)

    def test_peg_threshold_excludes_when_not_strictly_below(self):
        # PER=20, yoy=20% → PEG=20/(0.20*100)=1.0，門檻peg_max=1.0（嚴格小於），應排除
        per_rows = [{"Code": "2330", "PEratio": "20"}]
        rev_rows = [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                     "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", self._fake_fetch(per_rows, rev_rows)):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertEqual(out["candidates"], [])

    def test_negative_or_missing_yoy_excluded_not_negative_peg(self):
        per_rows = [{"Code": "2330", "PEratio": "10"}]
        rev_rows = [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                     "營業收入-去年同月增減(%)": "-5", "資料年月": "11506"}]
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", self._fake_fetch(per_rows, rev_rows)):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertEqual(out["candidates"], [])  # yoy<=revenue_yoy_min(0.0) 被排除

    def test_per_missing_excludes_candidate(self):
        per_rows = []  # 完全查不到這檔的PER
        rev_rows = [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                     "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]
        with unittest.mock.patch.object(
                market_scan, "_fetch_json", self._fake_fetch(per_rows, rev_rows)):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertEqual(out["candidates"], [])

    def test_per_endpoint_error_short_circuits_this_market_only(self):
        def fake(url, market_label):
            if url == market_scan.TWSE_PER_URL:
                return {"error": "TWSE HTTP 500"}
            return {"data": []}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertEqual(out["error"], "TWSE HTTP 500")
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["total_scanned"], 0)  # 連營收批次都沒抓到，掃描數是0

    def test_unexpected_exception_recorded_not_raised(self):
        def fake(url, market_label):
            raise RuntimeError("模擬非預期例外")
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan._scan_market(
                "TWSE", market_scan.TWSE_PER_URL, market_scan.TWSE_REVENUE_URL,
                "Code", "PEratio", ("半導體業",), 1.0, 0.0)
        self.assertIn("非預期錯誤", out["error"])
        self.assertEqual(out["candidates"], [])


class ScanCandidatesTest(unittest.TestCase):
    def test_twse_failure_does_not_block_tpex_candidates(self):
        """回歸測試：TWSE 掛了，TPEx 仍要正常回傳候選，不能整批槓龜。"""
        def fake(url, market_label):
            if market_label == "TWSE":
                return {"error": "TWSE 呼叫失敗：模擬逾時"}
            if url == market_scan.TPEX_PER_URL:
                return {"data": [{"SecuritiesCompanyCode": "3260", "PriceEarningRatio": "8.0"}]}
            return {"data": [{"公司代號": "3260", "公司名稱": "威剛", "產業別": "半導體業",
                              "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan.scan_candidates(FRAMEWORK)
        self.assertIsNotNone(out["market_errors"]["TWSE"])
        self.assertIsNone(out["market_errors"]["TPEx"])
        self.assertEqual([c["code"] for c in out["candidates"]], ["3260"])
        # TWSE失敗貢獻0，TPEx成功抓到1列營收資料，合計1（不是整批算失敗變0）
        self.assertEqual(out["total_scanned"], 1)

    def test_tpex_failure_does_not_block_twse_candidates(self):
        def fake(url, market_label):
            if market_label == "TPEx":
                return {"error": "TPEx 呼叫失敗：模擬逾時"}
            if url == market_scan.TWSE_PER_URL:
                return {"data": [{"Code": "2330", "PEratio": "8.0"}]}
            return {"data": [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                              "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan.scan_candidates(FRAMEWORK)
        self.assertIsNotNone(out["market_errors"]["TPEx"])
        self.assertIsNone(out["market_errors"]["TWSE"])
        self.assertEqual([c["code"] for c in out["candidates"]], ["2330"])

    def test_candidates_sorted_by_peg_ascending(self):
        def fake(url, market_label):
            if url == market_scan.TWSE_PER_URL:
                return {"data": [{"Code": "AAA", "PEratio": "20"}]}
            if url == market_scan.TWSE_REVENUE_URL:
                return {"data": [{"公司代號": "AAA", "公司名稱": "A", "產業別": "半導體業",
                                  "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
            if url == market_scan.TPEX_PER_URL:
                return {"data": [{"SecuritiesCompanyCode": "BBB", "PriceEarningRatio": "5"}]}
            return {"data": [{"公司代號": "BBB", "公司名稱": "B", "產業別": "半導體業",
                              "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan.scan_candidates(FRAMEWORK)
        # AAA: PEG=20/20=1.0 → 被peg_max=1.0(嚴格小於)排除；BBB: PEG=5/20=0.25 → 保留
        self.assertEqual([c["code"] for c in out["candidates"]], ["BBB"])


class RunScanTest(unittest.TestCase):
    def test_unknown_framework_returns_error(self):
        out = market_scan.run_scan("no_such_framework")
        self.assertEqual(out, {"error": "未知框架：no_such_framework"})

    def test_stitches_stage_a_candidates_with_stage_b_drawdown(self):
        stage_a_result = {
            "candidates": [
                {"code": "2330", "name": "台積電", "market": "TWSE",
                 "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.20,
                 "revenue_period": "2026-06", "peg": 0.5},
            ],
            "codes": ["2330"],
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
        }
        with unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.screener, "compute_drawdown",
                return_value={"drawdown_pct": 0.45, "high_price": 100.0,
                              "high_date": "2026-06-01", "current_price": 55.0,
                              "current_date": "2026-07-20", "error": None}):
            out = market_scan.run_scan("peg_deep_dip_concentration")

        self.assertEqual(out["candidate_count"], 1)
        self.assertEqual(out["meets_count"], 1)  # peg=0.5<1 且 drawdown=0.45>=0.40
        row = out["results"][0]
        self.assertEqual(row["code"], "2330")
        self.assertAlmostEqual(row["drawdown_pct"], 0.45)
        self.assertTrue(row["meets_framework"])
        self.assertEqual(out["market_errors"], {"TWSE": None, "TPEx": None})
        self.assertEqual(out["total_scanned"], 500)  # 從 stage_a 傳遞過來，不是重新計算

    def test_drawdown_failure_recorded_not_fatal_to_other_candidates(self):
        """回歸測試：某檔算回檔幅度失敗，不能讓其他候選也不見。"""
        stage_a_result = {
            "candidates": [
                {"code": "1111", "name": "失敗檔", "market": "TWSE",
                 "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.20,
                 "revenue_period": "2026-06", "peg": 0.5},
                {"code": "2330", "name": "台積電", "market": "TWSE",
                 "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.20,
                 "revenue_period": "2026-06", "peg": 0.5},
            ],
            "codes": ["1111", "2330"],
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
        }

        def fake_drawdown(code, data_dir=None, token=None):
            if code == "1111":
                return {"drawdown_pct": None, "high_price": None, "high_date": None,
                        "current_price": None, "current_date": None,
                        "error": "非預期錯誤：模擬失敗"}
            return {"drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
                    "current_price": 55.0, "current_date": "2026-07-20", "error": None}

        with unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.screener, "compute_drawdown", fake_drawdown):
            out = market_scan.run_scan("peg_deep_dip_concentration")

        self.assertEqual(out["candidate_count"], 2)
        by_code = {r["code"]: r for r in out["results"]}
        self.assertIsNotNone(by_code["1111"]["error"])
        self.assertFalse(by_code["1111"]["meets_framework"])
        self.assertIsNone(by_code["2330"]["error"])
        self.assertTrue(by_code["2330"]["meets_framework"])

    def test_trigger_source_passed_through(self):
        stage_a_result = {"candidates": [], "codes": [],
                          "market_errors": {"TWSE": None, "TPEx": None}, "total_scanned": 0}
        with unittest.mock.patch.object(market_scan, "scan_candidates", return_value=stage_a_result):
            out = market_scan.run_scan("peg_deep_dip_concentration", trigger_source="scheduled")
        self.assertEqual(out["trigger_source"], "scheduled")
        self.assertEqual(out["candidate_count"], 0)
        self.assertEqual(out["meets_count"], 0)


class MainCliTest(unittest.TestCase):
    """CLI 入口（launchd排程呼叫）：mock run_scan，不打真實API。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-marketscan-cli-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_main_persists_result_and_returns_zero(self):
        fake_result = {
            "framework_id": "peg_deep_dip_concentration", "trigger_source": "scheduled",
            "candidate_count": 1, "meets_count": 1,
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
            "results": [{"code": "2330", "name": "台積電", "market": "TWSE",
                        "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.2,
                        "revenue_period": "2026-06", "drawdown_pct": 0.45,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 55.0, "current_date": "2026-07-20",
                        "peg": 0.5, "meets_framework": True, "error": None}],
        }
        with unittest.mock.patch.object(market_scan, "run_scan", return_value=fake_result) as mock_scan:
            code = market_scan.main(["--data-dir", self.tmp, "--trigger", "scheduled"])
            mock_scan.assert_called_once_with(
                "peg_deep_dip_concentration", data_dir=self.tmp, trigger_source="scheduled")
        self.assertEqual(code, 0)

        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan()
        store.close()
        self.assertTrue(latest["found"])
        self.assertEqual(latest["results"][0]["code"], "2330")

    def test_main_custom_framework_arg_passed_through(self):
        with unittest.mock.patch.object(
                market_scan, "run_scan",
                return_value={"error": "未知框架：custom_id"}) as mock_scan:
            code = market_scan.main(["--data-dir", self.tmp, "--framework", "custom_id"])
            mock_scan.assert_called_once_with(
                "custom_id", data_dir=self.tmp, trigger_source="scheduled")
        self.assertEqual(code, 1)  # error時回傳非0，launchd log會看得出失敗

    def test_main_error_does_not_persist(self):
        with unittest.mock.patch.object(
                market_scan, "run_scan", return_value={"error": "模擬失敗"}):
            market_scan.main(["--data-dir", self.tmp])
        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan()
        store.close()
        self.assertFalse(latest["found"])


if __name__ == "__main__":
    unittest.main()
