# Extracted Requirements: Substack 文章自動匯入（011）

**Feature Slug:** substack-import
**Last Updated:** 2026-11-19（追加決定後修訂）

來源標記：SRC-001＝PO prompt、SRC-002＝PO 決定紀錄（優先）、SRC-003＝RSS／ToS 研究、SRC-004＝010 盤點。

## Candidate Functional Requirements

| ID | 候選需求（產品語言） | 來源 |
|----|----------------------|------|
| CFR-01 | 以 Substack 公開 RSS 為唯一內容來源；Gmail 通知信不用 | SRC-002 決定2；SRC-003 §5 |
| CFR-02 | 追蹤清單放在設定檔；新增作者、停用作者由 Claude 在對話中修改，PO 不需寫程式 | SRC-002 決定3；SRC-001 Components 2 |
| CFR-03 | 初始追蹤作者：FOMO研究院電子報（subdomain fomosoc）、大叔美股筆記（unclestocknotes） | SRC-002 追蹤來源 |
| CFR-04 | 文章存入獨立資料庫 `substack.db`；不修改 010 的 `articles.db` | SRC-002 決定4 |
| CFR-05 | 去重鍵用 guid／URL，重複文章不重複儲存 | SRC-001 Components 4 |
| CFR-06 | 首次執行只收「首次執行日前 14 天」內的文章（實測約 25 篇） | SRC-002 決定5 |
| CFR-07 | 每日 22:00 執行一次（05:00～18:00 的適用範圍見 CFR-28） | SRC-002 決定6 |
| CFR-08 | 011 另設獨立的執行鎖，只寫 `substack.db` | SRC-002 決定10；SRC-001 010補充 |
| CFR-09 | 免費文章存全文；付費文章只存預覽並標記「僅預覽」；判斷規則三類：P 預覽（content:encoded 結尾為固定「Read more」連結段落）、F 全文（無該尾端且有足夠純文字）、N 非文字（無該尾端且幾乎無文字或僅有播放器）；無法確定者一律存為「僅預覽」並標示；不得以文章長度判斷 | SRC-002 決定7、「追加決定（Q-103／Q-104 調查後）」節；SRC-005；SRC-003 §2 |
| CFR-10 | 不登入、不用任何 cookie、不繞付費牆、不抓付費全文 | SRC-001 Target／Function |
| CFR-11 | 圖片下載存本機、不自動送模型分析；內文保留圖位標記（含圖說／alt）；轉寫見 CFR-26 | SRC-002 決定8；SRC-001 010補充 |
| CFR-12 | 011 文章預設不進入 010 排程轉寫流水線，且須有測試證明 | SRC-001 010補充 |
| CFR-13 | 不呼叫模型、不消耗 claude.ai 訂閱額度（預設只抓取與存檔） | SRC-001 010補充 |
| CFR-14 | Telegram 通知含作者＋標題；日誌與錯誤訊息不含標題 | SRC-002 決定9（覆寫 SRC-001 通知限制） |
| CFR-15 | 健檢／通知回報剩餘硬碟空間、`substack.db` 與圖片目錄占用量；只報現況，不判定異常、不設閾值 | SRC-002 決定11 |
| CFR-16 | 即時取得：手動觸發立即輪詢一次 RSS，與排程共用鎖、去重與資料庫；可指定單一作者或全部；同一作者兩次輪詢有最小間隔（任何輪詢，含排程，皆計入）；只認 RSS，不抓單篇網頁；feed 尚未出現則回報「稍後再試」 | SRC-002 即時取得 |
| CFR-17 | 即時取得兩個入口：(1) Mac 上 Claude Code 對話；(2) claude.ai 連接器（含手機） | SRC-002 即時取得（PO 原話「1+2」） |
| CFR-18 | 入口 (2) 為新增的通用**寫入**工具：台股與美股兩個連接器都提供、行為逐字相同；不接受網址參數；只寫 `substack.db`；不進唯讀白名單 | SRC-002 即時取得 |
| CFR-19 | 守門數字以合併當下 `function/alphavibe` 實際值為準，011 為台股／美股各 +1、唯讀不變（撰寫時 2026-11-19 實測基準：台 50、美 10、唯讀 31，背景資訊）；`test_article_connectors_parity.py` 僅對該工具名稱放寬例外並新增測試 | SRC-002 即時取得、「追加決定（Q-103／Q-104 調查後）」節；SRC-004 守門測試 |
| CFR-20 | 既有 `search_articles`／`get_article` 內部同時查 `articles.db` 與 `substack.db`，結果標示來源（出版名稱）並標示「僅預覽」 | SRC-002 決定4、市場標籤；SRC-001 Components 3 |
| CFR-21 | 第一版不做市場（台／美）標籤，只用「來源（出版名稱）」；新增台股作者＝設定檔多一行 | SRC-002 市場標籤 |
| CFR-22 | PO 須在當下對話親自確認的範圍：登入、鑰匙圈、消耗訂閱用量，以及安裝排程；RSS 輪詢（排程與即時取得）不另逐次確認 | SRC-001 Function／010補充；SRC-002「追加決定」節第1題 |
| CFR-23 | 舊庫唯讀相容；010 既有行為不得改變（011 使用獨立 substack.db，不需遷移 010 的 articles.db，見 data-model-note） | SRC-001 不要做；SRC-004 舊庫唯讀 |
| CFR-24 | 備份、健檢、日誌外洩掃描、回滾、部署、quickstart 等維運要求 | SRC-001 Components 6 |
| CFR-25 | 被擋（403／429）或異常即停手並通知，不重試轟炸；用條件請求（ETag）、設定逾時與間隔、通用 User-Agent、遵守 robots.txt | SRC-001 Function；SRC-003 §3、§6 |
| CFR-26 | 第一版須能對少數幾篇文章手動跑一次圖片轉寫以驗證流程與功能；手動、不排程、須 PO 當下確認（消耗訂閱額度）、不改 010 既有行為與 `articles.db`、011 文章預設不進 010 排程流水線；實作路徑規格階段判定（整理者對 PO 原話的解讀，待 PO 確認） | SRC-002「追加決定」節第2題 |
| CFR-27 | 即時取得時圖片同步下載；下載失敗的圖片由排程補下載 | SRC-002「追加決定」節第5題 |
| CFR-28 | 05:00～18:00 時窗只約束會消耗 AI agent token 的工作；RSS 抓取、即時取得、22:00 排程不受限；手動 token 工作是否受限待確認 | SRC-002「追加決定」節第4題 |
| CFR-29 | 新增寫入工具不得破壞 010「文章通道唯讀」守門（`article_tools` 唯讀開庫、不寫 `alphavibe.db`／`us_stocks.db` 的測試），須另證 | SRC-004；SRC-001 Components 3 |
| CFR-30 | 即時取得（含圖片下載）須在連接器逾時內回報進度或分段，避免逾時 | SRC-002「追加決定」節第5題（衍生）；SRC-004 |
| CFR-31 | 來源可信度標示：引用 Substack 作者意見須標明來源與「僅預覽」 | SRC-001 Components 3 |
| CFR-32 | 會消耗 AI agent token 的排程之間（含 010 的 23:40）間隔過短時，系統提醒 PO 修改（健檢／通知，不自動改排程）；數值待定 | SRC-002「追加決定」節第3題 |
| CFR-33 | 預覽比例異常提醒：全文（F）與僅預覽（P）的比例相較近期突然異常時，健檢須提醒 PO；只報現況與提醒，不自動處置（不改判、不停止匯入）；數值待規格 | SRC-002「追加決定（Q-103／Q-104 調查後）」節（風險）；SRC-005 |
| CFR-34 | 價值說明：依 2026-11-19 實測，現有兩個作者近 40 篇中約 35 篇為僅預覽；PO 已知悉並決定繼續 | SRC-002「追加決定（Q-103／Q-104 調查後）」節（PO 原話「結果正確，011要繼續。」）；SRC-005 |

## Candidate Actors And User Goals

- **PO（Stander）**：自己追蹤的 Substack 作者有新文章時，不用手動處理就能在 claude.ai 對話搜尋並引用；看到新文章時可立刻要求取得；用對話管理追蹤清單。（SRC-001 Purpose；SRC-002）
- **Claude（Mac Claude Code／claude.ai 連接器）**：搜尋、讀取、代 PO 修改設定檔、代 PO 觸發即時取得。（SRC-002 決定3、即時取得）
- **排程系統（launchd 每日 22:00）**：自動輪詢 RSS 並寫庫。（SRC-002 決定6）

## Candidate Success Criteria

- 追蹤作者在 feed 出現的新文章，最遲於下一次 22:00 排程後可在 claude.ai 搜尋到。（由 CFR-07、CFR-20 推得；具體量測待規格階段）
- 重複執行不產生重複文章；首次執行僅收 14 天內約 25 篇。（SRC-002 決定5）
- 搜尋結果每筆可辨識來源與是否僅預覽。（CFR-20）
- 011 文章零筆進入 010 排程轉寫流水線，且 010 既有測試與行為不變。（CFR-12、CFR-23）
- 排程執行不消耗模型額度。（CFR-13）

## Candidate Constraints And Assumptions

- 環境：macOS Apple Silicon Mac mini；`/usr/bin/python3` 3.9.6、標準庫、3.9 相容；launchd；正式環境 `AlphaVibe-prod`。（SRC-001 Target）
- RSS 每個 feed 只含最近 20 篇（固定上限、非時間窗）；歷史回補不能靠 RSS。（SRC-003 §2，[事實]實測）
- 付費文章公開 feed 只有預覽；無機器可讀的付費旗標；以內文結尾「Read more」連結推論僅預覽，為推論非站方保證，站方改版可能使判斷整批失準。（SRC-003 §2、SRC-005）
- 假設：個人低頻 RSS 輪詢風險低，但 ToS「copies or stores any significant portion」存全文有灰色地帶，屬 PO 風險判斷。（SRC-003 §4 [推論]）
- 文章僅供 PO 個人本機參考，不轉發、不公開。（SRC-001 Target；SRC-002 決定1）
- 日誌／通知／回報不得含帳密、cookie、token、全文；標題僅可出現在 Telegram 通知與資料庫內容。（SRC-001 安全；SRC-002 決定9）
- 對外請求用通用 User-Agent，不放 PO email 或個資。（SRC-001 Function）
- 本分支以 `function/alphavibe` 為基底（偏離 develop 預設，已向 PO 說明）。（SRC-002 環境事實）

## Candidate Error Or Failure Behavior

- feed 回 403／429：停手、告警、不重試轟炸。（SRC-003 §3、§6；SRC-001）
- feed 尚未出現剛發的文章：即時取得回報稍後再試。（SRC-002 即時取得）
- 同一作者過於頻繁手動輪詢：以最小間隔守衛拒絕。（SRC-002 即時取得）
- 圖片下載失敗：文章照存、記缺圖，由排程補下載（CFR-27）；硬碟空間不足等細節：raw 未明述，見 GAP。

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | SRC-001, SRC-002 | Conflict | PO prompt 要求日誌／通知／回報不得含標題；PO 決定 9 要求通知含作者＋標題 | Resolved | 以 SRC-002 為準：通知可含、日誌與錯誤訊息不含（clarification Q-009） |
| GAP-002 | SRC-001, SRC-002 | Conflict | prompt 列「RSS 為主、Gmail 通知信為輔」與「可共用 articles.db」；決定為 RSS 唯一、獨立庫 | Resolved | 以 SRC-002 為準 |
| GAP-003 | SRC-001, SRC-002 | Unclear | 「每次真實對外執行由 PO 在對話確認」與「每日 22:00 無人值守排程」如何並存 | Resolved | 追加決定第1題：還原為登入／鑰匙圈／消耗用量須親自確認，安裝排程須親自確認，RSS 輪詢不逐次確認（Q-101） |
| GAP-004 | SRC-002, SRC-004 | Conflict | 「需要時轉寫指定圖片，重用 010 流水線」與「不動 `articles.db`」：流水線讀取的是 `articles.db` 的圖片資料 | Partially Resolved | 追加決定第2題：第一版手動少量轉寫、不改 010；實作路徑與 PO 解讀確認見 Q-115 |
| GAP-005 | SRC-002, SRC-004 | Unclear | `get_article` 目前以整數 article_id 識別；兩庫並查時 011 文章如何識別 | Open | 見 Q-108（設計層，非阻擋） |
| GAP-006 | SRC-002 | Unclear | 文章發布後內容被作者修改（同 guid、內容不同）時是否更新已存內容 | Open | 見 Q-109 |
| GAP-007 | SRC-003 §2 | Unclear | feed 固定 20 篇；若兩次輪詢之間發文超過 20 篇會漏文（低頻作者機率低） | Open | 見 Q-110，非阻擋 |
| GAP-008 | SRC-001 | Unclear | 備份與健檢是否納入 `substack.db`／圖片目錄 | Open | 見 Q-111 |
