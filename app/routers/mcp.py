"""MCP 連接器路由：POST /mcp、POST /mcp/{token}。

規劃文件第5節「逐一遷移既有功能」的第一項（見
docs/spec-intake/alphavibe/roadmap.md Q-046）：從
poc/kb-mcp/report_server.py 的 do_POST() 遷移過來。選 MCP 當第一個遷移
對象，是因為底層邏輯（mcp_http_gateway.handle_mcp_post()）完全不用改，
適合拿來驗證新架構「路由層轉手給既有純函式」這個模式走不走得通。

**這裡刻意不做的事**：
- 不改 poc/kb-mcp/mcp_http_gateway.py 的任何一行，只 import 呼叫
  handle_mcp_post()／path_token_matches()／mcp_method_not_allowed()
  （比照 app/deps.py 對 kb_store.py 的既有作法：sys.path.insert 後直接
  import，邏輯完全不重寫）
- 不遷移 GET /mcp、GET /mcp/{token}：既有 report_server.py 的 GET 分支
  只是回 405（MCP Streamable HTTP transport 只支援 POST），這一步先只做
  POST；之後要補 GET 是低風險的獨立小工作
- 不遷移 /mcp 以外的其他既有路由（/screen、/dashboard/* 等留給下一步）

**Basic Auth 白名單**：這兩條路由不受 app.deps.DashboardAuthMiddleware
管制，見 app/deps.py 的 `_is_mcp_path()`（比照 report_server.py 的
`_is_mcp_or_oauth_probe_path()`）——MCP 自己的 token 機制
（mcp_http_gateway._auth_ok() / path_token_matches()，走 Authorization
header 或 URL 路徑密鑰）才是它的把關方式，兩層認證不可疊加，理由同
report_server.py 模組 docstring 最後一段。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Request, Response

# app/routers/mcp.py 在 AlphaVibe/app/routers/ 底下，往上兩層是 AlphaVibe/，
# 再進 poc/kb-mcp/ 才是 mcp_http_gateway.py 所在目錄。獨立做一次
# sys.path.insert（跟 app/deps.py 同一套 idempotent 寫法），讓這個檔案
# 不依賴 app/deps.py 是否已先被 import 過，避免對 import 順序產生隱性依賴。
_KB_MCP_DIR = Path(__file__).resolve().parent.parent.parent / "poc" / "kb-mcp"
if str(_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_KB_MCP_DIR))

import mcp_http_gateway  # noqa: E402  (需先插入 sys.path 才能 import)

from app.deps import _resolve_data_dir  # noqa: E402

router = APIRouter()

# 密鑰錯誤／未設定時的通用 404 文案，逐字比照 report_server.py do_POST()
# 同一段程式碼——刻意跟「未知路徑」的 404 訊息完全一致，讓不知道密鑰的
# 呼叫者無法從回應內容分辨「這裡有 MCP 端點但密鑰錯」跟「這個路徑根本
# 不存在」，維持既有的 fail-closed 行為。
_UNKNOWN_PATH_404 = (
    "404：僅支援 POST /mcp、/screen、/market-scan、/market-scan/track、"
    "/dashboard/watchlist、/dashboard/trade、/dashboard/laoyutou、"
    "/dashboard/tradeledger、/dashboard/tradecsv、"
    "/dashboard/holdings/preview、/dashboard/holdings/confirm、"
    "/dashboard/stocks/add、/dashboard/stock/<code>/refresh 或 "
    "/dashboard/stock/<code>/note"
).encode("utf-8")


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    """比照 report_server.py do_POST() 的 `path == "/mcp"` 分支：讀 raw
    body bytes，把 headers／body 原封不動轉手給 handle_mcp_post()，不在
    這裡重新實作驗證或 JSON-RPC 處理邏輯。`request.headers` 是 Starlette
    的 Headers 物件，`.get(key)` 為 case-insensitive，滿足
    handle_mcp_post() 對 headers 參數「dict-like，只用到 .get()」的要求。
    """
    body_bytes = await request.body()
    status, content_type, body = mcp_http_gateway.handle_mcp_post(
        request.headers, body_bytes, data_dir=_resolve_data_dir())
    return Response(content=body, status_code=status, media_type=content_type)


@router.post("/mcp/{token}")
async def mcp_post_with_token(token: str, request: Request) -> Response:
    """比照 report_server.py do_POST() 的 `path.startswith("/mcp/")` 分支：
    URL 路徑密鑰驗證（手機 Claude App 自訂連接器用，因為該連接器設定 UI
    沒有自訂 header 欄位可填 Authorization，詳見
    mcp_http_gateway.path_token_matches() docstring）。

    密鑰正確時，比照既有邏輯合成一份等效的
    `Authorization: Bearer <token>` header 轉傳進 handle_mcp_post()——
    密鑰本身已經被 path_token_matches() 用 compare_digest 驗證過，這裡
    只是把驗證結果轉換成 handle_mcp_post() 認得的格式，不是繞過驗證、也
    沒有另外實作一套 JSON-RPC 處理邏輯。

    密鑰錯誤或未設定時回通用 404（不是 401/403）——不知道密鑰的呼叫者
    應該以為這個路徑根本不存在，理由同 report_server.py 同一段程式碼的
    說明。無論密鑰是否正確都先讀完 body，避免影響同一連線後續請求
    （FastAPI/Starlette 每個 request 各自管理 body，不像
    BaseHTTPRequestHandler 需要手動讀完避免殘留 byte，但仍照抄既有作法
    先讀出 body_bytes 保持行為一致）。
    """
    body_bytes = await request.body()
    if mcp_http_gateway.path_token_matches(token):
        headers = dict(request.headers.items())
        headers["Authorization"] = "Bearer " + token
        status, content_type, body = mcp_http_gateway.handle_mcp_post(
            headers, body_bytes, data_dir=_resolve_data_dir())
        return Response(content=body, status_code=status, media_type=content_type)
    return Response(
        content=_UNKNOWN_PATH_404,
        status_code=404,
        media_type="text/plain; charset=utf-8",
    )
