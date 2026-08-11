"""research_brief.py 測試：SRC-013 Stage 1「研究啟動包」
（`prepare_research_brief`）與 Stage 2（對照組交叉驗證）。

全部 mock `finmind_client`／`fundamentals_client` 底層查詢函式，不打真實
外部API，比照 `test_review_engine.py` 既有慣例。重點驗證：
1. 財務體檢五個「有資料源」小節（revenue_quality/valuation/
   institutional_flow/price_history_recent/balance_sheet）查詢成功時有
   實際數字、失敗時status為query_failed。
2. 三個「無資料源」小節（gross_margin_operating_leverage/cash_flow/
   earnings_call_qa）status固定no_data_source。
3. 頂層六個「需要對話判斷」小節status固定needs_discussion——這是SRC-013
   核心設計原則，no_data_source跟needs_discussion必須用不同status值
   區分，不能混在一起。
4. 全程不呼叫任何LLM/AI，純粹組裝mock回傳值。
5.（Stage 2）`peers`未指定時只用一次`get_stock_info`全量查詢帶出同產業
   候選名單`peer_candidates`，不對候選逐檔查財務API（額度保護，2026-07-28
   FinMind額度打光教訓）；`peers`有指定時對每個peer重跑財務體檢五項並排
   放入`peer_comparison`，且不再呼叫`get_stock_info`（兩欄位互斥）。
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import fundamentals_client  # noqa: E402
import research_brief  # noqa: E402

NO_DATA_SOURCE_FIELDS = ("gross_margin_operating_leverage", "cash_flow", "earnings_call_qa")
NEEDS_DISCUSSION_SECTIONS = ("business_understanding", "industry_structure",
                             "expectation_gap", "thesis_break_conditions",
                             "valuation_narrative", "converging_questions")
DATA_BEARING_FIELDS = ("revenue_quality", "valuation", "institutional_flow",
                       "price_history_recent", "balance_sheet")


def _ok_revenue_yoy():
    return {"stock_id": "2330", "errors": [],
            "revenue_yoy": [
                {"revenue_year": 2026, "revenue_month": i, "revenue": 1000 + i,
                 "yoy_growth": 0.1 + i * 0.01}
                for i in range(1, 8)
            ]}


def _ok_revenue_latest():
    return {"revenue_yoy": 0.15, "revenue_period": "2026-06",
            "market": "TWSE", "data_source": "twse_official", "error": None}


def _ok_valuation():
    return {"per": 20.5, "pbr": 6.2, "dividend_yield": 2.1,
            "market": "TWSE", "data_source": "twse_official", "error": None}


def _ok_institutional():
    return {"stock_id": "2330", "errors": [],
            "trading": [
                {"date": "2026-08-01", "stock_id": "2330", "name": "Foreign_Investor",
                 "buy": 100, "sell": 50},
                {"date": "2026-08-04", "stock_id": "2330", "name": "Foreign_Investor",
                 "buy": 80, "sell": 90},
            ],
            "foreign_net": 40}


def _ok_price_history():
    return {"stock_id": "2330", "errors": [],
            "prices": [
                {"date": "2026-08-01", "close": 1000.0, "max": 1010.0, "min": 990.0},
                {"date": "2026-08-04", "close": 1050.0, "max": 1060.0, "min": 1000.0},
            ]}


def _ok_balance_sheet():
    return {"stock_id": "2330", "errors": [], "balance_sheet_date": "2026-03-31",
            "cash_and_equivalents": 3000000000.0, "current_liabilities": 1700000000.0,
            "total_liabilities": 2700000000.0, "total_assets": 8600000000.0,
            "debt_ratio": 2700000000.0 / 8600000000.0}


def _ok_stock_info():
    """`get_stock_info()` 不帶stock_id的全量查詢結果——2330跟2303/2454同屬
    「半導體業」（供peer_candidates測試同產業篩選），2412屬不同產業（供驗證
    排除邏輯），"0000"不在名單裡（供查無產業分類情境）。"""
    return {"stock_id": None, "errors": [],
            "stocks": [
                {"stock_id": "2330", "stock_name": "台積電", "industry_category": "半導體業",
                 "type": "twse", "date": "2026-01-01"},
                {"stock_id": "2303", "stock_name": "聯電", "industry_category": "半導體業",
                 "type": "twse", "date": "2026-01-01"},
                {"stock_id": "2454", "stock_name": "聯發科", "industry_category": "半導體業",
                 "type": "twse", "date": "2026-01-01"},
                {"stock_id": "2412", "stock_name": "中華電", "industry_category": "通信網路業",
                 "type": "twse", "date": "2026-01-01"},
            ]}


def _patch_all_success():
    return [
        unittest.mock.patch.object(finmind_client, "get_revenue_yoy",
                                   return_value=_ok_revenue_yoy()),
        unittest.mock.patch.object(fundamentals_client, "get_revenue_yoy_latest",
                                   return_value=_ok_revenue_latest()),
        unittest.mock.patch.object(fundamentals_client, "get_valuation",
                                   return_value=_ok_valuation()),
        unittest.mock.patch.object(finmind_client, "get_institutional_trading",
                                   return_value=_ok_institutional()),
        unittest.mock.patch.object(finmind_client, "get_stock_price_history",
                                   return_value=_ok_price_history()),
        unittest.mock.patch.object(finmind_client, "get_balance_sheet_summary",
                                   return_value=_ok_balance_sheet()),
        unittest.mock.patch.object(finmind_client, "get_stock_info",
                                   return_value=_ok_stock_info()),
    ]


class PrepareResearchBriefStructureTest(unittest.TestCase):
    """全部底層查詢成功時，驗證整體dict結構與七節骨架完整。"""

    def setUp(self):
        self.patchers = _patch_all_success()
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def test_top_level_keys(self):
        out = research_brief.prepare_research_brief("2330")
        # Stage 2：peers未指定（預設）時，多一個peer_candidates欄位。
        expected_top = ({"code", "generated_at", "financial_check", "peer_candidates"}
                        | set(NEEDS_DISCUSSION_SECTIONS))
        self.assertEqual(set(out.keys()), expected_top)
        self.assertEqual(out["code"], "2330")
        self.assertTrue(out["generated_at"])

    def test_financial_check_sub_keys(self):
        out = research_brief.prepare_research_brief("2330")
        expected_sub = set(DATA_BEARING_FIELDS) | set(NO_DATA_SOURCE_FIELDS)
        self.assertEqual(set(out["financial_check"].keys()), expected_sub)

    def test_no_data_source_status_fixed(self):
        out = research_brief.prepare_research_brief("2330")
        for field in NO_DATA_SOURCE_FIELDS:
            self.assertEqual(out["financial_check"][field]["status"], "no_data_source")
            self.assertTrue(out["financial_check"][field]["note"])

    def test_needs_discussion_status_fixed(self):
        out = research_brief.prepare_research_brief("2330")
        for section in NEEDS_DISCUSSION_SECTIONS:
            self.assertEqual(out[section]["status"], "needs_discussion")
            self.assertTrue(out[section]["note"])

    def test_no_data_source_and_needs_discussion_are_distinct_status_values(self):
        """SRC-013核心設計原則：兩種留白狀態不能混用同一個status值。"""
        out = research_brief.prepare_research_brief("2330")
        no_data_statuses = {out["financial_check"][f]["status"] for f in NO_DATA_SOURCE_FIELDS}
        needs_discussion_statuses = {out[s]["status"] for s in NEEDS_DISCUSSION_SECTIONS}
        self.assertEqual(no_data_statuses, {"no_data_source"})
        self.assertEqual(needs_discussion_statuses, {"needs_discussion"})
        self.assertTrue(no_data_statuses.isdisjoint(needs_discussion_statuses))

    def test_revenue_quality_has_real_numbers(self):
        out = research_brief.prepare_research_brief("2330")
        section = out["financial_check"]["revenue_quality"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(section["latest_yoy"], 0.15)
        self.assertEqual(section["latest_period"], "2026-06")
        self.assertEqual(len(section["recent_trend"]), 6)  # 近6個月

    def test_valuation_has_real_numbers(self):
        out = research_brief.prepare_research_brief("2330")
        section = out["financial_check"]["valuation"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(section["per"], 20.5)
        self.assertEqual(section["pbr"], 6.2)
        self.assertEqual(section["data_source"], "twse_official")

    def test_institutional_flow_has_real_numbers(self):
        out = research_brief.prepare_research_brief("2330")
        section = out["financial_check"]["institutional_flow"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(section["foreign_net"], 40)
        self.assertEqual(section["trading_days"], 2)
        self.assertEqual(section["latest_date"], "2026-08-04")

    def test_price_history_recent_has_real_numbers(self):
        out = research_brief.prepare_research_brief("2330")
        section = out["financial_check"]["price_history_recent"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(section["latest_close"], 1050.0)
        self.assertEqual(section["period_high"], 1060.0)
        self.assertEqual(section["period_low"], 990.0)
        self.assertEqual(section["data_points"], 2)

    def test_balance_sheet_has_real_numbers(self):
        out = research_brief.prepare_research_brief("2330")
        section = out["financial_check"]["balance_sheet"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(section["cash_and_equivalents"], 3000000000.0)
        self.assertEqual(section["balance_sheet_date"], "2026-03-31")
        self.assertAlmostEqual(section["debt_ratio"], 2700000000.0 / 8600000000.0)

    def test_no_llm_or_ai_call_involved(self):
        """反面驗證：組裝過程只用到mock的5個底層函式，沒有任何額外的網路/
        LLM相關呼叫——mock齊全的情況下函式仍能跑完不出例外，且回傳值
        completely derived from the mocked returns（不會無中生有多餘欄位
        內容），是最直接能驗證「機械組裝」性質的方式。"""
        out = research_brief.prepare_research_brief("2330")
        # revenue_quality的note在latest_yoy有值時應為None（不會被塞入任何
        # 額外生成文字）
        self.assertIsNone(out["financial_check"]["revenue_quality"]["note"])
        self.assertIsNone(out["financial_check"]["valuation"]["note"])


class PrepareResearchBriefFailureTest(unittest.TestCase):
    """底層查詢失敗時，對應小節status要標記query_failed並保留原因，
    不臆測、不中斷整個啟動包組裝。"""

    def test_revenue_query_failed(self):
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "0000",
                             "errors": ["FinMind 呼叫失敗（TaiwanStockMonthRevenue）：模擬斷網"]}), \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": None, "revenue_period": None, "market": None,
                             "data_source": None, "error": "模擬官方與FinMind皆失敗"}), \
             unittest.mock.patch.object(fundamentals_client, "get_valuation",
                                        return_value=_ok_valuation()), \
             unittest.mock.patch.object(finmind_client, "get_institutional_trading",
                                        return_value=_ok_institutional()), \
             unittest.mock.patch.object(finmind_client, "get_stock_price_history",
                                        return_value=_ok_price_history()), \
             unittest.mock.patch.object(finmind_client, "get_balance_sheet_summary",
                                        return_value=_ok_balance_sheet()), \
             unittest.mock.patch.object(finmind_client, "get_stock_info",
                                        return_value=_ok_stock_info()):
            out = research_brief.prepare_research_brief("0000")

        section = out["financial_check"]["revenue_quality"]
        self.assertEqual(section["status"], "query_failed")
        self.assertIn("模擬斷網", section["note"])
        # 其他小節不受影響，仍正常組裝
        self.assertEqual(out["financial_check"]["valuation"]["status"], "ok")

    def test_all_data_bearing_sections_query_failed(self):
        fail_result_no_key = {"stock_id": "0000", "errors": ["模擬全部查詢失敗"]}
        fail_result_with_error = {"per": None, "pbr": None, "dividend_yield": None,
                                  "market": None, "data_source": None,
                                  "error": "模擬全部查詢失敗"}
        with unittest.mock.patch.object(finmind_client, "get_revenue_yoy",
                                        return_value=fail_result_no_key), \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": None, "revenue_period": None, "market": None,
                             "data_source": None, "error": "模擬全部查詢失敗"}), \
             unittest.mock.patch.object(fundamentals_client, "get_valuation",
                                        return_value=fail_result_with_error), \
             unittest.mock.patch.object(finmind_client, "get_institutional_trading",
                                        return_value=fail_result_no_key), \
             unittest.mock.patch.object(finmind_client, "get_stock_price_history",
                                        return_value=fail_result_no_key), \
             unittest.mock.patch.object(
                finmind_client, "get_balance_sheet_summary",
                return_value={"stock_id": "0000", "errors": ["模擬全部查詢失敗"],
                             "balance_sheet_date": None, "cash_and_equivalents": None,
                             "current_liabilities": None, "total_liabilities": None,
                             "total_assets": None, "debt_ratio": None}), \
             unittest.mock.patch.object(finmind_client, "get_stock_info",
                                        return_value=_ok_stock_info()):
            out = research_brief.prepare_research_brief("0000")

        for field in DATA_BEARING_FIELDS:
            section = out["financial_check"][field]
            self.assertEqual(section["status"], "query_failed", field)
            self.assertTrue(section["note"], field)
        # 沒有查詢資料源的欄位跟頂層判斷欄位，不受查詢失敗影響，仍是固定佔位
        for field in NO_DATA_SOURCE_FIELDS:
            self.assertEqual(out["financial_check"][field]["status"], "no_data_source")
        for section_name in NEEDS_DISCUSSION_SECTIONS:
            self.assertEqual(out[section_name]["status"], "needs_discussion")
        # "0000" 不在stock_info候選名單裡，peer_candidates查無產業分類，
        # 不視為錯誤中斷整個啟動包組裝。
        self.assertEqual(out["peer_candidates"], {"industry": None, "candidates": []})

    def test_underlying_unexpected_exception_propagates_no_extra_wrapping(self):
        """finmind_client／fundamentals_client本身已保證正常情況下不丟例外
        （見兩者docstring，查詢失敗一律回傳errors/error鍵）。research_brief
        比照review_engine.general_review()既有慣例，不額外包一層
        try/except——這裡用side_effect模擬「萬一底層真的意外丟出例外」
        這種不該發生的情況，驗證目前設計下例外會直接往上傳，不是被吞掉，
        這是刻意的取捨（見回報「取捨」欄）。"""
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                side_effect=RuntimeError("模擬不該發生的意外例外")):
            with self.assertRaises(RuntimeError):
                research_brief.prepare_research_brief("2330")


class PrepareResearchBriefPeerCandidatesTest(unittest.TestCase):
    """SRC-013 Stage 2：`peers`未指定（預設）時的`peer_candidates`分支。"""

    def setUp(self):
        self.patchers = _patch_all_success()
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def test_peer_candidates_present_not_peer_comparison(self):
        out = research_brief.prepare_research_brief("2330")
        self.assertIn("peer_candidates", out)
        self.assertNotIn("peer_comparison", out)

    def test_peer_candidates_industry_and_candidates(self):
        out = research_brief.prepare_research_brief("2330")
        pc = out["peer_candidates"]
        self.assertEqual(pc["industry"], "半導體業")
        # 同產業扣除自己：2303聯電／2454聯發科，順序沿用stock_info原始順序
        self.assertEqual(pc["candidates"], [
            {"code": "2303", "name": "聯電"},
            {"code": "2454", "name": "聯發科"},
        ])

    def test_peer_candidates_excludes_self(self):
        out = research_brief.prepare_research_brief("2330")
        codes = [c["code"] for c in out["peer_candidates"]["candidates"]]
        self.assertNotIn("2330", codes)

    def test_peer_candidates_empty_when_industry_not_found(self):
        # "0000" 不在_ok_stock_info()的名單裡，查無產業分類。
        out = research_brief.prepare_research_brief("0000")
        self.assertEqual(out["peer_candidates"], {"industry": None, "candidates": []})

    def test_peer_candidates_empty_when_alone_in_industry(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info",
                return_value={"stock_id": None, "errors": [],
                             "stocks": [{"stock_id": "2330", "stock_name": "台積電",
                                        "industry_category": "半導體業",
                                        "type": "twse", "date": "2026-01-01"}]}):
            out = research_brief.prepare_research_brief("2330")
        self.assertEqual(out["peer_candidates"], {"industry": "半導體業", "candidates": []})

    def test_peer_candidates_calls_get_stock_info_exactly_once(self):
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info",
                return_value=_ok_stock_info()) as mock_info:
            research_brief.prepare_research_brief("2330")
        self.assertEqual(mock_info.call_count, 1)

    def test_peer_candidates_does_not_call_financial_apis_for_candidates(self):
        """額度保護（2026-07-28教訓）：peer_candidates分支只查一次
        get_stock_info全量，不對候選清單裡任何一檔額外呼叫財務相關API——
        用call_count驗證財務體檢五個底層函式各只被呼叫一次（只為主標的
        2330查詢，2303/2454候選完全沒被查）。"""
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_ok_revenue_yoy()) as m_rev, \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value=_ok_revenue_latest()) as m_rev_latest, \
             unittest.mock.patch.object(
                fundamentals_client, "get_valuation", return_value=_ok_valuation()) as m_val, \
             unittest.mock.patch.object(
                finmind_client, "get_institutional_trading",
                return_value=_ok_institutional()) as m_inst, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_ok_price_history()) as m_price, \
             unittest.mock.patch.object(
                finmind_client, "get_balance_sheet_summary",
                return_value=_ok_balance_sheet()) as m_bs, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value=_ok_stock_info()):
            research_brief.prepare_research_brief("2330")

        for mock_fn in (m_rev, m_rev_latest, m_val, m_inst, m_price, m_bs):
            self.assertEqual(mock_fn.call_count, 1)


class PrepareResearchBriefPeerComparisonTest(unittest.TestCase):
    """SRC-013 Stage 2：`peers`有指定時的`peer_comparison`分支。"""

    def setUp(self):
        self.patchers = _patch_all_success()
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def test_peer_comparison_present_not_peer_candidates(self):
        out = research_brief.prepare_research_brief("2330", peers=["2303"])
        self.assertIn("peer_comparison", out)
        self.assertNotIn("peer_candidates", out)

    def test_peer_comparison_has_five_data_bearing_fields_per_peer(self):
        out = research_brief.prepare_research_brief("2330", peers=["2303", "3711"])
        self.assertEqual(set(out["peer_comparison"].keys()), {"2303", "3711"})
        for peer_code in ("2303", "3711"):
            self.assertEqual(set(out["peer_comparison"][peer_code].keys()),
                             set(DATA_BEARING_FIELDS))

    def test_peer_comparison_reuses_existing_functions_real_numbers(self):
        out = research_brief.prepare_research_brief("2330", peers=["2303"])
        peer = out["peer_comparison"]["2303"]
        self.assertEqual(peer["valuation"]["status"], "ok")
        self.assertEqual(peer["valuation"]["per"], 20.5)
        self.assertEqual(peer["balance_sheet"]["status"], "ok")
        self.assertAlmostEqual(peer["balance_sheet"]["debt_ratio"],
                               2700000000.0 / 8600000000.0)

    def test_peer_comparison_no_evaluative_or_ranking_fields(self):
        """方向A核心原則：純數字並排，不做評語/排名判斷——驗證peer_comparison
        底下每個peer的五項只有既有函式回傳的固定鍵，沒有額外塞入排名/評分/
        建議類欄位。"""
        out = research_brief.prepare_research_brief("2330", peers=["2303"])
        for field_name, section in out["peer_comparison"]["2303"].items():
            for forbidden in ("rank", "score", "recommendation", "comment", "better"):
                self.assertNotIn(forbidden, section, "%s.%s 不應有評語/排名欄位" % (field_name, forbidden))

    def test_peer_comparison_does_not_call_get_stock_info(self):
        """互斥驗證：給了peers時不該再打一次get_stock_info全量查詢
        （那是peer_candidates分支才需要的，避免多餘API呼叫）。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value=_ok_stock_info()) as mock_info:
            research_brief.prepare_research_brief("2330", peers=["2303"])
        self.assertEqual(mock_info.call_count, 0)

    def test_peer_comparison_calls_financial_apis_once_per_code(self):
        """主標的＋2個peer共3檔，財務體檢底層函式各應被呼叫3次（1主標的＋
        2 peers），不多不少。"""
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", return_value=_ok_revenue_yoy()) as m_rev, \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value=_ok_revenue_latest()), \
             unittest.mock.patch.object(
                fundamentals_client, "get_valuation", return_value=_ok_valuation()), \
             unittest.mock.patch.object(
                finmind_client, "get_institutional_trading",
                return_value=_ok_institutional()), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value=_ok_price_history()), \
             unittest.mock.patch.object(
                finmind_client, "get_balance_sheet_summary", return_value=_ok_balance_sheet()):
            research_brief.prepare_research_brief("2330", peers=["2303", "3711"])
        self.assertEqual(m_rev.call_count, 3)

    def test_peer_comparison_peer_query_failure_does_not_break_brief(self):
        """peer自己的查詢失敗只讓該peer該小節status變query_failed，不中斷
        整個啟動包組裝（跟主標的財務體檢的既有容錯行為一致）。"""
        def revenue_side_effect(code, data_dir=None, token=None):
            if code == "2303":
                return {"stock_id": "2303", "errors": ["模擬2303查詢失敗"]}
            return _ok_revenue_yoy()

        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy", side_effect=revenue_side_effect):
            out = research_brief.prepare_research_brief("2330", peers=["2303"])

        self.assertEqual(out["peer_comparison"]["2303"]["revenue_quality"]["status"],
                         "query_failed")
        # 主標的自己的財務體檢不受peer查詢失敗影響
        self.assertEqual(out["financial_check"]["revenue_quality"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
