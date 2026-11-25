"""T009：資料匣——區塊解析、驗證、路徑守衛（realpath／符號連結）、掃描、建檔、搬檔。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import external_content_inbox as I  # noqa: E402

BLOCK = ("---\nsource_type: youtube\nurl: https://www.youtube.com/watch?v=AAAAAAAAAAA\n"
         "title: 標題: 含冒號\nauthor: 頻道\ndate: 2026-11-19\nguid:\n---\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ec-inbox-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)

    def put(self, name, text):
        inbox, _ = I.ensure_dirs(self.data)
        with open(os.path.join(inbox, name), "w", encoding="utf-8") as f:
            f.write(text)
        return os.path.join(inbox, name)


class ParseTest(unittest.TestCase):
    def test_basic_parse_colon_value_comments_unknown(self):
        text = ("---\n# 註解\n\nsource_type: youtube\nurl: https://youtu.be/AAAAAAAAAAA?t=3\n"
                "title: 標題: 含冒號\nauthor: 頻道\ndate: 2026-11-19\nfoo: bar\n---\n內文第一行\n第二行")
        meta, body, unknown = I.parse_inbox_text(text)
        self.assertEqual(meta["title"], "標題: 含冒號")
        self.assertEqual(meta["url"], "https://youtu.be/AAAAAAAAAAA?t=3")
        self.assertEqual(unknown, ["foo"])
        self.assertEqual(body, "內文第一行\n第二行")

    def test_crlf_and_bom(self):
        text = "﻿---\r\nsource_type: article\r\nurl: https://a.com/x\r\ntitle: t\r\nauthor: a\r\ndate: 2026-01-02\r\n---\r\n內文"
        meta, body, _ = I.parse_inbox_text(text)
        self.assertEqual(meta["source_type"], "article")
        self.assertEqual(body.strip(), "內文")

    def test_unparseable_blocks(self):
        for bad, frag in (("沒有區塊\n---\n", "第一行"),
                          ("---\nsource_type: youtube\n沒有冒號\n---\n", "第 3 行"),
                          ("---\nsource_type: youtube\nurl: x", "結束")):
            with self.assertRaises(I.InboxError) as cm:
                I.parse_inbox_text(bad)
            self.assertIn(frag, str(cm.exception))

    def test_validate_missing_and_formats(self):
        meta, _, _ = I.parse_inbox_text(BLOCK)
        ok = I.validate_meta(meta)
        self.assertEqual(ok["source_type"], "youtube")
        self.assertIsNone(ok["guid"])
        m = dict(meta)
        del m["author"]
        del m["title"]
        with self.assertRaises(I.InboxError) as cm:
            I.validate_meta(m)
        self.assertIn("author", str(cm.exception))
        self.assertIn("title", str(cm.exception))

    def test_validate_missing_url_is_specific(self):
        meta, _, _ = I.parse_inbox_text(BLOCK)
        meta["url"] = ""
        with self.assertRaises(I.InboxError) as cm:
            I.validate_meta(meta)
        self.assertIn("連結", str(cm.exception))

    def test_validate_bad_source_type_date_url(self):
        meta, _, _ = I.parse_inbox_text(BLOCK)
        for k, v, frag in (("source_type", "blog", "source_type"), ("date", "2026/11/19", "YYYY-MM-DD"),
                           ("date", "2026-02-30", "日曆"), ("url", "ftp://x.com/a", "http"),
                           ("url", "不是網址", "http")):
            m = dict(meta)
            m[k] = v
            with self.assertRaises(I.InboxError, msg=(k, v)) as cm:
                I.validate_meta(m)
            self.assertIn(frag, str(cm.exception))

    def test_source_type_case_insensitive(self):
        meta, _, _ = I.parse_inbox_text(BLOCK)
        meta["source_type"] = "YouTube"
        self.assertEqual(I.validate_meta(meta)["source_type"], "youtube")

    def test_body_empty_including_fullwidth_space(self):
        for b in ("", "  \n\t ", "　　\n"):
            with self.assertRaises(I.InboxError) as cm:
                I.check_body(b)
            self.assertIn("內文為空", str(cm.exception))
        self.assertEqual(I.check_body("有內容"), "有內容")

    def test_duplicate_block_in_body(self):
        body = "\n\n" + BLOCK + "\n逐字稿"
        with self.assertRaises(I.InboxError) as cm:
            I.check_body(body)
        self.assertIn("重複的中繼資料區塊", str(cm.exception))
        # 一般分隔線（--- 之間不是 key: value）不誤判
        self.assertEqual(I.check_body("---\n這是分隔線後的一般文字\n---\n更多"), "---\n這是分隔線後的一般文字\n---\n更多")


class ScanAndGuardTest(Base):
    def test_ensure_dirs_created(self):
        inbox, processed = I.ensure_dirs(self.data)
        self.assertTrue(os.path.isdir(inbox) and os.path.isdir(processed))

    def test_scan_top_level_only_with_skipped(self):
        self.put("a.md", BLOCK + "x")
        self.put("b.TXT", BLOCK + "x")
        self.put("c.rtf", "x")
        self.put(".DS_Store", "x")
        _, processed = I.ensure_dirs(self.data)
        with open(os.path.join(processed, "old.md"), "w") as f:
            f.write("x")
        pending, skipped = I.list_pending(self.data)
        self.assertEqual(pending, ["a.md", "b.TXT"])
        self.assertEqual(skipped, ["c.rtf"])

    def test_basename_validation(self):
        for bad in ("../x.md", "processed/x.md", "/etc/passwd", "a/b.md", "..", "processed", "", "a\\b.md"):
            with self.assertRaises(I.InboxError, msg=bad):
                I.validate_basename(bad)
        self.assertEqual(I.validate_basename("ok.md"), "ok.md")

    def test_read_ok_and_missing(self):
        self.put("a.md", "內容")
        self.assertEqual(I.read_inbox_file(self.data, "a.md"), "內容")
        with self.assertRaises(FileNotFoundError):
            I.read_inbox_file(self.data, "nope.md")

    def test_read_rejects_processed_path(self):
        _, processed = I.ensure_dirs(self.data)
        with open(os.path.join(processed, "x.md"), "w") as f:
            f.write("x")
        with self.assertRaises(I.InboxError):
            I.read_inbox_file(self.data, "processed/x.md")

    def test_symlink_escaping_inbox_rejected(self):
        outside = os.path.join(self.tmp, "secret.txt")
        with open(outside, "w") as f:
            f.write("機密")
        inbox, _ = I.ensure_dirs(self.data)
        os.symlink(outside, os.path.join(inbox, "link.md"))
        with self.assertRaises(I.InboxError) as cm:
            I.read_inbox_file(self.data, "link.md")
        self.assertIn("資料匣最上層", str(cm.exception))

    def test_symlink_into_processed_rejected(self):
        inbox, processed = I.ensure_dirs(self.data)
        target = os.path.join(processed, "x.md")
        with open(target, "w") as f:
            f.write("x")
        os.symlink(target, os.path.join(inbox, "l.md"))
        with self.assertRaises(I.InboxError):
            I.read_inbox_file(self.data, "l.md")

    def test_data_dir_itself_is_symlink(self):
        # 模擬 AlphaVibe-prod/poc/data -> AlphaVibe/poc/data
        real = os.path.join(self.tmp, "real-data")
        os.makedirs(real)
        link = os.path.join(self.tmp, "prod-data")
        os.symlink(real, link)
        inbox, _ = I.ensure_dirs(link)
        with open(os.path.join(inbox, "a.md"), "w", encoding="utf-8") as f:
            f.write("經由符號連結資料目錄")
        self.assertEqual(I.list_pending(link)[0], ["a.md"])
        self.assertEqual(I.read_inbox_file(link, "a.md"), "經由符號連結資料目錄")
        newname = I.move_to_processed(link, "a.md")
        self.assertTrue(os.path.exists(os.path.join(real, "inbox", "processed", newname)))
        self.assertFalse(os.path.exists(os.path.join(real, "inbox", "a.md")))

    def test_var_private_var_equivalence(self):
        # macOS：/var -> /private/var；用「另一種寫法」的資料目錄也要能讀
        real = os.path.realpath(self.data)
        alt = self.data if real != os.path.abspath(self.data) else real
        self.put("a.md", "x")
        self.assertEqual(I.read_inbox_file(alt, "a.md"), "x")
        self.assertEqual(I.read_inbox_file(real, "a.md"), "x")

    def test_size_limit_and_encoding(self):
        self.put("big.md", "字" * (I.MAX_FILE_CHARS + 1))
        with self.assertRaises(I.InboxError) as cm:
            I.read_inbox_file(self.data, "big.md")
        self.assertIn("過大", str(cm.exception))
        self.put("ok.md", "字" * I.MAX_FILE_CHARS)
        self.assertEqual(len(I.read_inbox_file(self.data, "ok.md")), I.MAX_FILE_CHARS)
        inbox, _ = I.ensure_dirs(self.data)
        with open(os.path.join(inbox, "bad.md"), "wb") as f:
            f.write(b"\xff\xfe\x00bad")
        with self.assertRaises(I.InboxError) as cm:
            I.read_inbox_file(self.data, "bad.md")
        self.assertIn("UTF-8", str(cm.exception))


class MoveAndCreateTest(Base):
    def test_move_no_overwrite_adds_sequence(self):
        _, processed = I.ensure_dirs(self.data)
        for i, text in enumerate(("甲", "乙", "丙")):
            self.put("a.md", text)
            newname = I.move_to_processed(self.data, "a.md")
            self.assertEqual(newname, "a.md" if i == 0 else "a-%d.md" % i)
        got = sorted(os.listdir(processed))
        self.assertEqual(got, ["a-1.md", "a-2.md", "a.md"])
        with open(os.path.join(processed, "a.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "甲")
        self.assertEqual(I.list_pending(self.data)[0], [])

    def test_move_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            I.move_to_processed(self.data, "gone.md")

    def test_build_filename_rules(self):
        n = I.build_inbox_filename("2026-11-19", "標題: a/b?*  c", "youtube:AAAAAAAAAAA")
        self.assertTrue(n.startswith("2026-11-19_標題_a_b_c_"), n)
        self.assertTrue(n.endswith(".md"))
        long = I.build_inbox_filename("2026-11-19", "長" * 300, "youtube:AAAAAAAAAAA")
        self.assertLessEqual(len(long[:-3]), 80)
        self.assertEqual(long, I.build_inbox_filename("2026-11-19", "長" * 300, "youtube:AAAAAAAAAAA"))
        self.assertIn("untitled", I.build_inbox_filename("2026-11-19", "???", "k"))

    def test_create_pending_file_round_trip_no_overwrite_no_temp(self):
        meta = I.validate_meta(I.parse_inbox_text(BLOCK)[0])
        p1 = I.create_pending_file(self.data, meta, "youtube:AAAAAAAAAAA")
        p2 = I.create_pending_file(self.data, meta, "youtube:AAAAAAAAAAA")
        self.assertNotEqual(p1, p2)
        self.assertTrue(p2.endswith("-1.md"))
        inbox, _ = I.ensure_dirs(self.data)
        self.assertEqual(os.path.dirname(p1), os.path.realpath(inbox))
        self.assertEqual(len(os.listdir(inbox)), 3)   # 兩個檔＋processed/，沒有暫存殘留
        with open(p1, encoding="utf-8") as f:
            text = f.read()
        m2, body, unknown = I.parse_inbox_text(text)
        self.assertEqual(m2["title"], "標題: 含冒號")
        self.assertEqual(unknown, [])
        with self.assertRaises(I.InboxError):
            I.check_body(body)       # 內文留空

    def test_create_failure_leaves_no_partial_file(self):
        meta = I.validate_meta(I.parse_inbox_text(BLOCK)[0])
        I.ensure_dirs(self.data)
        orig = I._unique_link

        def boom(*a, **k):
            raise OSError("磁碟已滿")
        I._unique_link = boom
        try:
            with self.assertRaises(I.InboxError) as cm:
                I.create_pending_file(self.data, meta, "k")
        finally:
            I._unique_link = orig
        self.assertIn("建檔失敗", str(cm.exception))
        inbox, _ = I.inbox_paths(self.data)
        self.assertEqual(os.listdir(inbox), ["processed"])

    def test_find_pending_by_source_key(self):
        self.put("a.md", BLOCK)
        self.put("broken.md", "沒有區塊")
        found = I.find_pending_by_source_key(self.data, "youtube:AAAAAAAAAAA")
        self.assertTrue(found.endswith("a.md"))
        self.assertIsNone(I.find_pending_by_source_key(self.data, "youtube:BBBBBBBBBBB"))


if __name__ == "__main__":
    unittest.main()
