"""排程健康巡檢的測試（2026-09-17 架構體檢 B4）。

最重要的一條：用 2026-09-14 的真實數字重現當時的事故，確認這支巡檢
真的會報警。那天 TPEx 資料源失敗，market_scan 照樣「完成」，
total_scanned 從 2327 掉到 1074，沒有任何人發現——如果這支巡檢在當時
就存在卻仍然回報 OK，那它等於不存在。
"""
import datetime
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import check_scheduled_jobs as checker  # noqa: E402


def _iso(hours_ago):
    return (datetime.datetime.now()
            - datetime.timedelta(hours=hours_ago)).isoformat(timespec="seconds")


class MarketScanCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-health-")
        self.db = os.path.join(self.tmp, "alphavibe.db")
        conn = sqlite3.connect(self.db)
        conn.execute("""
            CREATE TABLE market_scan_runs (
                id INTEGER PRIMARY KEY, framework_id TEXT, trigger_source TEXT,
                candidate_count INTEGER, meets_count INTEGER,
                twse_error TEXT, tpex_error TEXT, run_at TEXT,
                total_scanned INTEGER, benchmark_drawdown_pct REAL,
                benchmark_error TEXT, emerging_error TEXT)""")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _add(self, total_scanned=2327, hours_ago=2, **errors):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO market_scan_runs (framework_id, trigger_source,"
            " candidate_count, meets_count, twse_error, tpex_error, run_at,"
            " total_scanned, benchmark_error, emerging_error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("peg_deep_dip_concentration", "scheduled", 200, 25,
             errors.get("twse_error"), errors.get("tpex_error"), _iso(hours_ago),
             total_scanned, errors.get("benchmark_error"), errors.get("emerging_error")))
        conn.commit()
        conn.close()

    def _severities(self):
        return [f[0] for f in checker.check_market_scan(self.tmp)]

    def _details(self):
        return " ".join(f[2] for f in checker.check_market_scan(self.tmp))

    def test_healthy_run_reports_ok(self):
        for i in range(5):
            self._add(hours_ago=24 * i + 2)
        self.assertEqual(self._severities(), ["ok"])

    def test_reproduces_2026_09_14_incident(self):
        """真實事故重現：TPEx 失敗 + 掃描量腰斬，必須報 critical。"""
        for i in range(5):                       # 先建立正常的歷史基準
            self._add(total_scanned=2327, hours_ago=24 * (i + 2))
        self._add(total_scanned=1074, hours_ago=2,
                  tpex_error="TPEx 呼叫失敗：<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>")
        sevs = self._severities()
        self.assertIn("critical", sevs, "9/14 那種情況必須報 critical")
        detail = self._details()
        self.assertIn("上櫃", detail, "要講清楚是哪個市場沒掃到")
        self.assertIn("覆蓋率", detail, "掃描量腰斬要被獨立指出")

    def test_coverage_drop_alone_is_critical(self):
        """即使沒有 error 欄位，掃描量驟降本身就代表資料不完整。"""
        for i in range(5):
            self._add(total_scanned=2327, hours_ago=24 * (i + 2))
        self._add(total_scanned=1000, hours_ago=2)
        self.assertIn("critical", self._severities())

    def test_normal_daily_fluctuation_is_not_flagged(self):
        """2327→2336 這種正常波動不該吵人，否則告警會被無視。"""
        for i in range(5):
            self._add(total_scanned=2327, hours_ago=24 * (i + 2))
        self._add(total_scanned=2336, hours_ago=2)
        self.assertEqual(self._severities(), ["ok"])

    def test_stale_run_is_critical(self):
        self._add(hours_ago=50)
        sevs = self._severities()
        self.assertIn("critical", sevs)
        self.assertIn("小時沒有成功的掃描", self._details())

    def test_benchmark_error_is_only_warning(self):
        """大盤基準失敗只影響一個欄位，不像資料源失敗會讓整批結果殘缺。"""
        for i in range(5):
            self._add(hours_ago=24 * (i + 2))
        self._add(hours_ago=2, benchmark_error="FinMind HTTP 402")
        self.assertIn("warning", self._severities())
        self.assertNotIn("critical", self._severities())

    def test_emerging_error_is_critical(self):
        for i in range(5):
            self._add(hours_ago=24 * (i + 2))
        self._add(hours_ago=2, emerging_error="興櫃 呼叫失敗")
        self.assertIn("critical", self._severities())

    def test_no_records_at_all_is_critical(self):
        self.assertIn("critical", self._severities())

    def test_missing_database_is_critical(self):
        findings = checker.check_market_scan(os.path.join(self.tmp, "nope"))
        self.assertEqual(findings[0][0], "critical")


class BackupCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-bk-")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _make(self, name="alphavibe-20260917-033000.db.gz", size_mb=2.3, hours_ago=1):
        path = os.path.join(self.tmp, name)
        with gzip.open(path, "wb") as f:
            # 用隨機位元組：重複字元（b"x" * N）壓縮後只剩幾 KB，會誤觸
            # 「備份檔異常小」那條檢查，測出來的是假失敗
            f.write(os.urandom(int(size_mb * 1024 * 1024)))
        ts = (datetime.datetime.now() - datetime.timedelta(hours=hours_ago)).timestamp()
        os.utime(path, (ts, ts))
        return path

    def test_recent_backup_is_ok(self):
        self._make()
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "ok")

    def test_no_backup_is_critical(self):
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "critical")

    def test_stale_backup_is_critical(self):
        self._make(hours_ago=50)
        findings = checker.check_backups(self.tmp)
        self.assertEqual(findings[0][0], "critical")
        self.assertIn("小時前", findings[0][2])

    def test_suspiciously_small_backup_is_critical(self):
        """備份檔存在但幾乎是空的，比沒有備份更危險（會以為有）。"""
        path = os.path.join(self.tmp, "alphavibe-20260917-033000.db.gz")
        with gzip.open(path, "wb") as f:
            f.write(b"")
        self.assertEqual(checker.check_backups(self.tmp)[0][0], "critical")


class ExitCodeTest(unittest.TestCase):
    """critical 要用非 0 退出碼，之後不管接哪種通知管道都認得。"""

    def test_exit_code_2_when_critical(self):
        tmp = tempfile.mkdtemp(prefix="alphavibe-exit-")
        try:
            state_file = os.path.join(tmp, "state.json")
            rc = checker.main(["--data-dir", os.path.join(tmp, "nope"),
                               "--state-file", state_file, "--json"])
            self.assertEqual(rc, 2)
            self.assertTrue(os.path.exists(state_file), "狀態檔要寫出來供通知管道讀取")
        finally:
            shutil.rmtree(tmp)


class WebServiceCheckTest(unittest.TestCase):
    """web 服務存活檢查（架構體檢 B4 追加）。

    存在的理由：A5 的 fail-closed 引入了新故障模式——token 從 plist
    消失時服務拒絕啟動，launchd 的 KeepAlive 讓它每 10 秒 crash-loop，
    對外變成「連不上」。首頁橫幅在這種故障下幫不上忙（連首頁都打不開），
    只有這支獨立排程的巡檢叫得出來。
    """

    def test_unreachable_service_is_critical(self):
        # 保留埠 9（discard），本機不會有東西在聽
        findings = checker.check_web_service(
            "http://127.0.0.1:9/api/healthz", attempts=2, gap_seconds=0)
        self.assertEqual(findings[0][0], "critical")
        self.assertIn("連不上", findings[0][2])

    def test_unreachable_message_points_at_the_likely_cause(self):
        """訊息要直接指向最可能的原因，半夜看手機的人沒空翻文件。"""
        findings = checker.check_web_service(
            "http://127.0.0.1:9/api/healthz", attempts=1, gap_seconds=0)
        detail = findings[0][2]
        self.assertIn("ALPHAVIBE_DASHBOARD_TOKEN", detail)
        self.assertIn("拒絕啟動", detail)

    def test_retries_before_giving_up(self):
        """巡檢可能剛好撞上服務重啟的空檔，單次失敗就告警會製造假警報，
        而假警報會訓練人忽略真警報。"""
        calls = []

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            if len(calls) < 2:
                raise OSError("connection refused")
            return _Resp()

        with unittest.mock.patch("urllib.request.urlopen", fake_urlopen):
            findings = checker.check_web_service(
                "http://x/api/healthz", attempts=3, gap_seconds=0)
        self.assertEqual(findings[0][0], "ok", "第二次成功就該回報正常")
        self.assertEqual(len(calls), 2, "成功後不該繼續重試")

    def test_http_error_does_not_retry(self):
        """4xx/5xx 代表服務活著但不對勁，重試沒有意義。"""
        import urllib.error
        calls = []

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            raise urllib.error.HTTPError(url, 500, "boom", {}, None)

        with unittest.mock.patch("urllib.request.urlopen", fake_urlopen):
            findings = checker.check_web_service(
                "http://x/api/healthz", attempts=3, gap_seconds=0)
        self.assertEqual(findings[0][0], "critical")
        self.assertIn("HTTP 500", findings[0][2])
        self.assertEqual(len(calls), 1, "HTTP 錯誤不該重試")

    def test_healthy_service_is_ok(self):
        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with unittest.mock.patch("urllib.request.urlopen",
                                 lambda url, timeout=None: _Resp()):
            findings = checker.check_web_service("http://x/api/healthz")
        self.assertEqual(findings[0][0], "ok")


class NotifyDecisionTest(unittest.TestCase):
    """只在狀態變化時通知——每天固定發一則「還是壞的」會讓人麻痺，
    麻痺的告警等於沒有告警。"""

    @staticmethod
    def _state(status, *details):
        return {
            "status": status,
            "findings": [{"severity": status, "job": "market_scan", "detail": d}
                         for d in details] or
                        [{"severity": "ok", "job": "market_scan", "detail": "正常"}],
        }

    def test_first_run_healthy_stays_quiet(self):
        wanted, _ = checker.should_notify(None, self._state("ok"))
        self.assertFalse(wanted, "第一次跑而且一切正常，不該吵人")

    def test_first_run_with_problem_notifies(self):
        wanted, _ = checker.should_notify(None, self._state("critical", "TPEx 掛了"))
        self.assertTrue(wanted)

    def test_unchanged_problem_does_not_renotify(self):
        prev = self._state("critical", "TPEx 掛了")
        wanted, reason = checker.should_notify(prev, self._state("critical", "TPEx 掛了"))
        self.assertFalse(wanted, "同樣的問題不該每天重發")
        self.assertIn("相同", reason)

    def test_new_problem_notifies(self):
        prev = self._state("ok")
        wanted, _ = checker.should_notify(prev, self._state("critical", "TPEx 掛了"))
        self.assertTrue(wanted)

    def test_recovery_notifies(self):
        prev = self._state("critical", "TPEx 掛了")
        wanted, reason = checker.should_notify(prev, self._state("ok"))
        self.assertTrue(wanted, "恢復正常也要讓人知道，否則不知道還要不要處理")
        self.assertIn("恢復", reason)

    def test_different_problem_same_severity_notifies(self):
        """都是 critical 但換了一個問題，仍然要通知。"""
        prev = self._state("critical", "TPEx 掛了")
        wanted, _ = checker.should_notify(prev, self._state("critical", "備份沒跑"))
        self.assertTrue(wanted)


class MessageFormatTest(unittest.TestCase):
    def test_message_lists_problems_not_ok_items(self):
        state = {
            "status": "critical",
            "checked_at": "2026-09-17T04:00:00+08:00",
            "findings": [
                {"severity": "ok", "job": "backup", "detail": "正常"},
                {"severity": "critical", "job": "market_scan", "detail": "上櫃 TPEx 資料源失敗"},
            ],
        }
        msg = checker.notify.format_health_message(state)
        self.assertIn("CRITICAL", msg)
        self.assertIn("上櫃 TPEx 資料源失敗", msg)
        self.assertNotIn("正常", msg, "ok 的項目不該佔用手機通知的版面")

    def test_healthy_message_is_explicit(self):
        state = {"status": "ok", "checked_at": "x", "findings": []}
        self.assertIn("全部排程正常", checker.notify.format_health_message(state))


class StatementImportCheckTest(unittest.TestCase):
    """009 T018：日對帳單匯入心跳／失敗／通知失敗。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-health-stmt-")
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from kb_store import KBStore
        self.store = KBStore(self.tmp)

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp)

    def _run(self, hours_ago, outcome="ok", notify_failed=0):
        self.store.conn.execute(
            "INSERT INTO statement_import_runs (started_at, finished_at, outcome,"
            " statements_found, notify_failed) VALUES (?,?,?,0,?)",
            (_iso(hours_ago), _iso(hours_ago), outcome, notify_failed))
        self.store.conn.commit()

    def _sev(self):
        return [f[0] for f in checker.check_statement_import(self.tmp)]

    def test_not_launched_is_ok(self):
        self.assertEqual(self._sev(), ["ok"])
        empty = tempfile.mkdtemp(prefix="alphavibe-health-empty-")
        try:
            sqlite3.connect(os.path.join(empty, "alphavibe.db")).close()
            self.assertEqual([f[0] for f in checker.check_statement_import(empty)], ["ok"])
        finally:
            shutil.rmtree(empty)

    def test_recent_heartbeat_ok(self):
        self._run(5)
        self.assertEqual(self._sev(), ["ok"])

    def test_stale_heartbeat_critical(self):
        self._run(31)
        self.assertEqual(self._sev(), ["critical"])

    def test_latest_failed_statement_warning(self):
        self._run(1)
        self.store.record_statement_failure({"message_id": "m", "statement_date": "2026-10-29",
                                             "status": "failed", "error": "PDF 密碼錯誤"})
        findings = checker.check_statement_import(self.tmp)
        self.assertEqual([f[0] for f in findings], ["warning"])
        self.assertIn("PDF 密碼錯誤", findings[0][2])

    def test_unfinished_run_warning_after_one_hour(self):
        self.store.conn.execute(
            "INSERT INTO statement_import_runs (started_at) VALUES (?)", (_iso(0.1),))
        self.store.conn.commit()
        self.assertEqual(self._sev(), ["ok"])  # 可能還在跑
        self.store.conn.execute("UPDATE statement_import_runs SET started_at=?", (_iso(2),))
        self.store.conn.commit()
        self.assertEqual(self._sev(), ["warning"])

    def test_earlier_notify_failure_not_hidden_by_later_quiet_run(self):
        # F5：20:15 送失敗、23:15 沒新信成功 → 仍要回報
        self._run(3, notify_failed=1)
        self._run(0.1)
        findings = checker.check_statement_import(self.tmp)
        self.assertEqual([f[0] for f in findings], ["warning"])
        self.assertIn("Telegram", findings[0][2])

    def test_notify_failed_and_mailbox_error_warning(self):
        self._run(1, outcome="mailbox_error", notify_failed=1)
        self.assertEqual(self._sev(), ["warning", "warning"])


class InvestanchorsImportCheckTest(unittest.TestCase):
    """010 定錨文章匯入巡檢：唯讀、只輸出數字與狀態。"""

    def setUp(self):
        import article_store
        self.article_store = article_store
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-health-ia-")
        self.store = article_store.ArticleStore(self.tmp)

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp)

    def _iso8(self, hours_ago):
        tz8 = datetime.timezone(datetime.timedelta(hours=8))
        return (datetime.datetime.now(tz8) - datetime.timedelta(hours=hours_ago)).isoformat()

    def _run(self, hours_ago, logged_in=1, logged_out=1, blocked_until=None):
        self.store.conn.execute(
            "INSERT INTO import_runs (started_at, finished_at, trigger, logged_in, logged_out,"
            " blocked_until) VALUES (?,?,?,?,?,?)",
            (self._iso8(hours_ago), self._iso8(hours_ago), "schedule", logged_in, logged_out,
             blocked_until))
        self.store.conn.commit()

    def _article(self, aid, status, ok=1):
        self.store.conn.execute(
            "INSERT INTO article (article_id, url, title, status, id_time_ok) VALUES (?,?,?,?,?)",
            (aid, "https://investanchors.com/user/vip_contents/%d" % aid, "SECRET-TITLE", status, ok))
        self.store.conn.commit()

    def _check(self):
        return checker.check_investanchors_import(self.tmp)

    def _sev(self):
        return [f[0] for f in self._check() if f[0] != "ok"]

    def _text(self):
        return " ".join(f[2] for f in self._check())

    def test_db_missing_is_ok_and_not_created(self):
        empty = tempfile.mkdtemp(prefix="alphavibe-health-ia-empty-")
        try:
            findings = checker.check_investanchors_import(empty)
            self.assertEqual([f[0] for f in findings], ["ok"])
            self.assertIn("尚未建立", findings[0][2])
            self.assertEqual(os.listdir(empty), [])
        finally:
            shutil.rmtree(empty)

    def test_no_runs_is_ok(self):
        self.assertEqual([f[0] for f in self._check()], ["ok"])

    def test_recent_normal_run_ok_with_summary(self):
        self._run(5)
        findings = self._check()
        self.assertEqual([f[0] for f in findings], ["ok"])
        self.assertIn("轉寫開關 關", findings[0][2])
        self.assertIn("回補 未啟動", findings[0][2])

    def test_logged_in_not_logged_out_critical(self):
        self._run(5, logged_in=1, logged_out=0)
        self.assertEqual(self._sev(), ["critical"])
        self.assertIn("未確認登出", self._text())

    def test_no_login_logged_out_zero_not_flagged(self):
        self._run(5, logged_in=0, logged_out=0)
        self.assertEqual(self._sev(), [])

    def test_stale_runs_critical(self):
        self._run(24 * checker.INVESTANCHORS_STALE_DAYS + 1)
        self.assertEqual(self._sev(), ["critical"])
        self._run(24 * checker.INVESTANCHORS_STALE_DAYS - 1)
        self.assertEqual(self._sev(), [])

    def test_blocked_until_active_warning_expired_ignored(self):
        future = (datetime.datetime.now(datetime.timezone.utc)
                  + datetime.timedelta(hours=10)).isoformat()
        self._run(5, blocked_until=future)
        self.assertEqual(self._sev(), ["warning"])
        self.store.conn.execute("UPDATE import_runs SET blocked_until=?", (self._iso8(3),))
        self.store.conn.commit()
        self.assertEqual(self._sev(), [])

    def test_abandoned_and_id_time_anomalies_warn(self):
        self._run(5)
        self._article(1111111111111, "abandoned")
        self._article(2222, "fetched", ok=0)
        findings = self._check()
        self.assertEqual([f[0] for f in findings if f[0] != "ok"], ["warning", "warning"])
        text = self._text()
        self.assertIn("1 篇文章已放棄", text)
        self.assertIn("累計 1 篇", text)

    def test_transcription_and_backfill_status_in_summary(self):
        self._run(5)
        self._article(1111111111111, "fetched")
        self.store.add_image(1111111111111, 1, "https://x/1.png")
        self.store.add_image(1111111111111, 2, "https://x/2.png")
        self.store.conn.execute(
            "UPDATE article_image SET transcribe_attempts=? WHERE seq=2",
            (self.article_store.MAX_TRANSCRIBE_ATTEMPTS,))
        self.store.set_setting("transcribe_enabled", "1")
        self.store.conn.execute(
            "INSERT INTO backfill_state (id, completed, next_cursor) VALUES (1, 0, 'p3')")
        self.store.conn.commit()
        text = self._text()
        self.assertIn("轉寫開關 開", text)
        self.assertIn("未轉寫 2 張、已達上限 1 張", text)
        self.assertIn("進行中（游標 p3）", text)
        self.store.conn.execute("UPDATE backfill_state SET completed=1")
        self.store.conn.commit()
        self.assertIn("回補 已完成", self._text())

    def test_output_has_no_title_or_body(self):
        self._run(5, logged_out=0)
        self._article(1111111111111, "abandoned")
        self.assertNotIn("SECRET-TITLE", self._text())

    def test_read_only_file_unchanged(self):
        self._run(5, logged_out=0)
        self._article(1111111111111, "abandoned")
        self.store.conn.close()
        path = os.path.join(self.tmp, "articles.db")
        with open(path, "rb") as f:
            before = f.read()
        mtime = os.stat(path).st_mtime_ns
        checker.check_investanchors_import(self.tmp)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.stat(path).st_mtime_ns, mtime)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["articles.db"])
        self.store = self.article_store.ArticleStore(self.tmp)  # 讓 tearDown 能關

    def test_registered_in_run_all(self):
        names = [c[0] for c in checker.CHECKS]
        self.assertIn("investanchors_import", names)


if __name__ == "__main__":
    unittest.main()
