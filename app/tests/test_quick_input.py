"""快速輸入表單串接的整合測試（2026-08-24 新增，Q-046 待辦第1項：把5個
快速輸入表單接上 web/src/pages/Dashboard.jsx）。

目的：驗證 web/src/components/QuickInputPanel.jsx 實際送出的 request
body 格式，跟 app/routers/actions.py／app/routers/holdings_import.py
真正期待的格式吻合——這是「前端沒串過這6個寫入端點」這次任務唯一新增
的風險面（後端邏輯本身、底層 kb_store.py／trade_text_parser.py／
trade_ledger_parser.py／holdings_parser.py 都是既有函式，不在這裡重測，
已有各自的單元測試）。跟 test_smoke.py 一樣是黑箱測試：真的啟動
uvicorn、真的用 urllib 送 HTTP request，不是 in-process TestClient。

刻意不觸發 FinMind 呼叫（見 CLAUDE.md 2026-07-28 教訓：密集開發時的
測試呼叫會跟正式排程共用同一個匿名額度池，打光了會連累當晚02:00的
正式排程）——老芋頭進出／交易明細表兩個端點的名稱→代碼解析
（stock_alias_resolver.resolve_stock_codes()）會在快取沒命中時打
FinMind，所以這裡測試前先用 store.save_stock_alias() 把測試用的假
股票名稱→代碼寫進 stock_aliases 快取，讓查詢在快取層就命中。

用法（跟 test_smoke.py 完全一致，同一份獨立測試庫即可）：
    ALPHAVIBE_DATA_DIR=poc/data-test .venv/bin/python3 -m app.tests.test_quick_input

安全機制：跟 test_smoke.py 一樣，啟動前檢查 ALPHAVIBE_DATA_DIR 不等於
正式路徑 poc/data/，沒設定或設定成正式路徑會直接拒絕執行。埠號用
8093（跟人工測試常用的8090、test_smoke.py的8091錯開，避免撞號）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_PRODUCTION_DATA_DIR = os.path.abspath(os.path.join(_APP_ROOT, "poc", "data"))
_PORT = 8093
_BASE = "http://127.0.0.1:%d" % _PORT

_KB_MCP_DIR = os.path.join(_APP_ROOT, "poc", "kb-mcp")
if _KB_MCP_DIR not in sys.path:
    sys.path.insert(0, _KB_MCP_DIR)


def _guard_data_dir() -> str:
    data_dir = os.environ.get("ALPHAVIBE_DATA_DIR")
    if not data_dir:
        print("FAIL: 未設定 ALPHAVIBE_DATA_DIR，拒絕執行測試。"
              "請指向一份獨立的測試資料庫複本。")
        sys.exit(1)
    resolved = os.path.abspath(data_dir)
    if resolved == _PRODUCTION_DATA_DIR:
        print("FAIL: ALPHAVIBE_DATA_DIR 指向正式資料庫路徑（%s），拒絕執行測試。"
              % _PRODUCTION_DATA_DIR)
        sys.exit(1)
    return resolved


def _post(path: str, body: dict, timeout: float = 15.0):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, {"_raw": raw.decode("utf-8", "replace")}


def _wait_for_server(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("server process exited early with code %s" % proc.returncode)
        try:
            with urllib.request.urlopen(_BASE + "/api/healthz", timeout=1):
                return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("server did not become ready within %.1fs" % timeout)


def main() -> int:
    data_dir = _guard_data_dir()
    print("測試資料目錄（已確認非正式庫）：%s" % data_dir)

    # 預先寫入測試用的股票別名快取，避免老芋頭進出／交易明細表兩項測試
    # 觸發真正的 FinMind 呼叫（見本檔開頭 docstring）。
    from kb_store import KBStore  # noqa: E402

    seed_store = KBStore(data_dir)
    try:
        seed_store.save_stock_alias("測試股老芋頭", "9801", source="test_quick_input seed")
        seed_store.save_stock_alias("測試股明細表", "9802", source="test_quick_input seed")
        # watchlist 衝突情境：先存一筆「偏多」立場，之後打 /api/watchlist
        # （固定送「觀察」立場）應該回 conflict=True。
        seed_store.save_stance("9803", "偏多", name="測試股衝突", source_ref="test_quick_input seed")
    finally:
        seed_store.close()

    env = dict(os.environ)
    env["ALPHAVIBE_DATA_DIR"] = data_dir
    python = os.path.join(_APP_ROOT, ".venv", "bin", "python3")
    log_path = os.path.join("/tmp", "alphavibe-test-quick-input-server-%d.log" % os.getpid())
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(_PORT)],
        cwd=_APP_ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )

    failures = []
    try:
        _wait_for_server(proc)

        # ---- 1. POST /api/watchlist ----
        status, body = _post("/api/watchlist", {"code": "9800", "name": "測試股加自選"})
        if status == 200 and body.get("saved") is True and body.get("conflict") is False:
            print("PASS POST /api/watchlist 新代碼 -> saved=True/conflict=False")
        else:
            print("FAIL POST /api/watchlist 新代碼 -> status=%s body=%s" % (status, body))
            failures.append("watchlist create")

        status, body = _post("/api/watchlist", {"code": "9803"})
        if (status == 200 and body.get("saved") is False and body.get("conflict") is True
                and body.get("hint")):
            print("PASS POST /api/watchlist 衝突代碼 -> saved=False/conflict=True，附 hint")
        else:
            print("FAIL POST /api/watchlist 衝突代碼 -> status=%s body=%s" % (status, body))
            failures.append("watchlist conflict")

        status, body = _post("/api/watchlist", {"code": "  "})
        if status == 400:
            print("PASS POST /api/watchlist 空代碼 -> 400")
        else:
            print("FAIL POST /api/watchlist 空代碼 -> status=%s（預期400）" % status)
            failures.append("watchlist empty code")

        # ---- 2. POST /api/trades ----
        status, body = _post("/api/trades", {
            "code": "9800", "name": "測試股加自選", "action": "買",
            "shares": 1000, "price": 12.5, "date": "2026-01-05",
        })
        if (status == 200 and body.get("saved") is True and body.get("code") == "9800"
                and body.get("action") == "買" and body.get("id")):
            print("PASS POST /api/trades 正常買進 -> saved=True，回傳 id/code/action 正確")
        else:
            print("FAIL POST /api/trades 正常買進 -> status=%s body=%s" % (status, body))
            failures.append("trades create")

        status, body = _post("/api/trades", {
            "code": "9800", "action": "买", "shares": 100, "price": 10, "date": "2026-01-05",
        })
        if status == 400:
            print("PASS POST /api/trades action不是買/賣 -> 400")
        else:
            print("FAIL POST /api/trades action不是買/賣 -> status=%s（預期400）body=%s" % (status, body))
            failures.append("trades invalid action")

        status, body = _post("/api/trades", {
            "code": "9800", "action": "買", "shares": 100, "date": "2026-01-05",
        })
        if status == 422:
            print("PASS POST /api/trades 缺少 price -> 422（Pydantic 型別檢查）")
        else:
            print("FAIL POST /api/trades 缺少 price -> status=%s（預期422）body=%s" % (status, body))
            failures.append("trades missing price")

        # ---- 3. POST /api/laoyutou-trades ----
        status, body = _post("/api/laoyutou-trades", {
            "text": "20260101\n50買進100股測試股老芋頭",
        })
        saved = body.get("saved") or [] if isinstance(body, dict) else []
        if (status == 200 and body.get("total_parsed") == 1 and len(saved) == 1
                and saved[0].get("code") == "9801"
                and not body.get("unresolved_names") and not body.get("unparsed_lines")):
            print("PASS POST /api/laoyutou-trades 單筆解析並寫入 -> code對應正確、無查無代碼/無法解析")
        else:
            print("FAIL POST /api/laoyutou-trades -> status=%s body=%s" % (status, body))
            failures.append("laoyutou-trades create")

        status, body = _post("/api/laoyutou-trades", {"text": "   "})
        if status == 400:
            print("PASS POST /api/laoyutou-trades 空白內容 -> 400")
        else:
            print("FAIL POST /api/laoyutou-trades 空白內容 -> status=%s（預期400）" % status)
            failures.append("laoyutou-trades empty text")

        # ---- 4. POST /api/trade-ledger ----
        status, body = _post("/api/trade-ledger", {
            "text": "115/07/22 OT買 測試股明細表 10 100.00 0 0 0 0(付) qitest001",
        })
        saved = body.get("saved") or [] if isinstance(body, dict) else []
        if (status == 200 and body.get("total_parsed") == 1 and len(saved) == 1
                and saved[0].get("code") == "9802"
                and not body.get("unresolved_names") and not body.get("unparsed_lines")):
            print("PASS POST /api/trade-ledger 單筆解析並寫入 -> code對應正確、無查無代碼/無法解析")
        else:
            print("FAIL POST /api/trade-ledger -> status=%s body=%s" % (status, body))
            failures.append("trade-ledger create")

        status, body = _post("/api/trade-ledger", {"text": ""})
        if status == 400:
            print("PASS POST /api/trade-ledger 空白內容 -> 400")
        else:
            print("FAIL POST /api/trade-ledger 空白內容 -> status=%s（預期400）" % status)
            failures.append("trade-ledger empty text")

        # ---- 5. POST /api/holdings/preview -> POST /api/holdings/confirm ----
        status, preview_body = _post("/api/holdings/preview", {
            "text": "9911 測試庫存匯入 100",
        })
        rows = preview_body.get("rows") or [] if isinstance(preview_body, dict) else []
        if (status == 200 and preview_body.get("total_parsed") == 1 and len(rows) == 1
                and rows[0].get("code") == "9911" and rows[0].get("shares") == 100
                and "diff" in preview_body):
            print("PASS POST /api/holdings/preview 解析一筆 -> rows/diff 格式正確，未寫入")
        else:
            print("FAIL POST /api/holdings/preview -> status=%s body=%s" % (status, preview_body))
            failures.append("holdings preview")
            rows = []

        if rows:
            status, confirm_body = _post("/api/holdings/confirm", {"rows": rows})
            if (status == 200 and confirm_body.get("saved") is True
                    and confirm_body.get("count") == len(rows) and confirm_body.get("snapshot_date")):
                print("PASS POST /api/holdings/confirm 用 preview 回傳的 rows 原樣送回 -> 寫入成功")
            else:
                print("FAIL POST /api/holdings/confirm -> status=%s body=%s" % (status, confirm_body))
                failures.append("holdings confirm")

            # 驗證真的寫進資料庫，不是只回應成功但沒真的 INSERT。
            check_store = KBStore(data_dir)
            try:
                latest = check_store.get_holdings()
            finally:
                check_store.close()
            latest_codes = {h["code"] for h in (latest.get("holdings") or [])}
            if "9911" in latest_codes:
                print("PASS confirm 後 get_holdings() 查得到剛存入的代碼 9911")
            else:
                print("FAIL confirm 後 get_holdings() 查不到代碼 9911：%s" % latest_codes)
                failures.append("holdings confirm not persisted")
        else:
            print("FAIL 因為 preview 沒有 rows，略過 confirm 測試")
            failures.append("holdings confirm skipped")

        status, confirm_body = _post("/api/holdings/confirm", {"rows": []})
        if status == 400:
            print("PASS POST /api/holdings/confirm 空 rows -> 400")
        else:
            print("FAIL POST /api/holdings/confirm 空 rows -> status=%s（預期400）" % status)
            failures.append("holdings confirm empty rows")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()

    print()
    if failures:
        print("整體：FAIL（%d 項失敗：%s）" % (len(failures), ", ".join(failures)))
        return 1
    print("整體：PASS（全部項目通過）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
