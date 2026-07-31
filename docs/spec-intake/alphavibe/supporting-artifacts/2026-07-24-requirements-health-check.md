# 需求健檢報告（2026-07-24）

> 目的：PO 於 2026-07-24 表示「實際用下來發現需要的跟當初寫的不一樣了」，
> 要求對 product-spec.md 做一次全文健檢，並比對實際使用行為與原始設計
> 假設的落差，作為「重新檢視需求／使用範圍／操作流程」的討論起點。
> 本檔案為健檢原始資料，兩個獨立 Explore agent 分別產出，未經篩選或
> 加入建議——判斷與取捨留給 PO。

---

## 一、FR 層級健檢（product-spec.md §5，FR-001~043 全 43 條逐條核對）

統計：完全對應 15／部分對應 12／完全沒做 16／文件未跟上（程式碼超前）5

驗證方式：完整讀取 product-spec.md §5、server.py（672行）、kb_store.py
（602行）、report.py／report_server.py、screener.py／market_scan.py／
frameworks.py／holdings_parser.py／finmind_client.py／tpex_client.py、
全部 6 個 tests/*.py（175/175 測試現場重跑通過），並對每條可疑處另外
grep 關鍵字確認。

### 完全對應（15 條）
FR-001, FR-003, FR-013, FR-016, FR-017, FR-018, FR-019, FR-020, FR-021,
FR-023, FR-026, FR-027, FR-029, FR-041, FR-042

### 部分對應（12 條，摘要）
- **FR-004** 收盤後報告產出：無 report generation 工具，流程全發生在對話層，無持久化紀錄
- **FR-005** watchlist：無專屬表，用 stances 頂替，缺 memo/added_date，無刪除工具
- **FR-007** 來源連結：source_ref 只是純文字 escape，不是可點擊連結
- **FR-008** FinMind 完整，**Alpha Vantage 完全查無**（美股數據整合等於未做）
- **FR-014** .md 檔擴展有做；「啟動時拼接進 system prompt」完全沒做（已知落差）；附帶發現：實際哲學檔案命名與 product-spec.md 表格描述已不符
- **FR-015** AI 對話式輸入：寫入機制沒問題，但「第四種輸入方式並列於儀表板」這個 UI 層級功能完全不存在——實際上四種輸入全部退化成同一件事：直接在 Claude Code 對話裡講/貼/傳圖
- **FR-025** 資訊流時間軸：只有寫死 20 筆的平面清單，無按標的分組、無時間軸 UI
- **FR-028** 快照 diff：get_snapshots 能拿歷次資料，但無 diff 運算邏輯，report.py 自己承認「待 1c 儀表板」
- **FR-030** 篩選框架引擎：無真正版本化機制；5 個哲學框架檔案中 frameworks.py 只註冊了 1 個
- **FR-038** 情境機率評估：完全靠自由文字頂替，無結構化子欄位
- **FR-039** 信心分級：完全依賴自由文字，無欄位/邏輯驗證信心等級對應比例
- **FR-043** 減碼三分類＋錨點：完全無專屬欄位/enum，grep「錨點」全 repo 零命中

### 完全沒做（16 條）
- **非預期落差（優先度較高，共 11 條）**：FR-002（定錨email regex解析）、FR-006（報告兩區呈現）、FR-009（URL爬取，推測由對話層原生處理）、FR-010（Vision圖片解析，推測由對話層原生處理）、FR-011（觸價提醒）、FR-012（LINE前置清洗層）、FR-024（總覽名單頁，report.py明講刻意不做）、FR-040（加碼Gate四問，連權宜設計都沒有）
- **文件已標註後行/Deferred，屬預期內（8 條）**：FR-022、FR-031、FR-032~037

### 文件未跟上（程式碼已做但 spec 沒提到，5 項）
1. 興櫃股估值粗估（get_emerging_stock_valuation + tpex_client.py，含完整測試）
2. 股票名稱→代碼查證快取（save/get_stock_alias + stock_aliases 表）
3. 股價／產業別快取子系統（refresh_holdings_prices + 兩張表）
4. **第二層全市場批次篩選引擎**（run_market_scan + market_scan.py 264行 + 網頁UI + 每日02:00排程，148個測試，**PO每天在用**）——FR-030 僅一句話帶過，完全沒描述
5. 三大法人買賣超查詢（get_institutional_trading）

---

## 二、實際使用行為 vs 原始設計假設

查證方式：讀 product-spec.md §2-4、scope-decision.md Goal 段落，比對
`list_stances`／`get_holdings`／`get_stock_theme` 等 MCP 工具與直接
sqlite3 唯讀查詢 `poc/data/alphavibe.db` 的實際資料（約16道查詢）。

### 對照表

| # | 設計怎麼寫的 | 實際觀察到什麼 | 落差程度 |
|---|---|---|---|
| 1 | 核心迴圈＝資訊討論→浮現目標股→估值討論→進出決策 | 33筆立場分4個離散批次：07-16(AI主動篩選研究)、07-19(21檔既有持股一次健檢)、07-20、07-22(market_scan批次候選)。主要模式是「批次審查既有部位」＋「AI自主篩選」，不是逐檔討論 | 部分偏離 |
| 2 | 三大貼入來源：LINE群組/一對一、定錨email、股癌FB | comments 84筆：line 64(76%)、own_trade 12、conversation 7、youtube 1；**定錨0筆、股癌0筆**。且64筆「line」**100%**是轉貼第三方「老芋頭」的交易執行紀錄，不是群組行情討論 | **完全不同模式** |
| 3 | FR-021估值討論結論寫入 entry_condition／valuation_metric，供觸價提醒使用 | entry_condition **0/33**留空；time_horizon **0/33**留空；valuation_metric 23/33有填但多為PER/PBR描述，非目標價區間 | **完全不同模式** |
| 4 | 追溯性快照包（snapshots/snapshot_sources）凍結分析結論供diff，FR-038/043設計要沿用此地基 | snapshots表 **0筆**、snapshot_sources表 **0筆**，save_snapshot從未被實際呼叫過 | **完全不同模式** |
| 5 | 持股快照FR-029：截圖Vision解析入庫{code,shares,avg_cost,snapshot_date} | holdings 22筆，avg_cost **22筆中僅1筆有值**；來源是券商庫存表文字轉錄，非截圖Vision解析 | 部分偏離 |
| 6 | Secondary User（受信任朋友）小規模使用 | 全12張表schema無任何user_id/分享相關欄位或表 | 一致（預期內） |
| 7-11 | FR-038~043部位管理新概念語彙（信心分級5%/8%/10%、Gate四問、情境機率、主題標籤、減碼三分類） | 全部 **0/33** 精確語彙命中；stock_themes表**0筆**；僅有9/33(27%)出現PO自創的「信心高/中等」非正式標籤 | **完全不同模式** |
| 12 | 全市場條件篩選選股：**明確列為Deferred**，v1不做（Q-030），理由是需全市場數據管線 | market_scan_runs **7次執行**（含scheduled排程觸發）、market_scan_results累計**887筆**、最新一次已達1973檔（近全市場規模）；產出已直接寫入正式立場（3135凌航） | **完全不同模式，且與正式決策Q-030直接矛盾** |
| 13 | FR-022交易紀錄「後行階段」，結構化記錄進出場 | 無trades表；買賣執行紀錄以Layer3自由文字評論形式存在（own_trade 12筆＋line 64筆），需求已在發生但落地方式不同 | 部分偏離 |
| 14 | Scenario 2 AI對話式輸入：口述心得AI萃取歸檔 | conversation標籤7筆，內容與設計描述相符 | 一致 |

### 關鍵原始數字
- stances 33筆（28個標的）／snapshots **0**／holdings 22／stock_themes **0**／
  stock_industries 21／stock_aliases 44／market_scan_runs 7／
  market_scan_results 887／comments 84（line 64／own_trade 12／conversation 7／youtube 1／定錨0／股癌0）
- stances欄位使用率：source_ref 100%、risk_factor 94%、valuation_metric 70%、
  **entry_condition 0%、time_horizon 0%**
- 日期分布：07-16=8、07-19=21、07-20=2、07-22=2（4個活動日，非連續每日累積）

---

## 三、對 PO 而言最需要決策的發現（依重要性排序，非依原報告順序）

1. **Q-030（全市場篩選Deferred）與實況矛盾**：正式定案「v1不做」，但
   market_scan 已是排程執行、掃近2000檔的運作中系統，且產出已寫入正式
   立場。這不是「差不多但有落差」，是文件明寫Deferred但系統已經在跑。
2. **「老芋頭」第三方交易信號是目前最大宗的資料來源，但從未出現在
   product-spec的Actor或Scenario設計裡**。真實工作流可能高度圍繞
   「跟隨/驗證他人交易訊號」，跟原設計「自己從三來源討論出想法」性質不同。
3. **FR-021估值討論的核心產出（目標買賣價區間）從未被寫入過**，
   追溯性快照包（FR-026~030，FR-038/043要沿用的地基）也是0筆使用——
   這兩塊被寫進v1 In-Scope、且新系統設計奠基其上的機制，目前是空中樓閣。
4. **FR-038~043（剛完成、175/175測試綠的部位管理系統）新概念語彙採用率0%**——
   信心分級、Gate四問、情境機率評估，完成當天至今沒有一筆立場照此格式寫。
5. **FR-015的儀表板輸入UI從不存在**，實際輸入管道就是直接對話——
   與OQ-3（PO已回饋UI差、資料缺漏多）同一根因，建議合併討論。
6. **5項已建好且在用的功能完全沒寫進product-spec.md**（尤其market_scan
   批次篩選引擎，PO每天在用），代表文件已嚴重落後於實際開發進度。
7. 8條「完全沒做」但屬文件已標註後行/Deferred的項目，優先度低於上述。
