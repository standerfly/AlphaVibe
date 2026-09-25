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


def external_volume_mounted(path):
    """確認 `path` 底下的 `/Volumes/<name>` 那一層，真的是掛載中的磁碟，
    不是開機硬碟上剛好也有一個同名的普通資料夾。

    **背景**（2026-09-25 使用者要設定固定的外接硬碟預設路徑時，程式碼
    審查發現的風險）：外接儲存的 `commit_import()` 用 `os.makedirs()`
    確保目的地資料夾存在——如果外接硬碟沒接、`dest_dir` 指向的
    `/Volumes/<name>/...` 路徑不存在，`os.makedirs()` 不會報錯，而是
    直接在**開機硬碟**的 `/Volumes/` 底下建立一個同名的普通資料夾，
    照片就這樣悄悄被寫進內接硬碟，卻沒有任何錯誤或警告——使用者會
    誤以為存到外接硬碟了。這個函式在真正寫入前擋下這種情況。

    只認 `/Volumes/<name>` 這一層是否為掛載點（`os.path.ismount()`），
    不要求 `dest_dir` 本身（可能是硬碟下的子資料夾）已經存在——那一段
    交給 `os.makedirs()` 在確認硬碟有掛載之後照常建立。"""
    normalized = os.path.abspath(path)
    parts = normalized.split(os.sep)
    if len(parts) >= 3 and parts[1] == "Volumes":
        mount_point = os.sep.join(parts[:3])
        return os.path.ismount(mount_point)
    # 不在 /Volumes/ 底下的路徑（理論上外接硬碟都掛在這裡）——保守起見
    # 退回檢查路徑本身是否已經存在。
    return os.path.isdir(normalized)


def _iter_candidate_files(source_path, recursive):
    """列出 `source_path` 底下符合副檔名的檔案。`recursive=False`
    （預設，匯入複製模式沿用既有行為）只看最上層；`recursive=True`
    （原地索引模式常用，見 `commit_import()` 的 `reference` 分支）用
    `os.walk()` 遞迴整棵目錄樹——原地索引的典型情境是使用者指向一個
    像 `GOPRO/`／`RX100m3/` 這種依相機分類、底下還有年份/事件子資料夾
    的既有相片庫，不遞迴的話只會看到最外層、幾乎等於掃不到照片。"""
    if not recursive:
        for filename in sorted(os.listdir(source_path)):
            full_path = os.path.join(source_path, filename)
            if os.path.isfile(full_path):
                yield filename, full_path
        return

    for root, _dirs, files in os.walk(source_path):
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            # 遞迴模式下用「相對於 source_path 的路徑」當顯示用檔名，
            # 不然子資料夾裡一堆都叫 IMG_0001.jpg 時，掃描結果列表會
            # 分不出是哪一張（見 scan_folder() docstring 的
            # new_files[].filename 用途：也是 reference 模式下寫進
            # commit_import() 的顯示名稱，不影響實際路徑或 file_hash）。
            rel = os.path.relpath(full_path, source_path)
            yield rel, full_path


def scan_folder(source_path, photo_store, recursive=False):
    """掃描來源資料夾，計算去重預覽。**不複製任何檔案**——這是
    `file_hash` 凍結計算的唯一時機點，之後 `commit_import()` 只會使用
    這裡算好的 hash，不會重新計算。

    `recursive`：是否連同子資料夾一起掃（見 `_iter_candidate_files()`
    docstring）。

    **移動偵測**（2026-09-25 新增，只對 `reference` 模式的既有紀錄有
    意義）：如果找到的檔案 hash 對上一筆既有紀錄，但那筆紀錄的
    `storage_path` 不是我們現在找到的這個路徑——代表使用者在 STND
    之外把這個原地索引的檔案搬到新資料夾了。這種情況不算「重複」，
    而是回報在 `moved_files`，交給 `heal_moved_paths()` 更新資料庫裡
    記錄的路徑（不需要重新複製、不需要重新產生縮圖、不需要重新同步
    中繼資料——檔案內容沒變，hash 相同，先前寫進檔案本身的標籤也還在）。
    只有 `storage_location == "reference"` 的既有紀錄才會觸發這個判斷；
    `internal`／`external` 複製模式的既有紀錄，`storage_path` 是 STND
    自己管理的副本路徑，重新掃到來源資料夾裡的同一份原始檔本來就該
    算普通重複，不是「移動」。

    **已知限制**（與本檔案開頭「`file_hash` 凍結計算」原則直接相關，
    不是 bug）：這個判斷完全靠 hash 比對，如果使用者在搬移前已經透過
    STND 幫這張照片打過標籤（`write_metadata()` 會實際改寫原始檔案的
    位元組），搬移後重新算出來的 hash 會跟資料庫凍結的舊 hash 不同，
    這裡就偵測不到「是同一張搬家了」，重新掃描新位置會把它當成
    `new_files` 裡的新照片。標籤本身仍然完整保留在檔案的 XMP/IPTC
    裡（不會遺失，換一台裝置用 Lightroom 之類工具開一樣讀得到），只是
    STND 資料庫端會多一筆指向舊路徑、狀態顯示「原檔離線」的孤兒紀錄，
    需要使用者自行從相簿頁刪除。要完全避免：搬移資料夾整理**在**
    幫照片打標籤**之前**做。
        {"total": int, "new_files": [...], "moved_files": [{"photo_id",
          "old_path", "new_path", "filename"}], "duplicate_count": int,
          "unreadable": [filename,...]}
    """
    if not os.path.isdir(source_path):
        raise ValueError("source_path 不是有效的資料夾：%s" % source_path)

    new_files = []
    moved_files = []
    duplicate_count = 0
    unreadable = []
    # 同一批掃描內容相同的檔案也要視為重複（例如使用者資料夾裡本來就有
    # 兩份一樣的檔案）——只查 photo_store.find_by_hash() 只能擋「跟資料庫
    # 裡既有照片重複」，擋不了「這一批裡面自己互相重複」，後者若不擋，
    # commit_import() 對第二份會因 UNIQUE 約束衝突而落入 failed，語意上
    # 該算「重複跳過」而不是「匯入失敗」。
    seen_hashes_this_batch = set()

    for filename, full_path in _iter_candidate_files(source_path, recursive):
        if not filename.lower().endswith(VALID_EXTENSIONS):
            continue
        try:
            file_hash = _compute_md5(full_path)
            file_size = os.path.getsize(full_path)
        except OSError:
            unreadable.append(filename)
            continue

        existing = photo_store.find_by_hash(file_hash)
        if existing is not None or file_hash in seen_hashes_this_batch:
            if (existing is not None
                    and existing["storage_location"] == "reference"
                    and existing["storage_path"] != full_path):
                moved_files.append({
                    "photo_id": existing["id"], "filename": filename,
                    "old_path": existing["storage_path"], "new_path": full_path,
                })
            else:
                duplicate_count += 1
            continue
        seen_hashes_this_batch.add(file_hash)

        new_files.append({
            "filename": filename, "path": full_path,
            "file_hash": file_hash, "file_size": file_size,
        })

    total = len(new_files) + len(moved_files) + duplicate_count + len(unreadable)
    return {
        "total": total, "new_files": new_files, "moved_files": moved_files,
        "duplicate_count": duplicate_count, "unreadable": unreadable,
    }


def heal_moved_paths(moved_files, photo_store):
    """把 `scan_folder()` 偵測到的 `moved_files` 實際套用到資料庫——
    只更新 `storage_path`，不碰其他任何欄位（`file_hash`／
    `metadata_sync_status`／縮圖都不需要變，見 `PhotoStore.
    update_storage_path()` docstring）。回傳實際更新成功的筆數。"""
    healed = 0
    for moved in moved_files:
        if photo_store.update_storage_path(moved["photo_id"], moved["new_path"]):
            healed += 1
    return healed


def commit_import(new_files, storage_location, dest_dir, thumbnail_dir,
                   photo_store):
    """把 `scan_folder()` 找出的新照片寫入 `photo_store`，`storage_location`
    決定檔案本身怎麼處理：

    - `internal`／`external`：複製進 `dest_dir`（跟舊行為一致）
    - `reference`（2026-09-25 新增）：**不複製**，`storage_path` 直接是
      `entry["path"]`（使用者原本的檔案位置）——`dest_dir` 參數這個
      模式下不使用（呼叫端可傳任意值，例如 `None`）

    縮圖／EXIF 一律從「照片實際所在位置」讀取——複製模式讀剛複製好的
    `dest_path`，reference 模式直接讀原始檔案，兩者呼叫的是同一段邏輯，
    差別只在 `dest_path` 這個變數怎麼算出來。

    單一檔案失敗（複製/縮圖/寫入任一步出錯）**跳過該檔案、不中斷其餘
    匯入**（spec.md Edge Cases）。

    複製模式的儲存檔名固定為 `<file_hash><副檔名>`——hash 在
    `scan_folder()` 已經保證唯一，用它命名同時避免檔名衝突、讓
    `storage_path` 可追溯回對應的 `file_hash`（reference 模式沒有這個
    問題，本來就是各自獨立的原始檔案，不需要改名）。

    回傳：`{"imported_count": int, "imported_photo_ids": [int,...],
      "failed": [{"filename", "reason"}]}`——`imported_photo_ids` 供
    呼叫端（`app/routers/photos.py` 的匯入 job 狀態）知道這批剛匯入的
    照片是哪幾筆，不用另外查詢。

    Raises:
        RuntimeError: `storage_location == "external"` 但 `dest_dir`
            指向的硬碟目前沒有掛載（見 `external_volume_mounted()`
            docstring）——整批匯入直接中止，不寫入任何檔案，避免
            `os.makedirs()` 悄悄在開機硬碟建立同名資料夾。
    """
    if storage_location == "external" and not external_volume_mounted(dest_dir):
        raise RuntimeError(
            "外接硬碟未連接或路徑不存在：%s，請確認硬碟已連接後再試一次"
            % dest_dir)
    os.makedirs(thumbnail_dir, exist_ok=True)
    if storage_location != "reference":
        os.makedirs(dest_dir, exist_ok=True)

    imported_count = 0
    imported_photo_ids = []
    failed = []

    for entry in new_files:
        filename = entry["filename"]
        file_hash = entry["file_hash"]
        thumb_path = os.path.join(thumbnail_dir, file_hash + ".jpg")
        try:
            if storage_location == "reference":
                dest_path = entry["path"]
            else:
                ext = os.path.splitext(filename)[1].lower()
                dest_path = os.path.join(dest_dir, file_hash + ext)
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
