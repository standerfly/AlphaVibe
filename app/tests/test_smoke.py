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

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_PRODUCTION_DATA_DIR = os.path.abspath(
    os.path.join(_APP_ROOT, "poc", "data"))
_PORT = 8091  # 刻意跟人工測試常用的 8090 錯開，避免撞號
_BASE = "http://127.0.0.1:%d" % _PORT


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


def _get(path: str):
    req = urllib.request.Request(_BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
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

        # 資產分頁的 4 個口袋應該已經自動種子出來（因為這是全新的隔離庫）。
        status, pockets_body = _get("/api/assets/pockets")
        pocket_count = len(pockets_body.get("pockets", [])) if pockets_body else 0
        if pocket_count == 4:
            print("PASS assets/pockets 自動種子出 4 筆")
        else:
            print("FAIL assets/pockets 預期 4 筆，實際 %d 筆" % pocket_count)
            failures.append("assets seed count mismatch")

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
