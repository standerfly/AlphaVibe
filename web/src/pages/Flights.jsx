/* 機票掃描分頁（specs/005-flight-scan-page，US1 T022–T024）。

   核心概念：**日期是輸出不是輸入**——使用者只給目的地、候選外站、出發
   區間與行程天數，系統在區間內抽樣日期查價，回傳依價格排序的組合。

   兩個與一般清單頁不同的地方：
   1. 「排隊中」不是錯誤狀態。外部查價服務有速率上限，配額用完時掃描會
      排隊等待，這是預期的營運狀態，視覺上不使用錯誤色。
   2. 「查無票價」與「查詢失敗」必須分開呈現（FR-023）——前者是查到了
      但沒有可用票價，後者是查詢本身失敗，對使用者的意義完全不同。 */
import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, apiDelete, apiPatch } from '../api/client.js'
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
const POLL_MS = 4000

/* 頻率選項：週期越長越省查詢配額，但價格反應越慢。
   30 天不是「每月同一天」——排程以「距上次成功滿 N 天且今天輪到它」
   判定，月份長度不同不影響。 */
const FREQ_OPTIONS = [
  { days: 7, label: '每週' },
  { days: 14, label: '每兩週' },
  { days: 30, label: '每月' },
]

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
            <th>接駁(估)</th><th>第1段</th><th>第4段</th><th>航空</th><th>查價</th>
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
              <td className="flight-links">
                {r.links?.four_segment && (
                  <a href={r.links.four_segment} target="_blank" rel="noreferrer">四段票</a>
                )}
                {r.links?.connector && (
                  <a href={r.links.connector} target="_blank" rel="noreferrer">接駁</a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <small className="flight-muted">接駁票為單一代表日期的估算值，實際購買前請重查。</small>
    </div>
  )
}

/* 被跳過的日期（FR-010）。

   不只給數量——使用者需要知道「哪些日期」以及「為什麼」，才能判斷要不要
   放寬排除月份或改變間隔策略。只顯示「跳過 3 個日期」等於要他自己猜。 */
const SKIP_REASON_LABEL = {
  // 2026-09-24：原本第1段／第4段用固定策略（m1/m3/m5）時，沒檢查算出來
  // 的日期是否已經過去，近期主行程配大間隔會推出已飛走的航段（買不到、
  // 白佔配額）。修正後 reason 依實際原因拆成兩種，後備文案跟著補齊；
  // 正常情況下都有 `s.detail`，這裡只是缺失時的保底。
  no_feasible_offset: '找不到能避開排除月份的間隔',
  excluded_month: '找不到能避開排除月份的間隔',
  past_date: '已經是過去日期，買不到票',
}

function SkippedList({ skipped }) {
  if (!skipped.length) return null
  return (
    <details className="flight-skipped">
      <summary>有 {skipped.length} 個日期被跳過</summary>
      <ul>
        {skipped.map((s, i) => (
          <li key={i}>
            {s.outbound_date}：{s.detail || SKIP_REASON_LABEL[s.reason] || s.reason}
          </li>
        ))}
      </ul>
      <small className="flight-muted">
        放寬該航段的排除月份，或把間隔策略改為較短的選項，即可納入這些日期。
      </small>
    </details>
  )
}

function TrackCard({ track, onScan, onDelete, onOpen, onFrequency, open, detail }) {
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
          {track.lowest.target_met ? (
            <span className="flight-pill flight-pill--ok">已達目標價</span>
          ) : track.lowest.gap_to_target != null && (
            <span className="flight-muted"> · 距目標價還差 {ntd(track.lowest.gap_to_target)}</span>
          )}
        </p>
      ) : (
        <p className="flight-muted">尚無報價</p>
      )}
      {track.skipped_count > 0 && (
        <p className="flight-muted">
          有 {track.skipped_count} 個日期因找不到可用的間隔而跳過，
          展開結果可看是哪幾天。
        </p>
      )}
      {track.state === 'stale' && (
        <p className="flight-stale">
          距上次成功掃描已超過兩個週期，畫面上的價格可能不再有效；
          達標通知也會暫停，直到重新掃描成功為止。
        </p>
      )}
      <p className="flight-muted">
        自動重掃：
        <select
          className="flight-freq"
          value={track.scan_frequency_days}
          onChange={(e) => onFrequency(track.id, Number(e.target.value))}
        >
          {FREQ_OPTIONS.map((o) => (
            <option key={o.days} value={o.days}>{o.label}</option>
          ))}
        </select>
        {track.next_scan_date && <> · 下次 {md(track.next_scan_date)}</>}
        {track.last_success_at && <> · 上次成功 {md(track.last_success_at.slice(0, 10))}</>}
      </p>
      {track.notify?.last_notified_at && (
        <p className={track.notify.last_notify_failed ? 'flight-error' : 'flight-muted'}>
          {track.notify.last_notify_failed
            ? `上次達標通知（NT$${(track.notify.last_notified_price || 0).toLocaleString()}）送出失敗，請檢查 Telegram 設定`
            : `已通知達標 NT$${(track.notify.last_notified_price || 0).toLocaleString()}（${md(track.notify.last_notified_at.slice(0, 10))}）`}
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
          {detail.blocked && (
            <p className="flight-muted">
              {detail.blocked_kind === 'soft_timeout'
                ? '上次掃描遇到連續逾時（外部服務的軟性阻擋），已中止並保留已完成的部分。隔一段時間再試即可。'
                : '上次掃描被外部服務明確阻擋，已中止並保留已完成的部分。建議放慢查詢節奏後再試。'}
            </p>
          )}
          {detail.state === 'scanning' && (
            <p className="flight-muted">
              掃描中：{detail.progress?.done}/{detail.progress?.total}（畫面會自動更新）
            </p>
          )}
          <ResultTable results={detail.results || []} />
          <SkippedList skipped={detail.skipped || []} />
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

  /* 掃描進行中時輪詢結果，完成後停止。

     間隔 4 秒：掃描以每筆數秒到數十秒的速度推進，秒級輪詢沒有意義，
     只會徒增請求。沿用 Gateway.jsx 既有的 setInterval 模式，不為此
     引入 SSE／WebSocket——專案內無既有用例，而這裡的更新頻率極低。 */
  useEffect(() => {
    if (openId == null) { setDetail(null); return }
    let alive = true
    let timer = null

    const fetchDetail = () => apiGet(`/api/flights/tracks/${openId}/results`)
      .then((d) => {
        if (!alive) return
        setDetail(d)
        // 只有還在跑或排隊中才需要繼續輪詢
        const running = d.state === 'scanning' || d.state === 'queued'
        if (!running && timer) { clearInterval(timer); timer = null }
      })
      .catch((e) => { if (alive) setError(e.message) })

    fetchDetail().then(() => {
      if (alive && !timer) timer = setInterval(fetchDetail, POLL_MS)
    })
    return () => { alive = false; if (timer) clearInterval(timer) }
  }, [openId])

  /* 掃描中時，卡片上的狀態與進度也要跟著更新（不只展開的結果區）。 */
  useEffect(() => {
    const anyRunning = (data?.tracks || []).some(
      (t) => t.state === 'scanning' || t.state === 'queued')
    if (!anyRunning) return
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [data, load])

  async function scan(id) {
    try {
      const r = await apiPost(`/api/flights/tracks/${id}/scan`, {})
      setNotice(r.message || `掃描已開始：本次將查 ${r.will_query} 組`)
      load()
    } catch (e) { setError(e.message) }
  }

  async function setFrequency(id, days) {
    try {
      await apiPatch(`/api/flights/tracks/${id}`, { scan_frequency_days: days })
      setNotice('已更新重掃頻率')
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
                   onFrequency={setFrequency}
                   onOpen={setOpenId} open={openId === t.id} detail={detail} />
      ))}

      <p className="flight-muted">
        提醒：第1段（外站→台北）一定要搭，no-show 會讓後三段全部失效；
        四段票僅經濟艙適用，商務艙在多城市查詢會跳艙翻倍。
      </p>

      <NativeTracking />
    </section>
  )
}

/* 外部服務自帶的價格追蹤（FR-022）。

   重點是**說清楚它不支援四段票**——使用者很容易以為可以直接追蹤這裡
   查到的組合。可用的是主行程來回票，作為四段票價格的代理指標。 */
function NativeTracking() {
  const [info, setInfo] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open || info) return
    apiGet('/api/flights/native-tracking').then(setInfo).catch(() => {})
  }, [open, info])

  return (
    <details className="flight-native" onToggle={(e) => setOpen(e.target.open)}>
      <summary>用外部服務自己的價格追蹤功能？</summary>
      {!info && <p className="flight-muted">載入中…</p>}
      {info && (
        <>
          <p className="flight-muted">{info.reason}</p>
          <p className="flight-muted">可用於：{info.usable_for}</p>
          <ol className="flight-muted">
            {info.steps.map((st, i) => <li key={i}>{st}</li>)}
          </ol>
          {info.main_trip_links?.length > 0 && (
            <ul className="flight-muted">
              {info.main_trip_links.map((l, i) => (
                <li key={i}>
                  <a href={l.url} target="_blank" rel="noreferrer">{l.label}</a>
                </li>
              ))}
            </ul>
          )}
          <p className="flight-muted">
            腳本：<code>{info.script_path}</code>
          </p>
        </>
      )}
    </details>
  )
}
