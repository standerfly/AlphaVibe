"""FIFO 持股損益計算（FR-001~FR-006、FR-011）。

設計原則：**純函式，不碰 I/O**——輸入是 trade_ledger 的交易列與現價
dict，輸出是結果 dict。資料庫存取留給呼叫端（server.py），這樣測試
不需要建資料庫，也不可能誤寫正式庫。

## 三個容易踩的坑（都有測試釘住，見 tests/test_pnl.py）

1. **股數單位是「股」不是「張」**：金額即 `股數 × 價格`，**不可 ×1000**。
   證據見 specs/001-entry-exit-foundation/research.md R-001——大立光買
   3 @2605 ＝ 7,815 元（零股交易），若當成張則是 781 萬，與本投組規模
   不符。規劃階段曾有一份盤點報告據值域推論為「張」，已證實錯誤。

2. **賣出可能超過買進**：交易流水表起始於 2025-11-21，之前的既有部位
   沒有進場紀錄，實測 60 檔中有 21 檔累計賣出 > 累計買進。這種標的
   回 status="history_incomplete" 並附缺口股數，**不猜測缺失批次的成本**，
   也不輸出未實現損益（FR-004）。

3. **疑似重複列照原樣計入**（PO 2026-09-02 裁決 Q2-A）：實測流水表有
   141 筆同 code/action/shares/price/date 的多餘列。「同日同價買進相同
   股數」可能是真實的分批下單，自動排除有誤刪真單的風險，所以只在
   suspected_duplicates 附警示，不排除、不修改原始資料（FR-006）。

## 已知限制

流水表沒有手續費與證交稅欄位，所有損益都是**毛額**
（fees_included 固定為 False，FR-005）。要與券商對帳需自行扣除。
"""

COST_METHOD = "FIFO"


def resolve_current_price(code, prices):
    """從 KBStore.get_stock_prices() 的回傳取現價與其日期。

    回傳 (price, price_date)；查無資料回 (None, None)。
    price_date 要一路帶到輸出，讓使用者判斷報價新鮮度。
    """
    row = (prices or {}).get(code)
    if not row:
        return (None, None)
    return (row.get("price"), row.get("price_date"))


def _count_suspected_duplicates(rows):
    """同 code/action/shares/price/date 視為疑似重複；回傳「多餘」筆數
    （出現 3 次算 2 筆多餘）。只計數不排除，理由見模組 docstring。"""
    seen = {}
    for row in rows:
        key = (row.get("code"), row.get("action"), row.get("shares"),
               row.get("price"), row.get("date"))
        seen[key] = seen.get(key, 0) + 1
    return sum(count - 1 for count in seen.values() if count > 1)


def _empty_result(code, name=None, status="no_trades"):
    return {
        "code": code, "name": name, "cost_method": COST_METHOD,
        "fees_included": False, "status": status,
        "realized_pnl": None, "unrealized_pnl": None, "unrealized_pct": None,
        "shares_held": 0.0, "cost_basis": 0.0,
        "current_price": None, "price_date": None,
        "suspected_duplicates": 0, "shortfall_shares": None,
        "note": "金額為毛額，未扣手續費與證交稅",
    }


def compute_position_pnl(code, entries, prices):
    """算單一標的的 FIFO 損益。

    entries 可以是該標的的交易列，也可以是全部標的的交易列（會自行
    篩選 code），呼叫端不必先分組。
    """
    rows = [r for r in (entries or []) if r.get("code") == code]
    if not rows:
        return _empty_result(code)

    # 排序鍵沿用 kb_store.get_trade_ledger 的既有語意：date 為主、id 為次，
    # 同一天多筆時用寫入順序決定先後。
    rows.sort(key=lambda r: (r.get("date") or "", r.get("id") or 0))
    name = rows[0].get("name")
    duplicates = _count_suspected_duplicates(rows)

    lots = []          # FIFO 佇列：[{"shares": 剩餘股數, "price": 單價}]
    realized = 0.0
    shortfall = 0.0    # 賣出但配不到買進批次的股數

    for row in rows:
        action = row.get("action")
        shares = float(row.get("shares") or 0)
        price = float(row.get("price") or 0)
        if shares <= 0:
            continue
        if action == "買":
            lots.append({"shares": shares, "price": price})
        elif action == "賣":
            remaining = shares
            while remaining > 0 and lots:
                lot = lots[0]
                matched = min(lot["shares"], remaining)
                realized += (price - lot["price"]) * matched
                lot["shares"] -= matched
                remaining -= matched
                if lot["shares"] <= 0:
                    lots.pop(0)
            if remaining > 0:
                # 買進紀錄不足以配對——既有部位在流水表起始日之前建立
                shortfall += remaining
        # 其他 action 值不存在（kb_store.py:1141-1142 已強制只收「買」/「賣」），
        # 真的出現就當作不影響持股的雜訊略過。

    shares_held = sum(lot["shares"] for lot in lots)
    cost_basis = sum(lot["shares"] * lot["price"] for lot in lots)
    current_price, price_date = resolve_current_price(code, prices)

    result = _empty_result(code, name)
    result.update({
        "realized_pnl": round(realized, 2),
        "shares_held": round(shares_held, 4),
        "cost_basis": round(cost_basis, 2),
        "current_price": current_price,
        "price_date": price_date,
        "suspected_duplicates": duplicates,
    })

    # status 判定順序（見 specs/001-entry-exit-foundation/data-model.md）：
    # no_trades → history_incomplete → no_price → ok
    if shortfall > 0:
        result["status"] = "history_incomplete"
        result["shortfall_shares"] = round(shortfall, 4)
        # 已實現只算配得上批次的部分；未實現不輸出（不捏造缺失批次成本）
        return result

    if shares_held > 0 and current_price is None:
        result["status"] = "no_price"
        return result

    result["status"] = "ok"
    if shares_held > 0:
        market_value = shares_held * float(current_price)
        unrealized = market_value - cost_basis
        result["unrealized_pnl"] = round(unrealized, 2)
        result["unrealized_pct"] = (round(unrealized / cost_basis * 100, 2)
                                    if cost_basis else None)
    else:
        # 已全數出清：已實現損益照常回傳（FR-003），未實現為 0
        result["unrealized_pnl"] = 0.0
        result["unrealized_pct"] = None
    return result


def compute_all_positions(entries, prices):
    """全部標的的 FIFO 損益（FR-011）。

    每檔獨立計算並各自 try 保護——任何單一標的的資料問題都不會讓整批
    查詢失敗，這是 FR-011 的核心要求。
    """
    codes = []
    for row in (entries or []):
        code = row.get("code")
        if code and code not in codes:
            codes.append(code)
    codes.sort()

    positions = []
    summary = {"ok": 0, "history_incomplete": 0, "no_price": 0,
               "no_trades": 0, "error": 0}
    for code in codes:
        try:
            item = compute_position_pnl(code, entries, prices)
        except Exception as exc:  # 單檔失敗不影響其他檔
            item = _empty_result(code, status="error")
            item["note"] = "計算失敗：%s" % exc
        positions.append(item)
        status = item.get("status", "error")
        summary[status] = summary.get(status, 0) + 1

    return {
        "count": len(positions),
        "cost_method": COST_METHOD,
        "fees_included": False,
        "positions": positions,
        "summary": summary,
        "note": "金額為毛額，未扣手續費與證交稅",
    }
