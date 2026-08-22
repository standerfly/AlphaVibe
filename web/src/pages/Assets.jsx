import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client.js'

/* 資產分頁（規劃文件第5節 Step 4，2026-08-21）：口袋／帳戶管理、建倉進度、
   情境試算，串接 app/routers/assets.py 的既有 API。決策脈絡見
   docs/spec-intake/alphavibe/roadmap.md Q-046 與
   docs/spec-intake/alphavibe/supporting-artifacts/2026-08-21-personal-console-expansion.md
   「資產分頁設計」節。

   目前沒有「列出所有建倉計畫」的 API（只有 GET /api/assets/buildup/{plan_id}），
   種子資料固定只寫入一筆、id 一定是 1（見 kb_store.py _seed_asset_defaults()），
   所以這裡先寫死 plan id；之後真的有多計畫需求，要先加一支列表 API，
   不要在前端猜 id。

   口袋卡片的 current_amount／建倉進度的 entries 都會因為「設定餘額」
   「建倉打勾/取消」而變動，所以這兩類操作完成後，除了重整自己那組資料，
   也要連帶重整另一邊（不能只重整自己按的那個表單），否則畫面會顯示
   過期的加總數字。*/

const BUILDUP_PLAN_ID = 1

function money(v) {
  return v == null ? '—' : Math.round(v).toLocaleString('zh-TW')
}

function pocketProgressPct(current, target) {
  if (!target || target <= 0) return null
  return Math.min(100, Math.max(0, (current / target) * 100))
}

const SIM_FIELDS = [
  { key: 'principal', label: '起始本金', step: '1000', min: '0' },
  { key: 'monthly_contribution', label: '每月定期定額', step: '500', min: '0' },
  { key: 'years_to_retirement', label: '累積期年數', step: '0.5', min: '0' },
  { key: 'accumulation_rate', label: '累積期年化報酬率（如 0.08＝8%）', step: '0.01' },
  { key: 'withdrawal_rate', label: '提領期年化報酬率', step: '0.01' },
  { key: 'withdrawal_years', label: '提領期年數', step: '0.5', min: '0' },
]

export default function Assets() {
  const [pockets, setPockets] = useState(null)
  const [accounts, setAccounts] = useState(null)
  const [holdings, setHoldings] = useState(null)
  const [coreError, setCoreError] = useState(null)

  const [buildup, setBuildup] = useState(null)
  const [buildupError, setBuildupError] = useState(null)

  // pocketForm/accountForm 身兼「新增」與「編輯」兩用：id 為 null 時是
  // 新增模式，送出時 POST 不帶 id；點卡片上的「編輯」會把 id 連同既有值
  // 一起填進來，送出時帶 id，後端 upsert_pocket()/upsert_account() 看到
  // id 就會更新既有那筆，不會新增（見 app/routers/assets.py 的
  // PocketUpsert/AccountUpsert docstring）——後端本來就支援這個語意，
  // 這裡純粹是補上前端沒有的編輯入口（2026-08-22 使用者回報才發現漏了）。
  const [pocketForm, setPocketForm] = useState({ id: null, name: '', target_amount: '' })
  const [accountForm, setAccountForm] = useState({ id: null, name: '', category: '' })
  const [holdingForm, setHoldingForm] = useState({ pocket_id: '', account_id: '', amount: '' })
  const [formError, setFormError] = useState(null)
  const [busy, setBusy] = useState(false)

  const [buildupEditing, setBuildupEditing] = useState(null)
  const [buildupInput, setBuildupInput] = useState('')
  const [buildupBusy, setBuildupBusy] = useState(false)

  const [simForm, setSimForm] = useState({
    principal: '', monthly_contribution: '', years_to_retirement: '',
    accumulation_rate: '', withdrawal_rate: '', withdrawal_years: '',
  })
  const [simResult, setSimResult] = useState(null)
  const [simError, setSimError] = useState(null)
  const [simBusy, setSimBusy] = useState(false)

  const refreshCore = useCallback(() => {
    setCoreError(null)
    return Promise.all([
      apiGet('/api/assets/pockets'),
      apiGet('/api/assets/accounts'),
      apiGet('/api/assets/holdings'),
    ]).then(([p, a, h]) => {
      setPockets(p.pockets)
      setAccounts(a.accounts)
      setHoldings(h.holdings)
    }).catch((err) => setCoreError(err.message))
  }, [])

  const refreshBuildup = useCallback(() => {
    setBuildupError(null)
    return apiGet(`/api/assets/buildup/${BUILDUP_PLAN_ID}`)
      .then((b) => setBuildup(b))
      .catch((err) => setBuildupError(err.message))
  }, [])

  useEffect(() => {
    refreshCore()
    refreshBuildup()
  }, [refreshCore, refreshBuildup])

  async function handleSubmitPocket(e) {
    e.preventDefault()
    setFormError(null)
    const name = pocketForm.name.trim()
    if (!name) { setFormError('口袋名稱必填'); return }
    setBusy(true)
    try {
      await apiPost('/api/assets/pockets', {
        id: pocketForm.id || undefined,
        name,
        target_amount: pocketForm.target_amount === '' ? null : Number(pocketForm.target_amount),
      })
      setPocketForm({ id: null, name: '', target_amount: '' })
      await refreshCore()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleEditPocket(p) {
    setFormError(null)
    setPocketForm({ id: p.id, name: p.name, target_amount: p.target_amount ?? '' })
  }

  function handleCancelEditPocket() {
    setFormError(null)
    setPocketForm({ id: null, name: '', target_amount: '' })
  }

  async function handleSubmitAccount(e) {
    e.preventDefault()
    setFormError(null)
    const name = accountForm.name.trim()
    if (!name) { setFormError('帳戶名稱必填'); return }
    setBusy(true)
    try {
      await apiPost('/api/assets/accounts', {
        id: accountForm.id || undefined,
        name,
        category: accountForm.category.trim() || null,
      })
      setAccountForm({ id: null, name: '', category: '' })
      await refreshCore()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleEditAccount(a) {
    setFormError(null)
    setAccountForm({ id: a.id, name: a.name, category: a.category || '' })
  }

  function handleCancelEditAccount() {
    setFormError(null)
    setAccountForm({ id: null, name: '', category: '' })
  }

  async function handleSetHolding(e) {
    e.preventDefault()
    setFormError(null)
    if (!holdingForm.pocket_id || !holdingForm.account_id || holdingForm.amount === '') {
      setFormError('口袋、帳戶、餘額都要填')
      return
    }
    setBusy(true)
    try {
      await apiPost('/api/assets/holdings', {
        pocket_id: Number(holdingForm.pocket_id),
        account_id: Number(holdingForm.account_id),
        amount: Number(holdingForm.amount),
      })
      setHoldingForm({ pocket_id: '', account_id: '', amount: '' })
      await refreshCore()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleArchivePocket(id) {
    setFormError(null)
    setBusy(true)
    try {
      await apiPost(`/api/assets/pockets/${id}/archive`)
      await refreshCore()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleArchiveAccount(id) {
    setFormError(null)
    setBusy(true)
    try {
      await apiPost(`/api/assets/accounts/${id}/archive`)
      await refreshCore()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleBuildupComplete(monthNumber) {
    const amount = Number(buildupInput)
    if (buildupInput === '' || Number.isNaN(amount)) return
    setBuildupBusy(true)
    setBuildupError(null)
    try {
      await apiPost(
        `/api/assets/buildup/${BUILDUP_PLAN_ID}/months/${monthNumber}/complete`,
        { actual_amount: amount },
      )
      setBuildupEditing(null)
      setBuildupInput('')
      // 打勾會累加進 asset_holdings，口袋卡片的 current_amount 也要跟著更新。
      await Promise.all([refreshCore(), refreshBuildup()])
    } catch (err) {
      setBuildupError(err.message)
    } finally {
      setBuildupBusy(false)
    }
  }

  async function handleBuildupUndo(monthNumber) {
    setBuildupBusy(true)
    setBuildupError(null)
    try {
      await apiPost(`/api/assets/buildup/${BUILDUP_PLAN_ID}/months/${monthNumber}/undo`)
      await Promise.all([refreshCore(), refreshBuildup()])
    } catch (err) {
      setBuildupError(err.message)
    } finally {
      setBuildupBusy(false)
    }
  }

  async function handleSimulate(e) {
    e.preventDefault()
    setSimError(null)
    setSimResult(null)
    const payload = {}
    for (const { key } of SIM_FIELDS) {
      const raw = simForm[key]
      if (raw === '') { setSimError('請填寫所有欄位再送出試算'); return }
      const num = Number(raw)
      if (Number.isNaN(num)) { setSimError(`${key} 不是有效數字`); return }
      payload[key] = num
    }
    setSimBusy(true)
    try {
      const res = await apiPost('/api/assets/simulate', payload)
      setSimResult(res)
    } catch (err) {
      setSimError(err.message)
    } finally {
      setSimBusy(false)
    }
  }

  const cumulativeInvested = buildup
    ? buildup.entries.reduce((sum, entry) => sum + (entry.actual_amount || 0), 0)
    : 0

  return (
    <div>
      <div className="page-title"><h1>資產</h1></div>

      {coreError && <div className="error-box">載入失敗：{coreError}</div>}
      {!pockets && !coreError && <div className="loading-box">載入中…</div>}

      {pockets && (
        <div className="pocket-grid">
          {pockets.length === 0 && <p className="empty">目前沒有口袋，先在下面「口袋／帳戶管理」新增一個。</p>}
          {pockets.map((p) => {
            const pctVal = pocketProgressPct(p.current_amount, p.target_amount)
            const pocketHoldings = (holdings || []).filter((h) => h.pocket_id === p.id)
            return (
              <div className="pocket-card" key={p.id}>
                <div className="pocket-card__head">
                  <div className="pocket-card__name">{p.name}</div>
                  <div className="pocket-card__actions">
                    <button
                      type="button"
                      className="btn-muted btn-sm"
                      disabled={busy}
                      onClick={() => handleEditPocket(p)}
                    >編輯</button>
                    <button
                      type="button"
                      className="btn-danger-outline btn-sm"
                      disabled={busy}
                      onClick={() => handleArchivePocket(p.id)}
                    >封存</button>
                  </div>
                </div>
                <div className="pocket-card__amounts">
                  <span className="pocket-card__current">{money(p.current_amount)}</span>
                  <span>目標 {p.target_amount != null ? money(p.target_amount) : '未設定'}</span>
                </div>
                {pctVal != null && (
                  <>
                    <div className="progress-track">
                      <div
                        className={'progress-fill' + (pctVal >= 100 ? ' is-over' : '')}
                        style={{ width: `${pctVal}%` }}
                      />
                    </div>
                    <div className="pocket-card__pct">{pctVal.toFixed(1)}%</div>
                  </>
                )}
                <div className="pocket-card__accounts">
                  {pocketHoldings.length === 0 && <span className="account-chip">尚無帳戶餘額</span>}
                  {pocketHoldings.map((h) => (
                    <span className="account-chip" key={h.id}>
                      {h.account_name}
                      <span className="account-chip__amount">{money(h.amount)}</span>
                    </span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="card">
        <div className="card__head"><h2>口袋／帳戶管理</h2></div>
        <div className="card__body">
          {formError && <div className="error-box">{formError}</div>}

          <div className="subform">
            <div className="subform__title">{pocketForm.id ? '編輯口袋' : '新增口袋'}</div>
            <form onSubmit={handleSubmitPocket}>
              <div className="form-grid">
                <div className="form-field">
                  <label htmlFor="pocket-name">名稱</label>
                  <input
                    id="pocket-name"
                    type="text"
                    value={pocketForm.name}
                    onChange={(e) => setPocketForm({ ...pocketForm, name: e.target.value })}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="pocket-target">目標金額（選填）</label>
                  <input
                    id="pocket-target"
                    type="number"
                    min="0"
                    value={pocketForm.target_amount}
                    onChange={(e) => setPocketForm({ ...pocketForm, target_amount: e.target.value })}
                  />
                </div>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn" disabled={busy}>
                  {pocketForm.id ? '儲存變更' : '新增口袋'}
                </button>
                {pocketForm.id && (
                  <button type="button" className="btn-muted" disabled={busy} onClick={handleCancelEditPocket}>
                    取消編輯
                  </button>
                )}
              </div>
            </form>
          </div>

          <div className="subform">
            <div className="subform__title">{accountForm.id ? '編輯帳戶' : '新增帳戶'}</div>
            <form onSubmit={handleSubmitAccount}>
              <div className="form-grid">
                <div className="form-field">
                  <label htmlFor="account-name">名稱</label>
                  <input
                    id="account-name"
                    type="text"
                    value={accountForm.name}
                    onChange={(e) => setAccountForm({ ...accountForm, name: e.target.value })}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="account-category">類型標籤（選填，如「銀行」「證券」）</label>
                  <input
                    id="account-category"
                    type="text"
                    value={accountForm.category}
                    onChange={(e) => setAccountForm({ ...accountForm, category: e.target.value })}
                  />
                </div>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn" disabled={busy}>
                  {accountForm.id ? '儲存變更' : '新增帳戶'}
                </button>
                {accountForm.id && (
                  <button type="button" className="btn-muted" disabled={busy} onClick={handleCancelEditAccount}>
                    取消編輯
                  </button>
                )}
              </div>
            </form>
          </div>

          <div className="subform">
            <div className="subform__title">設定口袋 × 帳戶餘額</div>
            <form onSubmit={handleSetHolding}>
              <div className="form-grid">
                <div className="form-field">
                  <label htmlFor="holding-pocket">口袋</label>
                  <select
                    id="holding-pocket"
                    value={holdingForm.pocket_id}
                    onChange={(e) => setHoldingForm({ ...holdingForm, pocket_id: e.target.value })}
                  >
                    <option value="">請選擇</option>
                    {(pockets || []).map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label htmlFor="holding-account">帳戶</label>
                  <select
                    id="holding-account"
                    value={holdingForm.account_id}
                    onChange={(e) => setHoldingForm({ ...holdingForm, account_id: e.target.value })}
                  >
                    <option value="">請選擇</option>
                    {(accounts || []).map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label htmlFor="holding-amount">餘額（覆蓋既有值）</label>
                  <input
                    id="holding-amount"
                    type="number"
                    value={holdingForm.amount}
                    onChange={(e) => setHoldingForm({ ...holdingForm, amount: e.target.value })}
                  />
                </div>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn" disabled={busy}>設定餘額</button>
                <span className="form-note">這是覆蓋不是累加：送出後該口袋×帳戶的餘額會變成填的數字。</span>
              </div>
            </form>
          </div>

          <div className="subform">
            <div className="subform__title">帳戶清單</div>
            <div className="manage-list">
              {(accounts || []).length === 0 && <p className="empty">目前沒有帳戶。</p>}
              {(accounts || []).map((a) => (
                <div className="manage-row" key={a.id}>
                  <span>
                    <span className="manage-row__name">{a.name}</span>
                    {a.category && <span className="manage-row__meta">{a.category}</span>}
                  </span>
                  <span className="manage-row__actions">
                    <button
                      type="button"
                      className="btn-muted btn-sm"
                      disabled={busy}
                      onClick={() => handleEditAccount(a)}
                    >編輯</button>
                    <button
                      type="button"
                      className="btn-danger-outline btn-sm"
                      disabled={busy}
                      onClick={() => handleArchiveAccount(a.id)}
                    >封存</button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card__head"><h2>建倉進度</h2></div>
        <div className="card__body">
          {buildupError && <div className="error-box">載入失敗：{buildupError}</div>}
          {!buildup && !buildupError && <div className="loading-box">載入中…</div>}
          {buildup && (
            <>
              <div className="buildup-summary">
                <div>
                  <div className="buildup-summary__value">{buildup.label}</div>
                  <div className="buildup-summary__label">{buildup.pocket_name} × {buildup.account_name}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="buildup-summary__value">
                    {money(cumulativeInvested)} / {money(buildup.monthly_target_amount * buildup.total_months)}
                  </div>
                  <div className="buildup-summary__label">累計投入 / 目標金額</div>
                </div>
              </div>
              <div className="buildup-grid">
                {buildup.entries.map((entry) => {
                  const done = entry.actual_amount != null
                  const editing = buildupEditing === entry.month_number
                  return (
                    <div
                      key={entry.month_number}
                      className={'buildup-cell' + (done ? ' is-done' : '')}
                      onClick={() => {
                        if (buildupBusy) return
                        if (done) {
                          handleBuildupUndo(entry.month_number)
                        } else if (!editing) {
                          setBuildupEditing(entry.month_number)
                          setBuildupInput(String(entry.planned_amount ?? buildup.monthly_target_amount ?? ''))
                        }
                      }}
                    >
                      <div className="buildup-cell__month">第{entry.month_number}月</div>
                      <div className="buildup-cell__check">{done ? '✓' : '○'}</div>
                      {done ? (
                        <div className="buildup-cell__amount">{money(entry.actual_amount)}</div>
                      ) : (
                        <div className="buildup-cell__planned">預計 {money(entry.planned_amount)}</div>
                      )}
                      {editing && !done && (
                        <div onClick={(e) => e.stopPropagation()}>
                          <div className="buildup-input-row">
                            <input
                              type="number"
                              value={buildupInput}
                              onChange={(e) => setBuildupInput(e.target.value)}
                            />
                          </div>
                          <div className="form-actions" style={{ marginTop: '.35rem' }}>
                            <button
                              type="button"
                              className="btn btn-sm"
                              disabled={buildupBusy}
                              onClick={() => handleBuildupComplete(entry.month_number)}
                            >打勾</button>
                            <button
                              type="button"
                              className="btn-muted btn-sm"
                              disabled={buildupBusy}
                              onClick={() => { setBuildupEditing(null); setBuildupInput('') }}
                            >取消</button>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head"><h2>情境試算</h2></div>
        <div className="card__body">
          <div className="disclaimer-box">
            <span className="disclaimer-box__label">注意：</span>
            這是粗略估算工具，公式尚未跟原始素材完整核對過（已知用範例反推有誤差），
            送出試算後下方會顯示伺服器回傳的完整揭露文字，請務必看過再參考結果。
          </div>
          <form onSubmit={handleSimulate}>
            <div className="form-grid">
              {SIM_FIELDS.map(({ key, label, step, min }) => (
                <div className="form-field" key={key}>
                  <label htmlFor={`sim-${key}`}>{label}</label>
                  <input
                    id={`sim-${key}`}
                    type="number"
                    step={step}
                    min={min}
                    value={simForm[key]}
                    onChange={(e) => setSimForm({ ...simForm, [key]: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <div className="form-actions">
              <button type="submit" className="btn" disabled={simBusy}>試算</button>
            </div>
          </form>

          {simError && <div className="error-box">{simError}</div>}

          {simResult && (
            <>
              <div className="simulate-result-grid">
                <div className="val-item">
                  <div className="label">退休時資產（fv_total）</div>
                  <div className="value">{money(simResult.fv_total)}</div>
                </div>
                <div className="val-item">
                  <div className="label">每月可提領金額</div>
                  <div className="value">{money(simResult.monthly_withdrawal)}</div>
                </div>
              </div>
              <div className="disclaimer-box">
                <span className="disclaimer-box__label">重要揭露：</span>
                {simResult.disclaimer}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
