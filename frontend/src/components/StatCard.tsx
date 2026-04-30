import type { ReactNode } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'

interface StatCardProps {
  icon: ReactNode
  iconBg: string
  value: string
  label: string
  sub: string
  trend?: { value: string; up: boolean }
  statusDot?: 'green' | 'amber' | 'red'
}

export default function StatCard({ icon, iconBg, value, label, sub, trend, statusDot }: StatCardProps) {
  return (
    <div
      className="rounded-xl p-5 border border-slate-800 hover:border-slate-700 transition-colors"
      style={{ background: '#0f1629' }}
    >
      <div className="flex items-start justify-between mb-4">
        <div className={`w-11 h-11 rounded-lg flex items-center justify-center ${iconBg}`}>
          {icon}
        </div>
        {trend && (
          <div className={`flex items-center gap-1 text-xs font-medium ${trend.up ? 'text-emerald-400' : 'text-red-400'}`}>
            {trend.up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {trend.value}
          </div>
        )}
      </div>
      <div className="text-3xl font-bold text-white mb-1">{value}</div>
      <div className="text-slate-400 text-sm font-medium mb-1">{label}</div>
      <div className="flex items-center gap-1.5">
        {statusDot && (
          <div className={`w-1.5 h-1.5 rounded-full ${
            statusDot === 'green' ? 'bg-emerald-500' :
            statusDot === 'amber' ? 'bg-amber-500' : 'bg-red-500'
          }`} />
        )}
        <span className={`text-xs ${
          statusDot === 'green' ? 'text-emerald-400' :
          statusDot === 'amber' ? 'text-amber-400' :
          statusDot === 'red' ? 'text-red-400' : 'text-slate-500'
        }`}>{sub}</span>
      </div>
    </div>
  )
}
