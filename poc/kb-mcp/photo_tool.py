"""相片整理命令列工具（macOS）。

流程：整理（organize）→ 評分（rate）→ 匯入（import）→ 清理（clean）。

    python3 photo_tool.py organize <資料夾> [--recursive] [--apply]
    python3 photo_tool.py undo [<紀錄檔>]
    python3 photo_tool.py rate <0-5> <檔案...>
    python3 photo_tool.py import <資料夾> [--location internal|external|reference] [--dest DIR] [--recursive]
    python3 photo_tool.py clean <資料夾> [--delete]
    python3 photo_tool.py rebuild-thumbnails

設計原則：
- `organize` 預設只預覽（dry-run），加 `--apply` 才真的搬；每次搬移寫入
  歷史紀錄（`~/.photo-tool/history/`），`undo` 可復原；從不覆蓋既有檔案。
- 同名不同副檔名的檔案視為一組（X3F＋JPG＋XMP）一起搬、一起評分。
- 評分一律寫 XMP:Rating（0-5，與 AlphaVibe 相容）；RAW（含 X3F）寫旁邊的
  `.xmp` sidecar；另外加上 Finder 標籤 `★N`，Finder 才能搜尋/篩選。
- `clean` 預設只列清單，必須互動式輸入 yes 才會把「已確認匯入」的來源檔
  移到垃圾桶（可從垃圾桶復原）。

注意：已匯入 AlphaVibe 的照片請在 AlphaVibe 介面評分（資料庫是真相來源，
已存在的紀錄不會回頭讀檔案）；`organize` 只該用在匯入之前的原始照片。
"""
import argparse
import datetime
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from photo_formats import (  # noqa: E402
    USER_TAGS_ATTR, ext_of, find_exiftool, is_photo, make_jpeg,
    primary_rank, read_capture_date, read_finder_tags, sidecar_path,
    uses_sidecar, write_finder_tags)

HISTORY_DIR = os.path.expanduser("~/.photo-tool/history")
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
STAR_TAG_RE = re.compile(r"^★[1-5]($|\n)")
PRODUCTION_DATA_DIR = os.path.abspath(os.path.join(HERE, "..", "data"))


# ---------- 檔案分組 ----------

def _group_key(path):
    return (os.path.dirname(path), os.path.splitext(os.path.basename(path))[0].lower())


def collect_groups(root, recursive=False):
    """回傳 `{(目錄, 小寫主檔名): [檔案路徑,...]}`。一組 = 同目錄同主檔名的
    所有照片檔與 .xmp sidecar（例如 SDIM0071.X3F／.jpg／.xmp）。沒有任何
    照片檔、只有孤立 .xmp 的不成組。"""
    groups = {}
    walker = os.walk(root) if recursive else [(root, [], os.listdir(root))]
    for dirpath, _dirs, files in walker:
        for name in sorted(files):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full):
                continue
            if is_photo(full) or ext_of(full) == ".xmp":
                groups.setdefault(_group_key(full), []).append(full)
    return {k: v for k, v in groups.items() if any(is_photo(p) for p in v)}


def primary_of(members):
    photos = [p for p in members if is_photo(p)]
    return min(photos, key=primary_rank)


# ---------- organize ----------

def plan_organize(root, recursive=False):
    """建立搬移計畫（不動任何檔案）。回傳 dict：
    moves=[{src,dst,date,source}], skipped_in_place, no_exif=[group 主檔],
    duplicates=[{src,existing}]"""
    root = os.path.abspath(root)
    moves, in_place, no_exif, duplicates = [], 0, [], []
    claimed = set()  # 本次計畫已佔用的目的路徑，避免兩組搬到同名
    for _key, members in sorted(collect_groups(root, recursive).items()):
        primary = primary_of(members)
        when, source = read_capture_date(primary)
        date_str = when.strftime("%Y-%m-%d")
        if source == "file":
            no_exif.append(primary)
        dest_dir = os.path.join(root, date_str)
        if os.path.dirname(primary) == dest_dir:
            in_place += 1
            continue
        for src in members:
            dst = os.path.join(dest_dir, os.path.basename(src))
            if os.path.exists(dst) or dst in claimed:
                if os.path.exists(dst) and _same_file(src, dst):
                    duplicates.append({"src": src, "existing": dst})
                    continue
                dst = _unique_path(dst, claimed)
            claimed.add(dst)
            moves.append({"src": src, "dst": dst, "date": date_str,
                          "source": source})
    return {"root": root, "moves": moves, "in_place": in_place,
            "no_exif": no_exif, "duplicates": duplicates}


def _same_file(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    from photo_importer import _compute_md5
    return _compute_md5(a) == _compute_md5(b)


def _unique_path(path, claimed):
    base, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = "%s_%d%s" % (base, n, ext)
        if not os.path.exists(cand) and cand not in claimed:
            return cand
        n += 1


def apply_organize(plan):
    """執行搬移並寫歷史紀錄，回傳紀錄檔路徑。"""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(HISTORY_DIR, "%s-organize.json" % stamp)
    created_dirs, done = [], []
    for mv in plan["moves"]:
        dest_dir = os.path.dirname(mv["dst"])
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
            created_dirs.append(dest_dir)
        shutil.move(mv["src"], mv["dst"])  # 目的路徑已確認不存在，不會覆蓋
        done.append({"src": mv["src"], "dst": mv["dst"]})
        # 每搬一個就更新紀錄，中途失敗也能復原已搬的
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({"root": plan["root"], "moves": done,
                       "created_dirs": created_dirs}, f, ensure_ascii=False, indent=1)
    if not done:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({"root": plan["root"], "moves": [], "created_dirs": []}, f)
    return log_path


def undo(log_path=None):
    """復原一次 organize。回傳 (還原數, 略過[(路徑, 原因)])。"""
    if log_path is None:
        if not os.path.isdir(HISTORY_DIR):
            raise RuntimeError("沒有任何歷史紀錄可以復原")
        logs = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith("-organize.json"))
        if not logs:
            raise RuntimeError("沒有任何歷史紀錄可以復原")
        log_path = os.path.join(HISTORY_DIR, logs[-1])
    with open(log_path, encoding="utf-8") as f:
        log = json.load(f)
    restored, skipped = 0, []
    for mv in reversed(log["moves"]):
        if not os.path.exists(mv["dst"]):
            skipped.append((mv["dst"], "檔案已不在搬移後的位置"))
        elif os.path.exists(mv["src"]):
            skipped.append((mv["dst"], "原位置已有同名檔案，不覆蓋"))
        else:
            shutil.move(mv["dst"], mv["src"])
            restored += 1
    for d in reversed(log["created_dirs"]):
        try:
            os.rmdir(d)  # 只刪空資料夾
        except OSError:
            pass
    os.rename(log_path, log_path + ".undone")
    return restored, skipped


# ---------- rate ----------

def _star_tags(existing, n):
    tags = [t for t in existing if not STAR_TAG_RE.match(t)]
    if n > 0:
        tags.append("★%d\n0" % n)
    return tags


def set_finder_star_tag(path, n):
    """把 Finder 標籤換成 ★N（保留使用者其他標籤；n=0 清除星等標籤）。"""
    write_finder_tags(path, _star_tags(read_finder_tags(path), n))


def rate_file(path, n):
    """對單一照片檔寫入評分：RAW 寫 sidecar，其餘寫檔案本身；再加 Finder 標籤。"""
    if not 0 <= n <= 5:
        raise ValueError("評分必須是 0 到 5")
    from photo_metadata_sync import _EMPTY_XMP
    exiftool = find_exiftool()
    if exiftool is None:
        raise RuntimeError("找不到 exiftool，請先執行：brew install exiftool")
    target = path
    if uses_sidecar(path):
        target = sidecar_path(path)
        if not os.path.exists(target):
            with open(target, "w", encoding="utf-8") as f:
                f.write(_EMPTY_XMP)
    # exiftool -overwrite_original 會用新檔取代原檔，檔案上的 Finder 標籤
    # （xattr）會跟著遺失——實測確認——所以寫入前先讀出、寫入後補回。
    saved_tags = read_finder_tags(path)
    proc = subprocess.run(
        [exiftool, "-overwrite_original", "-XMP:Rating=%d" % n, target],
        capture_output=True)
    write_finder_tags(path, saved_tags)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    set_finder_star_tag(path, n)


def rate_files(paths, n):
    """對選取的檔案評分；同組（同目錄同主檔名）的其他照片檔一併評分。
    回傳 (成功清單, 失敗[(路徑, 原因)])。"""
    targets, seen = [], set()
    for p in paths:
        p = os.path.abspath(p)
        if not os.path.isfile(p):
            continue
        siblings = [p]
        d, stem = _group_key(p)
        for name in os.listdir(d):
            full = os.path.join(d, name)
            if (full != p and is_photo(full)
                    and os.path.splitext(name)[0].lower() == stem):
                siblings.append(full)
        for s in siblings:
            if is_photo(s) and s not in seen:
                seen.add(s)
                targets.append(s)
    ok, failed = [], []
    for t in targets:
        try:
            rate_file(t, n)
            ok.append(t)
        except Exception as exc:  # noqa: BLE001
            failed.append((t, str(exc)))
    return ok, failed


# ---------- import / clean / rebuild ----------

def _open_store(data_dir, write=True):
    from photo_store import PhotoStore
    data_dir = os.path.abspath(data_dir or os.environ.get("ALPHAVIBE_DATA_DIR")
                               or PRODUCTION_DATA_DIR)
    if (write and data_dir == PRODUCTION_DATA_DIR
            and os.environ.get("ALPHAVIBE_ALLOW_PRODUCTION_WRITE") != "1"):
        raise SystemExit(
            "拒絕寫入正式資料目錄 %s。要正式匯入請加環境變數 "
            "ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1，測試請用 --data-dir 指向複製目錄。"
            % data_dir)
    return PhotoStore(data_dir)


def do_import(folder, location, dest, recursive, data_dir):
    from photo_importer import commit_import, scan_folder
    store = _open_store(data_dir)
    try:
        scan = scan_folder(folder, store, recursive=recursive)
        print("掃描：新照片 %d、重複 %d、搬家 %d、無法讀取 %d" % (
            len(scan["new_files"]), scan["duplicate_count"],
            len(scan["moved_files"]), len(scan["unreadable"])))
        if not scan["new_files"]:
            return 0
        dest_dir = dest or os.path.join(store.data_dir, "photos", "originals", location)
        thumb_dir = os.path.join(store.data_dir, "photos", "thumbnails")
        result = commit_import(scan["new_files"], location, dest_dir, thumb_dir, store)
        print("匯入完成：成功 %d、失敗 %d" % (result["imported_count"], len(result["failed"])))
        for f in result["failed"]:
            print("  失敗 %s：%s" % (f["filename"], f["reason"]))
        return 1 if result["failed"] else 0
    finally:
        store.close()


def find_imported_sources(folder, store, recursive=False):
    """找出來源資料夾裡「已確認匯入、且 AlphaVibe 端副本仍在」的檔案組。
    只認 internal/external 複製模式（reference 模式照片就在原位，不能刪）。"""
    from photo_importer import _compute_md5
    safe = []
    for _key, members in sorted(collect_groups(folder, recursive).items()):
        photos = [p for p in members if is_photo(p)]
        ok = True
        for p in photos:
            rec = store.find_by_hash(_compute_md5(p))
            if (rec is None or rec["storage_location"] == "reference"
                    or not os.path.exists(rec["storage_path"])):
                ok = False
                break
        if ok and photos:
            safe.extend(members)
    return safe


def move_to_trash(path):
    script = 'tell application "Finder" to delete POSIX file %s' % json.dumps(path)
    proc = subprocess.run(["osascript", "-e", script], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())


def rebuild_thumbnails(data_dir):
    from photo_importer import THUMBNAIL_MAX_DIM
    store = _open_store(data_dir)
    done = skipped = failed = 0
    try:
        rows = store.conn.execute(
            "SELECT id, storage_path, thumbnail_path FROM photos").fetchall()
        for row in rows:
            if not os.path.exists(row["storage_path"]):
                skipped += 1  # 外接硬碟沒接等：保留舊縮圖
                continue
            try:
                make_jpeg(row["storage_path"], row["thumbnail_path"], THUMBNAIL_MAX_DIM)
                done += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("失敗 id=%s：%s" % (row["id"], exc))
    finally:
        store.close()
    print("縮圖重建：成功 %d、略過(原檔離線) %d、失敗 %d" % (done, skipped, failed))
    return 1 if failed else 0


# ---------- CLI ----------

def summarize_plan(plan, max_dates=12):
    """把搬移計畫整理成人看的文字（命令列與確認視窗共用）。"""
    moves = plan["moves"]
    by_date = {}
    for mv in moves:
        by_date.setdefault(mv["date"], []).append(mv)
    lines = ["將搬移 %d 個檔案到 %d 個日期資料夾：" % (len(moves), len(by_date))]
    for date in sorted(by_date)[:max_dates]:
        lines.append("  %s  ← %d 個檔案" % (date, len(by_date[date])))
    if len(by_date) > max_dates:
        lines.append("  …還有 %d 個日期" % (len(by_date) - max_dates))
    if plan["in_place"]:
        lines.append("已在正確日期資料夾（略過）：%d 組" % plan["in_place"])
    if plan["duplicates"]:
        lines.append("內容相同的重複檔（保留原位不搬）：%d 個" % len(plan["duplicates"]))
    if plan["no_exif"]:
        lines.append("無 EXIF 拍攝日期（改用檔案建立時間）：%d 組" % len(plan["no_exif"]))
    return "\n".join(lines)


def _dialog(message, ok_label, title="相片整理"):
    """顯示確認視窗；使用者按確認回傳 True，取消回傳 False。"""
    proc = subprocess.run(
        ["osascript",
         "-e", "on run argv",
         "-e", 'display dialog (item 1 of argv) with title (item 2 of argv) '
               'buttons {"取消", (item 3 of argv)} default button 2 '
               'cancel button 1 with icon note',
         "-e", "end run", message, title, ok_label],
        capture_output=True)
    return proc.returncode == 0


def _notify(message, title="相片整理"):
    subprocess.run(
        ["osascript", "-e", "on run argv",
         "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
         "-e", "end run", message, title], capture_output=True)


def organize_gui(folder, ask=_dialog, notify=_notify):
    """Finder 右鍵流程：預覽 → 確認視窗 → 搬移 → 通知。回傳 True 表示有搬。"""
    if not os.path.isdir(folder):
        notify("不是資料夾：%s" % folder)
        return False
    plan = plan_organize(folder)
    if not plan["moves"]:
        notify("沒有需要整理的照片（%s）" % os.path.basename(folder))
        return False
    msg = "資料夾：%s\n\n%s\n\n確認後才會搬移，之後可用「復原上次整理」還原。" % (
        folder, summarize_plan(plan))
    if not ask(msg, "執行整理"):
        return False
    apply_organize(plan)
    notify("完成：已搬移 %d 個檔案。可用「復原上次整理」還原。" % len(plan["moves"]))
    return True


def undo_gui(ask=_dialog, notify=_notify):
    """Finder 右鍵流程：確認後復原最近一次整理。"""
    if not os.path.isdir(HISTORY_DIR):
        notify("沒有可復原的整理紀錄")
        return False
    logs = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith("-organize.json"))
    if not logs:
        notify("沒有可復原的整理紀錄")
        return False
    with open(os.path.join(HISTORY_DIR, logs[-1]), encoding="utf-8") as f:
        log = json.load(f)
    if not ask("要復原最近一次整理嗎？\n\n資料夾：%s\n將把 %d 個檔案搬回原位置。" % (
            log["root"], len(log["moves"])), "復原"):
        return False
    restored, skipped = undo()
    notify("已復原 %d 個檔案%s" % (
        restored, "，略過 %d 個（原位置已有同名檔案或檔案不見了）" % len(skipped)
        if skipped else ""))
    return True


def _print_plan(plan, apply):
    moves = plan["moves"]
    by_date = {}
    for mv in moves:
        by_date.setdefault(mv["date"], []).append(mv)
    files = len(moves)
    print("%s：將搬移 %d 個檔案到 %d 個日期資料夾" % (
        "執行" if apply else "預覽", files, len(by_date)))
    for date in sorted(by_date):
        print("  %s  ← %d 個檔案" % (date, len(by_date[date])))
    if plan["in_place"]:
        print("已在正確日期資料夾（略過）：%d 組" % plan["in_place"])
    if plan["duplicates"]:
        print("內容相同的重複檔（保留在原位，不搬）：%d 個" % len(plan["duplicates"]))
    if plan["no_exif"]:
        print("無 EXIF 拍攝日期（改用檔案建立時間）：%d 組" % len(plan["no_exif"]))
        for p in plan["no_exif"][:10]:
            print("  - %s" % p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="相片整理工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("organize", help="依拍攝日期整理成 yyyy-MM-dd 資料夾")
    p.add_argument("folder")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--apply", action="store_true", help="真的搬移（預設只預覽）")

    p = sub.add_parser("organize-gui", help="Finder 右鍵用：預覽視窗確認後整理")
    p.add_argument("folder")

    sub.add_parser("undo-gui", help="Finder 右鍵用：確認後復原最近一次整理")

    p = sub.add_parser("undo", help="復原最近一次（或指定紀錄）的整理")
    p.add_argument("log", nargs="?")

    p = sub.add_parser("rate", help="批次評分 0-5 星（寫 XMP:Rating＋Finder ★標籤）")
    p.add_argument("stars", type=int, choices=range(0, 6))
    p.add_argument("files", nargs="+")

    p = sub.add_parser("import", help="匯入 AlphaVibe 相簿")
    p.add_argument("folder")
    p.add_argument("--location", choices=("internal", "external", "reference"),
                   default="internal")
    p.add_argument("--dest")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--data-dir")

    p = sub.add_parser("clean", help="列出（可選擇刪除）已匯入的來源檔案")
    p.add_argument("folder")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--delete", action="store_true")
    p.add_argument("--data-dir")

    p = sub.add_parser("rebuild-thumbnails", help="用新解析度重建既有照片縮圖")
    p.add_argument("--data-dir")

    args = ap.parse_args(argv)

    if args.cmd == "organize":
        if not os.path.isdir(args.folder):
            print("不是有效的資料夾：%s" % args.folder)
            return 2
        plan = plan_organize(args.folder, args.recursive)
        _print_plan(plan, args.apply)
        if not plan["moves"]:
            return 0
        if args.apply:
            log = apply_organize(plan)
            print("完成。復原指令：python3 photo_tool.py undo   （紀錄：%s）" % log)
        else:
            print("這只是預覽，沒有搬動任何檔案。確認後加 --apply 執行。")
        return 0

    if args.cmd == "organize-gui":
        organize_gui(args.folder)
        return 0

    if args.cmd == "undo-gui":
        undo_gui()
        return 0

    if args.cmd == "undo":
        restored, skipped = undo(args.log)
        print("已復原 %d 個檔案" % restored)
        for path, why in skipped:
            print("  略過 %s：%s" % (path, why))
        return 0

    if args.cmd == "rate":
        ok, failed = rate_files(args.files, args.stars)
        print("評分 %d 星：成功 %d 個檔案" % (args.stars, len(ok)))
        for path, why in failed:
            print("  失敗 %s：%s" % (path, why))
        return 1 if failed or not ok else 0

    if args.cmd == "import":
        return do_import(args.folder, args.location, args.dest, args.recursive,
                         args.data_dir)

    if args.cmd == "clean":
        store = _open_store(args.data_dir, write=False)
        try:
            files = find_imported_sources(args.folder, store, args.recursive)
        finally:
            store.close()
        print("已確認匯入（AlphaVibe 端副本存在且雜湊一致）的來源檔案：%d 個" % len(files))
        for f in files:
            print("  %s" % f)
        if not files or not args.delete:
            if files:
                print("沒有刪除任何檔案。要移到垃圾桶請加 --delete，並在提示時輸入 yes。")
            return 0
        if not sys.stdin.isatty():
            print("--delete 需要在終端機互動確認，已取消。")
            return 2
        if input("把以上 %d 個檔案移到垃圾桶？輸入 yes 確認：" % len(files)).strip() != "yes":
            print("已取消，沒有刪除任何檔案。")
            return 0
        for f in files:
            move_to_trash(f)
        print("已移到垃圾桶（可從垃圾桶復原）。")
        return 0

    if args.cmd == "rebuild-thumbnails":
        return rebuild_thumbnails(args.data_dir)
    return 2


if __name__ == "__main__":
    sys.exit(main())
