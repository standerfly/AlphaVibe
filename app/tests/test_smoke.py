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
    rm -rf poc/data-test && cp -R poc/data poc/data-test
    sqlite3 poc/data-test/alphavibe.db "DELETE FROM asset_buildup_entries;
      DELETE FROM asset_buildup_plans; DELETE FROM asset_holdings;
      DELETE FROM asset_accounts; DELETE FROM asset_pockets;
      DELETE FROM sqlite_sequence WHERE name LIKE 'asset_%';"
    ALPHAVIBE_DATA_DIR=poc/data-test python3 -m app.tests.test_smoke

2026-08-22 追加：正式庫種了真實資產資料後，複製正式庫當測試底本時
「資產表清空＋sqlite_sequence 歸零」這兩步變成必要——這份測試假設
資產表從空的開始（要驗證「不會自動種子」與「種子後 id=1」），複製
正式庫過來如果不清空，會拿到已經有資料、id 也不是從 1 開始的測試庫，
上面兩項驗證都會失真。

安全機制：腳本啟動前會自行檢查 ALPHAVIBE_DATA_DIR 不等於正式路徑
poc/data/，避免重蹈覆轍；沒設定或設定成正式路徑會直接拒絕執行。
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import shutil
import tempfile
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


def _post(path: str, body: bytes, headers: dict = None, timeout: float = 10.0):
    req = urllib.request.Request(
        _BASE + path, data=body, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_or_none(raw):
    """`_post`／`_delete` 回傳的是 raw bytes（不像 `_get` 會解析），
    需要讀內容時自行解析。非 JSON（例如 204 空 body）回 None。"""
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _delete(path: str, timeout: float = 10.0):
    """Phase 5（US3，T028）新增：`DELETE /api/us-stocks/watch-conditions/{id}`
    是這個 repo 第一個真正的 DELETE 端點，`_get`／`_post` 都不適用，補一個
    對稱的極簡 helper。"""
    req = urllib.request.Request(_BASE + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

def _patch(path: str, body: bytes, timeout: float = 10.0):
    """006（T029）新增：調整重掃頻率是這個 repo 第一個 PATCH 端點。"""
    req = urllib.request.Request(_BASE + path, data=body, method="PATCH",
                                 headers={"Content-Type": "application/json"})
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


# gateway_monitor（2026-08-31 新增，STND「管家」分頁，見
# app/routers/gateway_monitor.py 檔頭 docstring 與
# ~/.claude/plans/hazy-petting-wreath.md）的內部邏輯單元測試。

# **刻意用獨立 subprocess 執行，不在這個外層腳本 import app.routers.
# gateway_monitor**——這支測試腳本開頭 docstring 明確講「刻意不用
# pytest/httpx...改用標準庫」，import gateway_monitor 會連帶 import
# fastapi/pydantic，讓外層腳本也綁死 fastapi 依賴，跟既有設計原則衝突。
# 用跟啟動 uvicorn 一樣的模式（.venv/bin/python3 -c "..."）跑一段獨立腳本，
# 外層 test_smoke.py 本身維持零外部依賴。
#
# 這裡驗證的是「不方便／不安全用真正的黑箱 HTTP 測」的部分：LOCKDOWN
# 旗標檔要讓 POST /chat、/task 直接拒絕（不能真的在正式 telegram_gateway/
# state/ 建立 LOCKDOWN 檔——那是 Telegram 側也在用的共用旗標，測試不該
# 動到正式系統的鎖定狀態）、.env 權限模式解析、gateway_state.json／
# usage_log.jsonl 的讀寫與彙總邏輯。全部用 tempfile 建的 scratch 目錄，
# 不碰任何正式檔案。唯一例外是 `_transcript_path()` 那一項刻意用今天
# 真實存在的 session_id（見任務背景知識第3點「底線變破折號」的 bug），
# 因為這是唯讀 glob 搜尋，不會寫壞任何東西。
_GATEWAY_UNIT_CHECK_SCRIPT = r"""
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from app.routers import gateway_monitor as gw

failures = []


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures.append(label)


with tempfile.TemporaryDirectory() as tmp:
    scratch = Path(tmp)
    gw._STATE_DIR = scratch
    gw._GATEWAY_STATE_PATH = scratch / "gateway_state.json"
    gw._USAGE_LOG_PATH = scratch / "usage_log.jsonl"
    gw._AUDIT_LOG_PATH = scratch / "audit_log.jsonl"
    gw._LOCKDOWN_FLAG_PATH = scratch / "LOCKDOWN"

    state = gw._load_state()
    check("空狀態有兩個已知專案捷徑 domain（general 已拿掉，見「擴充：任意命名主題」）",
          set(state["domains"].keys()) == set(gw.PROJECT_DOMAINS.keys()))

    gw._set_session_id("alphavibe", "unit-test-session-1")
    check("set/get session_id round trip",
          gw._get_session_id("alphavibe") == "unit-test-session-1")

    # ---- 任意命名主題（2026-08-31 擴充）：命名規則邊界測試。這些規則
    # 必須跟 telegram_gateway/config.py 的同名函式逐字一致。 ----
    check("normalize_domain_name 統一小寫去頭尾空白",
          gw.normalize_domain_name("  MyTopic  ") == "mytopic")
    check("is_valid_domain_name 接受已知簡單名稱", gw.is_valid_domain_name("alphavibe"))
    check("is_valid_domain_name 接受中文名稱", gw.is_valid_domain_name("股票研究"))
    check("is_valid_domain_name 拒絕空字串", gw.is_valid_domain_name("") is False)
    check("is_valid_domain_name 拒絕含空白的名稱（Telegram args[0] 斷詞安全考量）",
          gw.is_valid_domain_name("旅行 規劃") is False)
    check("is_valid_domain_name 拒絕含斜線的名稱", gw.is_valid_domain_name("not/a-domain") is False)
    check("is_valid_domain_name 接受剛好 40 字元",
          gw.is_valid_domain_name("a" * gw.MAX_DOMAIN_NAME_LEN))
    check("is_valid_domain_name 拒絕 41 字元",
          gw.is_valid_domain_name("a" * (gw.MAX_DOMAIN_NAME_LEN + 1)) is False)
    check("resolve_cwd 已知專案捷徑回傳真實路徑",
          gw.resolve_cwd("alphavibe") == gw.PROJECT_DOMAINS["alphavibe"])
    check("resolve_cwd 未知名稱 fallback 到家目錄、不拋錯（取代舊的 KeyError 查表）",
          gw.resolve_cwd("brand-new-topic") == Path.home())

    # 合法但從未見過的名稱應該被接受、_load_state() 能看到新 key——這類
    # 測試只能放在這個子行程腳本層級（直接呼叫內部函式），不能透過真正
    # 的 HTTP 端點觸發（POST /chat 一旦通過驗證就會真的呼叫 claude CLI，
    # 消耗真實訂閱額度，見本檔案檔頭 docstring）。
    gw._set_session_id("股票研究", "unit-test-session-new-topic")
    reloaded = gw._load_state()
    check("全新主題名稱第一次使用即自動建立（不需要預先存在於 PROJECT_DOMAINS）",
          "股票研究" in reloaded["domains"]
          and reloaded["domains"]["股票研究"]["session_id"] == "unit-test-session-new-topic")

    # list_conversations() 必須走訪 state 本身，不能走訪 PROJECT_DOMAINS
    # 固定字典——不修的話，任意命名的新主題永遠不會出現在這裡，直接打臉
    # 「跨管道共用記憶看得到」這個核心賣點（見「擴充：任意命名主題」章節）。
    conv = gw.list_conversations()
    conv_names = {d["name"] for d in conv["domains"]}
    check("list_conversations() 含任意命名的新主題（走訪 state 而非 PROJECT_DOMAINS）",
          {"股票研究", "alphavibe", "harness"} <= conv_names)

    gw._add_inflight("alphavibe", "sess-a", "/tmp", "測試任務")
    inflight = gw._load_state()["inflight_bg_tasks"]
    check("add_inflight 寫入一筆",
          len(inflight) == 1 and inflight[0]["claude_session_id"] == "sess-a")
    gw._clear_inflight("sess-a")
    check("clear_inflight 清空", gw._load_state()["inflight_bg_tasks"] == [])

    # ---- 背景任務完成可見性（2026-08-31 擴充）：mark_inflight_done()
    # 原地標記，不立刻清除；超過保留期才真的刪除。 ----
    gw._add_inflight("harness", "sess-bg-done", "/tmp/y", "背景測試任務")
    gw._mark_inflight_done("sess-bg-done")
    marked = gw._load_state()["inflight_bg_tasks"]
    check("mark_inflight_done() 原地標記 status=done，不清除紀錄",
          len(marked) == 1 and marked[0]["status"] == "done" and "completed_at" in marked[0])

    st_for_purge = gw._load_state()
    old_ts = (datetime.now(timezone.utc)
              - timedelta(hours=gw._COMPLETED_TASK_RETENTION_HOURS + 1)).isoformat()
    st_for_purge["inflight_bg_tasks"][0]["completed_at"] = old_ts
    gw._save_state(st_for_purge)
    check("超過保留期的已完成任務下次 _load_state() 時真的被刪除",
          gw._load_state()["inflight_bg_tasks"] == [])

    # list_tasks() 2026-08-31 拿掉舊的 known_cwds（cwd 反查 domain）邏輯，
    # 對任意命名主題也要能正確回報 domain（任意主題共用 Path.home()，
    # 用 cwd 反查會拿到錯的／拿不到 domain，必須改讀持久化的 domain 欄位）。
    gw._add_inflight("股票研究", "sess-bg-arbitrary", str(Path.home()), "任意主題背景任務")
    tasks_result = gw.list_tasks()
    check("list_tasks() 對任意命名主題的任務回傳正確 domain（不靠 cwd 反查）",
          any(t["domain"] == "股票研究" and t["claude_session_id"] == "sess-bg-arbitrary"
              for t in tasks_result["tasks"]))
    gw._clear_inflight("sess-bg-arbitrary")

    gw._append_usage_log("alphavibe", {"session_id": "s1", "total_cost_usd": 1.5,
        "usage": {"input_tokens": 10, "output_tokens": 20}}, kind="sync", channel="web")
    gw._append_usage_log("alphavibe", {"session_id": "s2", "total_cost_usd": None,
        "usage": {}}, kind="bg", channel="web")
    entries = gw._load_usage_entries()
    check("usage_log 寫入兩筆", len(entries) == 2)
    agg = gw._aggregate_usage(entries, datetime.now(timezone.utc) - timedelta(days=1))
    check("彙總總花費為 1.5", agg["total_cost_usd"] == 1.5)
    check("彙總標記 has_unknown_cost（背景任務無金額）", agg["has_unknown_cost"] is True)
    check("彙總 calls 數為 2", agg["calls"] == 2)
    since_future = datetime.now(timezone.utc) + timedelta(days=1)
    agg_future = gw._aggregate_usage(entries, since_future)
    check("since 設在未來時彙總為 0（時間篩選確實生效）", agg_future["calls"] == 0)

    env_path = scratch / "fake.env"
    gw._ENV_FILE_PATH = env_path
    env_path.write_text("CLAUDE_PERMISSION_MODE=bypassPermissions\n", encoding="utf-8")
    check("permission_args 讀到設定值",
          gw._permission_args() == ["--permission-mode", "bypassPermissions"])
    env_path.write_text("CLAUDE_PERMISSION_MODE=\n", encoding="utf-8")
    check("空值不傳旗標", gw._permission_args() == [])

    m = gw._BACKGROUNDED_RE.search("Starting background service...\nbackgrounded · a5581939\n")
    check("backgrounded regex 抓到短 id", bool(m) and m.group(1) == "a5581939")

    fake_jsonl = scratch / "fake-session.jsonl"
    fake_jsonl.write_text("\n".join([
        json.dumps({"type": "user", "timestamp": "t1", "message": {"content": "你好"}}),
        json.dumps({"type": "assistant", "timestamp": "t2", "message": {"content": [
            {"type": "text", "text": "哈囉"}]}}),
        json.dumps({"type": "assistant", "timestamp": "t3", "message": {"content": [
            {"type": "tool_use", "name": "Bash"}]}}),
        json.dumps({"type": "queue-operation", "message": {}}),
    ]), encoding="utf-8")
    messages = gw._extract_messages(fake_jsonl)
    check("只抽出有文字的 2 則訊息（純 tool_use／非 user-assistant type 被略過）",
          len(messages) == 2 and messages[0]["text"] == "你好" and messages[1]["text"] == "哈囉")

    gw._LOCKDOWN_FLAG_PATH.write_text(json.dumps({"locked_at": "t"}), encoding="utf-8")
    check("LOCKDOWN 檔案存在時 _is_locked_down() 為真", gw._is_locked_down() is True)

    async def _check_lockdown_rejects():
        rejected_chat = False
        try:
            await gw.post_chat(gw.ChatRequest(domain="alphavibe", text="hi"))
        except HTTPException as exc:
            rejected_chat = exc.status_code == 423
        rejected_task = False
        try:
            await gw.post_task(gw.TaskRequest(domain="alphavibe", description="hi"))
        except HTTPException as exc:
            rejected_task = exc.status_code == 423
        return rejected_chat, rejected_task

    rejected_chat, rejected_task = asyncio.run(_check_lockdown_rejects())
    check("鎖定時 POST /chat 回 423（未呼叫 claude CLI）", rejected_chat)
    check("鎖定時 POST /task 回 423（未呼叫 claude CLI）", rejected_task)

    gw._LOCKDOWN_FLAG_PATH.unlink()
    check("刪除旗標後 _is_locked_down() 為假", gw._is_locked_down() is False)

    # 不合法主題名稱要在呼叫 claude CLI 之前就被 400 擋下（鎖定已解除，
    # 這裡測的是命名驗證本身，不是鎖定閘門）。
    async def _check_invalid_domain_rejected():
        rejected_chat = False
        try:
            await gw.post_chat(gw.ChatRequest(domain="not/a-domain", text="hi"))
        except HTTPException as exc:
            rejected_chat = exc.status_code == 400
        rejected_task = False
        try:
            await gw.post_task(gw.TaskRequest(domain="not/a-domain", description="hi"))
        except HTTPException as exc:
            rejected_task = exc.status_code == 400
        return rejected_chat, rejected_task

    rejected_chat2, rejected_task2 = asyncio.run(_check_invalid_domain_rejected())
    check("不合法主題名稱 POST /chat 回 400（未呼叫 claude CLI）", rejected_chat2)
    check("不合法主題名稱 POST /task 回 400（未呼叫 claude CLI）", rejected_task2)

    try:
        gw.get_transcript("not/a-domain")
        transcript_invalid_rejected = False
    except HTTPException as exc:
        transcript_invalid_rejected = exc.status_code == 400
    check("get_transcript() 對不合法主題名稱回 400", transcript_invalid_rejected)

    real_path = gw._transcript_path("adbfa17c-05d3-4025-8dba-86bc37b1b758")
    check("真實 session_id 找得到逐字稿（底線變破折號的路徑，不是用猜的）",
          real_path is not None and "-Users-stander-My-project-AlphaVibe" in str(real_path))

print()
if failures:
    print("GATEWAY_UNIT: FAIL (%d 項失敗)" % len(failures))
    sys.exit(1)
print("GATEWAY_UNIT: PASS")
sys.exit(0)
"""


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
    # 2026-09-17 架構體檢 A5：app/main.py 啟動時會斷言認證有設定，沒設
    # token 又沒明確授權就拒絕啟動。這支黑箱測試本來就跑在無認證模式下
    # （測的是業務端點的輸出正確性，不是認證行為），所以明確表態——
    # 這正是這個旗標存在的用途：讓「無認證」變成需要主動宣告的選擇，
    # 而不是讀不到 token 時的靜默預設。
    env["ALPHAVIBE_ALLOW_NO_AUTH"] = "1"
    python = os.path.join(_APP_ROOT, ".venv", "bin", "python3")

    print()
    print("=== gateway_monitor 內部邏輯單元測試（獨立 scratch state，不碰"
          "正式 telegram_gateway/state/，不需要啟動 uvicorn） ===")
    gateway_unit_failures = []
    unit_result = subprocess.run(
        [python, "-c", _GATEWAY_UNIT_CHECK_SCRIPT], cwd=_APP_ROOT,
        capture_output=True, text=True, timeout=30)
    print(unit_result.stdout)
    if unit_result.returncode != 0:
        print("gateway_monitor 單元測試 stderr（最後 2000 字）：")
        print(unit_result.stderr[-2000:])
        gateway_unit_failures.append("gateway_monitor unit checks")

    # 2026-08-22 教訓：原本用 stdout=subprocess.PIPE 但從未讀取，這份
    # 測試本身後面會送 30 個併發請求，uvicorn 每個請求都印一行 log，
    # 沒人清 pipe 的話 OS pipe buffer（通常 64KB）滿了之後 child process
    # 會卡在 write() 上，實測導致這個 subprocess 直接死掉、後續請求
    # 變成 ConnectionRefused——不是併發修復本身的問題（同樣的併發測試
    # 換成用一般背景行程啟動 server 完全正常），是這支測試腳本自己的
    # subprocess 管理方式有 bug。改成導向暫存檔，不會阻塞。
    log_path = os.path.join(
        "/tmp", "alphavibe-test-smoke-server-%d.log" % os.getpid())
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(_PORT)],
        cwd=_APP_ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )

    failures = list(gateway_unit_failures)
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
            ("GET /api/us-stocks/healthz", "/api/us-stocks/healthz", 200),
            ("GET /api/us-stocks/watchlist", "/api/us-stocks/watchlist", 200),
            ("GET /api/us-stocks/trades/recent", "/api/us-stocks/trades/recent", 200),
            ("GET /api/flights/healthz", "/api/flights/healthz", 200),
            ("GET /api/flights/tracks", "/api/flights/tracks", 200),
            ("GET /api/flights/native-tracking", "/api/flights/native-tracking", 200),
            ("GET /api/photos/albums", "/api/photos/albums", 200),
            ("GET /api/photos/tags", "/api/photos/tags", 200),
            ("GET /api/photos/browse-folders", "/api/photos/browse-folders", 200),
            # gateway_monitor（2026-08-31 新增，STND「管家」分頁）：這三支
            # 讀的是 telegram_gateway/state/ 的正式共用狀態（不是這個測試
            # 專用的 poc/data-test），刻意不用 STND_GATEWAY_STATE_DIR 覆寫
            # ——都是唯讀查詢，直接對著今天真實累積的資料驗證格式正確，
            # 見下方「gateway_monitor 深度驗證」區塊的進一步斷言。
            ("GET /api/gateway/conversations", "/api/gateway/conversations", 200),
            ("GET /api/gateway/tasks", "/api/gateway/tasks", 200),
            ("GET /api/gateway/usage", "/api/gateway/usage", 200),
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

        # 2026-08-22 教訓（切換上線後又追加一次）：web/src/pages/Assets.jsx
        # 把唯一的建倉計畫 ID 寫死成 BUILDUP_PLAN_ID = 1，這個假設只有在
        # sqlite_sequence 沒被之前的污染/重跑弄跳號時才成立——PO 實際使用
        # 時就因為前兩次污染事故讓 asset_buildup_plans 的計數器跳到 2，
        # 種子資料生出來變成 id=3，前端打 /api/assets/buildup/1 變成
        # 404。這裡直接驗證種子資料生出來的 plan id 就是 1，這個假設
        # 才立得住；如果哪天又跳號，這個檢查要先炸，不要等 PO 真的用
        # 才發現。
        status, buildup_body = _get("/api/assets/buildup/1")
        if status == 200 and buildup_body and buildup_body.get("id") == 1:
            print("PASS 種子資料的建倉計畫 id=1，跟前端寫死的 BUILDUP_PLAN_ID 對得上")
        else:
            print("FAIL /api/assets/buildup/1 -> %s（前端會 404，多半是 "
                  "sqlite_sequence 跳號，檢查 poc/data*/alphavibe.db 的 "
                  "sqlite_sequence 表）" % status)
            failures.append("buildup plan id mismatch")

        # 2026-08-22 教訓：PO 回報「只有封存沒有編輯」，查證後發現後端
        # 其實原本就支援（POST 帶 id＝更新、不帶＝新增，PocketUpsert/
        # AccountUpsert 本來就這樣設計），缺的只是前端沒有編輯入口——
        # 已補上前端，這裡驗證的是後端 upsert 語意本身沒有壞：帶既有 id
        # 送出更新，總筆數不該變、id 不該變（不是新增一筆），欄位要
        # 真的被改到。
        status, pockets_before = _get("/api/assets/pockets")
        count_before = len(pockets_before.get("pockets", []))
        target_pocket = pockets_before["pockets"][0]
        update_status, update_body = _post(
            "/api/assets/pockets",
            json.dumps({
                "id": target_pocket["id"],
                "name": target_pocket["name"],
                "target_amount": target_pocket["target_amount"],
                "note": "smoke-test-edit",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        status, pockets_after = _get("/api/assets/pockets")
        count_after = len(pockets_after.get("pockets", []))
        updated = next(
            (p for p in pockets_after["pockets"] if p["id"] == target_pocket["id"]),
            None)
        if (update_status == 200 and count_after == count_before
                and updated is not None and updated.get("note") == "smoke-test-edit"):
            print("PASS 帶 id 送出更新：總筆數不變、id 不變、欄位確實更新（編輯語意正確）")
        else:
            print("FAIL 編輯（帶 id 的 upsert）行為不符預期："
                  "before=%d after=%d updated=%r" % (count_before, count_after, updated))
            failures.append("pocket update semantics")

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

        # stance/reason（2026-08-24 補回「假說清單」欄位，Q-046 遷移遺漏）：
        # 上面的整份 dict 比對已經隱含涵蓋這兩欄，但這裡額外做「有沒有真的
        # 傳出資料」的存在性檢查——避免兩邊剛好都是 None/沒有這個 key 時，
        # 相等比對仍能通過、卻沒真正驗證到欄位有內容（比照 CLAUDE.md 教訓
        # 紀錄「斷言要驗證真的有東西，不要只驗證形狀」的精神）。測試庫
        # （複製自正式庫）已知有 31 檔代碼、296 筆立場紀錄，所以第一頁
        # 10 筆裡應該至少有一筆非 None 的 stance/reason；同時確認完全沒有
        # 立場紀錄的代碼會拿到 None 而不是缺欄位或拋錯。
        results = (holdings_body or {}).get("results") or []
        has_stance_key = all("stance" in r and "reason" in r for r in results)
        has_nonnull_stance = any(r.get("stance") for r in results)
        if has_stance_key and has_nonnull_stance:
            print("PASS /api/holdings 每筆都有 stance/reason 欄位，且至少一筆非空")
        else:
            print("FAIL /api/holdings 的 stance/reason 欄位缺漏或全部是空值")
            print("  results stance/reason 樣本：",
                  json.dumps([{"code": r.get("code"), "stance": r.get("stance"),
                               "reason": r.get("reason")} for r in results[:3]],
                             ensure_ascii=False))
            failures.append("holdings stance/reason missing")

        # industry_category/theme（2026-08-24 新增，投資分頁主題集中度
        # 待辦）：跟上面 stance/reason 同一個精神——存在性＋非空值雙重
        # 檢查，不只驗證形狀。測試庫第一頁已知混有兩種代碼：8299（有
        # theme 無 industry_category）與多檔研究中代碼（有
        # industry_category 無 theme），所以兩欄各自都該至少有一筆非
        # None，同時也該至少有一筆是 None（確認查無資料時是 None 不是
        # 拋錯或缺欄位）。
        has_industry_theme_key = all(
            "industry_category" in r and "theme" in r for r in results)
        has_nonnull_industry = any(r.get("industry_category") for r in results)
        has_nonnull_theme = any(r.get("theme") for r in results)
        if has_industry_theme_key and has_nonnull_industry and has_nonnull_theme:
            print("PASS /api/holdings 每筆都有 industry_category/theme 欄位，且各至少一筆非空")
        else:
            print("FAIL /api/holdings 的 industry_category/theme 欄位缺漏或全部是空值")
            print("  results industry_category/theme 樣本：",
                  json.dumps([{"code": r.get("code"),
                               "industry_category": r.get("industry_category"),
                               "theme": r.get("theme")} for r in results[:5]],
                             ensure_ascii=False))
            failures.append("holdings industry_category/theme missing")

        # theme_concentration（2026-08-24 新增，投資分頁主題集中度待辦）：
        # 跟上面 /api/screen／/api/market-scan 同一個比對精神——直接呼叫
        # 底層 report._theme_concentration_data() 拿「正確答案」，跟 API
        # 回傳逐欄比對，不是只驗證「有回傳東西」。這裡刻意用獨立的
        # store3（而非上面已關閉的 store2）避免跟前面的 with 區塊搶
        # 連線生命週期。
        store3 = KBStore(data_dir)
        try:
            expected_theme_conc = report._theme_concentration_data(store3)  # noqa: SLF001
        finally:
            store3.close()
        actual_theme_conc = (holdings_body or {}).get("theme_concentration")
        norm_expected_theme_conc = json.loads(json.dumps(expected_theme_conc))
        if norm_expected_theme_conc == actual_theme_conc:
            print("PASS /api/holdings 的 theme_concentration 跟 "
                  "report._theme_concentration_data() 一致（%d 個主題，"
                  "total_value=%s）" % (len(expected_theme_conc["themes"]),
                                       expected_theme_conc["total_value"]))
        else:
            print("FAIL /api/holdings 的 theme_concentration 跟底層函式不一致")
            print("  expected:", json.dumps(norm_expected_theme_conc, ensure_ascii=False))
            print("  actual  :", json.dumps(actual_theme_conc, ensure_ascii=False))
            failures.append("theme_concentration mismatch")

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

        # ---- 美股獨立系統（specs/003-us-stocks Phase 3 US1，T020）----
        # 深度比對：直接在測試庫寫入交易紀錄（不透過 API），跟 API 讀取
        # 路徑逐欄比對，不只測 200（比照本檔案其餘檢查的既有精神，見
        # app/routers/us_stocks.py 檔頭 docstring）。這批寫入用的是完全
        # 獨立的 USStockStore／us_stocks.db，不會碰到上面任何台股相關
        # 檢查用到的 alphavibe.db（FR-015/016）。
        from us_stock_store import USStockStore  # noqa: E402

        us_store = USStockStore(data_dir)
        try:
            us_store.save_trade(ticker="NET", trade_date="2026-08-05",
                                 action="buy", shares=10, price=298.40)
            us_store.save_trade(ticker="NET", trade_date="2026-08-10",
                                 action="sell", shares=3, price=310.25)
            us_store.save_price_snapshot(
                ticker="NET", snapshot_date="2026-09-05", close_price=280.0)
            us_store.save_price_snapshot(
                ticker="NET", snapshot_date="2026-09-06", close_price=286.96)
            expected_us_holdings = us_store.compute_holdings("NET")
            expected_us_ledger = us_store.list_trades("NET")
            expected_us_history = us_store.price_history_with_gaps("NET")
        finally:
            us_store.close()

        status, actual_us_holdings = _get("/api/us-stocks/holdings?ticker=NET")
        if status == 200 and actual_us_holdings == expected_us_holdings:
            print("PASS /api/us-stocks/holdings 輸出跟 USStockStore.compute_holdings() 一致")
        else:
            print("FAIL /api/us-stocks/holdings 跟底層函式不一致："
                  "expected=%r actual=%r" % (expected_us_holdings, actual_us_holdings))
            failures.append("us-stocks holdings mismatch")

        status, actual_us_trades = _get("/api/us-stocks/trades?ticker=NET")
        if status == 200 and (actual_us_trades or {}).get("entries") == expected_us_ledger:
            print("PASS /api/us-stocks/trades 輸出跟 USStockStore.list_trades() 一致")
        else:
            print("FAIL /api/us-stocks/trades 跟底層函式不一致")
            failures.append("us-stocks trades mismatch")

        status, actual_us_history = _get("/api/us-stocks/price-history?ticker=NET")
        if status == 200 and actual_us_history == expected_us_history:
            print("PASS /api/us-stocks/price-history 輸出跟 "
                  "USStockStore.price_history_with_gaps() 一致")
        else:
            print("FAIL /api/us-stocks/price-history 跟底層函式不一致："
                  "expected=%r actual=%r" % (expected_us_history, actual_us_history))
            failures.append("us-stocks price-history mismatch")

        status, us_watchlist_body = _get("/api/us-stocks/watchlist")
        us_watchlist_row = next(
            (r for r in (us_watchlist_body or {}).get("watchlist", [])
             if r["ticker"] == "NET"), None)
        if (status == 200 and us_watchlist_row is not None
                and us_watchlist_row["shares_held"] == expected_us_holdings["shares_held"]
                and us_watchlist_row["avg_cost"] == expected_us_holdings["avg_cost"]
                and us_watchlist_row["current_price"] == 286.96):
            print("PASS /api/us-stocks/watchlist 含 NET，持股/現價跟底層資料一致")
        else:
            print("FAIL /api/us-stocks/watchlist 跟底層資料兜不起來：%r" % us_watchlist_row)
            failures.append("us-stocks watchlist mismatch")

        # /api/us-stocks/healthz 的 db_path 必須是獨立的 us_stocks.db，
        # 不是 alphavibe.db——這是 FR-015/016「完全獨立」在執行期的最低
        # 健檢，完整驗證見 quickstart.md「部署後驗收重點」（Phase 6 T034）。
        status, us_healthz = _get("/api/us-stocks/healthz")
        if status == 200 and (us_healthz or {}).get("db_path", "").endswith("us_stocks.db"):
            print("PASS /api/us-stocks/healthz 確認查的是獨立的 us_stocks.db")
        else:
            print("FAIL /api/us-stocks/healthz db_path 不是預期的 us_stocks.db：%r" % us_healthz)
            failures.append("us-stocks db isolation check")

        # POST /api/us-stocks/trades/confirm（T017 匯入核對確認畫面用）：
        # 送出既有紀錄的修正值，確認 store.update_trade() 真的落庫。
        trade_id = expected_us_ledger[0]["id"]
        confirm_status, confirm_raw = _post(
            "/api/us-stocks/trades/confirm",
            json.dumps({"trades": [{
                "id": trade_id, "ticker": "NET", "trade_date": "2026-08-05",
                "action": "buy", "shares": 12, "price": 300.0,
            }]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        confirm_body = json.loads(confirm_raw.decode("utf-8")) if confirm_raw else {}
        us_store2 = USStockStore(data_dir)
        try:
            updated_trade = us_store2.get_trade(trade_id)
        finally:
            us_store2.close()
        if (confirm_status == 200 and confirm_body.get("errors") == []
                and updated_trade is not None
                and updated_trade["shares"] == 12 and updated_trade["price"] == 300.0):
            print("PASS /api/us-stocks/trades/confirm 正確更新既有交易紀錄")
        else:
            print("FAIL /api/us-stocks/trades/confirm 未正確更新："
                  "status=%s body=%r updated=%r"
                  % (confirm_status, confirm_body, updated_trade))
            failures.append("us-stocks confirm mismatch")

        # ---- 美股「投資立場」（specs/003-us-stocks Phase 4 US2，T022）----
        # 深度比對：直接在測試庫寫入立場（含多段落 full_note，模擬真實
        # 研究筆記長度），跟 API 讀取路徑逐欄比對，特別驗證 full_note
        # 沒有被任何一層（router/序列化）截斷（FR-009）。
        us_full_note = (
            "# NET 研究筆記（煙霧測試用）\n\n"
            "## 一、核心結論\n\n第一段落內容，測試多行文字完整保留。\n\n"
            "## 二、財報數字\n\n| 指標 | 數值 |\n|---|---|\n| 營收 | $696.1M |\n\n"
            "## 三、風險點\n\n- 風險一\n- 風險二\n\n"
            "> 這是一段引用文字。\n"
        )
        us_store3 = USStockStore(data_dir)
        try:
            us_store3.save_stance(
                ticker="NET", direction="bullish", summary="偏多．等回檔",
                full_note=us_full_note, bear_price=200, bull_price=330)
            expected_us_stance = us_store3.get_latest_stance("NET")
        finally:
            us_store3.close()

        status, actual_us_stance_body = _get("/api/us-stocks/stance?ticker=NET")
        actual_us_stance = (actual_us_stance_body or {}).get("stance")
        if (status == 200 and actual_us_stance == expected_us_stance
                and actual_us_stance is not None
                and actual_us_stance["full_note"] == us_full_note
                and len(actual_us_stance["full_note"]) == len(us_full_note)):
            print("PASS /api/us-stocks/stance 輸出跟 USStockStore.get_latest_stance() "
                  "一致，full_note 完整無截斷")
        else:
            print("FAIL /api/us-stocks/stance 跟底層函式不一致或 full_note 被截斷："
                  "expected=%r actual=%r" % (expected_us_stance, actual_us_stance))
            failures.append("us-stocks stance mismatch")

        # ---- 美股「關注條件」（specs/003-us-stocks Phase 5 US3，T028）----
        # 深度比對：POST 新增 → GET 查詢比對底層 store 輸出 → DELETE 刪除
        # → 確認真的從底層消失。同時驗證 watchlist 在有監控條件之後帶出
        # watch_status（先前 T020 那次查詢 NET 時還沒有任何監控條件，
        # 所以那裡看不到這個欄位有值，這裡補上完整驗證）。
        create_status, create_raw = _post(
            "/api/us-stocks/watch-conditions",
            json.dumps({
                "ticker": "NET", "metric_type": "price",
                "comparator": "lt", "threshold": 250,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        created_condition = json.loads(create_raw.decode("utf-8")) if create_raw else {}
        us_store4 = USStockStore(data_dir)
        try:
            expected_conditions = us_store4.list_watch_conditions_with_stale("NET")
        finally:
            us_store4.close()

        list_status, list_body = _get("/api/us-stocks/watch-conditions?ticker=NET")
        if (create_status == 200 and created_condition.get("status") == "insufficient_data"
                and list_status == 200
                and (list_body or {}).get("conditions") == expected_conditions):
            print("PASS /api/us-stocks/watch-conditions 新增/查詢輸出跟 "
                  "USStockStore.list_watch_conditions_with_stale() 一致")
        else:
            print("FAIL /api/us-stocks/watch-conditions 新增/查詢跟底層函式不一致："
                  "create=%r list=%r expected=%r"
                  % (created_condition, list_body, expected_conditions))
            failures.append("us-stocks watch-conditions crud mismatch")

        watchlist_status2, watchlist_body2 = _get("/api/us-stocks/watchlist")
        watchlist_row2 = next(
            (r for r in (watchlist_body2 or {}).get("watchlist", [])
             if r["ticker"] == "NET"), None)
        if (watchlist_status2 == 200 and watchlist_row2 is not None
                and watchlist_row2.get("watch_status") == "insufficient_data"
                and watchlist_row2.get("stance_direction") == "bullish"):
            print("PASS /api/us-stocks/watchlist 帶出 watch_status／"
                  "stance_direction（T030 完整版 landing 頁欄位）")
        else:
            print("FAIL /api/us-stocks/watchlist 缺少或錯誤的 watch_status/"
                  "stance_direction：%r" % watchlist_row2)
            failures.append("us-stocks watchlist watch_status mismatch")

        condition_id = created_condition.get("id")
        delete_status, _ = _delete("/api/us-stocks/watch-conditions/%s" % condition_id)
        us_store5 = USStockStore(data_dir)
        try:
            deleted_check = us_store5.get_watch_condition(condition_id)
        finally:
            us_store5.close()
        if delete_status == 200 and deleted_check is None:
            print("PASS DELETE /api/us-stocks/watch-conditions/{id} 真的從底層刪除")
        else:
            print("FAIL DELETE /api/us-stocks/watch-conditions/{id} 未正確刪除："
                  "status=%s remaining=%r" % (delete_status, deleted_check))
            failures.append("us-stocks watch-conditions delete mismatch")

        delete_missing_status, _ = _delete("/api/us-stocks/watch-conditions/999999")
        if delete_missing_status == 404:
            print("PASS DELETE 不存在的監控條件回 404")
        else:
            print("FAIL DELETE 不存在的監控條件應回 404，實際：%s" % delete_missing_status)
            failures.append("us-stocks watch-conditions delete-missing mismatch")

        # 相簿分頁（specs/004-photos-albums-search，User Story 1）深度
        # 驗證：匯入去重、相簿/標籤/評分整理、刪除只動 db 不動磁碟——
        # 不只驗證 HTTP 200，比對底層檔案系統與資料庫的實際狀態（比照
        # 本檔案一貫的深度比對慣例，而非淺層檢查）。
        _TINY_JPEG_A = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYW"
            "GDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/"
            "2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QA"
            "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
            "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
            "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
            "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
            "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
            "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
            "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
            "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
            "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU"
            "1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDEooorjO8/"
            "/9k="
        )
        _TINY_JPEG_B = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYW"
            "GDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/"
            "2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QA"
            "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
            "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
            "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
            "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
            "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
            "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
            "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
            "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
            "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU"
            "1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwB1FFFch8uf"
            "/9k="
        )
        photo_src_dir = tempfile.mkdtemp(prefix="alphavibe-smoke-photos-src-")
        try:
            with open(os.path.join(photo_src_dir, "a.jpg"), "wb") as fh:
                fh.write(_TINY_JPEG_A)
            with open(os.path.join(photo_src_dir, "b.jpg"), "wb") as fh:
                fh.write(_TINY_JPEG_B)

            scan_status, scan_raw = _post(
                "/api/photos/import/scan",
                json.dumps({"source_path": photo_src_dir,
                            "storage_location": "internal"}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            scan_body = json.loads(scan_raw.decode("utf-8")) if scan_raw else {}
            if scan_status == 200 and scan_body.get("new_count") == 2 \
                    and scan_body.get("duplicate_count") == 0:
                print("PASS photos/import/scan 找到 2 張新照片、0 張重複")
            else:
                print("FAIL photos/import/scan -> %s %r" % (scan_status, scan_body))
                failures.append("photos import scan mismatch")

            commit_status, commit_raw = _post(
                "/api/photos/import/commit",
                json.dumps({"scan_token": scan_body.get("scan_token")}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            commit_body = json.loads(commit_raw.decode("utf-8")) if commit_raw else {}
            job_id = commit_body.get("job_id") if commit_status == 200 else None
            if commit_status == 200 and job_id:
                print("PASS photos/import/commit 已啟動背景任務")
            else:
                print("FAIL photos/import/commit -> %s %r" % (commit_status, commit_body))
                failures.append("photos import commit failed")

            imported_ids = []
            if job_id:
                deadline = time.time() + 10
                job_body = {}
                while time.time() < deadline:
                    job_status, job_body = _get("/api/photos/import/jobs/%s" % job_id)
                    if job_body.get("status") in ("completed", "failed"):
                        break
                    time.sleep(0.2)
                if job_body.get("status") == "completed" \
                        and job_body.get("imported_count") == 2 \
                        and job_body.get("failed") == []:
                    print("PASS 背景匯入任務完成，2 張全部成功、0 張失敗")
                    imported_ids = job_body.get("imported_photo_ids", [])
                else:
                    print("FAIL 背景匯入任務未如預期完成：%r" % job_body)
                    failures.append("photos import job did not complete as expected")

            if len(imported_ids) == 2:
                thumb_req = urllib.request.Request(
                    _BASE + "/api/photos/thumbnail/%d" % imported_ids[0])
                try:
                    with urllib.request.urlopen(thumb_req, timeout=5) as resp:
                        thumb_status = resp.status
                        thumb_bytes = resp.read()
                except urllib.error.HTTPError as exc:
                    thumb_status, thumb_bytes = exc.code, b""
                if thumb_status == 200 and len(thumb_bytes) > 0:
                    print("PASS GET /api/photos/thumbnail/{id} 回傳真正的縮圖位元組（%d bytes）"
                          % len(thumb_bytes))
                else:
                    print("FAIL GET /api/photos/thumbnail/{id} -> %s（%d bytes）"
                          % (thumb_status, len(thumb_bytes)))
                    failures.append("photos thumbnail endpoint mismatch")

                photo1_status, photo1_body = _get("/api/photos/photos/%d" % imported_ids[0])
                if (photo1_status == 200
                        and os.path.exists(photo1_body.get("storage_path", ""))
                        and os.path.exists(photo1_body.get("thumbnail_path", ""))
                        and photo1_body.get("metadata_sync_status") == "pending"):
                    print("PASS 匯入照片的原始檔＋縮圖真的落在磁碟上，"
                          "metadata_sync_status 預設 pending")
                else:
                    print("FAIL 照片詳情或磁碟檔案不符預期：%r" % photo1_body)
                    failures.append("photos detail/disk file mismatch")

                album_status, album_raw = _post(
                    "/api/photos/albums",
                    json.dumps({"title": "smoke-test-album"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                album_body = json.loads(album_raw.decode("utf-8")) if album_raw else {}
                album_id = album_body.get("id") if album_status == 200 else None

                batch_status, batch_raw = _post(
                    "/api/photos/photos/batch",
                    json.dumps({
                        "photo_ids": imported_ids, "add_album_id": album_id,
                        "add_tags": ["夕陽", "京都"], "set_rating": 4,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                batch_body = json.loads(batch_raw.decode("utf-8")) if batch_raw else {}
                if batch_status == 200 and batch_body.get("updated") == imported_ids:
                    print("PASS 批次指派相簿/標籤/評分成功")
                else:
                    print("FAIL 批次指派失敗：%s %r" % (batch_status, batch_body))
                    failures.append("photos batch update mismatch")

                # User Story 3：標籤/評分中繼資料同步（背景任務把 db
                # 端的標籤/評分寫回照片檔案本身的 XMP/IPTC，見
                # photo_metadata_sync.py）。batch 呼叫已經觸發背景寫回，
                # 這裡輪詢確認狀態真的轉為 synced，並用 exiftool 直接
                # 讀檔案確認「真的寫進去了」，不只是信任 API 回應。
                sync_deadline = time.time() + 10
                synced_photo = {}
                while time.time() < sync_deadline:
                    _, synced_photo = _get("/api/photos/photos/%d" % imported_ids[0])
                    if synced_photo.get("metadata_sync_status") in ("synced", "failed"):
                        break
                    time.sleep(0.3)
                if synced_photo.get("metadata_sync_status") == "synced":
                    print("PASS 標籤/評分背景寫回完成，狀態轉為 synced")
                else:
                    print("FAIL 中繼資料同步狀態未如預期轉為 synced：%r" % synced_photo)
                    failures.append("photos metadata sync status mismatch")

                exif_check = subprocess.run(
                    ["exiftool", "-j", "-Rating", "-Keywords", "-Subject",
                     synced_photo.get("storage_path", "")],
                    capture_output=True, timeout=15)
                exif_json = json.loads(exif_check.stdout.decode("utf-8") or "[{}]")[0]
                if (exif_json.get("Rating") == 4
                        and set(exif_json.get("Keywords", []) or []) == {"夕陽", "京都"}):
                    print("PASS exiftool 直接讀檔案確認標籤/評分真的寫進去了"
                          "（不只是 db 端的宣稱）")
                else:
                    print("FAIL 檔案本身的中繼資料跟預期不符：%r" % exif_json)
                    failures.append("photos file metadata content mismatch")

                resync_status, resync_raw = _post(
                    "/api/photos/photos/%d/resync" % imported_ids[0], b"")
                resync_body = json.loads(resync_raw.decode("utf-8")) if resync_raw else {}
                if resync_status == 200 and resync_body.get("status") == "pending":
                    print("PASS 手動重新同步端點回應正確")
                else:
                    print("FAIL 手動重新同步端點回應不符：%s %r" % (resync_status, resync_body))
                    failures.append("photos resync endpoint mismatch")

                album_photos_status, album_photos_body = _get(
                    "/api/photos/albums/%d/photos" % album_id)
                album_photo_ids = {p["id"] for p in album_photos_body.get("photos", [])} \
                    if album_photos_status == 200 else set()
                if album_photo_ids == set(imported_ids):
                    print("PASS 相簿內縮圖牆正確顯示這 2 張照片")
                else:
                    print("FAIL 相簿內容不符：%r" % album_photos_body)
                    failures.append("photos album contents mismatch")

                tags_status, tags_body = _get("/api/photos/tags?q=%E5%A4%95")  # 「夕」
                if tags_status == 200 and "夕陽" in tags_body.get("tags", []):
                    print("PASS 標籤自動完成能查到剛加的「夕陽」")
                else:
                    print("FAIL 標籤自動完成沒查到預期標籤：%r" % tags_body)
                    failures.append("photos tag suggest mismatch")

                # User Story 2：跨相簿全域搜尋（不含 storage_path 存在性
                # 檢查——search_photos() 只讀資料庫欄位，見 FR-010）。
                search_status, search_body = _get(
                    "/api/photos/search?tags=%E5%A4%95%E9%99%BD")  # tags=夕陽
                search_ids = {p["id"] for p in search_body.get("photos", [])} \
                    if search_status == 200 else set()
                if search_status == 200 and search_ids == set(imported_ids):
                    print("PASS 全域搜尋依標籤「夕陽」找到剛匯入的 2 張照片")
                else:
                    print("FAIL 全域搜尋標籤結果不符：status=%s %r" % (search_status, search_body))
                    failures.append("photos search by tag mismatch")

                no_match_status, no_match_body = _get(
                    "/api/photos/search?tags=%E4%B8%8D%E5%AD%98%E5%9C%A8")  # tags=不存在
                if no_match_status == 200 and no_match_body.get("photos") == []:
                    print("PASS 全域搜尋不存在的標籤正確回傳空結果")
                else:
                    print("FAIL 搜尋不存在的標籤應回空結果：%r" % no_match_body)
                    failures.append("photos search empty-result mismatch")

                facets_status, facets_body = _get("/api/photos/search/facets")
                if facets_status == 200 and "camera_models" in facets_body \
                        and "lenses" in facets_body:
                    print("PASS 搜尋 facets 端點回傳正確結構")
                else:
                    print("FAIL 搜尋 facets 端點結構不符：%r" % facets_body)
                    failures.append("photos search facets mismatch")

                first_photo_path = imported_ids[0]
                first_storage_path = photo1_body.get("storage_path")
                delete_status, delete_body = _delete(
                    "/api/photos/photos/%d" % first_photo_path)
                still_in_album_status, still_in_album_body = _get(
                    "/api/photos/albums/%d/photos" % album_id)
                remaining_ids = {p["id"] for p in still_in_album_body.get("photos", [])}
                if (delete_status == 200
                        and first_photo_path not in remaining_ids
                        and first_storage_path and os.path.exists(first_storage_path)):
                    print("PASS 刪除照片：從相簿消失，但磁碟原始檔仍存在"
                          "（FR-011：僅刪 db 不刪檔案）")
                else:
                    print("FAIL 刪除照片行為不符 FR-011：status=%s remaining=%r "
                          "file_exists=%s" % (
                              delete_status, remaining_ids,
                              os.path.exists(first_storage_path or "")))
                    failures.append("photos delete-keeps-file mismatch")
        finally:
            shutil.rmtree(photo_src_dir, ignore_errors=True)

        # ---- 相簿「原地索引」模式 + 搬家偵測（2026-09-25 新增，見
        # poc/kb-mcp/photo_importer.py scan_folder()/commit_import()/
        # heal_moved_paths() docstring）：不複製檔案、直接對使用者原始
        # 資料夾建立索引，搬移後重新掃描要能自動更新 storage_path。
        # 用跟上面內容不同的第三張 fixture，避免跟上面已匯入的 A/B 撞
        # hash 被誤判成重複。
        _TINY_JPEG_C = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYW"
            "GDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/"
            "2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QA"
            "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
            "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
            "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
            "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
            "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
            "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
            "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRom"
            "JygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
            "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU"
            "1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooor2DxT/"
            "2Q=="
        )
        ref_src_dir = tempfile.mkdtemp(prefix="alphavibe-smoke-photos-ref-")
        ref_new_dir = tempfile.mkdtemp(prefix="alphavibe-smoke-photos-ref-moved-")
        try:
            ref_original_path = os.path.join(ref_src_dir, "c.jpg")
            with open(ref_original_path, "wb") as fh:
                fh.write(_TINY_JPEG_C)

            ref_scan_status, ref_scan_raw = _post(
                "/api/photos/import/scan",
                json.dumps({"source_path": ref_src_dir,
                            "storage_location": "reference"}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            ref_scan_body = json.loads(ref_scan_raw.decode("utf-8")) if ref_scan_raw else {}
            if ref_scan_status == 200 and ref_scan_body.get("new_count") == 1:
                print("PASS reference 模式 scan 找到 1 張新照片")
            else:
                print("FAIL reference 模式 scan -> %s %r" % (ref_scan_status, ref_scan_body))
                failures.append("photos reference scan mismatch")

            ref_commit_status, ref_commit_raw = _post(
                "/api/photos/import/commit",
                json.dumps({"scan_token": ref_scan_body.get("scan_token")}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            ref_commit_body = json.loads(ref_commit_raw.decode("utf-8")) if ref_commit_raw else {}
            ref_job_id = ref_commit_body.get("job_id") if ref_commit_status == 200 else None

            ref_photo_id = None
            if ref_job_id:
                deadline = time.time() + 10
                ref_job_body = {}
                while time.time() < deadline:
                    _, ref_job_body = _get("/api/photos/import/jobs/%s" % ref_job_id)
                    if ref_job_body.get("status") in ("completed", "failed"):
                        break
                    time.sleep(0.2)
                ref_ids = ref_job_body.get("imported_photo_ids", [])
                if ref_job_body.get("status") == "completed" and len(ref_ids) == 1:
                    ref_photo_id = ref_ids[0]
                    print("PASS reference 模式背景匯入完成，1 張成功")
                else:
                    print("FAIL reference 模式匯入任務未如預期完成：%r" % ref_job_body)
                    failures.append("photos reference import job mismatch")

            if ref_photo_id is not None:
                _, ref_photo_body = _get("/api/photos/photos/%d" % ref_photo_id)
                # 核心行為：storage_path 就是原始檔案的路徑（沒有被複製走），
                # 且來源資料夾裡除了那張原始照片沒有多出任何檔案。
                if (ref_photo_body.get("storage_path") == ref_original_path
                        and os.listdir(ref_src_dir) == ["c.jpg"]):
                    print("PASS reference 模式沒有複製檔案，storage_path 指向原始位置")
                else:
                    print("FAIL reference 模式應該原地索引不複製：%r（來源資料夾內容 %r）"
                          % (ref_photo_body.get("storage_path"), os.listdir(ref_src_dir)))
                    failures.append("photos reference no-copy mismatch")

                # 搬家偵測：在 STND 之外把檔案搬到新資料夾，重新掃描新位置
                # 應該偵測到「搬家」而不是當成新照片或普通重複。
                ref_new_path = os.path.join(ref_new_dir, "c.jpg")
                shutil.move(ref_original_path, ref_new_path)

                moved_scan_status, moved_scan_raw = _post(
                    "/api/photos/import/scan",
                    json.dumps({"source_path": ref_new_dir,
                                "storage_location": "reference"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                moved_scan_body = json.loads(moved_scan_raw.decode("utf-8")) if moved_scan_raw else {}
                if (moved_scan_status == 200 and moved_scan_body.get("moved_count") == 1
                        and moved_scan_body.get("new_count") == 0):
                    print("PASS 搬家後重新掃描正確偵測到 1 筆搬家（不是新照片/重複）")
                else:
                    print("FAIL 搬家偵測結果不符：%s %r" % (moved_scan_status, moved_scan_body))
                    failures.append("photos move-detection scan mismatch")

                moved_commit_status, moved_commit_raw = _post(
                    "/api/photos/import/commit",
                    json.dumps({"scan_token": moved_scan_body.get("scan_token")}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
                moved_commit_body = (
                    json.loads(moved_commit_raw.decode("utf-8")) if moved_commit_raw else {})
                moved_job_id = (
                    moved_commit_body.get("job_id") if moved_commit_status == 200 else None)

                if moved_job_id:
                    deadline = time.time() + 10
                    moved_job_body = {}
                    while time.time() < deadline:
                        _, moved_job_body = _get("/api/photos/import/jobs/%s" % moved_job_id)
                        if moved_job_body.get("status") in ("completed", "failed"):
                            break
                        time.sleep(0.2)
                    if (moved_job_body.get("status") == "completed"
                            and moved_job_body.get("healed_count") == 1
                            and moved_job_body.get("imported_count") == 0):
                        print("PASS 搬家路徑更新（heal）背景任務完成，healed_count=1")
                    else:
                        print("FAIL 搬家路徑更新任務未如預期完成：%r" % moved_job_body)
                        failures.append("photos move-heal job mismatch")

                _, ref_photo_after_move = _get("/api/photos/photos/%d" % ref_photo_id)
                if ref_photo_after_move.get("storage_path") == ref_new_path:
                    print("PASS 搬家後 storage_path 已更新為新位置（同一筆紀錄，不是新增）")
                else:
                    print("FAIL 搬家後 storage_path 未正確更新：%r"
                          % ref_photo_after_move.get("storage_path"))
                    failures.append("photos move-heal storage_path mismatch")
        finally:
            shutil.rmtree(ref_src_dir, ignore_errors=True)
            shutil.rmtree(ref_new_dir, ignore_errors=True)

        # ---- gateway_monitor：對著真實 telegram_gateway/state/ 資料的
        # 深度驗證（2026-08-31 新增，STND「管家」分頁）。跟上面幾組
        # router 不同，這裡刻意不比對「底層函式」（沒有底層函式，資料
        # 來源就是共用狀態檔本身），改成直接讀同一份 gateway_state.json/
        # usage_log.jsonl 檔案內容，逐欄比對 API 回應是否一致——這是這
        # 支 router 語境下等價的「跟真相source比對」。 ----
        gw_state_path = os.path.join(
            "/Users/stander/My_project/AI/telegram_gateway/state", "gateway_state.json")
        with open(gw_state_path, encoding="utf-8") as f:
            gw_state_on_disk = json.load(f)

        status, conv_body = _get("/api/gateway/conversations")
        expected_domains = gw_state_on_disk.get("domains", {})
        actual_by_name = {d["name"]: d for d in conv_body.get("domains", [])}
        # 2026-08-31「擴充：任意命名主題」：domain 集合不再固定三個，改跟
        # gateway_state.json 實際內容完全相等比對——比單純放寬成 subset
        # 更嚴謹，能同時抓「少報」（list_conversations() 又退化成走訪
        # PROJECT_DOMAINS 固定字典）與「多報」。
        conv_ok = (
            status == 200
            and set(actual_by_name.keys()) == set(expected_domains.keys())
            and all(
                actual_by_name[name]["session_id"] == info.get("session_id")
                and actual_by_name[name]["last_active"] == info.get("last_active")
                for name, info in expected_domains.items()
                if name in actual_by_name
            )
        )
        if conv_ok:
            print("PASS /api/gateway/conversations 跟 gateway_state.json 內容逐欄一致（真實資料）")
        else:
            print("FAIL /api/gateway/conversations 跟 gateway_state.json 不一致")
            print("  expected:", json.dumps(expected_domains, ensure_ascii=False))
            print("  actual  :", json.dumps(actual_by_name, ensure_ascii=False))
            failures.append("gateway conversations mismatch")

        # transcript：驗證「底線變破折號」那個真實 bug 案例（任務背景
        # 知識第3點）——alphavibe domain 的 session 逐字稿實際存在
        # ~/.claude/projects/-Users-stander-My-project-AlphaVibe/ 底下
        # （AlphaVibe 中的 _ 變成 -），如果 _transcript_path() 又退化成
        # 用猜的（把 cwd 的 / 換成 -，但漏掉 _ 也要換），這裡會直接找不到
        # 逐字稿、回 404，測試會抓到。
        status, transcript_body = _get("/api/gateway/conversations/alphavibe/transcript")
        transcript_ok = (
            status == 200
            and transcript_body is not None
            and "-Users-stander-My-project-AlphaVibe" in transcript_body.get("transcript_path", "")
            and len(transcript_body.get("messages", [])) > 0
        )
        if transcript_ok:
            print("PASS /api/gateway/conversations/alphavibe/transcript 找到真實逐字稿"
                  "（%d 則訊息，路徑含底線變破折號的真實目錄名稱）"
                  % len(transcript_body.get("messages", [])))
        else:
            print("FAIL transcript 端點沒有正確找到底線變破折號路徑下的逐字稿：%r" % transcript_body)
            failures.append("gateway transcript underscore-dash lookup")

        status, harness_transcript = _get("/api/gateway/conversations/harness/transcript")
        if status == 404:
            print("PASS harness domain 目前無 session_id 時 transcript 端點正確回 404")
        else:
            print("FAIL harness domain 應回 404，實際 %s" % status)
            failures.append("gateway transcript harness should 404")

        # 2026-08-31「擴充：任意命名主題」後，"not-a-domain" 其實是個合法
        # 名稱（不含空白／斜線）——這裡測的不再是「未知 domain 被拒絕」，
        # 而是「合法但從未使用過的名稱，沒有 session_id 時回 404」，跟
        # harness 那個案例是同一種情況。
        status, unknown_transcript = _get("/api/gateway/conversations/not-a-domain/transcript")
        if status == 404:
            print("PASS 從未使用過的合法主題名稱，transcript 請求正確回 404（無 session_id）")
        else:
            print("FAIL 從未使用過的主題應回 404，實際 %s" % status)
            failures.append("gateway transcript unknown domain should 404")

        # POST /chat、/task 的 domain 驗證（400，發生在真的呼叫 claude CLI
        # 之前，安全，不會觸發真實訂閱用量或卡住）——真正呼叫 claude CLI
        # 的端對端驗證另外用 1 次真實請求手動驗證過（見任務回報，不放進
        # 這支可重跑的自動化測試，避免每次跑測試都消耗真實訂閱額度）。
        # 2026-08-31 教訓：舊的 fixture 值 "not-a-domain" 在新規則下其實
        # 是合法名稱（見上面 transcript 測試），如果沿用會通過驗證、真的
        # 呼叫 claude CLI——改用含斜線的 "not/a-domain"，一定會被
        # is_valid_domain_name() 擋下。
        chat_status, chat_body = _post(
            "/api/gateway/chat",
            json.dumps({"domain": "not/a-domain", "text": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        task_status, task_body = _post(
            "/api/gateway/task",
            json.dumps({"domain": "not/a-domain", "description": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        if chat_status == 400 and task_status == 400:
            print("PASS POST /api/gateway/chat、/api/gateway/task 對不合法主題名稱都正確回 400（未呼叫 claude CLI）")
        else:
            print("FAIL domain 驗證沒有正確擋下：chat=%s task=%s" % (chat_status, task_status))
            failures.append("gateway chat/task domain validation")

        # usage：cross-check API 彙總跟直接解析 usage_log.jsonl 加總結果一致
        usage_log_path = os.path.join(
            "/Users/stander/My_project/AI/telegram_gateway/state", "usage_log.jsonl")
        with open(usage_log_path, encoding="utf-8") as f:
            usage_lines = [json.loads(line) for line in f if line.strip()]
        today_start = datetime.now(timezone.utc).astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        expected_today_cost = round(sum(
            e.get("total_cost_usd") or 0.0 for e in usage_lines
            if e.get("timestamp") and datetime.fromisoformat(e["timestamp"]) >= today_start
        ), 4)
        status, usage_body = _get("/api/gateway/usage")
        actual_today_cost = (usage_body or {}).get("today", {}).get("total_cost_usd")
        if status == 200 and actual_today_cost == expected_today_cost:
            print("PASS /api/gateway/usage 今日花費加總跟直接解析 usage_log.jsonl 一致（%s）" % actual_today_cost)
        else:
            print("FAIL /api/gateway/usage 今日花費跟手動加總不一致：expected=%s actual=%s"
                  % (expected_today_cost, actual_today_cost))
            failures.append("gateway usage aggregation mismatch")

        # ---- 機票分頁（specs/005-flight-scan-page，T026）----
        # 深度檢查而非只看 200：建立→列出→觸發→查詢→刪除跑完整流程，
        # 並**把 API 回報的組合數跟底層 expand_track() 的輸出對照**。
        # 只檢查狀態碼的話，枚舉邏輯整個壞掉（例如回傳空清單）也會通過。
        flight_track_id = None
        # 先把查詢配額佔滿，讓觸發掃描必定回 queued 而不真的啟動背景查價。
        # 否則這份測試會連上外部查價服務、消耗真實配額，且結果隨當下剩餘
        # 額度而變——測試必須是確定性的，不能依賴外部服務狀態。
        try:
            sys.path.insert(0, os.path.join(_APP_ROOT, "poc", "kb-mcp"))
            import flight_search as _fsearch
            _fsearch.record_browser_usage(
                os.environ["ALPHAVIBE_DATA_DIR"],
                _fsearch.HOURLY_BROWSER_LIMIT)
        except Exception as exc:
            print("WARN 無法預先佔滿查詢配額（%s），掃描觸發可能連上外部服務" % exc)
        try:
            created_status, created = _post(
                "/api/flights/tracks",
                json.dumps({
                    "destination": "PRG", "outstations": ["NRT", "OKA"],
                    "window_start": "2027-04", "window_end": "2027-05",
                    "trip_days_min": 10, "trip_days_max": 14,
                    "samples_per_month": 2,
                    "lead_strategy": "m3", "trail_strategy": "m1",
                }).encode("utf-8"),
                {"Content-Type": "application/json"})
            created = _json_or_none(created)
            if created_status == 201 and created and created.get("id"):
                flight_track_id = created["id"]
                print("PASS /api/flights/tracks 建立條件（id=%s）" % flight_track_id)
            else:
                print("FAIL /api/flights/tracks 建立條件：status=%s body=%s"
                      % (created_status, created))
                failures.append("flights create")

            if flight_track_id:
                # 與底層枚舉比對：API 的 progress.total 必須等於
                # flight_scan_service.expand_track() 算出的組合數
                sys.path.insert(0, os.path.join(_APP_ROOT, "poc", "kb-mcp"))
                import flight_scan_service as _svc
                import flight_store as _fstore
                _st = _fstore.FlightStore(os.environ["ALPHAVIBE_DATA_DIR"])
                try:
                    _track = _st.get_track(flight_track_id)
                    _itins, _skipped = _svc.expand_track(_track)
                    expected_total = len(_itins)
                finally:
                    _st.close()

                status, body = _get("/api/flights/tracks")
                api_total = None
                for t in (body or {}).get("tracks", []):
                    if t.get("id") == flight_track_id:
                        api_total = (t.get("progress") or {}).get("total")
                if status == 200 and api_total == expected_total and expected_total > 0:
                    print("PASS /api/flights/tracks 組合數與底層 expand_track 一致（%d 組）"
                          % expected_total)
                else:
                    print("FAIL /api/flights/tracks 組合數不一致：api=%s expand_track=%s"
                          % (api_total, expected_total))
                    failures.append("flights combination count mismatch")

                # 觸發掃描：配額不足時必須回 200（排隊）而非錯誤——
                # 那是預期的營運狀態，不是系統故障（contracts「錯誤語意」）
                scan_status, scan_body = _post(
                    "/api/flights/tracks/%d/scan" % flight_track_id, b"{}",
                    {"Content-Type": "application/json"})
                scan_body = _json_or_none(scan_body)
                if scan_status == 200 and (scan_body or {}).get("state") == "queued":
                    print("PASS /api/flights/tracks/{id}/scan 配額用盡時回 200 排隊"
                          "（非錯誤），約 %d 分鐘後釋出"
                          % (((scan_body.get("seconds_until_free") or 0) + 59) // 60))
                else:
                    print("FAIL /api/flights/tracks/{id}/scan：status=%s body=%s"
                          % (scan_status, scan_body))
                    failures.append("flights scan trigger")

                res_status, res_body = _get(
                    "/api/flights/tracks/%d/results" % flight_track_id)
                if res_status == 200 and "results" in (res_body or {}):
                    print("PASS /api/flights/tracks/{id}/results 回應含 results 與 progress")
                    # 原生追蹤說明必須明確回報「不支援四段票」——這是結構化
                    # 欄位而非文案，前端據此呈現限制（FR-022）
                    nt_status, nt_body = _get("/api/flights/native-tracking")
                    if (nt_status == 200
                            and (nt_body or {}).get("supported_for_four_segment") is False
                            and (nt_body or {}).get("reason")):
                        print("PASS /api/flights/native-tracking 明確回報四段票不支援且附理由")
                    else:
                        print("FAIL /api/flights/native-tracking：status=%s" % nt_status)
                        failures.append("flights native tracking")
                else:
                    print("FAIL /api/flights/tracks/{id}/results：status=%s" % res_status)
                    failures.append("flights results")

            # ---- 價格追蹤（specs/006-flight-price-tracking，T029）----
            # 同樣是深度檢查：PATCH 之後**重新查一次清單**確認真的寫進去，
            # 並把 API 回報的下次掃描日跟底層 next_scan_date() 對照——
            # 只看 PATCH 回 200 的話，寫入沒生效也會通過。
            if flight_track_id:
                pa_status, pa_body = _patch(
                    "/api/flights/tracks/%d" % flight_track_id,
                    json.dumps({"scan_frequency_days": 30}).encode("utf-8"))
                pa_body = _json_or_none(pa_body)
                re_status, re_body = _get("/api/flights/tracks")
                persisted = None
                for t in (re_body or {}).get("tracks", []):
                    if t.get("id") == flight_track_id:
                        persisted = t
                if (pa_status == 200 and persisted
                        and persisted.get("scan_frequency_days") == 30):
                    print("PASS PATCH /api/flights/tracks/{id} 頻率改為每月並持久化")
                else:
                    print("FAIL PATCH 頻率：status=%s 重查得到 %s"
                          % (pa_status, (persisted or {}).get("scan_frequency_days")))
                    failures.append("flights patch frequency")

                # 下次掃描日：與底層同一支函式對照，且必須落在該條件排定的
                # 星期幾——前端只顯示這個值，算錯不會有任何其他徵兆
                _st2 = _fstore.FlightStore(os.environ["ALPHAVIBE_DATA_DIR"])
                try:
                    _t2 = _st2.get_track(flight_track_id)
                    expected_next = _svc.next_scan_date(_t2)
                    expected_wd = _svc.scheduled_weekday(_t2)
                finally:
                    _st2.close()
                api_next = (persisted or {}).get("next_scan_date")
                # 用既有的 `from datetime import datetime`（本檔案第 44 行
                # 已把模組名綁成 class），不另外 import 模組造成名稱衝突
                next_wd = (datetime.fromisoformat(api_next).weekday()
                           if api_next else None)
                if api_next == expected_next and next_wd == expected_wd:
                    print("PASS 下次掃描日與底層 next_scan_date 一致（%s，星期%d）"
                          % (api_next, expected_wd + 1))
                else:
                    print("FAIL 下次掃描日：api=%s 底層=%s 星期 api=%s 應為 %s"
                          % (api_next, expected_next, next_wd, expected_wd))
                    failures.append("flights next_scan_date")

                # 頻率必須是正整數——0 或負數會讓排程每天都判定「到期」
                z_status, _z = _patch(
                    "/api/flights/tracks/%d" % flight_track_id,
                    json.dumps({"scan_frequency_days": 0}).encode("utf-8"))
                if z_status == 400:
                    print("PASS PATCH 頻率 0 被拒絕（400）")
                else:
                    print("FAIL PATCH 頻率 0 未被拒絕：status=%s" % z_status)
                    failures.append("flights patch frequency validation")

                # 結果端點要帶出通知狀態欄位（FR-019）——沒通知過時是
                # 欄位齊全但值為 None，不是整個 key 不存在，否則前端
                # 得對兩種形狀各寫一套判斷
                nres_status, nres_body = _get(
                    "/api/flights/tracks/%d/results" % flight_track_id)
                nblock = (nres_body or {}).get("notify")
                if (nres_status == 200 and isinstance(nblock, dict)
                        and "last_notified_at" in nblock
                        and "last_notify_failed" in nblock):
                    print("PASS /results 帶出通知狀態欄位（未通知過時值為空）")
                else:
                    print("FAIL /results 通知狀態欄位：%s" % (nblock,))
                    failures.append("flights notify block")

                # ---- 組合數上限守衛（007-trip-day-range，T024）----
                # 天數區間 1~100（100 個選項）配 4 外站 × 每月抽樣 4 次
                # × 3 個月 = 4*4*3*100 = 4800，遠超過上限 60，必須被拒絕
                cap_status, cap_body = _post(
                    "/api/flights/tracks",
                    json.dumps({
                        "destination": "PRG",
                        "outstations": ["NRT", "OKA", "KIX", "FUK"],
                        "window_start": "2027-04", "window_end": "2027-06",
                        "trip_days_min": 1, "trip_days_max": 100,
                        "samples_per_month": 4,
                    }).encode("utf-8"),
                    {"Content-Type": "application/json"})
                cap_body = _json_or_none(cap_body)
                cap_detail = str((cap_body or {}).get("detail", ""))
                if (cap_status == 400 and "組合數" in cap_detail
                        and "60" in cap_detail):
                    print("PASS 組合數超標（4800 > 60）被拒絕並說明組合數與上限")
                else:
                    print("FAIL 組合數超標未被正確拒絕：status=%s body=%s"
                          % (cap_status, cap_body))
                    failures.append("flights combination cap")

                # 資料庫確認沒有真的寫入這筆超標條件——不能只信任 API
                # 回應，要對照底層資料
                _list_status, _list_body = _get("/api/flights/tracks")
                _names = [t.get("name") for t in (_list_body or {}).get("tracks", [])]
                if not any("FUK" in str(n) for n in _names):
                    print("PASS 超標條件確認未寫入資料庫")
                else:
                    print("FAIL 超標條件疑似仍被寫入資料庫：%s" % _names)
                    failures.append("flights combination cap db write")

                # ---- 目標價可獨立 PATCH（2026-09-24 新增）----
                # 跟頻率不同，改目標價不影響已枚舉的組合，所以要能單獨改
                # 且不動到剛才設的 scan_frequency_days=30
                tp_status, tp_body = _patch(
                    "/api/flights/tracks/%d" % flight_track_id,
                    json.dumps({"target_price": 40000}).encode("utf-8"))
                tp_body = _json_or_none(tp_body)
                if (tp_status == 200 and tp_body
                        and tp_body.get("target_price") == 40000
                        and tp_body.get("scan_frequency_days") == 30):
                    print("PASS PATCH target_price 更新且不影響其他欄位")
                else:
                    print("FAIL PATCH target_price：status=%s body=%s"
                          % (tp_status, tp_body))
                    failures.append("flights patch target_price")

                # 清空目標價：用 clear_target_price 旗標而非省略欄位，
                # 因為 JSON 缺席欄位與明確 null 在這個 schema 下都可能
                # 代表「沒有要改」，需要明確旗標才能表達「故意清空」
                cl_status, cl_body = _patch(
                    "/api/flights/tracks/%d" % flight_track_id,
                    json.dumps({"clear_target_price": True}).encode("utf-8"))
                cl_body = _json_or_none(cl_body)
                if cl_status == 200 and cl_body and cl_body.get("target_price") is None:
                    print("PASS PATCH clear_target_price 清空目標價")
                else:
                    print("FAIL PATCH clear_target_price：status=%s body=%s"
                          % (cl_status, cl_body))
                    failures.append("flights patch clear_target_price")

                # 空 PATCH（什麼都沒帶）必須被拒絕，不該悄悄變成 no-op
                empty_status, _eb = _patch(
                    "/api/flights/tracks/%d" % flight_track_id, b"{}")
                if empty_status == 400:
                    print("PASS PATCH 空 body 被拒絕（400）")
                else:
                    print("FAIL PATCH 空 body 未被拒絕：status=%s" % empty_status)
                    failures.append("flights patch empty body")

                # ---- 天數區間不開放 PATCH（007-trip-day-range，T025）----
                # 帶 trip_days_min/max 但也帶合法的 scan_frequency_days：
                # 請求應該成功（頻率有改），但天數必須維持不變——確認
                # 這兩個欄位被悄悄忽略，而不是被吃進去卻沒生效或報錯
                td_status, td_body = _patch(
                    "/api/flights/tracks/%d" % flight_track_id,
                    json.dumps({"scan_frequency_days": 14,
                               "trip_days_min": 999,
                               "trip_days_max": 999}).encode("utf-8"))
                td_body = _json_or_none(td_body)
                if (td_status == 200 and td_body
                        and td_body.get("scan_frequency_days") == 14
                        and td_body.get("trip_days_min") != 999
                        and td_body.get("trip_days_max") != 999):
                    print("PASS PATCH 天數區間欄位被忽略，其餘欄位正常生效")
                else:
                    print("FAIL PATCH 天數區間欄位未被正確忽略：%s" % td_body)
                    failures.append("flights patch ignores trip_days_range")

            # 驗證失敗必須回 400 並說明原因（FR-025）
            bad_status, bad_body = _post(
                "/api/flights/tracks",
                json.dumps({"destination": "PRG", "outstations": [],
                            "window_start": "2027-04", "window_end": "2027-05",
                            "trip_days_min": 10, "trip_days_max": 14}).encode("utf-8"),
                {"Content-Type": "application/json"})
            bad_body = _json_or_none(bad_body)
            if bad_status == 400 and "outstations" in str((bad_body or {}).get("detail", "")):
                print("PASS /api/flights/tracks 空外站清單被拒絕並說明原因")
            else:
                print("FAIL /api/flights/tracks 空外站清單未被正確拒絕：status=%s"
                      % bad_status)
                failures.append("flights validation")
        finally:
            if flight_track_id:
                del_status, _ = _delete("/api/flights/tracks/%d" % flight_track_id)
                if del_status == 204:
                    print("PASS /api/flights/tracks/{id} 刪除回 204")
                else:
                    print("FAIL /api/flights/tracks/{id} 刪除：status=%s" % del_status)
                    failures.append("flights delete")

        # ---- 單純來回（specs/008-roundtrip-search，T019）----
        # 同樣是深度檢查：建立→與底層 expand_roundtrip_track() 比對
        # 組合數→觸發掃描（配額已在上面佔滿，必為 queued）→查詢結果。
        roundtrip_track_id = None
        try:
            rt_created_status, rt_created = _post(
                "/api/flights/tracks/roundtrip",
                json.dumps({
                    "destinations": ["AOJ", "CTS"],
                    "window_start": "2027-01", "window_end": "2027-02",
                    "trip_days_min": 3, "trip_days_max": 7,
                    "samples_per_month": 2,
                }).encode("utf-8"),
                {"Content-Type": "application/json"})
            rt_created = _json_or_none(rt_created)
            if rt_created_status == 201 and rt_created and rt_created.get("id"):
                roundtrip_track_id = rt_created["id"]
                print("PASS /api/flights/tracks/roundtrip 建立條件（id=%s）"
                      % roundtrip_track_id)
            else:
                print("FAIL /api/flights/tracks/roundtrip 建立條件：status=%s body=%s"
                      % (rt_created_status, rt_created))
                failures.append("roundtrip create")

            if roundtrip_track_id:
                # 獨立 import：不依賴上面四段票區塊是否成功執行到
                # `import flight_scan_service as _svc` 那一步（若
                # flight_track_id 建立失敗，那段 import 不會執行）
                sys.path.insert(0, os.path.join(_APP_ROOT, "poc", "kb-mcp"))
                import flight_scan_service as _svc
                import flight_store as _fstore
                _st_rt = _fstore.FlightStore(os.environ["ALPHAVIBE_DATA_DIR"])
                try:
                    _rt_track = _st_rt.get_roundtrip_track(roundtrip_track_id)
                    _rt_itins, _rt_skipped = _svc.expand_roundtrip_track(_rt_track)
                    expected_rt_total = len(_rt_itins)
                finally:
                    _st_rt.close()

                rt_list_status, rt_list_body = _get("/api/flights/tracks")
                rt_api_total = None
                rt_track_type = None
                for t in (rt_list_body or {}).get("tracks", []):
                    if t.get("id") == roundtrip_track_id and t.get("track_type") == "roundtrip":
                        rt_api_total = (t.get("progress") or {}).get("total")
                        rt_track_type = t.get("track_type")
                if (rt_list_status == 200 and rt_api_total == expected_rt_total
                        and expected_rt_total > 0 and rt_track_type == "roundtrip"):
                    print("PASS /api/flights/tracks 合併清單含單純來回、"
                          "組合數與底層 expand_roundtrip_track 一致（%d 組）"
                          % expected_rt_total)
                else:
                    print("FAIL 單純來回組合數不一致：api=%s expand_roundtrip_track=%s"
                          % (rt_api_total, expected_rt_total))
                    failures.append("roundtrip combination count mismatch")

                # ---- 單純來回可編輯頻率／目標價（2026-09-25 補上，
                # 比照四段票 PATCH 端點）----
                rt_tp_status, rt_tp_body = _patch(
                    "/api/flights/tracks/roundtrip/%d" % roundtrip_track_id,
                    json.dumps({"target_price": 40000,
                               "scan_frequency_days": 14}).encode("utf-8"))
                rt_tp_body = _json_or_none(rt_tp_body)
                if (rt_tp_status == 200 and rt_tp_body
                        and rt_tp_body.get("target_price") == 40000
                        and rt_tp_body.get("scan_frequency_days") == 14):
                    print("PASS PATCH /api/flights/tracks/roundtrip/{id} "
                          "頻率與目標價同時更新")
                else:
                    print("FAIL PATCH /api/flights/tracks/roundtrip/{id}："
                          "status=%s body=%s" % (rt_tp_status, rt_tp_body))
                    failures.append("roundtrip patch frequency/target_price")

                rt_cl_status, rt_cl_body = _patch(
                    "/api/flights/tracks/roundtrip/%d" % roundtrip_track_id,
                    json.dumps({"clear_target_price": True}).encode("utf-8"))
                rt_cl_body = _json_or_none(rt_cl_body)
                if (rt_cl_status == 200 and rt_cl_body
                        and rt_cl_body.get("target_price") is None):
                    print("PASS PATCH /api/flights/tracks/roundtrip/{id} "
                          "clear_target_price 清空目標價")
                else:
                    print("FAIL PATCH clear_target_price（roundtrip）："
                          "status=%s body=%s" % (rt_cl_status, rt_cl_body))
                    failures.append("roundtrip patch clear_target_price")

                rt_empty_status, _rt_eb = _patch(
                    "/api/flights/tracks/roundtrip/%d" % roundtrip_track_id,
                    b"{}")
                if rt_empty_status == 400:
                    print("PASS PATCH /api/flights/tracks/roundtrip/{id} "
                          "空 body 被拒絕（400）")
                else:
                    print("FAIL PATCH 空 body（roundtrip）未被拒絕：status=%s"
                          % rt_empty_status)
                    failures.append("roundtrip patch empty body")

                # 配額已在四段票流程開頭佔滿，觸發掃描必為 queued
                rt_scan_status, rt_scan_body = _post(
                    "/api/flights/tracks/roundtrip/%d/scan" % roundtrip_track_id,
                    b"{}", {"Content-Type": "application/json"})
                rt_scan_body = _json_or_none(rt_scan_body)
                if rt_scan_status == 200 and (rt_scan_body or {}).get("state") == "queued":
                    print("PASS /api/flights/tracks/roundtrip/{id}/scan "
                          "配額用盡時回 200 排隊（非錯誤）")
                else:
                    print("FAIL /api/flights/tracks/roundtrip/{id}/scan：status=%s body=%s"
                          % (rt_scan_status, rt_scan_body))
                    failures.append("roundtrip scan trigger")

                rt_res_status, rt_res_body = _get(
                    "/api/flights/tracks/roundtrip/%d/results" % roundtrip_track_id)
                if (rt_res_status == 200 and "results" in (rt_res_body or {})
                        and "notify" in (rt_res_body or {})):
                    print("PASS /api/flights/tracks/roundtrip/{id}/results "
                          "回應含 results 與 notify")
                else:
                    print("FAIL /api/flights/tracks/roundtrip/{id}/results：status=%s"
                          % rt_res_status)
                    failures.append("roundtrip results")

            # 候選目的地為空必須被拒絕（FR-025 精神延伸至單純來回）
            rt_bad_status, rt_bad_body = _post(
                "/api/flights/tracks/roundtrip",
                json.dumps({"destinations": [],
                            "window_start": "2027-01", "window_end": "2027-02",
                            "trip_days_min": 3, "trip_days_max": 7}).encode("utf-8"),
                {"Content-Type": "application/json"})
            rt_bad_body = _json_or_none(rt_bad_body)
            if (rt_bad_status == 400
                    and "destinations" in str((rt_bad_body or {}).get("detail", ""))):
                print("PASS /api/flights/tracks/roundtrip 空候選目的地被拒絕並說明原因")
            else:
                print("FAIL /api/flights/tracks/roundtrip 空候選目的地未被正確拒絕："
                      "status=%s" % rt_bad_status)
                failures.append("roundtrip validation")

            # ---- preferred_transit 持久化（008 US2，T022）----
            # 建立時帶 preferred_transit，確認 create→list 往返後欄位值
            # 不變（4 段 legs 的判斷依據，見 flight_scan_service.py
            # expand_roundtrip_track() 的 transit 分支）
            rt_transit_id = None
            try:
                rt_t_status, rt_t_created = _post(
                    "/api/flights/tracks/roundtrip",
                    json.dumps({
                        "destinations": ["FRA"],
                        "window_start": "2027-01", "window_end": "2027-02",
                        "trip_days_min": 5, "trip_days_max": 9,
                        "preferred_transit": "NRT",
                        "samples_per_month": 1,
                    }).encode("utf-8"),
                    {"Content-Type": "application/json"})
                rt_t_created = _json_or_none(rt_t_created)
                if rt_t_status == 201 and rt_t_created and rt_t_created.get("id"):
                    rt_transit_id = rt_t_created["id"]
                    rt_t_list_status, rt_t_list_body = _get("/api/flights/tracks")
                    persisted = None
                    for t in (rt_t_list_body or {}).get("tracks", []):
                        if t.get("id") == rt_transit_id and t.get("track_type") == "roundtrip":
                            persisted = t.get("preferred_transit")
                    if rt_t_list_status == 200 and persisted == "NRT":
                        print("PASS preferred_transit 持久化：create→list 往返後仍為 NRT")
                    else:
                        print("FAIL preferred_transit 未正確持久化：got=%r" % persisted)
                        failures.append("roundtrip preferred_transit persistence")
                else:
                    print("FAIL preferred_transit 建立條件：status=%s body=%s"
                          % (rt_t_status, rt_t_created))
                    failures.append("roundtrip preferred_transit create")
            finally:
                if rt_transit_id:
                    rt_t_del_status, _ = _delete(
                        "/api/flights/tracks/roundtrip/%d" % rt_transit_id)
                    if rt_t_del_status != 204:
                        print("FAIL preferred_transit 測試條件刪除：status=%s"
                              % rt_t_del_status)
                        failures.append("roundtrip preferred_transit cleanup")

            # ---- 組合數上限守衛（008 US4，T028）----
            # 候選目的地 4 個 × 天數選項 100 個（1~100 天）× 每月抽樣 4 次
            # × 3 個月 = 4800，遠超過上限 60
            rt_cap_status, rt_cap_body = _post(
                "/api/flights/tracks/roundtrip",
                json.dumps({
                    "destinations": ["AOJ", "CTS", "AXT", "KIJ"],
                    "window_start": "2027-01", "window_end": "2027-03",
                    "trip_days_min": 1, "trip_days_max": 100,
                    "samples_per_month": 4,
                }).encode("utf-8"),
                {"Content-Type": "application/json"})
            rt_cap_body = _json_or_none(rt_cap_body)
            rt_cap_detail = str((rt_cap_body or {}).get("detail", ""))
            if (rt_cap_status == 400 and "組合數" in rt_cap_detail
                    and "60" in rt_cap_detail):
                print("PASS 單純來回組合數超標（4800 > 60）被拒絕並說明組合數與上限")
            else:
                print("FAIL 單純來回組合數超標未被正確拒絕：status=%s body=%s"
                      % (rt_cap_status, rt_cap_body))
                failures.append("roundtrip combination cap")
        finally:
            if roundtrip_track_id:
                rt_del_status, _ = _delete(
                    "/api/flights/tracks/roundtrip/%d" % roundtrip_track_id)
                if rt_del_status == 204:
                    print("PASS /api/flights/tracks/roundtrip/{id} 刪除回 204")
                else:
                    print("FAIL /api/flights/tracks/roundtrip/{id} 刪除：status=%s"
                          % rt_del_status)
                    failures.append("roundtrip delete")

        # 2026-08-22 教訓：get_kb_store() 是 sync generator dependency，
        # Starlette 用 anyio thread pool 執行，「建立」跟「關閉」不保證
        # 同一條 worker thread——沒有 check_same_thread=False 時，正式
        # 環境併發測試 30 個 request 有 23 個 500
        # （sqlite3.ProgrammingError）。這裡刻意送真正併發（非依序）的
        # 30 個請求，確保這個 class 的 bug 回歸時測試會抓到，不是只測
        # 依序請求（依序請求幾乎不會踩到這個 race）。**必須放在
        # finally/proc.terminate() 之前**——server 被關掉之後才送請求，
        # 只會得到 ConnectionRefused，不是在測併發，這是這份測試自己
        # 曾經踩過的坑（見同一天的 commit）。
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            statuses = list(pool.map(
                lambda _: _get("/api/assets/holdings")[0], range(30)))
        ok_count = sum(1 for s in statuses if s == 200)
        if ok_count == 30:
            print("PASS 30 個併發請求全數 200（無 SQLite 跨執行緒競爭）")
        else:
            print("FAIL 30 個併發請求只有 %d 個 200（疑似 sqlite3 "
                  "跨執行緒競爭回歸，檢查 kb_store.py 的 "
                  "check_same_thread 設定）" % ok_count)
            failures.append("concurrency regression")

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
