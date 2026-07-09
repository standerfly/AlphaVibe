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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kb_store import KBStore  # noqa: E402

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
         vertical-align: top; }
th { background: #f1f3f5; white-space: nowrap; }
.stance { font-weight: 700; white-space: nowrap; }
.empty { color: #868e96; padding: 1rem 0; }
.comment { border-left: 3px solid #adb5bd; margin: .8rem 0; padding: .2rem .8rem; }
.comment .head { font-size: .8rem; color: #868e96; margin-bottom: .2rem; }
.tag { background: #e7f5ff; color: #1971c2; border-radius: 3px;
       padding: 0 .4rem; font-size: .75rem; margin-right: .4rem; }
"""


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


def render(store):
    stances = store.list_stances()
    comments = store.recent_comments(limit=20)["results"]
    modules = store.list_philosophy()["modules"]
    snapshots = store.list_latest_snapshots()
    holdings = store.get_holdings()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = []
    parts.append("<!doctype html><html lang=\"zh-Hant\"><head>"
                 "<meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                 "<title>AlphaVibe 知識庫檢視</title>"
                 "<style>%s</style></head><body>" % CSS)
    parts.append("<h1>AlphaVibe 知識庫檢視</h1>")
    parts.append("<p class=\"meta\">產出時間 %s ｜ 立場 %d 檔 ｜ 分析快照 %d 檔 ｜ "
                 "持股快照 %d 檔 ｜ 近期評論 %d 則 ｜ 哲學模組 %d 個 ｜ "
                 "唯讀快照，重跑 report.py 更新</p>"
                 % (now, len(stances), len(snapshots), holdings["count"],
                    len(comments), len(modules)))
    parts.append("<p class=\"meta\">本頁為研究輔助資訊，非投資建議。</p>")

    parts.append("<h2>Layer 2 個股立場總覽</h2>")
    if stances:
        parts.append("<table><tr><th>代碼</th><th>名稱</th><th>立場</th>"
                     "<th>進場條件</th><th>估值依據</th><th>理由</th>"
                     "<th>日期</th><th>來源</th></tr>")
        for s in stances:
            color = STANCE_COLORS.get(s["stance"], DEFAULT_STANCE_COLOR)
            parts.append(
                "<tr><td>%s</td><td>%s</td>"
                "<td class=\"stance\" style=\"color:%s\">%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (esc(s["code"]), esc(s["name"]), color, esc(s["stance"]),
                   esc(s["entry_condition"]), esc(s["valuation_metric"]),
                   esc(s["reason"]), esc(s["date"]), esc(s["source_ref"])))
        parts.append("</table>")
    else:
        parts.append("<p class=\"empty\">尚無立場資料——開始跟 Claude 聊，"
                     "確認入庫後這裡就會長出來。</p>")

    parts.append("<h2>分析快照（每檔最新一筆；歷次 diff 用 get_snapshots 或待 1c 儀表板）</h2>")
    if snapshots:
        parts.append("<table><tr><th>代碼</th><th>名稱</th><th>日期</th>"
                     "<th>當時價</th><th>當時估值</th><th>驅動因素</th>"
                     "<th>下檔風險</th><th>框架</th><th>來源數</th></tr>")
        for sn in snapshots:
            parts.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (esc(sn["code"]), esc(sn["name"]), esc(sn["snapshot_date"]),
                   esc(sn["price_at_time"]), esc(sn["valuation_at_time"]),
                   clip(sn["thesis"]), clip(sn["risks"]),
                   esc(sn["framework_version"]), sn["source_count"]))
        parts.append("</table>")
    else:
        parts.append("<p class=\"empty\">尚無分析快照。</p>")

    parts.append("<h2>持股快照%s</h2>"
                 % ("（%s）" % esc(holdings["snapshot_date"])
                    if holdings["snapshot_date"] else ""))
    if holdings["holdings"]:
        parts.append("<table><tr><th>代碼</th><th>名稱</th><th>股數</th>"
                     "<th>平均成本</th><th>來源</th></tr>")
        for h in holdings["holdings"]:
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                         "<td>%s</td></tr>"
                         % (esc(h["code"]), esc(h["name"]), esc(h["shares"]),
                            esc(h["avg_cost"]), esc(h["source_ref"])))
        parts.append("</table>")
    else:
        parts.append("<p class=\"empty\">尚無持股快照。</p>")

    parts.append("<h2>Layer 3 最近評論（最多 20 則）</h2>")
    if comments:
        for c in comments:
            symbols = (" ｜ " + esc(c["symbols"])) if c["symbols"] else ""
            parts.append(
                "<div class=\"comment\"><div class=\"head\">"
                "<span class=\"tag\">%s</span>%s%s</div><div>%s</div></div>"
                % (esc(c["source_tag"]), esc(c["date"]), symbols, esc(c["body"])))
    else:
        parts.append("<p class=\"empty\">尚無評論資料。</p>")

    parts.append("<h2>Layer 1 哲學模組</h2>")
    if modules:
        parts.append("<ul>%s</ul>" % "".join(
            "<li>%s（%d bytes）</li>" % (esc(m["module"]), m["size"])
            for m in modules))
    else:
        parts.append("<p class=\"empty\">尚無哲學模組。</p>")

    parts.append("</body></html>")
    return "".join(parts)


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
    print("已產出：%s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
