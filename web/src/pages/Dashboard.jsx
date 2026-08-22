import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiGet } from '../api/client.js'
import { SearchIcon } from '../components/icons.jsx'

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'holdings', label: '庫存中' },
  { key: 'research', label: '研究中' },
]

/* 儀表板：GET /api/holdings，接上搜尋關鍵字（q）、篩選 tab（filter）、
   分頁（page）三個 query string 參數——三者都用 useSearchParams 存進
   網址，重新整理／分享連結時篩選狀態不會消失。搜尋輸入框跟網址參數之間
   加 300ms debounce，避免每敲一個字就打一次 API。 */
export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const filter = searchParams.get('filter') || 'all'
  const page = parseInt(searchParams.get('page') || '1', 10)
  const urlQuery = searchParams.get('q') || ''

  const [inputValue, setInputValue] = useState(urlQuery)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  // 網址參數變動（切 tab／換頁／瀏覽器上一頁）時重新查詢。
  useEffect(() => {
    let cancelled = false
    setError(null)
    const params = new URLSearchParams({ filter, page: String(page), q: urlQuery })
    apiGet(`/api/holdings?${params.toString()}`)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [filter, page, urlQuery])

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

  return (
    <div>
      <div className="page-title">
        <h1>儀表板</h1>
      </div>

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
    </div>
  )
}
