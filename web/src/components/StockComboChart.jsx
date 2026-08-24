import { useMemo } from 'react'

/* 個股詳情頁「走勢與力道」複合圖（2026-08-24，補回 Q-046 待辦第2項）。
   從 poc/kb-mcp/report.py 的 _render_combo_chart_svg()（2026-08-09 完成
   的視覺設計，含兩輪 PO 對照 mockup 的反饋）逐項 port 過來：座標算法、
   均價虛線、交易點＋虛線接力道長條、已平倉淡化＋分隔線，全部保留；
   差別只在輸出從拼接 SVG 字串改成 React 直接產生 SVG 元素，配色改用
   web/src/styles/tokens.css 既有的 CSS var（--accent/--red/--green/
   --amber/--ink-dim/--rule-strong），跟舊版寫死同一組 var() 名稱，
   深淺主題切換不用額外處理，也不新增任何圖表函式庫依賴。

   資料源：app/routers/stock_detail.py 回傳的 holdings.price_history
   （store.get_cached_price_history()，[{date, close}]，依日期升冪）與
   holdings.ledger_entries（store.get_trade_ledger()，[{id, date, action,
   shares, price, ...}]，依日期升冪）。呼叫端（StockDetail.jsx）只在
   ledger_entries 非空時才渲染這個元件——跟舊版 _holdings_card_html()
   的 `if ledger:` 閘門一致：完全沒有交易紀錄時，這裡不畫一張只有價格
   折線、下半部力道區空白的「半殘」圖，維持舊版「沒有交易就不畫這張圖」
   的設計判斷。price_history 資料不足（少於2個有效收盤價）則由本元件
   自己顯示清楚的空狀態文字，不畫出畸形圖。 */

function fmtNum(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Number.isInteger(v)) return String(v)
  return String(Number(v.toPrecision(6)))
}

// x 軸用「第幾個交易日」的整數索引而非真實日曆天數（股價圖常見慣例，
// 週末／休市日不佔版面，折線才不會出現無意義的長平段）。交易日期若剛好
// 不是交易日，往前找最近一個有股價的交易日對齊；早於股價快取起點的
// 交易日對不到，跳過（該筆仍會出現在下方精簡清單，只是圖上畫不出來）。
// 邏輯照搬 report.py::_combo_chart_aligned_trades()。
function alignTrades(prices, entries) {
  const dateIndex = new Map()
  prices.forEach((p, i) => dateIndex.set(p.date, i))
  const sortedDates = Array.from(dateIndex.keys()).sort()
  const aligned = []
  for (const entry of entries) {
    let idx = dateIndex.has(entry.date) ? dateIndex.get(entry.date) : null
    if (idx == null) {
      const earlier = sortedDates.filter((d) => d <= entry.date)
      if (earlier.length === 0) continue
      idx = dateIndex.get(earlier[earlier.length - 1])
    }
    aligned.push({ index: idx, entry })
  }
  return aligned
}

// 已平倉舊紀錄 vs 目前部位的分界：aligned（依日期升冪）裡最後一筆「賣」
// 的位置索引；整份紀錄裡沒有賣出過（單純累積加碼）回傳 -1。邏輯照搬
// report.py::_last_sell_position()。
function lastSellPosition(aligned) {
  let last = -1
  aligned.forEach((a, i) => { if (a.entry.action === '賣') last = i })
  return last
}

const WIDTH = 640
const HEIGHT = 300
// pad_r 留寬給右側高/低/最新價/均價文字標籤（「均價 NNNN」比其他純數字
// 標籤寬，用它決定 pad_r，避免文字被 viewBox 邊界裁掉）；pad_b 留給下方
// 橫軸日期。跟舊版同一組數值。
const PAD_L = 8
const PAD_R = 70
const PAD_T = 10
const PAD_B = 22

export default function StockComboChart({ priceHistory, ledgerEntries, avgCost }) {
  const chart = useMemo(() => {
    const prices = priceHistory || []
    const entries = ledgerEntries || []
    const closes = prices.filter((p) => p.close != null).map((p) => p.close)
    if (closes.length < 2) return null

    const lo = Math.min(...closes)
    const hi = Math.max(...closes)
    const span = (hi - lo) || (Math.abs(hi) * 0.02 || 1.0)
    const n = prices.length
    const priceH = HEIGHT * 0.52
    const barH = HEIGHT * 0.22
    const gapH = HEIGHT - PAD_T - priceH - barH - PAD_B
    const barAreaTop = PAD_T + priceH + gapH
    const barBaseY = barAreaTop + barH

    const xAt = (i) => PAD_L + (WIDTH - PAD_L - PAD_R) * i / Math.max(n - 1, 1)
    const yPrice = (close) => PAD_T + priceH * (1 - (close - lo) / span)

    const points = prices
      .map((p, i) => (p.close != null ? `${xAt(i).toFixed(1)},${yPrice(p.close).toFixed(1)}` : null))
      .filter(Boolean)
      .join(' ')

    const aligned = alignTrades(prices, entries)
    const boundary = lastSellPosition(aligned)

    // 高／低／最新收盤價／均價文字標籤：均價常跟高/低其中一個很接近
    // （例如接近波段低點承接），y座標算出來太近會疊字看不清楚——收集
    // 全部標籤後統一做最小間距碰撞閃避（由上到下掃一輪，太近的往下
    // 推開），照搬舊版做法。
    const latestEntry = [...prices].reverse().find((p) => p.close != null)
    const latestClose = latestEntry ? latestEntry.close : null
    const labelX = WIDTH - PAD_R + 6
    const labels = [{ y: yPrice(hi), text: fmtNum(hi), cls: 'chart-label' }]
    if (latestClose != null && lo < latestClose && latestClose < hi) {
      labels.push({ y: yPrice(latestClose), text: fmtNum(latestClose), cls: 'chart-label chart-label-latest' })
    }
    const avgInRange = avgCost != null && avgCost >= lo && avgCost <= hi
    if (avgInRange) {
      labels.push({ y: yPrice(avgCost), text: `均價 ${fmtNum(avgCost)}`, cls: 'chart-label chart-label-avg' })
    }
    labels.push({ y: yPrice(lo), text: fmtNum(lo), cls: 'chart-label' })
    labels.sort((a, b) => a.y - b.y)
    const minGap = 11
    for (let i = 1; i < labels.length; i++) {
      if (labels[i].y - labels[i - 1].y < minGap) labels[i].y = labels[i - 1].y + minGap
    }

    const maxValue = aligned.reduce(
      (m, a) => Math.max(m, Math.abs(a.entry.shares * a.entry.price)), 0) || 1.0
    const barW = Math.max(2.0, (WIDTH - PAD_L - PAD_R) / Math.max(n, 1) * 0.6)

    // 圖例（legend）：avgCost 這裡故意用「有沒有值」判斷要不要提示均價
    // 圖例，不是「有沒有畫進圖裡」（avgInRange）——跟舊版 legend 段落同一個
    // 細節差異：均價超出價格區間時虛線不畫，但圖例文字仍會提到「均價」。
    const hasSell = entries.some((e) => e.action === '賣')

    let firstTradeDate = null
    let lastTradeDate = null
    aligned.forEach((a) => {
      if (firstTradeDate == null || a.entry.date < firstTradeDate) firstTradeDate = a.entry.date
      if (lastTradeDate == null || a.entry.date > lastTradeDate) lastTradeDate = a.entry.date
    })

    return {
      points, aligned, boundary, labels, maxValue, barW,
      priceH, barH, barAreaTop, barBaseY, xAt, yPrice,
      avgInRange, avgY: avgInRange ? yPrice(avgCost) : null,
      hasSell, firstTradeDate, lastTradeDate, labelX,
      cacheFrom: prices[0].date, cacheTo: prices[prices.length - 1].date,
    }
  }, [priceHistory, ledgerEntries, avgCost])

  if (!chart) {
    return <p className="empty">尚無足夠資料繪製走勢圖。</p>
  }

  const {
    points, aligned, boundary, labels, maxValue, barW,
    barH, barAreaTop, barBaseY, xAt, yPrice,
    avgInRange, avgY, hasSell, firstTradeDate, lastTradeDate, labelX,
    cacheFrom, cacheTo,
  } = chart

  return (
    <>
      <svg className="combo-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%"
        preserveAspectRatio="xMidYMid meet" role="img" aria-label="價格與買賣力道圖">
        <polyline points={points} fill="none" stroke="var(--accent)"
          strokeWidth="1.8" strokeLinejoin="round" />

        {avgInRange && (
          <line x1={PAD_L} y1={avgY.toFixed(1)} x2={WIDTH - PAD_R} y2={avgY.toFixed(1)}
            stroke="var(--amber)" strokeWidth="1.2" strokeDasharray="5,3" />
        )}

        {labels.map((l, i) => (
          <text key={`label-${i}`} x={labelX} y={(l.y + 4).toFixed(1)} className={l.cls}>{l.text}</text>
        ))}

        {/* 每筆交易的價位點＋往下接到力道長條區的虛線，讓價位跟力道對得起來。
            已平倉舊紀錄（i <= boundary）淡化顯示。 */}
        {aligned.map((a, i) => {
          const x = xAt(a.index)
          const y = yPrice(a.entry.price)
          const color = a.entry.action === '買' ? 'var(--red)' : 'var(--green)'
          const dim = i <= boundary
          return (
            <g key={`pt-${a.entry.id ?? i}`} opacity={dim ? 0.4 : 1}>
              <line x1={x.toFixed(1)} y1={y.toFixed(1)} x2={x.toFixed(1)} y2={barAreaTop.toFixed(1)}
                stroke="var(--rule-strong)" strokeWidth="1" strokeDasharray="2,2" />
              <circle cx={x.toFixed(1)} cy={y.toFixed(1)} r="2.6" fill={color} />
            </g>
          )
        })}

        {/* 買賣力道長條：高度＝該筆交易金額相對這批交易裡金額最大那筆的
            比例，純呈現彼此力道差異，不是相對股價／市值。 */}
        {aligned.map((a, i) => {
          const e = a.entry
          const value = e.shares * e.price
          const bh = barH * Math.min(1, Math.abs(value) / maxValue)
          const color = e.action === '買' ? 'var(--red)' : 'var(--green)'
          const opacity = i <= boundary ? 0.35 : 0.85
          const x = xAt(a.index) - barW / 2
          const y = barBaseY - bh
          return (
            <g key={`bar-${e.id ?? i}`}>
              <rect x={x.toFixed(1)} y={y.toFixed(1)} width={barW.toFixed(1)} height={bh.toFixed(1)}
                fill={color} opacity={opacity}>
                <title>
                  {e.date} {e.action} {fmtNum(e.shares)}股 @{fmtNum(e.price)}
                  {i <= boundary ? '（已平倉舊紀錄）' : ''}
                </title>
              </rect>
              <text x={xAt(a.index).toFixed(1)} y={(y - 4).toFixed(1)} className="chart-bar-label"
                fill={color} opacity={opacity}>{fmtNum(e.shares)}</text>
            </g>
          )
        })}

        {/* 分隔線：最後一筆賣出所在的x位置，貫穿價格區＋力道區，把「已平倉
            舊紀錄」跟「目前部位」在視覺上切開。沒有賣出過就不畫。 */}
        {boundary >= 0 && (
          <line x1={xAt(aligned[boundary].index).toFixed(1)} y1={PAD_T}
            x2={xAt(aligned[boundary].index).toFixed(1)} y2={barBaseY.toFixed(1)}
            stroke="var(--ink-dim)" strokeWidth="1" strokeDasharray="4,3" />
        )}

        {/* 橫軸：基準線＋每筆交易的刻度＋最早/最新交易日期。 */}
        <line x1={PAD_L} y1={barBaseY.toFixed(1)} x2={WIDTH - PAD_R} y2={barBaseY.toFixed(1)}
          stroke="var(--rule-strong)" strokeWidth="1.2" />
        {aligned.map((a, i) => {
          const x = xAt(a.index)
          return (
            <line key={`tick-${a.entry.id ?? i}`} x1={x.toFixed(1)} y1={(barBaseY - 3).toFixed(1)}
              x2={x.toFixed(1)} y2={(barBaseY + 3).toFixed(1)} stroke="var(--ink-dim)" strokeWidth="1" />
          )
        })}
        {firstTradeDate != null && (
          <text x={PAD_L} y={(barBaseY + 16).toFixed(1)} className="chart-label" textAnchor="start">
            {firstTradeDate}
          </text>
        )}
        {lastTradeDate != null && lastTradeDate !== firstTradeDate && (
          <text x={WIDTH - PAD_R} y={(barBaseY + 16).toFixed(1)} className="chart-label" textAnchor="end">
            {lastTradeDate}
          </text>
        )}
      </svg>
      <p className="meta">
        <span style={{ color: 'var(--accent)' }}>●</span> 價格折線
        <span style={{ color: 'var(--red)' }}>●</span> 買進力道
        <span style={{ color: 'var(--green)' }}>●</span> 賣出力道
        {avgCost != null && <><span style={{ color: 'var(--amber)' }}>┄</span> 均價　</>}
        ｜快取範圍 {cacheFrom} ~ {cacheTo}
        {hasSell && '　｜淡色＝已平倉舊紀錄，實色＝目前這批部位'}
      </p>
    </>
  )
}
