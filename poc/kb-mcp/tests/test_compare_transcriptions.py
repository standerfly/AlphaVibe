"""compare_transcriptions 測試（010 方案 D vs C 比對）：全用 tempfile 假資料，不連網、不碰真實資料。"""
import contextlib
import datetime
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import compare_transcriptions as ct  # noqa: E402
import paddle_eval as pe  # noqa: E402

TITLE = "這是一個絕對不能出現在輸出裡的文章標題"
FULLTEXT = "獨一無二的轉寫全文片段ZZZ"


def tbl(rows):
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


BASE = [["項目", "2023", "2024"],
        ["營收", "24,417.0", "30,000"],
        ["毛利率", "20.8%", "21.5%"],
        ["淨利", "(1,234)", "5,678"]]


def c_result(text, status="transcribed", reason=None, low=None, mode="ocr_grid"):
    r = {"status": status, "is_table": True, "text": text, "model": "paddleocr-9.9/server/%s" % mode,
         "reason": reason, "abort": False, "retryable": False, "detail": None,
         "meta": {"mode": mode, "tiles": 1, "elapsed": 1.0, "low_confidence": low or [], "warnings": []}}
    return r


def c_report(entries, modes=("ocr_grid",)):
    """entries: [(label, path, size, {mode: result})] → 以真正的 paddle_eval.build_report 產生，確保格式吻合。"""
    rows = [{"label": l, "path": p, "size": s, "results": res} for (l, p, s, res) in entries]
    return pe.build_report(rows, list(modes), "引擎 paddleocr-9.9／server；mode=%s" % "+".join(modes), "2026-11-18 09:00:00")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.out = os.path.join(self.d, "out")
        self.now = lambda: datetime.datetime(2026, 11, 18, 9, 30, 5)

    def path(self, *p):
        return os.path.join(self.d, *p)

    def write(self, name, content, binary=False):
        p = self.path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
        return p

    def make_d(self, texts, sizes=None, folder="d"):
        """texts: {image_id: text}；圖路徑 /imgs/img<id>.png。回傳 results.json 路徑。"""
        items, results = [], []
        for iid, text in texts.items():
            w, h = (sizes or {}).get(iid, (100, 80))
            items.append({"image_id": iid, "path": "/imgs/img%d.png" % iid, "sha256": "a" * 64, "width": w, "height": h})
            results.append({"image_id": iid, "sha256": "a" * 64, "is_table": True, "text": text})
        self.write(folder + "/manifest.json", {"version": 1, "items": items})
        return self.write(folder + "/results.json", {"version": 1, "model": "manual:test", "results": results})

    def make_c(self, texts, name="paddle-eval-1.md", modes=("ocr_grid",), statuses=None):
        entries = []
        for iid, text in texts.items():
            res = {}
            for m in modes:
                st = (statuses or {}).get(iid)
                res[m] = (c_result(text, mode=m) if st is None else
                          {"status": "untranscribed", "is_table": None, "text": "", "model": "x", "reason": st, "abort": False,
                           "retryable": False, "detail": None, "meta": {"elapsed": 0.1}})
            entries.append(("img%d.png" % iid, "/imgs/img%d.png" % iid, (100, 80), res))
        return self.write(name, c_report(entries, modes))

    def run_cli(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = ct.run(list(argv), now=self.now)
        return code, buf.getvalue(), err.getvalue()

    def report(self):
        names = sorted(n for n in os.listdir(self.out) if n.startswith("compare-"))
        with open(os.path.join(self.out, names[-1]), encoding="utf-8") as f:
            return f.read()


class ParseTest(unittest.TestCase):
    def test_basic_table(self):
        g = ct.parse_markdown(tbl(BASE))
        self.assertEqual((g["nrows"], g["ncols"], g["blocks"]), (4, 3, 1))
        self.assertEqual(g["rows"][1], ["營收", "24,417.0", "30,000"])

    def test_missing_separator_and_ragged(self):
        g = ct.parse_markdown("| a | b | c |\n| 1 | 2 |\n| 3 | 4 | 5 | 6 |")
        self.assertEqual((g["nrows"], g["ncols"]), (3, 4))
        self.assertTrue(g["ragged"])
        self.assertEqual(g["rows"][1], ["1", "2", "", ""])

    def test_escaped_pipe_and_no_outer_pipes(self):
        g = ct.parse_markdown("a \\| b | c | d\n1 | 2 | 3")
        self.assertEqual(g["rows"][0], ["a | b", "c", "d"])
        self.assertEqual(g["ncols"], 3)

    def test_text_lines_and_blocks(self):
        g = ct.parse_markdown("標題一行\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n說明\n\n| c |\n| 9 |")
        self.assertEqual(g["text_lines"], ["標題一行", "說明"])
        self.assertEqual(g["blocks"], 2)
        self.assertEqual(g["nrows"], 4)

    def test_lowconf_and_spaces(self):
        g = ct.parse_markdown("|  a   b  |  [?]  | ? |\n| --- | --- | --- |")
        self.assertEqual(g["rows"][0][0], "a b")
        self.assertTrue(ct.is_lowconf_cell(g["rows"][0][1]))
        self.assertTrue(ct.is_lowconf_cell(g["rows"][0][2]))
        self.assertFalse(ct.is_lowconf_cell("12?"))
        self.assertEqual(ct.parse_markdown("")["nrows"], 0)


class NumberTest(unittest.TestCase):
    def keys(self, s):
        return [t["key"] for t in ct.extract_numbers(s)[0]]

    def test_thousands_and_decimals(self):
        self.assertEqual(self.keys("24,417.0"), ["24417.0"])
        self.assertEqual(self.keys("24417"), ["24417"])        # 保留小數位：與上者 key 不同
        self.assertEqual(self.keys("1,234,567"), ["1234567"])

    def test_percent_and_paren_negative(self):
        self.assertEqual(self.keys("20.8%"), ["20.8"])
        self.assertEqual(self.keys("(1,234)"), ["-1234"])
        self.assertEqual(self.keys("(12.5%)"), ["-12.5"])
        self.assertEqual(self.keys("-1,234"), ["-1234"])

    def test_fullwidth_and_minus_variants(self):
        self.assertEqual(self.keys("１，２３４．５"), ["1234.5"])
        self.assertEqual(self.keys("−5"), ["-5"])
        self.assertEqual(self.keys("－5"), ["-5"])
        self.assertEqual(self.keys("（１２）"), ["-12"])
        self.assertEqual(self.keys("２０．８％"), ["20.8"])

    def test_range_and_chinese_adjacent(self):
        self.assertEqual(self.keys("10-20"), ["10", "20"])         # 範圍不是負數
        self.assertEqual(self.keys("營收24,417元"), ["24417"])
        self.assertEqual(self.keys("2025-12"), ["2025", "12"])

    def test_malformed(self):
        t = ct.extract_numbers("24.417.0")[0][0]
        self.assertTrue(t["malformed"])
        self.assertEqual(t["digits"], "244170")

    def test_residue(self):
        self.assertEqual(ct.extract_numbers("營收 24,417 億")[1], "營收 億")


def tk(s, pos=(1, 1)):
    t = ct.extract_numbers(s)[0][0]
    t["pos"] = pos
    return t


class PairTest(unittest.TestCase):
    def levels(self, d, c):
        r = ct.compare_tokens([tk(d)], [tk(c)])
        return [(x["level"], x["reason"]) for x in r["suspects"]], r

    def test_decimal_misplaced_high(self):
        lv, _ = self.levels("24,417.0", "24.417.0")
        self.assertEqual(lv[0][0], ct.LEVEL_HIGH)
        self.assertIn("錯置", lv[0][1])

    def test_percent_magnitude_high(self):
        lv, _ = self.levels("20.8%", "208%")
        self.assertEqual(lv[0][0], ct.LEVEL_HIGH)

    def test_magnitude_trailing_zero_high(self):
        lv, _ = self.levels("24,417", "244,170")
        self.assertEqual(lv[0][0], ct.LEVEL_HIGH)
        self.assertIn("數量級", lv[0][1])

    def test_digit_dropped_medium(self):
        lv, _ = self.levels("1,234", "1,23")
        self.assertEqual(lv[0][0], ct.LEVEL_MID)
        self.assertIn("位數差 1", lv[0][1])

    def test_sign_lost_high(self):
        lv, _ = self.levels("(1,234)", "1,234")
        self.assertEqual(lv[0][0], ct.LEVEL_HIGH)
        self.assertIn("正負號", lv[0][1])

    def test_format_only_low(self):
        lv, _ = self.levels("24,417.0", "24417")
        self.assertEqual(lv[0][0], ct.LEVEL_LOW)

    def test_unrelated_not_paired(self):
        lv, r = self.levels("1,234", "9,876")
        self.assertEqual(lv, [])
        self.assertEqual((len(r["only_d"]), len(r["only_c"])), (1, 1))

    def test_multiset_and_duplicates(self):
        d = [tk("5", (1, 1)), tk("5", (2, 1)), tk("7", (3, 1))]
        c = [tk("5", (1, 1)), tk("7", (3, 1)), tk("7", (4, 1))]
        r = ct.compare_tokens(d, c)
        self.assertEqual(r["matched"], 2)  # 5×1、7×1
        self.assertEqual([t["key"] for t in r["only_d"]], ["5"])
        self.assertEqual([t["key"] for t in r["only_c"]], ["7"])

    def test_tolerance(self):
        r = ct.compare_tokens([tk("100.0")], [tk("100.5")], tol=0.01)
        self.assertEqual(r["tol_matched"], 1)
        self.assertEqual(r["only_d"], [])
        r0 = ct.compare_tokens([tk("100.0")], [tk("100.5")], tol=0)
        self.assertEqual(r0["tol_matched"], 0)


class CompareTextsTest(unittest.TestCase):
    def test_same_shape_cell_diffs(self):
        c = [r[:] for r in BASE]
        c[1][1] = "24.417.0"
        c[2][2] = "215%"
        r = ct.compare_texts(tbl(BASE), tbl(c))
        self.assertEqual(r["mode"], "cell")
        got = sorted((x["pos_d"], x["d"], x["c"]) for x in r["num_diffs"])
        self.assertEqual(got, [((2, 2), "24,417.0", "24.417.0"), ((3, 3), "21.5%", "215%")])
        self.assertEqual(len([s for s in r["tokens"]["suspects"] if s["level"] == ct.LEVEL_HIGH]), 2)

    def test_identical(self):
        r = ct.compare_texts(tbl(BASE), tbl(BASE))
        self.assertEqual((r["num_diffs"], r["text_diffs"], r["tokens"]["suspects"]), ([], [], []))

    def test_text_diff_low_priority_and_normalize(self):
        c = [r[:] for r in BASE]
        c[1][0] = "营收"          # 簡體
        c[3][0] = "淨 利"          # 空白
        r = ct.compare_texts(tbl(BASE), tbl(c))
        self.assertEqual(len(r["text_diffs"]), 2)
        self.assertEqual(r["num_diffs"], [])
        r2 = ct.compare_texts(tbl(BASE), tbl(c), normalize_text=True)
        self.assertEqual(r2["text_diffs"], [])

    def test_different_shape_header_alignment(self):
        c = [["項目", "2023", "2024", "備註"], ["營收", "24,417.0", "30,000", "-"], ["淨利", "(1,234)", "5,687", "-"]]
        r = ct.compare_texts(tbl(BASE), tbl(c))
        self.assertEqual(r["mode"], "header")
        self.assertEqual([(x["d"], x["c"]) for x in r["num_diffs"]], [("5,678", "5,687")])
        mids = [s for s in r["tokens"]["suspects"] if s["level"] == ct.LEVEL_MID]
        self.assertEqual(len(mids), 1)                       # 位置不同也要在集合層被抓到

    def test_different_shape_unalignable_degrades(self):
        c = [["甲", "乙"], ["丙", "24,417.0"]]
        r = ct.compare_texts(tbl(BASE), tbl(c))
        self.assertEqual(r["mode"], "set")
        self.assertIn("對不上", r["note"])
        self.assertEqual(r["num_diffs"], [])
        self.assertTrue(r["tokens"]["only_d"])               # 其餘數字仍有集合比對

    def test_one_side_empty(self):
        r = ct.compare_texts(tbl(BASE), "")
        self.assertEqual(r["mode"], "set")
        self.assertGreater(len(r["tokens"]["only_d"]), 0)

    def test_lowconf_counts(self):
        c = [r[:] for r in BASE]
        c[1][1] = "[?]"
        d = [r[:] for r in BASE]
        d[3][2] = "?"
        r = ct.compare_texts(tbl(d), tbl(c))
        self.assertEqual(r["d_low"], [(4, 3)])
        self.assertEqual(r["c_low"], [(2, 2)])
        self.assertTrue(all(x["lowconf"] for x in r["num_diffs"]))


class ParseCReportTest(Base):
    def test_roundtrip_with_paddle_eval_format(self):
        p = self.make_c({1: tbl(BASE), 2: tbl(BASE)}, modes=("ocr_grid", "table_pipeline"))
        srcs = ct.build_c_sources([p])
        self.assertEqual([s["id"] for s in srcs], ["C1", "C2"])
        self.assertIn("table_pipeline", srcs[1]["label"])
        sec = srcs[0]["sections"][0]
        self.assertEqual(sec["path"], "/imgs/img1.png")
        self.assertEqual(sec["size"], (100, 80))
        self.assertEqual(sec["data"]["status"], "transcribed")
        self.assertEqual(ct.parse_markdown(sec["data"]["text"])["nrows"], 4)
        self.assertEqual(sec["data"]["low_count"], 0)

    def test_failed_section_status(self):
        p = self.make_c({1: tbl(BASE)}, statuses={1: "no_text_detected"})
        sec = ct.build_c_sources([p])[0]["sections"][0]
        self.assertEqual(sec["data"]["status"], "untranscribed")
        self.assertEqual(sec["data"]["reason"], "no_text_detected")


class CliTest(Base):
    def test_basic_run_and_report(self):
        c = [r[:] for r in BASE]
        c[1][1] = "24.417.0"
        dres = self.make_d({1: tbl(BASE), 2: tbl(BASE)})
        cr = self.make_c({1: tbl(c), 2: tbl(BASE)})
        code, out, err = self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)
        self.assertEqual(code, 0, err)
        rep = self.report()
        self.assertIn("## 總結", rep)
        self.assertIn("兩邊一致不代表一定正確", rep)
        self.assertIn("建議優先核對的圖", rep)
        self.assertIn("## 如何核對", rep)
        self.assertIn("24.417.0", rep)
        self.assertIn("img1.png", rep)
        # 排序：有差異的圖 1 排在建議清單第 1
        self.assertIn("1. C1｜img1.png", rep)
        self.assertNotIn("2. C1｜img2.png", rep)
        self.assertIn("高 1", out)

    def test_multiple_c_reports(self):
        dres = self.make_d({1: tbl(BASE)})
        c2 = [r[:] for r in BASE]
        c2[3][2] = "5,67"
        a = self.make_c({1: tbl(BASE)}, name="paddle-eval-a.md")
        b = self.make_c({1: tbl(c2)}, name="paddle-eval-b.md")
        code, out, err = self.run_cli("--d-results", dres, "--c-report", a, "--c-report", b, "--out", self.out)
        self.assertEqual(code, 0, err)
        rep = self.report()
        self.assertIn("C1：paddle-eval-a.md", rep)
        self.assertIn("C2：paddle-eval-b.md", rep)
        self.assertIn("位數差 1", rep)

    def test_unmatched_images(self):
        dres = self.make_d({1: tbl(BASE), 2: tbl(BASE)})
        # manifest 多一筆沒結果、results 多一筆不在 manifest
        with open(self.path("d/manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        man["items"].append({"image_id": 9, "path": "/imgs/img9.png", "sha256": "a" * 64, "width": 1, "height": 1})
        man["items"] = [i for i in man["items"] if i["image_id"] != 2]
        self.write("d/manifest.json", man)
        cr = self.make_c({1: tbl(BASE), 7: tbl(BASE)})        # C 有 7、沒有 D 的 2
        code, out, err = self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)
        self.assertEqual(code, 0, err)
        rep = self.report()
        un = rep.split("## 未配對")[1].split("## 逐張詳細")[0]
        self.assertIn("不在 manifest", un)
        self.assertIn("9", un)
        self.assertIn("img7.png", un)

    def test_c_failed_section_reported(self):
        dres = self.make_d({1: tbl(BASE)})
        cr = self.make_c({1: tbl(BASE)}, statuses={1: "no_text_detected"})
        code, out, err = self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)
        self.assertEqual(code, 0, err)
        self.assertIn("C 轉寫失敗", self.report())

    def test_no_overwrite_same_second(self):
        dres = self.make_d({1: tbl(BASE)})
        cr = self.make_c({1: tbl(BASE)})
        for _ in range(3):
            self.assertEqual(self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)[0], 0)
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["compare-20261118-093005-2.md", "compare-20261118-093005-3.md", "compare-20261118-093005.md"])

    def test_explicit_manifest_path(self):
        dres = self.make_d({1: tbl(BASE)}, folder="d")
        os.rename(self.path("d/manifest.json"), self.path("elsewhere.json"))
        cr = self.make_c({1: tbl(BASE)})
        self.assertEqual(self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)[0], 2)
        self.assertEqual(self.run_cli("--d-results", dres, "--manifest", self.path("elsewhere.json"),
                                      "--c-report", cr, "--out", self.out)[0], 0)

    def test_errors_exit_2_without_traceback(self):
        dres = self.make_d({1: tbl(BASE)})
        cr = self.make_c({1: tbl(BASE)})
        bad = self.write("bad.json", "{ not json " + TITLE)
        a_file = self.write("afile", "x")
        notc = self.write("notc.md", "# 隨便\n沒有任何區段 " + TITLE)
        cases = [
            ["--d-results", bad, "--manifest", self.path("d/manifest.json"), "--c-report", cr, "--out", self.out],
            ["--d-results", self.path("nope.json"), "--c-report", cr, "--out", self.out],
            ["--d-results", dres, "--c-report", self.path("nope.md"), "--out", self.out],
            ["--d-results", dres, "--c-report", cr, "--out", a_file],
            ["--d-results", dres, "--c-report", notc, "--out", self.out],
            ["--d-results", self.write("w.json", "[1,2]"), "--manifest", self.path("d/manifest.json"), "--c-report", cr, "--out", self.out],
            ["--d-results", dres, "--c-report", cr, "--out", self.out, "--numeric-tol", "-1"],
            ["--d-results", dres, "--out", self.out],                       # 缺 --c-report（argparse）
        ]
        for argv in cases:
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertNotIn("Traceback", out + err)
            self.assertNotIn(TITLE, out + err)
        self.assertFalse(os.path.exists(self.out))

    def test_stdout_has_no_title_or_fulltext_and_report_has_no_title(self):
        t1 = tbl(BASE) + "\n\n" + TITLE + " 2024\n"                     # 非表格文字行（含標題）
        d_rows = [r[:] for r in BASE]
        d_rows[1][0] = FULLTEXT
        dres = self.make_d({1: tbl(d_rows) + "\n\n" + TITLE + " 2024\n"})
        cr = self.make_c({1: t1})
        code, out, err = self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)
        self.assertEqual(code, 0, err)
        self.assertNotIn(TITLE, out + err)
        self.assertNotIn(FULLTEXT, out + err)
        rep = self.report()
        self.assertNotIn(TITLE, rep)
        self.assertIn(FULLTEXT[:10], rep)                                   # 文字差異表有轉寫片段

    def test_no_network(self):
        dres = self.make_d({1: tbl(BASE)})
        cr = self.make_c({1: tbl(BASE)})

        def boom(*a, **k):
            raise AssertionError("不得連網")
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            self.assertEqual(self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out)[0], 0)

    def test_numeric_tol_and_normalize_flags(self):
        c = [r[:] for r in BASE]
        c[1][2] = "30,100"
        dres = self.make_d({1: tbl(BASE)})
        cr = self.make_c({1: tbl(c)})
        self.assertEqual(self.run_cli("--d-results", dres, "--c-report", cr, "--out", self.out, "--numeric-tol", "0.01")[0], 0)
        rep = self.report()
        self.assertIn("容差內視為一致 1", rep)
        self.assertNotIn("**逐格數字差異**", rep)


class MainEntryTest(Base):
    def test_help_exit_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ct.run(["--help"]), 0)


if __name__ == "__main__":
    unittest.main()
