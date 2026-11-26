# Phase 1 資料模型：外部內容知識庫

**Feature**: 012-external-content-kb | **Date**: 2026-11-25
資料庫檔：`<data_dir>/external_content.db`（獨立於 alphavibe.db、articles.db、substack.db、us_stocks.db）。
建構子只建表與補欄位，不寫任何資料。所有寫入方法自己開交易（`BEGIN IMMEDIATE`），資料與稽核列同一交易。

## 表 `content`（外部內容，對應 spec Key Entity「外部內容」）

| 欄位 | 型別 | 規則 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 對外使用的內容 ID |
| `source_key` | TEXT NOT NULL UNIQUE | 來源身分（見 contracts/inbox-file-format.md「身分規則」）；FR-010 去重的唯一依據 |
| `source_type` | TEXT NOT NULL | `youtube` \| `podcast` \| `article`（CHECK） |
| `url` | TEXT NOT NULL | 原始連結（PO 提供的原樣，不改寫）；FR-015 必填 |
| `title` | TEXT NOT NULL | 非空 |
| `author` | TEXT NOT NULL | 頻道或作者；非空 |
| `published_on` | TEXT NOT NULL | `YYYY-MM-DD` 格式驗證 |
| `body` | TEXT NOT NULL | 全文；非空白（FR-002「內文為空」不入庫） |
| `body_sha256` | TEXT NOT NULL | 正規化空白後內文的雜湊；非唯一索引（同內容不同來源只警告） |
| `guid` | TEXT NULL | Podcast 發布來源唯一識別（可選） |
| `created_at` | TEXT NOT NULL | 入庫時間（UTC ISO） |
| `updated_at` | TEXT NOT NULL | 最後取代全文時間 |
| `deleted_at` | TEXT NULL | 軟刪除時間；非 NULL 者 `search`／`get` 一律排除。軟刪除時同時把 `source_key` 改為 `<原 key>#deleted-<id>` 以釋放唯一鍵（之後可重新匯入同一來源）；還原只能手動（見 quickstart），第一版不提供還原工具 |

索引：`UNIQUE(source_key)`、`INDEX(body_sha256)`、`INDEX(published_on)`。
不儲存免責標註——標註由輸出層固定附加（FR-003），避免被資料覆蓋或遺漏。

## 表 `summary`（已確認摘要，對應 Key Entity「已確認摘要」）

| 欄位 | 型別 | 規則 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `content_id` | INTEGER NOT NULL | FK → content.id（內容軟刪除時摘要列保留、不再被查詢） |
| `text` | TEXT NOT NULL | 摘要文字（非空） |
| `status` | TEXT NOT NULL | `confirmed` \| `revoked`（撤回後不再被查詢，但保留列供稽核） |
| `confirmed_at` | TEXT NOT NULL | UTC ISO |
| `po_quote` | TEXT NOT NULL | PO 同意的原話（非空；R7） |

一筆內容可有 0..n 則 `confirmed`。草稿從不寫入此表。**修改**（`revise`）＝同一交易內撤回舊則並新增一則（視同重新確認，需新的 `po_quote`），任一步失敗整筆回滾。

## 表 `audit_log`（稽核紀錄，對應 Key Entity「稽核紀錄」；FR-020）

| 欄位 | 型別 | 規則 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `ts` | TEXT NOT NULL | UTC ISO |
| `channel` | TEXT NOT NULL | 入口：`http`（claude.ai／ngrok 經 gateway）｜`stdio`（本機 Claude Code） |
| `action` | TEXT NOT NULL | `import` \| `replace` \| `delete` \| `summary_confirm` \| `summary_revise` \| `summary_revoke` |
| `content_id` | INTEGER NULL | 刪除後仍保留紀錄，故不設 FK |
| `detail` | TEXT NOT NULL | JSON 字串：來源 key、標題、檔名（若有）、PO 原話（摘要時）等；**不放全文** |

只增不改不刪。

## 資料匣檔案（不在資料庫，是檔案系統狀態；Key Entity「資料匣檔案」）

位置 `<data_dir>/inbox/`；已處理搬至 `<data_dir>/inbox/processed/`。狀態不存資料庫，由位置與內容推得：

| 狀態 | 判定 | 轉換 |
|---|---|---|
| 待填寫 | 在 inbox 內、內文為空白 | PO 貼入內文後自然變待處理（無須任何操作） |
| 待處理 | 在 inbox 最上層、內文非空白、副檔名 `.md`／`.txt` | `import_inbox` 成功 → 已處理；失敗 → 維持待處理；重複且 PO 尚未決定 → 維持待處理；重複且內文雜湊相同 → 已處理（`already_processed`） |
| 已處理 | 在 `inbox/processed/` | 入庫成功，或 PO 對重複選擇「放棄」後搬入 |

重複時 PO 選「取代」：以 `on_duplicate=replace` 並**指定 `filenames`** 重呼叫 `import_inbox`，取代全文後該檔搬入 processed；選「放棄」則 `on_duplicate=skip` 並指定 `filenames`。若資料庫已提交但搬檔失敗，檔案留在 inbox，下次匯入因雜湊相同回 `already_processed` 並補搬，不會重複入庫。

## 驗證規則（對應 spec FR）

| 規則 | 對應 |
|---|---|
| 五個必填欄位缺任一／`source_type` 不在三值內／`published_on` 格式錯／區塊無法解析 → 該檔不入庫並指出問題（不影響其他檔） | FR-002 |
| 內文去空白後為空 → 「內文為空」 | FR-002 |
| `url` 無法得出 `source_key`（例：YouTube 連結找不到影片 ID） → 不入庫並說明 | FR-015、Edge |
| `source_key` 已存在 → 不新增；回報既有那筆；等 PO 決定取代／放棄 | FR-010 |
| `body_sha256` 相同但 `source_key` 不同 → 仍入庫並在結果附 `same_body_elsewhere` 警告（`imported` 與 `duplicate` 皆附） | FR-010 |
| 去重判斷在驗內文之前：已存在的來源不驗內文非空；內文雜湊與庫內相同 → `already_processed` | FR-010、FR-004 |
| 單檔入庫：`content`＋`audit_log` 同一交易，失敗整筆回滾 | FR-007 |
| 取代全文：只更新 `body`、`body_sha256`、`updated_at`；`summary` 保留；查詢時若摘要 `confirmed_at` 早於內容 `updated_at`，輸出加註「此摘要確認於全文更新之前」 | FR-010、場景 4 |
| 讀檔只允許 realpath 在 `<data_dir>/inbox/` 內 | FR-019 |

## 關係

```
content 1 ──── 0..n summary          （summary.content_id → content.id；內容為軟刪除，摘要隨之不可被查詢，列保留）
content ·····  audit_log             （以 content_id 邏輯關聯，不設 FK，刪除後紀錄仍在）
```
