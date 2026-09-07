import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiDelete, apiGet, apiPost } from '../api/client.js'
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

/* 「關注條件」卡片（Phase 5 US3，T029）用的小工具函式。三態 pill 沿用
   既有 .pill.ok/.pill.alert/.pill.pending 樣式（見 StockDetail.jsx
   earnedPill 的同一套語言：ok=綠／alert=紅／pending=灰對應「資料不足」，
   不是發明新配色）。「未更新（無額度）」是疊加在 pill 旁的獨立文字
   標記，不是 pill 本身的第四種顏色——data-model.md §3 明確說 is_stale
   跟 status 是兩個獨立欄位，status 在 is_stale 時仍維持上一次成功評估
   的值，UI 上也該分開呈現，不要把兩件事混進同一個視覺元素。 */
const WATCH_STATUS_PILL = { ok: 'ok', alert: 'alert', insufficient_data: 'pending' }
const WATCH_STATUS_LABEL = { ok: '未觸發', alert: '已觸發', insufficient_data: '資料不足' }
const METRIC_TYPE_LABEL = { price: '股價', gaap_gross_margin: '毛利率', revenue_yoy: '營收年增率' }
const COMPARATOR_LABEL = { lt: '小於', gt: '大於' }

function watchConditionText(c) {
  return `${METRIC_TYPE_LABEL[c.metric_type] || c.metric_type} ${COMPARATOR_LABEL[c.comparator] || c.comparator} ${c.threshold}`
}

export default function UsStockDetail() {
  const { ticker } = useParams()
  const [priceHistory, setPriceHistory] = useState(null)
  const [ledger, setLedger] = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [stanceData, setStanceData] = useState(null)
  const [watchConditions, setWatchConditions] = useState(null)
  const [error, setError] = useState(null)
  const [noteExpanded, setNoteExpanded] = useState(false)

  // 關注條件新增表單狀態（Phase 5 US3，T029）——獨立於上面「頁面資料
  // 是否載入完成」的狀態，表單本身的送出/錯誤不該擋住其餘卡片顯示。
  const [newMetricType, setNewMetricType] = useState('price')
  const [newComparator, setNewComparator] = useState('lt')
  const [newThreshold, setNewThreshold] = useState('')
  const [watchBusy, setWatchBusy] = useState(false)
  const [watchError, setWatchError] = useState(null)

  function refreshWatchConditions() {
    return apiGet(`/api/us-stocks/watch-conditions?ticker=${encodeURIComponent(ticker)}`)
      .then((d) => setWatchConditions(d.conditions))
  }

  useEffect(() => {
    let cancelled = false
    setPriceHistory(null)
    setLedger(null)
    setHoldings(null)
    setStanceData(null)
    setWatchConditions(null)
    setError(null)
    setNoteExpanded(false)
    Promise.all([
      apiGet(`/api/us-stocks/price-history?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/trades?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/holdings?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/stance?ticker=${encodeURIComponent(ticker)}`),
      apiGet(`/api/us-stocks/watch-conditions?ticker=${encodeURIComponent(ticker)}`),
    ]).then(([ph, tr, hd, st, wc]) => {
      if (cancelled) return
      setPriceHistory(ph)
      setLedger(tr)
      setHoldings(hd)
      setStanceData(st)
      setWatchConditions(wc.conditions)
    }).catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [ticker])

  async function handleAddWatchCondition(e) {
    e.preventDefault()
    if (!newThreshold) return
    setWatchBusy(true)
    setWatchError(null)
    try {
      await apiPost('/api/us-stocks/watch-conditions', {
        ticker, metric_type: newMetricType, comparator: newComparator,
        threshold: Number(newThreshold),
      })
      setNewThreshold('')
      await refreshWatchConditions()
    } catch (err) {
      setWatchError(err.message)
    } finally {
      setWatchBusy(false)
    }
  }

  async function handleDeleteWatchCondition(id) {
    setWatchBusy(true)
    setWatchError(null)
    try {
      await apiDelete(`/api/us-stocks/watch-conditions/${id}`)
      await refreshWatchConditions()
    } catch (err) {
      setWatchError(err.message)
    } finally {
      setWatchBusy(false)
    }
  }

  const loaded = priceHistory && ledger && holdings && stanceData && watchConditions
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

          {/* 「關注條件」卡片（Phase 5 US3，T029）：三態 pill（未觸發/
              已觸發/資料不足）＋「未更新（無額度）」疊加標記，見上方
              watchConditionText／WATCH_STATUS_* 常數區塊的取捨說明。
              新增表單直接呼叫 REST 端點（不透過 Claude 對話），理由見
              app/routers/us_stocks.py 檔頭 docstring。 */}
          <section className="card">
            <div className="card__head">
              <h2>關注條件</h2>
              <span className="card__meta">
                {watchConditions.length > 0 ? `${watchConditions.length} 項` : '尚無設定'}
              </span>
            </div>
            <div className="card__body">
              {watchConditions.length === 0 && (
                <p className="empty">尚無監控門檻，可在下方新增。</p>
              )}
              {watchConditions.map((c) => (
                <div className="trade-row" key={c.id}>
                  <span className={'pill ' + (WATCH_STATUS_PILL[c.status] || 'pending')}>
                    {WATCH_STATUS_LABEL[c.status] || c.status}
                  </span>
                  <span className="trade-row__mid">{watchConditionText(c)}</span>
                  {c.is_stale && (
                    <span className="meta" title="last_evaluated_at 不是今天，額度用盡跳過時維持上一次的狀態">
                      未更新（無額度）
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn-muted btn-sm"
                    disabled={watchBusy}
                    onClick={() => handleDeleteWatchCondition(c.id)}
                  >
                    刪除
                  </button>
                </div>
              ))}

              <form onSubmit={handleAddWatchCondition} className="form-actions" style={{ marginTop: '.8rem', flexWrap: 'wrap' }}>
                <select value={newMetricType} onChange={(e) => setNewMetricType(e.target.value)}>
                  <option value="price">股價</option>
                  <option value="gaap_gross_margin">毛利率</option>
                  <option value="revenue_yoy">營收年增率</option>
                </select>
                <select value={newComparator} onChange={(e) => setNewComparator(e.target.value)}>
                  <option value="lt">小於</option>
                  <option value="gt">大於</option>
                </select>
                <input
                  type="number" step="any" placeholder="門檻數值" value={newThreshold}
                  onChange={(e) => setNewThreshold(e.target.value)}
                  style={{
                    width: '8rem', border: '1px solid var(--rule)', borderRadius: '4px',
                    background: 'var(--paper)', color: 'var(--ink)', font: 'inherit',
                    fontSize: '.82rem', padding: '.25rem .35rem',
                  }}
                />
                <button type="submit" className="btn" disabled={watchBusy || !newThreshold}>
                  {watchBusy ? '處理中…' : '新增監控條件'}
                </button>
              </form>
              {watchError && <div className="error-box" style={{ marginTop: '.5rem' }}>{watchError}</div>}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
