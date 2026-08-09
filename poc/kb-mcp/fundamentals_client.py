"""單股估值／營收查詢：官方來源優先，FinMind 降級為備援（2026-08-01，
來源選用邏輯稽核修正）。

背景：稽核發現「官方來源優先、FinMind降級為備援」這個既定架構原則
（screener._fetch_prices_with_fallback／benchmark._fetch_benchmark 已經是
正確範例）在低流量個股查詢路徑（screener.py 的PER/PEG部分、
review_engine.py、server.py）完全沒落實，直接寫死呼叫 finmind_client。
本模組補上這一層，供三個呼叫點共用：

- get_valuation(code)：單一股票最新一期 PER/PBR/殖利率。
- get_revenue_yoy_latest(code)：單一股票最新一期月營收年增率。
- get_per_history(code)：單一股票歷史PER序列（FR-051下檔風險模型用）。

介面設計精神照抄 screener._fetch_prices_with_fallback()：呼叫端只認一個
來源中立的函式，內部自己決定先打官方、失敗才 fallback FinMind，呼叫端
完全不用知道底層是誰。不丟例外，查詢徹底失敗時回傳同樣的 key 結構、
值為 None＋error 訊息，比照 finmind_client／screener 系列函式的既有慣例。

⚠️ 月營收「多月歷史序列」（給 review_engine._growth_deceleration 判斷連續
趨勢用）刻意不在這個模組的範圍內——官方查無乾淨的個股歷史營收API（MOPS
的表單頁不是API，不整合），這部分維持直接呼叫 finmind_client.get_revenue_yoy
當唯一來源，不做官方優先包裝（PO已確認範圍：只有「最新一期單筆」才需要
官方優先＋FinMind備援）。

批次估值/營收端點的URL、欄位對映、HTTP fetch邏輯（含cache/錯誤處理）全部
重用 market_scan.py 既有的 _fetch_json／TWSE_PER_URL／TWSE_REVENUE_URL／
TPEX_PER_URL／TPEX_REVENUE_URL／TWSE_PER_EXTRA_FIELDS／
TPEX_PER_EXTRA_FIELDS／_to_float／_revenue_period，不重寫一份新的fetch
邏輯——market_scan.py本身是全市場批次篩選用的，這裡只是從同一份批次回應
裡挑出單一代碼那一列，做逐股查詢用途。歷史PER序列則重用
twse_price_client.fetch_per_history()（BWIBBU逐月合併，同一套模式）。

⚠️ 本模組對 market_scan 的 import 刻意延遲到函式內部（不在模組頂層），
理由：market_scan.py 本身在模組頂層 `import screener`，若 screener.py 也
在模組頂層 `import fundamentals_client`（screen_stocks() 要重用這裡的
函式），三個模組會形成 screener→fundamentals_client→market_scan→screener
的匯入環。函式內延遲匯入時，這個環只會在「函式真正被呼叫」那一刻才需要
market_scan已經載入完成，而不是在「模組載入」那一刻——三個模組不論從
哪一個入口先被 import，到函式真正執行時全部都已經載入完畢，不會有
ImportError／AttributeError。finmind_client／twse_price_client 兩個模組
本身零專案內部依賴，維持模組頂層 import 不會有這個問題。

僅標準庫依賴（透過 finmind_client／twse_price_client／market_scan）。
Python 3.9 相容。
"""
import finmind_client
import twse_price_client


def _official_valuation(code, cache=None):
    """依序試 TWSE、TPEx 官方PER批次端點，回傳該代碼那一列的
    per/pbr/dividend_yield/market；兩個市場批次資料裡都查無該代碼、或
    兩邊批次端點本身都查詢失敗，回傳 None（呼叫端據此 fallback FinMind，
    不細分「查無該代碼」跟「端點本身失敗」，跟
    screener._fetch_prices_with_fallback 對 twse_price_client 錯誤的處理
    方式一致）。"""
    import market_scan  # 延遲匯入，見模組 docstring 說明理由

    for market, url, code_field, ratio_field, extra_fields in (
            ("TWSE", market_scan.TWSE_PER_URL, "Code", "PEratio",
             market_scan.TWSE_PER_EXTRA_FIELDS),
            ("TPEx", market_scan.TPEX_PER_URL, "SecuritiesCompanyCode",
             "PriceEarningRatio", market_scan.TPEX_PER_EXTRA_FIELDS)):
        resp = market_scan._fetch_json(url, market, cache=cache)
        if "error" in resp:
            continue
        for row in resp["data"]:
            if row.get(code_field) == code:
                return {
                    "per": market_scan._to_float(row.get(ratio_field)),
                    "pbr": market_scan._to_float(row.get(extra_fields.get("pbr"))),
                    "dividend_yield": market_scan._to_float(
                        row.get(extra_fields.get("dividend_yield"))),
                    "market": market,
                }
    return None


def get_valuation(code, data_dir=None, token=None, cache=None):
    """單一股票最新一期 PER/PBR/殖利率：官方優先（依序試TWSE、TPEx批次
    端點裡有沒有這個代碼），兩者都查無資料/失敗才 fallback
    finmind_client.get_fundamentals 的估值部分。

    回傳 {"per","pbr","dividend_yield","market","data_source","error"}。
    data_source：「twse_official」／「tpex_official」／「finmind_fallback」；
    market：找到資料的那個市場別（"TWSE"/"TPEx"/None），fallback FinMind時
    為 None（FinMind批次不分市場，這裡不臆測）。絕不丟例外。
    """
    try:
        official = _official_valuation(code, cache=cache)
        if official is not None:
            return {
                "per": official["per"], "pbr": official["pbr"],
                "dividend_yield": official["dividend_yield"],
                "market": official["market"],
                "data_source": "twse_official" if official["market"] == "TWSE"
                               else "tpex_official",
                "error": None,
            }
        fund = finmind_client.get_fundamentals(code, data_dir=data_dir, token=token)
        valuation = fund.get("valuation")
        if valuation:
            return {
                "per": valuation.get("PER"), "pbr": valuation.get("PBR"),
                "dividend_yield": valuation.get("dividend_yield"),
                "market": None, "data_source": "finmind_fallback", "error": None,
            }
        return {
            "per": None, "pbr": None, "dividend_yield": None, "market": None,
            "data_source": "finmind_fallback",
            "error": "；".join(fund.get("errors") or ["官方與FinMind皆查無估值資料"]),
        }
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        return {"per": None, "pbr": None, "dividend_yield": None, "market": None,
                "data_source": None, "error": "非預期錯誤：%s" % exc}


def _official_revenue(code, cache=None):
    """依序試 TWSE、TPEx 官方月營收批次端點，回傳該代碼那一列的
    revenue_yoy/revenue_period/market；規則同 `_official_valuation`。"""
    import market_scan  # 延遲匯入，見模組 docstring 說明理由

    for market, url in (("TWSE", market_scan.TWSE_REVENUE_URL),
                        ("TPEx", market_scan.TPEX_REVENUE_URL)):
        resp = market_scan._fetch_json(url, market, cache=cache)
        if "error" in resp:
            continue
        for row in resp["data"]:
            if row.get("公司代號") == code:
                yoy_pct = market_scan._to_float(row.get("營業收入-去年同月增減(%)"))
                yoy = yoy_pct / 100 if yoy_pct is not None else None
                return {
                    "revenue_yoy": yoy,
                    "revenue_period": market_scan._revenue_period(row.get("資料年月")),
                    "market": market,
                }
    return None


def get_revenue_yoy_latest(code, data_dir=None, token=None, cache=None):
    """單一股票最新一期月營收年增率：官方優先（依序試TWSE、TPEx批次端點），
    兩者都查無資料/失敗才 fallback finmind_client.get_revenue_yoy 裡「最新
    一筆非null」的年增率（挑選邏輯重用 screener._latest_yoy_growth，跟
    screen_stocks() 既有的挑選規則保持一致，不另外發明一套）。

    回傳 {"revenue_yoy","revenue_period","market","data_source","error"}，
    語意同 get_valuation()。絕不丟例外。⚠️ 這裡只回「最新一期」，多月
    趨勢序列（給 review_engine._growth_deceleration 用）不在本函式範圍
    （見模組 docstring），呼叫端仍需另外呼叫 finmind_client.get_revenue_yoy
    取得完整序列。
    """
    try:
        official = _official_revenue(code, cache=cache)
        if official is not None:
            return {
                "revenue_yoy": official["revenue_yoy"],
                "revenue_period": official["revenue_period"],
                "market": official["market"],
                "data_source": "twse_official" if official["market"] == "TWSE"
                               else "tpex_official",
                "error": None,
            }
        import screener  # 延遲匯入，見模組 docstring 說明理由（重用挑選邏輯）
        rev = finmind_client.get_revenue_yoy(code, data_dir=data_dir, token=token)
        if rev.get("errors"):
            # FinMind查詢本身真的失敗（網路/額度/查無此代碼）才算error。
            return {"revenue_yoy": None, "revenue_period": None, "market": None,
                    "data_source": "finmind_fallback", "error": "；".join(rev["errors"])}
        yoy, period = screener._latest_yoy_growth(rev.get("revenue_yoy") or [])
        # 查詢成功但挑不出非null年增率（例如剛掛牌不足一年、資料點不足）
        # 不算error，維持None——跟改動前 screen_stocks() 從不檢查這種情況
        # 的既有靜默降級行為一致，不要用error訊息汙染這個常見的正常情境。
        return {"revenue_yoy": yoy, "revenue_period": period, "market": None,
                "data_source": "finmind_fallback", "error": None}
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        return {"revenue_yoy": None, "revenue_period": None, "market": None,
                "data_source": None, "error": "非預期錯誤：%s" % exc}


def get_per_history(code, data_dir=None, token=None, window_days=730, cache=None):
    """單一股票歷史PER序列（FR-051下檔風險模型用）：TWSE股票走官方BWIBBU
    stockNo逐月合併（twse_price_client.fetch_per_history），查無資料
    （TPEx股票／官方端點失敗任何原因）一律 fallback
    finmind_client.get_per_history。TPEx沒有對應官方歷史端點（見
    twse_price_client 模組docstring），不需要先判斷市場別，直接嘗試TWSE
    官方端點即可，查無資料自然會fallback。

    回傳 dict，"per_history" 鍵存在時結構同 finmind_client.get_per_history
    （date/PER/PBR/dividend_yield），額外附 "data_source"
    （"twse_official"/"finmind_fallback"）。查詢徹底失敗（官方查無資料
    且FinMind也失敗）時沒有 "per_history" 鍵，"errors" 說明原因——跟
    finmind_client.get_per_history 原本「查無資料時不給 per_history 鍵」
    的既有慣例一致，呼叫端（review_engine._downside_risk）本來就是用
    `"per_history" not in per_result` 判斷資料是否足夠，不用改讀取邏輯。
    """
    try:
        official = twse_price_client.fetch_per_history(
            code, window_days=window_days, cache=cache)
        if "error" not in official and official.get("per_history"):
            return {"stock_id": code, "per_history": official["per_history"],
                    "data_source": "twse_official", "errors": []}
        fallback = finmind_client.get_per_history(
            code, days=window_days, data_dir=data_dir, token=token)
        fallback["data_source"] = "finmind_fallback"
        return fallback
    except Exception as exc:  # 絕不丟例外中斷呼叫端
        return {"stock_id": code, "errors": ["非預期錯誤：%s" % exc], "data_source": None}
