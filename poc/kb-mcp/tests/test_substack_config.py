"""T007：設定檔 `substack_config.json` 的載入、驗證與原子寫入（contracts/config-format.md）。

逐條覆蓋契約的驗證表；另驗 init／show／validate、備份保留 10 份、暫存檔＋os.replace 的原子性，
以及「資料目錄指向正式庫且沒有 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 就拒絕」的防呆。
"""
import copy
import glob
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import article_data_guard  # noqa: E402
import substack_config as C  # noqa: E402

# 契約「初始內容」逐欄照抄（contracts/config-format.md）
CONTRACT_INITIAL = {
    "version": 1,
    "min_poll_interval_minutes": 30,
    "alert_policy": "every_failure",
    "image_hosts": ["substackcdn.com", "substack-post-media.s3.amazonaws.com"],
    "authors": [
        {"key": "fomosoc", "name": "FOMO研究院電子報",
         "feed_url": "https://www.fomosoc.com/feed", "enabled": True},
        {"key": "unclestocknotes", "name": "大叔美股筆記",
         "feed_url": "https://unclestocknotes.substack.com/feed", "enabled": True},
    ],
}


def good():
    return copy.deepcopy(CONTRACT_INITIAL)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class ValidateTest(unittest.TestCase):
    def assertRejects(self, cfg, needle=None):
        reasons = C.validate(cfg)
        self.assertTrue(reasons, "應該被拒絕但通過了：%r" % (cfg,))
        if needle:
            self.assertTrue(any(needle in r for r in reasons),
                            "拒絕原因應提到 %r，實際 %r" % (needle, reasons))

    def test_contract_initial_is_valid(self):
        self.assertEqual(C.validate(good()), [])

    def test_version_must_be_one(self):
        for bad in (0, 2, "1", None, True):
            cfg = good()
            cfg["version"] = bad
            self.assertRejects(cfg, "version")

    def test_min_poll_interval_bounds(self):
        for ok_value in (10, 30, 1440):
            cfg = good()
            cfg["min_poll_interval_minutes"] = ok_value
            self.assertEqual(C.validate(cfg), [], "%s 應該可接受" % ok_value)
        for bad in (9, 0, -1, 1441, 30.5, "30", True, None):
            cfg = good()
            cfg["min_poll_interval_minutes"] = bad
            self.assertRejects(cfg, "min_poll_interval_minutes")

    def test_alert_policy_enum(self):
        for ok_value in ("every_failure", "consecutive_3"):
            cfg = good()
            cfg["alert_policy"] = ok_value
            self.assertEqual(C.validate(cfg), [])
        for bad in ("EVERY_FAILURE", "consecutive3", "", None, 1):
            cfg = good()
            cfg["alert_policy"] = bad
            self.assertRejects(cfg, "alert_policy")

    def test_image_hosts_rules(self):
        cfg = good()
        cfg["image_hosts"] = []
        self.assertEqual(C.validate(cfg), [], "0 個圖片主機是允許的")
        cfg = good()
        cfg["image_hosts"] = ["h%d.example.com" % i for i in range(20)]
        self.assertEqual(C.validate(cfg), [])
        cfg = good()
        cfg["image_hosts"] = ["h%d.example.com" % i for i in range(21)]
        self.assertRejects(cfg, "image_hosts")
        for bad in ("SubstackCDN.com", "substackcdn.com/path", "substackcdn.com:443",
                    "203.0.113.7", "::1", "https://substackcdn.com", "", "localhost:8080"):
            cfg = good()
            cfg["image_hosts"] = [bad]
            self.assertRejects(cfg, "image_hosts")

    def test_authors_count_and_uniqueness(self):
        cfg = good()
        cfg["authors"] = []
        self.assertRejects(cfg, "authors")
        cfg = good()
        cfg["authors"] = [{"key": "k%d" % i, "name": "N%d" % i,
                           "feed_url": "https://h%d.example.com/feed" % i, "enabled": True}
                          for i in range(21)]
        self.assertRejects(cfg, "authors")
        cfg = good()
        cfg["authors"][1]["key"] = cfg["authors"][0]["key"]
        self.assertRejects(cfg, "key")
        cfg = good()
        cfg["authors"][1]["feed_url"] = cfg["authors"][0]["feed_url"]
        self.assertRejects(cfg, "feed_url")

    def test_author_key_pattern(self):
        for ok_value in ("ab", "a1", "a-b", "0abc", "a" * 40):
            cfg = good()
            cfg["authors"][0]["key"] = ok_value
            self.assertEqual(C.validate(cfg), [], "%s 應該可接受" % ok_value)
        for bad in ("a", "-ab", "Ab", "a_b", "a" * 41, "ab.", "", None, 1):
            cfg = good()
            cfg["authors"][0]["key"] = bad
            self.assertRejects(cfg, "key")

    def test_author_name_length(self):
        for ok_value in ("A", "名" * 60):
            cfg = good()
            cfg["authors"][0]["name"] = ok_value
            self.assertEqual(C.validate(cfg), [])
        for bad in ("", "名" * 61, None, 1):
            cfg = good()
            cfg["authors"][0]["name"] = bad
            self.assertRejects(cfg, "name")

    def test_feed_url_rules(self):
        for ok_value in ("https://www.fomosoc.com/feed", "https://x.substack.com/feed"):
            cfg = good()
            cfg["authors"][0]["feed_url"] = ok_value
            self.assertEqual(C.validate(cfg), [])
        bad_urls = [
            "http://www.fomosoc.com/feed",          # 非 https
            "https://u:p@www.fomosoc.com/feed",     # 帳密
            "https://www.fomosoc.com:8443/feed",    # 埠
            "https://www.fomosoc.com/feed?x=1",     # query
            "https://www.fomosoc.com/feed#a",       # fragment
            "https://www.fomosoc.com/feed/private",  # 路徑不是恰好 /feed（FR-001）
            "https://www.fomosoc.com/rss",
            "https://www.fomosoc.com/",
            "https://www.fomosoc.com",
            "https://203.0.113.7/feed",             # IP
            "https://localhost/feed",
            "", None, 1,
        ]
        for bad in bad_urls:
            cfg = good()
            cfg["authors"][0]["feed_url"] = bad
            self.assertRejects(cfg, "feed_url")

    def test_enabled_must_be_bool(self):
        for bad in (1, 0, "true", None):
            cfg = good()
            cfg["authors"][0]["enabled"] = bad
            self.assertRejects(cfg, "enabled")

    def test_unknown_fields_rejected(self):
        cfg = good()
        cfg["poll_interval"] = 30
        self.assertRejects(cfg, "poll_interval")
        cfg = good()
        cfg["authors"][0]["url"] = "https://x/feed"
        self.assertRejects(cfg, "url")

    def test_missing_fields_rejected(self):
        for key in ("version", "min_poll_interval_minutes", "alert_policy", "image_hosts",
                    "authors"):
            cfg = good()
            del cfg[key]
            self.assertRejects(cfg, key)
        for key in ("key", "name", "feed_url", "enabled"):
            cfg = good()
            del cfg["authors"][0][key]
            self.assertRejects(cfg, key)

    def test_non_object_config_rejected(self):
        for bad in ([], "x", 1, None):
            self.assertRejects(bad)

    def test_allowed_image_hosts_includes_author_feed_hosts(self):
        hosts = C.allowed_image_hosts(good())
        self.assertIn("substackcdn.com", hosts)
        self.assertIn("www.fomosoc.com", hosts)
        self.assertIn("unclestocknotes.substack.com", hosts)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)

    def test_missing_file_raises_config_missing(self):
        with self.assertRaises(C.ConfigMissing):
            C.load_config(self.dir)

    def test_invalid_file_raises_with_reasons(self):
        path = os.path.join(self.dir, C.CONFIG_FILENAME)
        cfg = good()
        cfg["min_poll_interval_minutes"] = 5
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg))
        with self.assertRaises(C.ConfigInvalid) as cm:
            C.load_config(self.dir)
        self.assertTrue(cm.exception.reasons)

    def test_broken_json_raises_config_invalid(self):
        path = os.path.join(self.dir, C.CONFIG_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(C.ConfigInvalid):
            C.load_config(self.dir)

    def test_valid_file_loads(self):
        C.write_config(self.dir, good())
        self.assertEqual(C.load_config(self.dir)["version"], 1)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.path = os.path.join(self.dir, C.CONFIG_FILENAME)

    def test_write_rejects_invalid(self):
        cfg = good()
        cfg["alert_policy"] = "nope"
        with self.assertRaises(C.ConfigInvalid):
            C.write_config(self.dir, cfg)
        self.assertFalse(os.path.exists(self.path))

    def test_write_is_atomic_and_leaves_old_bytes_on_failure(self):
        C.write_config(self.dir, good())
        before = read_bytes(self.path)
        orig_replace = os.replace

        def boom(src, dst):
            raise OSError("注入的 os.replace 失敗")
        os.replace = boom
        try:
            cfg = good()
            cfg["min_poll_interval_minutes"] = 60
            with self.assertRaises(OSError):
                C.write_config(self.dir, cfg)
        finally:
            os.replace = orig_replace
        self.assertEqual(read_bytes(self.path), before, "寫到一半失敗不得動到舊檔")
        self.assertEqual(glob.glob(os.path.join(self.dir, "*.tmp*")), [],
                         "失敗後不得留下暫存檔")

    def test_backup_created_and_pruned_to_ten(self):
        C.write_config(self.dir, good())
        # 預先放 15 份舊備份（時間戳不同）
        for i in range(15):
            name = "%s.bak-20261101-00%02d00" % (C.CONFIG_FILENAME, i)
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write("{}")
        cfg = good()
        cfg["min_poll_interval_minutes"] = 45
        C.write_config(self.dir, cfg)
        baks = sorted(glob.glob(os.path.join(self.dir, C.CONFIG_FILENAME + ".bak-*")))
        self.assertEqual(len(baks), 10, "備份只保留最新 10 份，實際 %d" % len(baks))
        self.assertEqual(C.load_config(self.dir)["min_poll_interval_minutes"], 45)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.path = os.path.join(self.dir, C.CONFIG_FILENAME)

    def run_cli(self, *args, **kwargs):
        out = io.StringIO()
        env = kwargs.pop("env", {})
        code = C.main(["--data-dir", self.dir] + list(args), env=env, out=out)
        return code, out.getvalue()

    def test_requires_data_dir(self):
        out = io.StringIO()
        self.assertEqual(C.main(["init"], env={}, out=out), 2)

    def test_init_creates_contract_content(self):
        code, text = self.run_cli("init")
        self.assertEqual(code, 0, text)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, CONTRACT_INITIAL)

    def test_init_refuses_to_overwrite(self):
        self.run_cli("init")
        before = read_bytes(self.path)
        code, text = self.run_cli("init")
        self.assertEqual(code, 2)
        self.assertEqual(read_bytes(self.path), before)

    def test_show_prints_whole_config(self):
        self.run_cli("init")
        code, text = self.run_cli("show")
        self.assertEqual(code, 0)
        self.assertIn("fomosoc", text)
        self.assertIn("every_failure", text)
        self.assertEqual(json.loads(text), CONTRACT_INITIAL)

    def test_validate_prints_ok_or_reason(self):
        self.run_cli("init")
        code, text = self.run_cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("OK", text)

        cfg = good()
        cfg["alert_policy"] = "nope"
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg))
        code, text = self.run_cli("validate")
        self.assertEqual(code, 2)
        self.assertIn("alert_policy", text)

    def test_validate_missing_file(self):
        code, text = self.run_cli("validate")
        self.assertEqual(code, 2)
        self.assertNotEqual(text.strip(), "")

    def test_production_data_dir_refused(self):
        """正式目錄＋沒有旗標 → exit 2，且不建立任何檔案（2026-08-22 事故教訓）。"""
        prod = article_data_guard.PRODUCTION_DATA_DIR
        before = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        out = io.StringIO()
        code = C.main(["--data-dir", prod, "init"], env={}, out=out)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.isfile(os.path.join(prod, C.CONFIG_FILENAME)),
                         "拒絕後不得建立設定檔")
        after = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        self.assertEqual(before, after, "拒絕後正式資料目錄內容不得改變")

    def test_production_data_dir_allowed_with_flag_but_not_written_here(self):
        """帶旗標時 guard 本身不拒絕（只驗 guard 行為，不真的寫正式目錄）。"""
        prod = article_data_guard.PRODUCTION_DATA_DIR
        resolved = article_data_guard.resolve_data_dir(
            prod, env={"ALPHAVIBE_ALLOW_PRODUCTION_WRITE": "1"})
        self.assertEqual(resolved, prod)


# ================================================================ T033：圖片主機白名單（FR-034）
class ImageHostCliTest(unittest.TestCase):
    """`add-image-host`／`remove-image-host`：PO 在對話中增修白名單，不編輯程式。"""

    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.path = os.path.join(self.dir, C.CONFIG_FILENAME)
        out = io.StringIO()
        self.assertEqual(C.main(["--data-dir", self.dir, "init"], env={}, out=out), 0,
                         out.getvalue())

    def run_cli(self, *args):
        out = io.StringIO()
        code = C.main(["--data-dir", self.dir] + list(args), env={}, out=out)
        return code, out.getvalue()

    def hosts(self):
        return C.load_config(self.dir)["image_hosts"]

    def backups(self):
        return sorted(glob.glob(self.path + C.BACKUP_SUFFIX + "*"))

    def test_add_lowercase_domain_is_accepted_and_backed_up(self):
        before = read_bytes(self.path)
        code, text = self.run_cli("add-image-host", "images.example.com")
        self.assertEqual(code, 0, text)
        self.assertIn("images.example.com", self.hosts())
        self.assertEqual(len(self.backups()), 1, "每次寫入都要有備份")
        self.assertEqual(read_bytes(self.backups()[0]), before, "備份必須是寫入前的內容")

    def test_add_rejects_bad_hosts_without_writing(self):
        before = read_bytes(self.path)
        for bad in ("Images.Example.com", "images.example.com/path", "images.example.com:443",
                    "203.0.113.7", "localhost", "https://images.example.com", "",
                    "images example.com"):
            code, text = self.run_cli("add-image-host", bad)
            self.assertEqual(code, 2, "%r 應該被拒絕：%s" % (bad, text))
            self.assertEqual(read_bytes(self.path), before, "被拒絕時不得寫檔")
        self.assertEqual(self.backups(), [], "被拒絕時不得產生備份")

    def test_add_duplicate_is_refused(self):
        existing = self.hosts()[0]
        code, text = self.run_cli("add-image-host", existing)
        self.assertEqual(code, 2, text)
        self.assertEqual(self.hosts().count(existing), 1)

    def test_add_beyond_twenty_is_refused(self):
        for i in range(C.MAX_IMAGE_HOSTS - len(self.hosts())):
            code, text = self.run_cli("add-image-host", "h%d.example.com" % i)
            self.assertEqual(code, 0, text)
        self.assertEqual(len(self.hosts()), C.MAX_IMAGE_HOSTS)
        code, text = self.run_cli("add-image-host", "overflow.example.com")
        self.assertEqual(code, 2, text)
        self.assertEqual(len(self.hosts()), C.MAX_IMAGE_HOSTS)
        self.assertNotIn("overflow.example.com", self.hosts())

    def test_remove_existing_host(self):
        target = self.hosts()[0]
        code, text = self.run_cli("remove-image-host", target)
        self.assertEqual(code, 0, text)
        self.assertNotIn(target, self.hosts())
        self.assertEqual(len(self.backups()), 1)

    def test_remove_unknown_host_is_refused(self):
        before = read_bytes(self.path)
        code, text = self.run_cli("remove-image-host", "nope.example.com")
        self.assertEqual(code, 2, text)
        self.assertEqual(read_bytes(self.path), before)

    def test_author_feed_host_cannot_be_removed(self):
        """作者 feed 主機是自動允許項、不在 image_hosts，不能被移除（contracts/cli.md §2）。"""
        feed_host = "unclestocknotes.substack.com"
        self.assertIn(feed_host, C.allowed_image_hosts(C.load_config(self.dir)))
        self.assertNotIn(feed_host, self.hosts())
        before = read_bytes(self.path)
        code, text = self.run_cli("remove-image-host", feed_host)
        self.assertEqual(code, 2, text)
        self.assertIn("feed", text)
        self.assertEqual(read_bytes(self.path), before)

    def test_host_argument_is_required(self):
        self.assertEqual(self.run_cli("add-image-host")[0], 2)
        self.assertEqual(self.run_cli("remove-image-host")[0], 2)

    def test_missing_config_is_refused(self):
        other = F.temp_data_dir(self)
        out = io.StringIO()
        code = C.main(["--data-dir", other, "add-image-host", "a.example.com"], env={}, out=out)
        self.assertEqual(code, 2, out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(other, C.CONFIG_FILENAME)))


class AlertPolicyCliTest(unittest.TestCase):
    """T037：`set-alert-policy every_failure|consecutive_3`（FR-032：PO 可隨時切換、不得寫死）。"""

    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.path = os.path.join(self.dir, C.CONFIG_FILENAME)
        out = io.StringIO()
        self.assertEqual(C.main(["--data-dir", self.dir, "init"], env={}, out=out), 0,
                         out.getvalue())

    def run_cli(self, *args):
        out = io.StringIO()
        code = C.main(["--data-dir", self.dir] + list(args), env={}, out=out)
        return code, out.getvalue()

    def policy(self):
        return C.load_config(self.dir)["alert_policy"]

    def backups(self):
        return sorted(glob.glob(self.path + C.BACKUP_SUFFIX + "*"))

    def test_switch_to_consecutive_3_and_back(self):
        self.assertEqual(self.policy(), "every_failure", "預設為初期策略")
        before = read_bytes(self.path)
        code, text = self.run_cli("set-alert-policy", "consecutive_3")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.policy(), "consecutive_3")
        self.assertIn("consecutive_3", text)
        self.assertEqual(len(self.backups()), 1, "寫入要有備份")
        self.assertEqual(read_bytes(self.backups()[0]), before, "備份必須是寫入前的內容")
        cfg = C.load_config(self.dir)
        expected = good()
        expected["alert_policy"] = "consecutive_3"
        self.assertEqual(cfg, expected, "只改 alert_policy，其餘欄位不動")
        code, text = self.run_cli("set-alert-policy", "every_failure")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.policy(), "every_failure")
        self.assertEqual(len(self.backups()), 2)

    def test_other_values_refused_without_writing(self):
        before = read_bytes(self.path)
        for bad in ("consecutive_2", "EVERY_FAILURE", "never", "", "every_failure "):
            code, text = self.run_cli("set-alert-policy", bad)
            self.assertEqual(code, 2, "%r 應該被拒絕：%s" % (bad, text))
            self.assertEqual(read_bytes(self.path), before, "被拒絕時不得寫檔")
        self.assertEqual(self.backups(), [], "被拒絕時不得產生備份")

    def test_argument_is_required(self):
        before = read_bytes(self.path)
        self.assertEqual(self.run_cli("set-alert-policy")[0], 2)
        self.assertEqual(read_bytes(self.path), before)

    def test_missing_config_is_refused(self):
        other = F.temp_data_dir(self)
        out = io.StringIO()
        code = C.main(["--data-dir", other, "set-alert-policy", "consecutive_3"], env={},
                      out=out)
        self.assertEqual(code, 2, out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(other, C.CONFIG_FILENAME)))

    def test_production_data_dir_refused(self):
        prod = article_data_guard.PRODUCTION_DATA_DIR
        out = io.StringIO()
        code = C.main(["--data-dir", prod, "set-alert-policy", "consecutive_3"], env={},
                      out=out)
        self.assertEqual(code, 2, out.getvalue())


if __name__ == "__main__":
    unittest.main()
