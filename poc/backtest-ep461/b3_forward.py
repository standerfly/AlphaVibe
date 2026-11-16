"""B3 前瞻報酬。起算日是狀態確認日（T+confirm）的收盤，不是訊號日（避免前視偏誤）。"""


def bench_map(bench_rows):
    return dict((r["date"], r["close"]) for r in bench_rows)


def fwd(rows, i, h, bmap):
    """從 rows[i] 收盤起算 h 個交易日的報酬與相對基準的超額報酬；不夠天數回 None。"""
    j = i + h
    if i < 0 or j >= len(rows):
        return None
    ret = rows[j]["close"] / rows[i]["close"] - 1
    b0, b1 = bmap.get(rows[i]["date"]), bmap.get(rows[j]["date"])
    ex = ret - (b1 / b0 - 1) if b0 and b1 else None
    return ret, ex


def mfe_mae(rows, i, h):
    """起算日後 h 日內：最大有利波動（最高價）與最大不利波動（最低價），相對起算日收盤。"""
    if i + h >= len(rows):
        return None
    entry = rows[i]["close"]
    hi = max(r["high"] for r in rows[i + 1:i + h + 1])
    lo = min(r["low"] for r in rows[i + 1:i + h + 1])
    return hi / entry - 1, lo / entry - 1


def attach_forward(rows, signals, bmap, horizons, confirm, mm_h=20):
    for s in signals:
        for h in horizons:
            s["ret%d" % h] = s["ex%d" % h] = None
        s["mfe"] = s["mae"] = None
        if s["state"] == "pending":
            continue
        e = s["idx"] + confirm
        s["entry_date"] = rows[e]["date"]
        for h in horizons:
            r = fwd(rows, e, h, bmap)
            if r:
                s["ret%d" % h], s["ex%d" % h] = r
        mm = mfe_mae(rows, e, mm_h)
        if mm:
            s["mfe"], s["mae"] = mm


def mark_independent(signals, gap=20):
    """同檔同方向，與上一個獨立事件相隔不到 gap 個交易日的訊號視為同一波（重疊窗口）。"""
    last = {}
    for s in sorted(signals, key=lambda x: x["idx"]):
        k = s["direction"]
        prev = last.get(k)
        s["indep"] = prev is None or s["idx"] - prev >= gap
        if s["indep"]:
            last[k] = s["idx"]


def baseline_days(rows, bmap, horizons, start_idx=0):
    """無條件基準：同一檔每個交易日 t（從 start_idx 起）的前瞻報酬。"""
    out = []
    for t in range(start_idx, len(rows)):
        item = {"date": rows[t]["date"]}
        for h in horizons:
            r = fwd(rows, t, h, bmap)
            item["ret%d" % h], item["ex%d" % h] = r if r else (None, None)
        out.append(item)
    return out
