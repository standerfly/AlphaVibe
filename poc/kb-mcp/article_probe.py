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
import imaplib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

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


class ProbeError(Exception):
    """探查無法繼續。訊息不得含帳密、cookie、全文。"""


# ---------------------------------------------------------------- Node 子行程

def _node_binary():
    return shutil.which("node") or "/opt/homebrew/bin/node"


def default_scraper_runner(payload, verbose=False):
    """啟動 Node scraper：帳密只寫進 stdin；stdout 逐行 JSON。回傳 JSON 物件清單。"""
    node = _node_binary()
    if not os.path.exists(node):
        raise ProbeError("找不到 node，無法執行探查")
    try:
        proc = subprocess.Popen(
            [node, SCRAPER_JS],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None if verbose else subprocess.DEVNULL)
    except OSError:
        raise ProbeError("無法啟動 node")
    objs = []
    try:
        proc.stdin.write(json.dumps(payload).encode("utf-8"))
        proc.stdin.close()
        deadline = time.time() + SCRAPER_DEADLINE_SEC
        for raw in proc.stdout:
            try:
                objs.append(json.loads(raw.decode("utf-8").strip() or "{}"))
            except ValueError:
                continue
            if time.time() > deadline:
                proc.kill()
                break
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
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


def classify_mail_links(html_text):
    """只回分類與主機名，不回完整網址（追蹤網址可能帶個人識別碼）。"""
    parser = _HrefParser()
    parser.feed(html_text or "")
    direct, same_site, external = 0, 0, 0
    hosts = []
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
    return {"direct_article": direct, "same_site_other": same_site,
            "external_redirect": external, "external_hosts": hosts}


def probe_mail(address, app_password, imap_factory=None, days=30, max_messages=2):
    """唯讀檢視最近幾封定錨通知信的連結型態（BODY.PEEK，不標已讀、不跟隨任何連結）。"""
    factory = imap_factory or statement_mailbox._default_factory
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
                 "external_redirect": 0, "external_hosts": []}
        for uid in uids[-max_messages:]:
            raw = statement_mailbox._fetch_parts(conn, uid, "BODY.PEEK[]")
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            facts["messages_examined"] += 1
            facts["sender_matches"] = MAIL_SENDER in str(msg.get("From") or "").lower()
            if not facts["sender_matches"]:
                continue
            body = msg.get_body(preferencelist=("html", "plain"))
            if body is None:
                continue
            if body.get_content_type() == "text/html":
                facts["has_html_part"] = True
            cls = classify_mail_links(body.get_content())
            for k in ("direct_article", "same_site_other", "external_redirect"):
                facts[k] += cls[k]
            for h in cls["external_hosts"]:
                if h not in facts["external_hosts"] and len(facts["external_hosts"]) < 5:
                    facts["external_hosts"].append(h)
        return facts
    except (imaplib.IMAP4.error, OSError) as e:
        raise ProbeError("Gmail 讀取失敗：%s" % type(e).__name__)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


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
    items = list(p1.get("items") or []) + list(p2.get("items") or [])
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
        },
        "P2_logout": {
            "mechanism_found": mech.get("found"),
            "candidates": mech.get("candidates"),
            "clicked": logout.get("clicked"),
            "server_side_verified": logout.get("verified"),
            "context_close_is_not_logout": True,
        },
        "P2a_P2b_manual": {
            "login_at": summary.get("login_at"),
            "logout_at": summary.get("logout_at"),
            "need_po_observation": [
                "P2a：探查期間請 PO 手機與電腦保持登入，探查結束後確認是否被登出",
                "P2b：登出後立刻用第三個瀏覽器登入，確認是否因名額未釋放而被拒",
            ],
        },
        "P3_read_state": {
            "changed_after_open": read_state.get("changed"),
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
        "P8_half_year": estimate_half_year(items, today),
        "P8_id_monotonic_with_date": check_id_monotonic(items, today),
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


def _write_report(data_dir, report, now):
    out_dir = os.path.join(os.path.abspath(data_dir), PROBE_DIRNAME)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    path = os.path.join(out_dir, "probe-%s.json" % now.strftime("%Y%m%d-%H%M%S"))
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
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--skip-mail", action="store_true",
                    help="略過 Gmail 通知信連結檢查（P4）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    def say(msg):
        out.write(msg + "\n")

    if not args.confirm_po_present:
        say("拒絕執行：探查會用 PO 的會員帳號登入定錨網站，必須 PO 在場並加上 "
            "--confirm-po-present。未讀取任何憑證、未連線。")
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
        say("⚠️ 探查異常結束（沒有收到 summary）。若曾登入成功，請立刻手動登出定錨網站。")
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
        say("⚠️ 停止：找不到伺服器端登出機制，不得進入實作；請 PO 立刻手動登出並回報。")
        ok = False
    elif summary.get("stage_error"):
        say("⚠️ 探查中止：%s" % summary.get("stage_error"))
        ok = False
    if summary.get("logged_in") and not (summary.get("logged_out")
                                         and summary.get("logout_verified")):
        say("⚠️ 登出未驗證：請 PO 立刻手動登出定錨網站（避免佔用裝置名額）。")
        ok = False
    if not summary.get("logged_in"):
        ok = False
    say("探查%s。" % ("完成" if ok else "未完全成功"))
    return 0 if ok else 1


def main(argv=None):
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
