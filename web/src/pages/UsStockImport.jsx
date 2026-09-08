import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet, apiPost } from '../api/client.js'
import { ChevronLeftIcon } from '../components/icons.jsx'

/* 美股交易匯入核對確認畫面（Phase 3 US1，T017）——**只實作 STEP 2**。

   資料流程（見 app/routers/us_stocks.py 檔頭 docstring「STEP 2」設計
   取捨說明，這裡重申給前端讀者）：使用者在跟 Claude 的對話中貼交易
   截圖，Claude 讀圖轉文字後呼叫 parse_and_save_us_trade（MCP 工具）
   直接寫入 us_trades——這一步已經完成，本頁不負責、也不提供任何截圖
   上傳/拖曳 UI（STEP 1，PO 已明確確認不做，見 tasks.md 開頭範圍註記）。

   本頁做的事：GET /api/us-stocks/trades/recent 抓「Claude 剛剛在對話中
   解析寫入」的最近紀錄，呈現成可編輯表格，讓使用者核對 OCR/理解可能
   出錯的欄位（股數、價格、日期、代號、買賣別）；按「確認」後把（可能
   已修正的）整批資料 POST 到 /api/us-stocks/trades/confirm，逐筆呼叫
   store.update_trade() 落庫。

   視覺沿用既有 .preview-table／.form-field／.btn 系列樣式（見
   web/src/pages/Assets.jsx／web/src/styles/app.css 既有慣例），不發明
   新的表格/表單視覺語言。 */

const ACTION_LABELS = { buy: '買進', sell: '賣出' }

function EditableCell({ value, onChange, type = 'text', width }) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: width || '100%', border: '1px solid var(--rule)', borderRadius: '4px',
        background: 'var(--paper)', color: 'var(--ink)', font: 'inherit',
        fontSize: '.82rem', padding: '.25rem .35rem',
      }}
    />
  )
}

export default function UsStockImport() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  function refresh() {
    setError(null)
    setResult(null)
    return apiGet('/api/us-stocks/trades/recent?limit=20')
      .then((d) => setRows(d.trades.map((t) => ({ ...t }))))
      .catch((err) => setError(err.message))
  }

  useEffect(() => { refresh() }, [])

  function updateField(id, field, value) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)))
  }

  async function handleConfirm() {
    if (!rows || rows.length === 0) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const payload = {
        trades: rows.map((r) => ({
          id: r.id,
          ticker: r.ticker,
          trade_date: r.trade_date,
          action: r.action,
          shares: Number(r.shares),
          price: Number(r.price),
        })),
      }
      const out = await apiPost('/api/us-stocks/trades/confirm', payload)
      setResult(out)
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <Link to="/us-stocks" className="back-link">
        <ChevronLeftIcon width={16} height={16} /> 回美股
      </Link>
      <div className="page-title"><h1>交易匯入核對</h1></div>
      <p className="meta">
        把交易截圖貼給 Claude，Claude 讀圖轉文字後會直接存成下方的紀錄。
        這裡只負責核對——欄位打錯的話直接修正，按「確認」送出即可。
      </p>

      {error && <div className="error-box">操作失敗：{error}</div>}
      {!rows && !error && <div className="loading-box">載入中…</div>}

      {rows && rows.length === 0 && (
        <div className="placeholder-box">
          <div className="placeholder-box__title">尚無待核對交易</div>
          <div className="placeholder-box__text">
            把交易截圖貼給 Claude 之後，這裡會顯示最近解析出來的紀錄。
          </div>
        </div>
      )}

      {rows && rows.length > 0 && (
        <>
          <div className="preview-table-wrap">
            <table className="preview-table">
              <thead>
                <tr>
                  <th>代號</th>
                  <th>日期</th>
                  <th>買賣</th>
                  <th>股數</th>
                  <th>價格</th>
                  <th>金額（自動計算）</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <EditableCell value={r.ticker}
                        onChange={(v) => updateField(r.id, 'ticker', v.toUpperCase())}
                        width="5rem" />
                    </td>
                    <td>
                      <EditableCell value={r.trade_date} type="date"
                        onChange={(v) => updateField(r.id, 'trade_date', v)} width="9rem" />
                    </td>
                    <td>
                      <select value={r.action}
                        onChange={(e) => updateField(r.id, 'action', e.target.value)}>
                        <option value="buy">{ACTION_LABELS.buy}</option>
                        <option value="sell">{ACTION_LABELS.sell}</option>
                      </select>
                    </td>
                    <td>
                      <EditableCell value={r.shares} type="number"
                        onChange={(v) => updateField(r.id, 'shares', v)} width="5rem" />
                    </td>
                    <td>
                      <EditableCell value={r.price} type="number"
                        onChange={(v) => updateField(r.id, 'price', v)} width="6rem" />
                    </td>
                    <td>{(Number(r.shares) * Number(r.price)).toLocaleString('en-US', { maximumFractionDigits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="form-actions">
            <button className="btn" onClick={handleConfirm} disabled={busy}>
              {busy ? '送出中…' : '確認'}
            </button>
          </div>

          {result && result.errors.length === 0 && (
            <div className="success-box">已確認 {result.updated.length} 筆交易。</div>
          )}
          {result && result.errors.length > 0 && (
            <div className="notice-box">
              {result.updated.length} 筆確認成功，{result.errors.length} 筆失敗：
              {result.errors.map((e) => `#${e.id} ${e.error}`).join('；')}
            </div>
          )}
        </>
      )}
    </div>
  )
}
