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
    """14 位數 ID 的前 13 位 → epoch 毫秒；形態不符或換算時間不合理回 None。"""
    n = parse_article_id(article_id)
    if n is None:
        return None
    s = str(n)
    if len(s) != ID_DIGITS:
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


def cutoff_for(start_day):
    """回補截止：(ISO 日期, 該日 00:00 台北時間的 epoch 毫秒)。"""
    d = six_months_before(start_day)
    ms = int(datetime.datetime(d.year, d.month, d.day, tzinfo=TZ8).timestamp() * 1000)
    return d.isoformat(), ms


def is_before_cutoff(article_id, cutoff_ms, margin_days=MARGIN_DAYS, now_ms=None):
    """只有 id_time_ok 且建立時間早於「截止日 − 餘裕」才回 True；id_time_ok=0 一律 False。"""
    ms = id_time_ms(article_id, now_ms)
    if ms is None:
        return False
    return ms < int(cutoff_ms) - int(margin_days) * 24 * 3600 * 1000
