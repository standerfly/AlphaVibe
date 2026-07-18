"""alphavibe-kb 測試：儲存層單元測試＋MCP 協定端到端煙霧測試。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
from kb_store import KBStore  # noqa: E402

SERVER = os.path.join(os.path.dirname(HERE), "server.py")


class KBStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-kb-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_stance_save_and_get(self):
        out = self.store.save_stance("2330", "偏多", name="台積電",
                                     reason="先進封裝需求強",
                                     entry_condition="900 以下分批",
                                     source_ref="conv#1")
        self.assertTrue(out["saved"])
        self.assertFalse(out["conflict"])
        latest = self.store.get_latest_stance("2330")
        self.assertEqual(latest["stance"], "偏多")
        self.assertEqual(latest["entry_condition"], "900 以下分批")

    def test_stance_conflict_blocks_until_overwrite(self):
        self.store.save_stance("2330", "偏多", date="2026-07-01")
        blocked = self.store.save_stance("2330", "偏空", date="2026-07-08")
        self.assertFalse(blocked["saved"])
        self.assertTrue(blocked["conflict"])
        self.assertEqual(blocked["existing"]["stance"], "偏多")
        # 使用者確認後 overwrite 才會寫入，且立場歷史保留兩筆
        forced = self.store.save_stance("2330", "偏空", date="2026-07-08",
                                        overwrite=True)
        self.assertTrue(forced["saved"])
        self.assertTrue(forced["conflict"])
        self.assertEqual(self.store.get_latest_stance("2330")["stance"], "偏空")
        self.assertEqual(len(self.store.get_stance_history("2330")), 2)

    def test_same_stance_is_not_conflict(self):
        self.store.save_stance("2454", "偏多")
        again = self.store.save_stance("2454", "偏多", reason="補理由")
        self.assertTrue(again["saved"])
        self.assertFalse(again["conflict"])

    def test_list_stances_latest_per_code(self):
        self.store.save_stance("2330", "偏多", date="2026-07-01")
        self.store.save_stance("2330", "中性", date="2026-07-05", overwrite=True)
        self.store.save_stance("2454", "觀望", date="2026-07-02")
        stances = self.store.list_stances()
        self.assertEqual(len(stances), 2)
        by_code = {s["code"]: s["stance"] for s in stances}
        self.assertEqual(by_code["2330"], "中性")

    def test_comment_chinese_fulltext_search(self):
        self.store.save_comment("今日大盤量縮整理，觀望 FOMC 決議",
                                source_tag="conversation", symbols="TAIEX")
        self.store.save_comment("台積電法說會後外資調升目標價",
                                source_tag="line", symbols="2330")
        hit = self.store.search_comments("法說會")
        self.assertEqual(hit["count"], 1)
        self.assertIn("台積電", hit["results"][0]["body"])
        miss = self.store.search_comments("聯發科")
        self.assertEqual(miss["count"], 0)
        short = self.store.search_comments("台")
        self.assertIn("error", short)

    def test_comments_batch_all_success(self):
        out = self.store.save_comments_batch([
            {"body": "早盤觀察：外資買超金融股", "source_tag": "line"},
            {"body": "尾盤拉抬電子權值股", "source_tag": "youtube", "symbols": "2330"},
        ])
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["saved_count"], 2)
        self.assertEqual(out["failed_count"], 0)
        self.assertTrue(all(r["saved"] for r in out["results"]))
        self.assertEqual(self.store.recent_comments(10)["count"], 2)

    def test_comments_batch_partial_success_keeps_valid_rows(self):
        out = self.store.save_comments_batch([
            {"body": "合法評論一", "source_tag": "line"},
            {"body": "", "source_tag": "line"},           # 缺 body（空字串）
            {"body": "合法評論二", "source_tag": "conversation"},
            {"source_tag": "line"},                        # 缺 body（key 都沒有）
        ])
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["saved_count"], 2)
        self.assertEqual(out["failed_count"], 2)
        self.assertTrue(out["results"][0]["saved"])
        self.assertFalse(out["results"][1]["saved"])
        self.assertIn("body", out["results"][1]["error"])
        self.assertTrue(out["results"][2]["saved"])
        self.assertFalse(out["results"][3]["saved"])
        # 只有合法的兩筆真的寫入資料庫，非法的兩筆不能讓整批全部失敗
        self.assertEqual(self.store.recent_comments(10)["count"], 2)

    def test_comments_batch_empty_list(self):
        out = self.store.save_comments_batch([])
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["saved_count"], 0)
        self.assertEqual(out["failed_count"], 0)
        self.assertEqual(out["results"], [])

    def test_stock_alias_save_and_get(self):
        out = self.store.save_stock_alias("環宇KY", "4991", name_full="環宇-KY",
                                          market="上市", source="公開資訊觀測站")
        self.assertTrue(out["saved"])
        self.assertEqual(out["record"]["code"], "4991")
        got = self.store.get_stock_alias("環宇KY")
        self.assertTrue(got["found"])
        self.assertEqual(got["record"]["code"], "4991")
        self.assertEqual(got["record"]["market"], "上市")

    def test_stock_alias_not_found(self):
        got = self.store.get_stock_alias("不存在的股票")
        self.assertFalse(got["found"])
        self.assertEqual(got["name"], "不存在的股票")

    def test_stock_alias_same_name_overwrites(self):
        self.store.save_stock_alias("奇鼎", "3722", source="第一次查證")
        updated = self.store.save_stock_alias("奇鼎", "3722", source="第二次查證",
                                               market="上櫃")
        self.assertTrue(updated["saved"])
        got = self.store.get_stock_alias("奇鼎")
        self.assertEqual(got["record"]["source"], "第二次查證")
        self.assertEqual(got["record"]["market"], "上櫃")
        # 同名再存＝更新，不是新增第二筆
        self.assertEqual(self.store.get_stock_alias()["count"], 1)

    def test_stock_alias_list_all_sorted_newest_first(self):
        self.store.save_stock_alias("A股", "1111", verified_date="2026-07-01")
        self.store.save_stock_alias("B股", "2222", verified_date="2026-07-10")
        all_aliases = self.store.get_stock_alias()
        self.assertEqual(all_aliases["count"], 2)
        self.assertEqual(all_aliases["aliases"][0]["name"], "B股")

    def test_philosophy_roundtrip_and_append(self):
        self.store.save_philosophy("yuzhiyu", "# 低 PER 高殖利率")
        self.store.save_philosophy("yuzhiyu", "恐慌分批買入", mode="append")
        got = self.store.get_philosophy("yuzhiyu")
        self.assertIn("低 PER", got["content"])
        self.assertIn("恐慌分批", got["content"])
        self.assertEqual(self.store.list_philosophy()["count"], 1)
        missing = self.store.get_philosophy("nobody")
        self.assertIn("error", missing)

    def test_philosophy_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            self.store.save_philosophy("../evil", "x")


class FinMindClientTest(unittest.TestCase):
    def test_parses_mocked_payload(self):
        per_payload = {"status": 200, "data": [
            {"date": "2026-07-07", "PER": 18.5, "PBR": 5.1, "dividend_yield": 2.1}]}
        rev_payload = {"status": 200, "data": [
            {"date": "2026-06-01", "revenue": 123}, {"date": "2026-07-01", "revenue": 456}]}

        def fake_fetch(dataset, stock_id, start_date, token):
            return {"data": per_payload["data"]} if dataset == "TaiwanStockPER" \
                else {"data": rev_payload["data"]}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_fundamentals("2330")
        self.assertEqual(out["valuation"]["PER"], 18.5)
        self.assertEqual(len(out["monthly_revenue"]), 2)
        self.assertEqual(out["errors"], [])

    def test_network_failure_returns_hint(self):
        def fail(dataset, stock_id, start_date, token):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_fundamentals("2330")
        self.assertEqual(len(out["errors"]), 2)
        self.assertIn("hint", out)

    def test_get_stock_info_parses_mocked_payload(self):
        payload = [
            {"industry_category": "半導體業", "stock_id": "2330",
             "stock_name": "台積電", "type": "twse", "date": "2026-07-18"},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockInfo")
            self.assertIsNone(start_date)
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_stock_info("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["stocks"]), 1)
        self.assertEqual(out["stocks"][0]["industry_category"], "半導體業")
        self.assertEqual(out["stocks"][0]["stock_name"], "台積電")

    def test_get_stock_info_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_stock_info("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("stocks", out)

    def test_get_stock_price_history_parses_mocked_payload(self):
        payload = [
            {"date": "2026-07-08", "stock_id": "2330", "Trading_Volume": 25519599,
             "Trading_money": 62400639776, "open": 2445.0, "max": 2465.0,
             "min": 2420.0, "close": 2465.0, "spread": 25.0, "Trading_turnover": 94688},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockPrice")
            self.assertIsNotNone(start_date)
            self.assertIsNotNone(end_date)
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_stock_price_history("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["prices"]), 1)
        self.assertEqual(out["prices"][0]["close"], 2465.0)
        self.assertEqual(out["prices"][0]["Trading_Volume"], 25519599)

    def test_get_stock_price_history_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_stock_price_history("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("prices", out)

    def test_get_revenue_yoy_calculates_growth(self):
        payload = [
            {"date": "2025-06-01", "stock_id": "2330", "revenue": 200000,
             "revenue_month": 5, "revenue_year": 2025},
            {"date": "2025-07-01", "stock_id": "2330", "revenue": 100000,
             "revenue_month": 6, "revenue_year": 2025},
            {"date": "2026-07-01", "stock_id": "2330", "revenue": 150000,
             "revenue_month": 6, "revenue_year": 2026},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockMonthRevenue")
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_revenue_yoy("2330")
        self.assertEqual(out["errors"], [])
        by_ym = {(r["revenue_year"], r["revenue_month"]): r for r in out["revenue_yoy"]}
        # 2026/6 對比 2025/6：(150000-100000)/100000 = 0.5
        self.assertAlmostEqual(by_ym[(2026, 6)]["yoy_growth"], 0.5)
        # 2025/5 沒有 2024/5 資料可比對，年增率應為 null
        self.assertIsNone(by_ym[(2025, 5)]["yoy_growth"])
        # 2025/6 沒有 2024/6 資料可比對，年增率應為 null
        self.assertIsNone(by_ym[(2025, 6)]["yoy_growth"])

    def test_get_revenue_yoy_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_revenue_yoy("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("revenue_yoy", out)

    def test_get_institutional_trading_sums_foreign_net(self):
        # name 值為 2026-07-18 對 2330 實測 FinMind API 確認的真實分類字串
        payload = [
            {"date": "2026-07-13", "stock_id": "2330", "name": "Foreign_Investor",
             "buy": 16267509, "sell": 29016050},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Foreign_Dealer_Self",
             "buy": 0, "sell": 0},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Investment_Trust",
             "buy": 361457, "sell": 318232},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Dealer_self",
             "buy": 392405, "sell": 391500},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Dealer_Hedging",
             "buy": 636358, "sell": 547400},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockInstitutionalInvestorsBuySell")
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_institutional_trading("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["trading"]), 5)
        # foreign_net = Foreign_Investor(16267509-29016050) + Foreign_Dealer_Self(0-0)
        self.assertEqual(out["foreign_net"], 16267509 - 29016050)

    def test_get_institutional_trading_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_institutional_trading("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("trading", out)


class ProtocolE2ETest(unittest.TestCase):
    """實際啟動 server 子行程，走一遍 initialize → tools/list → tools/call。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-mcp-e2e-")
        env = dict(os.environ, ALPHAVIBE_DATA_DIR=self.tmp)
        self.proc = subprocess.Popen(
            [sys.executable, SERVER], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, text=True, bufsize=1,
        )

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        shutil.rmtree(self.tmp)

    def _rpc(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.assertTrue(line, "server 沒有回應")
        return json.loads(line)

    def test_full_handshake_and_tool_call(self):
        init = self._rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "0"}}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "alphavibe-kb")
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")

        # notification：不應有回應（下一個 request 的回覆 id 須是 2）
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()

        tools = self._rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(tools["id"], 2)
        names = [t["name"] for t in tools["result"]["tools"]]
        for expected in ("save_stance", "get_stance", "list_stances",
                         "save_comment", "search_comments",
                         "save_philosophy", "get_philosophy", "get_fundamentals"):
            self.assertIn(expected, names)

        saved = self._rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "save_stance",
                                      "arguments": {"code": "2330", "stance": "偏多",
                                                    "source_ref": "e2e"}}})
        self.assertFalse(saved["result"]["isError"])
        body = json.loads(saved["result"]["content"][0]["text"])
        self.assertTrue(body["saved"])

        got = self._rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                         "params": {"name": "get_stance",
                                    "arguments": {"code": "2330"}}})
        body = json.loads(got["result"]["content"][0]["text"])
        self.assertTrue(body["found"])
        self.assertEqual(body["latest"]["stance"], "偏多")

        unknown = self._rpc({"jsonrpc": "2.0", "id": 5, "method": "no/such"})
        self.assertEqual(unknown["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
