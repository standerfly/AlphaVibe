"""FinMind 呼叫量優化測試（2026-11）：TaiwanStockInfo 快取、營收快取 TTL、
呼叫計數器。全部 mock 網路、使用暫存目錄，不碰 poc/data。"""
import datetime
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
from kb_store import KBStore  # noqa: E402

_ROW = {"industry_category": "半導體業", "stock_id": "2330",
        "stock_name": "台積電", "type": "twse", "date": "2026-07-18"}


class StockInfoCacheTest(unittest.TestCase):
    def setUp(self):
        finmind_client.clear_stock_info_cache()
        self.addCleanup(finmind_client.clear_stock_info_cache)

    def test_second_call_hits_cache(self):
        with unittest.mock.patch.object(
                finmind_client, "_fetch", return_value={"data": [_ROW]}) as m:
            a = finmind_client.get_stock_info("2330", token="x")
            b = finmind_client.get_stock_info("2330", token="y")
        self.assertEqual(m.call_count, 1)
        self.assertEqual(a["stocks"], b["stocks"])
        self.assertEqual(b["errors"], [])

    def test_cached_copy_not_polluted_by_caller(self):
        with unittest.mock.patch.object(
                finmind_client, "_fetch", return_value={"data": [_ROW]}):
            a = finmind_client.get_stock_info("2330")
            a["stocks"][0]["stock_name"] = "被改過"
            b = finmind_client.get_stock_info("2330")
        self.assertEqual(b["stocks"][0]["stock_name"], "台積電")

    def test_error_not_cached(self):
        seq = [{"error": "模擬斷網"}, {"data": [_ROW]}]
        with unittest.mock.patch.object(
                finmind_client, "_fetch", side_effect=seq) as m:
            first = finmind_client.get_stock_info("2330")
            second = finmind_client.get_stock_info("2330")
        self.assertEqual(m.call_count, 2)
        self.assertEqual(len(first["errors"]), 1)
        self.assertEqual(second["errors"], [])

    def test_empty_data_not_cached(self):
        with unittest.mock.patch.object(
                finmind_client, "_fetch", return_value={"data": []}) as m:
            finmind_client.get_stock_info("9999")
            finmind_client.get_stock_info("9999")
        self.assertEqual(m.call_count, 2)

    def test_ttl_expiry_refetches(self):
        with unittest.mock.patch.object(
                finmind_client, "_fetch", return_value={"data": [_ROW]}) as m:
            finmind_client.get_stock_info("2330")
            key = ("", "2330")
            ts, val = finmind_client._stock_info_cache[key]
            finmind_client._stock_info_cache[key] = (
                ts - finmind_client.STOCK_INFO_TTL_SECONDS - 1, val)
            finmind_client.get_stock_info("2330")
        self.assertEqual(m.call_count, 2)

    def test_key_separates_stock_id_and_data_dir(self):
        with unittest.mock.patch.object(
                finmind_client, "_fetch", return_value={"data": [_ROW]}) as m:
            finmind_client.get_stock_info("2330")
            finmind_client.get_stock_info(None)
            finmind_client.get_stock_info("2330", data_dir="/nonexistent-a")
        self.assertEqual(m.call_count, 3)


class RevenueCacheTtlTest(unittest.TestCase):
    def test_25h_old_cache_still_hits_with_default(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        store = KBStore(tmp)
        store.save_revenue_yoy_cache("2330", {"series": [1, 2, 3]})
        old = (datetime.datetime.now()
               - datetime.timedelta(hours=25)).isoformat()
        store.conn.execute(
            "UPDATE revenue_yoy_cache SET fetched_at = ? WHERE code = ?",
            (old, "2330"))
        store.conn.commit()
        self.assertEqual(store.get_revenue_yoy_cache("2330"),
                         {"series": [1, 2, 3]})
        # 超過 26 小時仍應失效
        older = (datetime.datetime.now()
                 - datetime.timedelta(hours=27)).isoformat()
        store.conn.execute(
            "UPDATE revenue_yoy_cache SET fetched_at = ? WHERE code = ?",
            (older, "2330"))
        store.conn.commit()
        self.assertIsNone(store.get_revenue_yoy_cache("2330"))


class CallCounterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        finmind_client.set_call_log_dir(self.tmp)
        self.addCleanup(finmind_client.set_call_log_dir, None)
        self.path = os.path.join(self.tmp, finmind_client.CALL_COUNTS_FILENAME)

    def _fake_urlopen(self, payload):
        resp = unittest.mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        cm = unittest.mock.MagicMock()
        cm.__enter__.return_value = resp
        return unittest.mock.patch.object(
            finmind_client.urllib.request, "urlopen", return_value=cm)

    def test_counts_accumulate_ok_and_err(self):
        with self._fake_urlopen({"status": 200, "data": []}):
            finmind_client._fetch("TaiwanStockPER", "2330", "2026-01-01", "SECRET")
            finmind_client._fetch("TaiwanStockPER", "2330", "2026-01-01", "SECRET")
        with self._fake_urlopen({"status": 402, "msg": "limit"}):
            finmind_client._fetch("TaiwanStockPER", "2330", "2026-01-01", "SECRET")
        with unittest.mock.patch.object(
                finmind_client.urllib.request, "urlopen",
                side_effect=OSError("boom")):
            finmind_client._fetch("TaiwanStockInfo", None, None, "SECRET")
        with open(self.path, encoding="utf-8") as fh:
            raw = fh.read()
        counts = json.loads(raw)
        today = datetime.date.today().isoformat()
        self.assertEqual(counts[today]["TaiwanStockPER"], {"ok": 2, "err": 1})
        self.assertEqual(counts[today]["TaiwanStockInfo"], {"ok": 0, "err": 1})
        self.assertNotIn("SECRET", raw)
        self.assertNotIn("token", raw.lower())

    def test_write_failure_is_silent(self):
        ro = os.path.join(self.tmp, "ro")
        os.mkdir(ro)
        os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, ro, stat.S_IRWXU)
        finmind_client.set_call_log_dir(ro)
        with self._fake_urlopen({"status": 200, "data": [1]}):
            out = finmind_client._fetch("TaiwanStockPER", "2330", None, "")
        self.assertEqual(out, {"data": [1]})
        # 目錄不存在也不丟例外
        finmind_client.set_call_log_dir(os.path.join(self.tmp, "nope"))
        with self._fake_urlopen({"status": 200, "data": []}):
            finmind_client._fetch("TaiwanStockPER", "2330", None, "")

    def test_corrupt_file_is_recovered(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{壞掉")
        with self._fake_urlopen({"status": 200, "data": []}):
            finmind_client._fetch("TaiwanStockPrice", "2330", None, "")
        with open(self.path, encoding="utf-8") as fh:
            counts = json.load(fh)
        today = datetime.date.today().isoformat()
        self.assertEqual(counts[today]["TaiwanStockPrice"]["ok"], 1)

    def test_no_dir_configured_writes_nothing(self):
        finmind_client.set_call_log_dir(None)
        saved = finmind_client._call_log_dir
        finmind_client._call_log_dir = None
        self.addCleanup(setattr, finmind_client, "_call_log_dir", saved)
        with self._fake_urlopen({"status": 200, "data": []}):
            finmind_client._fetch("TaiwanStockPrice", "2330", None, "")
        self.assertFalse(os.path.exists(self.path))

    def test_explicit_token_still_counts_via_public_function(self):
        # 回歸：呼叫端傳了 token 會讓 `token or _read_token()` 短路，
        # 計數器不能因此漏記（公開函式要自己記住 data_dir）
        finmind_client.set_call_log_dir(None)
        finmind_client._call_log_dir = None
        self.addCleanup(finmind_client.set_call_log_dir, None)
        finmind_client.clear_stock_info_cache()
        payload = {"status": 200, "data": [
            {"stock_id": "2330", "stock_name": "台積電",
             "industry_category": "半導體業", "type": "twse", "date": "2026-01-01"}]}
        with self._fake_urlopen(payload):
            finmind_client.get_stock_info(data_dir=self.tmp, token="SECRET")
        with open(self.path, encoding="utf-8") as fh:
            counts = json.load(fh)
        today = datetime.date.today().isoformat()
        self.assertEqual(counts[today]["TaiwanStockInfo"]["ok"], 1)


if __name__ == "__main__":
    unittest.main()
