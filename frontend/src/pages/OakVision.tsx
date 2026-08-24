import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp,
  Radar, ScanEye, Square, Wifi, WifiOff,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl, getRobotOakStreamUrl } from '../lib/robotTransport'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OakDetection {
  label: string
  confidence: number
  cx: number
  cy: number
  xmin: number
  xmax: number
  ymin: number
  ymax: number
  x_mm: number
  y_mm: number
  z_mm: number
}

interface OakStatus {
  oak_available?: boolean
  oak_connected?: boolean
  oak_usb_speed?: string | null
  oak_error?: string | null
  oak_video_available?: boolean
  oak_detections?: OakDetection[]
  oak_depth_zones?: { left: boolean; center: boolean; right: boolean }
  oak_depth_cm?: { left: number | null; center: number | null; right: number | null }
  oak_last_update_age_s?: number | null
}

const VEHICLE_LABELS = new Set(['car', 'truck', 'bus', 'motorbike', 'motorcycle'])
type Direction = 'forward' | 'backward' | 'left' | 'right'

const KEY_DIRECTIONS: Record<string, Direction> = {
  ArrowUp: 'forward', w: 'forward', W: 'forward',
  ArrowDown: 'backward', s: 'backward', S: 'backward',
  ArrowLeft: 'left', a: 'left', A: 'left',
  ArrowRight: 'right', d: 'right', D: 'right',
}

function boxColor(label: string): string {
  if (label === 'person') return '#22c55e'
  if (VEHICLE_LABELS.has(label)) return '#f59e0b'
  return '#38bdf8'
}

function formatDistance(zMm: number): string {
  return `${(zMm / 1000).toFixed(2)} m`
}

function OakDriveControls({ enabled }: { enabled: boolean }) {
  const connection = useSharedRobotConnection()
  const [speed, setSpeed] = useState(0.25)
  const [active, setActive] = useState<Direction | null>(null)
  const repeatRef = useRef<ReturnType<typeof window.setInterval> | null>(null)
  const activeRef = useRef<Direction | null>(null)

  const stop = useCallback(() => {
    if (repeatRef.current !== null) {
      window.clearInterval(repeatRef.current)
      repeatRef.current = null
    }
    if (activeRef.current !== null) connection.sendStop()
    activeRef.current = null
    setActive(null)
  }, [connection])

  const start = useCallback((direction: Direction) => {
    if (!enabled || activeRef.current === direction) return
    stop()
    activeRef.current = direction
    setActive(direction)
    connection.sendMove(direction, speed)
    repeatRef.current = window.setInterval(
      () => connection.sendMove(direction, speed),
      150,
    )
  }, [connection, enabled, speed, stop])

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.matches('input, textarea, select, button')) return
      const direction = KEY_DIRECTIONS[event.key]
      if (direction) {
        event.preventDefault()
        start(direction)
      } else if (event.key === ' ') {
        event.preventDefault()
        stop()
      }
    }
    const keyUp = (event: KeyboardEvent) => {
      if (KEY_DIRECTIONS[event.key]) stop()
    }
    const release = () => stop()
    window.addEventListener('keydown', keyDown)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('pointerup', release)
    window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', keyDown)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('pointerup', release)
      window.removeEventListener('blur', release)
      stop()
    }
  }, [start, stop])

  const button = (
    direction: Direction,
    label: string,
    icon: React.ReactNode,
    gridArea: string,
  ) => (
    <button
      type="button"
      aria-label={label}
      style={{ gridArea }}
      disabled={!enabled}
      onPointerDown={(event) => { event.preventDefault(); start(direction) }}
      className={`touch-none select-none rounded-xl border flex flex-col items-center justify-center gap-1 transition-colors ${
        active === direction
          ? 'border-blue-400 bg-blue-600 text-white'
          : 'border-slate-200 bg-slate-100 text-slate-600 hover:bg-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
      } disabled:opacity-35`}
    >
      {icon}<span className="text-[10px]">{label}</span>
    </button>
  )

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/50">
      <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
        Pilotage du rover
      </h2>
      <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
        Maintenez un bouton, ou utilisez WASD / les flèches. Espace pour arrêter.
      </p>
      <div className="mt-3 mx-auto grid grid-cols-[repeat(3,62px)] grid-rows-[repeat(3,56px)] justify-center gap-2">
        {button('forward', 'Avant', <ArrowUp size={19} />, '1 / 2')}
        {button('left', 'Gauche', <ArrowLeft size={19} />, '2 / 1')}
        <button
          type="button"
          aria-label="Stop"
          style={{ gridArea: '2 / 2' }}
          onPointerDown={stop}
          disabled={!enabled}
          className="touch-none rounded-xl border border-red-500/40 bg-red-500/15 text-red-500 flex flex-col items-center justify-center gap-1 disabled:opacity-35"
        >
          <Square size={18} /><span className="text-[10px]">Stop</span>
        </button>
        {button('right', 'Droite', <ArrowRight size={19} />, '2 / 3')}
        {button('backward', 'Arrière', <ArrowDown size={19} />, '3 / 2')}
      </div>
      <label className="block mt-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex justify-between mb-1.5">
          <span>Vitesse</span><span>{Math.round(speed * 200)} %</span>
        </span>
        <input
          type="range"
          min="0.15"
          max="0.5"
          step="0.05"
          value={speed}
          onChange={(event) => setSpeed(Number(event.target.value))}
          disabled={!enabled}
          className="w-full accent-blue-500 disabled:opacity-35"
        />
      </label>
      {!enabled && (
        <p className="mt-2 text-[11px] text-amber-600 dark:text-amber-400">
          Pilotage indisponible pendant une patrouille ou lorsque le contrôle manuel est verrouillé.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OakVision() {
  const conn = useSharedRobotConnection()
  const connected = conn.status === 'connected'
  const apiBase = getRobotApiUrl(conn.robotIp)
  const streamUrl = getRobotOakStreamUrl(conn.robotIp)

  const [status, setStatus] = useState<OakStatus>({})
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const streamRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setStreamUnavailable(false)
    setStreamKey(k => k + 1)
    if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
  }, [conn.robotIp, connected])

  useEffect(() => {
    if (!connected) {
      setStatus({})
      return
    }
    let disposed = false
    const poll = async () => {
      try {
        const response = await fetch(`${apiBase}/api/oak/status`)
        if (response.ok && !disposed) setStatus(await response.json())
      } catch {
        // silencieux — on retente au prochain tick
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 400)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [apiBase, connected])

  const detections = status.oak_detections ?? []
  const depthZones = status.oak_depth_zones
  const depthCm = status.oak_depth_cm
  const driveEnabled = connected
    && !(conn.lastStatus?.patrol_active ?? false)
    && (conn.lastStatus?.control_available ?? true)
  const videoReady = connected && Boolean(status.oak_video_available) && !streamUnavailable

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <ScanEye size={20} className="text-blue-600 dark:text-blue-400" />
            Vision OAK-D
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Test exclusif de la caméra OAK-D — ce qu'elle voit, avec label et confiance
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            ok={status.oak_connected ?? false}
            label={status.oak_connected ? 'OAK connectée' : 'OAK déconnectée'}
          />
          {status.oak_usb_speed && (
            <span className="px-2.5 py-1 rounded-lg text-xs font-medium border border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300">
              USB {status.oak_usb_speed}
            </span>
          )}
        </div>
      </div>

      {status.oak_error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-400">
          <AlertCircle size={15} className="flex-shrink-0" />
          {status.oak_error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
        {/* Flux vidéo + overlay détections */}
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden dark:border-slate-800 dark:bg-slate-900/50">
          <div className="relative aspect-square bg-black">
            {connected ? (
              <img
                key={`${streamUrl}-${streamKey}`}
                src={streamUrl}
                alt="Flux OAK-D"
                className={`w-full h-full object-contain ${videoReady ? '' : 'invisible'}`}
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
            ) : null}

            {!videoReady && (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm gap-2">
                <WifiOff size={16} />
                {connected ? 'Attente du flux vidéo OAK…' : 'Robot non connecté'}
              </div>
            )}

            {videoReady && detections.map((det, i) => (
              <div
                key={i}
                className="absolute border-2 pointer-events-none"
                style={{
                  left: `${Math.max(0, det.xmin) * 100}%`,
                  top: `${Math.max(0, det.ymin) * 100}%`,
                  width: `${Math.max(0, Math.min(1, det.xmax) - Math.max(0, det.xmin)) * 100}%`,
                  height: `${Math.max(0, Math.min(1, det.ymax) - Math.max(0, det.ymin)) * 100}%`,
                  borderColor: boxColor(det.label),
                }}
              >
                <span
                  className="absolute -top-5 left-0 px-1.5 py-0.5 text-[10px] font-semibold text-black rounded-t whitespace-nowrap"
                  style={{ background: boxColor(det.label) }}
                >
                  {det.label} · {Math.round(det.confidence * 100)}% · {formatDistance(det.z_mm)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Panneau détections + zones de profondeur */}
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/50">
            <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">
              Détections ({detections.length})
            </h2>
            {detections.length === 0 ? (
              <p className="text-sm text-slate-400 dark:text-slate-600">Rien de détecté</p>
            ) : (
              <ul className="space-y-1.5">
                {detections.map((det, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between text-sm px-2 py-1.5 rounded-lg bg-slate-50 dark:bg-slate-800/50"
                  >
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: boxColor(det.label) }} />
                      <span className="text-slate-700 dark:text-slate-200 capitalize">{det.label}</span>
                    </span>
                    <span className="text-slate-500 dark:text-slate-400 text-xs">
                      {Math.round(det.confidence * 100)}% · {formatDistance(det.z_mm)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/50">
            <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Radar size={13} />
              Zones de profondeur
            </h2>
            <div className="grid grid-cols-3 gap-2">
              {(['left', 'center', 'right'] as const).map(zone => (
                <div
                  key={zone}
                  className={`rounded-lg px-2 py-2 text-center border ${
                    depthZones?.[zone]
                      ? 'bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/30'
                      : 'bg-slate-50 border-slate-200 dark:bg-slate-800/50 dark:border-slate-700'
                  }`}
                >
                  <div className="text-[10px] uppercase text-slate-500 dark:text-slate-400">
                    {zone === 'left' ? 'Gauche' : zone === 'center' ? 'Centre' : 'Droite'}
                  </div>
                  <div className={`text-sm font-semibold ${depthZones?.[zone] ? 'text-red-600 dark:text-red-400' : 'text-slate-700 dark:text-slate-200'}`}>
                    {depthCm?.[zone] != null ? `${depthCm[zone]?.toFixed(0)} cm` : '—'}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
            Dernière mise à jour :{' '}
            {status.oak_last_update_age_s != null ? `il y a ${status.oak_last_update_age_s.toFixed(1)} s` : '—'}
          </div>

          <OakDriveControls enabled={driveEnabled} />
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border ${
        ok
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-600/15 dark:text-emerald-400 dark:border-emerald-600/30'
          : 'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700'
      }`}
    >
      {ok ? <Wifi size={12} /> : <WifiOff size={12} />}
      {label}
    </span>
  )
}
