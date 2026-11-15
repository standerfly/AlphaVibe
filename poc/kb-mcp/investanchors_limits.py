"""低頻上限常數與守衛（010 FR-007／FR-012，spec 驗收（a））。

**放寬任何一項都須 PO 同意**（寫進 tasks.md 通用規則 5）。本模組刻意不 import `article_store`
（`LimitGuard` 只要求傳入的 store 有 `logins_today()` 與 `blocked_until()` 兩個方法），
這樣 `article_store` 可以反過來引用這裡的常數而不會循環 import。
僅標準庫，Python 3.9 相容。
"""
import datetime
import random

MAX_ARTICLES_PER_RUN = 5
MAX_LOGINS_PER_DAY = 1
DELAY_RANGE = (30, 90)            # 篇與篇之間（秒）
IMAGE_DELAY_RANGE = (5, 15)       # 圖片下載之間（秒）
MAX_ATTEMPTS_PER_ARTICLE = 3
BLOCK_BACKOFF_DAYS = 1
MAX_LIST_PAGES = 3

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
        return rng.uniform(*IMAGE_DELAY_RANGE)

    def block_until(self, now=None):
        base = now or self.now()
        return base + datetime.timedelta(days=BLOCK_BACKOFF_DAYS)
