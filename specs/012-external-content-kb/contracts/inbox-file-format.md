# 契約：資料匣檔案格式與身分規則

**Feature**: 012-external-content-kb | **Date**: 2026-11-25
此格式是**草稿**（spec Assumptions：規劃階段可微調）；若修改，須同步更新 `docs/runbooks/external-content-project-instructions.md` 的 AI Studio prompt 範本。

## 位置

`<data_dir>/inbox/<檔名>.md`；已處理者在 `<data_dir>/inbox/processed/`。
`create_inbox_file` 產生的檔名：`<YYYY-MM-DD>_<安全化標題>_<source_key短雜湊>.md`（只含字母、數字、`-`、`_`、中文；其餘以 `_` 取代；長度上限 80 字）。
PO 自行放入的檔案不限檔名，副檔名須為 `.md` 或 `.txt`。

## 內容結構

```
---
source_type: youtube
url: https://www.youtube.com/watch?v=XXXXXXXXXXX
title: 這集的標題
author: 頻道或作者名稱
date: 2026-11-19
guid:
---

（內文：逐字稿）
```

規則：
- 第一行必須是 `---`；區塊以下一個單獨一行的 `---` 結束；其後全為內文。
- 區塊內每行 `key: value`（冒號後第一個空白之後為值，值可含冒號）；空行與 `#` 開頭註解行忽略。
- 必填鍵：`source_type`、`url`、`title`、`author`、`date`。選填鍵：`guid`（Podcast 發布來源唯一識別）。未知鍵：忽略並在結果中提示。
- `source_type`：`youtube` | `podcast` | `article`（小寫）。
- `date`：`YYYY-MM-DD`。
- 內文去除前後空白後為空 → 「內文為空」。
- 編碼 UTF-8；單檔上限 2,000,000 字元（防呆）。
- `create_inbox_file` 產生的檔案內文為空，故在 PO 貼入前永遠是「待填寫」。
- 內文開頭若又出現第二個 `---` 中繼資料區塊（常見操作錯誤：把 AI Studio 完整檔貼進建好的範本）→ 該檔失敗並提示移除重複區塊。
- Apple Podcasts 身分改取「節目 ID（網址中的 `id<數字>`）＋單集 `i=<數字>`」，不用整條網址（含國家碼與節目名稱）。

## 身分規則（`source_key`）

| 類型 | 規則 | 範例 |
|---|---|---|
| YouTube（**以網址主機判斷，不看 `source_type`**；PO 把含 YouTube 連結的內容標成 `podcast` 也走此規則，`source_type` 與主機不符時只在結果中提示） | `youtube:<11 碼影片 ID>`。主機：精確比對 `youtube.com`、`www.youtube.com`、`m.youtube.com`、`music.youtube.com`、`youtu.be`（不得用子字串或後綴比對，防 `youtube.com.evil.com`）。ID 來自 `watch?v=`、`/shorts/<id>`、`/live/<id>`、`/embed/<id>`、`youtu.be/<id>`。忽略 `si`、`feature`、`t`、`start`、`list`、`utm_*`、`pp`。 | `youtu.be/ABC?si=x&t=30` 與 `youtube.com/watch?v=ABC` → 同一個 `youtube:ABC` |
| Podcast（有 `guid`） | `podcast:guid:<guid 原樣>` | |
| Podcast（無 `guid`） | 一般網址規則；Apple Podcasts（`podcasts.apple.com`）取 `podcast:apple:<節目id>:<單集i>`。 | |
| 一般網址（含文章、無 guid 的 Podcast） | `url:<規則化網址>`：強制 `https`、主機小寫並去 `www.`、去 fragment、去追蹤參數（`utm_*`、`fbclid`、`gclid`、`si`、`ref`）、其餘 query 依鍵排序保留、去尾斜線。 | |

無法得出 `source_key`（如 YouTube 網址找不到 ID、網址不是 http/https）→ 該檔不入庫並說明。

## 結果回報（每檔一行語意）

`import_inbox` 逐檔回報 `status`：`imported`｜`duplicate`（附既有內容 ID 與標題）｜`failed`（附原因：缺欄位清單／格式錯誤／內文為空／連結無效／不可讀或編碼錯誤）｜`already_processed`（重複且內文雜湊與庫內相同，檔案已搬入 processed）｜`replaced`（重複且 PO 指定 `replace`：已取代全文並保留已確認摘要，檔案已搬入 processed）｜`skipped`（重複且 PO 指定 `skip`：不寫入、視為放棄，檔案已搬入 processed）。
`imported` 與 `duplicate` 都另附 `same_body_elsewhere`（全文雜湊相同、但 `source_key` 不同的其他內容 ID／標題，若有）——這是「同內容不同來源只警告不阻擋」（FR-010）的警告欄位。
結果另含 `skipped_unsupported`（副檔名非 `.md`／`.txt` 而被略過的檔名清單）。
