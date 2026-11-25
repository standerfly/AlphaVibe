"""Substack 文章匯入（011）：排程進入點＋PO 的手動操作（contracts/cli.md §1）。

共通規則：
* `--data-dir` 必填、**最先檢查**（`article_data_guard.resolve_data_dir()`）：在讀設定、開庫、
  發任何請求之前就拒絕指向正式資料目錄而沒有明確旗標的呼叫（2026-08-22 事故教訓）。
* 整次執行持一把專屬執行鎖 `<data_dir>/.substack_import.lock`（flock，非阻塞）；
  拿不到＝忙碌：印一行、**不寫庫**、exit 3（FR-017）。
* stdout／stderr 只含作者代號、內部 id、HTTP 狀態、結果代碼、計數、時間、空間數字；
  **不含**標題、內文、文章網址、圖片網址、token（FR-026）。
* 零模型、零登入：本模組不開子行程、不讀鑰匙圈（FR-019；由靜態測試守門）。
* 依賴注入（`http`／`notifier`／`clock`／`sleep`／`env`／`out`／`err`）比照既有匯入腳本的
  `run(argv, **deps)` 慣例，測試一律注入假物件。

退出碼（contracts/cli.md 共通規則）：
  0 完成（含無新文章）｜1 有作者失敗或牆鐘預算中止｜2 參數／資料目錄／設定檔拒絕｜
  3 忙碌（鎖被占用，未寫庫）｜4 中止（磁碟寫入失敗）｜5 手動轉寫因使用量上限／登入問題中止

動作在各自的任務接上；未實作者一律回 exit 2 並印代碼 `not_implemented`（不假裝成功）。

僅標準庫、Python 3.9 相容。
"""
import argparse
import datetime
import fcntl
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import article_data_guard  # noqa: E402
import substack_config  # noqa: E402
import substack_reclassify  # noqa: E402
import substack_store  # noqa: E402

LOCK_NAME = ".substack_import.lock"
RUN_BUDGET_SEC = 1200           # 單次執行牆鐘預算 20 分鐘（research R2）
TZ8 = datetime.timezone(datetime.timedelta(hours=8))

EXIT_OK = 0
EXIT_AUTHOR_FAILED = 1
EXIT_REFUSED = 2
EXIT_BUSY = 3
EXIT_DISK = 4
EXIT_USAGE_LIMIT = 5

NOT_IMPLEMENTED = "not_implemented"
# 需要取鎖的動作（唯讀動作不取鎖）
LOCKED_ACTIONS = ("run", "backfill", "retry_images", "reclassify")
READONLY_ACTIONS = ("reclassify_history", "status")
# 需要設定檔的動作（重判只讀已存文章，不需要設定檔）
CONFIG_ACTIONS = ("run", "backfill", "retry_images")


class _RealClock(object):
    def now(self):
        return datetime.datetime.now(TZ8)

    def monotonic(self):
        return time.monotonic()


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)

    def exit(self, status=0, message=None):
        raise _ArgError(message or "")


def build_parser():
    parser = _Parser(prog="substack_import.py", add_help=True,
                     description="Substack 文章匯入（011）")
    parser.add_argument("--data-dir", dest="data_dir", default=None,
                        help="資料目錄（必填；指向正式庫需 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1）")
    parser.add_argument("--scheduled", action="store_true",
                        help="launchd 專用：先做排程日判斷再執行完整流程")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="零網路、不寫庫；列出會做什麼")
    parser.add_argument("--backfill", dest="backfill", default=None, metavar="AUTHOR_KEY",
                        help="手動追補單一作者（忽略 14 天窗）")
    parser.add_argument("--retry-images", dest="retry_images", default=None, metavar="IMAGE_IDS",
                        help="逗號分隔 image_id：重設失敗次數後立即重試一次")
    parser.add_argument("--reclassify", action="store_true",
                        help="重新判斷完整度（零網路、零模型；原判斷不覆寫）")
    parser.add_argument("--article-ids", dest="article_ids", default=None, metavar="IDS",
                        help="搭 --reclassify：逗號分隔的內部文章 id")
    parser.add_argument("--author", dest="author", default=None, metavar="AUTHOR_KEY",
                        help="搭 --reclassify：該作者全部已存文章")
    parser.add_argument("--reclassify-history", dest="reclassify_history", default=None,
                        metavar="ARTICLE_IDS", help="唯讀：列出原判斷與全部重判紀錄")
    parser.add_argument("--status", action="store_true", help="唯讀摘要")
    return parser


def _action_of(args):
    """回傳 (動作名稱, 拒絕原因)；拒絕原因非 None 時一律 exit 2。"""
    chosen = []
    if args.backfill:
        chosen.append("backfill")
    if args.retry_images:
        chosen.append("retry_images")
    if args.reclassify:
        chosen.append("reclassify")
    if args.reclassify_history:
        chosen.append("reclassify_history")
    if args.status:
        chosen.append("status")
    if len(chosen) > 1:
        return None, "互斥選項不得同時使用：%s" % "、".join(sorted(chosen))
    action = chosen[0] if chosen else "run"
    if action != "reclassify" and (args.article_ids or args.author):
        return None, "--article-ids／--author 只能搭 --reclassify 使用"
    if action == "reclassify":
        if bool(args.article_ids) == bool(args.author):
            return None, "--reclassify 必須指定 --article-ids 或 --author（兩者只能一個）"
    if args.scheduled and action != "run":
        return None, "--scheduled 只用於完整流程，不能搭其他動作"
    if args.dry_run and action in ("backfill", "retry_images", "status",
                                   "reclassify_history"):
        return None, "--dry-run 不適用於 %s" % action
    return action, None


class Context(object):
    """一次執行的所有依賴與狀態（給 dispatch 用）。"""

    def __init__(self, args, action, data_dir, cfg, store, http, notifier, clock, sleep,
                 env, out, err, started_mono):
        self.args = args
        self.action = action
        self.data_dir = data_dir
        self.cfg = cfg
        self.store = store
        self.http = http
        self.notifier = notifier
        self.clock = clock
        self.sleep = sleep
        self.env = env
        self.out = out
        self.err = err
        self.started_mono = started_mono

    def say(self, text):
        self.out.write(text + "\n")

    def warn(self, text):
        self.err.write(text + "\n")

    def remaining(self):
        """剩餘牆鐘預算秒數（research R2）。"""
        return max(0, RUN_BUDGET_SEC - (self.clock.monotonic() - self.started_mono))


def _parse_ids(text):
    ids, bad = [], []
    for piece in str(text or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            ids.append(int(piece))
        except ValueError:
            bad.append(piece)
    return ids, bad


def dispatch(ctx):
    """執行選定的動作。模組層級函式，方便測試替換。"""
    if ctx.action == "reclassify":
        return _do_reclassify(ctx)
    if ctx.action == "reclassify_history":
        return _do_reclassify_history(ctx)
    ctx.warn("尚未實作的動作：%s（代碼 %s）" % (ctx.action, NOT_IMPLEMENTED))
    return EXIT_REFUSED


# ---------------------------------------------------------------- US2：重判（FR-033）
def _do_reclassify(ctx):
    """零網路、零模型：不建立 http／notifier，只讀 content_html 重判並新增重判紀錄。"""
    ids = None
    if ctx.args.article_ids:
        ids, bad = _parse_ids(ctx.args.article_ids)
        if bad:
            ctx.warn("--article-ids 只接受整數，無法解析：%s" % "、".join(bad))
            return EXIT_REFUSED
    run_id = None
    if not ctx.args.dry_run:
        run_id = ctx.store.start_run("reclassify")
    trigger = (substack_reclassify.TRIGGER_ARTICLE if ids is not None
               else substack_reclassify.TRIGGER_AUTHOR)
    report = substack_reclassify.reclassify(
        ctx.store, article_ids=ids, author=ctx.args.author, dry_run=ctx.args.dry_run,
        trigger=trigger, run_id=run_id, clock=ctx.clock)
    _print_reclassify_report(ctx, report)
    code = EXIT_AUTHOR_FAILED if report["missing_ids"] else EXIT_OK
    if run_id is not None:
        ctx.store.finish_run(run_id, result="ok" if code == EXIT_OK else "partial")
    return code


def _print_reclassify_report(ctx, report):
    """只印計數與內部 id，不含標題（FR-026）。"""
    prefix = "reclassify（dry-run）" if report["dry_run"] else "reclassify"
    detail = "、".join("%s→%s ×%d" % (old, new, count)
                       for (old, new), count in sorted(report["transitions"].items())) or "無"
    ctx.say("%s：檢查 %d 篇、未變 %d 篇、改變 %d 篇（%s）"
            % (prefix, report["checked"], report["unchanged"], report["changed"], detail))
    for row in report["rows"]:
        if row["changed"]:
            ctx.say("  id=%d %s→%s（%s）" % (row["article_id"], row["old_completeness"],
                                             row["new_completeness"], row["new_reason"]))
    for article_id in report["missing_ids"]:
        ctx.warn("  找不到文章 id=%s（略過；整體以 exit 1 回報）" % article_id)


def _do_reclassify_history(ctx):
    """唯讀：列出原判斷與全部重判紀錄。"""
    ids, bad = _parse_ids(ctx.args.reclassify_history)
    if bad:
        ctx.warn("--reclassify-history 只接受整數，無法解析：%s" % "、".join(bad))
        return EXIT_REFUSED
    rows = substack_reclassify.history(ctx.store, ids)
    found = {row["article_id"] for row in rows}
    for row in rows:
        ctx.say("id=%d 原判斷=%s（%s） 有效=%s 重判 %d 次"
                % (row["article_id"], row["original_completeness"], row["original_reason"],
                   row["effective_completeness"], len(row["reclassifications"])))
        for item in row["reclassifications"]:
            ctx.say("  %s %s→%s（%s；規則 %s；trigger=%s）"
                    % (item["at"], item["old_completeness"], item["new_completeness"],
                       item["new_reason"], item["rule_version"], item["trigger"]))
    missing = [i for i in ids if i not in found]
    for article_id in missing:
        ctx.warn("找不到文章 id=%s" % article_id)
    return EXIT_AUTHOR_FAILED if missing else EXIT_OK


# ---------------------------------------------------------------- 進入點
def run(argv=None, http=None, notifier=None, clock=None, sleep=None, env=None, out=None,
        err=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    clock = clock or _RealClock()
    sleep = sleep if sleep is not None else time.sleep
    argv = sys.argv[1:] if argv is None else list(argv)

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _ArgError as exc:
        if str(exc):
            err.write(str(exc).rstrip() + "\n")
        return EXIT_REFUSED

    action, refusal = _action_of(args)
    if refusal:
        err.write("拒絕執行：%s\n" % refusal)
        return EXIT_REFUSED

    try:
        data_dir = article_data_guard.resolve_data_dir(args.data_dir, env=env)
    except article_data_guard.DataDirRefused as exc:
        err.write("拒絕執行：%s\n" % exc)
        return EXIT_REFUSED

    cfg = None
    if action in CONFIG_ACTIONS:
        try:
            cfg = substack_config.load_config(data_dir)
        except substack_config.ConfigMissing as exc:
            err.write("拒絕執行：%s\n" % exc)
            return EXIT_REFUSED
        except substack_config.ConfigInvalid as exc:
            err.write("拒絕執行：設定檔不合格\n")
            for reason in exc.reasons:
                err.write("  %s\n" % reason)
            return EXIT_REFUSED

    lock_handle = None
    if action in LOCKED_ACTIONS:
        lock_path = os.path.join(data_dir, LOCK_NAME)
        lock_handle = open(lock_path, "w")
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_handle.close()
            out.write("忙碌：另一個 substack 執行正在進行，本次不寫庫\n")
            return EXIT_BUSY

    store = None
    try:
        readonly = action in READONLY_ACTIONS or (action == "reclassify" and args.dry_run)
        try:
            if readonly:
                store = substack_store.SubstackStore.open_readonly(data_dir)
            else:
                store = substack_store.SubstackStore(data_dir)
        except FileNotFoundError as exc:
            err.write("拒絕執行：%s\n" % exc)
            return EXIT_REFUSED
        ctx = Context(args, action, data_dir, cfg, store, http, notifier, clock, sleep,
                      env, out, err, clock.monotonic())
        try:
            return dispatch(ctx)
        except substack_store.DiskFullError:
            err.write("中止：磁碟或資料庫空間不足（已回滾，未留半寫入紀錄）\n")
            return EXIT_DISK
    finally:
        if store is not None:
            store.close()
        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_handle.close()


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
