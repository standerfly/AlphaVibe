"""交易紀錄自動同步持股快照（2026-09-02，STND Telegram 管家擴充二）。

`trade_ledger`（PO 自己的交易流水，FR-056）與 `holdings`（持股快照，
FR-029）原本是兩張互不相干的表：匯入交易紀錄不會反映到持股清單——新
買進的股票不會出現在持股清單，賣光的股票不會被標記為已出清。這支模組
是掛載在 `trade_ledger_parser.py::resolve_and_save_trade_ledger()` 尾端
的自動同步邏輯：每次交易匯入後，讀目前持股當 baseline，依這批交易逐筆
套用，重建一份「今天完整快照」寫回 `holdings` 表。

已確認的產品決定：
1. 自動觸發（`saved` 非空即觸發），不需要人工再做一次「確認持股」的
   動作。
2. 買：加權平均法算新均價（`shares<=0` 時新均價=成交價；舊均價本身
   缺值時新均價保持缺值，不瞎猜）。賣：股數減少，均價不變。都不含
   手續費（`trade_ledger` 沒存這個欄位，不擴充範圍）。
3. 之後重新上傳券商持股報告永遠優先——這件事完全靠 `holdings.id`
   AUTOINCREMENT 嚴格遞增＋`kb_store.get_holdings()` 改成取每天每代碼
   最大 id 那列自然達成（見 `kb_store.py::get_holdings()`），本模組
   不需要額外的「來源優先權」判斷。

刻意逐筆套用而非批次淨額聚合：同一批次「先買後賣」跟「先賣後買」算出
的加權平均成本不同（賣出不影響均價，但下一筆買進的均價基準是「賣出後
剩餘的股數」），必須按 (date, 原始出現順序) 排序後依序模擬，不能簡化
成「這批總買股數/總買金額」這種聚合算法。

明確不做：不回填/修正 `trade_ledger` 既有歷史推算 `avg_cost` 缺值
（`trade_ledger` 本身有大量疑似重複列，回填風險高，不在範圍內）；不
觸及老芋頭進出（`trade_text_parser.py`，那是跟蹤別人的交易，不是 PO
自己的持股，不觸發這裡的同步）。
"""
from __future__ import annotations


def sync_holdings_from_trades(store, trades, snapshot_date=None,
                               source_ref="交易紀錄自動同步"):
    """依這批交易更新持股快照。

    trades：`resolve_and_save_trade_ledger()` 回傳的 `saved` 清單格式
    （每筆至少含 `code`／`name`／`action`／`shares`／`price`／`date`；
    `add_sequence`／`order_ref` 等其餘欄位不使用）。**呼叫端必須保持
    這份清單的原始出現順序**——同代碼的排序 tie-break 用
    (date, 這份清單裡的原始位置)，不是重新猜測真實下單時間。

    trades 為空（呼叫端沒有任何交易真的寫入，例如整批都是
    unresolved_names 或 duplicates_skipped）時完全不觸發，回傳
    synced=False，不呼叫 save_holdings()——避免無意義地把 baseline
    原封不動重寫一份新快照。

    baseline 一律讀 `store.get_holdings()`（不帶 code，取最新快照、已
    篩掉 shares<=0 的代碼）——因此「先前已出清、這批又重新買回」的
    代碼會被當成全新持股處理（shares 從 0 起算，符合「shares<=0 時新
    均價=成交價」的規則），不需要額外的特殊分支。

    回傳 dict：
        synced: bool，是否真的執行了同步
        codes_new: 這批交易讓一個原本沒有持股（不在 baseline）的代碼
            變成有持股（同步後 shares>0）
        codes_cleared: 這批交易讓一個原本有持股（在 baseline）的代碼
            歸零（同步後 shares<=0）
        avg_cost_unknown_codes: 這批交易有碰到、且同步後 shares>0、但
            均價算不出來（舊均價本身就是缺值）的代碼——不含完全沒被
            這批交易碰到、只是原封不動搬過去的代碼
        oversold_codes: 這批交易裡有任何一筆賣出超過當時可賣股數的
            代碼（股數已 floor 在 0，這裡只是標記供人工注意，去重）
        save_result: `store.save_holdings()` 的原始回傳
            （synced=False 時為 None）
    """
    empty_result = {
        "synced": False, "codes_new": [], "codes_cleared": [],
        "avg_cost_unknown_codes": [], "oversold_codes": [],
        "save_result": None,
    }
    if not trades:
        return empty_result

    by_code = {}
    for idx, t in enumerate(trades):
        by_code.setdefault(t["code"], []).append((idx, t))
    if not by_code:
        return empty_result

    baseline = store.get_holdings()
    baseline_by_code = {h["code"]: dict(h) for h in baseline["holdings"]}

    codes_new = []
    codes_cleared = []
    avg_cost_unknown_codes = []
    oversold_codes = []

    result_by_code = {}
    # 沒被這批交易碰到的既有持股，原封不動搬到新快照（同一批次要重建
    # 「今天完整快照」，不能只寫有交易的那幾檔，否則今天沒交易的其他
    # 股票會因為最後快照停留在舊日期而從查詢結果整批消失）。
    for code, row in baseline_by_code.items():
        if code not in by_code:
            result_by_code[code] = {
                "code": code, "name": row.get("name"),
                "shares": row.get("shares"), "avg_cost": row.get("avg_cost"),
            }

    for code, group in by_code.items():
        # 依 (date, 原始出現順序) 排序——Python sort 穩定，用這個鍵即可
        # 達成「同日按原始出現順序」的 tie-break（不猜真實下單時間）。
        group.sort(key=lambda item: (item[1]["date"], item[0]))

        existing = baseline_by_code.get(code)
        is_new_code = existing is None
        shares = (existing.get("shares") if existing else None) or 0
        avg_cost = existing.get("avg_cost") if existing else None
        name = existing.get("name") if existing else None

        for _, t in group:
            name = t.get("name") or name
            if t["action"] == "買":
                buy_shares = t["shares"]
                price = t["price"]
                if shares <= 0:
                    # 手上沒股票（含新股票、或這批次裡先賣光又買回）：
                    # 新均價直接等於這筆成交價。
                    avg_cost = price
                elif avg_cost is not None:
                    avg_cost = ((shares * avg_cost + buy_shares * price)
                                / (shares + buy_shares))
                # else：shares>0 但 avg_cost 本身缺值——保持缺值，不瞎猜。
                shares = shares + buy_shares
            else:  # 賣：股數減少，均價不變
                sell_shares = t["shares"]
                if sell_shares > shares:
                    oversold_codes.append(code)
                shares = max(0, shares - sell_shares)

        if is_new_code and shares > 0:
            codes_new.append(code)
        if existing is not None and shares <= 0:
            codes_cleared.append(code)
        if shares > 0 and avg_cost is None:
            avg_cost_unknown_codes.append(code)

        result_by_code[code] = {
            "code": code, "name": name, "shares": shares, "avg_cost": avg_cost,
        }

    rows = list(result_by_code.values())
    save_result = store.save_holdings(rows, snapshot_date=snapshot_date,
                                       source_ref=source_ref)

    return {
        "synced": True,
        "codes_new": codes_new,
        "codes_cleared": codes_cleared,
        "avg_cost_unknown_codes": avg_cost_unknown_codes,
        "oversold_codes": sorted(set(oversold_codes)),
        "save_result": save_result,
    }
