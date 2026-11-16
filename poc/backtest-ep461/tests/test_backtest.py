"""合成資料測試（不連網、不用真實資料）。執行：python3 -m unittest discover -s tests -v
真實資料的正確性由 regression_0050.py 用 0050 的 14 筆訊號另行驗證。"""
import datetime
import http.server
import io
import json
import os
import random
import sys
import tempfile
import threading
import unittest
import urllib.parse
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import b0_download as B0  # noqa: E402
import b1_adjust as B1  # noqa: E402
import b2_signals as B2  # noqa: E402
import b3_forward as B3  # noqa: E402
import common as C  # noqa: E402


def mk_rows(closes, vols=None, spread=1.0, start="2024-01-01"):
    d0 = datetime.date.fromisoformat(start)
    rows = []
    for i, c in enumerate(closes):
        rows.append({"date": (d0 + datetime.timedelta(days=i)).isoformat(), "open": c,
                     "high": c + spread / 2, "low": c - spread / 2, "close": float(c),
                     "volume": float(vols[i] if vols else 1000)})
    return rows


def base_series(extra_closes, extra_vols):
    closes = [100.0 if i % 2 == 0 else 100.5 for i in range(25)] + extra_closes
    vols = [1000.0] * 25 + extra_vols
    return mk_rows(closes, vols)


class AdjustTest(unittest.TestCase):
    def test_split_and_dividend(self):
        rows = mk_rows([100.0] * 10 + [24.5] * 10)
        ex_split = rows[10]["date"]
        events = [{"date": ex_split, "kind": "split", "before": 98.0, "after": 24.5},
                  {"date": rows[15]["date"], "kind": "dividend", "before": 24.5, "after": 24.0}]
        adj, applied, dropped = B1.apply_adjustments(rows, events)
        self.assertEqual(len(applied), 2)
        self.assertFalse(dropped)
        f_split, f_div = 24.5 / 98.0, 24.0 / 24.5
        self.assertAlmostEqual(adj[0]["close"], 100 * f_split * f_div, places=9)
        self.assertAlmostEqual(adj[10]["close"], 24.5 * f_div, places=9)
        self.assertAlmostEqual(adj[19]["close"], 24.5, places=9)
        self.assertAlmostEqual(adj[0]["volume"], 1000 / f_split, places=6)   # 分割：成交量放大
        self.assertAlmostEqual(adj[12]["volume"], 1000.0, places=6)          # 股利不動成交量

    def test_event_outside_range_and_bad_factor(self):
        rows = mk_rows([10.0] * 5)
        far = "2099-01-01"
        bad = {"date": rows[2]["date"], "kind": "dividend", "before": 10.0, "after": 1.0}
        adj, applied, dropped = B1.apply_adjustments(
            rows, [{"date": far, "kind": "split", "before": 10, "after": 2}, bad])
        self.assertEqual(applied, [])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(adj[0]["close"], 10.0)

    def test_manual_event_only_when_missing(self):
        d = tempfile.mkdtemp()
        C.RAW_DIR = os.path.join(d, "raw")
        ev = B1.load_events("0050")
        self.assertTrue(any(e.get("manual") for e in ev))
        C.write_json_atomic(C.raw_path(C.SPLIT_DATASET, "0050"), {"meta": {}, "data": [
            {"date": "2025-06-17", "stock_id": "0050", "before_price": 188.65, "after_price": 47.16}]})
        ev = B1.load_events("0050")
        self.assertFalse(any(e.get("manual") for e in ev))
        self.assertEqual(len(ev), 1)

    def test_missing_reference_field_fails_loudly(self):
        d = tempfile.mkdtemp()
        C.RAW_DIR = os.path.join(d, "raw")
        C.write_json_atomic(C.raw_path(C.DIVIDEND_DATASET, "2308"), {"meta": {}, "data": [
            {"date": "2024-07-01", "something_else": 1.0}]})
        with self.assertRaises(B1.DataError):
            B1.load_events("2308")


class SignalTest(unittest.TestCase):
    def test_breakout_held_and_shrink(self):
        rows = base_series([105.0] + [106.0] * 6, [2000.0] + [500.0] * 6)
        rows[25]["high"], rows[25]["low"] = 106.0, 100.0
        s = B2.c3_signals(rows)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["direction"], "breakout")
        self.assertAlmostEqual(s[0]["ratio"], 2.0)
        self.assertAlmostEqual(s[0]["pos"], 5 / 6.0)
        self.assertEqual(s[0]["state"], "held_shrink")
        self.assertAlmostEqual(s[0]["shrink_ratio"], 0.25)

    def test_breakout_held_not_shrunk(self):
        rows = base_series([105.0] + [106.0] * 6, [2000.0] + [1800.0] * 6)
        self.assertEqual(B2.c3_signals(rows)[0]["state"], "held_noshrink")

    def test_breakout_failed(self):
        rows = base_series([105.0, 106.0, 100.0, 106.0, 106.0, 106.0, 106.0], [2000.0] + [500.0] * 6)
        self.assertEqual(B2.c3_signals(rows)[0]["state"], "failed")

    def test_breakdown_failed_when_reclaimed(self):
        rows = base_series([95.0, 96.0, 101.0, 96.0, 96.0, 96.0, 96.0], [2000.0] + [500.0] * 6)
        s = B2.c3_signals(rows)
        self.assertEqual((s[0]["direction"], s[0]["state"]), ("breakdown", "failed"))

    def test_pending_when_not_enough_days(self):
        rows = base_series([105.0, 106.0, 106.0], [2000.0, 500.0, 500.0])
        self.assertEqual(B2.c3_signals(rows)[0]["state"], "pending")

    def test_low_volume_is_not_a_signal(self):
        rows = base_series([105.0] + [106.0] * 6, [1200.0] + [500.0] * 6)
        self.assertEqual(B2.c3_signals(rows), [])

    def test_cooldown(self):
        closes = [105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0, 114.0]
        vols = [3000.0, 3000.0, 3000.0, 3000.0, 3000.0, 3000.0, 3000.0, 3000.0, 3000.0, 3000.0]
        rows = base_series(closes, vols)
        got = B2.c3_signals(rows, cooldown=5)
        # vol 前 5 日均量會被放大，量比逐漸低於 1.5：只檢查冷卻讓相鄰日不會連續計入
        idxs = [s["idx"] for s in got]
        self.assertTrue(all(b - a >= 5 for a, b in zip(idxs, idxs[1:])))

    def test_c2_metrics(self):
        bench = [0.01, -0.02] * 30
        stock = [2 * b for b in bench]
        rets = [("d%d" % i, s, b) for i, (s, b) in enumerate(zip(stock, bench))]
        m = B2.c2_metrics(rets, 59, 60)
        self.assertAlmostEqual(m["up_capture"], 2.0)
        self.assertAlmostEqual(m["down_capture"], 2.0)
        self.assertAlmostEqual(m["resilience"], 0.0)
        self.assertEqual(B2.c2_bucket(m), "弱·不抗跌" if m["cum_rel"] <= 0 else "強·不抗跌")
        few = [("d%d" % i, 0.01, 0.01 if i else -0.01) for i in range(60)]
        m2 = B2.c2_metrics(few, 59, 60)
        self.assertIsNone(m2["down_capture"])  # 基準下跌日 < 8 天 → 樣本不足
        self.assertIsNone(B2.c2_bucket(m2))


class ForwardTest(unittest.TestCase):
    def test_fwd_and_excess(self):
        rows = mk_rows([100, 110, 121, 133.1, 146.41])
        bench = mk_rows([100, 100, 100, 100, 100])
        r, ex = B3.fwd(rows, 0, 2, B3.bench_map(bench))
        self.assertAlmostEqual(r, 0.21)
        self.assertAlmostEqual(ex, 0.21)
        self.assertIsNone(B3.fwd(rows, 3, 5, B3.bench_map(bench)))

    def test_entry_is_confirmation_day_not_signal_day(self):
        rows = base_series([105.0] + [106.0] * 12, [2000.0] + [500.0] * 12)
        s = B2.c3_signals(rows)
        B3.attach_forward(rows, s, B3.bench_map(rows), (5,), 5)
        self.assertEqual(s[0]["entry_date"], rows[25 + 5]["date"])
        self.assertAlmostEqual(s[0]["ret5"], rows[35]["close"] / rows[30]["close"] - 1)


class _Handler(http.server.BaseHTTPRequestHandler):
    log = []
    quota_after = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.log.append(q)
        if _Handler.quota_after is not None and len(_Handler.log) > _Handler.quota_after:
            body = {"msg": "Requests reach the upper limit", "status": 402}
        else:
            ds, sid = q["dataset"][0], q.get("data_id", [""])[0]
            if sid == "6826":
                rows = []
            elif ds == C.PRICE_DATASET:
                rows = [{"date": "2024-01-02", "stock_id": sid, "Trading_Volume": 1000, "open": 10, "max": 11,
                         "min": 9, "close": 10}]
            else:
                rows = [{"date": "2024-06-01", "stock_id": sid, "before_price": 10, "after_price": 9.5}]
            body = {"msg": "success", "status": 200, "data": rows}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        C.API_URL = "http://127.0.0.1:%d/" % self.srv.server_address[1]
        d = tempfile.mkdtemp()
        C.DATA_DIR, C.RAW_DIR = d, os.path.join(d, "raw")
        _Handler.log, _Handler.quota_after = [], None
        os.environ["FINMIND_TOKEN"] = "TESTTOKEN"
        B0._sleep = lambda s: None

    def tearDown(self):
        self.srv.shutdown()
        os.environ.pop("FINMIND_TOKEN", None)

    def run_dl(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = B0.main(["download", "--ignore-schedule-window", "--sleep", "0"] + list(extra))
        return code, buf.getvalue()

    def test_full_download_then_resume_skips_everything(self):
        code, out = self.run_dl("--only", "price")
        self.assertEqual(code, 0)
        self.assertEqual(len(_Handler.log), len(C.SYMBOLS))
        self.assertTrue(all(q["token"] == ["TESTTOKEN"] for q in _Handler.log))
        self.assertEqual(C.read_json(C.raw_path(C.PRICE_DATASET, "6826"))["meta"]["status"], "empty")
        _Handler.log.clear()
        code, out = self.run_dl("--only", "price")
        self.assertEqual((code, len(_Handler.log)), (0, 0))

    def test_quota_stops_and_resumes(self):
        _Handler.quota_after = 3
        code, out = self.run_dl()
        self.assertEqual(code, 2)
        self.assertIn("額度用完", out)
        saved = [s for s in C.SYMBOLS if os.path.isfile(C.raw_path(C.PRICE_DATASET, s))]
        self.assertEqual(len(saved), 3)
        _Handler.quota_after, _Handler.log = None, []
        code, _ = self.run_dl("--only", "price")
        self.assertEqual(code, 0)
        self.assertEqual(len(_Handler.log), len(C.SYMBOLS) - 3)  # 只補沒抓的

    def test_max_calls(self):
        code, out = self.run_dl("--max-calls", "2", "--only", "price")
        self.assertEqual((code, len(_Handler.log)), (2, 2))

    def test_refuses_without_token(self):
        os.environ.pop("FINMIND_TOKEN")
        old = C.read_token
        C.read_token = lambda f=None: ""
        try:
            code, out = self.run_dl()
        finally:
            C.read_token = old
        self.assertEqual(code, 3)
        self.assertEqual(len(_Handler.log), 0)

    def test_schedule_window(self):
        self.assertTrue(B0.in_schedule_window(datetime.datetime(2026, 11, 17, 2, 0)))
        self.assertFalse(B0.in_schedule_window(datetime.datetime(2026, 11, 17, 22, 30)))


def synth_raw(stock_id, days=600, seed=1, drift=0.0005):
    rnd = random.Random(seed)
    d = datetime.date(2022, 1, 3)
    px, rows = 100.0, []
    while len(rows) < days:
        if d.weekday() < 5:
            ret = rnd.gauss(drift, 0.015)
            o = px
            px = max(5.0, px * (1 + ret))
            hi, lo = max(o, px) * 1.005, min(o, px) * 0.995
            rows.append({"date": d.isoformat(), "stock_id": stock_id, "Trading_Volume": int(rnd.uniform(5e5, 2e6)),
                         "open": round(o, 2), "max": round(hi, 2), "min": round(lo, 2), "close": round(px, 2)})
        d += datetime.timedelta(days=1)
    return rows


class EndToEndTest(unittest.TestCase):
    def test_run_backtest_and_pack(self):
        import b6_report
        import pack_results
        import run_backtest
        d = tempfile.mkdtemp()
        C.DATA_DIR, C.RAW_DIR, C.OUT_DIR = d, os.path.join(d, "raw"), os.path.join(d, "out")
        for i, sid in enumerate([C.BENCH, "2308", "2337", "3131"]):
            C.write_json_atomic(C.raw_path(C.PRICE_DATASET, sid),
                                {"meta": {"status": "ok", "rows": 600}, "data": synth_raw(sid, seed=i + 1)})
        C.write_json_atomic(C.raw_path(C.PRICE_DATASET, "6826"), {"meta": {"status": "empty"}, "data": []})
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_backtest.main(["--symbols", "2308", "2337", "3131", "6826"])
        self.assertEqual(code, 0, buf.getvalue())
        for name in ("summary.md", "signals.csv", "group_all.csv", "sensitivity.csv", "manifest.json"):
            self.assertTrue(os.path.isfile(os.path.join(C.OUT_DIR, name)), name)
        summary = open(os.path.join(C.OUT_DIR, "summary.md"), encoding="utf-8").read()
        self.assertIn("6826", summary)
        self.assertIn("樣本不足", summary + buf.getvalue())
        # 重跑結果必須相同
        first = open(os.path.join(C.OUT_DIR, "signals.csv"), encoding="utf-8").read()
        with redirect_stdout(io.StringIO()):
            run_backtest.main(["--symbols", "2308", "2337", "3131", "6826"])
        self.assertEqual(first, open(os.path.join(C.OUT_DIR, "signals.csv"), encoding="utf-8").read())
        with redirect_stdout(io.StringIO()) as pb:
            pack_results.main()
        self.assertTrue(os.path.isfile(os.path.join(C.OUT_DIR, "paste_back.txt")))
        self.assertNotIn("TESTTOKEN", open(os.path.join(C.OUT_DIR, "paste_back.txt"), encoding="utf-8").read())

    def test_regression_script_without_data(self):
        import regression_0050
        d = tempfile.mkdtemp()
        C.DATA_DIR, C.RAW_DIR, C.OUT_DIR = d, os.path.join(d, "raw"), os.path.join(d, "out")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(regression_0050.main(), 3)

    def test_regression_compare_logic(self):
        import regression_0050 as R
        exact = [{"date": e[0], "direction": e[1], "ratio": e[2], "pos": e[3], "state": e[4]}
                 for e in R.EXPECTED]
        self.assertEqual(R.compare(exact), ([], [], []))
        exact[0] = dict(exact[0], ratio=9.0)
        missing, extra, diffs = R.compare(exact[1:] + [{"date": "2030-01-01", "direction": "breakout",
                                                         "ratio": 2, "pos": .5, "state": "failed"}])
        self.assertEqual(missing, ["2025-07-16"])
        self.assertEqual(extra, ["2030-01-01"])


if __name__ == "__main__":
    unittest.main()
