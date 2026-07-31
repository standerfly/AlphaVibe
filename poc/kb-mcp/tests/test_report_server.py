"""report_server 測試：即時渲染、PWA meta、icon、健康檢查、404。

2026-07-30：新增 `/mcp` 路徑測試（見 test_mcp_post_dispatches_via_gateway
等，class尾端）——mcp_http_gateway.py 的 `/mcp` 端點邏輯合併進
report_server.py，同process同埠（8080）共用，不再需要另外轉發新埠。
這裡只驗證「合併後這條路真的通」，完整的協定情境（token驗證/401、
不支援協定版本400、壞JSON、notification 202…）已在
test_mcp_http_gateway.py 的 HandleMcpPostDirectCallTest 涵蓋，不重測。

2026-07-30：新增 Dashboard HTTP Basic Auth 測試（見
DashboardBasicAuthTest，獨立class＋獨立server，因為需要動態切換
ALPHAVIBE_DASHBOARD_TOKEN 環境變數，不想污染上面 ReportServerTest
共用同一個server的其他測試）。見 report_server.py 模組docstring最後
一段與 `_dashboard_auth_ok()`。
"""
import base64
import html
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import finmind_client  # noqa: E402
import frameworks  # noqa: E402
import market_scan  # noqa: E402
import report  # noqa: E402
import report_server  # noqa: E402
import screener  # noqa: E402
from kb_store import KBStore  # noqa: E402


class ReportServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="alphavibe-rsrv-test-")
        report_server.ReportHandler.data_dir = cls.tmp
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), report_server.ReportHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def _get(self, path):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def _post(self, path, form):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()

    def _rpc(self, payload):
        """POST /mcp 用：body是原始JSON-RPC訊息，不是urlencoded表單
        （跟其他/dashboard/*等路徑的表單格式不同）。"""
        url = "http://127.0.0.1:%d/mcp" % self.port
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def _extract_hidden_value(self, page, field_name):
        """從渲染出來的HTML裡取出 `<input type="hidden" name="{field_name}"
        value="...">` 的原始值，並做html.unescape還原成真實內容——模擬瀏覽器
        解析HTML屬性值的行為（真實瀏覽器會在送出表單前先unescape再
        urlencode，這裡手動重現這兩步，因為測試沒有真的瀏覽器可用）。"""
        match = re.search(
            r'name="%s" value="(.*?)">' % re.escape(field_name), page)
        self.assertIsNotNone(
            match, "找不到 hidden input name=\"%s\"" % field_name)
        return html.unescape(match.group(1))

    def test_page_ok_and_pwa_meta(self):
        """FR-058：`/` 現在渲染儀表板（方案A），不是舊版render()——見下方
        test_report_classic_path_renders_legacy_full_page，舊版仍完整保留在
        /report-classic。"""
        status, headers, body = self._get("/")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("AlphaVibe 儀表板", page)
        self.assertIn("apple-mobile-web-app-capable", page)
        self.assertIn("apple-touch-icon", page)

    def test_report_classic_path_renders_legacy_full_page(self):
        status, headers, body = self._get("/report-classic")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("AlphaVibe 知識庫檢視", page)

    def test_live_rendering_reflects_new_data(self):
        _, _, before = self._get("/report.html")
        self.assertNotIn("台積電".encode("utf-8"), before)
        store = KBStore(self.tmp)
        store.save_stance("2330", "偏多", name="台積電")
        store.close()
        _, _, after = self._get("/report.html")
        self.assertIn("台積電".encode("utf-8"), after)

    def test_legacy_bookmark_path(self):
        status, _, body = self._get("/poc/data/report.html")
        self.assertEqual(status, 200)
        self.assertIn("AlphaVibe 知識庫檢視".encode("utf-8"), body)

    def test_icon_is_valid_png(self):
        status, headers, body = self._get("/apple-touch-icon.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        # 舊書籤路徑下的相對 icon 連結也要通
        status2, _, _ = self._get("/poc/data/apple-touch-icon.png")
        self.assertEqual(status2, 200)

    def test_healthz_and_404(self):
        status, _, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/no/such/page")
        self.assertEqual(ctx.exception.code, 404)

    def test_screen_get_returns_form(self):
        status, headers, body = self._get("/screen")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("<form method=\"post\" action=\"/screen\">", page)

    def test_screen_post_empty_codes_reshows_form_with_error(self):
        status, _, body = self._post("/screen", {"codes": "   "})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("請至少輸入一個股票代碼", page)

    def test_screen_post_renders_results_table(self):
        fake_result = {
            "results": [{"code": "2330", "name": "台積電", "per": 10.0,
                        "revenue_yoy": 0.20, "drawdown_pct": 0.40,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 60.0, "current_date": "2026-07-01",
                        "peg": 0.5, "meets_framework": True, "error": None}],
            "total": 1,
        }
        with unittest.mock.patch.object(
                screener, "screen_stocks", return_value=fake_result) as mock_screen:
            status, _, body = self._post("/screen", {"codes": "2330"})
        mock_screen.assert_called_once_with(["2330"], data_dir=self.tmp)
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("data-label=\"代碼\">2330", page)
        self.assertIn("class=\"row-highlight\"", page)

    def test_screen_post_wrong_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/no/such/post", {"codes": "2330"})
        self.assertEqual(ctx.exception.code, 404)

    def test_market_scan_get_empty_state(self):
        status, headers, body = self._get("/market-scan")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("尚無掃描紀錄", page)

    def test_market_scan_get_shows_existing_latest(self):
        store = KBStore(self.tmp)
        store.save_market_scan_run(
            "peg_deep_dip_concentration", "scheduled",
            [{"code": "3135", "name": "凌航", "market": "TWSE", "industry": "半導體業",
              "per": 8.0, "revenue_yoy": 0.5, "revenue_period": "2026-06",
              "drawdown_pct": 0.45, "high_price": 100.0, "high_date": "2026-06-01",
              "current_price": 55.0, "current_date": "2026-07-20", "peg": 0.16,
              "meets_framework": True, "error": None}],
            candidate_count=1)
        store.close()
        status, _, body = self._get("/market-scan")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("data-label=\"代碼\">3135", page)

    def test_market_scan_get_unknown_framework_falls_back_to_default(self):
        # 這個class的其他測試會共用同一個self.tmp資料庫，執行順序不保證資料
        # 是空的，所以這裡只驗證「不報錯、退回預設框架」，不假設空狀態文字。
        status, _, body = self._get("/market-scan?framework=no_such_framework")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("PEG深度回檔", page)  # 預設框架的下拉選單標籤有出現

    def test_market_scan_post_triggers_scan_and_persists(self):
        fake_result = {
            "framework_id": "peg_deep_dip_concentration", "trigger_source": "manual",
            "candidate_count": 1, "meets_count": 1,
            "market_errors": {"TWSE": None, "TPEx": None}, "total_scanned": 1973,
            "results": [{"code": "3135", "name": "凌航", "market": "TWSE",
                        "industry": "半導體業", "per": 8.0, "revenue_yoy": 0.5,
                        "revenue_period": "2026-06", "drawdown_pct": 0.45,
                        "high_price": 100.0, "high_date": "2026-06-01",
                        "current_price": 55.0, "current_date": "2026-07-20",
                        "peg": 0.16, "meets_framework": True, "error": None}],
        }
        with unittest.mock.patch.object(
                market_scan, "run_scan", return_value=fake_result) as mock_scan:
            status, _, body = self._post(
                "/market-scan", {"framework": "peg_deep_dip_concentration"})
            mock_scan.assert_called_once_with(
                "peg_deep_dip_concentration", data_dir=self.tmp, trigger_source="manual")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("data-label=\"代碼\">3135", page)

        # 觸發過的結果要真的存進DB，之後GET也看得到（不是只顯示這次response）
        store = KBStore(self.tmp)
        latest = store.get_latest_market_scan("peg_deep_dip_concentration")
        store.close()
        self.assertTrue(latest["found"])
        self.assertEqual(latest["results"][0]["code"], "3135")

    def test_market_scan_post_unknown_framework_falls_back_to_default(self):
        """網頁表單的框架代號只會從下拉選單來，理論上不會亂打；萬一收到不明
        代號（如表單被竄改），退回預設框架正常執行，不要讓使用者看到裸錯誤。"""
        with unittest.mock.patch.object(
                market_scan, "run_scan",
                return_value={"framework_id": frameworks.default_framework_id(),
                             "trigger_source": "manual", "candidate_count": 0,
                             "meets_count": 0, "market_errors": {"TWSE": None, "TPEx": None},
                             "total_scanned": 1973, "results": []}) as mock_scan:
            status, _, body = self._post("/market-scan", {"framework": "no_such_framework"})
            mock_scan.assert_called_once_with(
                frameworks.default_framework_id(), data_dir=self.tmp, trigger_source="manual")
        self.assertEqual(status, 200)

    def test_market_scan_post_error_does_not_persist(self):
        """run_scan本身回傳error時（例如未來新增其他失敗情境），頁面要顯示
        錯誤訊息，且不能寫入資料庫（避免存進一筆沒有意義的空紀錄）。

        這個class的其他測試會共用同一個self.tmp資料庫，不能假設呼叫前是
        空的——改成比對呼叫前後的run_id是否改變（沒改變＝沒有新增資料）。"""
        store = KBStore(self.tmp)
        before = store.get_latest_market_scan()
        store.close()
        before_run_id = before["run"]["id"] if before["found"] else None

        with unittest.mock.patch.object(
                market_scan, "run_scan",
                return_value={"error": "模擬失敗"}):
            status, _, body = self._post(
                "/market-scan", {"framework": "peg_deep_dip_concentration"})
        self.assertEqual(status, 200)
        self.assertIn("模擬失敗", body.decode("utf-8"))

        store = KBStore(self.tmp)
        after = store.get_latest_market_scan()
        store.close()
        after_run_id = after["run"]["id"] if after["found"] else None
        self.assertEqual(before_run_id, after_run_id)  # 沒有新增任何一筆

    def _seed_scan_result(self, code, meets=True, peg=0.16):
        """幫/market-scan/track測試準備一筆真實存在的run+result（用獨特代碼
        前綴避免跟其他測試/其他候選代碼衝突）。"""
        store = KBStore(self.tmp)
        try:
            saved = store.save_market_scan_run(
                "peg_deep_dip_concentration", "manual",
                [{"code": code, "name": "測試股%s" % code, "market": "TWSE",
                  "industry": "半導體業", "per": 8.0, "revenue_yoy": 0.5,
                  "revenue_period": "2026-06", "drawdown_pct": 0.45,
                  "high_price": 100.0, "high_date": "2026-06-01",
                  "current_price": 55.0, "current_date": "2026-07-20",
                  "peg": peg, "meets_framework": meets, "error": None}],
                candidate_count=1)
        finally:
            store.close()
        return saved["run_id"]

    def test_track_post_success_no_conflict(self):
        run_id = self._seed_scan_result("T9101")
        status, _, body = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9101", "stance": "觀察"})
        self.assertEqual(status, 200)
        self.assertIn("已加入追蹤", body.decode("utf-8"))

        store = KBStore(self.tmp)
        latest = store.get_latest_stance("T9101")
        store.close()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["stance"], "觀察")
        self.assertIn("PEG", latest["reason"])
        self.assertEqual(latest["source_ref"], "market_scan/run_%d" % run_id)

    def test_track_post_conflict_then_overwrite_confirm(self):
        run_id = self._seed_scan_result("T9102")
        status1, _, body1 = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9102", "stance": "觀察"})
        self.assertEqual(status1, 200)

        # 再次加入追蹤，改選不同立場 → 應該觸發衝突確認頁，不是直接存入
        status2, _, body2 = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9102", "stance": "偏多"})
        page2 = body2.decode("utf-8")
        self.assertEqual(status2, 200)
        self.assertIn("已有立場，要更新嗎", page2)
        self.assertIn("觀察", page2)
        self.assertIn("偏多", page2)

        store = KBStore(self.tmp)
        still_old = store.get_latest_stance("T9102")
        store.close()
        self.assertEqual(still_old["stance"], "觀察")  # 還沒真的覆蓋

        # 確認覆蓋
        status3, _, body3 = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9102", "stance": "偏多", "overwrite": "1"})
        self.assertEqual(status3, 200)
        self.assertIn("已更新覆蓋既有立場", body3.decode("utf-8"))

        store = KBStore(self.tmp)
        new_latest = store.get_latest_stance("T9102")
        history = store.get_stance_history("T9102", limit=10)
        store.close()
        self.assertEqual(new_latest["stance"], "偏多")
        self.assertEqual(len(history), 2)  # 舊的「觀察」歷史還在，沒被刪除

    def test_track_post_missing_scan_result_shows_error_page(self):
        status, _, body = self._post(
            "/market-scan/track",
            {"run_id": "999999", "code": "T9103", "stance": "觀察"})
        self.assertEqual(status, 200)
        self.assertIn("找不到這筆候選資料", body.decode("utf-8"))

    def test_track_post_invalid_stance_defaults_to_observe(self):
        run_id = self._seed_scan_result("T9104")
        status, _, body = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9104", "stance": "亂打的值"})
        self.assertEqual(status, 200)
        self.assertIn("已加入追蹤", body.decode("utf-8"))

        store = KBStore(self.tmp)
        latest = store.get_latest_stance("T9104")
        store.close()
        self.assertEqual(latest["stance"], "觀察")

    def test_track_post_same_stance_again_appends_no_conflict(self):
        """疊加情境：立場沒變，再按一次也不該觸發衝突頁，直接多存一筆歷史。"""
        run_id = self._seed_scan_result("T9105")
        self._post("/market-scan/track",
                   {"run_id": str(run_id), "code": "T9105", "stance": "觀察"})
        status, _, body = self._post(
            "/market-scan/track",
            {"run_id": str(run_id), "code": "T9105", "stance": "觀察"})
        self.assertEqual(status, 200)
        self.assertIn("已加入追蹤", body.decode("utf-8"))
        self.assertNotIn("已有立場，要更新嗎", body.decode("utf-8"))

        store = KBStore(self.tmp)
        history = store.get_stance_history("T9105", limit=10)
        store.close()
        self.assertEqual(len(history), 2)

    # ---------- FR-058 快速輸入：3個表單各自的POST路由 ----------
    # 303轉址後urllib預設會自動跟隨（轉成GET），self._post()拿到的就是
    # 轉址後首頁（含flash訊息）的最終回應，不用另外處理Location header。

    def test_dashboard_watchlist_post_success_redirects_with_flash(self):
        status, _, body = self._post(
            "/dashboard/watchlist", {"code": "T9201", "name": "測試自選股"})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("已加入自選股：T9201", page)

        store = KBStore(self.tmp)
        latest = store.get_latest_stance("T9201")
        store.close()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["stance"], "觀察")
        self.assertEqual(latest["name"], "測試自選股")
        self.assertEqual(latest["source_ref"], "dashboard快速輸入")

    def test_dashboard_watchlist_post_missing_code_shows_error(self):
        status, _, body = self._post("/dashboard/watchlist", {"name": "缺代碼"})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("代碼為必填", page)

        store = KBStore(self.tmp)
        latest = store.get_latest_stance("")
        store.close()
        self.assertIsNone(latest)  # 沒有真的存入任何東西

    def test_dashboard_trade_post_success(self):
        status, _, body = self._post("/dashboard/trade", {
            "code": "T9202", "name": "測試交易股", "action": "買",
            "shares": "1000", "price": "55.5", "date": "2026-07-30",
            "add_sequence": "1"})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("已記錄交易：T9202 買", page)

        store = KBStore(self.tmp)
        ledger = store.get_trade_ledger("T9202")
        store.close()
        self.assertEqual(ledger["count"], 1)
        self.assertEqual(ledger["entries"][0]["shares"], 1000.0)
        self.assertEqual(ledger["entries"][0]["price"], 55.5)
        self.assertEqual(ledger["entries"][0]["add_sequence"], 1)

    def test_dashboard_trade_post_missing_required_field_shows_error(self):
        status, _, body = self._post("/dashboard/trade", {
            "code": "T9203", "action": "買", "date": "2026-07-30"})  # 缺股數／價格
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("缺少必填欄位", page)
        self.assertIn("股數", page)
        self.assertIn("價格", page)

        store = KBStore(self.tmp)
        ledger = store.get_trade_ledger("T9203")
        store.close()
        self.assertEqual(ledger["count"], 0)

    def test_dashboard_trade_post_invalid_number_shows_error(self):
        status, _, body = self._post("/dashboard/trade", {
            "code": "T9206", "action": "買", "shares": "不是數字",
            "price": "10", "date": "2026-07-30"})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("格式錯誤", page)

    def test_dashboard_laoyutou_post_success(self):
        """2026-07-30 改版：貼整段格式化文字（不再逐欄位填），伺服器端呼叫
        trade_text_parser 解析＋批次寫入。預先存好 stock_aliases 快取命中，
        測試才不會意外觸發真的 FinMind 網路查詢（比照
        test_trade_text_parser.py 既有的 mock/預先快取慣例）。"""
        store = KBStore(self.tmp)
        store.save_stock_alias("測試老芋頭股", "T9204", source="測試預先快取")
        store.close()

        text = "20260730\n獲利了結\n88賣出500股測試老芋頭股"
        status, _, body = self._post("/dashboard/laoyutou", {"text": text})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("已存入 1 筆老芋頭交易", page)

        store = KBStore(self.tmp)
        trades = store.get_laoyutou_trades(code="T9204")
        store.close()
        self.assertEqual(trades["count"], 1)
        self.assertEqual(trades["trades"][0]["reason"], "獲利了結")
        self.assertEqual(trades["trades"][0]["action"], "賣")
        self.assertEqual(trades["trades"][0]["date"], "2026-07-30")

    def test_dashboard_laoyutou_post_missing_required_field_shows_error(self):
        status, _, body = self._post("/dashboard/laoyutou", {"text": "   "})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("內容是空的", page)

    def test_dashboard_laoyutou_post_unresolved_name_reported_not_saved(self):
        """代碼查無比對時不寫入、且在flash訊息裡明確列出哪個名稱未解析，
        不能靜默丟掉。mock掉finmind_client.get_stock_info——不能因為快取
        沒命中就在測試裡打真的FinMind API（本專案已有過密集測試打光額度
        的教訓，見CLAUDE.md），回傳空清單模擬「FinMind也查無比對」。"""
        text = "20260730\n88買進100股絕對查無此股票代號測試"
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}):
            status, _, body = self._post("/dashboard/laoyutou", {"text": text})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("代碼查無比對", page)
        self.assertIn("絕對查無此股票代號測試", page)

    def test_dashboard_tradeledger_post_success_with_add_sequence(self):
        """FR-056：貼PO自己的交易明細表文字，伺服器端呼叫trade_ledger_parser
        解析＋批次寫入trade_ledger（不是laoyutou_trades）。預先存好
        stock_aliases快取命中，避免測試觸發真的FinMind網路查詢。"""
        store = KBStore(self.tmp)
        store.save_stock_alias("測試明細股", "T9207", source="測試預先快取")
        store.close()

        text = ("115/07/22 集買 測試明細股 10 100.00 7 1,000 1,007(收) k-0001-00\n"
                "115/07/23 集買 測試明細股 10 105.00 7 1,050 1,057(收) k-0002-00\n"
                "115/07/24 集賣 測試明細股 5 110.00 2 550 548(付) k-0003-00\n")
        status, _, body = self._post("/dashboard/tradeledger", {"text": text})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("已存入 3 筆交易明細", page)

        store = KBStore(self.tmp)
        ledger = store.get_trade_ledger("T9207")
        store.close()
        self.assertEqual(ledger["count"], 3)
        buys = [e for e in ledger["entries"] if e["action"] == "買"]
        sells = [e for e in ledger["entries"] if e["action"] == "賣"]
        self.assertEqual(sorted(e["add_sequence"] for e in buys), [1, 2])
        self.assertEqual([e["add_sequence"] for e in sells], [None])

    def test_dashboard_tradeledger_post_missing_required_field_shows_error(self):
        status, _, body = self._post("/dashboard/tradeledger", {"text": "   "})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("內容是空的", page)

    def test_dashboard_tradeledger_post_unresolved_name_reported_not_saved(self):
        """代碼查無比對時不寫入、flash訊息要明確列出未解析名稱。mock掉
        finmind_client.get_stock_info，理由同老芋頭那組測試（避免打光
        FinMind匿名額度）。"""
        text = "115/07/22 集買 絕對查無此股票代號測試 10 100.00 7 1,000 1,007(收) k-0001-00\n"
        with unittest.mock.patch.object(
                finmind_client, "get_stock_info", return_value={"stocks": []}):
            status, _, body = self._post("/dashboard/tradeledger", {"text": text})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("代碼查無比對", page)
        self.assertIn("絕對查無此股票代號測試", page)

    def test_dashboard_holdings_preview_post_empty_text_shows_error(self):
        status, _, body = self._post(
            "/dashboard/holdings/preview", {"text": "   "})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("內容是空的", page)

    def test_dashboard_holdings_preview_post_shows_diff_and_unparsed_lines(self):
        """預覽頁要能分類新增／消失／股數變化，且unparsed_lines非空時要
        清楚列出，不能吞掉。代碼刻意用9911/9912/9913這種測試專用範圍，
        避開2330/3661/3135等其他測試（同一個class共用一個store/tmp）已經
        用掉、且test_live_rendering_reflects_new_data等測試會拿來當「這個
        字串不該出現」判準的代碼／名稱，避免互相污染。"""
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "9911", "name": "測試庫存股-KY", "shares": 100, "avg_cost": 3000},
            {"code": "9913", "name": "測試即將消失股", "shares": 50, "avg_cost": None},
        ])
        store.close()

        # "89898 缺股數的一行"：開頭是數字（看起來像資料列）但沒有股數欄位，
        # 不符合 holdings_parser._DATA_LINE_RE，會落入 unparsed_lines
        # （開頭不是數字的雜訊行會被 holdings_parser 靜默忽略，不算
        # unparsed，見 holdings_parser.py 的 _LOOKS_LIKE_DATA_RE）。
        text = ("9911 測試庫存股-KY 200 3480.00\n"
                "9912 測試新進股 500 100.00\n"
                "89898 缺股數的一行")
        status, _, body = self._post("/dashboard/holdings/preview", {"text": text})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)

        self.assertIn("新增（這次有、上次沒有）", page)
        self.assertIn("9912", page)
        self.assertIn("測試新進股", page)
        self.assertIn("這次帳單沒有這一檔", page)
        self.assertIn("9913", page)
        self.assertIn("測試即將消失股", page)
        self.assertIn("股數變化", page)
        self.assertIn("9911", page)
        self.assertIn("1 行無法解析", page)
        self.assertIn("89898 缺股數的一行", page)

        # 沒有真的寫入資料庫（人工確認關卡：預覽不能有寫入副作用）
        store = KBStore(self.tmp)
        history = store.get_holdings(code="9912")
        store.close()
        self.assertEqual(history["count"], 0)

    def test_dashboard_holdings_confirm_post_missing_rows_shows_error(self):
        status, _, body = self._post(
            "/dashboard/holdings/confirm", {"rows_json": ""})
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("沒有可存入的資料", page)

    def test_dashboard_holdings_preview_then_confirm_full_flow(self):
        """端到端：貼帳單→預覽→從隱藏欄位取值→確認存入，驗證store真的多了
        一筆新快照，且股票名稱（含「-KY」）在HTML跳脫/還原往返中不失真，
        avg_cost從上次快照正確沿用。用get_holdings(code=...)查逐代碼歷史
        （而非get_holdings()整批最新快照）來驗證——save_holdings每次呼叫
        都是單純INSERT、同一天內重複呼叫會在同一個snapshot_date累加多筆，
        這是既有行為（不可更動），用code查詢history[0]（最新一筆）才是
        對這個功能本身的正確驗證方式，不受同一天內測試seed資料干擾。"""
        store = KBStore(self.tmp)
        store.save_holdings([
            {"code": "9921", "name": "測試庫存股-KY", "shares": 100, "avg_cost": 3000},
        ])
        store.close()

        text = "9921 測試庫存股-KY 200 3480.00\n9922 測試新進股 500 100.00"
        status, _, body = self._post("/dashboard/holdings/preview", {"text": text})
        preview_page = body.decode("utf-8")
        self.assertEqual(status, 200)

        rows_json_raw = self._extract_hidden_value(preview_page, "rows_json")
        restored_rows = json.loads(rows_json_raw)
        by_code = {r["code"]: r for r in restored_rows}
        self.assertEqual(by_code["9921"]["name"], "測試庫存股-KY")  # 「-KY」往返不失真
        self.assertEqual(by_code["9921"]["avg_cost"], 3000)  # 沿用上次成本
        self.assertIsNone(by_code["9922"]["avg_cost"])  # 全新代碼，無成本可沿用

        confirm_status, _, confirm_body = self._post(
            "/dashboard/holdings/confirm", {"rows_json": rows_json_raw})
        self.assertEqual(confirm_status, 200)
        confirm_page = confirm_body.decode("utf-8")
        self.assertIn("已存入 2 檔持股快照", confirm_page)

        store = KBStore(self.tmp)
        latest_9921 = store.get_holdings(code="9921")["history"][0]
        latest_9922 = store.get_holdings(code="9922")["history"][0]
        store.close()
        self.assertEqual(latest_9921["name"], "測試庫存股-KY")
        self.assertEqual(latest_9921["shares"], 200)
        self.assertEqual(latest_9921["avg_cost"], 3000)
        self.assertEqual(latest_9922["name"], "測試新進股")
        self.assertEqual(latest_9922["shares"], 500)
        self.assertIsNone(latest_9922["avg_cost"])

    # ---------- 2026-07-30：/mcp 合併路由（同process同埠8080共用）----------

    def test_mcp_post_dispatches_via_gateway(self):
        """證明合併後這條路真的通：POST /mcp 打一個不需要額外資料的工具
        （list_stances），走的是 mcp_http_gateway.handle_mcp_post()，回應
        格式跟該模組獨立執行時完全一致（同一段邏輯，只是換了個process掛載
        位置）。"""
        status, headers, body = self._rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "list_stances", "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        resp = json.loads(body.decode("utf-8"))
        self.assertEqual(resp["id"], 1)
        self.assertFalse(resp["result"]["isError"])

    def test_mcp_post_tools_list_includes_known_tool(self):
        status, _, body = self._rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(status, 200)
        resp = json.loads(body.decode("utf-8"))
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("list_stances", names)

    def test_mcp_get_returns_405(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/mcp")
        self.assertEqual(ctx.exception.code, 405)

    # ---------- 2026-07-30：/mcp/<token> URL路徑密鑰驗證（手機Claude App用）----------
    # 動機：Claude App「Custom Connectors via Remote MCP」設定UI只有OAuth
    # 一個驗證選項，沒有自訂header欄位可填Authorization Bearer，因此另開
    # 一條把密鑰放進URL路徑本身的路由。密鑰驗證邏輯（fail-closed等）已在
    # test_mcp_http_gateway.py的PathTokenMatchesTest涵蓋，這裡只驗證
    # report_server.py路由層「接得對」：正確token通、錯誤/空token回通用
    # 404（不是401/403，見mcp_http_gateway.path_token_matches()docstring）。

    def _rpc_path(self, path, payload):
        """POST 到 /mcp/<token>（或 /mcp/ 空token）用：body是原始
        JSON-RPC訊息，跟既有self._rpc()（打/mcp）同樣的request風格。"""
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_mcp_path_token_post_with_correct_token_returns_200(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            status, headers, body = self._rpc_path(
                "/mcp/path-secret",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(status, 200)
            self.assertIn("application/json", headers["Content-Type"])
            resp = json.loads(body.decode("utf-8"))
            names = [t["name"] for t in resp["result"]["tools"]]
            self.assertIn("list_stances", names)

    def test_mcp_path_token_post_with_wrong_token_returns_404(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            status, _, _ = self._rpc_path(
                "/mcp/wrong-token",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(status, 404)

    def test_mcp_path_token_post_with_empty_token_returns_404(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            status, _, _ = self._rpc_path(
                "/mcp/",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(status, 404)

    def test_mcp_path_token_get_with_correct_token_returns_405(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get("/mcp/path-secret")
            self.assertEqual(ctx.exception.code, 405)

    def test_mcp_path_token_get_with_wrong_token_returns_404(self):
        with unittest.mock.patch.dict(os.environ, {"ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get("/mcp/wrong-token")
            self.assertEqual(ctx.exception.code, 404)


class DashboardBasicAuthTest(unittest.TestCase):
    """Dashboard HTTP Basic Auth 測試（2026-07-30）：獨立server（不共用
    ReportServerTest的class-level server），因為要動態切換
    ALPHAVIBE_DASHBOARD_TOKEN環境變數，不想跟其他測試的既有假設
    （多數都沒帶Authorization header）互相干擾。見 report_server.py
    模組docstring最後一段與 `_dashboard_auth_ok()`。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="alphavibe-rsrv-auth-test-")
        report_server.ReportHandler.data_dir = cls.tmp
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), report_server.ReportHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def _get_raw(self, path, headers=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def _basic_header(self, password, user="alphavibe"):
        raw = ("%s:%s" % (user, password)).encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

    def test_no_token_configured_allows_unauthenticated_access(self):
        """fail-open預設：未設定ALPHAVIBE_DASHBOARD_TOKEN時，不帶任何
        header也要能正常存取——證明這次改動不影響既有現況（458個既有
        測試都沒有帶Basic Auth header）。"""
        self.assertNotIn("ALPHAVIBE_DASHBOARD_TOKEN", os.environ)
        status, _, body = self._get_raw("/")
        self.assertEqual(status, 200)
        self.assertIn("AlphaVibe 儀表板", body.decode("utf-8"))

    def test_token_configured_rejects_missing_auth_header(self):
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status, headers, _ = self._get_raw("/")
            self.assertEqual(status, 401)
            self.assertIn("Basic", headers["WWW-Authenticate"])
            self.assertIn('realm="AlphaVibe"', headers["WWW-Authenticate"])

    def test_token_configured_accepts_correct_password(self):
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status, _, body = self._get_raw(
                "/", headers=self._basic_header("secret-pw"))
            self.assertEqual(status, 200)
            self.assertIn("AlphaVibe 儀表板", body.decode("utf-8"))

    def test_token_configured_rejects_wrong_password(self):
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status, headers, _ = self._get_raw(
                "/", headers=self._basic_header("wrong-pw"))
            self.assertEqual(status, 401)
            self.assertIn("Basic", headers["WWW-Authenticate"])

    def test_token_configured_rejects_post_without_auth_and_no_side_effect(self):
        """POST路由同樣要被擋，且擋下來時不能有任何寫入副作用（驗證發生
        在body/表單處理之前）。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            url = "http://127.0.0.1:%d/dashboard/watchlist" % self.port
            data = urllib.parse.urlencode({"code": "T9999"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    status = resp.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            self.assertEqual(status, 401)

        store = KBStore(self.tmp)
        latest = store.get_latest_stance("T9999")
        store.close()
        self.assertIsNone(latest)  # 401時沒有真的處理表單、沒有寫入

    def test_token_configured_does_not_affect_mcp_route(self):
        """/mcp 有自己獨立的header-token驗證（ALPHAVIBE_MCP_TOKEN，跟
        ALPHAVIBE_DASHBOARD_TOKEN是不同環境變數）；同時設定兩者時，
        /mcp仍照自己既有規則走，不會被dashboard Basic Auth攔截（回歸
        測試，證明例外規則生效）。"""
        with unittest.mock.patch.dict(os.environ, {
                "ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw",
                "ALPHAVIBE_MCP_TOKEN": "mcp-secret"}):
            url = "http://127.0.0.1:%d/mcp" % self.port
            data = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer mcp-secret"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = resp.read()
            self.assertEqual(status, 200)
            resp_json = json.loads(body.decode("utf-8"))
            names = [t["name"] for t in resp_json["result"]["tools"]]
            self.assertIn("list_stances", names)

    def test_token_configured_does_not_affect_mcp_path_token_route(self):
        """/mcp/<token> 路徑密鑰驗證同樣不受dashboard Basic Auth影響——
        不帶Authorization header，只靠正確的URL路徑密鑰就要能打通（這正是
        這條路由存在的理由：Claude App無法處理Basic Auth彈窗）。"""
        with unittest.mock.patch.dict(os.environ, {
                "ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw",
                "ALPHAVIBE_MCP_TOKEN": "path-secret"}):
            url = "http://127.0.0.1:%d/mcp/path-secret" % self.port
            data = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = resp.read()
            self.assertEqual(status, 200)
            resp_json = json.loads(body.decode("utf-8"))
            names = [t["name"] for t in resp_json["result"]["tools"]]
            self.assertIn("list_stances", names)

    @staticmethod
    def _extract_cookie_value(set_cookie_header):
        """從 `Set-Cookie: alphavibe_session=<value>; Max-Age=...; ...`
        取出 `alphavibe_session=<value>` 這段（下一個請求要帶的
        `Cookie:` header值）。"""
        first_attr = set_cookie_header.split(";", 1)[0].strip()
        return first_attr

    def test_correct_basic_auth_sets_session_cookie(self):
        """密碼正確的Basic Auth請求，回應要帶Set-Cookie: alphavibe_session=
        ...（2026-07-30新增的長效cookie輔助路徑，見report_server.py模組
        docstring）。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status, headers, _ = self._get_raw(
                "/", headers=self._basic_header("secret-pw"))
            self.assertEqual(status, 200)
            set_cookie = headers.get("Set-Cookie")
            self.assertIsNotNone(set_cookie)
            self.assertTrue(set_cookie.startswith("alphavibe_session="))
            self.assertIn("Max-Age=2592000", set_cookie)
            self.assertIn("HttpOnly", set_cookie)
            self.assertIn("Secure", set_cookie)
            self.assertIn("SameSite=Lax", set_cookie)
            self.assertIn("Path=/", set_cookie)

    def test_cookie_alone_authenticates_next_request(self):
        """第一個請求靠Basic Auth拿到cookie後，下一個請求只帶這個cookie
        （不帶Basic Auth header）也要能通過驗證。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status1, headers1, _ = self._get_raw(
                "/", headers=self._basic_header("secret-pw"))
            self.assertEqual(status1, 200)
            cookie_value = self._extract_cookie_value(headers1["Set-Cookie"])

            status2, headers2, body2 = self._get_raw(
                "/", headers={"Cookie": cookie_value})
            self.assertEqual(status2, 200)
            self.assertIn("AlphaVibe 儀表板", body2.decode("utf-8"))
            # 已經是靠cookie過的，不需要重新設一次。
            self.assertIsNone(headers2.get("Set-Cookie"))

    def test_tampered_cookie_signature_rejected(self):
        """簽章被竄改過的cookie要驗證失敗（401），跟完全沒帶憑證一樣。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status1, headers1, _ = self._get_raw(
                "/", headers=self._basic_header("secret-pw"))
            self.assertEqual(status1, 200)
            cookie_value = self._extract_cookie_value(headers1["Set-Cookie"])
            name, _, value = cookie_value.partition("=")
            expiry_str, _, signature = value.partition(".")
            tampered_signature = ("0" if signature[0] != "0" else "1") + signature[1:]
            tampered_cookie = "%s=%s.%s" % (name, expiry_str, tampered_signature)

            status2, _, _ = self._get_raw(
                "/", headers={"Cookie": tampered_cookie})
            self.assertEqual(status2, 401)

    def test_expired_cookie_rejected(self):
        """expiry_ts設在過去的cookie（用正確密鑰簽出來的，模擬30天後的
        情況）要驗證失敗（401）。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            expired_ts = int(time.time()) - 3600
            signature = report_server._sign_dashboard_cookie(expired_ts)
            expired_cookie = "alphavibe_session=%d.%s" % (expired_ts, signature)

            status, _, _ = self._get_raw(
                "/", headers={"Cookie": expired_cookie})
            self.assertEqual(status, 401)

    def test_no_credentials_at_all_still_rejected(self):
        """完全不帶任何憑證（沒有Basic Auth也沒有cookie）→401，跟改動前
        行為一致（回歸測試，對照既有的
        test_token_configured_rejects_missing_auth_header）。"""
        with unittest.mock.patch.dict(
                os.environ, {"ALPHAVIBE_DASHBOARD_TOKEN": "secret-pw"}):
            status, headers, _ = self._get_raw("/")
            self.assertEqual(status, 401)
            self.assertIn("Basic", headers["WWW-Authenticate"])


class StaticIconTest(unittest.TestCase):
    def test_static_mode_writes_icon(self):
        tmp = tempfile.mkdtemp(prefix="alphavibe-static-icon-")
        try:
            out = os.path.join(tmp, "report.html")
            self.assertEqual(report.main(["--data-dir", tmp, "--out", out]), 0)
            icon = os.path.join(tmp, "apple-touch-icon.png")
            self.assertTrue(os.path.exists(icon))
            with open(icon, "rb") as fh:
                self.assertTrue(fh.read(8) == b"\x89PNG\r\n\x1a\n")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
