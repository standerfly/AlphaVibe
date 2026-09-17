"""認證設定的回歸測試（2026-09-17 架構體檢 A5）。

守的是一件事：**沒有認證設定時，服務必須拒絕，而不是靜默放行**。

舊版是 fail-open——讀不到 token 就當作「本機開發模式」放行所有請求。
問題不在於當下有沒有設 token，而在於失效模式：plist 一次編輯失誤，
公開 ngrok 網址上的儀表板與 47 個 MCP 工具（含全部寫入工具）就全部
無認證，服務照樣回 200，沒有任何跡象。

這也是本專案 app/tests/ 底下第一支標準 unittest（既有的 test_smoke.py
與 test_quick_input.py 是手寫腳本，`def test_` 數量是 0，
`unittest discover` 一個都收不到——見體檢報告 B2）。

執行：.venv/bin/python3 -m unittest discover -s app/tests
"""
import os
import sys
import unittest
import unittest.mock

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from app import deps  # noqa: E402


def _env(**overrides):
    """回傳一個把指定變數設成 overrides 的 patch context。值為 None
    代表「該變數不存在」（不是空字串）。"""
    base = {k: v for k, v in os.environ.items()
            if k not in ("ALPHAVIBE_DASHBOARD_TOKEN", "ALPHAVIBE_MCP_TOKEN",
                         "ALPHAVIBE_ALLOW_NO_AUTH")}
    base.update({k: v for k, v in overrides.items() if v is not None})
    return unittest.mock.patch.dict(os.environ, base, clear=True)


class StartupAssertionTest(unittest.TestCase):
    """assert_auth_configured()：不合格的設定必須讓服務起不來。"""

    def test_rejects_when_no_tokens_and_no_optout(self):
        with _env():
            with self.assertRaises(RuntimeError) as ctx:
                deps.assert_auth_configured()
            msg = str(ctx.exception)
            self.assertIn("拒絕啟動", msg)
            self.assertIn("ALPHAVIBE_DASHBOARD_TOKEN", msg)
            self.assertIn("ALPHAVIBE_MCP_TOKEN", msg)

    def test_rejects_when_only_dashboard_token_set(self):
        """兩道認證是獨立的——只設一個不算設定完整。/mcp 被豁免於
        儀表板認證，只靠 ALPHAVIBE_MCP_TOKEN 那一道。"""
        with _env(ALPHAVIBE_DASHBOARD_TOKEN="pw"):
            with self.assertRaises(RuntimeError) as ctx:
                deps.assert_auth_configured()
            self.assertIn("ALPHAVIBE_MCP_TOKEN", str(ctx.exception))

    def test_rejects_when_only_mcp_token_set(self):
        with _env(ALPHAVIBE_MCP_TOKEN="secret"):
            with self.assertRaises(RuntimeError) as ctx:
                deps.assert_auth_configured()
            self.assertIn("ALPHAVIBE_DASHBOARD_TOKEN", str(ctx.exception))

    def test_passes_when_both_tokens_set(self):
        with _env(ALPHAVIBE_DASHBOARD_TOKEN="pw", ALPHAVIBE_MCP_TOKEN="secret"):
            deps.assert_auth_configured()  # 不該拋例外

    def test_optout_allows_startup_but_warns(self):
        """明確授權時放行，但一定要留下 stderr 警告——無聲的無認證模式
        跟舊版的 fail-open 一樣危險。"""
        with _env(ALPHAVIBE_ALLOW_NO_AUTH="1"):
            with unittest.mock.patch("sys.stderr") as fake_err:
                deps.assert_auth_configured()
            written = "".join(c.args[0] for c in fake_err.write.call_args_list)
            self.assertIn("ALPHAVIBE_ALLOW_NO_AUTH=1", written)
            self.assertIn("ALPHAVIBE_DASHBOARD_TOKEN", written)

    def test_optout_must_be_exactly_1(self):
        """避免 "0"／"false"／"" 這類值被當成真值放行。"""
        for value in ("0", "false", "no", "", "true", "yes"):
            with _env(ALPHAVIBE_ALLOW_NO_AUTH=value):
                if value == "1":
                    continue
                with self.assertRaises(RuntimeError,
                                       msg="ALPHAVIBE_ALLOW_NO_AUTH=%r 不該放行" % value):
                    deps.assert_auth_configured()


class RequestLevelFailClosedTest(unittest.TestCase):
    """第二道防線：即使繞過啟動斷言（例如執行期環境變數被清掉），
    請求層也不能放行。"""

    def test_dashboard_auth_denies_when_token_missing(self):
        with _env():
            self.assertFalse(deps._dashboard_auth_ok({}))

    def test_dashboard_auth_allows_when_explicitly_opted_out(self):
        with _env(ALPHAVIBE_ALLOW_NO_AUTH="1"):
            self.assertTrue(deps._dashboard_auth_ok({}))

    def test_dashboard_auth_denies_wrong_password(self):
        import base64
        wrong = base64.b64encode(b"user:wrong-pw").decode()
        with _env(ALPHAVIBE_DASHBOARD_TOKEN="right-pw"):
            self.assertFalse(deps._dashboard_auth_ok({"Authorization": "Basic " + wrong}))

    def test_dashboard_auth_accepts_correct_password(self):
        import base64
        right = base64.b64encode(b"user:right-pw").decode()
        with _env(ALPHAVIBE_DASHBOARD_TOKEN="right-pw"):
            self.assertTrue(deps._dashboard_auth_ok({"Authorization": "Basic " + right}))

    def test_mcp_auth_denies_when_token_missing(self):
        with _env():
            self.assertFalse(deps.mcp_auth_ok())

    def test_mcp_auth_ok_when_token_set(self):
        with _env(ALPHAVIBE_MCP_TOKEN="secret"):
            self.assertTrue(deps.mcp_auth_ok())

    def test_mcp_auth_respects_optout(self):
        with _env(ALPHAVIBE_ALLOW_NO_AUTH="1"):
            self.assertTrue(deps.mcp_auth_ok())


if __name__ == "__main__":
    unittest.main()
