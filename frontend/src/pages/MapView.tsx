import { useEffect, useRef, useState, useCallback } from 'react'
import { Map, Play, Square, Save, RefreshCw, AlertTriangle } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl } from '../lib/robotTransport'

interface SlamStatus { running: boolean; container: string }
interface SlamMap {
  ok: boolean
  image: string
  width: number
  height: number
  resolution_m: number
  origin_x: number
  origin_y: number
}

export default function MapView() {
  const { robotIp, status: connStatus } = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(robotIp)
  const isOnline = connStatus === 'connected'

  const [slamRunning, setSlamRunning] = useState(false)
  const [mapData, setMapData] = useState<SlamMap | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── helpers ───────────────────────────────────────────────────────────────

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
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        setError((body as { error?: string }).error ?? `HTTP ${r.status}`)
        return
      }
      const d: SlamMap = await r.json()
      setMapData(d)
      setLastUpdate(new Date())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur inconnue')
    }
  }, [apiBase, isOnline, slamRunning])

  // ── actions ───────────────────────────────────────────────────────────────

  async function handleStart() {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/api/slam/start`, { method: 'POST' })
      const d = await r.json()
      if (d.ok || d.running) { setSlamRunning(true) }
      else setError(d.error ?? 'Démarrage SLAM échoué')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setLoading(false)
    }
  }

  async function handleStop() {
    setLoading(true)
    try {
      await fetch(`${apiBase}/api/slam/stop`, { method: 'POST' })
      setSlamRunning(false)
      setMapData(null)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/api/slam/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: '/tmp/rasprover_map' }),
      })
      const d = await r.json()
      if (!d.ok) setError(d.error ?? 'Sauvegarde échouée')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  // ── effects ───────────────────────────────────────────────────────────────

  useEffect(() => { void fetchStatus() }, [fetchStatus])

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (slamRunning && isOnline) {
      void fetchMap()
      pollRef.current = setInterval(fetchMap, 3000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [slamRunning, isOnline, fetchMap])

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <Map size={18} className="text-purple-400" />
          </div>
          <div>
            <h1 className="text-white font-semibold text-lg">Carte SLAM</h1>
            <p className="text-slate-500 text-xs">slam_toolbox online_async — ROS 2 Jazzy</p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {slamRunning && (
            <>
              <button
                onClick={() => { void fetchMap() }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
              >
                <RefreshCw size={13} />
                Actualiser
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !mapData}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-emerald-300 bg-emerald-600/20 hover:bg-emerald-600/40 disabled:opacity-40 transition-colors"
              >
                <Save size={13} />
                {saving ? 'Sauvegarde…' : 'Sauvegarder'}
              </button>
            </>
          )}
          <button
            onClick={slamRunning ? handleStop : handleStart}
            disabled={loading || !isOnline}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40 ${
              slamRunning
                ? 'text-red-300 bg-red-600/20 hover:bg-red-600/40'
                : 'text-blue-300 bg-blue-600/20 hover:bg-blue-600/40'
            }`}
          >
            {slamRunning ? <Square size={13} /> : <Play size={13} />}
            {loading ? '…' : slamRunning ? 'Arrêter SLAM' : 'Démarrer SLAM'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}

      {/* Map display */}
      <div
        className="rounded-xl overflow-hidden flex items-center justify-center"
        style={{ background: '#0f1629', border: '1px solid #1e293b', minHeight: '420px' }}
      >
        {!isOnline ? (
          <div className="text-center text-slate-500 space-y-2">
            <Map size={40} className="mx-auto opacity-30" />
            <p className="text-sm">Robot non connecté</p>
          </div>
        ) : !slamRunning ? (
          <div className="text-center text-slate-500 space-y-3">
            <Map size={40} className="mx-auto opacity-30" />
            <p className="text-sm">Lance le SLAM pour démarrer la cartographie</p>
            <p className="text-xs text-slate-600">
              Nécessite le container <code className="text-slate-500">ros2-slam</code>
            </p>
          </div>
        ) : !mapData ? (
          <div className="text-center text-slate-500 space-y-2">
            <RefreshCw size={28} className="mx-auto animate-spin opacity-50" />
            <p className="text-sm">Attente de la première carte…</p>
          </div>
        ) : (
          <div className="p-4 space-y-2 w-full">
            <img
              src={`data:image/png;base64,${mapData.image}`}
              alt="Carte SLAM"
              className="w-full max-w-2xl mx-auto rounded border border-slate-700"
              style={{ imageRendering: 'pixelated' }}
            />
            <div className="flex items-center justify-center gap-6 text-xs text-slate-500 mt-2">
              <span>{mapData.width} × {mapData.height} px</span>
              <span>{(mapData.resolution_m * 100).toFixed(1)} cm/px</span>
              {lastUpdate && <span>Mis à jour {lastUpdate.toLocaleTimeString()}</span>}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-xs text-slate-500">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-white" />
          <span>Libre</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-black border border-slate-700" />
          <span>Occupé</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm bg-slate-500" />
          <span>Inconnu</span>
        </div>
      </div>
    </div>
  )
}
