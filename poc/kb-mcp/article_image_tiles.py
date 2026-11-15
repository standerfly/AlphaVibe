"""長圖切片（010 T035、research R5「切片規則（T035 定案）」）。

定錨文章的表格圖常是很高的長圖（實測 2190×5195）。視覺模型對過大的圖會自動縮小，文字就失真，
所以送出前要切片。本模組分兩層：
  - 純 Python（僅標準庫、3.9 相容）：讀 PNG／JPEG／GIF／WebP 尺寸、判斷長圖、規劃切點、檢查位元組大小、
    合併各片轉寫文字（依重疊區去重）。
  - 像素處理委派給 `scraper/image_tiler.js`（Playwright canvas，沿用既有依賴，**不新增任何 Python 套件**；
    只在本機處理圖片檔、不連網）。

給 T036（轉寫模組）的用法：
    with open_tiles(圖檔路徑) as ts:          # 規劃→產生切片（暫存，離開時清除、不入庫）
        if ts.status != "ok":                 # "untranscribed" → 該圖標 untranscribed，原圖保留
            ...
        for index, data, media_type in ts.iter_tile_bytes():   # 逐片取得 bytes
            ...                                                # 每片已檢查過 base64 後大小
    text = merge_transcripts([各片轉寫文字...])               # 依重疊區列去重
"""
import base64
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

# ── 模型限制常數（集中於此；之後模型限制改變只需改這一處）─────────────────────────────
# 來源：T033 查到的官方文件 https://platform.claude.com/docs/en/build-with-claude/vision
# （查證日期 2026-11-15；Haiku 5.5 屬「高解析度層」）。
MAX_EDGE_PX = 2576               # 長邊超過會被模型自動縮小（寬度的硬上限；本模組也用於片高上限）
PATCH_PX = 28                    # 視覺 token ＝ ⌈寬/28⌉ × ⌈高/28⌉
MAX_VISION_TOKENS = 4784         # 超過會被自動縮小
MAX_IMAGE_SIDE_PX = 8000         # 單張上限 8000×8000 px
MAX_BASE64_BYTES = 10 * 1000 * 1000   # 單張上限 10 MB（base64 後）；文件未說明 MB 是否為 1024 制，取保守的 10^6 制
# ── 切片策略常數（research R5；T035 定案）──────────────────────────────────────────────
MAX_TILES = 8                    # 切片數上限；超過 → untranscribed（不縮小湊數）
LONG_IMAGE_MIN_HEIGHT_PX = 2000  # 長圖判定：高 ≥ 2000
LONG_IMAGE_MIN_RATIO = 1.5       # 且 高/寬 ≥ 1.5
TILE_HEIGHT_WIDTH_RATIO = 0.8    # 片高 ＝ min(寬×0.8, 由模型不縮圖條件算出的上限)
OVERLAP_MIN_RATIO = 0.15         # 相鄰切片重疊 ≥ 片高的 15%
OVERLAP_MIN_PX = 200             # 且 ≥ 200 px
END_SEARCH_MIN_RATIO = 0.6       # 找切點時，片底至少要有片高的 60%（避免為了貼近空白帶而切出太矮的片）
MERGE_MAX_OVERLAP_LINES = 40     # 合併時最多比對幾行重疊
MERGE_MIN_MATCH_CHARS = 6        # 只重疊 1 行時，該行至少要這麼多字元才算（避免 "N/A" 之類巧合）

TILER_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper", "image_tiler.js")
TILER_TIMEOUT_SEC = 180

# 狀態
STATUS_OK = "ok"
STATUS_UNTRANSCRIBED = "untranscribed"


# ── 尺寸讀取 ────────────────────────────────────────────────────────────────────────
def sniff_media_type(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_size(data: bytes) -> Optional[Tuple[int, int]]:
    """回傳 (寬, 高)；格式不明或資料損毀回傳 None。只讀標頭，不解碼像素。"""
    kind = sniff_media_type(data)
    try:
        if kind == "image/png":
            if data[12:16] != b"IHDR" or len(data) < 24:
                return None
            w, h = struct.unpack(">II", data[16:24])
        elif kind == "image/jpeg":
            w, h = _jpeg_size(data)
        elif kind == "image/gif":
            w, h = struct.unpack("<HH", data[6:10])
        elif kind == "image/webp":
            w, h = _webp_size(data)
        else:
            return None
    except (struct.error, ValueError, IndexError):
        return None
    return (w, h) if w > 0 and h > 0 else None


def _jpeg_size(data: bytes) -> Tuple[int, int]:
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:           # 填充位元組
            i += 1
            continue
        if marker in (0x01,) or 0xD0 <= marker <= 0xD9:   # 無長度欄位的標記
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0～SOF15，扣掉 DHT(C4)、JPG(C8)、DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    raise ValueError("no SOF marker")


def _webp_size(data: bytes) -> Tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X":
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
    elif chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    elif chunk == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        w, h = w & 0x3FFF, h & 0x3FFF
    else:
        raise ValueError("unknown webp chunk")
    return w, h


# ── 判斷與限制 ──────────────────────────────────────────────────────────────────────
def is_long_image(width: int, height: int) -> bool:
    """長圖：高/寬 ≥ 1.5 且高 ≥ 2000 px。"""
    return width > 0 and height >= LONG_IMAGE_MIN_HEIGHT_PX and height / width >= LONG_IMAGE_MIN_RATIO


def vision_tokens(width: int, height: int) -> int:
    return math.ceil(width / PATCH_PX) * math.ceil(height / PATCH_PX)


def fits_model_limits(width: int, height: int) -> bool:
    """整張送出而不被模型縮小的硬條件：寬 ≤2576、長邊 ≤2576、視覺 token ≤4784、單邊 ≤8000。"""
    return (width <= MAX_EDGE_PX and height <= MAX_EDGE_PX
            and width <= MAX_IMAGE_SIDE_PX and height <= MAX_IMAGE_SIDE_PX
            and vision_tokens(width, height) <= MAX_VISION_TOKENS)


def check_tile_bytes(bytes_len: int) -> bool:
    """送出前檢查：該片 base64 後的大小是否在上限內（True＝可送；False＝該圖應標 untranscribed）。"""
    if bytes_len < 0:
        return False
    return 4 * math.ceil(bytes_len / 3) <= MAX_BASE64_BYTES


def tile_max_height(width: int) -> int:
    """片高上限＝min(寬×0.8, 由「視覺 token ≤4784 且長邊 ≤2576」算出的上限)。"""
    cols = math.ceil(width / PATCH_PX)
    token_cap = (MAX_VISION_TOKENS // cols) * PATCH_PX
    return max(0, min(int(width * TILE_HEIGHT_WIDTH_RATIO), token_cap, MAX_EDGE_PX))


def scaled_dims(width: int, height: int) -> Tuple[int, int, bool]:
    """寬 >2576 → 先等比縮到寬 2576（回傳 resized=True）。高度四捨五入（與 image_tiler.js 的 Math.round 一致）。"""
    if width > MAX_EDGE_PX:
        return MAX_EDGE_PX, int(height * MAX_EDGE_PX / width + 0.5), True
    return width, height, False


def needs_tiling(width: int, height: int) -> bool:
    """（已縮放後的尺寸）長圖，或整張送會被模型縮小 → 要切片。短圖且滿足硬條件 → 整張送。"""
    return is_long_image(width, height) or not fits_model_limits(width, height)


# ── 規劃 ────────────────────────────────────────────────────────────────────────────
@dataclass
class TilePlan:
    status: str                                  # "ok" | "untranscribed"
    reason: str = ""                             # untranscribed 時的原因代碼
    orig_width: int = 0
    orig_height: int = 0
    width: int = 0                               # 縮放後（resized=False 時等於原尺寸）
    height: int = 0
    resized: bool = False                        # 原圖寬 >2576，已先縮圖（回報「已縮圖」）
    tiles: List[Tuple[int, int]] = field(default_factory=list)   # (top, bottom)，縮放後座標、bottom 不含

    @property
    def scale_width(self) -> int:
        return self.width if self.resized else 0

    @property
    def single_whole(self) -> bool:
        return len(self.tiles) == 1 and not self.resized


def _pick_cut(bands: Sequence[Sequence[int]], lo: int, hi: int) -> Optional[int]:
    """在 [lo, hi] 內找落在空白帶中的切點（取最大者；帶內取中點，必要時夾進視窗）。
    切點 c 保證 c-1 與 c 都在空白帶內（離開帶邊界至少 1 列）。"""
    best = None
    for bs, be in bands:
        a, b = max(bs + 1, lo), min(be - 1, hi)
        if a > b:
            continue
        c = min(max((bs + be) // 2, a), b)
        if best is None or c > best:
            best = c
    return best


def plan_tiles(width: int, height: int, bands: Optional[Sequence[Sequence[int]]] = None) -> TilePlan:
    """純規劃。width／height 為原圖尺寸；bands 為「縮放後座標」的空白帶 [[起列, 止列(不含)], ...]。"""
    w, h, resized = scaled_dims(width, height)
    base = TilePlan(STATUS_OK, "", width, height, w, h, resized)
    if w <= 0 or h <= 0:
        base.status, base.reason = STATUS_UNTRANSCRIBED, "bad_dimensions"
        return base
    if not needs_tiling(w, h):
        base.tiles = [(0, h)]
        return base

    th = tile_max_height(w)
    ov_min = max(math.ceil(th * OVERLAP_MIN_RATIO), OVERLAP_MIN_PX)
    if th <= ov_min + 1:
        base.status, base.reason = STATUS_UNTRANSCRIBED, "tile_too_small"
        return base
    bands = bands or []
    tiles: List[Tuple[int, int]] = []
    s = 0
    while True:
        limit = s + th
        if limit >= h:
            tiles.append((s, h))
            break
        lo_e = s + max(int(th * END_SEARCH_MIN_RATIO), ov_min + 1)
        e = _pick_cut(bands, lo_e, limit) or limit
        tiles.append((s, e))
        if len(tiles) >= MAX_TILES:
            base.status, base.reason = STATUS_UNTRANSCRIBED, "too_many_tiles"
            return base
        hi_s = e - ov_min
        ns = _pick_cut(bands, max(s + 1, e - 2 * ov_min), hi_s) or hi_s
        s = ns
    if len(tiles) > MAX_TILES:
        base.status, base.reason = STATUS_UNTRANSCRIBED, "too_many_tiles"
        return base
    base.tiles = tiles
    return base


# ── 產生切片（呼叫 Node）────────────────────────────────────────────────────────────
class TilerError(Exception):
    pass


def _node_binary() -> str:
    return shutil.which("node") or "/opt/homebrew/bin/node"


def run_tiler(cfg: dict) -> List[dict]:
    """執行 image_tiler.js，回傳事件 list（不含 summary）；失敗丟 TilerError。可在測試／T036 中替換（runner 參數）。"""
    node = _node_binary()
    if not os.path.exists(node):
        raise TilerError("no_node")
    try:
        proc = subprocess.run([node, TILER_JS], input=json.dumps(cfg), capture_output=True,
                              text=True, timeout=TILER_TIMEOUT_SEC, cwd=os.path.dirname(TILER_JS))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TilerError("tiler_run_failed:%s" % type(e).__name__)
    events, summary = [], None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "summary":
            summary = ev
        else:
            events.append(ev)
    if not summary or not summary.get("ok"):
        raise TilerError((summary or {}).get("error") or "tiler_no_summary")
    return events


class TileSet:
    """open_tiles 的結果。可當 context manager；離開時刪除暫存切片（原圖不動）。"""

    def __init__(self, plan: TilePlan, paths: List[str], media_types: List[str], temp_dir: Optional[str]):
        self.plan = plan
        self.paths = paths
        self.media_types = media_types
        self._temp_dir = temp_dir

    @property
    def status(self) -> str:
        return self.plan.status

    @property
    def reason(self) -> str:
        return self.plan.reason

    @property
    def resized(self) -> bool:
        return self.plan.resized

    def iter_tile_bytes(self) -> Iterator[Tuple[int, bytes, str]]:
        """逐片產出 (序號從 1 起, bytes, media_type)；status 非 ok 時不產出任何東西。"""
        if self.status != STATUS_OK:
            return
        for i, (p, mt) in enumerate(zip(self.paths, self.media_types), 1):
            with open(p, "rb") as f:
                yield i, f.read(), mt

    def cleanup(self) -> None:
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def __enter__(self) -> "TileSet":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()


def _untranscribed(orig_w: int, orig_h: int, reason: str, plan: Optional[TilePlan] = None) -> TileSet:
    p = plan or TilePlan(STATUS_UNTRANSCRIBED, reason, orig_w, orig_h)
    p.status, p.reason, p.tiles = STATUS_UNTRANSCRIBED, reason, []
    return TileSet(p, [], [], None)


def open_tiles(image_path: str, runner: Optional[Callable[[dict], List[dict]]] = None,
               tmp_root: Optional[str] = None) -> TileSet:
    """規劃→產生切片（暫存、不入庫）。預期內的失敗（格式不明、片數過多、位元組過大、瀏覽器缺失）
    一律回傳 status="untranscribed" 的 TileSet，不丟例外；原圖永遠不被修改或刪除。"""
    runner = runner or run_tiler
    with open(image_path, "rb") as f:
        head = f.read()
    size = image_size(head)
    if size is None:
        return _untranscribed(0, 0, "unsupported_or_corrupt_image")
    ow, oh = size
    media_type = sniff_media_type(head) or "application/octet-stream"
    w, h, resized = scaled_dims(ow, oh)

    # 短圖且不需縮放：不經瀏覽器，整張原檔送出
    if not resized and not needs_tiling(w, h):
        plan = plan_tiles(ow, oh)
        if not check_tile_bytes(len(head)):
            return _untranscribed(ow, oh, "tile_bytes_too_large", plan)
        return TileSet(plan, [image_path], [media_type], None)

    temp_dir = tempfile.mkdtemp(prefix="article_tiles_", dir=tmp_root)
    try:
        bands: List[List[int]] = []
        if needs_tiling(w, h):
            ev = runner({"mode": "bands", "path": image_path, "scale_width": w if resized else 0})
            info = next((e for e in ev if e.get("type") == "bands"), None)
            if not info or (info["width"], info["height"]) != (w, h):
                raise TilerError("tiler_size_mismatch")
            bands = info["bands"]
        plan = plan_tiles(ow, oh, bands)
        if plan.status != STATUS_OK:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _untranscribed(ow, oh, plan.reason, plan)
        ev = runner({"mode": "slice", "path": image_path, "scale_width": plan.scale_width,
                     "cuts": [list(t) for t in plan.tiles], "out_dir": temp_dir})
        tiles = sorted((e for e in ev if e.get("type") == "tile"), key=lambda e: e["index"])
        if len(tiles) != len(plan.tiles):
            raise TilerError("tiler_tile_count_mismatch")
        paths = [t["path"] for t in tiles]
        for p in paths:
            if not check_tile_bytes(os.path.getsize(p)):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _untranscribed(ow, oh, "tile_bytes_too_large", plan)
        return TileSet(plan, paths, ["image/png"] * len(paths), temp_dir)
    except TilerError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _untranscribed(ow, oh, "tiler_failed:%s" % e)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ── 合併轉寫 ────────────────────────────────────────────────────────────────────────
def _norm(line: str) -> str:
    return "".join(line.split())


def merge_transcripts(texts: Sequence[str]) -> str:
    """依重疊區的列文字去重合併各片轉寫：找「前文最後 k 行（忽略空白）＝下一片最前 k 行」的最大 k，
    丟掉下一片重複的 k 行。只重疊 1 行時，該行需 ≥6 個非空白字元，避免 "N/A" 之類的巧合被誤刪。
    （限制：若某列剛好被切斷、兩片轉出的文字不同，則該列兩份都會留下——寧可多留不可漏。）"""
    merged: List[str] = []
    for text in texts:
        lines = [ln for ln in (text or "").splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        if merged and lines:
            prev = [(_norm(x), x) for x in merged if x.strip()]
            cur = [_norm(x) for x in lines if x.strip()]
            best = 0
            for k in range(min(MERGE_MAX_OVERLAP_LINES, len(prev), len(cur)), 0, -1):
                if [p[0] for p in prev[-k:]] == cur[:k]:
                    if k == 1 and len(cur[0]) < MERGE_MIN_MATCH_CHARS:
                        continue
                    best = k
                    break
            if best:
                dropped = 0
                while dropped < best and lines:
                    if lines[0].strip():
                        dropped += 1
                    lines.pop(0)
        merged.extend(lines)
    return "\n".join(merged).strip("\n")
