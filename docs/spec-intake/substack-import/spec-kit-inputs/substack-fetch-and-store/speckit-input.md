# Spec Kit Input: Substack 文章抓取與儲存

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** substack-fetch-and-store
**Handoff Order:** 1

> Draft：尚含 Open 項（Q-103、Q-107、Q-111、Q-115、Q-117），不得交給 speckit-specify。

## Feature Summary

每日 22:00 自動從 PO 追蹤的 Substack 作者的公開 RSS 取得新文章，存入獨立的 `substack.db`（含免費全文、付費預覽標記、圖片與圖位標記；缺圖由排程補下載），有新文章時發 Telegram 通知，並在健檢中回報硬碟空間現況。排程不呼叫模型、不登入、不繞付費牆，不改動 010 的 `articles.db`。另須能對少數幾篇文章手動跑一次圖片轉寫以驗證流程（手動、不排程）。

## Actors

- PO（Stander）：追蹤作者；親自確認安裝排程與任何登入／鑰匙圈／消耗用量動作（含手動轉寫）。
- Claude：依 PO 對話修改追蹤清單設定檔。
- 排程：每日 22:00 無人值守執行。

## Problem And Goal

PO 追蹤的作者有新文章時，需要自動存到 Mac 供 claude.ai 對話搜尋引用，且不消耗模型額度、不另造平行系統。

## In Scope

- 設定檔追蹤清單（初始：FOMO研究院電子報、大叔美股筆記），對話中新增／停用。
- RSS 唯一來源；條件請求、逾時、通用識別、遵守 robots.txt；403／429 停手告警。
- 獨立 `substack.db`；guid／URL 去重；首次只收 14 天內。
- 免費全文；付費僅預覽並標記「僅預覽」。
- 圖片下載、不自動分析、保留圖位標記（含圖說／alt）；下載失敗的圖由排程補下載。
- 手動轉寫少數幾篇文章（限手動、不排程、須 PO 當下確認、不改 010 行為；實作路徑待 Q-115）。
- 每日 22:00；05:00～18:00 只約束消耗 AI agent token 的工作，RSS 抓取與 22:00 排程不受限；011 專屬鎖。
- 會消耗 token 的排程間隔過短時提醒 PO（健檢／通知，不自動改排程；數值待 Q-117）。
- Telegram 通知含作者＋標題；日誌與錯誤訊息不含標題；外洩掃描。
- 空間現況回報（剩餘空間、`substack.db` 與圖片目錄占用量），不設閾值。
- 011 文章不進 010 排程轉寫流水線（有測試）；排程不呼叫模型。
- 備份／健檢／日誌輪替／回滾（納入範圍待 Q-111）。

## Out Of Scope

Gmail 通知信、登入／cookie／繞付費牆、抓單篇網頁、改動 `articles.db`、排程階段模型呼叫、自動轉發、市場標籤、空間閾值、全量歷史回補、排程化（自動）圖片轉寫、即時取得工具與搜尋整合（屬第 2 包）。

## User Scenarios

1. 首次執行只存前 14 天內約 25 篇，再跑一次數量不變。
2. 22:00 有新文章：存入並通知（作者＋標題）；日誌不含標題。
3. 付費文章：存預覽並標「僅預覽」。
4. feed 403／429：該作者停手告警，其他作者照常。
5. 圖片下載失敗：文章照存，圖記缺圖，下次排程補下載。
6b. 手動轉寫：PO 當下親自確認後對少數幾篇文章跑一次，010 不受影響。
6c. token 排程間隔過短：健檢／通知提醒 PO，不自動改排程。
6. 對話中新增或停用作者後，下次執行生效。
7. 010 不受影響：`articles.db` 前後不變、010 既有測試全過。

## Functional Requirements

對應 product-spec.md：FR-001～FR-017、FR-025（定錨查詢不變）、FR-026、FR-030（token 排程間隔提醒）。重點：
- FR-010 手動少量轉寫：不寫死實作路徑，規格階段判定並證明 010 不變（Q-115）。
- 去重與重跑安全；單作者／單篇失敗互不影響；不留半寫入紀錄。
- 付費判斷依分類別的內文尾端模式，不使用「拿不準就填某值」規則；抽樣驗證待 Q-103。
- 時窗：05:00～18:00 只約束消耗 token 的工作（FR-011）。

## Success Criteria

- 重複執行文章數不變。
- 011 文章進入 010 排程轉寫流水線 0 筆；排程模型呼叫 0 次；手動轉寫可對少數幾篇成功一次且 010 不變。
- 日誌／錯誤訊息通過外洩掃描（無標題、帳密、cookie、token）。
- 010 既有測試全過、`articles.db` 前後無差異。
- 健檢輸出含空間現況且無異常判定。

## Constraints And Assumptions

macOS Mac mini、python3 3.9.6 標準庫、launchd、`AlphaVibe-prod` 部署；RSS 每 feed 固定 20 篇；付費文章僅預覽且無機器可讀旗標；站方限速未公布；ToS 灰色地帶由 PO 承擔（Q-107）；PO 親自確認範圍為登入／鑰匙圈／消耗用量與安裝排程，RSS 輪詢不逐次確認（Q-101 已答）；子行程環境白名單含 USER 與 LOGNAME；路徑以 realpath 比對。

## Source Decisions

clarification-log.md：Q-001～Q-011、Q-101、Q-106、Q-119～Q-121 已答；Open：Q-103、Q-105、Q-107、Q-109、Q-110、Q-111、Q-114、Q-115、Q-116、Q-117。追加決定來源：raw/2026-11-19-po-decisions-dialogue.md「追加決定」節。範圍見 scope-decision.md；支援文件見 supporting-artifacts/（整合、錯誤矩陣、安全、資料模型、排程與鎖、流程與狀態模型）。
