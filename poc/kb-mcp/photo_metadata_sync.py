"""標籤/評分中繼資料同步：把 STND 資料庫裡的標籤與評分單向寫回照片
檔案本身的 XMP/IPTC 中繼資料（User Story 3，spec.md FR-012~015）。

**架構原則**（見 `specs/004-photos-albums-search/research.md` §2、
`docs/spec-intake/alphavibe/supporting-artifacts/
2026-09-16-travel-photos-design.md`「四、2026-09-17 補充」）：資料庫
永遠是搜尋與真相來源，`write_metadata()` 是**單向鏡射**（db → 檔案）
——已存在的紀錄，STND 從不反過來讀檔案中繼資料做搜尋或還原資料。
寫入失敗或原始檔所在硬碟未掛載都不影響資料庫端的標籤/評分/搜尋，
呼叫端據此決定 `metadata_sync_status` 該標 `pending`（暫時性，見
`MetadataSyncUnavailable`）還是 `failed`（見 `RuntimeError`）。

**唯一的例外**（2026-09-30 新增 `read_existing_tags()`）：`photo_
importer.commit_import()` 建立**全新**照片紀錄的那一刻，會呼叫這個
函式檢查照片檔案本身是否已經帶有標籤/評分（例如使用者在 MacBook Air
上用另一套 STND 離線整理過、標籤已經寫進檔案，或相機/其他工具本來就
有評分），有的話直接套用到這筆新紀錄上。這**不是**對上面「單向鏡射」
原則的違反——那條原則管的是「已存在的紀錄」不會被檔案內容影響；這裡
只在「紀錄還不存在、剛要誕生」的瞬間讀一次，之後這筆紀錄的搜尋/編輯
完全回到資料庫為準，不會再讀檔案。跟 `photo_store.py` docstring
記錄的另外兩個 `file_hash` 例外（人工確認清單／原地內容修正）是
同一種性質的受限例外，理由也一致：讀取的時機被嚴格限定，不是常態性
的「檔案內容可以隨時覆蓋資料庫」。

`exiftool` 是系統層外部依賴（非 Python 套件，`brew install exiftool`
安裝）。MVP 範圍僅處理 JPG（見 `photo_importer.py` 的 `VALID_EXTENSIONS`）。

**實作時實測發現的關鍵細節**（原 `research.md` §2 的命令格式只是
方向性設計，這裡補上實測驗證過的精確語法）：
- **IPTC 中文字元預設會被當成 Latin 編碼寫壞**（`夕陽` 寫入後讀出來變
  `??`）——必須加 `-charset iptc=UTF8` 告訴 exiftool 這次呼叫要用
  UTF-8 讀寫 IPTC；`XMP:Subject` 本身就是 Unicode-safe，不受影響
- 只加 `-charset iptc=UTF8` 還不夠**跨工具**相容——這只影響 exiftool
  自己這次呼叫怎麼寫，沒有在檔案裡留下「這是 UTF-8」的標記，其他
  工具（或沒指定 `-charset` 的 exiftool 呼叫）讀回會是亂碼。必須額外
  明確寫入 `-IPTC:CodedCharacterSet=UTF8` 這個 IPTC envelope 欄位，
  其他標準工具（Lightroom、Finder 等）才會正確辨識並解碼——這正是
  PO 選擇「跟著相片走」這個方向的目的（見 Q-050），少這個標記等於
  沒有真正達成可攜性
- 多值欄位（`Keywords`／`Subject`）用一般 `=`（不是 `+=`）重複帶多次
  即為**整批取代**語意，對應 `PhotoStore.set_photo_tags()` 的取代
  語意（已實測確認：檔案原有「夕陽/京都」，重新只帶「夜景」寫入後，
  檔案裡的標籤真的變成只剩「夜景」，不是疊加）
- 標籤清空（`tags=[]`）要明確帶 `-IPTC:Keywords= -XMP:Subject=`
  （等號後面留空），不能省略這兩個參數——省略的話檔案裡的舊標籤會
  維持原樣不動，不會被清空
- `-overwrite_original` 確認不會留下 `_original` 備份檔（已實測確認）
"""
import json
import os
import subprocess


class MetadataSyncUnavailable(Exception):
    """原始檔案目前無法存取（例如外接硬碟未掛載）——呼叫端應將
    `metadata_sync_status` 標記為 `pending`（暫時性，之後補寫即可），
    不是 `failed`。"""


def read_existing_tags(path):
    """讀取 `path` 指向的照片檔案裡**已經存在**的標籤（`Subject`）與
    評分（`Rating`）——只給 `photo_importer.commit_import()` 在建立
    全新照片紀錄時呼叫一次，見本檔案開頭 docstring「唯一的例外」。

    找不到欄位、檔案不存在、exiftool 執行失敗都回傳 `([], 0)`，**不
    拋例外**——沒有既有標籤是正常情況（剛從記憶卡出來的原始檔案本來
    就沒有），呼叫端不需要特別處理任何失敗分支。

    `Subject` 欄位只有一個標籤時 exiftool 回傳字串、多個標籤時回傳
    陣列，這裡統一轉成清單回傳。"""
    try:
        proc = subprocess.run(
            ["exiftool", "-j", "-charset", "iptc=UTF8", "-Rating", "-Subject", path],
            capture_output=True, timeout=15)
        if proc.returncode != 0:
            return [], 0
        data = json.loads(proc.stdout.decode("utf-8", "replace"))[0]
    except (subprocess.SubprocessError, OSError, ValueError, IndexError, KeyError):
        return [], 0

    rating = data.get("Rating") or 0
    subject = data.get("Subject")
    if isinstance(subject, str):
        tags = [subject]
    elif isinstance(subject, list):
        tags = [str(t) for t in subject]
    else:
        tags = []
    return tags, rating


def write_metadata(storage_path, tags, rating):
    """把 `tags`（標籤清單）與 `rating`（0-5）寫入 `storage_path` 指向
    的照片檔案。成功時無回傳值；失敗時拋出例外，由呼叫端依例外類型
    決定 `metadata_sync_status` 該標記成什麼（見本檔案開頭 docstring）。

    Raises:
        MetadataSyncUnavailable: 檔案目前不存在/無法存取。
        RuntimeError: exiftool 執行失敗（格式不支援、檔案損壞、權限
            問題等），訊息包含 exiftool 的錯誤輸出，供記錄
            `metadata_sync_error`。
    """
    if not os.path.exists(storage_path):
        raise MetadataSyncUnavailable(
            "原始檔案目前無法存取（可能是外接硬碟未掛載）：%s" % storage_path)

    cmd = [
        "exiftool", "-charset", "iptc=UTF8", "-overwrite_original",
        "-IPTC:CodedCharacterSet=UTF8",
        "-XMP:Rating=%d" % rating,
    ]
    if tags:
        for tag in tags:
            cmd.append("-IPTC:Keywords=%s" % tag)
            cmd.append("-XMP:Subject=%s" % tag)
    else:
        # 標籤清空時必須明確帶空值才會真的清掉檔案裡的舊標籤（見本檔案
        # 開頭 docstring 的實測發現，省略這兩個參數只會維持原樣不動）。
        cmd.append("-IPTC:Keywords=")
        cmd.append("-XMP:Subject=")
    cmd.append(storage_path)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError("exiftool 執行失敗：%s" % exc)

    if proc.returncode != 0:
        raise RuntimeError(
            "exiftool 回傳非 0：%s"
            % proc.stderr.decode("utf-8", "replace").strip())
