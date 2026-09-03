import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client.js'

/* 市場掃描（2026-08-24 新增，Q-046 待辦第3項）：GET /api/market-scan 的
   輕量前端。對照舊版 poc/kb-mcp/report.py:2428-2555
   （render_market_scan_page）設計版面（符合框架的候選預設展開、全部候選
   收合），但**刻意不遷移「立即掃描」按鈕**：app/routers/market_scan.py
   開頭 docstring 已查證這支 GET 端點只讀 market_scan_runs／
   market_scan_results 兩張表既有資料，不會現場觸發新的批次運算——真正
   產生掃描結果的是每天 02:00 的 com.alphavibe.marketscan 排程（獨立
   job，這次任務範圍明確要求不得碰）。因此這裡呈現成「顯示最近一次掃描
   結果＋掃描時間」，沒有任何按鈕會讓使用者誤以為按下去會現場重新掃描
   全市場。

   框架下拉選單的 (id, label) 選項來自 GET /api/dashboard 的
   strategy_settings 欄位（= poc/kb-mcp/frameworks.py 的 FRAMEWORKS 原始
   清單，app/routers/dashboard.py 已公開這個既有端點）——重用它純粹是為
   了取得框架 id→label 對照表，不在前端另外寫死一份容易跟後端 frameworks.py
   漂移的清單。這個端點同時回傳 today_highlights／today_new_candidates
   兩個這裡用不到的區塊，但都只是既有 sqlite 資料的讀取組裝，沒有外部
   API 呼叫，換取「框架清單不必在前端另存一份」划算。 */

function fmtPct(v) {
  return v != null ? `${(v * 100).toFixed(2)}%` : '—'
}
function fmtNum(v) {
  return v != null ? v.toFixed(2) : '—'
}

const TRIGGER_LABEL = { manual: '手動觸發', scheduled: '排程自動' }

/* 興櫃候選的 PER/PEG 精確度低於正式上市/上櫃股（半年報/年報EPS，非TTM，
   估算股數），這裡跟 report.py `_market_scan_row_html()` 同一套邏輯——
   備註欄一律標明，不能讓使用者誤以為興櫃候選跟上市/上櫃一樣可信
   （roadmap.md 明文要求；2026-09-03 補齊興櫃篩選缺口時一併同步兩邊
   前端，避免只改 SSR 版）。跟既有 r.error 並存時兩者都顯示。 */
function noteFor(r) {
  const parts = []
  if (r.market === '興櫃') {
    parts.push('興櫃估值為粗估（半年報/年報EPS，非TTM），精確度低於上市/上櫃')
  }
  if (r.error) {
    parts.push(r.error)
  }
  return parts.length > 0 ? parts.join('；') : '—'
}

/* 「加入追蹤」按鈕（可選加分項）：直接呼叫 PR#9 已做好的
   POST /api/watchlist（QuickInputPanel.jsx 的 WatchlistForm 用同一個
   端點），語意等同舊版 report.py `_market_scan_track_form_html()`／
   `POST /market-scan/track`——但這裡不重現舊版「reason 由伺服器端重新
   查資料庫現算」那段複雜邏輯（compose_market_scan_track_reason()，
   /market-scan/track 從未被遷移到 app/），單純以「觀察」立場加入自選股，
   跟投資分頁「加自選股」表單的效果完全一致，是刻意縮小的範圍（見任務
   回報的取捨說明）。 */
function TrackButton({ code, name }) {
  const [state, setState] = useState('idle') // idle | busy | done | conflict | error
  const [msg, setMsg] = useState(null)

  async function handleClick() {
    setState('busy')
    try {
      const res = await apiPost('/api/watchlist', { code, name: name || undefined })
      if (res.conflict) {
        setState('conflict')
        setMsg(res.hint || '已有不同立場紀錄，未覆寫')
      } else {
        setState('done')
      }
    } catch (err) {
      setState('error')
      setMsg(err.message)
    }
  }

  if (state === 'done') return <span className="badge badge-positive">已加入</span>

  return (
    <div>
      <button
        type="button"
        className="btn-sm btn-muted"
        disabled={state === 'busy'}
        onClick={handleClick}
      >
        {state === 'busy' ? '加入中…' : '加入追蹤'}
      </button>
      {(state === 'conflict' || state === 'error') && (
        <div className="stock-row__reason" title={msg}>{msg}</div>
      )}
    </div>
  )
}

function ResultsTable({ rows, showTrack }) {
  return (
    <div className="preview-table-wrap">
      <table className="preview-table">
        <thead>
          <tr>
            <th>代碼</th><th>名稱</th><th>市場</th><th>產業別</th>
            <th>PER</th><th>營收年增率</th><th>PEG</th><th>回檔幅度</th>
            <th>超額跌幅</th><th>PBR</th><th>殖利率</th><th>目前價</th>
            <th>符合框架</th><th>備註</th>
            {showTrack && <th>加入追蹤</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code}>
              <td>{r.code}</td>
              <td>{r.name || '—'}</td>
              <td>{r.market || '—'}</td>
              <td>{r.industry || '—'}</td>
              <td>{fmtNum(r.per)}</td>
              <td>{fmtPct(r.revenue_yoy)}</td>
              <td>{r.peg != null ? r.peg.toFixed(2) : '—'}</td>
              <td>{fmtPct(r.drawdown_pct)}</td>
              <td>{fmtPct(r.excess_drawdown_pct)}</td>
              <td>{fmtNum(r.pbr)}</td>
              <td>{fmtPct(r.dividend_yield)}</td>
              <td>{r.current_price != null ? r.current_price.toFixed(2) : '—'}</td>
              <td>
                {r.meets_framework
                  ? <span className="badge badge-danger">符合</span>
                  : <span className="badge badge-neutral">—</span>}
              </td>
              <td>{noteFor(r)}</td>
              {showTrack && <td><TrackButton code={r.code} name={r.name} /></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function MarketScanPanel() {
  const [frameworkOptions, setFrameworkOptions] = useState([])
  // '' 代表「還沒有使用者明確選過框架」，此時 API 呼叫不帶 framework
  // 參數，讓後端自己 fallback 到 frameworks.default_framework_id()；
  // 選單顯示值改用 activeFrameworkId（見下方），不會因此顯示空白選項。
  const [requestedFramework, setRequestedFramework] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/api/dashboard')
      .then((d) => { if (!cancelled) setFrameworkOptions(d.strategy_settings || []) })
      .catch(() => { /* 拿不到框架清單只影響下拉選單標籤顯示，不擋主要功能 */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const qs = requestedFramework ? `?framework=${encodeURIComponent(requestedFramework)}` : ''
    apiGet(`/api/market-scan${qs}`)
      .then((d) => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [requestedFramework])

  const activeFrameworkId = requestedFramework || (data ? data.framework_id : '')
  const hasKnownOption = frameworkOptions.some((fw) => fw.id === activeFrameworkId)

  return (
    <div>
      <div className="card">
        <div className="card__head"><h2>市場掃描</h2></div>
        <div className="card__body">
          <p className="form-note">
            用 TWSE/TPEx 官方批次資料，在框架鎖定的產業別內自動找候選，涵蓋上市＋上櫃＋興櫃
            （2026-09-03起）。興櫃沒有官方批次PER資料，改用「先篩產業別＋營收年增率、再逐檔
            查估值」補齊，精確度低於上市/上櫃，候選列的備註欄會標明。這裡永遠顯示最近一次
            掃描結果——掃描本身由每天 02:00 排程自動執行，不會因為打開這個頁面而現場重新計算。
          </p>
          <div className="form-field" style={{ maxWidth: '24rem' }}>
            <label htmlFor="scan-framework">框架</label>
            <select
              id="scan-framework"
              value={activeFrameworkId}
              onChange={(e) => setRequestedFramework(e.target.value)}
            >
              {activeFrameworkId && !hasKnownOption && (
                <option value={activeFrameworkId}>{activeFrameworkId}</option>
              )}
              {frameworkOptions.map((fw) => (
                <option key={fw.id} value={fw.id}>{fw.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {loading && <div className="loading-box">載入中…</div>}
      {!loading && error && <div className="error-box">載入失敗：{error}</div>}

      {!loading && !error && data && !data.found && (
        <p className="empty">尚無掃描紀錄，掃描由每天 02:00 排程自動執行，稍後再回來查看。</p>
      )}

      {!loading && !error && data && data.found && (() => {
        const run = data.run
        const results = data.results || []
        const hitRows = results.filter((r) => r.meets_framework)
        return (
          <div className="card">
            <div className="card__head">
              <h2>市場掃描結果</h2>
              <span className="card__meta">{run.run_at}</span>
            </div>
            <div className="card__body">
              <p className="meta">
                {TRIGGER_LABEL[run.trigger_source] || run.trigger_source || '—'}｜
                候選 {run.candidate_count ?? results.length} 檔，
                符合框架 {run.meets_count ?? hitRows.length} 檔
                {run.benchmark_drawdown_pct != null && `｜同期大盤回檔 ${fmtPct(run.benchmark_drawdown_pct)}`}
              </p>

              {(run.twse_error || run.tpex_error || run.emerging_error) && (
                <div className="error-box">
                  {run.twse_error && `TWSE 資料源異常：${run.twse_error}　`}
                  {run.tpex_error && `TPEx 資料源異常：${run.tpex_error}　`}
                  {run.emerging_error && `興櫃資料源異常：${run.emerging_error}`}
                  （該市場當次候選數會變少，不影響其他市場）
                </div>
              )}
              {run.benchmark_error && (
                <div className="error-box">
                  大盤基準資料異常：{run.benchmark_error}
                  （本次「同期大盤回檔」與「超額跌幅」無法計算，不影響其他欄位）
                </div>
              )}

              <div className="group-label">符合框架的候選（{hitRows.length}）</div>
              {hitRows.length === 0
                ? <p className="empty">這次沒有候選同時符合框架門檻，可以到下方「全部候選」查看完整清單。</p>
                : <ResultsTable rows={hitRows} showTrack />}

              <details className="collapse" style={{ marginTop: '.8rem' }}>
                <summary>全部候選（{results.length} 檔，含未達門檻）</summary>
                <div style={{ marginTop: '.6rem' }}>
                  {results.length === 0
                    ? <p className="empty">這次掃描沒有候選（可能兩個資料源都異常，或框架門檻下確實沒有符合的股票）。</p>
                    : <ResultsTable rows={results} showTrack />}
                </div>
              </details>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
