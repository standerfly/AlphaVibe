"""EP461 回測（poc/backtest-ep461）共用設定與小工具。

僅用標準庫、Python 3.9 相容（Mac 本機是 3.9.6）。
本資料夾完全獨立：不 import poc/kb-mcp、不讀寫正式庫 poc/data，
下載資料放在本資料夾的 data/、結果放在 out/（兩者都已 gitignore）。
規格：專案文件 claude/回測規格-EP461與相對強弱.md v0.3。
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BT_DATA_DIR") or os.path.join(HERE, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
OUT_DIR = os.environ.get("BT_OUT_DIR") or os.path.join(HERE, "out")
API_URL = os.environ.get("FINMIND_API_URL", "https://api.finmindtrade.com/api/v4/data")

BENCH = "0050"
# 庫存 15 檔（2026-11-13 快照，規格第 2 節）
HOLDINGS = [
    ("2308", "台達電"), ("2337", "旺宏"), ("2441", "超豐"), ("2449", "京元電子"),
    ("3131", "弘塑"), ("3526", "凡甲"), ("3661", "世芯-KY"), ("4931", "新盛力"),
    ("6223", "旺矽"), ("6515", "穎崴"), ("6757", "台灣虎航"), ("6826", "和淞"),
    ("7734", "印能科技"), ("7769", "鴻勁"), ("8299", "群聯"),
]
NAMES = dict(HOLDINGS)
NAMES[BENCH] = "元大台灣50"
SYMBOLS = [BENCH] + [s for s, _ in HOLDINGS]

PRICE_DATASET = "TaiwanStockPrice"
# 還原因子來源（資料集名稱依 FinMind 文件記憶，B0 的 probe 會實際確認名稱與欄位）
DIVIDEND_DATASET = "TaiwanStockDividendResult"      # 除權息結果（含參考價）
SPLIT_DATASET = "TaiwanStockSplitPrice"             # 分割／面額變更參考價
CAPRED_DATASET = "TaiwanStockCapitalReductionReferencePrice"  # 減資參考價
EVENT_DATASETS = [DIVIDEND_DATASET, SPLIT_DATASET, CAPRED_DATASET]
DEFAULT_START = "2010-01-01"

# 已知事件的手動備援：只有「下載資料裡沒有同檔、同日前後 5 天的分割事件」時才使用。
MANUAL_EVENTS = [
    {"stock_id": "0050", "date": "2025-06-18", "factor": 0.25, "kind": "split",
     "note": "0050 於 2025-06 一拆四（規格第 6 節 B1）"},
]

# 規格第 6 節的暫定參數
PARAMS = {"n": 20, "vr_min": 1.5, "vr_win": 5, "cooldown": 5, "confirm": 5,
          "shrink": 0.7, "shrink_win": 3}
HORIZONS = (5, 10, 20, 60)
SENS_N = (10, 20, 60)
SENS_VR = (1.5, 2.0, 3.0)
SENS_SHRINK = (0.5, 0.7, 0.9)


def read_token(explicit_file=None):
    """token 來源：環境變數 FINMIND_TOKEN > --token-file > 本資料夾 finmind_token.txt
    > ../data/finmind_token.txt（專案既有慣例位置）。絕不印出 token。"""
    token = os.environ.get("FINMIND_TOKEN", "").strip()
    if token:
        return token
    candidates = []
    if explicit_file:
        candidates.append(explicit_file)
    candidates += [os.path.join(HERE, "finmind_token.txt"),
                   os.path.join(HERE, "..", "data", "finmind_token.txt")]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
    return ""


def raw_path(dataset, stock_id):
    return os.path.join(RAW_DIR, dataset, "%s.json" % stock_id)


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_raw(dataset, stock_id):
    path = raw_path(dataset, stock_id)
    if not os.path.isfile(path):
        return None
    return read_json(path)


def today_str():
    return datetime.date.today().isoformat()


def pct(x, digits=2):
    return "—" if x is None else ("%+.*f%%" % (digits, x * 100))
