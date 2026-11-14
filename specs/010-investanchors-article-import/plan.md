# Implementation Plan: 定錨產業筆記文章自動匯入

**Branch**: `010-investanchors-article-import`（實際工作分支 `claude/admiring-ptolemy-1jaw79`）| **Date**: 2026-11-15 | **Spec**: [spec.md](spec.md)
**Input**: `specs/010-investanchors-article-import/spec.md`（需求基線 `docs/spec-intake/investanchors-import/`，Accepted 2026-11-14）

## Summary

排程（launchd，PO 的 Mac）平常只唯讀檢查 Gmail 的定錨通知信；有新信、每週核對日、或歷史回補未完成時，
才啟動一次**全新、無持久化 profile 的 Playwright 瀏覽器**登入、依文章 ID 逐篇取全文與圖片、**跑完登出並
關閉瀏覽器**，把文章存進獨立的 `articles.db`（SQLite）＋本機圖片檔；表格圖用視覺模型 API 轉寫成文字
（標示機器轉寫、保留原圖）。台股與美股兩個 MCP 連接器各新增唯讀 `search_articles`／`get_article`，讀同一個
`articles.db`。設計重心是「低頻、不佔登入名額、失敗不傷既有資料」，不是效能。

技術路線沿用 008／009 已驗證的樣式：Python 進入點腳本＋依賴注入（可測）、Node/Playwright 以 subprocess＋
JSON Lines 溝通、獨立 store＋`_deps.py` 資料目錄守衛、鑰匙圈取密、`notify.send_telegram` 通知。

## Technical Context

**Language/Version**: Python 3.9（這台機器唯一版本，不得用 ≥3.10 語法）；Node 20+（`/opt/homebrew/bin/node`，Playwright `^1.50.0`，沿用 `poc/kb-mcp/scraper/package.json`）
**Primary Dependencies**: 標準庫（`imaplib`、`sqlite3`、`urllib`、`html.parser`、`subprocess`）；Playwright（既有）；**不新增 Python 套件**（requirements.txt 只有 yfinance，視覺模型以 `urllib` 呼叫 HTTP API，不裝 SDK）
**Storage**: 新獨立 `poc/data/articles.db`（SQLite，`check_same_thread=False`）＋圖片檔 `poc/data/articles_images/<article_id>/<n>.<ext>`；不碰 `alphavibe.db`／`us_stocks.db`（FR-015）
**Testing**: `python3 -m unittest discover -s poc/kb-mcp/tests`；新增 `test_article_store.py`／`test_investanchors_*.py`；以注入 fake（IMAP／scraper／模型／notifier／時鐘）測試，不連真網站；以獨立 `tempfile` data-dir
**Target Platform**: macOS（PO 的 MacBook，launchd；部署於 `AlphaVibe-prod` worktree，`ops/deploy.sh`）
**Project Type**: 排程 CLI ＋ 兩個 MCP 唯讀工具（無 STND 網頁頁面，spec 明列不在範圍）
**Performance Goals**: 無吞吐目標；反向目標——每次 ≤5 篇、每日 ≤1 次登入（每晚 23:00）、篇間隔 30～90 秒隨機（FR-007）；歷史回補只補最近半年（PO 2026-11-15）、最多每天 5 篇，預估約 11～26 天
**Constraints**: 每次執行結束必登出；不留 cookie／storageState 檔；日誌／通知不含帳密、cookie、全文；失敗同次不重試；被擋→整次中止並延後 ≥1 天
**Scale/Scope**: 1 位使用者；文章總數待探查（預期數百～數千篇）；單篇約數十 KB 文字＋數張圖

## Constitution Check

`.specify/memory/constitution.md` **仍是未填寫的空白模板**（全為 `[PRINCIPLE_n_NAME]` 佔位），沒有可評估的
原則，故本 gate 無條文可檢查，**不視為通過或失敗**。改以 `CLAUDE.md` 與 spec 的硬性要求作為實質 gate：

| 實質 gate（來源） | 設計如何滿足 |
|---|---|
| 獨立 db、不污染台股／美股資料（FR-015、CLAUDE.md 美股先例） | 新 `articles.db`＋`article_deps.py`；建構子不寫入任何資料列（2026-08-22 教訓） |
| 資料目錄必須明確指定、正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` | `article_deps.py` 複製 `us_stock_deps.py` 守衛；CLI 走 `--data-dir` |
| 帳密不進 repo／日誌（FR-001、009 鑰匙圈教訓） | 新 service `stnd-investanchors`；禁止 dump-keychain／-w／-g |
| 低頻硬上限、放寬須 PO 同意（FR-007） | 上限寫成常數＋執行紀錄表強制檢查，超限直接拒絕啟動 |
| 驗證不自驗、獨立驗收（全域規則） | tasks 階段排入 fresh-agent 驗收；回補完成需與網站「總覽」半年內文章逐篇核對（SC-001） |

建議（不阻擋本 plan）：PO 另行決定是否要用 `/speckit-constitution` 填寫原則；目前各 feature 靠 CLAUDE.md 運作。

**設計後重新評估**：Phase 1 設計後上表五項仍全部滿足，無需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/010-investanchors-article-import/
├── plan.md              # 本檔
├── research.md          # Phase 0：決策＋「需在 PO 的 Mac 探查」清單（含探查腳本規格）
├── data-model.md        # Phase 1：articles.db schema、狀態機、驗證規則
├── quickstart.md        # Phase 1：PO 一次性設定、探查、上線、日常、已知坑
├── contracts/
│   ├── cli.md           # 匯入進入點、探查工具、補轉寫、核對工具
│   └── mcp-tools.md     # search_articles／get_article（台股＋美股）
└── tasks.md             # /speckit-tasks 產生（本指令不建立）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── article_store.py              # 新：ArticleStore（articles.db；比照 flight_store.py）
├── investanchors_mailbox.py      # 新：IMAP 唯讀取信，抽出通知信的標題＋文章 ID（參考 statement_mailbox.py）
├── investanchors_import.py       # 新：排程進入點（觸發判斷、配額、退避、編排、通知）
├── article_transcribe.py         # 新：表格圖→文字（視覺模型 HTTP 呼叫，金鑰自鑰匙圈）
├── article_probe.py              # 新：Phase 0 一次性探查工具（唯讀、極低頻）
├── article_reconcile.py          # 新：回補完成後與網站「總覽」逐篇核對（唯讀）
├── keychain_secrets.py           # 改：支援第二個 service（stnd-investanchors）
├── notify.py                     # 不改（直接呼叫 send_telegram）
├── server.py                     # 改：TOOLS＋call_tool 加兩個工具
├── server_readonly.py            # 改：READONLY_TOOLS／SCHEMAS 加兩個工具
├── us_stock_mcp_server.py        # 改：TOOLS＋call_tool 加兩個工具（台美刻意各自一份）
├── check_scheduled_jobs.py       # 改：新增 check_investanchors_import()
├── scraper/
│   └── investanchors_scraper.js  # 新：Playwright 登入→取清單／文章→登出（stdin JSON、stdout JSONL）
└── tests/
    ├── test_article_store.py
    ├── test_investanchors_mailbox.py
    ├── test_investanchors_import.py
    ├── test_article_transcribe.py
    ├── test_pnl.py               # 改：test_tool_counts 48→50、29→31
    └── test_traceability.py      # 改：test_tools_list_has_forty_eight（:252-261）48→50，函式名與 docstring 同步，預期工具名清單加兩項

app/
└── article_deps.py               # 新：資料目錄守衛（複製 us_stock_deps.py 邏輯）

ops/launchd/
└── com.alphavibe.investanchorsimport.plist   # 新：排程
```

**Structure Decision**: 全部落在既有 `poc/kb-mcp/`（排程與 MCP 的既有所在），不新增 FastAPI router、不動 `web/`
（STND 閱讀頁不在範圍）。`app/` 只新增資料目錄守衛供日後或 MCP 閘道使用，與 `us_stock_deps.py` 並列。

## Complexity Tracking

無 Constitution 違規需說明。唯一偏離慣例之處：**不使用 FTS5**（見 research R6，2 字中文詞搜不到），改用
`LIKE` 掃描；這是簡化而非增加複雜度。
