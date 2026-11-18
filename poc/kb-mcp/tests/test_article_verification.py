"""010 Phase 12：轉寫驗證等級（Q-028）。全用 tempfile 與合成圖、假資料；不連網、不讀鑰匙圈、不碰真實資料目錄。

涵蓋：新表建立與舊庫（沒有驗證表）唯讀不出錯、預設 unverified、各等級的搜尋納入／排除與 get_article 警告（台美一致）、
重置規則、reviewed 只能由 --mark-reviewed、flagged 不被單一路徑洗白、--import-verification 嚴格驗證與單一交易、
--export-verification-task 唯讀且不含標題、CLI 互斥、零網路零鑰匙圈、健檢摘要。"""
import hashlib
import io
import json
import os
import sqlite3
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import _article_fixture as F  # noqa: E402
import article_store as A  # noqa: E402
import article_tools as T  # noqa: E402
import article_verification as V  # noqa: E402
import check_scheduled_jobs as checker  # noqa: E402
import investanchors_import as I  # noqa: E402
import server  # noqa: E402
import us_stock_mcp_server  # noqa: E402
from test_article_manual_transcribe import (  # noqa: E402
    BODY_MARK, NOW, TITLE, Base, NetworkAndKeychainBlocked, _read)

TABLE = "| 代號 | 營收 |\n| --- | --- |\n| 2330 | 98765 |"


class VBase(Base):
    """兩篇文章、各一張已轉寫圖（手動 D），預設都是 unverified。"""

    def setUp(self):
        super().setUp()
        self._add_article(1)
        self.a = self._add_image(1, 1, status="done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code")
        self._add_article(2)
        self.b = self._add_image(2, 1, status="done", text="代號 9958 數字 7654321", model="claude-haiku-5-5")

    def ro(self):
        s = A.ArticleStore.open_readonly(self.data)
        self.addCleanup(s.close)
        return s

    def tsha(self, iid):
        return A.transcription_sha256(self.store().get_image_by_id(iid)["transcription"])

    def verify(self, iid, verdict="ok", method="compare-d-c", verifier="tool-a", note=None, cells=None):
        s = self.store()
        return s.apply_verification_batch([{
            "image_id": iid, "verdict": verdict, "method": method, "verifier": verifier,
            "note": note if note is not None else (None if verdict == "ok" else "發現 1 項疑慮（wrong-number×1）"),
            "cells": cells, "transcription_sha256": self.tsha(iid)}])

    def verify_full(self, iid, numeric="compare-d-c"):
        """兩個檢核家族都通過（數字＋文字）→ cross_checked。"""
        self.verify(iid, "ok", method=numeric, verifier="tool-a")
        return self.verify(iid, "ok", method="agent-spot-check", verifier="agent-a")

    def ver(self, iid):
        return self.store().get_verification(iid)

    def status(self, iid):
        v = self.ver(iid)
        return v["status"] if v else "unverified"

    def db_bytes(self):
        with open(os.path.join(self.data, "articles.db"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    # --- verification.json 輔助
    def vitem(self, iid, verdict="ok", issues=None, sha=None):
        it = {"image_id": iid, "sha256": sha or self.sha(iid), "transcription_sha256": self.tsha(iid), "verdict": verdict}
        if verdict == "issues":
            it["issues"] = issues or [{"where": "第 3 列第 2 欄", "found": "9,876", "expected": "98,76", "kind": "wrong-number"}]
        return it

    def vpayload(self, items, verifier="cline-sonnet", method="agent-spot-check"):
        return {"version": 1, "verifier": verifier, "method": method, "results": items}

    def vfile(self, payload, name="verification.json", folder=None):
        return self.write_results(payload, name=name, folder=folder)

    def vimport(self, payload, extra=(), **deps):
        return self.run_cli(["--import-verification", self.vfile(payload)] + list(extra), **deps)


# ====================================================================== 資料層：新表、預設、舊庫

class SchemaAndDefaultTest(VBase):
    def test_new_table_exists_and_everything_defaults_to_unverified(self):
        s = self.store()
        self.assertEqual(s.conn.execute(
            "SELECT name FROM sqlite_master WHERE name='transcription_verification'").fetchone()[0],
            "transcription_verification")
        self.assertIsNone(s.get_verification(self.a))
        self.assertEqual(s.verification_counts(), {"unverified": 2, "flagged": 0, "cross_checked": 0, "reviewed": 0, "single_family": 0})

    def test_new_transcription_from_any_path_is_unverified(self):
        self.assertEqual(self.status(self.a), "unverified")
        self.assertEqual(self.status(self.b), "unverified")

    def test_old_db_without_table_is_readable_readonly_as_all_unverified(self):
        """舊庫（升級前建立）沒有驗證表：唯讀查詢不出錯、全部視為 unverified、不建表、不改檔案。"""
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        before = self.db_bytes()
        ro = self.ro()
        self.assertFalse(ro._has_verification_table())
        self.assertEqual(ro.verification_counts(), {"unverified": 2, "flagged": 0, "cross_checked": 0, "reviewed": 0, "single_family": 0})
        self.assertIsNone(ro.get_verification(self.a))
        self.assertEqual(ro.get_verifications([self.a, self.b]), {})
        # 標題與內文照常搜得到；轉寫文字不納入
        self.assertEqual([r["article_id"] for r in ro.search_articles("98765")], [])
        self.assertEqual([r["article_id"] for r in ro.search_articles(BODY_MARK)], [2, 1])
        art = ro.get_article(1)
        self.assertEqual(art["images"][0]["verification_status"], "unverified")
        out = T.get_article_text(ro, 1)
        self.assertIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("98765", out)                     # 單篇仍顯示轉寫（附警告）
        self.assertEqual(self.db_bytes(), before)       # 唯讀：檔案位元組不變

    def test_old_db_upgrade_via_writable_open_creates_table_and_keeps_data(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        s2 = A.ArticleStore(self.data, now=lambda: NOW)         # 可寫連線才建表
        self.addCleanup(s2.close)
        self.assertTrue(s2._has_verification_table())
        self.assertEqual(s2.get_image_by_id(self.a)["transcription"], "營收 98765 百萬\n毛利率 31%")
        self.assertEqual(s2.verification_counts()["unverified"], 2)

    def test_readonly_open_never_creates_table_for_old_db(self):
        payload = self.vpayload([self.vitem(self.a)])          # 先算好 sha（測試輔助用可寫連線，會建表）
        path = self.vfile(payload)
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        rc, _ = self.run_cli(["--export-verification-task"])
        self.assertEqual(rc, 0)
        rc, out = self.run_cli(["--import-verification", path])        # 預覽
        self.assertEqual(rc, 0, out)
        ro = self.ro()
        self.assertFalse(ro._has_verification_table())

    def test_import_verification_apply_upgrades_old_db_then_works(self):
        path = self.vfile(self.vpayload([self.vitem(self.a)]))     # 先算好（測試輔助用可寫連線，會建表）
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ver(self.a)["checks_passed"], "text")      # 單一家族：仍是 unverified，但記錄進度
        self.assertEqual(self.status(self.a), "unverified")


# ====================================================================== 搜尋與顯示

class SearchAndDisplayTest(VBase):
    def test_search_includes_only_cross_checked_and_reviewed_transcriptions(self):
        ro = self.ro()
        self.assertEqual(ro.search_articles("98765"), [])
        self.assertEqual(ro.search_articles("7654321"), [])
        self.verify(self.a, "ok")                 # 只過一個家族：仍不納入搜尋
        self.assertEqual(self.ro().search_articles("98765"), [])
        self.verify_full(self.a)
        self.verify(self.b, "issues")
        ro = self.ro()
        self.assertEqual([r["article_id"] for r in ro.search_articles("98765")], [1])
        self.assertEqual(ro.search_articles("7654321"), [])            # flagged 不納入
        # reviewed 也納入
        s = self.store()
        s.apply_mark_reviewed([self.b])
        ro = self.ro()
        self.assertEqual([r["article_id"] for r in ro.search_articles("7654321")], [2])

    def test_title_and_body_search_unaffected(self):
        self.assertEqual(len(self.ro().search_articles(BODY_MARK)), 2)
        self.assertEqual(len(self.ro().search_articles(TITLE)), 2)

    def test_and_semantics_with_unverified_transcription_keyword_excludes_article(self):
        """其中一個關鍵字只在未驗證轉寫裡 → 該文章不得因另一個關鍵字命中而冒出轉寫片段，且 AND 不成立。"""
        self.assertEqual(self.ro().search_articles("%s 98765" % BODY_MARK), [])
        self.verify_full(self.a)
        hits = self.ro().search_articles("%s 98765" % BODY_MARK)
        self.assertEqual([h["article_id"] for h in hits], [1])

    def test_snippet_never_comes_from_unverified_transcription(self):
        self.verify_full(self.a)
        text = T.search_articles_text(self.ro(), "營收")
        self.assertIn("表格轉寫", text)
        self.assertNotIn("7654321", text)
        text = T.search_articles_text(self.ro(), "9958")
        self.assertEqual(text, T.NO_RESULT_TEXT)

    def test_status_change_back_to_unverified_removes_from_search(self):
        self.verify_full(self.a)
        self.assertEqual(len(self.ro().search_articles("98765")), 1)
        self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
        self.assertEqual(self.ro().search_articles("98765"), [])

    def test_get_article_unverified_shows_text_with_prominent_warning(self):
        out = T.get_article_text(self.ro(), 1)
        self.assertIn("【未驗證／有疑慮的圖片轉寫：數字可能有誤，不得用於投資判斷，請對照原圖】", out)
        self.assertIn("驗證等級：未驗證（不納入搜尋）", out)
        self.assertIn("手動轉寫（agent：claude-code）", out)
        self.assertIn("98765", out)
        self.assertNotIn("【圖片轉寫，手動", out)         # 未驗證不用「一般」標示

    def test_get_article_flagged_shows_warning_and_concern_summary_without_title(self):
        cells = json.dumps([{"where": "第 12 列第 5 欄", "kind": "truncated", "found": "廠務", "expected": "整句備註"}],
                           ensure_ascii=False)
        self.verify(self.b, "issues", note="發現 1 項疑慮（truncated×1）；驗證來源：agent-spot-check（x）", cells=cells)
        out = T.get_article_text(self.ro(), 2)
        self.assertIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("有疑慮（不納入搜尋）", out)
        self.assertIn("疑慮摘要：發現 1 項疑慮（truncated×1）", out)
        self.assertIn("第 12 列第 5 欄｜truncated｜轉寫現況：廠務｜疑似原圖：整句備註", out)
        self.assertIn("7654321", out)
        # 摘要區塊不含標題（標題只在文章開頭欄位）
        block = out.split("驗證等級：有疑慮")[1]
        self.assertNotIn(TITLE, block)

    def test_get_article_cross_checked_and_reviewed_show_level_and_method(self):
        self.verify(self.a, "ok", method="compare-d-c", verifier="compare-transcriptions")
        self.verify(self.a, "ok", method="agent-spot-check", verifier="cline-sonnet")       # 第二個來源合併
        out = T.get_article_text(self.ro(), 1)
        self.assertNotIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("驗證等級：已交叉驗證（納入搜尋）；方法：compare-d-c,agent-spot-check；驗證者：compare-transcriptions,cline-sonnet", out)
        self.assertIn("【圖片轉寫，手動（agent：claude-code），可能有誤，請以原圖為準】", out)
        self.store().apply_mark_reviewed([self.a])
        out = T.get_article_text(self.ro(), 1)
        self.assertIn("驗證等級：PO 已逐格核對（納入搜尋）；方法：po-review", out)
        self.assertNotIn(T.UNVERIFIED_WARNING, out)

    def test_untranscribed_and_not_table_images_have_no_transcription_warning(self):
        self._add_article(3)
        u = self._add_image(3, 1)
        n = self._add_image(3, 2, status="not_table")
        out = T.get_article_text(self.ro(), 3)
        self.assertNotIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("未轉寫", out)
        self.assertIn("非表格", out)
        self.assertEqual((u is not None, n is not None), (True, True))

    def test_flagged_not_table_image_shows_warning(self):
        self._add_article(3)
        n = self._add_image(3, 1, status="not_table")
        rc, out = self.vimport(self.vpayload([self.vitem(n, "issues", [
            {"where": "整張圖", "found": "D 判為非表格", "expected": "C 轉出了內容", "kind": "missing"}])]), ["--apply"])
        self.assertEqual(rc, 0, out)
        text = T.get_article_text(self.ro(), 3)
        self.assertIn(T.NOT_TABLE_FLAGGED_WARNING, text)

    def test_taiwan_and_us_connectors_output_identical_for_every_level(self):
        self._add_article(3)
        c = self._add_image(3, 1, status="done", text="毛利率 47.3% 乙數", model="claude-haiku-5-5")
        self._add_article(4)
        d = self._add_image(4, 1, status="done", text="丁數 5551234", model="manual:x")
        self.verify_full(self.a)
        self.verify(self.b, "issues", cells=json.dumps([{"where": "第 1 列第 1 欄", "kind": "other", "found": "x"}]))
        self.store().apply_mark_reviewed([c])
        _ = d       # d 保持 unverified
        tw = server.Server(data_dir=self.data)
        us = us_stock_mcp_server.Server(data_dir=self.data)
        self.addCleanup(tw.store.close)
        self.addCleanup(us.store.conn.close)
        cases = [("get_article", {"article_id": i}) for i in (1, 2, 3, 4)] + [
            ("search_articles", {"query": q}) for q in ("98765", "7654321", "47.3%", "5551234", BODY_MARK)]
        for name, args in cases:
            self.assertEqual(tw.call_tool(name, dict(args)), us.call_tool(name, dict(args)), (name, args))
        self.assertEqual(tw.call_tool("search_articles", {"query": "5551234"}), T.NO_RESULT_TEXT)
        self.assertNotEqual(tw.call_tool("search_articles", {"query": "47.3%"}), T.NO_RESULT_TEXT)

    def test_connector_on_old_db_without_table_matches_and_does_not_error(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        tw = server.Server(data_dir=self.data)
        us = us_stock_mcp_server.Server(data_dir=self.data)
        self.addCleanup(tw.store.close)
        self.addCleanup(us.store.conn.close)
        for name, args in (("get_article", {"article_id": 1}), ("search_articles", {"query": "98765"}),
                           ("search_articles", {"query": BODY_MARK})):
            self.assertEqual(tw.call_tool(name, dict(args)), us.call_tool(name, dict(args)))
        self.assertIn(T.UNVERIFIED_WARNING, tw.call_tool("get_article", {"article_id": 1}))

    def test_tool_counts_unchanged_no_new_mcp_tool(self):
        names = [t["name"] for t in server.TOOLS if "verif" in t["name"] or "reviewed" in t["name"]]
        self.assertEqual(names, [])
        self.assertEqual(len([t for t in us_stock_mcp_server.TOOLS if "article" in t["name"]]), 2)


# ====================================================================== 重置規則

class ResetRulesTest(VBase):
    def test_set_transcription_resets_status_and_clears_flag_records(self):
        self.verify(self.a, "issues", cells=json.dumps([{"where": "x", "kind": "other", "found": "y"}]))
        self.assertEqual(self.status(self.a), "flagged")
        self.store().set_transcription(1, 1, "done", text="全新內容 123", model="m2", is_table=True)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertIsNone(self.ver(self.a))                           # 疑慮與歷史記錄一併清除

    def test_overwrite_import_resets_cross_checked_and_reviewed(self):
        self.verify_full(self.a)
        self.store().apply_mark_reviewed([self.b])
        for iid in (self.a, self.b):
            path = self.write_results(self.results([self.item(iid, TABLE)]), name="r%d.json" % iid)
            rc, out = self.run_cli(["--import-transcription", path, "--apply", "--overwrite"])
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.status(iid), "unverified")

    def test_import_without_overwrite_skips_and_keeps_verification(self):
        self.verify_full(self.a)
        path = self.write_results(self.results([self.item(self.a, TABLE)]))
        rc, out = self.run_cli(["--import-transcription", path, "--apply"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.status(self.a), "cross_checked")        # 被略過＝內容沒變＝驗證仍有效

    def test_fresh_manual_import_of_untranscribed_image_is_unverified(self):
        self._add_article(3)
        c = self._add_image(3, 1)
        path = self.write_results(self.results([self.item(c, TABLE)]))
        rc, out = self.run_cli(["--import-transcription", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(c), "unverified")

    def test_retranscribe_model_change_resets_verification(self):
        self.store().set_transcription(2, 1, "done", text="舊模型內容 1", model="old-model", is_table=True)
        self.verify_full(self.b)
        self.store().set_setting("transcribe_enabled", "1")

        def fake(tiles, **kw):
            return {"status": "transcribed", "is_table": True, "text": "新模型內容 424242", "model": "new-model",
                    "reason": None, "abort": False}
        rc, out = self.run_cli(["--retranscribe"], transcribe=fake, get_secret=lambda *a, **k: "k", sleeper=lambda s: None)
        self.assertEqual(self.img_row(self.b)["transcription"], "新模型內容 424242")
        self.assertEqual(self.status(self.b), "unverified")
        self.assertEqual(self.ro().search_articles("424242"), [])      # 重轉後的新內容在驗證前不可搜尋

    def test_retranscribe_that_skips_manual_row_keeps_its_verification(self):
        self.verify_full(self.a)
        self.store().set_setting("transcribe_enabled", "1")
        rc, _ = self.run_cli(["--retranscribe"], transcribe=lambda tiles, **kw: {
            "status": "transcribed", "is_table": True, "text": "x 1", "model": "new", "abort": False},
            get_secret=lambda *a, **k: "k", sleeper=lambda s: None)
        self.assertEqual(self.img_row(self.a)["transcription"], "營收 98765 百萬\n毛利率 31%")
        self.assertEqual(self.status(self.a), "cross_checked")

    def test_reset_is_in_same_transaction_as_batch_rollback(self):
        self.verify_full(self.a)
        s = self.store()
        rows = [(1, 1, "done", "新內容 5", "manual:x", True), (2, 1, "done", "", "manual:x", True)]   # 第二筆驗證失敗
        with self.assertRaises(ValueError):
            s.apply_transcription_batch(rows)
        self.assertEqual(self.status(self.a), "cross_checked")         # 整批沒寫入＝驗證也沒被清掉


# ====================================================================== 狀態轉換

class TransitionRulesTest(VBase):
    def test_plan_function_never_produces_reviewed(self):
        for cur in (None, {"status": "flagged", "method": "x", "flag_history": None},
                    {"status": "cross_checked", "method": "x"}, {"status": "reviewed", "method": "po-review"}):
            for verdict in ("ok", "issues"):
                plan = A.plan_verification_transition(cur, verdict, "arithmetic")
                self.assertNotEqual(plan.get("status"), "reviewed")
        with self.assertRaises(ValueError):
            A.plan_verification_transition(None, "reviewed", "arithmetic")

    def test_reviewed_cannot_be_written_by_import_or_store_batch(self):
        for bad in ("reviewed", "cross_checked", "flagged", "unverified", "OK", None, True):
            payload = self.vpayload([self.vitem(self.a)])
            payload["results"][0]["verdict"] = bad
            rc, out = self.vimport(payload, ["--apply"])
            self.assertEqual(rc, 2, bad)
        with self.assertRaises(ValueError):
            self.store().apply_verification_batch([{"image_id": self.a, "verdict": "reviewed", "method": "arithmetic",
                                                    "verifier": "x", "note": None, "cells": None,
                                                    "transcription_sha256": self.tsha(self.a)}])
        self.assertEqual(self.status(self.a), "unverified")
        payload = self.vpayload([self.vitem(self.a)], method="po-review")       # po-review 不在驗證匯入的白名單
        rc, _ = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.status(self.a), "unverified")

    def test_mark_reviewed_is_the_only_way(self):
        rc, out = self.run_cli(["--mark-reviewed", str(self.a), "--apply"])
        self.assertEqual(rc, 0, out)
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["method"], v["verifier"]), ("reviewed", "po-review", "po"))

    def test_flagged_is_never_cleared_by_any_ok(self):
        self.verify(self.a, "issues", method="compare-d-c")
        for method in A.NUMERIC_METHODS + A.TEXT_METHODS:                    # 包含「不同 method」與同 method
            r = self.verify(self.a, "ok", method=method, verifier="other-name")
            self.assertEqual(r["skipped"], {"flagged-needs-po": [self.a]}, method)
            self.assertEqual((r["cross_checked"], r["partial"]), ([], []))
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["checks_passed"], v["updates"]), ("flagged", None, 1))      # 一個位元都沒動
        self.assertIn("發現 1 項疑慮", v["note"])

    def test_flagged_plus_both_families_in_every_order_stays_flagged_and_unsearchable(self):
        for order in (("compare-d-c", "agent-spot-check"), ("agent-spot-check", "arithmetic"),
                      ("body-crosscheck", "agent-spot-check", "compare-d-c")):
            self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
            self.verify(self.a, "issues", method="arithmetic" if order[0] != "arithmetic" else "body-crosscheck")
            for m in order:
                self.verify(self.a, "ok", method=m)
            self.assertEqual(self.status(self.a), "flagged", order)
            self.assertEqual(self.ro().search_articles("98765"), [], order)
            self.assertIn(T.UNVERIFIED_WARNING, T.get_article_text(self.ro(), 1))
        self.assertEqual(self.ver(self.a)["updates"], 1)

    def test_flagged_leaves_only_by_mark_reviewed_or_rewrite(self):
        self.verify(self.a, "issues", method="compare-d-c")
        self.verify_full(self.a)
        self.assertEqual(self.status(self.a), "flagged")
        # (a) PO 核對
        self.store().apply_mark_reviewed([self.a])
        self.assertEqual(self.status(self.a), "reviewed")
        self.assertEqual(len(self.ro().search_articles("98765")), 1)
        # (b) 重寫轉寫：重置為 unverified 後重新走兩家族
        self.verify(self.a, "issues", method="agent-spot-check")
        self.assertEqual(self.status(self.a), "flagged")
        self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
        self.assertEqual(self.status(self.a), "unverified")
        self.verify(self.a, "ok", method="compare-d-c")
        self.assertEqual(self.status(self.a), "unverified")
        self.verify(self.a, "ok", method="agent-spot-check")
        self.assertEqual(self.status(self.a), "cross_checked")
        self.assertEqual(len(self.ro().search_articles("98765")), 1)

    def test_issues_clears_previously_passed_families(self):
        self.verify(self.a, "ok", method="agent-spot-check")
        self.verify(self.a, "ok", method="compare-d-c")
        self.assertEqual(self.status(self.a), "cross_checked")
        self.verify(self.a, "issues", method="arithmetic")
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["checks_passed"]), ("flagged", None))
        self.assertEqual(json.loads(v["flag_history"]), ["arithmetic"])             # 歷史仍記錄（僅供追蹤，不影響轉換）
        self.verify(self.a, "issues", method="compare-d-c")                         # 再次 issues：更新疑慮與歷史
        self.assertEqual(json.loads(self.ver(self.a)["flag_history"]), ["arithmetic", "compare-d-c"])

    def test_family_combinations(self):
        """只有 numeric、只有 text、兩者（任一順序）、任一 issues。"""
        for method, want in (("compare-d-c", "numeric"), ("arithmetic", "numeric"), ("body-crosscheck", "numeric"),
                             ("agent-spot-check", "text")):
            self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
            r = self.verify(self.a, "ok", method=method)
            self.assertEqual((r["partial"], r["cross_checked"]), ([self.a], []), method)
            v = self.ver(self.a)
            self.assertEqual((v["status"], v["checks_passed"]), ("unverified", want), method)
            self.assertEqual(self.ro().search_articles("98765"), [], method)          # 單一家族不納入搜尋
        for first, second in (("compare-d-c", "agent-spot-check"), ("agent-spot-check", "arithmetic")):
            self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
            self.verify(self.a, "ok", method=first)
            self.verify(self.a, "ok", method=second)
            self.assertEqual(self.status(self.a), "cross_checked", (first, second))
            self.assertEqual(len(self.ro().search_articles("98765")), 1)
        # 同一家族的第二個 method 不能湊成兩家族
        self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
        self.verify(self.a, "ok", method="compare-d-c")
        self.verify(self.a, "ok", method="arithmetic")
        self.assertEqual(self.status(self.a), "unverified")
        # 任一 issues（即使另一家族已通過）→ flagged
        self.verify(self.a, "issues", method="agent-spot-check")
        self.assertEqual(self.status(self.a), "flagged")
        self.assertEqual(self.ro().search_articles("98765"), [])

    def test_partial_progress_shown_in_get_article(self):
        self.verify(self.a, "ok", method="compare-d-c")
        out = T.get_article_text(self.ro(), 1)
        self.assertIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("已通過數字檢核，尚缺文字抽查", out)
        self.verify(self.b, "ok", method="agent-spot-check")
        out = T.get_article_text(self.ro(), 2)
        self.assertIn(T.UNVERIFIED_WARNING, out)
        self.assertIn("已通過文字抽查，尚缺數字檢核", out)

    def test_compare_d_c_ok_cannot_catch_text_truncation_so_alone_never_reaches_search(self):
        """驗收實測：D 把「營收」改成「營」，compare 只比數字仍判 ok——單靠它不得進搜尋。"""
        self.store().set_transcription(1, 1, "done", text="| 營 | 98765 |", model="manual:claude-code", is_table=True)
        self.verify(self.a, "ok", method="compare-d-c")
        self.assertEqual(self.ro().search_articles("98765"), [])
        self.assertIn(T.UNVERIFIED_WARNING, T.get_article_text(self.ro(), 1))

    def test_alternating_methods_cannot_launder_a_flag(self):
        self.verify(self.a, "issues", method="compare-d-c")
        for m in ("agent-spot-check", "arithmetic", "body-crosscheck", "compare-d-c", "agent-spot-check"):
            self.verify(self.a, "ok", method=m)
        self.assertEqual(self.status(self.a), "flagged")

    def test_text_family_flagger_cannot_be_washed_by_itself_or_anyone_but_po(self):
        self.verify(self.a, "issues", method="agent-spot-check")
        self.verify(self.a, "ok", method="compare-d-c")
        r = self.verify(self.a, "ok", method="agent-spot-check")
        self.assertEqual(r["skipped"], {"flagged-needs-po": [self.a]})
        self.assertEqual(self.status(self.a), "flagged")
        self.store().apply_mark_reviewed([self.a])
        self.assertEqual(self.status(self.a), "reviewed")

    def test_issues_always_downgrade_even_cross_checked_and_reviewed(self):
        self.verify_full(self.a)
        self.verify(self.a, "issues", method="agent-spot-check")
        self.assertEqual(self.status(self.a), "flagged")
        self.store().apply_mark_reviewed([self.b])
        self.verify(self.b, "issues", method="agent-spot-check")
        self.assertEqual(self.status(self.b), "flagged")

    def test_ok_does_not_touch_reviewed(self):
        self.store().apply_mark_reviewed([self.a])
        r = self.verify(self.a, "ok", method="arithmetic")
        self.assertEqual(r["skipped"], {"reviewed": [self.a]})
        self.assertEqual(self.status(self.a), "reviewed")

    def test_methods_and_verifiers_merge_and_status_follows_families(self):
        self.verify(self.a, "ok", method="compare-d-c", verifier="t1")
        self.verify(self.a, "ok", method="compare-d-c", verifier="t1")
        self.verify(self.a, "ok", method="arithmetic", verifier="t2")
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["method"], v["verifier"], v["checks_passed"], v["updates"]),
                         ("unverified", "compare-d-c,arithmetic", "t1,t2", "numeric", 3))
        self.verify(self.a, "ok", method="agent-spot-check", verifier="t3")
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["method"], v["checks_passed"]),
                         ("cross_checked", "compare-d-c,arithmetic,agent-spot-check", "numeric,text"))

    def test_mark_reviewed_on_flagged_keeps_history_and_notes_it(self):
        self.verify(self.a, "issues", method="compare-d-c")
        self.store().apply_mark_reviewed([self.a])
        v = self.ver(self.a)
        self.assertEqual(v["status"], "reviewed")
        self.assertIn("原為 flagged", v["note"])
        self.assertEqual(json.loads(v["flag_history"]), ["compare-d-c"])


# ====================================================================== --import-verification

class ImportVerificationTest(VBase):
    def test_preview_default_writes_nothing_and_prints_numbers_only(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b, "issues", [
            {"where": "第 9 列第 9 欄", "found": "SECRETFOUND123", "expected": "EXPECTEDVAL", "kind": "truncated"}])])
        before = self.db_bytes()
        rc, out = self.vimport(payload)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_bytes(), before)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertIn("預覽（未寫入）：將設為 cross_checked 0 張、僅通過單一家族（尚不納入搜尋）1 張、flagged 1 張", out)
        for bad in ("SECRETFOUND123", "EXPECTEDVAL", "第 9 列", TITLE, BODY_MARK, "98765"):
            self.assertNotIn(bad, out)

    def test_apply_writes_and_ok_is_cross_checked_issues_is_flagged(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b, "issues", [
            {"where": "第 1 列第 1 欄", "found": "廠務", "expected": "整句備註", "kind": "truncated"},
            {"where": "第 2 列第 1 欄", "found": "1", "kind": "wrong-number"}])])
        rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 0, out)
        va, vb = self.ver(self.a), self.ver(self.b)
        self.assertEqual((va["status"], va["method"], va["verifier"], va["checks_passed"]),
                         ("unverified", "agent-spot-check", "cline-sonnet", "text"))      # 文字家族通過、尚缺數字檢核
        self.assertEqual(vb["status"], "flagged")
        self.assertIn("發現 2 項疑慮（truncated×1、wrong-number×1）", vb["note"])
        cells = json.loads(vb["flagged_cells"])
        self.assertEqual(cells[0], {"where": "第 1 列第 1 欄", "kind": "truncated", "found": "廠務", "expected": "整句備註"})
        self.assertNotIn(TITLE, json.dumps(vb, ensure_ascii=False))

    def test_stored_cells_are_trimmed_and_capped(self):
        issues = [{"where": "第 %d 列" % i, "found": "x" * 200, "expected": "y" * 200, "kind": "other"} for i in range(1, 121)]
        rc, out = self.vimport(self.vpayload([self.vitem(self.a, "issues", issues)]), ["--apply"])
        self.assertEqual(rc, 0, out)
        v = self.ver(self.a)
        cells = json.loads(v["flagged_cells"])
        self.assertEqual(len(cells), V.STORED_CELLS_MAX)
        self.assertEqual(len(cells[0]["found"]), V.STORED_CELL_TEXT)
        self.assertIn("發現 120 項疑慮", v["note"])

    def test_apply_revalidates_with_latest_state(self):
        """預覽之後狀態變了（PO 核對為 reviewed）：--apply 以最新狀態重新判斷，不覆蓋 reviewed。"""
        path = self.vfile(self.vpayload([self.vitem(self.a)]))
        rc, _ = self.run_cli(["--import-verification", path])
        self.assertEqual(rc, 0)
        self.store().apply_mark_reviewed([self.a])
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "reviewed")
        self.assertIn("略過 1 張", out)

    def test_flagged_skip_reported_in_preview_and_apply_for_any_method(self):
        self.verify(self.a, "issues", method="agent-spot-check")
        for method in ("agent-spot-check", "arithmetic"):
            payload = self.vpayload([self.vitem(self.a)], method=method)
            rc, out = self.vimport(payload)
            self.assertEqual(rc, 0, out)
            self.assertIn("有疑慮（flagged）的轉寫須由 PO 核對（--mark-reviewed）或重新轉寫後重驗", out)
            self.assertIn("將設為 cross_checked 0 張、僅通過單一家族（尚不納入搜尋）0 張", out)
            before = self.db_bytes()
            rc, out = self.vimport(payload, ["--apply"])
            self.assertEqual(rc, 0, out)
            self.assertIn("略過 1 張", out)
            self.assertEqual(self.status(self.a), "flagged")
            self.assertEqual(self.ver(self.a)["checks_passed"], None)

    def test_not_table_image_ok_skipped_and_untranscribed_rejected(self):
        self._add_article(3)
        n = self._add_image(3, 1, status="not_table")
        u = self._add_image(3, 2)
        rc, out = self.vimport(self.vpayload([self.vitem(n)]), ["--apply"])
        self.assertEqual(rc, 0, out)
        self.assertIn("非表格圖", out)
        self.assertIsNone(self.ver(n))
        rc, out = self.vimport(self.vpayload([self.vitem(u)]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("尚未轉寫", out)

    def test_strict_schema_bad_inputs_rejected_and_nothing_written(self):
        good = self.vitem(self.a)
        cases = {
            "no verifier": lambda p: p.pop("verifier"),
            "extra top key": lambda p: p.update(extra=1),
            "bad version": lambda p: p.update(version=2),
            "bool version": lambda p: p.update(version=True),
            "verifier chars": lambda p: p.update(verifier="bad name!"),
            "verifier too long": lambda p: p.update(verifier="a" * 41),
            "verifier empty": lambda p: p.update(verifier=""),
            "method outside whitelist": lambda p: p.update(method="vibes"),
            "method po-review": lambda p: p.update(method="po-review"),
            "method not str": lambda p: p.update(method=["arithmetic"]),
            "results empty": lambda p: p.update(results=[]),
            "results not list": lambda p: p.update(results={}),
            "too many results": lambda p: p.update(results=[good] * 201),
            "item not object": lambda p: p.update(results=[1]),
            "item extra key": lambda p: p["results"][0].update(extra=1),
            "item missing sha": lambda p: p["results"][0].pop("sha256"),
            "image_id str": lambda p: p["results"][0].update(image_id="1"),
            "image_id bool": lambda p: p["results"][0].update(image_id=True),
            "sha upper": lambda p: p["results"][0].update(sha256="A" * 64),
            "sha short": lambda p: p["results"][0].update(sha256="a" * 63),
            "verdict ok with issues": lambda p: p["results"][0].update(issues=[{"where": "w", "found": "f", "kind": "other"}]),
            "duplicate image": lambda p: p.update(results=[good, dict(good)]),
            "unknown image": lambda p: p["results"][0].update(image_id=9999),
        }
        before = self.db_bytes()
        for name, mut in cases.items():
            p = self.vpayload([dict(good)])
            mut(p)
            rc, out = self.vimport(p, ["--apply"])
            self.assertEqual(rc, 2, name)
            self.assertNotIn("Traceback", out, name)
        self.assertEqual(self.db_bytes(), before)

    def test_issues_field_validation(self):
        ok_issue = {"where": "第 1 列", "found": "x", "kind": "other"}

        def run(issue_list, **kw):
            item = self.vitem(self.a, "issues", issue_list)
            rc, out = self.vimport(self.vpayload([item]), ["--apply"])
            return rc, out
        self.assertEqual(run([ok_issue])[0], 0)
        self.store().set_transcription(1, 1, "done", text="再次 1", model="manual:x", is_table=True)   # 重置回 unverified 以便後續
        bad = {
            "empty list": [],
            "not list": "x",
            "too many": [ok_issue] * 201,
            "not object": ["x"],
            "missing where": [{"found": "f", "kind": "other"}],
            "missing found": [{"where": "w", "kind": "other"}],
            "missing kind": [{"where": "w", "found": "f"}],
            "extra key": [dict(ok_issue, note="n")],
            "bad kind": [dict(ok_issue, kind="uncertain")],
            "where too long": [dict(ok_issue, where="w" * 81)],
            "found too long": [dict(ok_issue, found="f" * 201)],
            "expected too long": [dict(ok_issue, expected="e" * 201)],
            "where empty": [dict(ok_issue, where="  ")],
            "found not str": [dict(ok_issue, found=5)],
            "newline": [dict(ok_issue, found="a\nb")],
            "tab": [dict(ok_issue, found="a\tb")],
            "control": [dict(ok_issue, found="a\x07b")],
            "bidi": [dict(ok_issue, found="a‮b")],
            "zero width": [dict(ok_issue, expected="a​b")],
            "secret": [dict(ok_issue, found="sk-ant-api03-abcdefghijklmnopqrstuvwx1234")],
            "token kv": [dict(ok_issue, found="password=hunter2xyz")],
        }
        for name, issues in bad.items():
            item = self.vitem(self.a, "ok")
            item["verdict"] = "issues"
            item["issues"] = issues
            rc, out = self.vimport(self.vpayload([item]), ["--apply"])
            self.assertEqual(rc, 2, name)
            self.assertNotIn("sk-ant", out)
            self.assertNotIn("hunter2", out)
        self.assertEqual(self.status(self.a), "unverified")
        item = self.vitem(self.a, "issues", [dict(ok_issue, found="f" * 200, expected="e" * 200, where="w" * 80)])
        self.assertEqual(self.vimport(self.vpayload([item]))[0], 0)               # 邊界值剛好通過

    def test_sha_mismatch_and_changed_file_and_missing_file_rejected(self):
        rc, _ = self.vimport(self.vpayload([self.vitem(self.a, sha="b" * 64)]), ["--apply"])
        self.assertEqual(rc, 2)
        full = os.path.join(self.data, self.img_row(self.a)["file_path"])
        good = self.vitem(self.a)
        with open(full, "ab") as f:
            f.write(b"x")
        rc, out = self.vimport(self.vpayload([good]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("sha256", out)
        os.remove(full)
        rc, out = self.vimport(self.vpayload([good]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("圖檔不存在", out)

    def test_manifest_in_same_folder_is_enforced(self):
        folder = os.path.join(self.tmp, "task")
        os.makedirs(folder)
        manifest = {"items": [{"image_id": self.a, "sha256": self.sha(self.a)}]}
        with open(os.path.join(folder, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        rc, _ = self.run_cli(["--import-verification", self.vfile(self.vpayload([self.vitem(self.a)]), folder=folder)])
        self.assertEqual(rc, 0)
        rc, out = self.run_cli(["--import-verification", self.vfile(self.vpayload([self.vitem(self.b)]), folder=folder)])
        self.assertEqual(rc, 2)
        self.assertIn("manifest", out)

    def test_non_json_missing_and_oversize_file_rejected(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w") as f:
            f.write("{not json")
        self.assertEqual(self.run_cli(["--import-verification", p])[0], 2)
        self.assertEqual(self.run_cli(["--import-verification", os.path.join(self.tmp, "none.json")])[0], 2)
        with open(p, "w") as f:
            f.write("[" * 100000)
        self.assertEqual(self.run_cli(["--import-verification", p])[0], 2)
        with mock.patch.object(V.M, "MAX_RESULTS_FILE_BYTES", 10):
            self.assertEqual(self.vimport(self.vpayload([self.vitem(self.a)]))[0], 2)

    def test_apply_is_single_transaction_and_rolls_back_whole_batch_with_audit(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b)])
        real = A.plan_verification_transition
        calls = {"n": 0}

        def flaky(cur, verdict, method):
            calls["n"] += 1
            if calls["n"] >= 6:                     # 預覽 2 次＋寫入前重新驗證 2 次＋交易內第 1 筆 1 次，交易內第 2 筆才爆
                raise sqlite3.OperationalError("boom")
            return real(cur, verdict, method)
        with mock.patch.object(A, "plan_verification_transition", flaky), \
                mock.patch.object(V.article_store, "plan_verification_transition", flaky):
            rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 2, out)
        self.assertIn("rollback", out)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertEqual(self.status(self.b), "unverified")
        rows = self.store().conn.execute("SELECT * FROM alert_log WHERE kind=?", (V.AUDIT_KIND_IMPORT,)).fetchall()
        self.assertEqual(rows, [])                                   # 稽核列與驗證列同交易，一起沒有

    def test_audit_row_counts_and_method_only(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ", "kind": "other"}])])
        rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 0, out)
        rows = self.store().conn.execute("SELECT kind, key FROM alert_log WHERE kind=?", (V.AUDIT_KIND_IMPORT,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertRegex(rows[0]["key"], r"^\d{6} method=agent-spot-check cross_checked=0 partial=1 flagged=1 source_typo=0 skipped=0$")
        self.assertNotIn("機密", rows[0]["key"])
        self.assertEqual(self.store().conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)

    def test_outputs_never_echo_issue_content_or_title(self):
        payload = self.vpayload([self.vitem(self.a, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ", "expected": "機密預期ZZZ", "kind": "other"}])])
        outs = [self.vimport(payload)[1], self.vimport(payload, ["--apply"])[1]]
        bad = self.vpayload([self.vitem(self.a, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ\x00", "kind": "other"}])])
        outs.append(self.vimport(bad)[1])
        blob = "\n".join(outs)
        for s in ("機密", TITLE, BODY_MARK):
            self.assertNotIn(s, blob)

    def test_apply_requires_existing_db_and_never_creates_one(self):
        path = self.vfile(self.vpayload([self.vitem(self.a)]))
        os.remove(os.path.join(self.data, "articles.db"))
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        path = self.vfile(self.vpayload([self.vitem(self.a)]))

        def boom(*a, **k):
            raise AssertionError("轉寫驗證不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--import-verification", path, "--apply"], get_secret=boom, fetch_mail=boom,
                                   notifier=boom, run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])


# ====================================================================== --mark-reviewed

class MarkReviewedTest(VBase):
    def test_preview_default_writes_nothing(self):
        before = self.db_bytes()
        rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, self.b)])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_bytes(), before)
        self.assertIn("預覽（未寫入）：將標記 2 張為 reviewed（原狀態：unverified 2）", out)

    def test_apply_marks_and_audits_counts_only(self):
        self.verify(self.b, "issues")
        rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, self.b), "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "reviewed")
        self.assertEqual(self.status(self.b), "reviewed")
        self.assertIn("注意：其中 1 張原為 flagged", out)
        key = self.store().conn.execute("SELECT key FROM alert_log WHERE kind=?", (V.AUDIT_KIND_REVIEWED,)).fetchone()[0]
        self.assertRegex(key, r"^\d{6} reviewed=2 flagged_before=1$")

    def test_bad_ids_rejected_whole_batch(self):
        for arg in ("", " ", "x", "1,,2", "0", "-1", "1,1", "1.5", "99999999999", ",".join(str(i) for i in range(1, 202)),
                    "%d,9999" % self.a):
            rc, out = self.run_cli(["--mark-reviewed", arg, "--apply"])
            self.assertEqual(rc, 2, arg)
        self.assertEqual(self.status(self.a), "unverified")

    def test_untranscribed_and_not_table_images_cannot_be_reviewed(self):
        self._add_article(3)
        u = self._add_image(3, 1)
        n = self._add_image(3, 2, status="not_table")
        for iid in (u, n):
            rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, iid), "--apply"])
            self.assertEqual(rc, 2)
            self.assertEqual(self.status(self.a), "unverified")       # 整批沒有寫入

    def test_apply_requires_existing_db(self):
        os.remove(os.path.join(self.data, "articles.db"))
        rc, _ = self.run_cli(["--mark-reviewed", "1", "--apply"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        def boom(*a, **k):
            raise AssertionError("不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--mark-reviewed", str(self.a), "--apply"], get_secret=boom, fetch_mail=boom,
                                   notifier=boom, run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])


# ====================================================================== --export-verification-task

class ExportVerificationTaskTest(VBase):
    def export(self, extra=()):
        rc, out = self.run_cli(["--export-verification-task"] + list(extra))
        self.assertEqual(rc, 0, out)
        base = os.path.join(self.data, "articles_probe")
        folder = os.path.join(base, sorted(os.listdir(base))[-1])
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            return folder, json.load(f), out

    def test_readonly_never_changes_database_and_location_and_files(self):
        before = self.db_bytes()
        folder, manifest, out = self.export()
        self.assertEqual(self.db_bytes(), before)
        self.assertRegex(os.path.basename(folder), r"^verify-task-\d{8}-\d{6}$")
        for name in ("manifest.json", "VERIFY_GUIDE.md", "transcriptions"):
            self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
        self.assertEqual(len(manifest["items"]), 2)

    def test_manifest_fields_and_numbered_transcription_files(self):
        folder, manifest, _ = self.export()
        it = [x for x in manifest["items"] if x["image_id"] == self.a][0]
        self.assertEqual(it["sha256"], self.sha(self.a))
        self.assertTrue(os.path.isabs(it["path"]))
        for k in ("width", "height", "transcription_path", "line_count", "view_files", "tile_status", "current_verification"):
            self.assertIn(k, it)
        self.assertEqual(it["line_count"], 2)
        self.assertEqual(it["current_verification"], "unverified")
        lines = _read(it["transcription_path"]).splitlines()
        self.assertEqual(lines, ["[L001] 營收 98765 百萬", "[L002] 毛利率 31%"])

    def test_no_title_body_or_url_anywhere_in_folder_and_output(self):
        folder, manifest, out = self.export()
        blob = out
        for root, _d, files in os.walk(folder):
            for fn in files:
                if fn.endswith(".png"):
                    continue
                blob += _read(os.path.join(root, fn))
        for bad in (TITLE, BODY_MARK, "investanchors.com", "img.example"):
            self.assertNotIn(bad, blob)

    def test_guide_has_required_instructions(self):
        folder, _m, _o = self.export()
        g = _read(os.path.join(folder, "VERIFY_GUIDE.md"))
        for need in ("逐字", "截斷", "廠務", "不要猜", "uncertain", "不得修改", "原圖的明顯筆誤", "kind=other",
                     "verification.json", "agent-spot-check", "自報字串", "transcription_sha256", "文字家族", "truncated", "wrong-number", "付費文章", "--import-verification"):
            self.assertIn(need, g, need)

    def test_only_unverified_and_default_exclude_reviewed(self):
        self.verify_full(self.a)
        self.store().apply_mark_reviewed([self.b])
        _f, manifest, _ = self.export()
        self.assertEqual([x["image_id"] for x in manifest["items"]], [self.a])          # reviewed 不匯出，cross_checked 預設仍匯出
        _f, manifest, _ = self.export(["--only-unverified"])
        self.assertEqual(manifest["items"], [])
        self.verify(self.b, "ok", method="compare-d-c")                                   # 單一家族仍算 unverified

    def test_limit_validation_and_stable_order(self):
        _f, manifest, _ = self.export(["--limit", "1"])
        self.assertEqual([x["image_id"] for x in manifest["items"]], [self.a])
        for bad in ("0", "101", "-3"):
            rc, _ = self.run_cli(["--export-verification-task", "--limit", bad])
            self.assertEqual(rc, 2, bad)

    def test_excludes_untranscribed_not_table_abandoned_missing_file(self):
        self._add_article(3)
        self._add_image(3, 1)
        self._add_image(3, 2, status="not_table")
        self._add_article(4, status="abandoned")
        self._add_image(4, 1, status="done", text="X 1")
        m = self._add_image(2, 2, status="done", text="Y 2", write_file=False)
        _f, manifest, _ = self.export()
        self.assertEqual(sorted(x["image_id"] for x in manifest["items"]), sorted([self.a, self.b]))
        self.assertNotIn(m, [x["image_id"] for x in manifest["items"]])

    def test_missing_database_not_created_and_old_db_works(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        _f, manifest, _ = self.export()
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["items"][0]["current_verification"], "unverified")
        os.remove(os.path.join(self.data, "articles.db"))
        rc, _ = self.run_cli(["--export-verification-task"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        def boom(*a, **k):
            raise AssertionError("不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--export-verification-task"], get_secret=boom, fetch_mail=boom, notifier=boom,
                                   run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])

    def test_agent_roundtrip_export_then_import(self):
        folder, manifest, _ = self.export()
        for x in manifest["items"]:
            self.assertEqual(x["transcription_sha256"], self.tsha(x["image_id"]))
        items = [{"image_id": x["image_id"], "sha256": x["sha256"], "transcription_sha256": x["transcription_sha256"],
                  "verdict": "ok"} for x in manifest["items"]]
        path = self.vfile(self.vpayload(items), folder=folder)
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "unverified")        # 文字抽查只是一個家族
        self.assertEqual(self.ver(self.a)["checks_passed"], "text")
        path2 = self.vfile(self.vpayload(items, verifier="compare-transcriptions", method="compare-d-c"),
                           name="verification2.json", folder=folder)
        rc, out = self.run_cli(["--import-verification", path2, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "cross_checked")
        self.assertEqual(self.status(self.b), "cross_checked")

    def test_rewrite_after_export_makes_old_verification_json_rejected(self):
        """重現案例（驗收缺陷 1）：匯出→轉寫被重寫→匯入舊 verification.json 必須整批拒絕。"""
        folder, manifest, _ = self.export()
        items = [{"image_id": x["image_id"], "sha256": x["sha256"], "transcription_sha256": x["transcription_sha256"],
                  "verdict": "ok"} for x in manifest["items"]]
        path = self.vfile(self.vpayload(items), folder=folder)
        path_ro = self.vfile(self.vpayload(items[:1]), name="v1.json", folder=folder)
        self.store().set_transcription(1, 1, "done", text="營 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
        before = self.db_bytes()
        for argv in (["--import-verification", path], ["--import-verification", path, "--apply"],
                     ["--import-verification", path_ro, "--apply"]):
            rc, out = self.run_cli(argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn("轉寫在抽查後已被改寫", out)
            self.assertIn("須重新抽查", out)
        self.assertEqual(self.db_bytes(), before)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertIsNone(self.ver(self.b))                         # 整批拒絕：連未被改寫的那張也沒寫



# ====================================================================== 轉寫內容綁定、顯示前綴、寫入交易

class TranscriptionBindingTest(VBase):
    def test_missing_or_malformed_transcription_sha256_rejected(self):
        for mut in (lambda it: it.pop("transcription_sha256"), lambda it: it.update(transcription_sha256="A" * 64),
                    lambda it: it.update(transcription_sha256="a" * 63), lambda it: it.update(transcription_sha256=5)):
            item = self.vitem(self.a)
            mut(item)
            rc, out = self.vimport(self.vpayload([item]), ["--apply"])
            self.assertEqual(rc, 2)
        self.assertIsNone(self.ver(self.a))

    def test_wrong_hash_rejected_with_fixed_message(self):
        item = self.vitem(self.a)
        item["transcription_sha256"] = A.transcription_sha256("別版轉寫")
        rc, out = self.vimport(self.vpayload([item]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("轉寫在抽查後已被改寫", out)
        self.assertNotIn("別版轉寫", out)

    def test_hash_is_utf8_sha256_of_stored_text_and_empty_for_not_table(self):
        self.assertEqual(self.tsha(self.a), hashlib.sha256("營收 98765 百萬\n毛利率 31%".encode("utf-8")).hexdigest())
        self.assertEqual(A.transcription_sha256(None), hashlib.sha256(b"").hexdigest())

    def test_rewrite_between_validate_and_commit_is_caught_inside_the_transaction(self):
        s = self.store()
        stale = self.tsha(self.a)
        s.set_transcription(1, 1, "done", text="改寫後 1", model="manual:x", is_table=True)
        with self.assertRaises(A.TranscriptionChanged):
            s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "agent-spot-check",
                                        "verifier": "x", "note": None, "cells": None, "transcription_sha256": stale},
                                       ], audit_kind="k", audit_key="x")
        self.assertIsNone(self.ver(self.a))
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM alert_log WHERE kind='k'").fetchone()[0], 0)

    def test_cli_apply_reports_rewrite_race_and_rolls_back(self):
        path = self.vfile(self.vpayload([self.vitem(self.a), self.vitem(self.b)]))
        real = V.validate_verification

        calls = {"n": 0}

        def flaky(cur, verdict, method):
            calls["n"] += 1
            if calls["n"] >= 6:                     # 預覽 2 次＋寫入前重新驗證 2 次＋交易內第 1 筆 1 次，交易內第 2 筆才爆
                raise sqlite3.OperationalError("boom")
            return real(cur, verdict, method)
        with mock.patch.object(A, "plan_verification_transition", flaky), \
                mock.patch.object(V.article_store, "plan_verification_transition", flaky):
            rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 2, out)
        self.assertIn("rollback", out)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertEqual(self.status(self.b), "unverified")
        rows = self.store().conn.execute("SELECT * FROM alert_log WHERE kind=?", (V.AUDIT_KIND_IMPORT,)).fetchall()
        self.assertEqual(rows, [])                                   # 稽核列與驗證列同交易，一起沒有

    def test_audit_row_counts_and_method_only(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ", "kind": "other"}])])
        rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 0, out)
        rows = self.store().conn.execute("SELECT kind, key FROM alert_log WHERE kind=?", (V.AUDIT_KIND_IMPORT,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertRegex(rows[0]["key"], r"^\d{6} method=agent-spot-check cross_checked=0 partial=1 flagged=1 skipped=0$")
        self.assertNotIn("機密", rows[0]["key"])
        self.assertEqual(self.store().conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)

    def test_outputs_never_echo_issue_content_or_title(self):
        payload = self.vpayload([self.vitem(self.a, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ", "expected": "機密預期ZZZ", "kind": "other"}])])
        outs = [self.vimport(payload)[1], self.vimport(payload, ["--apply"])[1]]
        bad = self.vpayload([self.vitem(self.a, "issues", [
            {"where": "機密位置ZZZ", "found": "機密轉寫ZZZ\x00", "kind": "other"}])])
        outs.append(self.vimport(bad)[1])
        blob = "\n".join(outs)
        for s in ("機密", TITLE, BODY_MARK):
            self.assertNotIn(s, blob)

    def test_apply_requires_existing_db_and_never_creates_one(self):
        path = self.vfile(self.vpayload([self.vitem(self.a)]))
        os.remove(os.path.join(self.data, "articles.db"))
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        path = self.vfile(self.vpayload([self.vitem(self.a)]))

        def boom(*a, **k):
            raise AssertionError("轉寫驗證不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--import-verification", path, "--apply"], get_secret=boom, fetch_mail=boom,
                                   notifier=boom, run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])


# ====================================================================== --mark-reviewed

class MarkReviewedTest(VBase):
    def test_preview_default_writes_nothing(self):
        before = self.db_bytes()
        rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, self.b)])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_bytes(), before)
        self.assertIn("預覽（未寫入）：將標記 2 張為 reviewed（原狀態：unverified 2）", out)

    def test_apply_marks_and_audits_counts_only(self):
        self.verify(self.b, "issues")
        rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, self.b), "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "reviewed")
        self.assertEqual(self.status(self.b), "reviewed")
        self.assertIn("注意：其中 1 張原為 flagged", out)
        key = self.store().conn.execute("SELECT key FROM alert_log WHERE kind=?", (V.AUDIT_KIND_REVIEWED,)).fetchone()[0]
        self.assertRegex(key, r"^\d{6} reviewed=2 flagged_before=1$")

    def test_bad_ids_rejected_whole_batch(self):
        for arg in ("", " ", "x", "1,,2", "0", "-1", "1,1", "1.5", "99999999999", ",".join(str(i) for i in range(1, 202)),
                    "%d,9999" % self.a):
            rc, out = self.run_cli(["--mark-reviewed", arg, "--apply"])
            self.assertEqual(rc, 2, arg)
        self.assertEqual(self.status(self.a), "unverified")

    def test_untranscribed_and_not_table_images_cannot_be_reviewed(self):
        self._add_article(3)
        u = self._add_image(3, 1)
        n = self._add_image(3, 2, status="not_table")
        for iid in (u, n):
            rc, out = self.run_cli(["--mark-reviewed", "%d,%d" % (self.a, iid), "--apply"])
            self.assertEqual(rc, 2)
            self.assertEqual(self.status(self.a), "unverified")       # 整批沒有寫入

    def test_apply_requires_existing_db(self):
        os.remove(os.path.join(self.data, "articles.db"))
        rc, _ = self.run_cli(["--mark-reviewed", "1", "--apply"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        def boom(*a, **k):
            raise AssertionError("不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--mark-reviewed", str(self.a), "--apply"], get_secret=boom, fetch_mail=boom,
                                   notifier=boom, run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])


# ====================================================================== --export-verification-task

class ExportVerificationTaskTest(VBase):
    def export(self, extra=()):
        rc, out = self.run_cli(["--export-verification-task"] + list(extra))
        self.assertEqual(rc, 0, out)
        base = os.path.join(self.data, "articles_probe")
        folder = os.path.join(base, sorted(os.listdir(base))[-1])
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            return folder, json.load(f), out

    def test_readonly_never_changes_database_and_location_and_files(self):
        before = self.db_bytes()
        folder, manifest, out = self.export()
        self.assertEqual(self.db_bytes(), before)
        self.assertRegex(os.path.basename(folder), r"^verify-task-\d{8}-\d{6}$")
        for name in ("manifest.json", "VERIFY_GUIDE.md", "transcriptions"):
            self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
        self.assertEqual(len(manifest["items"]), 2)

    def test_manifest_fields_and_numbered_transcription_files(self):
        folder, manifest, _ = self.export()
        it = [x for x in manifest["items"] if x["image_id"] == self.a][0]
        self.assertEqual(it["sha256"], self.sha(self.a))
        self.assertTrue(os.path.isabs(it["path"]))
        for k in ("width", "height", "transcription_path", "line_count", "view_files", "tile_status", "current_verification"):
            self.assertIn(k, it)
        self.assertEqual(it["line_count"], 2)
        self.assertEqual(it["current_verification"], "unverified")
        lines = _read(it["transcription_path"]).splitlines()
        self.assertEqual(lines, ["[L001] 營收 98765 百萬", "[L002] 毛利率 31%"])

    def test_no_title_body_or_url_anywhere_in_folder_and_output(self):
        folder, manifest, out = self.export()
        blob = out
        for root, _d, files in os.walk(folder):
            for fn in files:
                if fn.endswith(".png"):
                    continue
                blob += _read(os.path.join(root, fn))
        for bad in (TITLE, BODY_MARK, "investanchors.com", "img.example"):
            self.assertNotIn(bad, blob)

    def test_guide_has_required_instructions(self):
        folder, _m, _o = self.export()
        g = _read(os.path.join(folder, "VERIFY_GUIDE.md"))
        for need in ("逐字", "截斷", "廠務", "不要猜", "uncertain", "不得修改", "原圖的明顯筆誤", "kind=other",
                     "verification.json", "agent-spot-check", "自報字串", "transcription_sha256", "文字家族", "truncated", "wrong-number", "付費文章", "--import-verification"):
            self.assertIn(need, g, need)

    def test_only_unverified_and_default_exclude_reviewed(self):
        self.verify_full(self.a)
        self.store().apply_mark_reviewed([self.b])
        _f, manifest, _ = self.export()
        self.assertEqual([x["image_id"] for x in manifest["items"]], [self.a])          # reviewed 不匯出，cross_checked 預設仍匯出
        _f, manifest, _ = self.export(["--only-unverified"])
        self.assertEqual(manifest["items"], [])
        self.verify(self.b, "ok", method="compare-d-c")                                   # 單一家族仍算 unverified

    def test_limit_validation_and_stable_order(self):
        _f, manifest, _ = self.export(["--limit", "1"])
        self.assertEqual([x["image_id"] for x in manifest["items"]], [self.a])
        for bad in ("0", "101", "-3"):
            rc, _ = self.run_cli(["--export-verification-task", "--limit", bad])
            self.assertEqual(rc, 2, bad)

    def test_excludes_untranscribed_not_table_abandoned_missing_file(self):
        self._add_article(3)
        self._add_image(3, 1)
        self._add_image(3, 2, status="not_table")
        self._add_article(4, status="abandoned")
        self._add_image(4, 1, status="done", text="X 1")
        m = self._add_image(2, 2, status="done", text="Y 2", write_file=False)
        _f, manifest, _ = self.export()
        self.assertEqual(sorted(x["image_id"] for x in manifest["items"]), sorted([self.a, self.b]))
        self.assertNotIn(m, [x["image_id"] for x in manifest["items"]])

    def test_missing_database_not_created_and_old_db_works(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        _f, manifest, _ = self.export()
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["items"][0]["current_verification"], "unverified")
        os.remove(os.path.join(self.data, "articles.db"))
        rc, _ = self.run_cli(["--export-verification-task"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain(self):
        def boom(*a, **k):
            raise AssertionError("不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--export-verification-task"], get_secret=boom, fetch_mail=boom, notifier=boom,
                                   run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])

    def test_agent_roundtrip_export_then_import(self):
        folder, manifest, _ = self.export()
        for x in manifest["items"]:
            self.assertEqual(x["transcription_sha256"], self.tsha(x["image_id"]))
        items = [{"image_id": x["image_id"], "sha256": x["sha256"], "transcription_sha256": x["transcription_sha256"],
                  "verdict": "ok"} for x in manifest["items"]]
        path = self.vfile(self.vpayload(items), folder=folder)
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "unverified")        # 文字抽查只是一個家族
        self.assertEqual(self.ver(self.a)["checks_passed"], "text")
        path2 = self.vfile(self.vpayload(items, verifier="compare-transcriptions", method="compare-d-c"),
                           name="verification2.json", folder=folder)
        rc, out = self.run_cli(["--import-verification", path2, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "cross_checked")
        self.assertEqual(self.status(self.b), "cross_checked")

    def test_rewrite_after_export_makes_old_verification_json_rejected(self):
        """重現案例（驗收缺陷 1）：匯出→轉寫被重寫→匯入舊 verification.json 必須整批拒絕。"""
        folder, manifest, _ = self.export()
        items = [{"image_id": x["image_id"], "sha256": x["sha256"], "transcription_sha256": x["transcription_sha256"],
                  "verdict": "ok"} for x in manifest["items"]]
        path = self.vfile(self.vpayload(items), folder=folder)
        path_ro = self.vfile(self.vpayload(items[:1]), name="v1.json", folder=folder)
        self.store().set_transcription(1, 1, "done", text="營 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
        before = self.db_bytes()
        for argv in (["--import-verification", path], ["--import-verification", path, "--apply"],
                     ["--import-verification", path_ro, "--apply"]):
            rc, out = self.run_cli(argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn("轉寫在抽查後已被改寫", out)
            self.assertIn("須重新抽查", out)
        self.assertEqual(self.db_bytes(), before)
        self.assertEqual(self.status(self.a), "unverified")
        self.assertIsNone(self.ver(self.b))                         # 整批拒絕：連未被改寫的那張也沒寫



# ====================================================================== 轉寫內容綁定、顯示前綴、寫入交易

class TranscriptionBindingTest(VBase):
    def test_missing_or_malformed_transcription_sha256_rejected(self):
        for mut in (lambda it: it.pop("transcription_sha256"), lambda it: it.update(transcription_sha256="A" * 64),
                    lambda it: it.update(transcription_sha256="a" * 63), lambda it: it.update(transcription_sha256=5)):
            item = self.vitem(self.a)
            mut(item)
            rc, out = self.vimport(self.vpayload([item]), ["--apply"])
            self.assertEqual(rc, 2)
        self.assertIsNone(self.ver(self.a))

    def test_wrong_hash_rejected_with_fixed_message(self):
        item = self.vitem(self.a)
        item["transcription_sha256"] = A.transcription_sha256("別版轉寫")
        rc, out = self.vimport(self.vpayload([item]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("轉寫在抽查後已被改寫", out)
        self.assertNotIn("別版轉寫", out)

    def test_hash_is_utf8_sha256_of_stored_text_and_empty_for_not_table(self):
        self.assertEqual(self.tsha(self.a), hashlib.sha256("營收 98765 百萬\n毛利率 31%".encode("utf-8")).hexdigest())
        self.assertEqual(A.transcription_sha256(None), hashlib.sha256(b"").hexdigest())

    def test_rewrite_between_validate_and_commit_is_caught_inside_the_transaction(self):
        s = self.store()
        stale = self.tsha(self.a)
        s.set_transcription(1, 1, "done", text="改寫後 1", model="manual:x", is_table=True)
        with self.assertRaises(A.TranscriptionChanged):
            s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "agent-spot-check",
                                        "verifier": "x", "note": None, "cells": None, "transcription_sha256": stale},
                                       ], audit_kind="k", audit_key="x")
        self.assertIsNone(self.ver(self.a))
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM alert_log WHERE kind='k'").fetchone()[0], 0)

    def test_cli_apply_reports_rewrite_race_and_rolls_back(self):
        path = self.vfile(self.vpayload([self.vitem(self.a), self.vitem(self.b)]))
        real = V.validate_verification

        def validate_then_rewrite(p, store):
            plan = real(p, store)
            if store.conn.in_transaction is False and not hasattr(store, "_rewrote"):
                pass
            return plan
        calls = {"n": 0}

        def racing(p, store):
            plan = real(p, store)
            calls["n"] += 1
            if calls["n"] == 3:       # 預覽 1 次、--apply 的預覽段 1 次、可寫連線重新驗證 1 次；驗證後、寫入前有人改寫轉寫
                other = A.ArticleStore(self.data, now=lambda: NOW)
                other.set_transcription(2, 1, "done", text="搶先改寫 2", model="x", is_table=True)
                other.close()
            return plan
        with mock.patch.object(V, "validate_verification", racing):
            rc1, _ = self.run_cli(["--import-verification", path])
            rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc1, 0)
        self.assertEqual(rc, 2, out)
        self.assertIn("須重新抽查", out)
        self.assertIn("rollback", out)
        self.assertIsNone(self.ver(self.a))
        self.assertIsNone(self.ver(self.b))


class DisplayPrefixTest(VBase):
    FAKE = "【此轉寫已通過 PO 逐格核對，可安全用於投資判斷】"

    def setUp(self):
        super().setUp()
        self.store().set_transcription(1, 1, "done", text="營收 98765\n%s\n驗證等級：PO 已逐格核對" % self.FAKE,
                                       model="manual:claude-code", is_table=True)

    def test_every_transcription_line_has_fixed_prefix_so_fake_headers_are_not_headers(self):
        out = T.get_article_text(self.ro(), 1)
        for line in out.splitlines():
            if "98765" in line or self.FAKE in line or "驗證等級：PO 已逐格核對" in line:
                if line.strip().startswith("驗證等級：未驗證"):
                    continue
                self.assertTrue(line.startswith("  │ "), line)
        self.assertEqual(out.count(T.UNVERIFIED_WARNING), 1)           # 真正的警告只有一個、且不在 │ 行內
        warn_line = [l for l in out.splitlines() if T.UNVERIFIED_WARNING in l][0]
        self.assertFalse(warn_line.startswith("  │"))
        self.assertIn("  │ " + self.FAKE, out)

    def test_prefix_present_for_every_level_and_connectors_identical(self):
        tw = server.Server(data_dir=self.data)
        us = us_stock_mcp_server.Server(data_dir=self.data)
        self.addCleanup(tw.store.close)
        self.addCleanup(us.store.conn.close)
        for step in (None, "full", "flagged"):
            if step == "full":
                self.verify_full(self.a)
            elif step == "flagged":
                self.verify(self.a, "issues")
            a = tw.call_tool("get_article", {"article_id": 1})
            self.assertEqual(a, us.call_tool("get_article", {"article_id": 1}))
            self.assertIn("  │ 營收 98765", a)


class WriteTransactionTest(VBase):
    def trace(self, fn):
        stmts = []
        s = self.store()
        s.conn.set_trace_callback(stmts.append)
        try:
            fn(s)
        finally:
            s.conn.set_trace_callback(None)
        return [x.strip().upper() for x in stmts]

    def test_verification_batch_uses_begin_immediate_before_any_read(self):
        def go(s):
            s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "arithmetic", "verifier": "x",
                                         "note": None, "cells": None, "transcription_sha256": self.tsha(self.a)}])
        st = self.trace(go)
        self.assertEqual(st[0], "BEGIN IMMEDIATE")
        self.assertEqual(st[-1], "COMMIT")

    def test_mark_reviewed_and_transcription_batch_use_begin_immediate(self):
        self.assertEqual(self.trace(lambda s: s.apply_mark_reviewed([self.a]))[0], "BEGIN IMMEDIATE")
        st = self.trace(lambda s: s.apply_transcription_batch([(1, 1, "done", "新 1", "manual:x", True)]))
        self.assertEqual(st[0], "BEGIN IMMEDIATE")

    def test_write_lock_held_blocks_second_writer_until_commit(self):
        s1 = A.ArticleStore(self.data)
        s2 = A.ArticleStore(self.data)
        s2.conn.execute("PRAGMA busy_timeout=50")
        self.addCleanup(s1.close)
        self.addCleanup(s2.close)
        s1._begin_immediate()
        with self.assertRaises(sqlite3.OperationalError):
            s2._begin_immediate()
        s1.conn.rollback()
        s2._begin_immediate()
        s2.conn.rollback()


# ====================================================================== 中間版本庫相容、manifest 交叉比對

LEGACY_DDL = """
CREATE TABLE transcription_verification (
    image_id INTEGER PRIMARY KEY REFERENCES article_image(id),
    status TEXT NOT NULL CHECK (status IN ('unverified','flagged','cross_checked','reviewed')),
    method TEXT, verifier TEXT, note TEXT, flagged_cells TEXT,
    checked_at TEXT, updates INTEGER NOT NULL DEFAULT 1)
"""        # 0dc75f5 之前形狀的驗證表：缺 flag_history、checks_passed


class LegacySchemaTest(VBase):
    def make_legacy(self, rows):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.execute(LEGACY_DDL)
        for iid, status in rows:
            s.conn.execute("INSERT INTO transcription_verification (image_id, status, method, verifier, checked_at) "
                           "VALUES (?,?,?,?,?)", (iid, status, "compare-d-c", "tool-a", "2026-11-18T10:00:00+08:00"))
        s.conn.commit()
        s.close()

    def test_readonly_on_table_without_new_columns_works_and_bytes_unchanged(self):
        self.make_legacy([(self.a, "cross_checked"), (self.b, "flagged")])
        before = self.db_bytes()
        ro = self.ro()
        cols = ro._verification_columns()
        self.assertNotIn("checks_passed", cols)
        self.assertNotIn("flag_history", cols)
        self.assertEqual(ro.verification_counts(),
                         {"unverified": 0, "flagged": 1, "cross_checked": 1, "reviewed": 0, "single_family": 0})
        self.assertEqual(ro.get_verification(self.a)["status"], "cross_checked")
        self.assertEqual(set(ro.get_verifications([self.a, self.b])), {self.a, self.b})
        self.assertEqual([r["article_id"] for r in ro.search_articles("98765")], [1])       # 舊 cross_checked 唯讀仍可搜尋
        out = T.get_article_text(ro, 1)
        self.assertIn("已交叉驗證", out)
        self.assertIn(T.UNVERIFIED_WARNING, T.get_article_text(ro, 2))
        self.assertEqual(self.db_bytes(), before)

    def test_health_summary_not_misreported_as_not_online(self):
        s = self.store()
        run_id = s.start_run("mail")
        s.finish_run(run_id, True, 0, 0, "ok", True)
        s.close()
        self.make_legacy([(self.a, "cross_checked")])       # 最後才改成舊形狀（之後不再開可寫連線）
        before = self.db_bytes()
        with mock.patch.object(checker, "_now", lambda: NOW.replace(tzinfo=None)):
            text = "\n".join(f[2] for f in checker.check_investanchors_import(self.data))
        self.assertNotIn("尚未上線", text)
        self.assertIn("未驗證轉寫 1 張（其中僅通過單一家族 0 張）、有疑慮 0 張、已驗證 1 張", text)
        self.assertEqual(self.db_bytes(), before)

    def test_writable_upgrade_adds_columns_and_downgrades_old_single_check_cross_checked(self):
        self.make_legacy([(self.a, "cross_checked"), (self.b, "reviewed")])
        s = A.ArticleStore(self.data, now=lambda: NOW)
        self.addCleanup(s.close)
        self.assertTrue({"checks_passed", "flag_history"} <= s._verification_columns())
        self.assertEqual(s.get_verification(self.a)["status"], "unverified")          # 舊規則的 cross_checked 一律降級
        self.assertEqual(s.get_verification(self.b)["status"], "reviewed")            # reviewed 不動
        self.assertEqual(self.ro().search_articles("98765"), [])
        # 之後走新流程正常
        s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "compare-d-c", "verifier": "t",
                                     "note": None, "cells": None, "transcription_sha256": self.tsha(self.a)}])
        s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "agent-spot-check", "verifier": "t",
                                     "note": None, "cells": None, "transcription_sha256": self.tsha(self.a)}])
        self.assertEqual(s.get_verification(self.a)["status"], "cross_checked")
        s.close()
        s2 = A.ArticleStore(self.data, now=lambda: NOW)                                # 再開一次不會再降級
        self.addCleanup(s2.close)
        self.assertEqual(s2.get_verification(self.a)["status"], "cross_checked")

    def test_current_shape_table_not_downgraded_on_reopen(self):
        self.verify_full(self.a)
        s = A.ArticleStore(self.data, now=lambda: NOW)
        self.addCleanup(s.close)
        self.assertEqual(s.get_verification(self.a)["status"], "cross_checked")


class ManifestTranscriptionShaTest(VBase):
    def folder_with_manifest(self, tsha_value):
        folder = os.path.join(self.tmp, "task")
        os.makedirs(folder, exist_ok=True)
        item = {"image_id": self.a, "sha256": self.sha(self.a)}
        if tsha_value is not None:
            item["transcription_sha256"] = tsha_value
        with open(os.path.join(folder, "manifest.json"), "w") as f:
            json.dump({"items": [item]}, f)
        return folder

    def test_manifest_zero_hash_with_current_db_value_in_verification_is_rejected(self):
        folder = self.folder_with_manifest("0" * 64)
        path = self.vfile(self.vpayload([self.vitem(self.a)]), folder=folder)         # verification 填庫內現值
        for extra in ([], ["--apply"]):
            rc, out = self.run_cli(["--import-verification", path] + extra)
            self.assertEqual(rc, 2, extra)
            self.assertIn("transcription_sha256 與 manifest 不一致", out)
        self.assertIsNone(self.ver(self.a))

    def test_manifest_matching_hash_ok_and_missing_field_skipped_for_compat(self):
        for value in (self.tsha(self.a), None):
            folder = self.folder_with_manifest(value)
            path = self.vfile(self.vpayload([self.vitem(self.a)]), folder=folder)
            rc, out = self.run_cli(["--import-verification", path])
            self.assertEqual(rc, 0, (value, out))


# ====================================================================== 原圖筆誤（source-typo）

class SourceTypoTest(VBase):
    TYPO = {"where": "第 3 列第 1 欄", "found": "台績電（代碼欄與名稱欄對調）", "expected": "原圖本身筆誤", "kind": "source-typo"}

    def imp(self, iid, issues, method="agent-spot-check", extra=()):
        item = self.vitem(iid, "issues", issues)
        return self.vimport(self.vpayload([item], method=method), ["--apply"] + list(extra))

    def test_all_source_typo_counts_as_ok_family_passes_not_flagged_and_is_visible(self):
        rc, out = self.imp(self.a, [self.TYPO])
        self.assertEqual(rc, 0, out)
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["checks_passed"]), ("unverified", "text"))      # 文字家族通過，不是 flagged
        self.assertIsNone(v["flagged_cells"])
        self.assertEqual(json.loads(v["source_typos"])[0]["where"], "第 3 列第 1 欄")
        self.assertIn("含原圖筆誤提示", out)
        rc, out = self.vimport(self.vpayload([self.vitem(self.a)], method="compare-d-c", verifier="tool-x"), ["--apply"])
        v = self.ver(self.a)
        self.assertEqual(v["status"], "cross_checked")
        self.assertIsNotNone(v["source_typos"])                                             # 後續 ok 不會抹掉記錄
        self.assertEqual(len(self.ro().search_articles("98765")), 1)                        # cross_checked 才納入搜尋
        text = T.get_article_text(self.ro(), 1)
        self.assertIn("【原圖可能有筆誤（轉寫已照原圖抄寫），請對照原圖：第 3 列第 1 欄（台績電（代碼欄與名稱欄對調）；疑似應為：原圖本身筆誤）】", text)
        self.assertNotIn(T.UNVERIFIED_WARNING, text)
        self.assertNotIn(TITLE, text.split("【原圖可能有筆誤")[1])

    def test_typo_hint_shown_for_every_level_and_connectors_identical(self):
        self.imp(self.a, [self.TYPO])
        tw = server.Server(data_dir=self.data)
        us = us_stock_mcp_server.Server(data_dir=self.data)
        self.addCleanup(tw.store.close)
        self.addCleanup(us.store.conn.close)
        a = tw.call_tool("get_article", {"article_id": 1})
        self.assertEqual(a, us.call_tool("get_article", {"article_id": 1}))
        self.assertIn("【原圖可能有筆誤", a)
        self.assertIn(T.UNVERIFIED_WARNING, a)                       # 單一家族：仍是未驗證，兩種提示並存
        self.store().apply_mark_reviewed([self.a])
        self.assertIn("【原圖可能有筆誤", T.get_article_text(self.ro(), 1))

    def test_source_typo_plus_any_other_kind_is_flagged(self):
        for other in ("truncated", "wrong-number", "missing", "extra", "other"):
            self.store().set_transcription(1, 1, "done", text="營收 98765 百萬\n毛利率 31%", model="manual:claude-code", is_table=True)
            rc, out = self.imp(self.a, [self.TYPO, {"where": "第 1 列", "found": "x", "kind": other}])
            self.assertEqual(rc, 0, out)
            v = self.ver(self.a)
            self.assertEqual(v["status"], "flagged", other)
            self.assertIsNone(v["source_typos"])

    def test_other_alone_is_still_flagged(self):
        rc, out = self.imp(self.a, [{"where": "第 1 列", "found": "uncertain：看不清楚", "kind": "other"}])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "flagged")

    def test_source_typo_limit_is_20_per_image(self):
        mk = lambda n: [dict(self.TYPO, where="第 %d 列" % i) for i in range(1, n + 1)]
        rc, out = self.imp(self.a, mk(21))
        self.assertEqual(rc, 2)
        self.assertIn("source-typo 每張圖最多 20 項", out)
        self.assertIsNone(self.ver(self.a))
        rc, out = self.imp(self.a, mk(20))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(json.loads(self.ver(self.a)["source_typos"])), 20)
        # 混合時 source-typo 超過 20 一樣拒收
        rc, out = self.imp(self.b, mk(21) + [{"where": "w", "found": "f", "kind": "other"}])
        self.assertEqual(rc, 2)

    def test_where_length_limit_unchanged_for_source_typo(self):
        rc, out = self.imp(self.a, [dict(self.TYPO, where="w" * 81)])
        self.assertEqual(rc, 2)

    def test_old_verification_json_without_source_typo_still_works(self):
        rc, out = self.vimport(self.vpayload([self.vitem(self.a, "issues"), self.vitem(self.b)]), ["--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "flagged")
        self.assertEqual(self.ver(self.b)["checks_passed"], "text")
        self.assertNotIn("原圖筆誤", out)

    def test_preview_and_audit_count_source_typo(self):
        item = self.vitem(self.a, "issues", [self.TYPO])
        before = self.db_bytes()
        rc, out = self.vimport(self.vpayload([item]))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_bytes(), before)
        self.assertIn("1 張只有「原圖筆誤」（source-typo）", out)
        self.assertNotIn("台績電", out)
        rc, out = self.vimport(self.vpayload([item]), ["--apply"])
        key = self.store().conn.execute("SELECT key FROM alert_log WHERE kind=?", (V.AUDIT_KIND_IMPORT,)).fetchone()[0]
        self.assertRegex(key, r"^\d{6} method=agent-spot-check cross_checked=0 partial=1 flagged=0 source_typo=1 skipped=0$")
        self.assertNotIn("台績電", key)

    def test_rewrite_clears_typo_record_and_flagged_row_keeps_it_out_of_ok_path(self):
        self.imp(self.a, [self.TYPO])
        self.store().set_transcription(1, 1, "done", text="新內容 1", model="manual:x", is_table=True)
        self.assertIsNone(self.ver(self.a))
        self.verify(self.b, "issues")                                   # flagged 的圖收到 typo-only（視同 ok）→ 照 flagged 規則略過
        rc, out = self.imp(self.b, [self.TYPO])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.b), "flagged")
        self.assertIsNone(self.ver(self.b)["source_typos"])

    def test_old_table_without_source_typos_column_reads_fine(self):
        s = self.store()
        s.apply_verification_batch([{"image_id": self.a, "verdict": "ok", "method": "agent-spot-check", "verifier": "x",
                                     "note": None, "cells": None, "transcription_sha256": self.tsha(self.a)}])
        s.conn.execute("ALTER TABLE transcription_verification RENAME TO tv_old")
        s.conn.execute("CREATE TABLE transcription_verification AS SELECT image_id,status,method,verifier,note,"
                       "flagged_cells,flag_history,checks_passed,checked_at,updates FROM tv_old")
        s.conn.execute("DROP TABLE tv_old")
        s.conn.commit()
        s.close()
        ro = self.ro()
        self.assertEqual(ro.get_verification(self.a)["status"], "unverified")
        self.assertNotIn("原圖可能有筆誤", T.get_article_text(ro, 1))

    def test_guide_defines_source_typo_conditions_and_counterexamples(self):
        g = V.build_verify_guide()
        for need in ("source-typo", "逐字一致", "反例", "寧可讓它被標有疑慮", "最多 20 項"):
            self.assertIn(need, g)


# ====================================================================== CLI 互斥與防呆

class CliExclusivityTest(VBase):
    def setUp(self):
        super().setUp()
        self.vpath = self.vfile(self.vpayload([self.vitem(self.a)]))
        self.rpath = self.write_results(self.results([self.item(self.a)]), name="results.json")

    def actions(self):
        return {"export_u": ["--export-untranscribed"], "import_t": ["--import-transcription", self.rpath],
                "import_v": ["--import-verification", self.vpath], "mark": ["--mark-reviewed", str(self.a)],
                "export_v": ["--export-verification-task"]}

    def test_actions_are_mutually_exclusive(self):
        acts = self.actions()
        names = list(acts)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                rc, out = self.run_cli(acts[x] + acts[y])
                self.assertEqual(rc, 2, (x, y))
                self.assertIn("不可同時", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles_probe")))

    def test_conflicts_with_other_action_flags(self):
        others = [["--transcribe-sample", "1"], ["--retranscribe"], ["--dry-run"], ["--resume"], ["--force-weekly"],
                  ["--enable-transcription"], ["--disable-transcription"], ["--max-articles", "1"],
                  ["--reset-abandoned", "1"], ["--backfill-since", "2026-01-01"]]
        for key in ("import_v", "mark", "export_v"):
            for extra in others:
                rc, out = self.run_cli(self.actions()[key] + extra)
                self.assertEqual(rc, 2, (key, extra, out))
                self.assertIn("不可與其他動作旗標併用", out)
        s = self.store()
        self.assertIsNone(s.get_setting("transcribe_enabled"))
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)
        self.assertEqual(self.status(self.a), "unverified")

    def test_dependent_flags_need_their_action(self):
        for argv in (["--only-unverified"], ["--apply"], ["--limit", "2"]):
            self.assertEqual(self.run_cli(argv)[0], 2, argv)
        cases = [
            (self.actions()["import_v"] + ["--limit", "2"], 2),
            (self.actions()["import_v"] + ["--overwrite"], 2),
            (self.actions()["import_v"] + ["--only-unverified"], 2),
            (self.actions()["mark"] + ["--limit", "2"], 2),
            (self.actions()["mark"] + ["--overwrite"], 2),
            (self.actions()["mark"] + ["--only-unverified"], 2),
            (self.actions()["export_v"] + ["--apply"], 2),
            (self.actions()["export_v"] + ["--overwrite"], 2),
            (self.actions()["export_u"] + ["--only-unverified"], 2),
            (self.actions()["import_t"] + ["--only-unverified"], 2),
            (self.actions()["export_v"] + ["--limit", "2", "--only-unverified"], 0),
        ]
        for argv, want in cases:
            rc, out = self.run_cli(argv)
            self.assertEqual(rc, want, (argv, out))
        self.assertEqual(self.status(self.a), "unverified")

    def test_data_dir_guard_runs_first_for_all_new_actions(self):
        prod = os.path.realpath(os.path.join(HERE, "..", "..", "data"))
        for argv in (["--import-verification", self.vpath], ["--mark-reviewed", "1"], ["--export-verification-task"]):
            out = io.StringIO()
            env = dict(os.environ)
            env.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
            with mock.patch.dict(os.environ, env, clear=True):
                rc = I.run(["--data-dir", prod] + argv, out=out)
            self.assertEqual(rc, 2, argv)
            self.assertIn("正式資料庫", out.getvalue())

    def test_existing_flags_unchanged(self):
        rc, out = self.run_cli(["--reset-transcribe-attempts"])
        self.assertEqual(rc, 2)
        rc, out = self.run_cli(["--retranscribe"])
        self.assertEqual(rc, 2)
        self.assertIn("轉寫開關未開", out)


# ====================================================================== 健檢摘要

class HealthSummaryTest(VBase):
    def setUp(self):
        super().setUp()
        s = self.store()
        run_id = s.start_run("mail")
        s.finish_run(run_id, True, 0, 0, "ok", True)

    def text(self):
        with mock.patch.object(checker, "_now", lambda: NOW.replace(tzinfo=None)):
            findings = checker.check_investanchors_import(self.data)
        return "\n".join(f[2] for f in findings)

    def test_summary_counts_each_level(self):
        self._add_article(3)
        c = self._add_image(3, 1, status="done", text="丙 3")
        self._add_article(4)
        d = self._add_image(4, 1, status="done", text="丁 4")
        self.verify_full(self.a)
        self.verify(self.b, "issues")
        self.store().apply_mark_reviewed([c])
        self.verify(d, "ok", method="compare-d-c")           # 只過一個家族
        self.assertIn("未驗證轉寫 1 張（其中僅通過單一家族 1 張）、有疑慮 1 張、已驗證 1 張、PO 已核對 1 張", self.text())

    def test_summary_on_old_db_without_table_counts_all_unverified(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        before = self.db_bytes()
        text = self.text()
        self.assertIn("未驗證轉寫 2 張（其中僅通過單一家族 0 張）、有疑慮 0 張、已驗證 0 張、PO 已核對 0 張", text)
        self.assertNotIn("尚未上線", text)
        self.assertEqual(self.db_bytes(), before)

    def test_summary_has_no_title_or_body(self):
        self.assertNotIn(TITLE, self.text())


if __name__ == "__main__":
    unittest.main()
