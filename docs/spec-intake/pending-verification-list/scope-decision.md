# Scope Decision: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

**現況：本節等待 PO 決定 clarification-log.md 的 Q-001~Q-005 後才能定案。**
以下先記錄目前已知、不受這些決定影響的邊界；MVP 範圍細節待補。

## MVP In Scope

- 待補（取決於 Q-001~Q-004 的 PO 決定）——但無論選哪個組合，最小共識是：
  能登記一筆帶有「判斷內容＋觸發條件/預期時間點」的待觀察項目，且能查詢
  出「已到期但狀態仍是待驗證」的項目（見 extracted-requirements.md
  FR-C01/FR-C03/FR-C04）。

## Out Of Scope

- 從研究對話自動抽取「待觀察」句型的 NLP/自動化機制——即使 Q-004 選到
  預留擴充空間的選項，這次 pre-spec／後續第一版實作都不包含真正做出
  自動抽取本身，只是設計時不擋死（Source: 001, PO 原文用「未來可能」）。
- 多使用者/角色權限機制——沿用 STND 現有個人單一使用者假設（見
  readiness-checks.md「Permission, role, or approval behavior」列為 N/A）。

## Deferred Or Later

- 主動排程掃描＋通知機制（Q-003 選項C）——即使 PO 選擇這個方向，本身
  規模較大（STND 目前無任何通知基礎設施），可能需要拆成獨立的
  spec-kit-inputs 套件、晚於基本登記/查詢功能交付（待 Q-005 一併決定
  handoff order）。

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| 待定 | 待 Q-001~Q-005 決定後，視範圍大小判斷是否需要拆分（例如「登記與查詢」
  vs「主動排程通知」可能是兩個 handoff 順序不同的 spec-kit-inputs 套件） | — | — | Draft |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| 排除自動抽取本身於 MVP 之外 | 001 | Codex（待 PO 確認） | 2026-08-27 | PO 原文用「未來可能」而非現在就要，且自動抽取涉及 NLP/句型辨識，複雜度與現有 STND「不重寫底層演算法、直接 import poc/kb-mcp」的既有模式不同調，先框在範圍外，待 Q-004 最終確認 |
