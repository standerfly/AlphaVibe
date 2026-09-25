import { useState } from 'react'
import { apiPost } from '../../api/client.js'
import { UploadIcon } from '../icons.jsx'

/* 相簿匯入流程（User Story 1，T022）：三步驟——選路徑與儲存位置→
   去重預覽→背景匯入進度。互動細節比照已驗證的流程圖/畫面 Demo
   （https://claude.ai/code/artifact/57660844-0f08-419e-84e7-cec1aba4d1ef），
   對應後端 app/routers/photos.py 的 /api/photos/import/* 三個端點。
   輪詢間隔固定 800ms，MVP 不做退避/取消，匯入批次小（個人相片庫規模）
   實測下很快就會完成（見 poc/kb-mcp/tests/test_photo_importer.py）。 */
export default function ImportWizard({ albums, onDone, onCancel }) {
  const [step, setStep] = useState(1)
  const [sourcePath, setSourcePath] = useState('')
  const [storageLocation, setStorageLocation] = useState('internal')
  // 2026-09-25：PO 目前固定用這顆外接硬碟存照片，預先帶入路徑省得每次
  // 手動打——仍是可編輯的一般 input，硬碟改名/換硬碟時直接在畫面上改，
  // 不用改程式碼。後端 scan/commit 兩處都會驗證這個路徑當下真的有掛載
  // （見 photo_importer.py::external_volume_mounted()），沒接的話會擋
  // 下來提示，不會悄悄寫進內接硬碟。
  const [destPath, setDestPath] = useState('/Volumes/macmini_ext8G/')
  const [scanResult, setScanResult] = useState(null)
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [assignChoice, setAssignChoice] = useState('new')
  const [existingAlbumId, setExistingAlbumId] = useState(albums?.[0]?.id ?? '')
  const [newAlbumTitle, setNewAlbumTitle] = useState('')
  const [assignDone, setAssignDone] = useState(false)

  async function handleScan() {
    if (!sourcePath.trim()) {
      setError('請輸入來源資料夾路徑')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const body = { source_path: sourcePath.trim(), storage_location: storageLocation }
      if (storageLocation === 'external') body.dest_path = destPath.trim()
      const result = await apiPost('/api/photos/import/scan', body)
      setScanResult(result)
      setStep(2)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleCommit() {
    setBusy(true)
    setError(null)
    try {
      const { job_id } = await apiPost('/api/photos/import/commit', {
        scan_token: scanResult.scan_token,
      })
      setStep(3)
      pollJob(job_id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  function pollJob(jobId) {
    const tick = async () => {
      try {
        const res = await fetch(`/api/photos/import/jobs/${jobId}`)
        const data = await res.json()
        setJob(data)
        if (data.status === 'running') {
          setTimeout(tick, 800)
        } else {
          setBusy(false)
        }
      } catch (err) {
        setError(err.message)
        setBusy(false)
      }
    }
    setBusy(true)
    tick()
  }

  async function handleAssign() {
    setBusy(true)
    setError(null)
    try {
      let albumId = existingAlbumId
      if (assignChoice === 'new') {
        if (!newAlbumTitle.trim()) {
          setError('請輸入新相簿名稱')
          setBusy(false)
          return
        }
        const created = await apiPost('/api/photos/albums', { title: newAlbumTitle.trim() })
        albumId = created.id
      }
      await apiPost('/api/photos/photos/batch', {
        photo_ids: job.imported_photo_ids, add_album_id: albumId,
      })
      setAssignDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-title"><h1>匯入照片</h1></div>
      {error && <div className="offline-note" style={{ marginBottom: '.8rem' }}>{error}</div>}

      <div className="wizard-panel">
        {step === 1 && (
          <>
            <div className="photo-toolbar" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              <label className="meta">來源資料夾（本機絕對路徑）</label>
              <input
                type="text" value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
                placeholder="/Volumes/Photos/2026-11-import"
              />
            </div>
            <div className="radio-row" style={{ display: 'flex', gap: '1.2rem', margin: '.8rem 0' }}>
              <label>
                <input type="radio" checked={storageLocation === 'internal'}
                  onChange={() => setStorageLocation('internal')} /> 存內接硬碟
              </label>
              <label>
                <input type="radio" checked={storageLocation === 'external'}
                  onChange={() => setStorageLocation('external')} /> 存外接硬碟
              </label>
            </div>
            {storageLocation === 'external' && (
              <input
                type="text" value={destPath}
                onChange={(e) => setDestPath(e.target.value)}
                placeholder="外接硬碟上的存放路徑，例如 /Volumes/PhotoArchive/2026"
              />
            )}
          </>
        )}

        {step === 2 && scanResult && (
          <table className="itinerary-table" style={{ width: '100%', fontSize: '.85rem' }}>
            <tbody>
              <tr><td>掃描到的檔案</td><td style={{ textAlign: 'right' }}>{scanResult.total}</td></tr>
              <tr><td>新照片（將匯入）</td>
                <td style={{ textAlign: 'right', color: 'var(--green)' }}>{scanResult.new_count}</td></tr>
              <tr><td>重複檔案（將跳過）</td>
                <td style={{ textAlign: 'right', color: 'var(--ink-dim)' }}>{scanResult.duplicate_count}</td></tr>
              {scanResult.unreadable.length > 0 && (
                <tr><td>無法讀取</td>
                  <td style={{ textAlign: 'right', color: 'var(--red)' }}>{scanResult.unreadable.length}</td></tr>
              )}
            </tbody>
          </table>
        )}

        {step === 3 && (
          <div>
            <div className="meta">
              {job?.status === 'completed' ? '完成' : job?.status === 'failed' ? '失敗' : '匯入中…'}
            </div>
            <div className="wizard-progress-track">
              <div className="wizard-progress-fill"
                style={{ width: job?.status === 'running' ? '60%' : '100%' }} />
            </div>
            {job?.status === 'completed' && (
              <div className="meta">
                已匯入 {job.imported_count} 張
                {job.failed?.length > 0 && `，${job.failed.length} 張失敗`}
              </div>
            )}
            {job?.status === 'failed' && <div className="offline-note">{job.error}</div>}

            {job?.status === 'completed' && job.imported_count > 0 && !assignDone && (
              <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rule)', paddingTop: '.9rem' }}>
                <div className="meta" style={{ marginBottom: '.5rem' }}>加入哪個相簿？</div>
                <div style={{ display: 'flex', gap: '.6rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  <label>
                    <input type="radio" checked={assignChoice === 'new'}
                      onChange={() => setAssignChoice('new')} /> 新相簿
                  </label>
                  {newAlbumTitle !== null && assignChoice === 'new' && (
                    <input type="text" value={newAlbumTitle}
                      onChange={(e) => setNewAlbumTitle(e.target.value)}
                      placeholder="新相簿名稱" />
                  )}
                  {albums?.length > 0 && (
                    <>
                      <label>
                        <input type="radio" checked={assignChoice === 'existing'}
                          onChange={() => setAssignChoice('existing')} /> 既有相簿
                      </label>
                      {assignChoice === 'existing' && (
                        <select value={existingAlbumId}
                          onChange={(e) => setExistingAlbumId(Number(e.target.value))}>
                          {albums.map((a) => (
                            <option key={a.id} value={a.id}>{a.title}</option>
                          ))}
                        </select>
                      )}
                    </>
                  )}
                  <button type="button" className="btn" disabled={busy} onClick={handleAssign}>
                    加入相簿
                  </button>
                </div>
              </div>
            )}
            {assignDone && (
              <div className="toast" style={{ marginTop: '.8rem' }}>已加入相簿</div>
            )}
          </div>
        )}
      </div>

      <div className="wizard-actions">
        <button type="button" className="btn-muted" onClick={onCancel} disabled={busy && step === 3}>
          {step === 3 && job?.status !== 'running' ? '關閉' : '取消'}
        </button>
        {step === 1 && (
          <button type="button" className="btn" onClick={handleScan} disabled={busy}>
            <UploadIcon width={16} height={16} style={{ verticalAlign: '-3px', marginRight: '.35rem' }} />
            下一步
          </button>
        )}
        {step === 2 && (
          <button type="button" className="btn" onClick={handleCommit} disabled={busy}>確認匯入</button>
        )}
        {step === 3 && job?.status && job.status !== 'running' && (
          <button type="button" className="btn" onClick={onDone}>完成</button>
        )}
      </div>
    </div>
  )
}
