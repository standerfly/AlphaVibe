"""YouTube 中繼資料自動填（012 research R5，FR-018）。僅標準庫（Python 3.9 相容）。

標題與頻道取自 oEmbed，發布日期取自影片網頁的 `"uploadDate":"YYYY-MM-DD..."`。
SSRF 防護：只接受 https 且主機精確比對於 YOUTUBE_HOSTS；以 11 碼影片 ID 重組標準網址再請求
（不用 PO 給的原始字串）；禁止跨主機轉址；回應上限 2 MB；逾時 10 秒；fetcher 可注入。
拿不到的欄位明確列入 `missing`，絕不猜測。
"""
import datetime
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

import external_content_identity as identity

TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
ALLOWED_HOSTS = identity.YOUTUBE_HOSTS

_UPLOAD_DATE_RE = re.compile(r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})')


class MetadataError(Exception):
    """中繼資料擷取失敗（網址不合法、被 SSRF 防護拒絕、回應過大、網路錯誤等）。"""


def check_allowed_url(url):
    """只放行 https 且主機精確屬於 YouTube 主機清單的網址，否則 MetadataError。"""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise MetadataError("網址格式無效")
    if parts.scheme != "https":
        raise MetadataError("只接受 https 網址")
    if host not in ALLOWED_HOSTS:
        raise MetadataError("主機不在允許清單內：%s" % host)
    return url


def canonical_urls(url):
    """由原始連結解出 11 碼影片 ID，回 (影片 ID, 標準網址, oEmbed 網址)。
    原始連結本身必須是 https＋精確 YouTube 主機。"""
    check_allowed_url(url)
    vid = identity.youtube_video_id(url)
    if not vid:
        raise MetadataError("找不到 11 碼影片 ID")
    canonical = "https://www.youtube.com/watch?v=%s" % vid
    oembed = "https://www.youtube.com/oembed?url=%s&format=json" % quote(canonical, safe="")
    return vid, canonical, oembed


def parse_oembed(text):
    """回 (title, author_name)，缺或空者為 None。"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise MetadataError("oEmbed 回應不是有效 JSON")
    if not isinstance(data, dict):
        raise MetadataError("oEmbed 回應格式不符")

    def clean(v):
        return v.strip() if isinstance(v, str) and v.strip() else None
    return clean(data.get("title")), clean(data.get("author_name"))


def parse_upload_date(html):
    """從影片網頁取 `"uploadDate":"YYYY-MM-DD..."` 的日期部分；找不到或不是真實日期回 None。"""
    if not isinstance(html, str):
        return None
    m = _UPLOAD_DATE_RE.search(html)
    if not m:
        return None
    try:
        datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return m.group(1)


# ---------------------------------------------------------------- 實際網路（可被注入的 fetcher 取代）

class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """禁止跨主機轉址：轉址目標必須仍是 https＋允許清單內的主機。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_allowed_url(newurl)
        except MetadataError as e:
            raise MetadataError("拒絕轉址：%s" % e)
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def _build_opener():
    return urllib.request.build_opener(_SameHostRedirect())


def read_limited(fp, max_bytes=MAX_RESPONSE_BYTES):
    data = fp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise MetadataError("回應超過大小上限（%d bytes）" % max_bytes)
    return data


def default_fetch(url):
    """預設 fetcher：回傳文字。每次請求前先驗網址；轉址、大小、逾時皆受限。"""
    check_allowed_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AlphaVibe external-content)",
                                               "Accept-Language": "en"})
    try:
        resp = _build_opener().open(req, timeout=TIMEOUT_SECONDS)
        try:
            raw = read_limited(resp)
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
    except MetadataError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MetadataError("請求失敗：%s" % e)
    return raw.decode("utf-8", errors="replace")


def fetch_youtube_metadata(url, fetcher=None):
    """盡力取得 YouTube 影片的 title／author／date。

    回 {"title","author","date"（取不到為 None）, "missing": [欄位名], "notes": [說明]}。
    網址不合法丟 MetadataError；個別請求失敗只記入 notes 並把對應欄位列為缺少。
    fetcher(url) -> str；預設走真實網路。注入的 fetcher 只會收到重組後的標準網址／oEmbed 網址。"""
    fetch = fetcher or default_fetch
    _, canonical, oembed = canonical_urls(url)
    result = {"title": None, "author": None, "date": None, "missing": [], "notes": []}

    def safe(u, label):
        check_allowed_url(u)
        try:
            text = fetch(u)
        except Exception as e:
            result["notes"].append("%s取得失敗：%s" % (label, e))
            return None
        if isinstance(text, bytes):
            if len(text) > MAX_RESPONSE_BYTES:
                result["notes"].append("%s回應超過大小上限" % label)
                return None
            text = text.decode("utf-8", errors="replace")
        if not isinstance(text, str):
            result["notes"].append("%s回應格式不符" % label)
            return None
        if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            result["notes"].append("%s回應超過大小上限" % label)
            return None
        return text

    body = safe(oembed, "oEmbed ")
    if body is not None:
        try:
            result["title"], result["author"] = parse_oembed(body)
        except MetadataError as e:
            result["notes"].append(str(e))
    page = safe(canonical, "影片網頁")
    if page is not None:
        result["date"] = parse_upload_date(page)
        if result["date"] is None:
            result["notes"].append("影片網頁找不到 uploadDate")
    for k in ("title", "author", "date"):
        if not result[k]:
            result[k] = None
            result["missing"].append(k)
    return result
