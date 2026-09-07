import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiGet } from '../api/client.js'
import { ChevronLeftIcon } from '../components/icons.jsx'
import StockComboChart from '../components/StockComboChart.jsx'
import UsStockResearchNote from '../components/UsStockResearchNote.jsx'

/* 美股個股詳情頁（Phase 3 US1，T018）：股價走勢圖疊加買賣點位，是這個
   User Story 的核心展示畫面（Independent Test：「打開個股詳情頁能看到
   股價線＋買賣點位標記」，見 tasks.md Phase 3 Goal）。

   技術取捨（回報時需要交代的重點）：**直接重用既有 StockComboChart
   元件**，不重寫一份美股版走勢圖——理由：
   1. 該元件的 props 介面（priceHistory: [{date, close}]／
      ledgerEntries: [{id, date, action('買'/'賣'), shares, price}]／
      avgCost: number|null）本身跟股票市場無關，純粹是「時間序列+交易
      標記」的通用繪圖元件，美股資料轉換成同樣形狀即可直接餵。
   2. 「紅漲綠跌/紅買綠賣」是 2026-09-05 對話中 PO 明確決定美股沿用台股
      慣例、不用國際慣例——重用同一個元件等於視覺規則自動保證一致，不用
      另外複製一份色彩判斷邏輯，未來要調整只需要改一處。
   3. 唯一的轉接工作是欄位名稱／action 值映射（見 toPriceHistory／
      toLedgerEntries），對照 app/routers/us_stocks.py 的實際回傳格式：
      - GET /api/us-stocks/price-history 回傳 {history:[{date,
        close_price}]}，元件要的是 {date, close} → 轉 close_price→close
      - GET /api/us-stocks/trades 回傳 {entries:[{id, trade_date,
        action('buy'/'sell'), shares, price}]} → 轉 trade_date→date、
        action 'buy'→'買'/'sell'→'賣'
      - GET /api/us-stocks/holdings 回傳 {avg_cost} → 直接對應 avgCost */

function money(v) {
  return v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function toPriceHistory(history) {
  return (history || []).map((h) => ({ date: h.date, close: h.close_price }))
}

function toLedgerEntries(entries) {
  return (entries || []).map((e) => ({
    id: e.id,
    date: e.trade_date,
    action: e.action === 'buy' ? '買' : '賣',
    shares: e.shares,
    price: e.price,
  }))
}

/* 「投資立場」卡片（Phase 4 US2，T024）用的小工具函式。direction 徽章
   色彩沿用既有 trade-row__tag 的紅買綠賣配色（bullish≈買方向=紅、
   bearish≈賣方向=綠，見 web/src/styles/app.css 對應區塊的取捨說明），
   跟本頁走勢圖「紅漲綠跌/紅買綠賣」是同一套視覺語言，不是另創語意。 */
const DIRECTION_LABEL = { bullish: '偏多', bearish: '偏空', neutral: '觀望' }

function directionLabel(direction) {
  return DIRECTION_LABEL[direction] || direction || '—'
}

function priceBand(low, high) {
  if (low == null && high == null) return '—'
  if (low != null && high != null) return `${money(low)} ~ ${money(high)}`
  return money(low != null ? low : high)
}

export default function UsStockDetail() {
  const { ticker } = useParams()
  const [priceHistory, setPriceHistory] = useState(null)
  const [ledger, setLedger] = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [stanceData, setStanceData] = useState(null)
  const [error, setError] = useState(null)
  const [noteExpanded, setNoteExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setPriceHistory(null)
    setLedger(null)
    setHoldings(null)
    setStanceData(null)
    setError(null)
    setNoteExpanded(false)
    Promise.all([
      apiGet(`/api/us-stocks/price-history?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/trades?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/holdings?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/stance?ticker=${encodeURIComponent(ticker)}`),
    ]).then(([ph, tr, hd, st]) => {
      if (cancelled) return
      setPriceHistory(ph)
      setLedger(tr)
      setHoldings(hd)
      setStanceData(st)
    }).catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [ticker])

  const loaded = priceHistory && ledger && holdings && stanceData
  const ledgerEntries = loaded ? toLedgerEntries(ledger.entries) : []
  const stance = loaded ? stanceData.stance : null

  return (
    <div>
      <Link to="/us-stocks" className="back-link">
        <ChevronLeftIcon width={16} height={16} /> 回美股
      </Link>

      {error && <div className="error-box">載入失敗：{error}</div>}
      {!loaded && !error && <div className="loading-box">載入中…</div>}

      {loaded && (
        <div>
          <div className="detail-header">
            <div>
              <span className="detail-header__name">{ticker}</span>
            </div>
          </div>

          <section className="card">
            <div className="card__head">
              <h2>持股與交易</h2>
              <span className="card__meta">
                {ledgerEntries.length > 0 ? `${ledgerEntries.length} 筆交易` : '尚無交易紀錄'}
              </span>
            </div>
            <div className="card__body">
              <div className="holdings-grid">
                <div className="val-item">
                  <div className="label">持股數</div>
                  <div className="value">{holdings.shares_held}</div>
                </div>
                <div className="val-item">
                  <div className="label">均價</div>
                  <div className="value">{money(holdings.avg_cost)}</div>
                </div>
                <div className="val-item">
                  <div className="label">已實現損益</div>
                  <div className="value">{money(holdings.realized)}</div>
                </div>
              </div>

              {ledgerEntries.length > 0 && (
                <StockComboChart
                  priceHistory={toPriceHistory(priceHistory.history)}
                  ledgerEntries={ledgerEntries}
                  avgCost={holdings.avg_cost}
                />
              )}
              {ledgerEntries.length === 0 && (
                <p className="empty">尚無交易紀錄，無法繪製走勢與力道圖。</p>
              )}

              {ledgerEntries.length > 0 && (
                <details className="trade-list-details" open={ledgerEntries.length <= 5}>
                  <summary>交易流水（{ledgerEntries.length} 筆）</summary>
                  {ledgerEntries.map((e) => (
                    <div className="trade-row" key={e.id}>
                      <span className={'trade-row__tag ' + (e.action === '買' ? 'buy' : 'sell')}>
                        {e.action}
                      </span>
                      <span className="trade-row__mid">{e.shares} 股 @ {e.price}</span>
                      <span className="trade-row__date">{e.date}</span>
                    </div>
                  ))}
                </details>
              )}

              {priceHistory.gap_dates && priceHistory.gap_dates.length > 0 && (
                <p className="meta" style={{ marginTop: '.6rem' }}>
                  資料缺口（{priceHistory.gap_dates.length} 天無報價紀錄，可能是排程當天額度用盡）：
                  {priceHistory.gap_dates.slice(0, 5).join('、')}
                  {priceHistory.gap_dates.length > 5 ? ' …' : ''}
                </p>
              )}
            </div>
          </section>

          {/* 「投資立場」卡片（Phase 4 US2，T024）：direction／bear-base-
              bull 情境價格帶／summary 摘要在卡片主體直接顯示；完整研究
              筆記（full_note）預設收合，展開按鈕點開後渲染 T023 的
              UsStockResearchNote——展開後內容完整呈現，不因為是「展開
              區塊」就順便砍減，FR-009 明確要求呈現時不得因版面密度考量
              省略/壓縮內容。 */}
          <section className="card">
            <div className="card__head">
              <h2>投資立場</h2>
              {stance && <span className="card__meta">建立於 {stance.created_at}</span>}
            </div>
            <div className="card__body">
              {!stance && <p className="empty">尚無投資立場紀錄，跟 Claude 討論後可存入。</p>}
              {stance && (
                <div>
                  <span className={'direction-badge ' + stance.direction}>
                    {directionLabel(stance.direction)}
                  </span>
                  <div className="stance-bands">
                    <div className="val-item">
                      <div className="label">Bear</div>
                      <div className="value">{priceBand(stance.bear_price, stance.bear_price_high)}</div>
                    </div>
                    <div className="val-item">
                      <div className="label">Base</div>
                      <div className="value">{priceBand(stance.base_price_low, stance.base_price_high)}</div>
                    </div>
                    <div className="val-item">
                      <div className="label">Bull</div>
                      <div className="value">{priceBand(stance.bull_price, null)}</div>
                    </div>
                  </div>
                  <p className="stance-summary">{stance.summary}</p>
                  <button
                    type="button"
                    className="btn-muted btn-sm"
                    onClick={() => setNoteExpanded((v) => !v)}
                  >
                    {noteExpanded ? '收合完整研究筆記 ▾' : '展開完整研究筆記 ▸'}
                  </button>
                  {noteExpanded && (
                    <div className="stance-note-toggle">
                      <UsStockResearchNote fullNote={stance.full_note} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
