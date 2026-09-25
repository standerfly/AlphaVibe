"""`photo_importer.py` 測試：掃描去重、複製、縮圖、EXIF 讀取（best-effort）。

需要真正的 macOS `sips` 命令列工具（見 `research.md` §1），故這裡用一張
真實可解碼的最小 JPEG fixture（8x8 純色，base64 內嵌，不依賴 Pillow
在執行環境中存在——只在「產生 fixture」這個一次性動作用過 Pillow，
測試本身執行時不需要它）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_importer*"
"""
import base64
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from photo_importer import (  # noqa: E402
    scan_folder, commit_import, _compute_md5, external_volume_mounted)
from photo_metadata_sync import write_metadata  # noqa: E402
from photo_store import PhotoStore  # noqa: E402

# 8x8 純色 JPEG，632 bytes，無 EXIF（用於驗證「沒有 EXIF 時正確回傳
# None」這條路徑；「真的有相機 EXIF 時欄位名稱是否精確對應」未拿真實
# 相機 JPG 驗證過，見 photo_importer.py docstring 的已知風險）。
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEj"
    "JR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARES"
    "EhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx"
    "8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDE"
    "ooorjO8//9k="
)


def _write_tiny_jpeg(path):
    with open(path, "wb") as f:
        f.write(base64.b64decode(_TINY_JPEG_B64))


class ExternalVolumeMountedTest(unittest.TestCase):
    """2026-09-25：使用者要設定固定外接硬碟預設路徑時，程式碼審查發現
    `os.makedirs()` 在硬碟沒接時會悄悄在開機硬碟建立同名資料夾——這組
    測試驗證擋下這個情況的判斷邏輯。"""

    def test_true_when_volumes_mount_point_is_mounted(self):
        with mock.patch("os.path.ismount", return_value=True) as m:
            self.assertTrue(
                external_volume_mounted("/Volumes/macmini_ext8G/2026-import"))
            m.assert_called_once_with("/Volumes/macmini_ext8G")

    def test_false_when_volumes_mount_point_not_mounted(self):
        with mock.patch("os.path.ismount", return_value=False):
            self.assertFalse(
                external_volume_mounted("/Volumes/macmini_ext8G/2026-import"))

    def test_non_volumes_path_falls_back_to_isdir(self):
        tmp = tempfile.mkdtemp(prefix="external-volume-test-")
        try:
            self.assertTrue(external_volume_mounted(tmp))
            self.assertFalse(
                external_volume_mounted(os.path.join(tmp, "does-not-exist")))
        finally:
            shutil.rmtree(tmp)


class ScanFolderTest(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp(prefix="photo-import-src-")
        self.store_dir = tempfile.mkdtemp(prefix="photo-import-store-")
        self.store = PhotoStore(self.store_dir)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.source_dir)
        shutil.rmtree(self.store_dir)

    def test_finds_new_jpg_file(self):
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        result = scan_folder(self.source_dir, self.store)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["new_files"]), 1)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["unreadable"], [])
        self.assertEqual(result["new_files"][0]["filename"], "a.jpg")

    def test_ignores_non_image_files(self):
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        with open(os.path.join(self.source_dir, "notes.txt"), "w") as f:
            f.write("這不是照片")
        result = scan_folder(self.source_dir, self.store)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["new_files"][0]["filename"], "a.jpg")

    def test_skips_already_imported_hash(self):
        path = os.path.join(self.source_dir, "a.jpg")
        _write_tiny_jpeg(path)
        existing_hash = _compute_md5(path)
        self.store.add_photo(
            file_hash=existing_hash, storage_path="/tmp/already.jpg",
            storage_location="internal", thumbnail_path="/tmp/already-t.jpg")
        result = scan_folder(self.source_dir, self.store)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["new_files"], [])

    def test_invalid_source_path_raises(self):
        with self.assertRaises(ValueError):
            scan_folder("/path/does/not/exist", self.store)

    def test_two_identical_files_in_same_batch_dedupe_against_each_other(self):
        """匯入當下同一個資料夾裡就有兩份內容相同的檔案，第二份要算
        重複跳過，不能讓 commit_import() 因為 UNIQUE 約束衝突把它記成
        失敗（見 scan_folder() 的 seen_hashes_this_batch 修正）。"""
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        _write_tiny_jpeg(os.path.join(self.source_dir, "a-copy.jpg"))
        result = scan_folder(self.source_dir, self.store)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(len(result["new_files"]), 1)

    def test_same_content_produces_same_hash(self):
        p1 = os.path.join(self.source_dir, "a.jpg")
        p2 = os.path.join(self.source_dir, "b.jpg")
        _write_tiny_jpeg(p1)
        _write_tiny_jpeg(p2)
        self.assertEqual(_compute_md5(p1), _compute_md5(p2))


class CommitImportTest(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp(prefix="photo-import-src-")
        self.store_dir = tempfile.mkdtemp(prefix="photo-import-store-")
        self.dest_dir = tempfile.mkdtemp(prefix="photo-import-dest-")
        self.thumb_dir = tempfile.mkdtemp(prefix="photo-import-thumb-")
        self.store = PhotoStore(self.store_dir)

    def tearDown(self):
        self.store.close()
        for d in (self.source_dir, self.store_dir, self.dest_dir, self.thumb_dir):
            shutil.rmtree(d)

    def test_commit_raises_when_external_dest_not_mounted_and_writes_nothing(self):
        """2026-09-25：外接硬碟沒接時，commit_import 必須直接中止、
        不寫入任何檔案或資料庫紀錄——不能讓 os.makedirs() 悄悄在開機
        硬碟建立同名資料夾（見 external_volume_mounted() docstring）。"""
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        scan = scan_folder(self.source_dir, self.store)
        fake_external_dest = "/Volumes/definitely-not-a-real-mounted-drive-xyz/import"

        with mock.patch("photo_importer.external_volume_mounted", return_value=False):
            with self.assertRaises(RuntimeError):
                commit_import(
                    scan["new_files"], "external", fake_external_dest,
                    self.thumb_dir, self.store)

        self.assertEqual(self.store.list_albums(), [])  # sanity: store 可用
        self.assertIsNone(self.store.find_by_hash(scan["new_files"][0]["file_hash"]))
        self.assertFalse(os.path.exists("/Volumes/definitely-not-a-real-mounted-drive-xyz"))

    def test_commit_creates_photo_record_with_real_files_on_disk(self):
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        scan = scan_folder(self.source_dir, self.store)
        result = commit_import(
            scan["new_files"], "internal", self.dest_dir, self.thumb_dir,
            self.store)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["failed"], [])

        row = self.store.find_by_hash(scan["new_files"][0]["file_hash"])
        self.assertIsNotNone(row)
        self.assertTrue(os.path.exists(row["storage_path"]))
        self.assertTrue(os.path.exists(row["thumbnail_path"]))
        self.assertEqual(row["storage_location"], "internal")
        self.assertEqual(row["metadata_sync_status"], "pending")
        # 沒有相機 EXIF 的來源檔案，這幾個欄位應該是 None（見本檔案開頭
        # docstring 的已知風險：只驗證「沒有 EXIF 時正確回傳 None」）
        self.assertIsNone(row["camera_model"])
        self.assertIsNone(row["lens"])

    def test_reimport_same_source_after_commit_is_detected_as_duplicate(self):
        """`research.md` §4 的端到端驗證：即使檔案已經被複製、產生縮圖
        （目的地檔案的位元組跟原始來源不再是同一份實體檔案），重新掃描
        **同一個來源資料夾**（使用者電腦裡沒被 STND 動過的那份）仍必須
        被判定為重複。"""
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        first_scan = scan_folder(self.source_dir, self.store)
        commit_import(
            first_scan["new_files"], "internal", self.dest_dir,
            self.thumb_dir, self.store)

        second_scan = scan_folder(self.source_dir, self.store)
        self.assertEqual(second_scan["duplicate_count"], 1)
        self.assertEqual(second_scan["new_files"], [])

    def test_unreadable_file_skipped_without_aborting_batch(self):
        """一個壞檔＋一個好檔一起匯入：壞檔記入 `failed`，好檔仍成功
        （spec.md Edge Cases：無法讀取的檔案跳過，不中斷其餘匯入）。"""
        good_path = os.path.join(self.source_dir, "good.jpg")
        bad_path = os.path.join(self.source_dir, "bad.jpg")
        _write_tiny_jpeg(good_path)
        with open(bad_path, "wb") as f:
            f.write(b"this is not a real jpeg file at all")

        scan = scan_folder(self.source_dir, self.store)
        self.assertEqual(len(scan["new_files"]), 2)  # hash 不驗證有效性
        result = commit_import(
            scan["new_files"], "internal", self.dest_dir, self.thumb_dir,
            self.store)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["filename"], "bad.jpg")

    def test_file_hash_frozen_even_after_real_metadata_write_changes_bytes(self):
        """`research.md` §4 的完整端到端驗證（跨 photo_importer +
        photo_metadata_sync）：對已匯入照片的**複製檔案**真的呼叫
        `write_metadata()`（會真的改變該檔案的位元組——exiftool 不是
        no-op），之後重新掃描**原始來源資料夾**（完全沒被 STND 動過的
        那份），仍然必須被正確判定為重複，證明 hash 凍結機制在「檔案
        位元組真的被中繼資料寫回動過」這個最貼近實際使用的情境下依然
        成立，不只是理論上的資料庫欄位不變。"""
        _write_tiny_jpeg(os.path.join(self.source_dir, "a.jpg"))
        first_scan = scan_folder(self.source_dir, self.store)
        commit_import(
            first_scan["new_files"], "internal", self.dest_dir,
            self.thumb_dir, self.store)

        imported = self.store.find_by_hash(first_scan["new_files"][0]["file_hash"])
        before_bytes = open(imported["storage_path"], "rb").read()

        write_metadata(imported["storage_path"], ["夕陽", "京都"], 4)

        after_bytes = open(imported["storage_path"], "rb").read()
        self.assertNotEqual(
            before_bytes, after_bytes,
            "測試前提不成立：exiftool 寫入後檔案位元組應該要真的改變")

        second_scan = scan_folder(self.source_dir, self.store)
        self.assertEqual(second_scan["duplicate_count"], 1)
        self.assertEqual(second_scan["new_files"], [])
        reloaded = self.store.find_by_hash(first_scan["new_files"][0]["file_hash"])
        self.assertEqual(reloaded["file_hash"], imported["file_hash"])

    def test_storage_path_named_by_hash_not_original_filename(self):
        _write_tiny_jpeg(os.path.join(self.source_dir, "原始檔名.jpg"))
        scan = scan_folder(self.source_dir, self.store)
        commit_import(
            scan["new_files"], "internal", self.dest_dir, self.thumb_dir,
            self.store)
        row = self.store.find_by_hash(scan["new_files"][0]["file_hash"])
        self.assertIn(scan["new_files"][0]["file_hash"], row["storage_path"])


if __name__ == "__main__":
    unittest.main()
