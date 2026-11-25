"""外部內容知識庫的來源身分（012 contracts/inbox-file-format.md「身分規則」、research R3）。

只依賴標準庫（Python 3.9 相容），不 import 任何投資／文章模組。

* `source_key(url, source_type, guid=None)`：去重唯一依據；無法得出時丟 `IdentityError`（帶繁體中文原因）。
* `body_sha256(text)`：空白正規化後的 sha256 hex，只用於「同內容不同來源」警告。
* `youtube_video_id(url)`：YouTube 判斷**只看網址主機（精確比對）**，不看 source_type。
"""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

YOUTUBE_HOSTS = frozenset(("youtube.com", "www.youtube.com", "m.youtube.com",
                           "music.youtube.com", "youtu.be"))
APPLE_PODCAST_HOST = "podcasts.apple.com"
# 一般網址規則要去掉的追蹤參數（utm_* 另以前綴判斷）
TRACKING_PARAMS = frozenset(("fbclid", "gclid", "si", "ref"))
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_APPLE_SHOW_SEG_RE = re.compile(r"^id(\d+)$")
_DIGITS_RE = re.compile(r"^\d+$")


class IdentityError(ValueError):
    """無法由網址得出 source_key（網址不是 http/https、YouTube 找不到影片 ID 等）。"""


def _split(url):
    if not isinstance(url, str) or not url.strip():
        raise IdentityError("連結為空，無法判斷來源身分")
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        raise IdentityError("連結格式無效：%s" % url)
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise IdentityError("連結必須是 http 或 https 網址：%s" % url)
    return parts, host


def body_sha256(text):
    """內文雜湊：所有連續空白（含全形空白、換行）收斂成單一空格並去頭尾後取 sha256。"""
    if not isinstance(text, str):
        raise TypeError("body_sha256 需要字串")
    norm = " ".join(text.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def youtube_video_id(url):
    """若網址主機（精確比對）是 YouTube，回 11 碼影片 ID；不是 YouTube 或找不到 ID 回 None。
    要區分「是 YouTube 但沒 ID」與「不是 YouTube」請用 `is_youtube_url`。"""
    try:
        parts, host = _split(url)
    except IdentityError:
        return None
    if host not in YOUTUBE_HOSTS:
        return None
    segs = [s for s in parts.path.split("/") if s]
    cand = None
    if host == "youtu.be":
        cand = segs[0] if segs else None
    elif segs and segs[0] == "watch":
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if k == "v":
                cand = v
                break
    elif len(segs) >= 2 and segs[0] in ("shorts", "live", "embed"):
        cand = segs[1]
    if cand and _VIDEO_ID_RE.match(cand):
        return cand
    return None


def is_youtube_url(url):
    """網址主機是否為 YouTube（精確比對，不看 source_type）。無效網址回 False。"""
    try:
        _, host = _split(url)
    except IdentityError:
        return False
    return host in YOUTUBE_HOSTS


def _generic_key(parts, host):
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    try:
        port = parts.port
    except ValueError:
        raise IdentityError("連結埠號無效")
    if port and port not in (80, 443):
        netloc = "%s:%d" % (host, port)
    path = parts.path.rstrip("/")
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    pairs.sort()
    query = urlencode(pairs)
    return "url:https://%s%s%s" % (netloc, path, ("?" + query) if query else "")


def _apple_key(parts):
    show = None
    for seg in parts.path.split("/"):
        m = _APPLE_SHOW_SEG_RE.match(seg)
        if m:
            show = m.group(1)
            break
    episode = None
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k == "i" and _DIGITS_RE.match(v):
            episode = v
            break
    if show and episode:
        return "podcast:apple:%s:%s" % (show, episode)
    return None


def source_key(url, source_type, guid=None):
    """依身分規則算 source_key。

    順序：YouTube 主機（不看 source_type）→ podcast 且有 guid → podcast 的 Apple Podcasts
    （缺節目 ID 或單集 i 則退回一般網址規則）→ 一般網址。"""
    parts, host = _split(url)
    if host in YOUTUBE_HOSTS:
        vid = youtube_video_id(url)
        if not vid:
            raise IdentityError("YouTube 連結找不到影片 ID，無法判斷來源身分：%s" % url)
        return "youtube:%s" % vid
    if source_type == "podcast":
        g = guid.strip() if isinstance(guid, str) else ""
        if g:
            return "podcast:guid:%s" % g
        if host == APPLE_PODCAST_HOST:
            key = _apple_key(parts)
            if key:
                return key
    return _generic_key(parts, host)
