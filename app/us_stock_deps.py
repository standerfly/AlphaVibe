"""美股獨立系統的 FastAPI dependency：`USStockStore` 連線。

**這個檔案不 import `app/deps.py`**，也不透過它間接碰到 `alphavibe.db`
或既有台股查詢管道（spec.md FR-015/016、`research.md` §1/2 的「完全
獨立」要求）——資料目錄安全防呆邏輯比照 `app/deps.py::_resolve_data_dir()`
的既有模式撰寫（2026-08-22 資產表污染事故教訓：`ALPHAVIBE_DATA_DIR`
未設定不得有隱性預設值，見 AlphaVibe/CLAUDE.md 教訓紀錄），但是完全獨立
的程式碼路徑，不呼叫、不繼承任何 `app/deps.py` 的函式。

**環境變數沿用 `ALPHAVIBE_DATA_DIR`**（不是新環境變數）：`USStockStore`
與 `KBStore` 的資料庫檔案本來就住在同一個資料目錄下（`poc/data/`，只是
檔名不同：`us_stocks.db` vs `alphavibe.db`，見 `data-model.md`），共用
「資料目錄在哪」這個環境變數對測試/部署更方便，且不影響 FR-015/016
要求的程式碼/資料表層級獨立——這一層獨立的是「查詢管道與程式碼」，不是
「资料目錄環境變數的名字」。`ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 旗標
同理沿用，一個旗標同時代表「我確實要寫入正式資料」，不分是哪個 store。

限制：這個 `app/` 目錄下的檔案要維持 Python 3.9 語法相容（這台機器只有
3.9.6），用 `from __future__ import annotations` 讓 PEP 604 的
`X | None` 註記可以安全使用（比照 `app/deps.py` 同樣的限制與寫法）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

# app/us_stock_deps.py 在 AlphaVibe/app/ 底下，往上一層是 AlphaVibe/，
# 再進 poc/kb-mcp/ 才是 us_stock_store.py 所在目錄（跟 app/deps.py 對
# kb_store.py 的路徑推算方式一致，但這裡獨立各自算一次，不共用變數）。
_US_STOCK_KB_MCP_DIR = Path(__file__).resolve().parent.parent / "poc" / "kb-mcp"
if str(_US_STOCK_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_US_STOCK_KB_MCP_DIR))

from us_stock_store import USStockStore  # noqa: E402  (需先插入 sys.path 才能 import)


_US_STOCK_PRODUCTION_DATA_DIR = os.path.abspath(
    str(_US_STOCK_KB_MCP_DIR / ".." / "data"))


def _resolve_us_stock_data_dir() -> str:
    """資料目錄解析：`ALPHAVIBE_DATA_DIR` 環境變數**必須明確設定**，沒有
    隱性預設值——比照 `app/deps.py::_resolve_data_dir()` 2026-08-22 教訓
    設下的同一道防線（測試埠忘了設定這個環境變數，直接寫進了正式資料庫），
    這裡獨立寫一份同樣邏輯，不呼叫也不 import 那個函式。"""
    env_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not env_dir:
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 未設定。這個環境變數是必要的，沒有隱性"
            "預設值——比照 app/deps.py::_resolve_data_dir() 2026-08-22 的"
            "教訓，避免測試/開發環境意外寫進正式資料庫。"
            "測試/開發：指向一份獨立複製出來的資料目錄（例如 poc/data-test/）。"
            "正式部署：明確指向 " + _US_STOCK_PRODUCTION_DATA_DIR
        )
    resolved = os.path.abspath(env_dir)
    if resolved == _US_STOCK_PRODUCTION_DATA_DIR and os.environ.get(
        "ALPHAVIBE_ALLOW_PRODUCTION_WRITE") != "1":
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 指向正式資料庫路徑（"
            + _US_STOCK_PRODUCTION_DATA_DIR
            + "），但沒有設定 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 明確確認。"
            "如果是要正式切換服務，請明確加上這個環境變數；"
            "如果是要測試，請改指向獨立的複製資料目錄，不要指向這個路徑。"
        )
    return resolved


def get_us_stock_store() -> Iterator[USStockStore]:
    """FastAPI dependency：每個 request 各自建立一個 `USStockStore`（各自
    開一條 sqlite3 連線），request 結束後關閉——比照
    `app/deps.py::get_kb_store()` 同樣的 yield 型 dependency 模式（sqlite3
    連線不可跨執行緒共用，見 `USStockStore.__init__` 的
    `check_same_thread=False` 說明），但這裡是完全獨立的程式碼，不呼叫
    `app/deps.py` 的任何函式。"""
    store = USStockStore(_resolve_us_stock_data_dir())
    try:
        yield store
    finally:
        store.close()
