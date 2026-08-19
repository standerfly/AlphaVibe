"""追溯層測試：分析快照＋來源、持股快照、新 MCP 工具、report 呈現。"""
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import fundamentals_client  # noqa: E402
import report  # noqa: E402
import review_engine  # noqa: E402
import server  # noqa: E402
import tpex_client  # noqa: E402
from kb_store import KBStore  # noqa: E402


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trace-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_snapshot_roundtrip_with_sources(self):
        out = self.store.save_snapshot(
            "6805", "先進封裝測試需求強勁", name="鴻勁",
            snapshot_date="2026-06-18", price_at_time=1250.0,
            valuation_at_time="PER 28", risks="單一客戶集中",
            watch_next="7 月營收", framework_version="framework_v1",
            model_id="claude-fable-5",
            sources=[
                {"url": "https://mops.example/1", "title": "5 月營收",
                 "quote_summary": "月營收 YoY +40%"},
                {"url": "https://news.example/2", "title": "法說摘要"},
            ])
        self.assertTrue(out["saved"])
        self.assertEqual(out["sources_saved"], 2)

        got = self.store.get_snapshots("6805")
        self.assertEqual(got["count"], 1)
        snap = got["snapshots"][0]
        self.assertEqual(snap["price_at_time"], 1250.0)
        self.assertEqual(snap["framework_version"], "framework_v1")
        self.assertEqual(len(snap["sources"]), 2)
        self.assertEqual(snap["sources"][0]["title"], "5 月營收")
        # retrieved_at 未給時應自動補當天
        self.assertTrue(snap["sources"][0]["retrieved_at"])

    def test_snapshot_diff_order_newest_first(self):
        self.store.save_snapshot("6805", "買進理由 v1", snapshot_date="2026-06-18",
                                 price_at_time=1250.0)
        self.store.save_snapshot("6805", "事實更新 v2", snapshot_date="2026-07-09",
                                 price_at_time=1400.0)
        got = self.store.get_snapshots("6805")
        self.assertEqual(got["count"], 2)
        self.assertEqual(got["snapshots"][0]["snapshot_date"], "2026-07-09")
        self.assertEqual(got["snapshots"][1]["snapshot_date"], "2026-06-18")

    def test_list_latest_snapshots_per_code(self):
        self.store.save_snapshot("6805", "v1", snapshot_date="2026-06-18")
        self.store.save_snapshot("6805", "v2", snapshot_date="2026-07-09",
                                 sources=[{"url": "u"}])
        self.store.save_snapshot("2330", "台積電論點", snapshot_date="2026-07-09")
        latest = self.store.list_latest_snapshots()
        self.assertEqual(len(latest), 2)
        by_code = {s["code"]: s for s in latest}
        self.assertEqual(by_code["6805"]["thesis"], "v2")
        self.assertEqual(by_code["6805"]["source_count"], 1)


class HoldingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-holdings-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_holdings_latest_and_history(self):
        self.store.save_holdings(
            [{"code": "2330", "name": "台積電", "shares": 1000, "avg_cost": 880.0},
             {"code": "6805", "shares": 2000, "avg_cost": 1100.0}],
            snapshot_date="2026-06-18", source_ref="screenshot-a.png")
        self.store.save_holdings(
            [{"code": "2330", "shares": 2000, "avg_cost": 900.0}],
            snapshot_date="2026-07-09")

        latest = self.store.get_holdings()
        self.assertEqual(latest["snapshot_date"], "2026-07-09")
        self.assertEqual(latest["count"], 1)
        self.assertEqual(latest["holdings"][0]["shares"], 2000)

        history = self.store.get_holdings("2330")
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["history"][0]["snapshot_date"], "2026-07-09")

    def test_holdings_empty_and_validation(self):
        self.assertEqual(self.store.get_holdings()["count"], 0)
        with self.assertRaises(ValueError):
            self.store.save_holdings([])
        with self.assertRaises(ValueError):
            self.store.save_holdings([{"name": "沒代碼"}])


class ServerToolsTest(unittest.TestCase):
    """直接以 Server 類別呼叫（協定層已有既有 E2E 測試涵蓋）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-tools-test-")
        self.server = server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.server.store.close()
        shutil.rmtree(self.tmp)

    def test_tools_list_has_forty_two(self):
        """2026-08-19：40→42，新增 save_position_plan／get_position_plan
        （加碼計畫總額度，補上 check_position_control 的 suggested_add_pct
        一直缺的分母）。"""
        names = [t["name"] for t in server.TOOLS]
        self.assertEqual(len(names), 42)
        for expected in ("save_snapshot", "get_snapshots",
                         "save_holdings", "get_holdings",
                         "save_stock_alias", "get_stock_alias",
                         "save_stock_theme", "get_stock_theme",
                         "save_comments_batch",
                         "get_stock_info", "get_stock_price_history",
                         "get_revenue_yoy", "get_institutional_trading",
                         "parse_holdings_report",
                         "get_emerging_stock_valuation",
                         "refresh_holdings_prices",
                         "screen_stocks",
                         "run_market_scan", "get_market_scan",
                         "save_laoyutou_trade", "get_laoyutou_trades",
                         "save_trade_ledger_entry", "get_trade_ledger",
                         "check_general_review", "check_strategy_review",
                         "check_laoyutou_signal", "check_position_control",
                         "record_module_d_findings", "run_module_d_check",
                         "parse_and_save_laoyutou_trades",
                         "parse_and_save_trade_ledger",
                         "parse_and_save_trade_csv",
                         "save_position_plan", "get_position_plan"):
            self.assertIn(expected, names)

    def test_check_laoyutou_signal_tool_dispatch_wires_args(self):
        """驗證 check_laoyutou_signal dispatch 正確傳遞參數＋預設 lookback_days
        （不打真實資料庫查詢以外的東西，這裡直接 mock review_engine 函式）。"""
        with unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value={"code": "2330", "has_signal": False,
                              "recent_trades": [], "po_holds": False,
                              "finding": "近14天無老芋頭相關動向",
                              "checked_at": "2026-07-29T00:00:00"}) as mock_review:
            out = self.server.call_tool("check_laoyutou_signal", {"code": "2330"})
            mock_review.assert_called_once_with(
                "2330", store=self.server.store, lookback_days=14)
        self.assertEqual(out["code"], "2330")

        with unittest.mock.patch.object(
                review_engine, "laoyutou_signal_review",
                return_value={"code": "2330"}) as mock_review:
            self.server.call_tool(
                "check_laoyutou_signal", {"code": "2330", "lookback_days": 30})
            mock_review.assert_called_once_with(
                "2330", store=self.server.store, lookback_days=30)

    def test_check_position_control_tool_dispatch_wires_args(self):
        """驗證 check_position_control dispatch 正確傳遞參數（含省略
        confidence_level 時傳 None）。"""
        with unittest.mock.patch.object(
                review_engine, "position_control_suggestion",
                return_value={"code": "2330", "current_position_pct": None,
                              "theme": None, "theme_concentration_pct": None,
                              "next_add_sequence": 1, "suggested_add_pct": None,
                              "suggested_initial_position_pct": None,
                              "concentration_warning": None, "detail": "",
                              "checked_at": "2026-07-29T00:00:00"}) as mock_review:
            out = self.server.call_tool("check_position_control", {"code": "2330"})
            mock_review.assert_called_once_with(
                "2330", store=self.server.store, confidence_level=None)
        self.assertEqual(out["code"], "2330")

        with unittest.mock.patch.object(
                review_engine, "position_control_suggestion",
                return_value={"code": "2330"}) as mock_review:
            self.server.call_tool(
                "check_position_control", {"code": "2330", "confidence_level": "很好"})
            mock_review.assert_called_once_with(
                "2330", store=self.server.store, confidence_level="很好")

    def test_record_module_d_findings_tool_dispatch_wires_args(self):
        """驗證 record_module_d_findings dispatch 正確傳遞參數，含 findings
        陣列與省略 date 時傳 None（不打真實資料庫查詢以外的東西，這裡直接
        mock review_engine.auto_record_findings）。"""
        findings = [
            {"trigger_label": "策略層／peg_deep_dip_concentration",
             "concern_flag": True, "detail": "PEG已回升至1.15（門檻1.0）"},
        ]
        with unittest.mock.patch.object(
                review_engine, "auto_record_findings",
                return_value={"code": "2330", "skipped": False,
                              "skip_reason": None, "has_conflict": False,
                              "written": []}) as mock_record:
            out = self.server.call_tool(
                "record_module_d_findings", {"code": "2330", "findings": findings})
            mock_record.assert_called_once_with(
                "2330", store=self.server.store, findings=findings, date=None)
        self.assertEqual(out["code"], "2330")

        with unittest.mock.patch.object(
                review_engine, "auto_record_findings",
                return_value={"code": "2330"}) as mock_record:
            self.server.call_tool("record_module_d_findings", {
                "code": "2330", "findings": findings, "date": "2026-07-29"})
            mock_record.assert_called_once_with(
                "2330", store=self.server.store, findings=findings, date="2026-07-29")

    def test_check_general_review_tool_dispatch_wires_args(self):
        """驗證 check_general_review dispatch 正確傳遞參數（不打真實 API）。"""
        with unittest.mock.patch.object(
                review_engine, "general_review",
                return_value={"code": "2330", "growth_deceleration": {},
                              "downside_risk": {}, "manual_notes": {},
                              "checked_at": "2026-07-29T00:00:00"}) as mock_review:
            out = self.server.call_tool("check_general_review", {"code": "2330"})
            mock_review.assert_called_once_with("2330", data_dir=self.server.data_dir)
        self.assertEqual(out["code"], "2330")

    def test_check_strategy_review_tool_dispatch_wires_args(self):
        """驗證 check_strategy_review dispatch 正確傳遞參數（不打真實 API）。"""
        with unittest.mock.patch.object(
                review_engine, "strategy_specific_review",
                return_value={"code": "2330", "strategy_id": "peg_deep_dip_concentration",
                              "invalidated": False, "reasons": [],
                              "current_values": {"peg": None, "drawdown_pct": None,
                                                 "revenue_yoy": None},
                              "checked_at": "2026-07-29T00:00:00"}) as mock_review:
            out = self.server.call_tool("check_strategy_review", {
                "code": "2330", "strategy_id": "peg_deep_dip_concentration"})
            mock_review.assert_called_once_with(
                "2330", "peg_deep_dip_concentration", data_dir=self.server.data_dir)
        self.assertEqual(out["code"], "2330")

    def test_run_module_d_check_tool_dispatch_wires_args(self):
        """驗證 run_module_d_check dispatch 正確傳遞參數（不打真實 API／
        DB，這裡直接 mock review_engine.run_module_d_review）。"""
        with unittest.mock.patch.object(
                review_engine, "run_module_d_review",
                return_value={"code": "2330", "checked_at": "2026-07-29T00:00:00",
                              "general": None, "strategies": [], "laoyutou": None,
                              "position_control": None, "findings": [],
                              "auto_record": None, "module_d_results_saved_count": 0,
                              "errors": {}}) as mock_review:
            out = self.server.call_tool("run_module_d_check", {"code": "2330"})
            mock_review.assert_called_once_with(
                "2330", store=self.server.store, data_dir=self.server.data_dir)
        self.assertEqual(out["code"], "2330")

    def test_traceability_tools_roundtrip(self):
        saved = self.server.call_tool("save_snapshot", {
            "code": "6805", "thesis": "測試論點",
            "price_at_time": 1250.5,
            "sources": [{"url": "https://x", "title": "來源一"}],
        })
        self.assertTrue(saved["saved"])
        got = self.server.call_tool("get_snapshots", {"code": "6805"})
        self.assertEqual(got["count"], 1)
        self.assertEqual(len(got["snapshots"][0]["sources"]), 1)

        self.server.call_tool("save_holdings", {
            "rows": [{"code": "2330", "shares": 1000}]})
        latest = self.server.call_tool("get_holdings", {})
        self.assertEqual(latest["count"], 1)

    def test_parse_holdings_report_tool_is_pure_no_db_writes(self):
        """parse_holdings_report 是純函式：呼叫後 get_holdings 仍是空的（無副作用）。"""
        out = self.server.call_tool("parse_holdings_report", {
            "text": "1785 光洋科 150 16,125 16,125 16,125 107.50"})
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(out["rows"][0]["code"], "1785")
        self.assertEqual(out["unparsed_lines"], [])
        # 純解析，不該寫進資料庫
        self.assertEqual(self.server.call_tool("get_holdings", {})["count"], 0)

    def test_laoyutou_trade_tools_roundtrip(self):
        saved = self.server.call_tool("save_laoyutou_trade", {
            "code": "2330", "name": "台積電", "action": "買",
            "shares": 1000, "price": 900.0, "date": "2026-07-20",
            "reason": "清理門戶策略轉向"})
        self.assertTrue(saved["saved"])
        got = self.server.call_tool("get_laoyutou_trades", {"code": "2330"})
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["trades"][0]["reason"], "清理門戶策略轉向")

    def test_trade_ledger_tools_roundtrip(self):
        saved = self.server.call_tool("save_trade_ledger_entry", {
            "code": "2330", "name": "台積電", "action": "買",
            "shares": 1000, "price": 900.0, "date": "2026-07-01",
            "add_sequence": 1})
        self.assertTrue(saved["saved"])
        self.server.call_tool("save_trade_ledger_entry", {
            "code": "2330", "name": "台積電", "action": "賣",
            "shares": 300, "price": 980.0, "date": "2026-07-15",
            "add_sequence": 3})
        got = self.server.call_tool("get_trade_ledger", {"code": "2330"})
        self.assertEqual(got["count"], 2)
        self.assertIsNone(got["entries"][1]["add_sequence"])

    def test_stock_alias_tools_roundtrip(self):
        saved = self.server.call_tool("save_stock_alias", {
            "name": "政美", "code": "4915", "market": "上櫃"})
        self.assertTrue(saved["saved"])
        got = self.server.call_tool("get_stock_alias", {"name": "政美"})
        self.assertTrue(got["found"])
        self.assertEqual(got["record"]["code"], "4915")

    def test_save_comments_batch_tool_partial_success(self):
        out = self.server.call_tool("save_comments_batch", {
            "comments": [
                {"body": "第一筆", "source_tag": "line"},
                {"source_tag": "line"},
            ]})
        self.assertEqual(out["saved_count"], 1)
        self.assertEqual(out["failed_count"], 1)

    def test_finmind_tools_dispatch_wires_args(self):
        """驗證 4 個新 FinMind 工具的 dispatch 正確傳遞參數（不打真實 API）。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info",
                return_value={"stock_id": None, "stocks": []}) as mock_info:
            self.server.call_tool("get_stock_info", {})
            mock_info.assert_called_once_with(stock_id=None, data_dir=self.server.data_dir)

        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history",
                return_value={"stock_id": "2330", "prices": []}) as mock_price:
            self.server.call_tool("get_stock_price_history", {
                "stock_id": "2330", "start_date": "2026-06-01", "end_date": "2026-07-01"})
            mock_price.assert_called_once_with(
                "2330", start_date="2026-06-01", end_date="2026-07-01",
                data_dir=self.server.data_dir)

        # 2026-08-01 來源選用邏輯稽核修正：get_revenue_yoy dispatch 額外呼叫
        # fundamentals_client.get_revenue_yoy_latest 附上官方優先的
        # "latest" 欄位（見 server.py），這裡一併mock掉，避免測試真的打
        # 官方TWSE/TPEx批次端點（"2330"是真實代碼，不mock會真的打網路）。
        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "2330", "revenue_yoy": []}) as mock_yoy, \
             unittest.mock.patch.object(
                fundamentals_client, "get_revenue_yoy_latest",
                return_value={"revenue_yoy": None, "revenue_period": None,
                              "market": None, "data_source": None, "error": None}
                ) as mock_latest:
            self.server.call_tool("get_revenue_yoy", {"stock_id": "2330"})
            mock_yoy.assert_called_once_with("2330", data_dir=self.server.data_dir)
            mock_latest.assert_called_once_with("2330", data_dir=self.server.data_dir)

        with unittest.mock.patch.object(
                finmind_client, "get_institutional_trading",
                return_value={"stock_id": "2330", "trading": [], "foreign_net": 0}) as mock_inst:
            self.server.call_tool("get_institutional_trading", {"stock_id": "2330"})
            mock_inst.assert_called_once_with(
                "2330", start_date=None, end_date=None, data_dir=self.server.data_dir)

    def test_get_fundamentals_dispatch_uses_official_valuation_keeps_monthly_revenue(self):
        """2026-08-01 來源選用邏輯稽核修正：get_fundamentals dispatch 的
        PER/PBR/殖利率改用 fundamentals_client.get_valuation()（官方優先），
        monthly_revenue／errors／token_used 仍來自 finmind_client.get_fundamentals
        （官方無對應多月來源，見 fundamentals_client 模組docstring）。"""
        with unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "2330", "token_used": False, "errors": [],
                             "valuation": {"date": "2026-06-01", "PER": 999.0,
                                          "PBR": 999.0, "dividend_yield": 999.0},
                             "monthly_revenue": [{"date": "2026-07-01", "revenue_year": 2026,
                                                 "revenue_month": 6, "revenue": 100}]}
                ) as mock_fund, \
             unittest.mock.patch.object(
                fundamentals_client, "get_valuation",
                return_value={"per": 32.60, "pbr": 10.67, "dividend_yield": 0.91,
                             "market": "TWSE", "data_source": "twse_official",
                             "error": None}) as mock_val:
            out = self.server.call_tool("get_fundamentals", {"stock_id": "2330"})

        mock_fund.assert_called_once_with("2330", data_dir=self.server.data_dir)
        mock_val.assert_called_once_with("2330", data_dir=self.server.data_dir)
        # 官方優先結果覆蓋掉 finmind_client.get_fundamentals 本身的valuation
        # （999.0 是刻意設的哨兵值，確認真的被覆蓋，不是巧合對上）。
        self.assertEqual(out["valuation"], {"PER": 32.60, "PBR": 10.67, "dividend_yield": 0.91})
        self.assertEqual(out["valuation_data_source"], "twse_official")
        # monthly_revenue 維持 finmind_client 的結果不動
        self.assertEqual(out["monthly_revenue"][0]["revenue"], 100)
        self.assertEqual(out["errors"], [])

    def test_get_fundamentals_dispatch_appends_error_when_valuation_fails(self):
        with unittest.mock.patch.object(
                finmind_client, "get_fundamentals",
                return_value={"stock_id": "0000", "token_used": False,
                             "errors": ["TaiwanStockMonthRevenue 無資料（代碼是否正確？）"]}), \
             unittest.mock.patch.object(
                fundamentals_client, "get_valuation",
                return_value={"per": None, "pbr": None, "dividend_yield": None,
                             "market": None, "data_source": "finmind_fallback",
                             "error": "模擬官方與FinMind估值皆查詢失敗"}):
            out = self.server.call_tool("get_fundamentals", {"stock_id": "0000"})

        self.assertIn("模擬官方與FinMind估值皆查詢失敗", out["errors"])
        self.assertIn("TaiwanStockMonthRevenue 無資料（代碼是否正確？）", out["errors"])
        self.assertIsNone(out["valuation"]["PER"])

    def test_emerging_stock_valuation_tool_dispatch_wires_args(self):
        """驗證 get_emerging_stock_valuation 的 dispatch 正確傳遞參數（不打真實 API）。"""
        with unittest.mock.patch.object(
                tpex_client, "get_emerging_stock_valuation",
                return_value={"stock_id": "6826", "caveats": [], "errors": []}) as mock_val:
            out = self.server.call_tool("get_emerging_stock_valuation", {"stock_id": "6826"})
            mock_val.assert_called_once_with("6826", data_dir=self.server.data_dir)
            self.assertEqual(out["stock_id"], "6826")

    def test_screen_stocks_tool_dispatch_parses_codes_and_wires_args(self):
        """驗證 dispatch 把逗號/換行分隔的 codes 字串正確解析成清單再轉呼叫
        screener.screen_stocks（不打真實 FinMind API）。沒給 framework_id／
        門檻參數時，kwargs 跟改動前完全一樣（只有 data_dir），維持向下相容。"""
        import screener  # noqa: E402  (延後匯入，避免污染檔案頂層 import 順序)
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value={"results": [], "total": 0}) as mock_screen:
            out = self.server.call_tool("screen_stocks", {"codes": "3485,6953\n6719"})
            mock_screen.assert_called_once_with(
                ["3485", "6953", "6719"], data_dir=self.server.data_dir)
            self.assertEqual(out, {"results": [], "total": 0})

    def test_screen_stocks_tool_rejects_unknown_framework_without_calling_api(self):
        """framework_id 無效時直接回 error，且完全不呼叫 screener.screen_stocks
        （不打任何 FinMind API）——這是計畫明訂的硬性要求。"""
        import screener  # noqa: E402
        with unittest.mock.patch.object(screener, "screen_stocks") as mock_screen:
            out = self.server.call_tool(
                "screen_stocks", {"codes": "3485", "framework_id": "no_such_framework"})
            mock_screen.assert_not_called()
        self.assertEqual(out, {"error": "未知框架：no_such_framework"})

    def test_screen_stocks_tool_dispatch_applies_framework_thresholds(self):
        """給有效 framework_id 時，帶入該框架的 peg_max/drawdown_min/drawdown_max/
        excess_drawdown_min 當作門檻（revenue_high_price_dip 的 peg_max 是 None，
        驗證 None 會被如實傳遞，不會被 args.get() 的預設值蓋掉）。"""
        import screener  # noqa: E402
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value={"results": [], "total": 0}) as mock_screen:
            self.server.call_tool(
                "screen_stocks", {"codes": "3485", "framework_id": "revenue_high_price_dip"})
            mock_screen.assert_called_once_with(
                ["3485"], data_dir=self.server.data_dir,
                framework_id="revenue_high_price_dip",
                peg_threshold=None, drawdown_min=0.15, drawdown_max=0.40,
                excess_drawdown_min=None)

    def test_screen_stocks_tool_dispatch_distinguishes_omitted_from_explicit_null(self):
        """核心語意：`"peg_threshold" in args` 判斷——顯式傳 null 要變成
        None（關掉這項條件），沒給這個參數則完全不出現在 kwargs 裡（沿用
        screener 的內建預設值）。用 args.get() 分不出這兩種情況，是這次
        設計特別要求避開的坑。"""
        import screener  # noqa: E402
        with unittest.mock.patch.object(
                screener, "screen_stocks",
                return_value={"results": [], "total": 0}) as mock_screen:
            self.server.call_tool(
                "screen_stocks", {"codes": "3485", "peg_threshold": None, "drawdown_min": 0.2})
            mock_screen.assert_called_once_with(
                ["3485"], data_dir=self.server.data_dir,
                peg_threshold=None, drawdown_min=0.2)

    def test_run_market_scan_tool_dispatch_defaults_and_persists(self):
        """未給framework_id用預設框架；成功時把結果存進DB，且回傳給MCP呼叫端
        的內容是瘦身過的摘要（DB仍存完整資料，這裡只驗證瘦身後的形狀）。"""
        import frameworks  # noqa: E402
        import market_scan  # noqa: E402
        fake_result = {
            "framework_id": "peg_deep_dip_concentration", "trigger_source": "manual",
            "candidate_count": 1, "meets_count": 1,
            "market_errors": {"TWSE": None, "TPEx": None}, "total_scanned": 1973,
            "benchmark_drawdown_pct": 0.095, "benchmark_error": None,
            "results": [{"code": "2330", "name": "台積電", "market": "TWSE",
                        "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.2,
                        "revenue_period": "2026-06", "drawdown_pct": 0.45,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 55.0, "current_date": "2026-07-20",
                        "peg": 0.5, "meets_framework": True, "error": None,
                        "market_drawdown_pct": 0.1, "excess_drawdown_pct": 0.35}],
        }
        with unittest.mock.patch.object(
                market_scan, "run_scan", return_value=fake_result) as mock_scan:
            out = self.server.call_tool("run_market_scan", {})
            mock_scan.assert_called_once_with(
                frameworks.default_framework_id(),
                data_dir=self.server.data_dir, trigger_source="manual")
        # 回傳是瘦身摘要：run 層統計數字都在，但 results 換成 meets（只留符合
        # 框架的候選，且只有精簡欄位），不是原始 fake_result 的 results 整包。
        self.assertEqual(out["framework_id"], "peg_deep_dip_concentration")
        self.assertEqual(out["candidate_count"], 1)
        self.assertEqual(out["meets_count"], 1)
        self.assertEqual(out["total_scanned"], 1973)
        self.assertNotIn("results", out)
        self.assertEqual(len(out["meets"]), 1)
        self.assertEqual(out["meets"][0]["code"], "2330")
        self.assertNotIn("high_price", out["meets"][0])  # 精簡欄位，不含完整細節
        self.assertIn("get_market_scan", out["note"])  # 提示如何取完整清單
        latest = self.server.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertTrue(latest["found"])
        self.assertEqual(latest["results"][0]["code"], "2330")
        self.assertEqual(latest["run"]["total_scanned"], 1973)

    def test_run_market_scan_tool_dispatch_passes_framework_id(self):
        import market_scan  # noqa: E402
        with unittest.mock.patch.object(
                market_scan, "run_scan",
                return_value={"error": "未知框架：nope"}) as mock_scan:
            out = self.server.call_tool("run_market_scan", {"framework_id": "nope"})
            mock_scan.assert_called_once_with(
                "nope", data_dir=self.server.data_dir, trigger_source="manual")
        self.assertEqual(out, {"error": "未知框架：nope"})

    def test_run_market_scan_tool_does_not_persist_on_error(self):
        import market_scan  # noqa: E402
        with unittest.mock.patch.object(
                market_scan, "run_scan", return_value={"error": "未知框架：x"}):
            self.server.call_tool("run_market_scan", {"framework_id": "x"})
        latest = self.server.store.get_latest_market_scan()
        self.assertFalse(latest["found"])

    def test_get_market_scan_tool_dispatch_reads_from_db(self):
        self.server.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [{"code": "2330", "name": "台積電", "market": "TWSE", "industry": "半導體業",
              "per": 10.0, "revenue_yoy": 0.2, "revenue_period": "2026-06",
              "drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
              "current_price": 55.0, "current_date": "2026-07-20", "peg": 0.5,
              "meets_framework": True, "error": None}],
            candidate_count=1)
        out = self.server.call_tool("get_market_scan", {})
        self.assertTrue(out["found"])
        self.assertEqual(out["results"][0]["code"], "2330")

    def test_get_market_scan_tool_default_shrinks_output_and_reports_counts(self):
        """預設 meets_only=true/limit=50/verbose=false：只回符合框架的候選、
        欄位精簡過，且一定附 total_results/returned/omitted/filters/
        available_frameworks，讓 AI 使用者不會把截斷後的少數幾筆誤當成
        全部候選母體。"""
        rows = [{"code": "2330", "name": "台積電", "market": "TWSE", "industry": "半導體業",
                "per": 10.0, "revenue_yoy": 0.2, "revenue_period": "2026-06",
                "drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
                "current_price": 55.0, "current_date": "2026-07-20", "peg": 0.5,
                "meets_framework": True, "error": None,
                "market_drawdown_pct": 0.1, "excess_drawdown_pct": 0.35},
               {"code": "2454", "name": "聯發科", "market": "TWSE", "industry": "半導體業",
                "per": 20.0, "revenue_yoy": 0.1, "revenue_period": "2026-06",
                "drawdown_pct": 0.1, "high_price": 100.0, "high_date": "2026-06-01",
                "current_price": 90.0, "current_date": "2026-07-20", "peg": 2.0,
                "meets_framework": False, "error": None}]
        self.server.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled", rows, candidate_count=2)
        out = self.server.call_tool("get_market_scan", {})
        self.assertTrue(out["found"])
        self.assertEqual(out["returned"], 1)  # 只有 2330 meets_framework=True
        self.assertEqual(out["total_results"], 1)
        self.assertEqual(out["omitted"], 0)
        self.assertEqual(out["filters"],
                         {"framework_id": None, "meets_only": True, "limit": 50, "verbose": False})
        self.assertIn("revenue_high_price_dip", out["available_frameworks"])
        row = out["results"][0]
        self.assertEqual(row["code"], "2330")
        self.assertNotIn("high_price", row)  # 精簡欄位，不含完整細節
        self.assertIn("excess_drawdown_pct", row)

    def test_get_market_scan_tool_verbose_meets_only_false_returns_full_rows(self):
        """meets_only=false, limit=0, verbose=true 要能拿回完整候選（含未達
        門檻的列）與完整欄位（不被精簡）。"""
        rows = [{"code": "2330", "name": "台積電", "market": "TWSE", "industry": "半導體業",
                "per": 10.0, "revenue_yoy": 0.2, "revenue_period": "2026-06",
                "drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
                "current_price": 55.0, "current_date": "2026-07-20", "peg": 0.5,
                "meets_framework": True, "error": None},
               {"code": "2454", "name": "聯發科", "market": "TWSE", "industry": "半導體業",
                "per": 20.0, "revenue_yoy": 0.1, "revenue_period": "2026-06",
                "drawdown_pct": 0.1, "high_price": 100.0, "high_date": "2026-06-01",
                "current_price": 90.0, "current_date": "2026-07-20", "peg": 2.0,
                "meets_framework": False, "error": None}]
        self.server.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled", rows, candidate_count=2)
        out = self.server.call_tool(
            "get_market_scan", {"meets_only": False, "limit": 0, "verbose": True})
        self.assertEqual(out["returned"], 2)
        self.assertEqual(out["total_results"], 2)
        self.assertIn("high_price", out["results"][0])  # verbose=true，完整欄位
        codes = {r["code"] for r in out["results"]}
        self.assertEqual(codes, {"2330", "2454"})

    def test_refresh_holdings_prices_no_holdings(self):
        """庫存是空的：不呼叫任何 FinMind API，回傳全空結果，不出錯。"""
        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history") as mock_price, \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info") as mock_info:
            out = self.server.call_tool("refresh_holdings_prices", {})
        mock_price.assert_not_called()
        mock_info.assert_not_called()
        self.assertEqual(out, {"updated": 0, "failed": [], "prices": {}})

    def test_refresh_holdings_prices_updates_multiple_codes_and_industries(self):
        self.server.store.save_holdings([
            {"code": "2330", "name": "台積電", "shares": 1000},
            {"code": "2454", "name": "聯發科", "shares": 500},
        ])

        def fake_price(stock_id, start_date=None, end_date=None, data_dir=None):
            self.assertIsNotNone(start_date)  # 用近 7 天短窗口，不是預設 90 天
            by_code = {
                "2330": [{"date": "2026-07-17", "close": 1000.0},
                         {"date": "2026-07-18", "close": 1010.0}],
                "2454": [{"date": "2026-07-18", "close": 1300.0}],
            }
            return {"stock_id": stock_id, "errors": [],
                    "prices": by_code.get(stock_id, [])}

        def fake_info(stock_id=None, data_dir=None):
            return {"stocks": [
                {"stock_id": "2330", "industry_category": "半導體業"},
                {"stock_id": "2454", "industry_category": "半導體業"},
                {"stock_id": "9999", "industry_category": "與庫存無關，不該被存"},
            ]}

        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history", fake_price), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", fake_info):
            out = self.server.call_tool("refresh_holdings_prices", {})

        self.assertEqual(out["updated"], 2)
        self.assertEqual(out["failed"], [])
        # 兩筆日期取最新一筆（2026-07-18 的 1010.0，不是先出現的 1000.0）
        self.assertEqual(out["prices"]["2330"]["price"], 1010.0)
        self.assertEqual(out["prices"]["2330"]["price_date"], "2026-07-18")
        self.assertEqual(out["prices"]["2454"]["price"], 1300.0)

        prices_in_db = self.server.store.get_stock_prices()
        self.assertEqual(prices_in_db["2454"]["price"], 1300.0)
        industries = self.server.store.get_stock_industries()
        self.assertEqual(industries["2330"]["industry_category"], "半導體業")
        self.assertNotIn("9999", industries)  # 非庫存代碼不該被順便存進來

    def test_refresh_holdings_prices_partial_failure_recorded_not_fatal(self):
        """興櫃股或查無資料的代碼記入 failed，不影響其餘檔案正常更新。"""
        self.server.store.save_holdings([
            {"code": "2330", "shares": 1000},
            {"code": "6826", "shares": 100},   # 模擬興櫃股查無 TaiwanStockPrice
        ])

        def fake_price(stock_id, start_date=None, end_date=None, data_dir=None):
            if stock_id == "6826":
                return {"stock_id": stock_id,
                        "errors": ["TaiwanStockPrice 無資料（代碼/日期區間是否正確？）"]}
            return {"stock_id": stock_id, "errors": [],
                    "prices": [{"date": "2026-07-18", "close": 900.0}]}

        def fake_info(stock_id=None, data_dir=None):
            return {"stocks": [{"stock_id": "2330", "industry_category": "半導體業"}]}

        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history", fake_price), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", fake_info):
            out = self.server.call_tool("refresh_holdings_prices", {})

        self.assertEqual(out["updated"], 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(out["failed"][0]["code"], "6826")
        self.assertIn("無資料", out["failed"][0]["reason"])
        self.assertIn("2330", out["prices"])
        self.assertNotIn("6826", out["prices"])

    def test_refresh_holdings_prices_unexpected_exception_recorded_not_fatal(self):
        """單檔查詢拋出未預期例外（非finmind_client結構化errors）不可中斷整批。

        回歸測試：2026-07-20 獨立驗收發現舊版沒有 try/except 包住單檔查詢，
        一旦某檔拋例外（而非回傳{"error":...}），迴圈會直接中斷，後面尚未
        處理的代碼(含原本會成功的)完全不會被嘗試。"""
        self.server.store.save_holdings([
            {"code": "1111", "shares": 10},   # 模擬拋出非預期例外
            {"code": "2330", "shares": 5},    # 應該仍要被嘗試且成功
        ])

        call_log = []

        def fake_price(stock_id, start_date=None, end_date=None, data_dir=None):
            call_log.append(stock_id)
            if stock_id == "1111":
                raise RuntimeError("模擬非預期例外（例如格式錯亂的API回應）")
            return {"stock_id": stock_id, "errors": [],
                    "prices": [{"date": "2026-07-20", "close": 999.0}]}

        def fake_info(stock_id=None, data_dir=None):
            return {"stocks": []}

        with unittest.mock.patch.object(
                finmind_client, "get_stock_price_history", fake_price), \
             unittest.mock.patch.object(
                finmind_client, "get_stock_info", fake_info):
            out = self.server.call_tool("refresh_holdings_prices", {})

        self.assertIn("1111", call_log)
        self.assertIn("2330", call_log)  # 2330 排在1111後面,必須仍被嘗試到
        self.assertEqual(out["updated"], 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(out["failed"][0]["code"], "1111")
        self.assertIn("2330", out["prices"])


class ReportTraceabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-report-trace-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_report_renders_snapshot_and_holdings(self):
        store = KBStore(self.tmp)
        store.save_snapshot("6805", "先進封裝需求 <強勁>", name="鴻勁",
                            snapshot_date="2026-07-09", price_at_time=1400.0,
                            framework_version="framework_v1",
                            sources=[{"url": "u", "title": "t"}])
        store.save_holdings([{"code": "6805", "shares": 2000,
                              "avg_cost": 1100.0}])
        store.close()

        out = os.path.join(self.tmp, "report.html")
        self.assertEqual(report.main(["--data-dir", self.tmp, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("分析快照", page)
        self.assertIn("framework_v1", page)
        self.assertIn("&lt;強勁&gt;", page)      # 跳脫
        self.assertIn("我的庫存與分析", page)     # 持股快照＋立場合併表格（新版）
        self.assertIn("1100.0", page)
        self.assertIn("尚無分析", page)          # 6805 有庫存但沒存立場
        self.assertIn("非投資建議", page)         # 免責聲明（NFR）
        self.assertIn("分析快照 1 檔", page)

    def test_report_merges_holdings_with_stances_and_splits_watchlist(self):
        """庫存＋立場合併成一張表；沒有立場的庫存顯示「尚無分析」；
        觀察名單立場區塊排除掉庫存代碼——三者都要驗證關聯正確、不是隨機配對。"""
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "2330", "name": "台積電", "shares": 1000, "avg_cost": 900.0},
            {"code": "2454", "name": "聯發科", "shares": 500, "avg_cost": 1200.0},
            {"code": "3661", "name": "世芯-KY", "shares": 5, "avg_cost": 3700.0},
        ])
        store.save_stance("2330", "偏多", name="台積電",
                          valuation_metric="PER 20 以下", reason="基本面穩健")
        store.save_stance("2454", "偏空", name="聯發科",
                          valuation_metric="PER 25 以上偏貴", reason="庫存去化中")
        # 3661 世芯-KY：只有庫存，故意不存立場，驗證「尚無分析」
        store.save_stance("2603", "偏多", name="長榮", reason="航運景氣回溫")
        store.save_stance("1101", "偏空", name="台泥", reason="產能過剩")
        store.close()

        out = os.path.join(self.tmp, "report.html")
        self.assertEqual(report.main(["--data-dir", self.tmp, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()

        def section_html(section_id):
            # 用 details id 定位區塊，不用標題文字 split——標題文字現在也
            # 出現在頁首目錄（TOC）連結裡，文字 split 會誤判成第一個是 TOC。
            start = page.index('id="%s"' % section_id)
            end = page.index("</details>", start)
            return page[start:end]

        holdings_section = section_html("section-holdings")
        watchlist_section = section_html("section-stance")

        def row_for(code, section):
            # 庫存總覽的代碼欄位是個股詳情頁連結（2026-08-09），格式變成
            # data-label="代碼"><a href="...">CODE</a>；純觀察區塊沒有
            # 交易/庫存資料可畫圖，仍是純文字——正則同時相容兩種格式。
            m = re.search(
                r'data-label="代碼">(?:<a[^>]*>)?%s(?:</a>)?<.*?</tr>' % re.escape(code),
                section, re.S)
            self.assertIsNotNone(m, "找不到代碼 %s 的表格列" % code)
            return m.group(0)

        row_2330 = row_for("2330", holdings_section)
        self.assertIn('data-label="股數">1000.0<', row_2330)
        self.assertIn('data-label="平均成本">900.0<', row_2330)
        self.assertIn('style="color:var(--red)">偏多<', row_2330)
        self.assertIn('data-label="估值依據">PER 20 以下<', row_2330)
        self.assertIn('data-label="理由">基本面穩健<', row_2330)

        row_2454 = row_for("2454", holdings_section)
        self.assertIn('data-label="股數">500.0<', row_2454)
        self.assertIn('data-label="平均成本">1200.0<', row_2454)
        self.assertIn('style="color:var(--green)">偏空<', row_2454)
        self.assertIn('data-label="估值依據">PER 25 以上偏貴<', row_2454)
        self.assertIn('data-label="理由">庫存去化中<', row_2454)

        row_3661 = row_for("3661", holdings_section)
        self.assertIn('data-label="股數">5.0<', row_3661)
        self.assertIn('data-label="平均成本">3700.0<', row_3661)
        self.assertIn('style="color:var(--ink-dim)">尚無分析<', row_3661)
        self.assertIn('data-label="估值依據">尚無分析<', row_3661)
        self.assertIn('data-label="理由">尚無分析<', row_3661)
        self.assertIn('data-label="更新日期">尚無分析<', row_3661)

        # 觀察名單只出現非庫存代碼，庫存代碼不該滲入
        self.assertIn('data-label="代碼">2603<', watchlist_section)
        self.assertIn('data-label="代碼">1101<', watchlist_section)
        for code in ("2330", "2454", "3661"):
            self.assertNotIn('data-label="代碼">%s<' % code, watchlist_section)

    def test_report_market_value_ratio_and_industry_with_price_cache(self):
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "2330", "name": "台積電", "shares": 1000, "avg_cost": 900.0},
            {"code": "2454", "name": "聯發科", "shares": 100, "avg_cost": 1000.0},
        ])
        store.upsert_stock_price("2330", 1000.0, "2026-07-18")
        store.upsert_stock_price("2454", 1500.0, "2026-07-18")
        store.upsert_stock_industry("2330", "半導體業")
        store.close()

        out = os.path.join(self.tmp, "report.html")
        self.assertEqual(report.main(["--data-dir", self.tmp, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()

        value_2330 = 1000 * 1000.0
        value_2454 = 100 * 1500.0
        total = value_2330 + value_2454
        ratio_2330 = value_2330 / total * 100
        ratio_2454 = value_2454 / total * 100

        self.assertIn("%s 元" % format(value_2330, ",.0f"), page)
        self.assertIn("%.1f%%" % ratio_2330, page)
        self.assertIn("%.1f%%" % ratio_2454, page)
        self.assertIn("半導體業", page)
        self.assertIn("僅計入已更新價格的持股", page)
        # updated_at 是寫入當下的時間戳（非 price_date），驗證有出現該提示文字即可
        import datetime as _dt
        self.assertIn("價格更新時間：%s" % _dt.date.today().isoformat(), page)
        # 2454 沒有存產業別快取，該欄要顯示「—」而不是空白或報錯
        self.assertIn('data-label="產業別">—<', page)

    def test_report_holdings_without_price_cache_shows_placeholder_no_crash(self):
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "6826", "name": "和淞", "shares": 10},
            {"code": "6805", "name": "鴻勁", "shares": 5},
        ])
        store.close()

        out = os.path.join(self.tmp, "report.html")
        # 完全沒有價格快取：不能除以零、不能整頁產出失敗
        self.assertEqual(report.main(["--data-dir", self.tmp, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("未更新價格", page)
        self.assertIn("尚未更新股價，執行 refresh_holdings_prices", page)

    def test_report_reason_expands_for_long_text_plain_for_short(self):
        store = KBStore(self.tmp)
        long_reason = "這是很長的理由內容" * 6  # 54 字，超過 40 字摘要門檻
        store.save_holdings([{"code": "2330", "name": "台積電", "shares": 1000}])
        store.save_stance("2330", "偏多", reason=long_reason)
        store.save_stance("2454", "偏空", name="聯發科", reason="短理由不用展開")
        store.close()

        out = os.path.join(self.tmp, "report.html")
        self.assertEqual(report.main(["--data-dir", self.tmp, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()

        # 長理由：包成 details/summary，全文仍在頁面中（展開後可見）
        self.assertIn("<details class=\"reason\">", page)
        self.assertIn(long_reason, page)
        self.assertIn(long_reason[:40], page)
        # 短理由：不多包一層 details，直接顯示全文
        self.assertIn("短理由不用展開", page)
        short_row_match = re.search(
            r'data-label="理由">[^<]*短理由不用展開', page)
        self.assertIsNotNone(short_row_match,
                             "短理由不該被包進 <details>，應直接顯示")


if __name__ == "__main__":
    unittest.main()
