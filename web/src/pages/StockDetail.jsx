import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiGet } from '../api/client.js'
import { ChevronLeftIcon } from '../components/icons.jsx'

function pct(v, digits = 1) {
  return v == null ? '—' : `${(v * (Math.abs(v) <= 1 ? 100 : 1)).toFixed(digits)}%`
}
function pctRaw(v, digits = 1) {
  // v 已經是百分比數值（非 0~1 小數），例如 current_position_pct。
  return v == null ? '—' : `${v.toFixed(digits)}%`
}
function num(v) {
  return v == null ? '—' : v
}
function money(v) {
  return v == null ? '—' : Math.round(v).toLocaleString('zh-TW')
}

/* 三態 earned 指示：true→ok(綠)／false→alert(紅)／null→pending(灰，
   對應「資料不足，無法判斷」，見 review_engine.auto_score_review
   docstring，不要把 null 誤畫成「沒過」）。*/
function earnedPill(earned) {
  if (earned === true) return <span className="pill ok">符合</span>
  if (earned === false) return <span className="pill alert">未符合</span>
  return <span className="pill pending">資料不足</span>
}

function findingClass(row) {
  if (row.trigger_type === '策略層') return 'ref'
  if (row.trigger_type === '老芋頭動向') return 'pending'
  return row.concern_flag ? 'alert' : 'ok'
}

function pillClass(row) {
  if (row.trigger_type === '策略層') return 'ref'
  if (row.trigger_type === '老芋頭動向') return 'pending'
  return row.concern_flag ? 'alert' : 'ok'
}

function FindingRow({ row }) {
  return (
    <div className={'finding ' + findingClass(row)}>
      <div className="finding__stripe" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="finding__label-row">
          <span className="finding__label">{row.trigger_label || row.trigger_type}</span>
          <span className={'pill ' + pillClass(row)}>{row.concern_flag ? '需留意' : '無異常'}</span>
        </div>
        <div className="finding__detail">
          {row.finding}
          {row.suggested_action ? `　→ ${row.suggested_action}` : ''}
        </div>
      </div>
    </div>
  )
}

/* 個股詳情頁：GET /api/stocks/:code。回傳結構是目前所有既有路由裡整合度
   最高的一頁（見 app/routers/stock_detail.py 檔頭 docstring），這裡逐區塊
   對照該檔案 get_stock_detail() 的回傳 dict 欄位名稱呈現，不臆測欄位、
   查無資料的區塊照後端語意顯示「尚無資料／尚未設定」而非略過不畫。 */
export default function StockDetail() {
  const { code } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    apiGet(`/api/stocks/${code}`)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [code])

  return (
    <div>
      <Link to="/dashboard" className="back-link">
        <ChevronLeftIcon width={16} height={16} /> 回投資
      </Link>

      {error && <div className="error-box">載入失敗：{error}</div>}
      {!data && !error && <div className="loading-box">載入中…</div>}
      {!data && !error ? null : data && <StockDetailBody data={data} />}
    </div>
  )
}

function StockDetailBody({ data }) {
  const {
    code, name, price, prev_close, delta_pct,
    valuation, module_d, verdict_html, concentration,
    position_plan, holdings, buy_reason, buy_reasons_count, other_notes,
  } = data

  return (
    <div>
      <div className="detail-header">
        <div>
          <span className="detail-header__name">{name || code}</span>
          <span className="detail-header__code">{code}</span>
        </div>
        <div className="detail-header__price">
          <span className="detail-header__now">{num(price)}</span>
          {delta_pct != null && (
            <span className={'detail-header__delta ' + (delta_pct >= 0 ? 'is-up' : 'is-down')}>
              {delta_pct >= 0 ? '+' : ''}{delta_pct.toFixed(2)}%
            </span>
          )}
          <div className="meta">昨收 {num(prev_close)}</div>
        </div>
      </div>

      {verdict_html && (
        // verdict_html 是後端同源產出的信任內容（review_engine 的結論
        // banner，見 stock_detail.py 檔頭「唯一例外」段），非使用者輸入，
        // 這裡直接渲染沿用舊版一字不差的判準文字，不重新發明一套。
        <div dangerouslySetInnerHTML={{ __html: verdict_html }} />
      )}

      <section className="card">
        <div className="card__head">
          <h2>估值快照</h2>
          {valuation && <span className="card__meta">{valuation.checked_at}</span>}
        </div>
        <div className="card__body">
          {!valuation && <p className="empty">尚無估值資料，等待背景刷新後顯示。</p>}
          {valuation && (
            <>
              <div className="val-grid">
                <div className="val-item">
                  <div className="label">本益比 PER</div>
                  <div className="value">{num(valuation.per)}</div>
                </div>
                <div className="val-item">
                  <div className="label">股價淨值比 PBR</div>
                  <div className="value">{num(valuation.pbr)}</div>
                </div>
                <div className="val-item">
                  <div className="label">殖利率</div>
                  <div className="value">{pctRaw(valuation.dividend_yield)}</div>
                </div>
                <div className="val-item">
                  <div className="label">營收年增率（{valuation.revenue_period || '—'}）</div>
                  <div className="value">{pct(valuation.revenue_yoy)}</div>
                </div>
              </div>
              <div className="val-source">
                資料來源：估值 {valuation.valuation_data_source || '—'}
                {valuation.valuation_error && `（${valuation.valuation_error}）`}
                ／營收 {valuation.revenue_data_source || '—'}
                {valuation.revenue_error && `（${valuation.revenue_error}）`}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card__head">
          <h2>Checks・加碼審查</h2>
          <span className="card__meta">
            {module_d.latest_batch.length ? `${module_d.latest_batch.length} 項自動檢查` : '尚無資料'}
          </span>
        </div>
        <div className="card__body">
          {module_d.gate.length > 0 && <div className="group-label">Required・Gate（通用層）</div>}
          {module_d.gate.map((r) => <FindingRow key={r.id} row={r} />)}
          {module_d.reference.length > 0 && <div className="group-label">Reference only（策略層，不影響 Gate）</div>}
          {module_d.reference.map((r) => <FindingRow key={r.id} row={r} />)}
          {module_d.status.length > 0 && <div className="group-label">Status check（老芋頭動向）</div>}
          {module_d.status.map((r) => <FindingRow key={r.id} row={r} />)}
          {module_d.latest_batch.length === 0 && <p className="empty">尚無檢視資料，稍後將自動更新。</p>}

          <details className="collapse">
            <summary>待人工查證（系統無資料源，{module_d.manual_gate_items.length + module_d.manual_score_items.length} 項）</summary>
            {module_d.manual_gate_items.map((m) => (
              <div className="manual-item" key={m.label}>
                <div className="manual-item__label">{m.label}</div>
                <div className="manual-item__why">{m.why}</div>
              </div>
            ))}
            {module_d.manual_score_items.map((m) => (
              <div className="manual-item" key={m.label}>
                <div className="manual-item__label">{m.label}（權重 {m.weight}）</div>
                <div className="manual-item__why">{m.why}</div>
              </div>
            ))}
          </details>
        </div>
      </section>

      <section className="card">
        <div className="card__head">
          <h2>Score・自動化評分</h2>
        </div>
        <div className="card__body">
          {!module_d.score && <p className="empty">尚未計算，等待背景刷新後顯示。</p>}
          {module_d.score && module_d.score.items.map((it) => (
            <div
              className={'finding ' + (it.earned === true ? 'ok' : it.earned === false ? 'alert' : 'pending')}
              key={it.key}
            >
              <div className="finding__stripe" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="finding__label-row">
                  <span className="finding__label">{it.label}（權重 {it.weight}）</span>
                  {earnedPill(it.earned)}
                </div>
                <div className="finding__detail">{it.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card__head"><h2>集中度</h2></div>
        <div className="card__body">
          <div className="val-grid">
            <div className="val-item">
              <div className="label">單股佔比（上限 {concentration.single_stock_cap_pct}%）</div>
              <div className="value">{pctRaw(concentration.current_position_pct)}</div>
            </div>
            <div className="val-item">
              <div className="label">
                主題「{concentration.theme || '未標記'}」佔比（上限 {concentration.theme_cap_pct}%）
              </div>
              <div className="value">{pctRaw(concentration.theme_concentration_pct)}</div>
            </div>
          </div>
          {concentration.concentration_warning && (
            <p className="finding__detail" style={{ color: 'var(--red-ink)', marginTop: '.6rem' }}>
              {concentration.concentration_warning}
            </p>
          )}
          <p className="finding__detail" style={{ marginTop: '.6rem' }}>{concentration.detail}</p>
        </div>
      </section>

      <section className="card">
        <div className="card__head"><h2>加碼計畫</h2></div>
        <div className="card__body">
          {!position_plan.plan && <p className="empty">尚未設定加碼計畫。</p>}
          {position_plan.plan && (
            <div className="holdings-grid">
              <div className="val-item">
                <div className="label">計畫總額</div>
                <div className="value">{money(position_plan.plan.plan_amount)}</div>
              </div>
              <div className="val-item">
                <div className="label">已投入金額（{position_plan.invested_source || '—'}）</div>
                <div className="value">{money(position_plan.invested_amount)}</div>
              </div>
              <div className="val-item">
                <div className="label">完成度</div>
                <div className="value">{pctRaw(position_plan.completion_pct)}</div>
              </div>
            </div>
          )}
          {position_plan.plan && position_plan.plan.note && (
            <p className="finding__detail">備註：{position_plan.plan.note}</p>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card__head"><h2>持股與交易</h2></div>
        <div className="card__body">
          {!holdings && <p className="empty">純研究標的，無庫存快照也無交易紀錄。</p>}
          {holdings && (
            <>
              <div className="holdings-grid">
                <div className="val-item">
                  <div className="label">持股數</div>
                  <div className="value">{num(holdings.holding_row && holdings.holding_row.shares)}</div>
                </div>
                <div className="val-item">
                  <div className="label">市值</div>
                  <div className="value">{money(holdings.market_value)}</div>
                </div>
                <div className="val-item">
                  <div className="label">投組佔比</div>
                  <div className="value">{pctRaw(holdings.portfolio_pct)}</div>
                </div>
                <div className="val-item">
                  <div className="label">{holdings.avg_cost_label}</div>
                  <div className="value">{num(holdings.avg_cost)}</div>
                </div>
                <div className="val-item">
                  <div className="label">現價</div>
                  <div className="value">{num(holdings.current_price)}</div>
                </div>
                <div className="val-item">
                  <div className="label">浮動損益</div>
                  <div className="value">{pct(holdings.pnl_pct)}</div>
                </div>
              </div>
              {holdings.ledger_entries.length > 0 && (
                <details className="trade-list-details" open={holdings.ledger_entries.length <= 5}>
                  <summary>交易流水（{holdings.ledger_entries.length} 筆）</summary>
                  {holdings.ledger_entries.map((e) => (
                    <div className="trade-row" key={e.id}>
                      <span className={'trade-row__tag ' + (e.action === '買' ? 'buy' : 'sell')}>
                        {e.action}
                      </span>
                      <span className="trade-row__mid">
                        {e.shares} 股 @ {e.price}
                        {e.add_sequence != null && `（第 ${e.add_sequence} 次加碼）`}
                      </span>
                      <span className="trade-row__date">{e.date}</span>
                    </div>
                  ))}
                </details>
              )}
            </>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card__head">
          <h2>心得與留言</h2>
          <span className="card__meta">買進理由 {buy_reasons_count} 則</span>
        </div>
        <div className="card__body">
          {buy_reason && (
            <div className="reason-pin">
              <div className="reason-pin__body">
                <div className="reason-pin__label-row">
                  <span className="reason-pin__label">買進理由</span>
                  <span className="reason-pin__date">{buy_reason.date}</span>
                </div>
                <div className="reason-pin__text">{buy_reason.body}</div>
              </div>
            </div>
          )}
          {other_notes.length === 0 && !buy_reason && <p className="empty">尚無留言。</p>}
          {other_notes.map((c, i) => (
            <div className="finding pending" key={i}>
              <div className="finding__stripe" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="finding__label-row">
                  <span className="finding__label">{c.source_tag}</span>
                  <span className="card__meta">{c.date}</span>
                </div>
                <div className="finding__detail">{c.body}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
