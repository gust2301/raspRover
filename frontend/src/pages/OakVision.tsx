import { useEffect, useRef, useState } from 'react'
import { ScanEye, Wifi, WifiOff, AlertCircle, Radar } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotApiUrl, getRobotOakStreamUrl } from '../lib/robotTransport'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OakDetection {
  label: string
  confidence: number
  cx: number
  cy: number
  xmin: number
  xmax: number
  ymin: number
  ymax: number
  x_mm: number
  y_mm: number
  z_mm: number
}

interface OakStatus {
  oak_available?: boolean
  oak_connected?: boolean
  oak_usb_speed?: string | null
  oak_error?: string | null
  oak_video_available?: boolean
  oak_detections?: OakDetection[]
  oak_depth_zones?: { left: boolean; center: boolean; right: boolean }
  oak_depth_cm?: { left: number | null; center: number | null; right: number | null }
  oak_last_update_age_s?: number | null
}

const VEHICLE_LABELS = new Set(['car', 'truck', 'bus', 'motorbike', 'motorcycle'])

function boxColor(label: string): string {
  if (label === 'person') return '#22c55e'
  if (VEHICLE_LABELS.has(label)) return '#f59e0b'
  return '#38bdf8'
}

function formatDistance(zMm: number): string {
  return `${(zMm / 1000).toFixed(2)} m`
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OakVision() {
  const conn = useSharedRobotConnection()
  const connected = conn.status === 'connected'
  const apiBase = getRobotApiUrl(conn.robotIp)
  const streamUrl = getRobotOakStreamUrl(conn.robotIp)

  const [status, setStatus] = useState<OakStatus>({})
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const streamRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setStreamUnavailable(false)
    setStreamKey(k => k + 1)
    if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
  }, [conn.robotIp, connected])

  useEffect(() => {
    if (!connected) {
      setStatus({})
      return
    }
    let disposed = false
    const poll = async () => {
      try {
        const response = await fetch(`${apiBase}/api/oak/status`)
        if (response.ok && !disposed) setStatus(await response.json())
      } catch {
        // silencieux — on retente au prochain tick
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 400)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [apiBase, connected])

  const detections = status.oak_detections ?? []
  const depthZones = status.oak_depth_zones
  const depthCm = status.oak_depth_cm

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <ScanEye size={20} className="text-blue-600 dark:text-blue-400" />
            Vision OAK-D
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Test exclusif de la caméra OAK-D — ce qu'elle voit, avec label et confiance
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            ok={status.oak_connected ?? false}
            label={status.oak_connected ? 'OAK connectée' : 'OAK déconnectée'}
          />
          {status.oak_usb_speed && (
            <span className="px-2.5 py-1 rounded-lg text-xs font-medium border border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300">
              USB {status.oak_usb_speed}
            </span>
          )}
        </div>
      </div>

      {status.oak_error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-400">
          <AlertCircle size={15} className="flex-shrink-0" />
          {status.oak_error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
        {/* Flux vidéo + overlay détections */}
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden dark:border-slate-800 dark:bg-slate-900/50">
          <div className="relative aspect-square bg-black">
            {connected ? (
              <img
                key={`${streamUrl}-${streamKey}`}
                src={streamUrl}
                alt="Flux OAK-D"
                className={`w-full h-full object-contain ${streamUnavailable ? 'hidden' : ''}`}
                onLoad={() => {
                  setStreamUnavailable(false)
                  if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
                }}
                onError={() => {
                  setStreamUnavailable(true)
                  if (streamRetryRef.current) clearTimeout(streamRetryRef.current)
                  streamRetryRef.current = setTimeout(() => {
                    setStreamUnavailable(false)
                    setStreamKey(k => k + 1)
                  }, 4000)
                }}
              />
            ) : null}

            {(!connected || streamUnavailable) && (
              <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm gap-2">
                <WifiOff size={16} />
                {connected ? 'Flux OAK indisponible…' : 'Robot non connecté'}
              </div>
            )}

            {!streamUnavailable && connected && detections.map((det, i) => (
              <div
                key={i}
                className="absolute border-2 pointer-events-none"
                style={{
                  left: `${Math.max(0, det.xmin) * 100}%`,
                  top: `${Math.max(0, det.ymin) * 100}%`,
                  width: `${Math.max(0, Math.min(1, det.xmax) - Math.max(0, det.xmin)) * 100}%`,
                  height: `${Math.max(0, Math.min(1, det.ymax) - Math.max(0, det.ymin)) * 100}%`,
                  borderColor: boxColor(det.label),
                }}
              >
                <span
                  className="absolute -top-5 left-0 px-1.5 py-0.5 text-[10px] font-semibold text-black rounded-t whitespace-nowrap"
                  style={{ background: boxColor(det.label) }}
                >
                  {det.label} · {Math.round(det.confidence * 100)}% · {formatDistance(det.z_mm)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Panneau détections + zones de profondeur */}
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/50">
            <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">
              Détections ({detections.length})
            </h2>
            {detections.length === 0 ? (
              <p className="text-sm text-slate-400 dark:text-slate-600">Rien de détecté</p>
            ) : (
              <ul className="space-y-1.5">
                {detections.map((det, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between text-sm px-2 py-1.5 rounded-lg bg-slate-50 dark:bg-slate-800/50"
                  >
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: boxColor(det.label) }} />
                      <span className="text-slate-700 dark:text-slate-200 capitalize">{det.label}</span>
                    </span>
                    <span className="text-slate-500 dark:text-slate-400 text-xs">
                      {Math.round(det.confidence * 100)}% · {formatDistance(det.z_mm)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/50">
            <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Radar size={13} />
              Zones de profondeur
            </h2>
            <div className="grid grid-cols-3 gap-2">
              {(['left', 'center', 'right'] as const).map(zone => (
                <div
                  key={zone}
                  className={`rounded-lg px-2 py-2 text-center border ${
                    depthZones?.[zone]
                      ? 'bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/30'
                      : 'bg-slate-50 border-slate-200 dark:bg-slate-800/50 dark:border-slate-700'
                  }`}
                >
                  <div className="text-[10px] uppercase text-slate-500 dark:text-slate-400">
                    {zone === 'left' ? 'Gauche' : zone === 'center' ? 'Centre' : 'Droite'}
                  </div>
                  <div className={`text-sm font-semibold ${depthZones?.[zone] ? 'text-red-600 dark:text-red-400' : 'text-slate-700 dark:text-slate-200'}`}>
                    {depthCm?.[zone] != null ? `${depthCm[zone]?.toFixed(0)} cm` : '—'}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
            Dernière mise à jour :{' '}
            {status.oak_last_update_age_s != null ? `il y a ${status.oak_last_update_age_s.toFixed(1)} s` : '—'}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border ${
        ok
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-600/15 dark:text-emerald-400 dark:border-emerald-600/30'
          : 'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700'
      }`}
    >
      {ok ? <Wifi size={12} /> : <WifiOff size={12} />}
      {label}
    </span>
  )
}
