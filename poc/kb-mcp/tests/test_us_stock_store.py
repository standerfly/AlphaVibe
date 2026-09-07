"""`us_stock_store.py` 測試：schema 建立、CRUD、獨立 db 檔案隔離。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_stock*"
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from us_stock_store import USStockStore  # noqa: E402


class SchemaTest(unittest.TestCase):
    """schema 建立：4 張表都存在，且沒有任何隱式種子資料寫入
    （2026-08-22 資產表事故教訓——__init__ 不得有寫入副作用）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_four_tables_created(self):
        rows = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r["name"] for r in rows}
        for expected in ("us_trades", "us_stances", "us_watch_conditions",
                          "us_price_snapshots"):
            self.assertIn(expected, table_names)

    def test_db_file_is_us_stocks_db_not_alphavibe_db(self):
        self.assertEqual(os.path.basename(self.store.db_path), "us_stocks.db")
        self.assertTrue(os.path.exists(self.store.db_path))

    def test_no_seed_data_on_fresh_store(self):
        """__init__ 不得掛任何有副作用的種子寫入邏輯——全新資料庫上所有
        表都應該是空的。"""
        self.assertEqual(self.store.list_trades(), [])
        self.assertEqual(self.store.list_stances(), [])
        self.assertEqual(self.store.list_watch_conditions(), [])
        self.assertEqual(self.store.list_price_snapshots("NET"), [])
        self.assertEqual(self.store.get_tracked_tickers(), [])


class TradeCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_save_and_list_trade(self):
        saved = self.store.save_trade(
            ticker="NET", trade_date="2026-08-05", action="buy",
            shares=10, price=298.40)
        self.assertEqual(saved["amount"], 2984.0)
        trades = self.store.list_trades("NET")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "buy")

    def test_amount_can_be_manually_overridden(self):
        saved = self.store.save_trade(
            ticker="NET", trade_date="2026-08-05", action="buy",
            shares=10, price=298.40, amount=3000.0)
        self.assertEqual(saved["amount"], 3000.0)

    def test_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_trade(
                ticker="NET", trade_date="2026-08-05", action="hold",
                shares=10, price=298.40)

    def test_non_positive_shares_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_trade(
                ticker="NET", trade_date="2026-08-05", action="buy",
                shares=0, price=298.40)

    def test_non_positive_price_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_trade(
                ticker="NET", trade_date="2026-08-05", action="buy",
                shares=10, price=-1)

    def test_list_trades_all_tickers(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=298.40)
        self.store.save_trade(ticker="CRWD", trade_date="2026-08-06",
                               action="sell", shares=5, price=350.0)
        self.assertEqual(len(self.store.list_trades()), 2)


class StanceCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_save_and_get_latest_stance(self):
        self.store.save_stance(
            ticker="NET", direction="bullish", summary="偏多．等回檔",
            full_note="# NET 研究筆記\n\n完整內容...")
        latest = self.store.get_latest_stance("NET")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["direction"], "bullish")
        self.assertEqual(latest["status"], "active")

    def test_full_note_required(self):
        with self.assertRaises(ValueError):
            self.store.save_stance(
                ticker="NET", direction="bullish", summary="偏多",
                full_note="   ")

    def test_invalid_direction_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_stance(
                ticker="NET", direction="sideways", summary="不確定",
                full_note="內容")

    def test_multiple_stances_kept_latest_active_wins(self):
        self.store.save_stance(ticker="NET", direction="bullish",
                                summary="第一次", full_note="筆記一")
        self.store.save_stance(ticker="NET", direction="bearish",
                                summary="第二次", full_note="筆記二")
        latest = self.store.get_latest_stance("NET")
        self.assertEqual(latest["summary"], "第二次")
        self.assertEqual(len(self.store.list_stances("NET")), 2)

    def test_closed_stance_excluded_by_default(self):
        self.store.save_stance(ticker="NET", direction="bullish",
                                summary="舊立場", full_note="筆記",
                                status="closed")
        self.assertIsNone(self.store.get_latest_stance("NET"))
        self.assertIsNotNone(
            self.store.get_latest_stance("NET", include_closed=True))


class WatchConditionCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_save_watch_condition_defaults(self):
        saved = self.store.save_watch_condition(
            ticker="NET", metric_type="price", comparator="lt", threshold=250)
        self.assertEqual(saved["status"], "insufficient_data")
        self.assertIsNone(saved["last_evaluated_at"])

    def test_invalid_comparator_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_watch_condition(
                ticker="NET", metric_type="price", comparator="eq",
                threshold=250)

    def test_list_watch_conditions_by_ticker(self):
        self.store.save_watch_condition(
            ticker="NET", metric_type="price", comparator="lt", threshold=250)
        self.store.save_watch_condition(
            ticker="CRWD", metric_type="price", comparator="gt", threshold=400)
        self.assertEqual(len(self.store.list_watch_conditions("NET")), 1)
        self.assertEqual(len(self.store.list_watch_conditions()), 2)


class PriceSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_save_and_list_price_snapshot(self):
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-06", close_price=286.96,
            source="fmp")
        snapshots = self.store.list_price_snapshots("NET")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["close_price"], 286.96)

    def test_same_day_upsert_does_not_duplicate(self):
        """(ticker, snapshot_date) 唯一——同一天重複寫入覆蓋，不疊加新列
        （data-model.md §4）。"""
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-06", close_price=286.96)
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-06", close_price=290.00)
        snapshots = self.store.list_price_snapshots("NET")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["close_price"], 290.00)

    def test_snapshots_ordered_oldest_first(self):
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-05", close_price=280.0)
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-06", close_price=286.96)
        snapshots = self.store.list_price_snapshots("NET")
        self.assertEqual([s["snapshot_date"] for s in snapshots],
                         ["2026-09-05", "2026-09-06"])


class TrackedTickersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_union_across_four_tables(self):
        """追蹤清單＝四張表任一張出現過的 ticker 聯集（FR-013），包含
        「純觀察中」只出現在 us_watch_conditions 的股票（尚無交易）。"""
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=298.40)
        self.store.save_stance(ticker="CRWD", direction="bullish",
                                summary="觀察中", full_note="筆記")
        self.store.save_watch_condition(
            ticker="SNOW", metric_type="price", comparator="lt", threshold=150)
        self.assertEqual(self.store.get_tracked_tickers(),
                         ["CRWD", "NET", "SNOW"])


class UpdateTradeTest(unittest.TestCase):
    """`update_trade()`（Phase 3 US1 T016/T017 支援方法）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_update_existing_trade(self):
        saved = self.store.save_trade(
            ticker="NET", trade_date="2026-08-05", action="buy",
            shares=10, price=298.40)
        updated = self.store.update_trade(
            saved["id"], ticker="NET", trade_date="2026-08-05",
            action="buy", shares=12, price=300.0)
        self.assertEqual(updated["shares"], 12)
        self.assertEqual(updated["price"], 300.0)
        self.assertEqual(updated["amount"], 3600.0)  # 重新計算

    def test_update_missing_trade_returns_none(self):
        result = self.store.update_trade(
            9999, ticker="NET", trade_date="2026-08-05", action="buy",
            shares=1, price=1)
        self.assertIsNone(result)

    def test_update_invalid_action_rejected(self):
        saved = self.store.save_trade(
            ticker="NET", trade_date="2026-08-05", action="buy",
            shares=10, price=298.40)
        with self.assertRaises(ValueError):
            self.store.update_trade(
                saved["id"], ticker="NET", trade_date="2026-08-05",
                action="hold", shares=10, price=298.40)

    def test_update_amount_manually_overridden(self):
        saved = self.store.save_trade(
            ticker="NET", trade_date="2026-08-05", action="buy",
            shares=10, price=298.40)
        updated = self.store.update_trade(
            saved["id"], ticker="NET", trade_date="2026-08-05",
            action="buy", shares=10, price=298.40, amount=3000.0)
        self.assertEqual(updated["amount"], 3000.0)


class ListRecentTradesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_recent_trades_newest_first(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=298.40)
        self.store.save_trade(ticker="CRWD", trade_date="2026-08-06",
                               action="buy", shares=5, price=350.0)
        recent = self.store.list_recent_trades(limit=10)
        self.assertEqual(recent[0]["ticker"], "CRWD")
        self.assertEqual(recent[1]["ticker"], "NET")

    def test_recent_trades_respects_limit(self):
        for i in range(5):
            self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                                   action="buy", shares=1, price=100 + i)
        self.assertEqual(len(self.store.list_recent_trades(limit=3)), 3)


class ComputeHoldingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_single_buy_holdings(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=300.0)
        holdings = self.store.compute_holdings("NET")
        self.assertEqual(holdings["shares_held"], 10)
        self.assertEqual(holdings["avg_cost"], 300.0)
        self.assertEqual(holdings["realized"], 0.0)

    def test_weighted_average_cost_across_two_buys(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=300.0)
        self.store.save_trade(ticker="NET", trade_date="2026-08-06",
                               action="buy", shares=10, price=320.0)
        holdings = self.store.compute_holdings("NET")
        self.assertEqual(holdings["shares_held"], 20)
        self.assertEqual(holdings["avg_cost"], 310.0)  # (10*300+10*320)/20

    def test_sell_reduces_shares_and_realizes_pnl(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=300.0)
        self.store.save_trade(ticker="NET", trade_date="2026-08-10",
                               action="sell", shares=4, price=350.0)
        holdings = self.store.compute_holdings("NET")
        self.assertEqual(holdings["shares_held"], 6)
        self.assertEqual(holdings["avg_cost"], 300.0)  # 均價不變
        self.assertEqual(holdings["realized"], 200.0)  # 4*(350-300)

    def test_full_exit_resets_avg_cost_to_none(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=300.0)
        self.store.save_trade(ticker="NET", trade_date="2026-08-10",
                               action="sell", shares=10, price=350.0)
        holdings = self.store.compute_holdings("NET")
        self.assertEqual(holdings["shares_held"], 0)
        self.assertIsNone(holdings["avg_cost"])
        self.assertEqual(holdings["realized"], 500.0)

    def test_ticker_with_no_trades_returns_zero_holdings(self):
        holdings = self.store.compute_holdings("NOPE")
        self.assertEqual(holdings["shares_held"], 0.0)
        self.assertIsNone(holdings["avg_cost"])

    def test_all_tickers_mode_returns_list(self):
        self.store.save_trade(ticker="NET", trade_date="2026-08-05",
                               action="buy", shares=10, price=300.0)
        self.store.save_trade(ticker="CRWD", trade_date="2026-08-06",
                               action="buy", shares=5, price=350.0)
        result = self.store.compute_holdings()
        tickers = {h["ticker"] for h in result["holdings"]}
        self.assertEqual(tickers, {"NET", "CRWD"})


class PriceHistoryWithGapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-stock-store-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_no_gap_on_consecutive_weekdays(self):
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-03", close_price=280.0)  # 週四
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-04", close_price=282.0)  # 週五
        result = self.store.price_history_with_gaps("NET")
        self.assertEqual(result["gap_dates"], [])
        self.assertEqual(len(result["history"]), 2)

    def test_weekend_between_snapshots_not_flagged_as_gap(self):
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-04", close_price=282.0)  # 週五
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-07", close_price=286.0)  # 下週一
        result = self.store.price_history_with_gaps("NET")
        self.assertEqual(result["gap_dates"], [])  # 中間只有週六日，非平日

    def test_missing_weekday_flagged_as_gap(self):
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-03", close_price=280.0)  # 週四
        self.store.save_price_snapshot(
            ticker="NET", snapshot_date="2026-09-08", close_price=290.0)  # 下週二
        result = self.store.price_history_with_gaps("NET")
        # 中間平日：週五(09-04)、週一(09-07) 兩天缺快照。
        self.assertEqual(result["gap_dates"], ["2026-09-04", "2026-09-07"])

    def test_ticker_with_no_snapshots_returns_empty_history(self):
        result = self.store.price_history_with_gaps("NOPE")
        self.assertEqual(result["history"], [])
        self.assertEqual(result["gap_dates"], [])


class IndependentDbIsolationTest(unittest.TestCase):
    """獨立 db 檔案隔離：不同 data_dir 的兩個 USStockStore 完全互不影響。"""

    def setUp(self):
        self.tmp_a = tempfile.mkdtemp(prefix="us-stock-store-test-a-")
        self.tmp_b = tempfile.mkdtemp(prefix="us-stock-store-test-b-")

    def tearDown(self):
        shutil.rmtree(self.tmp_a)
        shutil.rmtree(self.tmp_b)

    def test_two_data_dirs_are_isolated(self):
        store_a = USStockStore(self.tmp_a)
        store_b = USStockStore(self.tmp_b)
        try:
            store_a.save_trade(ticker="NET", trade_date="2026-08-05",
                                action="buy", shares=10, price=298.40)
            self.assertEqual(len(store_a.list_trades()), 1)
            self.assertEqual(len(store_b.list_trades()), 0)
            self.assertNotEqual(store_a.db_path, store_b.db_path)
        finally:
            store_a.close()
            store_b.close()


if __name__ == "__main__":
    unittest.main()
