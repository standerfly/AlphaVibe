"""HTML→純文字與完整度分類（011；FR-010～FR-012、FR-014、spec Q14；research R6）。

只用標準庫 `html.parser`（不新增任何套件）。三類完整度：
* `P`（僅預覽）：內文結尾是站方固定的「Read more」連結段落——**只看結構，不看長度**（FR-012）；
  無法確定屬於哪一類時也一律存 `P` 並標 `uncertain:<代碼>`（寧可誤標）。
* `F`（全文）：沒有該尾端，且可見文字（扣除圖位／播放器標記與空白）≥ `MIN_FULLTEXT_CHARS`。
* `N`（非文字）：沒有該尾端，且可見文字 < 門檻（幾乎無文字或只有播放器）。
  **N 類不保存內文**（`analyze()` 的 `body_text` 為 None；FR-011、spec Q14），
  但圖位清單照樣回傳，供寫入圖片列。

圖位標記（FR-014）：`〔圖 N｜圖說：…｜alt：…〕`，依出現順序編號；`figure` 內的 `figcaption`
併入該圖的標記、不重複輸出。`iframe`／`embed`／`object` → `〔嵌入內容〕`；
`audio`／`video`／class 含 player 的容器 → `〔播放器〕`；`script`／`style` 丟棄。

僅標準庫、Python 3.9 相容。
"""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

MIN_FULLTEXT_CHARS = 200
# 規則版本：改動分類規則時遞增，重判紀錄會記下用的是哪一版（FR-033）
RULE_VERSION = "2026-11-20.1"

EMBED_MARK = "〔嵌入內容〕"
PLAYER_MARK = "〔播放器〕"
READ_MORE_TEXT = "read more"

REASON_READ_MORE = "read_more_tail"
REASON_FULL = "text_ge_200"
REASON_SHORT = "text_lt_200"
UNCERTAIN_NO_CONTENT = "uncertain:no_content"
UNCERTAIN_PARSE = "uncertain:parse_error"
UNCERTAIN_MISMATCH = "uncertain:read_more_mismatch"
UNCERTAIN_AFTER = "uncertain:content_after_read_more"

VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                       "meta", "param", "source", "track", "wbr"))
DROP_TAGS = frozenset(("script", "style", "noscript", "head", "template"))
EMBED_TAGS = frozenset(("iframe", "embed", "object"))
PLAYER_TAGS = frozenset(("audio", "video"))
BLOCK_TAGS = frozenset(("address", "article", "aside", "blockquote", "div", "dl", "dd", "dt",
                        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
                        "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
                        "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead",
                        "tr", "ul"))
_MARK_RE = re.compile(r"〔[^〕]*〕")
_PLAYER_CLASS_RE = re.compile(r"player", re.I)
_SLUG_PATH_RE = re.compile(r"^/p/[^/]+/?$")


class HtmlParseError(Exception):
    """內容無法當成 HTML 解析（分類時轉成 uncertain:parse_error）。"""


class Node(object):
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []
        self.parent = parent


class _DomBuilder(HTMLParser):
    """容錯的淺層 DOM 建構器：壞掉的巢狀不丟例外，只盡量還原結構。"""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]
        self.elements = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in BLOCK_TAGS and self.stack[-1].tag == "p":
            self.stack.pop()                     # <p> 遇到區塊元素隱性關閉
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        self.elements += 1
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        self.elements += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def parse_dom(content_html):
    if content_html is None:
        raise HtmlParseError("no_content")
    text = str(content_html)
    builder = _DomBuilder()
    try:
        builder.feed(text)
        builder.close()
    except Exception:                                    # noqa: BLE001
        raise HtmlParseError("parse_error")
    if builder.elements == 0 and "<" in text:
        raise HtmlParseError("parse_error")              # 有標記符號卻解析不出任何元素
    _merge_figcaptions(builder.root)
    return builder.root


# ---------------------------------------------------------------- 樹的小工具
def _elements(node):
    for child in node.children:
        if isinstance(child, str):
            continue
        yield child
        for inner in _elements(child):
            yield inner


def _plain_text(node):
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in DROP_TAGS:
            parts.append(_plain_text(child))
    return "".join(parts)


def _norm_inline(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _merge_figcaptions(root):
    """figure 內的 figcaption 併入第一張圖的標記，並標記為不重複輸出。"""
    for node in _elements(root):
        if node.tag != "figure":
            continue
        images = [n for n in _elements(node) if n.tag == "img"]
        captions = [n for n in _elements(node) if n.tag == "figcaption"]
        if not images or not captions:
            continue
        images[0].attrs["__caption__"] = _norm_inline(_plain_text(captions[0]))
        captions[0].attrs["__merged__"] = "1"


def _is_player_box(node):
    class_attr = node.attrs.get("class") or ""
    return bool(_PLAYER_CLASS_RE.search(class_attr))


def _meaningful_top_level(root):
    items = []
    for child in root.children:
        if isinstance(child, str):
            if child.strip():
                items.append(child)
        elif child.tag not in DROP_TAGS:
            items.append(child)
    return items


def _top_level_ancestor(root, node):
    current = node
    while current is not None and current.parent is not None and current.parent is not root:
        current = current.parent
    return current


# ---------------------------------------------------------------- 轉純文字
def _image_mark(seq, caption, alt):
    parts = ["圖 %d" % seq]
    if caption:
        parts.append("圖說：%s" % caption)
    if alt:
        parts.append("alt：%s" % alt)
    return "〔" + "｜".join(parts) + "〕"


def _render(root, skip_ids=()):
    out = []
    images = []
    counter = [0]

    def emit_newline():
        if out and out[-1] != "\n":
            out.append("\n")

    def walk(node):
        for child in node.children:
            if isinstance(child, str):
                inline = _norm_inline(child)
                if inline:
                    out.append(inline)
                continue
            if id(child) in skip_ids or child.tag in DROP_TAGS:
                continue
            if child.tag == "figcaption" and child.attrs.get("__merged__"):
                continue
            if child.tag == "img":
                counter[0] += 1
                caption = child.attrs.get("__caption__") or None
                alt = _norm_inline(child.attrs.get("alt")) or None
                images.append({"seq": counter[0], "src": child.attrs.get("src"),
                               "alt": alt, "caption": caption})
                out.append(_image_mark(counter[0], caption, alt))
                continue
            if child.tag in EMBED_TAGS:
                emit_newline()
                out.append(EMBED_MARK)
                emit_newline()
                continue
            if child.tag in PLAYER_TAGS or _is_player_box(child):
                emit_newline()
                out.append(PLAYER_MARK)
                emit_newline()
                continue
            if child.tag == "br":
                emit_newline()
                continue
            if child.tag in BLOCK_TAGS:
                emit_newline()
                if child.tag == "li":
                    out.append("• ")
                walk(child)
                emit_newline()
                continue
            walk(child)

    walk(root)
    return _normalize("".join(out)), images


def _normalize(text):
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line)


def html_to_text(content_html, drop_read_more_tail=False, link=None):
    """回傳 (純文字, 圖片清單)。圖片清單元素：{'seq','src','alt','caption'}。

    `drop_read_more_tail=True` 時去掉尾端的 Read more 段（P 類的公開預覽，FR-011）。
    """
    root = parse_dom(content_html)
    skip = set()
    if drop_read_more_tail:
        anchor = _find_read_more(root)
        tail = _read_more_tail(root, anchor, link) if anchor is not None else None
        if tail is not None:
            skip.add(id(tail))
    return _render(root, skip)


def visible_text_len(text):
    """可見文字長度：扣除圖位／播放器／嵌入標記與所有空白（FR-010）。"""
    stripped = _MARK_RE.sub("", str(text or ""))
    return len(re.sub(r"\s+", "", stripped))


# ---------------------------------------------------------------- 分類
def _find_read_more(root):
    anchors = [n for n in _elements(root)
               if n.tag == "a" and _norm_inline(_plain_text(n)).lower() == READ_MORE_TEXT]
    return anchors[-1] if anchors else None


def _only_child_is(node, anchor):
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                return False
        elif child is not anchor and child.tag not in DROP_TAGS:
            return False
    return True


def _href_is_article(href, link):
    if not href or not link:
        return False
    target = urlsplit(str(href))
    source = urlsplit(str(link))
    if target.scheme != "https":
        return False
    host = (target.hostname or "").lower()
    if not host or host != (source.hostname or "").lower():
        return False
    return bool(_SLUG_PATH_RE.match(target.path or ""))


def _read_more_tail(root, anchor, link):
    """符合站方固定結構時回傳該尾端段落節點，否則 None。"""
    if anchor is None:
        return None
    parent = anchor.parent
    if parent is None or parent.tag != "p":
        return None
    items = _meaningful_top_level(root)
    if not items or items[-1] is not parent:
        return None
    if not _only_child_is(parent, anchor):
        return None
    if not _href_is_article(anchor.attrs.get("href"), link):
        return None
    return parent


def _content_after(root, anchor):
    """Read more 之後還有內容（FR-012 的不確定情形之一）。"""
    top = _top_level_ancestor(root, anchor)
    items = _meaningful_top_level(root)
    if top is not None and items and items[-1] is not top:
        return True
    parent = anchor.parent
    if parent is None:
        return False
    seen = False
    for child in parent.children:
        if child is anchor:
            seen = True
            continue
        if not seen:
            continue
        if isinstance(child, str):
            if child.strip():
                return True
        elif child.tag not in DROP_TAGS:
            return True
    return False


def classify(content_html, link=None):
    """回傳 (完整度, 依據代碼)。不確定一律 P（FR-012）；**不以長度判斷 P**。"""
    if content_html is None or not str(content_html).strip():
        return "P", UNCERTAIN_NO_CONTENT
    try:
        root = parse_dom(content_html)
    except HtmlParseError:
        return "P", UNCERTAIN_PARSE
    anchor = _find_read_more(root)
    if anchor is not None:
        if _read_more_tail(root, anchor, link) is not None:
            return "P", REASON_READ_MORE
        if _content_after(root, anchor):
            return "P", UNCERTAIN_AFTER
        return "P", UNCERTAIN_MISMATCH
    text, _images = _render(root)
    if visible_text_len(text) >= MIN_FULLTEXT_CHARS:
        return "F", REASON_FULL
    return "N", REASON_SHORT


def analyze(content_html, link=None):
    """分類＋產生要存的內文與圖位清單。

    回傳 {'completeness','reason','body_text','images'}：
    * N 類 `body_text` 為 None（不保存內文，FR-011、spec Q14），圖位清單仍回傳；
    * P 類（`read_more_tail`）去掉尾端 Read more 段；
    * 內容缺漏或無法解析（uncertain:*）時 `body_text` 為空字串——沒有可抽取的文字就是空的，
      不猜、不補假內容；原始內容仍由呼叫端存進 `content_html` 供日後重判。
    """
    completeness, reason = classify(content_html, link)
    images = []
    text = ""
    if content_html is not None and str(content_html).strip():
        try:
            root = parse_dom(content_html)
        except HtmlParseError:
            root = None
        if root is not None:
            skip = set()
            if reason == REASON_READ_MORE:
                anchor = _find_read_more(root)
                tail = _read_more_tail(root, anchor, link)
                if tail is not None:
                    skip.add(id(tail))
            text, images = _render(root, skip)
    body_text = None if completeness == "N" else text
    return {"completeness": completeness, "reason": reason, "body_text": body_text,
            "images": images}
