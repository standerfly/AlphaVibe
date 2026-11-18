"""Phase 14 流水線測試共用：假的 `claude` 可執行檔（stub）、假資料目錄、PNG 產生器。

零網路、零真實 claude、零鑰匙圈。stub 是一個真的 Python 腳本檔（用 sys.executable），所以測試走的是
`claude_cli_runner.default_runner` 的真實 subprocess 路徑（含環境白名單、cwd、stdin 提示詞、逾時殺行程群組）。
stub 的行為由同資料夾的 config.json 決定（子行程環境被白名單過濾，不能靠環境變數傳設定）：
  responses[<模型別名>] = [回應, ...]（依該別名被呼叫的順序；超過時重複最後一個）
  回應 kind：ok｜limit｜login｜sleep｜badjson｜no_structured｜write_in_workdir｜echo_token｜error
stub 把每次呼叫記到 calls.jsonl（args、cwd、環境變數**名稱**、stdin、工作夾檔案）；不記 token 值。
"""
import json
import os
import stat
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import article_store as A  # noqa: E402

URL = "https://investanchors.com/user/vip_contents/%d"

HELP_BASE = """Usage: claude [options] [command] [prompt]
Options:
  --add-dir <directories...>            More directories Claude can access
  --allowedTools, --allowed-tools <tools...>   allow
  --system-prompt <prompt>              System prompt
  --bare                                Minimal mode
  --disallowedTools, --disallowed-tools <tools...>   deny
  --json-schema <schema>                JSON Schema
  --max-budget-usd <amount>             Maximum dollar amount
  --model <model>                       Model
  --no-session-persistence              Don't save sessions
  --output-format <format>              Output format
  --permission-mode <mode>              Permission mode
  -p, --print                           print mode
  --tools <tools...>                    Built-in tools
  --setting-sources <sources>           Comma-separated list of setting sources
  --strict-mcp-config                   Only use MCP servers from --mcp-config
  --disable-slash-commands              Disable all skills
"""
HELP_OPTIONAL = """  --permission-prompts <target>         Who answers permission prompts
"""

STUB = r'''#!%(py)s
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(here, "config.json")))
args = sys.argv[1:]
if args[:1] == ["--help"]:
    sys.stdout.write(cfg["help"]); sys.exit(0)
if args[:2] == ["auth", "status"]:
    sys.stdout.write(cfg.get("auth", json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}))); sys.exit(cfg.get("auth_rc", 0))
stdin = sys.stdin.read()
model = args[args.index("--model") + 1]
cpath = os.path.join(here, "counters.json")
counters = json.load(open(cpath)) if os.path.exists(cpath) else {}
idx = counters.get(model, 0)
counters[model] = idx + 1
json.dump(counters, open(cpath, "w"))
token = cfg.get("token")
rec = {"args": args, "cwd": os.getcwd(), "env_keys": sorted(os.environ), "stdin": stdin, "model": model,
       "files": sorted(os.listdir(os.getcwd())), "token_in_env": bool(token) and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == token,
       "token_in_args": bool(token) and any(token in a for a in args)}
open(os.path.join(here, "calls.jsonl"), "a").write(json.dumps(rec, ensure_ascii=False) + "\n")
seq = cfg["responses"][model]
resp = seq[min(idx, len(seq) - 1)]
kind = resp["kind"]
def result(**kw):
    d = {"type": "result", "subtype": "success", "is_error": False, "result": ""}
    d.update(kw)
    sys.stdout.write(json.dumps(d))
if kind == "ok":
    result(structured_output={"is_table": resp.get("is_table", True), "text": resp["text"]})
elif kind == "verify":
    result(structured_output=resp["so"])
elif kind == "write_in_workdir":
    open(os.path.join(os.getcwd(), "evil.txt"), "w").write("x")
    result(structured_output={"is_table": True, "text": resp["text"]})
elif kind == "limit":
    result(is_error=True, subtype="error", result="You've hit your session limit · resets 3:45pm"); sys.exit(1)
elif kind == "weekly":
    result(is_error=True, subtype="error", result="You've hit your weekly limit · resets Nov 21, 9am"); sys.exit(1)
elif kind == "limit_plain":
    sys.stderr.write("Claude usage limit reached. Your limit will reset at 3:45pm"); sys.exit(1)
elif kind == "no_structured_trigger":
    result(result="You've hit your session limit \u00b7 resets 3:45pm 401 Unauthorized log in again")
elif kind == "limit_with_content":
    result(is_error=True, subtype="error", result="You've hit your session limit \u00b7 resets 3:45pm SECRETTABLECONTENT 甲公司"); sys.stderr.write("rate limited"); sys.exit(1)
elif kind == "limit_token":
    result(is_error=True, subtype="error", result="You've hit your session limit \u00b7 resets 3:45pm " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")); sys.stderr.write("tok=" + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")); sys.exit(1)
elif kind == "login":
    result(is_error=True, subtype="error", result="OAuth token has expired. Expired — log in again"); sys.exit(1)
elif kind == "sleep":
    time.sleep(resp.get("sec", 30)); result(structured_output={"is_table": True, "text": "| a |"})
elif kind == "badjson":
    sys.stdout.write("not json {")
elif kind == "no_structured":
    result(result="hello")
elif kind == "echo_token":
    sys.stderr.write("boom " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "") + " boom"); sys.stdout.write("x " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")); sys.exit(1)
elif kind == "error":
    result(is_error=True, subtype="error", result="some failure"); sys.exit(1)
'''


class Stub(object):
    def __init__(self, tmpdir, optional=True, auth=None):
        self.dir = os.path.join(tmpdir, "stubbin")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "claude")
        with open(self.path, "w") as f:
            f.write(STUB % {"py": sys.executable})
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.cfg = {"help": HELP_BASE + (HELP_OPTIONAL if optional else ""), "responses": {}}
        if auth is not None:
            self.cfg["auth"] = auth
        self.save()

    def save(self):
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump(self.cfg, f)

    def reset_counters(self):
        p = os.path.join(self.dir, "counters.json")
        if os.path.exists(p):
            os.remove(p)

    def respond(self, model, *responses):
        self.cfg["responses"][model] = list(responses)
        self.save()

    def calls(self):
        p = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]


def _png_from_raw(width, height, raw):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def make_png(width=300, height=200, shade=0):
    row = b"\x00" + bytes([200 + shade % 50, 200, 200]) * width
    return _png_from_raw(width, height, row * height)


def body(text):
    return (text + "。") + "補充說明。" * 60


def build_data_dir(data_dir, n_images=3, status="fetched"):
    """建立含 1 篇文章、n 張未轉寫圖（真的 PNG 檔，各不相同）的 articles.db。回傳 [(image_id, seq, path)]。"""
    s = A.ArticleStore(data_dir)
    s.upsert_discovered(900, URL % 900, "測試文章", list_date="2026-11-10")
    s.mark_fetched(900, body("測試內文"), published_at="2026-11-10T08:00:00+08:00")
    out = []
    imgdir = os.path.join(data_dir, "article_images", "900")
    os.makedirs(imgdir, exist_ok=True)
    for seq in range(1, n_images + 1):
        s.add_image(900, seq, "https://img.example/900-%d.png" % seq)
        rel = os.path.join("article_images", "900", "%d.png" % seq)
        with open(os.path.join(data_dir, rel), "wb") as f:
            f.write(make_png(300 + seq, 200, shade=seq))
        s.set_image_file(900, seq, rel)
        out.append(os.path.join(data_dir, rel))
    ids = [r[0] for r in s.conn.execute("SELECT id FROM article_image ORDER BY seq").fetchall()]
    s.close()
    return [(ids[i], i + 1, out[i]) for i in range(len(ids))]


TABLE_A = "| 項目 | 營收 | 毛利率 |\n| --- | --- | --- |\n| 甲公司 | 1,234 | 31.5% |\n| 乙公司 | 5,678 | 22.0% |"
TABLE_A_PADDLE = "| 項目 | 營收 | 毛利率 |\n| --- | --- | --- |\n| 甲公司 | 1234 | 31.5% |\n| 乙公司 | 5678 | 22.0% |\n| 圖表 | 100 |"
