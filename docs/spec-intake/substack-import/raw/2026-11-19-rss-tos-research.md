# Substack 公開 RSS 取得可行性研究（2026-11-19）
標註：[事實]=有來源/實測 [推論] [未知]

## 實測紀錄（共 4 次 GET，UA="Mozilla/5.0 (compatible; personal-feed-reader/0.1)"，無登入無 cookie，間隔數秒）
1. https://substack.com/robots.txt → 200, cache-control public,max-age=86400, ETag 有
2. https://on.substack.com/feed → 200, application/xml; charset=utf-8, ETag W/"c3220-..."(弱), cache-control: no-cache, server cloudflare, cf-cache-status HIT, x-robots-tag noindex,noarchive,nofollow, 約 799KB
3. 同上 + If-None-Match → **304**（ETag 條件請求可用；cache-control no-cache = 每次須重驗證）
4. https://www.noahpinion.blog/feed（自訂網域）→ 200, 同樣標頭風格, ETag, 約 990KB
未測 If-Modified-Since / Last-Modified（回應未見 Last-Modified 標頭）；未測 /feed 的 Atom、未測速率上限（刻意不密集請求）。

## 1. 路徑
- [事實] <名>.substack.com/feed 回 RSS 2.0（實測 #2）；自訂網域同路徑 /feed 可用（實測 #4）。
- [事實] 無 Atom 專用路徑的證據：feed 內僅含 atom:link（rel=self）命名空間，主體是 RSS 2.0（實測 #2 channel 子元素）。是否另有 /feed.atom：[未知]（未測）。
- [事實] 私人 feed /feed/private 與 podcast private 被 robots.txt 禁止（實測 #1）；需登入 token，不在本案範圍。

## 2. 內容
- [事實] 每項含 title, description(約 100–160 字摘要), link, guid(isPermaLink=false), pubDate(RFC822 GMT), enclosure(封面圖), content:encoded（實測 #2）。
- [事實] 條目數：兩個 feed 都剛好 20 筆（實測 #2、#4）；on.substack 最舊項為 2026-06-30，最新 2026-11-12，故 20 是固定上限、非時間窗。→ 只能抓最近 20 篇，歷史回補不能靠 RSS。
- [事實] 免費文章 content:encoded 為全文（單篇 3KB–85KB）。
- 付費文章：[事實-網上描述] 公開 feed 只含標題+預覽，內文換成訂閱提示（https://finder.wprssaggregator.com/rss-feeds/platform/substack 、 https://orangebot.ai/blog/how-to-export-from-substack-to-rss）；付費全文須私人 feed token。[實測 #4 部分驗證] 該 feed 出現 11 個「Read more」、末尾「Subscribe now」按鈕區塊（class=button-wrapper），但我未能確認哪篇是付費，也沒有找到專屬 paywall 標記 class [未知：有無機器可讀的付費旗標]。[推論] 判斷付費需靠內容尾端模式（「Read more」/截斷）或到文章頁，後者超出本案限制。

## 3. 頻率/快取/限速
- [事實] ETag + If-None-Match → 304（實測 #3）。[事實] Cache-Control: no-cache（須重驗證，非「N 秒內別再抓」）。Last-Modified：未見 [未知 If-Modified-Since]。
- [推論] 以 ETag 條件請求每日輪詢數個作者，流量極低（304 幾乎無 body）。
- 速率上限：[未知]，官方未公布。網上僅說大量單 IP 抓數百個 publication 會被擋（https://dev.to/agenthustler/how-to-scrape-substack-newsletters-in-2026-posts-subscriber-counts-and-author-data-1gmp 、 https://frog03-20494.wykr.es/blog/scrape-substack-newsletters-2026）；429→持續 403 的升級描述來自 Feedzy 通用文件，非 Substack 專屬。
- [未知] Substack 官方說明頁 support.substack.com 的 RSS 條目我抓取回 403（WebFetch），故沒能引用官方 RSS 文件原文。

## 4. 條款 / robots / API
- [事實] ToS（https://substack.com/tos ；WebFetch 摘錄）禁止「Crawls, scrapes, or spiders any page, data, or portion of Substack (manual or automated)」與「Copies or stores any significant portion of the content on Substack」。二次整理見 https://conductatlas.com/platform/substack/substack-terms-of-use/prohibition-on-scraping-or-crawling-substack/ ：自動存取僅限「specifically provided」的 API/介面，並要求遵守 robot exclusion。[注意] 我沒逐字取得「僅限 API」那句的原文，是二手轉述。
- [事實] robots.txt（實測 #1）：User-agent:* 只禁 /feed/private、/subscribe、/action/ 等；**/feed 未被禁止**；BLEXBot 全禁。另 feed 回應帶 x-robots-tag: noindex（針對搜尋索引，非抓取禁令）。
- [事實] 有 Developer API ToS：https://substack.com/api-tos （未深讀；是否涵蓋讀取公開文章 [未知]）。
- [推論] RSS 是 Substack 官方對外提供的訂閱介面（/feed 公開、robots 未禁），個人低頻 RSS 輪詢屬 RSS 讀者的標準用途，風險遠低於爬網頁；但 ToS「copies or stores significant portion」字面上對「存全文」仍有灰色地帶。個人自用不散布風險低，是否可接受屬 PO 風險判斷，非法律意見。
- [推論] 與 010（定錨）不同：此處不登入、不繞付費牆，只存免費全文＋付費預覽。

## 5. 通知信格式
- [未知/僅推論] 我沒找到官方文件描述通知信 HTML 結構。常見事實（網上多處經驗，未在本次來源逐一驗證）：寄件者為 <作者>@substack.com 或 no-reply@substack.com，連結多為 substack.com/redirect/<token> 或 email.mg*.substack.com 的追蹤轉址。→ 不建議靠信件取連結；RSS 的 link/guid 為乾淨的 /p/<slug> 永久連結，比通知信穩。

## 6. 反面證據
- [事實-網上回報] 有人回報 Cloudflare 擋 Substack RSS：r/rss「Cloudflare blocking Substack RSS feeds」(https://www.reddit.com/r/rss/comments/1kr860k/ — 我無法抓取 reddit，僅見搜尋結果標題/鏡像連結 pol1.lr.ggtyler.dev)、NewsBlur 論壇 https://forum.newsblur.com/t/trouble-adding-substack-feeds/10174 、https://forum.newsblur.com/t/three-sites-403-error/10110 、OpenRSS https://openrss.org/work/144。細節（時間、頻率、是否已修復）我沒讀到 [未知]。
- [事實-實測] 我以通用 UA、無 JS、低頻請求，2 個不同 feed 都 200，無 challenge。
- [推論] 風險來源是：資料中心 IP、機器味 UA、短時間大量請求。住宅 IP 每日數次、帶 ETag、UA 通用，被擋機率低但非零；程式要處理 403/429（退避、告警、不重試轟炸）。

## 對 011 的建議（推論）
RSS 輪詢可行：每作者每日 1–2 次，帶 If-None-Match；每次只能看到最近 20 篇（歷史需另法）；付費文章只會拿到預覽，須在資料標記「僅預覽」；用 guid 去重；遇 403/429 停手並告警。待 PO 決定項：可接受 ToS 灰色地帶、是否存全文。
