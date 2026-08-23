import { useEffect, useState, useCallback } from 'react'
import { Map, Maximize2, RefreshCw } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl } from '../lib/robotTransport'
import { useNavigate } from 'react-router-dom'

interface SlamStatus { running: boolean }
interface SlamMap { ok: boolean; image: string; width: number; height: number; resolution_m: number }

export default function MapCard() {
  const { robotIp, status: connStatus } = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(robotIp)
  const isOnline = connStatus === 'connected'
  const navigate = useNavigate()

  const [slamRunning, setSlamRunning] = useState(false)
  const [mapData, setMapData] = useState<SlamMap | null>(null)

  const fetchStatus = useCallback(async () => {
    if (!isOnline) return
    try {
      const r = await fetch(`${apiBase}/api/slam/status`)
      if (!r.ok) return
      const d: SlamStatus = await r.json()
      setSlamRunning(d.running)
    } catch { /* ignore */ }
  }, [apiBase, isOnline])

  const fetchMap = useCallback(async () => {
    if (!isOnline || !slamRunning) return
    try {
      const r = await fetch(`${apiBase}/api/slam/map`)
      if (!r.ok) return
      const d: SlamMap = await r.json()
      if (d.ok) setMapData(d)
    } catch { /* ignore */ }
  }, [apiBase, isOnline, slamRunning])

  useEffect(() => {
    void fetchStatus()
    const id = setInterval(() => { void fetchStatus() }, 5000)
    return () => clearInterval(id)
  }, [fetchStatus])

  useEffect(() => {
    if (!slamRunning || !isOnline) return
    void fetchMap()
    const id = setInterval(() => { void fetchMap() }, 4000)
    return () => clearInterval(id)
  }, [slamRunning, isOnline, fetchMap])

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#0f1629] overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Map size={15} className={slamRunning ? 'text-purple-600 dark:text-purple-400' : 'text-slate-400 dark:text-slate-500'} />
          <h2 className="text-slate-900 dark:text-white font-semibold text-sm">Carte SLAM</h2>
          {slamRunning && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-400 font-mono">EN COURS</span>
          )}
        </div>
        <button
          onClick={() => navigate('/map')}
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800 transition-colors"
          title="Ouvrir la carte complète"
        >
          <Maximize2 size={15} />
        </button>
      </div>

      <div className="relative h-52 flex items-center justify-center bg-[#070d1a]">
        {!isOnline ? (
          <div className="text-center text-slate-600 space-y-1">
            <Map size={28} className="mx-auto opacity-30" />
            <p className="text-xs">Robot non connecté</p>
          </div>
        ) : mapData ? (
          <img
            src={`data:image/png;base64,${mapData.image}`}
            alt="Carte SLAM"
            className="w-full h-full object-contain"
            style={{ imageRendering: 'pixelated' }}
          />
        ) : slamRunning ? (
          <div className="text-center text-slate-500 space-y-2">
            <RefreshCw size={24} className="mx-auto animate-spin opacity-50" />
            <p className="text-xs">Génération de la carte…</p>
          </div>
        ) : (
          <div className="text-center space-y-3">
            <Map size={28} className="mx-auto text-slate-600 opacity-50" />
            <p className="text-xs text-slate-500">SLAM inactif</p>
            <button
              onClick={() => navigate('/map')}
              className="flex items-center gap-1.5 mx-auto px-3 py-1.5 rounded-lg text-xs font-medium text-purple-300 bg-purple-600/20 hover:bg-purple-600/30 disabled:opacity-40 transition-colors"
            >
              <Map size={12} />
              Ouvrir Carte SLAM
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
