"""T037／T038／T040：轉寫接進匯入流程、轉寫開關（預設關閉）、--retranscribe、--transcribe-sample。

只用合成圖與本機假模型 server（127.0.0.1）＋假 get_secret；不連真實網路、不讀真實鑰匙圈、不動正式庫。"""
import datetime
import glob
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import article_data_guard  # noqa: E402
import article_store  # noqa: E402
import investanchors_import as I  # noqa: E402
import keychain_secrets  # noqa: E402
from test_article_image_tiles import _png_from_raw, make_table_png  # noqa: E402
from test_article_transcribe import FakeServer, ok_resp  # noqa: E402
from test_investanchors_import import Harness, WED, art, clue, li, summ  # noqa: E402

VKEY = "sk-ant-FAKE-VISION-KEY-0123456789"


def solid_png(width, height):
    """標頭宣稱 width×height 的小檔（只為測尺寸判斷；不會被送去切片）。"""
    return _png_from_raw(width, height, b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height)))


class Env(object):
    """Harness＋假模型 server＋計數用假 get_secret＋會寫出合成 PNG 的假下載器。"""

    def __init__(self, test, responses=None, png=None):
        self.test = test
        self.h = Harness(test)
        self.server = FakeServer(responses or [ok_resp(True, "代號|營收\n2330|98765")])
        test.addCleanup(self.server.close)
        self.vision_calls = 0
        self.png = png or make_table_png(300, 200)
        self.tiler_calls = []

    def get_secret(self, account, runner=None, service=None):
        if account == "vision-api-key":
            self.vision_calls += 1
            return VKEY
        return self.h._secret(account, runner, service)

    def download(self, store, aid, data_dir, **kw):
        for im in store.list_images(aid):
            if im.get("file_path"):
                continue
            rel = os.path.join("articles_images", str(aid), "%d.png" % im["seq"])
            full = os.path.join(data_dir, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(self.png)
            store.set_image_file(aid, im["seq"], rel)
        return {"downloaded": [], "failed": []}

    def deps(self, **over):
        d = dict(get_secret=self.get_secret, download_images=self.download, transcribe_api_url=self.server.url,
                 sleeper=lambda s: None, tiles_runner=self._no_runner)
        d.update(over)
        return d

    def _no_runner(self, cfg):
        self.tiler_calls.append(cfg["mode"])
        raise AssertionError("短圖不該啟動切片器")

    def run(self, argv=None, **over):
        return self.h.run(argv, **self.deps(**over))

    def import_article(self, aid, images=2, day_offset=0):
        urls = ["http://127.0.0.1/img%d-%d.png" % (aid, i) for i in range(1, images + 1)]
        self.h.script = lambda p: [li(aid), art(aid, images=urls), summ()]
        self.h.clock[0] = WED + datetime.timedelta(days=day_offset)
        self.h.clues = [clue("<m%d@x>" % aid)]
        return self.run()

    def statuses(self):
        s = self.h.store()
        return [(i["article_id"], i["seq"], i["transcription_status"]) for a in
                [r[0] for r in s.conn.execute("SELECT article_id FROM article ORDER BY article_id")]
                for i in s.list_images(a)]

    def requests(self):
        return len(self.server.requests)


class SwitchTest(unittest.TestCase):
    def test_1_default_off_with_key_in_keychain_makes_zero_api_calls_and_zero_key_reads(self):
        e = Env(self)
        self.assertEqual(e.import_article(1001), 0)
        self.assertEqual(e.requests(), 0)
        self.assertEqual(e.vision_calls, 0)
        self.assertEqual([x[2] for x in e.statuses()], ["untranscribed", "untranscribed"])
        s = e.h.store()
        self.assertTrue(all(i["file_path"] and os.path.isfile(os.path.join(e.h.tmp, i["file_path"]))
                            for i in s.list_images(1001)))          # 圖片照常下載
        self.assertIsNone(s.get_setting("transcribe_enabled"))       # 無此列＝關

    def test_2_enable_then_import_transcribes_and_writes(self):
        e = Env(self)
        self.assertEqual(e.run(["--enable-transcription"]), 0)
        self.assertEqual(e.import_article(1001), 0)
        self.assertGreater(e.requests(), 0)
        self.assertGreater(e.vision_calls, 0)
        self.assertEqual([x[2] for x in e.statuses()], ["done", "done"])
        im = e.h.store().list_images(1001)[0]
        self.assertIn("98765", im["transcription"])
        self.assertEqual((im["is_table"], im["transcribed_model"]), (1, "claude-haiku-5-5"))

    def test_3_disable_again_new_images_not_transcribed(self):
        e = Env(self)
        e.run(["--enable-transcription"])
        e.import_article(1001, images=1)
        before_req, before_key = e.requests(), e.vision_calls
        self.assertGreater(before_req, 0)
        self.assertEqual(e.run(["--disable-transcription"]), 0)
        e.import_article(1002, images=2, day_offset=1)
        self.assertEqual((e.requests(), e.vision_calls), (before_req, before_key))
        self.assertEqual(e.statuses(), [(1001, 1, "done"), (1002, 1, "untranscribed"), (1002, 2, "untranscribed")])

    def test_4_retranscribe_refused_when_off(self):
        e = Env(self)
        e.import_article(1001)
        scraper_calls = len(e.h.payloads)
        self.assertEqual(e.run(["--retranscribe"]), 2)
        self.assertIn("轉寫開關未開", e.h.out.getvalue())
        self.assertEqual((e.requests(), e.vision_calls, len(e.h.payloads)), (0, 0, scraper_calls))

    def test_5_state_survives_reopening_the_store(self):
        e = Env(self)
        e.run(["--enable-transcription"])
        s = article_store.ArticleStore(e.h.tmp)
        self.assertEqual(s.get_setting("transcribe_enabled"), "1")
        s.close()
        e.run(["--disable-transcription"])
        s = article_store.ArticleStore(e.h.tmp)
        self.assertEqual(s.get_setting("transcribe_enabled"), "0")
        s.close()

    def test_toggle_is_idempotent_prints_state_and_does_nothing_else(self):
        e = Env(self)
        fetched = []
        for _ in range(2):
            self.assertEqual(e.run(["--enable-transcription"], fetch_mail=lambda: fetched.append(1) or []), 0)
        self.assertIn("已開啟", e.h.out.getvalue())
        self.assertEqual(e.run(["--disable-transcription"]), 0)
        self.assertIn("已關閉", e.h.out.getvalue())
        self.assertEqual((fetched, e.h.payloads, e.vision_calls, e.requests()), ([], [], 0, 0))
        self.assertEqual(e.h.store().recent_runs(5), [])

    def test_toggle_refuses_combination_with_other_actions(self):
        e = Env(self)
        self.assertEqual(e.run(["--enable-transcription", "--retranscribe"]), 2)
        self.assertIsNone(e.h.store().get_setting("transcribe_enabled"))

    def test_new_flags_go_through_data_guard(self):
        env = dict(os.environ)
        env.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
        for flags in (["--enable-transcription"], ["--disable-transcription"], ["--retranscribe"],
                      ["--transcribe-sample", "1"]):
            with mock.patch.dict(os.environ, env, clear=True):
                called = []
                rc = I.run(["--data-dir", article_data_guard.PRODUCTION_DATA_DIR] + flags,
                           get_secret=lambda *a, **k: called.append(a), fetch_mail=lambda: called.append(1))
            self.assertEqual(rc, 2, flags)
            self.assertEqual(called, [])


class ImportFlowTest(unittest.TestCase):
    def test_transcription_failure_keeps_article_and_image_then_retranscribe_fills_in(self):
        e = Env(self, responses=[(500, {"error": {"message": "boom"}})])
        e.run(["--enable-transcription"])
        self.assertEqual(e.import_article(1001, images=1), 0)         # 轉寫失敗不影響匯入結果
        s = e.h.store()
        self.assertEqual(s.get_article_row(1001)["status"], "fetched")
        im = s.list_images(1001)[0]
        self.assertTrue(os.path.isfile(os.path.join(e.h.tmp, im["file_path"])))
        self.assertEqual((im["transcription_status"], im["transcription"]), ("untranscribed", None))
        # 模型恢復後補轉；不啟動 scraper、不登入
        e.server.responses[:] = [ok_resp(True, "補轉成功|1")]
        del e.server.requests[:]
        scraper_calls = len(e.h.payloads)
        self.assertEqual(e.run(["--retranscribe"]), 0)
        self.assertEqual(len(e.h.payloads), scraper_calls)           # run_scraper 呼叫數 0
        self.assertGreater(e.requests(), 0)
        im = e.h.store().list_images(1001)[0]
        self.assertEqual((im["transcription_status"], im["transcription"]), ("done", "補轉成功|1"))
        self.assertEqual(e.h.store().logins_today(e.h.clock[0]), 1)  # 沒有多登入

    def test_not_table_is_recorded_without_text(self):
        e = Env(self, responses=[ok_resp(False, "")])
        e.run(["--enable-transcription"])
        e.import_article(1001, images=1)
        im = e.h.store().list_images(1001)[0]
        self.assertEqual((im["transcription_status"], im["transcription"], im["is_table"]), ("not_table", None, 0))

    def test_abort_stops_remaining_images_this_run_then_retranscribe_resumes(self):
        e = Env(self, responses=[(401, {"error": {"message": "invalid x-api-key"}})])
        e.run(["--enable-transcription"])
        e.import_article(1001, images=3)
        self.assertEqual(e.requests(), 1)                              # 第一張就中止，其餘不再送
        self.assertEqual([x[2] for x in e.statuses()], ["untranscribed"] * 3)
        e.server.responses[:] = [ok_resp(True, "x|y")]
        self.assertEqual(e.run(["--retranscribe"]), 0)
        self.assertEqual([x[2] for x in e.statuses()], ["done"] * 3)

    def test_retranscribe_redoes_images_from_other_model_only(self):
        e = Env(self)
        e.run(["--enable-transcription"])
        e.import_article(1001, images=1)
        del e.server.requests[:]
        self.assertEqual(e.run(["--retranscribe"]), 0)                 # 同模型：不重轉
        self.assertEqual(e.requests(), 0)
        e.server.responses[:] = [ok_resp(True, "新模型|1")]
        self.assertEqual(e.run(["--retranscribe"], transcribe_model="claude-test-next"), 0)
        im = e.h.store().list_images(1001)[0]
        self.assertEqual((im["transcribed_model"], im["transcription"]), ("claude-test-next", "新模型|1"))
        self.assertEqual(e.server.requests[0][1]["model"], "claude-test-next")


class BackfillTest(unittest.TestCase):
    """2026-11-15 審查：夜間補轉先前未轉寫的圖＋失敗次數上限。"""

    def _seed(self, e, n_articles=1, per=1, start=2001):
        s = article_store.ArticleStore(e.h.tmp)
        for aid in range(start, start + n_articles):
            s.upsert_discovered(aid, "https://investanchors.com/user/vip_contents/%d" % aid, "t%d" % aid)
            s.mark_fetched(aid, "內文。" * 100)
            for seq in range(1, per + 1):
                s.add_image(aid, seq, "http://127.0.0.1/%d-%d.png" % (aid, seq))
                rel = os.path.join("articles_images", str(aid), "%d.png" % seq)
                os.makedirs(os.path.join(e.h.tmp, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(e.h.tmp, rel), "wb") as f:
                    f.write(e.png)
                s.set_image_file(aid, seq, rel)
        s.close()

    def _attempts(self, e):
        return [r[0] for r in e.h.store().conn.execute(
            "SELECT transcribe_attempts FROM article_image ORDER BY article_id, seq")]

    def test_enabled_nightly_run_backfills_at_most_ten_old_images(self):
        e = Env(self)
        self._seed(e, n_articles=4, per=4)                             # 16 張舊圖
        e.run(["--enable-transcription"])
        self.assertEqual(e.run(), 0)                                   # 無觸發也補轉
        done = [x for x in e.statuses() if x[2] == "done"]
        self.assertEqual(len(done), I.BACKFILL_TRANSCRIBE_PER_RUN)
        self.assertEqual(e.requests(), 10)
        self.assertEqual(done[0][:2], (2001, 1))                       # 依 article_id／seq
        self.assertEqual(e.h.store().transcription_counts()["untranscribed"], 6)
        self.assertEqual(e.run(), 0)                                   # 下一輪補完剩下的
        self.assertEqual(e.h.store().transcription_counts()["untranscribed"], 0)

    def test_backfill_runs_after_new_article_with_trigger_and_skips_images_just_tried(self):
        e = Env(self, responses=[(500, {"error": {"message": "boom"}})])
        self._seed(e, n_articles=1, per=1)
        e.run(["--enable-transcription"])
        self.assertEqual(e.import_article(1001, images=1), 0)          # 新圖失敗＋舊圖補轉失敗
        by = dict(((a, q), n) for (a, q), n in zip([(2001, 1), (1001, 1)], [
            e.h.store().conn.execute("SELECT transcribe_attempts FROM article_image WHERE article_id=?",
                                     (a,)).fetchone()[0] for a in (2001, 1001)]))
        self.assertEqual(by, {(2001, 1): 1, (1001, 1): 1})             # 新圖本次只計 1 次（不被補轉重複試）

    def test_failures_stop_auto_backfill_at_cap_but_retranscribe_still_tries(self):
        e = Env(self, responses=[(500, {"error": {"message": "boom"}})])
        self._seed(e)
        e.run(["--enable-transcription"])
        for i in range(I.MAX_TRANSCRIBE_ATTEMPTS):
            e.run()
            self.assertEqual(self._attempts(e), [i + 1])
        del e.server.requests[:]
        e.run()                                                        # 達上限：不再自動補轉
        self.assertEqual((e.requests(), self._attempts(e)), (0, [3]))
        self.assertEqual(e.h.store().transcription_counts(), {"untranscribed": 1, "exhausted": 1})
        e.run(["--retranscribe"])                                      # 手動仍會試
        self.assertGreater(e.requests(), 0)
        self.assertEqual(self._attempts(e), [4])

    def test_reset_attempts_flag_makes_exhausted_image_auto_backfill_again(self):
        e = Env(self, responses=[(401, {"error": {"message": "invalid x-api-key"}})])
        self._seed(e)
        s = article_store.ArticleStore(e.h.tmp)
        s.conn.execute("UPDATE article_image SET transcribe_attempts=3")
        s.conn.commit()
        s.close()
        e.run(["--enable-transcription"])
        e.run()
        self.assertEqual(e.requests(), 0)                              # 達上限：夜間不碰
        self.assertEqual(e.run(["--retranscribe", "--reset-transcribe-attempts"]), 1)   # 401 abort
        self.assertEqual(self._attempts(e), [0])                       # abort 沒送出：歸零後不計次
        e.server.responses[:] = [ok_resp(True, "補轉|1")]
        e.run()
        self.assertEqual([x[2] for x in e.statuses()], ["done"])

    def test_reset_flag_only_valid_with_retranscribe(self):
        e = Env(self)
        for argv in (["--reset-transcribe-attempts"], ["--enable-transcription", "--reset-transcribe-attempts"]):
            self.assertEqual(e.run(argv), 2)
        self.assertIn("只能與 --retranscribe 併用", e.h.out.getvalue())
        self.assertIsNone(e.h.store().get_setting("transcribe_enabled"))

    def test_switch_off_no_backfill_no_counting_no_key_read(self):
        e = Env(self)
        self._seed(e, n_articles=2, per=2)
        self.assertEqual(e.run(), 0)
        self.assertEqual((e.requests(), e.vision_calls, self._attempts(e)), (0, 0, [0, 0, 0, 0]))
        self.assertEqual([x[2] for x in e.statuses()], ["untranscribed"] * 4)

    def test_abort_stops_backfill_and_does_not_count(self):
        e = Env(self, responses=[(401, {"error": {"message": "invalid x-api-key"}})])
        self._seed(e, n_articles=1, per=3)
        e.run(["--enable-transcription"])
        e.run()
        self.assertEqual(e.requests(), 1)                              # abort 後本次停止
        self.assertEqual(self._attempts(e), [0, 0, 0])

    def test_backfill_orders_by_fewest_attempts_first(self):
        e = Env(self)
        self._seed(e, n_articles=1, per=2)
        s = article_store.ArticleStore(e.h.tmp)
        s.bump_transcribe_attempts(2001, 1)
        self.assertEqual([i["seq"] for i in s.images_to_backfill(10)], [2, 1])
        s.close()


class SampleTest(unittest.TestCase):
    def _fill(self, e, specs):
        """specs: [(aid, seq, png_bytes)]，直接寫入庫與磁碟（不經匯入）。"""
        s = article_store.ArticleStore(e.h.tmp)
        for aid, seq, data in specs:
            if s.get_article_row(aid) is None:
                s.upsert_discovered(aid, "https://investanchors.com/user/vip_contents/%d" % aid, "t%d" % aid)
                s.mark_fetched(aid, "內文。" * 100)
            s.add_image(aid, seq, "http://127.0.0.1/%d-%d.png" % (aid, seq))
            rel = os.path.join("articles_images", str(aid), "%d.png" % seq)
            os.makedirs(os.path.join(e.h.tmp, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(e.h.tmp, rel), "wb") as f:
                f.write(data)
            s.set_image_file(aid, seq, rel)
        s.close()

    def _long_runner(self, e):
        import test_article_image_tiles as TT

        def fake(cfg):
            e.tiler_calls.append(cfg["mode"])
            if cfg["mode"] == "bands":
                return [{"type": "bands", "width": 1000, "height": 2600, "bands": TT.blank_bands(2600)}]
            out = []
            for i, (top, bottom) in enumerate(cfg["cuts"], 1):
                tp = os.path.join(cfg["out_dir"], "tile_%02d.png" % i)
                with open(tp, "wb") as f:
                    f.write(make_table_png(1000, bottom - top))
                out.append({"type": "tile", "index": i, "path": tp, "width": 1000, "height": bottom - top})
            return out
        return fake

    def _dump(self, e):
        return [(r[0], r[1], r[2]) for r in e.h.store().conn.execute(
            "SELECT article_id, seq, transcription_status FROM article_image ORDER BY 1,2")]

    def test_sample_includes_long_image_writes_file_not_db_and_never_logs_in(self):
        e = Env(self, responses=[ok_resp(True, "抽樣|轉寫")])
        self._fill(e, [(1, 1, solid_png(300, 200)), (1, 2, solid_png(400, 300)), (2, 1, make_table_png(1000, 2600)),
                       (2, 2, solid_png(200, 100))])
        before = self._dump(e)
        for _ in range(5):                                             # 隨機抽樣：多跑幾次都必含長圖
            del e.server.requests[:]
            rc = e.run(["--transcribe-sample", "2"], tiles_runner=self._long_runner(e))
            self.assertEqual(rc, 0)
            out = sorted(glob.glob(os.path.join(e.h.tmp, "articles_probe", "transcribe-sample-*.md")))[-1]
            with open(out, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("｜長圖", text)
            self.assertEqual(text.count("## "), 2)
            self.assertIn("抽樣|轉寫", text)
            self.assertNotIn(VKEY, text)
            self.assertEqual(self._dump(e), before)                    # 不寫 DB
        self.assertEqual(e.h.payloads, [])                             # 不登入
        self.assertEqual(e.h.store().recent_runs(5), [])
        self.assertGreater(e.vision_calls, 0)                          # 開關關閉時仍可呼叫模型（唯一例外）

    def test_sample_reports_insufficient_count_without_calling_model(self):
        e = Env(self)
        self._fill(e, [(1, 1, make_table_png(1000, 2600)), (1, 2, solid_png(300, 200))])
        self.assertEqual(e.run(["--transcribe-sample", "5"]), 1)
        self.assertIn("不足", e.h.out.getvalue())
        self.assertIn("2 張", e.h.out.getvalue())
        self.assertEqual((e.requests(), e.vision_calls), (0, 0))
        self.assertFalse(os.path.exists(os.path.join(e.h.tmp, "articles_probe")))

    def test_sample_reports_when_no_long_image(self):
        e = Env(self)
        self._fill(e, [(1, 1, solid_png(300, 200)), (1, 2, solid_png(400, 300))])
        self.assertEqual(e.run(["--transcribe-sample", "2"]), 1)
        self.assertIn("沒有長圖", e.h.out.getvalue())
        self.assertEqual((e.requests(), e.vision_calls), (0, 0))

    def test_sample_without_db_is_reported(self):
        e = Env(self)
        self.assertEqual(e.run(["--transcribe-sample", "1"]), 1)
        self.assertFalse(os.path.exists(os.path.join(e.h.tmp, "articles.db")))   # 唯讀，不建庫


if __name__ == "__main__":
    unittest.main()
