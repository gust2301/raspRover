import { useEffect, useState } from 'react'
import {
  AlertTriangle, ShieldAlert, Info, RefreshCw, Loader2,
  AlertCircle, Video, Calendar, X,
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
  info:     { badge: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30',   icon: <Info size={13} />,         dot: 'bg-blue-400'  },
  warning:  { badge: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30', icon: <AlertTriangle size={13} />, dot: 'bg-amber-400' },
  critical: { badge: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30',       icon: <ShieldAlert size={13} />,   dot: 'bg-red-500'   },
}

const TYPE_LABEL: Record<string, string> = {
  obstacle:               'Obstacle détecté',
  patrol_start:           'Patrouille démarrée',
  patrol_stop:            'Patrouille arrêtée',
  patrol_stuck:           'Robot bloqué',
  alert:                  'Alerte déclenchée',
  emergency:              'Arrêt urgence',
  person_detected:        'Personne détectée',
  person_lost:            'Personne perdue de vue',
  human_detected_patrol:  'Personne détectée (patrouille)',
}

const DAYS_OPTIONS = [
  { value: 1,  label: 'Auj.' },
  { value: 3,  label: '3 j'  },
  { value: 7,  label: '7 j'  },
  { value: 30, label: '30 j' },
] as const

const SEVERITY_FILTER = ['tous', 'critical', 'warning', 'info'] as const
type SeverityFilter = typeof SEVERITY_FILTER[number]

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatTs(ts: string): string {
  // "2026-05-07T14:32:10" → "2026-05-07 14:32:10"
  return ts.replace('T', ' ')
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function IncidentRow({ inc }: { inc: Incident }) {
  const s = SEVERITY_STYLE[inc.severity] ?? SEVERITY_STYLE.warning

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:bg-slate-800/20 transition-colors">
      <div className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${s.dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-0.5">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
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
                bg-emerald-50 text-emerald-700 border border-emerald-200
                hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30
                dark:hover:bg-emerald-500/20 transition-colors"
            >
              <Video size={10} />
              Média
            </a>
          )}
        </div>
        {inc.details && (
          <p className="text-xs text-slate-400 dark:text-slate-500 truncate">{inc.details}</p>
        )}
      </div>
      <span className="text-xs text-slate-400 dark:text-slate-600 font-mono flex-shrink-0 mt-0.5 whitespace-nowrap">
        {formatTs(inc.ts)}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Incidents() {
  const conn = useSharedRobotConnection()
  const [incidents, setIncidents]     = useState<Incident[]>([])
  const [isLoading, setIsLoading]     = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [severityFilter, setSeverity] = useState<SeverityFilter>('tous')
  const [days, setDays]               = useState<number>(7)
  const [dateFilter, setDateFilter]   = useState<string>('')   // YYYY-MM-DD ou ''

  // ── Fetch ──────────────────────────────────────────────────────────────────

  const fetchIncidents = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const base   = getRobotApiUrl(conn.robotIp)
      const params = dateFilter ? `date=${dateFilter}` : `days=${days}`
      const res    = await fetch(`${base}/api/incidents?${params}`)
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
  }, [conn.robotIp, days, dateFilter])

  // ── Handlers ──────────────────────────────────────────────────────────────

  function selectDays(d: number) {
    setDateFilter('')   // désactive le filtre date
    setDays(d)
  }

  function selectDate(d: string) {
    setDateFilter(d)    // désactive les boutons période
  }

  function clearDate() {
    setDateFilter('')
  }

  // ── Derived ───────────────────────────────────────────────────────────────

  const filtered = severityFilter === 'tous'
    ? incidents
    : incidents.filter(i => i.severity === severityFilter)

  const counts = {
    critical: incidents.filter(i => i.severity === 'critical').length,
    warning:  incidents.filter(i => i.severity === 'warning').length,
    info:     incidents.filter(i => i.severity === 'info').length,
  }

  const periodLabel = dateFilter
    ? new Date(dateFilter + 'T00:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
    : DAYS_OPTIONS.find(o => o.value === days)?.label ?? `${days} j`

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-4xl mx-auto w-full space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#0f1629] overflow-hidden">

        {/* ── Barre de titre ─────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} className="text-amber-600 dark:text-amber-400" />
            <h1 className="text-slate-900 dark:text-white font-semibold text-sm">Journal des incidents</h1>
            {!isLoading && incidents.length > 0 && (
              <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
                {incidents.length} entrée{incidents.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <button
            onClick={fetchIncidents}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 disabled:opacity-40 transition-colors px-2 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
            Actualiser
          </button>
        </div>

        {/* ── Filtres date ───────────────────────────────────────────────── */}
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 space-y-2.5">
          {/* Ligne 1 : boutons période rapide */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 dark:text-slate-500 w-14 flex-shrink-0">Période</span>
            <div className="flex gap-1">
              {DAYS_OPTIONS.map(o => (
                <button
                  key={o.value}
                  onClick={() => selectDays(o.value)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                    !dateFilter && days === o.value
                      ? 'bg-slate-600 text-white'
                      : 'bg-slate-100 text-slate-500 hover:text-slate-900 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            {/* Séparateur */}
            <span className="text-slate-300 dark:text-slate-700 text-xs">ou</span>
            {/* Date picker */}
            <div className="flex items-center gap-1.5">
              <Calendar size={13} className="text-slate-400 dark:text-slate-500 flex-shrink-0" />
              <input
                type="date"
                value={dateFilter}
                max={todayStr()}
                onChange={e => selectDate(e.target.value)}
                className={`bg-white dark:bg-slate-800 border text-xs px-2 py-1 rounded-lg focus:outline-none focus:border-slate-500 transition-colors ${
                  dateFilter
                    ? 'border-slate-400 text-slate-700 dark:border-slate-500 dark:text-slate-200'
                    : 'border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400'
                }`}
              />
              {dateFilter && (
                <button
                  onClick={clearDate}
                  className="text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300 transition-colors"
                  title="Effacer la date"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          </div>

          {/* Résumé période active */}
          {dateFilter && (
            <p className="text-xs text-slate-400 dark:text-slate-500">
              Affichage du <span className="text-slate-600 dark:text-slate-300 font-medium">{periodLabel}</span>
            </p>
          )}
        </div>

        {/* ── Stats ─────────────────────────────────────────────────────── */}
        <div className="flex border-b border-slate-200 dark:border-slate-800">
          {[
            { key: 'critical', label: 'Critiques', count: counts.critical, color: 'text-red-600 dark:text-red-400'   },
            { key: 'warning',  label: 'Alertes',   count: counts.warning,  color: 'text-amber-600 dark:text-amber-400' },
            { key: 'info',     label: 'Infos',     count: counts.info,     color: 'text-blue-600 dark:text-blue-400'  },
          ].map(s => (
            <div key={s.key} className="flex-1 px-4 py-3 text-center border-r border-slate-200 dark:border-slate-800 last:border-r-0">
              <p className={`text-xl font-bold font-mono ${s.color}`}>{s.count}</p>
              <p className="text-xs text-slate-400 dark:text-slate-600 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* ── Filtre sévérité ───────────────────────────────────────────── */}
        <div className="flex gap-1 px-4 py-2 border-b border-slate-200 dark:border-slate-800">
          {SEVERITY_FILTER.map(f => (
            <button
              key={f}
              onClick={() => setSeverity(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors capitalize ${
                severityFilter === f
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300'
              }`}
            >
              {f === 'tous' ? `Tous (${incidents.length})` : f}
            </button>
          ))}
        </div>

        {/* ── Contenu ───────────────────────────────────────────────────── */}
        <div>
          {error && (
            <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border-b border-red-200 dark:text-red-300 dark:bg-red-500/10 dark:border-red-500/20 px-4 py-3">
              <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {isLoading && incidents.length === 0 && (
            <div className="flex justify-center py-12">
              <Loader2 size={24} className="text-slate-400 dark:text-slate-600 animate-spin" />
            </div>
          )}

          {!isLoading && filtered.length === 0 && !error && (
            <div className="text-center py-12 space-y-2">
              <AlertTriangle size={32} className="mx-auto text-slate-300 dark:text-slate-700" />
              <p className="text-slate-400 dark:text-slate-600 text-sm">
                {severityFilter === 'tous'
                  ? `Aucun incident pour ${dateFilter ? `le ${periodLabel}` : 'cette période'}.`
                  : `Aucun incident « ${severityFilter} » sur cette période.`}
              </p>
              {!dateFilter && (
                <p className="text-xs text-slate-300 dark:text-slate-700">
                  Les incidents sont enregistrés automatiquement pendant la patrouille.
                </p>
              )}
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
