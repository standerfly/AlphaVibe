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

import concurrent.futures
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
            ("GET /api/pending-verifications", "/api/pending-verifications", 200),
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

        # 待觀察／待查詢清單（2026-08-27新增，specs/001-pending-verification-list/）：
        # 空清單先驗證（避免測試庫本身剛好有殘留資料造成誤判），再寫入
        # 一筆已到期＋一筆還很遠的項目，驗證 API 的 due_only 篩選邏輯跟
        # 直接呼叫底層 list_pending_verifications(due_only=True) 一致
        # （比照上面 /api/screen 等既有比對精神：不只驗證「有回傳」，
        # 要跟底層函式逐欄比對）。
        status, empty_body = _get("/api/pending-verifications")
        if status == 200 and empty_body == {"items": []}:
            print("PASS /api/pending-verifications 初始為空清單")
        else:
            print("FAIL /api/pending-verifications 初始清單不是空的：%r"
                  % (empty_body,))
            failures.append("pending-verifications not empty initially")

        pv_store = KBStore(data_dir)
        try:
            due_item = pv_store.save_pending_verification(
                judgment_text="smoke-test 已到期案例",
                trigger_type="date", trigger_condition_text="測試觸發條件",
                trigger_date="2020-01-01")
            pv_store.save_pending_verification(
                judgment_text="smoke-test 還很遠案例",
                trigger_type="date", trigger_condition_text="測試觸發條件",
                trigger_date="2099-01-01")
            expected_due = pv_store.list_pending_verifications(due_only=True)
        finally:
            pv_store.close()
        status, actual_due = _get("/api/pending-verifications")
        norm_expected_due = json.loads(json.dumps(expected_due))
        if (status == 200 and actual_due == {"items": norm_expected_due}
                and len(norm_expected_due) == 1
                and norm_expected_due[0]["id"] == due_item["id"]):
            print("PASS /api/pending-verifications?due_only=true 跟 "
                  "list_pending_verifications(due_only=True) 一致（只含已到期項目）")
        else:
            print("FAIL /api/pending-verifications 跟底層函式不一致")
            print("  expected:", json.dumps(norm_expected_due, ensure_ascii=False))
            print("  actual  :", json.dumps(actual_due, ensure_ascii=False))
            failures.append("pending-verifications output mismatch")

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            pv_statuses = list(pool.map(
                lambda _: _get("/api/pending-verifications")[0], range(30)))
        pv_ok_count = sum(1 for s in pv_statuses if s == 200)
        if pv_ok_count == 30:
            print("PASS /api/pending-verifications 30 個併發請求全數 200")
        else:
            print("FAIL /api/pending-verifications 30 個併發請求只有 %d 個 200"
                  % pv_ok_count)
            failures.append("pending-verifications concurrency regression")

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
