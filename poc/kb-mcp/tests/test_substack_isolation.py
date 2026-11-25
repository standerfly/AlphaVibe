"""T013：011 與 010 的隔離守門（FR-006、FR-019、FR-021、FR-027；research R1）。

**守門型測試：建立時就該是綠的，之後每個階段都必須保持綠。**

T-A 靜態隔離：`poc/kb-mcp/substack_*.py` 全文（連註解、docstring、字串都算）不得出現
010 文章庫的資料庫檔名、儲存模組名或類別名，也不得出現該模組的寫入方法名（以**完整識別字**
比對，避免誤傷 011 自己的 `insert_article_with_images` 這類名稱）；反向：010 的三個模組不得
出現 `substack` 字樣。掃描器本身有反向測試（只在註解裡提到也必須被抓到）。

FR-019 靜態：011 的模組不得 import 模型／子行程／鑰匙圈相關模組。
FR-027 可驗證項：資料只在 gitignore 的資料目錄、沒有任何 STND／MCP 入口、備份目的地在家目錄底下。

T-B（流水線不選取 011）與執行期攔截在 T026 另加。
"""
import glob
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KB_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPO_DIR = os.path.realpath(os.path.join(KB_DIR, "..", ".."))

# 010 文章庫的識別字（011 全文不得出現；要提到它時寫「010 文章庫」）
TEN_DB_FILENAME = "articles" + ".db"
TEN_MODULE = "article" + "_store"
TEN_CLASS = "Article" + "Store"
FORBIDDEN_TEXT = (TEN_DB_FILENAME, TEN_MODULE, TEN_CLASS)

# FR-019：011 不得 import 這些（模型、子行程、鑰匙圈）
FORBIDDEN_IMPORTS = ("claude_cli_runner", "article_transcribe", "transcription_pipeline",
                     "subprocess", "keychain_secrets")
FR019_MODULES = ("substack_import.py", "substack_feed.py", "substack_html.py",
                 "substack_images.py", "substack_store.py", "substack_config.py",
                 "substack_reclassify.py")
# 010 的這些模組不得認得 011
TEN_MODULES_MUST_NOT_KNOW = ("transcription_pipeline.py", TEN_MODULE + ".py",
                             "investanchors_import.py")
# FR-027：這些對外入口不得出現 011 字樣
OUTWARD_FILES = ("server.py", "server_readonly.py", "us_stock_mcp_server.py")
TEXT_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".html",
                   ".css", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh", ".plist")


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def substack_sources():
    """011 的程式檔（不含 tests/）。"""
    return sorted(glob.glob(os.path.join(KB_DIR, "substack_*.py")))


def forbidden_method_names():
    """動態取得 010 儲存模組的寫入方法名（def set_／insert_／update_／mark_ 開頭）。"""
    src = read_text(os.path.join(KB_DIR, TEN_MODULE + ".py"))
    names = re.findall(r"^\s*def ((?:set_|insert_|update_|mark_)\w+)", src, re.M)
    return sorted(set(names))


def scan_source(path, method_names=()):
    """回傳該檔案的違規清單（空＝乾淨）。以完整識別字比對方法名。"""
    text = read_text(path)
    problems = []
    for needle in FORBIDDEN_TEXT:
        if needle in text:
            problems.append("%s 出現 %r" % (os.path.basename(path), needle))
    for name in method_names:
        if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), text):
            problems.append("%s 出現 010 的寫入方法名 %r" % (os.path.basename(path), name))
    return problems


def imported_modules(text):
    names = set()
    for match in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z0-9_.]+)", text, re.M):
        names.add(match.group(1).split(".")[0])
    return names


class StaticIsolationTest(unittest.TestCase):
    """T-A：結構隔離（FR-006、FR-021）。"""

    def test_sources_exist(self):
        self.assertTrue(substack_sources(), "找不到任何 substack_*.py（掃描器會變成空轉）")

    def test_no_reference_to_ten_article_store(self):
        method_names = forbidden_method_names()
        self.assertTrue(method_names, "沒有抓到任何 010 寫入方法名，掃描器失效")
        problems = []
        for path in substack_sources():
            problems.extend(scan_source(path, method_names))
        self.assertEqual(problems, [], "；".join(problems))

    def test_scanner_catches_mention_in_comment_only(self):
        """反向測試：只在註解裡提到也必須被抓到（否則掃描器是裝飾品）。"""
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="substack-scan-"))
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "substack_bad.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 這個註解提到 %s，應該被抓到\nX = 1\n" % TEN_DB_FILENAME)
        self.assertTrue(scan_source(path, forbidden_method_names()))

        path2 = os.path.join(tmp, "substack_bad2.py")
        with open(path2, "w", encoding="utf-8") as f:
            f.write('"""docstring 提到 %s"""\n' % TEN_CLASS)
        self.assertTrue(scan_source(path2, forbidden_method_names()))

        path3 = os.path.join(tmp, "substack_bad3.py")
        with open(path3, "w", encoding="utf-8") as f:
            f.write("import os\nX = '%s-journal'\n" % TEN_DB_FILENAME)
        self.assertTrue(scan_source(path3, forbidden_method_names()),
                        "子字串（-journal）也要被抓到")

        path4 = os.path.join(tmp, "substack_ok.py")
        with open(path4, "w", encoding="utf-8") as f:
            f.write("# 011 自己的方法名不該被誤判\n"
                    "def insert_article_with_images(self):\n    return 1\n")
        self.assertEqual(scan_source(path4, forbidden_method_names()), [],
                         "完整識別字比對：011 自己的 insert_article_with_images 不得誤傷")

    def test_ten_modules_do_not_know_about_substack(self):
        for name in TEN_MODULES_MUST_NOT_KNOW:
            path = os.path.join(KB_DIR, name)
            if not os.path.isfile(path):
                continue
            self.assertNotIn("substack", read_text(path).lower(), "%s 不得提到 011" % name)


class ForbiddenImportTest(unittest.TestCase):
    """FR-019：排程零模型、零子行程、零鑰匙圈。"""

    def test_no_model_or_subprocess_imports(self):
        checked = 0
        for name in FR019_MODULES:
            path = os.path.join(KB_DIR, name)
            if not os.path.isfile(path):
                continue                        # 尚未建立的檔案跳過，不視為失敗
            checked += 1
            text = read_text(path)
            imported = imported_modules(text)
            for forbidden in FORBIDDEN_IMPORTS:
                self.assertNotIn(forbidden, imported, "%s 不得 import %s" % (name, forbidden))
                self.assertIsNone(
                    re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % forbidden, text),
                    "%s 不得提及 %s" % (name, forbidden))
        self.assertGreater(checked, 0, "沒有任何 011 模組被檢查")


class Fr027Test(unittest.TestCase):
    """FR-027 可驗證項（plan.md）：資料不外流、沒有對外入口。"""

    def test_gitignore_covers_data_dirs(self):
        text = read_text(os.path.join(REPO_DIR, ".gitignore"))
        self.assertIn("poc/data/", text)
        self.assertIn("poc/data-test-substack/", text)

    def test_no_outward_entry_point_mentions_substack(self):
        for name in OUTWARD_FILES:
            path = os.path.join(KB_DIR, name)
            if not os.path.isfile(path):
                continue
            self.assertNotIn("substack", read_text(path).lower(),
                             "%s 不得出現 011 字樣（第 1 包沒有任何對外入口）" % name)

    def test_app_has_no_substack_reference(self):
        app_dir = os.path.join(REPO_DIR, "app")
        scanned = 0
        for root, dirs, files in os.walk(app_dir):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".venv")]
            for name in files:
                if os.path.splitext(name)[1].lower() not in TEXT_EXTENSIONS:
                    continue
                path = os.path.join(root, name)
                scanned += 1
                self.assertNotIn("substack", read_text(path).lower(),
                                 "%s 不得出現 011 字樣" % path)
        self.assertGreater(scanned, 0, "app/ 一個檔案都沒掃到，守門失效")

    def test_backup_destination_is_under_home(self):
        text = read_text(os.path.join(KB_DIR, "backup_databases.py"))
        match = re.search(r"DEFAULT_DEST\s*=\s*os\.path\.expanduser\(\s*\"([^\"]+)\"", text)
        self.assertIsNotNone(match, "找不到 DEFAULT_DEST 的 expanduser 寫法")
        dest = os.path.expanduser(match.group(1))
        self.assertTrue(dest.startswith(os.path.expanduser("~")),
                        "備份目的地必須在家目錄底下（不得指向對外位置）")


if __name__ == "__main__":
    unittest.main()
