# Workflow And States: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import

```mermaid
flowchart TD
    A[排程觸發 不定時] --> B{登入狀態有效?}
    B -- 否 --> C[鑰匙圈取帳密 登入]
    C -- 失敗 --> X[中止 + Telegram 通知]
    C -- 成功 --> D
    B -- 是 --> D[讀三類清單 台股/美股/週報]
    D --> E[過濾置頂公告 + 已匯入文章ID]
    E --> F{待抓清單為空?}
    F -- 是 --> Z[結束]
    F -- 否 --> G[取本批上限N篇 逐篇抓全文+圖]
    G -- 被擋/逾時 --> Y[中止 退避 + 通知]
    G -- 成功 --> H[寫入 去重 累加分類標籤]
    H --> I{批次上限到?}
    I -- 否 --> G
    I -- 是 --> Z
```

## 文章狀態

| 狀態 | 意義 | 轉換 |
|------|------|------|
| discovered | 清單看到、尚未抓 | → fetched／failed |
| fetched | 全文已存 | 終態（內容更新另議） |
| failed | 抓取失敗，待重試 | → fetched |
| skipped | 置頂公告 | 終態 |
