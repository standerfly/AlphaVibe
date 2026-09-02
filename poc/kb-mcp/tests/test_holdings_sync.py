"""holdings_sync.py測試（2026-09-02，交易紀錄自動同步持股快照）。

比照 test_traceability.py::HoldingsTest 的 tempfile.mkdtemp()+KBStore
慣例。重點驗證：逐筆套用（不是批次淨額聚合，同批次「先買後賣」跟
「先賣後買」算出的均價不同）、shares<=0時新均價不瞎猜賣出均價不變、
賣超floor在0、未交易代碼原封不動搬過去、券商報告永遠優先於自動同步
（靠id AUTOINCREMENT，不需要額外欄位），以及2026-09-01那8筆交易的
回溯情境（跟正式資料庫現況比對）。
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import holdings_sync  # noqa: E402
from kb_store import KBStore  # noqa: E402


class HoldingsSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-holdings-sync-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    # ---------- 基本情境 ----------

    def test_new_code_added(self):
        """全新股票（baseline沒有）買進後應該出現在持股清單，均價=成交價。"""
        trades = [{"code": "1101", "name": "台泥", "action": "買",
                   "shares": 100, "price": 30.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertTrue(result["synced"])
        self.assertEqual(result["codes_new"], ["1101"])
        self.assertEqual(result["codes_cleared"], [])
        self.assertEqual(result["avg_cost_unknown_codes"], [])
        self.assertEqual(result["oversold_codes"], [])

        latest = self.store.get_holdings()
        self.assertEqual(latest["count"], 1)
        self.assertEqual(latest["holdings"][0]["code"], "1101")
        self.assertEqual(latest["holdings"][0]["shares"], 100)
        self.assertEqual(latest["holdings"][0]["avg_cost"], 30.0)

    def test_sell_all_clears_to_zero(self):
        """全部賣出：股數歸零、均價不變，且不再出現在get_holdings()。"""
        self.store.save_holdings(
            [{"code": "1216", "name": "統一", "shares": 100, "avg_cost": 50.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "1216", "name": "統一", "action": "賣",
                   "shares": 100, "price": 55.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(result["codes_cleared"], ["1216"])
        self.assertEqual(result["codes_new"], [])

        latest = self.store.get_holdings()
        self.assertEqual(latest["count"], 0)

        history = self.store.get_holdings("1216")
        self.assertEqual(history["history"][0]["shares"], 0)
        self.assertEqual(history["history"][0]["avg_cost"], 50.0)

    def test_partial_sell_avg_cost_unchanged(self):
        """部分賣出：股數減少，均價不變。"""
        self.store.save_holdings(
            [{"code": "1301", "name": "台塑", "shares": 1000, "avg_cost": 80.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "1301", "name": "台塑", "action": "賣",
                   "shares": 300, "price": 90.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(result["codes_cleared"], [])
        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["shares"], 700)
        self.assertEqual(row["avg_cost"], 80.0)

    def test_buy_more_weighted_average_known_cost(self):
        """加碼且舊均價已知：加權平均法算新均價。"""
        self.store.save_holdings(
            [{"code": "1303", "name": "南亞", "shares": 1000, "avg_cost": 60.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "1303", "name": "南亞", "action": "買",
                   "shares": 500, "price": 66.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(result["avg_cost_unknown_codes"], [])
        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["shares"], 1500)
        # (1000*60 + 500*66) / 1500 = 93000/1500 = 62.0
        self.assertAlmostEqual(row["avg_cost"], 62.0)

    def test_buy_more_avg_cost_unknown_stays_unknown(self):
        """加碼但舊均價本身缺值：新均價保持缺值，不瞎猜。"""
        self.store.save_holdings(
            [{"code": "1326", "name": "台化", "shares": 200, "avg_cost": None}],
            snapshot_date="2026-08-31")
        trades = [{"code": "1326", "name": "台化", "action": "買",
                   "shares": 100, "price": 70.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(result["avg_cost_unknown_codes"], ["1326"])
        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["shares"], 300)
        self.assertIsNone(row["avg_cost"])

    def test_interleaved_buy_sell_buy_sequential_not_aggregate(self):
        """同批次「買→賣→買」交錯：逐筆套用的均價跟「批次淨額聚合」算出
        來的不一樣，證明沒有偷懶用聚合算法。"""
        trades = [
            {"code": "1402", "name": "遠東新", "action": "買",
             "shares": 100, "price": 10.0, "date": "2026-09-01"},
            {"code": "1402", "name": "遠東新", "action": "賣",
             "shares": 40, "price": 12.0, "date": "2026-09-01"},
            {"code": "1402", "name": "遠東新", "action": "買",
             "shares": 50, "price": 20.0, "date": "2026-09-01"},
        ]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)
        self.assertEqual(result["codes_new"], ["1402"])

        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["shares"], 110)
        # step1: shares<=0 -> avg=10.0, shares=100
        # step2: 賣40 -> shares=60, avg不變=10.0
        # step3: shares>0且avg已知 -> avg=(60*10+50*20)/110=1600/110
        self.assertAlmostEqual(row["avg_cost"], 1600 / 110)
        # 對照組：若用「批次淨額聚合」（例如簡單把兩筆買進的股數與金額
        # 加總、忽略中間賣出對股數基準的影響）會算出不同的錯誤答案，
        # 用這個反例確認我們沒有走那條路。
        wrong_naive_avg = (100 * 10.0 + 50 * 20.0) / (100 + 50)  # = 13.333...
        self.assertNotAlmostEqual(row["avg_cost"], wrong_naive_avg)

    def test_same_batch_pure_buys_net_calculation(self):
        """同批次同代碼（純買進、無中間賣出）：逐筆套用結果等同淨額加權
        平均計算——用來跟上一個「買賣交錯」測試對照，證明差異只在於
        中間有沒有賣出動作，純買進序列本身就是淨額計算。"""
        trades = [
            {"code": "2002", "name": "中鋼", "action": "買",
             "shares": 60, "price": 100.0, "date": "2026-09-01"},
            {"code": "2002", "name": "中鋼", "action": "買",
             "shares": 40, "price": 110.0, "date": "2026-09-01"},
        ]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)
        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["shares"], 100)
        expected_net_avg = (60 * 100.0 + 40 * 110.0) / 100  # = 104.0
        self.assertAlmostEqual(row["avg_cost"], expected_net_avg)
        self.assertEqual(result["avg_cost_unknown_codes"], [])

    def test_untouched_code_carried_over_unchanged(self):
        """沒被這批交易碰到的既有持股，原封不動搬到新快照。"""
        self.store.save_holdings(
            [{"code": "1402", "name": "遠東新", "shares": 500, "avg_cost": 45.0},
             {"code": "1403", "name": "華夏", "shares": 200, "avg_cost": 15.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "1403", "name": "華夏", "action": "買",
                   "shares": 100, "price": 16.0, "date": "2026-09-01"}]
        holdings_sync.sync_holdings_from_trades(self.store, trades)

        latest = self.store.get_holdings()
        by_code = {h["code"]: h for h in latest["holdings"]}
        self.assertEqual(by_code["1402"]["shares"], 500)
        self.assertEqual(by_code["1402"]["avg_cost"], 45.0)
        self.assertEqual(by_code["1402"]["name"], "遠東新")

    def test_oversold_floors_at_zero_and_flagged(self):
        """賣超（賣出股數超過可賣股數）：股數floor在0，且回報oversold_codes。"""
        self.store.save_holdings(
            [{"code": "2027", "name": "大成鋼", "shares": 50, "avg_cost": 20.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "2027", "name": "大成鋼", "action": "賣",
                   "shares": 80, "price": 25.0, "date": "2026-09-01"}]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(result["oversold_codes"], ["2027"])
        self.assertEqual(result["codes_cleared"], ["2027"])
        latest = self.store.get_holdings()
        self.assertEqual(latest["count"], 0)
        history = self.store.get_holdings("2027")
        self.assertEqual(history["history"][0]["shares"], 0)
        self.assertEqual(history["history"][0]["avg_cost"], 20.0)

    def test_empty_batch_does_not_trigger_sync(self):
        """空批次：完全不觸發（不呼叫save_holdings，baseline原封不動）。"""
        self.store.save_holdings(
            [{"code": "1101", "name": "台泥", "shares": 100, "avg_cost": 30.0}],
            snapshot_date="2026-08-31")
        result = holdings_sync.sync_holdings_from_trades(self.store, [])

        self.assertEqual(result, {
            "synced": False, "codes_new": [], "codes_cleared": [],
            "avg_cost_unknown_codes": [], "oversold_codes": [],
            "save_result": None,
        })
        latest = self.store.get_holdings()
        self.assertEqual(latest["snapshot_date"], "2026-08-31")  # 沒有新快照

    def test_fresh_environment_builds_first_snapshot_purely_from_trades(self):
        """全新環境（完全沒有baseline）：純靠交易建出第一份持股快照。"""
        self.assertEqual(self.store.get_holdings()["count"], 0)
        trades = [
            {"code": "5880", "name": "合庫金", "action": "買",
             "shares": 1000, "price": 25.0, "date": "2026-09-01"},
            {"code": "2880", "name": "華南金", "action": "買",
             "shares": 2000, "price": 20.0, "date": "2026-09-01"},
        ]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)
        self.assertEqual(set(result["codes_new"]), {"5880", "2880"})

        latest = self.store.get_holdings()
        self.assertEqual(latest["count"], 2)
        by_code = {h["code"]: h for h in latest["holdings"]}
        self.assertEqual(by_code["5880"]["shares"], 1000)
        self.assertEqual(by_code["5880"]["avg_cost"], 25.0)
        self.assertEqual(by_code["2880"]["shares"], 2000)
        self.assertEqual(by_code["2880"]["avg_cost"], 20.0)

    # ---------- 券商報告互動 ----------

    def test_scenario_a_sync_then_broker_report_same_day_report_wins(self):
        """情境A：自動同步先寫，同一天稍後上傳券商持股報告——報告勝出
        （靠id AUTOINCREMENT嚴格遞增，不需要額外的「來源優先權」欄位）。"""
        self.store.save_holdings(
            [{"code": "2317", "name": "鴻海", "shares": 1000, "avg_cost": 100.0}],
            snapshot_date="2026-08-31")
        trades = [{"code": "2317", "name": "鴻海", "action": "買",
                   "shares": 100, "price": 120.0, "date": "2026-09-01"}]
        holdings_sync.sync_holdings_from_trades(
            self.store, trades, snapshot_date="2026-09-02")

        # 同步後理應是 shares=1100，但券商報告接著上傳，帶完全不同的數字。
        self.store.save_holdings(
            [{"code": "2317", "name": "鴻海", "shares": 2000, "avg_cost": 95.0}],
            snapshot_date="2026-09-02", source_ref="券商持股報告")

        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["code"], "2317")
        self.assertEqual(row["shares"], 2000)
        self.assertEqual(row["avg_cost"], 95.0)
        self.assertEqual(row["source_ref"], "券商持股報告")

    def test_scenario_b_broker_report_then_sync_same_day_sync_stacks_on_report(self):
        """情境B：券商報告先寫，自動同步在同一天之後才寫——同步應該正確
        疊加在報告基礎上，不是被蓋掉（同步讀到的baseline就是剛上傳的
        報告，不是舊的/空的資料）。"""
        self.store.save_holdings(
            [{"code": "2454", "name": "聯發科", "shares": 300, "avg_cost": 800.0}],
            snapshot_date="2026-09-02", source_ref="券商持股報告")

        trades = [{"code": "2454", "name": "聯發科", "action": "買",
                   "shares": 20, "price": 900.0, "date": "2026-09-02"}]
        holdings_sync.sync_holdings_from_trades(
            self.store, trades, snapshot_date="2026-09-02")

        latest = self.store.get_holdings()
        row = latest["holdings"][0]
        self.assertEqual(row["code"], "2454")
        self.assertEqual(row["shares"], 320)
        # (300*800 + 20*900) / 320 = 258000/320 = 806.25
        self.assertAlmostEqual(row["avg_cost"], 806.25)


class BackfillScenarioTest(unittest.TestCase):
    """回溯情境測試：seed一份跟正式資料庫現況一樣的21檔baseline（shares
    照方案『回溯今天已匯入的8筆交易』表格描述、avg_cost全None），寫入
    方案裡列的那8筆交易，斷言結果精確等於方案表格。

    已知落差（誠實記錄，供人工核對真正回溯時參照）：方案原文敘述
    「其餘13檔原封不動搬到新快照」，但方案自己核對過的事實是baseline
    共21檔、且8筆交易裡有6筆（松川精密/智邦/百和/鈺邦/群聯/新盛力）對應
    baseline裡『既有』的代碼——21-6=15，不是13。19檔的最終結果、4檔
    出清、2檔新增、群聯14股/新盛力150股這些數字彼此互相印證、跟21這個
    數字一致；「13」看起來是方案敘述時的算術誤差，這裡採用算術上唯一
    自洽的15檔做測試，而不是照抄有誤的13。實際跑
    backfill_holdings_sync_once.py時仍要以正式資料庫的真實查詢結果為準。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-holdings-backfill-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_backfill_2026_09_01_eight_trades_matches_plan_table(self):
        # 6檔「這批交易會碰到」的既有持股（avg_cost全None，比照正式庫現況）。
        touched_existing = [
            {"code": "7788", "name": "松川精密", "shares": 50, "avg_cost": None},
            {"code": "2345", "name": "智邦", "shares": 5, "avg_cost": None},
            {"code": "9938", "name": "百和", "shares": 400, "avg_cost": None},
            {"code": "6449", "name": "鈺邦", "shares": 15, "avg_cost": None},
            {"code": "8299", "name": "群聯", "shares": 9, "avg_cost": None},
            {"code": "4931", "name": "新盛力", "shares": 100, "avg_cost": None},
        ]
        # 15檔「這批交易不會碰到」的既有持股，湊足baseline共21檔
        # （見class docstring：21-6=15，不是方案原文寫的13）。
        untouched = [
            {"code": "1101", "name": "台泥", "shares": 1000, "avg_cost": None},
            {"code": "1216", "name": "統一", "shares": 2000, "avg_cost": None},
            {"code": "1301", "name": "台塑", "shares": 500, "avg_cost": None},
            {"code": "1303", "name": "南亞", "shares": 800, "avg_cost": None},
            {"code": "2002", "name": "中鋼", "shares": 3000, "avg_cost": None},
            {"code": "2027", "name": "大成鋼", "shares": 100, "avg_cost": None},
            {"code": "2317", "name": "鴻海", "shares": 200, "avg_cost": None},
            {"code": "2454", "name": "聯發科", "shares": 50, "avg_cost": None},
            {"code": "2603", "name": "長榮", "shares": 400, "avg_cost": None},
            {"code": "2880", "name": "華南金", "shares": 1500, "avg_cost": None},
            {"code": "3008", "name": "大立光", "shares": 10, "avg_cost": None},
            {"code": "5880", "name": "合庫金", "shares": 2500, "avg_cost": None},
            {"code": "6505", "name": "台塑化", "shares": 300, "avg_cost": None},
            {"code": "2308", "name": "台達電", "shares": 150, "avg_cost": None},
            {"code": "2330", "name": "台積電", "shares": 25, "avg_cost": None},
        ]
        baseline_rows = touched_existing + untouched
        self.assertEqual(len(baseline_rows), 21)
        self.store.save_holdings(baseline_rows, snapshot_date="2026-08-31")

        trades = [
            {"code": "3037", "name": "欣興", "action": "買",
             "shares": 10, "price": 954.0, "date": "2026-09-01"},
            {"code": "3526", "name": "凡甲", "action": "買",
             "shares": 50, "price": 287.5, "date": "2026-09-01"},
            {"code": "7788", "name": "松川精密", "action": "賣",
             "shares": 50, "price": 100.0, "date": "2026-09-01"},
            {"code": "2345", "name": "智邦", "action": "賣",
             "shares": 5, "price": 100.0, "date": "2026-09-01"},
            {"code": "9938", "name": "百和", "action": "賣",
             "shares": 400, "price": 50.0, "date": "2026-09-01"},
            {"code": "6449", "name": "鈺邦", "action": "賣",
             "shares": 15, "price": 30.0, "date": "2026-09-01"},
            {"code": "8299", "name": "群聯", "action": "買",
             "shares": 5, "price": 600.0, "date": "2026-09-01"},
            {"code": "4931", "name": "新盛力", "action": "買",
             "shares": 50, "price": 45.0, "date": "2026-09-01"},
        ]
        result = holdings_sync.sync_holdings_from_trades(self.store, trades)

        self.assertEqual(set(result["codes_new"]), {"3037", "3526"})
        self.assertEqual(set(result["codes_cleared"]),
                          {"7788", "2345", "9938", "6449"})
        self.assertEqual(set(result["avg_cost_unknown_codes"]),
                          {"8299", "4931"})
        self.assertEqual(result["oversold_codes"], [])

        latest = self.store.get_holdings()
        self.assertEqual(latest["count"], 19)  # 21+2-4=19，跟方案表格一致
        by_code = {h["code"]: h for h in latest["holdings"]}

        expected_cleared = {"7788", "2345", "9938", "6449"}
        for code in expected_cleared:
            self.assertNotIn(code, by_code)

        self.assertEqual(by_code["3037"]["shares"], 10)
        self.assertEqual(by_code["3037"]["avg_cost"], 954.0)
        self.assertEqual(by_code["3526"]["shares"], 50)
        self.assertEqual(by_code["3526"]["avg_cost"], 287.5)
        self.assertEqual(by_code["8299"]["shares"], 14)  # 9+5
        self.assertIsNone(by_code["8299"]["avg_cost"])
        self.assertEqual(by_code["4931"]["shares"], 150)  # 100+50
        self.assertIsNone(by_code["4931"]["avg_cost"])

        for row in untouched:
            self.assertIn(row["code"], by_code, "未交易代碼不該消失：%r" % row)
            self.assertEqual(by_code[row["code"]]["shares"], row["shares"])
            self.assertIsNone(by_code[row["code"]]["avg_cost"])


if __name__ == "__main__":
    unittest.main()
