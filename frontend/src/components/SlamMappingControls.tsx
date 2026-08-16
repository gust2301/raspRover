import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, Square } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'

type Direction = 'forward' | 'backward' | 'left' | 'right'

const KEY_DIRECTIONS: Record<string, Direction> = {
  ArrowUp: 'forward', w: 'forward', W: 'forward',
  ArrowDown: 'backward', s: 'backward', S: 'backward',
  ArrowLeft: 'left', a: 'left', A: 'left',
  ArrowRight: 'right', d: 'right', D: 'right',
}

export default function SlamMappingControls() {
  const connection = useSharedRobotConnection()
  const [speed, setSpeed] = useState(0.3)
  const [active, setActive] = useState<Direction | null>(null)
  const repeatRef = useRef<ReturnType<typeof window.setInterval> | null>(null)
  const activeRef = useRef<Direction | null>(null)
  const streamUrl = getRobotStreamUrl(connection.robotIp)
  const connected = connection.status === 'connected'

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
    if (!connected || activeRef.current === direction) return
    stop()
    activeRef.current = direction
    setActive(direction)
    connection.sendMove(direction, speed)
    repeatRef.current = window.setInterval(
      () => connection.sendMove(direction, speed),
      150,
    )
  }, [connected, connection, speed, stop])

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

  const driveButton = (
    direction: Direction,
    label: string,
    icon: React.ReactNode,
    gridArea: string,
  ) => (
    <button
      type="button"
      aria-label={label}
      style={{ gridArea }}
      disabled={!connected}
      onPointerDown={(event) => { event.preventDefault(); start(direction) }}
      className={`touch-none select-none rounded-xl border flex flex-col items-center justify-center gap-1 transition-colors ${
        active === direction
          ? 'border-blue-400 bg-blue-600 text-white'
          : 'border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700'
      } disabled:opacity-35`}
    >
      {icon}<span className="text-[11px]">{label}</span>
    </button>
  )

  return (
    <section className="rounded-xl border border-blue-500/20 bg-slate-900/60 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800">
        <h2 className="text-sm font-medium text-white">Pilotage de cartographie</h2>
        <p className="text-xs text-slate-500 mt-0.5">Pilotez et contrôlez la carte sans changer d’écran.</p>
      </div>

      <div className="aspect-video bg-black relative flex items-center justify-center">
        {connected ? (
          <img src={streamUrl} alt="Vue caméra du rover" className="absolute inset-0 w-full h-full object-contain" />
        ) : (
          <div className="text-slate-600 text-xs text-center"><Camera size={28} className="mx-auto mb-2" />Robot hors ligne</div>
        )}
      </div>

      <div className="p-4">
        <div className="grid grid-cols-[repeat(3,68px)] grid-rows-[repeat(3,62px)] justify-center gap-2">
          {driveButton('forward', 'Avant', <ArrowUp size={21} />, '1 / 2')}
          {driveButton('left', 'Gauche', <ArrowLeft size={21} />, '2 / 1')}
          <button type="button" onPointerDown={stop} disabled={!connected}
            style={{ gridArea: '2 / 2' }}
            className="touch-none rounded-xl border border-red-500/40 bg-red-500/15 text-red-300 flex flex-col items-center justify-center gap-1 disabled:opacity-35">
            <Square size={19} /><span className="text-[11px]">Stop</span>
          </button>
          {driveButton('right', 'Droite', <ArrowRight size={21} />, '2 / 3')}
          {driveButton('backward', 'Arrière', <ArrowDown size={21} />, '3 / 2')}
        </div>

        <label className="block mt-4 text-xs text-slate-400">
          <span className="flex justify-between mb-2"><span>Vitesse</span><span>{Math.round(speed * 200)} %</span></span>
          <input type="range" min="0.15" max="0.5" step="0.05" value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
            className="w-full accent-blue-500" />
        </label>
        <p className="text-[11px] text-slate-600 text-center mt-2">WASD ou flèches · Espace pour arrêter</p>
      </div>
    </section>
  )
}
