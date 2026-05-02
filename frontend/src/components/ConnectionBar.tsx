import { useState } from 'react'
import { Wifi, WifiOff, Settings2 } from 'lucide-react'
import { type ConnectionStatus } from '../hooks/useRobotConnection'

// ---------------------------------------------------------------------------
// Barre de connexion partagée (Pilotage + Patrouille)
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<ConnectionStatus, { dot: string; label: string; text: string }> = {
  disconnected: { dot: 'bg-slate-500',              label: 'Déconnecté',  text: 'text-slate-400'  },
  connecting:   { dot: 'bg-amber-400 animate-pulse', label: 'Connexion…',  text: 'text-amber-400'  },
  connected:    { dot: 'bg-emerald-400 animate-pulse', label: 'Connecté',  text: 'text-emerald-400' },
  error:        { dot: 'bg-red-500',                label: 'Erreur',       text: 'text-red-400'    },
}

export interface ConnectionBarProps {
  status: ConnectionStatus
  robotIp: string
  setRobotIp: (ip: string) => void
  connect: () => void
  disconnect: () => void
  latencyMs: number | null
  errorMessage: string | null
}

export function ConnectionBar({
  status, robotIp, setRobotIp, connect, disconnect, latencyMs, errorMessage,
}: ConnectionBarProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(robotIp)
  const s = STATUS_STYLES[status]

  const save = () => {
    setRobotIp(draft)
    setEditing(false)
  }

  return (
    <div
      className="relative z-20 flex flex-wrap items-center gap-3 px-4 sm:px-5 py-3 border-b border-slate-800"
      style={{ background: '#0a0f1e' }}
    >
      <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${s.dot}`} />
      <span className={`text-sm font-medium ${s.text}`}>{s.label}</span>

      {latencyMs !== null && status === 'connected' && (
        <span className="text-xs text-slate-500 font-mono">{latencyMs} ms</span>
      )}

      <div className="flex-1 min-w-0" />

      {/* IP editor */}
      {editing ? (
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && save()}
            className="bg-slate-800 border border-slate-600 text-white text-sm px-3 py-1.5 rounded-lg font-mono w-full sm:w-44 focus:outline-none focus:border-blue-500"
            autoFocus
            placeholder="192.168.1.100"
          />
          <button onClick={save} className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1">OK</button>
          <button onClick={() => setEditing(false)} className="text-xs text-slate-500 hover:text-slate-300 px-1 py-1">✕</button>
        </div>
      ) : (
        <button
          onClick={() => { setDraft(robotIp); setEditing(true) }}
          className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm font-mono px-3 py-1.5 rounded-lg border border-slate-700 hover:border-slate-500 transition-colors max-w-full"
        >
          <Settings2 size={13} />
          <span className="truncate">{robotIp}</span>
        </button>
      )}

      {status === 'connected' ? (
        <button
          onClick={disconnect}
          className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700 transition-colors"
        >
          <WifiOff size={14} />
          Déconnecter
        </button>
      ) : (
        <button
          onClick={connect}
          disabled={status === 'connecting'}
          className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Wifi size={14} />
          Connecter
        </button>
      )}

      {errorMessage && (
        <div className="w-full text-xs text-amber-300/90 border border-amber-500/30 bg-amber-500/10 rounded-lg px-3 py-2">
          {errorMessage}
        </div>
      )}
    </div>
  )
}
