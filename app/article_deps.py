"""定錨文章庫的 FastAPI dependency：`ArticleStore` 連線（010 T008）。

**這個檔案不 import `app/deps.py`、`app/us_stock_deps.py` 或任何台股／美股模組**——資料目錄安全
防呆比照 `app/us_stock_deps.py` 的既有寫法（2026-08-22 資產表污染事故教訓：`ALPHAVIBE_DATA_DIR`
未設定不得有隱性預設值），但是獨立的一份程式碼，不呼叫、不繼承對方的任何函式。

文章庫 `articles.db` 與台股 `alphavibe.db`、美股 `us_stocks.db` 住在同一個資料目錄下、檔名不同；
環境變數與 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 旗標沿用（一個旗標代表「我確實要寫入正式資料」）。

這個 `app/` 目錄下的檔案要維持 Python 3.9 語法相容（`from __future__ import annotations`）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

_ARTICLE_KB_MCP_DIR = Path(__file__).resolve().parent.parent / "poc" / "kb-mcp"
if str(_ARTICLE_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_ARTICLE_KB_MCP_DIR))

import article_data_guard  # noqa: E402
from article_store import ArticleStore  # noqa: E402  (需先插入 sys.path 才能 import)


_ARTICLE_PRODUCTION_DATA_DIR = os.path.abspath(str(_ARTICLE_KB_MCP_DIR / ".." / "data"))


def _resolve_article_data_dir() -> str:
    """`ALPHAVIBE_DATA_DIR` 必須明確設定，沒有隱性預設值；指向正式路徑必須同時設
    `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`。"""
    env_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not env_dir:
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 未設定。這個環境變數是必要的，沒有隱性預設值——"
            "比照 app/deps.py::_resolve_data_dir() 2026-08-22 的教訓，避免測試／開發環境"
            "意外寫進正式資料庫。測試／開發：指向獨立的資料目錄（例如 poc/data-test-articles/）。"
            "正式部署：明確指向 " + _ARTICLE_PRODUCTION_DATA_DIR
        )
    return article_data_guard.resolve_data_dir(env_dir)   # 與 CLI 共用同一份判斷（含 symlink 解析）


def get_article_store() -> Iterator[ArticleStore]:
    """每個 request 各自建立一個 `ArticleStore`（各自一條 sqlite3 連線），結束後關閉。"""
    store = ArticleStore(_resolve_article_data_dir())
    try:
        yield store
    finally:
        store.close()
