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

T048 攔截法可行性（InterceptFeasibilityTest）：先證明「在全新 /usr/bin/python3 子行程裡 monkeypatch
`sqlite3.connect`／`builtins.open`／`os.open` 能攔到四種開檔方式」，T-C 才有意義。

T049 T-C（ManualTranscribeDoesNotTouchTenTest）：全新子行程、攔截所有開檔路徑、讓 010 儲存類別
一被建構就拋例外，跑完 `substack_transcribe.py --plan` 與 `--run --confirm`（假 claude 腳本），
斷言沒有任何開啟路徑是 010 文章庫、010 文章庫位元組不變、未新建、LaunchAgents 無新檔。
T-D（ScheduleScanTest）：`ops/launchd/*.plist` 皆不引用 `substack_transcribe`。
"""
import datetime
import fnmatch
import glob
import os
import plistlib
import re
import shutil
import subprocess
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
                 "substack_reclassify.py", "substack_health.py")
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


# ================================================================ T048／T049 執行期攔截
SYSTEM_PYTHON = "/usr/bin/python3"          # 3.9.6；T-C 必須在與正式環境相同的直譯器跑
SUBPROCESS_TIMEOUT = 120

# 包裝腳本：先攔截再 runpy 目標腳本。用法：
#   python3 wrapper.py <記錄檔> <plain|guard010> <目標腳本> [目標參數...]
# 記錄檔每行「種類<TAB>realpath」；記錄檔本身在攔截之前就開好（不會記到自己）。
# guard010 模式另外：讓 010 儲存類別的建構子與唯讀開庫一被呼叫就記錄並拋例外，
# 並記錄每個子行程的第一個參數（證明沒有執行 security 之類的鑰匙圈程式）。
INTERCEPT_WRAPPER = r'''
import builtins, io, os, runpy, sqlite3, sqlite3.dbapi2, sys, urllib.parse

LOG_PATH, MODE, TARGET = sys.argv[1], sys.argv[2], sys.argv[3]
_orig_open, _orig_os_open, _orig_connect = builtins.open, os.open, sqlite3.connect
_log = _orig_open(LOG_PATH, "a", encoding="utf-8")


def _record(kind, path):
    try:
        path = os.fspath(path)
    except TypeError:
        return
    if isinstance(path, bytes):
        path = path.decode("utf-8", "replace")
    if not isinstance(path, str) or not path:
        return
    _log.write("%s\t%s\n" % (kind, os.path.realpath(path)))
    _log.flush()


def _open(file, *a, **k):
    if not isinstance(file, int):
        _record("open", file)
    return _orig_open(file, *a, **k)


def _os_open(path, *a, **k):
    _record("os.open", path)
    return _orig_os_open(path, *a, **k)


def _connect(database, *a, **k):
    if isinstance(database, str) and database.startswith("file:"):
        _record("sqlite-uri", urllib.parse.unquote(database[5:].split("?", 1)[0]))
    else:
        _record("sqlite", database)
    return _orig_connect(database, *a, **k)


builtins.open = _open
io.open = _open
os.open = _os_open
sqlite3.connect = _connect
sqlite3.dbapi2.connect = _connect

if MODE == "guard010":
    import subprocess
    sys.path.insert(0, os.path.dirname(os.path.abspath(TARGET)))
    mod_name = "article" + "_store"
    cls_name = "Article" + "Store"
    mod = __import__(mod_name)
    cls = getattr(mod, cls_name)

    def _boom(*a, **k):
        _log.write("TEN_STORE_CALLED\t-\n")
        _log.flush()
        raise RuntimeError("010 storage must not be used")

    cls.__init__ = _boom
    cls.open_readonly = classmethod(_boom)
    _OrigPopen = subprocess.Popen

    class _LoggingPopen(_OrigPopen):
        def __init__(self, args, *a, **k):
            first = args[0] if isinstance(args, (list, tuple)) else args
            _log.write("popen\t%s\n" % os.path.basename(str(first)))
            _log.flush()
            _OrigPopen.__init__(self, args, *a, **k)

    subprocess.Popen = _LoggingPopen

sys.argv = [TARGET] + sys.argv[4:]
code = 0
try:
    runpy.run_path(TARGET, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
_log.close()
sys.exit(code)
'''

# T048 的最小目標腳本：四種開檔方式＋「攔截之後才 import 的模組」
FEASIBILITY_TARGET = r'''
import os, sqlite3, sys
d = sys.argv[1]
sys.path.insert(0, d)
sqlite3.connect(os.path.join(d, "via_connect.db")).close()
sqlite3.connect("file:%s?mode=rwc" % os.path.join(d, "via_uri.db"), uri=True).close()
with open(os.path.join(d, "via_open.txt"), "w") as f:
    f.write("x")
fd = os.open(os.path.join(d, "via_open.txt"), os.O_RDONLY)
os.close(fd)
import late_helper                      # 攔截之後才 import、模組頂層 import sqlite3
late_helper.touch(os.path.join(d, "via_late.db"))
from sqlite3 import dbapi2              # 標準庫子模組
dbapi2.connect(os.path.join(d, "via_dbapi2.db")).close()
from sqlite3 import connect as late_connect
late_connect(os.path.join(d, "via_from_import.db")).close()
'''

LATE_HELPER = "import sqlite3\n\n\ndef touch(path):\n    sqlite3.connect(path).close()\n"


def child_env(home):
    user = os.environ.get("USER") or "tester"
    return {"PATH": "/usr/bin:/bin", "HOME": home, "LANG": "C",
            "USER": user, "LOGNAME": os.environ.get("LOGNAME") or user}


def run_wrapped(work, mode, target, args, home):
    """以全新的 /usr/bin/python3 子行程跑包裝腳本；回傳 (returncode, stdout, stderr, 記錄列)。"""
    wrapper = os.path.join(work, "intercept_wrapper.py")
    with open(wrapper, "w", encoding="utf-8") as f:
        f.write(INTERCEPT_WRAPPER)
    log_path = os.path.join(work, "intercept-%s.log" % len(os.listdir(work)))
    open(log_path, "w").close()
    proc = subprocess.run([SYSTEM_PYTHON, wrapper, log_path, mode, target] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work,
                          env=child_env(home), timeout=SUBPROCESS_TIMEOUT,
                          universal_newlines=True)
    with open(log_path, encoding="utf-8") as f:
        rows = [tuple(ln.rstrip("\n").split("\t", 1)) for ln in f if ln.strip()]
    return proc.returncode, proc.stdout, proc.stderr, rows


def db_bytes(path):
    """比照 tests/test_article_verification.py 的 db_bytes()：整檔位元組（不存在回 None）。"""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(os.path.isfile(SYSTEM_PYTHON), "需要 /usr/bin/python3")
class InterceptFeasibilityTest(unittest.TestCase):
    """T048：攔截法本身先被證明可行（否則 T-C 會是偽陰性）。"""

    def setUp(self):
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="substack-intercept-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.files = os.path.join(self.work, "files")
        os.makedirs(self.files)
        with open(os.path.join(self.files, "late_helper.py"), "w") as f:
            f.write(LATE_HELPER)
        self.target = os.path.join(self.work, "feasibility_target.py")
        with open(self.target, "w") as f:
            f.write(FEASIBILITY_TARGET)

    def test_child_is_python_39(self):
        out = subprocess.run([SYSTEM_PYTHON, "-c", "import sys;print(sys.version_info[:2])"],
                             stdout=subprocess.PIPE, universal_newlines=True,
                             timeout=SUBPROCESS_TIMEOUT).stdout
        self.assertEqual(out.strip(), "(3, 9)")

    def test_all_open_methods_are_recorded(self):
        import builtins
        import sqlite3
        parent = (builtins.open, os.open, sqlite3.connect)
        code, out, err, rows = run_wrapped(self.work, "plain", self.target, [self.files],
                                           self.work)
        self.assertEqual(code, 0, err)
        f = lambda name: os.path.join(self.files, name)       # noqa: E731
        expected = [
            ("sqlite", f("via_connect.db")),
            ("sqlite-uri", f("via_uri.db")),
            ("open", f("via_open.txt")),
            ("os.open", f("via_open.txt")),
            ("sqlite", f("via_late.db")),
            ("sqlite", f("via_dbapi2.db")),
            ("sqlite", f("via_from_import.db")),
        ]
        for item in expected:
            self.assertIn(item, rows, "攔不到：%s（記錄：%s）" % (item, rows))
        self.assertEqual((builtins.open, os.open, sqlite3.connect), parent,
                         "子行程的攔截不得污染父行程")


@unittest.skipUnless(os.path.isfile(SYSTEM_PYTHON), "需要 /usr/bin/python3")
class ManualTranscribeDoesNotTouchTenTest(unittest.TestCase):
    """T049 T-C：手動轉寫全程（含 import 階段）不開 010 文章庫、不建構 010 儲存類別。"""

    TEN_SUFFIXES = (TEN_DB_FILENAME, TEN_DB_FILENAME + "-journal", TEN_DB_FILENAME + "-wal",
                    TEN_DB_FILENAME + "-shm")

    def setUp(self):
        import _pipeline_fixture as PF
        self.PF = PF
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="substack-tc-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.home = os.path.join(self.work, "home")
        os.makedirs(self.home)
        self.agents = os.path.join(self.home, "Library", "LaunchAgents")
        self.stub = PF.Stub(self.work)
        self.stub.respond("sonnet", {"kind": "ok", "text": PF.TABLE_A})
        self.stub.respond("opus", {"kind": "verify", "so": {"verdict": "ok", "issues": []}})
        self.target = os.path.join(KB_DIR, "substack_transcribe.py")

    def _build_substack(self, data):
        import _substack_fixture as SF
        import substack_store
        SF.write_config(data)
        sub = substack_store.SubstackStore(data)
        try:
            article_id = sub.insert_article_with_images(SF.article_row(), SF.image_rows(2))
            for image in sub.list_images(article_id):
                rel = os.path.join("substack_images", str(article_id), "%d.png" % image["seq"])
                os.makedirs(os.path.join(data, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(data, rel), "wb") as f:
                    f.write(self.PF.make_png(220 + image["seq"], 150, shade=image["seq"]))
                sub.set_image_downloaded(image["id"], rel, sha256="0" * 64, size_bytes=10)
        finally:
            sub.close()

    def _plan_and_run(self, data):
        code, out, err, rows_plan = run_wrapped(self.work, "guard010", self.target,
                                                ["--data-dir", data, "--plan"], self.home)
        self.assertEqual(code, 0, out + err)
        m = re.search(r"確認碼：([0-9a-f]{6})", out)
        self.assertIsNotNone(m, out + err)
        code, out, err, rows_run = run_wrapped(
            self.work, "guard010", self.target,
            ["--data-dir", data, "--run", "--confirm", m.group(1), "--claude-bin",
             self.stub.path, "--timeout-sec", "60"], self.home)
        self.assertEqual(code, 0, out + err)
        self.assertIn("結果=ok", out)
        return rows_plan + rows_run

    def _assert_never_opened_ten(self, rows):
        opened = [p for kind, p in rows if kind in ("open", "os.open", "sqlite", "sqlite-uri")]
        self.assertTrue(any(p.endswith(os.sep + "substack.db") for p in opened),
                        "攔截記錄裡沒有 substack.db：攔截可能失效（偽陰性）")
        bad = [p for p in opened if p.endswith(self.TEN_SUFFIXES)]
        self.assertEqual(bad, [], "手動轉寫開啟了 010 文章庫：%s" % bad)
        self.assertNotIn(("TEN_STORE_CALLED", "-"), rows, "010 儲存類別被建構或唯讀開庫")
        popen = [p for kind, p in rows if kind == "popen"]
        self.assertTrue(popen, "沒有任何子行程：假 claude 沒被呼叫，測試空轉")
        self.assertEqual(set(popen), {"claude"}, "只能執行 --claude-bin（不得執行鑰匙圈程式）")

    def test_full_flow_with_ten_db_present(self):
        data = os.path.join(self.work, "data")
        os.makedirs(data)
        self.PF.build_data_dir(data, 2)            # 010 fixture（父行程建立；子行程不得碰）
        self._build_substack(data)
        ten_db = os.path.join(data, TEN_DB_FILENAME)
        before = db_bytes(ten_db)
        self.assertIsNotNone(before)
        listing_before = set(os.listdir(data))
        rows = self._plan_and_run(data)
        self._assert_never_opened_ten(rows)
        self.assertEqual(db_bytes(ten_db), before, "010 文章庫位元組不得改變")
        new_entries = set(os.listdir(data)) - listing_before
        self.assertTrue(new_entries <= {".substack_import.lock"}, new_entries)
        self.assertEqual(len(self.stub.calls()), 4, "2 張圖 × (reader-1＋驗證者)")
        self.assertFalse(os.path.isdir(self.agents) and os.listdir(self.agents),
                         "不得寫入任何 LaunchAgents plist")

    def test_ten_db_not_created_when_absent(self):
        data = os.path.join(self.work, "data-no-ten")
        os.makedirs(data)
        self._build_substack(data)
        rows = self._plan_and_run(data)
        self._assert_never_opened_ten(rows)
        for suffix in self.TEN_SUFFIXES:
            self.assertFalse(os.path.exists(os.path.join(data, suffix)), "不得新建 %s" % suffix)
        self.assertFalse(os.path.isdir(self.agents) and os.listdir(self.agents))


class ScheduleScanTest(unittest.TestCase):
    """T049 T-D：手動轉寫不得被排程（FR-022）。"""

    def test_no_launchd_plist_references_transcribe(self):
        plists = glob.glob(os.path.join(REPO_DIR, "ops", "launchd", "*.plist"))
        self.assertTrue(plists, "ops/launchd/ 沒有任何 plist，掃描空轉")
        for path in plists:
            self.assertNotIn("substack_transcribe", read_text(path), path)

    def test_transcribe_has_no_scheduled_or_enable_option(self):
        text = read_text(os.path.join(KB_DIR, "substack_transcribe.py"))
        self.assertNotIn('"--scheduled"', text)
        self.assertNotIn('"--enable"', text)


class SubstackImportPlistTest(unittest.TestCase):
    """T059：排程 plist 結構（FR-017、FR-029、research R9）。

    這個測試在 T060 建立 `ops/launchd/com.alphavibe.substackimport.plist` 之前必須先失敗
    （plist 不存在），確認失敗後才建立檔案讓它轉綠。
    """

    PLIST_PATH = os.path.join(REPO_DIR, "ops", "launchd",
                               "com.alphavibe.substackimport.plist")
    PROD_DIR = "/Users/stander/My_project/AlphaVibe-prod"

    def setUp(self):
        # 刻意不 skip：T060 完成前，plist 不存在，open() 會拋 FileNotFoundError，
        # 讓本類別的每個測試都以 ERROR 收場——這正是 T059 要的「先確認會失敗」。
        with open(self.PLIST_PATH, "rb") as f:
            self.plist = plistlib.load(f)

    def test_plist_file_exists(self):
        self.assertTrue(os.path.isfile(self.PLIST_PATH),
                        "找不到 %s（T060 尚未建立此檔案）" % self.PLIST_PATH)

    def test_label(self):
        self.assertEqual(self.plist.get("Label"), "com.alphavibe.substackimport")

    def test_program_arguments(self):
        expected = [
            "/usr/bin/python3",
            os.path.join(self.PROD_DIR, "poc", "kb-mcp", "substack_import.py"),
            "--data-dir",
            os.path.join(self.PROD_DIR, "poc", "data"),
            "--scheduled",
        ]
        self.assertEqual(self.plist.get("ProgramArguments"), expected)

    def test_start_calendar_interval_has_exactly_two_entries(self):
        intervals = self.plist.get("StartCalendarInterval")
        self.assertEqual(intervals, [
            {"Hour": 22, "Minute": 0},
            {"Hour": 1, "Minute": 0},
        ])

    def test_no_run_at_load_or_keep_alive(self):
        self.assertNotIn("RunAtLoad", self.plist)
        self.assertNotIn("KeepAlive", self.plist)

    def test_environment_variables(self):
        env = self.plist.get("EnvironmentVariables")
        self.assertEqual(set(env.keys()), {"PATH", "ALPHAVIBE_ALLOW_PRODUCTION_WRITE"})
        self.assertEqual(env.get("PATH"), "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(env.get("ALPHAVIBE_ALLOW_PRODUCTION_WRITE"), "1")

    def test_log_paths_match_rotate_logs_glob(self):
        import rotate_logs
        out_path = os.path.expanduser(self.plist.get("StandardOutPath") or "")
        err_path = os.path.expanduser(self.plist.get("StandardErrorPath") or "")
        self.assertEqual(out_path, os.path.expanduser("~/Library/Logs/alphavibe-substack.log"))
        self.assertEqual(err_path,
                         os.path.expanduser("~/Library/Logs/alphavibe-substack.err.log"))
        self.assertTrue(fnmatch.fnmatch(out_path, rotate_logs.DEFAULT_LOG_GLOB),
                        "%s 不符合 rotate_logs.DEFAULT_LOG_GLOB（%s）"
                        % (out_path, rotate_logs.DEFAULT_LOG_GLOB))
        self.assertTrue(fnmatch.fnmatch(err_path, rotate_logs.DEFAULT_LOG_GLOB),
                        "%s 不符合 rotate_logs.DEFAULT_LOG_GLOB（%s）"
                        % (err_path, rotate_logs.DEFAULT_LOG_GLOB))

    def test_working_directory(self):
        self.assertEqual(self.plist.get("WorkingDirectory"), self.PROD_DIR)


if __name__ == "__main__":
    unittest.main()
