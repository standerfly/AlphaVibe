import { Routes, Route } from 'react-router-dom'
import AppShell from './components/AppShell.jsx'
import Home from './pages/Home.jsx'
import DashboardList from './pages/Dashboard.jsx'
import StockDetail from './pages/StockDetail.jsx'
import Assets from './pages/Assets.jsx'
import Photos from './pages/Photos.jsx'
import Gateway from './pages/Gateway.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<DashboardList />} />
        <Route path="/dashboard/:code" element={<StockDetail />} />
        <Route path="/assets" element={<Assets />} />
        <Route path="/photos" element={<Photos />} />
        <Route path="/gateway" element={<Gateway />} />
        <Route path="*" element={<Home />} />
      </Route>
    </Routes>
  )
}
