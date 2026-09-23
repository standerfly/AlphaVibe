# 台股 Edge AI／邊緣運算供應鏈研究筆記（2026-08-31 整理）

研究起點：一段 ChatGPT 對話紀錄（分享連結）
https://chatgpt.com/share/6a94d916-6294-83ee-b976-3d11a123092a
（標題：「分析邊緣運算供應鏈」，對話內容標註至 2026/8/31）

**追加內容**（同一段對話的延伸提問，使用者於同日補追加）：
https://chatgpt.com/share/6a9517ad-a500-83e9-b33e-50610fe75fe1
（追問「請分析雲端或邊緣都會需要的供應鏈」，見第八節）

**性質說明**：這份筆記不是我自己執行的多來源網頁研究，而是對**既有一份 ChatGPT 對話**的完整解析與結構化摘要——該對話本身包含 assistant 的網頁搜尋與財報數字引用，但這些數字未經本次整理再次向原始來源查證，一律照對話原文轉述，並保留原文自己標註的信心程度與矛盾點。

已發布 Artifact（排版版，含目錄導覽、投資雷達分級卡片、10檔公司財報比較表）：
https://claude.ai/code/artifact/ff96d1de-7969-491b-a49a-cc66a8ba8d60

---

## 一、原始問題與對話結構

使用者原始問題（對話開場）：
> AI雲端運算的市場目前已有一定的規模且市場供應鏈架構相對清晰。請分析邊緣運算的技術趨勢與市場供應鏈。

對話共經歷六個階段（第 5、6 階段為同日追加內容，見第八節）：

| 階段 | 內容 | 對話中的角色 |
|---|---|---|
| 1 | 邊緣運算技術趨勢與供應鏈全景第一版分析 | assistant 完整回答 |
| 2 | 使用者貼上一篇工商時報／IT系統供應鏈報導（IPC×邊緣AI雙動能） | 使用者提供的原始文章 |
| 3 | assistant 根據補充資料做出**投資主軸修正** | assistant 修正分析 |
| 4 | 整合為「2026/8/31 台股 Edge AI 投資地圖 V1」 | assistant 最終產出 |
| 5 | 使用者追問「請分析雲端或邊緣都會需要的供應鏈」，assistant 給出六大共同供應鏈初版分析 | assistant 完整回答 |
| 6 | assistant 把分析「再往前推一層」，產出 Cloud × Edge Common Supply Chain 最終版 | assistant 最終產出 |

---

## 二、技術趨勢核心論點

**核心命題**：邊緣運算正處於轉折點，從「把雲端伺服器搬到使用者附近（Edge Server）」演變成「AI 直接進入設備與物理世界（Edge AI / Physical AI）」。

- **Cloud AI vs Edge AI 的本質差異**：Cloud AI＝大型集中式算力基礎建設（GPU／HBM／Server／Networking）；Edge AI＝大量分散式「感知→推論→決策→執行」節點（AI SoC／Memory／IPC／Sensor／Networking／Industrial Automation／Robotics／Power／Software／Cybersecurity）。
- **驅動力**：不是「雲端不夠快」，而是特定應用必須立即做決策、不能把資料送去雲端再等答案回來——工業機器人、自動駕駛、AMR、人形機器人、智慧攝影機、AOI、無人商店、智慧醫療、無人機、車內AI、智慧電網。Qualcomm 對 Industrial Edge AI 的定位也強調降低 latency、bandwidth cost。
- **雲端不會被取代，是 Cloud + Edge Continuum**：簡單即時查詢在裝置端直接回答；複雜規劃型查詢交給雲端。
- **技術演進四階段**：Cloud Computing → Edge Server → Edge AI → **Physical AI**（AI 開始控制物理世界：Perception→Reasoning→Planning→Action→Robot/Vehicle/Machine）。NVIDIA 力推 Jetson Thor／Physical AI／Robotics 即押注此方向；研華已將 Jetson Thor 用於機器人、智慧製造、物流。
- **六個技術主軸**：
  1. **NPU/AI Accelerator**：Edge 的瓶頸是 Performance/Watt，不一定需要 NVIDIA GPU，SoC＋NPU＋ASIC＋GPU＋MCU 都可能存在。
  2. **Memory**：Cloud AI 靠 HBM，Edge AI 則是 LPDDR/DDR/eMMC/UFS/NAND/NOR/SRAM 重要性上升，尤其 Edge 裝置開始跑 LLM/VLM/多模態時，「Edge AI ≠ 低階 MCU 市場」。
  3. **AI Model Compression**：Quantization/Pruning/Distillation/Sparse model/MoE/TinyML，讓百億參數模型壓縮到能在 Edge 端跑。
  4. **Edge + Cloud Hybrid AI**：Edge 不會取代 Cloud，最終是協同架構。
  5. **Networking（5G/Wi-Fi 7/8/Ethernet/TSN）**：Edge AI 設備數量龐大，對網路需求會爆發。
  6. **Physical AI**：GenAI→Agentic AI→Physical AI 是連續技術路線，核心是 AI 能不能「看、想、動」。
- **市場規模【原文引用，未經本次再查證】**：ABI Research（2026 Q2 資料）估全球 Edge AI chipset 市場 2026 年約 **US$34.4B**，2031 年約 **US$96B**（約 5 年成長近 2.8 倍；僅 chipset 市場，不含 IPC／機器人／網通）。
- **商業模式變化**：Edge AI System 有機會從「賣一次性硬體（IPC）」轉為「Hardware + Software + Fleet Management + OTA + Subscription」。
- **資安成為核心零組件**：Edge 端「100,000 devices = 100,000 attack surfaces」，且 AI Model 本身就是資產，需要 Secure Boot、TPM、Hardware Root of Trust、Model encryption。

---

## 三、中途的關鍵修正（本篇對話最有價值的動態）

**修正前（第一版分析）**：
- 投資主軸放在 **AI SoC／AI Compute 層**（NVIDIA、Qualcomm、MediaTek、AMD、Intel）為 Tier 1，IPC（研華）列為 Tier 2 Edge System Integrator。
- 台灣供應鏈分層表把「AI SoC（聯發科）」與「Edge AI/IPC（研華）」並列最高評等，未特別排序孰輕孰重。
- 論述停留在產業架構與技術趨勢層次，尚無具體財報數字佐證。

**觸發修正的補充資料**（使用者提供的原始文章，工商時報／記者杜念魯）：
- 全球 IPC 產值 2025 年約 61 億美元 → 2030 年 89.1 億美元，CAGR **7.9%**。
- 全球邊緣 AI 市場 2025~2032 年 CAGR 高達 **33.5%**（此數字後續被 assistant 查核並提出保留，見第五節）。
- 研華 B/B ratio 從 2025 年的 1.01~1.33 區間，加速攀升到 2026 年 Q1 **1.77**、Q2 **1.44**、7 月再升至 **1.64**。

**修正後**：
- assistant 明確表示：「我現在會把 Edge AI 的投資主軸從『AI晶片』往下移到『AI邊緣系統／IPC／Physical AI』」，理由是**真正開始看到訂單與財報兌現的已經不是晶片，而是 IPC 廠**。
- 排序邏輯改成「AI成長速度 × 台廠競爭優勢 × 財報兌現 × 未來市場空間」，改把研華（Edge AI System）列為第一梯隊。
- 強調「研華 B/B Ratio 與 AI 營收占比，是比單純市場 CAGR 更有價值的訊號」——即從「產業級總體數字」轉向「個別公司財報驗證」的研究方法論轉變。
- 結論轉折句：「Edge AI 不只是『產業故事』，已經開始進入財報。而這比市場研究機構說『2032 CAGR 33.5%』重要得多。」

---

## 四、供應鏈與公司分級全景

### 4.1 第一版（修正前）台灣 Edge AI 供應鏈分層表

| 層級 | 代表公司 | 評分 |
|---|---|---|
| AI SoC | 聯發科 | ★★★★★ |
| Edge AI / IPC | 研華 | ★★★★★ |
| Edge AI IPC | 樺漢、AAEON相關 | ★★★★ |
| Edge Server | 緯穎 | ★★★★ |
| Edge / AI Server | 廣達、緯創、英業達 | ★★★ |
| Power | 台達電 | ★★★★ |
| Networking | 智邦、啟碁等 | ★★★★ |
| Memory | 南亞科、華邦電等 | ★★★ |
| PCB | 欣興、金像電等 | ★★★ |
| Sensors / Camera | 未具名 | ★★★★ |
| Robotics / Automation | 台達、研華、上銀等 | ★★★★ |

此版本把研華 2026/7 推出的 AIR-075（Jetson Thor＋4×10GbE＋multi-camera＋Agentic AI＋Vision AI＋Robotics＋Factory automation，並開始納入 Edge AI fleet／model lifecycle management）作為 Edge AI/IPC 樣板案例，並提醒「有 Edge AI 業務」不等於「Edge AI 是主要獲利來源」。

### 4.2 修正後分級（尚未附完整財報數字）

修正核心：投資主軸從「AI晶片」下移到「AI邊緣系統／IPC／Physical AI」，因為真正開始有訂單與財報兌現的是 IPC 廠。

| 梯隊 | 公司（代號） | 定位 |
|---|---|---|
| 第一梯隊：Edge AI System | **研華 2395** | 最完整 Edge AI pure-play proxy：IPC+Embedded+AI Box+Robot+WISE+WEDA+System Integration，已有財報驗證 |
| 第二梯隊：Physical AI/Robotics Edge | **凌華 6166** | Machine Vision + Motion Control + Edge AI + Robotics，搭配 NVIDIA IGX Thor/Jetson Thor 平台 |
| 第三梯隊：Embedded Edge AI | **研揚 6579、威強電 3022、艾訊 3088、融程電 3416、安勤 3479、宸曜 6922** | Edge AI 可直接嵌入原有產品，ASP 可能從傳統 IPC 的 100 提升到 150~250（或更高） |

- **研華財報數字**：2026 Q2 營收 261.26億，YoY +46%，毛利率 37.7%，營益率 19.6%，EPS 5.20，稅後淨利 YoY +127%；上半年營收 465.12億，YoY +32%，毛利率 38.3%，營益率 19.0%，EPS 9.05，淨利 YoY +66%。
- **研華 B/B Ratio**：Q1 1.77，Q2 1.44。
- **研華 Edge AI 營收占比**：從約 15% 提升至 Q1 約 20.5%，公司目標年底提高到約 30%（**assistant 原文自行加註**：此數字「不會直接視為完全獨立驗證的官方數字，但方向值得高度重視」）。
- IPC 分三類（成長性／毛利潛力／投資評價）：傳統IPC（★★／★★／週期股）、AI IPC（★★★★／★★★★／成長股）、AI+Robotics+Software（★★★★★／★★★★★／最值得研究）。
- 提出 **Edge AI Score** 公式：AI營收占比 × AI營收成長率 × ASP提升 × B/B Ratio × Design Win × 毛利率 × Robotics exposure × Software revenue。B/B 判讀基準：1.0正常、1.2健康、1.4強勁、1.7+非常強。
- 風險提示（**引用來源為「部分券商研究」，非 assistant 自行驗證**）：「樺漢的成本轉嫁能力」與「凌華的毛利壓力」被列為觀察重點。

### 4.3 最終版：台股 Edge AI 投資地圖 V1 主表——2026 H1 財報比較

| 公司 | 代號 | 核心定位 | H1營收YoY | H1毛利率 | Edge AI 潛力 | 評價 |
|---|---:|---|---:|---:|---:|---|
| 研華 | 2395 | Edge AI / IPC / IWS | +32% | 38.3% | ★★★★★ | **A+** |
| 研揚 | 6579 | Embedded / Edge AI / Robot | +28.7% | 34.5% | ★★★★★ | **A** |
| 融程電 | 3416 | Rugged Edge / AI | +30.4% | 38.6% | ★★★★☆ | **A** |
| 宸曜 | 6922 | Edge AI / AMR / Robot | +35.6% | 40.1% | ★★★★★ | **A-** |
| 凌華 | 6166 | Vision / Motion / Edge AI | +41.1% | 34.6% | ★★★★★ | **A-** |
| 樺漢 | 6414 | Industrial System / AI | +23.6% | 19.7% | ★★★★☆ | **B+** |
| 艾訊 | 3088 | IPC / Automation / AI | +41.8% | 33.1% | ★★★★☆ | **B+** |
| 威強電 | 3022 | Edge / AI / Medical / Robot | +18.8% | 27.9% | ★★★★☆ | **B** |
| 廣積 | 8050 | IPC / Network Edge | +9.4% | 24.9% | ★★★☆ | **B-** |
| 安勤 | 3479 | Medical / Edge AI | +13.6% | 約26.0% | ★★★☆ | **B-** |

**各公司細節數字（原文逐一列出）：**

- **研華 2395**：H1 營收+32%、毛利率38.3%、營益率19.0%、EPS+66%。8/28 收盤 669元，近四季 EPS 15.82元，PER 約 42.3倍。2026年策略明確納入 AI-driven smart manufacturing、AI operation decision、AI infrastructure、Edge AI、Agentic AI、Physical AI（WISE/WEDA/IWS 架構）。
- **研揚 6579**：H1 營收 52.28億，YoY +28.7%，毛利率 34.52%，EPS 6.15元；7月營收 9.14億，YoY +28.16%，累計前7月 YoY +28.66%。機器人專案涵蓋全球前三大機械手臂廠、AMR、保全機器人、自駕農業機械。8/28 股價約 147元，PER約 20倍。
- **融程電 3416**：H1 營收 21.23億，YoY 約 +30.4%，毛利率 38.55%，EPS約 4.16元（單季Q2 EPS 2.48）。定位「Rugged Edge AI」（工業/軌道/國防/車載/戶外），視為 Edge AI 中的高毛利 niche player。
- **宸曜 6922**：H1 營收 11.36億，YoY約 +35.6%，毛利率 40.05%（此批公司中最高）。聚焦AI+Robotics+AMR+Edge Computing，MoneyDJ 產業整理列為機器人/AMR受惠公司。8/28 股價 208.5元，PER約 21.8倍。規模較小，單一客戶/專案變化影響較大，定位「高成長、高波動」。
- **凌華 6166**：H1 營收 79.03億，YoY約 +41.1%，毛利率 34.55%（去年同期34.69%，幾乎沒有增加——營收爆發但毛利未同步擴張，是評 A- 而非 A+ 的原因）。定位「Vision + Motion + AI」。8/28 股價 116.5元，PER約 22.3倍。
- **樺漢 6414**：2026 H1 營收 85.49億（去年同期69.16億），約 +23.6%，毛利率 19.66%（此批中最低）。8/28股價 390元，近四季EPS 24.75，PER約 15.76倍（此批中最低）。定位「Industrial System Integration」而非純Edge AI成長股，潛力來自Hardware+Software+System Integration+ESaaS+Industrial AI。
- **艾訊 3088**：H1 營收 46.13億，YoY約 +41.8%（此批中成長最快之一）、毛利率 33.09%。8/28股價約 124元，PER約 15.5倍——被assistant稱為「可能比市場最愛的研華更有預期差」，但同時提出待追蹤問題：AI營收占比多少？AI營收增速多少？Robotics/Vision是否成為主要成長來源？
- **威強電 3022**：H1 營收 40.82億，YoY約 +18.8%，毛利率 27.88%（去年同期33.75%，下降 -5.87個百分點——被列為「財報警訊」）。產品線正確（2026推出GAIA-5000：NVIDIA Jetson Thor+iRM，主打智慧製造與機器人；NANO-X100：AMD Ryzen AI Embedded X100，用於AMR/Edge AI Vision），但獲利面出現「營收增、毛利降」的警訊模式。
- **廣積 8050**：H1 營收 33.34億，YoY約 +9.4%（此批中最慢），但毛利率由 22.55% 提升到 24.93%——歸類為「成長較慢、獲利改善」類型。
- **安勤 3479**：H1 毛利率「約26.0%」——**此數字只出現在主表，原文未找到對應的詳細段落與引用來源說明**（見第六節內容缺口）。

**四象限定性定位圖**（原文標註「這是一個定性定位圖，不是量化股價預測」）：
- 高毛利＋AI成長高：宸曜、艾訊
- 高毛利＋AI成長低：融程、凌華
- 低毛利＋AI成長高：研華、研揚
- 低毛利＋AI成長低：樺漢、威強電

---

## 五、估值與觀察指標

**市場規模數字的多重版本（assistant 核對使用者文章數字後列出，並列呈現不同來源）**：
- 使用者文章：IPC 2025年61億美元→2030年89.1億美元，CAGR 7.9%（assistant 核對後認為與 Research and Markets / The Business Research Company 資料一致）。
- 使用者文章：Edge AI CAGR 33.5%（2025~2032）。
- Market Glass（2026）：Edge AI 2025年239億美元→2032年839億美元，CAGR 19.7%，其中 hardware CAGR約 17.7%。
- 另一份研究對 Edge AI devices 的定義：2025~2031 CAGR約 25.4%。
- 「Edge AI accelerator」定義：CAGR約 32.7%。
- **assistant 結論**：不應把 33.5% 直接視為整個 Edge AI 產業 CAGR，重點不在於精確百分比，而在於「Edge AI 成長速度明顯高於傳統IPC，且台灣IPC廠正把這個成長轉化成訂單與營收」。
- IoT 市場 CAGR 2024~2029：15.12%。

**個股觀察指標**：
- **B/B Ratio（訂單能見度）**：研華 2025年1.01~1.33 → 2026 Q1 1.77 → Q2 1.44 → 7月1.64；Q2北美更達1.92。
- **Edge AI 營收占比**：研華約15%→Q1約20.5%→年底目標約30%（精確度未完全確認，見上）。
- **毛利率趨勢**：assistant 反覆強調「AI營收增加 ≠ EPS一定大增」，若「AI營收+50%但毛利率-5%」可能只是「營收漂亮、獲利沒同步」——威強電（毛利率年減5.87個百分點）被列為此陷阱的實例案例。
- **Forward PE**：研華約42.3倍（669元）；研揚約20倍（147元）；宸曜約21.8倍（208.5元）；凌華約22.3倍（116.5元）；樺漢約15.76倍（390元）；艾訊約15.5倍（124元）。
- **Edge AI Score 公式**：= AI營收占比 × AI營收成長率 × ASP提升 × B/B Ratio × Design Win × 毛利率 × Robotics exposure × Software revenue。
- **Design Win 生命週期**：Design Win → Certification → Pilot → Mass Production → Revenue，assistant 認為這比單季營收更重要，因為導入週期可能很長。
- **AI Revenue Growth vs Total Revenue Growth 要分開看**：例如「營收+40%但AI營收+10%」不算Edge AI成長股；「營收+25%但AI營收+80%」反而可能是更好標的。
- **最終選股框架（Edge AI × 跌深補漲）**：
  - 基本面：①H1營收YoY>20% AND ②EPS YoY>20% AND ③毛利率沒有惡化 AND ④AI/Robotics營收持續增加 AND ⑤B/B>1
  - 股價：⑥股價距離近期高點 -15%~-30%
  - 籌碼：⑦外資沒有長期大幅撤出
  - 最後才看：⑧Forward PE < 同族群平均
- **建議建立的 Edge AI Scorecard 指標清單**：Edge AI營收占比、AI營收CAGR、B/B、毛利率趨勢、2026/27 EPS、Forward PE、近高點回撤幅度、外資持股變化 → 用於得出四類分法：「目前最值得等待回檔買入」「基本面最強但太貴」「股價已反映」「營收漂亮但獲利沒有兌現」。

---

## 六、最終結論／2026/8/31 台股 Edge AI 投資地圖 V1（原文完整分級結構）

原文開頭結論句：
> 目前我最關注的不是「哪家IPC最純」，而是「哪家公司正在從傳統IPC升級成Edge AI/Physical AI平台」。

### 6.1 開場總結分級

- **第一梯隊**：研華、研揚、融程電、宸曜、凌華
- **樺漢**：屬於低估值但商業模式較複雜的系統整合型
- **威強電、艾訊、廣積、安勤**：則需要等待 AI/機器人業務進一步證明

### 6.2「如果現在只能選5家」排名（原文標註：以產業趨勢×財報×未來成長×估值綜合，非推薦買賣）

1. 🥇 **2395 研華**——「產業龍頭」。優點：產業地位+AI平台+Software+Robotics+財報；缺點：估值高（PER約42倍）。
2. 🥈 **6579 研揚**——「高成長/合理估值」。優點：H1+28.7%、毛利34.5%、Robot/AMR；PER約20倍，assistant表示「我會高度關注」。
3. 🥉 **3416 融程電**——「高毛利Edge AI niche」。優點：H1+30%、毛利38.6%，Industrial/Rugged具護城河。
4. ④ **6922 宸曜**——「高成長Physical AI」。優點：營收+35.6%、毛利40%，Robot/AMR exposure高；風險是規模小、波動大。
5. ⑤ **3088 艾訊**——「可能的預期差」。H1+41.8%但PER約15.5倍，若後續證明AI/Robotics營收高速成長，市場可能重新評價。

**另立「價值重估組」**：**6414 樺漢**——PER15.8倍但有Industrial AI+System Integration+ESaaS，潛在催化劑鏈：AI Revenue↑→Software Revenue↑→毛利率↑→EPS↑→PE re-rating，估值可能從15x→20x。

### 6.3 Edge AI 投資雷達（三層 Level 分類）

- **Level 1：已經兌現** —— **研華**（目前最強）
- **Level 2：正在高速兌現** —— **研揚、融程電、宸曜、凌華、艾訊**（assistant表示這一群才是現在最想找「股價尚未完全反映EPS成長」的候選）
- **Level 3：轉型觀察** —— **樺漢、威強電、安勤、廣積**（主要看AI營收占比是否突破、毛利率是否改善）

> **注意**：艾訊 3088 在此 Level 2 分類與 6.1 節「需等待證明」分類**互相矛盾**，原文未自行調和，詳見第六節末「內容缺口與矛盾標注」第 1 點。

### 6.4 各公司一句話總評

- 研華：基本面最強，但估值太高
- 研揚：基本面強、估值中等
- 融程：成長＋高毛利
- 宸曜：成長非常強，但波動較高
- 艾訊：成長很快＋估值低，可能存在預期差
- 樺漢：估值低，但必須等AI營收與毛利率改善證明

### 6.5 產業鏈延伸方向

assistant 認為下一階段研究重點會從 IPC 往下游延伸：**研華/研揚/凌華 → 伺服器→Vision→Motion Control→Servo→Motor→Robot**。並引用「MoneyDJ 今年整理IPC×Robot供應鏈」，將凌華、研華、艾訊、泓格、威強電、樺漢、宸曜、研揚、新漢等公司納入不同機器人環節（**泓格、新漢**兩家公司僅在此處提及一次，全篇無任何數字，屬「有名字但無數字」）。

### 6.6 下一步建議

原文建議把 10 家公司（**2395、6579、3416、6922、6166、3088、6414、3022、3479、8050**）做成「Edge AI Scorecard」，指標見第五節。

---

## 七、內容缺口與矛盾標注（誠實列出，非本次整理新發現，均為原文自帶的不確定性或矛盾）

1. **艾訊 3088 的分類前後不一致**：對話最後一則訊息內，開場總結段落把艾訊列入「需要等待AI/機器人業務進一步證明」一組；但同一則訊息稍後的「如果現在只能選5家」把艾訊排進第5名正面推薦（「可能的預期差」），「Edge AI投資雷達」也把艾訊列在 **Level 2：正在高速兌現**（與研揚、融程電、宸曜、凌華同組，明確不與樺漢/威強電/安勤/廣積的Level 3同組）。同一份文件內至少出現三套分類邏輯，對艾訊的定位前後矛盾，原文未自行說明或調和這個差異。
2. **Edge AI CAGR 33.5%（使用者提供文章的核心數字）**：assistant 自行查核後認為此數字很可能是「某個較窄、較高速成長的 Edge AI 市場定義」下的結果，與其他來源給出的 19.7%／25.4%／32.7% 等版本並列但不一致，assistant 明確表示「不應直接視為整個Edge AI產業CAGR」——這是原文自己承認的不確定性。
3. **研華 Edge AI 營收占比（15%→20.5%→目標30%）**：assistant 原文自行加註「我不會直接視為完全獨立驗證的官方數字，但方向值得高度重視」，屬於原文自我標註的低確信度數字。
4. **安勤3479 H1毛利率「約26.0%」**：只出現在主表格中，逐一介紹各公司財報的段落並未包含安勤的詳細數字與來源說明，是主表格裡唯一缺少對應細節段落佐證的公司。
5. **「樺漢的成本轉嫁能力」與「凌華的毛利壓力」**：assistant 註明引用來源是「部分券商研究」，屬於間接引用，非 assistant 自行驗證的一手數字。
6. **泓格、新漢**：僅被提及一次（引用「MoneyDJ產業整理」），全篇沒有這兩家公司的任何財務數字、代號或分級評價。
7. **市場規模數字單位**：使用者原文「全球IPC產值2025年約61億美元」，已照抄原文用字，未做單位換算或改寫。
8. **樺漢 6414 分類的演變**：修正稿（第四節4.2）並未把樺漢明確列入其三梯隊架構中任一層，只在「下一步建議拆解」的10家公司名單中出現；到了最終版才明確把樺漢獨立列為「低估值但商業模式複雜的系統整合型」／「價值重估組」／Level 3。這是 assistant 對樺漢的分類在對話後期才明確定型，屬於演變而非矛盾，特此註記供參考。

---

## 八、追問延伸：Cloud AI × Edge AI 共同供應鏈（2026-08-31 同日追加）

> 延續前七節（IPC/Edge AI 純度視角），使用者同日追問：「請分析雲端或邊緣都會需要的供應鏈」。這是**互補視角，不是取代或推翻**前七節的 Edge AI 投資地圖——前七節找「Edge AI 純度最高」的公司，本節找「不管 Cloud 或 Edge 誰勝出，都吃得到」的共同底層供應鏈。**未重新查證前七節已確認的內容**。

### 8.1 核心論點：為什麼「共同供應鏈」比「Edge AI 受惠股」更重要

原文開場點出動機：
> 「這個問題其實比『Edge AI 哪些公司受惠』更重要。因為如果把 Cloud AI 與 Edge AI 的共同需求抽出來，就能找到一批『不管 AI 運算最後放在資料中心、企業端、工廠、車輛或機器人，都會吃到』的供應鏈……**不必押注 Cloud 或 Edge 哪一條路最後勝出。**」

論證邏輯：
1. Cloud 與 Edge 架構不同（Cloud＝GPU/ASIC/CPU＋HBM/DDR/SSD；Edge＝NPU/AI SoC/MCU＋LPDDR/NAND/NOR），但底層需求高度重疊：Compute、Memory、Connectivity、Power、Thermal、PCB/Package 六項共同硬體底座。
2. 純押 Edge AI 概念股（如 IPC）其實是「Edge AI beta 很高」的單邊賭注；純押 HBM 則是押注「大型 Cloud AI」單邊。Power、Memory、PCB 這類公司「Cloud 與 Edge 兩邊都吃」，風險較分散。
3. 原文結論句：「Edge AI 概念股不一定是最安全的 AI 投資。反而，**Cloud + Edge 共通供應鏈，可能是更好的核心持倉池。**」
4. 最終版進一步收斂：建議把 Cloud AI vs Edge AI 的二分思考，升級成 **「AI Infrastructure Continuum」**（Cloud→Data Center→Enterprise→Edge Server→Edge Device→Robot/Vehicle→Physical AI 一路走），有一批供應鏈會沿途一路吃到，這才是「AI 運算下沉時，誰能一路吃到？」的關鍵問題。

### 8.2 共同供應鏈環節全景（依最終版排序，逐環節列出公司與數字）

**1. Power（電源）——最終版排名第 1，判定「目前最好的 Cloud+Edge 共通題材」**
- **台達電 2308**：2026 Q2 營收約 2,075 億、毛利率 36.3%、營益率 17.2%、EPS 7.32（Q1 EPS 3.60）。業務同時涵蓋 Data Center AI Server Power/HVDC/Liquid Cooling，以及 Edge/Factory 的 Industrial Automation/Robot/Power Management，稱為「Cloud + Edge + Industrial 三重 exposure」。
- **光寶科 2301**：2026 H1 營收 961 億、YoY +25%、毛利率 24.7%、營益率 12.8%、EPS 4.80、淨利 YoY +66%；Q2 單季 EPS 3.14，YoY **+126%**。公司表示 AI 相關營收占比全年可望突破 30%，雲端相關業務 Q2 年增超過七成；2026 CapEx 上修到 180 億元，並在美國布局 HVDC Power Rack。原文把光寶從「傳統電源股」重新定義為「AI Power Infrastructure」。
- （初版另補充：Delta 在 2026 COMPUTEX 同時展示 Data Center 的 800VDC/90-110kW power shelf/CDU/liquid cooling，以及 Physical AI/Edge AI 的 multi-node Edge AI workstation，強調「同一家公司同時吃 Cloud 與 Edge」。）

**2. PCB／CCL／高速材料——排名第 2**
- **金像電 2368**：2026 H1 營收 435.92 億、YoY 約 +68%、毛利率 34.72%、EPS 約 16.14~16.17；Q2 營收 242.79 億，7 月營收首次突破 100 億。8/28 股價 1,130 元，PE 約 40.6 倍。原文警語：「基本面非常強，但市場已經知道這件事……EPS 還要增長多少，才能支撐 40 倍 PE？」
- **欣興 3037**：Q2 營收 429 億、YoY 約 +89%、毛利率 24.8%、EPS 8.45（Q1 EPS 3.28）。HDI+ABF+IC Substrate+AI，定位偏「Advanced Computing Infrastructure」。
- **台光電**：僅在供應鏈總表被列名，**全篇未給財報數字或代號**。

**3. Memory（記憶體）——排名第 3**
- **華邦電 2344**：2026 Q2 營收 598.43 億、YoY **+184.7%**、毛利率 **66.2%**、EPS 5.40。Custom Memory Solution（CMS）已占 Q2 營收 53%，平均 ASP 季增接近 100%。原文強調這是「AI→Custom Memory→高ASP→產品組合改善→毛利率→EPS」的財報兌現鏈。
- **旺宏 2337**：2026 前六個月營收約 295.9 億、YoY **+129%**；月營收 YoY 加速（1月+51%→6月+216%），7 月營收 77.25 億。原文提醒需追蹤「需求是真的 Edge AI，還是純粹 memory price recovery」，判定旺宏仍比華邦更偏「Memory cycle」性質。
- **南亞科**：僅在供應鏈總表被列名，**未給財報數字**。Micron（美股）、SK hynix、MediaTek（聯發科 Genio 420 搭配 LPDDR）亦被提及作為 Memory 需求例證，均無代號或數字。

**4. Semiconductor／Foundry／AI SoC——排名第 4（初版判定「S 級：最不需要押注 Cloud/Edge」）**
- **台積電 2330**：核心論點——TSMC 把 HPC 平台定義為支援 cloud-to-edge AI applications，整合先進製程、3DFabric、HBM、silicon photonics，因此「是『Cloud AI vs Edge AI』最不需要押注的一家公司」。**⚠️ 初版全篇未附台積電代號，代號只在最終版出現**，兩版對同一家公司的資訊完整度不一致。
- 上游國際公司（均無代號/數字）：AMD、NVIDIA、Intel、Qualcomm、NXP、Renesas；聯發科同列 AI SoC/ASIC 代表台股，亦無代號。

**5. Networking／Connectivity——排名第 5**
- **智邦 2345**：8/28 股價 2,125 元。核心優勢在 Cloud AI 的 800G/1.6T/AI Cluster，Edge AI 需求存在但占比較小——原文明確定位為「AI Infrastructure Core」而非「Edge AI Core」。
- 市場數字（非個股）：TrendForce 估 2026 年 AI-focused optical transceiver 市場達 260 億美元，較 2025 年成長逾 57%。啟碁同列代表台股，無數字。

**6. Thermal（散熱）——排名第 6**
- **奇鋐 3017**：H1 營收 981.59 億、YoY +85.46%、EPS 44.54；Q2 單季營收 491.21 億、YoY +65.98%。公司稱 2026 為「ASIC 元年」，散熱需求不再只依賴 NVIDIA GPU。
- **雙鴻 3324**：H1 營收 172.49 億、YoY +77.31%；7 月營收 YoY +117%；市場預期全年液冷占比可能達 60~65%。
- **健策 3653**：8/28 股價 5,785 元，PE **約 130.6 倍**。原文明確表示技術地位好，但「估值已經極度要求未來 EPS 持續超預期」，**不會放在目前最優先切入名單**。
- 市場數字：TrendForce 估 AI chip liquid cooling penetration 由 2025 年約 33% 提升到 2026 年約 53%，並從 GPU/CPU 擴展到網卡、Busbar/power board、光模組。

**7. Advanced Packaging——排名第 7**
- **日月光投控 3711**：2026 Q2 營收 1,911 億、毛利率 21%、營益率 11.1%、EPS 4.80（Q1 EPS 3.24）。同時推出 310×310mm panel-level packaging，支援 AI/HPC/networking/edge AI，新產線預計 **2027 年**量產。
- 台積電同時代表 Semiconductor 與 Advanced Packaging（CoWoS 整合 SoC+HBM）。

**8. Connector／Cable（僅初版總表出現，最終版未再展開）**
- **貿聯、嘉澤**：僅列名，**全篇無財報數字**（原文列表寫成「貿聯、嘉澤、貿聯等」，貿聯重複一次，判斷為原文行文瑕疵，如實照抄）。

**9. IPC／Edge System／Robotics（兩版均判定「非最純的共通供應鏈」）**
> 原文明確點出：「IPC 本身反而不是『最純的共通供應鏈』……它其實是『Edge AI beta 很高』的投資」——代表公司仍是前七節已列的研華、研揚、融程、宸曜、凌華、艾訊，**本輪未提供新財報數字**，僅重複列名於「Edge Beta」分組；威強電、廣積、安勤三家**本輪完全未被提及**。

### 8.3 與前七節（Edge AI 投資地圖）的關係

**全新公司**（前七節完全沒出現過）：

| 代號 | 公司 | 環節 |
|---|---|---|
| 2330 | 台積電 | 半導體代工／先進封裝 |
| 2308 | 台達電 | 電源 |
| 2301 | 光寶科 | 電源 |
| 2345 | 智邦 | 網通 |
| 2368 | 金像電 | PCB/CCL |
| 3037 | 欣興 | PCB/CCL |
| 2344 | 華邦電 | 記憶體 |
| 2337 | 旺宏 | 記憶體 |
| 3017 | 奇鋐 | 散熱 |
| 3324 | 雙鴻 | 散熱 |
| 3653 | 健策 | 散熱 |
| 3711 | 日月光投控 | 先進封裝 |

另有多家**有名字但原文未附代號**（南亞科、台光電、貿聯、嘉澤、啟碁）及非台股國際公司（AMD/NVIDIA/Intel/Qualcomm/NXP/Renesas/Micron/SK hynix，聯發科為台股但原文本身也未附代號）。

**前七節已出現、本次補充內容的公司**：僅**樺漢 6414** 有新的質性論述——重申「可能被市場錯誤分類」，若 AI Software/System Integration 占比上升可能出現「EPS growth + PE re-rating」雙重效果，歸入「Re-rating Candidates」組，但**未提供新財報數字**，論點與前七節一致。研華、研揚、融程、宸曜、凌華、艾訊六家僅重複列名，無新數字；威強電、廣積、安勤三家本輪完全未提及。

### 8.4 最終結論／投資意涵

**共通供應鏈總表**：

| 排名 | 供應鏈 | 代表台股 | Cloud | Edge | 財報強度 | 評價 |
|---:|---|---|---:|---:|---:|---|
| 1 | Power | 台達、光寶 | ★★★★★ | ★★★★★ | ★★★★★ | **A+** |
| 2 | PCB/CCL | 金像、欣興、台光電 | ★★★★★ | ★★★★ | ★★★★★ | **A+** |
| 3 | Memory | 華邦、旺宏、南亞科 | ★★★★★ | ★★★★★ | ★★★★★ | **A** |
| 4 | Semiconductor | 台積、聯發科 | ★★★★★ | ★★★★★ | ★★★★★ | **A** |
| 5 | Networking | 智邦 | ★★★★★ | ★★★ | ★★★★★ | **A** |
| 6 | Thermal | 奇鋐、雙鴻、健策 | ★★★★★ | ★★★ | ★★★★★ | **A** |
| 7 | Packaging | 台積、日月光 | ★★★★★ | ★★★★ | ★★★★ | **A** |
| 8 | Connector | 嘉澤、貿聯 | ★★★★★ | ★★★★ | ★★★★ | **A-** |
| 9 | IPC / Edge System | 研華、研揚 | ★★ | ★★★★★ | ★★★★ | **A-** |
| 10 | Robotics | 宸曜、凌華等 | ★ | ★★★★★ | ★★★★ | **B+ / A-** |

**投資報酬率角度重新分組**（原文明確表示「不會直接買最強的公司」，要找「基本面成長速度－市場已反映程度」最大者）：

- **第一群：基本面最強，但市場已知道**（估值偏高，非優先買點）：台積電、智邦、奇鋐、金像電、研華——金像電 PE 約 40.6 倍、奇鋐 PE 約 44.8 倍（⚠️此數字僅出現一次，缺詳細來源段落）、健策 PE 超過 130 倍。
- **第二群：AI 獲利正在加速，但市場估值尚未完全重估**（原文判定為目前最想找的目標）：
  1. **光寶科 2301**——AI電源+Cloud+Edge+AI營收>30%+H1 EPS+66%，Q2 EPS YoY+126%
  2. **華邦電 2344**——「財報兌現鏈」，且強調不只是 Cloud AI 受益者，Edge AI 對 Memory 需求增加也會受惠
  3. **旺宏 2337**——歸入「Memory復甦+Edge AI」觀察名單，但需判斷是真 Edge AI 需求還是純 memory price recovery
  4. **台達電 2308**——優點是「AI Infrastructure 的穿越週期能力」，「不需要猜 AI 最後跑在哪裡」
  5. **樺漢 6414**——「可能被市場錯誤分類」，若 AI Software/System Integration 占比上升，可能出現 EPS growth + PE re-rating 雙重效果

**最終三分類清單**（全篇壓軸，原文標註這是下一步待做的 20 檔候選股篩選之前的分類）：
- **Core**：台積電、台達電、光寶科、華邦電、高階PCB/CCL、封裝
- **Growth**：金像電、欣興、智邦、奇鋐、雙鴻
- **Edge / Physical AI Beta**：研華、研揚、融程、宸曜、凌華、艾訊
- **Re-rating Candidates**：樺漢、光寶、華邦、旺宏（⚠️光寶、華邦重複出現在 Core 與 Re-rating Candidates 兩組，原文未自行調和，如實照抄）

原文結尾宣告「下一步」而非最終投資建議：把供應鏈縮成 **20 檔候選股**，計算「AI Exposure × EPS Growth × Margin Expansion × Forward PE × 回撤幅度」，最後只留 **5～8 檔**——**這一步在本次追加內容中尚未執行**，屬於原文自己宣告的下一階段。

### 8.5 內容缺口與矛盾標注（本次追加，非前七節已列項目）

1. **初版沒有給台積電代號**，代號「2330」只在最終版才出現——兩版對同一家公司的資訊完整度不一致，如實照抄未補齊。
2. **最終版「最終三分類清單」中，光寶科與華邦電同時出現在「Core」與「Re-rating Candidates」兩組**，原文未自行調和。
3. **貿聯在初版供應鏈總表的 Connector 欄位重複出現一次**，判斷為原文行文瑕疵，如實照抄。
4. **奇鋐 PE「約 44.8 倍」**只出現一次，缺詳細計算依據段落佐證（同段金像電、健策的 PE 都有股價÷近四季EPS的明確依據）。
5. **南亞科、台光電、貿聯、嘉澤、啟碁**：僅被列名為某環節代表台股，全篇無財報數字或代號，性質同前七節已標注的「泓格、新漢」情況。
6. **背景查證資料未整合進主文**：assistant 搜尋過程中查到但未收錄的 4 則素材——川湖科技（King Slide Works，AI伺服器機櫃滑軌，市佔約80%、毛利率87%，創辦人林土城已成台灣首富）、美國製造業復甦總經背景（Boeing/Vertiv/Emerson等，2026資本支出估1.8兆美元）、NVIDIA 2027財測帶動亞歐晶片股（Kioxia/Samsung/SK Hynix/ASML/STMicro）、台灣檢方起訴9人非法出口AI伺服器到中國（涉Nvidia/Super Micro）——均查到但未在主文出現或被引用，判斷屬於搜尋過程的背景素材，非本次整理的疏漏。**川湖科技**與 Cloud/Edge 共同供應鏈主題高度相關（伺服器機櫃機構件），卻未被納入本節「共同供應鏈環節全景」，是原文自己的取捨，非本次摘要遺漏。
7. **既有名單中的威強電3022、廣積8050、安勤3479**：本次追加內容完全未提及，不是矛盾，只是本輪分析未涵蓋。

---

## 已發布 Artifact

排版版（含目錄導覽、投資雷達分級卡片、10檔公司財報比較表）：
https://claude.ai/code/artifact/ff96d1de-7969-491b-a49a-cc66a8ba8d60
