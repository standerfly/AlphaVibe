"""第二層全市場批次篩選：多框架門檻清單（方案A輕量設計）。

不做資料庫 CRUD 介面；新增/修改框架用講的，由 AI 改這份清單常數，改完
要重啟 report_server（launchd kickstart）跟下次排程才會生效。

⚠️ industries 目前刻意設計成必填、不支援 None（代表全市場）：Q-030
（docs/spec-intake/alphavibe/scope-decision.md）的決策是先限定產業別、
不做全市場無差別掃描。要新增「不限產業」的框架前，須先跟使用者確認掃描
範圍怎麼收斂，不要讓 AI 自行假設用全市場。
"""

FRAMEWORKS = [
    {
        "id": "peg_deep_dip_concentration",
        "label": "PEG深度回檔＋集中持股（老芋頭實戰邏輯）",
        "philosophy_module": "framework_peg_deep_dip_concentration",
        "industries": ("半導體業", "電子零組件業", "其他電子業"),
        "peg_max": 1.0,
        "revenue_yoy_min": 0.0,
        "drawdown_min": 0.40,
        "drawdown_max": None,
    },
]


def get_framework(framework_id):
    for fw in FRAMEWORKS:
        if fw["id"] == framework_id:
            return fw
    return None


def default_framework_id():
    return FRAMEWORKS[0]["id"]
