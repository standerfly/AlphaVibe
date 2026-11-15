"""定錨產業筆記文章匯入——排程進入點（010 T016～T019、contracts/cli.md §1）。

流程（任何一步被拒絕都**不登入**）：
  (1) 低頻守衛：今日已嘗試登入、或被擋延後尚未到期 → 記一筆並結束；
  (2) 唯讀取信：只取 Message-ID 與寄達時間（信只當觸發）；
  (3) 決定觸發：有未處理的新信／週日核對（保底）／回補未完成；都沒有 → `trigger=none`，**不啟動 scraper**；
  (4) 啟動 scraper（登入 1 次、讀清單、抓**清單上所有未入庫的文章**，不論有無通知信，受每次 5 篇上限）；
  (5) 套用結果：去重、公告略過、置頂標記、不寫殘缺全文、單篇失敗同次不重試、達 3 次放棄；
  (6) 每次結束都要求伺服器端登出已驗證；未驗證立即通知；
  (7) Telegram：新文章（標題＋連結）與需介入的失敗（固定文字，不含任何例外細節）。

依賴注入（測試用）：fetch_mail、run_scraper、download_images、transcribe、notifier、get_secret、now、
sleeper、rng、delay_ms、image_hosts。僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import os
import sys
import tempfile
import shutil

import article_data_guard
import article_images
import article_store
import investanchors_limits
import investanchors_mailbox
import investanchors_redact
import keychain_secrets

HERE = os.path.dirname(os.path.abspath(__file__))
TZ8 = investanchors_limits.TZ8
CANON_URL = "https://investanchors.com/user/vip_contents/%d"
MAIL_DAYS = 14
MAIL_FAILURES_BEFORE_ALERT = 3
WEEKLY_MIN_GAP_DAYS = 6
WEEKLY_OVERDUE_DAYS = 8          # 週日那次因睡眠錯過時的保底：超過 8 天沒核對就補
HALT_SETTING = "halted_reason"
RECENT_ARTICLE_DAYS = 7           # 建立時間（由 ID 推得）在此天數內才逐篇通知，更早的合併成一則摘要

ALERT_TEXTS = {
    "login_failed": "⚠️ 定錨匯入：登入失敗（帳號或密碼可能錯誤）。請更新鑰匙圈 stnd-investanchors 後再執行。",
    "account_disabled": "⚠️ 定錨匯入：帳號可能被停用或超過裝置上限，已停止後續排程。請到網站確認後，用 --resume 恢復。",
    "blocked": "⚠️ 定錨匯入：偵測到被網站阻擋的跡象，已中止本次並延後至少一天。",
    "structure_changed": "⚠️ 定錨匯入：網站頁面結構可能改變（取不到完整內文），該篇已標記失敗。",
    "article_abandoned": "⚠️ 定錨匯入：有文章累計失敗已達上限，已停止自動重試。",
    "logout_unverified": ("⚠️ 定錨匯入：登出未驗證。探查的登入狀態可能仍留在網站伺服器端，PO 在自己的裝置登出無法清除；"
                          "請勿再次執行，先回報。"),
    "mailbox_failure": "⚠️ 定錨匯入：信箱讀取連續失敗（不影響每週核對）。",
    "id_time_anomaly": "⚠️ 定錨匯入：文章 ID 的時間規律出現多篇異常，半年截止判斷可能失效，請回報。",
}


class ImportError_(Exception):
    pass


def _default_now():
    return datetime.datetime.now(TZ8)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ8)


def weekly_due(now, last_weekly):
    """週日且上次核對 ≥6 天前；或超過 8 天沒核對（週日那次錯過時補上）。從未核對過只在週日觸發。"""
    now = _aware(now).astimezone(TZ8)
    if last_weekly is None:
        return now.weekday() == 6
    gap = now - _aware(last_weekly)
    if now.weekday() == 6 and gap >= datetime.timedelta(days=WEEKLY_MIN_GAP_DAYS):
        return True
    return gap >= datetime.timedelta(days=WEEKLY_OVERDUE_DAYS)


def backfill_active(store):
    """US4（T042）才會讓回補成為觸發；目前永遠為 False。"""
    return False


def _default_notifier(text):
    import notify
    return notify.send_telegram(text)


def build_parser():
    ap = argparse.ArgumentParser(description="定錨產業筆記文章匯入（排程進入點）")
    ap.add_argument("--data-dir", required=True,
                    help="必填、無預設值；指向正式資料目錄需 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1")
    ap.add_argument("--dry-run", action="store_true",
                    help="只取信並列出觸發判斷；不登入、不寫入、不通知")
    ap.add_argument("--force-weekly", action="store_true", help="視為每週核對日（手動試跑用）")
    ap.add_argument("--max-articles", type=int, default=None,
                    help="本次最多抓幾篇（只能降低，上限 %d）" % investanchors_limits.MAX_ARTICLES_PER_RUN)
    ap.add_argument("--reset-abandoned", type=int, default=None, metavar="ARTICLE_ID",
                    help="PO 介入後把已放棄的文章重置為可重試")
    ap.add_argument("--resume", action="store_true", help="帳號停用等狀況排除後，恢復排程")
    return ap


class Importer(object):
    def __init__(self, args, fetch_mail=None, run_scraper=None, download_images=None, transcribe=None,
                 notifier=None, get_secret=None, now=None, sleeper=None, rng=None, delay_ms=None,
                 image_hosts=None, base_url=None, timeout_ms=30000, out=None):
        self.args = args
        self.out = out or sys.stdout
        self.now = now or _default_now
        self.get_secret = get_secret or keychain_secrets.get_secret
        self.fetch_mail = fetch_mail or self._default_fetch_mail
        self.run_scraper = run_scraper or self._default_run_scraper
        self.download_images = download_images or article_images.download_images
        self.transcribe = transcribe
        self.notifier = notifier or _default_notifier
        self.sleeper = sleeper
        self.rng = rng
        self.delay_ms = list(delay_ms) if delay_ms else [
            investanchors_limits.DELAY_RANGE[0] * 1000, investanchors_limits.DELAY_RANGE[1] * 1000]
        self.image_hosts = image_hosts or article_images.DEFAULT_ALLOWED_HOSTS
        self.base_url = base_url or "https://investanchors.com"
        self.timeout_ms = timeout_ms
        self.secrets = []
        self.older_fetched = 0

    # ---------------------------------------------------------------- 預設依賴
    def _default_fetch_mail(self):
        addr = self.get_secret("gmail-address")
        pw = self.get_secret("gmail-app-password")
        self.secrets.extend([addr, pw])
        return investanchors_mailbox.fetch_mail_clues(addr, pw, days=MAIL_DAYS)

    def _default_run_scraper(self, payload):
        import article_probe
        return article_probe.default_scraper_runner(payload)

    def say(self, msg):
        self.out.write(msg + "\n")

    def alert(self, store, kind, key="-"):
        """固定文字、同日同類別去重；不含任何例外細節或內容。"""
        if store is not None and not store.alert_once(kind, key, day=self.now().astimezone(TZ8).date().isoformat()):
            return False
        try:
            self.notifier(ALERT_TEXTS[kind])
        except Exception:
            pass
        return True

    # ---------------------------------------------------------------- 主流程
    def main(self):
        args = self.args
        try:                                            # 在取信、登入、寫入之前就拒絕（dry-run 也一樣）
            args.data_dir = article_data_guard.resolve_data_dir(args.data_dir)
        except article_data_guard.DataDirRefused as e:
            self.say("拒絕執行：%s" % e)
            return 2
        if args.dry_run:
            return self._dry_run()
        store = article_store.ArticleStore(args.data_dir, now=self.now)
        try:
            if args.reset_abandoned is not None:
                ok = store.reset_abandoned(args.reset_abandoned)
                self.say("已重置文章 %s" % args.reset_abandoned if ok else "該文章不是 abandoned，未變更")
                return 0 if ok else 1
            if args.resume:
                store.set_setting(HALT_SETTING, "")
                self.say("已恢復排程")
                return 0
            return self._execute(store)
        finally:
            store.close()

    def _mail_step(self, store, record):
        """唯讀取信；record=False（dry-run）時不寫入。回傳 (clues, failed)。"""
        try:
            clues = self.fetch_mail()
        except Exception as e:                     # 信箱失敗：不因信觸發，連續失敗才通知
            if record:
                n = int(store.get_setting("mail_fail_count", "0")) + 1
                store.set_setting("mail_fail_count", n)
                if n >= MAIL_FAILURES_BEFORE_ALERT:
                    self.alert(store, "mailbox_failure", "mail")
            return [], True
        if record:
            store.set_setting("mail_fail_count", 0)
            for c in clues:
                store.add_mail_clue(c["message_id"], c.get("mail_date"), now=self.now())
        return clues, False

    def _triggers(self, store, unprocessed):
        t = []
        if unprocessed:
            t.append("mail")
        if self.args.force_weekly or weekly_due(self.now(), store.last_weekly_check()):
            t.append("weekly")
        if backfill_active(store):
            t.append("backfill")
        return t

    def _dry_run(self):
        """零副作用：不建立資料庫檔（沒有就用暫存目錄）、不寫入、不登入、不通知。"""
        db_exists = os.path.exists(os.path.join(os.path.abspath(self.args.data_dir), article_store.DB_FILENAME))
        tmp = None
        if db_exists:
            store = article_store.ArticleStore(self.args.data_dir, now=self.now)
        else:
            tmp = tempfile.mkdtemp(prefix="ia-dryrun-")
            store = article_store.ArticleStore(tmp, now=self.now)
        try:
            clues, failed = self._mail_step(store, record=False)
            seen = set(r["message_id"] for r in store.unprocessed_mail_clues())
            known = set(r[0] for r in store.conn.execute("SELECT message_id FROM mail_clue"))
            new_clues = [c for c in clues if c["message_id"] in seen or c["message_id"] not in known]
            triggers = self._triggers(store, new_clues)
            ok, reason = investanchors_limits.LimitGuard(store, self.now).may_login()
            self.say("dry-run：新信 %d 封；觸發 %s；登入守衛 %s%s" % (
                len(new_clues), ",".join(triggers) or "無", "放行" if ok else "拒絕", "" if ok else "（%s）" % reason))
            return 0
        finally:
            store.close()
            if tmp:
                shutil.rmtree(tmp, True)

    def _execute(self, store):
        guard = investanchors_limits.LimitGuard(store, self.now)
        if store.get_setting(HALT_SETTING):
            run = store.start_run("none")
            store.finish_run(run, None, 0, 0, "halted", None)
            self.say("已停止排程（%s）；排除後用 --resume 恢復" % store.get_setting(HALT_SETTING))
            return 2
        ok, reason = guard.may_login()
        if not ok:
            run = store.start_run("none")
            store.finish_run(run, None, 0, 0, "aborted_limit", None)
            self.say("拒絕登入：%s" % reason)
            return 2
        self._mail_step(store, record=True)
        unprocessed = store.unprocessed_mail_clues()
        triggers = self._triggers(store, unprocessed)
        if not triggers:
            run = store.start_run("none")
            store.finish_run(run, None, 0, 0, "ok", None)
            self.say("無觸發，未登入")
            return 0
        return self._run_site(store, guard, triggers, unprocessed)

    # ---------------------------------------------------------------- 登入、抓取、套用結果
    def _run_site(self, store, guard, triggers, unprocessed):
        cap = guard.cap_for_run(self.args.max_articles)
        run_id = store.start_run("+".join(triggers))
        pending = [r["article_id"] for r in store.list_pending(limit=cap)]
        try:
            email = self.get_secret("email", service=keychain_secrets.INVESTANCHORS_SERVICE)
            password = self.get_secret("password", service=keychain_secrets.INVESTANCHORS_SERVICE)
        except Exception:
            store.finish_run(run_id, None, 0, 0, "no_credentials", None)
            self.say("無法讀取登入憑證（請依 quickstart 存入鑰匙圈）")
            return 1
        self.secrets.extend([email, password])
        payload = {"mode": "import", "email": email, "password": password, "base_url": self.base_url,
                   "known_ids": sorted(store.known_ids()), "pending_ids": pending,
                   "max_list_pages": investanchors_limits.MAX_LIST_PAGES, "max_articles": cap,
                   "delay_ms": self.delay_ms, "timeout_ms": self.timeout_ms}
        store.mark_login_started(run_id)               # **啟動登入前**先扣當日額度
        try:
            objs = self.run_scraper(payload)
        except Exception as e:
            objs = []
            self.say("scraper 執行失敗：%s" % investanchors_redact.safe_error(e, self.secrets))
        return self._apply(store, guard, run_id, triggers, unprocessed, objs)

    def _apply(self, store, guard, run_id, triggers, unprocessed, objs):
        summary = None
        items, articles, errors = [], [], []
        for o in objs:
            t = o.get("type")
            if t == "summary":
                summary = o
            elif t == "list_item":
                items.append(o)
            elif t == "article":
                articles.append(o)
            elif t == "article_error":
                errors.append(o)
        failed_run = False
        result = "ok"
        blocked_until = None
        login_ok = None
        stage = (summary or {}).get("stage_error") or ""
        counters = (summary or {}).get("counters") or {}
        if summary is None:
            result, failed_run = "scraper_error", True
        elif stage.startswith("login_failed") or stage == "ambiguous_login_form":
            login_ok, result, failed_run = False, "login_failed", True
            reason = stage.split(":", 1)[1] if ":" in stage else stage
            if reason == "account_disabled":
                store.set_setting(HALT_SETTING, "account_disabled")
                self.alert(store, "account_disabled")
            else:
                self.alert(store, "login_failed")
        else:
            login_ok = bool(summary.get("logged_in"))
        via = triggers[0]
        if login_ok:
            self._apply_list(store, items, via)
            self.older_fetched = 0
            ok_n, fail_n = self._apply_articles(store, articles, errors)
            if self.older_fetched:                     # 較早的文章合併成一則，不列標題
                try:
                    self.notifier("📰 定錨補抓：已補抓 %d 篇較早的文章" % self.older_fetched)
                except Exception:
                    pass
            attempted, fetched = ok_n + fail_n, ok_n
            if summary.get("blocked"):
                result, failed_run = "blocked", True
                blocked_until = guard.block_until()
                self.alert(store, "blocked")
            elif fail_n:
                result, failed_run = "partial", True
            if counters.get("list_pages"):
                store.mark_mail_processed([c["message_id"] for c in unprocessed])
        else:
            attempted = fetched = 0
            if summary is not None and summary.get("blocked") and result == "ok":
                result, failed_run = "blocked", True
                blocked_until = guard.block_until()
                self.alert(store, "blocked")
        if stage and result == "ok":                    # 其他未預期的中止原因（例外、無瀏覽器…）
            result, failed_run = "scraper_error", True
        logged_out = bool(summary and summary.get("logout_verified"))
        if not logged_out and stage != "no_browser":    # 有嘗試登入就必須驗證登出；未驗證立即通知
            self.alert(store, "logout_unverified")
            failed_run = True
        store.finish_run(run_id, login_ok, attempted, fetched, result, logged_out, blocked_until=blocked_until,
                         list_pages=(counters.get("list_pages") or 0) if login_ok else 0)
        self.say("完成：結果 %s；抓取 %d／%d 篇；登出%s" % (result, fetched, attempted, "已驗證" if logged_out else "未驗證"))
        return 1 if failed_run else 0

    def _apply_list(self, store, items, via):
        for it in items:
            aid = int(it["article_id"])
            store.upsert_discovered(aid, CANON_URL % aid, it.get("title") or "(無標題)",
                                    list_date=it.get("date"), via=via, pinned=bool(it.get("pinned")),
                                    now=self.now())
            if it.get("is_announcement"):
                store.mark_skipped(aid)

    def _apply_articles(self, store, articles, errors):
        ok_n = fail_n = 0
        for a in articles:
            aid = int(a["article_id"])
            row = store.get_article_row(aid)
            if row is None or row["status"] not in article_store.PENDING_STATUSES:
                continue
            try:
                store.mark_fetched(aid, a.get("body") or "", a.get("published_at"), now=self.now())
            except article_store.BodyTooShort:
                self._fail(store, aid, "short")
                fail_n += 1
                continue
            for im in a.get("images") or []:
                store.add_image(aid, int(im["seq"]), im.get("src_url"))
            ok_n += 1
            self._notify_new(store, aid)
            self._images(store, aid)
        for e in errors:
            aid = int(e["article_id"])
            row = store.get_article_row(aid)
            if row is None or row["status"] not in article_store.PENDING_STATUSES:
                continue
            self._fail(store, aid, e.get("reason") or "unknown")
            fail_n += 1
        return ok_n, fail_n

    def _fail(self, store, aid, reason):
        status = store.mark_failed(aid, "article_error:%s" % reason, secrets=self.secrets)
        if reason in ("structure", "short"):
            self.alert(store, "structure_changed", "any")
        if status == "abandoned":
            self.alert(store, "article_abandoned", str(aid))

    def _notify_new(self, store, aid):
        row = store.get_article_row(aid)
        if not store.alert_once("new_article", str(aid), day="forever"):
            return
        if not self._is_recent(row):
            self.older_fetched += 1
            return
        try:
            self.notifier("📰 定錨新文章：%s\n%s" % (row["title"], CANON_URL % aid))
        except Exception:
            pass

    def _is_recent(self, row):
        """建立時間（由文章 ID 推得）距現在 7 天內；`id_time_ok=0`（推不出）視為近期。"""
        if not row.get("id_time_ok") or row.get("id_time_ms") is None:
            return True
        age = self.now().timestamp() * 1000 - row["id_time_ms"]
        return age <= RECENT_ARTICLE_DAYS * 86400 * 1000

    def _images(self, store, aid):
        kwargs = {"allowed_hosts": self.image_hosts, "rng": self.rng}
        if self.sleeper is not None:
            kwargs["sleeper"] = self.sleeper
        try:
            self.download_images(store, aid, store.data_dir, **{k: v for k, v in kwargs.items() if v is not None})
        except Exception:
            pass                                   # 圖片失敗不影響文章，下次補抓


def run(argv=None, **deps):
    args = build_parser().parse_args(argv)
    return Importer(args, **deps).main()


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
