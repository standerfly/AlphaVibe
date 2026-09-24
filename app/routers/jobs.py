"""排程健康狀態路由：GET /api/jobs/health（2026-09-17 架構體檢 B4）。

資料來源是 `poc/kb-mcp/check_scheduled_jobs.py` 每天 04:00 巡檢後寫下的
狀態檔，這裡只負責讀出來給前端。**刻意不在請求裡即時重跑巡檢**：巡檢
要開資料庫、掃備份目錄，讓每個開首頁的請求都做這些事既慢又沒必要，
而且首頁要顯示的本來就是「最近一次排程跑得怎麼樣」這種每天才變一次
的資訊。

跟 `/api/healthz` 的差別（名字很像，用途完全不同）：
- `/api/healthz`：服務本身還活著嗎，給 uptime 探測用，**不需認證**
- `/api/jobs/health`：昨晚的排程跑成功了嗎，給首頁橫幅用，需要認證

狀態檔不存在時回 `status: "unknown"` 而不是 500——巡檢還沒跑過第一次
（例如剛部署）是正常情況，不是錯誤。前端對 unknown 不顯示橫幅。
"""
import json
import os

from fastapi import APIRouter

router = APIRouter()

# 跟 check_scheduled_jobs.py 的 DEFAULT_STATE_FILE 對齊。允許用環境變數
# 覆寫，測試才能指到暫存檔而不必碰使用者真正的狀態檔。
_STATE_FILE = os.environ.get(
    "ALPHAVIBE_HEALTH_STATE_FILE",
    os.path.expanduser("~/Library/Logs/alphavibe-health.json"))


@router.get("/api/jobs/health")
def jobs_health() -> dict:
    """最近一次排程巡檢的結果。

    回傳結構直接沿用狀態檔的格式（status／checked_at／critical_count／
    warning_count／findings），不另外轉換——多一層轉換就多一個要跟著
    改的地方，而這份 JSON 的消費者只有首頁橫幅一個。
    """
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return {"status": "unknown", "reason": "巡檢尚未執行過", "findings": []}
    except (OSError, ValueError) as exc:
        # 檔案在但讀不了/壞了，這本身就值得知道
        return {"status": "unknown", "reason": "狀態檔無法讀取：%s" % exc,
                "findings": []}

    state.setdefault("status", "unknown")
    state.setdefault("findings", [])
    return state
