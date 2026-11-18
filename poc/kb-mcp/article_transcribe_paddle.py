"""方案 C：本機 PaddleOCR 表格轉寫引擎（010 方案 C；不外送資料、不用付費 API）。

與 `article_transcribe.py`（Anthropic API 引擎，方案 A）並列、互不依賴；本模組**不修改**它，也不 import 它。
回傳值刻意與 `article_transcribe.transcribe_image()` 同形：
    {status, is_table, text, model, reason, abort}      # status ∈ transcribed／untranscribed
另加三個**額外**欄位（呼叫端可忽略）：
    retryable  True＝暫時性錯誤（引擎執行失敗、逾時），值得下次再試；False＝確定性失敗（重試也一樣）。
    detail     人看的補充說明（例如「未安裝」時的安裝步驟）；已過 safe_error 脫敏、長度受限。
    meta       {mode, tiles, size, elapsed, low_confidence:[…], warnings:[…]}，供評估工具（paddle_eval.py）使用。

設計重點
- **lazy import**：paddleocr／paddlepaddle／numpy／PIL 只在真的要轉寫時才 import；沒裝時本模組仍可 import，
  呼叫時回 reason=paddle_not_installed（abort=True，因為對每張圖都一樣）＋安裝提示，不讓專案 import 失敗。
- **預設離線**：`allow_download=False`。模型必須已在本機（`model_dir`／環境變數 ALPHAVIBE_PADDLE_MODEL_DIR／
  PaddleX 預設快取 ~/.paddlex/official_models）；缺模型 → reason=model_not_available（abort=True），**不會偷偷連網下載**。
  離線時另設 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK／HF_HUB_OFFLINE，避免 PaddleX 啟動時的連線檢查。
  這些環境變數必須在 paddlex 第一次 import 之前設定；同一行程內第一次 import 之後再改無效（評估工具在啟動時就決定）。
- **兩種表格重建模式**（`mode`）：
    ocr_grid（預設）：只用 PP-OCRv5 文字偵測＋辨識（兩個模型約 170 MB），再由本模組依文字框座標分群成列／欄。
        不依賴表格結構模型（官方表格結構準確率僅 63.7～69.7%），無框表格也能用；缺點是合併儲存格只能放在第一欄。
    table_pipeline：PaddleOCR 的 TableRecognitionPipelineV2（版面偵測＋表格分類＋SLANeXt＋儲存格偵測）→ pred_html → Markdown。
        需要 `paddleocr[doc-parser]`，模型約 1.2 GB，且底層用 PP-OCRv4 辨識；官方結構準確率低，須實測。
- **長圖**：重用 `article_image_tiles.plan_tiles()` 的切片規則（片高≈寬×0.8、重疊≥15%且≥200px、切點落空白帶、
  最多 8 片，與 API 路徑一致，才能逐片並排比對），像素處理改用 numpy／PIL（paddle 本來就依賴它們，不需要 Node）。
  理由：表格結構模型與版面偵測會把整張圖縮到幾百 px，長圖整張丟會讓文字糊掉。
  ocr_grid 模式在「全圖座標」上合併各片文字框（丟棄貼著內部切線的被切斷框、重疊區依位置與文字去重）後只分群一次，
  所以欄位在各片之間一致；table_pipeline 模式各片 HTML 無共同座標，改以列文字去重合併。
- **不猜測**：辨識信心 < min_score 的格子一律寫 `[?]`（猜測值只放 meta.low_confidence，不進 text）；
  沒有任何文字被偵測 → untranscribed（FR-017：不得以空白充數）。
- Python 3.9 相容。
"""
import html.parser
import logging
import os
import time

import article_image_tiles
from investanchors_redact import safe_error

log = logging.getLogger("article_transcribe_paddle")

ENGINE_NAME = "paddleocr"
MODE_GRID = "ocr_grid"
MODE_PIPELINE = "table_pipeline"
MODES = (MODE_GRID, MODE_PIPELINE)

LOW_CONF = "[?]"
DEFAULT_MIN_SCORE = 0.80          # 尚未用真實財經表格調校；PO 抽查後再調
MODEL_DIR_ENV = "ALPHAVIBE_PADDLE_MODEL_DIR"
DEFAULT_VARIANT = "server"        # server（準、慢、約 170MB）／mobile（快、小）
DEFAULT_DET_MAX_SIDE = 1280       # 文字偵測輸入長邊上限（px）。不設的話 PaddleOCR 對 1678x2190 的切片會嘗試配置 ~18GB 記憶體

# PaddleOCR 3.x 官方模型名稱（paddleocr 3.7.0／paddlex 3.7.2 實測；官方改名時只需改這裡）。
OCR_MODELS = {
    "server": ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"),
    "mobile": ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"),
}

INSTALL_HINT = (
    "未安裝 PaddleOCR。請在獨立 venv 安裝（不要裝進正式環境／既有 .venv）："
    "python3 -m venv ~/.venvs/paddle && ~/.venvs/paddle/bin/pip install paddlepaddle==3.3.1 paddleocr==3.7.0；"
    "完整步驟見 specs/010-investanchors-article-import/paddle-setup.md"
)
MODEL_HINT = (
    "找不到本機模型。離線模式不會自動下載：請先用 `paddle_eval.py --allow-download` 在可連網時下載，"
    "或以 model_dir／環境變數 %s 指向含 PP-OCRv5_server_det 與 PP-OCRv5_server_rec 子資料夾的目錄" % MODEL_DIR_ENV
)

DEPENDENCY_HINT = (
    "table_pipeline 模式需要額外依賴：pip install \"paddleocr[doc-parser]==3.7.0\"（ocr_grid 模式不需要）")

_BLANK_TOLERANCE = 8              # 整列與該列主色的灰階差 ≤ 此值視為同色
_BLANK_FRACTION = 0.98
_MIN_BAND_PX = 4
_EDGE_PX = 3                      # 文字框距內部切線 ≤ 此值視為被切斷


# ── 例外與結果 ───────────────────────────────────────────────────────────────────────
class PaddleUnavailable(Exception):
    """引擎無法使用的確定性原因（未安裝、缺模型、缺影像函式庫）。reason 是固定代碼。"""

    def __init__(self, reason, hint="", cause=None):
        """hint＝我們自己寫的固定提示（可含路徑，不脫敏）；cause＝底層例外訊息（一律過 safe_error 脫敏）。"""
        Exception.__init__(self, reason)
        self.reason = reason
        self.detail = hint + (("｜" if hint else "") + safe_error(cause) if cause else "")


def _result(status, reason=None, is_table=None, text=None, abort=False, model=None,
            retryable=False, detail=None, meta=None):
    return {"status": status, "is_table": is_table, "text": text,
            "model": model or ENGINE_NAME, "reason": reason, "abort": abort,
            "retryable": retryable, "detail": detail, "meta": meta or {}}


def _fail(reason, abort=False, retryable=False, detail=None, model=None, meta=None):
    return _result("untranscribed", reason=safe_error(reason), abort=abort, retryable=retryable,
                   detail=detail or None, model=model, meta=meta)


# ── 表格：grid（list of rows of str）→ Markdown ─────────────────────────────────────
def _cell_text(s):
    s = " ".join(str(s if s is not None else "").split())
    return s.replace("|", "\\|")


def grid_to_markdown(grid):
    """第一列當表頭；各列補齊成相同欄數。空儲存格輸出空字串（不填猜測值）。"""
    rows = [list(r) for r in grid if r is not None]
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    if ncols == 0:
        return ""
    norm = [[_cell_text(c) for c in r] + [""] * (ncols - len(r)) for r in rows]

    def line(cells):
        return "| " + " | ".join(cells) + " |"
    out = [line(norm[0]), "| " + " | ".join(["---"] * ncols) + " |"]
    out.extend(line(r) for r in norm[1:])
    return "\n".join(out)


# ── 表格：HTML → grid（支援 colspan／rowspan、空格、巢狀標籤）───────────────────────────
class _TableParser(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.tables = []          # 每個元素 {"rows": [[cell...]...]}；cell = {text, colspan, rowspan}
        self._cur = None
        self._row = None
        self._cell = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._cur = {"rows": []}
                self.tables.append(self._cur)
        elif self._cur is None or self._depth != 1:
            return
        elif tag == "tr":
            self._row = []
            self._cur["rows"].append(self._row)
        elif tag in ("td", "th"):
            if self._row is None:                       # 缺 <tr> 的壞 HTML
                self._row = []
                self._cur["rows"].append(self._row)
            self._cell = {"text": [], "colspan": _span(a.get("colspan")), "rowspan": _span(a.get("rowspan"))}
            self._row.append(self._cell)
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._cur, self._row, self._cell = None, None, None
        elif tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)


def _span(v):
    try:
        return max(1, min(int(v), 50))
    except (TypeError, ValueError):
        return 1


def parse_html_tables(html_text):
    """解析 HTML，回傳 [{"grid": [[str]], "anchors": [(row, col), ...]}, ...]。
    anchors 依 td 在文件中的順序，記錄每個儲存格左上角的 (列, 欄)，供與 cell_box_list 對位。
    合併儲存格：文字只放在左上角，被合併涵蓋的其他格留空（不複製、不猜測）。"""
    parser = _TableParser()
    try:
        parser.feed(html_text or "")
        parser.close()
    except Exception:
        return []
    out = []
    for t in parser.tables:
        occupied = {}             # (r, c) -> True
        cells = {}
        anchors = []
        nrows = 0
        ncols = 0
        for r, row in enumerate(t["rows"]):
            c = 0
            for cell in row:
                while occupied.get((r, c)):
                    c += 1
                text = " ".join("".join(cell["text"]).split())
                cells[(r, c)] = text
                anchors.append((r, c))
                for dr in range(cell["rowspan"]):
                    for dc in range(cell["colspan"]):
                        occupied[(r + dr, c + dc)] = True
                nrows = max(nrows, r + cell["rowspan"])
                ncols = max(ncols, c + cell["colspan"])
                c += cell["colspan"]
        if not nrows or not ncols:
            continue
        grid = [[cells.get((r, c), "") for c in range(ncols)] for r in range(nrows)]
        out.append({"grid": grid, "anchors": anchors})
    return out


def html_to_markdown(html_text):
    """HTML 表格 → Markdown 表格（多個 table 以空行隔開）。沒有表格回空字串。"""
    return "\n\n".join(grid_to_markdown(t["grid"]) for t in parse_html_tables(html_text))


# ── 文字框 → grid（ocr_grid 模式）────────────────────────────────────────────────────
class Box(object):
    """一個辨識出的文字框；座標為全圖像素。"""
    __slots__ = ("x0", "y0", "x1", "y1", "text", "score")

    def __init__(self, x0, y0, x1, y1, text, score):
        self.x0, self.y0, self.x1, self.y1 = float(x0), float(y0), float(x1), float(y1)
        self.text, self.score = text, score

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2.0

    @property
    def h(self):
        return max(1.0, self.y1 - self.y0)


def _median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return 0.0
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def cluster_rows(boxes):
    """依垂直位置分群成列（回傳 list of list[Box]，由上而下；列內由左而右）。"""
    if not boxes:
        return []
    med_h = _median([b.h for b in boxes])
    ordered = sorted(boxes, key=lambda b: b.cy)
    rows, row_cy = [], []
    for b in ordered:
        if rows and abs(b.cy - row_cy[-1]) <= 0.55 * med_h:
            rows[-1].append(b)
            row_cy[-1] = sum(x.cy for x in rows[-1]) / len(rows[-1])
        else:
            rows.append([b])
            row_cy.append(b.cy)
    return [sorted(r, key=lambda b: b.x0) for r in rows]


def column_bands(boxes, gap=None):
    """欄帶：把「窄框」的水平區間投影後合併（間隙 ≤ gap 視為同欄）。橫跨很多欄的寬框（標題列、合併儲存格）
    先排除，避免把所有欄黏成一欄。回傳 [(x0, x1), ...] 由左而右。"""
    if not boxes:
        return []
    med_h = _median([b.h for b in boxes])
    gap = med_h * 0.6 if gap is None else gap
    span = max(b.x1 for b in boxes) - min(b.x0 for b in boxes)
    narrow = [b for b in boxes if (b.x1 - b.x0) <= 0.45 * span] or list(boxes)
    ivs = sorted((b.x0, b.x1) for b in narrow)
    bands = [list(ivs[0])]
    for x0, x1 in ivs[1:]:
        if x0 - bands[-1][1] <= gap:
            bands[-1][1] = max(bands[-1][1], x1)
        else:
            bands.append([x0, x1])
    return [(a, b) for a, b in bands]


def _band_index(box, bands):
    """與框水平重疊最多的欄帶索引；都不重疊則取中心最近者。"""
    best, best_ov = None, 0.0
    for i, (a, b) in enumerate(bands):
        ov = min(b, box.x1) - max(a, box.x0)
        if ov > best_ov:
            best, best_ov = i, ov
    if best is not None:
        return best
    return min(range(len(bands)), key=lambda i: abs((bands[i][0] + bands[i][1]) / 2.0 - box.cx))


def boxes_to_grid(boxes, min_score=DEFAULT_MIN_SCORE):
    """文字框 → (grid, low_confidence)。low_confidence 是 [{row, col, guess, score}]（猜測值**不**進 grid）。"""
    boxes = [b for b in boxes if b.text is not None and str(b.text).strip()]
    rows = cluster_rows(boxes)
    if not rows:
        return [], []
    bands = column_bands(boxes)
    grid, low = [], []
    for ri, row in enumerate(rows):
        cells = [[] for _ in bands]
        for b in row:
            cells[_band_index(b, bands)].append(b)
        out_row = []
        for ci, cb in enumerate(cells):
            if not cb:
                out_row.append("")
                continue
            if any((b.score is not None and b.score < min_score) for b in cb):
                out_row.append(LOW_CONF)
                low.append({"row": ri, "col": ci, "guess": " ".join(b.text for b in cb),
                            "score": round(min(b.score for b in cb if b.score is not None), 3)})
            else:
                out_row.append(" ".join(b.text for b in cb))
        grid.append(out_row)
    return grid, low


def is_table_grid(grid):
    """至少 2 列、至少 2 個非空欄 → 視為表格。"""
    if len(grid) < 2:
        return False
    ncols = max(len(r) for r in grid)
    used = [any((r[c] if c < len(r) else "").strip() for r in grid) for c in range(ncols)]
    return sum(1 for u in used if u) >= 2


def plain_text(boxes):
    """非表格：依列由上而下、列內由左而右，每列一行。"""
    return "\n".join(" ".join(b.text for b in row) for row in cluster_rows(
        [b for b in boxes if b.text is not None and str(b.text).strip()]))


# ── 切片間合併 ──────────────────────────────────────────────────────────────────────
def merge_tile_boxes(tile_boxes, tile_spans):
    """各片文字框（片內座標）→ 全圖座標、去除被切斷的框與重疊區重複框。
    tile_boxes[i]：第 i 片的 Box 清單（片內座標）；tile_spans[i]：(top, bottom)（全圖座標）。"""
    n = len(tile_spans)
    kept = []                         # (tile_index, Box 全圖座標)
    for i, (boxes, (top, bottom)) in enumerate(zip(tile_boxes, tile_spans)):
        for b in boxes:
            g = Box(b.x0, b.y0 + top, b.x1, b.y1 + top, b.text, b.score)
            if n > 1:
                if i > 0 and b.y0 <= _EDGE_PX:                        # 貼著上方內部切線：被切斷
                    continue
                if i < n - 1 and b.y1 >= (bottom - top) - _EDGE_PX:   # 貼著下方內部切線：被切斷
                    continue
            kept.append((i, g))
    merged = []
    for i, g in kept:
        dup = False
        for j, m in merged:
            if j == i:
                continue
            if _same_box(m, g):
                dup = True
                if (g.score or 0) > (m.score or 0):                   # 留信心較高者
                    m.text, m.score = g.text, g.score
                break
        if not dup:
            merged.append((i, g))
    return [g for _i, g in merged]


def _same_box(a, b):
    """兩框幾乎重疊（重疊重複辨識的同一格）：中心距離小於框高的一半，且水平重疊過半。"""
    if abs(a.cy - b.cy) > 0.5 * max(a.h, b.h):
        return False
    ov = min(a.x1, b.x1) - max(a.x0, b.x0)
    return ov > 0.5 * min(a.x1 - a.x0, b.x1 - b.x0)


def _norm_row(row):
    return "".join("".join(str(c).split()) for c in row)


def _find_overlap(merged, rows):
    """找前文結尾與下一片開頭的重疊。允許前文最後 1 列、下一片最前 2 列是「被切線切斷的殘缺列」而不相符
    （規劃保證相鄰切片重疊 ≥200px，所以下一片開頭的列必然在前文已有完整版本）。
    回傳 (drop_tail, skip_head, k)：丟掉前文結尾 drop_tail 列、下一片開頭 skip_head 列後，兩者的 k 列相同。
    k 最大者優先，其次丟得最少者；找不到回 (0, 0, 0)。只重疊 1 列時該列至少 6 個非空白字元（避免巧合）。"""
    best = (0, 0, 0)
    max_k = min(len(merged), len(rows), article_image_tiles.MERGE_MAX_OVERLAP_LINES)
    nm = [_norm_row(r) for r in merged]
    nr = [_norm_row(r) for r in rows]
    for k in range(max_k, 0, -1):
        for drops in ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (1, 2)):
            dt, sh = drops
            if len(merged) - dt < k or len(rows) - sh < k:
                continue
            if nm[len(merged) - dt - k:len(merged) - dt] == nr[sh:sh + k]:
                if k == 1 and len(nr[sh]) < article_image_tiles.MERGE_MIN_MATCH_CHARS:
                    continue
                return (dt, sh, k)
    return best


def merge_grids(grids):
    """table_pipeline 用：依序串接各片的 grid，去掉重疊列（見 _find_overlap）；全空白列一律丟掉
    （表格結構模型在切線附近常吐出空列，保留只會污染）。回傳 (grid, warnings)。"""
    merged, warnings = [], []
    ncols = max([len(r) for g in grids for r in g] or [0])
    widths = set(len(g[0]) for g in grids if g)
    if len(widths) > 1:
        warnings.append("columns_mismatch_between_tiles")
    for g in grids:
        rows = [list(r) + [""] * (ncols - len(r)) for r in g if any(str(c).strip() for c in r)]
        dt, sh, k = _find_overlap(merged, rows)
        if k:
            if dt:
                del merged[len(merged) - dt:]
            rows = rows[sh + k:]
        merged.extend(rows)
    return merged, warnings


# 解碼前的像素上限（防解壓炸彈）：實際最大的文章圖 2190x5327≈1170 萬像素，上限放寬到 5000 萬
MAX_IMAGE_PIXELS = 50000000


# ── 影像層（numpy／PIL；可注入以便測試）──────────────────────────────────────────────
class PilImage(object):
    """以 PIL／numpy 實作的影像處理；paddle 本來就依賴它們。"""

    def __init__(self, data):
        try:
            import numpy as np
            from PIL import Image
        except ImportError as e:
            raise PaddleUnavailable("image_lib_missing", "缺少 numpy／Pillow（paddle 的依賴，裝好 paddlepaddle 通常就有）", e)
        self._np = np
        try:
            import io
            im = Image.open(io.BytesIO(data))
            pixels = int(im.size[0]) * int(im.size[1])      # 只讀檔頭，尚未解碼
            if pixels > MAX_IMAGE_PIXELS:
                raise ValueError("image_too_large")
            im.load()
        except ValueError:
            raise
        except Exception:
            raise ValueError("image_decode_error")
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            im = bg
        self._im = im.convert("RGB")
        self.width, self.height = self._im.size

    def resize_width(self, new_w):
        from PIL import Image
        new_h = int(self.height * new_w / self.width + 0.5)
        self._im = self._im.resize((new_w, new_h), Image.LANCZOS)
        self.width, self.height = self._im.size

    def blank_bands(self):
        np = self._np
        arr = np.asarray(self._im.convert("L"), dtype="int16")
        med = np.median(arr, axis=1)
        near = (np.abs(arr - med[:, None]) <= _BLANK_TOLERANCE).mean(axis=1) >= _BLANK_FRACTION
        bands, start = [], None
        for y, v in enumerate(near.tolist() + [False]):
            if v and start is None:
                start = y
            elif not v and start is not None:
                if y - start >= _MIN_BAND_PX:
                    bands.append([start, y])
                start = None
        return bands

    def crop_bgr(self, top, bottom):
        """回傳 paddle 吃的 BGR ndarray（OpenCV 慣例）。"""
        np = self._np
        arr = np.asarray(self._im.crop((0, top, self.width, bottom)))
        return np.ascontiguousarray(arr[:, :, ::-1])


def _open_image(data):
    return PilImage(data)


# ── 引擎 ─────────────────────────────────────────────────────────────────────────────
def _model_base_dir(model_dir=None):
    if model_dir:
        return model_dir
    env = os.environ.get(MODEL_DIR_ENV)
    if env:
        return env
    cache = os.environ.get("PADDLE_PDX_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".paddlex")
    return os.path.join(cache, "official_models")


def _model_present(base, name):
    d = os.path.join(base, name)
    return os.path.isdir(d) and any(
        os.path.exists(os.path.join(d, f)) for f in ("inference.yml", "inference.json", "inference.pdiparams"))


def prepare_environment(allow_download):
    """在 import paddle 之前設定環境變數。離線時關掉 PaddleX 的連線檢查與 HF 連線。"""
    if not allow_download:
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def import_paddleocr():
    """lazy import；沒裝回 PaddleUnavailable（reason=paddle_not_installed）。"""
    try:
        import paddleocr
    except ImportError as e:
        raise PaddleUnavailable("paddle_not_installed", INSTALL_HINT, e)
    return paddleocr


def _as_list(v):
    """None → []；list／ndarray → list（避免對 ndarray 做 `or` 的真值判斷）。"""
    return [] if v is None else list(v)


def _to_box_list(res):
    """PaddleOCR OCRResult（dict 形）→ [Box]。優先用 rec_boxes（x0,y0,x1,y1），否則由 rec_polys 取外接框。"""
    texts = _as_list(res.get("rec_texts"))
    scores = _as_list(res.get("rec_scores"))
    boxes = res.get("rec_boxes")
    polys = res.get("rec_polys")
    out = []
    for i, t in enumerate(texts):
        s = float(scores[i]) if i < len(scores) else None
        if boxes is not None and len(boxes) > i:
            x0, y0, x1, y1 = [float(v) for v in list(boxes[i])[:4]]
        elif polys is not None and len(polys) > i:
            xs = [float(p[0]) for p in polys[i]]
            ys = [float(p[1]) for p in polys[i]]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            continue
        out.append(Box(x0, y0, x1, y1, t, s))
    return out


class PaddleEngine(object):
    """包住 paddleocr 的薄轉接層，只暴露 analyze(bgr_array) → {"boxes": [Box], "tables": [...]}。
    建構時才 import paddleocr 並載入模型（一個引擎實例重複使用；載入約 1～35 秒）。"""

    def __init__(self, mode=MODE_GRID, variant=DEFAULT_VARIANT, model_dir=None, allow_download=False,
                 enable_mkldnn=False, paddleocr_module=None, det_max_side=DEFAULT_DET_MAX_SIDE):
        if mode not in MODES:
            raise ValueError("unknown mode: %r" % (mode,))
        if variant not in OCR_MODELS:
            raise ValueError("unknown variant: %r" % (variant,))
        self.mode, self.variant = mode, variant
        self.allow_download = bool(allow_download)
        self.model_base = _model_base_dir(model_dir)
        self.enable_mkldnn = bool(enable_mkldnn)
        self.det_max_side = int(det_max_side) if det_max_side else None
        if paddleocr_module is None:
            prepare_environment(self.allow_download)
            paddleocr_module = import_paddleocr()
        self._p = paddleocr_module
        self.version = getattr(paddleocr_module, "__version__", "unknown")
        self.label = "%s-%s/%s/%s" % (ENGINE_NAME, self.version, variant, mode)
        det, rec = OCR_MODELS[variant]
        kw = dict(self._model_kwargs("text_detection", det), **self._model_kwargs("text_recognition", rec))
        common = dict(use_doc_orientation_classify=False, use_doc_unwarping=False,
                      enable_mkldnn=self.enable_mkldnn)
        try:
            if mode == MODE_GRID:
                self._ocr = paddleocr_module.PaddleOCR(use_textline_orientation=False, **dict(common, **kw))
                self._pipe = None
            else:
                self._pipe = paddleocr_module.TableRecognitionPipelineV2(**dict(common, **kw))
                self._ocr = None
        except PaddleUnavailable:
            raise
        except Exception as e:
            if "dependenc" in str(e).lower() or isinstance(e, ImportError):
                raise PaddleUnavailable("paddle_dependency_missing", DEPENDENCY_HINT, "%s: %s" % (type(e).__name__, e))
            raise PaddleUnavailable("engine_init_failed", "", "%s: %s" % (type(e).__name__, e))

    def _model_kwargs(self, prefix, name):
        """已在本機的模型 → 傳 *_model_dir（不連網）；不在本機 → 允許下載才只傳名稱，否則 model_not_available。"""
        if _model_present(self.model_base, name):
            return {prefix + "_model_name": name, prefix + "_model_dir": os.path.join(self.model_base, name)}
        if self.allow_download:
            return {prefix + "_model_name": name}
        raise PaddleUnavailable("model_not_available", "%s｜缺少 %s（找過 %s）" % (MODEL_HINT, name, self.model_base))

    def _det_kwargs(self):
        if not self.det_max_side:
            return {}
        return {"text_det_limit_type": "max", "text_det_limit_side_len": self.det_max_side}

    def analyze(self, bgr):
        if self.mode == MODE_GRID:
            res = self._ocr.predict(bgr, **self._det_kwargs())
            return {"boxes": _to_box_list(res[0]) if res else [], "tables": []}
        res = self._pipe.predict(bgr, **self._det_kwargs())
        if not res:
            return {"boxes": [], "tables": []}
        r = res[0]
        boxes = _to_box_list(r.get("overall_ocr_res") if r.get("overall_ocr_res") is not None else {})
        tables = []
        for tr in _as_list(r.get("table_res_list")):
            tables.append({"html": tr.get("pred_html") or "",
                           "cell_boxes": [list(map(float, list(c)[:4])) for c in _as_list(tr.get("cell_box_list"))],
                           "ocr": _to_box_list(tr.get("table_ocr_pred") if tr.get("table_ocr_pred") is not None else {})})
        return {"boxes": boxes, "tables": tables}


_ENGINES = {}


def get_engine(mode=MODE_GRID, variant=DEFAULT_VARIANT, model_dir=None, allow_download=False,
               enable_mkldnn=False, det_max_side=DEFAULT_DET_MAX_SIDE):
    """行程內快取引擎（載入模型很慢；匯入流程逐圖呼叫時共用同一個）。"""
    key = (mode, variant, _model_base_dir(model_dir), bool(allow_download), bool(enable_mkldnn),
           det_max_side)
    eng = _ENGINES.get(key)
    if eng is None:
        eng = PaddleEngine(mode=mode, variant=variant, model_dir=model_dir, allow_download=allow_download,
                           enable_mkldnn=enable_mkldnn, det_max_side=det_max_side)
        _ENGINES[key] = eng
    return eng


def clear_engine_cache():
    _ENGINES.clear()


# ── pipeline 模式：HTML＋信心 → grid ─────────────────────────────────────────────────
def _tables_to_grid(tables, min_score):
    """把一片的 table_pipeline 結果轉成 (grid, low_confidence, warnings)。多個表格依序串接。
    儲存格信心：以 cell_box_list（與 td 同序）找出含有低信心 OCR 框中心的儲存格，改寫成 [?]。"""
    grid, low, warnings = [], [], []
    for t in tables:
        parsed = parse_html_tables(t["html"])
        if not parsed:
            continue
        pt = parsed[0]
        g = [list(r) for r in pt["grid"]]
        cboxes = t.get("cell_boxes") or []
        if len(cboxes) != len(pt["anchors"]):
            warnings.append("cell_boxes_misaligned")
        else:
            for ob in t.get("ocr") or []:
                if ob.score is None or ob.score >= min_score:
                    continue
                for (r, c), cb in zip(pt["anchors"], cboxes):
                    if cb[0] <= ob.cx <= cb[2] and cb[1] <= ob.cy <= cb[3]:
                        if g[r][c] != LOW_CONF:
                            low.append({"row": r, "col": c, "guess": g[r][c], "score": round(ob.score, 3)})
                            g[r][c] = LOW_CONF
                        break
        grid.extend(g)
    return grid, low, warnings


# ── 對外 API ─────────────────────────────────────────────────────────────────────────
def _load_bytes(image):
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    with open(image, "rb") as f:
        return f.read()


def transcribe_image_paddle(image, *, model_dir=None, allow_download=False, mode=MODE_GRID,
                            variant=DEFAULT_VARIANT, min_score=DEFAULT_MIN_SCORE, engine=None,
                            timeout=None, image_opener=None, enable_mkldnn=False, clock=None,
                            det_max_side=DEFAULT_DET_MAX_SIDE):
    """轉寫一張圖（bytes 或檔案路徑；長圖內部自動切片）。

    回傳 {status, is_table, text, model, reason, abort, retryable, detail, meta}（見模組說明）。永不丟例外。
    - engine：可注入（測試／評估工具重用）；省略時用 get_engine() 的行程內快取。
    - timeout：整張圖的秒數上限（只在片與片之間檢查；單片推論無法中斷）→ reason=timeout（retryable）。
    - image_opener：測試注入用；預設 PIL／numpy。
    """
    clock = clock or time.time
    t0 = clock()
    opener = image_opener or _open_image
    try:
        data = _load_bytes(image)
    except OSError:
        return _fail("image_read_error")
    if article_image_tiles.sniff_media_type(data) is None:
        return _fail("unsupported_image_format")
    try:
        if engine is None:
            engine = get_engine(mode, variant, model_dir, allow_download, enable_mkldnn, det_max_side)
        mode = getattr(engine, "mode", mode)
        label = getattr(engine, "label", ENGINE_NAME)
        img = opener(data)
    except PaddleUnavailable as e:
        return _fail(e.reason, abort=True, detail=e.detail)
    except ValueError as e:
        return _fail(str(e) or "image_decode_error")
    except Exception as e:
        return _fail("engine_init_failed", abort=True, detail=safe_error("%s: %s" % (type(e).__name__, e)))

    meta = {"mode": mode, "size": [img.width, img.height], "tiles": 0, "low_confidence": [],
            "warnings": []}
    try:
        ow, oh = img.width, img.height
        w, h, resized = article_image_tiles.scaled_dims(ow, oh)
        if resized:
            img.resize_width(w)
        bands = img.blank_bands() if article_image_tiles.needs_tiling(w, h) else None
        plan = article_image_tiles.plan_tiles(ow, oh, bands)
        if plan.status != article_image_tiles.STATUS_OK:
            return _fail(plan.reason or "tile_plan_failed", model=label, meta=meta)
        meta["tiles"] = len(plan.tiles)
        per_tile = []
        for (top, bottom) in plan.tiles:
            if timeout is not None and clock() - t0 > timeout:
                return _fail("timeout", retryable=True, model=label, meta=meta)
            per_tile.append(engine.analyze(img.crop_bgr(top, bottom)))
        return _assemble(per_tile, plan.tiles, mode, min_score, label, meta, t0, clock)
    except PaddleUnavailable as e:
        return _fail(e.reason, abort=True, detail=e.detail, model=label, meta=meta)
    except MemoryError:
        return _fail("out_of_memory", retryable=True, model=label, meta=meta)
    except Exception as e:
        log.warning("PaddleOCR 轉寫失敗：%s", safe_error("%s: %s" % (type(e).__name__, e)))
        return _fail("engine_error:%s" % type(e).__name__, retryable=True, model=label, meta=meta)


def _assemble(per_tile, spans, mode, min_score, label, meta, t0, clock):
    if mode == MODE_GRID:
        boxes = merge_tile_boxes([a["boxes"] for a in per_tile], spans)
        if not boxes:
            return _fail("no_text_detected", model=label, meta=_done(meta, t0, clock))
        grid, low = boxes_to_grid(boxes, min_score)
        meta["low_confidence"] = low
        if is_table_grid(grid):
            return _result("transcribed", is_table=True, text=grid_to_markdown(grid), model=label,
                           meta=_done(meta, t0, clock))
        return _result("transcribed", is_table=False, text=plain_text(boxes), model=label,
                       meta=_done(meta, t0, clock))
    grids = []
    for i, a in enumerate(per_tile):
        g, low, warns = _tables_to_grid(a["tables"], min_score)
        if not g and a["boxes"]:                       # 該片沒偵測到表格：退回文字框分群
            g, low = boxes_to_grid(merge_tile_boxes([a["boxes"]], [(0, 10 ** 9)]), min_score)
            warns = warns + ["tile_%d_no_table_fallback_grid" % (i + 1)]
        meta["low_confidence"].extend(dict(x, tile=i + 1) for x in low)
        meta["warnings"].extend(warns)
        grids.append(g)
    grid, warns = merge_grids(grids)
    meta["warnings"].extend(warns)
    if not grid:
        return _fail("no_text_detected", model=label, meta=_done(meta, t0, clock))
    if is_table_grid(grid):
        return _result("transcribed", is_table=True, text=grid_to_markdown(grid), model=label,
                       meta=_done(meta, t0, clock))
    flat = "\n".join(" ".join(c for c in r if c) for r in grid)
    return _result("transcribed", is_table=False, text=flat, model=label, meta=_done(meta, t0, clock))


def _done(meta, t0, clock):
    meta["elapsed"] = round(clock() - t0, 3)
    return meta


def transcribe_tiles_paddle(tiles, get_secret=None, api_url=None, model=None, timeout=None,
                            sleeper=None, merge=None, **kwargs):
    """與 `article_transcribe.transcribe_image(tiles, ...)` 同簽名的相容入口，方便日後接進
    investanchors_import 的轉寫引擎抽象（`self.transcribe`）。get_secret／api_url／sleeper／merge 一律忽略
    （本機引擎不需要金鑰、不連網；多片合併用本模組自己的座標去重）。

    注意：呼叫端若已用 Node 切好片（tiles 為多個 bytes），這裡**逐片**辨識、再以 merge_grids 依列去重，
    無法使用全圖座標；單片（bytes 清單長度 1）時等同 transcribe_image_paddle(整張)。
    僅需整張圖時請直接呼叫 transcribe_image_paddle（切片與合併品質較好）。"""
    if not tiles:
        return _fail("no_tiles")
    if len(tiles) == 1:
        return transcribe_image_paddle(tiles[0], timeout=timeout, **kwargs)
    grids, texts, any_table, last = [], [], False, None
    for t in tiles:
        r = transcribe_image_paddle(t, timeout=timeout, **kwargs)
        if r["status"] != "transcribed":
            return r
        last = r
        any_table = any_table or bool(r["is_table"])
        texts.append(r["text"])
    merged = article_image_tiles.merge_transcripts(texts)
    return _result("transcribed", is_table=any_table, text=merged, model=last["model"],
                   meta={"mode": last["meta"].get("mode"), "tiles": len(tiles)})


__all__ = [
    "transcribe_image_paddle", "transcribe_tiles_paddle", "html_to_markdown", "grid_to_markdown",
    "parse_html_tables", "PaddleEngine", "PaddleUnavailable", "get_engine", "clear_engine_cache",
]
