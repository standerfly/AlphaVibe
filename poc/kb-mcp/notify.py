#!/usr/bin/env python3
"""通知管道（2026-09-17 架構體檢 B4）。

排程巡檢偵測到問題後要讓人知道。兩個管道：

1. **Telegram**——半夜壞掉早上就看得到。直接打 Bot API，刻意**不** import
   `AI/telegram_gateway/` 的任何程式碼：那個專案用 python-dotenv 與
   python-telegram-bot 套件，而 poc/kb-mcp/ 是「僅標準庫」慣例；更重要的是
   解耦——通知不該依賴閘道服務當下有沒有在跑。共用的只有那份設定檔
   （~/.config/stnd-gateway/.env）裡的 bot token 與收件人 id。

2. **狀態檔**——由 app/routers/health.py 讀出來，顯示成 STND 首頁橫幅。
   這部分不在這支模組，巡檢本來就會寫狀態檔。

通知的鐵則：**任何失敗都不能讓呼叫端崩潰**。通知管道壞掉是小事，
因為通知壞掉害得巡檢本身跑不完、連狀態檔都沒寫，才是大事。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENV_FILE = os.path.expanduser("~/.config/stnd-gateway/.env")
_TELEGRAM_API = "https://api.telegram.org/bot%s/sendMessage"
_TIMEOUT_S = 15


def _load_env_file(path):
    """解析 KEY=VALUE 格式的 .env。只用標準庫，夠應付這個檔案的格式
    （註解、空行、選擇性的引號）。讀不到就回空 dict，不拋例外。"""
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    except OSError:
        pass
    return values


def telegram_config(env_file=DEFAULT_ENV_FILE):
    """回傳 (bot_token, [chat_id...])。缺任一項就回 (None, [])。"""
    env = _load_env_file(env_file)
    token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_ids = env.get("ALLOWED_USER_IDS") or os.environ.get("ALLOWED_USER_IDS") or ""
    chat_ids = [p.strip() for p in raw_ids.split(",") if p.strip()]
    if not token or not chat_ids:
        return None, []
    return token, chat_ids


def send_telegram(text, env_file=DEFAULT_ENV_FILE):
    """發送 Telegram 訊息給所有設定的收件人。

    回傳 (成功數, [錯誤訊息...])。永遠不拋例外——見模組 docstring。
    """
    token, chat_ids = telegram_config(env_file)
    if not token:
        return 0, ["Telegram 未設定（找不到 TELEGRAM_BOT_TOKEN 或 ALLOWED_USER_IDS）"]

    sent, errors = 0, []
    url = _TELEGRAM_API % token
    for chat_id in chat_ids:
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
            if body.get("ok"):
                sent += 1
            else:
                errors.append("chat %s：%s" % (chat_id, body.get("description", "未知錯誤")))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("description", "")
            except Exception:
                pass
            errors.append("chat %s：HTTP %s %s" % (chat_id, exc.code, detail))
        except Exception as exc:
            errors.append("chat %s：%s" % (chat_id, exc))
    return sent, errors


def format_health_message(state):
    """把巡檢結果排成一則適合手機閱讀的訊息。

    刻意不用 Markdown/HTML parse_mode：狀態訊息裡可能含底線、星號等
    字元（例如 market_scan、檔名），套 parse_mode 會讓 Telegram 拒收
    整則訊息或顯示錯亂，而這是「出事時才發」的訊息，絕對不能自己壞掉。
    """
    status = state.get("status", "unknown")
    icon = {"critical": "🔴", "warning": "🟡", "ok": "🟢"}.get(status, "⚪")
    lines = ["%s STND 排程巡檢：%s" % (icon, status.upper()),
             "時間 %s" % state.get("checked_at", "?"), ""]
    for f in state.get("findings", []):
        if f.get("severity") == "ok":
            continue
        mark = {"critical": "✗", "warning": "!"}.get(f.get("severity"), "-")
        lines.append("%s [%s] %s" % (mark, f.get("job", "?"), f.get("detail", "")))
    if status == "ok":
        lines.append("全部排程正常。")
    return "\n".join(lines).strip()


def main(argv=None):
    """命令列自我測試：發一則測試訊息，確認管道真的通。

    用法：python3 poc/kb-mcp/notify.py "訊息內容"
    """
    text = " ".join(argv or sys.argv[1:]) or "STND 通知管道測試訊息"
    sent, errors = send_telegram(text)
    print("送出 %d 則" % sent)
    for e in errors:
        print("  錯誤：%s" % e)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
