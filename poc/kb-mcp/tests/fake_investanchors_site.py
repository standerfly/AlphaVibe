"""本機假定錨網站（http server）：供探查工具與匯入流程的測試共用，不連真實網站。

預設行為與 010 探查測試原本內嵌的 FakeSite 完全相同；T001 起可設定：
每頁文章數（per_page）、清單項目（items：id／標題／日期）、置頂項（pinned，跨頁重複）、
是否有公告、各篇文章頁的結構模式（article_modes）、清單被擋（list_mode）、
登出模式（沿用四種）。請求紀錄在 `site.log`，另有幾個斷言用的輔助方法。
"""
import datetime
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EMAIL = "po@example.com"
PASSWORD = "pw-secret-123"
CSRF = "tok123"

MENU_JS_DELETE = (
    '<div class="dropdown"><a class="dropdown-toggle" href="#" '
    'onclick="document.getElementById(\'m\').style.display=\'block\';return false">帳號</a>'
    '<ul id="m" style="display:none"><li><a href="/logout" data-method="delete" '
    'onclick="fetch(\'/logout\',{method:\'DELETE\'}).then(function(){location.href='
    '\'/user/vip_contents/investanchors_index\'});return false">登出</a></li></ul></div>')
HIDDEN_NO_JS = '<div style="display:none"><a href="/logout" data-method="delete">登出</a></div>'
LOGOUT_HTML = {
    "link": '<a href="/logout">登出</a>',
    "none": "",
    "menu_js_delete": MENU_JS_DELETE,
    "hidden_delete_no_js": HIDDEN_NO_JS,
}

ARTICLE_MODES = ("normal", "no_image", "no_container", "short", "timeout", "forbidden")
BODY_UNIT = "SECRETBODY 第一段內容。"


def fake_id(when, n=0):
    """14 位數文章 ID：前 13 位為 epoch 毫秒（建立時間），最後 1 位為流水號（模擬真實網站的規律）。"""
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    return int(when.timestamp() * 1000) * 10 + (n % 10)


def _default_items():
    items = [{"id": 1010 - i, "title": "SECRETTITLE %d" % (1010 - i),
              "date": "2026-11-%02d" % (14 - 2 * i)} for i in range(6)]
    items += [{"id": 1004 - i, "title": "SECRETTITLE %d" % (1004 - i),
               "date": "2026-10-%02d" % (28 - 2 * i)} for i in range(3)]
    return items


class FakeSite(object):
    """logout_mode：link（可見 GET 連結）／none／menu_js_delete（隱藏選單、JS 送 DELETE）／
    hidden_delete_no_js（隱藏連結、只接受 DELETE 或 POST+_method=delete+CSRF，GET 無效）。
    article_modes：{文章 ID: 模式}，模式見 ARTICLE_MODES；未列出者為 default_article_mode。
    list_mode：None／"forbidden"（登入後的清單頁回 403）。"""

    def __init__(self, logout_mode="link", register_first=False, post_login_pw_field=False,
                 hidden_register_first=False, items=None, per_page=6, pinned=None,
                 announcement=True, article_modes=None, default_article_mode="normal",
                 list_mode=None, timeout_sleep=6.0, email=EMAIL, password=PASSWORD):
        self.logout_mode = logout_mode
        self.register_first = register_first
        self.hidden_register_first = hidden_register_first
        self.post_login_pw_field = post_login_pw_field
        self.items = list(items) if items is not None else _default_items()
        self.per_page = per_page
        self.pinned = list(pinned) if pinned is not None else [
            {"id": 777, "title": "SECRETTITLE置頂", "date": "2021-02-06"}]
        self.announcement = announcement
        self.article_modes = dict(article_modes or {})
        self.default_article_mode = default_article_mode
        self.list_mode = list_mode
        self.timeout_sleep = timeout_sleep
        self.email = email
        self.password = password
        self.sessions = set()
        self.read = set()
        self.log = []
        self.lock = threading.Lock()
        self.server = None

    # ---- 斷言用輔助 ----
    def login_posts(self):
        return [e for e in self.log if e == ("POST", "/login")]

    def article_requests(self):
        out = []
        for method, path in self.log:
            last = path.rsplit("/", 1)[-1]
            if method == "GET" and path.startswith("/user/vip_contents/") and last.isdigit():
                out.append(int(last))
        return out

    def list_requests(self):
        return [e for e in self.log
                if e[0] == "GET" and e[1] == "/user/vip_contents/investanchors_index"]

    def logout_requests(self):
        return [e for e in self.log if e[1] == "/logout"]

    def _item(self, article_id):
        for it in self.items + self.pinned:
            if it["id"] == article_id:
                return it
        return None

    def start(self):
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _sid(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sid":
                        return v
                return None

            def _send(self, body, code=200, headers=None):
                data = body.encode("utf-8")
                self.send_response(code)
                hdrs = dict(headers or {})
                self.send_header("Content-Type", hdrs.pop("Content-Type", "text/html; charset=utf-8"))
                self.send_header("Content-Length", str(len(data)))
                for k, v in hdrs.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _do_logout(self):
                site.sessions.discard(self._sid())
                return self._send("", 302, {"Location": "/user/vip_contents/investanchors_index",
                                            "Set-Cookie": "sid=; Max-Age=0; Path=/"})

            def _login_page(self, err=False):
                login = ('<form method="POST" action="/login">%s'
                         '<input type="email" name="email"><input type="password" name="password">'
                         '<label><input type="checkbox" name="remember" checked>記住我</label>'
                         '<button type="submit">登入</button></form>'
                         % ("<p>帳號或密碼錯誤</p>" if err else ""))
                register = ('<form method="POST" action="/register"><input name="name">'
                            '<input type="email" name="reg_email"><input type="password" name="rp">'
                            '<input type="password" name="rp2"><button type="submit">註冊</button></form>')
                if site.hidden_register_first:
                    forms = '<div style="display:none">%s</div>%s' % (register, login)
                elif site.register_first:
                    forms = register + login
                else:
                    forms = login + register
                return "<html><body>%s</body></html>" % forms

            def _chrome(self):
                extra = '<input type="password" name="unlock">' if site.post_login_pw_field else ""
                return ('<head><meta name="csrf-token" content="%s"></head><nav>%s%s</nav>'
                        % (CSRF, LOGOUT_HTML[site.logout_mode], extra))

            def _list_page(self, page):
                rows = [(p["id"], p["title"], p["date"]) for p in site.pinned]
                if page == 1 and site.announcement:
                    rows.append((9999, "【公告】SECRETTITLE公告", "2027-01-01"))
                start = (page - 1) * site.per_page
                chunk = site.items[start:start + site.per_page]
                rows += [(i["id"], i["title"], i["date"]) for i in chunk]
                trs = "".join(
                    '<tr><td><a href="/user/vip_contents/%d" style="font-weight:%s">%s</a>'
                    '</td><td>%s</td></tr>' % (i, "400" if i in site.read else "700", t, d)
                    for i, t, d in rows)
                has_next = page * site.per_page < len(site.items)
                nxt = ('<a rel="next" href="/user/vip_contents/investanchors_index?page=%d">'
                       '下一頁</a>' % (page + 1)) if has_next else ""
                nav = ('<a href="/user/vip_contents/investanchors_index?lv=0">總覽</a>'
                       '<a href="/user/vip_contents/investanchors_index?lv=1">週報</a>')
                return "<html>%s<body>%s<table>%s</table>%s</body></html>" % (
                    self._chrome(), nav, trs, nxt)

            def _article_page(self, aid, mode):
                it = site._item(aid)
                date = (it or {}).get("date") or "2026-11-08"
                stamp = '<span class="post_date">· %s 12:00</span>' % date
                long_body = "<p>%s</p><p>%s</p>" % (BODY_UNIT * 20, BODY_UNIT * 20)
                if mode == "no_container":
                    inner = '<div class="other">%s</div>' % long_body
                    return "<html>%s<body>%s%s</body></html>" % (self._chrome(), stamp, inner)
                if mode == "short":
                    body = "<p>SECRETBODY 太短</p>"
                    media = ""
                elif mode == "no_image":
                    body = long_body
                    media = ""
                else:
                    body = long_body
                    media = ('<table><tr><td>'
                             '<img src="/img/pub/a1b2c3d4e5.png" alt="">'
                             '<img data-src="/img/secure/f6e5d4c3b2.png" '
                             'src="/img/secure/f6e5d4c3b2.png" loading="lazy" alt="表"></td></tr></table>')
                return ('<html>%s<body><img src="/img/pub/logo.png" alt="logo">%s'
                        '<div id="inves_content" class="investanchors_content">%s%s</div>'
                        '</body></html>' % (self._chrome(), stamp, body, media))

            def do_GET(self):
                u = urlparse(self.path)
                with site.lock:
                    site.log.append(("GET", u.path))
                    logged = self._sid() in site.sessions
                    if u.path == "/logout":
                        if site.logout_mode == "link" and logged:
                            return self._do_logout()
                        return self._send("method not allowed", 405)
                    if u.path.startswith("/img/secure/"):
                        if not logged:
                            return self._send("login required", 403)
                        return self._send("x", 200, {"Content-Type": "image/png"})
                    if u.path.startswith("/img/"):
                        return self._send("x", 200, {"Content-Type": "image/png"})
                    if not logged:
                        return self._send(self._login_page())
                    if u.path == "/user/vip_contents/investanchors_index":
                        if site.list_mode == "forbidden":
                            return self._send("forbidden", 403)
                        page = int((parse_qs(u.query).get("page") or ["1"])[0])
                        return self._send(self._list_page(page))
                    parts = u.path.rsplit("/", 1)
                    if parts[-1].isdigit():
                        aid = int(parts[-1])
                        mode = site.article_modes.get(aid, site.default_article_mode)
                if u.path.rsplit("/", 1)[-1].isdigit() and logged and \
                        u.path.startswith("/user/vip_contents/"):
                    if mode == "timeout":
                        time.sleep(site.timeout_sleep)
                    if mode == "forbidden":
                        return self._send("forbidden", 403)
                    with site.lock:
                        site.read.add(aid)
                    return self._send(self._article_page(aid, mode))
                return self._send("not found", 404)

            def do_DELETE(self):
                with site.lock:
                    site.log.append(("DELETE", urlparse(self.path).path))
                    if urlparse(self.path).path == "/logout":
                        return self._do_logout()
                    return self._send("not found", 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                path = urlparse(self.path).path
                with site.lock:
                    site.log.append(("POST", path))
                    if path == "/logout":
                        if (form.get("_method") == ["delete"]
                                and self.headers.get("X-CSRF-Token") == CSRF):
                            return self._do_logout()
                        return self._send("forbidden", 403)
                    if path == "/register":
                        return self._send("registered?!")
                    ok = (form.get("email") == [site.email]
                          and form.get("password") == [site.password])
                    if ok:
                        site.sessions.add("s1")
                        return self._send("", 302, {"Location": "/user/vip_contents/investanchors_index",
                                                    "Set-Cookie": "sid=s1; Path=/"})
                    return self._send(self._login_page(err=True))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
