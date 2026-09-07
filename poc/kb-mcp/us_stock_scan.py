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

**Phase 5（US3，T027）擴充**：股票報價成功寫入後，接著評估該股票的所有
`us_watch_conditions`（見 `_evaluate_watch_conditions_for_ticker()`）：

- 股票整體排程失敗（額度用盡/查詢例外，`outcome.get("error")` 非空）：
  **完全不呼叫**任何監控條件的評估方法——這批條件的 `status`／
  `last_evaluated_at` 維持上一次的值，`USStockStore._is_stale()` 之後會
  據此判斷為「未更新（無額度）」（data-model.md §3）。
- 股票整體成功，但單一監控條件對應的 `metric_type` 這輪沒有值（例如
  基本面查詢單獨失敗，見既有 `test_fundamentals_failure_does_not_block_price_write`
  先例）：這筆條件也**不更新**——處理方式與「整體跳過」一致，理由見
  `_evaluate_condition()` docstring。
- 條件能算出新狀態（`ok`/`alert`）：呼叫
  `store.update_watch_condition_evaluation()`。若本輪 `alert` 且前一次
  不是 `alert`（新觸發，FR-012），呼叫 `notify_telegram()`（見下方 stub
  說明）；持續 `alert` 不重複推播。
- `notify_telegram()` 目前是**明確標記的 stub**——`function/stnd-gateway-web`
  分支（本分支工作目錄沒有這支程式碼，tasks.md T027 開頭已確認）合併
  進來之後，要把這裡換成真正呼叫該分支建立的 Telegram 閘道。
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import us_stock_price_client  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402


def notify_telegram(message):
    """Telegram 推播 stub（T027）。

    **TODO（`function/stnd-gateway-web` 分支合併進來之後要做的事）**：
    這支分支目前不在本分支（003-us-stocks）的工作目錄裡（已確認：
    `grep -rl "telegram" app/ poc/kb-mcp/` 完全沒有命中既有程式碼），所以
    這裡先不假裝知道那支分支的實際呼叫介面（HTTP 端點？直接 import 的
    Python 函式？需要什麼認證/使用者識別參數？）。合併後請：
    1. 查看該分支實際提供的推播介面（函式簽章或 HTTP API）
    2. 把這個函式內部換成真正呼叫該介面，**保留相同的函式簽章**
       `notify_telegram(message: str) -> bool`，這樣 `run_scan()` 呼叫端
       跟這支檔案的測試（`test_us_stock_scan.py`）都不需要跟著改
    3. 確認失敗時的行為：目前的設計是「推播失敗不影響監控狀態的正確性」
       （spec.md Acceptance Scenario 5），也就是即使這個函式回傳
       `False`，`run_scan()` 仍然照常更新 `status`／`last_evaluated_at`，
       只是不更新 `last_notified_at`（讓下一輪仍是 alert 狀態時可以
       重試推播，見 `run_scan()` 對回傳值的處理）——真正接上閘道後這個
       行為應該維持，不要因為要「確保推播一定送出」而讓推播失敗回頭
       影響監控狀態的寫入

    目前：只把「本應推播的訊息內容」記錄到 stderr，回傳 `True`（假裝
    推播成功）。回傳值刻意做成 bool 而非拋例外——呼叫端要能區分「推播
    成功/失敗」來決定要不要更新 `last_notified_at`，例外會讓這個判斷變
    複雜，且一次推播失敗不該中斷其餘股票/條件的評估（比照本檔案其餘
    降級模式的一貫精神）。
    """
    sys.stderr.write("us_stock_scan[notify_telegram STUB]：%s\n" % message)
    sys.stderr.flush()
    return True


def _evaluate_condition(condition, outcome):
    """比對單一監控條件與本輪抓到的資料，回傳新狀態字串（`"ok"`／
    `"alert"`）或 `None`。

    回傳 `None` 代表這輪抓不到這個條件對應的 `metric_type` 數值（可能是
    `metric_type` 不在 `us_price_snapshots` 目前支援的 3 種欄位內，或該
    欄位這輪剛好是 `None`——例如基本面查詢單獨失敗，價格仍成功）——這種
    情況呼叫端**不應該**更新這筆條件的 `status`／`last_evaluated_at`，
    理由：如果把它降級為 `insufficient_data`，會抹掉這筆條件過去可能已
    經是 `ok`/`alert` 的正確歷史狀態，且跟 FR-017「資料不足」的定義
    （＝從未成功取得過資料）不符——這裡碰到的是「這輪暫時沒有這個特定
    指標的值」，語意上更接近「這輪沒刷新到」，處理方式比照額度用盡跳過
    整檔股票的既有先例（不更新，不誤判）。"""
    metric_type = condition["metric_type"]
    if metric_type == "price":
        value = outcome.get("close_price")
    elif metric_type == "gaap_gross_margin":
        value = outcome.get("gaap_gross_margin")
    elif metric_type == "revenue_yoy":
        value = outcome.get("revenue_yoy")
    else:
        value = None
    if value is None:
        return None
    threshold = condition["threshold"]
    if condition["comparator"] == "lt":
        triggered = value < threshold
    else:  # "gt"
        triggered = value > threshold
    return "alert" if triggered else "ok"


def _evaluate_watch_conditions_for_ticker(store, ticker, outcome, evaluated_at):
    """對一檔「本輪排程成功」的股票，逐一評估它的監控條件並視需要推播。
    只在股票整體成功時才會被呼叫（見 `run_scan()`）——額度用盡跳過的
    股票完全不會走到這裡，對應 data-model.md §3 的狀態轉換規則。

    回傳這輪實際更新過的條件清單（供 CLI 印出摘要／測試驗證用，非
    必要欄位）。"""
    updated = []
    for condition in store.list_watch_conditions(ticker):
        new_status = _evaluate_condition(condition, outcome)
        if new_status is None:
            continue  # 這輪抓不到這個指標，維持原狀不動（見上方 docstring）
        prev_status = condition["status"]
        prev_notified_at = condition["last_notified_at"]
        store.update_watch_condition_evaluation(
            condition["id"], new_status, evaluated_at=evaluated_at)
        newly_triggered = new_status == "alert" and prev_status != "alert"
        notified = False
        if newly_triggered:
            message = (
                "【美股監控】%s %s %s %s（目前狀態：已觸發）" % (
                    ticker, condition["metric_type"],
                    "跌破" if condition["comparator"] == "lt" else "突破",
                    condition["threshold"],
                )
            )
            sent = notify_telegram(message)
            if sent:
                store.mark_watch_condition_notified(
                    condition["id"], notified_at=evaluated_at)
                notified = True
            # sent=False：刻意不更新 last_notified_at，讓下一輪只要仍是
            # alert 狀態就會再次嘗試推播（見 notify_telegram() docstring
            # 第3點）——不因為這次推播失敗就假裝已經通知過。
        updated.append({
            "condition_id": condition["id"], "ticker": ticker,
            "prev_status": prev_status, "new_status": new_status,
            "newly_triggered": newly_triggered, "notified": notified,
            "prev_notified_at": prev_notified_at,
        })
    return updated


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
    """對追蹤中的所有股票各自抓一次報價／基本面並寫入 `us_price_snapshots`，
    成功的股票接著評估它的監控條件（T027）。

    回傳 `{"snapshot_date":.., "results": [...], "condition_updates": [...]}`：
    - `results`：每筆含 `ticker`／`saved`／`error`，供 CLI `main()` 印出
      摘要、供測試驗證降級行為（單一股票失敗不影響其餘股票）。
    - `condition_updates`：這輪**實際更新過**的監控條件清單（額度用盡
      跳過、或該輪抓不到對應 metric_type 的條件都不會出現在這裡——見
      `_evaluate_watch_conditions_for_ticker()` docstring），供測試驗證
      FR-012 的推播判斷邏輯。
    """
    store = USStockStore(data_dir)
    try:
        tickers = store.get_tracked_tickers()
        snapshot_date = datetime.date.today().isoformat()
        evaluated_at = datetime.datetime.now().isoformat(timespec="seconds")
        results = []
        condition_updates = []
        for ticker in tickers:
            outcome = _scan_one_ticker(ticker, data_dir, token=token)
            if outcome.get("error"):
                # 整檔股票這輪跳過（額度用盡/查詢例外）：完全不呼叫監控
                # 條件評估——這批條件的 status／last_evaluated_at 維持
                # 上一次的值，data-model.md §3 狀態轉換規則。
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
            if outcome["saved"]:
                condition_updates.extend(
                    _evaluate_watch_conditions_for_ticker(
                        store, ticker, outcome, evaluated_at))
        return {"snapshot_date": snapshot_date, "results": results,
                "condition_updates": condition_updates}
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
    for update in result["condition_updates"]:
        if update["newly_triggered"]:
            print("us_stock_scan監控條件新觸發：ticker=%s condition_id=%s"
                  " notified=%s" % (update["ticker"], update["condition_id"],
                                     update["notified"]))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
