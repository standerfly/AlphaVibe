"""即時渲染的知識庫檢視 server（Part A 手機化，2026-07-10）。

取代 `python3 -m http.server 8080`：同一個 8080 埠（devtunnels 轉發網址
不變），但每次請求都即時讀 SQLite 重新渲染——iPhone 下拉重新整理永遠
看到最新資料，不必再手動跑 report.py。

純標準庫、Python 3.9 相容。sqlite 連線不可跨執行緒共用，因此每個請求
各自開一個 KBStore 連線（讀取量小，成本可忽略）。

用法：python3 poc/kb-mcp/report_server.py [--port 8080] [--data-dir DIR]
"""
import argparse
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frameworks  # noqa: E402
import market_scan  # noqa: E402
import report  # noqa: E402
import screener  # noqa: E402
from kb_store import KBStore  # noqa: E402

PAGE_PATHS = ("/", "/report.html", "/poc/data/report.html")  # 末項相容舊書籤


class ReportHandler(BaseHTTPRequestHandler):
    data_dir = None  # 由 main() 設定

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in PAGE_PATHS:
            store = KBStore(self.data_dir)
            try:
                page = report.render(store)
            finally:
                store.close()
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path.endswith("/apple-touch-icon.png") or path == "/apple-touch-icon.png":
            self._send(200, "image/png", report.make_icon_png())
        elif path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok")
        elif path == "/screen":
            self._send(200, "text/html; charset=utf-8",
                       report.render_screen_form().encode("utf-8"))
        elif path == "/market-scan":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = urllib.parse.parse_qs(query)
            framework_id = (params.get("framework") or [None])[0]
            if not framework_id or frameworks.get_framework(framework_id) is None:
                framework_id = frameworks.default_framework_id()
            store = KBStore(self.data_dir)
            try:
                latest = store.get_latest_market_scan(framework_id=framework_id)
            finally:
                store.close()
            page = report.render_market_scan_page(framework_id, latest)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8",
                       "404：檢視頁在 /（或 /report.html）".encode("utf-8"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/screen":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            codes_text = (form.get("codes") or [""])[0]
            codes = screener.parse_codes(codes_text)
            if not codes:
                page = report.render_screen_form(error="請至少輸入一個股票代碼")
                self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
                return
            result = screener.screen_stocks(codes, data_dir=self.data_dir)
            page = report.render_screen_results(result)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        if path == "/market-scan":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body.decode("utf-8"))
            framework_id = (form.get("framework") or [None])[0]
            if not framework_id or frameworks.get_framework(framework_id) is None:
                framework_id = frameworks.default_framework_id()
            result = market_scan.run_scan(
                framework_id, data_dir=self.data_dir, trigger_source="manual")
            store = KBStore(self.data_dir)
            try:
                if "error" not in result:
                    store.save_market_scan_run(
                        framework_id, "manual", result["results"],
                        result["candidate_count"],
                        market_errors=result["market_errors"])
                latest = store.get_latest_market_scan(framework_id=framework_id)
            finally:
                store.close()
            page = report.render_market_scan_page(
                framework_id, latest, error=result.get("error"))
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
            return
        self._send(404, "text/plain; charset=utf-8",
                   "404：僅支援 POST /screen 或 /market-scan".encode("utf-8"))

    def log_message(self, fmt, *args):  # 安靜一點，只留到 stderr
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main(argv=None):
    parser = argparse.ArgumentParser(description="即時渲染知識庫檢視 server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    ReportHandler.data_dir = os.path.abspath(
        args.data_dir or os.environ.get("ALPHAVIBE_DATA_DIR")
        or os.path.join(here, "..", "data"))

    server = ThreadingHTTPServer(("0.0.0.0", args.port), ReportHandler)
    print("檢視 server 啟動：http://localhost:%d/（資料目錄 %s）"
          % (server.server_address[1], ReportHandler.data_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
