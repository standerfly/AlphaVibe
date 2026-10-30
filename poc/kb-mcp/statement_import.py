#!/usr/bin/env python3
"""國泰台股日對帳單 Email 自動匯入（specs/009-cathay-tw-statement-import）。

流程：鑰匙圈取密碼 → Gmail 唯讀取信（statement_mailbox）→ qpdf/pdftotext 解密擷取
（statement_pdf）→ 解析（cathay_statement_parser）→ 名稱對代號、委託書號正規化防重複、
平均成本 → 單一交易寫入成交與庫存（KBStore.apply_statement_import）→ Telegram 摘要。

用法（contracts/cli.md §1）：
    python3 statement_import.py [--data-dir DIR] [--days N] [--dry-run]
    python3 statement_import.py --rerun MESSAGE_ID_OR_DATE [--data-dir DIR]
    python3 statement_import.py --from-file PDF [--data-dir DIR] [--dry-run]

結束碼：0＝完成（含部分完成與個別對帳單失敗，已記錄並通知）；1＝信箱連線或設定錯誤。
輸出與通知不含任何密碼、身分證字號、帳號。僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import json
import os
import sys
import traceback

import holdings_sync
import keychain_secrets
import notify
import stock_alias_resolver
import statement_mailbox
import statement_pdf
from cathay_statement_parser import StatementFormatError, parse_daily_statement
from kb_store import KBStore
from order_ref import normalize_order_ref

SOURCE_PREFIX = "國泰日對帳單"
PROCESSED, PARTIAL, FAILED = "processed", "partial", "failed"
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def _today():
    return datetime.date.today().isoformat()


# ---------- 單份對帳單 ----------

def make_resolver(store, data_dir, dry_run=False):
    """名稱→代號：試跑只查本機快取（不寫入、不連 FinMind），正式執行沿用
    stock_alias_resolver（查不到才整批問 FinMind，結果寫回快取）。"""
    if dry_run:
        def lookup(names):
            out = {}
            for n in names:
                alias = store.get_stock_alias(n)
                if alias.get("found"):
                    out[n] = alias["record"]["code"]
            return out
        return lookup

    def resolve(names):
        resolved, _ = stock_alias_resolver.resolve_stock_codes(
            names, store, data_dir=data_dir, alias_source="國泰日對帳單自動匯入")
        return resolved
    return resolve


def _replay_cost(ledger_rows, code):
    """以交易紀錄從零完整重播；回傳 (股數, 均價)。"""
    sim = holdings_sync.apply_trades_to_positions([], ledger_rows)
    for r in sim["rows"]:
        if r["code"] == code:
            return r["shares"], r["avg_cost"]
    return 0, None


def _resolve_avg_cost(code, stmt_shares, sim_row, base_row, bought_today, ledger_rows):
    """research R6 四層順序；回傳均價或 None。"""
    if sim_row and sim_row["shares"] == stmt_shares and sim_row["avg_cost"] is not None:
        return sim_row["avg_cost"]
    if base_row and base_row.get("avg_cost") is not None and not bought_today:
        return base_row["avg_cost"]
    shares, cost = _replay_cost(ledger_rows, code)
    if shares == stmt_shares and cost is not None:
        return cost
    return None


def process_statement(store, statement, message_id, resolver, dry_run=False):
    """處理一份已解析的對帳單；寫入（非試跑時）並回傳摘要 dict。"""
    date = statement["statement_date"]
    source_ref = "%s %s" % (SOURCE_PREFIX, date)
    holdings = statement["holdings"]
    name_to_code = {h["name"]: h["code"] for h in holdings}

    missing = [t["name"] for t in statement["trades"] if t["name"] not in name_to_code]
    resolved = resolver(sorted(set(missing))) if missing else {}

    # 防重複：比對資料庫既有成交（重跑、交易明細表已匯入過的都會跳過）。同一份對帳單內
    # 委託書號（含序號）相同的列——同委託分次成交會有不同序號，完全同號較可能是 PDF 轉文字
    # 時同一列被讀兩次——只寫第一筆，並列入通知請 PO 確認，不靜默處理。
    existing_refs = store.existing_normalized_order_refs()
    day_trades, to_write, unresolved, repeated_refs = [], [], [], []
    seen = set()
    duplicates = 0
    for t in statement["trades"]:
        code = name_to_code.get(t["name"]) or resolved.get(t["name"])
        if not code:
            unresolved.append(t["name"])
            continue
        key = normalize_order_ref(t["order_ref"])
        if key in seen:
            repeated_refs.append(t["order_ref"])
            continue
        seen.add(key)
        trade = dict(t, code=code)
        day_trades.append(trade)
        if key in existing_refs:
            duplicates += 1
            continue
        to_write.append(trade)

    # add_sequence：沿用 resolve_and_save_trade_ledger 規則（既有有序號的買進筆數＋1 起算）。
    all_entries = store.get_all_trade_entries()
    next_seq = {}
    for e in all_entries:
        if e["action"] == "買" and e["add_sequence"] is not None:
            next_seq[e["code"]] = next_seq.get(e["code"], 1) + 1
    rows_to_write = []
    for t in to_write:
        seq = None
        if t["action"] == "買":
            seq = next_seq.get(t["code"], 1)
            next_seq[t["code"]] = seq + 1
        rows_to_write.append({
            "code": t["code"], "name": t["name"], "action": t["action"],
            "shares": t["shares"], "price": t["price"], "date": date, "add_sequence": seq,
            "fee": t["fee"], "tax": t["tax"], "order_ref": t["order_ref"],
            "source_ref": source_ref})

    # FR-013：只有「已處理過的對帳單」比本份新時才不寫庫存；手動匯入交易同步出的較新快照
    # 不擋（對帳單是標準），否則晚一天補跑的對帳單會永遠無法更新庫存。
    latest = store.latest_statement_holdings_date()
    write_holdings = latest is None or date >= latest

    holdings_rows, diffs, cost_unknown = [], [], []
    if write_holdings:
        baseline = store.get_holdings_before(date)
        base_by = {r["code"]: r for r in baseline}
        sim_by = {r["code"]: r for r in
                  holdings_sync.apply_trades_to_positions(baseline, day_trades)["rows"]}
        bought = {t["code"] for t in day_trades if t["action"] == "買"}
        ledger_by = {}
        for e in all_entries + rows_to_write:
            ledger_by.setdefault(e["code"], []).append(e)
        for h in holdings:
            cost = _resolve_avg_cost(h["code"], h["shares"], sim_by.get(h["code"]),
                                     base_by.get(h["code"]), h["code"] in bought,
                                     ledger_by.get(h["code"], []))
            if cost is None and h["shares"] > 0:
                cost_unknown.append(h["code"])
            holdings_rows.append({"code": h["code"], "name": h["name"],
                                  "shares": h["shares"], "avg_cost": cost})
        if baseline:
            stmt_by = {h["code"]: h["shares"] for h in holdings}
            for code in sorted(set(stmt_by) | {c for c, r in sim_by.items() if r["shares"]}):
                expected = (sim_by.get(code) or {}).get("shares") or 0
                actual = stmt_by.get(code, 0)
                if expected != actual:
                    diffs.append({"code": code, "expected": expected, "actual": actual})

    status = PARTIAL if unresolved else PROCESSED
    detail = {"unresolved_names": unresolved, "diffs": diffs, "cost_unknown": cost_unknown,
              "repeated_refs": repeated_refs}
    import_row = {
        "message_id": message_id, "statement_date": date, "status": status,
        "trades_written": len(rows_to_write), "trades_skipped_duplicate": duplicates,
        "holdings_count": len(holdings) if write_holdings else None,
        "holdings_written": 1 if write_holdings else 0,
        "detail_json": json.dumps(detail, ensure_ascii=False), "error": None,
        "holdings_source_ref": source_ref}

    cost_alerts = []
    if not dry_run:
        store.apply_statement_import(rows_to_write, holdings_rows, date, write_holdings,
                                     import_row)
        cost_alerts = [c for c in cost_unknown if store.alert_once("cost_unknown", c)]

    return {"statement_date": date, "status": status, "written": len(rows_to_write),
            "duplicates": duplicates, "holdings_count": len(holdings),
            "holdings_written": write_holdings, "diffs": diffs,
            "cost_unknown": cost_unknown, "cost_alerts": cost_alerts,
            "unresolved": unresolved, "repeated_refs": repeated_refs,
            "trades": rows_to_write, "holdings": holdings_rows}


# ---------- 通知文字（contracts §3） ----------

def format_summary(s):
    date = s["statement_date"]
    if s["status"] == PARTIAL:
        lines = ["⚠️ %s %s 部分完成：%d 筆成交名稱對不到代號（%s），其餘已寫入"
                 % (SOURCE_PREFIX, date, len(s["unresolved"]), "、".join(s["unresolved"]))]
    else:
        lines = ["📒 %s %s 已匯入" % (SOURCE_PREFIX, date)]
    tail = ("庫存 %d 檔" % s["holdings_count"] if s["holdings_written"]
            else "已有較新的庫存，本份不更新庫存")
    lines.append("成交 %d 筆寫入（跳過重複 %d）・%s" % (s["written"], s["duplicates"], tail))
    if s["diffs"]:
        lines.append("⚠️ 庫存與買賣紀錄推算不同：" + "、".join(
            "%s 推算 %s／對帳單 %s" % (d["code"], _fmt_shares(d["expected"]),
                                       _fmt_shares(d["actual"])) for d in s["diffs"]))
    if s["cost_alerts"]:
        lines.append("⚠️ 平均成本算不出來：" + "、".join(s["cost_alerts"]))
    if s.get("repeated_refs"):
        lines.append("⚠️ 對帳單內委託書號重複，只寫入第一筆（請用比對工具確認）："
                     + "、".join(s["repeated_refs"]))
    return "\n".join(lines)


def format_failure(date, reason):
    return "❌ %s %s 匯入失敗：%s，未寫入任何資料" % (SOURCE_PREFIX, date or "（日期不明）", reason)


def _fmt_shares(v):
    return str(int(v)) if float(v).is_integer() else str(v)


# ---------- 整次執行 ----------

class _Run:
    def __init__(self, store, dry_run, today):
        self.store, self.dry_run, self.today = store, dry_run, today
        self.messages = []

    def notify_once(self, key, text):
        """錯誤／部分完成類通知：同一 key 一天一次（statement_alerts）。"""
        if self.dry_run or self.store.alert_once("error", "%s|%s" % (self.today, key)):
            self.messages.append(text)


def _process_item(run, item, pdf_password, resolver, cache_resolver):
    store, msg_id = run.store, item["message_id"]
    date = item.get("date_hint")
    previous = store.statement_import_status(msg_id)
    if previous and previous["status"] == PARTIAL and \
            (previous["processed_at"] or "")[:10] == run.today:
        # 部分完成的自動重試一天只問一次 FinMind（匿名額度全域共用）；之後只查本機快取，
        # PO 手動補上的名稱對應（stock_aliases）照樣生效。
        resolver = cache_resolver

    def fail(category, reason):
        if not run.dry_run:
            store.record_statement_failure({
                "message_id": msg_id, "statement_date": date or run.today,
                "status": FAILED, "error": reason})
        run.notify_once("%s|%s" % (msg_id, category), format_failure(date, reason))
        return "%s %s 失敗：%s" % (SOURCE_PREFIX, date or "?", reason)

    pdf = item.get("pdf_path") or item.get("pdf_bytes")
    if not pdf:
        return fail("no_pdf", "信件沒有 PDF 附件")
    try:
        text = statement_pdf.extract_text(pdf, pdf_password)
    except statement_pdf.PdfError as e:
        return fail("pdf", str(e))
    try:
        statement = parse_daily_statement(text, fallback_date=date)
    except StatementFormatError as e:
        return fail("format", "PDF 格式無法辨識（可能改版）：%s" % e)
    date = statement["statement_date"]
    try:
        s = process_statement(store, statement, msg_id, resolver, dry_run=run.dry_run)
    except Exception as e:  # apply_statement_import 已 rollback
        traceback.print_exc(file=sys.stderr)
        return fail("write", "寫入失敗（%s）" % type(e).__name__)
    if s["status"] == PARTIAL:
        run.notify_once("%s|partial" % msg_id, format_summary(s))
    else:
        run.messages.append(format_summary(s))
    if run.dry_run:
        print(json.dumps({"trades": s["trades"], "holdings": s["holdings"]},
                         ensure_ascii=False, indent=1))
    return format_summary(s).replace("\n", "｜")


def _select_items(store, items, rerun):
    if rerun:
        wanted = {r["message_id"] for r in store.find_statement_imports_by_date(rerun)}
        return [i for i in items
                if i["message_id"] == rerun or i["message_id"] in wanted
                or i.get("date_hint") == rerun]
    selected = []
    for i in items:
        status = store.statement_import_status(i["message_id"])
        if not status or status["status"] != PROCESSED:
            selected.append(i)
    return selected


def run(data_dir, days=14, dry_run=False, rerun=None, from_file=None,
        get_secret=keychain_secrets.get_secret, fetch=statement_mailbox.fetch_statements,
        notifier=notify.send_telegram, resolver=None, today=None):
    """回傳結束碼。"""
    store = KBStore(data_dir)
    r = _Run(store, dry_run, today or _today())
    run_id = None if dry_run else store.start_import_run()
    outcome, error, found = "ok", None, 0
    try:
        try:
            pdf_password = get_secret("pdf-password")
            if from_file:
                items = [{"message_id": "file:%s" % os.path.abspath(from_file),
                          "date_hint": None, "pdf_path": from_file}]
            else:
                if rerun and rerun[:4].isdigit() and "-" in rerun:
                    try:
                        age = (datetime.date.fromisoformat(r.today)
                               - datetime.date.fromisoformat(rerun)).days
                        days = max(days, age + 3)
                    except ValueError:
                        pass
                items = fetch(get_secret("gmail-address"), get_secret("gmail-app-password"),
                              days)
        except (keychain_secrets.SecretNotFound, statement_mailbox.MailboxError) as e:
            outcome, error = "mailbox_error", str(e)
            r.notify_once("mailbox|%s" % type(e).__name__,
                          "❌ %s：無法讀取信箱或密碼——%s" % (SOURCE_PREFIX, e))
            print(error, file=sys.stderr)
            return 1
        items = items if from_file else _select_items(store, items, rerun)
        found = len(items)
        cache_resolver = make_resolver(store, data_dir, dry_run=True)
        resolver = resolver or make_resolver(store, data_dir, dry_run)
        for item in items:
            print(_process_item(r, item, pdf_password, resolver, cache_resolver))
        if not items:
            print("沒有需要處理的新對帳單")
        return 0
    except Exception as e:
        outcome, error = "error", "%s: %s" % (type(e).__name__, e)
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        notify_failed = False
        if r.messages and not dry_run:
            sent, errors = notifier("\n\n".join(r.messages))
            notify_failed = bool(errors) or not sent
        elif r.messages:
            print("\n—— 試跑：以下通知不會送出 ——\n" + "\n\n".join(r.messages))
        if run_id is not None:
            store.finish_import_run(run_id, outcome, statements_found=found,
                                    notify_failed=notify_failed, error=error)
        store.conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="國泰台股日對帳單 Email 自動匯入")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--rerun", metavar="MESSAGE_ID_OR_DATE")
    g.add_argument("--from-file", metavar="PDF")
    args = ap.parse_args(argv)
    return run(os.path.abspath(args.data_dir), days=args.days, dry_run=args.dry_run,
               rerun=args.rerun, from_file=args.from_file)


if __name__ == "__main__":
    sys.exit(main())
