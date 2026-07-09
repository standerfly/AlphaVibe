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
| Q-025 | 對話式輸入的 LLM 用量邊界？（與「最小化 LLM requests」原則的張力，SRC-002 OQ-2） | 2026-07-07 | Open（非阻塞） | 建議：v1 不設硬性上限，以 Phase 1 PoC 實測用量後、Phase 2 動工前定案 | — |
| Q-026 | AI 對話功能自身的對話歷史保存政策？（只存已確認入庫內容，或整段對話留存＋保存期限；SRC-002 OQ-1，extracted-requirements GAP-003） | 2026-07-07 | Open（非阻塞） | 建議：待 Phase 1 PoC 實測後定；PoC 期間先只存已確認入庫內容＋其來源引用片段 | — |
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