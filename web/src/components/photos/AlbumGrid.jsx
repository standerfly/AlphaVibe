import { useState } from 'react'
import { PhotosIcon } from '../icons.jsx'

/* 相簿列表（User Story 1，T023）：卡片式列出所有相簿＋新增相簿的
   inline 表單，互動比照已驗證的流程圖/畫面 Demo。封面縮圖 MVP 階段
   先用純色佔位（`albums.cover_photo_id` 目前沒有對應的縮圖 URL 端點），
   之後要顯示真正封面照時在這裡換成 <img src={...}/> 即可，其餘結構
   不用動。*/
export default function AlbumGrid({ albums, onOpenAlbum, onCreateAlbum }) {
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')

  async function submitCreate() {
    if (!title.trim()) return
    await onCreateAlbum(title.trim())
    setTitle('')
    setCreating(false)
  }

  return (
    <div className="album-grid">
      {albums.map((album) => (
        <button key={album.id} className="album-card" onClick={() => onOpenAlbum(album.id)}>
          <div className="album-card__cover">
            <PhotosIcon width={28} height={28} />
          </div>
          <div className="album-card__body">
            <div className="album-card__title">{album.title}</div>
            <div className="album-card__meta">{album.photo_count} 張</div>
          </div>
        </button>
      ))}

      {!creating && (
        <button type="button" className="add-album-card" onClick={() => setCreating(true)}>
          <span style={{ fontSize: '1.4rem' }}>＋</span>
          <span>新增相簿</span>
        </button>
      )}
      {creating && (
        <div className="album-card" style={{ padding: '.8rem', cursor: 'default' }}>
          <input
            type="text" autoFocus value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="相簿標題"
            style={{ width: '100%', marginBottom: '.5rem', font: 'inherit',
              padding: '.4rem .55rem', borderRadius: 6, border: '1px solid var(--rule)' }}
          />
          <div style={{ display: 'flex', gap: '.4rem' }}>
            <button type="button" className="btn" style={{ flex: 1 }} onClick={submitCreate}>建立</button>
            <button type="button" className="btn-muted" style={{ flex: 1 }}
              onClick={() => { setCreating(false); setTitle('') }}>取消</button>
          </div>
        </div>
      )}
    </div>
  )
}
