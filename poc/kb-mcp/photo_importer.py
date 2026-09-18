"""相簿分頁匯入流程：掃描來源資料夾、去重預覽、複製檔案、產生縮圖與
讀取基礎 EXIF。

**這裡是 `file_hash` 凍結計算的唯一時機點**（見 `photo_store.py`
docstring、`specs/004-photos-albums-search/research.md` §4）：
`scan_folder()` 對「來源資料夾裡的原始檔案」計算 MD5，之後
`commit_import()` 把檔案複製到目的地——複製是逐位元組複製，此時來源與
目的地內容相同，所以在複製之前對來源算的 hash 跟複製後對目的地算的
hash 理論上一致，但我們**只在這裡算一次、之後永遠不再重算**，即使
日後標籤/評分中繼資料寫回會改變目的地檔案的位元組。

MVP 範圍僅處理 JPG（`.jpg`／`.jpeg`，不分大小寫）；不遞迴子資料夾
（spec.md 沒有要求遞迴匯入，維持簡單）。

縮圖與基礎 EXIF 讀取用 macOS 內建 `sips` 命令列工具（`research.md`
§1，不新增 Pillow 依賴）。**已知風險**（`quickstart.md`「已知的技術
待辦」）：`sips -g allxml` 回傳的 plist 裡，EXIF/TIFF 巢狀字典的確切
鍵名（`Model`／`LensModel`／`ISOSpeedRatings` 等）只在本機一張沒有
相機 EXIF 的既有樣本檔案上驗證過「沒有 EXIF 時能正確回傳 None」這條
路徑；「真的有相機 EXIF 時欄位名稱是否精確對應」尚未拿真實相機 JPG
驗證過，讀取失敗或欄位對不上時本函式一律回傳 `None`，不會拋例外中斷
匯入。
"""
import hashlib
import os
import plistlib
import shutil
import subprocess

VALID_EXTENSIONS = (".jpg", ".jpeg")


def _compute_md5(path):
    """對單一檔案計算 MD5（去重比對鍵）。分塊讀取，避免大檔案一次性
    載入記憶體。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_basic_exif(path):
    """讀取相機型號／鏡頭／ISO／快門／光圈／拍攝日期，來源不明或欄位
    不存在時對應欄位回傳 `None`，不拋例外（見本檔案開頭 docstring 的
    已知風險）。"""
    result = {
        "camera_model": None, "lens": None, "iso": None,
        "shutter_speed": None, "aperture": None, "photo_date": None,
    }
    try:
        proc = subprocess.run(
            ["sips", "-g", "allxml", path],
            capture_output=True, timeout=15)
        if proc.returncode != 0:
            return result
        data = plistlib.loads(proc.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return result

    tiff = data.get("{TIFF}") or {}
    exif = data.get("{Exif}") or {}

    result["camera_model"] = tiff.get("Model") or exif.get("Model")
    result["lens"] = exif.get("LensModel") or exif.get("Lens")
    iso = exif.get("ISOSpeedRatings")
    if isinstance(iso, (list, tuple)) and iso:
        result["iso"] = iso[0]
    elif isinstance(iso, (int, float)):
        result["iso"] = iso
    aperture = exif.get("FNumber") or exif.get("ApertureValue")
    if aperture is not None:
        result["aperture"] = "f/%s" % aperture
    shutter = exif.get("ExposureTime") or exif.get("ShutterSpeedValue")
    if shutter is not None:
        result["shutter_speed"] = str(shutter)
    result["photo_date"] = exif.get("DateTimeOriginal") or tiff.get("DateTime")
    return result


def _make_thumbnail(src_path, dest_path, max_dim=256):
    """用 `sips -Z` 產生等比例縮圖（長邊縮到 `max_dim`）。失敗時拋例外，
    由呼叫端（`commit_import`）捕捉並記入該張照片的失敗原因。"""
    proc = subprocess.run(
        ["sips", "-Z", str(max_dim), src_path, "--out", dest_path],
        capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            "sips 縮圖失敗：%s" % proc.stderr.decode("utf-8", "replace"))


def scan_folder(source_path, photo_store):
    """掃描來源資料夾，計算去重預覽。**不複製任何檔案**——這是
    `file_hash` 凍結計算的唯一時機點，之後 `commit_import()` 只會使用
    這裡算好的 hash，不會重新計算。

    回傳：
        {"total": int, "new_files": [{"filename", "path", "file_hash",
          "file_size"}], "duplicate_count": int, "unreadable": [filename,...]}
    """
    if not os.path.isdir(source_path):
        raise ValueError("source_path 不是有效的資料夾：%s" % source_path)

    new_files = []
    duplicate_count = 0
    unreadable = []
    # 同一批掃描內容相同的檔案也要視為重複（例如使用者資料夾裡本來就有
    # 兩份一樣的檔案）——只查 photo_store.find_by_hash() 只能擋「跟資料庫
    # 裡既有照片重複」，擋不了「這一批裡面自己互相重複」，後者若不擋，
    # commit_import() 對第二份會因 UNIQUE 約束衝突而落入 failed，語意上
    # 該算「重複跳過」而不是「匯入失敗」。
    seen_hashes_this_batch = set()

    for filename in sorted(os.listdir(source_path)):
        full_path = os.path.join(source_path, filename)
        if not os.path.isfile(full_path):
            continue
        if not filename.lower().endswith(VALID_EXTENSIONS):
            continue
        try:
            file_hash = _compute_md5(full_path)
            file_size = os.path.getsize(full_path)
        except OSError:
            unreadable.append(filename)
            continue

        if (photo_store.find_by_hash(file_hash) is not None
                or file_hash in seen_hashes_this_batch):
            duplicate_count += 1
            continue
        seen_hashes_this_batch.add(file_hash)

        new_files.append({
            "filename": filename, "path": full_path,
            "file_hash": file_hash, "file_size": file_size,
        })

    total = len(new_files) + duplicate_count + len(unreadable)
    return {
        "total": total, "new_files": new_files,
        "duplicate_count": duplicate_count, "unreadable": unreadable,
    }


def commit_import(new_files, storage_location, dest_dir, thumbnail_dir,
                   photo_store):
    """把 `scan_folder()` 找出的新照片複製進 `dest_dir`、產生縮圖、讀取
    基礎 EXIF、寫入 `photo_store`。單一檔案失敗（複製/縮圖/寫入任一步
    出錯）**跳過該檔案、不中斷其餘匯入**（spec.md Edge Cases）。

    儲存檔名固定為 `<file_hash><副檔名>`——hash 在 `scan_folder()` 已經
    保證唯一，用它命名同時避免檔名衝突、讓 `storage_path` 可追溯回
    對應的 `file_hash`。

    回傳：`{"imported_count": int, "imported_photo_ids": [int,...],
      "failed": [{"filename", "reason"}]}`——`imported_photo_ids` 供
    呼叫端（`app/routers/photos.py` 的匯入 job 狀態）知道這批剛匯入的
    照片是哪幾筆，不用另外查詢。
    """
    os.makedirs(dest_dir, exist_ok=True)
    os.makedirs(thumbnail_dir, exist_ok=True)

    imported_count = 0
    imported_photo_ids = []
    failed = []

    for entry in new_files:
        filename = entry["filename"]
        file_hash = entry["file_hash"]
        ext = os.path.splitext(filename)[1].lower()
        dest_path = os.path.join(dest_dir, file_hash + ext)
        thumb_path = os.path.join(thumbnail_dir, file_hash + ".jpg")
        try:
            shutil.copy2(entry["path"], dest_path)
            _make_thumbnail(dest_path, thumb_path)
            exif = _read_basic_exif(dest_path)
            photo = photo_store.add_photo(
                file_hash=file_hash,
                storage_path=dest_path,
                storage_location=storage_location,
                thumbnail_path=thumb_path,
                camera_model=exif["camera_model"],
                lens=exif["lens"],
                iso=exif["iso"],
                shutter_speed=exif["shutter_speed"],
                aperture=exif["aperture"],
                photo_date=exif["photo_date"],
                file_size=entry["file_size"],
            )
            imported_count += 1
            imported_photo_ids.append(photo["id"])
        except Exception as exc:  # noqa: BLE001 — 單張失敗不可中斷整批匯入
            failed.append({"filename": filename, "reason": str(exc)})
            continue

    return {"imported_count": imported_count,
            "imported_photo_ids": imported_photo_ids, "failed": failed}
