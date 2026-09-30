import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPatch, apiPost } from '../../api/client.js'
import { ChevronLeftIcon } from '../icons.jsx'
import PhotoThumbGrid from './PhotoThumbGrid.jsx'

/* 相簿內縮圖牆＋批次整理（User Story 1，T023）：多選照片後可一次加
   標籤／設評分，對應 contracts/photos-api.md 的
   POST /api/photos/photos/batch。
   2026-09-30：縮圖格改用共用元件 PhotoThumbGrid（見該檔案 docstring）
   ——每張縮圖直接可點星等單張評分（不用先多選），呼應 PO「像 contact
   sheet 選片」的速度需求；多選＋批次工具列（下面 photo-toolbar）保留
   給「一次幫一批加同一組標籤」這種场景。 */
export default function AlbumDetail({ albumId, onBack, onOpenPhoto }) {
  const [photos, setPhotos] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [tagInput, setTagInput] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await apiGet(`/api/photos/albums/${albumId}/photos`)
      setPhotos(data.photos)
    } catch (err) {
      setError(err.message)
    }
  }, [albumId])

  useEffect(() => { load() }, [load])

  function toggleSelect(photoId) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(photoId)) next.delete(photoId)
      else next.add(photoId)
      return next
    })
  }

  async function applyBatch(patch) {
    if (selected.size === 0) return
    setBusy(true)
    try {
      await apiPost('/api/photos/photos/batch', { photo_ids: [...selected], ...patch })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function addTags() {
    if (!tagInput.trim()) return
    const tags = tagInput.split(/[,，]/).map((t) => t.trim()).filter(Boolean)
    await applyBatch({ add_tags: tags })
    setTagInput('')
  }

  async function handleQuickRate(photoId, rating) {
    // 樂觀更新：先改本地畫面，不等 API 回應才刷新，contact-sheet 選片
    // 要的是「點了立刻看到變化」的速度感。
    setPhotos((prev) => prev.map((p) => (p.id === photoId ? { ...p, rating } : p)))
    try {
      await apiPatch(`/api/photos/photos/${photoId}`, { rating })
    } catch (err) {
      setError(err.message)
      load()
    }
  }

  if (error) return <div className="offline-note">{error}</div>
  if (!photos) return <div className="empty">載入中…</div>

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}
        style={{ display: 'inline-flex', alignItems: 'center', gap: '.3rem', background: 'none',
          border: 'none', color: 'var(--ink-dim)', cursor: 'pointer', marginBottom: '.6rem', padding: 0 }}>
        <ChevronLeftIcon width={16} height={16} /> 返回相簿列表
      </button>
      <div className="page-title"><h1>相簿</h1></div>

      {selected.size > 0 && (
        <div className="photo-toolbar">
          <span className="meta">已選 {selected.size} 張</span>
          <input type="text" value={tagInput} onChange={(e) => setTagInput(e.target.value)}
            placeholder="加標籤，逗號分隔多個" />
          <button type="button" className="btn" disabled={busy} onClick={addTags}>加標籤</button>
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" className="btn-muted" disabled={busy}
              onClick={() => applyBatch({ set_rating: n })}>{n}★</button>
          ))}
          <button type="button" className="btn-muted" onClick={() => setSelected(new Set())}>取消選取</button>
        </div>
      )}

      {photos.length === 0 ? (
        <div className="empty">這個相簿還沒有照片。</div>
      ) : (
        <PhotoThumbGrid
          photos={photos} selected={selected}
          onToggleSelect={toggleSelect} onOpenDetail={onOpenPhoto}
          onQuickRate={handleQuickRate}
        />
      )}
    </div>
  )
}
