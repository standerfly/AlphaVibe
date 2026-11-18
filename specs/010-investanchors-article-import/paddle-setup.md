# 方案 C：本機 PaddleOCR 表格轉寫——安裝、離線使用與評估（010）

日期：2026-11-18。狀態：**程式與 Linux 容器 smoke 已完成；Mac 實測、PO 抽查尚未做，未接進匯入流程、未部署**。
程式：`poc/kb-mcp/article_transcribe_paddle.py`（引擎）、`poc/kb-mcp/paddle_eval.py`（評估工具）；
測試：`poc/kb-mcp/tests/test_article_transcribe_paddle.py`、`test_paddle_eval.py`（假 paddleocr，不需真實安裝）。

## 0. 哪些已驗證、哪些必須在 Mac 實測

| 項目 | 狀態 | 依據 |
|---|---|---|
| pip 可安裝 paddlepaddle 3.3.1＋paddleocr 3.7.0，模型可下載、可推論 | **已在 Linux 容器驗證**（x86_64、Python 3.13、4 核、15GB RAM） | 本文第 6 節 |
| 辨識流程、Markdown 轉換、長圖切片合併、`[?]` 標記、離線（socket 全擋）仍可運作 | **已在 Linux 容器驗證**（真實模型＋合成圖；另有 93 個假模組單元測試） | 第 6 節、測試 |
| macOS arm64＋Python 3.9 的**相依解析**（只用預編譯 wheel） | **已用 `pip install --dry-run --platform macosx_*_arm64 --python-version 3.9` 驗證可解析**（含 `[doc-parser]`）；`paddlepaddle-3.3.1-cp39-cp39-macosx_11_0_arm64.whl` 實測存在、104,482,913 bytes | 第 3 節 |
| 在 Mac 上**真的裝起來、跑得動** | **必須實測**（容器是 x86＋Python 3.13，結果不能外推） | 第 7 節清單 |
| 耗時、記憶體（Apple Silicon 的 CPU 推論） | **必須實測**（容器數據僅供數量級參考） | 第 7 節 |
| 繁中**真實財經表格**的辨識準確度 | **完全未驗證**（容器只測合成圖；官方也沒有繁中財經數字表格的基準） | 第 7 節、第 8 節 |
| 與 Haiku／方案 D 的並排品質比較 | **必須由 PO 在 Mac 用真實抽查圖逐格比對** | 第 5 節 |

## 1. 這個引擎做什麼

- 輸入一張表格圖（長圖自動切片），輸出 **Markdown 表格**；看不清楚／信心低（預設 < 0.80）的格寫 `[?]`，**不猜測補值**；
  完全偵測不到文字 → `untranscribed`（不以空白充數，FR-017）。
- **全程本機**：預設離線，缺模型直接回「找不到模型」並要求中止，不會偷偷連網下載（`allow_download=False`）。
- 回傳值與 `article_transcribe.transcribe_image()` 同形（`status/is_table/text/model/reason/abort`），另加
  `retryable`（暫時性錯誤）、`detail`（人看的說明）、`meta`（模式、切片數、耗時、低信心格清單、警告）。
- 兩種重建表格的模式（`mode`）：

| 模式 | 用到的東西 | 模型體積 | 特色 | 風險 |
|---|---|---|---|---|
| `ocr_grid`（**預設**） | PP-OCRv5 文字偵測＋辨識，列／欄由本模組依文字框座標分群 | server 約 167MB（det 85＋rec 82）；mobile 約 22MB | 不依賴表格結構模型（官方結構準確率僅 63.7～69.7%）；無框表格可用；長圖在全圖座標上合併，欄位各片一致 | 合併儲存格只能放在第一欄、其餘留空；儲存格內換行會變成多列 |
| `table_pipeline` | `TableRecognitionPipelineV2`（版面偵測＋表格分類＋SLANeXt＋儲存格偵測）→ `pred_html` → Markdown | 約 1.1GB 額外模型（共約 1.3GB） | 能處理合併儲存格（colspan／rowspan） | 需 `paddleocr[doc-parser]`；較慢；對位 `cell_box_list` 與 `td` 有時不一致（容器實測長圖出現 `cell_boxes_misaligned` 警告，該片就無法標 `[?]`） |

  建議先用 `ocr_grid` 抽查；表格有大量合併儲存格再試 `table_pipeline`。評估工具可 `--mode both` 並排看兩者。

## 2. 長圖處理（設計決定與理由）

- 重用 `article_image_tiles.plan_tiles()` 的規則（片高≈寬×0.8、相鄰重疊 ≥15% 且 ≥200px、切點落在橫向空白帶、最多 8 片），
  與 API 路徑切法一致，才能逐片並排比對。像素處理改用 numpy／PIL（paddle 本來就依賴它們，**不需要 Node／Playwright**）。
- 為什麼要切：表格結構模型與版面偵測會把整張圖縮到幾百 px；而且**不限制偵測輸入大小時，PaddleOCR 對 2190 寬、1678 高的
  單片會嘗試配置約 18.8GB 記憶體而 `MemoryError`（容器實測）**，所以引擎預設 `det_max_side=1280`（文字偵測輸入長邊上限）。
- `ocr_grid`：各片文字框轉成全圖座標後，**丟棄貼著內部切線的被切斷框**、重疊區依位置與文字去重（留信心高者），再整張分群一次。
- `table_pipeline`：各片 HTML 沒有共同座標，改以列文字去重合併，允許前文最後 1 列、下一片最前 2 列為殘缺列；全空白列丟棄。

## 3. 安裝（在 Mac；獨立 venv，不污染既有 `.venv` 與 `AlphaVibe-prod`）

**原則**：獨立虛擬環境放在 repo 外（建議 `~/.venvs/paddle`），或 repo 內的 `.venv-paddle/`（已加入 `.gitignore`）。
**不要**裝進 `AlphaVibe/.venv`、系統 Python、或 `AlphaVibe-prod`（其 `requirements.txt` 不得因此改動）。
paddle 相關套件約 1.6GB（含依賴），模型另計，**絕不能進 launchd 排程使用的環境**，直到 PO 決定採用並另行評估部署。

```bash
# zsh／bash 皆可。Mac 系統 Python 是 3.9.6（/usr/bin/python3），paddleocr 3.7.0 要求 ≥3.8（[doc-parser] 要求 ≥3.9）
/usr/bin/python3 -m venv ~/.venvs/paddle
~/.venvs/paddle/bin/pip install --upgrade pip          # 系統內建 pip 太舊，認不得新的 macOS wheel 標籤
# 核心（ocr_grid 模式；PP-OCRv5）：
~/.venvs/paddle/bin/pip install paddlepaddle==3.3.1 paddleocr==3.7.0
# 只有要試 table_pipeline 模式才加：
~/.venvs/paddle/bin/pip install "paddleocr[doc-parser]==3.7.0"
# 裝好且驗證可用後，鎖定全部相依版本（日後重建用）：
~/.venvs/paddle/bin/pip freeze > ~/.venvs/paddle/requirements-lock.txt
```

- 我（容器）用 `pip install --dry-run --python-version 3.9 --platform macosx_11_0_arm64 --only-binary=:all:` 驗證過核心安裝可解析
  （解析結果包含 `numpy 2.0.2`、`opencv-contrib-python 4.10.0.84`、`pillow 11.3.0`、`shapely 2.0.7`、`pyclipper 1.3.0.post6`、
  `protobuf 6.33.6`、`modelscope 1.37.1`、`huggingface_hub 1.8.0`）；`[doc-parser]` 要加多個 `--platform macosx_1x_0_arm64` 標籤才解析得過
  （`scikit-learn` 只有較新的 macOS 標籤），真實 Mac 的 pip 會自行接受相容標籤，所以不是問題。**這只證明「可解析」，不證明「能執行」。**
- 容器實際安裝版本（Python 3.13、x86_64）：paddlepaddle 3.3.1、paddleocr 3.7.0、paddlex 3.7.2、numpy 2.3.5、opencv-contrib-python 4.10.0.84、
  pillow 13.0.0；`[doc-parser]` 另帶 scikit-learn、lxml、beautifulsoup4、openai 等。pip 會同時裝 `modelscope`／`huggingface_hub`／`aistudio-sdk`（paddlex 的模型下載後端）。
- **x86 專屬坑（Mac arm 不適用，但在 Intel Mac 或 Linux 會踩）**：paddle 3.3.1 預設啟用 oneDNN，x86 CPU 推論會丟
  `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`。
  本模組一律傳 `enable_mkldnn=False`，容器實測因此可正常推論；Apple Silicon 沒有 oneDNN，不受影響。

## 4. 模型：首次下載與之後離線使用

PaddleOCR 3.7.0／paddlex 3.7.2 **預設從 Hugging Face 下載**（`PADDLE_PDX_MODEL_SOURCE=huggingface`，倉庫 `PaddlePaddle/<模型名>`；
依序備援 AIStudio → ModelScope → BOS，BOS 即 `paddle-model-ecology.bj.bcebos.com`），存到 `~/.paddlex/official_models/<模型名>/`。
（官方調查原本寫預設來源是 bcebos；**以我實際安裝的版本為準是 huggingface.co**。）

```bash
# 1) 只有這一步需要網路（--allow-download 才會解除離線守衛）。ocr_grid 模式只下載 PP-OCRv5_server_det／rec 兩個：
~/.venvs/paddle/bin/python poc/kb-mcp/paddle_eval.py <含幾張測試圖的資料夾> --allow-download --out ./paddle_eval_out
# 想用較小較快的 mobile 模型（約 22MB）：加 --variant mobile
# 2) 之後完全離線（預設行為）：
~/.venvs/paddle/bin/python poc/kb-mcp/paddle_eval.py <圖片資料夾> --out ./paddle_eval_out
```

- **離線機制**：引擎先在 `model_dir` 參數 → 環境變數 `ALPHAVIBE_PADDLE_MODEL_DIR` → `$PADDLE_PDX_CACHE_HOME/official_models` →
  `~/.paddlex/official_models` 找模型子資料夾，找到就以 `*_model_dir` 明確指向本機；找不到且未允許下載 → `reason=model_not_available`
  （`abort=True`）。離線時另設 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`、`HF_HUB_OFFLINE=1`（避免 paddlex 啟動時的連線檢查；
  這兩個環境變數必須在 paddlex **第一次 import 之前**設定，所以評估工具啟動時就決定）。`paddle_eval.py` 另在行程內把
  socket 對外連線與 DNS 全擋（只放行 127.0.0.1／unix socket）。
- **容器實測**：模型下載好之後，socket 連線與 DNS 全部封鎖的情況下，`ocr_grid` 與 `table_pipeline` 都能完整推論（見第 6 節）。
- 模型可整個資料夾複製到另一台機器離線使用（把 `~/.paddlex/official_models/` 複製過去，或用 `ALPHAVIBE_PADDLE_MODEL_DIR` 指向）。
- 來源網址（容器 smoke 實際連過的）：`huggingface.co`（模型倉庫）、`pypi.org`／`files.pythonhosted.org`（套件）。
  `paddle-model-ecology.bj.bcebos.com` 只做過連通性 HEAD 檢查，沒有實際下載。

## 5. 使用與驗證

```bash
# 驗證安裝（印出版本；沒裝會看到清楚的「未安裝」錯誤與安裝提示，而不是 traceback）：
~/.venvs/paddle/bin/python -c "import paddleocr; print(paddleocr.__version__)"
# 跑單元測試（不需要 paddle；任何 Python 3.9+ 都行）：
python3 -m unittest tests.test_article_transcribe_paddle tests.test_paddle_eval   # 在 poc/kb-mcp 目錄下
# 評估：資料夾、或 --transcribe-sample 產生的報告（直接拿同一批抽樣圖，與 Haiku 的結果並排比對）、或 .json／.txt 清單：
~/.venvs/paddle/bin/python poc/kb-mcp/paddle_eval.py <資料夾或清單檔> --mode both --show-low-conf --out ./paddle_eval_out
```

報告 `paddle-eval-<時間>.md` 的每一節格式與 `transcribe-sample` 報告一致（`## k. <標籤>｜寬x高[｜長圖]`／`原圖：`／`狀態：`／轉寫），
另有每張耗時與平均、失敗數的總結；**不含文章標題或內文**。`--show-low-conf` 會在報告裡列出被標 `[?]` 的格子的引擎猜測值與信心
（只在報告裡，不進轉寫文字）。退出碼：0 全成功、1 有失敗、2 參數錯誤、3 引擎不可用（未安裝／缺模型）。

## 6. Linux 容器 smoke 結果（2026-11-18；x86_64、Python 3.13、4 核 CPU、無 GPU）

測試圖：用 PIL＋文泉驛正黑字型產生的**合成**繁中數字表格（欄位：項目／2024／2025E／2026E／年增率；每列隨機數字，固定亂數種子，有逐格正解）。
這不是真實財經表格，只能證明流程可行，**不代表真實準確度**。

| 圖 | 尺寸 | 模式 | 耗時 | 逐格結果 |
|---|---|---|---|---|
| 有框表格（12 列×5 欄） | 1478×816 | ocr_grid（server） | 23.6 s | 60/60 完全一致 |
| 有框表格 | 1478×816 | table_pipeline | 35.5 s | 60/60 |
| 無框表格（只有表頭底線） | 1478×816 | ocr_grid | 20.1 s | 60/60 |
| 無框表格 | 1478×816 | table_pipeline | 31.6 s | 60/60 |
| **長圖**（64 列×5 欄，模擬 2190×5327） | 2190×5296 | ocr_grid（切 4 片） | 102.1 s | **320/320**（無遺漏、無重複、表頭一次） |
| 長圖 | 2190×5296 | table_pipeline（切 4 片） | 133.7 s | 320/320（修正合併邏輯後；`cell_boxes_misaligned` 警告 1 次） |
| 有框表格 | 1478×816 | ocr_grid（**mobile** 模型） | 15.5 s | 60/60 |
| 無框表格 | 1478×816 | ocr_grid（mobile） | 8.6 s | 59/60：「稅後淨利」→「稅後凈利」 |
| 長圖 | 2190×5296 | ocr_grid（mobile） | 49.3 s | 319/320：同樣把「淨」讀成「凈」 |
| 輕度劣化（縮到 70% 再放大＋模糊 0.8） | 1478×816 | ocr_grid（server） | 23.3 s | 60/60 |
| **重度劣化**（縮到 45% 再放大＋模糊 1.6＋雜訊） | 1478×816 | ocr_grid（server） | 22.3 s | **11/60 完全一致、9 格標 `[?]`、40 格「有信心但讀錯」** |

（耗時含單次推論；首次載入模型另需 1～35 秒，引擎在行程內重複使用。耗時與 4 核 x86 CPU 有關，**Apple Silicon 必須另測**；
`table_pipeline` 的 35 秒含版面偵測等額外模型。同一台機器上同時有其他測試在跑時耗時會偏高，上表為評估工具單獨跑的數字。）

**誠實的觀察（不要誇大）**
1. 乾淨、解析度夠的合成圖：兩種模式、兩種表格型態都全對；長圖切片＋合併邏輯正確（首次實測 `table_pipeline` 在切線處多出 3 列重複＋1 空列，已修正並補測試）。
2. **重度劣化時，錯誤不會被信心門檻擋住**：40 個讀錯的格子信心都 ≥0.8（所以全部沒被標 `[?]`；例如 `24,417.0` 讀成 `24.417.0`、`76,458.7` 讀成 `764587`、`20.8%` 讀成 `208%`），
   只有另外 9 格因信心 <0.8 被標 `[?]`。也就是說 **`[?]` 不是「沒有錯」的保證**，數字的逗號／小數點／少位數是最危險的錯誤型態。真實的定錨表格圖解析度與清晰度必須由 PO 抽查決定可不可用。
3. 繁簡混用／異體字：重度劣化時出現「项目」「营業利益」（簡體字混入）；**mobile 模型把「淨」讀成「凈」且信心不低**（server 模型在乾淨圖上未出現）。
4. 沒有測過：真實財經表格的合併儲存格表頭、底色相近的分隔、跨欄標題、斜體／粗體混排、浮水印、極小字、百分比與括號負數等。
5. 容器資源：整個 venv 1.6GB（含 `[doc-parser]`）；所有下載過的模型 1.5GB（含 mobile、PP-OCRv4 與各表格模型）；`ocr_grid`＋`table_pipeline` 兩個引擎同時載入的行程 RSS 約 2.8GB。

## 7. 必須在 Mac 實測的清單

1. 用 `/usr/bin/python3`（3.9.6）建 venv、照第 3 節安裝，確認 `import paddleocr` 與推論真的能跑（尤其 `paddlepaddle` 的 arm64 wheel 在 macOS 版本上的相容性、
   `numpy 2.0.2`／`opencv` 組合、`[doc-parser]` 是否真的可裝）。
2. `paddle_eval.py --allow-download` 首次下載模型（網路、檔案大小、`~/.paddlex` 磁碟用量），再斷網重跑確認離線可用。
3. Apple Silicon 上的耗時與記憶體：單張短圖、2190×5300 長圖（4～5 片）各多久、記憶體峰值；`det_max_side`（預設 1280）與 server／mobile 的取捨。
4. **PO 抽查**（FR-018／SC-007 同一套標準：10 張真實表格含至少 1 張長圖，PO 逐格確認）：同一批圖用
   `investanchors_import.py --transcribe-sample N` 產 Haiku 結果、用 `paddle_eval.py <那份 transcribe-sample 報告> --mode both` 產 PaddleOCR 結果，並排比對；
   特別看數字的逗號／小數點／位數、負號與括號、百分比、繁簡字形、表頭、合併儲存格。
5. `min_score`（預設 0.80，尚未調校）與 `[?]` 的實際召回：把 `--show-low-conf` 的猜測值和原圖對，看被標 `[?]` 的格子是否真的是錯的、沒標的格子有沒有錯。
6. 長圖切線附近有沒有漏列／重複列（報告裡逐列檢查接縫）。
7. 與 API 引擎同一批圖並排後，決定是否值得（準確度＋省錢）採用方案 C，或僅當備援／離線方案。

## 8. 接進轉寫引擎抽象的建議（尚未做；本分支不得改 `investanchors_import.py`）

- `investanchors_import.py` 現有注入點 `self.transcribe(tiles, get_secret=…, api_url=…, model=…, timeout=…, merge=…)`。
  `article_transcribe_paddle.transcribe_tiles_paddle()` 簽名相容（忽略 `get_secret`／`api_url`／`sleeper`／`merge`），可直接當替代實作；
  但它會收到 Node 切好的多片 bytes，只能逐片辨識再以列去重合併。**更好的介面**：新增「整張圖」入口
  `transcribe_image_file(path, **kw)`（對應 `transcribe_image_paddle(path)`，自己切片、全圖座標合併），由引擎抽象依 `engine=api|paddle|manual` 選擇是否先呼叫 `open_tiles`。
- 引擎抽象建議以 `Transcriber` 協定表示：`transcribe(image_path) -> {status, is_table, text, model, reason, abort, retryable}`，
  `model` 欄位寫入 `article_image.transcribed_model`（本引擎為 `paddleocr-<版本>/<server|mobile>/<模式>`，換模型／版本即被視為可重轉對象）。
- `abort=True`（未安裝、缺模型、缺影像函式庫）→ 呼叫端中止本次後續圖，不計失敗次數（與缺金鑰同語意）；`retryable=True`（引擎執行錯誤、逾時、記憶體不足）→ 計入失敗次數。
- 開關：沿用 `setting.transcribe_enabled`；建議另加 `setting.transcribe_engine`（預設 `api`），**不得以「paddleocr 有沒有裝」當開關**（同 T038 原則）。
- 方案 C 的轉寫文字是 Markdown 表格（`|` 分隔、有 `| --- |` 分隔列），與 API 引擎「每列一行、`|` 分隔」格式相近但多了分隔列與 `[?]`；
  搜尋／顯示層若要統一請在輸出層處理，不要改資料庫內容。

## 9. 移除

```bash
rm -rf ~/.venvs/paddle            # 套件（約 1.6GB）
rm -rf ~/.paddlex                 # 模型快取（約 0.2～1.5GB，視下載了哪些）
rm -rf ~/.cache/huggingface       # 只有確定沒有其他用途時
# repo 端無需還原：本方案只新增檔案（引擎、評估工具、測試、本文件）與兩行 .gitignore，未改任何既有模組。
```

## 10. 授權

- paddleocr 3.7.0、paddlepaddle、paddlex：**Apache License 2.0**（`pip show paddleocr` 確認 paddleocr；其他依官方調查）。
- 模型（PP-OCRv5 等）由 PaddlePaddle 於 Hugging Face 發佈；**模型授權條款我未逐一查證**，PO 若要長期採用請另行確認。
- 本機推論不外送資料；唯一對外連線是「首次下載套件與模型」，且須明確傳 `--allow-download`。
