"""article_transcribe 測試（010 T036）：只用本機假 HTTP server（127.0.0.1），不連真實網路、不讀真實鑰匙圈。"""
import base64
import io
import json
import logging
import os
import sys
import threading
import time
import unittest
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import article_transcribe as at  # noqa: E402
import keychain_secrets  # noqa: E402

KEY = "sk-ant-FAKE-KEY-0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngdata"
JPG = b"\xff\xd8\xff\xe0" + b"fakejpg"


def ok_resp(is_table=True, text="a|b", stop="end_turn", content=None):
    if content is None:
        content = [{"type": "thinking", "thinking": "", "signature": "x"},
                   {"type": "text", "text": json.dumps({"is_table": is_table, "text": text})}]
    return 200, {"stop_reason": stop, "content": content}


class FakeServer(object):
    """依序回放 responses（每項 (status, json_obj_or_bytes) 或 ('sleep', 秒)）；用完後重複最後一項。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []   # (headers dict, body dict)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                outer.requests.append((dict((k.lower(), v) for k, v in self.headers.items()), body))
                i = min(len(outer.requests) - 1, len(outer.responses) - 1)
                status, payload = outer.responses[i]
                if status == "sleep":
                    time.sleep(payload)
                    return
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d/v1/messages" % self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def serve(self, responses):
        s = FakeServer(responses)
        self.addCleanup(s.close)
        return s

    def setUp(self):
        self.sleeps = []
        self.secret_calls = []

    def get_secret(self, account, service=None):
        self.secret_calls.append((account, service))
        return KEY

    def run_img(self, server, tiles=(PNG,), **kw):
        kw.setdefault("get_secret", self.get_secret)
        kw.setdefault("sleeper", self.sleeps.append)
        return at.transcribe_image(list(tiles), api_url=server.url, **kw)


class SingleTileTest(Base):
    def test_success_and_request_shape(self):
        s = self.serve([ok_resp(True, "表頭|值\n1|2")])
        r = self.run_img(s)
        self.assertEqual(r["status"], "transcribed")
        self.assertTrue(r["is_table"])
        self.assertEqual(r["text"], "表頭|值\n1|2")
        self.assertEqual(r["model"], "claude-haiku-5-5")
        self.assertFalse(r["abort"])
        self.assertEqual(self.secret_calls, [("vision-api-key", keychain_secrets.INVESTANCHORS_SERVICE)])
        hdr, body = s.requests[0]
        self.assertEqual(hdr["x-api-key"], KEY)
        self.assertEqual(hdr["anthropic-version"], "2026-10-21")
        self.assertEqual(hdr["content-type"], "application/json")
        for k in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(k, body)
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["output_config"]["effort"], "low")
        fmt = body["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(sorted(fmt["schema"]["required"]), ["is_table", "text"])
        content = body["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[1]["type"], "text")
        self.assertEqual(content[0]["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(content[0]["source"]["data"]), PNG)
        self.assertIn("?", content[1]["text"])

    def test_jpeg_media_type(self):
        s = self.serve([ok_resp()])
        self.run_img(s, tiles=(JPG,))
        self.assertEqual(s.requests[0][1]["messages"][0]["content"][0]["source"]["media_type"], "image/jpeg")

    def test_unknown_format_untranscribed_no_request(self):
        s = self.serve([ok_resp()])
        r = self.run_img(s, tiles=(b"notanimage",))
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(len(s.requests), 0)

    def test_refusal(self):
        s = self.serve([ok_resp(stop="refusal")])
        r = self.run_img(s)
        self.assertEqual(r["status"], "untranscribed")
        self.assertIsNone(r["text"])
        self.assertIn("refusal", r["reason"])
        self.assertFalse(r["abort"])
        self.assertEqual(len(s.requests), 1)

    def test_max_tokens(self):
        s = self.serve([ok_resp(stop="max_tokens", text="partial")])
        r = self.run_img(s)
        self.assertEqual(r["status"], "untranscribed")
        self.assertIsNone(r["text"])

    def test_other_stop_reason(self):
        r = self.run_img(self.serve([ok_resp(stop="pause_turn")]))
        self.assertEqual(r["status"], "untranscribed")

    def test_non_json_output(self):
        r = self.run_img(self.serve([ok_resp(content=[{"type": "text", "text": "not json"}])]))
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "output_not_json")

    def test_non_json_body(self):
        r = self.run_img(self.serve([(200, b"<html>")]))
        self.assertEqual(r["status"], "untranscribed")

    def test_missing_or_wrong_fields(self):
        for payload in ({"text": "x"}, {"is_table": True}, {"is_table": "yes", "text": "x"},
                        {"is_table": True, "text": 5}, [1]):
            s = self.serve([ok_resp(content=[{"type": "text", "text": json.dumps(payload)}])])
            r = self.run_img(s)
            self.assertEqual(r["status"], "untranscribed", payload)

    def test_no_text_block(self):
        r = self.run_img(self.serve([ok_resp(content=[{"type": "thinking", "thinking": ""}])]))
        self.assertEqual(r["status"], "untranscribed")

    def test_empty_text_is_still_valid_transcribed(self):
        # 模型誠實回報非表格＋空文字是合法結構；呼叫端依 is_table 決定，本模組不猜測
        r = self.run_img(self.serve([ok_resp(False, "")]))
        self.assertEqual((r["status"], r["is_table"], r["text"]), ("transcribed", False, ""))


class HttpErrorTest(Base):
    def test_abort_statuses(self):
        for code in (401, 402, 403):
            s = self.serve([(code, {"type": "error", "error": {"type": "x", "message": "key %s" % KEY}})])
            r = self.run_img(s)
            self.assertEqual(r["status"], "untranscribed")
            self.assertTrue(r["abort"], code)
            self.assertEqual(r["reason"], "http_%d" % code)
            self.assertEqual(len(s.requests), 1)

    def test_quota_400_aborts_but_plain_400_does_not(self):
        s = self.serve([(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                          "message": "You have reached your workspace spend limit"}})])
        self.assertTrue(self.run_img(s)["abort"])
        s = self.serve([(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad image"}})])
        r = self.run_img(s)
        self.assertEqual(r["status"], "untranscribed")
        self.assertFalse(r["abort"])

    def test_size_limit_400_is_not_quota_and_next_image_still_sent(self):
        # 2026-11-15 審查：訊息含 limit 但非帳務的 400 只讓該張圖失敗，不得 abort
        msg = "image exceeds the maximum size limit of 5 MB"
        s = self.serve([(400, {"type": "error", "error": {"type": "invalid_request_error", "message": msg}}),
                        ok_resp(True, "ok|1")])
        r1 = self.run_img(s)
        self.assertEqual(r1["status"], "untranscribed")
        self.assertFalse(r1["abort"])
        r2 = self.run_img(s)                                   # 下一張仍會被送出
        self.assertEqual(r2["status"], "transcribed")
        self.assertEqual(len(s.requests), 2)
        self.assertNotIn("limit", at._QUOTA_HINTS)

    def test_billing_style_400_variants_still_abort(self):
        for msg in ("Your credit balance is too low", "billing issue", "usage limit reached",
                    "monthly quota exceeded"):
            s = self.serve([(400, {"type": "error", "error": {"type": "invalid_request_error", "message": msg}})])
            self.assertTrue(self.run_img(s)["abort"], msg)

    def test_429_retry_then_success(self):
        s = self.serve([(429, {}), (529, {}), ok_resp(True, "ok")])
        r = self.run_img(s)
        self.assertEqual(r["status"], "transcribed")
        self.assertEqual(len(s.requests), 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_429_exhausted(self):
        s = self.serve([(429, {})])
        r = self.run_img(s)
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "http_429")
        self.assertFalse(r["abort"])
        self.assertEqual(len(s.requests), 3)   # 1 次＋重試 2 次
        self.assertEqual(len(self.sleeps), 2)

    def test_500_and_504_retry(self):
        for code in (500, 504):
            s = self.serve([(code, {})])
            r = self.run_img(s)
            self.assertEqual(r["reason"], "http_%d" % code)
            self.assertEqual(len(s.requests), 3)

    def test_other_status_no_retry(self):
        s = self.serve([(413, {})])
        r = self.run_img(s)
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(len(s.requests), 1)
        self.assertFalse(r["abort"])

    def test_timeout(self):
        s = self.serve([("sleep", 1.5)])
        r = self.run_img(s, timeout=0.3)
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(r["reason"], "timeout")
        self.assertFalse(r["abort"])
        self.assertEqual(len(s.requests), 1)

    def test_connection_refused(self):
        s = FakeServer([ok_resp()])
        url = s.url
        s.close()
        r = at.transcribe_image([PNG], get_secret=self.get_secret, api_url=url, sleeper=self.sleeps.append)
        self.assertEqual(r["status"], "untranscribed")
        self.assertFalse(r["abort"])


class KeyTest(Base):
    def test_missing_key_aborts_no_request(self):
        def nokey(account, service=None):
            raise keychain_secrets.SecretNotFound("找不到 vision-api-key")
        s = self.serve([ok_resp()])
        r = at.transcribe_image([PNG], get_secret=nokey, api_url=s.url)
        self.assertEqual(r["status"], "untranscribed")
        self.assertTrue(r["abort"])
        self.assertEqual(len(s.requests), 0)

    def test_no_tiles_never_reads_secret(self):
        r = at.transcribe_image([], get_secret=self.get_secret)
        self.assertEqual(r["status"], "untranscribed")
        self.assertEqual(self.secret_calls, [])

    def test_key_never_leaks(self):
        out, err = io.StringIO(), io.StringIO()
        logger = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        old_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        collected = []
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                for responses in ([(401, {"error": {"message": "bad key " + KEY}})],
                                  [(500, {"error": {"message": KEY}})],
                                  [ok_resp(stop="refusal")],
                                  [(200, ("garbage " + KEY).encode())],
                                  [ok_resp(content=[{"type": "text", "text": "x " + KEY}])],
                                  [("sleep", 1.0)]):
                    s = self.serve(responses)
                    collected.append(repr(self.run_img(s, timeout=0.3)))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        for blob in collected + [out.getvalue(), err.getvalue(), stream.getvalue()]:
            self.assertNotIn(KEY, blob)
            self.assertNotIn("FAKE-KEY", blob)


class MultiTileTest(Base):
    def test_context_and_merge_dedupe(self):
        s = self.serve([ok_resp(True, "表頭|值\nr1|1\nr2|2\nr3|3\nr4|4"),
                        ok_resp(True, "r3|3\nr4|4\nr5|5")])
        r = self.run_img(s, tiles=(PNG, JPG))
        self.assertEqual(r["status"], "transcribed")
        self.assertEqual(r["text"], "表頭|值\nr1|1\nr2|2\nr3|3\nr4|4\nr5|5")
        first = s.requests[0][1]["messages"][0]["content"][1]["text"]
        second = s.requests[1][1]["messages"][0]["content"][1]["text"]
        self.assertNotIn("上一片", first)
        self.assertIn("上一片", second)
        self.assertIn("表頭|值", second)
        self.assertIn("r3|3", second)
        self.assertIn("r4|4", second)
        self.assertNotIn("r1|1", second)
        self.assertIn("略過", second)
        self.assertEqual(len(self.secret_calls), 1)   # 金鑰只讀一次

    def test_injected_merge(self):
        s = self.serve([ok_resp(True, "a"), ok_resp(False, "b")])
        r = self.run_img(s, tiles=(PNG, PNG), merge=lambda ts: "+".join(ts))
        self.assertEqual(r["text"], "a+b")
        self.assertTrue(r["is_table"])

    def test_later_tile_failure_discards_all(self):
        s = self.serve([ok_resp(True, "a"), ok_resp(stop="refusal")])
        r = self.run_img(s, tiles=(PNG, PNG, PNG))
        self.assertEqual(r["status"], "untranscribed")
        self.assertIsNone(r["text"])
        self.assertEqual(len(s.requests), 2)   # 失敗後不再送後續切片

    def test_abort_propagates_and_stops(self):
        s = self.serve([ok_resp(True, "a"), (401, {})])
        r = self.run_img(s, tiles=(PNG, PNG, PNG))
        self.assertTrue(r["abort"])
        self.assertEqual(len(s.requests), 2)

    def test_default_merge_unit(self):
        self.assertEqual(at.default_merge(["a\nb\nc", "b\nc\nd", "x"]), "a\nb\nc\nd\nx")
        self.assertEqual(at.default_merge(["a"]), "a")
        self.assertEqual(at.context_from_text("h\n1\n2\n3"), "h\n2\n3")
        self.assertEqual(at.context_from_text(""), "")


if __name__ == "__main__":
    unittest.main()
