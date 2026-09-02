"""模組E 每日排程整合（FR-057）CLI 入口，供 launchd 排程呼叫
（`--trigger scheduled`）；也可手動跑 `python3 module_d_scheduler.py`
立即測試一次，不用等排程時間到。

比照 `market_scan.py` 的 `main()` 既有CLI慣例：`--data-dir`／
`--trigger scheduled|manual` 兩個參數，跑完印一行執行摘要。這次刻意
不做的事（PO已確認範圍，見派工說明）：
- 不改／不安裝 launchd plist 或任何系統排程設定——這裡只提供可手動執行
  的CLI進入點，怎麼接上系統排程留待下一步跟PO確認。
- module_d_results 表沒有 trigger_source 欄位（product-spec.md 定義的
  欄位不含這項），故 --trigger 只用於印出的執行摘要，不持久化。

實際批次邏輯（觀察名單＋庫存去重、單檔失敗不中斷整批）在
`review_engine.run_module_d_batch()`，這裡只是CLI包裝＋摘要輸出。

僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import os

import review_engine
from kb_store import KBStore


def default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="模組D每日排程整合（FR-057）：觀察名單＋庫存策略檢視")
    parser.add_argument("--data-dir", default=None, help="資料目錄（預設 poc/data）")
    parser.add_argument("--trigger", default="scheduled", choices=("scheduled", "manual"))
    args = parser.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir or default_data_dir())

    store = KBStore(data_dir)
    exit_code = 0
    # 002-entry-exit-signals R-009：加上時間戳與逐階段耗時。
    # 改動前這支腳本的輸出完全沒有時間資訊，要查排程跑多久只能回頭從
    # module_d_results.checked_at 反推——FR-012 要求「執行時間增幅可被
    # 量測」，沒有這幾行就無從驗證。
    started_at = datetime.datetime.now()
    print("module_d_scheduler開始：trigger=%s at=%s"
          % (args.trigger, started_at.isoformat(timespec="seconds")))
    try:
        batch_started = datetime.datetime.now()
        summary = review_engine.run_module_d_batch(store, data_dir=data_dir)
        batch_secs = (datetime.datetime.now() - batch_started).total_seconds()
        print("module_d_scheduler完成：trigger=%s total=%d checked=%d failed=%d concern=%d"
              " 批次耗時=%.1f秒"
              % (args.trigger, summary["total"], summary["checked_count"],
                 summary["failed_count"], len(summary["concern_codes"]), batch_secs))
        for f in summary["failed"]:
            print("  失敗：%s — %s" % (f["code"], f["error"]))

        # 2026-08-01新增：同一批代碼（跟run_module_d_batch的觀察名單＋庫存
        # 範圍完全一致，直接取summary["results"]裡每筆的code，不重新算一次
        # 去重清單）順便刷新股價/估值快照，供個股清單頁/詳情頁讀快取——
        # 不重跑run_module_d_review（上面run_module_d_batch已經跑過一次，
        # 見review_engine.refresh_stock_snapshot()docstring說明為何排程
        # 刻意不呼叫該函式）。單檔失敗不中斷整批，比照上面既有慣例。
        price_failed = 0
        for result in summary["results"]:
            try:
                review_engine.refresh_price_and_valuation(
                    result["code"], store, data_dir=data_dir)
            except Exception as exc:
                price_failed += 1
                print("  價格/估值刷新失敗：%s — %s" % (result["code"], exc))
        if summary["results"]:
            print("module_d_scheduler價格/估值刷新完成：total=%d failed=%d"
                  % (len(summary["results"]), price_failed))
    except Exception as exc:  # 排程失敗不該讓 launchd 認為是靜默成功
        print("module_d_scheduler失敗：%s" % exc)
        exit_code = 1
    finally:
        total_secs = (datetime.datetime.now() - started_at).total_seconds()
        print("module_d_scheduler結束：at=%s 總耗時=%.1f秒"
              % (datetime.datetime.now().isoformat(timespec="seconds"), total_secs))
        store.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
