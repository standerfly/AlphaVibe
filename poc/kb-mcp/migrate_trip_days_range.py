"""四段票天數區間化——id=9 一次性遷移腳本（007-trip-day-range）。

背景：`flight_track.trip_days` 從單一固定整數升級為區間
（`trip_days_min`／`trip_days_max`）。正式庫唯一一筆既有追蹤條件
（id=9，布拉格・成田出發，原 `trip_days=12`）需要遷移到新語意
（10～14 天，PO 於 pre-spec 階段採納 Claude 提案），且遷移不得變動
其目標價、通知歷史、重掃頻率等非天數相關欄位。

比照 `seed_assets_once.py` 的既有先例：**一次性、需要人手動執行**，
不掛進 `__init__()` 或任何自動觸發路徑（2026-08-22 事故的教訓——建構子
內的自動寫入副作用，兩度污染過正式資料庫）。

用法（先對測試庫驗證，再對正式庫執行——見
specs/007-trip-day-range/quickstart.md 坑 3）：
    python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data-test --dry-run
    python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data-test
    python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data --dry-run
    python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data

`--dry-run` 只印出遷移前後對照，不寫入。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flight_store import FlightStore  # noqa: E402

TRACK_ID = 9
NEW_MIN = 10
NEW_MAX = 14


def _print_track(label, track):
    if track is None:
        print("  %s：找不到 id=%d" % (label, TRACK_ID))
        return
    print("  %s：trip_days_min=%s trip_days_max=%s"
          " target_price=%s scan_frequency_days=%s"
          " last_notified_price=%s"
          % (label, track.get("trip_days_min"), track.get("trip_days_max"),
             track.get("target_price"), track.get("scan_frequency_days"),
             (track.get("notify") or {}).get("last_notified_price")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True,
        help="資料目錄路徑（明確指定，不提供預設值——避免不小心指到"
             "正式庫或搞錯環境，比照 seed_assets_once.py 的安全設計）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只印出遷移前後對照，不寫入",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    print("資料目錄：%s" % data_dir)
    print("目標：id=%d 的天數改為 %d～%d 天%s"
          % (TRACK_ID, NEW_MIN, NEW_MAX,
             "（dry-run，不寫入）" if args.dry_run else ""))

    store = FlightStore(data_dir)
    try:
        before = store.get_track(TRACK_ID)
        if before is None:
            print("找不到 id=%d，這個資料目錄可能不是預期的環境，"
                  "或這筆條件已被刪除。已中止，未做任何變更。" % TRACK_ID)
            return 1

        _print_track("遷移前", before)

        if before.get("trip_days_min") == NEW_MIN and \
                before.get("trip_days_max") == NEW_MAX:
            print("已經是目標區間（%d～%d 天），不需要遷移。"
                  % (NEW_MIN, NEW_MAX))
            return 0

        if args.dry_run:
            print("dry-run：以上是會被改動的條件，未實際寫入。")
            return 0

        after = store.update_trip_days_range(TRACK_ID, NEW_MIN, NEW_MAX)
        _print_track("遷移後", after)

        # 遷移只改天數，其餘欄位必須維持不變——這裡當場核對，不只是
        # 相信 update_trip_days_range() 的實作沒有動到別的欄位
        unchanged_fields = ("target_price", "scan_frequency_days", "notify")
        mismatches = [f for f in unchanged_fields if before.get(f) != after.get(f)]
        if mismatches:
            print("⚠️ 警告：遷移過程中以下欄位發生非預期變動：%s"
                  % mismatches)
            return 1

        print("遷移完成，非天數欄位（%s）核對一致。"
              % "、".join(unchanged_fields))
        print("提醒：這支腳本只改資料庫欄位，不會觸發重新查價——"
              "遷移後請手動觸發一次掃描，或等下次排程自動重掃。")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
