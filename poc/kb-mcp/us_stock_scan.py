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
  不是 `alert`（新觸發，FR-012），呼叫 `notify_telegram()`；持續
  `alert` 不重複推播。

**Telegram 推播（2026-09-08 接上）**：`function/stnd-gateway-web` 分支
查證結果——真正的 Telegram bot 是完全獨立的專案
`/Users/stander/My_project/AI/telegram_gateway/`（常駐 long-polling
process，不在本 repo），STND 這邊既有的整合模式（`gateway_monitor.py`，
該分支）刻意「獨立實作、不 import telegram_gateway」，只共用設定值
（`~/.config/stnd-gateway/.env` 的 `TELEGRAM_BOT_TOKEN`／
`ALLOWED_USER_IDS`），不共用程式碼。這裡照同一個既有慣例：直接呼叫
Telegram Bot API 的 `sendMessage` HTTP 端點（`urllib`，不新增依賴，也不
import `python-telegram-bot`），token 用跟 `gateway_monitor.py` 完全
一致的手刻 KEY=VALUE parser 從共用 env 檔讀取，**絕不寫死進原始碼**。
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import us_stock_price_client  # noqa: E402
from us_stock_store import USStockStore  # noqa: E402

# 共用設定檔路徑：跟 telegram_gateway／`gateway_monitor.py`
# （`function/stnd-gateway-web` 分支）完全一致，可用
# `STND_GATEWAY_ENV_FILE` 覆寫（供測試指向獨立複本，不動到真實設定檔）。
_GATEWAY_ENV_FILE = Path(os.environ.get(
    "STND_GATEWAY_ENV_FILE",
    str(Path.home() / ".config" / "stnd-gateway" / ".env"),
))


def _read_env_value(env_path, key):
    """每次呼叫都重讀檔案（不快取）。逐字比照
    `gateway_monitor.py::_read_env_value()` 的既有寫法，維持兩邊一致。"""
    if not env_path.exists():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def notify_telegram(message):
    """透過 Telegram Bot API 推播一則訊息給 `ALLOWED_USER_IDS`（共用
    `~/.config/stnd-gateway/.env` 設定，逗號分隔可多人，目前只有使用者
    本人一筆）。

    設計取捨（維持既有降級精神，見本檔案開頭）：
    - 直接打 `https://api.telegram.org/bot<token>/sendMessage`，不
      import `python-telegram-bot`／`telegram_gateway`——那是常駐
      long-polling process 的重量級框架，這裡只是「單次、無狀態」的
      推播，用 `urllib` 發一個 POST 就夠，且比照
      `us_stock_price_client.py` 既有的 HTTP client 選型
    - 缺 token／缺白名單、或任何一個 chat_id 送失敗，都**不拋例外**，
      回傳 `False`——呼叫端（`run_scan()`）靠這個 bool 決定要不要更新
      `last_notified_at`，例外會讓那段邏輯複雜化，且一次推播失敗不該
      中斷其餘股票/條件的評估
    - 多個 `ALLOWED_USER_IDS` 時逐一發送；只要有一個成功就不算完全失敗
      （回傳 `True`），避免其中一人封鎖 bot 就讓其他人也收不到
    """
    token = _read_env_value(_GATEWAY_ENV_FILE, "TELEGRAM_BOT_TOKEN")
    allowed_ids_raw = _read_env_value(_GATEWAY_ENV_FILE, "ALLOWED_USER_IDS")
    if not token or not allowed_ids_raw:
        sys.stderr.write(
            "us_stock_scan[notify_telegram]：%s 缺少 TELEGRAM_BOT_TOKEN 或"
            " ALLOWED_USER_IDS，跳過推播\n" % _GATEWAY_ENV_FILE
        )
        return False

    chat_ids = [x.strip() for x in allowed_ids_raw.split(",") if x.strip()]
    any_success = False
    for chat_id in chat_ids:
        try:
            payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
            req = urllib.request.Request(
                "https://api.telegram.org/bot%s/sendMessage" % token,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            any_success = True
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            sys.stderr.write(
                "us_stock_scan[notify_telegram]：推播失敗 chat_id=%s: %s\n"
                % (chat_id, exc)
            )
    return any_success


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
