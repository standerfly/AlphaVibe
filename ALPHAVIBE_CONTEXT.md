# AlphaVibe — 專案對話上下文

> 此文件用於在 claude.ai Projects 上維持跨 session 的對話連續性。
> 最後更新：2026-05-16

---

## 專案身份

- **專案名稱：** AlphaVibe
- **PO / TPM：** Stander
- **目前階段：** Pre-Spec（需求釐清中）
- **目前狀態：** `Draft` — 大部分需求尚待討論

---

## 核心目標

AlphaVibe 是一個**投資資訊儀表板系統（Investment Information Dashboard）**，核心目標：

1. 讓使用者能高效收集與建立投資相關資料
2. 讓使用者在單一系統中高效獲取所需的投資資訊
3. 透過 AI Agent 整理資料，給出可信且可靠的報告與建議

---

## 目標使用者

| 角色 | 目標 |
|---|---|
| 投資者（Investor） | 獲取所需的投資資訊以輔助決策（涵蓋不同經驗程度） |

---

## 目前已知的開放問題（全數 TBD）

以下項目尚未定義，是主要討論方向：

- **業務背景與優先級** — 為什麼現在做？對業務影響為何？
- **目標上線時間** — 預計 launch 時間點
- **MVP 範圍** — 哪些功能在 MVP 內，哪些 out of scope，哪些 defer
- **功能需求（FR）** — 系統應該做什麼（可測試的需求條目）
- **使用情境** — Happy path / Exception path
- **成功標準** — 如何衡量這個功能做成了
- **限制條件與假設** — 技術或業務上的約束
- **依賴項** — 需要哪些外部系統或團隊

---

## 已有的文件結構

```
docs/spec-intake/alphavibe/
├── raw/
│   └── src-001-product-brief.md   ← 唯一有實質內容的文件
├── product-spec.md                 ← 骨架，待填寫
├── extracted-requirements.md       ← 待提取
├── clarification-log.md            ← 待問答
├── scope-decision.md               ← 待決定
└── intake-index.md
```

---

## 對話指引（給 Claude）

這個專案正在 **Pre-Spec 階段**，意思是產品需求尚未確定，我（Stander）在與 Claude 討論以下事項：

- 釐清 MVP 範圍與功能需求
- 討論系統設計方向（AI Agent 架構、資料收集方式等）
- 決定優先級與上線策略

請根據上述背景協助我思考、提問、決策。如有不清楚的地方，請直接問我。

---

## 關鍵決策（待累積）

> 每次對話有重要決策時，請提醒我把結論補充到這裡。

| 日期 | 主題 | 決策內容 |
|---|---|---|
| （待新增） | | |
