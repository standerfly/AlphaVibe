"""低頻上限常數與守衛（010 FR-007／FR-012，spec 驗收（a））。

**放寬任何一項都須 PO 同意**（寫進 tasks.md 通用規則 5）。2026-11-17 PO 決定每日登入上限由 1 次放寬為 2 次
（只放寬登入次數；每次 ≤5 篇與頁／篇間隔下限不變），並新增「兩次登入至少間隔 6 小時」（Phase 9）。
本模組刻意不 import `article_store`
（`LimitGuard` 只要求傳入的 store 有 `logins_today()`、`last_login_started_at()` 與 `blocked_until()` 三個方法），
這樣 `article_store` 可以反過來引用這裡的常數而不會循環 import。
僅標準庫，Python 3.9 相容。
"""
import datetime
import os
import random

MAX_ARTICLES_PER_RUN = 5
MAX_LOGINS_PER_DAY = 2            # 2026-11-17 PO 決定由 1 放寬為 2（排程 12:30、23:00）
MIN_LOGIN_GAP_HOURS = 6           # 兩次登入（以實際登入開始時間，即 logged_in=1 的 run 的 started_at）至少相隔
DELAY_RANGE = (30, 90)            # 篇與篇之間（秒）
IMAGE_DELAY_RANGE = (5, 15)       # 圖片下載之間（秒）
MAX_ATTEMPTS_PER_ARTICLE = 3
# 間隔下限（低頻是硬性要求；Python 與 scraper JS 各自強制，兩邊數值須一致）：
MIN_PAGE_DELAY_MS = 30000         # 頁／篇之間下限（毫秒）
MIN_IMAGE_DELAY_SECONDS = 5       # 圖片之間下限（秒）
# 僅測試用，正式環境（launchd plist、CLI）不得設定：設為 "1" 時略過上述下限，讓假網站測試用小間隔。
TEST_SHORT_DELAY_ENV = "INVESTANCHORS_TEST_ALLOW_SHORT_DELAY"
BLOCK_BACKOFF_DAYS = 1
MAX_LIST_PAGES = 3


def short_delay_allowed(environ=None):
    return (environ if environ is not None else os.environ).get(TEST_SHORT_DELAY_ENV) == "1"


def clamp_delay_ms(delay_ms, environ=None):
    """把 [a,b] 毫秒間隔的兩端夾到 MIN_PAGE_DELAY_MS（有測試環境變數時原樣回傳）。b 不得小於 a。"""
    lo, hi = int(delay_ms[0]), int(delay_ms[1])
    if short_delay_allowed(environ):
        return [lo, hi]
    lo = max(lo, MIN_PAGE_DELAY_MS)
    return [lo, max(hi, lo)]


def clamp_image_delay_seconds(seconds, environ=None):
    return seconds if short_delay_allowed(environ) else max(seconds, MIN_IMAGE_DELAY_SECONDS)


TZ8 = datetime.timezone(datetime.timedelta(hours=8))


class LimitGuard(object):
    def __init__(self, store, now=None):
        self.store = store
        self._now = now or (lambda: datetime.datetime.now(TZ8))

    def now(self):
        n = self._now()
        return n if n.tzinfo else n.replace(tzinfo=TZ8)

    def may_login(self):
        """回傳 (可否登入, 原因)；拒絕時呼叫端不得啟動任何登入。"""
        now = self.now()
        until = self.store.blocked_until()
        if until is not None and now < until:
            return False, "blocked_until:%s" % until.isoformat()
        if self.store.logins_today(now) >= MAX_LOGINS_PER_DAY:
            return False, "daily_login_limit"
        last = self.store.last_login_started_at()
        if last is not None:
            earliest = last + datetime.timedelta(hours=MIN_LOGIN_GAP_HOURS)
            if now < earliest:                    # 剛好滿 6 小時（now == earliest）放行
                return False, "min_gap:%s" % earliest.isoformat()
        return True, "ok"

    def cap_for_run(self, requested=None):
        """每次抓取篇數上限：只能降低、不得超過 MAX_ARTICLES_PER_RUN。"""
        if requested is None:
            return MAX_ARTICLES_PER_RUN
        return max(0, min(int(requested), MAX_ARTICLES_PER_RUN))

    def delay_seconds(self, rng=None):
        rng = rng or random
        return rng.uniform(*DELAY_RANGE)

    def image_delay_seconds(self, rng=None):
        rng = rng or random
        return clamp_image_delay_seconds(rng.uniform(*IMAGE_DELAY_RANGE))

    def block_until(self, now=None):
        base = now or self.now()
        return base + datetime.timedelta(days=BLOCK_BACKOFF_DAYS)
