"""即時渲染的知識庫檢視 server（Part A 手機化，2026-07-10）。

取代 `python3 -m http.server 8080`：同一個 8080 埠（devtunnels 轉發網址
不變），但每次請求都即時讀 SQLite 重新渲染——iPhone 下拉重新整理永遠
看到最新資料，不必再手動跑 report.py。

純標準庫、Python 3.9 相容。sqlite 連線不可跨執行緒共用，因此每個請求
各自開一個 KBStore 連線（讀取量小，成本可忽略）。

`/mcp`（2026-07-30 合併，見 `mcp_http_gateway.py` 模組docstring）：
MCP Streamable HTTP transport 端點（手機 Claude App 自訂連接器用），
邏輯完全來自 `mcp_http_gateway.handle_mcp_post()`，這裡只是把它掛在同一
process、同一 8080 埠上，不需要另外轉發新埠——devtunnel 在 PO 的
VS Code 環境轉發新埠會卡住，這是繞開它的做法。`mcp_http_gateway.py`
本身仍保留獨立執行能力（未來要另開埠仍可以）。

Dashboard HTTP Basic Auth（2026-07-30 新增）：devtunnel 埠改成 Public
（匿名可存取）以便 Claude App 連接器打得到 `/mcp`（伺服器對伺服器呼叫
過不了 devtunnel 互動登入），這代表原本靠 devtunnel 帳號登入層保護的
其餘路徑（含會寫入真實交易/庫存資料的表單端點）現在對整個網路公開。
`ALPHAVIBE_DASHBOARD_TOKEN` 環境變數有設定時，除 `/mcp`、`/mcp/<token>`
外的所有路徑一律要求 `Authorization: Basic <base64(user:pass)>`，密碼
需與該環境變數相符（帳號欄位不檢查）；未設定時 fail-open（不驗證，
比照 `mcp_http_gateway._auth_ok()` 對 `ALPHAVIBE_MCP_TOKEN` 的既有慣例）
——本機開發/測試環境不需要這層保護，只有部署到公開網路時才設定它。

Dashboard 長效 session cookie（2026-07-30 新增）：PO 反饋手機端 devtunnel
連線常短暫中斷重連，每次重連瀏覽器都要求重新輸入 Basic Auth 密碼很煩
——瀏覽器對 Basic Auth 憑證的快取在連線中斷後不可靠，改用簽章 cookie
較穩定（cookie 由瀏覽器自行持久保存，不受連線中斷影響）。任何一次
Basic Auth 密碼驗證通過的請求，回應會附帶 `Set-Cookie: alphavibe_session=
<到期時間戳>.<HMAC簽章>`（30 天效期，`HttpOnly; Secure; SameSite=Lax`），
之後同裝置只要帶著這個 cookie 就能通過驗證，不用每次都跳密碼框。簽章
密鑰沿用同一個 `ALPHAVIBE_DASHBOARD_TOKEN`（不新增環境變數，單一真相
來源），驗證邏輯見 `_sign_dashboard_cookie()`／`_dashboard_cookie_valid()`。

用法：python3 poc/kb-mcp/report_server.py [--port 8080] [--data-dir DIR]
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finmind_client  # noqa: E402
import frameworks  # noqa: E402
import holdings_parser  # noqa: E402
import market_scan  # noqa: E402
import mcp_http_gateway  # noqa: E402
import report  # noqa: E402
import review_engine  # noqa: E402
import screener  # noqa: E402
import stock_alias_resolver  # noqa: E402
import trade_ledger_parser  # noqa: E402
import trade_text_parser  # noqa: E402
from kb_store import KBStore  # noqa: E402

# FR-058：`/` 改渲染儀表板（方案A單頁式），舊版完整檢視移到 /report-classic；
# /report.html、/poc/data/report.html 是舊手機書籤路徑，維持指向舊版 render()
# 不變（避免既有書籤/測試斷掉），不是儀表板。
CLASSIC_PATHS = ("/report-classic", "/report.html", "/poc/data/report.html")

_DASHBOARD_COOKIE_NAME = "alphavibe_session"
_DASHBOARD_COOKIE_MAX_AGE_SECONDS = 2592000  # 30 天

# 「加入研究」輸入框：純數字（4~6碼，允許末位一個英文字母，涵蓋一般個股
# 4碼、ETF/特別股常見5~6碼＋字母後綴）直接當代碼使用，不經過名稱解析；
# 其餘輸入一律視為股票名稱，走 _resolve_stock_add_input() 的名稱查證路徑。
_STOCK_CODE_RE = re.compile(r"^[0-9]{4,6}[A-Za-z]?$")

# ---------- 個股頁背景刷新（2026-08-01新增）----------
# 「不即時查詢」原則（見派工說明）：PO開個股詳情頁或按「更新」，畫面不等
# 外部API查詢完成——查詢在背景執行緒裡跑，跑完寫入資料庫，頁面下次重新
# 整理才看到新結果。_refreshing_codes 只是暫時性UI提示（「更新中...」），
# 行程重啟遺失也沒關係，故意不存資料庫。用 threading.Lock 保護存取（雖然
# CPython GIL下set.add/discard本身已是原子操作，仍加鎖讓程式碼意圖更明確、
# 不依賴直譯器實作細節）。
_refreshing_codes = set()
_refreshing_lock = threading.Lock()


def _mark_refreshing(code):
    with _refreshing_lock:
        _refreshing_codes.add(code)


def _unmark_refreshing(code):
    with _refreshing_lock:
        _refreshing_codes.discard(code)


def is_refreshing(code):
    """供 do_GET 渲染個股詳情頁前查詢：這個代碼目前是否有背景刷新
    執行緒正在跑。"""
    with _refreshing_lock:
        return code in _refreshing_codes


def _background_refresh_worker(code, data_dir):
    """背景執行緒實際執行的函式：自己開一個新的 KBStore（SQLite connection
    不可跨執行緒共用，每個 request handler／背景執行緒各自開自己的 store
    是既有規範，見本檔案各 do_GET/do_POST 既有寫法）。例外不可讓執行緒
    默默死掉不留痕跡，印到 stderr（比照 log_message() 既有的「安靜但
    留痕」原則）；finally 一定要把 code 從 _refreshing_codes 移除，不管
    成功或失敗，避免 UI 永遠卡在「更新中」。"""
    store = KBStore(data_dir)
    try:
        review_engine.refresh_stock_snapshot(code, store, data_dir=data_dir)
    except Exception as exc:  # 背景執行緒的例外不會被任何人接住，這裡是最後防線
        sys.stderr.write("背景刷新失敗（%s）：%s\n" % (code, exc))
    finally:
        store.close()
        _unmark_refreshing(code)


def trigger_stock_refresh(code, data_dir):
    """觸發背景執行緒刷新單一代碼的股價/估值/Module D檢視快取（「新增
    研究標的」與「PO手動按更新」兩種觸發路徑共用）。立即回傳、不等待
    執行緒完成——呼叫端（do_POST）應該在呼叫這個函式後馬上送出HTTP回應。
    回傳 Thread 物件供測試用 `.join()` 做確定性等待（正式呼叫路徑不應該
    join，只有測試需要等背景工作跑完才能斷言資料庫內容）。"""
    _mark_refreshing(code)
    thread = threading.Thread(
        target=_background_refresh_worker, args=(code, data_dir), daemon=True)
    thread.start()
    return thread


def _is_mcp_or_oauth_probe_path(path):
    """dashboard Basic Auth 要完全跳過的路徑：既有的 `/mcp`、`/mcp/<token>`
    （各自有自己的密鑰驗證），加上 2026-08-01 新發現的一類——手機 Claude
    App 連接器在真正呼叫工具前，會先探測幾個標準OAuth能力探測路徑
    （`/.well-known/oauth-authorization-server`、`/.well-known/
    oauth-protected-resource`、`/register` 等 RFC 8414／RFC 7591 慣例
    路徑），確認這台伺服器有沒有支援OAuth登入流程。這個專案沒有實作
    OAuth，這些路徑「本來就該回404（沒有這個功能）」，但如果讓它們先
    經過 dashboard 的 Basic Auth 檢查，會回401（有登入牆但你進不去）——
    Claude App 把401誤判成「這裡真的有一個OAuth登入服務，但連不上」，
    跳出「Couldn't register with AlphaVibe's sign-in service」的錯誤，
    而不是正確理解成「這個伺服器不支援OAuth，跳過探測直接用既有的路徑
    密鑰認證」。這裡讓這些路徑跳過Basic Auth，落到既有的通用404處理，
    才會回傳語意正確的404而不是401。"""
    return (path == "/mcp" or path.startswith("/mcp/")
            or path.startswith("/.well-known/") or path == "/register")


def _resolve_stock_add_input(raw_input, store, data_dir):
    """清單頁「加入研究」輸入框解析：純數字（見 _STOCK_CODE_RE）直接當
    代碼使用；否則視為股票名稱，重用 stock_alias_resolver.resolve_stock_
    codes() 做名稱→代碼查證（跟 trade_text_parser／trade_ledger_parser
    既有的名稱解析邏輯共用同一套，不重寫一份）。

    回傳 (code, name, error)：成功時 error 為 None；code 為純代碼輸入時，
    嘗試用 finmind_client.get_stock_info() 查一次公司全名（低流量單檔
    查詢，2026-08-01 端對端測試發現：不查名稱會讓詳情頁永遠顯示「尚無
    名稱」、清單頁的名稱搜尋也永遠比對不到——查詢失敗/查無資料時優雅
    降級回 None，不拋例外，比照 finmind_client 既有慣例，不影響代碼
    本身已經確定可用這件事）；走名稱解析成功時 name 回填使用者當初打的
    原始輸入文字。解析失敗（查無代碼）時 code/name 皆為 None，error
    附說明文字。"""
    raw_input = (raw_input or "").strip()
    if not raw_input:
        return None, None, "請輸入股票代碼或名稱"
    if _STOCK_CODE_RE.match(raw_input):
        name = None
        try:
            info = finmind_client.get_stock_info(stock_id=raw_input, data_dir=data_dir)
            stocks = info.get("stocks") or []
            if stocks:
                name = stocks[0].get("stock_name")
        except Exception:
            name = None
        return raw_input, name, None
    resolved, unresolved = stock_alias_resolver.resolve_stock_codes(
        [raw_input], store, data_dir=data_dir, alias_source="dashboard加入研究自動比對")
    if raw_input in resolved:
        return resolved[raw_input], raw_input, None
    return None, None, "查無對應股票代碼：%s，請確認名稱或直接輸入代碼" % raw_input


def _configured_dashboard_token():
    """讀目前生效的 ALPHAVIBE_DASHBOARD_TOKEN。每次呼叫都重讀
    os.environ（不快取成模組常數），比照 `mcp_http_gateway._configured_token()`
    的既有寫法，測試才能用 os.environ 動態切換兩種模式後照樣生效。"""
    return os.environ.get("ALPHAVIBE_DASHBOARD_TOKEN") or None


def _sign_dashboard_cookie(expiry_ts):
    """對 dashboard session cookie 的到期時間戳算 HMAC 簽章。密鑰沿用
    `ALPHAVIBE_DASHBOARD_TOKEN`（不新增環境變數，見模組docstring的單一
    真相來源原則）。呼叫前應確認 token 已設定——未設定時呼叫端不會走到
    這裡（`_require_dashboard_auth()` 在未設定token時已整體fail-open
    放行，不會嘗試簽發cookie；`_dashboard_cookie_valid()` 同樣會提早
    回False，不會呼叫這個函式）。"""
    token = _configured_dashboard_token()
    return hmac.new(token.encode("utf-8"), str(expiry_ts).encode("utf-8"),
                     hashlib.sha256).hexdigest()


def _dashboard_cookie_valid(cookie_header):
    """驗證 `Cookie:` header 裡名為 `alphavibe_session` 的值（格式：
    `<到期時間戳>.<HMAC簽章>`）。簽章錯誤或已過期都視為無效。

    未設定 ALPHAVIBE_DASHBOARD_TOKEN 時直接回 False——這不影響整體
    fail-open行為，因為 `_require_dashboard_auth()` 在未設定token時
    本來就整體放行、不會走到這個檢查（見模組docstring）。"""
    token = _configured_dashboard_token()
    if not token:
        return False
    session_value = None
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == _DASHBOARD_COOKIE_NAME:
            session_value = value
            break
    if not session_value:
        return False
    expiry_str, sep, signature = session_value.partition(".")
    if not sep or not expiry_str or not signature:
        return False
    try:
        expiry_ts = float(expiry_str)
    except ValueError:
        return False
    # 用 compare_digest 做定時比對，避免時序攻擊（比照 mcp_http_gateway._auth_ok()）。
    if not hmac.compare_digest(signature, _sign_dashboard_cookie(expiry_str)):
        return False
    return time.time() < expiry_ts


def _dashboard_password_ok(headers):
    """僅檢查 Basic Auth 密碼是否正確（不含 cookie）。呼叫前應已知
    `ALPHAVIBE_DASHBOARD_TOKEN` 已設定。`headers` 只要求支援 `.get(key)`
    （dict 或 `http.client.HTTPMessage` 皆可，故意不綁定
    BaseHTTPRequestHandler，方便單獨測試）。"""
    auth_header = headers.get("Authorization") or ""
    prefix = "Basic "
    if not auth_header.startswith(prefix):
        return False
    try:
        decoded = base64.b64decode(auth_header[len(prefix):]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _, _, supplied_password = decoded.partition(":")
    # 用 compare_digest 做定時比對，避免時序攻擊（比照 mcp_http_gateway._auth_ok()）。
    return hmac.compare_digest(supplied_password, _configured_dashboard_token())


def _dashboard_auth_ok(headers):
    """Dashboard 驗證檢查（見模組docstring最後兩段）：Basic Auth 密碼
    正確、或帶有效的長效 session cookie，任一成立即通過。`headers` 只
    要求支援 `.get(key)`（dict 或 `http.client.HTTPMessage` 皆可，故意
    不綁定 BaseHTTPRequestHandler，方便單獨測試）。

    未設定 ALPHAVIBE_DASHBOARD_TOKEN 時刻意 fail-open（不擋）——跟
    `mcp_http_gateway._auth_ok()` 對 `ALPHAVIBE_MCP_TOKEN` 未設定時「不
    驗證」的既有慣例一致，理由同樣是：本機開發/測試環境不需要這層保護，
    只有部署到公開網路時才設定這個環境變數啟用它。"""
    token = _configured_dashboard_token()
    if not token:
        return True  # 未設定 token＝這次選擇不驗證（fail-open，見上方docstring）
    if _dashboard_cookie_valid(headers.get("Cookie")):
        return True
    return _dashboard_password_ok(headers)


class ReportHandler(BaseHTTPRequestHandler):
    data_dir = None  # 由 main() 設定
    # 由 _require_dashboard_auth() 視情況設成待送出的 Set-Cookie header值
    # （見該方法docstring）；_send()/_redirect() 若發現非None就一併送出。
    # 每個請求開頭 _require_dashboard_auth() 都會先重置成 None，避免
    # HTTP/1.1 keep-alive下同一個handler instance處理下一個請求時殘留
    # 上一個請求的值。
    _dashboard_cookie_to_set = None

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self._dashboard_cookie_to_set:
            self.send_header("Set-Cookie", self._dashboard_cookie_to_set)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location):
        """FR-058 快速輸入表單送出後用：303（不是常見的302）確保瀏覽器/
        urllib都用GET重新請求Location，不會把表單資料再送一次。"""
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if self._dashboard_cookie_to_set:
            self.send_header("Set-Cookie", self._dashboard_cookie_to_set)
        self.end_headers()

    def _dashboard_flash_redirect(self, message):
        self._redirect("/?flash=" + urllib.parse.quote(message))

    def _read_form(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        return urllib.parse.parse_qs(body.decode("utf-8"))

    def _require_dashboard_auth(self):
        """Dashboard 驗證關卡（見模組docstring）：Basic Auth 密碼正確或
        帶有效 session cookie 皆可通過。回傳 True 代表已通過驗證（或未
        設定token、不需要驗證），呼叫端應繼續往下處理；回傳 False 代表
        已經自行送出 401 回應，呼叫端要立刻 return，不可再處理任何路由
        邏輯。

        2026-07-30新增：這次是靠 Basic Auth 密碼（不是既有cookie）過
        的話，順便把 Set-Cookie header值記進 self._dashboard_cookie_to_set，
        讓 _send()/_redirect() 送出回應時一併帶上——之後這個裝置只靠
        cookie就能過，不用每次都跳Basic Auth密碼框（見模組docstring）。
        已經是靠cookie過的請求不用重新設一次（還在效期內）。"""
        # 每次請求開頭先重置，避免keep-alive連線重用同一個handler
        # instance時，殘留上一個請求設的cookie值到這次回應。
        self._dashboard_cookie_to_set = None
        token = _configured_dashboard_token()
        if not token:
            return True  # 未設定 token＝fail-open，不驗證（見模組docstring）
        if _dashboard_cookie_valid(self.headers.get("Cookie")):
            return True  # 已有效session cookie，不用重新設一次
        if _dashboard_password_ok(self.headers):
            expiry_ts = int(time.time()) + _DASHBOARD_COOKIE_MAX_AGE_SECONDS
            signature = _sign_dashboard_cookie(expiry_ts)
            self._dashboard_cookie_to_set = (
                "%s=%d.%s; Max-Age=%d; Path=/; HttpOnly; Secure; SameSite=Lax"
                % (_DASHBOARD_COOKIE_NAME, expiry_ts, signature,
                   _DASHBOARD_COOKIE_MAX_AGE_SECONDS))
            return True
        body = "需要驗證".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AlphaVibe"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        # /mcp、/mcp/<token> 已各自有獨立的密鑰驗證機制（手機 Claude App
        # 連接器無法處理 Basic Auth 彈窗），這裡的 dashboard 驗證要完全
        # 跳過這兩條路由，不可疊加（見模組docstring最後一段）。
        if not _is_mcp_or_oauth_probe_path(path):
            if not self._require_dashboard_auth():
                return
        if path == "/":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = urllib.parse.parse_qs(query)
            flash = (params.get("flash") or [None])[0]
            store = KBStore(self.data_dir)
            try:
                page = report.render_dashboard(store, flash=flash)
            finally:
                store.close()
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path in CLASSIC_PATHS:
            store = KBStore(self.data_dir)
            try:
                page = report.render(store)
            finally:
                store.close()
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path.endswith("/apple-touch-icon.png") or path == "/apple-touch-icon.png":
            self._send(200, "image/png", report.make_icon_png())
        elif path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok")
        elif path == "/screen":
            self._send(200, "text/html; charset=utf-8",
                       report.render_screen_form().encode("utf-8"))
        elif path == "/market-scan":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = urllib.parse.parse_qs(query)
            framework_id = (params.get("framework") or [None])[0]
            if not framework_id or frameworks.get_framework(framework_id) is None:
                framework_id = frameworks.default_framework_id()
            store = KBStore(self.data_dir)
            try:
                latest = store.get_latest_market_scan(framework_id=framework_id)
            finally:
                store.close()
            page = report.render_market_scan_page(framework_id, latest)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path == "/dashboard/stocks":
            # 個股清單頁（持股＋研究中，2026-08-01新增，見report.py
            # render_stock_list_page()）：篩選/搜尋/分頁皆用GET query
            # string帶狀態，不用session，維持本專案「整頁送出、無JS」的
            # 技術棧原則。
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = urllib.parse.parse_qs(query)
            filter_key = (params.get("filter") or ["all"])[0]
            search_query = (params.get("q") or [""])[0]
            try:
                page = int((params.get("page") or ["1"])[0])
            except ValueError:
                page = 1
            flash = (params.get("flash") or [None])[0]
            store = KBStore(self.data_dir)
            try:
                page_html = report.render_stock_list_page(
                    store, filter_key=filter_key, query=search_query,
                    page=page, flash=flash)
            finally:
                store.close()
            self._send(200, "text/html; charset=utf-8", page_html.encode("utf-8"))
        elif path.startswith("/dashboard/stock/"):
            # 個股詳情頁（2026-08-01新增，見report.py render_stock_detail_
            # page()）：/dashboard/stock/<code>。刻意排在/dashboard/stocks
            # 之後（不會互相誤判——"/dashboard/stocks"不match
            # "/dashboard/stock/"這個含結尾斜線的前綴）。
            code = path[len("/dashboard/stock/"):]
            if not code or "/" in code:
                self._send(404, "text/plain; charset=utf-8",
                           "404：找不到這檔股票".encode("utf-8"))
            else:
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = urllib.parse.parse_qs(query)
                flash = (params.get("flash") or [None])[0]
                store = KBStore(self.data_dir)
                try:
                    page_html = report.render_stock_detail_page(
                        store, code, flash=flash, refreshing=is_refreshing(code))
                finally:
                    store.close()
                self._send(200, "text/html; charset=utf-8", page_html.encode("utf-8"))
        elif path == "/mcp":
            # MCP Streamable HTTP transport 只支援 POST，GET 統一回 405
            # （沿用 mcp_http_gateway.py 獨立執行時的既有行為）。
            status, content_type, body = mcp_http_gateway.mcp_method_not_allowed()
            self._send(status, content_type, body)
        elif path.startswith("/mcp/") and mcp_http_gateway.path_token_matches(
                path[len("/mcp/"):]):
            # URL路徑密鑰驗證（2026-07-30，手機Claude App自訂連接器用，見
            # mcp_http_gateway.path_token_matches() docstring）。密鑰正確
            # 時比照既有 /mcp 的GET行為回405；密鑰錯誤/未設定則落到下面
            # 的通用404（刻意不區分「路徑不存在」與「密鑰錯誤」，見
            # do_POST同一段路由的說明）。
            status, content_type, body = mcp_http_gateway.mcp_method_not_allowed()
            self._send(status, content_type, body)
        else:
            self._send(404, "text/plain; charset=utf-8",
                       "404：檢視頁在 /（或 /report.html）".encode("utf-8"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        # 同 do_GET：/mcp、/mcp/<token> 有自己的密鑰驗證機制，dashboard
        # Basic Auth 要完全跳過這兩條路由（見模組docstring最後一段）。
        if not _is_mcp_or_oauth_probe_path(path):
            if not self._require_dashboard_auth():
                return
        if path == "/mcp":
            # MCP Streamable HTTP transport（手機 Claude App 自訂連接器）。
            # 邏輯完全來自 mcp_http_gateway.handle_mcp_post()，這裡只是
            # 讀 body 轉手過去，用既有的 self._send() 送出回應（不重新
            # 發明一套送出邏輯）。
            length = int(self.headers.get("Content-Length") or 0)
            body_bytes = self.rfile.read(length) if length else b""
            status, content_type, body = mcp_http_gateway.handle_mcp_post(
                self.headers, body_bytes, data_dir=self.data_dir)
            self._send(status, content_type, body)
            return
        if path.startswith("/mcp/"):
            # URL路徑密鑰驗證（2026-07-30，手機Claude App自訂連接器用）：
            # Claude App標準連接器設定UI只有OAuth一個驗證選項，沒有自訂
            # header欄位可以填Authorization Bearer，所以另外開這條把密鑰
            # 放進URL路徑本身的路由，供公開網路呼叫。密鑰驗證邏輯見
            # mcp_http_gateway.path_token_matches()（跟既有/mcp的
            # header驗證共用同一把ALPHAVIBE_MCP_TOKEN，fail-closed）。
            #
            # 無論密鑰是否正確都先讀完body（比照本檔其他POST路由的既有
            # 寫法），避免keep-alive連線上殘留未讀的body byte把下一個
            # 請求解析搞壞。
            token = path[len("/mcp/"):]
            length = int(self.headers.get("Content-Length") or 0)
            body_bytes = self.rfile.read(length) if length else b""
            if mcp_http_gateway.path_token_matches(token):
                # handle_mcp_post()內部還會再跑一次header-based的
                # _auth_ok()（它不知道呼叫端是走哪條路由驗證的）。這裡的
                # request原本沒有Authorization header（Claude App走的就是
                # 這條路由，才需要它），所以合成一份等效的
                # 「Authorization: Bearer <token>」header轉傳進去，讓
                # handle_mcp_post()的內部檢查用同一把已驗證過的密鑰通過
                # ——密鑰本身已經被path_token_matches()用compare_digest
                # 驗證過，這裡只是把驗證結果轉換成handle_mcp_post()認得
                # 的格式，不是繞過驗證、也沒有另外實作一套JSON-RPC處理
                # 邏輯（那些仍完全由handle_mcp_post()負責）。
                headers = dict(self.headers.items())
                headers["Authorization"] = "Bearer " + token
                status, content_type, body = mcp_http_gateway.handle_mcp_post(
                    headers, body_bytes, data_dir=self.data_dir)
                self._send(status, content_type, body)
            else:
                # 密鑰錯誤或未設定：回通用404（不是401/403）——不知道
                # 密鑰的呼叫者應該以為這個路徑根本不存在，不能透露「這裡
                # 有東西但你沒授權」這種訊號。訊息字串刻意跟本方法最下面
                # 的「未知路徑」404完全一致，讓兩種情況無法被外部區分。
                self._send(404, "text/plain; charset=utf-8",
                           "404：僅支援 POST /mcp、/screen、/market-scan、/market-scan/track、"
                           "/dashboard/watchlist、/dashboard/trade、/dashboard/laoyutou、"
                           "/dashboard/tradeledger、/dashboard/tradecsv、"
                           "/dashboard/holdings/preview、/dashboard/holdings/confirm、"
                           "/dashboard/stocks/add、/dashboard/stock/<code>/refresh 或 "
                           "/dashboard/stock/<code>/note"
                           .encode("utf-8"))
            return
        if path == "/screen":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            codes_text = (form.get("codes") or [""])[0]
            codes = screener.parse_codes(codes_text)
            if not codes:
                page = report.render_screen_form(error="請至少輸入一個股票代碼")
                self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
                return
            result = screener.screen_stocks(codes, data_dir=self.data_dir)
            page = report.render_screen_results(result)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        if path == "/market-scan":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            framework_id = (form.get("framework") or [None])[0]
            if not framework_id or frameworks.get_framework(framework_id) is None:
                framework_id = frameworks.default_framework_id()
            result = market_scan.run_scan(
                framework_id, data_dir=self.data_dir, trigger_source="manual")
            store = KBStore(self.data_dir)
            try:
                if "error" not in result:
                    store.save_market_scan_run(
                        framework_id, "manual", result["results"],
                        result["candidate_count"],
                        market_errors=result["market_errors"],
                        total_scanned=result["total_scanned"],
                        benchmark={"window_drawdown_pct": result.get("benchmark_drawdown_pct"),
                                  "error": result.get("benchmark_error")})
                latest = store.get_latest_market_scan(framework_id=framework_id)
            finally:
                store.close()
            page = report.render_market_scan_page(
                framework_id, latest, error=result.get("error"))
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        if path == "/market-scan/track":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            code = (form.get("code") or [""])[0]
            stance = (form.get("stance") or [""])[0]
            if stance not in ("觀察", "偏多", "偏空"):
                stance = "觀察"
            overwrite = (form.get("overwrite") or [""])[0] == "1"
            try:
                run_id = int((form.get("run_id") or [""])[0])
            except ValueError:
                run_id = None

            store = KBStore(self.data_dir)
            try:
                run = store.get_market_scan_run(run_id) if run_id is not None else None
                result_row = store.get_market_scan_result(run_id, code) if run_id is not None else None
                if run is None or result_row is None or not code:
                    page = report.render_track_error_page(
                        "找不到這筆候選資料，可能掃描紀錄已更新，請回列表重新操作。")
                    self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
                    return
                framework = frameworks.get_framework(run["framework_id"])
                reason = report.compose_market_scan_track_reason(
                    result_row, framework or {"label": run["framework_id"]}, run["run_at"])
                saved = store.save_stance(
                    code, stance, name=result_row.get("name"), reason=reason,
                    source_ref="market_scan/run_%d" % run_id, overwrite=overwrite)
                if saved.get("conflict") and not saved.get("saved"):
                    page = report.render_track_conflict_page(
                        code, result_row.get("name"), stance, reason,
                        saved["existing"], run_id)
                else:
                    page = report.render_track_result_page(
                        saved, code, result_row.get("name"), stance)
            finally:
                store.close()
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        if path == "/dashboard/watchlist":
            form = self._read_form()
            code = (form.get("code") or [""])[0].strip()
            name = (form.get("name") or [""])[0].strip() or None
            if not code:
                self._dashboard_flash_redirect("⚠️ 加自選股失敗：代碼為必填")
                return
            store = KBStore(self.data_dir)
            try:
                store.save_stance(code, "觀察", name=name, source_ref="dashboard快速輸入")
            finally:
                store.close()
            self._dashboard_flash_redirect("已加入自選股：%s" % code)
            return
        if path == "/dashboard/trade":
            form = self._read_form()
            code = (form.get("code") or [""])[0].strip()
            name = (form.get("name") or [""])[0].strip() or None
            action = (form.get("action") or [""])[0].strip()
            shares_raw = (form.get("shares") or [""])[0].strip()
            price_raw = (form.get("price") or [""])[0].strip()
            date = (form.get("date") or [""])[0].strip()
            add_sequence_raw = (form.get("add_sequence") or [""])[0].strip()
            missing = [label for label, v in
                       (("代碼", code), ("買賣", action), ("股數", shares_raw),
                        ("價格", price_raw), ("日期", date)) if not v]
            if missing:
                self._dashboard_flash_redirect(
                    "⚠️ 記交易失敗：缺少必填欄位（%s）" % "、".join(missing))
                return
            try:
                shares = float(shares_raw)
                price = float(price_raw)
                add_sequence = int(add_sequence_raw) if add_sequence_raw else None
            except ValueError:
                self._dashboard_flash_redirect("⚠️ 記交易失敗：股數／價格／加碼序號格式錯誤")
                return
            store = KBStore(self.data_dir)
            try:
                store.save_trade_ledger_entry(
                    code, name, action, shares, price, date,
                    add_sequence=add_sequence, source_ref="dashboard快速輸入")
            except ValueError as exc:
                self._dashboard_flash_redirect("⚠️ 記交易失敗：%s" % exc)
                return
            finally:
                store.close()
            self._dashboard_flash_redirect("已記錄交易：%s %s" % (code, action))
            return
        if path == "/dashboard/laoyutou":
            # 2026-07-30：改用格式化文字貼入＋trade_text_parser 批次解析
            # （FR-044週邊工具），取代原本逐欄位手填的表單——PO反饋手機上
            # 一格一格輸入太慢，他固定格式貼一大段，格式規則見
            # trade_text_parser.py 模組docstring。
            form = self._read_form()
            text = (form.get("text") or [""])[0]
            if not text.strip():
                self._dashboard_flash_redirect("⚠️ 貼老芋頭進出失敗：內容是空的")
                return
            parsed = trade_text_parser.parse_laoyutou_trade_text(text)
            store = KBStore(self.data_dir)
            try:
                result = trade_text_parser.resolve_and_save_laoyutou_trades(
                    parsed, store, data_dir=self.data_dir)
            finally:
                store.close()
            msg_parts = ["已存入 %d 筆老芋頭交易（%s）"
                        % (len(result["saved"]), parsed.get("date") or "日期未解析")]
            if result["unresolved_names"]:
                names = "、".join(u["name"] for u in result["unresolved_names"])
                msg_parts.append("⚠️ %d 筆代碼查無比對（%s），未存入，"
                                 "請補stock_aliases後重貼這幾筆"
                                 % (len(result["unresolved_names"]), names))
            if result["unparsed_lines"]:
                msg_parts.append("⚠️ %d 行格式無法解析，已略過"
                                 % len(result["unparsed_lines"]))
            self._dashboard_flash_redirect("；".join(msg_parts))
            return
        if path == "/dashboard/tradeledger":
            # FR-056：PO自己的交易明細表批次貼入，直接處理不需要像庫存帳單
            # 那樣兩步驟預覽確認（這是PO自己的交易記錄，直接處理即可，見
            # 派工指示）。格式規則見 trade_ledger_parser.py 模組docstring。
            form = self._read_form()
            text = (form.get("text") or [""])[0]
            if not text.strip():
                self._dashboard_flash_redirect("⚠️ 貼交易明細表失敗：內容是空的")
                return
            parsed = trade_ledger_parser.parse_trade_ledger_text(text)
            store = KBStore(self.data_dir)
            try:
                result = trade_ledger_parser.resolve_and_save_trade_ledger(
                    parsed, store, data_dir=self.data_dir)
            finally:
                store.close()
            msg_parts = ["已存入 %d 筆交易明細" % len(result["saved"])]
            if result.get("duplicates_skipped"):
                msg_parts.append("另有 %d 筆偵測為重複（委託書號已存在）已跳過"
                                 % len(result["duplicates_skipped"]))
            if result["unresolved_names"]:
                names = "、".join(u["name"] for u in result["unresolved_names"])
                msg_parts.append("⚠️ %d 筆代碼查無比對（%s），未存入，"
                                 "請補stock_aliases後重貼這幾筆"
                                 % (len(result["unresolved_names"]), names))
            if result["unparsed_lines"]:
                msg_parts.append("⚠️ %d 行格式無法解析，已略過"
                                 % len(result["unparsed_lines"]))
            self._dashboard_flash_redirect("；".join(msg_parts))
            return
        if path == "/dashboard/tradecsv":
            # 國泰證券App「已成交」CSV格式對帳單批次貼入（跟上面的
            # /dashboard/tradeledger同精神：直接處理不需要像庫存帳單那樣
            # 兩步驟預覽確認，這是PO自己的交易記錄）。格式規則見
            # trade_ledger_parser.py 模組docstring
            # parse_trade_csv_text() 那段。
            form = self._read_form()
            text = (form.get("text") or [""])[0]
            if not text.strip():
                self._dashboard_flash_redirect("⚠️ 貼CSV對帳單失敗：內容是空的")
                return
            parsed = trade_ledger_parser.parse_trade_csv_text(text)
            store = KBStore(self.data_dir)
            try:
                result = trade_ledger_parser.resolve_and_save_trade_ledger(
                    parsed, store, data_dir=self.data_dir)
            finally:
                store.close()
            msg_parts = ["已存入 %d 筆交易明細" % len(result["saved"])]
            if result.get("duplicates_skipped"):
                msg_parts.append("另有 %d 筆偵測為重複（委託書號已存在）已跳過"
                                 % len(result["duplicates_skipped"]))
            if result["unresolved_names"]:
                names = "、".join(u["name"] for u in result["unresolved_names"])
                msg_parts.append("⚠️ %d 筆代碼查無比對（%s），未存入，"
                                 "請補stock_aliases後重貼這幾筆"
                                 % (len(result["unresolved_names"]), names))
            if result["unparsed_lines"]:
                msg_parts.append("⚠️ %d 行格式無法解析，已略過"
                                 % len(result["unparsed_lines"]))
            self._dashboard_flash_redirect("；".join(msg_parts))
            return
        if path == "/dashboard/holdings/preview":
            # 貼庫存帳單快速輸入第一步：解析＋跟上次快照比對，只渲染
            # 預覽頁，不寫入資料庫（holdings_parser docstring明講的人工
            # 確認關卡，第二步 /dashboard/holdings/confirm 才真的存入）。
            form = self._read_form()
            text = (form.get("text") or [""])[0]
            if not text.strip():
                self._dashboard_flash_redirect("⚠️ 貼庫存帳單失敗：內容是空的")
                return
            parsed = holdings_parser.parse_holdings_report(text)
            store = KBStore(self.data_dir)
            try:
                previous_holdings = store.get_holdings()
            finally:
                store.close()
            page = report.render_holdings_preview(parsed, previous_holdings)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        if path == "/dashboard/holdings/confirm":
            # 第二步：從預覽頁隱藏欄位還原解析結果（JSON），真的呼叫
            # save_holdings。隱藏欄位在render_holdings_preview()用esc()
            # 做HTML跳脫，這裡收到的是urlencode/parse_qs解碼後的原始JSON
            # 文字，直接json.loads即可，不需要另外html.unescape。
            form = self._read_form()
            rows_json = (form.get("rows_json") or [""])[0]
            try:
                rows = json.loads(rows_json) if rows_json else []
            except ValueError:
                rows = None
            if not rows:
                self._dashboard_flash_redirect(
                    "⚠️ 貼庫存帳單失敗：沒有可存入的資料，請回上一步重新貼上")
                return
            store = KBStore(self.data_dir)
            try:
                result = store.save_holdings(
                    rows, source_ref="dashboard貼庫存帳單快速輸入")
            except ValueError as exc:
                self._dashboard_flash_redirect("⚠️ 貼庫存帳單失敗：%s" % exc)
                return
            finally:
                store.close()
            self._dashboard_flash_redirect("已存入 %d 檔持股快照" % result["count"])
            return
        if path == "/dashboard/stocks/add":
            # 清單頁「加入研究」：解析代碼→save_stance註冊「研究中」→
            # 觸發背景刷新（見trigger_stock_refresh()）→導向新增的那檔
            # 詳情頁（2026-08-01新增，見派工說明需求#3）。
            form = self._read_form()
            raw_input = (form.get("input") or [""])[0]
            store = KBStore(self.data_dir)
            try:
                code, name, error = _resolve_stock_add_input(
                    raw_input, store, self.data_dir)
                if error:
                    self._redirect(
                        "/dashboard/stocks?flash=" + urllib.parse.quote("⚠️ " + error))
                    return
                save_result = store.save_stance(
                    code, "研究中", name=name, source_ref="dashboard加入研究")
            finally:
                store.close()
            # save_result["saved"]為False時代表既有立場衝突（FR-013/018保護，
            # 見save_stance docstring）——不強制覆蓋既有立場，這裡只是想去看
            # 這檔股票，直接導向既有詳情頁即可，不需要再觸發一次背景刷新
            # （該代碼理論上早就有快取資料）。
            if save_result.get("saved"):
                trigger_stock_refresh(code, self.data_dir)
            self._redirect("/dashboard/stock/" + urllib.parse.quote(code, safe=""))
            return
        if path.startswith("/dashboard/stock/") and path.endswith("/refresh"):
            # 詳情頁「更新」按鈕：觸發背景刷新，立即303轉址回詳情頁並附
            # flash提示，不等待背景執行緒完成（見trigger_stock_refresh()
            # docstring／派工說明「手動更新是背景處理，不會卡住PO繼續用
            # AlphaVibe」）。
            code = path[len("/dashboard/stock/"):-len("/refresh")]
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)  # 沒有表單欄位要讀，純粹清空body避免殘留
            if not code:
                self._send(404, "text/plain; charset=utf-8",
                           "404：找不到這檔股票".encode("utf-8"))
                return
            trigger_stock_refresh(code, self.data_dir)
            self._redirect(
                "/dashboard/stock/%s?flash=%s"
                % (urllib.parse.quote(code, safe=""),
                   urllib.parse.quote("已開始背景更新，稍後重新整理查看最新結果")))
            return
        if path.startswith("/dashboard/stock/") and path.endswith("/note"):
            # 詳情頁「心得與留言」表單：寫入 comments 表（source_tag區分
            # 買進理由/心得/交易備註），跟Claude App對話裡由AI寫入的是
            # 同一張表、同一份資料（見派工說明需求#4）。
            code = path[len("/dashboard/stock/"):-len("/note")]
            form = self._read_form()
            body_text = (form.get("body") or [""])[0].strip()
            source_tag = (form.get("source_tag") or [""])[0].strip()
            if source_tag not in ("買進理由", "心得", "交易備註"):
                source_tag = "心得"
            if not code:
                self._send(404, "text/plain; charset=utf-8",
                           "404：找不到這檔股票".encode("utf-8"))
                return
            if not body_text:
                msg = "⚠️ 留言失敗：內容不可為空"
            else:
                store = KBStore(self.data_dir)
                try:
                    store.save_comment(body_text, source_tag, symbols=code,
                                       source_ref="dashboard個股頁留言")
                finally:
                    store.close()
                msg = "已存入留言（%s）" % source_tag
            self._redirect("/dashboard/stock/%s?flash=%s"
                           % (urllib.parse.quote(code, safe=""), urllib.parse.quote(msg)))
            return
        self._send(404, "text/plain; charset=utf-8",
                   "404：僅支援 POST /mcp、/screen、/market-scan、/market-scan/track、"
                   "/dashboard/watchlist、/dashboard/trade、/dashboard/laoyutou、"
                   "/dashboard/tradeledger、/dashboard/tradecsv、"
                   "/dashboard/holdings/preview、/dashboard/holdings/confirm、"
                   "/dashboard/stocks/add、/dashboard/stock/<code>/refresh 或 "
                   "/dashboard/stock/<code>/note"
                   .encode("utf-8"))

    def log_message(self, fmt, *args):  # 安靜一點，只留到 stderr
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main(argv=None):
    parser = argparse.ArgumentParser(description="即時渲染知識庫檢視 server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    ReportHandler.data_dir = os.path.abspath(
        args.data_dir or os.environ.get("ALPHAVIBE_DATA_DIR")
        or os.path.join(here, "..", "data"))

    server = ThreadingHTTPServer(("0.0.0.0", args.port), ReportHandler)
    print("檢視 server 啟動：http://localhost:%d/（資料目錄 %s）"
          % (server.server_address[1], ReportHandler.data_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
