# Spec Kit Input: 旅遊分頁（Travel Diary，唯讀展示層）

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** travel-diary
**Handoff Order:** 2

## Feature Summary

STND 新增「旅遊」分頁：唯讀呈現獨立專案
`/Users/stander/My_project/mytravel/trips/` 既有的行程手記（markdown），
並可連結相簿分頁（見 `photos` package）的相簿，在行程詳情頁嵌入對應
照片縮圖牆。不搬移、不重寫原始檔案，不做結構化編輯表單。

## Actors

- PO（Stander）：STND 單人使用者

## Problem and Goal

PO 已經有一套運作良好的旅行規劃/紀錄工作流（用 Claude 共創、寫成
markdown 手記），但目前沒有地方能一站式瀏覽這些行程並看到對應照片。
目標：提供一個唯讀展示層，讓 PO 能在 STND 裡瀏覽既有行程內容並連結
相簿裡的照片，同時完全不干擾現有的寫作習慣。

## In Scope

- Trip 列表頁：自動掃描 `mytravel/trips/` 資料夾列出行程（標題、日期
  範圍解析自資料夾名稱、封面照取自連結相簿的第一張照片）
- Trip 詳情頁：把該行程的 `itinerary.md` 原文渲染成網頁
  （markdown→HTML），嵌入連結相簿的照片縮圖牆
- Trip↔Album 關聯管理：多對多，可在 Trip 詳情頁或相簿頁任一端手動
  設定連結（依賴 `photos` package 的 `trip_albums` 資料表與相簿功能）

## Out of Scope

- 行程內容的結構化編輯表單（itinerary_items／expenses 等獨立資料表）
- 對 mytravel 原始檔案的任何寫入/修改
- 行程搜尋、跨行程比對等進階功能

## User Scenarios

1. PO 在 `mytravel/trips/` 新增一個資料夾寫好 itinerary.md，STND 旅遊
   列表自動出現這趟新行程，不需要額外註冊
2. PO 打開某趟行程詳情頁，看到完整渲染後的行程表、攝影卡位指南等
   原始內容，底下看到連結相簿的照片縮圖牆
3. PO 在相簿頁把一個橫跨兩趟旅行的主題相簿（如「紅葉主題精選」）
   同時連結到兩趟行程，兩邊的 Trip 詳情頁都能看到這個相簿的照片

## Functional Requirements

對應 product-spec.md FR-063（完整條文見該文件與
`../../supporting-artifacts/2026-09-16-travel-photos-design.md`）。

## Success Criteria

- 新增一個 mytravel trip 資料夾後，不需任何 STND 操作即出現在列表
- Trip 詳情頁渲染的內容與原始 itinerary.md 一致，原始檔案未被修改
- 同一個相簿可同時連結多趟旅行並在各自詳情頁正確顯示

## Constraints and Assumptions

- 依賴 `photos` package（`albums`／`trip_albums` 資料表與相簿功能）
  先完成，開發順序：相簿基礎版先行
- mytravel 路徑固定為 `/Users/stander/My_project/mytravel/trips/`，
  跨機器部署需另行處理路徑設定（非本輪範圍）
- 唯讀，不對 mytravel 做任何寫入

## Source Decisions

clarification-log.md Q-047；product-spec.md FR-063；scope-decision.md；
`../../supporting-artifacts/2026-09-16-travel-photos-design.md`
