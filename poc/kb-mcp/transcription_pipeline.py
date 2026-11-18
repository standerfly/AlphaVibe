#!/usr/bin/env python3
"""定錨文章「新圖自動轉寫與驗證流水線」（010 Phase 14，clarification-log Q-029；2026-11-18 PO 決定，同日縮減為「最小差異」）。

沿用 2026-11-18 下午以互動 agent 實際驗證過的流程，只把「手動」換成排程呼叫 `claude -p`：

  選圖 → 暫存工作夾（單圖或長圖切片）
       → reader-1（`claude -p`，預設 sonnet）轉寫 → 單一交易寫入資料庫（unverified，model＝`claude-cli:<別名>`）
       → **驗證者**（另一次全新的 `claude -p`，不同模型別名，預設 opus）：輸入原圖（或切片）＋待查轉寫（每行加行號），
         沿用 VERIFY_GUIDE.md 的規則（逐字比對截斷、source-typo 定義與反例），以 --json-schema 回 {verdict, issues}
         → 轉成 `agent-spot-check` 驗證條目（verifier＝`pipeline-verifier-<別名>`），走既有 validate_verification／apply_verification 規則
       → PaddleOCR（本機 mobile、ocr_grid、離線）＋ compare「涵蓋」規則 → `compare-d-c` 條目（缺 paddle 或 inconclusive 不輸出）
  判定（既有規則）：兩家族都 ok → cross_checked（進搜尋）；任一 issues → flagged（只有 PO 能清除；Telegram 只通知張數）；其餘維持 unverified。
  驗證者**不是盲讀**（看得到待查轉寫）；PO 只核對 flagged，其他不抽查。

**零額外花費（PO 決定）**：只走 PO 的 claude.ai 訂閱（`claude -p`），絕不走 API 金鑰——見 `claude_cli_runner.py` 的硬性防呆與測試。
**使用量上限／登入失效**：偵測到就**立即停止本次執行**，剩下的圖維持原狀（untranscribed，或已轉寫但待驗證）、下次排程續做；不重試、不重複消耗；
只記錄重置時間字串與結果代碼（不存內容）。連續多次因此中止，健檢會警告。
**預設關閉**：`--enable` 之前除 `--dry-run` 外拒絕執行。上線門檻（PO 2026-11-18）：假 claude 自動測試全綠＋Mac 實測（PO 同意後另行）＋第一週 PO 看實際結果。

CLI（`--data-dir` 必填；正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，旗標最先檢查）：
  --dry-run                只列出將處理的圖、**完整命令列**與待 Mac 實測的假設清單，不執行任何外部程式（claude／paddle／node／鑰匙圈）、不寫庫
  --max-images N           單次最多處理幾張（預設 3、硬上限 5）；另有每日張數與每日執行次數上限
  --timeout-sec S          單次 claude 呼叫逾時（預設 600，夾在 30～1800）
  --reader1-model／--verifier-model   別名白名單 sonnet／opus／haiku／fable，兩者必須不同
  --claude-bin 路徑        絕對路徑（預設 /Users/stander/.local/bin/claude）
  --paddle-python 路徑     PaddleOCR 的獨立 venv python（預設 ~/.venvs/paddle/bin/python）；--no-paddle 略過數字家族
  --paddle-model-dir 路徑  本機模型根目錄（可選；mobile 模型約需 2GB 記憶體）
  --enable／--disable      寫入 articles.db setting `pipeline_enabled`
  --use-restricted         加 `--restricted`（把檔案工具限制在工作目錄；未在 Mac 實測，預設關）
  --unrestricted-read      明確 fallback：`--allowedTools Read` 不加路徑限定（預設拒絕；只有路徑限定語法在 Mac 實測不通時才由 PO 決定使用）
退出碼：0 完成（含沒有待處理的圖）、1 有圖處理失敗、2 參數／防呆拒絕、3 未啟用或前置條件不符、4 因使用量上限／登入失效／登入方式不符而中止。
stdout 與日誌只印數字與代碼：不含標題、全文、token、圖路徑。僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import article_data_guard  # noqa: E402
import article_image_tiles  # noqa: E402
import article_store  # noqa: E402
import article_verification as V  # noqa: E402
import claude_cli_runner as CR  # noqa: E402
import compare_transcriptions  # noqa: E402
import investanchors_redact  # noqa: E402
import pipeline_compare as PC  # noqa: E402

TZ8 = article_store.TZ8
DEFAULT_MAX_IMAGES = 3
HARD_MAX_IMAGES = 5
MAX_RUNS_PER_DAY = 2                 # 排程每日 2 次（PO 2026-11-18：保守預設；真實圖成本不可線性外推，須用真實圖實測後再調，放寬須 PO 同意）
MAX_IMAGES_PER_DAY = 6               # 每日張數上限（以「實際呼叫 claude 的張數」計）＝單次 3 張 × 每日 2 次
DEFAULT_PADDLE_PYTHON = os.path.expanduser("~/.venvs/paddle/bin/python")
PADDLE_EVAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paddle_eval.py")
PADDLE_TIMEOUT_PER_IMAGE_SEC = 300
LOCK_NAME = ".transcription_pipeline.lock"
SETTING_ENABLED = "pipeline_enabled"
AUDIT_KIND = "transcription_pipeline_write"
FLAGGED_NOTICE = "📋 定錨轉寫：%d 張圖需核對"
LIMIT_ABORT_WARN_RUNS = 3            # 健檢：連續幾次因使用量上限中止才警告
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_DISABLED, EXIT_ABORTED = 0, 1, 2, 3, 4
RESULT_FOR_KIND = {"usage_limit": "aborted_usage_limit", "login": "aborted_login", "auth_mode": "aborted_auth_mode"}
EXT_BY_MEDIA = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


class PipelineRefused(Exception):
    """可預期的拒絕（訊息只含固定說明）。"""


class PaddleUnavailable(Exception):
    """PaddleOCR 不可用或失敗（訊息只含固定代碼）。"""


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ====================================================================== 工作夾
class SkipImage(Exception):
    def __init__(self, reason, permanent):
        Exception.__init__(self, reason)
        self.reason, self.permanent = reason, permanent


def prepare_workdir(full, tiles_runner=None, tmp_root=None):
    """建立只放該圖（或其切片）的乾淨暫存夾。回傳 (workdir, file_names, tiled)。
    切不了（片數過多、位元組過大）＝permanent skip；本機沒有瀏覽器／tiler 失敗＝環境問題（非永久，不計失敗次數）。"""
    with open(full, "rb") as f:
        head = f.read()
    if article_image_tiles.image_size(head) is None:
        raise SkipImage("unreadable_image", True)
    workdir = tempfile.mkdtemp(prefix="pipeline-work-", dir=tmp_root)
    try:
        ts = article_image_tiles.open_tiles(full, runner=tiles_runner, tmp_root=tmp_root)
        with ts:
            if ts.status != article_image_tiles.STATUS_OK:
                raise SkipImage("tiles:%s" % ts.reason, not str(ts.reason).startswith("tiler_failed"))
            if ts.plan.single_whole:
                ext = EXT_BY_MEDIA.get(article_image_tiles.sniff_media_type(head) or "", ".png")
                name = "image" + ext
                shutil.copyfile(full, os.path.join(workdir, name))
                return workdir, [name], False
            names = []
            for k, data, _mt in ts.iter_tile_bytes():
                name = "tile-%02d.png" % k
                with open(os.path.join(workdir, name), "wb") as f:
                    f.write(data)
                names.append(name)
            return workdir, names, len(names) > 1
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


# ====================================================================== PaddleOCR（子行程）
def run_paddle_batch(paddle_python, image_paths, model_dir=None, timeout=None, variant="mobile", tmp_root=None):
    """用獨立 venv 的 python 執行 paddle_eval.py（ocr_grid、mobile、離線）。回傳 {path: {"status","text"}}。
    缺 paddle／失敗 → PaddleUnavailable（固定代碼）。mobile 模型約需 2GB 記憶體。"""
    if not paddle_python or not os.path.isfile(paddle_python) or not os.access(paddle_python, os.X_OK):
        raise PaddleUnavailable("paddle_python_missing")
    if not image_paths:
        return {}
    out_dir = tempfile.mkdtemp(prefix="pipeline-paddle-", dir=tmp_root)
    try:
        list_path = os.path.join(out_dir, "inputs.json")
        with open(list_path, "w", encoding="utf-8") as f:
            json.dump({"images": [{"path": p} for p in image_paths]}, f)
        argv = [paddle_python, PADDLE_EVAL, list_path, "--out", os.path.join(out_dir, "out"),
                "--mode", "ocr_grid", "--variant", variant]
        if model_dir:
            argv += ["--model-dir", model_dir]
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if os.environ.get(k)}
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        if os.environ.get("ALPHAVIBE_PADDLE_MODEL_DIR"):
            env["ALPHAVIBE_PADDLE_MODEL_DIR"] = os.environ["ALPHAVIBE_PADDLE_MODEL_DIR"]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True,
                                universal_newlines=True, encoding="utf-8", errors="replace")
        try:
            proc.communicate(timeout=timeout or PADDLE_TIMEOUT_PER_IMAGE_SEC * len(image_paths))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.communicate()
            raise PaddleUnavailable("paddle_timeout")
        if proc.returncode == 3:
            raise PaddleUnavailable("paddle_engine_unavailable")
        if proc.returncode not in (0, 1):
            raise PaddleUnavailable("paddle_exit_%s" % proc.returncode)
        outd = os.path.join(out_dir, "out")
        reports = sorted(n for n in (os.listdir(outd) if os.path.isdir(outd) else []) if n.startswith("paddle-eval-"))
        if not reports:
            raise PaddleUnavailable("paddle_no_report")
        with open(os.path.join(outd, reports[-1]), "r", encoding="utf-8") as f:
            rep = compare_transcriptions.parse_c_report(f.read())
        result = {}
        for sec in rep["sections"]:
            data = sec["modes"].get("ocr_grid")
            if data is not None:
                result[sec["path"]] = {"status": data["status"], "text": data["text"]}
        return result
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# ====================================================================== 設定與守衛
def parse_args(argv):
    ap = argparse.ArgumentParser(description="定錨表格圖自動轉寫與驗證流水線（Claude 訂閱零花費；預設關閉）")
    ap.add_argument("--data-dir", help="必填；正式資料目錄需 ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--enable", action="store_true")
    ap.add_argument("--disable", action="store_true")
    ap.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    ap.add_argument("--timeout-sec", type=int, default=CR.DEFAULT_TIMEOUT_SEC)
    ap.add_argument("--reader1-model", choices=CR.MODEL_ALIASES, default="sonnet")
    ap.add_argument("--verifier-model", choices=CR.MODEL_ALIASES, default="opus")
    ap.add_argument("--claude-bin", default=CR.DEFAULT_CLAUDE_BIN)
    ap.add_argument("--paddle-python", default=DEFAULT_PADDLE_PYTHON)
    ap.add_argument("--paddle-model-dir", default=None)
    ap.add_argument("--no-paddle", action="store_true")
    ap.add_argument("--use-restricted", action="store_true")
    ap.add_argument("--unrestricted-read", action="store_true")
    return ap.parse_args(argv)


def _validate_args(a):
    if sum(1 for x in (a.dry_run, a.enable, a.disable) if x) > 1:
        raise PipelineRefused("--dry-run／--enable／--disable 彼此互斥")
    if a.reader1_model == a.verifier_model:
        raise PipelineRefused("reader-1 與驗證者必須使用不同的模型別名")
    if a.max_images < 1 or a.max_images > HARD_MAX_IMAGES:
        raise PipelineRefused("--max-images 必須是 1～%d" % HARD_MAX_IMAGES)
    if not a.data_dir:
        raise PipelineRefused("資料目錄未指定。必須明確給 --data-dir")


# 需要在 Mac 實測確認的假設（--dry-run 會列出；quickstart §15 有同一份）
MAC_ASSUMPTIONS = (
    # 已於 2026-11-18 在 Mac 以降載後的旗標組合實測可用（sonnet 讀圖、opus 驗證：退出碼 0、structured_output 正常、permission_denials 0；
    # launchd 背景環境可直接用 claude.ai 訂閱登入，不需 setup-token）。以下仍待確認：
    "真實表格圖（尤其 2190×5327 長圖切 4 片）的圖片 token 遠大於合成小圖，成本不可線性外推；需用真實圖實測後再調每日上限（預設單次 3 張、每日 2 次）",
    "撞訂閱使用量上限時的退出碼與輸出文字（本程式以文字樣式偵測：hit your…limit／session|weekly limit／resets…／rate_limit）",
    "登入過期時的輸出文字（Expired — log in again／not logged in／401…）",
    "claude auth status 的 JSON 輸出欄位與白名單一致（authMethod＝claude.ai、apiProvider＝firstParty、loggedIn＝true、無 apiKeySource；不一致會中止並報 aborted_auth_mode）",
    "--allowedTools \"Read(//<暫存夾絕對路徑>/**)\" 路徑限定語法（官方 permissions：`//` 開頭＝檔案系統絕對路徑）能讓 Read 讀暫存夾內圖片；不通才由 PO 決定用 --unrestricted-read",
    "長圖切片（node＋Playwright）在 launchd 環境可用，且 claude Read 多張切片的行為正確",
    "轉寫與驗證的實際品質（第一週由 PO 看 flagged 與實際結果）",
)


# ====================================================================== 流水線本體
class Pipeline(object):
    def __init__(self, args, claude, paddle_batch=None, notify_fn=None, say=print, tiles_runner=None,
                 tmp_root=None, now=None):
        self.a = args
        self.claude = claude
        self.paddle_batch = paddle_batch
        self.notify_fn = notify_fn
        self.say = say
        self.tiles_runner = tiles_runner
        self.tmp_root = tmp_root
        self.now = now or (lambda: datetime.datetime.now(TZ8))

    # ---- 單張處理
    def _verdict_to_entries(self, store, item, text, verdict, issues, verifier, method):
        """組 verification.json → 既有 validate_verification／apply_verification（規則與人工匯入完全相同）。"""
        payload = PC.verification_payload(
            verifier, method, item["image_id"], item["sha256"], text, verdict, issues)
        d = tempfile.mkdtemp(prefix="pipeline-ver-", dir=self.tmp_root)
        try:
            path = os.path.join(d, "verification.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            plan = V.validate_verification(path, store)
            return V.apply_verification(store, plan, self.now)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _final_status(self, store, image_id):
        v = store.get_verification(image_id)
        return v["status"] if v else "unverified"

    def process_image(self, store, item, transcribe, counts, flagged_ids):
        """回傳 CallResult（撞限類，呼叫端須停止）或 None。transcribe＝True 時先做 reader-1。"""
        a = self.a
        workdir = None
        try:
            try:
                workdir, names, tiled = prepare_workdir(item["path"], self.tiles_runner, self.tmp_root)
            except SkipImage as e:
                if e.permanent and transcribe:
                    store.bump_transcribe_attempts(item["article_id"], item["seq"])
                elif e.permanent:
                    store.log_pipeline_verify_failure(item["image_id"])
                self.say("image_id=%d 略過：%s" % (item["image_id"], self.claude.safe(e.reason)))
                return None
            except OSError as e:
                self.say("image_id=%d 略過：io:%s" % (item["image_id"], type(e).__name__))
                return None
            counts["images_attempted"] += 1
            text = item.get("transcription")
            if transcribe:
                r1 = self.claude.call(a.reader1_model, workdir, names, tiled)
                if r1.aborts_run:
                    counts["images_attempted"] -= 1
                    return r1
                if not r1.ok:
                    counts["failed"] += 1
                    store.bump_transcribe_attempts(item["article_id"], item["seq"])
                    self.say("image_id=%d 失敗：reader1:%s" % (item["image_id"], self.claude.safe(r1.detail)))
                    return None
                try:
                    if not r1.is_table:
                        store.apply_pipeline_image(item["article_id"], item["seq"], "not_table", None, None, False, [],
                                                   audit_kind=AUDIT_KIND, audit_key=self._audit("not_table"))
                        counts["images_written"] += 1
                        counts["not_table"] += 1
                        return None
                    text = PC.normalize_text(r1.text)
                    store.apply_pipeline_image(item["article_id"], item["seq"], "done", text,
                                               CR.MODEL_PREFIX + a.reader1_model, True, [],
                                               audit_kind=AUDIT_KIND, audit_key=self._audit("transcribed"))
                    counts["images_written"] += 1
                except Exception as e:
                    counts["failed"] += 1
                    self.say("image_id=%d 寫入失敗：%s" % (item["image_id"], type(e).__name__))
                    return None
            # ---- 驗證者（全新的一次 claude -p；看得到待查轉寫，不盲讀）
            v = self.claude.call(a.verifier_model, workdir, names, tiled, verify_text=text)
            if v.aborts_run:
                return v                      # 轉寫已寫入（unverified）；下次排程由「待驗證」續做
            if not v.ok:
                counts["failed"] += 1
                store.log_pipeline_verify_failure(item["image_id"])
                self.say("image_id=%d 驗證失敗：%s" % (item["image_id"], self.claude.safe(v.detail)))
                return None
            try:
                self._verdict_to_entries(store, item, text, v.verdict, v.issues,
                                         "pipeline-verifier-%s" % a.verifier_model, "agent-spot-check")
                if self._final_status(store, item["image_id"]) != "flagged":
                    self._numeric(store, item, text)
            except (V.VerificationError, article_store.TranscriptionChanged, sqlite3.Error, OSError) as e:
                counts["failed"] += 1
                store.log_pipeline_verify_failure(item["image_id"])
                self.say("image_id=%d 驗證條目寫入失敗：%s" % (item["image_id"], type(e).__name__))
                return None
            st = self._final_status(store, item["image_id"])
            counts["flagged" if st == "flagged" else "cross_checked" if st == "cross_checked" else "unverified"] += 1
            if st == "flagged":
                flagged_ids.append(item["image_id"])
            return None
        finally:
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

    def _numeric(self, store, item, text):
        """PaddleOCR＋「涵蓋」規則 → compare-d-c 條目；缺 paddle／失敗／inconclusive 不輸出。"""
        if self.a.no_paddle or self.paddle_batch is None:
            return
        try:
            res = self.paddle_batch([item["path"]]).get(item["path"])
        except PaddleUnavailable as e:
            self.say("image_id=%d 數字家族不輸出：%s" % (item["image_id"], e))
            return
        except Exception as e:
            self.say("image_id=%d 數字家族不輸出：paddle_error:%s" % (item["image_id"], type(e).__name__))
            return
        if not res or res.get("status") != "transcribed":
            self.say("image_id=%d 數字家族不輸出：paddle_failed" % item["image_id"])
            return
        num = PC.numeric_family(item["sha256"], text, res["text"])
        if num["category"] in ("ok", "issues"):
            self._verdict_to_entries(store, item, text, num["category"], num["issues"], "pipeline-paddle", "compare-d-c")
        else:
            self.say("image_id=%d 數字家族不輸出：%s" % (item["image_id"], num["category"]))

    # ---- 正式流程
    def run_db(self, store, trigger):
        a = self.a
        counts = dict(images_attempted=0, images_written=0, cross_checked=0, flagged=0, unverified=0, not_table=0, failed=0)
        runs_today, images_today = store.pipeline_usage_today(self.now())
        if runs_today >= MAX_RUNS_PER_DAY:
            self.say("今日已執行 %d 次，達每日上限 %d 次，不再執行" % (runs_today, MAX_RUNS_PER_DAY))
            return EXIT_OK
        room = MAX_IMAGES_PER_DAY - images_today
        if room <= 0:
            self.say("今日已處理 %d 張，達每日上限 %d 張，不再執行" % (images_today, MAX_IMAGES_PER_DAY))
            return EXIT_OK
        cap = min(a.max_images, HARD_MAX_IMAGES, room)
        run_id = store.start_pipeline_run(trigger, self.now())
        result, reset_hint, exit_code, flagged_ids = "ok", None, EXIT_OK, []
        try:
            to_verify = store.pipeline_images_to_verify(cap + 50)
            to_do = store.images_to_backfill(cap + 50)
            if not to_verify and not to_do:
                result = "noop"
                self.say("沒有待處理的圖（untranscribed 或待驗證）")
                return EXIT_OK
            try:
                optional, degraded = self.claude.check_flags(tempfile.gettempdir())
            except CR.ClaudeCliError as e:
                result, exit_code = "aborted_flags", EXIT_ABORTED
                self.say("中止：%s" % self.claude.safe(e))
                return exit_code
            if degraded:
                self.say("降級的選用旗標：%d 項（%s）" % (len(degraded), "；".join(degraded)))
            auth = self.claude.check_auth(tempfile.gettempdir())
            if auth != "ok":
                result = {"login": "aborted_login", "auth_mode": "aborted_auth_mode"}.get(auth, "aborted_auth_mode")
                exit_code = EXIT_ABORTED
                self.say("中止：登入狀態檢查結果＝%s（不重試；請依 quickstart §15 處理）" % auth)
                return exit_code
            queue = [(img, False) for img in to_verify] + [(img, True) for img in to_do]
            abort = None
            for img, transcribe in queue:
                if counts["images_attempted"] >= cap:
                    break
                full = _safe_path(store.data_dir, img["file_path"])
                if full is None or not os.path.isfile(full):
                    continue
                item = {"image_id": img["id"], "article_id": img["article_id"], "seq": img["seq"], "path": full,
                        "sha256": _sha256_file(full), "transcription": img.get("transcription")}
                abort = self.process_image(store, item, transcribe, counts, flagged_ids)
                if abort is not None:
                    break
            if abort is not None:
                result, exit_code, reset_hint = RESULT_FOR_KIND[abort.kind], EXIT_ABORTED, abort.reset_hint
                self._save_debug(store, abort)
                self.say("中止：%s（剩下的圖維持原狀，下次排程續做；重置時間：%s）" % (abort.kind, reset_hint or "未知"))
            elif counts["failed"]:
                exit_code = EXIT_FAILED
            if flagged_ids and self.notify_fn is not None:
                try:
                    self.notify_fn(FLAGGED_NOTICE % len(flagged_ids))
                except Exception:
                    pass                                           # 通知壞掉不能讓流水線壞掉
            return exit_code
        except Exception as e:
            result = "error"
            self.say("流水線錯誤：%s" % self.claude.safe(type(e).__name__))
            raise
        finally:
            store.finish_pipeline_run(run_id, result, counts, reset_hint, self.now())
            self.say("流水線：處理 %d 張、新轉寫 %d（驗證後 cross_checked %d、flagged %d、未驗證 %d）、非表格 %d、失敗 %d；結果 %s%s"
                     % (counts["images_attempted"], counts["images_written"], counts["cross_checked"], counts["flagged"],
                        counts["unverified"], counts["not_table"], counts["failed"], result,
                        "；需核對 image_id：%s" % ",".join(str(i) for i in flagged_ids) if flagged_ids else ""))

    def _audit(self, what):
        stamp = self.now().astimezone(TZ8).strftime("%H%M%S%f")[:9]
        return "%s %s models=%s/%s" % (stamp, what, self.a.reader1_model, self.a.verifier_model)

    def _save_debug(self, store, ab):
        """撞限／登入失效時保留遮蔽後的短除錯文字（不含轉寫內容）到 <data-dir>/articles_probe/。"""
        if not ab.debug:
            return
        try:
            d = os.path.join(store.data_dir, "articles_probe")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "pipeline-debug-%s.txt" % self.now().astimezone(TZ8).strftime("%Y%m%d-%H%M%S"))
            with open(p, "w", encoding="utf-8") as f:
                f.write("kind=%s\nreset_hint=%s\n%s\n" % (ab.kind, ab.reset_hint, ab.debug))
        except OSError:
            pass

    # ---- dry-run
    def dry_run(self, store):
        a = self.a
        a_ = a
        runs_today, images_today = store.pipeline_usage_today(self.now())
        cap = max(0, min(a.max_images, HARD_MAX_IMAGES, MAX_IMAGES_PER_DAY - images_today))
        self.say("[dry-run] 不執行任何外部程式、不寫庫。pipeline_enabled＝%s；今日已執行 %d 次、已處理 %d 張。"
                 % ("開" if str(store.get_setting(SETTING_ENABLED, "0")) == "1" else "關", runs_today, images_today))
        queue = [(i, False) for i in store.pipeline_images_to_verify(cap + 50)] + [(i, True) for i in store.images_to_backfill(cap + 50)]
        picked = 0
        for img, transcribe in queue:
            if picked >= cap:
                break
            full = _safe_path(store.data_dir, img["file_path"])
            if full is None or not os.path.isfile(full):
                continue
            with open(full, "rb") as f:
                size = article_image_tiles.image_size(f.read(2 * 1024 * 1024))
            if size is None:
                continue
            picked += 1
            long_ = article_image_tiles.is_long_image(*size)
            steps = []
            if transcribe:
                steps += ["reader-1 claude -p --model %s 轉寫" % a_.reader1_model, "寫入 unverified"]
            else:
                steps.append("（已轉寫，只補驗證）")
            steps += ["驗證者 claude -p --model %s（看得到待查轉寫）" % a_.verifier_model, "以既有規則寫入驗證條目"]
            if not a_.no_paddle:
                steps.append("PaddleOCR（mobile、離線）涵蓋判定")
            self.say("[dry-run] image_id=%d（%dx%d%s）：%s" % (img["id"], size[0], size[1], "，長圖將切片" if long_ else "",
                                                          "；".join("%s%s" % ("①②③④⑤⑥"[k], t) for k, t in enumerate(steps))))
        self.say("[dry-run] 將處理 %d 張（單次上限 %d、今日剩餘額度 %d 張）" % (picked, min(a.max_images, HARD_MAX_IMAGES),
                                                                  MAX_IMAGES_PER_DAY - images_today))
        for label, model, verify in (("reader-1 轉寫", a.reader1_model, False), ("驗證者", a.verifier_model, True)):
            argv = CR.build_argv(a.claude_bin, model, "/<工作夾>", ["（選用旗標於實際執行時依 claude --help 決定）"], verify=verify,
                                 unrestricted_read=a.unrestricted_read)
            self.say("[dry-run] %s 完整命令列（提示詞走 stdin，cwd＝<工作夾>）：\n  %s" % (label, " ".join(shlex.quote(x) for x in argv)))
        self.say("[dry-run] 子行程環境只含：%s；訂閱 token（若鑰匙圈有 service stnd-investanchors／account claude-oauth-token）"
                 "以環境變數 %s 傳遞，值已遮蔽、不會印出；不含任何 ANTHROPIC_*／CLAUDE_CODE_USE_* 變數"
                 % ("、".join(CR.ENV_ALLOW), CR.TOKEN_ENV))
        self.say("[dry-run] 待 Mac 實測確認的假設（%d 項）：" % len(MAC_ASSUMPTIONS))
        for i, t in enumerate(MAC_ASSUMPTIONS, 1):
            self.say("  %d. %s" % (i, t))
        return EXIT_OK


def _safe_path(data_dir, rel):
    root = os.path.realpath(data_dir)
    full = os.path.realpath(os.path.join(root, rel or ""))
    return full if full.startswith(root + os.sep) else None


# ====================================================================== 入口
def _default_token_getter():
    import keychain_secrets
    try:
        return keychain_secrets.get_secret("claude-oauth-token", service=keychain_secrets.INVESTANCHORS_SERVICE)
    except keychain_secrets.SecretNotFound:
        return None


def run(argv=None, say=print, deps=None, env=None):
    """deps 可注入：runner、token_getter、paddle_batch、notify_fn、tiles_runner、tmp_root、now（測試用）。"""
    deps = deps or {}
    try:
        a = parse_args(argv)
    except SystemExit as e:
        return EXIT_REFUSED if e.code not in (0, None) else 0
    try:
        # 資料目錄防呆**最先**執行（在讀任何東西、開庫、碰任何外部程式之前）
        a.data_dir = article_data_guard.resolve_data_dir(a.data_dir, env)
        _validate_args(a)
        if not a.dry_run and not os.path.isfile(os.path.join(a.data_dir, article_store.DB_FILENAME)):
            raise PipelineRefused("找不到 %s（不建庫）" % article_store.DB_FILENAME)
    except article_data_guard.DataDirRefused as e:
        say("拒絕執行：%s" % e)
        return EXIT_REFUSED
    except PipelineRefused as e:
        say("拒絕執行：%s" % e)
        return EXIT_REFUSED

    claude = CR.ClaudeCli(a.claude_bin, a.timeout_sec, runner=deps.get("runner"),
                          token_getter=deps.get("token_getter") or _default_token_getter,
                          use_restricted=a.use_restricted, unrestricted_read=a.unrestricted_read)
    paddle_batch = deps.get("paddle_batch")
    if paddle_batch is None and not a.no_paddle:
        def paddle_batch(paths):
            return run_paddle_batch(a.paddle_python, paths, a.paddle_model_dir, tmp_root=deps.get("tmp_root"))
    notify_fn = deps.get("notify_fn")
    if notify_fn is None:
        def notify_fn(text):
            import notify
            notify.send_telegram(text)
    pipe = Pipeline(a, claude, paddle_batch, notify_fn, say, deps.get("tiles_runner"), deps.get("tmp_root"), deps.get("now"))

    try:
        if a.dry_run:                                              # 零副作用：唯讀開庫、不執行任何外部程式
            try:
                store = article_store.ArticleStore.open_readonly(a.data_dir)
            except FileNotFoundError:
                say("[dry-run] 文章庫尚未建立，沒有可處理的圖")
                return EXIT_OK
            try:
                return pipe.dry_run(store)
            finally:
                store.close()

        if a.enable or a.disable:
            store = article_store.ArticleStore(a.data_dir)
            try:
                if a.disable:
                    store.set_setting(SETTING_ENABLED, "0")
                    say("已停用流水線（pipeline_enabled=0）")
                    return EXIT_OK
                if str(store.get_setting("transcribe_enabled", "0")) == "1":
                    say("拒絕啟用：API 轉寫開關（transcribe_enabled）仍是開的，兩條路徑不得同時啟用")
                    return EXIT_DISABLED
                store.set_setting(SETTING_ENABLED, "1")
                say("已啟用流水線（pipeline_enabled=1）；排程安裝仍須 PO 在場同意，建議先做 Mac 實測（quickstart §15）")
                return EXIT_OK
            finally:
                store.close()

        # ---- 正式執行
        store = article_store.ArticleStore(a.data_dir)
        lock = None
        try:
            if str(store.get_setting(SETTING_ENABLED, "0")) != "1":
                say("拒絕執行：流水線尚未啟用（pipeline_enabled≠1）。啟用步驟見 quickstart §15；只想看計畫請加 --dry-run")
                return EXIT_DISABLED
            if str(store.get_setting("transcribe_enabled", "0")) == "1":
                say("拒絕執行：API 轉寫開關（transcribe_enabled）是開的，兩條路徑不得同時啟用")
                return EXIT_DISABLED
            try:
                CR.validate_bin(a.claude_bin)
            except CR.ClaudeCliError as e:
                say("拒絕執行：%s" % e)
                return EXIT_REFUSED
            lock = open(os.path.join(store.data_dir, LOCK_NAME), "w")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                say("另一個流水線行程正在執行，本次不執行")
                return EXIT_OK
            trigger = "manual" if sys.stdin is not None and sys.stdin.isatty() else "cron"
            return pipe.run_db(store, trigger)
        finally:
            if lock is not None:
                lock.close()
            store.close()
    except PipelineRefused as e:
        say("拒絕執行：%s" % e)
        return EXIT_REFUSED
    except CR.ClaudeCliError as e:
        say("拒絕執行：%s" % claude.safe(e))
        return EXIT_REFUSED


def main():
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
