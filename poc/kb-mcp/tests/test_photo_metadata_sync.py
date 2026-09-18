"""`photo_metadata_sync.py` 測試：exiftool 讀寫 XMP/IPTC 中繼資料。

需要真正的 `exiftool` 命令列工具（`brew install exiftool`）——大部分
測試對著真實檔案跑，不 mock，比照 `test_photo_importer.py` 對 `sips`
的既有做法；只有「exiftool 執行失敗」這種難以真實重現的情境才用
`unittest.mock` 模擬（T034 要求）。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_metadata_sync*"
"""
import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from photo_metadata_sync import (  # noqa: E402
    MetadataSyncUnavailable, write_metadata)

# 同一份 8x8 純色 JPEG fixture，跟 test_photo_importer.py 用的是同一張
# （無 EXIF，不影響中繼資料寫入測試——這裡測的是 XMP/IPTC 標籤/評分
# 欄位，跟既有 EXIF 相機資訊欄位是不同的中繼資料區塊）。
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYW"
    "GDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/"
    "2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QA"
    "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
    "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
    "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
    "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
    "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
    "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU"
    "1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDEooorjO8/"
    "/9k="
)


def _tiny_jpeg_path(dirpath, name="a.jpg"):
    path = os.path.join(dirpath, name)
    with open(path, "wb") as f:
        f.write(base64.b64decode(_TINY_JPEG_B64))
    return path


def _read_back(path):
    proc = subprocess.run(
        ["exiftool", "-j", "-Rating", "-Keywords", "-Subject", path],
        capture_output=True, timeout=15)
    import json
    return json.loads(proc.stdout.decode("utf-8"))[0]


class WriteMetadataRealFileTest(unittest.TestCase):
    """對著真實檔案跑，驗證實際寫入的中繼資料內容——不是只驗證
    exiftool 的 returncode。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-metadata-sync-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_writes_rating_and_chinese_tags_correctly(self):
        path = _tiny_jpeg_path(self.tmp)
        write_metadata(path, ["夕陽", "京都"], 4)
        result = _read_back(path)
        self.assertEqual(result["Rating"], 4)
        # exiftool -j 對多值欄位回傳 list；中文字元必須正確解碼（不是
        # 之前實測發現的「??」亂碼），這條斷言直接對應
        # photo_metadata_sync.py docstring 記錄的 IPTC charset 實測發現。
        self.assertEqual(set(result["Keywords"]), {"夕陽", "京都"})
        self.assertEqual(set(result["Subject"]), {"夕陽", "京都"})

    def test_rewrite_replaces_not_merges_tags(self):
        path = _tiny_jpeg_path(self.tmp)
        write_metadata(path, ["夕陽", "京都"], 4)
        write_metadata(path, ["夜景"], 5)
        result = _read_back(path)
        self.assertEqual(result["Keywords"], "夜景")
        self.assertEqual(result["Subject"], "夜景")
        self.assertEqual(result["Rating"], 5)

    def test_empty_tags_clears_existing_keywords(self):
        path = _tiny_jpeg_path(self.tmp)
        write_metadata(path, ["夕陽"], 3)
        write_metadata(path, [], 0)
        result = _read_back(path)
        self.assertNotIn("Keywords", result)
        self.assertNotIn("Subject", result)
        self.assertEqual(result["Rating"], 0)

    def test_no_overwrite_original_backup_file_left_behind(self):
        path = _tiny_jpeg_path(self.tmp)
        write_metadata(path, ["夕陽"], 4)
        leftovers = os.listdir(self.tmp)
        self.assertEqual(leftovers, ["a.jpg"])

    def test_unavailable_when_file_does_not_exist(self):
        with self.assertRaises(MetadataSyncUnavailable):
            write_metadata(
                os.path.join(self.tmp, "does-not-exist.jpg"), ["夕陽"], 4)


class WriteMetadataFailureMockedTest(unittest.TestCase):
    """exiftool 真的執行失敗的情境不容易在測試環境穩定重現（實測發現
    唯讀權限檔案在本機 macOS 上仍可被 `-overwrite_original` 寫入，見
    research.md 實作紀錄），改用 mock 模擬（T034 要求）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-metadata-sync-test-")
        self.path = _tiny_jpeg_path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_nonzero_returncode_raises_runtime_error_with_stderr(self):
        fake_result = mock.Mock(
            returncode=1, stderr=b"Error: format not supported")
        with mock.patch("subprocess.run", return_value=fake_result):
            with self.assertRaises(RuntimeError) as ctx:
                write_metadata(self.path, ["tag"], 3)
        self.assertIn("format not supported", str(ctx.exception))

    def test_subprocess_error_raises_runtime_error(self):
        with mock.patch("subprocess.run",
                         side_effect=FileNotFoundError("exiftool not found")):
            with self.assertRaises(RuntimeError):
                write_metadata(self.path, ["tag"], 3)

    def test_timeout_raises_runtime_error(self):
        with mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="exiftool", timeout=30)):
            with self.assertRaises(RuntimeError):
                write_metadata(self.path, ["tag"], 3)


if __name__ == "__main__":
    unittest.main()
