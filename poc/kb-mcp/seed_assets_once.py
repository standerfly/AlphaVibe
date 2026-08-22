"""資產分頁初始種子資料——一次性、需要人手動執行的腳本。

2026-08-22 教訓：這個種子動作原本綁在 KBStore.__init__()，導致任何建立
KBStore 的呼叫端（含每天 02:00 排程的 market_scan.py）都會意外觸發，
兩度把正式資料庫的資產表重新種回預設值。修正後，種子資料只能透過這支
腳本明確觸發，不會再被任何「順便建立一個 KBStore」的程式碼路徑意外執行。

用法（正式環境，真的要開始使用資產分頁時才跑，跑一次就好）：
    python3 poc/kb-mcp/seed_assets_once.py --data-dir poc/data

用法（測試環境）：
    python3 poc/kb-mcp/seed_assets_once.py --data-dir poc/data-test

冪等：KBStore.seed_asset_defaults() 內部只在 asset_pockets 表完全空的
時候才寫入，這支腳本重跑不會重複塞資料，但仍要求 --data-dir 明確指定，
不提供隱性預設值（比照 app/deps.py::_resolve_data_dir 的安全設計）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kb_store import KBStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True,
        help="資料目錄路徑（明確指定，不提供預設值——避免重蹈 "
             "2026-08-22 覆轍：不小心指到正式庫或搞錯環境）",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    print("資料目錄：%s" % data_dir)

    store = KBStore(data_dir)
    try:
        existing = store.conn.execute(
            "SELECT COUNT(*) AS c FROM asset_pockets").fetchone()["c"]
        if existing:
            print("asset_pockets 已有 %d 筆資料，不重複寫入（冪等，安全略過）。"
                  % existing)
            return 0
        store.seed_asset_defaults()
        after = store.conn.execute(
            "SELECT COUNT(*) AS c FROM asset_pockets").fetchone()["c"]
        print("已寫入種子資料，asset_pockets 現有 %d 筆。" % after)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
