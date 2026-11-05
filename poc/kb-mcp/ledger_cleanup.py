#!/usr/bin/env python3
"""以國泰「交易明細表」清理 trade_ledger 的一次性工具（009 上線前整年度清理）。

PO 2026-11-05 確認的修正項目：
  1. 刪除重複：同一委託書號（正規化後）多筆時，只留與明細表寫法完全相同的那筆（新格式
     `k-XXXX-00`）；其餘刪除（含舊格式把一筆成交拆成兩筆的情況）。沒有委託書號、但與
     某筆有委託書號的成交欄位完全相同的列（例：對話手動記錄），也視為重複刪除。
  2. 補登缺漏：明細表有、資料庫沒有的成交照明細表寫入（委託書號保留明細表寫法，之後的
     日對帳單匯入會正規化比對、自動跳過）。名稱對不到代號時須用 --alias 指定，否則拒絕寫入。
  3. 重算加碼次數：每檔買進依 (日期, id) 由 1 起重新編號，賣出為 NULL。
  「資料庫多出」中無法判定為重複的列只列出、不刪。

用法：
    python3 ledger_cleanup.py PDF --data-dir DIR [--alias 廣達=2382 ...] [--json]
    python3 ledger_cleanup.py PDF --data-dir DIR [--alias ...] --apply --confirm <計畫代碼>

不加 --apply 只產生修正計畫（資料庫以唯讀模式開啟）。--apply 必須帶上試跑時印出的計畫代碼：
資料或參數只要有任何不同，代碼就不同、拒絕執行，確保寫入的就是 PO 看過的那份清單。
寫入前先以 SQLite backup API 備份到 --backup-dir，所有修正在單一交易內完成，失敗整個還原。
結束碼：0＝完成；2＝PDF 打不開／格式無法辨識／計畫無法執行（例如代號未知、計畫代碼不符）。
僅標準庫，Python 3.9 相容。
"""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys

import keychain_secrets
import statement_pdf
import statement_reconcile
import trade_ledger_parser
from order_ref import normalize_order_ref

DEFAULT_BACKUP_DIR = os.path.expanduser("~/AlphaVibe-backups/cleanup")
_FIELDS = ("code", "date", "action", "shares", "price")


class CleanupError(Exception):
    pass


def _key(row):
    return tuple(float(row[f]) if f in ("shares", "price") else row[f] for f in _FIELDS)


def build_plan(statement_trades, conn, aliases=None, source_name=""):
    """回傳修正計畫 dict（不寫入）。"""
    aliases = aliases or {}
    rep = statement_reconcile.reconcile(statement_trades, conn)
    stmt_raw = {}
    for t in statement_trades:
        k = normalize_order_ref(t.get("order_ref"))
        if k:
            stmt_raw[k] = (t.get("order_ref") or "").strip()

    deletes, notes = [], []
    for group in rep["duplicates_in_db"]:
        rows = group["rows"]
        raw = stmt_raw.get(group["normalized_ref"])
        keep = next((r for r in rows if (r.get("order_ref") or "").strip() == raw), None)
        if keep is None:
            keep = min(rows, key=lambda r: r["id"])
            notes.append("委託書號 %s 沒有與明細表寫法相同的列，保留 id 最小的 #%s"
                         % (group["normalized_ref"], keep["id"]))
        deletes += [{"id": r["id"], "reason": "重複（保留 #%s）" % keep["id"], "row": r}
                    for r in rows if r["id"] != keep["id"]]

    deleted_ids = {d["id"] for d in deletes}
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM trade_ledger ORDER BY date, id")]
    with_ref = {}
    for r in all_rows:
        if r["id"] not in deleted_ids and normalize_order_ref(r.get("order_ref")):
            with_ref.setdefault(_key(r), []).append(r["id"])
    extra_kept = []
    for r in rep["extra_in_db"]:
        twins = with_ref.get(_key(r))
        if not normalize_order_ref(r.get("order_ref")) and twins:
            deletes.append({"id": r["id"], "reason": "無委託書號、與 #%s 完全相同" % twins[0],
                            "row": r})
        else:
            extra_kept.append(r)

    inserts, unresolved = [], []
    for m in rep["missing_in_db"]:
        code = m.get("code") or aliases.get(m.get("name"))
        if not code:
            unresolved.append(m.get("name"))
            continue
        inserts.append({"code": code, "name": m.get("name"), "action": m["action"],
                        "shares": m["shares"], "price": m["price"], "date": m["date"],
                        "order_ref": m.get("order_ref"),
                        "source_ref": "交易明細表補登 %s" % source_name})
    inserts.sort(key=lambda t: t["date"])

    # 加碼次數：以「刪除、補登之後」的完整流水重新編號
    deleted_ids = {d["id"] for d in deletes}
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
            "seq_updates": seq_updates, "extra_kept": extra_kept,
            "unresolved_names": sorted(set(unresolved)), "mismatched": rep["mismatched"],
            "notes": notes}
    plan["plan_code"] = plan_code(plan)
    return plan


def plan_code(plan):
    payload = json.dumps({"d": sorted(d["id"] for d in plan["deletes"]),
                          "i": plan["inserts"],
                          "s": sorted((u["id"], u["to"] if u["to"] is not None else -1)
                                      for u in plan["seq_updates"])},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def apply_plan(db_path, plan, backup_dir):
    """備份後在單一交易內套用；回傳備份檔路徑。"""
    if plan["unresolved_names"]:
        raise CleanupError("有名稱對不到代號，請用 --alias 指定：%s"
                           % "、".join(plan["unresolved_names"]))
    os.makedirs(backup_dir, exist_ok=True)
    backup = os.path.join(backup_dir, "alphavibe-before-ledger-cleanup-%s.db"
                          % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup)
        with dst:
            src.backup(dst)
        dst.close()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            src.execute("BEGIN")
            src.executemany("DELETE FROM trade_ledger WHERE id=?",
                            [(d["id"],) for d in plan["deletes"]])
            for u in plan["seq_updates"]:
                src.execute("UPDATE trade_ledger SET add_sequence=? WHERE id=?",
                            (u["to"], u["id"]))
            for t in plan["inserts"]:
                src.execute(
                    "INSERT INTO trade_ledger (code, name, action, add_sequence, shares, price,"
                    " date, source_ref, order_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (t["code"], t["name"], t["action"], t["add_sequence"], t["shares"],
                     t["price"], t["date"], t["source_ref"], t["order_ref"], now))
            src.commit()
        except Exception:
            src.rollback()
            raise
    finally:
        src.close()
    return backup


def format_plan(plan, pdf_name):
    lines = ["交易明細表：%s（%s ～ %s）" % (pdf_name, plan["period"][0], plan["period"][1]),
             "刪除 %d 筆、補登 %d 筆、加碼次數更新 %d 筆"
             % (len(plan["deletes"]), len(plan["inserts"]), len(plan["seq_updates"]))]
    if plan["deletes"]:
        lines.append("\n【刪除】")
        lines += ["- #%s %s %s %s %s股 @%s %s（%s）" % (
            d["id"], d["row"].get("date"), d["row"].get("code"), d["row"].get("action"),
            d["row"].get("shares"), d["row"].get("price"), d["row"].get("order_ref") or "",
            d["reason"]) for d in plan["deletes"]]
    if plan["inserts"]:
        lines.append("\n【補登】")
        lines += ["- %s %s %s %s股 @%s %s（加碼次數 %s）" % (
            t["date"], t["code"], t["action"], t["shares"], t["price"], t["order_ref"] or "",
            t["add_sequence"] if t["add_sequence"] is not None else "—")
            for t in plan["inserts"]]
    if plan["unresolved_names"]:
        lines.append("\n⚠️ 名稱對不到代號（請加 --alias 名稱=代號）：%s"
                     % "、".join(plan["unresolved_names"]))
    if plan["extra_kept"]:
        lines.append("\n【資料庫多出、無法判定為重複，不處理，請逐筆確認】")
        lines += ["- #%s %s %s %s %s股 @%s" % (r["id"], r["date"], r["code"], r["action"],
                                              r["shares"], r["price"])
                  for r in plan["extra_kept"]]
    if plan["mismatched"]:
        lines.append("\n⚠️ 數值不一致 %d 項（本工具不處理）" % len(plan["mismatched"]))
    lines += ["- 註：%s" % n for n in plan["notes"]]
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
    try:
        aliases = _parse_aliases(args.alias)
        parsed = trade_ledger_parser.parse_trade_ledger_text(
            extract(args.pdf, get_secret("pdf-password")))
        if parsed.get("unparsed_lines"):
            raise CleanupError("交易明細表有 %d 行成交無法辨識" % len(parsed["unparsed_lines"]))
        conn = statement_reconcile._open_ro(data_dir)
        try:
            plan = build_plan(parsed["trades"], conn, aliases, os.path.basename(args.pdf))
        finally:
            conn.close()
        if args.apply:
            if args.confirm != plan["plan_code"]:
                raise CleanupError("計畫代碼不符（目前為 %s）：資料或參數與試跑時不同，請重新試跑確認"
                                   % plan["plan_code"])
            backup = apply_plan(os.path.join(data_dir, "alphavibe.db"), plan, args.backup_dir)
            print("已套用：刪除 %d 筆、補登 %d 筆、加碼次數更新 %d 筆。備份：%s"
                  % (len(plan["deletes"]), len(plan["inserts"]), len(plan["seq_updates"]),
                     backup))
            return 0
    except (CleanupError, statement_reconcile.ReconcileError, statement_pdf.PdfError,
            keychain_secrets.SecretNotFound) as e:
        print("無法執行：%s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
    else:
        print(format_plan(plan, os.path.basename(args.pdf)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
