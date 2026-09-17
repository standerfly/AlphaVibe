# AlphaVibe 前端審查（web/src/，24 檔 5394 行）

審查範圍：唯讀審查，未修改/建立/刪除任何檔案，未執行 build。
審查日期：2026-09-17。

## 總結

發現 12 個問題：必修 1 個／該修 9 個／可不修 2 個（另有多項「已檢查、無發現」列在各節）。

整體結論：**架構本身還撐得住繼續長功能，但有一個結構性缺口（沒有 Error
Boundary）是現在就該補的地基問題，晚補一天，風險就多累積一天**。其餘問題
多屬「維護成本開始有感」等級（Assets.jsx 過大、格式化函式重複 4~6 份），
不是會馬上炸的等級。手機端（PO 主要使用情境）整體處理得比預期細緻
（overflow-x 容器、dark mode token 化、響應式 grid 都有做），只有觸控
熱區偏小與少數行動裝置專屬 gap 需要補。

---

## 角度 1：Assets.jsx / QuickInputPanel.jsx / StockDetail.jsx / UsStockDetail.jsx 拆分

### Assets.jsx（1047 行）—— 該修，中等工作量

混了 6 種職責在同一個 function component 裡：(a) 20+ 個 useState／
useCallback／useRef 構成的資料層（4 個 refresh 函式＋1 個 runSimulation＋
9 個 handleXxx mutation handler）、(b) 口袋卡片 grid 渲染、(c) 資產走勢圖卡
（含手動回填、投入紀錄兩個子表單）、(d) 口袋/帳戶 CRUD 表單、(e) 建倉進度
月曆格、(f) 情境試算表單＋推演圖。目前找一個 bug 要在 1047 行裡先定位是
哪一段，改一個表單有意外波及其他區塊渲染的認知負擔。

具體拆分草案：
- `pages/Assets.jsx`（~100行）：只留頁面組裝＋呼叫 `useAssetsData()`
- `pages/assets/useAssetsData.js`（~350行）：抽出全部 state／
  refreshCore／refreshBuildup／refreshNetWorth／refreshContributions／
  runSimulation／9個handleXxx——這塊是純邏輯，抽出後最大好處是可以獨立
  測試，不用掛著 1047 行 JSX 才能驗證資料流對不對
- `pages/assets/PocketGrid.jsx`（原436-488行）
- `pages/assets/NetWorthTrendCard.jsx`（原490-688行，含手動回填/投入
  紀錄兩個子表單——這塊本身也有 200 行，視情況可再拆 ManualEntryForm／
  ContributionForm）
- `pages/assets/PocketAccountManager.jsx`（原690-844行）
- `pages/assets/BuildupProgressCard.jsx`（原846-922行）
- `pages/assets/SimulationCard.jsx` + `ProjectionCard.jsx`（原924-1044行）
- `money()`／`pocketProgressPct()` 移進共用 `utils/format.js`（見角度4）

### QuickInputPanel.jsx（487行）—— 可不修

長，但內部已經拆得不錯：5個獨立子表單（WatchlistForm/TradeForm/
LaoyutouForm/TradeLedgerForm/HoldingsImportForm）各自用共用的
`useFormState()` hook管理busy/error/notice/success，彼此不互相污染，
`StatusBoxes`是共用呈現元件。真的要拆也只是把5個表單各自搬進獨立檔案
（`components/quick-input/*.jsx`），純組織性，沒有功能風險，優先度低於
Assets.jsx。

### StockDetail.jsx（391行）/ UsStockDetail.jsx（359行）—— 可不修，優先度低

兩者都是「唯讀展示為主」的頁面，用 `<section className="card">` 逐一
對應後端回傳的資料區塊（估值/Checks/Score/集中度/加碼計畫/持股交易/
心得），這種1:1對映其實是可讀性優點，不是單純的長度問題——沿著後端
docstring 逐段讀就能找到對應程式碼。UsStockDetail.jsx還有表單邏輯
（新增/刪除關注條件），但份量不大。如果之後要動，建議拆法是依卡片切
（ValuationCard/ChecksCard/ScoreCard/ConcentrationCard/
PositionPlanCard/HoldingsTradeCard/NotesCard），但目前不算迫切。

---

## 角度 2：狀態管理與資料流

- 未使用任何狀態管理庫（無 Redux/Zustand/Context 全域store），純靠
  useState + props + react-router 的 useSearchParams。以目前規模（8個
  路由頁、多為獨立fetch）這個選擇合理，沒有明顯的prop drilling問題
  （最深的傳遞鏈是 Dashboard.jsx → QuickInputPanel → 5個子表單，用
  callback prop `onDataChanged`，屬合理深度）。

- **【該修】Assets.jsx 缺少其餘頁面統一採用的 race-guard pattern**
  （`web/src/pages/Assets.jsx:116-148`）。Home.jsx/Dashboard.jsx/
  StockDetail.jsx/UsStocks.jsx/UsStockDetail.jsx/MarketScanPanel.jsx
  全部用「`let cancelled = false` + cleanup函式」防止舊請求覆蓋新資料或
  對已卸載元件setState，這是這個codebase一致遵守的模式，但Assets.jsx的
  `refreshCore`/`refreshBuildup`/`refreshNetWorth`/`refreshContributions`/
  `runSimulation`全部沒有這層防護。**會怎樣**：使用者快速連按「按月/
  按年」切換資產走勢圖（`handleNetWorthGranularity`，Assets.jsx:342-345）
  時，若較早發出的請求較晚回來，會用過期的資料覆蓋畫面（顯示跟按鈕
  高亮狀態不一致的圖）；離開資產分頁時未完成的請求resolve也會對已卸載
  元件呼叫setState（React18不會報錯，但是浪費且是潛在的未來bug溫床）。
  修法：比照其他頁面補上cancelled旗標，是機械性的修改。工作量：小。

- **未見其他race condition**：ScreenPanel.jsx／MarketScanPanel.jsx表單
  提交型的fetch雖也沒有cancelled guard，但這類是使用者主動觸發、
  有loading狀態擋按鈕，風險遠低於路由層級的自動fetch，可不修。

- **loading/error狀態覆蓋率**：已檢查全部8個頁面組件與6個資料型
  子元件，每一個fetch呼叫都配有對應的error顯示（`.error-box`）與
  loading顯示（`.loading-box`），沒有發現「fetch了但沒地方顯示失敗」
  的空缺。UsStockDetail.jsx的`loaded`判斷用5個資料是否都非null組成
  （UsStockDetail.jsx:161），**未驗證**：若後端某個端點在特定情境
  回傳null（例如從未交易過的ticker），會不會讓loading狀態卡住不放——
  這需要對照後端us_stocks.py實際回傳保證，本次審查未查證後端契約，
  標記為待確認事項。

---

## 角度 3：API層（client.js）

- **【該修】`apiGet`/`apiPost`/`apiDelete`的成功路徑`res.json()`沒有
  防護**（`web/src/api/client.js:31, 59, 82`）。三個函式對「回應HTTP
  200但body不是JSON」這個情境完全沒有處理——對照專案本身2026-09-10的
  教訓紀錄（ngrok瀏覽器警告頁回200+HTML導致`res.json()`丟出使用者看不懂
  的錯誤），目前的修法只是加了`ngrok-skip-browser-warning`header去避免
  「已知的」觸發情境，但沒有在client.js本身加一層防禦——如果之後換了
  別的proxy/CDN，或ngrok這個header失效、或後端某個路由意外回了HTML
  錯誤頁，會重演同一種「The string did not match the expected
  pattern」等級的難懂錯誤訊息（原生SyntaxError的message，不是
  ApiError的清楚訊息）。**會怎樣**：使用者只會看到`.error-box`裡一句
  類似「Unexpected token '<'...」的英文技術訊息，不知道發生什麼事。
  修法：在三個函式裡把`res.json()`包一層try/catch，非JSON時丟出
  `ApiError('回應格式異常，可能是網路中介層問題', res.status, path)`
  這類清楚訊息。工作量：小。

- **【該修】完全沒有client端timeout/retry**（`client.js`全檔）。三個
  fetch呼叫都沒有搭配`AbortController`設逾時，也沒有任何重試邏輯。
  對照本專案CLAUDE.md教訓紀錄中devtunnel時期30%請求無回應（HTTP 000）
  的實測歷史——雖然現在用ngrok穩定很多，但沒有client端超時代表「網路
  卡住」時，畫面會卡在「載入中…」永遠不會變成錯誤狀態，使用者除了手動
  重新整理頁面沒有其他線索或動作可做。**會怎樣**：手機訊號不穩時使用者
  會看到轉圈圈轉到懷疑人生，不知道是網路問題還是程式壞掉。修法：
  `apiGet`加`AbortSignal.timeout(15000)`之類的逾時，逾時時丟出清楚的
  ApiError訊息（「連線逾時，請檢查網路後重新整理」）。工作量：小。

- **一致性**：已檢查全部pages/components，確認沒有任何一處繞過
  api/client.js直接呼叫`fetch()`——19處fetch呼叫全部經過apiGet/apiPost/
  apiDelete三個helper，這點做得很乾淨。

- **【可不修/風格瑕疵】** Assets.jsx的`handleDeleteContribution`
  （Assets.jsx:396-407）用`apiPost('/api/assets/contributions/:id/delete')`
  模擬刪除，而UsStockDetail.jsx的`handleDeleteWatchCondition`
  （UsStockDetail.jsx:148-159）用真正的`apiDelete()`呼叫DELETE方法——
  兩者都各自對應到後端實際路由設計（已查證`app/routers/assets.py:537`
  確實是`@router.post(".../delete")`），不是前端bug，只是兩個功能各自
  演化出不同的REST慣例，未來新功能要選哪種风格沒有統一指引。

---

## 角度 4：元件重用（台股 vs 美股）

- **StockComboChart.jsx 已經是良好重用的正面案例**：同一個元件同時被
  StockDetail.jsx（台股）與UsStockDetail.jsx（美股）使用，透過
  `toPriceHistory()`/`toLedgerEntries()`兩個小型轉接函式把美股資料
  轉成元件原本的通用形狀（{date,close}／{date,action,shares,price}），
  UsStockDetail.jsx檔頭註解明確交代了這個技術取捨（含「紅漲綠跌」視覺
  規則因此自動保持一致）。這是目前codebase裡跨市場元件重用做得最好
  的地方，不需要改動。

- **【該修/可延伸】** 台美股「持股與交易」卡片裡的交易流水清單渲染
  區塊（StockDetail.jsx:335-351 vs UsStockDetail.jsx:216-229）幾乎
  逐行相同（`<details className="trade-list-details">` + 
  `.map` 產生 `.trade-row`），沒有抽成共用元件。**評估抽取風險**：
  兩邊資料形狀有實質差異——台股版多了`add_sequence`（加碼序號）跟
  `fifo.status==='history_incomplete'`的額外揭露列，硬抽成單一元件
  需要用props開關控制這些差異欄位，抽出來的元件可能反而比兩份各自
  20行的重複代碼更難讀（要先理解一堆條件分支才知道某個市場會不會出現
  某一列）。**建議**：值得抽，但抽成`<TradeLedgerList entries={} 
  extraColumns={} />`這種留有擴充點的設計，不要為了DRY而讓元件背負
  太多市場特定分支——工作量中等，優先度低於角度1/2/3的項目。

- **money()/pct()/num()系格式化函式重複定義 4~6次**——具體位置：
  `pages/Assets.jsx:24`／`pages/StockDetail.jsx:7,10,14,17`／
  `pages/UsStocks.jsx:18,21`／`pages/UsStockDetail.jsx:30`。
  `money()`在4個檔案各自定義一份幾乎相同的邏輯（Math.round+
  toLocaleString），差別只有台股版用'zh-TW'、美股版用'en-US'。
  `ScreenPanel.jsx`的`PCT_FMT`跟`MarketScanPanel.jsx`的`fmtPct`
  邏輯完全相同（`(v*100).toFixed(2)+'%'`）只是換了個名字。**會怎樣**：
  現在沒有立即風險，但下次「統一改成千分位符號」或「殖利率統一顯示
  到小數第3位」這類格式規則調整時，要記得改4~6個地方，容易漏改導致
  同一份頁面裡數字格式不一致而使用者未必看得出來（=悄悄的資料呈現
  不一致，不會報錯但會讓人懷疑數字算錯）。修法：抽一個
  `web/src/utils/format.js`匯出`formatMoney(v, locale)`／
  `formatPct(v, {digits, alreadyPercent})`，四個檔案改成import。
  工作量：小，風險低（純函式，好測試）。

---

## 角度 5：樣式系統

- **三層樣式（tokens.css / app.css / inline style）已檢查，無明顯
  互相打架的情形**：全部138處inline style掃描後，均為一次性版面微調
  （textAlign、fixed input width、marginTop間距），沒有發現inline
  style覆蓋CSS class定義的樣式屬性造成衝突渲染的案例；也確認JSX檔案
  裡沒有任何硬寫的hex色碼（`grep`結果為0），所有顏色都透過CSS
  var()走tokens.css——這代表深色模式的色彩覆蓋不會被繞過。風格上略
  不一致（有些頁面偏好inline style做間距、有些完全靠CSS class），
  但不是打架，可不修。

- **深色模式**：`tokens.css`的light/dark兩組token定義完整對稱（每個
  var都有對應深色版本），`@media (prefers-color-scheme:dark)`與
  `[data-theme="dark"]`兩處數值逐一比對後**一致，無遺漏**。唯一要注意
  的維護點是程式碼註解已經自己提醒「兩個區塊改一邊要記得改另一邊」，
  這是靠人工紀律而非結構保證同步（可以用CSS custom property的繼承或
  一份SCSS變數解決，但目前規模下人工維護的風險可控，可不修）。

- **手機版**：整體處理比預期細緻——`preview-table`／`us-note__table`
  等寬表格都包在`overflow-x:auto`的`.preview-table-wrap`容器裡（app.css
  註解明確引用「寬內容要在自己容器裡scroll，body不能橫向捲動」的設計
  原則），4處響應式`@media`規則涵蓋建倉grid/資產走勢summary/口袋grid/
  情境試算grid在窄螢幕的欄位收斂。**已檢查，未發現整頁橫向捲動風險**。

  - **【該修】觸控熱區偏小**：`.btn-sm`（app.css:220）與
    `.btn-danger-outline`（app.css:221-224）字級.76rem＋padding
    .3rem .7rem，實際渲染高度約22-24px，明顯低於Apple HIG建議的
    44pt／Material建議的48dp觸控熱區。這類按鈕大量出現在Assets.jsx
    的口袋卡片「編輯／封存」（Assets.jsx:446-457）、帳戶清單「編輯／
    封存」（826-837）、投入紀錄「刪除」（674-679）、以及
    UsStockDetail.jsx關注條件的「刪除」（318-325）——且常常兩顆
    按鈕緊鄰排列（`.manage-row__actions{gap:.4rem}`），在手機上容易
    誤觸相鄰按鈕（例如想點「編輯」誤觸旁邊的「封存」，封存還是個
    有點難復原的操作）。修法：`.btn-sm`與`.btn-danger-outline`加大
    padding到至少讓實際點擊區塊接近40px高，或加大按鈕間距。工作量：
    小，但要注意調整後不能讓Assets.jsx已經偏密集的卡片版面更擠。

  - **【該修】NetWorthChart.jsx的逐點「當期投入」數字只在SVG `<title>`
    tooltip裡**（`components/NetWorthChart.jsx:191-196, 203-206`），
    手機觸控沒有hover手勢，這個資訊在PO主要使用的裝置上等於看不到。
    值得注意的是**同一個問題在姊妹圖表NetWorthProjectionChart.jsx已經
    在2026-09-10被PO回報並修正**（該檔案檔頭註解明講「tooltip在手機上
    完全看不到...不能是唯一的資訊來源」），但NetWorthChart.jsx沒有
    同步套用一樣的修法——資產總額／累積投入的主要數字兩張圖都有畫成
    可見文字標籤，只有「當期投入」這個次要但仍有參考價值的數字被漏掉。
    修法：比照NetWorthProjectionChart.jsx的作法，在有空間的點加上
    可見的當期投入標籤，或至少在下方摘要區塊多加一個「本期投入」欄位。
    工作量：小，可能與角度資訊密度需要抓平衡（圖上已經有兩條線的
    數值標籤，再加一組可能變擠，需要視覺判斷微調，不是純技術問題）。

---

## 角度 6：可用性風險（白畫面／崩潰）

- **【必修】整個應用程式沒有任何React Error Boundary**（已用
  `grep -rn "componentDidCatch\|getDerivedStateFromError\|ErrorBoundary"`
  掃描`web/src/`全部24個檔案，0筆命中；`main.jsx`/`App.jsx`也確認未
  包任何錯誤邊界元件）。**會怎樣**：目前多個頁面對後端回應做了較深的
  巢狀解構且沒有防禦性檢查——例如StockDetail.jsx:92-97一次解構11個
  欄位、後續多處直接存取`module_d.latest_batch.length`／
  `concentration.single_stock_cap_pct`／`holdings.holding_row &&
  holdings.holding_row.shares`——只要後端某次回應的結構跟前端預期
  有落差（新版後端部署有bug、schema一次不小心漏了某個欄位、或未來
  新增欄位時忘記同步前端防禦），React在渲染時丟出的TypeError會讓
  **整個SPA白畫面**，不只是那張卡片壞掉，因為沒有任何一層Error
  Boundary攔截，React 18預設行為是把整棵樹卸載。使用者會看到完全
  空白的頁面，不知道發生什麼事，也不知道要重新整理還是等待。這正是
  本專案CLAUDE.md教訓紀錄裡2026-08-22「正式服務切換時靠獨立驗收才
  抓到問題」同一類風險的前端版本——差別是後端有測試守著，前端目前
  沒有任何守門機制。
  修法：在`App.jsx`的`<AppShell>`外層（或至少`<Outlet/>`外層）包一個
  簡單的class component ErrorBoundary，顯示「這個頁面出了問題，請
  重新整理」＋一個重新整理按鈕，而不是任其白畫面。工作量：小
  （一個約30行的通用ErrorBoundary元件＋在App.jsx包一層），效益大
  （防住所有頁面共同的最壞情境）。這是本次審查裡建議優先度最高的
  一項。

- **【該修，已於角度4提及】** Home.jsx「資產總覽」區塊寫死顯示
  「資產分頁尚未啟用」（Home.jsx:196-202），但Assets分頁自
  2026-08-22（`f4fe960`）起就已完整上線且持續在用（`pockets`/
  `accounts`/建倉/情境試算/資產走勢全部可動）。經`git log -p`回溯
  確認：這段文字是當初與Assets分頁同一個commit一起加入的初始
  placeholder，之後Home.jsx雖有兩次功能性更新（新增今日新候選/策略
  設定），這段placeholder從未被移除或更新。**會怎樣**：PO每天打開
  首頁，都會看到一段告訴自己「這個功能還沒做」的文字，而這個功能
  其實他自己天天在用——輕微但持續的錯誤資訊，容易造成「這個系統的
  狀態說明不可信」的觀感磨損。修法：刪掉這個placeholder區塊，或
  改成呼叫`/api/assets/net-worth-history`顯示目前資產總額摘要（如果
  想讓首頁真的有用）。工作量：小（純刪除）到中（真的接資料）。

- **PO最常用路徑（首頁→投資→個股詳情）已檢查，無其他重大體驗問題**：
  三個頁面（Home.jsx／Dashboard.jsx／StockDetail.jsx）都有完整的
  loading/error/empty三態處理，路由切換使用react-router標準機制，
  没有發現點擊後長時間無回饋或導致假死的操作。搜尋框300ms
  debounce＋URL query string同步的設計（Dashboard.jsx:107-127）
  也考慮到重新整理/分享連結不遺失篩選狀態，體驗上是加分項。

---

## 檢查角度清單（供覆蓋度參考）

1. 全檔案行數統計＋逐檔通讀（Assets.jsx／StockDetail.jsx／
   UsStockDetail.jsx／Dashboard.jsx／UsStocks.jsx／
   QuickInputPanel.jsx／ScreenPanel.jsx／MarketScanPanel.jsx／
   Home.jsx／Photos.jsx／App.jsx／AppShell.jsx／theme.js／
   ThemeToggle.jsx／icons.jsx／UsStockImport.jsx全文）
2. `grep`交叉比對：`cancelled`/`AbortController`/`useEffect`（race
   condition覆蓋率）、`ErrorBoundary`相關API（error boundary存在性）、
   `fetch(`（是否繞過client.js）、`function money/pct/num`（重複格式化
   函式）、`instanceof ApiError`（錯誤處理一致性）、`#[hex color]`
   （dark mode硬編碼色彩）、`dangerouslySetInnerHTML`（XSS面）、
   `@media`（響應式規則覆蓋率）
3. `git log`/`git log -p`回溯Home.jsx歷史，確認「資產分頁尚未啟用」
   placeholder的來源與是否曾被更新
4. 對照後端`app/routers/stock_detail.py`／`assets.py`原始碼，驗證
   StockDetail.jsx解構的巢狀欄位在後端是否保證存在、
   `handleDeleteContribution`用POST而非DELETE是否為前端bug還是
   對應後端既有路由設計
5. 逐一比對StockComboChart.jsx／NetWorthChart.jsx／
   NetWorthProjectionChart.jsx三個圖表元件的props介面與內部邏輯，
   評估已重用與可重用但未重用的部分
6. `package.json`確認技術棧（React 18.3.1＋react-router-dom 6.23.1，
   無額外狀態管理庫或UI框架依賴）
