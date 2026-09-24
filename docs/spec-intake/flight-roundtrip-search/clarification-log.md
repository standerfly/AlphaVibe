# Clarification Log: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
**Last Updated:** 2026-09-24

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | 「單純來回」的目的地範圍怎麼設定：單一目的地，還是像外站一樣多目的地候選？ | SRC-001 Q1 | Scope | Answered | 多目的地候選（像外站的做法）——一個條件可填多個候選目的地，系統比價找最便宜的組合 | Stander | 2026-09-24 |
| Q-002 | 行程天數：固定天數（跟四段票一樣）還是彈性區間？ | SRC-001 Q2 | Scope | Answered | 彈性區間（例如 3～7 天），找最便宜的天數＋日期組合 | Stander | 2026-09-24 |
| Q-003 | 轉機／到達機場怎麼處理：交給 Google Flights 自動決定，還是可指定偏好轉機城市？ | SRC-001 Q3 | Workflow | Answered | 可指定偏好轉機城市（類似四段票的 hub 概念）；查詢邏輯因此需支援 multi-city 而非純來回 | Stander | 2026-09-24 |
| Q-004 | 「單純來回」在網頁上怎麼呈現：同一個機票分頁加類型切換，還是分開的獨立分頁？ | SRC-001 Q4 | Workflow | Answered | 同一個「機票」分頁，加「四段票／單純來回」類型切換，卡片、通知、排程機制共用同一套介面 | Stander | 2026-09-24 |
| Q-005 | 既有四段票的固定天數限制（`trip_days` 單一整數）要不要一併處理？ | SRC-001 補充討論 | Data | Answered | 要——四段票的 `trip_days` 也改成跟單純來回一樣的區間語意，回頭升級既有已上線功能，不是單純來回獨有的設計 | Stander | 2026-09-24 |
| Q-006 | 既有的 id=9 追蹤條件（布拉格・成田出發，目前 `trip_days=12`）怎麼處理？ | SRC-001 補充討論 | Data | Answered | 改成區間並重新設定，不維持現狀 | Stander | 2026-09-24 |
| Q-007 | id=9 遷移後具體要設多少天的區間？ | GAP-001 | Data | Answered | 10～14 天（Claude 提案：以原本 12 天為中心 ±2 天，PO 採納） | Stander | 2026-09-24 |
| Q-008 | 多目的地候選情境下，達標／現況通知要不要標明「這次是哪個候選目的地觸發的」？ | GAP-002 | Observability | Answered | 要標明——通知內容需明確寫出觸發的候選目的地，不能只給價格讓使用者自己猜 | Stander | 2026-09-24 |
| Q-009 | 多目的地 × 彈性天數會讓單一條件的查詢組合數大幅增加，要不要對單一條件設組合數上限？ | GAP-003 | Scope | Answered | 要設上限——建立條件時若組合數超過門檻就拒絕並提示縮小範圍，避免一個條件吃光整小時配額 | Stander | 2026-09-24 |
| Q-010 | Q-009 的具體上限數字是多少？ | Q-009 追加 | Scope | Non-blocking | Claude 提案：60 組合／條件（依現行速率上限約 20 筆／小時推算，60 組合約需 3 小時分批查完，是背景排程可接受的上限；PO 未逐字確認這個數字，執行前於 product-spec 中列為 assumption，可隨時修正） | Claude（assumption） | 2026-09-24 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
- Q-001～Q-006 直接來自 SRC-001 記錄的 AskUserQuestion 對話，逐字對應
  PO 選擇的選項。
- Q-007～Q-009 是 pre-spec 階段針對 extracted-requirements.md 的
  GAP-001～GAP-003 追加提出的釐清問題，同樣以 AskUserQuestion 取得
  PO 明確決定。
- Q-010（組合數上限的具體數字）標記為 Non-blocking＋Claude assumption：
  阻斷的是「要不要設上限」這個範圍決定（Q-009，已回答），上限的精確
  數值屬於可隨時調整的技術參數，不阻塞 product-spec 定案。
