#!/usr/bin/env python3
"""機票價格追蹤的排程進入點（由 launchd 每日呼叫一次）。

## 這支腳本做什麼

1. 找出今天輪到、且距上次成功已滿一個週期的追蹤條件
2. 對每個條件執行既有的掃描（**不重新實作掃描邏輯**）
3. 掃完後判定是否跌破目標價：達標發「降價」通知；**未達標**則發「現況」
   通知（PO 2026-09-24 新增，告知這輪最低價與目標價的差距），兩者互斥、
   同一輪只會發一種

## 三個刻意的設計

**不依賴網頁服務**：排程必須在服務沒跑（重啟、當機、還沒啟動）時照常
執行——這功能的價值正是「不必盯著」。因此走 `--data-dir` 參數而非
`app/flight_deps.py` 的環境變數防呆：那道防線是為網頁服務設的
（2026-08-22 測試埠寫進正式庫的事故），排程由 launchd 以固定參數啟動，
情境不同；既有的 `market_scan.py`／`us_stock_scan.py` 也都是這個做法。

**每日跑一次、自行選取**：而不是每個條件一個 launchd job。條件由使用者
在網頁動態增刪，若每條件一個 plist，網頁服務就得能寫
`~/Library/LaunchAgents/` 並呼叫 `launchctl`——權限遠超所需，刪除條件時
還容易留下孤兒 plist。

**通知失敗不影響掃描**：`notify.send_telegram()` 的設計鐵則就是「任何
失敗都不讓呼叫端崩潰」，回傳 `(成功數, [錯誤])` 而不拋例外。掃描結果
照常保存，只在條件上標記通知未送達，讓使用者知道要自己回來看。

## 用法

    python3 flight_tracking_job.py --data-dir poc/data
    python3 flight_tracking_job.py --data-dir poc/data --dry-run

`--dry-run` 只列出今天輪到誰與會做什麼，**不查價、不通知**。
"""
import argparse
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import flight_scan_service as svc  # noqa: E402
import notify  # noqa: E402
from flight_store import FlightStore  # noqa: E402


def _log(msg):
    """輸出到 stdout，由 launchd 導向 log 檔。

    加時間戳是因為 launchd 的 log 是累積的——沒有時間戳就分不出這行是
    哪一天的執行（data-model.md 決定以 log 承擔執行紀錄的角色）。
    """
    print("[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       msg))
    sys.stdout.flush()


def process_track(track, data_dir, store, dry_run=False, notifier=None):
    """處理單一條件：掃描 → 判定 → 通知。回傳結果摘要 dict。"""
    tid = track["id"]
    summary = {"id": tid, "name": track["name"], "scanned": False,
               "notified": False, "skipped_reason": None}

    if dry_run:
        plan = svc.scan_plan(track, data_dir)
        summary["skipped_reason"] = "dry-run"
        summary["plan"] = plan
        _log("  [%d] %s｜待查 %d／%d 組，本時段可查 %d"
             % (tid, track["name"], plan["pending"], plan["planned"],
                plan["will_query"]))
        return summary

    outcome = svc.run_scan(tid, data_dir)
    summary["scanned"] = True
    summary["outcome"] = outcome
    _log("  [%d] %s｜查詢 %d 筆、寫入 %d 筆%s"
         % (tid, track["name"], outcome.get("queried", 0),
            outcome.get("written", 0),
            "（偵測到阻擋）" if outcome.get("blocked") else ""))

    # 重讀條件：run_scan 可能已更新 last_success_at，過期判定要用最新值
    track = store.get_track(tid)
    if track is None:                      # 執行期間被刪除
        summary["skipped_reason"] = "track_deleted"
        return summary

    lowest = store.lowest_result(tid)
    if not lowest:
        summary["skipped_reason"] = "no_priced_result"
        return summary

    state = svc.derive_state(track, data_dir, store=store)
    send = notifier or notify.send_telegram

    # 取完整的最低價那一列（lowest_result 只回摘要，通知需要四段日期）
    rows = [r for r in store.list_results(tid)
            if r["status"] == "ok" and r["price"] == lowest["price"]]
    if not rows:
        summary["skipped_reason"] = "row_not_found"
        return summary

    if svc.should_notify(track, lowest["price"], state=state):
        message = svc.build_notification(track, rows[0])
        sent, errors = send(message)
        ok = sent > 0
        store.record_notification(tid, lowest["price"], ok=ok)
        summary["notified"] = ok
        summary["notify_errors"] = errors
        _log("  [%d] 通知%s（NT$%s）%s"
             % (tid, "已送出" if ok else "失敗", format(lowest["price"], ","),
                "；" + "；".join(errors) if errors else ""))
        return summary

    # 未達標的現況通知（PO 2026-09-24 新增）：跟達標通知互斥，兩者不會
    # 同一輪都發——刻意不寫進 `record_notification()`（那組欄位是「上次
    # 達標通知」的語意，見 FR-019），也不做去重，每輪未達標都會送一次
    if svc.should_notify_status(track, lowest["price"], state=state):
        message = svc.build_status_notification(track, rows[0])
        sent, errors = send(message)
        summary["status_notified"] = sent > 0
        summary["status_notify_errors"] = errors
        _log("  [%d] 現況通知%s（最低 NT$%s，未達標）%s"
             % (tid, "已送出" if sent > 0 else "失敗",
                format(lowest["price"], ","),
                "；" + "；".join(errors) if errors else ""))
        summary["skipped_reason"] = "not_below_target_status_sent"
        return summary

    summary["skipped_reason"] = (
        "stale" if state == "stale" else "not_below_target_or_duplicate")
    return summary


def run(data_dir, dry_run=False, today=None, notifier=None):
    """一次排程執行。回傳所有處理過的條件摘要。"""
    store = FlightStore(data_dir)
    try:
        today = today or datetime.date.today()
        all_tracks = store.list_tracks()
        due = svc.due_tracks(store, today)
        _log("排程啟動｜%s（星期%d）｜條件 %d 個，今天輪到 %d 個%s"
             % (today.isoformat(), today.weekday() + 1, len(all_tracks),
                len(due), "｜DRY-RUN" if dry_run else ""))
        results = [process_track(t, data_dir, store, dry_run, notifier)
                   for t in due]
        _log("排程結束｜掃描 %d、通知 %d"
             % (sum(1 for r in results if r["scanned"]),
                sum(1 for r in results if r["notified"])))
        return results
    finally:
        store.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="機票價格追蹤排程")
    ap.add_argument("--data-dir", default="poc/data",
                    help="資料目錄（預設 poc/data）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出今天輪到誰與會做什麼，不查價、不通知")
    args = ap.parse_args(argv)
    try:
        run(os.path.abspath(args.data_dir), dry_run=args.dry_run)
    except Exception as exc:                # noqa: BLE001
        # 排程不該因單次失敗而留下無聲的空白——把錯誤寫進 log 才查得到
        _log("排程失敗：%s: %s" % (type(exc).__name__, exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
