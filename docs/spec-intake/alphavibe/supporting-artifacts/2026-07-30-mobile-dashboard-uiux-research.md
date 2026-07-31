# 手機儀表板 UI/UX 改版研究（2026-07-30）

## 一句話結論

推薦「**摺疊優先＋卡片欄位瘦身**」：沿用現有 `<details>/<summary>` 原生摺疊
（已經做了，只是預設全開）＋把「今日重點」以外的區塊預設收合並在標題顯示
筆數徽章＋高欄位數表格（庫存、新候選）在手機版精簡到 5~6 個主要欄位、次要
欄位收進既有的 `<details class="reason">` 展開樣式——不引入分頁籤/底部導覽/
多頁跳轉。信心程度：**中高**（架構判斷有多個可信來源佐證且與現有程式碼基礎
高度吻合；「哪些欄位算次要」是 PO 的產品判斷，本文件只給建議排序，不代表
唯一答案）。

---

## 一、現況盤點（實測 report.py / report_server.py，非猜測）

- `render_dashboard()`（`report.py:740-797`）是 FR-058「方案A單頁式」首頁，
  由上到下垂直串接 6 個區塊：今日重點、今日新候選、觀察名單／庫存總覽、
  純觀察標的（無庫存）、策略設定、快速輸入。
- **每個區塊已經是原生 `<details class="section">` 摺疊元件**（`report.py`
  第 268、387、565、609、647、678 行），不是純表格硬堆——這點很重要，代表
  「可摺疊區塊」這個模式在這個 repo 裡不是要從零導入，而是要調整既有設定。
- 但目前 6 個區塊裡 **4 個預設 `open`**（今日重點／今日新候選／庫存總覽／
  純觀察標的），只有策略設定與快速輸入預設收合。等於使用者打開頁面時，
  4 個資料表格同時全展開——實質上跟沒有摺疊差不多，這正是 PO 說「只有捲軸」
  的根本原因：摺疊機制存在，但預設狀態把它抵銷掉了。
- 頁面頂部已有 `<nav class="toc">` 錨點導覽（`report.py:779-787`），6 個區塊
  各一個 `<a href="#section-*">`，可以跳轉但**不會自動收合其他區塊**，跳過去
  之後還是要在一個已經全展開的長頁面裡找位置。
- CSS（`report.py:30-194`）已經有：
  - 語意化色彩 token（`--red`/`--green`/`--accent`/`--amber` 等，深色模式
    另有一組覆寫值，`@media (prefers-color-scheme: dark)`）
  - **表格在 ≤640px 已經轉成卡片**（`report.py:172-186`，`.tablewrap table`
    等規則把 `<table>` 拆成一張張帶 `data-label` 的卡片，橫向表格變直向
    堆疊清單）——這個轉換本身也是資料密度問題的一部分，見下一節。
  - `details.reason`（`report.py:139-143`）：表格裡「理由」欄位已經有「顯示
    全文」的展開樣式，證明這個 repo 已經在用「次要內容摺疊、點了才展開」
    的手法，只是目前只套用在單一欄位。
- 資料密度實測（欄位數＝手機版卡片模式下每一筆資料要往下捲幾行）：

  | 區塊 | 欄位數 | 備註 |
  |---|---|---|
  | 今日重點 | 5 | 代碼/檢視層/發現/建議動作/提醒，通常筆數少（只列有 `suggested_action` 的） |
  | 今日新候選 | 10 | 代碼/名稱/市場/產業別/符合策略/PER/營收年增率/PEG/回檔幅度/目前價 |
  | 觀察名單／庫存總覽 | **12** | 代碼/名稱/產業別/投資主題/股數/平均成本/市值/持股比例/立場/估值依據/理由/更新日期，另加主題集中度子表 |
  | 純觀察標的 | 5 | 代碼/名稱/立場/理由/更新日期 |
  | 策略設定 | 不是表格，用 `.comment` 卡片，每策略一張，本身已經算緊湊 |
  | 快速輸入 | 5 個表單，非資料密度問題 |

  庫存表 12 欄在手機卡片模式下，**每一檔持股就要往下捲 12 行資料**（外加
  `data-label` 小標籤各佔一行的視覺高度）——如果 PO 有 15~20 檔庫存，光是
  這個已展開的區塊就可能超過一個手機螢幕高度的 10~15 倍，這是比「該不該
  摺疊區塊」更根本的密度問題。

- `report_server.py` 確認：純 `http.server`、無前端框架、無建置流程，所有
  互動走傳統 `<form method="post">` 整頁送出＋303 轉址帶 flash 訊息回首頁
  （`report_server.py:167-179`），5 個 `/dashboard/*` POST 端點。**任何建議
  都必須能用純 HTML/CSS/最多幾行原生 JS 達成**，不能假設有 SPA 路由或
  client-side state。

---

## 二、資訊架構模式比較（至少3種，附來源）

### 1. 分頁籤（Tabs）

- **來源**：Material Design 對 tabs 的定位是「同一層級、彼此相關的內容」，
  適合篩選/切換同一父畫面下的手足內容；bottom navigation 則用於彼此獨立、
  同等重要的頂層目的地，且明確建議「少於3個目的地就該用 tabs 不要用
  bottom nav，超過5個也不建議」——
  [Material Design: Bottom navigation](https://m2.material.io/develop/android/components/bottom-navigation/)、
  [Navigation patterns](https://m1.material.io/patterns/navigation.html)。
  Apple HIG 對 tab bar 的建議是 iPhone 上用 3~5 個 tab，且 tab bar 只能做
  導覽，不能拿來觸發動作——
  [Apple HIG: Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars)。
- **優點**：同一時間只顯示一個區塊，頁面高度固定、不會有「捲不完」的問題；
  適合使用者會反覆切換於幾個「同等重要」的視角之間。
- **缺點**：這 5 個區塊**不是同等重要、也不是同時想看的東西**——今日重點
  是「每次打開都想先看」，策略設定是「幾乎不看，只在調整策略時看」，硬做
  成 5 個平權 tab，反而要多一次點擊才能看到今日重點（現在是預設就在最上面）。
  純 CSS 做 tabs 需要 radio-button hack（見第四節），比 `<details>` 複雜。
- **如果採用，5 區塊怎麼重組**：今日重點/新候選/庫存總覽/純觀察/策略設定
  各自變成一個 tab（快速輸入獨立或併入某個 tab 底部），使用者要先選 tab
  才看得到內容，等於**犧牲了「一開頁就看到今日重點」這個目前免費擁有的
  優勢**去換取「頁面不會太長」——不建議，見第五節理由。

### 2. 可摺疊區塊（Accordion／`<details>`）

- **來源**：NN/G 對手機版 accordion 的結論是——資料密集頁面上，accordion
  常常是解決「螢幕小、內容多」最有用的手法之一，讓使用者先看到全貌（像
  一份 mini 目錄）再決定要深入哪一塊；但也提醒 accordion 會增加互動成本、
  展開後捲動太深容易迷失方向，建議搭配「回到頂部」或把 accordion 標題做
  成 sticky——
  [NN/G: Accordions on Mobile](https://www.nngroup.com/articles/mobile-accordions/)。
  這個結論與更上位的 **漸進式揭露（progressive disclosure）** 原則一致：
  先只顯示最常用的東西，其餘依需求展開，可以同時改善學習成本、操作效率、
  降低出錯率，但超過兩層摺疊就容易出問題——
  [NN/G: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)。
- **優點**：AlphaVibe **已經用這個模式**（`<details class="section">`），
  零學習成本、零 JS、鍵盤與螢幕報讀器原生支援；只要調整預設開合狀態跟標題
  文字（加筆數），就能大幅改善現況，改動成本最低。
- **缺點**：如 NN/G 所述，全部收合後使用者要「盲猜」該點開哪個才找得到
  想看的東西——所以標題要帶上筆數／狀態徽章，不能只是區塊名稱。
- **如果採用，5 區塊怎麼重組**：**這是本文件的推薦方向**，具體重組見
  第五節，簡述：今日重點維持預設展開（就是「今天該看什麼」的答案本身），
  其餘 4 個資料區塊改成預設收合＋標題帶筆數徽章（例：「今日新候選
  (3)」），策略設定／快速輸入維持現狀已經收合。

### 3. 卡片摘要＋點進去看詳情（Summary Card + Drill-down／多頁）

- **來源**：NN/G 對 card 元件的建議——卡片適合「瀏覽不同性質的內容」、
  適合當作連到完整細節的入口，但**不適合需要逐項比較的場景**（眼動研究
  顯示使用者要在卡片之間來回對照反而更累），且卡片比清單列更佔空間——
  [NN/G: Cards: UI-Component Definition](https://www.nngroup.com/articles/cards-component/)。
  金融類 app 的常見做法是把總覽（總資產、當日損益）放最上層卡片，再把
  個別持股各自做成一張可點開的卡片而非傳統表格，用顏色＋箭頭做漲跌視覺化
  而非純數字——
  [Lollypop: Investment Dashboard UX Design](https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/)。
- **優點**：首頁可以做得非常短（每區塊只留一張摘要卡＋「查看全部」連結），
  真正做到「打開就看完」。
- **缺點**：以這個 repo 的技術棧（純 Python `http.server`、每個請求整頁
  重新渲染、無 client-side 路由）要做到「點進去看詳情」，代表**每個區塊
  都要變成獨立的 URL／獨立的整頁請求**（例如 `/dashboard/holdings`），
  對比現在的「頁內錨點跳轉」，多了一次網路往返；而且 PO 每天檢視的核心
  訴求就是「今日重點」這種需要一眼掃過的資訊，拆成多頁反而增加操作步驟。
  對這個「單一使用者、快速掃視＋偶爾填表單」的個人工具來說，投資報酬率
  低於方向2。
- **如果採用，5 區塊怎麼重組**：首頁只留 5 張摘要卡（例："今日重點：2
  項需留意"、"新候選：3 檔"、"庫存：12 檔，總市值 XXX"、"純觀察：5 檔"、
  "策略：3 套框架"），各自連到獨立頁面顯示完整表格；快速輸入表單獨立成
  自己的頁面或維持在首頁最下方。工作量明顯大於方向2（需要在
  `report_server.py` 新增對應路由）。

### 4.（補充，非取代）置頂摘要列（Sticky Summary Header）

- **來源**：NN/G 認為 sticky header 在「使用者整個瀏覽過程都會反覆需要」
  的元素上才值得犧牲螢幕空間，且務必保持不透明背景、高對比、動畫要短
  （約300~400ms），否則會變成干擾——
  [NN/G: Sticky Headers](https://www.nngroup.com/articles/sticky-headers/)。
- **定位**：這不是取代方向2的獨立方案，而是可疊加的加分項——把現有
  `<nav class="toc">` 錨點列改成 `position: sticky` 並在每個連結後面加上
  筆數徽章（例："今日重點 ⚠️2｜新候選 3｜庫存 12｜純觀察 5"），使用者
  捲動到任何地方都能一眼看到全局摘要並跳轉。**建議列為第二階段加分項**，
  不放進 MVP，因為 sticky 定位在手機瀏覽器（尤其 iOS Safari 的動態網址列）
  容易有跳動/遮擋細節問題，需要額外測試，跟核心問題（頁面太長）比是
  錦上添花而非雪中送炭。

### 5.（提及但不建議）底部導覽（Bottom Navigation）

- Material Design 的 bottom navigation 明確定位給「彼此獨立、同等重要的
  頂層目的地」，用 3~5 個——
  [Material Design: Bottom navigation](https://m2.material.io/develop/android/components/bottom-navigation/)。
  AlphaVibe 首頁的 5 個區塊彼此不是獨立目的地（今日重點根本是整個首頁存在
  的理由），而且首頁之上還有 `/screen`、`/market-scan`、`/report-classic`
  三個平行頁面——如果要用 bottom nav，語意上更適合放這幾個頁面而不是首頁
  內部的 5 個區塊，但那是另一個範圍更大的資訊架構決策，超出本次「改版
  現有 dashboard 頁面」的範圍，此處僅記錄以供未來參考，不列入本次建議。

---

## 三、純 HTML/CSS／少量原生 JS 技術限制下的可行做法

- **`<details>/<summary>`**：零 JS、原生鍵盤與螢幕報讀器支援，AlphaVibe
  已經在用。額外可用 `name` 屬性把多個 `<details>` 分組成「同時只能展開一個」
  的互斥摺疊（跟目前「各自獨立展開」不同，語意更接近手風琴），但要注意
  分組後使用者較難「同時展開兩個區塊比對」——
  [Hassell Inclusion: Accessible accordions with details/summary](https://hassellinclusion.com/blog/accessible-accordions-part-2-using-details-summary/)、
  [web.dev: Details and summary](https://web.dev/learn/html/details)。
  **建議不分組**（維持現況的獨立展開），因為 PO 可能想同時攤開「今日重點」
  跟「庫存總覽」對照著看，互斥摺疊會擋掉這個彈性。
- **CSS-only tabs（隱藏 radio button + `:checked` + 相鄰選擇器）**：技術上
  可行、不需要 JS，但如果用 `visibility:hidden` 隱藏 radio 會失去鍵盤可達性，
  要改用 `opacity:0` 才能保留可達性——
  [dfkaye.com: Accessible CSS-driven Tabs](https://dfkaye.com/posts/2020/08/23/accessible-css-driven-tabs-without-javascript/)。
  這個技巧比 `<details>` 複雜（要多包一層 radio+label 結構），而且如第二節
  第1點所述，本次不建議走 tabs 方向，所以這個技巧本次用不到，留存參考。
- **少量原生 JS 的合理用途**（非必要但可以加分）：一段極短的 script 讓
  「筆數徽章」在頁面渲染後不需要重整頁面——但因為這是 Python 產生的靜態
  HTML（每次請求整頁重算），筆數本來就是渲染當下算好直接寫進 HTML，
  **完全不需要 JS**，這點反而是這個技術棧的優勢：不像 SPA 需要額外處理
  「初次載入閃爍」問題。

---

## 四、投資類 App 的手機儀表板慣例（佐證方向2/3的細節做法）

- 資產總覽放最上層、用大字級凸顯總市值/總損益等關鍵數字，次要指標（如
  交易量、手續費）用較小較淡的字體區分主次順序——
  [Lollypop: Investment Dashboard UX Design](https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/)。
- 顏色不能是唯一的漲跌訊號，建議搭配箭頭圖示（↑/↓）並確保對比度達
  WCAG AAA——同上來源。AlphaVibe 目前的 `STANCE_COLORS`（`report.py:27`）
  只用顏色區分偏多/偏空文字，未來若要往這個方向優化，可以加上箭頭符號，
  但這屬於視覺細節優化，不影響本次資訊架構層級的建議，**列為次要加分項**。
- 「無來源，屬個人整合判斷」：Mobbin 上主流理財 App（如 Robinhood）的
  持股列表普遍採「一檔一列精簡卡片（代碼/名稱/市值/損益）＋點擊才看更多
  欄位（成本、產業分類等）」的模式，但 Mobbin 的實際截圖需要登入才能瀏覽
  完整內容，本次搜尋只取得平台介紹頁與二手轉述文章，**未能直接查看原始
  截圖驗證細節**，這一條的具體佐證強度低於本文件其他主張，僅供方向性
  參考。

---

## 五、推薦方案（明確表態）

### 方案名稱：摺疊優先＋卡片欄位瘦身

**核心邏輯**：不改變現有「單頁＋原生 `<details>` 摺疊」的資訊架構骨架
（方向2），因為它已經是這個使用情境（單一使用者、手機瀏覽器快速掃視＋
偶爾填表單）最合適的模式——不必為了「頁面太長」去犧牲「一次看到今日重點」
這個核心價值（tabs／多頁都要多一次點擊才看得到），只需要修正兩個具體
缺陷：

1. **預設開合狀態錯了**：4 個資料區塊同時預設展開＝跟沒有摺疊一樣。
   改成——「今日重點」維持預設展開（這是使用者打開頁面的目的本身，通常
   筆數少，攤開也不長）；「今日新候選」「觀察名單／庫存總覽」「純觀察
   標的」改為**預設收合**，標題加上筆數徽章（例：「今日新候選 (3)」「觀察
   名單／庫存總覽 (12 檔)」），讓使用者一眼看到全局規模、自己決定要不要
   點開；「策略設定」「快速輸入」維持現狀已收合。
2. **高欄位數表格在手機上太厚**：庫存表 12 欄、新候選表 10 欄，在既有的
   「表格→卡片」CSS 轉換下每一筆資料要捲 10~12 行。建議把每個區塊的欄位
   分成「主要」（一眼要看到：代碼/名稱/市值or現價/立場or符合策略/回檔or
   持股比例）跟「次要」（產業別/投資主題/估值依據/更新日期等），次要欄位
   收進既有的 `details.reason` 展開樣式（目前只用在「理由」欄，可以擴充
   到整組次要欄位）。**哪些欄位算主要/次要是產品判斷，不是技術判斷**，
   本文件先給一版建議排序，正式改版前建議跟 PO 過一次確認順序。

**為什麼適合這個情境（不是給大眾用的公開產品）**：PO 是唯一使用者，使用
模式是「手機上快速確認今天有沒有事、偶爾補填一筆交易」，不是需要被說服
留存或探索功能的訪客。這代表：不需要 tabs/bottom nav 去「引導探索」（唯一
使用者早就知道每個區塊是什麼）；也不需要為了追求「頁面極短」去拆成多頁
（多一次網路往返對這個純 Python 整頁重渲染的架構是實質延遲，不是免費的）。
「摺疊優先」剛好給「今日重點立即可見」＋「其他資訊一鍵可達」兩者最短路徑，
且改動幾乎全部落在既有模式裡（調整 `open` 屬性、標題文字、少量 CSS），
风险與投入都最低。

### 次要／第二階段加分項（不影響本次核心建議，另外排期即可）

- 置頂摘要列（sticky `.toc`，見第二節第4點）
- 漲跌箭頭圖示（見第四節）
- 若未來使用情境改變（例如要給別人看、或要在桌機也頻繁使用複雜篩選），
  再重新評估方向3（多頁 drill-down）或方向1（tabs）是否更合適——目前
  證據不支持現在就做。

---

## 六、實作影響評估（純研究判斷，未動手改程式碼）

| 項目 | 涉及檔案/函式 | 量級 |
|---|---|---|
| 調整各區塊預設開合狀態＋標題筆數徽章 | `report.py`：`_render_new_candidates_section()`（640行附近改標題字串加筆數）、`_render_holdings_section()`（268行附近拿掉 `open`＋標題加筆數）、`_render_watchlist_only_section()`（387行附近同上）——這3個函式本來就各自查自己的資料，筆數是既有變數（`len(order)`／`len(holdings["holdings"])`／`len(watchlist_only)`）直接可用，不需要新查詢 | **小改動**：純字串/屬性調整，每個函式改幾行，無新邏輯 |
| 高欄位表格「主要/次要欄位」瘦身 | `report.py`：`_render_holdings_section()`、`_render_new_candidates_section()` 的 `<tr>` 組裝邏輯——要把目前一行組完所有 `<td>` 的寫法拆成「主要欄位直接輸出」＋「次要欄位包進一個類似 `reason_html()` 的展開區塊」；CSS 常數（30-194行）可能要加一條規則讓這個新的「更多」展開跟現有 `details.reason` 視覺一致但語意分開 | **中改動**：牽動2個核心資料函式的表格組裝邏輯，且「哪些欄位算次要」需要先跟PO對齊，不是單純技術活 |
| （加分項）置頂摘要列 | `report.py`：`render_dashboard()` 裡目前的 `<nav class="toc">` 區塊（779-787行）＋ CSS `.toc` 規則（144-149行）加 `position: sticky` 與筆數徽章 | **小改動**，但需要在真機（尤其 iOS Safari）測試 sticky 定位是否跟動態網址列打架 |
| （加分項）漲跌箭頭 | `report.py`：`STANCE_COLORS`（27行）與各處輸出 `stance_text` 的地方 | **小改動** |
| 不需要的改動 | `report_server.py` 路由層——本次推薦方案不新增任何頁面/路由，維持現有5個 `/dashboard/*` POST 端點與既有 GET 路由不變 | 無 |

**整體量級**：核心建議（預設開合狀態調整）是小改動、單一 session 內可完成
並手動驗證（改完用瀏覽器縮到手機寬度肉眼檢查）；表格欄位瘦身是中改動，
建議拆成獨立任務，且先讓 PO 對過一輪「主要/次要欄位」清單再動手，避免
做完才發現排序跟 PO 認知的重要性不一致。

---

## 已知限制（誠實揭露）

- 本文件是資訊架構與模式層級的研究，**沒有做任何視覺稿或高保真 mockup**，
  推薦方案的「感覺讀起來順不順」仍需實際改完在手機上試用才能確認。
- Mobbin 等設計案例網站的實際截圖需要登入，本次僅取得平台介紹文字與二手
  轉述文章佐證投資類 App 慣例，第四節已標註哪些主張屬於「個人整合判斷」。
- 「主要欄位 vs 次要欄位」的具體分類（第五節）是研究者依欄位語意給出的
  建議排序，不是 PO 本人確認過的結果，正式排入實作前建議先跟 PO 過一次。
- 未評估這個改版對 `report-classic`（`render()` 舊版完整檢視，`report.py`
  第407行起）的影響——本文件只涵蓋 `render_dashboard()` 新首頁，舊版頁面
  不在本次研究範圍內（`report_server.py` 確認它仍是獨立路由 `/report-classic`，
  互不影響）。

---

## 研究來源清單

- [Material Design: Bottom navigation](https://m2.material.io/develop/android/components/bottom-navigation/)
- [Material Design: Navigation patterns](https://m1.material.io/patterns/navigation.html)
- [Apple HIG: Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars)
- [Apple HIG: Disclosure controls](https://developer.apple.com/design/human-interface-guidelines/disclosure-controls)
- [NN/G: Accordions on Mobile](https://www.nngroup.com/articles/mobile-accordions/)
- [NN/G: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
- [NN/G: Cards: UI-Component Definition](https://www.nngroup.com/articles/cards-component/)
- [NN/G: Sticky Headers: 5 Ways to Make Them Better](https://www.nngroup.com/articles/sticky-headers/)
- [Lollypop: Investment Dashboard UX Design](https://lollypop.design/blog/2026/may/investment-dashboard-ux-design-guide/)
- [Hassell Inclusion: Accessible accordions part 2 - using details/summary](https://hassellinclusion.com/blog/accessible-accordions-part-2-using-details-summary/)
- [web.dev: Details and summary](https://web.dev/learn/html/details)
- [dfkaye.com: Accessible CSS-driven Tabs (without JavaScript)](https://dfkaye.com/posts/2020/08/23/accessible-css-driven-tabs-without-javascript/)
- [Mobbin: Financial Dashboard Examples & UI Inspiration](https://mobbin.com/explore/web/app-categories/financial-dashboard)（僅平台介紹頁，未能查看完整截圖）
