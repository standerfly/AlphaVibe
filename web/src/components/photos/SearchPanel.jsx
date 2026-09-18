import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../../api/client.js'
import { ChevronLeftIcon, PhotosIcon } from '../icons.jsx'

/* 全域搜尋（User Story 2，T031）：跨所有相簿，camera/lens 結構化下拉
   ＋標籤多選組合查詢，互動比照已驗證的流程圖/畫面 Demo。搜尋一律讀
   資料庫（GET /api/photos/search），不受外接硬碟是否掛載影響（見
   photo_store.py::search_photos() 的設計說明）。 */
export default function SearchPanel({ onBack }) {
  const [facets, setFacets] = useState({ camera_models: [], lenses: [] })
  const [allTags, setAllTags] = useState([])
  const [camera, setCamera] = useState('')
  const [lens, setLens] = useState('')
  const [selectedTags, setSelectedTags] = useState(new Set())
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)

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

      {results && results.length > 0 && (
        <div className="thumb-grid">
          {results.map((photo) => (
            <div key={photo.id} className="thumb">
              <img src={`/api/photos/thumbnail/${photo.id}`} alt=""
                onError={(e) => { e.target.style.display = 'none' }} />
              <PhotosIcon width={22} height={22}
                style={{ position: 'absolute', top: '50%', left: '50%',
                  transform: 'translate(-50%,-50%)', opacity: .35 }} />
              {photo.rating > 0 && <span className="thumb__rating">★{photo.rating}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
