"""report.py 測試：有資料／空資料／HTML 跳脫。"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

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
        self.assertIn("background:#fff3bf", page)  # 符合框架的列有標色
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

    def _latest(self, rows, meets_count=None):
        return {"found": True,
                "run": {"run_at": "2026-07-22 02:00:00", "trigger_source": "scheduled",
                        "candidate_count": len(rows),
                        "meets_count": meets_count if meets_count is not None
                        else sum(1 for r in rows if r["meets_framework"]),
                        "twse_error": None, "tpex_error": None},
                "results": rows}

    def test_empty_state_when_no_scan_yet(self):
        page = report.render_market_scan_page(
            "peg_deep_dip_concentration", {"found": False, "run": None, "results": []})
        self.assertIn("尚無掃描紀錄", page)

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
        self.assertNotIn("background:#fff3bf", match_section.group(0))

    def test_all_candidates_section_still_highlights_matches(self):
        rows = [self._row("3135", meets=True), self._row("2222", meets=False, peg=3.0)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        all_section = re.search(
            r'<details class="section"><summary><h2>全部候選.*?</details>\s*</body>', page, re.S)
        self.assertIn("background:#fff3bf", all_section.group(0))

    def test_explanation_text_moved_into_collapsed_details(self):
        rows = [self._row("3135", meets=True)]
        page = report.render_market_scan_page("peg_deep_dip_concentration", self._latest(rows))
        self.assertIn("<summary>這是什麼？</summary>", page)
        # 說明文字要在收合details裡，不能是開頁就看到的裸段落
        self.assertNotIn('<p class="meta">用 TWSE/TPEx 官方批次資料', page)


if __name__ == "__main__":
    unittest.main()
