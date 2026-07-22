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
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kb_store import KBStore  # noqa: E402
import frameworks  # noqa: E402
import screener  # noqa: E402

# 台股慣例：紅漲綠跌 → 偏多紅、偏空綠
STANCE_COLORS = {"偏多": "#c92a2a", "偏空": "#2b8a3e"}
DEFAULT_STANCE_COLOR = "#495057"

CSS = """
body { font-family: -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif;
       margin: 2rem auto; max-width: 960px; padding: 0 1rem; color: #212529; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem;
     border-bottom: 2px solid #dee2e6; padding-bottom: .3rem; }
.meta { color: #868e96; font-size: .85rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border: 1px solid #dee2e6; padding: .45rem .6rem; text-align: left;
         vertical-align: top; overflow-wrap: break-word; }
th { background: #f1f3f5; white-space: nowrap; }
.stance { font-weight: 700; white-space: nowrap; }
.empty { color: #868e96; padding: 1rem 0; }
.comment { border-left: 3px solid #adb5bd; margin: .8rem 0; padding: .2rem .8rem; }
.comment .head { font-size: .8rem; color: #868e96; margin-bottom: .2rem; }
.tag { background: #e7f5ff; color: #1971c2; border-radius: 3px;
       padding: 0 .4rem; font-size: .75rem; margin-right: .4rem; }
.tablewrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
details.philomod { border: 1px solid #dee2e6; border-radius: 8px;
                    margin: .6rem 0; padding: .5rem .8rem; }
details.philomod summary { cursor: pointer; font-weight: 600; }
details.philomod summary::marker { color: #1971c2; }
details.philomod pre { white-space: pre-wrap; overflow-wrap: break-word;
                        font-family: inherit; font-size: .88rem;
                        line-height: 1.55; margin: .7rem 0 .1rem; }
/* 表格「理由」欄位的展開全文（巢狀在 <td> 裡，class 特意跟上面兩個 details
   分開，避免樣式互相污染） */
details.reason { display: inline-block; max-width: 100%; }
details.reason summary { cursor: pointer; color: #1971c2; }
details.reason summary::marker { color: #1971c2; }
details.reason .reason-full { white-space: pre-wrap; overflow-wrap: break-word;
                                margin-top: .3rem; }
.toc { margin: .8rem 0 1.2rem; padding: .6rem .9rem; background: #f8f9fa;
       border: 1px solid #dee2e6; border-radius: 8px; font-size: .95rem;
       line-height: 1.9; }
.toc a { color: #1971c2; text-decoration: none; margin-right: 1.1rem;
         display: inline-block; }
.toc a:hover { text-decoration: underline; }
details.section { margin: 1.4rem 0 0; }
details.section > summary { cursor: pointer; }
details.section > summary::marker { color: #1971c2; }
details.section > summary h2 { margin-top: 0; display: inline-block; }
/* 手機（<=640px）：表格改成一張張卡片，橫向捲動改直向堆疊，好讀很多 */
@media (max-width: 640px) {
  body { margin: 1rem auto; }
  .tablewrap table, .tablewrap tbody, .tablewrap tr,
  .tablewrap th, .tablewrap td { display: block; width: auto; }
  .tablewrap thead { display: none; }
  .tablewrap tr { border: 1px solid #dee2e6; border-radius: 8px;
                   margin-bottom: .75rem; overflow: hidden; }
  .tablewrap td { border: none; border-bottom: 1px solid #f1f3f5; }
  .tablewrap td:last-child { border-bottom: none; }
  .tablewrap td::before { content: attr(data-label); display: block;
                            font-size: .72rem; font-weight: 700;
                            color: #868e96; margin-bottom: .15rem; }
}
"""

PWA_META = (
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="apple-mobile-web-app-title" content="AlphaVibe">'
    '<meta name="theme-color" content="#1971c2">'
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


def render(store):
    stances = store.list_stances()
    comments = store.recent_comments(limit=20)["results"]
    modules = store.list_philosophy()["modules"]
    snapshots = store.list_latest_snapshots()
    holdings = store.get_holdings()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 持股與立場依代碼合併：庫存分析要能一眼對應，不用滑動比對兩張表
    stance_by_code = {s["code"]: s for s in stances}
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
        "<p><a href=\"/screen\" style=\"display:inline-block;padding:.5rem 1rem;"
        "background:#1971c2;color:#fff;border-radius:6px;text-decoration:none;"
        "font-weight:600;margin-right:.6rem;\">第一層選股篩選 →</a>"
        "<a href=\"/market-scan\" style=\"display:inline-block;padding:.5rem 1rem;"
        "background:#1971c2;color:#fff;border-radius:6px;text-decoration:none;"
        "font-weight:600;\">第二層全市場批次篩選 →</a></p>")

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

    parts.append("<details class=\"section\" id=\"section-holdings\" open>"
                 "<summary><h2>我的庫存與分析%s</h2></summary>"
                 % ("（%s）" % esc(holdings["snapshot_date"])
                    if holdings["snapshot_date"] else ""))
    if holdings["holdings"]:
        price_map = store.get_stock_prices()
        industry_map = store.get_stock_industries()

        # 市值：股數 × 快取股價；查不到股價（或無股數）的持股不計入市值，
        # 也不計入下面持股比例的分母——分母只算「有市值資料」的部分。
        market_values = {}
        for h in holdings["holdings"]:
            price_info = price_map.get(h["code"])
            if price_info and h.get("shares") is not None:
                market_values[h["code"]] = h["shares"] * price_info["price"]
        total_value = sum(market_values.values())

        if price_map:
            latest_price_update = max(v["updated_at"] for v in price_map.values())
            price_meta = "價格更新時間：%s" % esc(latest_price_update)
        else:
            price_meta = "尚未更新股價，執行 refresh_holdings_prices"
        parts.append("<p class=\"meta\">%s ｜ 僅計入已更新價格的持股，"
                     "持股比例可能不含全部庫存</p>" % price_meta)

        parts.append("<div class=\"tablewrap\"><table><thead><tr><th>代碼</th><th>名稱</th>"
                     "<th>產業別</th><th>股數</th><th>平均成本</th><th>市值</th>"
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

            value = market_values.get(h["code"])
            if value is not None:
                value_text = "%s 元" % format(value, ",.0f")
                ratio = (value / total_value * 100) if total_value else None
                ratio_text = ("%.1f%%" % ratio) if ratio is not None else "—"
            else:
                value_text = "未更新價格"
                ratio_text = "未更新價格"

            parts.append(
                "<tr><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"產業別\">%s</td>"
                "<td data-label=\"股數\">%s</td><td data-label=\"平均成本\">%s</td>"
                "<td data-label=\"市值\">%s</td><td data-label=\"持股比例\">%s</td>"
                "<td data-label=\"立場\" class=\"stance\" style=\"color:%s\">%s</td>"
                "<td data-label=\"估值依據\">%s</td><td data-label=\"理由\">%s</td>"
                "<td data-label=\"更新日期\">%s</td></tr>"
                % (esc(h["code"]), esc(h["name"]), industry_text,
                   esc(h["shares"]), esc(h["avg_cost"]), value_text, ratio_text,
                   color, stance_text, valuation_text, reason_text, date_text))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">尚無持股快照。</p>")
    parts.append("</details>")

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
        parts.append("<p class=\"empty\" style=\"color:#c92a2a\">%s</p>" % esc(error))
    parts.append(
        "<form method=\"post\" action=\"/screen\">"
        "<textarea name=\"codes\" rows=\"6\" "
        "style=\"width:100%;font-size:1rem;padding:.5rem;box-sizing:border-box;\" "
        "placeholder=\"3485,6953,6719\"></textarea>"
        "<p><button type=\"submit\" style=\"font-size:1rem;padding:.6rem 1.2rem;\">"
        "開始篩選</button></p></form>")
    parts.append("</body></html>")
    return "".join(parts)


def render_screen_results(result):
    """POST /screen 結果頁；result 為 screener.screen_stocks() 的回傳值。"""
    parts = [_screen_page_head("選股篩選結果")]
    parts.append("<p class=\"meta\"><a href=\"/screen\">← 重新篩選</a> ｜ "
                 "<a href=\"/\">回知識庫檢視</a></p>")
    parts.append("<h1>選股篩選結果</h1>")

    if result.get("error"):
        parts.append("<p class=\"empty\" style=\"color:#c92a2a\">%s</p>" % esc(result["error"]))
        parts.append("</body></html>")
        return "".join(parts)

    rows = result.get("results") or []
    hit_count = sum(1 for r in rows if r.get("meets_framework"))
    parts.append("<p class=\"meta\">共篩選 %d 檔，符合框架（PEG&lt;1 且回檔&gt;=40%%）"
                 "%d 檔（表格中以黃底標出）</p>" % (result.get("total", len(rows)), hit_count))

    if rows:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>PER</th><th>營收年增率</th>"
                     "<th>PEG</th><th>回檔幅度</th><th>目前價</th><th>符合框架</th>"
                     "<th>備註</th></tr></thead><tbody>")
        for r in rows:
            peg_text = ("%.2f" % r["peg"]) if r["peg"] is not None else "—"
            yoy_text = ("%.1f%%" % (r["revenue_yoy"] * 100)) if r["revenue_yoy"] is not None else "—"
            drawdown_text = ("%.1f%%" % (r["drawdown_pct"] * 100)) if r["drawdown_pct"] is not None else "—"
            per_text = ("%.2f" % r["per"]) if r["per"] is not None else "—"
            hit = r.get("meets_framework")
            row_style = " style=\"background:#fff3bf\"" if hit else ""
            hit_text = "符合" if hit else "—"
            note = esc(r.get("error")) if r.get("error") else "—"
            parts.append(
                "<tr%s><td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
                "<td data-label=\"PER\">%s</td><td data-label=\"營收年增率\">%s</td>"
                "<td data-label=\"PEG\">%s</td><td data-label=\"回檔幅度\">%s</td>"
                "<td data-label=\"目前價\">%s</td>"
                "<td data-label=\"符合框架\" class=\"stance\">%s</td>"
                "<td data-label=\"備註\">%s</td></tr>"
                % (row_style, esc(r["code"]), esc(r["name"]), per_text, yoy_text,
                   peg_text, drawdown_text, esc(r["current_price"]), hit_text, note))
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
                 "<button type=\"submit\" style=\"font-size:1rem;padding:.6rem 1.2rem;"
                 "background:#1971c2;color:#fff;border:none;border-radius:6px;\">"
                 "立即掃描（約需30秒~數分鐘）</button></form>" % esc(selected_id))

    parts.append("<details class=\"philomod\"><summary>這是什麼？</summary><pre>"
                 "用 TWSE/TPEx 官方批次資料，在框架鎖定的產業別內自動找候選"
                 "（不用手動貼代碼），範圍只有上市＋上櫃（興櫃沒有官方批次PER"
                 "資料，不在這次掃描範圍）。每天 02:00 也會自動掃描一次，"
                 "這裡永遠顯示最近一次結果。</pre></details>")

    if error:
        parts.append("<p class=\"empty\" style=\"color:#c92a2a\">%s</p>" % esc(error))

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
    parts.append("<p class=\"meta\">最近一次掃描：%s（%s）｜候選 %d 檔，符合框架 %d 檔</p>"
                 % (esc(run.get("run_at")), trigger_text,
                    run.get("candidate_count", len(rows)), hit_count))

    twse_err = run.get("twse_error")
    tpex_err = run.get("tpex_error")
    if twse_err or tpex_err:
        parts.append("<p class=\"empty\" style=\"color:#c92a2a\">")
        if twse_err:
            parts.append("TWSE 資料源異常：%s　" % esc(twse_err))
        if tpex_err:
            parts.append("TPEx 資料源異常：%s" % esc(tpex_err))
        parts.append("（該市場當次候選數會變少，不影響另一邊）</p>")

    parts.append("<details class=\"section\" open><summary><h2>符合框架的候選（%d 檔）</h2>"
                 "</summary>" % hit_count)
    if hit_rows:
        parts.append("<div class=\"tablewrap\"><table><thead><tr>"
                     "<th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>"
                     "<th>PER</th><th>營收年增率</th><th>PEG</th><th>回檔幅度</th>"
                     "<th>目前價</th></tr></thead><tbody>")
        for r in hit_rows:
            parts.append(_market_scan_row_html(r, highlight=False))
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
                     "<th>目前價</th><th>符合框架</th><th>備註</th></tr></thead><tbody>")
        for r in rows:
            parts.append(_market_scan_row_html(r, highlight=True))
        parts.append("</tbody></table></div>")
    else:
        parts.append("<p class=\"empty\">這次掃描沒有候選（可能兩個資料源都異常，"
                     "或框架門檻下確實沒有符合的股票）。</p>")
    parts.append("</details>")

    parts.append("</body></html>")
    return "".join(parts)


def _market_scan_row_html(r, highlight):
    """/market-scan 結果表格的單一列。highlight=True 才畫黃底（符合框架
    候選區塊裡全部列都符合，畫了反而是雜訊，所以那裡傳 False）。
    highlight=True 時多渲染「符合框架」「備註」兩欄，維持與全部候選表格
    的欄位對齊；highlight=False（符合框架區塊）省略這兩欄，因為值恆為
    「符合」「—」，不提供資訊。"""
    peg_text = ("%.2f" % r["peg"]) if r["peg"] is not None else "—"
    yoy_text = ("%.1f%%" % (r["revenue_yoy"] * 100)) if r["revenue_yoy"] is not None else "—"
    drawdown_text = ("%.1f%%" % (r["drawdown_pct"] * 100)) if r["drawdown_pct"] is not None else "—"
    per_text = ("%.2f" % r["per"]) if r["per"] is not None else "—"
    base = (
        "<td data-label=\"代碼\">%s</td><td data-label=\"名稱\">%s</td>"
        "<td data-label=\"市場\">%s</td><td data-label=\"產業別\">%s</td>"
        "<td data-label=\"PER\">%s</td><td data-label=\"營收年增率\">%s</td>"
        "<td data-label=\"PEG\">%s</td><td data-label=\"回檔幅度\">%s</td>"
        "<td data-label=\"目前價\">%s</td>"
        % (esc(r["code"]), esc(r["name"]), esc(r.get("market")), esc(r.get("industry")),
           per_text, yoy_text, peg_text, drawdown_text, esc(r.get("current_price"))))
    if not highlight:
        return "<tr>%s</tr>" % base
    hit = r.get("meets_framework")
    row_style = " style=\"background:#fff3bf\"" if hit else ""
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
