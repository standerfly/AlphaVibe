"""文章內文圖片下載（010 T015、research R5）。

探查實測：內文圖片網址**不帶 cookie 就能下載**（200 image/png），所以由 Python 以 HTTP 下載，
**不算登入次數**；但仍要隨機間隔（5～15 秒），避免短時間連續請求。圖片網址來自登入後的文章頁。

安全：只允許指定主機（預設 investanchors.com 及其子網域）、拒絕跨主機轉址、副檔名白名單、
路徑固定為 `articles_images/<article_id>/<seq>.<ext>`（不含任何來自網址的路徑片段）、單檔上限 20MB。
單張失敗只標記該圖（`file_path` 留 NULL，下次補抓），不影響文章。僅標準庫，Python 3.9 相容。
"""
import os
import random
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import investanchors_limits

IMAGES_DIRNAME = "articles_images"
MAX_BYTES = 20 * 1024 * 1024
ALLOWED_EXT = ("png", "jpg", "jpeg", "webp", "gif")
_CONTENT_TYPE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
                     "image/webp": "webp", "image/gif": "gif"}
DEFAULT_ALLOWED_HOSTS = ("investanchors.com",)


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            raise urllib.error.HTTPError(req.full_url, code, "cross-host redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _host_allowed(url, allowed_hosts):
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


def _ext_for(url, content_type):
    path_ext = os.path.splitext(urlparse(url).path)[1].lower().lstrip(".")
    if path_ext in ALLOWED_EXT:
        return path_ext
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(ct)


def download_images(store, article_id, data_dir, sleeper=time.sleep, rng=None, timeout=30,
                    max_bytes=MAX_BYTES, allowed_hosts=DEFAULT_ALLOWED_HOSTS):
    """下載該文章所有尚無本機檔的圖片。回傳 {"downloaded": [seq…], "failed": [(seq, reason)…]}。

    每張之間隨機間隔 IMAGE_DELAY_RANGE 秒（第一張前不等）。不帶 cookie。
    """
    rng = rng or random
    base = os.path.join(os.path.abspath(data_dir), IMAGES_DIRNAME)
    opener = urllib.request.build_opener(_SameHostRedirect)
    result = {"downloaded": [], "failed": []}
    first = True
    for img in store.list_images(article_id):
        if img.get("file_path"):
            continue
        url = img.get("src_url") or ""
        if urlparse(url).scheme not in ("http", "https") or not _host_allowed(url, allowed_hosts):
            result["failed"].append((img["seq"], "host_not_allowed"))
            continue
        if not first:
            sleeper(investanchors_limits.clamp_image_delay_seconds(
                rng.uniform(*investanchors_limits.IMAGE_DELAY_RANGE)))
        first = False
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with opener.open(req, timeout=timeout) as resp:
                ext = _ext_for(url, resp.headers.get("Content-Type"))
                if ext is None:
                    result["failed"].append((img["seq"], "bad_extension"))
                    continue
                data = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as e:
            result["failed"].append((img["seq"], "http_%d" % e.code))
            continue
        except (urllib.error.URLError, OSError, ValueError):
            result["failed"].append((img["seq"], "network"))
            continue
        if len(data) > max_bytes:
            result["failed"].append((img["seq"], "too_large"))
            continue
        rel = os.path.join(IMAGES_DIRNAME, str(int(article_id)), "%d.%s" % (int(img["seq"]), ext))
        full = os.path.join(os.path.abspath(data_dir), rel)
        if not os.path.abspath(full).startswith(base + os.sep):
            result["failed"].append((img["seq"], "bad_path"))
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, full)
        store.set_image_file(article_id, img["seq"], rel)
        result["downloaded"].append(img["seq"])
    return result
