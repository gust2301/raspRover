import { Wifi, Gauge, Thermometer, Target } from 'lucide-react'
import { mockRobot } from '../data/robots'

function BatteryGauge({ value }: { value: number }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const color = value > 50 ? '#10b981' : value > 20 ? '#f59e0b' : '#ef4444'

  return (
    <div className="relative w-32 h-32 mx-auto">
      <svg viewBox="0 0 120 120" className="w-full h-full -rotate-[135deg]">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#1e293b" strokeWidth="10"
          strokeDasharray={`${circumference * 0.75} ${circumference * 0.25}`}
          strokeLinecap="round" />
        <circle cx="60" cy="60" r={radius} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={`${circumference * 0.75 * value / 100} ${circumference}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.5s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-white">{value}%</span>
        <span className="text-xs text-slate-400 mt-1">Batterie</span>
      </div>
    </div>
  )
}

export default function RobotStatusCard() {
  const robot = mockRobot

  const stats = [
    { icon: Wifi, label: 'Connectivité', value: 'Excellente', color: 'text-emerald-400' },
    { icon: Gauge, label: 'Vitesse', value: `${robot.speed} m/s`, color: 'text-blue-400' },
    { icon: Thermometer, label: 'Température', value: `${robot.temperature} °C`, color: robot.temperature > 60 ? 'text-red-400' : 'text-slate-300' },
    { icon: Target, label: 'Mission', value: 'Patrouille en cours', color: 'text-blue-400' },
  ]

  return (
    <div className="rounded-xl border border-slate-800 p-5 h-full" style={{ background: '#0f1629' }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-white font-semibold text-sm">État du robot</h2>
        <div className="flex items-center gap-2">
          <span className="text-slate-400 text-xs">{robot.name}</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-emerald-400 text-xs">En ligne</span>
          </div>
        </div>
      </div>

      <BatteryGauge value={robot.battery} />

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
    </div>
  )
}
