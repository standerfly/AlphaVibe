"""T005：外部內容來源身分（source_key／body_sha256／youtube_video_id）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import external_content_identity as I  # noqa: E402

VID = "dQw4w9WgXcQ"
YT = "youtube:" + VID


class YouTubeTest(unittest.TestCase):
    def test_all_forms_converge_to_one_key(self):
        urls = [
            "https://www.youtube.com/watch?v=%s" % VID,
            "https://youtube.com/watch?v=%s" % VID,
            "https://m.youtube.com/watch?v=%s&feature=share" % VID,
            "https://music.youtube.com/watch?v=%s&si=abc" % VID,
            "https://youtu.be/%s?si=xyz&t=30" % VID,
            "http://youtu.be/%s" % VID,
            "https://www.youtube.com/shorts/%s" % VID,
            "https://www.youtube.com/live/%s?si=q" % VID,
            "https://www.youtube.com/embed/%s" % VID,
            "https://www.youtube.com/watch?list=PL1&v=%s&t=5s&start=3&pp=x&utm_source=a" % VID,
            "https://WWW.YouTube.com/watch?v=%s#t=10" % VID,
        ]
        for u in urls:
            self.assertEqual(I.source_key(u, "youtube"), YT, u)
            self.assertEqual(I.youtube_video_id(u), VID, u)

    def test_evil_host_not_youtube(self):
        for u in ("https://youtube.com.evil.com/watch?v=%s" % VID,
                  "https://evilyoutube.com/watch?v=%s" % VID,
                  "https://notyoutu.be/%s" % VID,
                  "https://example.com/watch?v=%s" % VID):
            self.assertIsNone(I.youtube_video_id(u), u)
            self.assertFalse(I.is_youtube_url(u), u)
            self.assertTrue(I.source_key(u, "youtube").startswith("url:"), u)

    def test_source_type_mislabel_still_youtube_rule(self):
        u = "https://youtu.be/%s?si=x" % VID
        self.assertEqual(I.source_key(u, "podcast"), YT)
        self.assertEqual(I.source_key(u, "article"), YT)
        self.assertEqual(I.source_key(u, "podcast", guid="g-1"), YT)   # guid 不蓋過 YouTube 規則

    def test_youtube_without_id_raises(self):
        for u in ("https://www.youtube.com/",
                  "https://www.youtube.com/watch",
                  "https://www.youtube.com/watch?v=short",
                  "https://www.youtube.com/channel/UC123",
                  "https://youtu.be/",
                  "https://www.youtube.com/shorts/"):
            with self.assertRaises(I.IdentityError, msg=u):
                I.source_key(u, "youtube")
            self.assertIsNone(I.youtube_video_id(u), u)

    def test_invalid_urls_raise(self):
        for u in ("", "   ", None, "ftp://example.com/a", "not a url", "https://"):
            with self.assertRaises(I.IdentityError, msg=repr(u)):
                I.source_key(u, "article")


class GenericTest(unittest.TestCase):
    def test_tracking_params_removed_others_kept_sorted(self):
        a = I.source_key("http://www.Example.com/post/1/?utm_source=x&b=2&fbclid=z&a=1&ref=t&si=q&gclid=g#frag", "article")
        self.assertEqual(a, "url:https://example.com/post/1?a=1&b=2")

    def test_equivalent_forms_converge(self):
        k1 = I.source_key("https://example.com/p?b=2&a=1", "article")
        k2 = I.source_key("http://www.example.com/p/?a=1&b=2&utm_campaign=c", "article")
        self.assertEqual(k1, k2)

    def test_distinct_query_stays_distinct(self):
        self.assertNotEqual(I.source_key("https://example.com/p?id=1", "article"),
                            I.source_key("https://example.com/p?id=2", "article"))

    def test_root_path_and_trailing_slash(self):
        self.assertEqual(I.source_key("https://example.com/", "article"), "url:https://example.com")
        self.assertEqual(I.source_key("https://example.com/a/b/", "article"), "url:https://example.com/a/b")


class PodcastTest(unittest.TestCase):
    def test_guid_wins_over_url(self):
        k = I.source_key("https://example.com/ep1?utm_source=x", "podcast", guid="  abc-123 ")
        self.assertEqual(k, "podcast:guid:abc-123")

    def test_empty_guid_falls_back_to_url(self):
        self.assertEqual(I.source_key("https://example.com/ep1", "podcast", guid=""), "url:https://example.com/ep1")
        self.assertEqual(I.source_key("https://example.com/ep1", "podcast", guid="  "), "url:https://example.com/ep1")

    def test_guid_ignored_for_non_podcast(self):
        self.assertEqual(I.source_key("https://example.com/a", "article", guid="g"), "url:https://example.com/a")

    def test_apple_podcasts_uses_show_and_episode_ids(self):
        a = I.source_key("https://podcasts.apple.com/tw/podcast/%E8%82%A1%E7%99%8C/id1234567890?i=1000700000001", "podcast")
        b = I.source_key("https://podcasts.apple.com/us/podcast/other-name/id1234567890?i=1000700000001&uo=4", "podcast")
        self.assertEqual(a, "podcast:apple:1234567890:1000700000001")
        self.assertEqual(a, b)
        c = I.source_key("https://podcasts.apple.com/tw/podcast/x/id1234567890?i=1000700000002", "podcast")
        self.assertNotEqual(a, c)

    def test_apple_without_episode_falls_back_to_generic(self):
        k = I.source_key("https://podcasts.apple.com/tw/podcast/x/id1234567890", "podcast")
        self.assertTrue(k.startswith("url:https://podcasts.apple.com/"))


class HashTest(unittest.TestCase):
    def test_whitespace_differences_stable(self):
        a = I.body_sha256("第一行\n\n第二行  內容\t結尾\n")
        b = I.body_sha256("  第一行 第二行 內容 結尾")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_content_difference_changes_hash(self):
        self.assertNotEqual(I.body_sha256("甲乙"), I.body_sha256("甲丙"))

    def test_non_string_rejected(self):
        with self.assertRaises(TypeError):
            I.body_sha256(None)


if __name__ == "__main__":
    unittest.main()
