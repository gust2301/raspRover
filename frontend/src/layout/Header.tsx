import { useState } from 'react'
import { ChevronDown, Bell, Building2, User, Menu, WifiOff } from 'lucide-react'
import { mockSites } from '../data/sites'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'

export default function Header({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const [selectedSite, setSelectedSite] = useState(mockSites[0])
  const [siteMenuOpen, setSiteMenuOpen] = useState(false)
  const conn = useSharedRobotConnection()

  return (
    <header
      className="flex items-center justify-between gap-3 px-3 sm:px-4 lg:px-6 py-3 border-b border-slate-800 sticky top-0 z-20"
      style={{ background: '#0a0f1e' }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onOpenSidebar}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors lg:hidden"
        >
          <Menu size={18} />
        </button>

        <div className="relative min-w-0">
          <button
            onClick={() => setSiteMenuOpen(v => !v)}
            className="flex items-center gap-2 max-w-[55vw] sm:max-w-none px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500 transition-colors text-sm"
          >
            <Building2 size={15} className="text-blue-400 flex-shrink-0" />
            <span className="font-medium truncate">{selectedSite.name}</span>
            <ChevronDown size={14} className="text-slate-500 flex-shrink-0" />
          </button>
          {siteMenuOpen && (
            <div
              className="absolute top-full mt-1 left-0 w-56 rounded-lg border border-slate-700 shadow-xl z-50 overflow-hidden"
              style={{ background: '#0f1629' }}
            >
              {mockSites.map(site => (
                <button
                  key={site.id}
                  onClick={() => {
                    setSelectedSite(site)
                    setSiteMenuOpen(false)
                  }}
                  className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left transition-colors hover:bg-slate-800 ${
                    site.id === selectedSite.id ? 'text-blue-400' : 'text-slate-300'
                  }`}
                >
                  <div
                    className={`w-1.5 h-1.5 rounded-full ${
                      site.status === 'operational'
                        ? 'bg-emerald-500'
                        : site.status === 'degraded'
                          ? 'bg-amber-500'
                          : 'bg-red-500'
                    }`}
                  />
                  {site.name}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-4">
        {/* Robot connection status */}
        <div className="hidden lg:flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            conn.status === 'connected' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400 animate-pulse'
          }`} />
          <span className={`text-xs font-mono truncate max-w-[160px] ${
            conn.status === 'connected' ? 'text-emerald-400' : 'text-amber-400'
          }`}>
            {conn.robotIp}
          </span>
          {conn.latencyMs !== null && (
            <span className="text-xs text-slate-600 font-mono">{conn.latencyMs} ms</span>
          )}
          <button
            onClick={conn.disconnect}
            title="Déconnecter"
            className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <WifiOff size={13} />
          </button>
        </div>

        <button className="relative p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
          <Bell size={18} />
          <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-bold">
            3
          </span>
        </button>

        <button className="flex items-center gap-2 px-2 sm:px-3 py-1.5 rounded-lg border border-slate-700 hover:border-slate-500 transition-colors">
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center">
            <User size={14} className="text-white" />
          </div>
          <span className="hidden sm:inline text-sm text-slate-300 font-medium">AD</span>
          <ChevronDown size={13} className="hidden sm:block text-slate-500" />
        </button>
      </div>
    </header>
  )
}
