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
import random
import sys
import tempfile
import shutil

import article_data_guard
import article_id_time
import article_image_tiles
import article_images
import article_manual_transcribe
import article_store
import article_transcribe
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
TRANSCRIBE_SETTING = "transcribe_enabled"   # 無此列＝關閉（預設）；不得以鑰匙圈有無金鑰當開關（T038）
# 2026-11-15 審查決定：夜間排程除了新文章的圖，每次再補轉最多 N 張先前未轉寫的圖；
# 單張累計失敗達 MAX_TRANSCRIBE_ATTEMPTS 次就不再自動補轉（只剩手動 --retranscribe）。
BACKFILL_TRANSCRIBE_PER_RUN = 10
MAX_TRANSCRIBE_ATTEMPTS = article_store.MAX_TRANSCRIBE_ATTEMPTS
SAMPLE_DIRNAME = "articles_probe"
BACKFILL_FIRST_CURSOR = 2         # 回補游標＝「下次要讀的頁碼」；第 1 頁每次都讀（新文章與置頂），游標從第 2 頁起
BLANK_PAGE_ALERT_AFTER = 3        # 同一游標位置連續幾次登入都拿到完全空白頁 → 通知 PO（不自動標完成）
BLANK_STREAK_SETTING = "backfill_blank_streak"   # 值 "<游標>:<連續次數>"；無此鍵或游標不符＝0
BACKFILL_STOP_PAGES = 2           # 連續幾頁「非置頂、非公告」項目全部早於門檻才算清單掃完（停止規則，research R11）
ID_ANOMALY_ALERT_OVER = 3         # id_time_ok=0 累計超過這個篇數 → 通知 PO（規律可能失效）
DETERMINISTIC_TILE_REASONS = ("too_many_tiles", "tile_too_small", "unsupported_or_corrupt_image",
                              "tile_bytes_too_large")   # 切片的確定性失敗：重試也不會變，計入補轉失敗次數
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
    "cutoff_mismatch": ("⚠️ 定錨匯入：回補的「太舊不開啟」判定在瀏覽器端與主程式不一致，"
                        "本次未標記任何延後、回補游標不前進。請回報。"),
    "backfill_blank_pages": ("⚠️ 定錨匯入：回補讀到的清單頁連續多次登入都是空白，回補暫停在原位置、未標記完成。"
                             "請到網站確認清單頁是否正常。"),
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
    """回補是否仍需登入：已啟動（backfill_state 有列）且尚未完成。完成後永遠為 False。"""
    state = store.get_backfill_state()
    return state is not None and not state["completed"]


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
    ap.add_argument("--backfill-since", default=None, metavar="YYYY-MM-DD",
                    help="PO 要求補抓更早的文章：把回補截止日往前放寬到該日（只能更早，否則拒絕）。"
                         "放寬範圍須 PO 同意；放寬後仍受每次 5 篇、每日登入至多 2 次的上限，慢慢補")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--enable-transcription", action="store_true", help="開啟表格圖轉寫（預設關閉；冪等，只改設定）")
    g.add_argument("--disable-transcription", action="store_true", help="關閉表格圖轉寫（冪等，只改設定）")
    ap.add_argument("--retranscribe", action="store_true",
                    help="只讀本機圖片補轉寫（未轉寫、或換模型後重轉）；不登入；轉寫開關關閉時拒絕")
    ap.add_argument("--reset-transcribe-attempts", action="store_true",
                    help="只能與 --retranscribe 併用：把達上限的未轉寫圖失敗次數歸零後重試")
    ap.add_argument("--transcribe-sample", type=int, default=None, metavar="N",
                    help="只讀本機圖片隨機抽 N 張（至少含 1 張長圖）轉寫，結果寫 <data-dir>/articles_probe/；"
                         "不寫資料庫、不登入；開關關閉時仍可執行")
    ap.add_argument("--export-untranscribed", action="store_true",
                    help="方案 D：唯讀匯出未轉寫的圖給 agent 讀（manifest.json＋AGENT_GUIDE.md＋長圖切片），"
                         "寫到 <data-dir>/articles_probe/manual-transcribe-<時間>/；不寫資料庫、不登入、不讀鑰匙圈")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="只能與 --export-untranscribed 併用：最多匯出幾張（預設 %d，上限 %d）"
                         % (article_manual_transcribe.DEFAULT_EXPORT_LIMIT, article_manual_transcribe.MAX_EXPORT_LIMIT))
    ap.add_argument("--import-transcription", default=None, metavar="RESULTS_JSON",
                    help="方案 D：匯入 agent 寫的 results.json（零網路、零鑰匙圈）；預設只預覽，需 --apply 才寫入")
    ap.add_argument("--apply", action="store_true", help="只能與 --import-transcription 併用：實際寫入")
    ap.add_argument("--overwrite", action="store_true",
                    help="只能與 --import-transcription 併用：允許覆寫已轉寫（done／not_table）的圖")
    return ap


class Importer(object):
    def __init__(self, args, fetch_mail=None, run_scraper=None, download_images=None, transcribe=None,
                 notifier=None, get_secret=None, now=None, sleeper=None, rng=None, delay_ms=None,
                 image_hosts=None, base_url=None, timeout_ms=30000, out=None,
                 transcribe_api_url=None, transcribe_model=None, transcribe_timeout=None,
                 tiles_runner=None, tile_tmp_root=None, sample_rng=None, auto_backfill=True):
        self.args = args
        self.out = out or sys.stdout
        self.now = now or _default_now
        self.get_secret = get_secret or keychain_secrets.get_secret
        self.fetch_mail = fetch_mail or self._default_fetch_mail
        self.run_scraper = run_scraper or self._default_run_scraper
        self.download_images = download_images or article_images.download_images
        self.transcribe = transcribe or article_transcribe.transcribe_image
        self.transcribe_api_url = transcribe_api_url
        self.transcribe_model = transcribe_model or article_transcribe.TRANSCRIBE_MODEL
        self.transcribe_timeout = transcribe_timeout
        self.tiles_runner = tiles_runner
        self.tile_tmp_root = tile_tmp_root
        self.sample_rng = sample_rng or random.Random()
        self.transcribe_aborted = False
        self.attempted_this_run = set()           # 本次已送出轉寫嘗試的 (article_id, seq)，補轉時不重複試
        self.notifier = notifier or _default_notifier
        self.sleeper = sleeper
        self.rng = rng
        # 下限防呆：低於 30 秒一律夾到 30 秒（測試環境變數除外，見 investanchors_limits）。
        self.delay_ms = investanchors_limits.clamp_delay_ms(delay_ms if delay_ms else [
            investanchors_limits.DELAY_RANGE[0] * 1000, investanchors_limits.DELAY_RANGE[1] * 1000])
        self.image_hosts = image_hosts or article_images.DEFAULT_ALLOWED_HOSTS
        self.base_url = base_url or "https://investanchors.com"
        self.timeout_ms = timeout_ms
        self.secrets = []
        self.older_fetched = 0
        self.auto_backfill = auto_backfill        # False＝首次登入不自動啟動回補（只給既有的非回補測試用）
        self._bf = None                           # 本次登入的回補脈絡（cutoff_ms、now_ms、resume 游標）

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
        manual_rc = self._manual_dispatch()
        if manual_rc is not None:
            return manual_rc
        if args.reset_transcribe_attempts and not args.retranscribe:
            self.say("拒絕執行：--reset-transcribe-attempts 只能與 --retranscribe 併用")
            return 2
        if args.backfill_since is not None:
            return self._backfill_since()
        if args.enable_transcription or args.disable_transcription:
            return self._toggle_transcription()
        if args.transcribe_sample is not None:
            return self._transcribe_sample(args.transcribe_sample)
        if args.dry_run:
            return self._dry_run()
        store = article_store.ArticleStore(args.data_dir, now=self.now)
        try:
            if args.retranscribe:
                return self._retranscribe(store)
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

    # ---------------------------------------------------------------- 方案 D：手動轉寫（Phase 10）
    def _manual_dispatch(self):
        """處理 --export-untranscribed／--import-transcription 與其附屬旗標的互斥檢查。
        回傳 None＝不是方案 D 的呼叫（照原流程）；否則回傳 exit code。完全不取信、不登入、不讀鑰匙圈、不連網。"""
        a = self.args
        export, imp = a.export_untranscribed, a.import_transcription is not None
        if not (export or imp):
            if a.limit is not None or a.apply or a.overwrite:
                self.say("拒絕執行：--limit／--apply／--overwrite 只能與方案 D 旗標併用")
                return 2
            return None
        if export and imp:
            self.say("拒絕執行：--export-untranscribed 與 --import-transcription 不可同時使用")
            return 2
        others = (a.retranscribe or a.reset_transcribe_attempts or a.transcribe_sample is not None or a.dry_run
                  or a.resume or a.reset_abandoned is not None or a.force_weekly or a.enable_transcription
                  or a.disable_transcription or a.max_articles is not None or a.backfill_since is not None)
        if others:
            self.say("拒絕執行：方案 D 旗標不可與其他動作旗標併用")
            return 2
        if export and (a.apply or a.overwrite):
            self.say("拒絕執行：--apply／--overwrite 只能與 --import-transcription 併用")
            return 2
        if imp and a.limit is not None:
            self.say("拒絕執行：--limit 只能與 --export-untranscribed 併用")
            return 2
        try:
            return self._manual_export() if export else self._manual_import()
        except article_manual_transcribe.ManualTranscribeError as e:
            self.say("拒絕執行：%s" % e)
            return 2
        except FileNotFoundError:
            self.say("文章庫尚未建立，沒有可處理的圖片")
            return 1

    def _manual_export(self):
        a = self.args
        limit = a.limit if a.limit is not None else article_manual_transcribe.DEFAULT_EXPORT_LIMIT
        r = article_manual_transcribe.export_untranscribed(
            a.data_dir, limit=limit, now=self.now, tiles_runner=self.tiles_runner, tile_tmp_root=self.tile_tmp_root)
        self.say("已匯出 %d 張未轉寫的圖（長圖 %d 張；切片降級 %d 張；檔案不存在略過 %d 張；無法讀取略過 %d 張）"
                 % (r["exported"], r["long_images"], r["tiles_degraded"], r["skipped_missing"],
                    r["skipped_unreadable"]))
        self.say("資料夾：%s" % r["out_dir"])
        self.say("請 agent 依 AGENT_GUIDE.md 讀圖並寫出 results.json；圖片來自付費文章，勿貼到公開處。")
        return 0

    def _manual_import(self):
        a = self.args
        apply_ = a.apply
        # 預覽用唯讀開庫（不建庫、不寫入）；--apply 才用可寫連線，且庫必須已存在
        store = article_store.ArticleStore.open_readonly(a.data_dir)
        try:
            plan = article_manual_transcribe.validate_results(a.import_transcription, store, overwrite=a.overwrite)
        finally:
            store.close()
        self.say("%s：將寫入 %d 筆、略過已轉寫 %d 筆（model=%s）" % (
            "寫入" if apply_ else "預覽（未寫入）", len(plan["rows"]), len(plan["skipped_done"]), plan["model"]))
        for iid, aid, seq, n in plan["details"]:
            self.say("  image_id=%d article_id=%d seq=%d 長度=%d 字" % (iid, aid, seq, n))
        if not apply_:
            self.say("以上是預覽；確認無誤後加 --apply 才會寫入。")
            return 0
        store = article_store.ArticleStore(a.data_dir, now=self.now)
        try:
            article_manual_transcribe.apply_plan(store, plan, now=self.now)
        finally:
            store.close()
        self.say("已寫入 %d 筆（單一交易）。" % len(plan["rows"]))
        return 0

    # ---------------------------------------------------------------- 放寬回補範圍（T044）
    def _backfill_since(self):
        """PO 要求補抓更早文章：只改資料庫（不取信、不登入、不讀金鑰）。只能往前放寬。"""
        a = self.args
        if (a.retranscribe or a.reset_transcribe_attempts or a.transcribe_sample is not None or a.dry_run
                or a.resume or a.reset_abandoned is not None or a.force_weekly
                or a.enable_transcription or a.disable_transcription or a.max_articles is not None):
            self.say("拒絕執行：--backfill-since 不可與其他動作旗標併用")
            return 2
        try:
            new_day = datetime.date.fromisoformat(a.backfill_since)
        except ValueError:
            self.say("拒絕執行：--backfill-since 必須是 YYYY-MM-DD 日期")
            return 2
        store = article_store.ArticleStore(a.data_dir, now=self.now)
        try:
            state = store.get_backfill_state()
            if state is None:
                self.say("拒絕執行：回補尚未啟動（第一次登入時才會寫入截止日），沒有可放寬的截止日")
                return 2
            new_date, new_ms = article_id_time.cutoff_from_date(new_day)
            if new_ms >= int(state["cutoff_ms"]):
                self.say("拒絕執行：新截止日 %s 不早於現有截止日 %s（只能往前放寬）；放寬範圍須 PO 同意"
                         % (new_date, state["cutoff_date"]))
                return 2
            store.widen_cutoff(new_date, new_ms, now=self.now())
            store.update_backfill(next_cursor=str(BACKFILL_FIRST_CURSOR), completed=False, list_done=False,
                                  now=self.now())
            back = 0
            for r in store.deferred_rows():          # ID 時間落在新舊截止日之間者（不再早於新門檻）轉回待抓
                if r.get("id_time_ok") and not article_id_time.is_before_cutoff(r["article_id"], new_ms):
                    if store.reactivate_deferred(r["article_id"]):
                        back += 1
            self.say("已放寬回補截止日：%s → %s；%d 篇延後文章轉回待抓；仍受每次 %d 篇、每日登入至多 2 次的上限，慢慢補（放寬範圍須 PO 同意）"
                     % (state["cutoff_date"], new_date, back, investanchors_limits.MAX_ARTICLES_PER_RUN))
            return 0
        finally:
            store.close()

    # ---------------------------------------------------------------- 轉寫（T037～T040）
    @staticmethod
    def transcription_enabled(store):
        return str(store.get_setting(TRANSCRIBE_SETTING, "0")) == "1"

    def _toggle_transcription(self):
        """只改設定：不取信、不登入、不讀任何金鑰。冪等，印出目前狀態。"""
        a = self.args
        if a.retranscribe or a.transcribe_sample is not None or a.dry_run or a.resume \
                or a.reset_abandoned is not None:
            self.say("拒絕執行：切換轉寫開關時不可同時帶其他動作旗標")
            return 2
        store = article_store.ArticleStore(a.data_dir, now=self.now)
        try:
            store.set_setting(TRANSCRIBE_SETTING, "1" if a.enable_transcription else "0")
            self.say("轉寫開關：%s" % ("已開啟" if self.transcription_enabled(store) else "已關閉"))
            return 0
        finally:
            store.close()

    def _transcribe_one(self, store, img):
        """轉寫一張本機圖並寫回資料庫。回傳 True 表示應中止本次後續圖（金鑰／額度問題）。永不丟例外。"""
        aid, seq = img["article_id"], img["seq"]
        try:
            path = os.path.join(store.data_dir, img["file_path"])
            with article_image_tiles.open_tiles(path, runner=self.tiles_runner, tmp_root=self.tile_tmp_root) as ts:
                if ts.status != "ok":
                    if ts.reason in DETERMINISTIC_TILE_REASONS:   # 確定性失敗：計次，累計達上限後不再自動補轉
                        self.attempted_this_run.add((aid, seq))
                        store.bump_transcribe_attempts(aid, seq)
                    return False                      # 保持 untranscribed，原因為固定代碼、不進任何輸出
                tiles = [b for _i, b, _mt in ts.iter_tile_bytes()]
                kw = {"get_secret": self.get_secret, "api_url": self.transcribe_api_url,
                      "model": self.transcribe_model, "timeout": self.transcribe_timeout,
                      "merge": article_image_tiles.merge_transcripts}
                if self.sleeper is not None:
                    kw["sleeper"] = self.sleeper
                r = self.transcribe(tiles, **kw)
            if r.get("abort"):
                return True                           # 缺金鑰／401 等：視為沒有送出，不計次
            self.attempted_this_run.add((aid, seq))
            if r.get("status") == "transcribed":
                if r.get("is_table") is False:
                    store.set_transcription(aid, seq, "not_table", is_table=False)
                    return False
                if (r.get("text") or "").strip():
                    store.set_transcription(aid, seq, "done", text=r["text"], model=r.get("model"), is_table=True)
                    return False
            store.bump_transcribe_attempts(aid, seq)  # 送出了但仍未轉寫
            return False
        except Exception:
            return False

    def _transcribe_article(self, store, aid):
        for img in store.list_images(aid):
            if self.transcribe_aborted:
                return
            if not img.get("file_path") or img.get("transcription_status") != "untranscribed":
                continue
            if self._transcribe_one(store, img):
                self.transcribe_aborted = True

    def _backfill_transcribe(self, store):
        """開關開啟時補轉先前未轉寫的圖（最多 BACKFILL_TRANSCRIBE_PER_RUN 張）；關閉時什麼都不做。"""
        if not self.transcription_enabled(store) or self.transcribe_aborted:
            return
        for img in store.images_to_backfill(BACKFILL_TRANSCRIBE_PER_RUN, exclude=self.attempted_this_run):
            if self._transcribe_one(store, img):
                self.transcribe_aborted = True
                return

    def _retranscribe(self, store):
        """只讀本機圖片：補轉 untranscribed，並重轉「模型不同於目前設定」的已轉寫圖。不登入、不啟動 scraper。"""
        if not self.transcription_enabled(store):
            self.say("拒絕執行：轉寫開關未開（先用 --enable-transcription 開啟）")
            return 2
        if self.args.reset_transcribe_attempts:
            self.say("已歸零失敗次數：%d 張" % store.reset_transcribe_attempts())
        todo = store.images_to_transcribe()
        todo += [dict(r) for r in store.conn.execute(
            "SELECT * FROM article_image WHERE file_path IS NOT NULL AND transcription_status='done' "
            "AND COALESCE(transcribed_model,'') != ? AND COALESCE(transcribed_model,'') NOT LIKE 'manual:%' "
            "ORDER BY article_id, seq", (self.transcribe_model,))]    # 方案 D 手動轉寫不被換模型重轉蓋掉
        done = 0
        for img in todo:
            if self.transcribe_aborted:
                break
            if self._transcribe_one(store, img):
                self.transcribe_aborted = True
            row = [i for i in store.list_images(img["article_id"]) if i["seq"] == img["seq"]][0]
            if row["transcription_status"] != img["transcription_status"] or \
                    row.get("transcribed_model") != img.get("transcribed_model"):
                done += 1
        left = len(store.images_to_transcribe())
        self.say("重轉完成：處理 %d 張、仍未轉寫 %d 張%s" % (done, left, "（因金鑰或額度問題中止）" if self.transcribe_aborted else ""))
        return 1 if (self.transcribe_aborted or left) else 0

    def _transcribe_sample(self, n):
        """抽查工具：只讀本機圖、不登入、不寫資料庫；結果寫 <data-dir>/articles_probe/transcribe-sample-<時間>.md。"""
        a = self.args
        if a.retranscribe or a.dry_run or a.resume or a.reset_abandoned is not None:
            self.say("拒絕執行：--transcribe-sample 不可與其他動作旗標併用")
            return 2
        if n < 1:
            self.say("拒絕執行：N 必須 ≥ 1")
            return 2
        try:
            store = article_store.ArticleStore.open_readonly(a.data_dir)
        except FileNotFoundError:
            self.say("文章庫尚未建立，沒有可抽查的圖片")
            return 1
        try:
            imgs = [dict(r) for r in store.conn.execute(
                "SELECT * FROM article_image WHERE file_path IS NOT NULL ORDER BY article_id, seq")]
            data_dir = store.data_dir
        finally:
            store.close()
        avail, longs = [], []
        for img in imgs:
            full = os.path.join(data_dir, img["file_path"])
            try:
                with open(full, "rb") as f:
                    size = article_image_tiles.image_size(f.read())
            except OSError:
                continue
            if size is None:
                continue
            img["_size"] = size
            avail.append(img)
            if article_image_tiles.is_long_image(*size):
                longs.append(img)
        if len(avail) < n:
            self.say("不足：目前本機有檔且可讀的圖片只有 %d 張（需要 %d 張），其中長圖 %d 張；不勉強抽樣" % (
                len(avail), n, len(longs)))
            return 1
        if not longs:
            self.say("不足：目前 %d 張圖片裡沒有長圖（高/寬 ≥ 1.5 且高 ≥ 2000px）；不勉強抽樣" % len(avail))
            return 1
        first = self.sample_rng.choice(longs)
        rest = [i for i in avail if i is not first]
        picked = [first] + self.sample_rng.sample(rest, n - 1)
        stamp = self.now().astimezone(TZ8).strftime("%Y%m%d-%H%M%S")
        out_dir = os.path.join(data_dir, SAMPLE_DIRNAME)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "transcribe-sample-%s.md" % stamp)
        lines = ["# 轉寫抽查（模型 %s；不寫資料庫）" % self.transcribe_model, ""]
        aborted = False
        for k, img in enumerate(picked, 1):
            w, h = img["_size"]
            lines.append("## %d. article_id=%s seq=%s｜%dx%d%s" % (
                k, img["article_id"], img["seq"], w, h, "｜長圖" if article_image_tiles.is_long_image(w, h) else ""))
            lines.append("原圖：%s" % os.path.join(data_dir, img["file_path"]))
            lines.append("")
            if aborted:
                lines += ["（因前一張遇到金鑰或額度問題，略過）", ""]
                continue
            res = self._sample_one(os.path.join(data_dir, img["file_path"]))
            lines.append("狀態：%s%s" % (res["status"], "（%s）" % res["reason"] if res.get("reason") else ""))
            lines.append("")
            if res["status"] == "transcribed":
                lines += ["```", res["text"] or "", "```", ""]
            aborted = bool(res.get("abort"))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.say("抽查完成：%d 張（含長圖），結果寫入 %s" % (n, out_path))
        return 0

    def _sample_one(self, path):
        try:
            with article_image_tiles.open_tiles(path, runner=self.tiles_runner, tmp_root=self.tile_tmp_root) as ts:
                if ts.status != "ok":
                    return {"status": "untranscribed", "reason": ts.reason}
                tiles = [b for _i, b, _mt in ts.iter_tile_bytes()]
                kw = {"get_secret": self.get_secret, "api_url": self.transcribe_api_url,
                      "model": self.transcribe_model, "timeout": self.transcribe_timeout,
                      "merge": article_image_tiles.merge_transcripts}
                if self.sleeper is not None:
                    kw["sleeper"] = self.sleeper
                r = self.transcribe(tiles, **kw)
            return {"status": r.get("status"), "reason": r.get("reason"), "text": r.get("text"),
                    "abort": r.get("abort")}
        except Exception:
            return {"status": "untranscribed", "reason": "exception"}

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
            self._backfill_transcribe(store)
            return 0
        rc = self._run_site(store, guard, triggers, unprocessed)
        self._backfill_transcribe(store)          # 新文章的轉寫之後再補轉舊圖（純本機，不需登入）
        return rc

    # ---------------------------------------------------------------- 登入、抓取、套用結果
    def _run_site(self, store, guard, triggers, unprocessed):
        cap = guard.cap_for_run(self.args.max_articles)
        run_id = store.start_run("+".join(triggers))
        try:
            email = self.get_secret("email", service=keychain_secrets.INVESTANCHORS_SERVICE)
            password = self.get_secret("password", service=keychain_secrets.INVESTANCHORS_SERVICE)
        except Exception:
            store.finish_run(run_id, None, 0, 0, "no_credentials", None)
            self.say("無法讀取登入憑證（請依 quickstart 存入鑰匙圈）")
            return 1
        self.secrets.extend([email, password])
        extra = self._backfill_context(store)
        pending = self._pending_ids(store, cap)
        payload = {"mode": "import", "email": email, "password": password, "base_url": self.base_url,
                   "known_ids": sorted(store.known_ids()), "pending_ids": pending,
                   "max_list_pages": investanchors_limits.MAX_LIST_PAGES, "max_articles": cap,
                   "delay_ms": self.delay_ms, "timeout_ms": self.timeout_ms}
        payload.update(extra)
        store.mark_login_started(run_id)               # **啟動登入前**先扣當日額度
        try:
            objs = self.run_scraper(payload)
        except Exception as e:
            objs = []
            self.say("scraper 執行失敗：%s" % investanchors_redact.safe_error(e, self.secrets))
        return self._apply(store, guard, run_id, triggers, unprocessed, objs)

    # ---------------------------------------------------------------- 回補（T042／T043）
    def _backfill_context(self, store):
        """第一次真正登入時寫入截止日（啟動日往前六個月，之後固定）；回傳要併進 scraper payload 的欄位。

        Python 是「太舊不開啟」判定的唯一權威：只把三個整數門檻交給 scraper（article_id_time.defer_thresholds）；
        resume_cursor＝下次要讀的清單頁碼（回補未完成且清單尚未掃完才有）。"""
        self._bf = None
        state = store.get_backfill_state()
        if state is None and self.auto_backfill:
            day = self.now().astimezone(TZ8).date()
            cutoff_date, cutoff_ms = article_id_time.cutoff_for(day)
            store.start_backfill(cutoff_date, cutoff_ms, now=self.now())
            store.update_backfill(next_cursor=str(BACKFILL_FIRST_CURSOR), now=self.now())
            state = store.get_backfill_state()
        if state is None:
            return {}
        now_ms = int(self.now().timestamp() * 1000)
        resume = None
        if not state["completed"] and not state["list_done"]:
            resume = int(state["next_cursor"] or BACKFILL_FIRST_CURSOR)
        self._bf = {"cutoff_ms": int(state["cutoff_ms"]), "now_ms": now_ms, "resume": resume}
        extra = article_id_time.defer_thresholds(state["cutoff_ms"], now_ms)
        extra["resume_cursor"] = resume
        return extra

    def _pending_ids(self, store, cap):
        """待抓清單。回補已啟動時，Python 先把「ID 時間早於門檻」的待辦（discovered）標 deferred，不交給 scraper。"""
        rows = store.list_pending()
        out = []
        for r in rows:
            aid = r["article_id"]
            if self._bf and r["status"] == "discovered" and \
                    article_id_time.is_before_cutoff(aid, self._bf["cutoff_ms"], now_ms=self._bf["now_ms"]):
                store.mark_deferred(aid)
                continue
            out.append(aid)
        return out[:cap]

    def _apply_progress(self, store, items, mismatched, empty_pages=()):
        """依本次讀到的清單推進回補進度：游標、停止規則、完成。有對帳不一致時什麼都不推進。"""
        bf = self._bf
        if bf is None or mismatched:
            return
        state = store.get_backfill_state()
        if state is None or state["completed"]:
            return
        list_done = bool(state["list_done"])
        if bf["resume"] is not None:
            by_page = {}
            for it in items:
                pg = int(it.get("page") or 1)
                if pg >= BACKFILL_FIRST_CURSOR:
                    by_page.setdefault(pg, []).append(it)
            # 完全沒有任何項目（連置頂都沒有）的頁＝讀取異常，不是「沒有更舊的了」：
            # 不計入連續頁判斷、游標不越過它；有置頂但無一般項目的頁仍照常參與判斷。
            blanks = sorted(pg for pg in empty_pages if pg >= BACKFILL_FIRST_CURSOR and pg not in by_page)
            first_blank = blanks[0] if blanks else None
            if first_blank is not None:
                by_page = dict((pg, v) for pg, v in by_page.items() if pg < first_blank)
            if by_page:
                store.update_backfill(next_cursor=str(max(int(state["next_cursor"] or 0), max(by_page) + 1)),
                                      now=self.now())
            self._track_blank_streak(store, bf["resume"], first_blank, bool(by_page))

            def page_all_old(pg):
                for it in by_page[pg]:
                    if it.get("is_announcement") or it.get("pinned"):
                        continue
                    if not article_id_time.is_before_cutoff(it["article_id"], bf["cutoff_ms"], now_ms=bf["now_ms"]):
                        return False
                return True        # 沒有任何一般項目（只剩置頂或公告）也算「該頁沒有更舊的文章」；完全空白的頁在上面已排除
            old = set(pg for pg in by_page if page_all_old(pg))
            if any(pg in old and pg + 1 in old for pg in old):
                list_done = True
                store.update_backfill(list_done=True, now=self.now())
        if list_done and not store.list_pending():
            store.update_backfill(completed=True, now=self.now())

    def _track_blank_streak(self, store, resume, first_blank, has_nonblank):
        """同一游標位置連續空白頁計數；達 BLANK_PAGE_ALERT_AFTER 通知一次（同日去重），不標完成。"""
        raw = store.get_setting(BLANK_STREAK_SETTING)
        n = 0
        if raw and ":" in raw:
            cur, _, cnt = raw.partition(":")
            if cur == str(resume) and cnt.isdigit():
                n = int(cnt)
        if has_nonblank:                                # 游標前進或讀到非空頁：歸零
            if raw is not None:
                store.set_setting(BLANK_STREAK_SETTING, "%d:0" % resume)
            return
        if first_blank is None or first_blank != resume:
            return                                      # 本次沒讀到游標頁（逾時等）：計數不變
        n += 1
        store.set_setting(BLANK_STREAK_SETTING, "%d:%d" % (resume, n))
        if n >= BLANK_PAGE_ALERT_AFTER:
            self.alert(store, "backfill_blank_pages")

    def _check_id_anomalies(self, store):
        if self._bf is not None and store.count_id_time_anomalies() > ID_ANOMALY_ALERT_OVER:
            self.alert(store, "id_time_anomaly", "any")

    def _apply(self, store, guard, run_id, triggers, unprocessed, objs):
        summary = None
        items, articles, errors = [], [], []
        empty_pages = []                                # 載入成功但沒有任何項目的清單頁（翻過最後一頁）
        for o in objs:
            t = o.get("type")
            if t == "summary":
                summary = o
            elif t == "list_item":
                items.append(o)
            elif t == "list_page" and not o.get("items"):
                empty_pages.append(int(o["page"]))
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
            mismatched = self._apply_list(store, items, via)
            if mismatched:                              # 兩端判定不一致：不寫延後（上面已略過）、不推進、通知
                self.alert(store, "cutoff_mismatch")
                result, failed_run = "cutoff_mismatch", True
            self._check_id_anomalies(store)
            self.older_fetched = 0
            ok_n, fail_n = self._apply_articles(store, articles, errors)
            self._apply_progress(store, items, mismatched, empty_pages)
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
            elif fail_n and result == "ok":
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
        """登記清單項目。回補已啟動時，用 Python 自己的 article_id_time 重算每項「延後」判定並與 scraper 回報對帳：
        一致且早於門檻 → 標 deferred（只存 ID、標題、清單日期）；不一致 → 不寫 deferred，回傳不一致的 ID 清單。"""
        bf = self._bf
        mismatched = []
        for it in items:
            aid = int(it["article_id"])
            ann = bool(it.get("is_announcement"))
            item_via = "backfill" if (bf and bf["resume"] is not None and int(it.get("page") or 1) > 1) else via
            store.upsert_discovered(aid, CANON_URL % aid, it.get("title") or "(無標題)",
                                    list_date=it.get("date"), via=item_via, pinned=bool(it.get("pinned")),
                                    now=self.now())
            if ann:
                store.mark_skipped(aid)
            if bf:
                mine = article_id_time.is_before_cutoff(aid, bf["cutoff_ms"], now_ms=bf["now_ms"])
                if mine != bool(it.get("defer")):
                    if aid not in mismatched:
                        mismatched.append(aid)
                elif mine and not ann:
                    store.mark_deferred(aid)
        return mismatched

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
        if self.transcription_enabled(store) and not self.transcribe_aborted:
            self._transcribe_article(store, aid)   # 開關關閉時：不呼叫模型、不讀 vision-api-key


def run(argv=None, **deps):
    args = build_parser().parse_args(argv)
    return Importer(args, **deps).main()


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
