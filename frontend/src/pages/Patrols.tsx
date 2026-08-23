import { useState, useEffect, useRef } from 'react'
import {
  Bot, Radar, Play, Square,
  AlertTriangle, Eye, Camera, CameraOff,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'
import LidarRadar360 from '../components/LidarRadar360'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATE_LABEL: Record<string, { text: string; color: string; pulse: boolean }> = {
  idle:     { text: 'En attente',         color: 'text-slate-400 dark:text-slate-400',   pulse: false },
  scanning: { text: 'Scan LIDAR',         color: 'text-cyan-600 dark:text-cyan-400',    pulse: true  },
  forward:  { text: 'En déplacement',     color: 'text-emerald-600 dark:text-emerald-400', pulse: true  },
  avoiding: { text: 'Évitement…',         color: 'text-amber-600 dark:text-amber-400',   pulse: true  },
  turning_left:  { text: 'Rotation gauche', color: 'text-amber-600 dark:text-amber-400', pulse: true  },
  turning_right: { text: 'Rotation droite', color: 'text-amber-600 dark:text-amber-400', pulse: true  },
  backing_up: { text: 'Recul sécurisé',   color: 'text-orange-600 dark:text-orange-400',  pulse: true  },
  stopped:  { text: 'Stop sécurité',      color: 'text-red-600 dark:text-red-400',     pulse: true  },
  stuck:    { text: 'Coincé — recul…',    color: 'text-orange-600 dark:text-orange-400',  pulse: true  },
}

function DistanceBar({ cm, label }: { cm: number | null | undefined; label: string }) {
  const pct = cm != null ? Math.max(0, Math.min(100, (cm / 300) * 100)) : 0
  const color = cm == null ? 'bg-slate-400 dark:bg-slate-700'
    : cm < 20 ? 'bg-red-500'
    : cm < 50 ? 'bg-amber-500'
    : 'bg-emerald-500'

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400 dark:text-slate-400">{label}</span>
        <span className={`font-mono font-medium ${cm == null ? 'text-slate-400 dark:text-slate-600' : cm < 20 ? 'text-red-600 dark:text-red-400' : cm < 50 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
          {cm != null ? `${cm.toFixed(0)} cm` : '—'}
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
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
  const [streamKey, setStreamKey] = useState(0)
  const streamRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const patrolActive      = conn.lastStatus?.patrol_active ?? false
  const patrolState       = conn.lastStatus?.patrol_state ?? 'idle'
  const patrolDecision    = conn.lastStatus?.patrol_decision
  const patrolReason      = conn.lastStatus?.patrol_decision_reason
  const frontCm           = conn.lastStatus?.lidar_front_cm ?? conn.lastStatus?.front_cm
  const obstacle          = conn.lastStatus?.lidar_obstacle_front ?? conn.lastStatus?.obstacle_front ?? false
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
    setStreamKey(k => k + 1)
    if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
  }, [conn.robotIp, conn.status])

  return (
    <div className="-m-3 sm:-m-4 lg:-m-6 flex flex-col min-h-full" style={{ background: '#070d1a' }}>

      {/* ---- Corps : caméra gauche + contrôles droite (identique à Pilotage) ---- */}
      <div className="flex flex-col xl:flex-row flex-1 overflow-hidden">

        {/* ── Caméra (flex-1, prend toute la hauteur) ── */}
        <div className="flex-1 flex flex-col xl:border-r border-slate-800 min-w-0 min-h-[45vh] xl:min-h-0">
          <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-800">
            <span className="text-sm font-medium text-slate-300">Flux caméra — Patrouille</span>
            {isConnected && (
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                <span className="text-xs text-red-400">EN DIRECT</span>
              </div>
            )}
          </div>

          <div
            className="flex-1 flex items-center justify-center relative min-h-[40vh] xl:min-h-0"
            style={{ background: '#040810' }}
          >
            {/* Sci-fi grid */}
            <svg className="absolute inset-0 w-full h-full opacity-5 pointer-events-none">
              <defs>
                <pattern id="pgrid-patrol" width="50" height="50" patternUnits="userSpaceOnUse">
                  <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#3b82f6" strokeWidth="0.5" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#pgrid-patrol)" />
            </svg>
            {/* Scan lines */}
            <div className="absolute inset-0 pointer-events-none opacity-[0.03]"
              style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 3px, #3b82f6 3px, #3b82f6 4px)' }} />

            {/* Corner brackets */}
            {(['top-4 left-4 border-t-2 border-l-2 rounded-tl', 'top-4 right-4 border-t-2 border-r-2 rounded-tr',
              'bottom-4 left-4 border-b-2 border-l-2 rounded-bl', 'bottom-4 right-4 border-b-2 border-r-2 rounded-br'] as const).map((cls, i) => (
              <div key={i} className={`absolute w-8 h-8 border-blue-500/40 ${cls}`} />
            ))}

            {isConnected && (
              <img
                key={`${streamUrl}-${streamKey}`}
                src={streamUrl}
                alt="Camera feed"
                className={`w-full h-full object-contain bg-black z-10 ${streamUnavailable ? 'hidden' : ''}`}
                onLoad={() => {
                  setStreamUnavailable(false)
                  if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
                }}
                onError={() => {
                  setStreamUnavailable(true)
                  if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
                  streamRetryRef.current = setTimeout(() => {
                    setStreamUnavailable(false)
                    setStreamKey(k => k + 1)
                  }, 4000)
                }}
              />
            )}

            {(!isConnected || streamUnavailable) && (
              <div className="text-center z-10 px-6">
                {streamUnavailable ? (
                  <CameraOff size={48} className="mx-auto mb-3 text-slate-700" />
                ) : (
                  <Camera size={48} className="mx-auto mb-3 text-slate-700" />
                )}
                <p className="text-slate-600 text-sm">
                  {!isConnected
                    ? 'Connecte-toi au robot pour voir le flux'
                    : 'Flux caméra indisponible'}
                </p>
              </div>
            )}

            {/* Patrol state overlay */}
            {patrolActive && (
              <div className={`absolute top-4 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 rounded-xl px-4 py-2 backdrop-blur-sm border ${
                patrolState === 'stuck'    ? 'bg-orange-900/90 border-orange-500' :
                patrolState === 'avoiding' ? 'bg-amber-900/90 border-amber-500'  :
                                             'bg-blue-900/90 border-blue-500'
              }`}>
                <Bot size={14} className={
                  patrolState === 'stuck'    ? 'text-orange-300' :
                  patrolState === 'avoiding' ? 'text-amber-300'  : 'text-blue-300'
                } />
                <span className={`text-xs font-bold ${
                  patrolState === 'stuck'    ? 'text-orange-200' :
                  patrolState === 'avoiding' ? 'text-amber-200'  : 'text-blue-200'
                }`}>
                  {patrolState === 'stuck'    ? '⚠ SCAN DÉBLOCAGE…'    :
                   patrolState === 'avoiding' ? '↩ ÉVITEMENT EN COURS' :
                                                '▶ PATROUILLE ACTIVE'}
                </span>
              </div>
            )}

            {/* Obstacle overlay */}
            {(obstacle || visionObstacle) && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 bg-red-900/90 border border-red-500 rounded-xl px-4 py-2 animate-pulse backdrop-blur-sm">
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
          </div>
        </div>

        {/* ── Contrôles droite (colonne fixe, scrollable) ── */}
        <div className="w-full xl:w-96 flex-shrink-0 overflow-y-auto bg-white dark:bg-[#0a0f1e]">
          <div className="px-5 py-5 space-y-4">

            {/* Patrol controls */}
            <div className="rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-[#0f1629] p-5">
              <div className="flex items-center gap-2 mb-4">
                <Bot size={16} className="text-blue-600 dark:text-blue-400" />
                <h2 className="text-slate-900 dark:text-white font-semibold text-sm">Contrôle patrouille</h2>
              </div>

              {/* State */}
              <div className="flex items-center justify-between mb-5 px-4 py-3 rounded-xl bg-slate-100 border border-slate-200 dark:bg-slate-800/50 dark:border-slate-700">
                <span className="text-xs text-slate-500 dark:text-slate-400">État</span>
                <div className="flex items-center gap-2">
                  {stateInfo.pulse && <div className={`w-2 h-2 rounded-full animate-pulse ${patrolState === 'avoiding' ? 'bg-amber-400' : 'bg-emerald-400'}`} />}
                  <span className={`text-sm font-bold ${stateInfo.color}`}>{stateInfo.text}</span>
                </div>
              </div>
              {(patrolDecision || patrolReason) && (
                <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/50 px-3 py-2">
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400 dark:text-slate-500">Décision</span>
                    <span className="font-mono text-cyan-700 dark:text-cyan-300">{patrolDecision ?? '--'}</span>
                  </div>
                  {patrolReason && (
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">{patrolReason}</p>
                  )}
                </div>
              )}

              {/* Start / Stop button */}
              <button
                onClick={() => patrolActive ? conn.stopPatrol() : conn.startPatrol()}
                disabled={!isConnected}
                className={`w-full py-4 rounded-xl border-2 font-bold text-base flex items-center justify-center gap-3 transition-all active:scale-95 ${
                  !isConnected
                    ? 'bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed dark:bg-slate-800/40 dark:text-slate-600 dark:border-slate-800'
                    : patrolActive
                      ? 'bg-red-50 text-red-600 border-red-300 hover:bg-red-600 hover:text-white hover:border-red-600 dark:bg-red-600/15 dark:text-red-400 dark:border-red-600/50'
                      : 'bg-blue-50 text-blue-600 border-blue-300 hover:bg-blue-600 hover:text-white hover:border-blue-600 dark:bg-blue-600/15 dark:text-blue-400 dark:border-blue-600/50'
                }`}
              >
                {patrolActive ? <Square size={20} /> : <Play size={20} />}
                {patrolActive ? 'Arrêter la patrouille' : 'Lancer la patrouille'}
              </button>

              {!isConnected && (
                <p className="mt-3 text-xs text-slate-400 dark:text-slate-500 text-center">Connectez-vous au robot pour démarrer</p>
              )}
            </div>

            {/* Sensors */}
            <div className="rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-[#0f1629] p-5">
              <div className="flex items-center gap-2 mb-4">
                <Radar size={16} className="text-blue-600 dark:text-blue-400" />
                <h2 className="text-slate-900 dark:text-white font-semibold text-sm">Détection d'obstacles</h2>
              </div>

              {conn.lastStatus?.sensor_error ? (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 dark:bg-red-950/40 dark:border-red-800/40 mb-4">
                  <AlertTriangle size={14} className="text-red-600 dark:text-red-400 flex-shrink-0" />
                  <span className="text-xs text-red-600 dark:text-red-400">{conn.lastStatus.sensor_error}</span>
                </div>
              ) : !isConnected ? (
                <p className="text-xs text-slate-400 dark:text-slate-600 mb-4">Données indisponibles</p>
              ) : null}

              {/* Ultrason */}
              <div className="flex items-center gap-1.5 mb-2">
                <Radar size={11} className="text-slate-400 dark:text-slate-500" />
                <span className="text-xs text-slate-400 dark:text-slate-500 uppercase tracking-wide">Ultrason</span>
              </div>
              <div className="space-y-3 mb-4">
                <DistanceBar cm={conn.lastStatus?.front_cm} label="Avant" />
                <DistanceBar cm={conn.lastStatus?.rear_cm}  label="Arrière" />
              </div>

              {/* LIDAR 360° radar */}
              <div className="flex items-center gap-1.5 mb-2">
                <Radar size={11} className={conn.lastScan?.connected ? 'text-cyan-600 dark:text-cyan-400' : 'text-slate-400 dark:text-slate-500'} />
                <span className="text-xs text-slate-400 dark:text-slate-500 uppercase tracking-wide">LIDAR 360°</span>
                <span className={`ml-auto text-[10px] font-mono ${conn.lastScan?.connected ? 'text-cyan-600 dark:text-cyan-400' : 'text-slate-400 dark:text-slate-600'}`}>
                  {conn.lastScan?.connected ? `${conn.lastScan.points.length} pts` : 'hors ligne'}
                </span>
              </div>
              <div className="flex justify-center mb-3">
                <LidarRadar360
                  points={conn.lastScan?.points}
                  rangeMaxM={conn.lastScan?.range_max_m ?? 6}
                  connected={Boolean(conn.lastScan?.connected)}
                  error={conn.lastScan?.error}
                  size={200}
                />
              </div>

              {/* LIDAR robot frame */}
              <div className="flex items-center gap-1.5 mb-2">
                <Radar size={11} className="text-slate-400 dark:text-slate-500" />
                <span className="text-xs text-slate-400 dark:text-slate-500 uppercase tracking-wide">LIDAR — repère robot</span>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <DistanceBar cm={conn.lastStatus?.lidar_front_cm} label="Avant" />
                <DistanceBar cm={conn.lastStatus?.lidar_right_cm} label="Droite" />
                <DistanceBar cm={conn.lastStatus?.lidar_rear_cm} label="Arrière" />
                <DistanceBar cm={conn.lastStatus?.lidar_left_cm} label="Gauche" />
              </div>
              {/* Vision 3 zones */}
              <div className="flex items-center gap-1.5 mb-2">
                <Eye size={11} className="text-slate-400 dark:text-slate-500" />
                <span className="text-xs text-slate-400 dark:text-slate-500 uppercase tracking-wide">Caméra — zones L/C/D</span>
                {isConnected && !visionAvailable && (
                  <span className="ml-auto text-xs text-amber-600 dark:text-amber-500/70">OpenCV absent</span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-1.5 mb-3">
                {([['G', visionLeft], ['C', visionCenter], ['D', visionRight]] as [string, boolean][]).map(([label, obs]) => (
                  <div key={label} className={`flex flex-col items-center py-2 rounded-lg border text-xs font-bold transition-colors ${
                    obs
                      ? 'bg-red-50 border-red-300 text-red-600 animate-pulse dark:bg-red-950/60 dark:border-red-700/50 dark:text-red-400'
                      : visionAvailable
                        ? 'bg-slate-100 border-slate-200 text-slate-500 dark:bg-slate-800/40 dark:border-slate-700 dark:text-slate-500'
                        : 'bg-slate-50 border-slate-100 text-slate-300 dark:bg-slate-800/20 dark:border-slate-800 dark:text-slate-700'
                  }`}>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 mb-0.5">{label === 'G' ? 'Gauche' : label === 'C' ? 'Centre' : 'Droite'}</span>
                    <span>{obs ? '⚠' : '✓'}</span>
                  </div>
                ))}
              </div>
              {visionAvailable && visionObstacle && (
                <div className="text-[10px] text-slate-400 dark:text-slate-500 text-right mb-3 font-mono">
                  {visionMethod === 'uniform' ? 'surface lisse' : 'contours'} · {Math.round(visionConfidence * 100)}%
                </div>
              )}

              {/* Combined obstacle */}
              {conn.lastStatus && (
                <div className={`px-3 py-2 rounded-lg text-center text-xs font-bold transition-colors ${
                  conn.lastStatus.obstacle
                    ? 'bg-red-50 border border-red-300 text-red-600 animate-pulse dark:bg-red-950/60 dark:border-red-700/50 dark:text-red-400'
                    : 'bg-slate-100 border border-slate-200 text-slate-500 dark:bg-slate-800/40 dark:border-slate-700 dark:text-slate-500'
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
