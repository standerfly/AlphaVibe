# AlphaVibe 後端架構分層與模組邊界審查

- 審查日期：2026-09-17
- 範圍：`app/`（18 檔 3735 行）、`poc/kb-mcp/`（32 檔 14680 行，不含 tests/）
- 分支：`function/alphavibe` @ `5a72ac0`
- 性質：唯讀審查，未修改任何專案檔案
- 結論：**PASS — 發現 15 個問題（必修 3／該修 8／可不修 4）**

---

## 0. 給 PO 的三行版

1. **先花半天做 F1（認證 fail-open）與 F2（正式服務跑哪份 code 沒人知道）**——
   這兩個都不是美學問題，是「某天東西壞了你不會知道」的問題，而且都便宜。
2. **接下來最值得的一週是 F4（report.py 砍死碼）**——有硬證據顯示你**現在正在
   花錢維護看不見的程式碼**：退役後的 6 次 commit 有 4 次在改不可達的函式。
3. **kb_store.py／server.py 的「太長」不急**——它們長，但長得整齊，
   而且有 400+ 個測試釘著。真要動，先切最乾淨的那一刀（資產領域，512 行，
   只有 2 個呼叫端），不要一次大搬家。

---

## 1. `poc/` 定位錯置的真實成本

### 接法的事實（已查證）

`app/` 用「執行期插 `sys.path`」接進 `poc/kb-mcp/`：

```
app/deps.py:42-46            _KB_MCP_DIR = <repo>/poc/kb-mcp ; sys.path.insert(0,…) ; from kb_store import KBStore
app/us_stock_deps.py:32-36   同樣寫法，獨立再算一次
app/routers/mcp.py:37-41     同上
app/routers/screen.py:49-55  同上
app/routers/holdings.py:66-71
app/routers/market_scan.py:80-86
app/routers/actions.py:84-92
app/routers/dashboard.py:83-89
app/routers/holdings_import.py:85-91
app/routers/stock_detail.py:78-84
app/tests/test_smoke.py:73
app/tests/test_quick_input.py:44
```

**共 12 份**同樣的三行 `sys.path.insert` 樣板。沒有符號連結、沒有 `.pth`、
沒有 `pip install -e`、沒有 `pyproject.toml`（repo 根目錄無任何 Python
封裝檔案，已查證）。每個檔案都刻意寫成 idempotent 並在註解說明「不依賴
其他檔案先 import 過」——這是有意識的設計，不是疏忽。

### 脆弱點（實際存在的，不是理論的）

1. **`poc/kb-mcp` 目錄名有連字號，不可能成為 package**。這就是為什麼只能走
   `sys.path` 而不能 `from poc.kb_mcp import kb_store`。改名 `kb-mcp` →
   `kb_mcp` 是搬家的必要前置。
2. **`sys.path.insert(0, …)` 把 32 個模組名塞進全域命名空間最前面**：
   `server`、`report`、`benchmark`、`screener`、`pnl`、`frameworks`…
   其中 `server` 這個名字風險最高——任何未來新增的第三方套件若提供
   `server` 模組，會被 `poc/kb-mcp/server.py` 遮蔽（反之亦然）。
   **已實測**（用 `importlib.machinery.FileFinder` 對 `sys.path` 上除
   `poc/kb-mcp` 以外的每個路徑逐一 find_spec 這 32 個名字）：
   **目前零衝突**。但這是一顆定時炸彈，而且爆炸形式是「import 到錯的東西」
   而非 ImportError，極難查。
3. **兩套 Python 直譯器跑同一份 `poc/` 程式碼**（見 F10）：
   `com.alphavibe.marketscan`／`com.alphavibe.moduled` 用
   `/usr/bin/python3`（系統 3.9.6），`com.alphavibe.usstockscan`／
   `com.alphavibe.reportserver` 用 `.venv/bin/*`。
4. **macOS bytecode 快取坑**（CLAUDE.md 2026-09-03 教訓）對 `/usr/bin/python3`
   跑的排程特別容易踩到，因為快取在 `~/Library/Caches/com.apple.python/`
   而非 repo 內。

### 隱性依賴盤點（搬家會一起壞的）

| 類型 | 位置 | 綁死的路徑 |
|---|---|---|
| launchd | `com.alphavibe.marketscan.plist` | `poc/kb-mcp/market_scan.py` |
| launchd | `com.alphavibe.moduled.plist` | `poc/kb-mcp/module_d_scheduler.py` |
| launchd | `com.alphavibe.usstockscan.plist` | `poc/kb-mcp/us_stock_scan.py` |
| launchd | `com.alphavibe.reportserver.plist` | `ALPHAVIBE_DATA_DIR=…/poc/data` |
| MCP（Claude Code） | `<repo>/.mcp.json` | `poc/kb-mcp/server.py`、`poc/kb-mcp/us_stock_mcp_server.py` |
| MCP（Cline） | `~/.cline/data/settings/cline_mcp_settings.json` | `/Users/…/AlphaVibe/poc/kb-mcp/server_readonly.py`（絕對路徑） |
| 資料目錄 | `app/deps.py:49`、`app/us_stock_deps.py:39-40` | `_KB_MCP_DIR/../data` 推算 |
| 測試 | `poc/kb-mcp/tests/*.py` | 24 份 `sys.path.insert(0, dirname(HERE))` |
| cron | 無（已查證 `crontab -l` 為空） | — |

**注意**：`poc/data/`（正式資料庫 `alphavibe.db`、`us_stocks.db`）住在 `poc/`
底下，而且路徑是用 `poc/kb-mcp/../data` **推算**出來的。搬 `poc/kb-mcp/`
一定連帶決定 `poc/data/` 怎麼辦。

### 搬 vs 不搬

| | 搬（`poc/kb-mcp/` → `src/alphavibe/`，做成真 package） | 不搬（只改名去掉 poc 字樣） | 什麼都不做 |
|---|---|---|---|
| 工作量 | **大（一週以上）** | 中（1–3 天） | 0 |
| 要動的檔案 | 12 份 app/ sys.path 樣板、24 份 tests sys.path、24 個模組間的 `import screener` → `from alphavibe import screener`、6 份 launchd plist、2 份 MCP 設定、資料目錄推算 2 處 | 同上但只改路徑字串，import 寫法不變 | — |
| 風險 | 高。3 組循環 import（見 §6）在改成 package 相對匯入後行為可能變；`poc/data/` 搬動會碰正式 DB | 中。改名期間 launchd／MCP 設定若沒同步，排程與連接器靜默失效 | — |
| 真正買到什麼 | 可 `pip install -e`、IDE 正確跳轉、消滅模組名污染、消滅 12 份樣板 | 只買到「名字不叫 poc 了」 | — |
| 不做的代價 | 每新增一支 router 要再抄一次三行樣板；模組名污染風險持續；新人（或新 session）看到 poc 會誤判可以亂動 | 同左 | 同左 |

**建議**：**現在不搬**。理由：`poc/` 這個名字造成的是「認知成本」不是「故障成本」，
而 CLAUDE.md 已經把事實寫清楚了。真正在咬人的是 §3 的死碼與 §5 的樣板重複，
那兩件事可以在**不搬家**的前提下解決（見 F5 的 20 行修法）。
如果未來真的要搬，把它跟 F4（砍死碼）綁在同一次做——先砍到 report.py 剩
1000 行再搬，搬的量少一半。

---

## 2. 死碼確認

### `report_server.py`（912 行）—— **可以刪**

證據（四個角度都查過）：

- **launchd**：`com.alphavibe.reportserver.plist` 現在跑
  `/Users/…/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080`，
  不是 `report_server.py`。舊版備份在
  `~/Library/LaunchAgents/backup-20260822/`。
- **執行中的行程**：`launchctl list | grep alphavibe` → `com.alphavibe.reportserver`
  PID 56897，`ps` 確認命令列是 uvicorn。沒有任何 `report_server.py` 行程。
- **cron**：`crontab -l` 為空。
- **import**：全 repo 只有 `poc/kb-mcp/tests/test_report_server.py:40` 一處
  `import report_server`。**沒有任何生產程式碼 import 它**。
- **MCP 設定**：`.mcp.json` 與 `cline_mcp_settings.json` 都不指向它。
- **git**：最後一次改動是 `658438b`（2026-08-19），退役日 2026-08-22 之後
  **零 commit**。真的凍結了。

**結論：可以刪。** 但注意兩個連帶物：
1. `poc/kb-mcp/tests/test_report_server.py`（58KB／63 個測試）要一起刪。
2. 刪 `report_server.py` 會讓 `report.py` 的 1846 行 HTML 渲染函式**同時變成
   零呼叫端**——這正是 F4 的機會點，兩件事要一起做才划算。

### `mcp_http_gateway.py`（282 行）—— **不能刪，它是活的**

**任務敘述中「據稱已退役」這一點是錯的。** 證據：

```
app/routers/mcp.py:41   import mcp_http_gateway
app/routers/mcp.py:70   mcp_http_gateway.handle_mcp_post(...)   ← POST /mcp 的實作
app/routers/mcp.py:96   mcp_http_gateway.path_token_matches(...)
app/routers/mcp.py:99   mcp_http_gateway.handle_mcp_post(...)   ← POST /mcp/{token}
app/deps.py:123（註解）  說明 _is_mcp_path() 為何要放行這兩條路由
```

退役的是**它的獨立埠常駐服務**（`com.alphavibe.mcphttpgateway.plist.disabled-20260822`，
原本跑 8082 埠），不是模組本身。手機 Claude App 連接器
（`https://chancefully-erosive-lilian.ngrok-free.dev/mcp/<token>`）今天仍然
走這段程式碼。

**模組內部的死碼**：`MCPHandler` class（`mcp_http_gateway.py:209-`）與 `main()`
是那個獨立埠外殼，`app/routers/mcp.py` 只呼叫上面的純函式，不經過 class。
約 73 行死碼，但它同時也是 `test_mcp_http_gateway.py` 21 個測試裡
`MCPHTTPGatewayTest` 那組的測試載體。刪了要改測試，**不划算，留著**。

### 這兩份測試還在跑嗎？在維持什麼？

實跑（2026-09-17）：

```
cd poc/kb-mcp/tests && python3 -m unittest test_report_server test_mcp_http_gateway
Ran 84 tests in 1.838s
OK
```

- 84 個測試全過、**1.8 秒**、無網路依賴（`finmind_client.get_stock_info` 有被
  `unittest.mock.patch` 擋住，`test_report_server.py:498/542/618`）。
- 所以它們**不是跑不動的殭屍**，也不是 CI 時間黑洞。它們在維持的是
  「一個沒有任何人執行的 HTTP server 的 63 個行為」。
- 成本不在執行時間，在**認知**：未來有人改 `report.py` 的共用函式時，
  會被 test_report_server 的失敗擋下來，然後花時間去修一個沒人用的伺服器。

---

## 3. 巨型檔案的內部結構

### 3.1 `report.py`（2870 行）—— 最值得動的一個

**它混了幾種職責？五種**：

| 職責 | 行數 | 位置 |
|---|---|---|
| CSS 樣式表（Python 字串常數） | 316 | `report.py:33-348` |
| PWA meta + PNG icon 產生器 | 26 | `report.py:349-374` |
| **資料查詢／組裝純函式** | ~516 | 散落全檔，21 個函式 |
| HTML 頁面渲染（12 個 `render_*` + 30 個 `_*_html`） | ~1846 | 散落全檔 |
| CLI 入口（產靜態 report.html） | 24 | `report.py:2841-2866` |

**關鍵發現：正式服務只用得到 516 行（18%）。**

用 AST 從 `app/` 的實際呼叫點反向做可達性分析（不看 docstring，只看真的
呼叫），`app/` 進入 `report.py` 的**全部**入口是：

```
report.STOCKLIST_PAGE_SIZE          app/routers/holdings.py:180,182,183
report._tracked_stock_rows          app/routers/holdings.py:156
report._theme_concentration_data    app/routers/holdings.py:194
report._latest_module_d_batch       app/routers/stock_detail.py:144
report._split_module_d_batch        app/routers/stock_detail.py:158
report._verdict_banner_html         app/routers/stock_detail.py:160
report._invested_amount             app/routers/stock_detail.py:168
report._portfolio_context           app/routers/stock_detail.py:184
report._avg_cost_for_chart          app/routers/stock_detail.py:189
report._carry_over_avg_cost         app/routers/holdings_import.py:165
report._diff_holdings               app/routers/holdings_import.py:168
（dashboard.py 另外用到 _render_today_highlights_section／
  _render_new_candidates_section／_render_strategy_settings_section／
  _format_condition_text 的「邏輯對照」，實際呼叫見 dashboard.py:130,153）
```

**沒有任何一個 `render_*` 公開函式被正式服務呼叫。** 遞迴展開這些進入點
後，可達函式 21 個／516 行；**不可達 41 個函式／1846 行**，加上 316 行 CSS
與 CLI，合計 **約 2190 行（76%）只能經由已退役的 `report_server.py` 到達**。

不可達清單（行號區間）：

```
make_icon_png                 361-374    (14)
clip                          383-389     (7)
reason_html                   392-403    (12)
_render_holdings_section      406-519   (114)
_render_watchlist_only_section 522-560   (39)
render                        563-679   (117)
_render_quick_input_section   837-919    (83)
render_dashboard              922-980    (59)
_fmt_price                    988-997    (10)
_delta_badge                 1000-1012   (13)
_stocklist_link              1108-1116    (9)
render_stock_list_page       1119-1241  (123)
_valuation_source_text       1244-1250    (7)
_finding_row_html            1304-1312    (9)
_module_d_card_html          1342-1436   (95)
_concentration_bar_html      1439-1457   (19)
_concentration_card_html     1460-1517   (58)
_fmt_amount                  1520-1526    (7)
_position_plan_card_html     1564-1621   (58)
_combo_chart_aligned_trades  1683-1702   (20)
_last_sell_position          1705-1713    (9)
_render_combo_chart_svg      1716-1867  (152)
_chart_stats_html            1923-1969   (47)
_holdings_card_html          1972-2060   (89)
_reason_pin_html             2063-2077   (15)
_notes_card_html             2080-2112   (33)
render_stock_detail_page     2115-2232  (118)
render_holdings_preview      2276-2363   (88)
_screen_page_head            2366-2372    (7)
render_screen_form           2375-2402   (28)
_thresholds_condition_text   2447-2463   (17)
render_screen_results        2466-2515   (50)
render_market_scan_page      2518-2650  (133)
compose_market_scan_track_reason 2666-2707 (42)
_market_scan_track_form_html 2710-2726   (17)
render_track_conflict_page   2729-2757   (29)
render_track_result_page     2760-2774   (15)
render_track_error_page      2777-2784    (8)
_market_scan_row_html        2787-2838   (52)
default_data_dir             2841-2843    (3)
main                         2846-2866   (21)
```

**這筆債正在收利息（硬證據）**：`report.py` 是近 90 天**churn 最高的後端檔案
（24 次 commit）**。退役日 2026-08-22 之後的 6 次 commit 中，**有 4 次改的是
上面這張不可達清單裡的函式**：

```
95a5059 (2026-09-03) → render_market_scan_page                    100% 死碼
c712c8b (2026-09-03) → render_market_scan_page, _market_scan_row_html  幾乎全死碼
66b8f2c (2026-09-03) → _chart_stats_html                          100% 死碼
0fffc7f (2026-09-03) → _chart_stats_html, _holdings_card_html（死）+ _avg_cost_for_chart（活）
e5dd491 (2026-08-24) → _tracked_stock_rows, _portfolio_context     活
8a0ec6e (2026-08-24) → _tracked_stock_rows                         活
```

**切法草案**（配合刪 `report_server.py` 一起做）：

```
poc/kb-mcp/report.py（2870）
  ├─ 保留 → poc/kb-mcp/report_data.py  約 520 行
  │    esc, _fmt_num, _fmt_pct, _row_status_text, _invalidation_text,
  │    _format_condition_text, _tracked_stock_rows, _theme_concentration_data,
  │    _portfolio_context, _invested_amount, _latest_module_d_batch,
  │    _split_module_d_batch, _verdict_banner_html, _avg_cost_for_chart,
  │    _sparkline_points, _render_sparkline_svg, _carry_over_avg_cost,
  │    _diff_holdings, _render_today_highlights_section,
  │    _render_new_candidates_section, _render_strategy_settings_section,
  │    STOCKLIST_PAGE_SIZE, _NOTE_TAGS
  │  （順手把其中 11 個 `_` 私有名改成公開名，解掉 F6 的一半）
  └─ 刪除 → 41 個渲染函式 + CSS 常數 + PWA_META + make_icon_png + main()
            約 2190 行，連同 report_server.py(912) 與
            tests/test_report_server.py(58KB) 一起刪
```

**切割風險**：
- `_verdict_banner_html` 回傳 HTML 片段，**必須保留**（正式前端在用，見 F6）。
  它引用的 `.verdict*` CSS 已經在 `web/src/styles/tokens.css:124-130` 有一份，
  所以刪 `report.CSS` 不會讓正式頁面掉樣式——**但這件事沒有任何測試在守**。
- `tests/test_report.py`（73KB／95 個測試）大部分在測要刪掉的渲染函式，
  要一起精簡。這是這項工作的主要工時來源。
- CLAUDE.md 2026-08-19 教訓（斷言會誤命中內嵌 CSS）在刪掉 CSS 常數後
  **自動消失**——這是額外紅利。

**工作量：大（一週以上）**，其中 report.py 本身半天，`test_report.py` 精簡
是大頭。**嚴重度：該修。**

### 3.2 `kb_store.py`（2121 行）

**混了幾種職責？13 個資料領域，外加一個非 SQLite 的檔案 IO 領域。**
單一 `KBStore` class，79 個方法／1529 行，加上 277 行的 `SCHEMA` 字串常數
（`kb_store.py:19-295`）與 `_MIGRATIONS`（`301-349`）。

| 領域 | 方法數 | 行數 | 備註 |
|---|---|---|---|
| 資產 assets | 19 | **512** | `kb_store.py:1548-2129`，2026-08-21 新增的 5 張表 |
| 交易／出場門檻 | 10 | 152 | |
| 個股參考資料（alias/price/valuation/industry/theme） | 12 | 142 | |
| core（連線／遷移／種子） | 4 | 120 | |
| 全市場掃描 | 4 | 111 | |
| 快取（revenue/auto_score/financial） | 6 | 95 | |
| 留言 | 5 | 84 | |
| 持股 | 2 | 80 | |
| 模組 D | 3 | 75 | |
| 快照 | 3 | 50 | |
| 立場 | 4 | 48 | |
| 部位計畫 | 3 | 30 | |
| **哲學庫（純檔案 IO，非 SQLite）** | 4 | 30 | `kb_store.py:1510-1546` |

**天然切割線：資產領域。** 已查證它的呼叫端**只有兩個**：
`app/routers/assets.py`（38 處）與 `poc/kb-mcp/seed_assets_once.py`（5 處）。
跟台股領域**零重疊**——不共用任何資料表、不被 `server.py`／`report.py`／
`review_engine.py` 呼叫。

**切法草案（Mixin，不改任何呼叫端）**：

```python
# poc/kb-mcp/kb_store_assets.py   （新檔，約 560 行：512 行方法 + 資產 5 張表的 SCHEMA 片段）
class AssetStoreMixin:
    def list_asset_pockets(self, …): …
    # …19 個方法原封不動搬過來

# poc/kb-mcp/kb_store.py  （剩約 1560 行）
from kb_store_assets import AssetStoreMixin
class KBStore(AssetStoreMixin):
    …
```

呼叫端一行都不用改（`store.list_asset_pockets()` 照常可用），
`isinstance` / `KBStore(data_dir)` 也不變。

**第二刀（可選）**：把 4 個 philosophy 方法（30 行）搬進獨立的
`philosophy_store.py`——它們根本不碰 SQLite，只是 `os.path.join` + 讀寫 `.md`
檔，掛在 SQLite store 上是歷史包袱。呼叫端只有
`server.py`(7)／`server_readonly.py`(1)／`report.py`(2)。

**切割風險：低。** `tests/test_kb.py`（78KB）是整份 repo 最厚的測試，
搬完直接重跑就知道有沒有壞。唯一要注意的是 `SCHEMA` 常數要跟著拆或維持
在 `kb_store.py` 由 `__init__` 一次 `executescript`（建議後者，改動更小）。

**工作量：小（半天內，Mixin 做法）／中（1–3 天，若連 SCHEMA 與測試一起拆）。
嚴重度：可不修（現在不痛，但資產領域還在長，等它超過 800 行就會痛）。**

### 3.3 `server.py`（1335 行）

**混了三種職責，比例極度失衡**：

| 職責 | 行數 | 位置 |
|---|---|---|
| **`TOOLS` JSON schema 宣告（47 個工具）** | **828（62%）** | `server.py:34-861` |
| `Server.call_tool()` 分派（47 個 `if name == …` 分支） | 315 | `server.py:893-1207` |
| MCP stdio transport（`handle`／`main`／`_result`） | 66 | `server.py:1270-1335` |
| 其他（`refresh_holdings_prices` 等） | ~90 | |

**天然切割線非常清楚**：

```
poc/kb-mcp/server.py（1335）
  ├─ poc/kb-mcp/mcp_tool_schemas.py   828 行  純資料，零邏輯，零 import
  ├─ poc/kb-mcp/mcp_transport.py       66 行  handle/_result/main 的共用基底
  └─ poc/kb-mcp/server.py             ~440 行  Server class + call_tool 分派
```

`mcp_tool_schemas.py` 這一刀**零風險**——它是一個 list literal，搬過去後
`from mcp_tool_schemas import TOOLS` 即可。`server_readonly.py:41`
（`[t for t in kb_server.TOOLS if …]`）與 `mcp_http_gateway.py` 都是透過
`kb_server.TOOLS` 取用，只要 `server.py` 仍 re-export `TOOLS` 就完全不用改。

`call_tool()` 的 47 個 `if` 分支可以改成 dispatch dict，但**不建議現在做**：
現有寫法雖然長，每個分支都只有 3–10 行且高度一致，可讀性其實不差，
改成 dict 換來的好處有限，而風險是 47 個分支逐一搬動。

**工作量：小（半天，只做 schema 外移）。嚴重度：可不修。**

### 3.4 `review_engine.py`（1149 行）

**這一份寫得好，我的建議是不要動。** 說明檢查方式：逐一看了 31 個頂層定義，
它是「常數區（66-115）＋ 私有計算輔助（118-237）＋ 6 個公開複核函式
（`general_review` / `strategy_specific_review` / `laoyutou_signal_review` /
`position_control_suggestion` / `run_module_d_review` / `auto_score_review`）
＋ 2 個刷新函式（903-996）」。沒有 class、沒有狀態、每個公開函式都是
`(code, store, …) -> dict`。

唯一可挑的切割線是把 `refresh_price_and_valuation` / `refresh_stock_snapshot`
（`review_engine.py:895-996`，檔案裡已經用 `# ---` 分隔線自己標出來了）
搬進獨立的 `stock_refresh.py`——因為它們是**寫入**動作，跟其餘「唯讀複核」
語意不同。約 100 行。**做不做都可以，這是品味不是債。**

**工作量：小。嚴重度：可不修（明確建議：不修）。**

---

## 4. 台美股雙軌重複程度

前提理解正確：資料與邏輯必須獨立，**以下全部不建議合併資料或業務邏輯**，
只討論純機械性樣板。

### 4.1 量化重複

| 對照組 | 重複程度 | 證據 |
|---|---|---|
| `server.py:1270-1335` vs `us_stock_mcp_server.py:285-351` | **66 行中只有 6 行實質不同** | `diff -u` 實測：差異只有 serverInfo 的 name 字串、啟動 log 文案、一處換行排版 |
| `kb_store.py` vs `us_stock_store.py` 的 `__init__`/`close` | 結構相同，各約 20 行 | 兩邊都是 `abspath`→`makedirs`→`sqlite3.connect(check_same_thread=False)`→`row_factory`→`executescript(SCHEMA)`；`us_stock_store.py:129-148` 的註解甚至直接寫「比照 kb_store.py 2026-08-22 教訓」 |
| `finmind_client._read_token:19-29` vs `us_stock_price_client._read_token:48-58` | **11 行中只有 2 行不同** | 差異只有環境變數名（`FINMIND_TOKEN` vs `FMP_API_KEY`）與檔名（`finmind_token.txt` vs `fmp_token.txt`） |
| `_fetch` HTTP+JSON+錯誤信封 | **4 份**近乎同構 | `finmind_client.py:31-54`、`twse_price_client.py:171-192`、`tpex_client.py:65-96`、`us_stock_price_client.py:60-74`；都是 `Request(User-Agent)`→`urlopen(timeout=TIMEOUT)`→`json.loads`→`except HTTPError` 回 `{"error": "<X> HTTP %s"}`→`except Exception` 回 `{"error": "<X> 呼叫失敗"}` |
| `default_data_dir()` | **6 份** | `market_scan.py:431`、`report.py:2841`、`module_d_scheduler.py:26`、`us_stock_scan.py:211`、`server.py:862`（`_default_`）、`us_stock_mcp_server.py:205`（`_default_`） |
| `argparse` CLI 樣板（`--data-dir` / `--trigger`） | 3 份高度相同 | `market_scan.py:448-452`、`us_stock_scan.py:327-330`、`module_d_scheduler.py:32-35` |
| `us_stock_scan.py` vs `market_scan.py` 主體 | **幾乎不重複** | 兩邊的掃描邏輯完全不同（台股走 TWSE/TPEx 批次 openapi + framework 篩選；美股走 FMP 逐檔 + watch condition 評估）。這部分的「獨立」是實質的，不是重複 |
| `us_stock_store.py` vs `kb_store.py` 的業務方法 | **不重複** | 美股 40 個方法全是 trades/stances/watch_conditions/price_snapshots，跟台股方法名與語意都不同 |

### 4.2 可以抽、且不違反獨立性的東西

建議建一個 `poc/kb-mcp/_common/` 或單一 `common_util.py`，只放**零業務語意**
的東西（三項，合計約 120 行，可消除約 260 行重複）：

```python
# 1) HTTP JSON 取得器（消 4 份 _fetch 的樣板）
def fetch_json(url, *, source_label, user_agent, timeout=15, sleep_after=0):
    """回傳 {"data": …} 或 {"error": "<source_label> …"}，絕不拋例外。"""

# 2) Token 讀取（消 2 份 _read_token）
def read_token(env_var, data_dir, filename):

# 3) MCP stdio transport 基底（消 66 行逐行重複）
class StdioMCPServerBase:
    SERVER_NAME = None      # 子類覆寫
    TOOLS = ()              # 子類覆寫
    def call_tool(self, name, args): raise NotImplementedError
    def handle(self, msg): …   # 唯一一份
    def serve_forever_stdio(self): …
```

`server.py` 與 `us_stock_mcp_server.py` 各自繼承，`call_tool` / `TOOLS` /
`SERVER_NAME` 仍完全獨立——**資料獨立、業務邏輯獨立、只共用 JSON-RPC 訊框**。

**明確不要抽的**：`default_data_dir()`。雖然有 6 份，但它們的預設值語意
其實不同（台股 `alphavibe.db` vs 美股 `us_stocks.db` 只是檔名差，但
`app/deps.py` 與 `app/us_stock_deps.py` 刻意寫成兩份獨立的
fail-loud 防呆——那是 2026-08-22 事故後的有意設計，共用會讓防呆失去
「兩個 store 各自把關」的性質）。這 6 份重複**建議保留**。

**工作量：中（1–3 天）。嚴重度：該修（但優先序低於 F4）。**

---

## 5. `app/` 這層本身

### 好的部分（明確講出來，不用花錢）

- **沒有任何 router 直接寫 SQL 或繞過 store 層。** 檢查方式：對
  `app/routers/*.py` 與 `app/*.py` grep `execute(` / `SELECT` / `INSERT` /
  `UPDATE` / `DELETE` / `.conn` / `sqlite3`，命中的**全部**是 docstring 說明
  文字（`holdings_import.py:190`、`dashboard.py:102`、`deps.py:92-94`、
  `us_stock_deps.py:72-73`），沒有一處是程式碼。這層很乾淨。
- **`deps.py` 的資料目錄防呆設計紮實。** `_resolve_data_dir()`
  （`deps.py:52-87`）要求 `ALPHAVIBE_DATA_DIR` 明確設定（fail loud），
  且指向正式路徑時還要 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`。這是
  2026-08-22 事故的正確修法，`us_stock_deps.py:43-67` 獨立複製一份也是
  對的（見 §4.2 最後一段）。
- **router 切分合理。** 10 個 router 對應 10 個功能域，42 個端點，沒有一個
  router 承擔兩個不相干的域。`assets.py` 最大（544 行）是因為它有 20 個端點，
  不是因為職責混亂。

### `deps.py`（256 行）在做什麼

三件事，比例合理：

1. `sys.path` 接線 + `KBStore` re-export（`deps.py:36-46`，11 行）
2. 資料目錄解析與正式庫防呆（`deps.py:49-87`，39 行）
3. **Dashboard 認證整套**（`deps.py:107-256`，150 行）：HMAC 簽章 cookie
   簽/驗、Basic Auth 密碼比對、`DashboardAuthMiddleware`

第 3 項佔了 59%。嚴格說「認證」跟「dependency 注入」是兩件事，可以拆成
`app/auth.py`，但**它只有一個消費者（`main.py:89` 掛 middleware）**，
拆了收益極低。**建議不拆。**

### `app/routers/mcp.py`（106 行）跟三個 MCP server 的關係

實際拓樸（已查證）：

```
poc/kb-mcp/server.py  (KB MCP，47 工具，含寫入)
   ├── stdio ← <repo>/.mcp.json 的 "alphavibe-kb"          （Claude Code 本機）
   ├── stdio ← server_readonly.py（28 工具白名單）
   │             ← ~/.cline/.../cline_mcp_settings.json     （Cline，唯讀）
   └── 函式呼叫 ← mcp_http_gateway.handle_mcp_post()
                   ← app/routers/mcp.py:70,99               （HTTP，手機 App）
                     每次請求 new 一個 kb_server.Server()，finally 關 store

poc/kb-mcp/us_stock_mcp_server.py  (美股 MCP，8 工具)
   └── stdio ← <repo>/.mcp.json 的 "alphavibe-us-stock"     （Claude Code 本機）
       （沒有 HTTP 管道——手機連接器碰不到美股工具）
```

所以 `app/routers/mcp.py` 是**唯一的 HTTP→MCP 橋**，而且只橋台股那一支。
這個關係是清楚的，不是亂的。值得記錄的一點：`handle_mcp_post()` 內部
自己 `kb_server.Server(data_dir=…)`（`mcp_http_gateway.py:196-206`），
**不走 `Depends(get_kb_store)`**——所以 MCP 路徑有第二套 DB 連線生命週期。
它在 `finally` 正確關閉，且 `data_dir` 仍來自 `_resolve_data_dir()`
（防呆有生效），功能上沒問題，只是要知道有兩條路徑。

### 錯誤處理一致性：不一致，但傷害有限

三種形狀並存：

| 形狀 | 用在哪 | 例 |
|---|---|---|
| `HTTPException(400/404, detail="⚠️ …失敗：…")` 中文 | `actions.py`(5)、`holdings_import.py`(4)、`assets.py`(4) | `actions.py:157` |
| `HTTPException(400/404, detail="…")` **英文** | `us_stocks.py`(3) | `us_stocks.py:256` `"watch condition not found"` |
| **HTTP 200 + body 內 `{"error": …}`** | `screen.py` | `screen.py:81`、實作在 `screener.screen_stocks()` |
| 部分成功時 body 內 `errors: [{id, error}]` | `us_stocks.py:302-305` | |
| 完全不處理錯誤 | `dashboard.py`、`holdings.py`、`market_scan.py`、`stock_detail.py`（各 0 個 HTTPException） | |

`screen.py` 那一種是刻意的（docstring 明說「忠實反映既有函式行為」），
可以接受。真正該統一的是**語言**與 `assets.py` 的 `POST …/delete`
vs `us_stocks.py` 的 `DELETE`（見 F14）。

---

## 6. 依賴方向

### 實際圖（只畫專案內部）

```
                       ┌──────────── app/main.py ────────────┐
                       │  (10 routers + auth middleware)     │
                       └──┬──────────────────────────┬───────┘
                          │ Depends                  │ Depends
                    app/deps.py              app/us_stock_deps.py
                          │ sys.path                 │ sys.path
  ┌───────────────────────┴──────────────┐           │
  │                                      │           │
kb_store ◄── report ──┐          mcp_http_gateway   us_stock_store ◄── us_stock_mcp_server
  ▲         │ │ │     │                  │ (import)        ▲              │
  │         │ │ │     │                  ▼                 │              ▼
  │         │ │ │     │             server.py ─────────────┼──► (KBStore) us_trade_text_parser
  │         │ │ │     │                  ▲                 │
  │         │ │ │     │           server_readonly.py       └── us_stock_scan ──► us_stock_price_client
  │         │ │ │     └──► frameworks                                              │ (lazy)
  │         │ │ └──► pnl ◄────── price_position ⇄ review_engine                    ▼
  │         │ └──► screener ⇄ benchmark                                        yfinance
  │         │          │  ⇅ (lazy)
  │         │          └──► fundamentals_client ⇄ market_scan
  │         │                     │
  │         └──────────────► finmind_client / twse_price_client / tpex_client
  │                              （零專案內部依賴，最底層）
  └── module_d_scheduler, holdings_sync, seed_assets_once, backfill_*
```

### 循環依賴：3 組，全部已知且已用延遲 import 打斷

| 環 | 打斷點 | 註解品質 |
|---|---|---|
| `screener` → `fundamentals_client` → `market_scan` → `screener` | `fundamentals_client.py:57,121,163` 函式內 `import market_scan` / `import screener` | 好。`fundamentals_client.py:33-44` docstring 完整說明了環的形狀與為何函式內 import 安全 |
| `review_engine` → `price_position` → `review_engine` | `review_engine.py:781` 函式內 `import price_position` | 好。`review_engine.py:777-780` 有 4 行註解說明 |
| `screener` → `benchmark` → (`screener`) | `benchmark.py` **刻意不 import** `screener`，改由呼叫端傳 `window_days` | 最好的一種。`benchmark.py:13-15` 與 `:31-34` 都說明了 |

另外 `report.py:1268,1358,1474` 也有函式內 `import review_engine`，
但那**不是循環**（`review_engine` 不 import `report`），註解自承是為了
「避免 report.py 匯入時就拉進整條依賴鏈」的載入時間考量。

**評價：這三個環都是有意識管理的，不是意外。** 註解到位，未來維護者看得懂。
**不建議動**——真要解需要把常數抽到第四個模組，改動面比收益大。

### 反模式檢查

- **底層反向依賴上層：沒有。** 已查證 `poc/kb-mcp/**` 對
  `from app.` / `import app` / `app/routers` 的 grep，命中的兩處
  （`us_stock_mcp_server.py:24,36`）都是 docstring 裡的**說明文字**，
  不是程式碼。`poc/` 也完全不碰 `web/`。**依賴方向是乾淨的單向。**
- **跨層直接呼叫：有，見 F6。** `app/routers/*` 直接呼叫 `report.py` 的
  8 個底線私有函式。這是「上層 reach-in 下層私有」，不是反向依賴，
  但一樣會擋住重構。

---

# findings 清單

## 必修（正確性或資料風險）

### F1｜認證在環境變數遺失時 fail-open，而服務掛在公開 ngrok 網址上

- **位置**：`app/deps.py:206-208`、`app/deps.py:231`（`_is_mcp_path` 放行）、
  `poc/kb-mcp/mcp_http_gateway.py:100-101`
- **為什麼是問題**：兩道認證都寫成「未設定 token ＝ 不驗證」：
  - `deps.py:206-208`：`ALPHAVIBE_DASHBOARD_TOKEN` 未設定 → 整個主控台
    （含資產、持股、交易紀錄）無認證放行。
  - `mcp_http_gateway.py:100-101`：`ALPHAVIBE_MCP_TOKEN` 未設定 →
    `POST /mcp` 無認證，而該路徑**被 `deps.py:231` 明確豁免**於
    dashboard 認證之外，沒有第二層保護。此時任何人都能呼叫 47 個 MCP 工具，
    **包含 `save_holdings`／`save_stance`／`run_market_scan`／
    `save_trade_ledger_entry` 等寫入工具**。

  服務跑在 `ngrok http 8080 --url=chancefully-erosive-lilian.ngrok-free.dev`
  （`com.alphavibe.ngrok.plist`），ngrok 免費層本身**不提供任何認證**。
  兩個 token 都只存在於 `com.alphavibe.reportserver.plist` 的
  `EnvironmentVariables` 區塊——那是一個未受版控、可被任何編輯動作破壞的
  單點。今天是安全的（兩個變數都有值，實測 `/api/dashboard` 回 401），
  但這是「一個檔案編輯失誤 ＝ 正式資料庫對全世界開放讀寫」的結構。

  註：`path_token_matches()`（`mcp_http_gateway.py:127-132`）已經是
  fail-closed 且有註解說明為何要跟 `_auth_ok()` 不同——所以這個問題
  **作者已經想過一半**，只是沒回頭把 `_auth_ok()` 也改掉。
- **修法**：
  1. 把 `_auth_ok()` 改成 fail-closed，另用一個明確的
     `ALPHAVIBE_ALLOW_ANONYMOUS=1` 旗標保留本機開發的便利
     （比照 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE` 既有慣例，語意一致）。
  2. `app/main.py` 啟動時斷言：若 `ALPHAVIBE_DATA_DIR` 指向正式庫
     （`_PRODUCTION_DATA_DIR`）而兩個 token 任一為空 → 直接拒絕啟動。
     這一條讓「正式服務無認證」變成**開不起來**而不是**悄悄開著**。
  3. 在 `app/tests/` 加一個回歸檢查：token 未設定時 `POST /mcp`
     必須回 401 而不是 200。
- **工作量**：**小（半天內）**
- **嚴重度**：**必修**

### F2｜正式服務跑的是哪一份 code，沒有任何機制可以確認

- **位置**：`~/Library/LaunchAgents/com.alphavibe.reportserver.plist`
  （`WorkingDirectory` 直接指向工作樹 `/Users/stander/My_project/AlphaVibe`）、
  `app/main.py`（無版本／commit 端點）
- **為什麼是問題**（實測數據）：
  - 執行中的 uvicorn PID 56897 啟動於 **2026-09-10 11:13:00**，已連續運行
    6 天 20 小時。
  - 同一期間 `git reflog` 顯示工作樹在 2026-09-15 07:32 切到
    `docs/ai-safety-pacing-market-impact`、07:37 切回 `function/alphavibe`
    並 fast-forward 了 3 個 commit。
  - Python 模組在 process 啟動時一次載入。**正式服務載入的是 2026-09-10
    當下磁碟上的 `app/` 與 `poc/`**，之後的分支切換與 commit 一律沒有生效。
  - 本次比對結果是**幸運的**：`git diff 65ea4c1 HEAD -- app/ poc/` 為空
    （期間只動了 `web/src/*.jsx`），所以目前沒有實質分歧。但這是運氣，
    不是機制。
  - 真正的風險：**若服務在切到 `docs/*` 分支的那 5 分鐘內因為任何原因重啟
    （KeepAlive 為 true，crash 即自動重啟），launchd 會載入那個分支的
    `app/`**，而且沒有任何告警。
  - 相關佐證：`MEMORY.md` 已有一條「report.py 改完要重啟服務」的教訓，
    說明這個坑踩過，但當時只解決了「記得重啟」，沒解決「怎麼知道現在跑的
    是哪一份」。
- **修法**（三選一或組合，由便宜到徹底）：
  1. **最便宜**：`app/main.py` 加 `GET /api/version`，啟動時讀一次
     `git rev-parse HEAD` 與 `time.time()` 存成模組常數回傳。前端首頁角落
     顯示。這樣「服務是舊的」變成一眼可見。（半天）
  2. 正式服務改用**獨立的 git worktree 或 clone**
     （例如 `/Users/stander/My_project/AlphaVibe-prod`），`WorkingDirectory`
     指過去，部署＝在那個目錄 `git pull` + `launchctl kickstart`。
     開發分支切換從此不可能影響正式服務。（1 天）
  3. 加一支 `deploy.sh`：檢查工作樹乾淨 → 跑 `app/tests/test_smoke.py` →
     `launchctl kickstart` → 打 `/api/version` 驗證 commit 相符。（1 天）
- **工作量**：**小（方案 1，半天內）／中（方案 2+3，1–3 天）**
- **嚴重度**：**必修**

### F3｜資產情境試算：唯一的 app 層業務邏輯，零測試，且自承公式未經核對

- **位置**：`app/routers/assets.py:290-437`
  （`_SIMULATE_DISCLAIMER` 290-293、`_accumulation_balance_at_month` 297-311、
  `_withdrawal_balance_at_month` 312-326、`_build_curve_points` 327-350、
  `_simulate_asset_scenario` 351-413、端點 `415-437`）
- **為什麼是問題**：
  1. **架構上是異類**：`app/` 的其他 9 個 router 全部只做 HTTP 轉接，
     業務邏輯一律在 `poc/`（這是 `main.py:37-42` 明確宣告的設計原則）。
     這 120 行是唯一的例外——一段金融計算住在 router 裡。
  2. **零測試**：`app/tests/test_smoke.py` 與 `test_quick_input.py` 對
     `simulate` 的 grep 命中數為 **0**；`poc/kb-mcp/tests/` 也沒有
     （已查證 `_simulate_asset_scenario` 在 `poc/` 完全不存在）。
  3. **程式碼自己承認不可信**：`assets.py:290-293` 的
     `_SIMULATE_DISCLAIMER` 原文寫「此試算公式尚未跟你原始素材核對過精確版本，
     用範例反推目前有約 1~2% 誤差」，且這段字串**會回傳給前端顯示**。
     `web/src/components/NetWorthProjectionChart.jsx:12` 註解也指回這裡。
  4. 這是 PO 用來做**個人退休／提領規劃**的數字。1~2% 在 20 年複利上不是
     小數字，而且沒有人能確認誤差來源是公式假設（期末給付 vs 期初給付）
     還是實作 bug——因為沒有測試把假設釘下來。
- **修法**：
  1. 把這 4 個函式搬到 `poc/kb-mcp/asset_simulation.py`（純函式，無 IO），
     `assets.py:415` 改成呼叫它。恢復「app/ 不放業務邏輯」的一致性。
  2. 補 `poc/kb-mcp/tests/test_asset_simulation.py`：至少釘住
     (a) `r_m == 0` 的線性特例、(b) `r_w == 0` 的線性特例、
     (c) 一組 PO 手邊的參考數字（**這一步需要 PO 提供**——這正是
     disclaimer 說的「原始素材」），(d) `m <= 0` 的邊界。
  3. 測試通過、誤差查清楚之後，把 `_SIMULATE_DISCLAIMER` 拿掉或改寫。
- **工作量**：**中（1–3 天）**，其中搬家與寫測試半天，
  **對帳找出 1~2% 誤差來源是主要未知數**（需要 PO 的原始素材）
- **嚴重度**：**必修**（不是程式會壞，是「PO 依據一個標註不可信的數字做財務規劃」）

---

## 該修（維護成本已經在咬人）

### F4｜`report.py` 76% 不可達，而且退役後仍在被修改

- **位置**：`poc/kb-mcp/report.py`（2870 行，不可達約 2190 行，
  清單見 §3.1）、`poc/kb-mcp/report_server.py`（912 行，可刪）、
  `poc/kb-mcp/tests/test_report_server.py`（58KB／63 測試，可刪）
- **為什麼是問題**：見 §3.1 的完整證據。一句話版本：
  **近 90 天 churn 第一名的檔案（24 commits），退役後 6 次 commit 有 4 次
  改的是沒有人看得到的 HTML**（`95a5059`、`c712c8b`、`66b8f2c`、`0fffc7f`）。
  這是本次審查裡唯一能用 git 紀錄證明「正在持續付出成本」的項目。
- **修法**：見 §3.1「切法草案」。順序建議：
  1. 先刪 `report_server.py` + `test_report_server.py`（獨立、零依賴，半天）
  2. 再依可達性清單刪 `report.py` 的 41 個渲染函式 + CSS 常數（半天）
  3. 最後精簡 `test_report.py`（95 個測試，大頭在這）
  4. **刪 CSS 常數前**先補一個測試釘住 `_verdict_banner_html` 產出的
     class 名稱與 `web/src/styles/tokens.css` 一致（見 F6）
- **工作量**：**大（一週以上）**，但步驟 1+2 就能拿到 80% 的收益，
  只要 1 天。步驟 3 可以分批做。
- **嚴重度**：**該修**

### F5｜`sys.path.insert` 樣板複製 12 份

- **位置**：`app/deps.py:42-44`、`app/us_stock_deps.py:32-34`、
  `app/routers/mcp.py:37-39`、`screen.py:49-53`、`holdings.py:66-71`、
  `market_scan.py:80-84`、`actions.py:84-89`、`dashboard.py:83-87`、
  `holdings_import.py:85-89`、`stock_detail.py:78-82`、
  `app/tests/test_smoke.py:73`、`app/tests/test_quick_input.py:44`
- **為什麼是問題**：每新增一支 router 都要再抄一次，漏抄的失敗形式是
  `ModuleNotFoundError`（會炸，所以不致命）。但它讓「`poc/` 在哪裡」這個
  事實散落在 12 個地方——F1 的搬家評估之所以貴，一半是因為這個。
  作者在每個檔案都寫了「獨立做一次，避免對 import 順序產生隱性依賴」的
  註解，說明這是**有意識的取捨**，不是疏忽——但取捨的另一邊（一個
  `app/_kbpath.py` 只要被 `app/__init__.py` import 一次就夠，同樣沒有
  順序依賴）沒有被評估。
- **修法**：新增 `app/_kb_path.py`（約 12 行），把 `sys.path.insert` 放進去，
  在 `app/__init__.py` 第一行 `from app import _kb_path  # noqa`。
  其餘 11 處刪掉三行、保留 `import kb_store` 等。`app/tests/*` 因為是
  `python3 -m app.tests.…` 執行，`app/__init__.py` 一定會先跑，也能省掉。
- **工作量**：**小（半天內）**
- **嚴重度**：**該修**

### F6｜`app/` 依賴 `report.py` 的 8 個私有函式，其中一個讓 JSON API 回傳 HTML

- **位置**：
  - 私有函式 reach-in：`app/routers/stock_detail.py:144,158,160,168,184,189`、
    `holdings.py:156,194`、`holdings_import.py:165,168`
    （程式碼裡有 `# noqa: SLF001` 註記，作者知道這是 reach-in）
  - HTML 穿層：`app/routers/stock_detail.py:160` →
    `poc/kb-mcp/report.py:1253-1302`（`_verdict_banner_html` 回傳
    `<div class="verdict verdict--%s">…`）→ API 欄位 `verdict_html` →
    `web/src/pages/StockDetail.jsx:117-121`
    （`dangerouslySetInnerHTML`）
  - CSS 雙份：`poc/kb-mcp/report.py:268-274` 與
    `web/src/styles/tokens.css:124-130` 逐字相同
- **為什麼是問題**：
  1. **私有介面被當公開介面用**：`report.py` 裡任何 `_` 開頭函式的簽章改動，
     都會直接打到正式 API。這讓 F4 的清理必須小心——好消息是可達性分析
     已經把清單列全了（§3.1）。
  2. **JSON API 回傳 HTML 片段**：`verdict_html` 是後端渲染好的 DOM，
     前端只能整塊注入。前端無法改樣式、無法本地化、無法在行動版換版型，
     而且在 React 裡走 `dangerouslySetInnerHTML`。
  3. **樣式表被維護兩份**：量測結果 —— `web/src/styles/tokens.css` 的
     **69 個選擇器中有 66 個**在 `report.py` 的 CSS 常數裡也有一份
     （`.card`、`.pill`、`.stock-row`、`.finding`、`.verdict*`…）。
     96% 重複，一份寫在 Python 字串裡、一份寫在 `.css` 檔。
     其中 `.verdict*` 那 7 條是**唯一真正有生命的**——因為只有它經由
     `verdict_html` 跨層。刪掉 `report.CSS` 時如果沒注意到這一點，
     正式頁面的判定橫幅會靜默掉樣式，而且 CLAUDE.md 2026-08-19 的教訓
     （斷言會誤命中內嵌 CSS）意味著現有測試抓不到。
- **修法**（三步，可分開做）：
  1. **立刻（20 分鐘）**：加一個測試，斷言
     `report._verdict_banner_html()` 產出的 class 名稱集合 ⊆
     `web/src/styles/tokens.css` 裡定義的選擇器集合。這一條是 F4 動工前的
     安全網。
  2. **F4 順手做**：把 §3.1 列出的 11 個被 `app/` 用到的私有函式改成公開名
     （去掉底線），移進 `report_data.py`。reach-in 問題自動消失。
  3. **之後（可選）**：把 `_verdict_banner_html` 改成回傳
     `{"level": "alert", "title": …, "detail": …}`，由
     `StockDetail.jsx` 自己組 DOM。這樣 `report.py` 的 CSS 常數可以
     整段刪掉，`tokens.css` 成為唯一樣式來源。
- **工作量**：**小（步驟 1+2，半天）／中（含步驟 3，1–3 天）**
- **嚴重度**：**該修**

### F7｜`kb_store.py` 單一 class 承載 13 個領域

- **位置**：`poc/kb-mcp/kb_store.py`（2121 行；`SCHEMA` 常數 19-295＝277 行、
  `_MIGRATIONS` 301-349、`KBStore` class 366-2129＝79 方法／1529 行）
  領域分佈表見 §3.2
- **為什麼是問題**：近 90 天 churn 第二名（22 commits）。目前**還沒有真的痛**
  ——方法名有規律、`tests/test_kb.py` 78KB 覆蓋厚實。但兩個訊號說明它會痛：
  1. 資產領域從 2026-08-21 新增到現在已經長到 **512 行／19 個方法（佔 33%）**，
     而它跟台股領域**零重疊**（呼叫端只有 `app/routers/assets.py` 與
     `seed_assets_once.py`）。
  2. `save_philosophy`/`get_philosophy`/`list_philosophy`/`_module_path`
     （`kb_store.py:1510-1546`）**根本不碰 SQLite**，是純檔案 IO，
     掛在 SQLite store 上是歷史包袱。
- **修法**：見 §3.2 的 Mixin 草案。切一刀就好（資產），呼叫端零改動。
- **工作量**：**小（半天，Mixin）／中（1–3 天，含 SCHEMA 與測試一起拆）**
- **嚴重度**：**該修**（但可排在 F4 之後；現在不動也不會出事）

### F8｜`server.py` 62% 是 JSON schema 宣告

- **位置**：`poc/kb-mcp/server.py:34-861`（`TOOLS`，828 行／47 個工具）、
  `server.py:893-1207`（`call_tool`，315 行／47 個 `if` 分支）
- **為什麼是問題**：churn 第三名（13 commits）。每次新增一個 MCP 工具要
  同時改三個地方（`TOOLS` schema、`call_tool` 分支、
  `server_readonly.py` 白名單），而 828 行的 list literal 讓「找到要改的
  那一段」本身就很慢。它不會壞，只是每次都慢。
- **修法**：見 §3.3。只做「schema 外移到 `mcp_tool_schemas.py`」即可，
  `server.py` 保留 `from mcp_tool_schemas import TOOLS` re-export，
  `server_readonly.py:41` 與 `mcp_http_gateway.py` 都不用改。
  `call_tool` 的 47 個分支**建議不動**。
- **工作量**：**小（半天內）**
- **嚴重度**：**該修**

### F9｜台美股 MCP transport 66 行近乎逐行重複，HTTP 樣板 4 份

- **位置**：
  - `poc/kb-mcp/server.py:1270-1335` vs
    `poc/kb-mcp/us_stock_mcp_server.py:285-351`（`diff -u` 實測：
    66 行中只有 serverInfo 名稱、log 文案、一處排版共 6 行不同）
  - `finmind_client.py:19-29` vs `us_stock_price_client.py:48-58`
    （`_read_token`，11 行中 2 行不同）
  - `_fetch` HTTP 信封 4 份：`finmind_client.py:31-54`、
    `twse_price_client.py:171-192`、`tpex_client.py:65-96`、
    `us_stock_price_client.py:60-74`
- **為什麼是問題**：MCP 協定版本協商（`SUPPORTED_PROTOCOL_VERSIONS`）
  是**安全與相容性相關**的邏輯，現在有兩份。協定升版時改一份漏一份，
  失敗形式是「美股連接器在某些 client 上連不上」——難查。
  HTTP 樣板的重複則是純浪費，但錯誤訊息格式已經飄了
  （tpex 有 cache 分支、其他沒有）。
- **修法**：見 §4.2 的三個抽取項（`fetch_json`／`read_token`／
  `StdioMCPServerBase`）。**只抽訊框與 IO，不抽任何業務邏輯或資料**——
  `TOOLS`、`call_tool`、store 全部維持各自獨立，不違反 FR-015/016。
  `default_data_dir()` 的 6 份重複**建議保留**（理由見 §4.2 末段）。
- **工作量**：**中（1–3 天）**
- **嚴重度**：**該修**

### F10｜`yfinance`／`pandas`／`numpy` 沒有任何依賴宣告；兩套直譯器跑同一份 code

- **位置**：`poc/kb-mcp/us_stock_price_client.py:178`（`import yfinance as yf`，
  函式內延遲匯入）；`app/requirements.txt`（只有 `fastapi==0.128.8`、
  `uvicorn==0.39.0`）；repo 根目錄**無** `requirements.txt`／`pyproject.toml`／
  `setup.py`（已查證）
- **為什麼是問題**：
  1. `.venv` 裡實際裝了 `yfinance 1.2.0`、`pandas 2.3.3`、`numpy 2.0.2`，
     但**沒有任何檔案記錄它們為什麼在那裡**。重建 venv → 美股報價的
     fallback 路徑（`get_quote_fallback`）靜默失效，而且因為是延遲 import，
     只有在 FMP 主路徑也失敗時才會爆，**最難查的那種**。
  2. **兩套直譯器**：`com.alphavibe.marketscan`／`com.alphavibe.moduled`
     用 `/usr/bin/python3`（系統 3.9.6，看不到 `.venv` 的套件）；
     `com.alphavibe.usstockscan`／`com.alphavibe.reportserver` 用
     `.venv/bin/*`。所以 `poc/` 底下的模組**不能自由使用第三方套件**——
     一旦 `market_scan.py` 路徑上的任何模組加了 `import yfinance`，
     02:00 的台股排程會直接掛掉。這個約束今天只存在於人的腦袋裡。
  3. CLAUDE.md 2026-09-03 的 macOS bytecode 快取坑對 `/usr/bin/python3`
     特別容易踩到。
- **修法**：
  1. 建 `requirements.txt`（repo 根），列 fastapi/uvicorn/yfinance 與
     `--only-binary` 註記；`app/requirements.txt` 保留或改成指向它。
  2. 在 `poc/kb-mcp/README.md`（或 CLAUDE.md）明文寫下
     「`market_scan.py` / `module_d_scheduler.py` 及其 import 鏈上的模組
     只能用標準庫，因為它們跑在系統 python」。
  3. 更省事的替代：把那兩支 plist 也改成 `.venv/bin/python3`，
     統一直譯器，約束就消失了。**建議走這條。**（注意：改完要確認
     `.venv` 的 python 版本與系統一致，且 launchd 重載。）
- **工作量**：**小（半天內）**
- **嚴重度**：**該修**

### F11｜`app/tests/` 不是測試套件，標準 discovery 一個都跑不到

- **位置**：`app/tests/test_smoke.py`（647 行）、
  `app/tests/test_quick_input.py`（280 行）
- **為什麼是問題**：兩個檔案的 `def test_` 數量是 **0**。它們是手寫腳本
  （`def main() -> int:` + `if __name__ == "__main__":`，
  `test_smoke.py:114,646`），靠 `print` + 自己數 PASS/FAIL，必須用
  `python3 -m app.tests.test_smoke` 執行。`python3 -m unittest discover`
  **一個都收不到**——名字叫 `test_*.py` 更加深誤導。
  對照之下 `poc/kb-mcp/tests/` 是標準 unittest（24 檔）。所以 repo 裡有
  兩套不相容的測試慣例，而正式對外服務那一層用的是比較弱的那套。
  覆蓋面也薄：`assets.py` 的 20 個端點，smoke 只碰到 3 個 GET
  （`test_smoke.py:149-151`），12 個 POST 端點與全部
  `_simulate_asset_scenario`（F3）沒有任何覆蓋。
- **修法**：
  1. 把 `test_smoke.py` 的檢查項改寫成 `unittest.TestCase`，
     用 `setUpModule`/`tearDownModule` 管 server 子行程（現有的
     `_wait_for_server`／`_guard_data_dir` 邏輯可直接沿用，不用重寫）。
     這樣 `python3 -m unittest discover` 能一次跑完 app/ 與 poc/。
  2. 補 `assets.py` 的寫入端點與 `us_stocks.py` 的 POST/DELETE 覆蓋。
  3. 若不想大動，**至少**把檔名改成 `smoke_check.py`／`quick_input_check.py`，
     消除「這裡有測試」的錯覺。（10 分鐘）
- **工作量**：**中（1–3 天）**（步驟 3 單獨做是小）
- **嚴重度**：**該修**

---

## 可不修（知道就好）

### F12｜3 組循環依賴，全部已被延遲 import 妥善處理

- **位置**：`fundamentals_client.py:33-44` + `:57,121,163`；
  `review_engine.py:777-781`；`benchmark.py:13-15,31-34`
- **結論**：**不建議動。** 三個環都有完整註解說明形狀與打斷理由，
  `benchmark.py` 甚至選了最乾淨的做法（根本不 import，改由呼叫端傳參）。
  要真正消除需要新增第四個「常數模組」，改動面大於收益。
  **這是寫得好的地方，記錄下來避免未來有人「順手優化」把它弄壞。**
- **工作量**：—
- **嚴重度**：**可不修**

### F13｜`mcp_http_gateway.py` 內部約 73 行死碼

- **位置**：`poc/kb-mcp/mcp_http_gateway.py:209-282`（`MCPHandler` class 與
  `main()`，獨立埠外殼；對應 plist 已停用為
  `com.alphavibe.mcphttpgateway.plist.disabled-20260822`）
- **為什麼知道就好**：模組本身是活的（見 §2），這 73 行是裡面的獨立外殼。
  但 `tests/test_mcp_http_gateway.py` 的 `MCPHTTPGatewayTest` 那組
  （21 個測試的一部分）就是靠這個 class 起 server 來測純函式的。
  刪了要改測試，換來 73 行，不划算。
- **工作量**：小，但不建議
- **嚴重度**：**可不修**

### F14｜`app/` 的 REST 慣例與錯誤格式不一致

- **位置**：
  - 無 router 使用 `APIRouter(prefix=…)` 或 `tags=`（10 個 router 全部是
    `APIRouter()`，路徑逐條手寫；`/api/assets/` 重複 12 次）
  - `assets.py:485,537` 用 `POST …/{id}/delete`，
    `us_stocks.py:247` 用 `DELETE …/{id}` —— 同一個 app 兩套慣例
  - 錯誤訊息語言：台股 router 中文 + ⚠️（`actions.py:157`），
    美股 router 英文（`us_stocks.py:256` `"watch condition not found"`）
  - 錯誤形狀：`HTTPException`（16 處）vs HTTP 200 + body `{"error": …}`
    （`screen.py:81`）vs 部分成功 `errors: [...]`（`us_stocks.py:302-305`）
  - 4 個 router（`dashboard`／`holdings`／`market_scan`／`stock_detail`）
    完全沒有錯誤處理——底層丟例外就是 500
- **為什麼知道就好**：這是單人專案的個人主控台，前端也是自己寫的，
  不一致的成本目前由同一個人吸收。`screen.py` 的 200+error 甚至是
  刻意的並有 docstring 說明。**真正值得順手做的只有兩件**：
  加 `prefix=`／`tags=`（讓 `/docs` 自動分組，20 分鐘），
  以及統一錯誤訊息語言（半小時）。
- **工作量**：**小（半天內）**
- **嚴重度**：**可不修**

### F15｜正式 plist 的註解宣稱需要 `/api/gateway/*`，但那個 router 從未存在於本分支

- **位置**：`~/Library/LaunchAgents/com.alphavibe.reportserver.plist`
  的 `PATH` 註解（原文：「`/api/gateway/chat`、`/api/gateway/task` 這兩個
  新端點需要呼叫 claude，沒有這個會 FileNotFoundError」）
- **事實查證**：
  - `git log function/alphavibe -- app/routers/gateway_monitor.py` → **空**。
    該 router 只存在於未合併的 `function/stnd-gateway-web`。
  - 正式服務啟動於 2026-09-10，當時 checkout 的是 `function/alphavibe`
    → **`/api/gateway/*` 端點在正式服務上不存在**。
  - 但 `~/.claude/projects/…/memory/MEMORY.md` 的
    `telegram-gateway-bg-task-bugs` 條目寫「Telegram 側 + STND 網頁『管家』
    兩批都完成…已 commit(function/stnd-gateway-web) 並部署上線正式服務」。
    **這句話與現況不符**：Telegram bot 本身確實在跑
    （`com.stnd.telegramgateway`，獨立 repo `AI/telegram_gateway`），
    但 STND 網頁的「管家」分頁**沒有上線**。
- **為什麼知道就好**：多餘的 `PATH` 項目無副作用。但這條記憶會誤導未來的
  session（以為管家分頁已上線而不去合併分支）。
- **修法**：更新 `MEMORY.md` 那條記憶，寫清楚「Telegram 側已上線；
  STND 網頁管家分頁在 `function/stnd-gateway-web`，**未合併、未上線**」。
  plist 註解可留可改。
- **工作量**：**小（10 分鐘）**
- **嚴重度**：**可不修**（但建議順手做，成本近乎零）

---

## 明確寫得好、不用花錢的部分

逐項說明檢查方式，避免「沒發現＝沒檢查」：

1. **依賴方向乾淨，沒有反向依賴。** 檢查方式：對 `poc/kb-mcp/**/*.py`
   grep `from app\.` / `import app\b` / `app/routers` / `app.main` / `app.deps`，
   命中 2 處（`us_stock_mcp_server.py:24,36`）**都是 docstring 說明文字**。
   另查 `poc/` 對 `web/dist` / `web/src` 的引用 → 0。**單向依賴成立。**
2. **`app/` 完全沒有裸 SQL。** 檢查方式：對 `app/routers/*.py` 與 `app/*.py`
   grep `execute(` / `SELECT ` / `INSERT ` / `UPDATE ` / `DELETE ` / `.conn` /
   `sqlite3` → 命中 6 處，逐一開檔確認**全部是註解或 docstring**。
   store 層邊界守得很乾淨。
3. **資料目錄防呆設計紮實。** `app/deps.py:52-87` 與
   `app/us_stock_deps.py:43-67` 的雙重旗標（必須明設 `ALPHAVIBE_DATA_DIR`，
   指向正式庫還要 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`）是 2026-08-22
   事故的正確修法。刻意寫兩份而不共用，讓兩個 store 各自把關，是對的取捨。
4. **`us_stock_store.py` 是比 `kb_store.py` 好的示範。** 524 行／40 方法，
   領域內聚，`__init__`（`:129-148`）明確拒絕任何副作用並註解說明
   （「刻意不呼叫任何種子資料寫入方法」），`check_same_thread=False`
   也帶著為什麼的註解。新寫的東西有把舊教訓吃進去。
5. **`server_readonly.py` 的唯讀白名單目前零 drift，且有測試釘住。**
   實測：`server.TOOLS` 47 個工具，白名單 28 個，
   **白名單裡沒有任何已不存在的工具**；未被白名單收錄的 3 個 read-ish 工具
   （`parse_and_save_*`）名字有 `save`，本來就該排除。
   `tests/test_pnl.py:249` 斷言 `len(READONLY_TOOLS) == 28`、
   `tests/test_traceability.py:1145-1147` 釘住
   `save_exit_threshold` 不得入列。硬編碼數字雖然брittle，但 drift 會**大聲**失敗。
6. **幾乎沒有 TODO/FIXME/HACK 殘留。** 檢查方式：對 `app/` + `poc/kb-mcp/`
   （排除 tests）grep `TODO|FIXME|XXX|HACK|暫時|待補|尚未實作|stub` →
   10 處命中，逐一看過**全部是正常的說明性中文**（「暫時封鎖的風險」
   指的是被 API 封鎖，不是暫時性程式碼）。唯一的真 stub 是
   `us_stock_mcp_server.py:281` 的 `raise ValueError("未知或尚未實作的工具")`，
   那是正確的預設分支。
7. **較新的模組都是小而純的函式模組。** `pnl.py`(185)、`price_position.py`(154)、
   `exit_signals.py`(295)、`holdings_sync.py`(154)、`benchmark.py`(168)、
   `frameworks.py`(91)、`stock_alias_resolver.py`(78) —— 全部無 class、
   無全域狀態、單一職責。`review_engine.py` 雖然 1149 行但結構同樣乾淨
   （見 §3.4）。**巨型檔案的問題只集中在 4 個舊檔，不是全面性的。**
8. **退役模組的測試仍然健康。** 實跑 84 個測試 1.838 秒全過，
   且 FinMind 呼叫都有 mock（`test_report_server.py:498,542,618`），
   不會重蹈 2026-07-28 打光額度的覆轍。刪它們是為了減少認知負擔，
   不是因為它們壞了。

---

## 建議排程（給 PO 直接當排期用）

| 順序 | 做什麼 | 工作量 | 為什麼是這個順序 |
|---|---|---|---|
| 1 | F1 認證 fail-closed + 啟動斷言 | 半天 | 最高風險、最便宜 |
| 2 | F2 方案 1（`/api/version`） | 半天 | 之後每次部署都受益 |
| 3 | F15 修正 MEMORY.md 那條記憶 | 10 分鐘 | 順手 |
| 4 | F6 步驟 1（verdict class 一致性測試） | 20 分鐘 | F4 的安全網，必須先做 |
| 5 | F4 步驟 1+2（刪 report_server.py + report.py 死碼） | 1 天 | 收益最大的一刀 |
| 6 | F5（`app/_kb_path.py`）、F8（schema 外移）、F10（統一直譯器） | 各半天 | 三個獨立的小勝 |
| 7 | F3（試算搬家 + 補測試） | 1–3 天 | 需要 PO 提供原始素材對帳 |
| 8 | F4 步驟 3（精簡 test_report.py） | 2–3 天 | 可分批，隨時可停 |
| 9 | F7（kb_store 資產 Mixin）、F9（共用工具層）、F11（測試框架統一） | 各 1–3 天 | 不急，等痛了再做 |
| — | F12、F13、F14 | — | 建議不做 |

---

## 本次審查用過的檢查角度（供覆核覆蓋度）

1. 檔案清單與行數統計（`find` + `wc -l`）
2. **AST 靜態分析**：抽取 `app/` 對 `poc/` 模組的**實際屬性存取**
   （排除 docstring/註解誤命中），據此做 `report.py` 的可達性分析
3. 模組層 import 圖建構（逐檔 grep 頂層 `import`/`from`，過濾標準庫）
4. **函式內延遲 import 搜尋**（找循環依賴的打斷點）
5. launchd plist 全量 dump + `launchctl list` 執行中行程比對 + `ps` 驗證
6. `crontab -l` / `.mcp.json` / `cline_mcp_settings.json` /
   `claude_desktop_config.json` 交叉查外部消費端
7. **`git log --since=90d` churn 排名**（找真正在痛的檔案）
8. **`git show --unified=0` 逐 commit 比對**：把退役後的改動落點對到
   可達性清單上（F4 的關鍵證據）
9. `git reflog` + `ps -o lstart` 比對正式行程啟動時間與分支切換時間（F2）
10. **`diff -u` 逐行比對**台美股對應區段（F9 的量化）
11. **CSS 選擇器集合運算**（Python 正則抽取 `report.CSS` 與 `tokens.css`
    的選擇器，做交集，F6 的量化）
12. 實跑 `python3 -m unittest`（退役模組測試狀態）
13. 實打 `curl` 本機 8080（服務存活與認證狀態）
14. 實際 import `server` / `server_readonly` 做白名單 drift 運算
15. `.venv/site-packages` 列表 vs 依賴宣告檔比對（F10）
16. 反向角度：`poc/` → `app/`、`poc/` → `web/` 的反向依賴掃描
17. 反向角度：`TODO|FIXME|HACK|暫時|stub` 全掃（找作者自承的未完成處）
18. 反向角度：`app/` 內 SQL 關鍵字全掃（找繞過 store 層的地方）
19. 方法級領域分群（AST 取 `KBStore` 全方法的行號區間，按資料表歸類）
20. **模組名遮蔽分析**：用 `importlib.machinery.FileFinder` 對 `sys.path` 上
    每個路徑（排除 `poc/kb-mcp` 本身）逐一 find_spec 那 32 個被注入的模組名
    → 零衝突
21. 文件漂移比對（`docs/architecture.md` vs 實際 router 清單與部署事實）
    → 大致相符；唯一小落差是 `:21` 的投資分頁 router 清單漏列 `dashboard.py`
    （CLAUDE.md 有列），不值得單獨開 finding
22. `git status --porcelain app/ poc/ web/src` → 乾淨，
    本報告反映的是 commit `5a72ac0` 的狀態，不含未提交異動

**未驗證／已知盲點**（照實列出）：
- `web/dist/` 是 gitignore 的建置產物，無法確認它與 `web/src/` 目前是否同步
  （F2 只針對 Python 端得出結論；前端靜態檔走 `FileResponse` 即時讀磁碟，
  不受 process 重啟影響）。
- 沒有實際執行 `poc/kb-mcp/tests/` 的完整套件（test_market_scan /
  test_screener / test_fundamentals_client 可能觸發 FinMind 網路呼叫，
  依 CLAUDE.md 2026-07-28 教訓刻意避開）。因此「所有測試目前全綠」
  **未驗證**，本報告只實測了 test_report_server + test_mcp_http_gateway。
- `_simulate_asset_scenario` 的 1~2% 誤差來源未追查（需要 PO 的原始素材，
  超出本次審查範圍）。
