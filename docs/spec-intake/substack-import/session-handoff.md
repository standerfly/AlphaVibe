# 011 Substack 匯入：交接備忘（2026-11-25，因對話可能被封存而落檔）

> 這份是「進度快照」，不是需求文件。需求以 `specs/011-substack-fetch-store/spec.md` 為準。

## 在哪裡工作
- **開發用獨立 worktree**：`/Users/stander/My_project/AlphaVibe-011`，分支 `011-substack-fetch-store`。
- 主資料夾 `/Users/stander/My_project/AlphaVibe` 會被其他 session 切到別的分支，**不要用它**，也不要假設它的分支。
- 分支上混有一個無關 commit `283dc3b`（AI 股研究文件，別的 session 提交）。尚未決定是否搬走。

## 進度
- pre-spec 已 Accepted（`docs/spec-intake/substack-import/`）；兩個 speckit-input 已 Accepted。
- Spec Kit：specify／clarify／plan／tasks 已完成並 commit（最後 commit `d268db1`）。**尚無任何程式碼**。
- **未 commit 的工作**（在 worktree）：N 類（非文字）文章決定的套用——spec.md（Q14、FR-011、FR-035、SC-015）、data-model、contracts/notifications、plan、research、quickstart、tasks、raw 決定紀錄追記。獨立驗收進行中，通過後才 commit。
- 尚未推送任何東西到 GitHub。

## 待 PO 確認（不阻擋開工，部署前要有答案）
1. FR-013 全文占比異常門檻：目前暫維持 30 個百分點（PO 原話「內文」語意不明）。
2. Q14 對 N 類的整理者解讀：N 內文不存、不進搜尋；存入時一次性提醒「要不要處理」（僅逐篇通知；PO 2026-11-25 決定摘要不附提醒，spec Q15）。
3. 其餘整理者解讀見 spec.md Clarifications 與 tasks.md「已決定事項」。

## 下一步
1. N 類改動獨立驗收通過 → commit。
2. 進入實作（`speckit-implement`），建議先做 MVP（US2＋US1，只在測試資料目錄驗收，不上線）。
3. 【須 PO 當下確認】才能做的事：對 Substack 的真實請求首跑、消耗訂閱額度的轉寫、安裝排程、正式部署、push／開 PR。

## 規則提醒
- 每階段由全新 agent 獨立驗收；產出者不自驗。
- 日誌／錯誤訊息不得含標題與全文；通知不含連結。
- 只用 Python 3.9 標準庫；測試用獨立資料目錄，不碰正式庫。
