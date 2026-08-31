"""STND「管家」分頁：監控＋聊天介面，串接 telegram_gateway 共用狀態。

背景：`/Users/stander/My_project/AI/telegram_gateway/`（獨立 repo、獨立
Python 行程，long-polling Telegram）已經常駐上線，靠呼叫本機 headless
`claude` CLI（`-p ... --resume`／`--bg ...`）跟使用者對話，並把對話記憶
（domain-keyed session_id）、用量、稽核紀錄寫進共用的
`telegram_gateway/state/*` 檔案。這支 router 是同一套「管家大腦」的
**第二個輸入/監看管道**——讓 STND 網頁也能讀寫同一份共用狀態，達成
「手機上問一半、回電腦前接著問」的跨管道記憶共用。完整方案見
`~/.claude/plans/hazy-petting-wreath.md` §2、§4、§6、§7。

**刻意的設計取捨（不要事後「修正」成別的樣子）**：

1. **獨立實作，不 import telegram_gateway**：兩者是不同 repo、不同
   Python 環境的行程，方案 §7 已明確接受「兩份程式碼手動保持同步」這個
   已知維護成本（見已知限制第 10 條）。這裡的 `_load_state`／
   `_save_state`／`_append_usage_log` 等函式是 `telegram_gateway/state.py`
   對應函式的獨立重寫，行為對齊但不共用模組。
2. **共用狀態檔路徑可用 `STND_GATEWAY_STATE_DIR` 環境變數覆寫**（預設指向
   telegram_gateway 的正式 state 目錄），方便測試時指向獨立複本，不會
   在跑測試時弄髒真正的 `gateway_state.json`。`PROJECT_DOMAINS`（已知
   專案捷徑，只剩 alphavibe／harness）寫死不做成可覆寫（不是安全邊界，
   見方案已知限制第 8 條）——但 domain／主題名稱本身**不再限於這個固定
   字典**，任何通過命名檢查的字串都是合法主題，第一次使用即自動建立
   （2026-08-31「擴充：任意命名主題」章節）。
3. **權限模式從共用的 `~/.config/stnd-gateway/.env` 讀 `CLAUDE_PERMISSION_MODE`**
   （`STND_GATEWAY_ENV_FILE` 可覆寫路徑）——跟 Telegram 側共用同一個設定
   來源，避免兩邊各自為政、日後不同步。這個 app/ 目錄沒有裝
   `python-dotenv`（`app/requirements.txt` 刻意只裝 fastapi/uvicorn 兩個
   套件），這裡用最小的手刻 KEY=VALUE parser（`_read_env_value()`），不
   新增依賴。
4. **背景任務線在本 process 的 asyncio event loop 裡自己輪詢完成狀態**
   （`_watch_bg_task()`），邏輯照抄 telegram_gateway `executor_claude.py`
   的 `submit_task()`/`_watch_bg_task()`，因為 `inflight_bg_tasks` 是
   「誰提交誰負責 watch」的設計——Telegram 側的 watcher 只會 watch
   它自己提交的任務，網頁提交的任務如果這裡不自己 watch，永遠不會被
   `clear_inflight()`，`gateway_state.json` 會卡著一筆假的進行中任務。
5. **鎖定（LOCKDOWN）只影響兩個 POST 端點**——GET 端點維持唯讀可查（前端
   靠這兩個 GET 回傳的 `lockdown` 欄位畫警示橫幅），跟 Telegram 側
   `/lockdown` 共用同一個旗標檔，解鎖一樣只能到本機刪檔（見
   telegram_gateway/state.py 的 `set_lockdown()` docstring）。

不要做的事（已跟方案發起者確認過的範圍邊界）：不 import／不修改
`telegram_gateway/` 任何檔案；不新增 audit_log 以外的稽核機制；不做
`claude --bg` 的逾時上限（方案已知限制第 5 條是刻意的）。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# ---------------------------------------------------------------------------
# 設定：共用狀態檔路徑、domain 捷徑（照抄方案 §2、§7 的字面值）
# ---------------------------------------------------------------------------

_STATE_DIR = Path(os.environ.get(
    "STND_GATEWAY_STATE_DIR",
    "/Users/stander/My_project/AI/telegram_gateway/state",
))
_GATEWAY_STATE_PATH = _STATE_DIR / "gateway_state.json"
_USAGE_LOG_PATH = _STATE_DIR / "usage_log.jsonl"
_AUDIT_LOG_PATH = _STATE_DIR / "audit_log.jsonl"
_LOCKDOWN_FLAG_PATH = _STATE_DIR / "LOCKDOWN"

# 已知專案捷徑（cwd 指到真實專案路徑，供需要讀檔/跑指令的主題使用）——
# 跟 telegram_gateway/config.py::PROJECT_DOMAINS 保持一致（見方案 §2、§7、
# 2026-08-31「擴充：任意命名主題」章節）。任意命名的主題不需要預先出現
# 在這裡，第一次使用即自動建立，cwd 一律 fallback 到 Path.home()。
PROJECT_DOMAINS: Dict[str, Path] = {
    "alphavibe": Path("/Users/stander/My_project/AlphaVibe"),
    "harness": Path("/Users/stander/My_project/AI/harness"),
}
DEFAULT_DOMAIN = "general"

# 主題名稱的長度上限。**這個數值必須跟
# telegram_gateway/config.py::MAX_DOMAIN_NAME_LEN 逐字一致**——任一邊
# 漏改，會讓某些名稱在一邊被接受、在另一邊被拒絕。
MAX_DOMAIN_NAME_LEN = 40

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_domain_name(name: str) -> str:
    """統一小寫、去頭尾空白。所有入口（`ChatRequest.domain`／
    `TaskRequest.domain`）都要先正規化，再驗證、再拿去查/寫 state——
    否則 `MyTopic` 跟 `mytopic` 會變成兩個獨立 session，直接打臉「跨
    管道共用記憶」這個核心賣點。**必須跟
    telegram_gateway/config.py::normalize_domain_name() 逐字一致。**
    """
    return name.strip().lower()


def is_valid_domain_name(name: str) -> bool:
    """假設輸入已經 normalize_domain_name() 過。規則：非空、長度
    ≤ MAX_DOMAIN_NAME_LEN、不含任何空白字元、不含 `/`、不含控制字元
    （空白字元的禁止理由是 Telegram `/switch` 用 `context.args[0]`
    斷詞，這裡沿用同一條規則以維持兩邊一致，即使網頁沒有這個斷詞
    問題）。**必須跟 telegram_gateway/config.py::is_valid_domain_name()
    逐字一致（長度上限、禁止字元集合）。**
    """
    if not name:
        return False
    if len(name) > MAX_DOMAIN_NAME_LEN:
        return False
    if any(ch.isspace() for ch in name):
        return False
    if "/" in name:
        return False
    if _CONTROL_CHAR_RE.search(name):
        return False
    return True


def resolve_cwd(name: str) -> Path:
    """`PROJECT_DOMAINS` 裡的已知專案捷徑用真實路徑；其餘一律 fallback
    到 `Path.home()`（精準避開 `claude --bg` 首次在未信任目錄執行卡死
    的地雷，新主題不支援自訂 cwd 是刻意的 MVP 邊界）。永不拋錯，取代
    舊有會 KeyError 的 `PROJECT_DOMAINS[domain]` 直接查表寫法。**必須跟
    telegram_gateway/config.py::resolve_cwd() 邏輯一致。**
    """
    return PROJECT_DOMAINS.get(name, Path.home())


# 網頁提交的背景任務完成後，inflight_bg_tasks 紀錄原地標記
# status="done"/completed_at 而不立刻清除，保留這麼多小時讓網頁輪詢
# 看得到「已完成」（Telegram 有主動推播墊底，網頁沒有）。到期真的刪除，
# 不是任務歷史列表。邏輯對齊
# telegram_gateway/config.py::COMPLETED_TASK_RETENTION_HOURS。
_COMPLETED_TASK_RETENTION_HOURS = 24

_ENV_FILE_PATH = Path(os.environ.get(
    "STND_GATEWAY_ENV_FILE",
    str(Path.home() / ".config" / "stnd-gateway" / ".env"),
))

_SYNC_TIMEOUT_S = int(os.environ.get("STND_GATEWAY_SYNC_TIMEOUT_S", "300"))
_BG_SUBMIT_TIMEOUT_S = 120
_BG_POLL_INTERVAL_S = int(os.environ.get("STND_GATEWAY_BG_POLL_INTERVAL_S", "10"))

_BACKGROUNDED_RE = re.compile(r"backgrounded\s+·\s+(\S+)")


# ---------------------------------------------------------------------------
# .env 讀取：不用 python-dotenv（app/ 沒裝這個套件），手刻最小 parser
# ---------------------------------------------------------------------------

def _read_env_value(env_path: Path, key: str) -> str:
    """每次呼叫都重讀檔案（不快取），比照 app/deps.py
    `_configured_dashboard_token()` 的既有寫法，方便動態切換設定值。"""
    if not env_path.exists():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _permission_args() -> List[str]:
    """空字串＝不傳 --permission-mode 旗標，交給 Claude Code 預設行為。
    邏輯對齊 telegram_gateway/executor_claude.py::_permission_args()。"""
    mode = _read_env_value(_ENV_FILE_PATH, "CLAUDE_PERMISSION_MODE")
    if mode:
        return ["--permission-mode", mode]
    return []


# ---------------------------------------------------------------------------
# gateway_state.json 讀寫（獨立實作，行為對齊 telegram_gateway/state.py，
# 見本檔開頭 docstring 取捨第 1 點）
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _empty_state() -> Dict[str, Any]:
    return {
        "version": 2,
        "domains": {name: {"session_id": None, "last_active": None} for name in PROJECT_DOMAINS},
        "chats": {},
        "inflight_bg_tasks": [],
    }


def _purge_stale_completed(state: Dict[str, Any]) -> bool:
    """把 `completed_at` 超過保留期的 `status=="done"` 背景任務紀錄真的
    刪除——不是任務歷史列表，只是讓近期完成的任務多活一段時間可見。
    回傳是否有變動，供 `_load_state()` 決定要不要重新寫檔。邏輯對齊
    telegram_gateway/state.py::_purge_stale_completed()。"""
    now = datetime.now(timezone.utc)
    kept: List[Dict[str, Any]] = []
    changed = False
    for task in state.get("inflight_bg_tasks", []):
        if task.get("status") == "done":
            completed_at = task.get("completed_at")
            parsed: Optional[datetime] = None
            if completed_at:
                try:
                    parsed = datetime.fromisoformat(completed_at)
                except ValueError:
                    parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if now - parsed > timedelta(hours=_COMPLETED_TASK_RETENTION_HOURS):
                    changed = True
                    continue
        kept.append(task)
    if changed:
        state["inflight_bg_tasks"] = kept
    return changed


def _load_state() -> Dict[str, Any]:
    if not _GATEWAY_STATE_PATH.exists():
        return _empty_state()
    try:
        state = json.loads(_GATEWAY_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    # 確保已知專案捷徑也存在於狀態裡；任意命名的主題不需要預先存在，
    # 第一次使用（_set_session_id／_add_inflight 等）時會自然透過
    # setdefault 建立。
    for name in PROJECT_DOMAINS:
        state.setdefault("domains", {}).setdefault(name, {"session_id": None, "last_active": None})
    state.setdefault("chats", {})
    state.setdefault("inflight_bg_tasks", [])
    if _purge_stale_completed(state):
        _save_state(state)
    return state


def _save_state(state: Dict[str, Any]) -> None:
    """write-to-tmp-then-rename，避免寫到一半被中斷造成壞檔。這個檔案
    現在被兩個獨立行程（telegram_gateway、這個 STND app）同時讀寫，沒有
    跨行程鎖——方案已知限制第 6 條接受的取捨，這裡不重新造鎖機制。"""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(_STATE_DIR), prefix=".gateway_state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _GATEWAY_STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _get_session_id(domain: str) -> Optional[str]:
    return _load_state().get("domains", {}).get(domain, {}).get("session_id")


def _set_session_id(domain: str, session_id: str) -> None:
    state = _load_state()
    state.setdefault("domains", {}).setdefault(domain, {})
    state["domains"][domain]["session_id"] = session_id
    state["domains"][domain]["last_active"] = _now_iso()
    _save_state(state)


def _add_inflight(domain: str, claude_session_id: str, cwd: str, description: str,
                   notify: Optional[Dict[str, Any]] = None) -> None:
    state = _load_state()
    state.setdefault("inflight_bg_tasks", []).append({
        "claude_session_id": claude_session_id,
        "domain": domain,
        "cwd": cwd,
        "description": description,
        "submitted_at": _now_iso(),
        "notify": notify,
    })
    _save_state(state)


def _clear_inflight(claude_session_id: str) -> None:
    state = _load_state()
    state["inflight_bg_tasks"] = [
        t for t in state.get("inflight_bg_tasks", [])
        if t.get("claude_session_id") != claude_session_id
    ]
    _save_state(state)


def _mark_inflight_done(claude_session_id: str) -> None:
    """完成時原地標記 `status="done"`／`completed_at`，不立刻清除——
    「擴充：任意命名主題」章節「背景任務完成可見性」採用的修法：網頁
    沒有主動推播（`notify=None`），靠輪詢 `GET /api/gateway/tasks` 看到
    狀態變化，所以 inflight 紀錄要保留一段時間（見
    `_COMPLETED_TASK_RETENTION_HOURS`）才能看到「已完成」。取代舊的
    `_clear_inflight()` 呼叫點。邏輯對齊
    telegram_gateway/state.py::mark_inflight_done()。"""
    state = _load_state()
    for t in state.get("inflight_bg_tasks", []):
        if t.get("claude_session_id") == claude_session_id:
            t["status"] = "done"
            t["completed_at"] = _now_iso()
            break
    _save_state(state)


def _append_usage_log(domain: str, payload: Dict[str, Any], kind: str, channel: str = "web") -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
    entry = {
        "timestamp": _now_iso(),
        "channel": channel,
        "domain": domain,
        "session_id": payload.get("session_id"),
        "kind": kind,
        "total_cost_usd": payload.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
    }
    with open(_USAGE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_audit_log(domain: str, action: str, text: str = "") -> None:
    """web 管道版本的稽核紀錄——沒有 Telegram 的 user_id/chat_id 概念，
    用 channel 欄位區分（既有 telegram 側寫入的行沒有這個欄位，JSONL
    逐行獨立解析，新增欄位不影響既有行的可讀性）。"""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now_iso(),
        "channel": "web",
        "domain": domain,
        "action": action,
        "text": (text or "")[:2000],
    }
    with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _is_locked_down() -> bool:
    return _LOCKDOWN_FLAG_PATH.exists()


def _lockdown_info() -> Optional[Dict[str, Any]]:
    if not _LOCKDOWN_FLAG_PATH.exists():
        return None
    try:
        return json.loads(_LOCKDOWN_FLAG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _lockdown_payload() -> Dict[str, Any]:
    return {"is_locked": _is_locked_down(), "info": _lockdown_info()}


# ---------------------------------------------------------------------------
# claude CLI 呼叫：agents 列表、逐字稿路徑搜尋
# ---------------------------------------------------------------------------

def _list_agents() -> List[Dict[str, Any]]:
    """`claude agents --json --all` 沒裝/找不到執行檔時回空清單，不讓
    GET 端點因為 claude CLI 不可用而整支炸掉（唯讀查詢應該儘量保持
    可用）。"""
    try:
        result = subprocess.run(
            ["claude", "agents", "--json", "--all"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def _transcript_path(session_id: str) -> Optional[Path]:
    """實測抓到真的 bug（見任務背景知識第3點）：Claude Code 把 cwd 轉成
    逐字稿目錄名稱時，`/` 與 `_` 都會換成 `-`，不要去猜這個轉換規則。
    改成直接用 session_id（UUID）在 `~/.claude/projects/*/` 底下 glob
    搜尋，不管實際目錄名稱長什麼樣都找得到。邏輯對齊
    telegram_gateway/executor_claude.py::_transcript_path()。"""
    projects_dir = Path.home() / ".claude" / "projects"
    matches = sorted(projects_dir.glob("*/%s.jsonl" % session_id))
    return matches[0] if matches else None


def _extract_text_from_content(content: Any) -> str:
    """user/assistant 訊息的 message.content 可能是純字串（一般文字
    訊息），也可能是 content block 陣列（含 tool_use/tool_result，混雜
    text block）。這裡只取出 text block——tool 呼叫本身不在「監控對話
    內容」這個用途的範圍內，純 tool_use/tool_result 的 turn 會被跳過
    （不會出現在回傳的 messages 裡）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _extract_messages(jsonl_path: Path, limit: int = 300) -> List[Dict[str, Any]]:
    if not jsonl_path.exists():
        return []
    messages: List[Dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue
        text = _extract_text_from_content((entry.get("message") or {}).get("content"))
        if not text:
            continue
        messages.append({
            "type": entry_type,
            "timestamp": entry.get("timestamp"),
            "text": text,
        })
    return messages[-limit:]


def _extract_usage_from_transcript(session_id: str) -> Dict[str, Any]:
    """背景任務沒有 CLI 回傳的 JSON payload（`claude agents --json` 沒有
    usage/cost 欄位，見任務背景知識第3點），只能從逐字稿的
    message.usage 逐行加總。逐字稿也沒有 USD 金額，`total_cost_usd`
    因此一定是 None。邏輯對齊
    telegram_gateway/executor_claude.py::_extract_usage_from_transcript()。
    """
    totals: Dict[str, int] = {}
    jsonl_path = _transcript_path(session_id)
    if jsonl_path and jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if isinstance(value, int):
                        totals[key] = totals.get(key, 0) + value
    return {"session_id": session_id, "total_cost_usd": None, "usage": totals}


# ---------------------------------------------------------------------------
# 用量彙總（GET /api/gateway/usage）
# ---------------------------------------------------------------------------

def _load_usage_entries() -> List[Dict[str, Any]]:
    if not _USAGE_LOG_PATH.exists():
        return []
    entries = []
    for line in _USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _aggregate_usage(entries: List[Dict[str, Any]], since: datetime) -> Dict[str, Any]:
    by_domain: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    has_unknown_cost = False
    call_count = 0
    for e in entries:
        ts = _parse_ts(e.get("timestamp"))
        if ts is None or ts < since:
            continue
        domain = e.get("domain") or "unknown"
        bucket = by_domain.setdefault(domain, {
            "total_cost_usd": 0.0, "calls": 0, "has_unknown_cost": False,
            "input_tokens": 0, "output_tokens": 0,
        })
        bucket["calls"] += 1
        call_count += 1
        cost = e.get("total_cost_usd")
        if cost is None:
            bucket["has_unknown_cost"] = True
            has_unknown_cost = True
        else:
            bucket["total_cost_usd"] += cost
            total_cost += cost
        bucket["input_tokens"] += e.get("input_tokens") or 0
        bucket["output_tokens"] += e.get("output_tokens") or 0
    for bucket in by_domain.values():
        bucket["total_cost_usd"] = round(bucket["total_cost_usd"], 4)
    return {
        "total_cost_usd": round(total_cost, 4),
        "calls": call_count,
        "has_unknown_cost": has_unknown_cost,
        "by_domain": by_domain,
    }


# ---------------------------------------------------------------------------
# GET /api/gateway/conversations
# ---------------------------------------------------------------------------

@router.get("/api/gateway/conversations")
def list_conversations() -> Dict[str, Any]:
    """2026-08-31 修正（「擴充：任意命名主題」章節，最高優先度的功能性
    bug）：改成走訪 `state.get("domains", {})` 本身，不再走訪
    `PROJECT_DOMAINS`（固定字典）——不修的話，Telegram 建立的任意新
    主題永遠不會出現在這裡，直接打臉「跨管道共用記憶看得到」這個核心
    賣點。依 `last_active` 新到舊排序（`None` 排最後），方便前端
    datalist 選單直接使用。"""
    state = _load_state()
    inflight_domains = {
        t.get("domain") for t in state.get("inflight_bg_tasks", [])
        if t.get("status") != "done"
    }
    domains = []
    for name, info in state.get("domains", {}).items():
        domains.append({
            "name": name,
            "session_id": info.get("session_id"),
            "last_active": info.get("last_active"),
            "has_inflight_task": name in inflight_domains,
        })
    domains.sort(key=lambda d: d["last_active"] or "", reverse=True)
    return {"domains": domains, "lockdown": _lockdown_payload()}


# ---------------------------------------------------------------------------
# GET /api/gateway/tasks
# ---------------------------------------------------------------------------

@router.get("/api/gateway/tasks")
def list_tasks() -> Dict[str, Any]:
    """回傳 `gateway_state.json` 記錄的 inflight_bg_tasks——包含真正
    進行中的任務，以及近期完成、`status=="done"` 但還在
    `_COMPLETED_TASK_RETENTION_HOURS` 保留期內的任務（見
    `_mark_inflight_done()`／「擴充：任意命名主題」章節「背景任務完成
    可見性」）。真正進行中的任務即時查 `claude agents --json` 對照
    真實狀態，不只信快取。

    2026-08-31 拿掉舊的 `known_cwds`（cwd 反查 domain）邏輯——任意主題
    預設共用 `Path.home()` 後，一個 cwd 會對應多個主題名稱，無法唯一
    反查回 domain。已完成任務改成直接讀持久化在紀錄裡的 `status`／
    `completed_at`，不再需要反查。"""
    state = _load_state()
    inflight = state.get("inflight_bg_tasks", [])
    agents = _list_agents()
    agents_by_session = {a.get("sessionId"): a for a in agents if a.get("sessionId")}

    tasks = []
    for t in inflight:
        session_id = t.get("claude_session_id")
        if t.get("status") == "done":
            status = "done"
        else:
            live = agents_by_session.get(session_id)
            status = live.get("state") if live else "unknown"
        tasks.append({
            "claude_session_id": session_id,
            "domain": t.get("domain"),
            "cwd": t.get("cwd"),
            "description": t.get("description"),
            "submitted_at": t.get("submitted_at"),
            "completed_at": t.get("completed_at"),
            "status": status,
        })

    return {"tasks": tasks, "lockdown": _lockdown_payload()}


# ---------------------------------------------------------------------------
# GET /api/gateway/usage
# ---------------------------------------------------------------------------

@router.get("/api/gateway/usage")
def get_usage() -> Dict[str, Any]:
    entries = _load_usage_entries()
    now = datetime.now(timezone.utc).astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # 本週一 00:00
    month_start = today_start.replace(day=1)
    return {
        "today": _aggregate_usage(entries, today_start),
        "this_week": _aggregate_usage(entries, week_start),
        "this_month": _aggregate_usage(entries, month_start),
    }


# ---------------------------------------------------------------------------
# GET /api/gateway/conversations/{domain}/transcript
# ---------------------------------------------------------------------------

@router.get("/api/gateway/conversations/{domain}/transcript")
def get_transcript(domain: str) -> Dict[str, Any]:
    """domain 先正規化再驗證格式（不再檢查是否為 `PROJECT_DOMAINS`
    固定字典的 key——任意合法名稱都是有效主題）。格式合法但沒有
    session_id（從未使用過）維持原本 404，這條路徑邏輯本來就是對的，
    不用改。"""
    normalized = normalize_domain_name(domain)
    if not is_valid_domain_name(normalized):
        raise HTTPException(status_code=400, detail="不合法的主題名稱：%s（長度需 1~%d、不能包含空白或「/」）" % (
            domain, MAX_DOMAIN_NAME_LEN))
    session_id = _get_session_id(normalized)
    if not session_id:
        raise HTTPException(status_code=404, detail="這個主題目前沒有對話記錄（session_id 為空）")
    path = _transcript_path(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="找不到逐字稿檔案（session_id=%s）" % session_id)
    return {
        "domain": normalized,
        "session_id": session_id,
        "transcript_path": str(path),
        "messages": _extract_messages(path),
    }


# ---------------------------------------------------------------------------
# POST /api/gateway/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    domain: str = Field(..., description="任意主題名稱（長度 1~40、不含空白或「/」）；已知專案捷徑：alphavibe/harness")
    text: str = Field(..., min_length=1, description="要送出的訊息")


async def _run(*args: str, cwd: Optional[Path] = None, timeout: Optional[float] = None
                ) -> subprocess.CompletedProcess:
    """在 thread pool 跑同步 subprocess，避免卡住 asyncio 事件迴圈。"""
    return await asyncio.to_thread(
        subprocess.run, list(args), cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout,
    )


@router.post("/api/gateway/chat")
async def post_chat(payload: ChatRequest) -> Dict[str, Any]:
    if _is_locked_down():
        raise HTTPException(status_code=423, detail="系統已鎖定（LOCKDOWN），拒絕執行。解鎖需要在本機手動刪除旗標檔（見 telegram_gateway/state.py）。")
    normalized = normalize_domain_name(payload.domain)
    if not is_valid_domain_name(normalized):
        raise HTTPException(status_code=400, detail="不合法的主題名稱：%s（長度需 1~%d、不能包含空白或「/」）" % (
            payload.domain, MAX_DOMAIN_NAME_LEN))

    cwd = resolve_cwd(normalized)
    session_id = _get_session_id(normalized)
    cmd = ["claude", "-p", payload.text, "--output-format", "json"] + _permission_args()
    if session_id:
        cmd += ["--resume", session_id]

    try:
        result = await _run(*cmd, cwd=cwd, timeout=_SYNC_TIMEOUT_S)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="找不到 claude 執行檔，請確認正式服務的 PATH 設定（見專案 CLAUDE.md 教訓紀錄）。")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="逾時（超過 %d 秒沒有回應）。任務可能還在跑，稍後查 /api/gateway/conversations。" % _SYNC_TIMEOUT_S)

    if not result.stdout.strip():
        stderr_tail = (result.stderr or "").strip()[-500:]
        raise HTTPException(status_code=502, detail="CLI 沒有輸出（exit=%s）。stderr: %s" % (
            result.returncode, stderr_tail or "(空)"))

    try:
        cli_payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="無法解析 CLI 輸出：%s" % result.stdout[:500])

    new_session_id = cli_payload.get("session_id")
    if new_session_id:
        _set_session_id(normalized, new_session_id)
    _append_usage_log(normalized, cli_payload, kind="sync", channel="web")
    _append_audit_log(normalized, "chat", payload.text)

    return {
        "domain": normalized,
        "session_id": new_session_id or session_id,
        "is_error": bool(cli_payload.get("is_error")),
        "result": cli_payload.get("result", "(沒有回覆內容)"),
        "permission_denials": cli_payload.get("permission_denials") or [],
        "total_cost_usd": cli_payload.get("total_cost_usd"),
    }


# ---------------------------------------------------------------------------
# POST /api/gateway/task
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    domain: str = Field(..., description="任意主題名稱（長度 1~40、不含空白或「/」）；已知專案捷徑：alphavibe/harness")
    description: str = Field(..., min_length=1, description="背景任務描述")


async def _resolve_full_session_id(short_id: str) -> Tuple[Optional[str], Optional[str]]:
    """短 id 只是顯示用，完整 UUID 要從 claude agents --json 查。邏輯
    對齊 telegram_gateway/executor_claude.py::_resolve_full_session_id()。
    """
    for _ in range(10):
        agents = await asyncio.to_thread(_list_agents)
        for a in agents:
            if a.get("id") == short_id or str(a.get("sessionId", "")).startswith(short_id):
                return a.get("sessionId"), a.get("cwd", "")
        await asyncio.sleep(1)
    return None, None


async def _watch_bg_task(domain: str, session_id: str) -> None:
    """無限輪詢直到完成——沒有固定逾時是刻意的（見方案已知限制第5條）。
    網頁提交的任務完成後不推播（`notify=None`），前端靠輪詢
    GET /api/gateway/tasks 自然看到狀態變化；這個函式唯一要做的收尾是
    把 usage 記下來、把任務原地標記為完成（不立刻清除，見
    `_mark_inflight_done()`／「擴充：任意命名主題」章節「背景任務完成
    可見性」）。任何例外都要吞掉，否則這個 fire-and-forget asyncio task
    的例外會變成 unhandled task exception，不影響其他請求但會汙染
    server log。"""
    try:
        while True:
            agents = await asyncio.to_thread(_list_agents)
            entry = next((a for a in agents if a.get("sessionId") == session_id), None)
            if entry and entry.get("state") == "done":
                _append_usage_log(domain, _extract_usage_from_transcript(session_id), kind="bg", channel="web")
                _mark_inflight_done(session_id)
                return
            await asyncio.sleep(_BG_POLL_INTERVAL_S)
    except Exception:
        # 背景 watcher 掛掉不該讓 inflight 紀錄永遠卡著查不到原因，但
        # 也不該讓整個 process 崩潰——至少把它標記完成，狀態不明時寧可
        # 讓它照正常保留期消失（前端可以到 claude agents 或逐字稿目錄
        # 人工核對），不要卡死顯示成永遠「進行中」。
        _mark_inflight_done(session_id)
        raise


@router.post("/api/gateway/task")
async def post_task(payload: TaskRequest) -> Dict[str, Any]:
    if _is_locked_down():
        raise HTTPException(status_code=423, detail="系統已鎖定（LOCKDOWN），拒絕執行。解鎖需要在本機手動刪除旗標檔（見 telegram_gateway/state.py）。")
    normalized = normalize_domain_name(payload.domain)
    if not is_valid_domain_name(normalized):
        raise HTTPException(status_code=400, detail="不合法的主題名稱：%s（長度需 1~%d、不能包含空白或「/」）" % (
            payload.domain, MAX_DOMAIN_NAME_LEN))

    cwd = resolve_cwd(normalized)
    cmd = ["claude", "--bg", payload.description] + _permission_args()
    try:
        result = await _run(*cmd, cwd=cwd, timeout=_BG_SUBMIT_TIMEOUT_S)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="找不到 claude 執行檔，請確認正式服務的 PATH 設定（見專案 CLAUDE.md 教訓紀錄）。")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="提交背景任務逾時（超過 %d 秒）。" % _BG_SUBMIT_TIMEOUT_S)

    combined = (result.stdout or "") + (result.stderr or "")
    match = _BACKGROUNDED_RE.search(combined)
    if not match:
        raise HTTPException(status_code=502, detail="無法從 CLI 輸出解析背景任務 id：%s" % combined[:500])
    short_id = match.group(1)

    full_session_id, agents_cwd = await _resolve_full_session_id(short_id)
    if not full_session_id:
        raise HTTPException(status_code=502, detail="已送出（短id=%s）但在 claude agents --json 找不到對應項目，可能還在啟動中，請稍後查 /api/gateway/tasks。" % short_id)

    _add_inflight(normalized, full_session_id, agents_cwd, payload.description, notify=None)
    _append_audit_log(normalized, "task", payload.description)
    asyncio.create_task(_watch_bg_task(normalized, full_session_id))

    return {
        "accepted": True,
        "short_id": short_id,
        "claude_session_id": full_session_id,
        "domain": normalized,
        "message": "已受理，背景執行中；完成狀態請查 /api/gateway/tasks",
    }
