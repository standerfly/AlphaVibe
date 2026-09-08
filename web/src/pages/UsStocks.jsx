import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../api/client.js'

/* 美股分頁 landing 頁：持股清單＋現價＋漲跌（Phase 3 US1，T019）；
   Phase 5（US3，T030）補上立場摘要＋監控觸發狀態欄位，完成完整版
   landing 頁。

   串接 GET /api/us-stocks/watchlist（app/routers/us_stocks.py），完全
   獨立於既有台股 /api/holdings、/api/dashboard 等端點（FR-015/016）。
   T030 起該端點改用四表聯集（含純觀察中、尚無交易的股票，spec.md Edge
   Cases），所以這裡不能假設每一列都有 shares_held > 0。
   視覺沿用既有 .stock-list/.stock-row 系列樣式（見
   web/src/styles/tokens.css），跟 Dashboard.jsx 的清單卡視覺一致，不
   發明新的排版語言；監控狀態 pill／立場徽章沿用 UsStockDetail.jsx 同一
   套 WATCH_STATUS_*／direction-badge 視覺語言，不重新發明一套配色。 */

function money(v) {
  return v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
}
function pct(v) {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

const DIRECTION_LABEL = { bullish: '偏多', bearish: '偏空', neutral: '觀望' }
const WATCH_STATUS_PILL = { ok: 'ok', alert: 'alert', insufficient_data: 'pending' }
const WATCH_STATUS_LABEL = { ok: '未觸發', alert: '已觸發', insufficient_data: '資料不足' }

export default function UsStocks() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/api/us-stocks/watchlist')
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [])

  const rows = data ? data.watchlist : null

  return (
    <div>
      <div className="page-title">
        <h1>美股</h1>
        <Link to="/us-stocks/import" className="btn">交易匯入核對</Link>
      </div>

      {error && <div className="error-box">載入失敗：{error}</div>}
      {!rows && !error && <div className="loading-box">載入中…</div>}

      {rows && rows.length === 0 && (
        <div className="placeholder-box">
          <div className="placeholder-box__title">尚無美股交易紀錄</div>
          <div className="placeholder-box__text">
            把交易截圖貼給 Claude，Claude 讀圖轉文字後會呼叫
            parse_and_save_us_trade 存成紀錄；存好後可以到
            「交易匯入核對」頁面檢視/修正。
          </div>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="stock-list">
          {rows.map((r) => (
            <Link to={`/us-stocks/${r.ticker}`} className="stock-row" key={r.ticker}>
              <div className="stock-row__id">
                <div className="stock-row__name-line">
                  <span className="stock-row__name">{r.ticker}</span>
                  {r.stance_direction && (
                    <span className={'direction-badge ' + r.stance_direction}>
                      {DIRECTION_LABEL[r.stance_direction] || r.stance_direction}
                    </span>
                  )}
                  {r.watch_status && (
                    <span className={'pill ' + (WATCH_STATUS_PILL[r.watch_status] || 'pending')}>
                      {WATCH_STATUS_LABEL[r.watch_status] || r.watch_status}
                    </span>
                  )}
                  {r.is_stale && <span className="meta">未更新（無額度）</span>}
                </div>
                <div className="stock-row__sub">
                  持股 {r.shares_held} 股｜均價 {money(r.avg_cost)}
                  {r.stance_summary ? `｜${r.stance_summary}` : ''}
                </div>
              </div>
              <div className="stock-row__price">
                <div className="stock-row__now">{money(r.current_price)}</div>
                {r.price_change_pct != null && (
                  <div className={'stock-row__delta ' + (r.price_change_pct >= 0 ? 'is-up' : 'is-down')}>
                    {pct(r.price_change_pct)}
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
