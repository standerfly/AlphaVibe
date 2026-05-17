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