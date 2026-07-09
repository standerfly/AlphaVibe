# AlphaVibe 開發路線圖與進度（Roadmap）

> 目的：讓**任何**接手的 session——不論主對話模型是 Sonnet、Opus 或其他，
> 或是 Cline——都能只靠本檔案＋所指文件繼續開發，不依賴任何對話記憶。
> 維護規則：完成一個階段就更新狀態欄（含日期與證據）；改動計畫本身
> 需 PO 同意並在 clarification-log 留紀錄。

## 階段總覽（2026-07-08 更新）

| 階段 | 內容 | 狀態 | 證據 |
|------|------|------|------|
| 0. 需求工程 | product-spec 補完＋主軸重塑（FR-001~025、Q-001~032） | ✅ 完成 | product-spec.md Status: Accepted（2026-07-08） |
| 1a. PoC：MCP 知識庫 | alphavibe-kb server（8 工具） | ✅ 完成 | commit 2297d45；測試 10/10；fresh agent 驗收 PASS |
| 1a+. PoC 擴充：追溯快照層 | snapshots/sources/holdings 三表＋4 新工具（共 12），report.py 快照/持股區塊（SRC-010、Q-034~036） | ✅ 完成 | 2026-07-09；測試 21/21 |
| 1b. 試用累積 | PO 日常使用：聊資訊→選股→估值→確認入庫→**存分析快照** | 🔄 進行中 | — |
| 1c. 儀表板：總覽名單頁 | FR-024（次之 FR-025 資訊流） | ⏳ 待 1b 累積資料 | — |
| 1d. Cline 粗活 | YouTube 字幕、爬蟲 adapters | ⏳ 隨 1b 需要啟動 | — |
| 2. 正式產品 | speckit 流程＋交易紀錄 FR-022 | ⏳ Phase 1 驗證後 | — |

Deferred（已定案遞延，見 scope-decision.md）：全市場條件篩選、Docker 雲端
部署、多用戶、全域投資助理、n8n、自動通知、Feedback Loop。

## 各階段接手指南

### 1b 試用累積（進行中）
- 執行者：PO 本人（本機或 VS Code tunnel 遠端），用法見 `poc/kb-mcp/README.md`。
- 檢視頁：`python3 poc/kb-mcp/report.py` 產靜態快照（2026-07-08 交付）——
  同時是 OQ-3 儀表板技術形態的「靜態產出」實驗，1c 決策時回收使用心得。
- 完成訊號：Layer 2 累積出一批真實立場（例如 ≥10 檔）、或 PO 說「做儀表板吧」。

### 1c 儀表板：總覽名單頁
- 啟動方式（對任何 session 說）：「讀 docs/spec-intake/alphavibe/roadmap.md
  和 product-spec.md §5 H 組，開發總覽名單頁。」
- 需求依據：FR-024（基本面狀態、距離目標買價、近期訊息量）＋ FR-028
  快照 diff（同標的歷次判斷對照，Q-036）；優先序 Q-031。
- 前置決策：先向 PO 提案儀表板技術形態（product-spec §11 SRC-009 OQ-3，
  本地輕量網頁 vs 靜態產出），**不要自行假設**。
- 資料來源：`poc/data/alphavibe.db`（schema 見 `poc/kb-mcp/kb_store.py`）。
- 硬約束：Python 3.9 相容、不引外部依賴（沿用 poc 原則）、繁體中文介面。
- 驗收（不可自驗）：頁面呈現 list_stances 真實資料與距離目標買價；
  派 fresh agent 依 FR-024 逐項核對＋實際開啟頁面。

### 1d Cline 任務（YouTube／爬蟲 adapters）
- 啟動方式：主對話 session 依 `~/.claude/rules/30-delegation-templates.md`
  第 2 型的精神，把單一 adapter 寫成自包含任務規格（含輸入輸出、邊界
  情況、驗收指令），交 PO 貼給 Cline 執行。
- 範圍鐵則：一次一個 adapter；產出寫入 Layer 3 前必須走確認流程（Q-021）。

### Phase 2 正式產品
- 前置：定案 Q-025（LLM 用量）、Q-026（對話歷史保存）、OQ-1（YouTube
  處理）、OQ-2（交易紀錄邊界）、OQ-3（儀表板形態）——多數靠 1b 實測數據；
  另評估 **服務化與多供應商架構**（Q-034，SRC-010 提案）與
  **watchpoints 排程形態**（FR-031）。
- 啟動方式：「依 handoff-checklist.md 進行 spec-kit input 切分」→ 之後走
  `speckit-specify` → plan → tasks → implement（見 ADR-0027）。

## 給接手 session 的原則（Sonnet 級模型也適用）

1. 先讀本檔案與專案 CLAUDE.md，**不要**從對話記憶或猜測出發。
2. 全域制度照用：派工三件套、驗證不自驗、判斷 rubrics
   （`~/.claude/rules/`，尤其 10/20/30 號檔）。
3. 本專案鐵則：本機只有 Python 3.9（腳本與 poc 都要相容）；poc 零外部
   依賴；文件一律繁體中文；skills 三份拷貝改動要同步。
4. 同一子任務卡住兩輪 → 帶失敗軌跡升級 opus 或停下問 PO，不要硬試第三次。
5. 涉及產品取捨（範圍、優先序、要不要做）→ 整理選項與代價問 PO，不代答。
