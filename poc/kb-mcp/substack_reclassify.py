"""重新判斷完整度（011 FR-033；research R11、data-model §1.9／§2.2b）。

PO 覺得付費／全文判斷失準時，可以要求對指定文章或指定作者的文章重判：
* **只讀已保存的 `content_html`**：不重新請求站方、不呼叫模型、不發通知；
* **原判斷與原始內容永不改動**（`article` 的每個欄位位元組不變，FR-007 不受影響）：
  每次重判在 `reclassification` **新增一列**（結果相同也記，證明重判過、規則版本為何）；
* 有效完整度＝最近一筆重判的 `new_completeness`（沒有重判則為原判斷），以唯讀視圖
  `article_effective` 提供；
* **spec Q14 的例外**：原判斷 N 的文章 `body_text` 恆為 NULL，重判為 F／P 時以同一個
  `html_to_text` 由 `content_html` 重新產生內文，寫進該筆重判紀錄的 `derived_body_text`
  （不動 `article` 任何欄位）；重判為 N 時不填；`body_text` 已有值者不重算、不覆寫。

重判用的是「當下程式裡的規則」（`substack_html.classify`／`RULE_VERSION`），
所以站方改版後的流程是：先改規則（程式變更）→ 再請 PO 要求重判。

僅標準庫、Python 3.9 相容。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import substack_html  # noqa: E402

TRIGGER_ARTICLE = "po_article"
TRIGGER_AUTHOR = "po_author"


def _derived_body(row, new_completeness, new_reason):
    """只在「原本沒有內文（原判斷 N）且新結果為 F／P」時產生內文（spec Q14）。"""
    if row.get("body_text") is not None:
        return None
    if new_completeness not in ("F", "P"):
        return None
    try:
        text, _images = substack_html.html_to_text(
            row.get("content_html"),
            drop_read_more_tail=(new_reason == substack_html.REASON_READ_MORE),
            link=row.get("link"))
    except substack_html.HtmlParseError:
        return None                     # 抽不出文字就不填，不猜、不補假內容
    return text


def reclassify(store, article_ids=None, author=None, dry_run=False, trigger=None, run_id=None,
               clock=None):
    """回傳報告 dict：checked／unchanged／changed／changed_ids／transitions／missing_ids／dry_run。

    零網路、零模型；`dry_run=True` 時完全不寫庫（呼叫端以唯讀方式開庫）。
    """
    targets = []
    missing = []
    if article_ids is not None:
        for article_id in article_ids:
            row = store.effective_article(article_id)
            if row is None:
                missing.append(article_id)
            else:
                targets.append(row)
    else:
        targets = store.list_effective_articles(author_key=author)

    if trigger is None:
        trigger = TRIGGER_ARTICLE if article_ids is not None else TRIGGER_AUTHOR
    at = None
    if clock is not None:
        at = clock.now().isoformat(timespec="seconds")

    report = {"checked": 0, "unchanged": 0, "changed": 0, "changed_ids": [],
              "transitions": {}, "missing_ids": list(missing), "dry_run": bool(dry_run),
              "rows": []}
    for row in targets:
        old = row["effective_completeness"]
        new_completeness, new_reason = substack_html.classify(row.get("content_html"),
                                                              row.get("link"))
        changed = new_completeness != old
        report["checked"] += 1
        if changed:
            report["changed"] += 1
            report["changed_ids"].append(row["id"])
            key = (old, new_completeness)
            report["transitions"][key] = report["transitions"].get(key, 0) + 1
        else:
            report["unchanged"] += 1
        report["rows"].append({"article_id": row["id"], "old_completeness": old,
                               "new_completeness": new_completeness, "new_reason": new_reason,
                               "changed": 1 if changed else 0})
        if dry_run:
            continue
        store.add_reclassification(
            article_id=row["id"], trigger=trigger, old_completeness=old,
            new_completeness=new_completeness, new_reason=new_reason,
            rule_version=substack_html.RULE_VERSION,
            derived_body_text=_derived_body(row, new_completeness, new_reason),
            run_id=run_id, at=at)
    return report


def history(store, article_ids=None):
    """唯讀：每篇的原判斷、有效完整度與全部重判紀錄（時間、前後類別、依據、規則版本）。"""
    rows = []
    ids = list(article_ids) if article_ids else None
    if ids is None:
        ids = [r["id"] for r in store.list_effective_articles()]
    for article_id in ids:
        row = store.effective_article(article_id)
        if row is None:
            continue
        items = [
            {"at": r["at"], "trigger": r["trigger"], "old_completeness": r["old_completeness"],
             "new_completeness": r["new_completeness"], "new_reason": r["new_reason"],
             "rule_version": r["rule_version"], "changed": r["changed"],
             "has_derived_body": r["derived_body_text"] is not None}
            for r in store.reclassification_rows([article_id])
        ]
        rows.append({"article_id": row["id"],
                     "original_completeness": row["original_completeness"],
                     "original_reason": row["original_reason"],
                     "effective_completeness": row["effective_completeness"],
                     "reclassifications": items})
    return rows


def effective_completeness(store, article_id):
    """有效完整度＝最近一筆重判結果，沒有重判則為原判斷（research R11）。"""
    return store.effective_completeness(article_id)
