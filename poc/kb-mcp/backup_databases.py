#!/usr/bin/env python3
"""正式資料庫每日備份（2026-09-17 架構體檢 A3）。

背景：在這之前正式庫完全沒有自動備份——6 個 launchd plist 與 crontab
都查過，現存的都是手動一次性快照。這跟 A2（寫入失敗留下髒資料）疊在
一起是複合風險：資料可能靜默損壞，而損壞後沒有回復手段。

用 sqlite3 的線上備份 API（`Connection.backup()`）而不是複製檔案：
正式服務隨時可能正在寫入，直接 `cp` 會拿到撕裂的資料庫（尤其 WAL
尚未 checkpoint 時）。備份 API 會取得一致的快照，不需要停掉服務。

備份完成後立刻 `PRAGMA integrity_check` 驗過才算數——沒驗過的備份
等於沒有備份，這是這支腳本最重要的一行。

用法：
    python3 poc/kb-mcp/backup_databases.py                # 用預設路徑
    python3 poc/kb-mcp/backup_databases.py --data-dir X --dest Y
    python3 poc/kb-mcp/backup_databases.py --dry-run      # 只印要做什麼
"""
import argparse
import datetime
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DEFAULT_DEST = os.path.expanduser("~/AlphaVibe-backups")

# 保留策略：每日備份留 30 份；每月 1 號那份另外收進 monthly/ 留 24 份。
# 資料庫現在約 7MB，gzip 後 1-2MB——30+24 份大約 80MB，個人機器可接受。
DAILY_KEEP = 30
MONTHLY_KEEP = 24

DATABASES = ("alphavibe.db", "us_stocks.db", "flights.db")
# 2026-09-24（007-trip-day-range quickstart.md 發現的缺口）：機票功能
# 2026-09-23 上線以來一直不在既有每日自動備份範圍。本次要對
# flights.db 做 schema 遷移，順手補上——低成本，直接保護這次異動。


def _log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def backup_one(src_path, dest_dir, stamp, dry_run=False):
    """備份單一資料庫，回傳 (成功?, 產出路徑或錯誤訊息)。"""
    name = os.path.basename(src_path)
    base = name[:-3] if name.endswith(".db") else name
    out_path = os.path.join(dest_dir, "%s-%s.db.gz" % (base, stamp))

    if not os.path.exists(src_path):
        return False, "來源不存在：%s" % src_path
    if dry_run:
        return True, "(dry-run) 會寫入 %s" % out_path

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="alphavibe-backup-")
    os.close(tmp_fd)
    try:
        # 線上備份：即使正式服務正在寫入也能取得一致快照
        src = sqlite3.connect("file:%s?mode=ro" % src_path, uri=True)
        try:
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        # 驗證：沒驗過的備份等於沒有備份
        check = sqlite3.connect(tmp_path)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if result != "ok":
            return False, "完整性檢查失敗（%s）：%s" % (name, result)

        with open(tmp_path, "rb") as fin, gzip.open(out_path, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        size_mb = os.path.getsize(out_path) / 1024.0 / 1024.0
        return True, "%s（%.2f MB，完整性 ok）" % (out_path, size_mb)
    except Exception as exc:
        return False, "%s 備份失敗：%s" % (name, exc)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def prune(dest_dir, prefix, keep, dry_run=False):
    """只刪這個 prefix 的備份，留最新 keep 份。回傳刪掉的檔名。"""
    if not os.path.isdir(dest_dir):
        return []
    files = sorted(
        (f for f in os.listdir(dest_dir)
         if f.startswith(prefix + "-") and f.endswith(".db.gz")),
        reverse=True,
    )
    removed = []
    for f in files[keep:]:
        if not dry_run:
            os.unlink(os.path.join(dest_dir, f))
        removed.append(f)
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description="AlphaVibe 正式資料庫每日備份")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    is_monthly = now.day == 1

    daily_dir = os.path.join(args.dest, "daily")
    monthly_dir = os.path.join(args.dest, "monthly")
    if not args.dry_run:
        os.makedirs(daily_dir, exist_ok=True)
        os.makedirs(monthly_dir, exist_ok=True)

    _log("開始備份：%s → %s%s" % (data_dir, args.dest, "（dry-run）" if args.dry_run else ""))

    failures = []
    for db_name in DATABASES:
        src_path = os.path.join(data_dir, db_name)
        ok, detail = backup_one(src_path, daily_dir, stamp, args.dry_run)
        if ok:
            _log("  ✓ %s" % detail)
            # 每月 1 號多留一份長期備份
            if is_monthly:
                m_ok, m_detail = backup_one(src_path, monthly_dir, stamp, args.dry_run)
                _log("  %s 月備份 %s" % ("✓" if m_ok else "✗", m_detail))
                if not m_ok:
                    failures.append(m_detail)
        else:
            _log("  ✗ %s" % detail)
            failures.append(detail)

    for db_name in DATABASES:
        base = db_name[:-3]
        gone = prune(daily_dir, base, DAILY_KEEP, args.dry_run)
        if gone:
            _log("  清理 daily/%s 舊備份 %d 份" % (base, len(gone)))
        gone_m = prune(monthly_dir, base, MONTHLY_KEEP, args.dry_run)
        if gone_m:
            _log("  清理 monthly/%s 舊備份 %d 份" % (base, len(gone_m)))

    if failures:
        _log("備份結束，有 %d 項失敗" % len(failures))
        return 1
    _log("備份完成，全部成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
