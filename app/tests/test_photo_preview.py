"""`/api/photos/preview/{id}` 測試：單張檢視改用按需產生的高解析預覽圖，
不再用格狀縮圖（256 像素放大後太糊，使用者曾誤以為照片沒拍好）。

執行：.venv/bin/python3 -m unittest discover -s app/tests -p "test_photo_preview*"
"""
import base64
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "poc", "kb-mcp"),
           os.path.join(_ROOT, "poc", "kb-mcp", "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import HTTPException  # noqa: E402

from app.routers.photos import get_preview  # noqa: E402
from photo_store import PhotoStore  # noqa: E402
from test_photo_importer import _TINY_JPEG_B64  # noqa: E402


class PreviewEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-preview-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = PhotoStore(os.path.join(self.tmp, "data"))
        self.addCleanup(self.store.close)
        self.orig = os.path.join(self.tmp, "orig.jpg")
        self.thumb = os.path.join(self.tmp, "thumb.jpg")
        for path in (self.orig, self.thumb):
            with open(path, "wb") as f:
                f.write(base64.b64decode(_TINY_JPEG_B64))
        self.photo = self.store.add_photo(
            file_hash="h1", storage_path=self.orig, storage_location="reference",
            thumbnail_path=self.thumb, file_size=632)

    def test_large_is_generated_and_cached(self):
        resp = get_preview(self.photo["id"], "large", self.store)
        self.assertTrue(resp.path.endswith("h1_large.jpg"))
        self.assertTrue(os.path.exists(resp.path))
        self.assertNotEqual(resp.path, self.thumb)

    def test_full_returns_original_for_jpeg(self):
        resp = get_preview(self.photo["id"], "full", self.store)
        self.assertEqual(resp.path, self.orig)

    def test_offline_original_falls_back_to_thumbnail(self):
        os.remove(self.orig)
        resp = get_preview(self.photo["id"], "large", self.store)
        self.assertEqual(resp.path, self.thumb)

    def test_unreadable_original_falls_back_to_thumbnail(self):
        with open(self.orig, "wb") as f:
            f.write(b"not an image")
        resp = get_preview(self.photo["id"], "large", self.store)
        self.assertEqual(resp.path, self.thumb)

    def test_invalid_size_and_missing_photo(self):
        with self.assertRaises(HTTPException) as ctx:
            get_preview(self.photo["id"], "huge", self.store)
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            get_preview(9999, "large", self.store)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
