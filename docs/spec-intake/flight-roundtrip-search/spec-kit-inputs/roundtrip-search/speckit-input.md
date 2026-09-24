# Spec Kit Input: 單純來回搜尋

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** roundtrip-search
**Handoff Order:** 2

## Feature Summary

新增「單純來回」查詢類型，讓 PO 可以查一般的來回行程（不限於外站四段
票這種特定玩法），支援多個候選目的地一起比價、天數區間、可選偏好轉機
城市，整合進同一個「機票」分頁並以類型切換呈現。依賴 `trip-day-range`
包先完成的天數區間化資料概念與組合數上限守衛。

## Actors

- PO（Stander，唯一使用者）

## Problem And Goal

PO 想查一趟單純的來回行程（例如「去青森看雪」），但現有系統的
`outstations` 欄位強制要求外站，完全無法表示單純來回這種普通行程。
青森等地方沒有國際線、通常需經東京轉機，PO 也想要有能力指定偏好的
轉機城市。

## In Scope

- 新增追蹤條件的行程類型欄位：四段票／單純來回，兩者在同一個
  「機票」分頁透過類型切換呈現，共用卡片、通知、排程機制
- 單純來回條件可設定多個候選目的地機場（例如 AOJ／CTS／AXT／KIJ），
  系統對每個候選目的地個別查價比較，結果中標示每筆對應的候選目的地
- 單純來回天數採區間語意（依賴 `trip-day-range` 包建立的資料概念）
- 可選擇性指定偏好轉機城市；未指定時交由 Google Flights 自動決定
  （查詢邏輯依是否指定轉機城市，分岔為單純來回的簡單網址或
  multi-city 網址）
- 沿用既有目標價達標通知（`should_notify`）與現況通知
  （`should_notify_status`）機制
- 多目的地候選情境下，通知內容明確標示觸發的候選目的地
- 沿用 `trip-day-range` 包建立的組合數上限守衛（預設 60／條件）

## Out Of Scope

- 不具備四段票的外站迴圈概念（沒有『從外站出發回外站』這種結構）
- 貨幣仍只支援 NTD
- 天數區間欄位不開放 PATCH 編輯

## User Scenarios

1. PO 建立單純來回條件，候選目的地填 AOJ／CTS／AXT／KIJ，天數區間
   3～7 天，出發區間 2027-01～02，觸發掃描後，結果顯示各候選目的地、
   各天數組合的比價，且能看出哪個候選目的地最便宜
2. PO 為單純來回條件指定偏好轉機城市（例如限定經 NRT），查詢結果的
   行程確實經過指定城市轉機
3. PO 未指定轉機城市，查詢結果由 Google Flights 自動安排轉機
4. 單純來回條件某次重掃後最低價跌破目標價，PO 收到的 Telegram 通知
   明確寫出是哪個候選目的地、多少錢
5. PO 嘗試建立候選目的地過多、天數區間過寬的單純來回條件（組合數
   超過 60），系統拒絕建立並說明組合數超標，建議縮小範圍
6. 同一個「機票」分頁上，PO 可透過類型切換在「四段票」與「單純來回」
   之間切換檢視，卡片外觀、通知標示、排程時間欄位呈現方式一致

## Functional Requirements

- FR-04：使用者可建立「單純來回」類型的追蹤條件，指定多個候選目的地
  機場
- FR-05：系統對單純來回條件的所有候選目的地個別查價，並在結果中標示
  每筆結果對應的候選目的地
- FR-06：單純來回條件的行程天數同樣採區間語意，與四段票一致
- FR-07：使用者可為單純來回條件選擇性指定偏好轉機城市；未指定時交由
  Google Flights 自動決定轉機組合
- FR-08：單純來回與四段票條件在同一個「機票」分頁呈現，透過類型切換
  區分，共用卡片、通知、排程機制
- FR-09：單純來回條件沿用既有的目標價達標通知與現況通知機制
- FR-10：多目的地候選情境下，達標通知與現況通知的訊息內容需明確標示
  觸發的候選目的地
- FR-11：建立單純來回追蹤條件時，若展開後的查詢組合數超過上限（預設
  60），系統拒絕建立並提示縮小範圍

## Success Criteria

- PO 可在單一單純來回追蹤條件內比較至少 2 個候選目的地的價格
- 指定偏好轉機城市時，查詢結果確實反映該偏好
- 多目的地候選的通知內容經 PO 實際收到並確認能一眼看出是哪個候選
  目的地觸發

## Constraints And Assumptions

- 依賴 `trip-day-range` 包已完成的天數區間資料概念與組合數上限守衛，
  handoff order 排在其之後
- 有指定轉機偏好時，查詢需組成 multi-city（沿用既有
  `google_flights_url()` 的 multi-city 能力，非新建查詢機制）；未
  指定時走單純來回的簡單網址——兩條路徑的技術設計留給本包的 Spec
  Kit 技術規劃階段
- Assumption：組合數上限沿用 `trip-day-range` 包的守衛邏輯，不另外
  為單純來回設計獨立門檻
- Assumption：排程、通知判定、過期防護機制沿用既有邏輯，需在技術
  規劃階段驗證多目的地情境下是否需要調整（例如「最低價」判定要不要
  考慮候選目的地之間的比較邏輯）

## Source Decisions

- clarification-log.md Q-001、Q-002、Q-003、Q-004、Q-008、Q-009、
  Q-010
- scope-decision.md「Split Feature Decisions」／「Decision Rationale」
- supporting-artifacts/data-model-migration.md
- supporting-artifacts/api-contract-changes.md
