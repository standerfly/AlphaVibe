"""追溯層測試：分析快照＋來源、持股快照、新 MCP 工具、report 呈現。"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import report  # noqa: E402
import server  # noqa: E402
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

    def test_tools_list_has_nineteen(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertEqual(len(names), 19)
        for expected in ("save_snapshot", "get_snapshots",
                         "save_holdings", "get_holdings",
                         "save_stock_alias", "get_stock_alias",
                         "save_comments_batch",
                         "get_stock_info", "get_stock_price_history",
                         "get_revenue_yoy", "get_institutional_trading"):
            self.assertIn(expected, names)

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

        with unittest.mock.patch.object(
                finmind_client, "get_revenue_yoy",
                return_value={"stock_id": "2330", "revenue_yoy": []}) as mock_yoy:
            self.server.call_tool("get_revenue_yoy", {"stock_id": "2330"})
            mock_yoy.assert_called_once_with("2330", data_dir=self.server.data_dir)

        with unittest.mock.patch.object(
                finmind_client, "get_institutional_trading",
                return_value={"stock_id": "2330", "trading": [], "foreign_net": 0}) as mock_inst:
            self.server.call_tool("get_institutional_trading", {"stock_id": "2330"})
            mock_inst.assert_called_once_with(
                "2330", start_date=None, end_date=None, data_dir=self.server.data_dir)


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
        self.assertIn("持股快照", page)
        self.assertIn("1100.0", page)
        self.assertIn("非投資建議", page)         # 免責聲明（NFR）
        self.assertIn("分析快照 1 檔", page)


if __name__ == "__main__":
    unittest.main()
