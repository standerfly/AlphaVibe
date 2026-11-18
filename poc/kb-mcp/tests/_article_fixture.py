"""US2 測試共用：建立含數篇 fetched 文章的測試 articles.db（假資料，不含真實內容）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import article_store as A  # noqa: E402

URL = "https://investanchors.com/user/vip_contents/%d"


def body(text):
    return (text + "。") + "補充說明。" * 60


def set_verification(store, article_id, seq, verdict="ok", method=None, verifier="test-tool", note=None, cells=None):
    """測試用：verdict=ok 時兩個檢核家族都通過（數字 compare-d-c＋文字 agent-spot-check）→ cross_checked；
    verdict=issues 時標 flagged。回傳最後一次 apply_verification_batch 的結果。"""
    row = store.conn.execute("SELECT id, transcription FROM article_image WHERE article_id=? AND seq=?",
                             (article_id, seq)).fetchone()
    base = {"image_id": row["id"], "verifier": verifier, "cells": cells,
            "transcription_sha256": A.transcription_sha256(row["transcription"])}
    if verdict == "issues":
        return store.apply_verification_batch([dict(base, verdict="issues", method=method or "compare-d-c",
                                                    note=note or "發現 1 項疑慮（wrong-number×1）")])
    store.apply_verification_batch([dict(base, verdict="ok", method=method or "compare-d-c", note=None)])
    return store.apply_verification_batch([dict(base, verdict="ok", method="agent-spot-check", note=None)])


def build(data_dir):
    s = A.ArticleStore(data_dir)
    rows = [
        (101, "環宇產業筆記", "2026-11-10", body("環宇今年財測上修，EPS 看升")),
        (102, "緯穎觀察", "2026-11-12", body("伺服器需求強勁，緯穎毛利率回升")),
        (103, "折扣率 100% 的_特例", "2026-11-05", body("折扣率達 100% 且 a_b 命名")),
        (104, "圖表文章", "2026-11-14", body("本文主要內容在圖表")),
    ]
    for aid, title, date, text in rows:
        s.upsert_discovered(aid, URL % aid, title, list_date=date)
        s.mark_fetched(aid, text, published_at=date + "T08:00:00+08:00")
    s.add_image(104, 1, "https://img.example/104-1.png")
    s.set_transcription(104, 1, "done", text="營收 98765 百萬元 毛利率 31%", model="m", is_table=True)
    set_verification(s, 104, 1)        # 已交叉驗證才納入搜尋（Q-028）
    s.add_image(104, 2, "https://img.example/104-2.png")
    s.set_transcription(104, 2, "untranscribed", is_table=None)
    # 未成功匯入：不得被搜到
    s.upsert_discovered(105, URL % 105, "環宇未匯入", list_date="2026-11-14")
    s.close()
