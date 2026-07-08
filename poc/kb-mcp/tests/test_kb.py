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
