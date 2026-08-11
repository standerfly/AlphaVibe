# 「研究啟動包」功能設計討論 (SRC-013)

> 來源：2026-08-10 PO 與 Claude 討論（延續 SRC-012），提問「能不能系統化：
> 我說要研究2330，系統依文章架構蒐集資料並彙整成文章內容？」。本文件記錄
> 討論結論與 PO 已確認的決定（**要做**，逐步分階段建置）；FR 編號為候選
> 編號，接續 FR-059（模組G），**尚未走 scope-decision 正式流程**，不寫入
> product-spec.md 正式章節。

## 1. 核心判斷：checklist 裡兩種性質不同的內容，不能一起自動化

把 SRC-012 checklist 的七節拆開看，只有「財務體檢（六面向）」多數是可查
數字，其餘六節本質是判斷/推理，不是查詢：

| 節次 | 性質 | AlphaVibe現有/可擴充資料源 |
|---|---|---|
| 財務體檢（六面向） | 多數可查數字 | `get_fundamentals`／`get_revenue_yoy`／`get_institutional_trading`／`get_stock_price_history` 大部分覆蓋；法說會Q&A逐字稿、部分資產負債表細項無API |
| 業務理解（三句話） | 純判斷 | 無資料源，護城河評估是LLM推理 |
| 產業結構（五問） | 多數判斷 | TAM無API；只有營收趨勢等間接線索可查 |
| 預期差 | 完全判斷 | 無台股分析師共識預期的免費結構化API——這正是FR-051把「預期獲利能否持續上修」設計成`manual_notes`（人工填）的原因，已知蓋不到 |
| 破裂條件 | 判斷產出 | 本身是討論結論，非查詢對象 |
| 估值：情境敘事 | 判斷，吃財務數字當輸入 | 敘事本身是LLM綜合，非查詢 |
| 收斂四問 | 純判斷 | 同上 |

## 2. 決策：方向A（機械蒐集＋排版），排除方向B（全自動生成報告）

**方向B（全自動LLM生成完整報告）已評估並排除**，原因：

1. 查不到資料源的欄位（護城河/TAM/預期差/法說會內容）若強迫LLM生成文字
   填滿，等於用訓練時的舊知識腦補——尤其台股中小型股資訊量本來就少，
   幻覺風險高，且因為排版成正式報告「看起來權威」，比承認不知道更危險。
2. 違背文章本身「研究的目的是讓你知道哪些股票值得你有意見」的主張，也
   違背AlphaVibe自己已驗證的教訓：FR-021 `entry_condition`、FR-026
   `save_snapshot` 這類「自動/結構化產出的結論欄位」，實測0%~0筆使用——
   自動產出的東西不會被真的讀、真的質疑。

**採用方向A**：工具只做「機械蒐集＋依checklist骨架排版」，查不到資料源
的欄位**留白並明確標註「需要對話討論」**，不強行生成敘事文字去填。判斷
與敘事仍留在PO與Claude的對話裡完成，結論照舊寫回`save_stance`的
`reason`/`risk_factor`（不新增schema，沿用既有機制）。

這個分工對應既有的「引擎＝Claude聊天思考＋Cline粗活」原則：拉資料排版
是粗活、該自動化；下判斷是思考、留在對話。也與FR-051現有設計一致
（財報兌現度/利多出盡/預期上修本來就是`manual_notes`人工欄位）。

## 3. 候選 FR-060：研究啟動包（Research Brief）

- **輸入**：股票代碼
- **輸出**：依 SRC-012 checklist 骨架排版的文字/結構化資料，可查到的
  財務欄位自動填值＋資料來源與時間戳；查不到的六節（業務理解/產業結構/
  預期差/破裂條件/估值敘事/收斂四問）固定顯示「〔需要對話討論〕」佔位
- **不做**：不呼叫LLM生成任何判斷性敘事段落；不自動寫入Layer 2
  （由PO/Claude討論後另外呼叫`save_stance`）
- **定位差異**：與模組D（FR-051~055）不同——模組D是「已進候選/持股的
  標的」定期複核；研究啟動包是「還沒決定要不要研究」的標的，第一次
  建立立場前的資料整理起手式，兩者互補不重疊

## 4. 分階段建置計畫（逐步完成，每階段都有待PO裁決的開放問題）

### Stage 1（MVP）—— ✅ 已完成（2026-08-11）
新增唯讀MCP工具（暫名 `prepare_research_brief(code)`），純組裝現有工具
輸出：呼叫 `get_fundamentals`／`get_revenue_yoy`／`get_institutional_trading`／
`get_stock_price_history`／`get_stock_alias`（視現有工具實際涵蓋範圍
以查證為準），依checklist財務六面向骨架排版；其餘六節固定佔位文字。
**不呼叫LLM生成任何內容**，機械邏輯層級等同`review_engine.py`現有的
`_growth_deceleration`／`_downside_risk`。
- 驗收：`prepare_research_brief("2330")` 輸出的財務數字與個別工具直接
  查詢結果一致，六個留白欄位正確出現且標註清楚。

**Stage 1 完成紀錄（2026-08-11，實作＋獨立驗證）**：
- 新增 `poc/kb-mcp/research_brief.py`（`prepare_research_brief()`）＋
  `finmind_client.get_balance_sheet_summary()`（新函式，不動既有
  `get_equity_attributable_to_owners()`）＋兩個對應MCP工具
  `prepare_research_brief`／`get_balance_sheet`（server.py）
- **status三分法**（本Stage核心設計，SRC-013第2節原則的具體落地）：
  `ok`/`query_failed`（財務體檢五項有資料源小節，反映實際查詢結果）、
  `no_data_source`（毛利槓桿/現金流/法說會Q&A，AlphaVibe已知資料邊界）、
  `needs_discussion`（頂層六節，判斷性質非查詢）——三種狀態不互相混用
- FinMind `TaiwanStockBalanceSheet` 實際查證（對2330單次呼叫，未重複
  查詢消耗額度）：該API該期共101個type，選用
  `CashAndCashEquivalents`／`CurrentLiabilities`／`Liabilities`／
  `TotalAssets` 四項；`Equity`（權益總額）與既有函式用的
  `EquityAttributableToOwnersOfParent` 是不同科目，未混用
- 測試：改前605→改後623（新增18筆：`get_balance_sheet_summary` 4筆＋
  `prepare_research_brief` 14筆），主對話獨立重跑
  `python3 -m unittest discover -s poc/kb-mcp/tests` 確認 **623 tests OK**
  （非採信subagent自報，已重新執行驗證）
- 主對話另外獨立呼叫 `prepare_research_brief("2330")` 核對真實輸出：
  財務體檢五項有數字（例：資產負債表 debt_ratio≈0.315）、三項
  `no_data_source`、頂層六項 `needs_discussion`，結構與本文件設計一致
- **已知取捨，非本次引入的問題**：`revenue_quality.recent_trend`
  （FinMind多月序列）與`latest_yoy`（官方優先）在2330實測中月份口徑
  對不齊（例如多月序列近5個月yoy_growth為null、latest卻有值）——這是
  `fundamentals_client`/`finmind_client`既有的資料源口徑差異（`get_revenue_yoy`
  工具本來就是同樣組合方式），不是Stage 1新增程式碼造成，維持現況呈現
- 未加入 `server_readonly.py`（Cline唯讀白名單）——**已於Stage 3補上**
  （見下方）
- 完整改動：`finmind_client.py`／`server.py`／`README.md`／
  `tests/test_kb.py`／`tests/test_traceability.py`（既有 `test_tools_list_has_forty`
  因新增2個工具改名`test_tools_list_has_forty_two`）／新檔案
  `research_brief.py`／`tests/test_research_brief.py`

### Stage 2（交叉驗證擴充）—— ✅ 已完成（2026-08-11）
PO裁決：**列出候選清單交由PO判斷，系統不自動挑選**（不用FR-041主題
標籤——那是PO討論/建倉過程才手動標的，第一次研究新標的時通常還沒有
標籤；改用官方產業分類，任何股票都有，更適合當預設候選來源）。

`prepare_research_brief(code, peers=None)` 新增 `peers` 參數：
- 未指定：一次 `get_stock_info` 全量查詢（不逐檔查財務API，避免同產業
  幾十檔被查詢浪費額度），篩出同產業分類代碼放進 `peer_candidates`
  （`{"industry":..., "candidates":[...]}`），只列清單給PO自己挑
- 有指定（如`["2303"]`）：對每個peer重跑財務體檢五項，並排放進
  `peer_comparison`，不做任何評語/排名判斷
- 兩欄位互斥，一次呼叫只出現其中一個

**完成紀錄（實作＋獨立驗證）**：
- `research_brief.py` 新增 `_peer_candidates()`／`_peer_comparison()`，
  重用既有五個財務體檢內部函式，未複製貼上邏輯
- 主對話獨立重跑測試：改前623→改後 **637 tests OK**（+14）
- 主對話獨立實測兩種情境（真實FinMind呼叫）：
  - `prepare_research_brief("2330")`（無peers）→ `industry="半導體業"`，
    `candidates`共291筆（例：3219倚強股份、6594展匯科、3054立萬利）
  - `prepare_research_brief("2330", peers=["2303"])`（2303聯電，真實
    同產業標的）→ `peer_comparison["2303"]`五項皆`status:"ok"`且有實際
    數字（例：PER 18.5、debt_ratio≈0.333），與2330自身數字並排、無評語

### Stage 3（與對話流程掛勾）—— ✅ 已完成（2026-08-11）
PO裁決：**PO手動觸發**（不併入FR-057排程自動跑）。

- **觸發方式**：對話中PO說「研究一下XXXX」「幫我拉XXXX的資料」類語句，
  Claude據此呼叫`prepare_research_brief`（要指定對照組可直接一併講，如
  「研究2330，跟聯電比」）——沿用既有對話觸發模式，不發明新指令語法
- **呈現規則**（已寫入
  `supporting-artifacts/2026-08-10-framework-pre-buy-research-checklist-draft.md`
  「搭配prepare_research_brief使用」小節）：Claude不原樣貼JSON、不幫
  needs_discussion欄位自動生成答案、peer_candidates原樣列給PO自己挑、
  六個needs_discussion欄位換成checklist對應小節的引導提問、結論仍由
  PO確認後手動`save_stance`
- **Cline唯讀白名單**：`prepare_research_brief`／`get_balance_sheet`已
  加入`server_readonly.py`的`READONLY_TOOLS`，主對話獨立grep確認
- **已知待辦（非阻塞）**：`server_readonly.py`白名單與全域
  `~/.claude/agents/stock-researcher.md`列的23個工具清單目前不完全
  一致（該檔在repo範圍外，屬全域設定），已在`server_readonly.py`
  docstring註記；要不要同步兩份清單待PO決定，不在本次範圍內處理

**2026-08-11 實測發現的呈現規則缺口（已修正）**：PO開新對話直接說
「研究一下台達電」，產出的摘要把「毛利率30.77%→35.64%」跟PER/PBR等
今天查到的新數字排在同一段。追查發現這**不是幻覺**——這組毛利率數字
真實存在於2026-08-01的立場記錄（`get_stance`歷史），`source_ref`
明確記載「PO提供毛利率與預估本益比走勢截圖」，當時記錄得完全正確。
真正的問題是**新session把十天前、PO截圖提供的舊資料，跟當天
`prepare_research_brief`查到的新資料混排成同一段，沒有標示日期/來源
差異**，讀者無法分辨哪個是即時查詢、哪個是舊記錄。已補上呈現規則
第6條（見checklist草稿）：混用`get_stance`等其他工具的歷史資料時，
必須標日期與來源，不能跟`prepare_research_brief`當天查詢結果混排。
**已於同日補上工具描述層**（`server.py`的`prepare_research_brief`
description新增「呈現規則」段落，跟哲學文件草稿內容一致）——這是比
哲學文件更保險的防線，任何session只要載入這個工具就看得到，不需要
額外查philosophy模組。主對話獨立重跑測試確認637 tests仍全綠，描述
文字改動未影響任何邏輯。哲學文件草稿（尚未`save_philosophy`安裝）
留作對話時的完整版引導提問來源，兩者不衝突。

**2026-08-11 第二次實測（呈現規則修正後）與新發現的設計問題（已裁決）**：
PO再開一次新對話說「研究一下台達電」，這次結果大幅改善——主對話逐項
查證（`get_trade_ledger`／`get_holdings`／`prepare_research_brief`
重跑）確認：加權平均成本1,809.2元與摘要的「約1,810元」幾乎一致（8筆
交易明細真實存在，非幻覺）、月增率／PER／PBR／外資賣超皆與即時查詢
結果吻合、且結尾正確標註「這是資料整理，不是加碼/減碼建議」、跨期
比較有標日期（「比7/19的64.16倍已回落」）——呈現規則第6條看起來確實
被注意到了。**唯一沒解釋清楚的落差**：摘要的股價高低點（5月高點2,560／
7月低點1,495）跟主對話兩次獨立查詢`prepare_research_brief`得到的
period_high 2585／period_low 1425不一致，時間差排除後仍無法解釋，
記錄下來但未深究（非阻塞）。

但這次測試浮現一個先前沒想到的設計問題：**該標的已有持股與現行立場
記錄，六個`needs_discussion`引導提問（適合「白紙候選」的角度）這次
換成了監控導向的提問（Q3驗證/止跌訊號/技術位階），不是原本設計的
六問**。主對話原本提議「已持倉/有現行立場時，自動把六問換成監控導向
提問」，**PO裁決否決這個提案**：「已持股不代表只需要監控，還是可能
要持續檢視／重新完整研究——這是PO的判斷，系統不該自動幫PO決定用哪種
分析角度」。改採：**已寫入呈現規則「第0步」**（見checklist草稿）——
`get_holdings`或`get_stance`查到該標的已有持股/立場記錄時，Claude要
先問PO想要（a）完整研究checklist六問，還是（b）持倉監控式檢視，PO
選了才照該方向呈現；全新標的沒有這筆歷史記錄，直接走六問不用多問。
這是純對話流程規則，不影響`prepare_research_brief`工具本身的輸出
（工具永遠回傳固定六個`needs_discussion`欄位，怎麼呈現是對話層決定）。

**2026-08-11 第三次實測：第0步沒生效，根因是主對話自己的疏漏（已修正）**：
PO第三次開新對話說「研究一下台達電」，新session完全沒問就直接做了
持倉監控式分析。追查發現：**第0步規則當時只寫進了checklist哲學文件
草稿，沒有同步補進`prepare_research_brief`工具描述本身**——跟呈現
規則第6條當初「兩邊都補」不同，這次主對話漏掉了工具描述那一半，
新session自然看不到。這次資料品質本身很扎實（主對話獨立重跑
`check_general_review`／`get_fundamentals`核對：歷史中位數37.9、
6個月月營收498.97/597.80/586.92/589.62/656.03/670.73億，全部精準
對到小數點，非幻覺），純粹是「先問PO」這條規則的落地漏掉一半。
**已修正**：`server.py`的`prepare_research_brief`description補上
「第0步」完整說明（跟呈現規則第6條同一個description裡），主對話
獨立重跑測試確認637 tests仍全綠。**教訓**：往後每次修呈現規則，
哲學文件草稿與工具描述兩處要同步檢查都補到，不能只改一邊——工具
描述是唯一保證任何session都看得到的地方，哲學文件草稿目前還沒
`save_philosophy`安裝，能否被讀到完全不確定。

**2026-08-11 第四次驗證：軟性文字提醒改成硬性程式閘門（已實作，MCP連線
是否即時生效待PO實測確認）**：連續3次真實對話測試＋1次專門派agent做的
驗證測試，都證實「第0步」寫成工具description的軟性文字提醒不可靠——
模型會用「不確定就查、可逆低成本不用問」這類全域判斷原則把規則推理
繞過去，直接分析、不先問。文字說服此路不通，改採**硬性程式閘門**，
參考本repo既有的`save_stance`衝突偵測模式（偵測到衝突不寫入、回傳
衝突資訊，呼叫端須明確帶`overwrite=True`才能真的寫入）：

- `prepare_research_brief(code, store, analysis_mode=None, peers=None, ...)`
  新增必要參數`store`；函式一開始查`store.get_holdings()`／
  `store.get_latest_stance()`，若該標的已有持股或立場記錄、且
  `analysis_mode`不是`"full"`或`"monitoring"`，**直接短路回傳**
  `{"gate": "confirm_analysis_mode_required", ...}`，**不觸碰任何
  financial_check查詢**（額外好處：省下FinMind額度）。查無持股/立場
  的全新標的不受影響，照舊直接產出完整結果。
- `server.py`同步更新inputSchema（新增`analysis_mode`可選參數）與
  description（改寫成描述硬性閘門行為，不再是「建議先問」語氣）。
- 主對話獨立驗證（不採信subagent自報）：重跑測試637→**643 tests
  OK**（+6）；直接Python呼叫三種情境——2308不帶`analysis_mode`→
  正確被擋（只有gate欄位，無financial_check）；2308帶
  `analysis_mode="monitoring"`→正常出五項數字；2330（先查證真的無
  持股/立場）不帶`analysis_mode`→正常出結果，未被誤擋。三種情境皆
  與程式碼行為一致。

**發現一個環境限制，誠實記錄**：主對話用ToolSearch查詢當前session
連到的`prepare_research_brief`工具schema，發現**還是舊版**（description
沒有`analysis_mode`字樣，inputSchema也沒有這個參數）——這個session
與MCP server的連線是在改程式碼「之前」建立並快取住的，不會因為檔案
變更就自動更新。派一個診斷用subagent去查也連到同一個舊版（回報
`BLOCKED_STALE_TOOL`），代表**subagent共用主對話既有的MCP連線，不是
獨立建立新的**——這代表主對話沒辦法從這個環境裡自己把「新session會
不會真的被擋」驗到底，這是本次驗證方法論的實際邊界，不是裝作測過了。
好消息：程式碼正確性已用直接Python呼叫的方式獨立驗證過（見上），
可信；不確定的只剩「PO之後在手機/新開對話觸發時，是否真的拿到新版
工具」——如果PO那邊的連線跟這個session各自獨立（前三次真實測試看起來
就是如此，各自開新對話），應該會直接讀到新版程式碼，但main agent
無法百分之百保證，需要PO下次實際觸發時確認才算數（比照前三次抓到
真實問題的方式）。

### Stage 4（視Stage 1-3使用狀況再評估）
若留白欄位在實際使用中不夠好用，考慮要不要讓Claude在對話中直接讀取
啟動包輸出＋SRC-012 checklist哲學文件，主動逐項引導討論（技術上這已
是現有能力，啟動包只是先把機械蒐集的部分做好，減少每次手動個別呼叫
5-6個工具的麻煩）。是否要做、值不值得，待前三階段實際用過再看。

## 5. 已知蓋不到的資料（誠實列出，不假裝有）

- 法說會Q&A逐字稿：台股無官方結構化API，MOPS只有簡報PDF，需人工聽打
  貼入（沿用模組A既有資訊蒐集管道）
- TAM市場規模數字：無API
- 法人共識預期/預估修正方向：無免費結構化API（FR-051已確認此限制）

這些欄位在啟動包裡永遠會是留白佔位，不是Stage未完成，是**已知的資料
邊界**，Stage 4 也解決不了，需要外部資訊（PO自己讀到的分析報告、新聞）
補進來討論。

## 6. 未來方向：UI化／排程化觸發（討論記錄，尚未實作，PO確認要存檔）

2026-08-11 analysis_mode硬性閘門測試過程中浮現的討論：對話式觸發
（PO說「研究一下XXXX」→ Claude判斷要不要呼叫工具）這條路徑，這次已
證實「靠模型判斷要不要先問」不可靠（見上方Stage3的四次實測紀錄）。
延伸出一個問題：要不要把`prepare_research_brief`「固化」成正式功能，
改用UI按鈕或排程直接呼叫，繞開LLM判斷這個環節本身？

**結論：可行，而且直接解決這次的核心問題根源**——UI/排程觸發時，
「該用哪種分析角度」不再需要靠模型判斷：

- **UI觸發**：「問PO」直接變成畫面上兩個按鈕（「完整研究」／
  「持倉監控複核」），PO點哪個就是哪個，zero判斷空間，不可能被模型
  推理繞過去。比程式閘門更乾淨（閘門還是要靠對話裡的Claude主動去問、
  PO回答、Claude再帶參數呼叫；UI按鈕直接跳過整段對話往返）。
- **排程觸發**：排程當下沒有真人可問，本來就不該問——改成固定政策：
  已持股/有立場的標的，排程一律跑`analysis_mode="monitoring"`（這其實
  就是模組D FR-051~057既有排程在做的事，`prepare_research_brief`只是
  多一種資料補充）；`"full"`完整六問模式永遠只能PO主動觸發（UI按鈕
  或對話），不會自動跑。

**架構上有現成先例，不是新模式**：`/dashboard/stock/<code>`頁面的
「更新」按鈕已經是「UI直接呼叫Python函式（`review_engine.
refresh_price_and_valuation()`），不經過LLM判斷要不要查」的既有模式；
`research_brief.prepare_research_brief()`本身就是獨立Python函式（本次
對話全程都是直接`import research_brief`呼叫測試，不需要透過MCP），
接進UI或排程沒有架構障礙。

**建議分兩步，UI優先**：

1. **第一步：UI按鈕**（風險低、複用既有架構、立即有用）——
   `/dashboard/stock/<code>`加按鈕（或兩個按鈕對應full/monitoring），
   呼叫時`analysis_mode`已確定，天生滿足閘門。財務體檢五項＋
   no_data_source三項直接渲染表格；**六個needs_discussion欄位**本質
   是判斷，靜態頁面做不了，顯示成引導提問文字＋「跟AI討論這幾點」
   連結帶去對話，不要讓頁面自己生成答案（維持機械蒐集/判斷分離原則）；
   對照組（Stage2 peers）UI上維持PO手動輸入，不自動選。
2. **第二步：排程**（等UI跑過一段時間、確認有用再做，非阻塞）——
   併入`module_d_scheduler.py`既有02:00排程，持股/觀察名單標的固定跑
   monitoring模式，寫進「模組D檢視結果表」，儀表板開頁面就看得到。
   **要注意FinMind額度**（2026-07-28教訓：匿名額度全域共用池）——
   持股+觀察名單標的數一多，每晚多查這些會不會擠爆額度，需要先估算
   標的數量再決定要不要做。

**不取代對話式觸發**：三條路徑並存——對話式（靈活但這次證明有可靠性
風險，已用硬性閘門補強）、UI（可靠，適合主動研究時用）、排程（適合
被動監控，不用PO觸發）。手機上隨口問這種情境，UI按鈕碰不到，對話式
仍有其價值。

**尚未實作**，是否要啟動、先做UI還是先做排程，待PO另外決定。
