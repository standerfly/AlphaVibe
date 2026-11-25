# Implementation Plan: Substack 文章抓取與儲存（第 1 包）

**Branch**: `011-substack-fetch-store` | **Date**: 2026-11-19 | **Spec**: [spec.md](spec.md)
**Input**: `specs/011-substack-fetch-store/spec.md`（已 Clarified；需求基線 `docs/spec-intake/substack-import/`，Accepted 2026-11-19）

## Summary

每天 22:00（Mac 睡眠錯過時 01:00 補跑；同一排程日只實際執行一次，醒來落在 23:00～00:59 者延後交 01:00），Mac 上的 launchd 排程執行一支純標準庫的 Python 程式：讀資料目錄中的追蹤清單設定檔，對每位啟用作者的 Substack **公開 RSS**
發出至多一次條件請求（ETag、逾時、通用 User-Agent、遵守 robots.txt、同作者最小間隔 30 分鐘可調），把新文章逐篇以單一交易存進
**獨立的 `substack.db`**（與 010 的 `articles.db` 完全分開），依內文結尾的固定「Read more」結構把每篇判為 預覽 P／全文 F／非文字 N
（不確定一律 P、不看長度），內文轉純文字並保留圖位標記，圖片下載到 `substack_images/`（失敗記缺圖、之後每次排程補下載、連續 3 次放棄）。
有新文章時每篇（含追補）各發一則 Telegram（作者＋標題＋完整度，**不含文章連結**，節流 1.5 秒；**N 類非文字文章不保存內文，其通知附一次性固定提醒請 PO 決定是否處理**，FR-011／FR-035），失敗下次補發；有新文章、告警或漏文提示時再發 1 則含空間現況的摘要；被擋（403／429）立即告警，其他失敗依 PO 可切換的告警策略。
排程不呼叫任何模型、不登入、不碰鑰匙圈。PO 可在對話中要求對指定文章／作者**重新判斷完整度**（以保存的原始 HTML 重判，原判斷與重判結果皆留紀錄、不覆寫歷史；research R11）。另提供一支**只能手動、須 PO 當下以確認碼確認**的轉寫試跑工具，重用 010 已驗證的
`claude -p` 訂閱呼叫封裝，但結果只寫 `substack.db`。維運面把新庫與圖片納入每日備份（資料庫壓縮備份＋圖片增量鏡像，鏡像有「不刪除、占用翻倍、無完整性驗證」限制，見 research R7）與 04:00 健檢
（上次成功、失敗統計、**每日**空間現況、放棄張數、全文占比提醒、token 排程間隔提醒）。

技術路線完全沿用 010：`poc/kb-mcp/` 下的進入點腳本＋依賴注入（可測）、`article_data_guard` 資料目錄防呆、`investanchors_redact` 遮蔽與外洩斷言、
`notify.send_telegram`、flock 執行鎖、`ops/launchd` plist＋`AlphaVibe-prod` 部署。重用邊界見 research.md R0。

## 工作位置

**工作位置（2026-11-20 起）**：011 在獨立 git worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`）開發與測試。主資料夾 `/Users/stander/My_project/AlphaVibe` 被其他 session 佔用、可能被切到別的分支，**不要假設其分支**，不得碰、不得在那裡切換分支、commit 或推送。正式環境仍是 `/Users/stander/My_project/AlphaVibe-prod`（路徑不變）。換環境或隔一段時間接手：先 `pwd`、`git branch --show-current`（須為 `011-substack-fetch-store`）、`git status`。

## Technical Context

**Language/Version**: Python 3.9.6（`/usr/bin/python3`，這台 Mac 唯一版本；不得用 3.10+ 語法）
**Primary Dependencies**: 僅標準庫——`urllib.request`、`urllib.robotparser`、`xml.etree.ElementTree`、`html.parser`、`email.utils`、`sqlite3`、`fcntl`、`plistlib`、`hashlib`、`json`、`shutil`；
重用專案內 `article_data_guard`、`investanchors_redact`、`notify`；手動轉寫另重用 `claude_cli_runner.ClaudeCli` 與 `transcription_pipeline.prepare_workdir`（只 import、不修改）。**注意**：import `prepare_workdir` 會因 `transcription_pipeline.py:49-56` 的頂層 import 而**間接載入 `article_store` 等模組，但不開庫**；靜態測試 T-A 只管 011 自己的原始碼，因此另有執行期證明 T-C（攔截所有 `sqlite3.connect`／`open`，斷言全程未開啟 `articles.db`，見 research R0／R1）。**不新增任何套件**
**Storage**: 新 `poc/data/substack.db`（SQLite，`check_same_thread=False`、rollback journal）＋`poc/data/substack_images/<article_id>/<seq>.<ext>`＋設定檔 `poc/data/substack_config.json`＋鎖檔 `poc/data/.substack_import.lock`；不建、不讀寫 `articles.db`（健檢除外：既有慣例以唯讀讀 `pipeline_run` 耗時）
**Testing**: `python3 -m unittest discover -s poc/kb-mcp/tests`；新增 `test_substack_*.py`；假 HTTP／假 notifier／假時鐘／假 claude runner；`tempfile` 獨立資料目錄（realpath）；010 全套必須前後皆綠
**Target Platform**: macOS（PO 的 Mac，launchd）；正式環境為 `AlphaVibe-prod` worktree（資料目錄經 symlink 共用）
**Project Type**: 排程 CLI＋兩支手動 CLI（設定、轉寫試跑）；無網頁、無 MCP（第 2 包）
**Performance Goals**: 無吞吐目標；反向目標——每作者每次 ≤1 次 feed 請求、作者間隔 5 秒、圖片間隔 1 秒、通知間隔 1.5 秒；單次執行**牆鐘**預算 20 分鐘，到期**強制中止**並釋放鎖（不是只停開新圖；22:00 啟動最晚約 22:20 結束，不跨入 23:00，也不長時間占鎖擋第 2 包；research R2）
**Constraints**: 排程零模型呼叫；日誌與錯誤不含標題、內文、文章／圖片網址、token；逐篇交易（無半寫入）；只寫 011 自己的檔案；不受 05:00～18:00 時窗限制（FR-018）；排程時段 22:00＋補跑 01:00 皆不在既有排程時段；sqlite3 一律 `isolation_level=None` ＋顯式交易（research R8）
**Scale/Scope**: 1 位使用者、初始 2 位作者（上限 20）；首次約 25 篇；之後每天約 0～3 篇；每 feed 固定 20 條、約 1MB

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` **仍是未填寫的空白模板**（全為 `[PRINCIPLE_n_NAME]` 佔位，2026-11-19 實讀），沒有可評估的原則，
本 gate 無條文可檢查，**不視為通過或失敗**（與 010 plan 相同處置）。改以專案 CLAUDE.md、全域規則與 spec 的硬性要求作為實質 gate：

| 實質 gate（來源） | 設計前評估 | 設計後評估（Phase 1 完成） |
|---|---|---|
| 獨立資料、不污染其他庫（FR-006、CLAUDE.md 美股／010 先例） | 計畫用獨立 `substack.db` | ✅ data-model 全部表在 `substack.db`；research R1 T-A 靜態＋T-B 執行期測試守門 |
| 資料目錄須明確指定、正式需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`（2026-08-22 教訓） | 重用 `article_data_guard` | ✅ 三支 CLI 皆最先檢查（contracts/cli.md 共通規則） |
| 建構子不得有寫資料的副作用（2026-08-22） | — | ✅ `SubstackStore.__init__` 只建表；設定檔 `init` 為明確子命令 |
| 不改 010 行為（FR-021、FR-024、FR-031） | 只 import 010 模組 | ✅ 只修改 `backup_databases.py`／`check_scheduled_jobs.py` 的新增區塊（research R7 逐項評估既有測試影響：無） |
| 秘密不進日誌、不碰鑰匙圈（FR-020、FR-026、009 鑰匙圈教訓） | — | ✅ 不取鑰匙圈；不記 notify 錯誤原文；外洩掃描測試 |
| 排程不耗 token、手動耗 token 須 PO 當下確認（FR-019、FR-020） | — | ✅ 排程模組不 import 任何模型呼叫；轉寫兩段式確認碼、launchd 啟動即拒絕 |
| 驗證不自驗（全域規則 10／20 號） | — | ✅ tasks 階段須排入 fresh agent 驗收（quickstart §4 V1～V16 為驗收清單） |
| Python 3.9、僅標準庫（CLAUDE.md 2026-07-07） | — | ✅ Technical Context |

**結論**：無違規，Complexity Tracking 不需填寫。建議（不阻擋）：PO 另行決定是否以 `/speckit-constitution` 填寫專案原則。

## Project Structure

### Documentation (this feature)

```text
specs/011-substack-fetch-store/
├── spec.md
├── plan.md              # 本檔
├── research.md          # Phase 0：R0 重用邊界＋R1～R10 決策
├── data-model.md        # Phase 1：substack.db 表、狀態轉換、驗證規則、FR→設計對照表（§5）
├── quickstart.md        # Phase 1：接手備忘、測試、驗證對照 V1～V16、上線、回滾
├── contracts/
│   ├── cli.md           # substack_import.py（含 --reclassify）／substack_config.py／substack_transcribe.py
│   ├── config-format.md # substack_config.json
│   ├── notifications.md # Telegram 文字格式
│   └── health-output.md # 健檢輸出
├── checklists/          # 既有
└── tasks.md             # /speckit-tasks 產生（本指令不建立）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── substack_store.py            # 新：SubstackStore（substack.db schema、唯讀開庫、逐篇交易、查詢）
├── substack_config.py           # 新：設定檔載入／驗證（排程共用）＋CLI 子命令（init/show/validate/add/enable/disable/set-*）
├── substack_feed.py             # 新：robots 快取、條件請求、回應判別（200/304/403/429/挑戰頁）、RSS 解析、去重鍵正規化
├── substack_html.py             # 新：HTML→純文字＋圖位標記、Read more 尾端偵測、P/F/N 分類（含 uncertain 規則；可見文字 ≥200 字；`RULE_VERSION`）
├── substack_reclassify.py       # 新：重判（FR-033）：以 content_html 重判、寫 reclassification、有效完整度查詢
├── substack_images.py           # 新：圖片下載（主機白名單、同白名單轉址、20MB、.part＋os.replace、fail_count／abandoned）
├── substack_import.py           # 新：排程／手動進入點（鎖、排程日與延後時窗、牆鐘預算強制中止、通知節流與補發、告警策略、摘要、--reclassify）
├── substack_transcribe.py       # 新：手動轉寫試跑（--plan／--run --confirm／--report；重用 ClaudeCli、prepare_workdir）
├── backup_databases.py          # 改：OPTIONAL_DATABASES 加 "substack.db"；新增 OPTIONAL_DIR_MIRRORS＋mirror_dir()，main() 呼叫
├── check_scheduled_jobs.py      # 改：新增 check_substack_import／check_substack_backup／check_token_schedule_gaps＋TOKEN_JOBS；登記進 CHECKS
└── tests/
    ├── _substack_fixture.py              # 新：假 feed（含 Read more／播放器／嵌入卡片／長文反例）、假 HTTP、假時鐘
    ├── test_substack_config.py           # 新：驗證規則、原子寫入、備份份數、正式目錄防呆
    ├── test_substack_feed.py             # 新：條件請求、304、403/429/挑戰頁、DTD 拒絕、robots 快取、轉址限制
    ├── test_substack_classify.py         # 新：P/F/N 與 uncertain、圖位標記、不以長度判斷
    ├── test_substack_reclassify.py       # 新：重判不覆寫原判斷、歷史累積、零網路零模型、--author 範圍、dry-run
    ├── test_substack_store.py            # 新：去重、交易回滾、唯讀不建檔、建構子無資料副作用
    ├── test_substack_images.py           # 新：缺圖→放棄、重試、磁碟滿中止
    ├── test_substack_import.py           # 新：14 天窗、重新啟用、追補、最小間隔、鎖忙碌、排程日／延後／補跑、時間預算、告警策略、通知節流與補發
    ├── test_substack_transcribe.py       # 新：確認碼、launchd 拒絕、選取規則、撞限停止、紀錄格式
    ├── test_substack_isolation.py        # 新：research R1 T-A～T-D（T-C 含執行期攔截 articles.db、T-D 以 `com.alphavibe.` 前綴判斷）、FR-019 靜態 import 檢查、FR-027 檢查
    ├── test_substack_no_leak.py          # 新：外洩掃描（比照 test_investanchors_no_leak.py）
    ├── test_backup_databases.py          # 改（只新增案例）：substack.db 可選、圖片鏡像增量
    └── test_check_scheduled_jobs.py      # 改（只新增案例）：三個新檢查

ops/launchd/
└── com.alphavibe.substackimport.plist    # 新：22:00＋01:00、--scheduled、alphavibe-substack*.log、無 RunAtLoad

.gitignore                                # 改：加 poc/data-test-substack/
CLAUDE.md                                 # 改：SPECKIT 區塊加 011 計畫引用（本指令）
```

**Structure Decision**: 全部落在既有 `poc/kb-mcp/`（排程與資料工具的既有所在），不新增 FastAPI router、不動 `web/`、不加 MCP 工具（第 2 包）。
模組依「可單獨測試的職責」切成 store／config／feed／html／images／import／transcribe，對應 010 的 store＋進入點＋下載器切法。

## FR-027 可驗證項（spec 要求「規格驗收 MUST 能證明」）

1. 資料檔全部在 `poc/data/`（`.gitignore:10`）→ 測試斷言 `.gitignore` 涵蓋 `poc/data/` 與 `poc/data-test-substack/`。
2. 本包沒有任何對外入口：測試斷言 `app/`、`poc/kb-mcp/server.py`、`server_readonly.py`、`us_stock_mcp_server.py` 不含 `substack` 字樣（第 2 包會有意識地放寬並改測試）。
3. 備份目的地是 PO 本機家目錄（`~/AlphaVibe-backups`），不是對外位置。
4. 唯一離開本機的內容是 PO 自己 Telegram 的「作者＋標題＋完整度」通知（FR-025；N 類另含 FR-035 的固定提醒句）——**不含文章連結、不含內文**；這是 FR-027 明定的例外（PO 決定 A1，2026-11-20）。測試斷言：通知文字不含 `http://`、`https://`，也不含該文章實際的 `link`／`link_norm` 值（不以「link」子字串判斷，以免標題含 LinkedIn 等字樣誤觸發）。

## 已決定（2026-11-20，PO）

PO 原話：「A1 照建議且不加連結、A2 照建議、A3 可要求重判、A4 照建議、FR-013 內文、B 組 B3 改為逐篇通知其餘照建議」。結果已套用到 spec.md（Clarifications Q7～Q13）與本計畫各文件；
原 15 項逐項結果如下（A＝spec 矛盾、B＝計畫新增設計選擇）：

| # | 題目 | 決定（PO，2026-11-20） | 落點 |
|---|---|---|---|
| 1（A1） | FR-027 與 Telegram 通知（含標題）字面衝突 | 照建議：FR-027 列例外——發給 PO 本人、只含作者／標題／完整度；**通知不加文章連結** | spec FR-027、FR-025；`contracts/notifications.md §1`；本檔「FR-027 可驗證項」 |
| 2（FR-013） | 全文占比門檻低文章量下常誤提醒 | PO 原話「內文」（語意不明）→ 暫解讀為**維持現行寫法**（近 7 天平均 ±30 個百分點）；**待 PO 確認**；已知可能常誤提醒（只提醒不處置） | spec FR-013、Assumptions；research R7 |
| 3（A2） | 補跑 01:00＋23:00～00:59 延後 | 採用：每日 22:00，錯過於 01:00 補跑；同排程日只實際執行一次；醒來落 23:00～00:59 延後交 01:00 | spec FR-017；research R2（含假時鐘邊界測試） |
| 4（B1） | F／N「足夠純文字」門檻 | 可見文字 ≥200 字 | spec FR-010；research R6 |
| 5（B2） | HTML 挑戰頁是否視同 403 | 視同 403／429，立即停止並通知 | spec FR-005、FR-032；data-model §2.4 |
| 6（B3） | 追補文章是否逐篇通知 | **改為逐篇通知**（不改發摘要） | spec FR-008、FR-025；research R4、R5 |
| 7（B4） | 摘要通知多發 1 則 | 採用：有新文章、告警或漏文提示時額外發摘要，含空間現況 | spec FR-025、FR-028；`contracts/notifications.md §2` |
| 8 | 通知是否加完整度與連結 | 加完整度；**不加連結**（同 A1） | spec FR-025 |
| 9（B5） | 圖片主機白名單 | 採用：只允許白名單主機；初始由計畫定（`substackcdn.com`、`substack-post-media.s3.amazonaws.com`＋作者 feed 主機）、PO 可在對話中增修 | spec 新 FR-034；`contracts/config-format.md`、`cli.md §2` |
| 10（B6） | 最小輪詢間隔下限 | 下限 10 分鐘 | spec FR-004；`contracts/config-format.md` |
| 11（B7） | 手動轉寫只轉表格圖 | 接受 | spec FR-022；research R1 |
| 12（B8） | 試跑「消耗」只記呼叫次數 | 接受 | spec FR-024；research R1 |
| 13（A3） | 付費判斷重新判斷 | **本包提供**：PO 可要求對指定文章／作者重判；以保存的原始內容、原判斷與重判結果皆留紀錄不覆寫 | spec 新 FR-033；research R11；data-model §1.9／§2.2b；`contracts/cli.md --reclassify` |
| 14（B9） | 預設告警策略 | `every_failure`；Q3 解讀視為已確認 | spec FR-032、Assumptions、Clarifications Q3 |
| 15 | SC-010 與提醒並存 | 照建議：SC-010 改為「不下異常判定、不設閾值」，提醒用現況措辭 | spec SC-010；`contracts/health-output.md` |
| （A4） | FR-028 空間回報範圍 | 照建議：每日健檢回報空間現況；有事件的通知附帶空間現況 | spec FR-028、SC-010；`contracts/notifications.md`、`health-output.md` |

仍待 PO 確認的只有 #2（FR-013 的暫解讀）。上線前（非 tasks 前）要有答案。

驗收指出並已於 2026-11-20 修正的計畫瑕疵：(a) `should_notify` 實際在 `check_scheduled_jobs.py:489`，`notify.py` 只有 `format_health_message`（research R7）；
(b) 間接載入 `article_store` 的執行期證明 T-C（research R0／R1）；(c) T-D 不再用 `XPC_SERVICE_NAME` 是否存在、改用 `com.alphavibe.` 前綴（research R1、`cli.md §3`）；
(d) sqlite3 `isolation_level=None`＋顯式交易＋回滾測試、排程日判斷排除 `deferred`／`already_done` 與假時鐘邊界（research R8、R2）；
(e) 圖片鏡像限制與首跑確認資料磁碟實際剩餘空間（research R7；`/` 顯示 36～38% 是系統卷，資料卷 `/System/Volumes/Data` 當日為 91% 已用、約 20Gi 可用）；
(f) 20 分鐘預算改牆鐘強制中止（research R2）。SC 編號順序（SC-011 在 SC-010 前）已於 spec 修正。

## Complexity Tracking

無 Constitution 違規需說明（constitution 未填寫）。唯一新增的「複雜度」是 01:00 補跑時段與排程日判斷（research R2），理由是 launchd
睡眠補跑可能落在 23:00～00:59，若只延後不補會整天漏跑；更簡單的「只靠醒來補跑」已評估並拒絕。
