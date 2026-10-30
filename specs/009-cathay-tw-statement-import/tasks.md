# Tasks: 國泰台股日對帳單 Email 自動匯入

**Input**: Design documents from `/specs/009-cathay-tw-statement-import/`
**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/cli.md、quickstart.md（皆已完成）

**Tests**: 本 feature 直接寫入 PO 的財務紀錄且不經事前確認（FR-009 全有或全無、FR-005 不重複是正確性的
唯一保護），測試全部納入、不視為選配。測試一律使用暫存資料目錄，絕不指向 `poc/data`。

**Organization**: 依 spec.md 的 3 個 User Story（US1 每日自動匯入、US2 不重複／不出錯／不半套、US3 唯讀比對工具）。
US1 與 US2 同為 P1 且共用同一條流程，實作上 US2 的保護機制在 Foundational 與 US1 一併完成，US2 階段以測試驗證。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行進行（不同檔案、不互相依賴）
- **[Story]**：所屬 User Story（US1／US2／US3）

---

## Phase 1: Setup

- [ ] T001 執行 `python3 -m unittest discover -s poc/kb-mcp/tests`，記錄目前失敗清單作為基準線（沙盒既有失敗：exiftool／sips 等環境因素）
- [ ] T002 驗證解密擷取管線：LibreOffice 產生含中文表格的 PDF、`qpdf` AES-256 加密，`qpdf --password-file=- --decrypt` 管線接 `pdftotext -layout` 可擷取中文；錯誤密碼 exit 2（research R2，已於規劃時實測通過）

---

## Phase 2: Foundational（全部 User Story 的基礎）

- [ ] T003 [P] 新增 `poc/kb-mcp/order_ref.py`：`normalize_order_ref()`（research R4）＋ `tests/test_statement_order_ref.py`（三種寫法、序號 01 區分、大小寫保留、不符樣式原樣回傳、空值）
- [ ] T004 [P] 新增 `poc/kb-mcp/keychain_secrets.py`：`get_secret(account)` 呼叫 `security find-generic-password -s stnd-statement-import -a <account> -w`；找不到時拋 `SecretNotFound`（訊息不含值）；可注入 runner 供測試＋測試
- [ ] T005 [P] 新增 `poc/kb-mcp/statement_pdf.py`：`find_tool(name)`（/opt/homebrew/bin → /usr/local/bin → PATH）、`extract_text(pdf_bytes_or_path, password)`：qpdf 經 stdin 收密碼、解密到 stdout 管線接 pdftotext，錯誤分類 `WrongPassword`／`PdfToolMissing`／`PdfUnreadable`；不寫任何暫存檔＋測試（含工具不存在時略過的真實加密 PDF 整合測試）
- [ ] T006 `poc/kb-mcp/kb_store.py`：`_MIGRATIONS` 新增 `trade_ledger.fee`、`trade_ledger.tax`；`SCHEMA` 新增 `statement_imports`、`statement_import_runs`、`statement_alerts`（data-model.md）
- [ ] T007 `poc/kb-mcp/kb_store.py`：`trade_ledger_order_ref_exists()` 改為比對 `normalize_order_ref()` 後的值；新增 `existing_normalized_order_refs()`；更新既有相關測試的預期（手動匯入路徑同受益）
- [ ] T008 `poc/kb-mcp/holdings_sync.py`：抽出純函式 `apply_trades_to_positions(baseline_rows, trades)`（不寫庫），`sync_holdings_from_trades()` 改呼叫它，行為不變（既有測試須全綠）
- [ ] T009 `poc/kb-mcp/kb_store.py`：新增 `apply_statement_import(trades, holdings_rows, snapshot_date, write_holdings, import_row)`——單一交易寫入成交（含 add_sequence、fee、tax、order_ref、source_ref）、庫存快照、`statement_imports` 紀錄（同 message_id 則更新）；例外時 rollback 後拋出；另新增 `statement_import_status(message_id)`、`latest_holdings_date()`、`record_import_run()`、`alert_once(kind, key)`＋測試（寫一半拋錯時資料庫完全不變）

**Checkpoint**：基礎模組與資料表完成，既有測試基準線不變

---

## Phase 3: User Story 1 — 成交與庫存每天自動進 STND（P1）🎯 MVP

- [ ] T010 [P] [US1] 新增 `poc/kb-mcp/cathay_statement_parser.py`：`parse_daily_statement(text)` → `{statement_date, trades, holdings}`（research R8）；`StatementFormatError`；`tests/test_statement_parser.py`：單筆買進、多筆買賣含 OT／興、零股、跨頁、收盤價 0 與 ▲▼、只有庫存無成交、缺區塊＝格式錯誤
- [ ] T011 [P] [US1] 新增 `poc/kb-mcp/statement_mailbox.py`：`fetch_statements(imap_factory, address, app_password, days)` → 依日期排序的 `[{message_id, date, subject, sender, pdf_bytes}]`；EXAMINE 唯讀、X-GM-RAW 寄件人搜尋、只抓 header 嚴格驗證寄件人與主旨（RFC 2047 解碼）後才抓內容；`tests/test_statement_mailbox.py` 以假 IMAP 物件測試（寄件人不符、主旨不符、無附件、多封排序）
- [ ] T012 [US1] 新增 `poc/kb-mcp/statement_import.py`：`process_statement(store, statement, message_id, resolver)` —— 名稱→代號（庫存明細優先、再 `stock_alias_resolver`）、委託書號正規化防重複、成本計算（research R6 四層順序）、FR-013 較舊對帳單不寫庫存、FR-007 差異、呼叫 `apply_statement_import`；回傳摘要
- [ ] T013 [US1] `statement_import.py`：`format_summary()` 與通知（contracts §3）；成本未知每檔只通知一次、錯誤同類一天一次（`alert_once`）；Telegram 失敗記入 `statement_import_runs.notify_failed`
- [ ] T014 [US1] `statement_import.py` CLI：`--data-dir`、`--days`、`--dry-run`、`--rerun`、`--from-file`（contracts §1）；每次執行寫心跳；結束碼語意
- [ ] T015 [US1] `tests/test_statement_import.py`：US1 驗收情境 1～6（新股、加碼加權平均、只賣不改成本、未列出股票移除、庫存差異列入通知、成本未知只通知一次）
- [ ] T016 [P] [US1] 新增 `ops/launchd/com.alphavibe.statementimport.plist`（20:15、23:15、07:45；`/usr/bin/python3`；PATH 含 Homebrew；WorkingDirectory `AlphaVibe-prod`；log 路徑）＋ `plutil -lint` 可通過的格式

**Checkpoint**：US1 可獨立運作（`--from-file` 處理一份 PDF → 寫入 → 通知）

---

## Phase 4: User Story 2 — 不重複、不出錯、不半套（P1）

- [ ] T017 [US2] `tests/test_statement_import.py` 補 US2 驗收情境：重複處理無變化、與交易明細表寫法（含連字號）既有成交不重複、同委託不同序號兩筆都寫、PDF 打不開與格式錯誤不寫任何資料、寫入中途失敗整份還原、名稱對不到＝partial 其餘照寫、partial 補上名稱後自動重試補寫、多份依日期舊到新且舊對帳單不覆蓋新庫存、寄件人或主旨不符不處理
- [ ] T018 [US2] `poc/kb-mcp/check_scheduled_jobs.py`：新增 `check_statement_import(data_dir)`（30 小時無心跳 critical、最近一份 failed warning、notify_failed warning；資料表不存在＝尚未上線視為 ok）並加入 `CHECKS`＋測試

---

## Phase 5: User Story 3 — 唯讀比對工具（P2）

- [ ] T019 [US3] 新增 `poc/kb-mcp/statement_reconcile.py`：預設讀 `/Users/stander/STND-對帳單/` 最新 PDF、鑰匙圈密碼解密、`trade_ledger_parser.parse_trade_ledger_text()` 解析、SQLite 唯讀模式（`file:...?mode=ro`）開資料庫、期間內逐筆比對輸出重複／缺漏／不一致（文字與 `--json`）；結束碼 0／2
- [ ] T020 [US3] `tests/test_statement_reconcile.py`：已知「一筆重複、一筆缺漏、一筆價格不同」得到恰好三筆；全部一致；資料庫與資料夾檔案執行前後完全相同；PDF 打不開回 2；預設挑最新檔

---

## Phase 6: Polish & Cross-Cutting

- [ ] T021 [P] 更新 `poc/kb-mcp/README.md`、`docs/architecture.md`（排程表新增 statementimport、系統依賴 qpdf／poppler）、`CLAUDE.md` 常用查證點
- [ ] T022 全部測試與基準線比對（T001）：新增測試全綠、既有失敗清單不變；Python 3.9 語法檢查（`ast.parse(feature_version=(3, 9))`）
- [ ] T023 秘密／個資掃描：新增檔案與測試資料不含真實身分證字號、密碼、信箱密碼、PO 真實成交數值

## Dependencies & Execution Order

- Phase 1 → Phase 2 → Phase 3（US1）→ Phase 4（US2 驗證）→ Phase 5（US3，可在 Phase 2 後平行）→ Phase 6
- T003、T004、T005 互相平行；T006 → T007 → T009；T008 獨立
- T010、T011 互相平行，皆在 T012 之前

## 上線前（不在本 tasks 範圍，PO 參與）

PO 在 Mac 上的一次性設定與實測、整年度比對與資料修正、部署與安裝排程、驗證期 3 次——見 quickstart.md。
