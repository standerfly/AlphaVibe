"""T046：手動少量轉寫試跑（US6；FR-020、FR-022～FR-024、SC-009；contracts/cli.md §3）。

**全程假物件**：模型呼叫一律走 `_substack_fixture.FakeClaudeRunner`（注入為 ClaudeCli 的 runner），
`--claude-bin` 指向一個從不被執行的假可執行檔；零網路（socket 連線一律攔截並讓測試失敗）。
絕不執行真的 `claude`、絕不消耗訂閱額度、絕不讀鑰匙圈。

涵蓋 tasks.md T046 的 (1)～(13)。
"""
import datetime
import fcntl
import hashlib
import io
import json
import os
import re
import socket
import sqlite3
import stat
import struct
import sys
import unittest
import zlib
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_store  # noqa: E402

TZ8 = F.TZ8
CODE_RE = re.compile(r"確認碼：([0-9a-f]{6})")


def make_png(width=300, height=200, shade=0):
    """合成的小 PNG（短圖：010 的切片模組不會開瀏覽器，整張原檔送出）。"""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes([200 + shade % 50, 200, 200]) * width
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height, 1)) + chunk(b"IEND", b""))


def file_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def expected_code(image_ids, day):
    raw = "%s|%s" % (",".join(str(i) for i in sorted(image_ids)), day)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6]


class _NoNetwork(object):
    """任何 socket 連線都讓測試失敗（零網路的執行期證明）。"""

    def __enter__(self):
        def refuse(*a, **k):
            raise AssertionError("不得發出網路請求")
        self._patches = [mock.patch.object(socket.socket, "connect", refuse),
                         mock.patch.object(socket, "create_connection", refuse)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class Base(unittest.TestCase):
    NOW = "2026-11-26 10:00:00"

    def setUp(self):
        import substack_transcribe as T
        self.T = T
        self.data = F.temp_data_dir(self)
        self.tmp = F.temp_data_dir(self)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        F.write_config(self.data)
        self.clock = F.FakeClock(self.NOW)
        self.runner = F.FakeClaudeRunner()
        self.claude_bin = os.path.join(self.tmp, "fake-claude-never-run")
        with open(self.claude_bin, "w") as f:
            f.write("#!/bin/sh\nexit 99\n")
        os.chmod(self.claude_bin, os.stat(self.claude_bin).st_mode | stat.S_IXUSR)
        self.factory_kwargs = []
        self.env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "LANG": "C",
                    "USER": "tester", "LOGNAME": "tester",
                    "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_CHILD_SESSION": "1"}
        self.out = io.StringIO()
        self.err = io.StringIO()
        self._seq = 0

    # ---------------------------------------------------------------- 資料
    def add_article(self, author=None, completeness="F", published="2026-11-20T09:00:00+08:00",
                    n_images=2, n_downloaded=None):
        """直接插庫一篇文章與 n 張圖；前 n_downloaded 張設為 downloaded 並寫出真的 PNG。"""
        n_downloaded = n_images if n_downloaded is None else n_downloaded
        author = author or F.AUTHOR_A["key"]
        overrides = {"author_key": author, "completeness": completeness,
                     "published_at": published}
        if completeness == "N":
            overrides.update(body_text=None, classify_reason="player_only")
        elif completeness == "P":
            overrides.update(classify_reason="paywall_marker")
        store = substack_store.SubstackStore(self.data)
        try:
            article_id = store.insert_article_with_images(F.article_row(**overrides),
                                                          F.image_rows(n_images))
            image_ids = []
            for image in store.list_images(article_id)[:n_downloaded]:
                rel = os.path.join("substack_images", str(article_id), "%d.png" % image["seq"])
                os.makedirs(os.path.join(self.data, os.path.dirname(rel)), exist_ok=True)
                self._seq += 1
                with open(os.path.join(self.data, rel), "wb") as f:
                    f.write(make_png(300 + self._seq % 40, 200, shade=self._seq))
                store.set_image_downloaded(image["id"], rel, sha256="0" * 64, size_bytes=100)
                image_ids.append(image["id"])
        finally:
            store.close()
        return article_id, image_ids

    def reclassify(self, article_id, old, new):
        store = substack_store.SubstackStore(self.data)
        try:
            store.add_reclassification(article_id, "manual", old, new, "test", "r-test",
                                       derived_body_text=F.filler(300) if new != "N" else None)
        finally:
            store.close()

    @property
    def db_path(self):
        return os.path.join(self.data, substack_store.DB_FILENAME)

    def ro(self):
        conn = sqlite3.connect("file:%s?mode=ro" % self.db_path, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def trial_rows(self):
        if not os.path.exists(self.db_path):
            return []
        conn = self.ro()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM transcription_trial ORDER BY id")]
        finally:
            conn.close()

    def transcription_rows(self):
        conn = self.ro()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM image_transcription ORDER BY image_id")]
        finally:
            conn.close()

    # ---------------------------------------------------------------- 執行
    def factory(self, **kwargs):
        import claude_cli_runner
        self.factory_kwargs.append(dict(kwargs))
        return claude_cli_runner.ClaudeCli(**kwargs)

    def go(self, *args, env=None):
        self.out = io.StringIO()
        self.err = io.StringIO()
        argv = ["--data-dir", self.data] + list(args)
        if "--run" in args and "--claude-bin" not in args:
            argv += ["--claude-bin", self.claude_bin]
        with _NoNetwork():
            return self.T.run(argv, env=self.env if env is None else env, out=self.out,
                              err=self.err, clock=self.clock, runner=self.runner,
                              claude_factory=self.factory, tmp_root=self.tmp)

    def text(self):
        return self.out.getvalue() + self.err.getvalue()

    def plan_code(self, *args):
        code = self.go("--plan", *args)
        self.assertEqual(code, 0, self.text())
        m = CODE_RE.search(self.out.getvalue())
        self.assertIsNotNone(m, self.text())
        return m.group(1)

    def assert_no_marks(self, text):
        self.assertEqual(F.marks_in(text), [], text)


# ================================================================ (1) --plan
class PlanTest(Base):
    def test_plan_is_readonly_zero_calls_and_lists_numbers_only(self):
        aid, ids = self.add_article(n_images=3, n_downloaded=2)
        before = file_bytes(self.db_path)
        code = self.go("--plan")
        out = self.out.getvalue()
        self.assertEqual(code, 0, self.text())
        self.assertEqual(self.runner.calls, [], "plan 不得有任何 claude 呼叫")
        self.assertEqual(self.factory_kwargs, [], "plan 不得建立 ClaudeCli")
        self.assertEqual(file_bytes(self.db_path), before, "plan 必須唯讀")
        self.assertIn("article_id=%d" % aid, out)
        self.assertIn(F.AUTHOR_A["key"], out)
        self.assertIn("2026-11-20", out)
        self.assertIn("已下載圖=2", out)
        self.assertIn("總圖=3", out)
        self.assertIn("預估 claude -p 呼叫 4 次", out)
        m = CODE_RE.search(out)
        self.assertIsNotNone(m, out)
        self.assert_no_marks(self.text())
        self.assertEqual(self.trial_rows(), [])

    def test_plan_without_database_does_not_create_it(self):
        code = self.go("--plan")
        self.assertEqual(code, 2, self.text())
        self.assertFalse(os.path.exists(self.db_path), "庫不存在時不得建庫")
        self.assertEqual(self.runner.calls, [])


# ================================================================ (2) 選取規則（FR-023）
class SelectionTest(Base):
    def test_latest_n_per_author_and_no_relaxing(self):
        a = F.AUTHOR_A["key"]
        old, _ = self.add_article(a, published="2026-11-10T09:00:00+08:00")
        mid, _ = self.add_article(a, published="2026-11-15T09:00:00+08:00")
        new, _ = self.add_article(a, published="2026-11-20T09:00:00+08:00")
        b_preview, _ = self.add_article(F.AUTHOR_B["key"], completeness="P")
        self.go("--plan", "--per-author", "2")
        out = self.out.getvalue()
        self.assertIn("article_id=%d" % new, out)
        self.assertIn("article_id=%d" % mid, out)
        self.assertNotIn("article_id=%d " % old, out + " ")
        self.assertNotIn("article_id=%d " % b_preview, out + " ")
        self.assertIn("%s：無符合條件文章" % F.AUTHOR_B["key"], out)

    def test_default_per_author_is_one(self):
        self.add_article(published="2026-11-10T09:00:00+08:00")
        new, _ = self.add_article(published="2026-11-20T09:00:00+08:00")
        self.go("--plan")
        out = self.out.getvalue()
        self.assertEqual(re.findall(r"article_id=(\d+)", out), [str(new)])

    def test_excludes_non_f_and_articles_without_downloaded_images(self):
        self.add_article(completeness="P")
        self.add_article(completeness="N", n_images=1)
        self.add_article(n_images=2, n_downloaded=0)
        self.go("--plan", "--per-author", "3")
        out = self.out.getvalue()
        self.assertEqual(re.findall(r"article_id=(\d+)", out), [])
        self.assertIn("%s：無符合條件文章" % F.AUTHOR_A["key"], out)
        self.assertIsNone(CODE_RE.search(out), "沒有對象時不產生確認碼")

    def test_per_author_range(self):
        self.add_article()
        for bad in ("0", "4", "-1", "x"):
            self.assertEqual(self.go("--plan", "--per-author", bad), 2, bad)
        self.assertEqual(self.go("--plan", "--per-author", "3"), 0)

    def test_reclassified_p_to_f_becomes_selectable(self):
        aid, _ = self.add_article(completeness="P")
        self.go("--plan")
        self.assertNotIn("article_id=%d" % aid, self.out.getvalue())
        self.reclassify(aid, "P", "F")
        self.go("--plan")
        self.assertIn("article_id=%d" % aid, self.out.getvalue())

    def test_reclassified_f_to_p_is_excluded(self):
        aid, _ = self.add_article(completeness="F")
        self.reclassify(aid, "F", "P")
        self.go("--plan")
        self.assertNotIn("article_id=%d" % aid, self.out.getvalue())

    def test_disabled_author_is_not_selected(self):
        F.write_config(self.data, authors=[dict(F.AUTHOR_A),
                                           dict(F.AUTHOR_B, enabled=False)])
        bid, _ = self.add_article(F.AUTHOR_B["key"])
        self.go("--plan")
        self.assertNotIn("article_id=%d" % bid, self.out.getvalue())

    def test_article_ids_must_pass_same_rule(self):
        a1, _ = self.add_article(published="2026-11-18T09:00:00+08:00")
        a2, _ = self.add_article(published="2026-11-19T09:00:00+08:00")
        preview, _ = self.add_article(completeness="P")
        nodl, _ = self.add_article(n_downloaded=0)
        self.assertEqual(self.go("--plan", "--article-ids", "%d,%d" % (a1, a2)), 0, self.text())
        out = self.out.getvalue()
        self.assertIn("article_id=%d" % a1, out)
        self.assertIn("article_id=%d" % a2, out)
        for bad in (preview, nodl, 99999):
            self.assertEqual(self.go("--plan", "--article-ids", "%d,%d" % (a1, bad)), 2, bad)
            self.assertIsNone(CODE_RE.search(self.out.getvalue()))

    def test_article_ids_at_most_three_per_author(self):
        ids = [self.add_article(published="2026-11-1%dT09:00:00+08:00" % i)[0] for i in range(4)]
        self.assertEqual(self.go("--plan", "--article-ids", ",".join(map(str, ids[:3]))), 0)
        self.assertEqual(self.go("--plan", "--article-ids", ",".join(map(str, ids))), 2)

    def test_article_ids_of_disabled_author_refused(self):
        F.write_config(self.data, authors=[dict(F.AUTHOR_A),
                                           dict(F.AUTHOR_B, enabled=False)])
        bid, _ = self.add_article(F.AUTHOR_B["key"])
        self.assertEqual(self.go("--plan", "--article-ids", str(bid)), 2)

    def test_per_author_and_article_ids_are_exclusive(self):
        aid, _ = self.add_article()
        self.assertEqual(self.go("--plan", "--per-author", "1", "--article-ids", str(aid)), 2)


# ================================================================ (3)(4) 確認碼與拒絕
class ConfirmCodeTest(Base):
    def test_code_is_hash_of_sorted_image_ids_and_taipei_date(self):
        _a, ids1 = self.add_article(F.AUTHOR_A["key"])
        _b, ids2 = self.add_article(F.AUTHOR_B["key"])
        code = self.plan_code()
        self.assertEqual(code, expected_code(ids1 + ids2, "2026-11-26"))

    def test_taipei_date_is_used_even_if_clock_is_utc(self):
        _a, ids = self.add_article()
        # UTC 2026-11-26 17:00 ＝ 台北 2026-11-27 01:00
        self.clock.set_now(datetime.datetime(2026, 11, 26, 17, 0,
                                             tzinfo=datetime.timezone.utc))
        self.assertEqual(self.plan_code(), expected_code(ids, "2026-11-27"))

    def _assert_refused_without_side_effects(self, code):
        self.assertEqual(code, 2, self.text())
        self.assertEqual(self.runner.model_calls, [], "被拒絕的執行不得呼叫模型")
        self.assertEqual(self.runner.calls, [], "被拒絕的執行不得執行 claude（含 --help）")
        self.assertEqual(self.trial_rows(), [], "被拒絕的執行不寫 transcription_trial")

    def test_wrong_code_refused(self):
        self.add_article()
        code = self.plan_code()
        wrong = "000000" if code != "000000" else "111111"
        before = file_bytes(self.db_path)
        self._assert_refused_without_side_effects(self.go("--run", "--confirm", wrong))
        self.assertEqual(file_bytes(self.db_path), before)

    def test_cross_day_refused(self):
        self.add_article()
        self.clock.set_now("2026-11-26 23:59:00")
        code = self.plan_code()
        self.clock.set_now("2026-11-27 00:01:00")
        self._assert_refused_without_side_effects(self.go("--run", "--confirm", code))
        self.assertIn("跨日", self.text())

    def test_changed_selection_refused(self):
        self.add_article(published="2026-11-19T09:00:00+08:00")
        code = self.plan_code()
        self.add_article(published="2026-11-21T09:00:00+08:00")      # 較新的一篇擠掉原本的選取
        self._assert_refused_without_side_effects(self.go("--run", "--confirm", code))

    def test_run_requires_confirm(self):
        self.add_article()
        self._assert_refused_without_side_effects(self.go("--run"))

    def test_empty_selection_run_refused(self):
        self.add_article(completeness="P")
        self._assert_refused_without_side_effects(
            self.go("--run", "--confirm", expected_code([], "2026-11-26")))

    def test_matching_code_runs(self):
        self.add_article()
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        self.assertEqual(len(self.trial_rows()), 1)


# ================================================================ (5) T-D XPC_SERVICE_NAME
class XpcServiceNameTest(Base):
    def _run_with(self, value):
        self.add_article()
        code = self.plan_code()
        env = dict(self.env)
        if value is not None:
            env["XPC_SERVICE_NAME"] = value
        return self.go("--run", "--confirm", code, env=env)

    def test_manual_contexts_not_refused(self):
        for value in (None, "0", "application.com.microsoft.VSCode.1234.5678"):
            with self.subTest(value=value):
                self.runner = F.FakeClaudeRunner()
                self.assertEqual(self._run_with(value), 0, self.text())
                self.assertEqual(len(self.runner.model_calls), 4)

    def test_project_launchd_jobs_refused(self):
        for value in ("com.alphavibe.substackimport", "com.alphavibe.transcriptionpipeline"):
            with self.subTest(value=value):
                self.runner = F.FakeClaudeRunner()
                self.assertEqual(self._run_with(value), 2, self.text())
                self.assertEqual(self.runner.calls, [])
                self.assertEqual(self.trial_rows(), [])

    def test_scheduled_flag_does_not_exist(self):
        self.add_article()
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code, "--scheduled"), 2)
        self.assertEqual(self.go("--plan", "--scheduled"), 2)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.trial_rows(), [])


# ================================================================ (6) 執行鎖
class LockTest(Base):
    def test_shares_import_lock_name(self):
        import substack_import
        self.assertEqual(self.T.LOCK_NAME, substack_import.LOCK_NAME)

    def test_busy_lock_exit_3_without_record(self):
        self.add_article()
        code = self.plan_code()
        handle = open(os.path.join(self.data, self.T.LOCK_NAME), "w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.go("--run", "--confirm", code), 3, self.text())
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.trial_rows(), [])


# ================================================================ (7) 登入方式／登入失效／使用量上限
class AbortTest(Base):
    def _run(self):
        code = self.plan_code()
        return self.go("--run", "--confirm", code)

    def test_non_subscription_auth_aborts(self):
        self.add_article()
        self.runner = F.FakeClaudeRunner(auth={"loggedIn": True, "authMethod": "console",
                                               "apiProvider": "firstParty"})
        self.assertEqual(self._run(), 5, self.text())
        self.assertEqual(self.runner.model_calls, [])
        trial = self.trial_rows()[0]
        self.assertEqual(trial["result"], "aborted_auth_mode")
        self.assertEqual(trial["claude_calls"], 0)
        self.assertEqual(trial["images_attempted"], 0)

    def test_missing_required_flag_aborts_as_auth_mode(self):
        self.add_article()
        self.runner = F.FakeClaudeRunner(help_text="  --print  x\n  --model  y\n")
        self.assertEqual(self._run(), 5, self.text())
        self.assertEqual(self.runner.model_calls, [])
        self.assertEqual(self.trial_rows()[0]["result"], "aborted_auth_mode")

    def test_logged_out_aborts_login(self):
        self.add_article()
        self.runner = F.FakeClaudeRunner(auth={"loggedIn": False})
        self.assertEqual(self._run(), 5, self.text())
        self.assertEqual(self.runner.model_calls, [])
        self.assertEqual(self.trial_rows()[0]["result"], "aborted_login")

    def test_login_expired_mid_run_aborts(self):
        self.add_article(n_images=2)
        self.runner = F.FakeClaudeRunner(responses={
            "reader": [{"kind": "table", "text": F.FAKE_TABLE_TEXT}, {"kind": "login"}]})
        self.assertEqual(self._run(), 5, self.text())
        trial = self.trial_rows()[0]
        self.assertEqual(trial["result"], "aborted_login")
        self.assertEqual(trial["claude_calls"], 3)

    def test_usage_limit_stops_immediately(self):
        self.add_article(n_images=3)
        self.runner = F.FakeClaudeRunner(responses={
            "reader": [{"kind": "table", "text": F.FAKE_TABLE_TEXT}, {"kind": "limit"},
                       {"kind": "table", "text": F.FAKE_TABLE_TEXT}]})
        self.assertEqual(self._run(), 5, self.text())
        self.assertEqual(len(self.runner.model_calls), 3, "撞限後不得再呼叫")
        trial = self.trial_rows()[0]
        self.assertEqual(trial["result"], "aborted_usage_limit")
        self.assertEqual(trial["reset_hint"], "3:45pm")
        self.assertEqual(trial["claude_calls"], 3)
        self.assertEqual(trial["images_ok"], 1)
        self.assertEqual(trial["images_attempted"], 1)
        self.assertEqual(len(self.transcription_rows()), 1)


# ================================================================ (8)(9) 轉寫流程與紀錄
class FlowTest(Base):
    def test_reader_then_verifier_with_defaults(self):
        self.add_article(n_images=2)
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        calls = [(c["role"], c["model"]) for c in self.runner.model_calls]
        self.assertEqual(calls, [("reader", "sonnet"), ("verifier", "opus")] * 2)
        verifier_stdin = self.runner.model_calls[1]["stdin"]
        self.assertIn("[L001]", verifier_stdin, "驗證者必須帶 reader 結果（加行號）")
        self.assertIn("甲公司", verifier_stdin)
        self.assertNotIn("待查轉寫", self.runner.model_calls[0]["stdin"])

    def test_not_table_has_no_text_and_no_verifier(self):
        _aid, ids = self.add_article(n_images=1)
        self.runner = F.FakeClaudeRunner(responses={"reader": [{"kind": "not_table"}]})
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        self.assertEqual([c["role"] for c in self.runner.model_calls], ["reader"])
        row = self.transcription_rows()[0]
        self.assertEqual(row["image_id"], ids[0])
        self.assertEqual(row["is_table"], 0)
        self.assertIsNone(row["text"])
        trial = self.trial_rows()[0]
        self.assertEqual(trial["images_not_table"], 1)
        self.assertEqual(trial["claude_calls"], 1)

    def test_trial_and_image_rows_queryable_readonly(self):
        a1, ids1 = self.add_article(F.AUTHOR_A["key"], n_images=2)
        _b, ids2 = self.add_article(F.AUTHOR_B["key"], n_images=1)
        self.runner = F.FakeClaudeRunner(responses={
            "reader": [{"kind": "table", "text": F.FAKE_TABLE_TEXT}, {"kind": "not_table"},
                       {"kind": "table", "text": F.FAKE_TABLE_TEXT}],
            "verifier": [{"kind": "verify_ok"}, {"kind": "verify_issues"}]})
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        trial = self.trial_rows()[0]
        self.assertEqual(trial["confirm_code"], code)
        self.assertEqual(trial["articles"], 2)
        self.assertEqual(trial["images_attempted"], 3)
        self.assertEqual(trial["images_ok"], 2)
        self.assertEqual(trial["images_not_table"], 1)
        self.assertEqual(trial["images_failed"], 0)
        self.assertEqual(trial["claude_calls"], 5)
        self.assertEqual(trial["result"], "ok")
        self.assertIn("sonnet", trial["models"])
        self.assertIn("opus", trial["models"])
        self.assertTrue(trial["started_at"] and trial["finished_at"])
        rows = {r["image_id"]: r for r in self.transcription_rows()}
        self.assertEqual(sorted(rows), sorted(ids1 + ids2))
        self.assertEqual({r["trial_id"] for r in rows.values()}, {trial["id"]})
        verdicts = sorted(str(r["verdict"]) for r in rows.values())
        self.assertEqual(verdicts, ["None", "issues", "ok"])
        issues_row = [r for r in rows.values() if r["verdict"] == "issues"][0]
        self.assertEqual(json.loads(issues_row["issues_json"])[0]["kind"], "wrong-number")
        self.assertEqual(issues_row["reader_model"], "sonnet")
        self.assertEqual(issues_row["verifier_model"], "opus")
        # FR-024：直接唯讀讀庫可查到轉寫文字
        conn = sqlite3.connect("file:%s?mode=ro" % self.db_path, uri=True)
        try:
            hits = conn.execute("SELECT image_id FROM image_transcription "
                                "WHERE text LIKE ?", ("%甲公司%",)).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(hits), 2)
        self.assert_no_marks(self.text())
        self.assertNotIn("甲公司", self.text(), "stdout 只印數字與代碼，不印轉寫內容")

    def test_reader_failure_is_partial(self):
        self.add_article(n_images=2)
        self.runner = F.FakeClaudeRunner(responses={
            "reader": [{"kind": "error"}, {"kind": "table", "text": F.FAKE_TABLE_TEXT}]})
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 1, self.text())
        trial = self.trial_rows()[0]
        self.assertEqual(trial["result"], "partial")
        self.assertEqual(trial["images_failed"], 1)
        self.assertEqual(trial["images_ok"], 1)
        self.assertEqual(trial["claude_calls"], 3)

    def test_missing_image_file_counts_as_failed(self):
        aid, ids = self.add_article(n_images=2)
        os.remove(os.path.join(self.data, "substack_images", str(aid), "1.png"))
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 1, self.text())
        trial = self.trial_rows()[0]
        self.assertEqual(trial["images_failed"], 1)
        self.assertEqual(trial["claude_calls"], 2)

    def test_same_model_for_reader_and_verifier_refused(self):
        self.add_article()
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code, "--reader1-model", "opus",
                                 "--verifier-model", "opus"), 2)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.trial_rows(), [])


# ================================================================ (10) --report
class ReportTest(Base):
    def test_report_readonly(self):
        self.add_article(n_images=2)
        code = self.plan_code()
        self.go("--run", "--confirm", code)
        trial_id = self.trial_rows()[0]["id"]
        before = file_bytes(self.db_path)
        calls_before = len(self.runner.calls)
        self.assertEqual(self.go("--report"), 0, self.text())
        out = self.out.getvalue()
        self.assertIn("trial#%d" % trial_id, out)
        self.assertIn("claude 呼叫=4", out)
        self.assertIn("結果=ok", out)
        self.assertEqual(self.go("--report", "--trial-id", str(trial_id)), 0, self.text())
        self.assertIn("image_id=", self.out.getvalue())
        self.assertNotIn("甲公司", self.text())
        self.assertEqual(file_bytes(self.db_path), before)
        self.assertEqual(len(self.runner.calls), calls_before)
        self.assertEqual(self.go("--report", "--trial-id", "999"), 2)

    def test_report_without_database_does_not_create_it(self):
        self.assertEqual(self.go("--report"), 2)
        self.assertFalse(os.path.exists(self.db_path))


# ================================================================ (11)～(13) 安全與參數傳遞
class SafetyTest(Base):
    def test_no_enable_option(self):
        self.assertEqual(self.go("--enable"), 2)
        self.assertEqual(self.go("--plan", "--enable"), 2)

    def test_claude_cli_built_without_token_and_no_keychain(self):
        import keychain_secrets   # 已被 010 模組在頂層間接載入；這裡只確認從未被呼叫
        self.add_article()
        code = self.plan_code()
        called = []
        with mock.patch.object(keychain_secrets, "get_secret",
                               lambda *a, **k: called.append(a)):
            self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        self.assertEqual(called, [], "不得讀鑰匙圈")
        self.assertEqual(len(self.factory_kwargs), 1)
        self.assertIsNone(self.factory_kwargs[0].get("token_getter"), "token_getter 必須是 None")
        for call in self.runner.calls:
            argv = call["args"][0]
            self.assertEqual(argv[0], self.claude_bin, "只執行 --claude-bin 指定的程式")
            self.assertNotIn("security", [os.path.basename(a) for a in argv])
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", call["args"][2])

    def test_child_env_whitelisted(self):
        self.add_article(n_images=1)
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code), 0, self.text())
        for call in self.runner.model_calls:
            env = call["env"]
            self.assertEqual(env.get("USER"), "tester")
            self.assertEqual(env.get("LOGNAME"), "tester")
            self.assertEqual([k for k in env if k.startswith("CLAUDE_CODE_")], [])

    def test_model_bin_timeout_passed_through(self):
        self.add_article(n_images=1)
        code = self.plan_code()
        self.assertEqual(self.go("--run", "--confirm", code, "--reader1-model", "haiku",
                                 "--verifier-model", "sonnet", "--timeout-sec", "120"),
                         0, self.text())
        kw = self.factory_kwargs[0]
        self.assertEqual(kw["claude_bin"], self.claude_bin)
        self.assertEqual(kw["timeout_sec"], 120)
        self.assertEqual([c["model"] for c in self.runner.model_calls], ["haiku", "sonnet"])
        self.assertEqual({c["timeout"] for c in self.runner.model_calls}, {120})
        self.assertEqual({c["args"][0][0] for c in self.runner.calls}, {self.claude_bin})
        self.assertIn("haiku", self.trial_rows()[0]["models"])

    def test_relative_or_missing_claude_bin_refused_without_record(self):
        self.add_article()
        code = self.plan_code()
        for bad in ("claude", os.path.join(self.tmp, "nope")):
            self.assertEqual(self.go("--run", "--confirm", code, "--claude-bin", bad), 2)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.trial_rows(), [])

    def test_production_data_dir_refused_first(self):
        import article_data_guard
        argv = ["--data-dir", article_data_guard.PRODUCTION_DATA_DIR, "--plan"]
        out, err = io.StringIO(), io.StringIO()
        code = self.T.run(argv, env={"PATH": "/usr/bin"}, out=out, err=err, clock=self.clock,
                          runner=self.runner, claude_factory=self.factory, tmp_root=self.tmp)
        self.assertEqual(code, 2)
        self.assertEqual(self.runner.calls, [])


if __name__ == "__main__":
    unittest.main()
