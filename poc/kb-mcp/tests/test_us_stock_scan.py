"""`us_stock_scan.py` 測試：mock price client，驗證單一股票失敗時其餘
股票仍正常寫入（graceful degradation，比照 market_scan.py 的既有降級
模式測試精神）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_stock_scan  # noqa: E402
import us_stock_price_client  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402


def _fake_get_quote(ticker, data_dir=None, token=None):
    if ticker == "BAD":
        return {"error": "FMP HTTP 402（配額用盡）"}
    return {"ticker": ticker, "close_price": 100.0 + len(ticker),
            "change_pct": 1.5, "source": "fmp"}


def _fake_get_fundamentals(ticker, data_dir=None, token=None):
    return {"ticker": ticker, "gaap_gross_margin": 0.75,
            "revenue_yoy": 0.12, "source": "fmp"}


class RunScanGracefulDegradationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-scan-test-")
        store = USStockStore(self.tmp)
        # 三檔追蹤中股票：兩檔會成功、一檔（BAD）模擬額度用盡失敗。
        store.save_trade(ticker="NET", trade_date="2026-08-05",
                          action="buy", shares=10, price=298.40)
        store.save_watch_condition(ticker="CRWD", metric_type="price",
                                    comparator="gt", threshold=400)
        store.save_watch_condition(ticker="BAD", metric_type="price",
                                    comparator="lt", threshold=100)
        store.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_one_ticker_failure_does_not_block_others(self):
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        by_ticker = {row["ticker"]: row for row in result["results"]}
        self.assertEqual(set(by_ticker.keys()), {"NET", "CRWD", "BAD"})

        self.assertTrue(by_ticker["NET"]["saved"])
        self.assertIsNone(by_ticker["NET"]["error"])
        self.assertTrue(by_ticker["CRWD"]["saved"])
        self.assertIsNone(by_ticker["CRWD"]["error"])

        self.assertFalse(by_ticker["BAD"]["saved"])
        self.assertIsNotNone(by_ticker["BAD"]["error"])

    def test_failed_ticker_leaves_no_snapshot_row_others_written(self):
        """額度用盡的股票當天完全沒有 us_price_snapshots 紀錄（歷史缺口，
        data-model.md §4 的預期行為），成功的股票正常寫入。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        store = USStockStore(self.tmp)
        try:
            net_snapshots = store.list_price_snapshots("NET")
            crwd_snapshots = store.list_price_snapshots("CRWD")
            bad_snapshots = store.list_price_snapshots("BAD")
        finally:
            store.close()

        self.assertEqual(len(net_snapshots), 1)
        self.assertEqual(net_snapshots[0]["snapshot_date"], result["snapshot_date"])
        self.assertEqual(len(crwd_snapshots), 1)
        self.assertEqual(len(bad_snapshots), 0)

    def test_fundamentals_failure_does_not_block_price_write(self):
        """基本面查詢失敗不影響報價本身寫入——兩者是獨立欄位。"""
        def failing_fundamentals(ticker, data_dir=None, token=None):
            return {"error": "FMP 無此股票損益表資料：%s" % ticker}

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=failing_fundamentals):
            result = us_stock_scan.run_scan(self.tmp)

        by_ticker = {row["ticker"]: row for row in result["results"]}
        self.assertTrue(by_ticker["NET"]["saved"])
        self.assertIsNone(by_ticker["NET"]["gaap_gross_margin"])
        self.assertIsNone(by_ticker["NET"]["revenue_yoy"])


class MainCliExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-scan-test-")
        store = USStockStore(self.tmp)
        store.save_trade(ticker="NET", trade_date="2026-08-05",
                          action="buy", shares=10, price=298.40)
        store.save_watch_condition(ticker="BAD", metric_type="price",
                                    comparator="lt", threshold=100)
        store.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_partial_failure_returns_nonzero_but_still_writes_success(self):
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_fake_get_quote), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=_fake_get_fundamentals):
            exit_code = us_stock_scan.main(
                ["--data-dir", self.tmp, "--trigger", "manual"])

        self.assertEqual(exit_code, 1)
        store = USStockStore(self.tmp)
        try:
            self.assertEqual(len(store.list_price_snapshots("NET")), 1)
        finally:
            store.close()


def _quote_ok(ticker, data_dir=None, token=None):
    """價格 300，高於本檔測試用的門檻（<200），評估結果應為 ok。"""
    return {"ticker": ticker, "close_price": 300.0, "source": "fmp"}


def _quote_low(ticker, data_dir=None, token=None):
    """價格 150，低於本檔測試用的門檻（<200），評估結果應為 alert。"""
    return {"ticker": ticker, "close_price": 150.0, "source": "fmp"}


def _quote_quota_exhausted(ticker, data_dir=None, token=None):
    return {"error": "FMP HTTP 402（配額用盡）"}


def _fundamentals_ok(ticker, data_dir=None, token=None):
    return {"ticker": ticker, "gaap_gross_margin": 0.75,
            "revenue_yoy": 0.12, "source": "fmp"}


class WatchConditionEvaluationTest(unittest.TestCase):
    """T031：監控條件評估＋推播觸發測試，對應 FR-011/012/017 與
    data-model.md §3 狀態轉換規則——這是本次規劃最容易做錯的地方（見
    tasks.md T031 附註），逐一覆蓋 4 個情境：(a) 正常評估觸發推播、
    (b) 持續 alert 不重複推播、(c) 額度用盡跳過＝「未更新（無額度）」、
    非「資料不足」、(d) 從未成功取得過資料＝「資料不足」、非「未更新」。

    監控條件固定用 metric_type=price／comparator=lt／threshold=200，
    `_quote_ok`（300，不觸發）／`_quote_low`（150，觸發）兩個 fake quote
    函式模擬「這輪有沒有碰觸門檻」，`_quote_quota_exhausted` 模擬整檔
    股票額度用盡跳過。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-scan-watch-test-")
        store = USStockStore(self.tmp)
        self.condition_id = store.save_watch_condition(
            ticker="TRIG", metric_type="price", comparator="lt",
            threshold=200)["id"]
        store.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _condition(self):
        store = USStockStore(self.tmp)
        try:
            return store.get_watch_condition(self.condition_id)
        finally:
            store.close()

    def _updates_for(self, result, ticker="TRIG"):
        return [u for u in result["condition_updates"] if u["ticker"] == ticker]

    def test_a_transition_to_alert_triggers_notify(self):
        """(a) 正常評估：狀態從非 alert 轉為 alert 時呼叫 notify_telegram，
        訊息內容帶有 ticker（可辨識是哪一檔股票的通知）。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_ok), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            result1 = us_stock_scan.run_scan(self.tmp)

        # 第一輪：300 > 200，不觸發，狀態轉為 ok，不推播。
        self.assertEqual(self._condition()["status"], "ok")
        mock_notify.assert_not_called()
        updates1 = self._updates_for(result1)
        self.assertEqual(len(updates1), 1)
        self.assertEqual(updates1[0]["new_status"], "ok")
        self.assertFalse(updates1[0]["newly_triggered"])

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_low), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            result2 = us_stock_scan.run_scan(self.tmp)

        # 第二輪：150 < 200，觸發，狀態轉為 alert，推播一次。
        condition_after = self._condition()
        self.assertEqual(condition_after["status"], "alert")
        self.assertIsNotNone(condition_after["last_notified_at"])
        mock_notify.assert_called_once()
        self.assertIn("TRIG", mock_notify.call_args[0][0])
        updates2 = self._updates_for(result2)
        self.assertEqual(len(updates2), 1)
        self.assertTrue(updates2[0]["newly_triggered"])
        self.assertTrue(updates2[0]["notified"])

    def test_b_continuous_alert_not_renotified(self):
        """(b) 同一項門檻持續處於已觸發狀態時不重複推播。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_low), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            us_stock_scan.run_scan(self.tmp)  # insufficient_data -> alert：第一次觸發
        mock_notify.assert_called_once()
        first_notified_at = self._condition()["last_notified_at"]

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_low), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify2:
            result2 = us_stock_scan.run_scan(self.tmp)  # 持續 alert：第二次不應推播

        mock_notify2.assert_not_called()
        self.assertEqual(self._condition()["last_notified_at"], first_notified_at)
        updates2 = self._updates_for(result2)
        self.assertEqual(updates2[0]["new_status"], "alert")
        self.assertFalse(updates2[0]["newly_triggered"])

    def test_c_quota_exhausted_is_stale_not_insufficient_data(self):
        """(c) 額度用盡跳過：status／last_evaluated_at 完全不變，
        `is_stale` 判斷為 True（「未更新（無額度）」），但 status 仍是
        上一次成功評估的值（不是 insufficient_data），也不觸發推播——這是
        FR-017 最核心、最容易做錯的區分。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_ok), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True):
            us_stock_scan.run_scan(self.tmp)
        before = self._condition()
        self.assertEqual(before["status"], "ok")
        self.assertIsNotNone(before["last_evaluated_at"])

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote",
                side_effect=_quote_quota_exhausted), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            result2 = us_stock_scan.run_scan(self.tmp)

        after = self._condition()
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["last_evaluated_at"], before["last_evaluated_at"])
        mock_notify.assert_not_called()
        # 額度用盡跳過的股票，其監控條件完全不出現在這輪的 condition_updates——
        # 證明評估這個步驟整個被跳過，不是「評估了但結果剛好沒變」。
        self.assertEqual(self._updates_for(result2), [])

        store = USStockStore(self.tmp)
        try:
            stale_view = store.list_watch_conditions_with_stale(
                "TRIG", today_str="2099-12-31")  # 模擬「今天」跟上次評估不同天
        finally:
            store.close()
        self.assertTrue(stale_view[0]["is_stale"])
        self.assertEqual(stale_view[0]["status"], "ok")  # 不是 insufficient_data

    def test_d_never_fetched_is_insufficient_data_not_stale(self):
        """(d) 從未成功取得過資料：status 維持 insufficient_data、
        last_evaluated_at 維持 None，`is_stale` 恆為 False——正確顯示
        「資料不足」而非「未更新（無額度）」，兩者不得互相誤判。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote",
                side_effect=_quote_quota_exhausted), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            us_stock_scan.run_scan(self.tmp)

        condition = self._condition()
        self.assertEqual(condition["status"], "insufficient_data")
        self.assertIsNone(condition["last_evaluated_at"])
        mock_notify.assert_not_called()

        store = USStockStore(self.tmp)
        try:
            stale_view = store.list_watch_conditions_with_stale(
                "TRIG", today_str="2099-12-31")
        finally:
            store.close()
        self.assertFalse(stale_view[0]["is_stale"])
        self.assertEqual(stale_view[0]["status"], "insufficient_data")

    def test_notify_failure_still_updates_status_but_not_last_notified_at(self):
        """notify_telegram 回傳 False（推播失敗）：警示狀態仍正常標示
        （spec.md Acceptance Scenario 5：不因推播失敗而遺漏警示），但
        `last_notified_at` 不更新——設計取捨：讓下一輪只要仍是 alert
        狀態就會重試推播，見 notify_telegram() docstring 第3點。"""
        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_low), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals", side_effect=_fundamentals_ok), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=False) as mock_notify:
            us_stock_scan.run_scan(self.tmp)

        condition = self._condition()
        self.assertEqual(condition["status"], "alert")  # 狀態仍正確標示
        self.assertIsNone(condition["last_notified_at"])  # 但沒記錄成功推播
        mock_notify.assert_called_once()

    def test_metric_missing_this_round_does_not_touch_condition(self):
        """股票整體排程成功（saved=True），但這筆條件對應的 metric_type
        這輪沒有值（例如基本面查詢單獨失敗）：條件維持原狀不動，不誤判為
        insufficient_data，也不當作「已評估」。"""
        store = USStockStore(self.tmp)
        margin_condition_id = store.save_watch_condition(
            ticker="TRIG", metric_type="gaap_gross_margin",
            comparator="lt", threshold=0.5)["id"]
        store.close()

        def failing_fundamentals(ticker, data_dir=None, token=None):
            return {"error": "FMP 無此股票損益表資料：%s" % ticker}

        with unittest.mock.patch.object(
                us_stock_price_client, "get_quote", side_effect=_quote_ok), \
             unittest.mock.patch.object(
                us_stock_price_client, "get_fundamentals",
                side_effect=failing_fundamentals), \
             unittest.mock.patch.object(
                us_stock_scan, "notify_telegram", return_value=True) as mock_notify:
            result = us_stock_scan.run_scan(self.tmp)

        store = USStockStore(self.tmp)
        try:
            margin_condition = store.get_watch_condition(margin_condition_id)
        finally:
            store.close()
        self.assertEqual(margin_condition["status"], "insufficient_data")
        self.assertIsNone(margin_condition["last_evaluated_at"])
        mock_notify.assert_not_called()
        margin_updates = [u for u in result["condition_updates"]
                           if u["condition_id"] == margin_condition_id]
        self.assertEqual(margin_updates, [])
        # 同一輪同一檔股票的 price 條件（本檔案 setUp 建立）正常評估——
        # 證明「這輪 metric 缺值」只影響對應的那一筆條件，不影響同股票
        # 其他監控條件的評估。
        price_updates = self._updates_for(result)
        self.assertEqual(len(price_updates), 1)
        self.assertEqual(price_updates[0]["new_status"], "ok")


class NotifyTelegramTest(unittest.TestCase):
    """`notify_telegram()` 本身的 HTTP 呼叫邏輯——上面所有測試都是
    mock 掉整個函式，完全沒測到這裡的實作，補上。全程用暫存設定檔
    （`STND_GATEWAY_ENV_FILE` 覆寫），不動、不讀真正的
    `~/.config/stnd-gateway/.env`，也不會真的打網路（mock urlopen）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.env_path = os.path.join(self.tmpdir, "fake.env")
        self._orig_env_file = us_stock_scan._GATEWAY_ENV_FILE
        self._orig_env_var = os.environ.get("STND_GATEWAY_ENV_FILE")

    def tearDown(self):
        us_stock_scan._GATEWAY_ENV_FILE = self._orig_env_file
        if self._orig_env_var is None:
            os.environ.pop("STND_GATEWAY_ENV_FILE", None)
        else:
            os.environ["STND_GATEWAY_ENV_FILE"] = self._orig_env_var
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_env(self, token="fake-token:ABC", allowed_ids="111,222"):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("TELEGRAM_BOT_TOKEN=%s\n" % token)
            f.write("ALLOWED_USER_IDS=%s\n" % allowed_ids)
        import pathlib
        us_stock_scan._GATEWAY_ENV_FILE = pathlib.Path(self.env_path)

    def test_missing_env_file_returns_false_no_network_call(self):
        """設定檔不存在：直接回 False，不嘗試打網路。"""
        import pathlib
        us_stock_scan._GATEWAY_ENV_FILE = pathlib.Path(self.tmpdir) / "nope.env"
        with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
            result = us_stock_scan.notify_telegram("測試訊息")
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_missing_token_returns_false(self):
        self._write_env(token="", allowed_ids="111")
        with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
            result = us_stock_scan.notify_telegram("測試訊息")
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_success_calls_correct_url_and_payload(self):
        """驗證真的打到 Telegram Bot API 的 sendMessage 端點，payload
        帶對的 chat_id／text，且 token 不外洩進任何例外訊息或回傳值。"""
        self._write_env(token="fake-token:ABC", allowed_ids="111")
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"ok":true}'
        with unittest.mock.patch(
                "urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = us_stock_scan.notify_telegram("股價跌破門檻")
        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        request_obj = mock_urlopen.call_args[0][0]
        self.assertEqual(
            request_obj.full_url,
            "https://api.telegram.org/botfake-token:ABC/sendMessage")
        sent_payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(sent_payload, {"chat_id": "111", "text": "股價跌破門檻"})

    def test_multiple_chat_ids_partial_failure_still_true(self):
        """兩個白名單使用者，其中一個發送失敗（例如封鎖了bot）：
        只要有一個成功就整體回傳True，不能因一人失敗就讓所有人都收不到。"""
        self._write_env(token="fake-token:ABC", allowed_ids="111,222")
        mock_resp = unittest.mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"ok":true}'

        def _side_effect(req, timeout=None):
            if b'"chat_id": "222"' in req.data:
                raise urllib.error.URLError("blocked")
            return mock_resp

        with unittest.mock.patch(
                "urllib.request.urlopen", side_effect=_side_effect):
            result = us_stock_scan.notify_telegram("測試")
        self.assertTrue(result)

    def test_all_chat_ids_fail_returns_false(self):
        self._write_env(token="fake-token:ABC", allowed_ids="111")
        with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("network down")):
            result = us_stock_scan.notify_telegram("測試")
        self.assertFalse(result)

    def test_network_failure_does_not_raise(self):
        """網路層失敗（非HTTPError）也不能讓呼叫端整個炸掉——
        FR相關：推播失敗不能影響其他股票/條件的評估流程。"""
        self._write_env()
        with unittest.mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("timeout")):
            try:
                result = us_stock_scan.notify_telegram("測試")
            except Exception as exc:  # noqa: BLE001
                self.fail("notify_telegram 不應該拋出例外，實際拋出：%r" % exc)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
