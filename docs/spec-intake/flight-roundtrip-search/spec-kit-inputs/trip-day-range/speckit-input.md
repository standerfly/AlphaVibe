# Spec Kit Input: 四段票天數區間化

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** trip-day-range
**Handoff Order:** 1

## Feature Summary

把既有已上線的外站四段票追蹤條件（`flight-search`／
`flight-price-tracking`，specs/005、006）的行程天數，從單一固定整數
（`trip_days`）升級為區間（下限～上限），系統在區間內抽樣不同天數＋
日期組合查價比較。同時遷移正式庫既有唯一一筆追蹤條件（id=9，布拉格・
成田出發）到新的區間語意（10～14 天）並重新查價。這是後續「單純來回」
功能（`roundtrip-search`）的前提依賴。

## Actors

- PO（Stander，唯一使用者）

## Problem And Goal

既有四段票功能的行程天數是單一固定值，無法在同一條件內比較不同天數
的價格。PO 認為這個限制不合理（即使外站四段票，也可能想比較 10 天跟
14 天何者更划算），要求回頭升級既有已上線功能。

## In Scope

- `flight_track` 資料表的天數欄位從單一整數改為區間（下限／上限）
- `expand_track()` 枚舉邏輯支援在區間內展開多個天數選項，組合數公式
  變為：月份數 × `samples_per_month` × 外站數 × 天數選項數
- 既有前端表單（`FlightTrackForm.jsx`）改為輸入區間而非單一天數
- 既有卡片／結果顯示（`Flights.jsx`）反映區間天數
- id=9 遷移：天數區間設為 10～14 天，觸發重新查價，其餘欄位（目標價
  40000、`scan_frequency_days=7`、通知歷史）維持不變
- 建立條件時的組合數上限守衛（預設 60，超過則拒絕建立並提示縮小
  範圍）——本包先在四段票類型落地，`roundtrip-search` 包會重用同一套
  守衛邏輯
- 既有 smoke test（`app/tests/test_smoke.py`）中依賴 `trip_days` 單一
  整數與組合數的斷言，需同步更新

## Out Of Scope

- 四段票的目的地／外站／hub／第1段提前策略／第4段延後策略等概念
  本身不變動
- 天數區間欄位不開放 PATCH 編輯（沿用既有「改變枚舉結果的欄位視為
  建新條件」原則）
- 單純來回類型本身（屬於 `roundtrip-search` 包）

## User Scenarios

1. PO 建立四段票條件，天數設為 10～14 天，出發區間 2027-04～05，
   觸發掃描後，結果顯示涵蓋 10/11/12/13/14 天等不同天數組合的比價
   結果
2. PO 查看 id=9，天數顯示為 10～14 天區間（非舊的固定 12 天），且已
   有重新查價後的結果，目標價與通知歷史維持不變
3. PO 嘗試建立一個天數區間過寬、外站過多的四段票條件（組合數超過
   60），系統拒絕建立並說明組合數超標，建議縮小範圍

## Functional Requirements

- FR-01：使用者可將四段票追蹤條件的行程天數設定為區間（下限～上限），
  而非單一固定天數
- FR-02：系統在天數區間內，對每個抽樣日期展開對應的天數選項各自查價
  比較
- FR-03：既有追蹤條件 id=9 遷移到區間語意，天數區間設為 10～14 天，
  並觸發重新查價，非天數相關欄位（目標價、通知歷史、重掃頻率）維持
  不變
- FR-11：建立四段票追蹤條件時，若展開後的查詢組合數超過上限（預設
  60），系統拒絕建立並提示縮小範圍
- FR-12：天數區間欄位不開放後續 PATCH 編輯；需要調整時視為「建新
  條件」

## Success Criteria

- PO 可在單一四段票追蹤條件內比較至少 3 種以上天數組合的價格
- id=9 遷移後，天數區間顯示與底層資料庫欄位一致（fresh 驗證：直接
  讀資料庫確認，非只看前端顯示）
- 組合數上限守衛在正式環境用超標的條件實測會被拒絕

## Constraints And Assumptions

- 這是對已上線生產功能與資料的異動——需要 schema migration、回歸
  測試、smoke test、正式環境驗證，等級比照過去處理正式服務異動的
  謹慎程度
- Assumption：組合數上限暫定 60／條件，未經 PO 逐字確認精確數字，
  可隨時調整
- Assumption：id=9 遷移目標區間為 10～14 天，是 Claude 提案並經 PO
  採納的預設值
- Assumption：排程（`flight_tracking_job.py`）、通知判定
  （`should_notify`／`should_notify_status`）、過期防護
  （`derive_state`）在天數區間化後沿用既有判定邏輯不需改變行為——
  需在本包的技術規劃階段逐一驗證是否成立
- 正式庫現有資料：id=9 是唯一一筆既有記錄，遷移影響範圍明確可控

## Source Decisions

- clarification-log.md Q-005、Q-006、Q-007、Q-009、Q-010
- scope-decision.md「Split Feature Decisions」／「Decision Rationale」
- supporting-artifacts/data-model-migration.md
- supporting-artifacts/api-contract-changes.md
