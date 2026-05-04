import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import Dashboard from './pages/Dashboard'
import Cameras from './pages/Cameras'
import Patrols from './pages/Patrols'
import Incidents from './pages/Incidents'
import Robots from './pages/Robots'
import Sites from './pages/Sites'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Pilotage from './pages/Pilotage'
import ConnectScreen from './pages/ConnectScreen'
import { RobotConnectionProvider } from './context/RobotConnectionContext'
import { useSharedRobotConnection } from './context/RobotConnectionContext'
import UpdatePrompt from './components/UpdatePrompt'

function AppGate() {
  const conn = useSharedRobotConnection()
  if (conn.status !== 'connected') return <ConnectScreen />
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="pilotage" element={<Pilotage />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="patrols" element={<Patrols />} />
        <Route path="incidents" element={<Incidents />} />
        <Route path="robots" element={<Robots />} />
        <Route path="sites" element={<Sites />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <RobotConnectionProvider>
      <BrowserRouter>
        <AppGate />
      </BrowserRouter>
      <UpdatePrompt />
    </RobotConnectionProvider>
  )
}
