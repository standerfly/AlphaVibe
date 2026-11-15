"""定錨文章庫的資料目錄安全防呆（010）——**唯一**的判斷邏輯，CLI 與 FastAPI 共用。

規則（比照 2026-08-22 資產表污染事故教訓）：
  - 資料目錄必須明確指定，沒有隱性預設值；
  - 解析後（含 symlink：AlphaVibe-prod/poc/data 是指向 AlphaVibe/poc/data 的 symlink）若是正式資料目錄，
    必須同時設 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，否則拒絕。

拒絕發生在取信、登入、寫入**之前**。僅標準庫，Python 3.9 相容。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCTION_DATA_DIR = os.path.realpath(os.path.join(HERE, "..", "data"))
ALLOW_FLAG = "ALPHAVIBE_ALLOW_PRODUCTION_WRITE"


class DataDirRefused(RuntimeError):
    pass


def resolve_data_dir(path, env=None):
    """回傳解析（realpath）後的資料目錄；拒絕時丟 DataDirRefused。"""
    env = os.environ if env is None else env
    if not path:
        raise DataDirRefused(
            "資料目錄未指定。必須明確給 --data-dir（沒有隱性預設值）。測試／開發請指向獨立目錄，"
            "例如 poc/data-test-articles/。")
    resolved = os.path.realpath(os.path.abspath(path))
    if resolved == PRODUCTION_DATA_DIR and env.get(ALLOW_FLAG) != "1":
        raise DataDirRefused(
            "資料目錄指向正式資料庫（%s），但沒有設定 %s=1 明確確認。若是測試，請改指向獨立目錄。"
            % (PRODUCTION_DATA_DIR, ALLOW_FLAG))
    return resolved
