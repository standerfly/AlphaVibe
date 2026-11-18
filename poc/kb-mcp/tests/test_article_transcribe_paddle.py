"""article_transcribe_paddle 測試（010 方案 C）：全程使用假的 paddleocr 模組與假的影像層，
**不依賴真實 paddle／numpy／PIL 安裝**（只有標 skipUnless 的 PilImage 測試需要 PIL＋numpy）；
不連網（socket 一律失敗仍須可運作）、不讀鑰匙圈、不碰真實資料目錄。"""
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
KBMCP = os.path.join(HERE, "..")
sys.path.insert(0, KBMCP)
import article_transcribe_paddle as ap  # noqa: E402
import article_image_tiles as tiles_mod  # noqa: E402
import investanchors_redact  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"          # 只要 sniff 得出是 PNG；影像解碼由假 opener 接手
HDR = ["項目", "2024", "2025E", "2026E", "年增率"]
COL_X = [20, 400, 650, 900, 1150]               # 每欄起點（框寬 150）


# ── 假影像層 ────────────────────────────────────────────────────────────────────────
class FakeImage(object):
    def __init__(self, width=1200, height=800, bands=None):
        self.width, self.height = width, height
        self._bands = bands if bands is not None else []
        self.resized_to = None

    def resize_width(self, new_w):
        self.resized_to = new_w
        self.height = int(self.height * new_w / self.width + 0.5)
        self.width = new_w

    def blank_bands(self):
        return self._bands

    def crop_bgr(self, top, bottom):
        return ("crop", top, bottom)


def opener_for(img):
    return lambda data: img


def box(x0, y0, x1, y1, text, score=0.99):
    return ap.Box(x0, y0, x1, y1, text, score)


def row_boxes(y, cells, score=0.99, h=40):
    return [box(COL_X[i], y, COL_X[i] + 150, y + h, c, score) for i, c in enumerate(cells)]


def to_res(boxes):
    """Box 清單 → PaddleOCR 結果 dict（rec_texts／rec_scores／rec_boxes）。"""
    return {"rec_texts": [b.text for b in boxes], "rec_scores": [b.score for b in boxes],
            "rec_boxes": [[b.x0, b.y0, b.x1, b.y1] for b in boxes]}


class FakeEngine(object):
    """analyze(crop_token) → {"boxes", "tables"}；behavior(top, bottom, call_index) 決定每片回傳。"""
    mode = ap.MODE_GRID
    label = "fake-engine"

    def __init__(self, behavior, mode=ap.MODE_GRID):
        self.behavior = behavior
        self.mode = mode
        self.calls = []

    def analyze(self, token):
        _tag, top, bottom = token
        self.calls.append((top, bottom))
        return self.behavior(top, bottom, len(self.calls) - 1)


def table_rows(n):
    rows = [HDR]
    for i in range(n):
        rows.append(["項目%02d" % i, "%d,%03d.5" % (i, 100 + i), "%d.%d" % (i, i), "%d,%d00" % (i + 1, i), "%d.2%%" % i])
    return rows


ROW_H, ROW_PITCH, TOP0 = 40, 80, 60


def tile_behavior(rows):
    """模擬長圖上的表格：第 i 列在全圖 y = TOP0 + i*ROW_PITCH。片內回傳完整框；
    被切線切到的列回傳被截斷的框（文字截一半、貼著片邊緣）。"""
    def beh(top, bottom, _idx):
        out = []
        for i, cells in enumerate(rows):
            y0 = TOP0 + i * ROW_PITCH
            y1 = y0 + ROW_H
            if y1 <= top or y0 >= bottom:
                continue
            cy0, cy1 = max(y0, top), min(y1, bottom)
            partial = (cy0 != y0) or (cy1 != y1)
            for ci, c in enumerate(cells):
                text = c[:max(1, len(c) // 2)] if partial else c
                out.append(box(COL_X[ci], cy0 - top, COL_X[ci] + 150, cy1 - top, text))
        return {"boxes": out, "tables": []}
    return beh


# ── 假 paddleocr 模組 ───────────────────────────────────────────────────────────────
def make_fake_paddleocr(ocr_boxes=None, tables=None, init_error=None, predict_error=None, version="9.9.9"):
    mod = types.ModuleType("paddleocr")
    mod.__version__ = version
    mod.init_calls = []
    mod.predict_calls = []

    class PaddleOCR(object):
        def __init__(self, **kw):
            if init_error:
                raise init_error
            mod.init_calls.append(("PaddleOCR", kw))

        def predict(self, img, **kw):
            mod.predict_calls.append(kw)
            if predict_error:
                raise predict_error
            return [to_res(ocr_boxes or [])]

    class TableRecognitionPipelineV2(object):
        def __init__(self, **kw):
            if init_error:
                raise init_error
            mod.init_calls.append(("Pipeline", kw))

        def predict(self, img, **kw):
            mod.predict_calls.append(kw)
            if predict_error:
                raise predict_error
            return [{"overall_ocr_res": to_res(ocr_boxes or []),
                     "table_res_list": [{"pred_html": t["html"], "cell_box_list": t.get("cell_boxes", []),
                                         "table_ocr_pred": to_res(t.get("ocr", []))} for t in (tables or [])]}]

    mod.PaddleOCR = PaddleOCR
    mod.TableRecognitionPipelineV2 = TableRecognitionPipelineV2
    return mod


@contextlib.contextmanager
def fake_models(*names):
    """建立含假模型資料夾的暫存根目錄（有 inference.yml 即視為存在）。"""
    with tempfile.TemporaryDirectory() as d:
        for n in names or ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"):
            os.makedirs(os.path.join(d, n))
            with open(os.path.join(d, n, "inference.yml"), "w") as f:
                f.write("x")
        yield d


@contextlib.contextmanager
def no_network():
    def blocked(*a, **k):
        raise OSError("network blocked by test")
    with mock.patch.object(socket.socket, "connect", blocked), \
            mock.patch.object(socket, "getaddrinfo", blocked), \
            mock.patch.object(socket, "create_connection", blocked):
        yield


class Base(unittest.TestCase):
    def setUp(self):
        ap.clear_engine_cache()
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ap.clear_engine_cache)


# ── 1. lazy import／未安裝 ───────────────────────────────────────────────────────────
class NotInstalledTest(Base):
    def test_module_imports_without_paddle(self):
        code = ("import sys; sys.modules['paddleocr']=None; sys.modules['paddle']=None;"
                "sys.path.insert(0, %r); import article_transcribe_paddle as m; print('ok', m.ENGINE_NAME)" % KBMCP)
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ok paddleocr", out.stdout)

    def test_no_top_level_paddle_import(self):
        with open(os.path.join(KBMCP, "article_transcribe_paddle.py"), encoding="utf-8") as f:
            src = f.read()
        for ln in src.splitlines():
            self.assertFalse(ln.startswith("import paddle") or ln.startswith("from paddle"), ln)
            self.assertFalse(ln.startswith("import numpy") or ln.startswith("from PIL"), ln)

    def test_not_installed_result(self):
        with mock.patch.dict(sys.modules, {"paddleocr": None}):
            r = ap.transcribe_image_paddle(PNG, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "paddle_not_installed")
        self.assertTrue(r["abort"])            # 對每張圖都一樣 → 呼叫端應中止
        self.assertFalse(r["retryable"])
        self.assertIn("pip install", r["detail"])
        self.assertIn("paddle-setup.md", r["detail"])

    def test_missing_image_lib_is_unavailable(self):
        def boom(data):
            raise ap.PaddleUnavailable("image_lib_missing", "缺少 numpy／Pillow")
        eng = FakeEngine(lambda t, b, i: {"boxes": [], "tables": []})
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=boom)
        self.assertEqual(r["reason"], "image_lib_missing")
        self.assertTrue(r["abort"])


# ── 2. 模型與離線 ───────────────────────────────────────────────────────────────────
class OfflineTest(Base):
    def test_missing_models_is_abort_and_no_download(self):
        fake = make_fake_paddleocr()
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            r = ap.transcribe_image_paddle(PNG, model_dir=empty, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["reason"], "model_not_available")
        self.assertTrue(r["abort"])
        self.assertIn("--allow-download", r["detail"])
        self.assertEqual(fake.init_calls, [])      # 連模型都沒開始載入，更不會下載

    def test_allow_download_passes_name_only_for_missing_model(self):
        fake = make_fake_paddleocr()
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            ap.get_engine(model_dir=empty, allow_download=True)
        kw = fake.init_calls[0][1]
        self.assertEqual(kw["text_detection_model_name"], "PP-OCRv5_server_det")
        self.assertNotIn("text_detection_model_dir", kw)

    def test_local_models_use_model_dir_kwargs(self):
        fake = make_fake_paddleocr()
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            ap.get_engine(model_dir=d)
        kw = fake.init_calls[0][1]
        self.assertEqual(kw["text_detection_model_dir"], os.path.join(d, "PP-OCRv5_server_det"))
        self.assertEqual(kw["text_recognition_model_dir"], os.path.join(d, "PP-OCRv5_server_rec"))
        self.assertIs(kw["enable_mkldnn"], False)
        self.assertIs(kw["use_doc_orientation_classify"], False)

    def test_model_dir_from_env(self):
        fake = make_fake_paddleocr()
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            os.environ[ap.MODEL_DIR_ENV] = d
            ap.get_engine()
        self.assertEqual(fake.init_calls[0][1]["text_detection_model_dir"], os.path.join(d, "PP-OCRv5_server_det"))

    def test_mobile_variant_names(self):
        fake = make_fake_paddleocr()
        with fake_models("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec") as d, \
                mock.patch.dict(sys.modules, {"paddleocr": fake}):
            eng = ap.get_engine(variant="mobile", model_dir=d)
        self.assertIn("mobile", eng.label)

    def test_works_with_network_completely_blocked(self):
        fake = make_fake_paddleocr(ocr_boxes=row_boxes(10, HDR) + row_boxes(80, ["A", "1", "2", "3", "4"]))
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}), no_network():
            r = ap.transcribe_image_paddle(PNG, model_dir=d, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["status"], "transcribed", r)
        self.assertTrue(r["is_table"])
        self.assertIn("| 項目 | 2024 | 2025E | 2026E | 年增率 |", r["text"])

    def test_offline_env_set_before_import(self):
        fake = make_fake_paddleocr()
        for k in ("HF_HUB_OFFLINE", "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"):
            os.environ.pop(k, None)
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            ap.get_engine(model_dir=d)
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
        self.assertEqual(os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"], "True")

    def test_allow_download_does_not_force_hf_offline(self):
        fake = make_fake_paddleocr()
        os.environ.pop("HF_HUB_OFFLINE", None)
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            ap.get_engine(model_dir=d, allow_download=True)
        self.assertNotIn("HF_HUB_OFFLINE", os.environ)

    def test_engine_cache_reuses_instance(self):
        fake = make_fake_paddleocr()
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            a, b = ap.get_engine(model_dir=d), ap.get_engine(model_dir=d)
            c = ap.get_engine(mode=ap.MODE_PIPELINE, model_dir=d)
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertEqual(len(fake.init_calls), 2)

    def test_det_limit_passed_to_predict(self):
        fake = make_fake_paddleocr(ocr_boxes=row_boxes(10, HDR))
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            ap.transcribe_image_paddle(PNG, model_dir=d, image_opener=opener_for(FakeImage()), det_max_side=999)
        self.assertEqual(fake.predict_calls[0], {"text_det_limit_type": "max", "text_det_limit_side_len": 999})

    def test_dependency_error_is_abort(self):
        fake = make_fake_paddleocr(init_error=RuntimeError("A dependency error occurred during pipeline creation"))
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            r = ap.transcribe_image_paddle(PNG, model_dir=d, mode=ap.MODE_PIPELINE, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["reason"], "paddle_dependency_missing")
        self.assertTrue(r["abort"])

    def test_init_failure_is_abort_and_redacted(self):
        fake = make_fake_paddleocr(init_error=RuntimeError("boom password=hunter2 cookie: sid=abc"))
        with fake_models() as d, mock.patch.dict(sys.modules, {"paddleocr": fake}):
            r = ap.transcribe_image_paddle(PNG, model_dir=d, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["reason"], "engine_init_failed")
        self.assertTrue(r["abort"])
        self.assertNotIn("hunter2", json.dumps(r, ensure_ascii=False))
        self.assertNotIn("abc", r["detail"])


# ── 3. HTML → Markdown ─────────────────────────────────────────────────────────────
class HtmlToMarkdownTest(unittest.TestCase):
    def test_basic_table(self):
        h = "<html><body><table><tbody><tr><td>項目</td><td>2024</td></tr><tr><td>營收</td><td>1,234.5</td></tr></tbody></table></body></html>"
        self.assertEqual(ap.html_to_markdown(h), "| 項目 | 2024 |\n| --- | --- |\n| 營收 | 1,234.5 |")

    def test_colspan_leaves_covered_cells_empty(self):
        h = "<table><tr><td colspan=2>標題</td><td>C</td></tr><tr><td>a</td><td>b</td><td>c</td></tr></table>"
        self.assertEqual(ap.html_to_markdown(h), "| 標題 |  | C |\n| --- | --- | --- |\n| a | b | c |")

    def test_rowspan_does_not_copy_text_down(self):
        h = "<table><tr><td rowspan=2>合計</td><td>x</td></tr><tr><td>y</td></tr></table>"
        t = ap.parse_html_tables(h)[0]
        self.assertEqual(t["grid"], [["合計", "x"], ["", "y"]])
        self.assertEqual(t["anchors"], [(0, 0), (0, 1), (1, 1)])

    def test_empty_cells_stay_empty(self):
        h = "<table><tr><td>a</td><td></td><td>c</td></tr></table>"
        self.assertEqual(ap.parse_html_tables(h)[0]["grid"], [["a", "", "c"]])

    def test_question_mark_cells_preserved(self):
        h = "<table><tr><td>a</td><td>[?]</td></tr></table>"
        self.assertIn("[?]", ap.html_to_markdown(h))

    def test_pipe_and_whitespace_escaped(self):
        h = "<table><tr><td>a|b</td><td> x <br> y </td></tr></table>"
        self.assertEqual(ap.html_to_markdown(h), "| a\\|b | x y |\n| --- | --- |")

    def test_entities_and_th(self):
        h = "<table><tr><th>A&amp;B</th><th>&lt;1&gt;</th></tr></table>"
        self.assertEqual(ap.parse_html_tables(h)[0]["grid"], [["A&B", "<1>"]])

    def test_two_tables_and_no_table(self):
        h = "<table><tr><td>1</td></tr></table><p>x</p><table><tr><td>2</td></tr></table>"
        self.assertEqual(len(ap.parse_html_tables(h)), 2)
        self.assertEqual(ap.html_to_markdown("<p>沒有表格</p>"), "")
        self.assertEqual(ap.html_to_markdown(""), "")
        self.assertEqual(ap.html_to_markdown(None), "")

    def test_nested_table_ignored_malformed_ok(self):
        h = "<table><tr><td>外<table><tr><td>內</td></tr></table></td></tr></table>"
        self.assertEqual(len(ap.parse_html_tables(h)), 1)
        ap.parse_html_tables("<table><tr><td>未關閉")            # 不得丟例外
        ap.parse_html_tables("<td>沒有 table</td>")

    def test_span_bounds(self):
        h = "<table><tr><td colspan='abc'>a</td><td colspan='999999'>b</td></tr></table>"
        g = ap.parse_html_tables(h)[0]["grid"]
        self.assertLessEqual(len(g[0]), 60)

    def test_grid_to_markdown_ragged_and_empty(self):
        self.assertEqual(ap.grid_to_markdown([["a", "b"], ["c"]]), "| a | b |\n| --- | --- |\n| c |  |")
        self.assertEqual(ap.grid_to_markdown([]), "")
        self.assertEqual(ap.grid_to_markdown([[]]), "")


# ── 4. 文字框 → grid ───────────────────────────────────────────────────────────────
class BoxesToGridTest(unittest.TestCase):
    def test_rows_and_columns(self):
        boxes = row_boxes(10, HDR) + row_boxes(80, ["營收", "1,000", "2,000", "3,000", "5.0%"])
        grid, low = ap.boxes_to_grid(boxes)
        self.assertEqual(grid[1], ["營收", "1,000", "2,000", "3,000", "5.0%"])
        self.assertEqual(low, [])

    def test_low_confidence_cell_is_question_mark_not_guess(self):
        boxes = row_boxes(10, HDR) + row_boxes(80, ["營收", "1,0O0", "2,000", "3,000", "5.0%"])
        boxes[6].score = 0.42                     # "1,0O0"
        grid, low = ap.boxes_to_grid(boxes, min_score=0.8)
        self.assertEqual(grid[1][1], "[?]")
        self.assertNotIn("1,0O0", ap.grid_to_markdown(grid))      # 猜測值不進轉寫文字
        self.assertEqual(low[0]["guess"], "1,0O0")
        self.assertEqual((low[0]["row"], low[0]["col"]), (1, 1))

    def test_empty_cell_not_filled(self):
        boxes = row_boxes(10, HDR) + row_boxes(80, ["營收", "1,000", "", "3,000", "5.0%"])
        grid, _ = ap.boxes_to_grid(boxes)
        self.assertEqual(grid[1][2], "")

    def test_wide_title_box_does_not_glue_columns(self):
        title = box(20, 0, 1300, 40, "某公司財務預測表（單位：百萬元）")
        boxes = [title] + row_boxes(60, HDR) + row_boxes(120, ["營收", "1", "2", "3", "4"])
        grid, _ = ap.boxes_to_grid(boxes)
        self.assertEqual(len(grid[1]), 5)
        self.assertEqual(grid[2][4], "4")

    def test_two_boxes_in_one_cell_joined(self):
        boxes = row_boxes(10, HDR) + row_boxes(80, ["營收", "1,000", "2,000", "3,000", "5.0%"])
        boxes.append(box(COL_X[1], 80, COL_X[1] + 150, 120, "(E)"))     # 與 "1,000" 同格同列
        grid, _ = ap.boxes_to_grid(boxes)
        self.assertEqual(grid[1][1], "1,000 (E)")

    def test_blank_text_boxes_dropped(self):
        grid, _ = ap.boxes_to_grid([box(0, 0, 10, 10, "  "), box(0, 0, 10, 10, None)])
        self.assertEqual(grid, [])

    def test_is_table_and_plain_text(self):
        self.assertFalse(ap.is_table_grid([["只有一列", "x"]]))
        self.assertFalse(ap.is_table_grid([["a"], ["b"]]))
        self.assertTrue(ap.is_table_grid([["a", "b"], ["c", "d"]]))
        boxes = [box(0, 0, 400, 30, "第一行文字"), box(0, 50, 400, 80, "第二行文字")]
        self.assertEqual(ap.plain_text(boxes), "第一行文字\n第二行文字")

    def test_to_box_list_from_polys_when_no_rec_boxes(self):
        res = {"rec_texts": ["a"], "rec_scores": [0.9], "rec_polys": [[[1, 2], [9, 2], [9, 8], [1, 8]]]}
        b = ap._to_box_list(res)[0]
        self.assertEqual((b.x0, b.y0, b.x1, b.y1), (1, 2, 9, 8))


# ── 5. 轉寫主流程與錯誤分類 ──────────────────────────────────────────────────────────
class TranscribeTest(Base):
    def run_one(self, behavior=None, img=None, **kw):
        eng = FakeEngine(behavior or (lambda t, b, i: {"boxes": row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"]),
                                                       "tables": []}))
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img or FakeImage()), **kw)
        return r, eng

    def test_success_shape_matches_api_engine(self):
        r, _ = self.run_one()
        for k in ("status", "is_table", "text", "model", "reason", "abort"):      # article_transcribe 的欄位
            self.assertIn(k, r)
        self.assertEqual(r["status"], "transcribed")
        self.assertIsNone(r["reason"])
        self.assertFalse(r["abort"])
        self.assertEqual(r["model"], "fake-engine")
        self.assertEqual(r["meta"]["tiles"], 1)
        self.assertEqual(r["meta"]["size"], [1200, 800])

    def test_low_confidence_in_result(self):
        def beh(t, b, i):
            bs = row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"])
            bs[7].score = 0.3
            return {"boxes": bs, "tables": []}
        r, _ = self.run_one(beh)
        self.assertIn("[?]", r["text"])
        self.assertEqual(len(r["meta"]["low_confidence"]), 1)

    def test_no_text_detected_is_deterministic_failure(self):
        r, _ = self.run_one(lambda t, b, i: {"boxes": [], "tables": []})
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "no_text_detected")
        self.assertFalse(r["abort"])
        self.assertFalse(r["retryable"])
        self.assertIsNone(r["text"])               # 不以空白充數

    def test_non_table_image(self):
        r, _ = self.run_one(lambda t, b, i: {"boxes": [box(0, 0, 400, 30, "一段說明文字")], "tables": []})
        self.assertEqual(r["status"], "transcribed")
        self.assertFalse(r["is_table"])
        self.assertEqual(r["text"], "一段說明文字")

    def test_engine_exception_is_retryable_and_reason_has_no_message(self):
        def beh(t, b, i):
            raise RuntimeError("secret cookie: sid=abcd1234 password=hunter2")
        r, _ = self.run_one(beh)
        self.assertEqual(r["reason"], "engine_error:RuntimeError")
        self.assertTrue(r["retryable"])
        self.assertFalse(r["abort"])
        self.assertNotIn("hunter2", json.dumps(r, ensure_ascii=False))

    def test_memory_error_retryable(self):
        def beh(t, b, i):
            raise MemoryError("alloc")
        r, _ = self.run_one(beh)
        self.assertEqual(r["reason"], "out_of_memory")
        self.assertTrue(r["retryable"])

    def test_unsupported_format_and_unreadable_path(self):
        eng = FakeEngine(lambda t, b, i: {"boxes": [], "tables": []})
        r = ap.transcribe_image_paddle(b"not an image", engine=eng, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["reason"], "unsupported_image_format")
        self.assertFalse(r["retryable"])
        r = ap.transcribe_image_paddle("/nonexistent/x.png", engine=eng)
        self.assertEqual(r["reason"], "image_read_error")
        self.assertFalse(r["abort"])

    def test_corrupt_image_decode_error(self):
        def bad(data):
            raise ValueError("image_decode_error")
        eng = FakeEngine(lambda t, b, i: {"boxes": [], "tables": []})
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=bad)
        self.assertEqual(r["reason"], "image_decode_error")
        self.assertFalse(r["abort"])

    def test_path_input(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(PNG)
        self.addCleanup(os.unlink, f.name)
        eng = FakeEngine(lambda t, b, i: {"boxes": row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"]), "tables": []})
        r = ap.transcribe_image_paddle(f.name, engine=eng, image_opener=opener_for(FakeImage()))
        self.assertEqual(r["status"], "transcribed")

    def test_timeout_between_tiles(self):
        ticks = iter([0, 0, 5, 10, 15, 20, 25, 30])
        img = FakeImage(2190, 5327)
        eng = FakeEngine(tile_behavior(table_rows(60)))
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img), timeout=3,
                                       clock=lambda: next(ticks))
        self.assertEqual(r["reason"], "timeout")
        self.assertTrue(r["retryable"])

    def test_output_has_no_sensitive_text(self):
        r, _ = self.run_one()
        blob = json.dumps(r, ensure_ascii=False)
        self.assertEqual(investanchors_redact.find_leaks(blob, secrets=["sk-ant-FAKE"]), [])
        self.assertNotIn("api", r["model"].lower())

    def test_wide_image_is_resized_before_tiling(self):
        img = FakeImage(4000, 1000)
        eng = FakeEngine(lambda t, b, i: {"boxes": row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"]), "tables": []})
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img))
        self.assertEqual(img.resized_to, 2576)
        self.assertEqual(r["status"], "transcribed")


# ── 6. 長圖切片與合併 ───────────────────────────────────────────────────────────────
class LongImageTest(Base):
    def run_long(self, n_rows=60, bands=None, w=2190, h=5327):
        rows = table_rows(n_rows)
        img = FakeImage(w, h, bands)
        eng = FakeEngine(tile_behavior(rows))
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img))
        return rows, r, eng

    def md_rows(self, text):
        return [[c.strip() for c in ln.strip("|").split(" | ")] for ln in text.splitlines()
                if ln.startswith("|") and not ln.startswith("| ---")]

    def test_long_image_is_tiled_and_each_row_once(self):
        rows, r, eng = self.run_long()
        self.assertEqual(r["status"], "transcribed", r)
        self.assertGreaterEqual(len(eng.calls), 3)
        self.assertEqual(r["meta"]["tiles"], len(eng.calls))
        got = self.md_rows(r["text"])
        self.assertEqual(got, [[c for c in row] for row in rows])      # 無遺漏、無重複、順序正確、表頭只有一次

    def test_tiles_overlap_at_least_planned_minimum(self):
        _rows, _r, eng = self.run_long()
        for (a_top, a_bot), (b_top, b_bot) in zip(eng.calls, eng.calls[1:]):
            self.assertGreaterEqual(a_bot - b_top, tiles_mod.OVERLAP_MIN_PX)

    def test_cut_through_row_does_not_leave_fragments(self):
        # 無空白帶 → 切點落在上限，必然切到某些列；被切斷的框要被丟棄，由重疊的另一片提供完整列
        rows, r, _eng = self.run_long(bands=[])
        got = self.md_rows(r["text"])
        self.assertEqual(got, [[c for c in row] for row in rows])

    def test_blank_bands_are_used_as_cut_points(self):
        bands = [[y, y + 20] for y in range(100 + 40, 5300, 80)]       # 每列之間都有空白帶
        rows, r, eng = self.run_long(bands=bands)
        self.assertEqual(self.md_rows(r["text"]), [[c for c in row] for row in rows])

    def test_dedupe_keeps_higher_confidence_text(self):
        # 同一列在兩片中都完整出現但其中一片信心低 → 取高者，不產生 [?]
        rows = table_rows(60)
        base = tile_behavior(rows)

        def beh(top, bottom, idx):
            res = base(top, bottom, idx)
            if idx == 0:
                for b in res["boxes"]:
                    b.score = 0.5            # 第一片全部低信心
            return res
        img = FakeImage(2190, 5327)
        eng = FakeEngine(beh)
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img))
        # 第一片獨有的列（不在重疊區）仍會是 [?]，但重疊區內的列取第二片的高信心值
        first_bottom = eng.calls[0][1]
        overlap_start = eng.calls[1][0]
        in_overlap = [i for i in range(len(rows)) if TOP0 + i * ROW_PITCH >= overlap_start + 4
                      and TOP0 + i * ROW_PITCH + ROW_H <= first_bottom - 4]
        got = self.md_rows(r["text"])
        self.assertTrue(in_overlap)
        for i in in_overlap:
            self.assertNotIn("[?]", got[i], i)

    def test_too_many_tiles_is_untranscribed(self):
        img = FakeImage(2190, 60000)
        eng = FakeEngine(tile_behavior(table_rows(5)))
        r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(img))
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "too_many_tiles")
        self.assertFalse(r["retryable"])
        self.assertEqual(eng.calls, [])            # 沒浪費推論

    def test_merge_tile_boxes_single_tile_keeps_edge_boxes(self):
        b = [box(0, 0, 100, 30, "貼邊"), box(0, 770, 100, 800, "貼底")]
        out = ap.merge_tile_boxes([b], [(0, 800)])
        self.assertEqual(len(out), 2)

    def test_merge_grids_dedupes_overlap_rows(self):
        g1 = [["h1", "h2"], ["r1x", "1111111"], ["r2x", "2222222"]]
        g2 = [["r1x", "1111111"], ["r2x", "2222222"], ["r3x", "3333333"]]
        merged, warns = ap.merge_grids([g1, g2])
        self.assertEqual([r[0] for r in merged], ["h1", "r1x", "r2x", "r3x"])
        self.assertEqual(warns, [])

    def test_merge_grids_truncated_edge_rows_dropped(self):
        # 下一片開頭是被切斷的殘缺列、前文最後一列也是殘缺列：兩者都應丟掉，只留完整版本
        g1 = [["h1", "h2"], ["r1xxxx", "1111111"], ["r2xxxx", "2222222"], ["r3x", "33"]]            # 末列殘缺
        g2 = [["", ""], ["r2x", "22"], ["r2xxxx", "2222222"], ["r3xxxx", "3333333"], ["r4xxxx", "4444444"]]
        merged, _ = ap.merge_grids([g1, g2])
        self.assertEqual([r[0] for r in merged], ["h1", "r1xxxx", "r2xxxx", "r3xxxx", "r4xxxx"])

    def test_merge_grids_drops_empty_rows(self):
        merged, _ = ap.merge_grids([[["a", "b"], ["", ""], ["c", "d"]]])
        self.assertEqual(merged, [["a", "b"], ["c", "d"]])

    def test_merge_grids_short_single_row_coincidence_kept(self):
        g1 = [["h", "h"], ["a", "1"]]
        g2 = [["a", "1"], ["b", "2"]]                   # 只重疊 1 列且過短 → 不當重複
        merged, _ = ap.merge_grids([g1, g2])
        self.assertEqual(len(merged), 4)

    def test_merge_grids_column_mismatch_warns_and_pads(self):
        merged, warns = ap.merge_grids([[["a", "b"]], [["c", "d", "e"]]])
        self.assertIn("columns_mismatch_between_tiles", warns)
        self.assertTrue(all(len(r) == 3 for r in merged))


# ── 7. table_pipeline 模式 ─────────────────────────────────────────────────────────
class PipelineModeTest(Base):
    HTML = ("<html><body><table><tr><td>項目</td><td>2024</td></tr>"
            "<tr><td>營收</td><td>1,000</td></tr></table></body></html>")
    CELLS = [[0, 0, 100, 50], [100, 0, 200, 50], [0, 50, 100, 100], [100, 50, 200, 100]]

    def ocr(self, scores=(0.99, 0.99, 0.99, 0.99)):
        pos = [(10, 10, 90, 40, "項目"), (110, 10, 190, 40, "2024"), (10, 60, 90, 90, "營收"), (110, 60, 190, 90, "1,000")]
        return [box(x0, y0, x1, y1, t, scores[i]) for i, (x0, y0, x1, y1, t) in enumerate(pos)]

    def run_pipe(self, tables, boxes=None):
        eng = FakeEngine(lambda t, b, i: {"boxes": boxes or [], "tables": tables}, mode=ap.MODE_PIPELINE)
        return ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(FakeImage()))

    def test_html_converted(self):
        r = self.run_pipe([{"html": self.HTML, "cell_boxes": self.CELLS, "ocr": self.ocr()}])
        self.assertEqual(r["text"], "| 項目 | 2024 |\n| --- | --- |\n| 營收 | 1,000 |")
        self.assertTrue(r["is_table"])
        self.assertEqual(r["meta"]["mode"], ap.MODE_PIPELINE)

    def test_low_confidence_cell_marked(self):
        r = self.run_pipe([{"html": self.HTML, "cell_boxes": self.CELLS, "ocr": self.ocr((0.99, 0.99, 0.99, 0.31))}])
        self.assertIn("| 營收 | [?] |", r["text"])
        self.assertNotIn("1,000", r["text"])
        self.assertEqual(r["meta"]["low_confidence"][0]["guess"], "1,000")

    def test_misaligned_cell_boxes_warn_not_crash(self):
        r = self.run_pipe([{"html": self.HTML, "cell_boxes": self.CELLS[:3], "ocr": self.ocr((0.1, 0.1, 0.1, 0.1))}])
        self.assertEqual(r["status"], "transcribed")
        self.assertIn("cell_boxes_misaligned", r["meta"]["warnings"])
        self.assertNotIn("[?]", r["text"])           # 對位不可靠 → 不亂標

    def test_tile_without_table_falls_back_to_ocr_grid(self):
        boxes = row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"])
        r = self.run_pipe([], boxes=boxes)
        self.assertEqual(r["status"], "transcribed")
        self.assertTrue(any("no_table_fallback" in w for w in r["meta"]["warnings"]))
        self.assertIn("| a | 1 | 2 | 3 | 4 |", r["text"])

    def test_no_text_anywhere_is_untranscribed(self):
        r = self.run_pipe([], boxes=[])
        self.assertEqual(r["reason"], "no_text_detected")

    def test_multi_tile_rows_deduped(self):
        def html_rows(idx_from, idx_to):
            rows = table_rows(40)
            body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in rows[i]) for i in range(idx_from, idx_to))
            return "<table>%s</table>" % body
        parts = {0: (0, 15), 1: (12, 28), 2: (25, 41)}               # 相鄰片重疊 3 列

        def beh(top, bottom, idx):
            a, b = parts[idx]
            return {"boxes": [], "tables": [{"html": html_rows(a, b), "cell_boxes": [], "ocr": []}]}
        eng = FakeEngine(beh, mode=ap.MODE_PIPELINE)
        with mock.patch.object(tiles_mod, "plan_tiles", return_value=tiles_mod.TilePlan(
                tiles_mod.STATUS_OK, "", 2190, 5327, 2190, 5327, False, [(0, 1700), (1450, 3100), (2850, 5327)])):
            r = ap.transcribe_image_paddle(PNG, engine=eng, image_opener=opener_for(FakeImage(2190, 5327)))
        lines = [ln for ln in r["text"].splitlines() if ln.startswith("|") and not ln.startswith("| ---")]
        self.assertEqual(len(lines), 41)             # 表頭 + 40 列，無重複
        self.assertEqual(lines[0], "| 項目 | 2024 | 2025E | 2026E | 年增率 |")


# ── 8. 相容入口 ─────────────────────────────────────────────────────────────────────
class TilesCompatTest(Base):
    def test_empty_tiles(self):
        r = ap.transcribe_tiles_paddle([])
        self.assertEqual(r["reason"], "no_tiles")

    def test_ignores_api_style_kwargs_and_never_reads_secret(self):
        def get_secret(*a, **k):
            raise AssertionError("本機引擎不得讀金鑰")
        eng = FakeEngine(lambda t, b, i: {"boxes": row_boxes(10, HDR) + row_boxes(80, ["a", "1", "2", "3", "4"]), "tables": []})
        with mock.patch.object(ap, "_open_image", opener_for(FakeImage())):
            r = ap.transcribe_tiles_paddle([PNG], get_secret=get_secret, api_url="http://x", model="m",
                                           sleeper=lambda s: None, merge=None, engine=eng)
        self.assertEqual(r["status"], "transcribed")

    def test_multi_tile_merges_overlap_lines(self):
        outs = iter([["| h | h |", "| --- | --- |", "| 營業收入 | 1,234,567 |", "| 營業毛利 | 2,345,678 |"],
                     ["| 營業收入 | 1,234,567 |", "| 營業毛利 | 2,345,678 |", "| 稅後淨利 | 3,456,789 |"]])

        def fake_one(tile, **kw):
            return {"status": "transcribed", "is_table": True, "text": "\n".join(next(outs)), "model": "m", "meta": {"mode": "ocr_grid"}}
        with mock.patch.object(ap, "transcribe_image_paddle", fake_one):
            r = ap.transcribe_tiles_paddle([PNG, PNG])
        self.assertEqual(r["text"].count("營業收入"), 1)
        self.assertIn("稅後淨利", r["text"])

    def test_multi_tile_failure_propagates(self):
        fail = {"status": "untranscribed", "reason": "engine_error:X", "abort": False, "meta": {}}
        with mock.patch.object(ap, "transcribe_image_paddle", lambda t, **kw: fail):
            r = ap.transcribe_tiles_paddle([PNG, PNG])
        self.assertEqual(r["reason"], "engine_error:X")


# ── 9. 真實 PIL／numpy 影像層（有裝才跑）──────────────────────────────────────────────
try:
    import numpy  # noqa: F401
    from PIL import Image
    HAVE_IMG = True
except ImportError:
    HAVE_IMG = False


@unittest.skipUnless(HAVE_IMG, "需要 numpy 與 Pillow")
class PilImageTest(unittest.TestCase):
    def png(self, im):
        import io
        b = io.BytesIO()
        im.save(b, format="PNG")
        return b.getvalue()

    def test_crop_is_bgr_and_sized(self):
        im = Image.new("RGB", (30, 40), (255, 0, 0))               # 紅
        p = ap.PilImage(self.png(im))
        arr = p.crop_bgr(10, 30)
        self.assertEqual(arr.shape, (20, 30, 3))
        self.assertEqual(tuple(arr[0, 0]), (0, 0, 255))             # BGR：紅色在最後一個通道
        self.assertTrue(arr.flags["C_CONTIGUOUS"])

    def test_blank_bands(self):
        im = Image.new("RGB", (200, 100), "white")
        for y in range(0, 20):
            for x in range(0, 200, 3):
                im.putpixel((x, y), (0, 0, 0))                     # 0..20 有內容
        for y in range(60, 80):
            for x in range(0, 200, 3):
                im.putpixel((x, y), (0, 0, 0))
        p = ap.PilImage(self.png(im))
        bands = p.blank_bands()
        self.assertIn([20, 60], bands)
        self.assertIn([80, 100], bands)

    def test_resize_width(self):
        p = ap.PilImage(self.png(Image.new("RGB", (400, 800), "white")))
        p.resize_width(200)
        self.assertEqual((p.width, p.height), (200, 400))

    def test_rgba_flattened_on_white(self):
        im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        p = ap.PilImage(self.png(im))
        self.assertEqual(tuple(p.crop_bgr(0, 10)[0, 0]), (255, 255, 255))

    def test_garbage_bytes_value_error(self):
        with self.assertRaises(ValueError):
            ap.PilImage(b"\x89PNG\r\n\x1a\nnot really")


if __name__ == "__main__":
    unittest.main()
