import { useState } from 'react'
import { apiPost } from '../../api/client.js'
import { UploadIcon } from '../icons.jsx'

/* 相簿匯入流程（User Story 1，T022）：三步驟——選路徑與儲存位置→
   去重預覽→背景匯入進度。互動細節比照已驗證的流程圖/畫面 Demo
   （https://claude.ai/code/artifact/57660844-0f08-419e-84e7-cec1aba4d1ef），
   對應後端 app/routers/photos.py 的 /api/photos/import/* 端點。
   輪詢間隔固定 800ms，MVP 不做退避/取消，匯入批次小（個人相片庫規模）
   實測下很快就會完成（見 poc/kb-mcp/tests/test_photo_importer.py）。
   2026-09-25：新增「原地索引」模式（不複製）＋搬家偵測＋人工確認
   清單（見 photo_importer.py scan_folder() docstring 的完整設計說明，
   /api/photos/import/resolve-match 對應的處理函式）。
   2026-09-27：新增「依子資料夾自動建立相簿」（見 app/routers/photos.py
   `_group_by_top_level_folder()` docstring）——沿用來源端已經分好的
   資料匣結構，省去進 STND 後重新手動分類一次；沒有子資料夾歸屬的
   照片仍走原本的手動「加入相簿」流程（`unassignedIds`）。 */
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
  // 2026-09-25：「原地索引」新模式——不複製，直接索引既有資料夾，
  // 搬移偵測與原始檔標籤寫回見 photo_importer.py scan_folder()/
  // heal_moved_paths() docstring。既有相片庫常見巢狀資料夾（依相機/
  // 年份分類），所以一起加了「包含子資料夾」選項，三種儲存模式共用。
  const [recursive, setRecursive] = useState(false)
  // 2026-09-27：「依子資料夾自動建立相簿」——沿用使用者已經在來源端
  // （例如 MacBook Air）分好的資料匣結構，省去進 STND 後重新手動分類
  // 一次。只在 recursive 打勾時才有意義（沒有子資料夾資訊可以分組），
  // 見 app/routers/photos.py `_group_by_top_level_folder()` docstring。
  const [autoAlbum, setAutoAlbum] = useState(true)
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
      const body = {
        source_path: sourcePath.trim(), storage_location: storageLocation,
        recursive, auto_album: recursive && autoAlbum,
      }
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

  async function handleResolveMatch(match) {
    setBusy(true)
    setError(null)
    try {
      const result = await apiPost('/api/photos/import/resolve-match', {
        scan_token: scanResult.scan_token,
        photo_id: match.photo_id,
        new_path: match.new_path,
      })
      setScanResult((prev) => ({
        ...prev,
        new_count: result.new_count,
        possible_matches: result.possible_matches,
      }))
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
        photo_ids: unassignedIds, add_album_id: albumId,
      })
      setAssignDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // job.unassigned_photo_ids 一律存在：auto_album 沒開時等於全部
  // imported_photo_ids（維持舊行為，整批手動選相簿）；auto_album 開了
  // 就只剩下沒有子資料夾歸屬的那些（見 app/routers/photos.py
  // `_run_import_job()` docstring）。
  const unassignedIds = job?.unassigned_photo_ids ?? []

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
            <div className="radio-row" style={{ display: 'flex', gap: '1.2rem', margin: '.8rem 0', flexWrap: 'wrap' }}>
              <label>
                <input type="radio" checked={storageLocation === 'internal'}
                  onChange={() => setStorageLocation('internal')} /> 存內接硬碟
              </label>
              <label>
                <input type="radio" checked={storageLocation === 'external'}
                  onChange={() => setStorageLocation('external')} /> 存外接硬碟
              </label>
              <label>
                <input type="radio" checked={storageLocation === 'reference'}
                  onChange={() => setStorageLocation('reference')} /> 原地索引，不複製
              </label>
            </div>
            {storageLocation === 'external' && (
              <input
                type="text" value={destPath}
                onChange={(e) => setDestPath(e.target.value)}
                placeholder="外接硬碟上的存放路徑，例如 /Volumes/PhotoArchive/2026"
              />
            )}
            {storageLocation === 'reference' && (
              <div className="meta" style={{ marginBottom: '.6rem' }}>
                不複製檔案，直接在原資料夾建立索引，保留你原本的整理方式。
                加標籤會直接寫進照片檔案本身；之後在 Finder 把照片搬到新資料夾，
                重新掃描同一個來源路徑會自動偵測搬家並更新路徑——但如果搬移前已經
                加過標籤，檔案內容會改變，搬移偵測會失效（標籤本身仍留在檔案裡不會
                遺失，只是這裡不會自動關聯到舊紀錄，需要手動刪除變成離線的舊紀錄）。
              </div>
            )}
            <label style={{ display: 'flex', alignItems: 'center', gap: '.4rem', marginTop: '.4rem' }}>
              <input type="checkbox" checked={recursive}
                onChange={(e) => setRecursive(e.target.checked)} />
              包含子資料夾
            </label>
            {recursive && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '.4rem', marginTop: '.4rem' }}>
                <input type="checkbox" checked={autoAlbum}
                  onChange={(e) => setAutoAlbum(e.target.checked)} />
                依子資料夾自動建立相簿（沿用來源端已經分好的資料匣分類）
              </label>
            )}
          </>
        )}

        {step === 2 && scanResult && (
          <>
            <table className="itinerary-table" style={{ width: '100%', fontSize: '.85rem' }}>
              <tbody>
                <tr><td>掃描到的檔案</td><td style={{ textAlign: 'right' }}>{scanResult.total}</td></tr>
                <tr><td>新照片（將匯入）</td>
                  <td style={{ textAlign: 'right', color: 'var(--green)' }}>{scanResult.new_count}</td></tr>
                {scanResult.moved_count > 0 && (
                  <tr><td>偵測到搬家（將更新路徑）</td>
                    <td style={{ textAlign: 'right', color: 'var(--green)' }}>{scanResult.moved_count}</td></tr>
                )}
                {scanResult.healed_in_place_count > 0 && (
                  <tr><td>原地內容有更新（將自動修正）</td>
                    <td style={{ textAlign: 'right', color: 'var(--green)' }}>{scanResult.healed_in_place_count}</td></tr>
                )}
                <tr><td>重複檔案（將跳過）</td>
                  <td style={{ textAlign: 'right', color: 'var(--ink-dim)' }}>{scanResult.duplicate_count}</td></tr>
                {scanResult.unreadable.length > 0 && (
                  <tr><td>無法讀取</td>
                    <td style={{ textAlign: 'right', color: 'var(--red)' }}>{scanResult.unreadable.length}</td></tr>
                )}
              </tbody>
            </table>

            {scanResult.folder_albums_preview && (
              <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rule)', paddingTop: '.9rem' }}>
                <div className="meta" style={{ marginBottom: '.4rem' }}>將依資料匣自動建立/加入相簿：</div>
                {scanResult.folder_albums_preview.albums.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '.85rem' }}>
                    {scanResult.folder_albums_preview.albums.map((a) => (
                      <li key={a.title}>{a.title}（{a.count} 張）</li>
                    ))}
                  </ul>
                ) : (
                  <div className="meta" style={{ fontSize: '.8rem' }}>沒有偵測到任何子資料夾</div>
                )}
                {scanResult.folder_albums_preview.unassigned_count > 0 && (
                  <div className="meta" style={{ fontSize: '.8rem', marginTop: '.3rem' }}>
                    另有 {scanResult.folder_albums_preview.unassigned_count} 張沒有子資料夾歸屬，
                    匯入後可手動指定相簿
                  </div>
                )}
              </div>
            )}

            {scanResult.possible_matches?.length > 0 && (
              <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rule)', paddingTop: '.9rem' }}>
                <div className="meta" style={{ marginBottom: '.4rem' }}>
                  以下檔名跟已經離線的舊照片相同，可能是搬家前已經打過標籤、
                  內容因此改變了的同一張照片——確認的話會更新舊紀錄的位置，
                  不會另外匯入一份；不確定就先不用理它，直接匯入成新照片。
                </div>
                {scanResult.possible_matches.map((match) => (
                  <div key={`${match.photo_id}-${match.new_path}`}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '.6rem',
                      padding: '.4rem 0', borderBottom: '1px dashed var(--rule)',
                    }}>
                    <div style={{ flex: 1, fontSize: '.8rem' }}>
                      <div>{match.filename}</div>
                      <div className="meta" style={{ fontSize: '.75rem' }}>
                        舊：{match.old_path}
                      </div>
                      <div className="meta" style={{ fontSize: '.75rem' }}>
                        新：{match.new_path}
                      </div>
                    </div>
                    <button type="button" className="btn-muted" disabled={busy}
                      onClick={() => handleResolveMatch(match)}>
                      確認是同一張
                    </button>
                  </div>
                ))}
              </div>
            )}
          </>
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
                {job.healed_count > 0 && `，更新了 ${job.healed_count} 張搬家路徑`}
                {job.healed_in_place_count > 0 && `，修正了 ${job.healed_in_place_count} 張原地內容`}
                {job.failed?.length > 0 && `，${job.failed.length} 張失敗`}
              </div>
            )}
            {job?.status === 'failed' && <div className="offline-note">{job.error}</div>}

            {job?.status === 'completed' && job.auto_albums?.length > 0 && (
              <div className="meta" style={{ marginTop: '.5rem' }}>
                已自動建立/加入相簿：
                {job.auto_albums.map((a) => `${a.title}（${a.count}張）`).join('、')}
              </div>
            )}

            {job?.status === 'completed' && unassignedIds.length > 0 && !assignDone && (
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
