import { useEffect, useState } from 'react'
import { Maximize2, Camera, CameraOff, Circle, Dot } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'

export default function VideoFeedCard() {
  const conn = useSharedRobotConnection()
  const [recording] = useState(true)
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const streamUrl = getRobotStreamUrl(conn.robotIp)

  useEffect(() => {
    setStreamUnavailable(false)
  }, [conn.robotIp, conn.status])

  return (
    <div
      className="rounded-xl border border-slate-800 overflow-hidden"
      style={{ background: '#0f1629' }}
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <h2 className="text-white font-semibold text-sm">Flux vidéo en direct</h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${conn.status === 'connected' ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`} />
            <span className={`text-xs font-medium ${conn.status === 'connected' ? 'text-emerald-400' : 'text-slate-500'}`}>
              {conn.status === 'connected' ? 'En direct' : 'Hors ligne'}
            </span>
          </div>
          <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
            <Maximize2 size={15} />
          </button>
        </div>
      </div>

      <div className="relative aspect-video bg-slate-950 flex items-center justify-center overflow-hidden">
        <div
          className="absolute inset-0"
          style={{ background: 'linear-gradient(180deg, #0a0f1e 0%, #111827 60%, #1e293b 100%)' }}
        >
          <svg className="absolute inset-0 w-full h-full opacity-10" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse">
                <path d="M 60 0 L 0 0 0 60" fill="none" stroke="#3b82f6" strokeWidth="0.5" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
          <div
            className="absolute inset-0 opacity-5"
            style={{
              backgroundImage:
                'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(59,130,246,0.3) 2px, rgba(59,130,246,0.3) 4px)',
            }}
          />
        </div>

        {conn.status === 'connected' && !streamUnavailable && (
          <img
            key={streamUrl}
            src={streamUrl}
            alt="Camera feed"
            className="absolute inset-0 w-full h-full object-contain bg-black z-10"
            onLoad={() => setStreamUnavailable(false)}
            onError={() => setStreamUnavailable(true)}
          />
        )}

        {(conn.status !== 'connected' || streamUnavailable) && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="text-slate-700 text-center px-6">
              {streamUnavailable ? (
                <CameraOff size={48} className="mx-auto mb-2 opacity-40" />
              ) : (
                <Camera size={48} className="mx-auto mb-2 opacity-30" />
              )}
              <p className="text-xs opacity-40">
                {conn.status === 'connected'
                  ? 'Flux caméra indisponible'
                  : 'Connectez-vous au robot pour voir le flux'}
              </p>
            </div>
          </div>
        )}

        <div className="absolute top-3 left-3 flex items-center gap-2 z-20">
          {recording && conn.status === 'connected' && (
            <div className="flex items-center gap-1.5 bg-black/60 backdrop-blur-sm rounded px-2 py-1">
              <Circle size={8} className="text-red-500 fill-red-500 animate-pulse" />
              <span className="text-white text-xs font-bold">REC</span>
              <span className="text-slate-300 text-xs">LIVE</span>
            </div>
          )}
        </div>

        <div className="absolute bottom-3 left-3 flex items-center gap-2 z-20">
          <span className="bg-black/60 backdrop-blur-sm text-slate-300 text-xs px-2 py-1 rounded font-mono">MJPEG</span>
          <span className="bg-black/60 backdrop-blur-sm text-slate-300 text-xs px-2 py-1 rounded font-mono">{conn.robotIp}</span>
        </div>

        <div className="absolute bottom-3 right-3 z-20">
          <div className="flex items-center gap-1 bg-black/60 backdrop-blur-sm rounded px-2 py-1">
            <Dot size={14} className={conn.status === 'connected' ? 'text-emerald-400' : 'text-slate-500'} />
            <span className="text-slate-300 text-xs font-mono">{conn.latencyMs ?? '--'} ms</span>
          </div>
        </div>

        <div className="absolute top-3 left-3 w-5 h-5 border-t-2 border-l-2 border-blue-500/50 rounded-tl z-20" />
        <div className="absolute top-3 right-3 w-5 h-5 border-t-2 border-r-2 border-blue-500/50 rounded-tr z-20" />
        <div className="absolute bottom-3 left-3 w-5 h-5 border-b-2 border-l-2 border-blue-500/50 rounded-bl z-20" />
        <div className="absolute bottom-3 right-3 w-5 h-5 border-b-2 border-r-2 border-blue-500/50 rounded-br z-20" />
      </div>
    </div>
  )
}
