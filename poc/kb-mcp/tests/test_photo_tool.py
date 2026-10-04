"""`photo_tool.py`／`photo_formats.py` 測試：依日期整理（預覽/搬移/復原/
不覆蓋）、評分（JPG 寫檔內、X3F 寫 sidecar、Finder ★ 標籤）、HEIC 匯入縮圖。

需要 macOS（sips、xattr）與 exiftool；沒有 exiftool 時整批略過。
執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_tool*"
"""
import base64
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import photo_tool  # noqa: E402
from photo_formats import (  # noqa: E402
    find_exiftool, make_jpeg, sidecar_path, uses_sidecar, is_photo)
from photo_importer import (  # noqa: E402
    VALID_EXTENSIONS, commit_import, scan_folder)
from photo_metadata_sync import read_existing_tags, write_metadata  # noqa: E402
from photo_store import PhotoStore  # noqa: E402
from test_photo_importer import _TINY_JPEG_B64  # noqa: E402

EXIFTOOL = find_exiftool()


def _write_jpeg(path, date=None, variant=b""):
    with open(path, "wb") as f:
        f.write(base64.b64decode(_TINY_JPEG_B64) + variant)
    if date:
        subprocess.run([EXIFTOOL, "-overwrite_original",
                        "-DateTimeOriginal=%s" % date, path],
                       check=True, capture_output=True)


def _finder_tags(path):
    r = subprocess.run(["xattr", "-px", photo_tool.USER_TAGS_ATTR, path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [t.split("\n")[0] for t in plistlib.loads(
        bytes.fromhex(r.stdout.replace("\n", "").replace(" ", "")))]


def _rating(path):
    out = subprocess.run([EXIFTOOL, "-s3", "-Rating", path],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out else 0


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class FormatsTest(unittest.TestCase):
    def test_extension_sets(self):
        for ext in (".jpg", ".heic", ".x3f", ".cr3", ".arw", ".dng"):
            self.assertIn(ext, VALID_EXTENSIONS)
        self.assertTrue(uses_sidecar("a.X3F"))
        self.assertFalse(uses_sidecar("a.jpg"))
        self.assertFalse(uses_sidecar("a.dng"))
        self.assertTrue(is_photo("/x/IMG.HEIC"))
        self.assertFalse(is_photo("/x/a.xmp"))
        self.assertEqual(sidecar_path("/x/SDIM0071.X3F"), "/x/SDIM0071.xmp")

    def test_make_jpeg_does_not_upscale(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "a.jpg"), os.path.join(d, "t.jpg")
            _write_jpeg(src)  # 8x8
            make_jpeg(src, dst, 512)
            out = subprocess.run(["sips", "-g", "pixelWidth", dst],
                                 capture_output=True, text=True).stdout
            self.assertIn("pixelWidth: 8", out)


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class OrganizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-tool-")
        self.hist = tempfile.mkdtemp(prefix="photo-hist-")
        self._old = photo_tool.HISTORY_DIR
        photo_tool.HISTORY_DIR = self.hist
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(shutil.rmtree, self.hist, True)
        self.addCleanup(setattr, photo_tool, "HISTORY_DIR", self._old)

    def _p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def test_groups_move_together_and_undo(self):
        _write_jpeg(self._p("A.jpg"), "2026:08:15 10:00:00")
        _write_jpeg(self._p("B.jpg"), "2026:08:16 10:00:00")
        with open(self._p("A.xmp"), "w") as f:
            f.write("<x/>")
        plan = photo_tool.plan_organize(self.tmp)
        self.assertEqual({m["date"] for m in plan["moves"]},
                         {"2026-08-15", "2026-08-16"})
        self.assertEqual(len(plan["moves"]), 3)  # A.jpg + A.xmp + B.jpg
        # 預覽不動檔案
        self.assertTrue(os.path.exists(self._p("A.jpg")))

        log = photo_tool.apply_organize(plan)
        self.assertTrue(os.path.exists(self._p("2026-08-15", "A.jpg")))
        self.assertTrue(os.path.exists(self._p("2026-08-15", "A.xmp")))
        self.assertTrue(os.path.exists(self._p("2026-08-16", "B.jpg")))
        self.assertFalse(os.path.exists(self._p("A.jpg")))

        restored, skipped = photo_tool.undo(log)
        self.assertEqual((restored, skipped), (3, []))
        self.assertTrue(os.path.exists(self._p("A.jpg")))
        self.assertFalse(os.path.exists(self._p("2026-08-15")))  # 空資料夾已清除

    def test_never_overwrites_and_skips_identical(self):
        _write_jpeg(self._p("A.jpg"), "2026:08:15 10:00:00")
        os.makedirs(self._p("2026-08-15"))
        # 同名但內容不同 → 不覆蓋，改名 _1
        _write_jpeg(self._p("2026-08-15", "A.jpg"), "2026:08:15 11:00:00",
                    variant=b"\x00")
        # 另一張內容與目的地完全相同 → 視為重複，保留原位
        shutil.copy(self._p("2026-08-15", "A.jpg"), self._p("B.jpg"))
        os.rename(self._p("B.jpg"), self._p("A2.jpg"))
        shutil.copy(self._p("2026-08-15", "A.jpg"), self._p("A.jpg"))
        plan = photo_tool.plan_organize(self.tmp)
        photo_tool.apply_organize(plan)
        names = sorted(os.listdir(self._p("2026-08-15")))
        self.assertIn("A.jpg", names)
        self.assertEqual(len([n for n in names if n.startswith("A")]) >= 2, True)

    def test_no_exif_is_reported(self):
        _write_jpeg(self._p("NOEXIF.jpg"))
        plan = photo_tool.plan_organize(self.tmp)
        self.assertEqual(plan["no_exif"], [self._p("NOEXIF.jpg")])
        self.assertEqual(len(plan["moves"]), 1)

    def test_already_in_place_is_skipped(self):
        os.makedirs(self._p("2026-08-15"))
        _write_jpeg(self._p("2026-08-15", "A.jpg"), "2026:08:15 10:00:00")
        plan = photo_tool.plan_organize(self.tmp, recursive=True)
        self.assertEqual(plan["moves"], [])
        self.assertEqual(plan["in_place"], 1)


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class OrganizeGuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-gui-")
        self.hist = tempfile.mkdtemp(prefix="photo-hist-")
        self._old = photo_tool.HISTORY_DIR
        photo_tool.HISTORY_DIR = self.hist
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(shutil.rmtree, self.hist, True)
        self.addCleanup(setattr, photo_tool, "HISTORY_DIR", self._old)
        _write_jpeg(os.path.join(self.tmp, "A.jpg"), "2026:08:15 10:00:00")
        self.notes = []

    def test_cancel_moves_nothing(self):
        moved = photo_tool.organize_gui(
            self.tmp, ask=lambda m, ok: False, notify=self.notes.append)
        self.assertFalse(moved)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "A.jpg")))
        self.assertEqual(os.listdir(self.hist), [])

    def test_confirm_moves_and_undo_gui_restores(self):
        asked = []
        moved = photo_tool.organize_gui(
            self.tmp, ask=lambda m, ok: asked.append(m) or True,
            notify=self.notes.append)
        self.assertTrue(moved)
        self.assertIn("2026-08-15", asked[0])  # 確認視窗有列出日期
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "2026-08-15", "A.jpg")))
        self.assertTrue(photo_tool.undo_gui(
            ask=lambda m, ok: True, notify=self.notes.append))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "A.jpg")))

    def test_nothing_to_do_and_no_history(self):
        empty = tempfile.mkdtemp(prefix="photo-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertFalse(photo_tool.organize_gui(
            empty, ask=lambda m, ok: True, notify=self.notes.append))
        self.assertFalse(photo_tool.undo_gui(
            ask=lambda m, ok: True, notify=self.notes.append))


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class RateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-rate-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_jpeg_rating_in_file_with_finder_tag(self):
        p = os.path.join(self.tmp, "a.jpg")
        _write_jpeg(p)
        ok, failed = photo_tool.rate_files([p], 4)
        self.assertEqual((ok, failed), ([p], []))
        self.assertEqual(_rating(p), 4)
        self.assertEqual(_finder_tags(p), ["★4"])
        photo_tool.rate_files([p], 2)
        self.assertEqual(_rating(p), 2)
        self.assertEqual(_finder_tags(p), ["★2"])  # 舊星等標籤被取代
        photo_tool.rate_files([p], 0)
        self.assertEqual(_rating(p), 0)
        self.assertEqual(_finder_tags(p), [])

    def test_keeps_users_other_finder_tags(self):
        p = os.path.join(self.tmp, "a.jpg")
        _write_jpeg(p)
        data = plistlib.dumps(["旅行\n0"], fmt=plistlib.FMT_BINARY).hex()
        subprocess.run(["xattr", "-wx", photo_tool.USER_TAGS_ATTR, data, p], check=True)
        photo_tool.rate_files([p], 3)
        self.assertEqual(sorted(_finder_tags(p)), ["★3", "旅行"])

    def test_raw_rating_goes_to_sidecar_and_raw_untouched(self):
        raw = os.path.join(self.tmp, "SDIM0071.X3F")
        with open(raw, "wb") as f:
            f.write(b"FOVb" + b"\x00" * 64)  # 假 RAW，只驗證沒被改寫
        before = open(raw, "rb").read()
        ok, failed = photo_tool.rate_files([raw], 5)
        self.assertEqual(failed, [])
        self.assertEqual(open(raw, "rb").read(), before)  # 原檔位元組不動
        self.assertEqual(_rating(sidecar_path(raw)), 5)
        self.assertEqual(_finder_tags(raw), ["★5"])

    def test_pair_is_rated_once_as_group(self):
        raw = os.path.join(self.tmp, "SDIM0071.X3F")
        jpg = os.path.join(self.tmp, "SDIM0071.jpg")
        with open(raw, "wb") as f:
            f.write(b"FOVb" + b"\x00" * 64)
        _write_jpeg(jpg)
        ok, failed = photo_tool.rate_files([jpg], 3)  # 只選 JPG
        self.assertEqual(failed, [])
        self.assertEqual(sorted(ok), sorted([raw, jpg]))
        self.assertEqual(_rating(jpg), 3)
        self.assertEqual(_rating(sidecar_path(raw)), 3)

    def test_write_metadata_preserves_finder_tags(self):
        p = os.path.join(self.tmp, "a.jpg")
        _write_jpeg(p)
        photo_tool.rate_files([p], 3)
        write_metadata(p, ["夕陽"], 5)  # AlphaVibe 寫回流程
        self.assertEqual(_rating(p), 5)
        self.assertEqual(_finder_tags(p), ["★3"])  # 標籤沒被 exiftool 丟掉

    def test_sidecar_metadata_sync_roundtrip(self):
        raw = os.path.join(self.tmp, "X.cr3")
        with open(raw, "wb") as f:
            f.write(b"\x00" * 64)
        write_metadata(raw, ["夕陽", "京都"], 4)
        tags, rating = read_existing_tags(raw)
        self.assertEqual(rating, 4)
        self.assertEqual(sorted(tags), ["京都", "夕陽"])
        self.assertEqual(open(raw, "rb").read(), b"\x00" * 64)


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class HeicImportTest(unittest.TestCase):
    def test_heic_is_scanned_and_gets_512_thumbnail_not_upscaled(self):
        tmp = tempfile.mkdtemp(prefix="photo-heic-")
        self.addCleanup(shutil.rmtree, tmp, True)
        src = os.path.join(tmp, "big.jpg")
        # 造一張夠大的 HEIC：先用 sips 把 8x8 jpg 放大到 1200 像素再轉 heic
        tiny = os.path.join(tmp, "tiny.jpg")
        _write_jpeg(tiny)
        subprocess.run(["sips", "-z", "800", "1200", tiny, "--out", src],
                       check=True, capture_output=True)
        heic = os.path.join(tmp, "IMG_0001.heic")
        proc = subprocess.run(["sips", "-s", "format", "heic", src, "--out", heic],
                              capture_output=True)
        if proc.returncode != 0 or not os.path.exists(heic):
            self.skipTest("此機器 sips 無法產生 HEIC")
        os.remove(src)
        os.remove(tiny)
        store = PhotoStore(os.path.join(tmp, "data"))
        self.addCleanup(store.close)
        scan = scan_folder(tmp, store)
        self.assertEqual([f["filename"] for f in scan["new_files"]], ["IMG_0001.heic"])
        result = commit_import(
            scan["new_files"], "internal", os.path.join(tmp, "dest"),
            os.path.join(tmp, "thumbs"), store)
        self.assertEqual(result["failed"], [])
        photo = store.get_photo(result["imported_photo_ids"][0])
        out = subprocess.run(["sips", "-g", "pixelWidth", photo["thumbnail_path"]],
                             capture_output=True, text=True).stdout
        self.assertIn("pixelWidth: 512", out)


if __name__ == "__main__":
    unittest.main()
