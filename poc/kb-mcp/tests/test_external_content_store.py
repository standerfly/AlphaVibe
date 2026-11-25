"""T007（基礎部分）：ExternalContentStore——schema、open_readonly、_tx 回滾、約束。"""
import datetime
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import external_content_store as S  # noqa: E402

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 25, 12, 0, tzinfo=UTC)

INSERT_CONTENT = ("INSERT INTO content (source_key, source_type, url, title, author, published_on, body, "
                  "body_sha256, guid, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)")


def row(key="youtube:AAAAAAAAAAA", source_type="youtube", published_on="2026-11-19", body="全文內容", title="標題"):
    return (key, source_type, "https://youtu.be/AAAAAAAAAAA", title, "頻道", published_on, body,
            "h" * 64, None, T0.isoformat(), T0.isoformat())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="extcontent-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = [T0]
        self.s = S.ExternalContentStore(self.tmp, now=lambda: self.clock[0])
        self.addCleanup(self.s.close)

    def count(self, table):
        return self.s.conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


class SchemaTest(Base):
    def test_constructor_creates_three_tables_and_writes_no_rows(self):
        names = set(r[0] for r in self.s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        for t in ("content", "summary", "audit_log"):
            self.assertIn(t, names)
            self.assertEqual(self.count(t), 0, t)

    def test_db_file_name_and_reopen_has_no_side_effects(self):
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "external_content.db")))
        s2 = S.ExternalContentStore(self.tmp)
        self.addCleanup(s2.close)
        for t in ("content", "summary", "audit_log"):
            self.assertEqual(s2.conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0], 0)

    def test_columns_per_data_model(self):
        cols = lambda t: [r[1] for r in self.s.conn.execute("PRAGMA table_info(%s)" % t)]
        self.assertEqual(cols("content"), ["id", "source_key", "source_type", "url", "title", "author",
                                           "published_on", "body", "body_sha256", "guid", "created_at",
                                           "updated_at", "deleted_at"])
        self.assertEqual(cols("summary"), ["id", "content_id", "text", "status", "confirmed_at", "po_quote"])
        self.assertEqual(cols("audit_log"), ["id", "ts", "channel", "action", "content_id", "detail"])

    def test_indexes(self):
        idx = set(r[1] for r in self.s.conn.execute("PRAGMA index_list(content)"))
        joined = " ".join(idx)
        self.assertIn("body_sha256", joined)
        self.assertIn("published_on", joined)
        uniq = [r[1] for r in self.s.conn.execute("PRAGMA index_list(content)") if r[2]]
        self.assertTrue(uniq)     # source_key 的 UNIQUE 自動索引

    def test_fulltext_and_created_at_are_preserved(self):
        body = "全文" * 1000
        self.s.conn.execute(INSERT_CONTENT, row(body=body))
        self.s.conn.commit()
        r = self.s.conn.execute("SELECT body, created_at, deleted_at FROM content").fetchone()
        self.assertEqual(r["body"], body)
        self.assertEqual(r["created_at"], T0.isoformat())
        self.assertIsNone(r["deleted_at"])


class ConstraintTest(Base):
    def insert(self, **kw):
        with self.s._tx() as c:
            c.execute(INSERT_CONTENT, row(**kw))

    def test_source_key_unique(self):
        self.insert()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert()
        self.assertEqual(self.count("content"), 1)

    def test_source_type_check(self):
        for bad in ("video", "", "YouTube"):
            with self.assertRaises(sqlite3.IntegrityError, msg=bad):
                self.insert(key="k-" + bad, source_type=bad)
        for good in S.SOURCE_TYPES:
            self.insert(key="k-" + good, source_type=good)
        self.assertEqual(self.count("content"), 3)

    def test_published_on_shape_check(self):
        for bad in ("2026/11/19", "20261119", "2026-1-9", "11-19-2026", "", "2026-11-19T00:00", "abcd-ef-gh"):
            with self.assertRaises(sqlite3.IntegrityError, msg=bad):
                self.insert(key="k-" + bad, published_on=bad)
        self.insert(key="ok", published_on="2026-11-19")
        self.assertEqual(self.count("content"), 1)

    def test_blank_body_and_title_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(key="a", body="  \n\t ")
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(key="b", title="")

    def test_summary_status_check(self):
        self.insert()
        ok = "INSERT INTO summary (content_id, text, status, confirmed_at, po_quote) VALUES (1,'s',?,?,?)"
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.conn.execute(ok, ("draft", T0.isoformat(), "好"))
        self.s.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.conn.execute(ok, ("confirmed", T0.isoformat(), " "))
        self.s.conn.rollback()
        self.s.conn.execute(ok, ("confirmed", T0.isoformat(), "好"))
        self.s.conn.commit()
        self.assertEqual(self.count("summary"), 1)


class TxTest(Base):
    def test_commit_writes_data_and_audit_together(self):
        with self.s._tx() as c:
            c.execute(INSERT_CONTENT, row())
            self.s._audit("import", 1, "stdio", {"source_key": "youtube:AAAAAAAAAAA", "title": "標題"})
        self.assertEqual(self.count("content"), 1)
        a = self.s.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((a["action"], a["content_id"], a["channel"]), ("import", 1, "stdio"))
        self.assertEqual(a["ts"], T0.isoformat())
        self.assertIn("標題", a["detail"])      # ensure_ascii=False
        self.assertFalse(self.s.conn.in_transaction)

    def test_exception_mid_transaction_rolls_back_everything_and_reraises(self):
        class Boom(Exception):
            pass
        with self.assertRaises(Boom):
            with self.s._tx() as c:
                c.execute(INSERT_CONTENT, row())
                self.s._audit("import", 1, "http", {"k": "v"})
                raise Boom()
        self.assertEqual(self.count("content"), 0)
        self.assertEqual(self.count("audit_log"), 0)
        self.assertFalse(self.s.conn.in_transaction)
        with self.s._tx() as c:        # 之後仍可正常寫入（鎖已釋放）
            c.execute(INSERT_CONTENT, row())
        self.assertEqual(self.count("content"), 1)

    def test_integrity_error_in_second_statement_rolls_back_first(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s._tx() as c:
                c.execute(INSERT_CONTENT, row(key="a"))
                self.s._audit("import", 1, "stdio", {})
                c.execute(INSERT_CONTENT, row(key="b", source_type="bogus"))
        self.assertEqual(self.count("content"), 0)
        self.assertEqual(self.count("audit_log"), 0)

    def test_audit_outside_tx_refused(self):
        with self.assertRaises(RuntimeError):
            self.s._audit("import", 1, "stdio", {})
        self.assertEqual(self.count("audit_log"), 0)

    def test_audit_constraints(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s._tx():
                self.s._audit("bogus_action", 1, "stdio", {})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s._tx():
                self.s._audit("import", 1, "carrier-pigeon", {})
        self.assertEqual(self.count("audit_log"), 0)

    def test_nested_tx_refused(self):
        with self.s._tx():
            with self.assertRaises(RuntimeError):
                with self.s._tx():
                    pass


class ReadonlyTest(Base):
    def test_missing_db_raises_and_creates_nothing(self):
        empty = tempfile.mkdtemp(prefix="extcontent-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(FileNotFoundError):
            S.ExternalContentStore.open_readonly(empty)
        self.assertEqual(os.listdir(empty), [])
        missing_dir = os.path.join(empty, "nope")
        with self.assertRaises(FileNotFoundError):
            S.ExternalContentStore.open_readonly(missing_dir)
        self.assertFalse(os.path.exists(missing_dir))

    def test_readonly_reads_but_cannot_write(self):
        with self.s._tx() as c:
            c.execute(INSERT_CONTENT, row())
        ro = S.ExternalContentStore.open_readonly(self.tmp)
        self.addCleanup(ro.close)
        self.assertEqual(ro.conn.execute("SELECT COUNT(*) FROM content").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            ro.conn.execute(INSERT_CONTENT, row(key="other"))


class ClockTest(Base):
    def test_default_clock_is_aware_utc(self):
        d = tempfile.mkdtemp(prefix="extcontent-clock-")
        self.addCleanup(shutil.rmtree, d, True)
        s = S.ExternalContentStore(d)
        self.addCleanup(s.close)
        self.assertIsNotNone(s.now().tzinfo)
        self.assertTrue(s.now_iso().endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
