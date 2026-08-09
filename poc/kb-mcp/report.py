"""產出三層知識庫的靜態檢視頁（Phase 1b 試用期的極簡唯讀報表）。

定位：拋棄式檢視工具，同時是 OQ-3（儀表板技術形態）的「靜態產出」實驗
——1b 試用期覺得它夠用，1c 就便宜做；覺得想互動，就是要做互動頁的證據。

刻意不做：即時股價、距離目標買價（需線上數據與互動，屬 1c 儀表板 FR-024）。

用法：python3 poc/kb-mcp/report.py [--data-dir DIR] [--out 路徑]
預設讀 poc/data/、寫到 poc/data/report.html。純標準庫、Python 3.9 相容。
"""
import argparse
import datetime
import html
import json
import os
import re
import struct
import sys
import urllib.parse
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kb_store import KBStore  # noqa: E402
import frameworks  # noqa: E402
import screener  # noqa: E402

# 台股慣例：紅漲綠跌 → 偏多紅、偏空綠
STANCE_COLORS = {"偏多": "var(--red)", "偏空": "var(--green)"}
DEFAULT_STANCE_COLOR = "var(--ink-dim)"

CSS = """
/* ---- 色彩／排版 token（2026-07-30 導入，取代全檔寫死 hex，支援
   deep mode）：語意色（red=需留意/警示、green=正向/完成、accent=互動
   元素）跟中性色分開定義，深色模式只需覆寫這一份 token，其餘規則透過
   var() 自動套用，不用逐條規則各自處理明暗兩色。 */
:root {
  --paper: #ffffff;
  --paper-raised: #f8f9fa;
  --paper-sunken: #f1f3f5;
  --ink: #212529;
  --ink-dim: #6c757d;
  --rule: #dee2e6;
  --rule-strong: #adb5bd;
  --accent: #1971c2;
  --accent-soft: #e7f5ff;
  --red: #c92a2a;
  --red-soft: #fff5f5;
  --red-ink: #862e2e;
  --green: #2b8a3e;
  --amber: #e8590c;
  --amber-soft: #fff4e6;
  --shadow: 0 1px 2px rgba(0,0,0,.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #16181c;
    --paper-raised: #1d2024;
    --paper-sunken: #24272c;
    --ink: #e9ecef;
    --ink-dim: #9298a0;
    --rule: #33373d;
    --rule-strong: #474c53;
    --accent: #6fb1f0;
    --accent-soft: #17273a;
    --red: #ff8a8a;
    --red-soft: #3a1f20;
    --red-ink: #ffc2c2;
    --green: #6fcf87;
    --amber: #ffa94d;
    --amber-soft: #3a2a17;
    --shadow: 0 1px 2px rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
body { font-family: -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif;
       margin: 0 auto; max-width: 1040px; padding: 1.5rem 1rem 4rem;
       color: var(--ink); background: var(--paper); line-height: 1.5;
       transition: background .15s ease, color .15s ease; }
a { color: var(--accent); }
h1 { font-size: 1.5rem; font-weight: 700; margin: 0 0 .3rem; }
h2 { font-size: 1.08rem; font-weight: 700; margin-top: 2rem;
     border-bottom: 2px solid var(--ink); padding-bottom: .35rem; }
.meta { color: var(--ink-dim); font-size: .85rem; }
table { border-collapse: collapse; width: 100%; font-size: .88rem;
        font-variant-numeric: tabular-nums; }
th, td { border: 1px solid var(--rule); padding: .5rem .65rem; text-align: left;
         vertical-align: top; overflow-wrap: break-word; }
th { background: var(--paper-sunken); white-space: nowrap; font-size: .74rem;
     text-transform: uppercase; letter-spacing: .02em; color: var(--ink-dim);
     font-weight: 700; }
tbody tr:hover { background: var(--paper-raised); }
.stance { font-weight: 700; white-space: nowrap; }
.empty { color: var(--ink-dim); padding: 1rem 0; }
.comment { border-left: 3px solid var(--rule-strong); margin: .8rem 0;
           padding: .3rem .9rem; background: var(--paper-raised);
           border-radius: 0 6px 6px 0; }
.comment .head { font-size: .8rem; color: var(--ink-dim); font-weight: 700;
                  margin-bottom: .25rem; }
.tag { background: var(--accent-soft); color: var(--accent); border-radius: 3px;
       padding: .1rem .5rem; font-size: .75rem; margin: 0 .3rem .2rem 0;
       display: inline-block; font-weight: 600; }
/* 通用小徽章：今日重點的「檢視層」、衝突提醒等短標籤用，跟 .tag（策略
   標籤）語意不同特意分開命名，避免以後改配色時互相牽動 */
.badge { display: inline-block; font-size: .7rem; font-weight: 700;
         padding: .1rem .5rem; border-radius: 3px; letter-spacing: .02em;
         white-space: nowrap; }
.badge-danger { background: var(--red-soft); color: var(--red-ink); }
.badge-neutral { background: var(--paper-sunken); color: var(--ink-dim); }
/* 今日重點：有衝突的列用左側色條＋淡底標出來，比整列變色更容易一眼
   掃過去找到真正需要注意的那幾列（純色底在深色模式下太搶眼，改用
   左側 4px 色條＋輕微淡底） */
tr.row-alert { background: var(--red-soft); box-shadow: inset 4px 0 0 var(--red); }
tr.row-highlight { background: var(--amber-soft); box-shadow: inset 4px 0 0 var(--amber); }
.btn-danger { background: var(--red); color: #fff; border: none;
              padding: .6rem 1.2rem; border-radius: 6px; font-size: .95rem;
              cursor: pointer; }
.btn-danger:hover { filter: brightness(1.08); }
/* 導覽用的按鈕式連結（首頁跳轉到 /screen、/market-scan 等）：原本每處
   各自寫一份 inline style 重複 6 次以上，統一成 class 才不用每加一個
   連結就複製一段 style，深色模式也才不會漏改 */
.btn, .btn-muted { display: inline-block; padding: .5rem 1rem; border-radius: 6px;
        text-decoration: none; font-weight: 600; margin: 0 .5rem .5rem 0; }
.btn { background: var(--accent); color: #fff; }
.btn:hover { filter: brightness(1.08); }
.btn-muted { background: var(--ink-dim); color: var(--paper); }
.btn-muted:hover { filter: brightness(1.1); }
.btn-primary-action { background: var(--accent); color: #fff; border: none;
        padding: .6rem 1.2rem; border-radius: 6px; cursor: pointer; }
.btn-primary-action:hover { filter: brightness(1.08); }
.tablewrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
details.philomod { border: 1px solid var(--rule); border-radius: 8px;
                    margin: .6rem 0; padding: .5rem .8rem; background: var(--paper-raised); }
details.philomod summary { cursor: pointer; font-weight: 600; }
details.philomod summary::marker { color: var(--accent); }
details.philomod pre { white-space: pre-wrap; overflow-wrap: break-word;
                        font-family: inherit; font-size: .88rem;
                        line-height: 1.55; margin: .7rem 0 .1rem; }
/* 表格「理由」欄位的展開全文（巢狀在 <td> 裡，class 特意跟上面兩個 details
   分開，避免樣式互相污染） */
details.reason { display: inline-block; max-width: 100%; }
details.reason summary { cursor: pointer; color: var(--accent); }
details.reason summary::marker { color: var(--accent); }
details.reason .reason-full { white-space: pre-wrap; overflow-wrap: break-word;
                                margin-top: .3rem; }
.toc { margin: .8rem 0 1.2rem; padding: .7rem 1rem; background: var(--paper-raised);
       border: 1px solid var(--rule); border-radius: 8px; font-size: .92rem;
       line-height: 2; }
.toc a { color: var(--accent); text-decoration: none; margin-right: 1.2rem;
         display: inline-block; font-weight: 600; }
.toc a:hover { text-decoration: underline; }
details.section { margin: 1.6rem 0 0; padding-bottom: .2rem; }
details.section > summary { cursor: pointer; }
details.section > summary::marker { color: var(--accent); }
details.section > summary h2 { margin-top: 0; display: inline-block; }
/* 快速輸入表單：桌機並排、輸入框跟按鈕維持一致的深淺色 token，不再是
   純表格頁面裡唯一有互動元素的區塊，特別給輸入框/按鈕加可見的邊框與
   focus 樣式（原本完全沒有這塊的專屬樣式，靠瀏覽器預設值，在深色模式
   下預設的白底輸入框會刺眼） */
.section input[type=text], .section input[type=number], .section input[type=date],
.section textarea, .section select {
  background: var(--paper); color: var(--ink); border: 1px solid var(--rule-strong);
  border-radius: 6px; padding: .45rem .6rem; font-size: .9rem; font-family: inherit;
}
.section textarea { resize: vertical; }
.section input:focus, .section textarea:focus { outline: 2px solid var(--accent);
  outline-offset: 1px; }
.section button[type=submit] {
  background: var(--accent); color: #fff; border: none; border-radius: 6px;
  padding: .5rem 1.1rem; font-size: .9rem; font-weight: 600; cursor: pointer;
}
.section button[type=submit]:hover { filter: brightness(1.08); }
/* 手機（<=640px）：表格改成一張張卡片，橫向捲動改直向堆疊，好讀很多 */
@media (max-width: 640px) {
  body { padding: 1rem 1rem 4rem; }
  h1 { font-size: 1.3rem; }
  .tablewrap table, .tablewrap tbody, .tablewrap tr,
  .tablewrap th, .tablewrap td { display: block; width: auto; }
  .tablewrap thead { display: none; }
  .tablewrap tr { border: 1px solid var(--rule); border-radius: 8px;
                   margin-bottom: .75rem; overflow: hidden; box-shadow: var(--shadow); }
  .tablewrap tr.row-alert, .tablewrap tr.row-highlight { box-shadow: var(--shadow); }
  .tablewrap td { border: none; border-bottom: 1px solid var(--paper-sunken); }
  .tablewrap td:last-child { border-bottom: none; }
  .tablewrap td::before { content: attr(data-label); display: block;
                            font-size: .72rem; font-weight: 700;
                            color: var(--ink-dim); margin-bottom: .15rem; }
}
/* 桌機（>=1040px 版心以上還有餘裕時）：今日重點/新候選/庫存三個核心
   表格允許更寬鬆的欄距，閱讀密度跟手機版分開調，避免同一份字級/間距
   在兩種尺寸各自妥協 */
@media (min-width: 900px) {
  th, td { padding: .6rem .8rem; }
  .toc { font-size: .95rem; }
}
/* ---- 個股清單頁／詳情頁（2026-08-01，依已核准mockup的版面結構重繪，
   刻意沿用上面既有的色彩token、不引入新配色：漲(紅var(--red))/跌
   (綠var(--green))語意跟.stance／STANCE_COLORS一致，「需留意」用
   var(--red)（跟既有.row-alert語意一致），卡片沿用.comment／
   details.philomod已有的圓角+邊框+陰影語言，只是換一種排列方式。 ---- */
.stocklist-search, .stocklist-add { display: flex; align-items: center; gap: .5rem;
  border-radius: 10px; padding: .55rem .8rem; margin-bottom: .75rem; }
.stocklist-search { background: var(--paper-raised); border: 1px solid var(--rule); }
.stocklist-add { background: var(--paper-sunken); border: 1px dashed var(--rule-strong); }
.stocklist-search input[type=text], .stocklist-add input[type=text] {
  border: none; background: none; outline: none; color: var(--ink); font: inherit;
  font-size: .9rem; width: 100%; padding: 0; }
.stocklist-add button { flex-shrink: 0; }
.filter-tabs { display: flex; gap: .4rem; margin-bottom: .9rem; flex-wrap: wrap; }
.filter-tab { font-size: .8rem; font-weight: 600; padding: .35rem .85rem; border-radius: 999px;
  border: 1px solid var(--rule); background: var(--paper); color: var(--ink-dim);
  text-decoration: none; display: inline-block; }
.filter-tab.active { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.stock-list { display: flex; flex-direction: column; gap: .55rem; margin-bottom: 1rem; }
.stock-row { display: flex; align-items: center; gap: .7rem; background: var(--paper);
  border: 1px solid var(--rule); border-radius: 10px; box-shadow: var(--shadow);
  padding: .7rem .9rem; text-decoration: none; color: inherit; }
.stock-row.has-concern { border-color: var(--red); }
.stock-row__id { min-width: 0; flex: 1; }
.stock-row__name-line { display: flex; align-items: baseline; gap: .4rem; flex-wrap: wrap; }
.stock-row__name { font-size: .96rem; font-weight: 700; }
.stock-row__code { font-size: .72rem; color: var(--ink-dim); font-variant-numeric: tabular-nums; }
.stock-row__sub { font-size: .72rem; color: var(--ink-dim); margin-top: .15rem; overflow-wrap: break-word; }
.stock-row__price { text-align: right; flex-shrink: 0; font-variant-numeric: tabular-nums; }
.stock-row__now { font-size: .92rem; font-weight: 700; }
.stock-row__delta { font-size: .74rem; font-weight: 700; }
.stock-row__delta.is-up { color: var(--red); }
.stock-row__delta.is-down { color: var(--green); }
.concern-dot { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; background: var(--red); }
.concern-slot { width: 8px; flex-shrink: 0; }
.pager { display: flex; align-items: center; justify-content: space-between;
  margin-top: .3rem; font-size: .82rem; color: var(--ink-dim); }
.pager__nav a, .pager__nav span { margin-left: .4rem; }
.pager .btn-muted[aria-disabled="true"] { opacity: .4; pointer-events: none; }

.card { background: var(--paper); border: 1px solid var(--rule); border-radius: 10px;
  box-shadow: var(--shadow); margin-bottom: 1rem; overflow: hidden; }
.card__head { display: flex; align-items: center; justify-content: space-between; gap: .75rem;
  padding: .8rem 1rem .65rem; border-bottom: 1px solid var(--rule); }
.card__head h2 { font-size: .95rem; font-weight: 700; margin: 0; border: none; padding: 0; }
.card__meta { font-size: .72rem; color: var(--ink-dim); white-space: nowrap; }
.card__body { padding: .85rem 1rem 1rem; }
.val-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .5rem; }
.val-item { background: var(--paper-sunken); border-radius: 8px; padding: .55rem .4rem; text-align: center; }
.val-item .label { font-size: .68rem; color: var(--ink-dim); }
.val-item .value { font-size: 1.02rem; font-weight: 700; margin-top: .15rem; font-variant-numeric: tabular-nums; }
.val-source { margin-top: .6rem; font-size: .7rem; color: var(--ink-dim); }
.finding { display: flex; gap: .6rem; padding: .65rem 0; border-bottom: 1px solid var(--rule); }
.finding:last-child { border-bottom: none; padding-bottom: 0; }
.finding:first-child { padding-top: 0; }
.finding__stripe { flex-shrink: 0; width: 3px; border-radius: 3px; align-self: stretch; }
.finding.ok .finding__stripe { background: var(--green); }
.finding.alert .finding__stripe { background: var(--red); }
.finding__label-row { display: flex; align-items: center; gap: .45rem; margin-bottom: .2rem; flex-wrap: wrap; }
.finding__label { font-size: .82rem; font-weight: 700; }
.pill { font-size: .68rem; font-weight: 700; padding: .1rem .55rem; border-radius: 999px; flex-shrink: 0; }
.pill.ok { color: var(--green); background: var(--paper-sunken); }
.pill.alert { color: var(--red-ink); background: var(--red-soft); }
.finding__detail { font-size: .84rem; color: var(--ink-dim); overflow-wrap: break-word; }
.reason-pin { display: flex; gap: .6rem; background: var(--accent-soft); border: 1px solid var(--accent);
  border-radius: 10px; padding: .75rem .9rem; margin-bottom: 1rem; }
.reason-pin__body { min-width: 0; flex: 1; }
.reason-pin__label-row { display: flex; justify-content: space-between; gap: .5rem; margin-bottom: .2rem; }
.reason-pin__label { font-size: .72rem; font-weight: 700; color: var(--accent); }
.reason-pin__date { font-size: .68rem; color: var(--ink-dim); white-space: nowrap; }
.reason-pin__text { font-size: .88rem; overflow-wrap: break-word; }
.holdings-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; margin-bottom: .8rem; }
.holdings-grid .val-item .value { font-size: .92rem; }
.trade-row { display: flex; align-items: center; gap: .6rem; padding: .4rem 0;
  border-bottom: 1px solid var(--rule); font-size: .8rem; }
.trade-row:last-child { border-bottom: none; }
.trade-row__tag { font-size: .68rem; font-weight: 700; padding: .08rem .45rem; border-radius: 5px; flex-shrink: 0; }
.trade-row__tag.buy { color: var(--red-ink); background: var(--red-soft); }
.trade-row__tag.sell { color: var(--green); background: var(--paper-sunken); }
.trade-row__mid { flex: 1; min-width: 0; }
.trade-row__date { color: var(--ink-dim); font-size: .74rem; flex-shrink: 0; }
.trade-list-details { margin-top: .3rem; }
.trade-list-details summary { cursor: pointer; font-size: .82rem; font-weight: 600;
  color: var(--accent); padding: .3rem 0; }
.trade-list-details summary::marker { color: var(--accent); }
/* 庫存買賣圖表（2026-08-09，嫁接進個股清單/詳情頁）：.spark 是清單頁
   每列的迷你走勢，.combo-chart 是詳情頁「走勢與力道」卡片裡的價格
   折線＋買賣力道長條圖，色彩沿用既有 .trade-row__tag／_delta_badge
   同一套紅漲綠跌語意，不另外配色。 */
.spark { display: block; vertical-align: middle; flex-shrink: 0; }
.combo-chart { width: 100%; height: auto; background: var(--paper-sunken);
                border-radius: 8px; margin: .5rem 0; }
.chart-label { font-size: 11px; fill: var(--ink-dim); font-variant-numeric: tabular-nums; }
.chart-label-latest { fill: var(--accent); font-weight: 700; }
.chart-label-avg { fill: var(--amber); font-weight: 700; }
.chart-stats { display: flex; justify-content: flex-end; gap: 1.1rem; flex-wrap: wrap;
                margin-bottom: .4rem; }
.chart-stats .stat { text-align: right; }
.chart-stats .stat b { display: block; font-size: 1rem; font-weight: 700;
                         font-variant-numeric: tabular-nums; }
.chart-stats .stat span { font-size: .68rem; color: var(--ink-dim); }
.chart-bar-label { font-size: 9px; font-weight: 700; text-anchor: middle;
                     font-variant-numeric: tabular-nums; }
.note { padding: .6rem 0; border-bottom: 1px solid var(--rule); }
.note:last-child { border-bottom: none; padding-bottom: 0; }
.note:first-child { padding-top: 0; }
.note__meta { display: flex; justify-content: space-between; gap: .5rem; font-size: .7rem;
  color: var(--ink-dim); margin-bottom: .15rem; }
.note__text { font-size: .85rem; overflow-wrap: break-word; white-space: pre-wrap; }
@media (min-width: 560px) {
  .val-grid { grid-template-columns: repeat(4, 1fr); }
}
"""

PWA_META = (
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="apple-mobile-web-app-title" content="AlphaVibe">'
    '<meta name="color-scheme" content="light dark">'
    '<meta name="theme-color" content="#f8f9fa" media="(prefers-color-scheme: light)">'
    '<meta name="theme-color" content="#1d2024" media="(prefers-color-scheme: dark)">'
    '<link rel="apple-touch-icon" href="apple-touch-icon.png">'
)


def make_icon_png(size=180, rgb=(25, 113, 194)):
    """以標準庫生成純色 PNG（iOS apple-touch-icon 用），零外部依賴。"""
    def chunk(tag, data):
        payload = tag + data
        return (struct.pack(">I", len(data)) + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))

    row = b"\x00" + bytes(rgb) * size          # 每列前綴 filter byte 0
    raw = row * size
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def esc(value):
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def clip(value, limit=80):
    if value is None or value == "":
        return "—"
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return html.escape(text)


def reason_html(value, summary_limit=40):
    """「理由」欄位用：短文字直接顯示全文；超過門檻改用 <details> 包住，
    摘要當展開按鈕、展開後看全文——不像 clip() 永遠截斷看不到後面。"""
    if value is None or value == "":
        return "—"
    text = str(value)
    if len(text) <= summary_limit:
        return html.escape(text)
    summary = html.escape(text[:summary_limit])
    full = html.escape(text)
    return ("<details class=\"reason\"><summary>%s…</summary>"
            "<div class=\"reason-full\">%s</div></details>" % (summary, full))


def _render_holdings_section(store):
    """「我的庫存與分析」／FR-058「觀察名單／庫存總覽」共用同一份市值／
    持股比例／主題集中度計算邏輯（2026-07-29 從 render() 抽出）：規格明講
    「兩套邏輯不能算出不同答案」，抽成單一函式讓 render()（舊版全頁）與
    render_dashboard()（新版方案A首頁）都呼叫同一份計算，不會日後各自
    改壞而answer分歧。獨立查一次 store，不依賴呼叫端先算好的中間變數。

    回傳完整的 `<details id="section-holdings">...</details>` 字串，呼叫端
    直接 append 即可。
    """
    stances = store.list_stances()
    stance_by_code = {s["code"]: s for s in stances}
    holdings = store.get_holdings()

    parts = []
    parts.append("<details class=\"section\" id=\"section-holdings\" open>"
                 "<summary><h2>我的庫存與分析%s</h2></summary>"
                 % ("（%s）" % esc(holdings["snapshot_date"])
                    if holdings["snapshot_date"] else ""))
    if holdings["holdings"]:
        price_map = store.get_stock_prices()
        industry_map = store.get_stock_industries()
        theme_map = store.get_stock_theme()

        # 市值：股數 × 快取股價；查不到股價（或無股數）的持股不計入市值，
        # 也不計入下面持股比例的分母——分母只算「有市值資料」的部分。
        market_values = {}
        for h in holdings["holdings"]:
            price_info = price_map.get(h["code"])
            if price_info and h.get("shares") is not None:
                market_values[h["code"]] = h["shares"] * price_info["price"]
        total_value = sum(market_values.values())

        # 主題集中度：依 stock_themes 標籤把已有市值的持股分組加總，未標記
        # 主題的持股不計入任何一組（只影響此摘要，不影響上面逐檔顯示）。
        theme_totals = {}
        for h in holdings["holdings"]:
            value = market_values.get(h["code"])
            if value is None:
                continue
            theme = theme_map.get(h["code"], {}).get("theme")
            if theme:
                theme_totals[theme] = theme_totals.get(theme, 0) + value

        if price_map:
            latest_price_update = max(v["updated_at"] for v in price_map.values())
            price_meta = "價格更新時間：%s" % esc(latest_price_update)
        else:
            price_meta = "尚未更新股價，執行 refresh_holdings_prices"
        parts.append("<p class=\"meta\">%s ｜ 僅計入已更新價格的持股，"
                     "持股比例可能不含全部庫存</p>" % price_meta)

        parts.append("<div class=\"tablewrap\"><table><thead><tr><th>代碼</th><th>名稱</th>"
                     "<th>產業別</th><th>投資主題</th><th>股數</th><th>平均成本</th><th>市值</th>"
                     "<th>持股比例</th><th>立場</th><th>估值依據</th><th>理由</th>"
                     "<th>更新日期</th></tr></thead><tbody>")
        for h in holdings["holdings"]:
            match = stance_by_code.get(h["code"])
            if match:
                color = STANCE_COLORS.get(match["stance"], DEFAULT_STANCE_COLOR)
                stance_text = esc(match["stance"])
                valuation_text = esc(match["valuation_metric"])
                reason_text = reason_html(match["reason"])
                date_text = esc(match["date"])
            else:
                color = DEFAULT_STANCE_COLOR
                stance_text = valuation_text = reason_text = date_text = "尚無分析"

            industry_text = esc(industry_map.get(h["code"], {}).get("industry_category"))
            theme_text = esc(theme_map.get(h["code"], {}).get("theme"))

            value = market_values.get(h["code"])
            if value is not None:
                value_text = "%s 元" % format(value, ",.0f")
                ratio = (value / total_value * 100) if total_value else None
                ratio_text = ("%.1f%%" % ratio) if ratio is not None else "—"
            else:
                value_text = "未更新價格"
                ratio_text = "未更新價格"

            parts.append(
                "<tr><td data-label=\"代碼\">"
                "<a href=\"/dashboard/stock/%s\">%s</a></td>"
                "<td data-label=\"名稱\">%s</td>"
                "<td data-label=\"產業別\">%s</td><td data-label=\"投資主題\">%s</td>"
                "<td data-label=\"股數\">%s</td><td data-label=\"平均成本\">%s</td>"
                "<td data-label=\"市值\">%s</td><td data-label=\"持股比例\">%s</td>"
                "<td data-label=\"立場\" class=\"stance\" style=\"color:%s\">%s</td>"
                "<td data-label=\"估值依據\">%s</td><td data-label=\"理由\">%s</td>"
                "<td data-label=\"更新日期\">%s</td></tr>"
                % (esc(urllib.parse.quote(h["code"], safe="")), esc(h["code"]), esc(h["name"]),
                   industry_text, theme_text,
                   esc(h["shares"]), esc(h["avg_cost"]), value_text, ratio_text,
                   color, stance_text, valuation_text, reason_text, date_text))
        parts.append("</tbody></table></div>")

        if theme_totals and total_value:
            parts.append("<h3>主題集中度</h3>"
                         "<div class=\"tablewrap\"><table><thead><tr><th>投資主題</th>"
                         "<th>合計市值</th><th>佔投資組合比例</th></tr></thead><tbody>")
            for theme, value in sorted(theme_totals.items(), key=lambda kv: -kv[1]):
                ratio = value / total_value * 100
                parts.append(
                    "<tr><td data-label=\"投資主題\">%s</td>"
                    "<td data-label=\"合計市值\">%s 元</td>"
                    "<td data-label=\"佔投資組合比例\">%.1f%%</td></tr>"
                    % (esc(theme), format(value, ",.0f"), ratio))
            parts.append("</tbody></table></div>")
            parts.append("<p class=\"meta\">僅計入已標記主題且已更新價格的持股；"
                         "單一主題參考上限 50%，單一股票參考上限 15%（見上表持股比例）</p>")
    else:
        parts.append("<p class=\"empty\">尚無持股快照。</p>")
    parts.append("</details>")
    return "".join(parts)


def _render_watchlist_only_section(store):
    """「純觀察標的（無庫存）」（2026-07-30，PO反饋補齊儀表板缺口）：
    render_dashboard() 的「觀察名單／庫存總覽」重用 _render_holdings_
    section() 之後，只會顯示有庫存的持股——`stances` 表裡純觀察性質、
    還沒真的買的立場（例如研究過覺得值得追蹤）完全不會出現在新首頁，
    只有切到 /report-classic 才看得到。這個函式補上這塊：立場存在但
    代碼不在目前庫存清單裡的標的，列成一張簡表。刻意不顯示市值／持股
    比例／主題集中度等庫存專屬欄位——這些標的沒有庫存資料，硬要顯示
    沒有意義（沿用 render() 舊版「觀察名單立場」區塊的篩選邏輯，但欄位
    精簡到代碼／名稱／立場／理由／更新日期）。

    回傳完整的 `<details id="section-watchlist-only">...</details>` 字串，
    呼叫端直接 append 即可。獨立查一次 store，不依賴呼叫端先算好的中間
    變數（跟 _render_holdings_section 一致的風格）。
    """
    stances = store.list_stances()
    holdings = store.get_holdings()
    holding_codes = set(h["code"] for h in holdings["holdings"])
    watchlist_only = [s for s in stances if s["code"] not in holding_codes]

    parts = []
    parts.append("<details class=\"section\" id=\"section-watchlist-only\" open>"
                 "<summary><h2>純觀察標的（無庫存）</h2></summary>")
    if watchlist_only:
        parts.append("<div class=\"tablewrap\"><table><thead><tr><th>代碼</th><th>名稱</th>"
                     "<th>立場</th><th>理由</th><th>更新日期</th></tr></thead><tbody>")
        for s in watchlist_only:
            color = STANCE_COLORS.get(s["stance"], DEFAULT_STANCE_COLOR)
            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"立場\" class=\"stance\" style=\"color:%s\">%s</td>"
                "<td data-label=\"理由\">%s</td><td data-label=\"更新日期\">%s</td></tr>"
                % (esc(s["code"]), esc(s["name"]), color, esc(s["stance"]),
                   reason_html(s["reason"]), esc(s["date"])))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">目前沒有純觀察、尚未建倉的標的。</p>")
    parts.append("</details>")
    return "".join(parts)


def render(store):
    stances = store.list_stances()
    comments = store.recent_comments(limit=20)["results"]
    modules = store.list_philosophy()["modules"]
    snapshots = store.list_latest_snapshots()
    holdings = store.get_holdings()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 持股與立場依代碼合併：庫存分析要能一眼對應，不用滑動比對兩張表
    # （stance_by_code 的合併查詢移進 _render_holdings_section 內部自算，
    # 這裡只需要 holding_codes 篩掉「觀察名單立場」裡已經是持股的部分）
    holding_codes = set(h["code"] for h in holdings["holdings"])
    watchlist_stances = [s for s in stances if s["code"] not in holding_codes]

    parts = []
    parts.append("<!doctype html><html lang=\"zh-Hant\"><head>"
                 "<meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                 + PWA_META +
                 "<title>AlphaVibe 知識庫檢視</title>"
                 "<style>%s</style></head><body>" % CSS)
    parts.append("<h1>AlphaVibe 知識庫檢視</h1>")
    parts.append("<p class=\"meta\">產出時間 %s ｜ 立場 %d 檔 ｜ 分析快照 %d 檔 ｜ "
                 "持股快照 %d 檔 ｜ 近期評論 %d 則 ｜ 哲學模組 %d 個 ｜ "
                 "唯讀快照，重跑 report.py 更新</p>"
                 % (now, len(stances), len(snapshots), holdings["count"],
                    len(comments), len(modules)))
    parts.append("<p class=\"meta\">本頁為研究輔助資訊，非投資建議。</p>")

    parts.append(
        "<p><a href=\"/screen\" class=\"btn\">第一層選股篩選 →</a>"
        "<a href=\"/market-scan\" class=\"btn\">第二層全市場批次篩選 →</a></p>")

    parts.append(
        "<nav class=\"toc\">"
        "<a href=\"#section-stance\">觀察名單立場</a>"
        "<a href=\"#section-snapshots\">分析快照</a>"
        "<a href=\"#section-holdings\">我的庫存與分析</a>"
        "<a href=\"#section-comments\">近期評論</a>"
        "<a href=\"#section-philosophy\">哲學模組</a>"
        "</nav>")

    parts.append("<details class=\"section\" id=\"section-stance\" open>"
                 "<summary><h2>觀察名單立場（不含庫存持股，見下方庫存分析）</h2></summary>")
    if watchlist_stances:
        parts.append("<div class=\"tablewrap\"><table><thead><tr><th>代碼</th><th>名稱</th><th>立場</th>"
                     "<th>進場條件</th><th>估值依據</th><th>理由</th>"
                     "<th>日期</th><th>來源</th></tr></thead><tbody>")
        for s in watchlist_stances:
            color = STANCE_COLORS.get(s["stance"], DEFAULT_STANCE_COLOR)
            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"立場\" class=\"stance\" style=\"color:%s\">%s</td>"
                "<td data-label=\"進場條件\">%s</td><td data-label=\"估值依據\">%s</td>"
                "<td data-label=\"理由\">%s</td><td data-label=\"日期\">%s</td>"
                "<td data-label=\"來源\">%s</td></tr>"
                % (esc(s["code"]), esc(s["name"]), color, esc(s["stance"]),
                   esc(s["entry_condition"]), esc(s["valuation_metric"]),
                   reason_html(s["reason"]), esc(s["date"]), esc(s["source_ref"])))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">尚無立場資料——開始跟 Claude 聊，"
                     "確認入庫後這裡就會長出來。</p>")
    parts.append("</details>")

    parts.append("<details class=\"section\" id=\"section-snapshots\" open>"
                 "<summary><h2>分析快照（每檔最新一筆；歷次 diff 用 get_snapshots 或待 1c 儀表板）</h2></summary>")
    if snapshots:
        parts.append("<div class=\"tablewrap\"><table><thead><tr><th>代碼</th><th>名稱</th><th>日期</th>"
                     "<th>當時價</th><th>當時估值</th><th>驅動因素</th>"
                     "<th>下檔風險</th><th>框架</th><th>來源數</th></tr></thead><tbody>")
        for sn in snapshots:
            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"日期\">%s</td><td data-label=\"當時價\">%s</td>"
                "<td data-label=\"當時估值\">%s</td><td data-label=\"驅動因素\">%s</td>"
                "<td data-label=\"下檔風險\">%s</td><td data-label=\"框架\">%s</td>"
                "<td data-label=\"來源數\">%s</td></tr>"
                % (esc(sn["code"]), esc(sn["name"]), esc(sn["snapshot_date"]),
                   esc(sn["price_at_time"]), esc(sn["valuation_at_time"]),
                   clip(sn["thesis"]), clip(sn["risks"]),
                   esc(sn["framework_version"]), sn["source_count"]))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">尚無分析快照。</p>")
    parts.append("</details>")

    parts.append(_render_holdings_section(store))

    parts.append("<details class=\"section\" id=\"section-comments\">"
                 "<summary><h2>Layer 3 最近評論（最多 20 則）</h2></summary>")
    if comments:
        for c in comments:
            symbols = (" ｜ " + esc(c["symbols"])) if c["symbols"] else ""
            parts.append(
                "<div class=\"comment\"><div class=\"head\">"
                "<span class=\"tag\">%s</span>%s%s</div><div>%s</div></div>"
                % (esc(c["source_tag"]), esc(c["date"]), symbols, esc(c["body"])))
    else:
        parts.append("<p class=\"empty\">尚無評論資料。</p>")
    parts.append("</details>")

    parts.append("<details class=\"section\" id=\"section-philosophy\" open>"
                 "<summary><h2>Layer 1 哲學模組（點標題展開全文）</h2></summary>")
    if modules:
        for m in modules:
            content = store.get_philosophy(m["module"]).get("content", "")
            parts.append(
                "<details class=\"philomod\"><summary>%s（%d bytes）</summary>"
                "<pre>%s</pre></details>"
                % (esc(m["module"]), m["size"], esc(content)))
    else:
        parts.append("<p class=\"empty\">尚無哲學模組。</p>")
    parts.append("</details>")

    parts.append("</body></html>")
    return "".join(parts)


def _invalidation_text(invalidation):
    """把 frameworks.py 某個框架的 "invalidation" dict（FR-052 策略專屬層）
    轉成人話的「假說失效」說明句，供 render_dashboard() 策略設定區塊使用。

    語意方向跟 _format_condition_text() 的 entry 門檻相反：entry 門檻的
    子句用「且」串接（全部符合才算候選），這裡子句用「，或」串接
    （任一子條件成立即視為假說失效）——見 frameworks.py 檔頭說明。措辭
    要能通用轉換任何策略的 invalidation 欄位組合，不寫死特定策略文字。

    invalidation 為 None、空 dict、或全部 key 皆為 None／缺席時，回傳
    None，交由呼叫端決定顯示什麼預設文字（FR-052 是選配欄位，不是每個
    框架都要有）。
    """
    if not invalidation:
        return None
    clauses = []
    if invalidation.get("peg_min") is not None:
        clauses.append("PEG回升至&gt;=%s" % _fmt_num(invalidation["peg_min"]))
    if invalidation.get("drawdown_max") is not None:
        clauses.append("回檔收斂至&lt;%s%%" % _fmt_pct(invalidation["drawdown_max"]))
    if invalidation.get("revenue_yoy_max") is not None:
        clauses.append("營收年增率降至&lt;=%s%%" % _fmt_pct(invalidation["revenue_yoy_max"]))
    if not clauses:
        return None
    return "假說失效：" + "，或".join(clauses)


def _render_today_highlights_section(store, date):
    """FR-058「今日重點」：模組D檢視結果（module_d_results）中 suggested_action
    不為空的記錄——依 review_engine.run_module_d_batch() 的設計，這代表
    concern_flag=True 且算得出部位控制建議的項目，才是真正需要PO留意的
    （沒觸發任何檢視規則的「正常」記錄 suggested_action 恆為 None，不顯示
    在這裡，避免每天一堆正常結果淹沒真正的重點）。conflict_flag=True
    （跟既有立場或其他策略衝突）的記錄排最前面。"""
    results = store.get_module_d_results(date=date)["results"]
    highlights = [r for r in results if r.get("suggested_action") is not None]
    highlights.sort(key=lambda r: not r.get("conflict_flag"))

    parts = []
    parts.append("<details class=\"section\" id=\"section-today-highlights\" open>"
                 "<summary><h2>今日重點</h2></summary>")
    if highlights:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>檢視層</th><th>發現</th><th>建議動作</th>"
                     "<th>提醒</th></tr></thead><tbody>")
        for r in highlights:
            conflict = bool(r.get("conflict_flag"))
            row_style = " class=\"row-alert\"" if conflict else ""
            conflict_text = "⚠️ 立場衝突" if conflict else "—"
            parts.append(
                "<tr%s><td data-label=\"代碼\">%s</td><td data-label=\"檢視層\">%s</td>"
                "<td data-label=\"發現\">%s</td><td data-label=\"建議動作\">%s</td>"
                "<td data-label=\"提醒\">%s</td></tr>"
                % (row_style, esc(r["code"]), esc(r["trigger_type"]),
                   esc(r["finding"]), esc(r["suggested_action"]), conflict_text))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">今日無需特別留意的標的。</p>")
    parts.append("</details>")
    return "".join(parts)


def _render_new_candidates_section(store):
    """FR-058「今日新候選」：合併 frameworks.FRAMEWORKS 每套框架各自最新
    一次 market_scan 結果裡 meets_framework=1 的候選。同一代碼同時符合
    多套框架時，合併成一列，「符合策略」欄位用標籤（.tag）並列顯示，
    不重複列出兩列——沿用各框架各自的 get_latest_market_scan() 最新一次
    run（跟 /market-scan 頁面同一個「最近一次」概念，不額外限定日期，
    因為每套框架的排程/手動觸發時間不保證相同）。"""
    merged = {}
    order = []
    for fw in frameworks.FRAMEWORKS:
        latest = store.get_latest_market_scan(framework_id=fw["id"], meets_only=True)
        if not latest.get("found"):
            continue
        for r in latest["results"]:
            code = r["code"]
            if code not in merged:
                merged[code] = {"row": r, "labels": []}
                order.append(code)
            merged[code]["labels"].append(fw["label"])

    parts = []
    parts.append("<details class=\"section\" id=\"section-new-candidates\" open>"
                 "<summary><h2>今日新候選</h2></summary>")
    if order:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>"
                     "<th>符合策略</th><th>PER</th><th>營收年增率</th><th>PEG</th>"
                     "<th>回檔幅度</th><th>目前價</th></tr></thead><tbody>")
        for code in order:
            r = merged[code]["row"]
            tags = "".join("<span class=\"tag\">%s</span>" % esc(label)
                           for label in merged[code]["labels"])
            peg_text = ("%.2f" % r["peg"]) if r.get("peg") is not None else "—"
            yoy_text = ("%.1f%%" % (r["revenue_yoy"] * 100)) if r.get("revenue_yoy") is not None else "—"
            drawdown_text = ("%.1f%%" % (r["drawdown_pct"] * 100)) if r.get("drawdown_pct") is not None else "—"
            per_text = ("%.2f" % r["per"]) if r.get("per") is not None else "—"
            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"市場\">%s</td><td data-label=\"產業別\">%s</td>"
                "<td data-label=\"符合策略\">%s</td>"
                "<td data-label=\"PER\">%s</td><td data-label=\"營收年增率\">%s</td>"
                "<td data-label=\"PEG\">%s</td><td data-label=\"回檔幅度\">%s</td>"
                "<td data-label=\"目前價\">%s</td></tr>"
                % (esc(code), esc(r.get("name")), esc(r.get("market")), esc(r.get("industry")),
                   tags, per_text, yoy_text, peg_text, drawdown_text, esc(r.get("current_price"))))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">目前沒有符合任何策略門檻的候選。</p>")
    parts.append("</details>")
    return "".join(parts)


def _render_strategy_settings_section():
    """FR-058「策略設定」：條列 frameworks.FRAMEWORKS 每套策略的篩選門檻
    （沿用 _format_condition_text，跟 /screen、/market-scan 頁面同一套
    措辭，不重寫第二份文字邏輯）與策略專屬檢視規則（_invalidation_text
    轉譯 invalidation 欄位）。最後加一張純文字說明卡——依FR-049設計，
    策略新增/調整走跟AI對話討論後改 frameworks.py，這裡不做表單/按鈕。"""
    parts = []
    parts.append("<details class=\"section\" id=\"section-strategy-settings\">"
                 "<summary><h2>策略設定</h2></summary>")
    for fw in frameworks.FRAMEWORKS:
        condition_text = _format_condition_text(
            peg_threshold=fw.get("peg_max"), revenue_yoy_min=fw.get("revenue_yoy_min"),
            drawdown_min=fw.get("drawdown_min"), drawdown_max=fw.get("drawdown_max"),
            excess_drawdown_min=fw.get("excess_drawdown_min"))
        invalidation_text = _invalidation_text(fw.get("invalidation")) or "尚未定義策略專屬檢視規則"
        parts.append(
            "<div class=\"comment\"><div class=\"head\">%s</div>"
            "<div>篩選門檻：%s</div><div>%s</div></div>"
            % (esc(fw["label"]), condition_text, invalidation_text))
    parts.append(
        "<div class=\"comment\"><div class=\"head\">＋新增或調整策略</div>"
        "<div>策略不是填表單做出來的——先跟AI討論你觀察到的操作邏輯，"
        "定案後由AI把篩選門檻＋專屬檢視規則寫進 frameworks.py，"
        "你只需要確認結果</div></div>")
    parts.append("</details>")
    return "".join(parts)


_DASHBOARD_FORM_STYLE = ("display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;"
                         "margin:.6rem 0 1.2rem;")


def _render_quick_input_section():
    """FR-058「快速輸入」：只做3個有明確欄位結構的真表單（加自選股／記
    交易／貼老芋頭進出），POST到report_server.py新增的/dashboard/*路徑。
    刻意不做「貼資訊給AI歸檔」這種需要LLM理解的假表單——那個走Claude
    Code對話（既有場景3），不是這裡的網頁表單能做的事。"""
    parts = []
    parts.append("<details class=\"section\" id=\"section-quick-input\">"
                 "<summary><h2>快速輸入</h2></summary>")
    parts.append(
        "<h3>＋ 加自選股</h3>"
        "<form method=\"post\" action=\"/dashboard/watchlist\" style=\"%s\">"
        "<input name=\"code\" placeholder=\"代碼\" required>"
        "<input name=\"name\" placeholder=\"名稱（可選）\">"
        "<button type=\"submit\">加入</button></form>" % _DASHBOARD_FORM_STYLE)
    parts.append(
        "<h3>＋ 記一筆交易</h3>"
        "<form method=\"post\" action=\"/dashboard/trade\" style=\"%s\">"
        "<input name=\"code\" placeholder=\"代碼\" required>"
        "<input name=\"name\" placeholder=\"名稱（可選）\">"
        "<select name=\"action\"><option value=\"買\">買</option>"
        "<option value=\"賣\">賣</option></select>"
        "<input name=\"shares\" type=\"number\" step=\"1\" placeholder=\"股數\" required>"
        "<input name=\"price\" type=\"number\" step=\"0.01\" placeholder=\"價格\" required>"
        "<input name=\"date\" type=\"date\" required>"
        "<input name=\"add_sequence\" type=\"number\" step=\"1\" placeholder=\"加碼序號（可選）\">"
        "<button type=\"submit\">記錄</button></form>" % _DASHBOARD_FORM_STYLE)
    parts.append(
        "<h3>＋ 貼老芋頭進出</h3>"
        "<p class=\"meta\">整段貼上，不用逐欄位填。第一行是8位數日期"
        "（例如20260729），接著可以先寫一行原因、再接交易行（格式："
        "價格＋買進/賣出/買回/回補＋股數＋股/張＋名稱＋可選括號註記，"
        "例如「365賣出500股聯鈞（出清）」），空行會清空目前的原因。</p>"
        "<form method=\"post\" action=\"/dashboard/laoyutou\">"
        "<textarea name=\"text\" rows=\"8\" placeholder=\"20260729&#10;"
        "殺估值，獲利跟不上股價，清倉換股&#10;365賣出500股聯鈞（出清）\" "
        "required style=\"width:100%;font-family:inherit;font-size:.9rem;"
        "padding:.5rem .6rem;\"></textarea>"
        "<div style=\"margin-top:.5rem;\">"
        "<button type=\"submit\">解析並批次記錄</button></div></form>")
    parts.append(
        "<h3>＋ 貼交易明細表</h3>"
        "<p class=\"meta\">整段貼上券商App/網站匯出的交易明細表文字（PO自己"
        "的買賣紀錄，跟上面的老芋頭進出是不同的表）。每一列自帶日期，貼了"
        "送出就直接解析並批次記錄，會自動算好每筆買進的加碼序號，不用像"
        "貼庫存帳單那樣先預覽確認。</p>"
        "<form method=\"post\" action=\"/dashboard/tradeledger\">"
        "<textarea name=\"text\" rows=\"8\" placeholder=\"交易日期: 115/07/22 - "
        "115/07/29 頁次: 1&#10;115/07/22 OT賣 中美晶 50 242.50 ... "
        "12,085(付) k-0116-00\" required style=\"width:100%;"
        "font-family:inherit;font-size:.9rem;padding:.5rem .6rem;\">"
        "</textarea>"
        "<div style=\"margin-top:.5rem;\">"
        "<button type=\"submit\">解析並批次記錄</button></div></form>")
    parts.append(
        "<h3>＋ 貼CSV對帳單</h3>"
        "<p class=\"meta\">整段貼上券商App匯出的「已成交」CSV格式對帳單"
        "（PO自己的買賣紀錄，跟上面的交易明細表寫入同一張表，只是這份"
        "格式更乾淨：標準CSV、西元日期）。貼了送出就直接解析並批次記錄，"
        "會自動算好每筆買進的加碼序號，不用像貼庫存帳單那樣先預覽確認。</p>"
        "<form method=\"post\" action=\"/dashboard/tradecsv\">"
        "<textarea name=\"text\" rows=\"8\" placeholder=\"根據您篩選的結果，"
        "總計有4筆資料，當前資料為1-4筆，看更多請至國泰證券app查詢&#10;"
        "股名,日期,成交股數,淨收付金額,買賣別,成交價,成本,手續費,交易稅,"
        "融資金額/券擔保品,資自備款/券保證金,利息,稅款,券手續費/標借費,"
        "委託書號&#10;弘塑,2026/07/30,3,&quot;-6,542&quot;,現買,2180,"
        "&quot;6,540&quot;,2,0,0,0,0,0,0,k09QI\" required style=\"width:100%;"
        "font-family:inherit;font-size:.9rem;padding:.5rem .6rem;\">"
        "</textarea>"
        "<div style=\"margin-top:.5rem;\">"
        "<button type=\"submit\">解析並批次記錄</button></div></form>")
    parts.append(
        "<h3>＋ 貼庫存帳單</h3>"
        "<p class=\"meta\">整段貼上券商App/網站匯出的零股庫存表文字。解析後"
        "會先顯示預覽（含與上次快照的差異比對），確認無誤才會真的存入，"
        "不會貼上就直接寫入資料庫。</p>"
        "<form method=\"post\" action=\"/dashboard/holdings/preview\">"
        "<textarea name=\"text\" rows=\"8\" placeholder=\"股票代號 股票名稱 "
        "庫存股數 ...\" required style=\"width:100%;font-family:inherit;"
        "font-size:.9rem;padding:.5rem .6rem;\"></textarea>"
        "<div style=\"margin-top:.5rem;\">"
        "<button type=\"submit\">解析並預覽</button></div></form>")
    parts.append("</details>")
    return "".join(parts)


def render_dashboard(store, flash=None):
    """FR-058 儀表板（方案A單頁式）：取代 `/` 首頁原本顯示的 render()。
    由上到下——今日重點／今日新候選／觀察名單庫存總覽／策略設定／快速
    輸入。舊版完整檢視（觀察名單立場／分析快照／評論／哲學模組）整份
    保留在 render()，改掛 `/report-classic`（見 report_server.py），不刪除
    也不重寫其邏輯。

    取捨（2026-07-30）：「觀察名單／庫存總覽」直接重用 _render_holdings_
    section()，只顯示庫存持股（含市值/持股比例/主題集中度）；純觀察
    立場（有立場但未持有的標的）另外用 _render_watchlist_only_section()
    補一個精簡區塊接在庫存總覽之後（2026-07-30 PO反饋：原本這塊完全不
    在新首頁出現，只能切到 /report-classic 才看得到）。

    flash：3個快速輸入表單送出後，report_server.py 以303轉址帶查詢參數
    回這裡顯示的一次性訊息（成功或錯誤皆可，開頭「⚠️」視為錯誤樣式，
    否則視為成功樣式）。
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    today = datetime.date.today().isoformat()

    parts = []
    parts.append("<!doctype html><html lang=\"zh-Hant\"><head>"
                 "<meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                 + PWA_META +
                 "<title>AlphaVibe 儀表板</title>"
                 "<style>%s</style></head><body>" % CSS)
    parts.append("<h1>AlphaVibe 儀表板</h1>")
    parts.append("<p class=\"meta\">產出時間 %s ｜ 下拉重新整理更新最新資料</p>" % now)
    parts.append("<p class=\"meta\">本頁為研究輔助資訊，非投資建議。</p>")
    if flash:
        is_error = flash.startswith("⚠️")
        color = "var(--red)" if is_error else "var(--green)"
        parts.append("<p class=\"meta\" style=\"color:%s;font-weight:600;\">%s</p>"
                     % (color, esc(flash)))
    parts.append(
        "<p><a href=\"/dashboard/stocks\" class=\"btn\">持股與自選清單 →</a>"
        "<a href=\"/report-classic\" class=\"btn-muted\">完整舊版檢視 →</a>"
        "<a href=\"/screen\" class=\"btn\">第一層選股篩選 →</a>"
        "<a href=\"/market-scan\" class=\"btn\">第二層全市場批次篩選 →</a></p>")
    parts.append(
        "<nav class=\"toc\">"
        "<a href=\"#section-today-highlights\">今日重點</a>"
        "<a href=\"#section-new-candidates\">今日新候選</a>"
        "<a href=\"#section-holdings\">觀察名單／庫存總覽</a>"
        "<a href=\"#section-watchlist-only\">純觀察標的（無庫存）</a>"
        "<a href=\"#section-strategy-settings\">策略設定</a>"
        "<a href=\"#section-quick-input\">快速輸入</a>"
        "</nav>")

    parts.append(_render_today_highlights_section(store, today))
    parts.append(_render_new_candidates_section(store))
    parts.append(_render_holdings_section(store))
    parts.append(_render_watchlist_only_section(store))
    parts.append(_render_strategy_settings_section())
    parts.append(_render_quick_input_section())

    parts.append("</body></html>")
    return "".join(parts)


STOCKLIST_PAGE_SIZE = 10

_NOTE_TAGS = ("心得", "買進理由", "交易備註")


def _fmt_price(value):
    """個股清單/詳情頁的價格顯示：四捨五入到2位小數、去除多餘尾端0
    （1580.0→"1,580"、93.6→"93.6"），None顯示「—」。跟_fmt_num()不同
    （那個是給門檻文字用的，這裡額外要千分位）。"""
    if value is None:
        return "—"
    text = format(round(value, 2), ",.2f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _delta_badge(delta_pct):
    """回傳 (css class, 顯示文字)。delta_pct 為 None（查不到price或
    prev_close）時顯示「—」、無漲跌class。台股慣例紅漲綠跌：is-up（漲）
    用 var(--red)，is-down（跌）用 var(--green)（token定義見CSS常數
    「個股清單頁／詳情頁」段落），跟既有STANCE_COLORS的偏多紅/偏空綠
    同一語意，不是憑空新配色。"""
    if delta_pct is None:
        return "", "—"
    if delta_pct > 0:
        return "is-up", "+%.2f%%" % delta_pct
    if delta_pct < 0:
        return "is-down", "%.2f%%" % delta_pct
    return "", "0.00%"


def _latest_module_d_batch(store, code):
    """回傳「最新一批」Module D檢視結果：同一次背景刷新（review_engine.
    run_module_d_review）寫入的所有列共用同一個checked_at時間戳，可能是
    通用層2筆＋策略層N筆＋老芋頭層0或1筆——不能把歷史所有批次的列混在
    一起顯示（見派工說明）。get_module_d_results()本身已依checked_at
    DESC排序，取第一筆的checked_at當「最新批次」的判準，篩出同批次
    全部列即可，不需要另外排序。"""
    rows = store.get_module_d_results(code=code, limit=50)["results"]
    if not rows:
        return []
    latest_checked_at = rows[0]["checked_at"]
    return [r for r in rows if r["checked_at"] == latest_checked_at]


def _row_status_text(latest_batch):
    """清單頁每列的一行狀態摘要：優先顯示需留意（concern_flag=True）的
    發現內容，沒有需留意項目則顯示第一筆檢視結果（例如「下檔風險可控」
    這類正常訊息），完全沒有資料則提示尚在等待背景刷新。"""
    if not latest_batch:
        return "尚無檢視資料，稍後將自動更新"
    concerns = [r for r in latest_batch if r.get("concern_flag")]
    pick = concerns[0] if concerns else latest_batch[0]
    return pick["finding"]


def _tracked_stock_rows(store):
    """清單頁資料來源：庫存（get_holdings，最新快照）∪ 立場（list_stances，
    每代碼最新一筆，涵蓋研究中/觀察/偏多/偏空各種立場文字）去重後的代碼
    清單——跟 review_engine.run_module_d_batch() 的批次範圍公式完全一致
    （同一套「PO在追蹤什麼」定義，不另外發明一套）。回傳每筆含
    code/name/is_holding/price/delta_pct/has_concern/status_text 的
    dict 清單，依代碼首次出現順序（庫存優先於純立場）。"""
    stances = store.list_stances()
    stance_by_code = {s["code"]: s for s in stances}
    holdings = store.get_holdings()["holdings"]
    holding_codes = set(h["code"] for h in holdings)
    holding_by_code = {h["code"]: h for h in holdings}
    all_codes = list(dict.fromkeys(
        [h["code"] for h in holdings] + [s["code"] for s in stances]))
    price_map = store.get_stock_prices()

    rows = []
    for code in all_codes:
        is_holding = code in holding_codes
        name = None
        if code in holding_by_code:
            name = holding_by_code[code].get("name")
        if not name and code in stance_by_code:
            name = stance_by_code[code].get("name")
        price_info = price_map.get(code)
        price = price_info["price"] if price_info else None
        prev_close = price_info.get("prev_close") if price_info else None
        delta_pct = None
        if price is not None and prev_close:
            delta_pct = (price - prev_close) / prev_close * 100
        latest_batch = _latest_module_d_batch(store, code)
        # 迷你走勢（2026-08-09新增）：讀快取股價歷史，只取最近60天——
        # 清單頁每列只要「近期形狀」，不需要跟詳情頁一樣的完整範圍，
        # 且點數少SVG較輕，一次渲染10列不會太重。純本地讀，不即時查價。
        spark_html = _render_sparkline_svg(
            _sparkline_points(store.get_cached_price_history(code, limit_days=60), price_info))
        rows.append({
            "code": code, "name": name, "is_holding": is_holding,
            "price": price, "delta_pct": delta_pct,
            "has_concern": any(r.get("concern_flag") for r in latest_batch),
            "status_text": _row_status_text(latest_batch),
            "spark_html": spark_html,
        })
    return rows


def _stocklist_link(filter_key, query, page):
    params = []
    if filter_key and filter_key != "all":
        params.append("filter=" + urllib.parse.quote(filter_key))
    if query:
        params.append("q=" + urllib.parse.quote(query))
    if page and page != 1:
        params.append("page=%d" % page)
    return "/dashboard/stocks" + ("?" + "&".join(params) if params else "")


def render_stock_list_page(store, filter_key="all", query="", page=1, flash=None):
    """個股清單頁（GET /dashboard/stocks，2026-08-01新增）：庫存＋研究中
    標的清單，分批顯示（一次10筆），可依全部/庫存中/研究中篩選，可搜尋
    代碼/名稱/PO寫過的心得內容（後者重用store.search_comments的FTS5
    全文檢索，symbols欄位解析成代碼集合後跟目前清單取交集）。純GET
    query string帶filter/q/page狀態，不用session，維持本專案整頁送出、
    無JS的既有技術棧（比照render_dashboard()等既有頁面的風格）。
    """
    if filter_key not in ("all", "holdings", "research"):
        filter_key = "all"
    query = (query or "").strip()

    all_rows = _tracked_stock_rows(store)
    holdings_count = sum(1 for r in all_rows if r["is_holding"])
    research_count = len(all_rows) - holdings_count

    if filter_key == "holdings":
        rows = [r for r in all_rows if r["is_holding"]]
    elif filter_key == "research":
        rows = [r for r in all_rows if not r["is_holding"]]
    else:
        rows = all_rows

    if query:
        comment_hit_codes = set()
        if len(query) >= 3:
            hits = store.search_comments(query, limit=100).get("results") or []
            for h in hits:
                for part in re.split(r"[,，\s]+", h.get("symbols") or ""):
                    if part:
                        comment_hit_codes.add(part)
        rows = [r for r in rows
                if query in (r["code"] or "") or query in (r["name"] or "")
                or r["code"] in comment_hit_codes]

    total = len(rows)
    total_pages = max(1, (total + STOCKLIST_PAGE_SIZE - 1) // STOCKLIST_PAGE_SIZE)
    page = max(1, min(page or 1, total_pages))
    start = (page - 1) * STOCKLIST_PAGE_SIZE
    page_rows = rows[start:start + STOCKLIST_PAGE_SIZE]

    parts = [_screen_page_head("持股與自選")]
    parts.append("<p class=\"meta\"><a href=\"/\">← 回儀表板</a></p>")
    parts.append("<h1>持股與自選</h1>")
    parts.append("<p class=\"meta\">共 %d 檔（%d 檔庫存＋%d 檔研究中）</p>"
                 % (len(all_rows), holdings_count, research_count))
    if flash:
        is_error = flash.startswith("⚠️")
        color = "var(--red)" if is_error else "var(--green)"
        parts.append("<p class=\"meta\" style=\"color:%s;font-weight:600;\">%s</p>"
                     % (color, esc(flash)))

    parts.append(
        "<form method=\"get\" action=\"/dashboard/stocks\" class=\"stocklist-search\">"
        "<input type=\"hidden\" name=\"filter\" value=\"%s\">"
        "<input type=\"text\" name=\"q\" value=\"%s\" "
        "placeholder=\"搜尋股票代碼/名稱，或搜尋你寫過的心得內容…\">"
        "<button type=\"submit\" class=\"btn-muted\" style=\"margin:0;\">搜尋</button>"
        "</form>" % (esc(filter_key), esc(query)))

    parts.append(
        "<form method=\"post\" action=\"/dashboard/stocks/add\" class=\"stocklist-add\">"
        "<input type=\"text\" name=\"input\" "
        "placeholder=\"輸入還沒追蹤的股票代碼/名稱，開始研究……\" required>"
        "<button type=\"submit\" class=\"btn\" style=\"margin:0;\">加入研究</button>"
        "</form>")

    parts.append("<div class=\"filter-tabs\">")
    for key, label, count in (("all", "全部", len(all_rows)),
                              ("holdings", "庫存中", holdings_count),
                              ("research", "研究中", research_count)):
        active = " active" if key == filter_key else ""
        parts.append(
            "<a class=\"filter-tab%s\" href=\"%s\">%s <span>%d</span></a>"
            % (active, esc(_stocklist_link(key, query, 1)), esc(label), count))
    parts.append("</div>")

    parts.append("<div class=\"stock-list\">")
    if page_rows:
        for r in page_rows:
            concern_html = ('<span class="concern-dot" title="需留意"></span>'
                            if r["has_concern"] else '<span class="concern-slot"></span>')
            row_class = "stock-row has-concern" if r["has_concern"] else "stock-row"
            delta_cls, delta_text = _delta_badge(r["delta_pct"])
            href_code = esc(urllib.parse.quote(r["code"], safe=""))
            parts.append(
                "<a class=\"%s\" href=\"/dashboard/stock/%s\">%s"
                "<div class=\"stock-row__id\"><div class=\"stock-row__name-line\">"
                "<span class=\"stock-row__name\">%s</span>"
                "<span class=\"stock-row__code\">%s</span></div>"
                "<div class=\"stock-row__sub\">%s</div></div>"
                "%s"
                "<div class=\"stock-row__price\"><div class=\"stock-row__now\">%s</div>"
                "<div class=\"stock-row__delta %s\">%s</div></div></a>"
                % (row_class, href_code, concern_html,
                   esc(r["name"]), esc(r["code"]),
                   esc(r["status_text"]), r["spark_html"],
                   _fmt_price(r["price"]), delta_cls, esc(delta_text)))
    else:
        parts.append("<p class=\"empty\">%s</p>"
                     % ("沒有符合搜尋條件的標的。" if query else
                        "目前沒有追蹤中的標的，用上面「加入研究」開始追蹤第一檔。"))
    parts.append("</div>")

    if total:
        end = min(start + STOCKLIST_PAGE_SIZE, total)
        parts.append("<div class=\"pager\">")
        parts.append("<span>顯示 %d–%d / %d 檔</span>" % (start + 1, end, total))
        parts.append("<div class=\"pager__nav\">")
        if page > 1:
            parts.append("<a class=\"btn-muted\" href=\"%s\">上一批</a>"
                         % esc(_stocklist_link(filter_key, query, page - 1)))
        else:
            parts.append("<span class=\"btn-muted\" aria-disabled=\"true\">上一批</span>")
        if page < total_pages:
            parts.append("<a class=\"btn\" href=\"%s\">下一批</a>"
                         % esc(_stocklist_link(filter_key, query, page + 1)))
        else:
            parts.append("<span class=\"btn-muted\" aria-disabled=\"true\">下一批</span>")
        parts.append("</div></div>")

    parts.append("</body></html>")
    return "".join(parts)


def _valuation_source_text(data_source):
    mapping = {
        "twse_official": "官方來源（TWSE）",
        "tpex_official": "官方來源（TPEx）",
        "finmind_fallback": "FinMind備援資料",
    }
    return mapping.get(data_source, "來源未知")


def _module_d_card_html(latest_batch):
    """Module D檢視結果卡：依trigger_type分組呈現（見派工說明），狀態
    顏色二分（PO明確要求「有concern_flag的用警示色、沒有的用正常色」，
    不細分mockup裡出現的warn第三種狀態）：concern_flag=True
    →alert（var(--red)），否則→ok（var(--green)）。"""
    parts = []
    parts.append("<section class=\"card\"><div class=\"card__head\">"
                 "<h2>Module D 檢視</h2>"
                 "<span class=\"card__meta\">%s</span></div><div class=\"card__body\">"
                 % ("%d 項" % len(latest_batch) if latest_batch else "尚無資料"))
    if latest_batch:
        groups = {}
        order = []
        for r in latest_batch:
            key = r["trigger_type"]
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)
        for trigger_type in order:
            for r in groups[trigger_type]:
                cls = "alert" if r.get("concern_flag") else "ok"
                pill_text = "需留意" if r.get("concern_flag") else "正常"
                label = trigger_type
                if r.get("strategy_id"):
                    label = "%s／%s" % (trigger_type, r["strategy_id"])
                parts.append(
                    "<div class=\"finding %s\"><span class=\"finding__stripe\"></span>"
                    "<div class=\"finding__body\"><div class=\"finding__label-row\">"
                    "<span class=\"finding__label\">%s</span>"
                    "<span class=\"pill %s\">%s</span></div>"
                    "<div class=\"finding__detail\">%s</div></div></div>"
                    % (cls, esc(label), cls, pill_text, esc(r["finding"])))
    else:
        parts.append("<p class=\"empty\">尚無檢視資料，背景刷新完成後會顯示在這裡。</p>")
    parts.append("</div></section>")
    return "".join(parts)


def _portfolio_context(store):
    """跟 _render_holdings_section() 同一份市值計算邏輯（規格明講兩處
    不能算出不同答案，見該函式docstring）：市值＝股數×快取股價，查不到
    股價的持股不計入市值也不計入下面比例的分母。這裡只回傳detail頁
    需要的部分：最新庫存快照列、每檔市值、投資組合總市值。"""
    holdings = store.get_holdings()["holdings"]
    price_map = store.get_stock_prices()
    market_values = {}
    for h in holdings:
        info = price_map.get(h["code"])
        if info and h.get("shares") is not None:
            market_values[h["code"]] = h["shares"] * info["price"]
    total_value = sum(market_values.values())
    return holdings, market_values, total_value


def _combo_chart_aligned_trades(prices, entries):
    """把交易流水的 date 對齊到快取股價歷史（prices，已依 date 升冪排序，
    來自 store.get_cached_price_history()）的索引位置，供
    _render_combo_chart_svg() 畫買賣力道長條用。x 軸刻意用「第幾個交易日」
    的整數索引而非真實日曆天數（股價圖常見慣例，週末／休市日不佔版面，
    折線才不會出現無意義的長平段）。交易日期若剛好不是交易日，往前找
    最近一個有股價的交易日對齊；早於股價快取起點的交易日對不到，跳過
    （該筆仍會出現在下方精簡清單，只是圖上畫不出來）。"""
    date_index = {p["date"]: i for i, p in enumerate(prices)}
    sorted_dates = sorted(date_index)
    aligned = []
    for e in entries:
        idx = date_index.get(e["date"])
        if idx is None:
            earlier = [d for d in sorted_dates if d <= e["date"]]
            if not earlier:
                continue
            idx = date_index[earlier[-1]]
        aligned.append({"index": idx, "entry": e})
    return aligned


def _render_combo_chart_svg(prices, aligned, avg_cost=None, width=640, height=300):
    """個股詳情頁「走勢與力道」：上半部價格折線＋下半部買賣力道長條，
    共用同一條x軸（見 _combo_chart_aligned_trades 的索引對齊說明）。長條
    高度以當次交易金額（股數×價格）相對「這批交易裡金額最大那筆」的
    比例縮放，不是相對股價或市值——單純呈現「這幾筆交易彼此的力道差異」。
    資料源是 store.get_cached_price_history()（2026-08-09新增，背景刷新
    順便存下的快取，見kb_store.py），不即時查外部API——跟這個頁面其餘
    區塊「所有資料都讀快取」的既有原則一致，還沒刷新過的代碼這裡會顯示
    資料不足的提示。

    2026-08-09補（PO比對mockup反饋後補齊）：
    - 均價虛線（avg_cost，查不到時不畫，不臆測）。
    - 每筆交易在價格折線上標一個點＋往下拉一條虛線接到力道長條區，
      讓「這筆交易當時的價位」跟「這筆的力道」看得出是同一筆。
    - 力道長條區加橫軸（基準線＋每筆的刻度）＋每根長條上方標股數。
    - 折線右側维持高/低/最新價文字標籤；橫軸下方加最早/最新交易日期。
    """
    closes = [p["close"] for p in prices if p.get("close") is not None]
    if len(closes) < 2:
        return "<p class=\"empty\">股價快取資料不足，按上方「更新」刷新後即可看到走勢圖。</p>"
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or (abs(hi) * 0.02 or 1.0)
    n = len(prices)
    # pad_r 留寬給右側高/低/最新價/均價文字標籤（「均價 NNNN」比其他純數字
    # 標籤寬，用它決定pad_r，避免文字被SVG viewBox邊界裁掉）；pad_b 留給
    # 下方橫軸日期。
    pad_l, pad_r, pad_t, pad_b = 8.0, 70.0, 10.0, 22.0
    price_h = height * 0.52
    bar_h = height * 0.22
    gap = height - pad_t - price_h - bar_h - pad_b
    bar_area_top = pad_t + price_h + gap
    bar_base_y = bar_area_top + bar_h

    def x_at(i):
        return pad_l + (width - pad_l - pad_r) * i / max(n - 1, 1)

    def y_price(close):
        return pad_t + price_h * (1 - (close - lo) / span)

    coords = " ".join(
        "%.1f,%.1f" % (x_at(i), y_price(p["close"]))
        for i, p in enumerate(prices) if p.get("close") is not None)

    parts = ["<svg class=\"combo-chart\" viewBox=\"0 0 %d %d\" preserveAspectRatio="
            "\"xMidYMid meet\" role=\"img\" aria-label=\"價格與買賣力道圖\">"
            % (width, height)]
    parts.append("<polyline points=\"%s\" fill=\"none\" stroke=\"var(--accent)\" "
                "stroke-width=\"1.8\" stroke-linejoin=\"round\"/>" % coords)

    # 高／低／最新收盤價／均價文字標籤：只標數字，不畫格線，維持圖表簡潔。
    # 均價常跟高/低其中一個很接近（例如接近波段低點承接），y座標算出來
    # 太近會疊字看不清楚——收集全部標籤後統一做最小間距碰撞閃避
    # （由上到下掃一輪，太近的往下推開），而不是各自獨立畫。
    label_x = width - pad_r + 6
    latest_close = next(p["close"] for p in reversed(prices) if p.get("close") is not None)
    if avg_cost is not None and lo <= avg_cost <= hi:
        avg_y = y_price(avg_cost)
        parts.append("<line x1=\"%.1f\" y1=\"%.1f\" x2=\"%.1f\" y2=\"%.1f\" "
                    "stroke=\"var(--amber)\" stroke-width=\"1.2\" stroke-dasharray=\"5,3\"/>"
                    % (pad_l, avg_y, width - pad_r, avg_y))

    labels = [(y_price(hi), esc(_fmt_num(hi)), "chart-label")]
    if lo < latest_close < hi:
        labels.append((y_price(latest_close), esc(_fmt_num(latest_close)),
                       "chart-label chart-label-latest"))
    if avg_cost is not None and lo <= avg_cost <= hi:
        labels.append((y_price(avg_cost), "均價 %s" % esc(_fmt_num(avg_cost)),
                       "chart-label chart-label-avg"))
    labels.append((y_price(lo), esc(_fmt_num(lo)), "chart-label"))
    labels.sort(key=lambda item: item[0])
    min_gap = 11.0
    for i in range(1, len(labels)):
        prev_y = labels[i - 1][0]
        if labels[i][0] - prev_y < min_gap:
            labels[i] = (prev_y + min_gap, labels[i][1], labels[i][2])
    for y, text, css_class in labels:
        parts.append("<text x=\"%.1f\" y=\"%.1f\" class=\"%s\">%s</text>"
                    % (label_x, y + 4, css_class, text))

    # 每筆交易的價位點＋往下接到力道長條區的虛線，讓價位跟力道對得起來。
    for a in aligned:
        e, x = a["entry"], x_at(a["index"])
        y = y_price(e["price"])
        color = "var(--red)" if e["action"] == "買" else "var(--green)"
        parts.append("<line x1=\"%.1f\" y1=\"%.1f\" x2=\"%.1f\" y2=\"%.1f\" "
                    "stroke=\"var(--rule-strong)\" stroke-width=\"1\" "
                    "stroke-dasharray=\"2,2\"/>" % (x, y, x, bar_area_top))
        parts.append("<circle cx=\"%.1f\" cy=\"%.1f\" r=\"2.6\" fill=\"%s\"/>" % (x, y, color))

    max_value = max((abs(a["entry"]["shares"] * a["entry"]["price"]) for a in aligned),
                    default=0) or 1.0
    bar_w = max(2.0, (width - pad_l - pad_r) / max(n, 1) * 0.6)
    for a in aligned:
        e = a["entry"]
        value = e["shares"] * e["price"]
        bh = bar_h * min(1.0, abs(value) / max_value)
        color = "var(--red)" if e["action"] == "買" else "var(--green)"
        x = x_at(a["index"]) - bar_w / 2
        parts.append(
            "<rect x=\"%.1f\" y=\"%.1f\" width=\"%.1f\" height=\"%.1f\" fill=\"%s\" "
            "opacity=\"0.85\"><title>%s %s %s股 @%s</title></rect>"
            % (x, bar_base_y - bh, bar_w, bh, color,
               esc(e["date"]), esc(e["action"]), esc(_fmt_num(e["shares"])),
               esc(_fmt_num(e["price"]))))
        parts.append(
            "<text x=\"%.1f\" y=\"%.1f\" class=\"chart-bar-label\" fill=\"%s\">%s</text>"
            % (x_at(a["index"]), bar_base_y - bh - 4, color, esc(_fmt_num(e["shares"]))))

    # 橫軸：基準線＋每筆交易的刻度＋最早/最新交易日期。
    parts.append("<line x1=\"%.1f\" y1=\"%.1f\" x2=\"%.1f\" y2=\"%.1f\" "
                "stroke=\"var(--rule-strong)\" stroke-width=\"1.2\"/>"
                % (pad_l, bar_base_y, width - pad_r, bar_base_y))
    for a in aligned:
        x = x_at(a["index"])
        parts.append("<line x1=\"%.1f\" y1=\"%.1f\" x2=\"%.1f\" y2=\"%.1f\" "
                    "stroke=\"var(--ink-dim)\" stroke-width=\"1\"/>"
                    % (x, bar_base_y - 3, x, bar_base_y + 3))
    if aligned:
        first_date = min(a["entry"]["date"] for a in aligned)
        last_date = max(a["entry"]["date"] for a in aligned)
        parts.append("<text x=\"%.1f\" y=\"%.1f\" class=\"chart-label\" "
                    "text-anchor=\"start\">%s</text>"
                    % (pad_l, bar_base_y + 16, esc(first_date)))
        if last_date != first_date:
            parts.append("<text x=\"%.1f\" y=\"%.1f\" class=\"chart-label\" "
                        "text-anchor=\"end\">%s</text>"
                        % (width - pad_r, bar_base_y + 16, esc(last_date)))
    parts.append("</svg>")
    return "".join(parts)


def _sparkline_points(history, price_info):
    """個股清單頁每列迷你走勢用：優先用快取股價歷史（store.
    get_cached_price_history()，多日真實序列，2026-08-09新增），該代碼
    還沒被背景刷新過（history為空）時退回目前快取的單一股價當唯一的點
    （會因為只有1個點畫不出線，由 _render_sparkline_svg 顯示「資料不足」，
    不強行湊數）。"""
    if history:
        return [(p["date"], p["close"]) for p in history if p.get("close") is not None]
    if price_info and price_info.get("price") is not None:
        return [(price_info.get("price_date") or "", price_info["price"])]
    return []


def _render_sparkline_svg(points, width=64, height=28):
    """畫個股清單頁每列的迷你走勢。少於2個點畫不出線，回傳文字提示。
    台股慣例紅漲綠跌：終點價 >= 起點價描紅，反之描綠，跟 STANCE_COLORS／
    _delta_badge 同一套色彩語意。"""
    if len(points) < 2:
        return "<span class=\"meta\" style=\"font-size:.7rem;\">走勢資料不足</span>"
    prices = [p for _, p in points]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or (abs(hi) * 0.02 or 1.0)
    n = len(points)
    pad = 2.0
    coords = []
    for i, (_, price) in enumerate(points):
        x = pad + (width - 2 * pad) * i / (n - 1)
        y = pad + (height - 2 * pad) * (1 - (price - lo) / span)
        coords.append("%.1f,%.1f" % (x, y))
    color = "var(--red)" if points[-1][1] >= points[0][1] else "var(--green)"
    return ("<svg class=\"spark\" viewBox=\"0 0 %d %d\" width=\"%d\" height=\"%d\" "
           "role=\"img\" aria-label=\"走勢\">"
           "<polyline points=\"%s\" fill=\"none\" stroke=\"%s\" stroke-width=\"1.6\" "
           "stroke-linejoin=\"round\" stroke-linecap=\"round\"/></svg>"
           % (width, height, width, height, " ".join(coords), color))


def _avg_cost_for_chart(holding_row, entries):
    """走勢圖均價虛線用（2026-08-09新增）：優先用庫存快照本身記錄的
    avg_cost（較「正確」但實測常缺值，見CLAUDE.md教訓：22筆中僅1筆
    有值）；查不到時退回用交易流水裡全部買進的加權平均價估算（不扣
    賣出，遇到有出過清的標的這個估算值會失真，是刻意的簡化，跟原始
    mockup設計取捨一致，不做FIFO成本計算）。兩者都沒有就回傳None，
    呼叫端看到None就不畫線，不臆測。"""
    if holding_row and holding_row.get("avg_cost") is not None:
        return holding_row["avg_cost"]
    buy_shares = sum(e["shares"] for e in entries if e["action"] == "買")
    if not buy_shares:
        return None
    buy_value = sum(e["shares"] * e["price"] for e in entries if e["action"] == "買")
    return buy_value / buy_shares


def _chart_stats_html(current_price, avg_cost, avg_cost_label):
    """走勢圖右上方的現價／均價／浮動損益（2026-08-09，PO比對mockup反饋
    補上——原mockup的chart-stats一直沒接進正式頁面）。浮動損益＝
    (現價-均價)/均價，兩者缺一個就不算、不臆測，只顯示「—」。台股慣例
    紅漲綠跌：損益為正描紅、為負描綠，跟 _delta_badge／STANCE_COLORS
    同一套語意（這裡「正」是賺錢，跟賣出力道那個「紅=買」的語意是兩件
    事，各自獨立不衝突）。"""
    parts = ["<div class=\"chart-stats\">"
            "<div class=\"stat\"><b>%s</b><span>現價</span></div>" % esc(_fmt_price(current_price))]
    if avg_cost is not None:
        parts.append("<div class=\"stat\"><b style=\"color:var(--amber)\">%s</b>"
                     "<span>%s</span></div>" % (esc(_fmt_price(avg_cost)), esc(avg_cost_label)))
        if current_price is not None:
            pnl_pct = (current_price - avg_cost) / avg_cost * 100
            color = ("var(--red)" if pnl_pct > 0 else
                    "var(--green)" if pnl_pct < 0 else "var(--ink-dim)")
            parts.append("<div class=\"stat\"><b style=\"color:%s\">%+.1f%%</b>"
                         "<span>浮動損益</span></div>" % (color, pnl_pct))
    parts.append("</div>")
    return "".join(parts)


def _holdings_card_html(store, code):
    """持股與交易卡：純研究標的（不在最新庫存快照、也從無交易紀錄）整個
    不顯示這張卡片，回傳空字串由呼叫端不附加（見派工說明「不要顯示空
    表格」）。曾經持有過、目前已出清（有交易紀錄但不在最新快照）的
    標的，仍顯示交易歷史，只是持股統計格改顯示「目前未持有」而非空表格
    ——這是判斷取捨，理由見最終回報。"""
    holdings, market_values, total_value = _portfolio_context(store)
    holding_row = next((h for h in holdings if h["code"] == code), None)
    ledger = store.get_trade_ledger(code)["entries"]

    if holding_row is None and not ledger:
        return ""

    parts = []
    parts.append("<section class=\"card\"><div class=\"card__head\">"
                 "<h2>持股與交易</h2>"
                 "<span class=\"card__meta\">%s</span></div><div class=\"card__body\">"
                 % ("庫存中" if holding_row else "目前未持有"))
    if holding_row:
        value = market_values.get(code)
        value_text = ("%s 元" % format(value, ",.0f")) if value is not None else "未更新價格"
        ratio_text = ("%.1f%%" % (value / total_value * 100)
                     if value is not None and total_value else "—")
        parts.append(
            "<div class=\"holdings-grid\">"
            "<div class=\"val-item\"><div class=\"label\">庫存股數</div>"
            "<div class=\"value\">%s</div></div>"
            "<div class=\"val-item\"><div class=\"label\">市值</div>"
            "<div class=\"value\">%s</div></div>"
            "<div class=\"val-item\"><div class=\"label\">佔投資組合</div>"
            "<div class=\"value\">%s</div></div></div>"
            % (esc(holding_row["shares"]), esc(value_text), esc(ratio_text)))
    else:
        parts.append("<p class=\"meta\">目前未持有此標的（曾有交易記錄如下）。</p>")
    if ledger:
        # 走勢與力道（2026-08-09新增）：價格折線疊買賣力道長條，資料源是
        # store.get_cached_price_history()——背景刷新（refresh_price_and_
        # valuation）順便存下的快取，不即時查外部API，還沒刷新過時顯示
        # 資料不足提示（見 _render_combo_chart_svg docstring）。
        history = store.get_cached_price_history(code)
        aligned = _combo_chart_aligned_trades(history, ledger)
        avg_cost = _avg_cost_for_chart(holding_row, ledger)
        if holding_row and holding_row.get("avg_cost") is not None:
            avg_cost_label = "均價"
        else:
            avg_cost_label = "均價（%d筆）" % sum(1 for e in ledger if e["action"] == "買")
        price_info = store.get_stock_prices().get(code)
        current_price = price_info["price"] if price_info else None
        parts.append(_chart_stats_html(current_price, avg_cost, avg_cost_label))
        parts.append(_render_combo_chart_svg(history, aligned, avg_cost=avg_cost))
        if len(history) >= 2:
            parts.append(
                "<p class=\"meta\">"
                "<span style=\"color:var(--accent);\">●</span> 價格折線　"
                "<span style=\"color:var(--red);\">●</span> 買進力道　"
                "<span style=\"color:var(--green);\">●</span> 賣出力道　"
                "%s"
                "｜快取範圍 %s ~ %s</p>"
                % ("<span style=\"color:var(--amber);\">┄</span> 均價　"
                   if avg_cost is not None else "",
                   esc(history[0]["date"]), esc(history[-1]["date"])))
        # 交易明細用原生 <details> 收折（2026-08-09，PO比對mockup反饋）：
        # 預設收合，只在summary先告訴筆數，避免交易一多整張卡被清單撐長，
        # 跟頁面其餘 <details class="section"> 收折的既有慣例一致。
        parts.append(
            "<details class=\"trade-list-details\"><summary>交易明細（%d 筆）"
            "</summary><div class=\"trade-list\">" % len(ledger))
        for entry in reversed(ledger):  # get_trade_ledger回傳舊到新，這裡改新到舊顯示
            tag_cls = "buy" if entry["action"] == "買" else "sell"
            parts.append(
                "<div class=\"trade-row\"><span class=\"trade-row__tag %s\">%s</span>"
                "<span class=\"trade-row__mid\">%s 股 @ %s</span>"
                "<span class=\"trade-row__date\">%s</span></div>"
                % (tag_cls, esc(entry["action"]), esc(entry["shares"]), esc(entry["price"]),
                   esc(entry["date"])))
        parts.append("</div></details>")
    parts.append("</div></section>")
    return "".join(parts)


def _reason_pin_html(buy_reason):
    if not buy_reason:
        return (
            "<div class=\"reason-pin\"><div class=\"reason-pin__body\">"
            "<div class=\"reason-pin__label-row\">"
            "<span class=\"reason-pin__label\">買進理由</span></div>"
            "<div class=\"reason-pin__text\">尚未記錄買進理由，"
            "可在下方留言區選擇「買進理由」新增。</div></div></div>")
    return (
        "<div class=\"reason-pin\"><div class=\"reason-pin__body\">"
        "<div class=\"reason-pin__label-row\">"
        "<span class=\"reason-pin__label\">買進理由</span>"
        "<span class=\"reason-pin__date\">%s</span></div>"
        "<div class=\"reason-pin__text\">%s</div></div></div>"
        % (esc(buy_reason["date"]), esc(buy_reason["body"])))


def _notes_card_html(href_code, other_notes, buy_reasons_count):
    parts = []
    parts.append("<section class=\"card\"><div class=\"card__head\">"
                 "<h2>心得與留言</h2>"
                 "<span class=\"card__meta\">%d 則%s</span></div><div class=\"card__body\">"
                 % (len(other_notes),
                    "（另有 %d 則買進理由已置頂）" % buy_reasons_count
                    if buy_reasons_count else ""))
    parts.append(
        "<div class=\"section\">"
        "<form method=\"post\" action=\"/dashboard/stock/%s/note\">"
        "<textarea name=\"body\" rows=\"3\" placeholder=\"記下你對這檔股票的想法……\" "
        "required style=\"width:100%%;box-sizing:border-box;\"></textarea>"
        "<div style=\"display:flex;align-items:center;justify-content:space-between;"
        "gap:.6rem;flex-wrap:wrap;margin-top:.5rem;\">"
        "<select name=\"source_tag\">" % href_code)
    for tag in _NOTE_TAGS:
        parts.append("<option value=\"%s\">%s</option>" % (esc(tag), esc(tag)))
    parts.append(
        "</select><button type=\"submit\">存入</button></div></form>"
        "<p class=\"meta\">也可以直接在 Claude App 對話裡跟我討論，"
        "我會幫你存到這裡（同一份資料）。</p></div>")

    if other_notes:
        for c in other_notes:
            parts.append(
                "<div class=\"note\"><div class=\"note__meta\"><span>%s</span>"
                "<span>%s</span></div><div class=\"note__text\">%s</div></div>"
                % (esc(c["date"]), esc(c["source_tag"]), esc(c["body"])))
    else:
        parts.append("<p class=\"empty\">尚無其他留言。</p>")
    parts.append("</div></section>")
    return "".join(parts)


def render_stock_detail_page(store, code, flash=None, refreshing=False):
    """個股詳情頁（GET /dashboard/stock/<code>，2026-08-01新增）：庫存股
    與純研究標的共用同一個頁面。所有資料都讀快取（stock_prices／
    stock_valuation_snapshots／module_d_results），不即時查外部API——
    refreshing=True（report_server.is_refreshing()目前有背景執行緒在跑
    這個代碼）時頁面提示「更新中」，資料仍是刷新前的快取值，要看到新
    結果得重新整理（見派工說明「不即時查詢」原則）。
    """
    stance = store.get_latest_stance(code)
    valuation = store.get_stock_valuation(code)
    price_info = store.get_stock_prices().get(code)
    latest_batch = _latest_module_d_batch(store, code)

    holdings_latest = store.get_holdings()["holdings"]
    holding_row = next((h for h in holdings_latest if h["code"] == code), None)
    name = holding_row.get("name") if holding_row else None
    if not name and stance:
        name = stance.get("name")

    price = price_info["price"] if price_info else None
    prev_close = price_info.get("prev_close") if price_info else None
    delta_pct = None
    if price is not None and prev_close:
        delta_pct = (price - prev_close) / prev_close * 100
    delta_cls, delta_text = _delta_badge(delta_pct)

    if refreshing:
        updated_text = "更新中…請稍後重新整理查看最新結果"
    else:
        candidates = []
        if valuation and valuation.get("checked_at"):
            candidates.append(valuation["checked_at"])
        if latest_batch:
            candidates.append(latest_batch[0]["checked_at"])
        updated_text = ("上次更新於 %s" % max(candidates)) if candidates else \
            "尚未產生分析，正在背景處理中／請按下方「更新」"

    href_code = esc(urllib.parse.quote(code, safe=""))
    title_text = html.escape(("%s %s" % (code, name)) if name else code)

    parts = [_screen_page_head(title_text)]
    parts.append("<p class=\"meta\"><a href=\"/dashboard/stocks\">← 回持股清單</a></p>")
    if flash:
        is_error = flash.startswith("⚠️")
        color = "var(--red)" if is_error else "var(--green)"
        parts.append("<p class=\"meta\" style=\"color:%s;font-weight:600;\">%s</p>"
                     % (color, esc(flash)))

    parts.append(
        "<div style=\"display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap;\">"
        "<span style=\"font-size:.85rem;color:var(--ink-dim);\">%s</span>"
        "<h1 style=\"margin:0;\">%s</h1></div>"
        % (esc(code), esc(name) if name else "（尚無名稱）"))
    parts.append(
        "<div style=\"display:flex;align-items:baseline;gap:.6rem;margin:.3rem 0 .5rem;\">"
        "<span style=\"font-size:1.3rem;font-weight:700;\">%s</span>"
        "<span class=\"stock-row__delta %s\" style=\"font-size:.95rem;\">%s</span></div>"
        % (_fmt_price(price), delta_cls, esc(delta_text)))
    parts.append(
        "<div style=\"display:flex;align-items:center;justify-content:space-between;"
        "gap:.75rem;font-size:.82rem;color:var(--ink-dim);margin-bottom:.8rem;flex-wrap:wrap;\">"
        "<span>%s</span>"
        "<form method=\"post\" action=\"/dashboard/stock/%s/refresh\" style=\"margin:0;\">"
        "<button type=\"submit\" class=\"btn-muted\" style=\"margin:0;\"%s>%s</button></form></div>"
        % (esc(updated_text), href_code,
           " disabled" if refreshing else "", "更新中…" if refreshing else "更新"))

    comments = store.get_comments_by_code(code, limit=50)["results"]
    buy_reasons = [c for c in comments if c["source_tag"] == "買進理由"]
    other_notes = [c for c in comments if c["source_tag"] != "買進理由"]
    parts.append(_reason_pin_html(buy_reasons[0] if buy_reasons else None))

    parts.append("<section class=\"card\"><div class=\"card__head\"><h2>估值</h2>")
    if valuation:
        parts.append("<span class=\"card__meta\">%s</span></div><div class=\"card__body\">"
                     % esc(valuation.get("checked_at")))
        per_text = ("%.1f" % valuation["per"]) if valuation.get("per") is not None else "—"
        pbr_text = ("%.2f" % valuation["pbr"]) if valuation.get("pbr") is not None else "—"
        yield_text = ("%.2f%%" % valuation["dividend_yield"]) \
            if valuation.get("dividend_yield") is not None else "—"
        yoy_text = ("%.1f%%" % (valuation["revenue_yoy"] * 100)) \
            if valuation.get("revenue_yoy") is not None else "—"
        parts.append(
            "<div class=\"val-grid\">"
            "<div class=\"val-item\"><div class=\"label\">本益比</div><div class=\"value\">%s</div></div>"
            "<div class=\"val-item\"><div class=\"label\">股價淨值比</div><div class=\"value\">%s</div></div>"
            "<div class=\"val-item\"><div class=\"label\">殖利率</div><div class=\"value\">%s</div></div>"
            "<div class=\"val-item\"><div class=\"label\">營收年增率</div><div class=\"value\">%s</div></div>"
            "</div>" % (per_text, pbr_text, yield_text, yoy_text))
        parts.append("<div class=\"val-source\">%s</div>"
                     % esc(_valuation_source_text(valuation.get("valuation_data_source"))))
        if valuation.get("valuation_error"):
            parts.append("<p class=\"meta\" style=\"color:var(--red);\">估值查詢提醒：%s</p>"
                         % esc(valuation["valuation_error"]))
        if valuation.get("revenue_error"):
            parts.append("<p class=\"meta\" style=\"color:var(--red);\">營收查詢提醒：%s</p>"
                         % esc(valuation["revenue_error"]))
    else:
        parts.append("</div><div class=\"card__body\">"
                     "<p class=\"empty\">尚無估值資料，背景刷新完成後會顯示在這裡。</p>")
    parts.append("</div></section>")

    parts.append(_module_d_card_html(latest_batch))

    holdings_card = _holdings_card_html(store, code)
    if holdings_card:
        parts.append(holdings_card)

    parts.append(_notes_card_html(href_code, other_notes, len(buy_reasons)))

    parts.append("</body></html>")
    return "".join(parts)


def _carry_over_avg_cost(rows, previous_holdings):
    """holdings_parser.parse_holdings_report() 的解析結果不含 avg_cost
    （帳單本來就沒有成本資料）；若上次快照同一代碼有非NULL的avg_cost，
    沿用帶過去，不讓已知的成本資料在「貼帳單→存新快照」的流程中消失。
    回傳新的清單（不修改傳入的rows），每筆含code/name/shares/avg_cost/
    is_emerging，供預覽頁顯示與確認表單的隱藏欄位JSON共用。"""
    prev_map = {h["code"]: h for h in (previous_holdings.get("holdings") or [])}
    enriched = []
    for r in rows:
        prev = prev_map.get(r["code"])
        avg_cost = prev.get("avg_cost") if prev else None
        enriched.append({
            "code": r["code"],
            "name": r.get("name"),
            "shares": r.get("shares"),
            "avg_cost": avg_cost,
            "is_emerging": bool(r.get("is_emerging")),
        })
    return enriched


def _diff_holdings(enriched_rows, previous_holdings):
    """比對這次解析結果與上次持股快照，分成新增／消失／股數變化三類，
    供 render_holdings_preview() 顯示。「消失」只代表這次帳單沒有印到
    這個代碼，不代表使用者已經出清——不在這裡替使用者下判斷。"""
    prev_map = {h["code"]: h for h in (previous_holdings.get("holdings") or [])}
    curr_map = {r["code"]: r for r in enriched_rows}
    added = [r for r in enriched_rows if r["code"] not in prev_map]
    removed = [h for h in (previous_holdings.get("holdings") or [])
               if h["code"] not in curr_map]
    changed = []
    for r in enriched_rows:
        prev = prev_map.get(r["code"])
        if prev is not None and prev.get("shares") != r.get("shares"):
            changed.append({
                "code": r["code"], "name": r.get("name"),
                "prev_shares": prev.get("shares"), "new_shares": r.get("shares"),
            })
    return {"added": added, "removed": removed, "changed": changed}


def render_holdings_preview(parsed, previous_holdings):
    """FR-058週邊工具「貼庫存帳單」第一步：預覽頁。

    parsed 是 holdings_parser.parse_holdings_report() 的原始回傳值
    （{"rows", "unparsed_lines", "total_parsed"}）；previous_holdings 是
    store.get_holdings() 的回傳值（比對用的「上次快照」，可能是空庫存）。

    人工確認關卡（holdings_parser docstring明講不可省略）：這裡只渲染
    預覽，不寫入資料庫——「確認存入」表單把完整解析結果（含沿用的
    avg_cost）序列化進隱藏欄位，POST 到 /dashboard/holdings/confirm 才
    真的呼叫 save_holdings（見 report_server.py）。
    """
    rows = parsed.get("rows") or []
    unparsed_lines = parsed.get("unparsed_lines") or []
    enriched_rows = _carry_over_avg_cost(rows, previous_holdings)
    diff = _diff_holdings(enriched_rows, previous_holdings)

    parts = [_screen_page_head("貼庫存帳單－確認")]
    parts.append("<p class=\"meta\"><a href=\"/\">← 回知識庫檢視</a></p>")
    parts.append("<h1>貼庫存帳單－確認解析結果</h1>")
    parts.append(
        "<p class=\"meta\">本次解析出 %d 檔 ｜ 上次快照：%s（%s 檔）｜ "
        "請確認無誤後再存入，存入不會覆蓋歷史紀錄，而是新增一筆最新快照</p>"
        % (len(enriched_rows),
           esc(previous_holdings.get("snapshot_date")),
           previous_holdings.get("count", 0)))

    if unparsed_lines:
        parts.append(
            "<div class=\"comment\" style=\"border-left-color:var(--red)\">"
            "<div class=\"head\" style=\"color:var(--red)\">"
            "⚠️ %d 行無法解析，請人工核對原始帳單是否有遺漏</div>"
            % len(unparsed_lines))
        for line in unparsed_lines:
            parts.append("<div><code>%s</code></div>" % esc(line))
        parts.append("</div>")

    parts.append("<h2>與上次快照比對</h2>")
    if diff["added"]:
        parts.append("<h3>新增（這次有、上次沒有）</h3>"
                     "<ul>")
        for r in diff["added"]:
            parts.append("<li>%s %s：%s 股</li>"
                         % (esc(r["code"]), esc(r["name"]), esc(r["shares"])))
        parts.append("</ul>")
    if diff["removed"]:
        parts.append(
            "<h3>這次帳單沒有這一檔（上次有，這次沒印到——不確定是否已"
            "出清，請自行核對）</h3><ul>")
        for h in diff["removed"]:
            parts.append("<li>%s %s：上次 %s 股</li>"
                         % (esc(h["code"]), esc(h["name"]), esc(h["shares"])))
        parts.append("</ul>")
    if diff["changed"]:
        parts.append("<h3>股數變化</h3><ul>")
        for c in diff["changed"]:
            parts.append("<li>%s %s：%s 股 → %s 股</li>"
                         % (esc(c["code"]), esc(c["name"]),
                            esc(c["prev_shares"]), esc(c["new_shares"])))
        parts.append("</ul>")
    if not (diff["added"] or diff["removed"] or diff["changed"]):
        parts.append("<p class=\"meta\">與上次快照相比沒有變化。</p>")

    parts.append("<h2>本次解析完整清單</h2>")
    if enriched_rows:
        parts.append(
            "<div class=\"tablewrap\"><table><thead><tr><th>代碼</th>"
            "<th>名稱</th><th>股數</th><th>平均成本</th><th>興櫃</th>"
            "</tr></thead><tbody>")
        for r in enriched_rows:
            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"股數\">%s</td><td data-label=\"平均成本\">%s</td>"
                "<td data-label=\"興櫃\">%s</td></tr>"
                % (esc(r["code"]), esc(r["name"]), esc(r["shares"]),
                   esc(r["avg_cost"]), "是" if r["is_emerging"] else "—"))
        parts.append("</tbody></table></div>")
        rows_json = json.dumps(enriched_rows, ensure_ascii=False)
        parts.append(
            "<form method=\"post\" action=\"/dashboard/holdings/confirm\">"
            "<input type=\"hidden\" name=\"rows_json\" value=\"%s\">"
            "<button type=\"submit\" class=\"btn-primary-action\">"
            "確認存入</button></form>" % esc(rows_json))
    else:
        parts.append("<p class=\"empty\">沒有解析出任何資料列，無法存入。"
                     "請確認帳單格式，或往回上一頁重貼。</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _screen_page_head(title):
    return ("<!doctype html><html lang=\"zh-Hant\"><head>"
            "<meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            + PWA_META +
            "<title>%s - AlphaVibe</title>"
            "<style>%s</style></head><body>" % (title, CSS))


def render_screen_form(error=None):
    """GET /screen：手機貼股票代碼的第一層篩選輸入表單。"""
    parts = [_screen_page_head("選股篩選")]
    parts.append("<p class=\"meta\"><a href=\"/\">← 回知識庫檢視</a></p>")
    parts.append("<h1>第一層選股篩選</h1>")
    parts.append("<p class=\"meta\">理由：股價從高點大幅回檔（&gt;=40%）常代表市場"
                 "情緒過度悲觀，但只有在「營收仍在正成長」時，這種下跌才比較可能是"
                 "錯殺、而不是基本面真的變差。PEG（本益成長比）&lt;1 則是拿本益比"
                 "對比成長率，找出相對估值便宜、有安全邊際的標的，比單看本益比更準。"
                 "兩個條件疊在一起，篩的是「跌深但基本面沒有真的變差」的成長股，"
                 "不是隨便一檔破底股。</p>")
    parts.append("<p class=\"meta\">篩選條件：PEG（本益成長比）&lt;1 且股價從近 120 天"
                 "高點回檔 &gt;=40%%。這只是框架裡可量化的兩個條件，供應鏈敘事"
                 "（賣鏟子邏輯／具體新客戶新市場事件）是否成立仍需人工確認，篩出來"
                 "的候選不代表可以直接買。貼入候選股票代碼，逗號或換行分隔，"
                 "一次最多 %d 檔。</p>"
                 % screener.MAX_CODES)
    if error:
        parts.append("<p class=\"empty\" style=\"color:var(--red)\">%s</p>" % esc(error))
    parts.append(
        "<form method=\"post\" action=\"/screen\">"
        "<textarea name=\"codes\" rows=\"6\" "
        "style=\"width:100%;font-size:1rem;padding:.5rem;box-sizing:border-box;\" "
        "placeholder=\"3485,6953,6719\"></textarea>"
        "<p><button type=\"submit\" style=\"font-size:1rem;padding:.6rem 1.2rem;\">"
        "開始篩選</button></p></form>")
    parts.append("</body></html>")
    return "".join(parts)


def _fmt_num(value):
    """把小數格式化成不帶多餘小數點的字串（1.0→"1"、0.4→"0.4"），供動態組出
    的門檻說明文字使用，避免「PEG&lt;1.0」這種比手寫版本囉唆的顯示。"""
    return "%g" % value


def _fmt_pct(value):
    """value 為小數（0.4＝40%），回傳去尾數的百分比字串，如 "40"、"9.5"。"""
    return _fmt_num(value * 100)


def _format_condition_text(peg_threshold=None, drawdown_min=None, drawdown_max=None,
                           excess_drawdown_min=None, revenue_yoy_min=None):
    """把框架/篩選門檻組成人看得懂的一句話，取代寫死的「PEG<1 且回檔>=40%」。

    任一參數為 None 代表「這個框架不看這項條件」，直接省略該子句——這樣
    framework revenue_high_price_dip（peg_threshold=None）才不會被印成
    「PEG<None」這種假字串。全部為 None 時回傳「不限條件」，理論上不會發生
    （框架至少會有一項條件），但防呆不可省。

    revenue_yoy_min（2026-07-29 新增，FR-058策略設定畫面用）：既有呼叫端
    （_thresholds_condition_text／compose_market_scan_track_reason）都沒有
    這項資料可傳，省略時維持 None、不新增子句，行為與改動前完全一致。
    """
    clauses = []
    if peg_threshold is not None:
        clauses.append("PEG&lt;%s" % _fmt_num(peg_threshold))
    if revenue_yoy_min is not None:
        clauses.append("營收年增率&gt;=%s%%" % _fmt_pct(revenue_yoy_min))
    if drawdown_min is not None and drawdown_max is not None:
        clauses.append("回檔%s%%~%s%%" % (_fmt_pct(drawdown_min), _fmt_pct(drawdown_max)))
    elif drawdown_min is not None:
        clauses.append("回檔&gt;=%s%%" % _fmt_pct(drawdown_min))
    elif drawdown_max is not None:
        clauses.append("回檔&lt;=%s%%" % _fmt_pct(drawdown_max))
    if excess_drawdown_min is not None:
        clauses.append("超額跌幅&gt;=%s%%" % _fmt_pct(excess_drawdown_min))
    if not clauses:
        return "不限條件"
    return " 且".join(clauses)


def _thresholds_condition_text(result):
    """從 screener.screen_stocks() 回傳值裡的 "thresholds" 區塊組門檻說明文字。

    "thresholds" 整個 key 缺席時（例如舊呼叫端、或單元測試直接手寫最小
    result dict）退回 screener 模組原本寫死的預設值（PEG&lt;1 且回檔&gt;=40%），
    行為與改動前完全一致；"thresholds" 存在但個別欄位是 None，則忠實反映
    「這個框架不看這項條件」，不套用預設值。
    """
    thresholds = result.get("thresholds")
    if thresholds is None:
        return _format_condition_text(peg_threshold=screener.PEG_THRESHOLD,
                                      drawdown_min=screener.DRAWDOWN_THRESHOLD)
    return _format_condition_text(
        peg_threshold=thresholds.get("peg_threshold"),
        drawdown_min=thresholds.get("drawdown_min"),
        drawdown_max=thresholds.get("drawdown_max"),
        excess_drawdown_min=thresholds.get("excess_drawdown_min"))


def render_screen_results(result):
    """POST /screen 結果頁；result 為 screener.screen_stocks() 的回傳值。"""
    parts = [_screen_page_head("選股篩選結果")]
    parts.append("<p class=\"meta\"><a href=\"/screen\">← 重新篩選</a> ｜ "
                 "<a href=\"/\">回知識庫檢視</a></p>")
    parts.append("<h1>選股篩選結果</h1>")

    if result.get("error"):
        parts.append("<p class=\"empty\" style=\"color:var(--red)\">%s</p>" % esc(result["error"]))
        parts.append("</body></html>")
        return "".join(parts)

    rows = result.get("results") or []
    hit_count = sum(1 for r in rows if r.get("meets_framework"))
    parts.append("<p class=\"meta\">共篩選 %d 檔，符合框架（%s）"
                 "%d 檔（表格中以黃底標出）</p>"
                 % (result.get("total", len(rows)), _thresholds_condition_text(result), hit_count))

    if rows:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>PER</th><th>營收年增率</th>"
                     "<th>PEG</th><th>回檔幅度</th><th>超額跌幅</th><th>目前價</th>"
                     "<th>符合框架</th><th>備註</th></tr></thead><tbody>")
        for r in rows:
            peg_text = ("%.2f" % r["peg"]) if r["peg"] is not None else "—"
            yoy_text = ("%.1f%%" % (r["revenue_yoy"] * 100)) if r["revenue_yoy"] is not None else "—"
            drawdown_text = ("%.1f%%" % (r["drawdown_pct"] * 100)) if r["drawdown_pct"] is not None else "—"
            excess_drawdown_text = ("%.1f%%" % (r.get("excess_drawdown_pct") * 100)
                                    if r.get("excess_drawdown_pct") is not None else "—")
            per_text = ("%.2f" % r["per"]) if r["per"] is not None else "—"
            hit = r.get("meets_framework")
            row_style = " class=\"row-highlight\"" if hit else ""
            hit_text = "符合" if hit else "—"
            note = esc(r.get("error")) if r.get("error") else "—"
            parts.append(
                "<tr%s><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"PER\">%s</td><td data-label=\"營收年增率\">%s</td>"
                "<td data-label=\"PEG\">%s</td><td data-label=\"回檔幅度\">%s</td>"
                "<td data-label=\"超額跌幅\">%s</td>"
                "<td data-label=\"目前價\">%s</td>"
                "<td data-label=\"符合框架\" class=\"stance\">%s</td>"
                "<td data-label=\"備註\">%s</td></tr>"
                % (row_style, esc(r["code"]), esc(r["name"]), per_text, yoy_text,
                   peg_text, drawdown_text, excess_drawdown_text, esc(r["current_price"]),
                   hit_text, note))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">沒有輸入任何代碼。</p>")
    parts.append("</body></html>")
    return "".join(parts)


def render_market_scan_page(selected_id, latest, error=None):
    """`/market-scan`：第二層全市場批次篩選頁。selected_id 是目前選的框架
    代號；latest 是 KBStore.get_latest_market_scan() 的回傳值。

    資訊架構原則（2026-07-22 使用者回饋「目前的畫面沒有UI的考量，就算有
    價值高的資訊，也是浪費」後改版）：符合框架的候選是使用者真正要看的
    東西，不能被淹沒在上百檔不符合的候選裡——結果拆成「符合框架」（預設
    展開，放最上面）與「全部候選」（預設收合，給想深入看原始資料的情境）
    兩個獨立區塊，說明文字也挪到按鈕下方的收合區塊，不擋在最前面。
    """
    parts = [_screen_page_head("全市場批次篩選")]
    parts.append("<p class=\"meta\"><a href=\"/\">← 回知識庫檢視</a></p>")
    parts.append("<h1>第二層全市場批次篩選</h1>")

    parts.append("<form method=\"get\" action=\"/market-scan\" style=\"margin:.6rem 0;\">"
                 "<select name=\"framework\">")
    for fw in frameworks.FRAMEWORKS:
        selected_attr = " selected" if fw["id"] == selected_id else ""
        parts.append("<option value=\"%s\"%s>%s</option>"
                     % (esc(fw["id"]), selected_attr, esc(fw["label"])))
    parts.append("</select> "
                 "<button type=\"submit\" style=\"padding:.4rem .8rem;\">切換框架</button>"
                 "</form>")

    parts.append("<form method=\"post\" action=\"/market-scan\">"
                 "<input type=\"hidden\" name=\"framework\" value=\"%s\">"
                 "<button type=\"submit\" style=\"font-size:1rem;\" "
                 "class=\"btn-primary-action\">"
                 "立即掃描（約需30秒~數分鐘）</button></form>" % esc(selected_id))

    parts.append("<details class=\"philomod\"><summary>這是什麼？</summary><pre>"
                 "用 TWSE/TPEx 官方批次資料，在框架鎖定的產業別內自動找候選"
                 "（不用手動貼代碼），範圍只有上市＋上櫃（興櫃沒有官方批次PER"
                 "資料，不在這次掃描範圍）。每天 02:00 也會自動掃描一次，"
                 "這裡永遠顯示最近一次結果。</pre></details>")

    # 框架若有量化規則做不到的條件（例如 revenue_high_price_dip 的 EPS 上修
    # ／外資動向／AI營收占比，全部需要人工查證），顯示提醒——不能讓使用者
    # 誤以為「符合框架」代表框架全部條件都已驗證過。
    selected_framework = frameworks.get_framework(selected_id) or {}
    manual_conditions = selected_framework.get("manual_conditions")
    revenue_note = selected_framework.get("revenue_condition_note")
    if manual_conditions or revenue_note:
        parts.append("<details class=\"philomod\">"
                     "<summary>這個框架有哪些條件是工具查不到、需要人工判斷？</summary><pre>")
        if revenue_note:
            parts.append("%s\n" % esc(revenue_note))
        for cond in (manual_conditions or []):
            parts.append("• %s\n" % esc(cond))
        parts.append("</pre></details>")

    if error:
        parts.append("<p class=\"empty\" style=\"color:var(--red)\">%s</p>" % esc(error))

    if not latest.get("found"):
        parts.append("<p class=\"empty\">尚無掃描紀錄，可按上方「立即掃描」，"
                     "或等待每天 02:00 排程自動跑一次。</p>")
        parts.append("</body></html>")
        return "".join(parts)

    run = latest["run"]
    rows = latest["results"]
    hit_rows = [r for r in rows if r.get("meets_framework")]
    hit_count = run.get("meets_count", len(hit_rows))
    trigger_text = {"manual": "手動觸發", "scheduled": "排程自動"}.get(
        run.get("trigger_source"), esc(run.get("trigger_source")))
    total_scanned = run.get("total_scanned")
    scanned_text = ("本次掃描全市場（上市+上櫃）共 %d 檔，其中" % total_scanned
                    if total_scanned is not None else "")
    benchmark_dd = run.get("benchmark_drawdown_pct")
    benchmark_text = ("｜同期大盤回檔 %s%%" % _fmt_pct(benchmark_dd)
                      if benchmark_dd is not None else "")
    parts.append("<p class=\"meta\">最近一次掃描：%s（%s）｜%s候選 %d 檔，符合框架 %d 檔%s</p>"
                 % (esc(run.get("run_at")), trigger_text, scanned_text,
                    run.get("candidate_count", len(rows)), hit_count, benchmark_text))

    twse_err = run.get("twse_error")
    tpex_err = run.get("tpex_error")
    if twse_err or tpex_err:
        parts.append("<p class=\"empty\" style=\"color:var(--red)\">")
        if twse_err:
            parts.append("TWSE 資料源異常：%s　" % esc(twse_err))
        if tpex_err:
            parts.append("TPEx 資料源異常：%s" % esc(tpex_err))
        parts.append("（該市場當次候選數會變少，不影響另一邊）</p>")

    benchmark_err = run.get("benchmark_error")
    if benchmark_err:
        parts.append("<p class=\"empty\" style=\"color:var(--red)\">大盤基準資料異常：%s"
                     "（本次「同期大盤回檔」與「超額跌幅」無法計算，不影響其他欄位）</p>"
                     % esc(benchmark_err))

    run_id = run.get("id")

    parts.append("<details class=\"section\" open><summary><h2>符合框架的候選（%d 檔）</h2>"
                 "</summary>" % hit_count)
    if hit_rows:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>"
                     "<th>PER</th><th>營收年增率</th><th>PEG</th><th>回檔幅度</th>"
                     "<th>超額跌幅</th><th>PBR</th><th>殖利率</th>"
                     "<th>目前價</th><th>加入追蹤</th></tr></thead><tbody>")
        for r in hit_rows:
            parts.append(_market_scan_row_html(r, highlight=False, run_id=run_id))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">這次沒有候選同時符合 PEG 與回檔門檻，"
                     "可以到下方「全部候選」查看完整清單。</p>")
    parts.append("</details>")

    parts.append("<details class=\"section\"><summary><h2>全部候選（%d 檔，含未達門檻）</h2>"
                 "</summary>" % len(rows))
    if rows:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>"
                     "<th>PER</th><th>營收年增率</th><th>PEG</th><th>回檔幅度</th>"
                     "<th>超額跌幅</th><th>PBR</th><th>殖利率</th>"
                     "<th>目前價</th><th>加入追蹤</th><th>符合框架</th><th>備註</th></tr></thead><tbody>")
        for r in rows:
            parts.append(_market_scan_row_html(r, highlight=True, run_id=run_id))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">這次掃描沒有候選（可能兩個資料源都異常，"
                     "或框架門檻下確實沒有符合的股票）。</p>")
    parts.append("</details>")

    parts.append("</body></html>")
    return "".join(parts)


# 沿用 /screen 頁面「理由」段落同一套因果說明文字（見 render_screen_form），
# 加入追蹤時的 reason 要能回答「為什麼這檔當初被篩出來」，不是只有數字。
_TRACK_FRAMEWORK_RATIONALE = (
    "股價大幅回檔常代表市場情緒過度悲觀，但只有在營收仍在正成長時，這種"
    "下跌才比較可能是錯殺、而不是基本面真的變差；PEG（本益成長比）<1"
    "代表用相對便宜的價格買到相對高成長的公司，是安全邊際的量化代理。"
)
_TRACK_DISCLAIMER = (
    "供應鏈敘事（賣鏟子邏輯／具體新客戶新市場事件）是否具體仍需人工確認，"
    "這只是篩選候選，不代表可以直接買。"
)


def compose_market_scan_track_reason(row, framework, run_at):
    """組出「加入追蹤」時存進 stances.reason 的說明文字：這檔的具體數字＋
    框架因果理由＋是否真的通過完整框架（而不是只通過Stage A初篩）。

    純函式，不查資料庫、不連外部 API——row/framework/run_at 都由呼叫端
    （POST /market-scan/track）先查好再傳進來。缺值（peg/drawdown為None）
    時明講「資料不完整」，不可以顯示 None 或亂算。
    """
    if row.get("per") is not None and row.get("revenue_yoy") is not None:
        peg_text = ("PEG %s（PER %.2f ÷ 營收年增率 %.1f%%）"
                    % (("%.2f" % row["peg"]) if row.get("peg") is not None else "算不出來",
                       row["per"], row["revenue_yoy"] * 100))
    else:
        peg_text = "PEG／PER／營收年增率資料不完整"

    if row.get("drawdown_pct") is not None:
        drawdown_text = ("股價自 %s 高點 %s 回檔 %.1f%% 至 %s（%s）"
                         % (row.get("high_date") or "—", row.get("high_price"),
                            row["drawdown_pct"] * 100, row.get("current_price"),
                            row.get("current_date") or "—"))
    else:
        drawdown_text = "回檔幅度資料不完整（%s）" % (row.get("error") or "查詢失敗原因不明")

    # 動態組門檻文字，不能寫死「PEG<%s 且回檔>=%s%%」——framework 2
    # （revenue_high_price_dip）的 peg_max 是 None，寫死版本會印出「PEG<None」
    # 這種假字串。_format_condition_text 對 None 欄位會直接省略該子句。
    condition_text = _format_condition_text(
        peg_threshold=framework.get("peg_max"),
        drawdown_min=framework.get("drawdown_min"),
        drawdown_max=framework.get("drawdown_max"),
        excess_drawdown_min=framework.get("excess_drawdown_min"))
    if row.get("meets_framework"):
        framework_note = ("符合框架完整門檻（%s）。%s"
                          % (condition_text, _TRACK_FRAMEWORK_RATIONALE))
    else:
        framework_note = ("只通過第一階段初篩（產業別＋PEG門檻＋營收正成長），"
                          "未達框架完整門檻（%s），僅供觀察，不是完整符合框架的候選。"
                          % condition_text)

    return ("%s第二層批次篩選候選（%s 掃描）。%s；%s。%s %s"
            % (framework.get("label", framework.get("id", "")), run_at,
               peg_text, drawdown_text, framework_note, _TRACK_DISCLAIMER))


def _market_scan_track_form_html(run_id, code):
    """每列的「加入追蹤」小表單：只帶 run_id/code/選的stance，reason 由
    伺服器端 `POST /market-scan/track` 重新查資料庫現算，不信任表單內容。
    2026-07-22 使用者要求：全部候選（不限符合框架的）都要有這個選項。"""
    return (
        "<form method=\"post\" action=\"/market-scan/track\" "
        "style=\"display:flex;gap:.3rem;align-items:center;flex-wrap:wrap;\">"
        "<input type=\"hidden\" name=\"run_id\" value=\"%d\">"
        "<input type=\"hidden\" name=\"code\" value=\"%s\">"
        "<select name=\"stance\">"
        "<option value=\"觀察\" selected>觀察</option>"
        "<option value=\"偏多\">偏多</option>"
        "<option value=\"偏空\">偏空</option>"
        "</select>"
        "<button type=\"submit\" style=\"font-size:.85rem;padding:.3rem .6rem;\">"
        "加入追蹤</button></form>"
        % (run_id, esc(code)))


def render_track_conflict_page(code, name, new_stance, new_reason, existing, run_id):
    """save_stance() 回傳 conflict=True 時顯示：既有立場 vs 準備存入的新
    立場，需要二次確認才能覆蓋（沿用 FR-013/018 既有的立場衝突精神，
    適配成網頁一次性表單流程；不是每次都要問——只有立場真的不同才問）。
    """
    parts = [_screen_page_head("加入追蹤－確認立場衝突")]
    parts.append("<p class=\"meta\"><a href=\"/market-scan\">← 返回</a></p>")
    parts.append("<h1>%s %s 已有立場，要更新嗎？</h1>" % (esc(code), esc(name)))
    parts.append("<p class=\"empty\" style=\"color:var(--red)\">新立場「%s」與既有立場「%s」"
                 "（%s）不同，請確認要不要覆蓋（既有立場不會消失，仍保留在歷史紀錄裡）。</p>"
                 % (esc(new_stance), esc(existing.get("stance")), esc(existing.get("date"))))
    parts.append("<h2>既有立場</h2>")
    parts.append("<div class=\"comment\"><div class=\"head\">%s ｜ %s</div><div>%s</div></div>"
                 % (esc(existing.get("date")), esc(existing.get("stance")),
                    esc(existing.get("reason"))))
    parts.append("<h2>準備存入的新立場</h2>")
    parts.append("<div class=\"comment\"><div class=\"head\">%s</div><div>%s</div></div>"
                 % (esc(new_stance), esc(new_reason)))
    parts.append(
        "<form method=\"post\" action=\"/market-scan/track\">"
        "<input type=\"hidden\" name=\"run_id\" value=\"%d\">"
        "<input type=\"hidden\" name=\"code\" value=\"%s\">"
        "<input type=\"hidden\" name=\"stance\" value=\"%s\">"
        "<input type=\"hidden\" name=\"overwrite\" value=\"1\">"
        "<button type=\"submit\" class=\"btn-danger\">確認覆蓋為新立場</button></form>"
        % (run_id, esc(code), esc(new_stance)))
    parts.append("<p class=\"meta\"><a href=\"/market-scan\">取消，返回</a></p>")
    parts.append("</body></html>")
    return "".join(parts)


def render_track_result_page(saved, code, name, stance):
    """加入追蹤成功後的簡短確認頁（不論是直接存入或覆蓋衝突後存入）。"""
    parts = [_screen_page_head("加入追蹤－完成")]
    parts.append("<p class=\"meta\"><a href=\"/market-scan\">← 返回</a></p>")
    parts.append("<h1>已加入追蹤</h1>")
    parts.append("<p class=\"meta\">%s %s ｜ 立場：%s ｜ %s</p>"
                 % (esc(code), esc(name), esc(stance),
                    "已更新覆蓋既有立場" if saved.get("conflict") else "已存入"))
    record = saved.get("record") or {}
    parts.append("<div class=\"comment\"><div class=\"head\">%s</div><div>%s</div></div>"
                 % (esc(record.get("date")), esc(record.get("reason"))))
    parts.append("<p class=\"meta\"><a href=\"/market-scan\">回全市場批次篩選</a> ｜ "
                 "<a href=\"/\">回知識庫檢視</a></p>")
    parts.append("</body></html>")
    return "".join(parts)


def render_track_error_page(message):
    """run_id/code 查無對應候選資料（例如掃描紀錄已被新的一批覆蓋）時顯示。"""
    parts = [_screen_page_head("加入追蹤－發生問題")]
    parts.append("<p class=\"meta\"><a href=\"/market-scan\">← 返回</a></p>")
    parts.append("<h1>無法加入追蹤</h1>")
    parts.append("<p class=\"empty\" style=\"color:var(--red)\">%s</p>" % esc(message))
    parts.append("</body></html>")
    return "".join(parts)


def _market_scan_row_html(r, highlight, run_id):
    """/market-scan 結果表格的單一列。highlight=True 才畫黃底（符合框架
    候選區塊裡全部列都符合，畫了反而是雜訊，所以那裡傳 False）。
    highlight=True 時多渲染「符合框架」「備註」兩欄，維持與全部候選表格
    的欄位對齊；highlight=False（符合框架區塊）省略這兩欄，因為值恆為
    「符合」「—」，不提供資訊。每列都有「加入追蹤」表單（兩個區塊都有，
    不限符合框架的候選）。"""
    peg_text = ("%.2f" % r["peg"]) if r["peg"] is not None else "—"
    yoy_text = ("%.1f%%" % (r["revenue_yoy"] * 100)) if r["revenue_yoy"] is not None else "—"
    drawdown_text = ("%.1f%%" % (r["drawdown_pct"] * 100)) if r["drawdown_pct"] is not None else "—"
    per_text = ("%.2f" % r["per"]) if r["per"] is not None else "—"
    # excess_drawdown_pct／pbr／dividend_yield 是 2026-07-28 新增欄位，歷史列
    # （遷移前存的 run）沒有這幾欄，一律用 .get() 不可直接索引，否則舊資料
    # 會讓整頁 KeyError。
    excess_drawdown_text = ("%.1f%%" % (r.get("excess_drawdown_pct") * 100)
                            if r.get("excess_drawdown_pct") is not None else "—")
    pbr_text = ("%.2f" % r.get("pbr")) if r.get("pbr") is not None else "—"
    dividend_yield_text = ("%.2f%%" % r.get("dividend_yield")
                           if r.get("dividend_yield") is not None else "—")
    track_form = _market_scan_track_form_html(run_id, r["code"])
    base = (
        "<td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
        "<td data-label=\"市場\">%s</td><td data-label=\"產業別\">%s</td>"
        "<td data-label=\"PER\">%s</td><td data-label=\"營收年增率\">%s</td>"
        "<td data-label=\"PEG\">%s</td><td data-label=\"回檔幅度\">%s</td>"
        "<td data-label=\"超額跌幅\">%s</td><td data-label=\"PBR\">%s</td>"
        "<td data-label=\"殖利率\">%s</td>"
        "<td data-label=\"目前價\">%s</td><td data-label=\"加入追蹤\">%s</td>"
        % (esc(r["code"]), esc(r["name"]), esc(r.get("market")), esc(r.get("industry")),
           per_text, yoy_text, peg_text, drawdown_text, excess_drawdown_text,
           pbr_text, dividend_yield_text, esc(r.get("current_price")), track_form))
    if not highlight:
        return "<tr>%s</tr>" % base
    hit = r.get("meets_framework")
    row_style = " class=\"row-highlight\"" if hit else ""
    hit_text = "符合" if hit else "—"
    note = esc(r.get("error")) if r.get("error") else "—"
    return ("<tr%s>%s<td data-label=\"符合框架\" class=\"stance\">%s</td>"
            "<td data-label=\"備註\">%s</td></tr>"
            % (row_style, base, hit_text, note))


def default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


def main(argv=None):
    parser = argparse.ArgumentParser(description="產出知識庫靜態檢視頁")
    parser.add_argument("--data-dir", default=None, help="資料目錄（預設 poc/data）")
    parser.add_argument("--out", default=None, help="輸出 HTML 路徑（預設 <data-dir>/report.html）")
    args = parser.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir or default_data_dir())
    out_path = os.path.abspath(args.out or os.path.join(data_dir, "report.html"))

    store = KBStore(data_dir)
    try:
        page = render(store)
    finally:
        store.close()
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    icon_path = os.path.join(os.path.dirname(out_path), "apple-touch-icon.png")
    with open(icon_path, "wb") as fh:
        fh.write(make_icon_png())
    print("已產出：%s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
