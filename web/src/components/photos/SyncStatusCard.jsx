import { useState } from 'react'
import { apiPost } from '../../api/client.js'

/* 標籤/評分中繼資料同步狀態卡（User Story 3，T040）：已同步/待同步/
   失敗三種狀態＋手動重新同步按鈕，互動比照已驗證的流程圖/畫面 Demo。
   `pending` 涵蓋兩種情境（剛編輯完還在背景處理中、或原始檔所在硬碟
   離線），文案統一顯示「待同步」，不強行區分——使用者體感上都是
   「還沒寫進檔案」，區分反而增加認知負擔；真正的失敗原因在 `failed`
   狀態時透過 `error` 顯示。 */
export default function SyncStatusCard({ photoId, status, error, onSynced }) {
  const [busy, setBusy] = useState(false)

  async function handleResync() {
    setBusy(true)
    try {
      await apiPost(`/api/photos/photos/${photoId}/resync`, undefined)
      onSynced?.()
    } finally {
      setBusy(false)
    }
  }

  const labels = {
    synced: ['已同步到檔案', 'synced'],
    pending: ['待同步', 'pending'],
    failed: ['同步失敗', 'failed'],
  }
  const [label, cls] = labels[status] || labels.pending

  return (
    <div className="info-card" style={{ border: '1px solid var(--rule)', borderRadius: 10,
      padding: '.8rem .9rem', marginTop: '.8rem' }}>
      <div style={{ fontSize: '.8rem', fontWeight: 700, color: 'var(--ink-dim)', marginBottom: '.5rem' }}>
        標籤／評分同步到檔案（XMP/IPTC）
      </div>
      <span style={{
        fontWeight: 700, fontSize: '.85rem',
        color: cls === 'synced' ? 'var(--green)' : cls === 'failed' ? 'var(--red)' : 'var(--amber)',
      }}>
        {label}
      </span>
      {status === 'failed' && error && (
        <div className="offline-note" style={{ marginTop: '.5rem' }}>{error}</div>
      )}
      {status !== 'synced' && (
        <div style={{ marginTop: '.6rem' }}>
          <button type="button" className="btn-muted" disabled={busy} onClick={handleResync}>
            {busy ? '同步中…' : '重新同步'}
          </button>
        </div>
      )}
    </div>
  )
}
