"""T014：HTML→純文字與完整度分類（FR-010～FR-012、FR-014、spec Q14；research R6）。

重點：**不以長度判斷 P**（Read more 結構才是）、不確定一律 P、N 類不保存內文。
最後一組測試用 `SubstackStore` 實際寫入再讀回，驗 FR-011 的存放規則。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_html as H  # noqa: E402
import substack_store as S  # noqa: E402

LINK = "https://%s/p/%s-1" % (F.DEFAULT_HOST, F.SLUG_MARK)
SAMPLES = F.article_samples(LINK)

# 結構樣本 → 期望的 (完整度, 依據)
EXPECTED = {
    "preview_short": ("P", "read_more_tail"),
    "preview_long": ("P", "read_more_tail"),
    "player_only": ("N", "text_lt_200"),
    "embed_card": ("N", "text_lt_200"),
    "full_long": ("F", "text_ge_200"),
    "full_no_tail": ("F", "text_ge_200"),
    "short_no_tail": ("N", "text_lt_200"),
    "disclaimer_end": ("F", "text_ge_200"),
    "empty_content": ("P", "uncertain:no_content"),
    "read_more_other_host": ("P", "uncertain:read_more_mismatch"),
    "read_more_then_more": ("P", "uncertain:content_after_read_more"),
    "broken_html": ("F", "text_ge_200"),
    "multi_image": ("F", "text_ge_200"),
    "with_script": ("F", "text_ge_200"),
}


class HtmlToTextTest(unittest.TestCase):
    def test_block_elements_become_newlines(self):
        text, _ = H.html_to_text("<p>第一段</p><p>第二段</p><div>第三段</div>")
        self.assertEqual([line for line in text.splitlines() if line.strip()],
                         ["第一段", "第二段", "第三段"])

    def test_list_items_get_bullet(self):
        text, _ = H.html_to_text("<ul><li>甲</li><li>乙</li></ul>")
        lines = [line for line in text.splitlines() if line.strip()]
        self.assertEqual(lines, ["• 甲", "• 乙"])

    def test_script_and_style_dropped(self):
        text, _ = H.html_to_text("<p>內容</p><script>var x=1;</script><style>.a{color:red}</style>")
        self.assertIn("內容", text)
        self.assertNotIn("var x", text)
        self.assertNotIn("color:red", text)

    def test_embed_and_player_markers(self):
        text, _ = H.html_to_text('<iframe src="https://x/y"></iframe>')
        self.assertIn(H.EMBED_MARK, text)
        text, _ = H.html_to_text('<audio src="https://x/a.mp3"></audio>')
        self.assertIn(H.PLAYER_MARK, text)
        text, _ = H.html_to_text('<video src="https://x/v.mp4"></video>')
        self.assertIn(H.PLAYER_MARK, text)
        text, _ = H.html_to_text('<div class="audio-player">x</div>')
        self.assertIn(H.PLAYER_MARK, text)

    def test_image_markers_numbered_in_order(self):
        text, images = H.html_to_text(SAMPLES["multi_image"])
        self.assertEqual([img["seq"] for img in images], [1, 2, 3])
        self.assertIn("〔圖 1", text)
        self.assertIn("〔圖 2", text)
        self.assertIn("〔圖 3", text)
        self.assertLess(text.index("〔圖 1"), text.index("〔圖 2"))
        self.assertLess(text.index("〔圖 2"), text.index("〔圖 3"))
        self.assertEqual(images[0]["alt"], "圖說ALT1")
        self.assertIsNone(images[0]["caption"])
        self.assertEqual(images[1]["caption"], "圖說CAP2")
        self.assertIsNone(images[2]["alt"])
        for img in images:
            self.assertIn(F.IMG_URL_MARK, img["src"])

    def test_figcaption_merged_into_marker_and_not_duplicated(self):
        html = ('<figure><img src="https://h/a.jpg" alt="ALT文字" />'
                '<figcaption>圖說文字</figcaption></figure>')
        text, images = H.html_to_text(html)
        self.assertEqual(images[0]["caption"], "圖說文字")
        self.assertEqual(images[0]["alt"], "ALT文字")
        self.assertIn("圖說：圖說文字", text)
        self.assertIn("alt：ALT文字", text)
        self.assertEqual(text.count("圖說文字"), 1, "figcaption 不得重複輸出")

    def test_marker_without_alt_or_caption(self):
        text, images = H.html_to_text('<img src="https://h/a.jpg" />')
        self.assertEqual(text.strip(), "〔圖 1〕")
        self.assertEqual(images[0]["seq"], 1)

    def test_visible_text_len_excludes_markers_and_whitespace(self):
        text, _ = H.html_to_text('<p>abc</p><img src="https://h/a.jpg" alt="長長長長長" />'
                                 '<iframe src="x"></iframe>')
        self.assertEqual(H.visible_text_len(text), 3)
        self.assertEqual(H.visible_text_len("  a\n b \t"), 2)


class ClassifyTest(unittest.TestCase):
    def test_all_structural_samples(self):
        for name, (completeness, reason) in sorted(EXPECTED.items()):
            got = H.classify(SAMPLES[name], LINK)
            self.assertEqual(got, (completeness, reason), "樣本 %s" % name)

    def test_missing_content_is_uncertain_preview(self):
        for empty in (None, "", "   ", "\n"):
            self.assertEqual(H.classify(empty, LINK), ("P", "uncertain:no_content"))

    def test_unparsable_html_is_uncertain_preview(self):
        self.assertEqual(H.classify("<", LINK), ("P", "uncertain:parse_error"))
        self.assertEqual(H.classify("<<<", LINK), ("P", "uncertain:parse_error"))

    def test_boundary_199_and_200(self):
        self.assertEqual(H.MIN_FULLTEXT_CHARS, 200)
        html_199 = "<p>%s</p>" % F.filler(199)
        html_200 = "<p>%s</p>" % F.filler(200)
        self.assertEqual(H.visible_text_len(H.html_to_text(html_199)[0]), 199)
        self.assertEqual(H.visible_text_len(H.html_to_text(html_200)[0]), 200)
        self.assertEqual(H.classify(html_199, LINK), ("N", "text_lt_200"))
        self.assertEqual(H.classify(html_200, LINK), ("F", "text_ge_200"))

    def test_never_decides_preview_by_length(self):
        tail = F.read_more_tail(LINK)
        short_tail = "<p>%s</p>%s" % (F.filler(50), tail)
        long_tail = "<p>%s</p>%s" % (F.filler(15000), tail)
        self.assertEqual(H.classify(short_tail, LINK), ("P", "read_more_tail"))
        self.assertEqual(H.classify(long_tail, LINK), ("P", "read_more_tail"))
        self.assertEqual(H.classify("<p>%s</p>" % F.filler(15000), LINK), ("F", "text_ge_200"))
        self.assertEqual(H.classify("<p>%s</p>" % F.filler(50), LINK), ("N", "text_lt_200"))

    def test_read_more_variants(self):
        # 大小寫與前後空白不影響
        for label in ("Read more", "read more", "READ MORE", "  Read More  "):
            html = "<p>%s</p><p><a href=\"%s\">%s</a></p>" % (F.filler(300), LINK, label)
            self.assertEqual(H.classify(html, LINK), ("P", "read_more_tail"), label)
        # 連結文字不是 Read more → 不算尾端（這裡是正常全文）
        html = "<p>%s</p><p><a href=\"%s\">繼續閱讀</a></p>" % (F.filler(300), LINK)
        self.assertEqual(H.classify(html, LINK), ("F", "text_ge_200"))
        # 尾端段落除了連結還有其他文字 → 結構不符
        html = "<p>%s</p><p>還有字 <a href=\"%s\">Read more</a></p>" % (F.filler(300), LINK)
        self.assertEqual(H.classify(html, LINK), ("P", "uncertain:read_more_mismatch"))
        # 尾端不是 p
        html = "<p>%s</p><div><a href=\"%s\">Read more</a></div>" % (F.filler(300), LINK)
        self.assertEqual(H.classify(html, LINK), ("P", "uncertain:read_more_mismatch"))
        # href 不是 /p/<slug>
        html = "<p>%s</p><p><a href=\"https://%s/archive\">Read more</a></p>" % (
            F.filler(300), F.DEFAULT_HOST)
        self.assertEqual(H.classify(html, LINK), ("P", "uncertain:read_more_mismatch"))

    def test_preview_body_text_drops_the_tail(self):
        html = SAMPLES["preview_short"]
        completeness, reason = H.classify(html, LINK)
        self.assertEqual((completeness, reason), ("P", "read_more_tail"))
        result = H.analyze(html, LINK)
        self.assertNotIn("Read more", result["body_text"])
        self.assertNotIn(F.SLUG_MARK, result["body_text"])
        self.assertIn(F.BODY_MARK, result["body_text"])
        full_text, _ = H.html_to_text(html)
        self.assertIn("Read more", full_text, "未去尾端的轉換仍應含 Read more（對照組）")

    def test_invariants_hold_for_every_sample(self):
        for name, html in sorted(SAMPLES.items()):
            completeness, reason = H.classify(html, LINK)
            if reason.startswith("uncertain:"):
                self.assertEqual(completeness, "P", "%s：不確定必為 P" % name)
            if completeness == "P":
                self.assertTrue(reason == "read_more_tail" or reason.startswith("uncertain:"),
                                "%s：P 只能來自 read_more_tail 或 uncertain:*（實際 %s）"
                                % (name, reason))
            self.assertIn(completeness, ("P", "F", "N"))

    def test_rule_version_is_non_empty_string(self):
        self.assertIsInstance(H.RULE_VERSION, str)
        self.assertTrue(H.RULE_VERSION.strip())


class AnalyzeStorageTest(unittest.TestCase):
    """FR-011 存放斷言：實際寫入 substack.db 再讀回。"""

    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)

    def insert(self, html):
        result = H.analyze(html, LINK)
        row = F.article_row(completeness=result["completeness"],
                            classify_reason=result["reason"],
                            content_html=html if html is not None else None,
                            body_text=result["body_text"])
        images = [{"seq": img["seq"], "src_url": img["src"], "alt": img["alt"],
                   "caption": img["caption"]} for img in result["images"]]
        article_id = self.store.insert_article_with_images(row, images)
        return article_id, self.store.get_article(article_id), result

    def test_full_article_stores_whole_text(self):
        html = SAMPLES["full_long"]
        _, row, result = self.insert(html)
        self.assertEqual(row["completeness"], "F")
        expected, _ = H.html_to_text(html)
        self.assertEqual(row["body_text"], expected)
        self.assertEqual(row["content_html"], html)
        self.assertGreaterEqual(H.visible_text_len(row["body_text"]), 15000)

    def test_preview_stores_only_public_preview(self):
        html = SAMPLES["preview_long"]
        article_id, row, _ = self.insert(html)
        self.assertEqual(row["completeness"], "P")
        self.assertNotIn("Read more", row["body_text"])
        self.assertEqual(row["content_html"], html, "原始內容原樣保存（重判的唯一輸入）")
        effective = self.store.effective_article(article_id)
        self.assertEqual(effective["effective_completeness"], "P")
        self.assertIsNotNone(effective["effective_body_text"])

    def test_non_text_stores_no_body_but_keeps_html_and_images(self):
        html = ('<div class="audio-player"><audio src="https://%s/a.mp3"></audio></div>%s'
                % (F.IMAGE_HOST, F.img_tag(1, with_caption=True)))
        article_id, row, result = self.insert(html)
        self.assertEqual(row["completeness"], "N")
        self.assertIsNone(row["body_text"], "N 類不得保存內文（FR-011、Q14）")
        self.assertEqual(row["content_html"], html, "原始內容仍原樣保存")
        images = self.store.list_images(article_id)
        self.assertEqual([img["seq"] for img in images], [1])
        self.assertEqual(images[0]["caption"], "圖說CAP1")
        self.assertEqual(images[0]["alt"], "圖說ALT1")
        effective = self.store.effective_article(article_id)
        self.assertIsNone(effective["effective_body_text"], "N 類不進搜尋可見範圍")
        self.assertEqual(effective["effective_completeness"], "N")

    def test_analyze_returns_none_body_for_non_text(self):
        result = H.analyze(SAMPLES["player_only"], LINK)
        self.assertEqual(result["completeness"], "N")
        self.assertIsNone(result["body_text"])
        self.assertTrue(result["images"] == [] or result["images"])

    def test_all_three_classes_keep_content_html(self):
        for name in ("full_no_tail", "preview_short", "short_no_tail"):
            store_dir = F.temp_data_dir(self)
            store = S.SubstackStore(store_dir)
            self.addCleanup(store.close)
            result = H.analyze(SAMPLES[name], LINK)
            row = F.article_row(completeness=result["completeness"],
                                classify_reason=result["reason"],
                                content_html=SAMPLES[name], body_text=result["body_text"])
            article_id = store.insert_article_with_images(row, [])
            saved = store.get_article(article_id)
            self.assertEqual(saved["content_html"], SAMPLES[name], name)
            if result["completeness"] == "N":
                self.assertIsNone(saved["body_text"], name)
            else:
                self.assertTrue(saved["body_text"], name)

    def test_body_text_null_iff_non_text(self):
        for name in sorted(SAMPLES):
            result = H.analyze(SAMPLES[name], LINK)
            self.assertEqual(result["body_text"] is None, result["completeness"] == "N",
                             "%s：body_text 為 NULL ⇔ 完整度 N" % name)


if __name__ == "__main__":
    unittest.main()
