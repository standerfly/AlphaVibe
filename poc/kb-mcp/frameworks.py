"""第二層全市場批次篩選：多框架門檻清單（方案A輕量設計）。

不做資料庫 CRUD 介面；新增/修改框架用講的，由 AI 改這份清單常數，改完
要重啟 report_server（launchd kickstart）跟下次排程才會生效。

⚠️ industries 目前刻意設計成必填、不支援 None（代表全市場）：Q-030
（docs/spec-intake/alphavibe/scope-decision.md）的決策是先限定產業別、
不做全市場無差別掃描。要新增「不限產業」的框架前，須先跟使用者確認掃描
範圍怎麼收斂，不要讓 AI 自行假設用全市場。

peg_max 可以是 None，代表這個框架「不看 PEG」（例如 revenue_high_price_dip
只看營收年增率＋回檔區間，不要求本益成長比便宜）——market_scan.py 的
`if peg_max is not None and (...)` 判斷式已經自然支援這個語意，不用另外改。

排程行為變更（2026-07-28）：market_scan.py 的 launchd plist 沒有改（仍是
`market_scan.py --trigger scheduled`），CLI 預設行為改成「不給 --framework
就跑全部框架」後，排程自然變成每天跑 FRAMEWORKS 裡的全部框架，執行時間
會變長（見 market_scan.py 的 run_scans() docstring）。

FR-052 策略專屬層（2026-07-29 新增）：每個框架可選配一個 "invalidation"
欄位，定義「這套策略的假說什麼時候算失效」，供 review_engine.py 的
strategy_specific_review() 使用。**語意方向跟 entry 門檻相反**——entry
門檻（peg_max/drawdown_min/...）是「全部條件都要符合」才算進場候選；
invalidation 是「任一子條件成立」就算假說失效，不用全部觸發。
invalidation dict 可能用到的 key：
- peg_min：PEG 回升到 >= 此值即失效（PEG 越低代表相對成長性越便宜，
  回升代表這個優勢消失）
- drawdown_max：回檔幅度 <= 此值即失效（回檔收斂，代表當初「跌深」
  的優勢已不存在）
- revenue_yoy_max：營收年增率 <= 此值即失效（成長動能轉弱甚至由正轉負）
某個框架的 invalidation dict 沒定義某個 key，代表「這個框架不用這個
條件判斷失效」（跟 screener.meets_framework_thresholds() 的 None＝不看
這項條件是同一種語意，方便理解，但這裡是用「key 不存在」不是「值為
None」來表示，因為 invalidation 整個 key 本身是可選的）。
"""

FRAMEWORKS = [
    {
        # ⚠️ 必須維持在 list 第 0 位：default_framework_id() 取 FRAMEWORKS[0]，
        # 網頁與 CLI（省略 --framework 時的舊行為、report.py 的預設分頁）都靠這個順序。
        "id": "peg_deep_dip_concentration",
        "label": "PEG深度回檔＋集中持股（老芋頭實戰邏輯）",
        "philosophy_module": "framework_peg_deep_dip_concentration",
        "industries": ("半導體業", "電子零組件業", "其他電子業"),
        "peg_max": 1.0,
        "revenue_yoy_min": 0.0,
        "drawdown_min": 0.40,
        "drawdown_max": None,
        "excess_drawdown_min": None,
        "invalidation": {"peg_min": 1.0, "drawdown_max": 0.15},
    },
    {
        "id": "revenue_high_price_dip",
        "label": "營收創高／年增強勁但股價跌深補漲候選",
        "philosophy_module": "framework_revenue_high_price_dip",
        "industries": ("半導體業", "電子零組件業", "其他電子業"),
        "peg_max": None,
        "revenue_yoy_min": 0.30,
        "drawdown_min": 0.15,
        # 與框架0的「回檔>=40%」互補分割，但邊界重疊：回檔恰好等於0.40的
        # 個股會同時符合兩個框架（框架0是>=，這裡是<=），這是刻意的，
        # 不是bug——兩個框架本來就允許同一檔在兩份候選名單裡都出現。
        "drawdown_max": 0.40,
        "excess_drawdown_min": None,
        "sort_by": "excess_drawdown",
        # framework_revenue_high_price_dip.md 的量化規則第1項是「近3個月營收
        # 創新高，或年增率>30%」——OR分支的前半段（創新高）批次API拿不到
        # （TWSE/TPEx批次端點只有當月一筆快照，沒有歷史區間可比對創高），
        # 本次只實作「年增率>30%」這個分支，兩邊都要顯示這個限制。
        "revenue_condition_note": "只實作「年增率>30%」分支，「近3個月營收創新高」批次API查不到，未實作",
        # 量化規則第2/4/5項（來源：framework_revenue_high_price_dip.md:9-16）
        # 工具查不到，只能由人工逐檔查證，UI要顯示提醒：
        "manual_conditions": [
            "EPS 是否仍持續上修（法人預估上調中，需查法說會/財報，非量化欄位）",
            "外資是否沒有出現長期、大幅撤退（需查連續多日籌碼動向，非單日快照）",
            "AI 營收占比是否持續提升，或公司法說會維持正向展望（產業定性判斷）",
        ],
        "invalidation": {"drawdown_max": 0.15, "revenue_yoy_max": 0.0},
    },
]


def get_framework(framework_id):
    for fw in FRAMEWORKS:
        if fw["id"] == framework_id:
            return fw
    return None


def default_framework_id():
    return FRAMEWORKS[0]["id"]
