"""010 Phase 0：定錨網站探查工具（唯讀、極低頻；PO 在場才可執行）。

目的：回答 specs/010-investanchors-article-import/research.md R0 的 P1～P8，
只輸出「結構事實」到 `<data_dir>/articles_probe/probe-<時間>.json`——
不含文章標題、全文、cookie、帳密。

硬性規約（R0 探查規約）：
  * 沒有 `--confirm-po-present` 直接拒絕，連鑰匙圈都不讀；
  * 登入 1 次、清單 ≤3 頁、開文章 ≤2 篇（Python 與 Node 兩層各自強制）；
  * 結束必走伺服器端登出並驗證，context.close() 不算登出；找不到登出機制就停止並回報；
  * 帳密由鑰匙圈 service `stnd-investanchors`（account `email`／`password`）讀出，
    只經 stdin 傳給 Node，不進 argv／環境變數／日誌。

僅標準庫，Python 3.9 相容。可注入 get_secret／scraper_runner／mail_prober／now 供測試。
"""
import argparse
import datetime
import email
import email.policy
import email.utils
import imaplib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlparse

import keychain_secrets
import statement_mailbox

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPER_JS = os.path.join(HERE, "scraper", "investanchors_scraper.js")

LIMITS = {"logins": 1, "list_pages": 3, "articles": 2}
MIN_DELAY_MS = 10000
DEFAULT_DELAY_MS = (30000, 90000)
DEFAULT_BASE_URL = "https://investanchors.com"
DEFAULT_DATA_DIR = os.path.join(HERE, "..", "data")
MAIL_SENDER = "postmaster@mailer.investanchors.com"
PROBE_DIRNAME = "articles_probe"
HALF_YEAR_DAYS = 183
MAX_STR = 200
SCRAPER_DEADLINE_SEC = 25 * 60
_ARTICLE_PATH_RE = re.compile(r"^/user/vip_contents/\d+$")


LOGOUT_UNVERIFIED_MSG = (
    "⚠️ 登出未驗證：探查的登入狀態可能仍留在網站伺服器端，PO 在自己的裝置上登出無法清除它。"
    "請勿再次執行探查，先回報主對話（可能已佔用一台裝置名額）。")


class ProbeError(Exception):
    """探查無法繼續。訊息不得含帳密、cookie、全文。"""


# ---------------------------------------------------------------- Node 子行程

def _node_binary():
    return shutil.which("node") or "/opt/homebrew/bin/node"


def default_scraper_runner(payload, verbose=False, timeout_sec=None, grace_sec=90):
    """啟動 Node scraper：帳密只寫進 stdin；stdout 逐行 JSON。回傳 JSON 物件清單。

    整體逾時用看門狗計時器實作（`for raw in proc.stdout` 在 Node 沒輸出時會一直卡住，
    單靠迴圈內檢查時間不會觸發）：到時間先送 SIGTERM（Node 會先走伺服器端登出再結束），
    `grace_sec` 後仍未結束才 kill。
    """
    node = _node_binary()
    if not os.path.exists(node):
        raise ProbeError("找不到 node，無法執行探查")
    timeout_sec = SCRAPER_DEADLINE_SEC if timeout_sec is None else timeout_sec
    try:
        proc = subprocess.Popen(
            [node, SCRAPER_JS],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None if verbose else subprocess.DEVNULL)
    except OSError:
        raise ProbeError("無法啟動 node")
    killer = threading.Timer(timeout_sec + grace_sec, proc.kill)
    terminator = threading.Timer(timeout_sec, proc.terminate)
    for t in (terminator, killer):
        t.daemon = True
        t.start()
    objs = []
    try:
        proc.stdin.write(json.dumps(payload).encode("utf-8"))
        proc.stdin.close()
        for raw in proc.stdout:
            try:
                objs.append(json.loads(raw.decode("utf-8").strip() or "{}"))
            except ValueError:
                continue
    finally:
        try:
            proc.wait(timeout=grace_sec + 30)
        except subprocess.TimeoutExpired:
            proc.kill()
        for t in (terminator, killer):
            t.cancel()
        try:
            proc.stdout.close()
        except (AttributeError, OSError):
            pass
    return objs


# ---------------------------------------------------------------- P4 通知信連結

class _HrefParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


_LONG_NUM_RE = re.compile(r"\d{13,}")
_TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def _path_shape(path):
    return re.sub(r"[0-9a-f]{6,}|\d+", "#", path or "")[:80]


def classify_mail_links(html_text):
    """只回分類、主機名與路徑形態（數字換成 #），不回完整網址與查詢值（追蹤網址可能帶個人識別碼）。

    `long_numbers` 是連結路徑／查詢值中 ≥13 位的數字（可能是文章 ID），僅供呼叫端內部比對，
    不得寫入報告。
    """
    parser = _HrefParser()
    parser.feed(html_text or "")
    direct, same_site, external = 0, 0, 0
    hosts, shapes, qkeys, long_numbers = [], {}, [], set()
    long_in_path = long_in_query = 0
    for href in parser.hrefs:
        u = urlparse(href)
        if u.scheme not in ("http", "https"):
            continue
        host = (u.hostname or "").lower()
        if host.endswith("investanchors.com") and _ARTICLE_PATH_RE.match(u.path or ""):
            direct += 1
        elif host.endswith("investanchors.com"):
            same_site += 1
        else:
            external += 1
            if host and host not in hosts and len(hosts) < 5:
                hosts.append(host)
        if host.endswith("investanchors.com"):
            sh = _path_shape(u.path)
            shapes[sh] = shapes.get(sh, 0) + 1
        nums_path = _LONG_NUM_RE.findall(u.path or "")
        qsl = parse_qsl(u.query, keep_blank_values=True)
        nums_query = [n for _k, v in qsl for n in _LONG_NUM_RE.findall(v)]
        long_in_path += 1 if nums_path else 0
        long_in_query += 1 if nums_query else 0
        long_numbers.update(nums_path + nums_query)
        for k, _v in qsl:
            if k[:20] not in qkeys and len(qkeys) < 10:
                qkeys.append(k[:20])
    return {"direct_article": direct, "same_site_other": same_site,
            "external_redirect": external, "external_hosts": hosts,
            "path_shapes": shapes, "query_keys": qkeys,
            "links_with_long_number_in_path": long_in_path,
            "links_with_long_number_in_query": long_in_query,
            "long_numbers": sorted(long_numbers)}


def _mail_date(msg):
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        return dt.astimezone(_TZ8).date().isoformat()
    except (TypeError, ValueError):
        return None


def probe_mail(address, app_password, imap_factory=None, days=30, max_messages=2,
               known_ids=None):
    """唯讀檢視定錨通知信的連結型態與寄達日期（BODY.PEEK，不標已讀、不跟隨任何連結）。

    known_ids：清單上已知的文章 ID 集合；給了就額外回報每封信裡的長數字有幾個對得上
    （只回數量，不回數字本身）。
    """
    factory = imap_factory or statement_mailbox._default_factory
    known_ids = set(str(i) for i in (known_ids or []))
    try:
        conn = factory()
        conn.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as e:
        raise ProbeError("Gmail 登入失敗：%s" % type(e).__name__)
    try:
        typ, _ = conn.select(statement_mailbox._find_all_mail(conn), readonly=True)
        if typ != "OK":
            raise ProbeError("無法開啟「所有郵件」")
        query = '"from:%s newer_than:%dd"' % (MAIL_SENDER, int(days))
        typ, data = conn.uid("SEARCH", "X-GM-RAW", query)
        if typ != "OK":
            raise ProbeError("Gmail 搜尋失敗")
        uids = (data[0] or b"").split() if data else []
        facts = {"messages_found": len(uids), "messages_examined": 0,
                 "sender_matches": None, "has_html_part": False,
                 "direct_article": 0, "same_site_other": 0,
                 "external_redirect": 0, "external_hosts": [],
                 "path_shapes": {}, "query_keys": [], "messages": []}
        for uid in uids[-max_messages:]:
            raw = statement_mailbox._fetch_parts(conn, uid, "BODY.PEEK[]")
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            facts["messages_examined"] += 1
            ok = MAIL_SENDER in str(msg.get("From") or "").lower()
            if facts["sender_matches"] is None or not ok:
                facts["sender_matches"] = ok
            rec = {"date": _mail_date(msg), "sender_ok": ok, "direct_article": 0,
                   "same_site_other": 0, "external_redirect": 0,
                   "distinct_long_numbers": 0, "ids_in_list": None, "ids_not_in_list": None}
            facts["messages"].append(rec)
            if not ok:
                continue
            body = msg.get_body(preferencelist=("html", "plain"))
            if body is None:
                continue
            if body.get_content_type() == "text/html":
                facts["has_html_part"] = True
            cls = classify_mail_links(body.get_content())
            for k in ("direct_article", "same_site_other", "external_redirect"):
                facts[k] += cls[k]
                rec[k] = cls[k]
            for h in cls["external_hosts"]:
                if h not in facts["external_hosts"] and len(facts["external_hosts"]) < 5:
                    facts["external_hosts"].append(h)
            for sh, n in cls["path_shapes"].items():
                facts["path_shapes"][sh] = facts["path_shapes"].get(sh, 0) + n
            for k in cls["query_keys"]:
                if k not in facts["query_keys"] and len(facts["query_keys"]) < 10:
                    facts["query_keys"].append(k)
            nums = set(cls["long_numbers"])
            rec["distinct_long_numbers"] = len(nums)
            if known_ids:
                rec["ids_in_list"] = len(nums & known_ids)
                rec["ids_not_in_list"] = len(nums - known_ids)
        top = sorted(facts["path_shapes"].items(), key=lambda kv: -kv[1])[:10]
        facts["path_shapes"] = dict(top)
        return facts
    except (imaplib.IMAP4.error, OSError) as e:
        raise ProbeError("Gmail 讀取失敗：%s" % type(e).__name__)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _id_time_date(article_id):
    s = str(article_id)
    if len(s) != 14:
        return None
    try:
        dt = datetime.datetime.fromtimestamp(int(s[:13]) / 1000.0, _TZ8)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.date()


def compare_mail_vs_list(messages, list_items, today, window_days=30):
    """只比日期、不記標題：通知信寄達日 vs 清單逐項日期。

    置頂項（跨頁重複）的清單日期不可靠，改用文章 ID 推得的建立日期。
    """
    start = today - datetime.timedelta(days=window_days)
    mail_days = {}
    for m in messages:
        if not m.get("sender_ok") or not m.get("date"):
            continue
        d = datetime.date.fromisoformat(m["date"])
        if start <= d <= today:
            mail_days[d] = mail_days.get(d, 0) + 1
    seen, art_days = set(), {}
    for it in list_items:
        if it.get("announcement") or it["id"] in seen:
            continue
        seen.add(it["id"])
        d = None
        if it.get("dup_across_pages"):
            d = _id_time_date(it["id"])
        elif it.get("date"):
            try:
                d = datetime.date.fromisoformat(it["date"])
            except ValueError:
                d = None
        if d and start <= d <= today:
            art_days[d] = art_days.get(d, 0) + 1

    def near(d, days):
        return any((d + datetime.timedelta(days=k)) in days for k in (-1, 0, 1))

    all_days = sorted(set(mail_days) | set(art_days))
    return {
        "window": [start.isoformat(), today.isoformat()],
        "mails_in_window": sum(mail_days.values()),
        "articles_in_window": sum(art_days.values()),
        "articles_on_days_with_no_mail_same_day": sum(
            n for d, n in art_days.items() if d not in mail_days),
        "articles_with_no_mail_within_1_day": sum(
            n for d, n in art_days.items() if not near(d, mail_days)),
        "mail_days_with_no_article_same_day": len([d for d in mail_days if d not in art_days]),
        "mails_with_multiple_long_numbers": len(
            [m for m in messages if (m.get("distinct_long_numbers") or 0) > 1]),
        "mail_total_ids_in_list": sum((m.get("ids_in_list") or 0) for m in messages),
        "mail_total_ids_not_in_list": sum((m.get("ids_not_in_list") or 0) for m in messages),
        "per_day": [{"date": d.isoformat(), "mails": mail_days.get(d, 0),
                     "articles": art_days.get(d, 0)} for d in all_days],
    }


def _latest_list_report(data_dir):
    d = os.path.join(os.path.abspath(data_dir), PROBE_DIRNAME)
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d), reverse=True):
        if not name.startswith("probe-"):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding="utf-8") as f:
                rep = json.load(f)
        except (OSError, ValueError):
            continue
        if (rep.get("P1_list_pagination") or {}).get("list_items"):
            return path
    return None


# ---------------------------------------------------------------- P8 估算

def _resolve_date(item, today):
    if item.get("date"):
        try:
            return datetime.date.fromisoformat(item["date"])
        except ValueError:
            return None
    md = item.get("md")
    if md:
        try:
            month, day = (int(x) for x in md.split("-"))
            d = datetime.date(today.year, month, day)
            if d > today + datetime.timedelta(days=31):
                d = datetime.date(today.year - 1, month, day)
            return d
        except ValueError:
            return None
    return None


def estimate_half_year(items, today):
    """依清單日期估算半年內篇數。清單日期只作粗篩（FR-005），公告不計。"""
    dated = []
    for it in items:
        if it.get("is_announcement"):
            continue
        d = _resolve_date(it, today)
        if d:
            dated.append(d)
    out = {"dated_items": len(dated), "undated_items": 0,
           "observed_from": None, "observed_to": None,
           "items_within_half_year": 0, "rate_per_day": None,
           "estimated_half_year_count": None,
           "method": "rate_extrapolation_from_observed_pages",
           "caveat": "只讀至多 3 頁，外推值僅供參考；真正篇數以回補實跑為準"}
    out["undated_items"] = len([i for i in items if not i.get("is_announcement")]) - len(dated)
    if not dated:
        return out
    cutoff = today - datetime.timedelta(days=HALF_YEAR_DAYS)
    out["observed_from"] = min(dated).isoformat()
    out["observed_to"] = max(dated).isoformat()
    out["items_within_half_year"] = len([d for d in dated if d >= cutoff])
    span = (max(dated) - min(dated)).days + 1
    if len(dated) >= 2 and span >= 7:
        rate = len(dated) / float(span)
        out["rate_per_day"] = round(rate, 3)
        out["estimated_half_year_count"] = int(round(rate * HALF_YEAR_DAYS))
    return out


def analyze_list(page1, page2, today):
    """清單逐項分析：跨頁重複項（疑似置頂）不參與日期範圍與半年內計數。"""
    ids1 = set(i["article_id"] for i in page1)
    dup_ids = ids1 & set(i["article_id"] for i in page2)
    cutoff = today - datetime.timedelta(days=HALF_YEAR_DAYS)

    def dates(items):
        out = []
        for it in items:
            if it.get("is_announcement") or it["article_id"] in dup_ids:
                continue
            d = _resolve_date(it, today)
            if d:
                out.append(d)
        return out

    def rng(items):
        ds = dates(items)
        return {"count": len(ds),
                "from": min(ds).isoformat() if ds else None,
                "to": max(ds).isoformat() if ds else None}

    p2_dates = dates(page2)
    nondup = [i for i in page1 + page2 if i["article_id"] not in dup_ids]
    all_dates = dates(page1) + p2_dates
    dup_dates = sorted(
        (_resolve_date(i, today).isoformat() if _resolve_date(i, today) else "?")
        for i in page1 if i["article_id"] in dup_ids)
    return {
        "unique_items": len(set(i["article_id"] for i in page1 + page2)),
        "duplicated_across_pages": len(dup_ids),
        "duplicated_item_dates_sorted": dup_dates,
        "page1_excluding_duplicates": rng(page1),
        "page2_excluding_duplicates": rng(page2),
        "items_within_half_year_excluding_duplicates": len([d for d in all_dates if d >= cutoff]),
        "half_year_boundary_reached_on_page2": any(d < cutoff for d in p2_dates),
        "rate_estimate_excluding_duplicates": estimate_half_year(nondup, today),
    }


def check_id_monotonic(items, today):
    """文章 ID 是否隨發布日期單調遞增（若是，日後可用 ID 做更穩的截止判斷）。"""
    pairs = []
    for it in items:
        if it.get("is_announcement"):
            continue
        d = _resolve_date(it, today)
        if d:
            pairs.append((d, it["article_id"]))
    if len(pairs) < 3:
        return "insufficient_data"
    pairs.sort()
    ids = [p[1] for p in pairs]
    return all(a <= b for a, b in zip(ids, ids[1:]))


# ---------------------------------------------------------------- 報告

def _by_step(facts):
    out = {}
    for f in facts:
        out.setdefault(f.get("step"), []).append(f.get("data") or {})
    return out


def build_report(facts, summary, mail, today, started_at):
    steps = _by_step(facts)
    p1 = (steps.get("list_page_1") or [{}])[0]
    p2 = (steps.get("list_page_2") or [{}])[0]
    p1_items = list(p1.get("items") or [])
    p2_items = list(p2.get("items") or [])
    items = p1_items + p2_items
    dup_ids = set(i["article_id"] for i in p1_items) & set(i["article_id"] for i in p2_items)
    list_items = [
        {"id": i["article_id"], "date": i.get("date") or i.get("md"),
         "announcement": bool(i.get("is_announcement")), "read": i.get("read_state"),
         "page": pg, "dup_across_pages": i["article_id"] in dup_ids}
        for pg, group in ((1, p1_items), (2, p2_items)) for i in group]
    counters = summary.get("counters") or {}
    login = (steps.get("login") or [{}])[0]
    mech = (steps.get("logout_mechanism") or [{}])[0]
    logout = (steps.get("logout") or [{}])[0]
    read_state = (steps.get("read_state") or [{}])[0]
    dates_full = len([i for i in items if i.get("date")])
    dates_md = len([i for i in items if i.get("md") and not i.get("date")])
    return {
        "generated_at": started_at,
        "limits": LIMITS,
        "counters": counters,
        "P1_list_pagination": {
            "paging_type": p1.get("paging_type"),
            "items_per_page_page1": p1.get("items_per_page"),
            "items_per_page_page2": p2.get("items_per_page"),
            "overlap_page1_page2": p2.get("overlap_with_page1"),
            "has_rel_next": p1.get("has_rel_next"),
            "next_href_path": (p1.get("next_href") or "").split("?")[0][:100],
            "page_query_keys": p1.get("page_query_keys"),
            "load_more_button": p1.get("load_more_button"),
            "list_items": list_items,
        },
        "P2_logout": {
            "mechanism_found": mech.get("found"),
            "candidates": mech.get("candidates"),
            "attempts": logout.get("attempts"),
            "server_side_verified": logout.get("verified"),
            "context_close_is_not_logout": True,
        },
        "P2a_P2b_observation": {
            "login_at": summary.get("login_at"),
            "logout_at": summary.get("logout_at"),
            "need_po_observation": [
                "P2a：探查期間 PO 只保留手機一台登入（電腦瀏覽器先登出），探查瀏覽器算第二台；"
                "結束後確認手機是否仍在線、有沒有被登出",
                "P2b：被動結論——以伺服器端登出已驗證為依據，不做任何額外登入測試（避免三台同時上線）",
            ],
        },
        "P3_read_state": {
            "changed_after_open": read_state.get("changed"),
            "had_unread_target": read_state.get("was_unread_before"),
            "comparisons": read_state.get("comparisons"),
        },
        "P4_mail_links": mail,
        "P5_list_structure": {
            "tabs": p1.get("tabs"),
            "announcements_on_page1": len([i for i in (p1.get("items") or [])
                                           if i.get("is_announcement")]),
            "items_with_full_date": dates_full,
            "items_with_month_day_only": dates_md,
            "items_without_date": len(items) - dates_full - dates_md,
        },
        "P6_article_dom": steps.get("article") or [],
        "P7_block_and_login": {
            "blocked": bool(summary.get("blocked")),
            "stage_error": summary.get("stage_error"),
            "login_scheme": login.get("scheme"),
            "login_final_path": login.get("final_path"),
            "remember_checkbox": login.get("remember_checkbox"),
            "remember_default_checked": login.get("remember_default_checked"),
            "login_failure_reason": login.get("reason"),
        },
        "P8_half_year": analyze_list(p1_items, p2_items, today),
        "P8_id_monotonic_with_date_excluding_duplicates": check_id_monotonic(
            [i for i in items if i["article_id"] not in dup_ids], today),
    }


def sanitize(report, secrets):
    """寫檔前的最後一道閘：不得含帳密、不得含長字串（防止全文／標題流出）。"""
    def walk(o):
        if isinstance(o, str):
            if len(o) > MAX_STR:
                raise ProbeError("報告含過長字串（疑似內文），拒絕寫檔")
            for s in secrets:
                if s and len(s) < 6 and o == s:
                    raise ProbeError("報告含與憑證相同的值，拒絕寫檔")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(report)
    dumped = json.dumps(report, ensure_ascii=False)
    for s in secrets:
        if s and len(s) >= 6 and s in dumped:
            raise ProbeError("報告含憑證內容，拒絕寫檔")


def _write_report(data_dir, report, now, prefix="probe"):
    out_dir = os.path.join(os.path.abspath(data_dir), PROBE_DIRNAME)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s.json" % (prefix, now.strftime("%Y%m%d-%H%M%S")))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- 進入點

def _limit_violations(counters):
    bad = []
    if (counters.get("logins") or 0) > LIMITS["logins"]:
        bad.append("logins")
    if (counters.get("list_pages") or 0) > LIMITS["list_pages"]:
        bad.append("list_pages")
    if (counters.get("articles_opened") or 0) > LIMITS["articles"]:
        bad.append("articles")
    return bad


def run(argv=None, get_secret=None, scraper_runner=None, mail_prober=None,
        now=None, out=None, allow_short_delay=False, delay_ms=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="010 定錨網站探查（唯讀、極低頻）")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--confirm-po-present", action="store_true",
                    help="PO 本人在場並同意此次探查（必填，否則拒絕執行）")
    ap.add_argument("--confirm-one-device-only", action="store_true",
                    help="PO 已確認定錨帳號目前只有一台裝置（手機）登入、電腦瀏覽器已登出"
                         "（必填：網站規定同帳號最多兩台，探查瀏覽器算一台）")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--article-id", action="append", default=[],
                    help="指定要開啟的文章 ID（最多 %d 篇；不足時補一篇對照文章）" % LIMITS["articles"])
    ap.add_argument("--skip-mail", action="store_true",
                    help="略過 Gmail 通知信連結檢查（P4）")
    ap.add_argument("--mail-only", action="store_true",
                    help="只唯讀檢視通知信連結形態與寄達日期並與清單日期比對；不登入定錨網站、不啟動瀏覽器")
    ap.add_argument("--confirm-mail-read", action="store_true",
                    help="PO 同意讀取 Gmail（--mail-only 必填；唯讀、不標已讀、不跟隨連結）")
    ap.add_argument("--list-report", default=None,
                    help="第二次探查報告路徑（--mail-only 比對用；預設取最新含逐項清單者）")
    ap.add_argument("--mail-days", type=int, default=30)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    def say(msg):
        out.write(msg + "\n")

    if args.mail_only:
        return _run_mail_only(args, get_secret, mail_prober, now, out)

    if not args.confirm_po_present:
        say("拒絕執行：探查會用 PO 的會員帳號登入定錨網站，必須 PO 在場並加上 "
            "--confirm-po-present。未讀取任何憑證、未連線。")
        return 2

    if len(args.article_id) > LIMITS["articles"] or not all(
            re.match(r"^\d{1,20}$", a) for a in args.article_id):
        say("拒絕執行：--article-id 最多 %d 篇，且必須是純數字" % LIMITS["articles"])
        return 2
    if not args.confirm_one_device_only:
        say("拒絕執行：網站規定同一帳號最多兩台裝置上線，探查的瀏覽器算一台。請 PO 先把電腦"
            "瀏覽器登出、只保留手機一台登入，再加上 --confirm-one-device-only。"
            "未讀取任何憑證、未連線。")
        return 2

    get_secret = get_secret or keychain_secrets.get_secret
    scraper_runner = scraper_runner or (
        lambda payload: default_scraper_runner(payload, verbose=args.verbose))
    now_fn = now or datetime.datetime.now
    started = now_fn()
    delay = tuple(delay_ms or DEFAULT_DELAY_MS)
    if not allow_short_delay and delay[0] < MIN_DELAY_MS:
        say("拒絕執行：頁面間隔下限為 %d 毫秒" % MIN_DELAY_MS)
        return 2

    try:
        email_addr = get_secret("email", service=keychain_secrets.INVESTANCHORS_SERVICE)
        password = get_secret("password", service=keychain_secrets.INVESTANCHORS_SERVICE)
    except keychain_secrets.SecretNotFound as e:
        say("無法開始：%s" % e)
        return 1
    secrets = [email_addr, password]

    mail = {"skipped": True}
    if not args.skip_mail:
        try:
            gmail_addr = get_secret("gmail-address")
            gmail_pw = get_secret("gmail-app-password")
            secrets.extend([gmail_addr, gmail_pw])
            prober = mail_prober or probe_mail
            mail = prober(gmail_addr, gmail_pw)
        except (keychain_secrets.SecretNotFound, ProbeError) as e:
            mail = {"error": type(e).__name__, "detail": str(e)[:150]}

    payload = {
        "mode": "probe", "email": email_addr, "password": password,
        "base_url": args.base_url,
        "max_list_pages": LIMITS["list_pages"], "max_articles": LIMITS["articles"],
        "target_article_ids": list(args.article_id),
        "delay_ms": list(delay), "timeout_ms": 30000,
    }
    try:
        objs = scraper_runner(payload)
    except ProbeError as e:
        say("探查失敗：%s" % e)
        return 1

    facts = [o for o in objs if o.get("type") == "fact"]
    summaries = [o for o in objs if o.get("type") == "summary"]
    if not summaries:
        say("⚠️ 探查異常結束（沒有收到 summary），無法確認是否已登出。" + LOGOUT_UNVERIFIED_MSG[len("⚠️ 登出未驗證："):])
        return 1
    summary = summaries[-1]

    report = build_report(facts, summary, mail, started.date(), started.isoformat())
    violations = _limit_violations(summary.get("counters") or {})
    report["limit_violations"] = violations
    try:
        sanitize(report, secrets)
        path = _write_report(args.data_dir, report, started)
    except ProbeError as e:
        say("探查完成但報告未寫出：%s" % e)
        return 1

    say("探查報告：%s" % path)
    ok = True
    if violations:
        say("⚠️ 超過硬上限：%s" % ",".join(violations))
        ok = False
    if summary.get("stage_error") == "no_logout_mechanism":
        say("⚠️ 停止：找不到伺服器端登出機制，不得進入實作，請回報主對話。")
        ok = False
    elif summary.get("stage_error"):
        say("⚠️ 探查中止：%s" % summary.get("stage_error"))
        ok = False
    if summary.get("logged_in") and not (summary.get("logged_out")
                                         and summary.get("logout_verified")):
        say(LOGOUT_UNVERIFIED_MSG)
        ok = False
    if not summary.get("logged_in"):
        ok = False
    say("探查%s。" % ("完成" if ok else "未完全成功"))
    return 0 if ok else 1


def _run_mail_only(args, get_secret, mail_prober, now, out):
    def say(msg):
        out.write(msg + "\n")

    if not args.confirm_mail_read:
        say("拒絕執行：--mail-only 會讀取 PO 的 Gmail（唯讀），必須 PO 同意並加上 --confirm-mail-read。"
            "未讀取任何憑證、未連線。")
        return 2
    if not 1 <= args.mail_days <= 90:
        say("拒絕執行：--mail-days 必須介於 1～90")
        return 2
    get_secret = get_secret or keychain_secrets.get_secret
    started = (now or datetime.datetime.now)()
    list_path = args.list_report or _latest_list_report(args.data_dir)
    list_items = []
    if list_path:
        try:
            with open(list_path, encoding="utf-8") as f:
                list_items = (json.load(f).get("P1_list_pagination") or {}).get("list_items") or []
        except (OSError, ValueError):
            say("⚠️ 讀不到清單報告，略過與清單的比對")
    known_ids = [i["id"] for i in list_items]
    try:
        gmail_addr = get_secret("gmail-address")
        gmail_pw = get_secret("gmail-app-password")
    except keychain_secrets.SecretNotFound as e:
        say("無法開始：%s" % e)
        return 1
    try:
        facts = (mail_prober or probe_mail)(
            gmail_addr, gmail_pw, days=args.mail_days, max_messages=60, known_ids=known_ids)
    except ProbeError as e:
        say("信箱檢視失敗：%s" % e)
        return 1
    report = {"generated_at": started.isoformat(), "mail": facts,
              "list_report_used": bool(list_items)}
    if list_items:
        report["comparison"] = compare_mail_vs_list(
            facts.get("messages") or [], list_items, started.date(), args.mail_days)
    try:
        sanitize(report, [gmail_addr, gmail_pw])
        path = _write_report(args.data_dir, report, started, prefix="mail")
    except ProbeError as e:
        say("檢視完成但報告未寫出：%s" % e)
        return 1
    say("信箱檢視報告：%s" % path)
    say("信箱檢視完成。")
    return 0


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
