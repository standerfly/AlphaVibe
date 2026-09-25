/* 新增單純來回查詢條件的表單（specs/008-roundtrip-search，T017）。

   跟 FlightTrackForm.jsx（外站四段票）並列、獨立的表單——欄位形狀
   不同：候選目的地是複選清單（互相比較的不同目的地，不是外站迴圈），
   多了可選的偏好轉機城市，沒有第1/4段間隔策略與排除月份（單純來回
   沒有那些概念，見 specs/008-roundtrip-search/data-model.md）。 */
import { useState } from 'react'
import { apiPost } from '../api/client.js'

const CANDIDATE_DESTINATIONS = [
  'AOJ', 'CTS', 'AXT', 'KIJ', 'HND', 'NRT', 'KIX', 'NGO', 'FUK',
  'BKK', 'KUL', 'HKG', 'SIN', 'SGN', 'MNL', 'ICN',
]

export default function RoundtripTrackForm({ onCreated, onCancel }) {
  const [hub, setHub] = useState('TPE')
  const [destinations, setDestinations] = useState([])
  const [customDest, setCustomDest] = useState('')
  const [preferredTransit, setPreferredTransit] = useState('')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [tripDaysMin, setTripDaysMin] = useState(3)
  const [tripDaysMax, setTripDaysMax] = useState(7)
  const [samples, setSamples] = useState(2)
  const [targetPrice, setTargetPrice] = useState('')
  const [frequency, setFrequency] = useState(7)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const toggleDestination = (code) =>
    setDestinations(destinations.includes(code)
      ? destinations.filter((c) => c !== code)
      : [...destinations, code])

  function addCustomDestination() {
    const code = customDest.trim().toUpperCase()
    if (code && !destinations.includes(code)) {
      setDestinations([...destinations, code])
    }
    setCustomDest('')
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const created = await apiPost('/api/flights/tracks/roundtrip', {
        hub: hub.trim().toUpperCase(),
        destinations,
        preferred_transit: preferredTransit.trim()
          ? preferredTransit.trim().toUpperCase() : null,
        window_start: windowStart,
        window_end: windowEnd,
        trip_days_min: Number(tripDaysMin),
        trip_days_max: Number(tripDaysMax),
        samples_per_month: Number(samples),
        target_price: targetPrice === '' ? null : Number(targetPrice),
        scan_frequency_days: Number(frequency),
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
      <h2>新增單純來回查詢條件</h2>
      <p className="flight-muted">
        查一般的來回行程，不限於外站四段票那種特定玩法。可以填多個候選
        目的地一起比價（例如「北海道或東北任一個看雪的地方」），系統會
        分別查價並標示哪個目的地最便宜。同樣不需要輸入具體日期，行程
        天數也是區間，系統在區間內抽樣比價。
      </p>

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="rt-hub">出發地機場</label>
        <input id="rt-hub" value={hub} maxLength={3}
               placeholder="TPE" onChange={(e) => setHub(e.target.value)} />
      </div>

      <div className="flight-form__row">
        <span className="flight-form__label">候選目的地（可複選，至少 1 個）</span>
        <div className="flight-chips">
          {CANDIDATE_DESTINATIONS.concat(
            destinations.filter((c) => !CANDIDATE_DESTINATIONS.includes(c))
          ).map((c) => (
            <button key={c} type="button"
                    className={destinations.includes(c) ? 'flight-chip flight-chip--on' : 'flight-chip'}
                    onClick={() => toggleDestination(c)}>{c}</button>
          ))}
        </div>
        <div className="flight-form__row--inline">
          <input value={customDest} maxLength={3}
                 placeholder="其他機場代碼，例如 FRA"
                 onChange={(e) => setCustomDest(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === 'Enter') { e.preventDefault(); addCustomDestination() }
                 }} />
          <button type="button" onClick={addCustomDestination}>加入候選</button>
        </div>
      </div>

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="rt-transit">偏好轉機城市（選填）</label>
        <input id="rt-transit" value={preferredTransit} maxLength={3}
               placeholder="不填＝交給 Google Flights 自動決定"
               onChange={(e) => setPreferredTransit(e.target.value)} />
        <small className="flight-muted">
          例如青森（AOJ）通常需經東京轉機，填 NRT 或 HND 可限定只經該
          城市轉機；不填就讓 Google Flights 自動安排轉機組合。
        </small>
      </div>

      <div className="flight-form__row flight-form__row--inline">
        <label className="flight-form__label" htmlFor="rt-ws">出發區間</label>
        <input id="rt-ws" type="month" value={windowStart}
               onChange={(e) => setWindowStart(e.target.value)} />
        <span>～</span>
        <input type="month" value={windowEnd}
               onChange={(e) => setWindowEnd(e.target.value)} />
      </div>

      <div className="flight-form__row flight-form__row--inline">
        <label className="flight-form__label" htmlFor="rt-tdmin">行程天數</label>
        <input id="rt-tdmin" type="number" min="1" value={tripDaysMin}
               onChange={(e) => setTripDaysMin(e.target.value)} />
        <span>～</span>
        <input id="rt-tdmax" type="number" min="1" value={tripDaysMax}
               onChange={(e) => setTripDaysMax(e.target.value)} />
        <label className="flight-form__label" htmlFor="rt-sp">每月抽樣</label>
        <input id="rt-sp" type="number" min="1" value={samples}
               onChange={(e) => setSamples(e.target.value)} />
      </div>

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="rt-tp">目標價（NTD）</label>
        <input id="rt-tp" type="number" min="0" value={targetPrice}
               placeholder="30000" onChange={(e) => setTargetPrice(e.target.value)} />
        <small className="flight-muted">
          來回票價跌破這個數字時會用 Telegram 通知。多個候選目的地時，
          判定基準是全部候選目的地中的最低價，通知內容會標示是哪個
          目的地觸發的。不填就只記錄不通知。
        </small>
      </div>

      <div className="flight-form__row">
        <label className="flight-form__label" htmlFor="rt-fq">自動重掃頻率</label>
        <select id="rt-fq" value={frequency}
                onChange={(e) => setFrequency(Number(e.target.value))}>
          <option value={7}>每週</option>
          <option value={14}>每兩週</option>
          <option value={30}>每月</option>
        </select>
        <small className="flight-muted">
          建立後仍可在條件卡片上調整頻率與目標價。
        </small>
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
