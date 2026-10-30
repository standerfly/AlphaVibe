"""讀取 macOS 鑰匙圈中的對帳單匯入密碼（specs/009 research R3、FR-012）。

三個項目都存在 service `stnd-statement-import` 底下，account 分別是
`gmail-address`、`gmail-app-password`、`pdf-password`（身分證字號，英文字母大寫）。
PO 以 `security add-generic-password -U -s stnd-statement-import -a <account> -w`
互動輸入存入（見 quickstart.md）。

密碼只在記憶體中傳遞：不寫檔、不印出、例外訊息不含值。`runner` 可注入，
測試不需要真的鑰匙圈。僅標準庫，Python 3.9 相容。
"""
import subprocess

SERVICE = "stnd-statement-import"
ACCOUNTS = ("gmail-address", "gmail-app-password", "pdf-password")


class SecretNotFound(Exception):
    """鑰匙圈裡找不到指定項目（或 security 指令不可用）。訊息只含 account 名稱。"""


def _default_runner(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def get_secret(account, runner=None):
    """回傳鑰匙圈中 `stnd-statement-import`／`account` 的值（去除結尾換行）。"""
    if account not in ACCOUNTS:
        raise ValueError("未知的鑰匙圈項目：%s" % account)
    runner = runner or _default_runner
    try:
        proc = runner(["security", "find-generic-password",
                       "-s", SERVICE, "-a", account, "-w"])
    except (OSError, subprocess.SubprocessError):
        raise SecretNotFound("無法執行 security 指令讀取鑰匙圈項目 %s" % account)
    value = (proc.stdout or "").rstrip("\n")
    if proc.returncode != 0 or not value:
        raise SecretNotFound(
            "鑰匙圈找不到 %s（service %s），請依 quickstart.md 存入" % (account, SERVICE))
    return value
