# 🚀 Pre-Spec 需求攝入工作流 (Product Intake Workflow)

**版本：** `v1.0.0`  
**最後更新：** 2026-05-14  
**狀態：** 穩定 (Stable)

---

## 📖 版本紀錄

| 版本 | 日期 | 更新內容 | 負責人 |
| :--- | :--- | :--- | :--- |
| v1.0.0 | 2026-05-13 | 初始版本：建立基於 ADR-0027 的標準化操作指南 | AI Assistant |
| v1.0.1 | 2026-05-14 | 新增完整 Skill 清單章節（15 個 Skills 工作流程說明） | AI Assistant |

---

## 🔧 環境需求 (Prerequisites)

在執行任何 Pre-Spec 指令前，請確認以下工具已就緒：

| 工具 | 用途 |
| :--- | :--- |
| Claude Code CLI | `/prespec` 指令執行環境 |
| Codex Agent | `$prespec` 變數語法的替代執行環境（二擇一） |
| Spec Kit v0.7.3 | Step 3+ 下游管線依賴 |
| Python 3.x | 自動化輔助腳本依賴 |
| Git（`develop` 分支） | 功能分支的整合基底 |

驗證安裝：在 Claude Code 中執行 `/prespec check the current status of <feature-slug>`，確認 skill 回應正常。

---

## 👥 角色分工 (Role Responsibilities)

| 角色 | 管線範圍 | 主要職責 |
| :--- | :--- | :--- |
| **Product Owner (PO)** | Step 0–1 | 收集原始素材、提供業務背景、確認功能 slug、核准 `product-spec.md` |
| **Technical Product Manager (TPM)** | Step 2 | 操作 pre-spec skill、解決釐清問題、審查規格書、執行 handoff 核准 |
| **Research & Development (RD)** | Step 3+ | Spec Kit 接手後負責技術規格、實作計畫與程式碼實作 |

---

## 🛠 如何啟用 (Quick Start)

請遵循以下三個步驟啟動新功能的攝入流程：

### Step 0: 收集原始素材 (Intake Collection)

由 **Product Owner (PO)** 收集所有相關素材，包括：
- 會議記錄、客戶需求描述、Slack/Email 討論摘要。
- 相關截圖、現有流程圖或參考文件。
- 業務背景、優先級與目標時間線。

### Step 1: 初始化工作空間 (Initialization)

> **`feature-slug` 命名規範**：使用 `kebab-case`（全小寫、以連字號分隔），例如 `autocharge-freecharge`。

1. **建立分支**：從 `develop` 分支建立 `function/<feature-slug>` 分支。
2. **建立目錄**：在 `docs/spec-intake/` 下建立功能資料夾，將 Step 0 的所有素材放入 `raw/`。
3. **註冊索引**：在 `docs/spec-intake/index.md` 中新增該功能的追蹤紀錄。

> **註**：為了避免產生大量 TBD 佔位檔案，完整的文件骨架（如 `product-spec.md` 等）將在 `raw/` 目錄放入素材後，於下次執行時自動生成。

初始化完成後，工作空間結構如下：

```
docs/spec-intake/<feature-slug>/
├── raw/                    ← PO 放原始素材
├── intake-index.md         ← 素材來源清單
├── extracted-requirements.md
├── clarification-log.md
├── scope-decision.md
├── product-spec.md         ← 主要交付物
├── supporting-artifacts/   ← 序列圖、API 合約等
└── spec-kit-inputs/        ← Spec Kit 交付包
```

**AI 指令 (AI Command)：**

Claude Code：
```text
/prespec initialize <feature-slug>
PO = <po-name>
TPM = <tpm-name>
```

Codex：
```text
Use $prespec for <feature-slug>: initialize the intake workspace.
PO = <po-name>
TPM = <tpm-name>
```

### Step 2: 需求標準化與釐清 (Normalization & Clarification)

由 **TPM** 協同 PO 執行以下循環：
1. **提取需求** — 將素材轉化為 `extracted-requirements.md`。
2. **釐清缺口** — 在 `clarification-log.md` 中記錄問題並獲得 PO 回答。
3. **界定範圍** — 在 `scope-decision.md` 中明確定義 In-Scope 與 Out-of-Scope。
4. **撰寫規格** — 生成並精煉 `product-spec.md`。
5. **產出輔助文件** — 根據需求複雜度建立 `supporting-artifacts/`（如序列圖、API 合約）。

**AI 指令 (AI Command)：**

Claude Code：
```text
/prespec <feature-slug>: run guided full flow
```

Codex：
```text
Use $prespec for <feature-slug>: run guided full flow.
```

> 當 skill 回報缺口時，提供決策後重新執行相同指令，直至 skill 回報 handoff 就緒。
> (When the skill reports gaps, provide the missing decisions and re-run the same command until handoff readiness is confirmed.)

---

## 🤖 AI Agent 使用說明 (AI Agent Usage)

Guided full flow 是推薦的日常操作指令：自動執行所有安全的 pre-spec 動作，在需要 PO/TPM 決策的關卡停止並說明缺口。

### Claude Code (`/prespec`)

```text
# 初始化工作空間（一次性）
/prespec initialize <feature-slug>
PO = <po-name>
TPM = <tpm-name>

# 執行引導式全流程 — 主要日常指令
/prespec <feature-slug>: run guided full flow

# 查詢當前狀態
/prespec check the current status of <feature-slug>

# 確認 handoff 就緒
/prespec check whether <feature-slug> is ready for Spec Kit handoff
```

### Codex (`$prespec`)

```text
# 初始化工作空間（一次性）
Use $prespec for <feature-slug>: initialize the intake workspace.
PO = <po-name>
TPM = <tpm-name>

# 執行引導式全流程 — 主要日常指令
Use $prespec for <feature-slug>: run guided full flow.

# 查詢當前狀態
Use $prespec to check the current status of <feature-slug>.

# 確認 handoff 就緒
Use $prespec to check whether <feature-slug> is ready for Spec Kit handoff.
```

### CLINE
- **模型：** `GEMMA-4-31B`
- **使用方式：** 使用 `@prespec` Mention 語法（例如：`@prespec <feature-slug>: run guided full flow`）。

完整指令清單請參閱：[Pre-Spec Workflow Runbook](docs/runbooks/pre-spec-workflow.md)

---

## 🛠 本專案完整 Skill 清單 (All Skills Reference)

本專案共包含 **15 個 Skills**，依工作流程順序分為四層：

### 第一層：Pre-Spec 需求前置（Step 0–2）

| Skill | 指令 | 用途 | 主要使用者 |
| :--- | :--- | :--- | :--- |
| **prespec** | `/prespec <feature-slug>: run guided full flow` | 將原始需求資料正規化為 `product-spec.md` 和 Spec Kit 交付包；負責 Step 1–2 全部工作 | TPM / PO |

### 第二層：Spec Kit 核心工作流程（Step 3+）

> 需要 `product-spec.md` 已標記為 `Accepted` 才能開始。依序執行。

| 順序 | Skill | 指令 | 用途 |
| :--- | :--- | :--- | :--- |
| 1 | **speckit-specify** | `/speckit-specify` | 將 `speckit-input.md` 轉換為完整的 `spec.md`（功能規格書） |
| 2 | **speckit-clarify** | `/speckit-clarify` | 找出 `spec.md` 中不夠明確的地方，最多問 5 個問題並更新規格（選用） |
| 3 | **speckit-plan** | `/speckit-plan` | 根據 `spec.md` 產生 `plan.md`（實作設計、架構決策） |
| 4 | **speckit-tasks** | `/speckit-tasks` | 根據 `plan.md` 產生有依賴順序的 `tasks.md`（可執行任務清單） |
| 4+ | **speckit-analyze** | `/speckit-analyze` | 對 `spec.md` / `plan.md` / `tasks.md` 做跨文件一致性分析，不修改檔案（選用） |
| 4+ | **speckit-checklist** | `/speckit-checklist` | 針對當前 feature 產生自定義檢查清單（選用） |
| 5 | **speckit-implement** | `/speckit-implement` | 依照 `tasks.md` 逐一執行實作任務 |
| 5* | **speckit-taskstoissues** | `/speckit-taskstoissues` | 將 `tasks.md` 轉換為 GitHub Issues（`speckit-implement` 的替代方案） |

### 第三層：專案設定

| Skill | 指令 | 用途 |
| :--- | :--- | :--- |
| **speckit-constitution** | `/speckit-constitution` | 建立或更新專案「基本原則」文件，並同步所有相關 templates |

### 第四層：Git 輔助

| Skill | 指令 | 用途 |
| :--- | :--- | :--- |
| **speckit-git-initialize** | `/speckit-git-initialize` | 初始化 Git repo 並建立第一個 commit |
| **speckit-git-feature** | `/speckit-git-feature` | 建立 feature branch（自動遞增編號或 timestamp） |
| **speckit-git-validate** | `/speckit-git-validate` | 驗證當前 branch 名稱是否符合命名規範 |
| **speckit-git-remote** | `/speckit-git-remote` | 偵測 Git remote URL（用於 GitHub 整合） |
| **speckit-git-commit** | `/speckit-git-commit` | Spec Kit 指令完成後自動 commit 所有變更 |

### 完整工作流程圖

```
Step 0-2: Pre-Spec
  /prespec → 產生 product-spec.md (Accepted)
      ↓
Step 3+: Spec Kit
  /speckit-specify  → spec.md
  /speckit-clarify  → spec.md（精煉，選用）
  /speckit-plan     → plan.md
  /speckit-tasks    → tasks.md
  /speckit-analyze  → 分析報告（選用）
  /speckit-implement 或 /speckit-taskstoissues
```

---

## 🚫 系統邊界 (System Boundaries)

Pre-Spec **不執行**以下操作 — 這些由 Spec Kit 或後續流程負責：

- **不建立** `specs/[feature]/spec.md` — 由 `speckit-specify` 負責。
- **不寫入** `.specify/feature.json` — 由 `speckit-specify` 負責。
- **不建立或切換** Spec Kit 工作分支 — 由 Spec Kit 的 `before_specify` hook 負責。
- **絕對禁止擅自將 `product-spec.md` 標記為 `Accepted`** — 必須由 PO/TPM 提供具名核准之證據（如會議記錄或 PR 審核紀錄），AI 不得自行更改此狀態。
- **不放行** `speckit-input.md` 交付 — `handoff-checklist.md` 未全部勾選前不得執行 handoff。

---

## ✅ 啟用完成檢查清單 (Handoff Checklist)

在將需求交付給開發團隊 (RD) 並啟動實作前，**必須**確認以下項目全部勾選：

- [ ] **規格書狀態**：`product-spec.md` 的狀態已標記為 `Accepted`。
- [ ] **核准紀錄**：`product-spec.md` 標頭已包含 PO 與 TPM 的核准姓名及日期。
- [ ] **無阻塞缺口**：`clarification-log.md` 中所有標記為 `Blocking` 的問題已全部解決。
- [ ] **範圍明確**：`scope-decision.md` 已明確定義 MVP 範圍，無模糊地帶。
- [ ] **輔助文件完備**：所有在 `readiness-checks.md` 中定義為 `Required` 的文件已完成並連結。
- [ ] **交付包導出**：已將 `product-spec.md` 拆分為一個或多個 `spec-kit-inputs/*.md` 交付包。
- [ ] **最終確認**：`handoff-checklist.md` 已全部勾選並由 TPM 確認。

> **Step 3+ 接手：** 所有項目完成後，TPM 對每個已接受的 `speckit-input.md` 執行 `speckit-specify`。
> Spec Kit 的 `before_specify` hook 自動建立工作分支，RD 接手後續技術實作。
> (After all items pass, TPM runs `speckit-specify` for each accepted input package. The `before_specify` hook creates the Spec Kit work branch; RD then owns technical implementation.)

---

## ⚠️ 核心原則 (Core Principles)

為了維持需求品質，請嚴格遵守以下邊界：
1. **先規格，後開發**：在 `product-spec.md` 達到 `Accepted` 狀態前，禁止開始撰寫技術設計或實作程式碼。
2. **行為描述 ≠ 實作任務**：`product-spec.md` 應描述「系統應該如何行為」，而非「開發者應該如何實作」。
3. **變更回溯**：若開發過程中發現需求必須變更，請先將 `product-spec.md` 狀態回調至 `In Review`，重新釐清後再次核准。

---

## 📚 延伸閱讀 (Further Reading)

| 文件 | 說明 |
| :--- | :--- |
| [ADR-0027](docs/adr/0027-prespec-workflow.md) | 決策依據、完整角色模型與 skill 邊界定義 |
| [Pre-Spec Runbook](docs/runbooks/pre-spec-workflow.md) | PO/TPM 操作步驟與完整 AI 指令清單 |
| [SKILL.md (Claude Code)](.claude/skills/prespec/SKILL.md) | Claude Code skill 完整參考 |
| [SKILL.md (CLINE)](.cline/skills/prespec/SKILL.md) | CLINE skill 完整參考 |
| [SKILL.md (Codex)](.agents/skills/prespec/SKILL.md) | Codex skill 完整參考 |
