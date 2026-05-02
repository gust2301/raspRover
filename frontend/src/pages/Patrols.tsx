import { useState, useEffect } from 'react'
import {
  Bot, Radar, Wifi, WifiOff, Settings2, Play, Square,
  ChevronDown, ChevronUp, AlertTriangle, Eye,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATE_LABEL: Record<string, { text: string; color: string; pulse: boolean }> = {
  idle:     { text: 'En attente',         color: 'text-slate-400',   pulse: false },
  scanning: { text: 'Scan L/C/D…',        color: 'text-blue-300',    pulse: true  },
  forward:  { text: 'En déplacement',     color: 'text-emerald-400', pulse: true  },
  avoiding: { text: 'Évitement…',         color: 'text-amber-400',   pulse: true  },
  stuck:    { text: 'Coincé — recul…',    color: 'text-orange-400',  pulse: true  },
}

function DistanceBar({ cm, label }: { cm: number | null | undefined; label: string }) {
  const pct = cm != null ? Math.max(0, Math.min(100, (cm / 300) * 100)) : 0
  const color = cm == null ? 'bg-slate-700'
    : cm < 20 ? 'bg-red-500'
    : cm < 50 ? 'bg-amber-500'
    : 'bg-emerald-500'

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400">{label}</span>
        <span className={`font-mono font-medium ${cm == null ? 'text-slate-600' : cm < 20 ? 'text-red-400' : cm < 50 ? 'text-amber-400' : 'text-emerald-400'}`}>
          {cm != null ? `${cm.toFixed(0)} cm` : '—'}
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-300 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page principale
// ---------------------------------------------------------------------------

export default function Patrols() {
  const conn = useSharedRobotConnection()
  const streamUrl = getRobotStreamUrl(conn.robotIp)
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(conn.robotIp)

  const patrolActive      = conn.lastStatus?.patrol_active ?? false
  const patrolState       = conn.lastStatus?.patrol_state ?? 'idle'
  const frontCm           = conn.lastStatus?.front_cm
  const obstacle          = conn.lastStatus?.obstacle_front ?? false
  const visionObstacle    = conn.lastStatus?.vision_obstacle ?? false
  const visionLeft        = conn.lastStatus?.vision_left ?? false
  const visionCenter      = conn.lastStatus?.vision_center ?? false
  const visionRight       = conn.lastStatus?.vision_right ?? false
  const visionConfidence  = conn.lastStatus?.vision_confidence ?? 0
  const visionAvailable   = conn.lastStatus?.vision_available ?? false
  const visionMethod      = conn.lastStatus?.vision_method ?? 'none'
  const stateInfo         = STATE_LABEL[patrolState] ?? STATE_LABEL.idle
  const isConnected       = conn.status === 'connected'

  useEffect(() => {
    setStreamUnavailable(false)
  }, [conn.robotIp, conn.status])

  return (
    <div className="flex flex-col h-full min-h-0 gap-0" style={{ background: '#070d1a' }}>

      {/* ---- Barre de connexion ---- */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 flex-shrink-0" style={{ background: '#0a0f1e' }}>
        <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${isConnected ? 'bg-emerald-400 animate-pulse' : conn.status === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-slate-500'}`} />
        <span className={`text-sm font-medium ${isConnected ? 'text-emerald-400' : 'text-slate-400'}`}>
          {isConnected ? 'Connecté' : conn.status === 'connecting' ? 'Connexion…' : 'Déconnecté'}
        </span>
        {isConnected && conn.latencyMs !== null && (
          <span className="text-xs text-slate-500 font-mono">{conn.latencyMs} ms</span>
        )}
        <div className="flex-1" />

        {/* IP editor */}
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { conn.setRobotIp(draft); setEditing(false) } }}
              className="bg-slate-800 border border-slate-600 text-white text-sm px-3 py-1 rounded-lg font-mono w-44 focus:outline-none focus:border-blue-500"
              autoFocus
            />
            <button onClick={() => { conn.setRobotIp(draft); setEditing(false) }} className="text-xs text-blue-400 px-2">OK</button>
            <button onClick={() => setEditing(false)} className="text-xs text-slate-500 px-1">✕</button>
          </div>
        ) : (
          <button
            onClick={() => { setDraft(conn.robotIp); setEditing(true) }}
            className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm font-mono px-3 py-1 rounded-lg border border-slate-700 hover:border-slate-500 transition-colors"
          >
            <Settings2 size={13} />
            <span className="truncate max-w-[160px]">{conn.robotIp}</span>
          </button>
        )}

        {isConnected ? (
          <button onClick={conn.disconnect} className="px-4 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700">
            <WifiOff size={14} className="inline mr-1.5" />Déconnecter
          </button>
        ) : (
          <button onClick={conn.connect} className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500">
            <Wifi size={14} className="inline mr-1.5" />Connecter
          </button>
        )}
      </div>

      {/* ---- Corps ---- */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-4 py-5 space-y-4">

          {/* Video feed */}
          <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
              <h2 className="text-white font-semibold text-sm">Flux vidéo — Patrouille</h2>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
                <span className={`text-xs ${isConnected ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {isConnected ? 'En direct' : 'Hors ligne'}
                </span>
              </div>
            </div>

            <div className="relative aspect-video bg-slate-950 flex items-center justify-center overflow-hidden">
              {/* Grid background */}
              <div className="absolute inset-0" style={{ background: 'linear-gradient(180deg, #0a0f1e 0%, #111827 60%, #1e293b 100%)' }}>
                <svg className="absolute inset-0 w-full h-full opacity-10" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <pattern id="pg" width="60" height="60" patternUnits="userSpaceOnUse">
                      <path d="M 60 0 L 0 0 0 60" fill="none" stroke="#3b82f6" strokeWidth="0.5" />
                    </pattern>
                  </defs>
                  <rect width="100%" height="100%" fill="url(#pg)" />
                </svg>
              </div>

              {isConnected && !streamUnavailable && (
                <img
                  key={streamUrl}
                  src={streamUrl}
                  alt="Camera feed"
                  className="absolute inset-0 w-full h-full object-contain bg-black z-10"
                  onLoad={() => setStreamUnavailable(false)}
                  onError={() => setStreamUnavailable(true)}
                />
              )}

              {(!isConnected || streamUnavailable) && (
                <div className="absolute inset-0 flex items-center justify-center z-10 text-slate-600 text-xs opacity-40">
                  {isConnected ? 'Flux indisponible' : 'Connectez-vous pour voir le flux'}
                </div>
              )}

              {/* Patrol state overlay */}
              {patrolActive && (
                <div className={`absolute top-4 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 rounded-xl px-4 py-2 backdrop-blur-sm border ${
                  patrolState === 'stuck'    ? 'bg-orange-900/90 border-orange-500' :
                  patrolState === 'avoiding' ? 'bg-amber-900/90 border-amber-500'  :
                  patrolState === 'scanning' ? 'bg-indigo-900/90 border-indigo-500' :
                                               'bg-blue-900/90 border-blue-500'
                }`}>
                  <Bot size={14} className={
                    patrolState === 'stuck' ? 'text-orange-300' :
                    patrolState === 'avoiding' ? 'text-amber-300' :
                    patrolState === 'scanning' ? 'text-indigo-300' : 'text-blue-300'
                  } />
                  <span className={`text-xs font-bold ${
                    patrolState === 'stuck' ? 'text-orange-200' :
                    patrolState === 'avoiding' ? 'text-amber-200' :
                    patrolState === 'scanning' ? 'text-indigo-200' : 'text-blue-200'
                  }`}>
                    {patrolState === 'stuck'    ? '⚠ COINCÉ — RECUL EN COURS'  :
                     patrolState === 'avoiding' ? '↩ ÉVITEMENT EN COURS'        :
                     patrolState === 'scanning' ? '⟳ SCAN L/C/D…'              :
                                                  '▶ PATROUILLE ACTIVE'}
                  </span>
                </div>
              )}

              {/* Obstacle overlay */}
              {(obstacle || visionObstacle) && (
                <div className="absolute bottom-12 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 bg-red-900/90 border border-red-500 rounded-xl px-4 py-2 animate-pulse backdrop-blur-sm">
                  {visionObstacle && !obstacle ? (
                    <Eye size={14} className="text-red-400" />
                  ) : (
                    <Radar size={14} className="text-red-400" />
                  )}
                  <span className="text-red-200 text-xs font-bold">
                    {obstacle
                      ? `OBSTACLE — ${frontCm?.toFixed(0)} cm`
                      : visionMethod === 'uniform'
                        ? 'MUR / MEUBLE DÉTECTÉ'
                        : 'OBSTACLE VISUEL'}
                  </span>
                </div>
              )}

              {/* Corner decorations */}
              <div className="absolute top-3 left-3 w-5 h-5 border-t-2 border-l-2 border-blue-500/50 rounded-tl z-20" />
              <div className="absolute top-3 right-3 w-5 h-5 border-t-2 border-r-2 border-blue-500/50 rounded-tr z-20" />
              <div className="absolute bottom-3 left-3 w-5 h-5 border-b-2 border-l-2 border-blue-500/50 rounded-bl z-20" />
              <div className="absolute bottom-3 right-3 w-5 h-5 border-b-2 border-r-2 border-blue-500/50 rounded-br z-20" />
            </div>
          </div>

          {/* Controls + Sensors */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

            {/* Patrol controls */}
            <div className="rounded-xl border border-slate-800 p-5" style={{ background: '#0f1629' }}>
              <div className="flex items-center gap-2 mb-4">
                <Bot size={16} className="text-blue-400" />
                <h2 className="text-white font-semibold text-sm">Contrôle patrouille</h2>
              </div>

              {/* State */}
              <div className="flex items-center justify-between mb-5 px-4 py-3 rounded-xl bg-slate-800/50 border border-slate-700">
                <span className="text-xs text-slate-400">État</span>
                <div className="flex items-center gap-2">
                  {stateInfo.pulse && <div className={`w-2 h-2 rounded-full animate-pulse ${patrolState === 'avoiding' ? 'bg-amber-400' : 'bg-emerald-400'}`} />}
                  <span className={`text-sm font-bold ${stateInfo.color}`}>{stateInfo.text}</span>
                </div>
              </div>

              {/* Start / Stop button */}
              <button
                onClick={() => patrolActive ? conn.stopPatrol() : conn.startPatrol()}
                disabled={!isConnected}
                className={`w-full py-4 rounded-xl border-2 font-bold text-base flex items-center justify-center gap-3 transition-all active:scale-95 ${
                  !isConnected
                    ? 'bg-slate-800/40 text-slate-600 border-slate-800 cursor-not-allowed'
                    : patrolActive
                      ? 'bg-red-600/15 text-red-400 border-red-600/50 hover:bg-red-600 hover:text-white hover:border-red-600'
                      : 'bg-blue-600/15 text-blue-400 border-blue-600/50 hover:bg-blue-600 hover:text-white hover:border-blue-600'
                }`}
              >
                {patrolActive ? <Square size={20} /> : <Play size={20} />}
                {patrolActive ? 'Arrêter la patrouille' : 'Lancer la patrouille'}
              </button>

              {!isConnected && (
                <p className="mt-3 text-xs text-slate-500 text-center">Connectez-vous au robot pour démarrer</p>
              )}

              {/* Settings toggle */}
              <button
                onClick={() => setShowSettings(v => !v)}
                className="w-full mt-4 flex items-center justify-between text-xs text-slate-500 hover:text-slate-300 transition-colors px-1"
              >
                <span>Paramètres avancés</span>
                {showSettings ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>

              {showSettings && (
                <div className="mt-3 space-y-2 text-xs text-slate-400 border border-slate-800 rounded-lg px-4 py-3">
                  <p className="text-slate-500">Ces paramètres se configurent dans <code className="text-blue-400">config.yaml</code> sur le Pi :</p>
                  <pre className="text-slate-400 bg-slate-900 rounded p-2 text-[11px] leading-relaxed">{`patrol:
  speed: 0.3                # 0-1
  obstacle_cm: 40           # cm (ultrason)
  step_duration: 0.7        # s par étape
  stuck_timeout: 3.5        # s avant recul
  scan_with_pantilt: false  # sweep caméra L/C/D`}</pre>
                </div>
              )}
            </div>

            {/* Sensors */}
            <div className="rounded-xl border border-slate-800 p-5" style={{ background: '#0f1629' }}>
              <div className="flex items-center gap-2 mb-4">
                <Radar size={16} className="text-blue-400" />
                <h2 className="text-white font-semibold text-sm">Détection d'obstacles</h2>
              </div>

              {conn.lastStatus?.sensor_error ? (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-950/40 border border-red-800/40 mb-4">
                  <AlertTriangle size={14} className="text-red-400 flex-shrink-0" />
                  <span className="text-xs text-red-400">{conn.lastStatus.sensor_error}</span>
                </div>
              ) : !isConnected ? (
                <p className="text-xs text-slate-600 mb-4">Données indisponibles</p>
              ) : null}

              {/* Ultrason */}
              <div className="flex items-center gap-1.5 mb-2">
                <Radar size={11} className="text-slate-500" />
                <span className="text-xs text-slate-500 uppercase tracking-wide">Ultrason</span>
              </div>
              <div className="space-y-3 mb-4">
                <DistanceBar cm={conn.lastStatus?.front_cm} label="Avant" />
                <DistanceBar cm={conn.lastStatus?.rear_cm}  label="Arrière" />
              </div>

              {/* Vision 3 zones */}
              <div className="flex items-center gap-1.5 mb-2">
                <Eye size={11} className="text-slate-500" />
                <span className="text-xs text-slate-500 uppercase tracking-wide">Caméra — zones L/C/D</span>
                {isConnected && !visionAvailable && (
                  <span className="ml-auto text-xs text-amber-500/70">OpenCV absent</span>
                )}
              </div>
              {/* Zone bars */}
              <div className="grid grid-cols-3 gap-1.5 mb-3">
                {([['G', visionLeft], ['C', visionCenter], ['D', visionRight]] as [string, boolean][]).map(([label, obs]) => (
                  <div key={label} className={`flex flex-col items-center py-2 rounded-lg border text-xs font-bold transition-colors ${
                    obs
                      ? 'bg-red-950/60 border-red-700/50 text-red-400 animate-pulse'
                      : visionAvailable
                        ? 'bg-slate-800/40 border-slate-700 text-slate-500'
                        : 'bg-slate-800/20 border-slate-800 text-slate-700'
                  }`}>
                    <span className="text-[10px] text-slate-500 mb-0.5">{label === 'G' ? 'Gauche' : label === 'C' ? 'Centre' : 'Droite'}</span>
                    <span>{obs ? '⚠' : '✓'}</span>
                  </div>
                ))}
              </div>
              {visionAvailable && visionObstacle && (
                <div className="text-[10px] text-slate-500 text-right mb-3 font-mono">
                  {visionMethod === 'uniform' ? 'surface lisse' : 'contours'} · {Math.round(visionConfidence * 100)}%
                </div>
              )}

              {/* Combined obstacle */}
              {conn.lastStatus && (
                <div className={`px-3 py-2 rounded-lg text-center text-xs font-bold transition-colors ${
                  conn.lastStatus.obstacle
                    ? 'bg-red-950/60 border border-red-700/50 text-red-400 animate-pulse'
                    : 'bg-slate-800/40 border border-slate-700 text-slate-500'
                }`}>
                  {conn.lastStatus.obstacle ? '⚠ OBSTACLE DÉTECTÉ' : 'Voie libre'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
