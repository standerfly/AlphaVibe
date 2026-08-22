"""app/ FastAPI 服務的煙霧測試（2026-08-22 新增）。

背景：2026-08-22 發現先前的「測試都驗證過」宣稱在 repo 裡完全查無實體
佐證（見 harness 專案 scratchpad 的 alphavibe-verify-report.md），且因為
ALPHAVIBE_DATA_DIR 沒有強制要求，測試埠一度意外寫進正式資料庫（詳見
app/deps.py::_resolve_data_dir 的教訓紀錄）。這份腳本存在的目的就是
留下真正可重跑、可查證的測試證據，不再只是口頭宣稱。

刻意不用 pytest/httpx（兩者都未安裝，app/requirements.txt 刻意只裝
fastapi/uvicorn 兩個套件）——改用標準庫 subprocess 啟動真正的
uvicorn，urllib 發請求，跟正式部署路徑一致（黑箱煙霧測試，不是
in-process TestClient 那種可能繞過中介層/生命週期邏輯的測試）。

用法：
    ALPHAVIBE_DATA_DIR=<獨立測試資料夾> python3 -m app.tests.test_smoke

安全機制：腳本啟動前會自行檢查 ALPHAVIBE_DATA_DIR 不等於正式路徑
poc/data/，避免重蹈覆轍；沒設定或設定成正式路徑會直接拒絕執行。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error


def _post(path: str, body: bytes, headers: dict = None, timeout: float = 10.0):
    req = urllib.request.Request(
        _BASE + path, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_PRODUCTION_DATA_DIR = os.path.abspath(
    os.path.join(_APP_ROOT, "poc", "data"))
_PORT = 8091  # 刻意跟人工測試常用的 8090 錯開，避免撞號
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
        print("FAIL: ALPHAVIBE_DATA_DIR 指向正式資料庫路徑（%s），"
              "拒絕執行測試——這正是 2026-08-22 事故的成因，"
              "測試腳本本身也要擋。" % _PRODUCTION_DATA_DIR)
        sys.exit(1)
    return resolved


def _get(path: str, timeout: float = 5.0):
    req = urllib.request.Request(_BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _wait_for_server(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "server process exited early with code %s" % proc.returncode)
        try:
            with urllib.request.urlopen(_BASE + "/api/healthz", timeout=1):
                return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("server did not become ready within %.1fs" % timeout)


def main() -> int:
    data_dir = _guard_data_dir()
    print("測試資料目錄（已確認非正式庫）：%s" % data_dir)

    env = dict(os.environ)
    env["ALPHAVIBE_DATA_DIR"] = data_dir
    python = os.path.join(_APP_ROOT, ".venv", "bin", "python3")
    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(_PORT)],
        cwd=_APP_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    failures = []
    try:
        _wait_for_server(proc)

        checks = [
            ("GET /api/healthz", "/api/healthz", 200),
            ("GET /api/whoami", "/api/whoami", 200),
            ("GET /api/dashboard", "/api/dashboard", 200),
            ("GET /api/holdings", "/api/holdings", 200),
            ("GET /api/screen", "/api/screen", 200),
            ("GET /api/market-scan", "/api/market-scan", 200),
            ("GET /api/assets/pockets", "/api/assets/pockets", 200),
            ("GET /api/assets/accounts", "/api/assets/accounts", 200),
            ("GET /api/assets/holdings", "/api/assets/holdings", 200),
        ]
        for label, path, expect_status in checks:
            status, body = _get(path)
            ok = status == expect_status
            print("%s %s -> %s (expect %s)" %
                  ("PASS" if ok else "FAIL", label, status, expect_status))
            if not ok:
                failures.append(label)

        # whoami 必須明確回報它連的是我們剛剛啟動時指定的測試路徑，
        # 這是「沒有默默寫錯地方」的最終確認，不只是信任 env var 有生效。
        status, whoami_body = _get("/api/whoami")
        if whoami_body and whoami_body.get("data_dir") == data_dir:
            print("PASS whoami.data_dir 對得上指定的測試路徑")
        else:
            print("FAIL whoami.data_dir 跟指定的測試路徑不一致：%r" % whoami_body)
            failures.append("whoami.data_dir mismatch")

        # 2026-08-22 教訓（見 kb_store.py 同日教訓紀錄）：KBStore 不再
        # 自動種子任何資料，這裡反過來明確驗證「不會自動生資料」，
        # 再驗證「明確呼叫 seed_asset_defaults() 才會生資料」——兩段
        # 都要驗，只驗其中一段沒辦法證明修復是正確的。
        status, pockets_body = _get("/api/assets/pockets")
        pocket_count = len(pockets_body.get("pockets", [])) if pockets_body else 0
        if pocket_count == 0:
            print("PASS assets/pockets 沒有被自動種子（修復生效）")
        else:
            print("FAIL assets/pockets 預期 0 筆（不該自動種子），實際 %d 筆"
                  % pocket_count)
            failures.append("unexpected auto-seed")

        from kb_store import KBStore  # noqa: E402
        seed_store = KBStore(data_dir)
        try:
            seed_store.seed_asset_defaults()
        finally:
            seed_store.close()
        status, pockets_body = _get("/api/assets/pockets")
        pocket_count = len(pockets_body.get("pockets", [])) if pockets_body else 0
        if pocket_count == 4:
            print("PASS 明確呼叫 seed_asset_defaults() 後正確生出 4 筆")
        else:
            print("FAIL 明確呼叫後預期 4 筆，實際 %d 筆" % pocket_count)
            failures.append("explicit seed count mismatch")

        # ---- 功能正確性比對：API 回傳是否跟直接呼叫底層共用函式一致 ----
        # 這幾支 router 的設計是「原封不動轉手底層函式的 dict，不重新
        #定義 schema」（見各 router docstring），所以「新 API 有沒有
        # 引入 bug」等同「跟直接呼叫底層函式的結果比對是否一致」——
        # 底層演算法本身（screener.py／kb_store.py）新舊共用、不重寫，
        # 不在這裡的驗證範圍內。
        import screener  # noqa: E402
        from kb_store import KBStore  # noqa: E402
        import frameworks  # noqa: E402

        test_codes = ["2330", "3008"]
        expected_screen = screener.screen_stocks(test_codes, data_dir=data_dir)
        status, actual_screen = _get("/api/screen?codes=2330,3008", timeout=30)
        # 透過 json 往返一次消除 float repr 差異（例如 5610 vs 5610.0）
        # 造成的假陽性，只比對「resolve 後的資料值」是否一致。
        norm_expected = json.loads(json.dumps(expected_screen))
        if norm_expected == actual_screen:
            print("PASS /api/screen 輸出跟直接呼叫 screener.screen_stocks() 一致")
        else:
            print("FAIL /api/screen 輸出跟底層函式不一致")
            print("  expected:", json.dumps(norm_expected)[:300])
            print("  actual  :", json.dumps(actual_screen)[:300])
            failures.append("screen output mismatch")

        fw_id = frameworks.default_framework_id()
        store = KBStore(data_dir)
        try:
            expected_scan = store.get_latest_market_scan(framework_id=fw_id)
        finally:
            store.close()
        status, actual_scan = _get("/api/market-scan?framework=%s" % fw_id, timeout=30)
        norm_expected_scan = json.loads(json.dumps(expected_scan))
        actual_scan_stripped = dict(actual_scan or {})
        actual_scan_stripped.pop("framework_id", None)  # API 多加的欄位，預期差異
        if norm_expected_scan == actual_scan_stripped:
            print("PASS /api/market-scan 輸出跟直接呼叫 get_latest_market_scan() 一致")
        else:
            print("FAIL /api/market-scan 輸出跟底層函式不一致")
            failures.append("market-scan output mismatch")

        # holdings：router 自己做 filter/搜尋/分頁，不是單純轉手，所以
        # 比對重點是「底層資料（_tracked_stock_rows）跟 API 算出來的
        # 計數/分頁是否一致」，不是整份 dict 相等。
        import report  # noqa: E402
        store2 = KBStore(data_dir)
        try:
            all_rows = report._tracked_stock_rows(store2)  # noqa: SLF001
        finally:
            store2.close()
        expected_holdings_count = sum(1 for r in all_rows if r["is_holding"])
        expected_all_total = len(all_rows)
        status, holdings_body = _get("/api/holdings")
        checks_ok = (
            holdings_body is not None
            and holdings_body.get("all_total") == expected_all_total
            and holdings_body.get("holdings_count") == expected_holdings_count
            and holdings_body.get("research_count") == expected_all_total - expected_holdings_count
        )
        if checks_ok:
            # 再比對第一頁內容跟底層資料前 N 筆一致（扣掉 API 刻意省略的 spark_html）。
            page_size = report.STOCKLIST_PAGE_SIZE
            expected_page1 = [
                {k: v for k, v in r.items() if k != "spark_html"}
                for r in all_rows[:page_size]
            ]
            norm_expected_page1 = json.loads(json.dumps(expected_page1))
            checks_ok = norm_expected_page1 == holdings_body.get("results")
        if checks_ok:
            print("PASS /api/holdings 計數與第一頁內容跟 _tracked_stock_rows() 一致")
        else:
            print("FAIL /api/holdings 跟底層資料兜不起來")
            failures.append("holdings output mismatch")

        # MCP：直接呼叫 handle_mcp_post() 跟透過 HTTP 打 /mcp，應該是
        # 完全一樣的 (status, body)——這是唯一邏輯完全共用、風險最低的
        # router，理論上該逐位元組相等。ALPHAVIBE_MCP_TOKEN 沒設定時
        # fail-open（見 mcp_http_gateway._auth_ok()），測試環境不用帶
        # Authorization header。
        import mcp_http_gateway  # noqa: E402
        mcp_request = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        ).encode("utf-8")
        expected_status, expected_ct, expected_body = mcp_http_gateway.handle_mcp_post(
            {}, mcp_request, data_dir=data_dir)
        actual_status, actual_body = _post(
            "/mcp", mcp_request, headers={"Content-Type": "application/json"})
        if expected_status == actual_status and expected_body == actual_body:
            print("PASS /mcp 輸出跟直接呼叫 handle_mcp_post() 逐位元組一致")
        else:
            print("FAIL /mcp 輸出跟 handle_mcp_post() 不一致 "
                  "(expected status=%s actual status=%s)"
                  % (expected_status, actual_status))
            failures.append("mcp output mismatch")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print("整體：FAIL（%d 項失敗：%s）" % (len(failures), ", ".join(failures)))
        return 1
    print("整體：PASS（全部項目通過）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
