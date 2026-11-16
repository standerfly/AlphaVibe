"""定錨文章庫逐篇核對工具（010 T045、SC-001、contracts/cli.md §3）——**唯讀**。

用途：回補完成後，讀網站「總覽」清單，與 `article` 表中「建立時間在半年內」的文章逐篇比對，
輸出缺漏／重複清單；早於截止日者只確認為 `deferred`（不開啟、不計缺漏）。

硬性界線：
  - **不寫入 `article`（及 `article_image`）表**，也不開啟任何文章頁：沿用 scraper 的 `import` 模式，
    固定送 `max_articles=0`、`pending_ids=[]`（因此 targets 為空，只讀清單），不新增 scraper 模式——
    登入／登出驗證、被擋偵測、置頂去重、整數門檻判定全部沿用既有且已測的路徑，改動最小。
  - 唯一寫入：(a) `import_runs` 一筆 trigger=`reconcile` 的執行紀錄（走與匯入同一個 LimitGuard，
    登入計入當日額度；這是額度記帳，不是文章資料）；(b) `<data-dir>/articles_probe/` 下的核對進度檔
    `reconcile-state.json`（游標與已見 ID，**不放 setting 表**，不碰 `backfill_state`）與報告檔
    `reconcile-<時間>.json`。進度檔與報告檔只有 ID 與狀態，**不含標題、內文、帳密、cookie**。
  - 受低頻約束：每日登入 ≤1 次（與匯入共用額度）、被擋延後、單次 ≤3 頁（第 1 頁＋游標起的頁，可分多次）、
    頁間隔由 scraper 控制（30～90 秒）。被拒就回報原因，不勉強。
  - 停止條件同回補（research R11）：連續 2 頁「非置頂、非公告」項目全部早於門檻才算掃完。
  - 「早於門檻」只用 Python 的 `article_id_time.is_before_cutoff`（唯一權威）；與 scraper 回報的 `defer`
    不一致 → 不推進進度、結果記 `cutoff_mismatch`。
  - 資料目錄一律經 `article_data_guard`（--data-dir 必填、正式庫需旗標）。

「重複」的定義（data-model 以 article_id 為主鍵，同 ID 不可能兩筆，所以改查實質重複）：
  非公告的列中，(a) 正規化網址（去 www、尾端斜線）相同、或 (b) 標題＋清單日期相同者，但 article_id 不同。
僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import json
import os
import sys

import article_data_guard
import article_id_time
import article_store
import investanchors_limits
import keychain_secrets

TZ8 = investanchors_limits.TZ8
PROBE_DIRNAME = "articles_probe"
STATE_FILENAME = "reconcile-state.json"
FIRST_CURSOR = 2                 # 第 1 頁每次都讀（置頂與新文章），游標從第 2 頁起（同回補）
STOP_PAGES = 2                   # 連續幾頁全舊才算掃完
HALT_SETTING = "halted_reason"
TRIGGER = "reconcile"


def build_parser():
    ap = argparse.ArgumentParser(description="定錨文章庫逐篇核對（唯讀；不寫 article 表、不開啟文章頁）")
    ap.add_argument("--data-dir", required=True,
                    help="必填、無預設值；指向正式資料目錄需 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1")
    ap.add_argument("--restart", action="store_true", help="丟棄核對進度，從頭重掃清單")
    ap.add_argument("--report-only", action="store_true", help="只用已掃到的進度與目前資料庫重新比對；不登入")
    return ap


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ8)


def _norm_url(url):
    u = (url or "").strip().lower().replace("://www.", "://")
    return u.rstrip("/")


def find_duplicates(rows):
    """rows：非公告的 article 列（dict）。回傳 [[article_id, ...], ...]（每組≥2、不同 ID 的實質重複）。"""
    groups = []
    for key_fn in (lambda r: ("u", _norm_url(r["url"])),
                   lambda r: ("t", (r["title"] or "").strip(), r["list_date"]) if r["title"] else None):
        buckets = {}
        for r in rows:
            k = key_fn(r)
            if k is not None:
                buckets.setdefault(k, set()).add(int(r["article_id"]))
        for ids in buckets.values():
            if len(ids) > 1:
                g = sorted(ids)
                if g not in groups:
                    groups.append(g)
    return sorted(groups)


def compare(store, seen, cutoff_ms, now_ms, complete):
    """把清單已見項目（seen：{id字串: {"a": 是否公告}}）與資料庫逐篇比對。回傳只含 ID 與狀態的 dict。"""
    missing, not_fetched, older_not_deferred = [], [], []
    ok = older_deferred = 0
    recent_ids = set()
    for sid, meta in sorted(seen.items(), key=lambda kv: int(kv[0])):
        aid = int(sid)
        if meta.get("a"):
            continue                                              # 公告不核對
        row = store.get_article_row(aid)
        if article_id_time.is_before_cutoff(aid, cutoff_ms, now_ms=now_ms):
            if row is not None and row["status"] == "deferred":
                older_deferred += 1
            elif row is None or row["status"] != "fetched":       # 早於截止日卻不是延後：只提示，不計缺漏
                older_not_deferred.append({"id": aid, "status": row["status"] if row else "absent"})
            continue
        recent_ids.add(aid)
        if row is None:
            missing.append(aid)
        elif row["status"] == "fetched":
            ok += 1
        else:
            not_fetched.append({"id": aid, "status": row["status"]})
    rows = [dict(r) for r in store.conn.execute(
        "SELECT article_id, url, title, list_date, status FROM article WHERE status != 'skipped'")]
    dup = find_duplicates(rows)
    db_not_in_list = []
    if complete:                                                  # 只有掃完整份清單，「庫內有、清單沒有」才有意義
        for r in rows:
            aid = int(r["article_id"])
            if str(aid) in seen or article_id_time.is_before_cutoff(aid, cutoff_ms, now_ms=now_ms):
                continue
            db_not_in_list.append({"id": aid, "status": r["status"]})
    return {"recent_ok": ok, "missing": missing, "not_fetched": not_fetched, "duplicates": dup,
            "older_deferred": older_deferred, "older_not_deferred": older_not_deferred,
            "db_not_in_list": db_not_in_list}


class Reconciler(object):
    def __init__(self, args, run_scraper=None, get_secret=None, now=None, delay_ms=None, base_url=None,
                 timeout_ms=30000, out=None):
        self.args = args
        self.blank_page = False                  # 本次是否讀到完全空白的清單頁（讀取異常）
        self.out = out or sys.stdout
        self.now = now or (lambda: datetime.datetime.now(TZ8))
        self.get_secret = get_secret or keychain_secrets.get_secret
        self.run_scraper = run_scraper or self._default_run_scraper
        # 下限防呆：低於 30 秒一律夾到 30 秒（測試環境變數除外，見 investanchors_limits）。
        self.delay_ms = investanchors_limits.clamp_delay_ms(delay_ms if delay_ms else [
            investanchors_limits.DELAY_RANGE[0] * 1000, investanchors_limits.DELAY_RANGE[1] * 1000])
        self.base_url = base_url or "https://investanchors.com"
        self.timeout_ms = timeout_ms
        self.report = None

    @staticmethod
    def _default_run_scraper(payload):
        import article_probe
        return article_probe.default_scraper_runner(payload)

    def say(self, msg):
        self.out.write(msg + "\n")

    # ------------------------------------------------------------ 進度檔
    def _probe_dir(self):
        return os.path.join(self.args.data_dir, PROBE_DIRNAME)

    def _state_path(self):
        return os.path.join(self._probe_dir(), STATE_FILENAME)

    def _load_state(self, cutoff_ms):
        fresh = {"cutoff_ms": int(cutoff_ms), "next_cursor": FIRST_CURSOR, "complete": False,
                 "old_pages": [], "seen": {}, "runs": 0}
        if self.args.restart:
            return fresh
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            return fresh
        if int(st.get("cutoff_ms", -1)) != int(cutoff_ms):        # 截止日被放寬過：舊進度作廢
            return fresh
        for k, v in fresh.items():
            st.setdefault(k, v)
        return st

    def _save_state(self, st):
        os.makedirs(self._probe_dir(), exist_ok=True)
        tmp = self._state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, sort_keys=True)
        os.replace(tmp, self._state_path())

    def _write_report(self, body):
        os.makedirs(self._probe_dir(), exist_ok=True)
        stamp = self.now().astimezone(TZ8).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self._probe_dir(), "reconcile-%s.json" % stamp)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, sort_keys=True, indent=1)
        return path

    # ------------------------------------------------------------ 主流程
    def main(self):
        try:
            self.args.data_dir = article_data_guard.resolve_data_dir(self.args.data_dir)
        except article_data_guard.DataDirRefused as e:
            self.say("拒絕執行：%s" % e)
            return 2
        if not os.path.isfile(os.path.join(self.args.data_dir, article_store.DB_FILENAME)):
            self.say("拒絕執行：文章庫不存在（尚未匯入／回補），沒有可核對的對象")
            return 2
        store = article_store.ArticleStore(self.args.data_dir, now=self.now)
        try:
            return self._execute(store)
        finally:
            store.close()

    def _execute(self, store):
        bf = store.get_backfill_state()
        if bf is None:
            self.say("拒絕執行：回補尚未啟動，沒有截止日可依據")
            return 2
        cutoff_ms = int(bf["cutoff_ms"])
        st = self._load_state(cutoff_ms)
        now_ms = int(_aware(self.now()).timestamp() * 1000)
        rc = 0
        if not self.args.report_only and not st["complete"]:
            rc = self._scan(store, st, cutoff_ms, now_ms)
        elif st["complete"] and not self.args.report_only:
            self.say("清單已掃完，直接用進度檔比對（不登入）；要重掃請用 --restart")
        if rc == 2:
            return rc
        result = compare(store, st["seen"], cutoff_ms, now_ms, st["complete"])
        body = {"generated_at": _aware(self.now()).isoformat(), "cutoff_date": bf["cutoff_date"],
                "scan_complete": bool(st["complete"]), "next_cursor": st["next_cursor"],
                "backfill_completed": bool(bf["completed"]), "seen_count": len(st["seen"]),
                "blank_page": bool(self.blank_page)}
        body.update(result)
        path = self._write_report(body)
        self.report = body
        self.say("核對%s：缺漏 %d、重複 %d 組、未抓取 %d、半年內已入庫 %d；早於截止日已延後 %d；報告 %s"
                 % ("完成" if st["complete"] else "（清單尚未掃完，僅供參考）",
                    len(result["missing"]), len(result["duplicates"]), len(result["not_fetched"]),
                    result["recent_ok"], result["older_deferred"], path))
        if result["missing"]:
            self.say("缺漏 ID：%s" % ", ".join(str(i) for i in result["missing"]))
        if result["duplicates"]:
            self.say("重複 ID 組：%s" % json.dumps(result["duplicates"]))
        if rc:
            return rc
        return 1 if (result["missing"] or result["duplicates"]) else 0

    # ------------------------------------------------------------ 登入讀清單（不開任何文章頁）
    def _scan(self, store, st, cutoff_ms, now_ms):
        guard = investanchors_limits.LimitGuard(store, self.now)
        halted = store.get_setting(HALT_SETTING)
        if halted:
            self.say("拒絕登入：排程已停止（%s）；排除後用匯入工具 --resume 恢復" % halted)
            return 2
        ok, reason = guard.may_login()
        if not ok:
            self.say("拒絕登入：%s（不勉強；改天再核對，或用 --report-only 先比對已掃到的部分）" % reason)
            return 2
        try:
            email = self.get_secret("email", service=keychain_secrets.INVESTANCHORS_SERVICE)
            password = self.get_secret("password", service=keychain_secrets.INVESTANCHORS_SERVICE)
        except Exception:
            self.say("無法讀取登入憑證（請依 quickstart 存入鑰匙圈）")
            return 1
        payload = {"mode": "import", "email": email, "password": password, "base_url": self.base_url,
                   "known_ids": [], "pending_ids": [],          # 與 max_articles=0 一起保證不開任何文章頁
                   "max_list_pages": investanchors_limits.MAX_LIST_PAGES, "max_articles": 0,
                   "delay_ms": self.delay_ms, "timeout_ms": self.timeout_ms,
                   "resume_cursor": int(st["next_cursor"])}
        payload.update(article_id_time.defer_thresholds(cutoff_ms, now_ms))
        run_id = store.start_run(TRIGGER)
        store.mark_login_started(run_id)                         # 啟動登入前先扣當日額度
        try:
            objs = self.run_scraper(payload)
        except Exception:
            objs = []
            self.say("scraper 執行失敗（細節不輸出）")
        return self._apply(store, guard, run_id, st, cutoff_ms, now_ms, objs)

    def _apply(self, store, guard, run_id, st, cutoff_ms, now_ms, objs):
        summary, items, page_counts = None, [], {}
        for o in objs:
            t = o.get("type")
            if t == "summary":
                summary = o
            elif t == "list_item":
                items.append(o)
            elif t == "list_page":
                page_counts[int(o["page"])] = int(o.get("items") or 0)
        stage = (summary or {}).get("stage_error") or ""
        counters = (summary or {}).get("counters") or {}
        login_ok = bool(summary and summary.get("logged_in"))
        result, blocked_until, rc = "ok", None, 0
        if summary is None:
            result, rc, login_ok = "scraper_error", 1, False
        elif stage.startswith("login_failed") or stage == "ambiguous_login_form":
            result, rc, login_ok = "login_failed", 1, False
        elif summary.get("blocked"):
            result, rc = "blocked", 1
            blocked_until = guard.block_until()
        elif stage:
            result, rc = "scraper_error", 1
        if login_ok and result in ("ok", "blocked") and any(1 for _ in items):
            mismatched = [it for it in items if not it.get("is_announcement") and
                          bool(it.get("defer")) != article_id_time.is_before_cutoff(
                              int(it["article_id"]), cutoff_ms, now_ms=now_ms)]
            if mismatched:                                       # 兩端判定不一致：不推進進度
                result, rc = "cutoff_mismatch", 1
                self.say("兩端「早於截止日」判定不一致（%d 項），本次不推進進度" % len(mismatched))
            else:
                self._advance(st, items, page_counts)
        logged_out = bool(summary and summary.get("logout_verified"))
        if not logged_out and stage != "no_browser":
            rc = 1
            self.say("警告：伺服器端登出未驗證（請檢查，勿連續重跑）")
        store.finish_run(run_id, login_ok if summary is not None else None, 0, 0, result, logged_out,
                         blocked_until=blocked_until, list_pages=(counters.get("list_pages") or 0) if login_ok else 0)
        self.say("登入讀清單：結果 %s；讀 %d 頁；登出%s"
                 % (result, counters.get("list_pages") or 0, "已驗證" if logged_out else "未驗證"))
        return rc

    def _advance(self, st, items, page_counts):
        by_page = {}
        for it in items:
            by_page.setdefault(int(it.get("page") or 1), []).append(it)
            st["seen"][str(int(it["article_id"]))] = {"a": bool(it.get("is_announcement"))}
        cursor_pages = set(p for p in by_page if p >= FIRST_CURSOR)
        # 完全空白的頁（連置頂都沒有）＝讀取異常：不計入、進度不越過它，報告註記 blank_page（不通知、不寫 DB）
        blanks = sorted(pg for pg, n in page_counts.items()
                        if pg >= FIRST_CURSOR and n == 0 and pg not in by_page)
        if blanks:
            self.blank_page = True
            self.say("讀到完全空白的清單頁（第 %d 頁），視為讀取異常：進度不越過、請稍後重試" % blanks[0])
            cursor_pages = set(p for p in cursor_pages if p < blanks[0])
        if cursor_pages:
            st["next_cursor"] = max(int(st["next_cursor"]), max(cursor_pages) + 1)
        cutoff_ms = int(st["cutoff_ms"])
        now_ms = int(_aware(self.now()).timestamp() * 1000)
        old = set(int(p) for p in st["old_pages"])
        for pg in cursor_pages:
            if all(it.get("is_announcement") or it.get("pinned")
                   or article_id_time.is_before_cutoff(int(it["article_id"]), cutoff_ms, now_ms=now_ms)
                   for it in by_page[pg]):
                old.add(pg)
        st["old_pages"] = sorted(old)
        if any(p in old and p + 1 in old for p in old):
            st["complete"] = True
        st["runs"] = int(st["runs"]) + 1
        self._save_state(st)


def run(argv=None, **deps):
    args = build_parser().parse_args(argv)
    return Reconciler(args, **deps).main()


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
