import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost } from '../api/client.js'

/* 「管家」分頁（2026-08-31 新增）：STND Telegram 管家閘道的網頁監控＋
   聊天介面，串接 app/routers/gateway_monitor.py 的六個端點。完整方案見
   ~/.claude/plans/hazy-petting-wreath.md §6。

   跟其他分頁不同：這裡的資料完全不是這個 app 自己的 KBStore/SQLite，
   而是 telegram_gateway/state/ 底下的共用狀態檔——手機上用 Telegram 問過
   的話，這裡看得到；在這裡送出的訊息，也會被 Telegram 那條線記得（同一
   個 domain 共用同一段 session 記憶）。

   輪詢設計：對話清單／背景任務清單每 15 秒自動重新整理一次（背景任務
   可能在使用者沒有互動的情況下完成，需要自己冒出來，不像其他分頁只在
   使用者操作後才需要重抓）；資源消耗卡片變動較慢，跟著同一個輪詢週期
   一起刷新即可，不需要獨立頻率。 */

const POLL_INTERVAL_MS = 15000

// 2026-08-31「擴充：任意命名主題」：只有已知專案捷徑（cwd 指到真實
// 專案路徑）需要顯示名稱對照，其餘任意命名的主題直接顯示原始名稱
// （domainLabel() 的既有 fallback `DOMAIN_LABELS[name] || name` 不用改）。
const DOMAIN_LABELS = { alphavibe: 'AlphaVibe', harness: 'Harness' }

function domainLabel(name) {
  return DOMAIN_LABELS[name] || name
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-TW', { hour12: false })
  } catch (_err) {
    return iso
  }
}

function money(v) {
  return v == null ? '—' : v.toLocaleString('zh-TW', { maximumFractionDigits: 4 })
}

function statusBadgeClass(status) {
  if (status === 'done') return 'badge-positive'
  if (status === 'working' || status === 'queued') return 'badge-neutral'
  return 'badge-neutral'
}

export default function Gateway() {
  const [domains, setDomains] = useState(null)
  const [convError, setConvError] = useState(null)

  const [tasks, setTasks] = useState(null)
  const [tasksError, setTasksError] = useState(null)

  const [usage, setUsage] = useState(null)
  const [usageError, setUsageError] = useState(null)

  const [lockdown, setLockdown] = useState(null)

  const [selectedDomain, setSelectedDomain] = useState('general')
  const [inputText, setInputText] = useState('')
  const [chatLog, setChatLog] = useState([])
  const [chatBusy, setChatBusy] = useState(false)
  const [taskBusy, setTaskBusy] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [taskNotice, setTaskNotice] = useState(null)

  const [transcriptDomain, setTranscriptDomain] = useState(null)
  const [transcriptData, setTranscriptData] = useState(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState(null)

  const refreshConversations = useCallback(() => {
    return apiGet('/api/gateway/conversations')
      .then((d) => {
        setDomains(d.domains)
        setLockdown(d.lockdown)
        setConvError(null)
      })
      .catch((err) => setConvError(err.message))
  }, [])

  const refreshTasks = useCallback(() => {
    return apiGet('/api/gateway/tasks')
      .then((d) => {
        setTasks(d.tasks)
        setLockdown(d.lockdown)
        setTasksError(null)
      })
      .catch((err) => setTasksError(err.message))
  }, [])

  const refreshUsage = useCallback(() => {
    return apiGet('/api/gateway/usage')
      .then((d) => { setUsage(d); setUsageError(null) })
      .catch((err) => setUsageError(err.message))
  }, [])

  const refreshAll = useCallback(() => {
    refreshConversations()
    refreshTasks()
    refreshUsage()
  }, [refreshConversations, refreshTasks, refreshUsage])

  // 主題選單的選項來源：GET /api/gateway/conversations 修好後會回傳
  // 完整清單（含 Telegram 建立的任意新主題），依上次活躍時間排序，
  // 供下方 <datalist> 使用。
  const sortedDomains = useMemo(() => {
    if (!domains) return []
    return [...domains].sort((a, b) => (b.last_active || '').localeCompare(a.last_active || ''))
  }, [domains])

  useEffect(() => {
    refreshAll()
    const timer = setInterval(refreshAll, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [refreshAll])

  const isLocked = !!(lockdown && lockdown.is_locked)

  async function handleSendChat(e) {
    e.preventDefault()
    const text = inputText.trim()
    if (!text) return
    setActionError(null)
    setTaskNotice(null)
    setChatBusy(true)
    const domain = selectedDomain
    setChatLog((log) => [...log, { domain, role: 'user', text, timestamp: new Date().toISOString() }])
    try {
      const res = await apiPost('/api/gateway/chat', { domain, text })
      setChatLog((log) => [...log, {
        domain,
        role: res.is_error ? 'error' : 'assistant',
        text: res.result,
        timestamp: new Date().toISOString(),
      }])
      setInputText('')
      await refreshConversations()
    } catch (err) {
      setActionError(err.message)
      setChatLog((log) => [...log, { domain, role: 'error', text: err.message, timestamp: new Date().toISOString() }])
    } finally {
      setChatBusy(false)
    }
  }

  async function handleSubmitTask() {
    const description = inputText.trim()
    if (!description) return
    setActionError(null)
    setTaskNotice(null)
    setTaskBusy(true)
    try {
      const res = await apiPost('/api/gateway/task', { domain: selectedDomain, description })
      setTaskNotice(`已受理，背景執行中（id=${res.short_id}），完成後請重新整理下方「背景任務」查看`)
      setInputText('')
      await refreshTasks()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setTaskBusy(false)
    }
  }

  async function handleToggleTranscript(domain) {
    if (transcriptDomain === domain) {
      setTranscriptDomain(null)
      setTranscriptData(null)
      return
    }
    setTranscriptDomain(domain)
    setTranscriptData(null)
    setTranscriptError(null)
    setTranscriptLoading(true)
    try {
      const res = await apiGet(`/api/gateway/conversations/${encodeURIComponent(domain)}/transcript`)
      setTranscriptData(res)
    } catch (err) {
      setTranscriptError(err.message)
    } finally {
      setTranscriptLoading(false)
    }
  }

  return (
    <div>
      <div className="page-title"><h1>管家</h1></div>

      {isLocked && (
        <div className="gateway-lockdown-banner">
          <span className="gateway-lockdown-banner__title">系統已鎖定（LOCKDOWN）</span>
          <span>
            聊天與背景任務已停用，唯讀查詢不受影響。解鎖需要在本機手動刪除旗標檔。
            {lockdown && lockdown.info && lockdown.info.locked_at
              ? `（鎖定於 ${fmtTime(lockdown.info.locked_at)}）` : ''}
          </span>
        </div>
      )}

      <div className="card">
        <div className="card__head">
          <h2>跟管家對話</h2>
          <span className="card__meta">跟 Telegram 共用同一段對話記憶（依 domain 區分）</span>
        </div>
        <div className="card__body">
          {actionError && <div className="error-box">{actionError}</div>}
          {taskNotice && <div className="success-box">{taskNotice}</div>}

          <form onSubmit={handleSendChat}>
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="gateway-domain">情境（主題）</label>
                {/* 2026-08-31「擴充：任意命名主題」：固定 <select> 改成
                    自由輸入＋建議清單——同一個輸入框「選既有主題」跟
                    「打新名稱建立」共用，不用另外做「新增主題」表單。
                    命名規則不在前端重複驗證，非法名稱交給後端 400，沿用
                    既有 actionError 顯示機制。 */}
                <input
                  id="gateway-domain"
                  list="gateway-domain-options"
                  value={selectedDomain}
                  onChange={(e) => setSelectedDomain(e.target.value)}
                  placeholder="輸入已知主題名稱，或打新名稱建立"
                />
                <datalist id="gateway-domain-options">
                  {sortedDomains.map((d) => (
                    <option key={d.name} value={d.name}>{domainLabel(d.name)}</option>
                  ))}
                </datalist>
              </div>
            </div>
            <div className="form-field" style={{ marginTop: '.6rem' }}>
              <label htmlFor="gateway-input">訊息</label>
              <textarea
                id="gateway-input"
                rows={3}
                value={inputText}
                disabled={isLocked}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="輸入訊息……「送出」同步等回覆；「背景執行」立刻回受理，完成狀態看下方背景任務清單"
              />
            </div>
            <div className="form-actions">
              <button type="submit" className="btn" disabled={isLocked || chatBusy || taskBusy || !inputText.trim()}>
                {chatBusy ? '送出中…' : '送出'}
              </button>
              <button
                type="button"
                className="btn-muted"
                disabled={isLocked || chatBusy || taskBusy || !inputText.trim()}
                onClick={handleSubmitTask}
              >
                {taskBusy ? '提交中…' : '背景執行'}
              </button>
            </div>
          </form>

          {chatLog.length > 0 && (
            <div className="gateway-chat-log">
              {chatLog.map((m, i) => (
                <div key={i} className={'gateway-chat-bubble gateway-chat-bubble--' + m.role}>
                  <div className="gateway-chat-bubble__meta">
                    {domainLabel(m.domain)} · {m.role === 'user' ? '你' : m.role === 'error' ? '錯誤' : '管家'}
                  </div>
                  <div className="gateway-chat-bubble__text">{m.text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <h2>對話狀態</h2>
          <span className="card__meta">每 15 秒自動更新</span>
        </div>
        <div className="card__body">
          {convError && <div className="error-box">載入失敗：{convError}</div>}
          {!domains && !convError && <div className="loading-box">載入中…</div>}
          {domains && (
            <div className="preview-table-wrap">
              <table className="preview-table gateway-table">
                <thead>
                  <tr>
                    <th>情境</th><th>Session</th><th>上次活躍</th><th>進行中任務</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {domains.map((d) => (
                    <tr key={d.name}>
                      <td>{domainLabel(d.name)}</td>
                      <td>{d.session_id ? d.session_id.slice(0, 8) + '…' : '（尚未開始）'}</td>
                      <td>{fmtTime(d.last_active)}</td>
                      <td>{d.has_inflight_task
                        ? <span className="badge badge-neutral">進行中</span>
                        : <span className="meta">—</span>}</td>
                      <td>
                        {d.session_id && (
                          <button type="button" className="btn-muted btn-sm" onClick={() => handleToggleTranscript(d.name)}>
                            {transcriptDomain === d.name ? '收起逐字稿' : '查看逐字稿'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {transcriptDomain && (
            <div className="gateway-transcript-panel">
              {transcriptLoading && <div className="loading-box">載入逐字稿中…</div>}
              {transcriptError && <div className="error-box">載入逐字稿失敗：{transcriptError}</div>}
              {transcriptData && (
                <>
                  <p className="form-note">{domainLabel(transcriptDomain)} · 共 {transcriptData.messages.length} 則訊息</p>
                  <div className="gateway-chat-log">
                    {transcriptData.messages.map((m, i) => (
                      <div key={i} className={'gateway-chat-bubble gateway-chat-bubble--' + (m.type === 'user' ? 'user' : 'assistant')}>
                        <div className="gateway-chat-bubble__meta">{m.type === 'user' ? '你' : '管家'} · {fmtTime(m.timestamp)}</div>
                        <div className="gateway-chat-bubble__text">{m.text}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <h2>背景任務</h2>
          <span className="card__meta">每 15 秒自動更新</span>
        </div>
        <div className="card__body">
          {tasksError && <div className="error-box">載入失敗：{tasksError}</div>}
          {!tasks && !tasksError && <div className="loading-box">載入中…</div>}
          {tasks && tasks.length === 0 && <p className="empty">目前沒有背景任務紀錄。</p>}
          {tasks && tasks.length > 0 && (
            <div className="preview-table-wrap">
              <table className="preview-table gateway-table">
                <thead>
                  <tr><th>情境</th><th>描述</th><th>狀態</th><th>提交時間</th></tr>
                </thead>
                <tbody>
                  {tasks.map((t) => (
                    <tr key={t.claude_session_id}>
                      <td>{domainLabel(t.domain)}</td>
                      <td className="gateway-table__desc">{t.description || '—'}</td>
                      <td><span className={'badge ' + statusBadgeClass(t.status)}>{t.status}</span></td>
                      <td>{t.submitted_at ? fmtTime(t.submitted_at) : '（歷史紀錄，無提交時間）'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head"><h2>資源消耗</h2></div>
        <div className="card__body">
          {usageError && <div className="error-box">載入失敗：{usageError}</div>}
          {!usage && !usageError && <div className="loading-box">載入中…</div>}
          {usage && (
            <div className="stat-row">
              {[['today', '今日'], ['this_week', '本週'], ['this_month', '本月']].map(([key, label]) => (
                <div className="stat-tile" key={key}>
                  <div className="stat-tile__label">{label}花費（USD）</div>
                  <div className="stat-tile__value">
                    ${money(usage[key].total_cost_usd)}
                    {usage[key].has_unknown_cost && <span className="gateway-usage-note"> +未知</span>}
                  </div>
                  <div className="meta">{usage[key].calls} 次呼叫</div>
                </div>
              ))}
            </div>
          )}
          {usage && usage.today.calls > 0 && (
            <div className="preview-table-wrap" style={{ marginTop: '.8rem' }}>
              <table className="preview-table gateway-table">
                <thead><tr><th>情境（今日）</th><th>花費（USD）</th><th>次數</th><th>Input tokens</th><th>Output tokens</th></tr></thead>
                <tbody>
                  {Object.entries(usage.today.by_domain).map(([name, d]) => (
                    <tr key={name}>
                      <td>{domainLabel(name)}</td>
                      <td>${money(d.total_cost_usd)}{d.has_unknown_cost ? ' +未知' : ''}</td>
                      <td>{d.calls}</td>
                      <td>{d.input_tokens}</td>
                      <td>{d.output_tokens}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="form-note" style={{ marginTop: '.6rem' }}>
            背景任務沒有 USD 金額（只有 token 數，見「+未知」標記）——`claude agents --json`
            不回傳花費欄位，只能從逐字稿加總 token，無法換算成金額。
          </p>
        </div>
      </div>
    </div>
  )
}
