"""服務版本資訊（2026-09-17 架構體檢 A5）。

動機：體檢當下沒有任何方法確認正式服務跑的是哪一份程式碼。uvicorn
從 2026-09-10 一直跑著，期間 git reflog 顯示工作樹切去別的分支又切
回並前進了 3 個 commit；那次剛好只動到 .jsx 沒事，但 launchd 的
KeepAlive 重啟會載入**當下 checkout 的任意分支**。當時只能靠比對
pyc 快取的時間戳來推斷，那不是一個可靠的辦法。

git 資訊在模組載入時抓一次就固定住——這正是我們要的語意：回報的是
「這個行程啟動時載入的那份程式碼」，不是「現在磁碟上的程式碼」。
每次請求重抓反而會謊報（磁碟變了但行程還跑著舊的，正是要偵測的情況）。
"""
import datetime
import os
import subprocess

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*args):
    """跑一個 git 指令，失敗回 None（不是 .git 目錄、沒裝 git 都算）。"""
    try:
        out = subprocess.run(
            ["git"] + list(args), cwd=_REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=5, check=True,
        )
        return out.stdout.decode("utf-8", "replace").strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def _collect():
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "commit_short": commit[:7] if commit else None,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "committed_at": _git("log", "-1", "--format=%cI"),
        # dirty=True 代表服務啟動時工作區有未 commit 的改動——也就是
        # 現在跑的東西不完全在版控裡，重啟後可能就不一樣了。
        "dirty": bool(status) if status is not None else None,
        "started_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }


# 啟動時抓一次就固定（見模組 docstring）
INFO = _collect()
