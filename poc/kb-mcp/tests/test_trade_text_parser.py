"""trade_text_parser 測試（FR-044 老芋頭進出批次文字解析＋批次寫入）。

SAMPLE_TEXT 是 PO 實際會貼的完整真實範例（不是自編假資料），逐條驗證
parser 對每一行都解析正確，不只驗證前幾行。
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
import trade_text_parser  # noqa: E402
from kb_store import KBStore  # noqa: E402

# PO 實際貼的完整文字（2026-07-30 澄清：第一行固定是8位數日期 YYYYMMDD）。
# 賣出批次10筆、買進批次23筆（自行逐行數過，"買進批次22筆"的口頭提示
# 少算一筆——276行 176買進2張揚博 ... 到130.5回補100股順德一共23行）。
SAMPLE_TEXT = """\
20260729
殺估值，獲利跟不上股價，清倉換股
365賣出500股聯鈞（出清）
280賣出2張政美（出清）
129.5賣出1張奇鼎
121賣出2張聯陽（出清）
179賣出1張元太（出清）
502賣出800股聯詠（出清）
172賣出1張緯創
182賣出900股原相（出清）
98.6賣出1張超豐
99.6賣出700股兆捷（出清）


176買進2張揚博
357買進2張環宇KY
1485買進1張群聯
2260買進20股弘塑
2830買進30股世芯KY
5190買進20股鴻勁
135買進150股晶技
108.5買進100股瑞峰
196買進100股鈺邦
95.5買進1張金山電
308買進50股南寶
149買回100股同欣電
198買回50股勤凱
375.5買進50股家登
388買回100股臻鼎KY
415買進50股和淞
72買進50股來頡（來到底部）
690回補60股欣興
793回補10股均華
680回補10股亞翔
168買進100股欣銓
1945買回20股智邦
130.5回補100股順德
"""

SELL_COUNT = 10
BUY_COUNT = 23
TOTAL_COUNT = SELL_COUNT + BUY_COUNT


class ParseFullSampleTest(unittest.TestCase):
    """完整範例文字的整體解析正確性。"""

    def setUp(self):
        self.out = trade_text_parser.parse_laoyutou_trade_text(SAMPLE_TEXT)

    def test_date_line_parsed_and_excluded_from_reason(self):
        self.assertEqual(self.out["date"], "2026-07-29")
        # 日期行不能被誤判成第一筆交易的原因——第一筆賣出的 reason 只該是
        # 「殺估值...」，不含日期數字。
        first_sell = self.out["trades"][0]
        self.assertEqual(first_sell["reason"], "殺估值，獲利跟不上股價，清倉換股")
        self.assertNotIn("20260729", first_sell["reason"])

    def test_total_trade_count_matches_sell_and_buy_batches(self):
        self.assertEqual(self.out["total_parsed"], TOTAL_COUNT)
        self.assertEqual(len(self.out["trades"]), TOTAL_COUNT)
        sells = [t for t in self.out["trades"] if t["action"] == "賣"]
        buys = [t for t in self.out["trades"] if t["action"] == "買"]
        self.assertEqual(len(sells), SELL_COUNT)
        self.assertEqual(len(buys), BUY_COUNT)

    def test_no_unparsed_lines(self):
        self.assertEqual(self.out["unparsed_lines"], [])

    def test_sell_batch_reason_all_contain_殺估值(self):
        sells = [t for t in self.out["trades"] if t["action"] == "賣"]
        self.assertEqual(len(sells), SELL_COUNT)
        for t in sells:
            self.assertIn("殺估值", t["reason"] or "")

    def test_buy_batch_reason_none_after_blank_line_reset(self):
        """空行必須清空原因——買進批次前有兩個空行、沒有新的原因行，
        因此全部23筆買進的reason都該是None，不能沿用賣出批次的原因。"""
        buys = [t for t in self.out["trades"] if t["action"] == "買"]
        self.assertEqual(len(buys), BUY_COUNT)
        for t in buys:
            self.assertIsNone(t["reason"])
            self.assertNotIn("殺估值", t.get("reason") or "")

    def test_note_parsed_for_lines_with_parentheses(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["聯鈞"]["note"], "出清")
        self.assertEqual(by_name["政美"]["note"], "出清")
        self.assertEqual(by_name["來頡"]["note"], "來到底部")

    def test_note_none_for_lines_without_parentheses(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertIsNone(by_name["奇鼎"]["note"])
        self.assertIsNone(by_name["緯創"]["note"])
        self.assertIsNone(by_name["揚博"]["note"])

    def test_unit_zhang_converts_to_thousand_shares(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["政美"]["shares"], 2000)  # 2張
        self.assertEqual(by_name["奇鼎"]["shares"], 1000)  # 1張
        self.assertEqual(by_name["揚博"]["shares"], 2000)  # 2張
        self.assertEqual(by_name["金山電"]["shares"], 1000)  # 1張

    def test_unit_gu_keeps_share_count_unchanged(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["聯鈞"]["shares"], 500)  # 500股
        self.assertEqual(by_name["弘塑"]["shares"], 20)  # 20股
        self.assertEqual(by_name["晶技"]["shares"], 150)  # 150股

    def test_mixed_chinese_english_stock_names_parsed_correctly(self):
        names = {t["name"] for t in self.out["trades"]}
        self.assertIn("環宇KY", names)
        self.assertIn("世芯KY", names)
        self.assertIn("臻鼎KY", names)

    def test_decimal_price_parsed_correctly(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["奇鼎"]["price"], 129.5)
        self.assertEqual(by_name["超豐"]["price"], 98.6)
        self.assertEqual(by_name["兆捷"]["price"], 99.6)

    def test_action_mapping_for_three_buy_verbs(self):
        """買進／買回／回補三個字面不同的動詞都要對應 action="買"。"""
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["揚博"]["action"], "買")  # 買進
        self.assertEqual(by_name["同欣電"]["action"], "買")  # 買回
        self.assertEqual(by_name["欣興"]["action"], "買")  # 回補
        self.assertEqual(by_name["聯鈞"]["action"], "賣")  # 賣出

    def test_raw_line_preserved(self):
        by_name = {t["name"]: t for t in self.out["trades"]}
        self.assertEqual(by_name["聯鈞"]["raw_line"], "365賣出500股聯鈞（出清）")


class ParseDateLineTest(unittest.TestCase):
    def test_no_date_line_returns_date_none(self):
        text = "殺估值，獲利跟不上股價，清倉換股\n365賣出500股聯鈞（出清）\n"
        out = trade_text_parser.parse_laoyutou_trade_text(text)
        self.assertIsNone(out["date"])
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(out["trades"][0]["reason"], "殺估值，獲利跟不上股價，清倉換股")

    def test_date_line_not_first_nonblank_line_is_ignored(self):
        """8位數字只有出現在「文字第一個非空行」才視為日期；不是第一行的話
        不特別處理——照一般規則走：開頭是數字但不符合交易行格式，跟其他
        「疑似交易行但格式跑掉」的行一樣歸入unparsed_lines（不會被誤判成
        日期，也不會被誤判成原因行去污染後面聯鈞這筆交易的reason，reason
        仍該是前一行「殺估值」）。"""
        text = "殺估值\n20260729\n365賣出500股聯鈞（出清）\n"
        out = trade_text_parser.parse_laoyutou_trade_text(text)
        self.assertIsNone(out["date"])
        self.assertEqual(out["unparsed_lines"], ["20260729"])
        self.assertEqual(out["trades"][0]["reason"], "殺估值")

    def test_blank_lines_before_date_line_still_detected(self):
        text = "\n\n20260729\n365賣出500股聯鈞（出清）\n"
        out = trade_text_parser.parse_laoyutou_trade_text(text)
        self.assertEqual(out["date"], "2026-07-29")
        self.assertIsNone(out["trades"][0]["reason"])


class ParseUnparsedLinesTest(unittest.TestCase):
    def test_malformed_digit_leading_line_goes_to_unparsed(self):
        """開頭是數字但不符合完整交易行格式的行，歸入unparsed_lines，
        不誤判成原因行（避免污染後續交易的reason）。"""
        text = "365賣出股聯鈞\n176買進2張揚博\n"  # 缺股數
        out = trade_text_parser.parse_laoyutou_trade_text(text)
        self.assertEqual(out["unparsed_lines"], ["365賣出股聯鈞"])
        self.assertEqual(out["total_parsed"], 1)
        self.assertIsNone(out["trades"][0]["reason"])

    def test_empty_text_returns_empty_result(self):
        out = trade_text_parser.parse_laoyutou_trade_text("")
        self.assertIsNone(out["date"])
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["total_parsed"], 0)


class ResolveAndSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-parser-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def _parsed(self, trades, date=None, unparsed_lines=None):
        return {"date": date, "trades": trades,
               "unparsed_lines": unparsed_lines or []}

    def test_cache_hit_does_not_call_finmind(self):
        self.store.save_stock_alias("聯鈞", "3450", source="測試預先建立")
        parsed = self._parsed([
            {"price": 365.0, "action": "賣", "shares": 500, "name": "聯鈞",
             "note": "出清", "reason": None, "raw_line": "x"},
        ], date="2026-07-29")

        with unittest.mock.patch.object(
                trade_text_parser.finmind_client, "get_stock_info") as mock_fm:
            out = trade_text_parser.resolve_and_save_laoyutou_trades(
                parsed, store=self.store, data_dir=self.tmp)
            mock_fm.assert_not_called()

        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["code"], "3450")
        self.assertEqual(out["unresolved_names"], [])
        got = self.store.get_laoyutou_trades(code="3450")
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["trades"][0]["reason"], "出清")  # note單獨存在時直接當reason

    def test_finmind_fallback_hit_with_hyphen_normalization_and_caches_alias(self):
        """快取沒有「世芯KY」，FinMind清單裡是「世芯-KY」——正規化去除連字號
        後應能比對成功，並把結果存回stock_aliases快取。"""
        parsed = self._parsed([
            {"price": 2830.0, "action": "買", "shares": 30, "name": "世芯KY",
             "note": None, "reason": None, "raw_line": "x"},
        ], date="2026-07-29")

        fake_info = {"stocks": [
            {"stock_id": "3661", "stock_name": "世芯-KY"},
            {"stock_id": "2330", "stock_name": "台積電"},
        ]}
        with unittest.mock.patch.object(
                trade_text_parser.finmind_client, "get_stock_info",
                return_value=fake_info) as mock_fm:
            out = trade_text_parser.resolve_and_save_laoyutou_trades(
                parsed, store=self.store, data_dir=self.tmp)
            mock_fm.assert_called_once_with(data_dir=self.tmp, token=None)

        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["code"], "3661")
        self.assertEqual(out["unresolved_names"], [])

        # 應已寫回快取，下次同名稱直接命中步驟1不必再查FinMind。
        alias = self.store.get_stock_alias("世芯KY")
        self.assertTrue(alias["found"])
        self.assertEqual(alias["record"]["code"], "3661")
        self.assertEqual(alias["record"]["source"], "老芋頭進出批次解析自動比對")

    def test_both_cache_and_finmind_miss_goes_to_unresolved_and_not_saved(self):
        parsed = self._parsed([
            {"price": 100.0, "action": "買", "shares": 1000, "name": "查無此股",
             "note": None, "reason": None, "raw_line": "100買進1張查無此股"},
        ], date="2026-07-29")

        fake_info = {"stocks": [{"stock_id": "2330", "stock_name": "台積電"}]}
        with unittest.mock.patch.object(
                trade_text_parser.finmind_client, "get_stock_info",
                return_value=fake_info):
            out = trade_text_parser.resolve_and_save_laoyutou_trades(
                parsed, store=self.store, data_dir=self.tmp)

        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)
        self.assertEqual(out["unresolved_names"][0]["name"], "查無此股")
        self.assertEqual(out["unresolved_names"][0]["raw_line"], "100買進1張查無此股")
        # 沒有code，絕不可寫入laoyutou_trades
        self.assertEqual(self.store.get_laoyutou_trades()["count"], 0)

    def test_reason_and_note_combined_with_separator(self):
        self.store.save_stock_alias("聯鈞", "3450")
        parsed = self._parsed([
            {"price": 365.0, "action": "賣", "shares": 500, "name": "聯鈞",
             "note": "出清", "reason": "殺估值，獲利跟不上股價，清倉換股",
             "raw_line": "x"},
        ], date="2026-07-29")
        trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, data_dir=self.tmp)
        saved = self.store.get_laoyutou_trades(code="3450")["trades"][0]
        self.assertEqual(saved["reason"],
                         "殺估值，獲利跟不上股價，清倉換股；出清")

    def test_reason_only_no_note(self):
        self.store.save_stock_alias("奇鼎", "6069")
        parsed = self._parsed([
            {"price": 129.5, "action": "賣", "shares": 1000, "name": "奇鼎",
             "note": None, "reason": "殺估值", "raw_line": "x"},
        ], date="2026-07-29")
        trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, data_dir=self.tmp)
        saved = self.store.get_laoyutou_trades(code="6069")["trades"][0]
        self.assertEqual(saved["reason"], "殺估值")

    def test_neither_reason_nor_note_results_in_none(self):
        self.store.save_stock_alias("揚博", "2493")
        parsed = self._parsed([
            {"price": 176.0, "action": "買", "shares": 2000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x"},
        ], date="2026-07-29")
        trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, data_dir=self.tmp)
        saved = self.store.get_laoyutou_trades(code="2493")["trades"][0]
        self.assertIsNone(saved["reason"])

    def test_parsed_date_takes_priority_over_explicit_date_param(self):
        self.store.save_stock_alias("揚博", "2493")
        parsed = self._parsed([
            {"price": 176.0, "action": "買", "shares": 2000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x"},
        ], date="2026-07-29")
        trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, date="2026-01-01", data_dir=self.tmp)
        saved = self.store.get_laoyutou_trades(code="2493")["trades"][0]
        self.assertEqual(saved["date"], "2026-07-29")

    def test_explicit_date_param_used_when_text_has_no_date(self):
        self.store.save_stock_alias("揚博", "2493")
        parsed = self._parsed([
            {"price": 176.0, "action": "買", "shares": 2000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x"},
        ], date=None)
        trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, date="2026-01-01", data_dir=self.tmp)
        saved = self.store.get_laoyutou_trades(code="2493")["trades"][0]
        self.assertEqual(saved["date"], "2026-01-01")

    def test_unparsed_lines_passed_through(self):
        parsed = self._parsed([], date="2026-07-29",
                              unparsed_lines=["365賣出股聯鈞"])
        out = trade_text_parser.resolve_and_save_laoyutou_trades(
            parsed, store=self.store, data_dir=self.tmp)
        self.assertEqual(out["unparsed_lines"], ["365賣出股聯鈞"])
        self.assertEqual(out["total_parsed"], 0)

    def test_accepts_bare_trade_list_as_fallback_interface(self):
        """容錯：直接傳trades list（不是完整parse結果dict）也要能動作，
        只是沒有date/unparsed_lines可透傳。"""
        self.store.save_stock_alias("揚博", "2493")
        bare_trades = [
            {"price": 176.0, "action": "買", "shares": 2000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x"},
        ]
        out = trade_text_parser.resolve_and_save_laoyutou_trades(
            bare_trades, store=self.store, date="2026-05-01", data_dir=self.tmp)
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(len(out["saved"]), 1)
        saved = self.store.get_laoyutou_trades(code="2493")["trades"][0]
        self.assertEqual(saved["date"], "2026-05-01")

    def test_duplicate_name_only_queries_alias_cache_once(self):
        """同一批次裡同名稱出現多次，只該查一次stock_aliases，不必重複查。"""
        self.store.save_stock_alias("揚博", "2493")
        parsed = self._parsed([
            {"price": 176.0, "action": "買", "shares": 2000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x1"},
            {"price": 180.0, "action": "買", "shares": 1000, "name": "揚博",
             "note": None, "reason": None, "raw_line": "x2"},
        ], date="2026-07-29")
        with unittest.mock.patch.object(
                self.store, "get_stock_alias",
                wraps=self.store.get_stock_alias) as mock_alias:
            out = trade_text_parser.resolve_and_save_laoyutou_trades(
                parsed, store=self.store, data_dir=self.tmp)
            mock_alias.assert_called_once_with("揚博")
        self.assertEqual(len(out["saved"]), 2)


class McpToolDispatchTest(unittest.TestCase):
    """server.py 的 parse_and_save_laoyutou_trades 工具串接測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-trade-parser-mcp-test-")
        self.srv = server.Server(data_dir=self.tmp)

    def tearDown(self):
        self.srv.store.close()
        shutil.rmtree(self.tmp)

    def test_tool_registered_in_tools_list(self):
        names = [t["name"] for t in server.TOOLS]
        self.assertIn("parse_and_save_laoyutou_trades", names)

    def test_dispatch_parses_and_saves_using_text_date_line(self):
        self.srv.store.save_stock_alias("聯鈞", "3450")
        text = "20260729\n殺估值\n365賣出500股聯鈞（出清）\n"
        out = self.srv.call_tool("parse_and_save_laoyutou_trades", {"text": text})
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(len(out["saved"]), 1)
        self.assertEqual(out["saved"][0]["code"], "3450")
        saved = self.srv.store.get_laoyutou_trades(code="3450")["trades"][0]
        self.assertEqual(saved["date"], "2026-07-29")
        self.assertEqual(saved["reason"], "殺估值；出清")

    def test_dispatch_date_param_used_when_text_has_no_date_line(self):
        self.srv.store.save_stock_alias("揚博", "2493")
        text = "176買進2張揚博\n"
        out = self.srv.call_tool(
            "parse_and_save_laoyutou_trades", {"text": text, "date": "2026-02-14"})
        self.assertEqual(len(out["saved"]), 1)
        saved = self.srv.store.get_laoyutou_trades(code="2493")["trades"][0]
        self.assertEqual(saved["date"], "2026-02-14")

    def test_dispatch_unresolved_name_not_saved(self):
        text = "20260729\n100買進1張查無此股\n"
        with unittest.mock.patch.object(
                trade_text_parser.finmind_client, "get_stock_info",
                return_value={"stocks": []}):
            out = self.srv.call_tool("parse_and_save_laoyutou_trades", {"text": text})
        self.assertEqual(out["saved"], [])
        self.assertEqual(len(out["unresolved_names"]), 1)
        self.assertEqual(out["unresolved_names"][0]["name"], "查無此股")


if __name__ == "__main__":
    unittest.main()
