"""相片標籤：標籤清單（詞彙）管理與批次貼/移除標籤。

標籤同時寫在三處（與 AlphaVibe 相容）：
- 檔案的 XMP:Subject＋IPTC:Keywords（RAW 如 X3F 寫旁邊的 `.xmp` sidecar）
  ——AlphaVibe 匯入時由 `photo_metadata_sync.read_existing_tags()` 讀進資料庫
- Finder 標籤（純名稱，不帶顏色）——Finder 搜尋/篩選/智慧型檔案夾
- `~/.photo-tool/tags.json`——你的標籤清單與快速鍵對應

一張照片可以有任意多個標籤。評分用的 `★N` Finder 標籤與使用者自己加的其他
Finder 標籤不會被動到（只增減指定名稱的標籤）。

快速鍵（⌃⌘＋鍵）：數字 1-9 或字母；`q`（鎖定螢幕）、`f`（全螢幕）、`d`
（查字典）是 macOS 保留組合，`t` 留給「貼標籤…」視窗，皆不可指派。
"""
import json
import os
import re
import subprocess

from photo_formats import (
    expand_group, find_exiftool, group_key, read_finder_tags, sidecar_path,
    uses_sidecar, write_finder_tags)
from photo_metadata_sync import read_existing_tags, write_metadata

CONFIG_DIR = os.environ.get("PHOTO_TOOL_HOME") or os.path.expanduser("~/.photo-tool")
FORBIDDEN_CHARS = set(',;"\n\r\t/:\\')
STAR_RE = re.compile(r"^★[1-5]$")
RESERVED_KEYS = {"q", "f", "d", "t"}
VALID_KEYS = (set("123456789") | set("abcdefghijklmnopqrstuvwxyz")) - RESERVED_KEYS
MAX_RECENT = 12
STARTER_TAGS = [
    {"name": "街拍", "key": "1", "group": ""},
    {"name": "光影", "key": "2", "group": ""},
    {"name": "家人", "key": "3", "group": ""},
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


def validate_key(key):
    key = (key or "").strip().lower()
    if key not in VALID_KEYS:
        raise ValueError(
            "快速鍵必須是 1-9 或字母（q、f、d、t 是系統保留，不能用）：%r" % key)
    return key


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


def add_tag(name, key=None, group=""):
    data = load_vocab()
    name = validate_name(name)
    if find_tag(data, name):
        raise ValueError("標籤已存在：%s" % name)
    entry = {"name": name, "key": "", "group": (group or "").strip()}
    if key:
        _assign_key(data, entry, key)
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


def _assign_key(data, entry, key):
    key = validate_key(key)
    for t in data["tags"]:
        if t is not entry and t.get("key") == key:
            raise ValueError("快速鍵 %s 已被「%s」使用" % (key.upper(), t["name"]))
    entry["key"] = key


def set_key(name, key):
    """指派/更換快速鍵；`key` 為 None 或空字串表示清除。"""
    data = load_vocab()
    entry = find_tag(data, name)
    if entry is None:
        raise ValueError("清單裡沒有這個標籤：%s" % name)
    if key:
        _assign_key(data, entry, key)
    else:
        entry["key"] = ""
    save_vocab(data)
    return entry


def tag_for_key(key):
    key = (key or "").strip().lower()
    for t in load_vocab()["tags"]:
        if t.get("key") == key:
            return t["name"]
    return None


def touch_recent(names):
    data = load_vocab()
    recent = [n for n in data["recent"] if n not in names]
    data["recent"] = (list(names) + recent)[:MAX_RECENT]
    save_vocab(data)


# ---------- 讀寫檔案標籤 ----------

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


def choose_from_list(items, preselected, prompt, title="相片標籤"):
    """多選清單視窗。回傳選取的項目清單；取消回傳 None。"""
    def lit(xs):
        return "{" + ", ".join('"%s"' % _esc(x) for x in xs) + "}"
    script = ('choose from list %s with title "%s" with prompt "%s" '
              'default items %s with multiple selections allowed '
              'and empty selection allowed OK button name "套用" '
              'cancel button name "取消"') % (
        lit(items), _esc(title), _esc(prompt), lit(preselected))
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

def slot_toggle(key, paths, notify_fn=notify):
    """快速鍵流程：⌃⌘＋鍵 → 切換該格對應的標籤，通知結果。"""
    name = tag_for_key(key)
    if name is None:
        notify_fn("快速鍵 %s 還沒有對應的標籤（用 tags key 指派）" % key.upper())
        return None
    result = toggle(paths, name)
    if result["action"] == "none":
        notify_fn("選取的項目裡沒有照片")
    elif result["failed"]:
        notify_fn("「%s」有 %d 個檔案失敗：%s" % (
            name, len(result["failed"]), result["failed"][0][1][:80]))
    elif result["action"] == "add":
        notify_fn("已貼上「%s」到 %d 張" % (name, result["groups"]))
    else:
        notify_fn("已移除「%s」（%d 張）" % (name, result["groups"]))
    return result


_NEW_LABEL = "＋ 新增標籤…"
_OUTSIDE = "（不在清單）"


def _label(tag):
    return "%s ▸ %s" % (tag["group"], tag["name"]) if tag.get("group") else tag["name"]


def picker(paths, choose=choose_from_list, ask=ask_text, notify_fn=notify):
    """「貼標籤…」視窗：最近用過的排最前、目前選取照片都有的預先勾選；
    取消勾選＝移除、新勾選＝貼上；可當場新增標籤。"""
    if not expand_group(paths):
        notify_fn("選取的項目裡沒有照片")
        return None
    data = load_vocab()
    common, union = selection_tags(paths)
    by_name = {t["name"]: t for t in data["tags"]}
    ordered = [n for n in data["recent"] if n in by_name]
    ordered += [t["name"] for t in data["tags"] if t["name"] not in ordered]
    labels = {}
    for n in ordered:
        labels[_label(by_name[n])] = n
    for n in union:
        if n not in by_name:  # 檔案上有、清單裡沒有：也列出來才有辦法移除
            labels[n + _OUTSIDE] = n
    items = list(labels) + [_NEW_LABEL]
    pre = [lbl for lbl, n in labels.items() if n in common]
    chosen = choose(items, pre, "勾選要貼上的標籤；取消勾選會移除。")
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
    parts = []
    if add:
        parts.append("貼上 " + "、".join(add))
    if remove:
        parts.append("移除 " + "、".join(remove))
    notify_fn("%s（%d 張）%s" % ("；".join(parts), groups,
                                 "，%d 個失敗" % len(failed) if failed else ""))
    return {"add": add, "remove": remove, "failed": failed}


def cheatsheet_text(paths=()):
    data = load_vocab()
    lines = ["快速鍵（⌃⌘＋鍵）　按一次貼上、再按一次移除", ""]
    keyed = [t for t in data["tags"] if t.get("key")]
    for t in sorted(keyed, key=lambda t: (not t["key"].isdigit(), t["key"])):
        lines.append("⌃⌘%s　%s" % (t["key"].upper(), _label(t)))
    if not keyed:
        lines.append("（還沒有指派快速鍵）")
    lines += ["", "⌃⌘T　開啟「貼標籤…」視窗（可勾選全部標籤、新增標籤）"]
    unkeyed = [t["name"] for t in data["tags"] if not t.get("key")]
    if unkeyed:
        lines += ["", "只能從視窗貼的標籤：" + "、".join(unkeyed)]
    if paths:
        common, union = selection_tags(paths)
        lines += ["", "目前選取的照片："]
        lines.append("　全部都有：" + ("、".join(common) if common else "（無）"))
        partial = [t for t in union if t not in common]
        if partial:
            lines.append("　部分有：" + "、".join(partial))
    return "\n".join(lines)


def show_cheatsheet(paths):
    show_message(cheatsheet_text(paths), title="相片標籤速查表")
