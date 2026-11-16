#!/usr/bin/env python3
"""回歸驗證：用 0050 的 14 筆已知訊號（規格第 7 節）檢查 B2 程式。

規格的 14 筆是用「2025-06-18 分割後、未還原」的原始價在對話裡手算的，所以這裡也用
原始價、只取 2025-06-18～2026-11-13。規格沒說清楚的冷卻細節（見 b2_signals.c3_signals），
會自動試 4 種組合，印出哪一種完全吻合；都不吻合就逐筆列出差異（先查資料、再查程式）。
結果同時存 out/regression_0050.txt。結束碼：0 有一種組合完全吻合；1 無；3 沒資料。
"""
import itertools
import os
import sys

import b1_adjust
import b2_signals as B2
import b3_forward as B3
import common as C

START, END = "2025-06-18", "2026-11-13"
EXPECTED_DAYS = 344
EXPECTED = [  # (日期, 方向, 量比, 收盤位置, 狀態)
    ("2025-07-16", "breakout", 1.67, 0.45, "held_noshrink"),
    ("2025-08-07", "breakout", 1.71, 0.84, "held_shrink"),
    ("2025-09-10", "breakout", 1.58, 0.92, "held_noshrink"),
    ("2025-11-14", "breakdown", 2.68, 0.60, "held_noshrink"),
    ("2026-01-05", "breakout", 3.14, 0.73, "held_shrink"),
    ("2026-02-23", "breakout", 2.02, 0.16, "held_shrink"),
    ("2026-03-31", "breakdown", 2.32, 0.15, "failed"),
    ("2026-04-08", "breakout", 1.55, 0.96, "held_shrink"),
    ("2026-04-27", "breakout", 1.81, 0.19, "held_shrink"),
    ("2026-07-17", "breakdown", 4.55, 0.05, "failed"),
    ("2026-07-28", "breakdown", 4.96, 0.17, "failed"),
    ("2026-09-07", "breakout", 1.58, 0.91, "failed"),
    ("2026-09-21", "breakout", 1.64, 0.94, "held_shrink"),
    ("2026-10-30", "breakdown", 2.23, 0.76, "held_noshrink"),
]
EXPECTED_BASE = {5: (0.0120, 0.65, 339), 10: (0.0236, 0.68, 334), 20: (0.0507, 0.80, 324)}


def compare(sigs):
    got = dict((s["date"], s) for s in sigs if s["state"] != "pending" or True)
    exp = dict((e[0], e) for e in EXPECTED)
    missing = sorted(d for d in exp if d not in got)
    extra = sorted(d for d in got if d not in exp)
    diffs = []
    for d, (_, direction, ratio, pos, state) in sorted(exp.items()):
        s = got.get(d)
        if not s:
            continue
        probs = []
        if s["direction"] != direction:
            probs.append("方向 %s≠%s" % (s["direction"], direction))
        if abs(s["ratio"] - ratio) > 0.011:
            probs.append("量比 %.2f≠%.2f" % (s["ratio"], ratio))
        if abs(s["pos"] - pos) > 0.011:
            probs.append("位置 %.2f≠%.2f" % (s["pos"], pos))
        if s["state"] != state:
            probs.append("狀態 %s≠%s" % (s["state"], state))
        if probs:
            diffs.append((d, probs))
    return missing, extra, diffs


def main():
    raw = C.load_raw(C.PRICE_DATASET, C.BENCH)
    if raw is None:
        print("沒有 0050 價格檔，先跑 b0_download.py download。")
        return 3
    allrows = b1_adjust.normalize_prices(raw["data"])
    rows = [r for r in allrows if START <= r["date"] <= END]
    lines = ["0050 回歸驗證：%s～%s 共 %d 個交易日（規格 %d）" % (
        rows[0]["date"] if rows else "?", rows[-1]["date"] if rows else "?", len(rows), EXPECTED_DAYS)]
    if len(rows) != EXPECTED_DAYS:
        lines.append("  ⚠ 交易日數與規格不同：以下比對可能失準，先確認資料區間／缺漏。")
    if len(rows) < 30:
        print("\n".join(lines + ["資料太少，無法驗證。"]))
        return 3

    bmap = B3.bench_map(rows)
    base_ok = True
    for h, (mean, up, n) in EXPECTED_BASE.items():
        b = [x["ret%d" % h] for x in B3.baseline_days(rows, bmap, (h,)) if x["ret%d" % h] is not None]
        m, u = sum(b) / len(b), sum(1 for x in b if x > 0) / float(len(b))
        ok = len(b) == n and abs(m - mean) < 0.0006 and abs(u - up) < 0.006
        base_ok &= ok
        lines.append("  基準 %2d 日：均值 %+.2f%%（規格 %+.2f%%）上漲比例 %.0f%%（規格 %.0f%%）n=%d（規格 %d） %s" % (
            h, m * 100, mean * 100, u * 100, up * 100, len(b), n, "OK" if ok else "不符"))

    p = C.PARAMS
    matched = None
    for mode, strict in itertools.product(("counted", "all"), (False, True)):
        sigs = B2.c3_signals(rows, n=p["n"], vr_min=p["vr_min"], vr_win=p["vr_win"], cooldown=p["cooldown"],
                             confirm=p["confirm"], shrink=p["shrink"], shrink_win=p["shrink_win"],
                             cooldown_mode=mode, cooldown_strict=strict)
        missing, extra, diffs = compare(sigs)
        exact = not (missing or extra or diffs) and len(sigs) == len(EXPECTED)
        lines.append("  組合 冷卻=%s、%s：訊號 %d 筆（規格 14）→ %s" % (
            mode, "相隔>5日" if strict else "相隔>=5日", len(sigs), "完全吻合" if exact else "不吻合"))
        if exact and matched is None:
            matched = (mode, strict)
        if not exact and (mode, strict) == ("counted", False):
            lines.append("    缺少：%s" % (missing or "無"))
            lines.append("    多出：%s" % (extra or "無"))
            for d, probs in diffs:
                lines.append("    %s：%s" % (d, "；".join(probs)))
    if matched:
        lines.append("結論：B2 與規格 14 筆完全吻合（冷卻=%s、%s）。請把這組寫回規格定義。" % (
            matched[0], "相隔>5日" if matched[1] else "相隔>=5日"))
    else:
        lines.append("結論：沒有任何組合完全吻合。依規格的註記，先查資料（規格那組是手抄的）再查程式；"
                     "把本檔貼回給 Claude。")
    # 資訊：用還原後資料（含配息調整）訊號會不會變
    adj, _, _ = b1_adjust.load_series(C.BENCH, adjust=True)
    adj_rows = [r for r in adj if START <= r["date"] <= END]
    if adj_rows:
        mode, strict = matched or ("counted", False)
        s_raw = B2.c3_signals(rows, cooldown_mode=mode, cooldown_strict=strict)
        s_adj = B2.c3_signals(adj_rows, cooldown_mode=mode, cooldown_strict=strict)
        a, b = set((s["date"], s["direction"]) for s in s_raw), set((s["date"], s["direction"]) for s in s_adj)
        lines.append("（參考）同一區間改用還原價：訊號 %d 筆；與原始價差異 +%s −%s" % (
            len(s_adj), sorted(b - a) or "無", sorted(a - b) or "無"))
    text = "\n".join(lines)
    print(text)
    os.makedirs(C.OUT_DIR, exist_ok=True)
    with open(os.path.join(C.OUT_DIR, "regression_0050.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return 0 if matched and base_ok else 1


if __name__ == "__main__":
    sys.exit(main())
