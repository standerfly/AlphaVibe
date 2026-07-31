"""trade_ledger_parser 測試（FR-056 PO自己的交易明細表批次文字解析＋
add_sequence 計算＋批次寫入 trade_ledger）。

SAMPLE_TEXT 是 PO 實際會貼的完整真實範例（不是自編假資料），逐條驗證
parser 對每一行都解析正確；add_sequence 正確性是本檔測試重點，尤其
「資料庫裡已有歷史買進記錄」時要接續編號、以及同一天多筆買進的排序
tie-break（用原始出現順序，穩定排序，不判斷真實下單時間）。
"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import server  # noqa: E402
import trade_ledger_parser  # noqa: E402
from kb_store import KBStore  # noqa: E402

# PO 實際貼的完整交易明細表文字（2026-07-30 提供）。15筆交易：
# 中美晶2筆賣出、旺宏1賣1買、台達電5筆買進、家碩4筆買進、家登1筆買進、
# 世芯-KY1筆買進。
SAMPLE_TEXT = """\
交易日期: 115/07/22 - 115/07/29 頁次: 1
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
交易日期 CD 股票名稱 股數 單價 手續費 交易稅 證所稅 融券手續費 利息 預收/留置款 價 金 淨收付金額 委託書號
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
115/07/22 OT賣 中美晶 50 242.50 4 36 12,125 12,085(付) k-0116-00
115/07/22 集買 台達電 10 1,905.00 7 19,050 19,057(收) k-01NM-00
115/07/22 集賣 旺宏 50 135.00 2 20 6,750 6,728(付) k-02Jc-00
115/07/22 OT買 家碩 100 221.00 8 22,100 22,108(收) k-02n6-00
115/07/23 集買 台達電 10 1,900.00 7 19,000 19,007(收) k-00iE-00
115/07/23 OT賣 中美晶 50 244.00 4 36 12,200 12,160(付) k-01ut-00
115/07/23 集買 旺宏 100 128.00 5 12,800 12,805(收) k-03k1-00
115/07/23 OT買 家碩 50 231.00 4 11,550 11,554(收) k-03Xs-00
115/07/23 OT買 家碩 50 224.00 4 11,200 11,204(收) k-07g9-00
115/07/24 集買 台達電 5 1,870.00 3 9,350 9,353(收) k-01bY-00
115/07/24 OT買 家碩 25 218.50 2 5,462 5,464(收) k-07ED-00
115/07/27 集買 台達電 5 1,760.00 3 8,800 8,803(收) k-01eX-00
115/07/28 OT買 家登 20 423.50 3 8,470 8,473(收) k-0839-00
115/07/28 集買 台達電 5 1,580.00 3 7,900 7,903(收) k-0DM8-00
115/07/29 集買 世芯-KY 5 2,805.00 5 14,025 14,030(收) k-0BrU-00
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
合 計: 64 92 180,782 118,788(收)
"""

TOTAL_COUNT = 15

# 名稱→代碼比對表（測試用預先建立的 stock_aliases，避免打真的 FinMind API）。
ALIAS_MAP = {
    "中美晶": "5483", "台達電": "2308", "旺宏": "2337",
    "家碩": "6953", "家登": "3680", "世芯-KY": "3661",
}


class ParseFullSampleTest(unittest.TestCase):
    """完整範例文字的整體解析正確性（純函式，不碰資料庫）。"""

    def setUp(self):
        self.out = trade_ledger_parser.parse_trade_ledger_text(SAMPLE_TEXT)

    def test_total_trade_count(self):
        self.assertEqual(self.out["total_parsed"], TOTAL_COUNT)
        self.assertEqual(len(self.out["trades"]), TOTAL_COUNT)

    def test_no_unparsed_lines(self):
        """表頭列／分隔線／頁首列／合計列都要被正確跳過，不進unparsed_lines。"""
        self.assertEqual(self.out["unparsed_lines"], [])

    def test_all_15_trades_fields_correct(self):
        """逐筆核對日期(民國轉西元)/買賣別/名稱/股數/價格，不只驗證前幾筆。"""
        expected = [
            ("2026-07-22", "賣", "中美晶", 50, 242.50),
            ("2026-07-22", "買", "台達電", 10, 1905.00),
            ("2026-07-22", "賣", "旺宏", 50, 135.00),
            ("2026-07-22", "買", "家碩", 100, 221.00),
            ("2026-07-23", "買", "台達電", 10, 1900.00),
            ("2026-07-23", "賣", "中美晶", 50, 244.00),
            ("2026-07-23", "買", "旺宏", 100, 128.00),
            ("2026-07-23", "買", "家碩", 50, 231.00),
            ("2026-07-23", "買", "家碩", 50, 224.00),
            ("2026-07-24", "買", "台達電", 5, 1870.00),
            ("2026-07-24", "買", "家碩", 25, 218.50),
            ("2026-07-27", "買", "台達電", 5, 1760.00),
            ("2026-07-28", "買", "家登", 20, 423.50),
            ("2026-07-28", "買", "台達電", 5, 1580.00),
            ("2026-07-29", "買", "世芯-KY", 5, 2805.00),
        ]
        self.assertEqual(len(self.out["trades"]), len(expected))
        for trade, (date, action, name, shares, price) in zip(self.out["trades"], expected):
            self.assertEqual(trade["date"], date, trade)
            self.assertEqual(trade["action"], action, trade)
            self.assertEqual(trade["name"], name, trade)
            self.assertEqual(trade["shares"], shares, trade)
            self.assertEqual(trade["price"], price, trade)

    def test_roc_date_converted_to_western(self):
        self.assertEqual(self.out["trades"][0]["date"], "2026-07-22")
        self.assertEqual(self.out["trades"][-1]["date"], "2026-07-29")

    def test_raw_line_preserved(self):
        first = self.out["trades"][0]
        self.assertIn("中美晶", first["raw_line"])
        self.assertIn("115/07/22", first["raw_line"])


class ParseSkipLinesTest(unittest.TestCase):
    def test_header_summary_line_skipped(self):
        text = "交易日期: 115/07/22 - 115/07/29 頁次: 1\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_separator_line_skipped(self):
        text = "-" * 40 + "\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_header_row_skipped(self):
        text = "交易日期 CD 股票名稱 股數 單價 手續費 交易稅 委託書號\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_total_line_skipped(self):
        text = "合 計: 64 92 180,782 118,788(收)\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_empty_text_returns_empty_result(self):
        out = trade_ledger_parser.parse_trade_ledger_text("")
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["total_parsed"], 0)

    def test_malformed_data_line_goes_to_unparsed(self):
        """開頭像資料列（民國年日期）但股數欄位格式跑掉的行，歸入
        unparsed_lines，不靜默丟棄、也不誤解析成錯的欄位。"""
        text = "115/07/22 OT賣 中美晶 五十 242.50 4 36 12,125 12,085(付) k-0116-00\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(len(out["unparsed_lines"]), 1)
        self.assertIn("中美晶", out["unparsed_lines"][0])


class ResolveAndSaveAddSequenceTest(unittest.TestCase):
    """add_sequence 計算正確性——本檔測試重點。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-ledger-test-")
        self.store = KBStore(self.tmp)
        for name, code in ALIAS_MAP.items():
            self.store.save_stock_alias(name, code, source="測試預先建立")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _run(self):
        parsed = trade_ledger_parser.parse_trade_ledger_text(SAMPLE_TEXT)
        return trade_ledger_parser.resolve_and_save_trade_ledger(
            parsed, self.store, data_dir=self.tmp)

    def test_all_15_saved_none_unresolved_or_unparsed(self):
        out = self._run()
        self.assertEqual(out["total_parsed"], TOTAL_COUNT)
        self.assertEqual(len(out["saved"]), TOTAL_COUNT)
        self.assertEqual(out["unresolved_names"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_delta_5_buys_get_sequence_1_to_5_when_no_prior_history(self):
        """台達電這批5筆買進（07/22,07/23,07/24,07/27,07/28各一筆），資料庫
        裡台達電之前沒有任何trade_ledger記錄，依日期順序應拿到1~5。"""
        out = self._run()
        delta_buys = [s for s in out["saved"] if s["code"] == "2308"]
        self.assertEqual(len(delta_buys), 5)
        dates_in_order = [s["date"] for s in delta_buys]
        self.assertEqual(dates_in_order,
                         ["2026-07-22", "2026-07-23", "2026-07-24",
                          "2026-07-27", "2026-07-28"])
        self.assertEqual([s["add_sequence"] for s in delta_buys], [1, 2, 3, 4, 5])
        for s in delta_buys:
            self.assertEqual(s["action"], "買")

    def test_delta_continues_from_existing_history_instead_of_restarting_at_1(self):
        """資料庫裡台達電之前已經有2筆買進記錄，這批新資料應接著拿到
        3,4,5,6,7，不是重新從1開始。"""
        self.store.save_trade_ledger_entry(
            "2308", "台達電", "買", 1000, 500.0, "2026-06-01", add_sequence=1)
        self.store.save_trade_ledger_entry(
            "2308", "台達電", "買", 1000, 550.0, "2026-06-15", add_sequence=2)

        out = self._run()
        delta_buys = [s for s in out["saved"] if s["code"] == "2308"]
        self.assertEqual(len(delta_buys), 5)
        self.assertEqual([s["add_sequence"] for s in delta_buys], [3, 4, 5, 6, 7])

        # 資料庫裡的完整流水也要能佐證：舊2筆＋新5筆＝7筆買進，序號連續。
        ledger = self.store.get_trade_ledger("2308")
        buy_entries = [e for e in ledger["entries"] if e["action"] == "買"]
        self.assertEqual(len(buy_entries), 7)
        self.assertEqual([e["add_sequence"] for e in buy_entries], [1, 2, 3, 4, 5, 6, 7])

    def test_jiashuo_4_buys_same_day_tiebreak_by_original_order(self):
        """家碩這批有4筆買進（07/22,07/23×2,07/24），07/23那兩筆同一天出現
        兩次——tie-break用原始出現順序（穩定排序），先出現的231.00那筆該
        拿到比後出現的224.00那筆小的序號。"""
        out = self._run()
        jiashuo_buys = [s for s in out["saved"] if s["code"] == "6953"]
        self.assertEqual(len(jiashuo_buys), 4)
        self.assertEqual([s["add_sequence"] for s in jiashuo_buys], [1, 2, 3, 4])
        # 依原始文字出現順序：100@221.00(07/22) → 50@231.00(07/23，先出現)
        # → 50@224.00(07/23，後出現) → 25@218.50(07/24)
        self.assertEqual([s["price"] for s in jiashuo_buys], [221.00, 231.00, 224.00, 218.50])
        same_day = [s for s in jiashuo_buys if s["date"] == "2026-07-23"]
        self.assertEqual(same_day[0]["price"], 231.00)
        self.assertEqual(same_day[0]["add_sequence"], 2)
        self.assertEqual(same_day[1]["price"], 224.00)
        self.assertEqual(same_day[1]["add_sequence"], 3)

    def test_zhongmeijing_2_sells_add_sequence_none(self):
        """中美晶2筆都是賣出，add_sequence都應該是None。"""
        out = self._run()
        sells = [s for s in out["saved"] if s["code"] == "5483"]
        self.assertEqual(len(sells), 2)
        for s in sells:
            self.assertEqual(s["action"], "賣")
            self.assertIsNone(s["add_sequence"])

    def test_shixin_ky_1_buy_sequence_1(self):
        """世芯-KY只有1筆買進，序號應該是1（之前無記錄）。"""
        out = self._run()
        shixin = [s for s in out["saved"] if s["code"] == "3661"]
        self.assertEqual(len(shixin), 1)
        self.assertEqual(shixin[0]["add_sequence"], 1)

    def test_wanghong_sell_none_buy_sequence_1(self):
        """旺宏1賣1買：賣出None，買進（之前無記錄）該是1。"""
        out = self._run()
        wanghong = [s for s in out["saved"] if s["code"] == "2337"]
        self.assertEqual(len(wanghong), 2)
        by_action = {s["action"]: s for s in wanghong}
        self.assertIsNone(by_action["賣"]["add_sequence"])
        self.assertEqual(by_action["買"]["add_sequence"], 1)

    def test_persisted_to_db_matches_returned_saved_list(self):
        """回傳的saved清單要跟實際寫入資料庫的內容一致（不只回傳正確，
        真的有寫進去）。"""
        out = self._run()
        for s in out["saved"]:
            ledger = self.store.get_trade_ledger(s["code"])
            match = [e for e in ledger["entries"]
                    if e["date"] == s["date"] and e["price"] == s["price"]
                    and e["shares"] == s["shares"] and e["action"] == s["action"]]
            self.assertEqual(len(match), 1, "找不到對應的DB紀錄：%r" % s)
            self.assertEqual(match[0]["add_sequence"], s["add_sequence"])


class ResolveAndSaveNameResolutionTest(unittest.TestCase):
    """名稱→代碼解析（共用 stock_alias_resolver.py）在這個模組裡的整合行為。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-ledger-name-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_cache_hit_does_not_call_finmind(self):
        self.store.save_stock_alias("家登", "3680", source="測試")
        text = "115/07/28 OT買 家登 20 423.50 3 8,470 8,473(收) k-0839-00\n"
        parsed = trade_ledger_parser.parse_trade_ledger_text(text)
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info") as mock_fm:
            out = trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, self.store, data_dir=self.tmp)
            mock_fm.assert_not_called()
        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["code"], "3680")

    def test_finmind_fallback_with_hyphen_normalization_caches_alias(self):
        """驗證與trade_text_parser.py共用同一套FinMind整批比對＋正規化邏輯
        （不是各自重寫一份）：快取沒有「世芯-KY」，FinMind清單裡也是
        「世芯-KY」，直接比對應成功並存回快取。"""
        text = "115/07/29 集買 世芯-KY 5 2,805.00 5 14,025 14,030(收) k-0BrU-00\n"
        parsed = trade_ledger_parser.parse_trade_ledger_text(text)
        fake_info = {"stocks": [{"stock_id": "3661", "stock_name": "世芯-KY"}]}
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info", return_value=fake_info) as mock_fm:
            out = trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, self.store, data_dir=self.tmp)
            mock_fm.assert_called_once_with(data_dir=self.tmp, token=None)
        self.assertEqual(out["saved"][0]["code"], "3661")
        alias = self.store.get_stock_alias("世芯-KY")
        self.assertTrue(alias["found"])
        self.assertEqual(alias["record"]["source"], "交易明細表批次解析自動比對")

    def test_both_cache_and_finmind_miss_goes_to_unresolved_and_not_saved(self):
        text = "115/07/22 OT買 查無此股 100 10.00 1 1,000 1,001(收) k-0000-00\n"
        parsed = trade_ledger_parser.parse_trade_ledger_text(text)
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info", return_value={"stocks": []}):
            out = trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, self.store, data_dir=self.tmp)
        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)
        self.assertEqual(out["unresolved_names"][0]["name"], "查無此股")
        self.assertIn("查無此股", out["unresolved_names"][0]["raw_line"])
        self.assertEqual(self.store.get_trade_ledger("不存在的代碼")["count"], 0)

    def test_unparsed_lines_passed_through(self):
        parsed = {"trades": [], "unparsed_lines": ["壞掉的一行"]}
        out = trade_ledger_parser.resolve_and_save_trade_ledger(
            parsed, self.store, data_dir=self.tmp)
        self.assertEqual(out["unparsed_lines"], ["壞掉的一行"])
        self.assertEqual(out["total_parsed"], 0)

    def test_accepts_bare_trade_list_as_fallback_interface(self):
        self.store.save_stock_alias("家登", "3680", source="測試")
        bare_trades = [
            {"date": "2026-07-28", "action": "買", "name": "家登",
             "shares": 20, "price": 423.5, "raw_line": "x"},
        ]
        out = trade_ledger_parser.resolve_and_save_trade_ledger(
            bare_trades, self.store, data_dir=self.tmp)
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["add_sequence"], 1)


class McpToolDispatchTest(unittest.TestCase):
    """server.py 的 parse_and_save_trade_ledger 工具串接測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-ledger-mcp-test-")
        self.srv = server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        shutil.rmtree(self.tmp)

    def test_tool_registered_in_tools_list(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertIn("parse_and_save_trade_ledger", names)

    def test_dispatch_parses_and_saves_with_add_sequence(self):
        self.srv.store.save_stock_alias("家登", "3680", source="測試")
        text = "115/07/28 OT買 家登 20 423.50 3 8,470 8,473(收) k-0839-00\n"
        out = self.srv.call_tool("parse_and_save_trade_ledger", {"text": text})
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["code"], "3680")
        self.assertEqual(out["saved"][0]["add_sequence"], 1)
        self.assertEqual(out["saved"][0]["date"], "2026-07-28")
        ledger = self.srv.store.get_trade_ledger("3680")
        self.assertEqual(ledger["count"], 1)

    def test_dispatch_unresolved_name_not_saved(self):
        text = "115/07/22 OT買 查無此股 100 10.00 1 1,000 1,001(收) k-0000-00\n"
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info", return_value={"stocks": []}):
            out = self.srv.call_tool("parse_and_save_trade_ledger", {"text": text})
        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)
        self.assertEqual(out["unresolved_names"][0]["name"], "查無此股")


if __name__ == "__main__":
    unittest.main()
