import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiGet } from '../api/client.js'
import { SearchIcon } from '../components/icons.jsx'
import QuickInputPanel from '../components/QuickInputPanel.jsx'
import ScreenPanel from '../components/ScreenPanel.jsx'
import MarketScanPanel from '../components/MarketScanPanel.jsx'

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'holdings', label: '庫存中' },
  { key: 'research', label: '研究中' },
]

/* 投資分頁內部子頁籤（2026-08-24 新增，Q-046 待辦第3項）：PO 已明確決定
   不新增頂部導覽 tab，改在「投資」分頁內部用子頁籤切換「追蹤清單」（既有
   庫存/研究列表）／「選股篩選」（GET /api/screen）／「市場掃描」
   （GET /api/market-scan）。狀態存在網址的 `view` 參數（`list`／`screen`／
   `scan`，預設 `list`），比照 `filter`／`page`／`q` 既有慣例——重新整理／
   分享連結時子頁籤不會消失，也不新增任何路由路徑（不會跟
   `/dashboard/:code` 個股詳情頁的動態代碼路徑產生比對順序疑慮）。 */
const VIEW_TABS = [
  { key: 'list', label: '追蹤清單' },
  { key: 'screen', label: '選股篩選' },
  { key: 'scan', label: '市場掃描' },
]

/* 立場徽章色彩，比照 poc/kb-mcp/report.py 既有的 STANCE_COLORS／
   DEFAULT_STANCE_COLOR 邏輯（只有「偏多」「偏空」兩個精確字串有特殊色，
   其餘立場文字一律用中性色）——不在前端另外發明一套判斷規則。 */
function stanceBadgeClass(stance) {
  if (stance === '偏多') return 'badge-danger'
  if (stance === '偏空') return 'badge-positive'
  return 'badge-neutral'
}

/* 投資分頁：GET /api/holdings，接上搜尋關鍵字（q）、篩選 tab（filter）、
   分頁（page）三個 query string 參數——三者都用 useSearchParams 存進
   網址，重新整理／分享連結時篩選狀態不會消失。搜尋輸入框跟網址參數之間
   加 300ms debounce，避免每敲一個字就打一次 API。 */
export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const view = searchParams.get('view') || 'list'
  const filter = searchParams.get('filter') || 'all'
  const page = parseInt(searchParams.get('page') || '1', 10)
  const urlQuery = searchParams.get('q') || ''

  const [inputValue, setInputValue] = useState(urlQuery)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)
  // 快速輸入面板送出成功、且可能影響目前列表（加自選股／確認庫存匯入）
  // 時遞增，觸發下面的 useEffect 重新查詢——理由見 QuickInputPanel.jsx
  // 的 onDataChanged 註解。
  const [refreshKey, setRefreshKey] = useState(0)

  // 網址參數變動（切 tab／換頁／瀏覽器上一頁）或 refreshKey 變動時重新查詢。
  // 只在「追蹤清單」子頁籤時查詢——切到選股篩選／市場掃描時不需要
  // /api/holdings，`view` 進到依賴陣列也讓「切回追蹤清單」時自動重新
  // 查一次，避免在別的子頁籤加自選股後回來看到過期資料。
  useEffect(() => {
    if (view !== 'list') return
    let cancelled = false
    setError(null)
    const params = new URLSearchParams({ filter, page: String(page), q: urlQuery })
    apiGet(`/api/holdings?${params.toString()}`)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [view, filter, page, urlQuery, refreshKey])

  // 輸入框變動 debounce 300ms 後才寫回網址參數（同時重置頁碼到第 1 頁，
  // 跟後端「換搜尋字串／篩選 tab 就該重新從第一頁看」的既有慣例一致）。
  function handleInputChange(e) {
    const value = e.target.value
    setInputValue(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchParams({ filter, page: '1', q: value })
    }, 300)
  }

  function handleFilterClick(key) {
    setSearchParams({ filter: key, page: '1', q: urlQuery })
  }

  function goToPage(p) {
    setSearchParams({ filter, page: String(p), q: urlQuery })
  }

  // 切子頁籤：已經在那個子頁籤就不做事（避免重複點擊「追蹤清單」把
  // filter／page／q 重設掉）；真的切換時只寫 `view`，不帶其餘參數——
  // 切回「追蹤清單」時 filter／page／q 自然回到預設值（全部／第1頁／無
  // 搜尋字），跟「換一個子頁籤等於重新開始看」的既有慣例（切 filter tab
  // 也會重置到第1頁）一致。
  function handleViewClick(key) {
    if (key === view) return
    setSearchParams({ view: key })
  }

  return (
    <div>
      <div className="page-title">
        <h1>投資</h1>
      </div>

      <div className="filter-tabs">
        {VIEW_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={'filter-tab' + (view === t.key ? ' active' : '')}
            onClick={() => handleViewClick(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {view === 'screen' && <ScreenPanel />}
      {view === 'scan' && <MarketScanPanel />}

      {view === 'list' && (
        <>
          <QuickInputPanel onDataChanged={() => setRefreshKey((k) => k + 1)} />

          <div className="stocklist-search">
            <SearchIcon width={16} height={16} />
            <input
              type="text"
              placeholder="搜尋代碼／名稱／心得內容"
              value={inputValue}
              onChange={handleInputChange}
            />
          </div>

          <div className="filter-tabs">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={'filter-tab' + (filter === f.key ? ' active' : '')}
                onClick={() => handleFilterClick(f.key)}
              >
                {f.label}
                {data && f.key === 'all' && ` ${data.all_total}`}
                {data && f.key === 'holdings' && ` ${data.holdings_count}`}
                {data && f.key === 'research' && ` ${data.research_count}`}
              </button>
            ))}
          </div>

          {error && <div className="error-box">載入失敗：{error}</div>}
          {!data && !error && <div className="loading-box">載入中…</div>}

          {data && data.results.length === 0 && (
            <p className="empty">沒有符合條件的標的。</p>
          )}

          {data && data.results.length > 0 && (
            <div className="stock-list">
              {data.results.map((r) => (
                <div
                  key={r.code}
                  className={'stock-row' + (r.has_concern ? ' has-concern' : '')}
                  onClick={() => navigate(`/dashboard/${r.code}`)}
                >
                  {r.has_concern ? <div className="concern-dot" /> : <div className="concern-slot" />}
                  <div className="stock-row__id">
                    <div className="stock-row__name-line">
                      <span className="stock-row__name">{r.name || r.code}</span>
                      <span className="stock-row__code">{r.code}</span>
                      {r.is_holding && <span className="badge badge-neutral">庫存中</span>}
                    </div>
                    <div className="stock-row__sub">{r.status_text}</div>
                    <div className="stock-row__stance-line">
                      {r.stance
                        ? <span className={'badge ' + stanceBadgeClass(r.stance)}>{r.stance}</span>
                        : <span className="badge badge-neutral">尚無立場</span>}
                      {r.reason && (
                        <span className="stock-row__reason" title={r.reason}>{r.reason}</span>
                      )}
                    </div>
                  </div>
                  <div className="stock-row__price">
                    <div className="stock-row__now">{r.price != null ? r.price : '—'}</div>
                    {r.delta_pct != null && (
                      <div className={'stock-row__delta ' + (r.delta_pct >= 0 ? 'is-up' : 'is-down')}>
                        {r.delta_pct >= 0 ? '+' : ''}{r.delta_pct.toFixed(2)}%
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {data && data.total_pages > 1 && (
            <div className="pager">
              <span>第 {data.page} / {data.total_pages} 頁（共 {data.total} 檔）</span>
              <div className="pager__nav">
                <button type="button" disabled={data.page <= 1} onClick={() => goToPage(data.page - 1)}>
                  上一頁
                </button>
                <button type="button" disabled={data.page >= data.total_pages} onClick={() => goToPage(data.page + 1)}>
                  下一頁
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
