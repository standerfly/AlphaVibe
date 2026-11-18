"""010 Phase 14：轉寫流水線測試。全用 tempfile、假的 claude 可執行檔（stub）與假 paddle；零網路、零真實 claude、零鑰匙圈。"""
import datetime
import fcntl
import glob
import json
import os
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import _pipeline_fixture as F  # noqa: E402
import article_data_guard  # noqa: E402
import article_store as A  # noqa: E402
import article_tools  # noqa: E402
import check_scheduled_jobs as checker  # noqa: E402
import claude_cli_runner as CR  # noqa: E402
import investanchors_import  # noqa: E402
import keychain_secrets  # noqa: E402
import pipeline_compare as PC  # noqa: E402
import transcription_pipeline as T  # noqa: E402

PLIST = os.path.join(HERE, "..", "..", "..", "ops", "launchd", "com.alphavibe.transcriptionpipeline.plist")
TOKEN = "tok-FAKE-9f8e7d6c5b4a39281706"
TB = F.TABLE_A
VOK = {"kind": "verify", "so": {"verdict": "ok"}}


def vissues(*items):
    return {"kind": "verify", "so": {"verdict": "issues", "issues": list(items)}}


def _read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def paddle_ok(paths):
    return {p: {"status": "transcribed", "text": F.TABLE_A_PADDLE} for p in paths}


# ====================================================================== 硬性防呆（claude_cli_runner）
class GuardTest(unittest.TestCase):
    def test_argv_has_no_billing_flags_and_fixed_safe_shape(self):
        argv = CR.build_argv("/x/claude", "sonnet", "/tmp/w", ["--permission-prompts", "none"])
        for bad in CR.FORBIDDEN_FLAGS:
            self.assertNotIn(bad, argv)
        self.assertNotIn("--bare", argv)
        self.assertNotIn("--max-budget-usd", argv)
        self.assertNotIn("--max-turns", argv)
        for need in ("-p", "--model", "--output-format", "--json-schema", "--no-session-persistence", "--permission-mode",
                     "--tools", "--allowedTools", "--disallowedTools", "--add-dir", "--system-prompt"):
            self.assertIn(need, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "Read(//tmp/w/**)")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--add-dir") + 1], "/tmp/w")
        for tool in ("Bash", "Edit", "Write", "WebFetch", "WebSearch"):
            self.assertIn(tool, argv[argv.index("--disallowedTools") + 1].split())
        # 提示詞走 stdin，不在命令列
        self.assertNotIn("請用 Read 工具", " ".join(argv))

    def test_assert_argv_safe_rejects_each_forbidden_flag_and_bad_model(self):
        for bad in CR.FORBIDDEN_FLAGS:
            with self.assertRaises(CR.ClaudeCliError):
                CR.assert_argv_safe(["claude", "-p", bad])
        with self.assertRaises(CR.ClaudeCliError):
            CR.assert_argv_safe(["claude", "--model", "claude-opus-4-1"])
        with self.assertRaises(CR.ClaudeCliError):
            CR.assert_argv_safe(["claude", "--max-budget-usd=5"])
        self.assertEqual(CR.assert_argv_safe(["claude", "--model", "opus"]), ["claude", "--model", "opus"])

    def test_env_is_whitelist_and_strips_billing_variables(self):
        base = {"PATH": "/bin", "HOME": "/h", "LANG": "C", "ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_AUTH_TOKEN": "t",
                "ANTHROPIC_BASE_URL": "http://x", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1",
                "AWS_ACCESS_KEY_ID": "a", "HTTPS_PROXY": "p", "FOO": "bar"}
        env = CR.build_env(None, base)
        self.assertEqual(set(env), {"PATH", "HOME", "LANG"})
        env2 = CR.build_env(TOKEN, base)
        self.assertEqual(set(env2), {"PATH", "HOME", "LANG", "CLAUDE_CODE_OAUTH_TOKEN"})

    def test_assert_env_safe_rejects_billing_and_unknown_variables(self):
        for k in CR.BILLING_ENV_NAMES + ("ANTHROPIC_FOO", "CLAUDE_CODE_USE_MANTLE", "RANDOM_VAR"):
            with self.assertRaises(CR.ClaudeCliError):
                CR.assert_env_safe({"PATH": "/bin", k: "1"})

    def test_module_never_uses_api_path(self):
        src = _read(CR.__file__)
        self.assertNotIn("api.anthropic.com", src)
        self.assertNotIn("urllib", src)
        self.assertFalse(hasattr(CR, "urlopen"))
        # 只引用 article_transcribe 的常數文字，不帶進任何 API 呼叫函式
        import article_transcribe
        for name in dir(CR):
            obj = getattr(CR, name)
            if callable(obj) and getattr(obj, "__module__", None) == "article_transcribe":
                self.fail("引用了 article_transcribe 的函式：%s" % name)
        psrc = _read(T.__file__)
        self.assertNotIn("api.anthropic.com", psrc)
        self.assertNotIn("urlopen", psrc)
        self.assertNotIn("transcribe_tiles(", psrc)
        self.assertNotIn("article_transcribe.", psrc)

    def test_validate_bin_requires_absolute_executable(self):
        with self.assertRaises(CR.ClaudeCliError):
            CR.validate_bin("claude")
        with self.assertRaises(CR.ClaudeCliError):
            CR.validate_bin("/no/such/claude")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c")
            with open(p, "w") as f:
                f.write("x")
            with self.assertRaises(CR.ClaudeCliError):           # 存在但不可執行
                CR.validate_bin(p)

    def test_timeout_clamped(self):
        self.assertEqual(CR.clamp_timeout(1), CR.MIN_TIMEOUT_SEC)
        self.assertEqual(CR.clamp_timeout(10 ** 6), CR.MAX_TIMEOUT_SEC)

    def test_plan_flags_missing_required_and_degrade_optional(self):
        missing, args, degraded = CR.plan_flags(F.HELP_BASE)
        self.assertEqual(missing, [])
        self.assertEqual(args, [])
        self.assertEqual(len(degraded), len(CR.OPTIONAL_FLAGS))
        missing, args, _ = CR.plan_flags(F.HELP_BASE + F.HELP_OPTIONAL)
        self.assertEqual(args, ["--permission-prompts", "none"])
        missing, _a, _d = CR.plan_flags(F.HELP_BASE.replace("--json-schema", "--json-schemaX"))
        self.assertEqual(missing, ["--json-schema"])
        _m, args, _d = CR.plan_flags(F.HELP_BASE + "  --restricted  x\n", use_restricted=True)
        self.assertIn("--restricted", args)
        missing, _a, _d = CR.plan_flags(F.HELP_BASE, use_restricted=True)
        self.assertEqual(missing, ["--restricted"])

    def test_all_safety_flags_are_required_with_no_drop_backdoor(self):
        for f in ("--setting-sources", "--strict-mcp-config", "--disable-slash-commands", "--system-prompt",
                  "--no-session-persistence", "--permission-mode", "--tools", "--allowedTools", "--disallowedTools",
                  "--json-schema", "--output-format"):
            self.assertIn(f, CR.REQUIRED_FLAGS)
            missing, _a, _d = CR.plan_flags(F.HELP_BASE.replace(f + " ", f + "X ").replace(f + ",", f + "X,"))
            self.assertIn(f, missing, f)
        import inspect
        self.assertNotIn("drop", inspect.signature(CR.plan_flags).parameters)
        self.assertNotIn("drop_flags", inspect.signature(CR.ClaudeCli.__init__).parameters)
        self.assertNotIn("--drop-flag", _read(T.__file__).replace("--drop-flag", "--drop-flag", 0).split("def parse_args")[1].split("def _validate_args")[0])

    def test_argv_always_has_setting_sources_empty_strict_mcp_and_no_slash_commands(self):
        argv = CR.build_argv("/x/claude", "sonnet", "/tmp/w", [])
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)

    def test_allowed_tools_is_path_scoped_by_default_and_unrestricted_only_by_explicit_flag(self):
        with tempfile.TemporaryDirectory() as d:
            argv = CR.build_argv("/x/claude", "sonnet", d, [])
            rule = argv[argv.index("--allowedTools") + 1]
            self.assertEqual(rule, "Read(/%s/**)" % os.path.realpath(d))
            self.assertTrue(rule.startswith("Read(//"))
            self.assertNotEqual(rule, "Read")
            argv2 = CR.build_argv("/x/claude", "sonnet", d, [], unrestricted_read=True)
            self.assertEqual(argv2[argv2.index("--allowedTools") + 1], "Read")
        self.assertFalse(T.parse_args(["--data-dir", "x"]).unrestricted_read)

    def test_env_whitelist_is_minimal(self):
        self.assertEqual(set(CR.ENV_ALLOW), {"PATH", "HOME", "LANG"})


class ClassifyFailureTest(unittest.TestCase):
    def obj(self, text, **kw):
        d = {"type": "result", "is_error": True, "result": text}
        d.update(kw)
        return d

    def test_usage_limit_samples(self):
        for text in ("You've hit your session limit · resets 3:45pm", "You've hit your weekly limit · resets Nov 21, 9am",
                     "Claude usage limit reached.", "rate_limit_error", "5-hour limit reached", "Too many requests"):
            kind, _h = CR.classify_failure(1, "", "", self.obj(text))
            self.assertEqual(kind, "usage_limit", text)
        kind, hint = CR.classify_failure(1, "", "Claude usage limit reached. Your limit will reset at 3:45pm")
        self.assertEqual(kind, "usage_limit")

    def test_reset_hint_extracted_and_sanitized(self):
        _k, hint = CR.classify_failure(1, "", "", self.obj("You've hit your session limit · resets 3:45pm"))
        self.assertEqual(hint, "3:45pm")
        _k, hint = CR.classify_failure(1, "", "", self.obj("hit your limit resets <script>3pm</script>"))
        self.assertNotIn("<", hint or "")

    def test_login_samples(self):
        for text in ("OAuth token has expired. Expired — log in again", "Not logged in · Please run /login",
                     "authentication_error: invalid", "401 Unauthorized"):
            kind, _h = CR.classify_failure(1, "", "", self.obj(text))
            self.assertEqual(kind, "login", text)

    def test_other_failure(self):
        self.assertEqual(CR.classify_failure(1, "", "boom", self.obj("some failure"))[0], "other")
        self.assertEqual(CR.classify_failure(2, "garbage", "")[0], "other")

    def test_structured_output_validation(self):
        self.assertEqual(CR.validate_structured({"is_table": True, "text": "| a |\r\n| 1 |"}), (True, "| a |\n| 1 |"))
        self.assertEqual(CR.validate_structured({"is_table": False, "text": "caption"}), (False, ""))
        for bad in (None, {}, {"is_table": True}, {"is_table": "yes", "text": "x"}, {"is_table": True, "text": ""},
                    {"is_table": True, "text": "a\x00b"}, {"is_table": True, "text": "| a |", "extra": 1},
                    {"is_table": True, "text": "token sk-ant-api03-abcdefghijklmnop12345"}, {"is_table": True, "text": 5}):
            self.assertIsNone(CR.validate_structured(bad), bad)


# ====================================================================== 數字家族與驗證條目（pipeline_compare）
class NumericFamilyTest(unittest.TestCase):
    SHA = "a" * 64

    def test_ok_when_ocr_covers_numbers(self):
        self.assertEqual(PC.numeric_family(self.SHA, TB, F.TABLE_A_PADDLE)["category"], "ok")

    def test_issues_on_number_mismatch_without_content(self):
        r = PC.numeric_family(self.SHA, TB, F.TABLE_A_PADDLE.replace("5678", "5687"))
        self.assertEqual(r["category"], "issues")
        for i in r["issues"]:
            self.assertNotIn("5678", json.dumps(i, ensure_ascii=False))
            PC.V._check_issue(i, "t")

    def test_inconclusive_when_ocr_missing_numbers(self):
        r = PC.numeric_family(self.SHA, TB, "| 項目 | 營收 |\n| --- | --- |\n| 甲公司 | 1234 |")
        self.assertNotEqual(r["category"], "ok")

    def test_unavailable_when_no_ocr(self):
        r = PC.numeric_family(self.SHA, TB, None, "paddle_timeout")
        self.assertEqual((r["category"], r["reason"]), ("unavailable", "paddle_timeout"))

    def test_verification_payload_binds_transcription_hash(self):
        p = PC.verification_payload("pipeline-paddle", "compare-d-c", 7, self.SHA, TB, "ok", [])
        self.assertEqual(p["results"][0]["transcription_sha256"], A.transcription_sha256(TB))
        self.assertEqual((p["version"], p["method"], p["verifier"]), (1, "compare-d-c", "pipeline-paddle"))
        self.assertNotIn("issues", p["results"][0])
        iss = [{"where": "第 1 列", "found": "x", "kind": "other"}]
        self.assertEqual(PC.verification_payload("v", "agent-spot-check", 7, self.SHA, TB, "issues", iss)["results"][0]["issues"], iss)

    def test_normalize_text(self):
        self.assertEqual(PC.normalize_text("\r\n a  \r\nb \n\n"), " a\nb")


class VerifierRunnerTest(unittest.TestCase):
    def test_verify_argv_uses_verify_schema_and_prompt_but_same_safe_shape(self):
        argv = CR.build_argv("/x/claude", "opus", "/tmp/w", [], verify=True)
        self.assertIn("verdict", argv[argv.index("--json-schema") + 1])
        self.assertNotIn("is_table", argv[argv.index("--json-schema") + 1])
        self.assertNotIn("--append-system-prompt", argv)
        sp = argv[argv.index("--system-prompt") + 1]
        self.assertLess(len(sp), 200)                               # 短提示詞：只放角色與輸出格式
        self.assertNotIn("source-typo", sp)
        up = CR.build_user_prompt(["image.png"], False, "x")        # 規則放在使用者訊息
        for needle in ("source-typo", "逐字比對", "不是來重新轉寫", "[L012]", "反例"):
            self.assertIn(needle, up)
        for bad in CR.FORBIDDEN_FLAGS:
            self.assertNotIn(bad, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read")

    def test_user_prompt_has_numbered_transcript_only_in_verify_mode(self):
        v = CR.build_user_prompt(["image.png"], False, "a\nb")
        self.assertIn("[L001] a", v)
        self.assertIn("[L002] b", v)
        t = CR.build_user_prompt(["image.png"], False)
        self.assertNotIn("[L001]", t)

    def test_validate_verdict(self):
        self.assertEqual(CR.validate_verdict({"verdict": "ok"}), ("ok", []))
        good = {"verdict": "issues", "issues": [{"where": "第 3 列第 2 欄", "found": "9,87", "kind": "wrong-number"}]}
        self.assertEqual(CR.validate_verdict(good)[0], "issues")
        for bad in (None, {}, {"verdict": "maybe"}, {"verdict": "ok", "issues": [{"where": "a", "found": "b", "kind": "other"}]},
                    {"verdict": "issues"}, {"verdict": "issues", "issues": []},
                    {"verdict": "issues", "issues": [{"where": "a", "found": "b", "kind": "nope"}]},
                    {"verdict": "issues", "issues": [{"where": "a" * 100, "found": "b", "kind": "other"}]},
                    {"verdict": "issues", "issues": [{"where": "a", "found": "x\ny", "kind": "other"}]},
                    {"verdict": "ok", "extra": 1}):
            self.assertIsNone(CR.validate_verdict(bad), bad)


# ====================================================================== 流水線端到端（stub claude）
class PBase(unittest.TestCase):
    N = 3

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pipe-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.imgs = F.build_data_dir(self.data, self.N)
        self.stub = F.Stub(self.tmp)
        self.stub.respond("sonnet", {"kind": "ok", "text": TB})
        self.stub.respond("opus", VOK)
        self.out = []
        self.notices = []
        self.token = None
        self.paddle = paddle_ok
        for name, val in (("MAX_RUNS_PER_DAY", 50), ("MAX_IMAGES_PER_DAY", 50)):     # 預設值另有測試；這裡放寬避免多次執行被每日上限擋下
            p = mock.patch.object(T, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.set_setting("pipeline_enabled", "1")

    # ---- helpers
    def store(self):
        return A.ArticleStore(self.data)

    def set_setting(self, k, v):
        s = self.store()
        s.set_setting(k, v)
        s.close()

    def deps(self, **kw):
        d = {"paddle_batch": self.paddle, "notify_fn": self.notices.append, "token_getter": lambda: self.token}
        d.update(kw)
        return d

    def run_pipe(self, *extra, **depkw):
        return T.run(["--data-dir", self.data, "--claude-bin", self.stub.path] + list(extra), say=self.out.append,
                     deps=self.deps(**depkw), env={})

    def text(self):
        return "\n".join(self.out)

    def rows(self):
        s = self.store()
        try:
            return [dict(r) for r in s.conn.execute("SELECT * FROM article_image ORDER BY seq")]
        finally:
            s.close()

    def ver(self):
        s = self.store()
        try:
            return {r["image_id"]: dict(r) for r in s.conn.execute("SELECT * FROM transcription_verification")}
        finally:
            s.close()

    def model_calls(self):
        return [c for c in self.stub.calls()]

    def last_run(self):
        s = self.store()
        try:
            return s.recent_pipeline_runs(1)[0]
        finally:
            s.close()


class HappyPathTest(PBase):
    def test_transcribe_then_verify_then_numeric_gives_cross_checked(self):
        rc = self.run_pipe()
        self.assertEqual(rc, 0, self.text())
        rows = self.rows()
        self.assertEqual([r["transcription_status"] for r in rows], ["done"] * 3)
        self.assertEqual({r["transcribed_model"] for r in rows}, {"claude-cli:sonnet"})
        self.assertTrue(all(r["transcription"] == TB for r in rows))
        v = self.ver()
        self.assertEqual({x["status"] for x in v.values()}, {"cross_checked"})
        for x in v.values():
            self.assertEqual(x["checks_passed"], "numeric,text")
            self.assertEqual(set(x["method"].split(",")), {"agent-spot-check", "compare-d-c"})
            self.assertEqual(set(x["verifier"].split(",")), {"pipeline-verifier-opus", "pipeline-paddle"})
        self.assertEqual(self.notices, [])
        run = self.last_run()
        self.assertEqual((run["result"], run["images_attempted"], run["cross_checked"], run["flagged"]), ("ok", 3, 3, 0))

    def test_verification_bound_to_transcription_hash(self):
        # 驗證條目套用時會核對 transcription_sha256：轉寫在驗證後被改寫 → 驗證列被重置（既有規則）
        self.run_pipe("--max-images", "1")
        s = self.store()
        s.set_transcription(900, 1, "done", text=TB + "\n| 新 | 1 |", model="manual:x", is_table=True)
        self.assertIsNone(s.get_verification(self.imgs[0][0]))
        s.close()

    def test_cross_checked_enters_search_and_display_label(self):
        self.run_pipe("--max-images", "1")
        s = A.ArticleStore.open_readonly(self.data)
        try:
            hits = s.search_articles("甲公司")
            img = [i for i in s.list_images(900) if i["seq"] == 1][0]
        finally:
            s.close()
        self.assertTrue(hits)
        self.assertIn("Claude 自動轉寫", article_tools.transcription_source(img["transcribed_model"]))
        self.assertIn("sonnet", article_tools.transcription_label(img["transcribed_model"]))

    def test_idempotent_second_run_processes_only_remaining(self):
        self.run_pipe("--max-images", "2")
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["done", "done", "untranscribed"])
        self.assertEqual(len(self.stub.calls()), 4)                # 2 張 × （轉寫＋驗證）
        self.run_pipe("--max-images", "2")
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["done"] * 3)
        self.assertEqual(len(self.stub.calls()), 6)
        self.run_pipe()
        self.assertEqual(len(self.stub.calls()), 6)                # 沒有待處理的圖 → 不呼叫 claude
        self.assertIn("沒有待處理", self.text())

    def test_reader_and_verifier_are_separate_fresh_calls_with_different_models(self):
        self.run_pipe("--max-images", "1")
        calls = self.stub.calls()
        self.assertEqual([c["model"] for c in calls], ["sonnet", "opus"])
        self.assertNotEqual(calls[0]["cwd"], "")
        # reader-1 的提示詞不含任何轉寫內容；驗證者看得到行號待查轉寫（不盲讀）
        for needle in ("甲公司", "1,234", "[L001]"):
            self.assertNotIn(needle, calls[0]["stdin"])
        self.assertIn("[L001] | 項目 | 營收 | 毛利率 |", calls[1]["stdin"])
        self.assertIn("甲公司", calls[1]["stdin"])
        self.assertNotIn("甲公司", " ".join(calls[1]["args"]))
        self.assertIn("verdict", calls[1]["args"][calls[1]["args"].index("--json-schema") + 1])
        self.assertIn("is_table", calls[0]["args"][calls[0]["args"].index("--json-schema") + 1])
        self.assertIn("source-typo", calls[1]["stdin"])
        self.assertNotIn("source-typo", calls[1]["args"][calls[1]["args"].index("--system-prompt") + 1])
        self.assertIn("逐字比對", calls[1]["stdin"])
        self.assertIn("轉寫", calls[0]["stdin"])
        self.assertEqual(calls[0]["args"][calls[0]["args"].index("--setting-sources") + 1], "")   # 空字串（Mac 實測）
        self.assertIn("--strict-mcp-config", calls[0]["args"])
        self.assertNotIn("--mcp-config", calls[0]["args"])
        self.assertTrue(all("--resume" not in c["args"] and "--continue" not in c["args"] for c in calls))

    def test_same_model_for_reader_and_verifier_refused(self):
        rc = self.run_pipe("--reader1-model", "opus", "--verifier-model", "opus")
        self.assertEqual(rc, 2)
        self.assertEqual(self.stub.calls(), [])

    def test_cwd_is_clean_workdir_and_add_dir_only_that(self):
        self.run_pipe("--max-images", "1")
        c = self.stub.calls()[0]
        self.assertEqual(c["files"], ["image.png"])
        self.assertEqual(c["args"][c["args"].index("--add-dir") + 1], c["cwd"])
        self.assertNotIn(self.data, c["cwd"])
        self.assertFalse(os.path.exists(c["cwd"]))                 # 跑完已清除
        self.assertNotIn("ANTHROPIC_API_KEY", c["env_keys"])

    def test_env_whitelist_applies_even_when_parent_has_api_keys(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-api03-xxxxxxxxxxxxxxxxxxxx",
                                          "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_USE_BEDROCK": "1",
                                          "AWS_SECRET_ACCESS_KEY": "s"}):
            self.run_pipe("--max-images", "1")
        for c in self.stub.calls():
            bad = [k for k in c["env_keys"] if k.startswith("ANTHROPIC_") or k.startswith("CLAUDE_CODE_USE_") or k.startswith("AWS_")]
            self.assertEqual(bad, [])
            self.assertTrue(set(c["env_keys"]) <= set(CR.ENV_ALLOW) | {"CLAUDE_CODE_OAUTH_TOKEN", "LC_CTYPE"} | {"PWD", "SHLVL", "_", "OLDPWD", "LC_ALL"})

    def test_actual_argv_has_no_bare_or_budget_flags(self):
        self.run_pipe("--max-images", "1")
        for c in self.stub.calls():
            for bad in ("--bare", "--max-budget-usd", "--max-turns"):
                self.assertNotIn(bad, c["args"])
            self.assertIn(c["args"][c["args"].index("--model") + 1], CR.MODEL_ALIASES)

    def test_max_images_default_and_hard_cap(self):
        self.assertEqual(self.run_pipe("--max-images", "6"), 2)
        self.assertEqual(self.stub.calls(), [])
        self.assertEqual(self.run_pipe("--max-images", "0"), 2)

class VerdictMatrixTest(PBase):
    N = 1

    def test_verifier_issues_flagged_and_notified_with_count_only(self):
        self.stub.respond("opus", vissues({"where": "第 3 列第 2 欄", "found": "9,87", "expected": "98,7", "kind": "wrong-number"}))
        rc = self.run_pipe()
        self.assertEqual(rc, 0)
        x = list(self.ver().values())[0]
        self.assertEqual((x["status"], x["verifier"], x["method"]), ("flagged", "pipeline-verifier-opus", "agent-spot-check"))
        self.assertIn("第 3 列第 2 欄", x["flagged_cells"])
        self.assertEqual(self.notices, ["📋 定錨轉寫：1 張圖需核對"])
        for forbidden in ("測試文章", "甲公司", "image.png", self.data, "9,87"):
            self.assertNotIn(forbidden, self.notices[0])
            self.assertNotIn(forbidden, self.text())
        self.assertIn("需核對 image_id：", self.text())
        s = A.ArticleStore.open_readonly(self.data)
        try:
            self.assertEqual(s.search_articles("乙公司"), [])      # flagged 不進搜尋
        finally:
            s.close()

    def test_source_typo_only_counts_as_ok_with_typo_record(self):
        self.stub.respond("opus", vissues({"where": "第 2 列第 1 欄", "found": "名稱與代碼對調", "kind": "source-typo"}))
        self.run_pipe()
        x = list(self.ver().values())[0]
        self.assertEqual(x["status"], "cross_checked")
        self.assertTrue(x["source_typos"])
        self.assertEqual(self.notices, [])

    def test_verifier_issues_mixed_with_source_typo_still_flagged(self):
        self.stub.respond("opus", vissues({"where": "a", "found": "b", "kind": "source-typo"},
                                          {"where": "c", "found": "d", "kind": "truncated"}))
        self.run_pipe()
        self.assertEqual(list(self.ver().values())[0]["status"], "flagged")

    def test_paddle_missing_leaves_unverified_with_text_family_only(self):
        rc = self.run_pipe("--no-paddle")
        self.assertEqual(rc, 0)
        x = list(self.ver().values())[0]
        self.assertEqual((x["status"], x["checks_passed"]), ("unverified", "text"))
        self.assertEqual(self.notices, [])
        self.assertEqual(self.rows()[0]["transcription_status"], "done")

    def test_paddle_unavailable_exception_does_not_block_text_family(self):
        def boom(paths):
            raise T.PaddleUnavailable("paddle_timeout")
        self.run_pipe(paddle_batch=boom)
        x = list(self.ver().values())[0]
        self.assertEqual((x["status"], x["checks_passed"]), ("unverified", "text"))

    def test_paddle_generic_exception_contained(self):
        def boom(paths):
            raise RuntimeError("secret detail")
        self.run_pipe(paddle_batch=boom)
        self.assertEqual(list(self.ver().values())[0]["status"], "unverified")
        self.assertNotIn("secret detail", self.text())

    def test_paddle_number_mismatch_flags(self):
        bad = lambda paths: {p: {"status": "transcribed", "text": F.TABLE_A_PADDLE.replace("5678", "5687")} for p in paths}  # noqa: E731
        self.run_pipe(paddle_batch=bad)
        x = list(self.ver().values())[0]
        self.assertEqual(x["status"], "flagged")
        self.assertIn("compare-d-c", x["method"])
        self.assertEqual(self.notices, ["📋 定錨轉寫：1 張圖需核對"])

    def test_paddle_inconclusive_stays_unverified_text_only(self):
        weak = lambda paths: {p: {"status": "transcribed", "text": "| 項目 | 營收 |\n| --- | --- |\n| 甲公司 | 1234 |"} for p in paths}  # noqa: E731
        self.run_pipe(paddle_batch=weak)
        x = list(self.ver().values())[0]
        self.assertIn(x["status"], ("unverified", "flagged"))
        if x["status"] == "unverified":
            self.assertEqual(x["checks_passed"], "text")

    def test_paddle_failed_status_counts_as_unavailable(self):
        fail = lambda paths: {p: {"status": "untranscribed", "text": ""} for p in paths}  # noqa: E731
        self.run_pipe(paddle_batch=fail)
        x = list(self.ver().values())[0]
        self.assertEqual((x["status"], x["checks_passed"]), ("unverified", "text"))

    def test_not_table_written_without_verifier_call(self):
        self.stub.respond("sonnet", {"kind": "ok", "is_table": False, "text": ""})
        self.assertEqual(self.run_pipe(), 0)
        r = self.rows()[0]
        self.assertEqual((r["transcription_status"], r["transcription"], r["transcribed_model"]), ("not_table", None, None))
        self.assertEqual(self.ver(), {})
        self.assertEqual([c["model"] for c in self.stub.calls()], ["sonnet"])

    def test_paddle_not_run_when_verifier_already_flags(self):
        calls = []

        def spy(paths):
            calls.append(paths)
            return paddle_ok(paths)
        self.stub.respond("opus", vissues({"where": "a", "found": "b", "kind": "other"}))
        self.run_pipe(paddle_batch=spy)
        self.assertEqual(calls, [])

class FailureHandlingTest(PBase):
    N = 2

    def run_fast(self, *extra, **kw):
        return self.run_pipe(*extra, runner=lambda argv, inp, env, cwd, t: CR.default_runner(
            argv, inp, env, cwd, 1.5 if "--model" in argv else t), **kw)

    def test_timeout_kills_child_marks_retryable_and_continues(self):
        self.stub.respond("sonnet", {"kind": "sleep", "sec": 30}, {"kind": "ok", "text": TB})
        t0 = time.time()
        rc = self.run_fast()
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(rc, 1)
        rows = self.rows()
        self.assertEqual((rows[0]["transcription_status"], rows[0]["transcribe_attempts"]), ("untranscribed", 1))
        self.assertEqual(rows[1]["transcription_status"], "done")
        self.assertIn("timeout", self.text())

    def test_bad_json_and_missing_structured_output_not_written(self):
        self.stub.respond("sonnet", {"kind": "badjson"}, {"kind": "no_structured"})
        rc = self.run_pipe()
        self.assertEqual(rc, 1)
        rows = self.rows()
        self.assertEqual([r["transcription_status"] for r in rows], ["untranscribed", "untranscribed"])
        self.assertEqual([r["transcribe_attempts"] for r in rows], [1, 1])
        self.assertEqual(self.ver(), {})
        # 失敗不得有部分結果：reader-2 根本沒被呼叫
        self.assertEqual([c["model"] for c in self.stub.calls()], ["sonnet", "sonnet"])

    def test_generic_error_exit_counts_attempt(self):
        self.stub.respond("sonnet", {"kind": "error"})
        self.run_pipe("--max-images", "1")
        self.assertEqual(self.rows()[0]["transcription_status"], "untranscribed")
        self.assertEqual(self.rows()[0]["transcribe_attempts"], 1)

    def test_verifier_failure_keeps_unverified_transcription_and_retries_verify_only(self):
        self.stub.respond("opus", {"kind": "badjson"}, VOK)
        rc = self.run_pipe("--max-images", "1")
        self.assertEqual(rc, 1)
        r = self.rows()[0]
        self.assertEqual(r["transcription_status"], "done")
        self.assertEqual(self.ver(), {})
        self.assertEqual([c["model"] for c in self.stub.calls()], ["sonnet", "opus"])
        # 下次：先補驗證（不再呼叫 reader-1 轉寫同一張）
        self.stub.cfg["responses"]["sonnet"] = [{"kind": "ok", "text": TB}]
        self.stub.save()
        self.run_pipe("--max-images", "1")
        models = [c["model"] for c in self.stub.calls()]
        self.assertEqual(models, ["sonnet", "opus", "opus"])
        self.assertEqual(list(self.ver().values())[0]["status"], "cross_checked")

    def test_verify_failures_capped(self):
        self.stub.respond("opus", {"kind": "error"})
        for _ in range(A.ArticleStore.MAX_PIPELINE_VERIFY_FAILURES):
            s = self.store()
            s.conn.execute("DELETE FROM pipeline_run")
            s.conn.commit()
            s.close()
            self.run_pipe("--max-images", "1")
        n = len(self.stub.calls())
        s = self.store()
        self.assertEqual(s.pipeline_images_to_verify(10), [])
        s.close()
        self.assertEqual(self.rows()[0]["transcription_status"], "done")
        self.assertGreaterEqual(n, 1)

    def test_manual_or_api_transcriptions_are_never_picked_for_verification(self):
        s = self.store()
        s.set_transcription(900, 2, "done", text=TB, model="manual:cline", is_table=True)
        s.close()
        s = self.store()
        ids = [i["seq"] for i in s.pipeline_images_to_verify(10)]
        s.close()
        self.assertEqual(ids, [])

    def test_worker_that_modifies_workdir_is_rejected(self):
        self.stub.respond("sonnet", {"kind": "write_in_workdir", "text": TB})
        rc = self.run_pipe("--max-images", "1")
        self.assertEqual(rc, 1)
        self.assertEqual(self.rows()[0]["transcription_status"], "untranscribed")
        self.assertIn("workdir_modified", self.text())

    def test_images_at_attempt_limit_are_not_selected(self):
        s = self.store()
        for _ in range(A.MAX_TRANSCRIBE_ATTEMPTS):
            s.bump_transcribe_attempts(900, 1)
        s.close()
        self.run_pipe()
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["untranscribed", "done"])

    def test_abandoned_article_and_missing_file_skipped(self):
        s = self.store()
        s.conn.execute("UPDATE article SET status='abandoned'")
        s.conn.commit()
        s.close()
        self.run_pipe()
        self.assertEqual(self.stub.calls(), [])
        self.assertEqual(self.last_run()["result"], "noop")

    def test_missing_image_file_skipped(self):
        os.remove(self.imgs[0][2])
        self.run_pipe()
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["untranscribed", "done"])

    def test_secret_like_text_rejected(self):
        self.stub.respond("sonnet", {"kind": "ok", "text": "| a |\n| --- |\n| sk-ant-api03-abcdefghijklmnopqrstuvwx |"})
        self.run_pipe("--max-images", "1")
        self.assertEqual(self.rows()[0]["transcription_status"], "untranscribed")


class UsageLimitTest(PBase):
    N = 4

    def test_limit_stops_whole_run_keeps_rest_untouched_then_resumes(self):
        self.stub.respond("sonnet", {"kind": "ok", "text": TB}, {"kind": "limit"}, {"kind": "ok", "text": TB})
        rc = self.run_pipe("--max-images", "4")
        self.assertEqual(rc, 4)
        rows = self.rows()
        self.assertEqual([r["transcription_status"] for r in rows], ["done", "untranscribed", "untranscribed", "untranscribed"])
        self.assertEqual([r["transcribe_attempts"] for r in rows], [0, 0, 0, 0])        # 撞限不計失敗次數
        self.assertEqual([c["model"] for c in self.stub.calls()], ["sonnet", "opus", "sonnet"])   # 撞限後不再多呼叫
        run = self.last_run()
        self.assertEqual((run["result"], run["reset_hint"], run["images_attempted"]), ("aborted_usage_limit", "3:45pm", 1))
        self.assertIn("下次排程續做", self.text())
        dbg = glob.glob(os.path.join(self.data, "articles_probe", "pipeline-debug-*.txt"))
        self.assertEqual(len(dbg), 1)
        with open(dbg[0], encoding="utf-8") as f:
            dbg_text = f.read()
        self.assertNotIn("甲公司", dbg_text)
        self.assertIn("3:45pm", dbg_text)
        # 下次排程續做：不重做已完成的第 1 張
        self.stub.respond("sonnet", {"kind": "ok", "text": TB})
        self.stub.reset_counters()
        rc = self.run_pipe("--max-images", "4")
        self.assertEqual(rc, 0)
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["done"] * 4)
        self.assertEqual(self.stub.calls()[0]["model"], "sonnet")

    def test_limit_on_verifier_keeps_transcription_unverified_and_resumes_verification(self):
        self.stub.respond("opus", {"kind": "limit"})
        rc = self.run_pipe()
        self.assertEqual(rc, 4)
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["done", "untranscribed", "untranscribed", "untranscribed"])
        self.assertEqual([r["transcribe_attempts"] for r in self.rows()], [0] * 4)
        self.assertEqual(self.ver(), {})
        self.assertEqual(len(self.stub.calls()), 2)
        s = self.store()
        self.assertEqual(s.pipeline_verify_failures(self.imgs[0][0]), 0)      # 撞限不計驗證失敗次數
        self.assertEqual(len(s.pipeline_images_to_verify(10)), 1)
        s.close()
        self.stub.respond("opus", VOK)
        self.stub.reset_counters()
        rc = self.run_pipe("--max-images", "4")
        self.assertEqual(rc, 0)
        self.assertEqual([r["transcription_status"] for r in self.rows()], ["done"] * 4)
        self.assertEqual({x["status"] for x in self.ver().values()}, {"cross_checked"})
        # 第一次續做先補驗證那一張（opus 先於 sonnet），不重新轉寫它
        self.assertEqual(self.stub.calls()[2]["model"], "opus")

    def test_weekly_and_plain_stderr_limit_messages(self):
        for kind in ("weekly", "limit_plain"):
            self.stub.reset_counters()
            self.stub.respond("sonnet", {"kind": kind})
            self.out.clear()
            self.assertEqual(self.run_pipe("--max-images", "1"), 4, kind)
            self.assertEqual(self.last_run()["result"], "aborted_usage_limit")
        self.assertEqual(self.rows()[0]["transcribe_attempts"], 0)

    def test_login_expired_aborts_without_retry(self):
        self.stub.respond("sonnet", {"kind": "login"})
        rc = self.run_pipe()
        self.assertEqual(rc, 4)
        self.assertEqual(self.last_run()["result"], "aborted_login")
        self.assertEqual(len(self.stub.calls()), 1)
        self.assertEqual([r["transcribe_attempts"] for r in self.rows()], [0] * 4)

    def test_auth_status_not_logged_in_aborts_before_any_model_call(self):
        self.stub.cfg["auth"] = json.dumps({"loggedIn": False})
        self.stub.save()
        self.assertEqual(self.run_pipe(), 4)
        self.assertEqual(self.stub.calls(), [])
        self.assertEqual(self.last_run()["result"], "aborted_login")

    def test_auth_status_api_key_mode_aborts_before_any_model_call(self):
        for method in ("api_key", "Anthropic Console", "bedrock", "vertex"):
            self.stub.cfg["auth"] = json.dumps({"loggedIn": True, "authMethod": method})
            self.stub.save()
            s = self.store()
            s.conn.execute("DELETE FROM pipeline_run")        # 每次重來，避免被每日執行次數上限擋下
            s.conn.commit()
            s.close()
            self.assertEqual(self.run_pipe(), 4, method)
            self.assertEqual(self.last_run()["result"], "aborted_auth_mode")
        self.assertEqual(self.stub.calls(), [])

    def test_missing_required_flag_aborts(self):
        self.stub.cfg["help"] = F.HELP_BASE.replace("--json-schema", "--other")
        self.stub.save()
        self.assertEqual(self.run_pipe(), 4)
        self.assertEqual(self.last_run()["result"], "aborted_flags")
        self.assertEqual(self.stub.calls(), [])

    def test_optional_flags_degrade_with_notice(self):
        s = F.Stub(os.path.join(self.tmp, "s2"), optional=False)
        s.respond("sonnet", {"kind": "ok", "text": TB})
        s.respond("opus", VOK)
        rc = T.run(["--data-dir", self.data, "--claude-bin", s.path, "--max-images", "1"], say=self.out.append,
                   deps=self.deps(), env={})
        self.assertEqual(rc, 0)
        self.assertIn("降級的選用旗標", self.text())
        self.assertNotIn("--permission-prompts", s.calls()[0]["args"])

    def test_daily_run_and_image_caps(self):
        for _ in range(T.MAX_RUNS_PER_DAY):
            s = self.store()
            s.finish_pipeline_run(s.start_pipeline_run("cron"), "noop", {})
            s.close()
        self.assertEqual(self.run_pipe(), 0)
        self.assertIn("達每日上限", self.text())
        self.assertEqual(self.stub.calls(), [])

    def test_daily_image_cap_limits_batch(self):
        s = self.store()
        rid = s.start_pipeline_run("cron")
        s.finish_pipeline_run(rid, "ok", {"images_attempted": T.MAX_IMAGES_PER_DAY - 1})
        s.close()
        self.run_pipe("--max-images", "5")
        self.assertEqual(len([c for c in self.stub.calls() if c["model"] == "sonnet"]), 1)


class SafetyGatesTest(PBase):
    N = 1

    def test_production_data_dir_requires_flag_first(self):
        prod = article_data_guard.PRODUCTION_DATA_DIR
        before = sorted(os.listdir(prod)) if os.path.isdir(prod) else None
        rc = T.run(["--data-dir", article_data_guard.PRODUCTION_DATA_DIR, "--dry-run"], say=self.out.append,
                   deps=self.deps(), env={})
        self.assertEqual(rc, 2)
        self.assertIn("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", self.text())
        self.assertEqual(sorted(os.listdir(prod)) if os.path.isdir(prod) else None, before)   # 沒碰、沒建庫
        self.assertFalse(os.path.exists(os.path.join(prod, "articles.db")))
        self.assertEqual(self.stub.calls(), [])

    def test_data_dir_required(self):
        self.assertEqual(T.run([], say=self.out.append, deps=self.deps(), env={}), 2)

    def test_missing_db_not_created(self):
        d = os.path.join(self.tmp, "empty")
        os.makedirs(d)
        rc = T.run(["--data-dir", d, "--claude-bin", self.stub.path], say=self.out.append, deps=self.deps(), env={})
        self.assertEqual(rc, 2)
        self.assertEqual(os.listdir(d), [])

    def test_disabled_by_default_refuses_without_calling_anything(self):
        self.set_setting("pipeline_enabled", "0")
        self.assertEqual(self.run_pipe(), 3)
        self.assertIn("尚未啟用", self.text())
        self.assertEqual(self.stub.calls(), [])

    def test_refuses_when_api_transcribe_switch_is_on(self):
        self.set_setting("transcribe_enabled", "1")
        self.assertEqual(self.run_pipe(), 3)
        self.assertEqual(self.stub.calls(), [])

    def test_lock_prevents_concurrent_runs(self):
        lock = open(os.path.join(self.data, T.LOCK_NAME), "w")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.run_pipe(), 0)
        self.assertIn("另一個流水線行程", self.text())
        self.assertEqual(self.stub.calls(), [])

    def test_claude_bin_must_be_absolute_executable(self):
        rc = T.run(["--data-dir", self.data, "--claude-bin", "claude"], say=self.out.append, deps=self.deps(), env={})
        self.assertEqual(rc, 2)

    def test_mutually_exclusive_actions(self):
        self.assertEqual(self.run_pipe("--dry-run", "--enable"), 2)
        self.assertEqual(self.run_pipe("--enable", "--disable"), 2)

    def test_drop_flag_backdoor_does_not_exist(self):
        self.assertEqual(self.run_pipe("--drop-flag=--setting-sources"), 2)
        self.assertEqual(self.stub.calls(), [])

    def test_default_claude_bin_and_paddle_python_constants(self):
        a = T.parse_args(["--data-dir", "x"])
        self.assertEqual(a.claude_bin, "/Users/stander/.local/bin/claude")
        self.assertEqual(a.paddle_python, os.path.expanduser("~/.venvs/paddle/bin/python"))
        self.assertEqual((a.max_images, a.reader1_model, a.verifier_model), (3, "sonnet", "opus"))


class RequiredFlagsAbortTest(PBase):
    N = 1

    def test_missing_any_required_flag_aborts_with_zero_model_calls(self):
        for f in ("--setting-sources", "--strict-mcp-config", "--disable-slash-commands", "--system-prompt",
                  "--no-session-persistence", "--permission-mode", "--tools", "--allowedTools", "--disallowedTools",
                  "--json-schema", "--output-format"):
            self.stub.cfg["help"] = F.HELP_BASE.replace(f + " ", f + "X ").replace(f + ",", f + "X,") + F.HELP_OPTIONAL
            self.stub.save()
            s = self.store()
            s.conn.execute("DELETE FROM pipeline_run")
            s.conn.commit()
            s.close()
            self.assertEqual(self.run_pipe(), 4, f)
            self.assertEqual(self.last_run()["result"], "aborted_flags", f)
        self.assertEqual([c for c in self.stub.calls()], [])          # 連 --help 以外都沒有（stub 只記模型呼叫）
        self.assertEqual(self.rows()[0]["transcription_status"], "untranscribed")


class AuthWhitelistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stub = F.Stub(self.tmp)

    def auth(self, payload, rc=0):
        self.stub.cfg["auth"] = payload if isinstance(payload, str) else json.dumps(payload)
        self.stub.cfg["auth_rc"] = rc
        self.stub.save()
        return CR.ClaudeCli(self.stub.path).check_auth(self.tmp)

    def test_only_explicit_subscription_passes(self):
        good = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}
        self.assertEqual(self.auth(good), "ok")
        self.assertEqual(self.auth(dict(good, apiKeySource="none")), "ok")

    def test_bypass_cases_all_abort(self):
        good = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}
        cases = [
            {k: v for k, v in good.items() if k != "authMethod"},                      # 缺 authMethod
            dict(good, authMethod="oauth_token_x"),                                      # 未知值
            dict(good, authMethod="Anthropic API"),
            {k: v for k, v in good.items() if k != "apiProvider"},                      # 缺 apiProvider
            dict(good, apiProvider="bedrock"), dict(good, apiProvider="vertex"), dict(good, apiProvider="foundry"),
            dict(good, apiKeySource="ANTHROPIC_API_KEY"),                                # apiKeySource 存在
            dict(good, apiKeySource="apiKeyHelper"),
            {k: v for k, v in good.items() if k != "loggedIn"},                         # 缺 loggedIn
            dict(good, loggedIn="yes"),
            ["not", "a", "dict"],
        ]
        for c in cases:
            self.assertEqual(self.auth(c), "auth_mode", c)
        self.assertEqual(self.auth("authMethod: claude.ai\nloggedIn: true"), "auth_mode")       # 非 JSON 一律拒絕
        self.assertEqual(self.auth(good, rc=1), "auth_mode")                                      # 退出碼非 0

    def test_logged_out_is_login(self):
        self.assertEqual(self.auth({"loggedIn": False}), "login")


class FalsePositiveGuardTest(PBase):
    """D2：成功回應的內容（即使含 401／31%／limit／resets）不得被誤判；除錯檔不含轉寫文字。"""
    N = 1
    NASTY = ("| 項目 | 數值 |\n| --- | --- |\n| 401 | 31% |\n| usage limit reached | resets 3:45pm |\n"
             "| You've hit your weekly limit | log in again 401 Unauthorized |")

    def test_legit_table_with_trigger_words_is_not_misclassified(self):
        self.stub.respond("sonnet", {"kind": "ok", "text": self.NASTY})
        self.stub.respond("opus", VOK)
        rc = self.run_pipe("--no-paddle")
        self.assertEqual(rc, 0, self.text())
        self.assertEqual(self.rows()[0]["transcription"], self.NASTY)
        self.assertEqual(self.last_run()["result"], "ok")
        self.assertEqual(glob.glob(os.path.join(self.data, "articles_probe", "pipeline-debug-*")), [])

    def test_verifier_issue_text_with_trigger_words_is_not_misclassified(self):
        self.stub.respond("opus", vissues({"where": "第 3 列", "found": "401 limit resets 3pm", "kind": "other"}))
        self.assertEqual(self.run_pipe("--no-paddle"), 0)
        self.assertEqual(list(self.ver().values())[0]["status"], "flagged")

    def test_success_without_structured_output_is_not_scanned(self):
        # rc 0、非 is_error、subtype success、result 含觸發字：只是 no_structured，不是撞限
        self.stub.respond("sonnet", {"kind": "no_structured_trigger"})
        rc = self.run_pipe()
        self.assertEqual(rc, 1)
        self.assertEqual(self.last_run()["result"], "ok")
        self.assertEqual(self.rows()[0]["transcribe_attempts"], 1)
        self.assertIn("no_structured_output", self.text())

    def test_classify_only_on_failure_signal(self):
        ok = {"type": "result", "subtype": "success", "is_error": False, "result": "You've hit your session limit resets 3pm 401"}
        self.assertEqual(CR.classify_failure(0, "", "", ok)[0], "other")
        self.assertEqual(CR.classify_failure(1, "", "", ok)[0], "usage_limit")                        # rc 非 0
        self.assertEqual(CR.classify_failure(0, "", "", dict(ok, is_error=True))[0], "usage_limit")  # is_error
        self.assertEqual(CR.classify_failure(0, "", "", dict(ok, subtype="error_during_execution"))[0], "usage_limit")
        self.assertEqual(CR.classify_failure(0, "", "Claude usage limit reached", ok)[0], "usage_limit")   # stderr 命中
        self.assertEqual(CR.classify_failure(0, "401 limit", "", None)[0], "other")                   # 成功的原始 stdout 不掃

    def test_debug_file_has_no_response_text(self):
        self.stub.respond("sonnet", {"kind": "limit_with_content"})
        self.assertEqual(self.run_pipe(), 4)
        files = glob.glob(os.path.join(self.data, "articles_probe", "pipeline-debug-*.txt"))
        self.assertEqual(len(files), 1)
        text = _read(files[0])
        for forbidden in ("甲公司", "SECRETTABLECONTENT", "hit your", "session limit"):
            self.assertNotIn(forbidden, text)
        for needed in ("rc=1", "subtype=error", "fields=", "reset_hint=3:45pm"):
            self.assertIn(needed, text)

    def test_debug_text_drops_stderr_that_echoes_result(self):
        obj = {"result": "SECRETTABLECONTENT line one two three", "subtype": "error", "duration_ms": 12, "is_error": True}
        t = CR.debug_text(1, obj, "boom SECRETTABLECONTENT line one two three", [])
        self.assertNotIn("SECRETTABLECONTENT", t)
        self.assertIn("duration_ms=12", t)
        self.assertIn("fields=", t)


class DefaultsTest(unittest.TestCase):
    def test_conservative_daily_defaults(self):
        self.assertEqual((T.DEFAULT_MAX_IMAGES, T.MAX_RUNS_PER_DAY, T.MAX_IMAGES_PER_DAY), (3, 2, 6))
        self.assertEqual(T.HARD_MAX_IMAGES, 5)

    def test_optional_flag_values_match_mac_verified_combo(self):
        _m, args, _d = CR.plan_flags(F.HELP_BASE + F.HELP_OPTIONAL)
        self.assertEqual(args[args.index("--permission-prompts") + 1], "none")
        full = CR.build_argv("/x/claude", "sonnet", "/w", args)
        self.assertEqual(full[full.index("--setting-sources") + 1], "")
        self.assertIn("--disable-slash-commands", full)
        self.assertNotIn("--effort", full)


class DryRunTest(PBase):
    def test_dry_run_has_zero_side_effects_and_calls_nothing(self):
        db = os.path.join(self.data, "articles.db")
        before = _read(db, "rb")
        boom = mock.Mock(side_effect=AssertionError("外部程式不得被呼叫"))
        with mock.patch("subprocess.Popen", boom), mock.patch.object(keychain_secrets, "_default_runner", boom), \
                mock.patch("subprocess.run", boom):
            rc = T.run(["--data-dir", self.data, "--dry-run"], say=self.out.append,
                       deps={"paddle_batch": boom, "notify_fn": boom}, env={})
        self.assertEqual(rc, 0)
        self.assertEqual(_read(db, "rb"), before)
        self.assertEqual(self.stub.calls(), [])
        self.assertFalse(os.path.exists(os.path.join(self.data, T.LOCK_NAME)))
        t = self.text()
        self.assertIn("[dry-run]", t)
        self.assertIn("將處理 3 張", t)
        self.assertIn("claude -p --model sonnet", t)
        self.assertIn("--model opus", t)
        self.assertIn("完整命令列", t)
        self.assertIn("--disallowedTools", t)
        self.assertIn("--no-session-persistence", t)
        self.assertIn("驗證者", t)
        self.assertIn("待 Mac 實測確認的假設（%d 項）" % len(T.MAC_ASSUMPTIONS), t)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", t)
        self.assertNotIn("--bare", t.replace("不含", ""))
        self.assertNotIn(TOKEN, t)
        self.assertNotIn("測試文章", t)
        boom.assert_not_called()

    def test_dry_run_steps_are_numbered_consecutively_and_scoped_read_rule_shown(self):
        s = self.store()
        s.set_transcription(900, 1, "done", text=TB, model="claude-cli:sonnet", is_table=True)
        s.close()
        T.run(["--data-dir", self.data, "--dry-run"], say=self.out.append, deps=self.deps(), env={})
        t = self.text()
        self.assertIn("①（已轉寫，只補驗證）；②驗證者", t)
        self.assertIn("①reader-1", t)
        self.assertNotIn("③驗證者", t.split("\n")[1])
        self.assertIn("Read(//", t)
        self.assertNotIn("--drop-flag", t)

    def test_dry_run_works_when_disabled_and_reports_state(self):
        self.set_setting("pipeline_enabled", "0")
        self.assertEqual(T.run(["--data-dir", self.data, "--dry-run"], say=self.out.append, deps=self.deps(), env={}), 0)
        self.assertIn("pipeline_enabled＝關", self.text())

    def test_dry_run_respects_max_images(self):
        T.run(["--data-dir", self.data, "--dry-run", "--max-images", "2"], say=self.out.append, deps=self.deps(), env={})
        self.assertIn("將處理 2 張", self.text())

    def test_dry_run_does_not_create_pipeline_run_row(self):
        T.run(["--data-dir", self.data, "--dry-run"], say=self.out.append, deps=self.deps(), env={})
        s = self.store()
        self.assertEqual(s.recent_pipeline_runs(), [])
        s.close()

    def test_dry_run_on_old_db_without_pipeline_table_does_not_create_it(self):
        s = self.store()
        s.conn.execute("DROP TABLE pipeline_run")
        s.conn.commit()
        s.close()
        before = _read(os.path.join(self.data, "articles.db"), "rb")
        T.run(["--data-dir", self.data, "--dry-run"], say=self.out.append, deps=self.deps(), env={})
        self.assertEqual(_read(os.path.join(self.data, "articles.db"), "rb"), before)


class EnableDisableTest(PBase):
    def test_enable_then_disable(self):
        self.set_setting("pipeline_enabled", "0")
        self.assertEqual(self.run_pipe("--enable"), 0)
        s = self.store()
        self.assertEqual(s.get_setting("pipeline_enabled"), "1")
        s.close()
        self.assertEqual(self.run_pipe("--disable"), 0)
        s = self.store()
        self.assertEqual(s.get_setting("pipeline_enabled"), "0")
        s.close()
        self.assertEqual(self.stub.calls(), [])

    def test_enable_refused_while_api_transcribe_switch_on(self):
        self.set_setting("pipeline_enabled", "0")
        self.set_setting("transcribe_enabled", "1")
        self.assertEqual(self.run_pipe("--enable"), 3)
        s = self.store()
        self.assertEqual(s.get_setting("pipeline_enabled"), "0")
        s.close()

class AtomicityTest(PBase):
    N = 1

    def test_pipeline_write_with_bad_entry_rolls_back_transcription(self):
        iid = self.imgs[0][0]
        s = self.store()
        bad = {"image_id": iid, "verdict": "ok", "method": "agent-spot-check", "verifier": "t", "note": None, "cells": None,
               "transcription_sha256": "0" * 64}
        with self.assertRaises(A.TranscriptionChanged):
            s.apply_pipeline_image(900, 1, "done", TB, "claude-cli:sonnet", True, [bad], audit_kind=T.AUDIT_KIND, audit_key="x")
        self.assertEqual(s.get_image_by_id(iid)["transcription_status"], "untranscribed")
        self.assertIsNone(s.get_verification(iid))
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM alert_log WHERE kind=?", (T.AUDIT_KIND,)).fetchone()[0], 0)
        s.close()

    def test_pipeline_write_with_good_entries_is_single_transaction(self):
        iid = self.imgs[0][0]
        s = self.store()
        e = {"image_id": iid, "verdict": "ok", "method": "agent-spot-check", "verifier": "t", "note": None, "cells": None,
             "transcription_sha256": A.transcription_sha256(TB)}
        r = s.apply_pipeline_image(900, 1, "done", TB, "claude-cli:sonnet", True, [e])
        self.assertEqual(r["partial"], [iid])
        s.close()

    def test_failed_verification_write_leaves_transcription_unverified(self):
        with mock.patch.object(T.V, "apply_verification", side_effect=sqlite3.OperationalError("locked")):
            rc = self.run_pipe()
        self.assertEqual(rc, 1)
        self.assertEqual(self.rows()[0]["transcription_status"], "done")
        self.assertEqual(self.ver(), {})
        s = self.store()
        self.assertEqual(s.pipeline_verify_failures(self.imgs[0][0]), 1)
        s.close()

    def test_audit_row_has_only_models_and_step(self):
        self.run_pipe()
        s = self.store()
        keys = [r[0] for r in s.conn.execute("SELECT key FROM alert_log WHERE kind=?", (T.AUDIT_KIND,))]
        s.close()
        self.assertEqual(len(keys), 1)
        self.assertIn("transcribed", keys[0])
        self.assertNotIn("甲公司", keys[0])

class TokenTest(PBase):
    N = 1

    def test_token_goes_only_through_env_and_never_leaks(self):
        self.token = TOKEN
        self.stub.cfg["token"] = TOKEN
        self.stub.save()
        self.run_pipe()
        calls = self.stub.calls()
        self.assertTrue(all(c["token_in_env"] for c in calls))
        self.assertFalse(any(c["token_in_args"] or TOKEN in json.dumps(c) for c in calls))
        self.assertNotIn(TOKEN, self.text())

    def test_no_token_means_default_login_without_env_var(self):
        self.run_pipe()
        self.assertTrue(all("CLAUDE_CODE_OAUTH_TOKEN" not in c["env_keys"] for c in self.stub.calls()))

    def test_token_in_claude_error_output_is_masked_everywhere(self):
        self.token = TOKEN
        self.stub.cfg["token"] = TOKEN
        self.stub.save()
        self.stub.respond("sonnet", {"kind": "limit_token"})
        rc = self.run_pipe()
        self.assertEqual(rc, 4)
        self.assertNotIn(TOKEN, self.text())
        files = glob.glob(os.path.join(self.data, "articles_probe", "*"))
        self.assertTrue(files)
        for p in files:
            self.assertNotIn(TOKEN, _read(p))
        s = self.store()
        dump = "\n".join(s.conn.iterdump())
        s.close()
        self.assertNotIn(TOKEN, dump)

    def test_token_in_other_failures_not_in_output_or_db(self):
        self.token = TOKEN
        self.stub.cfg["token"] = TOKEN
        self.stub.save()
        self.stub.respond("sonnet", {"kind": "echo_token"})
        self.run_pipe()
        s = self.store()
        dump = "\n".join(s.conn.iterdump())
        s.close()
        self.assertNotIn(TOKEN, dump)
        self.assertNotIn(TOKEN, self.text())

    def test_injected_getter_means_keychain_never_touched(self):
        boom = mock.Mock(side_effect=AssertionError("鑰匙圈不得被讀"))
        with mock.patch.object(keychain_secrets, "_default_runner", boom):
            self.run_pipe()
        boom.assert_not_called()

    def test_default_getter_only_reads_named_item_without_dump_flags(self):
        calls = []

        class P(object):
            returncode, stdout = 44, ""

        def fake(args):
            calls.append(list(args))
            return P()
        with mock.patch.object(keychain_secrets, "_default_runner", fake):
            cli = CR.ClaudeCli(self.stub.path, token_getter=T._default_token_getter)
            self.assertIsNone(cli.token())
        self.assertEqual(calls, [["security", "find-generic-password", "-s", "stnd-investanchors", "-a",
                                  "claude-oauth-token", "-w"]])
        self.assertFalse(any("dump-keychain" in " ".join(c) or "-g" in c for c in calls))

    def test_getter_exception_falls_back_to_default_login_without_leaking(self):
        def bad():
            raise RuntimeError(TOKEN)
        self.run_pipe(token_getter=bad)
        self.assertNotIn(TOKEN, self.text())
        self.assertTrue(all("CLAUDE_CODE_OAUTH_TOKEN" not in c["env_keys"] for c in self.stub.calls()))


class LongImageTest(PBase):
    N = 0

    def test_long_image_is_tiled_into_workdir_and_prompt_mentions_overlap(self):
        s = self.store()
        s.add_image(900, 1, "https://img.example/x.png")
        rel = os.path.join("article_images", "900", "long.png")
        os.makedirs(os.path.join(self.data, "article_images", "900"), exist_ok=True)
        import test_article_image_tiles as TT
        with open(os.path.join(self.data, rel), "wb") as f:
            f.write(TT.make_table_png(1000, 2600))
        s.set_image_file(900, 1, rel)
        s.close()

        def fake(cfg):
            if cfg["mode"] == "bands":
                return [{"type": "bands", "width": 1000, "height": 2600, "bands": TT.blank_bands(2600)}]
            out = []
            for i, (top, bottom) in enumerate(cfg["cuts"], 1):
                tp = os.path.join(cfg["out_dir"], "tile_%02d.png" % i)
                with open(tp, "wb") as f:
                    f.write(TT.make_table_png(1000, bottom - top))
                out.append({"type": "tile", "index": i, "path": tp, "width": 1000, "height": bottom - top})
            return out
        rc = self.run_pipe(tiles_runner=fake)
        self.assertEqual(rc, 0, self.text())
        c = self.stub.calls()[0]
        self.assertGreater(len(c["files"]), 1)
        self.assertTrue(all(n.startswith("tile-") for n in c["files"]))
        self.assertIn("切片", c["stdin"])
        self.assertIn(c["files"][0], c["stdin"])

    def test_tiler_unavailable_skips_without_counting_attempt(self):
        s = self.store()
        s.add_image(900, 1, "https://img.example/x.png")
        rel = os.path.join("article_images", "900", "long.png")
        os.makedirs(os.path.join(self.data, "article_images", "900"), exist_ok=True)
        import test_article_image_tiles as TT
        with open(os.path.join(self.data, rel), "wb") as f:
            f.write(TT.make_table_png(1000, 2600))
        s.set_image_file(900, 1, rel)
        s.close()

        def broken(cfg):
            raise T.article_image_tiles.TilerError("no browser")
        self.run_pipe(tiles_runner=broken)
        self.assertEqual(self.rows()[0]["transcribe_attempts"], 0)
        self.assertEqual(self.stub.calls(), [])
        self.assertIn("略過", self.text())


class OutputHygieneTest(PBase):
    def test_stdout_has_no_title_body_path_or_token(self):
        self.token = TOKEN
        self.stub.respond("opus", {"kind": "ok", "text": TB.replace("5,678", "5,687")})
        self.run_pipe()
        t = self.text()
        for bad in ("測試文章", "測試內文", self.data, "article_images", "甲公司", TOKEN, ".png"):
            self.assertNotIn(bad, t)


class LegacyDbTest(unittest.TestCase):
    def test_readonly_open_of_db_without_pipeline_table(self):
        with tempfile.TemporaryDirectory() as d:
            F.build_data_dir(d, 1)
            s = A.ArticleStore(d)
            s.conn.execute("DROP TABLE pipeline_run")
            s.conn.commit()
            s.close()
            ro = A.ArticleStore.open_readonly(d)
            try:
                self.assertEqual(ro.recent_pipeline_runs(), [])
                self.assertEqual(ro.pipeline_usage_today(), (0, 0))
                self.assertEqual(ro.pipeline_pending_counts(), {"pending": 1, "exhausted": 0, "to_verify": 0})
            finally:
                ro.close()


# ====================================================================== 健檢與 plist
NOW = datetime.datetime(2026, 11, 20, 12, 0, 0)


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        F.build_data_dir(self.tmp, 2)

    def store(self):
        return A.ArticleStore(self.tmp)

    def add_run(self, result, hours_ago=1, reset=None, attempted=0):
        s = A.ArticleStore(self.tmp, now=lambda: NOW.replace(tzinfo=A.TZ8) - datetime.timedelta(hours=hours_ago))
        rid = s.start_pipeline_run("cron")
        s.finish_pipeline_run(rid, result, {"images_attempted": attempted}, reset)
        s.close()

    def enable(self):
        s = self.store()
        s.set_setting("pipeline_enabled", "1")
        s.close()

    def findings(self):
        with mock.patch.object(checker, "_now", lambda: NOW):
            return checker.check_transcription_pipeline(self.tmp)

    def sev(self):
        return [f[0] for f in self.findings()]

    def test_registered_in_checks(self):
        self.assertIn("transcription_pipeline", [c[0] for c in checker.CHECKS])

    def test_no_db_is_ok_and_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(checker.check_transcription_pipeline(d)[0][0], "ok")
            self.assertEqual(os.listdir(d), [])

    def test_disabled_summary_with_counts_only(self):
        f = self.findings()
        self.assertEqual([x[0] for x in f], ["ok"])
        self.assertIn("未啟用", f[0][2])
        self.assertIn("待轉寫 2 張", f[0][2])
        self.assertNotIn("測試文章", f[0][2])

    def test_enabled_without_any_run_warns_when_pending(self):
        self.enable()
        self.assertIn("warning", self.sev())

    def test_stale_run_warns_only_with_pending(self):
        self.enable()
        self.add_run("ok", hours_ago=24 * 4)
        self.assertIn("warning", self.sev())
        self.add_run("ok", hours_ago=2)
        self.assertNotIn("warning", self.sev())

    def test_stale_but_nothing_pending_is_ok(self):
        self.enable()
        self.add_run("ok", hours_ago=24 * 5)
        s = self.store()
        s.conn.execute("UPDATE article_image SET transcription_status='not_table'")
        s.conn.commit()
        s.close()
        self.assertNotIn("warning", self.sev())

    def test_usage_limit_streak_warns_with_reset_time(self):
        self.enable()
        for h in (6, 5, 4):
            self.add_run("aborted_usage_limit", hours_ago=h, reset="3:45pm")
        f = self.findings()
        w = [x for x in f if x[0] == "warning"]
        self.assertTrue(w)
        self.assertIn("3:45pm", w[0][2])
        self.assertIn("連續 3 次", w[0][2])

    def test_single_usage_limit_is_not_a_warning(self):
        self.enable()
        self.add_run("aborted_usage_limit", hours_ago=2, reset="3:45pm")
        self.assertNotIn("warning", self.sev())

    def test_streak_broken_by_success(self):
        self.enable()
        self.add_run("aborted_usage_limit", hours_ago=9)
        self.add_run("ok", hours_ago=8)
        self.add_run("aborted_usage_limit", hours_ago=7)
        self.add_run("aborted_usage_limit", hours_ago=6)
        self.assertNotIn("warning", self.sev())

    def test_login_expired_warns_and_api_mode_is_critical(self):
        self.enable()
        self.add_run("aborted_login", hours_ago=1)
        self.assertIn("warning", self.sev())
        self.add_run("aborted_auth_mode", hours_ago=0.5)
        self.assertIn("critical", self.sev())

    def test_summary_includes_flagged_count_and_last_result_only_numbers(self):
        self.enable()
        self.add_run("ok", hours_ago=2, attempted=2)
        s = self.store()
        rid = s.conn.execute("SELECT id FROM article_image LIMIT 1").fetchone()[0]
        s.conn.execute("UPDATE article_image SET transcription_status='done', transcription='x' WHERE id=?", (rid,))
        s.apply_verification_batch([{"image_id": rid, "verdict": "issues", "method": "compare-d-c", "verifier": "t",
                                     "note": "n", "cells": None, "transcription_sha256": A.transcription_sha256("x")}])
        s.close()
        text = self.findings()[-1][2]
        self.assertIn("有疑慮待 PO 核對 1 張", text)
        self.assertIn("結果 ok", text)

    def test_summary_counts_not_table_and_text_only(self):
        self.enable()
        s = self.store()
        ids = [r[0] for r in s.conn.execute("SELECT id FROM article_image ORDER BY seq")]
        s.conn.execute("UPDATE article_image SET transcription_status='not_table' WHERE id=?", (ids[0],))
        s.conn.execute("UPDATE article_image SET transcription_status='done', transcription='x', transcribed_model='claude-cli:sonnet' WHERE id=?", (ids[1],))
        s.apply_verification_batch([{"image_id": ids[1], "verdict": "ok", "method": "agent-spot-check", "verifier": "t", "note": None,
                                     "cells": None, "transcription_sha256": A.transcription_sha256("x")}])
        s.close()
        text = self.findings()[-1][2]
        self.assertIn("僅通過文字家族（數字家族缺漏）1 張", text)
        self.assertIn("非表格累計 1 張", text)

    def test_run_all_includes_pipeline_without_breaking(self):
        with mock.patch.object(checker, "_now", lambda: NOW):
            findings = checker.run_all(self.tmp)
        self.assertIn("transcription_pipeline", [f[1] for f in findings])


class PlistTest(unittest.TestCase):
    def setUp(self):
        with open(PLIST, "rb") as f:
            self.p = plistlib.load(f)
        self.raw = _read(PLIST)

    def test_label_and_program(self):
        self.assertEqual(self.p["Label"], "com.alphavibe.transcriptionpipeline")
        args = self.p["ProgramArguments"]
        self.assertEqual(args[0], "/usr/bin/python3")
        self.assertTrue(args[1].endswith("AlphaVibe-prod/poc/kb-mcp/transcription_pipeline.py"))
        self.assertEqual(args[2:], ["--data-dir", "/Users/stander/My_project/AlphaVibe-prod/poc/data"])
        self.assertNotIn("--bare", args)

    def test_two_times_1310_and_2340(self):
        sci = self.p["StartCalendarInterval"]
        self.assertEqual([(d["Hour"], d["Minute"]) for d in sci], [(13, 10), (23, 40)])
        self.assertLessEqual(len(sci), T.MAX_RUNS_PER_DAY)

    def test_no_runatload_or_keepalive(self):
        self.assertNotIn("RunAtLoad", self.p)
        self.assertNotIn("KeepAlive", self.p)

    def test_environment_has_no_api_billing_variables(self):
        env = self.p["EnvironmentVariables"]
        self.assertEqual(set(env), {"PATH", "ALPHAVIBE_ALLOW_PRODUCTION_WRITE"})
        self.assertEqual(env["ALPHAVIBE_ALLOW_PRODUCTION_WRITE"], "1")
        path = env["PATH"].split(":")
        self.assertIn("/Users/stander/.local/bin", path)
        self.assertIn("/opt/homebrew/bin", path)
        for k in env:
            self.assertFalse(k.startswith("ANTHROPIC_") or k.startswith("CLAUDE_CODE_"), k)
        for v in env.values():
            self.assertNotIn("sk-ant", v)
        self.assertNotIn("sk-ant", self.raw)
        self.assertNotIn(CR.TOKEN_ENV, "".join(env))

    def test_no_stale_golden_eval_wording(self):
        self.assertNotIn("golden", self.raw.lower())
        self.assertNotIn("金標準", self.raw)

    def test_log_path(self):
        self.assertEqual(self.p["StandardOutPath"], "/Users/stander/Library/Logs/alphavibe-transcription.log")

    def test_no_time_collision_with_other_launchd_plists(self):
        mine = set((d["Hour"], d["Minute"]) for d in self.p["StartCalendarInterval"])
        known = {(2, 0), (3, 30), (3, 45), (4, 0), (6, 0), (7, 45), (9, 30), (12, 30), (17, 0), (20, 15), (23, 0), (23, 15), (10, 0)}
        self.assertFalse(mine & known)
        for path in glob.glob(os.path.join(os.path.dirname(PLIST), "*.plist")):
            if os.path.abspath(path) == os.path.abspath(PLIST):
                continue
            with open(path, "rb") as f:
                other = plistlib.load(f).get("StartCalendarInterval") or []
            other = [other] if isinstance(other, dict) else other
            self.assertFalse(mine & set((d.get("Hour"), d.get("Minute")) for d in other), path)

    def test_gap_between_runs_exceeds_session_window(self):
        times = sorted(d["Hour"] * 60 + d["Minute"] for d in self.p["StartCalendarInterval"])
        gaps = [b - a for a, b in zip(times, times[1:])] + [times[0] + 1440 - times[-1]]
        self.assertTrue(all(g >= 60 for g in gaps))


class ApiRetranscribeProtectionTest(unittest.TestCase):
    def test_retranscribe_query_skips_claude_cli_models(self):
        src = _read(investanchors_import.__file__)
        self.assertIn("NOT LIKE 'claude-cli:%'", src)
        self.assertIn("NOT LIKE 'manual:%'", src)


if __name__ == "__main__":
    unittest.main()
