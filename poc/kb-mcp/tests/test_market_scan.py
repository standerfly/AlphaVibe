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
        def fake(url, market_label, cache=None):
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
        def fake(url, market_label, cache=None):
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
        def fake(url, market_label, cache=None):
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
        def fake(url, market_label, cache=None):
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
        def fake(url, market_label, cache=None):
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
        def fake(url, market_label, cache=None):
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

    def test_pbr_and_dividend_yield_extracted_per_market_field_names(self):
        """TWSE／TPEx 兩市場欄位名不同（見模組層 TWSE_PER_EXTRA_FIELDS／
        TPEX_PER_EXTRA_FIELDS，2026-07-28 實跑確認），scan_candidates 要各自
        用對應欄位名抓到 pbr／dividend_yield，不能兩市場共用同一組欄位名。"""
        def fake(url, market_label, cache=None):
            if url == market_scan.TWSE_PER_URL:
                return {"data": [{"Code": "2330", "PEratio": "8.0",
                                  "PBratio": "1.5", "DividendYield": "3.28"}]}
            if url == market_scan.TWSE_REVENUE_URL:
                return {"data": [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                                  "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
            if url == market_scan.TPEX_PER_URL:
                return {"data": [{"SecuritiesCompanyCode": "3260", "PriceEarningRatio": "5.0",
                                  "PriceBookRatio": "0.8", "YieldRatio": "6.42"}]}
            return {"data": [{"公司代號": "3260", "公司名稱": "威剛", "產業別": "半導體業",
                              "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan.scan_candidates(FRAMEWORK)
        by_code = {c["code"]: c for c in out["candidates"]}
        self.assertAlmostEqual(by_code["2330"]["pbr"], 1.5)
        self.assertAlmostEqual(by_code["2330"]["dividend_yield"], 3.28)
        self.assertAlmostEqual(by_code["3260"]["pbr"], 0.8)
        self.assertAlmostEqual(by_code["3260"]["dividend_yield"], 6.42)

    def test_pbr_and_dividend_yield_missing_field_does_not_raise(self):
        """欄位缺失或空字串一律回None，不丟例外——比照既有per的防呆規則。"""
        def fake(url, market_label, cache=None):
            if url == market_scan.TWSE_PER_URL:
                return {"data": [{"Code": "2330", "PEratio": "8.0"}]}  # 沒有PBratio/DividendYield
            return {"data": [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                              "營業收入-去年同月增減(%)": "20", "資料年月": "11506"}]}
        with unittest.mock.patch.object(market_scan, "_fetch_json", fake):
            out = market_scan.scan_candidates(FRAMEWORK)
        self.assertIsNone(out["candidates"][0]["pbr"])
        self.assertIsNone(out["candidates"][0]["dividend_yield"])


def _fake_bench(window_drawdown_pct=0.0951, error=None):
    return {"closes": None, "dates": None, "high_date": "2026-06-23",
            "high_price": 48218.87, "current_date": "2026-07-27",
            "current_close": 43634.19, "window_drawdown_pct": window_drawdown_pct,
            "error": error}


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
                market_scan.benchmark, "load_benchmark", return_value=_fake_bench()), \
             unittest.mock.patch.object(
                market_scan.screener, "compute_drawdown",
                return_value={"drawdown_pct": 0.45, "high_price": 100.0,
                              "high_date": "2026-06-01", "current_price": 55.0,
                              "current_date": "2026-07-20",
                              "market_drawdown_pct": 0.10, "excess_drawdown_pct": 0.35,
                              "error": None}):
            out = market_scan.run_scan("peg_deep_dip_concentration")

        self.assertEqual(out["candidate_count"], 1)
        self.assertEqual(out["meets_count"], 1)  # peg=0.5<1 且 drawdown=0.45>=0.40
        row = out["results"][0]
        self.assertEqual(row["code"], "2330")
        self.assertAlmostEqual(row["drawdown_pct"], 0.45)
        self.assertAlmostEqual(row["excess_drawdown_pct"], 0.35)
        self.assertTrue(row["meets_framework"])
        self.assertEqual(out["market_errors"], {"TWSE": None, "TPEx": None})
        self.assertEqual(out["total_scanned"], 500)  # 從 stage_a 傳遞過來，不是重新計算
        self.assertAlmostEqual(out["benchmark_drawdown_pct"], 0.0951)
        self.assertIsNone(out["benchmark_error"])

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

        def fake_drawdown(code, data_dir=None, token=None, benchmark_series=None,
                          market=None, price_cache=None):
            if code == "1111":
                return {"drawdown_pct": None, "high_price": None, "high_date": None,
                        "current_price": None, "current_date": None,
                        "market_drawdown_pct": None, "excess_drawdown_pct": None,
                        "data_source": None, "error": "非預期錯誤：模擬失敗"}
            return {"drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
                    "current_price": 55.0, "current_date": "2026-07-20",
                    "market_drawdown_pct": 0.10, "excess_drawdown_pct": 0.35,
                    "data_source": "twse_official", "error": None}

        with unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.benchmark, "load_benchmark", return_value=_fake_bench()), \
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
        with unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.benchmark, "load_benchmark", return_value=_fake_bench()):
            out = market_scan.run_scan("peg_deep_dip_concentration", trigger_source="scheduled")
        self.assertEqual(out["trigger_source"], "scheduled")
        self.assertEqual(out["candidate_count"], 0)
        self.assertEqual(out["meets_count"], 0)

    def test_excess_drawdown_min_framework_filters_meets(self):
        """第二框架 revenue_high_price_dip 用 excess_drawdown_min（本身是
        None，靠 sort_by 排序，這裡直接構造一個帶 excess_drawdown_min 的假框架
        驗證 meets_framework 判斷有吃到超額跌幅參數，不只是peg/drawdown。"""
        stage_a_result = {
            "candidates": [
                {"code": "2330", "name": "台積電", "market": "TWSE",
                 "industry": "半導體業", "per": None, "revenue_yoy": 0.35,
                 "revenue_period": "2026-06", "peg": None},
            ],
            "codes": ["2330"],
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
        }
        fake_framework = dict(FRAMEWORK, id="excess_test", peg_max=None,
                              drawdown_min=0.15, drawdown_max=0.40,
                              excess_drawdown_min=0.20)
        with unittest.mock.patch.object(
                market_scan.frameworks, "get_framework", return_value=fake_framework), \
             unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.benchmark, "load_benchmark", return_value=_fake_bench()), \
             unittest.mock.patch.object(
                market_scan.screener, "compute_drawdown",
                return_value={"drawdown_pct": 0.20, "high_price": 100.0,
                              "high_date": "2026-06-01", "current_price": 80.0,
                              "current_date": "2026-07-20",
                              "market_drawdown_pct": -0.05, "excess_drawdown_pct": 0.25,
                              "error": None}):
            out = market_scan.run_scan("excess_test")
        self.assertTrue(out["results"][0]["meets_framework"])  # 0.25 >= 0.20


class RunScansTest(unittest.TestCase):
    """run_scans()：多框架依序跑、共用 shared 快取——大盤基準只抓一次、
    出現在多個框架候選清單裡的同一檔代碼只查一次回檔幅度。"""

    def test_shared_cache_avoids_duplicate_lookups_across_frameworks(self):
        fw_a = dict(FRAMEWORK, id="fw_a")
        fw_b = dict(FRAMEWORK, id="fw_b")

        def fake_get_framework(fid):
            return {"fw_a": fw_a, "fw_b": fw_b}.get(fid)

        stage_a_common = {
            "candidates": [
                {"code": "2330", "name": "台積電", "market": "TWSE",
                 "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.20,
                 "revenue_period": "2026-06", "peg": 0.5},
            ],
            "codes": ["2330"],
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
        }

        drawdown_calls = []

        def fake_drawdown(code, data_dir=None, token=None, benchmark_series=None,
                          market=None, price_cache=None):
            drawdown_calls.append(code)
            return {"drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
                    "current_price": 55.0, "current_date": "2026-07-20",
                    "market_drawdown_pct": 0.10, "excess_drawdown_pct": 0.35,
                    "data_source": "twse_official", "error": None}

        bench_calls = []

        def fake_load_benchmark(**kwargs):
            bench_calls.append(kwargs)
            return _fake_bench()

        with unittest.mock.patch.object(
                market_scan.frameworks, "get_framework", fake_get_framework), \
             unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_common), \
             unittest.mock.patch.object(
                market_scan.screener, "compute_drawdown", fake_drawdown), \
             unittest.mock.patch.object(
                market_scan.benchmark, "load_benchmark", fake_load_benchmark):
            results = market_scan.run_scans(["fw_a", "fw_b"])

        self.assertEqual(len(results), 2)
        self.assertEqual([r["framework_id"] for r in results], ["fw_a", "fw_b"])
        # 兩個框架的候選都是2330，第二個框架重用快取，不再查一次FinMind
        self.assertEqual(drawdown_calls, ["2330"])
        # 大盤基準也只抓一次
        self.assertEqual(len(bench_calls), 1)

    def test_unknown_framework_does_not_block_other_frameworks(self):
        stage_a_result = {"candidates": [], "codes": [],
                          "market_errors": {"TWSE": None, "TPEx": None}, "total_scanned": 0}
        with unittest.mock.patch.object(
                market_scan, "scan_candidates", return_value=stage_a_result), \
             unittest.mock.patch.object(
                market_scan.benchmark, "load_benchmark", return_value=_fake_bench()):
            results = market_scan.run_scans(["no_such_framework", "peg_deep_dip_concentration"])
        self.assertEqual(results[0], {"error": "未知框架：no_such_framework"})
        self.assertNotIn("error", results[1])


class MainCliTest(unittest.TestCase):
    """CLI 入口（launchd排程呼叫）：mock run_scans，不打真實API。

    行為變更（2026-07-28）：main() 改成呼叫 run_scans()（複數）而不是
    run_scan()（單數）——不給 --framework 時要跑 frameworks.FRAMEWORKS
    全部框架，不再只跑預設框架一個。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-marketscan-cli-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _fake_result(self, framework_id, code="2330"):
        return {
            "framework_id": framework_id, "trigger_source": "scheduled",
            "candidate_count": 1, "meets_count": 1,
            "market_errors": {"TWSE": None, "TPEx": None},
            "total_scanned": 500,
            "benchmark_drawdown_pct": 0.0951, "benchmark_error": None,
            "results": [{"code": code, "name": "台積電", "market": "TWSE",
                        "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.2,
                        "revenue_period": "2026-06", "drawdown_pct": 0.45,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 55.0, "current_date": "2026-07-20",
                        "market_drawdown_pct": 0.10, "excess_drawdown_pct": 0.35,
                        "peg": 0.5, "meets_framework": True, "error": None,
                        "pbr": 1.5, "dividend_yield": 3.28}],
        }

    def test_main_persists_result_and_returns_zero(self):
        fake_result = self._fake_result("peg_deep_dip_concentration")
        with unittest.mock.patch.object(
                market_scan, "run_scans", return_value=[fake_result]) as mock_scans:
            code = market_scan.main(
                ["--data-dir", self.tmp, "--trigger", "scheduled",
                 "--framework", "peg_deep_dip_concentration"])
            mock_scans.assert_called_once_with(
                ["peg_deep_dip_concentration"], data_dir=self.tmp,
                trigger_source="scheduled")
        self.assertEqual(code, 0)

        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan()
        store.close()
        self.assertTrue(latest["found"])
        self.assertEqual(latest["results"][0]["code"], "2330")
        self.assertAlmostEqual(latest["run"]["benchmark_drawdown_pct"], 0.0951)

    def test_main_without_framework_arg_runs_all_frameworks(self):
        """行為變更：不給 --framework 時要跑全部框架，不再只跑預設框架一個。"""
        all_ids = [fw["id"] for fw in market_scan.frameworks.FRAMEWORKS]
        self.assertEqual(len(all_ids), 2)  # 這波新增了第二個框架，確保測試沒有跟預期脫節
        fake_results = [self._fake_result(fid, code="code-%s" % fid) for fid in all_ids]
        with unittest.mock.patch.object(
                market_scan, "run_scans", return_value=fake_results) as mock_scans:
            code = market_scan.main(["--data-dir", self.tmp])
            mock_scans.assert_called_once_with(
                all_ids, data_dir=self.tmp, trigger_source="scheduled")
        self.assertEqual(code, 0)

        store = KBStore(self.tmp)
        runs = store.conn.execute("SELECT framework_id FROM market_scan_runs").fetchall()
        store.close()
        self.assertEqual(sorted(r["framework_id"] for r in runs), sorted(all_ids))

    def test_main_custom_framework_arg_passed_through(self):
        with unittest.mock.patch.object(
                market_scan, "run_scans",
                return_value=[{"error": "未知框架：custom_id"}]) as mock_scans:
            code = market_scan.main(["--data-dir", self.tmp, "--framework", "custom_id"])
            mock_scans.assert_called_once_with(
                ["custom_id"], data_dir=self.tmp, trigger_source="scheduled")
        self.assertEqual(code, 1)  # error時回傳非0，launchd log會看得出失敗

    def test_main_multiple_framework_args_accumulate(self):
        """--framework 可重複給，指定跑其中幾個（action="append"）。"""
        with unittest.mock.patch.object(
                market_scan, "run_scans",
                return_value=[self._fake_result("a"), self._fake_result("b")]) as mock_scans:
            market_scan.main(
                ["--data-dir", self.tmp, "--framework", "a", "--framework", "b"])
            mock_scans.assert_called_once_with(
                ["a", "b"], data_dir=self.tmp, trigger_source="scheduled")

    def test_main_partial_failure_still_saves_other_frameworks_and_returns_one(self):
        """任一框架失敗要回傳碼1，但其餘框架仍要跑完存檔——不能因為一個
        框架壞掉就讓能跑的框架也不存檔。"""
        ok_result = self._fake_result("peg_deep_dip_concentration")
        with unittest.mock.patch.object(
                market_scan, "run_scans",
                return_value=[{"error": "未知框架：broken"}, ok_result]):
            code = market_scan.main(
                ["--data-dir", self.tmp, "--framework", "broken",
                 "--framework", "peg_deep_dip_concentration"])
        self.assertEqual(code, 1)

        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan("peg_deep_dip_concentration")
        total_runs = store.conn.execute(
            "SELECT COUNT(*) c FROM market_scan_runs").fetchone()["c"]
        store.close()
        self.assertTrue(latest["found"])  # 沒失敗的框架仍要存到
        self.assertEqual(total_runs, 1)  # 失敗的那個框架沒有存

    def test_main_error_does_not_persist(self):
        with unittest.mock.patch.object(
                market_scan, "run_scans", return_value=[{"error": "模擬失敗"}]):
            code = market_scan.main(["--data-dir", self.tmp, "--framework", "x"])
        self.assertEqual(code, 1)
        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan()
        store.close()
        self.assertFalse(latest["found"])


if __name__ == "__main__":
    unittest.main()
