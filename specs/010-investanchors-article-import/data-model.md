# Data Model: 定錨產業筆記文章自動匯入

資料庫：`<data_dir>/articles.db`（獨立，`ArticleStore`，比照 `flight_store.py`：`check_same_thread=False`、
`row_factory=sqlite3.Row`、`executescript(SCHEMA)` 全部 `CREATE TABLE IF NOT EXISTS`、**建構子不寫入任何資料列**）。
圖片檔：`<data_dir>/articles_images/<article_id>/<seq>.<ext>`。

## 表

### `article`（文章；不含分類）
| 欄位 | 型別 | 說明 |
|---|---|---|
| article_id | INTEGER PK | `/user/vip_contents/<數字>` 的數字（唯一身分，FR-003）；實測為 14 位數，SQLite 64 位整數足夠 |
| url | TEXT NOT NULL | 完整原文網址 |
| title | TEXT NOT NULL | 標題（**取自清單連結文字**，通知信主旨為輔；文章頁無 h1，不依賴其標題選擇器） |
| list_date | TEXT | 清單上顯示的日期（**僅供顯示與 `deferred` 紀錄**，不參與新舊判斷或半年截止） |
| published_at | TEXT | 發布時間（ISO，含時分；取自文章頁 `span.post_date`；清單日期對置頂項不可靠，**不參與新舊判斷與半年截止**） |
| id_time_ms | INTEGER | 由文章 ID 推得的建立時間（14 位數 ID 的前 13 位，epoch 毫秒）；不合規格時為 NULL |
| id_time_ok | INTEGER NOT NULL DEFAULT 1 | 0＝ID 形態或換算時間不合理（防呆，R11）：該篇不得被判為「早於截止日」 |
| pinned | INTEGER NOT NULL DEFAULT 0 | 1＝曾在清單的第 1、2 頁同時出現（置頂項）；置頂項不被當舊文跳過 |
| body | TEXT | 全文；僅在 `status='fetched'` 時非空（FR-013 不寫殘缺全文） |
| status | TEXT NOT NULL | `discovered`／`fetched`／`failed`／`abandoned`／`skipped`／`deferred`（清單看到、早於回補截止日、未抓取；只存 ID、標題、日期，`body` 為 NULL） |
| attempts | INTEGER NOT NULL DEFAULT 0 | 累計失敗次數（達 3 → abandoned） |
| last_error | TEXT | 最近一次失敗原因（**不含全文／帳密**） |
| discovered_via | TEXT | `mail`／`weekly`／`backfill` |
| discovered_at / fetched_at | TEXT | ISO 時間 |

### `article_image`
| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| article_id | INTEGER NOT NULL → article | |
| seq | INTEGER NOT NULL | 文中順序；`UNIQUE(article_id, seq)` |
| src_url | TEXT | 原圖網址（補抓用） |
| file_path | TEXT | 相對 `data_dir` 的本機路徑；下載失敗為 NULL（標記缺，下次補抓） |
| is_table | INTEGER | 1／0／NULL（模型判斷；未判斷為 NULL） |
| transcription_status | TEXT NOT NULL | `done`／`untranscribed`／`not_table` |
| transcribe_attempts | INTEGER NOT NULL DEFAULT 0 | 轉寫嘗試「送出後仍維持 `untranscribed`」的累計次數（成功或 `not_table` 不再計；abort 未送出不計）；達 `MAX_TRANSCRIBE_ATTEMPTS`＝3 不再自動補轉，`--retranscribe` 不受限；舊表由 `_ensure_columns` 自動補欄位 |
| transcription | TEXT | **只存轉寫內容**，不含任何標示或路徑（標示由輸出層加，避免 LIKE 搜尋被標示用字命中所有文章） |
| transcribed_model | TEXT | 例：`claude-haiku-5-5`（升級模型時可辨識哪些要重轉） |

### `mail_clue`（通知信線索；只是觸發，不是身分）
`message_id TEXT PRIMARY KEY`、`mail_date TEXT`（寄達時間，ISO，台北時區）、`seen_at`、`processed INTEGER`。
只用來判斷「有沒有未處理的新信」；**不含文章 ID、標題或連結**（信中連結是追蹤轉址，不解析、不記錄）。

### `backfill_state`（單列）
`id=1`、`completed INTEGER`（0／1）、`next_cursor TEXT`（清單續讀位置；形式依 P1 探查而定）、
`cutoff_date TEXT`（截止日＝回補**首次啟動日**往前六個月，ISO 日期）、`cutoff_ms INTEGER`（同一時點的 epoch 毫秒，
供與 `article.id_time_ms` 比較）；啟動後固定不隨日期漂移，除非 PO 用
`--backfill-since` 放寬並重新開啟回補、`started_at`、`updated_at`。

### `import_runs`（執行紀錄；用來強制上限與驗證 SC-004）
`id`、`started_at`、`finished_at`、`trigger`（`mail`／`weekly`／`backfill`／`none`）、`logged_in INTEGER`（**已嘗試登入**，用來計當日額度，只升不降；密碼錯誤等失敗的嘗試也算）、`login_ok INTEGER`（登入是否成功；沒嘗試為 NULL）、
`articles_attempted`、`articles_fetched`、`result`（`ok`／`partial`／`login_failed`／`blocked`／`structure_changed`／`aborted_limit`）、
`logged_out INTEGER`（**必為 1 才算合格**）、`blocked_until TEXT`（被擋後下一次最早時間）。

### `setting`（設定；單純 key/value）
`key TEXT PRIMARY KEY`、`value TEXT`。目前只存 **`transcribe_enabled`（轉寫啟用開關；沒有此列＝關閉，預設關閉）**。關閉時圖片照常下載、一律 `untranscribed`、不呼叫模型 API、不讀取 `vision-api-key`；**不得用鑰匙圈有沒有金鑰當開關**。

### `alert_log`（通知去重，比照 `statement_alerts`/`alert_once`）
`kind`、`key`、`day`；同 kind+key 同日只通知一次。

## 狀態機（article.status）

```
discovered ──取文成功──▶ fetched            （終態；不覆寫、不更新）
discovered ──失敗──▶ failed(attempts+1) ──下次排程再試──▶ fetched
failed ──attempts≥3──▶ abandoned + Telegram （終態；PO 介入後可手動重置為 failed）
discovered ──標題以【公告】開頭──▶ skipped   （終態；FR-004）
（回補時）id_time_ok=1 且 id_time_ms < cutoff_ms − 14 天，且非置頂、非公告 ──▶ deferred    （不開啟；只存 ID、標題、清單日期）
deferred ──PO 要求補抓（放寬截止日，`--backfill-since`）──▶ discovered ──▶（走上面的流程）
```
**半年截止只看 ID 推得的建立時間**，**不使用清單日期**（置頂的近期文章清單日期會顯示 2021 年）；`id_time_ok=0` 的文章
一律不得進入 `deferred`，照常處理。判斷新舊或是否已抓仍只看 `article_id`。`deferred` 的文章
之後若被通知信指到（理論上不會：通知信只寄新文章），直接轉 `discovered` 並抓取。
同一次執行內：進入 `failed` 的文章**不再嘗試**（FR-012）。`fetched` 的文章再從信或清單被看到 → 無動作
（不重新開啟，FR-003）。

## 驗證規則
- `article_id` 必須是正整數；`id_time_ms` 僅在 ID 為 14 位數且前 13 位換算的時間介於 2020-01-01 與「現在＋1 天」之間時設值，否則 `id_time_ok=0`；URL 必須符合 `^https://(www\.)?investanchors\.com/user/vip_contents/\d+$`（站內路徑才收）。
- `status='fetched'` ⇔ `body` 非空且長度 ≥ 下限（防殘缺：下限由探查 P6 後定，起始 200 字）。
- 常數（`investanchors_import.py`／`article_store.py`，2026-11-15 審查決定）：`BACKFILL_TRANSCRIBE_PER_RUN=10`（夜間每次最多補轉幾張舊圖）、`MAX_TRANSCRIBE_ATTEMPTS=3`。補轉順序：`transcribe_attempts` 少的先，再依 article_id／seq；僅 `status=fetched` 文章。`ArticleStore.transcription_counts()` 回 `{"untranscribed", "exhausted"}`（供 T050 健康檢查）。
- `transcription` 只含轉寫內容；「機器轉寫」標示一律在輸出時（`get_article`／`search_articles` 片段）加上，不入庫。`untranscribed` 時 `transcription` 必為 NULL（不以空白／猜測充數，FR-017）。
- 只增不刪：store 不提供 delete 方法；放棄的文章只改 status。
- 日誌／`last_error`／通知 **不得含** 帳密、cookie、全文（以單元測試對日誌輸出做負向斷言）。
