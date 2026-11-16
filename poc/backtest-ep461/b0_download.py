#!/usr/bin/env python3
"""B0 資料下載：FinMind → 本地檔（data/raw/<資料集>/<代號>.json）。

子指令：
  probe     第一步。小量呼叫確認除權息／分割／減資資料集的名稱、欄位與 token 權限，
            結果存 data/probe.json 並印出（把輸出貼回給 Claude）。
  download  下載 0050 與庫存 15 檔的日價量 + 事件資料集。可續傳（已存的檔不重抓）。
  status    列出每個檔案的下載狀態。

節制：逐檔呼叫、每次間隔 --sleep 秒、失敗重試最多 3 次（遇暫時性錯誤才退避）、
遇到額度用完（HTTP／status 402）立即停止並存進度；預設避開凌晨 01:30–03:30
（專案的 02:00 全市場掃描時段）；一次最多 --max-calls 次。
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import common as C


class QuotaExhausted(Exception):
    pass


def _sleep(seconds):
    time.sleep(seconds)


def fetch(dataset, stock_id, start, end, token, retries=3, timeout=30):
    """回傳 {"status": "ok"|"refused"|"error", "data": [...], "msg": str}。
    額度用完丟 QuotaExhausted。暫時性錯誤（逾時、5xx、429）退避重試。"""
    params = {"dataset": dataset}
    if stock_id:
        params["data_id"] = stock_id
    if start:
        params["start_date"] = start
    if end:
        params["end_date"] = end
    if token:
        params["token"] = token
    url = C.API_URL + "?" + urllib.parse.urlencode(params)
    backoff = [5, 15, 45]
    scale = float(os.environ.get("BT_BACKOFF_SCALE", "1"))
    last = ""
    for attempt in range(retries + 1):
        payload = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "alphavibe-backtest-ep461"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 402:
                raise QuotaExhausted("HTTP 402")
            if exc.code in (429, 500, 502, 503, 504):
                last = "HTTP %s" % exc.code
            else:
                return {"status": "refused", "data": [], "msg": "HTTP %s" % exc.code}
        except Exception as exc:  # 網路、逾時、JSON 壞掉
            last = "%s: %s" % (type(exc).__name__, exc)
        if payload is not None:
            code = payload.get("status")
            if code in (200, "200"):
                return {"status": "ok", "data": payload.get("data") or [], "msg": ""}
            if code in (402, "402"):
                raise QuotaExhausted(str(payload.get("msg", "")))
            return {"status": "refused", "data": [],
                    "msg": "status=%s %s" % (code, payload.get("msg", ""))}
        if attempt < retries:
            _sleep(backoff[min(attempt, len(backoff) - 1)] * scale)
    return {"status": "error", "data": [], "msg": "重試 %d 次仍失敗：%s" % (retries, last)}


def in_schedule_window(now=None):
    now = now or datetime.datetime.now()
    minutes = now.hour * 60 + now.minute
    return 90 <= minutes <= 210  # 01:30–03:30


def _meta(dataset, stock_id, start, end, result):
    rows = result["data"]
    dates = [r.get("date") for r in rows if isinstance(r, dict) and r.get("date")]
    status = result["status"]
    if status == "ok" and not rows:
        status = "empty"
    return {"dataset": dataset, "stock_id": stock_id, "start": start, "end": end,
            "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "rows": len(rows), "fields": sorted(rows[0].keys()) if rows else [],
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "status": status, "msg": result.get("msg", "")}


def plan(symbols, only):
    tasks = []
    if only in ("all", "price"):
        tasks += [(C.PRICE_DATASET, s) for s in symbols]
    if only in ("all", "events"):
        tasks += [(d, s) for d in C.EVENT_DATASETS for s in symbols]
    return tasks


def run_download(args):
    token = C.read_token(args.token_file)
    if not token and not args.allow_anonymous:
        print("找不到 FinMind token（環境變數 FINMIND_TOKEN 或 finmind_token.txt）。"
              "匿名額度會連累排程，預設不執行；確定要匿名下載請加 --allow-anonymous。")
        return 3
    if in_schedule_window() and not args.ignore_schedule_window:
        print("現在是 01:30–03:30（02:00 全市場掃描時段），為避免搶額度先不下載。"
              "換個時間再跑，或加 --ignore-schedule-window。")
        return 3
    symbols = args.symbols or C.SYMBOLS
    end = args.end or C.today_str()
    tasks = plan(symbols, args.only)
    calls = 0
    done = skipped = bad = 0
    stopped = ""
    for dataset, sid in tasks:
        path = C.raw_path(dataset, sid)
        if os.path.isfile(path) and not args.force:
            st = C.read_json(path).get("meta", {}).get("status")
            if st in ("ok", "empty") or (st == "refused" and not args.retry_refused):
                skipped += 1
                continue
        if calls >= args.max_calls:
            stopped = "到達 --max-calls=%d" % args.max_calls
            break
        if calls:
            _sleep(args.sleep)
        try:
            result = fetch(dataset, sid, args.start, end, token)
        except QuotaExhausted as exc:
            stopped = "FinMind 額度用完（%s）" % exc
            break
        calls += 1
        meta = _meta(dataset, sid, args.start, end, result)
        C.write_json_atomic(path, {"meta": meta, "data": result["data"]})
        flag = {"ok": "OK", "empty": "空", "refused": "被拒", "error": "失敗"}[meta["status"]]
        print("[%s] %s %s rows=%d %s %s" % (flag, dataset, sid, meta["rows"],
              meta["last_date"] or "", meta["msg"]))
        if meta["status"] in ("ok", "empty"):
            done += 1
        else:
            bad += 1
    print("本次呼叫 %d 次；新存 %d、略過（已有）%d、問題 %d。" % (calls, done, skipped, bad))
    if stopped:
        print("已停止：%s。進度已存，等一小時（額度重置）後重跑同一指令即可續傳。" % stopped)
        return 2
    return 1 if bad else 0


PROBES = [
    # (資料集, 代號或 None=全市場, 起, 迄)：同時確認欄位名稱與 token 權限
    (C.PRICE_DATASET, "0050", "2025-06-10", "2025-06-24"),
    (C.DIVIDEND_DATASET, "2308", "2022-01-01", "2025-12-31"),
    (C.DIVIDEND_DATASET, None, "2025-06-01", "2025-06-30"),
    (C.SPLIT_DATASET, "0050", "2025-05-01", "2025-07-31"),
    (C.SPLIT_DATASET, None, "2025-05-01", "2025-07-31"),
    (C.CAPRED_DATASET, None, "2024-01-01", "2025-12-31"),
    ("TaiwanStockPriceAdj", "2308", "2025-01-01", "2025-03-31"),  # 選配：現成還原價（可能需付費權限）
]


def run_probe(args):
    token = C.read_token(args.token_file)
    if in_schedule_window() and not args.ignore_schedule_window:
        print("現在是 01:30–03:30，先不呼叫。加 --ignore-schedule-window 可強制。")
        return 3
    print("token：%s" % ("有" if token else "沒有（匿名）"))
    report = []
    for i, (dataset, sid, start, end) in enumerate(PROBES):
        if i:
            _sleep(args.sleep)
        try:
            res = fetch(dataset, sid, start, end, token)
        except QuotaExhausted as exc:
            print("額度用完（%s），probe 中止。" % exc)
            break
        rows = res["data"]
        entry = {"dataset": dataset, "stock_id": sid or "(全市場)", "range": [start, end],
                 "status": res["status"], "msg": res["msg"], "rows": len(rows),
                 "fields": sorted(rows[0].keys()) if rows else [], "sample": rows[:2]}
        report.append(entry)
        print("--- %s / %s / %s~%s" % (dataset, entry["stock_id"], start, end))
        print("    狀態=%s rows=%d %s" % (res["status"], len(rows), res["msg"]))
        if rows:
            print("    欄位：%s" % ", ".join(entry["fields"]))
            print("    範例：%s" % json.dumps(rows[0], ensure_ascii=False))
    C.write_json_atomic(os.path.join(C.DATA_DIR, "probe.json"),
                        {"probed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                         "results": report})
    print("\n已存 data/probe.json。把上面輸出貼回給 Claude（不含 token）。")
    return 0


def run_status(args):
    rows = []
    for dataset, sid in plan(C.SYMBOLS, "all"):
        path = C.raw_path(dataset, sid)
        if not os.path.isfile(path):
            rows.append((dataset, sid, "尚未下載", 0, ""))
            continue
        m = C.read_json(path).get("meta", {})
        rows.append((dataset, sid, m.get("status"), m.get("rows", 0),
                     "%s~%s" % (m.get("first_date"), m.get("last_date"))))
    for r in rows:
        print("%-42s %-5s %-8s %6s %s" % r)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token-file")
    common.add_argument("--sleep", type=float, default=2.5, help="每次呼叫間隔秒數（預設 2.5）")
    common.add_argument("--ignore-schedule-window", action="store_true")
    sub.add_parser("probe", parents=[common])
    d = sub.add_parser("download", parents=[common])
    d.add_argument("--start", default=C.DEFAULT_START)
    d.add_argument("--end")
    d.add_argument("--only", choices=["all", "price", "events"], default="all")
    d.add_argument("--symbols", nargs="*")
    d.add_argument("--max-calls", type=int, default=100)
    d.add_argument("--force", action="store_true", help="已存在的檔案也重抓")
    d.add_argument("--retry-refused", action="store_true", help="重試先前被拒的項目")
    d.add_argument("--allow-anonymous", action="store_true")
    sub.add_parser("status", parents=[common])
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        return run_probe(args)
    if args.cmd == "download":
        return run_download(args)
    if args.cmd == "status":
        return run_status(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
