# Data Model: Substack 文章抓取與儲存（011，第 1 包）

**Date**: 2026-11-19 ｜ 依據：spec.md Key Entities、FR；research.md R5～R8。
儲存：`<data_dir>/substack.db`（SQLite，獨立於 010 的 `articles.db`，FR-006）＋`<data_dir>/substack_images/`＋設定檔
`<data_dir>/substack_config.json`（格式見 `contracts/config-format.md`）＋執行鎖檔 `<data_dir>/.substack_import.lock`。
時間欄位一律帶時區的 ISO 字串（台北 `+08:00`，比照 010）。所有表名、欄位名與 010 無共用；011 不在 `articles.db` 建任何東西。

## 1. 實體與資料表

### 1.1 追蹤作者 `author`（spec：追蹤作者；FR-002、FR-004、FR-008、FR-032）

設定檔是「是否啟用、顯示名稱、feed 網址」的唯一來源；本表只存**執行狀態**，每次執行開頭依設定檔同步。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `author_key` | TEXT PK | 設定檔 `key`（例 `fomosoc`、`unclestocknotes`），日誌只用這個代號 |
| `display_name` | TEXT | 同步自設定檔（通知與手動轉寫報告用） |
| `feed_url` | TEXT | 同步自設定檔 |
| `last_seen_enabled` | INTEGER 0/1 | 上一次非 dry-run 執行看到的啟用狀態（判斷「重新啟用」） |
| `activated_at` | TEXT | 首次／重新啟用被看到的時間；14 天窗的基準（FR-008） |
| `window_from` | TEXT（日期） | `activated_at` 台北日期往前 14 天；早於此發布者不自動存 |
| `etag` | TEXT NULL | 上次 200 回應的 ETag 原字串（FR-003 條件請求） |
| `last_request_at` | TEXT NULL | 上次對 feed **實際發出**請求的時間（含 304、失敗）；最小間隔依據（FR-004） |
| `last_outcome` | TEXT NULL | 上次結果代碼（見 §2.4） |
| `last_success_at` | TEXT NULL | 上次 200／304 的時間（健檢「上次成功時間」） |
| `consecutive_failures` | INTEGER | 連續失敗次數；200／304 歸零；間隔跳過不變（FR-032） |

### 1.2 文章 `article`（spec：文章；FR-006～FR-012、FR-025）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 內部編號（日誌、圖片目錄用；不與 010 的 article_id 混用） |
| `author_key` | TEXT NOT NULL | → `author.author_key` |
| `guid` | TEXT NULL，UNIQUE（非 NULL 時） | RSS guid 原字串（去重鍵一） |
| `link` | TEXT NOT NULL | RSS link 原字串（供去重與日後查找；**不進通知**，PO 決定 A1，FR-025） |
| `link_norm` | TEXT NOT NULL UNIQUE | 正規化網址（去重鍵二，規則見 research R6） |
| `title` | TEXT NOT NULL | **資料通道**：只存庫與通知，不進日誌（FR-026） |
| `published_at` | TEXT NOT NULL | pubDate 解析值（解析不了不入庫，research R6） |
| `fetched_at` | TEXT NOT NULL | 存入時間；全文占比「抓取日」依此（FR-013） |
| `source` | TEXT | `schedule`／`manual`／`backfill` |
| `completeness` | TEXT NOT NULL | **原判斷**：`P`（僅預覽）／`F`（全文）／`N`（非文字）（FR-010）；寫入後**不可改**（重判結果另存 §1.9，FR-033） |
| `classify_reason` | TEXT NOT NULL | 原判斷依據：`read_more_tail`／`text_ge_200`／`text_lt_200`／`uncertain:<代碼>`（不確定者 completeness 一律 `P`，FR-012）；`text_ge_200`＝可見文字 ≥200 字（FR-010） |
| `content_html` | TEXT | `content:encoded` 原文（P 即為公開預覽本身，FR-011）；**重判（FR-033）的唯一輸入**，寫入後不可改 |
| `body_text` | TEXT NULL | 轉換後純文字，含圖位標記〔圖 N｜圖說：…｜alt：…〕（FR-014）；P 類不含尾端 Read more 段；**N 類恆為 NULL（不保存內文，PO 決定 Q14、FR-011）**——N 類的圖位標記改由 `article_image` 列（`seq`、圖說、alt）與 `content_html` 保存；寫入後不可改 |
| `description` | TEXT NULL | RSS description（預覽摘要） |
| `enclosure_type` | TEXT NULL | 例 `image/jpeg`、`audio/mpeg`（只記型別） |
| `notify_status` | TEXT NOT NULL | `pending`／`sent`／`failed`／`abandoned`（FR-025） |
| `notify_attempts` | INTEGER | 已嘗試次數（上限 3） |
| `notified_at` | TEXT NULL | 成功時間 |

索引：`UNIQUE(guid) WHERE guid IS NOT NULL`、`UNIQUE(link_norm)`、`(author_key, published_at)`、`(fetched_at)`。

唯讀視圖 `article_effective`（FR-033）：`article` 左連接「每篇最近一筆 `reclassification`」，輸出 `effective_completeness`（有重判取最近一筆的 `new_completeness`，否則 `article.completeness`）、`original_completeness`、`reclassified_count`、`effective_body_text`（**可搜尋內文的唯一出處**：有效完整度為 `N` → NULL；否則 `article.body_text` 非 NULL 時取之，否則取「最近一筆 `derived_body_text` 非 NULL 的重判紀錄」之值；FR-011、Q14）。查詢完整度（手動轉寫選取、`--status`、未來第 2 包搜尋）一律用 `effective_completeness`，取內文一律用 `effective_body_text`（N 類永遠 NULL；第 2 包搜尋只能索引 `effective_body_text` 非 NULL 者）；FR-013 全文占比用 `original_completeness`（research R7）。

### 1.3 圖片 `article_image`（spec：圖片；FR-014～FR-016）

（表名雖與 010 同名，但位於 `substack.db`，兩庫互不可見。）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PK | image_id（PO 要求重試、手動轉寫時用） |
| `article_id` | INTEGER NOT NULL | → `article.id` |
| `seq` | INTEGER NOT NULL | 圖位序號：0＝封面（enclosure image），1..n＝內文出現順序；`UNIQUE(article_id, seq)` |
| `src_url` | TEXT NOT NULL | 來源網址（**不進日誌**） |
| `alt` | TEXT NULL | alt 文字 |
| `caption` | TEXT NULL | figcaption 文字 |
| `status` | TEXT NOT NULL | `pending`（尚未嘗試）／`downloaded`／`missing`（缺圖，已失敗 1～2 次）／`abandoned`（放棄） |
| `fail_count` | INTEGER NOT NULL DEFAULT 0 | 補下載**連續**失敗次數（成功後不再使用；PO 重試時歸零） |
| `last_error_code` | TEXT NULL | `http_<碼>`／`timeout`／`network`／`host_not_allowed`／`not_image`／`too_large`／`redirect_refused`（只存代碼） |
| `file_path` | TEXT NULL | 相對資料目錄的路徑 `substack_images/<article_id>/<seq>.<ext>`；只有 `downloaded` 才非 NULL |
| `sha256` | TEXT NULL | 下載檔雜湊 |
| `bytes` | INTEGER NULL | 檔案大小（健檢占用量另以實際目錄計算） |
| `downloaded_at` | TEXT NULL | |

### 1.4 輪詢紀錄 `poll_log`（spec：輪詢紀錄；FR-004、FR-005、FR-029）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | → `run.id` |
| `author_key` | TEXT | |
| `at` | TEXT | 判斷或請求時間 |
| `requested` | INTEGER 0/1 | 是否真的打到站方（間隔跳過＝0） |
| `http_status` | INTEGER NULL | |
| `outcome` | TEXT | 見 §2.4 |
| `items_in_feed` | INTEGER NULL | 200 時的條目數 |
| `new_items` | INTEGER NULL | 本次新存篇數 |
| `skipped_window` | INTEGER NULL | 因 14 天窗略過 |
| `skipped_no_pubdate` | INTEGER NULL | |
| `all_new` | INTEGER 0/1 | 20 篇全為新文（漏文提示，Edge Case） |
| `duration_ms` | INTEGER NULL | |

### 1.5 執行 `run`（觀測、補跑判斷、時長實證 Q-105）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PK | |
| `started_at`／`finished_at` | TEXT | `finished_at` NULL＝被中斷 |
| `trigger` | TEXT | `schedule`／`catchup`（01:00 或醒來補跑）／`manual`／`backfill`／`retry_images`／`reclassify`（`--reclassify` 重判，FR-033） |
| `schedule_day` | TEXT NULL | 排程日（22:00 起算的日期）；只有 `schedule`／`catchup` 有值 |
| `result` | TEXT | `ok`／`partial`（有作者失敗）／`aborted_disk`／`aborted_budget`（20 分鐘牆鐘預算到，research R2）／`aborted_config`／`deferred`（23:00～00:59 啟動）／`already_done` |
| `authors_polled`／`authors_skipped_interval`／`authors_failed` | INTEGER | |
| `new_articles`／`images_downloaded`／`images_missing`／`images_abandoned_now` | INTEGER | |
| `notify_sent`／`notify_failed` | INTEGER | |
| `budget_exhausted` | INTEGER 0/1 | 牆鐘預算用完：圖片階段到 18 分鐘強制中止、或 20 分鐘整體強制中止（research R2） |

註：鎖拿不到（忙碌）時**不寫庫**（FR-017），只寫 stdout；所以忙碌不會出現在本表。`deferred`／`already_done` 只寫一列 `run`、零網路。**排程日判斷（FR-017）只看 `trigger IN ('schedule','catchup') AND result NOT IN ('deferred','already_done')` 的列**——`deferred`／`already_done` 是「沒有執行」的紀錄，不得讓補跑誤判為當日已跑。

### 1.6 robots 快取 `robots_cache`（FR-003）

`host` TEXT PK、`fetched_at` TEXT、`http_status` INTEGER、`body` TEXT（robots.txt 內容，公開資料）。

### 1.7 手動轉寫紀錄 `transcription_trial`、`image_transcription`（spec：手動轉寫紀錄；FR-022～FR-024）

`transcription_trial`：`id`、`started_at`、`finished_at`、`confirm_code`、`articles`、`images_attempted`、`images_ok`、`images_not_table`、
`images_failed`、`claude_calls`、`models`、`result`（`ok`／`partial`／`aborted_usage_limit`／`aborted_login`／`aborted_auth_mode`）、`reset_hint`。

`image_transcription`：`image_id` → `article_image.id`、`trial_id`、`is_table` 0/1、`text`（資料通道，可查找引用；FR-024 以直接讀庫驗證）、
`reader_model`、`verifier_model`、`verdict`（`ok`／`issues`／NULL）、`issues_json`、`created_at`；`UNIQUE(image_id, trial_id)`。

### 1.8 執行鎖、告警策略（spec Key Entities）

- 執行鎖：檔案 `<data_dir>/.substack_import.lock`（flock），不是資料表（research R8）。
- 告警策略：設定檔欄位 `alert_policy`（`every_failure` 預設／`consecutive_3`），不是資料表（research R5）。
- 最小輪詢間隔：設定檔欄位 `min_poll_interval_minutes`（預設 30、下限 10，FR-004）。
- 圖片主機白名單：設定檔欄位 `image_hosts`（初始兩個固定主機＋各作者 feed 主機自動允許；PO 可增修，FR-034），不是資料表。

### 1.9 重判紀錄 `reclassification`（spec：重判紀錄；FR-033）

只增不改（append-only）：沒有任何 UPDATE／DELETE 路徑。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `article_id` | INTEGER NOT NULL | → `article.id` |
| `at` | TEXT NOT NULL | 重判時間（台北 `+08:00`） |
| `trigger` | TEXT NOT NULL | `po_article`（`--article-ids`）／`po_author`（`--author`） |
| `old_completeness` | TEXT NOT NULL | 重判**當下的有效值**（第一次重判＝原判斷；之後＝前一次重判結果） |
| `new_completeness` | TEXT NOT NULL | `P`／`F`／`N`；不確定者仍一律 `P`（FR-012） |
| `new_reason` | TEXT NOT NULL | 同 `classify_reason` 的代碼集合 |
| `rule_version` | TEXT NOT NULL | 重判所用 `substack_html.RULE_VERSION`（讓日後看得出是哪一版規則判的） |
| `derived_body_text` | TEXT NULL | **僅在**文章 `body_text` 為 NULL（原判斷 N）而 `new_completeness` 為 `F` 或 `P` 時填：用與匯入同一個 `html_to_text`（P 則同樣去掉尾端 Read more 段）對保存的 `content_html` 重新轉換的結果，含圖位標記（FR-033、FR-011、Q14）；其他情況 NULL。重判為 `N` 時不填；既有 `body_text` 非 NULL 的文章也不填（不重算、不覆寫）。append-only，寫入後不可改 |
| `changed` | INTEGER 0/1 | `new_completeness != old_completeness` |
| `run_id` | INTEGER NULL | → `run.id`（本次重判寫的 `run` 列，`trigger='reclassify'`） |

索引：`(article_id, id)`。`--dry-run` 不寫任何列。結果相同也寫一列（證明已重判、規則版本為何）。

## 2. 狀態轉換

### 2.1 文章

```text
feed 條目 ──去重命中──────────────▶ 略過（不寫，計 duplicate）
   │  （guid 與 link_norm 各命中不同兩篇＝`dedupe_conflict`：同樣略過；計數只印 stdout／日誌、不入庫、無對應欄位）
   │──早於 window_from（非追補）──▶ 略過（不寫，計 skipped_window）
   │──pubDate 解析失敗（非追補）──▶ 略過（不寫，計 skipped_no_pubdate）
   └──單一交易寫入成功──────────▶ 已存（completeness=P|F|N，終態；不覆寫、不更新，FR-007；N 類 body_text=NULL、content_html 與圖片列照存，FR-011）
        交易失敗 → 回滾、不留紀錄 → 下次執行重新評估
```

### 2.2 通知（每篇文章）

`pending` →（送出成功）`sent` ｜ `pending`/`failed` →（失敗）`failed`（attempts+1）→ attempts=3 → `abandoned`。
每次執行先補發 `pending`/`failed`，再發新文章；同次不重試。

**N 類提醒（FR-035）**：N 類提醒是該篇逐篇通知本身的固定文字（`contracts/notifications.md §1`），沒有獨立的提醒狀態欄位——該篇通知 `sent` 後即不再有任何提醒（一次性、不催促）；通知失敗補發時重送的仍是同一則（含提醒）通知，成功後累計送達 1 次。重判（FR-033）永不發通知，故 N→F 或 F→N 的重判都不會產生新提醒。

### 2.2b 重判（FR-033）

```text
article（原判斷 P|F|N，永不改）
   │ PO 要求重判（--reclassify，取鎖、零網路、零模型）
   ▼
reclassification 新增一列（old=當下有效值 → new）──▶ 有效完整度＝最近一列 new（視圖 article_effective）
   │ 再次重判 → 再新增一列；先前所有列保留
   ▼
article.content_html／body_text／completeness／classify_reason 全程不變
```

**N 類重判為 F／P 的內文產生（Q14、FR-033）**：原判斷 N 的文章 `article.body_text` 恆為 NULL；重判結果為 F 或 P 時，`reclassify` 以保存的 `content_html` 重新呼叫 `html_to_text`，把結果寫入**該筆新增的 `reclassification.derived_body_text`**（不改 `article` 任何欄位，維持「重判前後 `article` 位元組不變」）；`article_effective.effective_body_text` 因此變為非 NULL，成為第 2 包可搜尋內容。若再次重判回 N，`effective_body_text` 回到 NULL（歷史的 `derived_body_text` 仍保留於舊列，不刪）；再重判為 F 時再產生新一筆 `derived_body_text`。原判斷為 F／P 者（`body_text` 已有值）重判不重算、`derived_body_text` 為 NULL，但若重判為 N，`effective_body_text` 仍回 NULL（有效完整度為 N 者不提供內文）。

### 2.3 圖片

```text
pending ──成功──▶ downloaded（終態）
pending ──失敗──▶ missing(fail_count=1)
missing ──成功──▶ downloaded
missing ──失敗──▶ missing(fail_count+1) ──fail_count=3──▶ abandoned（排程不再嘗試）
abandoned ──PO 要求重試（--retry-images）──▶ missing(fail_count=0) → 立即嘗試一次
（磁碟滿／時間預算用完：不改狀態、不加 fail_count）
```

### 2.4 每位作者每次執行的結果代碼 `outcome`

| 代碼 | 意義 | 計為失敗？ | 告警 |
|---|---|---|---|
| `ok_200` | 取得並處理 | 否（歸零） | 無 |
| `not_modified` | 304 | 否（歸零） | 無 |
| `skipped_interval` | 落在最小間隔內（未請求） | 不增不減 | 無（FR-004） |
| `blocked_403`／`rate_limited_429` | 站方擋下 | 是 | **一律立即**（FR-032）；告警文字附空間現況（FR-028） |
| `challenge_html` | 回應不是 feed（HTML 挑戰頁等），視同被擋 | 是 | 一律立即 |
| `timeout`／`network`／`http_<其他>`／`parse_error`／`too_large`／`redirect_refused`／`robots_disallow`／`robots_unavailable` | 其他失敗 | 是 | 依 `alert_policy` |

## 3. 驗證規則

| 規則 | 對應 |
|---|---|
| `completeness ∈ {P,F,N}`；`classify_reason` 以 `uncertain:` 開頭者 `completeness` 必為 `P` | FR-010、FR-012 |
| 不得以長度判斷 P：P 只能來自 `read_more_tail` 或 `uncertain:*` | FR-012 |
| `guid`（非 NULL）與 `link_norm` 各自唯一；插入前以「guid=? OR link_norm=?」查重，命中即不寫 | FR-007 |
| 已存文章沒有任何 UPDATE 路徑會改 `title`／`content_html`／`body_text`／`completeness`／`classify_reason` | FR-007（不覆寫） |
| `completeness='N'` ⇒ `body_text IS NULL`（`body_text` 為 NULL 者必為 N；F／P 必非 NULL）；N 類 `content_html` 非空時照存、圖片列照建 | FR-011、Q14 |
| `reclassification.derived_body_text` 只在「文章 `body_text IS NULL` 且 `new_completeness ∈ {F,P}`」時非 NULL；`article_effective.effective_body_text`：有效完整度 N ⇒ NULL | FR-011、FR-033、Q14 |
| 通知文字 `completeness='N'` 時恰含固定提醒句，且不含 `link`／內文；非 N 時不含該句 | FR-035、SC-015 |
| `reclassification` 只有 INSERT（無 UPDATE／DELETE）；`old_completeness` 必等於寫入當下的有效值；`new_completeness ∈ {P,F,N}`，`uncertain:*` 者必為 `P` | FR-033、FR-012 |
| 重判不讀網路、不呼叫模型、不發通知；重判前後 `article` 的所有欄位位元組不變 | FR-033、SC-012 |
| 通知文字只含作者（出版名稱）、標題、完整度（N 類另含 FR-035 固定提醒句）；不含 `link`／`link_norm`／任何網址 | FR-025、FR-027 例外 |
| 圖片下載前主機必須通過白名單（完全相同或子網域）；不通過者不發請求、記 `host_not_allowed`、`fail_count+1` | FR-034、FR-015 |
| 所有寫入經 `transaction()`（`isolation_level=None`、顯式 `BEGIN IMMEDIATE`）；交易外不得有 DML | FR-009（research R8） |
| `status='downloaded'` ⇔ `file_path` 非 NULL 且檔案存在（寫檔在前、更新在後） | FR-009 |
| `fail_count ≤ 3`；`fail_count=3` ⇔ `abandoned` | FR-015 |
| 每作者每次執行 `poll_log.requested=1` 的 feed 請求至多 1 筆 | FR-003 |
| `now - author.last_request_at < min_poll_interval` → 不請求 | FR-004 |
| 文章與其圖片列在同一交易內建立 | FR-009 |
| 唯讀開庫（健檢）不得建檔、不得改變位元組 | FR-029、比照 010 守門 |
| 日誌／`last_error_code`／`poll_log` 不含標題、文章網址、圖片網址 | FR-026 |

## 4. 相容性與遷移

- 新庫，無遷移；日後加欄位比照 `article_store.py:285-309` 的 `PRAGMA table_info`＋`ALTER TABLE ADD COLUMN`，唯讀查詢先查欄位是否存在（舊庫唯讀相容）。
- 回滾：刪除或還原 `substack.db`、`substack_images/`、`substack_config.json` 即回到 011 之前；不涉及 `articles.db`。

## 5. FR → 設計位置對照表

| FR | 設計位置 |
|---|---|
| FR-001 | research R6（只打設定檔中的 `/feed`、無 cookie／登入）；`contracts/config-format.md`（feed_url 驗證只收 `/feed`） |
| FR-002 | research R5；`contracts/config-format.md`、`contracts/cli.md §2`；§1.1 `author` |
| FR-003 | research R6（條件請求、逾時、UA、robots）；§1.1 `etag`、§1.6 |
| FR-004 | §1.1 `last_request_at`、§2.4 `skipped_interval`；設定 `min_poll_interval_minutes`（10～1440，下限 10：`contracts/config-format.md`、`contracts/cli.md §2 set-interval`） |
| FR-005 | §2.4（含 `challenge_html` 視同 403／429）；research R4（不連續重試、告警依策略）、R2（01:00 不重打已執行的排程日） |
| FR-006 | 獨立 `substack.db`；research R1 T-A、R8 |
| FR-007 | §1.2 唯一索引、§3 |
| FR-008 | §1.1 `activated_at`／`window_from`；research R5 追補；`contracts/cli.md §1 --backfill`（追補文章逐篇通知：research R4、`contracts/notifications.md §1`） |
| FR-009 | research R8；§3 |
| FR-010～FR-012 | research R6（Read more 結構、可見文字 ≥200 字門檻、不確定規則）；§1.2 `completeness`／`classify_reason`、§3；**FR-011 的 N 類不存內文**：§1.2 `body_text`（N 恆 NULL）、`article_effective.effective_body_text`、§3 |
| FR-013 | research R7「全文占比提醒」（維持近 7 天平均 ±30 個百分點，PO 暫解讀待確認；用原判斷）；`contracts/health-output.md` |
| FR-014 | research R6（HTML→文字、圖位標記）；§1.3 |
| FR-015 | §2.3；`contracts/cli.md --retry-images`；健檢放棄張數 |
| FR-016 | 不設保留期限；健檢只報占用（`contracts/health-output.md`） |
| FR-017 | research R2（22:00＋01:00 補跑、排程日、23:00～00:59 延後、假時鐘邊界）；R8 鎖；R9 plist 22:00＋01:00；§1.5 `run.schedule_day`／`result`（排程日判斷排除 `deferred`／`already_done`） |
| FR-018 | research R2（補跑不受 05:00～18:00 限制）；無時窗程式碼 |
| FR-019 | `substack_import.py` 不 import `claude_cli_runner`／`article_transcribe`／`subprocess`（靜態測試）；執行期攔截 `subprocess` |
| FR-020 | research R1（確認碼兩段式）、R9（安裝排程須 PO 確認）；不碰鑰匙圈 |
| FR-021 | research R1 T-A／T-B |
| FR-022、FR-023 | research R1（只轉表格圖、選取用有效完整度 §1.2 視圖）；`contracts/cli.md §3`；§1.7 |
| FR-024 | research R1 T-C（含執行期證明）；§1.7 `transcription_trial.claude_calls`（消耗＝呼叫次數）、`image_transcription.text`（直接讀庫驗證） |
| FR-025 | research R4（作者＋標題＋完整度、無連結、追補逐篇、摘要含空間）；§1.2 `notify_*`、§2.2；`contracts/notifications.md §1、§2` |
| FR-026 | research R6「日誌內容」、R7 外洩掃描；§3 |
| FR-027 | plan.md「FR-027 可驗證項」（含 Telegram 通知例外：只含作者、標題、完整度、N 類另含固定提醒句、無連結）；資料只在 gitignore 的 `poc/data/`、無任何 STND／MCP 入口；§3 通知不含網址 |
| FR-028 | `contracts/health-output.md`（每日健檢空間現況、放棄張數）；`contracts/notifications.md §2` 摘要與 §3 告警附空間現況；research R4、R7 |
| FR-029 | research R7（備份、健檢）；R9（回滾、部署）；`rotate_logs` glob |
| FR-030 | research R3 |
| FR-031 | research R1 T-E；plan.md 驗收 |
| FR-032 | research R4；§1.1 `consecutive_failures`、§2.4（`challenge_html` 立即告警）；設定 `alert_policy`；`contracts/notifications.md §3` |
| FR-033（新增） | research R11；§1.2 視圖 `article_effective`、§1.9 `reclassification`（含 `derived_body_text`：N 重判為 F／P 的內文產生）、§2.2b、§3；`contracts/cli.md §1 --reclassify／--reclassify-history` |
| FR-034（新增） | research R6 圖片下載（白名單）；設定 `image_hosts`（`contracts/config-format.md`）；`contracts/cli.md §2 add-image-host／remove-image-host`；§1.3 `host_not_allowed`、§3 |
| FR-035（新增，Q14） | `contracts/notifications.md §1（N 類逐篇提醒）、§2（摘要附提醒）`；§2.2 N 類提醒為一次性（沿用 `notify_status`，無獨立欄位）；§3 通知文字驗證規則；research R4（通知內容） |
