# AlphaVibe 專案指南（v1，2026-07-06）

## 這個 repo 是什麼

投資資訊儀表板（Investment Information Dashboard）的**需求工程 repo**，
目前在 pre-spec 階段。**沒有 production code**——`docs/swagger.yaml`、
`docs/docs.go` 是模板殘留，不代表有後端；唯一的可視產出是
`frontend_mockup.html`（純靜態 mockup）。不要假設有可跑的服務或測試。

使用者 Stander 在此專案的角色是 PO/TPM：工作重心是需求釐清、規格文件、
mockup 迭代，不是寫程式。

## 工作流（ADR-0027 兩段式）

1. **Pre-spec（現階段）**：原始素材 → 審閱過的需求基線。用 `/prespec` skill。
   產物在 `docs/spec-intake/<feature-slug>/`：`product-spec.md`、
   `clarification-log.md`、`scope-decision.md` 等。
2. **Spec Kit（下游）**：需求基線 → `specs/` 技術規格與實作。用 `speckit-*` skills。
   pre-spec 階段**不得**建立 `specs/` 下的任何產物。

完整流程說明：`docs/runbooks/pre-spec-workflow.md`；
決策依據：`docs/adr/0027-prespec-workflow.md`。

## 分支規則

- 功能分支：`function/<feature-slug>`（kebab-case），基底鎖定 `develop`（ADR-0027）。
- **已知現況（2026-07-06）**：repo 目前**只有** `function/alphavibe` 分支，
  `develop` 尚未建立。初始化腳本寫死以 develop 為基底，直接跑會失敗——
  遇到新功能要初始化時，先問使用者要補建 `develop` 還是改用 `--no-branch`。
- 初始化腳本完整路徑：`.claude/skills/prespec/scripts/prespec_init.py`
  （不在 repo 根目錄）。不要手動開分支。

## 本 repo 的具體注意事項

- `docs/spec-intake/*/raw/` 下是原始素材（LINE 對話全文、播客筆記、週報），
  單檔可達數十 KB。**不要在主對話直讀**——派 subagent 摘要，
  只回需要的段落與行號（見全域規則 10-model-dispatch.md）。
- `frontend_mockup.html` 約 31KB。要改它時先用 Grep 定位目標區塊再點讀，
  不要整檔讀入。
- skills 有三份拷貝：`.claude/skills/`（Claude Code 用，**source of truth**）、
  `.cline/skills/`（Cline 用）、`.agents/skills/`（Codex 用）。
  **已知現況（2026-07-06）**：前兩份各 15 個 skill，`.agents/skills/` 只有
  10 個（缺全部 5 個 `speckit-git-*`）——三份本來就不齊，不要假設一致。
  修改 skill 時：改 `.claude/skills/`，再同步到另兩份既有的同名 skill；
  要不要把缺的 skill 補進 `.agents/`，問使用者，不要自行決定。
- `ALPHAVIBE_CONTEXT.md` 是手動貼到 claude.ai Projects 用的摘要，
  會過時；與 repo 內文件衝突時，以 `docs/` 下的文件為準。
- 文件一律繁體中文，表格與 kebab-case slug 沿用既有格式。

## 常用查證點

- 功能清單與狀態：`docs/spec-intake/index.md`
- 目前功能的開放問題：`docs/spec-intake/alphavibe/clarification-log.md`
- 範圍決策：`docs/spec-intake/alphavibe/scope-decision.md`

## 教訓紀錄

（依 ~/.claude/rules/40-maintenance.md 的格式在此追加）

- 2026-07-07｜情境：prespec_init.py 用 `Path.write_text(newline=)` 在本機 Python 3.9.6 崩潰（該參數需 ≥3.10）
  ｜教訓：這台機器（含 AI-stock-km-v1 的 .venv）只有 Python 3.9.6，skill 腳本必須保持 3.9 相容
  ｜動作：已用 `open(newline="\n")` 寫法修復 init／sync_index 兩腳本並同步三份拷貝
