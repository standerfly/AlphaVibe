"""相片標籤：標籤清單（詞彙）管理與批次貼/移除標籤。

標籤同時寫在三處（與 AlphaVibe 相容）：
- 檔案的 XMP:Subject＋IPTC:Keywords（RAW 如 X3F 寫旁邊的 `.xmp` sidecar）
  ——AlphaVibe 匯入時由 `photo_metadata_sync.read_existing_tags()` 讀進資料庫
- Finder 標籤（純名稱，不帶顏色）——Finder 搜尋/篩選/智慧型檔案夾
- `~/.photo-tool/tags.json`——你的標籤清單（含使用次數、最近使用，用來排編號）

一張照片可以有任意多個標籤。評分用的 `★N` Finder 標籤與使用者自己加的其他
Finder 標籤不會被動到（只增減指定名稱的標籤）。

貼標籤的方式：⌃⌥⌘T 開視窗，清單每個標籤前有自動編號（依最近與常用排序），
在清單裡按數字鍵就會跳到那一項；⌃⌥⌘R 把上一次貼的標籤套用到目前選取的照片。
不再替每個標籤各綁一組系統快速鍵（實測 ⌘＋數字類組合在 Finder 服務裡不會觸發）。
"""
import json
import os
import re
import subprocess

import datetime

from photo_formats import (
    HEIC_EXTS, JPEG_EXTS, WRITABLE_RAW_EXTS, expand_group, find_exiftool,
    group_key, is_photo, read_finder_tags, sidecar_path, uses_sidecar,
    write_finder_tags)
from photo_metadata_sync import read_existing_tags, write_metadata

CONFIG_DIR = os.environ.get("PHOTO_TOOL_HOME") or os.path.expanduser("~/.photo-tool")
FORBIDDEN_CHARS = set(',;"\n\r\t/:\\')
STAR_RE = re.compile(r"^★[1-5]$")
MAX_RECENT = 12
STARTER_TAGS = [
    {"name": "街拍", "group": "", "uses": 0},
    {"name": "光影", "group": "", "uses": 0},
    {"name": "家人", "group": "", "uses": 0},
]


# ---------- 標籤清單 ----------

def vocab_path():
    return os.path.join(CONFIG_DIR, "tags.json")


def validate_name(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("標籤名稱不能是空的")
    if len(name) > 40:
        raise ValueError("標籤名稱太長（上限 40 字）")
    bad = sorted(set(name) & FORBIDDEN_CHARS)
    if bad:
        raise ValueError("標籤名稱不能包含這些字元：%s" % " ".join(repr(c) for c in bad))
    if STAR_RE.match(name):
        raise ValueError("★1～★5 是評分專用，不能當一般標籤")
    return name



def load_vocab():
    """讀取清單；第一次使用時建立起始清單（街拍、光影、家人）。"""
    path = vocab_path()
    if not os.path.exists(path):
        data = {"tags": [dict(t) for t in STARTER_TAGS], "recent": []}
        save_vocab(data)
        return data
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("tags", [])
    data.setdefault("recent", [])
    data.setdefault("last", [])
    return data


def save_vocab(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = vocab_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, vocab_path())


def find_tag(data, name):
    for t in data["tags"]:
        if t["name"] == name:
            return t
    return None


def add_tag(name, group=""):
    data = load_vocab()
    name = validate_name(name)
    if find_tag(data, name):
        raise ValueError("標籤已存在：%s" % name)
    entry = {"name": name, "group": (group or "").strip(), "uses": 0}
    data["tags"].append(entry)
    save_vocab(data)
    return entry


def remove_tag(name):
    """只從清單移除，不動已經貼在檔案上的標籤（要清掉請用 `tag remove`）。"""
    data = load_vocab()
    before = len(data["tags"])
    data["tags"] = [t for t in data["tags"] if t["name"] != name]
    data["recent"] = [n for n in data["recent"] if n != name]
    if len(data["tags"]) == before:
        raise ValueError("清單裡沒有這個標籤：%s" % name)
    save_vocab(data)





def touch_recent(names):
    """記錄最近使用（排編號用）並累計使用次數。"""
    data = load_vocab()
    recent = [n for n in data["recent"] if n not in names]
    data["recent"] = (list(names) + recent)[:MAX_RECENT]
    for n in names:
        entry = find_tag(data, n)
        if entry is not None:
            entry["uses"] = entry.get("uses", 0) + 1
    save_vocab(data)


def ordered_names(data):
    """視窗裡的編號順序：最近用過的在前，其餘依累計使用次數，再依清單順序。"""
    by_name = {t["name"]: t for t in data["tags"]}
    names = [n for n in data["recent"] if n in by_name]
    rest = [t for t in data["tags"] if t["name"] not in names]
    rest.sort(key=lambda t: -t.get("uses", 0))   # sort 穩定：同次數維持清單順序
    return names + [t["name"] for t in rest]


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def read_file_tags(path):
    """讀取檔案目前的標籤：XMP:Subject 與 IPTC:Keywords 的聯集（依序、去重）。
    RAW 讀旁邊的 sidecar。檔案不存在/讀取失敗回傳 []。"""
    target = sidecar_path(path) if uses_sidecar(path) else path
    if not os.path.exists(target):
        return []
    try:
        proc = subprocess.run(
            [find_exiftool() or "exiftool", "-j", "-charset", "iptc=UTF8",
             "-Subject", "-Keywords", target],
            capture_output=True, timeout=15)
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout.decode("utf-8", "replace"))[0]
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return []
    merged = []
    for t in _as_list(data.get("Subject")) + _as_list(data.get("Keywords")):
        if t not in merged:
            merged.append(t)
    return merged


def _finder_name(entry):
    return entry.split("\n")[0]


def apply_delta(path, add=(), remove=()):
    """對單一照片檔增減標籤（檔案內/sidecar＋Finder 標籤），保留評分與其他
    標籤。回傳 True 表示有實際改動。"""
    add, remove = list(add), set(remove)
    current = read_file_tags(path)
    new = [t for t in current if t not in remove]
    new += [t for t in add if t not in new]
    changed = False
    if new != current:
        _old, rating = read_existing_tags(path)
        write_metadata(path, new, rating)
        changed = True
    # Finder 標籤：只增減指定名稱，★N 與使用者其他標籤保留
    entries = read_finder_tags(path)
    names = {_finder_name(e) for e in entries}
    new_entries = [e for e in entries if _finder_name(e) not in remove]
    for t in add:
        if t not in {_finder_name(e) for e in new_entries}:
            new_entries.append(t + "\n0")
    if {_finder_name(e) for e in new_entries} != names:
        write_finder_tags(path, new_entries)
        changed = True
    return changed


def apply_to_selection(paths, add=(), remove=()):
    """對選取的檔案（連同同組檔案）增減標籤。回傳 (照片組數, 失敗[(路徑, 原因)])。"""
    targets = expand_group(paths)
    failed = []
    for t in targets:
        try:
            apply_delta(t, add, remove)
        except Exception as exc:  # noqa: BLE001
            failed.append((t, str(exc)))
    return len({group_key(t) for t in targets}), failed


def toggle(paths, name):
    """切換標籤：選取的照片全部都有 → 移除；否則 → 全部貼上。
    回傳 `{"action": "add"|"remove"|"none", "groups": int, "failed": [...]}`。"""
    name = validate_name(name)
    targets = expand_group(paths)
    if not targets:
        return {"action": "none", "groups": 0, "failed": []}
    all_have = all(name in read_file_tags(t) for t in targets)
    action = "remove" if all_have else "add"
    groups, failed = apply_to_selection(
        paths, add=() if all_have else (name,), remove=(name,) if all_have else ())
    if action == "add":
        touch_recent([name])
    return {"action": action, "groups": groups, "failed": failed}


def clear_all(paths):
    """移除選取照片上的全部標籤（Finder 標籤只移除同名的，★N 與其他不動）。"""
    groups = set()
    failed = []
    for t in expand_group(paths):
        try:
            tags = read_file_tags(t)
            if tags:
                apply_delta(t, remove=tags)
            groups.add(group_key(t))
        except Exception as exc:  # noqa: BLE001
            failed.append((t, str(exc)))
    return len(groups), failed


def selection_tags(paths):
    """回傳 (全部都有的標籤, 至少一張有的標籤)，各依出現順序。"""
    targets = expand_group(paths)
    sets = [read_file_tags(t) for t in targets]
    if not sets:
        return [], []
    union = []
    for s in sets:
        for t in s:
            if t not in union:
                union.append(t)
    common = [t for t in union if all(t in s for s in sets)]
    return common, union


# ---------- 視窗（osascript） ----------

def _esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _osascript(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def notify(message, title="相片標籤"):
    _osascript('display notification "%s" with title "%s"' % (_esc(message), _esc(title)))


def choose_from_list(items, preselected, prompt, title="相片標籤", multiple=True):
    """清單視窗（預設多選）。回傳選取的項目清單；取消回傳 None。"""
    def lit(xs):
        return "{" + ", ".join('"%s"' % _esc(x) for x in xs) + "}"
    script = ('choose from list %s with title "%s" with prompt "%s" '
              'default items %s %sOK button name "%s" '
              'cancel button name "取消"') % (
        lit(items), _esc(title), _esc(prompt), lit(preselected),
        "with multiple selections allowed and empty selection allowed "
        if multiple else "", "套用" if multiple else "選擇")
    proc = _osascript(script)
    out = proc.stdout.strip()
    if proc.returncode != 0 or out == "false":
        return None
    return [x for x in out.split(", ") if x]


def ask_text(prompt, title="相片標籤"):
    proc = _osascript(
        'text returned of (display dialog "%s" with title "%s" default answer "" '
        'buttons {"取消", "新增"} default button 2 cancel button 1)' % (
            _esc(prompt), _esc(title)))
    return proc.stdout.strip() if proc.returncode == 0 else None


def show_message(message, title="相片標籤"):
    _osascript('display dialog "%s" with title "%s" buttons {"好"} default button 1' % (
        _esc(message), _esc(title)))


# ---------- 右鍵流程 ----------


_NEW_LABEL = "＋ 新增標籤…"
_OUTSIDE = "（不在清單）"


def _label(tag):
    return "%s ▸ %s" % (tag["group"], tag["name"]) if tag.get("group") else tag["name"]


def numbered_labels(data, extra_names=()):
    """回傳 {視窗上顯示的文字: 標籤名稱}，依 `ordered_names()` 加上 1、2、3… 編號。
    在清單視窗按數字鍵會跳到對應項目（macOS 清單的輸入即選取）。"""
    by_name = {t["name"]: t for t in data["tags"]}
    labels = {}
    for i, name in enumerate(ordered_names(data), 1):
        labels["%d　%s" % (i, _label(by_name[name]))] = name
    for name in extra_names:   # 檔案上有、清單裡沒有：也列出來才有辦法移除
        if name not in by_name:
            labels[name + _OUTSIDE] = name
    return labels


def picker(paths, choose=choose_from_list, ask=ask_text, notify_fn=notify):
    """「貼標籤…」視窗（⌃⌥⌘T）：標籤前有自動編號（最近與常用排前面），按數字鍵
    跳到該項；目前選取照片都有的預先勾選，取消勾選＝移除、新勾選＝貼上；可當場
    新增標籤。這次貼上的標籤會記起來，⌃⌥⌘R 可套用到別批照片。"""
    if not expand_group(paths):
        notify_fn("選取的項目裡沒有照片")
        return None
    data = load_vocab()
    common, union = selection_tags(paths)
    labels = numbered_labels(data, union)
    items = list(labels) + [_NEW_LABEL]
    pre = [lbl for lbl, n in labels.items() if n in common]
    chosen = choose(items, pre, "按數字鍵跳到標籤，勾選＝貼上、取消勾選＝移除。")
    if chosen is None:
        return None
    selected = [labels[c] for c in chosen if c in labels]
    if _NEW_LABEL in chosen:
        new_name = ask("新標籤名稱：")
        if new_name:
            try:
                add_tag(new_name)
                selected.append(validate_name(new_name))
            except ValueError as exc:
                notify_fn(str(exc))
    add = [n for n in selected if n not in common]
    remove = [n for n in common if n not in selected]
    if not add and not remove:
        notify_fn("沒有變更")
        return {"add": [], "remove": []}
    groups, failed = apply_to_selection(paths, add=add, remove=remove)
    if add:
        touch_recent(add)
        data = load_vocab()
        data["last"] = list(add)
        save_vocab(data)
    parts = []
    if add:
        parts.append("貼上 " + "、".join(add))
    if remove:
        parts.append("移除 " + "、".join(remove))
    notify_fn("%s（%d 張）%s" % ("；".join(parts), groups,
                                 "，%d 個失敗" % len(failed) if failed else ""))
    return {"add": add, "remove": remove, "failed": failed}


def repeat_last(paths, notify_fn=notify):
    """「重複上次標籤」（⌃⌥⌘R）：把上一次在視窗貼上的標籤套用到目前選取的照片
    （只新增，不移除；已經有的不受影響）。"""
    last = load_vocab().get("last") or []
    if not last:
        notify_fn("還沒有「上一次貼的標籤」，先用 ⌃⌥⌘T 貼一次")
        return None
    if not expand_group(paths):
        notify_fn("選取的項目裡沒有照片")
        return None
    groups, failed = apply_to_selection(paths, add=last)
    touch_recent(last)
    notify_fn("已貼上 %s（%d 張）%s" % ("、".join(last), groups,
                                       "，%d 個失敗" % len(failed) if failed else ""))
    return {"added": last, "groups": groups, "failed": failed}


# ====================================================================

def history_dir():
    return os.path.join(CONFIG_DIR, "history")


def find_tagged_files(names, folder=None):
    """找出目前貼了 `names` 任一標籤的照片檔。

    - 指定 `folder`：用 exiftool 遞迴掃描檔案內/sidecar 的標籤（最可靠）。
    - 沒指定：用 Spotlight 查 Finder 標籤（快，但只涵蓋有被索引的位置）。
    回傳排序、去重的照片檔路徑清單（sidecar 會對應回它的 RAW）。"""
    names = set(names)
    found = set()
    if folder:
        exiftool = find_exiftool() or "exiftool"
        in_file_exts = [e.lstrip(".") for e in JPEG_EXTS + HEIC_EXTS + WRITABLE_RAW_EXTS]
        cmd = [exiftool, "-r", "-j", "-charset", "iptc=UTF8", "-Subject", "-Keywords"]
        for e in in_file_exts + ["xmp"]:
            cmd += ["-ext", e]
        cmd.append(folder)
        proc = subprocess.run(cmd, capture_output=True, timeout=600)
        try:
            rows = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
        except ValueError:
            rows = []
        for row in rows:
            tags = set(_as_list(row.get("Subject")) + _as_list(row.get("Keywords")))
            if not tags & names:
                continue
            path = row["SourceFile"]
            if path.lower().endswith(".xmp"):
                d, stem = group_key(path)
                for fn in os.listdir(d):
                    full = os.path.join(d, fn)
                    if (uses_sidecar(full) and is_photo(full)
                            and os.path.splitext(fn)[0].lower() == stem):
                        found.add(full)
            elif is_photo(path):
                found.add(os.path.abspath(path))
    else:
        for name in names:
            proc = subprocess.run(
                ["mdfind", "kMDItemUserTags == '%s'" % name.replace("'", "\\'")],
                capture_output=True, timeout=60)
            for line in proc.stdout.decode("utf-8", "replace").splitlines():
                if line and is_photo(line):
                    found.add(line)
    return sorted(found)


def plan_change(sources, target, folder=None):
    """預覽：`sources` 全部換成 `target`（改名/合併）；`target` 為 None 表示
    刪除。回傳 {"sources","target","files","groups"}。"""
    sources = [validate_name(n) for n in sources]
    if target is not None:
        target = validate_name(target)
    files = find_tagged_files(sources, folder)
    return {"sources": sources, "target": target, "files": files,
            "groups": len({group_key(f) for f in files}), "folder": folder}


def apply_change(plan, update_vocab=True):
    """執行 `plan_change()` 的結果，寫歷史紀錄供復原。回傳
    {"changed_files","failed","log"}。"""
    sources, target = plan["sources"], plan["target"]
    os.makedirs(history_dir(), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(history_dir(), "%s-tags.json" % stamp)
    entries, failed = [], []
    for path in plan["files"]:
        try:
            before = read_file_tags(path)
            apply_delta(path, add=(target,) if target else (),
                        remove=[n for n in sources if n != target])
            after = read_file_tags(path)
            added = [t for t in after if t not in before]
            removed = [t for t in before if t not in after]
            if added or removed:
                entries.append({"path": path, "added": added, "removed": removed})
        except Exception as exc:  # noqa: BLE001
            failed.append((path, str(exc)))
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"sources": sources, "target": target, "entries": entries,
                   "vocab_before": load_vocab() if update_vocab else None},
                  f, ensure_ascii=False, indent=1)
    if update_vocab:
        _update_vocab_for_change(sources, target)
    return {"changed_files": len(entries), "failed": failed, "log": log_path}


def _update_vocab_for_change(sources, target):
    data = load_vocab()
    by_name = {t["name"]: t for t in data["tags"]}
    moved_group, moved_uses = "", 0
    for n in sources:
        if n in by_name and n != target:
            moved_group = moved_group or by_name[n].get("group", "")
            moved_uses += by_name[n].get("uses", 0)
    data["tags"] = [t for t in data["tags"] if t["name"] not in sources or t["name"] == target]
    if target:
        entry = find_tag(data, target)
        if entry is None:   # 改名：新名稱繼承舊名稱的分組與使用次數
            data["tags"].append({"name": target, "group": moved_group, "uses": moved_uses})
        else:               # 合併進既有標籤：次數相加，沒有分組就繼承
            entry["uses"] = entry.get("uses", 0) + moved_uses
            entry["group"] = entry.get("group") or moved_group
        data["recent"] = [target if n in sources else n for n in data["recent"]]
        data["last"] = [target if n in sources else n for n in data.get("last", [])]
    else:
        data["recent"] = [n for n in data["recent"] if n not in sources]
        data["last"] = [n for n in data.get("last", []) if n not in sources]
    for key in ("recent", "last"):
        seen, out = set(), []
        for n in data[key]:
            if n not in seen:
                seen.add(n)
                out.append(n)
        data[key] = out
    save_vocab(data)


def undo_last_change():
    """復原最近一次跨檔案標籤變更（含標籤清單）。回傳 (還原檔案數, 略過[(路徑, 原因)])。"""
    d = history_dir()
    logs = sorted(f for f in os.listdir(d) if f.endswith("-tags.json")) if os.path.isdir(d) else []
    if not logs:
        raise ValueError("沒有可復原的標籤變更紀錄")
    log_path = os.path.join(d, logs[-1])
    with open(log_path, encoding="utf-8") as f:
        log = json.load(f)
    restored, skipped = 0, []
    for e in log["entries"]:
        if not os.path.exists(e["path"]):
            skipped.append((e["path"], "檔案已不在原位置"))
            continue
        apply_delta(e["path"], add=e["removed"], remove=e["added"])
        restored += 1
    if log.get("vocab_before") is not None:
        save_vocab(log["vocab_before"])
    os.rename(log_path, log_path + ".undone")
    return restored, skipped


# ---------- 「管理標籤…」視窗 ----------

def choose_folder(prompt="選擇要處理的資料夾"):
    proc = _osascript('POSIX path of (choose folder with prompt "%s")' % _esc(prompt))
    return proc.stdout.strip().rstrip("/") or None if proc.returncode == 0 else None


def confirm(message, ok_label="執行", title="相片標籤"):
    proc = subprocess.run(
        ["osascript",
         "-e", "on run argv",
         "-e", 'display dialog (item 1 of argv) with title (item 2 of argv) '
               'buttons {"取消", (item 3 of argv)} default button 2 '
               'cancel button 1 with icon note',
         "-e", "end run", message, title, ok_label], capture_output=True)
    return proc.returncode == 0


def _reinstall_services():
    import photo_services
    photo_services.install(load_vocab())


_ACTIONS = ("新增標籤", "改名", "合併標籤", "刪除標籤", "復原上次標籤變更")
_SCOPE_MAC = "整台 Mac（用 Spotlight，只含已索引的位置）"
_SCOPE_FOLDER = "選擇資料夾…（掃描檔案內的標籤，最準確）"


def _pick_one(choose, items, prompt):
    got = choose(items, [], prompt, multiple=False)
    return got[0] if got else None


def _pick_scope(choose, pick_folder):
    """回傳 (確認選了範圍, 資料夾或 None)。"""
    scope = _pick_one(choose, [_SCOPE_FOLDER, _SCOPE_MAC], "要在哪裡尋找貼了這些標籤的照片？")
    if scope is None:
        return False, None
    if scope == _SCOPE_FOLDER:
        folder = pick_folder()
        return (folder is not None), folder
    return True, None


def manager(choose=choose_from_list, ask=ask_text, confirm_fn=confirm,
            pick_folder=choose_folder, notify_fn=notify, reinstall=_reinstall_services):
    """「管理標籤…」：新增、改名、合併、刪除、指派快速鍵、復原。
    改名/合併/刪除會先找出受影響的照片、顯示數量，你確認才改檔案。"""
    action = _pick_one(choose, list(_ACTIONS), "要做什麼？")
    if action is None:
        return None
    names = [t["name"] for t in load_vocab()["tags"]]
    try:
        if action == "新增標籤":
            name = ask("新標籤名稱：")
            if not name:
                return None
            add_tag(name)
            reinstall()
            notify_fn("已新增「%s」" % name.strip())
            return action
        if action == "復原上次標籤變更":
            if not confirm_fn("要復原最近一次標籤的改名/合併/刪除嗎？", "復原"):
                return None
            restored, skipped = undo_last_change()
            reinstall()
            notify_fn("已復原 %d 個檔案%s" % (
                restored, "，略過 %d 個" % len(skipped) if skipped else ""))
            return action
        if not names:
            notify_fn("標籤清單是空的")
            return None
        if action == "改名":
            old = _pick_one(choose, names, "要改名的標籤：")
            if old is None:
                return None
            new = ask("「%s」的新名稱：" % old)
            if not new:
                return None
            sources, target, verb = [old], validate_name(new), "改名成「%s」" % new.strip()
        elif action == "合併標籤":
            picked = choose(names, [], "選兩個以上要合併的標籤：")
            if not picked or len(picked) < 2:
                notify_fn("合併至少要選兩個標籤")
                return None
            target = _pick_one(choose, picked, "合併後要保留哪個名稱？")
            if target is None:
                return None
            sources, verb = picked, "合併成「%s」" % target
        else:  # 刪除標籤
            old = _pick_one(choose, names, "要刪除的標籤：")
            if old is None:
                return None
            sources, target, verb = [old], None, "從所有照片移除並刪除"
        ok, folder = _pick_scope(choose, pick_folder)
        if not ok:
            return None
        plan = plan_change(sources, target, folder)
        msg = "把「%s」%s\n\n範圍：%s\n找到 %d 張照片（%d 個檔案）。\n確認後才會改檔案，之後可用「復原上次標籤變更」還原。" % (
            "、".join(sources), verb, folder or "整台 Mac（Spotlight）",
            plan["groups"], len(plan["files"]))
        if not confirm_fn(msg, "執行"):
            return None
        result = apply_change(plan)
        reinstall()
        notify_fn("完成：改了 %d 個檔案%s" % (
            result["changed_files"],
            "，%d 個失敗" % len(result["failed"]) if result["failed"] else ""))
        return action
    except ValueError as exc:
        notify_fn(str(exc))
        return None
