"""美股報價每日排程 CLI 入口。

比照 `poc/kb-mcp/market_scan.py` 的降級模式（單位獨立 try/except、不因
單一股票失敗中斷其餘）與 CLI `main()` 結構，但**完全獨立**：不 import
`market_scan.py`／`kb_store.py`／`finmind_client.py` 等既有台股模組，
只呼叫本次新增的 `USStockStore`（`us_stock_store.py`）與
`us_stock_price_client.py`（`research.md` §2 查詢管道獨立決策）。

排程部署方式（launchd plist，比照 `com.alphavibe.marketscan.plist`）見
`specs/003-us-stocks/quickstart.md`「launchd 部署步驟」一節——這個腳本
本身不建立、不部署 plist（比照既有先例，plist 是直接手動建在使用者
機器上的獨立檔案，不進版控）。

降級規則（`data-model.md` §4「歷史缺口」、`research.md` §4）：
- 追蹤股票清單＝四張表 ticker 聯集（`USStockStore.get_tracked_tickers()`）
- 每檔股票獨立包 try/except，主要來源（FMP）失敗直接記錄錯誤、跳過寫入，
  不中斷其餘股票的處理（比照 `market_scan.py:307-319` 的既有模式）
- 這一輪（Foundational，Phase 2）只負責「抓資料寫入 us_price_snapshots」，
  **不評估** `us_watch_conditions`——監控條件的評估/推播是 Phase 5
  （US3，T027）的擴充範圍，見 tasks.md「跨 Story 的資料相依」一節
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import us_stock_price_client  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402


def default_data_dir():
    """比照 `market_scan.py::default_data_dir()` 的既有慣例：環境變數
    `ALPHAVIBE_DATA_DIR`（跟既有台股腳本共用同一個「資料目錄在哪」的
    環境變數——兩者的 db 檔案本來就住在同一個 `poc/data/` 目錄下，只是
    檔名不同，共用目錄變數不影響 FR-015/016 的程式碼/資料表獨立要求），
    未設定則預設 `<本檔案>/../data`。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


def _scan_one_ticker(ticker, data_dir, token=None):
    """單一股票獨立 try/except：任何非預期例外都轉成 `{"error": ...}`，
    不往外拋，確保呼叫端（`run_scan`）的迴圈不會被單一股票中斷（比照
    `market_scan.py::_scan_market` 同樣的防線精神）。"""
    try:
        quote = us_stock_price_client.get_quote(
            ticker, data_dir=data_dir, token=token)
        if "error" in quote:
            return {"ticker": ticker, "error": quote["error"], "saved": False}

        fundamentals = us_stock_price_client.get_fundamentals(
            ticker, data_dir=data_dir, token=token)
        gaap_gross_margin = None
        revenue_yoy = None
        if "error" not in fundamentals:
            gaap_gross_margin = fundamentals.get("gaap_gross_margin")
            revenue_yoy = fundamentals.get("revenue_yoy")
        # 基本面查詢失敗不影響報價本身寫入——兩者是獨立欄位，能查到多少
        # 算多少（比照 market_scan.py 對「有多少存多少」的既有精神）。

        return {
            "ticker": ticker,
            "close_price": quote.get("close_price"),
            "gaap_gross_margin": gaap_gross_margin,
            "revenue_yoy": revenue_yoy,
            "source": quote.get("source", "fmp"),
            "error": None,
            "saved": False,
        }
    except Exception as exc:  # 非預期錯誤不可讓其他股票也失敗
        return {"ticker": ticker, "error": "非預期錯誤：%s" % exc, "saved": False}


def run_scan(data_dir, token=None):
    """對追蹤中的所有股票各自抓一次報價／基本面並寫入 `us_price_snapshots`。

    回傳 `{"snapshot_date":.., "results": [...]}`，每筆 result 含
    `ticker`／`saved`／`error`，供 CLI `main()` 印出摘要、供測試驗證
    降級行為（單一股票失敗不影響其餘股票）。
    """
    store = USStockStore(data_dir)
    try:
        tickers = store.get_tracked_tickers()
        snapshot_date = datetime.date.today().isoformat()
        results = []
        for ticker in tickers:
            outcome = _scan_one_ticker(ticker, data_dir, token=token)
            if outcome.get("error"):
                results.append(outcome)
                continue
            try:
                store.save_price_snapshot(
                    ticker=ticker, snapshot_date=snapshot_date,
                    close_price=outcome.get("close_price"),
                    gaap_gross_margin=outcome.get("gaap_gross_margin"),
                    revenue_yoy=outcome.get("revenue_yoy"),
                    source=outcome.get("source", "fmp"),
                )
                outcome["saved"] = True
            except Exception as exc:  # 寫入失敗同樣不可中斷其餘股票
                outcome["error"] = "寫入失敗：%s" % exc
                outcome["saved"] = False
            results.append(outcome)
        return {"snapshot_date": snapshot_date, "results": results}
    finally:
        store.close()


def main(argv=None):
    """CLI 入口，供 launchd 排程呼叫（`--trigger scheduled`）；也可手動跑
    `python3 us_stock_scan.py --trigger manual` 立即測試一次。`--trigger`
    目前只影響印出的訊息，尚無對應的排程紀錄表可寫入（這 4 張表沒有
    「掃描批次」這種 log 表，跟 `market_scan.py` 的 `market_scan_runs`
    不同）——留著這個參數只是為了跟既有 CLI 慣例、quickstart.md 的文件
    保持一致的呼叫介面。

    任一股票失敗回傳碼 1，但其餘股票仍會處理完、能存的都存（比照
    `market_scan.py::main()` 同樣「部分失敗不影響整體」的退出碼精神）。
    """
    parser = argparse.ArgumentParser(
        description="美股每日報價排程（獨立於台股 market_scan.py）")
    parser.add_argument("--data-dir", default=None, help="資料目錄（預設 poc/data）")
    parser.add_argument("--trigger", default="scheduled",
                         choices=("scheduled", "manual"))
    args = parser.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir or default_data_dir())
    result = run_scan(data_dir)

    exit_code = 0
    for row in result["results"]:
        if row.get("error"):
            print("us_stock_scan失敗：trigger=%s ticker=%s error=%s"
                  % (args.trigger, row["ticker"], row["error"]))
            exit_code = 1
        else:
            print("us_stock_scan完成：trigger=%s ticker=%s close_price=%s snapshot_date=%s"
                  % (args.trigger, row["ticker"], row.get("close_price"),
                     result["snapshot_date"]))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
