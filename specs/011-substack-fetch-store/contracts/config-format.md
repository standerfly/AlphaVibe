# Contract: 設定檔格式 `substack_config.json`（011）

位置：`<data_dir>/substack_config.json`（正式＝`poc/data/substack_config.json`，gitignore，不進 repo）。
編碼 UTF-8、JSON 物件。**只經 `substack_config.py` 修改**（見 `cli.md §2`）；排程每次執行讀取並重新驗證。

## 初始內容（`init` 產生）

```json
{
  "version": 1,
  "min_poll_interval_minutes": 30,
  "alert_policy": "every_failure",
  "image_hosts": ["substackcdn.com", "substack-post-media.s3.amazonaws.com"],
  "authors": [
    {"key": "fomosoc", "name": "FOMO研究院電子報", "feed_url": "https://www.fomosoc.com/feed", "enabled": true},
    {"key": "unclestocknotes", "name": "大叔美股筆記", "feed_url": "https://unclestocknotes.substack.com/feed", "enabled": true}
  ]
}
```

FOMO 的 feed 網址以 `raw/2026-11-19-po-decisions-dialogue.md` 第 4 行（出版網域 `www.fomosoc.com`、subdomain `fomosoc`）推得，**首跑確認**；
若 `www` 網域不通，改為 `https://fomosoc.substack.com/feed`（以 `substack_config.py` 修改，不改程式）。

## 欄位與驗證規則（任一不符＝整份不合格；排程整次不發請求並告警）

| 欄位 | 型別 | 必填 | 規則 |
|---|---|---|---|
| `version` | int | 是 | 必須為 `1` |
| `min_poll_interval_minutes` | int | 是 | 10～1440（FR-004 可調；**下限 10 分鐘為 PO 決定 B6**，小於 10 被拒絕） |
| `alert_policy` | string | 是 | `every_failure`（初期，預設）或 `consecutive_3`（FR-032） |
| `image_hosts` | string[] | 是 | 0～20 個；**圖片下載白名單**（FR-034，PO 決定 B5）：初始＝`substackcdn.com`、`substack-post-media.s3.amazonaws.com`；小寫主機名、不得含路徑／埠／IP；比對規則＝完全相同或為其子網域。各作者 feed 主機自動視為允許。不在白名單的圖 **不發請求**、記缺圖（`host_not_allowed`）；PO 在對話中增修（`add-image-host`／`remove-image-host`） |
| `authors` | object[] | 是 | 1～20 位；`key` 不得重複、`feed_url` 不得重複 |
| `authors[].key` | string | 是 | `^[a-z0-9][a-z0-9-]{1,39}$`；日誌唯一使用的作者識別；建立後不可改 |
| `authors[].name` | string | 是 | 1～60 字；通知與報告的顯示名稱（出版名稱） |
| `authors[].feed_url` | string | 是 | `https://`、無帳密、無埠、無 query／fragment、路徑必須恰為 `/feed`、主機不得為 IP／`localhost`；`/feed/private` 等一律拒絕（FR-001） |
| `authors[].enabled` | bool | 是 | false＝不輪詢，已存文章保留（FR-002） |

- 不允許未列出的欄位（防止拼錯的設定被默默忽略）。
- 沒有任何隱性預設值：檔案不存在 → 排程拒絕並告警「設定檔不存在」（請 Claude 執行 `init`）。

## 修改情境對照（PO 在對話中說 → Claude 執行）

| PO 說 | 指令 |
|---|---|
| 「追蹤 XXX」 | `add --key <代號> --name "<出版名稱>" --feed-url https://<host>/feed`（Claude 先查出版名稱與網域，回報 PO 確認後再加） |
| 「先不要追 XXX」 | `disable <代號>` |
| 「XXX 再開回來」 | `enable <代號>`（下次執行重新套用「啟用當天往前 14 天」） |
| 「最小間隔改成 60 分鐘」 | `set-interval 60` |
| 「改成連續 3 次才通知」 | `set-alert-policy consecutive_3` |
| 「圖片主機 XXX 也允許下載」 | `add-image-host <主機>`（Claude 先確認該主機是圖片 CDN 並回報 PO；之後該主機的缺圖可用 `--retry-images` 重試） |
| 「不要再從 XXX 下載圖片」 | `remove-image-host <主機>` |
| 「最小間隔改成 5 分鐘」 | 拒絕（下限 10 分鐘）；Claude 說明並提供 ≥10 的選項 |
