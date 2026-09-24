# Quickstart: 相簿分頁（Photo Albums & Search）

**Feature**: `specs/004-photos-albums-search/spec.md`

給接手實作或驗收這個功能的人（含未來 session）的快速上手指南。

## 這個功能是什麼

STND 新增「相簿」分頁：本機照片匯入（去重、背景處理）、相簿/標籤/評分
整理、跨相簿全域搜尋（相機型號/鏡頭/標籤組合查詢），並把標籤與評分
單向寫回照片檔案本身的 XMP/IPTC 中繼資料，使其在 STND 之外的工具
（Lightroom、Finder…）依然可見。**與既有 `KBStore`／`USStockStore`
在資料表、查詢管道兩層完全獨立**，不共用任何程式碼或資料表。

## 開發前必讀

1. `specs/004-photos-albums-search/spec.md` — 完整需求（3 個 User
   Story、16 條 FR）
2. `specs/004-photos-albums-search/research.md` — 5 項關鍵技術決策，
   **尤其 §4「file_hash 匯入掃描時算一次、永久不重算」**——這是最容易
   被後來的人「順手修正」壞掉的地方，改之前務必先讀這一節的完整理由
3. `specs/004-photos-albums-search/data-model.md` — 5 張新表的完整
   schema 與 `metadata_sync_status` 狀態轉換圖
4. `specs/004-photos-albums-search/contracts/photos-api.md` — REST
   端點規格（本 repo 第一次用這個格式，此前的 Spec Kit 功能都是 MCP
   tool 格式，因為那些功能本來就是設計給 Claude 對話查詢用；相簿分頁
   純粹是網頁 UI 操作，沒有對話式查詢需求）
5. `docs/spec-intake/alphavibe/spec-kit-inputs/photos/speckit-input.md`
   與 `docs/spec-intake/alphavibe/supporting-artifacts/
   2026-09-16-travel-photos-design.md` — pre-spec 階段的完整決策脈絡
   （含 AutoGallery 原型查證結果、Q-049/Q-050），想知道「為什麼是這樣
   設計」查這裡
6. 已發布的[流程圖與畫面 Demo](https://claude.ai/code/artifact/57660844-0f08-419e-84e7-cec1aba4d1ef)
   （Claude Artifact）——PO 已經看過並確認過的畫面走向，UI 實作時可
   直接參考互動細節（搜尋篩選列、同步狀態卡片等），不需要重新設計

## 部署前置作業：安裝 `exiftool`

本功能新增的唯一系統層依賴。**不是 Python 套件**，不會出現在
`pip install` 裡：

```bash
brew install exiftool
exiftool -ver   # 確認安裝成功，應該印出版本號
```

沒裝這個之前，中繼資料寫回（User Story 3）會失敗；匯入、相簿整理、
搜尋（User Story 1、2）不受影響，因為它們只碰資料庫。

## 本地驗證方式（實作完成後）

比照既有 `poc/kb-mcp/tests/` 與 `app/tests/test_smoke.py` 的模式：

```bash
# 儲存層測試
python3 -m unittest discover -s poc/kb-mcp/tests -p "test_photo*"

# FastAPI router 深度比對測試
ALPHAVIBE_DATA_DIR=<獨立測試庫路徑> .venv/bin/python3 -m app.tests.test_smoke
```

**務必**指定獨立的 `ALPHAVIBE_DATA_DIR`（例如 `poc/data-test/`，已
gitignore），**絕對不要**指向 `poc/data/`（正式庫）——這是本 repo
2026-08-22 資產表污染事故的教訓，見 CLAUDE.md 教訓紀錄。相簿功能會
在同一個資料目錄下新增 `photos.db` 與照片儲存資料夾，測試時這兩者都
要落在獨立測試庫路徑下，不能碰正式庫或正式照片檔案。

## 手動驗收流程（對照 spec.md 的 Acceptance Scenarios）

1. 準備一個含 5-10 張 JPG 的測試資料夾，透過匯入畫面選擇它＋選內接
   儲存位置，確認預覽顯示正確張數，確認後匯入，確認畫面在匯入期間
   仍可操作其他功能
2. 對同一個資料夾**再匯入一次**，確認全部被判定為重複、跳過，資料庫
   裡沒有多出重複的 `photos` 列
3. 把其中幾張分配到同一個新相簿，加上標籤（例如「夕陽」「京都」），
   給評分
4. 用全域搜尋（不進入相簿）以標籤／相機型號組合查詢，確認結果包含
   剛才標記的照片
5. 檢查其中一張照片詳情頁的中繼資料同步狀態，稍等或手動觸發後應變成
   「已同步」；用 `exiftool photo.jpg` 直接檢查該檔案的 `Keywords`／
   `Rating` 欄位，確認真的寫進檔案了
6. 刪除一張照片，確認它從搜尋結果與相簿中消失，但 `storage_path`
   指向的實際檔案在磁碟上依然存在

## 已知的技術待辦／風險

- **（2026-09-18 更新）`sips` EXIF 讀取只驗證過「沒有 EXIF 時正確回
  `None`」這條路徑**——本機測試用的合成 JPG 都沒有相機 EXIF；
  `Model`／`LensModel`／`ISOSpeedRatings` 等鍵名是否精確對應真實相機
  輸出的 `sips -g allxml` 結構，仍待有真實照片時驗證，讀取失敗不會
  中斷匯入（已有防呆設計）
- **（2026-09-18 已解決）exiftool 中文標籤寫入的 charset 陷阱**：
  IPTC 欄位預設會把中文寫成亂碼，且只加 `-charset iptc=UTF8` 還不夠
  跨工具相容，必須另外明確寫入 `-IPTC:CodedCharacterSet=UTF8` 標記，
  完整細節見 `poc/kb-mcp/photo_metadata_sync.py` 檔頭 docstring 與
  `tasks.md`「Implementation Notes（US3 補充）」
- 大量照片（例如一次匯入超過 1000 張）在 `BackgroundTasks` 下的實際
  耗時與 uvicorn worker 資源占用，MVP 階段未實測，若使用情境超出
  「偶發批次匯入」的預期規模，屆時再重新評估要不要換成獨立 worker
  程序（見 research.md §3 Alternatives considered）
