import { useCallback, useEffect, useState } from 'react'
import { Camera, Car, CheckCircle, MapPin, Play, Save, Square, Trash2 } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl, getRobotStreamUrl } from '../lib/robotTransport'

interface SlamMap {
  image: string
  width: number
  height: number
  resolution_m: number
  origin_x: number
  origin_y: number
}

interface LearnedPoint {
  x: number
  y: number
  yaw: number
  pan: number
  tilt: number
  zone: string
}

interface RouteSummary {
  id: string
  name: string
  map_name: string
  waypoint_count: number
}

interface CaptureRecord {
  id: string
  zone: string
  image_url: string
}

interface Inspection {
  id: string
  registration: string
  route_name: string
  status: string
  current_waypoint?: number | null
  error?: string | null
  captures?: CaptureRecord[]
}

const ZONES = [
  ['front', 'Avant'], ['front_left', 'Avant gauche'], ['left', 'Côté gauche'],
  ['rear_left', 'Arrière gauche'], ['rear', 'Arrière'], ['rear_right', 'Arrière droit'],
  ['right', 'Côté droit'], ['front_right', 'Avant droit'], ['wheel', 'Roue'],
]

const STATUS_LABEL: Record<string, string> = {
  starting: 'Préparation', navigating: 'Navigation', capturing: 'Prise de photo',
  returning_home: 'Retour à la maison', completed: 'Terminée', cancelled: 'Annulée', error: 'Erreur',
}

export default function VehicleInspections() {
  const connection = useSharedRobotConnection()
  const apiBase = getRobotApiUrl(connection.robotIp)
  const streamUrl = getRobotStreamUrl(connection.robotIp)
  const [mapData, setMapData] = useState<SlamMap | null>(null)
  const [activeMap, setActiveMap] = useState<string | null>(null)
  const [pose, setPose] = useState<{ x: number; y: number; yaw: number } | null>(null)
  const [routes, setRoutes] = useState<RouteSummary[]>([])
  const [selectedRoute, setSelectedRoute] = useState('')
  const [points, setPoints] = useState<LearnedPoint[]>([])
  const [routeName, setRouteName] = useState('Parcours place 1')
  const [registration, setRegistration] = useState('')
  const [vehicleLabel, setVehicleLabel] = useState('')
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (connection.status !== 'connected') return
    try {
      const statusResponse = await fetch(`${apiBase}/api/slam/status`)
      const status = await statusResponse.json()
      setActiveMap(status.active_map ?? null)
      setPose(status.pose ?? null)
      if (status.mode === 'navigation') {
        const mapResponse = await fetch(`${apiBase}/api/slam/map`)
        if (mapResponse.ok) setMapData(await mapResponse.json())
      }
      const routeResponse = await fetch(`${apiBase}/api/automotive/routes`)
      const routeData = await routeResponse.json()
      if (routeResponse.ok) setRoutes(routeData.routes ?? [])
      if (inspection) {
        const inspectionResponse = await fetch(`${apiBase}/api/automotive/inspections/${inspection.id}`)
        const inspectionData = await inspectionResponse.json()
        if (inspectionResponse.ok) setInspection(inspectionData.inspection)
      }
    } catch { /* le prochain poll réessaiera */ }
  }, [apiBase, connection.status, inspection?.id])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => window.clearInterval(timer)
  }, [refresh])

  function addPoint(event: React.MouseEvent<HTMLDivElement>) {
    if (!mapData || !activeMap) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const pixelX = (event.clientX - bounds.left) / bounds.width * mapData.width
    const pixelY = (1 - (event.clientY - bounds.top) / bounds.height) * mapData.height
    setPoints(current => [...current, {
      x: mapData.origin_x + pixelX * mapData.resolution_m,
      y: mapData.origin_y + pixelY * mapData.resolution_m,
      yaw: 0,
      pan: Number(connection.lastStatus?.pan ?? 0),
      tilt: Number(connection.lastStatus?.tilt ?? 0),
      zone: ZONES[current.length % ZONES.length][0],
    }])
  }

  function addCurrentPose() {
    if (!pose) return
    setPoints(current => [...current, {
      ...pose,
      pan: Number(connection.lastStatus?.pan ?? 0),
      tilt: Number(connection.lastStatus?.tilt ?? 0),
      zone: ZONES[current.length % ZONES.length][0],
    }])
  }

  function updatePoint(index: number, values: Partial<LearnedPoint>) {
    setPoints(current => current.map((point, pointIndex) => pointIndex === index ? { ...point, ...values } : point))
  }

  async function saveRoute() {
    if (!activeMap || points.length < 2) return
    setBusy(true); setError(null)
    try {
      const response = await fetch(`${apiBase}/api/automotive/routes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: routeName, map_name: activeMap, waypoints: points }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error ?? 'Enregistrement impossible')
      setSelectedRoute(data.route.id)
      setNotice('Parcours d’inspection enregistré')
      await refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function startInspection() {
    if (!selectedRoute || !registration.trim()) return
    setBusy(true); setError(null)
    try {
      const response = await fetch(`${apiBase}/api/automotive/inspections/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ route_id: selectedRoute, registration, label: vehicleLabel }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error ?? 'Démarrage impossible')
      setInspection(data.inspection)
      setNotice('Inspection automatique démarrée')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Erreur') }
    finally { setBusy(false) }
  }

  async function stopInspection() {
    await fetch(`${apiBase}/api/automotive/inspections/stop`, { method: 'POST' })
    await refresh()
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center"><Car className="text-blue-400" size={21} /></div>
        <div><h1 className="text-xl font-semibold text-white">Inspection automobile</h1>
          <p className="text-xs text-slate-500">Apprendre une place, inspecter automatiquement, puis rentrer à la maison.</p></div>
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300 flex gap-2"><CheckCircle size={17} />{notice}</div>}

      <div className="grid xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,1fr)] gap-5">
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-4">
          <div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold text-white">1. Apprentissage du parcours</h2>
            <p className="text-xs text-slate-500">Carte active : {activeMap ?? 'chargez une carte depuis Carte SLAM'}</p></div>
            <button onClick={addCurrentPose} disabled={!pose} className="px-3 py-2 rounded-lg bg-slate-800 text-xs text-slate-200 disabled:opacity-40"><MapPin size={13} className="inline mr-1" />Position actuelle</button>
          </div>
          <div className="relative min-h-80 flex items-center justify-center rounded-lg bg-slate-950 overflow-hidden">
            {mapData ? <div onClick={addPoint} className="relative w-full max-w-2xl cursor-crosshair">
              <img src={`data:image/png;base64,${mapData.image}`} className="block w-full" style={{ imageRendering: 'pixelated' }} alt="Carte de la place" />
              {points.map((point, index) => {
                const left = (point.x - mapData.origin_x) / mapData.resolution_m / mapData.width * 100
                const top = 100 - (point.y - mapData.origin_y) / mapData.resolution_m / mapData.height * 100
                return <span key={index} className="absolute -ml-3 -mt-3 w-6 h-6 rounded-full bg-blue-500 border border-white text-white text-xs flex items-center justify-center" style={{ left: `${left}%`, top: `${top}%` }}>{index + 1}</span>
              })}
            </div> : <p className="text-sm text-slate-500">Nav2 et une carte enregistrée doivent être actifs.</p>}
          </div>
          <div className="space-y-2 max-h-64 overflow-auto">
            {points.map((point, index) => <div key={index} className="grid grid-cols-[2rem_1fr_repeat(3,5rem)_2rem] gap-2 items-center text-xs">
              <span className="text-blue-400 font-bold">{index + 1}</span>
              <select value={point.zone} onChange={event => updatePoint(index, { zone: event.target.value })} className="bg-slate-800 rounded px-2 py-2 text-slate-200">{ZONES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
              <input title="Orientation du rover en degrés" type="number" value={Math.round(point.yaw * 180 / Math.PI)} onChange={event => updatePoint(index, { yaw: Number(event.target.value) * Math.PI / 180 })} className="bg-slate-800 rounded px-2 py-2 text-slate-200" />
              <input title="Pan caméra" type="number" value={point.pan} onChange={event => updatePoint(index, { pan: Number(event.target.value) })} className="bg-slate-800 rounded px-2 py-2 text-slate-200" />
              <input title="Tilt caméra" type="number" value={point.tilt} onChange={event => updatePoint(index, { tilt: Number(event.target.value) })} className="bg-slate-800 rounded px-2 py-2 text-slate-200" />
              <button onClick={() => setPoints(current => current.filter((_, i) => i !== index))} className="text-red-400"><Trash2 size={15} /></button>
            </div>)}
          </div>
          <div className="flex gap-2"><input value={routeName} onChange={event => setRouteName(event.target.value)} className="flex-1 bg-slate-800 rounded-lg px-3 py-2 text-sm text-white" placeholder="Nom du parcours" />
            <button onClick={saveRoute} disabled={busy || points.length < 2 || !activeMap} className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm disabled:opacity-40"><Save size={15} className="inline mr-1" />Enregistrer</button></div>
        </section>

        <div className="space-y-5">
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
            <h2 className="text-sm font-semibold text-white">2. Lancer une inspection automatique</h2>
            <select value={selectedRoute} onChange={event => setSelectedRoute(event.target.value)} className="w-full bg-slate-800 rounded-lg px-3 py-2 text-sm text-white"><option value="">Choisir un parcours</option>{routes.map(route => <option key={route.id} value={route.id}>{route.name} · {route.waypoint_count} points</option>)}</select>
            <input value={registration} onChange={event => setRegistration(event.target.value.toUpperCase())} placeholder="Immatriculation" className="w-full bg-slate-800 rounded-lg px-3 py-2 text-sm text-white" />
            <input value={vehicleLabel} onChange={event => setVehicleLabel(event.target.value)} placeholder="Modèle / référence (facultatif)" className="w-full bg-slate-800 rounded-lg px-3 py-2 text-sm text-white" />
            {inspection && <div className="rounded-lg bg-slate-950 p-3 text-xs space-y-1"><p className="text-white font-medium">{inspection.registration} · {inspection.route_name}</p><p className={inspection.status === 'error' ? 'text-red-400' : 'text-blue-400'}>{STATUS_LABEL[inspection.status] ?? inspection.status}{inspection.current_waypoint != null ? ` · point ${inspection.current_waypoint + 1}` : ''}</p>{inspection.error && <p className="text-red-400">{inspection.error}</p>}</div>}
            {inspection && ['starting', 'navigating', 'capturing', 'returning_home'].includes(inspection.status)
              ? <button onClick={stopInspection} className="w-full py-2 rounded-lg bg-red-600/30 text-red-300 text-sm"><Square size={15} className="inline mr-1" />Arrêter</button>
              : <button onClick={startInspection} disabled={busy || !selectedRoute || !registration.trim()} className="w-full py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-40"><Play size={15} className="inline mr-1" />Démarrer l’inspection</button>}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
            <div className="px-4 py-3 text-sm text-white flex gap-2"><Camera size={16} />Caméra d’inspection</div>
            <img src={streamUrl} alt="Flux du rover" className="w-full aspect-video object-contain bg-black" />
          </section>
          {!!inspection?.captures?.length && <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><h2 className="text-sm font-semibold text-white mb-3">Captures ({inspection.captures.length})</h2><div className="grid grid-cols-2 gap-2">{inspection.captures.map(capture => <div key={capture.id}><img src={`${apiBase}${capture.image_url}`} className="rounded aspect-video object-cover" /><p className="text-[11px] text-slate-400 mt-1">{capture.zone}</p></div>)}</div></section>}
        </div>
      </div>
    </div>
  )
}
