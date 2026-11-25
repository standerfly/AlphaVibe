"""Substack 追蹤清單與設定（011）：`<data_dir>/substack_config.json`。

契約：`specs/011-substack-fetch-store/contracts/config-format.md`、`contracts/cli.md §2`。
設計原則（research R5）：
* 設定檔是「是否啟用、顯示名稱、feed 網址、間隔、告警策略、圖片白名單」的**唯一來源**；
  **沒有任何隱性預設值**——檔案不存在就拒絕並要求先 `init`（FR-012 精神）。
* 只透過本 CLI 修改：驗證通過才寫，寫入用暫存檔＋`os.replace`（原子），寫前備份舊檔（保留 10 份）。
* 第一步一律 `article_data_guard.resolve_data_dir()`：指向正式資料目錄要有明確旗標才允許
  （2026-08-22 資產表污染事故教訓）。

本包只實作 `init`／`show`／`validate`；`add`／`enable`／`disable`／`set-interval`／
`set-alert-policy`／`add-image-host`／`remove-image-host` 在後續任務加入。

僅標準庫、Python 3.9 相容。
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import article_data_guard  # noqa: E402

CONFIG_FILENAME = "substack_config.json"
BACKUP_SUFFIX = ".bak-"
BACKUPS_KEPT = 10

MIN_POLL_MINUTES = 10
MAX_POLL_MINUTES = 1440
ALERT_POLICIES = ("every_failure", "consecutive_3")
MAX_IMAGE_HOSTS = 20
MAX_AUTHORS = 20
MAX_NAME_LEN = 60
FEED_PATH = "/feed"

TOP_FIELDS = ("version", "min_poll_interval_minutes", "alert_policy", "image_hosts", "authors")
AUTHOR_FIELDS = ("key", "name", "feed_url", "enabled")

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# 契約「初始內容」（FOMO 的網址首跑確認，若 www 網域不通改用 fomosoc.substack.com/feed）
INITIAL_CONFIG = {
    "version": 1,
    "min_poll_interval_minutes": 30,
    "alert_policy": "every_failure",
    "image_hosts": ["substackcdn.com", "substack-post-media.s3.amazonaws.com"],
    "authors": [
        {"key": "fomosoc", "name": "FOMO研究院電子報",
         "feed_url": "https://www.fomosoc.com/feed", "enabled": True},
        {"key": "unclestocknotes", "name": "大叔美股筆記",
         "feed_url": "https://unclestocknotes.substack.com/feed", "enabled": True},
    ],
}

EXIT_OK = 0
EXIT_REFUSED = 2


class ConfigMissing(RuntimeError):
    """設定檔不存在：不猜、不用預設值，請先執行 init。"""


class ConfigInvalid(RuntimeError):
    def __init__(self, reasons):
        self.reasons = list(reasons)
        RuntimeError.__init__(self, "；".join(self.reasons))


# ---------------------------------------------------------------- 驗證
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_hostname(value):
    if not isinstance(value, str) or not value or value != value.lower():
        return False
    if not _HOST_RE.match(value):
        return False
    labels = value.split(".")
    if all(label.isdigit() for label in labels):     # 純數字＝IP，不收
        return False
    return True


def config_path(data_dir):
    return os.path.join(os.path.realpath(os.path.abspath(data_dir)), CONFIG_FILENAME)


def _validate_feed_url(value, reasons, label):
    if not isinstance(value, str) or not value:
        reasons.append("%s.feed_url 必須是字串" % label)
        return
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(value)
    except ValueError:
        reasons.append("%s.feed_url 無法解析" % label)
        return
    if parts.scheme != "https":
        reasons.append("%s.feed_url 必須是 https://" % label)
        return
    if "@" in (parts.netloc or ""):
        reasons.append("%s.feed_url 不得含帳號密碼" % label)
        return
    try:
        port = parts.port
    except ValueError:
        reasons.append("%s.feed_url 的埠無效" % label)
        return
    if port is not None:
        reasons.append("%s.feed_url 不得指定埠" % label)
        return
    if parts.query or parts.fragment:
        reasons.append("%s.feed_url 不得含 query 或 fragment" % label)
        return
    if parts.path != FEED_PATH:
        reasons.append("%s.feed_url 的路徑必須恰為 %s（收到 %r）"
                       % (label, FEED_PATH, parts.path))
        return
    host = (parts.hostname or "").lower()
    if not _is_hostname(host):
        reasons.append("%s.feed_url 的主機不得為 IP／localhost／空值" % label)


def validate(cfg):
    """回傳不合格原因清單（空清單＝合格）。任一不符＝整份不合格（契約）。"""
    reasons = []
    if not isinstance(cfg, dict):
        return ["設定檔最外層必須是 JSON 物件"]
    for key in cfg:
        if key not in TOP_FIELDS:
            reasons.append("未知欄位 %s（不允許未列出的欄位）" % key)
    for key in TOP_FIELDS:
        if key not in cfg:
            reasons.append("缺少欄位 %s" % key)
    if "version" in cfg and cfg["version"] != 1 or (
            "version" in cfg and not _is_int(cfg.get("version"))):
        reasons.append("version 必須為整數 1")
    if "min_poll_interval_minutes" in cfg:
        value = cfg["min_poll_interval_minutes"]
        if not _is_int(value) or not (MIN_POLL_MINUTES <= value <= MAX_POLL_MINUTES):
            reasons.append("min_poll_interval_minutes 必須是 %d～%d 的整數（下限 %d 分鐘）"
                           % (MIN_POLL_MINUTES, MAX_POLL_MINUTES, MIN_POLL_MINUTES))
    if "alert_policy" in cfg and cfg["alert_policy"] not in ALERT_POLICIES:
        reasons.append("alert_policy 只能是 %s" % " 或 ".join(ALERT_POLICIES))
    if "image_hosts" in cfg:
        hosts = cfg["image_hosts"]
        if not isinstance(hosts, list):
            reasons.append("image_hosts 必須是陣列")
        elif len(hosts) > MAX_IMAGE_HOSTS:
            reasons.append("image_hosts 最多 %d 個" % MAX_IMAGE_HOSTS)
        else:
            for host in hosts:
                if not _is_hostname(host):
                    reasons.append("image_hosts 的 %r 必須是小寫主機名（不得含路徑／埠／IP）"
                                   % (host,))
    if "authors" in cfg:
        reasons.extend(_validate_authors(cfg["authors"]))
    return reasons


def _validate_authors(authors):
    reasons = []
    if not isinstance(authors, list):
        return ["authors 必須是陣列"]
    if not 1 <= len(authors) <= MAX_AUTHORS:
        reasons.append("authors 必須有 1～%d 位（收到 %d）" % (MAX_AUTHORS, len(authors)))
    keys, urls = [], []
    for idx, author in enumerate(authors):
        label = "authors[%d]" % idx
        if not isinstance(author, dict):
            reasons.append("%s 必須是物件" % label)
            continue
        for field in author:
            if field not in AUTHOR_FIELDS:
                reasons.append("%s 未知欄位 %s" % (label, field))
        for field in AUTHOR_FIELDS:
            if field not in author:
                reasons.append("%s 缺少欄位 %s" % (label, field))
        key = author.get("key")
        if not isinstance(key, str) or not _KEY_RE.match(key or ""):
            reasons.append("%s.key 必須符合 ^[a-z0-9][a-z0-9-]{1,39}$" % label)
        else:
            keys.append(key)
        name = author.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME_LEN:
            reasons.append("%s.name 必須是 1～%d 字的字串" % (label, MAX_NAME_LEN))
        if "feed_url" in author:
            _validate_feed_url(author.get("feed_url"), reasons, label)
        if not isinstance(author.get("enabled"), bool):
            reasons.append("%s.enabled 必須是 true／false" % label)
        if isinstance(author.get("feed_url"), str):
            urls.append(author["feed_url"])
    if len(set(keys)) != len(keys):
        reasons.append("authors 的 key 不得重複")
    if len(set(urls)) != len(urls):
        reasons.append("authors 的 feed_url 不得重複")
    return reasons


def allowed_image_hosts(cfg):
    """圖片下載白名單＝設定的 image_hosts ＋各作者 feed 主機（自動允許，FR-034）。"""
    from urllib.parse import urlsplit
    hosts = set(cfg.get("image_hosts") or ())
    for author in cfg.get("authors") or ():
        if isinstance(author, dict) and isinstance(author.get("feed_url"), str):
            host = (urlsplit(author["feed_url"]).hostname or "").lower()
            if host:
                hosts.add(host)
    return sorted(hosts)


# ---------------------------------------------------------------- 讀寫
def load_config(data_dir):
    path = config_path(data_dir)
    if not os.path.isfile(path):
        raise ConfigMissing("設定檔不存在（%s）；請先執行 init，不使用任何預設值" % CONFIG_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except ValueError as exc:
        raise ConfigInvalid(["設定檔不是合法 JSON：%s" % exc])
    except OSError as exc:
        raise ConfigInvalid(["設定檔讀取失敗：%s" % exc.strerror])
    reasons = validate(cfg)
    if reasons:
        raise ConfigInvalid(reasons)
    return cfg


def raw_text(data_dir):
    path = config_path(data_dir)
    if not os.path.isfile(path):
        raise ConfigMissing("設定檔不存在（%s）" % CONFIG_FILENAME)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _backup_name(path, now_text):
    candidate = "%s%s%s" % (path, BACKUP_SUFFIX, now_text)
    suffix = 1
    while os.path.exists(candidate):
        candidate = "%s%s%s-%d" % (path, BACKUP_SUFFIX, now_text, suffix)
        suffix += 1
    return candidate


def _prune_backups(path):
    existing = sorted(glob.glob(path + BACKUP_SUFFIX + "*"))
    for old in existing[:-BACKUPS_KEPT] if len(existing) > BACKUPS_KEPT else []:
        try:
            os.remove(old)
        except OSError:
            pass


def write_config(data_dir, cfg, now_text=None):
    """驗證 → 備份舊檔 → 暫存檔＋os.replace（原子）。失敗不動舊檔、不留暫存檔。"""
    reasons = validate(cfg)
    if reasons:
        raise ConfigInvalid(reasons)
    path = config_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        import datetime
        stamp = now_text or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = _backup_name(path, stamp)
        with open(path, "rb") as src:
            data = src.read()
        with open(target, "wb") as dst:
            dst.write(data)
        _prune_backups(path)
    tmp = "%s.tmp-%d" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    return cfg


# ---------------------------------------------------------------- CLI
class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):           # 不要直接 sys.exit，讓 run()／main() 回退出碼
        raise _ArgError(message)

    def exit(self, status=0, message=None):
        raise _ArgError(message or "")


def build_parser():
    parser = _Parser(prog="substack_config.py", add_help=True,
                     description="Substack 追蹤清單與設定（011）")
    parser.add_argument("--data-dir", dest="data_dir", default=None,
                        help="資料目錄（必填；指向正式庫需 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="建立初始設定檔（已存在則拒絕）")
    sub.add_parser("show", help="印出設定全文")
    sub.add_parser("validate", help="只檢查合法性")
    return parser


def main(argv=None, env=None, out=None, err=None):
    out = sys.stdout if out is None else out
    err = out if err is None else err
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _ArgError as exc:
        if str(exc):
            err.write(str(exc).rstrip() + "\n")
        return EXIT_REFUSED
    try:
        data_dir = article_data_guard.resolve_data_dir(args.data_dir, env=env)
    except article_data_guard.DataDirRefused as exc:
        err.write("拒絕執行：%s\n" % exc)
        return EXIT_REFUSED
    if not args.command:
        err.write("請指定子命令：init／show／validate\n")
        return EXIT_REFUSED
    if args.command == "init":
        return _cmd_init(data_dir, out, err)
    if args.command == "show":
        return _cmd_show(data_dir, out, err)
    return _cmd_validate(data_dir, out, err)


def _cmd_init(data_dir, out, err):
    path = config_path(data_dir)
    if os.path.exists(path):
        err.write("拒絕執行：設定檔已存在（%s），init 不覆寫\n" % CONFIG_FILENAME)
        return EXIT_REFUSED
    write_config(data_dir, json.loads(json.dumps(INITIAL_CONFIG)))
    out.write("已建立 %s（%d 位作者）\n" % (CONFIG_FILENAME, len(INITIAL_CONFIG["authors"])))
    return EXIT_OK


def _cmd_show(data_dir, out, err):
    try:
        out.write(raw_text(data_dir))
    except ConfigMissing as exc:
        err.write("%s\n" % exc)
        return EXIT_REFUSED
    except OSError as exc:
        err.write("設定檔讀取失敗：%s\n" % exc.strerror)
        return EXIT_REFUSED
    return EXIT_OK


def _cmd_validate(data_dir, out, err):
    try:
        load_config(data_dir)
    except ConfigMissing as exc:
        err.write("%s\n" % exc)
        return EXIT_REFUSED
    except ConfigInvalid as exc:
        for reason in exc.reasons:
            err.write("不合格：%s\n" % reason)
        return EXIT_REFUSED
    out.write("OK\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
