"""第二層選股篩選：全市場批次初篩（Stage A）。

背景：第一層 `screener.py` 需要使用者手動貼候選代碼清單，逐檔查 FinMind。
第二層改用 TWSE／TPEx 官方 OpenAPI 的批次端點（一次回傳全市場當日 PER／
月營收年增率快照），在框架鎖定的產業別內快速初篩候選，不用逐檔查。

⚠️ 關鍵限制（2026-07-22 實測查證，不是猜的）：TWSE／TPEx 這些批次端點
**只回傳最新一個交易日，沒有日期區間參數**，算不出股價回檔幅度。回檔幅度
仍要靠 Stage B（`screener.compute_drawdown`）逐檔查 FinMind 歷史股價補上——
Stage A 只負責用 PER＋營收年增率把 1700+ 檔縮小到幾十~一百多檔候選，
把逐檔查詢的成本壓在可接受範圍。

⚠️ 範圍只有「上市＋上櫃」：興櫃沒有官方批次 PER 端點，維持現況用
`tpex_client.get_emerging_stock_valuation()` 逐檔估算，不受這個模組影響。

僅標準庫（urllib），錯誤處理風格比照 finmind_client.py／tpex_client.py：
不丟例外、回傳 {"error": ...}。TWSE／TPEx 兩個資料源各自獨立
try/except——一邊掛了不能讓另一邊也篩不出來。
"""
import argparse
import json
import os
import urllib.error
import urllib.request

import frameworks
import screener

TIMEOUT = 15
USER_AGENT = "alphavibe-kb-poc"

TWSE_PER_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_PER_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


def _fetch_json(url, market_label):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": "%s HTTP %s" % (market_label, exc.code)}
    except Exception as exc:  # 網路不通、逾時、JSON 壞掉
        return {"error": "%s 呼叫失敗：%s" % (market_label, exc)}
    if not isinstance(payload, list):
        return {"error": "%s 回應格式異常（非陣列）" % market_label}
    return {"data": payload}


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _revenue_period(roc_yyyymm):
    """民國年月字串（如 "11506"）轉 "2026-06"；格式不符回傳 None，不丟例外。"""
    if not isinstance(roc_yyyymm, str) or not roc_yyyymm.isdigit():
        return None
    if len(roc_yyyymm) not in (5, 6):
        return None
    try:
        year = int(roc_yyyymm[:-2]) + 1911
        month = int(roc_yyyymm[-2:])
        if not 1 <= month <= 12:
            return None
        return "%04d-%02d" % (year, month)
    except ValueError:
        return None


def _scan_market(market, per_url, revenue_url, per_code_field, per_ratio_field,
                  industries, peg_max, revenue_yoy_min):
    """單一市場（TWSE 或 TPEx）批次初篩。整段包 try/except，任何一步失敗
    都回傳 {"market":.., "error":.., "candidates": [], "total_scanned": 0}，
    不丟例外。

    total_scanned＝月營收批次的資料列數（迴圈實際跑過、逐列檢查產業別的
    公司總數），在拿到營收批次資料後立刻記錄，不受後續產業別/PEG篩選
    影響——這樣就算最後篩不出任何候選，也能如實反映「有查過多少家公司」。
    """
    try:
        per_resp = _fetch_json(per_url, market)
        if "error" in per_resp:
            return {"market": market, "error": per_resp["error"],
                    "candidates": [], "total_scanned": 0}
        per_map = {}
        for row in per_resp["data"]:
            code = row.get(per_code_field)
            if code:
                per_map[code] = row

        revenue_resp = _fetch_json(revenue_url, market)
        if "error" in revenue_resp:
            return {"market": market, "error": revenue_resp["error"],
                    "candidates": [], "total_scanned": 0}
        total_scanned = len(revenue_resp["data"])

        candidates = []
        for row in revenue_resp["data"]:
            industry = row.get("產業別")
            if industry not in industries:
                continue
            code = row.get("公司代號")
            if not code:
                continue

            per_row = per_map.get(code)
            per = _to_float(per_row.get(per_ratio_field)) if per_row else None

            yoy_pct = _to_float(row.get("營業收入-去年同月增減(%)"))
            yoy = yoy_pct / 100 if yoy_pct is not None else None
            if revenue_yoy_min is not None and (yoy is None or yoy <= revenue_yoy_min):
                continue

            # PEG = 本益比 / 營收年增率(%數字)。yoy<=0 或缺資料時算不出來，
            # 維持 None，不可以除以零或用負成長率算出負PEG（跟screener.py
            # 的PEG計算規則一致，兩層篩選門檻語意要一致）。
            peg = None
            if per is not None and yoy is not None and yoy > 0:
                peg = per / (yoy * 100)
            if peg_max is not None and (peg is None or peg >= peg_max):
                continue

            candidates.append({
                "code": code,
                "name": row.get("公司名稱"),
                "market": market,
                "industry": industry,
                "per": per,
                "revenue_yoy": yoy,
                "revenue_period": _revenue_period(row.get("資料年月")),
                "peg": peg,
            })
        return {"market": market, "error": None, "candidates": candidates,
                "total_scanned": total_scanned}
    except Exception as exc:  # 單一市場非預期錯誤不可讓另一市場也篩不出來
        return {"market": market, "error": "非預期錯誤：%s" % exc,
                "candidates": [], "total_scanned": 0}


def scan_candidates(framework):
    """對框架鎖定的產業別做全市場（上市+上櫃）批次初篩。

    framework 是 frameworks.FRAMEWORKS 裡的一筆 dict（需含 industries／
    peg_max／revenue_yoy_min）。TWSE／TPEx 各自獨立呼叫 `_scan_market`，
    互不影響——回傳的 market_errors 分別記錄兩邊狀況，任一邊失敗仍會
    回傳另一邊篩出的候選，不會整批槓龜。

    興櫃不在範圍內（見模組 docstring）。
    """
    industries = framework["industries"]
    peg_max = framework["peg_max"]
    revenue_yoy_min = framework["revenue_yoy_min"]

    twse = _scan_market("TWSE", TWSE_PER_URL, TWSE_REVENUE_URL,
                         "Code", "PEratio", industries, peg_max, revenue_yoy_min)
    tpex = _scan_market("TPEx", TPEX_PER_URL, TPEX_REVENUE_URL,
                         "SecuritiesCompanyCode", "PriceEarningRatio",
                         industries, peg_max, revenue_yoy_min)

    candidates = twse["candidates"] + tpex["candidates"]
    candidates.sort(key=lambda c: (c["peg"] is None, c["peg"] if c["peg"] is not None else 0))
    return {
        "candidates": candidates,
        "codes": [c["code"] for c in candidates],
        "market_errors": {"TWSE": twse["error"], "TPEx": tpex["error"]},
        "total_scanned": twse["total_scanned"] + tpex["total_scanned"],
    }


def run_scan(framework_id, data_dir=None, token=None, trigger_source="manual"):
    """Stage A → Stage B 串接：批次初篩候選，再逐檔查 FinMind 補回檔幅度、
    套框架門檻。Stage A 算出的 PER/年增率/PEG 直接採用（不在這裡用 FinMind
    重查一次，效能考量的取捨，已與使用者確認）；Stage B 只補「回檔幅度」
    這一項批次API查不到的資料。

    不寫資料庫（持久化交給呼叫端，例如 server.py 接上
    KBStore.save_market_scan_run）；回傳 dict 讓呼叫端自行決定要不要存。
    """
    framework = frameworks.get_framework(framework_id)
    if framework is None:
        return {"error": "未知框架：%s" % framework_id}

    stage_a = scan_candidates(framework)
    rows = []
    for cand in stage_a["candidates"]:
        row = dict(cand)
        drawdown_info = screener.compute_drawdown(cand["code"], data_dir=data_dir, token=token)
        row["drawdown_pct"] = drawdown_info["drawdown_pct"]
        row["high_price"] = drawdown_info["high_price"]
        row["high_date"] = drawdown_info["high_date"]
        row["current_price"] = drawdown_info["current_price"]
        row["current_date"] = drawdown_info["current_date"]
        row["error"] = drawdown_info["error"]
        row["meets_framework"] = screener.meets_framework_thresholds(
            row.get("peg"), row.get("drawdown_pct"),
            peg_threshold=framework.get("peg_max"),
            drawdown_min=framework.get("drawdown_min"),
            drawdown_max=framework.get("drawdown_max"))
        rows.append(row)

    rows.sort(key=lambda r: (r["peg"] is None, r["peg"] if r["peg"] is not None else 0))
    meets_count = sum(1 for r in rows if r["meets_framework"])
    return {
        "framework_id": framework_id,
        "trigger_source": trigger_source,
        "candidate_count": len(rows),
        "meets_count": meets_count,
        "market_errors": stage_a["market_errors"],
        "total_scanned": stage_a["total_scanned"],
        "results": rows,
    }


def default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ALPHAVIBE_DATA_DIR") or os.path.join(here, "..", "data")


def main(argv=None):
    """CLI 入口，供 launchd 排程呼叫（`--trigger scheduled`）；也可手動跑
    `python3 market_scan.py` 立即測試一次，不用等排程時間到。"""
    from kb_store import KBStore  # noqa: E402（延後匯入，避免CLI以外的用途也要背這個依賴）

    parser = argparse.ArgumentParser(description="第二層全市場批次篩選（Stage A+B）")
    parser.add_argument("--framework", default=None, help="框架代號（預設用 frameworks.default_framework_id()）")
    parser.add_argument("--data-dir", default=None, help="資料目錄（預設 poc/data）")
    parser.add_argument("--trigger", default="scheduled", choices=("scheduled", "manual"))
    args = parser.parse_args(argv)

    framework_id = args.framework or frameworks.default_framework_id()
    data_dir = os.path.abspath(args.data_dir or default_data_dir())

    result = run_scan(framework_id, data_dir=data_dir, trigger_source=args.trigger)
    if "error" in result:
        print("market_scan失敗：%s" % result["error"])
        return 1

    store = KBStore(data_dir)
    try:
        saved = store.save_market_scan_run(
            framework_id, args.trigger, result["results"],
            result["candidate_count"], market_errors=result["market_errors"],
            total_scanned=result["total_scanned"])
    finally:
        store.close()

    print("market_scan完成：framework=%s trigger=%s total_scanned=%d candidate_count=%d "
          "meets_count=%d run_id=%d run_at=%s TWSE_error=%s TPEx_error=%s"
          % (framework_id, args.trigger, result["total_scanned"], result["candidate_count"],
             result["meets_count"], saved["run_id"], saved["run_at"],
             result["market_errors"]["TWSE"], result["market_errors"]["TPEx"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
