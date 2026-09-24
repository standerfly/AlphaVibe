# Implementation Plan: 相簿分頁（Photo Albums & Search）

**Branch**: `004-photos-albums-search` | **Date**: 2026-09-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-photos-albums-search/spec.md`

## Summary

STND 新增相簿分頁：本機照片匯入（去重、背景處理）、相簿/標籤/評分整理、
跨相簿全域搜尋（camera_model／lens／標籤組合查詢），以及把標籤與評分
單向鏡射寫回照片檔案本身的 XMP/IPTC 中繼資料（新增系統層依賴
`exiftool`），使這些資訊在 STND 之外的工具中依然可見。技術路線：獨立
`PhotoStore` 類別＋獨立 SQLite 檔 `photos.db`（比照 `us_stock_store.py`
「完全獨立、`__init__` 不掛副作用種子寫入」慣例），資料庫永遠是搜尋與
真相來源，檔案中繼資料只是單向、可延遲的鏡射；匯入與中繼資料寫回都是
背景任務，不阻塞 HTTP request。

## Technical Context

**Language/Version**: Python 3.9.6（後端 `app/`／`poc/kb-mcp/`；**不可**
使用 3.10+ 語法——`match`/`case`、`X | Y` 型別聯集）；JavaScript
（React 18，`web/`，既有 Vite 前端）
**Primary Dependencies**: FastAPI 0.128.8、uvicorn 0.39.0（既有，
`app/requirements.txt`，本功能不新增 Python 套件）；**新增系統層外部
工具 `exiftool`**（非 Python 套件，經 Homebrew 安裝，供 JPG 的
XMP/IPTC 中繼資料讀寫）；縮圖產生與基礎 EXIF 讀取沿用 macOS 內建
`sips` 命令列工具（零新增 Python 套件，理由見 research.md §1）
**Storage**: 新增獨立 SQLite 檔 `poc/data/photos.db`，透過新的
`PhotoStore` 類別存取，與既有 `KBStore`／`alphavibe.db`、
`USStockStore`／`us_stocks.db` 完全獨立、互不 import
**Testing**: Python `unittest`（標準庫），比照 `app/tests/test_smoke.py`
既有驗證方式；不引入 pytest 等第三方測試框架
**Target Platform**: macOS（Mac mini 本機常駐服務，`uvicorn
app.main:app`，可能經 ngrok 對外提供遠端存取）
**Project Type**: web-service（FastAPI 後端＋React 前端，同源部署，
`app/` 直接 import `poc/kb-mcp/` 既有函式的既有慣例）
**Performance Goals**: 匯入 100+ 張照片的處理不得阻塞其他 HTTP
request（背景執行）；全域搜尋在本機 SQLite 上執行，個人相片庫規模
（數千至數萬張）下應為次秒級回應
**Constraints**: 單人使用、無多用戶權限；Python 3.9.6 語法限制；
`exiftool` 是本次新增的系統層依賴，需在部署文件記錄安裝步驟
（`brew install exiftool`）；不引入訊息佇列或獨立 worker 服務等額外
基礎設施——背景任務規模（單人、偶發批次匯入）不需要
**Scale/Scope**: 個人相片庫規模（估計數千至數萬張 JPG），非多租戶
商業規模

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 目前是未填寫的樣板（本專案從未實際
執行過 `speckit-constitution`），沒有具體可查核的原則條文可供比對。
改以本 repo 實際查證過、已有先例的架構慣例作為對應品質門檻（來源：
AlphaVibe `CLAUDE.md`、`poc/kb-mcp/us_stock_store.py` 檔頭慣例說明）：

| Gate | 檢查內容 | 結果 |
|---|---|---|
| G1 獨立資料層 | 新功能使用獨立 Store 類別＋獨立 db 檔案，不與既有 `KBStore`/`alphavibe.db` 混用 | PASS（見 Technical Context「Storage」） |
| G2 建構子無副作用寫入 | `PhotoStore.__init__` 只建 schema，不做任何種子/預設資料寫入 | PASS（設計要求；2026-08-22 資產表事故教訓，見 CLAUDE.md 教訓紀錄） |
| G3 Python 版本相容 | 避免 3.10+ 語法 | PASS |
| G4 背景任務不阻塞請求 | 匯入與中繼資料寫回皆為背景執行＋輪詢狀態，不同步阻塞 | PASS（見 research.md §2） |
| G5 資料庫為唯一真相來源 | 搜尋/瀏覽只讀資料庫，從不反過來讀檔案中繼資料 | PASS（spec.md FR-010、FR-012~014 直接要求） |

無違規，Complexity Tracking 表無需填寫。

**Phase 1 設計後重新檢查**：`data-model.md`（獨立 5 張表，無外鍵、
`__init__` 只建 schema）與 `contracts/photos-api.md`（搜尋端點只讀
資料庫、匯入與同步走背景任務＋輪詢）皆未引入任何違反上述 Gate 的
設計，G1~G5 維持 PASS。

## Project Structure

### Documentation (this feature)

```text
specs/004-photos-albums-search/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/
│   └── photos-api.md    # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── photo_store.py            # 新增：PhotoStore 類別，獨立 photos.db（比照 us_stock_store.py）
├── photo_importer.py         # 新增：匯入流程（掃描來源資料夾／MD5去重預覽／複製／sips縮圖／sips讀EXIF）
└── photo_metadata_sync.py    # 新增：呼叫 exiftool 讀寫 XMP/IPTC（keywords／rating）

app/
├── routers/
│   └── photos.py             # 新增：/api/photos/* 端點，只轉呼叫 poc/kb-mcp/ 上述模組，不重寫邏輯
├── main.py                   # 修改：註冊 photos router
└── tests/
    └── test_photos_smoke.py  # 新增：比照既有 test_smoke.py 慣例（含匯入去重、搜尋、同步狀態的端到端檢查）

web/src/
├── pages/
│   └── Photos.jsx            # 修改：從 MVP 空白佔位頁換成完整功能頁（相簿列表/詳情/搜尋/照片詳情）
├── components/
│   └── photos/               # 新增：相簿卡片、縮圖牆、匯入 wizard、搜尋篩選列等元件
└── api/
    └── client.js              # 修改：新增 photos 相關 API 呼叫函式
```

**Structure Decision**: 沿用 STND 既有「`app/` 前後端分離、底層資料層/
商業邏輯放 `poc/kb-mcp/`」架構慣例（Q-046 定案）。本功能的資料層與
背景任務邏輯放在 `poc/kb-mcp/` 新檔案，`app/routers/photos.py` 只負責
HTTP 介面轉呼叫，不重寫底層邏輯——完全比照 `us_stocks.py`／
`us_stock_store.py` 的既有分工模式。前端沿用 `web/src/pages/` +
`web/src/components/` 既有慣例，套用 `web/src/styles/tokens.css` 既有
色彩/元件樣式，不另開一套視覺系統（見 2026-09-16 流程圖/Demo artifact
已驗證過的畫面設計）。

## Complexity Tracking

*Constitution Check 無違規，本表無需填寫。*
