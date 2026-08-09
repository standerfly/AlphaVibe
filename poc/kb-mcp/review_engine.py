"""模組D 策略檢視引擎——通用檢視層（FR-051）。

不管哪個策略篩進來的標的，每檔都要過 5 項檢查；本檔案先實作其中 2 項可
自動計算的（成長趨緩／下檔風險），其餘 3 項（財報兌現度／利多出盡／預期
獲利能否持續上修）留 `manual_notes` 給 PO 手動填寫——這 3 項未來即使做了
自動化，`manual_notes` 這個人工覆寫管道仍要保留（PO 明確要求，見
docs/spec-intake/alphavibe/requirements-rescoping.md 通用層原則：「所有
檢查結果都是提醒，不自動裁決，決策權在 PO」）。因此本檔案刻意不把自動化
結果與手動欄位取同名，未來要新增財報兌現度／利多出盡的自動計算時，另立
新的頂層欄位即可，不需動 `manual_notes` 的結構。

FR-052 策略專屬層（2026-07-29 新增）：每套策略除了 entry 門檻（篩選進場
候選）之外，另外定義「這套策略的假說什麼時候算失效」（見 frameworks.py
各框架的 "invalidation" 欄位）。跟 entry 門檻「全部條件都要符合」的方向
相反，invalidation 是任一子條件成立就算失效。判斷用的原始數值
（peg／drawdown_pct／revenue_yoy）直接重用 screener.screen_stocks() 算好
的結果，不重新寫一套查詢邏輯。

FR-053 老芋頭動向比對／FR-054 部位控制建議（2026-07-29 新增）：這兩個
函式需要資料庫存取（老芋頭交易表、庫存、交易流水、股價/主題快取），
呼叫端傳入既有的 KBStore 實例（`store=self.store`），函式本身不開自己
的資料庫連線——跟 FR-051/052 只需要 data_dir/token（查 FinMind／重用
screener 結果）的介面不同，這是刻意的差異，不要誤改成一致。FR-053 刻意
不做任何基本面判斷，只陳述「老芋頭做了什麼、PO現在持有狀態」，解讀
交給 PO 或未來模組F呈現時的脈絡。FR-054 的市值／持股比例／主題集中度
計算邏輯，刻意與 report.py「我的庫存與分析」既有頁面完全一致（市值＝
股數×股價快取，查不到股價的持股不計入市值也不計入分母，主題集中度
只算有標記主題且有市值的持股），確保兩處算出來的數字不會兜不起來。

FR-055 立場自動回寫機制（2026-07-29 新增）：把上面 FR-051~054 產出的
「發現」寫回 Layer 2 個股立場表。範圍已由 PO 簡化——只偵測「系統記錄
之間互相不一致」，不做「系統發現跟 PO 既有立場文字語意衝突」的自動
偵測（語意判斷留給 PO）。細節見 `auto_record_findings` docstring。

FR-057 每日排程整合（2026-07-29 新增）：`get_associated_strategies`／
`run_module_d_review`／`run_module_d_batch` 把上面 FR-051~055 的 5 個函式
串成一個每日會實際跑的流程，見各函式 docstring。⚠️ `get_associated_
strategies` 的 SQL 細節封裝在 `kb_store.KBStore.get_associated_frameworks`
（review_engine.py 跟 FR-053/054 既有慣例一致，不直接碰 `store.conn`，
所有 SQL 留在 kb_store.py），這裡只是薄包裝。

2026-08-01（來源選用邏輯稽核修正）：`general_review()` 的歷史PER查詢
（`_downside_risk` 用）改呼叫 `fundamentals_client.get_per_history`（TWSE
官方BWIBBU逐月合併優先，FinMind降級為備援），不再直接寫死呼叫
`finmind_client.get_per_history`。⚠️ 月營收年增率查詢（`_growth_deceleration`
用）刻意「不」跟著改——那個檢查需要的是多月歷史序列判斷連續趨勢，官方
批次端點只有最新一期，沒有可用的官方多月序列來源（PO已確認範圍：只有
「最新一期單筆」才需要官方優先，多月趨勢維持現狀呼叫FinMind），所以
`revenue_result` 那一行維持不動。

僅標準庫。外部查詢失敗不丟例外，回傳裡標記失敗原因，不中斷整個檢查流程
（比照 finmind_client 既有慣例）。
"""
import datetime

import finmind_client
import frameworks
import fundamentals_client
import screener

# FR-054 遞減式加碼比例表：key＝第幾次加碼，value＝這次加碼相對於「這檔
# 股票加碼計畫總額度」的比例——不是投資組合佔比，兩者量綱不同（原始
# 哲學文件沒講清楚「加碼計畫總額度」怎麼訂，這裡如實回傳查表結果，不
# 擅自發明換算公式，避免誤導）。只定義到第5次，超過時查不到值。
ADD_SEQUENCE_SCHEDULE = {1: 0.40, 2: 0.25, 3: 0.15, 4: 0.10, 5: 0.10}

# FR-054 信心分級初始部位：直接是投資組合佔比，無歧義（跟上面遞減式加碼
# 比例的量綱不同，不要混用）。
CONFIDENCE_INITIAL_POSITION = {"普通": 0.05, "很好": 0.08, "非常高": 0.10}

# FR-054 集中度警示門檻（沿用 report.py 既有頁面文字：單股參考上限15%、
# 單一投資主題參考上限50%）。
SINGLE_STOCK_CONCENTRATION_WARN_PCT = 15.0
THEME_CONCENTRATION_WARN_PCT = 50.0

# 成長趨緩：至少要有 3 個非 null 的月營收年增率數據點才判斷趨勢。
MIN_YOY_POINTS = 3

# 下檔風險：至少要有這麼多筆歷史 PER 才做評估（新股門檻，資料點太少時
# 「歷史分布」沒有統計意義）。
MIN_PER_HISTORY_POINTS = 6

# 下檔風險：資料點達到這個數量才用百分位數計算 90 分位門檻；未達門檻時
# 退化用「歷史最大值的九成」當簡化門檻（PO 已確認可用簡化規則，見派工
# 說明）。TaiwanStockPER 是逐交易日資料，30 筆約等於 1 個半月的交易日，
# 抓 2 年（約 400~500 個交易日）大多數已上市一段時間的股票都能超過。
PERCENTILE_MIN_POINTS = 30


def _growth_deceleration(revenue_result):
    """成長趨緩檢查：近 3 個非 null 月營收年增率是否連續下滑，且原始值仍是
    正成長（轉負是另一個問題，不在這裡處理）。"""
    if "revenue_yoy" not in revenue_result:
        errs = revenue_result.get("errors") or ["月營收年增率資料無法取得"]
        return {"flagged": False,
                "detail": "資料不足，無法判斷趨勢（%s）" % "；".join(errs)}

    # get_revenue_yoy 回傳依時間升冪排列（比照 monthly_revenue 用
    # data[-6:] 取「最近」的既有慣例），非 null 的最後 N 筆即最近 N 個月。
    non_null = [row for row in revenue_result["revenue_yoy"]
                if row.get("yoy_growth") is not None]
    if len(non_null) < MIN_YOY_POINTS:
        return {"flagged": False, "detail": "資料不足，無法判斷趨勢"}

    recent = non_null[-MIN_YOY_POINTS:]
    values = [row["yoy_growth"] for row in recent]

    all_positive = all(v > 0 for v in values)
    strictly_declining = all(values[i] > values[i + 1] for i in range(len(values) - 1))

    if all_positive and strictly_declining:
        detail = "年增率連續%d個月下滑：%s" % (
            MIN_YOY_POINTS, "→".join("%.0f%%" % (v * 100) for v in values))
        return {"flagged": True, "detail": detail}

    return {"flagged": False, "detail": "近期營收年增率未見連續下滑"}


def _downside_risk(per_result):
    """下檔風險檢查（PE壓縮模型）：目前 PER 是否高於近 2 年歷史分布的
    偏高區間，若是則附上「PE 回歸歷史中位數」的粗略跌幅估計。

    簡化規則（非嚴謹統計模型，供 PO 參考用的提醒，不是自動裁決）：
    - 資料點 >= PERCENTILE_MIN_POINTS：門檻＝歷史 90 百分位數
    - 資料點不足：門檻＝歷史最大值 × 0.9（近似「接近甚至超越近 2 年
      新高」的偏高訊號，資料越少門檻越粗略，故意保守一點才用最大值）

    2026-07-31 查證修正：FinMind TaiwanStockPER 在 EPS 為負／無意義時，
    PER 欄位回傳 `0.0`（不是 None、也不是負值）——這是資料端用來表示
    「本益比不適用」的 sentinel 值，不是真實的估值倍數。過去這裡只濾掉
    None，實測某檔2025年連續虧損季的個股，730天窗口裡有 57% 的資料點是
    這個 0.0 sentinel，導致中位數／百分位門檻被大量無意義的 0 拉低到
    接近 0，算出「潛在跌幅估計」完全失真。這裡改成同時濾掉 <= 0 的值，
    只用真正有意義的正值 PER 計算統計量；若濾完後 valid 為空或不足，
    走下面既有的「資料不足」分支，不特別另外處理。
    """
    if "per_history" not in per_result:
        errs = per_result.get("errors") or ["歷史PER資料無法取得"]
        return {"flagged": False,
                "detail": "資料不足，無法評估（%s）" % "；".join(errs),
                "estimated_downside_pct": None}

    valid = [row for row in per_result["per_history"]
             if row.get("PER") is not None and row["PER"] > 0]
    if len(valid) < MIN_PER_HISTORY_POINTS:
        return {"flagged": False,
                "detail": "資料不足，無法評估（僅 %d 筆歷史PER，至少需 %d 筆）"
                          % (len(valid), MIN_PER_HISTORY_POINTS),
                "estimated_downside_pct": None}

    values = [row["PER"] for row in valid]
    # per_history 依時間升冪排列（比照 finmind_client 其餘函式慣例），
    # 最後一筆即最新一筆，當作「目前PER」。
    current_per = valid[-1]["PER"]
    median_per = _median(values)

    if len(values) >= PERCENTILE_MIN_POINTS:
        threshold = _percentile(values, 0.9)
        basis = "歷史90百分位 %.1f（近%d筆）" % (threshold, len(values))
    else:
        threshold = max(values) * 0.9
        basis = "歷史最大值9成 %.1f（僅%d筆，未達%d筆改用簡化門檻）" % (
            threshold, len(values), PERCENTILE_MIN_POINTS)

    if current_per > threshold:
        downside_pct = (current_per - median_per) / current_per * 100
        detail = ("下檔風險偏高：目前PER %.1f 高於%s；若PE回歸歷史中位數 %.1f，"
                  "潛在跌幅估計約 %.1f%%") % (current_per, basis, median_per, downside_pct)
        return {"flagged": True, "detail": detail, "estimated_downside_pct": downside_pct}

    detail = "PE在歷史合理區間，下檔風險相對可控（目前PER %.1f，%s，歷史中位數 %.1f）" % (
        current_per, basis, median_per)
    return {"flagged": False, "detail": detail, "estimated_downside_pct": None}


def _median(values):
    """中位數，不依賴 statistics 模組（避免對 Python 版本細節有隱性假設，
    純手算即可，資料量不大）。"""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _percentile(values, pct):
    """簡化版線性內插百分位數（pct 為 0~1）。資料點數已由呼叫端保證
    >= PERCENTILE_MIN_POINTS，這裡不再重複檢查。"""
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    rank = pct * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def general_review(code, data_dir=None, token=None):
    """FR-051 通用檢視層：不管哪個策略篩進來的標的，每檔都要過的檢查。

    這次只做 2 項可自動計算（成長趨緩／下檔風險）；財報兌現度／利多出盡／
    預期獲利能否持續上修這 3 項留 `manual_notes` 手動欄位，尚未自動化。
    所有檢查結果都是提醒，不自動裁決，決策權在 PO。
    """
    # 月營收多月序列：維持直接呼叫 finmind_client（見模組docstring說明，
    # 官方無對應多月歷史來源，不套用官方優先包裝）。
    revenue_result = finmind_client.get_revenue_yoy(code, data_dir=data_dir, token=token)
    # 歷史PER序列：官方優先（TWSE BWIBBU逐月合併），FinMind降級為備援
    # （2026-08-01 來源選用邏輯稽核修正，見模組docstring）。
    per_result = fundamentals_client.get_per_history(code, data_dir=data_dir, token=token)

    return {
        "code": code,
        "growth_deceleration": _growth_deceleration(revenue_result),
        "downside_risk": _downside_risk(per_result),
        "manual_notes": {
            "earnings_delivery": None,
            "good_news_priced_in": None,
            "estimate_revision": None,
        },
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _invalidation_reasons(current_values, invalidation):
    """依框架的 invalidation 子條件逐一檢查，回傳觸發的 reason 文字清單。

    任一子條件成立就加一筆 reason（不是全部條件都要成立），跟 entry 門檻
    「全部符合」的方向相反。子條件對應的數值若是 None（例如 PEG 因營收
    年增率<=0 算不出來，這是正常業務邏輯，不是查詢失敗），該子條件視為
    「無法判斷」，不觸發也不報錯——保守原則：資訊不足時不誤報失效。
    """
    reasons = []
    peg, drawdown, revenue_yoy = (current_values.get("peg"),
                                   current_values.get("drawdown_pct"),
                                   current_values.get("revenue_yoy"))

    peg_min = invalidation.get("peg_min")
    if peg_min is not None and peg is not None and peg >= peg_min:
        reasons.append("PEG已回升至%.2f（門檻%.1f）" % (peg, peg_min))

    drawdown_max = invalidation.get("drawdown_max")
    if drawdown_max is not None and drawdown is not None and drawdown <= drawdown_max:
        reasons.append("回檔已收斂至%.1f%%（門檻%.1f%%）"
                        % (drawdown * 100, drawdown_max * 100))

    revenue_yoy_max = invalidation.get("revenue_yoy_max")
    if revenue_yoy_max is not None and revenue_yoy is not None and revenue_yoy <= revenue_yoy_max:
        reasons.append("營收年增率已降至%.1f%%（門檻%.1f%%）"
                        % (revenue_yoy * 100, revenue_yoy_max * 100))

    return reasons


def strategy_specific_review(code, strategy_id, data_dir=None, token=None):
    """FR-052 策略專屬層：這檔標的目前還符不符合當初篩進來那套策略的假說。

    直接重用 screener.screen_stocks() 已經算好的 peg／drawdown_pct／
    revenue_yoy 原始數值，不重新查詢；只是用不同的（失效判斷）邏輯去
    解讀這些數值，跟 screen_stocks 內部的 meets_framework（進場判斷）
    是兩套獨立邏輯。
    """
    checked_at = datetime.datetime.now().isoformat(timespec="seconds")
    framework = frameworks.get_framework(strategy_id)
    if framework is None:
        return {
            "code": code,
            "strategy_id": strategy_id,
            "invalidated": False,
            "reasons": ["查無此策略代號：%s" % strategy_id],
            "current_values": {"peg": None, "drawdown_pct": None, "revenue_yoy": None},
            "checked_at": checked_at,
        }

    invalidation = framework.get("invalidation") or {}

    scan = screener.screen_stocks([code], data_dir=data_dir, token=token)
    row = (scan.get("results") or [None])[0]

    if row is None or row.get("error"):
        error_detail = row.get("error") if row else "查無資料"
        return {
            "code": code,
            "strategy_id": strategy_id,
            "invalidated": False,
            "reasons": ["資料不足或查詢失敗，無法判斷：%s" % error_detail],
            "current_values": {"peg": None, "drawdown_pct": None, "revenue_yoy": None},
            "checked_at": checked_at,
        }

    current_values = {"peg": row.get("peg"), "drawdown_pct": row.get("drawdown_pct"),
                       "revenue_yoy": row.get("revenue_yoy")}
    reasons = _invalidation_reasons(current_values, invalidation)

    return {
        "code": code,
        "strategy_id": strategy_id,
        "invalidated": bool(reasons),
        "reasons": reasons,
        "current_values": current_values,
        "checked_at": checked_at,
    }


def laoyutou_signal_review(code, store, lookback_days=14):
    """FR-053 老芋頭動向比對：獨立訊號來源，不限定策略——只要 PO 觀察/
    持有標的有老芋頭相關動作就觸發。

    刻意的範圍限制：這裡只陳述事實（他做了什麼、PO現在持有狀態），不
    編造或推論「這代表基本面轉弱/轉強」之類的判斷——那是 PO 自己或未來
    模組F呈現時的脈絡要處理的事，不是這個函式的責任。
    """
    checked_at = datetime.datetime.now().isoformat(timespec="seconds")
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=lookback_days)

    # limit 給大一點（100），確保 lookback_days 視窗內的交易不會因為該
    # 標的老芋頭交易史夠長而被 get_laoyutou_trades 預設 limit=20 截掉；
    # 視窗篩選仍在下面用 date 逐筆比對完成，不依賴呼叫端 limit 剛好等於
    # 視窗大小。
    all_trades = store.get_laoyutou_trades(code=code, limit=100).get("trades") or []
    recent_trades = []
    for trade in all_trades:
        try:
            trade_date = datetime.date.fromisoformat(trade["date"])
        except (TypeError, ValueError):
            # date 格式不符預期：跳過該筆，不讓單筆髒資料中斷整個檢查。
            continue
        if trade_date >= cutoff:
            recent_trades.append(trade)

    holdings = store.get_holdings().get("holdings") or []
    po_holds = any(h.get("code") == code for h in holdings)

    has_signal = bool(recent_trades)
    if has_signal:
        # store.get_laoyutou_trades 已依 date DESC、id DESC 排序，第一筆
        # 即最新一筆；recent_trades 保留該排序，finding 只取最新一筆描述，
        # 但完整清單仍全部回傳在 recent_trades，不因為只描述一筆就丟掉其餘。
        latest = recent_trades[0]
        if latest["action"] == "賣":
            finding = "老芋頭於%s賣出%s股（%s元）" % (
                latest["date"], latest["shares"], latest["price"])
            if po_holds:
                finding += "，你目前持有此檔"
        else:
            finding = "老芋頭於%s買進%s股（%s元）" % (
                latest["date"], latest["shares"], latest["price"])
        if latest.get("reason"):
            finding += "，原因：%s" % latest["reason"]
    else:
        finding = "近%d天無老芋頭相關動向" % lookback_days

    return {
        "code": code,
        "has_signal": has_signal,
        "recent_trades": recent_trades,
        "po_holds": po_holds,
        "finding": finding,
        "checked_at": checked_at,
    }


def _portfolio_position_context(code, store):
    """算目前市值佔投資組合比例與所屬主題集中度。

    刻意跟 report.py「我的庫存與分析」既有頁面的計算邏輯完全一致（不是
    重用程式碼本身，report.py 那段是內嵌在 HTML 產生邏輯裡沒有拆成獨立
    函式，但算法要一致）：市值＝股數×股價快取；查不到股價（或無股數）
    的持股不計入市值，也不計入下面持股比例的分母；主題集中度只算有
    標記主題且有市值的持股分組加總。確保模組F儀表板顯示的「目前佔比」
    跟 report.py 既有頁面顯示的持股比例算出來的數字要一致。
    """
    price_map = store.get_stock_prices()
    theme_map = store.get_stock_theme()
    holdings = store.get_holdings().get("holdings") or []

    market_values = {}
    for h in holdings:
        price_info = price_map.get(h["code"])
        if price_info and h.get("shares") is not None:
            market_values[h["code"]] = h["shares"] * price_info["price"]
    total_value = sum(market_values.values())

    theme_totals = {}
    for h in holdings:
        value = market_values.get(h["code"])
        if value is None:
            continue
        theme = theme_map.get(h["code"], {}).get("theme")
        if theme:
            theme_totals[theme] = theme_totals.get(theme, 0) + value

    current_value = market_values.get(code)
    current_position_pct = (
        current_value / total_value * 100
        if current_value is not None and total_value else None)

    theme = theme_map.get(code, {}).get("theme")
    theme_concentration_pct = None
    if theme and total_value and theme in theme_totals:
        theme_concentration_pct = theme_totals[theme] / total_value * 100

    return current_position_pct, theme, theme_concentration_pct


def position_control_suggestion(code, store, confidence_level=None):
    """FR-054 部位控制建議（核心功能）：整合信心分級初始部位／遞減式
    加碼比例／集中度上限提醒，供 PO 加碼/建倉前參考。所有結果都是提醒，
    不自動裁決，決策權在 PO（呼應 FR-051 通用層設計原則）。

    ⚠️ 語意澄清（不要在這裡另外發明公式）：`suggested_add_pct` 是查
    ADD_SEQUENCE_SCHEDULE 得到的原始比例，代表「這次加碼佔這檔股票加碼
    計畫總額度的比例」，跟 `current_position_pct`／`suggested_initial_
    position_pct`（投資組合佔比）是不同量綱，本函式不做兩者間的換算——
    原始哲學文件沒講清楚「加碼計畫總額度」怎麼訂，貿然換算會是猜的。
    """
    checked_at = datetime.datetime.now().isoformat(timespec="seconds")
    current_position_pct, theme, theme_concentration_pct = (
        _portfolio_position_context(code, store))

    ledger_entries = store.get_trade_ledger(code).get("entries") or []
    # 只數「買」且 add_sequence 非 None 的筆數（呼應 kb_store.py 的取捨：
    # 賣出動作跟加碼次序無關，save_trade_ledger_entry 強制寫入 NULL）。
    sequenced_buys = sum(
        1 for e in ledger_entries
        if e.get("action") == "買" and e.get("add_sequence") is not None)
    next_add_sequence = sequenced_buys + 1

    suggested_add_pct = ADD_SEQUENCE_SCHEDULE.get(next_add_sequence)

    # 僅「這是這檔第一次建倉」（next_add_sequence == 1）且有給信心等級時
    # 才給初始部位建議；confidence_level 不是三個已知值之一時（含 None）
    # 靜默不給值，不拋例外——呼叫端沒給或給錯字，都當作「這次不提供這項
    # 建議」處理，不中斷整個檢查流程。
    suggested_initial_position_pct = None
    if next_add_sequence == 1 and confidence_level in CONFIDENCE_INITIAL_POSITION:
        suggested_initial_position_pct = CONFIDENCE_INITIAL_POSITION[confidence_level]

    warnings = []
    if (current_position_pct is not None
            and current_position_pct >= SINGLE_STOCK_CONCENTRATION_WARN_PCT):
        warnings.append("單股佔比已達%.1f%%，達參考上限，加碼前應審慎評估"
                        % current_position_pct)
    if (theme_concentration_pct is not None
            and theme_concentration_pct >= THEME_CONCENTRATION_WARN_PCT):
        warnings.append("「%s」主題佔比已達%.1f%%，達參考上限，加碼前應審慎評估"
                        % (theme, theme_concentration_pct))
    concentration_warning = "；".join(warnings) if warnings else None

    # ---- 組成綜合文字說明 ----
    detail_parts = []
    if current_position_pct is not None:
        detail_parts.append("目前市值佔投資組合%.1f%%" % current_position_pct)
    else:
        detail_parts.append("尚無市值資料（未持有或股價未更新），無法計算目前佔投資組合比例")

    if theme:
        if theme_concentration_pct is not None:
            detail_parts.append(
                "所屬投資主題「%s」，該主題目前佔投資組合%.1f%%"
                % (theme, theme_concentration_pct))
        else:
            detail_parts.append(
                "所屬投資主題「%s」（該主題尚無市值資料，無法計算主題集中度）" % theme)
    else:
        detail_parts.append("尚未標記投資主題")

    if suggested_add_pct is not None:
        detail_parts.append(
            "這是第%d次加碼，依遞減式加碼表，建議比例為此股加碼計畫總額度的"
            "%.1f%%（相對於此股加碼計畫總額度，非投資組合佔比，實際加碼股數"
            "請自行依此比例判斷）" % (next_add_sequence, suggested_add_pct * 100))
    else:
        detail_parts.append(
            "這是第%d次加碼，已超出預設遞減加碼表範圍（僅定義到第5次），"
            "建議依實際情況自行判斷" % next_add_sequence)

    if suggested_initial_position_pct is not None:
        detail_parts.append(
            "首次建倉，依信心等級「%s」，建議初始部位佔投資組合%.1f%%"
            % (confidence_level, suggested_initial_position_pct * 100))

    if concentration_warning:
        detail_parts.append(concentration_warning)

    detail = "；".join(detail_parts) + "。"

    return {
        "code": code,
        "current_position_pct": current_position_pct,
        "theme": theme,
        "theme_concentration_pct": theme_concentration_pct,
        "next_add_sequence": next_add_sequence,
        "suggested_add_pct": suggested_add_pct,
        "suggested_initial_position_pct": suggested_initial_position_pct,
        "concentration_warning": concentration_warning,
        "detail": detail,
        "checked_at": checked_at,
    }


def _findings_conflict_prefix(findings):
    """FR-055 步驟4：組出「系統記錄間分歧」的衝突提示文字（同一批findings
    裡concern_flag不是全部一致時才會被呼叫）。

    列出這批裡每一筆trigger_label被標記「需留意」還是「無異常」，順序
    照findings原始順序，不重新排序。這段文字會原封不動插進這批裡每一筆
    要寫回的reason，讓PO一眼看出「同一批檢視彼此講法不一致」，衝不衝突
    要怎麼判斷交給PO自己讀了決定——這裡只如實列出，不做語意判斷。
    """
    segments = []
    for f in findings:
        label = "需留意" if f["concern_flag"] else "無異常"
        segments.append("[%s] 標記%s" % (f["trigger_label"], label))
    return "⚠️與同批其他檢視結果不一致：" + "，".join(segments) + "。"


def auto_record_findings(code, store, findings, date=None):
    """FR-055 立場自動回寫機制（擴充FR-013）：把模組D（FR-051~054）同一天
    對同一標的批次跑出來的發現，各自新增一筆Layer 2立場記錄。

    ⚠️ 刻意的範圍限制（PO已定案於2026-07-29派工說明，不要自行擴大）：
    規格原本要求偵測兩種衝突——(1)系統記錄之間互相不一致 (2)系統發現跟
    PO既有立場文字語意衝突。這裡只做(1)；(2)是語意判斷問題，PO確認不
    做自動偵測，系統只負責把發現如實記錄下來，衝不衝突PO自己讀了判斷。

    系統不主動改變立場本身（stance欄位）：每筆新記錄沿用該標的目前最新
    一筆立場的stance值不變，因此天然不會觸發save_stance既有的FR-013
    衝突偵測機制（該機制以「新stance跟最新一筆stance欄位是否相同」判斷
    衝突），不需要用overwrite=True。查無既有立場（沒有「決策」可以承接）
    時，系統不建立新立場，整批略過不寫入。

    findings：list of {"trigger_label": str, "concern_flag": bool,
    "detail": str}，同一天、同一標的的一批發現（呼叫端負責組出這個格式，
    例如未來FR-057排程整合會把FR-051~054的結果轉成這個格式）。多重觸發
    規則：一檔標的同時符合多套策略、各自檢視都觸發時，各自新增一筆系統
    記錄，不合併——這裡每一筆finding各自呼叫一次save_stance即對應此規則。
    """
    date = date or datetime.date.today().isoformat()
    existing = store.get_latest_stance(code)
    if existing is None:
        return {
            "code": code,
            "skipped": True,
            "skip_reason": "查無既有立場，系統不建立新立場，略過自動記錄",
            "written": [],
            "has_conflict": False,
        }

    stance = existing["stance"]
    has_conflict = len(set(bool(f["concern_flag"]) for f in findings)) > 1
    conflict_prefix = _findings_conflict_prefix(findings) if has_conflict else ""

    written = []
    for f in findings:
        trigger_label = f["trigger_label"]
        reason = "[模組D自動檢視 %s／%s]%s%s" % (
            date, trigger_label, conflict_prefix, f["detail"])
        result = store.save_stance(
            code=code, stance=stance, reason=reason, date=date,
            source_ref="模組D自動檢視／%s" % trigger_label,
        )
        written.append({
            "trigger_label": trigger_label,
            "stance_record_id": result["record"]["id"],
            "reason": reason,
        })

    return {
        "code": code,
        "skipped": False,
        "skip_reason": None,
        "has_conflict": has_conflict,
        "written": written,
    }


def get_associated_strategies(code, store):
    """FR-052 策略關聯判斷：這檔標的要跑哪些策略專屬層檢查（供
    `run_module_d_review` 決定要對哪些 strategy_id 呼叫
    `strategy_specific_review`）。

    薄包裝，實際 SQL 封裝在 `KBStore.get_associated_frameworks`（review_
    engine.py 跟 FR-053/054 既有慣例一致，只呼叫 store 的既有方法，不直接
    碰 store.conn）。從沒被 market_scan 篩中過的標的（例如 PO 手動加入
    觀察名單、或老芋頭訊號帶進來的）回傳空 list——這是正常情況，不是
    錯誤，代表這檔沒有「策略專屬層」要檢查，只跑通用層跟老芋頭層。
    """
    return store.get_associated_frameworks(code)


def _strategy_finding_detail(result):
    """把 strategy_specific_review() 的回傳整理成人類可讀的一句話，供
    run_module_d_review() 組 finding 用。invalidated=True 或查詢失敗/
    查無此策略時，reasons 非空，直接串接；invalidated=False 且查詢正常時
    reasons 是空list，改用 current_values 組一句「假說未失效」的說明，
    避免 detail 空白。"""
    if result["reasons"]:
        return "；".join(result["reasons"])
    values = result.get("current_values") or {}
    parts = []
    if values.get("peg") is not None:
        parts.append("PEG=%.2f" % values["peg"])
    if values.get("drawdown_pct") is not None:
        parts.append("回檔%.1f%%" % (values["drawdown_pct"] * 100))
    if values.get("revenue_yoy") is not None:
        parts.append("營收年增率%.1f%%" % (values["revenue_yoy"] * 100))
    if parts:
        return "假說未失效（現值：%s）" % "、".join(parts)
    return "假說未失效（現值資料不足）"


def run_module_d_review(code, store, data_dir=None, token=None):
    """FR-057 單檔檢視整合：依序串接 FR-051（通用層）／FR-052（策略層，
    透過 `get_associated_strategies` 決定要跑哪些策略）／FR-053（老芋頭
    動向），組出 FR-055 `auto_record_findings` 需要的 findings 格式，並把
    每一項檢視結果（不只是有問題的）持久化進 `module_d_results` 表供未來
    模組F儀表板讀取。

    ⚠️ 「items」與「findings」是刻意分開的兩個列表，不要合併：
    - `items`（內部用，含 trigger_type/strategy_id/trigger_label/
      concern_flag/detail）：通用層固定產生2筆（成長趨緩／下檔風險，
      無論 flagged 是 True 或 False 都各自成一筆）、策略層每個關聯策略
      各1筆（無論 invalidated 是 True 或 False）、老芋頭層僅在
      has_signal=True 時才有1筆。這份完整清單（含「沒觸發」的正常結果）
      全部寫入 `module_d_results`，讓儀表板能查「今天檢查過什麼、結果
      是什麼」，不是只存有問題的。
    - `findings`（餵給 `auto_record_findings` 寫入 stances 用）：從
      `items` 篩出 concern_flag=True 的子集合。這是刻意的設計決定，不是
      跟 items 相同的清單——若不篩選、把通用層固定的2筆（多數時候
      concern_flag=False）也天天寫進 stances，會造成 Layer 2 立場記錄
      被「無異常」的例行檢查結果洗版，違背 FR-055「發現」的精神；也唯有
      這樣才能滿足「全部正常無異常時不寫入stances」這條驗收條件（否則
      通用層固定產生2筆的設計會讓 findings 幾乎永遠非空）。

    單一子步驟失敗不中斷整個函式（比照 screener.screen_stocks()／
    benchmark.py 既有的 try/except-per-step 慣例）：失敗記錄在回傳結構的
    `errors` 欄位，該層不產生 items/findings，繼續跑下一層。
    """
    checked_at = datetime.datetime.now().isoformat(timespec="seconds")
    items = []
    errors = {}

    # ---- FR-051 通用層：固定產生2筆，無論 flagged 是否為 True ----
    general = None
    try:
        general = general_review(code, data_dir=data_dir, token=token)
        gd = general["growth_deceleration"]
        items.append({"trigger_type": "通用層", "strategy_id": None,
                      "trigger_label": "通用層／成長趨緩",
                      "concern_flag": bool(gd["flagged"]), "detail": gd["detail"]})
        dr = general["downside_risk"]
        items.append({"trigger_type": "通用層", "strategy_id": None,
                      "trigger_label": "通用層／下檔風險",
                      "concern_flag": bool(dr["flagged"]), "detail": dr["detail"]})
    except Exception as exc:
        general = None
        errors["general"] = "通用層檢視失敗：%s" % exc

    # ---- FR-052 策略層：關聯策略清單先查，查失敗不影響通用層／老芋頭層 ----
    strategies = []
    try:
        strategy_ids = get_associated_strategies(code, store)
    except Exception as exc:
        strategy_ids = []
        errors["associated_strategies"] = "策略關聯判斷失敗：%s" % exc

    for sid in strategy_ids:
        try:
            result = strategy_specific_review(code, sid, data_dir=data_dir, token=token)
            strategies.append(result)
            items.append({"trigger_type": "策略層", "strategy_id": sid,
                          "trigger_label": "策略層／%s" % sid,
                          "concern_flag": bool(result["invalidated"]),
                          "detail": _strategy_finding_detail(result)})
        except Exception as exc:  # 單一策略失敗不可讓其他策略/其他層也停擺
            errors.setdefault("strategies", {})[sid] = (
                "策略層檢視失敗（%s）：%s" % (sid, exc))

    # ---- FR-053 老芋頭動向：僅 has_signal=True 才產生1筆 ----
    laoyutou = None
    try:
        laoyutou = laoyutou_signal_review(code, store)
        if laoyutou["has_signal"]:
            items.append({"trigger_type": "老芋頭動向", "strategy_id": None,
                          "trigger_label": "老芋頭動向",
                          "concern_flag": True, "detail": laoyutou["finding"]})
    except Exception as exc:
        laoyutou = None
        errors["laoyutou"] = "老芋頭動向比對失敗：%s" % exc

    # findings：從 items 篩出 concern_flag=True 的子集合（見上方docstring
    # 說明為何不能直接用 items），轉成 auto_record_findings 需要的格式。
    findings = [{"trigger_label": it["trigger_label"],
                "concern_flag": it["concern_flag"], "detail": it["detail"]}
               for it in items if it["concern_flag"]]

    # ---- FR-054 部位控制建議：findings 非空（即有任一筆concern）才算 ----
    position_control = None
    if findings:
        try:
            position_control = position_control_suggestion(code, store)
        except Exception as exc:
            errors["position_control"] = "部位控制建議計算失敗：%s" % exc

    # ---- FR-055 立場自動回寫：findings 非空才寫入 stances ----
    auto_record = None
    if findings:
        try:
            auto_record = auto_record_findings(code, store, findings)
        except Exception as exc:
            errors["auto_record"] = "立場自動回寫失敗：%s" % exc

    conflict_flag = bool(auto_record and not auto_record.get("skipped")
                         and auto_record.get("has_conflict"))

    # ---- 寫入 module_d_results：items 全部（含「沒觸發」的正常結果）----
    saved_count = 0
    for it in items:
        suggested_action = (position_control["detail"]
                            if it["concern_flag"] and position_control else None)
        try:
            store.save_module_d_result(
                code=code, trigger_type=it["trigger_type"], finding=it["detail"],
                strategy_id=it["strategy_id"], suggested_action=suggested_action,
                conflict_flag=conflict_flag, concern_flag=it["concern_flag"],
                checked_at=checked_at)
            saved_count += 1
        except Exception as exc:
            errors.setdefault("module_d_results_save", []).append(
                "寫入module_d_results失敗（%s）：%s" % (it["trigger_label"], exc))

    return {
        "code": code,
        "checked_at": checked_at,
        "general": general,
        "strategies": strategies,
        "laoyutou": laoyutou,
        "position_control": position_control,
        "findings": findings,
        "auto_record": auto_record,
        "module_d_results_saved_count": saved_count,
        "errors": errors,
    }


def run_module_d_batch(store, data_dir=None, token=None):
    """FR-057 批次執行：觀察名單（`store.list_stances()` 全部代碼）∪ 庫存
    （`store.get_holdings()["holdings"]` 全部代碼）去重後的代碼清單，逐檔
    呼叫 `run_module_d_review`。單檔失敗不中斷整批（比照 market_scan.py／
    screener.py 既有的 per-item try/except 慣例）——`run_module_d_review`
    內部各子步驟本身已經是try/except保護、理論上不會往外丟例外，這裡的
    try/except是最後一道防線（例如store本身發生非預期錯誤）。
    """
    stance_codes = [s["code"] for s in store.list_stances()]
    holding_codes = [h["code"] for h in (store.get_holdings().get("holdings") or [])]
    codes = list(dict.fromkeys(stance_codes + holding_codes))  # 去重，保留原始出現順序

    results = []
    failed = []
    concern_codes = []
    for code in codes:
        try:
            result = run_module_d_review(code, store, data_dir=data_dir, token=token)
            results.append(result)
            if any(f["concern_flag"] for f in result["findings"]):
                concern_codes.append(code)
        except Exception as exc:  # 單檔非預期錯誤不可讓整批中斷
            failed.append({"code": code, "error": "非預期錯誤：%s" % exc})

    return {
        "total": len(codes),
        "checked_count": len(results),
        "failed_count": len(failed),
        "failed": failed,
        "concern_codes": concern_codes,
        "results": results,
    }


# ---------------------------------------------------------------------------
# 個股頁背景刷新（2026-08-01新增）：清單頁／詳情頁「不即時查詢」原則——
# 頁面只讀 stock_prices／stock_valuation_snapshots／module_d_results 快取，
# 實際查詢都在這裡的背景刷新流程裡完成，由 report_server.trigger_stock_
# refresh()（PO手動按更新／新增研究標的觸發）與 module_d_scheduler.py
# （每日18:00排程）兩條路徑共用，確保寫入同一份資料、同一套邏輯。
# ---------------------------------------------------------------------------

def refresh_price_and_valuation(code, store, data_dir=None, token=None):
    """單一代碼的股價＋估值快照刷新：

    - 股價：重用 screener._fetch_prices_with_fallback()（官方TWSE/TPEx
      優先、FinMind降級備援，market=None時依序試TWSE、TPEx——跟
      screen_stocks() 手動貼代碼、不知道市場別時的既有邏輯一致，不重寫
      一套新的股價來源選用規則）。取回的價格序列依日期升冪排列，最後
      一筆是最新收盤、倒數第二筆是前一交易日收盤，兩者一起存入
      stock_prices（prev_close有值時，清單頁/詳情頁才能算「今天漲跌幅」；
      只有一筆資料時 prev_close 存 None，不臆測）；完整序列另外「順便」
      存進 stock_price_history（2026-08-09新增，庫存買賣圖表用，見
      KBStore.save_price_history_points docstring——同一次查詢結果多存
      一份，不是多打一次API）。
    - 估值：fundamentals_client.get_valuation()／get_revenue_yoy_latest()
      （官方優先＋FinMind備援，2026-08-01已建好的模組，見該模組docstring
      的稽核修正說明），存入 stock_valuation_snapshots。

    兩步驟各自 try/except，一個失敗不影響另一個（比照 run_module_d_review
    的既有 try/except-per-step 慣例）。回傳 dict 供呼叫端記錄
    checked_at／saved結果／errors；不丟例外中斷呼叫端。
    """
    checked_at = datetime.datetime.now().isoformat(timespec="seconds")
    errors = {}

    price_saved = None
    try:
        prices, price_data_source = screener._fetch_prices_with_fallback(
            code, None, data_dir, token, None)
        if prices:
            latest = prices[-1]
            prev = prices[-2] if len(prices) >= 2 else None
            price_saved = store.upsert_stock_price(
                code, latest.get("close"), latest.get("date"),
                prev_close=(prev.get("close") if prev else None))
            store.save_price_history_points(code, prices)
        else:
            errors["price"] = "查無股價資料（來源：%s）" % price_data_source
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        errors["price"] = "股價刷新失敗：%s" % exc

    valuation_saved = None
    try:
        valuation = fundamentals_client.get_valuation(code, data_dir=data_dir, token=token)
        revenue = fundamentals_client.get_revenue_yoy_latest(code, data_dir=data_dir, token=token)
        valuation_saved = store.upsert_stock_valuation(
            code, per=valuation.get("per"), pbr=valuation.get("pbr"),
            dividend_yield=valuation.get("dividend_yield"),
            revenue_yoy=revenue.get("revenue_yoy"), revenue_period=revenue.get("revenue_period"),
            valuation_data_source=valuation.get("data_source"),
            revenue_data_source=revenue.get("data_source"),
            valuation_error=valuation.get("error"), revenue_error=revenue.get("error"),
            checked_at=checked_at)
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        errors["valuation"] = "估值刷新失敗：%s" % exc

    return {"code": code, "checked_at": checked_at, "price_saved": price_saved,
            "valuation_saved": valuation_saved, "errors": errors}


def refresh_stock_snapshot(code, store, data_dir=None, token=None):
    """單一代碼的完整背景刷新：股價／估值快照（refresh_price_and_valuation）
    ＋ Module D 檢視（run_module_d_review）。供
    report_server.trigger_stock_refresh() 背景執行緒使用——「新增研究
    標的」與「PO手動按更新」兩種觸發路徑都呼叫這個函式，確保寫入完全
    相同的資料／邏輯（見派工說明「背景刷新機制」）。

    每日18:00排程（module_d_scheduler.py）刻意「不」呼叫這個函式：排程
    走 run_module_d_batch()（已個別覆蓋 try/except／failed清單），批次跑完
    後另外對同一批代碼呼叫 refresh_price_and_valuation()，避免 run_module_d_
    review() 被重複呼叫兩次（run_module_d_batch 內部已經呼叫過一次）。
    """
    snapshot = refresh_price_and_valuation(code, store, data_dir=data_dir, token=token)
    review = run_module_d_review(code, store, data_dir=data_dir, token=token)
    return {"code": code, "checked_at": snapshot["checked_at"],
            "price_saved": snapshot["price_saved"],
            "valuation_saved": snapshot["valuation_saved"],
            "snapshot_errors": snapshot["errors"], "review": review}
