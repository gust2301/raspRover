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
import MapView from './pages/MapView'
import Network from './pages/Network'
import ConnectScreen from './pages/ConnectScreen'
import VehicleInspections from './pages/VehicleInspections'
import { RobotConnectionProvider } from './context/RobotConnectionContext'
import UpdatePrompt from './components/UpdatePrompt'

export default function App() {
  return (
    <RobotConnectionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/connect" element={<ConnectScreen />} />
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
            <Route path="network" element={<Network />} />
            <Route path="map" element={<MapView />} />
            <Route path="vehicle-inspections" element={<VehicleInspections />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <UpdatePrompt />
    </RobotConnectionProvider>
  )
}
