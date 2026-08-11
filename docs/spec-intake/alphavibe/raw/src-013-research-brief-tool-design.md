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
