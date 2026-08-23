import { Shield, Wifi, Loader2, AlertCircle, Settings2, ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'

const STATUS_MSG: Record<string, { text: string; color: string }> = {
  disconnected: { text: 'Déconnecté',       color: 'text-slate-400 dark:text-slate-400'   },
  connecting:   { text: 'Connexion…',        color: 'text-amber-600 dark:text-amber-400'   },
  error:        { text: 'Connexion échouée', color: 'text-red-600 dark:text-red-400'     },
  connected:    { text: 'Connecté',          color: 'text-emerald-600 dark:text-emerald-400' },
}

export default function ConnectScreen() {
  const conn = useSharedRobotConnection()
  const navigate = useNavigate()
  const location = useLocation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conn.robotIp)

  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  useEffect(() => {
    if (conn.status === 'connected') navigate(from, { replace: true })
  }, [conn.status, navigate, from])

  const isConnecting = conn.status === 'connecting'
  const { text: statusText, color: statusColor } = STATUS_MSG[conn.status]

  const saveAndConnect = () => {
    if (draft !== conn.robotIp) conn.setRobotIp(draft)
    setEditing(false)
    conn.connect()
  }

  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center px-4 bg-slate-100 dark:bg-[#070d1a]"
    >
      {/* Branding */}
      <div className="mb-10 flex flex-col items-center gap-3">
        <div className="w-14 h-14 rounded-2xl bg-blue-600 flex items-center justify-center shadow-xl shadow-blue-900/50">
          <Shield size={28} className="text-white" />
        </div>
        <div className="text-center">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-widest">SENTRYX</h1>
          <p className="text-slate-400 dark:text-slate-500 text-xs mt-1">Surveillance robotique autonome</p>
        </div>
      </div>

      {/* Card */}
      <div
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#0f1629] p-7"
      >
        <h2 className="text-slate-900 dark:text-white font-semibold text-base mb-5 text-center">Connexion au robot</h2>

        {/* Status */}
        <div className="flex items-center gap-2 mb-5 px-3 py-2.5 rounded-xl bg-slate-100 border border-slate-200 dark:bg-slate-800/60 dark:border-slate-700">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
            conn.status === 'connected'  ? 'bg-emerald-400 animate-pulse' :
            conn.status === 'connecting' ? 'bg-amber-400 animate-pulse'  :
            conn.status === 'error'      ? 'bg-red-500'                  :
                                           'bg-slate-400 dark:bg-slate-500'
          }`} />
          <span className={`text-sm font-medium ${statusColor}`}>{statusText}</span>
          {conn.latencyMs && conn.status === 'connected' && (
            <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 font-mono">{conn.latencyMs} ms</span>
          )}
        </div>

        {/* IP input / display */}
        <div className="mb-5">
          <label className="text-xs text-slate-500 dark:text-slate-400 mb-1.5 block">Adresse du robot</label>
          {editing ? (
            <div className="flex gap-2">
              <input
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && saveAndConnect()}
                placeholder="192.168.1.100 ou https://..."
                autoFocus
                className="flex-1 bg-white dark:bg-slate-800 border border-blue-500 text-slate-900 dark:text-white text-sm px-3 py-2.5 rounded-xl font-mono focus:outline-none transition-colors"
              />
              <button
                onClick={() => setEditing(false)}
                className="px-2 text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300 transition-colors"
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              onClick={() => { setDraft(conn.robotIp); setEditing(true) }}
              className="w-full flex items-center gap-2 bg-white border border-slate-300 hover:border-slate-400 dark:bg-slate-800 dark:border-slate-700 dark:hover:border-slate-500 text-slate-700 dark:text-slate-300 text-sm px-3 py-2.5 rounded-xl font-mono transition-colors text-left"
            >
              <Settings2 size={13} className="flex-shrink-0 text-slate-400 dark:text-slate-500" />
              <span className="truncate">{conn.robotIp}</span>
            </button>
          )}
        </div>

        {/* Primary action */}
        {isConnecting ? (
          <button
            onClick={conn.disconnect}
            className="w-full py-3 rounded-xl bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400 font-medium text-sm
              hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-300 dark:border-slate-700 transition-colors
              flex items-center justify-center gap-2"
          >
            <Loader2 size={15} className="animate-spin" />
            Annuler la connexion
          </button>
        ) : (
          <button
            onClick={saveAndConnect}
            className="w-full py-3 rounded-xl bg-blue-600 text-white font-semibold text-sm
              hover:bg-blue-500 transition-colors flex items-center justify-center gap-2
              shadow-lg shadow-blue-900/40"
          >
            <Wifi size={15} />
            Se connecter
          </button>
        )}

        {/* Error banner */}
        {conn.errorMessage && conn.status === 'error' && (
          <div className="mt-4 flex items-start gap-2 text-xs text-red-600 bg-red-50 border border-red-200 dark:text-red-300 dark:bg-red-500/10 dark:border-red-500/20 rounded-lg px-3 py-2.5">
            <AlertCircle size={12} className="flex-shrink-0 mt-0.5" />
            <span>{conn.errorMessage}</span>
          </div>
        )}
      </div>

      {/* Back to app */}
      <button
        onClick={() => navigate(-1)}
        className="mt-6 flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 dark:text-slate-600 dark:hover:text-slate-400 transition-colors"
      >
        <ArrowLeft size={12} />
        Continuer sans connexion
      </button>

      <p className="mt-3 text-xs text-slate-300 dark:text-slate-700">Entrez l'IP locale ou l'URL du tunnel ngrok/Cloudflare</p>
    </div>
  )
}
