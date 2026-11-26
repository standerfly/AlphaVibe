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

所有動作皆已實作（US5 起含 `--backfill`／`--dry-run`／`--status`）；`dispatch` 遇到未知動作
仍回 exit 2 並印代碼 `not_implemented`（不假裝成功）。

僅標準庫、Python 3.9 相容。
"""
import argparse
import datetime
import fcntl
import math
import os
import re
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
import substack_images  # noqa: E402
import substack_reclassify  # noqa: E402
import substack_store  # noqa: E402

LOCK_NAME = ".substack_import.lock"
RUN_BUDGET_SEC = 1200           # 單次執行牆鐘預算 20 分鐘（research R2）
# 圖片階段的期限＝預算減這麼多秒（18 分鐘到就中止，留 2 分鐘給通知與摘要，research R2）
IMAGE_DEADLINE_MARGIN_SEC = 120
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
SOURCE_BACKFILL = "backfill"
NO_TITLE = "（無標題）"

COMPLETENESS_LABEL = {"F": "全文", "P": "僅預覽", "N": "非文字"}
# N 類的固定提醒句：逐字同 contracts/notifications.md §1（FR-035，PO 決定 Q14）
NON_TEXT_REMINDER = "⚠️ 此文為非文字、內文未保存，請決定是否要處理。"

URL_PATTERN = re.compile(r"https?://\S+")  # 通知絕不含文章連結（FR-027／SC-005）：標題若含網址一律遮蔽
TRIGGER_LABEL = {"schedule": "排程", "catchup": "補跑", "manual": "手動", "backfill": "追補"}

# 告警固定文字（contracts/notifications.md §3；比照 investanchors_import 的 ALERT_TEXTS 慣例）。
# 佔位只填「設定檔裡的出版名稱／固定原因詞／連續次數／空間數字」，**不嵌入例外原文、回應內容、
# 標題或網址**（FR-026、FR-032）；每則末尾另附 format_space_line()（FR-028）。
ALERT_TEXTS = {
    "blocked": "⚠️ Substack 匯入：{name} 被站方擋下（{reason}），本次已停止該作者、不重試，下次排程再試。",
    "fetch_failed": "⚠️ Substack 匯入：{name} 抓取失敗（{reason}，連續 {count} 次），下次排程再試。",
    "disk": "⚠️ Substack 匯入：寫入失敗（可能是硬碟空間不足），本次已中止，已存文章不受影響。{free}",
    "config_invalid": ("⚠️ Substack 匯入：設定檔無法使用（{reason}），本次未發出任何請求。"
                       "請在對話中請 Claude 檢查設定。"),
}
# 被擋三種：不論告警策略一律立即告警（FR-032）
BLOCKED_REASON = {"blocked_403": "403", "rate_limited_429": "429", "challenge_html": "非 feed 回應"}
# 其他失敗的固定原因詞。契約只列「逾時｜網路錯誤｜無法解析｜HTTP {碼}｜robots 不允許」五種；
# 契約未列的代碼歸到語意最接近的一個（不新增詞、不嵌原文）：
#   robots_unavailable → robots 不允許（取不到 robots、也沒有 7 天內快取＝未獲允許，保守略過）
#   too_large          → 無法解析（超過 5MB 上限，本系統拒絕解析）
#   redirect_refused／error（未分類例外）→ 網路錯誤
FAILURE_REASON = {"timeout": "逾時", "network": "網路錯誤", "parse_error": "無法解析",
                  "robots_disallow": "robots 不允許", "robots_unavailable": "robots 不允許",
                  "too_large": "無法解析", "redirect_refused": "網路錯誤", "error": "網路錯誤"}
POLICY_EVERY = "every_failure"
POLICY_CONSECUTIVE = "consecutive_3"
CONSECUTIVE_THRESHOLD = 3

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
    if ctx.action == "retry_images":
        return _do_retry_images(ctx)
    if ctx.action == "reclassify":
        return _do_reclassify(ctx)
    if ctx.action == "reclassify_history":
        return _do_reclassify_history(ctx)
    if ctx.action == "backfill":
        return _do_backfill(ctx)
    if ctx.action == "status":
        return _do_status(ctx)
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
    """逐篇通知：作者＋標題＋完整度，**沒有連結**；N 類多一行固定提醒（FR-035）。

    標題是外部 feed 提供的原文，不可信任：若其中夾帶真實 URL（例如作者自己貼的連結），
    一律遮蔽，確保通知文字絕不含文章連結（FR-027／SC-005）。
    """
    safe_title = re.sub(r"\s{2,}", " ", URL_PATTERN.sub("", title)).strip()
    lines = ["📰 Substack 新文章｜%s" % display_name,
             safe_title,
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


# ---------------------------------------------------------------- 告警（FR-005、FR-028、FR-032）
def should_alert(outcome, policy, consecutive):
    """這次失敗要不要告警。

    * 403／429／挑戰頁：永遠 True（不論策略）。
    * `every_failure`：每次 True。
    * `consecutive_3`：只在「連續第 3 次」那一次 True（tasks T035「只在連續第 3 次發」）；
      第 4 次以後不再重複發，直到 200／304 歸零後重新計數。
    * 不認得的策略值（設定檔驗證不該放行）一律當 `every_failure`——寧可多發也不漏發。
    """
    if outcome in BLOCKED_REASON:
        return True
    if policy == POLICY_CONSECUTIVE:
        return int(consecutive or 0) == CONSECUTIVE_THRESHOLD
    return True


def failure_reason(outcome):
    """失敗代碼 → 契約的固定原因詞（`http_<碼>` → `HTTP <碼>`）；只輸出固定字串。"""
    if outcome in FAILURE_REASON:
        return FAILURE_REASON[outcome]
    if str(outcome).startswith("http_") and str(outcome)[5:].isdigit():
        return "HTTP %s" % str(outcome)[5:]
    return FAILURE_REASON["error"]


def _with_space(text, data_dir):
    return text + "\n" + substack_store.format_space_line(data_dir)


def format_author_alert(display_name, outcome, consecutive, data_dir):
    if outcome in BLOCKED_REASON:
        text = ALERT_TEXTS["blocked"].format(name=display_name, reason=BLOCKED_REASON[outcome])
    else:
        text = ALERT_TEXTS["fetch_failed"].format(name=display_name,
                                                  reason=failure_reason(outcome),
                                                  count=int(consecutive or 0))
    return _with_space(text, data_dir)


def format_disk_alert(data_dir):
    try:
        free = "剩餘空間 %.1f GB。" % substack_store.space_status(data_dir)["free_gb"]
    except Exception:                                   # noqa: BLE001
        free = "剩餘空間無法取得。"
    return _with_space(ALERT_TEXTS["disk"].format(free=free), data_dir)


def format_config_alert(missing, data_dir):
    text = ALERT_TEXTS["config_invalid"].format(reason="不存在" if missing else "格式錯誤")
    return _with_space(text, data_dir)


# ---------------------------------------------------------------- US1：完整流程（FR-001～FR-009）
class _RunState(object):
    """一次執行的計數器。

    圖片三個計數的語意（data-model §1.5、contracts/notifications.md §2）：
    * `images_downloaded`：本次成功下載的張數（摘要的「本次下載 d 張」）
    * `images_missing`：本次結束時仍待補的張數（`pending`＋`missing`，摘要的「缺圖待補 m 張」）
    * `images_abandoned_now`：本次新標為放棄的張數（寫進 `run`）；
      摘要的「放棄累計 a 張」用 `images_abandoned_total`（庫內 `abandoned` 總數）
    """

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
        self.budget_exhausted = False        # 整體 20 分鐘預算用完（會讓 result=aborted_budget）
        self.images_deadline_reached = False  # 只有圖片階段的 18 分鐘期限到（result 仍是 ok）
        self.missed_hints = []
        self.alerts = 0                     # 本次發出的告警則數（有告警就要發摘要，FR-025）

    def budget_flag(self):
        """`run.budget_exhausted`：整體預算用完**或**圖片階段期限到（data-model §1.5）。"""
        return 1 if (self.budget_exhausted or self.images_deadline_reached) else 0

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
                "budget_exhausted": self.budget_flag()}


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
        if not state.budget_exhausted:
            _download_images(ctx, state)                    # 步驟 5
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
        # 磁碟滿：立即中止（該篇已在自己的交易內回滾，先前提交的文章不受影響，US4-AS4）。
        # 記 run 本身也可能因空間不足失敗，失敗就算了——不能讓它蓋掉「中止」這件事。
        try:
            ctx.store.finish_run(run_id, result="aborted_disk", **state.counters())
        except substack_store.DiskFullError:
            pass
        _send_alert(ctx, state, format_disk_alert(ctx.data_dir))
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
        line = "  %s: skipped_interval wait=%d min" % (key, wait)
        if not ctx.args.scheduled:              # 手動執行：直接告訴 PO 還要等多久（FR-004）
            line += "（最小間隔 %d 分鐘，還需等待 %d 分鐘）" % (
                int(ctx.cfg["min_poll_interval_minutes"]), wait)
        ctx.say(line)
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

    連續失敗次數由 store 更新後重讀（同一份數字給 stdout 與告警）；是否告警依 `should_alert`
    （被擋三種一律立即，其餘看設定檔的 `alert_policy`，每次執行重讀設定，切換在下一次失敗生效）。
    """
    at = ctx.clock.now().isoformat(timespec="seconds")
    ctx.store.record_feed_request(key, at, outcome, http_status=http_status, requested=requested,
                                  count_failure=True)
    ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=1 if requested else 0,
                           http_status=http_status, outcome=outcome,
                           duration_ms=_ms_since(ctx, started_mono))
    state.authors_failed += 1
    row = ctx.store.get_author(key) or {}
    consecutive = int(row.get("consecutive_failures") or 0)
    ctx.say("  %s: %s%s（連續 %d 次）"
            % (key, outcome, "" if http_status is None else " http=%s" % http_status,
               consecutive))
    policy = (ctx.cfg or {}).get("alert_policy", POLICY_EVERY)
    if ctx.remaining() <= 0:
        # 整體 20 分鐘預算已用完＝「停止一切作業」（research R2 (2)）：失敗照記、不發告警；
        # 主流程接著以 aborted_budget 收尾並在 stderr 說明。
        return
    if should_alert(outcome, policy, consecutive):
        _send_alert(ctx, state, format_author_alert(_display_name(ctx, key), outcome,
                                                    consecutive, ctx.data_dir))


def _store_items(ctx, state, entry, items, source, ignore_window=False):
    """逐篇：去重 → pubDate → 14 天窗 → 分類 → 單篇一交易寫入（文章＋圖片列）。

    `ignore_window=True` 只給追補用（research R5）：不套 14 天窗，其餘（去重、沒有發布日就略過、
    單篇一交易、不覆寫）完全相同。
    """
    key = entry["key"]
    author = ctx.store.get_author(key) or {}
    window_from = None if ignore_window else author.get("window_from")
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


# ---------------------------------------------------------------- US5：追補（FR-008、research R5）
BACKFILL_HINT = "早於 %s 的文章 feed 已不提供，無法取得（不會改抓其他來源）。"


def backfill_target(cfg, key):
    """回傳 (設定檔裡的作者, 拒絕原因)。不存在或已停用 → 拒絕（已決定事項 #5）。"""
    for entry in (cfg or {}).get("authors", ()):
        if entry.get("key") == key:
            if not entry.get("enabled"):
                return None, "作者 %s 已停用，不追補（要追補請先 enable）" % key
            return entry, None
    return None, "設定檔沒有作者 %s，不追補" % key


def _oldest_in_feed(items):
    """feed 條目中最舊一篇的台北日期；沒有任何可解析的發布日 → None。"""
    dates = []
    for item in items or ():
        published = item.get("published_at")
        if published is None:
            continue
        published = (published.astimezone(TZ8) if published.tzinfo
                     else published.replace(tzinfo=TZ8))
        dates.append(published.date().isoformat())
    return min(dates) if dates else None


def _do_backfill(ctx):
    """`--backfill KEY`：守最小間隔與鎖、不帶 ETag、忽略 14 天窗、去重後存入、逐篇通知。

    作者存在且啟用已在取鎖、開庫之前檢查過（run()）；這裡再查一次是防禦性的。
    不下載圖片：追補只打該作者的 robots 與 feed（tasks T042 (5)），新存文章的圖片列維持
    `pending`，由下一次一般執行的圖片階段補下載。
    """
    key = ctx.args.backfill
    entry, refusal = backfill_target(ctx.cfg, key)
    if refusal:
        ctx.warn("拒絕執行：%s" % refusal)
        return EXIT_REFUSED
    wait = _interval_wait_minutes(ctx, ctx.store.get_author(key))
    if wait > 0:
        # 間隔內拒絕：零網路、不寫執行紀錄、不通知（FR-008「追補仍遵守最小輪詢間隔」）
        ctx.warn("拒絕執行：%s 距上次請求未滿最小間隔 %d 分鐘，還需等待 %d 分鐘"
                 % (key, int(ctx.cfg["min_poll_interval_minutes"]), wait))
        return EXIT_REFUSED

    now = ctx.clock.now()
    run_id = ctx.store.start_run("backfill", started_at=now.isoformat(timespec="seconds"))
    ctx.say("[%s] substack run#%d trigger=backfill author=%s"
            % (now.strftime("%Y-%m-%d %H:%M:%S"), run_id, key))
    state = _RunState()
    _sync_one_author(ctx, entry, now)
    started_mono = ctx.clock.monotonic()
    result, code = "ok", EXIT_OK
    try:
        gate = substack_feed.RobotsGate(ctx.store, _fetcher(ctx), ctx.clock)
        allowed, robots_outcome = gate.allowed(entry["feed_url"], remaining=ctx.remaining())
        if not allowed:
            _record_author_failure(ctx, state, key, robots_outcome, run_id, started_mono,
                                   requested=False)
        else:
            fetched = substack_feed.fetch_feed(_fetcher(ctx), entry["feed_url"], etag=None,
                                               remaining=ctx.remaining())
            outcome, status = fetched["outcome"], fetched["status"]
            if outcome != "ok_200":             # 不帶 ETag 不該有 304；一律當失敗處理
                _record_author_failure(ctx, state, key, outcome, run_id, started_mono,
                                       requested=True, http_status=status)
            else:
                _store_backfill(ctx, state, entry, fetched, run_id, started_mono)
        if state.budget_exhausted or ctx.remaining() <= 0:
            state.budget_exhausted = True
            result, code = "aborted_budget", EXIT_AUTHOR_FAILED
            ctx.warn("中止：牆鐘預算 %d 秒用完，未發出的通知維持 pending，下次執行補發"
                     % RUN_BUDGET_SEC)
        else:
            counts = ctx.store.image_status_counts()
            state.images_missing = counts["pending"] + counts["missing"]
            state.images_abandoned_total = counts["abandoned"]
            _notify_new(ctx, state)             # 追補文章逐篇通知（PO 決定 B3）＋先前未成功者
            _notify_summary(ctx, state, "backfill")
        if result == "ok" and state.authors_failed:
            result, code = "partial", EXIT_AUTHOR_FAILED
    except substack_store.DiskFullError:
        try:
            ctx.store.finish_run(run_id, result="aborted_disk", **state.counters())
        except substack_store.DiskFullError:
            pass
        _send_alert(ctx, state, format_disk_alert(ctx.data_dir))
        raise
    ctx.say("  notify: sent=%d failed=%d (articles=%d summary=%d)"
            % (state.notify_sent, state.notify_failed, state.notify_articles,
               state.notify_summary))
    ctx.store.finish_run(run_id, result=result, **state.counters())
    end = ctx.clock.now()
    ctx.say("[%s] done result=%s duration=%ds"
            % (end.strftime("%Y-%m-%d %H:%M:%S"), result, int((end - now).total_seconds())))
    return code


def _sync_one_author(ctx, entry, now):
    """追補只同步目標作者：首次或重新啟用一樣記下啟用基準（research R5），不動其他作者。"""
    key = entry["key"]
    before = ctx.store.get_author(key)
    ctx.store.upsert_author(key, entry["name"], entry["feed_url"])
    if (before is None or not before.get("activated_at")
            or not before.get("last_seen_enabled")):
        ctx.store.activate_author(key, now.isoformat(timespec="seconds"), window_from_text(now))
    else:
        ctx.store.note_author_enabled(key, True)


def _store_backfill(ctx, state, entry, fetched, run_id, started_mono):
    key = entry["key"]
    at = ctx.clock.now().isoformat(timespec="seconds")
    ctx.store.record_feed_request(key, at, fetched["outcome"], http_status=fetched["status"],
                                  etag=fetched["etag"], success=True)
    state.authors_polled += 1
    items = fetched["items"] or []
    tally = _store_items(ctx, state, entry, items, SOURCE_BACKFILL, ignore_window=True)
    ctx.store.add_poll_log(run_id=run_id, author_key=key, at=at, requested=1,
                           http_status=fetched["status"], outcome=fetched["outcome"],
                           items_in_feed=tally["items"], new_items=tally["stored"],
                           skipped_window=0, skipped_no_pubdate=tally["no_pubdate"],
                           duration_ms=_ms_since(ctx, started_mono))
    oldest = _oldest_in_feed(items)
    extra = ""
    for label, value in (("no_pubdate", tally["no_pubdate"]), ("invalid", tally["invalid"])):
        if value:
            extra += " %s=%d" % (label, value)
    ctx.say("backfill %s: feed_items=%d already=%d stored=%d oldest_in_feed=%s%s"
            % (key, tally["items"], tally["duplicate"] + tally["conflict"], tally["stored"],
               oldest or "-", extra))
    if oldest:
        ctx.say("  提示：" + BACKFILL_HINT % oldest)
    else:
        ctx.say("  提示：feed 目前沒有可判斷發布日的文章，無法追補更早的文章（不會改抓其他來源）。")
    ctx.say("  (P=%d F=%d N=%d) 圖片列維持待下載，下一次一般執行補下載"
            % (tally["by_completeness"]["P"], tally["by_completeness"]["F"],
               tally["by_completeness"]["N"]))


# ---------------------------------------------------------------- 步驟 5：圖片（FR-014～FR-016）
def _image_deadline(ctx):
    """圖片階段的剩餘秒數：整體剩餘預算再扣 120 秒（留給通知與摘要，research R2）。"""
    return ctx.remaining() - IMAGE_DEADLINE_MARGIN_SEC


def _image_fetcher(ctx, allowed_hosts):
    return ctx.http if ctx.http is not None else substack_images.fetcher_for(allowed_hosts)


def _images_to_fetch(ctx, state):
    """先本次新文章的圖，再補下載其餘 `pending`／`missing`（contracts/cli.md 步驟 5）。"""
    rows, seen = [], set()
    for article_id in state.new_articles:
        for row in ctx.store.list_images(article_id):
            if (row["status"] in substack_images.DOWNLOADABLE_STATUSES
                    and row["fail_count"] < substack_store.MAX_IMAGE_FAILS):
                rows.append(row)
                seen.add(row["id"])
    for row in ctx.store.images_awaiting_download():
        if row["id"] not in seen:
            rows.append(row)
    return rows


def _apply_image_stats(ctx, state, stats):
    """把批次結果併進計數器；缺圖待補與放棄累計一律重新由庫內狀態算，避免兩邊不一致。"""
    state.images_downloaded += stats.get("downloaded", 0)
    state.images_abandoned_now += stats.get("abandoned", 0)
    if stats.get("deadline_reached"):
        state.images_deadline_reached = True
    counts = ctx.store.image_status_counts()
    state.images_missing = counts["pending"] + counts["missing"]
    state.images_abandoned_total = counts["abandoned"]


def _download_images(ctx, state):
    """圖片下載階段：失敗**不**改變 `run.result` 與退出碼（spec US3-AS2、已決定事項 #1）。"""
    rows = _images_to_fetch(ctx, state)
    stats = substack_images._empty_stats()
    if _image_deadline(ctx) <= 0:
        stats["deadline_reached"] = True             # 期限已過：零請求、狀態不變
    elif rows:
        allowed = substack_config.allowed_image_hosts(ctx.cfg)
        stats = substack_images.download_batch(
            ctx.store, rows, fetch=_image_fetcher(ctx, allowed), allowed_hosts=allowed,
            deadline=lambda: _image_deadline(ctx), sleep=ctx.sleep)
    _apply_image_stats(ctx, state, stats)
    if stats["deadline_reached"]:
        ctx.warn("圖片階段中止：距牆鐘預算不足 %d 秒，未下載的圖維持原狀態，下次執行補下載"
                 % IMAGE_DEADLINE_MARGIN_SEC)
    return stats


def _do_retry_images(ctx):
    """`--retry-images`：重設指定圖片的失敗次數後立即試一次（只打圖片主機，不碰 feed）。"""
    ids, bad = _parse_ids(ctx.args.retry_images)
    if bad:
        ctx.warn("--retry-images 只接受整數，無法解析：%s" % "、".join(bad))
        return EXIT_REFUSED
    if not ids:
        ctx.warn("--retry-images 需要至少一個 image_id")
        return EXIT_REFUSED
    run_id = ctx.store.start_run("retry_images")
    state = _RunState()
    allowed = substack_config.allowed_image_hosts(ctx.cfg)
    report = substack_images.retry(ctx.store, ids, fetch=_image_fetcher(ctx, allowed),
                                   allowed_hosts=allowed,
                                   deadline=lambda: _image_deadline(ctx), sleep=ctx.sleep)
    _apply_image_stats(ctx, state, report["stats"])
    ctx.say("retry-images: 接受 %d 張、拒絕 %d 張"
            % (len(report["accepted"]), len(report["rejected"])))
    for image_id, reason in report["rejected"]:
        ctx.warn("  image_id=%s 拒絕：%s" % (image_id, reason))
    _print_image_counters(ctx, state)
    code = EXIT_AUTHOR_FAILED if report["rejected"] else EXIT_OK
    # 被拒絕的 id 比照 --reclassify 的慣例：明列、exit 1，run 記 partial（不靜默略過）
    ctx.store.finish_run(run_id, result="ok" if code == EXIT_OK else "partial",
                         **state.counters())
    return code


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


def _send_alert(ctx, state, text):
    """告警：與逐篇通知共用節流與錯誤處理（不記錯誤原文）；只計數，失敗不重試。"""
    ok = _send(ctx, state, text)
    state.alerts += 1
    ctx.say("  alert: %s" % ("sent" if ok else "failed"))
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


def _print_image_counters(ctx, state):
    ctx.say("  images: downloaded=%d missing=%d abandoned_now=%d budget_exhausted=%d"
            % (state.images_downloaded, state.images_missing, state.images_abandoned_now,
               state.budget_flag()))


def _print_run_counters(ctx, state):
    """stdout 只含代號、狀態、計數（FR-026）。"""
    if not state.new_articles:
        ctx.say("  無新文章")
    _print_image_counters(ctx, state)
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


# ---------------------------------------------------------------- US5：--dry-run 與 --status（唯讀）
def _do_dry_run(ctx):
    """零網路、不寫庫、不取鎖、不發通知：列出完整流程「會做什麼」（cli.md §1）。

    `ctx.store` 可能是 None（庫還不存在；唯讀承諾＝不建庫），此時每位啟用作者都視為首次。
    不呼叫 `_sync_authors`，所以 `last_seen_enabled`／`activated_at` 一律不動（research R5）。
    """
    now = ctx.clock.now()
    store = ctx.store
    ctx.say("[%s] substack dry-run：設定檔 OK（%d 位作者，最小間隔 %d 分鐘，告警策略 %s）；"
            "不發請求、不寫庫" % (now.strftime("%Y-%m-%d %H:%M:%S"), len(ctx.cfg["authors"]),
                              int(ctx.cfg["min_poll_interval_minutes"]),
                              ctx.cfg["alert_policy"]))
    if store is None:
        ctx.say("  （%s 尚未建立；真正執行時才會建立）" % substack_store.DB_FILENAME)
    if ctx.args.scheduled:
        day = schedule_day(now)
        trigger = "schedule" if now.hour == SCHEDULE_HOUR else "catchup"
        if in_defer_window(now):
            ctx.say("  排程判斷：排程日 %s，啟動於 23:00～00:59 → deferred（延後至 01:00 補跑，"
                    "不會輪詢任何作者）" % day)
            return EXIT_OK
        if store is not None and store.has_actual_scheduled_run(day):
            ctx.say("  排程判斷：排程日 %s 已執行過 → already_done（不會輪詢任何作者）" % day)
            return EXIT_OK
        ctx.say("  排程判斷：排程日 %s → 會執行（trigger=%s）" % (day, trigger))
    for entry in ctx.cfg["authors"]:
        key = entry["key"]
        if not entry.get("enabled"):
            ctx.say("  %s: 停用（不請求；已存文章保留）" % key)
            continue
        author = store.get_author(key) if store is not None else None
        wait = _interval_wait_minutes(ctx, author)
        if wait > 0:
            ctx.say("  %s: 會因間隔跳過（還需等待 %d 分鐘）" % (key, wait))
            continue
        fresh = (author is None or not author.get("activated_at")
                 or not author.get("last_seen_enabled"))
        if fresh:
            ctx.say("  %s: 會請求（首次或重新啟用：只收 %s 起發布的文章）"
                    % (key, window_from_text(now)))
        else:
            ctx.say("  %s: 會請求" % key)
    missing = len(store.images_awaiting_download()) if store is not None else 0
    ctx.say("  缺圖待補 %d 張（真正執行時於圖片階段補下載）" % missing)
    return EXIT_OK


def _do_status(ctx):
    """唯讀摘要（cli.md §1）：作者狀態、有效完整度、圖片四種狀態、未通知、最近 5 次執行。

    不取鎖、不需要設定檔（讀得到就順便列出啟用狀態與設定值）；輸出不含標題、內文、網址。
    """
    store = ctx.store
    cfg, cfg_note = None, None
    try:
        cfg = substack_config.load_config(ctx.data_dir)
    except substack_config.ConfigMissing:
        cfg_note = "設定檔無法讀取（不存在）"
    except substack_config.ConfigInvalid:
        cfg_note = "設定檔無法讀取（不合格；可用 substack_config.py validate 查原因）"
    now = ctx.clock.now()
    ctx.say("[%s] substack status" % now.strftime("%Y-%m-%d %H:%M:%S"))
    if cfg is not None:
        ctx.say("設定：最小間隔 %d 分鐘；告警策略 %s；作者 %d 位"
                % (int(cfg["min_poll_interval_minutes"]), cfg["alert_policy"],
                   len(cfg["authors"])))
    else:
        ctx.say("設定：%s" % cfg_note)
    configured = {}
    order = []
    for entry in (cfg or {}).get("authors", ()):
        configured[entry["key"]] = bool(entry.get("enabled"))
        order.append(entry["key"])
    rows = {row["author_key"]: row for row in store.author_status_rows()}
    for key in sorted(rows):
        if key not in configured:
            order.append(key)
    ctx.say("作者：")
    for key in order:
        if cfg is None:
            setting = "未知"
        elif key in configured:
            setting = "啟用" if configured[key] else "停用"
        else:
            setting = "不在設定檔"
        row = rows.get(key)
        if row is None:
            ctx.say("  %s 設定=%s 文章=0 尚未執行過" % (key, setting))
            continue
        ctx.say("  %s 設定=%s 文章=%d 上次結果=%s 上次請求=%s 上次成功=%s 連續失敗=%d"
                % (key, setting, int(row["articles"] or 0), row["last_outcome"] or "-",
                   row["last_request_at"] or "-", row["last_success_at"] or "-",
                   int(row["consecutive_failures"] or 0)))
    comp = store.completeness_counts(effective=True)
    total = comp["P"] + comp["F"] + comp["N"]
    ctx.say("文章（有效完整度）：共 %d 篇｜全文 F=%d／僅預覽 P=%d／非文字 N=%d；被重判過 %d 篇"
            % (total, comp["F"], comp["P"], comp["N"], comp["reclassified"]))
    images = store.image_status_counts()
    ctx.say("圖片：已下載 %d／待下載 %d／缺圖 %d／放棄 %d"
            % (images["downloaded"], images["pending"], images["missing"],
               images["abandoned"]))
    ctx.say("通知：未通知 %d 篇" % store.unnotified_count())
    ctx.say("最近 5 次執行：")
    runs = store.recent_runs(5)
    if not runs:
        ctx.say("  （尚無）")
    for run in runs:
        ctx.say("  run#%d %s trigger=%s day=%s result=%s new=%d polled=%d skipped=%d failed=%d "
                "images=%d/%d notify=%d/%d"
                % (run["id"], run["started_at"] or "-", run["trigger"] or "-",
                   run["schedule_day"] or "-", run["result"] or "running",
                   run["new_articles"], run["authors_polled"], run["authors_skipped_interval"],
                   run["authors_failed"], run["images_downloaded"], run["images_missing"],
                   run["notify_sent"], run["notify_failed"]))
    return EXIT_OK


# ---------------------------------------------------------------- 進入點
def _config_alert(action, missing, data_dir, notifier, sleep, out, err):
    """設定檔不能用：完整流程（排程或手動）發 `config_invalid` 告警；零請求、不開庫、不取鎖。

    `--backfill`／`--retry-images` 是 PO 在對話中當場下的指令，錯誤已印在 stderr，不另發 Telegram。
    """
    if action != "run":
        return
    ctx = Context(None, action, data_dir, None, None, None, notifier, None, sleep, None,
                  out, err, 0)
    _send_alert(ctx, _RunState(), format_config_alert(missing, data_dir))


def _run_dry(args, data_dir, http, notifier, clock, sleep, env, out, err):
    """完整流程的 `--dry-run`（含 `--scheduled --dry-run`）：驗證設定檔、唯讀開庫（不存在就不開、
    不建）、不取鎖；設定檔不合格只印原因並 exit 2，**不發告警**（contracts/notifications.md §4）。"""
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
    store = None
    try:
        try:
            store = substack_store.SubstackStore.open_readonly(data_dir)
        except FileNotFoundError:
            store = None
        ctx = Context(args, "run", data_dir, cfg, store, http, notifier, clock, sleep, env,
                      out, err, clock.monotonic())
        return _do_dry_run(ctx)
    finally:
        if store is not None:
            store.close()


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
        return _run_dry(args, data_dir, http, notifier, clock, sleep, env, out, err)

    cfg = None
    if action in CONFIG_ACTIONS:
        try:
            cfg = substack_config.load_config(data_dir)
        except substack_config.ConfigMissing as exc:
            err.write("拒絕執行：%s\n" % exc)
            _config_alert(action, True, data_dir, notifier, sleep, out, err)
            return EXIT_REFUSED
        except substack_config.ConfigInvalid as exc:
            err.write("拒絕執行：設定檔不合格\n")
            for reason in exc.reasons:
                err.write("  %s\n" % reason)
            _config_alert(action, False, data_dir, notifier, sleep, out, err)
            return EXIT_REFUSED

    if action == "backfill":
        # 不存在或已停用 → 拒絕：在取鎖、開庫、任何請求之前（已決定事項 #5：零網路、不寫庫）
        _entry, refusal = backfill_target(cfg, args.backfill)
        if refusal:
            err.write("拒絕執行：%s\n" % refusal)
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
