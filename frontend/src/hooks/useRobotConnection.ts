import { useCallback, useEffect, useRef, useState } from 'react'
import { getRobotTransportWarning, getRobotWsUrl } from '../lib/robotTransport'

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
  patrol_state?: 'idle' | 'forward' | 'avoiding' | 'stuck'
  navigation_mode?: 'LIDAR_ONLY' | 'HYBRID' | 'LEGACY'
  esp32_connected?: boolean
  control_available?: boolean
  status_warning?: string
  lidar_connected?: boolean
  lidar_port?: string | null
  lidar_error?: string | null
  lidar_points?: Array<{ angle: number; distance_cm: number }>
  lidar_front_cm?: number | null
  lidar_left_cm?: number | null
  lidar_right_cm?: number | null
  lidar_obstacle_front?: boolean
  lidar_updated_at?: number
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
  startTracking: () => void
  stopTracking: () => void
  trackingActive: boolean
  personDetected: boolean
  obstacleBlocked: boolean
  lastStatus: RobotStatus | null
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
          obstacleTimerRef.current = setTimeout(() => setObstacleBlocked(false), 2000)
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

  const startTracking = useCallback(() => {
    send({ type: 'tracker', action: 'start' })
  }, [send])

  const stopTracking = useCallback(() => {
    send({ type: 'tracker', action: 'stop' })
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
    startTracking,
    stopTracking,
    trackingActive,
    personDetected,
    obstacleBlocked,
    lastStatus,
    latencyMs,
    errorMessage,
  }
}
