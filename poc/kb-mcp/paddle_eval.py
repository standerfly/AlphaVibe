#!/usr/bin/env python3
"""PaddleOCR 轉寫評估工具（010 方案 C）：對一批本機表格圖跑本機 PaddleOCR，輸出可與 Haiku／方案 D 並排比對的報告。

用法（在裝了 paddleocr 的獨立 venv 裡；步驟見 specs/010-investanchors-article-import/paddle-setup.md）：
    python3 poc/kb-mcp/paddle_eval.py <圖片資料夾或清單檔> [--out DIR] [--mode ocr_grid|table_pipeline|both]
        [--variant server|mobile] [--model-dir DIR] [--min-score 0.8] [--limit N] [--det-max-side 1280]
        [--allow-download] [--show-low-conf]

輸入（二擇一）：
  - 資料夾：掃描其中的 png／jpg／jpeg／webp／gif（依檔名排序）。
  - 清單檔：.json（list，或 {"images":[…]}；元素為路徑字串或 {path, article_id?, seq?}）、
    .md（`investanchors_import.py --transcribe-sample` 產生的報告：取其中每個「原圖：<路徑>」與前一個二級標題的
    article_id／seq，所以可直接拿同一批抽樣圖與 Haiku 的結果並排）、.txt（每行一個路徑）。
    清單裡的 title 等其他欄位一律忽略，**報告不含文章標題、內文**。

輸出：<out>/paddle-eval-<YYYYmmdd-HHMMSS>.md（預設 out＝目前目錄下的 paddle_eval_out/）。格式比照 transcribe-sample 報告：
每張一節（`## k. 標籤｜寬x高[｜長圖]`、`原圖：路徑`、`狀態：…`、轉寫 Markdown），另有每張耗時與平均、失敗數的總結。

全程本機、**不連網**：預設把 socket 對外連線全部擋掉（只放行本機迴路與 unix socket），並設離線環境變數；
只有明確加 `--allow-download` 才會解除（用來第一次下載模型）。不讀鑰匙圈、不碰資料庫、不連定錨。
退出碼：0 全部成功；1 有失敗；2 參數錯誤；3 引擎不可用（未安裝／缺模型）。
"""
import argparse
import datetime
import json
import os
import re
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_image_tiles  # noqa: E402
import article_transcribe_paddle as ap  # noqa: E402

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
DEFAULT_OUT = "paddle_eval_out"
_HEAD_RE = re.compile(r"^##\s+\d+\.\s+(article_id=[^\s｜]+)\s+(seq=[^\s｜]+)")
_SRC_RE = re.compile(r"^原圖：(.+?)\s*$")


# ── 不連網守衛 ───────────────────────────────────────────────────────────────────────
def install_network_guard():
    """擋掉所有對外連線（含 DNS、UDP）；允許 unix socket 與本機迴路。回傳還原函式（測試用）。

    注意：這只約束 Python 層；Paddle 的 C 層與子行程不受影響，真正的離線保證要靠 prepare_environment 設的
    HF_HUB_OFFLINE 等環境變數，本守衛只是輔助（見 paddle-setup.md）。"""
    S = socket.socket
    orig = {
        "connect": S.connect, "connect_ex": S.connect_ex, "sendto": S.sendto,
        "getaddrinfo": socket.getaddrinfo, "gethostbyname": socket.gethostbyname,
        "gethostbyname_ex": socket.gethostbyname_ex,
    }
    local_hosts = ("127.0.0.1", "::1", "localhost")

    def _is_local(address):
        if isinstance(address, (str, bytes)):          # unix socket 路徑
            return True
        host = address[0] if address else ""
        return host in local_hosts

    def _block(what):
        raise OSError("paddle_eval：離線模式，已阻擋%s（要下載模型請加 --allow-download）" % what)

    def guarded_connect(self, address):
        if not _is_local(address):
            _block("對外連線")
        return orig["connect"](self, address)

    def guarded_connect_ex(self, address):
        if not _is_local(address):
            _block("對外連線")
        return orig["connect_ex"](self, address)

    def guarded_sendto(self, data, *a):
        address = a[-1] if a else None
        if address is not None and not _is_local(address):
            _block("對外 UDP 傳送")
        return orig["sendto"](self, data, *a)

    def guarded_getaddrinfo(host, *a, **k):
        if host not in local_hosts and host is not None:
            _block(" DNS 查詢")
        return orig["getaddrinfo"](host, *a, **k)

    def guarded_gethostbyname(host):
        if host not in local_hosts:
            _block(" DNS 查詢")
        return orig["gethostbyname"](host)

    def guarded_gethostbyname_ex(host):
        if host not in local_hosts:
            _block(" DNS 查詢")
        return orig["gethostbyname_ex"](host)

    S.connect, S.connect_ex, S.sendto = guarded_connect, guarded_connect_ex, guarded_sendto
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname, socket.gethostbyname_ex = guarded_gethostbyname, guarded_gethostbyname_ex

    def restore():
        S.connect, S.connect_ex, S.sendto = orig["connect"], orig["connect_ex"], orig["sendto"]
        socket.getaddrinfo = orig["getaddrinfo"]
        socket.gethostbyname, socket.gethostbyname_ex = orig["gethostbyname"], orig["gethostbyname_ex"]
    return restore


# ── 輸入 ────────────────────────────────────────────────────────────────────────────
def load_inputs(src):
    """回傳 [{"path", "label"}]。label 只用 article_id／seq 或檔名，絕不含標題。"""
    if os.path.isdir(src):
        names = sorted(n for n in os.listdir(src) if n.lower().endswith(IMAGE_EXTS))
        return [{"path": os.path.join(src, n), "label": n} for n in names]
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    base = os.path.dirname(os.path.abspath(src))
    ext = os.path.splitext(src)[1].lower()
    items = []
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()
    if ext == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("images", [])
        if not isinstance(data, list):
            raise ValueError("清單格式不正確（需為陣列，或含 images 陣列的物件）")
        for e in data:
            if isinstance(e, str):
                items.append({"path": e, "label": os.path.basename(e)})
            elif isinstance(e, dict) and isinstance(e.get("path"), str) and e.get("path"):
                label = " ".join("%s=%s" % (k, e[k]) for k in ("article_id", "seq") if e.get(k) is not None)
                items.append({"path": e["path"], "label": label or os.path.basename(e["path"])})
    elif ext == ".md":
        pending = None
        for ln in text.splitlines():
            m = _HEAD_RE.match(ln)
            if m:
                pending = "%s %s" % (m.group(1), m.group(2))
                continue
            m = _SRC_RE.match(ln)
            if m:
                p = m.group(1)
                items.append({"path": p, "label": pending or os.path.basename(p)})
                pending = None
    else:
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                items.append({"path": ln, "label": os.path.basename(ln)})
    for it in items:
        if not os.path.isabs(it["path"]):
            it["path"] = os.path.join(base, it["path"])
    return items


# ── 報告 ────────────────────────────────────────────────────────────────────────────
def _fmt_size(path):
    try:
        with open(path, "rb") as f:
            size = article_image_tiles.image_size(f.read(2 * 1024 * 1024))   # 只讀檔頭，不整檔載入
    except OSError:
        return None
    return size


def build_report(rows, modes, args_desc, stamp):
    """rows: [{label, path, size, results:{mode: result}}]；回傳 Markdown 字串。"""
    lines = ["# PaddleOCR 轉寫評估（%s；本機、不寫資料庫、不含文章標題）" % args_desc, "",
             "產生時間：%s" % stamp, ""]
    # 總結
    lines.append("## 總結")
    lines.append("")
    lines.append("| 模式 | 張數 | 成功 | 失敗 | 平均耗時（秒） | 總耗時（秒） |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for mode in modes:
        res = [r["results"][mode] for r in rows if mode in r["results"]]
        ok = [x for x in res if x["status"] == "transcribed"]
        times = [x["meta"].get("elapsed") for x in res if x["meta"].get("elapsed") is not None]
        avg = "%.2f" % (sum(times) / len(times)) if times else "-"
        lines.append("| %s | %d | %d | %d | %s | %.2f |" % (mode, len(res), len(ok), len(res) - len(ok), avg,
                                                         sum(times) if times else 0.0))
    lines += ["", "| # | 圖 | 尺寸 | " + " | ".join("%s 耗時／狀態" % m for m in modes) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in modes) + " |"]
    for k, r in enumerate(rows, 1):
        cells = []
        for m in modes:
            x = r["results"].get(m)
            if x is None:
                cells.append("-")
            else:
                t = x["meta"].get("elapsed")
                cells.append("%s｜%s" % ("%.1fs" % t if t is not None else "-",
                                         x["status"] if x["status"] == "transcribed" else "untranscribed:%s" % x["reason"]))
        lines.append("| %d | %s | %s | %s |" % (k, r["label"], "%dx%d" % r["size"] if r["size"] else "?", " | ".join(cells)))
    lines.append("")
    # 逐張
    for k, r in enumerate(rows, 1):
        w, h = r["size"] or (0, 0)
        lines.append("## %d. %s｜%s%s" % (k, r["label"], "%dx%d" % (w, h) if r["size"] else "尺寸不明",
                                          "｜長圖" if r["size"] and article_image_tiles.is_long_image(w, h) else ""))
        lines.append("原圖：%s" % r["path"])
        lines.append("")
        for m in modes:
            x = r["results"].get(m)
            if x is None:
                continue
            meta = x["meta"]
            lines.append("### 模式 %s" % m)
            lines.append("")
            lines.append("狀態：%s%s" % (x["status"], "（%s）" % x["reason"] if x.get("reason") else ""))
            lines.append("耗時：%s 秒｜切片：%s｜引擎：%s" % (meta.get("elapsed", "-"), meta.get("tiles", "-"), x["model"]))
            if x.get("detail"):
                lines.append("說明：%s" % x["detail"])
            if meta.get("warnings"):
                lines.append("警告：%s" % "、".join(meta["warnings"]))
            lines.append("")
            if x["status"] == "transcribed":
                lines.append("is_table：%s" % x["is_table"])
                lines += ["", x["text"] or "", ""]
                low = meta.get("low_confidence") or []
                lines.append("低信心格（[?]）：%d 格" % len(low))
                if low and meta.get("_show_low"):
                    lines.append("")
                    lines += ["- 列 %s 欄 %s：引擎猜測「%s」（信心 %s）" % (
                        q.get("row"), q.get("col"), q.get("guess"), q.get("score")) for q in low]
                lines.append("")
    return "\n".join(lines)


# ── 主流程 ───────────────────────────────────────────────────────────────────────────
def build_parser():
    ap_ = argparse.ArgumentParser(description="PaddleOCR 表格轉寫評估（本機、離線；010 方案 C）")
    ap_.add_argument("source", help="圖片資料夾，或清單檔（.json／.md（transcribe-sample 報告）／.txt）")
    ap_.add_argument("--out", default=DEFAULT_OUT, help="輸出資料夾（預設 ./%s）" % DEFAULT_OUT)
    ap_.add_argument("--mode", choices=list(ap.MODES) + ["both"], default=ap.MODE_GRID)
    ap_.add_argument("--variant", choices=sorted(ap.OCR_MODELS), default=ap.DEFAULT_VARIANT)
    ap_.add_argument("--model-dir", default=None, help="本機模型根目錄（含 PP-OCRv5_*_det／rec 子資料夾）")
    ap_.add_argument("--min-score", type=float, default=ap.DEFAULT_MIN_SCORE)
    ap_.add_argument("--det-max-side", type=int, default=ap.DEFAULT_DET_MAX_SIDE)
    ap_.add_argument("--limit", type=int, default=None, help="只跑前 N 張")
    ap_.add_argument("--allow-download", action="store_true", help="允許連網下載模型（預設完全離線）")
    ap_.add_argument("--show-low-conf", action="store_true", help="報告列出低信心格的引擎猜測值（只在報告裡，不進轉寫文字）")
    ap_.add_argument("--enable-mkldnn", action="store_true", help="x86 上啟用 oneDNN（paddle 3.3.1 在 x86 會當掉，預設關）")
    return ap_


def run(argv=None, transcribe=None, now=None, say=print, guard=True):
    """transcribe(path, mode, **kw) → result dict（可注入，測試用）。回傳退出碼。"""
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        say("拒絕執行：--limit 必須 ≥ 1")
        return 2
    try:
        items = load_inputs(args.source)
    except (OSError, ValueError, RecursionError, TypeError, AttributeError) as e:
        say("讀取輸入失敗：%s" % type(e).__name__)
        return 2
    if not items:
        say("沒有可處理的圖片")
        return 2
    if args.limit:
        items = items[:args.limit]
    if guard and not args.allow_download:
        ap.prepare_environment(False)
        install_network_guard()
    elif args.allow_download:
        ap.prepare_environment(True)
    modes = list(ap.MODES) if args.mode == "both" else [args.mode]
    if transcribe is None:
        def transcribe(path, mode, **kw):
            return ap.transcribe_image_paddle(
                path, mode=mode, variant=args.variant, model_dir=args.model_dir,
                allow_download=args.allow_download, min_score=args.min_score,
                det_max_side=args.det_max_side, enable_mkldnn=args.enable_mkldnn)
    rows, aborted, failures = [], None, 0
    for it in items:
        row = {"label": it["label"], "path": it["path"], "size": _fmt_size(it["path"]), "results": {}}
        for mode in modes:
            if aborted:
                res = ap._fail("skipped_after_abort:%s" % aborted)
            else:
                try:
                    res = transcribe(it["path"], mode)
                except Exception as e:          # 評估工具不因單張失敗中止
                    res = ap._fail("exception:%s" % type(e).__name__, retryable=True)
                if res.get("abort"):
                    aborted = res.get("reason")
            res["meta"]["_show_low"] = bool(args.show_low_conf)
            if res["status"] != "transcribed":
                failures += 1
            row["results"][mode] = res
        rows.append(row)
    stamp_dt = (now or datetime.datetime.now)()
    stamp = stamp_dt.strftime("%Y%m%d-%H%M%S")
    desc = "引擎 %s／%s；mode=%s" % (ap.ENGINE_NAME, args.variant, "+".join(modes))
    try:
        os.makedirs(args.out, exist_ok=True)
        out_path, n = os.path.join(args.out, "paddle-eval-%s.md" % stamp), 1
        while True:                                   # 不覆寫既有報告：同一秒重跑加序號
            try:
                f = open(out_path, "x", encoding="utf-8")
                break
            except FileExistsError:
                n += 1
                out_path = os.path.join(args.out, "paddle-eval-%s-%d.md" % (stamp, n))
                if n > 1000:
                    raise
        with f:
            f.write(build_report(rows, modes, desc, stamp_dt.strftime("%Y-%m-%d %H:%M:%S")))
    except OSError as e:
        say("寫入報告失敗：%s" % type(e).__name__)
        return 2
    say("評估完成：%d 張 × %d 種模式，失敗 %d，報告 %s" % (len(rows), len(modes), failures, out_path))
    if aborted:
        say("引擎不可用（%s）。%s" % (aborted, ap.INSTALL_HINT if "install" in aborted else ap.MODEL_HINT))
        return 3
    return 1 if failures else 0


def main():
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
