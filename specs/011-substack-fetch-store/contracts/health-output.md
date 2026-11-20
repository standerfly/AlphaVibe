# Contract: 健檢輸出（011 對 `check_scheduled_jobs.py` 的新增項目）

健檢每日 04:00 跑（既有 `com.alphavibe.healthcheck`，帶 `--notify`），輸出為 `(severity, job, detail)`；`ok` 項只進狀態檔
（`~/Library/Logs/alphavibe-health.json`）與 stdout，`warning`／`critical` 在「狀態有變化」時發 Telegram（既有 `should_notify`）。
三個新函式都只**唯讀**開庫（`mode=ro`），庫不存在不建檔；detail 只含數字、代碼、時間、作者代號，不含標題／內文／網址。

## 1. `substack_import`（`check_substack_import(data_dir)`）

| 情況 | severity | detail 範例 |
|---|---|---|
| `substack.db` 不存在 | ok | `尚未建立（找不到 substack.db）` |
| 沒有任何執行紀錄 | ok | `尚未有執行紀錄（排程未安裝？）` |
| 最後一次排程執行超過 3 天前 | warning | `超過 3 天沒有排程執行（最後一次：2026-11-20T22:00:03+08:00）` |
| 有作者連續失敗 ≥ 3 次 | warning | `作者 fomosoc 連續失敗 3 次（最近結果 timeout）` |
| 全文占比與近 7 天平均相差 > 30 個百分點（FR-013） | warning | `提醒：全文占比 80%，近 7 天平均 10%，相差 70 個百分點（超過 30）；只報現況，未改判、未停止匯入` |
| 未通知成功的文章（含已放棄） | warning（僅放棄時）／ok | `有 2 篇文章通知已放棄（累計 3 次失敗）` |
| 最近一次執行因 20 分鐘牆鐘預算中止（`aborted_budget`） | warning | `最近一次執行因超過 20 分鐘預算而中止（run#12），未完成的圖片與通知留待下次` |
| 摘要（**每日永遠輸出一筆**，含空間現況與放棄張數；FR-028） | ok | 見下 |

摘要（FR-028、FR-029、SC-010；**每日健檢必含**空間現況與放棄張數，與有無事件無關）：
```text
上次成功 2026-11-20T22:00:41+08:00（耗時 38 秒，最近 7 次最長 55 秒）；近 7 天請求 14 次：200×6、304×7、失敗×1（timeout×1）、被擋×0、間隔跳過×0；
文章 P 120／F 8／N 3（有效完整度；其中被重判過 2 篇）；圖片 已下載 410、缺圖 3、放棄 1；未通知 0；
全文占比：最近抓取日 0%，近 7 天平均 6%（可比較 7 天）；
空間：剩餘 21.8 GB；substack.db 4.2 MB；substack_images 85.3 MB
```
- 歷史不足 7 天：`全文占比：最近抓取日 50%，可比較天數 3（不足 7 天，不判斷）`。
- 「空間」只報現況，不出現任何判定字眼或閾值（FR-016、FR-028）。
- **SC-010 與提醒並存（PO 決定 #15）**：SC-010 的禁止範圍是「空間項」與整體不下「異常」判定、不設閾值；全文占比（FR-013）與 token 排程間隔（FR-030）的 warning 提醒用**現況措辭**（「提醒：…相差 N 個百分點」「提醒：…間隔 X 分，小於…」），不使用「異常」「不足」「危險」等判定字眼，也不對空間設閾值——兩者因此不矛盾。測試：對輸出做禁字掃描（「異常」「不足」「危險」「超標」「閾值」不得出現），但允許「提醒：」開頭的現況句。
- 每日健檢的空間現況放在 `ok` 摘要項，不觸發通知；**有事件時**的空間現況由摘要通知與告警通知附帶（`notifications.md §2、§3`）。

## 2. `substack_backup`（`check_substack_backup(data_dir, backup_dir)`）

| 情況 | severity | detail |
|---|---|---|
| `substack.db` 不存在 | ok | `尚未建立，略過` |
| 找不到 `substack-*.db.gz` 或最新一份 > 30 小時 | warning | `substack 最新備份是 40 小時前（…）` |
| 圖片鏡像 `.last_sync` 不存在或 > 30 小時 | warning | `substack_images 鏡像最後同步 40 小時前` |
| 正常 | ok | `正常（資料庫 6 小時前，共 30 份；圖片鏡像 6 小時前，412 個檔案）` |

## 3. `token_schedule_gaps`（`check_token_schedule_gaps(data_dir, agents_dir)`；FR-030）

| 情況 | severity | detail |
|---|---|---|
| 登記的 token 排程皆未安裝 | ok | `未安裝任何會消耗 token 的排程` |
| 某排程沒有耗時紀錄 | ok | `com.alphavibe.transcriptionpipeline：無耗時紀錄、無法判斷` |
| 相鄰兩次觸發間隔 < 前者預估耗時＋30 分 | warning | `提醒：com.alphavibe.transcriptionpipeline 23:40 → com.alphavibe.xxx 00:10 間隔 30 分，小於前者預估耗時 52 分＋30 分緩衝；請考慮調整排程（系統不會自動修改）` |
| 正常 | ok | `token 排程 1 個；transcriptionpipeline 23:40 預估耗時 52 分（最近 10 次最長），間隔 1440 分` |

此函式**從不回 critical**，不影響健檢退出碼。
