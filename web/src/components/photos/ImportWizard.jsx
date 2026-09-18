import { useState } from 'react'
import { apiPost } from '../../api/client.js'
import { UploadIcon } from '../icons.jsx'

/* 相簿匯入流程（User Story 1，T022）：三步驟——選路徑與儲存位置→
   去重預覽→背景匯入進度。互動細節比照已驗證的流程圖/畫面 Demo
   （https://claude.ai/code/artifact/57660844-0f08-419e-84e7-cec1aba4d1ef），
   對應後端 app/routers/photos.py 的 /api/photos/import/* 三個端點。
   輪詢間隔固定 800ms，MVP 不做退避/取消，匯入批次小（個人相片庫規模）
   實測下很快就會完成（見 poc/kb-mcp/tests/test_photo_importer.py）。 */
export default function ImportWizard({ onDone, onCancel }) {
  const [step, setStep] = useState(1)
  const [sourcePath, setSourcePath] = useState('')
  const [storageLocation, setStorageLocation] = useState('internal')
  const [destPath, setDestPath] = useState('')
  const [scanResult, setScanResult] = useState(null)
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

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
