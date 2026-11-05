"""委託書號正規化（specs/009-cathay-tw-statement-import research R4、FR-005）。

同一個國泰委託書號在不同來源寫法不同：
- 交易明細表（2026-08-31 起的解析）：`k-ABCD-00`
- 交易明細表（2026-07-31 的舊解析）：`kABCD`（無連字號、無序號）
- 日對帳單：`kABCD00`

既有防重複是字串完全比對，正式庫已因此出現重複成交（docs/spec-intake/
broker-statement-import/raw/src-004）。比對一律改用 `normalize_order_ref()`：
前綴字母＋4 碼委託編號＋2 碼序號，忽略連字號與空白；**大小寫保留**（編號大小寫
混合且有意義，轉換可能讓兩張不同委託相撞）；沒有序號者視為 `00`；同一委託不同
序號（`-00`／`-01`）是不同成交。不符合樣式的字串只去空白、原樣回傳，不猜。

僅標準庫，Python 3.9 相容。
"""
import re

_PATTERN = re.compile(r"^([A-Za-z])([0-9A-Za-z]{4})(\d{2})?$")


def normalize_order_ref(ref):
    """回傳正規化後的委託書號；空值回傳 None。"""
    if ref is None:
        return None
    compact = re.sub(r"[\s\-]", "", str(ref))
    if not compact:
        return None
    m = _PATTERN.match(compact)
    if not m:
        return compact
    prefix, body, seq = m.groups()
    return prefix + body + (seq or "00")
