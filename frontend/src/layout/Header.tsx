import { useState } from 'react'
import { ChevronDown, Bell, Shield, Building2, User } from 'lucide-react'
import { mockSites } from '../data/sites'

export default function Header() {
  const [selectedSite, setSelectedSite] = useState(mockSites[0])
  const [siteMenuOpen, setSiteMenuOpen] = useState(false)

  return (
    <header
      className="flex items-center justify-between px-6 py-3 border-b border-slate-800 sticky top-0 z-10"
      style={{ background: '#0a0f1e' }}
    >
      {/* Site selector */}
      <div className="relative">
        <button
          onClick={() => setSiteMenuOpen(v => !v)}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-slate-500 transition-colors text-sm"
        >
          <Building2 size={15} className="text-blue-400" />
          <span className="font-medium">{selectedSite.name}</span>
          <ChevronDown size={14} className="text-slate-500" />
        </button>
        {siteMenuOpen && (
          <div className="absolute top-full mt-1 left-0 w-56 rounded-lg border border-slate-700 shadow-xl z-50 overflow-hidden" style={{ background: '#0f1629' }}>
            {mockSites.map(site => (
              <button
                key={site.id}
                onClick={() => { setSelectedSite(site); setSiteMenuOpen(false) }}
                className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left transition-colors hover:bg-slate-800 ${
                  site.id === selectedSite.id ? 'text-blue-400' : 'text-slate-300'
                }`}
              >
                <div className={`w-1.5 h-1.5 rounded-full ${
                  site.status === 'operational' ? 'bg-emerald-500' :
                  site.status === 'degraded' ? 'bg-amber-500' : 'bg-red-500'
                }`} />
                {site.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-emerald-400">
          <Shield size={14} />
          <span>Système opérationnel</span>
        </div>

        <button className="relative p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
          <Bell size={18} />
          <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-bold">3</span>
        </button>

        <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700 hover:border-slate-500 transition-colors">
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center">
            <User size={14} className="text-white" />
          </div>
          <span className="text-sm text-slate-300 font-medium">AD</span>
          <ChevronDown size={13} className="text-slate-500" />
        </button>
      </div>
    </header>
  )
}
