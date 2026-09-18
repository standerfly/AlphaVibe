"""相簿分頁的 FastAPI dependency：`PhotoStore` 連線。

**這個檔案不 import `app/deps.py` 或 `app/us_stock_deps.py`**，也不
透過它們間接碰到 `alphavibe.db`／`us_stocks.db` 或既有查詢管道——完全
獨立的程式碼路徑，比照 `app/us_stock_deps.py` 對 `app/deps.py` 的既有
「各自獨立寫一份同樣邏輯」慣例（`specs/004-photos-albums-search/
plan.md` Constitution Check Gate G1）。

**環境變數沿用 `ALPHAVIBE_DATA_DIR`**（不是新環境變數）：`PhotoStore`
與 `KBStore`／`USStockStore` 的資料庫檔案本來就住在同一個資料目錄下
（`poc/data/`，只是檔名不同：`photos.db`），共用「資料目錄在哪」這個
環境變數對測試/部署更方便，且不影響 Gate G1 要求的程式碼/資料表層級
獨立。`ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 旗標同理沿用。

限制：這個 `app/` 目錄下的檔案要維持 Python 3.9 語法相容（這台機器只有
3.9.6），用 `from __future__ import annotations` 讓 PEP 604 的
`X | None` 註記可以安全使用（比照 `app/deps.py`／`app/us_stock_deps.py`
同樣的限制與寫法）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

# app/photo_deps.py 在 AlphaVibe/app/ 底下，往上一層是 AlphaVibe/，
# 再進 poc/kb-mcp/ 才是 photo_store.py 所在目錄（跟 app/deps.py 對
# kb_store.py 的路徑推算方式一致，但這裡獨立各自算一次，不共用變數）。
_PHOTO_KB_MCP_DIR = Path(__file__).resolve().parent.parent / "poc" / "kb-mcp"
if str(_PHOTO_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_PHOTO_KB_MCP_DIR))

from photo_store import PhotoStore  # noqa: E402  (需先插入 sys.path 才能 import)


_PHOTO_PRODUCTION_DATA_DIR = os.path.abspath(
    str(_PHOTO_KB_MCP_DIR / ".." / "data"))


def _resolve_photo_data_dir() -> str:
    """資料目錄解析：`ALPHAVIBE_DATA_DIR` 環境變數**必須明確設定**，沒有
    隱性預設值——比照 `app/deps.py::_resolve_data_dir()` 2026-08-22 教訓
    設下的同一道防線，這裡獨立寫一份同樣邏輯，不呼叫也不 import 那個
    函式。"""
    env_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not env_dir:
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 未設定。這個環境變數是必要的，沒有隱性"
            "預設值——比照 app/deps.py::_resolve_data_dir() 2026-08-22 的"
            "教訓，避免測試/開發環境意外寫進正式資料庫。"
            "測試/開發：指向一份獨立複製出來的資料目錄（例如 poc/data-test/）。"
            "正式部署：明確指向 " + _PHOTO_PRODUCTION_DATA_DIR
        )
    resolved = os.path.abspath(env_dir)
    if resolved == _PHOTO_PRODUCTION_DATA_DIR and os.environ.get(
        "ALPHAVIBE_ALLOW_PRODUCTION_WRITE") != "1":
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 指向正式資料庫路徑（"
            + _PHOTO_PRODUCTION_DATA_DIR
            + "），但沒有設定 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 明確確認。"
            "如果是要正式切換服務，請明確加上這個環境變數；"
            "如果是要測試，請改指向獨立的複製資料目錄，不要指向這個路徑。"
        )
    return resolved


def get_photo_store() -> Iterator[PhotoStore]:
    """FastAPI dependency：每個 request 各自建立一個 `PhotoStore`（各自
    開一條 sqlite3 連線），request 結束後關閉——比照
    `app/us_stock_deps.py::get_us_stock_store()` 同樣的 yield 型
    dependency 模式。**背景任務（匯入/中繼資料寫回）不使用這個
    dependency**——background task 在 response 送出後才執行，這裡的
    連線可能已經被 `finally` 關閉，背景任務改用
    `resolve_photo_data_dir_for_background()` 自行開一個獨立連線，見
    `app/routers/photos.py`。"""
    store = PhotoStore(_resolve_photo_data_dir())
    try:
        yield store
    finally:
        store.close()


def resolve_photo_data_dir_for_background() -> str:
    """給背景任務（`BackgroundTasks`）用：直接回傳資料目錄路徑（不是
    yield 一個 store 物件），讓背景任務在自己的時機點自行建立/關閉
    `PhotoStore`，避免跟 request-scoped dependency 的關閉時機互相
    競爭（見 `get_photo_store()` docstring）。"""
    return _resolve_photo_data_dir()
