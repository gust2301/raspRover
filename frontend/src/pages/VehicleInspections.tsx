import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, Car, CheckCircle,
  ChevronRight, CircleDot, House, Map, MapPin, Play, RotateCcw, Save,
  Square, Trash2,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl, getRobotStreamUrl } from '../lib/robotTransport'
import { ZONES } from '../data/zones'
import InspectionRunner from '../components/InspectionRunner'

type Phase = 'welcome' | 'mapping' | 'learning' | 'inspection'
type Direction = 'forward' | 'backward' | 'left' | 'right'
type FinishStage = null | 'saving' | 'stopping' | 'loading' | 'home'

interface SlamMap {
  image: string
  width: number
  height: number
  resolution_m: number
  origin_x: number
  origin_y: number
}

interface Pose {
  x: number
  y: number
  yaw: number
  position_stddev_m?: number
  yaw_stddev_rad?: number
}
interface LearnedPoint extends Pose { pan: number; tilt: number; zone: string }
interface SavedMap { name: string }
interface RouteSummary { id: string; name: string; map_name: string; waypoint_count: number }

function Step({ number, title, active, done }: { number: number; title: string; active: boolean; done: boolean }) {
  return <div className={`flex items-center gap-2 ${active ? 'text-blue-600 dark:text-blue-300' : done ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-600'}`}>
    <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border ${active ? 'bg-blue-600 border-blue-400 text-white' : done ? 'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/15 dark:border-emerald-500/40' : 'bg-slate-100 border-slate-200 dark:bg-slate-900 dark:border-slate-700'}`}>{done ? '✓' : number}</span>
    <span className="text-xs font-medium hidden sm:inline">{title}</span>
  </div>
}

function DrivePad({ connected, onMove, onStop }: {
  connected: boolean
  onMove: (direction: Direction) => void
  onStop: () => void
}) {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const [active, setActive] = useState<Direction | null>(null)

  const stop = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
    setActive(null)
    onStop()
  }, [onStop])

  const start = useCallback((direction: Direction) => {
    if (!connected) return
    if (timer.current) window.clearInterval(timer.current)
    setActive(direction)
    onMove(direction)
    timer.current = window.setInterval(() => onMove(direction), 150)
  }, [connected, onMove])

  useEffect(() => {
    const keyDirection: Record<string, Direction> = {
      ArrowUp: 'forward', w: 'forward', ArrowDown: 'backward', s: 'backward',
      ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right',
    }
    const down = (event: KeyboardEvent) => {
      if (event.repeat || !keyDirection[event.key]) return
      event.preventDefault(); start(keyDirection[event.key])
    }
    const up = (event: KeyboardEvent) => {
      if (!keyDirection[event.key]) return
      event.preventDefault(); stop()
    }
    const release = () => {
      if (timer.current) stop()
    }
    window.addEventListener('keydown', down); window.addEventListener('keyup', up)
    window.addEventListener('pointerup', release); window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', down); window.removeEventListener('keyup', up)
      window.removeEventListener('pointerup', release); window.removeEventListener('blur', release)
      if (timer.current) {
        window.clearInterval(timer.current)
        onStop()
      }
    }
  }, [onStop, start, stop])

  const button = (direction: Direction, icon: React.ReactNode, area: string) => <button
    style={{ gridArea: area }} onPointerDown={() => start(direction)} onPointerUp={stop}
    onPointerLeave={stop} disabled={!connected}
    className={`rounded-xl flex items-center justify-center border select-none touch-none ${active === direction ? 'bg-blue-600 border-blue-400 text-white scale-95' : 'bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-700'} disabled:opacity-30`}>
    {icon}
  </button>

  return <div className="space-y-2">
    <p className="text-center text-[11px] text-slate-400 dark:text-slate-500">Pilotez avec les boutons ou les flèches du clavier</p>
    <div className="mx-auto grid grid-cols-3 grid-rows-3 gap-2 w-[190px] h-[190px]">
      {button('forward', <ArrowUp />, '1 / 2')}
      {button('left', <ArrowLeft />, '2 / 1')}
      <button style={{ gridArea: '2 / 2' }} onPointerDown={stop} className="rounded-xl bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 dark:bg-red-500/15 dark:border-red-500/40 dark:text-red-300 flex items-center justify-center"><Square size={20} /></button>
      {button('right', <ArrowRight />, '2 / 3')}
      {button('backward', <ArrowDown />, '3 / 2')}
    </div>
  </div>
}

function LiveCamera({ streamUrl }: { streamUrl: string }) {
  return <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-black overflow-hidden">
    <div className="px-4 py-3 border-b border-slate-800 bg-slate-900 flex items-center gap-2 text-sm text-white"><Camera size={15} /> Vue du rover</div>
    <img src={streamUrl} alt="Caméra du rover" className="w-full aspect-video object-contain" />
  </div>
}

function MapPanel({ map, pose, points = [] }: { map: SlamMap | null; pose: Pose | null; points?: LearnedPoint[] }) {
  if (!map) return <div className="min-h-72 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 flex items-center justify-center text-sm text-slate-400 dark:text-slate-500">
    <div className="text-center"><Map size={34} className="mx-auto mb-2 opacity-30" /><p>La carte apparaîtra dès les premières mesures lidar.</p></div>
  </div>
  const position = (point: Pose) => ({
    left: `${(point.x - map.origin_x) / map.resolution_m / map.width * 100}%`,
    top: `${100 - (point.y - map.origin_y) / map.resolution_m / map.height * 100}%`,
  })
  const maxWidth = 520 * map.width / map.height
  return <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-black overflow-auto p-3 flex justify-center">
    <div className="relative w-full" style={{ aspectRatio: `${map.width} / ${map.height}`, maxWidth: `min(100%, ${maxWidth}px)` }}>
      <img src={`data:image/png;base64,${map.image}`} className="absolute inset-0 w-full h-full" style={{ imageRendering: 'pixelated' }} alt="Carte du plateau" />
      {points.map((point, index) => <span key={index} style={position(point)} className="absolute -ml-3 -mt-3 w-6 h-6 rounded-full bg-emerald-500 border border-white text-white text-xs font-bold flex items-center justify-center">{index + 1}</span>)}
      {pose && <span style={position(pose)} className="absolute -ml-2 -mt-2 w-4 h-4 rounded-full bg-blue-500 border-2 border-white shadow-lg" title="Rover" />}
    </div>
  </div>
}

export default function VehicleInspections() {
  const connection = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(connection.robotIp)
  const streamUrl = getRobotStreamUrl(connection.robotIp)
  const connected = connection.status === 'connected'
  const [phase, setPhase] = useState<Phase>('welcome')
  const [slamMode, setSlamMode] = useState<'mapping' | 'navigation' | 'stopped'>('stopped')
  const [mapData, setMapData] = useState<SlamMap | null>(null)
  const [activeMap, setActiveMap] = useState<string | null>(null)
  const [pose, setPose] = useState<Pose | null>(null)
  const [savedMaps, setSavedMaps] = useState<SavedMap[]>([])
  const [routes, setRoutes] = useState<RouteSummary[]>([])
  const [points, setPoints] = useState<LearnedPoint[]>([])
  const [selectedZone, setSelectedZone] = useState<string>('front')
  const [plateauName, setPlateauName] = useState('plateau-principal')
  const [routeName, setRouteName] = useState('Test localisation — 4 points')
  const [quickTest, setQuickTest] = useState(true)
  const [busy, setBusy] = useState(false)
  const [finishStage, setFinishStage] = useState<FinishStage>(null)
  const [finishMessage, setFinishMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const refreshInFlight = useRef(false)
  const posePollInFlight = useRef(false)
  const mapDataRef = useRef<SlamMap | null>(null)

  useEffect(() => { mapDataRef.current = mapData }, [mapData])

  const refresh = useCallback(async () => {
    if (!connected || refreshInFlight.current) return
    refreshInFlight.current = true
    try {
      const statusResponse = await fetch(`${apiBase}/api/slam/status`)
      if (statusResponse.ok) {
        const status = await statusResponse.json()
        setSlamMode(status.mode ?? 'stopped'); setActiveMap(status.active_map ?? null); setPose(status.pose ?? null)
        if (status.running && (status.mode === 'mapping' || mapDataRef.current === null)) {
          const mapResponse = await fetch(`${apiBase}/api/slam/map`)
          if (mapResponse.ok) setMapData(await mapResponse.json())
        }
      }
      const [mapsResponse, routesResponse] = await Promise.all([
        fetch(`${apiBase}/api/slam/maps`), fetch(`${apiBase}/api/automotive/routes`),
      ])
      if (mapsResponse.ok) setSavedMaps((await mapsResponse.json()).maps ?? [])
      if (routesResponse.ok) setRoutes((await routesResponse.json()).routes ?? [])
    } catch { /* le poll suivant réessaiera */ }
    finally { refreshInFlight.current = false }
  }, [apiBase, connected])

  useEffect(() => {
    void refresh(); const timer = window.setInterval(() => { void refresh() }, 10000)
    return () => window.clearInterval(timer)
  }, [refresh])

  useEffect(() => {
    if (!connected || (phase !== 'learning' && phase !== 'inspection')) return
    let disposed = false
    const updatePose = async () => {
      if (posePollInFlight.current) return
      posePollInFlight.current = true
      try {
        const response = await fetch(`${apiBase}/api/slam/pose`)
        if (response.ok && !disposed) setPose(await response.json())
      } catch { /* la prochaine mesure réessaiera */ }
      finally { posePollInFlight.current = false }
    }
    void updatePose()
    const timer = window.setInterval(() => { void updatePose() }, 500)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [apiBase, connected, phase])

  const move = useCallback((direction: Direction) => connection.sendMove(direction, 0.28), [connection.sendMove])
  const stop = useCallback(() => connection.sendStop(), [connection.sendStop])

  async function request(path: string, body?: object) {
    const response = await fetch(`${apiBase}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    const data = await response.json()
    if (!response.ok || data.ok === false) throw new Error(data.error ?? 'Opération impossible')
    return data
  }

  async function startPlateauMapping() {
    setBusy(true); setError(null); setMapData(null)
    try { await request('/api/slam/start'); setPhase('mapping'); setNotice('Cartographie démarrée : faites le tour du plateau.') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function finishPlateau() {
    if (!plateauName.trim()) {
      setFinishMessage('Donnez un nom au plateau avant de continuer.')
      return
    }
    if (!pose) {
      setFinishMessage('La position du rover n’est pas encore disponible. Attendez quelques secondes sans déplacer le rover, puis réessayez.')
      return
    }
    const finalPose = { ...pose }
    let savedName: string | null = null
    setBusy(true); setError(null); setNotice(null); setFinishMessage(null)
    try {
      setFinishStage('saving'); setFinishMessage('1/4 — Sauvegarde de la carte du plateau…')
      const saved = await request('/api/slam/save', { name: plateauName })
      savedName = saved.name
      setFinishStage('stopping'); setFinishMessage(`2/4 — Carte « ${saved.name} » sauvegardée. Arrêt de la cartographie…`)
      await request('/api/slam/stop')
      setFinishStage('loading'); setFinishMessage('3/4 — Démarrage de Nav2 sur la nouvelle carte… Cela peut prendre jusqu’à 60 secondes sur la Pi.')
      await request('/api/slam/load', { name: saved.name, initial_pose: finalPose })
      setFinishStage('home'); setFinishMessage('4/4 — Enregistrement de cette position comme maison du rover…')
      await request('/api/slam/home')
      setActiveMap(saved.name); setPoints([]); setPhase('learning')
      setNotice('Plateau enregistré. Pilotez maintenant autour du véhicule de référence.')
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : 'Erreur inconnue'
      setFinishMessage(savedName
        ? `La carte « ${savedName} » est bien sauvegardée, mais la préparation de Nav2 a échoué : ${detail}`
        : `La sauvegarde du plateau a échoué : ${detail}`)
    } finally { setBusy(false); setFinishStage(null) }
  }

  async function loadPlateau(name: string) {
    setBusy(true); setError(null)
    try {
      await request('/api/slam/load', { name }); setActiveMap(name); setMapData(null); setPoints([]); setPhase('learning')
      setNotice('Plateau chargé. Placez un véhicule de référence et apprenez le parcours.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function deletePlateau(name: string) {
    if (!window.confirm(`Supprimer la carte « ${name} » ?`)) return
    setBusy(true); setError(null)
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
      setSavedMaps(current => current.filter(map => map.name !== name))
      setRoutes(current => current.filter(route => route.map_name !== name))
      setNotice(`Carte « ${name} » supprimée.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function prepareInspection(route: RouteSummary) {
    setBusy(true); setError(null)
    try {
      if (activeMap !== route.map_name || slamMode !== 'navigation') {
        await request('/api/slam/load', { name: route.map_name })
        setActiveMap(route.map_name); setMapData(null)
      }
      setPhase('inspection')
      setNotice(`Plateau « ${route.map_name} » prêt pour l’inspection.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function recordPoint() {
    if (!pose || !activeMap || busy) return
    if (quickTest && points.length >= 4) {
      setNotice('Les quatre points du test sont déjà enregistrés.')
      return
    }
    setBusy(true); setError(null); setNotice('Validation du trajet par Nav2, sans déplacement…')
    try {
      const captured = await request('/api/automotive/points/capture', { map_name: activeMap, zone: selectedZone })
      const candidate = captured.point as LearnedPoint
      await request('/api/automotive/routes/validate', { map_name: activeMap, waypoints: [...points, candidate] })
      setPoints(current => [...current, candidate])
      const next = ZONES[(ZONES.findIndex(([value]) => value === selectedZone) + 1) % ZONES.length][0]
      const warning = captured.quality?.warning ? ` ${captured.quality.warning}.` : ''
      setSelectedZone(next); setNotice(`Point « ${ZONES.find(([value]) => value === selectedZone)?.[1]} » validé par Nav2 et enregistré.${warning}`)
    } catch (reason) {
      setNotice(null)
      setError(`Point non enregistré : ${reason instanceof Error ? reason.message : 'trajet Nav2 invalide'}`)
    } finally { setBusy(false) }
  }

  async function saveRoute() {
    if (!activeMap || points.length < 2) return
    if (quickTest && points.length !== 4) {
      setError(`Le test rapide demande exactement 4 points (${points.length}/4).`)
      return
    }
    setBusy(true); setError(null)
    try {
      await request('/api/automotive/routes', { name: routeName, map_name: activeMap, waypoints: points })
      setPhase('inspection'); setNotice('Parcours prêt pour les inspections automatiques.'); await refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  const cameraPan = Number(connection.lastStatus?.pan ?? 0)
  const cameraTilt = Number(connection.lastStatus?.tilt ?? 0)
  const adjustCamera = (pan: number, tilt: number) => connection.sendPanTilt(pan, tilt)

  return <div className="space-y-5 max-w-7xl mx-auto">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3"><div className="w-11 h-11 rounded-xl bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center"><Car className="text-blue-600 dark:text-blue-400" /></div>
        <div><h1 className="text-xl font-semibold text-slate-900 dark:text-white">Inspection automobile</h1><p className="text-sm text-slate-400 dark:text-slate-500">Configuration guidée du plateau et du parcours automatique.</p></div></div>
      <div className="flex items-center gap-3"><Step number={1} title="Plateau" active={phase === 'mapping'} done={phase === 'learning' || phase === 'inspection'} /><ChevronRight size={14} className="text-slate-300 dark:text-slate-700" /><Step number={2} title="Parcours" active={phase === 'learning'} done={phase === 'inspection'} /><ChevronRight size={14} className="text-slate-300 dark:text-slate-700" /><Step number={3} title="Inspection" active={phase === 'inspection'} done={false} /></div>
    </header>

    {error && <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">{error}</div>}
    {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300 flex gap-2"><CheckCircle size={17} />{notice}</div>}

    {phase === 'welcome' && <div className="space-y-5">
      <section className="rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white dark:border-blue-500/20 dark:from-blue-500/10 dark:to-slate-900 p-6">
        <p className="text-xs uppercase tracking-widest text-blue-600 dark:text-blue-400 mb-2">Première utilisation</p><h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2">Configurez d’abord votre plateau</h2>
        <p className="text-slate-500 dark:text-slate-400 max-w-2xl mb-5">Vous allez piloter le rover autour du parking pour créer sa carte. À la fin, ramenez-le à son emplacement de départ : cette position deviendra sa maison.</p>
        <button onClick={startPlateauMapping} disabled={!connected || busy} className="px-5 py-3 rounded-xl bg-blue-600 text-white font-medium disabled:opacity-40"><Play size={17} className="inline mr-2" />Créer un nouveau plateau</button>
      </section>
      {!!savedMaps.length && <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-5"><h3 className="text-slate-900 dark:text-white font-medium mb-1">Plateaux déjà enregistrés</h3><p className="text-sm text-slate-400 dark:text-slate-500 mb-4">Vous pouvez apprendre un nouveau parcours sur une carte existante.</p><div className="flex flex-wrap gap-2">{savedMaps.map(map => <div key={map.name} className="flex rounded-lg overflow-hidden"><button onClick={() => { void loadPlateau(map.name) }} disabled={busy} className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-sm text-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-200"><Map size={14} className="inline mr-2" />{map.name}</button><button onClick={() => { void deletePlateau(map.name) }} disabled={busy} className="px-3 bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-500/15 dark:text-red-400 dark:hover:bg-red-500/25" title={`Supprimer ${map.name}`}><Trash2 size={14} /></button></div>)}</div></section>}
      {!!routes.length && <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-5"><h3 className="text-slate-900 dark:text-white font-medium mb-3">Parcours prêts</h3><div className="flex flex-wrap gap-2">{routes.map(route => <button key={route.id} onClick={() => { void prepareInspection(route) }} disabled={busy} className="px-4 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:border-emerald-500/30 dark:text-emerald-300 disabled:opacity-40">{route.name} · {route.waypoint_count} vues</button>)}</div></section>}
    </div>}

    {phase === 'mapping' && <div className="space-y-5">
      <section className="rounded-xl border border-blue-200 bg-blue-50 dark:border-blue-500/30 dark:bg-blue-500/5 p-4"><h2 className="text-slate-900 dark:text-white font-semibold">Étape 1 — Faites le tour complet du plateau</h2><p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Passez dans toutes les allées. Quand la carte est complète, revenez à l’endroit où le rover devra rentrer après chaque inspection.</p></section>
      <div className="grid lg:grid-cols-[1fr_320px] gap-5"><div className="space-y-5"><LiveCamera streamUrl={streamUrl} /><MapPanel map={mapData} pose={pose} /></div><aside className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-5 space-y-5"><DrivePad connected={connected && !busy} onMove={move} onStop={stop} /><div className="border-t border-slate-200 dark:border-slate-800 pt-4"><label className="text-xs text-slate-500 dark:text-slate-400">Nom du plateau</label><input value={plateauName} onChange={event => { setPlateauName(event.target.value); setFinishMessage(null) }} disabled={busy} className="w-full mt-1 bg-slate-100 dark:bg-slate-800 rounded-lg px-3 py-2 text-slate-900 dark:text-white disabled:opacity-50" /><div className="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20 text-xs text-amber-700 dark:text-amber-300 flex gap-2"><House size={15} className="shrink-0" />Ramenez d’abord le rover à sa future maison.</div><div className={`mt-3 flex items-center gap-2 text-xs ${pose ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}><CircleDot size={13} />{pose ? `Position disponible : ${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : 'Attente de la position du rover…'}</div>{finishMessage && <div className={`mt-3 p-3 rounded-lg border text-xs ${finishStage ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-500/10 dark:border-blue-500/30 dark:text-blue-300' : 'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/30 dark:text-amber-300'}`}>{finishStage && <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse mr-2" />}{finishMessage}</div>}<button onClick={() => { void finishPlateau() }} disabled={busy} className="w-full mt-3 py-3 rounded-lg bg-emerald-600 text-white disabled:opacity-60"><Save size={15} className="inline mr-2" />{finishStage ? 'Préparation en cours…' : 'Terminer et enregistrer'}</button></div></aside></div>
    </div>}

    {phase === 'learning' && <div className="space-y-5">
      <section className="rounded-xl border border-blue-200 bg-blue-50 dark:border-blue-500/30 dark:bg-blue-500/5 p-4"><h2 className="text-slate-900 dark:text-white font-semibold">Étape 2 — Apprenez le tour du véhicule de référence</h2><p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Pilotez autour du véhicule. À chaque vue importante, orientez la caméra, choisissez la zone puis enregistrez le point. Les coordonnées sont capturées automatiquement.</p></section>
      <div className="grid xl:grid-cols-[1fr_360px] gap-5"><div className="space-y-5"><LiveCamera streamUrl={streamUrl} /><MapPanel map={mapData} pose={pose} points={points} /></div><aside className="space-y-5"><section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-4"><DrivePad connected={connected && !busy} onMove={move} onStop={stop} /></section><section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-4 space-y-3"><p className="text-sm font-medium text-slate-900 dark:text-white">Orienter la caméra</p><div className="grid grid-cols-3 gap-2 w-40 mx-auto"><button onClick={() => adjustCamera(cameraPan, cameraTilt + 8)} className="col-start-2 p-2 bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-200"><ArrowUp className="mx-auto" size={17} /></button><button onClick={() => adjustCamera(cameraPan - 10, cameraTilt)} className="p-2 bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-200"><ArrowLeft className="mx-auto" size={17} /></button><button onClick={() => adjustCamera(0, 0)} className="p-2 bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-200"><RotateCcw className="mx-auto" size={17} /></button><button onClick={() => adjustCamera(cameraPan + 10, cameraTilt)} className="p-2 bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-200"><ArrowRight className="mx-auto" size={17} /></button><button onClick={() => adjustCamera(cameraPan, cameraTilt - 8)} className="col-start-2 p-2 bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-200"><ArrowDown className="mx-auto" size={17} /></button></div><p className="text-center text-[11px] text-slate-400 dark:text-slate-500">Pan {cameraPan.toFixed(0)}° · Tilt {cameraTilt.toFixed(0)}°</p></section><section className="rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/5 p-4 space-y-3"><label className="text-xs text-slate-500 dark:text-slate-400">Zone visible actuellement</label><select value={selectedZone} onChange={event => setSelectedZone(event.target.value)} className="w-full bg-white border border-slate-300 dark:bg-slate-800 dark:border-transparent rounded-lg px-3 py-2 text-slate-900 dark:text-white">{ZONES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><div className="text-xs rounded-lg px-3 py-2 bg-slate-100 dark:bg-slate-800/70 text-slate-500 dark:text-slate-400">{pose?.position_stddev_m != null ? `Estimation AMCL (information) : ±${Math.round(pose.position_stddev_m * 100)} cm · ±${Math.round((pose.yaw_stddev_rad ?? 0) * 180 / Math.PI)}°` : 'Estimation AMCL en cours…'}</div><button onClick={() => { void recordPoint() }} disabled={!pose || busy || (quickTest && points.length >= 4)} className="w-full py-3 rounded-lg bg-emerald-600 text-white font-medium disabled:opacity-40"><CircleDot size={17} className="inline mr-2" />{busy ? 'Arrêt et mesure stable…' : quickTest ? `Enregistrer (${points.length}/4)` : 'Enregistrer ce point'}</button></section></aside></div>
      <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50 p-5"><div className="flex flex-wrap justify-between gap-3 mb-4"><div><h3 className="text-slate-900 dark:text-white font-medium">Points enregistrés ({points.length})</h3><p className="text-xs text-slate-400 dark:text-slate-500">Ils seront rejoués dans cet ordre.</p><label className="mt-2 flex items-center gap-2 text-xs text-blue-600 dark:text-blue-300"><input type="checkbox" checked={quickTest} onChange={event => { setQuickTest(event.target.checked); if (event.target.checked) setRouteName('Test localisation — 4 points') }} className="accent-blue-500" />Test rapide limité à 4 points</label></div><div className="flex gap-2"><input value={routeName} onChange={event => setRouteName(event.target.value)} className="bg-slate-100 dark:bg-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-white" /><button onClick={saveRoute} disabled={busy || points.length < 2 || (quickTest && points.length !== 4)} className="px-4 py-2 rounded-lg bg-blue-600 text-white disabled:opacity-40"><Save size={15} className="inline mr-1" />{quickTest ? `Enregistrer le test (${points.length}/4)` : 'Enregistrer le parcours'}</button></div></div><div className="flex flex-wrap gap-2">{points.map((point, index) => <div key={index} className="px-3 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs text-slate-600 dark:text-slate-300 flex items-center gap-2"><MapPin size={13} className="text-emerald-600 dark:text-emerald-400" /><span>{index + 1}. {ZONES.find(([value]) => value === point.zone)?.[1]}</span><button onClick={() => setPoints(current => current.filter((_, itemIndex) => itemIndex !== index))} className="text-red-500 dark:text-red-400 ml-1"><Trash2 size={13} /></button></div>)}</div></section>
    </div>}

    {phase === 'inspection' && <InspectionRunner onBackToSetup={() => setPhase('welcome')} />}
  </div>
}
