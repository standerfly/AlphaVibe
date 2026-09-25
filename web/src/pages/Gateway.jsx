import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../api/client.js'

/* 「管家」分頁（2026-08-31 新增）：STND Telegram 管家閘道的網頁監控＋
   聊天介面，串接 app/routers/gateway_monitor.py 的端點。完整方案見
   ~/.claude/plans/hazy-petting-wreath.md §6。

   跟其他分頁不同：這裡的資料完全不是這個 app 自己的 KBStore/SQLite，
   而是 telegram_gateway/state/ 底下的共用狀態檔——手機上用 Telegram 問過
   的話，這裡看得到；在這裡送出的訊息，也會被 Telegram 那條線記得（同一
   個 domain 共用同一段 session 記憶）。

   輪詢設計：對話清單／背景任務清單每 15 秒自動重新整理一次（背景任務
   可能在使用者沒有互動的情況下完成，需要自己冒出來，不像其他分頁只在
   使用者操作後才需要重抓）；資源消耗卡片變動較慢，跟著同一個輪詢週期
   一起刷新即可，不需要獨立頻率。

   2026-09-25「擴充三：Remote Control」新增：頂部連線卡片＋主題清單的
   收藏／搜尋／展開歷史／逐 session 連線按鈕＋新增 session modal。
   `active_remote_controls` 跟對話清單共用同一條輪詢（GET
   /api/gateway/conversations 回應內帶），不另開一條輪詢。 */

const POLL_INTERVAL_MS = 15000

// 2026-08-31「擴充：任意命名主題」：只有已知專案捷徑（cwd 指到真實
// 專案路徑）需要顯示名稱對照，其餘任意命名的主題直接顯示原始名稱
// （domainLabel() 的既有 fallback `DOMAIN_LABELS[name] || name` 不用改）。
const DOMAIN_LABELS = { alphavibe: 'AlphaVibe', harness: 'Harness', mytravel: 'MyTravel' }

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

// 已連線時長顯示（RC 卡片＋歷史 session 都用得到）——只顯示「已啟動 X
// 分鐘」，不做「已連接/等待連接」區分，見 plan「已識別但技術上沒有其他
// 選項」段落：目前找不到偵測手機是否真的連上的方式。
function fmtDuration(iso) {
  if (!iso) return '—'
  const start = new Date(iso).getTime()
  if (Number.isNaN(start)) return '—'
  const diffMin = Math.max(0, Math.round((Date.now() - start) / 60000))
  if (diffMin < 60) return `${diffMin} 分鐘`
  const hours = Math.floor(diffMin / 60)
  const mins = diffMin % 60
  return mins ? `${hours} 小時 ${mins} 分鐘` : `${hours} 小時`
}

// 新增 session modal 的 cwd 選項——固定四選一，路徑寫死顯示（不開放
// 自訂路徑，見 plan §4／已確認產品決定2）。
const CWD_CHOICES = [
  { value: 'home', label: '家目錄（一般用途，無特定專案）', path: '/Users/stander' },
  { value: 'alphavibe', label: 'alphavibe', path: '/Users/stander/My_project/AlphaVibe' },
  { value: 'harness', label: 'harness', path: '/Users/stander/My_project/AI/harness' },
  { value: 'mytravel', label: 'mytravel', path: '/Users/stander/My_project/mytravel' },
]

function RadioIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
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

  // ---- Remote Control（2026-09-25 新增）----
  const [activeRc, setActiveRc] = useState([])
  const [rcStoppingId, setRcStoppingId] = useState(null)
  const [rcConnectingSessionId, setRcConnectingSessionId] = useState(null)
  const [rcSuccess, setRcSuccess] = useState(null) // {name, url} | null
  const [copiedFlash, setCopiedFlash] = useState(null) // 最近一次複製成功的文字內容

  const [topicFilter, setTopicFilter] = useState('')
  const [expandedDomains, setExpandedDomains] = useState(() => new Set())
  const [favBusyName, setFavBusyName] = useState(null)

  const [sessionModalOpen, setSessionModalOpen] = useState(false)
  const [cwdChoice, setCwdChoice] = useState('home')
  const [sessionName, setSessionName] = useState('')
  const [sessionModalBusy, setSessionModalBusy] = useState(false)
  const [sessionModalError, setSessionModalError] = useState(null)

  const refreshConversations = useCallback(() => {
    return apiGet('/api/gateway/conversations')
      .then((d) => {
        setDomains(d.domains)
        setLockdown(d.lockdown)
        setActiveRc(d.active_remote_controls || [])
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

  // 主題清單搜尋（純前端 .filter()）——後端已經把排序做好（星號優先＋
  // last_active 新到舊），這裡只篩選、不重排，維持後端回傳的順序。
  const filteredDomains = useMemo(() => {
    if (!domains) return null
    const q = topicFilter.trim().toLowerCase()
    if (!q) return domains
    return domains.filter((d) => (
      d.name.toLowerCase().includes(q) || domainLabel(d.name).toLowerCase().includes(q)
    ))
  }, [domains, topicFilter])

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

  // ---- Remote Control 操作（2026-09-25 新增）----

  async function handleCopy(text) {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopiedFlash(text)
      setTimeout(() => setCopiedFlash((cur) => (cur === text ? null : cur)), 1200)
    } catch (_err) {
      // 剪貼簿權限不足、或非安全環境（http）時 clipboard API 可能整個
      // 不存在——靜默失敗，使用者仍能手動選取網址文字複製，不阻斷流程。
    }
  }

  async function handleStopRc(rcId) {
    setActionError(null)
    setRcStoppingId(rcId)
    try {
      await apiDelete(`/api/gateway/remote-control/${encodeURIComponent(rcId)}`)
      await refreshConversations()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setRcStoppingId(null)
    }
  }

  async function handleConnectRc(domain, sessionId) {
    setActionError(null)
    setRcConnectingSessionId(sessionId)
    try {
      const res = await apiPost('/api/gateway/remote-control', { domain, session_id: sessionId })
      setRcSuccess({ name: res.rc_name || domainLabel(domain), url: res.rc_url })
      await refreshConversations()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setRcConnectingSessionId(null)
    }
  }

  async function handleToggleFavorite(d) {
    const next = !d.is_favorite
    setFavBusyName(d.name)
    setActionError(null)
    // 樂觀更新：先反映在畫面上，失敗再還原。
    setDomains((cur) => (cur ? cur.map((x) => (x.name === d.name ? { ...x, is_favorite: next } : x)) : cur))
    try {
      await apiPatch(`/api/gateway/conversations/${encodeURIComponent(d.name)}/favorite`, { is_favorite: next })
      await refreshConversations()
    } catch (err) {
      setDomains((cur) => (cur ? cur.map((x) => (x.name === d.name ? { ...x, is_favorite: !next } : x)) : cur))
      setActionError(err.message)
    } finally {
      setFavBusyName(null)
    }
  }

  function toggleExpand(name) {
    setExpandedDomains((cur) => {
      const next = new Set(cur)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function openSessionModal() {
    setCwdChoice('home')
    setSessionName('')
    setSessionModalError(null)
    setSessionModalOpen(true)
  }

  function closeSessionModal() {
    if (sessionModalBusy) return
    setSessionModalOpen(false)
  }

  async function handleCreateSession() {
    setSessionModalError(null)
    setSessionModalBusy(true)
    const body = { cwd_choice: cwdChoice }
    // 選家目錄以外的捷徑時，主題名稱＝捷徑名稱、不可自訂（後端規則），
    // 這裡就不送 name，讓後端依 cwd_choice 自己決定；只有選家目錄且
    // 使用者有填才送出自訂名稱。
    if (cwdChoice === 'home' && sessionName.trim()) {
      body.name = sessionName.trim()
    }
    try {
      const res = await apiPost('/api/gateway/sessions', body)
      setSessionModalOpen(false)
      setRcSuccess({ name: domainLabel(res.domain), url: res.rc_url })
      await refreshConversations()
    } catch (err) {
      setSessionModalError(err.message)
    } finally {
      setSessionModalBusy(false)
    }
  }

  // 依 session_id 找目前是否有有效 RC 連線；找不到回 null。
  function findActiveRc(sessionId) {
    if (!sessionId) return null
    return activeRc.find((rc) => rc.session_id === sessionId) || null
  }

  function renderRcButton(domain, sessionId, key) {
    if (!sessionId) {
      return (
        <button
          key={key}
          type="button"
          className="gateway-rc-icon-btn"
          disabled
          title="尚未有 session，無法開啟 Remote Control"
        >
          <RadioIcon />
        </button>
      )
    }
    const active = findActiveRc(sessionId)
    if (active) {
      return (
        <button
          key={key}
          type="button"
          className="gateway-rc-icon-btn is-connected"
          disabled
          title="已開啟 Remote Control"
        >
          <RadioIcon />
        </button>
      )
    }
    const busy = rcConnectingSessionId === sessionId
    return (
      <button
        key={key}
        type="button"
        className="gateway-rc-icon-btn"
        disabled={busy || isLocked}
        title={busy ? '連線中…' : '開啟 Remote Control'}
        onClick={() => handleConnectRc(domain, sessionId)}
      >
        <RadioIcon />
      </button>
    )
  }

  return (
    <div>
      <div className="page-title"><h1>管家</h1></div>

      {isLocked && (
        <div className="gateway-lockdown-banner">
          <span className="gateway-lockdown-banner__title">系統已鎖定（LOCKDOWN）</span>
          <span>
            聊天、背景任務與建立新連線已停用，唯讀查詢、停止既有 Remote Control 不受影響。
            解鎖需要在本機手動刪除旗標檔。
            {lockdown && lockdown.info && lockdown.info.locked_at
              ? `（鎖定於 ${fmtTime(lockdown.info.locked_at)}）` : ''}
          </span>
        </div>
      )}

      {/* ============ Remote Control 連線管理（2026-09-25 新增） ============ */}
      <div className="card">
        <div className="card__head">
          <h2>Remote Control{activeRc.length > 0 ? `（${activeRc.length} 個連線中）` : ''}</h2>
          <span className="card__meta">閒置 30 分鐘自動停止</span>
        </div>
        <div className="card__body">
          {actionError && <div className="error-box">{actionError}</div>}
          {activeRc.length === 0 ? (
            <p className="empty">目前沒有連線中的 Remote Control——在下方主題清單點選連線圖示即可建立一個。</p>
          ) : (
            <div className="gateway-rc-list">
              {activeRc.map((rc) => (
                <div className="gateway-rc-item" key={rc.id}>
                  <span className="gateway-rc-dot" />
                  <div className="gateway-rc-main">
                    <div className="gateway-rc-name">{rc.rc_name || domainLabel(rc.domain)}</div>
                    <div className="gateway-rc-meta">已連線 {fmtDuration(rc.started_at)}</div>
                    <div className="gateway-rc-url mono">{rc.rc_url}</div>
                  </div>
                  <div className="gateway-rc-actions">
                    <button
                      type="button"
                      className="gateway-rc-icon-btn"
                      title="複製連結"
                      onClick={() => handleCopy(rc.rc_url)}
                    >
                      <CopyIcon />
                    </button>
                    {copiedFlash === rc.rc_url && <span className="gateway-rc-copied">已複製</span>}
                    <button
                      type="button"
                      className="btn-danger-outline btn-sm"
                      disabled={rcStoppingId === rc.id}
                      onClick={() => handleStopRc(rc.id)}
                    >
                      {rcStoppingId === rc.id ? '停止中…' : '停止連線'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <h2>跟管家對話</h2>
          <span className="card__meta">跟 Telegram 共用同一段對話記憶（依 domain 區分）</span>
        </div>
        <div className="card__body">
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '.6rem' }}>
            <span className="card__meta">每 15 秒自動更新</span>
            <button type="button" className="btn btn-sm" disabled={isLocked} onClick={openSessionModal}>
              ＋ 新增 Session
            </button>
          </div>
        </div>
        <div className="card__body">
          {convError && <div className="error-box">載入失敗：{convError}</div>}
          {!domains && !convError && <div className="loading-box">載入中…</div>}
          {domains && (
            <>
              <div className="stocklist-search">
                <input
                  type="text"
                  placeholder="搜尋主題名稱…"
                  value={topicFilter}
                  onChange={(e) => setTopicFilter(e.target.value)}
                />
              </div>
              <p className="form-note">
                點 ★ 把常用主題釘在清單最上面；點展開箭頭可以看這個主題底下的歷史 session
                （Remote Control 是綁在 session 上，不是主題上——同一個主題如果用過 /new 或
                「新增 Session」，會有不只一個 session，各自可以獨立開啟連線）。
              </p>
              <div className="preview-table-wrap">
                <table className="preview-table gateway-table">
                  <thead>
                    <tr>
                      <th>情境</th><th>Session</th><th>上次活躍</th><th>進行中任務</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDomains.map((d) => {
                      const hasHistory = !!(d.session_id || (d.session_history && d.session_history.length > 0))
                      const isExpanded = expandedDomains.has(d.name)
                      const historyItems = [
                        { session_id: d.session_id, started_at: d.started_at, last_active_at: d.last_active, archived_at: null, isCurrent: true },
                        ...(d.session_history || []),
                      ].filter((item) => item.session_id)
                      return (
                        <Fragment key={d.name}>
                          <tr>
                            <td className="gateway-topic-name">
                              {hasHistory ? (
                                <button
                                  type="button"
                                  className={'gateway-expand-btn' + (isExpanded ? ' is-open' : '')}
                                  onClick={() => toggleExpand(d.name)}
                                  title="展開歷史 session"
                                >▸</button>
                              ) : (
                                <span className="gateway-expand-spacer" />
                              )}
                              <button
                                type="button"
                                className={'gateway-fav-star' + (d.is_favorite ? ' is-fav' : '')}
                                disabled={favBusyName === d.name}
                                title={d.is_favorite ? '取消收藏' : '收藏，排到清單最前面'}
                                onClick={() => handleToggleFavorite(d)}
                              >★</button>
                              {domainLabel(d.name)}
                            </td>
                            <td>{d.session_id ? d.session_id.slice(0, 8) + '…' : '（尚未開始）'}</td>
                            <td>{fmtTime(d.last_active)}</td>
                            <td>{d.has_inflight_task
                              ? <span className="badge badge-neutral">進行中</span>
                              : <span className="meta">—</span>}</td>
                            <td>
                              <div className="gateway-row-actions">
                                {d.session_id && (
                                  <button type="button" className="btn-muted btn-sm" onClick={() => handleToggleTranscript(d.name)}>
                                    {transcriptDomain === d.name ? '收起逐字稿' : '查看逐字稿'}
                                  </button>
                                )}
                                {renderRcButton(d.name, d.session_id, d.name + '-current-rc')}
                              </div>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="gateway-session-history-row">
                              <td colSpan={5}>
                                <div className="gateway-session-history">
                                  {historyItems.map((item) => (
                                    <div className="gateway-session-history__item" key={item.session_id}>
                                      <div className="gateway-session-history__main">
                                        <div className={'gateway-session-history__label' + (item.isCurrent ? ' is-current' : '')}>
                                          {item.isCurrent ? '目前使用中' : '已封存（因為打過 /new 或建立了新 session）'}
                                        </div>
                                        <div className="gateway-session-history__meta">
                                          {fmtTime(item.started_at)} 開始 · 最後訊息 {fmtTime(item.last_active_at)}
                                          {item.archived_at ? ` · 封存於 ${fmtTime(item.archived_at)}` : ''}
                                        </div>
                                        <div className="gateway-session-history__id mono">{item.session_id.slice(0, 8)}…</div>
                                      </div>
                                      {renderRcButton(d.name, item.session_id, item.session_id + '-rc')}
                                    </div>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {filteredDomains.length === 0 && <p className="empty">沒有符合搜尋條件的主題。</p>}
            </>
          )}

          {rcSuccess && (
            <div className="gateway-rc-success">
              <div className="gateway-rc-success__title">
                {rcSuccess.name} 已開啟 Remote Control
                <button type="button" className="gateway-rc-success__close" title="關閉" onClick={() => setRcSuccess(null)}>×</button>
              </div>
              <p className="form-note" style={{ margin: '.2rem 0 0' }}>已啟動，掃描或點開下方連結即可用手機接手：</p>
              <div className="gateway-rc-success__url-row">
                <span className="mono">{rcSuccess.url}</span>
                <button type="button" className="btn-muted btn-sm" onClick={() => handleCopy(rcSuccess.url)}>
                  {copiedFlash === rcSuccess.url ? '已複製' : '複製'}
                </button>
              </div>
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
            不回傳花費欄位，只能從逐字稿加總 token，無法換算成金額。RC 連線期間手機端的用量
            目前也不記錄在這裡（見 README 已知限制）。
          </p>
        </div>
      </div>

      {/* ============ Modal：新增 Session（2026-09-25 新增） ============ */}
      {sessionModalOpen && (
        <div
          className="gateway-modal-backdrop"
          onClick={(e) => { if (e.target === e.currentTarget) closeSessionModal() }}
        >
          <div className="gateway-modal">
            <h3>新增 Session</h3>
            <p className="form-note">建立一個新的工作情境，之後可以在 Telegram 或這裡繼續對話，並立即開啟 Remote Control。</p>
            {sessionModalError && <div className="error-box">{sessionModalError}</div>}
            <div className="form-field">
              <label htmlFor="rc-cwd-select">工作目錄</label>
              <select
                id="rc-cwd-select"
                value={cwdChoice}
                disabled={sessionModalBusy}
                onChange={(e) => setCwdChoice(e.target.value)}
              >
                {CWD_CHOICES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.value === 'home' ? c.label : `${c.label} — ${c.path}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field" style={{ marginTop: '.7rem' }}>
              <label htmlFor="rc-session-name">主題名稱</label>
              <input
                id="rc-session-name"
                type="text"
                value={cwdChoice === 'home' ? sessionName : cwdChoice}
                disabled={sessionModalBusy || cwdChoice !== 'home'}
                placeholder="例如：報稅資料整理（留空自動命名）"
                onChange={(e) => setSessionName(e.target.value)}
              />
              {cwdChoice !== 'home' && (
                <p className="form-note">選擇專案捷徑時，主題名稱固定＝捷徑名稱，不可自訂。</p>
              )}
              {cwdChoice === 'home' && (
                <p className="form-note">若剛好跟已存在的主題同名，會把目前 session 歸檔、開一個全新 session。</p>
              )}
            </div>
            <div className="form-actions" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="btn-muted" disabled={sessionModalBusy} onClick={closeSessionModal}>
                取消
              </button>
              <button type="button" className="btn" disabled={sessionModalBusy} onClick={handleCreateSession}>
                {sessionModalBusy ? '建立中…（可能要等幾秒）' : '建立'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
