"""B4 分組統計與 B5 切分／敏感度。"""
import statistics

from b2_signals import DIRECTIONS, STATES, align_returns, c2_bucket, c2_metrics, c3_signals, C2_BUCKETS
from b3_forward import attach_forward, baseline_days, fwd, mark_independent


def summarize(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return {"n": 0, "mean": None, "median": None, "win": None}
    return {"n": len(v), "mean": sum(v) / len(v), "median": statistics.median(v),
            "win": sum(1 for x in v if x > 0) / float(len(v))}


def run_all(series, bmap, params, horizons):
    """series: {代號: 已還原 rows}。回傳 (全部 C3 訊號, 全部基準日)。"""
    sigs, base = [], []
    for sid, rows in series.items():
        s = c3_signals(rows, n=params["n"], vr_min=params["vr_min"], vr_win=params["vr_win"],
                       cooldown=params["cooldown"], confirm=params["confirm"],
                       shrink=params["shrink"], shrink_win=params["shrink_win"])
        attach_forward(rows, s, bmap, horizons, params["confirm"])
        mark_independent(s)
        for x in s:
            x["stock_id"] = sid
        sigs += s
        for b in baseline_days(rows, bmap, horizons, start_idx=params["n"]):
            b["stock_id"] = sid
            base.append(b)
    return sigs, base


def split_cutoff(series):
    """前後半切點：所有個股交易日合併後的中位日期（兩半的資料量大致相等）。"""
    dates = sorted(r["date"] for rows in series.values() for r in rows)
    return dates[len(dates) // 2] if dates else None


def in_period(date, cutoff, period):
    if period == "all" or cutoff is None:
        return True
    return date < cutoff if period == "first" else date >= cutoff


def baseline_stats(base, horizons, cutoff=None, period="all"):
    b = [x for x in base if in_period(x["date"], cutoff, period)]
    return dict((h, {"ret": summarize([x["ret%d" % h] for x in b]),
                     "ex": summarize([x["ex%d" % h] for x in b])}) for h in horizons)


def group_table(sigs, base, horizons, cutoff=None, period="all"):
    """每個 (方向, 狀態) 一列：訊號數、獨立事件數、各窗口報酬／超額統計、與基準的差、MFE／MAE。"""
    bs = baseline_stats(base, horizons, cutoff, period)
    rows = []
    for d in DIRECTIONS:
        for st in STATES:
            g = [s for s in sigs if s["direction"] == d and s["state"] == st
                 and in_period(s["date"], cutoff, period)]
            row = {"direction": d, "state": st, "n": len(g),
                   "indep": sum(1 for s in g if s.get("indep")),
                   "stocks": len(set(s["stock_id"] for s in g))}
            for h in horizons:
                r = summarize([s["ret%d" % h] for s in g])
                e = summarize([s["ex%d" % h] for s in g])
                row["n%d" % h] = r["n"]
                row["mean_ret%d" % h] = r["mean"]
                row["median_ret%d" % h] = r["median"]
                row["win_ret%d" % h] = r["win"]
                row["mean_ex%d" % h] = e["mean"]
                row["median_ex%d" % h] = e["median"]
                row["win_ex%d" % h] = e["win"]
                bm = bs[h]["ret"]["mean"]
                row["base_mean_ret%d" % h] = bm
                row["delta_ret%d" % h] = (r["mean"] - bm) if (r["mean"] is not None and bm is not None) else None
                bx = bs[h]["ex"]["mean"]  # 同批個股、同期間所有日子的無條件超額
                row["base_mean_ex%d" % h] = bx
                row["delta_ex%d" % h] = (e["mean"] - bx) if (e["mean"] is not None and bx is not None) else None
            row["mean_mfe"] = summarize([s["mfe"] for s in g])["mean"]
            row["mean_mae"] = summarize([s["mae"] for s in g])["mean"]
            rows.append(row)
    return rows, bs


def per_stock_table(sigs, base, horizons, h=20):
    out = []
    for sid in sorted(set(s["stock_id"] for s in sigs) | set(b["stock_id"] for b in base)):
        g = [s for s in sigs if s["stock_id"] == sid]
        bb = [b for b in base if b["stock_id"] == sid]
        row = {"stock_id": sid, "signals": len(g), "indep": sum(1 for s in g if s.get("indep")),
               "base_mean_ret%d" % h: summarize([b["ret%d" % h] for b in bb])["mean"],
               "base_n": len(bb)}
        for d in DIRECTIONS:
            for st in STATES[:3]:
                x = [s for s in g if s["direction"] == d and s["state"] == st]
                row["%s_%s_n" % (d, st)] = len(x)
                row["%s_%s_mean_ex%d" % (d, st, h)] = summarize([s["ex%d" % h] for s in x])["mean"]
        out.append(row)
    return out


def c2_samples(series, bench_rows, bmap, horizons, window=60, step=20):
    """C2 相對強弱分組：每隔 step 個交易日取一次（降低重疊窗口），用截至當日的資料分組，
    再看之後的報酬。第一階段只分組、不下判定。"""
    out = []
    for sid, rows in series.items():  # series 不含基準本身
        rets = align_returns(rows, bench_rows)
        idx_of = dict((r["date"], i) for i, r in enumerate(rows))
        for k in range(window - 1, len(rets), step):
            m = c2_metrics(rets, k, window)
            bucket = c2_bucket(m)
            if bucket is None:
                continue
            i = idx_of[m["date"]]
            item = {"stock_id": sid, "date": m["date"], "bucket": bucket,
                    "cum_rel": m["cum_rel"], "down_capture": m["down_capture"]}
            for h in horizons:
                r = fwd(rows, i, h, bmap)
                item["ret%d" % h], item["ex%d" % h] = r if r else (None, None)
            out.append(item)
    return out


def c2_table(samples, horizons, cutoff=None, period="all"):
    s_all = [s for s in samples if in_period(s["date"], cutoff, period)]
    rows = []
    for b in C2_BUCKETS + ("全部",):
        g = [s for s in s_all if b == "全部" or s["bucket"] == b]
        row = {"bucket": b, "n": len(g)}
        for h in horizons:
            r = summarize([s["ret%d" % h] for s in g])
            e = summarize([s["ex%d" % h] for s in g])
            row["mean_ret%d" % h] = r["mean"]
            row["mean_ex%d" % h] = e["mean"]
            row["win_ret%d" % h] = r["win"]
        rows.append(row)
    return rows


def sensitivity(series, bmap, base_params, grid_n, grid_vr, grid_shrink, cutoff, h=20):
    """B5 門檻敏感度：每組參數重跑訊號，輸出 h 日窗口的統計（全期／前半／後半）。"""
    out = []
    for n in grid_n:
        for vr in grid_vr:
            for sh in grid_shrink:
                p = dict(base_params, n=n, vr_min=vr, shrink=sh)
                sigs, base = run_all(series, bmap, p, (h,))
                for period in ("all", "first", "second"):
                    rows, bs = group_table(sigs, base, (h,), cutoff, period)
                    for r in rows:
                        if r["state"] == "pending":
                            continue
                        out.append({"n_lookback": n, "vr_min": vr, "shrink": sh, "period": period,
                                    "direction": r["direction"], "state": r["state"],
                                    "signals": r["n"], "indep": r["indep"],
                                    "mean_ret": r["mean_ret%d" % h], "mean_ex": r["mean_ex%d" % h],
                                    "median_ex": r["median_ex%d" % h],
                                    "delta_ex": r["delta_ex%d" % h],
                                    "base_mean_ret": r["base_mean_ret%d" % h]})
    return out
