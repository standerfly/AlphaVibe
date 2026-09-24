# Phase 0 Research: 四段票天數區間化

**Feature**: 007-trip-day-range
**Date**: 2026-09-24

005 已解決「怎麼查價」，006 已解決「什麼時候自動重掃、跌破目標價要不要
通知」。本階段只解決「天數從單一值改成區間，該怎麼安全地落在既有
schema 與展開邏輯上，且不破壞正式庫既有資料」。

---

## §1 天數區間怎麼在 `expand_track()` 展開

**Decision**：`expand_track()` 對區間內每個天數值各呼叫一次既有的
`fs.sample_dates(trip_days=<某個值>, ...)`，把各次回傳的
`(outbound_date, return_date)` 配對累加起來，再照既有邏輯逐一解析
lead／trail 與建立行程。`sample_dates()`／`build_itineraries_fixed_trip()`
**本身不需要修改**。

**Rationale**：讀過 `sample_dates()` 的實作（`flight_search.py`）確認
出發日的抽樣（挑每月第幾天）完全不依賴 `trip_days`——`trip_days` 只用來
算回程日（`return_date = outbound + trip_days`）。這代表對區間內每個
天數值分別呼叫一次，得到的出發日集合是一致的、只有回程日不同，語意
正確（PO 要的正是「同一批出發日，各自比較不同天數」），而且完全不用
碰底層查價／抽樣邏輯，风险最低。

**Alternatives considered**：
- 修改 `sample_dates()` 本身接受 `trip_days` 為區間並在內部展開：
  **被否決**。`sample_dates()` 已有 178 個測試覆蓋、被 CLI 工具與
  既有邏輯多處呼叫，改動簽章影響面過大；外層迴圈可以達到相同效果且
  完全不動這支函式。
- 只抽樣一次出發日、內部對每個出發日展開全部天數：效果等價於外層
  迴圈寫法，但要求 `sample_dates()` 回傳格式改變（回傳出發日清單而非
  配對），一樣是不必要的介面異動。

---

## §2 Schema 遷移：新增區間欄位，不刪除舊欄位

**Decision**：`ALTER TABLE flight_track ADD COLUMN trip_days_min INTEGER`
與 `... ADD COLUMN trip_days_max INTEGER`（比照既有 `_migrate()` 的
逐欄 ALTER＋容忍已存在的寫法）。**保留舊的 `trip_days INTEGER NOT NULL`
欄位在 schema 裡，但應用程式碼完全停止讀取它**；為了滿足既有的
`NOT NULL` 約束，新建列時鏡射寫入 `trip_days = trip_days_max`（純粹
避免違反約束，不是第二個真實來源，讀取路徑永遠只看新欄位）。

**Rationale**：這個 repo 的既有 migration 慣例（`flight_store.py`
`_migrate()`、`flight_tracking_job.py` 相關 006 遷移）**只用
`ADD COLUMN`，從未 `DROP COLUMN` 或改型別**。SQLite 的 `DROP COLUMN`
雖然新版本支援，但會牽涉表格重建，風險與既有慣例不符；沿用純 ADD 的
安全路徑更符合這個專案一貫的謹慎程度。

**Alternatives considered**：
- 直接把 `trip_days` 欄位重新定義成下限、另加一個 `trip_days_max`：
  **被否決**。同一個舊欄位名稱換了語意（原本代表精確天數，改成代表
  下限）會讓任何還沒更新的程式碼靜默讀到錯誤語意而不自知，比留著一個
  不再被讀取、名稱清楚過時的欄位更危險。
- 完全捨棄 `trip_days`、用 `ALTER TABLE ... DROP COLUMN`：**被否決**，
  理由同上——偏離既有慣例，且 `NOT NULL` 約束移除同樣需要表格重建。

**已知限制**：`trip_days` 欄位遷移後會變成 schema 裡的「死欄位」
（有值但無人讀取）。這是刻意的取捨，不是遺漏；若未來要徹底清理，需要
另外規劃一次表格重建，不在本次範圍內。

---

## §3 id=9 遷移機制：一次性腳本，不掛進任何自動流程

**Decision**：新增 `poc/kb-mcp/migrate_trip_days_range.py`，一次性、
需要人手動執行的腳本，直接對指定的 `--data-dir` 執行
`UPDATE flight_track SET trip_days_min=10, trip_days_max=14 WHERE id=9`
（透過 `FlightStore` 的方法而非裸 SQL，沿用既有驗證規則）。執行後印出
遷移前後的完整欄位供人工核對。

**Rationale**：比照既有 `seed_assets_once.py` 的先例（2026-08-22 事故
後建立的模式：有副作用的一次性動作獨立成腳本、不掛進 `__init__` 或任何
自動觸發路徑）。id=9 是正式庫**唯一**一筆需要遷移的記錄，用一次性腳本
比在應用程式碼裡寫「啟動時自動遷移」安全得多——後者一旦邏輯有誤會在
每次服務啟動時重複執行，難以控制影響範圍。

**Alternatives considered**：
- 在 `_migrate()`（連線建立時自動執行的 schema 遷移）裡順便把 id=9 的
  資料也改掉：**被否決**。`_migrate()` 的職責是「補齊 schema」，不該
  夾帶「改變特定使用者資料」這種一次性、有產品決策成分的動作（10～14
  這個數字是 PO 決定，不是技術上唯一合理的值）；混在一起會讓 schema
  遷移邏輯難以在其他環境／測試資料庫上安全重複執行。
- 透過既有 API（`PATCH /api/flights/tracks/{id}`）手動呼叫：**被否決
  作為遷移機制本身**——本次異動決定天數區間不開放 PATCH（FR-007），
  且 PATCH 端點在遷移當下可能还没部署新版本。獨立腳本直接操作
  `FlightStore` 更可控。

---

## §4 組合數上限守衛：獨立可重用函式，不綁死在單一條件型態

**Decision**：在 `flight_scan_service.py` 新增一個不依賴 `Track` 物件
形狀的純函式，接受抽象的計數參數（月份數、`samples_per_month`、目標
數量〔四段票的外站數，未來單純來回的候選目的地數〕、天數選項數），
回傳算出的組合數；呼叫端（`app/routers/flights.py` 的建立驗證）用這個
回傳值跟上限（60）比較，超過就拒絕。

**Rationale**：`docs/spec-intake/flight-roundtrip-search/scope-decision.md`
已定案 `roundtrip-search` 包要重用同一套上限守衛。若把守衛邏輯寫死在
只認得四段票 `Track` 形狀的函式裡，`roundtrip-search` 包實作時勢必要
複製一份幾乎相同的計算邏輯（只是把「外站數」換成「候選目的地數」），
兩處算法之後很容易分岔。用抽象計數參數的純函式，兩個包都呼叫同一支，
不需要共用資料模型也能共用計算規則。

**Alternatives considered**：
- 直接在 `expand_track()` 算完組合清單後才檢查長度：**被否決**。這樣
  等於先花時間做完整枚舉（雖然不查價，但仍有計算成本）才拒絕，而且
  `expand_track()` 目前的職責是「展開成清單」，不該同時負責「決定要不
  要拒絕」這個 API 層級的決策；驗證應該在建立條件的請求處理路徑就
  完成，愈早失敗愈好。

---

## §5 既有 lead／trail（第1段提前／第4段延後）邏輯確認不受影響

**Decision**：不修改 `_resolve_offsets()`、`pick_lead()`、`pick_trail()`。

**Rationale**：讀過現有實作確認這些函式的輸入是 `outbound_date`／
`return_date`（已經是具體日期字串），不是 `trip_days`——天數區間只改變
「用哪些天數值算出多組 `(outbound_date, return_date)`」，不改變這些
配對確定之後怎麼決定第1段／第4段的日期。天數區間化後，lead／trail 邏輯
會被呼叫更多次（每個天數選項各一次），但每次呼叫的輸入輸出關係與現在
完全相同，不需要改動。
