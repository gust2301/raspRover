import { useCallback, useEffect, useRef, useState } from 'react'
import { getRobotApiUrl, getRobotTransportWarning, getRobotWsUrl } from '../lib/robotTransport'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface RobotStatus {
  voltage?: number   // tension brute en V (depuis ESP32 T=130)
  battery?: number   // pourcentage calculé depuis voltage (0-100)
  speed_l?: number
  speed_r?: number
  pan?: number
  tilt?: number
  camera_light?: boolean
  distance_cm?: number | null
  obstacle?: boolean
  sensor_error?: string | null
  front_cm?: number | null
  rear_cm?: number | null
  obstacle_front?: boolean
  obstacle_rear?: boolean
  patrol_active?: boolean
  patrol_state?:
    | 'idle'
    | 'scanning'
    | 'forward'
    | 'avoiding'
    | 'turning_left'
    | 'turning_right'
    | 'backing_up'
    | 'stopped'
    | 'stuck'
  patrol_decision?: string
  patrol_decision_reason?: string
  navigation_mode?: 'LIDAR_ONLY' | 'HYBRID' | 'LEGACY'
  esp32_connected?: boolean
  control_available?: boolean
  status_warning?: string
  lidar_connected?: boolean
  lidar_port?: string | null
  lidar_error?: string | null
  lidar_points?: Array<{
    angle: number
    raw_angle?: number
    corrected_angle?: number
    zone?: 'front' | 'right' | 'rear' | 'left'
    distance_cm: number
  }>
  lidar_front_cm?: number | null
  lidar_left_cm?: number | null
  lidar_right_cm?: number | null
  lidar_rear_cm?: number | null
  lidar_obstacle_front?: boolean
  lidar_updated_at?: number
  lidar_angle_offset_deg?: number
  lidar_calibration?: LidarCalibration
  lidar_invert_angles?: boolean
  lidar_debug_points?: Array<{
    raw_angle: number
    corrected_angle: number
    zone: 'front' | 'right' | 'rear' | 'left'
    distance_cm: number
  }>
  tracker_active?: boolean
  tracking_person_detected?: boolean
  tracking_cx?: number | null
  tracking_cy?: number | null
  tracking_confidence?: number
  vision_obstacle?: boolean
  vision_left?: boolean
  vision_center?: boolean
  vision_right?: boolean
  vision_confidence?: number
  vision_available?: boolean
  vision_method?: 'canny' | 'uniform' | 'none'
  [key: string]: unknown
}

export interface LidarScanData {
  connected: boolean
  points: Array<{ angle_deg: number; distance_m: number; distance_cm: number }>
  range_min_m: number
  range_max_m: number
  updated_at: number | null
  error?: string | null
}

export interface LidarCalibration {
  angle_offset_deg: number
  invert_angles: boolean
  connected?: boolean
  port?: string | null
  error?: string | null
  zones?: {
    front?: number | null
    right?: number | null
    rear?: number | null
    left?: number | null
  }
  debug_points?: Array<{
    raw_angle: number
    corrected_angle: number
    zone: 'front' | 'right' | 'rear' | 'left'
    distance_cm: number
  }>
}

export interface RobotConnection {
  status: ConnectionStatus
  robotIp: string
  setRobotIp: (ip: string) => void
  connect: () => void
  disconnect: () => void
  sendMove: (direction: string, speed: number) => void
  sendMoveXY: (x: number, y: number) => void
  sendStop: () => void
  sendPanTilt: (pan: number, tilt: number) => void
  sendLight: (enabled: boolean) => void
  sendAlert: (onError?: (err: string) => void) => void
  stopAlert: () => void
  startPatrol: () => void
  stopPatrol: () => void
  adjustLidarOffset: (deltaDeg: number) => void
  toggleLidarInversion: () => void
  setLidarCalibration: (calibration: {
    angle_offset_deg?: number
    invert_angles?: boolean
    save?: boolean
  }) => Promise<LidarCalibration | null>
  refreshLidarCalibration: () => Promise<LidarCalibration | null>
  startTracking: () => void
  stopTracking: () => void
  clearObstacleBlock: () => void
  trackingActive: boolean
  personDetected: boolean
  obstacleBlocked: boolean
  lastStatus: RobotStatus | null
  lastScan: LidarScanData | null
  latencyMs: number | null
  errorMessage: string | null
}

const STORAGE_KEY = 'sentryx_robot_ip'
const DEFAULT_IP = 'https://rover.sopikeur.sn'

export function useRobotConnection(): RobotConnection {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [robotIp, setRobotIpState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? DEFAULT_IP
  )
  const [lastStatus, setLastStatus] = useState<RobotStatus | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [obstacleBlocked, setObstacleBlocked] = useState(false)
  const obstacleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [trackingActive, setTrackingActive] = useState(false)
  const [personDetected, setPersonDetected] = useState(false)
  const [lastScan, setLastScan] = useState<LidarScanData | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pingTsRef = useRef<number | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptRef = useRef(0)
  const shouldStayConnectedRef = useRef(false)
  const onAlertErrorRef = useRef<((err: string) => void) | null>(null)

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const setRobotIp = useCallback((ip: string) => {
    setRobotIpState(ip)
    localStorage.setItem(STORAGE_KEY, ip)
  }, [])

  const disconnect = useCallback(() => {
    shouldStayConnectedRef.current = false
    clearReconnectTimer()
    pingTsRef.current = null
    reconnectAttemptRef.current = 0
    wsRef.current?.close()
    wsRef.current = null
    setStatus('disconnected')
    setErrorMessage(null)
  }, [clearReconnectTimer])

  const connect = useCallback(() => {
    shouldStayConnectedRef.current = true
    clearReconnectTimer()
    pingTsRef.current = null
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setStatus('connecting')
    setErrorMessage(getRobotTransportWarning(robotIp))

    const ws = new WebSocket(getRobotWsUrl(robotIp))
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) return
      reconnectAttemptRef.current = 0
      setStatus('connected')
      setErrorMessage(null)
      // Demande un statut initial
      ws.send(JSON.stringify({ type: 'status' }))
    }

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return
      try {
        const data = JSON.parse(event.data as string) as Record<string, unknown>
        if (data.type === 'tracker_ack') {
          setTrackingActive(Boolean(data.tracker_active))
          setPersonDetected(Boolean(data.tracking_person_detected))
          setLastStatus(prev => prev ? { ...prev, ...data } : data as RobotStatus)
        } else if (data.type === 'status') {
          // Rétrocompatibilité : si le serveur Pi n'a pas encore _enrich_feedback,
          // il envoie 'v' brut (centivolts Waveshare, ex: 1134 = 11.34V) sans 'battery'.
          // Le JS officiel Waveshare fait data['v']/100 — on fait pareil ici.
          if (data.battery == null) {
            const rawV = data.v ?? data.voltage
            if (rawV != null) {
              const raw = Number(rawV)
              if (!isNaN(raw) && raw > 0) {
                // Centivolts si > 30, sinon déjà en volts
                const v = raw > 30 ? raw / 100 : raw
                data.battery = Math.max(0, Math.min(100, Math.round((v - 9.6) / 3.0 * 100)))
              }
            }
          }
          // Normalise 'v' (centivolts) → 'voltage' (volts) si absent
          if (data.voltage == null && data.v != null) {
            const raw = Number(data.v)
            data.voltage = raw > 30 ? raw / 100 : raw
          }
          if (data.tracker_active !== undefined) setTrackingActive(Boolean(data.tracker_active))
          if (data.tracking_person_detected !== undefined) setPersonDetected(Boolean(data.tracking_person_detected))
          setLastStatus(data as RobotStatus)
          if (pingTsRef.current !== null) {
            setLatencyMs(Date.now() - pingTsRef.current)
            pingTsRef.current = null
          }
        } else if (data.type === 'patrol_ack') {
          setLastStatus(prev => prev ? { ...prev, ...data } : data as RobotStatus)
        } else if (data.type === 'obstacle_blocked') {
          setObstacleBlocked(true)
          if (obstacleTimerRef.current) clearTimeout(obstacleTimerRef.current)
          obstacleTimerRef.current = setTimeout(() => setObstacleBlocked(false), 5000)
        } else if (data.type === 'obstacle_override_ack') {
          setObstacleBlocked(false)
          if (obstacleTimerRef.current) {
            clearTimeout(obstacleTimerRef.current)
            obstacleTimerRef.current = null
          }
        } else if (data.type === 'lidar_scan') {
          setLastScan(data as unknown as LidarScanData)
        } else if (data.type === 'alert_ack') {
          if (!data.ok && data.error) {
            console.warn('[SENTRYX] Audio error:', data.error)
            onAlertErrorRef.current?.(data.error as string)
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      if (wsRef.current !== ws) return
      setStatus('error')
      setErrorMessage(
        getRobotTransportWarning(robotIp) ?? 'Connexion WebSocket au robot impossible.'
      )
    }

    ws.onclose = () => {
      if (wsRef.current !== ws && wsRef.current !== null) return

      if (wsRef.current === ws) {
        wsRef.current = null
      }
      pingTsRef.current = null

      if (!shouldStayConnectedRef.current) {
        setStatus('disconnected')
        return
      }

      setStatus('connecting')
      setErrorMessage(
        getRobotTransportWarning(robotIp) ?? 'Connexion perdue, reconnexion automatique...'
      )

      const attempt = reconnectAttemptRef.current + 1
      reconnectAttemptRef.current = attempt
      const delayMs = Math.min(1000 * 2 ** Math.min(attempt - 1, 3), 8000)
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null
        if (shouldStayConnectedRef.current) {
          connect()
        }
      }, delayMs)
    }
  }, [clearReconnectTimer, robotIp])

  const send = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  const sendMove = useCallback((direction: string, speed: number) => {
    send({ type: 'move', direction, speed })
  }, [send])

  const sendMoveXY = useCallback((x: number, y: number) => {
    send({ type: 'move', x, y })
  }, [send])

  const sendStop = useCallback(() => {
    send({ type: 'stop' })
  }, [send])

  const sendPanTilt = useCallback((pan: number, tilt: number) => {
    send({ type: 'pantilt', pan, tilt })
  }, [send])

  const sendLight = useCallback((enabled: boolean) => {
    send({ type: 'light', enabled })
  }, [send])

  const sendAlert = useCallback((onError?: (err: string) => void) => {
    onAlertErrorRef.current = onError ?? null
    const wsReady = wsRef.current?.readyState === WebSocket.OPEN
    if (!wsReady) {
      onError?.('WebSocket non connecté — reconnecte-toi au robot')
      return
    }
    send({ type: 'alert', action: 'play' })
  }, [send])

  const stopAlert = useCallback(() => {
    send({ type: 'alert', action: 'stop' })
  }, [send])

  const startPatrol = useCallback(() => {
    send({ type: 'patrol', action: 'start' })
  }, [send])

  const stopPatrol = useCallback(() => {
    send({ type: 'patrol', action: 'stop' })
  }, [send])

  const applyLidarCalibrationState = useCallback((calibration: LidarCalibration) => {
    setLastStatus(prev => {
      const next = {
        ...(prev ?? {}),
        lidar_angle_offset_deg: calibration.angle_offset_deg,
        lidar_invert_angles: calibration.invert_angles,
        lidar_calibration: calibration,
      } as RobotStatus
      if (calibration.zones) {
        next.lidar_front_cm = calibration.zones.front
        next.lidar_right_cm = calibration.zones.right
        next.lidar_rear_cm = calibration.zones.rear
        next.lidar_left_cm = calibration.zones.left
      }
      if (calibration.debug_points) {
        next.lidar_debug_points = calibration.debug_points
      }
      return next
    })
  }, [])

  const setLidarCalibration = useCallback(async (calibration: {
    angle_offset_deg?: number
    invert_angles?: boolean
    save?: boolean
  }) => {
    try {
      const response = await fetch(`${getRobotApiUrl(robotIp)}/api/lidar/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(calibration),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json() as LidarCalibration & { ok?: boolean }
      applyLidarCalibrationState(data)
      send({ type: 'status' })
      return data
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Calibration LIDAR impossible')
      return null
    }
  }, [applyLidarCalibrationState, robotIp, send])

  const refreshLidarCalibration = useCallback(async () => {
    try {
      const response = await fetch(`${getRobotApiUrl(robotIp)}/api/lidar/calibration`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json() as LidarCalibration
      applyLidarCalibrationState(data)
      return data
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Lecture calibration LIDAR impossible')
      return null
    }
  }, [applyLidarCalibrationState, robotIp])

  const adjustLidarOffset = useCallback((deltaDeg: number) => {
    const current = Number(lastStatus?.lidar_angle_offset_deg ?? 0)
    void setLidarCalibration({ angle_offset_deg: (current + deltaDeg + 360) % 360 })
  }, [lastStatus?.lidar_angle_offset_deg, setLidarCalibration])

  const toggleLidarInversion = useCallback(() => {
    void setLidarCalibration({ invert_angles: !(lastStatus?.lidar_invert_angles ?? false) })
  }, [lastStatus?.lidar_invert_angles, setLidarCalibration])

  const startTracking = useCallback(() => {
    send({ type: 'tracker', action: 'start' })
  }, [send])

  const stopTracking = useCallback(() => {
    send({ type: 'tracker', action: 'stop' })
  }, [send])

  const clearObstacleBlock = useCallback(() => {
    setObstacleBlocked(false)
    if (obstacleTimerRef.current) {
      clearTimeout(obstacleTimerRef.current)
      obstacleTimerRef.current = null
    }
    send({ type: 'obstacle_override', seconds: 5 })
  }, [send])

  // Ping toutes les 3s pour mesurer la latence et récupérer le statut
  useEffect(() => {
    if (status !== 'connected') return
    const id = setInterval(() => {
      pingTsRef.current = Date.now()
      send({ type: 'status' })
    }, 3000)
    return () => clearInterval(id)
  }, [status, send])

  // HTTP fallback: poll /api/lidar/scan every 2s; WS updates override at 5 Hz when working
  useEffect(() => {
    if (status !== 'connected') return
    const poll = async () => {
      try {
        const res = await fetch(`${getRobotApiUrl(robotIp)}/api/lidar/scan`)
        const data = await res.json() as LidarScanData
        setLastScan(data)
      } catch {
        // network error — WS path will recover
      }
    }
    void poll()
    const id = setInterval(() => { void poll() }, 2000)
    return () => clearInterval(id)
  }, [status, robotIp])

  // Cleanup on unmount
  useEffect(() => () => {
    shouldStayConnectedRef.current = false
    clearReconnectTimer()
    wsRef.current?.close()
  }, [clearReconnectTimer])

  return {
    status,
    robotIp,
    setRobotIp,
    connect,
    disconnect,
    sendMove,
    sendMoveXY,
    sendStop,
    sendPanTilt,
    sendLight,
    sendAlert,
    stopAlert,
    startPatrol,
    stopPatrol,
    adjustLidarOffset,
    toggleLidarInversion,
    setLidarCalibration,
    refreshLidarCalibration,
    startTracking,
    stopTracking,
    clearObstacleBlock,
    trackingActive,
    personDetected,
    obstacleBlocked,
    lastStatus,
    lastScan,
    latencyMs,
    errorMessage,
  }
}
