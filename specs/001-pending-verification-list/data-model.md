# Data Model: Pending Verification List

**Phase 1 output** — 沿用 `docs/spec-intake/pending-verification-list/
product-spec.md`「資料模型與狀態轉換」章節已定案的內容（PO 已核准），
本文件把它整理成 Spec Kit 慣例的 data-model 格式，供 `/speckit.tasks`
拆解實作任務時直接引用，內容不新增決策。

## Entity: PendingVerification

代表一個附帶「未來某時間點/事件發生就能驗證」但書的判斷或假設。

### Storage

新增 SQLite 表 `pending_verifications`（`poc/kb-mcp/kb_store.py`
`SCHEMA` 常數），沿用既有 `_migrate()` 欄位遷移機制。不建外鍵約束（比照
`stock_themes`／`comments` 等既有表不強制關聯完整性的風格）。

### Fields

| 欄位 | 型別 | Nullable | 說明 | 驗證規則 |
|---|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 否 | | |
| `code` | TEXT | 是 | 可選，關聯的股票代碼；不強制單一標的 | 無格式驗證（比照既有 `stances.code` 自由文字） |
| `theme` | TEXT | 是 | 可選，對應既有 `stock_themes` 的主題文字 | 無外鍵約束 |
| `judgment_text` | TEXT | 否 | 判斷/假設內容 | 必填，非空字串 |
| `trigger_type` | TEXT | 否 | `date` 或 `event` | 必填，只接受這兩個值之一 |
| `trigger_date` | TEXT | 是 | 預期時間點，`YYYY-MM-DD` | `trigger_type=date` 時必填；`event` 時可選（見 Assumptions：未填則不參與「已到期」判斷） |
| `trigger_condition_text` | TEXT | 否 | 觸發條件文字描述 | 必填，非空字串 |
| `target_value` | TEXT | 是 | 可選，具體驗證目標（如「毛利率75%」） | 無格式驗證，自由文字 |
| `status` | TEXT | 否 | `pending`／`resolved`／`dropped` | 必填，預設 `pending`；只接受這三個值之一 |
| `resolution` | TEXT | 是 | 驗證結論或不追蹤原因 | `status` 轉為 `resolved` 時必填；`dropped` 時可選 |
| `resolved_at` | TEXT | 是 | 標記解決的時間戳（ISO datetime） | 狀態轉為 `resolved`／`dropped` 時系統自動寫入 |
| `source_ref` | TEXT | 是 | 來源引用 | 無格式驗證，比照既有 `source_ref` 慣例 |
| `created_at` | TEXT | 否 | | 系統自動寫入 |
| `updated_at` | TEXT | 否 | | 系統自動寫入，每次狀態轉換時更新 |

### State Transitions

```
        save()
          │
          ▼
      [pending] ──resolve(resolution)──> [resolved]  (終態)
          │
          └──────drop(resolution?)─────> [dropped]   (終態)
```

- 新建項目一律從 `pending` 開始（FR-001）
- `pending → resolved`：需提供 `resolution`，系統寫入 `resolved_at`
  （FR-005）
- `pending → dropped`：`resolution` 可選（語意上代表「為何不追蹤了」）
  （FR-006）
- `resolved`／`dropped` 為終態，不可逆（FR-007）——沒有
  `resolved/dropped → pending` 的轉換；要重新追蹤同一判斷須登記新項目
  （比照既有 `stances` 用多筆歷史列而非改寫既有列的模式）

### Query Patterns（供 API/MCP tool 設計參考）

1. 依 `status` 篩選（FR-003）：`WHERE status = ?`
2. 「已到期」清單（FR-004）：`WHERE status = 'pending' AND trigger_date
   IS NOT NULL AND trigger_date <= date('now', '+7 days')`（7天窗口見
   `research.md` 決策5，含已過期與即將到期）
3. 單筆查詢：`WHERE id = ?`

### Relationships

不與既有表建立外鍵關聯（`stock_themes`／`comments`／`position_plans`
維持不變，`code`／`theme` 欄位僅供人類/查詢對照，非資料庫層級約束）——
這是 pre-spec 階段的明確決定（Q-002=A 全新獨立表）。
