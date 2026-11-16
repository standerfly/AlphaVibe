"""B6 報表：CSV 明細 + 一份精簡的 summary.md（給 Stander 與 Claude 看）。"""
import csv
import os

import common as C
from b2_signals import DIR_LABEL, STATE_LABEL


def write_csv(path, rows, fields=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("")
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(dict((k, ("%.6f" % v) if isinstance(v, float) else v) for k, v in r.items()))


def _p(x):
    return C.pct(x)


def _group_md(rows, horizons, title):
    lines = ["### %s" % title, "",
             "| 方向 | 狀態 | 訊號數 | 獨立事件 | 檔數 | " + " | ".join("%d日 超額均值(n)" % h for h in horizons)
             + " | 20日 報酬均值 vs 基準 |", "|" + "---|" * (6 + len(horizons))]
    for r in rows:
        if r["n"] == 0:
            continue
        cells = ["%s (%d)" % (_p(r["mean_ex%d" % h]), r["n%d" % h]) for h in horizons]
        d20 = "%s vs %s" % (_p(r["mean_ret20"]), _p(r["base_mean_ret20"])) if "mean_ret20" in r else ""
        lines.append("| %s | %s | %d | %d | %d | %s | %s |" % (
            DIR_LABEL[r["direction"]], STATE_LABEL[r["state"]], r["n"], r["indep"], r["stocks"],
            " | ".join(cells), d20))
    return lines + [""]


def build_summary(ctx):
    """ctx：run_backtest 組好的字典。回傳 markdown 文字。"""
    H = ctx["horizons"]
    L = ["# EP461 回測結果（範圍＝庫存，只能說「在這些檔上」）", "",
         "- 資料日期：%s；清單：%s" % (ctx["data_range"], "、".join(ctx["analyzed"])),
         "- 參數：N=%(n)d、量比≥%(vr_min)s、量縮≤%(shrink)s、冷卻%(cooldown)d日、確認T+%(confirm)d" % ctx["params"],
         "- 前後半切點：%s（前半＝調整用、後半＝樣本外驗證）" % ctx["cutoff"],
         "- 還原：%s" % ctx["adjust_note"], ""]
    if ctx["insufficient"]:
        L.append("- 樣本不足／無資料：" + "；".join("%s %s" % (k, v) for k, v in ctx["insufficient"].items()))
        L.append("")
    b = ctx["baseline"]
    L.append("基準（所有日子的無條件報酬）：" + "；".join(
        "%d日 均值 %s／上漲比例 %s" % (h, _p(b[h]["ret"]["mean"]),
                                     "—" if b[h]["ret"]["win"] is None else "%.0f%%" % (b[h]["ret"]["win"] * 100))
        for h in H))
    L.append("")
    L += _group_md(ctx["group_all"], H, "C3 全期：超額報酬（相對 0050）")
    for period, name in (("first", "前半（調整期）"), ("second", "後半（樣本外）")):
        L += _group_md(ctx["group_" + period], (20,), "C3 %s：20日" % name)
    L += ["### C2 相對強弱分組（60日窗口，每20日取樣一次；只分組不下判定）", "",
          "| 分組 | n | " + " | ".join("%d日 超額均值" % h for h in H) + " |", "|" + "---|" * (2 + len(H))]
    for r in ctx["c2_all"]:
        L.append("| %s | %d | %s |" % (r["bucket"], r["n"], " | ".join(_p(r["mean_ex%d" % h]) for h in H)))
    L.append("")
    s = ctx["sens_summary"]
    if s:
        L += ["### 敏感度（N∈10/20/60、量比∈1.5/2/3、量縮∈0.5/0.7/0.9；20日超額均值，全期）", "",
              "| 方向 | 狀態 | 參數組數 | 最小 | 最大 | 正負號一致？ |", "|---|---|---|---|---|---|"]
        for r in s:
            L.append("| %s | %s | %d | %s | %s | %s |" % (
                DIR_LABEL[r["direction"]], STATE_LABEL[r["state"]], r["combos"], _p(r["min"]),
                _p(r["max"]), "是" if r["same_sign"] else "否（不穩定）"))
        L.append("")
    L += ["### 資料品質", ""]
    for q in ctx["quality"]:
        if q.get("error"):
            L.append("- %s %s：%s" % (q["stock_id"], q["name"], q["error"]))
            continue
        extra = []
        if q["jump_count"]:
            extra.append("還原後仍有 %d 次 >11%% 單日變動（例 %s）" % (
                q["jump_count"], ",".join(j["date"] for j in q["jumps_after_adjust"][:3])))
        if q["off_tick_by_year"]:
            extra.append("原始收盤不在跳動單位上的比例 %s" % q["off_tick_by_year"])
        if q["events_dropped"]:
            extra.append("丟棄事件 %d" % len(q["events_dropped"]))
        L.append("- %s %s：%s～%s，%d 列，套用事件 %s%s" % (
            q["stock_id"], q["name"], q["first"], q["last"], q["rows"], q["events_by_kind"],
            "；" + "；".join(extra) if extra else ""))
    L += ["", "### 限制（照規格第 3、8 節）", "",
          "- 這些檔是現在持有的（存活者偏誤）、多為半導體／AI 供應鏈（有效樣本遠少於檔數）、未計交易成本。",
          "- 同一波趨勢重複計入：以「獨立事件」欄為準看樣本量；每組若只有個位數事件，不下結論。",
          "- 後半期結果看過後再改門檻，該段即視為已用掉。"]
    return "\n".join(L) + "\n"
