"""010 Phase 10（方案 D）：手動轉寫的匯出／匯入／顯示／CLI 互斥。

全部用 tempfile 與合成圖、假資料；不連網、不讀鑰匙圈、不碰真實資料目錄。
「零網路、零鑰匙圈」以 monkeypatch 讓 socket 連線與 `security` 子行程呼叫一出現就失敗來證明。"""
import copy
import datetime
import hashlib
import io
import json
import os
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import article_data_guard  # noqa: E402
import article_image_tiles  # noqa: E402
import article_manual_transcribe as M  # noqa: E402
import article_store  # noqa: E402
import article_tools  # noqa: E402
import article_transcribe  # noqa: E402
import investanchors_import as I  # noqa: E402
import investanchors_redact  # noqa: E402
from test_article_image_tiles import blank_bands, make_table_png  # noqa: E402

TITLE = "機密標題-緯穎觀察"
BODY_MARK = "機密內文標記XYZ"
TZ8 = article_store.TZ8
NOW = datetime.datetime(2026, 11, 18, 10, 0, 0, tzinfo=TZ8)


def _read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def _write(path, data, mode="w"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        f.write(data)


def _body():
    return BODY_MARK + "。" + "補充說明。" * 60


class NetworkAndKeychainBlocked(object):
    """進入時讓任何 socket 連線與 `security` 子行程呼叫立即失敗（證明零網路、零鑰匙圈）。"""

    def __init__(self, block_all_subprocess=False):
        self.block_all = block_all_subprocess
        self.attempts = []

    def __enter__(self):
        def boom_socket(*a, **k):
            self.attempts.append("socket")
            raise AssertionError("不得連網")
        real_run, real_popen = subprocess.run, subprocess.Popen

        def guard(args):
            first = args[0] if isinstance(args, (list, tuple)) and args else str(args)
            name = os.path.basename(str(first))
            if self.block_all or name == "security":
                self.attempts.append("subprocess:%s" % name)
                raise AssertionError("不得呼叫子行程 %s" % name)

        def run(args, *a, **k):
            guard(args)
            return real_run(args, *a, **k)

        class Popen(real_popen):
            def __init__(s, args, *a, **k):
                guard(args)
                super().__init__(args, *a, **k)
        self._patches = [
            mock.patch.object(socket.socket, "connect", boom_socket),
            mock.patch.object(socket, "create_connection", boom_socket),
            mock.patch.object(socket, "getaddrinfo", boom_socket),
            mock.patch.object(subprocess, "run", run),
            mock.patch.object(subprocess, "Popen", Popen),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="manual-transcribe-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.png = make_table_png(300, 200)
        self.out = io.StringIO()

    def _add_article(self, aid, status="fetched"):
        s = article_store.ArticleStore(self.data, now=lambda: NOW)
        s.upsert_discovered(aid, "https://investanchors.com/user/vip_contents/%d" % aid, TITLE, list_date="2026-11-10")
        s.mark_fetched(aid, _body(), published_at="2026-11-10T08:00:00+08:00")
        if status == "abandoned":
            s.conn.execute("UPDATE article SET status='abandoned' WHERE article_id=?", (aid,))
            s.conn.commit()
        s.close()

    def _add_image(self, aid, seq, data=None, write_file=True, status=None, text=None, model="api-model"):
        s = article_store.ArticleStore(self.data, now=lambda: NOW)
        s.add_image(aid, seq, "https://img.example/%d-%d.png" % (aid, seq))
        if write_file:
            rel = os.path.join("articles_images", str(aid), "%d.png" % seq)
            full = os.path.join(self.data, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data if data is not None else self.png)
            s.set_image_file(aid, seq, rel)
        if status == "done":
            s.set_transcription(aid, seq, "done", text=text or "舊轉寫", model=model, is_table=True)
        elif status == "not_table":
            s.set_transcription(aid, seq, "not_table", is_table=False)
        iid = s.conn.execute("SELECT id FROM article_image WHERE article_id=? AND seq=?", (aid, seq)).fetchone()[0]
        s.close()
        return iid

    def store(self):
        s = article_store.ArticleStore(self.data, now=lambda: NOW)
        self.addCleanup(s.close)
        return s

    def img_row(self, iid):
        s = self.store()
        return s.get_image_by_id(iid)

    def run_cli(self, argv, **deps):
        out = io.StringIO()
        deps.setdefault("now", lambda: NOW)
        deps.setdefault("out", out)
        rc = I.run(["--data-dir", self.data] + argv, **deps)
        return rc, out.getvalue()

    def sha(self, iid):
        return M.sha256_file(os.path.join(self.data, self.img_row(iid)["file_path"]))

    def results(self, items, model="manual:claude-code"):
        return {"version": 1, "model": model, "results": items}

    def item(self, iid, text="| 代號 | 營收 |\n| --- | --- |\n| 2330 | 98765 |", is_table=True, sha=None):
        return {"image_id": iid, "sha256": sha or self.sha(iid), "is_table": is_table, "text": text}

    def write_results(self, payload, name="results.json", folder=None):
        folder = folder or self.tmp
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path


# ====================================================================== 匯出

class ExportTest(Base):
    def _manifest(self, out_dir):
        with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
            return json.load(f)

    def _export(self, limit=10, **deps):
        return M.export_untranscribed(self.data, limit=limit, now=lambda: NOW, **deps)

    def test_excludes_done_not_table_abandoned_missing_file_and_corrupt(self):
        self._add_article(1)
        a = self._add_image(1, 1)                                            # 入選
        self._add_image(1, 2, status="done")                                 # 已轉寫
        self._add_image(1, 3, status="not_table")                            # 非表格
        self._add_image(1, 4, write_file=False)                              # 沒有 file_path
        ghost = self._add_image(1, 5)                                        # 有紀錄但檔案被刪
        os.remove(os.path.join(self.data, self.img_row(ghost)["file_path"]))
        bad = self._add_image(1, 6, data=b"not an image at all")             # 壞檔
        self._add_article(2, status="abandoned")
        self._add_image(2, 1)                                                # 文章已放棄
        r = self._export()
        m = self._manifest(r["out_dir"])
        self.assertEqual([i["image_id"] for i in m["items"]], [a])
        self.assertEqual((r["skipped_missing"], r["skipped_unreadable"]), (1, 1))
        self.assertNotIn(bad, [i["image_id"] for i in m["items"]])

    def test_manifest_has_no_title_or_body_and_has_required_fields(self):
        self._add_article(1)
        iid = self._add_image(1, 1)
        r = self._export()
        raw = _read(os.path.join(r["out_dir"], "manifest.json"))
        self.assertNotIn(TITLE, raw)
        self.assertNotIn(BODY_MARK, raw)
        self.assertNotIn("investanchors.com", raw)           # 連網址都不放
        it = json.loads(raw)["items"][0]
        for k in ("image_id", "article_id", "seq", "path", "sha256", "width", "height", "is_long", "tiles",
                  "view_files", "transcription_status", "tile_status"):
            self.assertIn(k, it)
        self.assertEqual(it["image_id"], iid)
        self.assertEqual(it["sha256"], hashlib.sha256(self.png).hexdigest())
        self.assertEqual((it["width"], it["height"], it["is_long"]), (300, 200, False))
        self.assertEqual(it["view_files"], [it["path"]])      # 短圖直接引用原圖
        self.assertEqual(it["tile_status"], "not_needed")
        self.assertFalse(os.path.exists(os.path.join(r["out_dir"], "tiles")))
        self.assertTrue(os.path.isabs(it["path"]) and os.path.isfile(it["path"]))

    def test_guide_written_and_reuses_shared_rule_text(self):
        self._add_article(1)
        self._add_image(1, 1)
        r = self._export()
        guide = _read(os.path.join(r["out_dir"], "AGENT_GUIDE.md"))
        self.assertIn(article_transcribe.TRANSCRIBE_RULES, guide)
        self.assertIn(article_transcribe.TILE_OVERLAP_RULE, guide)
        self.assertIn("manual:", guide)
        self.assertIn("results.json", guide)
        self.assertIn("不得猜測", guide)
        self.assertNotIn(TITLE, guide)

    def test_shared_rules_still_in_api_prompt_unchanged(self):
        self.assertTrue(article_transcribe.PROMPT_BASE.startswith(article_transcribe.TRANSCRIBE_RULES))
        self.assertIn(article_transcribe.TILE_OVERLAP_RULE, article_transcribe.PROMPT_CONTEXT)

    def test_limit_and_stable_order(self):
        for aid in (30, 10, 20):
            self._add_article(aid)
            for seq in (2, 1):
                self._add_image(aid, seq)
        r = self._export(limit=4)
        m = self._manifest(r["out_dir"])
        self.assertEqual([(i["article_id"], i["seq"]) for i in m["items"]], [(10, 1), (10, 2), (20, 1), (20, 2)])
        r2 = self._export(limit=4)
        self.assertEqual([(i["article_id"], i["seq"]) for i in self._manifest(r2["out_dir"])["items"]],
                         [(i["article_id"], i["seq"]) for i in m["items"]])

    def test_default_limit_is_10_and_bad_limit_rejected(self):
        self._add_article(1)
        for seq in range(1, 13):
            self._add_image(1, seq)
        rc, out = self.run_cli(["--export-untranscribed"])
        self.assertEqual(rc, 0)
        folders = os.listdir(os.path.join(self.data, "articles_probe"))
        self.assertEqual(len(folders), 1)
        m = self._manifest(os.path.join(self.data, "articles_probe", folders[0]))
        self.assertEqual(len(m["items"]), 10)
        for bad in ("0", "-3", "101"):
            rc, _ = self.run_cli(["--export-untranscribed", "--limit", bad])
            self.assertEqual(rc, 2, bad)

    def test_output_folder_location_and_name(self):
        self._add_article(1)
        self._add_image(1, 1)
        r = self._export()
        self.assertEqual(r["out_dir"], os.path.join(os.path.realpath(self.data), "articles_probe",
                                                    "manual-transcribe-20261118-100000"))
        r2 = self._export()                                   # 同一秒再匯出不覆蓋
        self.assertNotEqual(r["out_dir"], r2["out_dir"])
        self.assertTrue(os.path.isdir(r["out_dir"]) and os.path.isdir(r2["out_dir"]))

    def test_long_image_tiles_written_to_export_folder_via_runner(self):
        self._add_article(1)
        long_png = make_table_png(1000, 2600)
        iid = self._add_image(1, 1, data=long_png)
        calls = []

        def fake(cfg):
            calls.append(cfg["mode"])
            if cfg["mode"] == "bands":
                return [{"type": "bands", "width": 1000, "height": 2600, "bands": blank_bands(2600)}]
            out = []
            for i, (top, bottom) in enumerate(cfg["cuts"], 1):
                tp = os.path.join(cfg["out_dir"], "tile_%02d.png" % i)
                with open(tp, "wb") as f:
                    f.write(make_table_png(1000, bottom - top))
                out.append({"type": "tile", "index": i, "path": tp, "width": 1000, "height": bottom - top})
            return out
        tmp_root = os.path.join(self.tmp, "tilestmp")
        os.makedirs(tmp_root)
        r = self._export(tiles_runner=fake, tile_tmp_root=tmp_root)
        it = self._manifest(r["out_dir"])["items"][0]
        self.assertEqual(calls, ["bands", "slice"])
        self.assertTrue(it["is_long"])
        self.assertEqual(it["tile_status"], "ok")
        self.assertGreater(len(it["tiles"]), 1)
        self.assertEqual(it["view_files"], it["tiles"])
        for p in it["tiles"]:
            self.assertTrue(p.startswith(r["out_dir"]) and os.path.isfile(p))
        self.assertEqual(os.listdir(tmp_root), [])            # 暫存切片已清除
        self.assertEqual(r["long_images"], 1)
        self.assertEqual(self.img_row(iid)["transcription_status"], "untranscribed")

    def test_long_image_degrades_without_browser(self):
        self._add_article(1)
        self._add_image(1, 1, data=make_table_png(1000, 2600))

        def no_browser(cfg):
            raise article_image_tiles.TilerError("no_node")
        r = self._export(tiles_runner=no_browser)
        it = self._manifest(r["out_dir"])["items"][0]
        self.assertEqual(it["tile_status"], "unavailable")
        self.assertIn("no_node", it["tile_reason"])
        self.assertEqual(it["tiles"], [])
        self.assertEqual(it["view_files"], [it["path"]])      # 退回原圖
        self.assertEqual(r["tiles_degraded"], 1)
        self.assertFalse(os.path.exists(os.path.join(r["out_dir"], "tiles")))

    def test_real_runner_without_playwright_degrades_not_crashes(self):
        """容器沒有 playwright／瀏覽器：預設 runner 失敗也要降級而非丟例外。"""
        self._add_article(1)
        self._add_image(1, 1, data=make_table_png(1000, 2600))
        r = self._export()
        it = self._manifest(r["out_dir"])["items"][0]
        self.assertIn(it["tile_status"], ("ok", "unavailable"))
        self.assertTrue(it["view_files"])

    def test_readonly_never_changes_database(self):
        self._add_article(1)
        self._add_image(1, 1)
        db = os.path.join(self.data, "articles.db")
        before = (os.stat(db).st_mtime_ns, hashlib.sha256(_read(db, "rb")).hexdigest())
        with NetworkAndKeychainBlocked():
            self._export()
            rc, _ = self.run_cli(["--export-untranscribed"])
        self.assertEqual(rc, 0)
        after = (os.stat(db).st_mtime_ns, hashlib.sha256(_read(db, "rb")).hexdigest())
        self.assertEqual(before, after)
        self.assertEqual(self.img_row(1)["transcription_status"], "untranscribed")

    def test_missing_database_is_not_created(self):
        rc, out = self.run_cli(["--export-untranscribed"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles_probe")))

    def test_cli_output_has_no_title_or_body(self):
        self._add_article(1)
        self._add_image(1, 1)
        rc, out = self.run_cli(["--export-untranscribed"])
        self.assertEqual(rc, 0)
        self.assertNotIn(TITLE, out)
        self.assertNotIn(BODY_MARK, out)
        self.assertIn("已匯出 1 張", out)

    def test_no_keychain_no_mail_no_notifier_called(self):
        self._add_article(1)
        self._add_image(1, 1)

        def boom(*a, **k):
            raise AssertionError("方案 D 不得呼叫")
        rc, _ = self.run_cli(["--export-untranscribed"], get_secret=boom, fetch_mail=boom, notifier=boom,
                             run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0)


# ====================================================================== 匯入

class ImportTest(Base):
    def setUp(self):
        super().setUp()
        self._add_article(1)
        self.a = self._add_image(1, 1)
        self.b = self._add_image(1, 2, data=make_table_png(320, 200))

    def imp(self, payload, extra=None, folder=None):
        path = self.write_results(payload, folder=folder)
        return self.run_cli(["--import-transcription", path] + (extra or []))

    def test_dry_run_default_writes_nothing_and_prints_lengths_not_text(self):
        text = "| 代號 | 營收 |\n| --- | --- |\n| 2330 | 98765 |"
        db = os.path.join(self.data, "articles.db")
        before = hashlib.sha256(_read(db, "rb")).hexdigest()
        rc, out = self.imp(self.results([self.item(self.a, text), self.item(self.b, is_table=False, text="")]))
        self.assertEqual(rc, 0)
        self.assertIn("預覽（未寫入）：將寫入 2 筆", out)
        self.assertIn("長度=%d" % len(text), out)
        self.assertNotIn("98765", out)
        self.assertNotIn(TITLE, out)
        self.assertEqual(hashlib.sha256(_read(db, "rb")).hexdigest(), before)
        self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed")

    def test_apply_writes_done_and_not_table_with_manual_model(self):
        text = "| 代號 | 營收 |\n| --- | --- |\n| 2330 | 98765 |"
        rc, out = self.imp(self.results([self.item(self.a, text), self.item(self.b, is_table=False, text="")]),
                           ["--apply"])
        self.assertEqual(rc, 0, out)
        ra, rb = self.img_row(self.a), self.img_row(self.b)
        self.assertEqual((ra["transcription_status"], ra["transcription"], ra["transcribed_model"], ra["is_table"]),
                         ("done", text, "manual:claude-code", 1))
        self.assertEqual((rb["transcription_status"], rb["transcription"], rb["transcribed_model"], rb["is_table"]),
                         ("not_table", None, None, 0))
        self.assertNotIn("98765", out)

    def test_audit_row_counts_only(self):
        self.imp(self.results([self.item(self.a)]), ["--apply"])
        rows = self.store().conn.execute("SELECT kind, key FROM alert_log").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "manual_transcription_import")
        self.assertIn("written=1", rows[0]["key"])
        self.assertIn("manual:claude-code", rows[0]["key"])
        self.assertNotIn("98765", rows[0]["key"])
        self.assertEqual(self.store().conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)

    def test_dry_run_writes_no_audit(self):
        self.imp(self.results([self.item(self.a)]))
        self.assertEqual(self.store().conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0], 0)

    def test_done_not_overwritten_without_flag_but_overwritten_with_it(self):
        c = self._add_image(1, 3, status="done", text="舊的 API 轉寫", model="claude-haiku-5-5")
        rc, out = self.imp(self.results([self.item(c, "| 新 |\n| --- |\n| 1 |"), self.item(self.a)]), ["--apply"])
        self.assertEqual(rc, 0)
        self.assertIn("略過已轉寫 1 筆", out)
        self.assertEqual(self.img_row(c)["transcription"], "舊的 API 轉寫")
        self.assertEqual(self.img_row(self.a)["transcription_status"], "done")
        rc, out = self.imp(self.results([self.item(c, "| 新 |\n| --- |\n| 1 |")]), ["--apply", "--overwrite"])
        self.assertEqual(rc, 0)
        r = self.img_row(c)
        self.assertEqual((r["transcription"], r["transcribed_model"]), ("| 新 |\n| --- |\n| 1 |", "manual:claude-code"))

    def test_not_table_also_protected_without_overwrite(self):
        c = self._add_image(1, 3, status="not_table")
        rc, out = self.imp(self.results([self.item(c)]), ["--apply"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.img_row(c)["transcription_status"], "not_table")

    def test_sha_mismatch_rejected_whole_batch(self):
        rc, out = self.imp(self.results([self.item(self.a), self.item(self.b, sha="0" * 64)]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("sha256", out)
        self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed")   # 好的那筆也沒寫

    def test_sha_must_match_manifest_in_same_folder(self):
        self._export_into_folder()
        folder = self.export_dir
        manifest = os.path.join(folder, "manifest.json")
        m = json.loads(_read(manifest))
        m["items"][0]["sha256"] = "f" * 64                     # manifest 被改，與檔案不符
        _write(manifest, json.dumps(m))
        rc, out = self.imp(self.results([self.item(self.a)]), ["--apply"], folder=folder)
        self.assertEqual(rc, 2)
        self.assertIn("manifest", out)

    def test_image_not_in_manifest_rejected(self):
        self._export_into_folder(limit=1)
        rc, out = self.imp(self.results([self.item(self.b)]), ["--apply"], folder=self.export_dir)
        self.assertEqual(rc, 2)
        self.assertIn("manifest", out)

    def test_import_ok_with_manifest_folder(self):
        self._export_into_folder()
        rc, out = self.imp(self.results([self.item(self.a)]), ["--apply"], folder=self.export_dir)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.img_row(self.a)["transcription_status"], "done")

    def _export_into_folder(self, limit=10):
        r = M.export_untranscribed(self.data, limit=limit, now=lambda: NOW)
        self.export_dir = r["out_dir"]

    def test_unknown_image_id_rejected(self):
        rc, out = self.imp(self.results([self.item(self.a), self.item(self.a + 999, sha="1" * 64)]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed")

    def test_bad_inputs_rejected(self):
        good = self.item(self.a)

        def mod(**kw):
            d = copy.deepcopy(good)
            d.update(kw)
            return d
        cases = {
            "model 缺少": {"version": 1, "results": [good]},
            "model 無前綴": self.results([good], model="claude-code"),
            "model 空 agent": self.results([good], model="manual:"),
            "model 含空白": self.results([good], model="manual:a b"),
            "model 含底線": self.results([good], model="manual:a_b"),
            "model 太長": self.results([good], model="manual:" + "a" * 41),
            "model 非字串": self.results([good], model=5),
            "version 錯": {"version": 2, "model": "manual:x", "results": [good]},
            "未知頂層欄位": dict(self.results([good]), extra=1),
            "results 空": self.results([]),
            "results 非陣列": self.results({}),
            "項目非物件": self.results(["x"]),
            "缺欄位": self.results([{"image_id": self.a, "sha256": good["sha256"], "text": "x"}]),
            "多欄位": self.results([mod(note="hi")]),
            "image_id 非整數": self.results([mod(image_id="1")]),
            "image_id 布林": self.results([mod(image_id=True)]),
            "sha 大寫": self.results([mod(sha256=good["sha256"].upper())]),
            "sha 太短": self.results([mod(sha256="abc")]),
            "is_table 非布林": self.results([mod(is_table="yes")]),
            "text 非字串": self.results([mod(text=123)]),
            "text 空但 is_table": self.results([mod(text="  \n")]),
            "非表格卻帶文字": self.results([mod(is_table=False, text="有字")]),
            "text 過長": self.results([mod(text="a" * (M.MAX_TEXT_CHARS + 1))]),
            "控制字元 NUL": self.results([mod(text="a\x00b")]),
            "控制字元 ESC": self.results([mod(text="a\x1b[31mb")]),
            "含 CR": self.results([mod(text="a\rb")]),
            "bidi RLO": self.results([mod(text="a\u202eb")]),
            "bidi 隔離": self.results([mod(text="a\u2066b\u2069")]),
            "零寬空白": self.results([mod(text="a\u200bb")]),
            "BOM": self.results([mod(text="a\ufeffb")]),
            "model 結尾換行": self.results([good], model="manual:x\n"),
            "image_id 重複": self.results([good, copy.deepcopy(good)]),
        }
        for name, payload in cases.items():
            rc, out = self.imp(payload, ["--apply"])
            self.assertEqual(rc, 2, "%s 應被拒絕：%s" % (name, out))
            self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed", name)

    def test_deeply_nested_json_rejected_cleanly(self):
        p = os.path.join(self.tmp, "deep.json")
        _write(p, "[" * 100000 + "]" * 100000)
        rc, out = self.run_cli(["--import-transcription", p])
        self.assertEqual(rc, 2, out)
        self.assertNotIn("Traceback", out)

    def test_apply_db_error_exits_2_with_fixed_message_and_rolls_back(self):
        with mock.patch.object(M, "apply_plan", side_effect=sqlite3.IntegrityError("boom 標題")):
            rc, out = self.imp(self.results([self.item(self.a)]), ["--apply"])
        self.assertEqual(rc, 2, out)
        self.assertIn("rollback", out)
        self.assertNotIn("boom", out)
        self.assertNotIn(TITLE, out)
        self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed")

    def test_non_json_and_missing_and_oversize_file_rejected(self):
        p = os.path.join(self.tmp, "bad.json")
        _write(p, "{not json")
        self.assertEqual(self.run_cli(["--import-transcription", p, "--apply"])[0], 2)
        self.assertEqual(self.run_cli(["--import-transcription", os.path.join(self.tmp, "none.json")])[0], 2)
        arr = os.path.join(self.tmp, "arr.json")
        _write(arr, "[1,2]")
        self.assertEqual(self.run_cli(["--import-transcription", arr])[0], 2)
        with mock.patch.object(M, "MAX_RESULTS_FILE_BYTES", 10):
            p2 = self.write_results(self.results([self.item(self.a)]))
            self.assertEqual(self.run_cli(["--import-transcription", p2])[0], 2)

    def test_secret_like_text_rejected(self):
        for bad in ("sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV", "token: ghp_" + "a" * 30, "Bearer abcdefghijklmnop12345",
                    "password=hunter2", "api_key: abc123", "x" * 5 + "Ab1" * 20,
                    "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"):
            rc, out = self.imp(self.results([self.item(self.a, text="| a |\n" + bad)]), ["--apply"])
            self.assertEqual(rc, 2, bad)
            self.assertNotIn(bad, out)                          # 拒收訊息不回顯內容

    def test_normal_table_text_not_mistaken_for_secret(self):
        long_table = ("| 項目 | 2025Q1 | 2025Q2 |\n| " + "-" * 60 + " | --- | --- |\n"
                      "| 營收 | 1234567890123456789012345678901234567890 | ? |\n| 毛利率 | 31.5% | 30.2% |")
        self.assertFalse(investanchors_redact.secret_like(long_table))
        rc, out = self.imp(self.results([self.item(self.a, text=long_table)]), ["--apply"])
        self.assertEqual(rc, 0, out)

    def test_apply_is_atomic_when_a_write_fails(self):
        s = self.store()
        plan = M.validate_results(self.write_results(self.results([self.item(self.a), self.item(self.b)])), s)
        rows = plan["rows"]
        self.assertEqual(len(rows), 2)
        bad_rows = [rows[0], (rows[1][0], rows[1][1], "bogus", None, "manual:x", True)]
        with self.assertRaises(ValueError):
            s.apply_transcription_batch(bad_rows, audit_kind="k", audit_key="x")
        self.assertEqual(self.img_row(self.a)["transcription_status"], "untranscribed")
        # 寫入中途出錯（第 2 筆 UPDATE 丟例外）→ 第 1 筆也要被 rollback，且稽核列不留
        orig = s._write_transcription
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("disk full")
            return orig(*a, **k)
        s._write_transcription = flaky
        with self.assertRaises(RuntimeError):
            s.apply_transcription_batch(rows, audit_kind="k", audit_key="x")
        s2 = article_store.ArticleStore.open_readonly(self.data)
        self.addCleanup(s2.close)
        self.assertEqual(s2.get_image_by_id(self.a)["transcription_status"], "untranscribed")
        self.assertEqual(s2.conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0], 0)

    def test_missing_image_file_rejected(self):
        os.remove(os.path.join(self.data, self.img_row(self.a)["file_path"]))
        rc, out = self.imp(self.results([self.item(self.b), self.item(self.a, sha="2" * 64)]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("圖檔不存在", out)

    def test_changed_image_file_rejected(self):
        it = self.item(self.a)
        with open(os.path.join(self.data, self.img_row(self.a)["file_path"]), "ab") as f:
            f.write(b"x")
        rc, out = self.imp(self.results([it]), ["--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("不一致", out)

    def test_path_escape_in_db_is_rejected(self):
        outside = os.path.join(self.tmp, "outside.png")
        _write(outside, self.png, "wb")
        s = self.store()
        s.conn.execute("UPDATE article_image SET file_path=? WHERE id=?", ("../outside.png", self.a))
        s.conn.commit()
        rc, out = self.imp(self.results([self.item(self.a, sha=hashlib.sha256(self.png).hexdigest())]), ["--apply"])
        self.assertEqual(rc, 2)

    def test_abandoned_article_rejected(self):
        self._add_article(2, status="abandoned")
        c = self._add_image(2, 1)
        rc, out = self.imp(self.results([self.item(c)]), ["--apply"])
        self.assertEqual(rc, 2)

    def test_apply_requires_existing_db_and_never_creates_one(self):
        shutil.rmtree(self.data)
        os.makedirs(self.data)
        p = self.write_results(self.results([{"image_id": 1, "sha256": "0" * 64, "is_table": True, "text": "x"}]))
        rc, _ = self.run_cli(["--import-transcription", p, "--apply"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles.db")))

    def test_zero_network_zero_keychain_during_import(self):
        path = self.write_results(self.results([self.item(self.a)]))

        def boom(*a, **k):
            raise AssertionError("方案 D 匯入不得呼叫")
        with NetworkAndKeychainBlocked(block_all_subprocess=True) as g:
            rc, out = self.run_cli(["--import-transcription", path, "--apply"], get_secret=boom, fetch_mail=boom,
                                   notifier=boom, run_scraper=boom, download_images=boom, transcribe=boom)
        self.assertEqual(rc, 0, out)
        self.assertEqual(g.attempts, [])
        self.assertEqual(self.img_row(self.a)["transcription_status"], "done")

    def test_import_works_when_transcribe_switch_is_off(self):
        self.assertIsNone(self.store().get_setting("transcribe_enabled"))
        rc, _ = self.imp(self.results([self.item(self.a)]), ["--apply"])
        self.assertEqual(rc, 0)
        self.assertIsNone(self.store().get_setting("transcribe_enabled"))     # 匯入不改開關


class ProductionGuardTest(Base):
    def test_production_dir_refused_before_anything_else(self):
        real = article_data_guard.PRODUCTION_DATA_DIR
        path = os.path.join(self.tmp, "r.json")
        _write(path, "{}")
        for argv in (["--import-transcription", path, "--apply"], ["--import-transcription", path],
                     ["--export-untranscribed"]):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(article_data_guard.ALLOW_FLAG, None)
                with mock.patch.object(article_store, "ArticleStore") as st:
                    rc = I.run(["--data-dir", real] + argv, out=out)
                st.open_readonly.assert_not_called()
                st.assert_not_called()
            self.assertEqual(rc, 2, argv)
            self.assertIn("正式資料庫", out.getvalue())

    def test_missing_data_dir_is_a_usage_error(self):
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            I.run(["--export-untranscribed"])


# ====================================================================== --retranscribe 不蓋掉手動轉寫

class RetranscribeKeepsManualTest(Base):
    def test_model_change_retranscribe_skips_manual_rows_but_redoes_api_rows(self):
        self._add_article(1)
        manual = self._add_image(1, 1, status="done", text="手動轉寫內容", model="manual:claude-code")
        api = self._add_image(1, 2, status="done", text="舊模型內容", model="old-model")
        self.store().set_setting("transcribe_enabled", "1")
        seen = []

        def fake_transcribe(tiles, **kw):
            seen.append(len(tiles))
            return {"status": "transcribed", "is_table": True, "text": "新模型內容", "model": "new-model",
                    "reason": None, "abort": False}
        rc, out = self.run_cli(["--retranscribe"], transcribe=fake_transcribe, get_secret=lambda *a, **k: "k",
                               sleeper=lambda s: None)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.img_row(manual)["transcription"], "手動轉寫內容")
        self.assertEqual(self.img_row(manual)["transcribed_model"], "manual:claude-code")
        self.assertEqual(self.img_row(api)["transcription"], "新模型內容")


# ====================================================================== 顯示與搜尋

class DisplayAndSearchTest(Base):
    def setUp(self):
        super().setUp()
        self._add_article(1)
        self.a = self._add_image(1, 1)
        self._add_article(2)
        self.api = self._add_image(2, 1, status="done", text="毛利率 77.7% API版", model="claude-haiku-5-5")

    def _manual_import(self, text):
        path = self.write_results(self.results([self.item(self.a, text)]))
        rc, out = self.run_cli(["--import-transcription", path, "--apply"])
        self.assertEqual(rc, 0, out)

    def test_get_article_labels_manual_vs_api_and_both_warn(self):
        self._manual_import("| 營收 | 98765 |\n| --- | --- |")
        s = article_store.ArticleStore.open_readonly(self.data)
        self.addCleanup(s.close)
        manual = article_tools.get_article_text(s, 1)
        api = article_tools.get_article_text(s, 2)
        self.assertIn("【圖片轉寫，手動（agent：claude-code），可能有誤，請以原圖為準】", manual)
        self.assertIn("98765", manual)
        self.assertNotIn(article_tools.TRANSCRIPTION_WARNING, manual)
        self.assertIn(article_tools.TRANSCRIPTION_WARNING, api)
        self.assertNotIn("手動", api)
        self.assertIn("已轉寫", manual)

    def test_search_finds_manual_transcription_like_api_one(self):
        self._manual_import("| 營收 | 98765 |")
        s = article_store.ArticleStore.open_readonly(self.data)
        self.addCleanup(s.close)
        r_manual = s.search_articles("98765")
        r_api = s.search_articles("77.7%")
        self.assertEqual([r["article_id"] for r in r_manual], [1])
        self.assertEqual([r["article_id"] for r in r_api], [2])
        self.assertEqual(r_manual[0]["source"], r_api[0]["source"])
        self.assertIn("98765", article_tools.search_articles_text(s, "98765"))

    def test_display_and_search_do_not_depend_on_transcribe_switch(self):
        """查證結論：transcribe_enabled 只管「是否呼叫外部 API」，不影響顯示與搜尋已存在的轉寫。"""
        self._manual_import("| 營收 | 98765 |")
        s = self.store()
        for value in (None, "0", "1"):
            if value is not None:
                s.set_setting("transcribe_enabled", value)
            ro = article_store.ArticleStore.open_readonly(self.data)
            try:
                self.assertEqual([r["article_id"] for r in ro.search_articles("98765")], [1])
                self.assertIn("98765", article_tools.get_article_text(ro, 1))
            finally:
                ro.close()


# ====================================================================== CLI 旗標互斥

class CliExclusivityTest(Base):
    def setUp(self):
        super().setUp()
        self._add_article(1)
        self.a = self._add_image(1, 1)
        self.results_path = self.write_results(self.results([self.item(self.a)]))

    def test_export_and_import_mutually_exclusive(self):
        rc, _ = self.run_cli(["--export-untranscribed", "--import-transcription", self.results_path])
        self.assertEqual(rc, 2)

    def test_conflicts_with_other_actions(self):
        others = [["--transcribe-sample", "1"], ["--retranscribe"], ["--dry-run"], ["--resume"],
                  ["--force-weekly"], ["--enable-transcription"], ["--disable-transcription"],
                  ["--max-articles", "1"], ["--reset-abandoned", "1"], ["--backfill-since", "2026-01-01"],
                  ["--retranscribe", "--reset-transcribe-attempts"]]
        for extra in others:
            for base in (["--export-untranscribed"], ["--import-transcription", self.results_path]):
                rc, out = self.run_cli(base + extra)
                self.assertEqual(rc, 2, (base, extra, out))
                self.assertIn("不可與其他動作旗標併用", out)
        s = self.store()
        self.assertIsNone(s.get_setting("transcribe_enabled"))            # 沒有任何副作用
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.data, "articles_probe")))

    def test_dependent_flags_need_their_action(self):
        for argv in (["--apply"], ["--overwrite"], ["--limit", "3"], ["--apply", "--overwrite"]):
            rc, out = self.run_cli(argv)
            self.assertEqual(rc, 2, argv)
        rc, _ = self.run_cli(["--export-untranscribed", "--apply"])
        self.assertEqual(rc, 2)
        rc, _ = self.run_cli(["--export-untranscribed", "--overwrite"])
        self.assertEqual(rc, 2)
        rc, _ = self.run_cli(["--import-transcription", self.results_path, "--limit", "3"])
        self.assertEqual(rc, 2)

    def test_existing_flags_unchanged(self):
        rc, out = self.run_cli(["--reset-transcribe-attempts"])
        self.assertEqual(rc, 2)
        self.assertIn("--retranscribe", out)
        rc, out = self.run_cli(["--retranscribe"])               # 開關未開仍被拒
        self.assertEqual(rc, 2)
        self.assertIn("轉寫開關未開", out)


# ====================================================================== 外洩

class LeakTest(Base):
    def test_outputs_and_manifest_exclude_title_body_and_transcription_text(self):
        self._add_article(1)
        iid = self._add_image(1, 1)
        secret_text = "| 機密數字 | 424242 |\n| --- | --- |"
        collected = []
        rc, out = self.run_cli(["--export-untranscribed"])
        collected.append(out)
        folder = os.path.join(self.data, "articles_probe", os.listdir(os.path.join(self.data, "articles_probe"))[0])
        for name in ("manifest.json", "AGENT_GUIDE.md"):
            collected.append(_read(os.path.join(folder, name)))
        path = self.write_results(self.results([self.item(iid, secret_text)]), folder=folder)
        rc, out = self.run_cli(["--import-transcription", path])
        collected.append(out)
        rc, out = self.run_cli(["--import-transcription", path, "--apply"])
        collected.append(out)
        rows = self.store().conn.execute("SELECT kind, key, day FROM alert_log").fetchall()
        collected.append(json.dumps([dict(r) for r in rows]))
        blob = "\n".join(collected)
        for bad in (TITLE, BODY_MARK, "424242", "機密數字"):
            self.assertNotIn(bad, blob)

    def test_rejection_messages_never_echo_content(self):
        self._add_article(1)
        iid = self._add_image(1, 1)
        marker = "ZZ內容標記ZZ\x00"
        rc, out = self.run_cli(["--import-transcription",
                                self.write_results(self.results([self.item(iid, marker)]))])
        self.assertEqual(rc, 2)
        self.assertNotIn("內容標記", out)


if __name__ == "__main__":
    unittest.main()
