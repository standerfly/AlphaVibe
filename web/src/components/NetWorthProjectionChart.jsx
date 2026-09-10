import { useMemo } from 'react'

/* 資產走勢（情境試算推演）圖表，2026-09-10 新增，稍晚兩次追加：
   (1) 近期(月)/長期(年)視角切換＋X軸刻度（原本只標現在/退休/結束三個
       點，中間沒有任何刻度，看起來像「沒有年份」）
   (2) 橫軸補單位說明＋線上各點補數值標籤（PO 反映原本每個點的數字
       只能滑鼠移過去看 <title> tooltip 才看得到——這在手機上完全看
       不到，觸控螢幕沒有 hover 這個手勢，等於數字對手機使用者是隱形
       的。tooltip 保留當桌面版的額外資訊，但不能是唯一的資訊來源）。

   兩個資料源都來自既有情境試算公式的視覺化延伸（見
   app/routers/assets.py::_simulate_asset_scenario() docstring），不是
   前端另外算：
   - `curve`（長期／年）：現在→退休→提領期結束，逐年取點，橫跨整段
     退休生涯（可能長達數十年）。
   - `monthlyCurve`（近期／月）：只有最近 24 個月，逐月取點，方便看
     剛開始那一兩年的建倉節奏跟複利怎麼慢慢累積；超出這個範圍看不到，
     長期趨勢要切回「年」視角。 */

const WIDTH = 640
const HEIGHT = 240
const PAD_L = 8
const PAD_R = 84
const PAD_T = 30
const PAD_B = 24
// 數值標籤（例如「NT$ 21,117,458」）大約寬 90px，兩個標籤中心距離
// 小於這個值就會疊字，用貪婪演算法挑要顯示哪些點的數值時拿來當門檻。
const MIN_VALUE_LABEL_GAP = 90

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

// 從候選索引裡，依序挑出「中心點x座標」彼此至少間隔 MIN_VALUE_LABEL_GAP
// 的一批，避免數值標籤疊在一起看不清楚——不管年/月視角、點數多寡，
// 同一套邏輯都能自動決定要顯示哪幾個點的數字。
function pickSpacedIndices(indices, xAt, minGap) {
  const picked = []
  let lastX = -Infinity
  indices.forEach((i) => {
    const x = xAt(i)
    if (x - lastX >= minGap) {
      picked.push(i)
      lastX = x
    }
  })
  return picked
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

    // 數值標籤：候選是「所有刻度點」再加上退休高峰（常常卡在兩個刻度
    // 中間，不在 ticks 裡），去重排序後用間距篩選——0（現在）跟
    // n-1（結束）一定保留候選，貪婪演算法本身也保證第一個候選必中選。
    const candidates = [...new Set([...ticks, ...(peakVisible ? [splitIdx] : [])])].sort((a, b) => a - b)
    const valueIndices = new Set(pickSpacedIndices(candidates, xAt, MIN_VALUE_LABEL_GAP))
    // 現在／退休／結束三個點語意重要，就算跟前一個選中點太近也一定顯示
    // 數值（寧可稍微擠一點，也不要讓「現在多少錢」這種關鍵數字消失）。
    valueIndices.add(0)
    if (peakVisible) valueIndices.add(splitIdx)
    valueIndices.add(n - 1)

    return { points, n, xAt, yAt, peakVisible, splitIdx, accumPts, withdrawPts, areaPoints, ticks, valueIndices }
  }, [points, retireIdx])

  if (!chart) {
    return <p className="empty">情境試算欄位還沒有可推演的資料，請先在下方情境試算表單送出一次試算。</p>
  }

  const { points: pts, n, xAt, yAt, peakVisible, splitIdx, accumPts, withdrawPts, areaPoints, ticks, valueIndices } = chart

  return (
    <>
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

        {/* 一般刻度點的數值標籤（現在/退休/結束三個特殊點不在這裡畫，
            下面各自有專屬標籤，避免同一個點疊出兩組文字）。 */}
        {[...valueIndices].map((i) => {
          if (i === 0 || i === n - 1 || (peakVisible && i === splitIdx)) return null
          return (
            <text key={`val-${i}`} x={xAt(i).toFixed(1)} y={(yAt(pts[i].amount) - 8).toFixed(1)}
              className="chart-label" textAnchor="middle">
              {fmtMoney(pts[i].amount)}
            </text>
          )
        })}

        {/* 「現在」：文字＋數值兩行都獨立標在第一個點上方，不是塞進底下
            的軸刻度文字——避免文字太長跟緊接在後面的刻度重疊。 */}
        <text x={xAt(0).toFixed(1)} y={(yAt(pts[0].amount) - 20).toFixed(1)} className="chart-label" textAnchor="start">
          現在
        </text>
        <text x={xAt(0).toFixed(1)} y={(yAt(pts[0].amount) - 8).toFixed(1)} className="chart-label chart-label-total" textAnchor="start">
          {fmtMoney(pts[0].amount)}
        </text>
        <circle cx={xAt(0).toFixed(1)} cy={yAt(pts[0].amount).toFixed(1)} r="3.4" fill="var(--accent)">
          <title>{labelAt(0)}（現在）　{fmtMoney(pts[0].amount)}</title>
        </circle>

        {peakVisible && (
          <>
            <circle cx={xAt(splitIdx).toFixed(1)} cy={yAt(pts[splitIdx].amount).toFixed(1)} r="4.2" fill="var(--accent)">
              <title>{labelAt(splitIdx)}（退休）　{fmtMoney(pts[splitIdx].amount)}</title>
            </circle>
            <text x={xAt(splitIdx).toFixed(1)} y={(yAt(pts[splitIdx].amount) - 20).toFixed(1)}
              className="chart-label chart-label-peak" textAnchor="middle">
              退休 {labelAt(splitIdx)}
            </text>
            <text x={xAt(splitIdx).toFixed(1)} y={(yAt(pts[splitIdx].amount) - 8).toFixed(1)}
              className="chart-label chart-label-peak" textAnchor="middle">
              {fmtMoney(pts[splitIdx].amount)}
            </text>
          </>
        )}

        <circle cx={xAt(n - 1).toFixed(1)} cy={yAt(pts[n - 1].amount).toFixed(1)} r="3" fill="var(--ink-dim)">
          <title>{labelAt(n - 1)}　{fmtMoney(pts[n - 1].amount)}</title>
        </circle>
        <text x={xAt(n - 1).toFixed(1)} y={(yAt(pts[n - 1].amount) - 8).toFixed(1)}
          className="chart-label chart-label-end" textAnchor="end">
          {fmtMoney(pts[n - 1].amount)}
        </text>
      </svg>
      <p className="meta">橫軸單位：{isMonth ? '年-月（近期24個月）' : '西元年'}</p>
    </>
  )
}
