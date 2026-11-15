"""T021：不外洩負向測試（spec 驗收（c））。

跑完整匯入流程（假網站＋真 scraper），收集：importer 的 stdout、scraper 的 JSONL 輸出、全部假 Telegram 訊息、
資料庫每個 TEXT 欄位（文章內文欄位除外，內文本來就要存）、資料目錄下所有檔案名稱，逐一斷言**不含**：
測試密碼、帳號、假 cookie（sid=）、CSRF token、追蹤連結 token、文章全文（獨特標記）。
涵蓋成功、登入失敗、被擋、頁面結構改變四條路徑。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import article_images  # noqa: E402
import article_probe  # noqa: E402
import investanchors_redact as R  # noqa: E402
from fake_investanchors_site import CSRF, EMAIL, PASSWORD, FakeSite  # noqa: E402
from test_investanchors_import import clue  # noqa: E402
from test_investanchors_import_e2e import E2E  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402

BODY_MARK = "SECRETBODY"
SECRETS = [PASSWORD, EMAIL]
FORBIDDEN = ["sid=", CSRF, "authenticity_token", "set-cookie", "/c/eJw"]


class CapturingRunner(object):
    def __init__(self):
        self.objs = []

    def __call__(self, payload):
        out = article_probe.default_scraper_runner(payload)
        self.objs.extend(out)
        return out


def db_text_values(store):
    """每個 TEXT 欄位的值（article.body 例外：全文本來就要存）。"""
    values = []
    tables = [r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        cols = [(r[1], (r[2] or "").upper()) for r in store.conn.execute("PRAGMA table_info(%s)" % t)]
        for name, ctype in cols:
            if t == "article" and name == "body":
                continue
            if ctype in ("TEXT", ""):
                for (v,) in store.conn.execute("SELECT %s FROM %s" % (name, t)):
                    if v is not None:
                        values.append("%s.%s=%s" % (t, name, v))
    return values


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class NoLeakTest(unittest.TestCase):
    def _run(self, site, creds_password=PASSWORD):
        h = E2E(self, site, clues=[clue()])
        runner = CapturingRunner()
        if creds_password != PASSWORD:
            h._secret_orig = h._secret

            def bad(account, runner=None, service=None):
                return creds_password if account == "password" else h._secret_orig(account, runner, service)
            h._secret = bad
        code = h.go(run_scraper=runner)
        return h, runner, code

    def _assert_everything_clean(self, h, runner, secrets=SECRETS):
        store = h.store()
        # 1. importer 輸出、通知
        for text in [h.out.getvalue()] + list(h.notes):
            R.assert_clean(text, secrets, FORBIDDEN + [BODY_MARK])
        # 2. scraper JSONL：文章事件含全文是資料通道，其餘事件不得有全文；全部不得有帳密／cookie／token
        for o in runner.objs:
            text = json.dumps(o, ensure_ascii=False)
            R.assert_clean(text, secrets, FORBIDDEN + ([] if o.get("type") == "article" else [BODY_MARK]))
        # 3. 資料庫 TEXT 欄位（含 last_error）
        for v in db_text_values(store):
            R.assert_clean(v, secrets, FORBIDDEN + [BODY_MARK])
        # 4. 資料目錄下的檔案名稱
        for root, _dirs, files in os.walk(h.tmp):
            for f in files:
                R.assert_clean(os.path.join(root, f), secrets, FORBIDDEN)

    def test_success_path(self):
        h, runner, code = self._run(FakeSite())
        self.assertEqual(code, 0)
        self.assertTrue(any(o.get("type") == "article" for o in runner.objs))       # 確實有跑到文章
        self._assert_everything_clean(h, runner)

    def test_login_failure_path(self):
        h, runner, code = self._run(FakeSite(), creds_password="wrong-pw-456")
        self.assertEqual(code, 1)
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "login_failed")
        self._assert_everything_clean(h, runner, SECRETS + ["wrong-pw-456"])

    def test_blocked_path(self):
        h, runner, code = self._run(FakeSite(article_modes={1010: "forbidden"}))
        self.assertEqual(code, 1)
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "blocked")
        self._assert_everything_clean(h, runner)

    def test_structure_change_path_has_last_error_and_it_is_clean(self):
        h, runner, code = self._run(FakeSite(default_article_mode="no_container"))
        self.assertEqual(code, 1)
        rows = h.store().conn.execute("SELECT last_error FROM article WHERE last_error IS NOT NULL").fetchall()
        self.assertTrue(rows)
        self._assert_everything_clean(h, runner)

    def test_scanner_itself_catches_a_planted_leak(self):
        h, runner, code = self._run(FakeSite())
        runner.objs.append({"type": "fact", "data": {"debug": "Cookie: sid=abc"}})
        with self.assertRaises(AssertionError):
            self._assert_everything_clean(h, runner)


if __name__ == "__main__":
    unittest.main()
