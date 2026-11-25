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
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import article_data_guard  # noqa: E402
import notify  # noqa: E402
import substack_config  # noqa: E402
import substack_feed  # noqa: E402
import substack_html  # noqa: E402
import substack_reclassify  # noqa: E402
import substack_store  # noqa: E402

LOCK_NAME = ".substack_import.lock"
RUN_BUDGET_SEC = 1200           # 單次執行牆鐘預算 20 分鐘（research R2）
TZ8 = datetime.timezone(datetime.timedelta(hours=8))

WINDOW_DAYS = 14                # 首次／重新啟用只收這麼多天內的文章（FR-008）
AUTHOR_GAP_SEC = 5              # 作者與作者之間的禮貌間隔（research R6）
NOTIFY_GAP_SEC = 1.5            # 通知節流（research R4）
FEED_FULL_PAGE = 20             # feed 每次固定提供的篇數；全為新文時提示可能漏文
SCHEDULE_HOUR = 22              # 主排程時刻；排程日＝啟動時刻減 22 小時的日期（FR-017）
DEFER_FROM_HOUR = 23            # 23:00～00:59 啟動 → 延後交給 01:00 補跑（FR-017）
DEFER_TO_HOUR = 1

SOURCE_SCHEDULE = "schedule"
SOURCE_MANUAL = "manual"
NO_TITLE = "（無標題）"

COMPLETENESS_LABEL = {"F": "全文", "P": "僅預覽", "N": "非文字"}
# N 類的固定提醒句：逐字同 contracts/notifications.md §1（FR-035，PO 決定 Q14）
NON_TEXT_REMINDER = "⚠️ 此文為非文字、內文未保存，請決定是否要處理。"
TRIGGER_LABEL = {"schedule": "排程", "catchup": "補跑", "manual": "手動", "backfill": "追補"}

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
    if ctx.action == "run":
        return _do_run(ctx)
    if ctx.action == "reclassify":
        return _do_reclassify(ctx)
    if ctx.action == "reclassify_history":
        return _do_reclassify_history(ctx)
    ctx.warn("尚未實作的動作：%s（代碼 %s）" % (ctx.action, NOT_IMPLEMENTED))
    return EXIT_REFUSED


# ---------------------------------------------------------------- 排程日與時間（FR-017）
def schedule_day(now):
    """排程日＝當日 22:00 起至次日 21:59，以「啟動時刻減 22 小時」的日期表示。"""
    return (now - datetime.timedelta(hours=SCHEDULE_HOUR)).date().isoformat()


def in_defer_window(now):
    """23:00～00:59 啟動：不執行、延後交給 01:00 補跑（避開 010 的 23:00／23:40 排程）。"""
    return now.hour >= DEFER_FROM_HOUR or now.hour < DEFER_TO_HOUR


def window_from_text(activated_at):
    """14 天窗起點：啟用當天的台北日期往前 14 天（FR-008）。"""
    return (activated_at.date() - datetime.timedelta(days=WINDOW_DAYS)).isoformat()


def _parse_iso(text):
    try:
        return datetime.datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 通知文字（FR-025、FR-035）
def format_article_notice(display_name, title, completeness):
    """逐篇通知：作者＋標題＋完整度，**沒有連結**；N 類多一行固定提醒（FR-035）。"""
    lines = ["📰 Substack 新文章｜%s" % display_name,
             title,
             "完整度：%s" % COMPLETENESS_LABEL[completeness]]
    if completeness == "N":
        lines.append(NON_TEXT_REMINDER)
    return "\n".join(lines)


def format_summary(trigger, counts, space_line, missed_hints=(), unnotified=0):
    """摘要：只列各類篇數（含非文字），**不附 N 類提醒句**（Q15）；空間只報現況。"""
    lines = ["📚 Substack 匯入（%s）：新增 %d 篇（全文 %d／僅預覽 %d／非文字 %d）"
             % (TRIGGER_LABEL.get(trigger, trigger), counts.get("new", 0), counts.get("F", 0),
                counts.get("P", 0), counts.get("N", 0)),
             "圖片：本次下載 %d 張、缺圖待補 %d 張、放棄累計 %d 張"
             % (counts.get("images_downloaded", 0), counts.get("images_missing", 0),
                counts.get("images_abandoned", 0)),
             space_line]
    for name, count in missed_hints:
        lines.append("提示：%s 本次 feed 的 %d 篇皆為新文，兩次輪詢之間可能有漏文（只提示，不補救）"
                     % (name, count))
    if unnotified:
        lines.append("通知：%d 篇尚未通知成功，下次執行補發" % unnotified)
    return "\n".join(lines)


# ---------------------------------------------------------------- US1：完整流程（FR-001～FR-009）
class _RunState(object):
    """一次執行的計數器。圖片計數留給 US3（T031／T032）填，本階段恆為 0。"""

    def __init__(self):
        self.authors_polled = 0
        self.authors_skipped_interval = 0
        self.authors_failed = 0
        self.polled_any = False
        self.new_articles = []
        self.completeness = {"P": 0, "F": 0, "N": 0}
        self.images_downloaded = 0
        self.images_missing = 0
        self.images_abandoned_now = 0
        self.images_abandoned_total = 0
        self.notify_sent = 0
        self.notify_failed = 0
        self.notify_articles = 0
        self.notify_summary = 0
        self.notify_attempted = set()
        self.budget_exhausted = False
        self.missed_hints = []
        self.alerts = 0                     # 告警在 US4（T036）接上

    def counters(self):
        return {"authors_polled": self.authors_polled,
                "authors_skipped_interval": self.authors_skipped_interval,
                "authors_failed": self.authors_failed,
                "new_articles": len(self.new_articles),
                "images_downloaded": self.images_downloaded,
                "images_missing": self.images_missing,
                "images_abandoned_now": self.images_abandoned_now,
                "notify_sent": self.notify_sent,
                "notify_failed": self.notify_failed,
                "budget_exhausted": 1 if self.budget_exhausted else 0}


def _do_run(ctx):
    """完整流程（contracts/cli.md §1 步驟 1～7）。"""
    now = ctx.clock.now()
    if ctx.args.scheduled:
        day = schedule_day(now)
        trigger = "schedule" if now.hour == SCHEDULE_HOUR else "catchup"
        # 延後判斷先於「已執行」判斷：22:00 跑過之後 23:30 醒來仍記 deferred（research R2）
        if in_defer_window(now):
            return _record_non_run(ctx, trigger, day, "deferred",
                                   "延後至 01:00 補跑（23:00～00:59 不執行）")
        if ctx.store.has_actual_scheduled_run(day):
            return _record_non_run(ctx, trigger, day, "already_done",
                                   "本排程日已執行過，本次不重複抓取")
    else:
        day, trigger = None, "manual"

    run_id = ctx.store.start_run(trigger, schedule_day=day,
                                 started_at=now.isoformat(timespec="seconds"))
    ctx.say("[%s] substack run#%d trigger=%s day=%s"
            % (now.strftime("%Y-%m-%d %H:%M:%S"), run_id, trigger, day or "-"))
    state = _RunState()
    source = SOURCE_SCHEDULE if ctx.args.scheduled else SOURCE_MANUAL
    result, code = "ok", EXIT_OK
    try:
        authors = _sync_authors(ctx, now)
        _notify_backlog(ctx, state)                         # 步驟 3：先補發先前未成功的通知
        for entry in authors:                               # 步驟 4：逐位啟用作者
            if ctx.remaining() <= 0:
                state.budget_exhausted = True
                break
            _poll_author(ctx, state, entry, run_id, source)
        # 步驟 5（圖片下載）在 US3／T032 接上；本階段只建立 pending 圖片列
        if not state.budget_exhausted and ctx.remaining() <= 0:
            state.budget_exhausted = True
        if state.budget_exhausted:
            result, code = "aborted_budget", EXIT_AUTHOR_FAILED
            ctx.warn("中止：牆鐘預算 %d 秒用完，未發出的通知維持 pending，下次執行補發"
                     % RUN_BUDGET_SEC)
        else:
            _notify_new(ctx, state)                         # 步驟 6
            _notify_summary(ctx, state, trigger)
        if result == "ok" and state.authors_failed:
            result, code = "partial", EXIT_AUTHOR_FAILED
    except substack_store.DiskFullError:
        ctx.store.finish_run(run_id, result="aborted_disk", **state.counters())
        raise
    _print_run_counters(ctx, state)
    ctx.store.finish_run(run_id, result=result, **state.counters())        # 步驟 7
    end = ctx.clock.now()
    ctx.say("[%s] done result=%s duration=%ds"
            % (end.strftime("%Y-%m-%d %H:%M:%S"), result,
               int((end - now).total_seconds())))
    return code


def _record_non_run(ctx, trigger, day, result, message):
    """deferred／already_done：只寫一列 run、零網路、不發通知（data-model §1.5 註）。"""
    run_id = ctx.store.start_run(trigger, schedule_day=day)
    ctx.store.finish_run(run_id, result=result)
    ctx.say("run#%d trigger=%s day=%s result=%s：%s" % (run_id, trigger, day, result, message))
    return EXIT_OK


def _sync_authors(ctx, now):
    """步驟 2：依設定檔同步 author 表，回傳本次要輪詢的啟用作者（設定檔順序）。"""
    enabled = []
    for entry in ctx.cfg["authors"]:
        key = entry["key"]
        before = ctx.store.get_author(key)
        ctx.store.upsert_author(key, entry["name"], entry["feed_url"])
        if entry.get("enabled"):
            fresh = (before is None or not before.get("activated_at")
                     or not before.get("last_seen_enabled"))
            if fresh:                           # 首次或重新啟用：重寫 14 天窗的基準（FR-008）
                ctx.store.activate_author(key, now.isoformat(timespec="seconds"),
                                          window_from_text(now))
            else:
                ctx.store.note_author_enabled(key, True)
            enabled.append(entry)
        else:
            ctx.store.note_author_enabled(key, False)
    return enabled


def _display_name(ctx, author_key):
    """通知與摘要用的出版名稱（來自 PO 自己的設定檔，不是文章內容）。"""
    for entry in (ctx.cfg or {}).get("authors", ()):
        if entry.get("key") == author_key:
            return entry.get("name") or author_key
    row = ctx.store.get_author(author_key)
    if row and row.get("display_name"):
        return row["display_name"]
    return author_key


def _fetcher(ctx):
    return ctx.http if ctx.http is not None else substack_feed.default_fetch


def _interval_wait_minutes(ctx, author):
    """還要等幾分鐘才能再輪詢這位作者（0＝可以請求）；FR-004。"""
    last = _parse_iso((author or {}).get("last_request_at"))
    if last is None:
        return 0
    need = int(ctx.cfg["min_poll_interval_minutes"]) * 60
    elapsed = (ctx.clock.now() - last).total_seconds()
    if elapsed < 0 or elapsed >= need:
        return 0
    return int(math.ceil((need - elapsed) / 60.0))


def _poll_author(ctx, state, entry, run_id, source):
    """單一作者：最小間隔 → robots → 條件請求 → 解析 → 去重 → 14 天窗 → 分類 → 逐篇寫入。"""
    key = entry["key"]
    author = ctx.store.get_author(key)
    wait = _interval_wait_minutes(ctx, author)
    if wait > 0:
        at = ctx.clock.now().isoformat(timespec="seconds")
        ctx.store.record_feed_request(key, at, "skipped_interval", requested=False,
                                      count_failure=False)
        ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=0,
                               outcome="skipped_interval")
        state.authors_skipped_interval += 1
        ctx.say("  %s: skipped_interval wait=%d min" % (key, wait))
        return

    if state.polled_any:
        ctx.sleep(AUTHOR_GAP_SEC)
    state.polled_any = True
    started_mono = ctx.clock.monotonic()

    gate = substack_feed.RobotsGate(ctx.store, _fetcher(ctx), ctx.clock)
    allowed, robots_outcome = gate.allowed(entry["feed_url"], remaining=ctx.remaining())
    if not allowed:
        # robots 判斷失敗沒有發出 feed 請求，但 data-model §2.4 明定算一次失敗
        _record_author_failure(ctx, state, key, robots_outcome, run_id, started_mono,
                               requested=False)
        return

    result = substack_feed.fetch_feed(_fetcher(ctx), entry["feed_url"],
                                      etag=(author or {}).get("etag"),
                                      remaining=ctx.remaining())
    outcome, status = result["outcome"], result["status"]
    at = ctx.clock.now().isoformat(timespec="seconds")
    if outcome == "not_modified":
        ctx.store.record_feed_request(key, at, outcome, http_status=status,
                                      etag=result["etag"], success=True)
        ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=1,
                               http_status=status, outcome=outcome,
                               duration_ms=_ms_since(ctx, started_mono))
        state.authors_polled += 1
        ctx.say("  %s: 304" % key)
        return
    if outcome != "ok_200":
        _record_author_failure(ctx, state, key, outcome, run_id, started_mono,
                               requested=True, http_status=status)
        return

    ctx.store.record_feed_request(key, at, outcome, http_status=status, etag=result["etag"],
                                  success=True)
    state.authors_polled += 1
    tally = _store_items(ctx, state, entry, result["items"] or [], source)
    all_new = 1 if (tally["items"] >= FEED_FULL_PAGE and tally["stored"] == tally["items"]) else 0
    if all_new:
        state.missed_hints.append((_display_name(ctx, key), tally["items"]))
    ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=1, http_status=status,
                           outcome=outcome, items_in_feed=tally["items"],
                           new_items=tally["stored"], skipped_window=tally["window"],
                           skipped_no_pubdate=tally["no_pubdate"], all_new=all_new,
                           duration_ms=_ms_since(ctx, started_mono))
    extra = ""
    for label, value in (("dup", tally["duplicate"]), ("dedupe_conflict", tally["conflict"]),
                         ("no_pubdate", tally["no_pubdate"]), ("invalid", tally["invalid"])):
        if value:
            extra += " %s=%d" % (label, value)
    ctx.say("  %s: %s items=%d new=%d window_skip=%d (P=%d F=%d N=%d)%s"
            % (key, status, tally["items"], tally["stored"], tally["window"],
               tally["by_completeness"]["P"], tally["by_completeness"]["F"],
               tally["by_completeness"]["N"], extra))


def _ms_since(ctx, started_mono):
    return int(max(0, ctx.clock.monotonic() - started_mono) * 1000)


def _record_author_failure(ctx, state, key, outcome, run_id, started_mono, requested,
                           http_status=None):
    """單一作者失敗：記代碼、不寫該作者的任何文章、不覆蓋既有資料，繼續下一位（FR-005）。

    告警（FR-032）在 US4／T036 接上；這裡只累計狀態與輸出代碼。
    """
    at = ctx.clock.now().isoformat(timespec="seconds")
    ctx.store.record_feed_request(key, at, outcome, http_status=http_status, requested=requested,
                                  count_failure=True)
    ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=1 if requested else 0,
                           http_status=http_status, outcome=outcome,
                           duration_ms=_ms_since(ctx, started_mono))
    state.authors_failed += 1
    row = ctx.store.get_author(key) or {}
    ctx.say("  %s: %s%s（連續 %s 次）"
            % (key, outcome, "" if http_status is None else " http=%s" % http_status,
               row.get("consecutive_failures")))


def _store_items(ctx, state, entry, items, source):
    """逐篇：去重 → pubDate → 14 天窗 → 分類 → 單篇一交易寫入（文章＋圖片列）。"""
    key = entry["key"]
    author = ctx.store.get_author(key) or {}
    window_from = author.get("window_from")
    tally = {"items": len(items), "stored": 0, "duplicate": 0, "conflict": 0, "window": 0,
             "no_pubdate": 0, "invalid": 0, "by_completeness": {"P": 0, "F": 0, "N": 0}}
    for item in items:
        if ctx.remaining() <= 0:
            state.budget_exhausted = True
            break
        link = item.get("link")
        if not link:
            tally["invalid"] += 1
            continue
        link_norm = substack_feed.normalize_link(link)
        hit = ctx.store.find_duplicate(item.get("guid"), link_norm)
        if hit:
            if hit["kind"] == "dedupe_conflict":
                tally["conflict"] += 1
            else:
                tally["duplicate"] += 1
            continue
        published = item.get("published_at")
        if published is None:
            tally["no_pubdate"] += 1            # 不猜日期：沒有發布日就套不了 14 天窗
            continue
        published = (published.astimezone(TZ8) if published.tzinfo
                     else published.replace(tzinfo=TZ8))
        if window_from and published.date().isoformat() < window_from:
            tally["window"] += 1
            continue
        info = substack_html.analyze(item.get("content_html"), link)
        row = {"author_key": key, "guid": item.get("guid") or None, "link": link,
               "link_norm": link_norm, "title": item.get("title") or NO_TITLE,
               "published_at": published.isoformat(timespec="seconds"),
               "fetched_at": ctx.clock.now().isoformat(timespec="seconds"), "source": source,
               "completeness": info["completeness"], "classify_reason": info["reason"],
               "content_html": item.get("content_html"), "body_text": info["body_text"],
               "description": item.get("description"),
               "enclosure_type": item.get("enclosure_type")}
        article_id = ctx.store.insert_article_with_images(row, _image_rows(info["images"], item))
        if article_id is None:                  # 競態：同一篇已存在，不覆寫（FR-007）
            tally["duplicate"] += 1
            continue
        tally["stored"] += 1
        tally["by_completeness"][info["completeness"]] += 1
        state.new_articles.append(article_id)
        state.completeness[info["completeness"]] += 1
    return tally


def _image_rows(images, item):
    """圖位清單 → 圖片列（status 由 store 預設為 pending）；seq=0 留給封面圖。"""
    rows = [{"seq": img["seq"], "src_url": img["src"], "alt": img.get("alt"),
             "caption": img.get("caption")} for img in (images or ()) if img.get("src")]
    enclosure_type = (item.get("enclosure_type") or "").lower()
    enclosure_url = item.get("enclosure_url")
    if (enclosure_url and enclosure_type.startswith("image/")
            and all(r["src_url"] != enclosure_url for r in rows)):
        rows.insert(0, {"seq": 0, "src_url": enclosure_url, "alt": None, "caption": None})
    return rows


# ---------------------------------------------------------------- 通知（FR-025、FR-028、FR-035）
def _send(ctx, state, text):
    """送一則通知。只看錯誤清單是否為空與數量，**不記錄錯誤原文**（含 Bot token，research R4）。"""
    if state.notify_sent or state.notify_failed:
        ctx.sleep(NOTIFY_GAP_SEC)
    sender = ctx.notifier if ctx.notifier is not None else notify.send_telegram
    try:
        _sent, errors = sender(text)
    except Exception:                                       # noqa: BLE001
        errors = ["send_failed"]
    ok = not errors
    if ok:
        state.notify_sent += 1
    else:
        state.notify_failed += 1
    return ok


def _notify_rows(ctx, state, rows):
    for row in rows:
        if row["id"] in state.notify_attempted:
            continue                                        # 同次不重試（research R4）
        if ctx.remaining() <= 0:
            state.budget_exhausted = True
            break
        text = format_article_notice(_display_name(ctx, row["author_key"]), row["title"],
                                     row["completeness"])
        ok = _send(ctx, state, text)
        state.notify_articles += 1
        state.notify_attempted.add(row["id"])
        ctx.store.record_notify_result(row["id"], ok,
                                       at=ctx.clock.now().isoformat(timespec="seconds"))


def _notify_backlog(ctx, state):
    """步驟 3：先補發先前 pending／failed 的通知（FR-025）。"""
    _notify_rows(ctx, state, ctx.store.articles_awaiting_notify())


def _notify_new(ctx, state):
    """步驟 6：本次新存文章的逐篇通知（含追補存入者，PO 決定 B3）。"""
    _notify_rows(ctx, state, ctx.store.articles_awaiting_notify())


def _notify_summary(ctx, state, trigger):
    """本次有新文章、有告警或有漏文提示時發 1 則摘要（PO 決定 B4、FR-028）。"""
    if not (state.new_articles or state.alerts or state.missed_hints):
        return
    counts = {"new": len(state.new_articles), "F": state.completeness["F"],
              "P": state.completeness["P"], "N": state.completeness["N"],
              "images_downloaded": state.images_downloaded,
              "images_missing": state.images_missing,
              "images_abandoned": state.images_abandoned_total}
    text = format_summary(trigger, counts, substack_store.format_space_line(ctx.data_dir),
                          missed_hints=state.missed_hints,
                          unnotified=ctx.store.unnotified_count())
    _send(ctx, state, text)
    state.notify_summary += 1


def _print_run_counters(ctx, state):
    """stdout 只含代號、狀態、計數（FR-026）。"""
    if not state.new_articles:
        ctx.say("  無新文章")
    ctx.say("  images: downloaded=%d missing=%d abandoned_now=%d budget_exhausted=%d"
            % (state.images_downloaded, state.images_missing, state.images_abandoned_now,
               1 if state.budget_exhausted else 0))
    ctx.say("  notify: sent=%d failed=%d (articles=%d summary=%d)"
            % (state.notify_sent, state.notify_failed, state.notify_articles,
               state.notify_summary))


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

    if action == "run" and args.dry_run:
        # 完整流程的 --dry-run 在 T045 才接上。拒絕要發生在取鎖與開庫**之前**，
        # 免得「還沒實作的動作」順手建出一個空的資料庫（唯讀承諾不能先被破壞）。
        err.write("尚未實作的動作：dry-run（代碼 %s）\n" % NOT_IMPLEMENTED)
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
