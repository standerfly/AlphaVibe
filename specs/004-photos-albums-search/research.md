# Phase 0 Research: 相簿分頁（Photo Albums & Search）

Technical Context 沒有留下 `NEEDS CLARIFICATION` 項目（pre-spec 階段
已透過 Q-049／Q-050 兩輪澄清定案），本檔案的任務是把「已經定案的產品
決策」轉成具體的技術做法，並記錄取捨。

## §1 縮圖產生與基礎 EXIF 讀取：`sips`，不引入 Pillow

**Decision**：縮圖產生（256px 或類似尺寸的預覽 JPG）與基礎 EXIF 欄位
（camera_model／lens／拍攝日期）讀取，都透過 subprocess 呼叫 macOS
內建的 `sips` 命令列工具，不新增 Pillow 或其他 Python 圖片處理套件。

**Rationale**：
- `app/requirements.txt` 目前刻意只裝 fastapi/uvicorn 兩個套件
  （「刻意只裝用得到的兩個套件，不預先加其他東西」），本功能已經因為
  `exiftool` 新增一個系統層依賴，沒有必要再疊加一個 Python 圖片套件
  做同樣的事
- `sips -Z <size> src.jpg --out thumb.jpg` 可直接產生縮圖；
  `sips -g allxml src.jpg` 或 `sips -g camerModel -g dpiHeight ...`
  可讀出常見 EXIF 欄位，MVP 只處理 JPG，`sips` 對 JPG 的支援穩定
- 這個決策承接自更早的規劃紀錄（`supporting-artifacts/
  2026-08-21-personal-console-expansion.md`「相簿分頁設計」節：
  「縮圖／metadata 改用 macOS 內建 `sips` 指令」），本次沿用不變更

**Alternatives considered**：Pillow（功能更完整，但引入新 Python
依賴，且本功能已有 `exiftool` 一個新系統依賴，不需要疊加第二個）。

## §2 中繼資料讀寫：`exiftool`

**Decision**：標籤（XMP/IPTC keywords）與評分（XMP rating，0-5 剛好
對應 spec.md 的評分範圍）的寫回，以及讀取既有中繼資料，都透過
subprocess 呼叫 `exiftool`。

**Rationale**：
- 業界標準工具，對 JPG 的 XMP/IPTC 讀寫穩定，支援批次操作
- 命令形式（示意）：
  - 寫入標籤（多值）＋評分：
    `exiftool -overwrite_original -XMP:Rating=4 -IPTC:Keywords="夕陽" -IPTC:Keywords="京都" -XMP:Subject="夕陽" -XMP:Subject="京都" photo.jpg`
    （IPTC:Keywords 與 XMP:Subject 都寫，兼顧不同讀取工具的相容性）
  - 讀取：`exiftool -j -Rating -Keywords -Subject -Model -LensModel -DateTimeOriginal photo.jpg`
    （`-j` 輸出 JSON，方便解析）
  - `-overwrite_original`：避免 exiftool 預設保留 `_original` 備份檔
    造成儲存空間浪費與檔案列表混亂（我們自己的 `photos.db` 已經是
    去重與狀態的權威來源，不需要 exiftool 額外的備份機制）
- 已於 Q-050 定案為系統層外部依賴（見 product-spec.md FR-062、
  `supporting-artifacts/2026-09-16-travel-photos-design.md`），此處
  補上具體呼叫方式

**Alternatives considered**：`piexif`／`pyexiv2`（Python 套件，但
`piexif` 對 XMP 支援有限、只處理 EXIF/IPTC 較舊格式；`pyexiv2` 需要
編譯原生程式庫，在僅有 Python 3.9.6 的機器上安裝風險更高，反而比裝一個
單一 Homebrew 套件更麻煩）。

## §3 背景任務機制：FastAPI `BackgroundTasks` ＋ db 狀態輪詢

**Decision**：匯入與中繼資料寫回都用 FastAPI 內建的
`BackgroundTasks`（隨 request 觸發、在回應送出後於同一 process 內
執行），進度與結果寫回 `photos.db`（`photos.metadata_sync_status`／
一個新的匯入批次記錄），前端透過輪詢對應的 GET 端點取得最新狀態，
不引入 Celery/RQ 等額外的訊息佇列或獨立 worker 服務。

**Rationale**：
- `app/routers/` 目前完全沒有背景任務先例可循（既有的「背景刷新」
  是指每天固定時間跑的排程腳本，如 `market_scan`、
  `check_scheduled_jobs`，屬於 cron/launchd 排程，不是「使用者觸發、
  當下就要開始跑」的請求內背景工作）；本功能是後者，`BackgroundTasks`
  是 FastAPI 對這個情境的標準內建解法，零新增依賴
- 單人使用、偶發批次匯入（不是高併發場景），不需要訊息佇列的擴充性；
  引入 Celery/RQ 等於新增一整套需要另外部署與維運的基礎設施，跟本
  專案「功能最小化」的一貫原則（product-spec.md §7 NFR）衝突
- 狀態寫回資料庫（而非只存在記憶體）的好處：即使使用者重新整理頁面
  或關掉瀏覽器，稍後回來查詢時進度/結果仍查得到；也讓「重新同步」
  這個手動重試動作有明確可查的狀態可以操作

**Alternatives considered**：Celery/RQ + Redis（過度工程，單人使用
規模不需要）；plain `threading.Thread`（可行但 `BackgroundTasks` 已經
是 FastAPI 官方建議且用法更簡單，優先選擇框架內建機制）。

## §4 去重雜湊時機：匯入掃描時對來源檔案算一次，永久不重算

**Decision**：`file_hash`（MD5）在「掃描來源資料夾產生去重預覽」這一
步，對**來源檔案**（使用者選的原始資料夾裡的檔案，複製之前）計算一次
並永久保存；之後即使背景任務把檔案複製到目的地、甚至日後 exiftool
把標籤/評分寫回這份複製後的檔案，都**不重新計算** `file_hash`。

**Rationale**：
- 複製動作是逐位元組複製，複製完成的那一刻，目的地檔案與來源檔案
  內容相同，此時的 hash 不論是對來源算還是對剛複製完的目的地算，
  結果一樣——選在「掃描/複製之前」這個時間點算，只是把時機提前到
  使用者還沒等太久就能看到去重預覽
- 之後 exiftool 寫回標籤/評分會改變目的地檔案的位元組，**但 hash
  已經凍結，不會因此改變**——這保證了「PO 電腦裡如果還留著一份沒被
  STND 動過的原始素材」，之後不管重新匯入幾次，都能正確比對回同一個
  `file_hash` 判定為重複並跳過
- 這是 Q-050 已經定案的產品層決策（見
  `supporting-artifacts/2026-09-16-travel-photos-design.md`「四、
  2026-09-17 補充」節「關鍵技術決策」），此處只是把「什麼時候算」的
  具體實作時機釘死，避免未來接手的人以為「重新計算比較保險」而改掉
  這個設計，那樣做反而會讓去重機制整個失效

**Alternatives considered**：對複製完成後的目的地檔案重新計算 hash
（會在未來任何一次 exiftool 寫回之後產生「同一張照片、hash 對不上」
的問題，已被明確排除，見上方 Rationale）。

## §5 本機資料夾瀏覽 UI：伺服器端輕量路徑瀏覽端點

**Decision**：匯入畫面「選資料夾路徑」透過一個伺服器端的輕量端點
（`GET /api/photos/browse-folders?path=`）列出指定路徑下的子資料夾，
供前端畫出一個簡易的資料夾瀏覽器；使用者也可以直接在路徑輸入框貼上
絕對路徑。伺服器端只回傳目錄清單（名稱＋路徑），不回傳檔案內容，且
限制只能瀏覽（不能寫入/刪除）。

**Rationale**：
- STND 跑在 Mac mini 本機，瀏覽器與伺服器是同一台機器，比起真的走
  HTTP multipart 上傳大量原始檔（尤其未來 RAW 檔案很大），伺服器端
  路徑瀏覽/選取的使用體驗更接近「本機應用程式選資料夾」，也是 Q-049
  已經定案的方向（比照 AutoGallery 原型的網頁式選資料夾）
- 唯讀端點，只回傳目錄結構，不執行任何寫入，風險可控

**Alternatives considered**：瀏覽器原生 `<input type="file"
webkitdirectory>`（可行，但拿到的是檔案物件列表需要透過瀏覽器上傳送
出，對大量/大檔案不友善，且無法讓使用者「先選好路徑、之後匯入時系統
直接從磁碟讀」──這與匯入流程「先預覽去重結果再確認」的設計不搭）。
