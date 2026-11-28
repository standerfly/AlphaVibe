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

    def _rejected(self, hours_ago):
        """被額度守衛擋下的執行（logged_in=0、result=aborted_limit）。"""
        self.store.conn.execute(
            "INSERT INTO import_runs (started_at, finished_at, trigger, logged_in, result) VALUES (?,?,?,?,?)",
            (self._iso8(hours_ago), self._iso8(hours_ago), "none", 0, "aborted_limit"))
        self.store.conn.commit()

    def _lost_slot_warnings(self):
        return [f for f in self._check() if f[0] == "warning" and "名額沒用滿" in f[2]]

    def test_rejected_with_unused_quota_warns(self):
        self._run(1)                       # 今天只登入 1 次
        self._rejected(0.5)                # 之後仍被擋 → 間隔不足／封鎖／手動占用
        w = self._lost_slot_warnings()
        self.assertEqual(len(w), 1)
        self.assertIn("間隔不足", w[0][2])

    def test_rejected_when_quota_used_up_is_normal(self):
        self._run(3)
        self._run(2)                       # 今天已登入 2 次（用滿）
        self._rejected(0.5)
        self.assertEqual(self._lost_slot_warnings(), [])

    def test_no_rejection_no_lost_slot_warning(self):
        self._run(1)
        self.assertEqual(self._lost_slot_warnings(), [])

    def test_old_rejection_outside_window_ignored(self):
        self._run(24 * 6)
        self._rejected(24 * 5)             # 5 天前（窗口 3 天）
        self.assertEqual(self._lost_slot_warnings(), [])

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

    def test_two_logins_today_ok_three_critical_and_summary_has_count(self):
        self._run(0.02)
        self._run(0.01)
        findings = self._check()
        self.assertEqual([f[0] for f in findings], ["ok"])
        self.assertIn("今日登入 2 次", findings[0][2])
        self._run(0.0)                                            # 當日第 3 次登入（額度守衛失效的徵兆）
        self.assertEqual(self._sev(), ["critical"])
        self.assertIn("今日登入 3 次，超過每日上限 2 次", self._text())

    def test_runs_without_login_do_not_count_toward_daily_logins(self):
        for h in (0.03, 0.02, 0.01, 0.0):
            self._run(h, logged_in=0, logged_out=None)
        self.assertEqual(self._sev(), [])
        self.assertIn("今日登入 0 次", self._text())

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


class ArticlesBackupCheckTest(unittest.TestCase):
    """010：articles.db 備份檢查——存在才檢查、缺漏／過舊 warning、未上線不報、不影響 alphavibe 備份檢查。"""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="alphavibe-art-data-")
        self.bk = tempfile.mkdtemp(prefix="alphavibe-art-bk-")
        self.addCleanup(shutil.rmtree, self.data, True)
        self.addCleanup(shutil.rmtree, self.bk, True)

    def _db(self):
        with open(os.path.join(self.data, "articles.db"), "wb") as f:
            f.write(b"x")

    def _bk(self, name, hours_ago=1):
        path = os.path.join(self.bk, name)
        with gzip.open(path, "wb") as f:
            f.write(os.urandom(1024))
        ts = (datetime.datetime.now() - datetime.timedelta(hours=hours_ago)).timestamp()
        os.utime(path, (ts, ts))

    def test_not_online_reports_nothing(self):
        self.assertEqual(checker.check_articles_backup(self.data, self.bk), [])

    def test_existing_db_without_backup_is_warning(self):
        self._db()
        f = checker.check_articles_backup(self.data, self.bk)
        self.assertEqual(f[0][0], "warning")
        self.assertEqual(f[0][1], "articles_backup")

    def test_existing_db_with_stale_backup_is_warning(self):
        self._db()
        self._bk("articles-20260101-033000.db.gz", hours_ago=checker.BACKUP_STALE_HOURS + 5)
        f = checker.check_articles_backup(self.data, self.bk)
        self.assertEqual(f[0][0], "warning")
        self.assertIn("小時前", f[0][2])

    def test_existing_db_with_fresh_backup_is_ok(self):
        self._db()
        self._bk("articles-20260101-033000.db.gz", hours_ago=2)
        self.assertEqual(checker.check_articles_backup(self.data, self.bk)[0][0], "ok")

    def test_alphavibe_backup_does_not_satisfy_articles_check(self):
        self._db()
        self._bk("alphavibe-20260101-033000.db.gz", hours_ago=1)      # 只有 alphavibe 備份
        self.assertEqual(checker.check_articles_backup(self.data, self.bk)[0][0], "warning")

    def test_articles_backup_does_not_change_alphavibe_check(self):
        self._bk("articles-20260101-033000.db.gz", hours_ago=1)       # 只有 articles 備份
        self.assertEqual(checker.check_backups(self.bk)[0][0], "critical")   # 與既有行為相同：找不到 alphavibe 備份

    def test_registered_in_checks_and_run_all_tolerates_missing_db(self):
        self.assertIn("articles_backup", [c[0] for c in checker.CHECKS])


# ---------------------------------------------------------------- 011 US7（T054～T056）
TZ8 = datetime.timezone(datetime.timedelta(hours=8))
# SC-010／PO 決定 #15：健檢 detail 不得出現的判定字眼（「提醒：」開頭的現況句允許）
JUDGEMENT_WORDS = ("異常", "不足", "危險", "超標", "閾值")


def _t8(hours_ago=0.0):
    return (datetime.datetime.now(TZ8) - datetime.timedelta(hours=hours_ago)).isoformat(
        timespec="seconds")


def _assert_no_judgement_words(test, findings):
    for sev, job, detail in findings:
        for word in JUDGEMENT_WORDS:
            test.assertNotIn(word, detail, "%s/%s 出現判定字眼 %r：%s" % (sev, job, word, detail))


def _snapshot(path):
    with open(path, "rb") as f:
        return f.read(), os.stat(path).st_mtime_ns


class SubstackImportCheckTest(unittest.TestCase):
    """011 T054：check_substack_import（SC-006 後半、SC-010、FR-013、FR-028、FR-029）。"""

    def setUp(self):
        import substack_store
        self.S = substack_store
        self.tmp = tempfile.mkdtemp(prefix="alphavibe-health-sub-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = None
        self._seq = 0

    def tearDown(self):
        if self.store is not None:
            self.store.close()

    def _db(self):
        if self.store is None:
            self.store = self.S.SubstackStore(self.tmp)
        return self.store

    def _run(self, hours_ago=2, trigger="schedule", result="ok", duration=38):
        s = self._db()
        start = datetime.datetime.now(TZ8) - datetime.timedelta(hours=hours_ago)
        day = start.date().isoformat() if trigger in ("schedule", "catchup") else None
        rid = s.start_run(trigger, schedule_day=day, started_at=start.isoformat(timespec="seconds"))
        s.finish_run(rid, result, finished_at=(start + datetime.timedelta(seconds=duration))
                     .isoformat(timespec="seconds"))
        return rid

    def _article(self, comp, days_ago=0, source="schedule", author="fomosoc"):
        s = self._db()
        self._seq += 1
        fetched = (datetime.datetime.now(TZ8).replace(hour=12, minute=0, second=0, microsecond=0)
                   - datetime.timedelta(days=days_ago))
        row = {"author_key": author, "guid": "g-%d" % self._seq,
               "link": "https://example.invalid/p/x-%d" % self._seq,
               "link_norm": "example.invalid/p/x-%d" % self._seq,
               "title": "t-%d" % self._seq, "published_at": fetched.isoformat(timespec="seconds"),
               "fetched_at": fetched.isoformat(timespec="seconds"), "source": source,
               "completeness": comp, "classify_reason": "test",
               "content_html": "<p>x</p>", "body_text": None if comp == "N" else "body"}
        return s.insert_article_with_images(row, ())

    def _check(self):
        if self.store is not None:
            self.store.close()
            self.store = None
        return checker.check_substack_import(self.tmp)

    def _warnings(self, findings):
        return [f for f in findings if f[0] == "warning"]

    def _summary(self, findings):
        hits = [f for f in findings if f[0] == "ok" and f[2].startswith("上次成功")]
        self.assertEqual(len(hits), 1, findings)
        return hits[0][2]

    def _seven_days(self, comp="P"):
        for d in range(1, 8):
            self._article(comp, days_ago=d)

    # --- 基本情況
    def test_missing_db_is_ok_and_creates_nothing(self):
        f = checker.check_substack_import(self.tmp)
        self.assertEqual(f, [("ok", "substack_import", "尚未建立（找不到 substack.db）")])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_no_runs_is_ok(self):
        self._db()
        f = self._check()
        self.assertFalse(self._warnings(f))
        self.assertIn(("ok", "substack_import", "尚未有執行紀錄（排程未安裝？）"), f)
        self.assertIn("上次成功 無", self._summary(f))

    def test_recent_scheduled_run_no_warning(self):
        self._run(hours_ago=2)
        f = self._check()
        self.assertFalse(self._warnings(f), f)

    def test_stale_scheduled_run_is_warning_ignoring_deferred(self):
        self._run(hours_ago=96)
        self._run(hours_ago=1, result="deferred", duration=0)
        self._run(hours_ago=1, trigger="catchup", result="already_done", duration=0)
        w = self._warnings(self._check())
        self.assertTrue([x for x in w if "超過 3 天沒有排程執行" in x[2]], w)

    def test_manual_run_does_not_count_as_scheduled(self):
        self._run(hours_ago=96)
        self._run(hours_ago=1, trigger="manual")
        w = self._warnings(self._check())
        self.assertTrue([x for x in w if "超過 3 天沒有排程執行" in x[2]], w)

    def test_author_consecutive_failures(self):
        self._run()
        s = self._db()
        s.upsert_author("fomosoc")
        s.upsert_author("other")
        for _ in range(3):
            s.record_feed_request("fomosoc", _t8(1), "timeout")
        for _ in range(2):
            s.record_feed_request("other", _t8(1), "timeout")
        w = self._warnings(self._check())
        self.assertIn(("warning", "substack_import", "作者 fomosoc 連續失敗 3 次（最近結果 timeout）"), w)
        self.assertFalse([x for x in w if "other" in x[2]])

    def test_aborted_budget_is_warning(self):
        rid = self._run(result="aborted_budget", duration=1200)
        w = self._warnings(self._check())
        self.assertTrue([x for x in w if "20 分鐘預算" in x[2] and ("run#%d" % rid) in x[2]], w)

    def test_notify_abandoned_is_warning(self):
        self._run()
        aid = self._article("F")
        s = self._db()
        for _ in range(3):
            s.record_notify_result(aid, False)
        w = self._warnings(self._check())
        self.assertTrue([x for x in w if "1 篇文章通知已放棄" in x[2]], w)

    def test_summary_contents(self):
        self._run(hours_ago=3, duration=38)
        self._run(hours_ago=27, duration=55)
        s = self._db()
        aid = s.insert_article_with_images(
            {"author_key": "fomosoc", "guid": "img", "link": "https://example.invalid/p/img",
             "link_norm": "example.invalid/p/img", "title": "t", "published_at": _t8(3),
             "fetched_at": _t8(3), "source": "schedule", "completeness": "P",
             "classify_reason": "read_more_tail", "content_html": "<p>x</p>", "body_text": "b"},
            [{"seq": 1, "src_url": "https://substackcdn.com/a.png"},
             {"seq": 2, "src_url": "https://substackcdn.com/b.png"},
             {"seq": 3, "src_url": "https://substackcdn.com/c.png"}])
        imgs = s.list_images(aid)
        s.set_image_downloaded(imgs[0]["id"], "substack_images/%d/1.png" % aid, size_bytes=3)
        s.set_image_failed(imgs[1]["id"], "timeout")
        for _ in range(3):
            s.set_image_failed(imgs[2]["id"], "timeout")
        self._article("N")
        s.add_reclassification(aid, "po_article", "P", "F", "manual", "v1", run_id=None)
        rid = self._run(hours_ago=1, trigger="manual", duration=10)
        for status, outcome, req, ago in ((200, "ok_200", 1, 2), (200, "ok_200", 1, 3),
                                          (304, "not_modified", 1, 4), (None, "timeout", 1, 5),
                                          (403, "blocked_403", 1, 6), (None, "skipped_interval", 0, 7),
                                          (200, "ok_200", 1, 24 * 8)):
            s.add_poll_log(run_id=rid, author_key="fomosoc", at=_t8(ago), requested=req,
                           http_status=status, outcome=outcome)
        text = self._summary(self._check())
        self.assertIn("耗時 10 秒，最近 7 次最長 55 秒", text)
        self.assertIn("近 7 天請求 5 次：200×2、304×1、失敗×1（timeout×1）、被擋×1、間隔跳過×1", text)
        self.assertIn("文章 P 0／F 1／N 1（有效完整度；其中被重判過 1 篇）", text)
        self.assertIn("圖片 已下載 1、缺圖 1、放棄 1", text)
        self.assertIn("未通知 2", text)
        self.assertIn("全文占比：", text)
        self.assertIn("空間：剩餘", text)
        self.assertIn("substack.db", text)
        # 只含數字、代碼、時間：不含標題與網址
        self.assertNotIn("example.invalid", text)
        self.assertNotIn("substackcdn", text)

    # --- FR-013 全文占比
    def test_ratio_fewer_than_seven_days_not_judged(self):
        self._run()
        for d in range(1, 4):
            self._article("P", days_ago=d)
        self._article("F")
        f = self._check()
        self.assertFalse([x for x in self._warnings(f) if "全文占比" in x[2]])
        self.assertIn("全文占比：最近抓取日 100%，可比較天數 3，未滿 7 天，不判斷", self._summary(f))

    def test_ratio_jump_over_30_points_is_reminder(self):
        self._run()
        self._seven_days("P")
        self._article("F")
        w = [x for x in self._warnings(self._check()) if "全文占比" in x[2]]
        self.assertEqual(len(w), 1, w)
        self.assertTrue(w[0][2].startswith("提醒："), w[0][2])
        self.assertIn("全文占比 100%，近 7 天平均 0%，相差 100 個百分點", w[0][2])
        self.assertIn("只報現況", w[0][2])

    def test_ratio_within_30_points_no_reminder(self):
        self._run()
        self._seven_days("F")
        self._article("F")
        self._article("P")          # 今日 50%，近 7 天 100%，相差 50 → 提醒
        self._article("F")          # 今日 67%，相差 33 → 仍提醒
        self._article("F")          # 今日 75%，相差 25 → 不提醒
        f = self._check()
        self.assertFalse([x for x in self._warnings(f) if "全文占比" in x[2]], f)
        self.assertIn("近 7 天平均 100%（可比較 7 天）", self._summary(f))

    def test_ratio_ignores_backfill(self):
        self._run()
        self._seven_days("P")
        self._article("P")
        for _ in range(5):
            self._article("F", source="backfill")
        f = self._check()
        self.assertFalse([x for x in self._warnings(f) if "全文占比" in x[2]], f)

    def test_ratio_uses_original_classification(self):
        self._run()
        self._seven_days("P")
        aid = self._article("F")
        s = self._db()
        s.add_reclassification(aid, "po_article", "F", "P", "manual", "v1")
        w = [x for x in self._warnings(self._check()) if "全文占比" in x[2]]
        self.assertEqual(len(w), 1, "重判不得改變 FR-013 的結果（用原判斷）")

    def test_n_class_does_not_trigger_reminder(self):
        self._run()
        self._seven_days("P")
        for _ in range(5):
            self._article("N")
        f = self._check()
        self.assertFalse(self._warnings(f), f)
        self.assertIn("N 5", self._summary(f))

    # --- 禁字與唯讀
    def test_no_judgement_words_even_with_many_warnings(self):
        self._run(hours_ago=96, result="aborted_budget")
        self._seven_days("P")
        aid = self._article("F")
        s = self._db()
        s.upsert_author("fomosoc")
        for _ in range(3):
            s.record_feed_request("fomosoc", _t8(1), "timeout")
            s.record_notify_result(aid, False)
        f = self._check()
        self.assertGreaterEqual(len(self._warnings(f)), 4, f)
        _assert_no_judgement_words(self, f)

    def test_readonly_bytes_unchanged_and_no_new_files(self):
        self._run()
        self._article("F")
        self.store.close()
        self.store = None
        path = os.path.join(self.tmp, "substack.db")
        before = _snapshot(path)
        listing = sorted(os.listdir(self.tmp))
        checker.check_substack_import(self.tmp)
        self.assertEqual(_snapshot(path), before)
        self.assertEqual(sorted(os.listdir(self.tmp)), listing)


class SubstackBackupCheckTest(unittest.TestCase):
    """011 T055：check_substack_backup（contracts/health-output.md §2；FR-029、US7-AS3）。"""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="alphavibe-sub-data-")
        self.root = tempfile.mkdtemp(prefix="alphavibe-sub-bk-")
        self.addCleanup(shutil.rmtree, self.data, True)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.daily = os.path.join(self.root, "daily")
        self.mirror = os.path.join(self.root, "mirror", "substack_images")
        os.makedirs(self.daily)

    def _db(self, with_images=True):
        with open(os.path.join(self.data, "substack.db"), "wb") as f:
            f.write(b"x")
        if with_images:
            os.makedirs(os.path.join(self.data, "substack_images", "1"))

    def _age(self, path, hours_ago):
        ts = (datetime.datetime.now() - datetime.timedelta(hours=hours_ago)).timestamp()
        os.utime(path, (ts, ts))

    def _bk(self, name="substack-20261120-033000.db.gz", hours_ago=1):
        path = os.path.join(self.daily, name)
        with gzip.open(path, "wb") as f:
            f.write(os.urandom(1024))
        self._age(path, hours_ago)

    def _sync(self, hours_ago=1, files=2):
        os.makedirs(os.path.join(self.mirror, "1"), exist_ok=True)
        for i in range(files):
            with open(os.path.join(self.mirror, "1", "%d.png" % i), "wb") as f:
                f.write(b"p")
        marker = os.path.join(self.mirror, ".last_sync")
        with open(marker, "w") as f:
            f.write("x")
        self._age(marker, hours_ago)

    def _check(self):
        return checker.check_substack_backup(self.data, self.daily)

    def _sev(self, findings):
        return sorted(set(f[0] for f in findings))

    def test_db_missing_is_ok_skip_and_creates_nothing(self):
        f = self._check()
        self.assertEqual(f, [("ok", "substack_backup", "尚未建立，略過")])
        self.assertEqual(os.listdir(self.data), [])
        self.assertEqual(os.listdir(self.daily), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "mirror")))

    def test_no_backup_is_warning(self):
        self._db()
        self._sync()
        f = self._check()
        self.assertEqual(self._sev(f), ["warning"])
        self.assertEqual(f[0][1], "substack_backup")

    def test_stale_backup_is_warning(self):
        self._db()
        self._sync()
        self._bk(hours_ago=checker.BACKUP_STALE_HOURS + 10)
        f = self._check()
        self.assertEqual(self._sev(f), ["warning"])
        self.assertIn("substack 最新備份是", f[0][2])
        self.assertIn("小時前", f[0][2])

    def test_mirror_marker_missing_is_warning(self):
        self._db()
        self._bk()
        f = self._check()
        self.assertEqual(self._sev(f), ["warning"])
        self.assertIn("substack_images 鏡像", f[0][2])

    def test_mirror_marker_stale_is_warning(self):
        self._db()
        self._bk()
        self._sync(hours_ago=40)
        f = self._check()
        self.assertEqual(self._sev(f), ["warning"])
        self.assertIn("substack_images 鏡像最後同步 40 小時前", f[0][2])

    def test_all_fresh_is_ok(self):
        self._db()
        self._bk(hours_ago=6)
        self._bk(name="substack-20261119-033000.db.gz", hours_ago=30)
        self._sync(hours_ago=6, files=3)
        f = self._check()
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0][0], "ok")
        self.assertIn("正常（資料庫 6 小時前，共 2 份；圖片鏡像 6 小時前，3 個檔案）", f[0][2])

    def test_no_images_dir_does_not_require_mirror(self):
        self._db(with_images=False)
        self._bk()
        f = self._check()
        self.assertEqual(self._sev(f), ["ok"], f)

    def test_articles_backup_does_not_satisfy_substack(self):
        self._db()
        self._sync()
        self._bk(name="articles-20261120-033000.db.gz")
        self.assertEqual(self._sev(self._check()), ["warning"])

    def test_no_judgement_words_and_readonly(self):
        self._db()
        listing = sorted(os.listdir(self.data))
        f = self._check()
        self._bk(hours_ago=99)
        self._sync(hours_ago=99)
        f += self._check()
        _assert_no_judgement_words(self, f)
        self.assertEqual(sorted(os.listdir(self.data)), listing)


class TokenScheduleGapsCheckTest(unittest.TestCase):
    """011 T056：check_token_schedule_gaps（FR-030、SC-010；research R3）。"""

    LABEL = "com.alphavibe.transcriptionpipeline"

    def setUp(self):
        import plistlib
        self.plistlib = plistlib
        self.data = tempfile.mkdtemp(prefix="alphavibe-tok-data-")
        self.agents = tempfile.mkdtemp(prefix="alphavibe-tok-agents-")
        self.addCleanup(shutil.rmtree, self.data, True)
        self.addCleanup(shutil.rmtree, self.agents, True)

    def _plist(self, times, label=None):
        label = label or self.LABEL
        path = os.path.join(self.agents, label + ".plist")
        sci = [{"Hour": h, "Minute": m} for h, m in times]
        with open(path, "wb") as f:
            self.plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/true"],
                                "StartCalendarInterval": sci if len(sci) != 1 else sci[0]}, f)
        return path

    def _pipeline_runs(self, minutes_list, unfinished=0):
        import article_store
        store = article_store.ArticleStore(self.data)
        try:
            base = datetime.datetime(2026, 11, 1, 23, 40, tzinfo=TZ8)
            for i, minutes in enumerate(minutes_list):
                start = base + datetime.timedelta(days=i)
                rid = store.start_pipeline_run("schedule", now=start)
                store.finish_pipeline_run(rid, "ok", now=start + datetime.timedelta(minutes=minutes))
            for i in range(unfinished):
                store.start_pipeline_run("schedule", now=base + datetime.timedelta(days=100 + i))
        finally:
            store.conn.close()

    def _check(self):
        return checker.check_token_schedule_gaps(self.data, agents_dir=self.agents)

    def test_none_installed_is_ok(self):
        self.assertEqual(self._check(),
                         [("ok", "token_schedule_gaps", "未安裝任何會消耗 token 的排程")])

    def test_no_duration_records_cannot_judge(self):
        self._plist([(23, 40)])
        f = self._check()
        self.assertEqual([x[0] for x in f], ["ok"])
        self.assertIn("%s：無耗時紀錄、無法判斷" % self.LABEL, f[0][2])
        self.assertEqual(os.listdir(self.data), [], "沒有 010 文章庫時不得建立")

    def test_only_unfinished_runs_cannot_judge(self):
        self._plist([(23, 40)])
        self._pipeline_runs([], unfinished=2)
        f = self._check()
        self.assertIn("無耗時紀錄、無法判斷", f[0][2])

    def test_single_slot_gap_is_1440(self):
        self._plist([(23, 40)])
        self._pipeline_runs([20, 52, 31])
        f = self._check()
        self.assertEqual([x[0] for x in f], ["ok"])
        self.assertIn("23:40", f[0][2])
        self.assertIn("預估耗時 52 分", f[0][2])
        self.assertIn("間隔 1440 分", f[0][2])

    def test_estimate_uses_latest_ten_finished_runs(self):
        self._plist([(23, 40)])
        self._pipeline_runs([300] + [10] * 10)          # 最舊的 300 分不在最近 10 筆內
        self.assertIn("預估耗時 10 分", self._check()[0][2])

    def test_short_gap_is_reminder_without_modifying_plist(self):
        path = self._plist([(23, 40), (0, 10)])
        self._pipeline_runs([52])
        before = _snapshot(path)
        f = self._check()
        w = [x for x in f if x[0] == "warning"]
        self.assertEqual(len(w), 1, f)
        self.assertTrue(w[0][2].startswith("提醒："), w[0][2])
        self.assertIn("23:40", w[0][2])
        self.assertIn("00:10", w[0][2])
        self.assertIn("間隔 30 分", w[0][2])
        self.assertIn("52 分＋30 分", w[0][2])
        self.assertIn("系統不會自動修改", w[0][2])
        self.assertEqual(_snapshot(path), before, "FR-030：不得自動修改排程")
        self.assertEqual(os.listdir(self.agents), [os.path.basename(path)])

    def test_long_enough_gap_no_reminder(self):
        self._plist([(23, 40), (12, 30)])
        self._pipeline_runs([52])
        self.assertEqual([x[0] for x in self._check()], ["ok"])

    def test_never_critical(self):
        scenarios = []
        scenarios.append(self._check())
        self._plist([(23, 40), (23, 41)])
        scenarios.append(self._check())
        self._pipeline_runs([600])
        scenarios.append(self._check())
        with open(os.path.join(self.agents, self.LABEL + ".plist"), "wb") as f:
            f.write(b"not a plist")
        scenarios.append(self._check())
        for f in scenarios:
            self.assertNotIn("critical", [x[0] for x in f], f)
            _assert_no_judgement_words(self, f)

    def test_unrelated_plists_ignored(self):
        self._plist([(23, 41)], label="com.alphavibe.flighttracking")
        self.assertEqual(self._check(),
                         [("ok", "token_schedule_gaps", "未安裝任何會消耗 token 的排程")])

    def test_all_three_registered_in_checks(self):
        names = [c[0] for c in checker.CHECKS]
        for name in ("substack_import", "substack_backup", "token_schedule_gaps"):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
