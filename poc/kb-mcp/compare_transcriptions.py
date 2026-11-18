"""方案 D（agent 讀圖 results.json）與方案 C（PaddleOCR 評估報告）轉寫結果比對工具（010 Phase 11）。

目的：同一批表格圖，找出 D 與 C 不一致的地方，**優先列出數字差異**（少位數、小數點／千位逗號錯置、
負號或括號掉了…），讓 PO 對照原圖只看有疑慮的格子。
注意：兩邊一致不代表一定正確（兩個引擎可能犯同樣的錯）；不一致也不代表哪邊對——最終以原圖為準。

`--emit-verification <路徑>`（010 Phase 12，Q-028）：另依比對結果輸出 verification.json（method=compare-d-c）供
`investanchors_import.py --import-verification` 匯入。**雙來源一致不代表正確**——這只是「有一個獨立來源（C）與 D 沒有衝突」，
且只屬「數字家族」——必須再有文字家族（agent 逐字抽查）通過才會成為 cross_checked；絕不是 reviewed；
每筆帶 transcription_sha256（由 D results 的 text 計算，須與匯入資料庫的文字一致；D 尚未匯入資料庫的圖，匯入驗證時會被拒收）；任何疑慮一律 flagged；比對失敗或未配對的圖不輸出（維持 unverified）。

純本機：不連網、不讀鑰匙圈、不登入、不碰資料庫；只讀 results.json／manifest.json／paddle-eval-*.md，
只寫 `<out>/compare-<時間>.md`（不覆寫）。報告含轉寫片段（付費文章圖片來源，只留本機），
**但不含文章標題**（非表格的文字行內容一律不輸出，只輸出其中的數字）；stdout 只印數字摘要。
僅標準庫，Python 3.9 相容。退出碼：0 完成、2 輸入／參數錯誤（錯誤訊息只含錯誤類別，不回顯內容）。
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation

import investanchors_redact

LEVEL_HIGH, LEVEL_MID, LEVEL_LOW = "高", "中", "低"
MAX_LIST = 40            # 報告內單一清單最多列幾項（其餘只給數量）
MAX_CELL_CHARS = 40      # 報告內單一格子文字最多顯示幾字
VERIFY_VERIFIER = "compare-transcriptions"
VERIFY_METHOD = "compare-d-c"
VERIFY_MAX_ISSUES = 200
MAX_PAIR_CANDIDATES = 1000000   # 近似配對候選上限（n×m 超過就略過編輯距離配對並註明）

# 簡繁字形歸一化（--normalize-text；只放財報表格常見字，非完整字表）
_SC2TC_PAIRS = (
    "营營 业業 净淨 润潤 额額 资資 产產 负負 债債 总總 计計 万萬 亿億 区區 国國 为為 与與 对對 关關 务務 发發 应應 时時 "
    "会會 实實 还還 进進 长長 门門 间間 现現 开開 税稅 费費 买買 卖賣 库庫 价價 币幣 级級 线線 单單 据據 损損 处處 户戶 场場 "
    "转轉 东東 权權 亏虧 数數 销銷 较較 经經 间間 动動 属屬 报報 预預 测測 续續 结結 构構 际際 综綜 项項 设設 备備 车車 电電 "
    "头頭 页頁 质質 称稱 标標 题題 论論 议議 认認 证證 号號 联聯 图圖 层層 来來 种種 极極 机機 获獲 采採 术術 业業"
)
_SC2TC = {p[0]: p[1] for p in _SC2TC_PAIRS.split()}


class CompareError(Exception):
    """輸入／參數錯誤（訊息不得含檔案內容）。"""


# ====================================================================== 文字與表格解析
def basic_norm(s):
    """NFKC（全形數字、％、（）轉半形）＋U+2212 轉 '-'＋空白收斂。"""
    s = unicodedata.normalize("NFKC", s or "").replace("−", "-")
    return re.sub(r"\s+", " ", s).strip()


def text_norm(s, aggressive=False):
    s = basic_norm(s)
    if aggressive:
        s = re.sub(r"\s+", "", s).lower()
        s = "".join(_SC2TC.get(ch, ch) for ch in s)
    return s


def _split_row(line):
    """以未跳脫的 | 切欄；\\| 還原成 |。回傳 (cells, 未跳脫 | 的個數)。"""
    cells, cur, i, bars = [], [], 0, 0
    s = line.strip()
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "|":
            bars += 1
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur))
    # 去掉頭尾的「管線外空欄」
    if s.startswith("|"):
        cells = cells[1:]
    if s.endswith("|") and not s.endswith("\\|") and cells:
        cells = cells[:-1]
    return [re.sub(r"\s+", " ", c).strip() for c in cells], bars


_SEP_CELL = re.compile(r"^:?-+:?$")


def parse_markdown(text):
    """容錯解析：缺分隔列、欄數不齊、\\|、[?]、空格都可。
    回傳 {rows: [[cell]]（已補齊成同欄數）, nrows, ncols, blocks, text_lines, ragged}。
    分隔列（全是 ---／:---:）不計入 rows。"""
    rows, text_lines, blocks, in_block, ragged_raw = [], [], 0, False, set()
    for line in (text or "").splitlines():
        if not line.strip():
            in_block = False
            continue
        cells, bars = _split_row(line)
        is_row = line.strip().startswith("|") or bars >= 2
        if not is_row:
            text_lines.append(line.strip())
            in_block = False
            continue
        if cells and all(_SEP_CELL.match(c) for c in cells if c != "") and any(c for c in cells):
            in_block = True
            continue                                  # 分隔列
        if not in_block:
            blocks += 1
            in_block = True
        rows.append(cells)
        ragged_raw.add(len(cells))
    ncols = max((len(r) for r in rows), default=0)
    ragged = len(ragged_raw) > 1
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    return {"rows": rows, "nrows": len(rows), "ncols": ncols, "blocks": blocks,
            "text_lines": text_lines, "ragged": ragged}


def is_lowconf_cell(cell):
    c = basic_norm(cell)
    return "[?]" in c or c == "?"


# ====================================================================== 數值 token
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])([-+]?)(\d[\d,.]*\d|\d)(%?)")


def _make_token(sign_ch, body, pct, paren_neg, raw):
    negative = sign_ch == "-" or paren_neg
    dots = body.count(".")
    malformed = False
    if dots > 1:
        malformed = True
    elif dots == 1:
        ip, fp = body.split(".")
        if "," in fp or not fp:
            malformed = True
    ip_part = body.split(".")[0]
    if not malformed and "," in ip_part and not re.fullmatch(r"\d{1,3}(,\d{3})+", ip_part):
        malformed = True            # 千位逗號分組不合法（如 12,34、2,00）：不當成合法數字，避免逗號錯置被判一致
    if malformed:
        digits = re.sub(r"\D", "", body).lstrip("0") or "0"
        value, ip, fp = None, "", ""
        key = "~" + ("-" if negative else "") + body + ("%" if pct else "")
        abs_key = "~" + body
    else:
        if dots == 1:
            ip, fp = body.split(".")
        else:
            ip, fp = body, ""
        ip = ip.replace(",", "").lstrip("0") or "0"
        digits = (ip + fp).lstrip("0") or "0"
        try:
            value = Decimal(ip + ("." + fp if fp else ""))
        except InvalidOperation:
            value = None
        if value is not None and value == 0:
            negative = False
        abs_key = ip + ("." + fp if fp else "")
        key = ("-" if negative else "") + abs_key + ("%" if pct else "")
    return {"key": key, "abs_key": abs_key, "neg": negative, "digits": digits, "value": value,
            "signed": (-value if (negative and value is not None) else value),
            "malformed": malformed, "raw": raw, "pct": bool(pct)}


def extract_numbers(text):
    """回傳 (tokens, residue)。residue＝去掉數值 token 後的文字（供非數字差異比較）。
    括號負數 (1,234) 與 -1,234 同為 -1234（括號前緊接字母／中文的代號註記如 台積電(2330) 不算負數）；
    百分號納入 key（20.8% 與 20.8 視為不同，列「百分號有／無不同」中等；20.8% 與 208% 的數字錯置為高）；
    千位逗號分組不合法（如 12,34）視為 malformed，不與 1,234 判為一致。"""
    s = basic_norm(text)
    tokens, out, last = [], [], 0
    for m in _NUM_RE.finditer(s):
        before = s[:m.start()].rstrip()
        after = s[m.end():].lstrip()
        paren = before.endswith("(") and after.startswith(")") and m.group(1) == ""
        if paren:
            lead = s[len(before) - 2:len(before) - 1] if len(before) >= 2 else ""   # 緊貼括號的前一字元（不略過空白）
            if lead and lead.isalpha():                   # 字母／中文緊貼括號＝代號註記（台積電(2330)），不是負數
                paren = False
        raw = m.group(0)
        tokens.append(_make_token(m.group(1), m.group(2), m.group(3), paren, ("(%s)" % raw) if paren else raw))
        out.append(s[last:m.start()])
        last = m.end()
    out.append(s[last:])
    return tokens, re.sub(r"\s+", " ", "".join(out)).strip()


def _lev(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return min(prev[-1], 99)


# 規則順序＝配對確定度（越前越確定）
_R_FORMAT, _R_SIGN, _R_POINT, _R_MAG, _R_LEN1, _R_SUB, _R_ED2 = range(7)


def classify_pair(d, c):
    """D、C 兩個『不相等』的數值 token 是否看起來像同一個數字。回傳 (rule, level, reason, dist) 或 None。"""
    if d["value"] is not None and c["value"] is not None:
        if d["neg"] == c["neg"] and d["value"] == c["value"] and d["pct"] != c["pct"]:
            return (_R_FORMAT, LEVEL_MID, "百分號有／無不同（單位可能遺漏）", 0)
        if d["neg"] == c["neg"] and d["value"] == c["value"]:
            return (_R_FORMAT, LEVEL_LOW, "僅格式不同（小數位數／逗號）", 0)
        if d["neg"] != c["neg"] and d["value"] == c["value"]:
            return (_R_SIGN, LEVEL_HIGH, "正負號不同（負號或括號掉了／多出）", 0)
    dx, dy = d["digits"], c["digits"]
    if dx == "0" or dy == "0":
        return None
    if dx == dy:
        return (_R_POINT, LEVEL_HIGH, "小數點／千位逗號錯置（數字相同、位置不同）", 0)
    if dx.rstrip("0") == dy.rstrip("0"):
        return (_R_MAG, LEVEL_HIGH, "數量級差（相差 10 的整數次方）", 0)
    dist = _lev(dx, dy)
    if dist <= 2 and min(len(dx), len(dy)) >= 3:
        if abs(len(dx) - len(dy)) == 1 and dist == 1:
            return (_R_LEN1, LEVEL_MID, "位數差 1（多／少一位）", dist)
        if len(dx) == len(dy):
            return (_R_SUB, LEVEL_MID, "同位數、%d 位數字不同" % dist, dist)
        return (_R_ED2, LEVEL_MID, "位數／數字差 %d" % dist, dist)
    return None


def compare_tokens(d_tokens, c_tokens, tol=0.0):
    """d_tokens/c_tokens：[{...token, pos}]。回傳 dict：only_d、only_c（疑似配對後剩下的）、suspects、
    matched、tol_matched、skipped_pairing。"""
    dd, cc = collections.OrderedDict(), collections.OrderedDict()
    for t in d_tokens:
        dd.setdefault(t["key"], []).append(t)
    for t in c_tokens:
        cc.setdefault(t["key"], []).append(t)
    matched = 0
    only_d, only_c = [], []
    for k, lst in dd.items():
        n = min(len(lst), len(cc.get(k, [])))
        matched += n
        only_d.extend(lst[n:])
    for k, lst in cc.items():
        n = min(len(lst), len(dd.get(k, [])))
        only_c.extend(lst[n:])

    tol_matched = 0
    if tol > 0 and only_d and only_c:
        cand = []
        for i, d in enumerate(only_d):
            if d["signed"] is None:
                continue
            for j, c in enumerate(only_c):
                if c["signed"] is None:
                    continue
                m = max(abs(d["signed"]), abs(c["signed"]))
                diff = abs(d["signed"] - c["signed"])
                if m == 0 or diff <= Decimal(str(tol)) * m:
                    cand.append((float(diff / m) if m else 0.0, i, j))
        used_d, used_c = set(), set()
        for _r, i, j in sorted(cand):
            if i in used_d or j in used_c:
                continue
            used_d.add(i)
            used_c.add(j)
            tol_matched += 1
        only_d = [t for i, t in enumerate(only_d) if i not in used_d]
        only_c = [t for j, t in enumerate(only_c) if j not in used_c]

    suspects, skipped = [], False
    if only_d and only_c:
        if len(only_d) * len(only_c) > MAX_PAIR_CANDIDATES:
            skipped = True
        else:
            cand = []
            for i, d in enumerate(only_d):
                for j, c in enumerate(only_c):
                    r = classify_pair(d, c)
                    if r is not None:
                        cand.append((r[0], 0 if d["pos"] == c["pos"] else 1, r[3], i, j, r))
            used_d, used_c = set(), set()
            for _rule, _p, _dist, i, j, r in sorted(cand, key=lambda x: x[:5]):
                if i in used_d or j in used_c:
                    continue
                used_d.add(i)
                used_c.add(j)
                suspects.append({"level": r[1], "reason": r[2], "d": only_d[i], "c": only_c[j], "rule": r[0]})
            only_d = [t for i, t in enumerate(only_d) if i not in used_d]
            only_c = [t for j, t in enumerate(only_c) if j not in used_c]
    order = {LEVEL_HIGH: 0, LEVEL_MID: 1, LEVEL_LOW: 2}
    suspects.sort(key=lambda s: (order[s["level"]], s["rule"]))
    return {"only_d": only_d, "only_c": only_c, "suspects": suspects, "matched": matched,
            "tol_matched": tol_matched, "pairing_skipped": skipped}


# ====================================================================== 單張圖比對
def _tokens_of(grid):
    toks = []
    for r, row in enumerate(grid["rows"], 1):
        for c, cell in enumerate(row, 1):
            if is_lowconf_cell(cell) and not re.search(r"\d", cell):
                continue
            ts, _res = extract_numbers(cell)
            for t in ts:
                t["pos"] = (r, c)
                toks.append(t)
    for i, line in enumerate(grid["text_lines"], 1):          # 非表格文字行：只取其中的數字，不輸出內容
        ts, _res = extract_numbers(line)
        for t in ts:
            t["pos"] = ("文字行", i)
            toks.append(t)
    return toks


def _pos_str(pos):
    if pos and pos[0] == "文字行":
        return "文字行%d" % pos[1]
    return "%d列%d欄" % pos


def _lowconf_positions(grid):
    return [(r, c) for r, row in enumerate(grid["rows"], 1) for c, cell in enumerate(row, 1) if is_lowconf_cell(cell)]


def _cell_numeric_equal(td, tc, tol):
    if [t["key"] for t in td] == [t["key"] for t in tc]:
        return True
    if tol > 0 and len(td) == len(tc):
        for a, b in zip(td, tc):
            if a["signed"] is None or b["signed"] is None:
                return False
            m = max(abs(a["signed"]), abs(b["signed"]))
            if m and abs(a["signed"] - b["signed"]) > Decimal(str(tol)) * m:
                return False
        return True
    return False


def _compare_cells(pairs, tol, normalize_text):
    """pairs: [((r,c)_d, cell_d, (r,c)_c, cell_c)]。回傳 (numeric_diffs, text_diffs)。"""
    num_diffs, text_diffs = [], []
    for pd_, cd, pc_, cc in pairs:
        if not cd and not cc:
            continue
        td, rd = extract_numbers(cd)
        tc, rc = extract_numbers(cc)
        low = is_lowconf_cell(cd) or is_lowconf_cell(cc)
        if not _cell_numeric_equal(td, tc, tol):
            num_diffs.append({"pos_d": pd_, "pos_c": pc_, "d": cd, "c": cc, "lowconf": low})
        elif text_norm(rd, normalize_text) != text_norm(rc, normalize_text):
            text_diffs.append({"pos_d": pd_, "pos_c": pc_, "d": cd, "c": cc, "lowconf": low})
    return num_diffs, text_diffs


def _align_by_headers(gd, gc):
    """形狀不同時：以第 1 欄（列標籤）與第 1 列（欄標頭）的文字對齊。回傳 pairs, 說明。"""
    def labels(vals):
        cnt = collections.Counter(vals)
        return {v: i for i, v in enumerate(vals) if v and cnt[v] == 1}
    if gd["nrows"] < 2 or gc["nrows"] < 2 or gd["ncols"] < 2 or gc["ncols"] < 2:
        return [], "表格列或欄不足 2，無法用標頭對齊"
    rd = labels([text_norm(r[0], True) for r in gd["rows"]])
    rc = labels([text_norm(r[0], True) for r in gc["rows"]])
    cd = labels([text_norm(x, True) for x in gd["rows"][0]])
    cc = labels([text_norm(x, True) for x in gc["rows"][0]])
    rkeys = [k for k in rd if k in rc]
    ckeys = [k for k in cd if k in cc]
    pairs = []
    for rk in rkeys:
        for ck in ckeys:
            i, j = rd[rk], cd[ck]
            k, l = rc[rk], cc[ck]
            if i == 0 or j == 0 or k == 0 or l == 0:
                continue                      # 標頭列／標籤欄本身不當數值格比對
            pairs.append(((i + 1, j + 1), gd["rows"][i][j], (k + 1, l + 1), gc["rows"][k][l]))
    if not pairs:
        return [], "列標籤與欄標頭文字在兩邊對不上（常見原因：合併儲存格展開方式不同、標頭文字不同）"
    return pairs, "列標籤 %d／%d 相符、欄標頭 %d／%d 相符" % (len(rkeys), max(len(rd), len(rc)), len(ckeys), max(len(cd), len(cc)))


def compare_texts(d_text, c_text, tol=0.0, normalize_text=False):
    gd, gc = parse_markdown(d_text), parse_markdown(c_text)
    td, tc = _tokens_of(gd), _tokens_of(gc)
    nt = compare_tokens(td, tc, tol)
    res = {"gd": gd, "gc": gc, "td": len(td), "tc": len(tc), "tokens": nt,
           "d_low": _lowconf_positions(gd), "c_low": _lowconf_positions(gc),
           "mode": "set", "note": "", "num_diffs": [], "text_diffs": [], "aligned": 0}
    same_shape = gd["nrows"] == gc["nrows"] and gd["ncols"] == gc["ncols"] and gd["nrows"] > 0
    if same_shape:
        pairs = [((r, c), gd["rows"][r - 1][c - 1], (r, c), gc["rows"][r - 1][c - 1])
                 for r in range(1, gd["nrows"] + 1) for c in range(1, gd["ncols"] + 1)]
        res["mode"], res["note"] = "cell", "形狀相同，逐格對照"
    elif gd["nrows"] and gc["nrows"]:
        pairs, why = _align_by_headers(gd, gc)
        if pairs:
            res["mode"], res["note"] = "header", "形狀不同，改以標頭對齊（%s）；未對齊的格子只在數值集合比對中涵蓋" % why
        else:
            res["note"] = "形狀不同且無法對齊，只做數值集合比對：%s" % why
    else:
        pairs = []
        res["note"] = "其中一邊沒有表格內容，只做數值集合比對"
    res["aligned"] = len(pairs)
    res["num_diffs"], res["text_diffs"] = _compare_cells(pairs, tol, normalize_text)
    return res


# ====================================================================== 輸入讀取
MAX_INPUT_BYTES = 8 * 1024 * 1024


def _check_input_file(path, what):
    """輸入檔：不跟隨符號連結、不超過 8MB（先檢查再讀，避免被餵超大檔或指向別處的連結）。"""
    if os.path.islink(path):
        raise CompareError("%s 不可是符號連結" % what)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > MAX_INPUT_BYTES:
            raise CompareError("%s 檔案過大（上限 %d MB）" % (what, MAX_INPUT_BYTES // (1024 * 1024)))
    except OSError:
        pass


def _read_text(path):
    _check_input_file(path, "C 報告")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_json(path, what):
    _check_input_file(path, what)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise CompareError("%s 檔案不存在" % what)
    except IsADirectoryError:
        raise CompareError("%s 路徑是資料夾" % what)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise CompareError("%s 不是有效的 JSON" % what)
    except OSError as e:
        raise CompareError("%s 無法讀取（%s）" % (what, type(e).__name__))


def load_d(results_path, manifest_path):
    """回傳 {model, items:[{image_id, path, width, height, is_table, text, sha_ok}], notes:[], orphan:[image_id]}。"""
    data = _load_json(results_path, "D results.json")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise CompareError("D results.json 格式不正確（缺 results 清單）")
    man = _load_json(manifest_path, "manifest.json")
    if not isinstance(man, dict) or not isinstance(man.get("items"), list):
        raise CompareError("manifest.json 格式不正確（缺 items）")
    mitems = {}
    for it in man["items"]:
        if isinstance(it, dict) and isinstance(it.get("image_id"), int) and isinstance(it.get("path"), str):
            mitems.setdefault(it["image_id"], it)
    results, bad, dup = {}, 0, 0
    for r in data["results"]:
        if not (isinstance(r, dict) and isinstance(r.get("image_id"), int) and not isinstance(r.get("image_id"), bool)
                and isinstance(r.get("text"), str)):
            bad += 1
            continue
        if r["image_id"] in results:
            dup += 1
            continue
        results[r["image_id"]] = r
    notes = []
    if bad:
        notes.append("D results 有 %d 筆格式不正確而略過" % bad)
    if dup:
        notes.append("D results 有 %d 筆重複 image_id 而略過" % dup)
    items, orphan = [], []
    for iid, r in results.items():
        m = mitems.get(iid)
        if m is None:
            orphan.append(iid)
            continue
        sha = m.get("sha256") if isinstance(m.get("sha256"), str) else r.get("sha256")
        items.append({"image_id": iid, "path": m["path"], "width": m.get("width"), "height": m.get("height"),
                      "is_table": r.get("is_table"), "text": r["text"], "sha256": sha})
    for it in items:
        if it["is_table"] is False:
            notes.append("image_id=%d 被 D 判為非表格圖（text 為空）；若 C 在該圖轉出了表格內容，請對照原圖人工確認" % it["image_id"])
    d_missing = [iid for iid in mitems if iid not in results]
    return {"model": data.get("model") if isinstance(data.get("model"), str) else "?",
            "items": items, "orphan": orphan, "d_missing": d_missing, "notes": notes}


_H2_RE = re.compile(r"^## (\d+)\. (.*)$")
_MODE_RE = re.compile(r"^### 模式 (\S+)\s*$")
_LOWCONF_RE = re.compile(r"^低信心格（\[\?\]）：(\d+) 格\s*$")
_STATUS_RE = re.compile(r"^狀態：(\S+?)(?:（(.*)）)?\s*$")


def parse_c_report(text):
    """回傳 {engine_desc, sections:[{label, path, size, modes:{mode:{status, reason, model, text, low_count}}}]}。"""
    lines = text.splitlines()
    engine_desc = ""
    if lines and lines[0].startswith("#"):
        m = re.search(r"（(.*)）", lines[0])
        engine_desc = m.group(1) if m else ""
    sections, cur, mode, mdata, body_start = [], None, None, None, None

    def finish_mode():
        nonlocal mdata, body_start
        mdata, body_start = None, None

    for ln in lines:
        m = _H2_RE.match(ln)
        if m:
            finish_mode()
            mode = None
            label = m.group(2)
            sm = re.search(r"｜(\d+)x(\d+)", label)
            cur = {"label": label.split("｜")[0].strip(), "path": "", "size": (int(sm.group(1)), int(sm.group(2))) if sm else None,
                   "modes": collections.OrderedDict()}
            sections.append(cur)
            continue
        if ln.startswith("## "):                      # 其他二級標題（總結…）結束目前節
            finish_mode()
            cur = None
            continue
        if cur is None:
            continue
        if ln.startswith("原圖：") and not cur["path"] and mode is None:
            cur["path"] = ln[len("原圖："):].strip()
            continue
        m = _MODE_RE.match(ln)
        if m:
            finish_mode()
            mode = m.group(1)
            mdata = {"status": "unknown", "reason": None, "model": "", "text": "", "low_count": None, "_buf": None}
            cur["modes"][mode] = mdata
            continue
        if mdata is None:
            continue
        if mdata["_buf"] is None:                     # 轉寫本文之前的 metadata 行
            sm = _STATUS_RE.match(ln)
            if sm:
                mdata["status"], mdata["reason"] = sm.group(1), sm.group(2)
            elif ln.startswith("耗時："):
                em = re.search(r"引擎：(.*)$", ln)
                mdata["model"] = em.group(1).strip() if em else ""
            elif ln.startswith("is_table："):
                mdata["_buf"] = []
            continue
        lm = _LOWCONF_RE.match(ln)
        if lm:
            mdata["low_count"] = int(lm.group(1))
            mdata["text"] = "\n".join(mdata["_buf"]).strip("\n")
            mdata["_buf"] = None
            mdata["_done"] = True
            continue
        mdata["_buf"].append(ln)
    for s in sections:
        for md in s["modes"].values():
            if md.get("_buf") is not None:            # 報告被截斷：沒看到低信心行也保留本文
                md["text"] = "\n".join(md["_buf"]).strip("\n")
            md.pop("_buf", None)
            md.pop("_done", None)
    return {"engine_desc": engine_desc, "sections": [s for s in sections if s["path"]]}


def _basename(p):
    return os.path.basename((p or "").replace("\\", "/").rstrip("/"))


def build_c_sources(report_paths):
    """每份報告的每個模式 → 一個 C 來源：{id, label, sections:[{path,label,size,mode_data}]}。"""
    sources = []
    for rp in report_paths:
        try:
            text = _read_text(rp)
        except FileNotFoundError:
            raise CompareError("C 報告檔案不存在")
        except (UnicodeDecodeError, IsADirectoryError):
            raise CompareError("C 報告無法讀取為 UTF-8 文字")
        except OSError as e:
            raise CompareError("C 報告無法讀取（%s）" % type(e).__name__)
        rep = parse_c_report(text)
        if not rep["sections"]:
            raise CompareError("C 報告沒有可解析的圖片區段（不是 paddle-eval 報告？）")
        modes = []
        for s in rep["sections"]:
            for m in s["modes"]:
                if m not in modes:
                    modes.append(m)
        if not modes:
            raise CompareError("C 報告沒有任何「### 模式」區段（不是 paddle-eval 報告，或轉寫全部失敗？）")
        for m in modes:
            secs = [{"path": s["path"], "label": s["label"], "size": s["size"], "data": s["modes"][m]}
                    for s in rep["sections"] if m in s["modes"]]
            sources.append({"label": "%s｜%s" % (os.path.basename(rp), m), "engine": rep["engine_desc"], "sections": secs})
    for i, s in enumerate(sources, 1):
        s["id"] = "C%d" % i
    return sources


# ====================================================================== 報告
def _clip(s, n=MAX_CELL_CHARS):
    s = (s or "").replace("\n", " ")
    s = s if len(s) <= n else s[:n] + "…"
    return s.replace("|", "\\|")


def _shape(g):
    return "%d×%d" % (g["nrows"], g["ncols"]) if g["nrows"] else "無表格"


def _tok_str(t):
    return "%s（%s）" % (_clip(t["raw"], 24), _pos_str(t["pos"]))


def _score(cmp_):
    s = cmp_["tokens"]["suspects"]
    hi = sum(1 for x in s if x["level"] == LEVEL_HIGH)
    mid = sum(1 for x in s if x["level"] == LEVEL_MID)
    lo = sum(1 for x in s if x["level"] == LEVEL_LOW)
    return hi, mid, lo


def build_report(d, sources, matches, unmatched_c, args_desc, stamp):
    """matches: [(source, d_item, c_section|None, cmp|None, reason_text)]。回傳 Markdown。"""
    L = ["# D 與 C 轉寫比對（%s；本機、不含文章標題）" % args_desc, "", "產生時間：%s" % stamp,
         "D：%s（%d 張）" % (d["model"], len(d["items"])), ""]
    for s in sources:
        L.append("%s：%s（%s）" % (s["id"], s["label"], s["engine"] or "引擎不明"))
    L += ["", "> **兩邊一致不代表一定正確**：D 與 C 可能犯同樣的錯（例如同一個難辨的數字），不一致也不代表哪邊對。"
          "本報告只負責縮小範圍——請對照原圖核對列出的格子，最終以原圖為準。", ""]
    for n in d["notes"]:
        L.append("- 註記：%s" % n)
    if d["notes"]:
        L.append("")

    # ---- 總結（每個 C 來源一張表）
    L.append("## 總結")
    L.append("")
    ranks = []
    for s in sources:
        L.append("### %s（%s）" % (s["id"], s["label"]))
        L.append("")
        L.append("| # | 圖 | 尺寸 | D 形狀 | C 形狀 | 數值 token D／C | 只在 D／只在 C | 疑似錯置 高／中／低 | 逐格數字差異 | [?] D／C | 比對方式 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for k, (src, it, sec, cmp_, why) in enumerate([m for m in matches if m[0] is s], 1):
            size = "%sx%s" % (it["width"], it["height"]) if it.get("width") else "?"
            name = _clip(_basename(it["path"]), 30)
            if cmp_ is None:
                L.append("| %d | %s | %s | %s | - | - | - | - | - | - | %s |" % (k, name, size, "-", _clip(why, 60)))
                continue
            hi, mid, lo = _score(cmp_)
            t = cmp_["tokens"]
            L.append("| %d | %s | %s | %s | %s | %d／%d | %d／%d | %d／%d／%d | %d | %d／%d | %s |" % (
                k, name, size, _shape(cmp_["gd"]), _shape(cmp_["gc"]), cmp_["td"], cmp_["tc"],
                len(t["only_d"]), len(t["only_c"]), hi, mid, lo, len(cmp_["num_diffs"]),
                len(cmp_["d_low"]), len(cmp_["c_low"]), {"cell": "逐格", "header": "標頭對齊", "set": "僅數值集合"}[cmp_["mode"]]))
            ranks.append((hi, mid, len(cmp_["num_diffs"]), len(t["only_d"]) + len(t["only_c"]), s["id"], it, cmp_))
        L.append("")
    L.append("### 建議優先核對的圖")
    L.append("")
    ranks.sort(key=lambda x: (-x[0], -x[1], -x[2], -x[3], x[4], x[5]["image_id"]))
    shown = [r for r in ranks if r[0] or r[1] or r[2] or r[3]]
    if not shown:
        L.append("- 沒有數字差異（仍請依「如何核對」抽查：一致不代表正確）。")
    for i, (hi, mid, nd, only, sid, it, _c) in enumerate(shown[:20], 1):
        L.append("%d. %s｜%s（image_id %s）：高疑似錯置 %d、中 %d、逐格數字差異 %d、只在單邊的數字 %d" % (
            i, sid, _clip(_basename(it["path"]), 30), it["image_id"], hi, mid, nd, only))
    L.append("")

    # ---- 未配對
    L.append("## 未配對")
    L.append("")
    any_un = False
    if d["orphan"]:
        any_un = True
        L.append("- D 結果的 image_id 不在 manifest（無原圖路徑可配對）：%s" % "、".join(str(i) for i in d["orphan"][:MAX_LIST]))
    if d["d_missing"]:
        any_un = True
        L.append("- manifest 有、D results 沒有結果的 image_id：%s" % "、".join(str(i) for i in d["d_missing"][:MAX_LIST]))
    for s in sources:
        un = unmatched_c.get(s["id"], [])
        if un:
            any_un = True
            L.append("- %s 有、D 沒有對應的圖：%s" % (s["id"], "、".join(_clip(_basename(x["path"]), 30) for x in un[:MAX_LIST])))
    unmatched_d = [(s["id"], it) for (s, it, sec, _c, _w) in matches if sec is None]
    for sid, it in unmatched_d:
        any_un = True
        L.append("- %s 沒有對應 D 圖 %s（image_id %s）的區段" % (sid, _clip(_basename(it["path"]), 30), it["image_id"]))
    if not any_un:
        L.append("- 全部配對成功。")
    L.append("")

    # ---- 逐張詳細
    L.append("## 逐張詳細")
    L.append("")
    for it in d["items"]:
        size = "%sx%s" % (it["width"], it["height"]) if it.get("width") else "尺寸不明"
        L.append("### 圖 %s｜%s｜%s" % (it["image_id"], _clip(_basename(it["path"]), 40), size))
        L.append("原圖：%s" % it["path"])
        L.append("")
        for (s, it2, sec, cmp_, why) in [m for m in matches if m[1] is it]:
            L.append("#### %s（%s）" % (s["id"], s["label"]))
            L.append("")
            if cmp_ is None:
                L.append("無法比對：%s" % why)
                L.append("")
                continue
            L += _detail(cmp_, it)
    L += ["## 如何核對", "",
          "1. 依「建議優先核對的圖」由上而下，開啟該圖的**原圖**（路徑在各圖標題下方）。",
          "2. **只看列出的格子**：每個疑似錯置與逐格差異都附位置（列、欄，表頭列算第 1 列、分隔列不算）。"
          "高＝數量級或小數點錯置／正負號不同，最優先；中＝位數或個別數字不同；低＝僅格式（如 24417.0 與 24417）。",
          "3. 判斷誰對：以原圖為準；兩邊都錯也可能（兩者一致時不會被列出）。確認後，D 的錯用 `--import-transcription --overwrite` 重匯入修正。",
          "4. 「只在 D／只在 C」是找不到近似對手的數字：可能是漏格、多出的列、或形狀不同導致的錯位，同樣對照原圖。",
          "5. 文字（非數字）差異標為低優先；簡繁字形與空白差異可用 `--normalize-text` 歸一化後再比。",
          "6. 報告含轉寫片段（付費文章圖片來源），只留本機，不要貼到公開處。", ""]
    return "\n".join(L)


def _detail(cmp_, it):
    L = []
    gd, gc, t = cmp_["gd"], cmp_["gc"], cmp_["tokens"]
    L.append("- 形狀：D %s（%d 個表格區塊%s）、C %s（%d 個表格區塊%s）" % (
        _shape(gd), gd["blocks"], "，欄數不齊已補空格" if gd["ragged"] else "", _shape(gc), gc["blocks"],
        "，欄數不齊已補空格" if gc["ragged"] else ""))
    L.append("- 比對方式：%s" % cmp_["note"])
    L.append("- 數值 token：D %d、C %d；完全相同 %d%s" % (cmp_["td"], cmp_["tc"], t["matched"],
                                                    ("；容差內視為一致 %d" % t["tol_matched"]) if t["tol_matched"] else ""))
    if t["pairing_skipped"]:
        L.append("- 註記：候選數量過多，略過近似配對，只列出『只在 D／只在 C』。")
    L.append("")
    if t["suspects"]:
        L.append("**疑似錯置（數字）**")
        L.append("")
        L.append("| 等級 | D 值（位置） | C 值（位置） | 原因 |")
        L.append("| --- | --- | --- | --- |")
        for x in t["suspects"][:MAX_LIST]:
            L.append("| %s | %s | %s | %s |" % (x["level"], _tok_str(x["d"]), _tok_str(x["c"]), x["reason"]))
        if len(t["suspects"]) > MAX_LIST:
            L.append("| … | 另 %d 項未列出 | | |" % (len(t["suspects"]) - MAX_LIST))
        L.append("")
    for title, lst in (("只在 D 的數字", t["only_d"]), ("只在 C 的數字", t["only_c"])):
        if lst:
            L.append("**%s**（%d 個）：%s%s" % (title, len(lst), "、".join(_tok_str(x) for x in lst[:MAX_LIST]),
                                           "、…另 %d 個" % (len(lst) - MAX_LIST) if len(lst) > MAX_LIST else ""))
            L.append("")
    if cmp_["num_diffs"]:
        L.append("**逐格數字差異**（%d 格；已對齊 %d 格）" % (len(cmp_["num_diffs"]), cmp_["aligned"]))
        L.append("")
        L.append("| D 位置 | C 位置 | D 值 | C 值 | 備註 |")
        L.append("| --- | --- | --- | --- | --- |")
        for x in cmp_["num_diffs"][:MAX_LIST * 2]:
            L.append("| %s | %s | %s | %s | %s |" % (_pos_str(x["pos_d"]), _pos_str(x["pos_c"]), _clip(x["d"]) or "（空）",
                                                    _clip(x["c"]) or "（空）", "含 [?]" if x["lowconf"] else ""))
        if len(cmp_["num_diffs"]) > MAX_LIST * 2:
            L.append("| … | | 另 %d 格未列出 | | |" % (len(cmp_["num_diffs"]) - MAX_LIST * 2))
        L.append("")
    for who, low in (("D", cmp_["d_low"]), ("C", cmp_["c_low"])):
        if low:
            L.append("**%s 的 [?]／低信心格**：%d 格：%s%s" % (who, len(low), "、".join("%d列%d欄" % p for p in low[:MAX_LIST]),
                                                       "、…" if len(low) > MAX_LIST else ""))
            L.append("")
    if cmp_["text_diffs"]:
        L.append("**文字（非數字）差異｜低優先**（%d 格）" % len(cmp_["text_diffs"]))
        L.append("")
        L.append("| D 位置 | C 位置 | D 文字 | C 文字 |")
        L.append("| --- | --- | --- | --- |")
        for x in cmp_["text_diffs"][:MAX_LIST // 2]:
            L.append("| %s | %s | %s | %s |" % (_pos_str(x["pos_d"]), _pos_str(x["pos_c"]), _clip(x["d"]), _clip(x["c"])))
        if len(cmp_["text_diffs"]) > MAX_LIST // 2:
            L.append("| … | | 另 %d 格未列出 | |" % (len(cmp_["text_diffs"]) - MAX_LIST // 2))
        L.append("")
    if not (t["suspects"] or t["only_d"] or t["only_c"] or cmp_["num_diffs"] or cmp_["text_diffs"]):
        L.append("數字與格子完全一致（仍不代表正確，請抽查）。")
        L.append("")
    return L


# ====================================================================== 驗證檔輸出（Q-028）
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _vclip(s, n):
    """驗證檔欄位：單行、去控制字元、截短；疑似金鑰字串以固定文字取代（匯入端會整批拒收這種字串）。"""
    s = re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]", " ", str(s or ""))
    s = " ".join(s.split())
    if investanchors_redact.secret_like(s):
        s = "（內容已省略）"
    return s if len(s) <= n else s[:n - 1] + "…"


def _issue(where, found, expected, kind):
    it = {"where": _vclip(where, 80) or "整張圖", "found": _vclip(found, 200), "kind": kind}
    exp = _vclip(expected, 200)
    if exp:
        it["expected"] = exp
    return it


def _compare_concerns(sid, cmp_):
    """單一 C 來源的比對 → 疑慮清單（沒有＝空）。判定依 PO 規格：高／中疑似錯置、只在單邊的數字、
    形狀不同而標頭對齊失敗、逐格數字差異、D 自己標了 [?]；低（僅格式）疑似與非數字文字差異**不**納入判定。"""
    out = []
    t = cmp_["tokens"]
    for x in t["suspects"]:
        if x["level"] in (LEVEL_HIGH, LEVEL_MID):
            out.append(_issue("%s：D %s／C %s" % (sid, _pos_str(x["d"]["pos"]), _pos_str(x["c"]["pos"])),
                              x["d"]["raw"], x["c"]["raw"], "wrong-number"))
    for x in t["only_d"]:
        out.append(_issue("%s：D %s" % (sid, _pos_str(x["pos"])), x["raw"], "", "extra"))
    for x in t["only_c"]:
        out.append(_issue("%s：C %s" % (sid, _pos_str(x["pos"])), "D 沒有對應的數字", x["raw"], "missing"))
    for x in cmp_["num_diffs"]:
        out.append(_issue("%s：D %s／C %s" % (sid, _pos_str(x["pos_d"]), _pos_str(x["pos_c"])),
                          x["d"] or "（空）", x["c"] or "（空）", "wrong-number"))
    gd, gc = cmp_["gd"], cmp_["gc"]
    if (gd["nrows"], gd["ncols"]) != (gc["nrows"], gc["ncols"]) and cmp_["mode"] != "header":
        out.append(_issue("%s：整張圖" % sid, "D %s／C %s，無法以標頭對齊" % (_shape(gd), _shape(gc)), "", "other"))
    for p in cmp_["d_low"]:
        out.append(_issue("%s：D %s" % (sid, _pos_str(p)), "[?] 存疑格（D 自己標示看不清楚）", "", "other"))
    return out


def build_verification(d, matches):
    """依比對結果組 verification.json。回傳 (payload|None, {"ok":n,"issues":n,"skipped":n})。
    * D 判為非表格而任一 C 來源有內容 → issues；其餘非表格圖不輸出（沒有轉寫文字可驗證）。
    * 表格圖：只用比對成功的來源；沒有任何成功來源、或兩邊都沒有數字可比 → 不輸出（維持 unverified）；
      任何成功來源有疑慮 → issues；全部成功來源皆無疑慮 → ok。
    * 缺有效 sha256 的圖不輸出。"""
    results, counts = [], {"ok": 0, "issues": 0, "skipped": 0}
    for it in d["items"]:
        sha = it.get("sha256")
        mine = [m for m in matches if m[1] is it]
        if not isinstance(sha, str) or not _SHA_RE.match(sha):
            counts["skipped"] += 1
            continue
        issues, verdict = [], None
        if it.get("is_table") is False:
            filled = [m for m in mine if m[2] is not None and m[2]["data"]["status"] == "transcribed"
                      and (m[2]["data"]["text"] or "").strip()]
            if filled:
                verdict = "issues"
                issues = [_issue("%s：整張圖" % m[0]["id"], "D 判為非表格（沒有轉寫）", "C 轉出了內容", "missing") for m in filled]
        else:
            done = [m for m in mine if m[3] is not None]
            if done and any(m[3]["td"] + m[3]["tc"] > 0 for m in done):
                for m in done:
                    issues.extend(_compare_concerns(m[0]["id"], m[3]))
                verdict = "issues" if issues else "ok"
        if verdict is None:
            counts["skipped"] += 1
            continue
        row = {"image_id": it["image_id"], "sha256": sha,
               "transcription_sha256": hashlib.sha256((it["text"] or "").encode("utf-8")).hexdigest(),
               "verdict": verdict}
        if verdict == "issues":
            seen, uniq = set(), []
            for x in issues:
                key = (x["where"], x["found"], x.get("expected"), x["kind"])
                if key not in seen:
                    seen.add(key)
                    uniq.append(x)
            row["issues"] = uniq[:VERIFY_MAX_ISSUES]
        counts[verdict] += 1
        results.append(row)
    if not results:
        return None, counts
    return {"version": 1, "verifier": VERIFY_VERIFIER, "method": VERIFY_METHOD, "results": results}, counts


# ====================================================================== 主流程
def build_parser():
    ap = argparse.ArgumentParser(description="方案 D（results.json）與方案 C（paddle-eval 報告）轉寫比對（本機、離線）")
    ap.add_argument("--d-results", required=True, help="D 的 results.json")
    ap.add_argument("--manifest", default=None, help="manifest.json（預設與 results.json 同資料夾）")
    ap.add_argument("--c-report", action="append", required=True, help="paddle-eval-*.md；可重複，每個模式視為一個 C 來源")
    ap.add_argument("--out", required=True, help="輸出資料夾（寫 compare-<時間>.md，不覆寫）")
    ap.add_argument("--numeric-tol", type=float, default=0.0,
                    help="數值相對容差（預設 0＝必須完全相同；0.01＝相差 1%% 內視為一致）")
    ap.add_argument("--normalize-text", action="store_true", help="非數字文字比較前歸一化（去空白、小寫、簡繁字形）")
    ap.add_argument("--emit-verification", default=None, metavar="PATH",
                    help="另輸出 verification.json（method=compare-d-c；不覆寫既有檔）。雙來源一致不代表正確：ok 只算數字家族通過"
                         "（另需 agent 文字抽查才成為 cross_checked）；有任何疑慮→issues；比對失敗或未配對的圖不輸出")
    return ap


def _write_new_json(path, payload):
    """寫驗證檔：不覆寫既有檔、不寫進符號連結。"""
    if os.path.islink(path):
        raise CompareError("--emit-verification 不可是符號連結")
    if os.path.isdir(path):
        raise CompareError("--emit-verification 必須是檔案路徑（目前指到資料夾）")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    try:
        f = open(path, "x", encoding="utf-8")
    except FileExistsError:
        raise CompareError("--emit-verification 的檔案已存在，不覆寫")
    with f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run(argv=None, now=None, say=print):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else 0
    err = lambda m: print(m, file=sys.stderr)       # noqa: E731
    try:
        if not (args.numeric_tol >= 0 and args.numeric_tol < 1):
            raise CompareError("--numeric-tol 必須在 0 到 1 之間")
        if os.path.exists(args.out) and not os.path.isdir(args.out):
            raise CompareError("--out 必須是資料夾（目前指到檔案）")
        if args.emit_verification and (os.path.exists(args.emit_verification) or os.path.islink(args.emit_verification)):
            raise CompareError("--emit-verification 的路徑已存在，不覆寫")
        manifest = args.manifest or os.path.join(os.path.dirname(os.path.abspath(args.d_results)), "manifest.json")
        d = load_d(args.d_results, manifest)
        sources = build_c_sources(args.c_report)

        matches, unmatched_c = [], {}
        for s in sources:
            used = set()
            for it in d["items"]:
                sec = None
                for i, c in enumerate(s["sections"]):
                    if i not in used and c["path"] == it["path"]:
                        sec, used_i = c, i
                        break
                if sec is None:
                    for i, c in enumerate(s["sections"]):
                        if i not in used and _basename(c["path"]) == _basename(it["path"]):
                            sec, used_i = c, i
                            break
                if sec is None:
                    matches.append((s, it, None, None, "C 報告沒有對應這張圖的區段"))
                    continue
                used.add(used_i)
                data = sec["data"]
                if data["status"] != "transcribed":
                    matches.append((s, it, sec, None, "C 轉寫失敗（%s%s）" % (data["status"], "：%s" % data["reason"] if data["reason"] else "")))
                    continue
                matches.append((s, it, sec, compare_texts(it["text"], data["text"], args.numeric_tol, args.normalize_text), ""))
            unmatched_c[s["id"]] = [c for i, c in enumerate(s["sections"]) if i not in used]

        stamp_dt = (now or datetime.datetime.now)()
        stamp = stamp_dt.strftime("%Y%m%d-%H%M%S")
        desc = "D=%s；C=%d 個來源；numeric-tol=%s；normalize-text=%s" % (
            d["model"], len(sources), args.numeric_tol, "開" if args.normalize_text else "關")
        report = build_report(d, sources, matches, unmatched_c, desc, stamp_dt.strftime("%Y-%m-%d %H:%M:%S"))
        os.makedirs(args.out, exist_ok=True)
        out_path, n = os.path.join(args.out, "compare-%s.md" % stamp), 1
        while True:
            try:
                f = open(out_path, "x", encoding="utf-8")
                break
            except FileExistsError:
                n += 1
                out_path = os.path.join(args.out, "compare-%s-%d.md" % (stamp, n))
                if n > 1000:
                    raise
        with f:
            f.write(report)
        ver_note = ""
        if args.emit_verification:
            payload, vc = build_verification(d, matches)
            if payload is None:
                ver_note = "；驗證檔：無可輸出的圖（未輸出 %d 張，維持 unverified）" % vc["skipped"]
            else:
                _write_new_json(args.emit_verification, payload)
                ver_note = "；驗證檔 ok %d／issues %d／未輸出 %d → %s" % (vc["ok"], vc["issues"], vc["skipped"], args.emit_verification)
    except CompareError as e:
        err("拒絕執行：%s" % e)
        return 2
    except (OSError, ValueError, RecursionError, TypeError, AttributeError, KeyError) as e:
        err("比對失敗：%s" % type(e).__name__)
        return 2

    real = [m for m in matches if m[3] is not None]
    hi = mid = lo = nd = 0
    for m in real:
        a, b, c = _score(m[3])
        hi, mid, lo, nd = hi + a, mid + b, lo + c, nd + len(m[3]["num_diffs"])
    unmatched = len(d["orphan"]) + len(d["d_missing"]) + sum(1 for m in matches if m[2] is None) + sum(len(v) for v in unmatched_c.values())
    say("比對完成：D %d 張、C 來源 %d 份、成功比對 %d 組、未配對／失敗 %d；疑似錯置 高 %d／中 %d／低 %d；逐格數字差異 %d；報告 %s"
        % (len(d["items"]), len(sources), len(real), unmatched + sum(1 for m in matches if m[2] is not None and m[3] is None),
           hi, mid, lo, nd, out_path) + ver_note)
    return 0


def main():
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
