import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../api/client.js'

/* 美股分頁 landing 頁（Phase 3 US1，T019）：持股清單＋現價＋漲跌。
   立場摘要／監控觸發狀態欄位刻意留空——那是 Phase 4/5（T024/T030）的
   工作，見 specs/003-us-stocks/tasks.md T019 範圍註記，這裡不假裝有
   這些資料。

   串接 GET /api/us-stocks/watchlist（app/routers/us_stocks.py），完全
   獨立於既有台股 /api/holdings、/api/dashboard 等端點（FR-015/016）。
   視覺沿用既有 .stock-list/.stock-row 系列樣式（見
   web/src/styles/tokens.css），跟 Dashboard.jsx 的清單卡視覺一致，不
   發明新的排版語言。 */

function money(v) {
  return v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
}
function pct(v) {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

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
                </div>
                <div className="stock-row__sub">
                  持股 {r.shares_held} 股｜均價 {money(r.avg_cost)}
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
