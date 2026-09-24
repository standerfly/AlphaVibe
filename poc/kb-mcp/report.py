"""產出三層知識庫的靜態檢視頁（Phase 1b 試用期的極簡唯讀報表）。

定位：拋棄式檢視工具，同時是 OQ-3（儀表板技術形態）的「靜態產出」實驗
——1b 試用期覺得它夠用，1c 就便宜做；覺得想互動，就是要做互動頁的證據。

刻意不做：即時股價、距離目標買價（需線上數據與互動，屬 1c 儀表板 FR-024）。

用法：python3 poc/kb-mcp/report.py [--data-dir DIR] [--out 路徑]
預設讀 poc/data/、寫到 poc/data/report.html。純標準庫、Python 3.9 相容。
"""
import argparse
import datetime
import html
import json
import os
import re
import struct
import sys
import urllib.parse
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kb_store import KBStore  # noqa: E402
import frameworks  # noqa: E402
import pnl  # noqa: E402
import screener  # noqa: E402

# 台股慣例：紅漲綠跌 → 偏多紅、偏空綠






def esc(value):
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


























STOCKLIST_PAGE_SIZE = 10







def _latest_module_d_batch(store, code):
    """回傳「最新一批」Module D檢視結果：同一次背景刷新（review_engine.
    run_module_d_review）寫入的所有列共用同一個checked_at時間戳，可能是
    通用層2筆＋策略層N筆＋老芋頭層0或1筆——不能把歷史所有批次的列混在
    一起顯示（見派工說明）。get_module_d_results()本身已依checked_at
    DESC排序，取第一筆的checked_at當「最新批次」的判準，篩出同批次
    全部列即可，不需要另外排序。"""
    rows = store.get_module_d_results(code=code, limit=50)["results"]
    if not rows:
        return []
    latest_checked_at = rows[0]["checked_at"]
    return [r for r in rows if r["checked_at"] == latest_checked_at]


def _row_status_text(latest_batch):
    """清單頁每列的一行狀態摘要：優先顯示需留意（concern_flag=True）的
    發現內容，沒有需留意項目則顯示第一筆檢視結果（例如「下檔風險可控」
    這類正常訊息），完全沒有資料則提示尚在等待背景刷新。"""
    if not latest_batch:
        return "尚無檢視資料，稍後將自動更新"
    concerns = [r for r in latest_batch if r.get("concern_flag")]
    pick = concerns[0] if concerns else latest_batch[0]
    return pick["finding"]


def _tracked_stock_rows(store):
    """清單頁資料來源：庫存（get_holdings，最新快照）∪ 立場（list_stances，
    每代碼最新一筆，涵蓋研究中/觀察/偏多/偏空各種立場文字）去重後的代碼
    清單——跟 review_engine.run_module_d_batch() 的批次範圍公式完全一致
    （同一套「PO在追蹤什麼」定義，不另外發明一套）。回傳每筆含
    code/name/is_holding/price/delta_pct/has_concern/status_text/
    stance/reason 的 dict 清單，依代碼首次出現順序（庫存優先於純立場）。

    stance/reason（2026-08-24 補回）：直接取自本函式已經在算的
    stance_by_code（來源是 store.list_stances()，跟 store.get_latest_
    stance(code) 同一張 stances 表、同一份「每代碼最新一筆」語意，只是
    _render_holdings_section()／_render_watchlist_only_section() 既有
    寫法是一次查表分攤到每一列，不逐列各查一次 get_latest_stance()——
    這裡沿用同一份既有寫法，不是另外發明查詢方式）。沒有任何立場紀錄的
    代碼（例如剛加入研究、還沒建立過立場）兩欄皆為 None，呼叫端自行決定
    空狀態顯示方式。

    industry_category/theme（2026-08-24 補回，投資分頁主題集中度待辦）：
    來源同 _render_holdings_section() 逐列顯示的兩欄
    （store.get_stock_industries()／store.get_stock_theme()，代碼查不到
    時各自回傳的 dict 沒有這個 key，用 .get(code, {}).get(...) 拿到
    None），沿用同一份既有查詢方式，不逐列各查一次。"""
    stances = store.list_stances()
    stance_by_code = {s["code"]: s for s in stances}
    holdings = store.get_holdings()["holdings"]
    holding_codes = set(h["code"] for h in holdings)
    holding_by_code = {h["code"]: h for h in holdings}
    all_codes = list(dict.fromkeys(
        [h["code"] for h in holdings] + [s["code"] for s in stances]))
    price_map = store.get_stock_prices()
    industry_map = store.get_stock_industries()
    theme_map = store.get_stock_theme()

    rows = []
    for code in all_codes:
        is_holding = code in holding_codes
        name = None
        if code in holding_by_code:
            name = holding_by_code[code].get("name")
        if not name and code in stance_by_code:
            name = stance_by_code[code].get("name")
        price_info = price_map.get(code)
        price = price_info["price"] if price_info else None
        prev_close = price_info.get("prev_close") if price_info else None
        delta_pct = None
        if price is not None and prev_close:
            delta_pct = (price - prev_close) / prev_close * 100
        latest_batch = _latest_module_d_batch(store, code)
        # 迷你走勢（2026-08-09新增）：讀快取股價歷史，只取最近60天——
        # 清單頁每列只要「近期形狀」，不需要跟詳情頁一樣的完整範圍，
        # 且點數少SVG較輕，一次渲染10列不會太重。純本地讀，不即時查價。
        spark_html = _render_sparkline_svg(
            _sparkline_points(store.get_cached_price_history(code, limit_days=60), price_info))
        stance_row = stance_by_code.get(code)
        rows.append({
            "code": code, "name": name, "is_holding": is_holding,
            "price": price, "delta_pct": delta_pct,
            "has_concern": any(r.get("concern_flag") for r in latest_batch),
            "status_text": _row_status_text(latest_batch),
            "spark_html": spark_html,
            "stance": stance_row.get("stance") if stance_row else None,
            "reason": stance_row.get("reason") if stance_row else None,
            "industry_category": industry_map.get(code, {}).get("industry_category"),
            "theme": theme_map.get(code, {}).get("theme"),
        })
    return rows








def _verdict_banner_html(store, code, latest_batch):
    """Verdict banner（2026-08-19 依已核准 mockup 新增）：把「今天到底
    該不該動」的結論放在頁面最上方，先於價格出現。

    這塊的動機是 PO 明確指出的心魔：詳情頁一打開先看到價格與均價，會
    觸發「跟成本比」的定錨慣性；把結論置頂，是要讓眼睛先接收「今天的
    證據支不支持動作」再看價格。

    結論由實際資料算出來，不是寫死的文案。優先序刻意如此（嚴重的先講）：
    1. Gate 有 concern → 擋住，紅
    2. 集中度已達上限 → 擋住，紅（規則等級的擋點，跟 Gate 獨立）
    3. Gate 全過但集中度算不出來 → 黃：不是「沒問題」是「看不到」
    4. 都過 → 綠
    5. 尚無檢視資料 → 中性灰，不假裝有結論
    """
    import review_engine  # 延後匯入，理由同 _concentration_card_html()

    gate, reference, _status = _split_module_d_batch(latest_batch or [])
    gate_concerns = [r for r in gate if r.get("concern_flag")]
    ref_out = [r for r in reference if r.get("concern_flag")]

    pc = review_engine.position_control_suggestion(code, store)
    conc_warning = pc.get("concentration_warning")
    conc_unknown = pc.get("current_position_pct") is None

    if not latest_batch:
        tone, title = "neutral", "尚無檢視結果"
        detail = "背景刷新完成後，這裡會顯示今天的加碼審查結論。"
    elif gate_concerns:
        tone, title = "alert", "Gate 有 %d 項需留意" % len(gate_concerns)
        detail = "；".join(r["finding"] for r in gate_concerns)
    elif conc_warning:
        tone, title = "alert", "Gate 全過，但集中度已達上限"
        detail = conc_warning + "——這是規則等級的擋點，需你自行確認後才繼續加碼。"
    elif conc_unknown:
        tone, title = "warn", "Gate 全過，但集中度算不出來"
        detail = ("持股快照沒有這檔的市值紀錄，集中度是「看不到」不是「沒問題」，"
                  "補齊後才能真正定案。")
    else:
        tone, title = "ok", "Gate 全過，集中度未超標"
        detail = "目前沒有擋住加碼的項目；Score 與部分 Gate 項仍需人工查證（見下方）。"

    if ref_out and tone != "alert":
        detail += ("　另：原篩選框架已退出候選，但那是候選機制、不是持有門檻，"
                   "不影響上面的結論。")

    return ("<div class=\"verdict verdict--%s\"><div class=\"verdict__title\">%s</div>"
            "<div class=\"verdict__detail\">%s</div></div>"
            % (tone, esc(title), esc(detail)))




def _split_module_d_batch(latest_batch):
    """把最新一批檢視結果拆成三組，對應已核准 mockup 的 Checks 分區。

    ⚠️ 這個拆法是 2026-08-16~19 討論的核心修正，不要合併回去：**策略層
    不屬於 Gate**。策略層跑的是 `check_strategy_review`＝「這檔還符不符合
    當初把它篩出來的框架門檻（PEG<1、回檔≥40% 之類）」，那是**候選篩選
    機制**，不是持有／加碼的必要條件——框架文件自己就寫「換股不代表原
    標的變差」。先前頁面把它跟通用層並列成同一串 finding，等於把「退出
    便宜貨候選名單」呈現得像「投資假說被推翻」，這正是 PO 指出的混淆。

    回傳 (gate_rows, reference_rows, status_rows)：
    - gate：通用層（成長趨緩／下檔風險）——真正的必過檢查
    - reference：策略層——僅供參考，不影響 Gate 判斷
    - status：老芋頭動向——獨立訊號，純陳述事實
    """
    gate, reference, status = [], [], []
    for r in latest_batch:
        t = r.get("trigger_type")
        if t == "策略層":
            reference.append(r)
        elif t == "老芋頭動向":
            status.append(r)
        else:
            gate.append(r)
    return gate, reference, status










def _invested_amount(store, code):
    """加碼進度卡的「已投入」金額＝**目前部位的成本**，不是歷史買進總額
    ——買了又賣掉的錢已經收回來了，不該還算在「這檔已經投入多少預算」裡
    （否則出清過的標的會顯示投入滿額，明明手上一股都沒有）。

    取值優先序（跟 `_avg_cost_for_chart()` 同一套「快照優先、流水表補位」
    的既有慣例）：
    1. 庫存快照 shares × avg_cost——最權威，但實測 avg_cost 常缺值
    2. 快照缺值或整檔不在快照裡 → 用交易流水表的**淨股數**（買-賣）×
       買進加權平均價估算
    3. 都算不出來（純研究標的、或淨股數 ≤0）→ 回傳 None，呼叫端顯示
       「尚未投入」，不要顯示 0 讓人以為是「投入了0元」

    回傳 (金額, 股數, 來源說明)；金額為 None 時後兩者仍可能有值。
    """
    holding = next((h for h in store.get_holdings()["holdings"]
                    if h["code"] == code), None)
    entries = store.get_trade_ledger(code).get("entries") or []

    if holding and holding.get("shares") and holding.get("avg_cost") is not None:
        shares = holding["shares"]
        return shares * holding["avg_cost"], shares, "庫存快照"

    buy_shares = sum(e["shares"] for e in entries if e["action"] == "買")
    sell_shares = sum(e["shares"] for e in entries if e["action"] == "賣")
    net_shares = buy_shares - sell_shares
    if holding and holding.get("shares"):
        # 快照有股數但沒均價：股數以快照為準（權威），單價用流水表估
        net_shares = holding["shares"]
    if net_shares <= 0 or not buy_shares:
        return None, (net_shares if net_shares > 0 else 0), None
    avg = sum(e["shares"] * e["price"] for e in entries if e["action"] == "買") / buy_shares
    return net_shares * avg, net_shares, "交易流水表估算"




def _portfolio_context(store):
    """跟 _render_holdings_section() 同一份市值計算邏輯（規格明講兩處
    不能算出不同答案，見該函式docstring）：市值＝股數×快取股價，查不到
    股價的持股不計入市值也不計入下面比例的分母。這裡只回傳detail頁
    需要的部分：最新庫存快照列、每檔市值、投資組合總市值。"""
    holdings = store.get_holdings()["holdings"]
    price_map = store.get_stock_prices()
    market_values = {}
    for h in holdings:
        info = price_map.get(h["code"])
        if info and h.get("shares") is not None:
            market_values[h["code"]] = h["shares"] * info["price"]
    total_value = sum(market_values.values())
    return holdings, market_values, total_value


def _theme_concentration_data(store):
    """主題集中度加總表的結構化版本（2026-08-24 新增，投資分頁待辦第5項）
    ——供 GET /api/holdings 使用。跟 _render_holdings_section()「主題
    集中度」小節、review_engine._portfolio_position_context() 的
    theme_totals 計算是同一份演算法（市值＝股數×快取股價；只把有標記
    主題且已有市值的持股依主題分組加總，分母是全部「有市值資料」持股的
    市值總和）——這裡不重新發明公式，只是把輸出從 HTML 字串／單一代碼
    的兩個標量，換成前端可以直接渲染的完整清單，直接呼叫 _portfolio_
    context() 取得跟其餘頁面完全一致的市值計算結果，不自己重算一遍。

    刻意對**全部持股**（store.get_holdings() 的最新快照）計算，不受
    /api/holdings 的 filter／q／page 影響——主題集中度是投資組合層級的
    聚合指標，用分頁後的子集合算會讓數字隨翻頁跳動、失去意義。

    回傳 {"total_value": 全部已標價持股市值總和,
    "themes": [{"theme", "market_value", "portfolio_pct"}, ...]}，
    themes 依市值由大到小排序（比照 _render_holdings_section() 既有
    排序）。沒有任何已標記主題且已標價的持股時，themes 回傳空清單
    （比照 _render_holdings_section() 的 `if theme_totals and
    total_value` 既有判斷，避免除以零）。"""
    holdings, market_values, total_value = _portfolio_context(store)
    theme_map = store.get_stock_theme()

    theme_totals = {}
    for h in holdings:
        value = market_values.get(h["code"])
        if value is None:
            continue
        theme = theme_map.get(h["code"], {}).get("theme")
        if theme:
            theme_totals[theme] = theme_totals.get(theme, 0) + value

    themes = []
    if theme_totals and total_value:
        for theme, value in sorted(theme_totals.items(), key=lambda kv: -kv[1]):
            themes.append({
                "theme": theme,
                "market_value": value,
                "portfolio_pct": value / total_value * 100,
            })
    return {"total_value": total_value, "themes": themes}








def _sparkline_points(history, price_info):
    """個股清單頁每列迷你走勢用：優先用快取股價歷史（store.
    get_cached_price_history()，多日真實序列，2026-08-09新增），該代碼
    還沒被背景刷新過（history為空）時退回目前快取的單一股價當唯一的點
    （會因為只有1個點畫不出線，由 _render_sparkline_svg 顯示「資料不足」，
    不強行湊數）。"""
    if history:
        return [(p["date"], p["close"]) for p in history if p.get("close") is not None]
    if price_info and price_info.get("price") is not None:
        return [(price_info.get("price_date") or "", price_info["price"])]
    return []


def _render_sparkline_svg(points, width=64, height=28):
    """畫個股清單頁每列的迷你走勢。少於2個點畫不出線，回傳文字提示。
    台股慣例紅漲綠跌：終點價 >= 起點價描紅，反之描綠，跟 STANCE_COLORS／
    _delta_badge 同一套色彩語意。"""
    if len(points) < 2:
        return "<span class=\"meta\" style=\"font-size:.7rem;\">走勢資料不足</span>"
    prices = [p for _, p in points]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or (abs(hi) * 0.02 or 1.0)
    n = len(points)
    pad = 2.0
    coords = []
    for i, (_, price) in enumerate(points):
        x = pad + (width - 2 * pad) * i / (n - 1)
        y = pad + (height - 2 * pad) * (1 - (price - lo) / span)
        coords.append("%.1f,%.1f" % (x, y))
    color = "var(--red)" if points[-1][1] >= points[0][1] else "var(--green)"
    return ("<svg class=\"spark\" viewBox=\"0 0 %d %d\" width=\"%d\" height=\"%d\" "
           "role=\"img\" aria-label=\"走勢\">"
           "<polyline points=\"%s\" fill=\"none\" stroke=\"%s\" stroke-width=\"1.6\" "
           "stroke-linejoin=\"round\" stroke-linecap=\"round\"/></svg>"
           % (width, height, width, height, " ".join(coords), color))


def _avg_cost_for_chart(holding_row, entries):
    """走勢圖均價虛線用（2026-08-09新增）：優先用庫存快照本身記錄的
    avg_cost（較「正確」但實測常缺值，見CLAUDE.md教訓：22筆中僅1筆
    有值）；查不到時退回用交易流水裡全部買進的加權平均價估算（不扣
    賣出，遇到有出過清的標的這個估算值會失真，是刻意的簡化，跟原始
    mockup設計取捨一致，不做FIFO成本計算）。兩者都沒有就回傳None，
    呼叫端看到None就不畫線，不臆測。"""
    if holding_row and holding_row.get("avg_cost") is not None:
        return holding_row["avg_cost"]
    buy_shares = sum(e["shares"] for e in entries if e["action"] == "買")
    if not buy_shares:
        return None
    buy_value = sum(e["shares"] * e["price"] for e in entries if e["action"] == "買")
    return buy_value / buy_shares












def _carry_over_avg_cost(rows, previous_holdings):
    """holdings_parser.parse_holdings_report() 的解析結果不含 avg_cost
    （帳單本來就沒有成本資料）；若上次快照同一代碼有非NULL的avg_cost，
    沿用帶過去，不讓已知的成本資料在「貼帳單→存新快照」的流程中消失。
    回傳新的清單（不修改傳入的rows），每筆含code/name/shares/avg_cost/
    is_emerging，供預覽頁顯示與確認表單的隱藏欄位JSON共用。"""
    prev_map = {h["code"]: h for h in (previous_holdings.get("holdings") or [])}
    enriched = []
    for r in rows:
        prev = prev_map.get(r["code"])
        avg_cost = prev.get("avg_cost") if prev else None
        enriched.append({
            "code": r["code"],
            "name": r.get("name"),
            "shares": r.get("shares"),
            "avg_cost": avg_cost,
            "is_emerging": bool(r.get("is_emerging")),
        })
    return enriched


def _diff_holdings(enriched_rows, previous_holdings):
    """比對這次解析結果與上次持股快照，分成新增／消失／股數變化三類，
    供 render_holdings_preview() 顯示。「消失」只代表這次帳單沒有印到
    這個代碼，不代表使用者已經出清——不在這裡替使用者下判斷。"""
    prev_map = {h["code"]: h for h in (previous_holdings.get("holdings") or [])}
    curr_map = {r["code"]: r for r in enriched_rows}
    added = [r for r in enriched_rows if r["code"] not in prev_map]
    removed = [h for h in (previous_holdings.get("holdings") or [])
               if h["code"] not in curr_map]
    changed = []
    for r in enriched_rows:
        prev = prev_map.get(r["code"])
        if prev is not None and prev.get("shares") != r.get("shares"):
            changed.append({
                "code": r["code"], "name": r.get("name"),
                "prev_shares": prev.get("shares"), "new_shares": r.get("shares"),
            })
    return {"added": added, "removed": removed, "changed": changed}




















# 沿用 /screen 頁面「理由」段落同一套因果說明文字（見 render_screen_form），
# 加入追蹤時的 reason 要能回答「為什麼這檔當初被篩出來」，不是只有數字。


















