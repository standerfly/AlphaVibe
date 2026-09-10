import { useMemo } from 'react'

/* 資產走勢（情境試算推演）圖表，2026-09-10 新增。把既有情境試算公式
   （POST /api/assets/simulate 回應裡的 `curve` 欄位，見
   app/routers/assets.py::_simulate_asset_scenario() docstring）畫成一條
   完整曲線：現在→累積期（藍實線＋面積）→退休高峰→提領期（橘虛線）
   →資金用盡。不是另一套公式，`curve` 已經算好每個年度點的金額與所屬
   階段（`phase`），這裡純粹是視覺化，不在前端重算任何假設。

   顏色語意：累積期沿用 --accent（跟「資產走勢（實際）」卡的資產總額
   同一個顏色，暗示這是同一條線的延伸）；提領期改用 --amber 虛線——
   跟這個 app「紅漲綠跌」的價格語意無關（這裡不是在講漲跌，是在講
   「換了一種花錢模式」），amber 在這個 app 裡本來就是「參考/提醒」
   的中性提示色（見 StockComboChart 均價虛線、情境試算的 disclaimer
   框），沿用同一個語意比另外發明紅綠更一致。 */

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

export default function NetWorthProjectionChart({ curve, retireYearOffset, nowYear }) {
  const chart = useMemo(() => {
    const pts = curve || []
    if (pts.length < 2) return null

    const amounts = pts.map((p) => p.amount)
    let lo = 0
    let hi = Math.max(...amounts)
    let span = hi - lo || 1
    hi += span * 0.1
    span = hi - lo

    const n = pts.length
    const plotH = HEIGHT - PAD_T - PAD_B
    const xAt = (i) => PAD_L + (WIDTH - PAD_L - PAD_R) * i / Math.max(n - 1, 1)
    const yAt = (v) => PAD_T + plotH * (1 - (v - lo) / span)

    const retireIdx = Math.max(0, Math.min(n - 1, retireYearOffset))
    const accumPts = []
    const withdrawPts = []
    pts.forEach((p, i) => {
      const xy = `${xAt(i).toFixed(1)},${yAt(p.amount).toFixed(1)}`
      if (i <= retireIdx) accumPts.push(xy)
      if (i >= retireIdx) withdrawPts.push(xy)
    })
    const areaPoints =
      `${PAD_L.toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)} ${accumPts.join(' ')} ` +
      `${xAt(retireIdx).toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)}`

    return {
      pts, n, xAt, yAt, retireIdx, accumPts, withdrawPts, areaPoints,
      peakAmount: pts[retireIdx].amount,
      endAmount: pts[n - 1].amount,
    }
  }, [curve, retireYearOffset])

  if (!chart) {
    return <p className="empty">情境試算欄位還沒有可推演的資料，請先在下方情境試算表單送出一次試算。</p>
  }

  const { pts, n, xAt, yAt, retireIdx, accumPts, withdrawPts, areaPoints, peakAmount, endAmount } = chart
  const yearLabel = (offset) => (nowYear != null ? String(nowYear + offset) : `+${offset}年`)

  return (
    <svg className="networth-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%"
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="資產推演曲線圖">
      <line x1={PAD_L} y1={HEIGHT - PAD_B} x2={WIDTH - PAD_R} y2={HEIGHT - PAD_B}
        stroke="var(--rule-strong)" strokeWidth="1" />

      <polygon points={areaPoints} fill="var(--accent-soft)" opacity="0.5" />
      <polyline points={accumPts.join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2.2"
        strokeLinejoin="round" strokeLinecap="round" />
      <polyline points={withdrawPts.join(' ')} fill="none" stroke="var(--amber)" strokeWidth="2"
        strokeDasharray="6,3" strokeLinejoin="round" strokeLinecap="round" />

      <circle cx={xAt(0).toFixed(1)} cy={yAt(pts[0].amount).toFixed(1)} r="3.4" fill="var(--accent)">
        <title>{yearLabel(0)}（現在）　{fmtMoney(pts[0].amount)}</title>
      </circle>
      <text x={xAt(0).toFixed(1)} y={HEIGHT - 6} className="chart-label" textAnchor="start">
        {yearLabel(0)}（現在）
      </text>

      <circle cx={xAt(retireIdx).toFixed(1)} cy={yAt(peakAmount).toFixed(1)} r="4.2" fill="var(--accent)">
        <title>{yearLabel(retireIdx)}（退休）　{fmtMoney(peakAmount)}</title>
      </circle>
      <text x={xAt(retireIdx).toFixed(1)} y={(yAt(peakAmount) - 8).toFixed(1)}
        className="chart-label chart-label-peak" textAnchor="middle">
        退休 {yearLabel(retireIdx)}
      </text>
      <text x={WIDTH - PAD_R + 6} y={(yAt(peakAmount) + 4).toFixed(1)} className="chart-label chart-label-peak">
        {fmtMoney(peakAmount)}
      </text>

      <circle cx={xAt(n - 1).toFixed(1)} cy={yAt(endAmount).toFixed(1)} r="3" fill="var(--ink-dim)">
        <title>{yearLabel(n - 1)}（提領期結束）　{fmtMoney(endAmount)}</title>
      </circle>
      <text x={xAt(n - 1).toFixed(1)} y={HEIGHT - 6} className="chart-label chart-label-end" textAnchor="end">
        {yearLabel(n - 1)}
      </text>
    </svg>
  )
}
