import { useState } from 'react'
import { apiGet } from '../api/client.js'

/* 選股篩選（2026-08-24 新增，Q-046 待辦第3項）：GET /api/screen 的輕量
   前端，貼股票代碼、顯示 PEG／回檔篩選結果。對照舊版
   poc/kb-mcp/report.py:2285-2425（render_screen_form／
   render_screen_results）設計輸入介面與結果呈現，但不照抄 HTML；後端
   app/routers/screen.py 只暴露 `codes` 一個參數（docstring 明講刻意不
   暴露 screener.screen_stocks() 支援但舊路由從未開放的 peg_threshold／
   drawdown_min），這裡也只做這一個輸入欄位，不發明它不支援的參數。

   screen.py 對「codes 為空」不擋（直接回傳空結果讓呼叫端自行決定 UX），
   這裡在前端做最基本的必填檢查，比照舊版表單「請至少輸入一個股票代碼」
   的提示語意。 */

function fmtPct(fraction) {
  // 對照 poc/kb-mcp/report.py _fmt_pct()：去除多餘小數位（40.0→"40"）。
  return Number((fraction * 100).toFixed(2)).toString()
}
function fmtNum(v) {
  return Number(v.toFixed(4)).toString()
}

/* 對照 poc/kb-mcp/report.py _format_condition_text()：把 screen_stocks()
   回傳的 thresholds 區塊組成人看得懂的一句話。/api/screen 目前固定不傳
   peg_threshold／drawdown_min 等覆寫參數，thresholds 理論上永遠是預設值
   （PEG<1 且回檔>=40%），但這裡仍照原始數值動態組字，不寫死文字，避免
   之後後端調整預設值時前端顯示的門檻說明跟著過期。 */
function formatConditionText(thresholds) {
  if (!thresholds) return null
  const clauses = []
  if (thresholds.peg_threshold != null) clauses.push(`PEG<${fmtNum(thresholds.peg_threshold)}`)
  if (thresholds.drawdown_min != null && thresholds.drawdown_max != null) {
    clauses.push(`回檔${fmtPct(thresholds.drawdown_min)}%~${fmtPct(thresholds.drawdown_max)}%`)
  } else if (thresholds.drawdown_min != null) {
    clauses.push(`回檔>=${fmtPct(thresholds.drawdown_min)}%`)
  } else if (thresholds.drawdown_max != null) {
    clauses.push(`回檔<=${fmtPct(thresholds.drawdown_max)}%`)
  }
  if (thresholds.excess_drawdown_min != null) {
    clauses.push(`超額跌幅>=${fmtPct(thresholds.excess_drawdown_min)}%`)
  }
  return clauses.length ? clauses.join(' 且') : '不限條件'
}

const PER_FMT = (v) => (v != null ? v.toFixed(2) : '—')
const PCT_FMT = (v) => (v != null ? `${(v * 100).toFixed(1)}%` : '—')

export default function ScreenPanel() {
  const [codesText, setCodesText] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [formError, setFormError] = useState(null)

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = codesText.trim()
    if (!trimmed) {
      setFormError('請至少輸入一個股票代碼')
      return
    }
    setFormError(null)
    setLoading(true)
    const params = new URLSearchParams({ codes: trimmed })
    apiGet(`/api/screen?${params.toString()}`)
      .then((d) => setData(d))
      .catch((err) => setFormError(err.message))
      .finally(() => setLoading(false))
  }

  const rows = data && !data.error ? (data.results || []) : []
  const hitCount = rows.filter((r) => r.meets_framework).length
  const conditionText = data ? formatConditionText(data.thresholds) : null

  return (
    <div>
      <div className="card">
        <div className="card__head"><h2>選股篩選</h2></div>
        <div className="card__body">
          <p className="form-note">
            篩選條件固定為 PEG（本益成長比）&lt;1 且股價從近 120 天高點回檔 &gt;=40%——股價
            大幅回檔常代表市場情緒過度悲觀，但只有在營收仍是正成長時，這種下跌才比較可能是
            錯殺而非基本面真的變差；PEG&lt;1 則是拿本益比對比成長率，找出相對估值便宜的標的。
            供應鏈敘事是否成立仍需人工確認，篩出來的候選不代表可以直接買。
          </p>
          <form onSubmit={handleSubmit}>
            <div className="form-field">
              <label htmlFor="screen-codes">股票代碼（逗號或換行分隔，一次最多 50 檔）</label>
              <textarea
                id="screen-codes"
                rows="4"
                placeholder="3485,6953,6719"
                value={codesText}
                onChange={(e) => setCodesText(e.target.value)}
              />
            </div>
            <div className="form-actions">
              <button type="submit" className="btn" disabled={loading}>
                {loading ? '篩選中…' : '開始篩選'}
              </button>
            </div>
            {formError && <div className="error-box">{formError}</div>}
          </form>
        </div>
      </div>

      {loading && <div className="loading-box">篩選中…</div>}

      {!loading && data === null && !formError && (
        <p className="empty">貼上股票代碼後按「開始篩選」查看結果。</p>
      )}

      {!loading && data && data.error && <div className="error-box">{data.error}</div>}

      {!loading && data && !data.error && (
        <div className="card">
          <div className="card__head">
            <h2>篩選結果</h2>
            <span className="card__meta">共 {data.total ?? rows.length} 檔</span>
          </div>
          <div className="card__body">
            {rows.length === 0 && <p className="empty">沒有輸入任何代碼。</p>}
            {rows.length > 0 && (
              <>
                <p className="meta">
                  符合框架{conditionText ? `（${conditionText}）` : ''} {hitCount} 檔
                </p>
                <div className="preview-table-wrap">
                  <table className="preview-table">
                    <thead>
                      <tr>
                        <th>代碼</th><th>名稱</th><th>PER</th><th>營收年增率</th>
                        <th>PEG</th><th>回檔幅度</th><th>超額跌幅</th><th>目前價</th>
                        <th>符合框架</th><th>備註</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.code}>
                          <td>{r.code}</td>
                          <td>{r.name || '—'}</td>
                          <td>{PER_FMT(r.per)}</td>
                          <td>{PCT_FMT(r.revenue_yoy)}</td>
                          <td>{r.peg != null ? r.peg.toFixed(2) : '—'}</td>
                          <td>{PCT_FMT(r.drawdown_pct)}</td>
                          <td>{PCT_FMT(r.excess_drawdown_pct)}</td>
                          <td>{r.current_price != null ? r.current_price : '—'}</td>
                          <td>
                            {r.meets_framework
                              ? <span className="badge badge-danger">符合</span>
                              : <span className="badge badge-neutral">—</span>}
                          </td>
                          <td>{r.error || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
