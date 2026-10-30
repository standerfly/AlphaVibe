#!/usr/bin/env python3
"""國泰「交易明細表」與資料庫成交逐筆比對——唯讀工具（specs/009 FR-015、US3）。

用法（contracts/cli.md §2）：
    python3 statement_reconcile.py [PDF] [--folder DIR] [--data-dir DIR] [--json]

- PDF 省略＝`--folder`（預設 `/Users/stander/STND-對帳單`）中修改時間最新的 `.pdf`。
- 密碼從鑰匙圈 `pdf-password` 讀取；解密內容只在記憶體中。
- 資料庫以 SQLite 唯讀模式（`mode=ro`）開啟，**不寫入任何資料**；不修改、不刪除資料夾內的檔案。
- 解析沿用 `trade_ledger_parser.parse_trade_ledger_text()`；委託書號依 `normalize_order_ref()` 比對。

比對範圍：交易明細表第一筆～最後一筆成交日之間的資料庫成交。輸出三類：
  資料庫重複——同一委託書號（正規化後）多筆，或期間內資料庫有、明細表沒有的成交；
  資料庫缺漏——明細表有、資料庫沒有；
  數值不一致——同一委託書號兩邊的日期、代號、買賣別、股數或價格不同。
結束碼：0＝比對完成（不論有無差異）；2＝PDF 打不開或格式無法辨識。僅標準庫，Python 3.9 相容。
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

import keychain_secrets
import statement_pdf
import trade_ledger_parser
from order_ref import normalize_order_ref
from stock_alias_resolver import normalize_name

DEFAULT_FOLDER = "/Users/stander/STND-對帳單"
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_FIELDS = ("date", "code", "action", "shares", "price")


class ReconcileError(Exception):
    pass


def latest_pdf(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*")) if f.lower().endswith(".pdf")]
    if not files:
        raise ReconcileError("資料夾裡沒有 PDF：%s" % folder)
    return max(files, key=os.path.getmtime)


def _open_ro(data_dir):
    db_path = os.path.join(data_dir, "alphavibe.db")
    if not os.path.exists(db_path):
        raise ReconcileError("找不到資料庫：%s" % db_path)
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _name_to_code(conn):
    mapping = {}
    for r in conn.execute("SELECT name, code FROM trade_ledger WHERE name IS NOT NULL"):
        mapping[normalize_name(r["name"])] = r["code"]
    try:
        for r in conn.execute("SELECT name, code FROM stock_aliases"):
            mapping[normalize_name(r["name"])] = r["code"]
    except sqlite3.OperationalError:
        pass
    return mapping


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def _brief(row):
    return {k: row.get(k) for k in ("id", "date", "code", "name", "action", "shares", "price",
                                    "order_ref") if k in row}


def reconcile(statement_trades, conn):
    """回傳 ReconcileReport dict（data-model.md）。"""
    if not statement_trades:
        raise ReconcileError("交易明細表沒有可辨識的成交")
    names = _name_to_code(conn)
    stmt = []
    for t in statement_trades:
        s = dict(t, code=names.get(normalize_name(t.get("name"))),
                 key=normalize_order_ref(t.get("order_ref")))
        stmt.append(s)
    start = min(t["date"] for t in stmt)
    end = max(t["date"] for t in stmt)

    all_rows = [dict(r) for r in conn.execute("SELECT * FROM trade_ledger ORDER BY date, id")]
    by_key = {}
    for r in all_rows:
        k = normalize_order_ref(r.get("order_ref"))
        if k:
            by_key.setdefault(k, []).append(r)
    period_rows = [r for r in all_rows if start <= r["date"] <= end]

    duplicates, missing, mismatched = [], [], []
    for k, rows in sorted(by_key.items()):
        if len(rows) > 1 and any(start <= r["date"] <= end for r in rows):
            duplicates.append({"normalized_ref": k, "reason": "同一委託書號多筆",
                               "rows": [_brief(r) for r in rows]})

    matched_ids = set()
    unmatched_stmt = []
    for s in stmt:
        rows = by_key.get(s["key"]) if s["key"] else None
        if not rows:
            unmatched_stmt.append(s)
            continue
        matched_ids.update(r["id"] for r in rows)
        db = rows[0]
        for f in _FIELDS:
            sv, dv = s.get(f), db.get(f)
            if f == "code" and sv is None:
                continue  # 名稱對不到代號時不比代號
            if not _same(sv, dv):
                mismatched.append({"order_ref": s.get("order_ref"), "field": f,
                                   "statement_value": sv, "db_value": dv})

    # 資料庫沒有委託書號的舊列：以欄位完全相同配對，配到就不算缺漏
    refless = [r for r in period_rows if not normalize_order_ref(r.get("order_ref"))]
    for s in unmatched_stmt:
        hit = next((r for r in refless if r["id"] not in matched_ids
                    and all(f == "code" and s.get(f) is None or _same(s.get(f), r.get(f))
                            for f in _FIELDS)), None)
        if hit:
            matched_ids.add(hit["id"])
            continue
        missing.append({k: s.get(k) for k in ("date", "code", "name", "action", "shares",
                                              "price", "order_ref")})

    for r in period_rows:
        if r["id"] not in matched_ids:
            duplicates.append({"normalized_ref": normalize_order_ref(r.get("order_ref")),
                               "reason": "交易明細表沒有這筆", "rows": [_brief(r)]})

    return {"period": [start, end], "statement_trades_count": len(stmt),
            "db_trades_count": len(period_rows), "duplicates_in_db": duplicates,
            "missing_in_db": missing, "mismatched": mismatched}


def format_report(rep, pdf_name):
    lines = ["交易明細表：%s" % pdf_name,
             "期間 %s ～ %s：明細表 %d 筆、資料庫 %d 筆"
             % (rep["period"][0], rep["period"][1], rep["statement_trades_count"],
                rep["db_trades_count"])]
    if not (rep["duplicates_in_db"] or rep["missing_in_db"] or rep["mismatched"]):
        lines.append("✅ 全部一致")
        return "\n".join(lines)
    if rep["duplicates_in_db"]:
        lines.append("\n【資料庫重複】%d 組" % len(rep["duplicates_in_db"]))
        for d in rep["duplicates_in_db"]:
            lines.append("- %s（%s）：%s" % (d["normalized_ref"] or "無委託書號", d["reason"],
                                           "；".join(_row_text(r) for r in d["rows"])))
    if rep["missing_in_db"]:
        lines.append("\n【資料庫缺漏】%d 筆" % len(rep["missing_in_db"]))
        for m in rep["missing_in_db"]:
            lines.append("- " + _row_text(m))
    if rep["mismatched"]:
        lines.append("\n【數值不一致】%d 項" % len(rep["mismatched"]))
        for m in rep["mismatched"]:
            lines.append("- %s %s：明細表 %s／資料庫 %s" % (
                m["order_ref"], m["field"], m["statement_value"], m["db_value"]))
    return "\n".join(lines)


def _row_text(r):
    return "%s %s %s %s %s股 @%s %s" % (
        ("#%s" % r["id"]) if r.get("id") else "", r.get("date"), r.get("code") or r.get("name"),
        r.get("action"), r.get("shares"), r.get("price"), r.get("order_ref") or "")


def main(argv=None, get_secret=keychain_secrets.get_secret, extract=None):
    ap = argparse.ArgumentParser(description="交易明細表與資料庫唯讀比對")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--folder", default=DEFAULT_FOLDER)
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    extract = extract or statement_pdf.extract_text
    try:
        pdf = args.pdf or latest_pdf(args.folder)
        text = extract(pdf, get_secret("pdf-password"))
        parsed = trade_ledger_parser.parse_trade_ledger_text(text)
        conn = _open_ro(os.path.abspath(args.data_dir))
        try:
            rep = reconcile(parsed["trades"], conn)
        finally:
            conn.close()
    except (ReconcileError, statement_pdf.PdfError, keychain_secrets.SecretNotFound) as e:
        print("無法比對：%s" % e, file=sys.stderr)
        return 2
    rep["unparsed_lines"] = len(parsed.get("unparsed_lines") or [])
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(format_report(rep, os.path.basename(pdf)))
        if rep["unparsed_lines"]:
            print("\n（另有 %d 行無法解析，請人工確認）" % rep["unparsed_lines"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
