"""T005：`substack_store.SubstackStore` 的 schema、交易與原子性（011 data-model §1、research R8）。

涵蓋：建表與索引、建構子零副作用、連線設定、顯式交易、FR-009 回滾與磁碟滿、
去重（含 dedupe_conflict 只回傳不入庫）、不覆寫的靜態守門、唯讀開庫、空間現況、時區。
一律用獨立 tempfile 資料目錄（realpath），絕不碰 poc/data。
"""
import os
import re
import sqlite3
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_store as S  # noqa: E402

TABLES = ("author", "article", "article_image", "poll_log", "run", "robots_cache",
          "transcription_trial", "image_transcription", "reclassification")
SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "substack_store.py")


def norm(sql):
    return re.sub(r"\s+", " ", (sql or "")).strip().lower()


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)


class SchemaTest(StoreTestBase):
    def test_all_tables_and_view_exist(self):
        names = {r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in TABLES:
            self.assertIn(t, names, "缺少資料表 %s" % t)
        views = {r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")}
        self.assertIn("article_effective", views)

    def test_view_exposes_effective_columns(self):
        cols = [r[1] for r in self.store.conn.execute("PRAGMA table_info(article_effective)")]
        for c in ("effective_completeness", "original_completeness", "reclassified_count",
                  "effective_body_text"):
            self.assertIn(c, cols)

    def test_reclassification_has_derived_body_text(self):
        cols = [r[1] for r in self.store.conn.execute("PRAGMA table_info(reclassification)")]
        for c in ("article_id", "at", "trigger", "old_completeness", "new_completeness",
                  "new_reason", "rule_version", "derived_body_text", "changed", "run_id"):
            self.assertIn(c, cols)

    def test_required_indexes(self):
        sqls = [norm(r[0]) for r in self.store.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")]
        blob = " || ".join(sqls)
        self.assertIn("unique index", blob)
        want = [
            ("unique", "on article(guid)", "where guid is not null"),
            ("unique", "on article(link_norm)", None),
            ("", "on article(author_key, published_at)", None),
            ("", "on article(fetched_at)", None),
            ("unique", "on article_image(article_id, seq)", None),
            ("unique", "on image_transcription(image_id, trial_id)", None),
            ("", "on reclassification(article_id, id)", None),
        ]
        for uniq, on_part, where_part in want:
            hits = [s for s in sqls if on_part in s]
            self.assertTrue(hits, "缺少索引 %s" % on_part)
            if uniq:
                self.assertTrue(any("unique index" in h for h in hits),
                                "%s 應為 UNIQUE" % on_part)
            if where_part:
                self.assertTrue(any(where_part in h for h in hits),
                                "%s 應為部分索引 %s" % (on_part, where_part))

    def test_unique_constraints_enforced(self):
        row = F.article_row()
        self.assertTrue(self.store.insert_article_with_images(row, []))
        dup_guid = F.article_row(guid=row["guid"])
        with self.store.transaction():
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.insert_article_row(dup_guid)
        dup_link = F.article_row(link_norm=row["link_norm"])
        with self.store.transaction():
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.insert_article_row(dup_link)

    def test_constructor_writes_no_rows(self):
        for t in TABLES:
            n = self.store.conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            self.assertEqual(n, 0, "建構子不該往 %s 寫資料" % t)

    def test_connection_settings(self):
        self.assertIsNone(self.store.conn.isolation_level)
        self.assertEqual(
            self.store.conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        mode = self.store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertNotEqual(str(mode).lower(), "wal")

    def test_connection_usable_from_another_thread(self):
        """check_same_thread=False 的行為證明（另一條 thread 查詢不丟 ProgrammingError）。"""
        box = {}

        def work():
            try:
                box["n"] = self.store.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
            except Exception as e:      # noqa: BLE001
                box["err"] = e
        t = threading.Thread(target=work)
        t.start()
        t.join()
        self.assertNotIn("err", box, "跨 thread 查詢失敗：%s" % box.get("err"))
        self.assertEqual(box["n"], 0)

    def test_timestamps_carry_taipei_offset(self):
        run_id = self.store.start_run("manual")
        started = self.store.conn.execute("SELECT started_at FROM run WHERE id=?",
                                          (run_id,)).fetchone()[0]
        self.assertTrue(started.endswith("+08:00"), started)
        self.store.finish_run(run_id, result="ok")
        finished = self.store.conn.execute("SELECT finished_at FROM run WHERE id=?",
                                           (run_id,)).fetchone()[0]
        self.assertTrue(finished.endswith("+08:00"), finished)
        aid = self.store.insert_article_with_images(F.article_row(), [])
        self.store.add_reclassification(article_id=aid, trigger="po_article", old_completeness="F",
                                        new_completeness="F", new_reason="text_ge_200",
                                        rule_version="t", run_id=run_id)
        at = self.store.conn.execute("SELECT at FROM reclassification").fetchone()[0]
        self.assertTrue(at.endswith("+08:00"), at)


class TransactionTest(StoreTestBase):
    def test_commit_and_rollback_semantics(self):
        self.assertFalse(self.store.conn.in_transaction)
        with self.store.transaction():
            self.assertTrue(self.store.conn.in_transaction)
            self.store.insert_article_row(F.article_row())
        self.assertFalse(self.store.conn.in_transaction)
        self.assertEqual(self._count("article"), 1)

        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.insert_article_row(F.article_row())
                raise RuntimeError("注入的例外")
        self.assertFalse(self.store.conn.in_transaction)
        self.assertEqual(self._count("article"), 1, "例外後必須回滾")

    def test_disk_full_becomes_disk_full_error(self):
        with self.assertRaises(S.DiskFullError):
            with self.store.transaction():
                self.store.insert_article_row(F.article_row())
                raise sqlite3.OperationalError("database or disk is full")
        self.assertEqual(self._count("article"), 0)
        self.assertFalse(self.store.conn.in_transaction)

    def test_rollback_when_images_fail(self):
        """FR-009 (a)：文章列已寫、圖片列寫入前出錯 → 兩表皆無該篇。"""
        def boom(*a, **k):
            raise RuntimeError("圖片列寫入失敗")
        self.store._insert_image_rows = boom
        with self.assertRaises(RuntimeError):
            self.store.insert_article_with_images(F.article_row(), F.image_rows(2))
        self.assertEqual(self._count("article"), 0)
        self.assertEqual(self._count("article_image"), 0)

    def test_disk_full_during_images_rolls_back(self):
        """FR-009 (c)：磁碟滿 → 回滾並轉成 DiskFullError，不留半寫入。"""
        def boom(*a, **k):
            raise sqlite3.OperationalError("database or disk is full")
        self.store._insert_image_rows = boom
        with self.assertRaises(S.DiskFullError):
            self.store.insert_article_with_images(F.article_row(), F.image_rows(1))
        self.assertEqual(self._count("article"), 0)
        self.assertEqual(self._count("article_image"), 0)

    def test_successful_insert_writes_article_and_images_together(self):
        aid = self.store.insert_article_with_images(F.article_row(), F.image_rows(3))
        self.assertTrue(aid)
        self.assertEqual(self._count("article"), 1)
        rows = self.store.list_images(aid)
        self.assertEqual([r["seq"] for r in rows], [1, 2, 3])
        self.assertEqual({r["status"] for r in rows}, {"pending"})
        self.assertEqual({r["fail_count"] for r in rows}, {0})

    def test_non_text_article_must_have_null_body(self):
        aid = self.store.insert_article_with_images(
            F.article_row(completeness="N", classify_reason="text_lt_200", body_text=None), [])
        body = self.store.conn.execute("SELECT body_text FROM article WHERE id=?",
                                       (aid,)).fetchone()[0]
        self.assertIsNone(body)
        with self.assertRaises(ValueError):
            self.store.insert_article_with_images(
                F.article_row(completeness="N", classify_reason="text_lt_200",
                              body_text="不該存的內文"), [])
        with self.assertRaises(ValueError):
            self.store.insert_article_with_images(
                F.article_row(completeness="F", classify_reason="text_ge_200", body_text=None), [])
        with self.assertRaises(ValueError):
            self.store.insert_article_with_images(
                F.article_row(completeness="F", classify_reason="uncertain:parse_error"), [])

    def _count(self, table):
        return self.store.conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


class DedupeTest(StoreTestBase):
    def test_same_guid_or_link_is_duplicate_and_not_overwritten(self):
        first = F.article_row()
        aid = self.store.insert_article_with_images(first, [])
        before = self.store.conn.execute("SELECT * FROM article WHERE id=?", (aid,)).fetchone()

        same_guid = F.article_row(guid=first["guid"], title="別的標題", body_text=F.filler(500))
        self.assertIsNone(self.store.insert_article_with_images(same_guid, []))
        same_link = F.article_row(link_norm=first["link_norm"], title="又一個標題")
        self.assertIsNone(self.store.insert_article_with_images(same_link, []))

        after = self.store.conn.execute("SELECT * FROM article WHERE id=?", (aid,)).fetchone()
        self.assertEqual(tuple(before), tuple(after), "已存文章不得被覆寫")
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0], 1)

    def test_find_duplicate_distinguishes_conflict(self):
        a = self.store.insert_article_with_images(F.article_row(), [])
        b = self.store.insert_article_with_images(F.article_row(), [])
        rows = {r["id"]: r for r in self.store.conn.execute("SELECT * FROM article")}

        self.assertIsNone(self.store.find_duplicate("沒見過的guid", "https://x/none"))

        hit = self.store.find_duplicate(rows[a]["guid"], "https://x/none")
        self.assertEqual(hit["kind"], "duplicate")
        self.assertEqual(hit["article_id"], a)

        hit = self.store.find_duplicate("沒見過的guid", rows[b]["link_norm"])
        self.assertEqual(hit["kind"], "duplicate")
        self.assertEqual(hit["article_id"], b)

        conflict = self.store.find_duplicate(rows[a]["guid"], rows[b]["link_norm"])
        self.assertEqual(conflict["kind"], "dedupe_conflict")
        self.assertEqual({conflict["guid_article_id"], conflict["link_article_id"]}, {a, b})
        self.assertIsNone(self.store.insert_article_with_images(
            F.article_row(guid=rows[a]["guid"], link_norm=rows[b]["link_norm"]), []))

    def test_no_dedupe_counter_columns_in_db(self):
        """dedupe_conflict 只印 stdout／日誌，不入庫（已決定事項 #4）。"""
        for table in ("run", "poll_log", "article"):
            cols = [r[1].lower() for r in self.store.conn.execute("PRAGMA table_info(%s)" % table)]
            for c in cols:
                self.assertNotIn("dedupe", c, "%s.%s 不該存在" % (table, c))
                self.assertNotIn("conflict", c, "%s.%s 不該存在" % (table, c))


class StaticGuardTest(unittest.TestCase):
    """FR-007／FR-033 的原始碼守門：不得有覆寫既有文章或改寫重判歷史的路徑。"""

    def setUp(self):
        with open(os.path.realpath(SOURCE), encoding="utf-8") as f:
            self.src = f.read()

    def test_update_article_only_touches_notify_columns(self):
        allowed = {"notify_status", "notify_attempts", "notified_at"}
        found = 0
        for m in re.finditer(r"UPDATE\s+article\s+SET\s+(.*?)(?:\s+WHERE|\"|')",
                             self.src, re.S | re.I):
            found += 1
            cols = {c.lower() for c in re.findall(r"(\w+)\s*=", m.group(1))}
            self.assertTrue(cols.issubset(allowed),
                            "UPDATE article SET 只允許通知欄位，實際：%s" % sorted(cols))
        self.assertGreater(found, 0, "預期至少有一處通知狀態的 UPDATE")

    def test_no_update_or_delete_on_reclassification(self):
        self.assertIsNone(re.search(r"UPDATE\s+reclassification", self.src, re.I))
        self.assertIsNone(re.search(r"DELETE\s+FROM\s+reclassification", self.src, re.I))

    def test_no_delete_on_article_tables(self):
        for t in ("article", "article_image"):
            self.assertIsNone(re.search(r"DELETE\s+FROM\s+%s\b" % t, self.src, re.I),
                              "%s 不該有 DELETE 路徑" % t)


class ReadOnlyTest(StoreTestBase):
    def test_open_readonly_does_not_create_or_modify(self):
        self.store.insert_article_with_images(F.article_row(), [])
        path = os.path.join(self.dir, S.DB_FILENAME)
        before = os.path.getsize(path)
        ro = S.SubstackStore.open_readonly(self.dir)
        self.addCleanup(ro.close)
        n = ro.conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
        self.assertEqual(n, 1)
        with self.assertRaises(sqlite3.OperationalError):
            ro.conn.execute("INSERT INTO run(trigger) VALUES ('manual')")
        self.assertEqual(os.path.getsize(path), before)

    def test_open_readonly_missing_db_raises_and_creates_nothing(self):
        empty = F.temp_data_dir(self)
        with self.assertRaises(FileNotFoundError):
            S.SubstackStore.open_readonly(empty)
        self.assertEqual(os.listdir(empty), [])


class SpaceTest(StoreTestBase):
    def test_space_status_and_line(self):
        os.makedirs(os.path.join(self.dir, "substack_images", "1"))
        with open(os.path.join(self.dir, "substack_images", "1", "1.jpg"), "wb") as f:
            f.write(b"x" * 2048)
        st = S.space_status(self.dir)
        self.assertGreater(st["free_gb"], 0)
        self.assertGreaterEqual(st["db_mb"], 0)
        self.assertGreaterEqual(st["images_mb"], 0)
        line = S.format_space_line(self.dir)
        self.assertRegex(
            line, r"^空間：剩餘 [0-9.]+ GB；substack\.db [0-9.]+ MB；圖片 [0-9.]+ MB$")

    def test_space_line_unavailable(self):
        missing = os.path.join(self.dir, "不存在的目錄")
        self.assertEqual(S.format_space_line(missing), "空間：無法取得")


if __name__ == "__main__":
    unittest.main()
