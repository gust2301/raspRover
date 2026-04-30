import { useState } from 'react'
import { Maximize2, Camera, Circle, Dot } from 'lucide-react'

export default function VideoFeedCard() {
  const [recording] = useState(true)

  return (
    <div
      className="rounded-xl border border-slate-800 overflow-hidden"
      style={{ background: '#0f1629' }}
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <h2 className="text-white font-semibold text-sm">Flux vidéo en direct</h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-emerald-400 text-xs font-medium">En direct</span>
          </div>
          <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
            <Maximize2 size={15} />
          </button>
        </div>
      </div>

      {/* Video feed */}
      <div className="relative aspect-video bg-slate-950 flex items-center justify-center overflow-hidden">
        {/* Simulated warehouse background */}
        <div className="absolute inset-0" style={{
          background: 'linear-gradient(180deg, #0a0f1e 0%, #111827 60%, #1e293b 100%)',
        }}>
          {/* Grid lines simulating warehouse */}
          <svg className="absolute inset-0 w-full h-full opacity-10" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
                <path d="M 60 0 L 0 0 0 60" fill="none" stroke="#3b82f6" strokeWidth="0.5"/>
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
          {/* Scan line effect */}
          <div className="absolute inset-0 opacity-5" style={{
            backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(59,130,246,0.3) 2px, rgba(59,130,246,0.3) 4px)',
          }} />
          {/* Center robot silhouette hint */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-slate-700 text-center">
              <Camera size={48} className="mx-auto mb-2 opacity-30" />
              <p className="text-xs opacity-30">Signal vidéo — En attente caméra</p>
            </div>
          </div>
        </div>

        {/* Overlays */}
        <div className="absolute top-3 left-3 flex items-center gap-2">
          {recording && (
            <div className="flex items-center gap-1.5 bg-black/60 backdrop-blur-sm rounded px-2 py-1">
              <Circle size={8} className="text-red-500 fill-red-500 animate-pulse" />
              <span className="text-white text-xs font-bold">REC</span>
              <span className="text-slate-300 text-xs">00:12:45</span>
            </div>
          )}
        </div>

        <div className="absolute bottom-3 left-3 flex items-center gap-2">
          <span className="bg-black/60 backdrop-blur-sm text-slate-300 text-xs px-2 py-1 rounded font-mono">1080p</span>
          <span className="bg-black/60 backdrop-blur-sm text-slate-300 text-xs px-2 py-1 rounded font-mono">30 fps</span>
        </div>

        <div className="absolute bottom-3 right-3">
          <div className="flex items-center gap-1 bg-black/60 backdrop-blur-sm rounded px-2 py-1">
            <Dot size={14} className="text-emerald-400" />
            <span className="text-slate-300 text-xs font-mono">24 ms</span>
          </div>
        </div>

        {/* Corner brackets */}
        <div className="absolute top-3 left-3 w-5 h-5 border-t-2 border-l-2 border-blue-500/50 rounded-tl" />
        <div className="absolute top-3 right-3 w-5 h-5 border-t-2 border-r-2 border-blue-500/50 rounded-tr" />
        <div className="absolute bottom-3 left-3 w-5 h-5 border-b-2 border-l-2 border-blue-500/50 rounded-bl" />
        <div className="absolute bottom-3 right-3 w-5 h-5 border-b-2 border-r-2 border-blue-500/50 rounded-br" />
      </div>
    </div>
  )
}
