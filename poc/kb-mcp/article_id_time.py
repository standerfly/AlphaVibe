"""由定錨文章 ID 推建立時間（010 research R11、spec 驗收（f））。

探查觀察（31 筆樣本，網站並未保證）：14 位數文章 ID 的前 13 位是建立時間的 epoch 毫秒。
這個規律只用來做歷史回補的半年截止，**必須有防呆**：ID 形態不符、或換算時間不合理時，
`id_time_ok=0`，該篇**不得被判為「早於截止日」而跳過**（`is_before_cutoff` 一律回 False）。

僅標準庫，Python 3.9 相容。
"""
import datetime
import time

TZ8 = datetime.timezone(datetime.timedelta(hours=8))
EARLIEST_MS = int(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
FUTURE_SLACK_MS = 24 * 3600 * 1000
MARGIN_DAYS = 14
ID_DIGITS = 14


def _now_ms(now_ms=None):
    return int(time.time() * 1000) if now_ms is None else int(now_ms)


def parse_article_id(value):
    """純數字、正整數才算合法；回傳 int，否則 None。"""
    s = str(value).strip() if value is not None else ""
    if not s.isdigit():
        return None
    n = int(s)
    return n if n > 0 else None


def id_time_ms(article_id, now_ms=None):
    """14 位數 ID 的前 13 位 → epoch 毫秒；形態不符或換算時間不合理回 None。

    形態判定只看字串本身：必須剛好是 14 個 ASCII 數字（不剝空白、不正規化前導零——
    與瀏覽器端 id_filter.js 逐筆一致，見 tests/fixtures/id_time_corpus.json）。整數輸入先轉十進位字串。"""
    s = str(article_id) if article_id is not None else ""
    if len(s) != ID_DIGITS or not all(c in "0123456789" for c in s):
        return None
    ms = int(s[:13])
    if ms < EARLIEST_MS or ms > _now_ms(now_ms) + FUTURE_SLACK_MS:
        return None
    return ms


def id_time_ok(article_id, now_ms=None):
    return id_time_ms(article_id, now_ms) is not None


def six_months_before(day):
    """回補啟動日往前六個月（日數超出該月時取該月最後一天）。"""
    month = day.month - 6
    year = day.year
    if month <= 0:
        month += 12
        year -= 1
    last = (datetime.date(year + (month == 12), (month % 12) + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last))


def cutoff_from_date(d):
    """指定截止日：(ISO 日期, 該日 00:00 台北時間的 epoch 毫秒)。`--backfill-since` 與 cutoff_for 共用。"""
    ms = int(datetime.datetime(d.year, d.month, d.day, tzinfo=TZ8).timestamp() * 1000)
    return d.isoformat(), ms


def cutoff_for(start_day):
    """回補截止：(ISO 日期, 該日 00:00 台北時間的 epoch 毫秒)。"""
    return cutoff_from_date(six_months_before(start_day))


def is_before_cutoff(article_id, cutoff_ms, margin_days=MARGIN_DAYS, now_ms=None):
    """只有 id_time_ok 且建立時間早於「截止日 − 餘裕」才回 True；id_time_ok=0 一律 False。"""
    ms = id_time_ms(article_id, now_ms)
    if ms is None:
        return False
    return ms < int(cutoff_ms) - int(margin_days) * 24 * 3600 * 1000


def defer_thresholds(cutoff_ms, now_ms=None, margin_days=MARGIN_DAYS):
    """把「ID 時間」判定換成純整數門檻交給 scraper（Python 是唯一權威，瀏覽器端不含任何時間常數）。

    14 位數 ID 的前 13 位是毫秒，所以「毫秒 m 滿足 a <= m <= b」等價於 ID 落在 [a*10, b*10+9]；
    「m < c」等價於 ID < c*10。瀏覽器端只做：14 位純數字、valid_id_min <= ID <= valid_id_max、
    且 ID < defer_below_id → 延後（不開啟）。與 `is_before_cutoff` 逐筆等價（tests/fixtures/id_time_corpus.json 守門）。
    """
    return {
        "defer_below_id": (int(cutoff_ms) - int(margin_days) * 24 * 3600 * 1000) * 10,
        "valid_id_min": EARLIEST_MS * 10,
        "valid_id_max": (_now_ms(now_ms) + FUTURE_SLACK_MS) * 10 + 9,
    }
