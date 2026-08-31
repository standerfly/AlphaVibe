# 台股 Edge AI／邊緣運算供應鏈研究筆記（2026-08-31 整理）

研究起點：一段 ChatGPT 對話紀錄（分享連結）
https://chatgpt.com/share/6a94d916-6294-83ee-b976-3d11a123092a
（標題：「分析邊緣運算供應鏈」，對話內容標註至 2026/8/31）

**性質說明**：這份筆記不是我自己執行的多來源網頁研究，而是對**既有一份 ChatGPT 對話**的完整解析與結構化摘要——該對話本身包含 assistant 的網頁搜尋與財報數字引用，但這些數字未經本次整理再次向原始來源查證，一律照對話原文轉述，並保留原文自己標註的信心程度與矛盾點。

已發布 Artifact（排版版，含目錄導覽、投資雷達分級卡片、10檔公司財報比較表）：
https://claude.ai/code/artifact/ff96d1de-7969-491b-a49a-cc66a8ba8d60

---

## 一、原始問題與對話結構

使用者原始問題（對話開場）：
> AI雲端運算的市場目前已有一定的規模且市場供應鏈架構相對清晰。請分析邊緣運算的技術趨勢與市場供應鏈。

對話共經歷四個階段：

| 階段 | 內容 | 對話中的角色 |
|---|---|---|
| 1 | 邊緣運算技術趨勢與供應鏈全景第一版分析 | assistant 完整回答 |
| 2 | 使用者貼上一篇工商時報／IT系統供應鏈報導（IPC×邊緣AI雙動能） | 使用者提供的原始文章 |
| 3 | assistant 根據補充資料做出**投資主軸修正** | assistant 修正分析 |
| 4 | 整合為「2026/8/31 台股 Edge AI 投資地圖 V1」 | assistant 最終產出 |

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

## 已發布 Artifact

排版版（含目錄導覽、投資雷達分級卡片、10檔公司財報比較表）：
https://claude.ai/code/artifact/ff96d1de-7969-491b-a49a-cc66a8ba8d60
