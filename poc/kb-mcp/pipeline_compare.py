"""轉寫流水線的數字家族與判定小工具（010 Phase 14，clarification-log Q-029）。純函式、零 I/O、零網路。

2026-11-18 PO 縮減範圍：文字家族改由「驗證者」（另一次全新的 `claude -p`，見 claude_cli_runner）看圖＋行號待查轉寫後回報，
**不再做 reader-1 對 reader-2 的盲讀逐格比對**；本模組只保留：
  numeric_family：reader-1 對本機 PaddleOCR 的「涵蓋」判定（重用 compare_transcriptions.classify_image，PR #59 的規則）——
                  ok／issues／inconclusive／unmatched／unavailable；inconclusive 與 unavailable **不輸出**（維持 unverified）。
  normalize_text：寫入資料庫前的輕量整理。
  verification_payload：組成 verification.json 結構（交給既有 validate_verification／apply_verification，規則完全相同）。
issues 的 found 一律是固定描述（不含格子內容）。
"""
import compare_transcriptions as C
import article_verification as V

MAX_ISSUES = V.MAX_ISSUES_PER_IMAGE
DESC_PADDLE = {"wrong-number": "與 PaddleOCR 的數字不一致", "other": "讀者1 標示看不清楚（?），PaddleOCR 無法佐證"}


def normalize_text(text):
    """統一換行、去掉行尾空白與頭尾空行（不動內容）。"""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


def numeric_family(image_sha256, text, paddle_text, paddle_status=None):
    """回傳 {"category": ok|issues|inconclusive|unmatched|unavailable, "issues": [...], "reason": 固定說明}。
    paddle_text 為 None（缺 paddle／失敗）→ unavailable。"""
    if paddle_text is None:
        return {"category": "unavailable", "issues": [], "reason": paddle_status or "paddle_unavailable"}
    it = {"image_id": 0, "sha256": image_sha256, "is_table": True, "text": text}
    cmp_ = C.compare_texts(text, paddle_text)
    mine = [({"id": "paddle"}, it, {"data": {"status": "transcribed", "text": paddle_text}}, cmp_)]
    res = C.classify_image(it, mine)
    issues = []
    for x in res["issues"][:MAX_ISSUES]:
        kind = x["kind"] if x["kind"] in DESC_PADDLE else "other"
        issues.append({"where": x["where"][:80], "found": DESC_PADDLE[kind], "kind": kind})
    return {"category": res["category"], "issues": issues, "reason": res["reason"]}


def verification_payload(verifier, method, image_id, image_sha256, transcription, verdict, issues):
    """verification.json 結構（version 1）。transcription_sha256 綁定這一版轉寫。"""
    row = {"image_id": image_id, "sha256": image_sha256,
           "transcription_sha256": V.article_store.transcription_sha256(transcription), "verdict": verdict}
    if verdict == "issues":
        row["issues"] = list(issues)
    return {"version": 1, "verifier": verifier, "method": method, "results": [row]}
