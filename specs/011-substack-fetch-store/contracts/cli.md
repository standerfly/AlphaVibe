# Contract: 命令列介面（011，第 1 包）

共通規則（三支程式皆同）：
- 直譯器 `/usr/bin/python3`（3.9.6）、只用標準庫；從任何目錄執行皆可（腳本自行把 `poc/kb-mcp/` 放進 `sys.path`）。
- `--data-dir` **必填**、最先檢查：`article_data_guard.resolve_data_dir()`；realpath 指向正式 `poc/data` 時須 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，
  否則拒絕（exit 2），在讀設定、開庫、發任何請求之前。
- stdout／stderr 只含：作者代號、內部 id、HTTP 狀態、結果代碼、計數、時間、空間數字。**不含**標題、內文、文章網址、圖片網址、token。
- 退出碼：`0` 完成（含無新文章）｜`1` 有作者失敗（其餘照常完成；**圖片下載失敗不算，仍 exit `0`，缺圖數顯示在輸出與摘要**，見 spec US3-AS2）｜`2` 參數／資料目錄／設定檔拒絕｜`3` 忙碌（鎖被占用，未寫庫）｜
  `4` 中止（磁碟寫入失敗）｜`5` 手動轉寫因使用量上限／登入失效／登入方式不符而中止。（20 分鐘牆鐘預算強制中止 `aborted_budget`：exit `1`，見 research R2。）

---

## 1. `poc/kb-mcp/substack_import.py`（排程進入點＋手動操作）

```text
substack_import.py --data-dir DIR [--scheduled] [--dry-run]
substack_import.py --data-dir DIR --backfill AUTHOR_KEY
substack_import.py --data-dir DIR --retry-images IMAGE_IDS
substack_import.py --data-dir DIR --reclassify (--article-ids IDS | --author AUTHOR_KEY) [--dry-run]
substack_import.py --data-dir DIR --reclassify-history ARTICLE_IDS
substack_import.py --data-dir DIR --status
```

| 選項 | 行為 | 網路 | 寫庫 |
|---|---|---|---|
| （無動作選項） | 手動執行一次完整流程（同排程，但不做排程日判斷；作者在最小間隔內 → 跳過並印出還需等待幾分鐘） | 是 | 是 |
| `--scheduled` | launchd 專用：先做排程日判斷（本排程日已執行過 → `already_done`；啟動於 23:00～00:59 → `deferred`），再執行完整流程；在間隔內的作者跳過、不告警 | 是 | 是 |
| `--dry-run` | 驗證設定檔、列出各作者「會請求／會因間隔跳過／停用」與原因、缺圖待補張數；**零網路、不寫庫**（唯讀開庫；庫不存在不建） | 否 | 否 |
| `--backfill KEY` | 手動追補單一作者（research R5）：守最小間隔與鎖、不帶 ETag、忽略 14 天窗、去重後存入；**作者已停用或不存在 → 拒絕並 exit `2`**（零網路、不寫庫） | 是 | 是 |
| `--retry-images IDS` | 逗號分隔 image_id；只接受 `abandoned`／`missing` 狀態；重設 `fail_count=0` 後立即嘗試下載一次 | 是（只打圖片主機） | 是 |
| `--reclassify` | **PO 要求重新判斷完整度（FR-033，research R11）**：`--article-ids` 逗號分隔內部 id，或 `--author` 作者代號（該作者全部已存文章）；取執行鎖；只讀 `article.content_html`，用目前的分類規則重判；每篇在 `reclassification` 新增一列（結果相同也記）；**原判斷與原始內容不改**；零網路、零模型、不發通知。`--dry-run`：只列「會改變」的 id 與新舊類別，不寫庫。stdout：檢查篇數、未變篇數、改變篇數（例 P→F ×2），不含標題。找不到的 id 明列錯誤、不靜默略過，且整體 **exit `1`**（存在的 id 仍照常重判；全部不存在也 exit `1`、不寫任何重判列） | 否 | 是（`--dry-run` 否） |
| `--reclassify-history` | 唯讀：列出指定文章的原判斷與全部重判紀錄（時間、前後類別、依據、規則版本），不含標題 | 否 | 否 |
| `--status` | 唯讀摘要（作者狀態、篇數 P/F/N〔有效完整度，並註明被重判過的篇數〕、圖片四種狀態張數、未通知篇數、最近 5 次執行） | 否 | 否 |

完整流程順序（每步失敗的處置見 data-model §2.4）：
1. guard → 讀設定檔並驗證（不合格：固定告警＋exit 2）→ 取鎖（失敗：印「忙碌」＋exit 3）。
2. 開庫（建表）→ 寫一列 `run` → 依設定檔同步 `author`（記錄首次／重新啟用的 `activated_at`）。
3. 補發先前未成功的通知（節流 1.5 秒）。
4. 逐位啟用作者（作者間隔 5 秒）：最小間隔判斷 → robots（快取）→ feed 條件請求 → 解析 → 去重 → 14 天窗 → 分類 → 每篇一交易寫入。
5. 下載本次新文章的圖片，再補下載 `pending`／`missing`（受 20 分鐘**牆鐘**預算：圖片階段 18 分鐘到即強制中止、整體 20 分鐘到即中止並釋放鎖，research R2）；圖片主機不在白名單者不發請求、記缺圖（FR-034）。
6. 逐篇通知（節流 1.5 秒；內容＝作者＋標題＋完整度，**無連結**；N 類另附 FR-035 固定提醒句、不存內文；追補文章亦逐篇）→ 告警（固定文字，附空間現況）→ 有新文章／告警／漏文提示時發 1 則摘要（含空間現況）。
7. 寫完 `run` → 釋放鎖。

圖片下載失敗不影響 `run.result`（仍 `ok`）與退出碼（exit `0`）；缺圖數印在 `images:` 行與摘要。guid 與 link_norm 各命中不同兩篇的 `dedupe_conflict` 計數只印在 stdout／日誌、不入庫。

stdout 範例（排程，有新文章）：
```text
[2026-11-20 22:00:03] substack run#12 trigger=schedule day=2026-11-20
  fomosoc: 200 items=20 new=2 window_skip=0 (P=2 F=0 N=0)
  unclestocknotes: 304
  images: downloaded=5 missing=1 abandoned_now=0 budget_exhausted=0
  notify: sent=3 failed=0 (articles=2 summary=1)
[2026-11-20 22:00:41] done result=ok duration=38s
```

`--backfill` 結果範例：
```text
backfill fomosoc: feed_items=20 already=14 stored=6 oldest_in_feed=2026-06-30
  提示：早於 2026-06-30 的文章 feed 已不提供，無法取得（不會改抓其他來源）。
```

## 2. `poc/kb-mcp/substack_config.py`（追蹤清單與設定，供 Claude 在對話中代 PO 操作）

```text
substack_config.py --data-dir DIR init
substack_config.py --data-dir DIR show
substack_config.py --data-dir DIR validate
substack_config.py --data-dir DIR add --key KEY --name NAME --feed-url URL
substack_config.py --data-dir DIR enable KEY
substack_config.py --data-dir DIR disable KEY
substack_config.py --data-dir DIR set-interval MINUTES
substack_config.py --data-dir DIR set-alert-policy every_failure|consecutive_3
substack_config.py --data-dir DIR add-image-host HOST
substack_config.py --data-dir DIR remove-image-host HOST
```

- `init`：設定檔不存在時建立初始內容（FOMO研究院電子報、大叔美股筆記，見 `config-format.md`）；已存在 → 拒絕（exit 2），不覆寫。
- 所有寫入子命令：載入 → 修改 → **完整驗證** → 舊檔複製為 `substack_config.json.bak-YYYYmmdd-HHMMSS`（保留最新 10 份）→ 暫存檔＋`os.replace`。
  驗證失敗不寫、印出原因、exit 2。
- 不提供刪除作者（停用即可，已存文章保留，FR-002）。
- `set-interval MINUTES`：只接受 10～1440；小於 10 → 拒絕（exit 2，印出「下限為 10 分鐘」），不寫檔（FR-004）。
- `add-image-host`／`remove-image-host`：增修圖片主機白名單（FR-034）；主機須為小寫網域名（不含路徑／埠／IP）；移除不存在者拒絕；各作者 feed 主機是自動允許項、不列在 `image_hosts`，不能被移除。
- `show` 輸出設定全文（設定檔不含任何秘密）；`validate` 只印 OK 或原因。
- 改動在**下一次執行**生效；不需部署、不需重啟（設定檔在資料目錄，正式與開發共用同一份）。

## 3. `poc/kb-mcp/substack_transcribe.py`（手動少量轉寫試跑；FR-022～FR-024）

```text
substack_transcribe.py --data-dir DIR --plan [--per-author N | --article-ids IDS]
substack_transcribe.py --data-dir DIR --run --confirm CODE [--per-author N | --article-ids IDS]
                       [--reader1-model sonnet] [--verifier-model opus] [--claude-bin PATH] [--timeout-sec S]
substack_transcribe.py --data-dir DIR --report [--trial-id ID]
```

- `--plan`：零網路、零模型呼叫、唯讀開庫。輸出每篇的內部 id、作者代號、發布日、已下載圖數；總圖數；預估 `claude -p` 呼叫次數（圖數×2）；
  **確認碼**（選中 image_id 清單＋當日日期的 6 碼雜湊）。不符合 FR-023 的作者明列「無符合條件文章」。
- `--run`：必須帶與當下 `--plan` 相同的確認碼；以下任一成立即拒絕（exit 2）且零模型呼叫：確認碼不符、跨日、選取結果不符 FR-023、
  環境變數 `XPC_SERVICE_NAME` **以 `com.alphavibe.` 開頭**（＝由本專案的 launchd 排程啟動；**不以「是否設有 XPC_SERVICE_NAME」判斷**（注意：「launchd 啟動時 XPC_SERVICE_NAME 等於 plist Label」為**未實測假設**，上線前須以 launchd 實跑一次確認；此變數會被子行程繼承，由常駐服務 reportserver 開出的行程〔例如管家 Remote Control 的 claude〕也可能帶 `com.alphavibe.` 前綴而被誤拒——此為次防線，主防線是確認碼，誤拒時改由 Mac 終端機手動執行。），因 Terminal／VS Code 開出的行程常帶其他非空值，會誤拒手動轉寫；research R1 T-D）、未取得執行鎖（exit 3）。
  通過後：`check_flags`／`check_auth`（非 claude.ai 訂閱即中止）→ 每張圖 reader-1 → 驗證者 → 寫 `image_transcription` → 撞限立即停止（exit 5）。
- 被拒絕的 `--run`（確認碼不符、跨日、選取不符、`XPC_SERVICE_NAME` 以 `com.alphavibe.` 開頭、未取得鎖）**不寫 `transcription_trial` 紀錄**，只回退出碼與訊息。
- `--report`：唯讀列出試跑紀錄（篇數、成敗、呼叫次數、結果代碼）。
- `--per-author N`：1～3，預設 1。`--article-ids`：每篇須為 F 類（以**有效完整度**判斷，含重判結果）且有已下載圖、每作者 1～3 篇。
- 只轉寫表格圖：沿用 010 提示詞，非表格圖記 `is_table=0`（「非表格」）、不產生文字（FR-022）。「消耗」＝`claude_calls`（呼叫次數）與圖數，取不到額度百分比（FR-024）。
- 本程式不提供 `--enable`、不讀鑰匙圈、不安裝任何排程；`ops/launchd/` 不得出現引用它的 plist（測試守門）。
