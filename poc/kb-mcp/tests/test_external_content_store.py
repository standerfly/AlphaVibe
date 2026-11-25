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


class AddContentTest(Base):
    def add(self, **kw):
        args = dict(source_type="youtube", url="https://www.youtube.com/watch?v=AAAAAAAAAAA", title="標題",
                    author="頻道", published_on="2026-11-19", body="逐字稿全文內容 SECRETBODY")
        args.update(kw)
        return self.s.add_content(**args)

    def test_import_success_writes_content_and_audit(self):
        r = self.add(channel="http", filename="a.md")
        self.assertEqual(r["status"], "imported")
        self.assertEqual(r["source_key"], "youtube:AAAAAAAAAAA")
        self.assertEqual(r["same_body_elsewhere"], [])
        self.assertEqual(self.count("content"), 1)
        a = self.s.conn.execute("SELECT * FROM audit_log").fetchall()
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["action"], a[0]["channel"], a[0]["content_id"]), ("import", "http", r["id"]))
        self.assertIn("a.md", a[0]["detail"])
        self.assertIn("youtube:AAAAAAAAAAA", a[0]["detail"])
        self.assertNotIn("SECRETBODY", a[0]["detail"])
        self.assertNotIn("逐字稿", a[0]["detail"])
        self.assertEqual(self.s.find_by_source_key("youtube:AAAAAAAAAAA")["id"], r["id"])
        self.assertIsNone(self.s.find_by_source_key("youtube:BBBBBBBBBBB"))

    def test_duplicate_returns_existing_without_writing(self):
        first = self.add()
        r = self.add(url="https://youtu.be/AAAAAAAAAAA?t=9", body="另一份內文")
        self.assertEqual(r["status"], "duplicate")
        self.assertEqual(r["existing"]["id"], first["id"])
        self.assertEqual(self.count("content"), 1)
        self.assertEqual(self.count("audit_log"), 1)

    def test_duplicate_checked_before_empty_body(self):
        self.add()
        r = self.add(body="   ")
        self.assertEqual(r["status"], "duplicate")

    def test_empty_body_variants_rejected_and_nothing_written(self):
        for b in ("", "  \n\t", "\u3000\u3000", None):
            with self.assertRaises(S.ContentValidationError, msg=repr(b)) as cm:
                self.add(body=b)
            self.assertIn("內文為空", str(cm.exception))
        self.assertEqual(self.count("content"), 0)
        self.assertEqual(self.count("audit_log"), 0)

    def test_validation_errors(self):
        cases = (dict(source_type="blog"), dict(title="  "), dict(author=""), dict(url=""),
                 dict(published_on="2026-02-30"), dict(published_on="20261119"),
                 dict(published_on="2026/11/19"), dict(channel="smtp"),
                 dict(url="ftp://x.com/a"), dict(url="https://www.youtube.com/watch?v=short"))
        for kw in cases:
            with self.assertRaises(S.ContentValidationError, msg=str(kw)):
                self.add(**kw)
        self.assertEqual(self.count("content"), 0)

    def test_same_body_elsewhere_warning(self):
        a = self.add(body="一模一樣 的內文")
        b = self.add(url="https://www.youtube.com/watch?v=BBBBBBBBBBB", title="另一支", body="一模一樣  的內文\n")
        self.assertEqual(b["status"], "imported")
        self.assertEqual(b["same_body_elsewhere"], [{"id": a["id"], "title": "標題"}])

    def test_tx_rolls_back_when_audit_fails(self):
        orig = self.s._audit

        def boom(*a, **k):
            raise RuntimeError("audit down")
        self.s._audit = boom
        with self.assertRaises(RuntimeError):
            self.add()
        self.s._audit = orig
        self.assertEqual(self.count("content"), 0)

    def test_guid_normalised(self):
        self.add(source_type="podcast", url="https://example.com/ep1", guid="  g-1  ")
        r = self.s.conn.execute("SELECT guid, source_key FROM content").fetchone()
        self.assertEqual((r["guid"], r["source_key"]), ("g-1", "podcast:guid:g-1"))


class SearchTest(Base):
    n = 0

    def add(self, body="內文", title="標題", published_on="2026-11-19", source_type="article", **kw):
        SearchTest.n += 1
        return self.s.add_content(source_type=source_type, url="https://example.com/p%d" % SearchTest.n,
                                  title=title, author="作者", published_on=published_on, body=body, **kw)["id"]

    def ids(self, q, **kw):
        return [h["id"] for h in self.s.search(q, **kw)]

    def test_like_wildcards_are_literal(self):
        a = self.add(body="漲幅達 100% 以上")
        b = self.add(body="變數 a_b 與 axb")
        c = self.add(body=r"路徑 C:\\temp\\x")
        self.add(body="100 元沒有百分號")
        self.assertEqual(self.ids("100%"), [a])
        self.assertEqual(self.ids("a_b"), [b])
        self.assertEqual(self.ids("\\temp"), [c])
        self.assertEqual(self.ids("%"), [a])
        self.assertEqual(self.ids("_"), [b])

    def test_whitespace_and_semantics(self):
        a = self.add(body="財測 上修 毛利")
        self.add(body="財測 下修")
        self.assertEqual(self.ids("財測 毛利"), [a])
        self.assertEqual(self.ids("  財測   毛利 "), [a])
        self.assertEqual(self.ids("財測 毛利 不存在"), [])

    def test_title_also_searched(self):
        a = self.add(title="半導體展望", body="完全無關")
        hit = self.s.search("半導體")[0]
        self.assertEqual(hit["id"], a)
        self.assertEqual(hit["snippets"], [])

    def test_two_char_chinese_terms(self):
        body = "財測上修，毛利改善，產能擴張，客戶拉貨，庫存回補"
        self.add(body=body)
        for t in ("財測", "毛利", "產能", "客戶", "庫存"):
            self.assertEqual(len(self.s.search(t)), 1, t)

    def test_source_type_filter_and_validation(self):
        a = self.add(body="財測", source_type="article")
        b = self.add(body="財測", source_type="podcast")
        self.assertEqual(self.ids("財測", source_type="podcast"), [b])
        self.assertEqual(sorted(self.ids("財測")), [a, b])
        with self.assertRaises(ValueError):
            self.s.search("財測", source_type="tweet")

    def test_empty_query_rejected(self):
        for q in ("", "   ", None):
            with self.assertRaises(ValueError):
                self.s.search(q)

    def test_limit_default_cap_and_nonpositive(self):
        for i in range(35):
            self.add(body="共同關鍵字 %d" % i)
        self.assertEqual(len(self.s.search("共同關鍵字")), 10)
        self.assertEqual(len(self.s.search("共同關鍵字", limit=5)), 5)
        self.assertEqual(len(self.s.search("共同關鍵字", limit=999)), 30)
        self.assertEqual(len(self.s.search("共同關鍵字", limit=0)), 10)    # <=0 回預設
        self.assertEqual(len(self.s.search("共同關鍵字", limit=-3)), 10)
        with self.assertRaises(ValueError):
            self.s.search("共同關鍵字", limit="x")

    def test_snippet_radius_and_max_two(self):
        body = "甲" * 200 + "財測" + "乙" * 200 + "毛利" + "丙" * 200 + "產能" + "丁" * 200
        self.add(body=body)
        hit = self.s.search("財測 毛利 產能")[0]
        self.assertEqual(len(hit["snippets"]), 2)
        s1 = hit["snippets"][0]
        self.assertEqual(s1, "…" + "甲" * 60 + "財測" + "乙" * 60 + "…")

    def test_snippet_no_ellipsis_at_edges_and_overlap_merged(self):
        self.add(body="財測 毛利")
        sn = self.s.search("財測 毛利")[0]["snippets"]
        self.assertEqual(sn, ["財測 毛利"])

    def test_order_newest_first(self):
        a = self.add(body="財測", published_on="2026-01-01")
        b = self.add(body="財測", published_on="2026-06-01")
        c = self.add(body="財測", published_on="2026-03-01")
        self.assertEqual(self.ids("財測"), [b, c, a])

    def test_soft_deleted_excluded(self):
        a = self.add(body="財測")
        b = self.add(body="財測")
        self.s.conn.execute("UPDATE content SET deleted_at = ? WHERE id = ?", ("2026-11-26T00:00:00+00:00", a))
        self.s.conn.commit()
        self.assertEqual(self.ids("財測"), [b])
        self.assertIsNone(self.s.get(a))

    def test_result_fields_and_confirmed_summaries(self):
        a = self.add(body="財測 內文", title="T")
        for st in ("confirmed", "revoked", "confirmed"):
            self.s.conn.execute("INSERT INTO summary (content_id,text,status,confirmed_at,po_quote) "
                                "VALUES (?,?,?,?,?)", (a, "s", st, "2026-11-26T00:00:00+00:00", "好"))
        self.s.conn.commit()
        h = self.s.search("財測")[0]
        for k in ("id", "source_type", "title", "author", "published_on", "url", "snippets"):
            self.assertIn(k, h)
        self.assertEqual((h["summary_count"], h["summary_ids"]), (2, [1, 3]))

    def test_works_on_readonly_connection(self):
        a = self.add(body="財測")
        ro = S.ExternalContentStore.open_readonly(self.tmp)
        self.addCleanup(ro.close)
        self.assertEqual([h["id"] for h in ro.search("財測")], [a])
        self.assertEqual(ro.get(a)["total_chars"], 2)

    def test_get_range_and_boundaries(self):
        a = self.add(body="0123456789")
        g = self.s.get(a)
        self.assertEqual((g["text"], g["total_chars"], g["offset_beyond_end"]), ("0123456789", 10, False))
        g = self.s.get(a, offset=2, length=3)
        self.assertEqual((g["text"], g["offset"], g["end"], g["returned_chars"]), ("234", 2, 5, 3))
        self.assertEqual(self.s.get(a, offset=8, length=99)["text"], "89")
        self.assertEqual(self.s.get(a, length=0)["text"], "")
        g = self.s.get(a, offset=10)
        self.assertEqual((g["text"], g["offset_beyond_end"]), ("", True))
        self.assertEqual(self.s.get(a, offset=99)["text"], "")
        for kw in ({"offset": -1}, {"length": -1}, {"offset": 1.5}):
            with self.assertRaises(ValueError):
                self.s.get(a, **kw)
        self.assertIsNone(self.s.get(9999))

    def test_get_summaries_only_confirmed(self):
        a = self.add(body="x")
        for st in ("confirmed", "revoked"):
            self.s.conn.execute("INSERT INTO summary (content_id,text,status,confirmed_at,po_quote) "
                                "VALUES (?,?,?,?,?)", (a, "t-" + st, st, "2026-11-26T00:00:00+00:00", "好"))
        self.s.conn.commit()
        sm = self.s.get(a)["summaries"]
        self.assertEqual([(x["summary_id"], x["text"]) for x in sm], [(1, "t-confirmed")])
        self.assertIn("confirmed_at", sm[0])


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ US3：摘要（T027）

import json  # noqa: E402

BODY_S = "BODYSENTINEL全文獨特字串"
TEXT_S = "SUMSENTINEL摘要獨特字串"


class SummaryBase(Base):
    def setUp(self):
        Base.setUp(self)
        r = self.s.add_content("youtube", "https://www.youtube.com/watch?v=AAAAAAAAAAA", "標題甲", "頻道",
                               "2026-11-19", "內文 " + BODY_S)
        self.cid = r["id"]
        r2 = self.s.add_content("youtube", "https://www.youtube.com/watch?v=BBBBBBBBBBB", "標題乙", "頻道",
                                "2026-11-19", "別篇")
        self.cid2 = r2["id"]

    def summaries(self):
        return [dict(r) for r in self.s.conn.execute("SELECT * FROM summary ORDER BY id")]

    def audits(self, action):
        return [dict(r) for r in self.s.conn.execute(
            "SELECT * FROM audit_log WHERE action = ? ORDER BY id", (action,))]


class AddSummaryTest(SummaryBase):
    def test_success(self):
        self.clock[0] = T0 + datetime.timedelta(hours=1)
        r = self.s.add_summary(self.cid, TEXT_S, "好，存吧", channel="http")
        self.assertEqual(r["summary_id"], 1)
        row_ = self.summaries()[0]
        self.assertEqual((row_["status"], row_["po_quote"], row_["content_id"]), ("confirmed", "好，存吧", self.cid))
        self.assertEqual(row_["confirmed_at"], self.clock[0].isoformat())
        a = self.audits("summary_confirm")
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["channel"], a[0]["content_id"]), ("http", self.cid))
        d = json.loads(a[0]["detail"])
        self.assertEqual(d, {"summary_id": 1, "title": "標題甲", "po_quote": "好，存吧"})
        self.assertNotIn(TEXT_S, a[0]["detail"])
        self.assertNotIn(BODY_S, a[0]["detail"])

    def test_blank_text_or_quote_rejected_including_fullwidth(self):
        for text, quote in (("", "好"), (" \t\n", "好"), ("\u3000", "好"), ("x", ""), ("x", "  "),
                            ("x", "\u3000\u3000"), ("x", None), (None, "好")):
            with self.assertRaises(ValueError, msg=repr((text, quote))):
                self.s.add_summary(self.cid, text, quote)
        self.assertEqual((self.count("summary"), len(self.audits("summary_confirm"))), (0, 0))

    def test_content_missing_or_soft_deleted_rejected(self):
        with self.assertRaises(ValueError):
            self.s.add_summary(999, "x", "好")
        self.s.conn.execute("UPDATE content SET deleted_at = ? WHERE id = ?", (T0.isoformat(), self.cid))
        self.s.conn.commit()
        with self.assertRaises(ValueError):
            self.s.add_summary(self.cid, "x", "好")
        self.assertEqual(self.count("summary"), 0)

    def test_audit_failure_rolls_back_summary(self):
        self.s.conn.execute("DROP TABLE audit_log")
        self.s.conn.commit()
        with self.assertRaises(sqlite3.Error):
            self.s.add_summary(self.cid, "x", "好")
        self.assertEqual(self.count("summary"), 0)

    def test_multiple_coexist_and_visible_in_get(self):
        self.s.add_summary(self.cid, "一", "好")
        self.s.add_summary(self.cid, "二", "好")
        self.assertEqual([x["text"] for x in self.s.get(self.cid)["summaries"]], ["一", "二"])

    def test_soft_deleted_content_hides_summaries_but_keeps_rows(self):
        self.s.add_summary(self.cid, "一", "好")
        self.s.conn.execute("UPDATE content SET deleted_at = ? WHERE id = ?", (T0.isoformat(), self.cid))
        self.s.conn.commit()
        self.assertIsNone(self.s.get(self.cid))
        self.assertEqual(self.s.search("內文"), [])
        self.assertEqual(self.count("summary"), 1)

    def test_no_summary_written_by_add_content(self):
        self.assertEqual(self.count("summary"), 0)


class ReviseRevokeTest(SummaryBase):
    def setUp(self):
        SummaryBase.setUp(self)
        self.sid = self.s.add_summary(self.cid, "舊版", "好")["summary_id"]

    def test_revise_atomic_swap(self):
        r = self.s.revise_summary(self.cid, self.sid, TEXT_S, "改這版", channel="stdio")
        self.assertEqual(r["old_summary_id"], self.sid)
        rows = self.summaries()
        self.assertEqual([(x["status"], x["text"]) for x in rows], [("revoked", "舊版"), ("confirmed", TEXT_S)])
        self.assertEqual(rows[1]["po_quote"], "改這版")
        self.assertEqual([x["text"] for x in self.s.get(self.cid)["summaries"]], [TEXT_S])
        a = self.audits("summary_revise")
        self.assertEqual(len(a), 1)
        d = json.loads(a[0]["detail"])
        self.assertEqual((d["old_summary_id"], d["new_summary_id"], d["title"], d["po_quote"]),
                         (self.sid, r["summary_id"], "標題甲", "改這版"))
        for t in (TEXT_S, "舊版", BODY_S):
            self.assertNotIn(t, a[0]["detail"])

    def test_revise_failure_leaves_old_summary_confirmed(self):
        # 讓「新增」那步失敗：以 trigger 擋 INSERT（舊列的 UPDATE 已先執行，必須被回滾）
        self.s.conn.execute("CREATE TRIGGER no_ins BEFORE INSERT ON summary BEGIN "
                            "SELECT RAISE(ABORT, 'boom'); END")
        self.s.conn.commit()
        with self.assertRaises(sqlite3.Error):
            self.s.revise_summary(self.cid, self.sid, "新", "好")
        self.assertEqual([(x["status"], x["text"]) for x in self.summaries()], [("confirmed", "舊版")])
        self.assertEqual(len(self.audits("summary_revise")), 0)
        self.assertEqual([x["text"] for x in self.s.get(self.cid)["summaries"]], ["舊版"])

    def test_revise_audit_failure_rolls_back_everything(self):
        self.s.conn.execute("DROP TABLE audit_log")
        self.s.conn.commit()
        with self.assertRaises(sqlite3.Error):
            self.s.revise_summary(self.cid, self.sid, "新", "好")
        self.assertEqual([x["status"] for x in self.summaries()], ["confirmed"])

    def test_revise_validation(self):
        for args in ((self.cid, self.sid, "", "好"), (self.cid, self.sid, "新", " \u3000"),
                     (self.cid, 999, "新", "好"), (self.cid2, self.sid, "新", "好"), (999, self.sid, "新", "好"),
                     (self.cid, True, "新", "好")):
            with self.assertRaises(ValueError, msg=repr(args)):
                self.s.revise_summary(*args)
        self.assertEqual([x["status"] for x in self.summaries()], ["confirmed"])

    def test_revoke(self):
        r = self.s.revoke_summary(self.cid, self.sid, "撤回吧", channel="http")
        self.assertEqual(r["summary_id"], self.sid)
        self.assertEqual([x["status"] for x in self.summaries()], ["revoked"])
        self.assertEqual(self.s.get(self.cid)["summaries"], [])
        self.assertEqual(self.s.search("內文")[0]["summary_count"], 0)
        a = self.audits("summary_revoke")
        self.assertEqual((len(a), a[0]["channel"]), (1, "http"))
        d = json.loads(a[0]["detail"])
        self.assertEqual((d["summary_id"], d["title"], d["po_quote"]), (self.sid, "標題甲", "撤回吧"))
        self.assertNotIn("舊版", a[0]["detail"])
        self.assertNotIn(BODY_S, a[0]["detail"])

    def test_revoke_validation(self):
        with self.assertRaises(ValueError):
            self.s.revoke_summary(self.cid2, self.sid, "好")          # 屬於別筆內容
        with self.assertRaises(ValueError):
            self.s.revoke_summary(self.cid, 999, "好")
        self.s.revoke_summary(self.cid, self.sid, "好")
        with self.assertRaises(ValueError):                      # 已撤回
            self.s.revoke_summary(self.cid, self.sid, "好")
        with self.assertRaises(ValueError):
            self.s.revise_summary(self.cid, self.sid, "新", "好")
        self.assertEqual(len(self.audits("summary_revoke")), 1)

    def test_revoke_blank_quote_rejected(self):
        for q in ("", "  ", "\u3000", None):
            with self.assertRaises(ValueError, msg=repr(q)):
                self.s.revoke_summary(self.cid, self.sid, q)
        self.assertEqual([x["status"] for x in self.summaries()], ["confirmed"])
        self.assertEqual(len(self.audits("summary_revoke")), 0)

    def test_revoke_audit_failure_rolls_back(self):
        self.s.conn.execute("DROP TABLE audit_log")
        self.s.conn.commit()
        with self.assertRaises(sqlite3.Error):
            self.s.revoke_summary(self.cid, self.sid, "好")
        self.assertEqual([x["status"] for x in self.summaries()], ["confirmed"])
