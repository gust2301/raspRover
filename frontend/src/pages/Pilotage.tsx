import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Wifi, WifiOff, AlertOctagon, ArrowUp, ArrowDown, ArrowLeft, ArrowRight,
  Square, Camera, CameraOff, Settings2, Activity, Lightbulb,
} from 'lucide-react'
import { type ConnectionStatus } from '../hooks/useRobotConnection'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'

// ---------------------------------------------------------------------------
// Connection bar
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<ConnectionStatus, { dot: string; label: string; text: string }> = {
  disconnected: { dot: 'bg-slate-500', label: 'Déconnecté', text: 'text-slate-400' },
  connecting:   { dot: 'bg-amber-400 animate-pulse', label: 'Connexion…', text: 'text-amber-400' },
  connected:    { dot: 'bg-emerald-400 animate-pulse', label: 'Connecté', text: 'text-emerald-400' },
  error:        { dot: 'bg-red-500', label: 'Erreur', text: 'text-red-400' },
}

function ConnectionBar({
  status, robotIp, setRobotIp, connect, disconnect, latencyMs, errorMessage,
}: {
  status: ConnectionStatus
  robotIp: string
  setRobotIp: (ip: string) => void
  connect: () => void
  disconnect: () => void
  latencyMs: number | null
  errorMessage: string | null
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(robotIp)
  const s = STATUS_STYLES[status]

  const save = () => {
    setRobotIp(draft)
    setEditing(false)
  }

  return (
    <div className="relative z-20 flex flex-wrap items-center gap-3 px-4 sm:px-5 py-3 border-b border-slate-800" style={{ background: '#0a0f1e' }}>
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
  onMove, onStop, onAction, connected, label, accent = 'blue', actionLabel = 'Stop', invertY = false,
}: {
  onMove: (dir: Direction) => void
  onStop: () => void
  onAction?: () => void
  connected: boolean
  label: string
  accent?: 'blue' | 'amber'
  actionLabel?: string
  invertY?: boolean
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
        className={`relative w-40 h-40 rounded-full border ${
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

function DriveJoystick({
  onMoveXY, onStop, connected, mode, onModeChange,
}: {
  onMoveXY: (x: number, y: number) => void
  onStop: () => void
  connected: boolean
  mode: DriveMode
  onModeChange: (m: DriveMode) => void
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
        className={`relative w-40 h-40 rounded-full border ${
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
  const [speed, setSpeed] = useState(0.35)
  const [pan, setPan] = useState(0)
  const [tilt, setTilt] = useState(0)
  const [emergency, setEmergency] = useState(false)
  const [driveMode, setDriveMode] = useState<DriveMode>(
    () => (localStorage.getItem(DRIVE_MODE_KEY) as DriveMode) ?? 'driver'
  )
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const streamRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [cameraLight, setCameraLight] = useState(false)
  const [isMobileLandscape, setIsMobileLandscape] = useState(false)

  const connected = conn.status === 'connected' && !emergency
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
    conn.sendMoveXY(x * s, y * s)
  }, [conn, speed])

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

  const handleCameraLightToggle = useCallback(() => {
    const next = !cameraLight
    setCameraLight(next)
    conn.sendLight(next)
  }, [cameraLight, conn])

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
      {/* Connection bar */}
      {!isMobileLandscape && (
        <ConnectionBar
          status={conn.status}
          robotIp={conn.robotIp}
          setRobotIp={conn.setRobotIp}
          connect={conn.connect}
          disconnect={conn.disconnect}
          latencyMs={conn.latencyMs}
          errorMessage={conn.errorMessage}
        />
      )}

      {/* Main layout */}
      <div className="flex flex-col xl:flex-row flex-1 overflow-hidden">

        {/* Left — camera feed */}
        <div className="flex-1 flex flex-col xl:border-r border-slate-800 min-w-0 min-h-[42vh] xl:min-h-0">
          <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-800">
            <span className="text-sm font-medium text-slate-300">Flux caméra</span>
            {conn.status === 'connected' && (
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                <span className="text-xs text-red-400">EN DIRECT</span>
              </div>
            )}
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

            {connected && (
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
                  {!connected
                    ? 'Connecte-toi au robot pour voir le flux'
                    : 'Flux caméra indisponible'}
                </p>
              </div>
            )}

            {/* Pan/tilt overlay indicator */}
            {conn.status === 'connected' && (
              <div className="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm rounded-lg px-3 py-2 font-mono text-xs text-slate-300">
                PAN {pan > 0 ? '+' : ''}{pan}° · TILT {tilt > 0 ? '+' : ''}{tilt}°
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
                  />
                </div>
                <div className="absolute right-3 bottom-3 z-20">
                  <MobileJoystick
                    label="Cam�ra"
                    accent="amber"
                    onMove={handlePanTiltNudge}
                    onStop={() => {}}
                    onAction={() => handlePanTilt(0, 0)}
                    connected={connected}
                    actionLabel="Recentrer"
                  />
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

          {/* Robot status */}
          {conn.lastStatus && (
            <div className="px-5 py-4">
              <div className="flex items-center gap-2 mb-3">
                <Activity size={14} className="text-slate-400" />
                <span className="text-sm font-medium text-slate-300">Données robot</span>
              </div>
              <div className="space-y-2">
                {conn.lastStatus.battery !== undefined && (
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">Batterie</span>
                    <span className="text-emerald-400 font-medium">{conn.lastStatus.battery} V</span>
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













