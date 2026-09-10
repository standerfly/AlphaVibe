import { useMemo } from 'react'

/* 資產走勢（情境試算推演）圖表，2026-09-10 新增，稍晚追加近期(月)/
   長期(年)視角切換（PO 反映原本只有年視角、X軸又只標了現在/退休/結束
   三個點，中間沒有任何刻度，看起來像「沒有年份」）。

   兩個資料源都來自既有情境試算公式的視覺化延伸（見
   app/routers/assets.py::_simulate_asset_scenario() docstring），不是
   前端另外算：
   - `curve`（長期／年）：現在→退休→提領期結束，逐年取點，橫跨整段
     退休生涯（可能長達數十年）。
   - `monthlyCurve`（近期／月）：只有最近 24 個月，逐月取點，方便看
     剛開始那一兩年的建倉節奏跟複利怎麼慢慢累積；超出這個範圍看不到，
     長期趨勢要切回「年」視角。

   兩種視角共用同一套畫法：X軸現在固定會有規律的刻度（不是只標頭尾跟
   退休三個點），退休高峰只在它真的落在目前這組資料範圍內才畫（近期
   視角通常看不到退休，除非設定的累積年數很短）。 */

const WIDTH = 640
const HEIGHT = 220
const PAD_L = 8
const PAD_R = 84
const PAD_T = 16
const PAD_B = 24

function fmtMoney(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  return 'NT$ ' + Math.round(v).toLocaleString('zh-TW')
}

// 每隔幾個點標一次 X 軸刻度。maxTicks 依標籤長度調整：年視角標籤是
// 「YYYY」4個字，月視角是「YYYY-MM」7個字幾乎兩倍寬，用同一個目標
// 刻度數會讓月視角的標籤擠在一起互相重疊，所以月視角刻度數故意抓少一點。
function tickInterval(n, maxTicks) {
  return Math.max(1, Math.round((n - 1) / maxTicks))
}

export default function NetWorthProjectionChart({
  curve, monthlyCurve, retireYearOffset, retireMonthOffset,
  granularity, nowYear, nowMonth,
}) {
  const isMonth = granularity === 'month'
  const points = isMonth ? (monthlyCurve || []) : (curve || [])
  const retireIdx = isMonth ? retireMonthOffset : retireYearOffset

  // 標籤：年視角直接是西元年；月視角從「現在」的年月往後推算 YYYY-MM，
  // nowMonth 是 1~12（一般 Date.getMonth() 回傳的 0~11 記得先 +1 再傳進來）。
  const labelAt = (offset) => {
    if (!isMonth) return String((nowYear ?? 0) + offset)
    const total = (nowMonth ?? 1) - 1 + offset
    const y = (nowYear ?? 0) + Math.floor(total / 12)
    const m = (total % 12) + 1
    return `${y}-${String(m).padStart(2, '0')}`
  }

  const chart = useMemo(() => {
    if (points.length < 2) return null

    const amounts = points.map((p) => p.amount)
    let lo = 0
    let hi = Math.max(...amounts)
    let span = hi - lo || 1
    hi += span * 0.1
    span = hi - lo

    const n = points.length
    const plotH = HEIGHT - PAD_T - PAD_B
    const xAt = (i) => PAD_L + (WIDTH - PAD_L - PAD_R) * i / Math.max(n - 1, 1)
    const yAt = (v) => PAD_T + plotH * (1 - (v - lo) / span)

    // 退休高峰只有落在目前這組資料範圍內才畫（近期/月視角通常看不到）。
    const peakVisible = retireIdx != null && retireIdx >= 0 && retireIdx <= n - 1

    const accumPts = []
    const withdrawPts = []
    const splitIdx = peakVisible ? retireIdx : (points[points.length - 1].phase === 'withdrawal' ? 0 : n - 1)
    points.forEach((p, i) => {
      const xy = `${xAt(i).toFixed(1)},${yAt(p.amount).toFixed(1)}`
      if (i <= splitIdx) accumPts.push(xy)
      if (i >= splitIdx) withdrawPts.push(xy)
    })
    const areaPoints =
      `${PAD_L.toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)} ${accumPts.join(' ')} ` +
      `${xAt(splitIdx).toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)}`

    const interval = tickInterval(n, isMonth ? 5 : 7)
    const ticks = []
    for (let i = 0; i < n; i += interval) ticks.push(i)
    if (ticks[ticks.length - 1] !== n - 1) ticks.push(n - 1)

    return { points, n, xAt, yAt, peakVisible, splitIdx, accumPts, withdrawPts, areaPoints, ticks }
  }, [points, retireIdx])

  if (!chart) {
    return <p className="empty">情境試算欄位還沒有可推演的資料，請先在下方情境試算表單送出一次試算。</p>
  }

  const { points: pts, n, xAt, yAt, peakVisible, splitIdx, accumPts, withdrawPts, areaPoints, ticks } = chart

  return (
    <svg className="networth-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%"
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="資產推演曲線圖">
      <line x1={PAD_L} y1={HEIGHT - PAD_B} x2={WIDTH - PAD_R} y2={HEIGHT - PAD_B}
        stroke="var(--rule-strong)" strokeWidth="1" />

      <polygon points={areaPoints} fill="var(--accent-soft)" opacity="0.5" />
      <polyline points={accumPts.join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2.2"
        strokeLinejoin="round" strokeLinecap="round" />
      {withdrawPts.length > 1 && (
        <polyline points={withdrawPts.join(' ')} fill="none" stroke="var(--amber)" strokeWidth="2"
          strokeDasharray="6,3" strokeLinejoin="round" strokeLinecap="round" />
      )}

      {/* X軸刻度：固定間隔，不管年/月視角都會有中間刻度，不是只有頭尾。 */}
      {ticks.map((i) => (
        <g key={`tick-${i}`}>
          <line x1={xAt(i).toFixed(1)} y1={(HEIGHT - PAD_B - 3).toFixed(1)}
            x2={xAt(i).toFixed(1)} y2={(HEIGHT - PAD_B + 3).toFixed(1)}
            stroke="var(--ink-dim)" strokeWidth="1" />
          <text x={xAt(i).toFixed(1)} y={HEIGHT - 6} className="chart-label"
            textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
            {labelAt(i)}
          </text>
        </g>
      ))}

      {/* 「現在」單獨標在第一個點上方（不是塞進底下的軸刻度文字），
          避免文字太長跟緊接在後面的刻度重疊——月視角的刻度間距本來就
          比年視角窄，兩者黏在一起會糊成一團看不清楚。 */}
      <text x={xAt(0).toFixed(1)} y={(yAt(pts[0].amount) - 8).toFixed(1)} className="chart-label" textAnchor="start">
        現在
      </text>
      <circle cx={xAt(0).toFixed(1)} cy={yAt(pts[0].amount).toFixed(1)} r="3.4" fill="var(--accent)">
        <title>{labelAt(0)}（現在）　{fmtMoney(pts[0].amount)}</title>
      </circle>

      {peakVisible && (
        <>
          <circle cx={xAt(splitIdx).toFixed(1)} cy={yAt(pts[splitIdx].amount).toFixed(1)} r="4.2" fill="var(--accent)">
            <title>{labelAt(splitIdx)}（退休）　{fmtMoney(pts[splitIdx].amount)}</title>
          </circle>
          <text x={xAt(splitIdx).toFixed(1)} y={(yAt(pts[splitIdx].amount) - 8).toFixed(1)}
            className="chart-label chart-label-peak" textAnchor="middle">
            退休 {labelAt(splitIdx)}
          </text>
          <text x={WIDTH - PAD_R + 6} y={(yAt(pts[splitIdx].amount) + 4).toFixed(1)} className="chart-label chart-label-peak">
            {fmtMoney(pts[splitIdx].amount)}
          </text>
        </>
      )}

      <circle cx={xAt(n - 1).toFixed(1)} cy={yAt(pts[n - 1].amount).toFixed(1)} r="3" fill="var(--ink-dim)">
        <title>{labelAt(n - 1)}　{fmtMoney(pts[n - 1].amount)}</title>
      </circle>
      {!peakVisible && (
        <text x={WIDTH - PAD_R + 6} y={(yAt(pts[n - 1].amount) + 4).toFixed(1)} className="chart-label chart-label-end">
          {fmtMoney(pts[n - 1].amount)}
        </text>
      )}
    </svg>
  )
}
