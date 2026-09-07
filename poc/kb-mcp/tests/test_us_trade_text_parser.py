"""`us_trade_text_parser.py` 測試（T012，specs/003-us-stocks Phase 3 US1）。

輸入格式（本模組自訂，見 us_trade_text_parser.py 檔頭 docstring）：
    每行一筆交易：{日期 YYYY-MM-DD} {代號} {買進|賣出} {股數}股 ${價格}
    例：2026-08-05 NET 買進 10股 $298.40

這是 Claude 讀完使用者貼的交易截圖、轉成結構化文字後餵給
`parse_and_save_us_trade` MCP 工具的格式（見 research.md §3：辨識發生在
呼叫工具之前，工具本身只用正則表達式解析固定格式文字，不做 OCR）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_us_trade*"
（第一次跑此檔案時 us_trade_text_parser.py 尚不存在，預期 ImportError／
FAIL——這是 T012「先寫測試，此時應該 FAIL」的驗收證據。）
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import us_trade_text_parser  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402

# PO 實際會貼的完整範例文字：3 筆買進、1 筆賣出、1 筆格式跑掉（缺 $ 符號）、
# 1 筆完全不像交易行的雜訊註解（順手加的說明，應被安靜忽略，不進
# unparsed_lines——同 trade_ledger_parser.py／trade_text_parser.py 對
# 「非資料列、也不符合已知跳過樣式」的既有處理精神）。
SAMPLE_TEXT = """\
這是我這週的美股交易紀錄
2026-08-05 NET 買進 10股 $298.40
2026-08-06 CRWD 買進 5股 $350.00
2026-08-10 net 賣出 3股 $310.25
2026-08-11 SNOW 買進 2.5股 $150.75
2026-08-12 AAPL 買進 1股 200
"""

TOTAL_COUNT = 4  # 5 行資料，其中最後一行缺 "$" 格式跑掉歸入 unparsed_lines


class ParseFullSampleTest(unittest.TestCase):
    def setUp(self):
        self.out = us_trade_text_parser.parse_us_trade_text(SAMPLE_TEXT)

    def test_total_trade_count(self):
        self.assertEqual(self.out["total_parsed"], TOTAL_COUNT)
        self.assertEqual(len(self.out["trades"]), TOTAL_COUNT)

    def test_buy_and_sell_actions_mapped_to_english(self):
        """action 必須是 us_stock_store.VALID_TRADE_ACTIONS 的
        'buy'/'sell'（英文），不是台股解析器慣用的中文'買'/'賣'——
        USStockStore.save_trade() 只接受這兩個英文值。NET 出現兩次
        （買進/賣出各一），這裡只驗證第一筆（買進）的 action，第二筆
        （賣出）由 test_ticker_normalized_to_uppercase 另外驗證。"""
        first_net = self.out["trades"][0]
        self.assertEqual(first_net["ticker"], "NET")
        self.assertEqual(first_net["action"], "buy")
        by_ticker = {t["ticker"]: t for t in self.out["trades"]
                     if t["ticker"] != "NET"}
        self.assertEqual(by_ticker["CRWD"]["action"], "buy")
        self.assertEqual(by_ticker["SNOW"]["action"], "buy")

    def test_ticker_normalized_to_uppercase(self):
        """第三筆刻意用小寫 net 測試大小寫正規化。"""
        tickers = {t["ticker"] for t in self.out["trades"]}
        self.assertIn("NET", tickers)
        self.assertNotIn("net", tickers)
        sells = [t for t in self.out["trades"] if t["action"] == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["ticker"], "NET")
        self.assertEqual(sells[0]["shares"], 3.0)
        self.assertEqual(sells[0]["price"], 310.25)

    def test_decimal_shares_parsed(self):
        by_ticker = {t["ticker"]: t for t in self.out["trades"]}
        self.assertEqual(by_ticker["SNOW"]["shares"], 2.5)
        self.assertEqual(by_ticker["SNOW"]["price"], 150.75)

    def test_date_parsed_correctly(self):
        self.assertEqual(self.out["trades"][0]["trade_date"], "2026-08-05")  # NET 買進
        by_ticker = {t["ticker"]: t for t in self.out["trades"]
                     if t["ticker"] != "NET"}
        self.assertEqual(by_ticker["CRWD"]["trade_date"], "2026-08-06")

    def test_missing_dollar_sign_goes_to_unparsed(self):
        """AAPL 那行價格沒有 "$" 前綴，不符合格式，歸入 unparsed_lines
        （寧可歸入待查也不要用不完整格式猜一個可能錯誤的價格）。"""
        self.assertEqual(len(self.out["unparsed_lines"]), 1)
        self.assertIn("AAPL", self.out["unparsed_lines"][0])

    def test_leading_note_line_silently_ignored(self):
        """開頭的說明文字（不像交易行、也不符合任何已知跳過樣式）不計入
        trades 也不計入 unparsed_lines，避免雜訊。"""
        for line in self.out["unparsed_lines"]:
            self.assertNotIn("這是我這週", line)
        self.assertEqual(len(self.out["unparsed_lines"]), 1)  # 只有AAPL那行

    def test_raw_line_preserved(self):
        self.assertEqual(
            self.out["trades"][0]["raw_line"], "2026-08-05 NET 買進 10股 $298.40")


class ParseEdgeCasesTest(unittest.TestCase):
    def test_empty_text_returns_empty_result(self):
        out = us_trade_text_parser.parse_us_trade_text("")
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["total_parsed"], 0)

    def test_none_text_returns_empty_result(self):
        out = us_trade_text_parser.parse_us_trade_text(None)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["total_parsed"], 0)

    def test_blank_lines_skipped(self):
        text = "\n\n2026-08-05 NET 買進 10股 $298.40\n\n"
        out = us_trade_text_parser.parse_us_trade_text(text)
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(out["unparsed_lines"], [])

    def test_malformed_date_line_looks_like_trade_goes_to_unparsed(self):
        """開頭是日期格式但股數/價格格式跑掉的行——視為疑似交易行但格式
        錯誤，歸入 unparsed_lines，不静默丟棄（同 trade_ledger_parser.py
        的 _LOOKS_LIKE_DATA_RE 判斷精神）。"""
        text = "2026-08-05 NET 買進 十股 $298.40\n"  # 股數用中文數字，不符合格式
        out = us_trade_text_parser.parse_us_trade_text(text)
        self.assertEqual(out["total_parsed"], 0)
        self.assertEqual(len(out["unparsed_lines"]), 1)

    def test_class_share_ticker_with_dot_suffix(self):
        text = "2026-08-05 BRK.B 買進 10股 $410.00\n"
        out = us_trade_text_parser.parse_us_trade_text(text)
        self.assertEqual(out["total_parsed"], 1)
        self.assertEqual(out["trades"][0]["ticker"], "BRK.B")


class ParseAndSaveTest(unittest.TestCase):
    """parse_and_save_us_trade_text()：解析＋直接寫入 USStockStore
    （美股不需要像台股一樣做「名稱→代碼」解析，截圖辨識出的就是代號本身，
    見 contracts/mcp-tools.md 工具一）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="us-trade-parser-test-")
        self.store = USStockStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_saves_all_parsed_trades(self):
        out = us_trade_text_parser.parse_and_save_us_trade_text(
            SAMPLE_TEXT, self.store)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["saved_count"], TOTAL_COUNT)
        self.assertEqual(len(out["trades"]), TOTAL_COUNT)
        # 已寫入 store，可查得到。
        self.assertEqual(len(self.store.list_trades("NET")), 2)  # 買+賣各一筆

    def test_saved_trade_has_amount_computed(self):
        out = us_trade_text_parser.parse_and_save_us_trade_text(
            "2026-08-05 NET 買進 10股 $298.40\n", self.store)
        self.assertEqual(out["trades"][0]["amount"], 2984.0)

    def test_unparsed_lines_reported_as_parse_issues(self):
        out = us_trade_text_parser.parse_and_save_us_trade_text(
            SAMPLE_TEXT, self.store)
        self.assertEqual(len(out["parse_issues"]), 1)
        self.assertIn("AAPL", out["parse_issues"][0])

    def test_partial_success_still_saves_valid_lines(self):
        """FR-003：不論辨識完整度，一律經人工核對才落庫——已成功解析的
        部分照樣寫入，不因為批次裡有解析失敗的行就整批放棄。"""
        text = "2026-08-05 NET 買進 10股 $298.40\n格式錯誤的一行\n"
        out = us_trade_text_parser.parse_and_save_us_trade_text(text, self.store)
        self.assertEqual(out["saved_count"], 1)
        self.assertEqual(len(self.store.list_trades("NET")), 1)

    def test_empty_text_saves_nothing(self):
        out = us_trade_text_parser.parse_and_save_us_trade_text("", self.store)
        self.assertEqual(out["saved_count"], 0)
        self.assertEqual(out["trades"], [])
        self.assertEqual(out["parse_issues"], [])


if __name__ == "__main__":
    unittest.main()
