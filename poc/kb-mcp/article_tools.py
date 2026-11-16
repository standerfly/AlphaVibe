"""定錨文章查詢的共用格式化層（010 US2，T026）。

台股 `server.py` 與美股 `us_stock_mcp_server.py` 各自註冊 `search_articles`／`get_article`，
但都呼叫這一份，確保兩個連接器輸出逐字相同。全部唯讀：以 SQLite mode=ro 開
`<data_dir>/articles.db`，不建庫、不寫入、不觸發任何網站存取。

「機器轉寫，可能有誤，請以原圖為準」標示只在這裡（輸出層）加，資料庫不存。
"""
import article_store

TRANSCRIPTION_WARNING = "【機器轉寫，可能有誤，請以原圖為準】"
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
            lines.append("  %s" % TRANSCRIPTION_WARNING)
            lines.append("  " + img["transcription"].replace("\n", "\n  "))
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
            "全部需出現（AND）；範圍含標題、全文與表格圖片的轉寫文字；"
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
            "表格轉寫為機器轉寫、可能有誤，請以原圖為準。找不到或尚未成功匯入會回明確錯誤。"),
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
