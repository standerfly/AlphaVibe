import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../api/client.js'

/* 首頁：GET /api/dashboard（今日重點／今日新候選數量）＋
   GET /api/holdings?filter=holdings（追蹤中檔數／需留意數量）。
   兩支各自獨立 fetch、各自的 loading/error 不互相卡住（其中一支失敗
   不影響另一支正常區塊顯示）。欄位名稱逐一對照
   app/routers/dashboard.py／holdings.py 實際回傳結構，不臆測欄位。 */
export default function Home() {
  const [dashboard, setDashboard] = useState(null)
  const [dashboardError, setDashboardError] = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [holdingsError, setHoldingsError] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/api/dashboard')
      .then((data) => { if (!cancelled) setDashboard(data) })
      .catch((err) => { if (!cancelled) setDashboardError(err.message) })
    apiGet('/api/holdings?filter=holdings')
      .then((data) => { if (!cancelled) setHoldings(data) })
      .catch((err) => { if (!cancelled) setHoldingsError(err.message) })
    return () => { cancelled = true }
  }, [])

  const concernCount = holdings
    ? holdings.results.filter((r) => r.has_concern).length
    : null

  return (
    <div>
      <div className="page-title">
        <h1>首頁</h1>
        {dashboard && <span className="meta">資料更新於 {dashboard.generated_at}</span>}
      </div>

      <div className="stat-row">
        <div className="stat-tile">
          <div className="stat-tile__label">追蹤中檔數</div>
          <div className="stat-tile__value">
            {holdings ? holdings.holdings_count : '—'}
          </div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile__label">需留意檔數</div>
          <div className={'stat-tile__value' + (concernCount ? ' is-attention' : '')}>
            {concernCount === null ? '—' : concernCount}
          </div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile__label">今日新候選</div>
          <div className="stat-tile__value">
            {dashboard ? dashboard.today_new_candidates.length : '—'}
          </div>
        </div>
      </div>

      <h2>今日重點</h2>
      {dashboardError && <div className="error-box">今日重點載入失敗：{dashboardError}</div>}
      {!dashboard && !dashboardError && <div className="loading-box">載入中…</div>}
      {dashboard && dashboard.today_highlights.length === 0 && (
        <p className="empty">今日無需特別留意的標的。</p>
      )}
      {dashboard && dashboard.today_highlights.length > 0 && (
        <div>
          {dashboard.today_highlights.map((h) => (
            <div key={h.id} className={'finding' + (h.conflict_flag ? ' alert' : ' ok')}>
              <div className="finding__stripe" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="finding__label-row">
                  <Link to={`/dashboard/${h.code}`} className="finding__label">
                    {h.code}
                  </Link>
                  <span className="badge badge-neutral">{h.type}</span>
                  <span className="badge badge-neutral">{h.trigger_label || h.trigger_type}</span>
                  {h.conflict_flag && <span className="badge badge-danger">立場衝突</span>}
                </div>
                <div className="finding__detail">
                  {h.finding}{h.suggested_action ? `　→ ${h.suggested_action}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <h2>資產總覽</h2>
      <div className="placeholder-box">
        <div className="placeholder-box__title">資產分頁尚未啟用</div>
        <div className="placeholder-box__text">
          資產總額目前沒有資料來源，這裡不顯示任何數字，避免看到不存在的假資料。
          資產分頁的完整功能（口袋／帳戶自訂清單、建倉進度、情境試算）將於下一步開發。
        </div>
      </div>
    </div>
  )
}
