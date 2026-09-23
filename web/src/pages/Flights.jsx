/* 機票掃描分頁（specs/005-flight-scan-page，US1 T022–T024）。

   核心概念：**日期是輸出不是輸入**——使用者只給目的地、候選外站、出發
   區間與行程天數，系統在區間內抽樣日期查價，回傳依價格排序的組合。

   兩個與一般清單頁不同的地方：
   1. 「排隊中」不是錯誤狀態。外部查價服務有速率上限，配額用完時掃描會
      排隊等待，這是預期的營運狀態，視覺上不使用錯誤色。
   2. 「查無票價」與「查詢失敗」必須分開呈現（FR-023）——前者是查到了
      但沒有可用票價，後者是查詢本身失敗，對使用者的意義完全不同。 */
import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, apiDelete } from '../api/client.js'
import FlightTrackForm from './FlightTrackForm.jsx'

const STATE_LABEL = {
  idle: '待掃描',
  queued: '排隊中',
  scanning: '掃描中',
  partial: '部分完成',
  complete: '已完成',
  stale: '資料可能已過期',
}
const STATE_PILL = {
  idle: 'pending', queued: 'pending', scanning: 'pending',
  partial: 'pending', complete: 'ok', stale: 'alert',
}
const RESULT_STATUS_LABEL = { no_fare: '查無票價', failed: '查詢失敗' }

function ntd(v) {
  return v == null ? '—' : `NT$${v.toLocaleString('en-US')}`
}
function md(iso) {
  return iso ? iso.slice(5) : '—'
}

function ResultTable({ results }) {
  if (!results.length) return <p className="flight-muted">尚無結果，觸發掃描後會顯示。</p>
  return (
    <div className="flight-table-scroll">
      <table className="flight-table">
        <thead>
          <tr>
            <th>主行程</th><th>外站</th><th>四段票(NTD)</th>
            <th>接駁(估)</th><th>第1段</th><th>第4段</th><th>航空</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => (
            <tr key={i} className={r.status !== 'ok' ? 'flight-row--muted' : undefined}>
              <td>{md(r.outbound_date)}～{md(r.return_date)}</td>
              <td>{r.outstation}</td>
              <td>
                {r.status === 'ok'
                  ? ntd(r.price)
                  : <span className="flight-muted">{RESULT_STATUS_LABEL[r.status] || r.status}</span>}
              </td>
              <td className="flight-muted">{r.connector_price ? ntd(r.connector_price) : '—'}</td>
              <td>{md(r.leg1_date)}<small className="flight-muted"> −{r.lead_days}天</small></td>
              <td>{md(r.leg4_date)}<small className="flight-muted"> +{r.trail_days}天</small></td>
              <td className="flight-muted">{r.airline || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <small className="flight-muted">接駁票為單一代表日期的估算值，實際購買前請重查。</small>
    </div>
  )
}

function TrackCard({ track, onScan, onDelete, onOpen, open, detail }) {
  const p = track.progress || { done: 0, total: 0 }
  return (
    <article className="flight-card">
      <header className="flight-card__head">
        <h3>{track.name}</h3>
        <span className={`flight-pill flight-pill--${STATE_PILL[track.state] || 'pending'}`}>
          {STATE_LABEL[track.state] || track.state}
        </span>
      </header>
      <p className="flight-muted">
        {track.window_start}～{track.window_end} · 行程 {track.trip_days} 天 ·
        外站 {track.outstations.join('／')} · 已查 {p.done}/{p.total}
      </p>
      {track.lowest ? (
        <p>
          最低 <strong>{ntd(track.lowest.price)}</strong>
          （{track.lowest.outstation}，{md(track.lowest.outbound_date)} 出發）
          {track.lowest.target_met && <span className="flight-pill flight-pill--ok">已達目標價</span>}
        </p>
      ) : (
        <p className="flight-muted">尚無報價</p>
      )}
      {track.skipped_count > 0 && (
        <p className="flight-muted">
          有 {track.skipped_count} 個日期因找不到可用的間隔而跳過。
        </p>
      )}
      <div className="flight-card__actions">
        <button onClick={() => onScan(track.id)}>重新掃描</button>
        <button onClick={() => onOpen(open ? null : track.id)}>
          {open ? '收合結果' : '查看結果'}
        </button>
        <button className="flight-btn--danger" onClick={() => onDelete(track.id)}>刪除</button>
      </div>
      {open && detail && (
        <>
          {detail.state === 'queued' && (
            <p className="flight-muted">
              已達查詢速率上限，約 {Math.ceil((detail.quota?.seconds_until_free || 0) / 60)} 分鐘後接續。
            </p>
          )}
          <ResultTable results={detail.results || []} />
        </>
      )}
    </article>
  )
}

export default function Flights() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await apiGet('/api/flights/tracks'))
      setError(null)
    } catch (e) { setError(e.message) }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (openId == null) { setDetail(null); return }
    let alive = true
    apiGet(`/api/flights/tracks/${openId}/results`)
      .then((d) => { if (alive) setDetail(d) })
      .catch((e) => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [openId])

  async function scan(id) {
    try {
      const r = await apiPost(`/api/flights/tracks/${id}/scan`, {})
      setNotice(r.message || `掃描已開始：本次將查 ${r.will_query} 組`)
      load()
    } catch (e) { setError(e.message) }
  }

  async function remove(id) {
    try {
      await apiDelete(`/api/flights/tracks/${id}`)
      if (openId === id) setOpenId(null)
      load()
    } catch (e) { setError(e.message) }
  }

  const quota = data?.quota
  return (
    <section className="flight-page">
      <header className="flight-page__head">
        <h1>機票</h1>
        <button className="flight-btn--primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '關閉表單' : '新增追蹤'}
        </button>
      </header>
      <p className="flight-page__lead">
        外站四段票掃描。給定目的地、候選外站與出發區間，系統抽樣日期查價，
        回傳依價格排序的組合——不需要自己指定日期。
      </p>

      {quota && (
        <p className="flight-muted">
          查詢用量：最近一小時 {quota.used}/{quota.limit} 次
          （此上限為{quota.limit_basis === 'measured' ? '實測值' : '推估值，尚未長期驗證'}）
          {quota.used >= quota.limit &&
            `，約 ${Math.ceil(quota.seconds_until_free / 60)} 分鐘後釋出名額`}
        </p>
      )}

      {notice && <p className="flight-muted">{notice}</p>}
      {error && <p className="flight-error">發生錯誤：{error}</p>}

      {showForm && (
        <FlightTrackForm
          onCancel={() => setShowForm(false)}
          onCreated={() => { setShowForm(false); setNotice('條件已建立，可按「重新掃描」開始查價'); load() }}
        />
      )}

      {!data && !error && <p className="flight-muted">載入中…</p>}
      {data && data.tracks.length === 0 && !showForm && (
        <p className="flight-muted">還沒有查詢條件。按「新增追蹤」建立第一個。</p>
      )}
      {data && data.tracks.map((t) => (
        <TrackCard key={t.id} track={t} onScan={scan} onDelete={remove}
                   onOpen={setOpenId} open={openId === t.id} detail={detail} />
      ))}

      <p className="flight-muted">
        提醒：第1段（外站→台北）一定要搭，no-show 會讓後三段全部失效；
        四段票僅經濟艙適用，商務艙在多城市查詢會跳艙翻倍。
      </p>
    </section>
  )
}
