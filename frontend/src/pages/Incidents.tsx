import { useEffect, useState } from 'react'
import {
  AlertTriangle, ShieldAlert, Info, RefreshCw, Loader2,
  AlertCircle, Video, ChevronDown,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl } from '../lib/robotTransport'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Incident {
  id: number
  ts: string
  type: string
  severity: 'info' | 'warning' | 'critical'
  details: string | null
  media_key: string | null
  media_url: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEVERITY_STYLE: Record<string, { badge: string; icon: React.ReactNode; dot: string }> = {
  info:     { badge: 'bg-blue-500/10 text-blue-300 border-blue-500/30',   icon: <Info size={13} />,         dot: 'bg-blue-400'   },
  warning:  { badge: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: <AlertTriangle size={13} />, dot: 'bg-amber-400'  },
  critical: { badge: 'bg-red-500/10 text-red-300 border-red-500/30',       icon: <ShieldAlert size={13} />,   dot: 'bg-red-500'    },
}

const TYPE_LABEL: Record<string, string> = {
  obstacle:        'Obstacle détecté',
  patrol_start:    'Patrouille démarrée',
  patrol_stop:     'Patrouille arrêtée',
  patrol_stuck:    'Robot bloqué',
  alert:           'Alerte déclenchée',
  emergency:       'Arrêt urgence',
  person_detected: 'Personne détectée',
  person_lost:     'Personne perdue de vue',
}

function formatTs(ts: string): string {
  return ts.replace('T', ' ').replace(/-(\d{2})-(\d{2})$/, ':$1:$2')
}

function IncidentRow({ inc }: { inc: Incident }) {
  const s = SEVERITY_STYLE[inc.severity] ?? SEVERITY_STYLE.warning

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-slate-800/60 hover:bg-slate-800/20 transition-colors">
      <div className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${s.dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-0.5">
          <span className="text-sm font-medium text-slate-200">
            {TYPE_LABEL[inc.type] ?? inc.type}
          </span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${s.badge}`}>
            {s.icon}
            {inc.severity}
          </span>
          {inc.media_key && (
            <a
              href={inc.media_url ?? '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs
                bg-emerald-500/10 text-emerald-300 border border-emerald-500/30
                hover:bg-emerald-500/20 transition-colors"
            >
              <Video size={10} />
              Vidéo
            </a>
          )}
        </div>
        {inc.details && (
          <p className="text-xs text-slate-500 truncate">{inc.details}</p>
        )}
      </div>
      <span className="text-xs text-slate-600 font-mono flex-shrink-0 mt-0.5">{formatTs(inc.ts)}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const FILTER_OPTIONS = ['tous', 'critical', 'warning', 'info'] as const
type Filter = typeof FILTER_OPTIONS[number]

export default function Incidents() {
  const conn = useSharedRobotConnection()
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('tous')
  const [days, setDays] = useState(7)

  const fetchIncidents = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const base = getRobotApiUrl(conn.robotIp)
      const res = await fetch(`${base}/api/incidents?days=${days}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setIncidents(await res.json() as Incident[])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur réseau')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchIncidents()
    const id = setInterval(fetchIncidents, 30_000)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.robotIp, days])

  const filtered = filter === 'tous' ? incidents : incidents.filter(i => i.severity === filter)

  const counts = {
    critical: incidents.filter(i => i.severity === 'critical').length,
    warning:  incidents.filter(i => i.severity === 'warning').length,
    info:     incidents.filter(i => i.severity === 'info').length,
  }

  return (
    <div className="max-w-4xl mx-auto w-full space-y-4">

      {/* Header card */}
      <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} className="text-amber-400" />
            <h1 className="text-white font-semibold text-sm">Journal des incidents</h1>
            {!isLoading && incidents.length > 0 && (
              <span className="text-xs text-slate-500 font-mono">{incidents.length} entrée{incidents.length > 1 ? 's' : ''}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Days selector */}
            <div className="relative">
              <select
                value={days}
                onChange={e => setDays(Number(e.target.value))}
                className="appearance-none bg-slate-800 border border-slate-700 text-slate-300 text-xs px-3 py-1.5 pr-7 rounded-lg focus:outline-none"
              >
                <option value={1}>Aujourd'hui</option>
                <option value={3}>3 jours</option>
                <option value={7}>7 jours</option>
              </select>
              <ChevronDown size={11} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
            </div>
            <button
              onClick={fetchIncidents}
              disabled={isLoading}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors px-2 py-1.5 rounded-lg hover:bg-slate-800"
            >
              <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
              Actualiser
            </button>
          </div>
        </div>

        {/* Stats bar */}
        <div className="flex border-b border-slate-800">
          {[
            { key: 'critical', label: 'Critiques', count: counts.critical, color: 'text-red-400' },
            { key: 'warning',  label: 'Alertes',   count: counts.warning,  color: 'text-amber-400' },
            { key: 'info',     label: 'Infos',      count: counts.info,     color: 'text-blue-400' },
          ].map(s => (
            <div key={s.key} className="flex-1 px-4 py-3 text-center border-r border-slate-800 last:border-r-0">
              <p className={`text-xl font-bold font-mono ${s.color}`}>{s.count}</p>
              <p className="text-xs text-slate-600 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 px-4 py-2 border-b border-slate-800">
          {FILTER_OPTIONS.map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors capitalize ${
                filter === f
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {f === 'tous' ? `Tous (${incidents.length})` : f}
            </button>
          ))}
        </div>

        {/* Content */}
        <div>
          {error && (
            <div className="flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border-b border-red-500/20 px-4 py-3">
              <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {isLoading && incidents.length === 0 && (
            <div className="flex justify-center py-12">
              <Loader2 size={24} className="text-slate-600 animate-spin" />
            </div>
          )}

          {!isLoading && filtered.length === 0 && !error && (
            <div className="text-center py-12 space-y-2">
              <AlertTriangle size={32} className="mx-auto text-slate-700" />
              <p className="text-slate-600 text-sm">
                {filter === 'tous'
                  ? 'Aucun incident enregistré sur cette période.'
                  : `Aucun incident de type « ${filter} ».`}
              </p>
              <p className="text-xs text-slate-700">Les incidents sont enregistrés automatiquement pendant la patrouille.</p>
            </div>
          )}

          {filtered.map(inc => (
            <IncidentRow key={inc.id} inc={inc} />
          ))}
        </div>
      </div>
    </div>
  )
}
