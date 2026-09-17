# Data Model: 相簿分頁（Photo Albums & Search）

儲存於獨立 SQLite 檔 `poc/data/photos.db`，透過新的 `PhotoStore` 類別
（`poc/kb-mcp/photo_store.py`）存取。比照 `us_stock_store.py`：
`__init__` 只執行 `CREATE TABLE IF NOT EXISTS`，不寫入任何列；表之間
以邏輯鍵關聯，不建外鍵約束（比照既有慣例，方便獨立測試與資料修復）。

本檔案只涵蓋本功能（`spec.md` Key Entities：Album／Photo／Tag）範圍
內的表。`trip_albums`（供未來 `travel-diary` 功能連結相簿與旅行）**不**
在本次範圍內建立，待該功能自己的 `/speckit.plan` 階段再對這個資料庫
新增。

## `albums`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | |
| `title` | TEXT NOT NULL | 相簿標題 |
| `description` | TEXT | 選填描述 |
| `cover_photo_id` | INTEGER | 指向 `photos.id`（邏輯關聯，非外鍵）；相簿沒有照片時為 NULL |
| `created_at` | TEXT NOT NULL | ISO 8601 時間戳 |

## `photos`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | |
| `file_hash` | TEXT NOT NULL UNIQUE | MD5，匯入掃描時對來源檔案計算一次並永久保存，**之後任何時候都不重新計算**（見 research.md §4，這是刻意設計，去重機制的正確性依賴這一點） |
| `storage_path` | TEXT NOT NULL | 複製後的實際檔案路徑（內接或外接硬碟下） |
| `storage_location` | TEXT NOT NULL | `internal` \| `external` |
| `thumbnail_path` | TEXT NOT NULL | 縮圖路徑，固定存內接硬碟 |
| `rating` | INTEGER NOT NULL DEFAULT 0 | 0-5 |
| `camera_model` | TEXT | 讀取自來源檔案既有 EXIF，可能為 NULL（例如螢幕截圖） |
| `lens` | TEXT | 同上 |
| `iso` | INTEGER | 同上（MVP 讀取但不特別在 UI 強調，供未來擴充） |
| `shutter_speed` | TEXT | 同上 |
| `aperture` | TEXT | 同上 |
| `photo_date` | TEXT | 拍攝日期（EXIF `DateTimeOriginal`），可能為 NULL |
| `file_size` | INTEGER | bytes |
| `imported_at` | TEXT NOT NULL | ISO 8601 時間戳 |
| `metadata_sync_status` | TEXT NOT NULL DEFAULT `'pending'` | `synced` \| `pending` \| `failed`（見 spec.md FR-012~014） |
| `metadata_synced_at` | TEXT | 最近一次成功寫回檔案的時間戳，可能為 NULL |
| `metadata_sync_error` | TEXT | 失敗原因（`failed` 狀態時），可能為 NULL |

**驗證規則**：
- `rating` 必須是 0 到 5 的整數，超出範圍在 `PhotoStore` 層拒絕寫入
- `file_hash` 唯一——匯入掃描階段用它判斷「這張照片是否已存在」，
  重複的一律跳過，不寫入新的 `photos` 列

**狀態轉換**（`metadata_sync_status`）：

```text
                 標籤/評分被編輯
                        │
                        ▼
   [pending] ──寫回成功──▶ [synced]
        │                     │
        │ 硬碟離線/exiftool失敗│ 標籤/評分再次被編輯
        ▼                     ▼
   [failed] ◀───寫回仍失敗──[pending]
        │
        │ 使用者手動「重新同步」
        ▼
   （重新走一次寫回流程）
```

任何一次標籤或評分編輯，都會把該照片的 `metadata_sync_status` 立即
設回 `pending`（不論之前是什麼狀態），代表資料庫端的資料已經是最新、
但檔案端還沒跟上；背景任務寫回成功才轉 `synced`，失敗才轉 `failed`。

## `photo_albums`（多對多）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `photo_id` | INTEGER NOT NULL | 邏輯關聯 `photos.id` |
| `album_id` | INTEGER NOT NULL | 邏輯關聯 `albums.id` |

複合唯一鍵 `(photo_id, album_id)`，避免同一張照片被重複加入同一個
相簿兩次。

## `tags`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | |
| `name` | TEXT NOT NULL UNIQUE | 標籤文字（例：日出、夕陽、京都），大小寫/前後空白正規化後比對唯一性，避免「京都」跟「京都 」變成兩個標籤 |

**正規化主檔的理由**：不採 AutoGallery 原型「`photo_id`+`tag_name`
自由文字窄表」的做法（那樣同義詞會各自長成一個標籤）；`tags` 獨立
成主檔，前端輸入標籤時可以查詢既有 `tags` 做自動完成建議（見 spec.md
FR-006）。

## `photo_tags`（多對多）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `photo_id` | INTEGER NOT NULL | 邏輯關聯 `photos.id` |
| `tag_id` | INTEGER NOT NULL | 邏輯關聯 `tags.id` |

複合唯一鍵 `(photo_id, tag_id)`。

## 查詢模式（供 `PhotoStore` 方法設計參考，非正式 schema）

- **全域搜尋**（spec.md User Story 2）：`photos` 依 `camera_model`／
  `lens` 過濾，再與 `photo_tags` join `tags` 依標籤名稱過濾（多個標籤
  時取交集——「同時符合這些標籤」，比照 spec.md Acceptance Scenario
  「相機＋標籤同時符合」的語意）；結果不 join `photo_albums`，搜尋本身
  跨相簿、不限定相簿範圍
- **相簿內縮圖牆**：`photo_albums` 依 `album_id` 找出所有 `photo_id`，
  再查 `photos`
- **標籤自動完成**：直接查 `tags.name`，依輸入前綴或包含比對
