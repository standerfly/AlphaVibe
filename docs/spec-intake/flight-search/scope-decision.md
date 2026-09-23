# Scope Decision: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
**Last Updated:** 2026-09-23

## MVP In Scope

1. STND 新增「機票」分頁（`app/routers/flights.py` ＋ `web/src/pages/Flights.jsx`）
2. 追蹤條件的建立、列出、刪除（目的地／外站多選／出發區間／行程天數／
   第1段提前策略／目標價／重掃頻率）
3. 外站四段票掃描：日期抽樣、按價格排序、接駁票估價並計入總成本
4. 第1段間隔策略：含「自動避開指定月份」（為每個主行程日期各自挑間隔）
5. 分頁開啟直接顯示已存結果；可手動觸發單一條件重掃
6. 背景掃描：速率守衛、跨時段分批、進度與排隊狀態顯示
7. 達標通知：最低價跌破目標價時以 Telegram 推播（複用既有推播基礎設施）
8. 每筆結果提供外部查價連結（四段票、接駁票）
9. UI 提示關鍵票規風險（第1段不可 no-show；僅經濟艙有意義）
10. Google Flights 原生追蹤的操作入口（主行程來回票，含 console 腳本說明）

## Out Of Scope

- **訂票與付款**：本系統只查價與比價，不介入訂票流程
- **多使用者與權限**：單人個人系統，無角色分層、無分享功能
- **拆票自組（各段分開購買）**：與四段票是不同機制，價格邏輯不同
- **Skyscanner／Trip.com 等站台的程式化抓取**：robots.txt 明確禁止
  （CON-03），僅可產生連結供人點閱
- **付費 API 訂閱**：SerpApi 路徑保留但需使用者自備 key（CON-01）
- **四段票的 Google Flights 原生追蹤**：該功能不支援多城市（CON-04）
- **商務艙查詢**：多城市查詢會跳艙翻倍，無實用價值（CON-06）

## Deferred Or Later

- 價格趨勢圖與歷史走勢分析（Q-018 建議記錄資料但 MVP 不做視覺化）
- 自動判斷「現在該買了嗎」的建議邏輯
- 多目的地同時比較（例如布拉格 vs 維也納哪個便宜）
- 外站接駁票與四段票的組合最佳化（目前接駁票僅估價，不參與組合搜尋）
- 票規自動檢核（例如自動判斷該航空是否允許此間隔）——目前僅以文字提示
- 重掃失敗的通知策略（Q-020，MVP 僅 UI 標示過期）

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| flight-scan-page | 分頁骨架、追蹤條件 CRUD、四段票掃描與結果顯示、手動觸發、速率守衛與分批、外部連結、票規提示 | 既有 `poc/kb-mcp/flight_search.py` 與 `scraper/`（已完成，97 測試） | 1 | Draft |
| flight-price-tracking | 定期自動重掃排程、達標判定、Telegram 推播、資料過期標示 | flight-scan-page；既有 Telegram 推播基礎設施 | 2 | Draft |

拆分理由：掃描與顯示是可獨立交付且立即有用的最小單位（PO 已能用 CLI
得到答案，分頁化即是把它變得手機可用）；定期重掃與通知需要排程與推播
整合，風險與相依都不同，分開交付可讓第一部分先上線驗證。

## Cross-Feature Dependencies And Handoff Order

- 兩個 spec feature 皆**不重寫**演算法，直接 import `poc/kb-mcp/flight_search.py`
  的既有函式（比照 `app/` 其他 router 的既有慣例）
- 資料層比照 `us_stock_store.py`／`photo_store.py` 先例：**獨立 store ＋
  獨立 db 檔**，不與投資資料共用
- flight-price-tracking 的排程須與既有 launchd 排程慣例一致
  （`~/Library/LaunchAgents/com.alphavibe.*.plist`）

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 日期為輸出而非輸入 | SRC-001 | Stander | 2026-09-22 | PO 核心痛點是「不想手動逐一輸入日期」 |
| 瀏覽器抓取為主力、付費 API 為備援 | SRC-001 | Stander | 2026-09-23 | 零成本約束；瀏覽器無額度上限且實測比免費 API 快十餘倍 |
| 抽樣掃描取代整月全掃 | SRC-001, SRC-005 | Stander | 2026-09-23 | 速率上限使全掃不可行（3,872 筆 vs 每小時上限） |
| 接駁票計入總成本排序 | SRC-002 | Claude（實測發現）／Stander（接受） | 2026-09-23 | 第1段須自費飛到外站；只按票面價排序會偏袒接駁貴的遠外站 |
| 拆為兩個 spec feature | — | Claude（提案） | 2026-09-23 | 掃描可獨立交付；排程與推播的相依與風險不同 |
| 不做訂票 | SRC-001 | Stander | 2026-09-22 | PO 全程以「查價與比價」描述需求，未提及訂票 |
| 外站與目的地皆為可調設定 | SRC-001 | Stander | 2026-09-23 | 「目前啦」明示偏好會變動 |
