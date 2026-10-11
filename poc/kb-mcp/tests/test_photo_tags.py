"""`photo_tags.py`／`photo_services.py` 測試：標籤清單、批次貼/移除/切換、
與評分及其他 Finder 標籤共存、RAW sidecar、勾選視窗邏輯、右鍵動作產生。

執行：python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo_tags*"
"""
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

import photo_services  # noqa: E402
import photo_tags as pt  # noqa: E402
import photo_tool  # noqa: E402
from photo_formats import find_exiftool, read_finder_tags, sidecar_path  # noqa: E402
from photo_metadata_sync import read_existing_tags  # noqa: E402
from test_photo_tool import _write_jpeg  # noqa: E402

EXIFTOOL = find_exiftool()


def _finder_names(path):
    return [e.split("\n")[0] for e in read_finder_tags(path)]


@unittest.skipUnless(EXIFTOOL, "需要 exiftool")
class TagTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="photo-tags-")
        self.cfg = tempfile.mkdtemp(prefix="photo-cfg-")
        self._old = pt.CONFIG_DIR
        pt.CONFIG_DIR = self.cfg
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(shutil.rmtree, self.cfg, True)
        self.addCleanup(setattr, pt, "CONFIG_DIR", self._old)
        self.notes = []

    def jpg(self, name="a.jpg"):
        p = os.path.join(self.tmp, name)
        _write_jpeg(p)
        return p

    def raw(self, name="SDIM0071.X3F"):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(b"FOVb" + b"\x00" * 64)
        return p


class VocabTest(TagTestBase):
    def test_starter_vocab_and_validation(self):
        data = pt.load_vocab()
        self.assertEqual([t["name"] for t in data["tags"]], ["街拍", "光影", "家人"])
        for bad in ("", "a,b", "a/b", "a:b", '含"引號', "★3", "x" * 41):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pt.validate_name(bad)

    def test_add_remove_and_old_vocab_with_keys_still_loads(self):
        pt.add_tag("人像", group="題材")
        with self.assertRaises(ValueError):
            pt.add_tag("人像")                       # 重複
        pt.remove_tag("人像")
        with self.assertRaises(ValueError):
            pt.remove_tag("不存在")
        # 舊版 tags.json（有 key 欄位、沒有 uses/last）仍可讀
        pt.save_vocab({"tags": [{"name": "舊", "key": "1", "group": ""}], "recent": []})
        data = pt.load_vocab()
        self.assertEqual(pt.ordered_names(data), ["舊"])
        self.assertEqual(data["last"], [])

    def test_ordering_recent_then_uses_then_vocab_order(self):
        for n in ("A", "B", "C"):
            pt.add_tag(n)
        pt.touch_recent(["C"])
        pt.touch_recent(["B"])
        pt.touch_recent(["B"])          # B 用兩次、最近；C 一次
        data = pt.load_vocab()
        self.assertEqual(pt.ordered_names(data)[:3], ["B", "C", "街拍"])
        self.assertEqual(find_uses(data, "B"), 2)


def find_uses(data, name):
    return pt.find_tag(data, name).get("uses", 0)


class ApplyTagsTest(TagTestBase):
    def test_toggle_multiple_tags_rating_and_other_finder_tags_survive(self):
        p = self.jpg()
        photo_tool.rate_files([p], 4)
        photo_tool.write_finder_tags(p, photo_tool.read_finder_tags(p) + ["旅行\n0"])
        r = pt.toggle([p], "街拍")
        self.assertEqual((r["action"], r["groups"]), ("add", 1))
        pt.toggle([p], "光影")                       # 一張可以有多個標籤
        self.assertEqual(sorted(pt.read_file_tags(p)), ["光影", "街拍"])
        self.assertEqual(sorted(_finder_names(p)), sorted(["光影", "旅行", "★4", "街拍"]))
        tags, rating = read_existing_tags(p)         # AlphaVibe 匯入時讀的就是這個
        self.assertEqual((sorted(tags), rating), (["光影", "街拍"], 4))
        r = pt.toggle([p], "街拍")                   # 再按一次 = 移除
        self.assertEqual(r["action"], "remove")
        self.assertEqual(pt.read_file_tags(p), ["光影"])
        self.assertEqual(sorted(_finder_names(p)), sorted(["光影", "旅行", "★4"]))

    def test_toggle_adds_to_all_when_only_some_have_it(self):
        a, b = self.jpg("a.jpg"), self.jpg("b.jpg")
        pt.toggle([a], "家人")
        r = pt.toggle([a, b], "家人")                # 只有 a 有 → 全部貼上
        self.assertEqual(r["action"], "add")
        self.assertEqual(pt.read_file_tags(b), ["家人"])
        r = pt.toggle([a, b], "家人")                # 都有了 → 移除
        self.assertEqual(r["action"], "remove")
        self.assertEqual(pt.read_file_tags(a) + pt.read_file_tags(b), [])

    def test_existing_iptc_keywords_are_kept(self):
        p = self.jpg()
        subprocess.run([EXIFTOOL, "-overwrite_original", "-charset", "iptc=UTF8",
                        "-IPTC:Keywords=舊關鍵字", p], check=True, capture_output=True)
        pt.toggle([p], "街拍")
        self.assertEqual(sorted(pt.read_file_tags(p)), sorted(["街拍", "舊關鍵字"]))

    def test_raw_uses_sidecar_and_pair_is_one_group(self):
        raw, jpg = self.raw(), os.path.join(self.tmp, "SDIM0071.jpg")
        _write_jpeg(jpg)
        before = open(raw, "rb").read()
        r = pt.toggle([jpg], "光影")                 # 只選 JPG，RAW 也跟著貼
        self.assertEqual(r["groups"], 1)
        self.assertEqual(open(raw, "rb").read(), before)       # RAW 本體不動
        self.assertEqual(pt.read_file_tags(raw), ["光影"])      # 來自 sidecar
        self.assertEqual(pt.read_file_tags(jpg), ["光影"])
        self.assertTrue(os.path.exists(sidecar_path(raw)))
        self.assertEqual(_finder_names(raw), ["光影"])

    def test_clear_all_keeps_stars(self):
        p = self.jpg()
        photo_tool.rate_files([p], 3)
        pt.apply_to_selection([p], add=("街拍", "家人"))
        groups, failed = pt.clear_all([p])
        self.assertEqual((groups, failed), (1, []))
        self.assertEqual(pt.read_file_tags(p), [])
        self.assertEqual(_finder_names(p), ["★3"])
        self.assertEqual(read_existing_tags(p)[1], 3)

    def test_non_photo_selection_is_ignored(self):
        txt = os.path.join(self.tmp, "n.txt")
        open(txt, "w").close()
        self.assertEqual(pt.toggle([txt], "街拍")["action"], "none")


class GuiFlowTest(TagTestBase):
    def test_repeat_last_applies_last_picked_tags(self):
        a, b = self.jpg("a.jpg"), self.jpg("b.jpg")
        self.assertIsNone(pt.repeat_last([a], notify_fn=self.notes.append))   # 還沒貼過
        self.assertIn("還沒有", self.notes[-1])
        pt.picker([a], choose=lambda items, pre, prompt: [i for i in items if "街拍" in i or "光影" in i],
                  notify_fn=self.notes.append)
        r = pt.repeat_last([b], notify_fn=self.notes.append)
        self.assertEqual(sorted(r["added"]), sorted(["街拍", "光影"]))
        self.assertEqual(sorted(pt.read_file_tags(b)), sorted(["街拍", "光影"]))
        pt.repeat_last([b], notify_fn=self.notes.append)       # 再按一次：只新增，不會移除
        self.assertEqual(sorted(pt.read_file_tags(b)), sorted(["街拍", "光影"]))

    def test_picker_numbers_labels(self):
        p = self.jpg()
        seen = {}
        pt.picker([p], choose=lambda items, pre, prompt: seen.setdefault("i", items) and None,
                  notify_fn=self.notes.append)
        self.assertEqual(seen["i"][:3], ["1　街拍", "2　光影", "3　家人"])
        self.assertEqual(seen["i"][-1], "＋ 新增標籤…")

    def test_picker_prechecks_common_and_applies_delta(self):
        a, b = self.jpg("a.jpg"), self.jpg("b.jpg")
        pt.apply_to_selection([a, b], add=("街拍",))
        pt.apply_to_selection([a], add=("孤兒",))    # 不在清單、且只有 a 有
        seen = {}

        def choose(items, pre, prompt):
            seen["items"], seen["pre"] = items, pre
            return [i for i in items if i.endswith("光影")] + ["＋ 新增標籤…"]  # 取消街拍、勾光影、新增一個

        pt.picker([a, b], choose=choose, ask=lambda p: "夜景",
                  notify_fn=self.notes.append)
        self.assertEqual(seen["pre"], ["1　街拍"])    # 兩張都有的才預先勾選（標籤前有編號）
        self.assertIn("孤兒（不在清單）", seen["items"])
        for f in (a, b):
            self.assertEqual(sorted(t for t in pt.read_file_tags(f) if t != "孤兒"),
                             ["光影", "夜景"])
        self.assertIsNotNone(pt.find_tag(pt.load_vocab(), "夜景"))   # 新標籤進清單
        self.assertEqual(pt.load_vocab()["recent"][:2].count("光影"), 1)

    def test_picker_cancel_and_no_change(self):
        p = self.jpg()
        self.assertIsNone(pt.picker([p], choose=lambda *a: None,
                                    notify_fn=self.notes.append))
        pt.picker([p], choose=lambda items, pre, prompt: [], notify_fn=self.notes.append)
        self.assertEqual(self.notes[-1], "沒有變更")
        self.assertEqual(pt.read_file_tags(p), [])

    def test_picker_orders_recent_first(self):
        p = self.jpg()
        pt.toggle([p], "家人")                       # 家人變成最近使用
        pt.toggle([p], "家人")
        seen = {}
        pt.picker([p], choose=lambda items, pre, prompt: seen.setdefault("i", items) and None,
                  notify_fn=self.notes.append)
        self.assertEqual(seen["i"][0], "1　家人")



class BulkChangeTest(TagTestBase):
    def _library(self):
        """3 組照片：a.jpg(街拍)、b.jpg(街拍+家人)、RAW+sidecar(街拍)、c.jpg(家人)"""
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        a = self.jpg("a.jpg")
        b = os.path.join(sub, "b.jpg")
        _write_jpeg(b)
        c = self.jpg("c.jpg")
        raw = self.raw()
        pt.apply_to_selection([a, b, raw], add=("街拍",))
        pt.apply_to_selection([b, c], add=("家人",))
        return a, b, c, raw

    def test_rename_rewrites_files_sidecar_keeps_key_and_other_tags_then_undo(self):
        a, b, c, raw = self._library()
        plan = pt.plan_change(["街拍"], "街頭", folder=self.tmp)
        self.assertEqual((plan["groups"], len(plan["files"])), (3, 3))
        self.assertEqual(pt.read_file_tags(a), ["街拍"])      # 預覽不動檔案
        result = pt.apply_change(plan)
        self.assertEqual((result["changed_files"], result["failed"]), (3, []))
        self.assertEqual(pt.read_file_tags(a), ["街頭"])
        self.assertEqual(sorted(pt.read_file_tags(b)), sorted(["街頭", "家人"]))
        self.assertEqual(pt.read_file_tags(raw), ["街頭"])     # sidecar 也改了
        self.assertIn("街頭", _finder_names(a))
        self.assertNotIn("街拍", _finder_names(a))
        data = pt.load_vocab()
        self.assertIsNone(pt.find_tag(data, "街拍"))
        restored, skipped = pt.undo_last_change()
        self.assertEqual((restored, skipped), (3, []))
        self.assertEqual(pt.read_file_tags(a), ["街拍"])
        self.assertIsNotNone(pt.find_tag(pt.load_vocab(), "街拍"))   # 標籤清單也復原
        with self.assertRaises(ValueError):                    # 已復原，沒有更多紀錄
            pt.undo_last_change()

    def test_merge_and_delete(self):
        a, b, c, raw = self._library()
        pt.apply_change(pt.plan_change(["街拍", "家人"], "生活", folder=self.tmp))
        self.assertEqual(pt.read_file_tags(b), ["生活"])       # 兩個標籤併成一個
        self.assertEqual(sorted(pt.read_file_tags(c)), ["生活"])
        names = [t["name"] for t in pt.load_vocab()["tags"]]
        self.assertIn("生活", names)
        self.assertNotIn("街拍", names)
        self.assertEqual(find_uses(pt.load_vocab(), "生活"), 0)
        pt.apply_change(pt.plan_change(["生活"], None, folder=self.tmp))
        for f in (a, b, c, raw):
            self.assertEqual(pt.read_file_tags(f), [])
        self.assertIsNone(pt.find_tag(pt.load_vocab(), "生活"))

    def test_rating_and_star_tag_untouched_by_bulk_change(self):
        a, b, c, raw = self._library()
        photo_tool.rate_files([a], 5)
        pt.apply_change(pt.plan_change(["街拍"], "街頭", folder=self.tmp))
        self.assertEqual(read_existing_tags(a)[1], 5)
        self.assertIn("★5", _finder_names(a))

    def test_manager_rename_flow_and_cancel(self):
        a, b, c, raw = self._library()
        script = iter([["改名"], ["街拍"], ["選擇資料夾…（掃描檔案內的標籤，最準確）"]])
        seen = {}

        def confirm_fn(msg, ok):
            seen["msg"] = msg
            return True

        reinstalled = []
        result = pt.manager(
            choose=lambda items, pre, prompt, multiple=True: next(script),
            ask=lambda prompt: "街頭", confirm_fn=confirm_fn,
            pick_folder=lambda: self.tmp, notify_fn=self.notes.append,
            reinstall=lambda: reinstalled.append(1))
        self.assertEqual(result, "改名")
        self.assertIn("3 張照片", seen["msg"])
        self.assertEqual(pt.read_file_tags(a), ["街頭"])
        self.assertEqual(reinstalled, [1])
        # 取消確認 → 不動
        script2 = iter([["刪除標籤"], ["家人"], ["選擇資料夾…（掃描檔案內的標籤，最準確）"]])
        self.assertIsNone(pt.manager(
            choose=lambda items, pre, prompt, multiple=True: next(script2),
            ask=lambda p: None, confirm_fn=lambda m, o: False,
            pick_folder=lambda: self.tmp, notify_fn=self.notes.append,
            reinstall=lambda: None))
        self.assertEqual(sorted(pt.read_file_tags(b)), sorted(["街頭", "家人"]))

    def test_manager_add(self):
        pt.manager(choose=lambda i, p, pr, multiple=True: ["新增標籤"],
                   ask=lambda prompt: "人像", notify_fn=self.notes.append,
                   reinstall=lambda: None)
        self.assertIsNotNone(pt.find_tag(pt.load_vocab(), "人像"))
        self.assertNotIn("指派/更換快速鍵", pt._ACTIONS)

    def test_rename_carries_uses_over(self):
        a, b, c, raw = self._library()
        pt.touch_recent(["街拍"])
        pt.touch_recent(["街拍"])
        pt.apply_change(pt.plan_change(["街拍"], "街頭", folder=self.tmp))
        self.assertEqual(find_uses(pt.load_vocab(), "街頭"), 2)
        self.assertEqual(pt.load_vocab()["recent"][0], "街頭")

    def test_invalid_names_rejected_in_plan(self):
        with self.assertRaises(ValueError):
            pt.plan_change(["街拍"], "a,b", folder=self.tmp)


class ServicesTest(TagTestBase):
    def test_install_generates_workflows_and_reinstall_cleans_stale(self):
        svc = os.path.join(self.tmp, "Services")
        os.makedirs(svc)
        keep = os.path.join(svc, "別人的動作.workflow")           # 不是我們的，不能被清掉
        os.makedirs(keep)
        # 舊版殘留（每個標籤一個動作、速查表）重新安裝時要被清掉
        for legacy in ("相片標籤 1 街拍", "相片標籤速查表"):
            os.makedirs(os.path.join(svc, legacy + ".workflow"))
        names = photo_services.install(pt.load_vocab(), services_dir=svc, bind=False)
        self.assertEqual(len(names), 12)                       # 固定 12 個，不隨標籤數增加
        pt.add_tag("人像")
        pt.add_tag("風景")
        self.assertEqual(len(photo_services.install(
            pt.load_vocab(), services_dir=svc, bind=False)), 12)
        for expect in ("相片貼標籤…", "相片重複上次標籤", "相片管理標籤…",
                       "相片評分 0 星", "相片評分 5 星", "相片依日期整理",
                       "相片整理選取的檔案", "相片復原上次整理"):
            self.assertIn(expect, names)
        left = sorted(os.listdir(svc))
        self.assertNotIn("相片標籤 1 街拍.workflow", left)
        self.assertNotIn("相片標籤速查表.workflow", left)
        rate = plistlib.load(open(os.path.join(
            svc, "相片評分 4 星.workflow", "Contents", "document.wflow"), "rb"))
        self.assertTrue(rate["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
                        .endswith('rate 4 "$@"'))
        rep = plistlib.load(open(os.path.join(
            svc, "相片重複上次標籤.workflow", "Contents", "document.wflow"), "rb"))
        self.assertTrue(rep["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
                        .endswith('tag-repeat "$@"'))
        folder = plistlib.load(open(os.path.join(
            svc, "相片依日期整理.workflow", "Contents", "document.wflow"), "rb"))
        self.assertEqual(folder["workflowMetaData"]["serviceInputTypeIdentifier"],
                         photo_services.FOLDER_INPUT)
        info = plistlib.load(open(os.path.join(
            svc, "相片依日期整理.workflow", "Contents", "Info.plist"), "rb"))
        self.assertEqual(info["NSServices"][0]["NSSendFileTypes"], ["public.folder"])
        self.assertTrue(os.path.exists(keep))


if __name__ == "__main__":
    unittest.main()
