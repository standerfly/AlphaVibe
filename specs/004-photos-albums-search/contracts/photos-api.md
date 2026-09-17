# API Contract: 相簿分頁 HTTP 端點

**Feature**: 004-photos-albums-search | **Date**: 2026-09-17

**格式說明**：既有 Spec Kit 先例（`specs/001-entry-exit-foundation/`、
`specs/003-us-stocks/`）的 contracts 都是 MCP tool 格式，因為那兩個
功能的產品需求本身就是「透過 Claude 對話查詢/分析」。相簿分頁的
`spec.md` 完全沒有對話式查詢需求——所有使用情境都是網頁 UI 操作
（匯入、瀏覽、搜尋、標記），因此本次改用 REST API 端點格式描述契約，
這是本 repo 第一次在 Spec Kit 產物裡用這個格式。**這些是 STND
`app/` 內部前後端之間的端點，不是對外公開 API**，前端 `web/src/
api/client.js` 會呼叫這些端點；`app/routers/photos.py` 內部直接
呼叫 `poc/kb-mcp/photo_store.py`／`photo_importer.py`／
`photo_metadata_sync.py`，不重寫商業邏輯。

所有端點均為 `/api/photos/*`，遵循既有 STND 認證中介層（Basic Auth，
比照既有 router 慣例，此處不重複描述認證機制）。

---

## 相簿管理

### `GET /api/photos/albums`

列出所有相簿。

**回應**：
```json
{"albums": [{"id": 1, "title": "2026 奧日光奧會津", "description": "",
  "cover_photo_id": 42, "photo_count": 87}]}
```

### `POST /api/photos/albums`

建立相簿。**請求**：`{"title": "...", "description": ""}`
**回應**：`{"id": 5, "title": "...", "description": ""}`

### `PATCH /api/photos/albums/{album_id}`

更新標題/描述/封面照。**請求**（任一欄位可省略）：
`{"title": "...", "description": "...", "cover_photo_id": 42}`

### `DELETE /api/photos/albums/{album_id}`

刪除相簿（不影響照片本身，只移除 `photo_albums` 關聯與相簿記錄）。

### `GET /api/photos/albums/{album_id}/photos`

列出該相簿內的照片（縮圖牆用）。支援 `?sort=date|rating`、
`?tag=<name>` 篩選。

---

## 匯入

### `GET /api/photos/browse-folders?path=<絕對路徑>`

伺服器端唯讀資料夾瀏覽，供匯入畫面選路徑用（見 research.md §5）。
省略 `path` 時回傳一組合理的起始位置（例如使用者家目錄）。

**回應**：
```json
{"path": "/Volumes/Photos", "folders": [
  {"name": "2026-11-import", "path": "/Volumes/Photos/2026-11-import"}]}
```

### `POST /api/photos/import/scan`

掃描來源資料夾，計算去重預覽（**不複製檔案**，見 research.md §4：
`file_hash` 在這一步對來源檔案計算）。

**請求**：
```json
{"source_path": "/Volumes/Photos/2026-11-import",
  "storage_location": "internal"}
```

**回應**：
```json
{"scan_token": "abc123", "total": 100, "new_count": 87,
  "duplicate_count": 13, "unreadable": []}
```

`scan_token` 供下一步 `import/commit` 引用，避免重新掃描；
`unreadable` 列出無法讀取/格式不支援的檔案名稱（見 spec.md Edge
Cases）。

### `POST /api/photos/import/commit`

確認匯入，啟動背景任務。**請求**：`{"scan_token": "abc123"}`
**回應**：`{"job_id": "job-789", "status": "running"}`

### `GET /api/photos/import/jobs/{job_id}`

輪詢匯入進度。**回應**：
```json
{"job_id": "job-789", "status": "running|completed|failed",
  "imported_count": 42, "total": 87, "skipped_duplicates": 13}
```

---

## 照片整理與詳情

### `GET /api/photos/photos/{photo_id}`

單張照片詳情（含 EXIF、所屬相簿、標籤、`metadata_sync_status`）。

### `PATCH /api/photos/photos/{photo_id}`

編輯評分/標籤（任一欄位可省略）。**請求**：
```json
{"rating": 4, "tags": ["夕陽", "京都"]}
```
儲存後立即生效於搜尋（見 spec.md FR-013），並把
`metadata_sync_status` 設回 `pending`，觸發背景中繼資料寫回
（見 research.md §2、§3）。

### `POST /api/photos/photos/batch`

批次操作（多選套用相簿/標籤/評分）。**請求**：
```json
{"photo_ids": [1, 2, 3], "add_album_id": 5, "add_tags": ["街拍"],
  "set_rating": 4}
```

### `POST /api/photos/photos/{photo_id}/resync`

手動重新觸發中繼資料寫回（見 spec.md User Story 3 Acceptance
Scenario 3）。**回應**：`{"status": "pending"}`（背景任務會再嘗試一次）。

### `DELETE /api/photos/photos/{photo_id}`

刪除照片記錄（僅刪 db，不動磁碟原始檔，見 spec.md FR-011）。

---

## 搜尋與標籤

### `GET /api/photos/search`

跨所有相簿的全域搜尋（見 spec.md User Story 2）。

**Query 參數**：`camera_model`、`lens`、`tags`（可重複，多個標籤取
交集）、`limit`、`offset`

**回應**：
```json
{"total": 12, "photos": [{"id": 42, "thumbnail_path": "...",
  "rating": 4, "camera_model": "Sigma fp L"}]}
```

### `GET /api/photos/tags?q=<前綴>`

標籤自動完成建議（見 spec.md FR-006）。

**回應**：`{"tags": ["夕陽", "夕陽紅"]}`
