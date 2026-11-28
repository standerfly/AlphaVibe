"""Substack 文章圖片下載（011；FR-014～FR-016、FR-034、research R6）。

只做一件事：把 `article_image` 裡狀態為 `pending`／`missing` 的圖片抓到
`<data_dir>/substack_images/<article_id>/<seq>.<ext>`，並在檔案真的落地之後才把狀態改成
`downloaded`。**圖片只下載、不做任何內容分析**（FR-014），本模組因此沒有任何送出圖片的程式路徑。

安全規則（比照既有的 010 圖片下載模組寫法，但**另寫不共用**，research R0）：
* 只允許 `https`，且主機必須與白名單完全相同或為其子網域（`image_hosts` ＋各作者 feed 主機）；
  白名單外**不發出請求**，直接記 `host_not_allowed` 並計一次失敗（FR-034）。
* 轉址只允許落在白名單主機，否則不跟隨，記 `redirect_refused`。
* `Content-Type` 必須是副檔名白名單內的 `image/*`；單檔上限 20MB；逾時 30 秒
  （並取 `min(30, 剩餘期限)`）；圖與圖之間間隔 1 秒。
* 檔名完全由 `article_id`／`seq`／Content-Type 決定，**不含任何來自網址的片段**；
  寫入先進 `.part` 暫存檔，`os.replace` 成正式檔名之後才 UPDATE 資料庫
  （資料庫說「已下載」時檔案必然存在，research R8）。

FR-016：本版**不設**圖片保留期限或占用上限，也沒有任何刪除已下載圖檔的程式路徑——
唯一的刪除動作作用於 `.part` 暫存檔（靜態測試守門）。占用現況只由
`substack_store.format_space_line()` 回報。

失敗分類：
* 站方／網路／白名單問題 → `fail_count+1`，達 3 次標 `abandoned`（排程不再自動重試，
  PO 可用 `--retry-images` 要求重試）。
* 環境問題（磁碟滿、期限到）→ **不計失敗次數**、狀態不變，下次執行再試（research R8）。

日誌只記代碼與內部 id：錯誤訊息、例外原文、圖片網址都不輸出（FR-026）。
僅標準庫、Python 3.9 相容。
"""
import errno
import hashlib
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import substack_feed  # noqa: E402
import substack_store  # noqa: E402

MAX_IMAGE_BYTES = 20 * 1024 * 1024      # 單檔上限（research R6）
IMAGE_TIMEOUT = 30                      # 單張逾時秒數（另取 min(此值, 剩餘期限)）
IMAGE_GAP_SEC = 1                       # 圖與圖之間的禮貌間隔
CHUNK_BYTES = 64 * 1024                 # 寫檔分段大小（期限可在段與段之間中斷）
PART_SUFFIX = ".part"

# 副檔名由 Content-Type 決定（不採用網址裡的副檔名，網址片段一律不進檔名）
CONTENT_TYPE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
                    "image/webp": "webp", "image/gif": "gif"}

RETRY_STATUSES = ("missing", "abandoned")       # PO 可要求重試的狀態
DOWNLOADABLE_STATUSES = ("pending", "missing")  # 排程會嘗試的狀態

CODE_HOST = "host_not_allowed"
CODE_NOT_IMAGE = "not_image"
CODE_TOO_LARGE = "too_large"
CODE_WRITE = "write_failed"


# ---------------------------------------------------------------- 白名單
def host_allowed(host, allowed_hosts):
    """完全相同或真正的子網域才算允許（不是字尾比對，`evilsubstackcdn.com` 不通過）。"""
    host = str(host or "").lower()
    if not host:
        return False
    for allowed in allowed_hosts or ():
        allowed = str(allowed or "").lower()
        if not allowed:
            continue
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def url_allowed(url, allowed_hosts):
    """只允許 https＋白名單主機。"""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    return host_allowed(parts.hostname, allowed_hosts)


class AllowedHostRedirect(urllib.request.HTTPRedirectHandler):
    """轉址只允許落在白名單主機；否則不跟隨（只回代碼，不含網址）。"""

    def __init__(self, allowed_hosts):
        self.allowed_hosts = tuple(allowed_hosts or ())

    def target_allowed(self, new_url):
        return url_allowed(new_url, self.allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, new_url):
        if not self.target_allowed(new_url):
            raise substack_feed.RedirectRefused("refused")
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, new_url)


# ---------------------------------------------------------------- 正式取得路徑
def default_fetch(url, headers=None, timeout=None, allowed_hosts=()):
    """正式路徑：`urllib.request`，不跟隨未允許的轉址，讀取上限 MAX_IMAGE_BYTES+1。"""
    opener = urllib.request.build_opener(AllowedHostRedirect(allowed_hosts))
    request = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with opener.open(request, timeout=timeout or IMAGE_TIMEOUT) as resp:
            body = resp.read(MAX_IMAGE_BYTES + 1)
            return substack_feed.Response(getattr(resp, "status", 200) or 200,
                                          dict(resp.headers), body, url)
    except urllib.error.HTTPError as exc:
        return substack_feed.Response(exc.code, dict(exc.headers or {}), b"", url)


# ---------------------------------------------------------------- 小工具
def ext_for(content_type):
    """回傳副檔名，或 None（代表不是可接受的 image/*）。"""
    main = str(content_type or "").split(";")[0].strip().lower()
    return CONTENT_TYPE_EXT.get(main)


def relative_path(article_id, seq, ext):
    """固定路徑 `substack_images/<article_id>/<seq>.<ext>`，不含任何網址片段。"""
    return os.path.join(substack_store.IMAGES_DIRNAME, str(int(article_id)),
                        "%d.%s" % (int(seq), ext))


def _header(headers, name):
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            return value
    return None


def _remaining(deadline):
    """剩餘期限秒數；`deadline` 為零參數可呼叫物件，None＝不設期限。"""
    if deadline is None:
        return None
    try:
        return float(deadline())
    except TypeError:
        return float(deadline)


def _timeout_for(remaining):
    if remaining is None:
        return IMAGE_TIMEOUT
    return min(IMAGE_TIMEOUT, max(0, remaining))


def _discard_part(path):
    """唯一的刪除動作：只作用於 `.part` 暫存檔（FR-016）。"""
    if not str(path).endswith(PART_SUFFIX):
        raise ValueError("只允許刪除 .part 暫存檔")
    try:
        os.remove(path)                 # 只刪 .part 暫存檔，正式圖檔永不刪除
    except OSError:
        pass


def _is_disk_full(exc):
    if getattr(exc, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
        return True
    return "disk is full" in str(exc).lower()


def _chunks(body):
    """把回應內容切成段：支援 bytes／str，以及有 read() 的流物件。"""
    reader = getattr(body, "read", None)
    if callable(reader):
        while True:
            chunk = reader(CHUNK_BYTES)
            if not chunk:
                return
            yield chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
    data = body if isinstance(body, bytes) else str(body or "").encode("utf-8")
    for start in range(0, len(data), CHUNK_BYTES):
        yield data[start:start + CHUNK_BYTES]


def _stream_to_part(part_path, body, max_bytes, deadline):
    """寫入 `.part`：超過上限或期限到就立刻停手。回傳 (位元組數, sha256, 中止原因)。"""
    digest = hashlib.sha256()
    total = 0
    with open(part_path, "wb") as handle:
        for chunk in _chunks(body):
            remaining = _remaining(deadline)
            if remaining is not None and remaining <= 0:
                return total, None, "deadline"
            total += len(chunk)
            if total > max_bytes:
                return total, None, CODE_TOO_LARGE
            handle.write(chunk)
            digest.update(chunk)
    return total, digest.hexdigest(), None


# ---------------------------------------------------------------- 單張下載
def _failed(store, image_id, code, requested=True):
    """記一次連續失敗（達 3 次由 store 標成 abandoned）；只存代碼，不存訊息原文。"""
    store.set_image_failed(image_id, code)
    row = store.get_image(image_id) or {}
    return {"result": "failed", "code": code, "requested": requested,
            "image_id": image_id, "status": row.get("status")}


def download_one(store, image_row, *, fetch=None, allowed_hosts=(), deadline=None, sleep=None,
                 gap=0, max_bytes=MAX_IMAGE_BYTES):
    """下載單張圖片。回傳 dict：result（downloaded／failed／deadline／skipped）＋code。

    `deadline`：零參數可呼叫物件，回傳距圖片階段期限的剩餘秒數（None＝不設期限）。
    `gap`：發出請求前要等的秒數（第一張傳 0，之後由呼叫端傳 IMAGE_GAP_SEC）。
    磁碟滿會丟 `substack_store.DiskFullError`（狀態與 fail_count 不變，由呼叫端中止整次執行）。
    """
    image_id = image_row["id"]
    status = image_row.get("status")
    if status not in DOWNLOADABLE_STATUSES:
        # abandoned／downloaded 不由排程處理（abandoned 只能由 PO 的 --retry-images 重啟）
        return {"result": "skipped", "code": "status_%s" % status, "requested": False,
                "image_id": image_id, "status": status}
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        return {"result": "deadline", "code": None, "requested": False,
                "image_id": image_id, "status": status}
    url = image_row.get("src_url") or ""
    if not url_allowed(url, allowed_hosts):
        return _failed(store, image_id, CODE_HOST, requested=False)     # 零請求（FR-034）

    if gap and sleep is not None:
        sleep(gap)
        remaining = _remaining(deadline)
        if remaining is not None and remaining <= 0:
            return {"result": "deadline", "code": None, "requested": False,
                    "image_id": image_id, "status": status}

    fetch = fetch if fetch is not None else default_fetch
    try:
        resp = fetch(url, headers={"User-Agent": substack_feed.UA},
                     timeout=_timeout_for(remaining))
    except Exception as exc:                                # noqa: BLE001
        return _failed(store, image_id, substack_feed.error_code(exc))

    code = int(getattr(resp, "status", 0) or 0)
    if code != 200:
        return _failed(store, image_id, "http_%d" % code)
    headers = getattr(resp, "headers", {}) or {}
    ext = ext_for(_header(headers, "content-type"))
    if ext is None:
        return _failed(store, image_id, CODE_NOT_IMAGE)
    declared = _header(headers, "content-length")
    if declared is not None:
        try:
            if int(str(declared).strip()) > max_bytes:
                return _failed(store, image_id, CODE_TOO_LARGE)     # 不讀取內容
        except (TypeError, ValueError):
            pass

    rel = relative_path(image_row["article_id"], image_row["seq"], ext)
    full = os.path.join(store.data_dir, rel)
    images_root = os.path.join(store.data_dir, substack_store.IMAGES_DIRNAME)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if not os.path.realpath(full).startswith(os.path.realpath(images_root) + os.sep):
        raise RuntimeError("圖片路徑逸出資料目錄（image_id=%s）" % image_id)
    part = full + PART_SUFFIX
    try:
        size, digest, abort = _stream_to_part(part, getattr(resp, "body", b""), max_bytes,
                                              deadline)
    except OSError as exc:
        _discard_part(part)
        if _is_disk_full(exc):
            raise substack_store.DiskFullError(str(exc))
        return _failed(store, image_id, CODE_WRITE)
    if abort == "deadline":
        _discard_part(part)
        return {"result": "deadline", "code": None, "requested": True,
                "image_id": image_id, "status": status}
    if abort == CODE_TOO_LARGE:
        _discard_part(part)
        return _failed(store, image_id, CODE_TOO_LARGE)

    try:
        os.replace(part, full)                      # 檔案落地，之後才改資料庫
    except OSError as exc:
        _discard_part(part)
        if _is_disk_full(exc):
            raise substack_store.DiskFullError(str(exc))
        return _failed(store, image_id, CODE_WRITE)
    try:
        store.set_image_downloaded(image_id, rel, sha256=digest, size_bytes=size)
    except substack_store.DiskFullError:
        _discard_part(part)
        raise
    except Exception as exc:                        # noqa: BLE001
        if substack_store._is_disk_full(exc):
            _discard_part(part)
            raise substack_store.DiskFullError(str(exc))
        raise
    return {"result": "downloaded", "code": None, "requested": True, "image_id": image_id,
            "status": "downloaded", "bytes": size, "file_path": rel}


# ---------------------------------------------------------------- 批次
def _empty_stats():
    return {"downloaded": 0, "failed": 0, "abandoned": 0, "skipped": 0, "requested": 0,
            "deadline_reached": False, "codes": {}}


def download_batch(store, rows, *, fetch=None, allowed_hosts=(), deadline=None, sleep=None,
                   max_bytes=MAX_IMAGE_BYTES):
    """依序下載多張圖片；期限到就停下（剩下的狀態與 fail_count 不變）。"""
    stats = _empty_stats()
    requested_any = False
    for row in rows or ():
        gap = IMAGE_GAP_SEC if requested_any else 0
        result = download_one(store, row, fetch=fetch, allowed_hosts=allowed_hosts,
                              deadline=deadline, sleep=sleep, gap=gap, max_bytes=max_bytes)
        if result["result"] == "deadline":
            stats["deadline_reached"] = True
            break
        if result.get("requested"):
            requested_any = True
            stats["requested"] += 1
        if result["result"] == "downloaded":
            stats["downloaded"] += 1
        elif result["result"] == "failed":
            stats["failed"] += 1
            code = result["code"]
            stats["codes"][code] = stats["codes"].get(code, 0) + 1
            if result.get("status") == "abandoned":
                stats["abandoned"] += 1
        else:
            stats["skipped"] += 1
    return stats


def fetcher_for(allowed_hosts):
    """正式路徑用的 fetch：把白名單綁進轉址判斷（測試一律改注入假 HTTP）。"""
    def fetch(url, headers=None, timeout=None):
        return default_fetch(url, headers=headers, timeout=timeout,
                             allowed_hosts=allowed_hosts)
    return fetch


def retry(store, image_ids, *, fetch=None, allowed_hosts=(), deadline=None, sleep=None):
    """PO 要求重試：只接受 `missing`／`abandoned`，其餘明列拒絕（不發請求）。

    回傳 {"accepted": [...], "rejected": [(id, 原因)], "stats": {...}}。
    """
    accepted, rejected = [], []
    for image_id in image_ids or ():
        row = store.get_image(image_id)
        if row is None:
            rejected.append((image_id, "not_found"))
        elif row["status"] not in RETRY_STATUSES:
            rejected.append((image_id, "status_%s" % row["status"]))
        else:
            accepted.append(int(image_id))
    reset = store.reset_images_for_retry(accepted)          # fail_count 歸零
    rows = [store.get_image(i) for i in reset]
    stats = download_batch(store, [r for r in rows if r], fetch=fetch,
                           allowed_hosts=allowed_hosts, deadline=deadline, sleep=sleep)
    return {"accepted": reset, "rejected": rejected, "stats": stats}
