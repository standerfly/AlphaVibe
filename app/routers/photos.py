"""相簿分頁：FastAPI router。

**Phase 3（User Story 1，`specs/004-photos-albums-search/tasks.md`
T018~T021）**：匯入（背景任務＋輪詢進度）、相簿 CRUD、照片整理
（評分/標籤/批次）、刪除。全域搜尋（User Story 2）與標籤/評分中繼
資料同步狀態轉換（User Story 3）留待對應 Story 階段再新增端點，這裡
刻意不預先實作（見 `photo_store.py` docstring 同一原則）。

**業務邏輯全部委派給 `PhotoStore`／`photo_importer`**（`poc/kb-mcp/
photo_store.py`／`photo_importer.py`）——跟既有 `us_stocks.py` 對
`USStockStore` 的既有慣例一致，這裡只做 HTTP 介面轉接，不重寫任何
演算法（去重、EXIF 讀取、縮圖產生皆在 `photo_importer.py`）。

**完全獨立於既有台股/美股 router**：不 import `app/deps.py`／
`app/us_stock_deps.py`，改用獨立的 `app/photo_deps.py`（見該檔案
docstring，對應 `plan.md` Constitution Check Gate G1）。

**匯入與中繼資料寫回的背景任務設計**（`research.md` §3）：匯入用
FastAPI `BackgroundTasks`，進度寫進這個模組內的記憶體字典
`_IMPORT_JOBS`（單一 process 內全域共用，跨 request 存活，滿足「使用者
重新整理頁面/關掉瀏覽器後回來仍查得到進度」——只有伺服器 process 真的
重啟才會遺失，這是 MVP 階段的合理簡化，比照 `research.md` §3 的
「不引入訊息佇列」原則）。背景任務**不使用** request-scoped 的
`Depends(get_photo_store)`——那個連線在 response 送出後可能已經被
`finally` 關閉，背景任務改用 `resolve_photo_data_dir_for_background()`
拿到資料目錄路徑，自行建立/關閉獨立的 `PhotoStore` 連線。

**掃描結果的暫存**（`_SCAN_CACHE`，同樣是記憶體字典）：`import/scan`
把掃描結果（含每個新照片的來源路徑與已計算好的 `file_hash`）存進去，
`import/commit` 用 `scan_token` 取出——**不會重新掃描、不會重新計算
hash**，這是 `research.md` §4 核心保證在 API 層的具體落實。

**人工確認清單**（2026-09-25 新增，`import/resolve-match`）：`reference`
模式的搬家偵測純靠 hash 比對，若照片搬家前已經被 STND 打過標籤，檔案
內容（因而 hash）已經變了，自動偵測會失效（見 `photo_importer.py
scan_folder()` docstring「已知限制」）。這裡用檔名比對列出候選
（`possible_matches`），交由使用者在前端人工確認——確認後才會真的
更新資料庫，避免純檔名比對的誤判風險（例如相機預設檔名撞名）被自動
套用。`resolve-match` 必須在對應 `scan_token` 被 `import/commit` 用掉
（`_SCAN_CACHE.pop`）之前呼叫，否則對不到快取。

**依子資料夾自動建立相簿**（2026-09-27 新增，`auto_album` 參數）：
使用者常見流程是先在別的電腦上把照片依事件/日期分好資料匣，才把整批
資料匣搬進 STND 索引——`recursive=True` 掃描時，每個第一層子資料夾
直接對應成一個相簿（`_group_by_top_level_folder()`），省去在 STND 裡
重新手動分類一次。只在 `auto_album=True` 時生效；沒有子資料夾可歸屬
的照片（直接在來源資料夾底下）留給既有的手動「加入相簿」流程處理。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.photo_deps import (PhotoStore, get_photo_store,
                             resolve_photo_data_dir_for_background)

_PHOTO_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_PHOTO_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_PHOTO_KB_MCP_DIR))

from photo_formats import full_size_jpeg, make_jpeg  # noqa: E402
from photo_importer import (  # noqa: E402
    scan_folder, commit_import, external_volume_mounted, heal_moved_paths,
    resolve_possible_match, heal_in_place_hashes)
from photo_metadata_sync import (  # noqa: E402
    MetadataSyncUnavailable, write_metadata)

router = APIRouter()

VALID_STORAGE_LOCATIONS = ("internal", "external", "reference")

# 記憶體狀態（見本檔案開頭 docstring「匯入與中繼資料寫回的背景任務設計」／
# 「掃描結果的暫存」）。單一 process 內全域共用，故意不落地成資料表
# ——MVP 階段的合理簡化，見 research.md §3。
_SCAN_CACHE: Dict[str, Dict[str, Any]] = {}
_IMPORT_JOBS: Dict[str, Dict[str, Any]] = {}


def _internal_dest_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "photos", "originals", "internal")


def _thumbnail_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "photos", "thumbnails")


def _preview_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "photos", "previews")


@router.get("/api/photos/browse-folders")
def browse_folders(
    path: Optional[str] = Query(None, description="省略＝從使用者家目錄開始"),
) -> Dict[str, Any]:
    """伺服器端唯讀資料夾瀏覽（`research.md` §5），供匯入畫面選路徑。
    只回傳子資料夾清單，不回傳檔案內容，不做任何寫入。"""
    base = os.path.abspath(path) if path else os.path.expanduser("~")
    if not os.path.isdir(base):
        raise HTTPException(status_code=400, detail="path 不是有效的資料夾：%s" % base)
    try:
        entries = sorted(os.listdir(base))
    except OSError as exc:
        raise HTTPException(status_code=400, detail="無法讀取資料夾：%s" % exc)
    folders = [
        {"name": name, "path": os.path.join(base, name)}
        for name in entries
        if not name.startswith(".") and os.path.isdir(os.path.join(base, name))
    ]
    return {"path": base, "folders": folders}


class ImportScanRequest(BaseModel):
    source_path: str
    storage_location: str
    dest_path: Optional[str] = None  # storage_location="external" 時必填
    recursive: bool = False  # 連同子資料夾一起掃，見 photo_importer.py
    auto_album: bool = False  # 依子資料夾自動建立相簿，2026-09-27 新增


def _preview_folder_groups(
        new_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`import/scan` 回應用的預覽版本，跟 `_group_by_top_level_folder()`
    同一套規則，但作用在還沒 commit 的 `new_files`（只有 `filename`，
    沒有照片 `id`）——只算數量，供使用者在確認匯入前先看到「將會建立/
    加入哪些相簿、各幾張」。"""
    groups: Dict[str, int] = {}
    unassigned = 0
    for entry in new_files:
        parts = entry["filename"].replace(os.sep, "/").split("/")
        if len(parts) > 1 and parts[0]:
            groups[parts[0]] = groups.get(parts[0], 0) + 1
        else:
            unassigned += 1
    return {
        "albums": [{"title": t, "count": c} for t, c in groups.items()],
        "unassigned_count": unassigned,
    }


@router.post("/api/photos/import/scan")
def import_scan(
    body: ImportScanRequest,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """掃描來源資料夾、計算去重預覽（`research.md` §4：`file_hash` 在
    這裡對來源檔案計算，之後永久不重算）。`storage_location="reference"`
    時**不需要** `dest_path`——原地索引，不複製檔案（見
    `photo_importer.py` `VALID_STORAGE_LOCATIONS` 說明）。"""
    if body.storage_location not in VALID_STORAGE_LOCATIONS:
        raise HTTPException(
            status_code=400,
            detail="storage_location 必須是 %s" % (VALID_STORAGE_LOCATIONS,))
    if body.storage_location == "external" and not body.dest_path:
        raise HTTPException(
            status_code=400,
            detail="storage_location=external 時必須提供 dest_path")
    if body.storage_location == "external" and not external_volume_mounted(body.dest_path):
        raise HTTPException(
            status_code=400,
            detail="外接硬碟未連接或路徑不存在：%s，請確認硬碟已連接後再試一次"
            % body.dest_path)
    try:
        scan_result = scan_folder(body.source_path, store, recursive=body.recursive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if body.storage_location == "external":
        dest_dir = body.dest_path
    elif body.storage_location == "reference":
        dest_dir = None  # 不使用，原地索引不複製檔案
    else:
        dest_dir = _internal_dest_dir(store.data_dir)
    scan_token = uuid.uuid4().hex
    _SCAN_CACHE[scan_token] = {
        "new_files": scan_result["new_files"],
        "moved_files": scan_result["moved_files"],
        "healed_in_place": scan_result["healed_in_place"],
        "possible_matches": scan_result["possible_matches"],
        "storage_location": body.storage_location,
        "dest_dir": dest_dir,
        "thumbnail_dir": _thumbnail_dir(store.data_dir),
        "data_dir": store.data_dir,
        "auto_album": body.auto_album,
    }
    folder_preview = (
        _preview_folder_groups(scan_result["new_files"]) if body.auto_album else None)
    return {
        "scan_token": scan_token,
        "total": scan_result["total"],
        "new_count": len(scan_result["new_files"]),
        "moved_count": len(scan_result["moved_files"]),
        "healed_in_place_count": len(scan_result["healed_in_place"]),
        "possible_matches": scan_result["possible_matches"],
        "duplicate_count": scan_result["duplicate_count"],
        "unreadable": scan_result["unreadable"],
        "folder_albums_preview": folder_preview,
    }


class ResolveMatchRequest(BaseModel):
    scan_token: str
    photo_id: int
    new_path: str


@router.post("/api/photos/import/resolve-match")
def import_resolve_match(
    body: ResolveMatchRequest,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """人工確認清單：使用者確認某個 `possible_matches` 候選「就是同一張
    搬家前已經打過標籤的照片」，立即更新該筆紀錄的 storage_path／
    file_hash（見 `PhotoStore.resolve_possible_match()` docstring），
    並把這個候選從快取的 `new_files`／`possible_matches` 移除，避免
    使用者接著按「確認匯入」時把同一份檔案又當成全新照片匯入一次。
    必須在對應的 `scan_token` 還沒被 `import/commit` 用掉前呼叫。"""
    cached = _SCAN_CACHE.get(body.scan_token)
    if cached is None:
        raise HTTPException(status_code=404, detail="scan_token 不存在或已使用過")

    match = next(
        (m for m in cached["possible_matches"]
         if m["photo_id"] == body.photo_id and m["new_path"] == body.new_path),
        None)
    if match is None:
        raise HTTPException(status_code=404, detail="找不到對應的候選項目")

    resolved = resolve_possible_match(match, store)
    if resolved is None:
        raise HTTPException(status_code=404, detail="照片紀錄不存在")

    cached["new_files"] = [
        f for f in cached["new_files"] if f["path"] != body.new_path]
    cached["possible_matches"] = [
        m for m in cached["possible_matches"]
        if not (m["photo_id"] == body.photo_id and m["new_path"] == body.new_path)]

    return {
        "resolved": True, "photo_id": resolved["id"],
        "storage_path": resolved["storage_path"],
        "new_count": len(cached["new_files"]),
        "possible_matches": cached["possible_matches"],
    }


def _group_by_top_level_folder(
        imported: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """依 `commit_import()` 回傳的 `imported`（`[{"id","filename"}]`）
    分組——遞迴掃描（`recursive=True`）時 `filename` 是相對路徑（例如
    `"2026-09-台北旅遊/day1/IMG001.jpg"`），第一段路徑就是使用者已經在
    來源端分好的資料匣名稱，直接拿來當相簿標題用（見「依子資料夾自動
    建立相簿」，2026-09-27 新增）。檔案直接在來源資料夾底下（`filename`
    不含路徑分隔符，沒有子資料夾）的照片歸進 `"_unassigned"` 這個保留
    key，代表「沒有子資料夾可以推斷相簿」，不會被當成相簿名稱。"""
    groups: Dict[str, List[int]] = {}
    for entry in imported:
        parts = entry["filename"].replace(os.sep, "/").split("/")
        key = parts[0] if len(parts) > 1 and parts[0] else "_unassigned"
        groups.setdefault(key, []).append(entry["id"])
    return groups


def _run_import_job(job_id: str, data_dir: str, new_files: List[Dict[str, Any]],
                     moved_files: List[Dict[str, Any]],
                     healed_in_place: List[Dict[str, Any]], storage_location: str,
                     dest_dir: str, thumbnail_dir: str, auto_album: bool) -> None:
    """背景任務本體。**不使用** request-scoped 的 `PhotoStore`——自行
    開一條獨立連線（見本檔案開頭 docstring）。`moved_files` 是
    `reference` 模式偵測到「檔案搬家了」的既有照片，跟 `new_files`
    一起處理：`heal_moved_paths()` 只更新路徑，不需要複製/縮圖/重新
    同步（見該函式 docstring）。`healed_in_place`（2026-09-30 新增）是
    路徑沒變、但內容原地被改過（通常是打了標籤）的既有照片，
    `heal_in_place_hashes()` 只更新 `file_hash`，理由同上。

    `auto_album`（2026-09-27 新增）：開啟時，把 `commit_import()` 回傳
    的 `imported` 依 `_group_by_top_level_folder()` 分組，每組用
    `PhotoStore.get_or_create_album()` 對應成一個相簿並加入——同一個
    資料匣名稱分批匯入多次會持續加進同一個相簿，不會分裂。沒有子
    資料夾可歸屬的照片（`_unassigned` 分組）留給前端用既有的手動
    「加入相簿」流程處理，不會被自動歸進任何相簿。"""
    store = PhotoStore(data_dir)
    try:
        result = commit_import(
            new_files, storage_location, dest_dir, thumbnail_dir, store)
        healed_count = heal_moved_paths(moved_files, store)
        healed_in_place_count = heal_in_place_hashes(healed_in_place, store)

        auto_albums: List[Dict[str, Any]] = []
        unassigned_photo_ids: List[int] = list(result["imported_photo_ids"])
        if auto_album and result["imported"]:
            groups = _group_by_top_level_folder(result["imported"])
            unassigned_photo_ids = groups.pop("_unassigned", [])
            for title, photo_ids in groups.items():
                album = store.get_or_create_album(title)
                for photo_id in photo_ids:
                    store.add_photo_to_album(photo_id, album["id"])
                auto_albums.append({
                    "album_id": album["id"], "title": album["title"],
                    "count": len(photo_ids),
                })

        _IMPORT_JOBS[job_id].update({
            "status": "completed",
            "imported_count": result["imported_count"],
            "imported_photo_ids": result["imported_photo_ids"],
            "healed_count": healed_count,
            "healed_in_place_count": healed_in_place_count,
            "failed": result["failed"],
            "auto_albums": auto_albums,
            "unassigned_photo_ids": unassigned_photo_ids,
        })
    except Exception as exc:  # noqa: BLE001 — 背景任務失敗要記錄，不能讓例外無聲消失
        _IMPORT_JOBS[job_id].update({"status": "failed", "error": str(exc)})
    finally:
        store.close()


def _run_metadata_sync(photo_id: int, data_dir: str) -> None:
    """背景任務本體：把一張照片目前的標籤/評分寫回檔案本身的 XMP/IPTC
    中繼資料（User Story 3）。**不使用** request-scoped 的
    `PhotoStore`——自行開一條獨立連線，理由同 `_run_import_job()`。

    區分兩種失敗：`MetadataSyncUnavailable`（原始檔暫時無法存取，例如
    外接硬碟未掛載）標記為 `pending`（維持待處理，不是失敗，之後補寫
    即可）；其餘例外（exiftool 真的執行失敗）標記為 `failed` 並記錄
    原因。"""
    store = PhotoStore(data_dir)
    try:
        photo = store.get_photo(photo_id)
        if photo is None:
            return
        tags = [t["name"] for t in store.get_photo_tags(photo_id)]
        try:
            write_metadata(photo["storage_path"], tags, photo["rating"])
        except MetadataSyncUnavailable:
            store.update_metadata_sync_status(photo_id, "pending")
        except Exception as exc:  # noqa: BLE001 — 背景任務失敗要記錄，不能無聲消失
            store.update_metadata_sync_status(photo_id, "failed", error=str(exc))
        else:
            store.update_metadata_sync_status(photo_id, "synced")
    finally:
        store.close()


class ImportCommitRequest(BaseModel):
    scan_token: str


@router.post("/api/photos/import/commit")
def import_commit(
    body: ImportCommitRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """確認匯入，啟動背景任務。用掉 `scan_token`（一次性——避免同一次
    掃描結果被重複提交造成兩次匯入）。"""
    cached = _SCAN_CACHE.pop(body.scan_token, None)
    if cached is None:
        raise HTTPException(status_code=404, detail="scan_token 不存在或已使用過")

    job_id = uuid.uuid4().hex
    total = len(cached["new_files"])
    _IMPORT_JOBS[job_id] = {
        "job_id": job_id, "status": "running",
        "imported_count": 0, "total": total, "healed_count": 0,
        "healed_in_place_count": 0, "failed": [],
        "auto_albums": [], "unassigned_photo_ids": [],
    }
    background_tasks.add_task(
        _run_import_job, job_id, cached["data_dir"], cached["new_files"],
        cached["moved_files"], cached["healed_in_place"], cached["storage_location"],
        cached["dest_dir"], cached["thumbnail_dir"], cached["auto_album"])
    return {"job_id": job_id, "status": "running"}


@router.get("/api/photos/import/jobs/{job_id}")
def import_job_status(job_id: str) -> Dict[str, Any]:
    job = _IMPORT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id 不存在")
    return job


# ---------- 相簿 ----------

class AlbumCreate(BaseModel):
    title: str
    description: Optional[str] = None


class AlbumUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    cover_photo_id: Optional[int] = None


@router.get("/api/photos/albums")
def list_albums(store: PhotoStore = Depends(get_photo_store)) -> Dict[str, Any]:
    return {"albums": store.list_albums()}


@router.post("/api/photos/albums")
def create_album(
    body: AlbumCreate, store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    try:
        return store.create_album(body.title, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/photos/albums/{album_id}")
def update_album(
    album_id: int, body: AlbumUpdate,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    try:
        result = store.update_album(
            album_id, title=body.title, description=body.description,
            cover_photo_id=body.cover_photo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="album not found")
    return result


@router.delete("/api/photos/albums/{album_id}")
def delete_album(
    album_id: int, store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    deleted = store.delete_album(album_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="album not found")
    return {"deleted": deleted}


@router.get("/api/photos/albums/{album_id}/photos")
def get_album_photos(
    album_id: int,
    sort: str = Query("date"),
    tag: Optional[str] = Query(None),
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    if store.get_album(album_id) is None:
        raise HTTPException(status_code=404, detail="album not found")
    return {"photos": store.list_album_photos(album_id, sort=sort, tag=tag)}


# ---------- 照片整理 ----------

@router.get("/api/photos/thumbnail/{photo_id}")
def get_thumbnail(
    photo_id: int, store: PhotoStore = Depends(get_photo_store),
) -> FileResponse:
    """把縮圖檔案的實際位元組回給瀏覽器（`<img src=...>` 直接指這個
    端點）。縮圖固定存內接硬碟（見 `research.md` §3 儲存策略），理論上
    永遠可讀；萬一檔案真的不在了（例如被手動刪除），回 404，前端
    `AlbumDetail.jsx` 的 `onError` 會優雅降級成純圖示佔位。"""
    photo = store.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    if not os.path.exists(photo["thumbnail_path"]):
        raise HTTPException(status_code=404, detail="thumbnail file missing on disk")
    return FileResponse(photo["thumbnail_path"])


PREVIEW_SIZES = {"large": 2048}


@router.get("/api/photos/preview/{photo_id}")
def get_preview(
    photo_id: int,
    size: str = Query("large", description="large=長邊2048；full=原始解析度（100%放大看對焦）"),
    store: PhotoStore = Depends(get_photo_store),
) -> FileResponse:
    """單張檢視用的高解析預覽圖，**按需產生並快取**（不在匯入時預先產生，
    省空間）。格狀頁的 256/512 縮圖放大後太糊，使用者曾因此誤以為照片
    沒拍好，所以單張檢視不再用縮圖。

    - `size=large`：長邊 2048（來源較小則維持原尺寸，不放大）
    - `size=full`：原始解析度 JPEG（JPG 直接回原檔；HEIC 轉 JPEG；RAW 回
      內嵌的最大 JPEG，X3F 為 2640x1760）
    原始檔暫時無法存取（例如外接硬碟未掛載）時，退回縮圖而不是 404。"""
    photo = store.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    if size not in ("large", "full"):
        raise HTTPException(status_code=400, detail="size 必須是 large 或 full")
    src = photo["storage_path"]
    if not os.path.exists(src):
        if os.path.exists(photo["thumbnail_path"]):
            return FileResponse(photo["thumbnail_path"])
        raise HTTPException(status_code=404, detail="original and thumbnail missing")
    cache_dir = _preview_dir(store.data_dir)
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, "%s_%s.jpg" % (photo["file_hash"], size))
    try:
        if size == "full":
            return FileResponse(full_size_jpeg(src, cached))
        if not os.path.exists(cached):
            make_jpeg(src, cached, PREVIEW_SIZES["large"])
        return FileResponse(cached)
    except Exception as exc:  # noqa: BLE001 — 預覽失敗退回縮圖，不讓畫面全黑
        if os.path.exists(photo["thumbnail_path"]):
            return FileResponse(photo["thumbnail_path"])
        raise HTTPException(status_code=500, detail="preview failed: %s" % exc)


@router.get("/api/photos/photos/{photo_id}")
def get_photo(
    photo_id: int, store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    photo = store.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    photo = dict(photo)
    photo["tags"] = [t["name"] for t in store.get_photo_tags(photo_id)]
    photo["albums"] = store.get_photo_albums(photo_id)
    return photo


class PhotoPatch(BaseModel):
    rating: Optional[int] = None
    tags: Optional[List[str]] = None


@router.patch("/api/photos/photos/{photo_id}")
def patch_photo(
    photo_id: int, body: PhotoPatch, background_tasks: BackgroundTasks,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """評分/標籤編輯。db 立即更新（畫面與全域搜尋馬上反映），接著把
    `metadata_sync_status` 設回 `pending` 並透過背景任務把最新的標籤/
    評分寫回照片檔案本身（User Story 3，spec.md FR-012/013）。"""
    if store.get_photo(photo_id) is None:
        raise HTTPException(status_code=404, detail="photo not found")
    try:
        if body.rating is not None:
            store.set_photo_rating(photo_id, body.rating)
        if body.tags is not None:
            store.set_photo_tags(photo_id, body.tags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if body.rating is not None or body.tags is not None:
        store.mark_metadata_pending(photo_id)
        background_tasks.add_task(_run_metadata_sync, photo_id, store.data_dir)
    return get_photo(photo_id, store)


@router.post("/api/photos/photos/{photo_id}/resync")
def resync_photo(
    photo_id: int, background_tasks: BackgroundTasks,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """手動重新觸發中繼資料寫回（spec.md User Story 3 Acceptance
    Scenario 3：使用者把外接硬碟接回去後手動補寫）。"""
    if store.get_photo(photo_id) is None:
        raise HTTPException(status_code=404, detail="photo not found")
    store.mark_metadata_pending(photo_id)
    background_tasks.add_task(_run_metadata_sync, photo_id, store.data_dir)
    return {"status": "pending"}


class PhotoBatchRequest(BaseModel):
    photo_ids: List[int]
    add_album_id: Optional[int] = None
    add_tags: Optional[List[str]] = None
    set_rating: Optional[int] = None


@router.post("/api/photos/photos/batch")
def batch_update_photos(
    body: PhotoBatchRequest, background_tasks: BackgroundTasks,
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """批次操作：`add_album_id`／`add_tags` 是**疊加**語意（不清空既有
    標籤/相簿），跟單張 `PATCH` 的取代語意不同，見 `photo_store.py`
    `add_tags_to_photo()` 的說明。`add_tags`／`set_rating` 會觸發中繼
    資料背景寫回（User Story 3），`add_album_id` 不會——相簿歸屬是
    STND 專屬概念，無對應的 XMP/IPTC 標準欄位。"""
    updated = []
    errors = []
    touches_metadata = bool(body.add_tags) or body.set_rating is not None
    for photo_id in body.photo_ids:
        if store.get_photo(photo_id) is None:
            errors.append({"photo_id": photo_id, "error": "photo not found"})
            continue
        try:
            if body.add_album_id is not None:
                store.add_photo_to_album(photo_id, body.add_album_id)
            if body.add_tags:
                store.add_tags_to_photo(photo_id, body.add_tags)
            if body.set_rating is not None:
                store.set_photo_rating(photo_id, body.set_rating)
        except ValueError as exc:
            errors.append({"photo_id": photo_id, "error": str(exc)})
            continue
        if touches_metadata:
            store.mark_metadata_pending(photo_id)
            background_tasks.add_task(_run_metadata_sync, photo_id, store.data_dir)
        updated.append(photo_id)
    return {"updated": updated, "errors": errors}


@router.delete("/api/photos/photos/{photo_id}")
def delete_photo(
    photo_id: int, store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """僅刪除資料庫紀錄，**不刪除磁碟上的原始檔案**（spec.md FR-011，
    `photo_store.py::delete_photo()` 已保證不觸碰 `storage_path`）。"""
    deleted = store.delete_photo(photo_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="photo not found")
    return {"deleted": deleted}


# ---------- 標籤自動完成 ----------
# FR-006（User Story 1：「加標籤時提示既有標籤」）需要的端點——雖然
# tasks.md 當初把 GET /api/photos/tags 誤標在 User Story 2（搜尋）的
# 任務分組，但這個端點本身是加標籤自動完成用，屬於 User Story 1 的
# 需求（見 spec.md FR-006），這裡跟著 User Story 1 一起實作，tasks.md
# 的分組標籤留待下次更新時修正，不影響功能正確性。

@router.get("/api/photos/search/facets")
def search_facets(store: PhotoStore = Depends(get_photo_store)) -> Dict[str, Any]:
    """全域搜尋畫面的相機/鏡頭下拉選單選項——只回傳資料庫裡實際出現過
    的值，不是寫死清單。"""
    return {
        "camera_models": store.list_camera_models(),
        "lenses": store.list_lenses(),
    }


@router.get("/api/photos/search")
def search_photos_endpoint(
    camera_model: Optional[str] = Query(None),
    lens: Optional[str] = Query(None),
    tags: List[str] = Query([]),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    """跨相簿全域搜尋（User Story 2，spec.md FR-009）。`tags` 可重複
    帶多個 query 參數（`?tags=夕陽&tags=京都`），取交集。分頁在 Python
    層做（個人相片庫規模，不需要 SQL 層 LIMIT/OFFSET 的複雜度）。"""
    all_photos = store.search_photos(
        camera_model=camera_model or None, lens=lens or None,
        tags=tags or None)
    return {"total": len(all_photos), "photos": all_photos[offset:offset + limit]}


@router.get("/api/photos/tags")
def suggest_tags(
    q: str = Query("", description="標籤名稱關鍵字，空字串＝回傳全部既有標籤"),
    store: PhotoStore = Depends(get_photo_store),
) -> Dict[str, Any]:
    if not q:
        return {"tags": [t["name"] for t in store.list_tags()]}
    return {"tags": [t["name"] for t in store.suggest_tags(q)]}
