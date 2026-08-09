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

    def test_all_15_order_refs_extracted(self):
        """委託書號（order_ref，2026-07-31新增）：這一列最後一個非空白
        token，逐筆核對PO真實範例裡的15個委託書號。"""
        expected_order_refs = [
            "k-0116-00", "k-01NM-00", "k-02Jc-00", "k-02n6-00", "k-00iE-00",
            "k-01ut-00", "k-03k1-00", "k-03Xs-00", "k-07g9-00", "k-01bY-00",
            "k-07ED-00", "k-01eX-00", "k-0839-00", "k-0DM8-00", "k-0BrU-00",
        ]
        self.assertEqual(len(self.out["trades"]), len(expected_order_refs))
        for trade, expected in zip(self.out["trades"], expected_order_refs):
            self.assertEqual(trade["order_ref"], expected, trade)


class ParseOrderRefEdgeCasesTest(unittest.TestCase):
    """委託書號抽取相關的邊界情況。注意：_DATA_LINE_RE 在price群組後要求
    至少一個空白（`\\s+`）才能匹配成功，而每一行進解析前已先strip()——
    因此「price之後完全沒有任何內容」的列根本無法匹配成功（會落入
    _LOOKS_LIKE_DATA_RE分支歸入unparsed_lines，不會進到order_ref抽取
    邏輯），故不對該情境斷言trades結果，改為驗證真正會發生的情況。"""

    def test_single_trailing_token_extracted_as_order_ref(self):
        """price之後只有一個token（沒有其餘手續費/交易稅等中間欄位）：
        該token本身就是order_ref。"""
        text = "115/07/22 OT賣 中美晶 50 242.50 k-0116-00\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(len(out["trades"]), 1)
        self.assertEqual(out["trades"][0]["order_ref"], "k-0116-00")
        self.assertEqual(out["trades"][0]["price"], 242.50)

    def test_multiple_trailing_tokens_takes_last_one_as_order_ref(self):
        text = "115/07/22 OT賣 中美晶 50 242.50 4 36 12,125 12,085(付) k-0116-00\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"][0]["order_ref"], "k-0116-00")

    def test_price_with_no_matching_trailing_whitespace_falls_to_unparsed(self):
        """驗證上方docstring所述的正則邊界：price後沒有空白可匹配時，
        該列不會被解析成trade（進unparsed_lines），不會產生price被誤判
        成order_ref的錯誤結果。"""
        text = "115/07/22 OT賣 中美晶 50 242.50\n"
        out = trade_ledger_parser.parse_trade_ledger_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(len(out["unparsed_lines"]), 1)


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

    def test_mixed_batch_partial_duplicates_add_sequence_not_disturbed_by_skipped_count(self):
        """混合情境：先貼台達電前2筆（07/22,07/23，拿到add_sequence 1,2），
        再貼完整15筆——台達電前2筆的委託書號（k-01NM-00/k-00iE-00）已存在
        資料庫，該2筆被判定重複整筆跳過（不寫入、不佔用序號）；其餘3筆
        台達電新資料應該正確接續拿到3,4,5，不是被跳過的2筆干擾成錯誤的
        4,5,6或其他結果（驗證『不算進add_sequence計算基礎』）。其餘代碼
        （第二批裡是它們首次出現，如家碩4筆）維持正常序號1起跳，不受
        台達電那組重複影響。"""
        first_batch_text = (
            "115/07/22 集買 台達電 10 1,905.00 7 19,050 19,057(收) k-01NM-00\n"
            "115/07/23 集買 台達電 10 1,900.00 7 19,000 19,007(收) k-00iE-00\n"
        )
        parsed_first = trade_ledger_parser.parse_trade_ledger_text(first_batch_text)
        first_out = trade_ledger_parser.resolve_and_save_trade_ledger(
            parsed_first, self.store, data_dir=self.tmp)
        self.assertEqual(len(first_out["saved"]), 2)
        self.assertEqual([s["add_sequence"] for s in first_out["saved"]], [1, 2])
        self.assertEqual(first_out["duplicates_skipped"], [])

        second_out = self._run()  # 完整15筆（含台達電前2筆的重複委託書號）

        delta_saved = [s for s in second_out["saved"] if s["code"] == "2308"]
        self.assertEqual(len(delta_saved), 3)  # 5筆中2筆重複被跳過，只剩3筆真的寫入
        self.assertEqual([s["add_sequence"] for s in delta_saved], [3, 4, 5])
        self.assertEqual([s["date"] for s in delta_saved],
                         ["2026-07-24", "2026-07-27", "2026-07-28"])

        delta_dupes = [d for d in second_out["duplicates_skipped"] if d["code"] == "2308"]
        self.assertEqual(len(delta_dupes), 2)
        self.assertEqual({d["order_ref"] for d in delta_dupes},
                         {"k-01NM-00", "k-00iE-00"})

        # 其餘代碼在第二批仍是首次出現，序號應維持正常從1起跳。
        jiashuo_saved = [s for s in second_out["saved"] if s["code"] == "6953"]
        self.assertEqual([s["add_sequence"] for s in jiashuo_saved], [1, 2, 3, 4])

        # DB裡台達電總買進筆數＝2(第一批)+3(第二批新寫入)=5，序號連續1~5，
        # 沒有因為重複跳過而產生序號缺口或重複序號。
        ledger = self.store.get_trade_ledger("2308")
        buy_entries = [e for e in ledger["entries"] if e["action"] == "買"]
        self.assertEqual(len(buy_entries), 5)
        self.assertEqual([e["add_sequence"] for e in buy_entries], [1, 2, 3, 4, 5])

    def test_trades_with_none_order_ref_never_treated_as_duplicates_of_each_other(self):
        """order_ref缺失（None，例如來源格式抽取失敗）的交易之間，即使
        其餘欄位完全相同，也不做防重複比對——這是刻意保守的選擇（無法
        判斷=不擋，見resolve_and_save_trade_ledger()docstring），避免用
        None互相誤判為重複而漏存合法交易。"""
        bare_trades = [
            {"date": "2026-07-28", "action": "買", "name": "家登",
             "shares": 20, "price": 423.5, "raw_line": "x", "order_ref": None},
            {"date": "2026-07-28", "action": "買", "name": "家登",
             "shares": 20, "price": 423.5, "raw_line": "y", "order_ref": None},
        ]
        out = trade_ledger_parser.resolve_and_save_trade_ledger(
            bare_trades, self.store, data_dir=self.tmp)
        self.assertEqual(len(out["saved"]), 2)
        self.assertEqual(out["duplicates_skipped"], [])
        self.assertEqual([s["add_sequence"] for s in out["saved"]], [1, 2])


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

    def test_dispatch_second_paste_reports_duplicates_skipped(self):
        """server.py的call_tool直接回傳resolve_and_save_trade_ledger()的
        完整dict，本來就會自然涵蓋新增的duplicates_skipped欄位（不需要
        額外改動server.py）——這裡端對端驗證這個假設成立。"""
        self.srv.store.save_stock_alias("家登", "3680", source="測試")
        text = "115/07/28 OT買 家登 20 423.50 3 8,470 8,473(收) k-0839-00\n"
        first = self.srv.call_tool("parse_and_save_trade_ledger", {"text": text})
        self.assertEqual(len(first["saved"]), 1)
        self.assertEqual(first["duplicates_skipped"], [])

        second = self.srv.call_tool("parse_and_save_trade_ledger", {"text": text})
        self.assertEqual(second["saved"], [])
        self.assertEqual(len(second["duplicates_skipped"]), 1)
        self.assertEqual(second["duplicates_skipped"][0]["order_ref"], "k-0839-00")
        self.assertEqual(second["duplicates_skipped"][0]["code"], "3680")


# PO 實際貼的完整「已成交」CSV對帳單文字（2026-07-30 提供，PO已手動驗算
# 過每一列的數學關係：成交股數×成交價≈成本；買進淨收付金額≈-(成本+手續費)；
# 賣出淨收付金額≈成本-手續費-交易稅）。第一行是變動的提示文字（筆數會變，
# 內容不寫死比對）；第二行是標準CSV表頭；之後每行是真正的CSV（含千分位
# 逗號的欄位用雙引號包住）。
CSV_SAMPLE_TEXT = (
    "根據您篩選的結果，總計有4筆資料，當前資料為1-4筆，看更多請至國泰證券app查詢\n"
    "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
    "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
    '弘塑,2026/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
    '矽格,2026/07/30,50,"8,622",現賣,173,"8,650",3,25,0,0,0,0,0,k09j3\n'
    '矽科宏晟,2026/07/30,40,"9,569",現賣,240,"9,600",3,28,0,0,0,0,0,k09VZ\n'
    '群聯,2026/07/30,6,"-9,213",現買,1535,"9,210",3,0,0,0,0,0,0,k07xA\n'
)

CSV_TOTAL_COUNT = 4

# 名稱→代碼比對表（測試用預先建立的 stock_aliases，避免打真的 FinMind API）。
CSV_ALIAS_MAP = {
    "弘塑": "3131", "矽格": "6257", "矽科宏晟": "6451", "群聯": "8299",
}


class ParseTradeCsvFullSampleTest(unittest.TestCase):
    """parse_trade_csv_text() 對PO真實範例文字的整體解析正確性
    （純函式，不碰資料庫）——本檔案新增第四種貼文字快速輸入格式。"""

    def setUp(self):
        self.out = trade_ledger_parser.parse_trade_csv_text(CSV_SAMPLE_TEXT)

    def test_total_trade_count(self):
        self.assertEqual(self.out["total_parsed"], CSV_TOTAL_COUNT)
        self.assertEqual(len(self.out["trades"]), CSV_TOTAL_COUNT)

    def test_no_unparsed_lines(self):
        """提示文字行、表頭列都要被正確跳過，不進unparsed_lines。"""
        self.assertEqual(self.out["unparsed_lines"], [])

    def test_all_4_trades_fields_correct(self):
        """逐筆核對日期(西元)/買賣別/名稱/股數/價格，跟PO手動驗算過的
        數字完全一致：弘塑買3股@2180、矽格賣50股@173、矽科宏晟賣40股@240、
        群聯買6股@1535，皆為2026-07-30。"""
        expected = [
            ("2026-07-30", "買", "弘塑", 3, 2180.0),
            ("2026-07-30", "賣", "矽格", 50, 173.0),
            ("2026-07-30", "賣", "矽科宏晟", 40, 240.0),
            ("2026-07-30", "買", "群聯", 6, 1535.0),
        ]
        self.assertEqual(len(self.out["trades"]), len(expected))
        for trade, (date, action, name, shares, price) in zip(self.out["trades"], expected):
            self.assertEqual(trade["date"], date, trade)
            self.assertEqual(trade["action"], action, trade)
            self.assertEqual(trade["name"], name, trade)
            self.assertEqual(trade["shares"], shares, trade)
            self.assertEqual(trade["price"], price, trade)

    def test_western_date_slash_converted_to_dash(self):
        self.assertEqual(self.out["trades"][0]["date"], "2026-07-30")

    def test_raw_line_preserved(self):
        first = self.out["trades"][0]
        self.assertIn("弘塑", first["raw_line"])
        self.assertIn("2026/07/30", first["raw_line"])

    def test_quoted_thousand_separator_amount_not_split_into_extra_field(self):
        """驗證csv模組正確處理引號內的千分位逗號（如"-6,542"），不會被
        誤拆成兩個欄位進而讓後面欄位(買賣別/成交價)對錯位。"""
        first = self.out["trades"][0]
        self.assertEqual(first["action"], "買")  # 若"-6,542"被誤拆，這裡會拿到"542"對不上買賣別
        self.assertEqual(first["price"], 2180.0)

    def test_all_4_order_refs_extracted(self):
        """委託書號（order_ref，2026-07-31新增）：CSV最後一欄（索引14），
        逐筆核對PO真實範例文字裡的4個委託書號。"""
        expected_order_refs = ["k09QI", "k09j3", "k09VZ", "k07xA"]
        self.assertEqual(len(self.out["trades"]), len(expected_order_refs))
        for trade, expected in zip(self.out["trades"], expected_order_refs):
            self.assertEqual(trade["order_ref"], expected, trade)


class ParseTradeCsvSkipAndEdgeCasesTest(unittest.TestCase):
    def test_prompt_line_skipped_regardless_of_content(self):
        """開頭提示文字（筆數會變、內容不寫死比對）：換成不同筆數/文字，
        照樣要被跳過而不是誤判成資料列或進unparsed_lines。"""
        text = (
            "根據您篩選的結果，總計有999筆資料，當前資料為1-1筆，其他不同的文字\n"
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            '弘塑,2026/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
        )
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(out["unparsed_lines"], [])

    def test_header_row_itself_skipped(self):
        text = ("股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
                "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n")
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_empty_text_returns_empty_result(self):
        out = trade_ledger_parser.parse_trade_csv_text("")
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["total_parsed"], 0)

    def test_unsupported_action_value_goes_to_unparsed_not_guessed(self):
        """買賣別不是「現買」/「現賣」（如融資買，PO未提供範例）時，歸入
        unparsed_lines讓PO人工檢查，不可靜默猜測成買或賣。"""
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            '弘塑,2026/07/30,3,"-6,542",融資買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
        )
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(len(out["unparsed_lines"]), 1)
        self.assertIn("融資買", out["unparsed_lines"][0])

    def test_malformed_date_goes_to_unparsed(self):
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            '弘塑,115/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
        )
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(len(out["unparsed_lines"]), 1)

    def test_too_few_fields_goes_to_unparsed(self):
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            "弘塑,2026/07/30,3\n"
        )
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(len(out["unparsed_lines"]), 1)

    def test_order_ref_column_missing_gives_none_not_indexerror(self):
        """欄位數足以解析出日期/股數/買賣別/成交價（≥6欄，通過既有檢查）
        但不足15欄（缺委託書號欄）時，order_ref該給None，不拋IndexError、
        不影響其餘欄位解析成功。"""
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價\n"
            "弘塑,2026/07/30,3,\"-6,542\",現買,2180\n"
        )
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(len(out["trades"]), 1)
        self.assertIsNone(out["trades"][0]["order_ref"])
        self.assertEqual(out["trades"][0]["price"], 2180.0)

    def test_no_header_found_at_all_treats_everything_as_noise(self):
        """完全沒有表頭列（極端情況）：所有行都被當成表頭前雜訊跳過，不進
        unparsed_lines也不進trades（沒有明確的資料列邊界，不猜測解析）。"""
        text = "只是一段沒有表頭的雜訊文字\n另一行雜訊\n"
        out = trade_ledger_parser.parse_trade_csv_text(text)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])


class ResolveAndSaveTradeCsvTest(unittest.TestCase):
    """parse_trade_csv_text() 的輸出可以直接餵給既有的
    resolve_and_save_trade_ledger()，不需要另一套resolve/save邏輯。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-csv-test-")
        self.store = KBStore(self.tmp)
        for name, code in CSV_ALIAS_MAP.items():
            self.store.save_stock_alias(name, code, source="測試預先建立")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _run(self):
        parsed = trade_ledger_parser.parse_trade_csv_text(CSV_SAMPLE_TEXT)
        return trade_ledger_parser.resolve_and_save_trade_ledger(
            parsed, self.store, data_dir=self.tmp)

    def test_all_4_saved_none_unresolved_or_unparsed(self):
        out = self._run()
        self.assertEqual(out["total_parsed"], CSV_TOTAL_COUNT)
        self.assertEqual(len(out["saved"]), CSV_TOTAL_COUNT)
        self.assertEqual(out["unresolved_names"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["duplicates_skipped"], [])

    def test_pasting_same_batch_twice_second_time_all_skipped_as_duplicates(self):
        """委託書號防重複（2026-07-31新增，PO明確要求）——最重要的回歸
        測試，直接對應PO今天真實遇到的情境：貼同一份CSV對帳單兩次。
        第一次4筆應該全部成功寫入；第二次貼入完全一樣的4筆，應該全部
        因委託書號（k09QI/k09j3/k09VZ/k07xA）已存在資料庫而被判定為
        重複，saved為空、duplicates_skipped有4筆，資料庫裡也沒有真的
        被多存一份。"""
        first = self._run()
        self.assertEqual(len(first["saved"]), CSV_TOTAL_COUNT)
        self.assertEqual(first["duplicates_skipped"], [])

        second = self._run()
        self.assertEqual(second["saved"], [])
        self.assertEqual(len(second["duplicates_skipped"]), CSV_TOTAL_COUNT)
        dup_order_refs = {d["order_ref"] for d in second["duplicates_skipped"]}
        self.assertEqual(dup_order_refs, {"k09QI", "k09j3", "k09VZ", "k07xA"})
        for d in second["duplicates_skipped"]:
            self.assertIn("code", d)
            self.assertIn("name", d)

        # 資料庫裡沒有真的被多存一份——每個代碼仍然只有1筆。
        for code in CSV_ALIAS_MAP.values():
            self.assertEqual(self.store.get_trade_ledger(code)["count"], 1)

    def test_buys_get_add_sequence_1_sells_get_none(self):
        out = self._run()
        by_code = {s["code"]: s for s in out["saved"]}
        self.assertEqual(by_code["3131"]["action"], "買")  # 弘塑
        self.assertEqual(by_code["3131"]["add_sequence"], 1)
        self.assertEqual(by_code["8299"]["action"], "買")  # 群聯
        self.assertEqual(by_code["8299"]["add_sequence"], 1)
        self.assertEqual(by_code["6257"]["action"], "賣")  # 矽格
        self.assertIsNone(by_code["6257"]["add_sequence"])
        self.assertEqual(by_code["6451"]["action"], "賣")  # 矽科宏晟
        self.assertIsNone(by_code["6451"]["add_sequence"])

    def test_persisted_to_db_matches_returned_saved_list(self):
        out = self._run()
        for s in out["saved"]:
            ledger = self.store.get_trade_ledger(s["code"])
            match = [e for e in ledger["entries"]
                    if e["date"] == s["date"] and e["price"] == s["price"]
                    and e["shares"] == s["shares"] and e["action"] == s["action"]]
            self.assertEqual(len(match), 1, "找不到對應的DB紀錄：%r" % s)

    def test_unresolved_name_not_saved(self):
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            '查無此股,2026/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
        )
        parsed = trade_ledger_parser.parse_trade_csv_text(text)
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info", return_value={"stocks": []}):
            out = trade_ledger_parser.resolve_and_save_trade_ledger(
                parsed, self.store, data_dir=self.tmp)
        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)
        self.assertEqual(out["unresolved_names"][0]["name"], "查無此股")


class McpToolDispatchTradeCsvTest(unittest.TestCase):
    """server.py 的 parse_and_save_trade_csv 工具串接測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-csv-mcp-test-")
        self.srv = server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        shutil.rmtree(self.tmp)

    def test_tool_registered_in_tools_list(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertIn("parse_and_save_trade_csv", names)

    def test_dispatch_parses_and_saves_full_sample(self):
        for name, code in CSV_ALIAS_MAP.items():
            self.srv.store.save_stock_alias(name, code, source="測試")
        out = self.srv.call_tool("parse_and_save_trade_csv", {"text": CSV_SAMPLE_TEXT})
        self.assertEqual(out["total_parsed"], CSV_TOTAL_COUNT)
        self.assertEqual(len(out["saved"]), CSV_TOTAL_COUNT)
        self.assertEqual(out["unresolved_names"], [])
        self.assertEqual(out["unparsed_lines"], [])

    def test_dispatch_unresolved_name_not_saved(self):
        text = (
            "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
            "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,委託書號\n"
            '查無此股,2026/07/30,3,"-6,542",現買,2180,"6,540",2,0,0,0,0,0,0,k09QI\n'
        )
        with unittest.mock.patch.object(
                trade_ledger_parser.stock_alias_resolver.finmind_client,
                "get_stock_info", return_value={"stocks": []}):
            out = self.srv.call_tool("parse_and_save_trade_csv", {"text": text})
        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)


if __name__ == "__main__":
    unittest.main()
