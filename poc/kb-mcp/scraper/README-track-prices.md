# Google Flights 價格追蹤：用法與限制

## 重要限制（2026-09-23 實測）

**Google Flights 的價格追蹤不支援「多城市」行程**，四段票頁面上沒有
追蹤按鈕。對照實驗（兩者皆未登入）：

| 頁面 | `button[role="switch"]` 含「追蹤」 |
|---|---|
| 來回票（TPE↔PRG） | 1 個（aria-label「追蹤從臺北市飛往布拉格…的票價」） |
| 四段票（NRT-TPE-PRG-TPE-NRT） | **0 個** |

網路上有文章聲稱 Google 的價格提醒已延伸到 multi-city，**實測不成立**。

## 能做什麼

追蹤**主行程**（台北↔目的地來回）的價格，當作四段票的代理指標——
主行程落在旺季時整張四段票都會被拉高（見研究筆記第 2 節），所以主行程
降價時四段票值得重查。四段票本身的追蹤要用 STND 機票分頁（自建）。

## 用法

1. 登入 Google 帳號（追蹤結果會寄到該帳號的 email）
2. 開啟**來回票**查詢頁（不是四段票頁）
3. 執行 `track-prices-console.js`：瀏覽器按 F12 → Console → 貼上 → Enter
   （或把 `track-prices-bookmarklet.txt` 的內容存成書籤，在頁面上點一下）

腳本會找出 `button[role="switch"]` 中 aria-label 含「追蹤」的那一個並
點擊，已在追蹤中則只提示、不重複點。找不到按鈕時會明確告知原因
（通常就是開在四段票頁面上）。

## 為什麼不用 jsname 選擇器

實測看到的按鈕是 `jsname="G7J12e"`，但那是 Google 的混淆識別碼，
改版即失效。改用 `role="switch"` ＋ aria-label 語意比對，穩定得多。
