"""010 Phase 6（US4）T042／T043／T044：歷史回補。

只用假網站（127.0.0.1）與假時鐘（每「天」跑一次）；Python 端邏輯用「會模擬瀏覽器端規則的假 scraper」快測，
另有幾條跑真 scraper＋假網站的端到端（無瀏覽器環境 skip）。不連真實網路、不讀鑰匙圈、不動正式庫。"""
import datetime
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import article_data_guard  # noqa: E402
import article_id_time  # noqa: E402
import article_store  # noqa: E402
import investanchors_import as I  # noqa: E402
from fake_investanchors_site import FakeSite, fake_id  # noqa: E402
from test_investanchors_import import BODY, WED, Harness, art, clue, li, summ  # noqa: E402
from test_investanchors_import_e2e import E2E  # noqa: E402
from test_investanchors_scraper_import import _browser_available  # noqa: E402
from test_investanchors_transcription import Env  # noqa: E402

TZ8 = I.TZ8
CUT_DATE, CUT_MS = article_id_time.cutoff_for(WED.date())      # 2026-05-11 00:00 +8
DAY = 24 * 3600 * 1000


def aid_at(days_ago, n=1):
    """建立時間為 WED 往前 days_ago 天的 14 位文章 ID。截止＝5/11、延後門檻＝4/27（約 198 天前）。"""
    return fake_id(WED - datetime.timedelta(days=days_ago), n)


def mk(days_ago, n=1, title=None, date="2026-11-01", ann=False):
    a = aid_at(days_ago, n)
    return {"id": a, "title": title or "T%d" % a, "date": date, "ann": ann}


PINNED = [dict(id=aid_at(2, 5), title="置頂一", date="2021-02-06", ann=False),
          dict(id=aid_at(3, 6), title="置頂二", date="2021-02-06", ann=False)]


class ListScraper(object):
    """模擬瀏覽器端：讀第 1 頁＋游標起的頁（共 ≤ max_list_pages）、置頂＝跨讀到的頁重複、
    「延後」只依 payload 的三個整數門檻（與 id_filter.js 同一句規則）、目標順序＝第 1 頁新文章→待辦→游標頁新文章。"""

    def __init__(self, items=None, per_page=4, pages=None, pinned=(), announcement=True):
        self.items = list(items or [])
        self.per_page = per_page
        self.explicit = dict(pages) if pages is not None else None
        self.pinned = list(pinned)
        self.announcement = announcement
        self.payloads = []
        self.read_pages = []
        self.opened = []                 # 歷次被「開啟」的文章 ID
        self.lie = {}                    # aid -> 強制回報的 defer 值（製造兩端不一致）
        self.fail_login = False
        self.dead_pages = set()          # 這些頁「讀不到」：翻到就中止後面的頁
        self.max_pages_seen = 0

    def rows(self, no):
        if self.explicit is not None:
            body = self.explicit.get(no, [])
        else:
            body = self.items[(no - 1) * self.per_page:no * self.per_page]
        rows = list(self.pinned)
        if no == 1 and self.announcement:
            rows.append({"id": 1612580077558, "title": "【公告】X", "date": "2027-01-01", "ann": True})
        return rows + list(body)

    @staticmethod
    def js_defer(aid, p):
        s = str(aid)
        if "defer_below_id" not in p or len(s) != 14 or not s.isdigit():
            return False
        n = int(s)
        return p["valid_id_min"] <= n <= p["valid_id_max"] and n < p["defer_below_id"]

    def __call__(self, p):
        self.payloads.append(p)
        if self.fail_login:
            return [summ(logged_in=False, stage_error="login_failed:bad_credentials")]
        nums = [1]
        cur = p.get("resume_cursor")
        if cur:
            nums += [cur + k for k in range(p["max_list_pages"] - 1)]
        read = {}
        for n in nums:
            if n in self.dead_pages:
                break
            read[n] = self.rows(n)
        self.read_pages.append(sorted(read))
        self.max_pages_seen = max(self.max_pages_seen, len(read))
        count = {}
        for rs in read.values():
            for r in rs:
                count[r["id"]] = count.get(r["id"], 0) + 1
        known = set(p["known_ids"])
        out, fresh, later = [], [], []
        for n in sorted(read):
            out.append({"type": "list_page", "page": n, "items": len(read[n])})
            for r in read[n]:
                d = self.lie.get(r["id"], self.js_defer(r["id"], p))
                out.append(li(r["id"], r["title"], date=r["date"], ann=r.get("ann", False),
                              pinned=count[r["id"]] > 1, page=n))
                out[-1]["defer"] = d
                if r.get("ann") or r["id"] in known or self.js_defer(r["id"], p):
                    continue
                (later if (cur and n > 1) else fresh).append(r["id"])
        pend = [i for i in p["pending_ids"] if i not in fresh and i not in later]
        seen, targets = set(), []
        for i in fresh + pend + later:
            if i not in seen:
                seen.add(i)
                targets.append(i)
        targets = targets[:p["max_articles"]]
        self.opened.extend(targets)
        for t in targets:
            out.append(art(t))
        out.append(summ(counters={"logins": 1, "navigations": 3, "list_pages": len(read),
                                  "articles_opened": len(targets)}))
        return out


def long_site():
    """游標頁 2～6 各有一篇近期文章：掃不完（沒有連續 2 頁全舊），回補會持續進行。"""
    return ListScraper(pages=dict((k, [mk(3 + k, k)]) for k in range(2, 7)), announcement=False)


class BF(Harness):
    """Harness＋預設啟用回補（既有 Harness 為了不影響非回補測試，預設關閉）。"""

    def __init__(self, test, scraper, **kw):
        Harness.__init__(self, test, script=scraper, **kw)
        self.scraper = scraper

    def run(self, argv=None, **over):
        over.setdefault("auto_backfill", True)
        return Harness.run(self, argv, **over)

    def day(self, n):
        self.clock[0] = WED + datetime.timedelta(days=n)
        return self.clock[0]

    def state(self):
        return self.store().get_backfill_state()

    def status_of(self, aid):
        r = self.store().get_article_row(aid)
        return r["status"] if r else None


def run_until_completed(h, max_days=40, start_day=0):
    for d in range(start_day, start_day + max_days):
        h.day(d)
        if d == start_day:
            h.clues = [clue("<first@x>")]
        rc = h.run()
        assert rc in (0, 1), h.out.getvalue()
        st = h.state()
        if st and st["completed"]:
            return d
    raise AssertionError("回補沒有在 %d 天內完成" % max_days)


# ====================================================================== T042：啟動、截止日、觸發

class BackfillStartTest(unittest.TestCase):
    def test_first_real_login_writes_fixed_cutoff_but_dry_run_never_does(self):
        ls = long_site()
        h = BF(self, ls, clues=[clue()])
        self.assertEqual(h.run(["--dry-run"]), 0)
        self.assertIsNone(h.state())                                      # dry-run 不寫
        self.assertEqual(ls.payloads, [])
        self.assertEqual(h.run(), 0)
        st = h.state()
        self.assertEqual((st["cutoff_date"], st["cutoff_ms"], st["completed"], st["next_cursor"]),
                         (CUT_DATE, CUT_MS, 0, "4"))                       # 本次讀了第 2、3 頁 → 下次從 4 起
        self.assertEqual(ls.payloads[0]["resume_cursor"], 2)              # 初始游標 2
        self.assertEqual(CUT_DATE, "2026-05-11")
        h.day(40)                                                         # 日期往後漂，截止日不動
        h.run()
        self.assertEqual((h.state()["cutoff_date"], h.state()["cutoff_ms"]), (CUT_DATE, CUT_MS))

    def test_no_login_means_no_start(self):
        h = BF(self, ListScraper())
        self.assertEqual(h.run(), 0)                                      # 無新信、非週日 → 不登入
        self.assertIsNone(h.state())
        self.assertEqual(h.payloads, [])

    def test_missing_credentials_do_not_start_backfill(self):
        h = BF(self, ListScraper(), clues=[clue()])
        h.creds_ok = False
        h.run()
        self.assertIsNone(h.state())

    def test_payload_carries_integer_thresholds_and_cursor_and_page_cap(self):
        ls = long_site()
        h = BF(self, ls, clues=[clue()])
        h.run()
        p = ls.payloads[0]
        now_ms = int(WED.timestamp() * 1000)
        self.assertEqual({k: p[k] for k in ("defer_below_id", "valid_id_min", "valid_id_max")},
                         article_id_time.defer_thresholds(CUT_MS, now_ms))
        self.assertEqual((p["resume_cursor"], p["max_list_pages"]), (2, 3))
        for k in ("defer_below_id", "valid_id_min", "valid_id_max", "resume_cursor"):
            self.assertIsInstance(p[k], int)
        self.assertNotIn("cutoff_ms", p)                                  # 瀏覽器端只拿整數門檻

    def test_without_auto_backfill_payload_has_no_backfill_fields(self):
        ls = ListScraper()
        h = BF(self, ls, clues=[clue()])
        h.run(auto_backfill=False)
        self.assertNotIn("defer_below_id", ls.payloads[0])
        self.assertNotIn("resume_cursor", ls.payloads[0])

    def test_backfill_active_and_trigger_follow_state(self):
        ls = long_site()
        h = BF(self, ls, clues=[clue()])
        s0 = h.store()
        self.assertFalse(I.backfill_active(s0))
        h.run()
        self.assertTrue(I.backfill_active(h.store()))
        h.day(1)
        h.run()                                                           # 沒新信，只因回補而登入
        self.assertEqual(len(ls.payloads), 2)
        self.assertEqual(h.store().recent_runs(1)[0]["trigger"], "backfill")


# ====================================================================== T042：ID 防呆、置頂、延後

class IdRulesTest(unittest.TestCase):
    def test_old_ids_become_deferred_with_only_id_title_and_list_date_and_are_never_opened(self):
        old = mk(300, title="舊文", date="2025-12-01")
        ls = long_site()
        ls.explicit[2] = [old]
        h = BF(self, ls, clues=[clue()])
        h.run()
        row = h.store().get_article_row(old["id"])
        self.assertEqual((row["status"], row["title"], row["list_date"], row["body"]),
                         ("deferred", "舊文", "2025-12-01", None))
        self.assertNotIn(old["id"], ls.opened)
        self.assertEqual(h.store().list_images(old["id"]), [])
        h.day(1)
        h.run()
        self.assertNotIn(old["id"], ls.payloads[1]["pending_ids"])        # 延後的不會被當待辦
        self.assertIn(old["id"], ls.payloads[1]["known_ids"])

    def test_pinned_items_with_2021_list_date_but_recent_id_are_fetched_not_deferred(self):
        ls = ListScraper(pages={2: [mk(20)]}, pinned=PINNED, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        for p in PINNED:
            row = h.store().get_article_row(p["id"])
            self.assertEqual((row["status"], row["pinned"], row["list_date"]), ("fetched", 1, "2021-02-06"))

    def test_four_pinned_with_2021_dates_all_fetched_in_the_real_flow(self):
        pinned = [dict(id=aid_at(1 + k, 5 + k), title="置頂%d" % k, date="2021-02-06", ann=False) for k in range(4)]
        ls = ListScraper(pages={2: [mk(20)]}, pinned=pinned)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual([h.status_of(p["id"]) for p in pinned], ["fetched"] * 4)

    def test_malformed_id_is_not_deferred_is_fetched_and_recorded_as_not_ok(self):
        short = {"id": 1001, "title": "短ID", "date": "2019-01-01", "ann": False}
        ls = ListScraper(pages={2: [short]}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        row = h.store().get_article_row(1001)
        self.assertEqual((row["status"], row["id_time_ok"]), ("fetched", 0))

    def test_unreasonable_time_is_not_deferred(self):
        future = fake_id(WED + datetime.timedelta(days=30))
        tiny = 1600000000000                                              # 13 位
        ancient = 15000000000001                                          # 14 位但前 13 位＝2017
        pages = {2: [{"id": x, "title": "x%d" % x, "date": "2019-01-01", "ann": False} for x in (future, tiny, ancient)]}
        ls = ListScraper(pages=pages, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        for x in (future, tiny, ancient):
            row = h.store().get_article_row(x)
            self.assertEqual((row["status"], row["id_time_ok"]), ("fetched", 0), x)

    def test_fourth_anomalous_id_alerts_po_but_three_do_not(self):
        bad = lambda k: {"id": 1000 + k, "title": "壞%d" % k, "date": "2019-01-01", "ann": False}   # noqa: E731
        ls = ListScraper(pages={2: [bad(1), bad(2), bad(3)]}, announcement=True)    # 13 位公告不算
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual(h.store().count_id_time_anomalies(), 3)
        self.assertFalse(any(n == I.ALERT_TEXTS["id_time_anomaly"] for n in h.notes))
        h.day(1)
        ls.explicit[4] = [bad(4)]                                         # 第 1 天讀的是游標頁 4、5
        h.run()
        self.assertEqual(h.store().count_id_time_anomalies(), 4)
        self.assertEqual([n for n in h.notes if n == I.ALERT_TEXTS["id_time_anomaly"]],
                         [I.ALERT_TEXTS["id_time_anomaly"]])

    def test_pending_old_discovered_item_is_deferred_by_python_before_login(self):
        ls = long_site()
        h = BF(self, ls, clues=[clue()])
        h.run()                                                           # 先啟動回補
        s = h.store()
        old = aid_at(400, 3)
        s.upsert_discovered(old, "https://investanchors.com/user/vip_contents/%d" % old, "舊待辦", via="mail")
        h.day(1)
        h.run()
        self.assertEqual(h.status_of(old), "deferred")
        self.assertNotIn(old, ls.payloads[1]["pending_ids"])


# ====================================================================== T042：進度、接續、完成

class ProgressTest(unittest.TestCase):
    def _site(self):
        """12 篇半年內＋6 篇更早（新到舊），每頁 4 篇；置頂 2 篇（ID 近期、清單日期 2021）。"""
        within = [mk(d, i) for i, d in enumerate([2, 9, 16, 23, 30, 45, 60, 80, 100, 120, 150, 180])]
        older = [mk(d, i) for i, d in enumerate([210, 230, 250, 280, 320, 360])]
        return within, older

    def test_multi_day_backfill_each_day_at_most_five_resumes_without_refetch_then_stops_for_good(self):
        within, older = self._site()
        ls = ListScraper(items=within + older, per_page=4, pinned=PINNED, announcement=True)
        h = BF(self, ls)
        done_day = run_until_completed(h)
        s = h.store()
        everything = set(w["id"] for w in within) | set(p["id"] for p in PINNED)
        self.assertEqual(set(r[0] for r in s.conn.execute("SELECT article_id FROM article WHERE status='fetched'")),
                         everything)
        self.assertEqual(set(r["article_id"] for r in s.deferred_rows()), set(o["id"] for o in older))
        self.assertEqual(len(ls.opened), len(set(ls.opened)))             # 一篇都沒重抓
        for r in s.recent_runs(50):
            self.assertLessEqual(r["articles_fetched"], 5)
        self.assertEqual(done_day, 2)                                     # 14 篇（12＋置頂 2）／每天 5 篇＝3 天（第 0～2 天）
        self.assertTrue(h.state()["completed"])
        logins = len(ls.payloads)
        for d in (done_day + 1, done_day + 3, done_day + 4):              # 完成後再也不因回補登入（略過週日：週日核對仍會登入）
            h.day(d)
            self.assertNotEqual(h.clock[0].weekday(), 6)
            h.run()
        self.assertEqual(len(ls.payloads), logins)
        self.assertFalse(I.backfill_active(h.store()))
        self.assertEqual(I.Importer(I.build_parser().parse_args(["--data-dir", h.tmp])
                                    )._triggers(h.store(), []).count("backfill"), 0)

    def test_interrupted_run_resumes_from_cursor_and_does_not_refetch(self):
        within, older = self._site()
        ls = ListScraper(items=within + older, per_page=4, pinned=[], announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual(h.state()["next_cursor"], "4")
        first = list(ls.opened)
        h.day(1)                                                          # 假設中間「中斷」一天沒跑也不影響
        h.day(2)
        h.run()
        self.assertEqual(ls.read_pages[-1], [1, 4, 5])                    # 從游標續讀
        self.assertTrue(set(first).issubset(set(ls.payloads[-1]["known_ids"])))
        self.assertFalse(set(first) & set(ls.opened[len(first):]))

    def test_new_articles_come_first_and_share_the_daily_five(self):
        within, older = self._site()
        ls = ListScraper(items=within + older, per_page=4, pinned=[], announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        h.day(1)
        fresh = [mk(0, k, title="新%d" % k) for k in (7, 8)]
        ls.items = fresh + ls.items
        h.run()
        day2 = ls.opened[5:]
        self.assertEqual(len(day2), 5)
        self.assertEqual(set(day2[:2]), set(f["id"] for f in fresh))      # 新文章優先

    def test_list_done_with_backlog_keeps_draining_without_reading_more_pages(self):
        within, older = self._site()
        ls = ListScraper(items=within + older, per_page=4, pinned=[], announcement=False)
        h = BF(self, ls)
        for d in range(0, 2):
            h.day(d)
            h.clues = [clue("<a@x>")] if d == 0 else []
            h.run()
        st = h.state()
        self.assertEqual((st["list_done"], st["completed"]), (1, 0))      # 清單掃完，但待辦還沒抓完
        self.assertTrue(I.backfill_active(h.store()))
        h.day(2)
        h.run()
        self.assertIsNone(ls.payloads[-1]["resume_cursor"])               # 只清待辦，不再往舊翻
        self.assertEqual(ls.read_pages[-1], [1])


class StopRuleTest(unittest.TestCase):
    def old_page(self, n, start=250):
        return [mk(start + 10 * k + n, k) for k in range(3)]

    def recent_page(self, n):
        return [mk(20 + 3 * n + k, k) for k in range(3)]

    def drive(self, pages, days):
        ls = ListScraper(pages=pages, announcement=False)
        h = BF(self, ls)
        states = []
        for d in range(days):
            h.day(d)
            h.clues = [clue("<a@x>")] if d == 0 else []
            h.run()
            st = h.state()
            states.append((st["next_cursor"], st["list_done"], st["completed"]))
        return h, ls, states

    def test_one_old_page_is_not_enough_two_consecutive_old_pages_are(self):
        pages = {2: self.recent_page(2), 3: self.old_page(3), 4: self.recent_page(4)[:1] + self.old_page(4)[:2],
                 5: self.old_page(5), 6: self.old_page(6)}
        h, ls, states = self.drive(pages, 1)
        self.assertEqual(ls.read_pages[-1], [1, 2, 3])
        self.assertEqual(states[-1][:2], ("4", 0))                        # 只有第 3 頁全舊 → 繼續
        h.day(1)
        h.run()                                                           # 讀第 4、5 頁：第 4 頁混有近期 → 不算
        self.assertEqual(ls.read_pages[-1], [1, 4, 5])
        self.assertEqual((h.state()["next_cursor"], h.state()["list_done"]), ("6", 0))
        h.day(2)
        h.run()                                                           # 第 6 頁全舊＋第 7 頁沒有東西（尾端）→ 連續 2 頁
        self.assertEqual(ls.read_pages[-1], [1, 6, 7])
        self.assertEqual(h.state()["list_done"], 1)

    def test_two_old_pages_in_one_run_set_list_done_and_do_not_assume_order(self):
        # 清單順序不穩：第 2 頁近期、第 3、4 頁全舊，之後又出現近期項目——不得因「某頁全舊」就假設後面都更舊
        pages = {2: self.recent_page(2), 3: self.old_page(3), 4: self.old_page(4), 5: self.recent_page(5)}
        h, ls, states = self.drive(pages, 2)
        self.assertEqual(states[0][:2], ("4", 0))                         # 第 1 天讀 2、3：只有 3 全舊
        self.assertEqual(states[1][1], 0)                                 # 第 2 天讀 4、5：4 全舊、5 近期 → 仍不算
        self.assertEqual(h.state()["next_cursor"], "6")

    def test_page_with_non_ok_id_is_not_old(self):
        weird = {"id": 1001, "title": "短", "date": "2019-01-01", "ann": False}
        pages = {2: self.old_page(2) + [weird], 3: self.old_page(3)}
        h, ls, states = self.drive(pages, 1)
        self.assertEqual(states[0][1], 0)

    def test_pinned_and_announcement_do_not_count_against_or_for_the_stop_rule(self):
        # 兩個游標頁除置頂外都是舊文：置頂（近期 ID）不得讓整頁變成「不算舊」
        pages = {2: self.old_page(2), 3: self.old_page(3)}
        ls = ListScraper(pages=pages, pinned=PINNED, announcement=True)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual(h.state()["list_done"], 1)

    def test_completed_needs_empty_backlog_and_then_trigger_stops(self):
        pages = {2: self.old_page(2), 3: self.old_page(3)}
        ls = ListScraper(pages=pages, pinned=PINNED, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual((h.state()["list_done"], h.state()["completed"]), (1, 1))   # 沒有待辦 → 完成
        self.assertFalse(I.backfill_active(h.store()))


class CursorTest(unittest.TestCase):
    def test_cursor_does_not_advance_on_login_failure_or_unread_pages(self):
        ls = ListScraper(pages={2: [mk(10)], 3: [mk(11)], 4: [mk(12)], 5: [mk(13)]}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual(h.state()["next_cursor"], "4")
        ls.fail_login = True
        h.day(1)
        h.run()
        self.assertEqual(h.state()["next_cursor"], "4")                   # 登入失敗：不推進
        ls.fail_login = False
        ls.dead_pages = {4, 5}                                            # 游標頁讀不到
        h.day(2)
        h.run()
        self.assertEqual(h.state()["next_cursor"], "4")
        ls.dead_pages = {5}                                               # 只讀到 4
        h.day(3)
        h.run()
        self.assertEqual(h.state()["next_cursor"], "5")

    def test_cursor_never_moves_backwards(self):
        ls = ListScraper(pages={}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        h.store().update_backfill(next_cursor="9")
        s = h.store()
        s.close = lambda: None
        ls.explicit = {3: [mk(10)]}                                       # 異常：只回舊頁碼的項目
        it = [dict(li(aid_at(10), page=3), defer=False)]
        imp = I.Importer(I.build_parser().parse_args(["--data-dir", h.tmp, "--dry-run"]), now=lambda: WED)
        imp._bf = {"cutoff_ms": CUT_MS, "now_ms": int(WED.timestamp() * 1000), "resume": 9}
        h.store().update_backfill(next_cursor="9")
        imp._apply_progress(h.store(), it, [])
        self.assertEqual(h.state()["next_cursor"], "9")

    def test_inserting_articles_between_logins_shifts_pages_but_nothing_is_missed(self):
        within = [mk(d, i) for i, d in enumerate(range(2, 100, 7))]
        older = [mk(d, i) for i, d in enumerate(range(230, 300, 10))]
        ls = ListScraper(items=within + older, per_page=4, pinned=PINNED, announcement=True)
        h = BF(self, ls)
        added = []
        for d in range(0, 12):
            h.day(d)
            h.clues = [clue("<a@x>")] if d == 0 else []
            if d in (1, 2, 3):                                           # 兩次登入之間網站新增 3 篇、頁界位移
                new = [mk(0, 7 + d * 0 + k + d * 3, title="新%d-%d" % (d, k)) for k in range(3)]
                ls.items = new + ls.items
                added += new
            h.run()
            if h.state()["completed"]:
                break
        self.assertTrue(h.state()["completed"])
        s = h.store()
        want_fetched = set(x["id"] for x in within + added) | set(p["id"] for p in PINNED)
        got_fetched = set(r[0] for r in s.conn.execute("SELECT article_id FROM article WHERE status='fetched'"))
        self.assertEqual(got_fetched, want_fetched)
        self.assertEqual(set(r["article_id"] for r in s.deferred_rows()), set(o["id"] for o in older))


# ====================================================================== A'(2)：執行期對帳

class CutoffMismatchTest(unittest.TestCase):
    def test_browser_says_defer_but_python_says_not_writes_no_deferred_and_alerts(self):
        item = mk(10, title="近期")
        ls = ListScraper(pages={2: [item]}, announcement=False)
        ls.lie[item["id"]] = True                                         # 瀏覽器端誤判延後（不開啟）
        h = BF(self, ls, clues=[clue()])
        rc = h.run()
        self.assertEqual(rc, 1)
        self.assertNotEqual(h.status_of(item["id"]), "deferred")          # 不寫 deferred（假瀏覽器仍開啟了它→fetched）
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "cutoff_mismatch")
        self.assertEqual([n for n in h.notes if n == I.ALERT_TEXTS["cutoff_mismatch"]],
                         [I.ALERT_TEXTS["cutoff_mismatch"]])
        self.assertEqual(h.state()["next_cursor"], "2")                   # 不推進
        self.assertEqual((h.state()["list_done"], h.state()["completed"]), (0, 0))

    def test_browser_says_keep_but_python_says_old_still_writes_no_deferred(self):
        old = mk(300, title="舊")
        ls = ListScraper(pages={2: [old]}, announcement=False)
        ls.lie[old["id"]] = False                                         # 瀏覽器端沒延後 → 會開啟
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertNotEqual(h.status_of(old["id"]), "deferred")
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "cutoff_mismatch")
        self.assertIn(I.ALERT_TEXTS["cutoff_mismatch"], h.notes)

    def test_consistent_run_never_alerts(self):
        ls = ListScraper(pages={2: [mk(10), mk(300, 2)]}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertNotIn(I.ALERT_TEXTS["cutoff_mismatch"], h.notes)
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "ok")

    def test_missing_defer_field_counts_as_not_deferred(self):
        old = mk(300)
        base = ListScraper(pages={2: [old]}, announcement=False)

        def strip(p):
            return [dict((k, v) for k, v in o.items() if k != "defer") for o in base(p)]
        h = BF(self, strip, clues=[clue()])
        h.run()
        self.assertEqual(h.store().recent_runs(1)[0]["result"], "cutoff_mismatch")

    def test_alert_text_is_fixed_and_has_no_details(self):
        t = I.ALERT_TEXTS["cutoff_mismatch"]
        self.assertNotRegex(t, r"\d{6,}")
        self.assertIn("定錨匯入", t)


# ====================================================================== T044：--backfill-since

class BackfillSinceTest(unittest.TestCase):
    def setup_state(self):
        old_a, old_b = mk(210, 1, title="剛好舊一"), mk(300, 2, title="很舊")
        ls = ListScraper(pages={2: [mk(10), old_a, old_b]}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        h.run()
        self.assertEqual(h.status_of(old_a["id"]), "deferred")
        return h, ls, old_a, old_b

    def test_widening_updates_cutoff_resets_progress_and_reactivates_only_the_in_between_ones(self):
        h, ls, old_a, old_b = self.setup_state()
        h.store().update_backfill(next_cursor="7", completed=True, list_done=True)
        new_date = "2026-02-11"                                           # 往前約 3 個月：210 天前(4/15)進範圍，300 天前(1/15)仍太舊
        n_before = len(ls.payloads)
        h.fetch_probe = []
        rc = h.run(["--backfill-since", new_date], fetch_mail=lambda: h.fetch_probe.append(1) or [])
        self.assertEqual(rc, 0, h.out.getvalue())
        d, ms = article_id_time.cutoff_from_date(datetime.date(2026, 2, 11))
        st = h.state()
        self.assertEqual((st["cutoff_date"], st["cutoff_ms"], st["completed"], st["next_cursor"], st["list_done"]),
                         (d, ms, 0, "2", 0))
        self.assertEqual((h.status_of(old_a["id"]), h.status_of(old_b["id"])), ("discovered", "deferred"))
        self.assertEqual(len(ls.payloads), n_before)                      # 只改資料庫：沒登入
        self.assertEqual(h.fetch_probe, [])                               # 也沒取信
        self.assertTrue(I.backfill_active(h.store()))
        self.assertIn("放寬範圍須 PO 同意", h.out.getvalue())

    def test_widened_backfill_is_still_capped_at_five_per_run(self):
        within = [mk(d, 1) for d in range(1, 10)]
        mid = [mk(d, 2) for d in range(215, 224)]
        ls = ListScraper(pages={2: within, 3: mid}, announcement=False)
        h = BF(self, ls, clues=[clue()])
        run_until_completed(h)
        self.assertEqual(len(h.store().deferred_rows()), len(mid))
        self.assertEqual(h.run(["--backfill-since", "2026-02-11"]), 0)
        before = len(ls.opened)
        h.day(50)
        h.run()
        self.assertEqual(len(ls.opened) - before, 5)                     # 仍受每日 5 篇上限
        self.assertTrue(I.backfill_active(h.store()))

    def test_refuses_same_or_later_date_and_changes_nothing(self):
        h, ls, old_a, old_b = self.setup_state()
        for bad in (CUT_DATE, "2026-06-01", "2026-11-01"):
            h.out.truncate(0)
            h.out.seek(0)
            self.assertEqual(h.run(["--backfill-since", bad]), 2)
            self.assertIn("只能往前放寬", h.out.getvalue())
            self.assertIn("放寬範圍須 PO 同意", h.out.getvalue())
            self.assertEqual((h.state()["cutoff_date"], h.state()["next_cursor"]), (CUT_DATE, "4"))
        self.assertEqual(h.status_of(old_a["id"]), "deferred")

    def test_refuses_bad_format_and_missing_state(self):
        h, ls, _a, _b = self.setup_state()
        self.assertEqual(h.run(["--backfill-since", "2026/02/11"]), 2)
        self.assertEqual(h.run(["--backfill-since", "yesterday"]), 2)
        fresh = BF(self, ListScraper())
        self.assertEqual(fresh.run(["--backfill-since", "2026-01-01"]), 2)
        self.assertIsNone(fresh.state())

    def test_cannot_combine_with_other_action_flags(self):
        h, ls, _a, _b = self.setup_state()
        for extra in (["--dry-run"], ["--resume"], ["--retranscribe"], ["--force-weekly"],
                      ["--enable-transcription"], ["--disable-transcription"], ["--reset-abandoned", "5"],
                      ["--transcribe-sample", "3"], ["--max-articles", "2"], ["--reset-transcribe-attempts"]):
            self.assertEqual(h.run(["--backfill-since", "2026-02-11"] + extra), 2, extra)
        self.assertEqual(h.state()["cutoff_date"], CUT_DATE)

    def test_data_dir_guard_applies(self):
        boom = mock.Mock(side_effect=AssertionError("不得開啟資料庫"))
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(article_store, "ArticleStore", boom):
            os.environ.pop("ALPHAVIBE_ALLOW_PRODUCTION_WRITE", None)
            rc = I.run(["--data-dir", article_data_guard.PRODUCTION_DATA_DIR, "--backfill-since", "2026-01-01"],
                       out=__import__("io").StringIO())
        self.assertEqual(rc, 2)
        boom.assert_not_called()

    def test_help_text_says_po_consent_is_required(self):
        txt = I.build_parser().format_help()
        self.assertIn("--backfill-since", txt)
        self.assertIn("放寬範圍須 PO 同意", " ".join(txt.split()))


# ====================================================================== 小修正：確定性切片失敗計次

class _TS(object):
    def __init__(self, reason):
        self.status, self.reason = "untranscribed", reason

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_tile_bytes(self):
        return iter(())


class TileFailureCountingTest(unittest.TestCase):
    def _seed(self, e):
        s = article_store.ArticleStore(e.h.tmp)
        aid = 2001
        s.upsert_discovered(aid, "https://investanchors.com/user/vip_contents/%d" % aid, "t")
        s.mark_fetched(aid, "內文。" * 100)
        s.add_image(aid, 1, "http://127.0.0.1/x.png")
        rel = os.path.join("articles_images", str(aid), "1.png")
        os.makedirs(os.path.join(e.h.tmp, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(e.h.tmp, rel), "wb") as f:
            f.write(e.png)
        s.set_image_file(aid, 1, rel)
        s.close()

    def _attempts(self, e):
        return [r[0] for r in e.h.store().conn.execute("SELECT transcribe_attempts FROM article_image")]

    def _run_with(self, reason, runs):
        e = Env(self)
        self._seed(e)
        e.run(["--enable-transcription"])
        calls = []

        def fake_open(path, runner=None, tmp_root=None):
            calls.append(path)
            return _TS(reason)
        with mock.patch.object(I.article_image_tiles, "open_tiles", fake_open):
            for _ in range(runs):
                e.run()
        return e, calls

    def test_deterministic_reasons_count_and_stop_after_three(self):
        for reason in ("too_many_tiles", "tile_too_small", "unsupported_or_corrupt_image", "tile_bytes_too_large"):
            e, calls = self._run_with(reason, 5)
            self.assertEqual(self._attempts(e), [I.MAX_TRANSCRIBE_ATTEMPTS], reason)
            self.assertEqual(len(calls), I.MAX_TRANSCRIBE_ATTEMPTS, reason)   # 第 4、5 次不再自動補轉
            self.assertEqual(e.requests(), 0)

    def test_transient_reasons_do_not_count(self):
        for reason in ("tiler_failed:boom", "no_browser", "bad_dimensions"):
            e, calls = self._run_with(reason, 4)
            self.assertEqual(self._attempts(e), [0], reason)
            self.assertEqual(len(calls), 4, reason)                           # 每次都會再試

    def test_reset_flag_makes_deterministic_failures_retry_again(self):
        e, calls = self._run_with("too_many_tiles", 4)
        self.assertEqual(self._attempts(e), [3])
        e.h.store().reset_transcribe_attempts()
        with mock.patch.object(I.article_image_tiles, "open_tiles", lambda *a, **k: _TS("too_many_tiles")):
            e.run()
        self.assertEqual(self._attempts(e), [1])


# ====================================================================== 端到端（真 scraper＋假網站＋假時鐘）

class BFE2E(E2E):
    def go(self, argv=None, **over):
        over.setdefault("auto_backfill", True)
        return E2E.go(self, argv, **over)


@unittest.skipUnless(_browser_available(), "需要 node＋playwright＋瀏覽器")
class RealScraperBackfillTest(unittest.TestCase):
    def _items(self):
        within = [{"id": aid_at(d, i), "title": "近%d" % d, "date": "2026-11-01"}
                  for i, d in enumerate([2, 12, 25, 40, 60, 90, 120, 150, 170, 185])]
        older = [{"id": aid_at(d, i), "title": "舊%d" % d, "date": "2026-11-01"}
                 for i, d in enumerate([215, 240, 270, 300, 330])]
        return within, older

    def test_multi_day_real_flow_pinned_fetched_older_only_deferred_then_no_more_logins(self):
        within, older = self._items()
        pinned = [{"id": aid_at(1 + k, 5 + k), "title": "置頂%d" % k, "date": "2021-02-06"} for k in range(4)]
        site = FakeSite(items=within + older, per_page=4, pinned=pinned, announcement=True)
        h = BFE2E(self, site, clues=[clue()])
        done = None
        for d in range(0, 8):
            h.day = d
            h.clock[0] = WED + datetime.timedelta(days=d)
            self.assertIn(h.go(), (0, 1), h.out.getvalue())
            self.assertEqual(site.sessions, set())
            if h.store().get_backfill_state()["completed"]:
                done = d
                break
        self.assertIsNotNone(done, h.out.getvalue())
        s = h.store()
        fetched = set(r[0] for r in s.conn.execute("SELECT article_id FROM article WHERE status='fetched'"))
        self.assertEqual(fetched, set(x["id"] for x in within) | set(p["id"] for p in pinned))
        self.assertEqual(set(r["article_id"] for r in s.deferred_rows()), set(o["id"] for o in older))
        opens = site.article_requests()
        self.assertEqual(len(opens), len(set(opens)))                      # 一篇都沒重開
        self.assertFalse(set(opens) & set(o["id"] for o in older))         # 更早的從未被開啟
        for r in s.recent_runs(20):
            self.assertLessEqual(r["articles_fetched"], 5)
        self.assertEqual(max(len(set(site.page_log[i:i + 3])) for i in range(0, len(site.page_log), 3)), 3)
        self.assertEqual(len(site.login_posts()), done + 1)               # 每「天」最多登入 1 次
        before = len(site.login_posts())
        h.clock[0] = WED + datetime.timedelta(days=done + 1)
        self.assertEqual(h.go(), 0)
        self.assertEqual(len(site.login_posts()), before)                  # 完成後不再登入

    def test_articles_added_between_real_logins_are_never_missed(self):
        within, older = self._items()
        site = FakeSite(items=within + older, per_page=3, pinned=[], announcement=False)
        h = BFE2E(self, site, clues=[clue()])
        added = []
        for d in range(0, 10):
            h.clock[0] = WED + datetime.timedelta(days=d)
            if d in (1, 2):
                new = [{"id": aid_at(0, 7 + 3 * d + k), "title": "新%d%d" % (d, k), "date": "2026-11-11"}
                       for k in range(2)]
                site.items = new + site.items
                added += new
            self.assertIn(h.go(), (0, 1), h.out.getvalue())
            if h.store().get_backfill_state()["completed"]:
                break
        self.assertTrue(h.store().get_backfill_state()["completed"], h.out.getvalue())
        fetched = set(r[0] for r in h.store().conn.execute("SELECT article_id FROM article WHERE status='fetched'"))
        self.assertEqual(fetched, set(x["id"] for x in within + added))


if __name__ == "__main__":
    unittest.main()
