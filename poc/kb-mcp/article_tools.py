"""定錨文章查詢的共用格式化層（010 US2，T026）。

台股 `server.py` 與美股 `us_stock_mcp_server.py` 各自註冊 `search_articles`／`get_article`，
但都呼叫這一份，確保兩個連接器輸出逐字相同。全部唯讀：以 SQLite mode=ro 開
`<data_dir>/articles.db`，不建庫、不寫入、不觸發任何網站存取。

「機器轉寫，可能有誤，請以原圖為準」標示只在這裡（輸出層）加，資料庫不存。
"""
import json

import article_store

# 轉寫驗證等級（Q-028）：unverified／flagged 的轉寫只在單篇顯示並附這句警告，不納入搜尋。
UNVERIFIED_WARNING = "【未驗證／有疑慮的圖片轉寫：數字可能有誤，不得用於投資判斷，請對照原圖】"
NOT_TABLE_FLAGGED_WARNING = "【此圖被判為非表格，但驗證發現疑慮：可能含表格內容而未轉寫，請對照原圖】"
MAX_DISPLAY_CELLS = 10
VERIFICATION_LEVEL_TEXT = {
    "unverified": "未驗證（不納入搜尋）",
    "flagged": "有疑慮（不納入搜尋）",
    "cross_checked": "已交叉驗證（納入搜尋）",
    "reviewed": "PO 已逐格核對（納入搜尋）",
}
TRANSCRIPTION_WARNING = "【機器轉寫，可能有誤，請以原圖為準】"
MANUAL_PREFIX = "manual:"     # 方案 D（agent 手動轉寫）寫入 transcribed_model 的前綴
CLAUDE_CLI_PREFIX = "claude-cli:"   # Phase 14 流水線（Claude Code 非互動模式讀圖）寫入 transcribed_model 的前綴


def transcription_label(model):
    """依 transcribed_model 決定轉寫來源標示：手動（方案 D）與 API 轉寫明確區分，兩者都提醒以原圖為準。"""
    if isinstance(model, str) and model.startswith(MANUAL_PREFIX):
        return "【圖片轉寫，手動（agent：%s），可能有誤，請以原圖為準】" % (model[len(MANUAL_PREFIX):] or "未標示")
    if isinstance(model, str) and model.startswith(CLAUDE_CLI_PREFIX):
        return "【圖片轉寫，Claude 自動轉寫（%s），可能有誤，請以原圖為準】" % (model[len(CLAUDE_CLI_PREFIX):] or "未標示")
    return TRANSCRIPTION_WARNING


def transcription_source(model):
    """轉寫來源（不含警告字樣，給 unverified／flagged 區塊用）。"""
    if isinstance(model, str) and model.startswith(MANUAL_PREFIX):
        return "手動轉寫（agent：%s）" % (model[len(MANUAL_PREFIX):] or "未標示")
    if isinstance(model, str) and model.startswith(CLAUDE_CLI_PREFIX):
        return "Claude 自動轉寫（模型別名：%s）" % (model[len(CLAUDE_CLI_PREFIX):] or "未標示")
    return "機器轉寫（模型：%s）" % (model or "未標示")


def _cell_lines(v):
    try:
        cells = json.loads(v.get("flagged_cells") or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    if isinstance(cells, list):
        for c in cells[:MAX_DISPLAY_CELLS]:
            if not isinstance(c, dict):
                continue
            line = "- %s｜%s｜轉寫現況：%s" % (c.get("where", "?"), c.get("kind", "other"), c.get("found", ""))
            if c.get("expected"):
                line += "｜疑似原圖：%s" % c["expected"]
            out.append(line)
        if len(cells) > MAX_DISPLAY_CELLS:
            out.append("- …另 %d 項" % (len(cells) - MAX_DISPLAY_CELLS))
    return out


def _partial_text(v):
    """只通過單一檢核家族時的說明；cross_checked 需要數字與文字兩個家族都通過。"""
    checks = set((v or {}).get("checks_passed", "") and v["checks_passed"].split(",") or [])
    if checks == {"numeric"}:
        return "檢核進度：已通過數字檢核，尚缺文字抽查（兩個家族都通過才納入搜尋）"
    if checks == {"text"}:
        return "檢核進度：已通過文字抽查，尚缺數字檢核（兩個家族都通過才納入搜尋）"
    return ""


def source_typo_line(img):
    """原圖可能有筆誤的提示（轉寫已照原圖抄寫）；任何驗證等級都顯示。只含位置與簡述，不含標題。"""
    v = img.get("verification") or {}
    try:
        typos = json.loads(v.get("source_typos") or "[]")
    except (TypeError, ValueError):
        return ""
    parts = []
    for t in (typos if isinstance(typos, list) else [])[:MAX_DISPLAY_CELLS]:
        if isinstance(t, dict):
            part = "%s（%s" % (t.get("where", "?"), t.get("found", ""))
            if t.get("expected"):
                part += "；疑似應為：%s" % t["expected"]
            parts.append(part + "）")
    if not parts:
        return ""
    more = len(typos) - MAX_DISPLAY_CELLS
    return "【原圖可能有筆誤（轉寫已照原圖抄寫），請對照原圖：%s%s】" % ("；".join(parts), "；…另 %d 項" % more if more > 0 else "")


def verification_header(img):
    """依驗證等級回傳 (標示行 list)：unverified／flagged＝醒目警告；cross_checked／reviewed＝等級與方法。"""
    status = img.get("verification_status") or "unverified"
    v = img.get("verification") or {}
    model = img.get("transcribed_model")
    if status in ("unverified", "flagged"):
        lines = [UNVERIFIED_WARNING,
                 "驗證等級：%s；來源：%s" % (VERIFICATION_LEVEL_TEXT[status], transcription_source(model))]
        partial = _partial_text(v)
        if partial:
            lines.append(partial)
        if status == "flagged":
            if v.get("note"):
                lines.append("疑慮摘要：%s" % v["note"])
            lines += _cell_lines(v)
        return lines
    detail = "驗證等級：%s" % VERIFICATION_LEVEL_TEXT.get(status, status)
    if v.get("method"):
        detail += "；方法：%s" % v["method"]
    if v.get("verifier") and status != "reviewed":
        detail += "；驗證者：%s" % v["verifier"]
    if v.get("checked_at"):
        detail += "；時間：%s" % v["checked_at"]
    lines = [transcription_label(model), detail]
    if status == "cross_checked":
        lines.append("（雙來源一致不代表絕對正確，重要數字仍請對照原圖）")
    return lines


NO_RESULT_TEXT = "查無符合的文章"


def _read_only_store(data_dir):
    return article_store.ArticleStore.open_readonly(data_dir)


def format_search_results(results):
    if not results:
        return NO_RESULT_TEXT
    lines = ["共 %d 筆（發布日期新到舊）：" % len(results)]
    for i, r in enumerate(results, 1):
        lines.append("%d. %s｜%s｜原文：%s｜片段（%s）：%s｜article_id=%s" % (
            i, r["title"], r.get("published_at") or "日期未知", r["url"],
            r.get("source") or "—", r.get("snippet") or "", r["article_id"]))
    return "\n".join(lines)


def format_article(article):
    lines = [
        "標題：%s" % article["title"],
        "發布日期：%s" % (article.get("published_at") or "日期未知"),
        "原文網址：%s" % article["url"],
        "article_id：%s" % article["article_id"],
        "",
        "【全文】",
        article.get("body") or "",
    ]
    images = article.get("images") or []
    lines += ["", "【圖片】共 %d 張" % len(images)]
    for img in images:
        if img.get("is_table") is None:
            kind = "未判定"
        else:
            kind = "表格" if img["is_table"] else "非表格"
        status = img.get("transcription_status")
        label = {"done": "已轉寫", "untranscribed": "未轉寫", "not_table": "非表格（不轉寫）"}.get(status, status)
        lines.append("#%s｜%s｜%s｜原圖 src_url：%s｜本機路徑：%s" % (
            img["seq"], kind, label, img.get("src_url") or "無", img.get("file_path") or "無"))
        if status == "done" and img.get("transcription"):
            for hl in verification_header(img):
                lines.append("  %s" % hl)
            typo = source_typo_line(img)
            if typo:
                lines.append("  %s" % typo)
            # 每行加固定前綴「│ 」：轉寫文字內偽造的「【…】」警告樣式行，無法與上方真正的警告標頭混淆
            lines.append("  │ " + img["transcription"].replace("\n", "\n  │ "))
        elif status == "not_table" and img.get("verification_status") == "flagged":
            lines.append("  %s" % NOT_TABLE_FLAGGED_WARNING)
            v = img.get("verification") or {}
            if v.get("note"):
                lines.append("  疑慮摘要：%s" % v["note"])
    return "\n".join(lines)


def search_articles_text(store, query, limit=10):
    return format_search_results(store.search_articles(query, limit))


def get_article_text(store, article_id):
    return format_article(store.get_article(article_id))


def run_search_articles(data_dir, args):
    """MCP 入口：開唯讀庫、查、關。庫不存在 → 例外（由 server 轉成 isError）。"""
    query = args.get("query")
    if not query or not str(query).strip():
        raise ValueError("search_articles 需要 query 參數")
    store = _read_only_store(data_dir)
    try:
        return search_articles_text(store, str(query), args.get("limit", 10))
    finally:
        store.close()


def run_get_article(data_dir, args):
    if args.get("article_id") is None:
        raise ValueError("get_article 需要 article_id 參數")
    store = _read_only_store(data_dir)
    try:
        return get_article_text(store, args["article_id"])
    finally:
        store.close()


ARTICLE_TOOL_SCHEMAS = [
    {
        "name": "search_articles",
        "description": (
            "搜尋已匯入的「定錨產業筆記」文章（唯讀）。query 以空白分隔多個關鍵字，"
            "全部需出現（AND）；範圍含標題、全文，以及「已驗證」（交叉驗證或 PO 核對）的表格圖片轉寫文字——"
            "未驗證或有疑慮的轉寫不納入搜尋（只在單篇 get_article 顯示並附警告）；"
            "依發布日期新到舊，每筆附原文網址、片段與 article_id。"
            "台股與美股連接器共用同一個文章庫，結果相同。不會連線網站。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "關鍵字，空白分隔，全部需出現。"},
                "limit": {"type": "integer", "description": "回傳筆數，預設 10，最大 30。"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_article",
        "description": (
            "讀單篇已匯入的定錨文章全文與圖片清單（唯讀）。圖片附原圖網址 src_url，"
            "表格轉寫為機器轉寫、可能有誤，請以原圖為準；每張圖標示驗證等級，未驗證／有疑慮者附醒目警告、不得用於投資判斷。"
            "找不到或尚未成功匯入會回明確錯誤。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "integer", "description": "search_articles 回傳的 article_id。"},
            },
            "required": ["article_id"],
        },
    },
]
ARTICLE_TOOL_NAMES = ("search_articles", "get_article")


def call_article_tool(data_dir, name, args):
    if name == "search_articles":
        return run_search_articles(data_dir, args)
    if name == "get_article":
        return run_get_article(data_dir, args)
    raise ValueError("未知文章工具：%s" % name)
