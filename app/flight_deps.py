"""機票掃描分頁的 FastAPI dependency：`FlightStore` 連線。

**這個檔案不 import `app/deps.py`**，也不透過它間接碰到 `alphavibe.db`
——比照 `app/us_stock_deps.py`／`app/photo_deps.py` 的既有先例，機票與
投資、相簿三者的資料完全獨立（`specs/005-flight-scan-page/plan.md`
「Structure Decision」）。資料目錄防呆邏輯照同一道模式重寫一份，
不呼叫也不繼承其他 deps 檔案的函式。

**環境變數沿用 `ALPHAVIBE_DATA_DIR`**（不是新環境變數）：`flights.db`
與其他資料庫本來就住在同一個資料目錄下，只是檔名不同。共用「資料目錄
在哪」這個變數對測試與部署較方便，且不影響資料表層級的獨立性。

限制：`app/` 底下的檔案要維持 Python 3.9 語法相容（這台機器只有 3.9.6），
用 `from __future__ import annotations` 讓 PEP 604 註記可安全使用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

# app/flight_deps.py 在 AlphaVibe/app/ 底下，往上一層是 AlphaVibe/，
# 再進 poc/kb-mcp/ 才是 flight_store.py 所在目錄。
_FLIGHT_KB_MCP_DIR = Path(__file__).resolve().parent.parent / "poc" / "kb-mcp"
if str(_FLIGHT_KB_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_FLIGHT_KB_MCP_DIR))

from flight_store import FlightStore  # noqa: E402  (需先插入 sys.path)

_FLIGHT_PRODUCTION_DATA_DIR = os.path.abspath(
    str(_FLIGHT_KB_MCP_DIR / ".." / "data"))


def _resolve_flight_data_dir() -> str:
    """資料目錄解析：`ALPHAVIBE_DATA_DIR` **必須明確設定**，沒有隱性預設值。

    這道防線來自 2026-08-22 的事故——測試埠忘了設定這個環境變數，直接
    寫進了正式資料庫（見 CLAUDE.md 教訓紀錄）。這裡獨立寫一份同樣邏輯，
    不呼叫也不 import 其他 deps 檔案的函式。
    """
    env_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not env_dir:
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 未設定。這個環境變數是必要的，沒有隱性"
            "預設值——比照 2026-08-22 的教訓，避免測試/開發環境意外寫進"
            "正式資料庫。測試/開發：指向獨立複製的資料目錄"
            "（例如 poc/data-test/）。正式部署：明確指向 "
            + _FLIGHT_PRODUCTION_DATA_DIR
        )
    resolved = os.path.abspath(env_dir)
    if resolved == _FLIGHT_PRODUCTION_DATA_DIR and os.environ.get(
            "ALPHAVIBE_ALLOW_PRODUCTION_WRITE") != "1":
        raise RuntimeError(
            "ALPHAVIBE_DATA_DIR 指向正式資料目錄（%s），但未設定 "
            "ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1。要真的寫入正式資料請"
            "明確設定該旗標；測試請改指向獨立複製的資料目錄。"
            % _FLIGHT_PRODUCTION_DATA_DIR
        )
    return resolved


def get_flight_store() -> Iterator[FlightStore]:
    """request-scoped 的 `FlightStore`，request 結束後關閉連線。

    **背景任務不得使用這個 dependency**——background task 在 response
    送出後才執行，這裡的連線可能已經被 `finally` 關閉。背景任務改用
    `resolve_flight_data_dir_for_background()` 自行開關獨立連線，
    這是 `app/routers/photos.py` 已踩過並記錄的坑。
    """
    store = FlightStore(_resolve_flight_data_dir())
    try:
        yield store
    finally:
        store.close()


def resolve_flight_data_dir_for_background() -> str:
    """給背景任務（`BackgroundTasks`）用：回傳資料目錄路徑而非 store 物件，

    讓背景任務在自己的時機點建立與關閉 `FlightStore`，避免與
    request-scoped dependency 的關閉時機競爭（見 `get_flight_store()`）。
    """
    return _resolve_flight_data_dir()
