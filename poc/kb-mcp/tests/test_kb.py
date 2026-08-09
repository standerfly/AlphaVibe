"""alphavibe-kb 測試：儲存層單元測試＋MCP 協定端到端煙霧測試。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -v
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import holdings_parser  # noqa: E402
import tpex_client  # noqa: E402
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

    def test_comments_batch_all_success(self):
        out = self.store.save_comments_batch([
            {"body": "早盤觀察：外資買超金融股", "source_tag": "line"},
            {"body": "尾盤拉抬電子權值股", "source_tag": "youtube", "symbols": "2330"},
        ])
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["saved_count"], 2)
        self.assertEqual(out["failed_count"], 0)
        self.assertTrue(all(r["saved"] for r in out["results"]))
        self.assertEqual(self.store.recent_comments(10)["count"], 2)

    def test_comments_batch_partial_success_keeps_valid_rows(self):
        out = self.store.save_comments_batch([
            {"body": "合法評論一", "source_tag": "line"},
            {"body": "", "source_tag": "line"},           # 缺 body（空字串）
            {"body": "合法評論二", "source_tag": "conversation"},
            {"source_tag": "line"},                        # 缺 body（key 都沒有）
        ])
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["saved_count"], 2)
        self.assertEqual(out["failed_count"], 2)
        self.assertTrue(out["results"][0]["saved"])
        self.assertFalse(out["results"][1]["saved"])
        self.assertIn("body", out["results"][1]["error"])
        self.assertTrue(out["results"][2]["saved"])
        self.assertFalse(out["results"][3]["saved"])
        # 只有合法的兩筆真的寫入資料庫，非法的兩筆不能讓整批全部失敗
        self.assertEqual(self.store.recent_comments(10)["count"], 2)

    def test_comments_batch_empty_list(self):
        out = self.store.save_comments_batch([])
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["saved_count"], 0)
        self.assertEqual(out["failed_count"], 0)
        self.assertEqual(out["results"], [])

    def test_stock_alias_save_and_get(self):
        out = self.store.save_stock_alias("環宇KY", "4991", name_full="環宇-KY",
                                          market="上市", source="公開資訊觀測站")
        self.assertTrue(out["saved"])
        self.assertEqual(out["record"]["code"], "4991")
        got = self.store.get_stock_alias("環宇KY")
        self.assertTrue(got["found"])
        self.assertEqual(got["record"]["code"], "4991")
        self.assertEqual(got["record"]["market"], "上市")

    def test_stock_alias_not_found(self):
        got = self.store.get_stock_alias("不存在的股票")
        self.assertFalse(got["found"])
        self.assertEqual(got["name"], "不存在的股票")

    def test_stock_alias_same_name_overwrites(self):
        self.store.save_stock_alias("奇鼎", "3722", source="第一次查證")
        updated = self.store.save_stock_alias("奇鼎", "3722", source="第二次查證",
                                               market="上櫃")
        self.assertTrue(updated["saved"])
        got = self.store.get_stock_alias("奇鼎")
        self.assertEqual(got["record"]["source"], "第二次查證")
        self.assertEqual(got["record"]["market"], "上櫃")
        # 同名再存＝更新，不是新增第二筆
        self.assertEqual(self.store.get_stock_alias()["count"], 1)

    def test_stock_alias_list_all_sorted_newest_first(self):
        self.store.save_stock_alias("A股", "1111", verified_date="2026-07-01")
        self.store.save_stock_alias("B股", "2222", verified_date="2026-07-10")
        all_aliases = self.store.get_stock_alias()
        self.assertEqual(all_aliases["count"], 2)
        self.assertEqual(all_aliases["aliases"][0]["name"], "B股")

    def test_stock_price_upsert_and_get(self):
        out = self.store.upsert_stock_price("2330", 1005.0, "2026-07-18")
        self.assertTrue(out["saved"])
        prices = self.store.get_stock_prices()
        self.assertIn("2330", prices)
        self.assertEqual(prices["2330"]["price"], 1005.0)
        self.assertEqual(prices["2330"]["price_date"], "2026-07-18")
        self.assertTrue(prices["2330"]["updated_at"])

    def test_stock_price_upsert_overwrites_not_duplicates(self):
        self.store.upsert_stock_price("2330", 1000.0, "2026-07-17")
        self.store.upsert_stock_price("2330", 1010.0, "2026-07-18")
        prices = self.store.get_stock_prices()
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices["2330"]["price"], 1010.0)
        self.assertEqual(prices["2330"]["price_date"], "2026-07-18")

    def test_stock_price_get_empty(self):
        self.assertEqual(self.store.get_stock_prices(), {})

    def test_stock_price_upsert_with_prev_close(self):
        out = self.store.upsert_stock_price("2330", 1005.0, "2026-07-18", prev_close=995.0)
        self.assertEqual(out["prev_close"], 995.0)
        prices = self.store.get_stock_prices()
        self.assertEqual(prices["2330"]["prev_close"], 995.0)

    def test_stock_price_prev_close_defaults_to_none(self):
        self.store.upsert_stock_price("2330", 1005.0, "2026-07-18")
        prices = self.store.get_stock_prices()
        self.assertIsNone(prices["2330"]["prev_close"])

    # ---------- 估值快照快取 ----------

    def test_stock_valuation_upsert_and_get(self):
        out = self.store.upsert_stock_valuation(
            "2330", per=14.2, pbr=2.85, dividend_yield=5.98,
            revenue_yoy=0.332, revenue_period="2026年6月",
            valuation_data_source="twse_official", revenue_data_source="twse_official",
            checked_at="2026-07-31T18:00:00")
        self.assertTrue(out["saved"])
        got = self.store.get_stock_valuation("2330")
        self.assertEqual(got["per"], 14.2)
        self.assertEqual(got["pbr"], 2.85)
        self.assertEqual(got["dividend_yield"], 5.98)
        self.assertEqual(got["revenue_yoy"], 0.332)
        self.assertEqual(got["valuation_data_source"], "twse_official")
        self.assertEqual(got["checked_at"], "2026-07-31T18:00:00")

    def test_stock_valuation_upsert_overwrites_not_duplicates(self):
        self.store.upsert_stock_valuation("2330", per=14.0, checked_at="2026-07-30T18:00:00")
        self.store.upsert_stock_valuation("2330", per=15.0, checked_at="2026-07-31T18:00:00")
        got = self.store.get_stock_valuation("2330")
        self.assertEqual(got["per"], 15.0)
        row_count = self.store.conn.execute(
            "SELECT COUNT(*) c FROM stock_valuation_snapshots WHERE code='2330'").fetchone()["c"]
        self.assertEqual(row_count, 1)

    def test_stock_valuation_get_missing_returns_none(self):
        self.assertIsNone(self.store.get_stock_valuation("9999"))

    def test_stock_valuation_requires_code(self):
        with self.assertRaises(ValueError):
            self.store.upsert_stock_valuation("")

    # ---------- 依代碼查留言 ----------

    def test_get_comments_by_code_exact_symbol_match(self):
        self.store.save_comment("封測產能利用率回升", source_tag="心得", symbols="2441")
        self.store.save_comment("外資調升目標價", source_tag="心得", symbols="2330")
        got = self.store.get_comments_by_code("2441")
        self.assertEqual(got["count"], 1)
        self.assertIn("封測", got["results"][0]["body"])

    def test_get_comments_by_code_avoids_substring_false_positive(self):
        """code="330"不該誤中symbols="2330"（子字串誤判，見docstring）。"""
        self.store.save_comment("外資調升目標價", source_tag="心得", symbols="2330")
        got = self.store.get_comments_by_code("330")
        self.assertEqual(got["count"], 0)

    def test_get_comments_by_code_multi_symbol_comment(self):
        self.store.save_comment("同時討論兩檔", source_tag="心得", symbols="2330,2441")
        self.assertEqual(self.store.get_comments_by_code("2330")["count"], 1)
        self.assertEqual(self.store.get_comments_by_code("2441")["count"], 1)
        self.assertEqual(self.store.get_comments_by_code("9999")["count"], 0)

    def test_get_comments_by_code_requires_code(self):
        with self.assertRaises(ValueError):
            self.store.get_comments_by_code("")

    def test_stock_industry_upsert_and_get(self):
        out = self.store.upsert_stock_industry("2330", "半導體業")
        self.assertTrue(out["saved"])
        industries = self.store.get_stock_industries()
        self.assertEqual(industries["2330"]["industry_category"], "半導體業")

    def test_stock_industry_upsert_overwrites_not_duplicates(self):
        self.store.upsert_stock_industry("2330", "舊分類")
        self.store.upsert_stock_industry("2330", "半導體業")
        industries = self.store.get_stock_industries()
        self.assertEqual(len(industries), 1)
        self.assertEqual(industries["2330"]["industry_category"], "半導體業")

    def test_stock_industry_get_empty(self):
        self.assertEqual(self.store.get_stock_industries(), {})

    def test_stock_theme_upsert_and_get(self):
        out = self.store.save_stock_theme("3661", "AI CAPEX")
        self.assertTrue(out["saved"])
        themes = self.store.get_stock_theme()
        self.assertEqual(themes["3661"]["theme"], "AI CAPEX")

    def test_stock_theme_upsert_overwrites_not_duplicates(self):
        self.store.save_stock_theme("3661", "舊主題")
        self.store.save_stock_theme("3661", "AI CAPEX")
        themes = self.store.get_stock_theme()
        self.assertEqual(len(themes), 1)
        self.assertEqual(themes["3661"]["theme"], "AI CAPEX")

    def test_stock_theme_get_empty(self):
        self.assertEqual(self.store.get_stock_theme(), {})

    def test_laoyutou_trade_save_and_get_by_code(self):
        out = self.store.save_laoyutou_trade(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-20",
            reason="清理門戶策略轉向", source_ref="line#1")
        self.assertTrue(out["saved"])
        result = self.store.get_laoyutou_trades(code="2330")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["trades"][0]["reason"], "清理門戶策略轉向")
        self.assertEqual(result["trades"][0]["action"], "買")

    def test_laoyutou_trade_reason_optional(self):
        out = self.store.save_laoyutou_trade(
            "2454", "聯發科", "賣", 500, 1200.0, "2026-07-21")
        self.assertTrue(out["saved"])
        result = self.store.get_laoyutou_trades(code="2454")
        self.assertIsNone(result["trades"][0]["reason"])

    def test_laoyutou_trade_get_by_code_sorted_date_desc(self):
        self.store.save_laoyutou_trade("2330", "台積電", "買", 1000, 900.0, "2026-07-01")
        self.store.save_laoyutou_trade("2330", "台積電", "買", 500, 950.0, "2026-07-15")
        self.store.save_laoyutou_trade("2330", "台積電", "賣", 200, 980.0, "2026-07-10")
        result = self.store.get_laoyutou_trades(code="2330")
        dates = [t["date"] for t in result["trades"]]
        self.assertEqual(dates, ["2026-07-15", "2026-07-10", "2026-07-01"])

    def test_laoyutou_trade_get_without_code_lists_recent_across_stocks(self):
        self.store.save_laoyutou_trade("2330", "台積電", "買", 1000, 900.0, "2026-07-01")
        self.store.save_laoyutou_trade("2454", "聯發科", "賣", 500, 1200.0, "2026-07-15")
        result = self.store.get_laoyutou_trades()
        self.assertIsNone(result["code"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["trades"][0]["code"], "2454")

    def test_laoyutou_trade_get_without_code_respects_limit(self):
        for i in range(5):
            self.store.save_laoyutou_trade(
                "2330", "台積電", "買", 100, 900.0, "2026-07-%02d" % (i + 1))
        result = self.store.get_laoyutou_trades(limit=2)
        self.assertEqual(result["count"], 2)

    def test_laoyutou_trade_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_laoyutou_trade(
                "2330", "台積電", "持有", 1000, 900.0, "2026-07-01")

    def test_trade_ledger_save_and_get(self):
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01", add_sequence=1)
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 500, 950.0, "2026-07-10", add_sequence=2)
        result = self.store.get_trade_ledger("2330")
        self.assertEqual(result["count"], 2)
        sequences = [e["add_sequence"] for e in result["entries"]]
        self.assertEqual(sequences, [1, 2])

    def test_trade_ledger_sell_forces_add_sequence_null(self):
        out = self.store.save_trade_ledger_entry(
            "2330", "台積電", "賣", 300, 980.0, "2026-07-15", add_sequence=3)
        self.assertIsNone(out["add_sequence"])
        result = self.store.get_trade_ledger("2330")
        self.assertIsNone(result["entries"][0]["add_sequence"])

    def test_trade_ledger_buy_without_add_sequence_defaults_none(self):
        out = self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01")
        self.assertIsNone(out["add_sequence"])

    def test_trade_ledger_ordered_oldest_first(self):
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 500, 950.0, "2026-07-10", add_sequence=2)
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01", add_sequence=1)
        result = self.store.get_trade_ledger("2330")
        dates = [e["date"] for e in result["entries"]]
        self.assertEqual(dates, ["2026-07-01", "2026-07-10"])

    def test_trade_ledger_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_trade_ledger_entry(
                "2330", "台積電", "持有", 1000, 900.0, "2026-07-01")

    def test_trade_ledger_order_ref_saved_and_retrievable(self):
        """order_ref（委託書號，2026-07-31新增）要能正確存入並讀出。"""
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01",
            add_sequence=1, order_ref="k09QI")
        result = self.store.get_trade_ledger("2330")
        self.assertEqual(result["entries"][0]["order_ref"], "k09QI")

    def test_trade_ledger_order_ref_defaults_to_none(self):
        """沒有傳order_ref的呼叫（既有呼叫端）要維持相容，值是NULL/None。"""
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01", add_sequence=1)
        result = self.store.get_trade_ledger("2330")
        self.assertIsNone(result["entries"][0]["order_ref"])

    def test_trade_ledger_order_ref_exists_true_when_present(self):
        self.store.save_trade_ledger_entry(
            "2330", "台積電", "買", 1000, 900.0, "2026-07-01", order_ref="k09QI")
        self.assertTrue(self.store.trade_ledger_order_ref_exists("k09QI"))

    def test_trade_ledger_order_ref_exists_false_when_absent(self):
        self.assertFalse(self.store.trade_ledger_order_ref_exists("k09QI"))

    def test_trade_ledger_order_ref_exists_false_for_none_or_empty(self):
        """None／空字串都是「無法判斷」，防禦性回傳False（不誤擋）。"""
        self.assertFalse(self.store.trade_ledger_order_ref_exists(None))
        self.assertFalse(self.store.trade_ledger_order_ref_exists(""))

    def test_trade_ledger_migrates_old_schema_without_order_ref(self):
        """回歸測試：模擬2026-07-31之前建的、沒有order_ref欄位的既有
        trade_ledger表（正式環境alphavibe.db目前19筆既有資料的實況），
        確認KBStore開啟時能安全遷移：既有資料列不消失，新欄位能正常寫入。"""
        tmp = tempfile.mkdtemp(prefix="alphavibe-trade-ledger-migration-test-")
        try:
            db_path = os.path.join(tmp, "alphavibe.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE trade_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    name TEXT,
                    action TEXT NOT NULL,
                    add_sequence INTEGER,
                    shares REAL,
                    price REAL,
                    date TEXT NOT NULL,
                    source_ref TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO trade_ledger (code, name, action, add_sequence,"
                " shares, price, date, source_ref, created_at)"
                " VALUES ('2330', '台積電', '買', 1, 1000, 900.0,"
                " '2026-07-01', NULL, '2026-07-01T00:00:00')")
            conn.commit()
            conn.close()

            store = KBStore(tmp)
            try:
                cols = {row["name"] for row in
                        store.conn.execute("PRAGMA table_info(trade_ledger)")}
                self.assertIn("order_ref", cols)

                old_entry = store.get_trade_ledger("2330")["entries"][0]
                self.assertIsNone(old_entry["order_ref"])
                self.assertEqual(old_entry["code"], "2330")

                # 遷移後新欄位能正常寫入。
                store.save_trade_ledger_entry(
                    "2330", "台積電", "買", 500, 950.0, "2026-07-10",
                    add_sequence=2, order_ref="k09QI")
                self.assertTrue(store.trade_ledger_order_ref_exists("k09QI"))
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp)

    def _market_scan_row(self, code, peg=0.5, meets=True, error=None):
        return {"code": code, "name": "測試股%s" % code, "market": "TWSE",
                "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.2,
                "revenue_period": "2026-06", "drawdown_pct": 0.45, "high_price": 100.0,
                "high_date": "2026-06-01", "current_price": 55.0, "current_date": "2026-07-20",
                "peg": peg, "meets_framework": meets, "error": error}

    def test_market_scan_run_roundtrip(self):
        rows = [self._market_scan_row("2330", peg=0.5, meets=True),
                self._market_scan_row("2454", peg=None, meets=False, error="非預期錯誤：boom")]
        saved = self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "manual", rows, candidate_count=2,
            market_errors={"TWSE": None, "TPEx": "TPEx 呼叫失敗：逾時"},
            total_scanned=1973)
        self.assertTrue(saved["run_id"])
        self.assertEqual(saved["meets_count"], 1)

        latest = self.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertTrue(latest["found"])
        self.assertEqual(latest["run"]["candidate_count"], 2)
        self.assertEqual(latest["run"]["meets_count"], 1)
        self.assertEqual(latest["run"]["twse_error"], None)
        self.assertEqual(latest["run"]["tpex_error"], "TPEx 呼叫失敗：逾時")
        self.assertEqual(latest["run"]["total_scanned"], 1973)
        self.assertEqual(len(latest["results"]), 2)
        codes = [r["code"] for r in latest["results"]]
        self.assertIn("2330", codes)
        self.assertIn("2454", codes)

    def test_market_scan_run_total_scanned_defaults_to_none(self):
        """呼叫端不傳total_scanned時（例如舊呼叫端還沒更新）要能正常存，
        存成NULL，不強制要求、不報錯。"""
        saved = self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "manual",
            [self._market_scan_row("2330")], candidate_count=1)
        self.assertTrue(saved["run_id"])
        latest = self.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertIsNone(latest["run"]["total_scanned"])

    def test_market_scan_get_latest_picks_most_recent_run(self):
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [self._market_scan_row("1111")], candidate_count=1)
        # run_at 精度只到秒，兩筆可能同一秒存入；查詢用 id DESC 當第二排序鍵
        # 保證仍能正確挑出「後存入」的那筆，不需要真的等待跨秒。
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "manual",
            [self._market_scan_row("2222")], candidate_count=1)

        latest = self.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertEqual(latest["results"][0]["code"], "2222")
        self.assertEqual(latest["run"]["trigger_source"], "manual")

    def test_market_scan_get_latest_filters_by_framework(self):
        self.store.save_market_scan_run(
            "framework_a", "manual", [self._market_scan_row("1111")], candidate_count=1)
        self.store.save_market_scan_run(
            "framework_b", "manual", [self._market_scan_row("2222")], candidate_count=1)

        latest_a = self.store.get_latest_market_scan("framework_a")
        self.assertEqual(latest_a["results"][0]["code"], "1111")
        latest_b = self.store.get_latest_market_scan("framework_b")
        self.assertEqual(latest_b["results"][0]["code"], "2222")

    def test_market_scan_get_latest_no_runs_yet(self):
        out = self.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertEqual(out, {"found": False, "run": None, "results": []})

    def test_market_scan_run_with_empty_rows(self):
        """兩邊資料源都失敗、篩不出任何候選時也要能正常存查，不出錯。"""
        saved = self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled", [], candidate_count=0,
            market_errors={"TWSE": "TWSE 呼叫失敗", "TPEx": "TPEx 呼叫失敗"})
        self.assertTrue(saved["run_id"])
        self.assertEqual(saved["meets_count"], 0)
        latest = self.store.get_latest_market_scan("peg_deep_dip_concentration")
        self.assertEqual(latest["results"], [])
        self.assertEqual(latest["run"]["twse_error"], "TWSE 呼叫失敗")

    def test_get_market_scan_run_found_and_not_found(self):
        saved = self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "manual",
            [self._market_scan_row("3135")], candidate_count=1, total_scanned=1973)
        run = self.store.get_market_scan_run(saved["run_id"])
        self.assertIsNotNone(run)
        self.assertEqual(run["framework_id"], "peg_deep_dip_concentration")
        self.assertEqual(run["total_scanned"], 1973)
        self.assertIsNone(self.store.get_market_scan_run(999999))

    def test_get_market_scan_result_found_and_not_found(self):
        saved = self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "manual",
            [self._market_scan_row("3135", peg=0.16), self._market_scan_row("2222", peg=3.0)],
            candidate_count=2)
        row = self.store.get_market_scan_result(saved["run_id"], "3135")
        self.assertIsNotNone(row)
        self.assertEqual(row["code"], "3135")
        self.assertAlmostEqual(row["peg"], 0.16)
        # 查無這個run_id裡的這個代碼
        self.assertIsNone(self.store.get_market_scan_result(saved["run_id"], "9999"))
        # 查無這個run_id
        self.assertIsNone(self.store.get_market_scan_result(999999, "3135"))

    def test_market_scan_runs_migrates_old_schema_without_total_scanned(self):
        """回歸測試：`CREATE TABLE IF NOT EXISTS` 對已存在的表不會補新欄位。
        這裡手動模擬「舊版本建的、沒有 total_scanned 欄位的既有資料庫」
        （這正是正式環境 poc/data/alphavibe.db 這次功能上線後的實際狀況），
        確認 KBStore 開啟時能安全遷移：既有資料列不消失，新欄位能正常寫入。
        """
        tmp = tempfile.mkdtemp(prefix="alphavibe-migration-test-")
        try:
            db_path = os.path.join(tmp, "alphavibe.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE market_scan_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    framework_id TEXT NOT NULL,
                    trigger_source TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL,
                    meets_count INTEGER NOT NULL,
                    twse_error TEXT,
                    tpex_error TEXT,
                    run_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO market_scan_runs (framework_id, trigger_source,"
                " candidate_count, meets_count, run_at)"
                " VALUES ('peg_deep_dip_concentration', 'scheduled', 5, 1,"
                " '2026-07-21T02:00:00')")
            conn.commit()
            conn.close()

            store = KBStore(tmp)
            try:
                cols = {row["name"] for row in
                        store.conn.execute("PRAGMA table_info(market_scan_runs)")}
                self.assertIn("total_scanned", cols)

                old_row = store.conn.execute(
                    "SELECT * FROM market_scan_runs WHERE candidate_count=5"
                ).fetchone()
                self.assertIsNotNone(old_row, "舊資料列在遷移後消失了")
                self.assertEqual(old_row["framework_id"], "peg_deep_dip_concentration")
                self.assertIsNone(old_row["total_scanned"])

                saved = store.save_market_scan_run(
                    "peg_deep_dip_concentration", "manual",
                    [self._market_scan_row("2330")], candidate_count=1,
                    total_scanned=1973)
                self.assertTrue(saved["run_id"])
                new_row = store.conn.execute(
                    "SELECT total_scanned FROM market_scan_runs WHERE id=?",
                    (saved["run_id"],)).fetchone()
                self.assertEqual(new_row["total_scanned"], 1973)

                total_rows = store.conn.execute(
                    "SELECT COUNT(*) c FROM market_scan_runs").fetchone()["c"]
                self.assertEqual(total_rows, 2)  # 舊的1筆+新存的1筆，沒有被清空
            finally:
                store.close()
        finally:
            shutil.rmtree(tmp)

    # ---------- 模組D檢視結果表（FR-051~055/057） ----------

    def test_save_and_get_module_d_result_by_code(self):
        saved = self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="年增率連續3個月下滑：40%→30%→20%")
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["trigger_type"], "通用層")
        self.assertIsNotNone(saved["checked_at"])

        got = self.store.get_module_d_results(code="2330")
        self.assertEqual(got["code"], "2330")
        self.assertIsNone(got["date"])
        self.assertEqual(got["count"], 1)
        row = got["results"][0]
        self.assertEqual(row["trigger_type"], "通用層")
        self.assertIsNone(row["strategy_id"])
        self.assertIsNone(row["suggested_action"])
        self.assertEqual(row["conflict_flag"], 0)
        self.assertEqual(row["concern_flag"], 0)  # 預設False，見_MIGRATIONS註解

    def test_save_module_d_result_with_concern_flag(self):
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="下檔風險偏高",
            concern_flag=True)
        row = self.store.get_module_d_results(code="2330")["results"][0]
        self.assertEqual(row["concern_flag"], 1)

    def test_save_module_d_result_with_strategy_and_suggested_action(self):
        self.store.save_module_d_result(
            code="2330", trigger_type="策略層", strategy_id="peg_deep_dip_concentration",
            finding="PEG已回升至1.15（門檻1.0）", suggested_action="建議減碼",
            conflict_flag=True, checked_at="2026-07-29T02:00:00")
        row = self.store.get_module_d_results(code="2330")["results"][0]
        self.assertEqual(row["strategy_id"], "peg_deep_dip_concentration")
        self.assertEqual(row["suggested_action"], "建議減碼")
        self.assertEqual(row["conflict_flag"], 1)
        self.assertEqual(row["checked_at"], "2026-07-29T02:00:00")

    def test_save_module_d_result_rejects_invalid_trigger_type(self):
        with self.assertRaises(ValueError):
            self.store.save_module_d_result(
                code="2330", trigger_type="不存在的類型", finding="x")

    def test_save_module_d_result_requires_code_and_finding(self):
        with self.assertRaises(ValueError):
            self.store.save_module_d_result(code="", trigger_type="通用層", finding="x")
        with self.assertRaises(ValueError):
            self.store.save_module_d_result(code="2330", trigger_type="通用層", finding="")

    def test_get_module_d_results_by_date_without_code(self):
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="今天檢查A",
            checked_at="2026-07-29T02:00:00")
        self.store.save_module_d_result(
            code="6805", trigger_type="老芋頭動向", finding="今天檢查B",
            checked_at="2026-07-29T02:05:00")
        self.store.save_module_d_result(
            code="2454", trigger_type="通用層", finding="昨天檢查",
            checked_at="2026-07-28T02:00:00")

        today = self.store.get_module_d_results(date="2026-07-29")
        self.assertIsNone(today["code"])
        self.assertEqual(today["date"], "2026-07-29")
        self.assertEqual(today["count"], 2)
        codes = {r["code"] for r in today["results"]}
        self.assertEqual(codes, {"2330", "6805"})

        yesterday = self.store.get_module_d_results(date="2026-07-28")
        self.assertEqual(yesterday["count"], 1)
        self.assertEqual(yesterday["results"][0]["code"], "2454")

    def test_get_module_d_results_empty_when_nothing_recorded(self):
        out = self.store.get_module_d_results(code="9999")
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["results"], [])

    def test_get_associated_frameworks_returns_matching_framework_ids(self):
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [self._market_scan_row("2330", peg=0.5, meets=True)], candidate_count=1)
        self.store.save_market_scan_run(
            "revenue_high_price_dip", "scheduled",
            [self._market_scan_row("2330", peg=None, meets=True)], candidate_count=1)
        associated = self.store.get_associated_frameworks("2330")
        self.assertEqual(sorted(associated),
                         ["peg_deep_dip_concentration", "revenue_high_price_dip"])

    def test_get_associated_frameworks_excludes_non_meeting_rows(self):
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [self._market_scan_row("2330", peg=3.0, meets=False)], candidate_count=1)
        self.assertEqual(self.store.get_associated_frameworks("2330"), [])

    def test_get_associated_frameworks_never_scanned_returns_empty_list(self):
        """從沒被market_scan篩中過的標的（PO手動加入觀察名單、或老芋頭訊號
        帶進來的）回傳空list，這是正常情況，不是錯誤。"""
        self.assertEqual(self.store.get_associated_frameworks("9999"), [])

    def test_get_associated_frameworks_keeps_matching_even_after_later_run_drops_it(self):
        """關鍵行為：即使「最新一次」該框架的run裡這支代碼已經不再符合門檻
        （策略假說開始失效正是最需要繼續檢查invalidation的時候），仍要保留
        關聯——不能因為最新run不再meets就讓策略關聯判斷清空。"""
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [self._market_scan_row("2330", peg=0.5, meets=True)], candidate_count=1)
        self.store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [self._market_scan_row("2330", peg=1.2, meets=False)], candidate_count=1)
        self.assertEqual(self.store.get_associated_frameworks("2330"),
                         ["peg_deep_dip_concentration"])

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

    def test_get_stock_info_parses_mocked_payload(self):
        payload = [
            {"industry_category": "半導體業", "stock_id": "2330",
             "stock_name": "台積電", "type": "twse", "date": "2026-07-18"},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockInfo")
            self.assertIsNone(start_date)
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_stock_info("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["stocks"]), 1)
        self.assertEqual(out["stocks"][0]["industry_category"], "半導體業")
        self.assertEqual(out["stocks"][0]["stock_name"], "台積電")

    def test_get_stock_info_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_stock_info("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("stocks", out)

    def test_get_stock_price_history_parses_mocked_payload(self):
        payload = [
            {"date": "2026-07-08", "stock_id": "2330", "Trading_Volume": 25519599,
             "Trading_money": 62400639776, "open": 2445.0, "max": 2465.0,
             "min": 2420.0, "close": 2465.0, "spread": 25.0, "Trading_turnover": 94688},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockPrice")
            self.assertIsNotNone(start_date)
            self.assertIsNotNone(end_date)
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_stock_price_history("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["prices"]), 1)
        self.assertEqual(out["prices"][0]["close"], 2465.0)
        self.assertEqual(out["prices"][0]["Trading_Volume"], 25519599)

    def test_get_stock_price_history_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_stock_price_history("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("prices", out)

    def test_get_revenue_yoy_calculates_growth(self):
        payload = [
            {"date": "2025-06-01", "stock_id": "2330", "revenue": 200000,
             "revenue_month": 5, "revenue_year": 2025},
            {"date": "2025-07-01", "stock_id": "2330", "revenue": 100000,
             "revenue_month": 6, "revenue_year": 2025},
            {"date": "2026-07-01", "stock_id": "2330", "revenue": 150000,
             "revenue_month": 6, "revenue_year": 2026},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockMonthRevenue")
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_revenue_yoy("2330")
        self.assertEqual(out["errors"], [])
        by_ym = {(r["revenue_year"], r["revenue_month"]): r for r in out["revenue_yoy"]}
        # 2026/6 對比 2025/6：(150000-100000)/100000 = 0.5
        self.assertAlmostEqual(by_ym[(2026, 6)]["yoy_growth"], 0.5)
        # 2025/5 沒有 2024/5 資料可比對，年增率應為 null
        self.assertIsNone(by_ym[(2025, 5)]["yoy_growth"])
        # 2025/6 沒有 2024/6 資料可比對，年增率應為 null
        self.assertIsNone(by_ym[(2025, 6)]["yoy_growth"])

    def test_get_revenue_yoy_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_revenue_yoy("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("revenue_yoy", out)

    def test_get_institutional_trading_sums_foreign_net(self):
        # name 值為 2026-07-18 對 2330 實測 FinMind API 確認的真實分類字串
        payload = [
            {"date": "2026-07-13", "stock_id": "2330", "name": "Foreign_Investor",
             "buy": 16267509, "sell": 29016050},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Foreign_Dealer_Self",
             "buy": 0, "sell": 0},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Investment_Trust",
             "buy": 361457, "sell": 318232},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Dealer_self",
             "buy": 392405, "sell": 391500},
            {"date": "2026-07-13", "stock_id": "2330", "name": "Dealer_Hedging",
             "buy": 636358, "sell": 547400},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockInstitutionalInvestorsBuySell")
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_institutional_trading("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["trading"]), 5)
        # foreign_net = Foreign_Investor(16267509-29016050) + Foreign_Dealer_Self(0-0)
        self.assertEqual(out["foreign_net"], 16267509 - 29016050)

    def test_get_institutional_trading_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_institutional_trading("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("trading", out)

    def test_get_per_history_parses_mocked_payload(self):
        payload = [
            {"date": "2024-07-01", "PER": 15.0, "PBR": 3.0, "dividend_yield": 2.5},
            {"date": "2026-07-07", "PER": 18.5, "PBR": 5.1, "dividend_yield": 2.1},
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockPER")
            self.assertIsNotNone(start_date)
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_per_history("2330")
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["per_history"]), 2)
        self.assertEqual(out["per_history"][-1]["PER"], 18.5)

    def test_get_per_history_no_data(self):
        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            return {"data": []}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_per_history("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("per_history", out)

    def test_get_per_history_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_per_history("2330")
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("per_history", out)

    def test_get_equity_attributable_to_owners_picks_latest_by_date(self):
        payload = [
            {"date": "2025-06-30", "stock_id": "6826",
             "type": "EquityAttributableToOwnersOfParent", "value": 6003920000.0},
            {"date": "2025-12-31", "stock_id": "6826",
             "type": "EquityAttributableToOwnersOfParent", "value": 7505428000.0},
            {"date": "2025-12-31", "stock_id": "6826",
             "type": "Equity", "value": 8000000000.0},  # 不同 type，應被濾掉
        ]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            self.assertEqual(dataset, "TaiwanStockBalanceSheet")
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_equity_attributable_to_owners("6826")
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["equity"], 7505428000.0)
        self.assertEqual(out["equity_date"], "2025-12-31")

    def test_get_equity_attributable_to_owners_no_matching_type(self):
        payload = [{"date": "2025-12-31", "stock_id": "6826", "type": "Equity", "value": 1.0}]

        def fake_fetch(dataset, stock_id, start_date, token, end_date=None):
            return {"data": payload}

        with unittest.mock.patch.object(finmind_client, "_fetch", fake_fetch):
            out = finmind_client.get_equity_attributable_to_owners("6826")
        self.assertIsNone(out["equity"])
        self.assertEqual(len(out["errors"]), 1)

    def test_get_equity_attributable_to_owners_api_failure(self):
        def fail(dataset, stock_id, start_date, token, end_date=None):
            return {"error": "FinMind 呼叫失敗（%s）：模擬斷網" % dataset}

        with unittest.mock.patch.object(finmind_client, "_fetch", fail):
            out = finmind_client.get_equity_attributable_to_owners("6826")
        self.assertIsNone(out["equity"])
        self.assertEqual(len(out["errors"]), 1)


class TPExClientTest(unittest.TestCase):
    """興櫃股估值粗估：mock TPEx 三端點＋FinMind 淨值，不打真實網路。"""

    LATEST_STATISTICS = [
        {"Date": "1150717", "SecuritiesCompanyCode": "6826",
         "CompanyName": "和淞", "LatestPrice": "506"},
        {"Date": "1150717", "SecuritiesCompanyCode": "1260",
         "CompanyName": "富味鄉", "LatestPrice": "24.2"},
    ]
    EPS_RANK = [
        {"Date": "1150719", "Rank": "1", "SecuritiesCompanyCode": "6826",
         "CompanyName": "和淞", "EPS": "27.33"},
    ]
    CAPITALS_RANK = [
        {"Date": "1150719", "Rank": "50", "SecuritiesCompanyCode": "6826",
         "CompanyName": "和淞", "Capital": "855.4"},
    ]

    def _mock_endpoints(self, latest=None, eps=None, capitals=None):
        latest = self.LATEST_STATISTICS if latest is None else latest
        eps = self.EPS_RANK if eps is None else eps
        capitals = self.CAPITALS_RANK if capitals is None else capitals

        def fake_fetch(endpoint_key):
            return {"data": {
                "latest_statistics": latest,
                "eps_rank": eps,
                "capitals_rank": capitals,
            }[endpoint_key]}
        return fake_fetch

    def test_roc_date_to_iso_valid(self):
        self.assertEqual(tpex_client.roc_date_to_iso("1150717"), "2026-07-17")
        self.assertEqual(tpex_client.roc_date_to_iso("1150719"), "2026-07-19")
        self.assertEqual(tpex_client.roc_date_to_iso("1000101"), "2011-01-01")

    def test_roc_date_to_iso_invalid_format_returns_none(self):
        self.assertIsNone(tpex_client.roc_date_to_iso(""))
        self.assertIsNone(tpex_client.roc_date_to_iso(None))
        self.assertIsNone(tpex_client.roc_date_to_iso("115071"))    # 少一碼
        self.assertIsNone(tpex_client.roc_date_to_iso("11507171"))  # 多一碼
        self.assertIsNone(tpex_client.roc_date_to_iso("abcdefg"))   # 非數字
        self.assertIsNone(tpex_client.roc_date_to_iso("1150732"))   # 32 日不存在
        self.assertIsNone(tpex_client.roc_date_to_iso("1150013"))   # 00 月不存在

    def test_normal_calculates_per_and_pbr(self):
        with unittest.mock.patch.object(tpex_client, "_fetch", self._mock_endpoints()), \
             unittest.mock.patch.object(
                 finmind_client, "get_equity_attributable_to_owners",
                 return_value={"equity": 7505428000.0, "equity_date": "2025-12-31",
                               "errors": []}):
            out = tpex_client.get_emerging_stock_valuation("6826")

        self.assertEqual(out["stock_id"], "6826")
        self.assertEqual(out["name"], "和淞")
        self.assertEqual(out["price"], 506.0)
        self.assertEqual(out["price_date"], "2026-07-17")
        self.assertEqual(out["eps"], 27.33)
        self.assertEqual(out["eps_period"], "2026-07-19")
        # PER = 506 / 27.33 ≈ 18.51（對照手動估算 18.5 倍）
        self.assertAlmostEqual(out["per"], 18.51, places=2)
        # estimated_shares = 855.4 百萬元 * 1,000,000 / 10 = 85,540,000
        self.assertAlmostEqual(out["estimated_shares"], 85_540_000)
        # book_value = 7,505,428,000 / 85,540,000 ≈ 87.75
        self.assertAlmostEqual(out["book_value"], 87.75, places=1)
        self.assertIsNotNone(out["pbr"])
        self.assertEqual(out["errors"], [])
        self.assertEqual(len(out["caveats"]), 2)
        self.assertIn("caveats", out)

    def test_eps_missing_per_is_null(self):
        with unittest.mock.patch.object(
                tpex_client, "_fetch", self._mock_endpoints(eps=[])), \
             unittest.mock.patch.object(
                 finmind_client, "get_equity_attributable_to_owners",
                 return_value={"equity": None, "equity_date": None,
                               "errors": ["查無資料"]}):
            out = tpex_client.get_emerging_stock_valuation("6826")

        self.assertIsNone(out["eps"])
        self.assertIsNone(out["per"])
        self.assertTrue(any("EPS" in e for e in out["errors"]))

    def test_eps_zero_or_negative_does_not_calculate_per(self):
        for bad_eps in ("0", "-5.2"):
            eps_rank = [{"Date": "1150719", "SecuritiesCompanyCode": "6826",
                        "CompanyName": "和淞", "EPS": bad_eps}]
            with unittest.mock.patch.object(
                    tpex_client, "_fetch", self._mock_endpoints(eps=eps_rank)), \
                 unittest.mock.patch.object(
                     finmind_client, "get_equity_attributable_to_owners",
                     return_value={"equity": None, "equity_date": None, "errors": []}):
                out = tpex_client.get_emerging_stock_valuation("6826")
            self.assertIsNone(out["per"], "EPS=%s 不應算出 PER" % bad_eps)
            self.assertTrue(any("EPS<=0" in e for e in out["errors"]))

    def test_stock_not_found_in_any_endpoint(self):
        with unittest.mock.patch.object(
                tpex_client, "_fetch",
                self._mock_endpoints(latest=[], eps=[], capitals=[])), \
             unittest.mock.patch.object(
                 finmind_client, "get_equity_attributable_to_owners",
                 return_value={"equity": None, "equity_date": None, "errors": []}):
            out = tpex_client.get_emerging_stock_valuation("9999")
        self.assertIsNone(out["price"])
        self.assertIsNone(out["per"])
        self.assertIsNone(out["pbr"])
        self.assertTrue(any("查無此代碼" in e for e in out["errors"]))

    def test_capital_missing_pbr_is_null(self):
        with unittest.mock.patch.object(
                tpex_client, "_fetch", self._mock_endpoints(capitals=[])), \
             unittest.mock.patch.object(
                 finmind_client, "get_equity_attributable_to_owners",
                 return_value={"equity": 7505428000.0, "equity_date": "2025-12-31",
                               "errors": []}):
            out = tpex_client.get_emerging_stock_valuation("6826")
        self.assertIsNone(out["estimated_shares"])
        self.assertIsNone(out["book_value"])
        self.assertIsNone(out["pbr"])
        # PER 不受影響，仍應算得出來
        self.assertIsNotNone(out["per"])

    def test_endpoint_error_is_recorded_not_raised(self):
        def fake_fetch_with_error(endpoint_key):
            if endpoint_key == "latest_statistics":
                return {"error": "TPEx 呼叫失敗（latest_statistics）：模擬斷網"}
            return {"data": {
                "eps_rank": self.EPS_RANK,
                "capitals_rank": self.CAPITALS_RANK,
            }[endpoint_key]}

        with unittest.mock.patch.object(tpex_client, "_fetch", fake_fetch_with_error), \
             unittest.mock.patch.object(
                 finmind_client, "get_equity_attributable_to_owners",
                 return_value={"equity": 7505428000.0, "equity_date": "2025-12-31",
                               "errors": []}):
            out = tpex_client.get_emerging_stock_valuation("6826")
        self.assertIsNone(out["price"])
        self.assertIn("TPEx 呼叫失敗（latest_statistics）：模擬斷網", out["errors"])
        # 沒有 price，PER 仍不應計算
        self.assertIsNone(out["per"])


HOLDINGS_REPORT_SAMPLE = """\
------ ------------------------------集 保------------------------------ ------------------------------融 資------------------------------ ------------------------------融 券------------------------------ 庫 存 ------------------------本日評估----------------------

股票代號 名稱 零股 昨日可用 本日買進 前日買進 本日賣出 本日可用 昨日可用 本日買進 前日買進 本日賣出 本日可用 昨日可用 本日買進 前日買進 本日賣出 本日可用 總 市 值 現股市值 信用市值 總市值 收盤價

庫 存 庫 存 庫 存 庫 存 庫 存 庫 存

------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
1785 光洋科 150 16,125 16,125 16,125 107.50
2308 台達電 10 17,400 17,400 17,400 1,740.00
2337 旺宏 400 50,000 50,000 50,000 125.00
2345 智邦 5 10,450 10,450 10,450 2,090.00
2441 超豐 70 8,855 8,855 8,855 126.50
2449 京元電子 40 11,460 11,460 11,460 286.50
3008 大立光 5 20,050 20,050 20,050 4,010.00
3081 聯亞 8 11,840 11,840 11,840 1,480.00
3357 臺慶科 50 10,900 10,900 10,900 218.00
3661 世芯-KY 5 17,400 17,400 17,400 3,480.00
4749 新應材 5 3,985 3,985 3,985 797.00
4931 新盛力 350 69,650 69,650 69,650 199.00
5425 台半 50 4,625 4,625 4,625 92.50
6196 帆宣 5 2,710 2,710 2,710 542.00
6257 矽格 100 21,450 21,450 21,450 214.50
6449 鈺邦 15 3,810 3,810 3,810 254.00
6725 矽科宏晟 40 12,000 12,000 12,000 300.00
6757 台灣虎航 1 56 56 56 56.20
6826 *和淞 270 138,342 83,005 83,005 512.38
7769 鴻勁 7 42,490 42,490 42,490 6,070.00
9938 百和 800 36,680 36,680 36,680 45.85
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
總計: 510,278 454,941 454,941
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
註: *:表示興櫃股票、$:表示全額股票、#:表示處置股票、!:表注意 股票

印表日期: 115/07/19 072057
"""

EXPECTED_HOLDINGS_ROWS = [
    {"code": "1785", "name": "光洋科", "shares": 150, "is_emerging": False},
    {"code": "2308", "name": "台達電", "shares": 10, "is_emerging": False},
    {"code": "2337", "name": "旺宏", "shares": 400, "is_emerging": False},
    {"code": "2345", "name": "智邦", "shares": 5, "is_emerging": False},
    {"code": "2441", "name": "超豐", "shares": 70, "is_emerging": False},
    {"code": "2449", "name": "京元電子", "shares": 40, "is_emerging": False},
    {"code": "3008", "name": "大立光", "shares": 5, "is_emerging": False},
    {"code": "3081", "name": "聯亞", "shares": 8, "is_emerging": False},
    {"code": "3357", "name": "臺慶科", "shares": 50, "is_emerging": False},
    {"code": "3661", "name": "世芯-KY", "shares": 5, "is_emerging": False},
    {"code": "4749", "name": "新應材", "shares": 5, "is_emerging": False},
    {"code": "4931", "name": "新盛力", "shares": 350, "is_emerging": False},
    {"code": "5425", "name": "台半", "shares": 50, "is_emerging": False},
    {"code": "6196", "name": "帆宣", "shares": 5, "is_emerging": False},
    {"code": "6257", "name": "矽格", "shares": 100, "is_emerging": False},
    {"code": "6449", "name": "鈺邦", "shares": 15, "is_emerging": False},
    {"code": "6725", "name": "矽科宏晟", "shares": 40, "is_emerging": False},
    {"code": "6757", "name": "台灣虎航", "shares": 1, "is_emerging": False},
    {"code": "6826", "name": "和淞", "shares": 270, "is_emerging": True},
    {"code": "7769", "name": "鴻勁", "shares": 7, "is_emerging": False},
    {"code": "9938", "name": "百和", "shares": 800, "is_emerging": False},
]


class HoldingsParserTest(unittest.TestCase):
    def test_parses_real_sample_all_21_rows(self):
        out = holdings_parser.parse_holdings_report(HOLDINGS_REPORT_SAMPLE)
        self.assertEqual(out["total_parsed"], 21)
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(len(out["rows"]), 21)
        for got, expected in zip(out["rows"], EXPECTED_HOLDINGS_ROWS):
            self.assertEqual(got, expected)

    def test_emerging_stock_star_prefix_stripped_and_flagged(self):
        out = holdings_parser.parse_holdings_report(HOLDINGS_REPORT_SAMPLE)
        by_code = {r["code"]: r for r in out["rows"]}
        self.assertEqual(by_code["6826"]["name"], "和淞")
        self.assertTrue(by_code["6826"]["is_emerging"])
        self.assertFalse(by_code["1785"]["is_emerging"])

    def test_headers_separators_and_footer_lines_are_skipped(self):
        text = "\n".join([
            "股票代號 名稱 零股 昨日可用 總 市 值 收盤價",
            "庫 存 庫 存",
            "-" * 20,
            "總計: 510,278 454,941 454,941",
            "註: *:表示興櫃股票、$:表示全額股票",
            "印表日期: 115/07/19 072057",
            "",
            "   ",
        ])
        out = holdings_parser.parse_holdings_report(text)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["unparsed_lines"], [])
        self.assertEqual(out["total_parsed"], 0)

    def test_malformed_data_like_line_goes_to_unparsed_not_dropped(self):
        text = "\n".join([
            "1785 光洋科 150 16,125 16,125 16,125 107.50",
            "8888 怪異格式列缺股數欄",
            "2308 台達電 10 17,400 17,400 17,400 1,740.00",
        ])
        out = holdings_parser.parse_holdings_report(text)
        self.assertEqual(out["total_parsed"], 2)
        self.assertEqual([r["code"] for r in out["rows"]], ["1785", "2308"])
        self.assertEqual(out["unparsed_lines"],
                         ["8888 怪異格式列缺股數欄"])

    def test_empty_text(self):
        out = holdings_parser.parse_holdings_report("")
        self.assertEqual(out, {"rows": [], "unparsed_lines": [], "total_parsed": 0})


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
                         "save_philosophy", "get_philosophy", "get_fundamentals",
                         "save_stock_theme", "get_stock_theme"):
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
