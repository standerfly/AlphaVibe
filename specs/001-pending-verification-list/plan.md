# Implementation Plan: Pending Verification List

**Branch**: 本 session 固定於 `claude/watchlist-feature-discussion-uzo3ga`
工作，未另建 `001-pending-verification-list` 分支（`.specify/scripts/
bash/setup-plan.sh` 會因分支命名不符而 ERROR，故本次略過該腳本、手動
建立本檔案——與 `spec.md` Feature Branch 欄位記錄的處理方式一致）
**Date**: 2026-08-27
**Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-pending-verification-list/spec.md`

**Note**: 本檔案依 `/speckit.plan` 的執行流程手動填寫（略過
`setup-plan.sh` 的原因見上方 Branch 欄位）。

## Summary

新增一個結構化的「待觀察／待驗證判斷」機制：使用者透過 Claude／MCP tool
登記一筆帶有觸發條件與預期時間點的判斷，資料以獨立 SQLite 表儲存完整
「判斷→觸發→結果」軌跡，STND 首頁新增一個唯讀區塊顯示「已到期／即將
到期」項目。技術做法完全沿用本 repo 既有三層架構——不新增框架、不新增
語言，只是既有模式（`kb_store.py` 新表＋`server.py` 新 MCP tool＋`app/`
新 router＋`web/` 首頁新增一個 fetch 區塊）的又一次套用，比照
`app/routers/assets.py` 上線先例的規模與風格。

## Technical Context

**Language/Version**: Python 3.9 相容語法（`poc/kb-mcp/` 既有限制，見
`CLAUDE.md` 教訓紀錄——本機曾用 3.9.6，正式服務環境用更新版本但程式碼
仍維持 3.9 相容寫法，如 `open(newline=)` 而非 `Path.write_text(newline=)`）
／前端 JavaScript（React 18，`web/package.json`）
**Primary Dependencies**: 後端沿用既有 `fastapi==0.128.8`、
`uvicorn==0.39.0`（`app/requirements.txt`，Q-046 授權後僅有的兩個外部
套件，不新增第三個）；`poc/kb-mcp/` 資料層與 MCP server 維持純標準庫
（`sqlite3`、`json`，無外部套件）；前端沿用既有 `react`／
`react-router-dom`（無新增套件）
**Storage**: SQLite（`poc/kb-mcp/kb_store.py` 既有 `SCHEMA`／
`_migrate()` 機制），新增獨立表 `pending_verifications`，不修改既有
`stances`／`comments`／`stock_themes`／`position_plans` 等既有表
**Testing**: `unittest`（`python3 -m unittest discover -s poc/kb-mcp/
tests`，PoC 層既有慣例）＋ `app/tests/test_smoke.py`（STND 層既有
深度比對測試慣例，見 `CLAUDE.md` 2026-08-19 教訓紀錄：斷言要用
`class="` 前綴等渲染形式，不能裸字串比對；2026-08-22 教訓紀錄：新表
上線前需要併發測試，不能只測依序單一請求）
**Target Platform**: 個人 macOS 本機常駐服務（`launchctl` LaunchAgent，
`uvicorn app.main:app`），透過 ngrok 固定網址對外服務——本功能不改動
部署方式
**Project Type**: Web service（既有 `poc/kb-mcp/`＋`app/`＋`web/` 三層
架構的延伸功能，非新專案）
**Performance Goals**: 個人單一使用者、低併發（比照既有規模，非高流量
服務）；不設特別效能目標，沿用既有 router 的既定回應速度
**Constraints**: 沿用既有分層邊界——`app/` 直接 import `poc/kb-mcp/*.py`
既有函式風格，不在 `app/` 重寫商業邏輯（`kb_store.py` 新方法才是商業
邏輯本體）；首頁區塊為唯讀（Q-003a 已定案），不做就地操作 UI
**Scale/Scope**: 單一使用者、預估待觀察項目累積量為個位數到低兩位數
（比照既有 `stances`／`comments` 表使用頻率），無需分頁/效能優化設計

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 目前仍是未填寫的範本檔案（`[PROJECT_
NAME] Constitution` 佔位字串，未曾被 `/speckit.constitution` 實際填寫
過）——本專案尚未制定正式的 constitution，因此沒有具體條文可供比對，
本階段無 gate 可評估，視為 PASS（無違反項目）。若日後補上 constitution，
應回頭補跑這個檢查。

**Post-Phase 1 re-check**：`data-model.md`／`contracts/`／
`quickstart.md` 完成後重新檢視，設計內容未新增任何脫離既有架構的元素
（沒有新語言、新框架、新專案），維持 PASS。

## Project Structure

### Documentation (this feature)

```text
specs/001-pending-verification-list/
├── plan.md              # 本檔案
├── research.md          # Phase 0 產出
├── data-model.md         # Phase 1 產出
├── quickstart.md         # Phase 1 產出
├── contracts/             # Phase 1 產出（MCP tool schema／HTTP API 摘要）
└── tasks.md               # Phase 2 產出（/speckit.tasks，本次不做）
```

### Source Code (repository root)

本 repo 是既有的三層架構（PoC 資料/邏輯層＋FastAPI 後端＋React 前端＋
獨立 MCP stdio server），本功能延伸既有結構，不新增任何新專案/新目錄
樹：

```text
poc/kb-mcp/
├── kb_store.py         # 新增 pending_verifications 表 + 4個方法
│                        # （save/list/get/resolve），沿用既有 SCHEMA/
│                        # _migrate() 機制
├── server.py            # TOOLS 清單新增4個 MCP tool schema +
│                        # dispatch 邏輯新增對應分支
└── tests/
    └── test_kb_store.py  # 新增 pending_verifications 相關單元測試
                          # （若既有測試檔案已有合適分類則併入，否則新增）

app/
├── routers/
│   └── pending_verifications.py  # 新 router：3個 endpoint
│                                  # （create/list/resolve），比照
│                                  # assets.py 風格（Pydantic model +
│                                  # _raise_from_value_error 錯誤轉換）
├── main.py               # 新增一行 app.include_router(...)
└── tests/
    └── test_smoke.py     # 新增深度比對測試案例（含併發測試，
                           # 比照2026-08-22教訓紀錄）

web/src/
├── pages/
│   └── Home.jsx          # 新增一個 fetch 區塊（GET 已到期/即將到期
│                          # 清單），獨立 loading/error，不影響既有
│                          # 兩個區塊（dashboard／holdings）
```

**Structure Decision**：沿用既有三層架構逐層新增，不引入新的專案結構
選項（不是獨立 library/CLI/mobile app）。這是延伸現有 web service 的
單一新功能切片，跟 `app/routers/assets.py` 上線先例規模與做法相同。

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

無——Constitution Check 無違反項目（尚無正式 constitution 可供比對），
本節不適用。
