"""`photo_store.py` 測試：schema 建立、CRUD、獨立 db 檔案隔離。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_store*"
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from photo_store import PhotoStore  # noqa: E402


class SchemaTest(unittest.TestCase):
    """schema 建立：5 張表都存在，且沒有任何隱式種子資料寫入
    （2026-08-22 資產表事故教訓——__init__ 不得有寫入副作用）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-store-test-")
        self.store = PhotoStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_five_tables_created(self):
        rows = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r["name"] for r in rows}
        for expected in ("albums", "photos", "photo_albums", "tags",
                          "photo_tags"):
            self.assertIn(expected, table_names)

    def test_db_file_is_photos_db_not_alphavibe_db(self):
        self.assertEqual(os.path.basename(self.store.db_path), "photos.db")
        self.assertTrue(os.path.exists(self.store.db_path))

    def test_no_seed_data_on_fresh_store(self):
        """__init__ 不得掛任何有副作用的種子寫入邏輯——全新資料庫上所有
        表都應該是空的。"""
        self.assertEqual(self.store.list_albums(), [])
        self.assertEqual(self.store.list_tags(), [])


class AlbumCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-store-test-")
        self.store = PhotoStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_create_and_get_album(self):
        album = self.store.create_album("測試相簿", "描述文字")
        self.assertIsNotNone(album["id"])
        self.assertEqual(album["title"], "測試相簿")
        self.assertEqual(self.store.get_album(album["id"])["title"], "測試相簿")

    def test_create_album_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            self.store.create_album("   ")

    def test_list_albums_includes_photo_count(self):
        album = self.store.create_album("相簿A")
        photo = self.store.add_photo(
            file_hash="abc123", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/a-thumb.jpg")
        self.store.add_photo_to_album(photo["id"], album["id"])
        albums = self.store.list_albums()
        self.assertEqual(albums[0]["photo_count"], 1)

    def test_update_album(self):
        album = self.store.create_album("舊標題")
        updated = self.store.update_album(album["id"], title="新標題")
        self.assertEqual(updated["title"], "新標題")
        self.assertEqual(updated["description"], album["description"])

    def test_update_missing_album_returns_none(self):
        self.assertIsNone(self.store.update_album(999999, title="x"))

    def test_delete_album_does_not_touch_photo_record(self):
        album = self.store.create_album("相簿A")
        photo = self.store.add_photo(
            file_hash="abc123", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/a-thumb.jpg")
        self.store.add_photo_to_album(photo["id"], album["id"])
        self.store.delete_album(album["id"])
        self.assertIsNone(self.store.get_album(album["id"]))
        self.assertIsNotNone(self.store.get_photo(photo["id"]))


class PhotoCrudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-store-test-")
        self.store = PhotoStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_add_and_find_by_hash(self):
        photo = self.store.add_photo(
            file_hash="hash1", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/a-thumb.jpg",
            camera_model="Sigma fp L", lens="45mm F2.8", photo_date="2026-10-21")
        self.assertEqual(photo["rating"], 0)
        self.assertEqual(photo["metadata_sync_status"], "pending")
        found = self.store.find_by_hash("hash1")
        self.assertEqual(found["id"], photo["id"])
        self.assertIsNone(self.store.find_by_hash("does-not-exist"))

    def test_add_photo_duplicate_hash_rejected(self):
        self.store.add_photo(
            file_hash="dup", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/a-thumb.jpg")
        with self.assertRaises(Exception):
            self.store.add_photo(
                file_hash="dup", storage_path="/tmp/b.jpg",
                storage_location="internal", thumbnail_path="/tmp/b-thumb.jpg")

    def test_add_photo_invalid_storage_location_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_photo(
                file_hash="h", storage_path="/tmp/a.jpg",
                storage_location="cloud", thumbnail_path="/tmp/a-thumb.jpg")

    def test_delete_photo_removes_record_only(self):
        """spec.md FR-011：僅刪資料庫紀錄，這裡驗證的是 db 層行為——
        `delete_photo()` 完全不碰檔案系統，`storage_path` 是否真的存在
        於磁碟由呼叫端（router）的檔案系統負責，不是這個方法的責任。"""
        photo = self.store.add_photo(
            file_hash="h1", storage_path="/tmp/does-not-matter.jpg",
            storage_location="internal", thumbnail_path="/tmp/t.jpg")
        deleted = self.store.delete_photo(photo["id"])
        self.assertEqual(deleted["id"], photo["id"])
        self.assertIsNone(self.store.get_photo(photo["id"]))

    def test_delete_missing_photo_returns_none(self):
        self.assertIsNone(self.store.delete_photo(999999))

    def test_set_photo_rating_validates_range(self):
        photo = self.store.add_photo(
            file_hash="h2", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/t.jpg")
        updated = self.store.set_photo_rating(photo["id"], 4)
        self.assertEqual(updated["rating"], 4)
        with self.assertRaises(ValueError):
            self.store.set_photo_rating(photo["id"], 6)
        with self.assertRaises(ValueError):
            self.store.set_photo_rating(photo["id"], -1)

    def test_list_album_photos_filters_by_tag_and_sorts(self):
        album = self.store.create_album("相簿A")
        p1 = self.store.add_photo(
            file_hash="p1", storage_path="/tmp/1.jpg",
            storage_location="internal", thumbnail_path="/tmp/t1.jpg",
            photo_date="2026-01-01")
        p2 = self.store.add_photo(
            file_hash="p2", storage_path="/tmp/2.jpg",
            storage_location="internal", thumbnail_path="/tmp/t2.jpg",
            photo_date="2026-02-01")
        self.store.add_photo_to_album(p1["id"], album["id"])
        self.store.add_photo_to_album(p2["id"], album["id"])
        self.store.set_photo_tags(p1["id"], ["夕陽"])

        all_photos = self.store.list_album_photos(album["id"])
        self.assertEqual(len(all_photos), 2)
        self.assertEqual(all_photos[0]["id"], p2["id"])  # 依日期新到舊

        tagged_only = self.store.list_album_photos(album["id"], tag="夕陽")
        self.assertEqual([p["id"] for p in tagged_only], [p1["id"]])


class TagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-store-test-")
        self.store = PhotoStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_get_or_create_tag_normalizes_case_and_whitespace(self):
        t1 = self.store.get_or_create_tag("京都")
        t2 = self.store.get_or_create_tag("  京都  ")
        t3 = self.store.get_or_create_tag("Sunset")
        t4 = self.store.get_or_create_tag("sunset")
        self.assertEqual(t1["id"], t2["id"])
        self.assertEqual(t3["id"], t4["id"])
        self.assertEqual(len(self.store.list_tags()), 2)

    def test_set_photo_tags_replaces_not_appends(self):
        photo = self.store.add_photo(
            file_hash="h", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/t.jpg")
        self.store.set_photo_tags(photo["id"], ["夕陽", "京都"])
        self.store.set_photo_tags(photo["id"], ["夜景"])
        tags = {t["name"] for t in self.store.get_photo_tags(photo["id"])}
        self.assertEqual(tags, {"夜景"})

    def test_add_tags_to_photo_appends_not_replaces(self):
        photo = self.store.add_photo(
            file_hash="h", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/t.jpg")
        self.store.add_tags_to_photo(photo["id"], ["夕陽"])
        self.store.add_tags_to_photo(photo["id"], ["京都"])
        tags = {t["name"] for t in self.store.get_photo_tags(photo["id"])}
        self.assertEqual(tags, {"夕陽", "京都"})

    def test_suggest_tags_case_insensitive_substring(self):
        self.store.get_or_create_tag("夕陽")
        self.store.get_or_create_tag("夜景")
        results = [t["name"] for t in self.store.suggest_tags("夕")]
        self.assertEqual(results, ["夕陽"])


class MetadataSyncFreezeTest(unittest.TestCase):
    """`research.md` §4 核心保證的回歸測試：中繼資料相關操作（標籤/
    評分變更）不得改變已存在照片的 `file_hash`。這是 User Story 3 的
    完整寫回流程還沒實作前就能先驗證的部分——`file_hash` 本身在整個
    `PhotoStore` 生命週期內都應該是唯讀的，沒有任何方法會去 UPDATE 它。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-store-test-")
        self.store = PhotoStore(self.tmp)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp)

    def test_file_hash_unchanged_after_tag_and_rating_edits(self):
        photo = self.store.add_photo(
            file_hash="frozen-hash-123", storage_path="/tmp/a.jpg",
            storage_location="internal", thumbnail_path="/tmp/t.jpg")
        original_hash = photo["file_hash"]

        self.store.set_photo_tags(photo["id"], ["夕陽", "京都"])
        self.store.set_photo_rating(photo["id"], 5)
        self.store.add_tags_to_photo(photo["id"], ["街拍"])

        reloaded = self.store.get_photo(photo["id"])
        self.assertEqual(reloaded["file_hash"], original_hash)

    def test_no_method_contains_update_of_file_hash_column(self):
        """靜態防呆：掃過整份 `photo_store.py` 原始碼，確認沒有任何 SQL
        語句對 `file_hash` 欄位做 UPDATE——比對字串比實際跑一次更能
        防止「未來新增一個方法時不小心加了 UPDATE file_hash」。"""
        source_path = os.path.join(os.path.dirname(HERE), "photo_store.py")
        with open(source_path, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("UPDATE photos SET file_hash", source)


if __name__ == "__main__":
    unittest.main()
