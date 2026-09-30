import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPatch, apiPost } from '../../api/client.js'
import { ChevronLeftIcon } from '../icons.jsx'
import PhotoThumbGrid from './PhotoThumbGrid.jsx'

/* 全域搜尋（User Story 2，T031）：跨所有相簿，camera/lens 結構化下拉
   ＋標籤多選組合查詢，互動比照已驗證的流程圖/畫面 Demo。搜尋一律讀
   資料庫（GET /api/photos/search），不受外接硬碟是否掛載影響（見
   photo_store.py::search_photos() 的設計說明）。
   2026-09-30：補上批次整理（多選＋工具列，跟相簿頁 AlbumDetail.jsx
   同一套模式，用共用元件 PhotoThumbGrid 避免兩邊各自維護一份、日後
   改一邊忘了同步另一邊）——這是 PO 明確指出的落差：之前只有相簿頁
   能批次貼標籤/評分，搜尋結果頁完全沒有。 */
export default function SearchPanel({ onBack, onOpenPhoto }) {
  const [facets, setFacets] = useState({ camera_models: [], lenses: [] })
  const [allTags, setAllTags] = useState([])
  const [camera, setCamera] = useState('')
  const [lens, setLens] = useState('')
  const [selectedTags, setSelectedTags] = useState(new Set())
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [tagInput, setTagInput] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    apiGet('/api/photos/search/facets').then(setFacets).catch((err) => setError(err.message))
    apiGet('/api/photos/tags').then((d) => setAllTags(d.tags)).catch((err) => setError(err.message))
  }, [])

  const runSearch = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (camera) params.set('camera_model', camera)
      if (lens) params.set('lens', lens)
      for (const t of selectedTags) params.append('tags', t)
      const data = await apiGet(`/api/photos/search?${params.toString()}`)
      setResults(data.photos)
      setSelected(new Set())
    } catch (err) {
      setError(err.message)
    }
  }, [camera, lens, selectedTags])

  useEffect(() => { runSearch() }, [runSearch])

  function toggleTag(tag) {
    setSelectedTags((prev) => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

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
      await runSearch()  // runSearch 本身會重置 selected，見上方
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
    setResults((prev) => prev.map((p) => (p.id === photoId ? { ...p, rating } : p)))
    try {
      await apiPatch(`/api/photos/photos/${photoId}`, { rating })
    } catch (err) {
      setError(err.message)
      runSearch()
    }
  }

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}
        style={{ display: 'inline-flex', alignItems: 'center', gap: '.3rem', background: 'none',
          border: 'none', color: 'var(--ink-dim)', cursor: 'pointer', marginBottom: '.6rem', padding: 0 }}>
        <ChevronLeftIcon width={16} height={16} /> 返回相簿
      </button>
      <div className="page-title"><h1>搜尋照片（跨所有相簿）</h1></div>
      {error && <div className="offline-note" style={{ marginBottom: '.8rem' }}>{error}</div>}

      <div className="photo-toolbar" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '.6rem' }}>
        <div style={{ display: 'flex', gap: '.9rem', flexWrap: 'wrap' }}>
          <label>
            相機型號{' '}
            <select value={camera} onChange={(e) => setCamera(e.target.value)}>
              <option value="">全部</option>
              {facets.camera_models.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            鏡頭{' '}
            <select value={lens} onChange={(e) => setLens(e.target.value)}>
              <option value="">全部</option>
              {facets.lenses.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
        </div>
        {allTags.length > 0 && (
          <div style={{ display: 'flex', gap: '.4rem', flexWrap: 'wrap' }}>
            {allTags.map((tag) => (
              <button
                key={tag} type="button"
                className={`filter-tab${selectedTags.has(tag) ? ' active' : ''}`}
                onClick={() => toggleTag(tag)}
              >
                #{tag}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="meta" style={{ margin: '.8rem 0' }}>
        {results === null ? '搜尋中…' : `符合條件：${results.length} 張`}
      </div>

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

      {results && results.length > 0 && (
        <PhotoThumbGrid
          photos={results} selected={selected}
          onToggleSelect={toggleSelect} onOpenDetail={onOpenPhoto}
          onQuickRate={handleQuickRate}
        />
      )}
    </div>
  )
}
