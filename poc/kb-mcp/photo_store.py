"""相簿分頁儲存層：`PhotoStore`。

**完全獨立於 `poc/kb-mcp/kb_store.py`／`KBStore` 與
`us_stock_store.py`／`USStockStore`**——不 import、不繼承、不共用任何
程式碼或資料表，獨立資料庫檔案 `poc/data/photos.db`。決策依據見
`specs/004-photos-albums-search/research.md`、`data-model.md`。

5 張表：`albums`（相簿）／`photos`（照片）／`photo_albums`（多對多）／
`tags`（標籤主檔）／`photo_tags`（多對多）。多對多關聯表以邏輯鍵關聯，
不建立外鍵約束（比照 `us_stock_store.py` 既有慣例）。

**不得在 `__init__` 掛任何有副作用的種子寫入邏輯**——2026-08-22 資產表
事故教訓（見 AlphaVibe/CLAUDE.md 教訓紀錄）：`KBStore.__init__` 曾經
無條件呼叫種子寫入方法，導致任何建構 `KBStore` 的呼叫端都會觸發寫入，
正式資料庫因此被污染兩次。這個類別從設計上就不建立這種耦合——
`__init__` 只做 schema 建立，不寫入任何列。

**`photos.file_hash` 只在匯入掃描時對來源檔案計算一次、永久保存，
之後任何方法都不得重新計算**（`research.md` §4）——這是刻意設計，
去重機制的正確性依賴這一點；日後標籤/評分中繼資料寫回會改變檔案本身
的位元組，但絕不能因此重算 `file_hash`，否則同一份原始素材重複匯入
會被誤判為「新照片」而不是重複。本檔案（Foundational＋User Story 1
範圍）沒有任何方法會觸碰已存在照片的 `file_hash`。

**本次（`specs/004-photos-albums-search`）實作範圍**：Foundational
（schema／相簿 CRUD／照片基礎方法／標籤方法）＋ User Story 1（匯入、
整理、瀏覽）。全域搜尋（User Story 2）與標籤/評分中繼資料同步狀態轉換
（User Story 3）的 Store 方法留待對應 Story 階段再新增，不在這裡預先
實作——保持每個 Story 可獨立完成、獨立驗證的設計原則
（`tasks.md`「Dependencies & Execution Order」）。

限制：這台開發機只有 Python 3.9.6，不使用 3.10+ 語法（match-case、
`X | Y` 型別聯集寫法）；僅用標準庫（`sqlite3`），比照
`us_stock_store.py` 既有慣例。
"""
import datetime
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    cover_photo_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT NOT NULL UNIQUE,
    storage_path TEXT NOT NULL,
    storage_location TEXT NOT NULL,
    thumbnail_path TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 0,
    camera_model TEXT,
    lens TEXT,
    iso INTEGER,
    shutter_speed TEXT,
    aperture TEXT,
    photo_date TEXT,
    file_size INTEGER,
    imported_at TEXT NOT NULL,
    metadata_sync_status TEXT NOT NULL DEFAULT 'pending',
    metadata_synced_at TEXT,
    metadata_sync_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_photos_file_hash ON photos(file_hash);

CREATE TABLE IF NOT EXISTS photo_albums (
    photo_id INTEGER NOT NULL,
    album_id INTEGER NOT NULL,
    UNIQUE(photo_id, album_id)
);
CREATE INDEX IF NOT EXISTS idx_photo_albums_album ON photo_albums(album_id);
CREATE INDEX IF NOT EXISTS idx_photo_albums_photo ON photo_albums(photo_id);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    UNIQUE(photo_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_photo_tags_tag ON photo_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_photo_tags_photo ON photo_tags(photo_id);
"""

VALID_STORAGE_LOCATIONS = ("internal", "external")
VALID_SYNC_STATUSES = ("synced", "pending", "failed")
VALID_SORT_FIELDS = {"date": "photo_date", "rating": "rating"}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class PhotoStore:
    def __init__(self, data_dir):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "photos.db")
        # check_same_thread=False：比照 kb_store.py／us_stock_store.py
        # 2026-08-22 教訓——FastAPI 的 sync generator dependency 由 anyio
        # thread pool 執行，同一個 request 的「建立」與「關閉」不保證在
        # 同一條 worker thread，這裡預先關掉這個誤判，實際上並沒有真正
        # 跨執行緒併發存取同一個連線。
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # 刻意不呼叫任何種子資料寫入方法——見本檔案開頭 docstring 的
        # 2026-08-22 教訓。

    def close(self):
        self.conn.close()

    # ---------- albums ----------

    def create_album(self, title, description=None):
        if not title or not title.strip():
            raise ValueError("title 不得為空")
        created_at = _now()
        cur = self.conn.execute(
            "INSERT INTO albums (title, description, cover_photo_id, created_at)"
            " VALUES (?, ?, NULL, ?)",
            (title.strip(), description, created_at),
        )
        self.conn.commit()
        return self.get_album(cur.lastrowid)

    def get_album(self, album_id):
        row = self.conn.execute(
            "SELECT * FROM albums WHERE id=?", (album_id,)).fetchone()
        return dict(row) if row else None

    def list_albums(self):
        """相簿列表附照片數（`photo_albums` 計數），供相簿列表卡片顯示。"""
        rows = self.conn.execute(
            "SELECT a.*, "
            " (SELECT COUNT(*) FROM photo_albums pa WHERE pa.album_id = a.id)"
            "   AS photo_count"
            " FROM albums a ORDER BY a.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_album(self, album_id, title=None, description=None,
                      cover_photo_id=None):
        existing = self.get_album(album_id)
        if existing is None:
            return None
        new_title = title if title is not None else existing["title"]
        if not new_title or not new_title.strip():
            raise ValueError("title 不得為空")
        new_description = (description if description is not None
                            else existing["description"])
        new_cover = (cover_photo_id if cover_photo_id is not None
                     else existing["cover_photo_id"])
        self.conn.execute(
            "UPDATE albums SET title=?, description=?, cover_photo_id=?"
            " WHERE id=?",
            (new_title.strip(), new_description, new_cover, album_id),
        )
        self.conn.commit()
        return self.get_album(album_id)

    def delete_album(self, album_id):
        """刪除相簿本身與 `photo_albums` 關聯，**不動照片紀錄**（照片
        可能還屬於其他相簿，或本來就允許沒有任何相簿）。"""
        existing = self.get_album(album_id)
        if existing is None:
            return None
        self.conn.execute("DELETE FROM photo_albums WHERE album_id=?", (album_id,))
        self.conn.execute("DELETE FROM albums WHERE id=?", (album_id,))
        self.conn.commit()
        return existing

    def add_photo_to_album(self, photo_id, album_id):
        self.conn.execute(
            "INSERT OR IGNORE INTO photo_albums (photo_id, album_id)"
            " VALUES (?, ?)", (photo_id, album_id))
        self.conn.commit()

    def list_album_photos(self, album_id, sort="date", tag=None):
        """相簿內縮圖牆（spec.md FR-009 相簿內瀏覽；不含跨相簿搜尋，
        那是 User Story 2 的 `search_photos()`）。`sort` 僅接受
        `data-model.md`「查詢模式」定義的 `date`／`rating`。"""
        sort_col = VALID_SORT_FIELDS.get(sort, "photo_date")
        query = (
            "SELECT p.* FROM photos p"
            " JOIN photo_albums pa ON pa.photo_id = p.id"
            " WHERE pa.album_id = ?"
        )
        params = [album_id]
        if tag:
            query += (
                " AND p.id IN ("
                "  SELECT pt.photo_id FROM photo_tags pt"
                "  JOIN tags t ON t.id = pt.tag_id WHERE t.name = ?)"
            )
            params.append(tag)
        query += " ORDER BY p.%s DESC" % sort_col
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ---------- photos ----------

    def find_by_hash(self, file_hash):
        """去重比對用（`photo_importer.scan_folder()` 呼叫）。**不會**
        觸發任何 hash 重新計算，純粹查詢既有紀錄。"""
        row = self.conn.execute(
            "SELECT * FROM photos WHERE file_hash=?", (file_hash,)).fetchone()
        return dict(row) if row else None

    def add_photo(self, file_hash, storage_path, storage_location,
                  thumbnail_path, camera_model=None, lens=None, iso=None,
                  shutter_speed=None, aperture=None, photo_date=None,
                  file_size=None):
        """寫入一筆新照片。`file_hash` 由呼叫端（`photo_importer.py`）在
        匯入掃描階段對來源檔案計算好傳入——這裡只負責寫入，不重新計算、
        不驗證 hash 是否「正確」，見本檔案開頭 docstring 的核心保證。"""
        if storage_location not in VALID_STORAGE_LOCATIONS:
            raise ValueError(
                "storage_location 必須是 %s，收到：%s"
                % (VALID_STORAGE_LOCATIONS, storage_location))
        imported_at = _now()
        cur = self.conn.execute(
            "INSERT INTO photos"
            " (file_hash, storage_path, storage_location, thumbnail_path,"
            "  rating, camera_model, lens, iso, shutter_speed, aperture,"
            "  photo_date, file_size, imported_at, metadata_sync_status)"
            " VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (file_hash, storage_path, storage_location, thumbnail_path,
             camera_model, lens, iso, shutter_speed, aperture, photo_date,
             file_size, imported_at),
        )
        self.conn.commit()
        return self.get_photo(cur.lastrowid)

    def get_photo(self, photo_id):
        row = self.conn.execute(
            "SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        return dict(row) if row else None

    def delete_photo(self, photo_id):
        """刪除照片紀錄（spec.md FR-011：僅刪 db，**不刪磁碟上的原始
        檔案**——呼叫端不會、也不該對 `storage_path` 執行任何檔案系統
        操作）。回傳刪除前的紀錄，`None`＝找不到，供呼叫端判斷要不要
        回 404（比照 `us_stock_store.py` 既有慣例）。"""
        existing = self.get_photo(photo_id)
        if existing is None:
            return None
        self.conn.execute("DELETE FROM photo_albums WHERE photo_id=?", (photo_id,))
        self.conn.execute("DELETE FROM photo_tags WHERE photo_id=?", (photo_id,))
        self.conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
        self.conn.commit()
        return existing

    def set_photo_rating(self, photo_id, rating):
        if rating is None or not (0 <= rating <= 5):
            raise ValueError("rating 必須是 0 到 5 的整數")
        if self.get_photo(photo_id) is None:
            return None
        self.conn.execute(
            "UPDATE photos SET rating=? WHERE id=?", (rating, photo_id))
        self.conn.commit()
        return self.get_photo(photo_id)

    # ---------- tags ----------

    def get_or_create_tag(self, name):
        """標籤正規化：去除前後空白、大小寫不敏感比對既有標籤（避免
        「京都」跟「京都 」／「Sunset」跟「sunset」各自長成一個標籤，見
        `data-model.md`「正規化主檔的理由」）。已存在則回傳既有的
        `tags.id`，不會建立新的一筆。"""
        normalized = (name or "").strip()
        if not normalized:
            raise ValueError("標籤名稱不得為空")
        row = self.conn.execute(
            "SELECT * FROM tags WHERE name = ? COLLATE NOCASE",
            (normalized,)).fetchone()
        if row:
            return dict(row)
        cur = self.conn.execute(
            "INSERT INTO tags (name) VALUES (?)", (normalized,))
        self.conn.commit()
        return {"id": cur.lastrowid, "name": normalized}

    def list_tags(self):
        rows = self.conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def suggest_tags(self, prefix, limit=10):
        """標籤自動完成（spec.md FR-006）：依名稱包含比對（不只前綴，
        方便打中間字也能找到既有標籤），大小寫不敏感。"""
        rows = self.conn.execute(
            "SELECT * FROM tags WHERE name LIKE ? COLLATE NOCASE"
            " ORDER BY name LIMIT ?",
            ("%%%s%%" % prefix, limit)).fetchall()
        return [dict(r) for r in rows]

    def set_photo_tags(self, photo_id, tag_names):
        """把一張照片的標籤**取代**成 `tag_names`（PATCH 單張照片的
        語意：送什麼就是什麼，不是疊加）。空清單＝清空該照片全部標籤。
        批次操作的疊加語意見 `add_tags_to_photo()`。"""
        if self.get_photo(photo_id) is None:
            return None
        self.conn.execute("DELETE FROM photo_tags WHERE photo_id=?", (photo_id,))
        for name in tag_names or []:
            tag = self.get_or_create_tag(name)
            self.conn.execute(
                "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id)"
                " VALUES (?, ?)", (photo_id, tag["id"]))
        self.conn.commit()
        return self.get_photo(photo_id)

    def add_tags_to_photo(self, photo_id, tag_names):
        """把 `tag_names` **疊加**到一張照片既有標籤上（批次操作用，見
        `contracts/photos-api.md` `POST /api/photos/photos/batch`
        的 `add_tags` 語意——不清空既有標籤）。"""
        if self.get_photo(photo_id) is None:
            return None
        for name in tag_names or []:
            tag = self.get_or_create_tag(name)
            self.conn.execute(
                "INSERT OR IGNORE INTO photo_tags (photo_id, tag_id)"
                " VALUES (?, ?)", (photo_id, tag["id"]))
        self.conn.commit()
        return self.get_photo(photo_id)

    def get_photo_tags(self, photo_id):
        rows = self.conn.execute(
            "SELECT t.* FROM tags t"
            " JOIN photo_tags pt ON pt.tag_id = t.id"
            " WHERE pt.photo_id = ? ORDER BY t.name",
            (photo_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_photo_albums(self, photo_id):
        rows = self.conn.execute(
            "SELECT a.* FROM albums a"
            " JOIN photo_albums pa ON pa.album_id = a.id"
            " WHERE pa.photo_id = ? ORDER BY a.title",
            (photo_id,)).fetchall()
        return [dict(r) for r in rows]
