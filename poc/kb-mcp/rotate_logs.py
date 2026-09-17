#!/usr/bin/env python3
"""AlphaVibe launchd 服務的 log 輪替（2026-09-17 架構體檢 B4）。

背景：6 個 launchd 服務的 log 完全沒有輪替機制，目前總量 1.6MB、單檔
最大 580KB，還不到緊急，但沒有上限就是會一直長。

**關鍵作法：copy-truncate，不是 move**。這些 log 正被 launchd 開著寫
（`StandardOutPath`／`StandardErrorPath` 是 launchd 自己持有的 file
handle），把檔案 mv 走的話 launchd 會繼續寫進那個已經改名的 inode，
新建的同名檔案永遠是空的，等於靜默失去所有 log。所以流程是：把內容
複製出去 → 用 truncate 清空原檔（inode 不變，launchd 的 handle 繼續
有效）。

代價：copy 與 truncate 之間如果剛好有新行寫入，那幾行會遺失。對這個
用途（個人服務的除錯 log）可以接受，換來的是不必停服務就能輪替。

用法：
    python3 poc/kb-mcp/rotate_logs.py                 # 用預設門檻
    python3 poc/kb-mcp/rotate_logs.py --max-bytes 1048576
    python3 poc/kb-mcp/rotate_logs.py --dry-run
"""
import argparse
import datetime
import glob
import gzip
import os
import shutil
import sys

DEFAULT_LOG_GLOB = os.path.expanduser("~/Library/Logs/alphavibe-*")
DEFAULT_MAX_BYTES = 5 * 1024 * 1024   # 單檔超過 5MB 才輪替
DEFAULT_KEEP = 5                      # 每個 log 保留幾份歷史


def _log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def _is_rotated(path):
    """輪替產生的歷史檔（.1.gz、.2.gz…）本身不該再被輪替。"""
    return path.endswith(".gz")


def rotate_one(path, keep=DEFAULT_KEEP, dry_run=False):
    """對單一 log 做 copy-truncate 輪替。回傳說明字串，沒做事回 None。"""
    size = os.path.getsize(path)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = "%s.%s.gz" % (path, stamp)
    if dry_run:
        return "(dry-run) %s（%.1f KB）→ %s" % (path, size / 1024.0, dest)

    with open(path, "rb") as fin, gzip.open(dest, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    # truncate 而非 unlink／rename：保住 inode，launchd 的 file handle
    # 繼續有效（見模組 docstring）
    with open(path, "r+b") as f:
        f.truncate(0)

    removed = prune_rotated(path, keep)
    detail = "%s（%.1f KB）→ %s" % (os.path.basename(path), size / 1024.0,
                                   os.path.basename(dest))
    if removed:
        detail += "，清掉 %d 份舊的" % removed
    return detail


def prune_rotated(path, keep):
    """只留最新 keep 份該 log 的歷史檔，回傳刪除數。"""
    olds = sorted(glob.glob(path + ".*.gz"), reverse=True)
    for old in olds[keep:]:
        os.unlink(old)
    return max(0, len(olds) - keep)


def main(argv=None):
    ap = argparse.ArgumentParser(description="AlphaVibe log 輪替")
    ap.add_argument("--glob", default=DEFAULT_LOG_GLOB)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    candidates = [p for p in sorted(glob.glob(args.glob))
                  if os.path.isfile(p) and not _is_rotated(p)]
    _log("檢查 %d 個 log（門檻 %.1f MB）%s"
         % (len(candidates), args.max_bytes / 1024.0 / 1024.0,
            "（dry-run）" if args.dry_run else ""))

    rotated = 0
    for path in candidates:
        try:
            if os.path.getsize(path) < args.max_bytes:
                continue
            detail = rotate_one(path, args.keep, args.dry_run)
            _log("  ✓ %s" % detail)
            rotated += 1
        except OSError as exc:
            _log("  ✗ %s 輪替失敗：%s" % (os.path.basename(path), exc))
    _log("完成，輪替 %d 個" % rotated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
