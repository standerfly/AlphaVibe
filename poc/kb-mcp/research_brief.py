"""SRC-013 Stage 1（MVP）「研究啟動包」（候選FR-060）。

背景與設計依據：`docs/spec-intake/alphavibe/raw/src-013-research-brief-tool-
design.md`（延續SRC-012）。完整checklist七節骨架見
`docs/spec-intake/alphavibe/supporting-artifacts/
2026-08-10-framework-pre-buy-research-checklist-draft.md`。

## 核心設計原則（不要違反）

1. **只做機械蒐集＋排版，不呼叫任何LLM生成敘事**——跟 `review_engine.py`
   的 `_growth_deceleration`／`_downside_risk` 同等級：純粹是既有工具
   回傳值的直接組裝或簡單機械運算（取最新一筆、算比率），沒有任何
   「判斷」或「推理」。方向A vs方向B（全自動生成報告）的取捨見上述
   SRC-013討論文件——方向B已評估並排除（幻覺風險＋FR-021/FR-026
   「自動結構化結論0%使用」的既有教訓）。
2. **checklist七節裡只有「財務體檢」多數可查數字**，其餘六節
   （業務理解／產業結構／預期差／破裂條件／估值敘事／收斂四問）本質是
   判斷，本函式固定回傳 `status: "needs_discussion"` 佔位，不強行生成
   文字去填——這六節的討論結論仍照舊寫回 `save_stance` 的 `reason`／
   `risk_factor`，不在這裡處理。
3. **「查不到資料源」與「需要對話判斷」是兩種不同性質的留白，用不同
   status值區分**（SRC-013核心設計原則）：
   - `no_data_source`：AlphaVibe目前沒有對應資料源可查（毛利率／營業
     利益率、現金流量表、法說會Q&A逐字稿——這是已知的資料邊界，Stage 1
     ~4都解決不了，需要PO自行從外部資訊補進對話，不是「尚未實作」）
   - `needs_discussion`：不是資料查詢問題，本質是PO與Claude對話中的
     判斷（護城河、TAM、預期差、破裂條件、估值情境敘事、收斂四問）
   - 財務體檢裡實際有資料源的五項（營收品質／估值／法人籌碼／近期股價／
     資產負債表）另外自成一類：`ok`（查詢成功，即使部分欄位因資料不足
     為null）／`query_failed`（底層查詢本身失敗，附errors說明）——跟上面
     兩種固定佔位的status不同，這裡的status反映「這次呼叫的實際結果」。

## 資料源選用（官方優先 vs 直接FinMind，逐項說明理由）

- 營收年增率：`finmind_client.get_revenue_yoy`（完整多月序列，判斷趨勢用）
  ＋ `fundamentals_client.get_revenue_yoy_latest`（最新一期，官方TWSE/TPEx
  優先＋FinMind備援）——沿用 `server.py` `get_revenue_yoy` 工具既有的
  組合方式，理由同 `fundamentals_client` 模組docstring：官方無多月歷史
  序列來源，多月序列維持FinMind單一來源；最新一期才有官方優先包裝。
- 估值PER/PBR/殖利率：`fundamentals_client.get_valuation`（官方優先＋
  FinMind備援），不重複呼叫 `finmind_client.get_fundamentals`（那個函式
  綁了近6個月原始營收，這裡的營收面已由上面的revenue_yoy涵蓋，不需要
  重複資料）。
- 三大法人籌碼：`finmind_client.get_institutional_trading`直接呼叫（近30天
  預設窗口）——`fundamentals_client.py` 對此無官方優先包裝（官方無對應
  結構化批次端點），沿用既有 `server.py` `get_institutional_trading`
  工具的唯一資料源。
- 股價歷史：`finmind_client.get_stock_price_history`直接呼叫（近90天
  預設窗口）——同上，`fundamentals_client.py` 對股價序列無官方優先包裝，
  沿用既有 `server.py` `get_stock_price_history` 工具的唯一資料源。
- 資產負債表：`finmind_client.get_balance_sheet_summary`（本次SRC-013任務
  新增，見該函式docstring）——FinMind無官方優先來源可比較，直接使用。

僅標準庫依賴（透過 finmind_client／fundamentals_client）。Python 3.9 相容。
外部查詢失敗不丟例外，比照全專案既有慣例（finmind_client／fundamentals_
client／review_engine），失敗時該欄位status標記query_failed並附note，
不中斷整個啟動包組裝。

## Stage 2（對照組交叉驗證，本次新增）

`prepare_research_brief` 新增可選參數 `peers`：未指定時只用一次
`get_stock_info` 全量查詢篩出同產業候選名單（`peer_candidates`），不對
候選逐檔查財務資料；有指定時對每個peer重跑財務體檢五項並排呈現
（`peer_comparison`），純數字不做評語/排名判斷（方向A原則延伸）。詳見
`_peer_candidates`／`_peer_comparison` docstring。
"""
import datetime

import finmind_client
import fundamentals_client

# 財務體檢裡三項AlphaVibe目前無資料源、Stage 1~4皆解決不了的欄位（SRC-013
# 第5節「已知蓋不到的資料」）：毛利率/營業利益率無API、現金流量表無API、
# 法說會Q&A逐字稿台股無官方結構化API（MOPS只有簡報PDF）。note文字沿用
# SRC-013文件用語，不是本函式臨時編的。
NO_DATA_SOURCE_FINANCIAL_FIELDS = {
    "gross_margin_operating_leverage": "目前AlphaVibe無毛利率/營業利益率資料源",
    "cash_flow": "目前AlphaVibe無現金流量表資料源",
    "earnings_call_qa": "台股無官方結構化API，需PO自行聽打貼入",
}

# 頂層六節（checklist七節扣掉「財務體檢」）本質是判斷非查詢，固定
# needs_discussion，note點出對應checklist小節與判斷提問方向，方便PO與
# Claude對話時知道該從哪裡接著問（引用 pre-buy-research-checklist 模組
# 小節標題，不是本函式臨時編的措辭）。
NEEDS_DISCUSSION_SECTIONS = {
    "business_understanding": "業務理解（三句話）：賣什麼/市場多大、誰付錢、"
        "護城河為何——需要PO與Claude對話判斷，非查詢",
    "industry_structure": "產業結構（五問）：TAM、產業週期、定價權、競爭格局、"
        "價值鏈瓶頸——多數判斷，僅營收趨勢等間接線索可查，非查詢",
    "expectation_gap": "預期差：市場現在的股價已反映多少預期，落差在哪一邊——"
        "完全判斷，台股無免費結構化分析師共識預期API可查",
    "thesis_break_conditions": "投資論點破裂條件：什麼情況代表這次判斷錯了——"
        "本身是討論結論，非查詢對象",
    "valuation_narrative": "估值：情境敘事（保守/正常/樂觀三句話，不做目標價"
        "數字表）——判斷，吃財務數字當輸入但敘事本身是綜合判斷，非查詢",
    "converging_questions": "收斂：買進前四問——走完以上六節後的最終判斷收斂，"
        "非查詢",
}


def _revenue_quality(code, data_dir, token):
    series = finmind_client.get_revenue_yoy(code, data_dir=data_dir, token=token)
    latest = fundamentals_client.get_revenue_yoy_latest(code, data_dir=data_dir, token=token)

    if "revenue_yoy" not in series:
        errs = series.get("errors") or []
        if latest.get("error"):
            errs = errs + [latest["error"]]
        return {"status": "query_failed", "latest_yoy": None, "latest_period": None,
                "latest_data_source": None, "recent_trend": [],
                "note": "；".join(errs) or "查詢失敗，原因不明"}

    # 近6個月（比照 finmind_client.get_fundamentals 既有 [-6:] 慣例），
    # 保留null值不過濾，讓PO看得到「這幾個月查不到」而不是悄悄跳過。
    recent_trend = [
        {"revenue_year": row.get("revenue_year"), "revenue_month": row.get("revenue_month"),
         "yoy_growth": row.get("yoy_growth")}
        for row in series["revenue_yoy"][-6:]
    ]
    note = None
    if latest.get("revenue_yoy") is None:
        note = latest.get("error") or "最新一期年增率查無非null資料（可能新掛牌不滿一年或資料延遲）"
    return {"status": "ok", "latest_yoy": latest.get("revenue_yoy"),
            "latest_period": latest.get("revenue_period"),
            "latest_data_source": latest.get("data_source"),
            "recent_trend": recent_trend, "note": note}


def _valuation(code, data_dir, token):
    val = fundamentals_client.get_valuation(code, data_dir=data_dir, token=token)
    return {"status": "query_failed" if val.get("error") else "ok",
            "per": val.get("per"), "pbr": val.get("pbr"),
            "dividend_yield": val.get("dividend_yield"),
            "data_source": val.get("data_source"), "market": val.get("market"),
            "note": val.get("error")}


def _institutional_flow(code, data_dir, token):
    trading = finmind_client.get_institutional_trading(code, data_dir=data_dir, token=token)
    if "trading" not in trading:
        return {"status": "query_failed", "foreign_net": None, "latest_date": None,
                "trading_days": 0, "note": "；".join(trading.get("errors") or ["查詢失敗，原因不明"])}

    dates = sorted({row.get("date") for row in trading["trading"] if row.get("date")})
    return {"status": "ok", "foreign_net": trading.get("foreign_net"),
            "latest_date": dates[-1] if dates else None,
            "trading_days": len(dates), "note": None}


def _price_history_recent(code, data_dir, token):
    price = finmind_client.get_stock_price_history(code, data_dir=data_dir, token=token)
    if "prices" not in price:
        return {"status": "query_failed", "latest_close": None, "latest_date": None,
                "period_high": None, "period_low": None, "data_points": 0,
                "note": "；".join(price.get("errors") or ["查詢失敗，原因不明"])}

    rows = price["prices"]
    closes = [row.get("close") for row in rows if row.get("close") is not None]
    highs = [row.get("max") for row in rows if row.get("max") is not None]
    lows = [row.get("min") for row in rows if row.get("min") is not None]
    latest = rows[-1] if rows else {}
    return {"status": "ok", "latest_close": latest.get("close"),
            "latest_date": latest.get("date"),
            "period_high": max(highs) if highs else None,
            "period_low": min(lows) if lows else None,
            "data_points": len(rows), "note": None}


def _balance_sheet(code, data_dir, token):
    balance = finmind_client.get_balance_sheet_summary(code, data_dir=data_dir, token=token)
    if balance.get("balance_sheet_date") is None:
        return {"status": "query_failed", "balance_sheet_date": None,
                "cash_and_equivalents": None, "current_liabilities": None,
                "total_liabilities": None, "total_assets": None, "debt_ratio": None,
                "note": "；".join(balance.get("errors") or ["查詢失敗，原因不明"])}
    return {"status": "ok", "balance_sheet_date": balance.get("balance_sheet_date"),
            "cash_and_equivalents": balance.get("cash_and_equivalents"),
            "current_liabilities": balance.get("current_liabilities"),
            "total_liabilities": balance.get("total_liabilities"),
            "total_assets": balance.get("total_assets"),
            "debt_ratio": balance.get("debt_ratio"), "note": None}


def _peer_candidates(code, data_dir, token):
    """SRC-013 Stage 2：`peers` 未指定時，用同一批 `get_stock_info` 全量
    查詢結果篩出同產業分類的其他股票代碼，只當「候選名單」給PO自己選，
    **不對任何候選額外呼叫財務相關API**（2026-07-28 FinMind額度打光連累
    正式排程的教訓，見專案CLAUDE.md教訓紀錄，避免同產業幾十檔被逐一查詢）。

    只查一次 `get_stock_info` 全量（不帶stock_id，TaiwanStockInfo為靜態
    參考表，單次API呼叫即可拿到全市場）。查無`code`對應的產業分類、或
    該產業只有自己一檔時，`candidates`為空list，不視為錯誤中斷。
    """
    info = finmind_client.get_stock_info(data_dir=data_dir, token=token)
    stocks = info.get("stocks") or []

    industry = None
    for row in stocks:
        if row.get("stock_id") == code:
            industry = row.get("industry_category")
            break

    if not industry:
        return {"industry": industry, "candidates": []}

    candidates = [
        {"code": row.get("stock_id"), "name": row.get("stock_name")}
        for row in stocks
        if row.get("industry_category") == industry and row.get("stock_id") != code
    ]
    return {"industry": industry, "candidates": candidates}


def _peer_comparison(peers, data_dir, token):
    """SRC-013 Stage 2：`peers` 有指定時，對每個peer code重跑跟主標的一樣
    的財務體檢五項（直接呼叫既有的 `_revenue_quality`／`_valuation`／
    `_institutional_flow`／`_price_history_recent`／`_balance_sheet`，不
    複製貼上邏輯）。純數字並排，不做任何評語/排名/「誰比較好」的判斷——
    這是方向A的核心原則（SRC-013第2節），判斷留給PO與Claude對話決定。
    """
    return {
        peer: {
            "revenue_quality": _revenue_quality(peer, data_dir, token),
            "valuation": _valuation(peer, data_dir, token),
            "institutional_flow": _institutional_flow(peer, data_dir, token),
            "price_history_recent": _price_history_recent(peer, data_dir, token),
            "balance_sheet": _balance_sheet(peer, data_dir, token),
        }
        for peer in peers
    }


VALID_ANALYSIS_MODES = ("full", "monitoring")


def prepare_research_brief(code, store, analysis_mode=None, peers=None, data_dir=None, token=None):
    """組裝「研究啟動包」：財務體檢五個有資料源小節查實際數字，其餘三個
    財務小節與頂層六節固定佔位（見模組docstring status三分法）。不呼叫
    任何LLM，全部是既有工具回傳值的直接組裝或簡單機械運算。

    Stage 3（本次新增，硬性程式閘門——SRC-013 2026-08-11測試結論：純文字
    description提醒會被模型用「不確定就查、可逆低成本不用問」等全域原則
    推理繞過，改用程式碼層面直接擋下）：呼叫前用`store.get_holdings`／
    `store.get_latest_stance`檢查該標的是否已有持股或現行立場記錄。若有，
    且`analysis_mode`未帶或不是合法值（"full"／"monitoring"），直接短路
    回傳`{"gate": "confirm_analysis_mode_required", ...}`，**不查任何
    financial_check資料**（連帶省下FinMind額度）——呼叫端必須先問PO要哪種
    分析角度，帶著PO的答案再呼叫一次，不可自行判斷。查無持股/立場記錄的
    全新標的不受此限，直接照原邏輯產出完整結果，不用多問。

    通過閘門後，回傳最外層新增`analysis_mode`欄位，記錄這次實際使用的
    模式：`"full"`／`"monitoring"`（沿用呼叫端帶入的合法值）／
    `"n/a_no_existing_record"`（全新標的，本來就不需要選模式）。

    `peers`（SRC-013 Stage 2，對照組交叉驗證，可選）：
    - 未指定（None，預設）：不查任何額外財務資料，只用一次
      `get_stock_info`全量查詢篩出同產業分類的候選代碼，放進
      `peer_candidates`（`{"industry": ..., "candidates": [...]}`），
      給PO自己決定要不要指定其中幾檔當對照組。
    - 有指定（例如`["2303", "3711"]`）：對每個peer code重跑財務體檢
      五項，並排放進`peer_comparison`（`{peer_code: {...五項...}, ...}`），
      不做任何評語/排名判斷。
    - 兩個欄位互斥，一次呼叫只產生其中一個，不會同時出現。
    """
    holdings = store.get_holdings(code=code)
    has_holdings = bool(holdings.get("count"))
    latest_stance = store.get_latest_stance(code)
    has_stance = bool(latest_stance)

    if (has_holdings or has_stance) and analysis_mode not in VALID_ANALYSIS_MODES:
        stance_summary = None
        if latest_stance:
            stance_summary = {
                "stance": latest_stance.get("stance"),
                "date": latest_stance.get("date"),
                "name": latest_stance.get("name"),
            }
        return {
            "code": code,
            "gate": "confirm_analysis_mode_required",
            "message": ("此標的已有持股/立場記錄，請先問PO要（a）完整研究"
                        "checklist六問（analysis_mode=\"full\"）、還是（b）"
                        "針對現有立場的持倉監控式檢視（analysis_mode="
                        "\"monitoring\"），PO選定後帶analysis_mode參數再"
                        "呼叫。不可自行判斷或直接套用其中一種。"),
            "has_holdings": has_holdings,
            "has_stance": has_stance,
            "latest_stance_summary": stance_summary,
        }

    resolved_mode = analysis_mode if (has_holdings or has_stance) else "n/a_no_existing_record"

    financial_check = {
        "revenue_quality": _revenue_quality(code, data_dir, token),
        "valuation": _valuation(code, data_dir, token),
        "institutional_flow": _institutional_flow(code, data_dir, token),
        "price_history_recent": _price_history_recent(code, data_dir, token),
        "balance_sheet": _balance_sheet(code, data_dir, token),
    }
    for field, note in NO_DATA_SOURCE_FINANCIAL_FIELDS.items():
        financial_check[field] = {"status": "no_data_source", "note": note}

    brief = {
        "code": code,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "analysis_mode": resolved_mode,
        "financial_check": financial_check,
    }
    for section, note in NEEDS_DISCUSSION_SECTIONS.items():
        brief[section] = {"status": "needs_discussion", "note": note}

    if peers:
        brief["peer_comparison"] = _peer_comparison(peers, data_dir, token)
    else:
        brief["peer_candidates"] = _peer_candidates(code, data_dir, token)

    return brief
