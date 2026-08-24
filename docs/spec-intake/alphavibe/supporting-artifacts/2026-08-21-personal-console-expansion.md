# AlphaVibe 個人主控台擴建規劃（2026-08-21）

> 本檔為 Claude Code 規劃 session 結論的 repo 內備份。完整版（架構圖、既有
> 功能遷移清單、資料模型 schema、實作順序、視覺 mockup）在文末的 Claude
> Artifact 外部連結；本檔是內容摘要，供連結失效或忘記存取方式時查閱。
> 對應決策紀錄：`roadmap.md`「Phase 2 正式產品」節 Q-046。

## 背景

現有 ngrok 網址（`chancefully-erosive-lilian.ngrok-free.dev`）背後是
`poc/kb-mcp/report_server.py`。要擴建成有首頁、儀表板、資產、相簿四個
分頁的個人主控台。

## 架構決策

poc/kb-mcp 全面重寫為 **FastAPI + React 輕量前後端分離**（同源部署、單一
process／Docker image，不是完整雙服務分離，不需要重設計 CORS／認證）。
**推翻 Q-034**（local-first，不需服務化架構）**與 Q-045**（先打磨到常用
才談架構升級，非必要不接受月費）。理由：未來功能擴充、維護性、docker 化。

## 既有功能遷移範圍

`/screen`、`/market-scan`、`/dashboard/stocks`、`/dashboard/stock/<code>`、
5 個表單端點（watchlist／trade／laoyutou／tradeledger／holdings-preview）、
`/mcp` 連接器全部遷移。`/report-classic` 停用不遷移。MCP 邏輯完全沿用既有
`mcp_http_gateway.handle_mcp_post()`，只是改由 FastAPI 路由呼叫。

## 資產分頁設計

- **資料模型**：`asset_pockets`（口袋：名稱／目標金額／排序，使用者可
  自訂）＋ `asset_accounts`（帳戶：名稱／類型標籤，使用者可自訂）＋
  `asset_holdings`（口袋 × 帳戶 × 金額 × 更新時間）
- **預設種子資料**：緊急預備金（60萬／銀行TS）、危機加碼緩衝（50萬／
  銀行KT 30萬＋銀行HN 20萬）、核心0050累積（120萬目標／證券HN原有部位＋
  分批投入）、衛星倉位（50萬／證券KT）
- 刪除採封存不做硬刪
- **建倉進度**：10 月 checklist，每格可打勾／取消，打勾時輸入實際投入
  金額（預設4萬可改），寫入指定口袋 × 帳戶
- **情境試算**：起始本金／退休年齡／定期定額／報酬率 → 退休時資產、
  每月可提領金額，伺服器端即時運算不進資料庫。**待驗證**：年金公式尚未
  跟使用者核對精確版本（用範例反推目前有 1~2% 誤差）
- **對帳單匯入**：不內建。更新走同一個 holdings API，之後掛 MCP write
  工具，需要時請 agent 讀對帳單後呼叫該介面

## 相簿分頁設計（MVP 階段暫緩，僅做導覽入口）

- 參考使用者現有 AutoGallery（本機 Tkinter＋SQLite 原型）的資料模型：
  `photos` 表（`file_hash` 去重、路徑、狀態＝預覽版／正式版、rating、
  camera_model、photo_date）＋ `photo_tags` 表（標籤）
- **Sigma dp 相機 X3F 轉 JPG 混合模式**：上傳自動用開源 x3f_tools
  （Kalpanika/x3f，BSD 授權，command line 可呼叫）轉快速預覽 JPG；Sigma
  Photo Pro 官方軟體經查證無法被腳本自動化（無 CLI、無 AppleScript
  dictionary），維持手動轉出正式版，丟進監看資料夾，服務用檔名比對後
  升級預覽版為正式版
- 縮圖／metadata 改用 macOS 內建 `sips` 指令（因零依賴限制不用
  Pillow／piexif）
- **MVP 範圍**：只做導覽列 tab 與空白頁面，不含任何實際功能。等資產
  分頁、既有功能遷移、導覽列都完成，且對 x3f_tools／AutoGallery 細節做
  進一步研究後才開工

## 建議實作順序

1. FastAPI 骨架（app 結構、資料庫連線、Basic Auth middleware）
2. 逐一遷移既有功能（對照遷移清單，每搬一個驗證新舊行為一致，MCP
   邏輯不動可最先驗證）
3. React 前端 App Shell + Nav（四個 tab）
4. 資產分頁全功能
5. 相簿分頁——僅入口
6. Docker 打包（multi-stage）
7.（未來階段）相簿完整功能

## 治理

這段 Claude Code 對話視同 pre-spec，不另外跑正式 `/prespec` 流程，直接
在既有 `poc/kb-mcp/` 目錄動工。

## 完整規劃與 mockup（外部連結，本檔為備份摘要）

- 完整規劃文件（架構圖／遷移清單／schema）：
  https://claude.ai/code/artifact/f6670921-c206-42d3-8198-e9d9f63de05a
- 視覺 mockup（四分頁畫面稿）：
  https://claude.ai/code/artifact/d98f29ae-2eb5-448d-a397-d10976e86dfd
