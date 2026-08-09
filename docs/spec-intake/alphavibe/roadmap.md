# AlphaVibe 開發路線圖與進度（Roadmap）

> 目的：讓**任何**接手的 session——不論主對話模型是 Sonnet、Opus 或其他，
> 或是 Cline——都能只靠本檔案＋所指文件繼續開發，不依賴任何對話記憶。
> 維護規則：完成一個階段就更新狀態欄（含日期與證據）；改動計畫本身
> 需 PO 同意並在 clarification-log 留紀錄。

## 階段總覽（2026-08-07 更新：修正1e/1f狀態，見下方「已知限制」文件落差記錄）

| 階段 | 內容 | 狀態 | 證據 |
|------|------|------|------|
| 0. 需求工程 | product-spec 補完＋主軸重塑（FR-001~025、Q-001~032） | ✅ 完成 | product-spec.md Status: Accepted（2026-07-08） |
| 1a. PoC：MCP 知識庫 | alphavibe-kb server（8 工具） | ✅ 完成 | commit 2297d45；測試 10/10；fresh agent 驗收 PASS |
| 1a+. PoC 擴充：追溯快照層 | snapshots/sources/holdings 三表＋4 新工具（共 12），report.py 快照/持股區塊（SRC-010、Q-034~036） | ✅ 完成 | 2026-07-09；測試 21/21 |
| 1a++. PoC 擴充：選股篩選（第一層＋第二層原型） | 第一層 `screen_stocks`（候選清單手動篩選）＋第二層 `run_market_scan`（TWSE/TPEx批次API全市場初篩＋FinMind補回檔幅度，框架鎖定產業別，每天02:00排程自動跑），手機可用（`/screen`、`/market-scan` 網頁） | ✅ 完成 | 2026-07-22；測試 148/148；fresh agent 驗收 PASS |
| 1a+++. PoC 擴充：部位管理／加碼系統（FR-038~043） | 十層決策框架（投資假說＋情境機率評估/寒冬保留比例、加碼Gate/Score、遞減式加碼、組合集中度、重新估值、減碼三分類＋錨點抗恐慌、風險評分）存進 `raw/部位管理*.md`（SRC-011）＋product-spec §5-K＋Layer 1 哲學庫 `framework_evidence_based_position_sizing`；程式面只做了組合集中度需要的「投資主題標籤」（FR-041/042） | ✅ 完成 | 2026-07-24；測試 175/175 |
| 1b. 試用累積 | PO 日常使用：聊資訊→選股→估值→確認入庫；加碼/減碼討論時套用部位管理框架、建倉時標記投資主題 | 🔄 持續進行（資料持續累積，供模組G未來使用） | 已累積28+檔立場（2026-07-24查證） |
| **1b+. 需求重新盤點＋product-spec全面重寫** | 依1b實測發現多處「文件與實際行為不同模式」（entry_condition/time_horizon 0%使用、snapshots表0筆使用、部位管理十層框架0%採用率等），PO與Claude完整討論（2026-07-25~27）產出「策略引擎＋每日PDCA」的 A-G 模組新架構，product-spec.md／scope-decision.md／clarification-log.md 全面更新 | ✅ 完成 | 2026-07-27；`requirements-rescoping.md`（討論全紀錄，含fresh-context agent通盤審查抓到4嚴重+5建議、PO逐項裁決）；product-spec.md重寫後fresh agent驗收10項條件（9直接PASS，1項小落差已修正） |
| 1e. 模組A+D+E開發 | 老芋頭交易結構化表（FR-044）、交易流水表（FR-056）、策略檢視引擎四組成部分（FR-051~055：通用檢視層/策略專屬層/老芋頭動向比對/部位控制建議）、每日排程整合（FR-057） | ✅ 完成（2026-08-07查證修正，先前誤標待啟動） | commit `4fa230e`（2026-07-31）；`review_engine.py`／`module_d_scheduler.py`；測試見`test_review_engine.py`／`test_module_d_scheduler.py`，2026-08-07實測全專案470/470綠；MCP工具`check_general_review`/`check_strategy_review`/`check_laoyutou_signal`/`check_position_control`/`record_module_d_findings`/`run_module_d_check`已掛載server.py |
| 1f. 模組F開發：儀表板方案A | FR-058，依 mockup（見 requirements-rescoping.md 連結）定案的單頁式結構：今日重點/新候選/觀察庫存/策略設定/快速輸入 | ✅ 完成（2026-08-07查證修正，先前誤標待1e完成） | 同commit `4fa230e`；`report.py`之`render_dashboard()`／`render_today_highlights()`／策略設定／快速輸入區塊；`report_server.py`提供`/`首頁與`/report-classic`舊版並存 |
| 1g. 模組G：策略績效回顧 | FR-059 | ⏳ 待樣本量足夠再啟動（1e/1f已完成，資料寫入管道已對，可持續累積） | — |
| 2. 正式產品 | speckit 流程＋交易紀錄整合 FR-022/FR-056 | ⏳ Phase 1 驗證後（五項前置開放問題已於2026-07-27全數定案，見下方「Phase 2 正式產品」節，但「現在啟動Phase 2」本身仍是待PO另外決定的獨立問題，不是自動觸發） | — |

Deferred（已定案遞延，見 scope-decision.md）：Docker 雲端部署、多用戶、
全域投資助理、n8n、自動通知、部位管理Score量化評分/風險評分（Q-039未
翻案部分）、Feedback Loop。**全市場條件篩選已於2026-07-27正式解禁改列
In-Scope（Q-042），不再屬於此清單**。

## 已知限制／待辦（2026-07-22 記錄，PO 確認「這件事得解決」）

- **第二層全市場批次篩選（`market_scan.py`）目前不涵蓋興櫃**：TWSE／TPEx
  的批次 PER 端點都只有上市/上櫃，興櫃沒有官方批次 PER/PBR 端點（已於
  2026-07-22 研究確認），所以 Stage A 的候選初篩完全排除興櫃股。
  **已知的技術解法（尚未實作）**：TPEx 有興櫃月營收批次端點
  `GET /openapi/v1/t187ap05_R`（354家公司，含產業別、官方年增率欄位，
  跟現有 `market_scan.py` 用的上市/上櫃營收批次端點同一種資料形狀）——
  可以先用這個端點依產業別＋營收年增率初篩出興櫃候選（跟現有 Stage A
  邏輯一致），但這批候選缺 PER（無批次端點），需要對篩出的**小批次**
  候選逐檔呼叫既有的 `tpex_client.get_emerging_stock_valuation()`
  （這個專案已經在用的興櫃逐檔估值函式，含完整 caveats 精確度警語）
  補 PER 估算，才能算出 PEG。實作時要接進 `run_scan()` 的 Stage A→B
  流程，且要在頁面/回報裡沿用 `get_emerging_stock_valuation()` 既有的
  caveats 精確度警語（興櫃估值本來就比上市櫃粗略，不能混為一談）。

- **Layer 1 哲學庫「啟動時自動拼接進 system prompt」（product-spec.md
  FR-014）目前沒有實作**（2026-07-24 查證確認）：`poc/kb-mcp/server.py`
  只實作 MCP `tools` capability，沒有 `resources`/`prompts`，也沒有
  initialize 階段讀取 `poc/data/philosophy/*.md` 的邏輯；`save_philosophy`
  /`get_philosophy` 是純被動檔案讀寫工具，存進去不會讓未來新對話自動套用。
  **目前的權宜做法**：專案 CLAUDE.md「常用查證點」用一行指向重要哲學
  模組路徑，靠使用端（Claude Code 會自動載入 CLAUDE.md）間接觸發；真正
  要做到「存了就自動生效」需要新增 MCP resources capability 或啟動腳本，
  屬於 Phase 2 前可評估的技術債，非阻塞。

- **類股資金流追蹤（FR-032~037）已改列 Deferred**（2026-07-24 查證確認，
  Q-041）：2026-07-12 新增時只寫進 product-spec.md v1 摘要行，從未走過
  scope-decision.md 的正式範圍決策流程，也與同文件 Out-of-Scope「自動
  通知」自相矛盾；加入後 12 天零實作（無資料表、無 ETL、無測試，git log
  只有一條純文件 commit）。已同步修正 product-spec.md／scope-decision.md
  ／clarification-log.md（Q-041）。待未來有明確需求與資源時再重新提案
  ——**注意**：全市場條件篩選（Q-030）已於2026-07-27獨立解禁改列
  In-Scope（Q-042），兩者是分開的決定，類股資金流不因此自動連帶解禁。

- **2026-08-07 查證發現：1e／1f 其實已在 commit `4fa230e`（2026-07-31）
  完成，但本檔案「階段總覽」表格當時沒同步更新狀態欄**（該commit本身
  有動到roadmap.md，但只改了其他段落，狀態欄仍停留在「⏳待啟動」，
  header日期也還留著舊的「2026-07-27更新」）——即使是「同一個commit
  改了程式又改了文件」也不保證文件內容真的跟上，接手前務必實際查
  `git log`／跑測試查證，不能只看狀態欄。已於本次查證修正狀態欄，
  詳見上方階段總覽表格與下方1e/1f接手指南。實測2026-08-07：
  `python3 -m unittest discover -s tests` 470/470 綠（含
  `test_review_engine.py`／`test_module_d_scheduler.py`）。

## 各階段接手指南

### 1b 試用累積（持續進行）
- 執行者：PO 本人（本機或 VS Code tunnel 遠端），用法見 `poc/kb-mcp/README.md`。
- 檢視頁：`python3 poc/kb-mcp/report_server.py`（2026-07-10 起，即時渲染
  ＋iPhone PWA 加入主畫面）；靜態模式 `report.py` 保留備用（2026-07-08）。
- 手機對話（Claude App 自訂連接器掛遠端 MCP）：已查證可行、**暫不做**
  （Q-037，2026-07-10）；未來要做時參考 implementation-options 的路線紀錄。
- **2026-07-27 狀態更新**：完成訊號（≥10檔立場）已達標（28+檔），且
  PO已完成需求重新盤點（1b+），下一步是照 1e→1f→1g 開發模組，不是
  停在「試用累積」——1b 本身持續進行只是為了累積更多資料供模組G使用。

### 1e 模組A+D+E開發（老芋頭表／交易流水表／策略檢視引擎／排程整合）—— ✅ 已完成
- **2026-08-07查證修正**：本節先前寫「待啟動」是誤標，實際已於
  commit `4fa230e`（2026-07-31）完成，見 `poc/kb-mcp/review_engine.py`
  （FR-051~055、FR-057的`get_associated_strategies`/`run_module_d_review`/
  `run_module_d_batch`）與 `poc/kb-mcp/module_d_scheduler.py`（CLI排程
  入口）。MCP工具已掛載：`check_general_review`／`check_strategy_review`／
  `check_laoyutou_signal`／`check_position_control`／`record_module_d_findings`／
  `run_module_d_check`。測試：`test_review_engine.py`／
  `test_module_d_scheduler.py`，2026-08-07實測隨全專案470/470通過。
- 若要接手改動這塊：先讀 `review_engine.py` 檔頭docstring（每個FR的
  設計取捨都寫在裡面，含「findings跟items為何要分開」等刻意決定），
  不要憑product-spec.md文字重新設計一遍。

### 1f 模組F開發：儀表板方案A —— ✅ 已完成
- **2026-08-07查證修正**：本節先前寫「待1e完成」是誤標，實際已於同一
  commit `4fa230e`（2026-07-31）完成，見 `poc/kb-mcp/report.py` 的
  `render_dashboard()`／`render_today_highlights()`／策略設定／快速輸入
  區塊，`report_server.py` 提供 `/`（新版）與 `/report-classic`（舊版）
  並存。
- **已知落差／下一步（2026-08-07 PO提出）**：`report.py` 目前庫存呈現
  是純文字/表格，沒有任何圖表（無`<svg>`/`polyline`/`canvas`）。PO想要
  的「庫存進出圖形化表格」（股價走勢＋買賣力道長條圖，協助判斷加減碼
  力道）尚未實作，是1f底下真正待做的新增功能，不是重新做1e/1f。
  已產出mockup定案（見對話紀錄，2026-08-07）：概念A總覽圖形化表格
  （每列一檔庫存徽章+迷你走勢+力道進度條+建議）＋概念B單檔拉大範例
  （價格折線+買賣力道長條圖+精簡清單），表格先掃過、點進去看大圖。
  「建議」欄位理由文字直接重用`review_engine.strategy_specific_review()`/
  `general_review()`/`laoyutou_signal_review()`/`position_control_suggestion()`
  的既有輸出，不必另外設計判斷邏輯。
- 硬約束：Python 3.9 相容、不引外部依賴（沿用 poc 原則，SVG/inline JS
  屬頁面自身內容非外部套件，可用）、繁體中文介面。
- 驗收（不可自驗）：派 fresh agent 依實作內容逐項核對＋實際開啟頁面
  確認圖表正確反映真實交易流水表與review_engine輸出。

### 1g 模組G：策略績效回顧
- 啟動時機：PO主動觸發，不是排程自動跑；等1e/1f運作一段時間、累積夠
  多市場篩選與檢視樣本後再啟動，避免樣本太小的統計沒有意義。
- 需求依據：product-spec.md FR-059。

### Phase 2 正式產品（前置條件已全數定案，是否現在啟動仍待PO另外決定）
- 前置五項開放問題（2026-07-24~27 PO逐項定案，見clarification-log.md
  Q-025/Q-026/Q-042/Q-043、product-spec.md §11）：
  - Q-025（LLM 用量）：**已定案**，維持不設硬上限
  - Q-026（對話歷史保存）：**已定案**，維持只存已確認入庫內容
  - OQ-2（交易紀錄邊界）：**已定案**，按既有建議（FR-022 只記價位/時間/理由）
  - OQ-1（YouTube 處理）：**已定案（2026-07-27）**，PO自行預處理成心得
    文字檔後自由文字貼入，不開發Cline adapter
  - OQ-3（儀表板形態）：**已定案（2026-07-27）**，方案A單頁式（FR-058）
  - Q-034（服務化與多供應商架構）：**已定案（2026-07-27）**，維持
    local-first，不需要服務化架構
  - watchpoints排程形態（FR-031）：仍未討論，非阻塞（FR-031本身是後行
    Phase 2項目）
- **五項開放問題全數解決不等於「現在就該啟動Phase 2」**——目前PO選擇
  的路徑是繼續在Phase 1 PoC擴充模組A-G（1e/1f/1g），不是跳去走
  speckit流程；啟動Phase 2是獨立的範圍/時機決定，需PO明確表示才進行。
- 啟動方式（PO決定要啟動時）：「依 handoff-checklist.md 進行 spec-kit
  input 切分」→ 之後走 `speckit-specify` → plan → tasks → implement
  （見 ADR-0027）。

## 給接手 session 的原則（Sonnet 級模型也適用）

1. 先讀本檔案與專案 CLAUDE.md，**不要**從對話記憶或猜測出發。
2. 全域制度照用：派工三件套、驗證不自驗、判斷 rubrics
   （`~/.claude/rules/`，尤其 10/20/30 號檔）。
3. 本專案鐵則：本機只有 Python 3.9（腳本與 poc 都要相容）；poc 零外部
   依賴；文件一律繁體中文；skills 三份拷貝改動要同步。
4. 同一子任務卡住兩輪 → 帶失敗軌跡升級 opus 或停下問 PO，不要硬試第三次。
5. 涉及產品取捨（範圍、優先序、要不要做）→ 整理選項與代價問 PO，不代答。
