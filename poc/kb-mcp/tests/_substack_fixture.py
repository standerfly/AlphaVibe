"""011 Substack 匯入的共用測試夾具（tasks T004）。

**全部內容皆為合成**：不複製任何真實文章的文字、標題或網址。
所有「像真的」字串都帶明顯的測試標記（見下方四個 *_MARK 常數），
讓外洩掃描（T027）可以用這些標記做負向斷言。

提供：
  make_feed(items)          —— RSS 2.0 字串（guid isPermaLink=false、link、title、pubDate、
                               content:encoded、description、enclosure）
  article_samples(link)     —— research R6 列出的結構樣本（dict：名稱 → content:encoded 內容）
  MALICIOUS_FEED_XML／CHALLENGE_HTML —— feed 層級的惡意 XML 與 HTML 挑戰頁
  FakeHttp                  —— 依 URL 回傳腳本化回應，記錄每筆請求（URL、headers、timeout）
  FakeClock                 —— 可設定的台北時間（+08:00）與 monotonic；sleep 只記錄不真睡
  FakeNotifier              —— 記錄每則通知文字，可腳本化失敗（錯誤字串含假 Bot token）
  FakeClaudeRunner          —— 記錄模型呼叫（本包不應該有任何呼叫）
  temp_data_dir()           —— tempfile.mkdtemp() 經 os.path.realpath
  write_config(data_dir)    —— 寫出合法設定檔

本檔案**不發出任何真實網路請求**：只建構 urllib 的例外型別當測試替身，從不開啟連線。
僅標準庫、Python 3.9 相容。
"""
import datetime
import email.utils
import json
import os
import re
import socket
import tempfile
import urllib.error

# ---------------------------------------------------------------- 外洩掃描標記（T027 用）
TITLE_MARK = "ZZTITLEMARKZZ"        # 只允許出現在資料庫資料通道與 Telegram 通知
BODY_MARK = "ZZBODYMARKZZ"          # 只允許出現在資料庫資料通道
SLUG_MARK = "zzslugmarkzz"          # 文章網址 slug（等同標題，連通知都不得出現）
IMG_URL_MARK = "zzimgurlmarkzz"     # 圖片網址片段

TZ8 = datetime.timezone(datetime.timedelta(hours=8))

DEFAULT_HOST = "zzfeedhost-a.example.com"
SECOND_HOST = "zzfeedhost-b.example.com"
AUTHOR_A = {"key": "zzauthora", "name": "測試出版A", "feed_url": "https://%s/feed" % DEFAULT_HOST,
            "enabled": True}
AUTHOR_B = {"key": "zzauthorb", "name": "測試出版B", "feed_url": "https://%s/feed" % SECOND_HOST,
            "enabled": True}

IMAGE_HOST = "zzimagecdn.example.com"


# ---------------------------------------------------------------- 設定檔
def config_dict(**overrides):
    cfg = {
        "version": 1,
        "min_poll_interval_minutes": 30,
        "alert_policy": "every_failure",
        "image_hosts": [IMAGE_HOST],
        "authors": [dict(AUTHOR_A), dict(AUTHOR_B)],
    }
    cfg.update(overrides)
    return cfg


def write_config(data_dir, **overrides):
    """寫出一份合法設定檔到 data_dir，回傳寫入的 dict。"""
    cfg = config_dict(**overrides)
    path = os.path.join(data_dir, "substack_config.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    return cfg


def temp_data_dir(test=None):
    """建立獨立測試資料目錄（realpath；macOS /var→/private/var 的坑）。

    傳入 TestCase 時自動登記 cleanup。"""
    path = os.path.realpath(tempfile.mkdtemp(prefix="substack-test-"))
    if test is not None:
        import shutil
        test.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


# ---------------------------------------------------------------- RSS feed 組裝
def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def rfc2822(dt):
    return email.utils.format_datetime(dt)


UNSET = object()        # 區分「沒給」與「明確給 None」（None 是有意義的值）


def feed_item(title=None, link=None, guid=None, published=UNSET, content_html=UNSET,
              description=None, enclosure=None, host=DEFAULT_HOST, slug=None, pub_date_raw=None):
    """組一個 feed 條目（dict）。slug 省略時用 SLUG_MARK 衍生。

    published／content_html 傳 None＝刻意缺漏（pubDate／content:encoded 不寫進 XML）。"""
    slug = slug or (SLUG_MARK + "-1")
    link = link if link is not None else "https://%s/p/%s" % (host, slug)
    if title is None:
        title = "%s 測試標題" % TITLE_MARK
    if guid is None:
        guid = "zzguid-%s" % slug
    if published is UNSET:
        published = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=TZ8)
    if content_html is UNSET:
        content_html = article_samples(link)["full_no_tail"]
    return {
        "title": title,
        "link": link,
        "guid": guid,
        "published": published,
        "pub_date_raw": pub_date_raw,
        "content_html": content_html,
        "description": description if description is not None else "預覽摘要（合成）",
        "enclosure": enclosure,      # (type, url) 或 None
    }


def make_feed(items, title="測試出版", host=DEFAULT_HOST):
    """產生 RSS 2.0 字串。items 可以是 feed_item() 的 dict 清單。"""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
             '<channel>',
             '<title>%s</title>' % _escape(title),
             '<link>https://%s</link>' % host,
             '<description>合成測試 feed</description>']
    for it in items:
        parts.append('<item>')
        parts.append('<title>%s</title>' % _escape(it["title"]))
        parts.append('<link>%s</link>' % _escape(it["link"]))
        if it.get("guid") is not None:
            parts.append('<guid isPermaLink="false">%s</guid>' % _escape(it["guid"]))
        raw = it.get("pub_date_raw")
        if raw is not None:
            parts.append('<pubDate>%s</pubDate>' % _escape(raw))
        elif it.get("published") is not None:
            parts.append('<pubDate>%s</pubDate>' % rfc2822(it["published"]))
        if it.get("description") is not None:
            parts.append('<description><![CDATA[%s]]></description>' % it["description"])
        if it.get("content_html") is not None:
            parts.append('<content:encoded><![CDATA[%s]]></content:encoded>' % it["content_html"])
        enc = it.get("enclosure")
        if enc:
            parts.append('<enclosure url="%s" type="%s" length="1234"/>'
                         % (_escape(enc[1]), _escape(enc[0])))
        parts.append('</item>')
    parts.append('</channel>')
    parts.append('</rss>')
    return "\n".join(parts)


# ---------------------------------------------------------------- 文章結構樣本（research R6）
def filler(n_chars, mark=BODY_MARK):
    """產生 n_chars 個可見字元的合成內文（含一個外洩標記）。"""
    base = mark + "合成內文字串用來湊字數"
    out = []
    total = 0
    while total < n_chars:
        out.append(base)
        total += len(base)
    text = "".join(out)[:max(n_chars, len(mark))]
    return text


def img_tag(idx, with_alt=True, with_caption=False, host=IMAGE_HOST):
    url = "https://%s/%s-%d.jpg" % (host, IMG_URL_MARK, idx)
    alt = ' alt="圖說ALT%d"' % idx if with_alt else ""
    tag = '<img src="%s"%s />' % (url, alt)
    if with_caption:
        return '<figure>%s<figcaption>圖說CAP%d</figcaption></figure>' % (tag, idx)
    return tag


def read_more_tail(link):
    """依文章連結組出站方的固定「Read more」尾端段落。"""
    return '<p><a href="%s">Read more</a></p>' % link


def article_samples(link="https://%s/p/%s-1" % (DEFAULT_HOST, SLUG_MARK)):
    """回傳 research R6 列出的結構樣本：名稱 → content:encoded 的內容。

    對應 `docs/spec-intake/substack-import/raw/2026-11-19-paid-preview-analysis.md` 第 4 行描述的結構。
    """
    other = "https://zzotherhost.example.com/p/%s-1" % SLUG_MARK
    return {
        # 1. Read more 尾端預覽（短）
        "preview_short": "<p>%s</p>%s" % (filler(50), read_more_tail(link)),
        # 2. Read more 尾端預覽（長文，驗「不以長度判斷」）
        "preview_long": "<p>%s</p>%s" % (filler(15000), read_more_tail(link)),
        # 3. 純播放器（非文字）
        "player_only": '<div class="audio-player"><audio src="https://%s/a.mp3"></audio></div>'
                       % IMAGE_HOST,
        # 4. 嵌入卡片（非文字）
        "embed_card": '<div class="embed-card"><iframe src="https://zzembed.example.com/x">'
                      '</iframe></div>',
        # 5. 長文無尾端（全文）
        "full_long": "<p>%s</p><p>%s</p>" % (filler(15000), filler(200)),
        # 6. 一般全文無尾端
        "full_no_tail": "<p>%s</p>%s<p>%s</p>" % (filler(300), img_tag(1, with_caption=True),
                                                  filler(300)),
        # 7. 短文無尾端（非文字）
        "short_no_tail": "<p>%s</p>" % filler(50),
        # 8. 免責聲明結尾（全文，尾端是 p 但不是 Read more 連結）
        "disclaimer_end": "<p>%s</p><p><em>本文僅供參考，不構成投資建議。</em></p>" % filler(400),
        # 9. content:encoded 缺漏／空白
        "empty_content": "",
        # 10. 尾端有 Read more 文字但 href 主機不符
        "read_more_other_host": "<p>%s</p><p><a href=\"%s\">Read more</a></p>"
                                % (filler(400), other),
        # 11. Read more 後面還有內容
        "read_more_then_more": "<p>%s</p>%s<p>%s</p>" % (filler(400), read_more_tail(link),
                                                         filler(100)),
        # 12. 壞掉的 HTML（標籤未閉合、巢狀錯亂）
        "broken_html": "<p><div>%s</span></p" % filler(300),
        # 13. 多圖（圖位標記編號）
        "multi_image": "<p>%s</p>%s%s<ul><li>項目一</li><li>項目二</li></ul>%s"
                       % (filler(250), img_tag(1), img_tag(2, with_caption=True),
                          img_tag(3, with_alt=False)),
        # 14. script／style 應被丟棄
        "with_script": "<p>%s</p><script>var x=1;</script><style>.a{color:red}</style>"
                       % filler(300),
    }


# feed 層級的惡意 XML（含 DTD／實體宣告，必須在解析前就被拒絕）
MALICIOUS_FEED_XML = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
    '<rss version="2.0"><channel><item><title>&xxe;</title>'
    '<link>https://%s/p/%s-x</link></item></channel></rss>' % (DEFAULT_HOST, SLUG_MARK))

# 站方回傳的 HTML 挑戰頁（視同被擋）
CHALLENGE_HTML = ('<!DOCTYPE html>\n<html><head><title>Just a moment...</title></head>'
                  '<body>請完成驗證</body></html>')


# ---------------------------------------------------------------- 假 HTTP
class FakeResponse(object):
    """最小化的回應物件（與 substack_feed 的 fetch 介面約定一致）。"""

    def __init__(self, status, headers=None, body="", url=None):
        self.status = int(status)
        self.headers = dict(headers or {})
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.url = url


# ---- 腳本化回應（放進 FakeHttp.route 的動作）
def ok(body, etag=None, content_type="application/rss+xml"):
    return {"kind": "ok", "body": body, "etag": etag, "content_type": content_type}


def not_modified(etag=None):
    return {"kind": "not_modified", "etag": etag}


def status(code, body="", content_type="text/plain"):
    return {"kind": "status", "code": int(code), "body": body, "content_type": content_type}


def challenge():
    return {"kind": "ok", "body": CHALLENGE_HTML, "etag": None, "content_type": "text/html"}


def timeout():
    return {"kind": "timeout"}


def network():
    return {"kind": "network"}


def hang(seconds=None):
    """卡住直到逾時：把注入的時鐘往前推（timeout 秒或指定秒數）再丟逾時。"""
    return {"kind": "hang", "seconds": seconds}


def redirect(new_url):
    return {"kind": "redirect", "url": new_url}


def too_large(size=6 * 1024 * 1024):
    return {"kind": "too_large", "size": int(size)}


class FakeHttp(object):
    """依 URL 回傳腳本化回應；記錄每筆請求的 URL、headers 與 timeout。

    用法：
        http = FakeHttp(clock)
        http.route("https://host/feed", ok(feed_xml, etag='W/"1"'), not_modified())
        http.default = status(404)
    """

    def __init__(self, clock=None):
        self.clock = clock
        self.routes = {}
        self.requests = []          # [{"url":…, "headers":…, "timeout":…}]
        self.default = None

    def route(self, url, *actions):
        self.routes.setdefault(url, []).extend(actions)
        return self

    def count(self, url=None):
        if url is None:
            return len(self.requests)
        return sum(1 for r in self.requests if r["url"] == url)

    def headers_for(self, url):
        return [r["headers"] for r in self.requests if r["url"] == url]

    def __call__(self, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        actions = self.routes.get(url)
        if actions:
            action = actions.pop(0) if len(actions) > 1 else actions[0]
        elif self.default is not None:
            action = self.default
        else:
            action = status(404)
        return self._act(url, action, timeout)

    def _act(self, url, action, timeout):
        kind = action["kind"]
        if kind == "ok":
            h = {"Content-Type": action["content_type"]}
            if action.get("etag"):
                h["ETag"] = action["etag"]
            return FakeResponse(200, h, action["body"], url)
        if kind == "not_modified":
            h = {}
            if action.get("etag"):
                h["ETag"] = action["etag"]
            return FakeResponse(304, h, b"", url)
        if kind == "status":
            return FakeResponse(action["code"], {"Content-Type": action["content_type"]},
                                action["body"], url)
        if kind == "too_large":
            return FakeResponse(200, {"Content-Type": "application/rss+xml"},
                                b"x" * action["size"], url)
        if kind == "timeout":
            raise socket.timeout("timed out")
        if kind == "network":
            raise urllib.error.URLError("合成網路錯誤")
        if kind == "hang":
            secs = action.get("seconds")
            if secs is None:
                secs = timeout if timeout else 30
            if self.clock is not None:
                self.clock.advance(secs)
            raise socket.timeout("timed out")
        if kind == "redirect":
            from substack_feed import RedirectRefused     # 延遲載入：只有這條路徑需要
            raise RedirectRefused(action["url"])
        raise AssertionError("未知的假回應種類：%s" % kind)


# ---------------------------------------------------------------- 假時鐘
class FakeClock(object):
    """可設定的台北時間與 monotonic；sleep 只記錄並推進時間，不真睡。"""

    def __init__(self, now="2026-11-20 22:00:00", mono=1000.0):
        self.set_now(now)
        self._mono = float(mono)
        self.slept = []

    def set_now(self, value):
        if isinstance(value, datetime.datetime):
            self._now = value if value.tzinfo else value.replace(tzinfo=TZ8)
        else:
            self._now = datetime.datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=TZ8)
        return self._now

    def now(self):
        return self._now

    def monotonic(self):
        return self._mono

    def advance(self, seconds):
        self._mono += float(seconds)
        self._now = self._now + datetime.timedelta(seconds=float(seconds))
        return self._now

    def sleep(self, seconds):
        self.slept.append(float(seconds))
        self.advance(seconds)


# ---------------------------------------------------------------- 假通知
class FakeNotifier(object):
    """記錄每則文字；可腳本化失敗。失敗訊息刻意含假 Bot token，驗證不落地。"""

    FAKE_BOT_TOKEN = "123456789:" + "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqR"   # 冒號後 35 字元

    def __init__(self, fail_times=0, fail_all=False):
        assert len(self.FAKE_BOT_TOKEN.split(":")[1]) == 35
        self.texts = []
        self.fail_times = int(fail_times)
        self.fail_all = bool(fail_all)
        self.calls = 0

    def __call__(self, text, *args, **kwargs):
        self.calls += 1
        self.texts.append(text)
        if self.fail_all or self.calls <= self.fail_times:
            return 0, ["chat 123：HTTP 401 Unauthorized https://api.telegram.org/bot%s/sendMessage"
                       % self.FAKE_BOT_TOKEN]
        return 1, []


# ---------------------------------------------------------------- 假 claude runner
class FakeClaudeRunner(object):
    """本包（T001～T028）不應該有任何模型呼叫；留給 US6 用，也供斷言「呼叫次數為 0」。"""

    def __init__(self, text="（假轉寫結果）"):
        self.calls = []
        self.text = text

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.text


# ---------------------------------------------------------------- 文章列（直接插庫用）
_ROW_SEQ = [0]


def article_row(**overrides):
    """組一個可直接交給 insert_article_with_images 的文章 dict（欄位值皆為合成）。"""
    _ROW_SEQ[0] += 1
    n = _ROW_SEQ[0]
    slug = "%s-%d" % (SLUG_MARK, n)
    link = "https://%s/p/%s" % (DEFAULT_HOST, slug)
    row = {
        "author_key": AUTHOR_A["key"],
        "guid": "zzguid-%d" % n,
        "link": link,
        "link_norm": link,
        "title": "%s 標題 %d" % (TITLE_MARK, n),
        "published_at": "2026-11-20T09:00:00+08:00",
        "fetched_at": "2026-11-20T22:00:05+08:00",
        "source": "schedule",
        "completeness": "F",
        "classify_reason": "text_ge_200",
        "content_html": "<p>%s</p>" % filler(300),
        "body_text": filler(300),
        "description": "預覽摘要（合成）",
        "enclosure_type": None,
    }
    row.update(overrides)
    return row


def image_rows(count=1, host=IMAGE_HOST):
    return [{"seq": i, "src_url": "https://%s/%s-%d.jpg" % (host, IMG_URL_MARK, i),
             "alt": "ALT%d" % i, "caption": "CAP%d" % i} for i in range(1, count + 1)]


# ---------------------------------------------------------------- 小工具
_MARK_RE = re.compile("|".join(re.escape(m) for m in (TITLE_MARK, BODY_MARK, SLUG_MARK,
                                                      IMG_URL_MARK)))


def marks_in(text):
    """回傳 text 中出現的測試標記清單（供外洩掃描輔助）。"""
    return sorted(set(_MARK_RE.findall(str(text))))
