"""T029：圖片下載（`substack_images.py`）的單元測試。

涵蓋 V3、V13、SC-008、SC-013、FR-014～FR-016、FR-034：
  (1) https 限定＋主機白名單（非白名單**零請求**、記 `host_not_allowed`、計次）
  (2) 轉址只允許落在白名單主機（否則 `redirect_refused`）
  (3) `Content-Type` 非 `image/*` → `not_image`；>20MB → `too_large`（中止讀取、刪 `.part`）；
      逾時 30 秒且取 `min(30, 剩餘)`；圖與圖間隔 `sleep(1)`
  (4) 寫入順序：`.part` → `os.replace` → 才 UPDATE 成 `downloaded`（含 sha256、bytes、file_path）
  (5) 狀態機 `pending`→`missing(1)`→`missing(2)`→`abandoned(3)`，之後排程零請求
  (6) 磁碟滿／期限到：丟 `DiskFullError`／中斷，狀態與 `fail_count` 不變、`.part` 不殘留
  (7) `retry(ids)`：只接受 `abandoned`／`missing`，其餘明列拒絕
  (8) 封面圖（`enclosure` 為 `image/*`）以 `seq=0` 下載；`audio/*`／`video/*` 只記型別不下載
  (9) FR-016 靜態：沒有刪除正式圖檔的程式路徑（`os.remove`／`unlink` 只允許作用於 `.part`）
 (10) 零模型（模組不得提及模型相關模組；import 守門在 T013）
 T034 追加：`add-image-host` 後 `--retry-images` 可下載先前 `host_not_allowed` 的圖（SC-013）

零真實網路：一律注入 `_substack_fixture` 的 FakeHttp／FakeClock。
"""
import errno
import hashlib
import io
import os
import re
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _substack_fixture as F  # noqa: E402
import substack_feed as FEED  # noqa: E402
import substack_images as IMG  # noqa: E402
import substack_import as IMP  # noqa: E402
import substack_store as S  # noqa: E402

ALLOWED = (F.IMAGE_HOST, F.DEFAULT_HOST)
OTHER_HOST = "zzevilhost.example.com"


class ImagesTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.store = S.SubstackStore(self.dir)
        self.addCleanup(self.store.close)

    # ---- 組裝：一篇文章＋n 張圖片列（status=pending）
    def seed(self, count=1, host=F.IMAGE_HOST, first_seq=1, scheme="https"):
        rows = [{"seq": first_seq + i,
                 "src_url": "%s://%s/%s-%d.jpg" % (scheme, host, F.IMG_URL_MARK, first_seq + i),
                 "alt": "ALT%d" % i, "caption": None} for i in range(count)]
        self.article_id = self.store.insert_article_with_images(F.article_row(), rows)
        self.assertIsNotNone(self.article_id)
        return self.store.list_images(self.article_id)

    def image(self, image_id):
        return self.store.get_image(image_id)

    def run_one(self, row, **kwargs):
        kwargs.setdefault("fetch", self.http)
        kwargs.setdefault("allowed_hosts", ALLOWED)
        kwargs.setdefault("sleep", self.clock.sleep)
        return IMG.download_one(self.store, row, **kwargs)

    def run_batch(self, rows, **kwargs):
        kwargs.setdefault("fetch", self.http)
        kwargs.setdefault("allowed_hosts", ALLOWED)
        kwargs.setdefault("sleep", self.clock.sleep)
        return IMG.download_batch(self.store, rows, **kwargs)

    def serve(self, url, *actions):
        self.http.route(url, *actions)

    def full_path(self, rel):
        return os.path.join(self.dir, rel)


# ================================================================ (1) 白名單與 https
class HostWhitelistTest(ImagesTestBase):
    def test_host_allowed_exact_and_subdomain_only(self):
        self.assertTrue(IMG.host_allowed("substackcdn.com", ("substackcdn.com",)))
        self.assertTrue(IMG.host_allowed("cdn.substackcdn.com", ("substackcdn.com",)))
        self.assertFalse(IMG.host_allowed("evilsubstackcdn.com", ("substackcdn.com",)),
                         "只允許完全相同或真正的子網域，不是字尾比對")
        self.assertFalse(IMG.host_allowed("substackcdn.com.evil.test", ("substackcdn.com",)))
        self.assertFalse(IMG.host_allowed("", ("substackcdn.com",)))
        self.assertFalse(IMG.host_allowed("substackcdn.com", ()))

    def test_non_whitelisted_host_makes_zero_requests(self):
        rows = self.seed(1, host=OTHER_HOST)
        result = self.run_one(rows[0])
        self.assertEqual(self.http.count(), 0, "非白名單主機不得發出請求（FR-034）")
        self.assertEqual(result["code"], "host_not_allowed")
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"], row["last_error_code"]),
                         ("missing", 1, "host_not_allowed"))
        self.assertIsNone(row["file_path"])

    def test_http_scheme_is_refused_without_request(self):
        rows = self.seed(1, scheme="http")
        result = self.run_one(rows[0])
        self.assertEqual(self.http.count(), 0, "只允許 https")
        self.assertEqual(result["code"], "host_not_allowed")
        self.assertEqual(self.image(rows[0]["id"])["fail_count"], 1)

    def test_subdomain_of_whitelisted_host_is_downloaded(self):
        rows = self.seed(1, host="cdn." + F.IMAGE_HOST)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        self.assertEqual(self.image(rows[0]["id"])["status"], "downloaded")

    def test_author_feed_host_is_allowed(self):
        rows = self.seed(1, host=F.DEFAULT_HOST)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        self.assertEqual(self.image(rows[0]["id"])["status"], "downloaded")


# ================================================================ (2) 轉址
class RedirectTest(ImagesTestBase):
    def test_refused_redirect_is_recorded_as_code_only(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.redirect("https://%s/x.jpg" % OTHER_HOST))
        result = self.run_one(rows[0])
        self.assertEqual(result["code"], "redirect_refused")
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["last_error_code"]), ("missing", "redirect_refused"))
        self.assertNotIn(OTHER_HOST, str(row["last_error_code"]))

    def test_default_fetch_redirect_handler_only_allows_whitelist(self):
        """正式路徑的轉址判斷：不實際連線，只驗判斷函式。"""
        handler = IMG.AllowedHostRedirect((F.IMAGE_HOST,))
        self.assertTrue(handler.target_allowed("https://%s/a.jpg" % F.IMAGE_HOST))
        self.assertTrue(handler.target_allowed("https://cdn.%s/a.jpg" % F.IMAGE_HOST))
        self.assertFalse(handler.target_allowed("https://%s/a.jpg" % OTHER_HOST))
        self.assertFalse(handler.target_allowed("http://%s/a.jpg" % F.IMAGE_HOST))


# ================================================================ (3) 回應判別
class ResponseRulesTest(ImagesTestBase):
    def test_non_image_content_type(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.ok("<html>not an image</html>", content_type="text/html"))
        result = self.run_one(rows[0])
        self.assertEqual(result["code"], "not_image")
        self.assertEqual(self.image(rows[0]["id"])["last_error_code"], "not_image")
        self.assertFalse(os.path.isdir(os.path.join(self.dir, S.IMAGES_DIRNAME, "1")))

    def test_image_subtype_without_allowed_extension_is_not_image(self):
        """image/* 但不在副檔名白名單（例 image/tiff）→ 無法決定副檔名，記 not_image。"""
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok(content_type="image/tiff"))
        self.assertEqual(self.run_one(rows[0])["code"], "not_image")

    def test_http_error_status_is_recorded_as_code(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(404, "nope"))
        self.assertEqual(self.run_one(rows[0])["code"], "http_404")
        self.assertEqual(self.image(rows[0]["id"])["last_error_code"], "http_404")

    def test_too_large_by_content_length_aborts_before_reading(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"],
                   F.image_ok(headers={"Content-Length": str(IMG.MAX_IMAGE_BYTES + 1)}))
        result = self.run_one(rows[0])
        self.assertEqual(result["code"], "too_large")
        self.assertEqual(self.parts(), [], "不得留下 .part 暫存檔")
        self.assertEqual(self.files(), [])

    def test_too_large_by_actual_bytes_removes_part(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok(data=b"x" * (IMG.MAX_IMAGE_BYTES + 1)))
        result = self.run_one(rows[0])
        self.assertEqual(result["code"], "too_large")
        self.assertEqual(self.parts(), [])
        self.assertEqual(self.files(), [], "超過上限不留半個檔案")
        self.assertEqual(self.image(rows[0]["id"])["status"], "missing")

    def test_max_image_bytes_is_twenty_megabytes(self):
        self.assertEqual(IMG.MAX_IMAGE_BYTES, 20 * 1024 * 1024)
        self.assertEqual(IMG.IMAGE_TIMEOUT, 30)
        self.assertEqual(IMG.IMAGE_GAP_SEC, 1)

    def test_timeout_is_default_30_and_clamped_to_remaining(self):
        rows = self.seed(2)
        for row in rows:
            self.serve(row["src_url"], F.image_ok())
        self.run_one(rows[0])
        self.assertEqual(self.http.requests[0]["timeout"], 30, "沒有期限時用預設 30 秒")
        self.run_one(rows[1], deadline=lambda: 12)
        self.assertEqual(self.http.requests[1]["timeout"], 12, "期限剩 12 秒 → min(30, 12)")

    def test_timeout_outcome_is_code_only(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.timeout())
        self.assertEqual(self.run_one(rows[0])["code"], "timeout")
        self.assertEqual(self.image(rows[0]["id"])["last_error_code"], "timeout")

    def test_network_error_outcome(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.network())
        self.assertEqual(self.run_one(rows[0])["code"], "network")

    def test_requests_carry_no_cookie_or_authorization(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        headers = self.http.requests[0]["headers"]
        self.assertNotIn("cookie", [k.lower() for k in headers])
        self.assertNotIn("authorization", [k.lower() for k in headers])
        self.assertEqual(headers.get("User-Agent"), FEED.UA)

    def test_one_second_gap_between_images_but_not_before_the_first(self):
        rows = self.seed(3)
        for row in rows:
            self.serve(row["src_url"], F.image_ok())
        self.clock.slept = []
        self.run_batch(rows)
        self.assertEqual(self.clock.slept, [1, 1], "三張圖 → 兩次間隔；第一張前不等")

    def test_no_gap_for_images_that_make_no_request(self):
        rows = self.seed(1, host=OTHER_HOST)
        self.clock.slept = []
        self.run_batch(rows)
        self.assertEqual(self.clock.slept, [], "沒有發出請求就不需要禮貌間隔")

    # ---- 小工具
    def parts(self):
        return self.collect(lambda name: name.endswith(IMG.PART_SUFFIX))

    def files(self):
        return self.collect(lambda name: not name.endswith(IMG.PART_SUFFIX))

    def collect(self, keep):
        base = os.path.join(self.dir, S.IMAGES_DIRNAME)
        out = []
        for root, _dirs, names in os.walk(base):
            out.extend(os.path.join(root, n) for n in names if keep(n))
        return sorted(out)


# ================================================================ (4) 寫入與路徑
class WriteTest(ImagesTestBase):
    def test_success_writes_file_then_updates_row(self):
        rows = self.seed(1)
        data = F.image_bytes(64)
        self.serve(rows[0]["src_url"], F.image_ok(data=data))
        result = self.run_one(rows[0])
        self.assertEqual(result["result"], "downloaded")
        row = self.image(rows[0]["id"])
        rel = os.path.join(S.IMAGES_DIRNAME, str(self.article_id), "1.jpg")
        self.assertEqual(row["file_path"], rel)
        self.assertEqual(row["status"], "downloaded")
        self.assertEqual(row["fail_count"], 0)
        self.assertIsNone(row["last_error_code"])
        self.assertEqual(row["bytes"], len(data))
        self.assertEqual(row["sha256"], hashlib.sha256(data).hexdigest())
        self.assertTrue(row["downloaded_at"].endswith("+08:00"))
        with open(self.full_path(rel), "rb") as f:
            self.assertEqual(f.read(), data)

    def test_downloaded_implies_file_exists(self):
        rows = self.seed(2)
        for row in rows:
            self.serve(row["src_url"], F.image_ok())
        self.run_batch(rows)
        for row in self.store.list_images(self.article_id):
            if row["status"] == "downloaded":
                self.assertIsNotNone(row["file_path"])
                self.assertTrue(os.path.isfile(self.full_path(row["file_path"])))
            else:
                self.assertIsNone(row["file_path"])

    def test_path_is_fixed_and_carries_no_url_fragment(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        rel = self.image(rows[0]["id"])["file_path"]
        self.assertNotIn(F.IMG_URL_MARK, rel, "路徑不得含任何網址片段")
        self.assertNotIn(F.IMAGE_HOST, rel)
        self.assertRegex(rel, r"^substack_images/\d+/\d+\.jpg$")

    def test_realpath_stays_under_data_dir(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        full = os.path.realpath(self.full_path(self.image(rows[0]["id"])["file_path"]))
        base = os.path.realpath(os.path.join(self.dir, S.IMAGES_DIRNAME))
        self.assertTrue(full.startswith(base + os.sep), full)

    def test_extension_comes_from_content_type_whitelist(self):
        cases = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
                 "image/webp": "webp", "image/gif": "gif"}
        for seq, (content_type, ext) in enumerate(sorted(cases.items()), start=1):
            self.setUp()
            rows = self.seed(1)
            self.serve(rows[0]["src_url"], F.image_ok(content_type=content_type))
            self.run_one(rows[0])
            self.assertTrue(self.image(rows[0]["id"])["file_path"].endswith("." + ext),
                            "%s → .%s" % (content_type, ext))

    def test_part_file_is_used_and_removed(self):
        """`.part` → `os.replace`：資料庫說 downloaded 時檔案必然在正式路徑上。"""
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())
        seen = {}
        real_replace = os.replace

        def spy(src, dst):
            seen["src"], seen["dst"] = src, dst
            seen["src_exists"] = os.path.isfile(src)
            seen["row_status"] = self.store.get_image(rows[0]["id"])["status"]
            return real_replace(src, dst)

        with mock.patch.object(os, "replace", spy):
            self.run_one(rows[0])
        self.assertTrue(seen["src"].endswith(IMG.PART_SUFFIX))
        self.assertTrue(seen["src_exists"])
        self.assertEqual(seen["row_status"], "pending", "UPDATE 必須在 os.replace 之後")
        self.assertFalse(os.path.exists(seen["src"]))
        self.assertTrue(os.path.isfile(seen["dst"]))

    def test_cover_image_uses_seq_zero_path(self):
        rows = self.seed(1, first_seq=0)
        self.serve(rows[0]["src_url"], F.image_ok(content_type="image/png"))
        self.run_one(rows[0])
        self.assertEqual(self.image(rows[0]["id"])["file_path"],
                         os.path.join(S.IMAGES_DIRNAME, str(self.article_id), "0.png"))


# ================================================================ (8) 封面與非圖片 enclosure
class EnclosureTest(unittest.TestCase):
    """封面圖判斷在 `substack_import._image_rows`（純函式，零網路）。"""

    def item(self, enclosure_type, url="https://%s/cover.jpg" % F.IMAGE_HOST):
        return {"enclosure_type": enclosure_type, "enclosure_url": url}

    def test_image_enclosure_becomes_seq_zero(self):
        rows = IMP._image_rows([{"seq": 1, "src": "https://%s/a.jpg" % F.IMAGE_HOST}],
                               self.item("image/jpeg"))
        self.assertEqual([r["seq"] for r in rows], [0, 1])
        self.assertEqual(rows[0]["src_url"], "https://%s/cover.jpg" % F.IMAGE_HOST)

    def test_audio_and_video_enclosure_are_not_downloaded(self):
        for kind in ("audio/mpeg", "video/mp4", "application/pdf"):
            rows = IMP._image_rows([{"seq": 1, "src": "https://%s/a.jpg" % F.IMAGE_HOST}],
                                   self.item(kind, url="https://%s/a.mp3" % F.IMAGE_HOST))
            self.assertEqual([r["seq"] for r in rows], [1], "%s 不得建立圖片列" % kind)

    def test_enclosure_already_in_body_is_not_duplicated(self):
        url = "https://%s/cover.jpg" % F.IMAGE_HOST
        rows = IMP._image_rows([{"seq": 1, "src": url}], self.item("image/jpeg", url=url))
        self.assertEqual([r["seq"] for r in rows], [1])


# ================================================================ (5) 狀態機
class StateMachineTest(ImagesTestBase):
    def test_pending_missing_missing_abandoned_then_zero_requests(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(500))
        image_id = rows[0]["id"]
        expected = [("missing", 1), ("missing", 2), ("abandoned", 3)]
        for i, (status, count) in enumerate(expected, start=1):
            batch = self.run_batch(self.store.images_awaiting_download())
            row = self.image(image_id)
            self.assertEqual((row["status"], row["fail_count"]), (status, count),
                             "第 %d 次失敗" % i)
            self.assertEqual(batch["failed"], 1)
            self.assertEqual(batch["abandoned"], 1 if status == "abandoned" else 0)
        before = self.http.count()
        self.assertEqual(self.store.images_awaiting_download(), [],
                         "abandoned 不再被排程選取")
        batch = self.run_batch(self.store.images_awaiting_download())
        self.assertEqual(self.http.count(), before, "放棄後零請求（SC-008）")
        self.assertEqual(batch["downloaded"], 0)

    def test_download_one_refuses_abandoned_row_without_request(self):
        rows = self.seed(1)
        self.store.set_image_failed(rows[0]["id"], "http_500")
        self.store.set_image_failed(rows[0]["id"], "http_500")
        self.store.set_image_failed(rows[0]["id"], "http_500")
        row = self.image(rows[0]["id"])
        self.assertEqual(row["status"], "abandoned")
        result = self.run_one(row)
        self.assertEqual(result["result"], "skipped")
        self.assertEqual(self.http.count(), 0)

    def test_missing_image_is_filled_on_next_pass(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(500), F.image_ok())
        self.run_batch(self.store.images_awaiting_download())
        self.assertEqual(self.image(rows[0]["id"])["status"], "missing")
        self.run_batch(self.store.images_awaiting_download())
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("downloaded", 0))
        self.assertTrue(os.path.isfile(self.full_path(row["file_path"])))

    def test_batch_counts_each_outcome(self):
        rows = self.seed(3)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.serve(rows[1]["src_url"], F.status(500))
        self.serve(rows[2]["src_url"], F.image_ok())
        batch = self.run_batch(rows)
        self.assertEqual((batch["downloaded"], batch["failed"], batch["abandoned"]), (2, 1, 0))
        self.assertEqual(batch["requested"], 3)
        self.assertFalse(batch["deadline_reached"])
        self.assertEqual(batch["codes"], {"http_500": 1})


# ================================================================ (6) 磁碟滿與期限
class DiskFullTest(ImagesTestBase):
    def test_enospc_while_writing_raises_disk_full_and_keeps_state(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())

        def boom(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(IMG, "_stream_to_part", boom):
            with self.assertRaises(S.DiskFullError):
                self.run_one(rows[0])
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"], row["last_error_code"]),
                         ("pending", 0, None), "環境問題不計入圖片失敗次數")
        self.assertEqual(self.part_files(), [])

    def test_sqlite_disk_full_raises_and_keeps_state(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())

        def boom(*args, **kwargs):
            raise sqlite3.OperationalError("database or disk is full")

        with mock.patch.object(S.SubstackStore, "set_image_downloaded", boom):
            with self.assertRaises(S.DiskFullError):
                self.run_one(rows[0])
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("pending", 0))
        self.assertEqual(self.part_files(), [])

    def test_other_write_error_counts_as_failure(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())

        def boom(*args, **kwargs):
            raise OSError(errno.EIO, "I/O error")

        with mock.patch.object(IMG, "_stream_to_part", boom):
            result = self.run_one(rows[0])
        self.assertEqual(result["code"], "write_failed")
        self.assertEqual(self.image(rows[0]["id"])["fail_count"], 1)
        self.assertEqual(self.part_files(), [])

    def test_deadline_already_passed_makes_no_request(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok())
        result = self.run_one(rows[0], deadline=lambda: 0)
        self.assertEqual(result["result"], "deadline")
        self.assertEqual(self.http.count(), 0)
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("pending", 0))

    def test_batch_stops_at_deadline_without_touching_remaining_rows(self):
        rows = self.seed(3)
        for row in rows:
            self.serve(row["src_url"], F.image_ok())
        budget = [20.0, 20.0, 0.0, 0.0, 0.0]

        def deadline():
            return budget.pop(0) if budget else 0.0

        batch = self.run_batch(rows, deadline=deadline)
        self.assertTrue(batch["deadline_reached"])
        self.assertEqual(batch["downloaded"], 1)
        statuses = [r["status"] for r in self.store.list_images(self.article_id)]
        self.assertEqual(statuses, ["downloaded", "pending", "pending"])
        self.assertEqual([r["fail_count"] for r in self.store.list_images(self.article_id)],
                         [0, 0, 0], "期限中止不計失敗次數")

    def test_deadline_during_write_removes_part_and_keeps_state(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.image_ok(data=F.image_bytes(IMG.CHUNK_BYTES * 3)))
        calls = [50.0, 50.0]

        def deadline():
            return calls.pop(0) if calls else 0.0

        result = self.run_one(rows[0], deadline=deadline)
        self.assertEqual(result["result"], "deadline")
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("pending", 0))
        self.assertEqual(self.part_files(), [])
        self.assertEqual(self.image_files(), [], "中斷的下載不留下正式檔")

    def part_files(self):
        return self.walk(lambda n: n.endswith(IMG.PART_SUFFIX))

    def image_files(self):
        return self.walk(lambda n: not n.endswith(IMG.PART_SUFFIX))

    def walk(self, keep):
        out = []
        for root, _dirs, names in os.walk(os.path.join(self.dir, S.IMAGES_DIRNAME)):
            out.extend(os.path.join(root, n) for n in names if keep(n))
        return sorted(out)


# ================================================================ (7) PO 要求重試
class RetryTest(ImagesTestBase):
    def test_retry_resets_fail_count_and_tries_once(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(500), F.status(500), F.status(500),
                   F.image_ok())
        for _ in range(3):
            self.run_batch(self.store.images_awaiting_download())
        self.assertEqual(self.image(rows[0]["id"])["status"], "abandoned")
        report = IMG.retry(self.store, [rows[0]["id"]], fetch=self.http,
                           allowed_hosts=ALLOWED, sleep=self.clock.sleep)
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["accepted"], [rows[0]["id"]])
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("downloaded", 0))
        self.assertEqual(report["stats"]["downloaded"], 1)

    def test_retry_of_missing_is_accepted(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(500), F.image_ok())
        self.run_batch(self.store.images_awaiting_download())
        self.assertEqual(self.image(rows[0]["id"])["status"], "missing")
        report = IMG.retry(self.store, [rows[0]["id"]], fetch=self.http,
                           allowed_hosts=ALLOWED, sleep=self.clock.sleep)
        self.assertEqual(report["rejected"], [])
        self.assertEqual(self.image(rows[0]["id"])["status"], "downloaded")

    def test_retry_rejects_downloaded_pending_and_unknown_ids(self):
        rows = self.seed(2)
        self.serve(rows[0]["src_url"], F.image_ok())
        self.run_one(rows[0])
        before = self.http.count()
        report = IMG.retry(self.store, [rows[0]["id"], rows[1]["id"], 9999], fetch=self.http,
                           allowed_hosts=ALLOWED, sleep=self.clock.sleep)
        self.assertEqual(report["accepted"], [])
        self.assertEqual([r[0] for r in report["rejected"]],
                         [rows[0]["id"], rows[1]["id"], 9999])
        self.assertEqual([r[1] for r in report["rejected"]],
                         ["status_downloaded", "status_pending", "not_found"])
        self.assertEqual(self.http.count(), before, "被拒絕的 id 不得發出請求")
        self.assertEqual(self.image(rows[1]["id"])["status"], "pending")

    def test_retry_failure_counts_from_zero_again(self):
        rows = self.seed(1)
        self.serve(rows[0]["src_url"], F.status(500), F.status(500), F.status(500),
                   F.status(500))
        for _ in range(3):
            self.run_batch(self.store.images_awaiting_download())
        IMG.retry(self.store, [rows[0]["id"]], fetch=self.http, allowed_hosts=ALLOWED,
                  sleep=self.clock.sleep)
        row = self.image(rows[0]["id"])
        self.assertEqual((row["status"], row["fail_count"]), ("missing", 1),
                         "重試歸零後再失敗一次＝missing(1)，不是直接回 abandoned")


# ================================================================ (9)(10) 靜態守門
DELETE_RE = re.compile(r"os\.remove\(|os\.unlink\(|\.unlink\(|shutil\.rmtree|os\.rmdir")
# 只掃**程式識別字**，不掃中文敘述——模組的 docstring 本來就要寫「不設保留期限」，
# 拿中文詞掃描會把「宣告沒有這件事」的句子當成違規（本測試第一版就踩到）。
RETENTION_WORDS = ("disk_usage", "retention", "max_total", "quota", "prune", "expire",
                   "older_than")


def source_of(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def deletion_findings(text):
    """回傳「刪除呼叫但附近沒有提到 .part」的行號清單（FR-016 守門）。"""
    lines = text.splitlines()
    findings = []
    for idx, line in enumerate(lines):
        if not DELETE_RE.search(line):
            continue
        window = "\n".join(lines[max(0, idx - 5):idx + 1]).lower()
        if "part" not in window:
            findings.append(idx + 1)
    return findings


class Fr016StaticTest(unittest.TestCase):
    """FR-016：本版不刪圖、不設保留期限或占用上限，只回報占用現況。"""

    def test_no_deletion_path_for_downloaded_images(self):
        text = source_of("substack_images.py")
        self.assertEqual(deletion_findings(text), [],
                         "substack_images.py 只允許刪除 .part 暫存檔")

    def test_scanner_catches_a_real_deletion(self):
        """反向測試：掃描器必須抓得到「刪正式圖檔」的寫法，否則是裝飾品。"""
        bad = "def clean(path):\n    os.remove(path)\n"
        self.assertEqual(deletion_findings(bad), [2])
        good = ("def discard(path):\n"
                "    # 只刪 .part 暫存檔\n"
                "    os.remove(path)\n")
        self.assertEqual(deletion_findings(good), [])

    def test_no_retention_or_quota_handling(self):
        text = source_of("substack_images.py")
        for word in RETENTION_WORDS:
            self.assertNotIn(word, text, "圖片模組不得有保留期限／占用上限處理（FR-016）")

    def test_no_model_module_mentioned(self):
        text = source_of("substack_images.py").lower()
        for word in ("claude", "transcribe", "openai", "model("):
            self.assertNotIn(word, text, "圖片不送模型分析（FR-014）")


# ================================================================ T034：SC-013 端到端
class AddImageHostThenRetryTest(unittest.TestCase):
    """非白名單主機的圖 → `add-image-host` → `--retry-images` 可下載（SC-013、FR-034）。"""

    def setUp(self):
        import substack_config as C
        self.C = C
        self.dir = F.temp_data_dir(self)
        self.clock = F.FakeClock()
        self.http = F.FakeHttp(self.clock)
        self.notifier = F.FakeNotifier()
        F.write_config(self.dir, image_hosts=[])
        store = S.SubstackStore(self.dir)
        self.src = "https://%s/%s-9.jpg" % (F.IMAGE_HOST, F.IMG_URL_MARK)
        article_id = store.insert_article_with_images(
            F.article_row(), [{"seq": 1, "src_url": self.src, "alt": None, "caption": None}])
        self.image_id = store.list_images(article_id)[0]["id"]
        store.close()
        self.http.route(self.src, F.image_ok())
        for host in (F.DEFAULT_HOST, F.SECOND_HOST):
            self.http.route("https://%s/robots.txt" % host, F.ok("", content_type="text/plain"))
        for author, host in ((F.AUTHOR_A, F.DEFAULT_HOST), (F.AUTHOR_B, F.SECOND_HOST)):
            self.http.route(author["feed_url"], F.ok(F.make_feed([], host=host)))

    def go(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = IMP.run(["--data-dir", self.dir] + list(args), http=self.http,
                       notifier=self.notifier, clock=self.clock, sleep=self.clock.sleep,
                       env={}, out=out, err=err)
        return code, out.getvalue() + err.getvalue()

    def config_cli(self, *args):
        out = io.StringIO()
        code = self.C.main(["--data-dir", self.dir] + list(args), env={}, out=out)
        return code, out.getvalue()

    def image(self):
        store = S.SubstackStore(self.dir)
        try:
            return store.get_image(self.image_id)
        finally:
            store.close()

    def test_host_not_allowed_then_add_host_then_retry_downloads(self):
        code, text = self.go()                      # 一次完整執行：補下載時撞到白名單
        self.assertEqual(code, IMP.EXIT_OK, text)
        self.assertEqual(self.http.count(self.src), 0, "白名單外零請求")
        row = self.image()
        self.assertEqual((row["status"], row["last_error_code"]), ("missing", "host_not_allowed"))

        code, text = self.config_cli("add-image-host", F.IMAGE_HOST)
        self.assertEqual(code, 0, text)
        self.assertIn(F.IMAGE_HOST, self.C.load_config(self.dir)["image_hosts"])

        code, text = self.go("--retry-images", str(self.image_id))
        self.assertEqual(code, IMP.EXIT_OK, text)
        self.assertEqual(self.http.count(self.src), 1)
        self.assertEqual(self.image()["status"], "downloaded")
        self.assertNotIn(F.IMG_URL_MARK, text, "stdout 不得含圖片網址（FR-026）")


if __name__ == "__main__":
    unittest.main()
