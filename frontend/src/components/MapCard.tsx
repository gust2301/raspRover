import { Maximize2 } from 'lucide-react'

export default function MapCard() {
  return (
    <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <h2 className="text-white font-semibold text-sm">Carte / Zone surveillée</h2>
        <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
          <Maximize2 size={15} />
        </button>
      </div>
      <div className="relative h-52 overflow-hidden" style={{ background: '#070d1a' }}>
        <svg className="w-full h-full" viewBox="0 0 500 200" xmlns="http://www.w3.org/2000/svg">
          {/* Background grid */}
          <defs>
            <pattern id="mapgrid" width="25" height="25" patternUnits="userSpaceOnUse">
              <path d="M 25 0 L 0 0 0 25" fill="none" stroke="#1e293b" strokeWidth="0.5"/>
            </pattern>
            <filter id="glow">
              <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
              <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <rect width="500" height="200" fill="url(#mapgrid)" />

          {/* Warehouse walls */}
          <rect x="30" y="20" width="440" height="160" fill="none" stroke="#1e3a5f" strokeWidth="2" rx="4" />

          {/* Inner zones */}
          <rect x="50" y="40" width="120" height="120" fill="#0a1628" stroke="#1e3a5f" strokeWidth="1" rx="2" />
          <rect x="190" y="40" width="120" height="120" fill="#0a1628" stroke="#1e3a5f" strokeWidth="1" rx="2" />
          <rect x="330" y="40" width="120" height="120" fill="#0a1628" stroke="#1e3a5f" strokeWidth="1" rx="2" />

          {/* Zone labels */}
          <text x="110" y="105" textAnchor="middle" fill="#1e3a5f" fontSize="11" fontFamily="monospace">ZONE A</text>
          <text x="250" y="105" textAnchor="middle" fill="#1e3a5f" fontSize="11" fontFamily="monospace">ZONE B</text>
          <text x="390" y="105" textAnchor="middle" fill="#1e3a5f" fontSize="11" fontFamily="monospace">ZONE C</text>

          {/* Patrol path */}
          <polyline
            points="80,160 80,60 200,60 200,160 320,160 320,60 430,60 430,130"
            fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.6"
            filter="url(#glow)"
          />

          {/* Checkpoints */}
          {([
            [80, 60], [200, 60], [200, 160], [320, 160], [320, 60], [430, 60],
          ] as [number, number][]).map(([cx, cy], i) => (
            <circle key={i} cx={cx} cy={cy} r="4" fill="#1e40af" stroke="#3b82f6" strokeWidth="1.5" />
          ))}

          {/* Sensitive zones */}
          <rect x="340" y="50" width="50" height="30" fill="#ef444420" stroke="#ef4444" strokeWidth="1" strokeDasharray="3,2" rx="2" />
          <text x="365" y="70" textAnchor="middle" fill="#ef4444" fontSize="7" fontFamily="monospace">SENSIBLE</text>

          {/* Robot position */}
          <g transform="translate(430, 130)" filter="url(#glow)">
            <circle r="10" fill="#1d4ed8" stroke="#3b82f6" strokeWidth="2" opacity="0.9" />
            <circle r="14" fill="none" stroke="#3b82f6" strokeWidth="1" opacity="0.4">
              <animate attributeName="r" values="14;20;14" dur="2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
            </circle>
            <polygon points="0,-5 4,3 -4,3" fill="#93c5fd" />
          </g>
        </svg>

        {/* Legend */}
        <div className="absolute bottom-3 left-3 flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-blue-500" />
            <span className="text-slate-400">Robot</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-4 border-t border-dashed border-blue-500/60" />
            <span className="text-slate-400">Itinéraire</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-red-500/50 border border-red-500" />
            <span className="text-slate-400">Zone sensible</span>
          </div>
        </div>
      </div>
    </div>
  )
}
