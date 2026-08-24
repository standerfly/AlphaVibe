"""AlphaVibe app 業務路由套件。

Phase 2 重寫第一步（規劃文件第5節 Step 1）只建骨架、驗證身分機制，不遷移
任何既有路由。第5節 Step 2 起逐一遷移既有功能：`mcp.py`（/mcp、
/mcp/{token}）、`screen.py`（/api/screen）、`market_scan.py`
（/api/market-scan）、`holdings.py`（/api/holdings，/dashboard/stocks
讀取端）依序完成。之後遷移個股詳情頁、表單端點等既有功能時，比照同樣
模式新增對應的 router 模組，並在 app/main.py 用 app.include_router() 掛上。
"""
from __future__ import annotations
