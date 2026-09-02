# Clarification Log: AlphaVibe

This document tracks all questions asked to the PO and the answers received.

| ID | Question | Date Asked | Status | Answer | Date Answered |
|----|----------|------------|--------|--------|---------------|
| Q-001 | 使用者現在如何獲取投資資訊？ | 2026-05-16 | Answered | 分散在 LINE 群組訊息、各投資網站、Facebook 社群；需要手動彙整，耗時且容易遺漏 | 2026-05-16 |
| Q-002 | 目標投資資產類別？ | 2026-05-16 | Answered | 台股為主，兼顧美股 | 2026-05-16 |
| Q-003 | 核心價值是什麼？即時性重要嗎？ | 2026-05-16 | Answered | 收集、彙整、分析與建議；即時性不重要；主要是每天收盤後的全面檢視，並為下一個交易日做準備 | 2026-05-16 |
| Q-004 | MVP 範圍：「收集」是 AI Agent 自動爬取，還是使用者手動貼入？ | 2026-05-16 | Answered | v1 全部手動貼入（LINE、定錨、股癌三來源皆同） | 2026-05-16 |
| Q-005 | LINE 群主是否知情並同意用其發言建立 AI 知識庫？ | 2026-05-16 | Answered | 知情同意，但需匿名保護隱私，系統內外均不顯示真名 | 2026-05-16 |
| Q-006 | 每日新資料如何進入系統？ | 2026-05-16 | Answered | v1 手動複製貼入；未來透過 n8n 自動化 | 2026-05-16 |
| Q-007 | LINE 聊天中的 [照片] 如何處理？ | 2026-05-16 | Answered | v1 跳過照片，記錄為佔位符；未來視需求加入 Vision LLM | 2026-05-16 |
| Q-008 | 群組其他成員的發言是否納入知識庫？ | 2026-05-16 | Answered | 否，只抓群主的發言 | 2026-05-16 |
| Q-009 | 個股立場（Layer 2）如何建立與維護？ | 2026-05-16 | Answered | LLM 自動抽取後人工修正，非全手動 | 2026-05-16 |
| Q-015 | 知識庫技術架構：RAG / Vector DB 還是其他？ | 2026-05-17 | Answered | 改採 SQLite 為主：Layer1 寫入 system prompt、Layer2 結構化 SQL、Layer3 FTS5 全文搜索；避免 Vector DB 和 embedding API 外部依賴，符合「穩定優先、最小化 LLM requests」原則 | 2026-05-17 |
| Q-016 | 公開市場 API 的 rate limit 與速度是否有問題？ | 2026-05-17 | Answered | 排程收盤後一次抓取，無 rate limit 問題；主力用 FinMind（台股）+ Alpha Vantage（美股），幾秒內完成 | 2026-05-17 |
| Q-017 | Facebook 與財經媒體文章的收集方式？ | 2026-05-17 | Answered | FB 手動貼入存 DB；財經媒體為 user-triggered（系統列出連結，使用者確認後才爬取）或手動貼入；需要「待確認連結列表」UI | 2026-05-17 |
| Q-018 | 圖片文章（截圖、雜誌掃描）如何處理？ | 2026-05-17 | Answered | 使用 Claude Vision API：一次 call 完成 OCR + 內容理解 + 摘要，不引入額外 OCR 服務；使用者可接受外部 API 資源 | 2026-05-17 |
| Q-010 | 持倉檢視是否納入 v1？ | 2026-05-16 | Answered | 持倉（含成本價/損益）不納入 v1；但自選股（watchlist）納入 v1，欄位為 {code, name, added_date, memo} | 2026-05-16 |
| Q-011 | 自選股管理 UI 入口為何？ | 2026-05-16 | Answered | 儀表板內可收合面板（右側或底部），不另開設定頁 | 2026-05-16 |
| Q-012 | Daily report 輸出格式為何？ | 2026-05-16 | Answered | 兩區：① 自選股有新消息（優先）② 今日其他提及股票；加上整體市場方向 + 明日策略 | 2026-05-16 |
| Q-013 | 知識庫初始建立方式？ | 2026-05-16 | Answered | Option B：使用者手動挑選歷史 LINE 片段，由 Claude 協助結構化分層（Layer 1/2/3） | 2026-05-16 |
| Q-014 | AI 知識庫來源有哪些？ | 2026-05-16 | Answered | 三來源：(1) LINE 🍀U Life 群組 (2) LINE 與于志宇一對一聊天 (3) 定錨產業筆記 email (4) 股癌筆記 Facebook；定錨可 regex 解析免 LLM，LINE 需 LLM 抽取 | 2026-05-16 |
| Q-019 | 新需求「AI 對話」（SRC-002）在產品中的定位？ | 2026-07-06 | Answered | 作為第四種資料輸入方式，與文字貼入/URL 爬取/圖片解析並列；使用者與 AI 討論投資想法或口述盤後心得，AI 從對話中萃取內容歸檔。不做全域助理、不做固定引導訪談 | 2026-07-06 |
| Q-020 | 對話內容「依照系統功能建立」——歸檔到哪裡？ | 2026-07-06 | Answered | 沿用既有三層知識庫：投資哲學→Layer 1、個股立場→Layer 2、盤勢/市場評論→Layer 3；不新增歸檔架構 | 2026-07-06 |
| Q-021 | 對話內容入庫前是否需使用者確認？ | 2026-07-06 | Answered | 即時確認制：AI 於對話中提議歸檔（層級＋內容摘要），使用者確認後才寫入，可修改或略過 | 2026-07-06 |
| Q-022 | 專案整合：AlphaVibe 與 AI-stock-km-v1 要不要只維護一個？ | 2026-07-07 | Answered | 只維護 AlphaVibe：pre-spec 完成後 code 建在本 repo（含 MCP 知識庫 PoC，放 poc/ 目錄）；AI-stock-km-v1 封存不刪，留作架構參考與日後資料（raw_documents、watchlist）遷移來源。詳見 implementation-options.md | 2026-07-07 |
| Q-023 | web 版 AI 工具的歷史對話是否要撈回本地系統？ | 2026-07-07 | Answered | 不撈回。歷史對話留在原處；日後若有個別重要內容，手動貼入即可（FR-001 通道），不做自動化匯入 | 2026-07-07 |
| Q-024 | AI 對話式輸入（FR-015~018）是否納入 v1 MVP？（SRC-002 OQ-3） | 2026-07-07 | Answered | 納入 v1。PO 於 2026-07-08 驗收 product-spec 時依建議確認（SRC-002 OQ-3 就此定案） | 2026-07-08 |
| Q-025 | 對話式輸入的 LLM 用量邊界？（與「最小化 LLM requests」原則的張力，SRC-002 OQ-2） | 2026-07-07 | Answered | 1b 實測數週（累積28檔立場）後，PO 確認維持 v1 建議：不設硬性上限 | 2026-07-24 |
| Q-026 | AI 對話功能自身的對話歷史保存政策？（只存已確認入庫內容，或整段對話留存＋保存期限；SRC-002 OQ-1，extracted-requirements GAP-003） | 2026-07-07 | Answered | 1b 實測數週後，PO 確認維持 v1 建議：只存已確認入庫內容＋其來源引用片段 | 2026-07-24 |
| Q-027 | 「全域投資助理」（對話中查詢知識庫既有內容）v1 不做已定（Q-019），但應歸類 Deferred（未來再考慮）或 Out-of-Scope（不做）？（SRC-002 OQ-4，extracted-requirements GAP-004） | 2026-07-07 | Answered | 列入 Deferred。PO 於 2026-07-08 依建議確認；scope-decision 已同步移列 | 2026-07-08 |
| Q-028 | 新想法（基本面選股＋估值＋交易紀錄）與 AlphaVibe 的關係？（SRC-009） | 2026-07-07 | Answered | 一個產品：以新主軸重塑 AlphaVibe，不開新專案，落在本 repo；已決策資產（三層知識庫、確認入庫、隱私、FinMind）直接繼承。NewProject 骨架保留備用 | 2026-07-07 |
| Q-029 | 新主軸的 MVP 核心迴圈與優先序？ | 2026-07-07 | Answered | 資訊歸檔討論 → 浮現目標股 → 估值討論（先基本面好、再談價格）→ 進出決策；交易紀錄（預計/實際進出場）後行 | 2026-07-07 |
| Q-030 | 三種選股方式（名單驅動／全市場條件篩選／哲學驅動）的時序？ | 2026-07-07 | Answered | 三者都要，但 v1 先做名單驅動＋哲學驅動（個股級數據即可）；全市場條件篩選後行（需全市場數據管線，列 Deferred） | 2026-07-07 |
| Q-031 | 儀表板圖像化的優先序？ | 2026-07-07 | Answered | 總覽名單頁 > 資訊流時間軸 > 個股頁 > 交易覆盤頁 | 2026-07-07 |
| Q-032 | AI 引擎與部署形態？ | 2026-07-07 | Answered | 不自建內嵌 LLM 的產品：Claude 為主力（聊天思考）＋ Cline 輔助（爬蟲等簡單工作），本地資料庫承載（local-first）；SRC-001 §8 的 Docker 雲端部署與自建前後端假設隨之修訂 | 2026-07-07 |
| Q-033 | 是否結合 Obsidian（個人使用情境）？ | 2026-07-08 | Answered | 不做整合：瀏覽需求由 1c 儀表板涵蓋（FR-024/025），避免 SQLite↔md 雙真相來源、違反功能最小化原則。Layer 1 哲學庫本為 .md 檔（poc/data/philosophy/），可自行加入 Obsidian vault 取用——格式天生相容，非整合。日後有具體需求（如手機離線瀏覽 L3）再以匯出腳本處理 | 2026-07-08 |
| Q-034 | 引擎架構是否因 SRC-010 建議書重開（FastAPI 服務化＋Agent Router 多供應商＋自建聊天 UI）？ | 2026-07-09 | Answered | 現在維持 local-first（Q-032 不變：Claude+Cline+MCP）；「服務化與多供應商」列為 Phase 2 前的待評估選項，屆時以 1b 實測經驗決定。現階段供應商可換性由 MCP 開放標準（任何支援 MCP 的用戶端可掛同一知識庫）與開放 SQLite 格式提供 | 2026-07-09 |
| Q-035 | SRC-010 的 holdings（持股入庫）納入程度？（Q-010 曾排除持倉追蹤） | 2026-07-09 | Answered | 部分納入：截圖持股解析（FR-010 Vision 通道）＋持股快照入庫 {code, shares, avg_cost, snapshot_date}，供分析引用與 diff；不做損益追蹤介面。屬 Q-010 的邊界修正而非推翻——損益計算與部位管理仍排除 | 2026-07-09 |
| Q-036 | SRC-010 追溯性需求包（分析快照＋來源引用＋diff、篩選框架、watchpoints）如何納入？ | 2026-07-09 | Answered | 納入 spec 並立即擴充 MCP PoC（save_snapshot／sources／holdings 工具）；diff 檢視排入 1c 儀表板；watchpoints 後行 Phase 2。附帶採納：查證單檔單次 ≤3 查詢、免責聲明 NFR、快照記錄產出模型與框架版本、查證來源優先序表存為參考 | 2026-07-09 |
| Q-037 | iPhone 使用需求：檢視與對話各怎麼做？ | 2026-07-10 | Answered | 檢視＝PWA 化＋即時渲染 server（report_server.py，沿用 devtunnels 8080 網址，加入主畫面）；**手機對話暫不做**——已查證可行路線（Claude App 自訂連接器掛遠端 MCP：官方支援手機 App、僅 tool calls、端點須公網可達，見 implementation-options 紀錄），未來要做時再啟動。CH-EN 專案研究結論：其機制為 Cloudflare Quick Tunnel（無驗證、網址不固定），不沿用，記為備援模式 | 2026-07-10 |
| Q-038 | 部位管理／加碼系統的範圍是否與 Q-010/Q-035「部位管理排除」衝突？（SRC-011） | 2026-07-23 | Answered | 不衝突，邊界修正：Q-010/Q-035 排除的是**損益計算與損益追蹤介面**；本次的**加碼/減碼決策邏輯**（Gate四問、信心分級建倉、遞減式加碼、組合集中度檢查）屬決策輔助流程，不涉損益計算，改列 In-Scope MVP 子集（見 scope-decision.md、product-spec §5-K） | 2026-07-23 |
| Q-039 | v2.0 十層框架這次要做到什麼開發深度？（SRC-011） | 2026-07-23 | Answered | MVP 先行：沿用既有 save_stance/save_holdings/save_snapshot 三工具＋人工判斷，不新增交易流水表；Score量化評分、風險評分、遞減式加碼比例自動計算列 Deferred，待 1b 試用驗證流程後再評估是否投入開發（部分子項如法人EPS上修/毛利率/ROE/Backlog目前無公開批次資料源） | 2026-07-23 |
| Q-040 | 投資主題標籤（如AI CAPEX橫跨世芯/家碩/台達/力智）如何處理？（SRC-011） | 2026-07-23 | Answered | 新增「投資主題標籤」欄位（不同於官方 industry_category），MVP 先由 PO 手動標註，供組合集中度人工檢查使用；單股佔比沿用既有 report.py 計算 | 2026-07-23 |
| Q-041 | 類股資金流追蹤（FR-032~037，2026-07-12 新增於 product-spec 摘要行）從未走過本文件的範圍決策流程，也與 Out-of-Scope「自動通知」自相矛盾，加入後12天零實作——如何定案？ | 2026-07-24 | Answered | 改列 Deferred：product-spec.md、scope-decision.md 同步修正（移出 v1 In-Scope 摘要、Out-of-Scope 矛盾解除、Deferred 清單新增條目）。待未來有明確需求與資源（可能與 Q-030 全市場條件篩選一併評估）時再重新提案 | 2026-07-24 |
| Q-042 | Q-030（全市場條件篩選選股）原列 Deferred，理由是「等資料庫基礎穩定後再建」——market_scan 實際上已於 2026-07-22 起有原型上線並排程運作（每天掃近2000檔），這個理由是否已經滿足，要不要正式解禁？ | 2026-07-27 | Answered | 正式改列 In-Scope：1b 階段確認 market_scan 持續使用、運作穩定，比照 Q-041（類股資金流）當初「文件狀態要反映實況」的處理原則。product-spec.md、scope-decision.md 同步修正 | 2026-07-27 |
| Q-043 | Q-034（服務化與多供應商架構）原決定「列為 Phase 2 前待評估項，屆時以 1b 實測經驗決定」——這次討論儀表板要不要整合對話能力，實質上就是那次評估，結論是什麼？ | 2026-07-27 | Answered | 評估結論：儀表板輸入需求以「方案A：對話輸入＋快速表單」滿足，不需要服務化架構（FastAPI＋Agent Router＋多供應商）；local-first＋Claude Code對話的架構假設維持不變。中間方案（儀表板內嵌輕量對話框）若未來需要更完整對話功能時仍是可行下一步，完整服務化架構目前規格過剩，繼續列 Deferred | 2026-07-27 |
| Q-044 | Q-039（部位管理十層框架開發深度）原決定「遞減式加碼比例自動計算、交易流水表列 Deferred」——這次設計模組D的部位控制建議（核心功能）時發現需要加碼次數歷史才能算出「第幾次加碼用多少%」，是否要一併從 Deferred 移出？ | 2026-07-27 | Answered | 部分翻案：遞減式加碼比例自動計算與交易流水表改列 In-Scope（部位控制建議的必要前置）；Score量化評分、風險評分維持 Deferred（部分子項無公開批次資料源，不受影響）。product-spec.md FR-054/FR-056、scope-decision.md 同步修正 | 2026-07-27 |
| Q-045 | 這次對話討論「擺脫單機依賴的正式部署」（雲端主機/服務化），累積了不少單機依賴的真實痛點（環境切換、tunnel不穩、hook卡死）——要不要現在啟動這條架構升級？ | 2026-08-18 | Answered | 暫緩，改用「使用率」當啟動門檻：PO明確表示核心動機不是穩定性，是先確認服務內容真正符合需求——目前使用率不好，要先優化內容，等使用率提升（＝內容已經對了）才討論上線／架構升級。日後若真的評估，優先找免費方案，非必要不接受月費（哪怕$5-10）。不是否決，是排序在「內容打磨」之後 | 2026-08-18 |
| Q-046 | Q-034（引擎架構服務化評估，2026-07-27結論：維持local-first）與 Q-045（2026-08-18結論：先打磨到常用才談架構升級，非必要不接受月費）是否因新的「個人主控台擴建」規劃而推翻？來源：Claude Code 規劃 session（未另外走本文件正式 `/prespec` 流程，該對話視同 pre-spec）；規劃全文見 `roadmap.md`「Phase 2 正式產品」節 2026-08-21 補充、`supporting-artifacts/2026-08-21-personal-console-expansion.md`（含連結的 Claude Artifact 架構圖／mockup）。Impact area：scope／架構（服務化與多供應商架構、產品定位）。決策者：PO Stander。 | 2026-08-21 | Answered（2026-08-24 補登入本文件） | **推翻 Q-034 與 Q-045**：`poc/kb-mcp` 全面重寫為 FastAPI（`app/`）＋ React（`web/`）輕量前後端分離（同源部署、單一 process，非完整雙服務分離，不需重新設計 CORS／認證）；底層計算邏輯與資料層（`kb_store.py`／`screener.py`／`report.py`／`frameworks.py`）未重寫，`app/` 各 router 直接 import 既有函式。產品定位同時擴展為「STND 個人一站入口」多分頁主控台（品牌名 STND，技術／repo 層級仍為 AlphaVibe）——除既有投資功能外新增資產分頁（口袋/帳戶/建倉進度/情境試算，已上線）與相簿分頁（MVP 僅導覽入口）。遷移範圍涵蓋既有 `/screen`、`/market-scan`、`/dashboard` 系列、5 個表單端點、MCP 連接器（`/mcp`）全數遷移，`/report-classic` 舊版頁面停用不遷移。推翻理由：為未來功能擴充、維護性、docker 化打底（docker 化本身截至上線時尚未實作，仍屬 Deferred）。已於 2026-08-22 實際完成開發並上線（`com.alphavibe.reportserver.plist` 改跑 `uvicorn app.main:app`）；本條目為 2026-08-24 依 pre-spec 基線正式補登，追溯依據見 product-spec.md §1/§3/§5/§8、`docs/architecture.md`。 | 2026-08-21（決策日）；2026-08-24（補登入本文件） |
| Q-047 | 旅遊分頁的內容整合深度：要不要整合獨立專案 `/Users/stander/My_project/mytravel/` 的資料？整合到多深（純導覽連結 vs 完整資料整合）？來源：`CLAUDE.md`「STND 分頁與程式碼位置」節、`docs/architecture.md`「已知開放問題」節（兩者皆明文記載此為待決事項，尚未走本文件正式決策流程）。Impact area：scope。 | 2026-08-22（CLAUDE.md 明文記載此為待決事項）；2026-08-24（本次補登為正式 clarification-log 條目） | Deferred | 旅遊分頁本身尚未開始建立（無前端頁面、無後端 router，程式碼確定會建在本 repo 但功能完全未開工）。要不要整合 `mytravel` 的資料、整合到多深，是獨立待討論的範圍決策，明文不預設；決定後才動工。 | 尚無決定（Open，待 PO） |
| Q-048 | 開發優先序重排：新功能「進出場時機分析工具」（`docs/spec-intake/entry-exit-timing-analysis/`）相對於 roadmap 既有懸置待辦（1g 模組G策略績效回顧、興櫃候選篩選缺口、Layer 1 哲學庫自動拼接 FR-014、Phase 2 正式產品啟動）應該排在哪？來源：2026-09-02 對話——PO 要求分析持股進場時機，過程中因人工拼湊多個唯讀工具發生 `yoy_growth` 單位誤讀事故（原始值是小數 1.0=100%，被誤當百分比少乘 100 倍，導致多檔持股成長判斷方向顛倒），盤點後確認現有工具無一涵蓋進出場時機分析。Impact area：scope、priority。 | 2026-09-02 | Answered | **優先序（PO 2026-09-02 定案）**：(1) 進出場時機分析工具（**第一順位**，理由：源自真實事故而非可無限期等待的路線圖項目，直接餵給日常加減碼決策，價值兌現快於事後回顧性質的 1g；且其 FIFO 損益邏輯完成後 1g 可直接複用，先做反而省工）→ (2) 興櫃候選篩選缺口（範圍小、技術解法已寫在 roadmap，與 (1) 不衝突可並行）→ (3) 1g 模組G策略績效回顧 → (4) Layer 1 哲學庫自動拼接（FR-014，已有 workaround，純技術債）。**Phase 2 正式產品啟動維持按住不動**（2026-08-18 Q-045「先打磨到常用才談架構升級」的決定本次未翻案）。PO 表示目標想完成前三項。**交付方式**：進出場時機分析分兩階段（階段A `entry-exit-foundation`：FIFO 損益＋股價歷史百分位＋MCP 工具化；階段B `entry-exit-signals`：討論式停損停利門檻＋背離偵測＋觸發建議＋報告頁面整合＋排程整合），拆分理由見該功能的 `scope-decision.md`。**實作尚未開放**：PO 同日明確指示「先不要執行改 CODE」，兩份 speckit-input 維持 Draft。 | 2026-09-02 |