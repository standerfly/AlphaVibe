"""外站四段票搜尋用戶端（SerpApi Google Flights multi-city）。

機票查詢功能的資料層。**完全不 import 任何投資相關模組**（比照
`us_stock_price_client.py`／`photo_store.py` 的獨立先例），只沿用既有慣例：
HTTP 用 `urllib` 標準庫、失敗回傳 `{"error": ...}` 不拋例外、token 讀取
優先序（參數 > 環境變數 > `data_dir/<name>_token.txt`）。

## 為什麼是「四段票」

外站四段票＝一張票四個航段、頭尾同一個外站，例如以曼谷為外站飛巴黎：
    曼谷→台北、台北→巴黎、巴黎→台北、台北→曼谷
台灣旅客實際只要中間兩段，但航空公司給「非基地市場」的轉機促銷價常低於
台北直接出發價，故整張四段反而更便宜。機制與風險詳見
`docs/research/2026-09-22-ex-station-4segment-ticket-search.md`。

## 重要限制（2026-09-22 研究結論，動手前必讀）

1. **必須用 multi-city 一次查四段**。分段查詢會得到完全不同（且貴得多）的
   價格——四段票的低價來自多航段平均計價，拆開就沒有了。
2. **經濟艙才有意義**。商務艙促銷艙多帶
   `VALID FOR ROUNDTRIP ONLY. NOT PERMITTED ON MULTI-CITY`，一輸入多城市
   就跳 C/J 艙、票價翻倍。故 `travel_class` 預設 1（經濟艙）。
3. **資料源假設尚未驗證**：所有中文教學都用 Skyscanner／Trip.com 查四段票，
   沒有一篇提到 Google Flights。Google Flights 的四段報價是否等於
   Skyscanner 的便宜價，必須實測比對後才能信任本模組的結果。這是本模組
   目前最大的未知，不是程式缺陷。

token 來源優先序：參數 > 環境變數 `SERPAPI_KEY` > `data_dir/serpapi_token.txt`。
SerpApi 免費層 250 次/月、限速 50 次/小時——`scan()` 預設照這個速率節流，
因此大範圍掃描會跑很久，這是額度現實而非效能問題。
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE_URL = "https://serpapi.com/search"
TIMEOUT = 40
USER_AGENT = "alphavibe-flight-search-poc"

# Node scraper 位置（見 scraper/flight_scraper.js）。
SCRAPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper")
SCRAPER_JS = os.path.join(SCRAPER_DIR, "flight_scraper.js")

# 節流預設值——依 2026-09-22 封鎖風險調查與壓力測試定案
# （研究筆記第 12 節）。固定間隔是機器人特徵，故用隨機區間。
SCRAPE_MIN_DELAY_MS = 5000
SCRAPE_MAX_DELAY_MS = 11000
# 單次 session 上限。這個數字改過三次，過程值得記住：
#   50 —— 憑「業界 100+/小時」推估的保守半值，無實測依據
#   18 —— 2026-09-22 實測「第 21 筆起連續逾時」後下修
#   30 —— 2026-09-23 查明那次封鎖的真正原因是用了 chrome-headless-shell
#         （指紋明顯），換成真實 Chrome 後連跑 24 筆零封鎖、間隔僅 8–14 秒。
#         「20 筆閾值」其實是指紋造成的假象，不是速率上限。
# 30 是在已實測的 24 筆之上留一點邊際；再往上沒有實測根據，不要亂加。
SCRAPE_SESSION_LIMIT = 30

# 貨幣：對外查價服務要求 ISO 4217 代碼，`NTD` 不被接受（Google Flights 的
# curr 參數實測只吃 TWD）。UI 與文件一律顯示「NTD」，此處是送給 API 的值。
# 兩者是同一貨幣的不同寫法，不得混用其他幣別（PO 2026-09-23 要求）。
DEFAULT_CURRENCY = "TWD"
DISPLAY_CURRENCY = "NTD"

# 樞紐固定台北——外站四段票的整個前提就是「頭尾外站、中間經台北轉機」。
DEFAULT_HUB = "TPE"

# 熱門便宜外站（2026-09-22 研究：吉隆坡／曼谷／香港／東京／首爾競爭激烈，
# 促銷艙位開得多）。不是保證便宜的清單，是「值得掃一遍」的候選。
DEFAULT_OUTSTATIONS = ["KUL", "BKK", "HKG", "NRT", "ICN", "SIN", "SGN", "MNL"]

# SerpApi 免費層限速（次/小時）。scan() 據此計算請求間隔。
DEFAULT_RATE_PER_HOUR = 50

# 第 1 段與第 2 段的日期差。0＝同日轉機、1＝隔日轉機。
# 預設含 1 是因為長途線常見「傍晚抵台北、隔日凌晨飛歐洲」的銜接
# （2026-09-22 PO 提供的實例：BKK 18:00 抵台北，TPE 隔日 00:10 飛 PRG，
# 日期差 1 天但實際只隔 6 小時，仍在票規要求的 24 小時轉機內）。
DEFAULT_OUT_STAYS = [0, 1]

# 第 3 段與第 4 段的日期差。0＝回台北當天就飛回外站。
# **第四段可以丟到很遠的未來**——PO 實例中第 3 段 7/13 回台北、第 4 段
# 9/8 才飛回曼谷，相隔 57 天，用意是把第四段留給下一趟旅行當去程（或直接
# 棄搭）。要掃這種組合請明確傳大值，例如 ret_stays=[0, 30, 60]。
DEFAULT_RET_STAYS = [0]

# SerpApi 免費層每月額度（2026-09-22 查證：250 次/月、50 次/小時、註冊
# 不需信用卡、不會自動轉付費）。用量寫在 data_dir/flight_usage.json，
# 跨次執行累計——額度是「本月用完就沒了」的硬限制，必須持久化追蹤，
# 不能只靠單次執行的 limit 參數。
FREE_TIER_MONTHLY_QUOTA = 250

# 固定行程模式的預設掃描範圍。上限 21 天是用 2026-09-22 PO 實例校準的：
# 該實例第 1 段比第 2 段早 15 天、第 4 段比第 3 段晚 1~13 天。原本憑空定的
# 0-14 差一天就漏掉那組票——預設值要能涵蓋已知的真實案例，不是拍腦袋。
DEFAULT_LEAD_DAYS = list(range(0, 22))
DEFAULT_TRAIL_DAYS = list(range(0, 22))

# 訂票地（Point of Sale）候選：(gl 國家碼, hl 語言碼)。
# 同一組航段在不同國家版本的訂票介面可能報不同價格——PO 提供的實例是用
# **荷蘭文介面**查到的低價。此差異尚未實證，用 compare_pos() 驗證。
DEFAULT_POS_LIST = [
    ("tw", "zh-TW"),
    ("nl", "nl"),
    ("hk", "zh-TW"),
    ("sg", "en"),
    ("my", "en"),
    ("th", "th"),
]


# 瀏覽器路徑的**滾動小時速率**上限。
#
# 這個機制的前一版寫成「每日 25 筆、跨日歸零」——那是把觀測到的
# 「約 20–25 筆後被擋」硬加上「每天」這個限定詞，**沒有任何證據支持
# 跨日重置**。快取時間戳給出的實際證據是：
#   2026-09-22 23:41–00:04（23 分鐘）20 筆 →  52 筆/小時 → 被擋
#   2026-09-23 08:58–09:04（ 7 分鐘）24 筆 → 205 筆/小時 → 被擋
# 兩次都是短時間密集查詢後被擋，且 00:04 被擋、08:58 已能查（恢復
# ≤ 8.9 小時）。業界經驗值是每 IP 每小時 3–5（保守）到 100+（好 IP），
# 我們跑 205 筆/小時遠超上限——**所以限制更可能是速率，不是每日總量**。
#
# 20 筆/小時是依上述證據取的保守值（遠低於被擋的 52），但**仍未驗證**：
# 沒有「以此速率連跑數小時不被擋」的實測。不要把它當成已知安全值。
HOURLY_BROWSER_LIMIT = 20
_USAGE_WINDOW_SEC = 3600


def _browser_usage_path(data_dir):
    return os.path.join(data_dir, "flight_browser_usage.json")


def read_browser_usage(data_dir, window_sec=_USAGE_WINDOW_SEC):
    """讀滾動視窗內的查詢筆數（預設最近 1 小時）。

    記錄每筆查詢的時間戳而非單純計數——計數配「跨日歸零」無法表達
    速率限制，而證據指向速率才是真正的瓶頸。

    與 API 路徑的 `flight_usage.json`（月額度）分開記帳：不同的限制來源。
    """
    now = time.time()
    empty = {"count": 0, "queries": [], "oldest_age_sec": None}
    if not data_dir:
        return empty
    path = _browser_usage_path(data_dir)
    if not os.path.exists(path):
        return empty
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return empty
    stamps = [float(t) for t in data.get("queries", [])
              if isinstance(t, (int, float))]

    # 相容舊格式 {"date": "YYYY-MM-DD", "count": N}——那是本機制還是
    # 「每日計數」時寫下的（2026-09-23 改為滾動小時前）。若完全忽略，
    # 配額守衛會誤判為沒用過而放行。
    #
    # 用**檔案的最後修改時間**當那些查詢的時間戳：舊格式沒有逐筆時間，
    # 但 mtime 是最後一次寫入的時刻，是現有資訊中最接近真實的。
    # 第一版改用「都發生在此刻」，結果舊紀錄永遠不會退出滾動視窗——
    # 只要還是同一天就一直卡住配額，即使那些查詢是十幾小時前的事。
    if not stamps and data.get("count"):
        try:
            legacy_ts = os.path.getmtime(path)
            stamps = [legacy_ts] * int(data["count"])
        except (OSError, ValueError, TypeError):
            pass

    recent = sorted(t for t in stamps if now - t < window_sec)
    return {"count": len(recent), "queries": recent,
            "oldest_age_sec": (now - recent[0]) if recent else None}


def record_browser_usage(data_dir, calls):
    """記錄 calls 筆查詢的時間戳。視窗外的舊紀錄順便清掉。"""
    if not data_dir or calls <= 0:
        return
    now = time.time()
    keep = read_browser_usage(data_dir, _USAGE_WINDOW_SEC * 4)["queries"]
    keep.extend([now] * calls)
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(_browser_usage_path(data_dir), "w", encoding="utf-8") as fh:
            json.dump({"queries": keep}, fh, ensure_ascii=False)
    except OSError:
        pass


def remaining_browser_quota(data_dir, limit=HOURLY_BROWSER_LIMIT):
    """滾動小時內還剩幾筆可查。"""
    return max(0, limit - read_browser_usage(data_dir)["count"])


def seconds_until_quota_frees(data_dir, limit=HOURLY_BROWSER_LIMIT):
    """還要等幾秒才會釋出一筆配額（配額未滿時回 0）。"""
    usage = read_browser_usage(data_dir)
    if usage["count"] < limit:
        return 0
    # 第 (count-limit+1) 筆舊紀錄離開視窗時就釋出一個名額
    idx = usage["count"] - limit
    return max(0, int(_USAGE_WINDOW_SEC - (time.time() - usage["queries"][idx])))


def _usage_path(data_dir):
    return os.path.join(data_dir, "flight_usage.json")


def read_usage(data_dir):
    """讀本月已用額度。跨月自動歸零（額度按自然月重置）。"""
    month = datetime.date.today().strftime("%Y-%m")
    if not data_dir:
        return {"month": month, "count": 0}
    path = _usage_path(data_dir)
    if not os.path.exists(path):
        return {"month": month, "count": 0}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {"month": month, "count": 0}
    if data.get("month") != month:
        return {"month": month, "count": 0}
    return {"month": month, "count": int(data.get("count", 0))}


def record_usage(data_dir, calls):
    """累加本月用量。calls 是這次實際消耗的 API 次數（快取命中不算）。"""
    if not data_dir or calls <= 0:
        return
    usage = read_usage(data_dir)
    usage["count"] += calls
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(_usage_path(data_dir), "w", encoding="utf-8") as fh:
            json.dump(usage, fh, ensure_ascii=False)
    except OSError:
        pass


def remaining_quota(data_dir, quota=FREE_TIER_MONTHLY_QUOTA):
    """本月還剩幾次可用。永不回傳負數。"""
    return max(0, quota - read_usage(data_dir)["count"])


def _read_token(data_dir=None, token=None):
    if token:
        return token.strip()
    env = os.environ.get("SERPAPI_KEY", "").strip()
    if env:
        return env
    if data_dir:
        path = os.path.join(data_dir, "serpapi_token.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
    return ""


def _month_days(month):
    """把 'YYYY-MM' 展開成該月每一天的 date 物件清單。"""
    try:
        year, mon = [int(x) for x in month.split("-")]
        first = datetime.date(year, mon, 1)
    except (ValueError, TypeError):
        raise ValueError("month 格式應為 YYYY-MM，收到：%r" % (month,))
    days = []
    cur = first
    while cur.month == mon:
        days.append(cur)
        cur += datetime.timedelta(days=1)
    return days


def build_itineraries(destination, month, outstations=None, hub=DEFAULT_HUB,
                      trip_days=None, out_stays=None, ret_stays=None):
    """枚舉所有要查價的四段票組合。

    純函式、不打網路——`--dry-run` 與單元測試都靠這支確認搜尋空間正確。

    日期推導（base 是第 1 段出發日，即「從外站飛往台北」那天）：
        第1段 外站→台北    base
        第2段 台北→目的地   base + out_stay
        第3段 目的地→台北   base + out_stay + trip_day
        第4段 台北→外站     base + out_stay + trip_day + ret_stay

    回傳 list of dict，每筆含 outstation／legs（4 個 leg）／參數組合，
    順序固定（外站 → 出發日 → 停留組合），方便斷言與續掃。
    """
    outstations = outstations or DEFAULT_OUTSTATIONS
    trip_days = trip_days or [10]
    out_stays = out_stays if out_stays is not None else DEFAULT_OUT_STAYS
    ret_stays = ret_stays if ret_stays is not None else DEFAULT_RET_STAYS

    itineraries = []
    for outstation in outstations:
        for base in _month_days(month):
            for out_stay in out_stays:
                for trip_day in trip_days:
                    for ret_stay in ret_stays:
                        d1 = base
                        d2 = d1 + datetime.timedelta(days=out_stay)
                        d3 = d2 + datetime.timedelta(days=trip_day)
                        d4 = d3 + datetime.timedelta(days=ret_stay)
                        legs = [
                            {"departure_id": outstation, "arrival_id": hub,
                             "date": d1.isoformat()},
                            {"departure_id": hub, "arrival_id": destination,
                             "date": d2.isoformat()},
                            {"departure_id": destination, "arrival_id": hub,
                             "date": d3.isoformat()},
                            {"departure_id": hub, "arrival_id": outstation,
                             "date": d4.isoformat()},
                        ]
                        itineraries.append({
                            "outstation": outstation,
                            "destination": destination,
                            "hub": hub,
                            "base_date": d1.isoformat(),
                            "out_stay": out_stay,
                            "trip_day": trip_day,
                            "ret_stay": ret_stay,
                            "legs": legs,
                        })
    return itineraries


def build_itineraries_fixed_trip(destination, outbound_date, return_date,
                                 outstations=None, hub=DEFAULT_HUB,
                                 lead_days=None, trail_days=None):
    """主行程日期固定，只枚舉外站與前後兩段的日期。

    這是真實的使用情境：你已經決定好哪天出國、哪天回來（第 2、3 段），
    要找的是「從哪個外站出發、第 1 段提早幾天、第 4 段延後幾天」最便宜。
    `build_itineraries()` 那種「掃整月出發日」的模式適合行程還沒定的時候。

    2026-09-22 PO 提供的實例證明這兩段間隔可以很大：
    第 1 段比第 2 段早 15 天、第 4 段比第 3 段晚 1~13 天，而主行程本身長
    91 天（米蘭旅居）。原本 `build_itineraries()` 的預設值（0~1 天）連
    這種組合的邊都碰不到。

    `lead_days`：第 1 段早於第 2 段幾天（0＝同日）。
    `trail_days`：第 4 段晚於第 3 段幾天（0＝同日）。
    """
    outstations = outstations or DEFAULT_OUTSTATIONS
    lead_days = DEFAULT_LEAD_DAYS if lead_days is None else lead_days
    trail_days = DEFAULT_TRAIL_DAYS if trail_days is None else trail_days

    try:
        d2 = datetime.date.fromisoformat(outbound_date)
        d3 = datetime.date.fromisoformat(return_date)
    except (ValueError, TypeError):
        raise ValueError("outbound_date／return_date 格式應為 YYYY-MM-DD")
    if d3 < d2:
        raise ValueError("return_date（%s）不可早於 outbound_date（%s）"
                         % (return_date, outbound_date))

    itineraries = []
    for outstation in outstations:
        for lead in lead_days:
            for trail in trail_days:
                d1 = d2 - datetime.timedelta(days=lead)
                d4 = d3 + datetime.timedelta(days=trail)
                legs = [
                    {"departure_id": outstation, "arrival_id": hub,
                     "date": d1.isoformat()},
                    {"departure_id": hub, "arrival_id": destination,
                     "date": d2.isoformat()},
                    {"departure_id": destination, "arrival_id": hub,
                     "date": d3.isoformat()},
                    {"departure_id": hub, "arrival_id": outstation,
                     "date": d4.isoformat()},
                ]
                itineraries.append({
                    "outstation": outstation,
                    "destination": destination,
                    "hub": hub,
                    "base_date": d1.isoformat(),
                    "lead": lead,
                    "trail": trail,
                    "out_stay": lead,
                    "trip_day": (d3 - d2).days,
                    "ret_stay": trail,
                    "legs": legs,
                })
    return itineraries


# 日本外站候選（PO 2026-09-22 指定「亞洲外站，日本首選」）。
# 東京兩場分開列：成田與羽田的票價常有明顯落差，不能只查一個。
JAPAN_OUTSTATIONS = ["NRT", "HND", "KIX", "NGO", "FUK", "CTS", "OKA"]

# Skyscanner 市場站台。路徑式多城市網址在各市場站台通用，
# 換站台等同換訂票地(POS)，價格可能不同——見 compare_pos()。
SKYSCANNER_MARKETS = {
    "tw": "www.skyscanner.com.tw",
    "hk": "www.skyscanner.com.hk",
    "sg": "www.skyscanner.com.sg",
    "jp": "www.skyscanner.jp",
    "nl": "www.skyscanner.nl",
    "uk": "www.skyscanner.net",
}


def _pb_varint(n):
    out = b""
    while True:
        chunk = n & 0x7F
        n >>= 7
        out += bytes([chunk | (0x80 if n else 0)])
        if not n:
            return out


def _pb_key(field, wire):
    return _pb_varint((field << 3) | wire)


def _pb_bytes(field, payload):
    """length-delimited 欄位（字串或巢狀訊息）。"""
    return _pb_key(field, 2) + _pb_varint(len(payload)) + payload


def _pb_int(field, value):
    return _pb_key(field, 0) + _pb_varint(value)


def google_flights_url(legs, hl="zh-TW", gl="tw", currency=DEFAULT_CURRENCY,
                       travel_class=1, adults=1):
    """把行程編成 Google Flights 的 `tfs` 參數，回傳可直接點開的網址。

    **零成本路徑，本專案目前唯一實測可用的免 API 查價方式**：不需要 API
    key、不需註冊、不消耗任何額度。人點開就看到 Google Flights 的真實
    四段票報價。

    `tfs` 是 base64url 編碼的 protobuf（無 padding），結構：

        Info.data      (f3, repeated)  每個航段
          FlightData.date        (f2)  YYYY-MM-DD
          FlightData.from_flight (f13) Airport{name=f2}
          FlightData.to_flight   (f14) Airport{name=f2}
        Info.seat      (f9)   1=經濟 2=豪華經濟 3=商務 4=頭等
        Info.passengers(f8)   1=成人
        Info.trip      (f19)  1=來回 2=單程 3=多城市

    2026-09-22 實測驗證（`docs/research/2026-09-22-...md` 第 8 節）：
    四段票網址回 HTTP 200，頁面同時含四個航段日期與 NRT/TPE/PRG 三個
    機場代碼，且含 `multi_city` 標記；對照組單程網址標題為
    「臺北市到布拉格」且幾乎不含 NRT。
    """
    body = b""
    for leg in legs:
        one = (_pb_bytes(2, leg["date"].encode())
               + _pb_bytes(13, _pb_bytes(2, leg["departure_id"].upper().encode()))
               + _pb_bytes(14, _pb_bytes(2, leg["arrival_id"].upper().encode())))
        body += _pb_bytes(3, one)
    body += _pb_int(9, travel_class)
    body += _pb_int(8, adults)
    # trip type：1 段＝單程(2)、2 段＝來回(1)、3 段以上＝多城市(3)
    trip = 2 if len(legs) == 1 else (1 if len(legs) == 2 else 3)
    body += _pb_int(19, trip)
    tfs = base64.urlsafe_b64encode(body).decode().rstrip("=")
    query = urllib.parse.urlencode({"tfs": tfs, "hl": hl, "gl": gl,
                                    "curr": currency})
    return "https://www.google.com/travel/flights?" + query


def skyscanner_url(legs, market="tw", adults=1, cabin="economy"):
    """把四段行程組成 Skyscanner 多城市查詢網址。

    **零成本路徑**：不需要 API key、不需要註冊、不消耗任何額度。適合在
    資料源假設驗證完成前先人工比價，也適合額度用盡時的備援。

    **⚠️ 2026-09-22 實測：多城市不適用，只有 1~2 段有效。**
    單程與來回路徑回 HTTP 200，但四段路徑回 404；官方 referrals
    multicity endpoint 雖回 200，卻只讀第一段（標題變成「東京到台北」）。
    Skyscanner 的多城市搜尋不是網址可表達的，要產生四段票連結請改用
    `google_flights_url()`（已實測可用）。

    本函式保留給單程用途——例如產生「台北→外站」接駁票的比價連結。
    """
    host = SKYSCANNER_MARKETS.get(market, SKYSCANNER_MARKETS["tw"])
    parts = []
    for leg in legs:
        date = datetime.date.fromisoformat(leg["date"]).strftime("%y%m%d")
        parts.append("%s/%s/%s" % (leg["departure_id"].lower(),
                                   leg["arrival_id"].lower(), date))
    query = urllib.parse.urlencode({"adultsv2": adults, "cabinclass": cabin})
    return "https://%s/transport/flights/%s/?%s" % (host, "/".join(parts),
                                                    query)


def _cache_key(legs, travel_class, adults, currency, gl="tw", hl="zh-TW"):
    """快取鍵必須含 gl/hl——不同訂票地可能是不同價格，混在一起會互相污染。"""
    raw = json.dumps({"legs": legs, "c": travel_class, "a": adults,
                      "cur": currency, "gl": gl, "hl": hl},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_path(data_dir, key):
    return os.path.join(data_dir, "flight_cache", key + ".json")


def _read_cache(data_dir, key):
    if not data_dir:
        return None
    path = _cache_path(data_dir, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _write_cache(data_dir, key, payload):
    if not data_dir:
        return
    path = _cache_path(data_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def _fetch(params):
    url = API_BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # 401＝key 無效、429＝超過限速/額度用盡，兩者都要讓呼叫端看得出差別
        return {"error": "SerpApi HTTP %s：%s" % (exc.code, body or exc.reason)}
    except urllib.error.URLError as exc:
        return {"error": "SerpApi 連線失敗：%s" % (exc.reason,)}
    except ValueError:
        return {"error": "SerpApi 回應不是合法 JSON"}


def _summarize(payload):
    """從 SerpApi 回應萃取最低價與航空公司。

    best_flights 與 other_flights 都要看——四段票常因艙位組合落在
    other_flights，只看 best_flights 會漏掉真正最便宜的組合。
    """
    flights = []
    for bucket in ("best_flights", "other_flights"):
        value = payload.get(bucket)
        if isinstance(value, list):
            flights.extend(value)
    priced = [f for f in flights
              if isinstance(f.get("price"), (int, float)) and f.get("price") > 0]
    if not priced:
        insights = payload.get("price_insights") or {}
        low = insights.get("lowest_price")
        if isinstance(low, (int, float)) and low > 0:
            return {"price": low, "airlines": [], "source": "price_insights",
                    "option_count": 0}
        return {"price": None, "airlines": [], "source": "none",
                "option_count": 0}
    cheapest = min(priced, key=lambda f: f["price"])
    airlines = []
    for seg in cheapest.get("flights") or []:
        name = seg.get("airline")
        if name and name not in airlines:
            airlines.append(name)
    return {
        "price": cheapest["price"],
        "airlines": airlines,
        "total_duration": cheapest.get("total_duration"),
        "source": "flights",
        "option_count": len(priced),
    }


def search_itinerary(legs, token, travel_class=1, adults=1, currency=DEFAULT_CURRENCY,
                     data_dir=None, use_cache=True, gl="tw", hl="zh-TW"):
    """查單一組四段票報價。回傳 {"price":…, "airlines":[…]} 或 {"error":…}。

    `travel_class` 預設 1（經濟艙）——商務艙在 multi-city 會跳艙翻倍，
    見模組 docstring 限制 2。
    """
    if not token:
        return {"error": "SERPAPI_KEY 未設定（環境變數或 data_dir/serpapi_token.txt）"}
    key = _cache_key(legs, travel_class, adults, currency, gl, hl)
    if use_cache:
        cached = _read_cache(data_dir, key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached
    params = {
        "engine": "google_flights",
        "api_key": token,
        "type": 3,  # 3 = multi-city
        "multi_city_json": json.dumps(legs, ensure_ascii=False),
        "travel_class": travel_class,
        "adults": adults,
        "currency": currency,
        "hl": hl,
        "gl": gl,
    }
    payload = _fetch(params)
    if "error" in payload:
        return payload
    if payload.get("search_metadata", {}).get("status") == "Error":
        return {"error": "SerpApi 查詢失敗：%s"
                % (payload.get("error") or "未知原因",)}
    result = _summarize(payload)
    result["cached"] = False
    if use_cache and result.get("price") is not None:
        _write_cache(data_dir, key, result)
    return result


def search_oneway(departure_id, arrival_id, date, token, travel_class=1,
                  adults=1, currency=DEFAULT_CURRENCY, data_dir=None, use_cache=True,
                  gl="tw", hl="zh-TW"):
    """查單程票價（type=2），用於估算「台北→外站」的自費接駁成本。

    外站四段票的第一段是「外站→台北」，所以你必須先自費飛到外站才搭得到。
    PO 提供的實例警語寫得很明白：「第一段一定要搭乘！需再買 TPE-BKK 單程
    機票」。**不把這筆算進去，排序就是錯的**——外站挑得越遠，四段票價可能
    越低但接駁票越貴，價差會被吃掉。
    """
    if not token:
        return {"error": "SERPAPI_KEY 未設定（環境變數或 data_dir/serpapi_token.txt）"}
    legs = [{"departure_id": departure_id, "arrival_id": arrival_id,
             "date": date}]
    key = _cache_key(legs, travel_class, adults, currency, gl, hl)
    if use_cache:
        cached = _read_cache(data_dir, key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached
    params = {
        "engine": "google_flights",
        "api_key": token,
        "type": 2,  # 2 = one way
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": date,
        "travel_class": travel_class,
        "adults": adults,
        "currency": currency,
        "hl": hl,
        "gl": gl,
    }
    payload = _fetch(params)
    if "error" in payload:
        return payload
    result = _summarize(payload)
    result["cached"] = False
    if use_cache and result.get("price") is not None:
        _write_cache(data_dir, key, result)
    return result


def estimate_connectors_browser(outstations, date, hub=DEFAULT_HUB,
                                data_dir=None, currency=DEFAULT_CURRENCY,
                                gl="tw", hl="zh-TW",
                                hourly_limit=HOURLY_BROWSER_LIMIT,
                                min_delay_ms=SCRAPE_MIN_DELAY_MS,
                                max_delay_ms=SCRAPE_MAX_DELAY_MS):
    """走**瀏覽器路徑**估算各外站的接駁票價（樞紐→外站單程）。

    與 `estimate_connectors()` 的差別只在資料源：那一支走 SerpApi
    （需要 token），這一支走瀏覽器（免 token、免額度，但受速率限制）。
    兩者的回傳形狀相同：{外站: 價格 or None}。

    **2026-09-23 實測前提**：`flight_scraper.js` 原本只解析多城市頁面
    （硬綁「整趟行程」字樣），單程頁面沒有該字樣會逾時。已改為依頁面
    型態切換錨點。**此路徑尚未以真實單程查詢驗證過**——當日配額已用盡
    （30/20），無法實測。首次實際使用時若接駁價全為 None，優先懷疑
    單程頁面的解析錨點，而非配額或網路。
    """
    itineraries = []
    for code in outstations:
        itineraries.append({
            "outstation": code,
            "legs": [{"departure_id": hub, "arrival_id": code, "date": date}],
        })
    outcome = scrape_itineraries(
        itineraries, data_dir=data_dir, currency=currency, gl=gl, hl=hl,
        min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms,
        hourly_limit=hourly_limit)
    prices = {}
    for row in outcome.get("results", []):
        prices[row["outstation"]] = row.get("price")
    for code in outstations:
        prices.setdefault(code, None)
    return prices


def estimate_connectors(outstations, date, token, hub=DEFAULT_HUB,
                        data_dir=None, currency=DEFAULT_CURRENCY, gl="tw", hl="zh-TW",
                        quota=FREE_TIER_MONTHLY_QUOTA):
    """估算各外站的接駁票價（台北→外站單程），每個外站只查一次。

    刻意只用單一代表日期估價，而不是每個組合都查——那會讓查詢量翻倍。
    回傳 {外站: 價格 or None}，價格是估算值，用於排序修正而非精確報價。

    **記帳責任在這一層**：`search_oneway()`／`search_itinerary()` 這類
    單筆查詢函式不自行記帳（由批次呼叫端統一負責），所以這支批次函式
    必須自己呼叫 `record_usage()`。2026-09-22 端到端測試抓到過一次漏記
    ——接駁估價 7 次沒進帳，額度顯示 27 但實際打了 34 次，額度守衛因此
    會低估用量而超支。
    """
    prices = {}
    for outstation in outstations:
        if quota is not None and remaining_quota(data_dir, quota) <= 0:
            prices[outstation] = None
            continue
        outcome = search_oneway(hub, outstation, date, token,
                                data_dir=data_dir, currency=currency,
                                gl=gl, hl=hl)
        if not outcome.get("cached") and "error" not in outcome:
            record_usage(data_dir, 1)
        elif "error" in outcome and not outcome.get("cached"):
            record_usage(data_dir, 1)   # 失敗的請求一樣消耗額度
        prices[outstation] = outcome.get("price")
    return prices


def compare_pos(legs, token, pos_list=None, data_dir=None, currency=DEFAULT_CURRENCY,
                travel_class=1, adults=1):
    """同一組航段、不同訂票地(POS)比價，驗證 gl/hl 是否真的影響價格。

    PO 提供的實例是用荷蘭文介面查到的低價，但「換個國家版本就更便宜」目前
    只是假設。這支函式花 len(pos_list) 次額度直接證實或推翻它——若各 POS
    價格一致，之後全掃就固定用 tw，不必把 POS 當成搜尋維度。
    """
    pos_list = pos_list or DEFAULT_POS_LIST
    rows = []
    for gl, hl in pos_list:
        outcome = search_itinerary(legs, token, travel_class, adults, currency,
                                   data_dir, True, gl, hl)
        rows.append({"gl": gl, "hl": hl, "price": outcome.get("price"),
                     "error": outcome.get("error"),
                     "cached": outcome.get("cached", False)})
    priced = [r for r in rows if r.get("price") is not None]
    spread = None
    if len(priced) >= 2:
        lo = min(r["price"] for r in priced)
        hi = max(r["price"] for r in priced)
        spread = {"low": lo, "high": hi, "diff": hi - lo,
                  "pct": (hi - lo) * 100.0 / lo if lo else None}
    return {"rows": rows, "spread": spread}


def scan(destination, month, token=None, outstations=None, hub=DEFAULT_HUB,
         trip_days=None, out_stays=None, ret_stays=None, data_dir=None,
         limit=None, rate_per_hour=DEFAULT_RATE_PER_HOUR, travel_class=1,
         adults=1, currency=DEFAULT_CURRENCY, progress=None, connector_prices=None,
         gl="tw", hl="zh-TW", interleave=True,
         quota=FREE_TIER_MONTHLY_QUOTA):
    """批次掃描並回傳按價格排序的結果。

    節流：免費層 50 次/小時 → 預設每次請求間隔 72 秒。命中快取不計入節流
    也不計入 limit（不消耗 API 額度）。任何一筆失敗不中斷整批，錯誤記在
    該筆的 `error` 欄位；但連續遇到額度類錯誤（429）會提早停止，避免白跑。

    `interleave=True`（預設）把掃描順序改為日期優先、外站輪替，讓有限的
    額度先橫向覆蓋所有外站。排序結果若有 `connector_prices`，依「四段票價
    ＋接駁票價」的總成本排序，而非票面價。
    """
    itineraries = build_itineraries(destination, month, outstations, hub,
                                    trip_days, out_stays, ret_stays)
    if interleave:
        # 按日期優先排序 → 同一天的各外站彼此相鄰，額度中途用完時仍能橫向
        # 比較「哪個外站便宜」。若照 build_itineraries 的原始順序（外站為
        # 外層迴圈），limit 小的時候只會掃完第一個外站的整月，其餘外站
        # 一筆都沒有，對「找最便宜外站」這個目的毫無用處。
        itineraries = sorted(
            itineraries,
            key=lambda it: (it["base_date"], it["out_stay"], it["trip_day"],
                            it["ret_stay"], it["outstation"]))
    token = _read_token(data_dir, token)
    interval = 3600.0 / rate_per_hour if rate_per_hour else 0.0

    results = []
    spent = 0            # 實際消耗的 API 次數（快取不算）
    consecutive_429 = 0
    for idx, itin in enumerate(itineraries):
        if limit is not None and spent >= limit:
            break
        if quota is not None and remaining_quota(data_dir, quota) <= 0:
            break
        outcome = search_itinerary(itin["legs"], token, travel_class, adults,
                                   currency, data_dir, True, gl, hl)
        row = dict(itin)
        row.update(outcome)
        # 真實成本＝四段票價＋自費飛到外站的接駁票價（見 search_oneway）
        connector = (connector_prices or {}).get(itin["outstation"])
        row["connector_price"] = connector
        if row.get("price") is not None and connector is not None:
            row["total_cost"] = row["price"] + connector
        else:
            row["total_cost"] = row.get("price")
        results.append(row)

        if not outcome.get("cached"):
            spent += 1
            record_usage(data_dir, 1)
            err = outcome.get("error") or ""
            if "429" in err:
                consecutive_429 += 1
                if consecutive_429 >= 3:
                    row["note"] = "連續 3 次額度/限速錯誤，提早停止掃描"
                    break
            else:
                consecutive_429 = 0
            if progress:
                progress(idx + 1, len(itineraries), spent, row)
            # 最後一筆不用再等
            if interval and idx + 1 < len(itineraries):
                time.sleep(interval)
        elif progress:
            progress(idx + 1, len(itineraries), spent, row)

    priced = [r for r in results if r.get("price") is not None]
    # 有接駁估價就按總成本排——只按票面價排會偏袒接駁貴的遠外站
    priced.sort(key=lambda r: r.get("total_cost") or r["price"])
    return {
        "destination": destination,
        "month": month,
        "planned": len(itineraries),
        "queried": len(results),
        "api_calls_spent": spent,
        "priced_count": len(priced),
        "results": priced,
        "failures": [r for r in results if r.get("price") is None],
    }


def search_deals(hub, destination, window_start, window_end, token,
                 trip_length=None, data_dir=None, currency=DEFAULT_CURRENCY, gl="tw",
                 hl="zh-TW", stops=0, max_price=None, use_cache=True):
    """階段 1：一次查詢涵蓋整個時間窗，找出主行程便宜的日期。

    解決 PO 的核心問題「日期是我要的輸出，不是輸入」。逐日查價要 180 次
    才能covers半年，這支用 `google_flights_deals` engine 的**日期範圍**
    參數，一個月只要 1 次查詢。

    `outbound_date` 接受 `YYYY-MM-DD,YYYY-MM-DD` 範圍；`trip_length`
    接受 `min,max`（例如 `10,14` ＝行程 10 到 14 天都可以）。

    **重要限制**：Deals engine **不支援 multi-city**（只有 type=1 來回、
    type=2 單程）。所以它只能查「台北→目的地」的主行程，不能直接查四段票
    ——這正是要分兩階段的原因：主行程落在旺季時整張四段票都會被拉高
    （見研究筆記第 2 節），所以主行程便宜的時段就是四段票值得細查的時段。

    **未實測**：`arrival_id` 在官方參數表中沒有記載（只出現在回應範例），
    所以這裡照常傳送，但**額外以回應中的目的地欄位過濾一次**，以防該
    engine 其實是「找便宜目的地」模式而忽略 arrival_id。拿到 API key 後
    第一件事就是確認這點。
    """
    if not token:
        return {"error": "SERPAPI_KEY 未設定（環境變數或 data_dir/serpapi_token.txt）"}
    window = "%s,%s" % (window_start, window_end)
    params = {
        "engine": "google_flights_deals",
        "api_key": token,
        "departure_id": hub.upper(),
        "arrival_id": destination.upper(),
        "outbound_date": window,
        "type": 1,
        "currency": currency,
        "hl": hl,
        "gl": gl,
        "stops": stops,
    }
    if trip_length:
        params["trip_length"] = trip_length
    if max_price:
        params["max_price"] = max_price

    cache_seed = [{"departure_id": hub, "arrival_id": destination,
                   "date": window, "trip_length": trip_length or ""}]
    key = _cache_key(cache_seed, 1, 1, currency, gl, hl)
    if use_cache:
        cached = _read_cache(data_dir, key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    payload = _fetch(params)
    if "error" in payload:
        return payload

    deals = []
    raw = payload.get("deals") or payload.get("best_flights") or []
    for item in raw if isinstance(raw, list) else []:
        price = item.get("price")
        start = item.get("start_date") or item.get("outbound_date")
        end = item.get("end_date") or item.get("return_date")
        if not (isinstance(price, (int, float)) and price > 0 and start and end):
            continue
        # arrival_id 未必被 engine 採用——用回應內容再過濾一次
        dest_fields = " ".join(str(item.get(f, "")) for f in
                               ("arrival_airport", "destination_id", "name",
                                "arrival_id"))
        if dest_fields.strip() and destination.upper() not in dest_fields.upper():
            continue
        deals.append({"price": price, "outbound_date": start,
                      "return_date": end,
                      "link": item.get("flight_link")})
    deals.sort(key=lambda d: d["price"])
    result = {"deals": deals, "window": window, "cached": False,
              "raw_count": len(raw) if isinstance(raw, list) else 0}
    if use_cache and deals:
        _write_cache(data_dir, key, result)
    return result


# 起始月剩餘天數低於此值就跳到下個月：殘缺窗口既浪費一次額度，
# 又幾乎不可能找到便宜票（近期票價本來就高）。
MIN_FIRST_WINDOW_DAYS = 14


def find_cheap_dates(hub, destination, token, months_ahead=6,
                     trip_length="10,14", data_dir=None, currency=DEFAULT_CURRENCY,
                     gl="tw", hl="zh-TW", rate_per_hour=DEFAULT_RATE_PER_HOUR,
                     quota=FREE_TIER_MONTHLY_QUOTA, start_date=None,
                     progress=None):
    """掃描未來 N 個月，回傳按價格排序的候選主行程日期。

    每個月 1 次查詢——半年只要 6 次額度，而不是逐日查的 180 次。

    起始月若只剩不到 `MIN_FIRST_WINDOW_DAYS` 天，自動跳到下個月 1 號開始，
    確保 `months_ahead` 個窗口都是完整月份（2026-09-22 實測發現：不跳的話
    第一個窗口只有 9 天，白花一次額度又少掃一個完整月）。
    """
    token = _read_token(data_dir, token)
    today = datetime.date.fromisoformat(start_date) if start_date \
        else datetime.date.today()
    _eom = (today.replace(day=28) + datetime.timedelta(days=4))
    _eom = _eom.replace(day=1) - datetime.timedelta(days=1)
    if (_eom - today).days + 1 < MIN_FIRST_WINDOW_DAYS:
        today = _eom + datetime.timedelta(days=1)
    interval = 3600.0 / rate_per_hour if rate_per_hour else 0.0

    all_deals = []
    spent = 0
    cursor = today
    for i in range(months_ahead):
        if quota is not None and remaining_quota(data_dir, quota) <= 0:
            break
        # 用每月 1 號切窗，末月取該月最後一天
        win_start = cursor
        nxt = (win_start.replace(day=28) + datetime.timedelta(days=4))
        win_end = nxt.replace(day=1) - datetime.timedelta(days=1)
        outcome = search_deals(hub, destination, win_start.isoformat(),
                               win_end.isoformat(), token,
                               trip_length=trip_length, data_dir=data_dir,
                               currency=currency, gl=gl, hl=hl)
        if not outcome.get("cached"):
            spent += 1
            record_usage(data_dir, 1)
        if progress:
            progress(i + 1, months_ahead, spent, outcome)
        for deal in outcome.get("deals", []):
            deal["window"] = outcome.get("window")
            all_deals.append(deal)
        cursor = win_end + datetime.timedelta(days=1)
        if interval and i + 1 < months_ahead:
            time.sleep(interval)

    all_deals.sort(key=lambda d: d["price"])
    return {"deals": all_deals, "api_calls_spent": spent,
            "months_scanned": months_ahead}


def plan_cheap_trip(hub, destination, token, outstations=None,
                    months_ahead=6, trip_length="10,14", top_dates=5,
                    lead=1, trail=1, data_dir=None, currency=DEFAULT_CURRENCY,
                    gl="tw", hl="zh-TW", rate_per_hour=DEFAULT_RATE_PER_HOUR,
                    quota=FREE_TIER_MONTHLY_QUOTA, connector_prices=None,
                    start_date=None, progress=None):
    """兩階段規劃：日期未定時，先找便宜時段，再對那些時段查四段票。

    這是 PO 真正要的流程——「你找到便宜的機票，我再看時間合不合適」。

        階段 1　每月 1 次查詢找便宜主行程日期　　→ months_ahead 次
        階段 2　top_dates 個日期 × 各外站查四段票 → top_dates × 外站數 次

    半年 × 7 個日本外站 × 取前 5 個便宜日期 ＝ 6 + 35 ＝ **41 次額度**，
    遠低於逐日全掃的一萬五千次，也在免費 250 次內。

    **啟發式的前提**：主行程（第 2、3 段）便宜的時段，整張四段票也傾向
    便宜——因為只要任一航段落在旺季，整票總價就被拉高（研究筆記第 2 節
    第 3 點）。這個前提合理但**尚未實證**，拿到 key 後值得抽驗：挑一個
    階段 1 判定為貴的日期也查一次四段票，確認確實比較貴。
    """
    outstations = outstations or JAPAN_OUTSTATIONS
    stage1 = find_cheap_dates(hub, destination, token,
                              months_ahead=months_ahead,
                              trip_length=trip_length, data_dir=data_dir,
                              currency=currency, gl=gl, hl=hl,
                              rate_per_hour=rate_per_hour, quota=quota,
                              start_date=start_date, progress=progress)
    if not stage1["deals"]:
        return {"stage1": stage1, "stage2": None,
                "error": "階段 1 沒找到任何候選日期，無法進入階段 2"}

    # 同一組出發/回程日只留最便宜那筆，避免 top_dates 被同一天塞滿
    seen = {}
    for deal in stage1["deals"]:
        k = (deal["outbound_date"], deal["return_date"])
        if k not in seen:
            seen[k] = deal
    candidates = list(seen.values())[:top_dates]

    itineraries = []
    for deal in candidates:
        itineraries.extend(build_itineraries_fixed_trip(
            destination, deal["outbound_date"], deal["return_date"],
            outstations, hub, [lead], [trail]))

    rows, spent2 = _query_batch(
        itineraries, _read_token(data_dir, token), data_dir=data_dir,
        currency=currency, gl=gl, hl=hl, rate_per_hour=rate_per_hour,
        connector_prices=connector_prices, progress=progress, quota=quota)
    priced = [r for r in rows if r.get("price") is not None]
    priced.sort(key=lambda r: r.get("total_cost") or r["price"])
    return {
        "stage1": stage1,
        "stage2": {"results": priced, "spent": spent2,
                   "candidates": candidates},
        "api_calls_spent": stage1["api_calls_spent"] + spent2,
    }


def node_binary():
    """找出 node 可執行檔的絕對路徑。

    **不能只依賴 `PATH`**：launchd 啟動的排程只有
    `/usr/bin:/bin:/usr/sbin:/sbin`，而 Homebrew 的 node 在
    `/opt/homebrew/bin`。少了這層解析，排程會每次都拿到「找不到 node」
    而靜默失敗——排程沒人盯著，這種失敗最難察覺。

    plist 那邊也設了 PATH，兩層都做是因為任一層日後被改動（換機器、
    改用 nvm、plist 重建）時，另一層還能撐住。
    """
    found = shutil.which("node")
    if found:
        return found
    for cand in ("/opt/homebrew/bin/node", "/usr/local/bin/node",
                 "/usr/bin/node"):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def scraper_available():
    """瀏覽器路徑是否可用（scraper 檔案與 node_modules 都在）。"""
    return (os.path.exists(SCRAPER_JS)
            and os.path.isdir(os.path.join(SCRAPER_DIR, "node_modules")))


def _browser_summary(res):
    """把 scraper 的一筆結果轉成與 API 路徑一致的欄位。

    寫快取與組裝回傳都用這支，避免兩處邏輯分岔——欄位若不一致，
    快取命中與現查的結果形狀就會不同，排序與輸出都會出錯。
    """
    return {
        "price": res.get("price"),
        "airlines": [res["airline"]] if res.get("airline") else [],
        "option_count": res.get("option_count", 0),
        "source": "browser",
    }


def scrape_itineraries(itineraries, data_dir=None, currency=DEFAULT_CURRENCY, gl="tw",
                       hl="zh-TW", min_delay_ms=SCRAPE_MIN_DELAY_MS,
                       max_delay_ms=SCRAPE_MAX_DELAY_MS,
                       session_limit=SCRAPE_SESSION_LIMIT, timeout_ms=25000,
                       use_cache=True, progress=None,
                       hourly_limit=HOURLY_BROWSER_LIMIT):
    """用 headless 瀏覽器批次查價。**不消耗任何 API 額度。**

    這是 PO 選定的主力路徑（2026-09-22）：不需註冊、無額度上限、比 API
    快十餘倍（API 免費層限速 72 秒/次，這裡約 5–11 秒/次且含節流）。

    合規依據（研究筆記第 12 節）：Google robots.txt 未禁止
    `/travel/flights`（只禁 `/search`、`/s/`、`/booking`），且無
    Crawl-delay 指令。但 robots.txt 允許 ≠ ToS 允許，故仍採保守節流：
    序列執行、隨機間隔、session 上限、被擋立即中止。

    **Skyscanner 不可用此路徑**——其 robots.txt 明確 `Disallow: /transport/*`
    （即 `skyscanner_url()` 產生的路徑）。那些連結只能給人點。

    回傳 {"results": [...], "blocked": bool, "stats": {...}}，
    每筆 result 形狀與 `search_itinerary()` 一致（price／airlines），
    方便與 API 路徑互換。
    """
    if not scraper_available():
        return {"results": [], "blocked": False,
                "error": "scraper 未就緒：請在 %s 執行 npm install" % SCRAPER_DIR}

    pending, cached_rows = [], []
    for idx, itin in enumerate(itineraries):
        key = _cache_key(itin["legs"], 1, 1, currency, gl, hl)
        hit = _read_cache(data_dir, key) if use_cache else None
        if hit is not None:
            row = dict(itin)
            row.update(hit)
            row["cached"] = True
            cached_rows.append(row)
        else:
            pending.append((idx, itin, key,
                            google_flights_url(itin["legs"], hl=hl, gl=gl,
                                               currency=currency)))

    if pending and hourly_limit is not None:
        left_now = remaining_browser_quota(data_dir, hourly_limit)
        if left_now <= 0:
            wait = seconds_until_quota_frees(data_dir, hourly_limit)
            return {"results": cached_rows, "blocked": False,
                    "soft_blocked": False,
                    "error": "最近一小時已查 %d 筆，達 %d 筆/小時的速率上限。"
                             "約 %d 分鐘後釋出名額（或用 --hourly-limit 0 "
                             "解除，風險自負）"
                             % (read_browser_usage(data_dir)["count"],
                                hourly_limit, (wait + 59) // 60)}
        if len(pending) > left_now:
            pending = pending[:left_now]

    scraped_rows = []
    blocked = False
    soft_blocked = False
    stats = {"requested": len(pending), "attempted": 0, "ok": 0,
             "elapsed_sec": 0}
    if pending:
        payload = {
            "urls": [{"id": str(i), "url": url} for i, _, _, url in pending],
            "min_delay_ms": min_delay_ms,
            "max_delay_ms": max_delay_ms,
            "session_limit": session_limit,
            "timeout_ms": timeout_ms,
        }
        node = node_binary()
        if node is None:
            return {"results": [], "blocked": False, "soft_blocked": False,
                    "error": "找不到 node，無法使用瀏覽器路徑"}
        try:
            proc = subprocess.Popen(
                [node, SCRAPER_JS],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=None if progress else subprocess.DEVNULL)
        except OSError:
            return {"results": [], "blocked": False, "soft_blocked": False,
                    "error": "找不到 node，無法使用瀏覽器路徑"}

        by_id, summary, fatal = {}, {}, None
        index = dict((str(i), (i, itin, key)) for i, itin, key, _u in pending)
        deadline = time.time() + max(
            180, len(pending) * (max_delay_ms / 1000.0 + 45))
        try:
            proc.stdin.write(json.dumps(payload).encode("utf-8"))
            proc.stdin.close()
            # 逐行收 JSON Lines：每筆一到手就寫快取，中途中斷也不會全丟
            for raw in proc.stdout:
                try:
                    obj = json.loads(raw.decode("utf-8").strip() or "{}")
                except ValueError:
                    continue
                if obj.get("type") == "summary":
                    summary = obj
                    if obj.get("error"):
                        fatal = obj["error"]
                    continue
                rid = obj.get("id")
                if rid is None:
                    continue
                by_id[rid] = obj
                entry = index.get(rid)
                if obj.get("status") != "blocked":
                    record_browser_usage(data_dir, 1)   # 逾時也算消耗
                if entry and use_cache and obj.get("status") == "ok":
                    _write_cache(data_dir, entry[2], _browser_summary(obj))
                if time.time() > deadline:
                    proc.kill()
                    break
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()

        if fatal:
            return {"results": [], "blocked": False, "soft_blocked": False,
                    "error": fatal}
        blocked = bool(summary.get("blocked"))
        soft_blocked = bool(summary.get("soft_blocked"))
        stats = summary.get("stats", stats)

        for i, itin, key, _url in pending:
            res = by_id.get(str(i))
            row = dict(itin)
            if res and res.get("status") == "ok":
                row.update(_browser_summary(res))
                row["cached"] = False
            else:
                row["price"] = None
                row["error"] = (res or {}).get("status", "未查詢")
                row["cached"] = False
            scraped_rows.append(row)

    return {"results": cached_rows + scraped_rows, "blocked": blocked,
            "soft_blocked": soft_blocked, "stats": stats}


# 旺季月份的便利常數。**只是便利值，不是預設**——排除月份必須由使用者
# 自由複選 1–12 月。2026-09-23 PO 審閱需求時指正：南半球目的地的旺季
# 與北半球相反，把「夏季」寫死成 6–8 月會讓南半球航線判斷錯誤。
# 任何季節快捷都必須標明所屬半球。
NORTHERN_SUMMER_MONTHS = [6, 7, 8]    # 歐洲、日本、北美等北半球目的地
SOUTHERN_SUMMER_MONTHS = [12, 1, 2]   # 澳紐、南美、南非等南半球目的地


# 航空公司聯盟對照表（2026-09-24 新增）。PO 指出：外站四段票的四個航段
# 不一定是同一家航空公司，應該標示聯盟名稱——同聯盟成員之間互為
# interline 夥伴，對行程異動／改簽的處理方式通常比跨聯盟或無聯盟組合
# 更有保障，這是判斷「這張票的組合可不可靠」的重要資訊。
#
# **這是盡力而為的對照表，不是航空業權威資料源**——只收錄台灣出發、
# 常見外站航線（日本、東南亞、長程中轉）會出現的航空公司；查無資料的
# 航空公司會照原樣顯示、不標示聯盟，不會被誤判成「無聯盟」。
# key 用「包含比對」而非精確比對，因為 Google Flights 同一家航空公司
# 在不同頁面可能顯示「全日空」或「全日空航空」等不同寫法的中文名稱。
AIRLINE_ALLIANCES = {
    # 星空聯盟 Star Alliance
    "長榮航空": "星空聯盟", "全日空": "星空聯盟", "聯合航空": "星空聯盟",
    "新加坡航空": "星空聯盟", "泰國航空": "星空聯盟", "紐西蘭航空": "星空聯盟",
    "漢莎航空": "星空聯盟", "土耳其航空": "星空聯盟", "韓亞航空": "星空聯盟",
    "深圳航空": "星空聯盟", "印度航空": "星空聯盟",
    # 天合聯盟 SkyTeam
    "中華航空": "天合聯盟", "大韓航空": "天合聯盟", "達美航空": "天合聯盟",
    "法國航空": "天合聯盟", "荷蘭皇家航空": "天合聯盟", "越南航空": "天合聯盟",
    "廈門航空": "天合聯盟", "中國東方航空": "天合聯盟", "加魯達印尼航空": "天合聯盟",
    # 寰宇一家 Oneworld
    "國泰航空": "寰宇一家", "日本航空": "寰宇一家", "美國航空": "寰宇一家",
    "英國航空": "寰宇一家", "卡達航空": "寰宇一家", "馬來西亞航空": "寰宇一家",
    "澳洲航空": "寰宇一家", "芬蘭航空": "寰宇一家", "菲律賓航空": "寰宇一家",
}

# 明確**不屬於**任何聯盟的航空公司——多是廉價航空或獨立經營。放進這個
# 集合是為了讓「查無聯盟」跟「已知獨立」在顯示時可以區分：前者是資料
# 缺口，後者是確定的事實（不必因為不在 AIRLINE_ALLIANCES 裡就顯示得
# 像是資料不全）。
AIRLINE_NO_ALLIANCE = {
    "星宇航空", "捷星航空", "捷星日本航空", "捷星亞洲航空", "樂桃航空",
    "酷航", "虎航", "越捷航空", "亞洲航空", "香草航空", "阿聯酋航空",
}


def _airline_alliance(name):
    """查一家航空公司屬於哪個聯盟。回傳聯盟名稱、`"獨立"`（已知不屬於
    任何聯盟）、或 `None`（未收錄，無法判斷）。用包含比對，見
    `AIRLINE_ALLIANCES` 的說明。
    """
    for key, alliance in AIRLINE_ALLIANCES.items():
        if key in name:
            return alliance
    for key in AIRLINE_NO_ALLIANCE:
        if key in name:
            return "獨立"
    return None


def describe_airlines(airlines):
    """把一組航空公司名稱組成適合顯示的字串，標示聯盟資訊（PO
    2026-09-24：「航空公司不一定是同一家，應該標示航空公司聯盟名稱」）。

    `airlines`：航空公司名稱清單（可能只有 1 個，也可能因四個航段分屬
    不同公司而有多個）。回傳空字串代表沒有資料可顯示。

    三種情況：
    - 只有 1 家：附上聯盟（查得到的話），例如「長榮航空（星空聯盟）」
    - 多家但同一聯盟：以聯盟為主標示，例如「星空聯盟（長榮航空／全日空）」
    - 多家但跨聯盟、或含獨立／未知聯盟成員：不能用單一聯盟概括，逐一
      列出航空公司並明確警示，例如
      「中華航空／捷星日本航空（跨航空公司，非同一聯盟，interline 保障不確定）」——
      這對外站四段票特別重要：第1段缺席會讓後三段全部失效，若組合內
      各航段不是同一聯盟甚至沒有 interline 協議，異動/改簽時能不能
      互相銜接更沒有保障。
    """
    names = [n for n in dict.fromkeys(airlines or []) if n]   # 去重、保序
    if not names:
        return ""
    if len(names) == 1:
        alliance = _airline_alliance(names[0])
        if alliance and alliance != "獨立":
            return "%s（%s）" % (names[0], alliance)
        return names[0]

    alliances = {_airline_alliance(n) for n in names}
    if len(alliances) == 1:
        only = next(iter(alliances))
        if only and only != "獨立":
            return "%s（%s）" % (only, "／".join(names))

    return "%s（跨航空公司，非同一聯盟，interline 保障不確定）" % "／".join(names)



def _parse_months(value):
    """解析排除月份設定：逗號清單或半球快捷。

    快捷刻意標明半球——「summer」本身是有歧義的，南半球目的地的旺季是
    12–2 月（2026-09-23 PO 指正）。保留無字首的 summer 作為 north-summer
    的別名，僅為相容既有用法。
    """
    raw = (value or "").strip().lower()
    if not raw:
        return []
    if raw in ("north-summer", "summer"):
        return list(NORTHERN_SUMMER_MONTHS)
    if raw == "south-summer":
        return list(SOUTHERN_SUMMER_MONTHS)
    months = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = int(part)
        if not 1 <= m <= 12:
            raise ValueError("排除月份必須介於 1-12，收到：%d" % m)
        if m not in months:
            months.append(m)
    return months


def sample_dates(months_ahead=6, per_month=4, trip_days=12, start_date=None,
                 min_lead_days=21, exclude_months=None):
    """在未來 N 個月裡抽樣出發日，回傳 [(出發日, 回程日), ...]。

    瀏覽器路徑沒有 API 額度限制，瓶頸是時間而非次數，所以不需要
    `plan_cheap_trip()` 那種「先用 Deals API 縮小範圍」的兩階段。
    直接抽樣掃描更簡單也更準——Deals API 的結果本身也只是抽樣。

    `min_lead_days`：跳過太近的日期（預設 21 天內不掃）。近期票價本來
    就高，掃了是浪費時間。

    `exclude_months`：要跳過的月份（1–12），**任意複選、可不連續**。
    被排除的月份不計入 `months_ahead`，所以指定排除 6–8 月時，
    `months_ahead=9` 會掃到隔年 1–5 月與 9–12 月共 9 個**實際可用**的
    月份，而不是掃到 9 月就停。
    `NORTHERN_SUMMER_MONTHS` 與 `SOUTHERN_SUMMER_MONTHS` 是兩個半球的
    便利常數，**不是預設值**——南半球目的地的旺季與北半球相反。
    """
    exclude = set(exclude_months or [])
    # 緩衝的用意是「別掃太近的日期」，基準是今天。使用者明確指定未來的
    # start_date 時不該再往後推——否則指定 2027-01-01 會因為多加 21 天
    # 而把整個 1 月跳掉（2026-09-22 實測踩到）。
    floor = datetime.date.today() + datetime.timedelta(days=min_lead_days)
    if start_date:
        earliest = max(datetime.date.fromisoformat(start_date), floor)
    else:
        earliest = floor
    out = []
    cursor = earliest.replace(day=1)
    months_done = 0
    # 上限放寬到 24 個月，避免排除月份把迴圈提早耗盡
    for _ in range(24):
        if months_done >= months_ahead:
            break
        eom = (cursor.replace(day=28) + datetime.timedelta(days=4))
        eom = eom.replace(day=1) - datetime.timedelta(days=1)
        if cursor.month in exclude:
            cursor = eom + datetime.timedelta(days=1)
            continue
        step = max(1, eom.day // per_month)
        added = 0
        for k in range(per_month):
            day = min(1 + k * step, eom.day)
            d = cursor.replace(day=day)
            if d < earliest:
                continue
            out.append((d.isoformat(),
                        (d + datetime.timedelta(days=trip_days)).isoformat()))
            added += 1
        if added:
            months_done += 1
        cursor = eom + datetime.timedelta(days=1)
    return out


def _pick_offset(base_date, candidates, exclude_months, forward):
    """從候選天數中挑第一個「讓偏移後的日期避開指定月份」的值。

    `forward=False` 往前推（第1段在主行程之前），`True` 往後推
    （第4段在回程之後）。兩端邏輯相同，只有方向不同。
    排除月份由呼叫端給定，本函式不假設任何季節定義。

    **候選清單的順序就是偏好順序**——本函式回傳第一個合格值，不做最佳化。
    這一點很容易誤用：2026-09-23 實測時把第4段候選寫成 `[1, 14, 30, …]`，
    結果每組都挑到「延後 1 天」，也就是第4段緊接回程——那正是 PO 想避免的
    密集行程。**避開月份是約束，拉遠是目標，兩者不同**：要拉遠就把大值
    放前面（例如 `[90, 60, 30, 14]`），或直接只給可接受的區間。
    """
    exclude = set(exclude_months or [])
    base = datetime.date.fromisoformat(base_date)
    today = datetime.date.today()
    for days in candidates:
        delta = datetime.timedelta(days=days)
        target = base + delta if forward else base - delta
        if target <= today:
            continue                      # 航段不能排在過去
        if target.month in exclude:
            continue
        return days
    return None


def pick_lead(outbound_date, lead_candidates, exclude_months=None):
    """為主行程出發日挑出讓**第1段**避開指定月份的提前天數。

    PO 2026-09-23 的需求：主行程要避開旺季月份，但第1段也不想落在那些
    月份（那趟外站旅行同樣會撞旺季）。單一 lead 值做不到——以排除 6–8 月
    為例，主行程在 2027-12 時 lead 120 天把第1段推到 8 月、lead 150 推到
    7 月，兩者都被排除；得改用 lead 90（第1段落在 9 月）。

    回傳第一個合格的候選值；全部不合格時回傳 None（該日期應整組跳過）。
    """
    return _pick_offset(outbound_date, lead_candidates, exclude_months, False)


def pick_trail(return_date, trail_candidates, exclude_months=None):
    """為主行程回程日挑出讓**第4段**避開指定月份的延後天數。

    與 `pick_lead()` 對稱。PO 2026-09-23 追加的需求：第3段與第4段的間隔
    也要能設定，理由同樣是**避免密集請假**——第4段（台北→外站）若緊接在
    回程之後就是連續行程；拉遠後可當成下一趟旅行的去程。

    這一端的價格槓桿比第1段更大：PO 提供的對照截圖（SRC-003／SRC-004）
    顯示同樣四個班機、僅第4段由 3/12 挪到 3/24，票價從 NTD 15,225 漲到
    18,564（＋21.9%）。
    """
    return _pick_offset(return_date, trail_candidates, exclude_months, True)


def scan_dates_browser(destination, outstations=None, hub=DEFAULT_HUB,
                       months_ahead=6, per_month=4, trip_days=12, lead=3,
                       trail=1, data_dir=None, currency=DEFAULT_CURRENCY, gl="tw",
                       hl="zh-TW", min_delay_ms=SCRAPE_MIN_DELAY_MS,
                       max_delay_ms=SCRAPE_MAX_DELAY_MS,
                       session_limit=SCRAPE_SESSION_LIMIT, start_date=None,
                       exclude_months=None, progress=None,
                       hourly_limit=HOURLY_BROWSER_LIMIT):
    """【主力功能】日期未定時，用瀏覽器掃出「哪時候、哪個外站最便宜」。

    這是 PO 的核心需求：「你找到便宜的機票，我再看時間是否適合」。

    查詢量 ＝ months_ahead × per_month × 外站數。預設 6×4×7 ＝ 168 次，
    以 5–11 秒節流約需 25–30 分鐘——PO 已表示查詢時間拉長可接受。
    要更快就縮 `per_month` 或先用少數外站粗篩。

    session_limit 會截斷超出的部分（預設 50），這是刻意的保護：一次跑
    太多次會提高封鎖風險。要掃完 168 次請分批執行，已查過的組合會命中
    快取、不重複連線。
    """
    outstations = outstations or JAPAN_OUTSTATIONS
    pairs = sample_dates(months_ahead, per_month, trip_days, start_date,
                         exclude_months=exclude_months)
    itineraries = []
    for outbound, ret in pairs:
        itineraries.extend(build_itineraries_fixed_trip(
            destination, outbound, ret, outstations, hub, [lead], [trail]))

    outcome = scrape_itineraries(
        itineraries, data_dir=data_dir, currency=currency, gl=gl, hl=hl,
        min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms,
        session_limit=session_limit, progress=progress,
        hourly_limit=hourly_limit)
    if outcome.get("error"):
        return {"results": [], "error": outcome["error"], "planned": len(itineraries)}

    priced = [r for r in outcome["results"] if r.get("price") is not None]
    priced.sort(key=lambda r: r.get("total_cost") or r["price"])
    return {
        "results": priced,
        "planned": len(itineraries),
        "scanned": len(outcome["results"]),
        "blocked": outcome.get("blocked", False),
        "soft_blocked": outcome.get("soft_blocked", False),
        "stats": outcome.get("stats", {}),
        "date_pairs": pairs,
    }


def _query_batch(itineraries, token, data_dir=None, currency=DEFAULT_CURRENCY,
                 travel_class=1, adults=1, gl="tw", hl="zh-TW",
                 rate_per_hour=DEFAULT_RATE_PER_HOUR, connector_prices=None,
                 progress=None, budget=None, quota=FREE_TIER_MONTHLY_QUOTA):
    """跑一批行程，回傳 (結果 list, 實際消耗額度)。

    命中快取不計入 budget 也不節流。連續 3 次額度錯誤提早中止。

    `quota` 是本月免費額度上限（預設 250）。每打一次 API 就即時寫入
    `data_dir/flight_usage.json`——額度是「本月用完就沒了」的硬限制，
    即時記帳才不會因為中途中斷而漏記，下次執行又以為還有額度。
    傳 quota=None 可停用額度守衛（例如已改用額度大得多的其他供應商）。
    """
    interval = 3600.0 / rate_per_hour if rate_per_hour else 0.0
    rows = []
    spent = 0
    consecutive_429 = 0
    quota_stop = False
    for idx, itin in enumerate(itineraries):
        if budget is not None and spent >= budget:
            break
        if quota is not None and remaining_quota(data_dir, quota) <= 0:
            quota_stop = True
            break
        outcome = search_itinerary(itin["legs"], token, travel_class, adults,
                                   currency, data_dir, True, gl, hl)
        row = dict(itin)
        row.update(outcome)
        connector = (connector_prices or {}).get(itin["outstation"])
        row["connector_price"] = connector
        if row.get("price") is not None and connector is not None:
            row["total_cost"] = row["price"] + connector
        else:
            row["total_cost"] = row.get("price")
        rows.append(row)

        if not outcome.get("cached"):
            spent += 1
            record_usage(data_dir, 1)
            if "429" in (outcome.get("error") or ""):
                consecutive_429 += 1
                if consecutive_429 >= 3:
                    break
            else:
                consecutive_429 = 0
            if progress:
                progress(idx + 1, len(itineraries), spent, row)
            if interval and idx + 1 < len(itineraries):
                time.sleep(interval)
        elif progress:
            progress(idx + 1, len(itineraries), spent, row)
    if quota_stop and rows:
        rows[-1]["note"] = "本月免費額度已用盡，掃描提前停止"
    return rows, spent


def _cheapest(rows):
    priced = [r for r in rows if r.get("price") is not None]
    if not priced:
        return None
    return min(priced, key=lambda r: r.get("total_cost") or r["price"])


def scan_layered(destination, outbound_date, return_date, token=None,
                 outstations=None, hub=DEFAULT_HUB, lead_days=None,
                 trail_days=None, base_lead=1, base_trail=1, top_k=2,
                 data_dir=None, currency=DEFAULT_CURRENCY, travel_class=1, adults=1,
                 gl="tw", hl="zh-TW", rate_per_hour=DEFAULT_RATE_PER_HOUR,
                 connector_prices=None, progress=None,
                 quota=FREE_TIER_MONTHLY_QUOTA):
    """分層貪婪掃描：先比外站，再調第 1 段，最後調第 4 段。

    為什麼不全組合掃：8 外站 × 15 lead × 15 trail ＝ 1,800 次查詢，遠超
    免費層 250 次/月。分三層各自只動一個維度，約 70 次就能收斂：

        第 1 層　固定 lead/trail，掃所有外站　　　　　　→ len(outstations) 次
        第 2 層　取最便宜的 top_k 外站，掃所有 lead　　 → top_k × len(lead) 次
        第 3 層　取第 2 層最佳組合，掃所有 trail　　　　→ top_k × len(trail) 次

    **已知取捨**：貪婪法假設各維度近似獨立，可能錯過「某外站只在特定
    lead 下才最便宜」這類交互作用。2026-09-22 PO 實例顯示第 4 段日期
    單獨就能造成 21.9% 價差（同樣四個班機，3/12 → 3/24：15,225 → 18,564），
    證明維度本身影響很大；維度之間是否獨立則尚未驗證。要完整掃就直接用
    `build_itineraries_fixed_trip()` 產生全組合再餵 `_query_batch()`。
    """
    outstations = outstations or DEFAULT_OUTSTATIONS
    lead_days = list(DEFAULT_LEAD_DAYS) if lead_days is None else list(lead_days)
    trail_days = list(DEFAULT_TRAIL_DAYS) if trail_days is None else list(trail_days)
    token = _read_token(data_dir, token)

    kw = dict(data_dir=data_dir, currency=currency, travel_class=travel_class,
              adults=adults, gl=gl, hl=hl, rate_per_hour=rate_per_hour,
              connector_prices=connector_prices, progress=progress,
              quota=quota)
    total_spent = 0
    layers = []

    # 第 1 層：哪個外站便宜
    probe = build_itineraries_fixed_trip(
        destination, outbound_date, return_date, outstations, hub,
        [base_lead], [base_trail])
    rows, spent = _query_batch(probe, token, **kw)
    total_spent += spent
    layers.append({"name": "外站比價", "rows": rows, "spent": spent})
    priced = [r for r in rows if r.get("price") is not None]
    if not priced:
        return {"best": None, "layers": layers, "api_calls_spent": total_spent,
                "error": "第 1 層沒有任何組合查到價格，後續層級略過"}
    priced.sort(key=lambda r: r.get("total_cost") or r["price"])
    finalists = [r["outstation"] for r in priced[:top_k]]

    # 第 2 層：第 1 段提早幾天
    lead_probe = build_itineraries_fixed_trip(
        destination, outbound_date, return_date, finalists, hub,
        [d for d in lead_days if d != base_lead], [base_trail])
    rows2, spent2 = _query_batch(lead_probe, token, **kw)
    total_spent += spent2
    layers.append({"name": "第1段日期", "rows": rows2, "spent": spent2})

    best_so_far = _cheapest(rows + rows2)
    if best_so_far is None:
        return {"best": None, "layers": layers, "api_calls_spent": total_spent}

    # 第 3 層：第 4 段延後幾天（PO 實例證明這維度單獨可差 21.9%）
    trail_probe = build_itineraries_fixed_trip(
        destination, outbound_date, return_date, [best_so_far["outstation"]],
        hub, [best_so_far["lead"]],
        [d for d in trail_days if d != best_so_far["trail"]])
    rows3, spent3 = _query_batch(trail_probe, token, **kw)
    total_spent += spent3
    layers.append({"name": "第4段日期", "rows": rows3, "spent": spent3})

    all_rows = rows + rows2 + rows3
    all_priced = [r for r in all_rows if r.get("price") is not None]
    all_priced.sort(key=lambda r: r.get("total_cost") or r["price"])
    return {
        "best": all_priced[0] if all_priced else None,
        "all_results": all_priced,
        "layers": layers,
        "api_calls_spent": total_spent,
        "planned_full_scan": len(outstations) * len(lead_days) * len(trail_days),
    }


def _fmt_legs(legs):
    return " → ".join("%s/%s" % (l["departure_id"], l["date"][5:]) for l in legs) \
        + " → " + legs[-1]["arrival_id"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="外站四段票掃描（SerpApi Google Flights multi-city）")
    parser.add_argument("--destination", required=True,
                        help="目的地機場代碼，例如 CDG")
    parser.add_argument("--month", help="掃描月份 YYYY-MM（行程未定時用：掃整月出發日）")
    parser.add_argument("--outbound", help="主行程去程日 YYYY-MM-DD（第2段，固定）")
    parser.add_argument("--return-date", dest="return_date",
                        help="主行程回程日 YYYY-MM-DD（第3段，固定）")
    parser.add_argument(
        "--lead-days",
        default="%d-%d" % (DEFAULT_LEAD_DAYS[0], DEFAULT_LEAD_DAYS[-1]),
        help="第1段比第2段早幾天，範圍 a-b 或逗號清單")
    parser.add_argument(
        "--trail-days",
        default="%d-%d" % (DEFAULT_TRAIL_DAYS[0], DEFAULT_TRAIL_DAYS[-1]),
        help="第4段比第3段晚幾天，範圍 a-b 或逗號清單。"
             "搭配 --exclude-trail-months 時**順序即偏好**，想拉遠就把大值"
             "放前面（例如 90,60,30），否則會挑到最小值＝第4段緊接回程")
    parser.add_argument("--top-k", type=int, default=2,
                        help="分層掃描中進入第2層的外站數（預設 2）")
    parser.add_argument("--layered", action="store_true",
                        help="分層貪婪掃描（先比外站→再調第1段→再調第4段），"
                             "額度約為全組合掃的 1/10。需搭配 --outbound/--return-date")
    parser.add_argument("--hub", default=DEFAULT_HUB, help="轉機樞紐（預設 TPE）")
    parser.add_argument("--outstations", default=",".join(DEFAULT_OUTSTATIONS),
                        help="候選外站，逗號分隔")
    parser.add_argument("--trip-days", default="10",
                        help="主行程天數，逗號分隔可多值，例如 8,10,12")
    parser.add_argument("--out-stays",
                        default=",".join(str(x) for x in DEFAULT_OUT_STAYS),
                        help="第1段到第2段的日期差，逗號分隔"
                             "（0＝當天轉機、1＝隔日轉機，預設兩者都掃）")
    parser.add_argument("--ret-stays",
                        default=",".join(str(x) for x in DEFAULT_RET_STAYS),
                        help="第3段到第4段的日期差，逗號分隔；第四段可丟到很遠"
                             "的未來，例如 0,30,60")
    parser.add_argument("--data-dir", default="poc/data",
                        help="token 與快取所在目錄（預設 poc/data）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多消耗幾次 API 額度（強烈建議測試時設小值）")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE_PER_HOUR,
                        help="每小時請求數上限（免費層 50）")
    parser.add_argument("--quota", type=int, default=FREE_TIER_MONTHLY_QUOTA,
                        help="本月免費額度上限（預設 %d，0＝不限制）"
                             % FREE_TIER_MONTHLY_QUOTA)
    parser.add_argument("--top", type=int, default=15, help="輸出前幾名")
    parser.add_argument("--out", default=None, help="結果另存 JSON 路徑")
    parser.add_argument("--dry-run", action="store_true",
                        help="只算搜尋空間與成本，不打 API、不需 token")
    parser.add_argument("--scan-dates", action="store_true",
                        help="【主力】用瀏覽器掃出「哪時候、哪個外站最便宜」。"
                             "不需 API key、無額度限制、日期是輸出不是輸入")
    parser.add_argument("--start-date",
                        help="掃描起始日 YYYY-MM-DD（預設今天）")
    parser.add_argument("--exclude-trail-months", default="",
                        help="第4段不可落在的月份，1-12 任意複選逗號分隔。"
                             "快捷同 --exclude-months。啟用時會從 "
                             "--trail-days 為每個主行程回程日各自挑一個"
                             "合格的延後天數（避免第4段緊接回程造成連續行程）")
    parser.add_argument("--exclude-lead-months", default="",
                        help="第1段不可落在的月份，1-12 任意複選逗號分隔"
                             "（例如 2,7,12）。快捷：north-summer=6,7,8、"
                             "south-summer=12,1,2（summer 為 north-summer 的"
                             "別名）。啟用時會從 --lead-days 為每個主行程"
                             "日期各自挑一個合格的提前天數")
    parser.add_argument("--exclude-months", default="",
                        help="排除的月份，1-12 任意複選逗號分隔。快捷："
                             "north-summer=6,7,8、south-summer=12,1,2"
                             "（summer 為 north-summer 的別名）。"
                             "南半球目的地旺季與北半球相反，勿混用")
    parser.add_argument("--per-month", type=int, default=4,
                        help="--scan-dates 每月抽樣幾個出發日（預設 4）")
    parser.add_argument("--session-limit", type=int, default=SCRAPE_SESSION_LIMIT,
                        help="單次執行最多查幾筆（預設 %d）；超出的分批跑，"
                             "已查過的會命中快取" % SCRAPE_SESSION_LIMIT)
    parser.add_argument("--hourly-limit", type=int,
                        default=HOURLY_BROWSER_LIMIT,
                        help="瀏覽器路徑的滾動小時速率上限（預設 %d 筆/小時。"
                             "實測 52 與 205 筆/小時都被擋，此值為保守推估、"
                             "尚未驗證；0＝解除限制，風險自負）"
                             % HOURLY_BROWSER_LIMIT)
    parser.add_argument("--min-delay", type=int, default=SCRAPE_MIN_DELAY_MS,
                        help="查詢間隔下限（毫秒，預設 %d）" % SCRAPE_MIN_DELAY_MS)
    parser.add_argument("--max-delay", type=int, default=SCRAPE_MAX_DELAY_MS,
                        help="查詢間隔上限（毫秒，預設 %d）" % SCRAPE_MAX_DELAY_MS)
    parser.add_argument("--plan-trip", action="store_true",
                        help="【日期未定時用】兩階段規劃：先逐月找便宜主行程"
                             "時段，再對最便宜的幾組日期查四段票。不需指定"
                             "日期——日期是輸出")
    parser.add_argument("--months-ahead", type=int, default=6,
                        help="--plan-trip 往後掃幾個月（預設 6）")
    parser.add_argument("--trip-length", default="10,14",
                        help="可接受的行程天數範圍 min,max（預設 10,14）")
    parser.add_argument("--top-dates", type=int, default=5,
                        help="階段1 取最便宜的幾組日期進入階段2（預設 5）")
    parser.add_argument("--lead", type=int, default=1,
                        help="第1段比第2段早幾天（--plan-trip 用，預設 1）")
    parser.add_argument("--trail", type=int, default=1,
                        help="第4段比第3段晚幾天（--plan-trip 用，預設 1）")
    parser.add_argument("--links", action="store_true",
                        help="產生可直接點開的 Google Flights 四段票查詢網址，"
                             "不打 API、不需 token、不消耗額度")
    parser.add_argument("--links-count", type=int, default=10,
                        help="--links 產生幾組（預設 10）")
    parser.add_argument("--pos", default="tw:zh-TW",
                        help="訂票地 gl:hl，例如 nl:nl（預設 tw:zh-TW）")
    parser.add_argument("--compare-pos", action="store_true",
                        help="拿第一組航段比較各訂票地價差，驗證 POS 是否影響價格"
                             "（耗額度＝POS 數量）")
    parser.add_argument("--connector", action="store_true",
                        help="同時估算台北→各外站的自費接駁票價，並改用"
                             "「四段票價＋接駁價」排序（每個外站多耗 1 次額度）")
    args = parser.parse_args(argv)

    def ints(s):
        """接受 '0,3,7' 或 '0-14' 兩種寫法。"""
        s = s.strip()
        if "-" in s and "," not in s:
            lo, hi = s.split("-", 1)
            return list(range(int(lo), int(hi) + 1))
        return [int(x) for x in s.split(",") if x.strip()]

    if args.outstations.strip().lower() == "japan":
        outstations = list(JAPAN_OUTSTATIONS)
    else:
        outstations = [x.strip().upper()
                       for x in args.outstations.split(",") if x.strip()]
    fixed_mode = bool(args.outbound and args.return_date)
    if (not fixed_mode and not args.month and not args.plan_trip
            and not args.scan_dates):
        print("請擇一：--plan-trip（日期未定，讓系統找便宜時段）、"
              "--month YYYY-MM（掃某個月的出發日），或 "
              "--outbound + --return-date（主行程已定）", file=sys.stderr)
        return 2

    lead_days = ints(args.lead_days)
    trail_days = ints(args.trail_days)
    excl = _parse_months(args.exclude_months)

    lead_excl = _parse_months(args.exclude_lead_months)
    trail_excl = _parse_months(args.exclude_trail_months)

    if args.scan_dates and fixed_mode:
        # 主行程固定、掃 --lead-days／--trail-days：用來測「第1段拉遠多久」
        # 對票價的影響（PO 2026-09-23：想把第1段當成另一趟獨立旅行的回程，
        # 避免密集請假）。走瀏覽器路徑，不耗 API 額度。
        scan_pairs = [(args.outbound, args.return_date)]
        itineraries = build_itineraries_fixed_trip(
            args.destination.upper(), args.outbound, args.return_date,
            outstations, args.hub.upper(), lead_days, trail_days)
    elif args.scan_dates:
        # 日期由抽樣決定，但仍要先枚舉出來——否則 --dry-run／--links
        # 會拿到空清單（甚至去讀不存在的 --month 而崩潰）
        scan_pairs = sample_dates(args.months_ahead, args.per_month,
                                  ints(args.trip_days)[0],
                                  start_date=args.start_date,
                                  exclude_months=excl)
        itineraries = []
        skipped = []
        for _ob, _rt in scan_pairs:
            if lead_excl:
                # 每個主行程日期各自挑一個讓第1段避開排除月份的 lead
                _lead = pick_lead(_ob, ints(args.lead_days), lead_excl)
                if _lead is None:
                    skipped.append("%s(第1段)" % _ob)
                    continue
            else:
                _lead = args.lead
            if trail_excl:
                # 第4段同理，以回程日為基準往後推
                _trail = pick_trail(_rt, ints(args.trail_days), trail_excl)
                if _trail is None:
                    skipped.append("%s(第4段)" % _ob)
                    continue
            else:
                _trail = args.trail
            itineraries.extend(build_itineraries_fixed_trip(
                args.destination.upper(), _ob, _rt, outstations,
                args.hub.upper(), [_lead], [_trail]))
        if skipped:
            print("跳過 %d 個日期（找不到能讓第1段避開排除月份的提前天數）：%s"
                  % (len(skipped), " ".join(skipped)), file=sys.stderr)
    elif args.plan_trip:
        itineraries = []          # 日期由階段1決定，這裡還無從枚舉
    elif fixed_mode:
        itineraries = build_itineraries_fixed_trip(
            args.destination.upper(), args.outbound, args.return_date,
            outstations, args.hub.upper(), lead_days, trail_days)
    else:
        itineraries = build_itineraries(args.destination.upper(), args.month,
                                        outstations, args.hub.upper(),
                                        ints(args.trip_days), ints(args.out_stays),
                                        ints(args.ret_stays))

    if args.links:
        shown = itineraries[:args.links_count]
        print("%d 組查詢網址（共 %d 組組合，零成本，點開即看真實報價）\n"
              % (len(shown), len(itineraries)))
        for itin in shown:
            print("%s  外站 %s" % (_fmt_legs(itin["legs"]), itin["outstation"]))
            print("  %s\n" % google_flights_url(
                itin["legs"], hl="zh-TW", gl="tw", currency=DEFAULT_CURRENCY))
        if len(itineraries) > len(shown):
            print("（還有 %d 組未列出，用 --links-count 調整）"
                  % (len(itineraries) - len(shown)))
        return 0

    if args.dry_run:
        total = len(itineraries)
        hours = total / float(args.rate) if args.rate else 0
        print("搜尋空間：%d 組四段票" % total)
        _ = hours
        if fixed_mode:
            trip_len = itineraries[0]["trip_day"]
            print("  主行程固定：%s 出發 → %s 回（%d 天），只掃前後兩段"
                  % (args.outbound, args.return_date, trip_len))
            print("  外站 %d 個 × 第1段提早 %d 種 × 第4段延後 %d 種"
                  % (len(outstations), len(lead_days), len(trail_days)))
            # 分層掃描是 API 路徑的省額度手段；瀏覽器路徑不耗額度，
            # 且組合數少時分層反而更多次，故不在該模式下建議
            layered = (len(outstations) + args.top_k * len(lead_days)
                       + args.top_k * len(trail_days))
            if not args.scan_dates and layered < total:
                print("  → 分層掃描只需約 %d 次（省 %.0f%%），加 --layered 使用"
                      % (layered, 100.0 * (total - layered) / total))
        elif args.scan_dates:
            print("  抽樣 %d 個日期 × %d 個外站（行程 %d 天）"
                  % (len(scan_pairs), len(outstations), ints(args.trip_days)[0]))
            print("  月份：%s"
                  % " ".join(sorted(set(p[0][:7] for p in scan_pairs))))
            print("  ※ 瀏覽器路徑不耗 API 額度，單批上限 %d 筆"
                  % args.session_limit)
        else:
            print("  外站 %d 個 × 出發日 %d 天 × 停留/天數組合 %d 種"
                  % (len(outstations), len(_month_days(args.month)),
                     len(ints(args.trip_days)) * len(ints(args.out_stays))
                     * len(ints(args.ret_stays))))
        if args.scan_dates:
            left = None
            per = (args.min_delay + args.max_delay) / 2000.0 + 8
            print("耗時：以 %.0f 秒/筆估算約 %.0f 分鐘"
                  % (per, total * per / 60.0))
        else:
            used = read_usage(args.data_dir)["count"]
            left = remaining_quota(args.data_dir, args.quota)
            print("額度：需 %d 次查詢；本月已用 %d／%d，剩 %d 次 → %s"
                  % (total, used, args.quota, left,
                     "夠" if total <= left else "不夠，缺 %d 次" % (total - left)))
        if not args.scan_dates:
            print("耗時：以 %d 次/小時節流約需 %.1f 小時" % (args.rate, hours))
        if left is not None and total > left:
            print("建議：用 --layered 分層掃描（固定行程模式），或縮小 "
                  "--outstations／--lead-days／--trail-days 範圍。"
                  "免費額度每月 1 號重置，不必付費。")
        ret_max = max(ints(args.ret_stays))
        if not fixed_mode and not args.scan_dates and ret_max < 14:
            print("\n提醒：--ret-stays 最大只有 %d 天。第四段可以排到很遠的未來"
                  "（實例是隔 57 天），掃不到那種組合就可能錯過更低的票價。"
                  "試試 --ret-stays 0,30,60。" % ret_max)
        print("\n前 3 組範例：")
        for itin in itineraries[:3]:
            print("  %s" % _fmt_legs(itin["legs"]))
        return 0

    try:
        gl, hl = args.pos.split(":", 1)
    except ValueError:
        print("--pos 格式應為 gl:hl，例如 nl:nl", file=sys.stderr)
        return 2

    if args.scan_dates:
        if not scraper_available():
            print("瀏覽器路徑未就緒：請在 %s 執行 npm install"
                  % SCRAPER_DIR, file=sys.stderr)
            return 2
        trip = ints(args.trip_days)[0]
        pairs = scan_pairs
        total = len(itineraries)
        est_min = total * ((args.min_delay + args.max_delay) / 2000.0 + 6) / 60.0
        used_now = read_browser_usage(args.data_dir)["count"]
        print("掃描 %d 個日期 × %d 個外站 = %d 筆，預估 %.0f 分鐘"
              "（最近一小時已查 %d／%d）"
              % (len(pairs), len(outstations), total, est_min,
                 used_now, args.hourly_limit), file=sys.stderr)
        if total > args.session_limit:
            print("超過單次上限 %d 筆，本次先跑 %d 筆；重跑會接續"
                  "（已查過的命中快取）"
                  % (args.session_limit, args.session_limit), file=sys.stderr)

        if fixed_mode:
            outcome = scrape_itineraries(
                itineraries, data_dir=args.data_dir, gl=gl, hl=hl,
                min_delay_ms=args.min_delay, max_delay_ms=args.max_delay,
                session_limit=args.session_limit, progress=True,
                hourly_limit=args.hourly_limit or None)
            priced = [r for r in outcome["results"]
                      if r.get("price") is not None]
            priced.sort(key=lambda r: r["price"])
            report = {"results": priced, "planned": len(itineraries),
                      "scanned": len(outcome["results"]),
                      "blocked": outcome.get("blocked", False),
                      "soft_blocked": outcome.get("soft_blocked", False),
                      "error": outcome.get("error")}
        else:
            report = scan_dates_browser(
                args.destination.upper(), outstations=outstations,
                hub=args.hub.upper(), months_ahead=args.months_ahead,
                per_month=args.per_month, trip_days=trip, lead=args.lead,
                trail=args.trail, data_dir=args.data_dir, gl=gl, hl=hl,
                min_delay_ms=args.min_delay, max_delay_ms=args.max_delay,
                session_limit=args.session_limit, start_date=args.start_date,
                exclude_months=excl, progress=True,
                hourly_limit=args.hourly_limit or None)
        if report.get("error"):
            print("失敗：%s" % report["error"], file=sys.stderr)
            return 1
        if report.get("blocked"):
            kind = ("連續逾時（軟封鎖）" if report.get("soft_blocked")
                    else "明確封鎖頁")
            print("\n⚠️ 偵測到%s，掃描已中止。已完成的結果仍有效且已存快取，"
                  "重跑會接續未完成的部分。建議隔數小時再試，"
                  "或加大 --min-delay／--max-delay。" % kind, file=sys.stderr)
        rows = report["results"]
        print("\n=== %s 四段票，依價格排序（查 %d／%d 筆）==="
              % (args.destination.upper(), report["scanned"],
                 report["planned"]))
        if not rows:
            print("沒有任何組合查到價格。")
            return 1
        if fixed_mode:
            print("%-6s %-12s %-5s %-9s %s"
                  % ("提前", "第1段日期", "外站", "四段票(NTD)", "航空"))
            for row in rows[:args.top]:
                # 2026-09-24：四段航程不一定同一家航空公司，改標示聯盟
                # （PO 要求），不再只取第一段的航空公司名稱
                print("%-6s %-12s %-5s %-9s %s"
                      % ("%d天" % row["lead"], row["legs"][0]["date"],
                         row["outstation"], format(int(row["price"]), ","),
                         describe_airlines(row.get("airlines") or [])))
        else:
            print("%-12s %-12s %-5s %-9s %s"
                  % ("出發", "回程", "外站", "四段票(NTD)", "航空"))
            for row in rows[:args.top]:
                print("%-12s %-12s %-5s %-9s %s"
                      % (row["legs"][1]["date"], row["legs"][2]["date"],
                         row["outstation"], format(int(row["price"]), ","),
                         describe_airlines(row.get("airlines") or [])))
        print("\n提醒：上表未含台北→外站的自費接駁票；"
              "第1段（外站→台北）一定要搭，否則後三段全部失效。")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            print("完整結果：%s" % args.out)
        return 0

    token = _read_token(args.data_dir)
    if not token:
        print("SERPAPI_KEY 未設定：請放進 %s/serpapi_token.txt 或設環境變數"
              % args.data_dir, file=sys.stderr)
        return 2

    quota = args.quota if args.quota > 0 else None
    left = remaining_quota(args.data_dir, args.quota) if quota else None
    if quota is not None and left <= 0:
        print("本月免費額度已用完（%d／%d）。額度每月 1 號重置；"
              "或用 --quota 0 解除限制（僅在你已確認不會產生費用時）。"
              % (read_usage(args.data_dir)["count"], args.quota),
              file=sys.stderr)
        return 2

    # 全組合掃在固定行程模式下動輒數千次，遠超免費額度——先擋下來
    if quota is not None and not args.layered and len(itineraries) > left:
        print("預計需要 %d 次查詢，但本月只剩 %d 次。"
              % (len(itineraries), left), file=sys.stderr)
        if fixed_mode:
            print("→ 加上 --layered 改用分層掃描（約 %d 次即可）"
                  % (len(outstations) + args.top_k * len(lead_days)
                     + args.top_k * len(trail_days)), file=sys.stderr)
        else:
            print("→ 或加 --limit N 限制本次用量，之後分批續掃"
                  "（已查過的組合會命中快取、不重複扣額度）", file=sys.stderr)
        return 2

    if args.plan_trip:
        def plan_progress(done, total, spent, item):
            # 階段1 傳的是 search_deals 結果，階段2 傳的是行程 row，形狀不同
            if "deals" in item:
                n = len(item.get("deals", []))
                print("[階段1 %d/%d 用量%d] %s → %d 筆候選"
                      % (done, total, spent, item.get("window", ""), n),
                      file=sys.stderr)
            else:
                price = item.get("price")
                print("[階段2 %d/%d 用量%d] %s %s"
                      % (done, total, spent, item.get("outstation", ""),
                         int(price) if price else
                         (item.get("error") or "無結果")),
                      file=sys.stderr)

        conn = None
        if args.connector:
            probe = (datetime.date.today()
                     + datetime.timedelta(days=90)).isoformat()
            print("估算台北→各外站接駁票價（代表日期 %s）…" % probe,
                  file=sys.stderr)
            conn = estimate_connectors(outstations, probe, token,
                                       hub=args.hub.upper(),
                                       data_dir=args.data_dir, gl=gl, hl=hl,
                                       quota=quota)

        result = plan_cheap_trip(
            args.hub.upper(), args.destination.upper(), token,
            outstations=outstations, months_ahead=args.months_ahead,
            trip_length=args.trip_length, top_dates=args.top_dates,
            lead=args.lead, trail=args.trail, data_dir=args.data_dir,
            gl=gl, hl=hl, rate_per_hour=args.rate, quota=quota,
            connector_prices=conn, progress=plan_progress)

        s1 = result["stage1"]
        print("\n=== 階段1：逐月掃 %s↔%s 主行程（行程 %s 天）==="
              % (args.hub.upper(), args.destination.upper(), args.trip_length))
        print("  掃 %d 個月，找到 %d 筆候選時段，耗額度 %d 次"
              % (s1["months_scanned"], len(s1["deals"]),
                 s1["api_calls_spent"]))
        if not result.get("stage2"):
            print("\n%s" % result.get("error", "階段2 未執行"))
            return 1
        for deal in result["stage2"]["candidates"]:
            print("    %s → %s  %s"
                  % (deal["outbound_date"], deal["return_date"],
                     format(int(deal["price"]), ",")))

        rows = result["stage2"]["results"]
        print("\n=== 階段2：四段票（%d 外站 × %d 組日期，耗額度 %d 次）==="
              % (len(outstations), len(result["stage2"]["candidates"]),
                 result["stage2"]["spent"]))
        if not rows:
            print("沒有任何四段票組合查到價格。")
            return 1
        has_conn = any(r.get("connector_price") for r in rows)
        header = "%-24s %-5s %-9s" % ("主行程日期", "外站", "四段票")
        if has_conn:
            header += " %-8s %-9s" % ("接駁", "總成本")
        print(header)
        for row in rows[:args.top]:
            line = "%-24s %-5s %-9s" % (
                "%s~%s" % (row["legs"][1]["date"], row["legs"][2]["date"]),
                row["outstation"], format(int(row["price"]), ","))
            if has_conn:
                c, tc = row.get("connector_price"), row.get("total_cost")
                line += " %-8s %-9s" % (format(int(c), ",") if c else "-",
                                        format(int(tc), ",") if tc else "-")
            print(line)
        if has_conn:
            print("\n接駁價為單一代表日期的估算值，實際購買前請重查。")
        else:
            print("\n注意：上表未計入台北→外站的自費接駁票。"
                  "加 --connector 會一併估算並改用總成本排序"
                  "（每個外站多耗 1 次額度）。")
        print("\n提醒：第1段（外站→台北）一定要搭，不能 no-show，"
              "否則後三段全部失效。")
        print("\n本月額度：已用 %d／%d，剩 %d 次"
              % (read_usage(args.data_dir)["count"], args.quota,
                 remaining_quota(args.data_dir, args.quota)))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print("完整結果：%s" % args.out)
        return 0

    if args.compare_pos:
        legs = itineraries[0]["legs"]
        print("比較訂票地價差，航段：%s\n" % _fmt_legs(legs))
        report = compare_pos(legs, token, data_dir=args.data_dir)
        print("%-6s %-8s %s" % ("國家", "語言", "價格"))
        for row in report["rows"]:
            price = row.get("price")
            print("%-6s %-8s %s" % (row["gl"], row["hl"],
                                    int(price) if price else
                                    (row.get("error") or "無結果")))
        spread = report["spread"]
        if spread:
            print("\n價差：%d（最低 %d、最高 %d，差 %.1f%%）"
                  % (spread["diff"], spread["low"], spread["high"],
                     spread["pct"]))
            print("→ %s" % ("價差顯著，POS 應納入搜尋維度"
                            if spread["pct"] >= 3
                            else "價差可忽略，全掃固定用 tw 即可"))
        else:
            print("\n可比價的結果不足 2 筆，無法判斷 POS 影響。")
        return 0

    connector_prices = None
    if args.connector:
        probe_date = itineraries[0]["base_date"]
        print("估算台北→各外站接駁票價（%s）…" % probe_date, file=sys.stderr)
        connector_prices = estimate_connectors(
            outstations, probe_date, token, hub=args.hub.upper(),
            data_dir=args.data_dir, gl=gl, hl=hl, quota=quota)
        for station, price in sorted(connector_prices.items()):
            print("  %s %s" % (station, int(price) if price else "查無"),
                  file=sys.stderr)

    def progress(done, total, spent, row):
        mark = "快取" if row.get("cached") else "查詢"
        price = row.get("price")
        desc = ("%s" % int(price)) if price else (row.get("error") or "無結果")
        print("[%d/%d 用量%d] %s %s %s"
              % (done, total, spent, mark, row["outstation"], desc),
              file=sys.stderr)

    if args.layered:
        if not fixed_mode:
            print("--layered 需要 --outbound 與 --return-date", file=sys.stderr)
            return 2
        result = scan_layered(
            args.destination.upper(), args.outbound, args.return_date,
            token=token, outstations=outstations, hub=args.hub.upper(),
            lead_days=lead_days, trail_days=trail_days, top_k=args.top_k,
            data_dir=args.data_dir, gl=gl, hl=hl, rate_per_hour=args.rate,
            connector_prices=connector_prices, progress=progress)
        print("\n=== 分層掃描結果（耗額度 %d 次，全組合掃需 %d 次）==="
              % (result["api_calls_spent"], result.get("planned_full_scan", 0)))
        for layer in result["layers"]:
            priced = [r for r in layer["rows"] if r.get("price") is not None]
            best = min(priced, key=lambda r: r.get("total_cost") or r["price"]) \
                if priced else None
            print("  %-10s 查 %2d 次，最佳 %s"
                  % (layer["name"], layer["spent"],
                     ("%s %d" % (best["outstation"], int(best["price"])))
                     if best else "無"))
        best = result.get("best")
        if not best:
            print("\n沒有任何組合查到價格：%s" % result.get("error", ""))
            return 1
        print("\n最便宜組合：")
        print("  外站 %s／第1段早 %d 天／第4段晚 %d 天"
              % (best["outstation"], best["lead"], best["trail"]))
        print("  航段 %s" % _fmt_legs(best["legs"]))
        print("  四段票 %d" % int(best["price"]))
        if best.get("connector_price"):
            print("  接駁票 %d（台北→%s，估算）"
                  % (int(best["connector_price"]), best["outstation"]))
            print("  總成本 %d" % int(best["total_cost"]))
        print("\n本月額度：已用 %d／%d，剩 %d 次"
              % (read_usage(args.data_dir)["count"], args.quota,
                 remaining_quota(args.data_dir, args.quota)))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print("\n完整結果：%s" % args.out)
        return 0

    report = scan(args.destination.upper(), args.month,
                  outstations=outstations, hub=args.hub.upper(),
                  trip_days=ints(args.trip_days), out_stays=ints(args.out_stays),
                  ret_stays=ints(args.ret_stays), data_dir=args.data_dir,
                  limit=args.limit, rate_per_hour=args.rate, progress=progress,
                  token=token, connector_prices=connector_prices,
                  gl=gl, hl=hl, quota=quota)

    print("\n=== %s %s 外站四段票（查 %d／%d 組，耗額度 %d 次）==="
          % (args.destination.upper(), args.month, report["queried"],
             report["planned"], report["api_calls_spent"]))
    if not report["results"]:
        print("沒有任何組合查到價格。失敗樣本：")
        for row in report["failures"][:3]:
            print("  %s → %s" % (row["outstation"], row.get("error") or "無結果"))
        return 1
    has_conn = any(r.get("connector_price") for r in report["results"])
    if has_conn:
        print("%-5s %-8s %-8s %-8s %-10s %s"
              % ("外站", "四段票", "接駁", "總成本", "出發日", "航段"))
        for row in report["results"][:args.top]:
            conn = row.get("connector_price")
            total = row.get("total_cost")
            print("%-5s %-8d %-8s %-8s %-10s %s"
                  % (row["outstation"], int(row["price"]),
                     int(conn) if conn else "-",
                     int(total) if total else "-",
                     row["base_date"], _fmt_legs(row["legs"])))
        print("\n接駁價為單一代表日期的估算值，實際購買前請重查。")
    else:
        print("%-5s %-6s %-10s %s" % ("外站", "價格", "出發日", "航段"))
        for row in report["results"][:args.top]:
            print("%-5s %-6d %-10s %s"
                  % (row["outstation"], int(row["price"]), row["base_date"],
                     _fmt_legs(row["legs"])))
        print("\n注意：未計入台北→外站的自費接駁票（加 --connector 才會算進排序）。")
    print("\n本月額度：已用 %d／%d，剩 %d 次"
          % (read_usage(args.data_dir)["count"], args.quota,
             remaining_quota(args.data_dir, args.quota)))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("\n完整結果：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
