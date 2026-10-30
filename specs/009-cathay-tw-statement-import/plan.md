# Implementation Plan: 國泰台股日對帳單 Email 自動匯入

**Branch**: `009-cathay-tw-statement-import` | **Date**: 2026-10-31 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/009-cathay-tw-statement-import/spec.md`

## Summary

每晚由 launchd 排程執行 `statement_import.py`：以應用程式密碼唯讀連線 Gmail，只取國泰台股日對帳單，
用鑰匙圈中的身分證字號經 `qpdf`（密碼走 stdin）解密、`pdftotext -layout` 擷取文字，解析成交與完整庫存，
在**單一 SQLite 交易**內寫入交易紀錄（委託書號正規化防重複）、庫存快照（對帳單為準、成本沿用既有規則）
與處理紀錄，再以既有 Telegram 通知模組送摘要。另提供唯讀比對工具 `statement_reconcile.py`，把 PO 放在
`/Users/stander/STND-對帳單/` 的交易明細表 PDF 與資料庫逐筆比對。技術決策見 [research.md](research.md)。

## Technical Context

**Language/Version**: Python 3.9（PO 的 Mac 系統 Python；排程以 `/usr/bin/python3` 執行）
**Primary Dependencies**: 僅標準庫（`imaplib`、`email`、`sqlite3`、`subprocess`）；系統層新增
`qpdf`、`poppler`（`pdftotext`），以 Homebrew 安裝；鑰匙圈用 macOS 內建 `security`
**Storage**: 既有 SQLite `alphavibe.db`（KBStore），擴欄 2 個、新增表 3 張（[data-model.md](data-model.md)）
**Testing**: `unittest`（`poc/kb-mcp/tests/`）；IMAP、鑰匙圈、`qpdf`／`pdftotext` 皆以可注入的介面
在測試中替換；另有以 LibreOffice＋qpdf 產生加密中文 PDF 的整合測試（工具不存在時自動略過）
**Target Platform**: PO 的 Mac（正式環境 worktree `AlphaVibe-prod`，launchd）
**Project Type**: 既有 poc/kb-mcp 命令列＋排程模組（不改 app/、web/）
**Performance Goals**: 一份對帳單處理 < 30 秒；整年度交易明細表比對 < 1 分鐘
**Constraints**: 不寫入密碼／個資到任何檔案或日誌；解密內容不落地；寫入全有或全無；Python 3.9 語法
**Scale/Scope**: 每日 0～1 份對帳單；交易紀錄數百筆

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**狀態：無可評估的 gate**（與 005～008 相同）。`.specify/memory/constitution.md` 仍是未填寫的樣板。
改以專案既有鐵則自我檢查：poc/kb-mcp 僅標準庫 ✅（系統層工具比照 exiftool 先例）；Python 3.9 相容 ✅；
測試不得指向正式庫 ✅（全部用暫存目錄）；文件繁體中文 ✅。

## Project Structure

### Documentation (this feature)

```text
specs/009-cathay-tw-statement-import/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/cli.md
├── checklists/requirements.md
└── tasks.md            # /speckit.tasks 產出
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── order_ref.py                    # 新：委託書號正規化（R4）
├── statement_pdf.py                # 新：qpdf|pdftotext 解密擷取（R2）
├── keychain_secrets.py             # 新：讀 macOS 鑰匙圈（R3）
├── cathay_statement_parser.py      # 新：日對帳單文字解析（R8）
├── statement_mailbox.py            # 新：Gmail IMAP 唯讀取信（R1）
├── statement_import.py             # 新：排程主程式（CLI 1）
├── statement_reconcile.py          # 新：唯讀比對工具（CLI 2）
├── holdings_sync.py                # 改：抽出純函式 apply_trades_to_positions（R6）
├── kb_store.py                     # 改：擴欄、新表、apply_statement_import、order_ref 正規化比對
├── check_scheduled_jobs.py         # 改：新增本排程健康檢查（R7）
└── tests/test_statement_*.py       # 新

ops/launchd/com.alphavibe.statementimport.plist   # 新（R7）
```

**Structure Decision**: 全部放在 poc/kb-mcp（與既有排程、解析器、KBStore 同處），不新增 app/ 路由或前端。

## Complexity Tracking

| 項目 | 為何需要 | 較簡單的替代方案為何不行 |
|---|---|---|
| 新增系統依賴 qpdf、poppler | 標準庫無法解 AES 加密 PDF | Python 第三方套件同樣是新依賴，且排程用系統 Python |
| `apply_statement_import` 專用寫入方法 | FR-009 全有或全無 | 既有寫入方法每筆 commit，無法整份還原 |
