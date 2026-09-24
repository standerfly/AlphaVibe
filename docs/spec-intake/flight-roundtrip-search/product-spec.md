# Product Spec: 機票查詢：四段票天數區間化＋單純來回搜尋

**Status:** In Review
**Feature Slug:** flight-roundtrip-search
**Function Branch:** function/flight-roundtrip-search
**Product Owner:** Stander
**TPM:** Claude
**Accepted At:** N/A
**Acceptance Evidence:** N/A

## Problem And Goal

既有的 `flight-search`／`flight-price-tracking` 功能（已上線）只能查
「外站四段票」這種特定玩法，且行程天數是單一固定整數，無法在一個條件
內比較不同天數的價格。PO 想查一趟單純的來回行程（例如「去青森看雪」）
時，發現現有系統完全無法表示——目的地欄位（`outstations`）強制要求
外站、且沒有單純來回這種結構。

在討論可行性時，PO 進一步發現既有四段票功能「天數是固定的」這件事本
身就不合理，因為即使是外站四段票，也可能想比較 10 天跟 14 天何者更
划算。

目標：(1) 把既有四段票的行程天數從固定整數升級為區間，讓 PO 在單一
條件內比較不同天數的價格；(2) 新增「單純來回」查詢類型，支援多個候選
目的地一起比價、天數區間、可選轉機城市偏好，整合進同一個「機票」分頁。

來源：docs/spec-intake/flight-roundtrip-search/raw/S01-po-conversation-2026-09-24.md

## Business Context And Priority

- Priority：PO 明確表示「討論完就開發」，緊接在 `flight-search`
  （005/006）完成上線之後提出，屬於同一個機票查詢功能線的直接延伸
- Timing：無外部時程壓力（個人工具），但 PO 意圖是本次 session 內
  討論定案後立即進入 Spec Kit 與實作
- Business value：擴大機票比價工具的適用範圍，從單一特殊玩法（外站
  四段票）擴展到一般旅遊情境（單純來回），同時修正既有功能「天數
  綁死」這個 PO 認為不合理的限制

## Actors

- **PO（Stander，唯一使用者）**：個人使用，透過網頁「機票」分頁建立
  追蹤條件、查看比價結果、透過 Telegram 接收降價／現況通知

## MVP Scope

### In Scope

- 既有四段票追蹤條件的行程天數改為區間（下限～上限），系統在區間內
  抽樣不同天數＋日期組合查價（FR-01、FR-02）
- 既有追蹤條件 id=9（布拉格・成田出發）遷移到區間語意（10～14 天）
  並重新查價（FR-03）
- 新增「單純來回」查詢類型：可設定多個候選目的地機場，系統比價找出
  全部候選中最便宜的組合（FR-04、FR-05）
- 「單純來回」天數採區間語意，與四段票一致（FR-06）
- 「單純來回」可選擇性指定偏好轉機城市；未指定時交由 Google Flights
  自動決定（FR-07）
- 「單純來回」與「四段票」整合在同一個「機票」分頁，以類型切換呈現
  （FR-08）
- 「單純來回」沿用既有的目標價達標通知與現況通知機制（FR-09）
- 多目的地候選情境下，通知內容明確標示觸發的候選目的地（FR-10）
- 建立條件時，查詢組合數超過上限（預設 60）就拒絕建立並提示縮小範圍
  （FR-11）

### Out Of Scope

- 四段票既有的目的地／外站／hub／第1段提前策略／第4段延後策略等
  概念本身不變動——本次只動「天數」這個維度
- 貨幣仍只支援 NTD（沿用既有決定）
- 「單純來回」不具備四段票的外站迴圈概念

### Deferred

- 天數區間欄位不開放後續 PATCH 編輯；需要調整時視為「建新條件」
  （FR-12）
- 組合數上限（60）暫定為寫死常數，不做成可設定值

## Functional Requirements

- FR-01：使用者可將四段票追蹤條件的行程天數設定為區間（下限～上限），
  而非單一固定天數（Q-005）
- FR-02：系統在天數區間內，對每個抽樣日期展開對應的天數選項各自查價
  比較（Q-005）
- FR-03：既有追蹤條件 id=9 遷移到區間語意，天數區間設為 10～14 天，
  並觸發重新查價（Q-006、Q-007）
- FR-04：使用者可建立「單純來回」類型的追蹤條件，指定多個候選目的地
  機場（Q-001）
- FR-05：系統對單純來回條件的所有候選目的地個別查價，並在結果中標示
  每筆結果對應的候選目的地（Q-001、Q-008）
- FR-06：單純來回條件的行程天數同樣採區間語意，與四段票一致（Q-002）
- FR-07：使用者可為單純來回條件選擇性指定偏好轉機城市；未指定時交由
  Google Flights 自動決定轉機組合（Q-003）
- FR-08：單純來回與四段票條件在同一個「機票」分頁呈現，透過類型切換
  區分，共用卡片、通知、排程機制（Q-004）
- FR-09：單純來回條件沿用既有的目標價達標通知（`should_notify`）與
  現況通知（`should_notify_status`）機制（assumption，PO 未表示要
  不同行為）
- FR-10：多目的地候選情境下，達標通知與現況通知的訊息內容需明確標示
  觸發的候選目的地（Q-008）
- FR-11：建立追蹤條件（四段票或單純來回）時，若展開後的查詢組合數
  超過上限（預設 60，assumption 見 Q-010），系統拒絕建立並提示縮小
  範圍（Q-009）
- FR-12：天數區間欄位不開放後續 PATCH 編輯；需要調整時比照既有慣例
  視為「建新條件」（沿用既有 `TrackUpdate` 設計原則的延伸推論）

## Acceptance Scenarios

1. PO 建立四段票條件，天數設為 10～14 天，出發區間 2027-04～05，
   觸發掃描後，結果顯示涵蓋 10/11/12/13/14 天等不同天數組合的比價
   結果
2. PO 查看 id=9，天數顯示為 10～14 天區間（非舊的固定 12 天），且已
   有重新查價後的結果
3. PO 建立單純來回條件，候選目的地填 AOJ／CTS／AXT／KIJ，天數區間
   3～7 天，出發區間 2027-01～02，觸發掃描後，結果顯示各候選目的地、
   各天數組合的比價，且能看出哪個候選目的地最便宜
4. PO 為單純來回條件指定偏好轉機城市（例如限定經 NRT），查詢結果的
   行程確實經過指定城市轉機
5. PO 未指定轉機城市，查詢結果由 Google Flights 自動安排轉機
6. 單純來回條件某次重掃後最低價跌破目標價，PO 收到的 Telegram 通知
   明確寫出是哪個候選目的地、多少錢
7. PO 嘗試建立一個候選目的地過多、天數區間過寬的單純來回條件（組合
   數超過 60），系統拒絕建立並說明組合數超標，建議縮小範圍
8. 同一個「機票」分頁上，PO 可透過類型切換在「四段票」與「單純來回」
   之間切換檢視，卡片外觀、通知標示、排程時間欄位呈現方式一致

## Success Criteria

- PO 可在單一追蹤條件內比較至少 3 種以上天數組合的價格（驗證區間
  查詢確實生效，非只查單一天數）
- PO 可在單一追蹤條件內比較至少 2 個候選目的地的價格（驗證多目的地
  候選確實生效）
- id=9 遷移後，天數區間顯示與底層資料庫欄位一致（fresh 驗證：直接
  讀資料庫確認區間欄位，非只看前端顯示）
- 組合數上限守衛在正式環境用超標的條件實測會被拒絕（非僅單元測試
  層級的驗證）

## Constraints And Assumptions

- 沿用既有 `flight-search` 的技術限制：查詢走瀏覽器路徑，速率上限
  約 20 筆／小時（推估值，未長期驗證）；貨幣僅 NTD；查詢間需延遲以
  避免軟性封鎖
- **Assumption**：組合數上限暫定 60／條件，未經 PO 逐字確認精確數字，
  可隨時調整（Q-010）
- **Assumption**：id=9 遷移目標區間為 10～14 天，是 Claude 提案並經
  PO 採納的預設值，非 PO 主動指定的精確需求（Q-007）
- **Assumption**：通知機制（`should_notify`／`should_notify_status`）、
  過期防護（`derive_state`）在天數區間化與多目的地情境下沿用既有
  判定邏輯，不需改變行為，僅輸入資料形狀改變——此為技術假設，需在
  Spec Kit 階段逐一驗證是否成立，不能只憑本文件推論
- 這是對**已上線生產功能與資料**的異動，需要跟過去處理正式服務異動
  時同等級的謹慎（migration、回歸測試、smoke test、正式環境驗證），
  不是全新獨立功能的一般開發流程

## Dependencies

- 依賴既有 `flight-search`（specs/005-flight-scan-page）與
  `flight-price-tracking`（specs/006-flight-price-tracking）已上線
  的排程、通知、過期防護基礎設施
- 依賴既有 Google Flights 瀏覽器查價整合
  （`poc/kb-mcp/flight_search.py`／`scraper/`）
- 正式庫現有資料：id=9 追蹤條件（唯一一筆既有記錄，需遷移）

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 建立條件時組合數超過上限 | 拒絕建立，不寫入資料庫 | 前端顯示錯誤訊息並說明算出的組合數與上限 | 使用者縮小候選目的地數量或天數區間後重新提交 | Yes |
| id=9 遷移後首次重新查價部分失敗（被封鎖／逾時） | 沿用既有「部分完成不更新 last_success_at」原則，保留已查到的部分結果 | 卡片顯示部分完成狀態，比照既有四段票的阻擋提示文案 | 下次排程或手動觸發時接續查詢未完成的組合 | No（沿用既有機制，非本次新增行為） |
| 單純來回多目的地候選中，部分候選目的地查詢失敗 | 其餘候選目的地的結果仍正常呈現，不因單一候選失敗而整條件失敗 | 結果列表中失敗的候選目的地標示為查詢失敗，其餘正常顯示價格 | 下次排程或手動觸發時重試失敗的候選目的地 | No |
| 轉機城市偏好設定後查無符合條件的班機 | 查無票價（no_fare 狀態），不視為查詢失敗 | 比照既有「查無票價與查詢失敗必須分開」原則，顯示查無票價而非錯誤 | 使用者調整轉機城市偏好或放寬條件 | No |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Complete | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| Data Model & Migration Note | Yes | Complete | supporting-artifacts/data-model-migration.md | 破壞性 schema 變更＋既有生產資料（id=9）遷移，風險需明確記錄 |
| API Contract Changes | Yes | Complete | supporting-artifacts/api-contract-changes.md | 修改既有已上線 API 端點的欄位形狀，屬破壞性變更 |

## Source Decisions

- 全部功能需求可追溯至
  `docs/spec-intake/flight-roundtrip-search/clarification-log.md`
  的 Q-001～Q-010（皆為 Answered，無 Open／Blocking 項目）
- 原始對話記錄：
  `docs/spec-intake/flight-roundtrip-search/raw/S01-po-conversation-2026-09-24.md`
- 範圍決策與拆包順序：
  `docs/spec-intake/flight-roundtrip-search/scope-decision.md`
