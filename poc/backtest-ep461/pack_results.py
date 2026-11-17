#!/usr/bin/env python3
"""把要貼回對話的結果打包成一段文字（只含彙總，不含原始價格、不含 token）。

用法（Mac）：python3 pack_results.py | pbcopy      然後在對話裡貼上。
也會存 out/paste_back.txt。
"""
import json
import os
import sys

import common as C


def _read(name):
    path = os.path.join(C.OUT_DIR, name)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return "（沒有 %s）" % name


def _probe_text():
    path = os.path.join(C.DATA_DIR, "probe.json")
    if not os.path.isfile(path):
        return "（沒有 probe.json）"
    res = json.load(open(path, encoding="utf-8"))["results"]
    out = []
    for r in res:
        out.append("%s / %s / %s~%s → %s rows=%d %s\n  欄位：%s\n  範例：%s" % (
            r["dataset"], r["stock_id"], r["range"][0], r["range"][1], r["status"], r["rows"], r["msg"],
            ", ".join(r["fields"]), json.dumps(r["sample"][:1], ensure_ascii=False)))
    return "\n".join(out)


def _status_text():
    lines = []
    for ds in [C.PRICE_DATASET] + C.EVENT_DATASETS:
        for sid in C.SYMBOLS:
            p = C.raw_path(ds, sid)
            if os.path.isfile(p):
                m = C.read_json(p).get("meta", {})
                lines.append("%s %s %s %s rows=%s %s~%s" % (ds.replace("TaiwanStock", ""), sid, m.get("status"),
                             m.get("msg", ""), m.get("rows"), m.get("first_date"), m.get("last_date")))
            else:
                lines.append("%s %s 未下載" % (ds.replace("TaiwanStock", ""), sid))
    return "\n".join(lines)


RESULT_REF = "refs/heads/function/backtest-ep461-results"


def publish(path, remote="origin", cwd=None):
    """把 paste_back.txt 單檔推到獨立結果分支（不動工作目錄、不動 function/backtest-ep461）。
    只推彙總文字：沒有原始價格、沒有 token。需要這台機器已能 git push（已設定 user.name/email）。"""
    import subprocess

    def git(*args, **kw):
        return subprocess.run(["git"] + list(args), cwd=cwd or C.HERE, check=True,
                              capture_output=True, text=True, **kw).stdout.strip()
    blob = git("hash-object", "-w", path)
    tree = git("mktree", input="100644 blob %s\tpaste_back.txt\n" % blob)
    commit = git("commit-tree", tree, "-m", "backtest-ep461 results %s" % C.today_str())
    git("push", "--force", remote, "%s:%s" % (commit, RESULT_REF))
    return commit


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parts =["## 回貼：EP461 回測結果（%s）" % C.today_str(),
             "### 欄位確認（probe）", _probe_text(),
             "### 下載狀態", _status_text(),
             "### 0050 回歸驗證", _read("regression_0050.txt"),
             "### 回測 summary", _read("summary.md")]
    text = "\n\n".join(parts) + "\n"
    os.makedirs(C.OUT_DIR, exist_ok=True)
    with open(os.path.join(C.OUT_DIR, "paste_back.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    if "--publish" in argv:
        try:
            c = publish(os.path.join(C.OUT_DIR, "paste_back.txt"))
            sys.stderr.write("已推到 origin 的 function/backtest-ep461-results（%s）。不用貼，直接告訴 Claude「跑完了」。\n" % c[:8])
        except Exception as exc:
            sys.stderr.write("推送失敗（%s）。改用：python3 pack_results.py | pbcopy 再貼回對話。\n" % exc)
        return
    sys.stdout.write(text)
    sys.stderr.write("（共 %d 字元；已另存 out/paste_back.txt）\n" % len(text))


if __name__ == "__main__":
    main()
