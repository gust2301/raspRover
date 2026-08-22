import { useEffect, useRef, useState, useCallback } from 'react'
import { Map, Play, Square, Save, RefreshCw, AlertTriangle, FolderOpen, Navigation, CheckCircle, House, Trash2 } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl } from '../lib/robotTransport'
import SlamMappingControls from '../components/SlamMappingControls'

interface RoverPose { x: number; y: number; yaw: number; updated_at?: number }
interface SlamStatus {
  running: boolean
  container: string
  mode: 'mapping' | 'navigation' | 'stopped'
  pose?: RoverPose | null
  error?: string | null
  topics?: { map: boolean; odom: boolean; scan: boolean }
}
interface SavedMap { name: string; modified_at: number; size_bytes: number }
interface MapHome extends RoverPose { map_name: string; updated_at?: number }
interface SlamMap {
  ok: boolean
  image: string
  width: number
  height: number
  resolution_m: number
  origin_x: number
  origin_y: number
  updated_at?: number
}

export default function MapView() {
  const { robotIp, status: connStatus } = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(robotIp)
  const isOnline = connStatus === 'connected'

  const [slamRunning, setSlamRunning] = useState(false)
  const [mode, setMode] = useState<SlamStatus['mode']>('stopped')
  const [pose, setPose] = useState<RoverPose | null>(null)
  const [savedMaps, setSavedMaps] = useState<SavedMap[]>([])
  const [navState, setNavState] = useState('idle')
  const [home, setHome] = useState<MapHome | null>(null)
  const [savingHome, setSavingHome] = useState(false)
  const [homeBusy, setHomeBusy] = useState(false)
  const [mapData, setMapData] = useState<SlamMap | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const posePollInFlight = useRef(false)

  // ── helpers ───────────────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    if (!isOnline) return
    try {
      const r = await fetch(`${apiBase}/api/slam/status`)
      if (!r.ok) return
      const d: SlamStatus = await r.json()
      setSlamRunning(d.running)
      setMode(d.mode ?? (d.running ? 'mapping' : 'stopped'))
      setPose(d.pose ?? null)
      setStatusMessage(d.error ?? null)
    } catch { /* ignore */ }
  }, [apiBase, isOnline])

  const fetchSavedMaps = useCallback(async () => {
    if (!isOnline) return
    try {
      const r = await fetch(`${apiBase}/api/slam/maps`)
      const d = await r.json()
      if (r.ok) setSavedMaps(d.maps ?? [])
    } catch { /* ignore */ }
  }, [apiBase, isOnline])

  const fetchMap = useCallback(async () => {
    if (!isOnline || !slamRunning) return
    try {
      const r = await fetch(`${apiBase}/api/slam/map`)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        const message = (body as { error?: string }).error ?? `HTTP ${r.status}`
        if (message !== 'Aucune carte disponible') setError(message)
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

  const fetchNavStatus = useCallback(async () => {
    if (!isOnline || mode !== 'navigation') return
    try {
      const r = await fetch(`${apiBase}/api/nav2/home/status`)
      const d = await r.json()
      setNavState(d.state ?? 'unavailable')
    } catch { /* ignore */ }
  }, [apiBase, isOnline, mode])

  const fetchHome = useCallback(async () => {
    if (!isOnline || mode !== 'navigation') return
    try {
      const r = await fetch(`${apiBase}/api/slam/home`)
      const d = await r.json()
      if (r.ok) setHome(d.home ?? null)
    } catch { /* ignore */ }
  }, [apiBase, isOnline, mode])

  const fetchPose = useCallback(async () => {
    if (!isOnline || mode !== 'navigation' || posePollInFlight.current) return
    posePollInFlight.current = true
    try {
      const r = await fetch(`${apiBase}/api/slam/pose`)
      if (r.ok) setPose(await r.json())
    } catch { /* le prochain passage réessaiera */ }
    finally { posePollInFlight.current = false }
  }, [apiBase, isOnline, mode])

  // ── actions ───────────────────────────────────────────────────────────────

  async function handleStart() {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/api/slam/start`, { method: 'POST' })
      const d = await r.json()
      if (d.ok || d.running) { setSlamRunning(true); setMode('mapping') }
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
      setMode('stopped')
      setMapData(null)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const suggested = `carte-${new Date().toISOString().slice(0, 10)}`
      const name = window.prompt('Nom de la carte', suggested)?.trim()
      if (!name) return
      const r = await fetch(`${apiBase}/api/slam/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const d = await r.json()
      if (!d.ok) setError(d.error ?? 'Sauvegarde échouée')
      else {
        await fetchSavedMaps()
        setNotice(`Carte « ${d.name ?? name} » sauvegardée avec succès`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  async function handleLoadMap(name: string) {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/api/slam/load`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error ?? 'Chargement échoué')
      setSlamRunning(true)
      setMode('navigation')
      setHome(null)
      window.setTimeout(() => { void fetchMap(); void fetchStatus(); void fetchHome() }, 1500)
    } catch (e) { setError(e instanceof Error ? e.message : 'Erreur') }
    finally { setLoading(false) }
  }

  async function handleDeleteMap(name: string) {
    if (!window.confirm(`Supprimer la carte « ${name} » ?`)) return
    setLoading(true); setError(null); setNotice(null)
    try {
      let response = await fetch(`${apiBase}/api/slam/maps/${encodeURIComponent(name)}`, { method: 'DELETE' })
      let data = await response.json()
      if (response.status === 409 && data.requires_force) {
        const dependencies = data.dependencies ?? {}
        const confirmed = window.confirm(
          `Cette carte contient ${dependencies.routes ?? 0} parcours, ${dependencies.inspections ?? 0} inspections et ${dependencies.captures ?? 0} photos. Tout supprimer définitivement ?`,
        )
        if (!confirmed) return
        response = await fetch(`${apiBase}/api/slam/maps/${encodeURIComponent(name)}?force=true`, { method: 'DELETE' })
        data = await response.json()
      }
      if (!response.ok || data.ok === false) throw new Error(data.error ?? 'Suppression impossible')
      await fetchSavedMaps()
      setNotice(`Carte « ${name} » supprimée.`)
    } catch (e) { setError(e instanceof Error ? e.message : 'Erreur') }
    finally { setLoading(false) }
  }

  async function handleSetHome() {
    setSavingHome(true)
    setError(null)
    try {
      const r = await fetch(`${apiBase}/api/slam/home`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error ?? 'Maison non enregistrée')
      setHome(d.home)
      setNotice('La position actuelle est maintenant la maison du rover')
    } catch (e) { setError(e instanceof Error ? e.message : 'Erreur') }
    finally { setSavingHome(false) }
  }

  async function handleGoHome() {
    setHomeBusy(true)
    setError(null)
    setNotice(null)
    try {
      const r = await fetch(`${apiBase}/api/nav2/home/start`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok || d.ok === false) throw new Error(d.error ?? 'Retour maison impossible')
      setNavState(d.state ?? 'starting')
      setNotice(d.message ?? 'Retour à la maison démarré')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Retour maison impossible')
    } finally { setHomeBusy(false) }
  }

  async function handleStopHome() {
    setHomeBusy(true)
    try {
      await fetch(`${apiBase}/api/nav2/home/stop`, { method: 'POST' })
      setNavState('cancelled')
      setNotice('Retour à la maison arrêté')
    } finally { setHomeBusy(false) }
  }

  // ── effects ───────────────────────────────────────────────────────────────

  useEffect(() => { void fetchStatus(); void fetchSavedMaps() }, [fetchStatus, fetchSavedMaps])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (slamRunning && isOnline) {
      void fetchMap(); void fetchHome()
      if (mode === 'navigation') {
        void fetchPose(); void fetchNavStatus()
        pollRef.current = setInterval(() => {
          void fetchPose(); void fetchNavStatus()
        }, 500)
      } else {
        pollRef.current = setInterval(() => {
          void fetchMap()
        }, 2500)
      }
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [slamRunning, isOnline, mode, fetchMap, fetchNavStatus, fetchHome, fetchPose])

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
            <p className="text-slate-500 text-xs">
              {mode === 'navigation' ? 'Nav2 + AMCL' : 'slam_toolbox online_async'} — ROS 2 Jazzy
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {slamRunning && mode === 'mapping' && (
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
            {loading ? '…' : slamRunning
              ? mode === 'navigation' ? 'Arrêter Nav2' : 'Arrêter SLAM'
              : 'Démarrer SLAM'}
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

      {statusMessage && !error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-sm">
          <AlertTriangle size={15} />
          {statusMessage}
        </div>
      )}

      {notice && (
        <div className="fixed z-50 right-4 bottom-4 max-w-sm flex items-center gap-2 px-4 py-3 rounded-xl bg-emerald-950 border border-emerald-500/40 text-emerald-300 text-sm shadow-2xl">
          <CheckCircle size={17} className="shrink-0" />
          <span>{notice}</span>
          <button onClick={() => setNotice(null)} className="ml-2 text-emerald-500 hover:text-emerald-200" aria-label="Fermer">×</button>
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex items-center gap-2 mb-3 text-sm font-medium text-slate-200">
          <FolderOpen size={15} /> Cartes enregistrées
        </div>
        {savedMaps.length === 0 ? (
          <p className="text-xs text-slate-500">Aucune carte persistante.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {savedMaps.map(saved => (
              <div key={saved.name} className="flex rounded-lg overflow-hidden">
                <button onClick={() => { void handleLoadMap(saved.name) }} disabled={loading}
                  className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 disabled:opacity-40">
                  Charger {saved.name}
                </button>
                <button onClick={() => { void handleDeleteMap(saved.name) }} disabled={loading}
                  className="px-3 bg-red-500/15 text-red-400 hover:bg-red-500/25 disabled:opacity-40"
                  title={`Supprimer ${saved.name}`}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={slamRunning && mode === 'mapping' ? 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]' : ''}>
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
            <div className="relative w-full max-w-2xl mx-auto">
              <img src={`data:image/png;base64,${mapData.image}`} alt="Carte SLAM"
                className="block w-full rounded border border-slate-700" style={{ imageRendering: 'pixelated' }} />
              {pose && (() => {
                const left = (pose.x - mapData.origin_x) / mapData.resolution_m / mapData.width * 100
                const top = 100 - (pose.y - mapData.origin_y) / mapData.resolution_m / mapData.height * 100
                return <div className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full bg-blue-500 border-2 border-white shadow-lg"
                  style={{ left: `${left}%`, top: `${top}%`, transform: `rotate(${pose.yaw}rad)` }} title="Position du rover">
                  <div className="absolute left-1/2 top-[-7px] w-0.5 h-2 bg-blue-500" />
                </div>
              })()}
              {home && (() => {
                const left = (home.x - mapData.origin_x) / mapData.resolution_m / mapData.width * 100
                const top = 100 - (home.y - mapData.origin_y) / mapData.resolution_m / mapData.height * 100
                return <div className="absolute -ml-3 -mt-3 w-6 h-6 rounded-full bg-amber-500 border-2 border-white text-white flex items-center justify-center shadow-lg"
                  style={{ left: `${left}%`, top: `${top}%` }} title="Maison du rover">
                  <House size={13} />
                </div>
              })()}
            </div>
            <div className="flex items-center justify-center gap-6 text-xs text-slate-500 mt-2">
              <span>{mapData.width} × {mapData.height} px</span>
              <span>{(mapData.resolution_m * 100).toFixed(1)} cm/px</span>
              {lastUpdate && <span>Mis à jour {lastUpdate.toLocaleTimeString()}</span>}
            </div>
          </div>
        )}
      </div>
      {slamRunning && mode === 'mapping' && <SlamMappingControls />}
      </div>

      {mode === 'navigation' && (
        <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 flex flex-wrap items-center gap-3">
          <Navigation size={17} className="text-blue-400" />
          <div className="flex-1 min-w-48">
            <p className="text-sm text-slate-200">Navigation Nav2 · {navState}</p>
            <p className="text-xs text-slate-500">Un seul objectif : rejoindre la maison enregistrée.</p>
          </div>
          <button onClick={() => { void handleSetHome() }} disabled={savingHome || !pose}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-amber-500/15 text-xs text-amber-300 disabled:opacity-40">
            <House size={14} />
            {savingHome ? 'Enregistrement…' : home ? 'Redéfinir la maison' : 'Définir comme maison'}
          </button>
          {navState === 'running' || navState === 'starting' ? (
            <button onClick={() => { void handleStopHome() }} disabled={homeBusy}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-red-600/30 text-xs text-red-300 disabled:opacity-40">
              <Square size={14} /> Arrêter le retour
            </button>
          ) : (
            <button onClick={() => { void handleGoHome() }} disabled={homeBusy || !home}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 text-xs text-white disabled:opacity-40">
              <House size={14} /> {homeBusy ? 'Démarrage…' : 'Rentrer à la maison'}
            </button>
          )}
        </div>
      )}

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
