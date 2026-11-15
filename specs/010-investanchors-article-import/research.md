# Research: 定錨產業筆記文章自動匯入

**Date**: 2026-11-15 ｜ 格式：Decision / Rationale / Alternatives。標 **[PROBE]** 者無法在沒有 PO 帳號的情況下
查證，須在 PO 的 Mac 上執行 `article_probe.py`（R0）後回填；設計已寫成對每種結果都成立。

## R0. 需在 PO 的 Mac 探查的事項（spec Assumptions 末條，plan 第一步）

| # | 未知 | 會影響什麼 | 設計對各結果的因應 |
|---|---|---|---|
| P1 | 「總覽」清單是否分頁／無限捲動、總篇數 | 回補批次數、核對方式、清單讀幾頁 | 讀取以「翻頁至沒有新 ID 為止」為通則；若無限捲動，scraper 改以捲動＋ID 去重，仍受單次篇數上限約束 |
| P2 | 登入狀態有效期、**伺服器端登出機制**（按鈕／endpoint） | FR-008 是否做得到；伺服器端 session 是否被釋放 | **伺服器端登出是必要步驟**，`context.close()` 只清本機 cookie、不算數。探查找不到登出機制 → **停止並回報 PO，不進入實作**；找到則以「再訪登入頁得到登入表單」驗證（SC-004） |
| P2a | 新登入是否會把 PO 其他裝置踢下線 | 排程登入是否干擾 PO 手機／電腦使用 | **探查時 PO 只保留手機一台登入（電腦瀏覽器先登出）**；探查瀏覽器算第二台，合計不超過網站「同帳號最多兩台」的上限；探查結束後請 PO 確認手機是否仍在線 |
| P2b | 網站如何計算「上線裝置」：登出後名額是否**立即釋放** | 兩台上限（FR-008）與排程時段安排 | **被動結論，不做任何額外登入測試**（主動用第三個瀏覽器登入本身就可能造成三台同時上線）：以「伺服器端登出已驗證」為依據；若無法確認釋放行為，每日登入次數與時段須更保守，並回報 PO 重新取捨 |
| P3 | 開啟文章是否改變已讀（細體／粗體） | FR-009 例外是否如預期；是否可用已讀狀態輔助 | 僅確認，不依賴已讀狀態判斷新舊（spec：身分只靠文章 ID） |
| P4 | 通知信連結是否直指 `/user/vip_contents/<ID>`（或是追蹤轉址） | 能否從信直接取得 ID | **已查明（見實測回填）：是追蹤轉址，不可跟隨；信只當觸發，不取文章 ID**（R1） |
| P5 | `lv=` 參數意義、清單日期列結構、公告標題格式 | 清單解析、【公告】略過 | 解析器以標題前綴 `【公告】` 判斷，不依賴 `lv` |
| P6 | 文章頁 DOM：內文容器、表格圖與一般圖的區分 | 取全文、判斷哪些圖要轉寫 | 見 R5：不可靠區分時，**所有內文圖都送轉寫**，由模型回報「非表格」 |
| P7 | 是否有同一 IP／行為頻率偵測、登入頁是否有隱藏欄位或 CSRF token | 封鎖偵測規則 | 先用起始值（5 篇／每日 1 次／30–90 秒）並再保守 |

**探查規約（保護帳號，硬性）**：只在 PO 在場、一次性執行；**執行前 PO 的電腦瀏覽器必須已登出、只保留手機一台登入**（工具要求加上 `--confirm-one-device-only` 才肯執行）；總計登入 1 次、開啟清單 ≤3 頁、開啟文章 ≤2 篇；
全程單一 context，結束即登出；輸出只寫結構事實（DOM 選擇器、頁數、有無分頁）到 `poc/data/articles_probe/`
（gitignore 目錄，**不存全文、不存 cookie**）。工具規格見 contracts/cli.md §2。

### R0 實測回填（2026-11-15，兩次真實探查；PO 在場、手機一台登入）

探查輸出只含結構事實（`poc/data/articles_probe/`，gitignore，未提交）。兩次各登入 1 次、清單 3 頁、開 2 篇，
伺服器端登出皆驗證成功，未被擋。樣本：清單 31 筆不重複項、2 篇有圖文章＋2 篇無圖文章。

| # | 結果（事實） | 對設計的影響 |
|---|---|---|
| P1 | `?page=N` 連結分頁；第 1 頁 16 筆、第 2 頁 20 筆；**每頁頂端有 5 筆置頂項重複出現**（1 筆公告＋4 筆一般文章）；清單位置兩次探查不同（第一次實際開的前兩篇非公告，這次排第 6、10 位） | 清單解析要跨頁去重、不依賴位置、以 ID 為準（R11） |
| P2 | 伺服器端登出：下拉選單內 `a[href=/user/session][data-method=delete]`（不可見）；第 1 種方式（展開選單再點）即驗證成功；登入後落在清單頁；`https`；「記住我」預設未勾 | 登出流程沿用已測的四段式（R3）；登入時維持不勾「記住我」 |
| P2a | PO 回報探查結束後**手機仍在登入**：手機一台＋探查瀏覽器一台（共 2 台）登入再登出，不影響手機登入 | 手機一台＋排程一台可行；PO 同時在電腦開定錨（第 3 台）仍是禁忌（R8 睡眠補跑風險） |
| P2b | 維持被動結論（以伺服器端登出已驗證為依據），未做額外登入測試 | 不變 |
| P3 | **開啟文章會把未讀（粗體）改成已讀**（實測：未讀文章開啟後變一般字體） | FR-009 的已讀例外成立；排程匯入會替 PO 把文章標已讀（PO 已接受，Q-004） |
| P4 | 近 30 天找到 12 封通知信（約每週 2.8 封；寄件者吻合、有 HTML），每封恰好 3 個站內連結，**全部是 `investanchors.com/c/<長 token>` 的點擊追蹤轉址**（每位收件人不同）：無查詢參數、無文章直連、信中長數字（≥13 位）0 個，**信中取不到文章 ID**。**篇數落差**：視窗 2026-10-16～11-15 信 12 封、文章 24 篇（置頂文以 ID 建立日計）。**PO 表示定錨每篇文章都會寄信；實測只搜到約一半，原因未驗證**（可能 PO 已刪信、信在垃圾桶或另有寄件地址、或搜尋條件）。連續信件最大間隔 4 天（30 天樣本；樣本小） | 信只當觸發：不取 ID、不跟隨連結、不解碼 token、不做標題比對；每次登入讀清單並抓所有未入庫 ID（R1）；漏搜部分信只延後觸發、不漏文章 |
| P5 | 總覽清單日期格式皆為完整年月日；只抓到 1 個 `lv=` 連結（「我的最愛」），其餘分頁不是此形式；公告標題以「【公告】」開頭，1 筆 | `lv` 不用；公告以標題前綴略過（不變） |
| P6 | 內文容器 `div#inves_content.investanchors_content.investanchors_content_research`；**無 h1**，標題選擇器未找到（`span.brand-title` 是網站品牌）；發布時間在 `span.post_date`，形態「· ####-##-## ##:##」；有留言區；正文 3177～10053 字。**內文圖片：2 篇有圖文章各只有 1 張**（PNG，位於 `<p>` 內、不在 table 內，已載入、無延遲載入屬性），尺寸 2190×5195（長圖）與 1653×993；路徑形態 `/uploads/image/file/#/<Basic｜Advanced…>-#.png`（同站）；**不帶 cookie 直接下載回 200 image/png**。另 2 篇無圖文章（內文容器內 0 張圖）。內文容器內無 HTML table（第一次回報的「1 個 table」是整頁計數，已更正） | 表格是圖片的假設成立，但**一篇可能只有 1 張很高的長圖**，轉寫前要切片（R5）；標題取自清單連結文字（R11）；圖片下載不需登入狀態但仍須間隔 |
| P7 | 無封鎖跡象；登入頁有登入／註冊兩個表單（測試以第一個可見密碼欄位所屬 form 登入） | 登入表單限定範圍的防呆保留 |
| P8 | **文章 ID 前 13 位＝epoch 毫秒（建立時間）**：公告 `1612580077558`＝2021-02-06（與清單日期吻合）；其餘 30 筆 14 位數 ID 的建立時間皆早於或等於清單日期，差 0～11 天（最大 11 天）；ID 與清單日期**不單調**（清單日期是發布日，不是建立日）。**4 筆置頂一般文章的清單日期顯示 2021-02-06，但 ID 時間是 2026-11-06～08（近期文章）**：清單日期對置頂項不可靠。去除 5 筆置頂後：第 1 頁 11 筆（2026-10-30～11-15）、第 2 頁 15 筆（2026-09-30～10-30），2 頁 26 筆涵蓋 47 天、**尚未到半年邊界**；外推約 101 篇／半年（0.55 篇／天） | 半年截止改用 **ID 建立時間**，不用清單日期（R11）；回補約 100 篇、每天 5 篇約 20 天 |

**重要限制**：上述 ID 規律由 31 筆樣本觀察得到，網站並未保證；實作必須有防呆（R11）。通知信 12 封／30 天與同期清單約 24 篇的落差已用「只比日期」的免登入檢視確認為真實存在（不是計算方式造成），
但**原因未驗證**（PO 表示每篇都寄；可能 PO 已刪信、信在垃圾桶或另有寄件地址）；設計不受影響（R1）。

## R1. 觸發與去重

**Decision**: 通知信**只當觸發**：**不從信取文章 ID、不跟隨信中連結**（`/c/<token>` 是每位收件人的點擊追蹤轉址，
跟隨會留下點擊紀錄）、**不解碼 token、不做標題比對**。三種觸發：(a) Gmail 有「未處理的定錨新信」（以 Message-ID
判斷）；(b) 每週核對日（週日，且上次核對 ≥6 天前，見 R12）；(c) 回補未完成。**每次登入（不論由何者觸發）都讀清單
第 1 頁，必要時往後翻到「一頁內非置頂項全部已入庫」為止；凡未入庫的文章 ID 都抓，不論有無對應通知信**，仍受每次
5 篇上限；**新文章優先於回補**。文章身分只看文章 ID（`/user/vip_contents/<數字>`，14 位數）；信件 Message-ID 只用來記
「這封信已看過」，不是文章身分（009 教訓：同一內容換來源會被當新資料）。
**Rationale**: 滿足 FR-003／FR-006／SC-003：沒有新信且非核對日且回補完成 → 登入次數 0。實測（P4）：信中連結全是
追蹤轉址、取不到 ID；PO 表示每篇文章都會寄信，但近 30 天只搜到 12 封（同期清單約 24 篇），**原因未驗證**。新設計對此不敏感：
每次登入都抓清單上所有未入庫文章，漏搜部分信只會**延後觸發**，不會漏文章。
**Alternatives**: 從信取 ID（不可行，連結是追蹤轉址）；標題比對（未驗證、也不必要）；解碼 token（含收件人追蹤資訊，不做）；
只靠清單輪詢（每天登入，違反低頻）；以信件為身分（漏信或多信即重複／漏抓）。

## R2. 取信

**Decision**: 新檔 `investanchors_mailbox.py`，沿用 `statement_mailbox.py` 的骨架：`IMAP4_SSL imap.gmail.com`、
`select(readonly=True)`、`BODY.PEEK[]`（信不會被標已讀）、`X-GM-RAW "from:postmaster@mailer.investanchors.com
newer_than:Nd"`。**只取 Message-ID 與寄達時間**（用來判斷「有沒有未處理的新信」）；**不解析、不記錄信中的連結與標題**；寄件者與天數參數化，不改 009 的常數。Gmail 位址與
app password **沿用既有鑰匙圈項目** `stnd-statement-import` 的 `gmail-address`／`gmail-app-password`。
**Rationale**: 既有、已上線驗證（009）；唯讀不改信箱狀態。
**待觀察（上線驗證期）**：搜尋條件目前是單一寄件者、「所有郵件」（不含垃圾桶與垃圾信）；實測只搜到約一半的信（PO 表示每篇都寄，原因未驗證）。因新設計每次登入都抓清單上所有未入庫文章，漏掉部分信只延後觸發、不會漏文章，**不需要為此擴大信箱讀取範圍**；上線驗證期觀察「文章進庫時間 vs 發布時間」即可。
**Alternatives**: 把 009 的 `fetch_statements` 改成泛用（動到已上線功能且含 PDF 專用邏輯，風險不值得）；Gmail OAuth（需新授權流程）。

## R3. 瀏覽器抓取與登入

**Decision**: 新 `scraper/investanchors_scraper.js`（Node/Playwright）；Python 以 `subprocess.Popen` 傳入 JSON
指令、讀 JSONL 結果，與 `flight_scraper.js` 同介面慣例（`result`／`summary{blocked}` 行）。**不使用**
`launchPersistentContext`／`storageState`：每次全新 context，登入狀態不落地（免 cookie 檔視同密碼的風險）。
**但關閉 context 只清掉本機 cookie，網站伺服器端的登入狀態仍在，仍可能被算成一台上線裝置**，所以不能
當作滿足 FR-008：**伺服器端登出是必要步驟**（`finally` 中先走網站登出、驗證成功，再關 context；與
contracts/cli.md §4 一致）。登出失敗＝該次標記 `logged_out=0`、Telegram 通知，且下一次執行前先重試登出。帳密由 Python 從鑰匙圈讀出後**經 stdin 傳給子行程**，不放命令列參數與環境變數。
防自動化旗標、zh-TW、Asia/Taipei、隨機延遲 `rnd()`、`BLOCK_URL_RE` 軟／硬封鎖偵測沿用 flight scraper 寫法
（`flight_scraper.js:29,72,186-196,207`）。**登入／登出／fill 流程 repo 內沒有先例，須新寫**。
**實測（2026-11-15）**：登入欄位為電子郵件＋密碼（「記住我」預設未勾，維持不勾）；登入後落在
`/user/vip_contents/investanchors_index`；登出為下拉選單內的 `a[href=/user/session][data-method=delete]`，
以四段式的第 (a) 段「展開選單再點」即驗證成功。文章頁只取三樣：內文容器 `div#inves_content`、發布時間
`span.post_date`、內文容器內的圖片；**不依賴文章頁的標題選擇器**（無 h1），標題取自清單連結文字。
**Rationale**: 全新 context 避免本機留下可重用的登入憑證；與伺服器端登出**合併**才滿足「網站端不留登入狀態」。
代價是每次要重新登入——但本功能本就一天最多 1 次。
**Alternatives**: 持久 profile（少登入但會留登入、可能占裝置名額，spec 明確取捨為不超限優先）；純 HTTP
requests 登入（Python 無 requests 依賴、且不易模擬瀏覽器行為；未排除，視 P7 探查結果再議）。

## R4. 低頻上限、退避、重試

**Decision**: 常數寫在 `investanchors_import.py` 頂端：`MAX_ARTICLES_PER_RUN=5`、`MAX_LOGINS_PER_DAY=1`（PO 決定 2026-11-15：一天一次，見 R8）、
`DELAY_RANGE=(30,90)` 秒、`MAX_ATTEMPTS_PER_ARTICLE=3`、`BLOCK_BACKOFF_DAYS=1`。執行前先查 `import_runs`
表：當日登入次數已達上限、或 `blocked_until` 未到，**直接結束且不登入**。被擋跡象（連續 2 次逾時、
導向登入頁、非預期頁面）→ 寫 `blocked_until = now+1 天`＋Telegram。單篇失敗：`attempts += 1`，同次不重試；
達 3 → `abandoned`＋通知。**放寬任一常數須 PO 同意**（寫入 quickstart 與常數註解）。
**Rationale**: FR-007／FR-012／FR-015。狀態存 db 而非檔案，沿用 `flight_browser_usage.json` 的精神但可查詢。

## R5. 表格圖轉寫

**Decision**: 新 `article_transcribe.py`，用 `urllib` 呼叫視覺模型 HTTP API（repo 內**沒有任何 LLM 呼叫先例**）。
**不裝 SDK 的理由**：排程跑系統 `/usr/bin/python3`（3.9.6）、僅標準庫（requirements.txt 只有 yfinance），
新增套件會讓每次部署與 launchd 環境多一個失敗點。
起始模型：**`claude-haiku-5-5`**（不加日期後綴；PO 決定「成本最低且抽查合格」，據主對話提供：輸入 0.10／輸出
0.50 美元每百萬 token，Haiku 4.5 為 1／5）；**模型 ID 寫成可調的模組常數 `TRANSCRIBE_MODEL`**，升級或換模型
只改一處，並寫入 `article_image.transcribed_model` 以便辨識重轉對象。**此 ID 與價格我無法在本環境獨立查證
（我的環境清單只列到 Haiku 4.5），實作第一步須對照官方文件確認 ID 存在可用。**
金鑰存鑰匙圈 `stnd-investanchors`／`vision-api-key`，缺金鑰或額度不足 → 該圖標記 `untranscribed`，
文章照存。提示詞要求：只轉寫圖中可見數字與文字、看不清楚的格子寫 `?`、判斷「是否為表格」。
**資料庫只存轉寫內容，不存任何「機器轉寫」標示或路徑**（否則 `LIKE` 搜尋會被標示用字／路徑字串命中所有
文章）；標示在輸出層（`get_article`／搜尋片段）加上。
**實作時須對照官方文件確認的點**：(1) 該模型預設會思考，`max_tokens` 要留足；(2) **不要送非預設的
temperature／top_p／top_k**（會被拒）；(3) `{is_table, text}` 用**結構化輸出**，不自行解析自由文字；
(4) 回應 `stop_reason` 為 `refusal` 或 `max_tokens` 時，該圖一律標 `untranscribed`，不採用任何部分輸出。
**圖片形態與切片（探查實測）**：一篇可能**只有 1 張內文圖**，且可能是很高的長圖（實測 2190×5195）；圖片網址不帶
cookie 即可下載（200 image/png），但網址要從登入後的文章頁取得。下載圖片**不算登入次數**，可在登出後由 Python
以 HTTP 下載，但仍須隨機間隔（建議 5～15 秒／張）。轉寫前的**切片原則**（單張尺寸與 token 上限實作時對照官方
文件確認）：(1) 依高度垂直切片，每片寬度保持原寬、高度約為寬度的 0.6～0.8 倍；(2) **相鄰切片重疊至少 15%**
（且不少於 200px），切點優先落在整列近乎同色的橫向空白帶，避免切斷文字列或表格列；(3) 每片的提示詞附上
「上一片轉寫出的表頭與最後 2 列」作為上下文，並要求若本片頂端的列已在上下文出現則略過，避免跨片的列被切斷
或重複；(4) 轉寫後依重疊區的列文字合併去重；(5) **切片數上限 8 片**，超過則該圖標 `untranscribed`（不得為了
湊進上限而縮小圖片）；(6) 原圖完整保留，切片只用於轉寫、不入庫。抽查樣本（10 張）須包含至少 1 張長圖。
**轉寫啟用開關（預設關閉）**：轉寫由 `articles.db` 的 `setting.transcribe_enabled` 明確控制，**不用鑰匙圈有沒有金鑰當開關**——否則 PO 一存金鑰，
夜間排程就會在抽查通過前開始轉寫。關閉時圖片照常下載、標 `untranscribed`、不呼叫模型 API。上線流程：部署（開關關閉）→ 回補累積圖片
（≥10 張且含長圖）→ PO 存金鑰 → `--transcribe-sample 10`（只轉寫抽樣、不寫 DB）→ PO 逐格確認 → 通過才 `--enable-transcription` →
`--retranscribe` 補轉積壓；不通過則升級模型再抽 10 張。
**上線前抽查（FR-018／SC-007；PO 決定 2026-11-15）**：從 P6 取得的真實表格抽 **10 張**，轉寫結果由 **PO 本人逐格
確認**，PO 認可才採用目前模型；**PO 不認可則升級模型、再抽 10 張**（逐級升）。**不設百分比門檻**。補轉寫：`investanchors_import.py --retranscribe` 只讀本機
圖片檔、不登入網站（FR-017）。
**Rationale**: 既有慣例「圖交給對話中的 Claude 讀」（`us_stock_mcp_server.py:66-69`）不適用於無人值守排程，
故必須新增，這是本功能唯一的全新外部依賴與費用來源。
**Alternatives**: 本機 OCR（tesseract 對中文財測表的數字準確度未驗證；備選，若 API 成本或隱私不接受再評）；
只存圖不轉寫（違反 FR-016，PO 明確要求表格數字進 MVP）。**表格圖送第三方模型 API：PO 已於 2026-11-14 同意**
（需求基線 Q-016）；送出的只有表格圖本身，用途為 PO 個人使用的資料處理。

### T033 官方文件查證（2026-11-15）

> 方法：WebFetch 官方文件（platform.claude.com）＋ claude-api skill。**未呼叫任何需金鑰的 API。**
> 注意：claude-api skill 內建模型表快取於 2026-09-25，**未列出** Haiku 5.5（最新只到 Haiku 4.5）；
> 官方文件（2026-11-15 抓取）則明確列出，兩者並列如下，以官方文件為準（skill 表只是過期，非否定）。

1. **模型 ID**：`claude-haiku-5-5` **存在**（2026-10-07 發布，固定 ID、無日期後綴、無別名），文字＋圖片輸入、
   1M context、128K 輸出、預設 effort `medium`、思考為 adaptive。價格：輸入 $0.10／輸出 $0.50 每百萬 token
   （**提示 ≤100K token**；>100K 則 $0.50／$2.50），與 R5 數字相符，但 R5 未提「>100K 提示漲價」（切片後
   單次請求遠低於 100K，不影響）。**tokenizer 比 Haiku 4.5 多約 30% token。** Priority Tier 不支援。
   https://platform.claude.com/docs/en/models/haiku-5-5/overview ／
   https://platform.claude.com/docs/en/models/overview ／
   https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide
2. **圖片格式**：user content 放 `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"<base64，無換行>"}}`，
   支援 `image/jpeg`、`image/png`、`image/gif`、`image/webp`（GIF 只取第一幀）；圖片區塊放文字區塊之前效果較佳（官方範例順序）。
   https://platform.claude.com/docs/en/build-with-claude/vision
3. **尺寸／大小／token**：單張上限 8000×8000 px、**10 MB（base64 後）**（Claude API）；單請求 >20 張圖時每張
   改限 ≤3000 px（本功能每請求 1 張，不觸發）。Haiku 5.5 屬「高解析度層」：**長邊 >2,576 px 或 >4,784 視覺 token
   就自動等比縮小**（不報錯；除非在圖片區塊設 `transformations`／`"oversized_image":"error"` 才改成報錯）。
   token ＝ `⌈寬/28⌉ × ⌈高/28⌉`。**對 R5 的影響**：2190×5195 的長圖若整張送，會被縮到長邊 2576（寬約 1086），
   文字會變小失真——**切片仍必要**；切片後每片寬度 2190 ≤2576 不被縮，每片高 ≈ 寬×0.6～0.8 ≈ 1300～1750 px，
   token ＝ 79×(47～63) ≈ 3,700～4,900，**約貼近 4,784 上限**，建議片高 ≤ 1,700 px（約 4,700 token）以免被縮，
   T035 規劃時以「寬 ≤2576、`⌈寬/28⌉×⌈高/28⌉` ≤ 4,784」為硬條件。檔案 base64 後 >10 MB 要先降（PNG 切片通常遠小於此）。
   https://platform.claude.com/docs/en/build-with-claude/vision
4. **結構化輸出**：兩種都可行，**建議 `output_config.format`（官方 structured outputs，GA、不需 beta header）**：
   body 加 `"output_config":{"format":{"type":"json_schema","schema":{"type":"object","properties":{"is_table":{"type":"boolean"},"text":{"type":"string"}},"required":["is_table","text"],"additionalProperties":false}}}`，
   回應在 `content` 的 `text` 區塊內是 JSON 字串，`json.loads` 即可；**不能用 `output_format`（已棄用）**。
   理由：請求最短、不需定義工具與解析 `tool_use`、與思考預設開啟相容性最好。限制：schema 不支援 `minLength` 等數值／字串約束、
   `additionalProperties` 只能 `false`。備案：forced `tool_choice`＋`strict:true`——**Haiku 5.5 接受強制 tool_choice**
   （Sonnet 5.5／Opus 5.5 不接受），但強制呼叫時**不會有 thinking 區塊**；官方另警告「思考關閉＋`output_config.format`＋需要自己的工具」才會漏呼叫工具，
   本功能無自有工具，不適用。**未驗證**：官方文件未明述 `max_tokens`／`refusal` 時輸出是否一定符合 schema——程式必須自行
   防禦（先查 `stop_reason`，再 `json.loads` 並驗證有 `is_table`、`text` 兩鍵，失敗→`untranscribed`）。
   https://platform.claude.com/docs/en/build-with-claude/structured-outputs ／
   https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5#json-output-with-your-own-tools
5. **預設思考與 max_tokens**：**adaptive 思考預設開啟**，思考 token **計入 `max_tokens`**，過小會在思考區塊後、文字前就
   `stop_reason:"max_tokens"`；預設 thinking 區塊的 `thinking` 欄位為空字串（只有 signature）。`thinking.type:"enabled"`＋`budget_tokens`
   回 400。選項：省略 `thinking`（adaptive，官方建議）並調低 `output_config.effort`（`low` 最省），或 `thinking:{"type":"disabled"}`（Haiku 5.5 接受，
   但僅限 effort low/medium/high，`xhigh`／`max` 回 400；官方提醒關閉思考時較易出現推理文字漏進回覆）。
   **建議**：`thinking` 省略、`output_config.effort:"low"`（轉寫是機械性抄錄，不需深度推理；實測抽查若準確度不足再升 `medium`），
   **`max_tokens` 先設 16000**（一片表格約數千輸出 token，加思考餘裕；可調常數，上限 128K）。**非串流請求 16000 在 SDK 逾時限制內；
   urllib 自行設 timeout（建議 ≥120 秒）。**
   https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide#configure-thinking ／
   https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5#use-effort-to-control-thinking
6. **sampling 參數**：Haiku 5.5 **明確要求省略 `temperature`／`top_p`／`top_k`**。另外，**API 版本 `2026-10-21` 起，這三個參數在所有模型上
   一律回 400（連預設值也是）**。→ 請求絕不帶這三個欄位（與 R5 假設相符，且比 R5 更嚴格）。
   https://platform.claude.com/docs/en/models/haiku-5-5/overview ／ https://platform.claude.com/docs/en/api/versioning ／
   https://platform.claude.com/docs/en/api/migration-2026-10-21
7. **stop_reason**：`refusal`＝HTTP 200（非錯誤），`stop_reason:"refusal"`，`stop_details`（`type`／`category`／`explanation`）有值，
   category 例：`cyber`／`frontier_llm`／`bio`／`general_harms`；**Haiku 5.5 沒有 server-side fallback**，同請求重送通常再被拒——
   程式處理：標 `untranscribed`、不重送、不採用任何部分輸出（與 R5 (4) 相符）。`max_tokens`＝回應被截斷（`stop_details` 為 null），
   官方建議「提高 max_tokens 或續寫」；本功能依 R5 (4) 一律標 `untranscribed`（可在日誌記一筆 stop_reason 供日後調高常數）。
   另 `stop_details` 只在 refusal 時非 null，讀取前要判斷。
   https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons ／
   https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5#safeguard-refusals
8. **HTTP header 與錯誤碼**：POST `https://api.anthropic.com/v1/messages`；`content-type: application/json`（必）、`anthropic-version`（必）、
   金鑰 `x-api-key`（官方標為「legacy fallback，仍支援」）或 `Authorization: Bearer <key>`（新 SDK 預設）。**`anthropic-version` 現行文件值為
   `2026-10-21`（官方建議用最新）**；舊值 `2023-06-01` 文件稱為「可保留」（migration 頁："keep that request on 2023-06-01"），**未見停用日期**。
   **建議 T036 手寫請求送 `2026-10-21`＋`x-api-key`**（不送 sampling 參數故無相容問題）；`anthropic-version` 做成模組常數。
   **未驗證**：未用真實金鑰確認 `x-api-key` 搭配 `2026-10-21` 的實際回應（本任務禁止）——T036 的假 server 測試無法證明此點，
   PO 存金鑰後 `--transcribe-sample` 是第一次真實驗證。錯誤 JSON 形態：`{"type":"error","error":{"type":"<類型>","message":"..."},"request_id":"req_..."}`。
   錯誤碼：400 `invalid_request_error`（**達到組織／工作區自訂花費上限也回 400**）、401 `authentication_error`（金鑰錯誤／撤銷／過期）、
   402 `billing_error`、403 `permission_error`、413 `request_too_large`（Messages 上限 128 MB）、**429 `rate_limit_error`（限流或用量層級月花費上限；
   花費上限型 429 沒有 `retry-after`，會持續失敗）**、500 `api_error`、504 `timeout_error`、**529 `overloaded_error`**。
   → T036 處理：401／402／403／400（含額度）→ 該圖 `untranscribed` 且**本次執行不再重試後續圖**（避免整批重複失敗，由實作決定）；429／500／529／504
   → 可退避重試 ≤2 次後標 `untranscribed`；所有錯誤訊息／日誌**不得含金鑰**（`request_id` 可記）。
   https://platform.claude.com/docs/en/api/overview ／ https://platform.claude.com/docs/en/api/errors ／ https://platform.claude.com/docs/en/api/versioning

**與 R5 假設比對（無阻擋項，結論：全部成立，另有 4 項需補入實作）**：
- 成立：模型 ID 存在可用、支援圖片；預設思考且吃 `max_tokens`；不可送 temperature／top_p／top_k；結構化輸出（`output_config.format`）；`refusal`／`max_tokens` 處理。
- 補充 A：R5 價格「0.10／0.50」僅適用提示 ≤100K token（切片後不影響）；tokenizer 約多 30% token。
- 補充 B：圖片在 Haiku 5.5 上限為長邊 2,576 px／4,784 視覺 token，超過**自動縮小不報錯**——T035 切片須以此為硬條件（片高 ≤ ~1,700 px @寬 2190）。
- 補充 C：`anthropic-version` 現行 `2026-10-21`；該版起 sampling 三參數一律 400。
- 補充 D：結構化輸出在 `max_tokens`／`refusal` 時是否仍符 schema 官方未明述，程式必須自行驗證 JSON。

### T034 切片實作方式決定（2026-11-15）

**選 (a) Playwright canvas（Node，沿用既有依賴與 `findChromium()`）；不新增 Python 套件。**
實測（本機既有 Chromium、真實那張 1653×993 PNG，只做本機步驟）：以 `data:` URL 載入 `Image` → `canvas.getImageData`
可讀像素、可 `drawImage` 裁切並 `toDataURL("image/png")` 輸出，**不被 tainted**。分工：Python 端（`article_image_tiles.py`，
標準庫）用 PNG IHDR／JPEG SOF 讀尺寸、判斷長圖、規劃切點；Node 腳本（`scraper/image_tiler.js`）負責偵測近乎同色的橫向空白帶
並輸出切片；不啟動任何網站存取。(b) `sips` 讀不了像素、(c) Pillow 需 PO 同意，皆不採用。
**待主對話確認的相依設計問題**：T033 查得 Haiku 5.5 對長邊 >2,576 px 或 >4,784 視覺 token 會自動縮小，
故切片硬條件為「寬 ≤2576 且 ⌈寬/28⌉×⌈高/28⌉ ≤4784」。寬 2190 時片高須 ≤約 1,700 px，而 R5 原訂「片高約寬度 0.6～0.8 倍」
上緣（約 1,750 px）會略超；擬改為「片高 = min(寬×0.8, 依上式算出的上限)」，重疊 ≥15% 且 ≥200 px、片數上限 8 不變。

#### 切片規則（T035 定案）

實作：`poc/kb-mcp/article_image_tiles.py`（Python 標準庫：尺寸讀取、規劃、位元組檢查、合併）＋
`poc/kb-mcp/scraper/image_tiler.js`（Playwright canvas：空白帶偵測、縮圖、切片輸出；不連網）。
所有限制常數集中在 `article_image_tiles.py` 頂部，來源為 T033 查到的官方文件
（https://platform.claude.com/docs/en/build-with-claude/vision，查證日期 2026-11-15），之後改限制只改該處：
`MAX_EDGE_PX=2576`、`PATCH_PX=28`、`MAX_VISION_TOKENS=4784`、`MAX_IMAGE_SIDE_PX=8000`、
`MAX_BASE64_BYTES=10 MB（取保守的 10^7）`、`MAX_TILES=8`。

1. **長圖判定**：高/寬 ≥1.5 且高 ≥2000 px。長圖，或「整張送會被模型縮小」（寬或長邊 >2576，或視覺 token ⌈寬/28⌉×⌈高/28⌉ >4784）者要切片；
   非長圖且滿足上述硬條件的短圖**不切、整張原檔送出**（不經瀏覽器）。
2. **寬度 >2576**：先等比縮到寬 2576（高度四捨五入），回傳 `resized=True`（「已縮圖」）再切片；縮圖後仍超過 8 片 → `untranscribed`。
   不得因寬度超限就整張送出（寬度超限但很矮的圖＝縮成寬 2576 的單片送出，仍標 resized）。
3. **片高** ＝ min(寬×0.8, 片高上限)；片高上限＝⌊4784 ÷ ⌈寬/28⌉⌋×28，且 ≤2576。寬 2190 → 1680 px。
4. **重疊**：相鄰切片重疊 ≥ max(⌈片高上限×15%⌉, 200 px)（寬 2190 → 252 px）。
5. **切點**：Node 端把「整列 ≥99% 的像素與該列主色相近（容差 10）」的連續列（≥4 列）視為空白帶（容許表格直向格線）。
   片底優先落在片高 60%～100% 之內最靠後的空白帶中點；下一片片頂在「片底−重疊」往上 1 倍重疊的視窗內優先取空白帶；
   視窗內沒有空白帶才退回硬切（此時重疊保證文字列完整出現在其中一片）。2190×5195 → 4 片。
6. **片數上限 8**：超過 → 該圖 `untranscribed`、原圖保留（不縮小湊數）；片高上限 ≤重疊下限＋1（極窄圖）亦同。
7. **位元組檢查**：`check_tile_bytes(n)`：base64 後（4×⌈n/3⌉）>10 MB → 該圖 `untranscribed`；`open_tiles()` 對每片（及整張送出的原檔）都已檢查。
8. **原圖完整保留**；切片只寫在 `tempfile` 暫存目錄，`TileSet` 離開 context（或 `cleanup()`）即清除，不入庫。預期內的失敗
   （格式不明、片數過多、位元組過大、瀏覽器缺失）一律回 `status="untranscribed"`＋`reason`，不丟例外。
9. **給 T036**：`open_tiles(路徑)` → `TileSet(status, reason, resized, plan, iter_tile_bytes())` →（逐片轉寫）→ `merge_transcripts(各片文字)`，
   合併依「前文最後 k 行＝下一片最前 k 行」去重（忽略空白；只重疊 1 行時該行需 ≥6 個非空白字元）。

## R6. 搜尋實作（實測推翻了原先的 FTS5 假設）

**Decision**: **不用 FTS5**，用 `LIKE` 掃描：查詢字串以空白切成多個關鍵字，皆需出現（AND），搜尋範圍＝
標題＋全文＋所有圖片轉寫文字；片段取第一個命中處前後各約 60 字。
**Rationale（2026-11-15 在這台機器實測，Python 3.9.6／SQLite 3.51.0）**：FTS5 `trigram` tokenizer 對 3 字以上
OK，但 **2 字中文詞完全搜不到**（「環宇」→0、「財測」→0；僅「EPS」英文 3 字→1）。台股個股簡稱大量是 2
字（環宇、緯穎…），這會讓核心用例（SC-008）失效；`unicode61` 不切中文詞。語料規模預估數百～數千篇×數十
KB（≤百 MB 量級），`LIKE` 全掃在本機毫秒～數百毫秒，足夠。
**Alternatives**: FTS5 trigram＋對 <3 字查詢退回 LIKE（兩套邏輯、更複雜，無必要）；自行做中文 bigram 前處理
欄位（可行但為此規模過度設計）。**重新評估點**：若 P1 探查得到文章數 >5,000 或查詢明顯變慢，再改 bigram FTS。

## R7. 查詢介面（MCP）

**Decision**: 兩工具 `search_articles(query, limit=10)`、`get_article(article_id)`。台股 `server.py` 與
美股 `us_stock_mcp_server.py` **各自註冊一份、都讀同一個 `articles.db`**（台美強制各自獨立 Server，
`mcp.py:125-129`）；唯讀白名單 `server_readonly.py` 加入（供 Cline／stock-researcher）。兩個 Server 的資料目錄
解析各自開 `articles.db`，因為它不屬任一市場，路徑固定為同一 `data_dir` 下的 `articles.db`。工具回傳
文字；`get_article` 一併回傳圖片清單（本機檔路徑＋是否為表格＋轉寫狀態＋轉寫文字）。同步清單
（CLAUDE.md「常用查證點」）：`server.py` TOOLS＋call_tool、`server_readonly.py`、`us_stock_mcp_server.py`、
`test_pnl.py::test_tool_counts`（**48→50、29→31**）、
`test_traceability.py::test_tools_list_has_forty_eight`（:252-261，`assertEqual(len(names), 48)`→50，函式名與
docstring 同步並加入預期工具名；**2026-11-15 起初誤判此檔無斷言，經審查並開檔確認後更正**）、Mac 上 `~/.claude` 的 stock-researcher 白名單（**不在 repo**，PO 手動）。
**注意**：`test_claude_ai_connector.py:46-49` 斷言美股模組不含 `get_holdings` 且 names==TOOLS；新工具名
不得與台股工具衝突。

## R8. 排程

**Decision**: `com.alphavibe.investanchorsimport.plist`，樣式同 `statementimport.plist`（`/usr/bin/python3`、
`AlphaVibe-prod`、PATH 含 `/opt/homebrew/bin`、log 寫 `~/Library/Logs/alphavibe-investanchors*.log`、
**無** `RunAtLoad`／`KeepAlive`，靠 `StartCalendarInterval` 於喚醒後補跑一次）。**PO 決定（2026-11-15）：一天一次，
每晚 23:00**（取代原建議的 12:40、15:40，作廢），對應 `MAX_LOGINS_PER_DAY=1`。既有排程時段：02:00、03:30、
03:45、04:00、06:00、07:45、09:30、17:00、20:15、23:15、週一 10:00；23:00 不與任一時段相同。
**與 23:15 `statementimport` 的重疊評估**：最壞情況單次 = 登入＋5 篇×最長 90 秒間隔（≈7.5 分鐘）＋圖片下載
與轉寫（每篇數秒～數十秒，且最後一篇之後無間隔）＋登出，保守估 10～12 分鐘，**可能跨到 23:15 而與之並行**。
結論：**並行無衝突、不需錯開**——兩者各自獨立行程；資料庫不同（`articles.db` vs `alphavibe.db`）；唯一共用的是
Gmail IMAP，但各開各的唯讀連線（皆 `readonly=True`／`BODY.PEEK`），Gmail 允許多連線；Chromium 與 qpdf 的
資源負載在本機可忽略。launchd 對不同 label 的 job 不會互相等待。若實測發現互相拖慢再改為 22:30。
**睡眠補跑風險**：Mac 在 23:00 睡眠時，launchd 於喚醒後補跑一次，實際時間可能落在 PO 正在使用網站的時段
（FR-008 兩台上限）；探查 P2b 與上線驗證期須觀察，必要時於程式內加「非 22:30–次日 06:00 不啟動」的時間窗守衛
（會使補跑延到下一個 23:00，視為可接受）。每次執行即使無觸發也會跑信箱檢查（便宜、唯讀），不等於登入。
**影響（歷史回補速度）**：每日最多登入 1 次、每次最多 5 篇，回補速度為**每天最多 5 篇**。**PO 2026-11-15
決定回補範圍只含最近半年（見 R11）**；探查實測半年約 100 篇，**以每天 5 篇計約 20 天**。新文章在回補期間與回補共用同一個每日 5 篇額度，**新文章（有通知信者）優先於回補**。
健康檢查：`check_scheduled_jobs.py` 新增 `check_investanchors_import()`（讀 `import_runs`，比照
`check_statement_import`）。

## R9. 內容更新與資料生命週期

**Decision**: 只增不刪；已 `fetched` 的文章**不因網站改文而覆寫**（第一版全文為準），不做更新偵測。
**Rationale**: spec 標為 plan 決定；偵測更新需重新開啟已匯入文章，直接違反 FR-003「不重複開啟」與低頻。
若 PO 日後要更新機制，另開 feature。

## R10. 憑證與祕密

**Decision**: 新 service `stnd-investanchors`，accounts：`email`、`password`、`vision-api-key`。擴充
`keychain_secrets.py` 成可指定 service（保持舊呼叫不變，009 測試不得受影響）。存入指令與 009 相同規約：
`security add-generic-password -U -s stnd-investanchors -a <固定名稱> -w`，**`-a` 後是固定名稱、`-w` 後不接
值**（009 已發生過誤填）；驗證只用 `find-generic-password ... >/dev/null && echo ok`；**禁止**
`dump-keychain`／`-w`／`-g`。.gitignore 目前**沒有**祕密檔規則；本設計無任何祕密落地檔，探查輸出目錄
`poc/data/articles_probe/` 已在被忽略的 `poc/data/` 之下。

## R11. 回補範圍：只補最近半年（PO 2026-11-15；2026-11-15 依探查改為以文章 ID 時間判斷）

**Decision**: 回補只處理「**建立時間**在回補**首次啟動日**往前六個月內」的文章；更早的記為 `deferred`（只存
ID、標題、清單日期，不開啟）。截止日存於 `backfill_state.cutoff_date`／`cutoff_ms`，啟動後固定。
**建立時間由文章 ID 推得，不用清單日期**：
- 規則：14 位數 ID 取前 13 位為 epoch 毫秒 `id_ms`；`id_ms >= cutoff_ms - 14 天` 即納入回補，否則記為 `deferred`。
  14 天餘裕依據：31 筆樣本中建立時間早於清單日期 0～11 天（最大 11 天），發布日晚於建立日。
- **防呆（此規律只由 31 筆樣本觀察得到，網站不保證）**：ID 不是 14 位數、或換算出的時間不合理（早於 2020-01-01
  或晚於現在 +1 天）時，**該篇不得被判為「早於截止日而跳過」**，改為照常處理（納入回補）並在該篇記
  `id_time_ok=0`；`import_runs` 累計 `id_time_ok=0` 的篇數，超過 3 篇即通知 PO（規律可能已失效）。
- **為什麼不用清單日期**：4 筆置頂一般文章的清單日期顯示 2021-02-06，但 ID 時間是 2026-11-06～08（近期文章）；
  清單日期對置頂項不可靠，用它做半年粗篩會把這 4 篇誤判為舊文而漏抓。清單日期只用於顯示（`published_at`
  以文章頁 `span.post_date` 為準）。新舊與是否已抓一律只看文章 ID（FR-003）。
**清單解析（P1 實測）**：每頁頂端有 5 筆置頂項（1 公告＋4 一般文章）在各頁重複出現；解析要**跨頁去重**
（出現在第 1 頁與第 2 頁的項目視為置頂，`article.pinned=1`），**置頂項不得被當成舊文跳過**，也**不參與
「整頁都早於截止日」的停止判斷**；不依賴清單位置，一律以 ID 為準。停止規則：某頁所有「非置頂、非公告」項目的
ID 時間都 `< cutoff_ms - 14 天` → 不再往更舊翻。
**標題**：取自清單連結文字（通知信主旨為輔），不依賴文章頁標題選擇器（探查未找到，無 h1）。
**之後擴大範圍**：`investanchors_import.py --backfill-since <YYYY-MM-DD>`（contracts/cli.md §1）把截止日往前
放寬、重新開啟回補，並把 ID 時間落在新舊截止日之間的 `deferred` 轉回 `discovered`，仍依每日 5 篇慢慢補；放寬範圍
須 PO 同意。
**回補估算（實測）**：去除置頂後 2 頁 26 筆涵蓋 47 天（0.55 篇／天），外推半年約 **100 篇**；每天 5 篇約 **20 天**
（尚未到半年邊界，實際值以回補實跑為準）。
**Alternatives**: 全量回補（PO 已排除）；用清單日期粗篩（已被置頂項證偽，見上）；ID 與清單日期單調（實測不成立，
清單日期是發布日、ID 是建立日，但 ID 時間 ≤ 清單日期，足以當截止判斷的下限）。

## R12. 每週核對的頻率（**定案：每週一次**；PO 可依上線後觀察調整）

**背景**：排程每晚 23:00 跑一次（R8）。平常只唯讀檢查信箱，有新信才登入；每次登入都會讀清單並抓所有未入庫文章（R1），
所以「沒有通知信的文章」會被**下一次由任何原因觸發的登入**順帶撈到。每週核對的角色因此是「**長時間沒有可觸發的信**」時的保底，
不是主要補漏機制。實測發文約每天 0.55 篇；近 30 天搜到 12 封通知信、分佈在 10 個日期，**連續信件最大間隔 4 天**。
**注意**：這個判斷只根據 30 天樣本；PO 表示每篇文章都寄信、實測只搜到約一半（原因未驗證），若之後發現信其實更稀疏，
應重新評估頻率。PO 尚未表示要改，**目前預設每週一次**。
**選項**（登入次數以「核對造成的額外登入」計；有新信的夜晚本來就會登入，不含在內）：
| 選項 | 核對造成的額外登入 | 無信可觸發時，文章最慢多久進來 | 副作用 |
|---|---|---|---|
| **每週一次（週日夜）← 預設** | 每週最多 1 次（該夜若已因新信登入則 0） | 最慢約 7 天（依 30 天樣本，通常因信的最大間隔 4 天而 ≤4 天） | 最符合「低頻」與 SC-003 |
| 每週兩次（例：週三、週日夜） | 每週最多 2 次 | 最慢約 4 天 | 登入次數增加；SC-003 的例外日由 1 天變 2 天 |
| 每天 | 每天 1 次（與每日排程合一） | 最慢約 1 天 | **幾乎每天登入**，失去「無新信不登入」的保護；SC-003 與 FR-006 須改寫；帳號風險最高 |
任何選項都受 `MAX_LOGINS_PER_DAY=1` 約束（一晚最多登入 1 次，新信與核對合併成一次）。FR-006／SC-002／SC-003／R1／R8／
contracts/cli.md 皆以「每週一次、保底」為準；若 PO 日後調整，依選項同步這些條文。

## 風險摘要

1. 帳號被停用（兩台上限／行為偵測）→ R3 全新 context＋R4 上限；探查規約最小化。
2. 站方改版 → DOM 解析集中在 scraper 一處，取不到內文就標失敗不寫殘缺（FR-013）。
3. 轉寫不準 → 標示＋原圖＋上線前抽 10 張由 PO 本人逐格確認。
4. 把付費內容送第三方模型 API → PO 已於 2026-11-14 同意（Q-016，R5）。
5. 歷史回補慢（每天最多 5 篇）→ 範圍限半年（R11），探查實測約 100 篇、約 20 天。
6. 文章 ID＝建立時間的規律只由 31 筆樣本得出 → 實作防呆：ID 不合規格時不得跳過、記錄並累計通知（R11）。
7. 通知信與文章篇數有落差（PO 表示每篇都寄，實測只搜到約一半，**原因未驗證**）→ 信只當觸發、每次登入抓所有未入庫文章，漏信只延後觸發、不漏文章（R1）；每週核對一次保底，頻率依上線後觀察調整、此判斷只根據 30 天樣本（R12）。
8. **信中連結是每位收件人的點擊追蹤轉址（`/c/<token>`），不可跟隨、不可解碼**（跟隨會留下點擊紀錄、token 含收件人追蹤資訊）。
9. 探查工具的報告不得含 token：首次純信箱實跑發現路徑形態只遮數字、字母 token 片段仍進報告，已修（長路徑段一律標 `<token>`，commit f1a2d76）。
