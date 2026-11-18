"""paddle_eval 測試（010 方案 C）：假轉寫函式、本機暫存資料夾；不依賴真實 paddle，不連網。"""
import datetime
import json
import os
import re
import socket
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import paddle_eval as pe  # noqa: E402
import article_transcribe_paddle as ap  # noqa: E402

TITLE = "這是一個絕對不能出現在報告裡的文章標題"


def make_png(path, w=100, h=80):
    """寫一張只有合法標頭的 PNG（尺寸讀取只看 IHDR；不需要真的像素）。"""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


def ok_result(text="| a | b |\n| --- | --- |\n| 1 | 2 |", elapsed=1.5, low=None, mode="ocr_grid"):
    return {"status": "transcribed", "is_table": True, "text": text, "model": "paddleocr-9.9/server/%s" % mode,
            "reason": None, "abort": False, "retryable": False, "detail": None,
            "meta": {"mode": mode, "tiles": 1, "elapsed": elapsed, "low_confidence": low or [], "warnings": []}}


def fail_result(reason="no_text_detected", abort=False, elapsed=0.5):
    r = ap._fail(reason, abort=abort)
    r["meta"] = {"elapsed": elapsed}
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.out = os.path.join(self.d, "out")
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.msgs = []
        self.now = lambda: datetime.datetime(2026, 11, 18, 9, 30, 5)

    def img_dir(self, n=3, long_at=None):
        p = os.path.join(self.d, "imgs")
        os.makedirs(p, exist_ok=True)
        for i in range(n):
            make_png(os.path.join(p, "img%02d.png" % i), 100, 80)
        if long_at is not None:
            make_png(os.path.join(p, "img%02d.png" % long_at), 200, 2400)
        return p

    def run_eval(self, argv, transcribe, **kw):
        return pe.run(argv + ["--out", self.out], transcribe=transcribe, now=self.now, say=self.msgs.append,
                      guard=False, **kw)

    def report(self):
        names = os.listdir(self.out)
        self.assertEqual(len(names), 1, names)
        self.assertRegex(names[0], r"^paddle-eval-\d{8}-\d{6}\.md$")
        with open(os.path.join(self.out, names[0]), encoding="utf-8") as f:
            return f.read()


class LoadInputsTest(Base):
    def test_folder_sorted_images_only(self):
        p = self.img_dir(3)
        open(os.path.join(p, "notes.txt"), "w").close()
        items = pe.load_inputs(p)
        self.assertEqual([i["label"] for i in items], ["img00.png", "img01.png", "img02.png"])

    def test_json_manifest_ignores_title(self):
        p = self.img_dir(2)
        m = os.path.join(self.d, "m.json")
        with open(m, "w", encoding="utf-8") as f:
            json.dump({"images": [{"path": os.path.join(p, "img00.png"), "article_id": "1763", "seq": 1, "title": TITLE},
                                  os.path.join(p, "img01.png")]}, f, ensure_ascii=False)
        items = pe.load_inputs(m)
        self.assertEqual(items[0]["label"], "article_id=1763 seq=1")
        self.assertEqual(items[1]["label"], "img01.png")
        self.assertNotIn(TITLE, json.dumps(items, ensure_ascii=False))

    def test_transcribe_sample_report_as_manifest(self):
        p = self.img_dir(2)
        md = os.path.join(self.d, "transcribe-sample-20261118-010101.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# 轉寫抽查（模型 claude-haiku-5-5；不寫資料庫）\n\n"
                    "## 1. article_id=1763000000001 seq=1｜2190x5195｜長圖\n原圖：%s\n\n狀態：transcribed\n\n```\n| a |\n```\n\n"
                    "## 2. article_id=1763000000002 seq=2｜1653x993\n原圖：%s\n" % (
                        os.path.join(p, "img00.png"), os.path.join(p, "img01.png")))
        items = pe.load_inputs(md)
        self.assertEqual([i["label"] for i in items], ["article_id=1763000000001 seq=1", "article_id=1763000000002 seq=2"])
        self.assertTrue(items[0]["path"].endswith("img00.png"))

    def test_txt_manifest_relative_paths_and_comments(self):
        p = self.img_dir(1)
        m = os.path.join(self.d, "list.txt")
        with open(m, "w", encoding="utf-8") as f:
            f.write("# 註解\nimgs/img00.png\n\n")
        items = pe.load_inputs(m)
        self.assertEqual(items[0]["path"], os.path.join(self.d, "imgs/img00.png"))

    def test_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            pe.load_inputs(os.path.join(self.d, "nope"))


class RunTest(Base):
    def test_report_format_and_summary(self):
        p = self.img_dir(3, long_at=2)
        times = iter([1.0, 2.0, 6.0])
        code = self.run_eval([p], lambda path, mode, **kw: ok_result(elapsed=next(times)))
        self.assertEqual(code, 0)
        text = self.report()
        self.assertIn("paddle-eval", os.listdir(self.out)[0])
        self.assertIn("## 總結", text)
        self.assertRegex(text, r"\| ocr_grid \| 3 \| 3 \| 0 \| 3\.00 \| 9\.00 \|")        # 平均 3.00、總 9.00
        self.assertIn("## 1. img00.png｜100x80", text)
        self.assertIn("## 3. img02.png｜200x2400｜長圖", text)                                # 長圖標記
        self.assertIn("原圖：%s" % os.path.join(p, "img00.png"), text)
        self.assertIn("狀態：transcribed", text)
        self.assertIn("| a | b |\n| --- | --- |\n| 1 | 2 |", text)
        self.assertIn("產生時間：2026-11-18 09:30:05", text)
        self.assertEqual(os.listdir(self.out), ["paddle-eval-20261118-093005.md"])
        self.assertTrue(any("失敗 0" in m for m in self.msgs))

    def test_failures_counted_and_exit_code_1(self):
        p = self.img_dir(3)
        results = iter([ok_result(), fail_result("no_text_detected"), fail_result("engine_error:RuntimeError")])
        code = self.run_eval([p], lambda path, mode, **kw: next(results))
        self.assertEqual(code, 1)
        text = self.report()
        self.assertRegex(text, r"\| ocr_grid \| 3 \| 1 \| 2 \|")
        self.assertIn("untranscribed:no_text_detected", text)
        self.assertIn("狀態：untranscribed（engine_error:RuntimeError）", text)

    def test_exception_in_one_image_does_not_stop_run(self):
        p = self.img_dir(2)
        calls = []

        def tr(path, mode, **kw):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return ok_result()
        code = self.run_eval([p], tr)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("exception:RuntimeError", self.report())

    def test_abort_skips_rest_and_exits_3(self):
        p = self.img_dir(3)
        calls = []

        def tr(path, mode, **kw):
            calls.append(path)
            return fail_result("paddle_not_installed", abort=True)
        code = self.run_eval([p], tr)
        self.assertEqual(code, 3)
        self.assertEqual(len(calls), 1)
        self.assertIn("skipped_after_abort", self.report())
        self.assertTrue(any("pip install" in m for m in self.msgs))

    def test_missing_model_abort_hint(self):
        p = self.img_dir(1)
        code = self.run_eval([p], lambda path, mode, **kw: fail_result("model_not_available", abort=True))
        self.assertEqual(code, 3)
        self.assertTrue(any("allow-download" in m for m in self.msgs))

    def test_mode_both_runs_each_mode(self):
        p = self.img_dir(2)
        seen = []

        def tr(path, mode, **kw):
            seen.append(mode)
            return ok_result(mode=mode, elapsed=2.0 if mode == "ocr_grid" else 4.0)
        code = self.run_eval([p, "--mode", "both"], tr)
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["ocr_grid", "table_pipeline", "ocr_grid", "table_pipeline"])
        text = self.report()
        self.assertIn("### 模式 ocr_grid", text)
        self.assertIn("### 模式 table_pipeline", text)
        self.assertRegex(text, r"\| table_pipeline \| 2 \| 2 \| 0 \| 4\.00 \|")

    def test_limit(self):
        p = self.img_dir(5)
        seen = []
        self.run_eval([p, "--limit", "2"], lambda path, mode, **kw: seen.append(path) or ok_result())
        self.assertEqual(len(seen), 2)

    def test_bad_args_exit_2(self):
        p = self.img_dir(1)
        self.assertEqual(self.run_eval([p, "--limit", "0"], lambda *a, **k: ok_result()), 2)
        empty = os.path.join(self.d, "empty")
        os.makedirs(empty)
        self.assertEqual(self.run_eval([empty], lambda *a, **k: ok_result()), 2)
        self.assertEqual(self.run_eval([os.path.join(self.d, "missing")], lambda *a, **k: ok_result()), 2)

    def test_report_never_contains_title_or_article_text(self):
        p = self.img_dir(1)
        m = os.path.join(self.d, "m.json")
        with open(m, "w", encoding="utf-8") as f:
            json.dump([{"path": os.path.join(p, "img00.png"), "article_id": "1", "seq": 1, "title": TITLE,
                        "body": "內文內文"}], f, ensure_ascii=False)
        self.run_eval([m], lambda path, mode, **kw: ok_result())
        text = self.report()
        self.assertNotIn(TITLE, text)
        self.assertNotIn("內文內文", text)

    def test_low_confidence_listing_only_with_flag(self):
        p = self.img_dir(1)
        low = [{"row": 3, "col": 2, "guess": "1,0O0", "score": 0.42}]
        self.run_eval([p], lambda path, mode, **kw: ok_result(low=low))
        text = self.report()
        self.assertIn("低信心格（[?]）：1 格", text)
        self.assertNotIn("1,0O0", text)
        for n in os.listdir(self.out):
            os.unlink(os.path.join(self.out, n))
        self.run_eval([p, "--show-low-conf"], lambda path, mode, **kw: ok_result(low=low))
        self.assertIn("引擎猜測「1,0O0」", self.report())

    def test_default_transcribe_passes_options(self):
        p = self.img_dir(1)
        with mock.patch.object(ap, "transcribe_image_paddle", return_value=ok_result()) as m:
            pe.run([p, "--out", self.out, "--variant", "mobile", "--min-score", "0.9", "--model-dir", "/m",
                    "--det-max-side", "960"], now=self.now, say=self.msgs.append, guard=False)
        kw = m.call_args[1]
        self.assertEqual((kw["variant"], kw["min_score"], kw["model_dir"], kw["det_max_side"], kw["allow_download"]),
                         ("mobile", 0.9, "/m", 960, False))


class NetworkGuardTest(Base):
    def setUp(self):
        Base.setUp(self)
        self._c, self._g = socket.socket.connect, socket.getaddrinfo
        self.addCleanup(self._restore)

    def _restore(self):
        socket.socket.connect, socket.getaddrinfo = self._c, self._g

    def test_guard_blocks_external_and_dns(self):
        restore = pe.install_network_guard()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            with self.assertRaises(OSError) as cm:
                s.connect(("93.184.216.34", 443))
            self.assertIn("離線模式", str(cm.exception))
            s.close()
            with self.assertRaises(OSError):
                socket.getaddrinfo("huggingface.co", 443)
            with self.assertRaises(OSError):
                socket.create_connection(("paddle-model-ecology.bj.bcebos.com", 443), timeout=1)
        finally:
            restore()
        self.assertIs(socket.socket.connect, self._c)

    def test_guard_allows_loopback(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        restore = pe.install_network_guard()
        try:
            c = socket.create_connection(("127.0.0.1", srv.getsockname()[1]), timeout=2)
            c.close()
        finally:
            restore()
            srv.close()

    def test_run_installs_guard_unless_allow_download(self):
        p = self.img_dir(1)
        os.environ.pop("HF_HUB_OFFLINE", None)
        with mock.patch.object(pe, "install_network_guard") as g:
            pe.run([p, "--out", self.out], transcribe=lambda *a, **k: ok_result(), now=self.now, say=self.msgs.append)
        g.assert_called_once()
        self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        os.environ.pop("HF_HUB_OFFLINE", None)
        with mock.patch.object(pe, "install_network_guard") as g:
            pe.run([p, "--out", self.out + "2", "--allow-download"], transcribe=lambda *a, **k: ok_result(),
                   now=self.now, say=self.msgs.append)
        g.assert_not_called()
        self.assertNotIn("HF_HUB_OFFLINE", os.environ)


if __name__ == "__main__":
    unittest.main()
