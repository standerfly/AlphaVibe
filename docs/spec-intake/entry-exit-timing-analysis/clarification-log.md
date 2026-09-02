# Clarification Log: 進出場時機分析工具

**Feature Slug:** entry-exit-timing-analysis
**Last Updated:** 2026-09-01

| ID | Question Or Conflict | Source IDs | Impact Area | Status | Answer Or Decision | Owner | Date |
|----|----------------------|------------|-------------|--------|--------------------|-------|------|
| Q-001 | MVP 範圍應該涵蓋 SRC-001 列出的哪幾項缺口？三項優先項（損益追蹤／股價歷史高低位／停損停利）之外，「基本面背離偵測」「營收趨勢範圍擴大」是否也要納入 MVP？ | SRC-001 | Scope | Answered | **五項全部納入 MVP**，不再區分優先/Deferred；「基本面背離偵測」「營收趨勢範圍擴大」不 Deferred，直接做 | Stander | 2026-09-01 |
| Q-002 | 損益追蹤要不要包含已出清（賣掉）標的的已實現損益，還是只計算目前持有中部位的未實現損益？ | SRC-001 | Scope / Data | Answered | **兩種都要算**——已實現損益（已出清標的）與未實現損益（目前持有）都要涵蓋 | Stander | 2026-09-01 |
| Q-003 | 停損/停利觸發的門檻規則是什麼？(a) 全體統一固定百分比 (b) 依信心分級/框架動態決定 (c) 由 PO 每檔手動設定 | SRC-001 | Domain Rule | Answered | **(c) 的變體**：不是 PO 自己單方設定，也不是系統自動決定——**每檔股票的門檻都要由 PO 與 Claude 討論後才設定**，是一個協作式設定流程，非固定公式、非全自動 | Stander | 2026-09-01 |
| Q-004 | 這些新分析要以什麼形式呈現？(a) MCP 工具 (b) 報告頁面 (c) 兩者都要 | SRC-001 | Workflow / API | Answered | **(c) 兩者都要**——MCP 工具（供 Claude 對話查詢）與報告頁面（`report.py`／`app/`）整合皆需要 | Stander | 2026-09-01 |
| Q-005 | 要不要整合進既有模組D每日排程，讓訊號能主動提醒；還是先做被動查詢工具？ | SRC-001 | Integration | Answered | **要整合**——納入既有模組D每日排程（17:00 自動跑），主動觸發提醒並寫入 Layer 2 立場記錄 | Stander | 2026-09-01 |
| Q-006 | （Q-001 答案的延伸澄清）「討論推薦其他策略」具體範圍是什麼？(a) 鎖定在觸發訊號當下，建議該檔接下來可以怎麼調整（換股/減碼/對沖/續抱理由） (b) 更廣的主動策略發現（例如整合 screen_stocks/market_scan 主動比對有沒有更好標的） | SRC-001 | Scope | Answered | **(a)**——鎖定在觸發訊號當下（停損/停利/背離訊號成立時），系統除了標示訊號本身，也要一併建議該檔持股接下來可以怎麼調整；**不做**更廣的主動選股/策略發現，那屬於獨立範圍，本輪不做 | Stander | 2026-09-01 |

## Notes

- Status values: Open, Blocking, Answered, Non-blocking, Deferred, Out of Scope.
- 本輪 6 題（Q-001~Q-006，Q-006 為 Q-001 的延伸澄清，不計入下一輪額度）
  皆已 Answered，MVP 範圍已確定為 SRC-001 列出的全部 5 項功能缺口
  ＋ 1 項新增的「觸發時策略建議」功能。
- 後續補齊狀態（2026-09-01 同日更新）：
  - Business Context 的 Priority／Timing——**已補齊**：PO 2026-09-01
    決定本功能為 roadmap 第一順位、分兩階段交付，見 `product-spec.md`
    Business Context And Priority 節與 `scope-decision.md`
    Split Feature Decisions
  - Error Handling 的具體失敗情境定義——**已補齊**：見 `product-spec.md`
    Error Handling Requirements 節（5 列矩陣），行為沿用本 repo 既有
    慣例（`benchmark.py` 優雅降級模式＋「算不出來就明講、不要畫 0%
    空條」三分狀態原則），非新發明
  - 停損/停利門檻的儲存機制細節（每股門檻要存在哪、能不能事後修改）
    ——**仍待展開**，屬技術設計細節，留給 spec-kit-input 階段
    （對應 readiness-checks.md GAP-R02 Data model note）；product-spec
    層級只需定義「系統要能記住 PO 與 Claude 討論後設定的門檻」這個
    產品行為，此部分已完成
