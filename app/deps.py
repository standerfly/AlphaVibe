"""共用 FastAPI dependency：KBStore 連線、Dashboard 認證。

**這個檔案不重寫、不複製 poc/kb-mcp/kb_store.py 的任何邏輯**——直接
import 既有的 KBStore，確保新舊兩邊（poc/kb-mcp/report_server.py 與
這裡）共用同一份 SQLite 存取邏輯與同一個資料庫檔案。做法比照
report_server.py 開頭的 `sys.path.insert(...)`。

Dashboard 認證（Basic Auth 密碼 or 簽章 cookie）整套邏輯也是照搬
report_server.py 的 `_configured_dashboard_token` /
`_sign_dashboard_cookie` / `_dashboard_cookie_valid` /
`_dashboard_password_ok` / `_dashboard_auth_ok`——只把「讀 headers」的
介面換成 Starlette 的 Request/Headers，行為（含未設定 token 時的
fail-open）完全不變，照抄不改邏輯。

限制：這個 app/ 目錄下的檔案要維持 Python 3.9 語法相容（這台機器只有
3.9.6），用 `from __future__ import annotations` 讓 PEP 604 的
`X | None` 註記可以安全使用（見 harness／AlphaVibe 兩邊 CLAUDE.md 教訓
紀錄）。但 app/ 目錄本身已被 Q-046 授權可以用 FastAPI 這類外部套件，
不再受 kb_store.py「僅標準庫」的限制。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from typing import Iterator

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

# ---------------------------------------------------------------------------
# 資料庫連線：直接 import poc/kb-mcp/kb_store.py 的 KBStore
# ---------------------------------------------------------------------------

# app/deps.py 在 AlphaVibe/app/ 底下，往上一層是 AlphaVibe/，
# 再進 poc/kb-mcp/ 才是 kb_store.py 所在目錄。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

from kb_store import KBStore  # noqa: E402  (需先插入 sys.path 才能 import)


_PRODUCTION_DATA_DIR = os.path.abspath(str(_KB_MCP_DIR / ".." / "data"))


def _resolve_data_dir() -> str:
    """資料目錄解析：`ALPHAVIBE_DATA_DIR` 環境變數**必須明確設定**，
    不再有隱性預設值。

    2026-08-22 教訓：舊版在沒設定時會 silently fallback 到
    poc/kb-mcp/../data（跟正式 report_server.py 用的是同一個
    alphavibe.db）。測試埠 8090 啟動時忘了設這個環境變數，實際上直接
    寫進了正式資料庫，污染了 5 張新增的資產表（asset_pockets 等），
    事後才發現並清除，詳見
    docs/spec-intake/alphavibe/supporting-artifacts/alphavibe-verify-report.md
    （若尚未搬移，暫存於 harness 專案 scratchpad）。

    改成沒設定就直接拒絕啟動（fail loud）：測試/開發環境要指向獨立的
    複製資料庫；未來這個 app/ 若要接手成為正式服務，也要在 launchd
    plist 明確加上這個環境變數指向 poc/data/——不再允許「忘記設定＝
    悄悄寫錯地方」這種可能性。"""
    env_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not env_dir:
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 未設定。這個環境變數現在是必要的，"
            "不再有隱性預設值——2026-08-22 曾因為隱性預設導致測試埠"
            "意外寫進正式資料庫（poc/data/alphavibe.db）。"
            "測試/開發：指向一份獨立複製出來的資料庫目錄。"
            "正式部署：明確指向 " + _PRODUCTION_DATA_DIR
        )
    resolved = os.path.abspath(env_dir)
    if resolved == _PRODUCTION_DATA_DIR and os.environ.get(
        "ALPHAVIBE_ALLOW_PRODUCTION_WRITE") != "1":
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 指向正式資料庫路徑（" + _PRODUCTION_DATA_DIR
            + "），但沒有設定 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 明確確認。"
            "這是為了避免重蹈 2026-08-22 的覆轍——如果你是要正式切換"
            "服務，請明確加上這個環境變數；如果是要測試，請改指向"
            "獨立的複製資料庫，不要指向這個路徑。"
        )
    return resolved


def get_kb_store() -> Iterator[KBStore]:
    """FastAPI dependency：每個 request 各自建立一個 KBStore（各自開一條
    sqlite3 連線），request 結束後關閉。

    不可用全域單例——sqlite3 連線不可跨執行緒共用，這點跟
    report_server.py 每個路由處理時都現開 `KBStore(self.data_dir)`、
    處理完 `store.close()` 的既有模式一致，只是這裡透過 FastAPI 的
    dependency injection（yield 型 dependency，在 response 送出後自動
    執行 finally 區塊）達成同樣效果。
    """
    store = KBStore(_resolve_data_dir())
    try:
        yield store
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Dashboard 認證：Basic Auth 密碼 或 HMAC-SHA256 簽章 cookie，任一成立即通過
# ---------------------------------------------------------------------------

_DASHBOARD_COOKIE_NAME = "alphavibe_session"
_DASHBOARD_COOKIE_MAX_AGE_SECONDS = 2592000  # 30 天，與 report_server.py 一致

# 這一步的骨架只有 /api/healthz 需要跳過認證（比照現有 /healthz 的定位：
# 健康檢查給 uptime/monitoring 探測用，不應該被登入牆擋住）。
_AUTH_EXEMPT_PATHS = {"/api/healthz"}


def _is_mcp_path(path: str) -> bool:
    """MCP 連接器路徑白名單判斷，比照 poc/kb-mcp/report_server.py 的
    `_is_mcp_or_oauth_probe_path()`——`/mcp`、`/mcp/<token>` 各自有自己的
    密鑰驗證機制（見 app/routers/mcp.py 呼叫的
    mcp_http_gateway._auth_ok() / path_token_matches()），不可疊加這裡的
    dashboard Basic Auth，否則手機 Claude App 連接器（無法處理 Basic
    Auth 彈窗）會連不上。

    這一步只遷移 MCP 本身，刻意不含原函式裡的 OAuth 探測路徑白名單
    （`/.well-known/*`、`/register`）——這個 app/ 骨架目前沒有對應的
    處理邏輯，那組白名單存在的意義（把 401 誤判成「這裡有洩漏的 OAuth
    服務」導正回 404）此刻不適用；之後真的要遷移那段行為時再一併補上。
    """
    return path == "/mcp" or path.startswith("/mcp/")


def _configured_dashboard_token() -> str | None:
    """讀目前生效的 ALPHAVIBE_DASHBOARD_TOKEN。每次呼叫都重讀
    os.environ（不快取成模組常數），比照 report_server.py 同名函式的
    既有寫法，方便用環境變數動態切換兩種模式。"""
    return os.environ.get("ALPHAVIBE_DASHBOARD_TOKEN") or None


def _sign_dashboard_cookie(expiry_ts) -> str:
    """對 session cookie 的到期時間戳算 HMAC 簽章。密鑰沿用
    ALPHAVIBE_DASHBOARD_TOKEN（不新增環境變數，單一真相來源）。呼叫前
    應確認 token 已設定。"""
    token = _configured_dashboard_token()
    return hmac.new(token.encode("utf-8"), str(expiry_ts).encode("utf-8"),
                     hashlib.sha256).hexdigest()


def _dashboard_cookie_valid(cookie_header: str | None) -> bool:
    """驗證 Cookie header 裡名為 alphavibe_session 的值
    （格式：`<到期時間戳>.<HMAC簽章>`）。簽章錯誤或已過期都視為無效。
    未設定 ALPHAVIBE_DASHBOARD_TOKEN 時直接回 False（不影響整體
    fail-open，因為呼叫端在未設定 token 時本來就不會走到這裡）。"""
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
    # 用 compare_digest 做定時比對，避免時序攻擊。
    if not hmac.compare_digest(signature, _sign_dashboard_cookie(expiry_str)):
        return False
    return time.time() < expiry_ts


def _dashboard_password_ok(headers) -> bool:
    """僅檢查 Basic Auth 密碼是否正確（不含 cookie）。呼叫前應已知
    ALPHAVIBE_DASHBOARD_TOKEN 已設定。`headers` 只要求支援 `.get(key)`
    （Starlette 的 Headers 物件是 case-insensitive，`.get("Authorization")`
    可正確取到）。"""
    auth_header = headers.get("Authorization") or ""
    prefix = "Basic "
    if not auth_header.startswith(prefix):
        return False
    try:
        decoded = base64.b64decode(auth_header[len(prefix):]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _, _, supplied_password = decoded.partition(":")
    # 用 compare_digest 做定時比對，避免時序攻擊。
    return hmac.compare_digest(supplied_password, _configured_dashboard_token())


def _dashboard_auth_ok(headers) -> bool:
    """Dashboard 驗證檢查：Basic Auth 密碼正確、或帶有效的長效 session
    cookie，任一成立即通過。

    未設定 ALPHAVIBE_DASHBOARD_TOKEN 時刻意 fail-open（不擋）——這是
    report_server.py 的既有行為，本機開發/測試環境不需要這層保護，
    只有部署到公開網路時才設定這個環境變數啟用它，這裡照抄不改邏輯。
    """
    token = _configured_dashboard_token()
    if not token:
        return True  # 未設定 token＝fail-open，不驗證
    if _dashboard_cookie_valid(headers.get("Cookie")):
        return True
    return _dashboard_password_ok(headers)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    """全域 Basic Auth／簽章 cookie 驗證中介層，掛在 app 層級讓所有路由
    預設都要過這關（`_AUTH_EXEMPT_PATHS` 內的路徑除外）。

    取捨：這裡選 middleware 而不是逐路由 `Depends(...)`，是因為
    report_server.py 原本的設計就是「所有路徑預設要驗證、少數路徑
    明確排除」（`_is_mcp_or_oauth_probe_path` 的 skip-path 概念），
    middleware 天然符合這種「預設全擋、白名單排除」的形狀；若改用
    per-route Depends，之後每新增一支路由都要記得手動加，容易漏掛，
    這在往後遷移 /screen、/dashboard/* 等一大批既有路由時風險更高。

    密碼驗證通過（非既有 cookie 通過）時，比照 report_server.py 的
    `_require_dashboard_auth()`，順便在回應簽發長效 session cookie，
    之後同一瀏覽器只靠 cookie 就能過，不用每次都跳 Basic Auth 密碼框。
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _AUTH_EXEMPT_PATHS or _is_mcp_path(request.url.path):
            return await call_next(request)

        token = _configured_dashboard_token()
        if not token:
            return await call_next(request)

        if _dashboard_cookie_valid(request.headers.get("Cookie")):
            return await call_next(request)

        if _dashboard_password_ok(request.headers):
            expiry_ts = int(time.time()) + _DASHBOARD_COOKIE_MAX_AGE_SECONDS
            signature = _sign_dashboard_cookie(expiry_ts)
            response: Response = await call_next(request)
            response.headers["set-cookie"] = (
                "%s=%d.%s; Max-Age=%d; Path=/; HttpOnly; Secure; SameSite=Lax"
                % (_DASHBOARD_COOKIE_NAME, expiry_ts, signature,
                   _DASHBOARD_COOKIE_MAX_AGE_SECONDS)
            )
            return response

        return PlainTextResponse(
            "需要驗證",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="AlphaVibe"'},
        )
