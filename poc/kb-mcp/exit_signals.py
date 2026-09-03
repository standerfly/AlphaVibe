"""進出場訊號層：停損停利門檻、營收趨勢、基本面與價格背離（階段B）。

設計原則同階段A 的 pnl.py／price_position.py：**純函式，不碰 I/O**
——輸入是已經查好的資料，輸出是結果 dict。資料庫存取留給呼叫端。

## 零新增外部呼叫（本階段最高風險項）

三種訊號的資料全部來自既有已載入或已快取的來源：
- 門檻觸發 → `stock_prices` 表（每日流程本來就會刷新）
- 營收趨勢 → `fetch_revenue_yoy()` 的結果（general_review 已呼叫過、20 小時快取）
- 背離偵測 → 上面兩者 ＋ 階段A 的 price_position（讀 stock_price_history 快取）

**任何一個新訊號都不得自己去打外部 API。** 階段A 曾因「從參數語意推論
呼叫次數」而讓正式排程慢了 29 分鐘（見 specs/001-entry-exit-foundation/
research.md R-006），本階段以 tests 中的呼叫次數實測守住這條線。

## 三個容易誤判的地方

1. **「尚未設定門檻」不等於安全**：沒設定就是 `not_set`，不得回
   `within_range`，也不得填任何預設門檻值（FR-003）。
2. **單邊資料不足不能下結論**：背離要同時有營收趨勢與股價位置，
   任一邊不足就是 `insufficient`（FR-006）。
3. **只有實際觸發才填 suggested_action**：那是首頁「今日重點」的篩選
   條件，全填會把首頁灌爆（見 research.md R-006）。
"""

# 背離判斷的高低檔門檻（百分位）。集中在這裡而非散落在判斷式裡，
# 方便日後調整與測試。
DIVERGENCE_LOW_PERCENTILE = 30.0
DIVERGENCE_HIGH_PERCENTILE = 70.0

# 營收趨勢觀察期數（FR-007：從既有的 3 期擴大為 6 期）。
# 上限受既有資料窗口限制——實測 REVENUE_YOY_LOOKBACK_DAYS=800 每檔
# 可得 14 筆非 null 年增率，故 6 期在既有資料內、零額外呼叫。
TREND_PERIODS = 6
# 少於這個期數不判斷趨勢（沿用既有 MIN_YOY_POINTS 的語意）
TREND_MIN_POINTS = 3
# 斜率絕對值小於此值視為持平（年增率是小數，0.01 ＝ 每期 1 個百分點）
TREND_FLAT_SLOPE = 0.01


# ---------------------------------------------------------------- 門檻

def evaluate_threshold(code, threshold, prices):
    """判斷單一標的的停損停利狀態。

    threshold：`get_exit_threshold(code)` 的結果，未設定時為 None。
    prices：`get_stock_prices()` 的結果。

    status 判定順序（見 specs/002-entry-exit-signals/data-model.md）：
      not_set → no_price → triggered_stop_loss → triggered_take_profit
      → within_range
    """
    result = {
        "code": code, "status": "not_set",
        "stop_loss": None, "take_profit": None,
        "current_price": None, "price_date": None,
        "distance_pct": None, "reason": None, "set_at": None,
    }

    if not threshold:
        # FR-003：沒設定就是沒設定，不得填預設值、不得回 within_range
        result["detail"] = "尚未設定停損停利門檻"
        return result

    stop_loss = threshold.get("stop_loss")
    take_profit = threshold.get("take_profit")
    result.update({"stop_loss": stop_loss, "take_profit": take_profit,
                   "reason": threshold.get("reason"),
                   "set_at": threshold.get("created_at")})

    price_row = (prices or {}).get(code) or {}
    current_price = price_row.get("price")
    result["current_price"] = current_price
    result["price_date"] = price_row.get("price_date")

    if current_price is None:
        result["status"] = "no_price"
        result["detail"] = "已設定門檻，但查無現價，無法判斷是否觸發"
        return result

    current_price = float(current_price)

    if stop_loss is not None and current_price <= float(stop_loss):
        result["status"] = "triggered_stop_loss"
        result["distance_pct"] = round(
            (current_price - float(stop_loss)) / float(stop_loss) * 100, 2)
        result["detail"] = ("已觸發停損：現價 %.2f 跌破門檻 %.2f（超出 %.2f%%）"
                            % (current_price, float(stop_loss),
                               abs(result["distance_pct"])))
        return result

    if take_profit is not None and current_price >= float(take_profit):
        result["status"] = "triggered_take_profit"
        result["distance_pct"] = round(
            (current_price - float(take_profit)) / float(take_profit) * 100, 2)
        result["detail"] = ("已觸發停利：現價 %.2f 達到門檻 %.2f（超出 %.2f%%）"
                            % (current_price, float(take_profit),
                               result["distance_pct"]))
        return result

    result["status"] = "within_range"
    # 距離「最近的那個門檻」還有多少，讓 PO 知道逼近程度
    distances = []
    if stop_loss is not None:
        distances.append(((current_price - float(stop_loss)) / current_price * 100,
                          "停損 %.2f" % float(stop_loss)))
    if take_profit is not None:
        distances.append(((float(take_profit) - current_price) / current_price * 100,
                          "停利 %.2f" % float(take_profit)))
    nearest = min(distances, key=lambda d: abs(d[0])) if distances else None
    if nearest:
        result["distance_pct"] = round(nearest[0], 2)
        result["detail"] = ("未觸發：現價 %.2f，距離%s 尚有 %.2f%%"
                            % (current_price, nearest[1], abs(nearest[0])))
    else:
        result["detail"] = "未觸發"
    return result


def evaluate_all_thresholds(thresholds, prices):
    """批次判斷。單檔失敗不影響其他檔（FR-011）。"""
    codes = sorted((thresholds or {}).keys())
    positions = []
    summary = {"not_set": 0, "no_price": 0, "triggered_stop_loss": 0,
               "triggered_take_profit": 0, "within_range": 0, "error": 0}
    for code in codes:
        try:
            item = evaluate_threshold(code, thresholds.get(code), prices)
        except Exception as exc:
            item = {"code": code, "status": "error",
                    "detail": "門檻判斷失敗：%s" % exc}
        positions.append(item)
        summary[item.get("status", "error")] = \
            summary.get(item.get("status", "error"), 0) + 1
    return {"count": len(positions), "positions": positions, "summary": summary}


# ------------------------------------------------------------ 營收趨勢

def _slope(values):
    """最小平方法斜率，手寫不依賴外部套件（沿用 review_engine 的做法）。"""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / float(n)
    numerator = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def revenue_trend(values, periods=TREND_PERIODS):
    """營收年增率趨勢（FR-007）。

    values：依時間升冪的年增率（已濾掉 None）。
    判斷準則＝**斜率方向 ＋ 最新值相對窗口中位數的位置**，兩者一致才
    認定方向。只看斜率會把「先崩後穩」誤判成持續下滑（既有的「最近 3 期
    嚴格遞減」則相反，條件太窄、實測 39 檔只有 1 檔觸發）。

    **不新增任何外部呼叫**——values 由呼叫端從既有的年增率結果取得。
    """
    clean = [v for v in (values or []) if v is not None]
    if len(clean) < TREND_MIN_POINTS:
        return {"direction": "insufficient", "periods_used": len(clean),
                "values": clean, "slope": None, "latest_vs_median": None,
                "detail": "資料不足，無法判斷趨勢（僅 %d 期，需 %d 期）"
                          % (len(clean), TREND_MIN_POINTS)}

    window = clean[-periods:]
    slope = _slope(window)
    median = _median(window)
    latest = window[-1]
    latest_vs_median = latest - median

    if slope < -TREND_FLAT_SLOPE and latest_vs_median < 0:
        direction = "falling"
    elif slope > TREND_FLAT_SLOPE and latest_vs_median > 0:
        direction = "rising"
    else:
        direction = "flat"

    return {
        "direction": direction, "periods_used": len(window), "values": window,
        "slope": round(slope, 6), "latest_vs_median": round(latest_vs_median, 6),
        "detail": "近 %d 期年增率：%s（趨勢：%s）" % (
            len(window), "→".join("%.0f%%" % (v * 100) for v in window),
            {"rising": "上升", "falling": "下滑", "flat": "持平"}[direction]),
    }


# -------------------------------------------------------------- 背離

def detect_divergence(code, revenue_values, price_position_result):
    """基本面與股價位置的背離（FR-005／FR-006）。

    price_position_result：階段A `price_position.compute()` 的結果。
    任一邊資料不足即回 insufficient——**不得單憑一邊下結論**。
    """
    trend = revenue_trend(revenue_values)
    result = {"code": code, "status": "insufficient",
              "revenue_trend": trend, "price_percentile": None, "basis": ""}

    pp = price_position_result or {}
    percentile = pp.get("percentile")
    pp_status = pp.get("status")
    result["price_percentile"] = percentile

    if trend["direction"] == "insufficient":
        result["basis"] = "營收年增率%s，無法判斷背離" % trend["detail"]
        return result
    if percentile is None or pp_status in ("insufficient", "no_data", None):
        result["basis"] = ("股價位置資料不足（%s），無法判斷背離"
                           % (pp.get("basis") or pp_status or "無資料"))
        return result

    both = "營收%s、股價位於歷史第 %.1f 百分位" % (
        trend["detail"], percentile)

    if trend["direction"] == "rising" and percentile < DIVERGENCE_LOW_PERCENTILE:
        result["status"] = "fundamentals_ahead"
        result["basis"] = "基本面轉強但股價未跟上——%s" % both
    elif trend["direction"] == "falling" and percentile > DIVERGENCE_HIGH_PERCENTILE:
        result["status"] = "price_ahead"
        result["basis"] = "股價位於高檔但基本面未跟上——%s" % both
    else:
        result["status"] = "aligned"
        result["basis"] = "基本面與股價位置未見明顯背離——%s" % both
    return result


# ------------------------------------------------------------ 觸發建議

# 哪些 status 算「實際觸發」——只有這些才填 suggested_action（research.md R-006）
TRIGGERED_STATUSES = frozenset((
    "triggered_stop_loss", "triggered_take_profit",
    "fundamentals_ahead", "price_ahead",
))


def is_triggered(signal):
    return (signal or {}).get("status") in TRIGGERED_STATUSES


def build_suggestion(signal):
    """訊號觸發時的調整建議（FR-008／FR-009）。

    範圍鎖定在「這檔持股接下來怎麼辦」，**不做主動選股或市場掃描**
    （Q-006 已排除）。未觸發回 None——不填 suggested_action 才不會把
    首頁「今日重點」灌爆。
    """
    if not is_triggered(signal):
        return None

    status = signal["status"]
    if status == "triggered_stop_loss":
        return ("已觸發停損門檻。可考慮：(1) 依原訂紀律執行減碼/出清 "
                "(2) 若當初的投資假說仍成立，重新討論門檻是否設得太緊 "
                "(3) 換股——但需另行評估替代標的，本判斷不含選股建議。")
    if status == "triggered_take_profit":
        return ("已觸發停利門檻。可考慮：(1) 分批減碼鎖定獲利 "
                "(2) 全數出清 (3) 續抱並上調停利門檻——續抱需要有新的理由，"
                "而不只是「還會漲」。")
    if status == "fundamentals_ahead":
        return ("基本面轉強但股價未跟上。可考慮：(1) 加碼（需先確認加碼"
                "計畫額度與集中度上限）(2) 維持部位並觀察下期營收是否延續 "
                "(3) 若股價落後另有原因（產業/籌碼），先釐清再決定。")
    if status == "price_ahead":
        return ("股價位於高檔但基本面未跟上。可考慮：(1) 部分減碼降低"
                "風險敞口 (2) 設定或收緊停利門檻 (3) 續抱但明確寫下續抱"
                "理由，避免只是捨不得賣。")
    return None


def suggestion_or_note(signal):
    """回傳 (suggested_action, note)。

    資料不足時 **訊號本身仍要照常回傳**，只是建議欄位標示資料不足
    ——不得因為建議產不出來就把訊號吞掉（FR-009）。
    """
    if not is_triggered(signal):
        return (None, None)
    suggestion = build_suggestion(signal)
    if suggestion:
        return (suggestion, None)
    return (None, "訊號已觸發，但資料不足以產生調整建議，需人工判斷")
