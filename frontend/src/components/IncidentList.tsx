import { AlertTriangle, User, Car, Battery, CheckCircle, ChevronRight } from 'lucide-react'
import type { Incident } from '../types'
import { mockIncidents } from '../data/incidents'

const ICON_MAP: Record<string, typeof AlertTriangle> = {
  'Mouvement détecté': AlertTriangle,
  'Présence humaine': User,
  'Véhicule détecté': Car,
  'Batterie faible': Battery,
  'Patrouille terminée': CheckCircle,
}

const LEVEL_STYLES = {
  critical: { dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', bg: 'bg-red-500/10' },
  warning: { dot: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-500/10' },
  info: { dot: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-500/10' },
  success: { dot: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10' },
}

function IncidentRow({ incident }: { incident: Incident }) {
  const Icon = ICON_MAP[incident.type] ?? AlertTriangle
  const styles = LEVEL_STYLES[incident.level]

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-transparent hover:border-slate-200 hover:bg-slate-50 dark:hover:border-slate-700 dark:hover:bg-slate-800/40 transition-all cursor-pointer">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${styles.bg}`}>
        <Icon size={14} className={styles.text} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-slate-900 dark:text-white text-xs font-medium truncate">{incident.type}</span>
          <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${styles.dot}`} />
        </div>
        <div className="text-slate-500 dark:text-slate-500 text-xs truncate">{incident.zone} — {incident.description}</div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-slate-400 dark:text-slate-500 text-xs font-mono">{incident.time}</span>
        <ChevronRight size={12} className="text-slate-400 dark:text-slate-600" />
      </div>
    </div>
  )
}

export default function IncidentList() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#0f1629] p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-slate-900 dark:text-white font-semibold text-sm">Incidents récents</h2>
        <button className="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 text-xs transition-colors">Voir tout</button>
      </div>
      <div className="space-y-1">
        {mockIncidents.map(incident => (
          <IncidentRow key={incident.id} incident={incident} />
        ))}
      </div>
    </div>
  )
}
