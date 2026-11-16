"""B1 資料讀取與還原（只讀本地檔，不連網）。

還原方式：後復權。每個事件（除權息、分割、減資）有因子 f = 參考價 / 事件前收盤；
事件日之前的所有價格乘上 f（累乘）。分割與減資（股數改變）的成交量乘 1/f；
現金／股票股利事件不調整成交量（暫定，見 README 假設）。
事件參考價欄位名稱以 B0 probe 確認的為準；對不到欄位會明確報錯，不猜。
"""
import bisect

import common as C


class DataError(Exception):
    pass


def pick(row, names):
    for n in names:
        if n in row and row[n] not in (None, ""):
            try:
                return float(row[n])
            except (TypeError, ValueError):
                return None
    return None


def normalize_prices(raw_rows):
    """FinMind TaiwanStockPrice → [{date, open, high, low, close, volume}]（依日期排序）。
    收盤 <= 0（暫停交易等）整列丟棄，不補值。"""
    by_date = {}
    for r in raw_rows:
        d = r.get("date")
        if not d:
            continue
        o, h = pick(r, ["open"]), pick(r, ["max", "high"])
        l, c = pick(r, ["min", "low"]), pick(r, ["close"])
        v = pick(r, ["Trading_Volume", "volume"])
        if None in (h, l, c, v):
            raise DataError("價格欄位對不上（需要 max/min/close/Trading_Volume）：%s" % sorted(r.keys()))
        if c <= 0:
            continue
        by_date[d] = {"date": d, "open": o if o else c, "high": h or c, "low": l or c,
                      "close": c, "volume": v}
    return [by_date[d] for d in sorted(by_date)]


def load_events(stock_id):
    """讀三個事件資料集 → [{date, kind, before, after}]；沒有檔案就當作沒有事件。"""
    events = []
    spec = [(C.DIVIDEND_DATASET, "dividend", ["before_price"], ["after_price", "reference_price"]),
            (C.SPLIT_DATASET, "split", ["before_price"], ["after_price", "reference_price"]),
            (C.CAPRED_DATASET, "capred", ["ClosingPriceonTheLastTradingDay"],
             ["PostReductionReferencePrice"])]
    for dataset, kind, before_names, after_names in spec:
        raw = C.load_raw(dataset, stock_id)
        if not raw:
            continue
        for r in raw["data"]:
            d = r.get("date")
            if not d:
                continue
            after = pick(r, after_names)
            if not after:
                raise DataError("%s/%s 找不到參考價欄位（找過 %s；實際欄位 %s）——"
                                "請看 probe 結果後修正 b1_adjust.load_events"
                                % (dataset, stock_id, after_names, sorted(r.keys())))
            events.append({"date": d, "kind": kind, "before": pick(r, before_names), "after": after})
    # 手動備援：同檔 5 天內已有分割事件就不用
    for m in C.MANUAL_EVENTS:
        if m["stock_id"] != stock_id:
            continue
        md = _ord(m["date"])
        if any(e["kind"] == "split" and abs(_ord(e["date"]) - md) <= 5 for e in events):
            continue
        events.append({"date": m["date"], "kind": m["kind"], "before": None, "after": None,
                       "factor": m["factor"], "manual": True})
    return events


def _ord(date_str):
    y, m, d = date_str.split("-")
    import datetime
    return datetime.date(int(y), int(m), int(d)).toordinal()


def apply_adjustments(rows, events):
    """回傳 (調整後 rows, 已套用事件清單, 被丟棄事件清單)。rows 需已排序。"""
    if not rows:
        return [], [], []
    dates = [r["date"] for r in rows]
    last_date = dates[-1]
    applied, dropped, seen = [], [], set()
    for e in sorted(events, key=lambda x: (x["date"], x["kind"])):
        key = (e["date"], e["kind"])
        if key in seen:
            continue
        seen.add(key)
        if e["date"] > last_date or e["date"] <= dates[0]:
            continue  # 價格區間之外的事件不影響任何一列
        factor = e.get("factor")
        if factor is None:
            before = e.get("before")
            if not before:  # 沒給事件前收盤，用自己資料的前一個交易日收盤
                i = bisect.bisect_left(dates, e["date"]) - 1
                before = rows[i]["close"]
            factor = e["after"] / before if before else None
        if not factor or not (0.2 <= factor <= 5.0):
            dropped.append({"date": e["date"], "kind": e["kind"], "factor": factor})
            continue
        applied.append({"date": e["date"], "kind": e["kind"], "factor": factor,
                        "manual": bool(e.get("manual"))})
    out = [None] * len(rows)
    idx = len(applied) - 1
    cum_p = cum_v = 1.0
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        while idx >= 0 and applied[idx]["date"] > r["date"]:
            cum_p *= applied[idx]["factor"]
            if applied[idx]["kind"] in ("split", "capred"):
                cum_v /= applied[idx]["factor"]
            idx -= 1
        out[i] = {"date": r["date"], "open": r["open"] * cum_p, "high": r["high"] * cum_p,
                  "low": r["low"] * cum_p, "close": r["close"] * cum_p,
                  "volume": r["volume"] * cum_v, "raw_close": r["close"], "raw_volume": r["volume"]}
    return out, applied, dropped


def _tick(price, etf):
    if etf:
        return 0.01 if price < 50 else 0.05
    for limit, tick in ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0)):
        if price < limit:
            return tick
    return 5.0


def quality_report(stock_id, raw_rows, adj_rows, applied, dropped):
    """資料品質：區間、事件、還原後仍有的大跳空、原始價是否落在跳動單位上（規格待決事項 4）。"""
    jumps = []
    for i in range(1, len(adj_rows)):
        r = adj_rows[i]["close"] / adj_rows[i - 1]["close"] - 1
        if abs(r) > 0.11:
            jumps.append({"date": adj_rows[i]["date"], "ret": round(r, 4)})
    etf = stock_id.startswith("00")
    off_by_year = {}
    for r in raw_rows:
        t = _tick(r["close"], etf)
        k = r["close"] / t
        year = r["date"][:4]
        tot, off = off_by_year.get(year, (0, 0))
        off_by_year[year] = (tot + 1, off + (1 if abs(k - round(k)) > 0.02 else 0))
    return {"stock_id": stock_id, "name": C.NAMES.get(stock_id, ""), "rows": len(adj_rows),
            "first": adj_rows[0]["date"] if adj_rows else None,
            "last": adj_rows[-1]["date"] if adj_rows else None,
            "events_applied": len(applied),
            "events_by_kind": {k: sum(1 for a in applied if a["kind"] == k)
                               for k in ("dividend", "split", "capred")},
            "events_dropped": dropped,
            "jumps_after_adjust": jumps[:10], "jump_count": len(jumps),
            "off_tick_by_year": {y: round(o / t, 3) for y, (t, o) in sorted(off_by_year.items()) if o},
            }


def load_series(stock_id, adjust=True):
    """回傳 (rows, quality)。沒有價格檔或價格為空：rows=[]，quality 含 error。"""
    raw = C.load_raw(C.PRICE_DATASET, stock_id)
    if raw is None:
        return [], {"stock_id": stock_id, "name": C.NAMES.get(stock_id, ""), "rows": 0,
                    "error": "沒有價格檔（尚未下載）"}
    rows = normalize_prices(raw["data"])
    if not rows:
        status = raw.get("meta", {}).get("status")
        return [], {"stock_id": stock_id, "name": C.NAMES.get(stock_id, ""), "rows": 0,
                    "error": "價格資料為空（FinMind 狀態 %s）" % status}
    events = load_events(stock_id) if adjust else []
    adj, applied, dropped = apply_adjustments(rows, events)
    return adj, quality_report(stock_id, rows, adj, applied, dropped)
