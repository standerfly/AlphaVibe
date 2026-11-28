"""公開 RSS feed 的請求、回應判別與解析（011；research R6、data-model §2.4）。

原則：
* **只打設定檔裡的公開 `/feed` 網址**，不帶 Cookie／Authorization、不登入、不用通知信（FR-001、FR-003）。
* 回應先「判別」再「解析」：每種結果都有固定代碼（§2.4），日誌只記代碼，
  **不記錄例外原文、標題、文章網址**（FR-026）。
* XML 先拒絕含 DTD／實體宣告的內容，才交給 `xml.etree.ElementTree`（防實體展開）。
* 轉址只允許落在該作者的 feed 主機或 `<x>.substack.com`（安全規則比照既有圖片下載模組的做法，
  另寫不共用程式）。
* 可注入 `fetch(url, headers, timeout)`：測試用假 HTTP，正式用 `urllib.request`。

僅標準庫、Python 3.9 相容。
"""
import datetime
import email.utils
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; personal-feed-reader/1.0)"
FEED_TIMEOUT = 30
MAX_FEED_BYTES = 5 * 1024 * 1024
ROBOTS_FRESH_SEC = 24 * 3600
ROBOTS_STALE_LIMIT_SEC = 7 * 86400
SUBSTACK_SUFFIX = ".substack.com"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"

# 每位作者每次執行的結果代碼（data-model §2.4）＋ error_code 可能回傳的代碼
OUTCOMES = ("ok_200", "not_modified", "skipped_interval", "blocked_403", "rate_limited_429",
            "challenge_html", "timeout", "network", "parse_error", "too_large",
            "redirect_refused", "robots_disallow", "robots_unavailable", "error")

_DTD_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.I)
_HTML_START_RE = re.compile(r"^\s*(<!doctype\s+html|<html\b)", re.I)


class RedirectRefused(Exception):
    """轉址到不被允許的主機：不跟隨（只回代碼，不含網址）。"""


class FeedTooLarge(Exception):
    """回應超過 MAX_FEED_BYTES。"""


class FeedParseError(Exception):
    """不是可解析的 RSS（含 DTD／實體宣告，或 XML 壞掉）。"""


class Response(object):
    """fetch() 的回傳型別：status／headers／body（bytes 或 str）。"""

    def __init__(self, status, headers=None, body=b"", url=None):
        self.status = int(status)
        self.headers = dict(headers or {})
        self.body = body
        self.url = url


# ---------------------------------------------------------------- 請求
def build_headers(etag=None):
    """只帶通用識別與條件請求標頭；**永不**帶 Cookie／Authorization（FR-001）。"""
    headers = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"}
    if etag:
        headers["If-None-Match"] = etag          # 原字串，含 W/ 弱標記
    return headers


def request_timeout(remaining=None):
    """每次網路操作的逾時＝min(預設 30 秒, 剩餘牆鐘預算)（research R2）。"""
    if remaining is None:
        return FEED_TIMEOUT
    return min(FEED_TIMEOUT, max(0, remaining))


def _host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def redirect_allowed(from_url, to_url):
    """只允許 https 且落在原主機或 <x>.substack.com。"""
    parts = urllib.parse.urlsplit(to_url)
    if parts.scheme != "https":
        return False
    target = (parts.hostname or "").lower()
    origin = _host_of(from_url)
    if not target:
        return False
    if target == origin:
        return True
    return target.endswith(SUBSTACK_SUFFIX)


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not redirect_allowed(req.full_url, newurl):
            raise RedirectRefused("refused")
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


def default_fetch(url, headers=None, timeout=None):
    """正式路徑：urllib.request（不跟隨未允許的轉址；非 2xx 也回 Response 交給判別）。"""
    opener = urllib.request.build_opener(_RestrictedRedirect)
    request = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with opener.open(request, timeout=timeout or FEED_TIMEOUT) as resp:
            body = resp.read(MAX_FEED_BYTES + 1)
            return Response(getattr(resp, "status", 200) or 200, dict(resp.headers), body, url)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(MAX_FEED_BYTES + 1)
        except Exception:                                 # noqa: BLE001
            pass
        return Response(exc.code, dict(exc.headers or {}), body, url)


# ---------------------------------------------------------------- 回應判別（§2.4）
def _as_text(body):
    if isinstance(body, bytes):
        return body.decode("utf-8", "replace")
    return "" if body is None else str(body)


def _body_len(body):
    if isinstance(body, bytes):
        return len(body)
    return len(_as_text(body).encode("utf-8"))


def classify_response(status, headers, body):
    status = int(status)
    if status == 304:
        return "not_modified"
    if status == 403:
        return "blocked_403"
    if status == 429:
        return "rate_limited_429"
    if status != 200:
        return "http_%d" % status
    if _body_len(body) > MAX_FEED_BYTES:
        return "too_large"
    content_type = ""
    for key, value in (headers or {}).items():
        if str(key).lower() == "content-type":
            content_type = str(value).lower()
            break
    if "html" in content_type:
        return "challenge_html"
    if _HTML_START_RE.match(_as_text(body)[:200]):
        return "challenge_html"
    return "ok_200"


def error_code(exc):
    """只回代碼字串：永不含例外原文、網址或 token（FR-026、research R4）。"""
    if isinstance(exc, RedirectRefused):
        return "redirect_refused"
    if isinstance(exc, FeedTooLarge):
        return "too_large"
    if isinstance(exc, FeedParseError):
        return "parse_error"
    if isinstance(exc, socket.timeout):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return "http_%d" % exc.code
    if isinstance(exc, urllib.error.URLError):
        if isinstance(getattr(exc, "reason", None), socket.timeout):
            return "timeout"
        return "network"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "network"
    return "error"


# ---------------------------------------------------------------- 解析
def parse_feed(body):
    """回傳條目清單；含 DTD／實體宣告或壞 XML 一律丟 FeedParseError。"""
    text = _as_text(body)
    if _DTD_RE.search(text):
        raise FeedParseError("dtd_refused")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedParseError("xml_error") from None
    except ValueError:
        raise FeedParseError("xml_error") from None
    items = []
    for node in root.iter("item"):
        items.append(_parse_item(node))
    return items


def _text_of(node, tag):
    child = node.find(tag)
    if child is None:
        return None
    text = child.text
    return text if text is None else text.strip() or None


def _parse_item(node):
    pub_raw = _text_of(node, "pubDate")
    published = None
    if pub_raw:
        try:
            published = email.utils.parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError, IndexError):
            published = None
    content = node.find(CONTENT_NS)
    content_html = None if content is None else content.text
    if content_html is not None and not content_html.strip():
        content_html = None
    enclosure = node.find("enclosure")
    return {
        "guid": _text_of(node, "guid"),
        "link": _text_of(node, "link"),
        "title": _text_of(node, "title"),
        "published_at": published,
        "pub_date_raw": pub_raw,
        "content_html": content_html,
        "description": _text_of(node, "description"),
        "enclosure_type": (enclosure.get("type") if enclosure is not None else None),
        "enclosure_url": (enclosure.get("url") if enclosure is not None else None),
    }


def normalize_link(url):
    """去重鍵二：https、小寫主機、去 query／fragment、去尾斜線（research R6）。"""
    parts = urllib.parse.urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    netloc = host
    port = None
    try:
        port = parts.port
    except ValueError:
        port = None
    if port and port != 443:
        netloc = "%s:%d" % (host, port)
    path = parts.path or ""
    if len(path) > 1:
        path = path.rstrip("/")
    elif path == "/":
        path = ""
    return "https://%s%s" % (netloc, path)


# ---------------------------------------------------------------- 單次 feed 取得
def fetch_feed(fetch, url, etag=None, remaining=None):
    """每作者每次執行最多呼叫一次（FR-003）。回傳 dict（outcome／status／etag／items）。"""
    headers = build_headers(etag)
    timeout = request_timeout(remaining)
    try:
        resp = fetch(url, headers=headers, timeout=timeout)
    except Exception as exc:                              # noqa: BLE001
        return {"outcome": error_code(exc), "status": None, "etag": None, "items": None,
                "body": None}
    outcome = classify_response(resp.status, resp.headers, resp.body)
    new_etag = None
    for key, value in (resp.headers or {}).items():
        if str(key).lower() == "etag":
            new_etag = value
            break
    result = {"outcome": outcome, "status": resp.status, "etag": new_etag, "items": None,
              "body": None}
    if outcome != "ok_200":
        return result
    try:
        result["items"] = parse_feed(resp.body)
    except FeedParseError as exc:
        result["outcome"] = error_code(exc)
        result["items"] = None
    return result


# ---------------------------------------------------------------- robots.txt
def _parse_iso(text):
    try:
        return datetime.datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


class RobotsGate(object):
    """robots.txt 判斷＋每主機 24 小時快取；取不到時可用 7 天內的舊快取（research R6）。

    robots 請求不是 feed 請求，不計入 FR-003 的「每作者至多一次」。
    """

    def __init__(self, store, fetch, clock):
        self.store = store
        self.fetch = fetch
        self.clock = clock

    def robots_url(self, url):
        return "https://%s/robots.txt" % _host_of(url)

    def allowed(self, url, remaining=None):
        """回傳 (是否允許, outcome)；允許時 outcome 為 None。"""
        host = _host_of(url)
        if not host:
            return False, "robots_unavailable"
        cached = self.store.get_robots_cache(host)
        body = self._fresh_body(cached, ROBOTS_FRESH_SEC)
        if body is None:
            body = self._refresh(host, url, remaining)
        if body is None:
            body = self._fresh_body(cached, ROBOTS_STALE_LIMIT_SEC)
        if body is None:
            return False, "robots_unavailable"
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(str(body).splitlines())
        if parser.can_fetch(UA, url):
            return True, None
        return False, "robots_disallow"

    def _fresh_body(self, cached, max_age_sec):
        if not cached:
            return None
        fetched_at = _parse_iso(cached.get("fetched_at"))
        if fetched_at is None:
            return None
        age = (self.clock.now() - fetched_at).total_seconds()
        if age < 0 or age > max_age_sec:
            return None
        return cached.get("body") or ""

    def _refresh(self, host, url, remaining):
        try:
            resp = self.fetch(self.robots_url(url), headers=build_headers(),
                              timeout=request_timeout(remaining))
        except Exception:                                 # noqa: BLE001
            return None
        outcome = classify_response(resp.status, resp.headers, resp.body)
        body = None
        if outcome == "ok_200":
            body = _as_text(resp.body)
        elif 400 <= int(resp.status) < 500 and int(resp.status) not in (403, 429):
            body = ""                                     # 404 等＝沒有限制（robots 慣例）
        if body is None:
            return None
        self.store.put_robots_cache(host, self.clock.now().isoformat(timespec="seconds"),
                                    int(resp.status), body)
        return body
