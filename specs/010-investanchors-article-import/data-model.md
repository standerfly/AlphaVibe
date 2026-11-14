# Data Model: 定錨產業筆記文章自動匯入

資料庫：`<data_dir>/articles.db`（獨立，`ArticleStore`，比照 `flight_store.py`：`check_same_thread=False`、
`row_factory=sqlite3.Row`、`executescript(SCHEMA)` 全部 `CREATE TABLE IF NOT EXISTS`、**建構子不寫入任何資料列**）。
圖片檔：`<data_dir>/articles_images/<article_id>/<seq>.<ext>`。

## 表

### `article`（文章；不含分類）
| 欄位 | 型別 | 說明 |
|---|---|---|
| article_id | INTEGER PK | `/user/vip_contents/<數字>` 的數字（唯一身分，FR-003） |
| url | TEXT NOT NULL | 完整原文網址 |
| title | TEXT NOT NULL | 標題 |
| published_at | TEXT | 發布日期（ISO；清單日期不可靠，僅作顯示，**不參與新舊判斷**） |
| body | TEXT | 全文；僅在 `status='fetched'` 時非空（FR-013 不寫殘缺全文） |
| status | TEXT NOT NULL | `discovered`／`fetched`／`failed`／`abandoned`／`skipped` |
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
| transcription | TEXT | 轉寫文字（儲存時已含「機器轉寫」標示前綴） |
| transcribed_model | TEXT | 例：`claude-haiku-4-5-20251001`（升級模型時可辨識哪些要重轉） |

### `mail_clue`（通知信線索；只是觸發，不是身分）
`message_id TEXT PRIMARY KEY`、`article_id INTEGER`（可為 NULL＝尚未解析出 ID）、`title`、`seen_at`、
`processed INTEGER`。同一篇多封信＝多列，不影響 `article` 去重。

### `backfill_state`（單列）
`id=1`、`completed INTEGER`（0／1）、`next_cursor TEXT`（清單續讀位置；形式依 P1 探查而定）、`updated_at`。

### `import_runs`（執行紀錄；用來強制上限與驗證 SC-004）
`id`、`started_at`、`trigger`（`mail`／`weekly`／`backfill`／`none`）、`logged_in INTEGER`、
`articles_attempted`、`articles_fetched`、`result`（`ok`／`partial`／`login_failed`／`blocked`／`structure_changed`／`aborted_limit`）、
`logged_out INTEGER`（**必為 1 才算合格**）、`blocked_until TEXT`（被擋後下一次最早時間）。

### `alert_log`（通知去重，比照 `statement_alerts`/`alert_once`）
`kind`、`key`、`day`；同 kind+key 同日只通知一次。

## 狀態機（article.status）

```
discovered ──取文成功──▶ fetched            （終態；不覆寫、不更新）
discovered ──失敗──▶ failed(attempts+1) ──下次排程再試──▶ fetched
failed ──attempts≥3──▶ abandoned + Telegram （終態；PO 介入後可手動重置為 failed）
discovered ──標題以【公告】開頭──▶ skipped   （終態；FR-004）
```
同一次執行內：進入 `failed` 的文章**不再嘗試**（FR-012）。`fetched` 的文章再從信或清單被看到 → 無動作
（不重新開啟，FR-003）。

## 驗證規則
- `article_id` 必須是正整數；URL 必須符合 `^https://(www\.)?investanchors\.com/user/vip_contents/\d+$`（站內路徑才收）。
- `status='fetched'` ⇔ `body` 非空且長度 ≥ 下限（防殘缺：下限由探查 P6 後定，起始 200 字）。
- `transcription` 非 NULL ⇒ 必以固定「機器轉寫」標示開頭；`untranscribed` 時 `transcription` 必為 NULL（不以空白／猜測充數，FR-017）。
- 只增不刪：store 不提供 delete 方法；放棄的文章只改 status。
- 日誌／`last_error`／通知 **不得含** 帳密、cookie、全文（以單元測試對日誌輸出做負向斷言）。
