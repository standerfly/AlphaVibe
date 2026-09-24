# Data Model & Migration Note: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
**Last Updated:** 2026-09-24
**Status:** Draft（product 層級意圖說明，非技術實作規格——精確 schema／
migration 步驟留給 Spec Kit `plan.md`／`data-model.md` 階段設計）

## 為什麼需要這份文件

本次異動包含一次**對已上線生產資料的破壞性 schema 變更**
（`flight_track.trip_days` 單一整數 → 區間），且正式庫已有一筆真實
追蹤條件（id=9）在使用中。這比一般新增欄位風險更高，需要明確記錄
遷移意圖，供 Spec Kit 階段設計具體 migration 腳本與回歸驗證步驟。

## 現況（變更前）

- `flight_track.trip_days INTEGER NOT NULL`——單一固定整數
- `expand_track()` 用這個單一值展開四段票組合：
  `月份數 × samples_per_month × 外站數`（天數不參與組合數乘法）
- 正式庫現況：僅 1 筆追蹤條件（id=9，布拉格・成田出發，
  `trip_days=12`，`target_price=40000`，`scan_frequency_days=7`，
  已有真實查價結果與通知歷史）

## 變更後（意圖，非最終 schema）

- 四段票／單純來回共用「天數區間」概念：`trip_days_min`／
  `trip_days_max`（欄位確切命名留給 Spec Kit `data-model.md`）
- 組合數公式變成：
  `月份數 × samples_per_month × 外站數（或候選目的地數） × 天數選項數`
  （天數選項數 = `trip_days_max − trip_days_min + 1`）
- 新增「單純來回」需要的欄位：候選目的地清單（複數，類似
  `outstations` 但語意不同——沒有外站迴圈）、可選的偏好轉機城市、
  行程類型標記（四段票／單純來回，供同一分頁的類型切換使用）
- 新增組合數上限守衛：建立條件時若算出的組合數超過門檻（暫定 60，
  見 clarification-log Q-010），拒絕建立並提示縮小範圍——四段票與
  單純來回都要套用同一道守衛

## 遷移範圍

- **id=9**：既有 1 筆記錄需要遷移到區間語意。PO 決定（clarification-log
  Q-006／Q-007）：改成 10～14 天區間並重新查價，不是保留舊值、也不是
  刪除重建。遷移後既有的目標價（40000）、通知歷史、`scan_frequency_days`
  等非天數相關欄位應維持不變。
- 目前正式庫只有這一筆記錄，遷移影響範圍明確、可控——不是要處理
  大量既有資料的批次遷移。
- 遷移後的重新查價會產生新的組合（10/11/12/13/14 天 × 既有日期抽樣），
  舊的 12 天專屬查價快取／結果如何處理（保留當歷史、還是清除重查）
  留給 Spec Kit 階段決定，非本文件範圍。

## 與既有機制的相容性

- 排程（`flight_tracking_job.py`）、通知判定（`should_notify`／
  `should_notify_status`）、過期防護（`derive_state`）預期不需要改
  判定邏輯本身，只需要能正確處理新的組合數計算方式——這些機制設計
  時就是基於「組合數」與「最低價」抽象運作，理論上不直接依賴
  `trip_days` 是單一值還是區間，但需要在 Spec Kit 階段逐一確認
  （不能只憑這裡的推論就假設沒問題）
- API 回應形狀變更見 `api-contract-changes.md`
