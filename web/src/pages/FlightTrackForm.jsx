/* 新增機票查詢條件的表單（specs/005-flight-scan-page，T021）。

   設計要點：**使用者不輸入任何具體日期**——只給出發區間（年月）與行程
   天數，系統在區間內抽樣（spec FR-004）。這是整個功能的核心概念，
   表單刻意不提供「出發日」欄位。

   排除月份是 1–12 的自由複選，**不提供「夏季」之類的季節快捷**——
   南半球目的地的旺季與北半球相反，寫死季節定義會讓南半球航線判斷錯誤
   （CON-12，PO 2026-09-23 審閱需求時指正）。 */
import { useState } from 'react'
import { apiPost } from '../api/client.js'

const JAPAN = ['NRT', 'HND', 'KIX', 'NGO', 'FUK', 'CTS', 'OKA']
const ASIA = ['BKK', 'KUL', 'HKG', 'SIN', 'SGN', 'MNL', 'ICN']
const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

const STRATEGIES = [
  { value: 'none', label: '不拉遠' },
  { value: 'm1', label: '約 1 個月' },
  { value: 'm3', label: '約 3 個月' },
  { value: 'm5', label: '約 5 個月' },
  { value: 'auto', label: '自動避開排除月份' },
]

function MonthPicker({ value, onChange, label, hint }) {
  const toggle = (m) =>
    onChange(value.includes(m) ? value.filter((x) => x !== m) : [...value, m].sort((a, b) => a - b))
  return (
    <div className="flight-form__row">
      <span className="flight-form__label">{label}</span>
      <div className="flight-months">
        {MONTHS.map((m) => (
          <button
            key={m}
            type="button"
            className={value.includes(m) ? 'flight-month flight-month--on' : 'flight-month'}
            onClick={() => toggle(m)}
          >
            {m}
          </button>
        ))}
      </div>
      {hint && <small className="flight-muted">{hint}</small>}
    </div>
  )
}

export default function FlightTrackForm({ onCreated, onCancel }) {
  const [destination, setDestination] = useState('')
  const [outstations, setOutstations] = useState([])
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [tripDays, setTripDays] = useState(12)
  const [leadStrategy, setLeadStrategy] = useState('m3')
  const [trailStrategy, setTrailStrategy] = useState('m1')
  const [exTrip, setExTrip] = useState([])
  const [exLead, setExLead] = useState([])
  const [exTrail, setExTrail] = useState([])
  const [targetPrice, setTargetPrice] = useState('')
  const [samples, setSamples] = useState(2)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const toggleStation = (code) =>
    setOutstations(outstations.includes(code)
      ? outstations.filter((c) => c !== code)
      : [...outstations, code])

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const created = await apiPost('/api/flights/tracks', {
        destination: destination.trim().toUpperCase(),
        outstations,
        window_start: windowStart,
        window_end: windowEnd,
        trip_days: Number(tripDays),
        lead_strategy: leadStrategy,
        trail_strategy: trailStrategy,
        exclude_months: { trip: exTrip, lead: exLead, trail: exTrail },
        target_price: targetPrice === '' ? null : Number(targetPrice),
        samples_per_month: Number(samples),
      })
      onCreated && onCreated(created.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="flight-form" onSubmit={submit}>
      <h2>新增查詢條件</h2>
      <p className="flight-muted">
        不需要輸入出發日——給區間與行程天數，系統會在區間內抽樣日期查價。
      </p>

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="dest">目的地機場</label>
        <input id="dest" value={destination} maxLength={3}
               placeholder="PRG" onChange={(e) => setDestination(e.target.value)} />
      </div>

      <div className="flight-form__row">
        <span className="flight-form__label">候選外站（可複選）</span>
        <div className="flight-chips">
          {JAPAN.concat(ASIA).map((c) => (
            <button key={c} type="button"
                    className={outstations.includes(c) ? 'flight-chip flight-chip--on' : 'flight-chip'}
                    onClick={() => toggleStation(c)}>{c}</button>
          ))}
        </div>
      </div>

      <div className="flight-form__row flight-form__row--inline">
        <label className="flight-form__label" htmlFor="ws">出發區間</label>
        <input id="ws" type="month" value={windowStart}
               onChange={(e) => setWindowStart(e.target.value)} />
        <span>～</span>
        <input type="month" value={windowEnd}
               onChange={(e) => setWindowEnd(e.target.value)} />
      </div>

      <div className="flight-form__row flight-form__row--inline">
        <label className="flight-form__label" htmlFor="td">行程天數</label>
        <input id="td" type="number" min="1" value={tripDays}
               onChange={(e) => setTripDays(e.target.value)} />
        <label className="flight-form__label" htmlFor="sp">每月抽樣</label>
        <input id="sp" type="number" min="1" value={samples}
               onChange={(e) => setSamples(e.target.value)} />
      </div>

      <div className="flight-form__row flight-form__row--inline">
        <label className="flight-form__label" htmlFor="ls">第1段提前</label>
        <select id="ls" value={leadStrategy} onChange={(e) => setLeadStrategy(e.target.value)}>
          {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <label className="flight-form__label" htmlFor="ts">第4段延後</label>
        <select id="ts" value={trailStrategy} onChange={(e) => setTrailStrategy(e.target.value)}>
          {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>
      <small className="flight-muted">
        拉遠是為了讓第1段成為另一趟旅行的回程、第4段成為再一趟的去程，
        避免密集請假。
      </small>

      <MonthPicker label="主行程排除月份" value={exTrip} onChange={setExTrip}
                   hint="1–12 任意複選。南半球目的地的旺季是 12–2 月，與北半球相反。" />
      <MonthPicker label="第1段排除月份" value={exLead} onChange={setExLead} />
      <MonthPicker label="第4段排除月份" value={exTrail} onChange={setExTrail} />

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="tp">目標價（NTD）</label>
        <input id="tp" type="number" min="0" value={targetPrice}
               placeholder="38000" onChange={(e) => setTargetPrice(e.target.value)} />
        <small className="flight-muted">目前僅記錄與顯示，降價通知為後續功能。</small>
      </div>

      {error && <p className="flight-error">建立失敗：{error}</p>}
      <div className="flight-form__actions">
        <button type="button" onClick={onCancel} disabled={busy}>取消</button>
        <button type="submit" className="flight-btn--primary" disabled={busy}>
          {busy ? '建立中…' : '建立條件'}
        </button>
      </div>
    </form>
  )
}
