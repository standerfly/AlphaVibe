"""相片格式支援：副檔名分類、sidecar 路徑、拍攝日期、縮圖/預覽圖產生。

JPG／HEIC 用 macOS 內建 `sips` 縮放；RAW（含 Sigma X3F）macOS 解不開，
改用 `exiftool` 抽出檔案內嵌的 JPEG（`JpgFromRaw` 優先、其次 `PreviewImage`），
再用 `sips` 縮放。X3F 實測：`JpgFromRaw` 是 2640x1760，`PreviewImage`
只有 640x480，所以必須優先取 `JpgFromRaw`。

RAW 格式 exiftool 多半只能讀不能寫（X3F 的 exiftool 寫入清單裡沒有），所以
評分/標籤改寫到旁邊的 `<檔名>.xmp` sidecar，原始檔位元組不動。
"""
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from datetime import datetime

JPEG_EXTS = (".jpg", ".jpeg")
HEIC_EXTS = (".heic", ".heif")
# exiftool 可直接寫入 XMP 的 RAW（DNG 是公開格式，可寫）
WRITABLE_RAW_EXTS = (".dng",)
# 只能讀、評分寫 sidecar 的 RAW
SIDECAR_RAW_EXTS = (".x3f", ".cr2", ".cr3", ".arw", ".nef", ".nrw", ".orf",
                    ".raf", ".rw2", ".pef", ".srw")
RAW_EXTS = SIDECAR_RAW_EXTS + WRITABLE_RAW_EXTS
ALL_PHOTO_EXTS = JPEG_EXTS + HEIC_EXTS + RAW_EXTS

# 整理時同一組檔案的優先順序：RAW 當主檔（日期、評分都以它為準）
_PRIMARY_ORDER = RAW_EXTS + HEIC_EXTS + JPEG_EXTS

EXIFTOOL_CANDIDATES = ("/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool")


def find_exiftool():
    """回傳 exiftool 的路徑；找不到回傳 None（Shortcuts／launchd 的 PATH
    很短，不能只靠 PATH）。"""
    found = shutil.which("exiftool")
    if found:
        return found
    for cand in EXIFTOOL_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


def ext_of(path):
    return os.path.splitext(path)[1].lower()


def is_photo(path):
    return ext_of(path) in ALL_PHOTO_EXTS


def is_raw(path):
    return ext_of(path) in RAW_EXTS


def uses_sidecar(path):
    """這個格式的評分/標籤要寫在旁邊的 .xmp，而不是檔案本身。"""
    return ext_of(path) in SIDECAR_RAW_EXTS


def sidecar_path(path):
    return os.path.splitext(path)[0] + ".xmp"


def primary_rank(path):
    ext = ext_of(path)
    return _PRIMARY_ORDER.index(ext) if ext in _PRIMARY_ORDER else len(_PRIMARY_ORDER)


def _run_exiftool(args, timeout=30):
    exiftool = find_exiftool()
    if exiftool is None:
        raise RuntimeError("找不到 exiftool，請先執行：brew install exiftool")
    return subprocess.run([exiftool] + args, capture_output=True, timeout=timeout)


def read_capture_date(path):
    """讀取拍攝日期，回傳 `(datetime, source)`；`source` 是 `"exif"` 或
    `"file"`（沒有 EXIF 時退回檔案建立時間，供呼叫端在預覽裡標示）。"""
    try:
        proc = _run_exiftool(
            ["-j", "-d", "%Y-%m-%d %H:%M:%S",
             "-DateTimeOriginal", "-CreateDate", path])
        if proc.returncode == 0:
            data = json.loads(proc.stdout.decode("utf-8", "replace"))[0]
            for key in ("DateTimeOriginal", "CreateDate"):
                value = data.get(key)
                if value and not str(value).startswith("0000"):
                    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S"), "exif"
    except (subprocess.SubprocessError, OSError, ValueError, IndexError, RuntimeError):
        pass
    stat = os.stat(path)
    ts = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(ts), "file"


def read_basic_exif_exiftool(path):
    """用 exiftool 讀相機/鏡頭/ISO/快門/光圈/拍攝日期（sips 讀不了 RAW 時
    的備援）。欄位缺或失敗回傳 None，不拋例外。"""
    result = {"camera_model": None, "lens": None, "iso": None,
              "shutter_speed": None, "aperture": None, "photo_date": None}
    try:
        proc = _run_exiftool(
            ["-j", "-n", "-Model", "-LensModel", "-LensID", "-ISO",
             "-ExposureTime", "-FNumber", "-d", "%Y:%m:%d %H:%M:%S",
             "-DateTimeOriginal", path], timeout=15)
        if proc.returncode != 0:
            return result
        data = json.loads(proc.stdout.decode("utf-8", "replace"))[0]
    except (subprocess.SubprocessError, OSError, ValueError, IndexError, RuntimeError):
        return result
    result["camera_model"] = data.get("Model")
    lens = data.get("LensModel") or data.get("LensID")
    result["lens"] = str(lens).strip() or None if lens else None
    iso = data.get("ISO")
    if isinstance(iso, (int, float)):
        result["iso"] = iso
    if data.get("FNumber") is not None:
        result["aperture"] = "f/%s" % data["FNumber"]
    exposure = data.get("ExposureTime")
    if exposure:
        result["shutter_speed"] = ("1/%d" % round(1 / exposure)
                                   if isinstance(exposure, (int, float)) and 0 < exposure < 1
                                   else str(exposure))
    result["photo_date"] = data.get("DateTimeOriginal")
    return result


def _image_size(path):
    """用 sips 讀長邊像素；失敗回傳 None。"""
    proc = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
        capture_output=True, timeout=30)
    if proc.returncode != 0:
        return None
    dims = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            dims[k.strip()] = v.strip()
    try:
        return max(int(dims["pixelWidth"]), int(dims["pixelHeight"]))
    except (KeyError, ValueError):
        return None


def extract_embedded_jpeg(src, dest):
    """從 RAW 抽出內嵌的最大 JPEG 寫到 `dest`。依序嘗試 JpgFromRaw、
    PreviewImage、OtherImage；都沒有就拋 RuntimeError。"""
    for tag in ("JpgFromRaw", "PreviewImage", "OtherImage"):
        proc = _run_exiftool(["-b", "-" + tag, src], timeout=60)
        if proc.returncode == 0 and proc.stdout[:2] == b"\xff\xd8":
            with open(dest, "wb") as f:
                f.write(proc.stdout)
            return tag
    raise RuntimeError("RAW 內找不到可用的內嵌預覽圖：%s" % src)


def make_jpeg(src, dest, max_dim):
    """產生長邊不超過 `max_dim` 的 JPEG（縮圖或預覽圖）。來源比 `max_dim`
    小時不放大，直接輸出原尺寸（避免把小圖拉糊）。失敗拋 RuntimeError。"""
    tmp_dir = None
    source = src
    try:
        if is_raw(src):
            tmp_dir = tempfile.mkdtemp(prefix="photo-embed-")
            source = os.path.join(tmp_dir, "embedded.jpg")
            extract_embedded_jpeg(src, source)
        size = _image_size(source)
        if size is not None and size <= max_dim:
            args = ["sips", "-s", "format", "jpeg", source, "--out", dest]
        else:
            args = ["sips", "-Z", str(max_dim), "-s", "format", "jpeg",
                    source, "--out", dest]
        proc = subprocess.run(args, capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(
                "sips 縮圖失敗：%s" % proc.stderr.decode("utf-8", "replace"))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def full_size_jpeg(src, dest):
    """單張檢視 100% 放大用：JPG 直接回傳原檔路徑（不複製）；HEIC 轉成全
    尺寸 JPEG；RAW 抽內嵌 JPEG。回傳實際可供瀏覽器顯示的檔案路徑。"""
    if ext_of(src) in JPEG_EXTS:
        return src
    if is_raw(src):
        extract_embedded_jpeg(src, dest)
        return dest
    proc = subprocess.run(
        ["sips", "-s", "format", "jpeg", src, "--out", dest],
        capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("sips 轉檔失敗：%s" % proc.stderr.decode("utf-8", "replace"))
    return dest


USER_TAGS_ATTR = "com.apple.metadata:_kMDItemUserTags"


def read_finder_tags(path):
    """讀取檔案上的 Finder 標籤（xattr）原始清單（每個元素是「名稱\n顏色」）。"""
    try:
        r = subprocess.run(["xattr", "-px", USER_TAGS_ATTR, path],
                           capture_output=True, text=True)
    except (subprocess.SubprocessError, OSError):
        return []
    if r.returncode != 0:
        return []
    try:
        return plistlib.loads(bytes.fromhex(r.stdout.replace("\n", "").replace(" ", "")))
    except Exception:  # noqa: BLE001
        return []


def write_finder_tags(path, tags):
    try:
        if tags:
            subprocess.run(["xattr", "-wx", USER_TAGS_ATTR,
                            plistlib.dumps(tags, fmt=plistlib.FMT_BINARY).hex(), path],
                           capture_output=True)
        else:
            subprocess.run(["xattr", "-d", USER_TAGS_ATTR, path], capture_output=True)
    except (subprocess.SubprocessError, OSError):
        pass


def group_key(path):
    """同目錄、同主檔名（不分大小寫）視為同一組（SDIM0071.X3F／.jpg／.xmp）。"""
    return (os.path.dirname(path),
            os.path.splitext(os.path.basename(path))[0].lower())


def expand_group(paths):
    """把選取的檔案展開成「同組的所有照片檔」（不含 .xmp sidecar）。
    非檔案、非照片的項目忽略；回傳去重後的絕對路徑清單。"""
    targets, seen = [], set()
    for p in paths:
        p = os.path.abspath(p)
        if not os.path.isfile(p) or not is_photo(p):
            continue
        d, stem = group_key(p)
        members = [p]
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if (full != p and is_photo(full)
                    and os.path.splitext(name)[0].lower() == stem):
                members.append(full)
        for m in members:
            if m not in seen:
                seen.add(m)
                targets.append(m)
    return targets
