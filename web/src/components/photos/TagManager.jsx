import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet, apiPost } from '../../api/client.js'
import { ChevronLeftIcon } from '../icons.jsx'

/* 標籤管理：列出全部標籤與張數，改名／合併／刪除。
   改名到已存在的名稱＝合併。資料庫改完後，後端會在背景把受影響照片的
   檔案中繼資料（XMP/IPTC／RAW sidecar）重新寫回，與 Finder 端的
   photo_tool `tags rename|merge|delete` 對應。 */
export default function TagManager({ onBack }) {
  const [tags, setTags] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [editing, setEditing] = useState(null) // { name, value }
  const [newName, setNewName] = useState('')
  const [mergeInto, setMergeInto] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await apiGet('/api/photos/tags/stats')
      setTags(data.tags)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function run(fn, doneText) {
    setError(null)
    setNotice(null)
    try {
      const result = await fn()
      setNotice(typeof doneText === 'function' ? doneText(result) : doneText)
      setSelected(new Set())
      setEditing(null)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const create = () => newName.trim() && run(
    async () => { await apiPost('/api/photos/tags', { name: newName }); setNewName('') },
    '已新增標籤')

  const rename = () => editing && editing.value.trim() && run(
    () => apiPost('/api/photos/tags/rename', { old: editing.name, new: editing.value }),
    (r) => (r.merged ? `已合併，影響 ${r.affected} 張` : `已改名，影響 ${r.affected} 張`))

  const merge = () => run(
    () => apiPost('/api/photos/tags/merge', { sources: [...selected], into: mergeInto }),
    (r) => `已合併，影響 ${r.affected} 張`)

  function remove(tag) {
    const msg = `刪除「${tag.name}」？會從 ${tag.count} 張照片移除（照片檔案本身不會被刪除）。`
    if (!window.confirm(msg)) return
    run(() => apiDelete(`/api/photos/tags?name=${encodeURIComponent(tag.name)}`),
      (r) => `已刪除，影響 ${r.affected} 張`)
  }

  function toggle(name) {
    const next = new Set(selected)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setSelected(next)
  }

  return (
    <div>
      <button type="button" className="back-link" onClick={onBack}
        style={{ display: 'inline-flex', alignItems: 'center', gap: '.3rem', background: 'none',
          border: 'none', color: 'var(--ink-dim)', cursor: 'pointer', marginBottom: '.6rem', padding: 0 }}>
        <ChevronLeftIcon width={16} height={16} /> 返回
      </button>
      <div className="page-title"><h1>標籤管理</h1></div>
      {error && <div className="offline-note" style={{ marginBottom: '.8rem' }}>{error}</div>}
      {notice && <div className="info-card" style={{ marginBottom: '.8rem' }}>{notice}</div>}

      <div className="info-card" style={{ marginBottom: '.9rem' }}>
        <div className="info-card__head">新增標籤</div>
        <div style={{ display: 'flex', gap: '.4rem' }}>
          <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)}
            placeholder="標籤名稱" style={{ flex: 1 }}
            onKeyDown={(e) => { if (e.key === 'Enter') create() }} />
          <button type="button" className="btn" onClick={create}>新增</button>
        </div>
      </div>

      {selected.size >= 2 && (
        <div className="info-card" style={{ marginBottom: '.9rem' }}>
          <div className="info-card__head">合併已勾選的 {selected.size} 個標籤</div>
          <div style={{ display: 'flex', gap: '.4rem' }}>
            <input type="text" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}
              placeholder="合併後的名稱（可用其中一個）" list="merge-targets" style={{ flex: 1 }} />
            <datalist id="merge-targets">
              {[...selected].map((n) => <option key={n} value={n} />)}
            </datalist>
            <button type="button" className="btn" disabled={!mergeInto.trim()} onClick={merge}>合併</button>
          </div>
        </div>
      )}

      {tags === null ? (
        <div className="empty">載入中…</div>
      ) : tags.length === 0 ? (
        <div className="empty">還沒有標籤</div>
      ) : (
        <div className="info-card">
          {tags.map((tag) => (
            <div key={tag.name} style={{ display: 'flex', alignItems: 'center', gap: '.5rem',
              padding: '.35rem 0', borderBottom: '1px solid var(--rule)' }}>
              <input type="checkbox" checked={selected.has(tag.name)} onChange={() => toggle(tag.name)}
                aria-label={`選取 ${tag.name}`} />
              {editing && editing.name === tag.name ? (
                <>
                  <input type="text" value={editing.value} autoFocus style={{ flex: 1 }}
                    onChange={(e) => setEditing({ name: tag.name, value: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') rename()
                      if (e.key === 'Escape') setEditing(null)
                    }} />
                  <button type="button" className="btn" onClick={rename}>儲存</button>
                  <button type="button" className="btn-muted" onClick={() => setEditing(null)}>取消</button>
                </>
              ) : (
                <>
                  <span className="tag-pill" style={{ flex: 0 }}>#{tag.name}</span>
                  <span style={{ flex: 1, color: 'var(--ink-dim)', fontSize: '.8rem' }}>{tag.count} 張</span>
                  <button type="button" className="btn-muted"
                    onClick={() => setEditing({ name: tag.name, value: tag.name })}>改名</button>
                  <button type="button" className="btn-muted" onClick={() => remove(tag)}>刪除</button>
                </>
              )}
            </div>
          ))}
          <div style={{ marginTop: '.6rem', fontSize: '.75rem', color: 'var(--ink-dim)' }}>
            改名成已存在的名稱會自動合併。勾選兩個以上可一次合併。
          </div>
        </div>
      )}
    </div>
  )
}
