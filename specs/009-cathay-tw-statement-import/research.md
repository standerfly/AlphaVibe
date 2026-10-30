# Research: 國泰台股日對帳單 Email 自動匯入

**Feature**: 009-cathay-tw-statement-import
**Date**: 2026-10-31

## R1. 讀取 Gmail

- **Decision**：Python 標準庫 `imaplib`＋`email`，以 Gmail「應用程式密碼」登入
  `imap.gmail.com:993`（SSL）。用 `EXAMINE`（唯讀選取，不會把信標成已讀）開「所有郵件」，
  以 Gmail 擴充搜尋 `X-GM-RAW "from:e-notification@ebill1.cathaysec.com.tw newer_than:Nd"`
  取得候選 UID，**只抓 header**（`BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)]`）
  在本機驗證寄件人與主旨（主旨需 RFC 2047 解碼後完全等於「國泰綜合證券日對帳單」），
  通過的才用 `BODY.PEEK[]` 取整封信、取出 PDF 附件。
- **Rationale**：零外部依賴（poc/kb-mcp 慣例）、Python 3.9 可用；只讀不改信箱；搜尋在
  Gmail 伺服器端先過濾寄件人，本機再嚴格驗證，其他信件的內容完全不會被讀取（FR-001、FR-012）。
- **Alternatives**：Gmail API＋OAuth——需要 Google Cloud 專案、OAuth 同意畫面與 refresh token
  管理，對單一使用者過重；Gmail 篩選器自動轉寄到另一信箱——多一個需要管理的帳號。
- **前提**：PO 的 Google 帳號需開啟兩步驟驗證才能建立應用程式密碼；IMAP 需在 Gmail 設定中啟用。

## R2. 解密 PDF 與擷取文字

- **Decision**：`qpdf --password-file=- --decrypt <pdf> -` 解密到 stdout（密碼經 stdin 傳入），
  管線接 `pdftotext -layout - -` 擷取保留版面的文字。兩者以 Homebrew 安裝（`brew install qpdf poppler`），
  比照相片功能 `exiftool` 的系統層依賴先例。執行檔路徑依序找 `/opt/homebrew/bin`、`/usr/local/bin`、
  `PATH`（launchd 預設 PATH 不含 Homebrew，機票排程踩過）。
- **Rationale**：2026-10-31 沙盒實測（LibreOffice 產生含中文表格的 PDF、qpdf AES-256 加密）：
  正確密碼可完整擷取中文欄位；錯誤密碼 qpdf 回 exit 2、訊息 `invalid password`，可明確判定。
  密碼不出現在行程參數（`ps` 看不到）、解密內容不落地（FR-012「解密後的內容不得留存」）。
- **Alternatives**：`pdftotext -upw <密碼>`——密碼會出現在行程參數；Python `pypdf`＋`cryptography`——
  需要第三方套件，且排程使用系統 `/usr/bin/python3`。
- **風險**：真實國泰 PDF 的 `-layout` 輸出版面需在 PO 的 Mac 上用真實檔案確認（沙盒無真實樣本）；
  解析器以「欄位順序＋數字樣式」辨識，而非固定欄寬，降低版面差異影響。

## R3. 密碼保管

- **Decision**：macOS 鑰匙圈 generic password，service `stnd-statement-import`，三個 account：
  `gmail-address`、`gmail-app-password`、`pdf-password`。程式以內建 CLI
  `security find-generic-password -s stnd-statement-import -a <account> -w` 讀取。PO 用
  `security add-generic-password ... -w`（不帶值，互動輸入）存入，密碼不進 shell 歷史。
- **Rationale**：FR-012；零依賴；launchd 以使用者身分執行，可讀登入鑰匙圈（首次可能跳出允許
  存取的對話框，PO 選「永遠允許」）。
- **Alternatives**：環境變數或設定檔——違反 FR-012。

## R4. 委託書號正規化（FR-005）

- **Decision**：`normalize_order_ref(s)`：去除連字號與空白後，以 `^([A-Za-z])([0-9A-Za-z]{4})(\d{2})?$`
  比對，回傳 `前綴+4碼+序號`（序號缺省為 `00`），大小寫保留；不符合樣式者回傳去除空白後的原字串
  （不猜）。既有 `trade_ledger_order_ref_exists()` 改為比對正規化後的值，讓手動匯入路徑同時受益。
- **Rationale**：實測資料庫已有 `kABCD`／`k-ABCD-00` 兩種寫法造成的重複（SRC-004）；日對帳單為
  `kABCD00`。三種寫法正規化後皆為 `kABCD00`；`k-ABCD-01` 為 `kABCD01`，與 `-00` 區分。
- **實作**：成交筆數僅數百，比對時讀出全部既有 `order_ref` 正規化成集合即可，不需新增索引欄位。

## R5. 原子寫入（FR-009）

- **Decision**：新增 `KBStore.apply_statement_import(...)`：在同一個 SQLite 交易內寫入成交、庫存快照、
  處理紀錄，最後一次 commit；任何例外 rollback 後往上拋。既有 `save_trade_ledger_entry()`／
  `save_holdings()` 每筆 commit，不可直接重用於本流程。
- **Rationale**：「寫一半失敗」必須全部還原。

## R6. 平均成本（FR-006）

- **Decision**：沿用 `holdings_sync.py` 已驗證的規則（買進加權平均、賣出不變、舊均價缺值則保持缺值），
  抽出為純函式 `apply_trades_to_positions(baseline, trades)` 供兩邊共用。每檔最終成本依序取：
  (1) 以基準庫存套用本次新寫入成交的模擬結果；(2) 基準庫存原有成本；(3) 以交易紀錄完整重播推算
  （重播後股數須等於對帳單股數才採用，否則視為推算不出來）；(4) 留空並通知（每檔只通知一次，
  記錄在 `statement_alerts`）。
- **Rationale**：PO 決策 Q-002；與既有同步邏輯一致，避免兩套成本算法。

## R7. 排程與健康檢查

- **Decision**：新 launchd 工作 `com.alphavibe.statementimport`，每日 20:15、23:15、07:45 執行（對帳單
  約 18:30～19:15 寄達；晚上兩次涵蓋延遲寄送，清晨一次補 Mac 晚間睡眠），以系統 `/usr/bin/python3`
  執行（標準庫即可）。每次執行（含無新信）都寫一筆心跳到 `statement_import_runs`；既有
  `check_scheduled_jobs.py`（04:00）新增檢查：超過 30 小時沒有心跳＝critical；最近一份對帳單失敗＝warning；
  Telegram 送出失敗＝warning。
- **Rationale**：SC-001、SC-004；與既有排程（02:00、03:30、03:45、04:00、06:00、09:30、17:00）錯開。

## R8. 解析器策略

- **日對帳單**：以區塊標題（「交割金額」「交易明細」「庫存明細」）切段；成交列以「名稱 類別(集/OT/興＋買/賣)
  股數 單價 金額 手續費 交易稅 … 委託書號（行尾）」辨識；成交日取自交割金額區塊第一個日期（西元
  `YYYY/MM/DD`）；庫存列以「4～6 碼代號 名稱 收盤價(可含▲▼、0) 集保股數 市值 …」辨識；忽略「總合計」
  「集保市值總計」等彙總列；找不到「交易明細」或「庫存明細」區塊、或成交列欄位數不足＝格式無法辨識（FR-009）。
  沒有成交的對帳單（只有庫存）視為合法。
- **交易明細表**（比對工具）：直接沿用 `trade_ledger_parser.parse_trade_ledger_text()`（民國年、CD、名稱、
  股數、單價、行尾委託書號），不另寫一套。
- **名稱→代號**：先用同份對帳單庫存明細（名稱→代號），再用 `stock_alias_resolver.resolve_stock_codes()`。
