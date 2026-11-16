"""010 T035：長圖切片（規劃／尺寸讀取／位元組檢查／合併去重＋瀏覽器端實際切片）。
全部用程式生成的合成圖，不連網、不碰正式資料；需要瀏覽器的測試沒有瀏覽器時略過。"""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_image_tiles as T  # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REAL_SAMPLE_GLOB_DIR = os.path.join(HERE, "..", "data-test-articles", "articles_images")


def _browser_available():
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    return (os.path.exists(node)
            and os.path.isdir(os.path.join(HERE, "scraper", "node_modules", "playwright"))
            and (os.path.exists("/Applications/Google Chrome.app")
                 or os.path.isdir(os.path.expanduser("~/Library/Caches/ms-playwright"))))


# ── 合成圖 ──────────────────────────────────────────────────────────────────────────
PERIOD, TEXT_H = 70, 40          # 每 70 列一組：前 40 列是「文字列」（深色橫帶），後 30 列是空白帶


def is_text_row(y):
    return (y % PERIOD) < TEXT_H


def blank_bands(height):
    """合成表格圖的空白帶（原尺寸座標）。"""
    return [[y0 + TEXT_H, min(y0 + PERIOD, height)] for y0 in range(0, height, PERIOD) if y0 + TEXT_H < height]


def make_table_png(width, height):
    """白底、直向格線（模擬表格框線，連空白帶也有）、文字列用深色方塊模擬。"""
    def row(text):
        px = [(255, 255, 255)] * width
        buf = bytearray(b"\xff" * (width * 3))
        for cx in range(6):                                  # 6 條 2px 直線
            x = int(width * (cx + 0.5) / 6)
            buf[x * 3:(x + 2) * 3] = b"\x99\x99\x99" * 2
        if text:
            for x0 in range(int(width * 0.04), int(width * 0.96), max(60, width // 12)):
                x1 = min(width, x0 + max(30, width // 20))
                buf[x0 * 3:x1 * 3] = b"\x20\x20\x30" * (x1 - x0)
        return b"\x00" + bytes(buf)
    r_text, r_blank = row(True), row(False)
    raw = b"".join(r_text if is_text_row(y) else r_blank for y in range(height))
    return _png_from_raw(width, height, raw)


def _png_from_raw(width, height, raw):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def make_jpeg_header(width, height):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dht = b"\xff\xc4" + struct.pack(">H", 5) + b"\x00\x00\x00"          # DHT 不是 SOF，必須被略過
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + dht + sof + b"\xff\xd9"


class SizeReadingTest(unittest.TestCase):
    def test_png_ihdr(self):
        self.assertEqual(T.image_size(make_table_png(37, 11)), (37, 11))

    def test_jpeg_sof_skips_other_markers(self):
        self.assertEqual(T.image_size(make_jpeg_header(1234, 5678)), (1234, 5678))

    def test_gif_and_webp_vp8x(self):
        self.assertEqual(T.image_size(b"GIF89a" + struct.pack("<HH", 30, 20) + b"\x00" * 8), (30, 20))
        vp8x = (b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x0a\x00\x00\x00" + b"\x00" * 4
                + (99).to_bytes(3, "little") + (49).to_bytes(3, "little"))
        self.assertEqual(T.image_size(vp8x), (100, 50))

    def test_garbage_returns_none(self):
        self.assertIsNone(T.image_size(b"not an image"))
        self.assertIsNone(T.image_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 3))
        self.assertIsNone(T.image_size(b"\xff\xd8\xff\xe0\x00"))

    def test_real_samples_size_readable_and_long_image_rule_consistent_local_only(self):
        """只讀本機真實樣本的尺寸（不送任何網路）。不假設樣本是短圖或長圖——回補會讓樣本變動，
        只斷言「尺寸讀得出來」且「長圖判定與定義（高/寬≥1.5 且高≥2000）一致」。"""
        found = []
        if os.path.isdir(REAL_SAMPLE_GLOB_DIR):
            for d in sorted(os.listdir(REAL_SAMPLE_GLOB_DIR)):
                p = os.path.join(REAL_SAMPLE_GLOB_DIR, d, "1.png")
                if os.path.exists(p):
                    found.append(p)
        if not found:
            self.skipTest("沒有本機真實樣本")
        for path in found:
            with open(path, "rb") as f:                       # 唯讀，只讀尺寸
                size = T.image_size(f.read())
            self.assertIsNotNone(size)
            w, h = size
            self.assertEqual(T.is_long_image(w, h), (h / float(w) >= 1.5 and h >= 2000))


class LimitsTest(unittest.TestCase):
    def test_long_image_judgement(self):
        self.assertTrue(T.is_long_image(2190, 5195))
        self.assertFalse(T.is_long_image(1653, 993))
        self.assertFalse(T.is_long_image(1000, 1999))         # 高不足 2000
        self.assertFalse(T.is_long_image(2000, 2400))         # 比例 <1.5
        self.assertTrue(T.is_long_image(1000, 2000))

    def test_constants_are_named_at_top(self):
        self.assertEqual((T.MAX_EDGE_PX, T.PATCH_PX, T.MAX_VISION_TOKENS, T.MAX_IMAGE_SIDE_PX, T.MAX_TILES),
                         (2576, 28, 4784, 8000, 8))

    def test_check_tile_bytes(self):
        self.assertTrue(T.check_tile_bytes(1000))
        self.assertTrue(T.check_tile_bytes(7_500_000))        # base64 後恰 10,000,000
        self.assertFalse(T.check_tile_bytes(7_500_001))
        self.assertFalse(T.check_tile_bytes(50 * 1024 * 1024))
        self.assertFalse(T.check_tile_bytes(-1))

    def test_tile_max_height(self):
        self.assertEqual(T.tile_max_height(2190), 1680)       # 4784//79=60 → 60×28
        self.assertEqual(T.tile_max_height(1000), 800)        # 寬×0.8 較小
        for w in (300, 1000, 2190, 2576):
            h = T.tile_max_height(w)
            self.assertLessEqual(T.vision_tokens(w, h), T.MAX_VISION_TOKENS)


class PlanTest(unittest.TestCase):
    def assert_plan_valid(self, plan, check_text_rows=True):
        th = T.tile_max_height(plan.width)
        ov_min = max(-(-th * 15 // 100), T.OVERLAP_MIN_PX)
        self.assertEqual(plan.status, "ok", plan.reason)
        self.assertLessEqual(len(plan.tiles), T.MAX_TILES)
        self.assertEqual(plan.tiles[0][0], 0)
        self.assertEqual(plan.tiles[-1][1], plan.height)
        for top, bottom in plan.tiles:
            self.assertLessEqual(plan.width, T.MAX_EDGE_PX)
            self.assertLessEqual(bottom - top, th)
            self.assertLessEqual(T.vision_tokens(plan.width, bottom - top), T.MAX_VISION_TOKENS)
        for (t1, b1), (t2, b2) in zip(plan.tiles, plan.tiles[1:]):
            overlap = b1 - t2
            self.assertGreaterEqual(overlap, ov_min)
            self.assertGreaterEqual(overlap, 0.15 * (b1 - t1))
            self.assertGreaterEqual(overlap, 200)
            self.assertGreater(t2, t1)

    def test_2190x5195_tile_count_and_overlap(self):
        plan = T.plan_tiles(2190, 5195, blank_bands(5195))
        self.assert_plan_valid(plan)
        self.assertEqual(len(plan.tiles), 4)
        self.assertFalse(plan.resized)

    def test_cuts_avoid_text_rows(self):
        plan = T.plan_tiles(2190, 5195, blank_bands(5195))
        for top, bottom in plan.tiles[1:]:
            self.assertFalse(is_text_row(top), "片頂 %d 落在文字列" % top)
        for top, bottom in plan.tiles[:-1]:
            self.assertFalse(is_text_row(bottom - 1), "片底 %d 落在文字列" % (bottom - 1))

    def test_without_bands_still_overlaps_and_fits(self):
        self.assert_plan_valid(T.plan_tiles(2190, 5195, None))

    def test_too_many_tiles_reports_untranscribed(self):
        plan = T.plan_tiles(2190, 20000, blank_bands(20000))
        self.assertEqual((plan.status, plan.reason), ("untranscribed", "too_many_tiles"))
        self.assertEqual(plan.tiles, [])

    def test_short_image_not_tiled(self):
        plan = T.plan_tiles(1653, 993)
        self.assertEqual((plan.status, plan.tiles, plan.resized), ("ok", [(0, 993)], False))
        self.assertTrue(plan.single_whole)

    def test_not_long_but_violates_limits_is_tiled(self):
        plan = T.plan_tiles(2000, 1900)                        # 非長圖，但 token 4896 >4784
        self.assert_plan_valid(plan)
        self.assertGreater(len(plan.tiles), 1)

    def test_wide_image_is_resized_first_and_flagged(self):
        plan = T.plan_tiles(3000, 7000, None)
        self.assertTrue(plan.resized)
        self.assertEqual((plan.width, plan.height, plan.scale_width), (2576, 6011, 2576))
        self.assert_plan_valid(plan)
        self.assertGreater(len(plan.tiles), 1)                 # 不得因寬度超限就整張送

    def test_wide_but_short_image_resized_single_tile(self):
        plan = T.plan_tiles(4000, 1000)
        self.assertTrue(plan.resized)
        self.assertEqual((plan.width, plan.height, plan.tiles), (2576, 644, [(0, 644)]))
        self.assertFalse(plan.single_whole)                    # 需要經 Node 縮圖

    def test_resized_but_still_too_many_tiles(self):
        plan = T.plan_tiles(5000, 30000, None)
        self.assertTrue(plan.resized)
        self.assertEqual((plan.status, plan.reason), ("untranscribed", "too_many_tiles"))

    def test_tiny_width_cannot_be_tiled(self):
        plan = T.plan_tiles(200, 3000)
        self.assertEqual(plan.status, "untranscribed")


class MergeTest(unittest.TestCase):
    def test_overlap_lines_removed(self):
        a = "表頭 A B C\n列1 100 200\n列2 300 400\n列3 500 600"
        b = "列2 300 400\n列3 500 600\n列4 700 800\n列5 900 1000"
        self.assertEqual(T.merge_transcripts([a, b]),
                         "表頭 A B C\n列1 100 200\n列2 300 400\n列3 500 600\n列4 700 800\n列5 900 1000")

    def test_whitespace_differences_ignored_and_blank_lines_skipped(self):
        a = "x 1\nrow  2  3\nrow 4 5"
        b = "\nrow 2 3\n\nrow 4  5\nrow 6 7"
        self.assertEqual(T.merge_transcripts([a, b]), "x 1\nrow  2  3\nrow 4 5\nrow 6 7")

    def test_no_overlap_keeps_everything(self):
        self.assertEqual(T.merge_transcripts(["a b c d\ne f g h", "i j k l"]), "a b c d\ne f g h\ni j k l")

    def test_short_single_line_coincidence_not_removed(self):
        self.assertEqual(T.merge_transcripts(["上\nN/A", "N/A\n下"]), "上\nN/A\nN/A\n下")

    def test_three_tiles_and_empty_input(self):
        out = T.merge_transcripts(["r1 aaaa\nr2 bbbb", "r2 bbbb\nr3 cccc", "r3 cccc\nr4 dddd"])
        self.assertEqual(out, "r1 aaaa\nr2 bbbb\nr3 cccc\nr4 dddd")
        self.assertEqual(T.merge_transcripts([]), "")


class OpenTilesNoBrowserTest(unittest.TestCase):
    """用假 runner／短圖驗證流程，不需瀏覽器。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_short_image_sent_whole_without_runner(self):
        p = self._write("s.png", make_table_png(300, 200))

        def boom(cfg):
            raise AssertionError("短圖不該呼叫 Node")
        with T.open_tiles(p, runner=boom) as ts:
            self.assertEqual((ts.status, ts.paths, ts.resized), ("ok", [p], False))
            (i, data, mt), = list(ts.iter_tile_bytes())
            self.assertEqual((i, mt), (1, "image/png"))
        self.assertTrue(os.path.exists(p))                    # 原圖不被清掉

    def test_unsupported_file_is_untranscribed(self):
        ts = T.open_tiles(self._write("x.bin", b"hello"))
        self.assertEqual((ts.status, ts.reason), ("untranscribed", "unsupported_or_corrupt_image"))
        self.assertEqual(list(ts.iter_tile_bytes()), [])

    def test_runner_failure_becomes_untranscribed(self):
        p = self._write("l.png", make_table_png(400, 2600))

        def fail(cfg):
            raise T.TilerError("no_browser")
        ts = T.open_tiles(p, runner=fail)
        self.assertEqual((ts.status, ts.reason), ("untranscribed", "tiler_failed:no_browser"))
        self.assertTrue(os.path.exists(p))

    def test_oversize_whole_image_rejected(self):
        p = self._write("s.png", make_table_png(300, 200))
        old = T.MAX_BASE64_BYTES
        T.MAX_BASE64_BYTES = 100
        self.addCleanup(setattr, T, "MAX_BASE64_BYTES", old)
        ts = T.open_tiles(p)
        self.assertEqual((ts.status, ts.reason), ("untranscribed", "tile_bytes_too_large"))

    def test_fake_runner_full_flow_and_oversize_tile_rejected(self):
        p = self._write("l.png", make_table_png(1000, 2600))   # 長圖（比例 6.5、高 ≥2000）
        calls = []

        def fake(cfg):
            calls.append(cfg["mode"])
            if cfg["mode"] == "bands":
                return [{"type": "bands", "width": 1000, "height": 2600, "bands": blank_bands(2600)}]
            out = []
            for i, (top, bottom) in enumerate(cfg["cuts"], 1):
                tp = os.path.join(cfg["out_dir"], "tile_%02d.png" % i)
                with open(tp, "wb") as f:
                    f.write(make_table_png(1000, bottom - top))
                out.append({"type": "tile", "index": i, "path": tp, "width": 1000, "height": bottom - top})
            return out
        ts = T.open_tiles(p, runner=fake, tmp_root=self.tmp)
        self.assertEqual((ts.status, calls), ("ok", ["bands", "slice"]))
        self.assertGreater(len(ts.paths), 1)
        tdir = os.path.dirname(ts.paths[0])
        ts.cleanup()
        self.assertFalse(os.path.exists(tdir))                # 暫存已清除
        old = T.MAX_BASE64_BYTES
        T.MAX_BASE64_BYTES = 100
        self.addCleanup(setattr, T, "MAX_BASE64_BYTES", old)
        ts2 = T.open_tiles(p, runner=fake, tmp_root=self.tmp)
        self.assertEqual((ts2.status, ts2.reason), ("untranscribed", "tile_bytes_too_large"))
        self.assertEqual(os.listdir(self.tmp), ["l.png"])     # 失敗也不留暫存


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class BrowserTilingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.long_png = os.path.join(cls.tmp, "long.png")
        with open(cls.long_png, "wb") as f:
            f.write(make_table_png(2190, 5195))
        with open(cls.long_png, "rb") as f:
            cls.long_bytes = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_band_detection_matches_synthetic_gaps_despite_vertical_lines(self):
        ev = T.run_tiler({"mode": "bands", "path": self.long_png})
        info = ev[0]
        self.assertEqual((info["width"], info["height"]), (2190, 5195))
        for y in range(5195):
            in_band = any(s <= y < e for s, e in info["bands"])
            self.assertEqual(in_band, not is_text_row(y), "列 %d" % y)

    def test_2190x5195_end_to_end(self):
        with T.open_tiles(self.long_png) as ts:
            self.assertEqual(ts.status, "ok")
            self.assertEqual(len(ts.paths), 4)
            plan = ts.plan
            tiles = list(ts.iter_tile_bytes())
            tdir = os.path.dirname(ts.paths[0])
            for (i, data, mt), (top, bottom) in zip(tiles, plan.tiles):
                self.assertEqual(mt, "image/png")
                self.assertEqual(T.image_size(data), (2190, bottom - top))
                self.assertLessEqual(T.vision_tokens(2190, bottom - top), T.MAX_VISION_TOKENS)
            for (t1, b1), (t2, b2) in zip(plan.tiles, plan.tiles[1:]):
                self.assertGreaterEqual(b1 - t2, 252)          # ≥15%×1680 且 ≥200
            for top, bottom in plan.tiles[1:]:
                self.assertFalse(is_text_row(top))
            for top, bottom in plan.tiles[:-1]:
                self.assertFalse(is_text_row(bottom - 1))
        self.assertFalse(os.path.exists(tdir))                 # 用完清除
        with open(self.long_png, "rb") as f:
            self.assertEqual(f.read(), self.long_bytes)        # 原圖完整保留

    def test_tile_pixels_are_the_expected_slice(self):
        """第一片的頂端從原圖第 0 列開始、輸出高度等於規劃的片高。"""
        with T.open_tiles(self.long_png) as ts:
            _, first, _ = next(ts.iter_tile_bytes())
            top, bottom = ts.plan.tiles[0]
            self.assertEqual((top, T.image_size(first)[1]), (0, bottom))

    def test_wide_image_resized_and_flagged(self):
        p = os.path.join(self.tmp, "wide.png")
        with open(p, "wb") as f:
            f.write(make_table_png(3000, 7000))
        with T.open_tiles(p) as ts:
            self.assertEqual(ts.status, "ok")
            self.assertTrue(ts.resized)
            self.assertGreater(len(ts.paths), 1)
            for i, data, mt in ts.iter_tile_bytes():
                w, h = T.image_size(data)
                self.assertEqual(w, 2576)
                self.assertLessEqual(T.vision_tokens(w, h), T.MAX_VISION_TOKENS)

    def test_wide_short_image_resized_single_tile(self):
        p = os.path.join(self.tmp, "wide_short.png")
        with open(p, "wb") as f:
            f.write(make_table_png(4000, 1000))
        with T.open_tiles(p) as ts:
            self.assertEqual((ts.status, ts.resized, len(ts.paths)), ("ok", True, 1))
            self.assertEqual(T.image_size(next(ts.iter_tile_bytes())[1]), (2576, 644))

    def test_too_many_tiles_real_browser_keeps_original(self):
        p = os.path.join(self.tmp, "huge.png")
        with open(p, "wb") as f:
            f.write(make_table_png(1500, 12000))               # 片高 1200、步長約 ≤1020 → >8 片
        ts = T.open_tiles(p)
        self.assertEqual((ts.status, ts.reason), ("untranscribed", "too_many_tiles"))
        self.assertTrue(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
