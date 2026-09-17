# Spec Kit Input: 相簿分頁（Photos MVP）

**Status:** Accepted
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** photos
**Handoff Order:** 1

## Feature Summary

STND 新增「相簿」分頁：本機照片的匯入、整理（相簿分類、標籤、評分）、
跨相簿全域搜尋、瀏覽，並將標籤/評分同步寫回照片檔案本身的中繼資料
（XMP/IPTC），使其在 STND 之外的工具中依然可見。MVP 僅處理 JPG；
RAW/X3F 轉檔與自動硬碟分層皆為 Deferred。

## Actors

- PO（Stander）：STND 單人使用者，透過瀏覽器操作（本機或遠端經 ngrok）

## Problem and Goal

PO 有大量本機/外接硬碟上的照片，目前沒有工具能快速依相機型號、鏡頭、
場景描述（日出/夕陽/夜景/街拍）、地點（如京都）等條件搜尋出想找的
照片；標記資訊若只留在單一工具裡，會在照片被複製/分享出去後遺失。
目標：讓 PO 能快速把資訊加到照片上，並能快速、跨相簿地搜尋與瀏覽這些
照片；資訊要跟著照片檔案本身，不被 STND 這個工具鎖住。

## In Scope

- 相簿管理：新建/改名/刪除相簿（標題、描述、封面照）
- 照片匯入：網頁選本機資料夾路徑＋選擇儲存位置（內接/外接硬碟）→
  MD5 file_hash 去重預覽 → 背景任務執行（複製檔案＋產生縮圖＋解析
  EXIF 寫入資料庫）
- 照片整理：批次指派相簿、加標籤（輸入自動帶出既有標籤＋常用標籤
  快速按鈕一鍵套用）、評分（0-5 星）
- 全域搜尋：跨所有相簿，可組合 camera_model／lens（結構化下拉）＋
  標籤（多選）查詢，結果為縮圖牆
- 瀏覽：相簿列表、相簿內縮圖牆（依日期/評分排序、依標籤篩選）、
  單張照片詳情（大圖、EXIF、所屬相簿、標籤、rating）
- 刪除：僅刪資料庫紀錄，不動磁碟原始檔
- 標籤/評分中繼資料同步：db 立即更新後，背景任務呼叫 exiftool 把
  標籤（XMP/IPTC keywords）與評分（XMP rating）寫回照片檔案；資料庫
  永遠是搜尋與真相來源，檔案中繼資料僅單向鏡射
- 同步狀態追蹤：`metadata_sync_status`（synced/pending/failed）＋
  失敗原因記錄；提供手動「重新同步」動作
- 原始檔離線行為：外接硬碟未掛載時，縮圖與資料庫資訊正常瀏覽/搜尋，
  僅「查看原圖/下載」與「同步中繼資料」動作停用/延後

## Out of Scope

- RAW／X3F／Sigma dp 轉檔的混合處理流程
- 自動冷熱儲存分層（原始檔搬移）
- 瀏覽器檔案上傳匯入管道（僅本機路徑選擇）
- 自動偵測外接硬碟重新掛載事件（僅手動「重新同步」）
- 相簿歸屬/旅遊關聯寫入檔案中繼資料（無對應標準欄位，僅存資料庫）

## User Scenarios

1. PO 插上外接硬碟、把一批 JPG 匯入到新相簿，系統提示「87 張新照片、
   13 張重複已跳過」，匯入在背景執行，PO 可以離開畫面
2. PO 幫剛匯入的照片批次加上「夕陽」「京都」標籤，並用快速按鈕加
   「街拍」；隔天用全域搜尋以「相機=Sigma fp L ＋ 標籤=夕陽」找出所有
   符合的照片，跨相簿都找得到
3. PO 把外接硬碟拔掉後仍能瀏覽相簿縮圖與搜尋，只有「查看原圖」跟
   中繼資料同步會顯示待處理狀態；插回硬碟後點「重新同步」補寫
4. PO 用 Lightroom 開啟同一張照片，看到剛剛在 STND 加的標籤與評分

## Functional Requirements

對應 product-spec.md FR-062（完整條文含資料模型、儲存策略、架構、
中繼資料同步設計，見該文件與
`../../supporting-artifacts/2026-09-16-travel-photos-design.md`）。

## Success Criteria

- 匯入 100 張照片可在背景完成，畫面不被卡住
- 全域搜尋在資料庫上執行，外接硬碟離線時搜尋結果不受影響
- 標籤/評分變更後，同一張照片的中繼資料同步狀態可在照片詳情頁查得到
- 重複匯入同一批未經 STND 處理的原始照片，能正確判定為重複並跳過

## Constraints and Assumptions

- 新增系統層外部依賴 `exiftool`（非 Python 套件，經 Homebrew 安裝）
- `file_hash` 只在匯入當下對原始位元組計算一次並永久保存，之後即使
  中繼資料寫回改變檔案位元組也不重新計算（避免破壞去重機制）
- 獨立 `PhotoStore` 類別＋獨立 `poc/data/photos.db`，比照
  `us_stock_store.py`「完全獨立、`__init__` 不掛副作用種子寫入」慣例
- 單人使用，無多用戶權限需求

## Source Decisions

clarification-log.md Q-049、Q-050；product-spec.md FR-062；
scope-decision.md「STND 個人主控台擴建」節；
`../../supporting-artifacts/2026-09-16-travel-photos-design.md`

**Acceptance Evidence**：PO Stander 於 2026-09-17 Claude Code session
明確指示「啟動speckit」，在已完整檢視本 package 拆解自的 FR-062 需求
基線（含全域搜尋、中繼資料同步設計）後確認交接。
