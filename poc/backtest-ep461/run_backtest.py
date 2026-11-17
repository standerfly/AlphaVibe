#!/usr/bin/env python3
"""回測主程式：讀 data/raw → B1 還原 → B2～B6 → out/。不連網、不碰正式庫，結果可重現。

用法：python3 run_backtest.py [--no-sensitivity] [--symbols 2308 2337 ...] [--min-rows 250]
"""
import argparse
import hashlib
import json
import os
import sys

import b1_adjust
import b4_b5_stats as S
import b6_report as R
import common as C
from b3_forward import bench_map


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()[:16]


def sens_summary(sens_rows):
    groups, dgroups = {}, {}
    for r in sens_rows:
        if r["period"] != "all" or r["mean_ex"] is None:
            continue
        groups.setdefault((r["direction"], r["state"]), []).append(r["mean_ex"])
        if r.get("delta_ex") is not None:
            dgroups.setdefault((r["direction"], r["state"]), []).append(r["delta_ex"])
    out = []
    for (d, st), v in sorted(groups.items()):
        dv = dgroups.get((d, st)) or [None]
        dv = [x for x in dv if x is not None] or [0.0]
        out.append({"direction": d, "state": st, "combos": len(v), "min": min(v), "max": max(v),
                    "same_sign": min(v) > 0 or max(v) < 0,
                    "dmin": min(dv), "dmax": max(dv), "dsame": min(dv) > 0 or max(dv) < 0})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--min-rows", type=int, default=250)
    ap.add_argument("--no-sensitivity", action="store_true")
    ap.add_argument("--no-adjust", action="store_true", help="只供除錯；正式回測不得用未還原資料")
    args = ap.parse_args(argv)

    symbols = [s for s in (args.symbols or C.SYMBOLS) if s != C.BENCH]
    bench_rows, bq = b1_adjust.load_series(C.BENCH, adjust=not args.no_adjust)
    if not bench_rows:
        print("沒有基準 0050 的價格檔：%s。先跑 b0_download.py download。" % bq.get("error"))
        return 3
    bmap = bench_map(bench_rows)

    series, quality, insufficient = {}, [bq], {}
    for sid in symbols:
        rows, q = b1_adjust.load_series(sid, adjust=not args.no_adjust)
        quality.append(q)
        if not rows:
            insufficient[sid] = q.get("error", "無資料")
        elif len(rows) < args.min_rows:
            insufficient[sid] = "只有 %d 列（< %d）：樣本不足" % (len(rows), args.min_rows)
        else:
            series[sid] = rows
    if not series:
        print("沒有任何可分析的個股。")
        return 3

    params, H = dict(C.PARAMS), C.HORIZONS
    cutoff = S.split_cutoff(series)
    sigs, base = S.run_all(series, bmap, params, H)
    group_all, bs = S.group_table(sigs, base, H)
    group_first, _ = S.group_table(sigs, base, H, cutoff, "first")
    group_second, _ = S.group_table(sigs, base, H, cutoff, "second")
    c2 = S.c2_samples(series, bench_rows, bmap, H)
    c2_all = S.c2_table(c2, H)
    sens = [] if args.no_sensitivity else S.sensitivity(
        series, bmap, params, C.SENS_N, C.SENS_VR, C.SENS_SHRINK, cutoff)

    os.makedirs(C.OUT_DIR, exist_ok=True)
    out = lambda name: os.path.join(C.OUT_DIR, name)
    R.write_csv(out("signals.csv"), sorted(sigs, key=lambda s: (s["stock_id"], s["date"])),
                ["stock_id", "date", "direction", "state", "ratio", "pos", "level", "floor", "shrink_ratio",
                 "indep", "entry_date"] + ["ret%d" % h for h in H] + ["ex%d" % h for h in H] + ["mfe", "mae"])
    R.write_csv(out("group_all.csv"), group_all)
    R.write_csv(out("group_first_half.csv"), group_first)
    R.write_csv(out("group_second_half.csv"), group_second)
    R.write_csv(out("per_stock.csv"), S.per_stock_table(sigs, base, H))
    R.write_csv(out("c2_buckets.csv"), c2_all)
    R.write_csv(out("sensitivity.csv"), sens)
    R.write_csv(out("data_quality.csv"), [dict((k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                                              for k, v in q.items()) for q in quality])

    firsts = [q["first"] for q in quality if q.get("first")]
    lasts = [q["last"] for q in quality if q.get("last")]
    ctx = {"horizons": H, "params": params, "cutoff": cutoff, "baseline": bs,
           "analyzed": sorted(series), "insufficient": insufficient,
           "data_range": "%s ～ %s（含 0050 基準）" % (min(firsts), max(lasts)),
           "adjust_note": "未還原（僅除錯）" if args.no_adjust else
           "依 FinMind 除權息／分割／減資參考價後復權（因子見 data_quality.csv）",
           "group_all": group_all, "group_first": group_first, "group_second": group_second,
           "c2_all": c2_all, "sens_summary": sens_summary(sens), "quality": quality}
    with open(out("summary.md"), "w", encoding="utf-8") as fh:
        fh.write(R.build_summary(ctx))
    manifest = {"params": params, "horizons": list(H), "cutoff": cutoff, "symbols": sorted(series),
                "insufficient": insufficient, "adjusted": not args.no_adjust,
                "raw_files": dict(("%s/%s" % (d, s), _sha(C.raw_path(d, s)))
                                  for d in [C.PRICE_DATASET] + C.EVENT_DATASETS
                                  for s in C.SYMBOLS if os.path.isfile(C.raw_path(d, s)))}
    with open(out("manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print("完成：%d 檔、%d 個 C3 訊號。結果在 %s（summary.md 先看）。" % (len(series), len(sigs), C.OUT_DIR))
    if insufficient:
        print("樣本不足／無資料：%s" % insufficient)
    return 0


if __name__ == "__main__":
    sys.exit(main())
