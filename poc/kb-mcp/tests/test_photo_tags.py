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
        self.assertEqual(pt.tag_for_key("2"), "光影")
        for bad in ("", "a,b", "a/b", "a:b", '含"引號', "★3", "x" * 41):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pt.validate_name(bad)
        for key in ("q", "f", "d", "t", "10", "!", ""):
            with self.assertRaises(ValueError, msg=repr(key)):
                pt.validate_key(key)
        self.assertEqual(pt.validate_key("S"), "s")

    def test_add_remove_key_conflicts(self):
        pt.add_tag("人像", key="s", group="題材")
        with self.assertRaises(ValueError):
            pt.add_tag("人像")                       # 重複
        with self.assertRaises(ValueError):
            pt.add_tag("風景", key="s")              # 快速鍵被佔用
        pt.set_key("人像", None)
        pt.add_tag("風景", key="s")
        self.assertEqual(pt.tag_for_key("s"), "風景")
        pt.remove_tag("風景")
        self.assertIsNone(pt.tag_for_key("s"))
        with self.assertRaises(ValueError):
            pt.remove_tag("不存在")


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
    def test_slot_toggle_notifies(self):
        p = self.jpg()
        pt.slot_toggle("1", [p], notify_fn=self.notes.append)
        pt.slot_toggle("1", [p], notify_fn=self.notes.append)
        pt.slot_toggle("9", [p], notify_fn=self.notes.append)
        self.assertIn("已貼上「街拍」到 1 張", self.notes[0])
        self.assertIn("已移除「街拍」", self.notes[1])
        self.assertIn("還沒有對應", self.notes[2])

    def test_picker_prechecks_common_and_applies_delta(self):
        a, b = self.jpg("a.jpg"), self.jpg("b.jpg")
        pt.apply_to_selection([a, b], add=("街拍",))
        pt.apply_to_selection([a], add=("孤兒",))    # 不在清單、且只有 a 有
        seen = {}

        def choose(items, pre, prompt):
            seen["items"], seen["pre"] = items, pre
            return ["光影", "＋ 新增標籤…"]           # 取消街拍、勾光影、新增一個

        pt.picker([a, b], choose=choose, ask=lambda p: "夜景",
                  notify_fn=self.notes.append)
        self.assertEqual(seen["pre"], ["街拍"])      # 兩張都有的才預先勾選
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
        self.assertEqual(seen["i"][0], "家人")

    def test_cheatsheet_lists_keys_and_selection(self):
        p = self.jpg()
        pt.add_tag("人像", key="s", group="題材")
        pt.add_tag("備忘")                            # 沒有快速鍵
        pt.toggle([p], "光影")
        text = pt.cheatsheet_text([p])
        for expect in ("⌃⌘1　街拍", "⌃⌘S　題材 ▸ 人像", "⌃⌘T", "只能從視窗貼的標籤：備忘",
                       "全部都有：光影"):
            self.assertIn(expect, text)


class ServicesTest(TagTestBase):
    def test_install_generates_workflows_and_reinstall_cleans_stale(self):
        svc = os.path.join(self.tmp, "Services")
        os.makedirs(svc)
        keep = os.path.join(svc, "相片評分 3 星.workflow")      # 別人的，不能被清掉
        os.makedirs(keep)
        names = photo_services.install(pt.load_vocab(), services_dir=svc, bind=False)
        self.assertEqual(names[:3], ["相片標籤 1 街拍", "相片標籤 2 光影", "相片標籤 3 家人"])
        self.assertIn("相片貼標籤…", names)
        wf = os.path.join(svc, "相片標籤 1 街拍.workflow", "Contents")
        info = plistlib.load(open(os.path.join(wf, "Info.plist"), "rb"))
        self.assertEqual(info["NSServices"][0]["NSMenuItem"]["default"], "相片標籤 1 街拍")
        doc = plistlib.load(open(os.path.join(wf, "document.wflow"), "rb"))
        cmd = doc["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
        self.assertTrue(cmd.endswith('tag-slot 1 "$@"'))
        # 改名＋換鍵後重新安裝：舊的消失
        pt.remove_tag("街拍")
        pt.add_tag("街頭", key="s")
        photo_services.install(pt.load_vocab(), services_dir=svc, bind=False)
        left = sorted(os.listdir(svc))
        self.assertNotIn("相片標籤 1 街拍.workflow", left)
        self.assertIn("相片標籤 S 街頭.workflow", left)
        self.assertTrue(os.path.exists(keep))


if __name__ == "__main__":
    unittest.main()
