import { NavLink, Outlet } from 'react-router-dom'
import { HomeIcon, DashboardIcon, AssetsIcon, PhotosIcon } from './icons.jsx'
import ThemeToggle from './ThemeToggle.jsx'

const TABS = [
  { to: '/', label: '首頁', icon: HomeIcon, end: true },
  { to: '/dashboard', label: '儀表板', icon: DashboardIcon, end: false },
  { to: '/assets', label: '資產', icon: AssetsIcon, end: false },
  { to: '/photos', label: '相簿', icon: PhotosIcon, end: false },
]

/* 共用 App Shell：頂部導覽列＋四個 tab，用 react-router-dom 的
   NavLink 判斷 active 狀態（isActive 由 NavLink 內建比對目前路徑，
   不用自己手刻）。/dashboard/:code 這類子路徑也要讓「儀表板」tab
   保持 active，所以只有首頁 tab 用 end（精確比對 "/"），其餘用
   前綴比對（NavLink 預設行為）。 */
export default function AppShell() {
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
        <Outlet />
      </main>
    </div>
  )
}
