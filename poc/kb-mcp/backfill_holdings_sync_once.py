"""交易紀錄自動同步持股快照——回溯補做，一次性、需要人手動執行的腳本。

2026-09-02 情境：holdings_sync.py 上線前，PO 已經透過 STND Telegram 管家
匯入了一批交易（`trade_ledger`），但當時還沒有自動同步機制，這批交易
沒有反映到 `holdings` 持股快照。這支腳本補做這一次同步：查
`trade_ledger WHERE date=?`（依 id 排序＝原始寫入順序，同一批匯入時
id 遞增順序等同 resolve_and_save_trade_ledger() 的 saved 清單原始順序）
→ 呼叫 sync_holdings_from_trades() → 印出結果供人工核對。

**不是**讓 resolve_and_save_trade_ledger() 重跑一次——那樣會在
trade_ledger 造成重複 INSERT（這批交易本來就已經寫進去了，只是持股
快照沒跟上），這支腳本只補「同步」那一步，不重新解析/寫入交易本身。

用法（正式環境，只需要跑一次）：
    python3 poc/kb-mcp/backfill_holdings_sync_once.py \\
        --data-dir poc/data --date 2026-09-01

用法（測試環境）：
    python3 poc/kb-mcp/backfill_holdings_sync_once.py \\
        --data-dir poc/data-test --date 2026-09-01

冪等性提醒：跟 seed_assets_once.py 不同，這支腳本**不是**冪等的——
重跑會讓 sync_holdings_from_trades() 依「當時的最新 baseline」再套用
一次同一批交易，若兩次執行之間 baseline 已經反映過這批交易，第二次會
把它們再套用一次（例如買進股數變兩倍）。只在確認這批交易「還沒有」被
同步過的情況下執行一次；跑完之後，之後每次匯入交易都會自動同步，不需
要再手動跑這支腳本。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import holdings_sync  # noqa: E402
from kb_store import KBStore  # noqa: E402


def _load_trades_for_date(store, date):
    """依 id（原始寫入順序）取出 trade_ledger 裡指定日期的全部列，轉成
    sync_holdings_from_trades() 需要的欄位格式（code/name/action/
    shares/price/date）。"""
    rows = store.conn.execute(
        "SELECT code, name, action, shares, price, date"
        " FROM trade_ledger WHERE date=? ORDER BY id", (date,),
    ).fetchall()
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True,
        help="資料目錄路徑（明確指定，不提供預設值——避免重蹈 "
             "2026-08-22 覆轍：不小心指到正式庫或搞錯環境）",
    )
    parser.add_argument(
        "--date", required=True,
        help="要回溯同步的交易日期（YYYY-MM-DD，篩選 trade_ledger.date）",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    print("資料目錄：%s" % data_dir)
    print("回溯日期：%s" % args.date)

    store = KBStore(data_dir)
    try:
        trades = _load_trades_for_date(store, args.date)
        print("trade_ledger 該日期共 %d 筆交易。" % len(trades))
        if not trades:
            print("沒有交易可同步，不執行任何寫入。")
            return 0

        result = holdings_sync.sync_holdings_from_trades(store, trades)

        print("同步完成：synced=%r" % result["synced"])
        print("新增持股 codes_new：%r" % result["codes_new"])
        print("已出清 codes_cleared：%r" % result["codes_cleared"])
        print("均價缺值 avg_cost_unknown_codes：%r"
              % result["avg_cost_unknown_codes"])
        print("賣超 oversold_codes：%r" % result["oversold_codes"])
        save_result = result["save_result"] or {}
        print("save_holdings 寫入筆數：%r，快照日期：%r"
              % (save_result.get("count"), save_result.get("snapshot_date")))

        latest = store.get_holdings()
        print("同步後 get_holdings() 快照日期 %r，共 %d 檔："
              % (latest["snapshot_date"], latest["count"]))
        for h in latest["holdings"]:
            print("  %s %s shares=%r avg_cost=%r"
                  % (h["code"], h.get("name"), h["shares"], h["avg_cost"]))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
