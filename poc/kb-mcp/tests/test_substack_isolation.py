"""T013：011 與 010 的隔離守門（FR-006、FR-019、FR-021、FR-027；research R1）。

**守門型測試：建立時就該是綠的，之後每個階段都必須保持綠。**

T-A 靜態隔離：`poc/kb-mcp/substack_*.py` 全文（連註解、docstring、字串都算）不得出現
010 文章庫的資料庫檔名、儲存模組名或類別名，也不得出現該模組的寫入方法名（以**完整識別字**
比對，避免誤傷 011 自己的 `insert_article_with_images` 這類名稱）；反向：010 的三個模組不得
出現 `substack` 字樣。掃描器本身有反向測試（只在註解裡提到也必須被抓到）。

FR-019 靜態：011 的模組不得 import 模型／子行程／鑰匙圈相關模組。
FR-027 可驗證項：資料只在 gitignore 的資料目錄、沒有任何 STND／MCP 入口、備份目的地在家目錄底下。

T-B（T026）：010 的排程轉寫流水線不會選取 011 的圖——同一個資料目錄下同時存在 010 的
文章庫與 011 的 `substack.db`（含已下載圖檔、含圖位標記的內文），010 的五個選取查詢與
`transcription_pipeline --dry-run` 都只能看到 010 自己的圖，`substack.db` 位元組與 mtime 不變。
"""
import datetime
import glob
import os
import re
import shutil
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


class PipelineDoesNotSelectSubstackTest(unittest.TestCase):
    """T-B：011 文章不得進入 010 的排程轉寫流水線（FR-021、SC-003；research R1）。

    設計正確時本測試建立即為綠；若失敗代表 010 會選到 011，必須停下回報，**不得改 010**。
    """

    def setUp(self):
        import _pipeline_fixture as PF
        import _substack_fixture as SF
        import article_store
        import substack_store

        self.data = os.path.realpath(tempfile.mkdtemp(prefix="substack-tb-"))
        self.addCleanup(shutil.rmtree, self.data, ignore_errors=True)
        # 010：1 篇文章、3 張待轉寫圖（真的 PNG 檔）
        self.ten_images = PF.build_data_dir(self.data, 3)
        store = article_store.ArticleStore(self.data)
        self.ten_ids = sorted(r["id"] for r in store.images_to_transcribe())
        store.close()
        self.assertEqual(len(self.ten_ids), 3, "010 fixture 必須真的有待轉寫圖，否則守門空轉")

        # 011：同一個資料目錄下的獨立庫，含「已下載」圖檔與含圖位標記的內文
        sub = substack_store.SubstackStore(self.data)
        article_id = sub.insert_article_with_images(
            SF.article_row(body_text="內文〔圖 1｜圖說：合成圖說｜alt：合成 alt〕內文"),
            SF.image_rows(2))
        image_dir = os.path.join(self.data, "substack_images", str(article_id))
        os.makedirs(image_dir, exist_ok=True)
        self.sub_image_ids = []
        for image in sub.list_images(article_id):
            rel = os.path.join("substack_images", str(article_id), "%d.png" % image["seq"])
            with open(os.path.join(self.data, rel), "wb") as f:
                f.write(PF.make_png(200, 150, shade=image["seq"]))
            sub.set_image_downloaded(image["id"], rel, sha256="x" * 64, size_bytes=10)
            self.sub_image_ids.append(image["id"])
        sub.close()
        self.sub_db = os.path.join(self.data, substack_store.DB_FILENAME)
        self.before = os.stat(self.sub_db)

    def _assert_substack_db_untouched(self):
        after = os.stat(self.sub_db)
        self.assertEqual(after.st_size, self.before.st_size, "substack.db 位元組不得改變")
        self.assertEqual(after.st_mtime, self.before.st_mtime, "substack.db mtime 不得改變")

    def test_ten_selection_queries_only_return_ten_images(self):
        import article_store
        store = article_store.ArticleStore.open_readonly(self.data)
        try:
            selections = {
                "images_to_transcribe": store.images_to_transcribe(),
                "images_to_backfill": store.images_to_backfill(100),
                "pipeline_images_to_verify": store.pipeline_images_to_verify(100),
                "images_for_manual_export": store.images_for_manual_export(),
            }
            counts = store.pipeline_pending_counts()
        finally:
            store.close()
        for name, rows in selections.items():
            ids = sorted(r["id"] for r in rows)
            self.assertTrue(set(ids) <= set(self.ten_ids),
                            "%s 選到了非 010 的圖：%s" % (name, ids))
            for row in rows:
                self.assertNotIn("substack", str(row.get("file_path") or "").lower(),
                                 "%s 選到 011 的圖檔路徑" % name)
        self.assertEqual(sorted(r["id"] for r in selections["images_to_transcribe"]),
                         self.ten_ids)
        self.assertEqual(counts["pending"], 3)
        self.assertEqual(counts["to_verify"], 0)
        self._assert_substack_db_untouched()

    def test_pipeline_dry_run_only_lists_ten_images(self):
        import transcription_pipeline
        lines = []
        code = transcription_pipeline.run(
            ["--data-dir", self.data, "--dry-run", "--claude-bin", "/usr/bin/true"],
            say=lines.append,
            deps={"token_getter": lambda: None, "paddle_batch": lambda paths: [],
                  "notify_fn": lambda text: None,
                  "now": lambda: datetime.datetime(2026, 11, 25, 23, 40,
                                                   tzinfo=datetime.timezone(
                                                       datetime.timedelta(hours=8)))},
            env={})
        text = "\n".join(lines)
        self.assertEqual(code, 0, text)
        self.assertNotIn("substack", text.lower(), "流水線 dry-run 不得提到 011 的任何東西")
        listed = sorted(int(m) for m in re.findall(r"image_id=(\d+)", text))
        self.assertEqual(listed, self.ten_ids, text)
        self.assertFalse(set(listed) & set(self.sub_image_ids) - set(self.ten_ids))
        self._assert_substack_db_untouched()


if __name__ == "__main__":
    unittest.main()
