import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Wifi, AlertOctagon, ArrowUp, ArrowDown, ArrowLeft, ArrowRight,
  Square, Camera, CameraOff, Activity, Lightbulb, Siren, Radar,
  Image, Video, VideoOff, Loader2, Circle, Crosshair,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'
import { useMedia } from '../hooks/useMedia'

// ---------------------------------------------------------------------------
// D-pad
// ---------------------------------------------------------------------------

type Direction = 'forward' | 'backward' | 'left' | 'right'

const KEY_MAP: Record<string, Direction> = {
  ArrowUp: 'forward', w: 'forward', W: 'forward',
  ArrowDown: 'backward', s: 'backward', S: 'backward',
  ArrowLeft: 'left', a: 'left', A: 'left',
  ArrowRight: 'right', d: 'right', D: 'right',
}

function Dpad({
  onMove, onStop, speed, connected,
}: {
  onMove: (dir: Direction) => void
  onStop: () => void
  speed: number
  connected: boolean
}) {
  const [active, setActive] = useState<Direction | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const startMove = useCallback((dir: Direction) => {
    if (!connected) return
    setActive(dir)
    onMove(dir)
    intervalRef.current = setInterval(() => onMove(dir), 150)
  }, [connected, onMove])

  const stopMove = useCallback(() => {
    setActive(null)
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    onStop()
  }, [onStop])

  // Keyboard
  useEffect(() => {
    const held = new Set<string>()
    const down = (e: KeyboardEvent) => {
      if (held.has(e.key)) return
      const dir = KEY_MAP[e.key]
      if (dir) { held.add(e.key); startMove(dir) }
      if (e.key === ' ') { e.preventDefault(); stopMove() }
    }
    const up = (e: KeyboardEvent) => {
      if (KEY_MAP[e.key]) { held.delete(e.key); stopMove() }
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up) }
  }, [startMove, stopMove])

  useEffect(() => () => { if (intervalRef.current) clearInterval(intervalRef.current) }, [])

  const btn = (dir: Direction, icon: React.ReactNode, label: string, style: React.CSSProperties) => (
    <button
      style={style}
      onPointerDown={() => startMove(dir)}
      onPointerUp={stopMove}
      onPointerLeave={stopMove}
      disabled={!connected}
      className={`rounded-2xl flex flex-col items-center justify-center gap-1.5 font-medium select-none touch-none transition-all duration-100
        ${!connected ? 'bg-slate-800/40 text-slate-700 cursor-not-allowed' :
          active === dir
            ? 'bg-blue-600 text-white scale-95 shadow-xl shadow-blue-900/60'
            : 'bg-slate-800 text-slate-300 hover:bg-slate-700 active:bg-blue-600 active:text-white border border-slate-700'
        }`}
    >
      {icon}
      <span className="text-xs leading-none">{label}</span>
    </button>
  )

  return (
    <div className="flex flex-col items-center gap-2">
      {/* WASD hint */}
      <p className="text-xs text-slate-600 mb-1">WASD / Flèches · Espace = Stop</p>

      {/* Grid 3×3 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 88px)', gridTemplateRows: 'repeat(3, 88px)', gap: 10 }}>
        {/* Haut */}
        {btn('forward', <ArrowUp size={28} />, 'Avant', { gridArea: '1 / 2' })}
        {/* Gauche */}
        {btn('left', <ArrowLeft size={28} />, 'Gauche', { gridArea: '2 / 1' })}
        {/* Stop */}
        <button
          style={{ gridArea: '2 / 2' }}
          onPointerDown={stopMove}
          disabled={!connected}
          className={`rounded-2xl flex flex-col items-center justify-center gap-1.5 select-none touch-none transition-all duration-100 font-bold
            ${!connected ? 'bg-slate-800/40 text-slate-700 cursor-not-allowed' :
              active === null
                ? 'bg-slate-700 text-slate-300 border border-slate-600'
                : 'bg-red-600 text-white shadow-xl shadow-red-900/60 scale-95'
            }`}
        >
          <Square size={24} />
          <span className="text-xs">Stop</span>
        </button>
        {/* Droite */}
        {btn('right', <ArrowRight size={28} />, 'Droite', { gridArea: '2 / 3' })}
        {/* Bas */}
        {btn('backward', <ArrowDown size={28} />, 'Arrière', { gridArea: '3 / 2' })}
      </div>

      {/* Vitesse */}
      <div className="w-full mt-4 px-2">
        <div className="flex justify-between text-xs text-slate-400 mb-1.5">
          <span>Vitesse</span>
          <span className="text-blue-400 font-medium">{Math.round(speed * 200)} %</span>
        </div>
        <div className="relative h-2 bg-slate-800 rounded-full">
          <div className="absolute left-0 top-0 h-full bg-blue-600 rounded-full transition-all" style={{ width: `${speed * 200}%` }} />
        </div>
      </div>
    </div>
  )
}

function MobileJoystick({
  onMove, onStop, onAction, connected, label, accent = 'blue', actionLabel = 'Stop', invertY = false, size = 160,
}: {
  onMove: (dir: Direction) => void
  onStop: () => void
  onAction?: () => void
  connected: boolean
  label: string
  accent?: 'blue' | 'amber'
  actionLabel?: string
  invertY?: boolean
  size?: number
}) {
  const baseRef = useRef<HTMLDivElement | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const onMoveRef = useRef(onMove)
  const onStopRef = useRef(onStop)
  const [stick, setStick] = useState({ x: 0, y: 0 })
  const [active, setActive] = useState<Direction | null>(null)

  useEffect(() => { onMoveRef.current = onMove }, [onMove])
  useEffect(() => { onStopRef.current = onStop }, [onStop])

  const stop = useCallback(() => {
    setStick({ x: 0, y: 0 })
    setActive(null)
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    onStopRef.current()
  }, [])

  const startDirection = useCallback((dir: Direction) => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
    }
    setActive(dir)
    onMoveRef.current(dir)
    intervalRef.current = setInterval(() => onMoveRef.current(dir), 150)
  }, [])

  const updateFromPointer = useCallback((clientX: number, clientY: number) => {
    const base = baseRef.current
    if (!base || !connected) return

    const rect = base.getBoundingClientRect()
    const radius = rect.width / 2
    const centerX = rect.left + radius
    const centerY = rect.top + radius
    const rawX = clientX - centerX
    const rawY = clientY - centerY
    const distance = Math.hypot(rawX, rawY)
    const maxOffset = radius * 0.55
    const ratio = distance > maxOffset ? maxOffset / distance : 1
    const x = rawX * ratio
    const y = rawY * ratio

    setStick({ x, y })

    if (distance < radius * 0.25) {
      stop()
      return
    }

    const dir: Direction =
      Math.abs(rawX) > Math.abs(rawY)
        ? (rawX > 0 ? 'right' : 'left')
        : (rawY > 0 ? (invertY ? 'forward' : 'backward') : (invertY ? 'backward' : 'forward'))

    if (dir !== active) {
      startDirection(dir)
    }
  }, [active, connected, startDirection, stop])

  useEffect(() => () => {
    if (intervalRef.current) clearInterval(intervalRef.current)
  }, [])

  return (
    <div className="flex flex-col items-center gap-4">
      <p className="text-xs text-slate-500 text-center">{label}</p>
      <div
        ref={baseRef}
        onPointerDown={(e) => {
          if (!connected) return
          e.currentTarget.setPointerCapture(e.pointerId)
          updateFromPointer(e.clientX, e.clientY)
        }}
        onPointerMove={(e) => {
          if (e.buttons === 0) return
          updateFromPointer(e.clientX, e.clientY)
        }}
        onPointerUp={stop}
        onPointerCancel={stop}
        style={{ width: size, height: size }}
        className={`relative rounded-full border ${
          connected
            ? accent === 'blue'
              ? 'border-blue-500/40 bg-slate-900/80'
              : 'border-amber-500/40 bg-slate-900/80'
            : 'border-slate-800 bg-slate-900/40'
        } touch-none select-none overflow-hidden`}
      >
        <div className="absolute inset-5 rounded-full border border-slate-800" />
        <div className="absolute inset-1/2 h-px -translate-x-1/2 w-[70%] bg-slate-800" />
        <div className="absolute inset-1/2 w-px -translate-y-1/2 h-[70%] bg-slate-800" />
        <div
          className={`absolute left-1/2 top-1/2 w-14 h-14 -translate-x-1/2 -translate-y-1/2 rounded-full border ${
            connected
              ? active
                ? accent === 'blue'
                  ? 'bg-blue-600 border-blue-400 shadow-lg shadow-blue-900/50'
                  : 'bg-amber-500 border-amber-400 shadow-lg shadow-amber-900/40 text-slate-950'
                : 'bg-slate-800 border-slate-700'
              : 'bg-slate-800/50 border-slate-800'
          }`}
          style={{ transform: `translate(calc(-50% + ${stick.x}px), calc(-50% + ${stick.y}px))` }}
        />
      </div>
      <button
        onClick={onAction ?? stop}
        disabled={!connected}
        className="px-5 py-2 rounded-lg bg-red-600/15 text-red-400 border border-red-600/40 disabled:opacity-40"
      >
        {actionLabel}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pan-Tilt
// ---------------------------------------------------------------------------

function PanTiltControl({
  pan, tilt, onPanTilt, connected,
}: {
  pan: number; tilt: number
  onPanTilt: (pan: number, tilt: number) => void
  connected: boolean
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <Camera size={14} className="text-slate-400" />
        <span className="text-sm font-medium text-slate-300">Caméra Pan-Tilt</span>
        <span className="ml-auto text-xs text-slate-500 font-mono">{pan.toFixed(0)}° / {tilt.toFixed(0)}°</span>
      </div>

      <div>
        <div className="flex justify-between text-xs text-slate-500 mb-1.5">
          <span>Pan (gauche ↔ droite)</span>
        </div>
        <input
          type="range" min="-90" max="90" step="2" value={pan}
          onChange={e => onPanTilt(Number(e.target.value), tilt)}
          disabled={!connected}
          className="w-full accent-blue-500 disabled:opacity-40"
        />
        <div className="flex justify-between text-xs text-slate-600 mt-1"><span>-90°</span><span>0°</span><span>90°</span></div>
      </div>

      <div>
        <div className="flex justify-between text-xs text-slate-500 mb-1.5">
          <span>Tilt (bas ↕ haut)</span>
        </div>
        <input
          type="range" min="-45" max="60" step="2" value={tilt}
          onChange={e => onPanTilt(pan, Number(e.target.value))}
          disabled={!connected}
          className="w-full accent-blue-500 disabled:opacity-40"
        />
        <div className="flex justify-between text-xs text-slate-600 mt-1"><span>-45°</span><span>0°</span><span>60°</span></div>
      </div>

      <button
        onClick={() => onPanTilt(0, 0)}
        disabled={!connected}
        className="w-full py-2 rounded-lg text-xs font-medium text-slate-400 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 transition-colors"
      >
        Recentrer caméra
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Joystick de déplacement avec mode Conducteur / Miroir
// ---------------------------------------------------------------------------

type DriveMode = 'driver' | 'mirror'
const DRIVE_MODE_KEY = 'sentryx_drive_mode'

function LidarScanPanel({
  connected,
  points = [],
  frontCm,
  leftCm,
  rightCm,
  obstacle,
  error,
  autoActive,
  mode,
}: {
  connected?: boolean
  points?: Array<{ angle: number; distance_cm: number }>
  frontCm?: number | null
  leftCm?: number | null
  rightCm?: number | null
  obstacle?: boolean
  error?: string | null
  autoActive?: boolean
  mode?: string
}) {
  const maxCm = 250
  const plot = points
    .filter(p => Math.abs(p.angle) <= 90 || p.angle >= 270)
    .slice(0, 140)
    .map((p, i) => {
      const angle = p.angle > 180 ? p.angle - 360 : p.angle
      const distanceRatio = Math.min(p.distance_cm, maxCm) / maxCm
      const x = 50 + Math.sin((angle * Math.PI) / 180) * distanceRatio * 44
      const y = 92 - Math.cos((angle * Math.PI) / 180) * distanceRatio * 82
      return <circle key={`${p.angle}-${i}`} cx={x} cy={y} r="0.9" className={obstacle ? 'fill-red-300' : 'fill-cyan-300'} />
    })

  return (
    <div className={`mx-5 mb-4 rounded-xl border px-4 py-3 ${
      connected
        ? obstacle ? 'border-red-500/60 bg-red-950/30' : 'border-cyan-500/30 bg-slate-800/40'
        : 'border-slate-700 bg-slate-800/30'
    }`}>
      <div className="flex items-center gap-2 mb-3">
        <Radar size={14} className={connected ? (obstacle ? 'text-red-400' : 'text-cyan-300') : 'text-slate-500'} />
        <span className="text-sm font-medium text-slate-300">LIDAR</span>
        <span className={`ml-auto text-[11px] font-mono ${connected ? 'text-emerald-400' : 'text-amber-400'}`}>
          {connected ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>

      <div className="grid grid-cols-[120px_1fr] gap-3 items-center">
        <svg viewBox="0 0 100 100" className="w-[120px] h-[120px] rounded-lg bg-slate-950 border border-slate-800">
          <path d="M 6 92 A 44 82 0 0 1 94 92" fill="none" className="stroke-slate-800" strokeWidth="1" />
          <path d="M 22 92 A 28 52 0 0 1 78 92" fill="none" className="stroke-slate-800" strokeWidth="1" />
          <line x1="50" y1="92" x2="50" y2="8" className="stroke-slate-700" strokeWidth="0.8" />
          <line x1="50" y1="92" x2="12" y2="26" className="stroke-slate-800" strokeWidth="0.8" />
          <line x1="50" y1="92" x2="88" y2="26" className="stroke-slate-800" strokeWidth="0.8" />
          {plot}
          <circle cx="50" cy="92" r="3" className="fill-blue-500" />
        </svg>

        <div className="space-y-2 min-w-0">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Avant</span>
            <span className={`font-mono font-medium ${obstacle ? 'text-red-400' : 'text-emerald-400'}`}>
              {frontCm != null ? `${frontCm.toFixed(0)} cm` : '--'}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Gauche / droite</span>
            <span className="text-cyan-300 font-mono">
              {leftCm != null ? leftCm.toFixed(0) : '--'} / {rightCm != null ? rightCm.toFixed(0) : '--'} cm
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">AUTO</span>
            <span className={autoActive ? 'text-blue-300 font-medium' : 'text-slate-500'}>
              {autoActive ? 'actif' : 'inactif'}{mode ? ` · ${mode}` : ''}
            </span>
          </div>
          {!connected && <p className="text-xs text-amber-400">{error ?? 'LIDAR non connecté'}</p>}
        </div>
      </div>
    </div>
  )
}

function DriveJoystick({
  onMoveXY, onStop, connected, mode, onModeChange, size = 160,
}: {
  onMoveXY: (x: number, y: number) => void
  onStop: () => void
  connected: boolean
  mode: DriveMode
  onModeChange: (m: DriveMode) => void
  size?: number
}) {
  const baseRef = useRef<HTMLDivElement | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const xyRef = useRef({ x: 0, y: 0 })
  const onMoveXYRef = useRef(onMoveXY)
  const onStopRef = useRef(onStop)
  const [stick, setStick] = useState({ x: 0, y: 0 })
  const [active, setActive] = useState(false)

  useEffect(() => { onMoveXYRef.current = onMoveXY }, [onMoveXY])
  useEffect(() => { onStopRef.current = onStop }, [onStop])

  const stop = useCallback(() => {
    setStick({ x: 0, y: 0 })
    setActive(false)
    xyRef.current = { x: 0, y: 0 }
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    onStopRef.current()
  }, [])

  const updateFromPointer = useCallback((clientX: number, clientY: number) => {
    const base = baseRef.current
    if (!base || !connected) return
    const rect = base.getBoundingClientRect()
    const radius = rect.width / 2
    const rawX = clientX - (rect.left + radius)
    const rawY = clientY - (rect.top + radius)
    const distance = Math.hypot(rawX, rawY)
    const maxOffset = radius * 0.55
    const ratio = distance > maxOffset ? maxOffset / distance : 1
    const sx = rawX * ratio
    const sy = rawY * ratio
    setStick({ x: sx, y: sy })

    if (distance < radius * 0.15) { stop(); return }

    const nx = rawX / radius
    const ny = rawY / radius
    xyRef.current = { x: nx, y: -ny }

    if (!intervalRef.current) {
      setActive(true)
      onMoveXYRef.current(nx, -ny)
      intervalRef.current = setInterval(() => {
        const { x, y } = xyRef.current
        onMoveXYRef.current(x, y)
      }, 80)
    }
  }, [connected, stop])

  useEffect(() => () => { if (intervalRef.current) clearInterval(intervalRef.current) }, [])

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-0.5">
        {(['driver', 'mirror'] as DriveMode[]).map(m => (
          <button
            key={m}
            onClick={() => onModeChange(m)}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              mode === m
                ? 'bg-blue-600 text-white'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {m === 'driver' ? '🎮 Conducteur' : '🪞 Miroir'}
          </button>
        ))}
      </div>
      <div
        ref={baseRef}
        onPointerDown={e => {
          if (!connected) return
          e.currentTarget.setPointerCapture(e.pointerId)
          updateFromPointer(e.clientX, e.clientY)
        }}
        onPointerMove={e => { if (e.buttons === 0) return; updateFromPointer(e.clientX, e.clientY) }}
        onPointerUp={stop}
        onPointerCancel={stop}
        style={{ width: size, height: size }}
        className={`relative rounded-full border ${
          connected
            ? 'border-blue-500/40 bg-slate-900/80'
            : 'border-slate-800 bg-slate-900/40'
        } touch-none select-none overflow-hidden`}
      >
        <div className="absolute inset-5 rounded-full border border-slate-800" />
        <div className="absolute inset-1/2 h-px -translate-x-1/2 w-[70%] bg-slate-800" />
        <div className="absolute inset-1/2 w-px -translate-y-1/2 h-[70%] bg-slate-800" />
        <div
          className={`absolute left-1/2 top-1/2 w-14 h-14 -translate-x-1/2 -translate-y-1/2 rounded-full border ${
            connected
              ? active ? 'bg-blue-600 border-blue-400 shadow-lg shadow-blue-900/50' : 'bg-slate-800 border-slate-700'
              : 'bg-slate-800/50 border-slate-800'
          }`}
          style={{ transform: `translate(calc(-50% + ${stick.x}px), calc(-50% + ${stick.y}px))` }}
        />
      </div>
      <button onClick={stop} disabled={!connected} className="px-5 py-2 rounded-lg bg-red-600/15 text-red-400 border border-red-600/40 disabled:opacity-40 text-xs">
        Stop
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page principale
// ---------------------------------------------------------------------------

export default function Pilotage() {
  const conn = useSharedRobotConnection()
  const media = useMedia(conn.robotIp)
  const [photoLoading, setPhotoLoading] = useState(false)
  const [videoLoading, setVideoLoading] = useState(false)
  const [speed, setSpeed] = useState(0.35)
  const [pan, setPan] = useState(0)
  const [tilt, setTilt] = useState(0)
  const [emergency, setEmergency] = useState(false)
  const [driveMode, setDriveMode] = useState<DriveMode>(
    () => (localStorage.getItem(DRIVE_MODE_KEY) as DriveMode) ?? 'driver'
  )
  const [alertActive, setAlertActive] = useState(false)
  const [alertError, setAlertError] = useState<string | null>(null)
  const alertTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const streamRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [cameraLight, setCameraLight] = useState(false)
  const [isMobileLandscape, setIsMobileLandscape] = useState(false)

  const patrolActive = conn.lastStatus?.patrol_active ?? false
  const trackingActive = conn.trackingActive
  const personDetected = conn.personDetected
  const robotConnected = conn.status === 'connected'
  const connected = robotConnected && !emergency && !patrolActive && (conn.lastStatus?.control_available ?? true)
  // L'alerte peut toujours être déclenchée si le robot est connecté (même en emergency)
  const canAlert = robotConnected
  const streamUrl = getRobotStreamUrl(conn.robotIp)

  useEffect(() => {
    setStreamUnavailable(false)
    setStreamKey(k => k + 1)
    if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
  }, [conn.robotIp, conn.status])

  useEffect(() => {
    setCameraLight(Boolean(conn.lastStatus?.camera_light))
  }, [conn.lastStatus?.camera_light])

  useEffect(() => {
    const updateViewportMode = () => {
      setIsMobileLandscape(window.innerWidth < 1024 && window.innerWidth > window.innerHeight)
    }

    updateViewportMode()
    window.addEventListener('resize', updateViewportMode)
    return () => window.removeEventListener('resize', updateViewportMode)
  }, [])

  const handleMove = useCallback((dir: Direction) => {
    conn.sendMove(dir, speed)
  }, [conn, speed])

  const handleMoveXY = useCallback((x: number, y: number) => {
    const s = speed / 0.5
    const mx = driveMode === 'mirror' ? -x : x
    const my = driveMode === 'mirror' ? -y : y
    conn.sendMoveXY(mx * s, my * s)
  }, [conn, speed, driveMode])

  const handleDriveMode = useCallback((m: DriveMode) => {
    setDriveMode(m)
    localStorage.setItem(DRIVE_MODE_KEY, m)
  }, [])

  const handleStop = useCallback(() => {
    conn.sendStop()
  }, [conn])

  const handlePanTilt = useCallback((p: number, t: number) => {
    setPan(p)
    setTilt(t)
    conn.sendPanTilt(p, t)
  }, [conn])

  const handleEmergency = useCallback(() => {
    setEmergency(true)
    conn.sendStop()
  }, [conn])

  const handleAlert = useCallback(() => {
    if (alertActive) {
      conn.stopAlert()
      setAlertActive(false)
      if (alertTimerRef.current) { clearTimeout(alertTimerRef.current); alertTimerRef.current = null }
    } else {
      setAlertError(null)
      conn.sendAlert((err) => {
        setAlertActive(false)
        setAlertError(err)
        if (alertTimerRef.current) { clearTimeout(alertTimerRef.current); alertTimerRef.current = null }
      })
      setAlertActive(true)
      alertTimerRef.current = setTimeout(() => setAlertActive(false), 3500)
    }
  }, [alertActive, conn])

  const handleCameraLightToggle = useCallback(() => {
    const next = !cameraLight
    setCameraLight(next)
    conn.sendLight(next)
  }, [cameraLight, conn])

  const handlePhoto = useCallback(async () => {
    setPhotoLoading(true)
    await media.takePhoto()
    setPhotoLoading(false)
  }, [media])

  const handleVideo = useCallback(async () => {
    setVideoLoading(true)
    if (media.isRecording) {
      await media.stopRecording()
    } else {
      await media.startRecording()
    }
    setVideoLoading(false)
  }, [media])

  const handlePanTiltNudge = useCallback((dir: Direction) => {
    const nextPan =
      dir === 'left' ? pan - 15 :
      dir === 'right' ? pan + 15 :
      pan
    const nextTilt =
      dir === 'forward' ? tilt + 10 :
      dir === 'backward' ? tilt - 10 :
      tilt

    setPan(nextPan)
    setTilt(nextTilt)
    conn.sendPanTilt(nextPan, nextTilt)
  }, [conn, pan, tilt])

  return (
    <div className={`flex flex-col min-h-full ${isMobileLandscape ? 'h-[100dvh] m-0' : '-m-3 sm:-m-4 lg:-m-6'}`} style={{ background: '#070d1a' }}>
      {/* Main layout */}
      <div className="flex flex-col xl:flex-row flex-1 overflow-hidden">

        {/* Left — camera feed */}
        <div className="flex-1 flex flex-col xl:border-r border-slate-800 min-w-0 min-h-[42vh] xl:min-h-0">
          <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-800">
            <span className="text-sm font-medium text-slate-300">Flux caméra</span>
            <div className="flex items-center gap-2">
              {conn.status === 'connected' && (
                <>
                  <button
                    onClick={handlePhoto}
                    disabled={photoLoading || media.isRecording}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium
                      bg-blue-600/15 text-blue-300 border border-blue-500/30
                      hover:bg-blue-600/25 hover:border-blue-400/50
                      disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                  >
                    {photoLoading ? <Loader2 size={11} className="animate-spin" /> : <Image size={11} />}
                    Photo
                  </button>
                  <button
                    onClick={handleVideo}
                    disabled={videoLoading}
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium
                      border transition-all disabled:opacity-40 disabled:cursor-not-allowed
                      ${media.isRecording
                        ? 'bg-red-600/20 text-red-300 border-red-500/40 hover:bg-red-600/30'
                        : 'bg-emerald-600/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/25'
                      }`}
                  >
                    {videoLoading
                      ? <Loader2 size={11} className="animate-spin" />
                      : media.isRecording ? <VideoOff size={11} /> : <Video size={11} />
                    }
                    {media.isRecording ? 'Stop' : 'Vidéo'}
                  </button>
                  {media.isRecording && (
                    <div className="flex items-center gap-1">
                      <Circle size={6} className="text-red-500 fill-red-500 animate-pulse" />
                      <span className="text-xs text-red-400 font-bold">REC</span>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5 ml-1 pl-2 border-l border-slate-700">
                    <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                    <span className="text-xs text-red-400">EN DIRECT</span>
                  </div>
                </>
              )}
            </div>
          </div>
          <div
            className={`flex-1 flex items-center justify-center relative sticky top-0 z-10 xl:static ${isMobileLandscape ? 'min-h-[100dvh]' : 'min-h-[42vh] md:min-h-[50vh] xl:min-h-0'}`}
            style={{ background: '#040810' }}
          >
            {/* Grille sci-fi */}
            <svg className="absolute inset-0 w-full h-full opacity-5 pointer-events-none">
              <defs>
                <pattern id="pgrid" width="50" height="50" patternUnits="userSpaceOnUse">
                  <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#3b82f6" strokeWidth="0.5" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#pgrid)" />
            </svg>
            {/* Scan lines */}
            <div className="absolute inset-0 pointer-events-none opacity-[0.03]"
              style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 3px, #3b82f6 3px, #3b82f6 4px)' }} />

            {/* Corner brackets */}
            {['top-4 left-4 border-t-2 border-l-2 rounded-tl', 'top-4 right-4 border-t-2 border-r-2 rounded-tr',
              'bottom-4 left-4 border-b-2 border-l-2 rounded-bl', 'bottom-4 right-4 border-b-2 border-r-2 rounded-br'].map((cls, i) => (
              <div key={i} className={`absolute w-8 h-8 border-blue-500/40 ${cls}`} />
            ))}

            {robotConnected && (
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

            {(!connected || streamUnavailable) && (
              <div className="text-center z-10 px-6">
                {streamUnavailable ? (
                  <CameraOff size={48} className="mx-auto mb-3 text-slate-700" />
                ) : (
                  <Camera size={48} className="mx-auto mb-3 text-slate-700" />
                )}
                <p className="text-slate-600 text-sm">
                  {!robotConnected
                    ? 'Connecte-toi au robot pour voir le flux'
                    : 'Flux caméra indisponible'}
                </p>
              </div>
            )}

            {/* Tracking active overlay */}
            {trackingActive && (
              <div className={`absolute top-4 right-4 z-30 flex items-center gap-2 rounded-xl px-3 py-1.5 backdrop-blur-sm border ${
                personDetected
                  ? 'bg-emerald-900/80 border-emerald-500/60 text-emerald-200'
                  : 'bg-slate-900/80 border-slate-600/60 text-slate-300'
              }`}>
                <Crosshair size={13} className={personDetected ? 'text-emerald-400' : 'text-slate-400 animate-pulse'} />
                <span className="text-xs font-bold">
                  {personDetected ? 'PERSONNE DÉTECTÉE' : 'RECHERCHE…'}
                </span>
              </div>
            )}

            {/* Obstacle warning overlay */}
            {(conn.lastStatus?.obstacle || conn.lastStatus?.lidar_obstacle_front) && (
              <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 bg-red-900/90 border border-red-500 rounded-xl px-4 py-2 animate-pulse backdrop-blur-sm">
                <Radar size={16} className="text-red-400" />
                <span className="text-red-200 text-sm font-bold">
                  OBSTACLE — {(conn.lastStatus.lidar_front_cm ?? conn.lastStatus.distance_cm)?.toFixed(0)} cm
                </span>
              </div>
            )}

            {/* Obstacle blocked flash */}
            {conn.obstacleBlocked && (
              <div className="absolute top-16 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 bg-amber-900/90 border border-amber-500 rounded-xl px-4 py-2 backdrop-blur-sm">
                <Radar size={14} className="text-amber-300 animate-pulse" />
                <span className="text-amber-200 text-xs font-bold">AVANCE BLOQUÉE</span>
                <button
                  onClick={conn.clearObstacleBlock}
                  className="ml-1 rounded-lg border border-amber-400/50 bg-amber-500/20 px-2 py-1 text-[11px] font-bold text-amber-100 hover:bg-amber-500/30"
                >
                  Débloquer 5s
                </button>
              </div>
            )}

            {/* Pan/tilt overlay indicator */}
            {conn.status === 'connected' && (
              <div className="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm rounded-lg px-3 py-2 font-mono text-xs text-slate-300">
                PAN {pan > 0 ? '+' : ''}{pan}° · TILT {tilt > 0 ? '+' : ''}{tilt}°
                {conn.lastStatus?.distance_cm != null && (
                  <span className={`ml-3 ${conn.lastStatus.obstacle ? 'text-red-400' : (conn.lastStatus.distance_cm < 50 ? 'text-amber-400' : 'text-emerald-400')}`}>
                    · {conn.lastStatus.distance_cm.toFixed(0)} cm
                  </span>
                )}
              </div>
            )}
            {isMobileLandscape && (
              <>
                <div className="absolute left-3 bottom-3 z-20">
                  <DriveJoystick
                    onMoveXY={handleMoveXY}
                    onStop={handleStop}
                    connected={connected}
                    mode={driveMode}
                    onModeChange={handleDriveMode}
                    size={110}
                  />
                </div>
                <div className="absolute right-3 bottom-3 z-20">
                  <MobileJoystick
                    label="Caméra"
                    accent="amber"
                    onMove={handlePanTiltNudge}
                    onStop={() => {}}
                    onAction={() => handlePanTilt(0, 0)}
                    connected={connected}
                    actionLabel="Recentrer"
                    size={110}
                  />
                </div>
                {/* Alert button landscape */}
                <div className="absolute top-3 right-3 z-20">
                  <button
                    onClick={handleAlert}
                    disabled={!canAlert}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border font-bold text-xs transition-all active:scale-95 ${
                      !canAlert
                        ? 'opacity-30 cursor-not-allowed bg-slate-900 border-slate-700 text-slate-500'
                        : alertActive
                          ? 'bg-orange-500 text-white border-orange-400 animate-pulse shadow-lg shadow-orange-900/50'
                          : 'bg-black/60 text-orange-400 border-orange-600/50 backdrop-blur-sm hover:bg-orange-600/20'
                    }`}
                  >
                    <Siren size={14} />
                    {alertActive ? 'Stop alerte' : 'Alerte'}
                  </button>
                </div>
              </>
            )}
          </div>

          <div className={`${isMobileLandscape ? 'hidden' : 'md:hidden'} border-t border-slate-800 px-4 py-5`} style={{ background: '#0a0f1e' }}>
            <div className="grid grid-cols-2 gap-4">
              <DriveJoystick
                onMoveXY={handleMoveXY}
                onStop={handleStop}
                connected={connected}
                mode={driveMode}
                onModeChange={handleDriveMode}
              />
              <MobileJoystick
                label="Caméra"
                accent="amber"
                onMove={handlePanTiltNudge}
                onStop={() => {}}
                onAction={() => handlePanTilt(0, 0)}
                connected={connected}
                actionLabel="Recentrer"
              />
            </div>
          </div>
        </div>

        {/* Right — controls */}
        <div className={`${isMobileLandscape ? 'hidden' : 'flex'} w-full xl:w-96 flex-col overflow-y-auto`} style={{ background: '#0a0f1e' }}>

          {/* Emergency stop */}
          <div className="hidden md:block px-5 pt-5 pb-4 border-b border-slate-800">
            <button
              onClick={handleEmergency}
              className={`w-full py-4 rounded-xl font-bold text-base flex items-center justify-center gap-3 transition-all duration-150 ${
                emergency
                  ? 'bg-red-700 text-white shadow-2xl shadow-red-900/50 cursor-default'
                  : 'bg-red-600/15 text-red-400 border-2 border-red-600/50 hover:bg-red-600 hover:text-white hover:border-red-600 hover:shadow-xl hover:shadow-red-900/40'
              }`}
            >
              <AlertOctagon size={22} />
              {emergency ? '⚠ ARRÊT D\'URGENCE ACTIF' : 'Arrêt d\'urgence'}
            </button>
            {emergency && (
              <button
                onClick={() => setEmergency(false)}
                className="w-full mt-2 py-2 rounded-lg text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                Réinitialiser
              </button>
            )}
          </div>

          {/* Speed slider */}
          <div className="hidden md:block px-5 py-4 border-b border-slate-800">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-slate-400">Vitesse maximale</span>
              <span className="text-blue-400 font-medium">{Math.round(speed * 200)} %</span>
            </div>
            <input
              type="range" min="0.1" max="0.5" step="0.05" value={speed}
              onChange={e => setSpeed(Number(e.target.value))}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-slate-600 mt-1">
              <span>Lent</span><span>Rapide</span>
            </div>
          </div>

          {/* D-pad */}
          <div className="hidden md:flex px-5 py-6 border-b border-slate-800 justify-center">
            <div className="hidden md:block">
              <Dpad onMove={handleMove} onStop={handleStop} speed={speed} connected={connected} />
            </div>
          </div>

          {/* Pan-Tilt */}
          <div className="hidden md:block px-5 py-5 border-b border-slate-800">
            <PanTiltControl pan={pan} tilt={tilt} onPanTilt={handlePanTilt} connected={connected} />
          </div>

          <div className="px-5 py-5 border-b border-slate-800">
            <button
              onClick={handleCameraLightToggle}
              disabled={!connected}
              className={`w-full py-3 rounded-xl border transition-colors flex items-center justify-center gap-3 ${
                !connected
                  ? 'bg-slate-800/40 text-slate-700 border-slate-800 cursor-not-allowed'
                  : cameraLight
                    ? 'bg-amber-500 text-slate-950 border-amber-400 shadow-lg shadow-amber-900/30'
                    : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
              }`}
            >
              <Lightbulb size={18} />
              <span className="text-sm font-medium">
                {cameraLight ? 'Lampe caméra allumée' : 'Allumer la lampe caméra'}
              </span>
            </button>
          </div>

          {/* Tracking */}
          <div className="px-5 py-4 border-b border-slate-800">
            <button
              onClick={() => trackingActive ? conn.stopTracking() : conn.startTracking()}
              disabled={conn.status !== 'connected' || patrolActive}
              className={`w-full py-3 rounded-xl border-2 transition-all duration-150 flex items-center justify-center gap-3 font-bold active:scale-95 ${
                conn.status !== 'connected' || patrolActive
                  ? 'bg-slate-800/40 text-slate-700 border-slate-800 cursor-not-allowed'
                  : trackingActive
                    ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/60 hover:bg-emerald-600/30'
                    : 'bg-slate-800/60 text-slate-300 border-slate-600/60 hover:bg-slate-700'
              }`}
            >
              <Crosshair size={18} />
              <span className="text-sm">{trackingActive ? 'Tracking actif — Arrêter' : 'Mode tracking humain'}</span>
            </button>
            {trackingActive && (
              <p className={`mt-2 text-xs rounded-lg px-3 py-2 border ${
                personDetected
                  ? 'text-emerald-400 bg-emerald-900/20 border-emerald-700/40'
                  : 'text-amber-400 bg-amber-900/20 border-amber-700/40 animate-pulse'
              }`}>
                {personDetected ? '✓ Personne détectée — caméra en suivi automatique' : 'Recherche d\'une personne…'}
              </p>
            )}
          </div>

          {/* Alert button */}
          <div className="px-5 py-4 border-b border-slate-800">
            <button
              onClick={handleAlert}
              disabled={!canAlert}
              className={`w-full py-3 rounded-xl border-2 transition-all duration-150 flex items-center justify-center gap-3 font-bold active:scale-95 ${
                !canAlert
                  ? 'bg-slate-800/40 text-slate-700 border-slate-800 cursor-not-allowed'
                  : alertActive
                    ? 'bg-orange-500 text-white border-orange-400 shadow-lg shadow-orange-900/40 animate-pulse'
                    : 'bg-orange-600/10 text-orange-400 border-orange-600/40 hover:bg-orange-600/20 hover:border-orange-500'
              }`}
            >
              <Siren size={18} />
              <span className="text-sm">{alertActive ? 'Alerte en cours — Arrêter' : 'Déclencher une alerte'}</span>
            </button>
            {alertError && (
              <p className="mt-2 text-xs text-red-400 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
                ⚠ Audio : {alertError}
              </p>
            )}
          </div>

          {/* Obstacle blocked warning */}
          {conn.obstacleBlocked && (
            <div className="px-5 pt-4">
              <div className="rounded-lg border border-amber-700/40 bg-amber-900/20 px-3 py-2">
                <p className="text-xs text-amber-400 animate-pulse">
                  ⚠ Obstacle détecté — avance bloquée
                </p>
                <button
                  onClick={conn.clearObstacleBlock}
                  className="mt-2 w-full rounded-lg border border-amber-500/40 bg-amber-500/15 py-2 text-xs font-bold text-amber-200 hover:bg-amber-500/25"
                >
                  Débloquer le pilotage pendant 5s
                </button>
              </div>
            </div>
          )}

          {/* Patrol active warning */}
          {patrolActive && (
            <div className="px-5 pt-4">
              <p className="text-xs text-blue-400 bg-blue-900/20 border border-blue-700/40 rounded-lg px-3 py-2">
                🤖 Patrouille active — contrôle manuel désactivé. Gérez la patrouille depuis la page <strong>Patrouilles</strong>.
              </p>
            </div>
          )}

          <LidarScanPanel
            connected={Boolean(conn.lastScan?.connected)}
            points={conn.lastScan?.points?.map(p => ({ angle: p.angle_deg, distance_cm: p.distance_cm }))}
            frontCm={conn.lastStatus?.lidar_front_cm}
            leftCm={conn.lastStatus?.lidar_left_cm}
            rightCm={conn.lastStatus?.lidar_right_cm}
            obstacle={Boolean(conn.lastStatus?.lidar_obstacle_front)}
            error={conn.lastScan?.error}
            autoActive={patrolActive}
            mode={conn.lastStatus?.navigation_mode}
          />

          {/* Distance sensor */}
          {conn.lastStatus?.distance_cm !== undefined && (
            <div className={`mx-5 mb-4 rounded-xl border px-4 py-3 transition-colors ${
              conn.lastStatus.obstacle
                ? 'border-red-500/60 bg-red-950/40'
                : (conn.lastStatus.distance_cm ?? 999) < 50
                  ? 'border-amber-500/40 bg-amber-950/30'
                  : 'border-slate-700 bg-slate-800/40'
            }`}>
              <div className="flex items-center gap-2 mb-2">
                <Radar size={14} className={conn.lastStatus.obstacle ? 'text-red-400' : 'text-slate-400'} />
                <span className="text-sm font-medium text-slate-300">Détection obstacle</span>
              </div>
              {conn.lastStatus.distance_cm !== null ? (
                <>
                  <div className="flex items-end gap-1.5">
                    <span className={`text-3xl font-bold font-mono ${
                      conn.lastStatus.obstacle ? 'text-red-400' :
                      (conn.lastStatus.distance_cm ?? 999) < 50 ? 'text-amber-400' : 'text-emerald-400'
                    }`}>
                      {conn.lastStatus.distance_cm?.toFixed(0)}
                    </span>
                    <span className="text-slate-500 text-sm mb-1">cm</span>
                  </div>
                  {conn.lastStatus.obstacle && (
                    <p className="text-xs font-bold text-red-400 mt-1 animate-pulse">⚠ OBSTACLE DÉTECTÉ</p>
                  )}
                </>
              ) : (
                <p className="text-xs text-slate-500">{conn.lastStatus.sensor_error ?? 'Hors portée'}</p>
              )}
            </div>
          )}

          {/* Robot status */}
          {conn.lastStatus && (
            <div className="px-5 py-4">
              <div className="flex items-center gap-2 mb-3">
                <Activity size={14} className="text-slate-400" />
                <span className="text-sm font-medium text-slate-300">Données robot</span>
              </div>
              <div className="space-y-2">
                {conn.lastStatus.voltage !== undefined && (
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">Batterie</span>
                    <span className={`font-medium ${
                      (conn.lastStatus.battery ?? 100) < 20 ? 'text-red-400' :
                      (conn.lastStatus.battery ?? 100) < 40 ? 'text-amber-400' :
                      'text-emerald-400'
                    }`}>
                      {conn.lastStatus.voltage.toFixed(1)} V
                      {conn.lastStatus.battery !== undefined && ` · ${conn.lastStatus.battery}%`}
                    </span>
                  </div>
                )}
                {conn.lastStatus.speed_l !== undefined && (
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">Vitesse L / R</span>
                    <span className="text-blue-400 font-mono">{conn.lastStatus.speed_l?.toFixed(2)} / {conn.lastStatus.speed_r?.toFixed(2)}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Hint connexion */}
          {conn.status === 'disconnected' && (
            <div className="px-5 py-6 text-center text-slate-600 text-sm">
              <Wifi size={32} className="mx-auto mb-2 opacity-30" />
              <p>Configure l'IP de ta Pi et connecte-toi</p>
              <p className="text-xs mt-1 text-slate-700">Entre l'IP ou l'URL du tunnel</p>
            </div>
          )}

          <div className="md:hidden mt-auto border-t border-slate-800">
            <div className="px-5 py-4 border-b border-slate-800">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-400">Vitesse maximale</span>
                <span className="text-blue-400 font-medium">{Math.round(speed * 200)} %</span>
              </div>
              <input
                type="range" min="0.1" max="0.5" step="0.05" value={speed}
                onChange={e => setSpeed(Number(e.target.value))}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-600 mt-1">
                <span>Lent</span><span>Rapide</span>
              </div>
            </div>

            <div className="px-5 pt-5 pb-4">
              <button
                onClick={handleEmergency}
                className={`w-full py-4 rounded-xl font-bold text-base flex items-center justify-center gap-3 transition-all duration-150 ${
                  emergency
                    ? 'bg-red-700 text-white shadow-2xl shadow-red-900/50 cursor-default'
                    : 'bg-red-600/15 text-red-400 border-2 border-red-600/50 hover:bg-red-600 hover:text-white hover:border-red-600 hover:shadow-xl hover:shadow-red-900/40'
                }`}
              >
                <AlertOctagon size={22} />
                {emergency ? '⚠ ARRÊT D\'URGENCE ACTIF' : 'Arrêt d\'urgence'}
              </button>
              {emergency && (
                <button
                  onClick={() => setEmergency(false)}
                  className="w-full mt-2 py-2 rounded-lg text-xs text-slate-500 hover:text-slate-300 transition-colors"
                >
                  Réinitialiser
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}









