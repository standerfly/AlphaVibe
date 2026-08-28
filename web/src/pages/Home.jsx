import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../api/client.js'

/* 首頁：GET /api/dashboard（今日重點／今日新候選／策略設定）＋
   GET /api/holdings?filter=holdings（追蹤中檔數／需留意數量）。
   兩支各自獨立 fetch、各自的 loading/error 不互相卡住（其中一支失敗
   不影響另一支正常區塊顯示）。欄位名稱逐一對照
   app/routers/dashboard.py／holdings.py 實際回傳結構，不臆測欄位。 */

function fmtPct(v) {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—'
}
function fmtNum(v) {
  return v != null ? v.toFixed(2) : '—'
}
/* 對照 poc/kb-mcp/report.py::_fmt_num()（`"%g" % value`）：去掉多餘小數位
   （1.0→"1"、0.4→"0.4"），同時用 toFixed(6) 先收斂浮點數誤差（例如
   0.29*100 在 JS 是 28.999999999999996），避免策略門檻文字出現長串小數。 */
function trimNum(v) {
  return Number(v.toFixed(6)).toString()
}

/* 對照 poc/kb-mcp/report.py::_format_condition_text()（report.py:2326-2354）：
   同一套「任一門檻為 null 就省略該子句、全部為 null 回傳『不限條件』」邏輯，
   只是回傳純文字（JSX 文字節點本來就會安全跳脫，不需要 report.py 那邊
   `&gt;=` 這類 HTML entity 寫法）。逐框架動態組字，不寫死目前兩個框架的
   文案，未來 frameworks.py 新增框架不用改這裡。 */
function formatConditionText(fw) {
  const clauses = []
  if (fw.peg_max != null) clauses.push(`PEG<${trimNum(fw.peg_max)}`)
  if (fw.revenue_yoy_min != null) clauses.push(`營收年增率>=${trimNum(fw.revenue_yoy_min * 100)}%`)
  if (fw.drawdown_min != null && fw.drawdown_max != null) {
    clauses.push(`回檔${trimNum(fw.drawdown_min * 100)}%~${trimNum(fw.drawdown_max * 100)}%`)
  } else if (fw.drawdown_min != null) {
    clauses.push(`回檔>=${trimNum(fw.drawdown_min * 100)}%`)
  } else if (fw.drawdown_max != null) {
    clauses.push(`回檔<=${trimNum(fw.drawdown_max * 100)}%`)
  }
  if (fw.excess_drawdown_min != null) clauses.push(`超額跌幅>=${trimNum(fw.excess_drawdown_min * 100)}%`)
  return clauses.length ? clauses.join(' 且') : '不限條件'
}

/* 對照 report.py::_invalidation_text()（report.py:681-705）：invalidation
   欄位缺席或全部子條件皆為 null 時回傳提示文字，跟 report.py 的呼叫端
   `_invalidation_text(...) or "尚未定義策略專屬檢視規則"` 邏輯一致。 */
function formatInvalidationText(invalidation) {
  const clauses = []
  if (invalidation) {
    if (invalidation.peg_min != null) clauses.push(`PEG回升至>=${trimNum(invalidation.peg_min)}`)
    if (invalidation.drawdown_max != null) clauses.push(`回檔收斂至<${trimNum(invalidation.drawdown_max * 100)}%`)
    if (invalidation.revenue_yoy_max != null) clauses.push(`營收年增率降至<=${trimNum(invalidation.revenue_yoy_max * 100)}%`)
  }
  return clauses.length ? '假說失效：' + clauses.join('，或') : '尚未定義策略專屬檢視規則'
}

export default function Home() {
  const [dashboard, setDashboard] = useState(null)
  const [dashboardError, setDashboardError] = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [holdingsError, setHoldingsError] = useState(null)
  const [pendingVerifications, setPendingVerifications] = useState(null)
  const [pendingVerificationsError, setPendingVerificationsError] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/api/dashboard')
      .then((data) => { if (!cancelled) setDashboard(data) })
      .catch((err) => { if (!cancelled) setDashboardError(err.message) })
    apiGet('/api/holdings?filter=holdings')
      .then((data) => { if (!cancelled) setHoldings(data) })
      .catch((err) => { if (!cancelled) setHoldingsError(err.message) })
    /* 待觀察／待查詢清單（specs/001-pending-verification-list/）：獨立
       fetch，跟上面兩支一樣互不阻塞——這支失敗不該讓「今日重點」等
       既有區塊跟著不能顯示，反之亦然。唯讀顯示，沒有就地操作
       （pre-spec Q-003a：登記/標記解決一律走 Claude／MCP tool）。 */
    apiGet('/api/pending-verifications?due_only=true')
      .then((data) => { if (!cancelled) setPendingVerifications(data) })
      .catch((err) => { if (!cancelled) setPendingVerificationsError(err.message) })
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

      <h2>今日新候選</h2>
      {dashboardError && <div className="error-box">今日新候選載入失敗：{dashboardError}</div>}
      {!dashboard && !dashboardError && <div className="loading-box">載入中…</div>}
      {dashboard && dashboard.today_new_candidates.length === 0 && (
        <p className="empty">目前沒有符合任何策略門檻的候選。</p>
      )}
      {dashboard && dashboard.today_new_candidates.length > 0 && (
        <div>
          <p className="meta">共 {dashboard.today_new_candidates.length} 檔</p>
          <div className="preview-table-wrap">
            <table className="preview-table">
              <thead>
                <tr>
                  <th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>
                  <th>符合策略</th><th>PER</th><th>營收年增率</th><th>PEG</th>
                  <th>回檔幅度</th><th>現價</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.today_new_candidates.map((r) => (
                  <tr key={r.code}>
                    <td>{r.code}</td>
                    <td>{r.name || '—'}</td>
                    <td>{r.market || '—'}</td>
                    <td>{r.industry || '—'}</td>
                    <td>
                      {r.matched_frameworks.map((label) => (
                        <span key={label} className="tag">{label}</span>
                      ))}
                    </td>
                    <td>{fmtNum(r.per)}</td>
                    <td>{fmtPct(r.revenue_yoy)}</td>
                    <td>{fmtNum(r.peg)}</td>
                    <td>{fmtPct(r.drawdown_pct)}</td>
                    <td>{r.current_price != null ? r.current_price : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <h2>策略設定</h2>
      {dashboardError && <div className="error-box">策略設定載入失敗：{dashboardError}</div>}
      {!dashboard && !dashboardError && <div className="loading-box">載入中…</div>}
      {dashboard && dashboard.strategy_settings.map((fw) => (
        <details key={fw.id} className="collapse">
          <summary>{fw.label}</summary>
          <div style={{ marginTop: '.5rem' }}>篩選門檻：{formatConditionText(fw)}</div>
          <div className="meta" style={{ marginTop: '.3rem' }}>{formatInvalidationText(fw.invalidation)}</div>
        </details>
      ))}
      {dashboard && (
        <p className="form-note" style={{ marginTop: '.6rem' }}>
          策略不是填表單做出來的——先跟AI討論你觀察到的操作邏輯，定案後由AI把篩選門檻＋
          專屬檢視規則寫進 frameworks.py，你只需要確認結果。
        </p>
      )}

      <h2>待驗證清單</h2>
      {pendingVerificationsError && (
        <div className="error-box">待驗證清單載入失敗：{pendingVerificationsError}</div>
      )}
      {!pendingVerifications && !pendingVerificationsError && (
        <div className="loading-box">載入中…</div>
      )}
      {pendingVerifications && pendingVerifications.items.length === 0 && (
        <p className="empty">目前沒有已到期或即將到期的待驗證項目。</p>
      )}
      {pendingVerifications && pendingVerifications.items.length > 0 && (
        <div>
          {pendingVerifications.items.map((item) => (
            <div key={item.id} className="finding">
              <div className="finding__stripe" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="finding__label-row">
                  {item.code && <span className="badge badge-neutral">{item.code}</span>}
                  {item.theme && <span className="badge badge-neutral">{item.theme}</span>}
                  <span className="badge badge-neutral">
                    {item.trigger_date ? `預計 ${item.trigger_date}` : '事件觸發'}
                  </span>
                </div>
                <div className="finding__detail">
                  {item.judgment_text}
                  {item.trigger_condition_text ? `　（觸發條件：${item.trigger_condition_text}）` : ''}
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
