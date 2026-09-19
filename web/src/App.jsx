import { Routes, Route } from 'react-router-dom'
import AppShell from './components/AppShell.jsx'
import Home from './pages/Home.jsx'
import DashboardList from './pages/Dashboard.jsx'
import StockDetail from './pages/StockDetail.jsx'
import Assets from './pages/Assets.jsx'
import Photos from './pages/Photos.jsx'
import UsStocks from './pages/UsStocks.jsx'
import UsStockImport from './pages/UsStockImport.jsx'
import UsStockDetail from './pages/UsStockDetail.jsx'
import Gateway from './pages/Gateway.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<DashboardList />} />
        <Route path="/dashboard/:code" element={<StockDetail />} />
        <Route path="/us-stocks" element={<UsStocks />} />
        {/* /us-stocks/import 必須排在 /us-stocks/:ticker 之前——react-router
            依宣告順序比對，若 :ticker 先註冊會把 "import" 當成 ticker 值
            吃掉，這個順序是正確性要求，不是隨意排列（Phase 3 US1 T017/T018，
            見 specs/003-us-stocks/tasks.md）。 */}
        <Route path="/us-stocks/import" element={<UsStockImport />} />
        <Route path="/us-stocks/:ticker" element={<UsStockDetail />} />
        <Route path="/assets" element={<Assets />} />
        <Route path="/photos" element={<Photos />} />
        <Route path="/gateway" element={<Gateway />} />
        <Route path="*" element={<Home />} />
      </Route>
    </Routes>
  )
}
