"""T004～T007：ArticleStore（articles.db）——schema、文章狀態機、圖片、通知信線索、回補進度、設定、執行紀錄。"""
import datetime
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_store as A  # noqa: E402

TZ8 = A.TZ8
URL = "https://investanchors.com/user/vip_contents/%d"
BODY = "內文。" * 100
AID = 17941406364761


def T(day, hour=23, minute=0):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=TZ8)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="articles-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = [T(15)]
        self.s = A.ArticleStore(self.tmp, now=lambda: self.clock[0])
        self.addCleanup(self.s.close)

    def add(self, aid=AID, title="標題", **kw):
        return self.s.upsert_discovered(aid, URL % aid, title, **kw)


class SchemaTest(Base):
    def test_constructor_creates_all_tables_and_writes_no_rows(self):
        names = set(r[0] for r in self.s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        for t in ("article", "article_image", "mail_clue", "backfill_state", "import_runs",
                  "alert_log", "setting"):
            self.assertIn(t, names)
            self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0], 0, t)

    def test_db_file_name_and_reopen_keeps_schema_without_side_effects(self):
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "articles.db")))
        s2 = A.ArticleStore(self.tmp)
        self.addCleanup(s2.close)
        self.assertEqual(s2.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0], 0)

    def test_mail_clue_has_no_article_id_or_title_columns(self):
        cols = [r[1] for r in self.s.conn.execute("PRAGMA table_info(mail_clue)")]
        self.assertEqual(cols, ["message_id", "mail_date", "seen_at", "processed"])

    def test_no_delete_methods_exposed(self):
        self.assertEqual([n for n in dir(A.ArticleStore) if "delete" in n.lower() or "remove" in n.lower()], [])

    def test_usable_from_another_thread(self):
        import threading
        out = []
        t = threading.Thread(target=lambda: out.append(self.s.known_ids()))
        t.start()
        t.join()
        self.assertEqual(out, [set()])


class ArticleStateTest(Base):
    def test_insert_then_exists_no_duplicate(self):
        self.assertEqual(self.add(), "inserted")
        self.assertEqual(self.add(), "exists")
        self.assertEqual(self.s.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0], 1)
        row = self.s.get_article_row(AID)
        self.assertEqual(row["status"], "discovered")
        self.assertEqual(row["id_time_ok"], 1)
        self.assertIsNotNone(row["id_time_ms"])

    def test_invalid_id_or_url_rejected(self):
        with self.assertRaises(ValueError):
            self.s.upsert_discovered("abc", URL % 1, "x")
        for bad in ("http://investanchors.com/user/vip_contents/1", "https://evil.com/user/vip_contents/1",
                    "https://investanchors.com/user/vip_contents/abc",
                    "https://investanchors.com/user/vip_contents/1/extra"):
            with self.assertRaises(ValueError, msg=bad):
                self.s.upsert_discovered(1, bad, "x")
        self.s.upsert_discovered(2, "https://www.investanchors.com/user/vip_contents/2", "ok")

    def test_unusual_id_gets_id_time_not_ok(self):
        self.s.upsert_discovered(1612580077558, URL % 1612580077558, "公告")
        row = self.s.get_article_row(1612580077558)
        self.assertEqual(row["id_time_ok"], 0)
        self.assertIsNone(row["id_time_ms"])

    def test_fetched_never_overwritten_or_reopened(self):
        self.add(title="原標題")
        self.assertTrue(self.s.mark_fetched(AID, BODY, "2026-11-08T12:00"))
        self.assertEqual(self.add(title="新標題", pinned=True), "exists")
        row = self.s.get_article_row(AID)
        self.assertEqual((row["title"], row["pinned"], row["status"]), ("原標題", 0, "fetched"))
        self.assertFalse(self.s.mark_fetched(AID, "別的內文" * 100))       # 不覆寫
        self.assertEqual(self.s.get_article_row(AID)["body"], BODY)
        self.assertEqual(self.s.mark_failed(AID, "late error"), "fetched")   # 終態不降級
        self.assertEqual(self.s.get_article_row(AID)["status"], "fetched")

    def test_partial_body_rejected_and_state_unchanged(self):
        self.add()
        for short in ("", None, "太短", "x" * 199):
            with self.assertRaises(A.BodyTooShort):
                self.s.mark_fetched(AID, short)
        row = self.s.get_article_row(AID)
        self.assertEqual((row["status"], row["body"]), ("discovered", None))

    def test_failed_attempts_then_abandoned_at_three(self):
        self.add()
        self.assertEqual(self.s.mark_failed(AID, "e1"), "failed")
        self.assertEqual(self.s.mark_failed(AID, "e2"), "failed")
        self.assertEqual(self.s.mark_failed(AID, "e3"), "abandoned")
        row = self.s.get_article_row(AID)
        self.assertEqual((row["status"], row["attempts"]), ("abandoned", 3))
        self.assertEqual(self.s.mark_failed(AID, "e4"), "abandoned")   # 不再累加
        self.assertEqual(self.s.get_article_row(AID)["attempts"], 3)

    def test_last_error_is_redacted(self):
        self.add()
        self.s.mark_failed(AID, "fail pw-secret-123 Cookie: sid=abc", secrets=["pw-secret-123"])
        err = self.s.get_article_row(AID)["last_error"]
        self.assertNotIn("pw-secret-123", err)
        self.assertNotIn("sid=abc", err)

    def test_abandoned_only_reset_manually(self):
        self.add()
        for _ in range(3):
            self.s.mark_failed(AID, "e")
        self.assertEqual(self.s.list_pending(), [])
        self.assertFalse(self.s.mark_deferred(AID))
        self.assertTrue(self.s.reset_abandoned(AID))
        row = self.s.get_article_row(AID)
        self.assertEqual((row["status"], row["attempts"]), ("failed", 0))
        self.assertEqual([r["article_id"] for r in self.s.list_pending()], [AID])

    def test_skipped_and_deferred_are_terminal_until_explicit_path(self):
        self.add(1, "【公告】x")
        self.assertTrue(self.s.mark_skipped(1))
        self.assertFalse(self.s.mark_deferred(1))
        self.add(2)
        self.assertTrue(self.s.mark_deferred(2))
        with self.assertRaises(ValueError):
            self.s.mark_fetched(2, BODY)                    # deferred 不能直接 fetched
        self.assertTrue(self.s.reactivate_deferred(2))      # PO 放寬截止日才可回 discovered
        self.assertEqual(self.s.get_article_row(2)["status"], "discovered")
        self.assertFalse(self.s.reactivate_deferred(2))

    def test_failed_can_become_fetched(self):
        self.add()
        self.s.mark_failed(AID, "e")
        self.assertTrue(self.s.mark_fetched(AID, BODY))
        row = self.s.get_article_row(AID)
        self.assertEqual((row["status"], row["last_error"]), ("fetched", None))

    def test_list_pending_new_before_backfill_then_newest_first_and_limit(self):
        self.add(30, via="backfill")
        self.add(20, via="mail")
        self.add(10, via="weekly")
        self.add(40, via="backfill")
        self.assertEqual([r["article_id"] for r in self.s.list_pending()], [20, 10, 40, 30])
        self.assertEqual([r["article_id"] for r in self.s.list_pending(limit=2)], [20, 10])

    def test_list_pending_excludes_attempts_at_limit_and_non_pending(self):
        self.add(1)
        self.add(2)
        self.s.mark_failed(2, "e")
        self.add(3)
        self.s.mark_deferred(3)
        self.assertEqual(sorted(r["article_id"] for r in self.s.list_pending()), [1, 2])

    def test_pinned_flag_sticks_and_known_ids(self):
        self.add(5)
        self.add(5, pinned=True)
        self.assertEqual(self.s.get_article_row(5)["pinned"], 1)
        self.add(6)
        self.assertEqual(self.s.known_ids(), {5, 6})
        self.assertEqual(self.s.count_by_status(), {"discovered": 2})

    def test_transition_on_missing_article_raises(self):
        for fn in (self.s.mark_deferred, self.s.mark_skipped, self.s.reset_abandoned):
            with self.assertRaises(KeyError):
                fn(999)


class ImageMailBackfillSettingTest(Base):
    def test_images_unique_per_seq_and_missing_file_tracking(self):
        self.add()
        self.assertTrue(self.s.add_image(AID, 1, "https://investanchors.com/uploads/a.png"))
        self.assertFalse(self.s.add_image(AID, 1, "https://investanchors.com/uploads/a.png"))
        self.assertEqual(len(self.s.images_missing_file()), 1)
        self.s.set_image_file(AID, 1, "articles_images/%d/1.png" % AID)
        self.assertEqual(self.s.images_missing_file(), [])
        self.assertEqual(self.s.list_images(AID)[0]["file_path"], "articles_images/%d/1.png" % AID)

    def test_transcription_rules(self):
        self.add()
        self.s.add_image(AID, 1, "u")
        self.s.set_image_file(AID, 1, "p")
        self.assertEqual(len(self.s.images_to_transcribe()), 1)
        with self.assertRaises(ValueError):
            self.s.set_transcription(AID, 1, "done", text="")            # 不以空白充數
        with self.assertRaises(ValueError):
            self.s.set_transcription(AID, 1, "untranscribed", text="猜測值")
        with self.assertRaises(ValueError):
            self.s.set_transcription(AID, 1, "maybe")
        self.s.set_transcription(AID, 1, "done", text="EPS 3.2", model="claude-haiku-5-5", is_table=True)
        im = self.s.list_images(AID)[0]
        self.assertEqual((im["transcription"], im["transcribed_model"], im["is_table"]),
                         ("EPS 3.2", "claude-haiku-5-5", 1))
        self.assertNotIn("機器轉寫", im["transcription"])
        self.assertEqual(self.s.images_to_transcribe(), [])
        self.s.set_transcription(AID, 1, "untranscribed")                # 重轉前清回
        im = self.s.list_images(AID)[0]
        self.assertEqual((im["transcription"], im["transcribed_model"]), (None, None))

    def test_mail_clue_dedupe_and_processing(self):
        self.assertTrue(self.s.add_mail_clue("<a@x>", "2026-11-12T20:00:00+08:00"))
        self.assertFalse(self.s.add_mail_clue("<a@x>", "2026-11-12T20:00:00+08:00"))
        self.s.add_mail_clue("<b@x>", "2026-11-13T20:00:00+08:00")
        self.assertEqual([c["message_id"] for c in self.s.unprocessed_mail_clues()], ["<a@x>", "<b@x>"])
        self.s.mark_mail_processed(["<a@x>"])
        self.assertEqual([c["message_id"] for c in self.s.unprocessed_mail_clues()], ["<b@x>"])

    def test_backfill_cutoff_fixed_and_only_widens_backwards(self):
        self.assertIsNone(self.s.get_backfill_state())
        self.s.start_backfill("2026-05-15", 1778774400000)
        with self.assertRaises(ValueError):
            self.s.start_backfill("2026-06-01", 1780000000000)           # 啟動後固定
        self.s.update_backfill(next_cursor="3", completed=False)
        st = self.s.get_backfill_state()
        self.assertEqual((st["next_cursor"], st["completed"], st["cutoff_date"]), ("3", 0, "2026-05-15"))
        self.s.update_backfill(completed=True)
        self.assertEqual(self.s.get_backfill_state()["completed"], 1)
        with self.assertRaises(ValueError):
            self.s.widen_cutoff("2026-06-01", 1780000000000)             # 往後＝拒絕
        with self.assertRaises(ValueError):
            self.s.widen_cutoff("2026-05-15", 1778774400000)             # 相同＝拒絕
        self.s.widen_cutoff("2026-02-15", 1771084800000)
        st = self.s.get_backfill_state()
        self.assertEqual((st["cutoff_date"], st["completed"], st["next_cursor"]), ("2026-02-15", 0, None))

    def test_update_backfill_before_start_rejected(self):
        with self.assertRaises(ValueError):
            self.s.update_backfill(completed=True)
        with self.assertRaises(ValueError):
            self.s.widen_cutoff("2026-01-01", 1)

    def test_settings_default_set_overwrite_and_persist(self):
        self.assertIsNone(self.s.get_setting("transcribe_enabled"))
        self.assertEqual(self.s.get_setting("transcribe_enabled", "0"), "0")
        self.s.set_setting("transcribe_enabled", 1)
        self.assertEqual(self.s.get_setting("transcribe_enabled"), "1")
        self.s.set_setting("transcribe_enabled", 0)
        self.assertEqual(self.s.get_setting("transcribe_enabled"), "0")
        s2 = A.ArticleStore(self.tmp)
        self.addCleanup(s2.close)
        self.assertEqual(s2.get_setting("transcribe_enabled"), "0")


class RunsAndAlertsTest(Base):
    def test_logins_today_counts_started_logins_even_if_run_never_finished(self):
        r1 = self.s.start_run("mail")
        self.assertEqual(self.s.logins_today(T(15)), 0)           # 還沒開始登入
        self.s.mark_login_started(r1)                              # 當機也已計入
        self.assertEqual(self.s.logins_today(T(15)), 1)
        r2 = self.s.start_run("none")
        self.s.finish_run(r2, False, 0, 0, "ok", None)
        self.assertEqual(self.s.logins_today(T(15)), 1)

    def test_failed_login_attempt_still_counts_and_finish_run_cannot_lower_it(self):
        r = self.s.start_run("mail")
        self.s.mark_login_started(r)
        self.s.finish_run(r, False, 0, 0, "login_failed", None)       # 密碼錯：有嘗試但失敗
        row = self.s.recent_runs(1)[0]
        self.assertEqual((row["logged_in"], row["login_ok"]), (1, 0))
        self.assertEqual(self.s.logins_today(T(15)), 1)
        r2 = self.s.start_run("mail")
        self.s.mark_login_started(r2)
        self.s.finish_run(r2, True, 1, 1, "ok", True)
        self.assertEqual(self.s.recent_runs(1)[0]["login_ok"], 1)
        self.assertEqual(self.s.logins_today(T(15)), 2)
        r3 = self.s.start_run("none")
        self.s.finish_run(r3, None, 0, 0, "ok", None)                  # 沒嘗試登入
        row3 = self.s.recent_runs(1)[0]
        self.assertEqual((row3["logged_in"], row3["login_ok"]), (0, None))

    def test_old_table_without_login_ok_is_migrated(self):
        import sqlite3
        tmp = tempfile.mkdtemp(prefix="articles-old-")
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = sqlite3.connect(os.path.join(tmp, "articles.db"))
        conn.execute("CREATE TABLE import_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, "
                     "finished_at TEXT, trigger TEXT NOT NULL, logged_in INTEGER NOT NULL DEFAULT 0, "
                     "articles_attempted INTEGER NOT NULL DEFAULT 0, articles_fetched INTEGER NOT NULL DEFAULT 0, "
                     "result TEXT, logged_out INTEGER, blocked_until TEXT)")
        conn.commit()
        conn.close()
        s2 = A.ArticleStore(tmp)
        self.addCleanup(s2.close)
        self.assertIn("login_ok", [r[1] for r in s2.conn.execute("PRAGMA table_info(import_runs)")])

    def test_old_article_image_without_transcribe_attempts_is_migrated(self):
        import sqlite3
        tmp = tempfile.mkdtemp(prefix="articles-old-")
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = sqlite3.connect(os.path.join(tmp, "articles.db"))
        conn.execute("CREATE TABLE article_image (id INTEGER PRIMARY KEY AUTOINCREMENT, article_id INTEGER NOT NULL, "
                     "seq INTEGER NOT NULL, src_url TEXT, file_path TEXT, is_table INTEGER, "
                     "transcription_status TEXT NOT NULL DEFAULT 'untranscribed', transcription TEXT, "
                     "transcribed_model TEXT, UNIQUE(article_id, seq))")
        conn.execute("INSERT INTO article_image (article_id, seq) VALUES (7, 1)")
        conn.commit()
        conn.close()
        s2 = A.ArticleStore(tmp)
        self.addCleanup(s2.close)
        self.assertIn("transcribe_attempts", [r[1] for r in s2.conn.execute("PRAGMA table_info(article_image)")])
        self.assertEqual(s2.conn.execute("SELECT transcribe_attempts FROM article_image").fetchone()[0], 0)
        A.ArticleStore(tmp).close()                                    # 再開一次不會重複 ALTER 而出錯

    def test_transcription_counts_only_fetched_articles(self):
        self.assertEqual(self.s.transcription_counts(), {"untranscribed": 0, "exhausted": 0})
        self.add(1)
        self.s.mark_fetched(1, "內文。" * 100)
        self.add(2)                                                    # 未 fetched：不計
        for aid in (1, 2):
            for seq in (1, 2):
                self.s.add_image(aid, seq, "http://x/%d-%d.png" % (aid, seq))
                self.s.set_image_file(aid, seq, "f/%d-%d.png" % (aid, seq))
        self.s.set_transcription(1, 2, "not_table", is_table=False)    # 已處理：不計
        for _ in range(A.MAX_TRANSCRIBE_ATTEMPTS):
            self.s.bump_transcribe_attempts(1, 1)
        self.assertEqual(self.s.transcription_counts(), {"untranscribed": 1, "exhausted": 1})
        self.s.reset_transcribe_attempts()
        self.assertEqual(self.s.transcription_counts(), {"untranscribed": 1, "exhausted": 0})

    def test_logins_today_uses_taipei_date_boundaries(self):
        self.clock[0] = T(15, 23, 0)
        r = self.s.start_run("mail")
        self.s.mark_login_started(r)
        self.assertEqual(self.s.logins_today(T(15, 23, 59)), 1)
        self.assertEqual(self.s.logins_today(T(16, 0, 30)), 0)    # 隔天
        utc_view = datetime.datetime(2026, 11, 15, 16, 30, tzinfo=datetime.timezone.utc)  # = 台北 16 日 00:30
        self.assertEqual(self.s.logins_today(utc_view), 0)

    def test_blocked_until_returns_latest(self):
        self.assertIsNone(self.s.blocked_until())
        r1 = self.s.start_run("mail")
        self.s.finish_run(r1, True, 0, 0, "blocked", True, blocked_until=T(16, 23))
        r2 = self.s.start_run("mail")
        self.s.finish_run(r2, True, 0, 0, "blocked", True, blocked_until=T(18, 23))
        self.assertEqual(self.s.blocked_until(), T(18, 23))

    def test_last_weekly_check_only_counts_successful_login_that_read_the_list(self):
        self.assertIsNone(self.s.last_weekly_check())
        self.clock[0] = T(8)
        r = self.s.start_run("weekly")
        self.s.mark_login_started(r)
        self.s.finish_run(r, True, 0, 0, "ok", True, list_pages=1)
        self.clock[0] = T(10)
        r2 = self.s.start_run("mail")                              # 非 weekly 觸發 → 不算
        self.s.mark_login_started(r2)
        self.s.finish_run(r2, True, 0, 0, "ok", True, list_pages=1)
        self.clock[0] = T(12)
        self.s.start_run("weekly")                                 # 沒登入 → 不算
        self.assertEqual(self.s.last_weekly_check(), T(8))
        self.clock[0] = T(14)
        r4 = self.s.start_run("weekly")                            # 已嘗試登入但失敗 → 不算
        self.s.mark_login_started(r4)
        self.s.finish_run(r4, False, 0, 0, "login_failed", True)
        self.clock[0] = T(15)
        r5 = self.s.start_run("weekly")                            # 登入成功但被擋、沒讀到清單 → 不算
        self.s.mark_login_started(r5)
        self.s.finish_run(r5, True, 0, 0, "blocked", True, list_pages=0)
        self.assertEqual(self.s.last_weekly_check(), T(8))
        self.clock[0] = T(16)
        r6 = self.s.start_run("mail+weekly")                       # 成功且讀到清單 → 算
        self.s.mark_login_started(r6)
        self.s.finish_run(r6, True, 0, 0, "ok", True, list_pages=3)
        self.assertEqual(self.s.last_weekly_check(), T(16))

    def test_old_import_runs_table_gets_list_pages_column(self):
        import sqlite3
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        conn = sqlite3.connect(os.path.join(d, A.DB_FILENAME))
        conn.execute("CREATE TABLE import_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, "
                     "finished_at TEXT, trigger TEXT NOT NULL, logged_in INTEGER NOT NULL DEFAULT 0, "
                     "articles_attempted INTEGER NOT NULL DEFAULT 0, articles_fetched INTEGER NOT NULL DEFAULT 0, "
                     "result TEXT, logged_out INTEGER, blocked_until TEXT)")
        conn.commit()
        conn.close()
        s = A.ArticleStore(d)
        self.addCleanup(s.close)
        cols = [r[1] for r in s.conn.execute("PRAGMA table_info(import_runs)")]
        self.assertIn("list_pages", cols)
        self.assertIsNone(s.last_weekly_check())

    def test_unverified_logout_runs(self):
        a = self.s.start_run("mail")
        self.s.finish_run(a, True, 1, 1, "ok", True)
        b = self.s.start_run("mail")
        self.s.finish_run(b, True, 1, 0, "partial", False)
        c = self.s.start_run("none")
        self.s.finish_run(c, False, 0, 0, "ok", None)
        d = self.s.start_run("mail")
        self.s.mark_login_started(d)                               # 進行中：logged_out 為 NULL
        self.assertEqual([r["id"] for r in self.s.unverified_logout_runs()], [b])

    def test_alert_once_same_kind_key_day(self):
        self.assertTrue(self.s.alert_once("login_failed", "x", day="2026-11-15"))
        self.assertFalse(self.s.alert_once("login_failed", "x", day="2026-11-15"))
        self.assertTrue(self.s.alert_once("login_failed", "x", day="2026-11-16"))
        self.assertTrue(self.s.alert_once("blocked", "x", day="2026-11-15"))
        self.assertTrue(self.s.alert_once("new", "a"))             # 預設為今天（台北）
        self.assertFalse(self.s.alert_once("new", "a"))

    def test_recent_runs_order(self):
        for _ in range(3):
            self.s.start_run("none")
        self.assertEqual([r["id"] for r in self.s.recent_runs(2)], [3, 2])


if __name__ == "__main__":
    unittest.main()
