import { Wifi, WifiOff, Gauge, Radar, Bot } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'

// ---------------------------------------------------------------------------
// Conversion tension → pourcentage (batterie LiPo 3S : 10.0V–12.6V)
// ---------------------------------------------------------------------------

const BATTERY_MIN_V = 10.0
const BATTERY_MAX_V = 12.6

function voltageToPercent(v: number): number {
  return Math.round(Math.max(0, Math.min(100, ((v - BATTERY_MIN_V) / (BATTERY_MAX_V - BATTERY_MIN_V)) * 100)))
}

// ---------------------------------------------------------------------------
// Jauge batterie semi-circulaire
// ---------------------------------------------------------------------------

function BatteryGauge({ pct, voltage }: { pct: number | null; voltage: number | undefined }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const safePct = pct ?? 0
  const color = pct == null ? '#475569' : safePct > 50 ? '#10b981' : safePct > 20 ? '#f59e0b' : '#ef4444'

  return (
    <div className="relative w-32 h-32 mx-auto">
      <svg viewBox="0 0 120 120" className="w-full h-full -rotate-[135deg]">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#1e293b" strokeWidth="10"
          strokeDasharray={`${circumference * 0.75} ${circumference * 0.25}`}
          strokeLinecap="round" />
        <circle cx="60" cy="60" r={radius} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={`${circumference * 0.75 * safePct / 100} ${circumference}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.5s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-white">{pct != null ? `${pct}%` : '—'}</span>
        {voltage !== undefined && (
          <span className="text-xs text-slate-500 font-mono mt-0.5">{voltage.toFixed(1)} V</span>
        )}
        <span className="text-xs text-slate-400 mt-0.5">Batterie</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Carte principale
// ---------------------------------------------------------------------------

export default function RobotStatusCard() {
  const conn = useSharedRobotConnection()
  const s    = conn.lastStatus
  const isOnline = conn.status === 'connected'

  // Batterie — battery = % calculé par le serveur (ou le hook), voltage = tension brute
  const batteryPct = (s?.battery as number | undefined) ?? (s?.voltage != null ? voltageToPercent(s.voltage as number) : null)
  const batteryV   = s?.voltage as number | undefined

  // Patrol
  const patrolActive = s?.patrol_active ?? false
  const patrolState  = s?.patrol_state ?? 'idle'

  // Distance
  const frontCm = s?.front_cm
  const obstacle = s?.obstacle ?? false

  const stats = [
    {
      icon: isOnline ? Wifi : WifiOff,
      label: 'Connectivité',
      value: isOnline ? `En ligne · ${conn.latencyMs ?? '—'} ms` : 'Hors ligne',
      color: isOnline ? 'text-emerald-400' : 'text-slate-500',
    },
    {
      icon: Bot,
      label: 'Mode',
      value: patrolActive
        ? (patrolState === 'avoiding' ? 'Évitement' : 'Patrouille')
        : 'Manuel',
      color: patrolActive ? 'text-blue-400' : 'text-slate-300',
    },
    {
      icon: Gauge,
      label: 'Moteurs L / R',
      value: s?.speed_l != null
        ? `${s.speed_l.toFixed(2)} / ${(s.speed_r as number | undefined)?.toFixed(2) ?? '—'}`
        : '— / —',
      color: 'text-blue-400',
    },
    {
      icon: Radar,
      label: 'Distance avant',
      value: frontCm != null ? `${(frontCm as number).toFixed(0)} cm` : '—',
      color: obstacle ? 'text-red-400' : frontCm != null && (frontCm as number) < 50 ? 'text-amber-400' : 'text-emerald-400',
    },
  ]

  return (
    <div className="rounded-xl border border-slate-800 p-5 h-full" style={{ background: '#0f1629' }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-white font-semibold text-sm">État du robot</h2>
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
          <span className={`text-xs ${isOnline ? 'text-emerald-400' : 'text-slate-500'}`}>
            {isOnline ? 'En ligne' : 'Hors ligne'}
          </span>
        </div>
      </div>

      <BatteryGauge pct={batteryPct ?? null} voltage={batteryV} />

      {!isOnline && (
        <p className="text-center text-xs text-slate-600 mt-2 mb-2">Connectez-vous pour voir les données réelles</p>
      )}

      <div className="mt-4 space-y-3">
        {stats.map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="flex items-center justify-between py-2 border-b border-slate-800/50 last:border-0">
            <div className="flex items-center gap-2 text-slate-400">
              <Icon size={14} />
              <span className="text-xs">{label}</span>
            </div>
            <span className={`text-xs font-medium ${color}`}>{value}</span>
          </div>
        ))}
      </div>

      {obstacle && (
        <div className="mt-3 px-3 py-2 rounded-lg bg-red-950/50 border border-red-700/40 text-center">
          <span className="text-xs font-bold text-red-400 animate-pulse">⚠ OBSTACLE DÉTECTÉ</span>
        </div>
      )}
    </div>
  )
}
