import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Camera, Route, AlertTriangle, Car,
  Bot, MapPin, FileText, Settings, Battery, Wifi, AlertOctagon, Gamepad2, X, Map, Network,
} from 'lucide-react'
import { mockRobot } from '../data/robots'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: "Vue d'ensemble", highlight: false },
  { to: '/pilotage', icon: Gamepad2, label: 'Pilotage', highlight: true },
  { to: '/cameras', icon: Camera, label: 'Caméras', highlight: false },
  { to: '/vehicle-inspections', icon: Car, label: 'Inspections véhicules', highlight: true },
  { to: '/patrols', icon: Route, label: 'Patrouilles', highlight: false },
  { to: '/map', icon: Map, label: 'Carte SLAM', highlight: false },
  { to: '/incidents', icon: AlertTriangle, label: 'Incidents', highlight: false },
  { to: '/robots', icon: Bot, label: 'Robots', highlight: false },
  { to: '/sites', icon: MapPin, label: 'Sites', highlight: false },
  { to: '/reports', icon: FileText, label: 'Rapports', highlight: false },
  { to: '/network', icon: Network, label: 'Wi-Fi', highlight: false },
  { to: '/settings', icon: Settings, label: 'Paramètres', highlight: false },
]

export default function Sidebar({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [emergencyActive, setEmergencyActive] = useState(false)
  const robot = mockRobot
  const conn = useSharedRobotConnection()
  const isOnline = conn.status === 'connected'
  const battery = conn.lastStatus?.battery ?? null

  return (
    <>
      <div
        className={`fixed inset-0 bg-black/50 backdrop-blur-sm z-30 transition-opacity md:hidden ${
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] flex flex-col transform transition-transform duration-200 lg:static lg:z-auto lg:w-64 lg:max-w-none lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ background: '#0a0f1e', borderRight: '1px solid #1e293b' }}
      >
        <div className="flex items-center gap-3 px-5 py-4 md:px-6 md:py-5 border-b border-slate-800">
          <div className="w-9 h-9 rounded-lg overflow-hidden bg-slate-900/80 ring-1 ring-slate-700/80 flex items-center justify-center flex-shrink-0">
            <img
              src="/assets/icons/android-chrome-192x192.png"
              alt="SENTRYX"
              className="w-full h-full object-cover"
            />
          </div>
          <div className="min-w-0">
            <span className="text-white font-bold text-lg tracking-widest">SENTRYX</span>
            <div className="text-slate-500 text-xs">Security Platform</div>
          </div>
          <button
            onClick={onClose}
            className="ml-auto p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 md:hidden"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label, highlight }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-600/30'
                    : highlight
                      ? 'text-blue-300 hover:text-white hover:bg-blue-600/20 border border-blue-600/20'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-slate-800 space-y-3">
          <div
            className="rounded-lg p-3"
            style={{ background: '#0f1629', border: '1px solid #1e293b' }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-400 font-medium">Robot actif</span>
              <div className="flex items-center gap-1">
                <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
                <span className={`text-xs ${isOnline ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {isOnline ? 'En ligne' : 'Hors ligne'}
                </span>
              </div>
            </div>
            <div className="text-white text-sm font-semibold mb-1">{robot.name}</div>
            <div className="text-slate-500 text-xs mb-2">ID : {robot.id}</div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Battery size={13} className={battery != null && battery < 20 ? 'text-red-400' : battery != null && battery < 40 ? 'text-amber-400' : 'text-emerald-400'} />
              <div className="flex-1 bg-slate-700 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full transition-all ${battery != null && battery < 20 ? 'bg-red-500' : battery != null && battery < 40 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                  style={{ width: `${battery ?? 0}%` }}
                />
              </div>
              <span className={`font-medium ${battery != null && battery < 20 ? 'text-red-400' : battery != null && battery < 40 ? 'text-amber-400' : 'text-emerald-400'}`}>
                {battery != null ? `${battery}%` : '—'}
              </span>
            </div>
            <div className="flex items-center gap-1.5 mt-1.5 text-xs text-slate-400">
              <Wifi size={12} className="text-blue-400" />
              <span>
                Connectivité : <span className="text-blue-400">Excellente</span>
              </span>
            </div>
          </div>

          <button
            onClick={() => setEmergencyActive(v => !v)}
            className={`w-full py-2.5 rounded-lg font-bold text-sm flex items-center justify-center gap-2 transition-all duration-150 ${
              emergencyActive
                ? 'bg-red-700 text-white shadow-lg shadow-red-900/50'
                : 'bg-red-600/20 text-red-400 border border-red-600/40 hover:bg-red-600 hover:text-white hover:shadow-lg hover:shadow-red-900/40'
            }`}
          >
            <AlertOctagon size={16} />
            {emergencyActive ? "ARRÊT ACTIF" : "Arrêt d'urgence"}
          </button>
        </div>
      </aside>
    </>
  )
}
