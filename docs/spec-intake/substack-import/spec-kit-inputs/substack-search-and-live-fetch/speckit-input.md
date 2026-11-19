# Spec Kit Input: Substack 搜尋整合與即時取得

**Status:** Accepted
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** substack-search-and-live-fetch
**Handoff Order:** 2

> Draft：依賴第 1 包，阻擋 Accept 的項目已清零（Q-102 已答）；尚含不阻擋 Open 項（Q-108、Q-113、Q-118；Q-104 待 PO 審閱確認），product-spec 未 Accepted，不得交給 speckit-specify。

## Feature Summary

讓 claude.ai（台股與美股連接器）與 Mac Claude Code 的既有文章搜尋／讀取同時涵蓋 Substack 文章，結果標示來源與「僅預覽」（來源可信度標示）；並提供通用的「即時取得」寫入工具，PO 看到新文章時可立刻要求立即輪詢一次 RSS 並同步下載圖片，手機 claude.ai 也能用。

## Actors

- PO（Stander）：在對話中搜尋、引用、要求即時取得。
- Claude（Mac Claude Code、claude.ai 連接器）：呼叫搜尋、讀取與即時取得。

## Problem And Goal

排程每日一次，PO 偶爾想在看到文章後馬上能與 Claude 討論；Mac 對話常被封存、手機無法使用，因此需連接器入口。同時搜尋要能一次涵蓋定錨與 Substack 兩類來源。

## In Scope

- `search_articles`／`get_article` 同時查定錨文章與 Substack 文章，結果標示來源（出版名稱）與「僅預覽」。
- 通用即時取得寫入工具：台股與美股連接器都提供且行為逐字相同；Mac Claude Code 亦可觸發。
- 可指定單一作者或全部；與排程共用鎖、去重、資料庫；只認 RSS；feed 未出現回報稍後再試。
- 圖片同步下載，失敗者留給排程補下載；須在連接器逾時內回報進度或分段（Q-118）。
- 同作者最小輪詢間隔守衛：預設 30 分鐘、為可隨時調整的設定（不寫死）（Q-102），任何輪詢（排程或即時）都計入。
- 引用 Substack 作者意見時標明來源與「僅預覽」（FR-029）。
- 新增寫入工具不得破壞 010「文章通道唯讀」守門，須另證（FR-027）。
- 不接受網址參數；只寫 `substack.db`；不進唯讀白名單。
- 守門數字：以合併當下 `function/alphavibe` 實際值為準：011 為台股／美股各 +1、唯讀不變（撰寫時 2026-11-19 實測基準：台股 50、美股 10、唯讀 31，僅為背景資訊）；011 tasks 階段須在合併當下重算；parity 測試僅對該工具例外並新增專屬測試。
- 舊庫（無新欄位）與 `substack.db` 不存在時唯讀查詢相容。

## Out Of Scope

市場（台／美）標籤與依市場隔離搜尋、抓單篇網頁、接受網址、修改 `articles.db`、排程與抓取儲存本身（第 1 包）、文章更新偵測。

## User Scenarios

1. 手機 claude.ai 要求取得某作者最新文章：已出現則存入並回報；未出現回報稍後再試。
2. 間隔內重複要求被拒並說明還需等待多久；排程剛輪詢過同作者亦計入。
3. 即時取得與排程同時：後到者回報忙碌，無重複紀錄。
4. 搜尋某主題：定錨與 Substack 結果並列，各有來源；付費預覽標「僅預覽」。
5. 台股與美股連接器對即時取得工具行為逐字相同。
6. 唯讀白名單不含即時取得工具。

## Functional Requirements

對應 product-spec.md：FR-014、FR-018～FR-025、FR-027～FR-029。重點：
- 圖片同步下載與逾時回報（FR-028）；010 唯讀守門另證（FR-027）；來源可信度標示（FR-029）。
- 工具不收網址、只寫 `substack.db`；回報文字須明確區分（新增 N 篇／無新文章／稍後再試／間隔內被拒／忙碌）。
- 既有 parity、工具數、唯讀白名單測試維持，僅對該工具名稱放寬。
- 011 文章在 `get_article` 的識別方式留到 plan（Q-108）。

## Success Criteria

- 工具數：台股與美股各比合併當下基準 +1、唯讀不變（基準以合併當下實際值為準）。
- 唯讀白名單測試證明不含即時取得工具。
- 兩連接器該工具輸出逐字相同（專屬 parity 測試）。
- 既有定錨文章搜尋結果前後一致。
- 即時取得每次回應都有明確結果類別。

## Constraints And Assumptions

PO 親自確認範圍為登入／鑰匙圈／消耗用量與安裝排程，RSS 輪詢不逐次確認（Q-101 已答）；站方速率上限未知，間隔預設 30 分鐘、可隨時調整，PO 已同意（Q-102 已答）；feed 發文延遲未實測（Q-112）；遠端分支 `origin/claude/substack-article-discussion-8c62eh` 若先合併會使守門基準變動（台 52、唯讀 33），故守門數字用相對敘述（Q-104，待審閱不阻擋）；`~/.claude` stock-researcher 白名單不在 repo，需 PO 在 Mac 同步（SRC-001）。

## Source Decisions

clarification-log.md：Q-012～Q-015、Q-102、Q-119、Q-121 已答；Open（皆不阻擋）：Q-104（待審閱）、Q-108、Q-112、Q-113、Q-118。支援文件：supporting-artifacts/permission-security-note.md、integration-note.md、schedule-and-locks.md。
