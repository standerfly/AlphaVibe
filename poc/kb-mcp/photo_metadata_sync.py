"""標籤/評分中繼資料同步：把 STND 資料庫裡的標籤與評分單向寫回照片
檔案本身的 XMP/IPTC 中繼資料（User Story 3，spec.md FR-012~015）。

**架構原則**（見 `specs/004-photos-albums-search/research.md` §2、
`docs/spec-intake/alphavibe/supporting-artifacts/
2026-09-16-travel-photos-design.md`「四、2026-09-17 補充」）：資料庫
永遠是搜尋與真相來源，這裡的寫入是**單向鏡射**（db → 檔案）——STND
從不反過來讀檔案中繼資料做搜尋或還原資料。寫入失敗或原始檔所在硬碟
未掛載都不影響資料庫端的標籤/評分/搜尋，呼叫端據此決定
`metadata_sync_status` 該標 `pending`（暫時性，見
`MetadataSyncUnavailable`）還是 `failed`（見 `RuntimeError`）。

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
import os
import subprocess


class MetadataSyncUnavailable(Exception):
    """原始檔案目前無法存取（例如外接硬碟未掛載）——呼叫端應將
    `metadata_sync_status` 標記為 `pending`（暫時性，之後補寫即可），
    不是 `failed`。"""


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
