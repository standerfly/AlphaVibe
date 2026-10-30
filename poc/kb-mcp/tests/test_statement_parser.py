"""009 T010：國泰日對帳單文字解析（測試資料皆為虛構數值）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cathay_statement_parser import StatementFormatError, parse_daily_statement  # noqa: E402

HEAD = """國泰綜合證券 日對帳單
交割金額
   成交日期      交割日期      預收款   留置款   客戶淨收(+)/付(-)金額
   2026/10/29    2026/11/02       0        0          -19,207
"""

TRADES_ONE = """交易明細
 商品名稱  類別  成交股數  單價   成交金額  手續費  交易稅  客戶應收付額  委託書號
 旺矽      集買      4    4800    19,200       7       0       -19,207    0 0 0 0   kAbCd00
 總合計                           19,200       7       0       -19,207
"""

HOLDINGS = """庫存明細
 代號   股票名稱   當日收盤價   集保股數   集保市值   融資股數  融券股數  理財資訊
 2308   台達電     ▲1,905.00        10     19,050        0         0   停損/停利通知 個股分析 我要下單
 6223   旺矽       ▼4800             4     19,200        0         0
 集保市值總計                                38,250
"""


class ParseDailyStatementTest(unittest.TestCase):
    def test_single_buy(self):
        r = parse_daily_statement(HEAD + TRADES_ONE + HOLDINGS)
        self.assertEqual(r["statement_date"], "2026-10-29")
        self.assertEqual(len(r["trades"]), 1)
        t = r["trades"][0]
        self.assertEqual((t["name"], t["market"], t["action"], t["shares"], t["price"],
                          t["amount"], t["fee"], t["tax"], t["order_ref"], t["date"]),
                         ("旺矽", "集", "買", 4, 4800.0, 19200.0, 7.0, 0.0, "kAbCd00",
                          "2026-10-29"))
        self.assertEqual([(h["code"], h["name"], h["shares"]) for h in r["holdings"]],
                         [("2308", "台達電", 10), ("6223", "旺矽", 4)])

    def test_multiple_trades_with_ot_xing_and_tax_star(self):
        trades = """交易明細
 中美晶    OT賣     50   242.50    12,125       4     *36     12,085   0 0 0 0  kXy0100
 世芯-KY   集買    100     2,500   250,000     356       0   -250,356   0 0 0 0  V00on01
 某興櫃    興買  1,000     12.30    12,300      17       0    -12,317   0 0 0 0  kZz9900
"""
        r = parse_daily_statement(HEAD + trades + HOLDINGS)
        got = [(t["name"], t["market"], t["action"], t["shares"], t["tax"], t["order_ref"])
               for t in r["trades"]]
        self.assertEqual(got, [("中美晶", "OT", "賣", 50, 36.0, "kXy0100"),
                               ("世芯-KY", "集", "買", 100, 0.0, "V00on01"),
                               ("某興櫃", "興", "買", 1000, 0.0, "kZz9900")])

    def test_odd_lot_and_zero_close_and_page_break(self):
        holdings = """庫存明細
 代號   股票名稱   當日收盤價   集保股數   集保市值
 2308   台達電     1,905.00          1      1,905
\f
 國泰綜合證券 日對帳單  第 2 頁
 代號   股票名稱   當日收盤價   集保股數   集保市值
 00878  國泰永續高股息   0          3          0
"""
        r = parse_daily_statement(HEAD + TRADES_ONE + holdings)
        self.assertEqual([(h["code"], h["shares"]) for h in r["holdings"]],
                         [("2308", 1), ("00878", 3)])

    def test_holdings_only(self):
        r = parse_daily_statement(HEAD + "交易明細\n 總合計  0  0  0\n" + HOLDINGS)
        self.assertEqual(r["trades"], [])
        self.assertEqual(len(r["holdings"]), 2)

    def test_no_trade_section_uses_fallback_date(self):
        r = parse_daily_statement(HOLDINGS, fallback_date="2026-10-30")
        self.assertEqual((r["statement_date"], r["trades"]), ("2026-10-30", []))

    def test_empty_holdings_section_is_valid(self):
        r = parse_daily_statement(HEAD + TRADES_ONE + "庫存明細\n 集保市值總計 0\n")
        self.assertEqual(r["holdings"], [])

    def test_missing_holdings_section(self):
        with self.assertRaises(StatementFormatError):
            parse_daily_statement(HEAD + TRADES_ONE)

    def test_missing_date(self):
        with self.assertRaises(StatementFormatError):
            parse_daily_statement(TRADES_ONE + HOLDINGS)

    def test_unparseable_trade_row(self):
        bad = "交易明細\n 旺矽 集買 4 4800 19,200\n"
        with self.assertRaises(StatementFormatError):
            parse_daily_statement(HEAD + bad + HOLDINGS)

    def test_unparseable_holding_row(self):
        bad = "庫存明細\n 2308 台達電 ▲\n"
        with self.assertRaises(StatementFormatError):
            parse_daily_statement(HEAD + TRADES_ONE + bad)

    def test_garbage(self):
        with self.assertRaises(StatementFormatError):
            parse_daily_statement("完全不相干的文字")


if __name__ == "__main__":
    unittest.main()
