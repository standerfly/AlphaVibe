"""脫敏與外洩斷言（010 FR-020、spec 驗收（c））。

`safe_error` 用在任何要寫進 `last_error`、日誌、通知的文字：把帳密、cookie、CSRF／session token、
追蹤連結 token、疑似內文的長字串一律遮蔽。`assert_clean` 供測試對輸出做負向斷言。
僅標準庫，Python 3.9 相容。
"""
import re

MAX_ERROR_LEN = 200
MIN_SECRET_LEN = 3

_COOKIE_HEADER_RE = re.compile(r"(?i)\b(set-cookie|cookie)\b\s*[:=]\s*[^\n\r]*")
_KV_SECRET_RE = re.compile(
    r"(?i)\b(sid|session(?:id)?|_session|sessionid|authenticity[_-]?token|csrf[_-]?token|"
    r"x-csrf-token|access[_-]?token|api[_-]?key|password|passwd|pwd)\b\s*[=:]\s*[^\s;,&\"']+")
_TRACKING_PATH_RE = re.compile(r"/c/[A-Za-z0-9_\-]{12,}")
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/=]{40,}")


def _secret_values(secrets):
    return [s for s in (secrets or ()) if s and len(str(s)) >= MIN_SECRET_LEN]


def safe_error(exc_or_text, secrets=()):
    """回傳可安全寫入日誌／資料庫／通知的文字。"""
    text = str(exc_or_text) if exc_or_text is not None else ""
    for s in _secret_values(secrets):
        text = text.replace(str(s), "<已遮蔽>")
    text = _COOKIE_HEADER_RE.sub(lambda m: m.group(1) + ": <已遮蔽>", text)
    text = _KV_SECRET_RE.sub(lambda m: m.group(1) + "=<已遮蔽>", text)
    text = _TRACKING_PATH_RE.sub("/c/<token>", text)
    text = _LONG_TOKEN_RE.sub("<token>", text)
    if len(text) > MAX_ERROR_LEN:
        return "<長文字已省略 %d 字>" % len(text)
    return text


def find_leaks(text, secrets=(), forbidden=()):
    """回傳 text 中找到的違規項目清單（空清單＝乾淨）。forbidden 為額外禁止的字串（例：文章全文標記）。"""
    text = str(text)
    leaks = []
    for s in _secret_values(secrets):
        if str(s) in text:
            leaks.append("secret")
    for f in forbidden or ():
        if f and str(f) in text:
            leaks.append("forbidden:%s" % str(f)[:20])
    if re.search(r"(?i)\bset-cookie\b|\bcookie\s*[:=]\s*\S", text):
        leaks.append("cookie")
    if re.search(r"(?i)authenticity[_-]?token\s*[=:]\s*\S|csrf[_-]?token\s*[=:]\s*\S", text):
        leaks.append("csrf")
    if _TRACKING_PATH_RE.search(text):
        leaks.append("tracking-token")
    return leaks


def assert_clean(text, secrets=(), forbidden=()):
    """測試用：text 含任何帳密／cookie／token／禁止字串即 AssertionError。"""
    leaks = find_leaks(text, secrets, forbidden)
    if leaks:
        raise AssertionError("輸出含不該外洩的內容：%s" % ", ".join(sorted(set(leaks))))
