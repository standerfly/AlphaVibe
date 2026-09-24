import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPatch } from '../../api/client.js'
import { ChevronLeftIcon } from '../icons.jsx'
import SyncStatusCard from './SyncStatusCard.jsx'

/* 單張照片詳情（User Story 3，T041）：大圖、EXIF、所屬相簿、標籤、
   可調整評分，並整合 SyncStatusCard 顯示中繼資料同步狀態。這是 User
   Story 1 刻意沒做的畫面（當時標記/整理都靠 AlbumDetail 的批次工具列
   完成），到這個 Story 才補上——因為同步狀態本質上是「單張照片」的
   屬性，批次工具列不適合呈現。*/
export default function PhotoDetail({ photoId, onBack }) {
  const [photo, setPhoto] = useState(null)
  const [tagInput, setTagInput] = useState('')
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await apiGet(`/api/photos/photos/${photoId}`)
      setPhoto(data)
      setTagInput(data.tags.join(', '))
    } catch (err) {
      setError(err.message)
    }
  }, [photoId])

  useEffect(() => { load() }, [load])

  // 標籤/評分編輯後，背景任務要過一小段時間才會把中繼資料寫進檔案；
  // metadata_sync_status 在那之前會是 'pending'。輪詢直到它變成
  // 'synced'／'failed'，不然畫面會停在「待同步」不會自己更新（這是
  // 用 Playwright 實際點過才發現的——PATCH 回應本來就只是當下那一刻
  // 的快照，背景任務完成後不會主動推回前端）。
  useEffect(() => {
    if (photo?.metadata_sync_status !== 'pending') return undefined
    const timer = setTimeout(load, 1000)
    return () => clearTimeout(timer)
  }, [photo?.metadata_sync_status, load])

  async function setRating(n) {
    try {
      const updated = await apiPatch(`/api/photos/photos/${photoId}`, { rating: n })
      setPhoto(updated)
    } catch (err) {
      setError(err.message)
    }
  }

  async function saveTags() {
    const tags = tagInput.split(/[,，]/).map((t) => t.trim()).filter(Boolean)
    try {
      const updated = await apiPatch(`/api/photos/photos/${photoId}`, { tags })
      setPhoto(updated)
    } catch (err) {
      setError(err.message)
    }
  }

  if (error) return <div className="offline-note">{error}</div>
  if (!photo) return <div className="empty">載入中…</div>

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}
        style={{ display: 'inline-flex', alignItems: 'center', gap: '.3rem', background: 'none',
          border: 'none', color: 'var(--ink-dim)', cursor: 'pointer', marginBottom: '.6rem', padding: 0 }}>
        <ChevronLeftIcon width={16} height={16} /> 返回
      </button>

      <div className="photo-detail">
        <div className="photo-detail__hero">
          <img src={`/api/photos/thumbnail/${photo.id}`} alt=""
            onError={(e) => { e.target.replaceWith(document.createElement('div')) }} />
        </div>
        <div>
          <div className="info-card">
            <div className="info-card__head">評分與標籤</div>
            <div className="rating-stars">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" className={n <= photo.rating ? 'is-on' : ''}
                  onClick={() => setRating(n)}>★</button>
              ))}
            </div>
            <div style={{ margin: '.6rem 0' }}>
              {photo.tags.map((t) => <span key={t} className="tag-pill">#{t}</span>)}
            </div>
            <div style={{ display: 'flex', gap: '.4rem' }}>
              <input type="text" value={tagInput} onChange={(e) => setTagInput(e.target.value)}
                placeholder="標籤，逗號分隔多個" style={{ flex: 1 }} />
              <button type="button" className="btn" onClick={saveTags}>更新標籤</button>
            </div>
            {photo.albums.length > 0 && (
              <div style={{ marginTop: '.6rem' }}>
                {photo.albums.map((a) => <span key={a.id} className="album-pill">{a.title}</span>)}
              </div>
            )}
          </div>

          <div className="info-card">
            <div className="info-card__head">EXIF</div>
            <dl className="exif-grid">
              <dt>相機</dt><dd>{photo.camera_model || '—'}</dd>
              <dt>鏡頭</dt><dd>{photo.lens || '—'}</dd>
              <dt>拍攝日期</dt><dd>{photo.photo_date || '—'}</dd>
              <dt>儲存位置</dt><dd>{photo.storage_location === 'external' ? '外接' : '內接'}</dd>
            </dl>
          </div>

          <SyncStatusCard
            photoId={photo.id}
            status={photo.metadata_sync_status}
            error={photo.metadata_sync_error}
            onSynced={load}
          />
        </div>
      </div>
    </div>
  )
}
