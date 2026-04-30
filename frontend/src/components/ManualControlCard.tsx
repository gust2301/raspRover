import { useState, useCallback } from 'react'
import { ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Square, AlertCircle } from 'lucide-react'

type Dir = 'forward' | 'backward' | 'left' | 'right' | null

export default function ManualControlCard() {
  const [active, setActive] = useState<Dir>(null)
  const [speed, setSpeed] = useState(1.2)
  const [manualMode, setManualMode] = useState(false)

  const handleDir = useCallback((dir: Dir) => {
    if (!manualMode) return
    setActive(dir)
  }, [manualMode])

  const dirButtons = [
    { dir: 'forward' as Dir, icon: ArrowUp, label: 'Avant', gridArea: '1 / 2' },
    { dir: 'left' as Dir, icon: ArrowLeft, label: 'Gauche', gridArea: '2 / 1' },
    { dir: null, icon: Square, label: 'Stop', gridArea: '2 / 2' },
    { dir: 'right' as Dir, icon: ArrowRight, label: 'Droite', gridArea: '2 / 3' },
    { dir: 'backward' as Dir, icon: ArrowDown, label: 'Arrière', gridArea: '3 / 2' },
  ]

  return (
    <div className="rounded-xl border border-slate-800 p-5 h-full" style={{ background: '#0f1629' }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-white font-semibold text-sm">Contrôle manuel</h2>
        <button
          onClick={() => setManualMode(v => !v)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            manualMode
              ? 'bg-blue-600/20 text-blue-400 border border-blue-600/40'
              : 'bg-slate-800 text-slate-400 border border-slate-700'
          }`}
        >
          {manualMode ? 'Mode manuel actif' : 'Mode manuel'}
        </button>
      </div>

      {!manualMode && (
        <div className="flex items-center gap-2 mb-3 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <AlertCircle size={13} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-400">Activez le mode manuel pour contrôler le robot</p>
        </div>
      )}

      {/* D-pad */}
      <div className="flex justify-center mb-5">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 52px)', gridTemplateRows: 'repeat(3, 52px)', gap: '6px' }}>
          {dirButtons.map(({ dir, icon: Icon, label, gridArea }) => (
            <button
              key={label}
              style={{ gridArea }}
              onPointerDown={() => handleDir(dir)}
              onPointerUp={() => handleDir(null)}
              onPointerLeave={() => handleDir(null)}
              disabled={!manualMode && dir !== null}
              className={`rounded-xl flex flex-col items-center justify-center gap-1 text-xs font-medium transition-all select-none ${
                dir === null
                  ? active !== null
                    ? 'bg-red-600 text-white'
                    : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  : active === dir
                    ? 'bg-blue-600 text-white scale-95 shadow-lg shadow-blue-900/50'
                    : manualMode
                      ? 'bg-slate-800 text-slate-300 hover:bg-slate-700 active:bg-blue-600 active:text-white'
                      : 'bg-slate-800/50 text-slate-600 cursor-not-allowed'
              }`}
            >
              <Icon size={18} />
              <span className="text-[10px] leading-none">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Speed */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400">Vitesse</span>
          <span className="text-xs text-blue-400 font-medium">{speed.toFixed(1)} m/s</span>
        </div>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={speed}
          onChange={e => setSpeed(Number(e.target.value))}
          disabled={!manualMode}
          className="w-full accent-blue-500 disabled:opacity-40"
        />
        <div className="flex justify-between text-xs text-slate-600 mt-1">
          <span>0</span>
          <span>2,0</span>
        </div>
      </div>

      <p className="text-xs text-slate-600 mt-3 text-center">
        Contrôle réservé aux opérateurs autorisés
      </p>
    </div>
  )
}
