"""report.py 測試：有資料／空資料／HTML 跳脫。"""
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import frameworks  # noqa: E402
import report  # noqa: E402
import screener  # noqa: E402
from kb_store import KBStore  # noqa: E402


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-report-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _generate(self):
        out = os.path.join(self.tmp, "report.html")
        code = report.main(["--data-dir", self.tmp, "--out", out])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            return fh.read()

    def test_report_with_data(self):
        store = KBStore(self.tmp)
        store.save_stance("2330", "偏多", name="台積電",
                          entry_condition="900 以下分批",
                          valuation_metric="PER 20 以下", source_ref="conv#1")
        store.save_comment("大盤量縮整理，觀望 FOMC", source_tag="conversation",
                           symbols="TAIEX")
        store.save_philosophy("yuzhiyu", "# 低 PER 高殖利率")
        store.close()

        page = self._generate()
        self.assertIn("台積電", page)
        self.assertIn("900 以下分批", page)
        self.assertIn("#c92a2a", page)  # 偏多＝紅（台股慣例）
        self.assertIn("大盤量縮整理", page)
        self.assertIn("yuzhiyu", page)
        self.assertIn("立場 1 檔", page)

    def test_report_empty_db(self):
        page = self._generate()
        self.assertIn("尚無立場資料", page)
        self.assertIn("尚無評論資料", page)
        self.assertIn("立場 0 檔", page)

    def test_report_shows_theme_concentration(self):
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "3661", "name": "世芯-KY", "shares": 100, "avg_cost": 2000},
            {"code": "2454", "name": "聯發科", "shares": 100, "avg_cost": 1000},
        ])
        store.upsert_stock_price("3661", 3000, "2026-07-24")
        store.upsert_stock_price("2454", 1000, "2026-07-24")
        store.save_stock_theme("3661", "AI CAPEX")
        store.close()

        page = self._generate()
        self.assertIn("主題集中度", page)
        self.assertIn("AI CAPEX", page)
        # 3661 市值 30 萬、2454 市值 10 萬，總市值 40 萬，AI CAPEX 佔 75%
        self.assertIn("75.0%", page)
        # 2454 沒標主題，跟其他缺值欄位一樣顯示 —，不計入任何主題小計
        self.assertIn(
            '<td data-label="投資主題">—</td>', page)

    def test_main_page_links_to_screen_feature(self):
        """主檢視頁要有連到 /screen 的入口，不能只有直接打 URL 才進得去
        （2026-07-22 使用者手機上找不到第一層篩選功能，就是漏了這個入口）。"""
        page = self._generate()
        self.assertIn("href=\"/screen\"", page)

    def test_toc_and_collapsible_sections(self):
        # 5 個區塊各自的預期狀態：True＝預設展開（有 open 屬性）
        expected_open = {
            "section-stance": True,
            "section-snapshots": True,
            "section-holdings": True,
            "section-comments": False,  # 近期評論預設收合，縮短預設頁面長度
            "section-philosophy": True,
        }

        page = self._generate()

        # 目錄的 5 個錨點連結
        toc_match = re.search(r"<nav class=\"toc\">(.*?)</nav>", page, re.S)
        self.assertIsNotNone(toc_match, "找不到目錄 <nav class=\"toc\">")
        toc_hrefs = re.findall(r'href="#([^"]+)"', toc_match.group(1))

        # id 值不重複，且與目錄一一對應
        self.assertEqual(len(toc_hrefs), len(set(toc_hrefs)), "目錄連結 id 有重複")
        self.assertEqual(set(toc_hrefs), set(expected_open.keys()))

        section_ids_in_page = re.findall(
            r'<details class="section" id="([^"]+)"', page)
        self.assertEqual(len(section_ids_in_page), len(set(section_ids_in_page)),
                          "區塊 id 有重複")
        self.assertEqual(set(section_ids_in_page), set(expected_open.keys()))

        # 目錄連結與區塊 id 逐一 match（不只驗數量）
        for section_id in expected_open:
            self.assertIn(section_id, toc_hrefs,
                          "目錄缺少 #%s 的連結" % section_id)

        # id 必須放在 <details> 標籤本身，且 open 狀態要符合規格
        for section_id, should_be_open in expected_open.items():
            tag_match = re.search(
                r'<details class="section" id="%s"( open)?>' % re.escape(section_id),
                page)
            self.assertIsNotNone(
                tag_match, "找不到區塊 <details id=\"%s\">（可能 id 沒有放在 details 標籤上）" % section_id)
            is_open = tag_match.group(1) is not None
            self.assertEqual(
                is_open, should_be_open,
                "區塊 %s 的預設展開狀態不符：預期 open=%s，實際=%s"
                % (section_id, should_be_open, is_open))

        # 5 個標題文字都在 <summary><h2>...</h2></summary> 結構裡
        for title in ["觀察名單立場", "分析快照", "我的庫存與分析",
                      "Layer 3 最近評論", "Layer 1 哲學模組"]:
            self.assertRegex(page, r"<summary><h2>%s" % re.escape(title))

    def test_html_escaping(self):
        store = KBStore(self.tmp)
        store.save_comment("<script>alert(1)</script> 惡意內容測試",
                           source_tag="web")
        store.save_stance("2454", "偏多", reason="估值 <合理> & 便宜")
        store.close()

        page = self._generate()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;合理&gt; &amp; 便宜", page)


class ScreenPageTest(unittest.TestCase):
    """render_screen_form／render_screen_results：第一層選股篩選頁面渲染。"""

    def test_form_has_textarea_and_max_codes_hint(self):
        page = report.render_screen_form()
        self.assertIn("<form method=\"post\" action=\"/screen\">", page)
        self.assertIn("<textarea name=\"codes\"", page)
        self.assertIn(str(screener.MAX_CODES), page)

    def test_form_shows_error_message_when_given(self):
        page = report.render_screen_form(error="請至少輸入一個股票代碼")
        self.assertIn("請至少輸入一個股票代碼", page)

    def test_results_page_shows_top_level_error_without_table(self):
        page = report.render_screen_results(
            {"results": [], "total": 0, "error": "一次最多篩選 50 檔，目前輸入 60 檔，請減少數量後再試"})
        self.assertIn("一次最多篩選 50 檔", page)
        self.assertNotIn("<table>", page)

    def test_results_page_renders_rows_and_highlights_framework_hits(self):
        result = {
            "results": [
                {"code": "2330", "name": "台積電", "per": 10.0, "revenue_yoy": 0.20,
                 "drawdown_pct": 0.40, "high_price": 100.0, "high_date": "2026-06-01",
                 "current_price": 60.0, "current_date": "2026-07-01",
                 "peg": 0.5, "meets_framework": True, "error": None},
                {"code": "9999", "name": None, "per": None, "revenue_yoy": None,
                 "drawdown_pct": None, "high_price": None, "high_date": None,
                 "current_price": None, "current_date": None,
                 "peg": None, "meets_framework": False, "error": "非預期錯誤：boom"},
            ],
            "total": 2,
        }
        page = report.render_screen_results(result)
        self.assertIn("data-label=\"代碼\">2330", page)
        self.assertIn("class=\"row-highlight\"", page)  # 符合框架的列有標色
        self.assertIn("非預期錯誤：boom", page)
        self.assertIn("符合框架（PEG&lt;1 且回檔&gt;=40%）1 檔", page)

    def test_results_page_empty_list_shows_placeholder(self):
        page = report.render_screen_results({"results": [], "total": 0})
        self.assertIn("沒有輸入任何代碼", page)

    def test_results_page_html_escapes_error_message(self):
        result = {"results": [{"code": "1111", "name": None, "per": None,
                               "revenue_yoy": None, "drawdown_pct": None,
                               "high_price": None, "high_date": None,
                               "current_price": None, "current_date": None,
                               "peg": None, "meets_framework": False,
                               "error": "<script>alert(1)</script>"}],
                  "total": 1}
        page = report.render_screen_results(result)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class MarketScanPageTest(unittest.TestCase):
    """render_market_scan_page：第二層全市場批次篩選頁面渲染。

    2026-07-22 使用者回饋「目前的畫面沒有UI的考量，就算有價值高的資訊，
    也是浪費」（127檔候選塞進同一張表格，符合框架的被淹沒）後改版：
    符合框架的候選拆到獨立區塊、預設展開；全部候選收合。這裡驗證這個
    資訊架構真的照設計運作，不是只驗證資料算得對。
    """

    def _row(self, code, meets, peg=0.5, error=None):
        return {"code": code, "name": "測試股%s" % code, "market": "TWSE",
                "industry": "半導體業", "per": 10.0, "revenue_yoy": 0.2,
                "revenue_period": "2026-06", "drawdown_pct": 0.45, "high_price": 100.0,
                "high_date": "2026-06-01", "current_price": 55.0, "current_date": "2026-07-20",
                "peg": peg, "meets_framework": meets, "error": error}

    def _latest(self, rows, meets_count=None, total_scanned=None, run_id=4):
        return {"found": True,
                "run": {"id": run_id, "run_at": "2026-07-22 02:00:00",
                        "trigger_source": "scheduled",
                        "candidate_count": len(rows),
                        "meets_count": meets_count if meets_count is not None
                        else sum(1 for r in rows if r["meets_framework"]),
                        "twse_error": None, "tpex_error": None,
                        "total_scanned": total_scanned},
                "results": rows}

    def test_empty_state_when_no_scan_yet(self):
        page = report.render_market_scan_page(
            "peg_deep_dip_concentration", {"found": False, "run": None, "results": []})
        self.assertIn("尚無掃描紀錄", page)

    def test_total_scanned_shown_when_present(self):
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page(
            "peg_deep_dip_concentration", self._latest(rows, total_scanned=1973))
        self.assertIn("本次掃描全市場（上市+上櫃）共 1973 檔", page)

    def test_total_scanned_omitted_when_none(self):
        """舊資料列（遷移前存的）沒有total_scanned，不該顯示「共None檔」。"""
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page(
            "peg_deep_dip_concentration", self._latest(rows, total_scanned=None))
        self.assertNotIn("共 None 檔", page)
        self.assertNotIn("本次掃描全市場", page)

    def test_matching_rows_appear_only_in_matches_section(self):
        rows = [self._row("3135", meets=True), self._row("2222", meets=False, peg=3.0)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))

        match_section = re.search(
            r'<details class="section" open><summary><h2>符合框架的候選.*?</details>', page, re.S)
        self.assertIsNotNone(match_section, "找不到符合框架區塊，或它沒有預設展開")
        self.assertIn("3135", match_section.group(0))
        self.assertNotIn("2222", match_section.group(0))

        all_section = re.search(
            r'<details class="section"><summary><h2>全部候選.*?</details>\s*</body>', page, re.S)
        self.assertIsNotNone(all_section, "找不到全部候選區塊，或它預設展開了（應該收合）")
        self.assertIn("3135", all_section.group(0))
        self.assertIn("2222", all_section.group(0))

    def test_all_candidates_section_defaults_collapsed(self):
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        self.assertIn('<details class="section"><summary><h2>全部候選', page)
        self.assertNotIn('<details class="section" open><summary><h2>全部候選', page)

    def test_zero_matches_shows_friendly_message_not_empty_table(self):
        rows = [self._row("2222", meets=False, peg=3.0)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        self.assertIn("這次沒有候選同時符合", page)

    def test_matches_section_has_no_yellow_highlight(self):
        """符合框架區塊裡全部列都符合，畫黃底是雜訊——不該出現在那個區塊。"""
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        match_section = re.search(
            r'<details class="section" open><summary><h2>符合框架的候選.*?</details>', page, re.S)
        self.assertNotIn("class=\"row-highlight\"", match_section.group(0))

    def test_all_candidates_section_still_highlights_matches(self):
        rows = [self._row("3135", meets=True), self._row("2222", meets=False, peg=3.0)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        all_section = re.search(
            r'<details class="section"><summary><h2>全部候選.*?</details>\s*</body>', page, re.S)
        self.assertIn("class=\"row-highlight\"", all_section.group(0))

    def test_explanation_text_moved_into_collapsed_details(self):
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        self.assertIn("<summary>這是什麼？</summary>", page)
        # 說明文字要在收合details裡，不能是開頁就看到的裸段落
        self.assertNotIn('<p class="meta">用 TWSE/TPEx 官方批次資料', page)

    def test_track_form_present_for_matching_and_non_matching_rows(self):
        """2026-07-22 使用者要求：全部候選（不限符合框架的）都要有加入追蹤選項。"""
        rows = [self._row("3135", meets=True), self._row("2222", meets=False, peg=3.0)]
        page = report.render_market_scan_page(
            "peg_deep_dip_concentration", self._latest(rows, run_id=7))
        self.assertIn('name="run_id" value="7"', page)
        self.assertIn('name="code" value="3135"', page)
        self.assertIn('name="code" value="2222"', page)
        self.assertIn('action="/market-scan/track"', page)
        self.assertIn('<option value="觀察" selected>', page)


class MarketScanTrackReasonTest(unittest.TestCase):
    """compose_market_scan_track_reason：加入追蹤時的理由組字。"""

    def setUp(self):
        self.framework = frameworks.get_framework("peg_deep_dip_concentration")

    def _row(self, **overrides):
        row = {"code": "3135", "name": "凌航", "per": 8.0, "revenue_yoy": 0.5,
               "peg": 0.16, "drawdown_pct": 0.45, "high_price": 100.0,
               "high_date": "2026-06-01", "current_price": 55.0,
               "current_date": "2026-07-20", "meets_framework": True, "error": None}
        row.update(overrides)
        return row

    def test_meets_framework_includes_full_rationale(self):
        reason = report.compose_market_scan_track_reason(
            self._row(), self.framework, "2026-07-22 13:58:21")
        self.assertIn("PEG 0.16", reason)
        self.assertIn("回檔 45.0%", reason)
        self.assertIn("符合框架完整門檻", reason)
        self.assertIn("安全邊際", reason)  # 框架因果理由有帶到
        self.assertIn("供應鏈敘事", reason)  # 免責提醒有帶到

    def test_not_meets_framework_uses_partial_wording(self):
        reason = report.compose_market_scan_track_reason(
            self._row(meets_framework=False, peg=3.0, drawdown_pct=0.1),
            self.framework, "2026-07-22 13:58:21")
        self.assertIn("只通過第一階段初篩", reason)
        self.assertNotIn("符合框架完整門檻", reason)

    def test_missing_peg_data_does_not_leak_none(self):
        reason = report.compose_market_scan_track_reason(
            self._row(per=None, revenue_yoy=None, peg=None, meets_framework=False),
            self.framework, "2026-07-22 13:58:21")
        self.assertNotIn("None", reason)
        self.assertIn("資料不完整", reason)

    def test_missing_drawdown_data_does_not_leak_none(self):
        reason = report.compose_market_scan_track_reason(
            self._row(drawdown_pct=None, high_price=None, high_date=None,
                     current_price=None, current_date=None,
                     error="非預期錯誤：模擬失敗", meets_framework=False),
            self.framework, "2026-07-22 13:58:21")
        self.assertNotIn("None", reason)
        self.assertIn("非預期錯誤：模擬失敗", reason)


class DashboardTest(unittest.TestCase):
    """FR-058 儀表板（方案A單頁式）render_dashboard() 測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-dashboard-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_empty_db_does_not_raise(self):
        page = report.render_dashboard(self.store)
        self.assertIn("AlphaVibe 儀表板", page)
        self.assertIn("今日無需特別留意的標的", page)
        self.assertIn("目前沒有符合任何策略門檻的候選", page)
        self.assertIn("尚無持股快照", page)

    def test_today_highlights_filters_and_sorts_conflict_first(self):
        today = report.datetime.date.today().isoformat()
        self.store.save_module_d_result(
            "2330", "通用層", "財報兌現度正常，無異常",
            suggested_action=None, conflict_flag=False,
            checked_at=today + "T09:00:00")
        self.store.save_module_d_result(
            "3661", "策略層", "PEG回升，假說可能失效",
            suggested_action="建議減碼30%", conflict_flag=False,
            checked_at=today + "T09:01:00")
        self.store.save_module_d_result(
            "2454", "老芋頭動向", "老芋頭賣出但基本面未變差",
            suggested_action="建議觀察，暫不跟進", conflict_flag=True,
            checked_at=today + "T09:02:00")
        page = report.render_dashboard(self.store)
        # suggested_action=None（沒觸發任何檢視規則的正常記錄）不出現在今日重點
        self.assertNotIn("財報兌現度正常，無異常", page)
        self.assertIn("PEG回升，假說可能失效", page)
        self.assertIn("老芋頭賣出但基本面未變差", page)
        self.assertIn("⚠️ 立場衝突", page)
        # conflict_flag=True（2454）排最前面，即使checked_at較晚
        self.assertLess(page.index("2454"), page.index("3661"))

    def test_today_highlights_sorts_holdings_before_watchlist_even_with_conflict(self):
        """2026-08-19新增（PO確認優先序「存股>觀察中>新的>對話」）：3661是
        持股、2454是純觀察且有立場衝突——即使2454衝突、checked_at較早，
        「是否持有」仍是第一排序鍵，3661該排在2454前面；「類型」欄要正確
        標示存股／觀察中。"""
        today = report.datetime.date.today().isoformat()
        self.store.save_holdings([{"code": "3661", "name": "世芯", "shares": 10,
                                    "avg_cost": 1000}])
        self.store.save_module_d_result(
            "2454", "老芋頭動向", "老芋頭賣出但基本面未變差",
            suggested_action="建議觀察，暫不跟進", conflict_flag=True,
            checked_at=today + "T09:00:00")
        self.store.save_module_d_result(
            "3661", "策略層", "PEG回升，假說可能失效",
            suggested_action="建議減碼30%", conflict_flag=False,
            checked_at=today + "T09:01:00")
        page = report.render_dashboard(self.store)
        self.assertLess(page.index("3661"), page.index("2454"))
        self.assertIn("存股", page)
        self.assertIn("觀察中", page)

    def test_no_highlights_today_shows_empty_state(self):
        page = report.render_dashboard(self.store)
        self.assertIn("今日無需特別留意的標的", page)

    def test_new_candidates_merges_multiple_frameworks_into_one_row(self):
        fw_ids = [fw["id"] for fw in frameworks.FRAMEWORKS]
        self.assertGreaterEqual(len(fw_ids), 2, "測試假設至少2套框架，跟FR-058要求的"
                                "「同一代碼符合多套框架要合併」情境一致")
        common_row = {"code": "3661", "name": "世芯-KY", "market": "TWSE",
                     "industry": "半導體業", "per": 8.0, "revenue_yoy": 0.5,
                     "revenue_period": "2026-06", "drawdown_pct": 0.45,
                     "high_price": 100.0, "high_date": "2026-06-01",
                     "current_price": 55.0, "current_date": "2026-07-20",
                     "peg": 0.16, "meets_framework": True, "error": None}
        for fid in fw_ids:
            self.store.save_market_scan_run(fid, "scheduled", [dict(common_row)],
                                            candidate_count=1)
        page = report.render_dashboard(self.store)
        self.assertEqual(page.count("data-label=\"代碼\">3661"), 1)
        for fw in frameworks.FRAMEWORKS:
            self.assertIn(fw["label"], page)

    def test_new_candidates_only_meets_framework_rows_included(self):
        fid = frameworks.default_framework_id()
        self.store.save_market_scan_run(
            fid, "scheduled",
            [{"code": "9999", "name": "未達門檻股", "market": "TWSE",
              "industry": "半導體業", "per": 20.0, "revenue_yoy": -0.1,
              "revenue_period": "2026-06", "drawdown_pct": 0.05,
              "high_price": 100.0, "high_date": "2026-06-01",
              "current_price": 95.0, "current_date": "2026-07-20",
              "peg": None, "meets_framework": False, "error": None}],
            candidate_count=1)
        page = report.render_dashboard(self.store)
        self.assertNotIn("data-label=\"代碼\">9999", page)
        self.assertIn("目前沒有符合任何策略門檻的候選", page)

    def test_strategy_settings_shows_thresholds_and_invalidation_text(self):
        page = report.render_dashboard(self.store)
        self.assertIn("篩選門檻：PEG&lt;1 且營收年增率&gt;=0% 且回檔&gt;=40%", page)
        self.assertIn("假說失效：PEG回升至&gt;=1，或回檔收斂至&lt;15%", page)
        self.assertIn("假說失效：回檔收斂至&lt;15%，或營收年增率降至&lt;=0%", page)
        self.assertIn("＋新增或調整策略", page)
        self.assertIn("策略不是填表單做出來的", page)

    def test_strategy_settings_handles_missing_invalidation_and_arbitrary_combo(self):
        """驗證invalidation轉換文字通用於任意策略／任意子條件組合，不是為
        既有兩套策略寫死的文字；也驗證沒有invalidation欄位時的預設文字。"""
        fake_frameworks = [
            {"id": "no_invalidation", "label": "無專屬規則測試框架",
             "peg_max": 1.5, "revenue_yoy_min": 0.1, "drawdown_min": 0.2,
             "drawdown_max": None, "excess_drawdown_min": None},
            {"id": "yoy_only", "label": "僅營收年增率失效測試框架",
             "peg_max": None, "revenue_yoy_min": None, "drawdown_min": None,
             "drawdown_max": None, "excess_drawdown_min": None,
             "invalidation": {"revenue_yoy_max": 0.05}},
        ]
        with unittest.mock.patch.object(frameworks, "FRAMEWORKS", fake_frameworks):
            page = report.render_dashboard(self.store)
        self.assertIn("尚未定義策略專屬檢視規則", page)
        self.assertIn("假說失效：營收年增率降至&lt;=5%", page)

    def test_holdings_section_matches_classic_render_exactly(self):
        """FR-058驗收硬要求：render()（舊版）跟render_dashboard()（新版）的
        持股比例／主題集中度數字要完全一致——兩者共用_render_holdings_
        section()，直接比對兩邊輸出的<details id="section-holdings">片段
        是否逐字元相同，證明沒有分歧。"""
        self.store.save_holdings([
            {"code": "3661", "name": "世芯-KY", "shares": 100, "avg_cost": 2000},
            {"code": "2454", "name": "聯發科", "shares": 100, "avg_cost": 1000},
        ])
        self.store.upsert_stock_price("3661", 3000, "2026-07-29")
        self.store.upsert_stock_price("2454", 1200, "2026-07-29")
        self.store.save_stock_theme("3661", "ASIC")
        self.store.save_stock_theme("2454", "手機晶片")

        classic_page = report.render(self.store)
        dashboard_page = report.render_dashboard(self.store)

        def extract_holdings(page):
            start = page.index('<details class="section" id="section-holdings"')
            end = page.index("</details>", start) + len("</details>")
            return page[start:end]

        holdings_classic = extract_holdings(classic_page)
        holdings_dashboard = extract_holdings(dashboard_page)
        self.assertEqual(holdings_classic, holdings_dashboard)
        self.assertIn("71.4%", holdings_classic)  # 世芯-KY市值300,000／總市值420,000
        self.assertIn("28.6%", holdings_classic)  # 聯發科市值120,000／總市值420,000

    def test_watchlist_only_section_lists_stance_without_holdings(self):
        """PO反饋：純觀察性質的立場（研究過但還沒真的買）要出現在儀表板，
        不能只有切到 /report-classic 才看得到。"""
        self.store.save_stance("3661", "偏多", name="世芯-KY",
                               reason="還在觀察，尚未建倉")
        page = report.render_dashboard(self.store)
        start = page.index('<details class="section" id="section-watchlist-only"')
        end = page.index("</details>", start) + len("</details>")
        section = page[start:end]
        self.assertIn("data-label=\"代碼\">3661", section)
        self.assertIn("世芯-KY", section)
        self.assertIn("偏多", section)
        self.assertIn("還在觀察，尚未建倉", section)
        # 純觀察區塊不顯示庫存專屬欄位（沒有庫存資料，顯示沒有意義）
        self.assertNotIn("市值", section)
        self.assertNotIn("持股比例", section)

    def test_watchlist_only_section_empty_when_all_stances_have_holdings(self):
        """有立場的標的都已經有對應庫存時，純觀察區塊要顯示空狀態文字，
        不能把已經在庫存總覽出現過的標的重複列一次。"""
        self.store.save_stance("3661", "偏多", name="世芯-KY", reason="估值合理")
        self.store.save_holdings([
            {"code": "3661", "name": "世芯-KY", "shares": 100, "avg_cost": 2000},
        ])
        page = report.render_dashboard(self.store)
        start = page.index('<details class="section" id="section-watchlist-only"')
        end = page.index("</details>", start) + len("</details>")
        section = page[start:end]
        self.assertIn("目前沒有純觀察、尚未建倉的標的。", section)
        self.assertNotIn("data-label=\"代碼\">3661", section)

    def test_watchlist_only_section_empty_when_no_stances_at_all(self):
        """完全沒有立場資料時（空db）也要顯示空狀態文字，不能出錯或留空白。"""
        page = report.render_dashboard(self.store)
        start = page.index('<details class="section" id="section-watchlist-only"')
        end = page.index("</details>", start) + len("</details>")
        section = page[start:end]
        self.assertIn("目前沒有純觀察、尚未建倉的標的。", section)

    def test_watchlist_only_section_excludes_holdings_when_mixed(self):
        """庫存＋純觀察混合情境：3661有庫存要出現在庫存總覽，2454純觀察
        要出現在本區塊，兩邊不能重複也不能互相跑錯區塊。"""
        self.store.save_stance("3661", "偏多", name="世芯-KY", reason="已建倉")
        self.store.save_holdings([
            {"code": "3661", "name": "世芯-KY", "shares": 100, "avg_cost": 2000},
        ])
        self.store.save_stance("2454", "偏多", name="聯發科", reason="觀察中，尚未買進")
        page = report.render_dashboard(self.store)

        holdings_start = page.index('<details class="section" id="section-holdings"')
        holdings_end = page.index("</details>", holdings_start) + len("</details>")
        holdings_section = page[holdings_start:holdings_end]

        watchlist_start = page.index('<details class="section" id="section-watchlist-only"')
        watchlist_end = page.index("</details>", watchlist_start) + len("</details>")
        watchlist_section = page[watchlist_start:watchlist_end]

        # 庫存總覽的代碼欄位是個股詳情頁連結（2026-08-09，庫存買賣圖表
        # 嫁接進 /dashboard/stock/<code>），純觀察區塊沒有交易/庫存資料
        # 可畫圖，維持純文字，兩邊格式刻意不同。
        self.assertIn("<a href=\"/dashboard/stock/3661\">3661</a>", holdings_section)
        self.assertNotIn("data-label=\"代碼\">3661", watchlist_section)
        self.assertIn("data-label=\"代碼\">2454", watchlist_section)
        self.assertNotIn("<a href=\"/dashboard/stock/2454\">2454</a>", holdings_section)

    def test_flash_message_success_and_error_styling(self):
        success_page = report.render_dashboard(self.store, flash="已加入自選股：2330")
        self.assertIn("已加入自選股：2330", success_page)
        self.assertIn("var(--green)", success_page)  # 成功＝綠

        error_page = report.render_dashboard(self.store, flash="⚠️ 加自選股失敗：代碼為必填")
        self.assertIn("加自選股失敗：代碼為必填", error_page)
        self.assertIn("#c92a2a", error_page)  # 錯誤＝紅

    def test_quick_input_section_has_trade_csv_form(self):
        """第四個貼文字快速輸入工具（2026-07-31新增）：貼國泰證券App
        「已成交」CSV格式對帳單，POST到/dashboard/tradecsv，跟既有3個表單
        同樣掛在快速輸入區塊裡。"""
        page = report.render_dashboard(self.store)
        start = page.index('<details class="section" id="section-quick-input"')
        end = page.index("</details>", start) + len("</details>")
        section = page[start:end]
        self.assertIn("貼CSV對帳單", section)
        self.assertIn('action="/dashboard/tradecsv"', section)
        self.assertIn('<textarea name="text"', section)


class HoldingsPreviewTest(unittest.TestCase):
    """report.render_holdings_preview()：貼庫存帳單快速輸入第一步（預覽），
    見 report_server.py 的 /dashboard/holdings/preview（第二步 /confirm 的
    端到端流程測試在 test_report_server.py）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-holdings-preview-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_categorizes_added_removed_changed_and_carries_avg_cost(self):
        """上次快照：2330(1000股,avg_cost=500)、2454(200股,無avg_cost)、
        9999(300股)。這次帳單：2330股數變成2000（avg_cost要沿用500）、
        2454股數不變（沒有avg_cost可沿用，維持None）、9999沒印到（消失）、
        3661是新代碼（新增）。"""
        self.store.save_holdings([
            {"code": "2330", "name": "台積電", "shares": 1000, "avg_cost": 500},
            {"code": "2454", "name": "聯發科", "shares": 200, "avg_cost": None},
            {"code": "9999", "name": "舊代碼", "shares": 300, "avg_cost": 10},
        ])
        parsed = {
            "rows": [
                {"code": "2330", "name": "台積電", "shares": 2000, "is_emerging": False},
                {"code": "2454", "name": "聯發科", "shares": 200, "is_emerging": False},
                {"code": "3661", "name": "世芯-KY", "shares": 50, "is_emerging": False},
            ],
            "unparsed_lines": [],
            "total_parsed": 3,
        }
        previous = self.store.get_holdings()
        page = report.render_holdings_preview(parsed, previous)

        # 新增：3661
        self.assertIn("新增（這次有、上次沒有）", page)
        self.assertIn("3661", page)
        self.assertIn("世芯-KY", page)
        # 消失：9999（不下判斷是否已出清，只講沒印到）
        self.assertIn("這次帳單沒有這一檔", page)
        self.assertIn("9999", page)
        self.assertIn("舊代碼", page)
        # 股數變化：2330 1000→2000（sqlite REAL 欄位存回來是 1000.0，不是
        # 純整數——跟其他既有測試對 shares/avg_cost 的實測結果一致）
        self.assertIn("股數變化", page)
        self.assertIn("1000.0 股 → 2000 股", page)
        # avg_cost 沿用：2330要帶著500.0字樣出現在完整清單
        self.assertIn(
            "<td data-label=\"平均成本\">500.0</td>", page)
        # 2454沒有avg_cost可沿用，維持None（顯示—），不能無中生有
        rows_json_start = page.index("name=\"rows_json\" value=\"") + len(
            "name=\"rows_json\" value=\"")
        rows_json_end = page.index("\">", rows_json_start)
        raw = html.unescape(page[rows_json_start:rows_json_end])
        restored = json.loads(raw)
        by_code = {r["code"]: r for r in restored}
        self.assertEqual(by_code["2330"]["avg_cost"], 500)
        self.assertIsNone(by_code["2454"]["avg_cost"])
        self.assertEqual(by_code["2330"]["shares"], 2000)
        self.assertEqual(by_code["3661"]["name"], "世芯-KY")

    def test_no_changes_shows_neutral_message(self):
        self.store.save_holdings([
            {"code": "2330", "name": "台積電", "shares": 1000, "avg_cost": 500},
        ])
        parsed = {
            "rows": [{"code": "2330", "name": "台積電", "shares": 1000,
                      "is_emerging": False}],
            "unparsed_lines": [], "total_parsed": 1,
        }
        page = report.render_holdings_preview(parsed, self.store.get_holdings())
        self.assertIn("與上次快照相比沒有變化。", page)
        self.assertNotIn("新增（這次有、上次沒有）", page)
        self.assertNotIn("股數變化", page)

    def test_unparsed_lines_shown_clearly(self):
        parsed = {
            "rows": [{"code": "2330", "name": "台積電", "shares": 1000,
                      "is_emerging": False}],
            "unparsed_lines": ["這一行格式怪怪的無法解析123abc"],
            "total_parsed": 1,
        }
        page = report.render_holdings_preview(parsed, self.store.get_holdings())
        self.assertIn("1 行無法解析", page)
        self.assertIn("這一行格式怪怪的無法解析123abc", page)

    def test_empty_rows_shows_no_confirm_form(self):
        """完全沒解析出任何列時，不能顯示會撞ValueError（save_holdings要求
        非空清單）的「確認存入」表單，要改顯示明確的空狀態訊息。"""
        parsed = {"rows": [], "unparsed_lines": ["壞掉的行"], "total_parsed": 0}
        page = report.render_holdings_preview(parsed, self.store.get_holdings())
        self.assertIn("沒有解析出任何資料列，無法存入", page)
        self.assertNotIn("/dashboard/holdings/confirm", page)

    def test_first_time_snapshot_all_rows_are_added(self):
        """從來沒有存過持股快照（previous_holdings為空）時，全部視為新增，
        不能因為prev為空而出錯或誤判成「消失」。"""
        parsed = {
            "rows": [{"code": "2330", "name": "台積電", "shares": 1000,
                      "is_emerging": False}],
            "unparsed_lines": [], "total_parsed": 1,
        }
        page = report.render_holdings_preview(parsed, self.store.get_holdings())
        self.assertIn("新增（這次有、上次沒有）", page)
        self.assertNotIn("這次帳單沒有這一檔", page)

    def test_rows_json_html_escape_round_trips_dash_ky_name(self):
        """股票名稱含「-KY」這種常見but非HTML特殊字元，經esc()跳脫進隱藏
        欄位value屬性後，html.unescape()還原要拿回一模一樣的名稱，不能
        遺失或變形資料。"""
        parsed = {
            "rows": [{"code": "3661", "name": "世芯-KY", "shares": 100,
                      "is_emerging": False}],
            "unparsed_lines": [], "total_parsed": 1,
        }
        page = report.render_holdings_preview(parsed, self.store.get_holdings())
        start = page.index("name=\"rows_json\" value=\"") + len(
            "name=\"rows_json\" value=\"")
        end = page.index("\">", start)
        raw = html.unescape(page[start:end])
        restored = json.loads(raw)
        self.assertEqual(restored[0]["name"], "世芯-KY")


class StockListPageTest(unittest.TestCase):
    """2026-08-01新增：render_stock_list_page()（清單頁）測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-stocklist-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_empty_shows_placeholder_and_add_form(self):
        page = report.render_stock_list_page(self.store)
        self.assertIn("目前沒有追蹤中的標的", page)
        self.assertIn("/dashboard/stocks/add", page)
        self.assertIn("共 0 檔（0 檔庫存＋0 檔研究中）", page)

    def test_holdings_and_research_counted_and_filtered(self):
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 100}])
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_stance("2441", "研究中", name="超豐")
        page_all = report.render_stock_list_page(self.store, filter_key="all")
        self.assertIn("共 2 檔（1 檔庫存＋1 檔研究中）", page_all)
        self.assertIn("2330", page_all)
        self.assertIn("2441", page_all)

        page_holdings = report.render_stock_list_page(self.store, filter_key="holdings")
        self.assertIn("2330", page_holdings)
        self.assertNotIn("2441", page_holdings)

        page_research = report.render_stock_list_page(self.store, filter_key="research")
        self.assertIn("2441", page_research)
        self.assertNotIn("2330", page_research)

    def test_row_shows_sparkline_when_price_history_cached(self):
        """2026-08-09新增：迷你走勢——有股價歷史快取時畫出sparkline
        （紅漲綠跌），沒有快取時顯示「走勢資料不足」而不是報錯或空白。
        清單頁sparkline只取近60天（見_tracked_stock_rows），日期用相對
        「今天」回推，避免日期寫死日後跑出視窗外而讓測試失真。"""
        today = report.datetime.date.today()
        d1 = (today - report.datetime.timedelta(days=30)).isoformat()
        d2 = (today - report.datetime.timedelta(days=5)).isoformat()
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_price_history_points("2330", [
            {"date": d1, "close": 900.0},
            {"date": d2, "close": 1000.0},
        ])
        self.store.save_stance("2441", "研究中", name="超豐")  # 無快取
        page = report.render_stock_list_page(self.store)
        self.assertIn("class=\"spark\"", page)
        self.assertIn("var(--red)", page)  # 900→1000 上漲，紅漲
        self.assertIn("走勢資料不足", page)  # 2441 沒有股價歷史快取

    def test_pagination_shows_ten_per_page(self):
        for i in range(15):
            self.store.save_stance("%04d" % (3000 + i), "研究中", name="測試股%d" % i)
        page1 = report.render_stock_list_page(self.store, page=1)
        self.assertIn("顯示 1–10 / 15 檔", page1)
        self.assertIn("下一批", page1)
        self.assertIn("aria-disabled=\"true\"", page1)  # 上一批disabled

        page2 = report.render_stock_list_page(self.store, page=2)
        self.assertIn("顯示 11–15 / 15 檔", page2)
        self.assertIn("上一批", page2)

        # 第一頁跟第二頁的代碼不重複
        codes_p1 = set(re.findall(r"stock-row__code\">(\d{4})<", page1))
        codes_p2 = set(re.findall(r"stock-row__code\">(\d{4})<", page2))
        self.assertEqual(len(codes_p1), 10)
        self.assertEqual(len(codes_p2), 5)
        self.assertEqual(codes_p1 & codes_p2, set())

    def test_page_out_of_range_clamped_to_last_page(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        page = report.render_stock_list_page(self.store, page=99)
        self.assertIn("顯示 1–1 / 1 檔", page)

    def test_search_matches_code(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.save_stance("2454", "研究中", name="聯發科")
        page = report.render_stock_list_page(self.store, query="2330")
        self.assertIn("2330", page)
        self.assertNotIn("2454", page)

    def test_search_matches_name(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.save_stance("2454", "研究中", name="聯發科")
        page = report.render_stock_list_page(self.store, query="聯發科")
        self.assertIn("2454", page)
        self.assertNotIn("2330", page)

    def test_search_matches_comment_full_text(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.save_stance("2454", "研究中", name="聯發科")
        self.store.save_comment("先進封裝需求強勁，法說會展望佳", source_tag="心得",
                                symbols="2330")
        page = report.render_stock_list_page(self.store, query="先進封裝")
        self.assertIn("2330", page)
        self.assertNotIn("2454", page)

    def test_search_no_match_shows_message(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        page = report.render_stock_list_page(self.store, query="不存在的關鍵字xyz")
        self.assertIn("沒有符合搜尋條件的標的", page)

    def test_concern_flag_marks_row_and_status_text(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.save_module_d_result(
            code="2330", trigger_type="老芋頭動向",
            finding="老芋頭於2026-07-30賣出500股", concern_flag=True,
            checked_at="2026-07-31T18:00:00")
        page = report.render_stock_list_page(self.store)
        self.assertIn("has-concern", page)
        self.assertIn("老芋頭於2026-07-30賣出500股", page)

    def test_only_latest_batch_used_not_historical_rows_mixed(self):
        """同一代碼跨兩個批次的檢視結果，清單頁只該用最新一批判斷concern，
        不能把舊批次的concern也算進來（見派工說明「不能把歷史所有批次的
        列混在一起顯示」）。"""
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="舊批次：下檔風險偏高",
            concern_flag=True, checked_at="2026-07-30T18:00:00")
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="新批次：下檔風險可控",
            concern_flag=False, checked_at="2026-07-31T18:00:00")
        page = report.render_stock_list_page(self.store)
        # 只檢查「列本身有沒有被套用 has-concern class」，不能檢查裸字串
        # "has-concern"——CSS樣式表裡 `.stock-row.has-concern {...}` 這條
        # 規則定義本身永遠存在於頁面裡，裸字串比對必定誤判成「找到了」。
        self.assertNotIn('class="stock-row has-concern"', page)
        self.assertIn("新批次：下檔風險可控", page)

    def test_price_and_delta_rendered(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        self.store.upsert_stock_price("2330", 1005.0, "2026-07-31", prev_close=995.0)
        page = report.render_stock_list_page(self.store)
        self.assertIn("1,005", page)
        self.assertIn("is-up", page)  # 漲=紅色class

    def test_no_price_shows_dash(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        page = report.render_stock_list_page(self.store)
        self.assertIn("—", page)

    def test_xss_escapes_stock_name_and_comment_content(self):
        self.store.save_stance("2330", "研究中", name="<script>alert(1)</script>")
        page = report.render_stock_list_page(self.store)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_invalid_filter_key_defaults_to_all(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        page = report.render_stock_list_page(self.store, filter_key="not-a-real-filter")
        self.assertIn("2330", page)
        self.assertIn("filter-tab active", page)  # 落回「全部」還是要有一個active


class StockDetailPageTest(unittest.TestCase):
    """2026-08-01新增：render_stock_detail_page()（個股詳情頁）測試。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-stockdetail-test-")
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_unknown_code_does_not_raise_shows_placeholders(self):
        page = report.render_stock_detail_page(self.store, "9999")
        self.assertIn("9999", page)
        self.assertIn("尚未產生分析", page)

    def test_concentration_card_shows_unavailable_not_zero_without_holdings(self):
        """2026-08-19新增：純研究標的（沒有庫存市值）算不出集中度時，要
        明講「看不到」而不是畫一條0%的空條讓人誤以為集中度很低——這是
        這張卡刻意跟「沒超標」區分開的第三種狀態。"""
        page = report.render_stock_detail_page(self.store, "9999")
        self.assertIn("集中度／部位控制", page)
        self.assertIn("無法判斷", page)
        self.assertIn("是「看不到」，不是「沒問題」", page)
        # 只比對實際渲染出來的元素（class="conc-fill"），不是 CSS 裡的
        # .conc-fill 規則定義——CSS 常數整份內嵌在頁面裡，直接搜字串會誤判
        self.assertNotIn("class=\"conc-fill", page)

    def test_concentration_card_flags_over_limit_single_and_theme(self):
        """單一持股且已標記主題時，單股與主題集中度都是100%，雙雙超過
        15%/50%上限——徽章要顯示「已達上限」，兩條進度條都要標成超標。"""
        self.store.save_holdings([{"code": "8299", "name": "群聯", "shares": 6,
                                    "avg_cost": 1535}])
        self.store.upsert_stock_price("8299", 2080.0, "2026-08-14")
        self.store.save_stock_theme("8299", "記憶體/NAND景氣循環")
        page = report.render_stock_detail_page(self.store, "8299")
        self.assertIn("已達上限", page)
        self.assertIn("記憶體/NAND景氣循環", page)
        self.assertIn("conc-fill over", page)
        self.assertIn("100.0%", page)

    def test_verdict_banner_appears_before_price_block(self):
        """2026-08-19新增：Verdict 置於價格之前——詳情頁原本一打開先看到
        現價/均價會觸發「跟成本比」的定錨慣性，結論置頂是刻意的版面決定，
        不是排版巧合，所以用順序斷言鎖住。"""
        self.store.upsert_stock_price("2330", 1000.0, "2026-08-14", prev_close=990.0)
        page = report.render_stock_detail_page(self.store, "2330")
        # 一律比對渲染出來的 class="..." 形式：CSS 常數整份內嵌在頁面裡，
        # 直接搜 class 名稱會先命中樣式定義、拿到錯的位置
        self.assertIn("<div class=\"verdict ", page)
        self.assertLess(page.index("<div class=\"verdict "),
                        page.index("<span class=\"stock-row__delta"))

    def test_verdict_flags_gate_concern_as_alert(self):
        """通用層有 concern → 紅色，且結論文字直接引用該筆發現。"""
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="營收年增率連續三月下滑",
            concern_flag=True, checked_at="2026-08-19T17:00:00")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("verdict verdict--alert", page)
        self.assertIn("Gate 有 1 項需留意", page)
        self.assertIn("營收年增率連續三月下滑", page)

    def test_verdict_does_not_treat_strategy_exit_as_gate_failure(self):
        """核心修正的回歸測試：策略層失效（退出篩選候選）**不能**讓
        verdict 變成 Gate 擋住——那是候選機制不是持有門檻。此時 Gate 全過、
        集中度算不出來，結論應該是黃色的「集中度算不出來」，並附註篩選
        框架退出候選不影響結論。"""
        self.store.save_module_d_result(
            code="2308", trigger_type="通用層", finding="PER在歷史合理區間",
            concern_flag=False, checked_at="2026-08-19T17:00:00")
        self.store.save_module_d_result(
            code="2308", trigger_type="策略層",
            strategy_id="peg_deep_dip_concentration",
            finding="PEG已回升至1.26（門檻1.0）", concern_flag=True,
            checked_at="2026-08-19T17:00:00")
        page = report.render_stock_detail_page(self.store, "2308")
        self.assertNotIn("verdict verdict--alert", page)
        self.assertIn("verdict verdict--warn", page)
        self.assertIn("集中度算不出來", page)
        self.assertIn("不影響上面的結論", page)

    def test_verdict_alerts_when_concentration_over_limit(self):
        """Gate 全過但集中度頂格 → 紅色，且說明這是規則等級的擋點。"""
        self.store.save_holdings([{"code": "8299", "name": "群聯", "shares": 6,
                                    "avg_cost": 1535}])
        self.store.upsert_stock_price("8299", 2080.0, "2026-08-14")
        self.store.save_module_d_result(
            code="8299", trigger_type="通用層", finding="PER遠低於歷史區間",
            concern_flag=False, checked_at="2026-08-19T17:00:00")
        page = report.render_stock_detail_page(self.store, "8299")
        self.assertIn("verdict verdict--alert", page)
        self.assertIn("集中度已達上限", page)
        self.assertIn("規則等級的擋點", page)

    def test_position_plan_card_without_plan_shows_form_not_zero_progress(self):
        """2026-08-19新增：沒設定計畫總額度時不畫進度條（沒有分母就沒有
        百分比），改顯示設定表單＋說明，跟集中度卡同一個「算不出來就明講」
        的原則。"""
        page = report.render_stock_detail_page(self.store, "9999")
        self.assertIn("加碼進度", page)
        self.assertIn("尚未設定計畫總額度", page)
        self.assertIn("/dashboard/stock/9999/plan", page)
        # 只比對實際渲染出來的進度條元素；「完成比例」四個字也出現在說明
        # 文字「因此算不出完成比例」裡，直接搜字串會誤判
        self.assertNotIn("conc-row__name\">完成比例", page)

    def test_position_plan_card_computes_progress_from_holdings_snapshot(self):
        """有庫存快照（股數＋均價）時，已投入＝股數×均價，完成比例與
        還可投入金額都要算出來。6股×1535＝9,210，佔計畫30,000的30.7%。"""
        self.store.save_holdings([{"code": "8299", "name": "群聯", "shares": 6,
                                    "avg_cost": 1535}])
        self.store.save_position_plan("8299", 30000)
        page = report.render_stock_detail_page(self.store, "8299")
        self.assertIn("9,210", page)
        self.assertIn("完成比例", page)
        self.assertIn("30.7%", page)
        self.assertIn("還可投入 NT$20,790", page)
        self.assertIn("庫存快照", page)

    def test_position_plan_card_falls_back_to_ledger_when_snapshot_missing(self):
        """庫存快照沒這檔（台達電實況）時退回交易流水表估算：60股買進、
        加權平均1809.17→已投入約108,550，來源要標示「交易流水表估算」。"""
        for shares, price, date, seq in ((10, 1830.0, "2026-06-26", 1),
                                          (10, 1790.0, "2026-07-21", 2),
                                          (10, 1905.0, "2026-07-22", 3),
                                          (10, 1900.0, "2026-07-23", 4),
                                          (5, 1870.0, "2026-07-24", 5),
                                          (5, 1760.0, "2026-07-27", 6),
                                          (5, 1580.0, "2026-07-28", 7),
                                          (5, 1650.0, "2026-08-07", 8)):
            self.store.save_trade_ledger_entry("2308", "台達電", "買", shares, price,
                                               date, add_sequence=seq)
        page = report.render_stock_detail_page(self.store, "2308")
        self.assertIn("108,550", page)
        self.assertIn("交易流水表估算", page)
        self.assertIn("60 股", page)

    def test_position_plan_card_excludes_sold_out_shares_from_invested(self):
        """已投入是「目前部位成本」不是「歷史買進總額」：買10股又賣掉6股，
        已投入只算剩下的4股，不是全部10股的買進金額。"""
        self.store.save_trade_ledger_entry("3661", "世芯", "買", 10, 1000.0,
                                           "2026-06-01", add_sequence=1)
        self.store.save_trade_ledger_entry("3661", "世芯", "賣", 6, 1500.0,
                                           "2026-07-01")
        page = report.render_stock_detail_page(self.store, "3661")
        self.assertIn("4,000", page)      # 4股×1000，不是10股的10,000
        self.assertNotIn("10,000", page)

    def test_concentration_card_shows_next_add_sequence(self):
        """加碼次序要顯示出來（遞減式加碼表定義到第5次）：已有2筆帶
        add_sequence的買進，下一次就是第3次，建議比例15%。"""
        self.store.save_holdings([{"code": "2308", "name": "台達電", "shares": 20,
                                    "avg_cost": 1800}])
        self.store.upsert_stock_price("2308", 1885.0, "2026-08-14")
        self.store.save_trade_ledger_entry("2308", "台達電", "買", 10, 1830.0,
                                           "2026-06-26", add_sequence=1)
        self.store.save_trade_ledger_entry("2308", "台達電", "買", 10, 1790.0,
                                           "2026-07-21", add_sequence=2)
        page = report.render_stock_detail_page(self.store, "2308")
        self.assertIn("第 3 次加碼", page)
        self.assertIn("15%", page)
        self.assertIn("尚無估值資料", page)
        self.assertIn("尚未記錄買進理由", page)

    def test_refreshing_state_shows_updating_message_and_disables_button(self):
        self.store.save_stance("2330", "研究中", name="台積電")
        page = report.render_stock_detail_page(self.store, "2330", refreshing=True)
        self.assertIn("更新中", page)
        self.assertIn("disabled", page)

    def test_buy_reason_pinned_card_shows_latest(self):
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_comment("舊的買進理由", source_tag="買進理由", symbols="2330",
                                date="2026-01-01")
        self.store.save_comment("最新的買進理由：先進封裝需求強", source_tag="買進理由",
                                symbols="2330", date="2026-05-11")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("reason-pin", page)
        self.assertIn("最新的買進理由：先進封裝需求強", page)
        # 心得與留言卡的一般留言清單不該重複列出買進理由
        self.assertEqual(page.count("最新的買進理由：先進封裝需求強"), 1)

    def test_valuation_card_shows_numbers_and_source(self):
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.upsert_stock_valuation(
            "2330", per=14.2, pbr=2.85, dividend_yield=5.98, revenue_yoy=0.332,
            valuation_data_source="twse_official", checked_at="2026-07-31T18:00:00")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("14.2", page)
        self.assertIn("2.85", page)
        self.assertIn("5.98%", page)
        self.assertIn("33.2%", page)
        self.assertIn("官方來源（TWSE）", page)

    def test_module_d_card_groups_by_trigger_type_with_concern_color(self):
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_module_d_result(
            code="2330", trigger_type="通用層", finding="下檔風險可控",
            concern_flag=False, checked_at="2026-07-31T18:00:00")
        self.store.save_module_d_result(
            code="2330", trigger_type="策略層", strategy_id="peg_deep_dip_concentration",
            finding="假說未失效", concern_flag=False, checked_at="2026-07-31T18:00:00")
        self.store.save_module_d_result(
            code="2330", trigger_type="老芋頭動向", finding="老芋頭賣出，你仍持有",
            concern_flag=True, checked_at="2026-07-31T18:00:00")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("下檔風險可控", page)
        self.assertIn("peg_deep_dip_concentration", page)
        self.assertIn("老芋頭賣出，你仍持有", page)
        # 2026-08-19 重構：三層改為分區呈現，狀態語意各自不同
        self.assertIn("Required・Gate", page)          # 通用層＝必過檢查
        self.assertIn("finding ok", page)
        # 策略層＝Reference only，用 ref（藍）不用紅綠，文字避開 PASS/FAIL
        self.assertIn("Reference only", page)
        self.assertIn("finding ref", page)
        self.assertIn("仍符合候選", page)
        # 老芋頭＝獨立訊號，刻意不再用 alert 紅色（工具設計本就是「純陳述
        # 事實、不做判斷」），改中性呈現；它的 concern_flag 仍照舊驅動
        # 清單頁「需留意」標記與今日重點，這裡只改詳情頁的呈現語意
        self.assertIn("Status check", page)

    def test_holdings_card_shown_when_holding_exists(self):
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 100,
                                   "avg_cost": 900}])
        self.store.upsert_stock_price("2330", 1000.0, "2026-07-31")
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 100, 900,
                                           "2026-05-11", add_sequence=1)
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("持股與交易", page)
        self.assertIn("庫存中", page)
        self.assertIn("100", page)

    def test_holdings_card_hidden_for_pure_research_stock(self):
        self.store.save_stance("2441", "研究中", name="超豐")
        page = report.render_stock_detail_page(self.store, "2441")
        self.assertNotIn("持股與交易", page)

    def test_holdings_card_shows_history_when_sold_out(self):
        """曾經持有、目前已出清（不在最新庫存快照，但trade_ledger有紀錄）：
        卡片仍顯示、但標示「目前未持有」，不是空表格（見派工說明判斷取捨）。"""
        self.store.save_trade_ledger_entry("2441", "超豐", "買", 1000, 90,
                                           "2026-01-01", add_sequence=1)
        self.store.save_trade_ledger_entry("2441", "超豐", "賣", 1000, 95,
                                           "2026-06-01")
        page = report.render_stock_detail_page(self.store, "2441")
        self.assertIn("持股與交易", page)
        self.assertIn("目前未持有", page)
        self.assertIn("trade-row__tag buy", page)
        self.assertIn("trade-row__tag sell", page)

    def test_holdings_card_chart_shows_insufficient_data_message_without_history_cache(self):
        """2026-08-09新增：庫存買賣圖表——還沒被背景刷新過（stock_price_
        history無資料）時，圖表區顯示提示文字而不是空白或報錯，交易清單
        仍照常顯示。"""
        self.store.save_trade_ledger_entry("2441", "超豐", "買", 1000, 90,
                                           "2026-06-01", add_sequence=1)
        page = report.render_stock_detail_page(self.store, "2441")
        self.assertIn("股價快取資料不足，按上方「更新」刷新後即可看到走勢圖", page)
        self.assertIn("trade-row__tag buy", page)

    def test_holdings_card_chart_renders_combo_chart_with_cached_history(self):
        """有股價歷史快取＋交易紀錄時，畫出價格折線＋買賣力道長條圖。"""
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 100,
                                   "avg_cost": 900}])
        self.store.save_price_history_points("2330", [
            {"date": "2026-06-01", "close": 900.0},
            {"date": "2026-06-15", "close": 950.0},
            {"date": "2026-07-01", "close": 1000.0},
        ])
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 100, 900,
                                           "2026-06-01", add_sequence=1)
        self.store.save_trade_ledger_entry("2330", "台積電", "賣", 30, 1000,
                                           "2026-07-01")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("class=\"combo-chart\"", page)
        self.assertIn("<polyline", page)
        self.assertIn("<rect", page)
        self.assertIn("快取範圍 2026-06-01 ~ 2026-07-01", page)

    def test_chart_stats_shows_current_avg_and_floating_pnl(self):
        """2026-08-09新增（PO比對mockup反饋）：走勢圖右上方現價/均價/
        浮動損益。holding.avg_cost有值時均價欄位不帶筆數。"""
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 100,
                                   "avg_cost": 900.0}])
        self.store.upsert_stock_price("2330", 1000.0, "2026-07-31")
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 100, 900,
                                           "2026-06-01", add_sequence=1)
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("class=\"chart-stats\"", page)
        self.assertIn("<b>1,000</b><span>現價</span>", page)
        self.assertIn("<b style=\"color:var(--amber)\">900</b><span>均價</span>", page)
        self.assertIn("+11.1%", page)
        self.assertIn("color:var(--red)", page)  # 浮動損益為正，紅漲語意

    def test_chart_stats_avg_cost_label_shows_buy_count_when_no_holding_avg_cost(self):
        """holding.avg_cost 缺值（實務常見）時退回交易流水加權平均，均價
        欄位標籤要帶「（N筆）」讓PO知道這是估算值不是帳上真實成本。"""
        self.store.save_holdings([{"code": "2441", "name": "超豐", "shares": 2000,
                                   "avg_cost": None}])
        self.store.save_trade_ledger_entry("2441", "超豐", "買", 1000, 90,
                                           "2026-06-01", add_sequence=1)
        self.store.save_trade_ledger_entry("2441", "超豐", "買", 1000, 100,
                                           "2026-06-15", add_sequence=2)
        page = report.render_stock_detail_page(self.store, "2441")
        self.assertIn("均價（2筆）", page)

    def test_chart_stats_floating_pnl_hidden_without_current_price(self):
        """查不到現價時浮動損益不算、不顯示假數字，均價本身仍顯示。"""
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 100,
                                   "avg_cost": 900.0}])
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 100, 900,
                                           "2026-06-01", add_sequence=1)
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("<b>—</b><span>現價</span>", page)
        self.assertIn("<b style=\"color:var(--amber)\">900</b><span>均價</span>", page)
        self.assertNotIn("浮動損益", page)

    def test_chart_dims_closed_lot_before_last_sell_and_draws_separator(self):
        """2026-08-09新增（PO反饋：混著全部歷史買賣紀錄容易誤會成都是
        目前部位）：最後一筆賣出之前的交易淡化顯示＋分隔線，之後的
        （目前部位）維持實色 opacity=0.85。"""
        self.store.save_holdings([{"code": "8299", "name": "群聯", "shares": 6,
                                   "avg_cost": 1535.0}])
        self.store.save_price_history_points("8299", [
            {"date": "2026-04-30", "close": 1990.0},
            {"date": "2026-07-15", "close": 2095.0},
            {"date": "2026-07-30", "close": 1535.0},
        ])
        self.store.save_trade_ledger_entry("8299", "群聯", "買", 4, 1990.0,
                                           "2026-04-30", add_sequence=1)
        self.store.save_trade_ledger_entry("8299", "群聯", "賣", 14, 2095.0, "2026-07-15")
        self.store.save_trade_ledger_entry("8299", "群聯", "買", 6, 1535.0,
                                           "2026-07-30", add_sequence=2)
        page = report.render_stock_detail_page(self.store, "8299")
        self.assertIn("opacity=\"0.35\"", page)  # 已平倉那筆長條淡化
        self.assertIn("opacity=\"0.85\"", page)  # 目前部位那筆長條維持實色
        self.assertIn("淡色＝已平倉舊紀錄，實色＝目前這批部位", page)
        self.assertIn("（已平倉舊紀錄）", page)  # rect title 上有附註

    def test_chart_no_dimming_when_never_sold(self):
        """單純累積加碼、從未賣出過：整批維持實色，不畫分隔線、不顯示
        「已平倉」相關文字，避免無意義的視覺雜訊。"""
        self.store.save_holdings([{"code": "2330", "name": "台積電", "shares": 20,
                                   "avg_cost": 900.0}])
        self.store.save_price_history_points("2330", [
            {"date": "2026-06-01", "close": 900.0},
            {"date": "2026-07-01", "close": 950.0},
        ])
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 890,
                                           "2026-06-01", add_sequence=1)
        self.store.save_trade_ledger_entry("2330", "台積電", "買", 10, 910,
                                           "2026-07-01", add_sequence=2)
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertNotIn("opacity=\"0.35\"", page)
        self.assertNotIn("已平倉", page)

    def test_notes_card_lists_non_buy_reason_comments(self):
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_comment("買進理由内容", source_tag="買進理由", symbols="2330")
        self.store.save_comment("心得內容A", source_tag="心得", symbols="2330")
        self.store.save_comment("交易備註內容B", source_tag="交易備註", symbols="2330")
        self.store.save_comment("別檔股票的留言，不該出現", source_tag="心得", symbols="9999")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("心得內容A", page)
        self.assertIn("交易備註內容B", page)
        self.assertNotIn("別檔股票的留言，不該出現", page)
        self.assertIn("另有 1 則買進理由已置頂", page)

    def test_xss_escapes_comment_body_and_name(self):
        self.store.save_stance("2330", "偏多", name="台積電")
        self.store.save_comment('<img src=x onerror=alert(1)>', source_tag="心得",
                                symbols="2330")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertNotIn("<img src=x onerror=alert(1)>", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)

    def test_title_escapes_stock_name(self):
        self.store.save_stance("2330", "偏多", name="<b>台積電</b>")
        page = report.render_stock_detail_page(self.store, "2330")
        self.assertIn("<title>2330 &lt;b&gt;台積電&lt;/b&gt; - AlphaVibe</title>", page)


if __name__ == "__main__":
    unittest.main()
