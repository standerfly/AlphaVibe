import { useMemo } from 'react'

/* 資產走勢（實際）圖表，2026-09-10 新增，Q-046 資產分頁「資產走勢」卡。
   決策脈絡：docs/spec-intake/alphavibe/roadmap.md Q-046 與
   app/routers/assets.py／poc/kb-mcp/kb_store.py「資產走勢」相關 docstring。

   資料源：GET /api/assets/net-worth-history 回傳的 `points`（依日期升冪，
   每筆 {period, snapshot_date, total_amount, cumulative_contributed,
   source}）。`cumulative_contributed` 可能是 null（舊快照、或手動回填時
   沒填這個欄位）——虛線只畫過有值的點，缺值的點直接跳過不強行補 0，
   避免畫出一條假的「投入歸零」。

   畫法沿用 StockComboChart.jsx 的既有慣例：viewBox+preserveAspectRatio
   讓 SVG 隨容器縮放、配色一律用 web/src/styles/tokens.css 的 CSS var、
   純 JSX 產生 SVG 元素不額外引入圖表函式庫。

   顏色語意：資產總額用 --accent（藍，中性主線）；累積投入用
   --ink-dim 虛線（中性、退居次要）；目標參考線用 --amber 虛線（沿用
   StockComboChart 均價虛線的「參考線」語意，不是警示）。損益的紅/綠
   刻意不畫進這張圖本身（圖上只有中性配色＋文字標籤），紅漲綠跌的語意
   留給呼叫端的統計數字卡（Assets.jsx 用既有 .is-up/.is-down class），
   這裡不要自己另外詮釋一次。 */

const WIDTH = 640
const HEIGHT = 240
const PAD_L = 8
const PAD_R = 96
const PAD_T = 16
const PAD_B = 24

function fmtMoney(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v < 0 ? '-' : ''
  return sign + 'NT$ ' + Math.round(Math.abs(v)).toLocaleString('zh-TW')
}

export default function NetWorthChart({ points, goalAmount }) {
  const chart = useMemo(() => {
    const pts = points || []
    if (pts.length < 2) return null

    const totals = pts.map((p) => p.total_amount)
    const contribIdx = []
    pts.forEach((p, i) => { if (p.cumulative_contributed != null) contribIdx.push(i) })
    const contribValues = contribIdx.map((i) => pts[i].cumulative_contributed)

    const allValues = totals.concat(contribValues)
    if (goalAmount != null && Number.isFinite(goalAmount)) allValues.push(goalAmount)
    let lo = Math.min(...allValues)
    let hi = Math.max(...allValues)
    let span = (hi - lo) || Math.max(Math.abs(hi) * 0.02, 1)
    // 上下各留 6% 緩衝，避免最高/最低點的圓點或標籤貼著邊界被裁掉。
    lo -= span * 0.06
    hi += span * 0.06
    span = hi - lo

    const n = pts.length
    const plotH = HEIGHT - PAD_T - PAD_B
    const xAt = (i) => PAD_L + (WIDTH - PAD_L - PAD_R) * i / Math.max(n - 1, 1)
    const yAt = (v) => PAD_T + plotH * (1 - (v - lo) / span)

    const totalPoints = pts.map((p, i) => `${xAt(i).toFixed(1)},${yAt(p.total_amount).toFixed(1)}`).join(' ')
    const areaPoints =
      `${PAD_L.toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)} ${totalPoints} ` +
      `${xAt(n - 1).toFixed(1)},${(HEIGHT - PAD_B).toFixed(1)}`
    const contribPoints = contribIdx.length >= 2
      ? contribIdx.map((i) => `${xAt(i).toFixed(1)},${yAt(pts[i].cumulative_contributed).toFixed(1)}`).join(' ')
      : null

    const last = pts[n - 1]
    const lastContribIdx = contribIdx.length ? contribIdx[contribIdx.length - 1] : null

    // 每個點的「當期投入」＝這個點跟上一個「有累積投入值」的點之間的差額，
    // 給 tooltip 用；缺前一個可比對的點就顯示不出當期投入（null）。
    const periodContribAt = (i) => {
      const p = pts[i]
      if (p.cumulative_contributed == null) return null
      const priorIdx = [...contribIdx].reverse().find((j) => j < i)
      if (priorIdx == null) return p.cumulative_contributed
      return p.cumulative_contributed - pts[priorIdx].cumulative_contributed
    }

    return {
      pts, n, xAt, yAt, totalPoints, areaPoints, contribPoints,
      goalY: (goalAmount != null && Number.isFinite(goalAmount)) ? yAt(goalAmount) : null,
      last, lastContribIdx, periodContribAt,
    }
  }, [points, goalAmount])

  if (!chart) {
    return (
      <p className="empty">
        尚無足夠資料繪製走勢圖（至少需要2個時間點）——之後每次資產異動或記一筆投入，
        都會自動累積一個點；也可以用下方「手動回填」先補幾筆過去的資料。
      </p>
    )
  }

  const { pts, n, xAt, yAt, totalPoints, areaPoints, contribPoints, goalY, last, lastContribIdx, periodContribAt } = chart

  return (
    <svg className="networth-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%"
      preserveAspectRatio="xMidYMid meet" role="img" aria-label="資產總額與累積投入金額走勢圖">
      <line x1={PAD_L} y1={HEIGHT - PAD_B} x2={WIDTH - PAD_R} y2={HEIGHT - PAD_B}
        stroke="var(--rule-strong)" strokeWidth="1" />

      {goalY != null && (
        <>
          <line x1={PAD_L} y1={goalY.toFixed(1)} x2={WIDTH - PAD_R} y2={goalY.toFixed(1)}
            stroke="var(--amber)" strokeWidth="1.4" strokeDasharray="5,3" />
          <text x={WIDTH - PAD_R + 6} y={(goalY + 4).toFixed(1)} className="chart-label chart-label-goal">
            目標 {fmtMoney(goalAmount)}
          </text>
        </>
      )}

      <polygon points={areaPoints} fill="var(--accent-soft)" opacity="0.55" />
      <polyline points={totalPoints} fill="none" stroke="var(--accent)" strokeWidth="2.2"
        strokeLinejoin="round" strokeLinecap="round" />

      {contribPoints && (
        <polyline points={contribPoints} fill="none" stroke="var(--ink-dim)" strokeWidth="1.8"
          strokeDasharray="6,3" strokeLinejoin="round" strokeLinecap="round" />
      )}

      {pts.map((p, i) => {
        const isLatest = i === n - 1
        const periodContrib = periodContribAt(i)
        return (
          <circle key={`total-${p.snapshot_date}`} cx={xAt(i).toFixed(1)} cy={yAt(p.total_amount).toFixed(1)}
            r={isLatest ? 4 : 2.6} fill="var(--accent)">
            <title>
              {p.period} 資產總額 {fmtMoney(p.total_amount)}
              {periodContrib != null ? `　當期投入 ${fmtMoney(periodContrib)}` : ''}
              {p.source === 'manual' ? '（手動回填）' : ''}
            </title>
          </circle>
        )
      })}
      {pts.map((p, i) => (
        p.cumulative_contributed == null ? null : (
          <circle key={`contrib-${p.snapshot_date}`} cx={xAt(i).toFixed(1)} cy={yAt(p.cumulative_contributed).toFixed(1)}
            r={i === lastContribIdx ? 3.4 : 2.2} fill="var(--ink-dim)">
            <title>
              {p.period} 累積投入 {fmtMoney(p.cumulative_contributed)}
              {periodContribAt(i) != null ? `　當期投入 ${fmtMoney(periodContribAt(i))}` : ''}
            </title>
          </circle>
        )
      ))}

      <text x={WIDTH - PAD_R + 6} y={(yAt(last.total_amount) + 4).toFixed(1)} className="chart-label chart-label-total">
        {fmtMoney(last.total_amount)}
      </text>
      {lastContribIdx != null && (
        <text x={WIDTH - PAD_R + 6} y={(yAt(pts[lastContribIdx].cumulative_contributed) + 4).toFixed(1)}
          className="chart-label chart-label-contrib">
          {fmtMoney(pts[lastContribIdx].cumulative_contributed)}
        </text>
      )}

      <text x={PAD_L} y={HEIGHT - 6} className="chart-label" textAnchor="start">{pts[0].period}</text>
      <text x={WIDTH - PAD_R} y={HEIGHT - 6} className="chart-label" textAnchor="end">{pts[n - 1].period}</text>
    </svg>
  )
}
