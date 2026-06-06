import { useEffect, useState } from 'react'
import { RotateCcw, Save, Settings as SettingsIcon, SlidersHorizontal, WifiOff, Crosshair } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl } from '../lib/robotTransport'

const ZONE_LABEL: Record<string, string> = {
  front: 'Avant',
  right: 'Droite',
  rear: 'Arrière',
  left: 'Gauche',
}

const ZONES = ['front', 'right', 'rear', 'left'] as const

function ZoneDistance({ label, cm }: { label: string; cm: number | null | undefined }) {
  const active = typeof cm === 'number'
  return (
    <div className={`rounded-lg border px-3 py-2 ${active ? 'border-cyan-500/30 bg-cyan-500/5' : 'border-slate-800 bg-slate-900/40'}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-sm ${active ? 'text-cyan-300' : 'text-slate-600'}`}>
        {active ? `${cm.toFixed(0)} cm` : '--'}
      </div>
    </div>
  )
}

export default function Settings() {
  const conn = useSharedRobotConnection()
  const connected = conn.status === 'connected'
  const calibration = conn.lastStatus?.lidar_calibration
  const offset = conn.lastStatus?.lidar_angle_offset_deg ?? calibration?.angle_offset_deg ?? 0
  const inverted = conn.lastStatus?.lidar_invert_angles ?? calibration?.invert_angles ?? false
  const debugPoints = conn.lastStatus?.lidar_debug_points ?? calibration?.debug_points ?? []
  const zones = calibration?.zones ?? {
    front: conn.lastStatus?.lidar_front_cm,
    right: conn.lastStatus?.lidar_right_cm,
    rear: conn.lastStatus?.lidar_rear_cm,
    left: conn.lastStatus?.lidar_left_cm,
  }
  const [autoCalibrating, setAutoCalibrating] = useState(false)
  const [autoCalibMsg, setAutoCalibMsg] = useState<string | null>(null)

  const handleAutoCalibrate = async () => {
    setAutoCalibrating(true)
    setAutoCalibMsg(null)
    try {
      const res = await fetch(`${getRobotApiUrl(conn.robotIp)}/api/lidar/calibrate/auto`, { method: 'POST' })
      const data = await res.json() as { ok?: boolean; angle_offset_deg?: number; error?: string }
      if (data.ok) {
        setAutoCalibMsg(`✓ Offset appliqué : ${data.angle_offset_deg?.toFixed(0)}° — sauvegardé`)
        await conn.refreshLidarCalibration()
      } else {
        setAutoCalibMsg(`Erreur : ${data.error ?? 'inconnu'}`)
      }
    } catch {
      setAutoCalibMsg('Erreur réseau')
    } finally {
      setAutoCalibrating(false)
    }
  }

  const nearest = ZONES
    .map(zone => ({ zone, cm: zones?.[zone] }))
    .filter((entry): entry is { zone: typeof ZONES[number]; cm: number } => typeof entry.cm === 'number')
    .sort((a, b) => a.cm - b.cm)[0]

  useEffect(() => {
    if (!connected) return
    void conn.refreshLidarCalibration()
    const id = setInterval(() => {
      void conn.refreshLidarCalibration()
    }, 1000)
    return () => clearInterval(id)
  }, [conn.refreshLidarCalibration, connected])

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
          <SettingsIcon size={22} className="text-blue-300" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Paramètres</h1>
          <p className="text-sm text-slate-500">Calibration et réglages runtime du robot.</p>
        </div>
      </div>

      <section className="rounded-xl border border-slate-800 bg-[#0f1629] p-5">
        <div className="flex items-center justify-between gap-3 mb-5">
          <div className="flex items-center gap-2">
            <SlidersHorizontal size={17} className="text-cyan-300" />
            <h2 className="text-white font-semibold">Calibration LIDAR</h2>
          </div>
          <div className={`text-xs font-mono ${connected ? 'text-emerald-400' : 'text-amber-400'}`}>
            {connected ? 'ONLINE' : 'OFFLINE'}
          </div>
        </div>

        {!connected && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            <WifiOff size={14} />
            Connecte-toi au robot pour modifier la calibration en temps réel.
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
          <div className="space-y-4">

            {/* Auto-calibrage */}
            <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 px-4 py-3 space-y-2">
              <div className="text-xs text-blue-300 font-medium">Calibrage automatique</div>
              <p className="text-[11px] text-slate-400">
                Placez le robot à ~50 cm face à un obstacle, puis cliquez.
                L'avant du robot sera aligné sur l'obstacle détecté.
              </p>
              <button
                onClick={handleAutoCalibrate}
                disabled={!connected || autoCalibrating}
                className="w-full h-10 rounded-lg border border-blue-500/50 bg-blue-600/20 text-sm text-blue-300 flex items-center justify-center gap-2 hover:bg-blue-600/30 disabled:opacity-40"
              >
                <Crosshair size={15} />
                {autoCalibrating ? 'Calibrage…' : 'Calibrer l\'avant automatiquement'}
              </button>
              {autoCalibMsg && (
                <div className={`text-[11px] font-mono ${autoCalibMsg.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}`}>
                  {autoCalibMsg}
                </div>
              )}
            </div>

            {/* Réglage manuel */}
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">Offset actuel</span>
              <span className="text-xl font-bold font-mono text-cyan-300">{offset.toFixed(0)}°</span>
            </div>

            <div className="grid grid-cols-4 gap-2">
              {[-15, -5, 5, 15].map(delta => (
                <button
                  key={delta}
                  onClick={() => conn.adjustLidarOffset(delta)}
                  disabled={!connected}
                  className="h-10 rounded-lg border border-slate-700 bg-slate-800 text-xs font-mono text-slate-200 hover:bg-slate-700 disabled:opacity-40"
                >
                  {delta > 0 ? `+${delta}°` : `${delta}°`}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => conn.setLidarCalibration({ angle_offset_deg: offset, invert_angles: inverted, save: true })}
                disabled={!connected}
                className="h-10 rounded-lg border border-emerald-500/40 bg-emerald-600/15 text-xs text-emerald-300 flex items-center justify-center gap-1.5 hover:bg-emerald-600/25 disabled:opacity-40"
              >
                <Save size={14} />
                Sauvegarder
              </button>
              <button
                onClick={() => conn.setLidarCalibration({ angle_offset_deg: 0, invert_angles: false })}
                disabled={!connected}
                className="h-10 rounded-lg border border-slate-700 bg-slate-800 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-40"
              >
                <RotateCcw size={14} className="inline mr-1" />
                Reset
              </button>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs text-slate-400">
              Obstacle le plus proche :{' '}
              <span className="font-mono text-cyan-300">
                {nearest ? `${ZONE_LABEL[nearest.zone]} — ${nearest.cm.toFixed(0)} cm` : '--'}
              </span>
            </div>
          </div>

          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <ZoneDistance label="Avant" cm={zones?.front} />
              <ZoneDistance label="Droite" cm={zones?.right} />
              <ZoneDistance label="Arrière" cm={zones?.rear} />
              <ZoneDistance label="Gauche" cm={zones?.left} />
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/60 overflow-hidden">
              <div className="grid grid-cols-4 gap-2 px-3 py-2 text-[10px] uppercase text-slate-500 border-b border-slate-800">
                <span>Brut</span>
                <span>Corr.</span>
                <span>Zone</span>
                <span className="text-right">cm</span>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {debugPoints.length > 0 ? debugPoints.slice(0, 18).map((p, idx) => (
                  <div key={`${p.raw_angle}-${p.corrected_angle}-${idx}`} className="grid grid-cols-4 gap-2 px-3 py-1.5 text-[11px] font-mono text-slate-400 border-b border-slate-900 last:border-b-0">
                    <span>{p.raw_angle.toFixed(0)}°</span>
                    <span>{p.corrected_angle.toFixed(0)}°</span>
                    <span className={p.zone === 'front' ? 'text-red-300' : p.zone === 'right' ? 'text-cyan-300' : p.zone === 'left' ? 'text-blue-300' : 'text-slate-500'}>
                      {ZONE_LABEL[p.zone] ?? p.zone}
                    </span>
                    <span className="text-right">{p.distance_cm.toFixed(0)}</span>
                  </div>
                )) : (
                  <div className="px-3 py-6 text-center text-xs text-slate-600">
                    Aucune mesure LIDAR disponible
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
