import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft, Check, ChevronRight, FileText,
  Loader2, Play, Radar, ScanLine, Square, TriangleAlert, Video,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl, getRobotStreamUrl } from '../lib/robotTransport'
import { zoneLabel } from '../data/zones'

type Screen = 'launch' | 'live' | 'report'

interface RouteSummary { id: string; name: string; map_name: string; waypoint_count: number }
interface CaptureRecord { id: string; zone: string; image_url: string }
interface Inspection {
  id: string
  registration: string
  route_name: string
  status: 'starting' | 'navigating' | 'capturing' | 'returning_home' | 'completed' | 'cancelled' | 'error'
  current_waypoint?: number | null
  error?: string | null
  captures?: CaptureRecord[]
  started_at?: string
  completed_at?: string | null
}
interface SlamStatus { mode: 'mapping' | 'navigation' | 'stopped'; ready: boolean; active_map: string | null }

const ACTIVE_STATUSES = new Set(['starting', 'navigating', 'capturing', 'returning_home'])

function formatDuration(startIso?: string, endIso?: string): string {
  if (!startIso || !endIso) return '—'
  const seconds = Math.max(0, Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m} min ${s.toString().padStart(2, '0')} s`
}

function formatDateTime(iso?: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function InspectionRunner({ onBackToSetup }: { onBackToSetup?: () => void }) {
  const conn = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(conn.robotIp)
  const streamUrl = getRobotStreamUrl(conn.robotIp)
  const connected = conn.status === 'connected'
  const battery = conn.lastStatus?.battery ?? null
  const obstacle = Boolean(conn.lastStatus?.obstacle || conn.lastStatus?.lidar_obstacle_front)

  const [screen, setScreen] = useState<Screen>('launch')
  const [routes, setRoutes] = useState<RouteSummary[]>([])
  const [slam, setSlam] = useState<SlamStatus>({ mode: 'stopped', ready: false, active_map: null })
  const [registration, setRegistration] = useState('')
  const [selectedRouteId, setSelectedRouteId] = useState('')
  const [busy, setBusy] = useState(false)
  const [prepareMessage, setPrepareMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const routesFetchInFlight = useRef(false)
  const slamFetchInFlight = useRef(false)

  const selectedRoute = routes.find(r => r.id === selectedRouteId) ?? null

  const refreshLaunchState = useCallback(async () => {
    if (!connected) return
    if (!routesFetchInFlight.current) {
      routesFetchInFlight.current = true
      fetch(`${apiBase}/api/automotive/routes`)
        .then(response => response.ok ? response.json() : null)
        .then(data => { if (data?.routes) setRoutes(data.routes) })
        .catch(() => {})
        .finally(() => { routesFetchInFlight.current = false })
    }
    if (!slamFetchInFlight.current) {
      slamFetchInFlight.current = true
      fetch(`${apiBase}/api/slam/status`)
        .then(response => response.ok ? response.json() : null)
        .then(data => { if (data) setSlam({ mode: data.mode, ready: Boolean(data.ready), active_map: data.active_map ?? null }) })
        .catch(() => {})
        .finally(() => { slamFetchInFlight.current = false })
    }
  }, [apiBase, connected])

  useEffect(() => {
    if (screen !== 'launch') return
    void refreshLaunchState()
    const timer = window.setInterval(() => { void refreshLaunchState() }, 4000)
    return () => window.clearInterval(timer)
  }, [screen, refreshLaunchState])

  useEffect(() => {
    if (!routes.length) return
    if (!selectedRouteId || !routes.some(r => r.id === selectedRouteId)) setSelectedRouteId(routes[0].id)
  }, [routes, selectedRouteId])

  async function request(path: string, body?: object) {
    const response = await fetch(`${apiBase}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    const data = await response.json()
    if (!response.ok || data.ok === false) throw new Error(data.error ?? 'Opération impossible')
    return data
  }

  async function waitForRobotReady(mapName: string) {
    const deadline = Date.now() + 60_000
    while (Date.now() < deadline) {
      const response = await fetch(`${apiBase}/api/slam/status`)
      if (response.ok) {
        const status = await response.json()
        setSlam({ mode: status.mode, ready: Boolean(status.ready), active_map: status.active_map ?? null })
        if (status.ready && status.mode === 'navigation' && status.active_map === mapName) return
      }
      await new Promise(resolve => setTimeout(resolve, 1500))
    }
    throw new Error('Le robot met trop de temps à se préparer. Réessayez.')
  }

  async function handleStart() {
    if (!selectedRoute || !registration.trim() || busy) return
    setBusy(true); setError(null)
    try {
      if (slam.active_map !== selectedRoute.map_name || slam.mode !== 'navigation') {
        setPrepareMessage('Préparation du robot pour ce plateau… (jusqu’à 60 s)')
        await request('/api/slam/load', { name: selectedRoute.map_name })
        await waitForRobotReady(selectedRoute.map_name)
      }
      setPrepareMessage(null)
      const data = await request('/api/automotive/inspections/start', { route_id: selectedRoute.id, registration: registration.trim() })
      setInspection(data.inspection)
      setScreen('live')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Impossible de démarrer l’inspection')
      setPrepareMessage(null)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (screen !== 'live' || !inspection) return
    let disposed = false
    const poll = async () => {
      try {
        const response = await fetch(`${apiBase}/api/automotive/inspections/${inspection.id}`)
        if (!response.ok || disposed) return
        const data = await response.json()
        const next = data.inspection as Inspection
        setInspection(next)
        if (next.status === 'completed') setScreen('report')
      } catch { /* le prochain sondage réessaiera */ }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 2000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [screen, inspection?.id, apiBase])

  async function handleStopInspection() {
    setBusy(true)
    try { await request('/api/automotive/inspections/stop') } catch { /* le robot est peut-être déjà arrêté */ }
    setBusy(false)
    setScreen('launch')
    setInspection(null)
  }

  function handleNewInspection() {
    setInspection(null)
    setRegistration('')
    setError(null)
    setScreen('launch')
  }

  const totalViews = selectedRoute?.waypoint_count ?? 0
  const currentView = inspection?.current_waypoint ?? 0
  const captureCount = inspection?.captures?.length ?? 0
  const progressRatio = totalViews > 0 ? Math.min(1, currentView / totalViews) : 0
  const circumference = 2 * Math.PI * 42

  return (
    <div className="max-w-md mx-auto flex flex-col">

      {screen === 'launch' && (
        <div className="flex-1 flex flex-col">
          <div className="flex flex-col gap-3">
            {error && (
              <div className="rounded-xl border px-4 py-3 text-sm flex items-center gap-2 border-red-200 bg-red-50 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400">
                <TriangleAlert size={16} className="shrink-0" />{error}
              </div>
            )}

            <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-4">
              <div className="flex items-center gap-2.5 mb-3">
                <span className="w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">1</span>
                <span className="font-semibold text-slate-900 dark:text-white">Véhicule</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 rounded-xl border-2 px-4 py-2.5 border-blue-600 bg-blue-50 dark:bg-blue-500/10">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Immatriculation</div>
                  <input
                    value={registration}
                    onChange={e => setRegistration(e.target.value.toUpperCase())}
                    placeholder="AA-000-AA"
                    className="w-full bg-transparent text-xl font-bold tracking-wide outline-none text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-600"
                  />
                </div>
                <div className="w-14 h-14 rounded-xl flex flex-col items-center justify-center gap-0.5 shrink-0 bg-slate-900 text-white dark:bg-slate-700">
                  <ScanLine size={20} />
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-4">
              <div className="flex items-center gap-2.5 mb-3">
                <span className="w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">2</span>
                <span className="font-semibold text-slate-900 dark:text-white">Motif</span>
              </div>
              {routes.length === 0 ? (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {connected ? 'Aucun parcours prêt sur ce robot pour le moment.' : 'Connectez-vous au robot pour voir les parcours disponibles.'}
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {routes.map(route => (
                    <button
                      key={route.id}
                      onClick={() => setSelectedRouteId(route.id)}
                      className={`flex items-center gap-3 rounded-xl border px-4 py-2.5 text-left transition-colors ${
                        route.id === selectedRouteId
                          ? 'border-blue-600 bg-blue-50 dark:bg-blue-500/10'
                          : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/60'
                      }`}
                    >
                      <span
                        className={`w-5 h-5 rounded-full shrink-0 ${
                          route.id === selectedRouteId
                            ? 'border-[6px] border-blue-600 bg-white'
                            : 'border-2 border-slate-300 dark:border-slate-600'
                        }`}
                      />
                      <span className={`flex-1 font-semibold text-[15px] ${route.id === selectedRouteId ? 'text-slate-900 dark:text-white' : 'text-slate-600 dark:text-slate-300'}`}>{route.name}</span>
                      {route.id === selectedRouteId && (
                        <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">{route.waypoint_count} vues</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedRoute && (
              <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center shrink-0">3</span>
                <span className="font-semibold flex-1 text-slate-900 dark:text-white">Emplacement</span>
                <span className="font-semibold text-blue-600 dark:text-blue-400">{selectedRoute.map_name}</span>
                <ChevronRight size={16} className="text-slate-400 dark:text-slate-500" />
              </div>
            )}
          </div>

          <div className="flex flex-col gap-3 mt-4">
            {prepareMessage ? (
              <div className="flex items-center gap-2.5 rounded-xl border px-3.5 py-3 border-blue-200 bg-blue-50 dark:border-blue-500/30 dark:bg-blue-500/10">
                <Loader2 size={16} className="animate-spin text-blue-600 dark:text-blue-400" />
                <span className="text-sm font-medium text-blue-600 dark:text-blue-400">{prepareMessage}</span>
              </div>
            ) : (
              <div
                className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-3 ${
                  connected
                    ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10'
                    : 'border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-900/40'
                }`}
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${connected ? 'bg-emerald-500' : 'bg-slate-400 dark:bg-slate-600'}`} />
                <span className={`text-sm font-semibold flex-1 ${connected ? 'text-emerald-700 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-500'}`}>
                  {connected ? `Robot prêt${battery != null ? ` · batterie ${battery} %` : ''}` : 'Robot hors ligne'}
                </span>
                {connected && <Check size={16} className="text-emerald-600 dark:text-emerald-400" />}
              </div>
            )}
            <button
              onClick={() => { void handleStart() }}
              disabled={!connected || !selectedRoute || !registration.trim() || busy}
              className="w-full py-3.5 rounded-2xl font-semibold text-white flex items-center justify-center gap-2 bg-blue-600 disabled:opacity-40"
            >
              {busy ? <Loader2 size={19} className="animate-spin" /> : <Play size={19} />}
              Démarrer l&rsquo;inspection
            </button>
            {onBackToSetup && (
              <button onClick={onBackToSetup} className="text-xs text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300">
                Configurer un autre plateau ou parcours
              </button>
            )}
          </div>
        </div>
      )}

      {screen === 'live' && inspection && (
        <div className="flex-1 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xl font-bold tracking-wide text-slate-900 dark:text-white">{inspection.registration}</div>
              <div className="text-[13px] text-slate-500 dark:text-slate-400">{inspection.route_name}{selectedRoute ? ` · ${selectedRoute.map_name}` : ''}</div>
            </div>
            {ACTIVE_STATUSES.has(inspection.status) ? (
              <div className="flex items-center gap-1.5 rounded-full border px-3 py-1.5 border-blue-200 bg-blue-50 dark:border-blue-500/30 dark:bg-blue-500/10">
                <span className="w-1.5 h-1.5 rounded-full animate-pulse bg-blue-600" />
                <span className="text-xs font-bold text-blue-600 dark:text-blue-400">EN COURS</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 rounded-full border px-3 py-1.5 border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10">
                <TriangleAlert size={13} className="text-red-600 dark:text-red-400" />
                <span className="text-xs font-bold text-red-600 dark:text-red-400">ERREUR</span>
              </div>
            )}
          </div>

          <div className="rounded-2xl overflow-hidden bg-black aspect-[4/3] relative">
            {connected ? (
              <img src={streamUrl} alt="Vue du robot" className="w-full h-full object-contain" />
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-slate-500">
                <Video size={34} /><span className="text-xs">Robot hors ligne</span>
              </div>
            )}
          </div>

          <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-4">
            <div className="relative w-24 h-24 shrink-0">
              <svg viewBox="0 0 100 100" className="w-24 h-24 -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" className="stroke-slate-100 dark:stroke-slate-800" strokeWidth="10" />
                <circle
                  cx="50" cy="50" r="42" fill="none" stroke="#2563eb" strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={`${circumference * progressRatio} ${circumference}`}
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xl font-bold text-slate-900 dark:text-white">{currentView}</span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">sur {totalViews || '?'}</span>
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-[15px] text-slate-900 dark:text-white">{Math.max(0, totalViews - currentView)} vues restantes</div>
              <div className="flex items-center gap-1.5 mt-2 text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                <Check size={14} />{captureCount} photo{captureCount > 1 ? 's' : ''} enregistrée{captureCount > 1 ? 's' : ''}
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100 dark:border-slate-800">
              <span className="text-sm text-slate-500 dark:text-slate-400">Robot</span>
              <span className="text-sm font-semibold text-slate-900 dark:text-white">{battery != null ? `Batterie ${battery} %` : '—'}</span>
            </div>
            <div className="flex items-center justify-between px-4 py-2.5">
              <span className="text-sm text-slate-500 dark:text-slate-400">Trajet</span>
              <span className={`text-sm font-semibold ${obstacle ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}`}>{obstacle ? 'Obstacle détecté' : 'Dégagé'}</span>
            </div>
          </div>

          {inspection.error && (
            <div className="rounded-xl border px-4 py-3 text-sm border-red-200 bg-red-50 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-400">
              {inspection.error}
            </div>
          )}

          <div className="flex flex-col gap-2.5 mt-1">
            <button
              onClick={() => { void handleStopInspection() }}
              disabled={busy}
              className="w-full py-3.5 rounded-2xl font-semibold flex items-center justify-center gap-2 border-2 border-red-200 bg-red-50 text-red-600 dark:border-red-500/40 dark:bg-red-500/15 dark:text-red-400 disabled:opacity-40"
            >
              <Square size={17} />Tout arrêter
            </button>
            <Link to="/pilotage" className="text-center text-sm font-semibold py-1 text-blue-600 dark:text-blue-400">
              Reprendre la main (technicien)
            </Link>
          </div>
        </div>
      )}

      {screen === 'report' && inspection && (
        <div className="flex-1 flex flex-col gap-3">
          <div>
            <button onClick={handleNewInspection} className="print:hidden flex items-center gap-2 text-sm mb-3 text-slate-500 dark:text-slate-400">
              <ArrowLeft size={17} />Rapport d&rsquo;inspection
            </button>
            <div className="text-2xl font-bold tracking-wide text-slate-900 dark:text-white">{inspection.registration}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">{inspection.route_name}</div>
            <div className="text-xs mt-0.5 text-slate-400 dark:text-slate-500">
              {formatDateTime(inspection.started_at)} · {formatDuration(inspection.started_at, inspection.completed_at ?? undefined)}
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-3.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Vues capturées</span>
            <span className="text-xl font-bold text-slate-900 dark:text-white">{captureCount} / {totalViews || captureCount}</span>
          </div>

          <div className="bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800 p-4">
            <div className="font-semibold mb-3 text-slate-900 dark:text-white">Photos par zone</div>
            {captureCount === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">Aucune photo enregistrée pour cette inspection.</p>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {inspection.captures?.map(capture => (
                  <div key={capture.id} className="relative rounded-lg overflow-hidden aspect-[4/3] bg-slate-200 dark:bg-slate-800">
                    <img src={`${apiBase}${capture.image_url}`} alt={zoneLabel(capture.zone)} className="w-full h-full object-cover" />
                    <span className="absolute left-1 bottom-1 text-white text-[9px] font-semibold rounded px-1.5 py-0.5 bg-black/60">
                      {zoneLabel(capture.zone)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="print:hidden flex gap-2.5 mt-1">
            <button
              onClick={() => window.print()}
              className="flex-1 py-3.5 rounded-2xl font-semibold text-white flex items-center justify-center gap-2 bg-blue-600"
            >
              <FileText size={17} />Exporter le PDF
            </button>
            <button
              onClick={handleNewInspection}
              className="px-5 py-3.5 rounded-2xl font-semibold border-2 border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300"
            >
              Nouvelle
            </button>
          </div>
        </div>
      )}

      {screen === 'live' && !inspection && (
        <div className="flex-1 flex items-center justify-center gap-2 py-16 text-slate-400 dark:text-slate-500">
          <Radar size={18} />Aucune inspection en cours.
        </div>
      )}
    </div>
  )
}
