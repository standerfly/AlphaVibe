"""轉寫驗證等級：驗證匯入／PO 核對／抽查任務匯出（010 Phase 12，clarification-log Q-028）。

背景：資料錯誤是最嚴重的錯。每張圖的轉寫有一個驗證等級（`transcription_verification` 表；沒有列＝unverified）：
  unverified    預設；任何新轉寫（手動 D、API）寫入時都是它
  flagged       任一檢核發現疑慮；**自動驗證匯入不能把它轉回去**，只能由 PO `--mark-reviewed` 或轉寫被改寫後重驗
  cross_checked 數字家族（compare-d-c／arithmetic／body-crosscheck 任一）與文字家族（agent-spot-check）都檢核通過；
                只過一個家族維持 unverified（記 checks_passed）
  reviewed      PO 本人逐格核對確認（**只有 `--mark-reviewed` 會寫入**）
只有 cross_checked／reviewed 的轉寫文字納入 `search_articles`；unverified／flagged 只在單篇 `get_article` 顯示並附警告。

本模組全部**零網路、零鑰匙圈、不登入、不取信**；匯出只讀庫與圖片檔，匯入只讀 verification.json 與圖檔 sha256。
錯誤訊息與輸出只含固定說明、image_id、數量，**不回顯 issues 內容、不含文章標題與內文**。
僅標準庫，Python 3.9 相容。
"""
import datetime
import hashlib
import json
import os
import re

import article_image_tiles
import article_manual_transcribe as M
import article_store
import investanchors_redact

TZ8 = article_store.TZ8
VERIFICATION_VERSION = 1
EXPORT_DIRNAME = M.EXPORT_DIRNAME
EXPORT_PREFIX = "verify-task-"
MANIFEST_NAME = "manifest.json"
GUIDE_NAME = "VERIFY_GUIDE.md"
TRANSCRIPTS_DIRNAME = "transcriptions"
DEFAULT_EXPORT_LIMIT = M.DEFAULT_EXPORT_LIMIT
MAX_EXPORT_LIMIT = M.MAX_EXPORT_LIMIT
MAX_RESULTS_ITEMS = M.MAX_RESULTS_ITEMS
MAX_ISSUES_PER_IMAGE = 200
MAX_WHERE, MAX_FOUND, MAX_EXPECTED = 80, 200, 200
STORED_CELL_TEXT = 80               # 資料庫 flagged_cells 內 found／expected 的長度（摘要，不存大量文字）
STORED_CELLS_MAX = 50
ISSUE_KINDS = ("truncated", "wrong-number", "missing", "extra", "other", "source-typo")
SOURCE_TYPO_KIND = "source-typo"      # 原圖本身的筆誤、轉寫已忠實照抄：全部都是它時視同 ok（不 flagged），但留記錄並在 get_article 顯示
MAX_SOURCE_TYPO_PER_IMAGE = 20
VERIFIER_RE = re.compile(r"[A-Za-z0-9-]{1,40}")        # 一律 fullmatch
MAX_REVIEW_IDS = 200
AUDIT_KIND_IMPORT = "transcription_verification_import"
AUDIT_KIND_REVIEWED = "transcription_mark_reviewed"
_TOP_KEYS = {"version", "verifier", "method", "results"}
_ITEM_KEYS_REQUIRED = {"image_id", "sha256", "transcription_sha256", "verdict"}
_ITEM_KEYS = _ITEM_KEYS_REQUIRED | {"issues"}
_ISSUE_KEYS_REQUIRED = {"where", "found", "kind"}
_ISSUE_KEYS = _ISSUE_KEYS_REQUIRED | {"expected"}
SKIP_REASON_TEXT = {
    "reviewed": "PO 已核對（自動驗證不動它）",
    "flagged-needs-po": "有疑慮（flagged）的轉寫須由 PO 核對（--mark-reviewed）或重新轉寫後重驗，自動驗證不能清除",
    "not-table-ok": "非表格圖（無轉寫文字可驗證）",
}


class VerificationError(Exception):
    """可預期的拒絕：訊息只含固定說明與 image_id／序號，絕不含 issues 或轉寫內容。"""


def _fail(msg):
    raise VerificationError(msg)


def _bad_text(s):
    """單行短欄位：拒收控制字元（含換行、Tab、bidi／零寬）與疑似金鑰。"""
    return bool(M._CONTROL_RE.search(s)) or "\n" in s or "\r" in s or "\t" in s or investanchors_redact.secret_like(s)


# ====================================================================== 匯入驗證

def validate_verification(path, store):
    """嚴格驗證 verification.json 並對照資料庫。回傳 plan：
    {verifier, method, entries:[{image_id, verdict, method, verifier, note, cells, transcription_sha256}],
     details:[(image_id, outcome_kind, n_issues)], skipped:{reason:[image_id]},
     outcome:{"cross_checked":[ids], "flagged":[ids], "partial":[ids]}, typo:[ids]}
    （一張圖的 issues 若**全部**是 source-typo，verdict 視同 ok 並帶 typos 記錄；只要有任何一項不是 source-typo 就照舊 flagged）
    （partial＝ok 但數字／文字兩個檢核家族尚未都通過，狀態不會變成 cross_checked）
    entries 只含「實際要寫」的筆；skipped 含預覽時就可判定略過的（非表格 ok、reviewed、flagged 須 PO 核對）。
    任何問題 → VerificationError（整批拒絕、不寫任何東西）。store 可為唯讀。"""
    data = M._load_json_file(path, "verification")
    if not isinstance(data, dict):
        _fail("verification 頂層必須是物件")
    if set(data) - _TOP_KEYS or _TOP_KEYS - set(data):
        _fail("verification 頂層欄位必須剛好是 version／verifier／method／results")
    if data["version"] != VERIFICATION_VERSION or isinstance(data["version"], bool):
        _fail("verification.version 必須是 %d" % VERIFICATION_VERSION)
    verifier = data["verifier"]
    if not isinstance(verifier, str) or not VERIFIER_RE.fullmatch(verifier):
        _fail("verifier 必填，只能用英數與連字號、≤40 字")
    method = data["method"]
    if not isinstance(method, str) or method not in article_store.VERIFICATION_METHODS:
        _fail("method 必須是白名單之一：%s" % "、".join(article_store.VERIFICATION_METHODS))
    results = data["results"]
    if not isinstance(results, list) or not results:
        _fail("verification.results 必須是非空陣列")
    if len(results) > MAX_RESULTS_ITEMS:
        _fail("一次最多 %d 筆" % MAX_RESULTS_ITEMS)
    manifest_shas = M._load_manifest_shas(path)
    manifest_tshas = _load_manifest_tshas(path) if manifest_shas is not None else {}

    entries, details, skipped, seen, typo_ids = [], [], {}, set(), []
    outcome = {"cross_checked": [], "flagged": [], "partial": []}
    for idx, it in enumerate(results, 1):
        tag = "第 %d 筆" % idx
        if not isinstance(it, dict):
            _fail("%s：必須是物件" % tag)
        if set(it) - _ITEM_KEYS or _ITEM_KEYS_REQUIRED - set(it):
            _fail("%s：欄位必須是 image_id／sha256／transcription_sha256／verdict（verdict=issues 時另有 issues）" % tag)
        iid = it["image_id"]
        if not isinstance(iid, int) or isinstance(iid, bool):
            _fail("%s：image_id 必須是整數" % tag)
        tag = "%s（image_id=%d）" % (tag, iid)
        if iid in seen:
            _fail("%s：image_id 重複" % tag)
        seen.add(iid)
        sha = it["sha256"]
        if not isinstance(sha, str) or not M.SHA256_RE.fullmatch(sha):
            _fail("%s：sha256 格式不正確（64 位小寫十六進位）" % tag)
        tsha = it["transcription_sha256"]
        if not isinstance(tsha, str) or not M.SHA256_RE.fullmatch(tsha):
            _fail("%s：transcription_sha256 格式不正確（64 位小寫十六進位）" % tag)
        verdict = it["verdict"]
        if verdict not in ("ok", "issues") or not isinstance(verdict, str):
            _fail("%s：verdict 必須是 ok 或 issues" % tag)
        issues = it.get("issues")
        if verdict == "ok":
            if issues not in (None, []):
                _fail("%s：verdict=ok 時不可帶 issues" % tag)
            issues = []
        else:
            if not isinstance(issues, list) or not issues:
                _fail("%s：verdict=issues 時 issues 必須是非空陣列" % tag)
            if len(issues) > MAX_ISSUES_PER_IMAGE:
                _fail("%s：issues 最多 %d 項" % (tag, MAX_ISSUES_PER_IMAGE))
            for j, iss in enumerate(issues, 1):
                _check_issue(iss, "%s 的第 %d 項疑慮" % (tag, j))
            if sum(1 for iss in issues if iss["kind"] == SOURCE_TYPO_KIND) > MAX_SOURCE_TYPO_PER_IMAGE:
                _fail("%s：source-typo 每張圖最多 %d 項" % (tag, MAX_SOURCE_TYPO_PER_IMAGE))

        img = store.get_image_by_id(iid)
        if img is None:
            _fail("%s：資料庫沒有這張圖" % tag)
        if img["article_status"] == "abandoned":
            _fail("%s：所屬文章已 abandoned" % tag)
        if img["transcription_status"] == "untranscribed":
            _fail("%s：這張圖尚未轉寫，沒有可驗證的內容" % tag)
        if manifest_shas is not None:
            if iid not in manifest_shas:
                _fail("%s：不在同資料夾的 manifest.json 內" % tag)
            if manifest_shas[iid] != sha:
                _fail("%s：sha256 與 manifest 不一致" % tag)
            if iid in manifest_tshas and manifest_tshas[iid] != tsha:      # manifest 缺此欄＝略過（相容）
                _fail("%s：transcription_sha256 與 manifest 不一致" % tag)
        full = M._safe_join(store.data_dir, img["file_path"]) if img.get("file_path") else None
        if full is None or not os.path.isfile(full):
            _fail("%s：本機圖檔不存在" % tag)
        if M.sha256_file(full) != sha:
            _fail("%s：sha256 與目前圖檔不一致（圖檔可能已變動）" % tag)
        if article_store.transcription_sha256(img.get("transcription")) != tsha:
            _fail("%s：轉寫在抽查後已被改寫（或抽查的文字尚未匯入資料庫），須重新抽查" % tag)

        typos = None
        if verdict == "issues" and all(iss["kind"] == SOURCE_TYPO_KIND for iss in issues):
            # 只有原圖筆誤：轉寫忠實，視同 ok（家族記為通過），但留下記錄（get_article 會顯示提示）
            typos = [dict({"where": iss["where"], "found": iss["found"][:STORED_CELL_TEXT]},
                          **({"expected": iss["expected"][:STORED_CELL_TEXT]} if iss.get("expected") else {}))
                     for iss in issues[:MAX_SOURCE_TYPO_PER_IMAGE]]
            verdict, issues = "ok", []
        if img["transcription_status"] == "not_table" and verdict == "ok":
            skipped.setdefault("not-table-ok", []).append(iid)         # 非表格圖沒有轉寫文字可「驗證通過」
            continue
        cur = store.get_verification(iid)
        plan = article_store.plan_verification_transition(cur, verdict, method)
        if plan["action"] == "skip":
            skipped.setdefault(plan["reason"], []).append(iid)
            continue
        kind = "flagged" if verdict == "issues" else ("cross_checked" if plan["status"] == "cross_checked" else "partial")
        outcome[kind].append(iid)
        entries.append({"image_id": iid, "verdict": verdict, "method": method, "verifier": verifier,
                        "note": _build_note(issues, method, verifier) if issues else None,
                        "cells": _build_cells(issues) if issues else None, "transcription_sha256": tsha,
                        "typos": typos})
        if typos:
            typo_ids.append(iid)
        details.append((iid, kind, len(issues)))
    return {"verifier": verifier, "method": method, "entries": entries, "details": details,
            "skipped": skipped, "outcome": outcome, "typo": typo_ids}


def _load_manifest_tshas(results_path):
    """同資料夾 manifest.json 內有 transcription_sha256 的項目：{image_id: 值}（缺此欄者不在結果內）。"""
    data = M._load_json_file(os.path.join(os.path.dirname(os.path.abspath(results_path)), MANIFEST_NAME), "manifest")
    out = {}
    for it in (data.get("items") if isinstance(data, dict) else None) or []:
        if isinstance(it, dict) and isinstance(it.get("image_id"), int) and isinstance(it.get("transcription_sha256"), str):
            out[it["image_id"]] = it["transcription_sha256"]
    return out


def _check_issue(iss, tag):
    if not isinstance(iss, dict):
        _fail("%s：必須是物件" % tag)
    if set(iss) - _ISSUE_KEYS or _ISSUE_KEYS_REQUIRED - set(iss):
        _fail("%s：欄位必須是 where／found／kind（expected 可選）" % tag)
    for key, limit, required in (("where", MAX_WHERE, True), ("found", MAX_FOUND, False), ("expected", MAX_EXPECTED, False)):
        if key not in iss:
            continue
        v = iss[key]
        if not isinstance(v, str):
            _fail("%s：%s 必須是字串" % (tag, key))
        if len(v) > limit:
            _fail("%s：%s 超過 %d 字" % (tag, key, limit))
        if required and not v.strip():
            _fail("%s：%s 不可為空" % (tag, key))
        if _bad_text(v):
            _fail("%s：%s 含控制字元、換行或疑似金鑰／token 的字串，拒收" % (tag, key))
    if iss["kind"] not in ISSUE_KINDS:
        _fail("%s：kind 必須是 %s 之一" % (tag, "／".join(ISSUE_KINDS)))


def _build_note(issues, method, verifier):
    kinds = {}
    for iss in issues:
        kinds[iss["kind"]] = kinds.get(iss["kind"], 0) + 1
    detail = "、".join("%s×%d" % (k, kinds[k]) for k in ISSUE_KINDS if k in kinds)
    return "發現 %d 項疑慮（%s）；驗證來源：%s（%s）" % (len(issues), detail, method, verifier)


def _build_cells(issues):
    """存進資料庫的疑慮摘要：只含位置與簡短描述（found／expected 截短），最多 STORED_CELLS_MAX 項；不含標題與全文。"""
    out = []
    for iss in issues[:STORED_CELLS_MAX]:
        c = {"where": iss["where"], "kind": iss["kind"], "found": iss["found"][:STORED_CELL_TEXT]}
        if iss.get("expected"):
            c["expected"] = iss["expected"][:STORED_CELL_TEXT]
        out.append(c)
    return json.dumps(out, ensure_ascii=False)


def _audit_key_for(plan, now):
    stamp = (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).strftime("%H%M%S")

    def key(result):
        skipped = sum(len(v) for v in result["skipped"].values())
        return "%s method=%s cross_checked=%d partial=%d flagged=%d source_typo=%d skipped=%d" % (
            stamp, plan["method"], len(result["cross_checked"]), len(result["partial"]), len(result["flagged"]),
            len(result["typo"]), skipped)
    return key


def apply_verification(store, plan, now=None):
    """單一交易寫入並寫一筆稽核（只含數量與 method）。回傳 store.apply_verification_batch 的結果。"""
    return store.apply_verification_batch(plan["entries"], audit_kind=AUDIT_KIND_IMPORT,
                                          audit_key=_audit_key_for(plan, now))


# ====================================================================== PO 核對

def parse_image_ids(text):
    """'12,13,15' → [12,13,15]；非正整數、重複、空項目、過多 → VerificationError。"""
    if not isinstance(text, str) or not text.strip():
        _fail("--mark-reviewed 需要至少一個 image_id（以逗號分隔）")
    ids = []
    for part in text.split(","):
        part = part.strip()
        if not re.fullmatch(r"[0-9]{1,9}", part) or int(part) < 1:
            _fail("--mark-reviewed 的 image_id 必須是以逗號分隔的正整數")
        ids.append(int(part))
    if len(ids) != len(set(ids)):
        _fail("--mark-reviewed 的 image_id 有重複")
    if len(ids) > MAX_REVIEW_IDS:
        _fail("一次最多標記 %d 張" % MAX_REVIEW_IDS)
    return ids


def plan_mark_reviewed(ids, store):
    """預覽／驗證：每張圖必須存在、已轉寫（done）、所屬文章非 abandoned。回傳 {"ids":[...], "was":{status:[ids]}}。"""
    was = {}
    for iid in ids:
        img = store.get_image_by_id(iid)
        if img is None:
            _fail("image_id=%d：資料庫沒有這張圖" % iid)
        if img["article_status"] == "abandoned":
            _fail("image_id=%d：所屬文章已 abandoned" % iid)
        if img["transcription_status"] != "done":
            _fail("image_id=%d：尚未轉寫（done），無法標記為已核對" % iid)
        cur = store.get_verification(iid)
        was.setdefault(cur["status"] if cur else "unverified", []).append(iid)
    return {"ids": list(ids), "was": was}


def apply_mark_reviewed(store, ids, now=None):
    stamp = (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).strftime("%H%M%S")
    return store.apply_mark_reviewed(
        ids, audit_kind=AUDIT_KIND_REVIEWED,
        audit_key=lambda r: "%s reviewed=%d flagged_before=%d" % (stamp, len(r["reviewed"]), len(r["was"].get("flagged", []))))


# ====================================================================== 抽查任務匯出

def build_verify_guide():
    """VERIFY_GUIDE.md：給獨立 agent（Cline、Claude Code 等）的抽查指示。"""
    return """# 給 agent 的轉寫抽查說明（轉寫驗證等級，Q-028）

你是被 PO 請來**獨立檢查「表格圖轉寫」有沒有錯**的 agent。你只做兩件事：對照原圖檢查、寫出 verification.json。
**你不是來重新轉寫的。** 不得修改任何轉寫檔、manifest、圖檔；不要碰資料庫；不要連網或呼叫外部 API。

## 為什麼需要你
轉寫文字會被拿來做投資討論，**資料錯誤是最嚴重的錯**。同一個轉寫來源可能犯一貫的錯（例如把長備註截斷、漏讀一個數字），
所以需要另一雙眼睛獨立檢查。你的結論決定這張圖的轉寫能不能被搜尋到：沒問題→納入搜尋；有疑慮→維持不納入並提醒 PO 核對。

## 作業步驟
1. 讀 `manifest.json`；`items` 內每一項是一張圖：
   - `view_files`：你要看的圖檔（短圖＝原圖；長圖＝切片，由上而下、相鄰切片刻意重疊；切不了時只有原圖，請自行分段檢視，**不可只看被縮小的整張就判定**）。
   - `transcription_path`：該圖目前的轉寫（Markdown 表格），**每一行前面有行號** `[L012]`，回報位置時請用行號與欄序（例：`第 12 列第 5 欄`，表頭列算第 1 列、分隔列 `| --- |` 不算）。
2. **逐列、逐格**對照原圖：
   - **文字欄位必須逐字比對**，檢查有沒有被**截斷**或**漏字**（真實案例：原圖備註是長句，轉寫只剩「廠務」兩個字——這種截斷錯誤最容易漏看）。
   - **每一個數字**都要核對：位數、小數點、千位逗號、正負號／括號、百分號、單位。
   - 檢查有沒有漏列、多出的列、欄位錯位（數字跑到隔壁欄）。
3. **看不清楚就不要猜**：無法確定的格子，該圖的 `verdict` 必須是 `issues`（**不可寫 ok**），那一項寫 `kind=other`、`found` 以 `uncertain：` 開頭說明原因。
4. **不得擅自更正原圖的明顯筆誤**：轉寫要忠實於原圖。若你認為原圖本身有筆誤，轉寫照原圖就是對的；請另外寫一項 `kind=source-typo` 說明位置與筆誤（條件與反例見下方 `issues[].kind` 說明）。
5. 每張圖給一個結論：
   - `"verdict": "ok"`：**整張圖**每一列每一格你都核對過、沒有任何疑慮。只要有任何一格沒核對或有疑問，就不是 ok。
   - `"verdict": "issues"`：列出你發現的每一項問題（上限 200 項）。
6. manifest 內每一項都要有對應結果；`image_id`、`sha256`、`transcription_sha256` 原樣抄 manifest（`transcription_sha256` 把你的結論綁定在你檢查的那一版轉寫；轉寫在你檢查後被改寫，匯入會整批拒絕）。
7. 這些圖片來自付費文章：輸出只留在本資料夾，**不要貼到任何公開或第三方的地方**。

## verification.json 格式（寫在本資料夾）

```json
{
  "version": 1,
  "verifier": "<你的 agent 名稱>",
  "method": "agent-spot-check",
  "results": [
    {"image_id": 12, "sha256": "<manifest 內該項的 sha256>", "transcription_sha256": "<manifest 內該項的 transcription_sha256>", "verdict": "ok"},
    {"image_id": 13, "sha256": "<...>", "transcription_sha256": "<...>", "verdict": "issues", "issues": [
      {"where": "第 12 列第 5 欄", "found": "廠務", "expected": "（原圖整句備註）", "kind": "truncated"},
      {"where": "第 3 列第 2 欄", "found": "9,876", "expected": "98,76", "kind": "wrong-number"}
    ]}
  ]
}
```

- `verifier`：必填，你的 agent 名稱，只能用英文字母、數字與連字號 `-`，長度 ≤ 40（例：`cline-sonnet`、`claude-code`）。
- `method`：寫 `agent-spot-check`。這是**文字家族**的檢核：只有「數字家族（compare-d-c、arithmetic、body-crosscheck）」與「文字家族（agent-spot-check）」都通過，轉寫才會成為 cross_checked 並納入搜尋；你的 ok 單獨不會讓它進搜尋。
- **限制（請知悉）**：`verifier` 與 `method` 是自報字串，系統無法證明你真的逐格檢查了；因此 reviewed 只能由 PO 設定，PO 頭兩週會逐張核對。請誠實：沒有逐格看完就不要寫 ok。
- `issues[].where` ≤ 80 字；`found`（轉寫現況）≤ 200 字；`expected`（原圖應為，可省略）≤ 200 字；
  **單行、不得含換行或控制字元**；不得出現任何看起來像金鑰或 token 的字串。
- `issues[].kind` 只能是：`truncated`（被截斷）、`wrong-number`（數字錯）、`missing`（漏列或漏格）、`extra`（多出的內容）、`other`（其他，含 uncertain）、`source-typo`（原圖本身的筆誤，見下）。
- **`source-typo` 的使用條件（很嚴格）**：只有在「**轉寫與原圖逐字一致**，但**原圖本身顯然有錯**」時才用，例如原圖把名稱欄與代碼欄對調、有明顯錯字。這代表轉寫是對的，所以若**這張圖的所有 issues 都是 `source-typo`**，這張圖視同 ok（不會被標有疑慮），但系統會留下記錄，`get_article` 會在該圖旁顯示「原圖可能有筆誤，請對照原圖」，PO 也會看到。每張圖最多 20 項。
- **反例（一律不是 source-typo）**：轉寫與原圖**不一致**（漏字、截斷、數字讀錯、多出內容）——這些是轉寫錯誤，請用 `truncated`／`wrong-number`／`missing`／`extra`。**不確定是不是原圖筆誤、或看不清楚，就用 `other`（uncertain），寧可讓它被標有疑慮。** 只要這張圖有任何一項不是 `source-typo`，整張圖照舊標有疑慮。不要為了讓圖通過而把轉寫錯誤改標成 source-typo——這會被 PO 逐張核對時抓出。
- 不要加其他欄位、不要輸出 manifest 沒有的 `image_id`、不要重複同一個 `image_id`（會整批被拒收）。
- 寫完後請 PO 預覽匯入（預設只預覽、不寫入）：
  `python3 poc/kb-mcp/investanchors_import.py --data-dir <資料目錄> --import-verification <本資料夾>/verification.json`
"""


def _unique_dir(base):
    path, n = base, 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d" % (base, n)
    os.makedirs(path)
    return path


def export_verification_task(data_dir, limit=DEFAULT_EXPORT_LIMIT, only_unverified=False, now=None,
                             tiles_runner=None, tile_tmp_root=None):
    """唯讀開庫，產出 `<data-dir>/articles_probe/verify-task-<時間>/`（manifest.json、VERIFY_GUIDE.md、
    transcriptions/<image_id>.md、長圖切片）。候選：已轉寫（done）、有本機檔且可讀、所屬文章非 abandoned、
    驗證等級非 reviewed；`only_unverified` 時只取 unverified。依 article_id／seq 穩定排序。
    不寫資料庫、不含標題與內文、不連網。庫不存在 → FileNotFoundError（不建庫）。"""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_EXPORT_LIMIT:
        raise VerificationError("--limit 必須是 1～%d 的整數" % MAX_EXPORT_LIMIT)
    store = article_store.ArticleStore.open_readonly(data_dir)
    try:
        rows = [dict(r) for r in store.conn.execute(
            "SELECT i.* FROM article_image i JOIN article a ON a.article_id=i.article_id "
            "WHERE i.file_path IS NOT NULL AND i.transcription_status='done' AND i.transcription IS NOT NULL "
            "AND a.status != 'abandoned' ORDER BY i.article_id, i.seq")]
        vers = store.get_verifications([r["id"] for r in rows])
        root = store.data_dir
    finally:
        store.close()

    picked, skipped_missing, skipped_unreadable = [], 0, 0
    for img in rows:
        if len(picked) >= limit:
            break
        status = vers[img["id"]]["status"] if img["id"] in vers else "unverified"
        if status == "reviewed" or (only_unverified and status != "unverified"):
            continue
        full = M._safe_join(root, img["file_path"])
        if full is None or not os.path.isfile(full):
            skipped_missing += 1
            continue
        with open(full, "rb") as f:
            data = f.read()
        size = article_image_tiles.image_size(data)
        if size is None:
            skipped_unreadable += 1
            continue
        picked.append((img, full, size, hashlib.sha256(data).hexdigest(), status))

    stamp = (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).strftime("%Y%m%d-%H%M%S")
    out_dir = _unique_dir(os.path.join(root, EXPORT_DIRNAME, EXPORT_PREFIX + stamp))
    tdir_t = os.path.join(out_dir, TRANSCRIPTS_DIRNAME)
    os.makedirs(tdir_t, exist_ok=True)
    items, long_n, degraded = [], 0, 0
    for img, full, (w, h), digest, status in picked:
        lines = (img["transcription"] or "").split("\n")
        tpath = os.path.join(tdir_t, "%d.md" % img["id"])
        with open(tpath, "w", encoding="utf-8") as f:
            f.write("\n".join("[L%03d] %s" % (n, ln) for n, ln in enumerate(lines, 1)) + "\n")
        is_long = article_image_tiles.is_long_image(w, h)
        long_n += 1 if is_long else 0
        item = {
            "image_id": img["id"], "article_id": img["article_id"], "seq": img["seq"],
            "path": full, "sha256": digest, "width": w, "height": h, "is_long": is_long,
            "transcription_path": tpath, "line_count": len(lines),
            "transcription_sha256": article_store.transcription_sha256(img["transcription"]),
            "transcribed_model": img.get("transcribed_model"), "current_verification": status,
            "tile_status": "not_needed", "tile_reason": None, "tiles": [], "view_files": [full],
        }
        with article_image_tiles.open_tiles(full, runner=tiles_runner, tmp_root=tile_tmp_root) as ts:
            if ts.status != article_image_tiles.STATUS_OK:
                item["tile_status"] = "unavailable"
                item["tile_reason"] = ts.reason
                degraded += 1
            elif not ts.plan.single_whole:
                tdir = os.path.join(out_dir, M.TILES_DIRNAME)
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
        "version": 1,
        "created_at": (now() if now else datetime.datetime.now(TZ8)).astimezone(TZ8).isoformat(),
        "note": "本檔不含文章標題與內文；sha256 為原圖檔的 SHA-256、transcription_sha256 為待查轉寫文字的 SHA-256，verification.json 須原樣抄回。",
        "items": items,
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, GUIDE_NAME), "w", encoding="utf-8") as f:
        f.write(build_verify_guide())
    return {"out_dir": out_dir, "exported": len(items), "skipped_missing": skipped_missing,
            "skipped_unreadable": skipped_unreadable, "long_images": long_n, "tiles_degraded": degraded}
