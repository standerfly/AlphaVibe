"""現價在歷史收盤價區間中的相對位置（FR-007~FR-009）。

設計原則同 pnl.py：**純函式，不碰 I/O**——輸入是
KBStore.get_cached_price_history() 的列與現價 dict，輸出結果 dict。

## 為什麼自己寫 percentile_rank 而不是重用 review_engine._percentile

`review_engine._percentile(values, pct)` 是「給百分位求數值」（例如求
第 90 百分位是多少），本模組需要的是**反方向**：「給數值求它排在第幾
百分位」。兩者互為反函數，repo 內原本沒有後者的實作，因此在此新增
一個小函式，不是重寫既有邏輯。門檻常數則直接沿用 review_engine，
避免另立一套標準。

## 三段式降級（沿用 _downside_risk 的既有模式）

    樣本 >= PERCENTILE_MIN_POINTS(30) → ok
    MIN_PER_HISTORY_POINTS(6) <= 樣本 < 30 → limited（給值，但 basis 明講不足）
    樣本 < 6                          → insufficient（percentile 必須是 None）
    完全沒有資料                      → no_data

**絕不能在資料不足時回 0**：0 會被讀成「現價位於歷史最低點」，意思
完全相反。這是 FR-009 的核心風險，tests/test_price_position.py 的
InsufficientDataTest 專門守這件事。

## 已知限制

stock_price_history 只有收盤價（無開高低與成交量），且實測最長約
100 個交易日、只有 39 檔有資料。所以本模組給的是「近期區間位置」而非
「長期估值定位」；FR-014 加長排程抓取窗口後會隨時間改善。
"""
from review_engine import MIN_PER_HISTORY_POINTS, PERCENTILE_MIN_POINTS

from pnl import resolve_current_price


def percentile_rank(values, target):
    """target 在 values 中的百分位排名（0~100）。

    用「小於的個數 + 相等個數的一半」除以總數（mid-rank 法），
    這樣重複值不會讓排名偏向任一端。values 為空回 None。
    """
    if not values:
        return None
    total = len(values)
    below = sum(1 for v in values if v < target)
    equal = sum(1 for v in values if v == target)
    return (below + 0.5 * equal) / total * 100.0


def _clean_closes(history_rows):
    """濾掉 None 與非正數收盤價。

    比照 review_engine._downside_risk 過濾 FinMind 0.0 sentinel 的既有
    做法——髒值混進樣本會讓百分位失真。
    """
    closes = []
    for row in (history_rows or []):
        close = row.get("close")
        if close is None:
            continue
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue
        if value > 0:
            closes.append(value)
    return closes


def compute(code, history_rows, prices):
    """算單一標的的價位定位。

    history_rows：get_cached_price_history() 的回傳（依日期升冪）。
    prices：get_stock_prices() 的回傳；查無現價時退回歷史最後一筆收盤價，
    並在 basis 說明，讓使用者知道用的不是即時報價。
    """
    rows = [r for r in (history_rows or []) if r.get("close") is not None]
    closes = _clean_closes(history_rows)
    sample_size = len(closes)

    result = {
        "code": code, "status": "no_data", "percentile": None,
        "current_price": None, "price_date": None,
        "sample_size": sample_size, "range_start": None, "range_end": None,
        "low": None, "high": None, "basis": "",
    }

    if sample_size == 0:
        result["basis"] = "無任何歷史收盤價快取，無法判斷"
        return result

    result["range_start"] = rows[0].get("date") if rows else None
    result["range_end"] = rows[-1].get("date") if rows else None
    result["low"] = min(closes)
    result["high"] = max(closes)

    current_price, price_date = resolve_current_price(code, prices)
    price_source = "現價快取"
    if current_price is None:
        current_price = closes[-1]
        price_date = result["range_end"]
        price_source = "歷史最後一筆收盤價（現價快取查無資料）"
    result["current_price"] = current_price
    result["price_date"] = price_date

    range_desc = "%s~%s" % (result["range_start"], result["range_end"])

    if sample_size < MIN_PER_HISTORY_POINTS:
        result["status"] = "insufficient"
        # percentile 維持 None——回 0 會被誤讀為「在歷史最低點」
        result["basis"] = ("僅 %d 筆收盤價（%s），未達 %d 筆下限，資料不足無法判斷"
                           % (sample_size, range_desc, MIN_PER_HISTORY_POINTS))
        return result

    rank = percentile_rank(closes, current_price)
    result["percentile"] = round(rank, 2) if rank is not None else None

    if sample_size < PERCENTILE_MIN_POINTS:
        result["status"] = "limited"
        result["basis"] = ("以 %d 筆收盤價計算（%s），樣本不足 %d 筆，"
                           "參考價值有限；價位來源：%s"
                           % (sample_size, range_desc, PERCENTILE_MIN_POINTS,
                              price_source))
    else:
        result["status"] = "ok"
        result["basis"] = ("以 %d 筆收盤價計算（%s）；價位來源：%s"
                           % (sample_size, range_desc, price_source))
    return result


def compute_all(history_by_code, prices):
    """全部標的的價位定位（FR-011）。

    history_by_code：{code: history_rows}。每檔獨立 try 保護，
    單一標的的問題不影響其他標的。
    """
    positions = []
    summary = {"ok": 0, "limited": 0, "insufficient": 0, "no_data": 0,
               "error": 0}
    for code in sorted(history_by_code or {}):
        try:
            item = compute(code, history_by_code.get(code), prices)
        except Exception as exc:  # 單檔失敗不影響其他檔
            item = {"code": code, "status": "error", "percentile": None,
                    "current_price": None, "price_date": None,
                    "sample_size": 0, "range_start": None, "range_end": None,
                    "low": None, "high": None,
                    "basis": "計算失敗：%s" % exc}
        positions.append(item)
        status = item.get("status", "error")
        summary[status] = summary.get(status, 0) + 1

    return {"count": len(positions), "positions": positions,
            "summary": summary}
