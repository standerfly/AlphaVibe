"""T001：共用假定錨網站的擴充功能自測（後續匯入測試都依賴它）。"""
import datetime
import os
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_investanchors_site import EMAIL, PASSWORD, FakeSite, fake_id  # noqa: E402

INDEX = "/user/vip_contents/investanchors_index"


class _Client(object):
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def get(self, path, timeout=10):
        try:
            with self.opener.open(self.base + path, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def login(self, email=EMAIL, password=PASSWORD):
        data = urllib.parse.urlencode({"email": email, "password": password}).encode()
        try:
            with self.opener.open(self.base + "/login", data, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:   # 登入成功後導向的清單頁可能是 403（list_mode）
            return e.code, e.read().decode("utf-8")


class FakeSiteTest(unittest.TestCase):
    def _site(self, **kw):
        site = FakeSite(**kw)
        base = site.start()
        self.addCleanup(site.stop)
        c = _Client(base)
        c.login()
        return site, c

    def test_fake_id_is_14_digits_with_epoch_ms_prefix(self):
        when = datetime.datetime(2026, 11, 8, 20, 23, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        i = fake_id(when, 1)
        self.assertEqual(len(str(i)), 14)
        self.assertEqual(int(str(i)[:13]), int(when.timestamp() * 1000))
        self.assertEqual(str(i)[-1], "1")

    def test_default_layout_unchanged_pinned_on_every_page_announcement_only_page1(self):
        site, c = self._site()
        _, p1 = c.get(INDEX)
        _, p2 = c.get(INDEX + "?page=2")
        self.assertEqual(p1.count('/user/vip_contents/777"'), 1)
        self.assertEqual(p2.count('/user/vip_contents/777"'), 1)
        self.assertIn("/user/vip_contents/9999", p1)
        self.assertNotIn("/user/vip_contents/9999", p2)
        self.assertIn('rel="next"', p1)
        self.assertNotIn('rel="next"', p2)

    def test_custom_items_per_page_and_no_announcement(self):
        items = [{"id": 100 + i, "title": "T%d" % i, "date": "2026-11-%02d" % (10 - i)} for i in range(5)]
        site, c = self._site(items=items, per_page=2, announcement=False, pinned=[])
        _, p1 = c.get(INDEX)
        _, p3 = c.get(INDEX + "?page=3")
        self.assertIn("/user/vip_contents/100", p1)
        self.assertNotIn("/user/vip_contents/9999", p1)
        self.assertIn("/user/vip_contents/104", p3)
        self.assertNotIn('rel="next"', p3)

    def test_article_modes(self):
        site, c = self._site(article_modes={1: "no_container", 2: "short", 3: "forbidden",
                                            4: "no_image"})
        base = "/user/vip_contents/"
        self.assertNotIn('id="inves_content"', c.get(base + "1")[1])
        status, short = c.get(base + "2")
        self.assertIn('id="inves_content"', short)
        self.assertLess(len(short), 1500)
        self.assertEqual(c.get(base + "3")[0], 403)
        no_img = c.get(base + "4")[1]
        self.assertNotIn("/img/pub/a1b2c3d4e5.png", no_img)
        normal = c.get(base + "5")[1]
        self.assertIn("/img/pub/a1b2c3d4e5.png", normal)
        self.assertIn("post_date", normal)
        self.assertEqual(site.article_requests(), [1, 2, 3, 4, 5])

    def test_normal_body_is_long_enough_to_pass_the_200_char_floor(self):
        site, c = self._site()
        body = c.get("/user/vip_contents/1010")[1]
        self.assertGreater(body.count("SECRETBODY"), 20)

    def test_list_mode_forbidden_and_timeout_mode(self):
        site, c = self._site(list_mode="forbidden", article_modes={9: "timeout"}, timeout_sleep=0.2)
        self.assertEqual(c.get(INDEX)[0], 403)
        self.assertEqual(c.get("/user/vip_contents/9")[0], 200)  # 逾時模式只是延遲

    def test_helpers_and_wrong_credentials(self):
        site = FakeSite()
        base = site.start()
        self.addCleanup(site.stop)
        c = _Client(base)
        c.login(password="wrong")
        self.assertEqual(site.sessions, set())
        c.login()
        self.assertEqual(len(site.login_posts()), 2)
        c.get(INDEX)
        self.assertEqual(len(site.list_requests()), 2)  # 未登入那次導向登入頁也算一次請求
        self.assertEqual(site.logout_requests(), [])


if __name__ == "__main__":
    unittest.main()
