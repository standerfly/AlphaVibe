import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { HomeIcon, DashboardIcon, UsStocksIcon, AssetsIcon, PhotosIcon, FlightsIcon, GatewayIcon } from './icons.jsx'
import ThemeToggle from './ThemeToggle.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'

const TABS = [
  { to: '/', label: '首頁', icon: HomeIcon, end: true },
  { to: '/dashboard', label: '投資', icon: DashboardIcon, end: false },
  { to: '/us-stocks', label: '美股', icon: UsStocksIcon, end: false },
  { to: '/assets', label: '資產', icon: AssetsIcon, end: false },
  { to: '/photos', label: '相簿', icon: PhotosIcon, end: false },
  { to: '/flights', label: '機票', icon: FlightsIcon, end: false },
  { to: '/gateway', label: '管家', icon: GatewayIcon, end: false },
]

/* 共用 App Shell：頂部導覽列＋七個 tab（2026-08-31 新增「管家」、
   2026-09-23 新增「機票」，見 specs/005-flight-scan-page；
   2026-09-07 新增「美股」，見 specs/003-us-stocks），用 react-router-dom
   的 NavLink 判斷 active 狀態（isActive 由 NavLink 內建比對目前路徑，
   不用自己手刻）。/dashboard/:code、/us-stocks/:ticker 這類子路徑也要讓
   對應 tab 保持 active，所以只有首頁 tab 用 end（精確比對 "/"），其餘用
   前綴比對（NavLink 預設行為）。「美股」與既有台股「投資」分頁在資料/
   查詢管道完全獨立（FR-015/016），只是導覽列上相鄰擺放，方便使用。 */
export default function AppShell() {
  // key={pathname}：讓 error boundary 在切換分頁時重置，否則一次渲染失敗就會
  // 卡在錯誤畫面切不出去（見 ErrorBoundary.jsx 的說明）。
  const { pathname } = useLocation()
  return (
    <div className="app-shell">
      <header className="topnav">
        <div className="topnav__brand">STND</div>
        <nav className="topnav__tabs">
          {TABS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => 'tab-link' + (isActive ? ' active' : '')}
            >
              <Icon />
              {label}
            </NavLink>
          ))}
        </nav>
        <ThemeToggle />
      </header>
      <main className="app-main">
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  )
}
