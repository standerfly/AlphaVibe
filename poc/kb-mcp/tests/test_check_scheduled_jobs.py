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


if __name__ == "__main__":
    unittest.main()
