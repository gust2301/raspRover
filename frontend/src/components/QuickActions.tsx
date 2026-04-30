import { useState } from 'react'
import { Play, Zap, Volume2, Mic, Home, MoreHorizontal } from 'lucide-react'

const actions = [
  { id: 'patrol', icon: Play, label: 'Démarrer patrouille', color: 'text-blue-400', bg: 'bg-blue-500/10 hover:bg-blue-500/20 border-blue-500/20', active: 'bg-blue-600 text-white border-blue-600' },
  { id: 'light', icon: Zap, label: 'Projecteur', color: 'text-amber-400', bg: 'bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/20', active: 'bg-amber-500 text-white border-amber-500' },
  { id: 'siren', icon: Volume2, label: 'Sirène', color: 'text-red-400', bg: 'bg-red-500/10 hover:bg-red-500/20 border-red-500/20', active: 'bg-red-600 text-white border-red-600' },
  { id: 'speak', icon: Mic, label: 'Parler', color: 'text-emerald-400', bg: 'bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/20', active: 'bg-emerald-600 text-white border-emerald-600' },
  { id: 'home', icon: Home, label: 'Retour base', color: 'text-slate-400', bg: 'bg-slate-800 hover:bg-slate-700 border-slate-700', active: 'bg-slate-600 text-white border-slate-600' },
  { id: 'more', icon: MoreHorizontal, label: 'Plus', color: 'text-slate-400', bg: 'bg-slate-800 hover:bg-slate-700 border-slate-700', active: 'bg-slate-600 text-white border-slate-600' },
]

export default function QuickActions() {
  const [activeActions, setActiveActions] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    setActiveActions(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="rounded-xl border border-slate-800 p-5 h-full" style={{ background: '#0f1629' }}>
      <h2 className="text-white font-semibold text-sm mb-4">Actions rapides</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {actions.map(({ id, icon: Icon, label, color, bg, active }) => {
          const isActive = activeActions.has(id)
          return (
            <button
              key={id}
              onClick={() => toggle(id)}
              className={`flex flex-col items-center justify-center gap-2 py-4 rounded-xl border transition-all duration-150 ${
                isActive ? active : `${color} ${bg} border`
              }`}
            >
              <Icon size={20} />
              <span className="text-xs font-medium leading-tight text-center">{label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
