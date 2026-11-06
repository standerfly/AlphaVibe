#!/usr/bin/env python3
"""以國泰「交易明細表」清理 trade_ledger 的一次性工具（009 上線前整年度清理）。

PO 2026-11-05 確認的修正項目：
  1. 刪除重複：同一委託書號（正規化後）多筆時，只留與明細表寫法完全相同的那筆（新格式
     `k-XXXX-00`），其餘刪除（含舊格式把一筆成交拆成兩筆的情況）。沒有委託書號、但與某筆
     有委託書號的成交欄位完全相同的列（例：對話手動記錄），也視為重複刪除。
  2. 補登缺漏：明細表有、資料庫沒有的成交照明細表寫入（委託書號保留明細表寫法，之後的
     日對帳單匯入會正規化比對、自動跳過）。
  3. 重算加碼次數：每檔買進依 (日期, id) 由 1 起重新編號，賣出為 NULL。

**寧可不刪也不誤刪**（2026-11-05 獨立驗收後）：下列重複群組整組不處理、列入「待確認」：
  - 明細表上這個委託書號出現 0 次或 2 次以上；
  - 群組裡沒有、或有多筆與明細表寫法完全相同的列；
  - 保留列的代號／日期／買賣／股數／價格與明細表不符；
  - 群組內各列的代號、日期或買賣別不一致（委託書號可能每日重編，跨日撞號）。
明細表任何一筆名稱對不到代號（含 --alias）時拒絕寫入，避免靠「忽略代號的欄位配對」漏補。
「資料庫多出」中無法判定為重複的列只列出、不刪。

用法：
    python3 ledger_cleanup.py PDF --data-dir DIR [--alias 廣達=2382 ...] [--json]
    python3 ledger_cleanup.py PDF --data-dir DIR [--alias ...] --apply --confirm <計畫代碼>

不加 --apply 只產生修正計畫（資料庫以唯讀模式開啟）。--apply 時先鎖住寫入
（BEGIN IMMEDIATE），在同一個交易內重算計畫、比對 --confirm 的計畫代碼——試跑後資料或參數
只要有任何會改變計畫的差異就拒絕；接著以另一條連線備份，再套用、commit，失敗整個還原。
請避開日對帳單排程時段（20:15、23:15、07:45）執行。
結束碼：0＝完成；2＝無法執行（PDF 打不開、格式無法辨識、代號未知、計畫代碼不符、寫入或備份
失敗——資料庫皆未改動）。僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys

import keychain_secrets
import statement_pdf
import statement_reconcile
import trade_ledger_parser
from order_ref import normalize_order_ref
from stock_alias_resolver import normalize_name

DEFAULT_BACKUP_DIR = os.path.expanduser("~/AlphaVibe-backups/cleanup")
_FIELDS = ("code", "date", "action", "shares", "price")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CleanupError(Exception):
    pass


def _key(row):
    return tuple(float(row[f]) if f in ("shares", "price") else row[f] for f in _FIELDS)


def _same_fields(a, b):
    return _key(a) == _key(b)


def build_plan(statement_trades, conn, aliases=None, source_name=""):
    """回傳修正計畫 dict（不寫入）。conn 需設 row_factory=sqlite3.Row。"""
    aliases = aliases or {}
    names = statement_reconcile._name_to_code(conn)
    trades, unresolved = [], []
    for t in statement_trades:
        code = aliases.get(t.get("name")) or names.get(normalize_name(t.get("name")))
        if not code:
            unresolved.append(t.get("name"))
        trades.append(dict(t, code=code))

    all_rows = [dict(r) for r in conn.execute("SELECT * FROM trade_ledger ORDER BY date, id")]
    bad_dates = [r["id"] for r in all_rows if not _DATE_RE.match(str(r["date"] or ""))]
    if bad_dates:
        raise CleanupError("資料庫有日期格式不是 YYYY-MM-DD 的成交（id %s），加碼次數排序會錯"
                           % ", ".join(map(str, bad_dates[:10])))

    rep = statement_reconcile.reconcile(trades, conn)
    stmt_by_key = {}
    for t in trades:
        k = normalize_order_ref(t.get("order_ref"))
        if k:
            stmt_by_key.setdefault(k, []).append(t)

    deletes, review = [], []
    for group in rep["duplicates_in_db"]:
        rows, key = group["rows"], group["normalized_ref"]
        st = stmt_by_key.get(key, [])
        reason = None
        if len(st) != 1:
            reason = "明細表上這個委託書號出現 %d 次" % len(st)
        else:
            raw = (st[0].get("order_ref") or "").strip()
            keeps = [r for r in rows if (r.get("order_ref") or "").strip() == raw]
            if len(keeps) != 1:
                reason = "有 %d 筆與明細表寫法（%s）相同的列" % (len(keeps), raw)
            elif not _same_fields(keeps[0], st[0]):
                reason = "與明細表寫法相同的那筆，數值與明細表不符"
            elif any((r["code"], r["date"], r["action"]) !=
                     (keeps[0]["code"], keeps[0]["date"], keeps[0]["action"]) for r in rows):
                reason = "同號但股票、日期或買賣別不同（可能跨日撞號）"
        if reason:
            review.append({"normalized_ref": key, "reason": reason, "rows": rows})
            continue
        keep = keeps[0]
        deletes += [{"id": r["id"], "reason": "重複（保留 #%s）" % keep["id"], "row": r}
                    for r in rows if r["id"] != keep["id"]]

    deleted_ids = {d["id"] for d in deletes}
    with_ref = {}
    for r in all_rows:
        if r["id"] not in deleted_ids and normalize_order_ref(r.get("order_ref")):
            with_ref.setdefault(_key(r), []).append(r["id"])
    extra_kept = []
    for r in rep["extra_in_db"]:
        if r["id"] in deleted_ids:
            continue
        twins = with_ref.get(_key(r))
        if not normalize_order_ref(r.get("order_ref")) and twins:
            deletes.append({"id": r["id"], "reason": "無委託書號、與 #%s 完全相同" % twins[0],
                            "row": r})
            deleted_ids.add(r["id"])
        else:
            extra_kept.append(r)

    inserts = [{"code": m["code"], "name": m.get("name"), "action": m["action"],
                "shares": m["shares"], "price": m["price"], "date": m["date"],
                "order_ref": m.get("order_ref"),
                "source_ref": "交易明細表補登 %s" % source_name}
               for m in rep["missing_in_db"] if m.get("code")]
    inserts.sort(key=lambda t: t["date"])

    # 加碼次數：以「刪除、補登之後」的完整流水重新編號
    future = [r for r in all_rows if r["id"] not in deleted_ids]
    future += [dict(t, id=None, _new=i) for i, t in enumerate(inserts)]
    future.sort(key=lambda r: (r["date"], r["id"] is None, r["id"] or 0, r.get("_new", 0)))
    seq_updates, counter = [], {}
    for r in future:
        if r["action"] == "買":
            counter[r["code"]] = counter.get(r["code"], 0) + 1
            want = counter[r["code"]]
        else:
            want = None
        if r["id"] is None:
            inserts[r["_new"]]["add_sequence"] = want
        elif r.get("add_sequence") != want:
            seq_updates.append({"id": r["id"], "from": r.get("add_sequence"), "to": want})

    plan = {"period": rep["period"], "deletes": deletes, "inserts": inserts,
            "seq_updates": seq_updates, "review": review, "extra_kept": extra_kept,
            "unresolved_names": sorted(set(n for n in unresolved if n)),
            "mismatched": rep["mismatched"]}
    plan["plan_code"] = plan_code(plan)
    return plan


def plan_code(plan):
    payload = json.dumps({"d": sorted([d["id"], _key(d["row"])] for d in plan["deletes"]),
                          "i": plan["inserts"],
                          "s": sorted((u["id"], u["to"] if u["to"] is not None else -1)
                                      for u in plan["seq_updates"]),
                          "u": plan["unresolved_names"]},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _backup(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(backup_dir, "alphavibe-before-ledger-cleanup-%s.db" % stamp)
    if os.path.exists(path):
        raise CleanupError("備份檔已存在：%s" % path)
    src = sqlite3.connect(db_path, timeout=30)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return path


def apply_cleanup(db_path, statement_trades, aliases, source_name, confirm, backup_dir):
    """鎖住寫入 → 交易內重算並核對計畫代碼 → 另一連線備份 → 套用 → commit。回傳 (plan, 備份路徑)。"""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            plan = build_plan(statement_trades, conn, aliases, source_name)
            if plan["unresolved_names"]:
                raise CleanupError("有名稱對不到代號，請用 --alias 指定：%s"
                                   % "、".join(plan["unresolved_names"]))
            if confirm != plan["plan_code"]:
                raise CleanupError("計畫代碼不符（目前為 %s）：資料或參數與試跑時不同，請重新試跑確認"
                                   % plan["plan_code"])
            backup = _backup(db_path, backup_dir)
            now = datetime.datetime.now().isoformat(timespec="seconds")
            conn.executemany("DELETE FROM trade_ledger WHERE id=?",
                             [(d["id"],) for d in plan["deletes"]])
            for u in plan["seq_updates"]:
                conn.execute("UPDATE trade_ledger SET add_sequence=? WHERE id=?",
                             (u["to"], u["id"]))
            for t in plan["inserts"]:
                conn.execute(
                    "INSERT INTO trade_ledger (code, name, action, add_sequence, shares, price,"
                    " date, source_ref, order_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (t["code"], t["name"], t["action"], t["add_sequence"], t["shares"],
                     t["price"], t["date"], t["source_ref"], t["order_ref"], now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return plan, backup


def _row_text(r):
    return "#%s %s %s %s %s股 @%s %s" % (r.get("id"), r.get("date"), r.get("code"),
                                         r.get("action"), r.get("shares"), r.get("price"),
                                         r.get("order_ref") or "")


def format_plan(plan, pdf_name):
    lines = ["交易明細表：%s（%s ～ %s）" % (pdf_name, plan["period"][0], plan["period"][1]),
             "刪除 %d 筆、補登 %d 筆、加碼次數更新 %d 筆；待確認 %d 組"
             % (len(plan["deletes"]), len(plan["inserts"]), len(plan["seq_updates"]),
                len(plan["review"]))]
    if plan["deletes"]:
        lines.append("\n【刪除】")
        lines += ["- %s（%s）" % (_row_text(d["row"]), d["reason"]) for d in plan["deletes"]]
    if plan["inserts"]:
        lines.append("\n【補登】")
        lines += ["- %s %s %s %s股 @%s %s（加碼次數 %s）" % (
            t["date"], t["code"], t["action"], t["shares"], t["price"], t["order_ref"] or "",
            t["add_sequence"] if t["add_sequence"] is not None else "—")
            for t in plan["inserts"]]
    if plan["review"]:
        lines.append("\n【待確認：同號但無法安全判定，整組不處理】")
        for g in plan["review"]:
            lines.append("- %s：%s" % (g["normalized_ref"], g["reason"]))
            lines += ["    %s" % _row_text(r) for r in g["rows"]]
    if plan["unresolved_names"]:
        lines.append("\n⚠️ 名稱對不到代號（請加 --alias 名稱=代號，否則無法套用）：%s"
                     % "、".join(plan["unresolved_names"]))
    if plan["extra_kept"]:
        lines.append("\n【資料庫多出、無法判定為重複，不處理，請逐筆確認】")
        lines += ["- %s" % _row_text(r) for r in plan["extra_kept"]]
    if plan["mismatched"]:
        lines.append("\n⚠️ 數值不一致 %d 項（本工具不處理）" % len(plan["mismatched"]))
    lines.append("\n計畫代碼：%s（確認無誤後加上 --apply --confirm %s 執行）"
                 % (plan["plan_code"], plan["plan_code"]))
    return "\n".join(lines)


def _parse_aliases(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise CleanupError("--alias 格式應為 名稱=代號：%s" % item)
        name, code = item.split("=", 1)
        out[name.strip()] = code.strip()
    return out


def main(argv=None, get_secret=keychain_secrets.get_secret, extract=None):
    ap = argparse.ArgumentParser(description="以交易明細表清理 trade_ledger（一次性）")
    ap.add_argument("pdf")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--alias", action="append", metavar="名稱=代號")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", metavar="計畫代碼")
    ap.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    args = ap.parse_args(argv)
    extract = extract or statement_pdf.extract_text
    data_dir = os.path.abspath(args.data_dir)
    source_name = os.path.basename(args.pdf)
    try:
        aliases = _parse_aliases(args.alias)
        parsed = trade_ledger_parser.parse_trade_ledger_text(
            extract(args.pdf, get_secret("pdf-password")))
        if parsed.get("unparsed_lines"):
            raise CleanupError("交易明細表有 %d 行成交無法辨識" % len(parsed["unparsed_lines"]))
        if not parsed["trades"]:
            raise CleanupError("交易明細表沒有可辨識的成交")
        if args.apply:
            plan, backup = apply_cleanup(os.path.join(data_dir, "alphavibe.db"),
                                         parsed["trades"], aliases, source_name,
                                         args.confirm, args.backup_dir)
            print("已套用：刪除 %d 筆、補登 %d 筆、加碼次數更新 %d 筆。備份：%s"
                  % (len(plan["deletes"]), len(plan["inserts"]), len(plan["seq_updates"]),
                     backup))
            return 0
        conn = statement_reconcile._open_ro(data_dir)
        try:
            plan = build_plan(parsed["trades"], conn, aliases, source_name)
        finally:
            conn.close()
    except (CleanupError, statement_reconcile.ReconcileError, statement_pdf.PdfError,
            keychain_secrets.SecretNotFound, sqlite3.Error, OSError) as e:
        print("無法執行（資料庫未改動）：%s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
    else:
        print(format_plan(plan, source_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
