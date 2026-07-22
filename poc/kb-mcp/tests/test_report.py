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


if __name__ == "__main__":
    unittest.main()
