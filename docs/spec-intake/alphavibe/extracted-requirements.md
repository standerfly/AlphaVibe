# Extracted Requirements: AlphaVibe

**Feature Slug:** alphavibe
**Last Updated:** 2026-07-07

## Candidate Functional Requirements

- **FR-001**: 使用者可手動貼入來自 LINE、定錨、股癌的原始文字，系統依來源 tag 儲存。（SRC-001 L111；相關澄清：Q-004, Q-014）
- **FR-002**: 系統可從定錨 email 文字以結構化解析（非 LLM）抽取個股代碼、EPS 財測、定錨觀點。（SRC-001 L112；相關澄清：Q-014）
- **FR-003**: 系統可透過 LLM 從 LINE 訊息抽取群主的個股立場，產出 {code, name, stance, date} 供人工確認。（SRC-001 L113；相關澄清：Q-008, Q-009）
- **FR-004**: 每日收盤後，系統採取「分段摘要 → 最終整合」流程產出報告：階段一將 Layer 3 原始訊息按個股/主題進行初步摘要、過濾雜訊；階段二結合初步摘要、Layer 1 哲學、Layer 2 立場及外部 API 數據，產出含市場方向、明日策略、個股更新的最終報告。（SRC-001 L114-116；相關澄清：Q-003, Q-015）
- **FR-005**: 使用者可在儀表板新增、刪除、檢視自選股（欄位 {code, name, added_date, memo}）。（SRC-001 L117；相關澄清：Q-010, Q-011）
- **FR-006**: 自選股有新消息時於報告中優先顯示於第一區；其他今日提及股票顯示於第二區。（SRC-001 L118；相關澄清：Q-012）
- **FR-007**: 報告內容可連結回原始來源片段。（SRC-001 L119；亦為 FR-017 來源回溯機制之依據）
- **FR-008**: 系統可透過 FinMind（台股）與 Alpha Vantage（美股）API 獲取指定個股的基礎財務數據與價格走勢。（SRC-001 L120；相關澄清：Q-016）
- **FR-009**: 使用者可提供 URL，系統觸發爬蟲抓取網頁內容並交由 LLM 分析。（SRC-001 L121；相關澄清：Q-017）
- **FR-010**: 使用者可上傳圖片，系統透過 Vision LLM（如 Claude Vision）解析圖表關鍵資訊並納入每日報告。（SRC-001 L122；相關澄清：Q-007, Q-018）
- **FR-011**: 系統於每日收盤後排程抓取自選股最新收盤價，若觸及 Layer 2 定義的 `entry_condition`，在當日報告中標記「觸發買入條件」提醒。（SRC-001 L123；依賴 Layer 2 schema，見 §1）
- **FR-012**: 系統實作「前置清洗層」，解析 LINE 匯出文字時依規則處理後再存入 Layer 3（FTS5）：雜訊過濾（regex 移除時間戳／系統通知／格式符號）、內容過濾（`[照片]`/`[影片]`/`[貼圖]`/`[相簿]`/`[檔案]` 跳過）、狀態過濾（已收回訊息跳過）、正常存入清洗後文字（附 {sender, timestamp, raw_text, source_tag}）。（SRC-001 L125-129；相關澄清：Q-007）
- **FR-013**: 當 Layer 3 當日訊息涉及某個股，且與 Layer 2 已定調立場明顯矛盾時，系統標記「⚠️ 立場衝突」並列出衝突摘要，不自動更新 Layer 2，由使用者決定是否修正。（SRC-001 L124；為 SRC-001 §11 Q3 之最終決定；亦為 FR-018 沿用之機制）
- **FR-014**: 系統應支援投資哲學模組的擴展；使用者於指定配置目錄新增 `.md` 檔案即可增加分析視角，新模組於系統重啟後生效。（SRC-001 L130；對應 §1 Layer 1 架構）
- **FR-015**: 使用者可在儀表板以「AI 對話」方式輸入資料：與 AI 以自然語言討論投資想法或口述盤後心得，作為與文字貼入（FR-001）、URL 爬取（FR-009）、圖片解析（FR-010）並列的第四種資料輸入方式。（SRC-002 L29-31；相關澄清：Q-019）
- **FR-016**: 系統可透過 LLM 從對話內容即時萃取可歸檔資訊，依內容型態分類：投資哲學/原則 → Layer 1；個股立場（{code, name, stance, reason, date}）→ Layer 2；盤勢/市場評論 → Layer 3。（SRC-002 L32-34；相關澄清：Q-020）
- **FR-017**: 每筆歸檔提議須經使用者即時確認（確認／修改／略過）後才寫入知識庫；寫入內容附帶對話來源引用，支援報告的來源回溯（FR-007）。（SRC-002 L35-36；相關澄清：Q-021）
- **FR-018**: 對話中萃取的個股立場與 Layer 2 既有立場明顯矛盾時，沿用 FR-013 的「⚠️ 立場衝突」機制：於提議卡片中標示衝突並列出既有立場，由使用者決定是否更新。（SRC-002 L37-39；沿用 FR-013）

> 2026-07-08 更新：FR-015~018 已由 PO 於 product-spec 驗收時**確認納入 v1 MVP**（clarification-log Q-024 = Answered），GAP-002 隨之 Resolved。

### SRC-009 主軸重塑新增（2026-07-07；補登於 2026-07-09）

- **FR-019**: 名單驅動選股——與 AI 討論歸檔資訊時浮現的標的，AI 即時補基本面數據協助評估。（SRC-009 §3；Q-030）
- **FR-020**: 哲學驅動候選——AI 依 Layer 1 哲學模組結合數據與歸檔資訊主動提候選。（SRC-009 §3；Q-030）
- **FR-021**: 估值討論——目標買賣價與理由經確認後寫入 Layer 2 既有欄位。（SRC-009 §3；Q-029）
- **FR-022**: 交易紀錄——記錄預計/實際進出場（價位、時間、理由），後行階段。（SRC-009 §3；Q-029；邊界見 SRC-009 OQ-2）
- **FR-023**: YouTube 來源納入。（SRC-009 §3；處理方式見 SRC-009 OQ-1）
- **FR-024**: 總覽名單儀表板頁。（SRC-009 §3；Q-031）
- **FR-025**: 資訊流時間軸。（SRC-009 §3；Q-031）

### SRC-010 追溯性需求新增（2026-07-09）

- **FR-026**: 分析快照——分析結論以快照凍結：{code, snapshot_date, price_at_time, valuation_at_time, thesis（驅動因素）, risks（下檔風險）, watch_next（後續關注點）, framework_version, model_id}。（SRC-010 §3.1/§3.3；Q-036）
- **FR-027**: 來源引用——每筆快照可附引用來源 {url, title, retrieved_at, quote_summary}；查證以單檔單次 ≤3 查詢為上限。（SRC-010 §3.1/§6；Q-036）
- **FR-028**: 快照 diff——同一標的歷次快照對照（結論/風險/價格/估值的變化），實作於 1c 儀表板。（SRC-010 §4.3；Q-036）
- **FR-029**: 持股快照——截圖經 Vision 解析（沿 FR-010）後入庫 {code, name, shares, avg_cost, snapshot_date}，供分析引用與 diff；**不含損益追蹤介面**（Q-010 邊界維持）。（SRC-010 §3.3；Q-035）
- **FR-030**: 篩選框架引擎——可版本化的 checklist（Layer 1 結構化延伸，如 framework_v1），screen 結果入快照並記錄框架版本。（SRC-010 §3.4；Q-036）
- **FR-031**: watchpoints 事件提醒——除權息/法說會/月營收公告到期提醒並觸發更新，**後行 Phase 2**（排程形態屆時再定）。（SRC-010 §4.2；Q-036）
- **NFR**: 免責聲明——系統輸出為研究輔助資訊、非投資建議，介面固定顯示。（SRC-010 §6；Q-036）
- **參考資料**: 查證來源優先序表（股價/月營收/法說/除權息/公告的首選與備援來源）。（SRC-010 §4.1）

## Candidate Actors And User Goals

- **Core User（您本人）**：獲取所需的投資資訊以輔助決策；主要使用者。（SRC-001 L75）
- **Secondary User（受信任朋友）**：獲取分析後的市場觀點；小規模多用戶支援，不含完整權限管理系統。（SRC-001 L76；範圍排除見 §4b「多用戶管理」）
- 補充：AI 對話式輸入（FR-015~018）不新增角色，沿用 Core User／Secondary User 既有互動對象，僅新增一種輸入管道。（SRC-002 §1 L10-15）

## Candidate Success Criteria

- **功能完整度**：實現從手動貼入資料到產出結構化報告的完整閉環。（SRC-001 L151）
- **分析準確度**：經人工抽樣核對，個股立場抽取與市場方向總結的準確率 ≥ 90%。（SRC-001 L152）
- **效率提升**：使用者每日覆盤所需的手動彙整時間顯著降低（業務動機章節量化為「從 1 小時縮減至 10 分鐘內」）。（SRC-001 L153, L65）
- **系統穩定性**：每日收盤後的排程任務能穩定執行，無毀滅性崩潰。（SRC-001 L154）

## Candidate Constraints And Assumptions

**系統設計原則（SRC-001 §8）：**
- 穩定優於速度：準確性與穩定性優先，不追求即時性，速度以排程機制補足。（SRC-001 L161）
- 最小化 LLM 請求：盡量減少對 AI Agent 的 API 呼叫次數以降低成本與錯誤率；但為求長文本處理穩定性，報告生成允許「分段摘要 → 最終整合」兩階段呼叫。（SRC-001 L162；與 FR-015~018 的張力見 GAP-001／Q-025）
- 前後端分離：介面與邏輯層獨立部署。（SRC-001 L163）
- 功能最小化：以最小可用為原則，各模組獨立開發與測試後再整合。（SRC-001 L164）
- 架構文件優先：系統架構與模組間溝通文件需完整維護，參數命名全系統保持一致。（SRC-001 L165）

**部署假設（SRC-001 §8）：**
- Docker 容器化方式部署於雲端。（SRC-001 L168）
- Layer 1 模組目錄建議透過 Docker Volume 掛載，以實現無需重新構建鏡像即可更新哲學庫。（SRC-001 L169）
- 初期單人使用，未來擴展至少量朋友（小規模多用戶）。（SRC-001 L170）

**來自澄清紀錄的額外限制與假設：**
- LINE 群主發言用於建立知識庫需其知情同意，且系統內外均需匿名保護隱私（不顯示真名）。（clarification-log Q-005）
- 知識庫技術架構確定採 SQLite（Layer1 寫入 system prompt／Layer2 結構化 SQL／Layer3 FTS5 全文搜索），刻意避免 Vector DB 與 embedding API 外部依賴。（clarification-log Q-015）
- 外部市場數據 API（FinMind／Alpha Vantage）採收盤後排程一次性抓取，無 rate limit 疑慮。（clarification-log Q-016）
- 專案整合決策：僅維護 AlphaVibe 一個 repo，pre-spec 完成後程式碼建於本 repo（含 MCP 知識庫 PoC，放 `poc/` 目錄）；AI-stock-km-v1 封存不刪，作為架構參考與未來資料遷移來源。（clarification-log Q-022）
- 既有 web 版 AI 工具（如 ChatGPT／Claude.ai）的歷史對話不做自動化撈回；日後若有個別重要內容，手動貼入即可（沿用 FR-001 通道）。（clarification-log Q-023）
- AI 對話式輸入（FR-015~018）的 LLM 用量邊界：目前建議 v1 不設硬性上限，待 Phase 1 PoC 實測用量後、Phase 2 動工前再定案；狀態為 **Open（非阻塞）**，非最終決定。（clarification-log Q-025）

## Candidate Error Or Failure Behavior

**錯誤處理表（SRC-001 §9）：**
- 外部 API（FinMind／Alpha Vantage）宕機：報告中標記數據缺失，不阻塞報告生成；復原方式為使用快取數據或手動觸發重新抓取。（SRC-001 L178）
- LLM API 額度耗盡／逾時：記錄錯誤日誌並通知使用者；復原方式為切換備用模型（Fallback LLM）或手動重新執行。（SRC-001 L179）
- 爬蟲被目標網站封鎖：記錄 URL 並標記為「抓取失敗」；建議使用者手動貼入內容。（SRC-001 L180）
- SQLite 資料庫鎖定：實作簡單重試機制（Retry logic）；自動重試 3 次後記錄錯誤。（SRC-001 L181）

**例外流程補充（SRC-001 §6 場景 2）：**
- API 請求失敗：FinMind 或 Alpha Vantage 回傳錯誤或達限額時，記錄錯誤並標記「數據更新失敗」，使用最後一次快取數據，不中斷報告生成流程。（SRC-001 L143）
- Vision 解析錯誤：LLM 無法正確辨識圖片圖表數據時，報告中標記「圖片解析不確定」，並保留原圖連結供人工核對。（SRC-001 L144）
- 資料抽取格式錯誤：LLM 抽取個股立場格式不符（如缺代碼）時，該片段移至「待人工確認」區塊，不直接寫入 Layer 2 結構化表格。（SRC-001 L145）

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001 §8 L162；SRC-002 §5 OQ-2 (L54-56)；clarification-log Q-025 | Conflict (tracked) | SRC-001 訂下「最小化 LLM 請求」設計原則；SRC-002 的 AI 對話式輸入（FR-015~018）天然增加 LLM 呼叫次數，兩者存在張力 | Open（非阻塞，已有 PO 建議方向） | 已由 clarification-log Q-025 追蹤：建議 v1 不設硬性用量上限，待 Phase 1 PoC 實測後、Phase 2 前定案。仍非最終決定，product-spec 應標註為待確認 |
| GAP-002 | SRC-002 §5 OQ-3 (L57)；clarification-log Q-024 | Unclear (tracked) | FR-015~018（AI 對話式輸入）是否納入 v1 MVP 範圍未定；SRC-001 §4a/4b/4c 的範圍分類（早於 SRC-002 撰寫）未涵蓋此功能 | **Resolved（2026-07-08）** | Q-024 已 Answered：PO 於 product-spec 驗收時確認納入 v1；scope-decision 與 product-spec §3 已同步標示 |
| GAP-003 | SRC-002 §5 OQ-1 (L52-53)；clarification-log Q-023 | Unclear | 新對話式輸入功能自身的對話歷史保存政策未定（只存「確認入庫」內容，或整段對話都留存；保存多久） | Open（尚未追蹤，clarification-log 目前無對應 ID） | 不可與 Q-023 混淆：Q-023 回答的是「既有 web 版 AI 工具的歷史對話是否要撈回」（已回答：不撈回），並未回答「新對話功能自身對話記錄的保留政策」，此問題仍完全未被回答，建議新增澄清問題追蹤 |
| GAP-004 | SRC-002 §5 OQ-4 (L58-59)；clarification-log Q-027 | Unclear | 「全域投資助理」（對話中查詢知識庫既有內容）已決定 v1 不做，但是否列入 Deferred 清單尚未定案 | **Resolved（2026-07-08）** | 已建 Q-027 追蹤並於 2026-07-08 Answered：定案列入 Deferred；scope-decision 已移列 |
| GAP-005 | SRC-001 §11 (L196-201)；clarification-log Q-001~Q-025 | Unclear (naming collision) | SRC-001 §11「開放問題」使用 Q1~Q4 編號，與 clarification-log 的 Q-001~Q-025 編號體系是兩套不同的 ID，容易誤讀為同一組問題 | Resolved（文件慣例差異，非語意衝突） | 建議後續文件引用 SRC-001 內部開放問題時改稱「SRC-001-OQ1」等以避免混淆；核對後，SRC-001 Q1（多用戶自選股隱私/權限）與 Q2（多來源立場衝突權重判定）均未見於 clarification-log 已答清單，仍為開放狀態；Q3 已於 SRC-001 文中自行標記解決（→ FR-013）；Q4 已標記 Deferred |
| GAP-006 | SRC-001 L123-125（FR-011, FR-013, FR-012 原文排列順序） | Unclear (documentation only) | 原文 FR 編號在文件中未依數字順序排列（FR-011 → FR-013 → FR-012 → FR-014） | Resolved（僅排版順序問題，內容本身無矛盾） | 逐條核對後三者敘述互不衝突、亦非重複；本文件已依編號順序重新排列呈現，FR 編號本身未變更 |
