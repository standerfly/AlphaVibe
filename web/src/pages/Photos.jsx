import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client.js'
import { SearchIcon, UploadIcon } from '../components/icons.jsx'
import AlbumGrid from '../components/photos/AlbumGrid.jsx'
import AlbumDetail from '../components/photos/AlbumDetail.jsx'
import ImportWizard from '../components/photos/ImportWizard.jsx'
import SearchPanel from '../components/photos/SearchPanel.jsx'

/* 相簿分頁（specs/004-photos-albums-search）：相簿列表／相簿詳情／
   匯入／全域搜尋四個子畫面的切換殼，取代原本 MVP 空白佔位頁（見
   CLAUDE.md「STND 分頁與程式碼位置」表，FR-062 已修訂）。User Story 1
   （匯入/整理/瀏覽）與 User Story 2（全域搜尋）已完成；照片詳情的
   中繼資料同步狀態卡（User Story 3）留待該 Story 完成後再接上。 */
export default function Photos() {
  const [view, setView] = useState('grid') // 'grid' | 'album' | 'import' | 'search'
  const [albums, setAlbums] = useState(null)
  const [activeAlbumId, setActiveAlbumId] = useState(null)
  const [error, setError] = useState(null)

  const loadAlbums = useCallback(async () => {
    try {
      const data = await apiGet('/api/photos/albums')
      setAlbums(data.albums)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { loadAlbums() }, [loadAlbums])

  async function handleCreateAlbum(title) {
    try {
      await apiPost('/api/photos/albums', { title })
      await loadAlbums()
    } catch (err) {
      setError(err.message)
    }
  }

  if (view === 'import') {
    return (
      <ImportWizard
        albums={albums}
        onCancel={() => setView('grid')}
        onDone={() => { setView('grid'); loadAlbums() }}
      />
    )
  }

  if (view === 'search') {
    return <SearchPanel onBack={() => setView('grid')} />
  }

  if (view === 'album' && activeAlbumId) {
    return <AlbumDetail albumId={activeAlbumId} onBack={() => setView('grid')} />
  }

  return (
    <div>
      <div className="page-title" style={{ display: 'flex', alignItems: 'center',
        justifyContent: 'space-between' }}>
        <h1>相簿</h1>
        <div style={{ display: 'flex', gap: '.5rem' }}>
          <button type="button" className="btn" onClick={() => setView('search')}>
            <SearchIcon width={16} height={16} style={{ verticalAlign: '-3px', marginRight: '.35rem' }} />
            搜尋照片
          </button>
          <button type="button" className="btn-muted" onClick={() => setView('import')}>
            <UploadIcon width={16} height={16} style={{ verticalAlign: '-3px', marginRight: '.35rem' }} />
            匯入照片
          </button>
        </div>
      </div>
      {error && <div className="offline-note" style={{ marginBottom: '.8rem' }}>{error}</div>}
      {albums === null ? (
        <div className="empty">載入中…</div>
      ) : (
        <AlbumGrid
          albums={albums}
          onOpenAlbum={(id) => { setActiveAlbumId(id); setView('album') }}
          onCreateAlbum={handleCreateAlbum}
        />
      )}
    </div>
  )
}
