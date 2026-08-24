import { useEffect, useRef, useState } from 'react'
import { apiPost } from '../api/client.js'

/* 快速輸入面板（2026-08-24 新增，Q-046 待辦第1項）：把舊版
   poc/kb-mcp/report.py:836-918 _render_quick_input_section() 的5個表單
   接上新版 app/+web/ 前端，串接既有已完成的後端路由
   （app/routers/actions.py 四個＋app/routers/holdings_import.py 兩個）。
   後端邏輯完全不動，這裡只做輸入介面。

   放在投資分頁（Dashboard.jsx）頁首、預設收合的 <details>——比照舊版
   「常駐但不擠佔版面」的定位，展開才佔空間。內部用 5 個 pill tab
   一次只顯示一個表單（不是5個表單全部攤開），對手機使用者比較好操作
   （PO主要用手機瀏覽，見 supporting-artifacts/
   2026-07-30-mobile-dashboard-uiux-research.md）。

   每個表單各自管理自己的 busy/error/notice/success 狀態
   （useFormState()），彼此獨立、切換 tab 不會互相污染。三種訊息語意：
   - error（紅）：後端 4xx／前端必填檢查失敗，不自動消失，讓使用者
     看得到、有機會修正後重送。
   - notice（黃）：語意上不算失敗、但需要人工留意的部分成功結果
     （例如 watchlist 立場衝突、批次解析有查無代碼的名稱／無法解析的
     行）。同樣不自動消失。
   - success（綠）：完全成功，4秒後自動消失，避免使用者以為要手動關掉。 */

function useFormState() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [success, setSuccess] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  function flashSuccess(msg) {
    setError(null)
    setNotice(null)
    setSuccess(msg)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setSuccess(null), 4000)
  }
  function flashNotice(msg) {
    setError(null)
    setSuccess(null)
    setNotice(msg)
  }
  function flashError(msg) {
    setNotice(null)
    setSuccess(null)
    setError(msg)
  }

  return { busy, setBusy, error, notice, success, flashSuccess, flashNotice, flashError }
}

// 本地時區的 YYYY-MM-DD（不能直接用 toISOString：那是UTC，台灣時間
// 凌晨0~8點會被切到前一天）。
function todayStr() {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function StatusBoxes({ error, notice, success }) {
  return (
    <>
      {error && <div className="error-box">{error}</div>}
      {notice && <div className="notice-box">{notice}</div>}
      {success && <div className="success-box">{success}</div>}
    </>
  )
}

/* ---- 1. 加自選股／加入研究：POST /api/watchlist ---- */
function WatchlistForm({ onSuccess }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const { busy, setBusy, error, notice, success, flashSuccess, flashNotice, flashError } = useFormState()

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmedCode = code.trim()
    if (!trimmedCode) { flashError('代碼為必填'); return }
    setBusy(true)
    try {
      const res = await apiPost('/api/watchlist', {
        code: trimmedCode,
        name: name.trim() || undefined,
      })
      if (res.conflict) {
        // save_stance() 判定為立場衝突時不會寫入，這不是HTTP錯誤（200），
        // 但語意上不算「成功加入」，用notice（黃）而非success（綠）。
        flashNotice(res.hint || `${trimmedCode} 已有不同立場紀錄，未覆寫`)
      } else {
        flashSuccess(`已加入自選股：${trimmedCode}`)
        setCode('')
        setName('')
        onSuccess && onSuccess()
      }
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="form-grid">
        <div className="form-field">
          <label htmlFor="qi-watchlist-code">代碼</label>
          <input id="qi-watchlist-code" type="text" value={code}
                 onChange={(e) => setCode(e.target.value)} required />
        </div>
        <div className="form-field">
          <label htmlFor="qi-watchlist-name">名稱（選填）</label>
          <input id="qi-watchlist-name" type="text" value={name}
                 onChange={(e) => setName(e.target.value)} />
        </div>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? '送出中…' : '加入自選股'}
        </button>
      </div>
      <StatusBoxes error={error} notice={notice} success={success} />
    </form>
  )
}

/* ---- 2. 記一筆交易：POST /api/trades ---- */
function TradeForm() {
  const [form, setForm] = useState({
    code: '', name: '', action: '買', shares: '', price: '',
    date: todayStr(), add_sequence: '',
  })
  const { busy, setBusy, error, success, flashSuccess, flashError } = useFormState()

  function update(key, value) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const code = form.code.trim()
    if (!code) { flashError('代碼為必填'); return }
    if (form.shares === '' || Number.isNaN(Number(form.shares))) {
      flashError('股數為必填，且需為數字'); return
    }
    if (form.price === '' || Number.isNaN(Number(form.price))) {
      flashError('價格為必填，且需為數字'); return
    }
    if (!form.date) { flashError('日期為必填'); return }
    setBusy(true)
    try {
      const shares = Number(form.shares)
      const price = Number(form.price)
      const res = await apiPost('/api/trades', {
        code,
        name: form.name.trim() || undefined,
        action: form.action,
        shares,
        price,
        date: form.date,
        add_sequence: form.add_sequence === '' ? undefined : Number(form.add_sequence),
      })
      flashSuccess(`已記錄交易：${res.action} ${res.code} ${shares}股 @ ${price}`)
      setForm({ code: '', name: '', action: '買', shares: '', price: '', date: form.date, add_sequence: '' })
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="form-grid">
        <div className="form-field">
          <label htmlFor="qi-trade-code">代碼</label>
          <input id="qi-trade-code" type="text" value={form.code}
                 onChange={(e) => update('code', e.target.value)} required />
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-name">名稱（選填）</label>
          <input id="qi-trade-name" type="text" value={form.name}
                 onChange={(e) => update('name', e.target.value)} />
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-action">買／賣</label>
          <select id="qi-trade-action" value={form.action}
                  onChange={(e) => update('action', e.target.value)}>
            <option value="買">買</option>
            <option value="賣">賣</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-shares">股數</label>
          <input id="qi-trade-shares" type="number" step="1" min="0" value={form.shares}
                 onChange={(e) => update('shares', e.target.value)} required />
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-price">價格</label>
          <input id="qi-trade-price" type="number" step="0.01" min="0" value={form.price}
                 onChange={(e) => update('price', e.target.value)} required />
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-date">日期</label>
          <input id="qi-trade-date" type="date" value={form.date}
                 onChange={(e) => update('date', e.target.value)} required />
        </div>
        <div className="form-field">
          <label htmlFor="qi-trade-addseq">加碼序號（選填，賣出會忽略）</label>
          <input id="qi-trade-addseq" type="number" step="1" min="0" value={form.add_sequence}
                 onChange={(e) => update('add_sequence', e.target.value)} />
        </div>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? '送出中…' : '記錄交易'}
        </button>
      </div>
      <StatusBoxes error={error} notice={null} success={success} />
    </form>
  )
}

/* ---- 3. 老芋頭進出（批次貼文字）：POST /api/laoyutou-trades ---- */
function LaoyutouForm() {
  const [text, setText] = useState('')
  const { busy, setBusy, error, notice, success, flashSuccess, flashNotice, flashError } = useFormState()

  async function handleSubmit(e) {
    e.preventDefault()
    if (!text.trim()) { flashError('內容不可空白'); return }
    setBusy(true)
    try {
      const res = await apiPost('/api/laoyutou-trades', { text })
      const savedCount = (res.saved || []).length
      const unresolved = res.unresolved_names || []
      const unparsed = res.unparsed_lines || []
      if (unresolved.length === 0 && unparsed.length === 0) {
        flashSuccess(`解析完成，共 ${res.total_parsed} 筆全部成功寫入`)
      } else {
        const parts = [`解析完成：共 ${res.total_parsed} 筆，成功寫入 ${savedCount} 筆`]
        if (unresolved.length) parts.push(`查無對應代碼：${unresolved.join('、')}`)
        if (unparsed.length) parts.push(`無法解析 ${unparsed.length} 行，請人工核對原始內容`)
        flashNotice(parts.join('；'))
      }
      setText('')
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <p className="form-note">
        整段貼上，不用逐欄位填。第一行是8位數日期（例如20260729），接著可以先寫一行原因、
        再接交易行（格式：價格＋買進/賣出/買回/回補＋股數＋股/張＋名稱＋可選括號註記，
        例如「365賣出500股聯鈞（出清）」）。
      </p>
      <div className="form-field">
        <textarea rows="8" value={text} placeholder={'20260729\n殺估值，獲利跟不上股價，清倉換股\n365賣出500股聯鈞（出清）'}
                   onChange={(e) => setText(e.target.value)} required />
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? '解析並記錄中…' : '解析並批次記錄'}
        </button>
      </div>
      <StatusBoxes error={error} notice={notice} success={success} />
    </form>
  )
}

/* ---- 4. 交易明細表（批次貼文字）：POST /api/trade-ledger ---- */
function TradeLedgerForm() {
  const [text, setText] = useState('')
  const { busy, setBusy, error, notice, success, flashSuccess, flashNotice, flashError } = useFormState()

  async function handleSubmit(e) {
    e.preventDefault()
    if (!text.trim()) { flashError('內容不可空白'); return }
    setBusy(true)
    try {
      const res = await apiPost('/api/trade-ledger', { text })
      const savedCount = (res.saved || []).length
      const unresolved = res.unresolved_names || []
      const unparsed = res.unparsed_lines || []
      const duplicates = res.duplicates_skipped || []
      if (unresolved.length === 0 && unparsed.length === 0 && duplicates.length === 0) {
        flashSuccess(`解析完成，共 ${res.total_parsed} 筆全部成功寫入`)
      } else {
        const parts = [`解析完成：共 ${res.total_parsed} 筆，成功寫入 ${savedCount} 筆`]
        if (unresolved.length) parts.push(`查無對應代碼：${unresolved.join('、')}`)
        if (unparsed.length) parts.push(`無法解析 ${unparsed.length} 行`)
        if (duplicates.length) parts.push(`委託書號重複已略過 ${duplicates.length} 筆`)
        flashNotice(parts.join('；'))
      }
      setText('')
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <p className="form-note">
        整段貼上券商App/網站匯出的交易明細表文字（PO自己的買賣紀錄，跟老芋頭進出是不同的表）。
        每一列自帶日期，送出就直接解析並批次記錄，會自動算好每筆買進的加碼序號。
      </p>
      <div className="form-field">
        <textarea rows="8" value={text}
                   placeholder={'交易日期: 115/07/22 - 115/07/29 頁次: 1\n115/07/22 OT賣 中美晶 50 242.50 ... 12,085(付) k-0116-00'}
                   onChange={(e) => setText(e.target.value)} required />
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? '解析並記錄中…' : '解析並批次記錄'}
        </button>
      </div>
      <StatusBoxes error={error} notice={notice} success={success} />
    </form>
  )
}

/* ---- 5. 貼庫存清單匯入（兩步驟）：POST /api/holdings/preview →
   POST /api/holdings/confirm。preview 純唯讀，只有 confirm 真的寫入
   資料庫——UI 要清楚區分兩個階段，避免使用者誤以為貼上就已經存進去。
   preview 回傳的 rows 就是 confirm 預期的格式，這裡原樣送回（不提供
   逐筆調整介面，超出這次範圍，見任務回報）。 ---- */
function HoldingsImportForm({ onSuccess }) {
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const { busy, setBusy, error, notice, success, flashSuccess, flashNotice, flashError } = useFormState()

  async function handlePreview(e) {
    e.preventDefault()
    if (!text.trim()) { flashError('內容不可空白'); return }
    setBusy(true)
    try {
      const res = await apiPost('/api/holdings/preview', { text })
      setPreview(res)
      if ((res.unparsed_lines || []).length > 0) {
        flashNotice(`已解析 ${res.total_parsed} 筆，另有 ${res.unparsed_lines.length} 行無法解析，請核對下方預覽`)
      } else if ((res.rows || []).length === 0) {
        flashNotice('沒有解析出任何可存入的資料，請確認貼上的內容')
      }
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirm() {
    if (!preview || !preview.rows || preview.rows.length === 0) return
    setBusy(true)
    try {
      const res = await apiPost('/api/holdings/confirm', { rows: preview.rows })
      flashSuccess(`已存入 ${res.count} 筆持股快照（快照日期 ${res.snapshot_date}）`)
      setPreview(null)
      setText('')
      onSuccess && onSuccess()
    } catch (err) {
      flashError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleBack() {
    setPreview(null)
  }

  if (!preview) {
    return (
      <form onSubmit={handlePreview}>
        <p className="form-note">
          整段貼上券商App/網站匯出的零股庫存表文字。解析後會先顯示預覽（含與上次快照的差異比對），
          確認無誤才會真的存入，不會貼上就直接寫入資料庫。
        </p>
        <div className="form-field">
          <textarea rows="8" value={text} placeholder="股票代號 股票名稱 庫存股數 ..."
                     onChange={(e) => setText(e.target.value)} required />
        </div>
        <div className="form-actions">
          <button type="submit" className="btn" disabled={busy}>
            {busy ? '解析中…' : '解析並預覽'}
          </button>
        </div>
        <StatusBoxes error={error} notice={notice} success={success} />
      </form>
    )
  }

  const diff = preview.diff || { added: [], removed: [], changed: [] }
  const rows = preview.rows || []

  return (
    <div>
      <div className="notice-box">
        ⚠️ 這只是預覽，尚未寫入資料庫。確認資料無誤後才按「確認寫入」——這是新增一筆最新快照，
        不會覆蓋或刪除歷史紀錄。
      </div>
      <div className="preview-table-wrap">
        <table className="preview-table">
          <thead>
            <tr><th>代碼</th><th>名稱</th><th>股數</th><th>成本</th><th>興櫃</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={5} className="empty">沒有可存入的資料</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.code}>
                <td>{r.code}</td>
                <td>{r.name || '—'}</td>
                <td>{r.shares != null ? r.shares : '—'}</td>
                <td>{r.avg_cost != null ? r.avg_cost : '—'}</td>
                <td>{r.is_emerging ? '是' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="form-note">
        與上次快照（{preview.previous_snapshot_date || '無'}，共 {preview.previous_count} 筆）比較：
        新增 {diff.added.length} 檔、消失 {diff.removed.length} 檔（不代表已出清，只是這次帳單沒印到）、
        股數變動 {diff.changed.length} 檔。
      </p>
      <div className="form-actions">
        <button type="button" className="btn" disabled={busy || rows.length === 0} onClick={handleConfirm}>
          {busy ? '寫入中…' : `確認寫入（共 ${rows.length} 筆）`}
        </button>
        <button type="button" className="btn-muted" disabled={busy} onClick={handleBack}>
          取消，重新貼上
        </button>
      </div>
      <StatusBoxes error={error} notice={null} success={success} />
    </div>
  )
}

const TABS = [
  { key: 'watchlist', label: '加自選股' },
  { key: 'trade', label: '記交易' },
  { key: 'laoyutou', label: '老芋頭進出' },
  { key: 'ledger', label: '交易明細表' },
  { key: 'holdings', label: '貼庫存匯入' },
]

/* onDataChanged：送出後可能影響目前投資分頁股票列表的操作（加自選股會
   新增立場、確認庫存匯入會改變庫存快照）完成後呼叫，讓外層重新查詢
   列表。記交易／老芋頭進出／交易明細表不影響 is_holding／stance 的
   判定依據（見 poc/kb-mcp/report.py _tracked_stock_rows()：庫存判定看
   holdings 快照表，不看 trade_ledger／laoyutou_trades），所以這三個
   表單刻意不觸發列表重整。 */
export default function QuickInputPanel({ onDataChanged }) {
  const [activeTab, setActiveTab] = useState('watchlist')

  return (
    <details className="quick-input">
      <summary>快速輸入</summary>
      <div className="quick-input__body">
        <div className="filter-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={'filter-tab' + (activeTab === t.key ? ' active' : '')}
              onClick={() => setActiveTab(t.key)}
            >{t.label}</button>
          ))}
        </div>
        {activeTab === 'watchlist' && <WatchlistForm onSuccess={onDataChanged} />}
        {activeTab === 'trade' && <TradeForm />}
        {activeTab === 'laoyutou' && <LaoyutouForm />}
        {activeTab === 'ledger' && <TradeLedgerForm />}
        {activeTab === 'holdings' && <HoldingsImportForm onSuccess={onDataChanged} />}
      </div>
    </details>
  )
}
