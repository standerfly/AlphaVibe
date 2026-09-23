# 原始素材：技術研究筆記（外部引用）

來源類型：本 repo 內既有文件
路徑：`docs/research/2026-09-22-ex-station-4segment-ticket-search.md`（943 行）
產出日期：2026-09-22 ~ 09-23

**刻意不複製內容到 raw/**：該檔案已在版控內且會持續更新，複製會造成
兩份分岔。此處僅登記為素材來源。

## 內容索引（供 pre-spec 取用）

| 節 | 內容 |
|---|---|
| 1–2 | 外站四段票機制、五個價格變數 |
| 3 | 開票鐵律與風險（第1段不可 no-show、商務艙不適用） |
| 3b–3c | PO 提供的兩組真實實例與參數 |
| 4 | 資料源盤點（官方 API 皆不開放、Amadeus 已下線） |
| 5 | 決定性未驗證假設（Google Flights vs Skyscanner 報價） |
| 8 | 零成本查價路徑（tfs protobuf 網址構造，已實測） |
| 12 | robots.txt 查證與節流設定 |
| 14–15 | 軟封鎖形態、串流落地 |
| 17 | 票規：長榮 24 小時轉機限制／星宇可多段中停／促銷艙 validity |
| 18–20 | 封鎖根因（headless 指紋）與速率限制修正 |
| 21 | 成田完整價格清單（22 筆） |

## 已實作的程式（同樣僅登記，不複製）

- `poc/kb-mcp/flight_search.py`（2018 行，97 測試）
- `poc/kb-mcp/scraper/flight_scraper.js`（Node + Playwright）
- `poc/kb-mcp/scraper/track-prices-*`（Google Flights 原生追蹤的 console 腳本）
