import { Terminal, CheckCircle2, AlertCircle, XCircle, Info } from 'lucide-react'
import { mockLogs } from '../data/incidents'
import type { SystemLog } from '../types'

const LOG_STYLES = {
  success: { icon: CheckCircle2, color: 'text-emerald-400' },
  info: { icon: Info, color: 'text-blue-400' },
  warning: { icon: AlertCircle, color: 'text-amber-400' },
  error: { icon: XCircle, color: 'text-red-400' },
}

function LogRow({ log }: { log: SystemLog }) {
  const { icon: Icon, color } = LOG_STYLES[log.type]
  return (
    <div className="flex items-center gap-2 py-1.5">
      <Icon size={12} className={`flex-shrink-0 ${color}`} />
      <span className="text-slate-400 text-xs flex-1">{log.message}</span>
      <span className="text-slate-600 text-xs font-mono flex-shrink-0">{log.time}</span>
    </div>
  )
}

export default function SystemLogs() {
  return (
    <div className="rounded-xl border border-slate-800 p-5" style={{ background: '#0f1629' }}>
      <div className="flex items-center gap-2 mb-3">
        <Terminal size={14} className="text-slate-400" />
        <h2 className="text-white font-semibold text-sm">Logs système</h2>
        <div className="ml-auto w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      </div>
      <div className="divide-y divide-slate-800/50 font-mono">
        {mockLogs.map(log => <LogRow key={log.id} log={log} />)}
      </div>
    </div>
  )
}
