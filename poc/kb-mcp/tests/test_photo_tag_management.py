"""PhotoStore 標籤管理（改名／合併／刪除／計數）與對應 API：資料庫改完後，
受影響照片的檔案中繼資料要被背景任務重新寫回。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_tag_management*"
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for _p in (ROOT, os.path.dirname(HERE), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import BackgroundTasks, HTTPException  # noqa: E402

from app.routers import photos as api  # noqa: E402
from photo_formats import find_exiftool  # noqa: E402
from photo_store import PhotoStore  # noqa: E402
from photo_tags import read_file_tags  # noqa: E402
from test_photo_tool import _write_jpeg  # noqa: E402


class StoreTagManagementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-tagmgmt-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = PhotoStore(os.path.join(self.tmp, "data"))
        self.addCleanup(self.store.close)
        self.ids = []
        for i in range(3):
            path = os.path.join(self.tmp, "p%d.jpg" % i)
            if find_exiftool():
                _write_jpeg(path)
            photo = self.store.add_photo(
                file_hash="h%d" % i, storage_path=path, storage_location="reference",
                thumbnail_path=path, file_size=1)
            self.ids.append(photo["id"])
        self.store.set_photo_tags(self.ids[0], ["街拍", "家人"])
        self.store.set_photo_tags(self.ids[1], ["街拍"])
        self.store.set_photo_tags(self.ids[2], ["家人"])
        self.store.get_or_create_tag("空標籤")

    def names(self, photo_id):
        return sorted(t["name"] for t in self.store.get_photo_tags(photo_id))

    def test_counts_include_unused(self):
        counts = {t["name"]: t["count"] for t in self.store.list_tags_with_counts()}
        self.assertEqual(counts, {"街拍": 2, "家人": 2, "空標籤": 0})

    def test_rename_plain_and_case_only_and_missing(self):
        r = self.store.rename_tag("街拍", "街頭")
        self.assertEqual((sorted(r["photo_ids"]), r["merged"]),
                         (sorted([self.ids[0], self.ids[1]]), False))
        self.assertEqual(self.names(self.ids[1]), ["街頭"])
        self.assertEqual(self.store.rename_tag("街頭", "街頭")["merged"], False)
        self.assertIsNone(self.store.rename_tag("不存在", "x"))
        with self.assertRaises(ValueError):
            self.store.rename_tag("街頭", "  ")

    def test_rename_into_existing_merges_without_duplicates(self):
        r = self.store.rename_tag("街拍", "家人")
        self.assertTrue(r["merged"])
        self.assertEqual(self.names(self.ids[0]), ["家人"])     # 原本兩個都有 → 不重複
        self.assertEqual(self.names(self.ids[1]), ["家人"])
        counts = {t["name"]: t["count"] for t in self.store.list_tags_with_counts()}
        self.assertEqual(counts["家人"], 3)
        self.assertNotIn("街拍", counts)

    def test_merge_many_and_delete(self):
        ids = self.store.merge_tags(["街拍", "家人"], "生活")
        self.assertEqual(sorted(ids), sorted(self.ids))
        for pid in self.ids:
            self.assertEqual(self.names(pid), ["生活"])
        self.assertEqual(sorted(self.store.delete_tag("生活")), sorted(self.ids))
        self.assertEqual(self.names(self.ids[0]), [])
        self.assertIsNone(self.store.delete_tag("生活"))


@unittest.skipUnless(find_exiftool(), "需要 exiftool")
class TagApiTest(StoreTagManagementTest):
    def run_tasks(self, bt):
        for task in bt.tasks:
            task.func(*task.args, **task.kwargs)

    def test_rename_rewrites_file_metadata_in_background(self):
        # 先把資料庫標籤寫回檔案（模擬正常使用後的狀態）
        for pid in self.ids:
            api._run_metadata_sync(pid, self.store.data_dir)
        self.assertEqual(sorted(read_file_tags(os.path.join(self.tmp, "p0.jpg"))),
                         sorted(["街拍", "家人"]))
        bt = BackgroundTasks()
        r = api.rename_tag(api.TagRename(old="街拍", new="街頭"), bt, self.store)
        self.assertEqual((r["affected"], r["merged"]), (2, False))
        self.run_tasks(bt)
        self.assertEqual(sorted(read_file_tags(os.path.join(self.tmp, "p0.jpg"))),
                         sorted(["街頭", "家人"]))
        self.assertEqual(self.store.get_photo(self.ids[1])["metadata_sync_status"], "synced")

    def test_delete_merge_create_and_validation(self):
        bt = BackgroundTasks()
        self.assertEqual(api.delete_tag(bt, "家人", self.store)["affected"], 2)
        self.run_tasks(bt)
        self.assertEqual(read_file_tags(os.path.join(self.tmp, "p2.jpg")), [])
        bt = BackgroundTasks()
        self.assertEqual(api.merge_tags(
            api.TagMerge(sources=["街拍", "空標籤"], into="日常"), bt, self.store)["affected"], 2)
        self.assertEqual(api.create_tag(api.TagCreate(name="夜景"), self.store)["tag"], "夜景")
        stats = {t["name"]: t["count"] for t in api.tag_stats(self.store)["tags"]}
        self.assertEqual(stats["日常"], 2)
        for bad in ("a,b", "★3", ""):
            with self.assertRaises(HTTPException) as ctx:
                api.create_tag(api.TagCreate(name=bad), self.store)
            self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            api.delete_tag(BackgroundTasks(), "不存在", self.store)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
