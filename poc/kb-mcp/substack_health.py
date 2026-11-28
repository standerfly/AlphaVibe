"""Substack 匯入（011）的每日健檢內容（US7；contracts/health-output.md §1）。

由 `check_scheduled_jobs.check_substack_import()` 呼叫：呼叫端以 `SubstackStore.open_readonly()`
（SQLite `mode=ro`）開庫後把 store 傳進來，本模組**只讀**、不開任何其他資料庫、不碰網路。
放在 `substack_*.py` 底下，讓 011 的健檢邏輯同樣受 tests/test_substack_isolation.py 的 T-A 靜態掃描守門。

輸出規則（SC-010、FR-026、FR-028、PO 決定 #15）：
* detail 只含數字、代碼、時間、作者代號；不含標題、內文、網址。
* 空間項只報現況，不下判定、不設界線；全文占比提醒用「提醒：」開頭的現況句。
* 每次健檢必有一筆 ok 摘要（以「上次成功」開頭），與有無事件無關。

僅標準庫、Python 3.9 相容。
"""
import datetime

import substack_store

JOB = "substack_import"
TZ8 = substack_store.TZ8

# 最後一次實際排程執行超過幾天＝排程沒在跑（容許 Mac 睡眠漏跑 2 晚；比照 010 的 3 天）
STALE_DAYS = 3
# 作者連續失敗幾次就在健檢提醒
AUTHOR_FAIL_WARN = 3
# 「上次成功」的耗時比較範圍：最近幾次實際執行
DURATION_WINDOW_RUNS = 7
# 請求統計與全文占比比較的天數
WINDOW_DAYS = 7
# FR-013：全文占比與近 7 天平均相差超過幾個百分點就提醒（Clarifications Q1）
RATIO_GAP_POINTS = 30

# 會抓取 feed 的觸發（retry_images／reclassify 不抓 feed，不算「匯入執行」）
FETCH_TRIGGERS = ("schedule", "catchup", "manual", "backfill")
SCHEDULED_TRIGGERS = ("schedule", "catchup")
COMPLETED_RESULTS = ("ok", "partial")
# FR-013 只計排程與手動抓到的文章（追補一次灌入會扭曲占比）
RATIO_SOURCES = ("schedule", "manual")
BLOCKED_OUTCOMES = ("blocked_403", "rate_limited_429", "challenge_html")


def _parse(value):
    """ISO 字串 → 帶時區的 datetime（無時區者視為台北時間）；解析不了回 None。"""
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ8)


def _actual_runs(conn):
    """真的執行過的匯入執行（排除 deferred／already_done 與非抓取觸發），新到舊。"""
    placeholders = ", ".join("?" for _ in substack_store.NON_RUN_RESULTS)
    trig = ", ".join("?" for _ in FETCH_TRIGGERS)
    sql = ("SELECT * FROM run WHERE trigger IN (%s) "
           "AND (result IS NULL OR result NOT IN (%s)) ORDER BY id DESC" % (trig, placeholders))
    return [dict(r) for r in conn.execute(sql, FETCH_TRIGGERS + substack_store.NON_RUN_RESULTS)]


def _duration_sec(run):
    start, end = _parse(run.get("started_at")), _parse(run.get("finished_at"))
    if start is None or end is None:
        return None
    return max(0, int(round((end - start).total_seconds())))


def _last_success_text(runs):
    done = [r for r in runs if r.get("result") in COMPLETED_RESULTS and r.get("finished_at")]
    if not done:
        return "上次成功 無"
    last = done[0]
    durations = [d for d in (_duration_sec(r) for r in runs[:DURATION_WINDOW_RUNS]
                             if r.get("finished_at")) if d is not None]
    dur = _duration_sec(last)
    return "上次成功 %s（耗時 %s 秒，最近 %d 次最長 %s 秒）" % (
        last["finished_at"], "?" if dur is None else dur, DURATION_WINDOW_RUNS,
        max(durations) if durations else "?")


def _request_stats_text(conn, now):
    cutoff = now - datetime.timedelta(days=WINDOW_DAYS)
    requested = ok200 = not_modified = blocked = skipped = 0
    fails = {}
    for row in conn.execute("SELECT at, requested, outcome FROM poll_log"):
        at = _parse(row["at"])
        if at is None or at < cutoff:
            continue
        outcome = row["outcome"] or ""
        if row["requested"]:
            requested += 1
        if outcome == "ok_200":
            ok200 += 1
        elif outcome == "not_modified":
            not_modified += 1
        elif outcome == "skipped_interval":
            skipped += 1
        elif outcome in BLOCKED_OUTCOMES:
            blocked += 1
        elif outcome:
            fails[outcome] = fails.get(outcome, 0) + 1
    fail_total = sum(fails.values())
    detail = ("（%s）" % "、".join("%s×%d" % (k, fails[k]) for k in sorted(fails))) if fails else ""
    return "近 %d 天請求 %d 次：200×%d、304×%d、失敗×%d%s、被擋×%d、間隔跳過×%d" % (
        WINDOW_DAYS, requested, ok200, not_modified, fail_total, detail, blocked, skipped)


def full_text_ratio(conn):
    """FR-013：回傳 (最近抓取日占比%, 近 7 天平均%或 None, 可比較天數)；沒有文章回 None。

    以文章 `fetched_at` 的台北日期分日、只計排程／手動來源、用原判斷 `article.completeness`
    （不隨重判變動，research R7）。近 7 天平均＝最近抓取日之前 7 個日曆日中有文章的日子各自占比的平均。"""
    placeholders = ", ".join("?" for _ in RATIO_SOURCES)
    by_day = {}
    for row in conn.execute("SELECT fetched_at, completeness FROM article WHERE source IN (%s)"
                            % placeholders, RATIO_SOURCES):
        at = _parse(row["fetched_at"])
        if at is None:
            continue
        day = at.astimezone(TZ8).date()
        f_count, total = by_day.get(day, (0, 0))
        by_day[day] = (f_count + (1 if row["completeness"] == "F" else 0), total + 1)
    if not by_day:
        return None
    latest = max(by_day)
    f_count, total = by_day[latest]
    latest_pct = 100.0 * f_count / total
    prev = []
    for back in range(1, WINDOW_DAYS + 1):
        item = by_day.get(latest - datetime.timedelta(days=back))
        if item:
            prev.append(100.0 * item[0] / item[1])
    if len(prev) < WINDOW_DAYS:
        return latest_pct, None, len(prev)
    return latest_pct, sum(prev) / len(prev), len(prev)


def import_findings(store, data_dir, now=None):
    """回傳 [(severity, JOB, detail), …]；store 必須是唯讀開啟的 SubstackStore。"""
    now = now or datetime.datetime.now(TZ8)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ8)
    conn = store.conn
    findings = []
    runs = _actual_runs(conn)
    any_run = conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    if not any_run:
        findings.append(("ok", JOB, "尚未有執行紀錄（排程未安裝？）"))

    scheduled = [r for r in runs if r.get("trigger") in SCHEDULED_TRIGGERS]
    if scheduled:
        last = scheduled[0]
        started = _parse(last.get("started_at"))
        if started is None or (now - started).total_seconds() > STALE_DAYS * 86400:
            findings.append(("warning", JOB, "超過 %d 天沒有排程執行（最後一次：%s）"
                             % (STALE_DAYS, last.get("started_at"))))

    for row in conn.execute("SELECT author_key, consecutive_failures, last_outcome FROM author "
                            "WHERE consecutive_failures >= ? ORDER BY author_key",
                            (AUTHOR_FAIL_WARN,)):
        findings.append(("warning", JOB, "作者 %s 連續失敗 %d 次（最近結果 %s）"
                         % (row["author_key"], int(row["consecutive_failures"]),
                            row["last_outcome"] or "-")))

    ratio = full_text_ratio(conn)
    if ratio is None:
        ratio_text = "全文占比：尚無排程或手動抓取的文章，不判斷"
    else:
        latest_pct, avg, days = ratio
        if avg is None:
            ratio_text = "全文占比：最近抓取日 %.0f%%，可比較天數 %d，未滿 %d 天，不判斷" % (
                latest_pct, days, WINDOW_DAYS)
        else:
            ratio_text = "全文占比：最近抓取日 %.0f%%，近 %d 天平均 %.0f%%（可比較 %d 天）" % (
                latest_pct, WINDOW_DAYS, avg, days)
            gap = abs(latest_pct - avg)
            if gap > RATIO_GAP_POINTS:
                findings.append(("warning", JOB,
                                 "提醒：全文占比 %.0f%%，近 %d 天平均 %.0f%%，相差 %.0f 個百分點（超過 %d）；"
                                 "只報現況，未改判、未停止匯入"
                                 % (latest_pct, WINDOW_DAYS, avg, gap, RATIO_GAP_POINTS)))

    abandoned = conn.execute(
        "SELECT COUNT(*) FROM article WHERE notify_status='abandoned'").fetchone()[0]
    if abandoned:
        findings.append(("warning", JOB, "有 %d 篇文章通知已放棄（累計 %d 次失敗）"
                         % (abandoned, substack_store.MAX_NOTIFY_ATTEMPTS)))

    if runs and runs[0].get("result") == "aborted_budget":
        findings.append(("warning", JOB, "最近一次執行因超過 20 分鐘預算而中止（run#%d），"
                         "未完成的圖片與通知留待下次" % runs[0]["id"]))

    comp = store.completeness_counts(effective=True)
    images = store.image_status_counts()
    summary = ("%s；%s；文章 P %d／F %d／N %d（有效完整度；其中被重判過 %d 篇）；"
               "圖片 已下載 %d、缺圖 %d、放棄 %d；未通知 %d；%s；%s" % (
                   _last_success_text(runs), _request_stats_text(conn, now),
                   comp["P"], comp["F"], comp["N"], comp["reclassified"],
                   images["downloaded"], images["missing"], images["abandoned"],
                   store.unnotified_count(), ratio_text,
                   substack_store.format_space_line(data_dir)))
    findings.append(("ok", JOB, summary))
    return findings
