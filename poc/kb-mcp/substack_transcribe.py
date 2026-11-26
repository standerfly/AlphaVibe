#!/usr/bin/env python3
"""Substack 手動少量轉寫試跑（011 US6；FR-020、FR-022～FR-024；contracts/cli.md §3、research R1）。

**只能手動觸發、不排程、會消耗 PO 的 claude.ai 訂閱用量**——所以採兩段式確認：

  1. `--plan`：零網路、零模型呼叫、唯讀開庫。列出試跑對象（內部 id、作者代號、發布日、圖數，不印標題）、
     預估 `claude -p` 呼叫次數（已下載圖數×2）與 6 碼**確認碼**（排序後 image_id 清單＋台北日期的雜湊前 6 碼）。
  2. PO 在當下對話說「確認」後，才執行 `--run --confirm <確認碼>`（與 plan 相同的選取參數）。
     以下任一成立即拒絕（exit 2／3）、**零模型呼叫、不寫試跑紀錄**：確認碼不符、跨日、選取結果變了或不符 FR-023、
     `XPC_SERVICE_NAME` 以 `com.alphavibe.` 開頭（＝本專案的 launchd 排程啟動；次防線，主防線是確認碼）、
     `--claude-bin` 不是可執行檔、執行鎖被占用（exit 3）。

選取規則（FR-023）：每位**啟用**作者取「有效完整度（`article_effective`，含重判）為 F、且至少 1 張 `downloaded` 圖」
中最新的 N 篇（`--per-author` 1～3，預設 1）；或 `--article-ids` 指定，每篇須通過同一規則、每作者 1～3 篇。
沒有符合文章的作者明列「無符合條件文章」，**不自動放寬**。

轉寫（通過所有檢查後）：先 `check_flags`／`check_auth`（不是 claude.ai 訂閱 → 中止）→ 每張圖 reader-1（預設 sonnet）
→ 是表格才跑驗證者（不同模型別名，預設 opus，`verify_text=` 帶 reader 結果）→ 寫 `image_transcription`。
非表格圖記 `is_table=0`、不產生文字（沿用 010 提示詞的限制，B7）。撞使用量上限／登入失效 → 立即停止、exit 5。
「消耗」只記實際模型呼叫次數 `claude_calls` 與圖數（取不到額度百分比，B8）。

隔離（research R1）：本模組只 import 010 的兩個低階元件——`claude_cli_runner.ClaudeCli`（訂閱專用防呆；
本模組不自造子行程環境，子行程環境一律由 ClaudeCli 的白名單建立）與 `transcription_pipeline.prepare_workdir`
（暫存工作夾，連同它丟出的 `SkipImage`）。讀寫對象只有 `substack.db`；不跑 PaddleOCR；不讀鑰匙圈
（`ClaudeCli(token_getter=None)`）；不提供 `--enable`；不安裝任何排程。import 上述元件會間接載入 010 的模組，
但不開任何 010 的庫——由 tests/test_substack_isolation.py 的 T-C 在全新子行程中以執行期攔截證明。

stdout／stderr 只印數字、作者代號、內部 id 與結果代碼：不含標題、內文、網址、轉寫文字。
退出碼：0 完成｜1 有圖失敗（partial）｜2 參數／資料目錄／設定檔／確認碼等拒絕｜3 忙碌（鎖被占用）｜
4 磁碟寫入失敗｜5 使用量上限／登入失效／登入方式不符而中止。

僅標準庫、Python 3.9 相容。
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import article_data_guard  # noqa: E402
import claude_cli_runner as CR  # noqa: E402
import substack_config  # noqa: E402
import substack_store  # noqa: E402
from transcription_pipeline import SkipImage, prepare_workdir  # noqa: E402

LOCK_NAME = ".substack_import.lock"          # 與 substack_import 共用同一把鎖（research R8）
TZ8 = datetime.timezone(datetime.timedelta(hours=8))
PER_AUTHOR_MIN, PER_AUTHOR_MAX, PER_AUTHOR_DEFAULT = 1, 3, 1
CODE_LEN = 6
CALLS_PER_IMAGE = 2                          # reader-1＋驗證者
DEFAULT_READER1, DEFAULT_VERIFIER = "sonnet", "opus"
LAUNCHD_PREFIX = "com.alphavibe."            # 本專案 launchd 排程的 Label 前綴（T-D 次防線）
RESULT_FOR_KIND = {"usage_limit": "aborted_usage_limit", "login": "aborted_login",
                   "auth_mode": "aborted_auth_mode"}

EXIT_OK, EXIT_PARTIAL, EXIT_REFUSED, EXIT_BUSY, EXIT_DISK, EXIT_ABORTED = 0, 1, 2, 3, 4, 5


class _RealClock(object):
    def now(self):
        return datetime.datetime.now(TZ8)


class _ArgError(Exception):
    pass


class _Refused(Exception):
    """可預期的拒絕；訊息只含固定說明與內部 id。"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)

    def exit(self, status=0, message=None):
        raise _ArgError(message or "")


def build_parser():
    p = _Parser(prog="substack_transcribe.py", description="Substack 手動少量轉寫試跑（011）")
    p.add_argument("--data-dir", dest="data_dir", default=None)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--report", action="store_true")
    p.add_argument("--confirm", default=None)
    p.add_argument("--per-author", dest="per_author", default=None)
    p.add_argument("--article-ids", dest="article_ids", default=None)
    p.add_argument("--trial-id", dest="trial_id", default=None)
    p.add_argument("--reader1-model", dest="reader1_model", default=None)
    p.add_argument("--verifier-model", dest="verifier_model", default=None)
    p.add_argument("--claude-bin", dest="claude_bin", default=None)
    p.add_argument("--timeout-sec", dest="timeout_sec", default=None)
    return p


def _parse_int(text, label):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        raise _Refused("%s 必須是整數" % label)


def validate_args(a):
    """參數層檢查（尚未開庫）；回傳正規化後的設定 dict。"""
    if not (a.plan or a.run or a.report):
        raise _Refused("必須指定 --plan、--run 或 --report 其中之一")
    if a.confirm is not None and not a.run:
        raise _Refused("--confirm 只能與 --run 一起使用")
    if a.run and not a.confirm:
        raise _Refused("--run 必須帶 --confirm <確認碼>（先執行 --plan 取得）")
    if a.trial_id is not None and not a.report:
        raise _Refused("--trial-id 只能與 --report 一起使用")
    if a.report and (a.per_author is not None or a.article_ids is not None):
        raise _Refused("--report 不接受選取參數")
    if not a.run and any(v is not None for v in (a.reader1_model, a.verifier_model,
                                                  a.claude_bin, a.timeout_sec)):
        raise _Refused("模型／claude 參數只能與 --run 一起使用")
    if a.per_author is not None and a.article_ids is not None:
        raise _Refused("--per-author 與 --article-ids 只能擇一")
    cfg = {"per_author": PER_AUTHOR_DEFAULT, "article_ids": None, "trial_id": None}
    if a.per_author is not None:
        n = _parse_int(a.per_author, "--per-author")
        if not PER_AUTHOR_MIN <= n <= PER_AUTHOR_MAX:
            raise _Refused("--per-author 只接受 %d～%d" % (PER_AUTHOR_MIN, PER_AUTHOR_MAX))
        cfg["per_author"] = n
    if a.article_ids is not None:
        ids = []
        for part in str(a.article_ids).split(","):
            if not part.strip():
                continue
            n = _parse_int(part, "--article-ids")
            if n <= 0:
                raise _Refused("--article-ids 必須是正整數")
            if n not in ids:
                ids.append(n)
        if not ids:
            raise _Refused("--article-ids 不可為空")
        cfg["article_ids"] = ids
    if a.trial_id is not None:
        cfg["trial_id"] = _parse_int(a.trial_id, "--trial-id")
    if a.run:
        reader = a.reader1_model or DEFAULT_READER1
        verifier = a.verifier_model or DEFAULT_VERIFIER
        for m in (reader, verifier):
            if m not in CR.MODEL_ALIASES:
                raise _Refused("模型必須是別名白名單之一：%s" % "、".join(CR.MODEL_ALIASES))
        if reader == verifier:
            raise _Refused("--reader1-model 與 --verifier-model 必須不同")
        timeout = CR.DEFAULT_TIMEOUT_SEC
        if a.timeout_sec is not None:
            try:
                timeout = float(a.timeout_sec)
            except ValueError:
                raise _Refused("--timeout-sec 必須是數字")
            timeout = int(timeout) if timeout == int(timeout) else timeout
        try:
            timeout = CR.clamp_timeout(timeout)
        except CR.ClaudeCliError as exc:
            raise _Refused(str(exc))
        claude_bin = a.claude_bin or CR.DEFAULT_CLAUDE_BIN
        try:
            CR.validate_bin(claude_bin)
        except CR.ClaudeCliError as exc:
            raise _Refused(str(exc))
        cfg.update(reader=reader, verifier=verifier, timeout=timeout, claude_bin=claude_bin,
                   confirm=str(a.confirm).strip().lower())
    return cfg


# ====================================================================== 選取（FR-023）
_ELIGIBLE_WHERE = (
    "e.effective_completeness = 'F' AND EXISTS (SELECT 1 FROM article_image i "
    "WHERE i.article_id = e.id AND i.status = 'downloaded' AND i.file_path IS NOT NULL)")


def _downloaded_images(store, article_id):
    return [dict(r) for r in store.conn.execute(
        "SELECT id, seq, file_path FROM article_image WHERE article_id=? "
        "AND status='downloaded' AND file_path IS NOT NULL ORDER BY seq", (article_id,))]


def _pick(store, row):
    images = _downloaded_images(store, row["id"])
    total = store.conn.execute("SELECT COUNT(*) FROM article_image WHERE article_id=?",
                               (row["id"],)).fetchone()[0]
    return {"article_id": row["id"], "author_key": row["author_key"],
            "published_at": row["published_at"], "images": images, "total_images": total}


def select_targets(store, enabled_keys, per_author, article_ids=None):
    """回傳 (groups, problems)。groups＝[(author_key, [pick, ...])]（空清單＝無符合條件文章）；
    problems 非空＝`--article-ids` 不符 FR-023（只含內部 id 與固定原因）。"""
    if article_ids is None:
        groups = []
        for key in enabled_keys:
            rows = store.conn.execute(
                "SELECT e.id, e.author_key, e.published_at FROM article_effective e "
                "WHERE e.author_key=? AND " + _ELIGIBLE_WHERE +
                " ORDER BY e.published_at DESC, e.id DESC LIMIT ?",
                (key, int(per_author))).fetchall()
            groups.append((key, [_pick(store, r) for r in rows]))
        return groups, []
    problems, by_author = [], {}
    for aid in article_ids:
        row = store.conn.execute(
            "SELECT e.id, e.author_key, e.published_at, e.effective_completeness, "
            "(SELECT COUNT(*) FROM article_image i WHERE i.article_id=e.id "
            " AND i.status='downloaded' AND i.file_path IS NOT NULL) AS downloaded "
            "FROM article_effective e WHERE e.id=?", (aid,)).fetchone()
        if row is None:
            problems.append("article_id=%d 不存在" % aid)
        elif row["author_key"] not in enabled_keys:
            problems.append("article_id=%d 的作者未啟用" % aid)
        elif row["effective_completeness"] != "F":
            problems.append("article_id=%d 有效完整度不是 F" % aid)
        elif not row["downloaded"]:
            problems.append("article_id=%d 沒有已下載的圖" % aid)
        else:
            by_author.setdefault(row["author_key"], []).append(_pick(store, row))
    for key, picks in by_author.items():
        if len(picks) > PER_AUTHOR_MAX:
            problems.append("作者 %s 指定了 %d 篇（每作者最多 %d 篇）"
                            % (key, len(picks), PER_AUTHOR_MAX))
    groups = []
    for key in enabled_keys:
        if key in by_author:
            picks = sorted(by_author[key], key=lambda p: (p["published_at"] or "", p["article_id"]),
                           reverse=True)
            groups.append((key, picks))
    return groups, problems


def all_picks(groups):
    return [p for _key, picks in groups for p in picks]


def image_ids_of(groups):
    return sorted(img["id"] for p in all_picks(groups) for img in p["images"])


def taipei_date(now):
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ8)
    return now.astimezone(TZ8).date()


def confirm_code(image_ids, day):
    """確認碼＝sha256(「排序後 image_id 以逗號相接｜台北日期 YYYY-MM-DD」) 的前 6 碼（不是密碼，只綁定計畫）。"""
    raw = "%s|%s" % (",".join(str(i) for i in sorted(image_ids)), day.isoformat())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:CODE_LEN]


# ====================================================================== 共用
def _enabled_keys(data_dir):
    try:
        cfg = substack_config.load_config(data_dir)
    except substack_config.ConfigMissing as exc:
        raise _Refused(str(exc))
    except substack_config.ConfigInvalid:
        raise _Refused("設定檔不合格（可用 substack_config.py validate 查原因）")
    return [e["key"] for e in cfg["authors"] if e.get("enabled")]


def _open_ro(data_dir):
    try:
        return substack_store.SubstackStore.open_readonly(data_dir)
    except FileNotFoundError as exc:
        raise _Refused(str(exc))


def _selection_flags(cfg):
    if cfg["article_ids"] is not None:
        return "--article-ids %s" % ",".join(str(i) for i in cfg["article_ids"])
    return "--per-author %d" % cfg["per_author"]


def _print_plan(out, now, groups, cfg, code):
    out.write("[%s] substack transcribe plan（零網路、零模型呼叫、唯讀）\n"
              % now.strftime("%Y-%m-%d %H:%M:%S"))
    n_articles = n_images = n_total = 0
    for key, picks in groups:
        if not picks:
            out.write("作者 %s：無符合條件文章\n" % key)
            continue
        out.write("作者 %s：\n" % key)
        for p in picks:
            n_articles += 1
            n_images += len(p["images"])
            n_total += p["total_images"]
            out.write("  article_id=%d 發布日=%s 已下載圖=%d 總圖=%d image_ids=%s\n"
                      % (p["article_id"], (p["published_at"] or "-")[:10], len(p["images"]),
                         p["total_images"], ",".join(str(i["id"]) for i in p["images"])))
    out.write("合計：文章 %d 篇；已下載圖 %d 張（文章總圖數 %d 張）；預估 claude -p 呼叫 %d 次"
              "（每張圖 reader-1＋驗證者各 1 次；非表格圖只需 1 次）\n"
              % (n_articles, n_images, n_total, n_images * CALLS_PER_IMAGE))
    if code is None:
        out.write("沒有可試跑的圖，不產生確認碼\n")
        return
    out.write("確認碼：%s（綁定本清單與台北日期 %s；跨日或清單變動須重新 --plan）\n"
              % (code, taipei_date(now).isoformat()))
    out.write("PO 在當下對話確認後才執行：--run --confirm %s %s\n" % (code, _selection_flags(cfg)))


# ====================================================================== --plan
def do_plan(data_dir, cfg, clock, out):
    keys = _enabled_keys(data_dir)
    store = _open_ro(data_dir)
    try:
        groups, problems = select_targets(store, keys, cfg["per_author"], cfg["article_ids"])
    finally:
        store.close()
    if problems:
        raise _Refused("指定的文章不符試跑規則（FR-023）：" + "；".join(problems))
    now = clock.now()
    ids = image_ids_of(groups)
    _print_plan(out, now, groups, cfg, confirm_code(ids, taipei_date(now)) if ids else None)
    return EXIT_OK


# ====================================================================== --report
def do_report(data_dir, cfg, out):
    store = _open_ro(data_dir)
    try:
        if cfg["trial_id"] is not None:
            rows = [dict(r) for r in store.conn.execute(
                "SELECT * FROM transcription_trial WHERE id=?", (cfg["trial_id"],))]
            if not rows:
                raise _Refused("找不到 trial#%d" % cfg["trial_id"])
        else:
            rows = [dict(r) for r in store.conn.execute(
                "SELECT * FROM transcription_trial ORDER BY id DESC")]
        out.write("substack transcribe report（唯讀）\n")
        if not rows:
            out.write("（尚無試跑紀錄）\n")
        for t in rows:
            out.write("trial#%d 開始=%s 結束=%s 確認碼=%s 文章=%d 圖：嘗試%d／成功%d／非表格%d／失敗%d "
                      "claude 呼叫=%d 模型=%s 結果=%s 重置時間=%s\n"
                      % (t["id"], t["started_at"] or "-", t["finished_at"] or "-",
                         t["confirm_code"] or "-", t["articles"] or 0, t["images_attempted"] or 0,
                         t["images_ok"] or 0, t["images_not_table"] or 0, t["images_failed"] or 0,
                         t["claude_calls"] or 0, t["models"] or "-", t["result"] or "running",
                         t["reset_hint"] or "-"))
        if cfg["trial_id"] is not None:
            for r in store.conn.execute(
                    "SELECT image_id, is_table, verdict, length(text) AS n FROM image_transcription "
                    "WHERE trial_id=? ORDER BY image_id", (cfg["trial_id"],)):
                out.write("  image_id=%d is_table=%s verdict=%s 文字長度=%d\n"
                          % (r["image_id"], r["is_table"], r["verdict"] or "-", r["n"] or 0))
    finally:
        store.close()
    return EXIT_OK


# ====================================================================== --run
def _check_not_scheduled(env):
    xpc = (env or {}).get("XPC_SERVICE_NAME") or ""
    if xpc.startswith(LAUNCHD_PREFIX):
        raise _Refused("疑似由本專案排程啟動（XPC_SERVICE_NAME 以 %s 開頭）；"
                       "手動轉寫只能由 PO 在終端機或對話中執行" % LAUNCHD_PREFIX)


def _validate_plan_for_run(data_dir, cfg, clock):
    """在鎖內、唯讀重算選取並比對確認碼。回傳 (groups, code)；不符即 _Refused（不寫任何東西）。"""
    keys = _enabled_keys(data_dir)
    store = _open_ro(data_dir)
    try:
        groups, problems = select_targets(store, keys, cfg["per_author"], cfg["article_ids"])
    finally:
        store.close()
    if problems:
        raise _Refused("指定的文章不符試跑規則（FR-023）：" + "；".join(problems))
    ids = image_ids_of(groups)
    if not ids:
        raise _Refused("沒有可試跑的圖（請先 --plan 確認）")
    day = taipei_date(clock.now())
    code = confirm_code(ids, day)
    if cfg["confirm"] == code:
        return groups, code
    if cfg["confirm"] == confirm_code(ids, day - datetime.timedelta(days=1)):
        raise _Refused("確認碼屬於前一日的 --plan（跨日）；請重新 --plan 並由 PO 再次確認")
    raise _Refused("確認碼不符（清單已變動或輸入錯誤）；請重新 --plan 並由 PO 再次確認")


def _safe_image_path(data_dir, rel):
    root = os.path.realpath(os.path.join(data_dir, substack_store.IMAGES_DIRNAME))
    full = os.path.realpath(os.path.join(data_dir, rel or ""))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    return full


class _Trial(object):
    """一次試跑在 substack.db 的紀錄；每筆寫入各自一個顯式交易。"""

    COUNTERS = ("images_attempted", "images_ok", "images_not_table", "images_failed",
                "claude_calls")

    def __init__(self, store, code, articles, models):
        self.store = store
        self.counts = dict((k, 0) for k in self.COUNTERS)
        with store.transaction():
            cur = store.conn.execute(
                "INSERT INTO transcription_trial(started_at, confirm_code, articles, "
                "images_attempted, images_ok, images_not_table, images_failed, claude_calls, models) "
                "VALUES (?,?,?,0,0,0,0,0,?)", (store.now_text(), code, articles, models))
            self.id = cur.lastrowid

    def save_image(self, image_id, is_table, text, reader, verifier, verdict, issues):
        with self.store.transaction():
            self.store.conn.execute(
                "INSERT INTO image_transcription(image_id, trial_id, is_table, text, reader_model, "
                "verifier_model, verdict, issues_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (image_id, self.id, 1 if is_table else 0, text if is_table else None, reader,
                 verifier, verdict,
                 json.dumps(issues, ensure_ascii=False) if issues else None,
                 self.store.now_text()))

    def finish(self, result, reset_hint=None):
        c = self.counts
        with self.store.transaction():
            self.store.conn.execute(
                "UPDATE transcription_trial SET finished_at=?, images_attempted=?, images_ok=?, "
                "images_not_table=?, images_failed=?, claude_calls=?, result=?, reset_hint=? "
                "WHERE id=?",
                (self.store.now_text(), c["images_attempted"], c["images_ok"],
                 c["images_not_table"], c["images_failed"], c["claude_calls"], result,
                 reset_hint, self.id))


def _transcribe_image(claude, trial, cfg, image_id, full, tiles_runner, tmp_root, say):
    """處理一張圖。回傳撞限類 CallResult（呼叫端必須立即停止）或 None。"""
    c = trial.counts
    try:
        workdir, names, tiled = prepare_workdir(full, tiles_runner, tmp_root)
    except SkipImage as exc:
        c["images_attempted"] += 1
        c["images_failed"] += 1
        say("image_id=%d 略過：%s" % (image_id, claude.safe(exc.reason)))
        return None
    except OSError as exc:
        c["images_attempted"] += 1
        c["images_failed"] += 1
        say("image_id=%d 略過：io:%s" % (image_id, type(exc).__name__))
        return None
    try:
        c["claude_calls"] += 1
        r1 = claude.call(cfg["reader"], workdir, names, tiled)
        if r1.aborts_run:
            return r1                     # 這張不算嘗試（比照 010）；試跑在呼叫端收尾
        c["images_attempted"] += 1
        if not r1.ok:
            c["images_failed"] += 1
            say("image_id=%d 失敗：reader1:%s" % (image_id, claude.safe(r1.detail)))
            return None
        if not r1.is_table:
            trial.save_image(image_id, False, None, cfg["reader"], None, None, None)
            c["images_not_table"] += 1
            say("image_id=%d 非表格（不轉寫）" % image_id)
            return None
        c["claude_calls"] += 1
        v = claude.call(cfg["verifier"], workdir, names, tiled, verify_text=r1.text)
        if v.aborts_run or not v.ok:
            # 轉寫文字已取得：仍存下（verdict 留空，代表未經驗證），計為失敗
            trial.save_image(image_id, True, r1.text, cfg["reader"], cfg["verifier"], None, None)
            c["images_failed"] += 1
            if v.aborts_run:
                return v
            say("image_id=%d 驗證失敗：%s（轉寫已存、未驗證）" % (image_id, claude.safe(v.detail)))
            return None
        trial.save_image(image_id, True, r1.text, cfg["reader"], cfg["verifier"], v.verdict,
                         v.issues)
        c["images_ok"] += 1
        say("image_id=%d 完成：verdict=%s" % (image_id, v.verdict))
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def do_run(data_dir, cfg, groups, code, env, clock, runner, claude_factory, tiles_runner,
           tmp_root, out):
    say = lambda text: out.write(text + "\n")   # noqa: E731
    store = substack_store.SubstackStore(data_dir, now=clock.now)
    try:
        picks = all_picks(groups)
        models = "reader1=%s;verifier=%s" % (cfg["reader"], cfg["verifier"])
        trial = _Trial(store, code, len(picks), models)
        claude = claude_factory(claude_bin=cfg["claude_bin"], timeout_sec=cfg["timeout"],
                                runner=runner, token_getter=None, base_env=env)
        work_cwd = tmp_root or tempfile.gettempdir()
        abort_kind, reset_hint = None, None
        try:
            claude.check_flags(work_cwd)
        except CR.ClaudeCliError as exc:
            abort_kind = "auth_mode"
            say("中止：claude 旗標檢查不通過（%s）" % claude.safe(exc))
        if abort_kind is None:
            auth = claude.check_auth(work_cwd)
            if auth != "ok":
                abort_kind = "login" if auth == "login" else "auth_mode"
                say("中止：登入狀態檢查結果＝%s（不是 claude.ai 訂閱登入，或登入失效）" % auth)
        if abort_kind is None:
            for p in picks:
                for img in p["images"]:
                    full = _safe_image_path(data_dir, img["file_path"])
                    if full is None:
                        trial.counts["images_attempted"] += 1
                        trial.counts["images_failed"] += 1
                        say("image_id=%d 略過：missing_file" % img["id"])
                        continue
                    abort = _transcribe_image(claude, trial, cfg, img["id"], full, tiles_runner,
                                              tmp_root, say)
                    if abort is not None:
                        abort_kind, reset_hint = abort.kind, abort.reset_hint
                        break
                if abort_kind is not None:
                    break
        if abort_kind is not None:
            result = RESULT_FOR_KIND.get(abort_kind, "aborted_auth_mode")
            exit_code = EXIT_ABORTED
        elif trial.counts["images_failed"]:
            result, exit_code = "partial", EXIT_PARTIAL
        else:
            result, exit_code = "ok", EXIT_OK
        trial.finish(result, reset_hint)
        c = trial.counts
        say("試跑 trial#%d 結果=%s 文章=%d 圖：嘗試%d／成功%d／非表格%d／失敗%d claude 呼叫=%d 模型=%s%s"
            % (trial.id, result, len(picks), c["images_attempted"], c["images_ok"],
               c["images_not_table"], c["images_failed"], c["claude_calls"], models,
               "；重置時間：%s" % (reset_hint or "未知") if abort_kind == "usage_limit" else ""))
        return exit_code
    finally:
        store.close()


# ====================================================================== 進入點
def run(argv=None, env=None, out=None, err=None, clock=None, runner=None, claude_factory=None,
        tiles_runner=None, tmp_root=None):
    """依賴注入（測試用假物件）：clock、runner（ClaudeCli 的子行程 runner）、claude_factory、tiles_runner、tmp_root。"""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    clock = clock or _RealClock()
    claude_factory = claude_factory or CR.ClaudeCli
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        a = build_parser().parse_args(argv)
    except _ArgError as exc:
        if str(exc):
            err.write(str(exc).rstrip() + "\n")
        return EXIT_REFUSED
    # 資料目錄防呆最先執行：在讀設定、開庫、碰任何外部程式之前
    try:
        data_dir = article_data_guard.resolve_data_dir(a.data_dir, env=env)
    except article_data_guard.DataDirRefused as exc:
        err.write("拒絕執行：%s\n" % exc)
        return EXIT_REFUSED
    try:
        cfg = validate_args(a)
        if a.report:
            return do_report(data_dir, cfg, out)
        if a.plan:
            return do_plan(data_dir, cfg, clock, out)
        _check_not_scheduled(os.environ if env is None else env)
    except _Refused as exc:
        err.write("拒絕執行：%s\n" % exc)
        return EXIT_REFUSED

    lock_handle = open(os.path.join(data_dir, LOCK_NAME), "w")
    try:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            out.write("忙碌：另一個 substack 執行正在進行，本次不轉寫、不寫庫\n")
            return EXIT_BUSY
        try:
            groups, code = _validate_plan_for_run(data_dir, cfg, clock)
        except _Refused as exc:
            err.write("拒絕執行：%s\n" % exc)
            return EXIT_REFUSED
        try:
            return do_run(data_dir, cfg, groups, code, env, clock, runner, claude_factory,
                          tiles_runner, tmp_root, out)
        except substack_store.DiskFullError:
            err.write("中止：磁碟或資料庫空間不足\n")
            return EXIT_DISK
    finally:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_handle.close()


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
