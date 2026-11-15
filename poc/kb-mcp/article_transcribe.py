"""表格圖轉寫：以 urllib 呼叫視覺模型 HTTP API（010 T036，FR-016／017，research R5）。

設計重點：
- 僅標準庫、Python 3.9 相容；不裝 SDK（理由見 research R5）。
- 模型 ID、API 版本、max_tokens、timeout 的依據：research R5 末尾「T033 官方文件查證（2026-11-15）」。
- 請求只含 model／max_tokens／messages／output_config；**絕不送** thinking／temperature／top_p／top_k
  （API 版本 2026-10-21 起 sampling 三參數一律 400；thinking 省略＝adaptive，以 effort=low 降低成本）。
- 回應處理順序：先查 stop_reason（官方未明述 refusal／max_tokens 時輸出是否合 schema，不可信任），
  再自行 json.loads 並驗證 is_table(bool)／text(str)。任何失敗一律 untranscribed，
  **不以空白或猜測值充數**（FR-017）。
- 金鑰只在「真的要送請求」時才讀（圖片清單為空不讀；開關關閉時呼叫端根本不呼叫本模組，T038）。
  金鑰絕不寫入日誌、例外、回傳值；reason 只用固定代碼，並再過一次 safe_error 脫敏。
- 本模組不 import article_image_tiles；多切片的合併函式由呼叫端注入（T037 接線）。
"""
import base64
import json
import logging
import socket
import urllib.error
import urllib.request

import keychain_secrets
from investanchors_redact import safe_error

log = logging.getLogger("article_transcribe")

# 以下常數依據 research R5「T033 官方文件查證（2026-11-15）」。
TRANSCRIBE_MODEL = "claude-haiku-5-5"
API_VERSION = "2026-10-21"
API_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 16000          # 思考 token 計入 max_tokens，留足餘裕
TIMEOUT_SECONDS = 120
EFFORT = "low"
KEY_ACCOUNT = "vision-api-key"

MAX_RETRIES = 2                       # 429／500／529／504 最多再試 2 次
RETRY_STATUSES = (429, 500, 529, 504)
BACKOFF_SECONDS = (2, 5)
ABORT_STATUSES = (401, 402, 403)
_QUOTA_HINTS = ("credit", "billing", "spend", "usage limit", "spending limit", "quota", "balance", "limit")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"is_table": {"type": "boolean"}, "text": {"type": "string"}},
    "required": ["is_table", "text"],
    "additionalProperties": False,
}

PROMPT_BASE = (
    "請把這張圖中「可見」的數字與文字完整轉寫成純文字。若是表格，每列一行、欄位以 | 分隔，保留表頭。"
    "只轉寫看得到的內容，不要推測、不要補值、不要加說明；看不清楚的格子一律寫 ?。"
    "同時判斷這張圖是否為表格。以 JSON 回覆：{\"is_table\": 布林值, \"text\": 轉寫文字}。"
)
PROMPT_CONTEXT = (
    "\n\n這是同一張長圖的後續切片，與上一片有重疊。上一片的表頭與最後 2 列如下（僅供對照，不要重複轉寫）：\n"
    "%s\n若本片頂端的列已出現在上述內容中，請略過這些重複列，只轉寫新的列。"
)


def _media_type(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_request_body(image_bytes, media_type, prev_context=None, model=None):
    """組請求 body：base64 圖片區塊在前、文字提示在後；不含 thinking／temperature／top_p／top_k。"""
    prompt = PROMPT_BASE
    if prev_context:
        prompt += PROMPT_CONTEXT % prev_context
    return {
        "model": model or TRANSCRIBE_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode("ascii")}},
                {"type": "text", "text": prompt},
            ],
        }],
        "output_config": {
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            "effort": EFFORT,
        },
    }


def _result(status, reason=None, is_table=None, text=None, abort=False, model=None):
    return {"status": status, "is_table": is_table, "text": text,
            "model": model or TRANSCRIBE_MODEL, "reason": reason, "abort": abort}


def _fail(reason, api_key=None, abort=False, model=None):
    return _result("untranscribed", reason=safe_error(reason, [api_key]), abort=abort, model=model)


def _looks_like_quota(err_body):
    try:
        msg = str(json.loads(err_body).get("error", {}).get("message", "")).lower()
    except (ValueError, AttributeError):
        return False
    return any(h in msg for h in _QUOTA_HINTS)


def _parse_response(raw, api_key, model):
    try:
        resp = json.loads(raw)
    except ValueError:
        return _fail("bad_response_json", api_key, model=model)
    if not isinstance(resp, dict):
        return _fail("bad_response_json", api_key, model=model)
    stop = resp.get("stop_reason")
    if stop != "end_turn":
        # 先查 stop_reason：refusal／max_tokens／其他一律不採用任何輸出
        log.warning("轉寫 stop_reason=%s，標 untranscribed", safe_error(stop))
        return _fail("stop_reason:%s" % stop, api_key, model=model)
    texts = [b.get("text") for b in (resp.get("content") or [])
             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    if not texts:
        return _fail("no_text_block", api_key, model=model)
    try:
        out = json.loads(texts[0])
    except ValueError:
        return _fail("output_not_json", api_key, model=model)
    if (not isinstance(out, dict) or not isinstance(out.get("is_table"), bool)
            or not isinstance(out.get("text"), str)):
        return _fail("output_missing_fields", api_key, model=model)
    return _result("transcribed", is_table=out["is_table"], text=out["text"], model=model)


def transcribe_tile(image_bytes, api_key, prev_context=None, api_url=None, model=None,
                    timeout=None, sleeper=None):
    """單一切片（或單張圖）的請求／回應處理。回傳 dict：
    {status, is_table, text, model, reason, abort}；永不丟例外、永不含金鑰。"""
    model = model or TRANSCRIBE_MODEL
    media = _media_type(image_bytes or b"")
    if media is None:
        return _fail("unsupported_image_format", api_key, model=model)
    if sleeper is None:
        import time
        sleeper = time.sleep
    body = json.dumps(build_request_body(image_bytes, media, prev_context, model)).encode("utf-8")
    headers = {"content-type": "application/json", "anthropic-version": API_VERSION,
               "x-api-key": api_key}
    attempt = 0
    while True:
        req = urllib.request.Request(api_url or API_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT_SECONDS) as resp:
                raw = resp.read()
            return _parse_response(raw, api_key, model)
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                err_body = e.read()
            except Exception:
                err_body = b""
            if code in ABORT_STATUSES or (code == 400 and _looks_like_quota(err_body)):
                return _fail("http_%d" % code, api_key, abort=True, model=model)
            if code in RETRY_STATUSES and attempt < MAX_RETRIES:
                sleeper(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                attempt += 1
                continue
            return _fail("http_%d" % code, api_key, model=model)
        except (socket.timeout, TimeoutError):
            return _fail("timeout", api_key, model=model)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                return _fail("timeout", api_key, model=model)
            return _fail("network_error", api_key, model=model)
        except OSError:
            return _fail("network_error", api_key, model=model)


def _rows(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def context_from_text(text):
    """上一片的表頭（第一個非空列）與最後 2 列，作為下一片提示詞的上下文。"""
    rows = _rows(text)
    if not rows:
        return ""
    picked = [rows[0]] + [r for r in rows[-2:] if r is not rows[0]]
    return "\n".join(picked)


def default_merge(texts):
    """預設合併：依序串接，並去掉下一片開頭與前文結尾重疊的列（最長重疊優先）。"""
    merged = []
    for t in texts:
        rows = _rows(t)
        k = min(len(merged), len(rows))
        while k > 0 and merged[-k:] != rows[:k]:
            k -= 1
        merged.extend(rows[k:])
    return "\n".join(merged)


def transcribe_image(tiles, get_secret=None, api_url=None, model=None, timeout=None,
                     sleeper=None, merge=None):
    """轉寫一張圖的所有切片（bytes 清單，由上而下）。

    - tiles 為空：直接回 untranscribed，**不呼叫 get_secret**。
    - 逐片送；第 2 片起附上一片的表頭與最後 2 列上下文。任一片失敗 → 整張圖 untranscribed
      （不採用部分結果）；回傳 abort=True 時呼叫端應停止本次執行後續圖。
    - merge(texts)->str 可注入（T037 接 article_image_tiles.merge_tile_texts）；預設 default_merge。
    回傳 {status, is_table, text, model, reason, abort}。"""
    model = model or TRANSCRIBE_MODEL
    if not tiles:
        return _fail("no_tiles", model=model)
    if get_secret is None:
        get_secret = keychain_secrets.get_secret
    try:
        api_key = get_secret(KEY_ACCOUNT, service=keychain_secrets.INVESTANCHORS_SERVICE)
    except keychain_secrets.SecretNotFound:
        return _fail("no_api_key", abort=True, model=model)
    except Exception:
        return _fail("key_read_error", abort=True, model=model)
    texts, any_table, prev = [], False, None
    for tile in tiles:
        r = transcribe_tile(tile, api_key, prev_context=prev, api_url=api_url, model=model,
                            timeout=timeout, sleeper=sleeper)
        if r["status"] != "transcribed":
            return r
        any_table = any_table or r["is_table"]
        texts.append(r["text"])
        prev = context_from_text(r["text"]) or None
    try:
        merged = (merge or default_merge)(texts)
    except Exception:
        return _fail("merge_error", api_key, model=model)
    return _result("transcribed", is_table=any_table, text=merged, model=model)
