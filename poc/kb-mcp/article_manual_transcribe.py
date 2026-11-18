"""方案 D：手動轉寫（由 Claude Code／Cline 等 agent 讀圖，免 API 金鑰）——匯出與匯入（010 Phase 10）。

流程（PO 觸發、agent 執行；全程**不呼叫任何外部 API、不讀鑰匙圈、不登入定錨、不連網**）：
  1. `--export-untranscribed`：唯讀開庫，把「未轉寫的圖」整理成一個資料夾
     `<data-dir>/articles_probe/manual-transcribe-<時間>/`（manifest.json、AGENT_GUIDE.md、長圖切片）。
  2. agent 依 AGENT_GUIDE.md 逐張讀圖，寫出 results.json。
  3. `--import-transcription results.json`：嚴格驗證；預設只預覽，`--apply` 才寫入（單一交易、全有或全無）。

安全設計：
- manifest 只放圖片身分與路徑，**不含文章標題與內文**（agent 不需要，也避免外流付費內容）。
- 匯入只認 manifest／資料庫裡真實存在、且 sha256 與目前檔案一致的圖；`model` 必須是 `manual:<agent 名稱>`，
  讓 PO 日後分得出手動與 API 轉寫；轉寫文字拒收控制字元與疑似金鑰／token 的字串。
- 重用 ArticleStore 既有的轉寫欄位（transcription／transcribed_model），不改 schema。
- 錯誤訊息只含 image_id／序號／固定代碼，不回顯轉寫內容。
僅標準庫，Python 3.9 相容。
"""
import datetime
import hashlib
import json
import os
import re
import shutil

import article_image_tiles
import article_store
import article_transcribe
import investanchors_redact

TZ8 = article_store.TZ8
EXPORT_DIRNAME = "articles_probe"
EXPORT_PREFIX = "manual-transcribe-"
MANIFEST_NAME = "manifest.json"
GUIDE_NAME = "AGENT_GUIDE.md"
TILES_DIRNAME = "tiles"
MANIFEST_VERSION = 1
RESULTS_VERSION = 1

DEFAULT_EXPORT_LIMIT = 10
MAX_EXPORT_LIMIT = 100
MODEL_PREFIX = "manual:"
MODEL_RE = re.compile(r"manual:[A-Za-z0-9-]{1,40}")   # 一律用 fullmatch（`$` 會放行結尾換行）
SHA256_RE = re.compile(r"[0-9a-f]{64}")   # 一律用 fullmatch
MAX_TEXT_CHARS = 40000            # 單張圖的轉寫文字上限（8 片長圖的量級已綽綽有餘）
MAX_RESULTS_ITEMS = 200
MAX_RESULTS_FILE_BYTES = 8 * 1000 * 1000
AUDIT_KIND = "manual_transcription_import"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")   # 允許 \n 與 \t；\r 也不收；含 bidi／零寬／格式字元
_TOP_KEYS = {"version", "model", "results"}
_ITEM_KEYS = {"image_id", "sha256", "is_table", "text"}


class ManualTranscribeError(Exception):
    """可預期的拒絕：訊息只含固定說明與 image_id／序號，絕不含轉寫內容。"""


def is_manual_model(model):
    return isinstance(model, str) and model.startswith(MODEL_PREFIX)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_join(data_dir, rel):
    """DB 內相對路徑 → 絕對路徑；解析後必須仍在 data_dir 之下，否則回 None。"""
    root = os.path.realpath(data_dir)
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def build_agent_guide():
    """AGENT_GUIDE.md 內容。規則句子取自 article_transcribe（與 API 轉寫同一套說法）。"""
    return """# 給 agent 的轉寫說明（方案 D：手動轉寫）

你是被 PO 請來把「付費文章裡的表格圖」轉成文字的 agent。只做讀圖與寫出 results.json，其餘什麼都不要做。

## 轉寫規則（與自動 API 轉寫同一套）

{rules}

補充（方案 D 特有）：
- 看不清楚的格子寫 `?`（與 API 轉寫相同）。**不得猜測、不得補數字、不得改寫原圖沒有的資訊、不得加註解或總結。**
- 表格請轉成 Markdown 表格（表頭、`| --- |` 分隔列、每列一行）；非表格但有文字的圖，照樣逐行轉寫可見文字。
- 圖若根本不是表格（照片、純裝飾、logo），`is_table` 填 `false`、`text` 填空字串 `""`。
- 長圖（manifest 內 `is_long=true`）已切成多片（`tiles` 清單，由上而下）。相鄰切片刻意重疊：{overlap}
  請把各片合併成**一張圖一份** `text`，不要因為切片而產生重複列。
- 長圖若 `tile_status` 不是 `ok`（例如本機沒有瀏覽器切不了），請自行把原圖分段檢視（每段至少涵蓋表格的完整列），
  **不可只看被縮小的整張就猜測**；實在看不清楚的格子寫 `?`。

## 作業步驟

1. 讀 `manifest.json`；`items` 內每一項是一張圖。`view_files` 是你要讀的圖檔（短圖＝原圖；長圖＝切片）。
2. 逐項讀圖、轉寫。**每項獨立處理**，不要把不同圖的內容混在一起。
3. 把全部結果寫成同資料夾的 `results.json`（格式如下）。`sha256` 必須原樣抄 manifest 該項的值。
4. 不要修改 manifest.json、不要修改或刪除任何圖檔、不要碰資料庫、不要連網或呼叫任何外部 API。
5. 這些圖片來自付費文章：輸出只留在本資料夾，**不要貼到任何公開或第三方的地方**。

## results.json 格式

```json
{{
  "version": 1,
  "model": "manual:<你的 agent 名稱>",
  "results": [
    {{"image_id": 12, "sha256": "<manifest 內該項的 sha256>", "is_table": true,
      "text": "| 代號 | 營收 |\\n| --- | --- |\\n| 2330 | 98765 |"}},
    {{"image_id": 13, "sha256": "<...>", "is_table": false, "text": ""}}
  ]
}}
```

- `model`：必填，固定以 `manual:` 開頭，後面接你的 agent 名稱，只能用英文字母、數字與連字號 `-`，長度 ≤ 40
  （例：`manual:claude-code`、`manual:cline-sonnet`）。
- `is_table` 為 `true` 時 `text` 不可為空；為 `false` 時 `text` 必須是空字串。
- `text` 長度上限 {max_chars} 字；不得含控制字元（換行 `\\n` 與 Tab 可以）；不得出現任何看起來像金鑰或 token 的字串。
- 不要輸出 manifest 沒有的 `image_id`；不要重複同一個 `image_id`；不要加其他欄位（會被拒收）。
- 寫完後請 PO 執行匯入預覽（預設只預覽、不寫入）：
  `python3 poc/kb-mcp/investanchors_import.py --data-dir <資料目錄> --import-transcription <本資料夾>/results.json`
""".format(rules=article_transcribe.TRANSCRIBE_RULES, overlap=article_transcribe.TILE_OVERLAP_RULE,
           max_chars=MAX_TEXT_CHARS)


# ====================================================================== 匯出

def _unique_dir(base):
    path = base
    n = 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d" % (base, n)
    os.makedirs(path)
    return path


def export_untranscribed(data_dir, limit=DEFAULT_EXPORT_LIMIT, now=None, tiles_runner=None, tile_tmp_root=None):
    """唯讀開庫並產出匯出資料夾。回傳 {out_dir, exported, skipped_missing, skipped_unreadable, long_images,
    tiles_degraded}。庫不存在 → FileNotFoundError（不建庫）。不寫資料庫、不讀鑰匙圈、不連網。"""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_EXPORT_LIMIT:
        raise ManualTranscribeError("--limit 必須是 1～%d 的整數" % MAX_EXPORT_LIMIT)
    store = article_store.ArticleStore.open_readonly(data_dir)
    try:
        candidates = store.images_for_manual_export()
        root = store.data_dir
    finally:
        store.close()

    picked, skipped_missing, skipped_unreadable = [], 0, 0
    for img in candidates:
        if len(picked) >= limit:
            break
        full = _safe_join(root, img["file_path"])
        if full is None or not os.path.isfile(full):
            skipped_missing += 1
            continue
        with open(full, "rb") as f:
            data = f.read()
        size = article_image_tiles.image_size(data)
        if size is None:
            skipped_unreadable += 1
            continue
        picked.append((img, full, size, hashlib.sha256(data).hexdigest()))

    stamp = (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).strftime("%Y%m%d-%H%M%S")
    out_dir = _unique_dir(os.path.join(root, EXPORT_DIRNAME, EXPORT_PREFIX + stamp))
    items, long_n, degraded = [], 0, 0
    for img, full, (w, h), digest in picked:
        is_long = article_image_tiles.is_long_image(w, h)
        long_n += 1 if is_long else 0
        item = {
            "image_id": img["id"], "article_id": img["article_id"], "seq": img["seq"],
            "path": full, "sha256": digest, "width": w, "height": h, "is_long": is_long,
            "transcription_status": img["transcription_status"],
            "tile_status": "not_needed", "tile_reason": None, "tiles": [], "view_files": [full],
        }
        with article_image_tiles.open_tiles(full, runner=tiles_runner, tmp_root=tile_tmp_root) as ts:
            if ts.status != article_image_tiles.STATUS_OK:
                # 降級：切不了（沒有瀏覽器／片數過多…）→ 只給原圖，並在 manifest 明講，agent 須自行分段檢視
                item["tile_status"] = "unavailable"
                item["tile_reason"] = ts.reason
                degraded += 1
            elif not ts.plan.single_whole:
                tdir = os.path.join(out_dir, TILES_DIRNAME)
                os.makedirs(tdir, exist_ok=True)
                tiles = []
                for k, data, _mt in ts.iter_tile_bytes():
                    p = os.path.join(tdir, "%d-%02d.png" % (img["id"], k))
                    with open(p, "wb") as f:
                        f.write(data)
                    tiles.append(p)
                item["tile_status"] = "ok"
                item["tiles"] = tiles
                item["view_files"] = list(tiles)
        items.append(item)

    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).isoformat(),
        "note": "本檔不含文章標題與內文；sha256 為原圖檔的 SHA-256，results.json 須原樣抄回。",
        "items": items,
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, GUIDE_NAME), "w", encoding="utf-8") as f:
        f.write(build_agent_guide())
    return {"out_dir": out_dir, "exported": len(items), "skipped_missing": skipped_missing,
            "skipped_unreadable": skipped_unreadable, "long_images": long_n, "tiles_degraded": degraded}


# ====================================================================== 匯入

def _fail(msg):
    raise ManualTranscribeError(msg)


def _load_json_file(path, what):
    if not os.path.isfile(path):
        _fail("找不到%s檔案" % what)
    if os.path.getsize(path) > MAX_RESULTS_FILE_BYTES:
        _fail("%s檔案過大（上限 %d MB）" % (what, MAX_RESULTS_FILE_BYTES // 1000000))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _fail("%s不是合法的 UTF-8 JSON" % what)


def _load_manifest_shas(results_path):
    """results.json 同資料夾若有 manifest.json：回傳 {image_id: sha256}；沒有則 None（只驗資料庫與檔案）。"""
    mpath = os.path.join(os.path.dirname(os.path.abspath(results_path)), MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return None
    data = _load_json_file(mpath, "manifest")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        _fail("manifest 格式不正確（缺 items）")
    out = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("image_id"), int) and isinstance(it.get("sha256"), str):
            out[it["image_id"]] = it["sha256"]
    return out


def validate_results(results_path, store, overwrite=False):
    """嚴格驗證 results.json 並對照資料庫。回傳 plan：
    {model, rows:[(article_id, seq, status, text, model, is_table)], details:[(image_id, article_id, seq, len)],
     skipped_done:[image_id]}。任何問題 → ManualTranscribeError（整批拒絕、不寫任何東西）。"""
    data = _load_json_file(results_path, "results")
    if not isinstance(data, dict):
        _fail("results 頂層必須是物件")
    extra = set(data) - _TOP_KEYS
    if extra:
        _fail("results 含未知的頂層欄位（%d 個）" % len(extra))
    if data.get("version") != RESULTS_VERSION or isinstance(data.get("version"), bool):
        _fail("results.version 必須是 %d" % RESULTS_VERSION)
    model = data.get("model")
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        _fail("model 必填，格式必須是 manual:<agent 名稱>（英數與連字號、≤40 字）")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        _fail("results.results 必須是非空陣列")
    if len(results) > MAX_RESULTS_ITEMS:
        _fail("一次最多 %d 筆" % MAX_RESULTS_ITEMS)
    manifest_shas = _load_manifest_shas(results_path)

    rows, details, skipped_done, seen = [], [], [], set()
    for idx, it in enumerate(results, 1):
        tag = "第 %d 筆" % idx
        if not isinstance(it, dict):
            _fail("%s：必須是物件" % tag)
        if set(it) - _ITEM_KEYS or _ITEM_KEYS - set(it):
            _fail("%s：欄位必須剛好是 image_id／sha256／is_table／text" % tag)
        iid = it["image_id"]
        if not isinstance(iid, int) or isinstance(iid, bool):
            _fail("%s：image_id 必須是整數" % tag)
        tag = "%s（image_id=%d）" % (tag, iid)
        if iid in seen:
            _fail("%s：image_id 重複" % tag)
        seen.add(iid)
        sha = it["sha256"]
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            _fail("%s：sha256 格式不正確（64 位小寫十六進位）" % tag)
        is_table, text = it["is_table"], it["text"]
        if not isinstance(is_table, bool):
            _fail("%s：is_table 必須是布林值" % tag)
        if not isinstance(text, str):
            _fail("%s：text 必須是字串" % tag)
        if len(text) > MAX_TEXT_CHARS:
            _fail("%s：text 超過上限 %d 字" % (tag, MAX_TEXT_CHARS))
        if _CONTROL_RE.search(text) or "\r" in text:
            _fail("%s：text 含控制字元" % tag)
        if investanchors_redact.secret_like(text):
            _fail("%s：text 含疑似金鑰／token 的字串，拒收" % tag)
        if is_table and not text.strip():
            _fail("%s：is_table=true 但 text 為空" % tag)
        if not is_table and text:
            _fail("%s：is_table=false 時 text 必須是空字串" % tag)

        img = store.get_image_by_id(iid)
        if img is None:
            _fail("%s：資料庫沒有這張圖" % tag)
        if img["article_status"] == "abandoned":
            _fail("%s：所屬文章已 abandoned" % tag)
        if manifest_shas is not None:
            if iid not in manifest_shas:
                _fail("%s：不在同資料夾的 manifest.json 內" % tag)
            if manifest_shas[iid] != sha:
                _fail("%s：sha256 與 manifest 不一致" % tag)
        full = _safe_join(store.data_dir, img["file_path"]) if img.get("file_path") else None
        if full is None or not os.path.isfile(full):
            _fail("%s：本機圖檔不存在" % tag)
        if sha256_file(full) != sha:
            _fail("%s：sha256 與目前圖檔不一致（圖檔可能已變動）" % tag)

        if img["transcription_status"] in ("done", "not_table") and not overwrite:
            skipped_done.append(iid)
            continue
        status = "done" if is_table else "not_table"
        rows.append((img["article_id"], img["seq"], status, text if is_table else None, model, is_table))
        details.append((iid, img["article_id"], img["seq"], len(text)))
    return {"model": model, "rows": rows, "details": details, "skipped_done": skipped_done}


def apply_plan(store, plan, now=None):
    """單一交易寫入並寫一筆稽核（只含數量）。"""
    stamp = (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).strftime("%H%M%S")
    key = "%s written=%d skipped=%d model=%s" % (stamp, len(plan["rows"]), len(plan["skipped_done"]), plan["model"])
    store.apply_transcription_batch(plan["rows"], audit_kind=AUDIT_KIND, audit_key=key)
