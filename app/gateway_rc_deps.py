"""Remote Control PTY 行程管理（2026-09-25 新增，「擴充三：Remote
Control」，見 `~/.claude/plans/hazy-petting-wreath.md` 該章節）。

背景：STND 網頁「管家」分頁要能 (1) 直接建立新的 claude session，
(2) 對任何既有/歷史 session 啟用 Claude Code 官方 Remote Control
（`/remote-control "<name>"`），讓手機 claude.ai App 能接手繼續對話。
Remote Control 對一個**互動式**（不是 headless `-p`/`--bg`）行程執行後
會產生 `https://claude.ai/code/session_<id>` 網址，本機行程必須持續存活
手機才連得上——這跟本專案原本要繞開的「teleport」雲端同步 bug 完全無關
（官方文件明確分開描述兩者）。

**避免循環 import**：這個模組要用到 `app.routers.gateway_monitor` 的
`_load_state`／`_save_state`／`normalize_domain_name`／`is_valid_domain_name`／
`MAX_DOMAIN_NAME_LEN`／`resolve_cwd`／`PROJECT_DOMAINS`／`_list_agents`／
`_transcript_path`／`_now_iso`，而 `gateway_monitor.py` 也要 import 這個
新模組來註冊路由——**每個函式內部才寫
`from app.routers import gateway_monitor as gw`，不要放在檔案頂層**，
否則載入順序會炸（`gateway_monitor` 匯入時本模組尚未初始化完成）。反過來
`gateway_monitor.py` 可以在檔案頂層 import 這個模組，因為這個模組頂層
完全不 import `gateway_monitor`，沒有循環。

**2026-09-25 實作前的手動驗證發現兩個超出原規劃預期的真實地雷
（見任務回報，這裡只記錄設計如何回應）**：

1. **家目錄（`Path.home()`）目前不是「已信任」狀態**
   （`~/.claude.json` 的 `projects["/Users/stander"].hasTrustDialogAccepted`
   實測為 `false`）——原規劃「新主題一律 fallback 到家目錄，因為 Day-0
   已經手動信任過」這個假設**目前不成立**。在使用者於真正終端機手動跑一次
   `claude`（cwd=家目錄）並接受信任提示之前，「新增 Session」選家目錄
   這個選項會在交握階段命中下面第 2 點的偵測邏輯而失敗（見
   `_TRUST_DIALOG_MARKERS`），不會是「卡死」而是「明確失敗＋清楚錯誤
   訊息」。
2. **信任對話框預設游標停在「No, exit」，直接送 Enter 會讓子行程退出
   （不是像原規劃猜測的「隨便送 Enter 都安全，只是清掉對話框」）**——
   對還沒被信任的目錄盲目送防禦性 Enter 會誤觸「No, exit」，直接殺死
   剛 spawn 的行程。因此 `_spawn_and_handshake()` 在送出防禦性 Enter
   之前，會先檢查輸出裡有沒有這個對話框的特徵字串，偵測到就**立刻
   中止並強制關閉行程**、拋出清楚說明「這個目錄尚未信任，需要人工在
   真正終端機處理一次」的錯誤，而不是照原規劃盲目送 4 次 Enter。這是
   刻意的工程判斷（安全優先），不是規格遺漏。
3. **「建立新 session」的 pid 反查機制在測試環境下沒有得到正面驗證，
   mtime-diff 備案在同一次測試中也沒有觀察到成功**（懷疑是因為驗證
   環境本身巢狀在另一個 Claude Code session 底下，子行程繼承
   `CLAUDE_CODE_CHILD_SESSION` 標記導致 transcript saving 被關閉，這在
   正式環境〔uvicorn/launchd 常駐、非巢狀〕不會發生，但受限於這次驗證
   環境沒能排除這個混淆因素）——兩個機制仍照規劃實作（先 pid 反查、
   失敗則 mtime-diff），但正式上線後**必須**由人工再做一次「建立新
   session」全流程的手動驗證（見任務回報「pid 比對機制的驗證結果」）。
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import pty
import re
import select
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

# 已驗證過的網址格式（見任務背景知識）：真實輸出的網址後面沒有空白，
# 直接接續終端機 Unicode box-drawing 分隔線字元（`─❯` 等，不是 ANSI
# escape，不會被 strip_ansi() 去除），用 `\S+` 之類寬鬆正則會把這些垃圾
# 字元一起吃進去變成壞掉的網址，必須鎖定已知網址格式。
RC_URL_RE = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]")

# 目錄信任對話框的特徵字串（見本檔頭 docstring 地雷 1、2）。實測發現
# classic renderer 有時會用游標定位序列取代字面空白字元，strip_ansi()
# 之後單字會黏在一起（例如「Quick safety check」變成
# 「Quicksafetycheck」）——比對前把所有空白都去掉，兩種情形都抓得到。
_TRUST_DIALOG_MARKERS = ("quicksafetycheck", "trustthisfolder", "no,exit")

# 兩種都手動驗證親眼撞見過（2026-09-25）：(1) 全新啟用時的確認文字；
# (2) 對「這個 session 先前已經連過 RC，但本機行程已經不在」（例如
# stop_rc() 只 SIGTERM 本機行程、或伺服器重啟後 reconcile_on_startup()
# 清過本機紀錄，但 Anthropic 伺服器端仍記得這個 session 曾經連過）的
# session 重新 --resume 並再送一次 /remote-control 時，畫面顯示的是
# 「管理既有連線」畫面（含 Disconnect this session／Show QR code），
# 不會出現「remote-control is active」這句話——但一樣代表 RC 可用
# （URL 沒變），不能只認第一種畫面。
_RC_ACTIVE_MARKERS = ("remote-controlisactive", "disconnectthissession")

_HANDSHAKE_TIMEOUT_S = float(os.environ.get("STND_GATEWAY_RC_HANDSHAKE_TIMEOUT_S", "30"))
_DEFENSIVE_ENTER_ROUNDS = 4

_NEW_SESSION_PID_ATTEMPTS = int(os.environ.get("STND_GATEWAY_RC_NEW_SESSION_PID_ATTEMPTS", "10"))
_NEW_SESSION_PID_DELAY_S = 1.0

RC_IDLE_TIMEOUT_MINUTES = float(os.environ.get("STND_GATEWAY_RC_IDLE_TIMEOUT_MINUTES", "30"))
RC_MAX_LIFETIME_MINUTES = float(os.environ.get("STND_GATEWAY_RC_MAX_LIFETIME_MINUTES", "240"))
_RC_WATCH_POLL_INTERVAL_S = float(os.environ.get("STND_GATEWAY_RC_WATCH_POLL_INTERVAL_S", "30"))

# ---------------------------------------------------------------------------
# 行程內狀態（活物件不能序列化進 gateway_state.json，重啟後必然清空——
# 這是刻意的取捨，見 reconcile_on_startup()）
# ---------------------------------------------------------------------------

_LIVE_HANDLES: Dict[str, Dict[str, Any]] = {}
_watch_tasks: Dict[str, "asyncio.Task[None]"] = {}
_domain_locks: Dict[str, asyncio.Lock] = {}


def _get_domain_lock(domain: str) -> asyncio.Lock:
    """同一 domain 併發鎖：避免對同一個 topic 同時按兩次「建立新
    session」或「啟用 RC」造成競態。"""
    return _domain_locks.setdefault(domain, asyncio.Lock())


class RcError(Exception):
    """帶 HTTP 狀態碼的錯誤，router 層（gateway_monitor.py）接住後轉成
    對應的 HTTPException。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# 低階 PTY 工具
# ---------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _read_available(master_fd: int, timeout: float = 2.0) -> bytes:
    end = time.time() + timeout
    chunk = b""
    while time.time() < end:
        try:
            r, _, _ = select.select([master_fd], [], [], 0.3)
        except (OSError, ValueError):
            break
        if master_fd in r:
            try:
                data = os.read(master_fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunk += data
        elif chunk:
            break
    return chunk


def _pid_alive(pid: int) -> bool:
    """`os.kill(pid, 0)` 探測。`ProcessLookupError` 代表行程真的不存在；
    `PermissionError` 理論上不會發生在我們自己 spawn 的子行程上，但保守
    當作存活處理（避免誤殺不是我們啟動的行程）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _force_kill(proc: "subprocess.Popen[bytes]", master_fd: Optional[int]) -> None:
    """交握失敗或連線停止時，確保不留下孤兒 claude 行程。
    terminate() → 等 5 秒 → kill()，最後關閉 PTY master fd。"""
    with contextlib.suppress(Exception):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
    except Exception:
        pass
    if master_fd is not None:
        with contextlib.suppress(OSError):
            os.close(master_fd)


def _drain_loop(master_fd: int, stop_event: threading.Event) -> None:
    """連線存活期間持續讀走 master_fd 丟棄——PTY 核心緩衝區（通常 64KB）
    沒人讀走的話，手機端持續互動產生的輸出會讓子行程的 write() 憑空卡
    住，變相凍結手機端對話。原本規劃階段的驗證腳本只跑了 20 秒沒踩到
    這個問題，是本次規劃過程中新識別出的必要機制。"""
    while not stop_event.is_set():
        try:
            r, _, _ = select.select([master_fd], [], [], 1.0)
        except (OSError, ValueError):
            return
        if master_fd in r:
            try:
                data = os.read(master_fd, 65536)
            except OSError:
                return
            if not data:
                return


def _start_drain_thread(master_fd: int, stop_event: threading.Event) -> threading.Thread:
    t = threading.Thread(target=_drain_loop, args=(master_fd, stop_event), daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# 交握：spawn + 送出 /remote-control + 抓網址
# ---------------------------------------------------------------------------

def _spawn_and_handshake(cmd: List[str], cwd: Path, rc_name: str) -> Dict[str, Any]:
    """同步阻塞，呼叫端必須 `asyncio.to_thread` 包起來（不能佔用 FastAPI
    event loop，比照 `executor_claude.py`／`gateway_monitor.py::_run()`
    既有原則）。

    回傳 `{"proc", "master_fd", "pid", "rc_url"}`；任何交握失敗（逾時、
    抓不到網址、偵測到目錄信任對話框）都會先 `_force_kill()` 再拋
    `RuntimeError`（訊息含去除 ANSI 後的最後 800 字，方便除錯）。
    """
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    os.close(slave_fd)

    captured = ""

    def _pump(timeout: float) -> None:
        nonlocal captured
        data = _read_available(master_fd, timeout=timeout)
        captured += strip_ansi(data.decode("utf-8", errors="replace"))

    def _squash() -> str:
        return re.sub(r"\s+", "", captured.lower())

    def _looks_like_untrusted_dir_dialog() -> bool:
        squashed = _squash()
        return any(marker in squashed for marker in _TRUST_DIALOG_MARKERS)

    def _looks_like_rc_active() -> bool:
        # 跟信任對話框偵測用同一招（squash 掉空白再比對，見
        # _TRUST_DIALOG_MARKERS 註解）——兩種已知成功畫面見
        # _RC_ACTIVE_MARKERS 定義處的說明，手動驗證都親眼撞見過，不是
        # 理論上的風險。
        squashed = _squash()
        return any(marker in squashed for marker in _RC_ACTIVE_MARKERS)

    try:
        time.sleep(4)
        _pump(2.0)

        if _looks_like_untrusted_dir_dialog():
            raise RuntimeError(
                "這個目錄尚未被信任（trust dialog）。請先在真正終端機手動"
                "執行一次 `claude`（cwd=%s）並選擇「Yes, I trust this "
                "folder」完成一次性信任設定，再重新嘗試。最後輸出：%s"
                % (cwd, captured[-800:])
            )

        # 防禦性清掉可能出現的（已知安全的）確認對話框：最多 4 輪，每輪
        # 只送 Enter 接受預設選項；一看到 remote-control 字樣代表已經在
        # 正常畫面上，提早結束。**每一輪送 Enter 之前都重新檢查一次是否
        # 出現信任對話框**——這個對話框預設游標停在「No, exit」，盲目送
        # Enter 會誤觸退出，不能沿用原規劃「無條件送 4 次 Enter」的寫法。
        for _ in range(_DEFENSIVE_ENTER_ROUNDS):
            if "remotecontrol" in _squash():
                break
            if _looks_like_untrusted_dir_dialog():
                raise RuntimeError(
                    "這個目錄尚未被信任（trust dialog）。請先在真正終端機"
                    "手動執行一次 `claude`（cwd=%s）並選擇「Yes, I trust "
                    "this folder」完成一次性信任設定，再重新嘗試。最後輸出："
                    "%s" % (cwd, captured[-800:])
                )
            os.write(master_fd, b"\r")
            time.sleep(2)
            _pump(2.0)

        os.write(master_fd, ('/remote-control "%s"' % rc_name).encode("utf-8"))
        time.sleep(1)
        _pump(1.0)
        os.write(master_fd, b"\r")
        time.sleep(4)
        _pump(5.0)

        deadline = time.time() + _HANDSHAKE_TIMEOUT_S
        while not _looks_like_rc_active() and time.time() < deadline:
            # 送出指令後可能還有一個 y/n 確認要不要啟用——這個階段已經
            # 確定不是目錄信任對話框（前面已經檢查過、且已經送出
            # /remote-control 指令），沿用原規劃送 Enter 清掉。
            os.write(master_fd, b"\r")
            time.sleep(2)
            _pump(3.0)

        match = RC_URL_RE.search(captured)
        if not _looks_like_rc_active() or not match:
            raise RuntimeError(
                "Remote Control 交握失敗（逾時或抓不到網址）。最後輸出：%s"
                % captured[-800:]
            )
        return {"proc": proc, "master_fd": master_fd, "pid": proc.pid, "rc_url": match.group(0)}
    except Exception:
        _force_kill(proc, master_fd)
        raise


# ---------------------------------------------------------------------------
# 新 session 的 session_id 解析（見本檔頭 docstring 地雷 3）
# ---------------------------------------------------------------------------

def _resolve_new_interactive_session_id(pid: int, spawn_epoch: float) -> Optional[str]:
    """先用我們自己 `Popen` 的 `proc.pid` 去比對 `claude agents --json
    --all` 裡的項目，抓出對應的 `sessionId`；失敗則改用備案：掃描
    `~/.claude/projects/**/*.jsonl` 的檔案 mtime，找出 `spawn_epoch`
    之後新出現、mtime 最新的逐字稿檔案，檔名（去掉 `.jsonl`）就是
    session_id。兩者都找不到回傳 `None`（呼叫端負責強制關閉行程、
    回 502）。"""
    from app.routers import gateway_monitor as gw  # 避免循環 import

    for _ in range(_NEW_SESSION_PID_ATTEMPTS):
        for agent in gw._list_agents():
            if agent.get("pid") == pid:
                sid = agent.get("sessionId")
                if sid:
                    return sid
        time.sleep(_NEW_SESSION_PID_DELAY_S)

    return _resolve_new_session_id_by_mtime(spawn_epoch)


def _resolve_new_session_id_by_mtime(spawn_epoch: float) -> Optional[str]:
    """備案機制：`spawn_epoch` 減 2 秒當緩衝（時鐘/寫入延遲餘裕），挑
    mtime 最新且晚於這個時間點的逐字稿檔案。"""
    projects_dir = Path.home() / ".claude" / "projects"
    threshold = spawn_epoch - 2.0
    newest_path: Optional[Path] = None
    newest_mtime = threshold
    if not projects_dir.exists():
        return None
    for path in projects_dir.glob("*/*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_path = path
    return newest_path.stem if newest_path is not None else None


# ---------------------------------------------------------------------------
# active_remote_controls[] 讀寫 + 自我修復
# ---------------------------------------------------------------------------

def list_active_remote_controls() -> List[Dict[str, Any]]:
    """含即時存活自我修復：`pid` 已經死掉（非預期崩潰、或行程被外部
    kill）的連線視為已經斷線，直接從 state 移除，不留幽靈連線在畫面上。
    給 `GET /api/gateway/remote-control` 與 `GET
    /api/gateway/conversations` 共用（見方案 §3）。"""
    from app.routers import gateway_monitor as gw

    state = gw._load_state()
    entries = state.get("active_remote_controls", [])
    alive: List[Dict[str, Any]] = []
    changed = False
    for entry in entries:
        pid = entry.get("pid")
        if pid is not None and _pid_alive(pid):
            alive.append(entry)
        else:
            changed = True
            rc_id = entry.get("id")
            _LIVE_HANDLES.pop(rc_id, None)
            _cancel_watch_task(rc_id)
    if changed:
        state["active_remote_controls"] = alive
        gw._save_state(state)
    return alive


async def _register_rc_entry(domain: str, session_id: Optional[str], rc_name: str,
                              rc_url: str, pid: int, cwd: Path, mode: str) -> str:
    from app.routers import gateway_monitor as gw

    rc_id = "rc_" + uuid.uuid4().hex[:8]
    state = gw._load_state()
    state.setdefault("active_remote_controls", []).append({
        "id": rc_id,
        "domain": domain,
        "session_id": session_id,
        "rc_name": rc_name,
        "rc_url": rc_url,
        "pid": pid,
        "cwd": str(cwd),
        "mode": mode,
        "started_at": gw._now_iso(),
    })
    gw._save_state(state)
    task = asyncio.create_task(_watch_rc(rc_id))
    _watch_tasks[rc_id] = task
    return rc_id


def _cancel_watch_task(rc_id: Optional[str]) -> None:
    if rc_id is None:
        return
    task = _watch_tasks.pop(rc_id, None)
    if task is not None and not task.done():
        task.cancel()


def _stop_live_handle_sync(rc_id: str) -> None:
    handle = _LIVE_HANDLES.pop(rc_id, None)
    if handle is None:
        return
    handle["stop_event"].set()
    _force_kill(handle["proc"], handle["master_fd"])


async def stop_rc(rc_id: str) -> bool:
    """停止一個連線，**不受 LOCKDOWN 限制**——停止連線是安全閥，鎖定
    期間仍可主動掐斷任何 RC。對不存在的 id 冪等回 `False`（呼叫端把它
    當「已經沒有這個連線」處理，不是錯誤；`DELETE` 端點對此仍回 200，
    見 `gateway_monitor.py`）。"""
    from app.routers import gateway_monitor as gw

    state = gw._load_state()
    entries = state.get("active_remote_controls", [])
    entry = next((e for e in entries if e.get("id") == rc_id), None)
    if entry is None:
        _cancel_watch_task(rc_id)
        _LIVE_HANDLES.pop(rc_id, None)
        return False

    if rc_id in _LIVE_HANDLES:
        await asyncio.to_thread(_stop_live_handle_sync, rc_id)
    else:
        # 沒有行程內活物件可用（理論上不該發生，除非跨行程/測試情境）——
        # 退化成裸 PID SIGTERM，邏輯對齊 reconcile_on_startup()。
        pid = entry.get("pid")
        if pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGTERM)

    # 重新讀一次再寫，縮小跟上面非同步/子執行緒操作之間的競態窗口
    # （沒有跨行程鎖是既有已知取捨，見 gateway_monitor.py 檔頭 docstring）。
    state = gw._load_state()
    state["active_remote_controls"] = [
        e for e in state.get("active_remote_controls", []) if e.get("id") != rc_id
    ]
    gw._save_state(state)
    _cancel_watch_task(rc_id)
    return True


async def _remove_rc_entry_only(rc_id: str) -> None:
    """行程已經意外死掉時只需要清狀態，不需要再 kill。"""
    from app.routers import gateway_monitor as gw

    state = gw._load_state()
    state["active_remote_controls"] = [
        e for e in state.get("active_remote_controls", []) if e.get("id") != rc_id
    ]
    gw._save_state(state)
    _LIVE_HANDLES.pop(rc_id, None)
    _cancel_watch_task(rc_id)


def reconcile_on_startup() -> None:
    """app 啟動時呼叫一次（見 `app/main.py` 的 startup hook）：把殘留的
    `active_remote_controls[]` 全部 `SIGTERM` 清掉、清空陣列。

    `master_fd`／`Popen` 是行程內活物件不能序列化，重啟後這個 process
    裡的 `_LIVE_HANDLES` 必然是空的，沒辦法用 `_force_kill()` 優雅收尾
    （沒有 master_fd 可關），只能直接對裸 PID 送 SIGTERM——
    `ProcessLookupError` 代表行程本來就不存在了（例如上次是正常關機），
    不是錯誤。**不嘗試「認養」孤兒行程**——PTY 核心緩衝區可能已經塞滿，
    技術上不完整，見方案「已識別但技術上沒有其他選項」段落。"""
    from app.routers import gateway_monitor as gw

    state = gw._load_state()
    entries = state.get("active_remote_controls", [])
    for entry in entries:
        pid = entry.get("pid")
        if pid is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGTERM)
    if entries:
        state["active_remote_controls"] = []
        gw._save_state(state)
    _LIVE_HANDLES.clear()
    for rc_id in list(_watch_tasks.keys()):
        _cancel_watch_task(rc_id)


# ---------------------------------------------------------------------------
# 閒置/存活監控
# ---------------------------------------------------------------------------

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _idle_minutes(session_id: Optional[str], started_at: Optional[datetime]) -> Optional[float]:
    """閒置判斷用逐字稿檔案 mtime（不是終端機輸出變化——游標閃爍等雜訊
    不能當「真的有人在用」的訊號）；找不到逐字稿（例如剛建立、還沒有
    任何一輪對話）時退回用 `started_at` 當參考點。"""
    from app.routers import gateway_monitor as gw

    reference = started_at
    if session_id:
        path = gw._transcript_path(session_id)
        if path is not None and path.exists():
            try:
                mtime = path.stat().st_mtime
                reference = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                pass
    if reference is None:
        return None
    now = datetime.now(timezone.utc)
    return (now - reference).total_seconds() / 60.0


async def _watch_rc(rc_id: str) -> None:
    """背景 asyncio task，比照 `gateway_monitor.py::_watch_bg_task()` 的
    輪詢精神。閒置超過 `RC_IDLE_TIMEOUT_MINUTES` 或存活超過
    `RC_MAX_LIFETIME_MINUTES` 就呼叫 `stop_rc()`；每輪順便用
    `os.kill(pid, 0)` 確認行程沒有意外掛掉。"""
    try:
        while True:
            await asyncio.sleep(_RC_WATCH_POLL_INTERVAL_S)

            from app.routers import gateway_monitor as gw
            state = gw._load_state()
            entry = next(
                (e for e in state.get("active_remote_controls", []) if e.get("id") == rc_id),
                None,
            )
            if entry is None:
                return  # 已經被 stop_rc() 或其他途徑移除

            pid = entry.get("pid")
            if pid is None or not _pid_alive(pid):
                await _remove_rc_entry_only(rc_id)
                return

            started_at = _parse_iso(entry.get("started_at"))
            now = datetime.now(timezone.utc)
            if started_at and (now - started_at) > timedelta(minutes=RC_MAX_LIFETIME_MINUTES):
                await stop_rc(rc_id)
                return

            idle_minutes = _idle_minutes(entry.get("session_id"), started_at)
            if idle_minutes is not None and idle_minutes > RC_IDLE_TIMEOUT_MINUTES:
                await stop_rc(rc_id)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        # 背景 watcher 本身出錯不該讓 process 崩潰，也不該讓連線紀錄卡死
        # 顯示成永遠存活——盡量停止行程，至少把紀錄清掉。
        with contextlib.suppress(Exception):
            await stop_rc(rc_id)


# ---------------------------------------------------------------------------
# 對外主流程：建立新 session／對既有 session 掛 RC
# ---------------------------------------------------------------------------

async def create_new_session(cwd_choice: str, name: Optional[str]) -> Dict[str, Any]:
    """`POST /api/gateway/sessions`：依決定 2（簡化版名稱/cwd 耦合）解析
    domain/cwd，若該 topic 已有 session 先歸檔，spawn 新互動行程並立刻
    掛 RC。"""
    from app.routers import gateway_monitor as gw

    if cwd_choice in gw.PROJECT_DOMAINS:
        domain = cwd_choice
        cwd = gw.resolve_cwd(domain)
        rc_name = domain
    elif cwd_choice == "home":
        # 前端 placeholder 寫「留空自動命名」（見 Gateway.jsx），這裡要
        # 真的兌現這個承諾，不能回 400——名稱格式 session-YYYYMMDD-HHMMSS
        # 可排序、不含空白/斜線，天生滿足 is_valid_domain_name()。
        raw_name = (name or "").strip() or time.strftime("session-%Y%m%d-%H%M%S")
        domain = gw.normalize_domain_name(raw_name)
        if not gw.is_valid_domain_name(domain):
            raise RcError(400, "不合法的主題名稱：%r（長度需 1~%d、不能包含空白或「/」）"
                          % (name, gw.MAX_DOMAIN_NAME_LEN))
        cwd = Path.home()
        rc_name = domain
    else:
        raise RcError(400, "不合法的 cwd_choice：%r（合法值：home、%s）"
                      % (cwd_choice, "、".join(sorted(gw.PROJECT_DOMAINS))))

    async with _get_domain_lock(domain):
        # 決定 2：若選的捷徑名稱剛好是已存在且有歷史對話的 topic，語意是
        # 「把目前 session 歸檔、開一個全新 session 立刻掛 RC」，不是報錯。
        gw._archive_current_session(domain)

        spawn_epoch = time.time()
        try:
            handshake = await asyncio.to_thread(_spawn_and_handshake, ["claude"], cwd, rc_name)
        except RuntimeError as exc:
            raise RcError(502, str(exc)) from exc

        proc = handshake["proc"]
        master_fd = handshake["master_fd"]
        pid = handshake["pid"]
        rc_url = handshake["rc_url"]

        session_id = await asyncio.to_thread(
            _resolve_new_interactive_session_id, pid, spawn_epoch)
        if not session_id:
            _force_kill(proc, master_fd)
            raise RcError(
                502,
                "建立新 session 後找不到對應的 session_id"
                "（pid 反查與逐字稿 mtime-diff 備案都沒抓到，行程已強制關閉）",
            )

        gw._set_session_id(domain, session_id)

        stop_event = threading.Event()
        drain_thread = _start_drain_thread(master_fd, stop_event)
        rc_id = await _register_rc_entry(
            domain, session_id, rc_name, rc_url, pid, cwd, mode="new_session")
        _LIVE_HANDLES[rc_id] = {
            "proc": proc, "master_fd": master_fd,
            "stop_event": stop_event, "drain_thread": drain_thread,
        }
        return {
            "id": rc_id, "domain": domain, "session_id": session_id,
            "rc_name": rc_name, "rc_url": rc_url, "cwd": str(cwd), "mode": "new_session",
        }


async def attach_remote_control(domain: str, session_id: str, name: Optional[str]) -> Dict[str, Any]:
    """`POST /api/gateway/remote-control`：對既有/歷史 session 掛 RC
    （帶 `--resume`）。呼叫端（`gateway_monitor.py`）要先確保 `domain`
    已經 `normalize_domain_name()`／`is_valid_domain_name()` 驗證過。"""
    from app.routers import gateway_monitor as gw

    state = gw._load_state()
    domain_entry = state.get("domains", {}).get(domain)
    if domain_entry is None:
        raise RcError(404, "找不到主題：%s" % domain)

    valid_ids = set()
    if domain_entry.get("session_id"):
        valid_ids.add(domain_entry["session_id"])
    for h in domain_entry.get("session_history", []):
        if h.get("session_id"):
            valid_ids.add(h["session_id"])
    if session_id not in valid_ids:
        raise RcError(404, "session_id 不屬於這個主題：%s" % session_id)
    if any(e.get("session_id") == session_id for e in state.get("active_remote_controls", [])):
        raise RcError(409, "這個 session 已經有 Remote Control 連線在跑")

    rc_name = (name or domain).strip() or domain
    cwd = gw.resolve_cwd(domain)

    async with _get_domain_lock(domain):
        # 鎖內重新檢查一次 409，縮小鎖外查驗跟鎖內 spawn 之間的競態窗口。
        state = gw._load_state()
        if any(e.get("session_id") == session_id for e in state.get("active_remote_controls", [])):
            raise RcError(409, "這個 session 已經有 Remote Control 連線在跑")

        try:
            handshake = await asyncio.to_thread(
                _spawn_and_handshake, ["claude", "--resume", session_id], cwd, rc_name)
        except RuntimeError as exc:
            raise RcError(502, str(exc)) from exc

        proc, master_fd, pid, rc_url = (
            handshake["proc"], handshake["master_fd"], handshake["pid"], handshake["rc_url"])
        stop_event = threading.Event()
        drain_thread = _start_drain_thread(master_fd, stop_event)
        rc_id = await _register_rc_entry(
            domain, session_id, rc_name, rc_url, pid, cwd, mode="resume_existing")
        _LIVE_HANDLES[rc_id] = {
            "proc": proc, "master_fd": master_fd,
            "stop_event": stop_event, "drain_thread": drain_thread,
        }
        return {
            "id": rc_id, "domain": domain, "session_id": session_id,
            "rc_name": rc_name, "rc_url": rc_url, "cwd": str(cwd), "mode": "resume_existing",
        }
