#!/usr/bin/env python3
"""排程健康巡檢（2026-09-17 架構體檢 B4）。

要解決的具體事故：2026-09-13 與 09-14 兩天，TPEx（上櫃）資料源連線
失敗，market_scan 照樣「完成」並寫進資料庫——total_scanned 從正常的
2327 掉到 1432 與 1074，等於整個上櫃市場沒掃到，選股結果少了一半以上
的標的。錯誤訊息確實記在 `market_scan_runs.tpex_error` 欄位裡，但沒有
任何人或機制會去看它，PO 是三天後做架構體檢才發現的。

這支腳本只負責**偵測與判定**，不負責怎麼通知——通知管道（Telegram／
網頁橫幅／其他）可以之後接上，讀這支腳本輸出的狀態檔即可。這樣切分
是因為偵測邏輯不管用哪種管道都一樣，而管道選擇是會變的。

嚴重度：
  critical — 資料不完整或排程沒跑，你看到的數字是錯的
  warning  — 有異常但結果仍可用
  ok       — 正常

用法：
    python3 poc/kb-mcp/check_scheduled_jobs.py
    python3 poc/kb-mcp/check_scheduled_jobs.py --json     # 只印 JSON
    python3 poc/kb-mcp/check_scheduled_jobs.py --data-dir X --state-file Y
"""
import argparse
import datetime
import glob
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notify  # noqa: E402

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DEFAULT_STATE_FILE = os.path.expanduser("~/Library/Logs/alphavibe-health.json")
DEFAULT_BACKUP_DIR = os.path.expanduser("~/AlphaVibe-backups/daily")
# 不需認證的探測端點（app/deps.py 的 _AUTH_EXEMPT_PATHS）
DEFAULT_SERVICE_URL = "http://localhost:8080/api/healthz"

# market_scan 每天 02:00 跑，超過 30 小時沒有新紀錄就是沒跑成功
SCAN_STALE_HOURS = 30
# total_scanned 低於近期中位數的這個比例就視為資料源殘缺
# （9/14 那次是 1074/2327 = 46%，所以 0.8 抓得到，正常日間波動約 2327~2336）
SCAN_COVERAGE_MIN_RATIO = 0.8
# 備份每天 03:30 跑
BACKUP_STALE_HOURS = 30


def _now():
    return datetime.datetime.now()


def _hours_since(dt):
    return (_now() - dt).total_seconds() / 3600.0


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def check_market_scan(data_dir):
    """台股 market_scan：有沒有跑、資料源有沒有失敗、掃描覆蓋率夠不夠。"""
    findings = []
    db_path = os.path.join(data_dir, "alphavibe.db")
    if not os.path.exists(db_path):
        return [("critical", "market_scan", "找不到資料庫：%s" % db_path)]

    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # 用 run_at 而不是 id 排序：id 遞增順序碰巧等於時間順序，但那是
        # 巧合不是保證——補寫歷史資料或重新匯入都會讓兩者脫鉤，那時
        # 「最新一筆」就會取錯，巡檢反而謊報。run_at 是 ISO 8601 字串，
        # 字典序等於時間序。
        rows = conn.execute(
            "SELECT * FROM market_scan_runs"
            " WHERE run_at IS NOT NULL ORDER BY run_at DESC LIMIT 20"
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return [("critical", "market_scan", "查詢失敗：%s" % exc)]
    conn.close()

    if not rows:
        return [("critical", "market_scan", "完全沒有掃描紀錄")]

    latest = rows[0]
    run_at = _parse_iso(latest["run_at"])
    if run_at is None:
        findings.append(("warning", "market_scan", "最新紀錄的時間無法解析：%r" % latest["run_at"]))
    else:
        hours = _hours_since(run_at)
        if hours > SCAN_STALE_HOURS:
            findings.append((
                "critical", "market_scan",
                "已經 %.0f 小時沒有成功的掃描（最後一次 %s）" % (hours, latest["run_at"])))

    # 資料源錯誤：錯誤訊息本來就記在欄位裡，只是從來沒人看
    for col, label in (("twse_error", "上市 TWSE"), ("tpex_error", "上櫃 TPEx"),
                       ("emerging_error", "興櫃"), ("benchmark_error", "大盤基準")):
        err = latest[col] if col in latest.keys() else None
        if err:
            sev = "warning" if col == "benchmark_error" else "critical"
            findings.append((
                sev, "market_scan",
                "%s 資料源失敗，該市場的股票這次沒有被掃到：%s" % (label, str(err)[:120])))

    # 覆蓋率驟降：即使沒有 error 欄位，掃描量掉一大截同樣代表資料不完整
    counts = [r["total_scanned"] for r in rows if r["total_scanned"]]
    if len(counts) >= 3 and latest["total_scanned"]:
        baseline = sorted(counts)[len(counts) // 2]          # 中位數
        ratio = latest["total_scanned"] / float(baseline)
        if ratio < SCAN_COVERAGE_MIN_RATIO:
            findings.append((
                "critical", "market_scan",
                "掃描覆蓋率只有近期中位數的 %.0f%%（這次 %d 檔 vs 平常 %d 檔），"
                "選股結果很可能漏掉整個市場"
                % (ratio * 100, latest["total_scanned"], baseline)))

    if not findings:
        findings.append((
            "ok", "market_scan",
            "正常（最近一次 %s，掃描 %d 檔）" % (latest["run_at"], latest["total_scanned"] or 0)))
    return findings


def check_backups(backup_dir=DEFAULT_BACKUP_DIR):
    """資料庫備份有沒有照常產生。"""
    files = glob.glob(os.path.join(backup_dir, "alphavibe-*.db.gz"))
    if not files:
        return [("critical", "backup", "找不到任何資料庫備份：%s" % backup_dir)]
    newest = max(files, key=os.path.getmtime)
    hours = _hours_since(datetime.datetime.fromtimestamp(os.path.getmtime(newest)))
    if hours > BACKUP_STALE_HOURS:
        return [("critical", "backup",
                 "最新備份是 %.0f 小時前（%s）" % (hours, os.path.basename(newest)))]
    size_mb = os.path.getsize(newest) / 1024.0 / 1024.0
    if size_mb < 0.1:
        return [("critical", "backup",
                 "最新備份檔異常小（%.2f MB），可能是壞的" % size_mb)]
    return [("ok", "backup",
             "正常（%.0f 小時前，%.1f MB，共 %d 份）" % (hours, size_mb, len(files)))]


def check_web_service(url=DEFAULT_SERVICE_URL, attempts=3, gap_seconds=5):
    """STND 網頁服務本身還活著嗎（2026-09-17 架構體檢 B4 追加）。

    為什麼巡檢有資格檢查這個：這支腳本是獨立的 launchd 排程，不經過
    web 服務，所以 web 服務掛掉時它照樣會跑、照樣發得出 Telegram。
    首頁橫幅在這種故障下幫不上忙——連首頁都打不開。

    為什麼需要這個檢查：A5 把認證改成 fail-closed 之後多了一種新的
    故障模式——token 若從 plist 消失，服務會拒絕啟動，而 plist 的
    KeepAlive 會讓 launchd 每隔約 10 秒重試一次，變成無限 crash-loop。
    那是刻意的取捨（連不上遠比無認證裸奔安全），但「連不上」這件事
    本身必須有人通知，否則就只是換一種無聲的失敗。

    打 /api/healthz：它在 _AUTH_EXEMPT_PATHS 裡，不需要認證，正是設計
    給探測用的。重試 3 次是因為巡檢可能剛好撞上服務重啟的空檔，單次
    失敗就告警會製造假警報——而假警報會訓練人忽略真警報。
    """
    import time
    import urllib.error
    import urllib.request

    last_error = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    return [("ok", "web_service", "正常（%s 回應 200）" % url)]
                last_error = "HTTP %s" % resp.status
        except urllib.error.HTTPError as exc:
            # 4xx/5xx 都代表服務活著但不對勁，不必重試
            return [("critical", "web_service",
                     "STND 網頁服務回應異常：HTTP %s（%s）" % (exc.code, url))]
        except Exception as exc:
            last_error = str(exc)
        if attempt < attempts - 1:
            time.sleep(gap_seconds)

    return [("critical", "web_service",
             "STND 網頁服務連不上（試了 %d 次）：%s。"
             "若剛改過 launchd plist，先查 ALPHAVIBE_DASHBOARD_TOKEN／"
             "ALPHAVIBE_MCP_TOKEN 是否還在——認證設定缺失會讓服務拒絕啟動"
             % (attempts, last_error))]


CHECKS = (
    ("market_scan", check_market_scan, True),   # True = 需要 data_dir
    ("backup", check_backups, False),
    ("web_service", check_web_service, False),
)


def run_all(data_dir):
    findings = []
    for name, fn, needs_dir in CHECKS:
        try:
            findings.extend(fn(data_dir) if needs_dir else fn())
        except Exception as exc:                    # 巡檢自己壞掉也要看得見
            findings.append(("critical", name, "巡檢本身失敗：%s" % exc))
    return findings


def _load_previous(state_file):
    try:
        with open(state_file, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _signature(state):
    """狀態的指紋：整體狀態 + 所有非 ok 項目的內容。用來判斷「有沒有
    變化」，而不是每次巡檢都發通知。"""
    items = sorted(
        "%s|%s|%s" % (f.get("severity"), f.get("job"), f.get("detail"))
        for f in state.get("findings", []) if f.get("severity") != "ok"
    )
    return (state.get("status"), tuple(items))


def should_notify(previous, current):
    """要不要發通知，回傳 (要不要, 原因)。

    只在「狀態有變化」時發：每天 04:00 固定發一則「還是壞的」會讓人
    麻痺，而麻痺的告警等於沒有告警。三種情況要發：
      - 出現新問題（ok → 有問題，或問題內容變了）
      - 問題消失（有問題 → ok），讓人知道不用再管了
    """
    if previous is None:
        # 第一次跑：只有出事才吵，正常就安靜
        return (current["status"] != "ok", "首次巡檢")
    prev_sig, cur_sig = _signature(previous), _signature(current)
    if prev_sig == cur_sig:
        return (False, "狀態與上次相同")
    if current["status"] == "ok":
        return (True, "問題已恢復")
    return (True, "狀態改變（%s → %s）" % (previous.get("status"), current["status"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="AlphaVibe 排程健康巡檢")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    ap.add_argument("--json", action="store_true", help="只輸出 JSON")
    ap.add_argument("--notify", action="store_true",
                    help="狀態有變化時發 Telegram 通知")
    ap.add_argument("--force-notify", action="store_true",
                    help="不管有沒有變化都發（測試通知管道用）")
    args = ap.parse_args(argv)

    previous = _load_previous(args.state_file) if args.state_file else None

    findings = run_all(os.path.abspath(args.data_dir))
    criticals = [f for f in findings if f[0] == "critical"]
    warnings = [f for f in findings if f[0] == "warning"]

    state = {
        "checked_at": _now().astimezone().isoformat(timespec="seconds"),
        "status": "critical" if criticals else ("warning" if warnings else "ok"),
        "critical_count": len(criticals),
        "warning_count": len(warnings),
        "findings": [{"severity": s, "job": j, "detail": d} for s, j, d in findings],
    }

    if args.state_file:
        try:
            with open(args.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            sys.stderr.write("寫入狀態檔失敗：%s\n" % exc)

    if args.notify or args.force_notify:
        wanted, reason = (True, "強制發送") if args.force_notify \
            else should_notify(previous, state)
        if wanted:
            sent, errors = notify.send_telegram(notify.format_health_message(state))
            if not args.json:
                print("  通知：%s → 送出 %d 則" % (reason, sent))
                for e in errors:
                    print("    錯誤：%s" % e)
        elif not args.json:
            print("  通知：略過（%s）" % reason)

    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        stamp = _now().strftime("%Y-%m-%d %H:%M:%S")
        icon = {"critical": "✗", "warning": "!", "ok": "✓"}
        print("[%s] 排程健康巡檢：%s" % (stamp, state["status"].upper()))
        for sev, job, detail in findings:
            print("  %s [%s] %s" % (icon.get(sev, "?"), job, detail))

    # critical 用非 0 退出碼，方便之後接任何通知管道（launchd、cron、
    # shell wrapper 都認得退出碼）
    return 2 if criticals else 0


if __name__ == "__main__":
    sys.exit(main())
