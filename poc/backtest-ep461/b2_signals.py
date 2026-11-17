"""B2 訊號計算：C3（EP461 量價）與 C2（相對強弱）。定義照規格第 6 節。

rows 為 b1 輸出（已還原）：每列含 date/open/high/low/close/volume，依日期遞增。
"""

DIRECTIONS = ("breakout", "breakdown")
STATES = ("held_shrink", "held_noshrink", "failed", "pending")
STATE_LABEL = {"held_shrink": "守住且量縮", "held_noshrink": "守住但量未縮",
               "failed": "失敗", "pending": "待確認"}
DIR_LABEL = {"breakout": "突破", "breakdown": "跌破"}


def c3_signals(rows, n=20, vr_min=1.5, vr_win=5, cooldown=5, confirm=5, shrink=0.7,
               shrink_win=3, cooldown_mode="counted", cooldown_strict=True):
    """找出 C3 強訊號。

    - 關卡：前 n 日（不含當天）收盤的最高 Level／最低 Floor。收盤>Level 突破、<Floor 跌破。
    - 量比：當日量 / 前 vr_win 日均量（不含當天），>= vr_min 才算強訊號。
    - 收盤位置：(收盤-當日最低)/(當日最高-當日最低)。
    - 冷卻：同方向訊號 cooldown 個交易日內不重複計。規格未說清楚的兩處，以參數保留：
        cooldown_mode  "counted"＝只有被計入的訊號會重設冷卻；"all"＝任何價格突破／跌破日都重設
        cooldown_strict False＝相隔 >= cooldown 日可再計；True＝相隔 > cooldown 日才可再計
      （regression_0050.py 會用 0050 的 14 筆已知訊號自動比對哪一種吻合。）
    - 狀態：訊號日 T 後 confirm 個交易日內，突破有收盤跌回 Level 之下、或跌破有收盤站回
      Floor 之上＝失敗；否則守住。守住且 T+1..T+shrink_win 均量 / T 日量 <= shrink 為量縮。
      T+confirm 尚未發生＝待確認。
    """
    close = [r["close"] for r in rows]
    vol = [r["volume"] for r in rows]
    out = []
    last = {"breakout": None, "breakdown": None}
    for i in range(max(n, vr_win), len(rows)):
        window = close[i - n:i]
        level, floor = max(window), min(window)
        if close[i] > level:
            d = "breakout"
        elif close[i] < floor:
            d = "breakdown"
        else:
            continue
        vavg = sum(vol[i - vr_win:i]) / float(vr_win)
        ratio = vol[i] / vavg if vavg > 0 else None
        counted_vol = ratio is not None and ratio >= vr_min
        li = last[d]
        gap = None if li is None else i - li
        blocked = gap is not None and (gap <= cooldown if cooldown_strict else gap < cooldown)
        record = counted_vol and not blocked
        if cooldown_mode == "all":
            last[d] = i
        elif record:
            last[d] = i
        if not record:
            continue
        r = rows[i]
        span = r["high"] - r["low"]
        pos = (r["close"] - r["low"]) / span if span > 0 else 0.5
        sig = {"date": r["date"], "idx": i, "direction": d, "close": r["close"],
               "level": level, "floor": floor, "ratio": ratio, "pos": pos,
               "state": "pending", "shrink_ratio": None}
        if i + confirm < len(rows):
            failed = False
            for j in range(i + 1, i + confirm + 1):
                if d == "breakout" and close[j] < level:
                    failed = True
                if d == "breakdown" and close[j] > floor:
                    failed = True
            nxt = vol[i + 1:i + 1 + shrink_win]
            sr = (sum(nxt) / len(nxt)) / vol[i] if vol[i] > 0 and nxt else None
            sig["shrink_ratio"] = sr
            if failed:
                sig["state"] = "failed"
            else:
                sig["state"] = "held_shrink" if (sr is not None and sr <= shrink) else "held_noshrink"
        out.append(sig)
    return out


def align_returns(stock_rows, bench_rows):
    """以共同日期對齊，回傳 [(date, 個股報酬, 基準報酬)]（第一個共同日沒有報酬）。"""
    bmap = dict((r["date"], r["close"]) for r in bench_rows)
    pairs = [(r["date"], r["close"], bmap[r["date"]]) for r in stock_rows if r["date"] in bmap]
    out = []
    for k in range(1, len(pairs)):
        d, s1, b1 = pairs[k]
        _, s0, b0 = pairs[k - 1]
        out.append((d, s1 / s0 - 1, b1 / b0 - 1))
    return out


def c2_metrics(rets, k, window, min_days=8):
    """在 rets（align_returns 結果）第 k 個位置（含）往前 window 天算 C2。
    基準上漲日或下跌日少於 min_days 天，對應指標標 None（樣本不足）。"""
    if k + 1 < window:
        return None
    seg = rets[k + 1 - window:k + 1]
    up = [(s, b) for _, s, b in seg if b > 0]
    dn = [(s, b) for _, s, b in seg if b < 0]
    cs = cb = 1.0
    for _, s, b in seg:
        cs *= 1 + s
        cb *= 1 + b
    up_cap = (sum(s for s, _ in up) / sum(b for _, b in up)) if len(up) >= min_days else None
    dn_cap = (sum(s for s, _ in dn) / sum(b for _, b in dn)) if len(dn) >= min_days else None
    resil = (sum(1 for s, b in dn if s > b) / float(len(dn))) if len(dn) >= min_days else None
    return {"date": seg[-1][0], "up_capture": up_cap, "down_capture": dn_cap,
            "resilience": resil, "cum_rel": cs / cb - 1, "n_up": len(up), "n_down": len(dn)}


C2_BUCKETS = ("強·抗跌", "強·不抗跌", "弱·抗跌", "弱·不抗跌")


def c2_bucket(m):
    """第一階段只用無門檻的二分：累計相對報酬是否 >0、下跌捕捉率是否 <1。不下判定，只分組。"""
    if m is None or m["down_capture"] is None:
        return None
    strong = m["cum_rel"] > 0
    resilient = m["down_capture"] < 1
    return ("強" if strong else "弱") + "·" + ("抗跌" if resilient else "不抗跌")
