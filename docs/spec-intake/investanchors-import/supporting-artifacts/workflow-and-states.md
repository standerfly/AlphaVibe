# Workflow And States: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import

```mermaid
flowchart TD
    A[排程觸發] --> M{Gmail 有定錨新信?\n或每週核對日?\n或回補未完成?}
    M -- 否 --> Z
    M -- 是 --> C[鑰匙圈取帳密 登入]
    C -- 失敗 --> X[中止 + Telegram 通知]
    C -- 成功 --> D[讀總覽清單或通知信連結 不分類]
    D --> E[過濾置頂公告 + 已匯入文章ID]
    E --> F{待抓清單為空?}
    F -- 是 --> Z[結束]
    F -- 否 --> G[取本批上限N篇 逐篇抓全文+圖]
    G -- 被擋/逾時 --> Y[中止 退避 + 通知]
    G -- 單篇失敗 --> R[記失敗次數 留待下次排程]
    R --> I
    G -- 成功 --> H[寫入 去重 + 存圖 + 表格圖轉寫]
    H --> I{批次上限到?}
    I -- 否 --> G
    I -- 是 --> L[登出 + 新文章 Telegram 通知]
    L --> Z
```

## 文章狀態

| 狀態 | 意義 | 轉換 |
|------|------|------|
| discovered | 清單看到、尚未抓 | → fetched／failed |
| fetched | 全文已存 | 終態（內容更新另議） |
| failed | 抓取失敗，待下次排程重試（同次不重試） | → fetched／abandoned |
| abandoned | 累計失敗達上限，停止自動重試並已通知 | PO 處理後手動重置 |
| skipped | 置頂公告 | 終態 |
