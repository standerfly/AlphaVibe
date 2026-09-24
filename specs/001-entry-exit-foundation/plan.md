# Implementation Plan: 進出場分析基礎層（損益追蹤與價位定位）

**Branch**: `001-entry-exit-foundation` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-entry-exit-foundation/spec.md`

## Summary

新增兩個唯讀 MCP 工具，讓對話助理能直接取得結構化的持股損益與價位定位，
取代目前人工交叉比對多個既有查詢的做法（2026-09-01 曾因此出錯）。

技術路線：在 `poc/kb-mcp/` 新增兩個獨立計算模組（FIFO 損益、歷史百分位），
只讀既有三張表、查詢時即算不落盤、不新增資料表，並沿用既有的降級模式與
測試慣例。既有的浮動損益顯示完全不動（階段B 才整合）。

## Technical Context

**Language/Version**: Python 3.9（本機唯一版本，`Path.write_text(newline=)`
等 3.10+ 語法不可用——見 CLAUDE.md 2026-07-07 教訓）
**Primary Dependencies**: 無（`poc/kb-mcp/` 零外部依賴原則；統計函式沿用
`review_engine` 自寫的 `_percentile`／`_median`，不引入 `statistics` 以外
的東西）
**Storage**: SQLite（`poc/data/alphavibe.db`）——本階段**唯讀**，不新增
資料表、不新增欄位
**Testing**: `unittest`（非 pytest），`python3 -m unittest discover -s poc/kb-mcp/tests`；
測試一律用 `tempfile.mkdtemp()` 建獨立庫（範本 `tests/test_holdings_sync.py:24-30`），
**絕不碰正式庫**
**Target Platform**: 本機 macOS，透過 MCP stdio server（`server.py`）與唯讀
wrapper（`server_readonly.py`）供 Claude／Cline 呼叫
**Project Type**: 單一專案，商業邏輯集中在 `poc/kb-mcp/`
**Performance Goals**: 全量計算（60 檔 / 537 筆交易）單次查詢應在
1 秒內完成——規模極小，不需要快取或索引最佳化
**Constraints**: 不即時查外部 API（FR-010）；不修改既有商業邏輯；
文件與介面繁體中文
**Scale/Scope**: 60 檔標的、537 筆交易、3726 筆股價歷史——全部可一次
載入記憶體處理

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**本專案的 `.specify/memory/constitution.md` 尚未填寫**（仍是全欄位
placeholder 的樣板，如 `[PRINCIPLE_1_NAME]`）。因此沒有可檢查的正式
constitution 條款。

依實際治理來源（專案 `CLAUDE.md` 與 `~/.claude/rules/`）檢查等效關卡：

| 關卡 | 狀態 | 依據 |
|---|---|---|
| Python 3.9 相容 | ✅ 設計未使用 3.10+ 語法 | CLAUDE.md 2026-07-07 教訓 |
| `poc/kb-mcp/` 零外部依賴 | ✅ 不新增任何套件 | CLAUDE.md 硬約束 |
| 不重寫既有商業邏輯 | ✅ 新增獨立模組；既有 `get_trade_ledger`／損益顯示皆不動 | CLAUDE.md「STND 分頁與程式碼位置」節 |
| 不碰正式資料庫 | ✅ 本階段全唯讀；測試用暫存庫 | CLAUDE.md 2026-08-22 教訓（正式庫曾被污染兩次） |
| 驗證不自驗 | ⏳ 實作完成後需派 fresh agent 驗收 | `~/.claude/rules/10-model-dispatch.md` 第 6 節 |
| 繁體中文介面與文件 | ✅ | CLAUDE.md |

**建議（非本階段阻塞）**：constitution.md 從未填寫，導致 speckit 的
Constitution Check 形同空轉。可另案處理（`/speckit-constitution`），
不在本功能範圍內。

## Project Structure

### Documentation (this feature)

```text
specs/001-entry-exit-foundation/
├── plan.md              # 本檔
├── spec.md              # 需求（14 條 FR，已驗收）
├── research.md          # Phase 0：9 項查證與取捨（含股數單位的關鍵修正）
├── data-model.md        # Phase 1：資料結構與狀態轉換（GAP-R02／R03）
├── quickstart.md        # Phase 1：怎麼跑、怎麼驗
├── contracts/
│   └── mcp-tools.md     # Phase 1：兩個新工具的介面契約（GAP-R01）
└── checklists/
    └── requirements.md  # spec 品質檢核（16/16 通過）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── pnl.py                    # 新增：FIFO 損益計算（純函式，不碰 I/O）
├── price_position.py         # 新增：歷史收盤價百分位（複用 review_engine._percentile）
├── kb_store.py               # 修改：新增 get_all_trade_entries()（不動既有方法）
├── screener.py               # 修改：PRICE_WINDOW_DAYS 120 → 400（FR-014）
├── server.py                 # 修改：TOOLS 定義 ＋ dispatch 分支（各 +2）
├── server_readonly.py        # 修改：READONLY_TOOLS 白名單 +2，順手校正過時的工具數字
└── tests/
    ├── test_pnl.py           # 新增：FIFO 各情境（含賣超、重複列、無現價）
    ├── test_price_position.py# 新增：三段式門檻與 no_data
    ├── test_traceability.py  # 修改：登記 FR-001~FR-014
    └── test_kb.py            # 修改：get_all_trade_entries() 的存取測試
```

**不動的檔案**（明文列出以免誤改）：`report.py`、`app/routers/stock_detail.py`、
`holdings_sync.py`、`review_engine.py` 的既有函式（只 import 其 `_percentile`）。

## 實作順序

1. **`kb_store.get_all_trade_entries()`** ＋ 測試——最底層，其他都依賴它
2. **`pnl.py` FIFO 引擎** ＋ 測試——純函式（輸入交易列＋現價 → 結果），
   不碰 DB，最容易測；先把 `history_incomplete`／`no_price`／重複列警示
   三種情境的測試寫出來再實作
3. **`price_position.py`** ＋ 測試——同樣是純函式（輸入收盤價序列＋現價）
4. **MCP 工具註冊三處** ＋ 守門測試（白名單漏加目前不會被抓到，要補）
5. **`PRICE_WINDOW_DAYS` 加長（FR-014）**——單獨一步，需實測單一標的
   確認外部 API 回應正常（見下方觀測性節）
6. **`test_traceability.py` 登記**——本 repo 的需求↔實作↔測試守門測試

## 觀測性與失敗降級（GAP-R04）

**本階段沒有新增排程或非同步流程**，觀測性需求集中在兩處：

1. **查詢層**：所有失敗一律以 `status` 欄位表達，不拋例外中斷整批查詢
   （FR-011）。四種 `status` 的判定順序見 `data-model.md`。原則沿用
   `benchmark.py` 的優雅降級與「算不出來就明講、不要畫 0% 空條」
   （roadmap.md:87-89、264-266）。

2. **FR-014 加長抓取窗口的風險**：`PRICE_WINDOW_DAYS` 120 → 400 只加長
   單次抓取的日期範圍，**不增加呼叫次數**，但單次回應的資料量會變大。
   實作時 MUST 以單一標的實測確認外部來源回應正常（不可假設），並記錄
   實測結果。若發現問題，降為 250 天並在 research.md 補記原因。
   相關教訓：2026-07-28 曾因密集測試把 FinMind 匿名額度打光、連累當晚
   02:00 正式排程（CLAUDE.md 教訓紀錄）——**實測要有節制，一檔即可**。

## Complexity Tracking

| 項目 | 為何需要 | 較簡單的替代方案為何不夠 |
|---|---|---|
| 新增 `get_all_trade_entries()` 而非重用 `get_trade_ledger` 迴圈 | 避免 60 次查詢的 N+1 | 迴圈可行但每次全量查詢都要開 60 次 cursor；單一查詢＋Python 分組更直接，且不動既有方法 |
| 兩個獨立模組而非塞進 `review_engine.py` | `review_engine` 已是模組D 的檢視引擎，職責不同且檔案已大 | 塞進去會讓「模組D 檢視」與「進出場分析」兩件事混在同一檔，階段B 要再拆更痛 |

**無其他複雜度豁免**——本階段刻意不做快取表、不做索引最佳化、不做
非同步，全部是查詢時即算的純函式。
