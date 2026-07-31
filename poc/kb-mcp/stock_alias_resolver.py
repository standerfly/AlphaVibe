"""股票名稱→代碼解析共用邏輯（2026-07-30 抽出）。

背景：trade_text_parser.py（老芋頭進出批次解析，FR-044）原本自己實作一套
「名稱→代碼」比對邏輯；新增 trade_ledger_parser.py（PO自己的交易明細表
解析，FR-056）需要一模一樣的邏輯。兩邊格式不同（老芋頭批次共用一個日期、
交易明細表每列自帶日期），但名稱解析規則完全相同，值得共用、不要複製
貼上兩份。

解析規則：
1. 先查 store.get_stock_alias(name) 快取，命中直接用
2. 未命中的名稱，整批只呼叫一次 finmind_client.get_stock_info() 建立
   「正規化名稱→代碼」比對表（去除連字號/空白後比對，例如FinMind的
   「世芯-KY」要能比對PO輸入的「世芯KY」），命中就存回 stock_aliases
   快取（下次直接命中步驟1，不必再查FinMind）
3. 兩者都未命中的名稱，歸入 unresolved_names，呼叫端不應該用假代碼寫入

僅標準庫 + finmind_client，不碰資料庫寫入以外的邏輯（stock_aliases 快取
寫入透過 store.save_stock_alias）。Python 3.9 相容。
"""
import finmind_client

# 名稱正規化時要去除的字元：連字號（比對FinMind「世芯-KY」vs PO輸入
# 「世芯KY」）、全形/半形空白。
_NORMALIZE_TRANSLATE = str.maketrans("", "", "-－ 　\t")


def normalize_name(name):
    """去除連字號與空白差異，供股票名稱比對用（不改變大小寫，股票名稱
    多為中文＋大寫英文字母，暫不需要大小寫正規化）。"""
    return (name or "").translate(_NORMALIZE_TRANSLATE)


def resolve_stock_codes(names, store, data_dir=None, token=None, alias_source=None):
    """把一批股票名稱解析成代碼，整批只呼叫一次 finmind_client.get_stock_info
    （而不是逐筆查）。

    names：股票名稱清單，可能含重複——內部會先去重，每個不重複名稱只查
    一次 store.get_stock_alias。
    alias_source：解析成功時寫回 stock_aliases 快取的 source 欄位文字，
    呼叫端應帶入能辨識來源的說明（例如「老芋頭進出批次解析自動比對」）。

    回傳 (resolved, unresolved_names)：
    - resolved：{name: code} 只含解析成功的名稱
    - unresolved_names：查無代碼的不重複名稱清單，依 names 首次出現順序
    """
    unique_names = []
    seen_names = set()
    for name in names:
        if name and name not in seen_names:
            seen_names.add(name)
            unique_names.append(name)

    resolved = {}
    pending_names = []
    for name in unique_names:
        alias = store.get_stock_alias(name)
        if alias.get("found"):
            resolved[name] = alias["record"]["code"]
        else:
            pending_names.append(name)

    if pending_names:
        info = finmind_client.get_stock_info(data_dir=data_dir, token=token)
        finmind_lookup = {}
        for stock in (info.get("stocks") or []):
            norm = normalize_name(stock.get("stock_name"))
            if norm and norm not in finmind_lookup:
                finmind_lookup[norm] = stock.get("stock_id")
        for name in pending_names:
            code = finmind_lookup.get(normalize_name(name))
            if code:
                resolved[name] = code
                store.save_stock_alias(name, code, source=alias_source)
            # 找不到的名稱先不放進 resolved，下面用 unique_names 過濾算出
            # unresolved_names。

    unresolved_names = [name for name in unique_names if name not in resolved]
    return resolved, unresolved_names
