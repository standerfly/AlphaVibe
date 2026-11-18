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

    def verify(self, iid, verdict="ok", method="compare-d-c", verifier="tool-a", note=None, cells=None):
        s = self.store()
        return s.apply_verification_batch([{
            "image_id": iid, "verdict": verdict, "method": method, "verifier": verifier,
            "note": note if note is not None else (None if verdict == "ok" else "發現 1 項疑慮（wrong-number×1）"),
            "cells": cells}])

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
        it = {"image_id": iid, "sha256": sha or self.sha(iid), "verdict": verdict}
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
        self.assertEqual(s.verification_counts(), {"unverified": 2, "flagged": 0, "cross_checked": 0, "reviewed": 0})

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
        self.assertEqual(ro.verification_counts(), {"unverified": 2, "flagged": 0, "cross_checked": 0, "reviewed": 0})
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
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        rc, out = self.vimport(self.vpayload([self.vitem(self.a)]), ["--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "cross_checked")


# ====================================================================== 搜尋與顯示

class SearchAndDisplayTest(VBase):
    def test_search_includes_only_cross_checked_and_reviewed_transcriptions(self):
        ro = self.ro()
        self.assertEqual(ro.search_articles("98765"), [])
        self.assertEqual(ro.search_articles("7654321"), [])
        self.verify(self.a, "ok")
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
        self.verify(self.a, "ok")
        hits = self.ro().search_articles("%s 98765" % BODY_MARK)
        self.assertEqual([h["article_id"] for h in hits], [1])

    def test_snippet_never_comes_from_unverified_transcription(self):
        self.verify(self.a, "ok")
        text = T.search_articles_text(self.ro(), "營收")
        self.assertIn("表格轉寫", text)
        self.assertNotIn("7654321", text)
        text = T.search_articles_text(self.ro(), "9958")
        self.assertEqual(text, T.NO_RESULT_TEXT)

    def test_status_change_back_to_unverified_removes_from_search(self):
        self.verify(self.a, "ok")
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
        self.verify(self.a, "ok")
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
        self.verify(self.a, "ok")
        self.store().apply_mark_reviewed([self.b])
        for iid in (self.a, self.b):
            path = self.write_results(self.results([self.item(iid, TABLE)]), name="r%d.json" % iid)
            rc, out = self.run_cli(["--import-transcription", path, "--apply", "--overwrite"])
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.status(iid), "unverified")

    def test_import_without_overwrite_skips_and_keeps_verification(self):
        self.verify(self.a, "ok")
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
        self.verify(self.b, "ok")
        self.store().set_setting("transcribe_enabled", "1")

        def fake(tiles, **kw):
            return {"status": "transcribed", "is_table": True, "text": "新模型內容 424242", "model": "new-model",
                    "reason": None, "abort": False}
        rc, out = self.run_cli(["--retranscribe"], transcribe=fake, get_secret=lambda *a, **k: "k", sleeper=lambda s: None)
        self.assertEqual(self.img_row(self.b)["transcription"], "新模型內容 424242")
        self.assertEqual(self.status(self.b), "unverified")
        self.assertEqual(self.ro().search_articles("424242"), [])      # 重轉後的新內容在驗證前不可搜尋

    def test_retranscribe_that_skips_manual_row_keeps_its_verification(self):
        self.verify(self.a, "ok")
        self.store().set_setting("transcribe_enabled", "1")
        rc, _ = self.run_cli(["--retranscribe"], transcribe=lambda tiles, **kw: {
            "status": "transcribed", "is_table": True, "text": "x 1", "model": "new", "abort": False},
            get_secret=lambda *a, **k: "k", sleeper=lambda s: None)
        self.assertEqual(self.img_row(self.a)["transcription"], "營收 98765 百萬\n毛利率 31%")
        self.assertEqual(self.status(self.a), "cross_checked")

    def test_reset_is_in_same_transaction_as_batch_rollback(self):
        self.verify(self.a, "ok")
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
                                                    "verifier": "x", "note": None, "cells": None}])
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

    def test_flagged_not_laundered_by_same_method(self):
        self.verify(self.a, "issues", method="compare-d-c")
        r = self.verify(self.a, "ok", method="compare-d-c")                 # 同一路徑再跑一次
        self.assertEqual(r["skipped"], {"same-method": [self.a]})
        self.assertEqual(self.status(self.a), "flagged")
        # 同一路徑換 verifier 名稱也一樣不行（看的是 method）
        r = self.verify(self.a, "ok", method="compare-d-c", verifier="other-name")
        self.assertEqual(self.status(self.a), "flagged")

    def test_flagged_can_be_cleared_by_a_different_method_and_is_recorded(self):
        self.verify(self.a, "issues", method="compare-d-c")
        r = self.verify(self.a, "ok", method="agent-spot-check", verifier="cline-sonnet")
        self.assertEqual(r["cross_checked"], [self.a])
        v = self.ver(self.a)
        self.assertEqual((v["status"], v["method"]), ("cross_checked", "agent-spot-check"))
        self.assertIn("原 flagged（來源：compare-d-c）經不同來源 agent-spot-check 覆核", v["note"])
        self.assertEqual(json.loads(v["flag_history"]), ["compare-d-c"])
        self.assertEqual(v["updates"], 2)

    def test_alternating_methods_cannot_launder_a_flag_that_each_method_raised(self):
        self.verify(self.a, "issues", method="compare-d-c")
        self.verify(self.a, "ok", method="agent-spot-check")                # 合法洗清一次
        self.verify(self.a, "issues", method="arithmetic")                  # 又被別的來源標疑慮
        self.assertEqual(self.status(self.a), "flagged")
        r = self.verify(self.a, "ok", method="compare-d-c")                 # 曾標過疑慮的來源不能再洗白
        self.assertEqual(r["skipped"], {"same-method": [self.a]})
        self.assertEqual(self.status(self.a), "flagged")
        r = self.verify(self.a, "ok", method="body-crosscheck")             # 全新的來源可以
        self.assertEqual(self.status(self.a), "cross_checked")

    def test_issues_always_downgrade_even_cross_checked_and_reviewed(self):
        self.verify(self.a, "ok")
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

    def test_methods_and_verifiers_merge_for_cross_checked(self):
        self.verify(self.a, "ok", method="compare-d-c", verifier="t1")
        self.verify(self.a, "ok", method="compare-d-c", verifier="t1")
        self.verify(self.a, "ok", method="arithmetic", verifier="t2")
        v = self.ver(self.a)
        self.assertEqual((v["method"], v["verifier"], v["updates"]), ("compare-d-c,arithmetic", "t1,t2", 3))

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
        self.assertIn("預覽（未寫入）：將設為 cross_checked 1 張、flagged 1 張", out)
        for bad in ("SECRETFOUND123", "EXPECTEDVAL", "第 9 列", TITLE, BODY_MARK, "98765"):
            self.assertNotIn(bad, out)

    def test_apply_writes_and_ok_is_cross_checked_issues_is_flagged(self):
        payload = self.vpayload([self.vitem(self.a), self.vitem(self.b, "issues", [
            {"where": "第 1 列第 1 欄", "found": "廠務", "expected": "整句備註", "kind": "truncated"},
            {"where": "第 2 列第 1 欄", "found": "1", "kind": "wrong-number"}])])
        rc, out = self.vimport(payload, ["--apply"])
        self.assertEqual(rc, 0, out)
        va, vb = self.ver(self.a), self.ver(self.b)
        self.assertEqual((va["status"], va["method"], va["verifier"]), ("cross_checked", "agent-spot-check", "cline-sonnet"))
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

    def test_antiwash_skip_reported_in_preview_and_apply(self):
        self.verify(self.a, "issues", method="agent-spot-check")
        rc, out = self.vimport(self.vpayload([self.vitem(self.a)], method="agent-spot-check"))
        self.assertEqual(rc, 0, out)
        self.assertIn("防洗白", out)
        self.assertIn("將設為 cross_checked 0 張", out)
        rc, out = self.vimport(self.vpayload([self.vitem(self.a)], method="arithmetic"), ["--apply"])
        self.assertEqual(self.status(self.a), "cross_checked")

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
        self.assertRegex(rows[0]["key"], r"^\d{6} method=agent-spot-check ok=1 flagged=1 skipped=0$")
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
                     "verification.json", "agent-spot-check", "truncated", "wrong-number", "付費文章", "--import-verification"):
            self.assertIn(need, g, need)

    def test_only_unverified_and_default_exclude_reviewed(self):
        self.verify(self.a, "ok")
        self.store().apply_mark_reviewed([self.b])
        _f, manifest, _ = self.export()
        self.assertEqual([x["image_id"] for x in manifest["items"]], [self.a])          # reviewed 不匯出，cross_checked 預設仍匯出
        _f, manifest, _ = self.export(["--only-unverified"])
        self.assertEqual(manifest["items"], [])

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
        items = [{"image_id": x["image_id"], "sha256": x["sha256"], "verdict": "ok"} for x in manifest["items"]]
        path = self.vfile(self.vpayload(items), folder=folder)
        rc, out = self.run_cli(["--import-verification", path, "--apply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(self.a), "cross_checked")
        self.assertEqual(self.status(self.b), "cross_checked")


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
        self.verify(self.a, "ok")
        self.verify(self.b, "issues")
        self.store().apply_mark_reviewed([c])
        _ = d
        self.assertIn("未驗證轉寫 1 張、有疑慮 1 張、已驗證 1 張、PO 已核對 1 張", self.text())

    def test_summary_on_old_db_without_table_counts_all_unverified(self):
        s = self.store()
        s.conn.execute("DROP TABLE transcription_verification")
        s.conn.commit()
        s.close()
        before = self.db_bytes()
        text = self.text()
        self.assertIn("未驗證轉寫 2 張、有疑慮 0 張、已驗證 0 張、PO 已核對 0 張", text)
        self.assertNotIn("尚未上線", text)
        self.assertEqual(self.db_bytes(), before)

    def test_summary_has_no_title_or_body(self):
        self.assertNotIn(TITLE, self.text())


if __name__ == "__main__":
    unittest.main()
