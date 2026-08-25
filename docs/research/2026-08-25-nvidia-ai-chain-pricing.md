# NVIDIA 資料中心 GPU 漲價趨勢研究筆記（2026-08-25 整理）

研究起點：DigiTimes報導
https://www.digitimes.com.tw/tech/dt/n/shwnws.asp?cnlid=1&id=0000766072_IFJLJTK78GIECM1JVIMBK
（標題：「NVIDIA漲價15%牽動AI供應鏈　晶片界：推論ASIC吸引力或攀升」，2026/08/25，作者劉憲杰）

---

## 一、起點新聞（DigiTimes 2026/08/25）逐項摘要

- **產品範圍**：搭載NVIDIA AI晶片的伺服器系統，涵蓋 Grace Blackwell 與新一代 Vera Rubin 平台
- **漲幅**：逾15%
- **生效時間**：2027年初開始出貨機種
- **調價方式**：以整套系統為單位、直接對大型客戶發出調價通知
- **原因（原文引句）**：「主因係記憶體的漲價過於強勁，已經讓所有不分應用的產品，都得透過漲價來減壓。」
- **BOM成本結構變化（原文引句）**：伺服器整櫃BOM中「HBM4與LPDDR5X合計佔比，由Blackwell世代的5%至10%，躍升至25%至30%」；其他元件「PCB上升233%、被動元件的MLCC上升182%、ABF材質封裝載板上升82%」
- **業界反應**：「這次NVIDIA漲價，有一說是讓推論ASIC的吸引力攀升」；但分析師也說「立即的市佔轉換應該還不會太快發生，但一定會進一步刺激記憶體技術的改進與升級」
- 這篇本質上是針對2026/08/22 Bloomberg獨家報導的台灣產業界解讀延伸稿，不是第一手獨家消息

---

## 二、完整時間軸（含世代對照）

| 時間 | 產品世代 | 漲價/定價內容 | 來源 |
|---|---|---|---|
| 2020 | A100（40GB PCIe） | 約$10,000–12,000；80GB版約$15,000–17,000（無官方單一定價，市場報價） | 綜合市場報價網站（IntuitionLabs / aitooldiscovery），**非官方一手數字，僅供量級參考** |
| 2022年3月宣布／Q3出貨 | H100 | NVIDIA未公布官方零售定價（供給極度受限，各AI實驗室搶購）；市場價格落在約$25,000–40,000 | 綜合市場報價（IntuitionLabs），**未查到官方定價文件，屬市場估計** |
| 2023年9月 | H100（日本市場） | 日本NVIDIA官方銷售夥伴將H100目錄價調漲16%，來到約544萬日圓（約$36,300） | 搜尋結果引用「Reuters分析」但未能定位到原始Reuters文章連結，**屬二手轉述，未直接查證原文，信心中等偏低** |
| 2024年中（供給最緊張期） | H100 | 二級市場H100單價一度衝上約$50,000 | 綜合市場報價（IntuitionLabs），同上屬市場估計非官方數字 |
| 2024年中 | H200 | 單顆GPU約$30,000–40,000；8-GPU HGX伺服器約$320,000–420,000 | 綜合市場報價（Mercatus/thepricer等），**非官方一手數字** |
| 2024年3月宣布（GTC） | Blackwell（B200/GB200） | Jensen Huang於CNBC受訪表示每顆GPU「between $30,000 and $40,000」；GB200 Superchip估價$60,000–70,000；GB200 NVL36機櫃平均售價約$1.8M，NVL72約$3M | CNBC引述黃仁勳談話（官方人士公開發言，可信度較高）＋DataCenterDynamics對NVL36/NVL72機櫃報價的產業轉述 |
| 2025年8月起 | GB200（雲端算力租用價） | 雲端on-demand GB200中位數價格從$13.25/hr漲至$16.00/hr，漲幅約21% | 綜合市場報價網站（getdeploying），**反映的是雲端轉售價格而非NVIDIA出廠定價，兩者不可直接等同** |
| **2026年8月22日** | **Grace Blackwell／Vera Rubin平台伺服器系統** | **NVIDIA通知主要大客戶：2027年初起出貨系統價格調漲「逾15%」（many cases）；漲幅依晶片世代與記憶體配置而異** | Bloomberg獨家報導（記者Brody Ford, Ian King），CNBC/Fortune/Yahoo Finance/Seeking Alpha/Tom's Hardware/wccftech/Semafor等媒體跟進轉載，皆註明消息來源為「熟悉內部溝通但要求匿名的人士」 |
| 2026年8月22日（同日） | 同上 | NVIDIA對置評請求「未立即回應」，**未否認報導** | Fortune、Yahoo Finance報導 |
| 2026年8月23日 | 同上 | Semafor跟進報導標題為「Nvidia says it's raising some prices more than 15%」，但內文查證後**仍未找到NVIDIA正式聲明**，全篇仍基於Bloomberg消息來源 | Semafor（記者Lauren Morganbesser），**標題與內文有落差，需注意：這不代表NVIDIA已正式公開承認，媒體標題用語較內文報導的確定性更強，屬轉載時的用語誇大，判定為推論/未證實** |
| 2026年8月24日 | 同上 | 台灣媒體（SETN三立新聞網）報導同一則Bloomberg消息，並補充美光執行長Sanjay Mehrotra說法：「資料中心客戶希望取得的供應量，比美光目前能承諾的數量高出約50%」；點名台灣供應鏈受惠廠商：伺服器組裝（鴻海、廣達、緯創、緯穎）、記憶體（南亞科、華邦電）、模組（威剛） | SETN https://www.setn.com/news/1894407 |
| 2026年8月25日 | 同上 | DigiTimes本篇（研究起點），補充BOM成本結構細節與ASIC替代效應觀點 | 見上方第一節 |

---

## 三、漲價原因分析（事實 vs 推論 標註）

1. **【事實】記憶體成本飆升是官方/媒體一致指向的主因**：Bloomberg原始報導、DigiTimes、SETN三方一致指出DRAM／HBM／LPDDR5X／SOCAMM供應吃緊、價格暴漲，是這波2026年8月漲價的核心敘事。Micron CEO Mehrotra公開說法（客戶需求超出可承諾供應量約50%）為第三方獨立佐證。

2. **【事實】先進封裝CoWoS產能是結構性瓶頸（但非本次漲價新聞直接點名的原因，屬背景脈絡）**：TSMC CoWoS產能預估2026年底達125K wpm、2027年底170K wpm；NVIDIA一家即預訂2026年逾半CoWoS產能（約80–85萬片晶圓），排擠AMD、Broadcom等競爭者。來源：DigiTimes（英文版）https://www.digitimes.com/news/a20260410VL204/ 、 https://www.digitimes.com/news/a20251210PD218/

3. **【事實，來自DigiTimes本篇獨家BOM拆解】記憶體佔整機BOM比重結構性跳升**：從Blackwell世代的5–10%躍升至25–30%，是本次調價「不得不」以整套系統為單位重新定價的直接依據。

4. **【事實但需注意適用範圍】其他非記憶體零組件同樣大漲**：PCB +233%、MLCC +182%、ABF載板 +82%（DigiTimes本篇引用，未附原始統計來源，屬產業人士轉述，未找到TrendForce等機構的獨立對應數字佐證，**信心中等**）。

5. **【推論】漲價亦可能部分反映NVIDIA藉需求強勢時機轉嫁成本、維持毛利率，而非純粹被動承受成本**：分析師Dan Ives評論「NVIDIA別無選擇，只能將部分額外成本轉嫁給客戶」（偏向支持「純轉嫁說」，屬看多論述）；但也有市場評論指出，這波漲價的最大受益者可能是美光等記憶體廠而非NVIDIA本身（Benzinga標題：「Could Micron Be the Real Winner?」），意味著**NVIDIA自身毛利率不必然因此次漲價而擴大**——這點與「NVIDIA藉機囤積超額利潤」的簡化敘事有出入，屬於需要並列呈現的矛盾證據。
   來源：https://www.benzinga.com/markets/prediction-markets/26/08/61380830/nvidia-ai-server-prices-micron

6. **【事實，財報數字提供背景】NVIDIA整體毛利率近年走勢**：FY2025（2024日曆年）Q1/Q2毛利率約74–75%；FY2026（2025日曆年）Q1降至70.6%、Q2 72.4%、Q3 73.4%、Q4回升至75.0%，全年71.1%（GAAP）。毛利率在70–75%區間波動、並非持續攀高，某種程度支持「近期毛利率其實承壓，漲價是彌補成本上升」的敘事，但仍處於半導體業界極高水準。
   來源：NVIDIA Newsroom官方財報 https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026 、MacroTrends https://www.macrotrends.net/stocks/charts/NVDA/nvidia/gross-margin

---

## 四、反面證據／質疑聲音／風險與限制

- **NVIDIA官方從未正面證實這則消息，只是「未否認」**：截至查證時點（2026-08-25），所有報導均基於Bloomberg「知情人士」的匿名消息，NVIDIA官方對媒體置評請求均未回應。這與「NVIDIA正式宣布漲價」是有落差的——嚴謹來說目前仍是「媒體報導的內部溝通」，不是公開聲明或財報揭露事項。

- **分析師對NVIDIA毛利率長期承壓已有既存疑慮**：獨立研究（PitchGrade）給NVIDIA的「AI Margin Pressure Score」評為6/10，認為近期毛利率強勢掩蓋了結構性風險。
  來源：https://pitchgrade.com/research/nvidia-ai-margin-pressure

- **競爭壓力：AMD與客製化ASIC正在侵蝕NVIDIA市占，漲價可能加速這個趨勢**：
  - AMD MI300X系列報價約比NVIDIA同等效能產品低20–30%，2025年Q3已拿下約7%的AI加速器市場。
  - 超大規模業者（Google TPU、Amazon Trainium、Microsoft Maia、Apple自研）自研晶片持續擴大：報導稱NVIDIA資料中心運算市占已從近90%滑落至約75%（2025年底數字），逾50%超大規模業者內部工作負載已跑在自研ASIC上。約40%的NVIDIA營收來自四大超大規模業者，這些業者同時都在建置競品晶片，是比AMD更大的結構性威脅。
  - 起點新聞本身（DigiTimes）也指出這次漲價「讓推論ASIC的吸引力攀升」，但同篇分析師也澄清「立即的市佔轉換應該還不會太快發生」——即使是提出這個論點的文章自己也未過度誇大立即效應。
  來源：siliconanalysts.com AMD vs NVIDIA市占分析、oplexa.com custom ASIC市場分析（此類為產業分析網站，非傳統媒體，數字未逐一查證原始出處，**信心中等，僅供方向參考**）

- **股價反應**：Bloomberg消息見報當日（2026-08-22），NVDA下跌2.91%（$208.48，跌$6.24），可解讀為市場對成本上升侵蝕獲利的疑慮，但也可能混雜當天其他總經因素，**不宜視為單一新聞的純粹因果**。

- **AI資本支出泡沫疑慮，若成真將是比漲價本身更大的下行風險**：2026年超大規模業者（Microsoft/Google/Amazon/Meta）合計資本支出上看逾$600–700B，科技巨頭2026年已發行逾$1000億美元債券融資AI capex，投資人透過CDS（信用違約交換）大舉避險（Oracle五年期CDS較去年9月已翻逾三倍）。若資本支出增速放緩，NVIDIA的漲價能否持續轉嫁、需求是否依然強勁，都存在不確定性。這是**宏觀風險，非直接反駁本次漲價新聞，但是評估漲價「能撐多久」時必須放進脈絡的變數**。
  來源：IEEE ComSoc/Introl/Futurum等產業資本支出彙整報告

- **數字本身存在來源分歧，需並列呈現**：
  - 「逾15%」（Bloomberg／CNBC／Fortune／Yahoo/SETN/DigiTimes多數轉載一致用語）
  - 「最高達17%」（wccftech標題用語：「could soar by as much as 17%」，屬單一媒體對同一份Bloomberg報導的加碼詮釋，未見其他來源附和，**信心較低，僅wccftech一家使用17%這個數字**）
  來源：https://wccftech.com/nvidias-vera-rubin-blackwell-gpu-server-prices-could-soar-by-as-much-as-17-as-memory-prices-bite-say-reports/

---

## 五、未知／查不到的部分（誠實列出）

- H100在2022年GTC發表時是否有官方公布的一手零售定價——查證結果是**沒有**，NVIDIA當時未公布統一MSRP，市場上流通的「$25,000–40,000」都是事後市場估計/經銷商報價，不是NVIDIA官方定價文件。
- 2023年9月日本H100漲價16%的原始一手來源（疑似Reuters或Nikkei）未能定位到確切文章URL，僅有二手引用，**建議若要在正式報告中引用此數字，應標註「未直接查證原文」**。
- DigiTimes本篇提到的「PCB上升233%、MLCC上升182%、ABF載板上升82%」未找到TrendForce或其他獨立機構的對應原始統計佐證，可能是產業人士口頭轉述的估計值，非正式發布數據。
- NVIDIA官方對這次「逾15%」漲價報導，截至查證時點**始終沒有正式聲明或否認**——這件事本身也是「未知」的一部分（不確定NVIDIA最終會不會、或已經用什麼方式正式回應）。

---

## 六、完整來源清單（URL）

1. DigiTimes（研究起點，中文）：https://www.digitimes.com.tw/tech/dt/n/shwnws.asp?cnlid=1&id=0000766072_IFJLJTK78GIECM1JVIMBK
2. Bloomberg（原始獨家）：https://www.bloomberg.com/news/articles/2026-08-22/nvidia-customers-notified-about-ai-related-price-hikes-above-15
3. CNBC：https://www.cnbc.com/2026/08/22/nvidia-customers-reportedly-warned-about-ai-related-price-hikes-.html
4. Fortune：https://fortune.com/2026/08/22/nvidia-customers-ai-related-price-hikes-15-percent-vera-rubin-grace-blackwell-chips/
5. Yahoo Finance（轉載1）：https://finance.yahoo.com/technology/ai/articles/nvidia-raising-ai-server-prices-131547349.html
6. Yahoo Finance（轉載2）：https://finance.yahoo.com/technology/ai/articles/nvidia-customers-notified-ai-related-192053530.html
7. Seeking Alpha：https://seekingalpha.com/news/4636096-nvidia-ai-server-price-hikes
8. Tom's Hardware：https://www.tomshardware.com/pc-components/dram/nvidia-reportedly-warns-biggest-customers-of-15-percent-price-hikes-on-ai-servers
9. wccftech（17%版本）：https://wccftech.com/nvidias-vera-rubin-blackwell-gpu-server-prices-could-soar-by-as-much-as-17-as-memory-prices-bite-say-reports/
10. Semafor：https://www.semafor.com/article/08/23/2026/nvidia-says-its-raising-some-prices-15
11. SETN三立新聞網（台灣供應鏈角度）：https://www.setn.com/news/1894407
12. Benzinga（Dan Ives評論／Micron受益論）：https://www.benzinga.com/markets/prediction-markets/26/08/61380830/nvidia-ai-server-prices-micron
13. Benzinga（TSMC漲價對NVIDIA毛利率影響）：https://www.benzinga.com/markets/tech/26/06/52920523/tsmcs-price-hike-is-bad-for-nvidia-margins-and-potentially-great-for-nvidia-stock
14. NVIDIA官方財報新聞稿（FY2026 Q4）：https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026
15. NVIDIA官方財報新聞稿（FY2025 Q4）：https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025
16. MacroTrends毛利率歷史圖：https://www.macrotrends.net/stocks/charts/NVDA/nvidia/gross-margin
17. DigiTimes英文版（CoWoS產能瓶頸）：https://www.digitimes.com/news/a20260410VL204/packaging-capacity-tsmc-nvidia-demand.html
18. DigiTimes英文版（TSMC擴充CoWoS，NVIDIA吃下逾半產能）：https://www.digitimes.com/news/a20251210PD218/tsmc-cowos-capacity-nvidia-equipment.html
19. PitchGrade（NVIDIA毛利率壓力評分）：https://pitchgrade.com/research/nvidia-ai-margin-pressure
20. siliconanalysts.com（AMD vs NVIDIA市占）：https://siliconanalysts.com/analysis/amd-vs-nvidia-ai-gpu-market-share-2026
21. TechPowerUp（GB200 Superchip定價）：https://www.techpowerup.com/322498/nvidia-blackwell-gb200-superchip-to-cost-up-to-70-000-us-dollars
22. DataCenterDynamics（GB200 NVL36/NVL72機櫃報價）：https://www.datacenterdynamics.com/en/news/nvidia-increases-blackwell-orders-from-tsmc-by-25-percent-18m-gb200-nvl36-server-cabinet-expected-to-account-for-bulk-of-deliveries/
23. 各GPU市場報價彙整站（非官方一手數字，僅供量級參考）：intuitionlabs.ai、jarvislabs.ai、getdeploying.com、mercatus-ai.com、thepricer.org

---

## 七、對台灣供應鏈與投資意義（我的推論，非新聞原文主張，務必標明）

**以下是基於上述事實的延伸推論，不是任何一篇新聞的原文結論，使用時應視為分析框架而非既定事實：**

1. **伺服器組裝／ODM廠（鴻海、廣達、緯創、緯穎）**：漲價會直接墊高單機/單櫃ASP，營收面看似受惠，但這類公司本質是低毛利率的代工/EMS模式，成本（記憶體、PCB、MLCC、ABF載板）同步大漲，**營收成長不必然等比例轉換成毛利成長**——已有台灣財經媒體（聯合新聞網）提出「AI伺服器代工毛利率見頂？」的疑問，搭配這幾家存貨水位走高的觀察，這是需要在後續季報中持續追蹤驗證的假設，不是可以現在就下定論的結論。

2. **記憶體供應鏈（南亞科、華邦電、威剛）**：這波漲價的根本驅動力是記憶體，理論上是直接受惠者，但要注意：HBM市場主要由SK Hynix、三星、美光三強寡占，台灣廠商（南亞科、華邦電）主要曝險在傳統DRAM／利基型記憶體，是透過「排擠效應」（HBM產能排擠傳統DRAM產能，推升傳統DRAM價格）間接受惠，而非直接參與HBM4這塊最核心的漲價敘事——受惠幅度與HBM原廠不能等量齊觀。

3. **TSMC（先進封裝CoWoS）**：CoWoS產能是這整條漲價敘事的關鍵瓶頸之一，NVIDIA一家吃下逾半產能，TSMC本身也傳出調漲代工價格（見Benzinga報導）——TSMC在這波成本轉嫁鏈中，議價力可能優於下游伺服器組裝廠。

4. **判斷這波漲價「能撐多久」的真正訊號，不是這則新聞本身，而是接下來1–2季超大規模業者（Microsoft/Google/Amazon/Meta）的資本支出guidance與訂單行為**：如果四大超大規模業者持續消化漲價、不縮減訂單，代表AI基礎建設需求仍強於供給，對整條台灣供應鏈是正向訊號；如果开始出現訂單遞延、轉單AMD/自研ASIC比例明顯提升，則會是這條投資邏輯反轉的早期警訊。目前（2026-08-25查證時點）尚未看到具體轉單或砍單的證據，僅有結構性的「自研晶片市占持續提升」長期趨勢報導，兩者時間尺度不同，不要混為一談。

5. **這是「成本推升型」漲價，還沒有證據顯示是「需求降溫型」漲價**：目前所有查到的證據都指向「供給端（記憶體+先進封裝）跟不上需求」，而非「NVIDIA主動測試客戶願付價格上限」。這對台股AI供應鏈的短期意義偏正面（代表訂單能見度仍在），但長期仍要留意NVIDIA毛利率是否因此被壓縮、進而影響其未來資本支出/研發投入節奏的二階效應——這部分屬於較遠期、confidence較低的推論。

---

## 八、追問延伸：漲價後成本壓力在AI產業鏈各環節的分布（2026-08-25 同日追加）

> 延續第一節起點新聞（DigiTimes逾15%系統漲價＋記憶體佔BOM 25-30%），往下追問：這筆錢最終從誰的口袋流出、痛感卡在誰身上。以下逐環節查證，**未重新查證第一節已確認的NVIDIA漲價基本事實**。

### 8.1 六環節逐一結論

**環節1：記憶體/先進封裝上游（Micron／SK海力士／三星HBM、TSMC CoWoS）**
**結論：能順利轉嫁，目前是全鏈最大贏家，且自身成本壓力尚未反映在財報毛利率上**
- 【事實】SK Hynix 2026年Q2：營收79.32兆韓元創紀錄、**營業利益率76%**（創紀錄）。來源：Investing.com https://www.investing.com/news/company-news/sk-hynix-q2-2026-slides-record-revenue-76-operating-margin-93CH-4818489 、SK hynix官方 https://news.skhynix.com/en/q2-2026-business-results/
- 【事實】HBM供給結構：SK Hynix市佔約50-55%、三星35-40%、美光5-10%；美光HBM產能已排到2027年滿載，且SK Hynix 2026年Q2已開始出貨HBM4。來源：siliconanalysts.com https://siliconanalysts.com/tools/hbm-analysis （產業分析網站，市占數字未逐一查證原始出處，信心中等）
- 【事實，但顯示上游也有自身成本壓力】TSMC 2026年Q2毛利率67.7%，但**公司自己預告Q3毛利率將降至約65%**，原因是2nm製程量產初期稀釋效應；資本支出上修至$600-640億美元，其中10-20%投入先進封裝／測試／光罩。CoWoS產能供需缺口目前約20%，預估2026年底縮小到約10%。來源：BigGo Finance https://finance.biggo.com/news/ff4e6083-1b21-4667-a21d-d05810cf6bdb 、howtheymake.money https://howtheymake.money/en/blog/2330-q2-2026-peak-margins-meet-record-capex
- **判讀**：記憶體廠（尤其HBM原廠）目前是這波漲價敘事中，財報數字最乾淨、最無疑義的受益者；TSMC同樣受益但正在承受2nm製程轉換帶來的短期毛利率稀釋——**這個稀釋是製程轉換的正常現象，不是被NVIDIA或下游壓縮的證據**，兩者不要混為一談。

**環節2：NVIDIA自己**
**結論：混合——目前財報毛利率仍在高檔，尚未看到「被上游壓縮」的明確證據，這次漲價更像是「提前防禦」而非「利潤已受損後的補救」**
- 【事實】最新一次已公布財報（Q1 FY2027，截至2026/4/26）：GAAP毛利率74.9%、non-GAAP毛利率75.0%，較FY2026全年（71.1% GAAP）明顯回升。來源：NVIDIA官方 https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2027
- 【事實】NVIDIA對Q2 FY2027（涵蓋2026/7/27結算季度，**將於2026/8/26公布，即本次查證後一天，尚未有實際數字**）的財測guidance為：non-GAAP毛利率約75.0%。市場分析已預先點名「DRAM、晶圓、先進封裝、基板成本上升可能持續施壓毛利率」是本次法說會關注焦點。來源：TradingKey https://www.tradingkey.com/analysis/stocks/us-stocks/262125952-nvidia-stock-q2-earnings-guidance-gross-margin-rubin-blackwell-china-tradingkey
- **判讀**：截至查證時點，NVIDIA帳面毛利率並未因這波記憶體漲價而下滑，反而處於近兩年高檔——這代表「逾15%系統漲價」的時間點是**在毛利率被壓縮之前**就先動手轉嫁成本，屬於防禦性定價，而非「利潤已經被啃食、不得不漲價止血」的落後反應。這與環節4-6呈現的「越下游越晚反應、越被動」形成對比。**留意：Q2 FY27實際數字將於2026/8/26公布，屆時應更新此節。**

**環節3：雲端巨頭／超大規模業者（Microsoft／Google／Amazon／Meta）**
**結論：混合，且四家內部已出現分化——微軟已有明確壓力訊號，AWS財報數字反而是擴張**
- 【事實，壓力訊號】微軟毛利率降至67.6%（從68.7%），**為2022年以來最低**，官方歸因於「加速折舊＋零組件成本通膨」；Intelligent Cloud部門營業利益率下滑180個基點至39.7%。來源：windowsforum.com整理財報 https://windowsforum.com/threads/microsoft-q3-2026-earnings-azure-ai-growth-vs-margin-pressure-from-capex.416169/
- 【事實，反例】AWS部門營業利益率反而**年增520個基點**（排除一次性項目），AI業務run rate已逾$250億美元、三位數成長。來源：同上heygotrade/uncoveralpha彙整 https://www.uncoveralpha.com/p/amazon-google-microsoft-meta-q2-earnings
- 【事實】2026年四大合計資本支出上看逾$7,250億美元（Amazon約$2,000億上修、Google $1,850-2,050億、Meta $1,250億、Microsoft $1,200-1,750億視日曆年/財年口徑）；**Amazon明確將capex guidance上修的原因之一寫成「因記憶體成本上升」（higher memory costs）**——這是少數「上游漲價直接反映進超大規模業者財測用語」的具體證據。來源：valueaddvc.com https://valueaddvc.com/blog/ai-hyperscaler-capex-compared-why-microsoft-google-meta-and-amazon-are-all-spending-at-once
- **判讀**：這環節不能用單一標籤概括——微軟明確出現毛利率被壓縮的訊號，AWS目前帳面仍在擴張（可能是規模效應/AI服務漲價抵銷了硬體成本），但四家都已把「更高的capex」寫進財測，代表折舊壓力正在累積、尚未完全反映在當期損益。

**環節4：GPU雲端出租商／Neocloud（CoreWeave／Nebius／Lambda）**
**結論：混合，且是六環節中「表面訂價能力」與「實際獲利能力」落差最大的一段——矛盾證據需並列**
- 【事實，訂價能力面】CoreWeave CFO於2026年Q1法說會表示公司「已大致售罄（largely sold out）」2026年容量，且對所有GPU世代都在漲價；現貨費率自2025年12月以來已漲超過20%；市場統計顯示H100合約租金漲40%、Blackwell漲48%；CEO Mike Intrator甚至表示2020年就已存在的A100仍以「full freight」（全額原價）簽約簽到2029年。來源：Yahoo Finance/24-7WallSt https://finance.yahoo.com/technology/ai/articles/coreweave-ceo-booking-2020-era-174325155.html 、tech-insider.org https://tech-insider.org/nvidia-blackwell-gpu-rental-price-surge-ornn-index-2026/
- 【事實，獲利品質面，與上面矛盾】CoreWeave帳面調整後EBITDA margin高達56%，但**計入折舊攤銷後的調整後營業利益率僅剩1%**；2026年Q2單季淨損$6.26億美元，資本支出高達$94億美元，利息費用是侵蝕獲利的主因。若採用業界更常見的4-5年折舊假設（CoreWeave自己用6年），GB200機隊的EBIT margin會從公司自報的約20.5%降到接近零甚至為負。來源：zettabyte.space「Neocloud unit economics」 https://www.zettabyte.space/blog/neocloud-unit-economics-gpu-cloud
- 【事實，同業對照，呈現Neocloud內部分化】Nebius同期表現明顯較佳：營收年增454%，毛利率77%，AI雲端業務調整後EBITDA margin 49.7%。來源：Motley Fool https://www.fool.com/investing/2026/08/04/better-neocloud-stock-nebius-vs-coreweave/
- **判讀**：使用者原判斷「Neocloud是壓力最大的一環」，查證後**方向正確但機制不同於預期**——不是「租金漲不動、被迫吸收NVIDIA漲價」（現貨/合約租金其實漲得很兇，訂價能力並不差），而是「租金雖能漲，但買GPU的資本支出＋債務利息＋折舊費用漲得更快」，本質是**資本結構/財務槓桿問題疊加硬體成本問題**，且CoreWeave與Nebius兩家財務體質差異極大，不能把「Neocloud」當成單一同質群體看待。

**環節5：伺服器代工／ODM（鴻海／廣達／緯創／緯穎）**
**結論：矛盾證據最明顯的一段，ODM廠內部分化清楚，不能一概而論**
- 【事實，承壓面】鴻海2026年Q1整體毛利率僅**6.18%**、營業利益率3.57%；產業評論指出「若AI機櫃毛利率低於集團平均，營收放大反而可能稀釋毛利率」，且鴻海主要大客戶（AWS、微軟、Google）議價能力強，鴻海承接的NVIDIA GB系列訂單走量大但單位毛利偏低。來源：股市基友 https://stockbuddyletter.com/foxconn-q2-2026-ai-margin/
- 【事實，較佳面，與上面矛盾】市場評論指出廣達AI伺服器毛利率「突破雙位數」，明顯優於鴻海；緯創／緯穎因掌握Microsoft／AWS的高階客製化訂單，毛利率表現「相對優於鴻海」。來源：豐雲學堂 https://www.sinotrade.com.tw/richclub/hotstock/AI%E4%BC%BA%E6%9C%8D%E5%99%A8%E8%A8%82%E5%96%AE%E7%86%B1%E6%BD%AE%E4%B8%8D%E6%B8%9B-%E9%B4%BB%E6%B5%B7-%E5%BB%A3%E9%81%94-%E7%B7%AF%E5%89%B5%E5%90%8C%E6%97%A5%E6%B3%95%E8%AA%AA%E9%87%8B%E5%87%BA%E5%BC%B7%E5%8B%81%E5%B1%95%E6%9C%9B-%E4%B8%89%E5%A4%A7%E4%BB%A3%E5%B7%A5%E5%B7%A8%E9%A0%AD2026%E5%B9%B4%E7%87%9F%E9%81%8B%E5%8B%95%E8%83%BD%E6%8C%81%E7%BA%8C%E5%8D%87%E6%BA%AB-%E8%82%A1%E5%B8%82%E8%A9%B1%E9%A1%8C-69152e3c97789711e33853c1
- **未找到具體法說會逐字稿引句直接證實「因這次記憶體漲價/NVIDIA系統漲價」而毛利率變化**——現有證據都是季度毛利率的橫向比較（鴻海 vs 廣達/緯創/緯穎），屬於結構性差異（客戶組合、產品組合），尚無法直接歸因於2026年8月這次NVIDIA新一輪漲價的因果關係，**這點屬於推論而非已證實的因果**。
- **判讀**：ODM廠的轉嫁能力高度取決於客戶結構與產品客製化程度——鴻海主打GB系列走量、客戶是議價力最強的四大巨頭之一，毛利率結構性偏低；廣達/緯穎的客製化程度與客戶結構使其毛利率表現較佳。**不能用「代工毛利率會被壓縮」或「代工毛利率不受影響」單一句話概括，兩者並存。**

**環節6：AI應用層／模型公司（OpenAI／Anthropic）與企業終端客戶**
**結論：明確被壓縮，且與「降價搶市占」的競爭動態強烈拉扯——目前競爭壓力壓過成本轉嫁**
- 【事實，虧損面】OpenAI 2026年預估虧損約$140億美元（部分外部模型估算現金燒錢速度上看$170-270億美元）；調整後毛利率從2024年的40%降至2025年的33%，2026年Q1回升至約39%。Anthropic 2026年預估虧損約$140億美元，但毛利率已從2024年約-94%大幅改善至2026年估44-60%區間（依資料來源與季度不同）；每一美元營收對應的運算成本從2026年Q1的$0.71降至Q2預估的$0.56。來源：valueaddvc.com（OpenAI）https://valueaddvc.com/blog/openai-revenue-2026-20b-arr-4b-month-path-to-profitability 、（Anthropic）https://valueaddvc.com/blog/is-anthropic-profitable-2026-losses-burn-rate-and-the-path-to-breakeven
- 【事實，與「成本轉嫁」直接矛盾】OpenAI於2026年7月**調降**API定價（"Terra"降20%、"Luna"降80%，官方說法是推理端優化使服務成本下降20%所致）；Anthropic原訂2026/9/1生效的Claude Sonnet漲價（$3/$15 → $... 更高）已於8/11**確定取消**，維持原本較低費率。來源：cloudzero.com（OpenAI）https://www.cloudzero.com/blog/openai-pricing/ 、finout.io（Anthropic）https://www.finout.io/blog/anthropic-api-pricing
- 【事實，補充脈絡】主要供應商每百萬token平均價格一年內從約$10降至$2.50；GPT-4發布以來每次查詢的推論成本已下降約95%——這是模型效率提升／競爭雙重作用的結果，與上游硬體成本上漲方向相反。來源：cloudzero.com https://www.cloudzero.com/blog/llm-api-pricing-comparison/
- **判讀**：這是六個環節中，「上游成本上升」與「下游定價」方向最明顯背離的一段。NVIDIA+記憶體的硬體成本在漲，但OpenAI/Anthropic之間為搶市占，API定價反而在降或凍漲，代價是兩家公司都維持巨額虧損（各約$140億美元/年量級）。**企業終端客戶目前是這條鏈上唯一明確享受到「降價」而非「漲價轉嫁」的環節**——但這個狀態能撐多久，取決於OpenAI/Anthropic的融資能力是否能持續覆蓋這個燒錢速度，屬於高度不確定的推論。

### 8.2 矛盾證據清單（並列呈現，不含糊帶過）

| 議題 | 證據A | 證據B | 矛盾點 |
|---|---|---|---|
| Neocloud訂價能力 | CoreWeave現貨漲20%+、H100合約+40%、Blackwell+48%，CFO稱「largely sold out」 | 同一家CoreWeave調整後營業利益率僅1%、Q2淨損$6.26億 | 表面訂價能力強，實際獲利能力極薄——問題不在轉嫁能力，在資本結構 |
| Neocloud同業比較 | CoreWeave獲利品質疑慮深（EBIT margin近零甚至負） | Nebius毛利率77%、AI雲端調整後EBITDA margin 49.7%、營收年增454% | 「Neocloud」不是同質群體，個別公司財務體質差異極大 |
| 雲端巨頭毛利率 | 微軟毛利率降至67.6%，2022年以來最低 | AWS營業利益率反而年增520bps | 四大超大規模業者內部分化，不能一概而論 |
| 台灣ODM毛利率 | 鴻海整體毛利率僅6.18%，AI機櫃恐稀釋毛利 | 廣達AI伺服器毛利率「突破雙位數」、緯創緯穎「相對優於鴻海」 | ODM廠因客戶結構/產品組合不同，轉嫁能力差異巨大 |
| 下游定價方向 | 上游記憶體/NVIDIA成本明確上漲（本研究第一節） | OpenAI 2026/7降價、Anthropic取消原訂9月漲價 | 終端AI服務定價與上游硬體成本方向相反，競爭動態壓過成本轉嫁 |

### 8.3 對台股投資標的的延伸判斷（我的推論，非新聞原文主張）

**風險段（推論，需留意毛利率是否持續承壓）**：
- **鴻海**：Q1 2026整體毛利率僅6.18%，AI機櫃走量但單位毛利偏低，大客戶（AWS/微軟/Google）議價力強，是六環節中「轉嫁能力證據最弱」的台廠代表——不代表營收會變差（GB系列訂單能見度仍在），但毛利率能否隨營收等比例成長，是後續每季法說會要盯的關鍵指標，而非現在就能下定論。

**受益段（推論，證據相對支持）**：
- **南亞科、華邦電**：記憶體排擠效應下的間接受益者（第一節已列，本次追問財報數字進一步佐證：SK Hynix營業利益率76%創紀錄，顯示整個記憶體產業定價環境確實極強勢，排擠效應理論上對南亞科/華邦電的傳統DRAM報價同樣有利）。
- **廣達、緯穎**：相對鴻海而言，客製化程度較高、客戶結構分散，本次追問查到的市場評論明確指出兩者毛利率「優於鴻海」，是ODM段內部「轉嫁能力較強」的代表——但這仍是同業比較的市場評論，非兩家公司法說會逐字稿的直接引句，信心中等。
- **台積電**：先進封裝CoWoS的稀缺性議價力目前看來是六環節中最穩固的（供需缺口仍有約20%），2026年Q3毛利率因2nm量產短期稀釋屬製程轉換正常現象，非被下游壓縮的訊號，中長期仍是這條漲價鏈中最能全身而退的一環。

**需持續觀察、目前證據不足以下定論的部分**：
- NVIDIA本身2026/8/26即將公布的Q2 FY2027實際財報，是驗證「這次漲價是否真的守住75%毛利率」的第一個關鍵時間點，本研究完成時（2026-08-25）尚未公布。
- 微軟等雲端巨頭的毛利率壓力，是否會在未來1-2季回頭向上游ODM廠（鴻海等）要求更低報價以轉嫁自身成本壓力——這是「痛感沿供應鏈再傳導一輪」的假設性風險，目前沒有直接證據，僅是邏輯推論。
- OpenAI/Anthropic的降價策略若因融資環境轉緊而無法持續，是否會轉向漲價、進而影響企業終端客戶的AI採用速度——這會是檢驗整條鏈需求端韌性的關鍵訊號，目前僅能持續追蹤，無法預判。

---

## 九、追問延伸：自研ASIC為什麼能繞過NVIDIA＋Anthropic自研晶片查證（2026-08-25 同日追加）

> 延續第八節「超大規模業者自研ASIC侵蝕NVIDIA市占（90%→75%）」的伏筆，往下拆解機制本身，並獨立查證使用者提到的「Anthropic也投入自研晶片」說法。**未重新查證前兩節已確認的NVIDIA漲價/毛利率基本事實。**

### 9.1 機制拆解：自研ASIC為什麼能減少對NVIDIA的依賴

**角度一：成本/TCO——理論上省下NVIDIA的硬體毛利，但證據多來自利益相關方，需保守看待**
- 【事實，但需注意來源立場】各家宣稱的省錢幅度差異極大且多為廠商/分析師單方說法：Google TPU推論性價比號稱是NVIDIA的4.7倍、耗電量減67%（案例：Midjourney年省$1,680萬、GPT-4規模5年生命週期估可省$63.2億美元）；AWS官方宣稱Trainium推論比同等NVIDIA GPU配置省最高50%成本。來源：ainewshub.org https://www.ainewshub.org/post/nvidia-vs-google-tpu-2025-cost-comparison （單一案例研究，未見獨立第三方覆核）、howaiworks.ai https://howaiworks.ai/blog/tpu-gpu-asic-ai-hardware-market-2025
- 【推論】這些數字幾乎全部來自Google/AWS自家部落格或引用其說法的二手媒體，屬於「賣家證詞」，不是獨立審計數字——NVIDIA毛利率74-75%代表理論上確實有相當大的省錢空間，但實際能省多少，取決於自研晶片自身的研發攤提成本、良率、產能利用率，這些變數外部很難獨立驗證，**應視為方向正確、幅度存疑**。

**角度二：軟體生態——CUDA護城河對「訓練」仍近乎完整，對「推論」正在被啃食但尚未被取代**
- 【事實】CUDA生態系統累積20多年的函式庫（cuDNN、cuBLAS、FlashAttention-3、vLLM的PagedAttention/連續批次處理、SGLang的推測解碼、TensorRT-LLM的FP8張量核心、NCCL多節點通訊）——這些最先進的LLM推論優化技術「幾乎全部只跑在CUDA上」，不跑在Trainium的Neuron SDK、TPU的JAX/XLA、Maia或MTIA上。來源：builtin.com https://builtin.com/articles/nvidias-cuda-future-ai-infrastructure
- 【事實】各家自建生態各自為政，沒有任何聯盟嘗試整合成單一堆疊來對抗CUDA——Google用XLA/JAX、Amazon用Neuron SDK、AMD用ROCm、Meta MTIA用PyTorch/XLA後端，彼此不相容也不互通。來源：同上
- 【事實，佐證遷移門檻正在降低但仍存在】以推論服務遷移到Trainium為例，把vLLM服務堆疊移植到Neuron相容程式碼，實務估計約需2-6週（若模型不是Neuron原生支援，還要再加時間）——顯示「繞過CUDA」的技術門檻對於**推論**場景已經降到週級別，不是遙不可及，但仍需要額外工程投入，不是零成本切換。來源：hashrateindex.com https://hashrateindex.com/blog/hyperscaler-ai-asic-market-report-part-1/

**角度三：工作負載——這是最關鍵的區分，ASIC目前主要啃食「推論」，「訓練」仍高度依賴NVIDIA**
- 【事實】市場出現清楚的負載分工：通用GPU持續以16.1%年複合成長率成長，主要由訓練負載驅動（NVIDIA的CUDA生態與軟體成熟度在訓練場景仍是強大護城河）；客製化ASIC則以44.6%年複合成長率成長，主要瞄準推論負載——推論目前已佔所有AI工作負載的三分之二。分析師預估NVIDIA在「推論」市場的份額可能從90%以上降到2028年的20-30%（**這是分析師預測，非已發生的事實，信心中等**）。來源：introl.com https://introl.com/blog/custom-silicon-inflection-2026-hyperscaler-asics-nvidia-gpu
- 【事實】以AWS自身產品線為例，Trainium系列本身也內部再分工：Trainium主打訓練、Inferentia主打推論——連自研陣營內部都認知到訓練與推論是不同的優化問題，不是一顆晶片打天下。來源：howaiworks.ai（同上）
- **判讀：「自研ASIC繞過NVIDIA」這句話如果不加區分負載類型，容易誤導——目前證據支持的是「推論負載正在被啃食」，「訓練負載（尤其前沿大模型訓練）仍高度依賴NVIDIA GPU+CUDA」，兩者不能混為一談。**

**角度四：供應鏈——ASIC同樣要排隊TSMC/CoWoS，只是換一種方式排隊；但出現了少數繞開TSMC找Samsung的嘗試**
- 【事實】絕大多數客製化ASIC（Google TPU、Amazon Trainium等）仍由TSMC代工，且同樣需要CoWoS先進封裝——換句話說，自研ASIC並沒有讓這些公司逃離TSMC/CoWoS產能瓶頸，只是把「跟NVIDIA搶產能」換成「用自己的訂單額度跟NVIDIA搶同一批產能」，性質上仍是同一條稀缺產能的競爭，沒有真正繞開。來源：本研究第八節已引用的TSMC CoWoS產能分析（DigiTimes、BigGo Finance）
- 【事實，值得特別注意的例外】Anthropic籌備中的自研推論晶片，傳出**與Samsung展開2nm製程初期探索性對談**，而非鎖定TSMC——這是本次查證中少見的「刻意迴避TSMC/CoWoS排隊問題」的具體訊號，但目前僅是「早期探索性對談」，未確認簽約或量產時程。來源：見9.2節Tom's Hardware報導

### 9.2 Anthropic自研晶片查證結果（獨立查證，明確標註使用者原話是否準確）

**使用者原話「Anthropic也投入自研晶片」——查證結論：以2026年8月的最新狀態而言，這句話字面上並非錯誤，但如果背後的理解是「Anthropic的晶片策略主要靠自己設計晶片」，那就是誤解，需要修正。實際情況是三層更精確的事實：**

1. 【事實，這是Anthropic算力策略的主體，佔絕大部分現有算力】Anthropic目前（且長期以來）的算力策略是**混用三個平台**：Google TPU（與Broadcom共同設計）、Amazon Trainium（透過與AWS合作的「Project Rainier」超級電腦叢集，2026年時已啟用約50萬顆Trainium2晶片，且預計擴大到逾100萬顆）、以及NVIDIA GPU。2025年10月23日，Anthropic與Google Cloud官方公告進一步擴大TPU使用規模至最多**100萬顆TPU**、逾1GW算力容量、規模達數百億美元，且公告中明確重申「獨特策略著重在三個晶片平臺的多元化應用」。**這些都是Google和Amazon自己設計的客製化晶片，Anthropic是這些晶片的大客戶/使用者，不是設計者。**
   來源：Anthropic官方公告 https://www.anthropic.com/news/expanding-our-use-of-google-cloud-tpus-and-services 、datacenterfrontier.com https://www.datacenterfrontier.com/machine-learning/article/55335703/inside-anthropics-multi-cloud-ai-factory-how-aws-trainium-and-google-tpus-shape-its-next-phase

2. 【事實，這是非常新、規模仍小的補充動作，不是取代既有策略】2026年6月初，Anthropic才**首次組建內部自研晶片團隊**，聘用前OpenAI晶片工程師Clive Chan（曾參與Broadcom設計的推論加速器專案約2.5年）主導，並與**Samsung**（而非TSMC）就2nm製程展開初期探索性對談。媒體報導明確定調這是「把內部自研設計新增為又一個選項」，而非推翻現有的TPU/Trainium/GPU三方並用架構；Anthropic自身立場強調「被單一供應商的定價結構綁定，看起來越來越像策略風險，而不只是採購細節」（"being locked to one vendor's pricing starts to look like a strategic liability rather than a procurement detail"）。這顆自研晶片鎖定的是**推論用途**，不是訓練。截至查證時點（2026-08-25），僅有「早期探索性對談」，未見已簽約、流片或量產時程的公開資訊。
   來源：Tom's Hardware（標題已證實）https://www.tomshardware.com/tech-industry/anthropic-to-build-its-own-co-designed-custom-ai-accelerator-for-inferencing-workloads-samsung-reported-to-be-partnering-with-the-claude-ai-maker-for-manufacturing 、AI Weekly（2026/8/5發表，8/10更新）https://aiweekly.co/alerts/anthropic-stands-up-custom-chip-team-keeps-multi-silicon-mix 、Forbes標題確認 https://www.forbes.com/sites/jonmarkman/2026/08/06/anthropic-enters-the-ai-chip-race-with-in-house-chip-team/ （Forbes內文因403無法完整存取，僅標題與檢索摘要可確認，**信心中等**）

3. **修正結論**：Anthropic「投入自研晶片」這件事**本身是真的，且時間點非常新（2026年6月才組建團隊、8月才被媒體報導）**，但它是Anthropic整體算力布局中極小、極早期的一塊，主體仍是「向Google租TPU算力、向Amazon租Trainium算力（外加自建的Project Rainier叢集）、以及採購NVIDIA GPU」這種**多元採購／多元代工客戶**的角色，而不是「像Google那樣自己設計晶片架構已成熟量產」的角色。如果使用者原本的理解是後者（把Anthropic類比成第二個Google TPU），這個類比目前不成立；如果理解是「Anthropic近期也開始跟進自研晶片這股風潮」，這句話是準確的。

### 9.3 反面證據／限制

- 【事實】超大規模業者並未「全押」自研晶片，NVIDIA絕對金額營收持續成長：NVIDIA FY2026資料中心營收達$1,937億美元（年增68%），2026上半年在AI加速器市場份額估計仍有75-81%（依統計口徑不同，有分析估計介於70-92%之間，區間本身顯示這個數字目前業界沒有共識，需保守解讀）。來源：celadonresearch.com https://celadonresearch.com/research/nvidia-ai-accelerators-q1-2026 、siliconanalysts.com https://siliconanalysts.com/analysis/nvidia-ai-accelerator-market-share-2024-2026
- 【事實，執行風險是真實存在的】AWS Trainium 3傳出延遲，原因是液冷系統尚未就緒、加上N3製程設計複雜度與SerDes/IO實作難度；組裝階段也傳出良率問題（報導形容為新系統「相當常見」的問題，非重大失敗）；Trainium 2預計2025年9月左右淘汰，過渡期先推出風冷的「Trainium 2 MAX」。相對之下，Google TPU專案被認為是超大規模業者自研陣營中進度最成熟、最平順的一個（TPU v7 Ironwood已於2025年4月發表）。來源：lumenalpha.substack.com https://lumenalpha.substack.com/p/delayed-aws-trainium-3-and-phased
- 【事實】NVIDIA／黃仁勳本人對ASIC威脅的公開回應是**持續淡化**：黃仁勳多次公開表示約90%的ASIC專案最終會失敗（類比新創公司多數失敗的邏輯）；並主張NVIDIA做的是「加速運算」而非單純「張量處理」，市場覆蓋範圍不是TPU等專用ASIC能比擬的；強調NVIDIA架構迭代與降本速度夠快，能持續讓客戶「持續採用」而非轉單。來源：DigiTimes英文版（標題：「Nvidia CEO dismisses ASIC threat as noncompetitive」）https://www.digitimes.com/news/a20250321PD211/nvidia-asic-gtc-jensen-huang-ceo.html
- **判讀**：NVIDIA官方立場本身當然帶有利益偏向（不會承認威脅重大），但「執行風險真實存在」（Trainium 3延遲）與「絕對金額尚未萎縮」是相對中性的事實佐證，顯示這個威脅目前是「趨勢方向明確、但尚未在財報數字上造成NVIDIA絕對衰退」的階段。

### 9.4 對投資判斷的延伸（我的推論，非新聞原文主張）

**代表威脅正在加速的訊號（推論）**：
- 連Anthropic這種**非超大規模業者、沒有自己雲端基礎設施的純AI模型公司**都在2026年跟進投入自研晶片團隊，顯示這個經濟邏輯的吸引力已經擴散到超大規模業者以外的圈層，不再只是Google/Amazon/Microsoft四大巨頭才玩得起的遊戲。
- Anthropic選擇Samsung而非TSMC做為2nm初期對談對象，若這個模式被其他公司複製，長期可能是TSMC在「最先進AI晶片代工」這個特定利基市場首次出現的具體分散風險訊號——**但目前僅一個早期探索性合作報導，樣本數是1，不宜過度外推**。
- 分析師預測NVIDIA推論市場份額可能在2028年前大幅下滑至20-30%——如果方向被驗證，代表「訓練靠NVIDIA、推論找ASIC」的分工會越來越制度化，而推論恰好是隨AI應用普及後成長最快的那塊（目前已佔工作負載三分之二）。

**代表威脅還早、不宜過度反應的訊號（推論）**：
- NVIDIA資料中心營收絕對金額仍在高速成長（FY2026年增68%），目前看到的是「新增算力需求中，ASIC分走的比例在提高」，不是「既有NVIDIA訂單被替換掉」——這是成長率放緩的故事，不是衰退的故事，兩者對股價/供應鏈的意義完全不同。
- CUDA護城河對「訓練」場景幾乎完整無損，前沿大模型訓練（決定AI能力上限的最關鍵環節）目前看不到任何一家在用ASIC取代NVIDIA GPU做訓練的證據——這部分本研究未查到反例，可視為NVIDIA目前最穩固的陣地。
- 自研晶片的執行風險是真實的（Trainium 3延遲案例），代表「自研」不等於「順利」，時程一旦落後，反而可能讓這些公司短期內更依賴NVIDIA做為備援產能，形成短期的反向需求。

**對台灣供應鏈的延伸（推論，銜接第八節）**：
- ASIC趨勢對台灣半導體供應鏈**不必然是壞消息**——目前絕大多數客製化ASIC仍在TSMC代工＋用CoWoS封裝，不管超大規模業者買的是NVIDIA GPU還是自家ASIC，多數情況下錢還是流向台積電，這是與「NVIDIA市占下滑＝台灣供應鏈受害」直覺不同、值得留意的一點。
- 真正該留意的風險訊號是「Samsung是否開始從TSMC手中搶下更多AI晶片代工訂單」——Anthropic這個案例目前是單一早期訊號，但如果未來看到更多AI晶片設計公司因TSMC/CoWoS產能排隊過久而轉向Samsung，這會是比「NVIDIA市占下滑」更直接衝擊台灣供應鏈的變數，建議後續追蹤。

---

## 十、追問延伸：自研ASIC機櫃組裝與資料中心運營的實際分工（2026-08-25 同日追加）

> 延續第九節「自研ASIC為什麼能繞過NVIDIA」，往下查證機櫃組裝與機房運營的實際廠商分工，判斷這對台灣ODM是「訂單質變」還是「訂單流失」。**未重新查證前面各節已確認的事實。**

### 10.1 五個案例逐一查證：機櫃組裝實際廠商

**Google TPU**
- 【事實】晶片設計：Google主導架構與軟體棧，**Broadcom**是主要設計合作夥伴，負責把Google架構轉化為可製造的ASIC（高速SerDes IP、電源供應協調、CoWoS封裝），合約期限至2031年；Broadcom FY2026 Q1 AI營收達$84億美元（年增106%）。來源：Data Gravity（2026/6/2發表）https://www.datagravity.dev/p/googles-tpu-supply-chain
- 【事實，機櫃組裝】**Inventec（英業達）是目前最明確被指認的主導ODM**，文章原文：「台灣ODM在這項工作中佔主導地位」，管理層對2026年ASIC伺服器出貨雙位數成長表示信心；**Wiwynn（緯穎，緯創子公司）正在馬來西亞積極擴展SMT產能，專攻ASIC伺服器組裝**；Quanta（廣達）、Foxconn（鴻海）、Mitac（神達）則是競爭中爭取更多訂單分配的廠商。來源：同上
- 【事實，補充個案】鴻海已拿下Google TPU伺服器的「重大訂單」，具體負責供應與TPU機櫃**1:1配比的運算托盤（compute trays）**；鴻海目前每週生產逾1,000個AI伺服器機櫃，計畫2026年底前翻倍到每週2,000個以上。文章未附精確訂單金額或簽約日期。來源：igorslab.de https://www.igorslab.de/en/foxconn-reaches-for-the-heart-of-the-ki-infrastructure-major-order-for-googles-tpu-server-reveals-new-dynamics-in-the-server-market/
- **判讀**：Google TPU機櫃組裝由台灣ODM群體共同參與（Inventec領先、Wiwynn/Foxconn/Quanta/Mitac都有份），不是由單一非台灣廠商壟斷，也不是繞開台灣供應鏈。

**Amazon Trainium（Project Rainier）**
- 【事實】AWS客製化AI伺服器「**主要由台灣緯穎（Wiwynn）組裝**」。來源：CommonWealth Magazine（天下雜誌英文版）https://english.cw.com.tw/article/article.action?id=4491
- 【事實，補充】鴻海、廣達、緯創同時也在液冷技術上投資，顯示三者都在AWS供應鏈中有一定程度參與，但搜尋結果未明確指出這三家是Project Rainier機櫃組裝的主力，主要組裝角色的證據集中指向Wiwynn。來源：同上
- 【事實】Project Rainier本身是為Anthropic訓練Claude打造的AI超級叢集，2026年時已啟用近50萬顆Trainium2晶片。來源：DataCenterDynamics https://www.datacenterdynamics.com/en/news/aws-activates-project-rainier-cluster-of-nearly-500000-trainium2-chips/

**Microsoft Maia**
- 【事實】Wiwynn與Quanta都是Microsoft的合約製造商；Quanta更進一步準備推出完整基礎設施解決方案（伺服器、儲存、網路）來運行Microsoft私有雲。來源：DataCenterDynamics（Quanta）https://www.datacenterdynamics.com/en/news/quanta-puts-all-you-need-to-run-microsofts-private-cloud-in-one-rack/
- 【事實】更廣泛地說，「Quanta、Wiwynn、Inventec、Foxconn、Celestica、Supermicro都是依規格生產伺服器的夥伴」——沒有查到單一廠商壟斷Maia機櫃組裝的證據，是多家台灣ODM（加上美系Celestica、Supermicro）競爭分工的格局。來源：techblog.comsoc.org https://techblog.comsoc.org/2025/09/01/hyperscaler-compute-server-in-house-designs-with-odm-partners/

**Meta MTIA**
- 【事實，本案是五個案例中集中度最高的】Meta與Quanta、Wiwynn、Foxconn合作設計/組裝運算伺服器；**Celestica（美國）與Quanta是主要組裝商（Key assemblers）**；**Wiwynn則是負責把運算、散熱、電力、網路/光學、機櫃製造整合成可部署系統的核心ODM，且Wiwynn營收有「超過一半來自Meta」**——這是本次查證中，單一台灣ODM對單一客戶依賴度最高、關係最深的案例。來源：Silba https://silbadeepdives.substack.com/p/6669-wiwynn-the-heavy-metal-behind
- 【事實】Meta的MTIA機櫃代號「Minerva」，2025下半年開始量產爬坡、2026年進一步擴大，每個機櫃含16個運算刀鋒（各配1顆MTIA晶片+1顆CPU，液冷設計）、6個網路刀鋒、1個機箱管理模組刀鋒。來源：同上

**Anthropic自研推論晶片**
- 【事實，明確回答「太早期，尚無答案」】截至2026年8月查證時點，Anthropic與Samsung僅止於2nm製程的**早期探索性對談**，媒體明確報導「該公司尚未決定這顆晶片要做什麼、性能多強、要如何裝進伺服器」（"has not yet determined what the chip will do, how powerful it will be, or how it will fit into a server"）；標準晶片開發週期需3-5年，這顆晶片最快也要到**2028年（甚至2029年）才可能量產**。來源：techtimes.com https://www.techtimes.com/articles/319574/20260702/anthropic-talks-samsung-build-custom-ai-chip-aiming-2nm-process.htm
- **判讀**：機櫃組裝廠商完全未知，且問這個問題本身在2026年8月這個時間點就「問得太早」——連晶片規格都沒定案，遑論組裝分工。**誠實標註：未知，且是「太早無法知道」而非「查不到」。**

### 10.2 資料中心運營模式：超大規模業者自建自營 vs Neocloud租賃模式

- 【事實】Google／Amazon／Microsoft核心資料中心策略是**自建自營為主，輔以部分colocation（向Equinix等業者租用機房空間）作為補充**——這是既定的hybrid模式，但高密度AI運算的核心campus多由自己設計興建。微軟公開策略被形容為「加倍投入自建AI資料中心，同時維持策略性colocation合作」。來源：globaldatacenterhub.com https://www.globaldatacenterhub.com/p/global-data-center-hub-issue-5
- 【事實，與第八節Neocloud分析呼應形成對比】CoreWeave模式相反：**主要用租來的「powered shell」（已通電但未裝機的機房外殼）＋自己買GPU裝進去**，機房本身多是租的，GPU資本支出才是自己資產負債表上的大項；資金來源高度依賴債務——CoreWeave總借款達$111.7億美元，多屬10-15%高利率、以GPU與客戶合約作抵押的貸款。
  來源：levelheadedinvesting.com https://www.levelheadedinvesting.com/p/when-growth-runs-on-debt-the-coreweave-case-study
- **核心差異**：超大規模業者是「自己蓋房子、自己裝潢、自己住」，資本雄厚、用自有現金流/低成本融資支撐；Neocloud是「租房子、自己裝潢、背房貸利率很高的裝潢貸款」——這正是第八節查到「CoreWeave帳面訂價能力強但實際獲利能力薄弱」的資本結構根源，本節從機房所有權角度再次印證同一個結論。

- 【事實，回應「客製化基礎設施是否也是自研動機之一」】**是，且有具體技術證據支持，不只是省NVIDIA毛利的財務動機**：Google TPU v7功耗約500W、Amazon Trainium 3約600W，均落在可用「直接晶片液冷」或「後門熱交換器」處理的範圍內，不需要NVIDIA最高階配置所需要的全浸沒式冷卻——這讓資料中心設計更簡化；報導並指出「晶片、互連、冷卻被設計成單一整合系統」是最先進AI訓練基礎設施的趨勢，Google的動機更被形容為「自家模型演進速度太快，第三方晶片跟不上」，Meta則因為「不做雲端生意，動機純粹是內部效率」。來源：sanieinstitute.substack.com https://sanieinstitute.substack.com/p/custom-silicon-or-bust-the-new-default
- 【推論，需保守看待】業者宣稱自研晶片在規模化後有40-65%的TCO優勢——**這類數字同樣來自業者自身或親廠商分析師，與第九節「省下NVIDIA毛利」的說法屬同一類「賣家證詞」，方向可信但幅度不宜照單全收**。

### 10.3 對台灣供應鏈的具體判斷（有證據支持，逐案例講清楚，不含糊帶過）

**整體結論：四個「有實體產品且已量產」的案例（TPU/Trainium/Maia/MTIA）全部確認台灣ODM深度參與機櫃組裝，是「訂單質變」（同一批台灣廠商，從組NVIDIA GPU機櫃變成也組ASIC機櫃），沒有一個案例查到「繞開台灣ODM、找中國廠商或hyperscaler純自製機櫃」的證據。唯一「未知」的案例（Anthropic自研晶片）是因為太早期、連晶片本身都沒定案，不是因為證據顯示會繞開台灣供應鏈。**

分案例具體判斷：
- **Google TPU**：質變，且是台灣ODM群體共同参與、彼此競爭份額的市場（Inventec目前領先、Foxconn/Quanta/Wiwynn/Mitac都有訂單或積極爭取）——對台灣ODM整體是機會，但個別廠商間存在份額洗牌風險（例如Inventec在ASIC機櫃這塊的份額可能高於它在NVIDIA GPU機櫃市場的份額）。
- **Amazon Trainium**：質變，且證據顯示相對集中在**緯穎（Wiwynn）**身上，鴻海/廣達/緯創在此案例中的角色證據較薄弱（僅查到液冷技術投資，未確認為機櫃組裝主力）。
- **Microsoft Maia**：質變，多家台灣ODM（Wiwynn、Quanta、Inventec、Foxconn）加上美系Celestica、Supermicro共同競爭，分工格局類似NVIDIA GPU伺服器市場的「多雄並立」。
- **Meta MTIA**：質變，且是五案中對單一台灣廠商（**緯穎**）依賴度最深的案例——緯穎營收逾半數來自Meta，代表緯穎在「自研ASIC」這條路線上，實質上已經是比「NVIDIA GPU伺服器組裝」更早、更深耕的既有業務，不是新增的機會，而是本業。
- **Anthropic自研推論晶片**：未知，太早期無法判斷，最快2028-2029年才可能量產，現在討論組裝分工沒有意義。

**延伸推論（我的判斷，非新聞原文主張）**：綜合五案例，「自研ASIC興起＝威脅台灣ODM」這個直覺**在機櫃組裝這一層並不成立**——真正影響台灣ODM個別廠商命運的，不是「NVIDIA GPU訂單被ASIC訂單取代」，而是「哪家ODM能在ASIC機櫃這個新戰場卡到位置、份額是否與NVIDIA GPU機櫃市場相同」。從目前證據看，**緯穎（Wiwynn）在Trainium與MTIA兩案中都占據核心地位，是這波ASIC趨勢中證據最明確的受益者**；鴻海在Google TPU案例中確認拿下訂單但採1:1配比的相對從屬角色（供應運算托盤搭配Google自己的TPU機櫃，而非緯穎/Inventec式的整機櫃整合角色）；廣達、英業達則分別在Microsoft Maia、Google TPU案例中有明確參與。**對台灣ODM整體是機會而非威脅，但機會的分配並不平均，緯穎目前證據上的曝險程度與受益程度都最高（意味著波動也可能最大）。**

> **本節與第十一節的重要銜接／修正**：第十一節子題B查證ODM廠**實際合併毛利率**時發現，廣達2026Q1僅4.78%、Q2約5.02%，緯穎2026Q1為7.55%（年減115bps）——遠低於本節聚焦的「機櫃組裝角色歸屬」問題所能反映的獲利品質。換句話說，**即使緯穎在ASIC機櫃這個新戰場卡位最深，它作為整體公司的合併毛利率仍是個位數**，這與零組件層（記憶體、載板、散熱、電源、先進封裝）動輒25%以上的毛利率形成鮮明對比。第十節「訂單質變、對台灣ODM是機會」的結論仍然成立（訂單量與營收面），但「機會」不宜直接等同於「高毛利」——組裝這個環節的結構性低毛利，不因NVIDIA GPU换成ASIC而改變。詳見第十一節子題B。

---

## 十一、追問延伸：機櫃組裝之外的AI基建環節盤點＋高毛利穩健標的觀察清單（2026-08-25 同日追加）

> 延續第十節,兩個子題：(A) 盤點電力、光通訊等機櫃組裝之外的關鍵環節；(B) 整合第一節至本節所有已識別公司,篩選出隔絕「AI應用層價格戰」風險、有財報數字佐證的高毛利觀察清單。**未重新查證前面各節已確認的事實。**

### 11.1 子題A：機櫃組裝之外的關鍵環節

**環節1：電力——供應鏈最緊、漲價證據最硬、且是本次查證中唯一「交期用『年』計算」的環節**
- 【事實，驅動力＋吃緊證據】美國逾半數規劃中的2026年資料中心恐因變壓器與配電設備嚴重缺貨而延遲或取消（產業估計30-50%）；目前僅約5GW在興建中,對比已宣布的約16GW；變壓器與渦輪機等關鍵零組件全球交期普遍拉長到15-24個月,部分達3-5年,產能已賣到2028年；**自2019年以來,電力變壓器單價已上漲77%,部分配電變壓器漲幅高達95%**。來源：chargeduppro.com https://chargeduppro.com/post/data-center-transformer-shortage-power-bottleneck-industrial-property-2026 、build.inc https://build.inc/insights/data-center-transformer-procurement-2026
- 【事實，國際受惠公司】GE Vernova（併購Prolec後在變壓器領域居主導地位）：2026年電氣化(Electrification)部門營收展望上修至$145-150億美元(含Prolec GE約$31億)、部門EBITDA margin展望18-20%；2026Q1單季在資料中心相關設備訂單即達$24億美元,超過2025全年。來源：GE Vernova官方 https://www.gevernova.com/news/press-releases/ge-vernova-reports-second-quarter-2026-financial-results-raises-2026-financial
- 【事實，台灣受惠公司：重電四雄】華城電機、士林電機(士電)、中興電工、亞力電機在手訂單能見度普遍到2027-2028年,中興電工甚至喊到2032年（在手訂單約440億台幣）；華城電機AI資料中心訂單已逾120億台幣,2026年AI DC占比估超10%,**2025Q4毛利率42.2%**；士電重電事業訂單滿至2028、已開始接2029-2030年訂單,2025年AI建廠設備占重電事業群2成,估2026年再增10個百分點；**大型電力變壓器交期已拉長到約兩年半,矽鋼片等關鍵原料供應緊俏是製造端瓶頸**。**中興電工訂單能見度雖最長,但本次查證未找到其具體毛利率數字,列入11.2的「未查證」清單。**來源：豐雲學堂 https://www.sinotrade.com.tw/richclub/industry/AI-%E8%B3%87%E6%96%99%E4%B8%AD%E5%BF%83%E8%88%88%E5%BB%BA%E8%88%87%E9%9B%BB%E5%AD%90%E6%A5%AD%E6%93%B4%E5%BB%A0-%E8%8F%AF%E5%9F%8E-%E5%A3%AB%E9%9B%BB-%E4%B8%AD%E8%88%88%E9%9B%BB-%E4%BA%9E%E5%8A%9B%E9%87%8D%E9%9B%BB%E5%BB%A0%E5%95%86%E6%8E%A5%E5%96%AE%E7%81%AB%E7%86%B1-%E7%94%A2%E6%A5%AD%E7%86%B1%E8%A9%B1-69ddf4043f76ec0ab4f49eff
- 【事實，台達電——電力+散熱雙重曝險最大的單一台廠】台達電AI相關營收占比已超25%（法人估2026挑戰30%以上）,液冷散熱業務營收占比達9%,AI電源相關營收占比突破20%,**AI伺服器電源市占達60%**；**2026Q1毛利率37.0%創歷史新高**,營益率17.8%同創新高；法人預期資料中心營收毛利率分別為39.0%、40.5%、40.1%。來源：工商時報 https://www.ctee.com.tw/news/20260426700019-430105 、經濟日報 https://money.udn.com/money/story/5612/9480332

**環節2：光通訊（800G/1.6T光模組＋CPO）——成長驅動力最強,但台廠具體毛利數字本次查證掛零，需誠實標註**
- 【事實，驅動力與市場規模】AI光收發模組市場2026年估達約$260億美元,年增逾50%；800G以上模組占全球出貨比重從2024年約19.5%躍升至2026年逾60%。來源：McKinsey/LightCounting彙整（見penchan.co） https://penchan.co/en/market/ai/supply-chain/cpo/
- 【事實，吃緊證據】McKinsey模型估計800G模組產出到2027年前仍落後需求40-60%,1.6T到2029年前落後30-40%；LightCounting估目前供需缺口約30%,預期2026年底隨新InP(磷化銦)產能認證完成而緩解；**瓶頸卡在雷射本身**——800G/1.6T以上規格所需的電吸收調變雷射與連續波雷射,都需要磷化銦(InP)基板,目前沒有量產替代材料,是實質配額制。來源：同上
- 【事實，價格】800G模組報價：長距版$420-450、短距版$360-380；1.6T模組報價：$1,300-1,500,預期兩年內可能降到約$1,100（**注意：這是預期供給緩解後價格下降,不是漲價**,方向與記憶體/電力相反,需並列說明——光通訊產業的稀缺性目前主要反映在「缺貨/交期」而非「持續飆漲的單價」）。來源：同上
- 【事實，台廠參與但毛利數字未查到】聯亞已與日本住友電工簽下2026-2030五年期InP基板長約（上游材料保供）；波若威在耦光元件(FA/FAU)領域布局；華星光在光收發模組領域布局；CPO（共同封裝光學）效率可望提升達3.5倍,NVIDIA計畫2025/2026硬體有限度採用,但2026年滲透率仍很低,與傳統可插拔模組並存。**本次查證未找到聯亞、波若威、華星光的具體毛利率數字,列入11.2「未查證」清單，不放進正式觀察清單。** 來源：數位時代 https://www.bnext.com.tw/article/91628/optical-communication-concept-stocks 、TechNews https://technews.tw/2026/03/17/tawian-optical-communication-industry/

**環節3（自選補充，證據最扎實的兩塊）：液冷散熱＋ABF載板**
- 【液冷散熱，事實】滲透率快速攀升：不同報告估計2025年約33%、2026年53-76%（**不同來源估計數字分歧達20個百分點以上,需並列**,來源：豐雲學堂兩篇分別引用53%與76%）；驅動力是NVIDIA Blackwell架構單櫃功耗突破百kW門檻。**奇鋐**在GB200/GB300水冷板市占40-50%,2026Q1營收年增翻倍,**2026Q1毛利率29.77%,Q2進一步墊高至約32.57%**（單季+2.8個百分點）；**雙鴻**打入Meta/AWS/微軟供應鏈,已取得NVIDIA GB300液冷認證,**高盛預估**（非已實現數字）2025/2026/2027毛利率各為28.6%/31.1%/31.4%,毛利率提升主因是ASIC專案客製化程度較高。來源：財報狗 https://statementdog.com/analysis/3017/profit-margin 、豐雲學堂 https://www.sinotrade.com.tw/richclub/industry/AI%E4%BC%BA%E6%9C%8D%E5%99%A8%E6%B0%A3%E5%86%B7%E8%BD%89%E5%90%91%E6%B6%B2%E5%86%B7%E6%95%A3%E7%86%B1-%E6%BB%B2%E9%80%8F%E7%8E%87%E7%AA%81%E7%A0%B450--%E5%A5%87%E9%8B%90-%E9%9B%99%E9%B4%BB-%E5%8F%B0%E9%81%94%E9%9B%BB%E7%AD%896%E6%AA%94%E4%BE%9B%E6%87%89%E9%8F%88%E5%8F%97%E6%83%A0-%E7%94%A2%E6%A5%AD%E7%86%B1%E8%A9%B1-6a5ee249a57c1ee53e18cc87
- 【ABF載板，事實】2026年ABF載板由「供過於求」轉為「供不應求」,2027年進一步擴大缺貨；交期從3-4個月拉長到12個月；長約價格估每季調漲10-15%,現貨價每季漲逾20%；驅動力是AI伺服器CPU需求比重快速攀升（含代理式AI架構轉變）。**欣興**高階ABF技術僅次龍頭Ibiden,同步布局CPO/光通訊mSAP/玻璃核心載板/CoWoP,年底前ABF產能擴充約40%,**法人估2026Q3毛利率升至25.4%（預估數字,非已實現）**。來源：豐雲學堂 https://www.sinotrade.com.tw/richclub/hotstock/2026%E5%B9%B4%E8%BC%89%E6%9D%BF%E7%94%A2%E6%A5%AD%E5%85%A8%E9%9D%A2%E5%BE%A9%E7%94%A6-%E6%AC%A3%E8%88%88%E9%A0%98%E8%BB%8DABF%E6%97%8F%E7%BE%A4%E5%BC%B7%E5%8A%9B%E5%8F%8D%E5%BD%88-%E9%AB%98%E9%9A%8E%E9%81%8B%E7%AE%97%E9%9C%80%E6%B1%82%E5%BC%95%E7%88%86PCB%E6%96%B0%E4%B8%80%E6%B3%A2%E6%88%90%E9%95%B7-%E8%82%A1%E5%B8%82%E8%A9%B1%E9%A1%8C-6965c7ca25b05425f58beaee

**環節4（額外發現，與第九、十節高度相關，值得特別點名）：ASIC IC設計服務——本次查證毛利率數字最高的環節**
- 【事實】**世芯-KY（Alchip）**：2026Q1毛利率**50.16%**,創單季歷史新高,季增7.86%、年增27%；受惠北美CSP大客戶N3 AI加速器即將放量出貨,預期Q3起營收獲利強勁季增,全年毛利率持續向上,2026-2029受惠3nm/2nm接力有強勁成長動能。這家公司的角色，正是第九節Google TPU案例裡「Broadcom把Google架構轉化為可製造ASIC」在台灣的對應（IC設計服務／協助CSP完成晶片設計到量產的橋樑）。來源：豐雲學堂 https://www.sinotrade.com.tw/richclub/hotstock/%E4%B8%96%E8%8A%AF-KY%E6%B3%95%E8%AA%AA%E6%9C%83-%E9%A6%96%E5%AD%A3EPS-17-55%E5%85%83-%E6%AF%9B%E5%88%A9%E7%8E%87%E5%89%B5%E6%AD%B7%E5%8F%B2%E6%96%B0%E9%AB%98-N3-AI%E5%8A%A0%E9%80%9F%E5%99%A8%E7%AC%AC%E4%B8%89%E5%AD%A3%E7%88%86%E9%87%8F-%E4%B8%8B%E5%8D%8A%E5%B9%B4%E7%87%9F%E6%94%B6%E8%BF%8E%E7%88%86%E7%99%BC%E6%88%90%E9%95%B7-%E8%82%A1%E5%B8%82%E8%A9%B1%E9%A1%8C-69fdaa684d59ab006c422047
- 【風險提醒，事實】同一批來源也指出：AI ASIC量產牽涉晶圓代工、封測、IP授權與設備產能多環節,任一環節交期/成本偏離假設,都可能壓縮毛利率或迫使公司調整接單策略——**這是集中度風險，客戶數少、單一大案量產時程若延遲，對財報影響會被放大**。

### 11.2 子題B：高毛利且隔絕應用層價格戰的觀察清單

**篩選邏輯**：優先納入(a)有結構性稀缺性/轉換成本證據、(b)有本次查證到的實際或近期財報毛利率數字佐證、(c)收入來源是AI基礎建設資本支出本身（機櫃/晶片/電力/封裝需求量），不是AI應用服務的終端定價，因此不直接暴露在OpenAI/Anthropic式的應用層降價競爭之下。**明確排除**：ODM機櫃組裝廠（廣達4.78-5.02%、緯穎7.55%、鴻海6.18%——本次查證證實此環節結構性低毛利，即使卡位ASIC機櫃也未改變，見10.3節銜接說明）；AI應用層/模型公司（OpenAI、Anthropic——見第八、九節，年虧損約$140億美元量級，且已出現降價/取消漲價的競爭壓力，是本觀察清單刻意要避開的風險段本身）。

| 公司 | 所屬環節 | 毛利率／獲利數字（來源） | 護城河強度 | 隔絕應用層價格戰程度 |
|---|---|---|---|---|
| 台積電(2330) | 晶圓代工／CoWoS先進封裝 | 67.7%（2026Q2實際，Q3估降至~65%因2nm量產稀釋，屬製程轉換正常現象）／BigGo Finance | **極高**——CoWoS產能稀缺、製程領先多年、客戶轉換成本極高 | **高**——代工收入不取決於哪家AI模型商在應用層贏,只要有人在建資料中心就有需求 |
| 世芯-KY(3661) | ASIC IC設計服務 | **50.16%**（2026Q1實際，創單季新高）／豐雲學堂 | 高——設計服務門檻高,與CSP客戶深度綁定 | 高——收入來自晶片設計/量產服務費,非AI應用定價；**但需留意客戶與專案集中度風險** |
| 南亞科(2408) | DRAM記憶體 | **67.9%**（2026Q1實際，較上季+18.9個百分點）／經濟日報 | 中——排擠效應下傳統DRAM報價強勢,但本質仍是循環財，2025全年EPS僅2.13元、2026上半年即達23.07元，波動極大 | 高，但**暴露在記憶體景氣循環風險**，非應用層價格戰 |
| 華邦電(2344) | DRAM／利基記憶體 | **66.2%**（2026Q2實際，上季53.4%）／CMoney財報 | 中，同上——循環財性質，且部分獲利來自出清過去低價庫存,非全部反映當期新增需求 | 高，同上，暴露記憶體循環風險 |
| 台達電(2308) | AI伺服器電源／液冷骨幹 | **37.0%**（2026Q1實際，創歷史新高，營益率17.8%同創新高） ／工商時報 | 中高——AI伺服器電源市占60%,品牌與系統整合能力強 | 高——電源需求跟機櫃數量掛鉤,不受應用層定價戰影響 |
| 華城電機(1519) | 電力變壓器／重電 | **42.2%**（2025Q4實際）／readmo.cmoney.tw | 中高——變壓器交期拉到2.5年，矽鋼片瓶頸短期難解 | 高——電網/資料中心供電需求，與AI應用定價無關 |
| 奇鋐(3017) | 液冷散熱（水冷板） | **29.77%→32.57%**（2026Q1→Q2實際）／財報狗 | 中——GB200/300水冷板40-50%市占，但雙鴻等對手緊追，機構件業競爭相對激烈 | 高——液冷需求跟機櫃功耗掛鉤 |
| 欣興(3037) | ABF載板 | 約**25.4%**（2026Q3法人預估，**非已實現數字**）／豐雲學堂 | 中高——技術僅次Ibiden，供給結構性吃緊到2027 | 高——載板需求跟晶片顆數/記憶體搭載量掛鉤 |
| SK海力士（**非台股，僅供比較參考**） | HBM記憶體 | **76%營業利益率**（2026Q2實際，創紀錄）／SK hynix官方 | 高——HBM市占50-55%，技術與良率門檻高 | 高，但同樣暴露記憶體循環風險；**提醒：非台灣證交所掛牌，僅作為理解台廠南亞科/華邦電所處產業環境的參照，不是可直接透過台股帳戶投資的標的** |

**共9檔（含1檔非台股參考），未超過12檔上限，寧缺勿濫。**

### 11.3 未查證清單（有被提及但查無具體財報數字支持，不放入正式觀察清單）

- **中興電工(1513)**：訂單能見度最長（喊到2032年，在手訂單約440億台幣），但本次查證未找到具體毛利率數字
- **雙鴻**：僅有高盛分析師預估毛利率（28.6%/31.1%/31.4%，2025-2027E），非已實現財報數字，方向正面但證據強度弱於奇鋐
- **聯亞**：確認簽下InP基板五年長約（上游原料保供角色明確），但毛利率數字未查到
- **波若威、華星光**：確認在耦光元件/光收發模組領域布局，但毛利率數字未查到
- **智原(GUC)**：與世芯-KY同屬ASIC設計服務類股，市場常並列討論，但本次查證未找到其具體最新毛利率數字
- **GE Vernova**：查到的是電氣化部門EBITDA margin展望（18-20%），非毛利率（gross margin）數字，兩者定義不同不可直接比較，故未列入主表
