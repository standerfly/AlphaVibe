"""外部內容資料匣（012 contracts/inbox-file-format.md、research R4）。

只依賴標準庫（Python 3.9 相容）。負責：中繼資料區塊解析與驗證、資料匣目錄管理、
讀檔 realpath 守衛、掃描、建檔（不覆蓋、不留半檔）、搬入 processed（同名不覆蓋）。
不碰資料庫；錯誤一律丟 `InboxError`（訊息為繁體中文原因）。
"""
import datetime
import hashlib
import os
import re
import tempfile
from urllib.parse import urlsplit

import external_content_identity as identity

MAX_FILE_CHARS = 2000000
SUPPORTED_EXTS = (".md", ".txt")
SOURCE_TYPES = ("youtube", "podcast", "article")
REQUIRED_KEYS = ("source_type", "url", "title", "author", "date")
KNOWN_KEYS = REQUIRED_KEYS + ("guid",)
INBOX_DIRNAME = "inbox"
PROCESSED_DIRNAME = "processed"
MAX_NAME_STEM = 80

_KV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*:")
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNSAFE_NAME_RE = re.compile(r"[^0-9A-Za-z\-_一-鿿]")


class InboxError(Exception):
    """資料匣檔案的具體問題（缺欄位、格式錯、路徑不合法等），訊息為繁體中文。"""


# ---------------------------------------------------------------- 目錄

def inbox_paths(data_dir):
    """回 (inbox 路徑, processed 路徑)，不建立。"""
    inbox = os.path.join(data_dir, INBOX_DIRNAME)
    return inbox, os.path.join(inbox, PROCESSED_DIRNAME)


def ensure_dirs(data_dir):
    inbox, processed = inbox_paths(data_dir)
    os.makedirs(processed, exist_ok=True)
    return inbox, processed


def _inbox_real(data_dir):
    inbox, _ = ensure_dirs(data_dir)
    return os.path.realpath(inbox)


# ---------------------------------------------------------------- 區塊解析與驗證

def parse_inbox_text(text):
    """解析 `---` 包夾的中繼資料區塊。回 (meta dict, body 字串, unknown_keys 清單)。
    只做結構解析；必填／格式驗證用 `validate_meta`；內文檢查用 `check_body`。"""
    if not isinstance(text, str):
        raise InboxError("檔案內容不是文字")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    if lines[0].rstrip("\r") != "---":
        raise InboxError("中繼資料區塊無法解析：第一行必須是 ---")
    meta = {}
    unknown = []
    end = None
    for i in range(1, len(lines)):
        raw = lines[i].rstrip("\r")
        if raw == "---":
            end = i
            break
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            raise InboxError("中繼資料區塊無法解析：第 %d 行不是 key: value 格式" % (i + 1))
        key, value = s.split(":", 1)
        key = key.strip().lower()
        if not key:
            raise InboxError("中繼資料區塊無法解析：第 %d 行缺少鍵名" % (i + 1))
        if key in KNOWN_KEYS:
            meta[key] = value.strip()
        elif key not in unknown:
            unknown.append(key)
    if end is None:
        raise InboxError("中繼資料區塊無法解析：找不到結束的 --- 行")
    body = "\n".join(lines[end + 1:])
    return meta, body, unknown


def validate_meta(meta):
    """驗證必填與格式，回正規化後的 dict（source_type 小寫、值去頭尾空白、guid 空字串→None）。
    問題以 InboxError 說明具體原因。"""
    m = dict((k, (v.strip() if isinstance(v, str) else v)) for k, v in meta.items())
    missing = [k for k in REQUIRED_KEYS if not (isinstance(m.get(k), str) and m.get(k))]
    if missing:
        if missing == ["url"]:
            raise InboxError("缺少連結（url），無法判斷來源身分")
        raise InboxError("缺少必填欄位：%s" % "、".join(missing))
    m["source_type"] = m["source_type"].lower()
    if m["source_type"] not in SOURCE_TYPES:
        raise InboxError("source_type 必須是 youtube、podcast、article 其中之一（目前是「%s」）" % m["source_type"])
    try:
        parts = urlsplit(m["url"])
        ok = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        ok = False
    if not ok:
        raise InboxError("連結無效：url 必須是 http 或 https 網址（目前是「%s」）" % m["url"])
    check_date(m["date"])
    g = m.get("guid")
    m["guid"] = g if isinstance(g, str) and g.strip() else None
    return m


def check_date(value):
    """date 必須是 YYYY-MM-DD 且為真實日曆日。"""
    if not isinstance(value, str) or not _DATE_SHAPE_RE.match(value.strip()):
        raise InboxError("date 格式必須是 YYYY-MM-DD（目前是「%s」）" % value)
    try:
        datetime.date.fromisoformat(value.strip())
    except ValueError:
        raise InboxError("date 不是真實的日曆日期（目前是「%s」）" % value)
    return value.strip()


def has_duplicate_block(body):
    """內文開頭（略過空白）是否又出現一個 `---` 中繼資料區塊（PO 把完整檔貼進建好的範本）。"""
    lines = body.lstrip().split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return False
    seen_kv = False
    for raw in lines[1:]:
        raw = raw.rstrip("\r")
        if raw == "---":
            return seen_kv
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if not _KV_RE.match(s):
            return False
        seen_kv = True
    return False


def check_body(body):
    """內文檢查：以 str.strip() 判斷是否為空（SQLite CHECK 擋不住全形空白），並偵測重複區塊。"""
    if not isinstance(body, str) or not body.strip():
        raise InboxError("內文為空")
    if has_duplicate_block(body):
        raise InboxError("內文開頭有重複的中繼資料區塊，請移除其中一個")
    return body


# ---------------------------------------------------------------- 路徑守衛、掃描、讀檔

def validate_basename(name):
    """filenames 參數只接受 inbox 最上層檔名：含路徑分隔字元、`..`、指向 processed/ 者拒絕。"""
    if not isinstance(name, str) or not name.strip():
        raise InboxError("檔名不可為空")
    if name != os.path.basename(name) or "/" in name or "\\" in name or "\x00" in name \
            or name in (".", "..") or os.sep in name or (os.altsep and os.altsep in name):
        raise InboxError("檔名只接受資料匣最上層的 basename，不可含路徑：%s" % name)
    if name == PROCESSED_DIRNAME:
        raise InboxError("不可指向 processed/：%s" % name)
    return name


def _resolve_in_inbox(data_dir, name):
    """回 (inbox_real, real_path)。inbox 根目錄與檔案兩邊都 realpath；檔案必須直接位於 inbox 根目錄。"""
    validate_basename(name)
    root = _inbox_real(data_dir)
    real = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(real) != root:
        raise InboxError("檔案不在資料匣最上層（含符號連結逃出資料匣的情形）：%s" % name)
    return root, real


def list_pending(data_dir):
    """掃描 inbox 最上層。回 (待處理檔名清單, skipped_unsupported 檔名清單)，皆排序。
    略過目錄（含 processed/）與以 . 開頭的隱藏檔。"""
    root = _inbox_real(data_dir)
    pending, skipped = [], []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        real = os.path.realpath(os.path.join(root, name))
        if not os.path.isfile(real):
            continue
        if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
            pending.append(name)
        else:
            skipped.append(name)
    return pending, skipped


def read_inbox_file(data_dir, name):
    """讀檔（UTF-8），回文字。檔案不存在丟 FileNotFoundError（呼叫端視為已被搬走）；
    其他問題（路徑不合法、過大、編碼錯誤）丟 InboxError。"""
    root, real = _resolve_in_inbox(data_dir, name)
    size = os.path.getsize(real)             # 檔案不存在 → FileNotFoundError
    if size > MAX_FILE_CHARS * 4:
        raise InboxError("檔案過大（超過 %d 字元上限）" % MAX_FILE_CHARS)
    try:
        with open(real, "rb") as f:
            raw = f.read()
    except IsADirectoryError:
        raise InboxError("不是檔案：%s" % name)
    except PermissionError:
        raise InboxError("檔案不可讀：%s" % name)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InboxError("檔案不是 UTF-8 編碼，請另存為 UTF-8 純文字")
    if len(text) > MAX_FILE_CHARS:
        raise InboxError("檔案過大：%d 字元，超過上限 %d" % (len(text), MAX_FILE_CHARS))
    return text


def _unique_link(src_real, dest_dir, name):
    """把 src 以不覆蓋的方式放到 dest_dir（同名加序號），回最終檔名。"""
    stem, ext = os.path.splitext(name)
    n = 0
    while True:
        cand = name if n == 0 else "%s-%d%s" % (stem, n, ext)
        dst = os.path.join(dest_dir, cand)
        try:
            os.link(src_real, dst)
            return cand, dst, True
        except FileExistsError:
            n += 1
        except FileNotFoundError:
            raise
        except OSError:
            if os.path.lexists(dst):
                n += 1
                continue
            return cand, dst, False      # 不支援硬連結：呼叫端改用 rename


def move_to_processed(data_dir, name):
    """把 inbox 最上層檔案搬進 processed/（同名不覆蓋、加序號）。回搬入後檔名。
    檔案已不存在丟 FileNotFoundError。"""
    root, real = _resolve_in_inbox(data_dir, name)
    if not os.path.lexists(real):
        raise FileNotFoundError(name)
    _, processed = ensure_dirs(data_dir)
    cand, dst, linked = _unique_link(real, os.path.realpath(processed), name)
    if linked:
        try:
            os.unlink(real)
        except FileNotFoundError:
            pass
    else:
        os.rename(real, dst)
    return cand


# ---------------------------------------------------------------- 建檔

def safe_title(title):
    s = _UNSAFE_NAME_RE.sub("_", title or "")
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "untitled"


def build_inbox_filename(date, title, key):
    """`<YYYY-MM-DD>_<安全化標題>_<source_key短雜湊>.md`；標題段截短使主檔名（不含副檔名）不超過 80 字。"""
    short = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    head = "%s_" % date
    tail = "_%s" % short
    room = max(1, MAX_NAME_STEM - len(head) - len(tail))
    t = safe_title(title)[:room].strip("_") or "untitled"
    return "%s%s%s.md" % (head, t, tail)


def _one_line(v):
    return " ".join(str(v).split()) if v is not None else ""


def render_template(meta):
    lines = ["---"]
    for k in KNOWN_KEYS:
        lines.append("%s: %s" % (k, _one_line(meta.get(k))))
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def create_pending_file(data_dir, meta, key):
    """在 inbox 最上層建檔（內文留空），回完整路徑。檔名衝突不覆蓋（加序號）；
    先寫暫存檔再以不覆蓋方式落地，任何失敗都不留半檔。"""
    inbox, _ = ensure_dirs(data_dir)
    root = os.path.realpath(inbox)
    name = build_inbox_filename(meta["date"], meta["title"], key)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_template(meta))
        cand, dst, linked = _unique_link(tmp, root, name)
        if not linked:
            os.rename(tmp, dst)
        return dst
    except Exception as e:
        raise InboxError("建檔失敗：%s" % e)
    finally:
        if os.path.lexists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def find_pending_by_source_key(data_dir, key):
    """資料匣待處理檔中是否已有相同 source_key 的檔案；回完整路徑或 None。無法解析的檔略過。"""
    root = _inbox_real(data_dir)
    pending, _ = list_pending(data_dir)
    for name in pending:
        real = os.path.realpath(os.path.join(root, name))
        if os.path.dirname(real) != root:
            continue
        try:
            with open(real, "rb") as f:
                head = f.read(65536).decode("utf-8", errors="ignore")
            meta, _, _ = parse_inbox_text(head)
            k = identity.source_key(meta.get("url", ""), (meta.get("source_type") or "").lower(),
                                    meta.get("guid"))
        except Exception:
            continue
        if k == key:
            return real
    return None
